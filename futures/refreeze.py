"""
futures/refreeze.py — HMM Re-freeze mechanism (GĐ3, anchored-expanding)
=========================================================================
Annual re-freeze pipeline for futures HMM labels:

  1. refreeze_hmm(anchor, fit_end)  — fit new model, produce labels, save metadata
  2. run_gate(labels_prev, labels_new) — 3-branch sensitivity gate
  3. run_verify(labels_new, ...)    — lightweight deploy_sim Calmar check
  4. apply_freeze(record)           — write to registry (the "swap" step)
  5. rollback()                     — restore previous freeze from registry

CONSTRAINTS (enforced structurally):
  - HMMEngine class is NEVER modified — only instantiated with parameters
  - futures/_validated_core.py label_regimes() is NEVER modified — called as-is
  - fit_C production is NEVER touched — apply_freeze writes to a separate registry;
    basket.py hmm_fit_end stays "2024-12-31" until the operator manually promotes
  - Swap is gated: gate must return AUTO_APPROVE (or VERIFY with operator consent)
    AND verify must return passed=True — otherwise rollback() is called automatically

Registry: models/hmm/futures_freeze_registry.json
  Stores: current freeze + last 3 freeze history for rollback
  Does NOT modify basket.py — operator reads registry and updates basket.py manually
  after reviewing the gate + verify report.

Run from D:\\raits:
    python -m futures.refreeze --fit-end 2025-12-31 --spy-csv spy_daily.csv \\
        --data-dir data\\cache\\futures \\
        --nkd-parquet global_index\\data\\NKD_continuous_1m_8y.parquet \\
        --regime-csv spy_daily.csv
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

REGISTRY_PATH   = Path("models/hmm/futures_freeze_registry.json")
REGISTRY_BACKUP = 3          # how many historical freeze records to keep

GATE_AUTO_PCT   = 5.0        # < 5%  → AUTO_APPROVE
GATE_HOLD_PCT   = 15.0       # > 15% → HOLD (also triggers on calm-flip)
CALM_FLIP_LIMIT = 10         # Calm→Stress or Calm→Normal > this → force VERIFY
# Catastrophe backstop ONLY -- the primary gate is the pair, see paired_verdict().
# 1.50 sits below the measured seed-noise minimum of 1.56 (five seeds of the identical
# system, 2026-08-15) so it can never fire on seed choice alone. Two of those five draws
# came in under the old live floor of 1.65, which is why an absolute threshold cannot be
# the primary gate. History: 2.38 was the fit_A floor measured 2026-07-02 at 1-tick on
# incremental data, deprecated by DECISIONS.md:128 four days after it was hardcoded here
# and never updated. See docs/futures/CALMAR_PROVENANCE.md.
CALMAR_FLOOR    = 1.50
# Paired tolerance. Not taste: fit_A floor / fit_C baseline = 1.65/1.72 = 95.9%
# (INVARIANTS.md line 23), i.e. a ~4.1% drop was already accepted. 5% is that, rounded.
PAIRED_TOL      = 0.05
PENDING_PATH    = Path("models/hmm/refreeze_pending.json")  # G3 fail-flag

# ── Pinned verify basis ───────────────────────────────────────────────────────
# run_verify shells out to deploy_sim with EXACTLY these, which is how
# BACKTEST_CALMAR_FLOOR = 1.65 and the $42,459/1.72 baseline were measured
# (runner.py:100-105, INVARIANTS.md line 22). Any change here silently changes what
# every future promotion is judged against — change the invariant doc in the same commit.
VERIFY_DATA_DIR       = "data/cache/futures/frozen_sim"
VERIFY_NKD_PARQUET    = "global_index/data/NKD_frozen_2024.parquet"
VERIFY_REGIME_CSV     = "spy_daily_live.csv"
VERIFY_END            = "2024-12-31"
VERIFY_TRAIN_END      = "2018-01-01"   # deploy_sim --hmm-train-end default
VERIFY_N_CONTRACTS    = 1
VERIFY_SLIPPAGE_TICKS = 2.0
VERIFY_INCLUDE_STRESS = False          # floor lineage 2.04→1.65 is no-stress (DECISIONS.md:36)

# deploy_sim's result line: "  net $42,459  |  Calmar 1.72  |  PF 1.48  |  Sharpe 1.67"
_VERIFY_METRIC_RE = re.compile(
    r"net \$([\d,\-]+)\s*\|\s*Calmar\s+([\d.\-]+)\s*\|\s*PF\s+([\d.\-]+)"
    r"\s*\|\s*Sharpe\s+([\d.\-]+)")
_VERIFY_MAXDD_RE = re.compile(r"MaxDD \$([\d,\-]+)")

COMMON_START    = "2019-01-01"   # start of gate comparison window


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class FreezeRecord:
    version:     str         # "futures_{fit_end}_{yyyymmdd_HHMMSS}"
    fit_end:     str         # "2024-12-31"
    anchor:      str         # "2017-01-01" (must match production: full spy_daily.csv start)
    n_components: int        # 3 (futures uses 3-state HMM)
    labels_hash: str         # SHA-256 of sorted labels for integrity check
    frozen_at:   str         # ISO datetime UTC
    calmar:      float       # Calmar ratio from verify step (0.0 if skipped)
    note:        str  = ""   # operator note
    invalid:     bool = False  # True → audit-only; rollback() skips this entry
    # The measurement basis `calmar` was produced on. Without it a recorded Calmar cannot be
    # reproduced or compared: the 2.744 in this registry (2026-07-06) is unrecoverable for
    # exactly this reason — see docs/futures/CALMAR_PROVENANCE.md §2.2. Empty on pre-2026-08-15
    # entries; from_dict() defaults it so those still load.
    calmar_basis: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FreezeRecord":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class GateResult:
    verdict:         str    # "AUTO_APPROVE" | "VERIFY" | "HOLD"
    pct_change:      float  # % label change on common window
    n_diff:          int
    n_common:        int
    flip_breakdown:  dict   # {"{from}->{to}": count}
    calm_flip_count: int    # Calm→{Stress,Normal} days (structural shift signal)
    reason:          str


@dataclass
class VerifyResult:
    passed:      bool
    calmar_new:  float
    calmar_floor: float
    net_new:     float
    detail:      str
    basis:       dict = field(default_factory=dict)   # what the number was measured on
    contaminated: bool = False   # True → eval window sits inside the fit window (I2.2)
    metrics_new:  dict = field(default_factory=dict)  # full deploy_sim metrics, new fit
    metrics_prev: dict = field(default_factory=dict)  # same for incumbent ({} if unpaired)
    checks:       dict = field(default_factory=dict)  # per-metric verdicts


@dataclass
class RefreezeReport:
    new_record:    Optional[FreezeRecord]   # None when pipeline fails at step 1
    gate:          Optional[GateResult]     # None when pipeline fails at step 1
    verify:        Optional[VerifyResult]
    swapped:       bool      # True if apply_freeze() was called
    rolled_back:   bool      # True if rollback() was called due to failure
    message:       str
    failed:        bool = False  # True if refreeze_hmm itself raised
    fail_type:     str  = ""     # "data_missing" | "unexpected" | ""


# ── Label utilities ───────────────────────────────────────────────────────────

def _labels_hash(labels: dict) -> str:
    """SHA-256 of sorted label series for integrity."""
    s = json.dumps({str(k): v for k, v in sorted(labels.items())}, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def _to_series(labels: dict) -> pd.Series:
    idx = pd.DatetimeIndex([pd.Timestamp(k).normalize() for k in labels])
    return pd.Series(list(labels.values()), index=idx).sort_index()


def _check_spy_coverage(spy: pd.Series, fit_end_ts: pd.Timestamp, csv_path) -> None:
    """G3: Abort re-freeze if SPY data does not reach fit_end.
    Prevents fitting the model on an incomplete date range — a partial fit would
    produce different label hashes than the operator expects and corrupts the gate.
    """
    last = spy.index.max()
    if last < fit_end_ts:
        from global_index.notify import notify
        msg = (
            f"G3 ABORT: spy_csv '{csv_path}' last date {last.date()} "
            f"< fit_end {fit_end_ts.date()}. "
            f"Cannot fit HMM on incomplete data — update spy_daily.csv to fit_end first."
        )
        notify("REFREEZE ABORTED", msg)
        log.error(msg)
        raise ValueError(msg)


# ── Pending-flag helpers (persistent alert for repeat failures) ───────────────

def _write_pending_flag(fit_end: str, fail_type: str, error: str,
                        pending_path: Path, attempts: int = 1) -> None:
    """Write flag file on re-freeze failure. Tracks attempt count for escalation."""
    pending_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "fail_type":      fail_type,   # "data_missing" | "unexpected"
        "fit_end_target": fit_end,
        "error":          error,
        "failed_at":      datetime.now(timezone.utc).isoformat(),
        "attempts":       attempts,
    }
    pending_path.write_text(json.dumps(data, indent=2))
    log.error("refreeze_pending flag written: fit_end=%s fail_type=%s attempts=%d",
              fit_end, fail_type, attempts)


def _clear_pending_flag(pending_path: Path) -> None:
    """Clear the pending flag after refreeze_hmm succeeds."""
    if pending_path.exists():
        pending_path.unlink()
        log.info("refreeze_pending flag cleared — re-freeze succeeded")


def _read_pending_flag(pending_path: Path) -> Optional[dict]:
    """Return pending flag dict or None if not set."""
    if not pending_path.exists():
        return None
    try:
        return json.loads(pending_path.read_text())
    except Exception:
        return None


def _alert_if_pending(pending_path: Path) -> int:
    """
    Re-notify if a prior failure flag exists. Called at the START of each pipeline run
    so the operator is reminded on EVERY attempt, not just the first failure.
    Returns prior attempt count (0 = no flag).
    """
    pending = _read_pending_flag(pending_path)
    if pending is None:
        return 0
    attempts  = pending.get("attempts", 1)
    target    = pending.get("fit_end_target", "?")
    fail_type = pending.get("fail_type", "unknown")
    error     = pending.get("error", "?")
    failed_at = pending.get("failed_at", "?")
    from global_index.notify import notify
    if fail_type == "data_missing":
        notify(
            "REFREEZE STILL PENDING",
            f"Re-freeze for fit_end={target} has failed {attempts} attempt(s). "
            f"Data still missing — update spy_daily.csv to cover {target}, then re-run. "
            f"Model UNCHANGED. First failed: {failed_at}.",
        )
    else:
        notify(
            "REFREEZE STILL PENDING CRITICAL",
            f"Re-freeze for fit_end={target} has failed {attempts} attempt(s) "
            f"with unexpected error. Investigate before retrying. "
            f"Model UNCHANGED. Error: {error}. First failed: {failed_at}.",
        )
    return attempts


# ── Core: refreeze_hmm ────────────────────────────────────────────────────────

def refreeze_hmm(
    anchor: str,
    fit_end: str,
    spy_csv: str,
    n_components: int = 3,
    train_end: str = "2018-01-01",
) -> tuple[FreezeRecord, dict]:
    """
    Fit anchored HMM from `anchor` to `fit_end`, produce labels from train_end onward.
    Returns (FreezeRecord, labels_dict). Does NOT write to registry — call apply_freeze().

    Mirrors exactly how fit_C was created via label_regimes():
        label_regimes(spy, train_end="2018-01-01", n_components=3, hmm_fit_end=fit_end)

    HMMEngine is instantiated with parameters — CLASS IS NOT MODIFIED.
    """
    from futures._validated_core import benchmark_daily, label_regimes

    spy      = benchmark_daily(spy_csv)
    fit_end_ts = pd.Timestamp(fit_end)
    _check_spy_coverage(spy, fit_end_ts, spy_csv)     # G3: abort if CSV < fit_end

    spy = spy[spy.index >= pd.Timestamp(anchor)]

    log.info("refreeze_hmm: fitting %s → %s (anchor=%s, n=%d)",
             train_end, fit_end, anchor, n_components)

    labels = label_regimes(spy, train_end, n_components, fit_end)

    now_utc = datetime.now(timezone.utc)
    version = f"futures_{fit_end.replace('-','')}_{now_utc.strftime('%Y%m%d_%H%M%S')}"
    record  = FreezeRecord(
        version=version,
        fit_end=fit_end,
        anchor=anchor,
        n_components=n_components,
        labels_hash=_labels_hash(labels),
        frozen_at=now_utc.isoformat(),
        calmar=0.0,
    )
    log.info("refreeze_hmm: fitted %d labels, hash=%s", len(labels), record.labels_hash)
    return record, labels


# ── Gate ─────────────────────────────────────────────────────────────────────

def run_gate(
    labels_prev: dict,
    labels_new:  dict,
    common_start: str  = COMMON_START,
    common_end:   str  = "",
    threshold_auto: float = GATE_AUTO_PCT,
    threshold_hold: float = GATE_HOLD_PCT,
    calm_flip_limit: int  = CALM_FLIP_LIMIT,
) -> GateResult:
    """
    Compare new labels to previous on the common window.
    3 branches:
      < threshold_auto%                           → AUTO_APPROVE
      threshold_auto–threshold_hold% or calm-flip → VERIFY  (needs operator review)
      > threshold_hold% or calm-flip > limit      → HOLD    (block swap)
    """
    sp = _to_series(labels_prev)
    sn = _to_series(labels_new)

    cs = pd.Timestamp(common_start)
    ce = pd.Timestamp(common_end) if common_end else min(sp.index.max(), sn.index.max())
    sp_win = sp[(sp.index >= cs) & (sp.index <= ce)]
    sn_win = sn[(sn.index >= cs) & (sn.index <= ce)]
    idx    = sp_win.index.intersection(sn_win.index)

    if len(idx) == 0:
        return GateResult(
            verdict="HOLD", pct_change=100.0, n_diff=0, n_common=0,
            flip_breakdown={}, calm_flip_count=0,
            reason="No common window between prev and new labels — cannot compare.")

    diff_mask = sp_win[idx] != sn_win[idx]
    n_diff    = int(diff_mask.sum())
    n_common  = len(idx)
    pct       = 100.0 * n_diff / n_common

    flips: dict[str, int] = {}
    calm_flip = 0
    if n_diff > 0:
        changed = idx[diff_mask]
        for d in changed:
            key = f"{sp_win[d]}->{sn_win[d]}"
            flips[key] = flips.get(key, 0) + 1
        calm_flip = sum(v for k, v in flips.items()
                        if k.startswith("Calm->"))

    if pct >= threshold_hold or calm_flip > calm_flip_limit:
        verdict = "HOLD"
        reason  = (f"{pct:.2f}% label change on common window meets/exceeds {threshold_hold}% hold threshold"
                   if pct >= threshold_hold else
                   f"Calm-flip count={calm_flip} exceeds limit={calm_flip_limit}")
    elif pct >= threshold_auto or calm_flip > 0:
        verdict = "VERIFY"
        reason  = (f"{pct:.2f}% label change requires operator review"
                   + (f"; {calm_flip} Calm→X flip(s) detected" if calm_flip else ""))
    else:
        verdict = "AUTO_APPROVE"
        reason  = f"{pct:.2f}% label change is within auto-approve threshold ({threshold_auto}%)"

    return GateResult(
        verdict=verdict, pct_change=pct, n_diff=n_diff, n_common=n_common,
        flip_breakdown=flips, calm_flip_count=calm_flip, reason=reason)


# ── Verify ────────────────────────────────────────────────────────────────────

def _deploy_sim_metrics(fit_end: str, data_dir: str, nkd_parquet: str,
                        regime_csv: str) -> tuple[Optional[dict], str]:
    """One deploy_sim run on the pinned basis. Returns (metrics, error_message)."""
    root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "global_index.deploy_sim",
           "--data-dir",       data_dir,
           "--nkd-parquet",    nkd_parquet,
           "--regime-csv",     regime_csv,
           "--end",            VERIFY_END,
           "--hmm-train-end",  VERIFY_TRAIN_END,
           "--hmm-fit-end",    fit_end,
           "--n-contracts",    str(VERIFY_N_CONTRACTS),
           "--slippage-ticks", str(VERIFY_SLIPPAGE_TICKS)]
    if VERIFY_INCLUDE_STRESS:
        cmd.append("--include-stress")

    # deploy_sim prints a character cp1252 cannot encode; on Windows a redirected stdout
    # kills the run with UnicodeEncodeError AFTER the full ~2m41s of work.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    log.info("deploy_sim fit_end=%s", fit_end)
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=3600)
    except Exception as exc:
        return None, f"deploy_sim failed to launch (fit_end={fit_end}): {exc}"
    if proc.returncode != 0:
        return None, (f"deploy_sim exited {proc.returncode} (fit_end={fit_end}): "
                      f"{(proc.stderr or proc.stdout or '')[-400:]}")

    m = _VERIFY_METRIC_RE.search(proc.stdout)
    d = _VERIFY_MAXDD_RE.search(proc.stdout)
    if not m or not d:
        return None, (f"could not parse DEPLOY METRICS (fit_end={fit_end}): "
                      + proc.stdout[-400:])
    return {
        "fit_end": fit_end,
        "net":     float(m.group(1).replace(",", "")),
        "calmar":  float(m.group(2)),
        "pf":      float(m.group(3)),
        "sharpe":  float(m.group(4)),
        "maxdd":   float(d.group(1).replace(",", "")),
        "command": " ".join(cmd[1:]),
    }, ""


def paired_verdict(m_new: dict, m_prev: Optional[dict],
                   calmar_floor: float = CALMAR_FLOOR,
                   tol: float = PAIRED_TOL) -> tuple[bool, str, dict]:
    """
    Decide promotion from measured metrics. Pure — no I/O, so it is testable without
    paying for two deploy_sim runs.

    Primary gate is the PAIR. Measured 2026-08-15 on five random seeds of the identical
    system: Calmar ranged 1.56–1.72 and 2 of 5 draws fell below the live floor of 1.65.
    An absolute threshold therefore cannot tell "the system degraded" from "the fit picked
    a different local optimum". A paired comparison can: both sides run the same basis and
    the same seed, so that variance is common-mode and cancels.

    Gated on three metrics, not one. In the same measurement Calmar spread 9.47% across
    seeds while PF spread 0.68% and Sharpe 2.42%. The reason is structural: Calmar has
    MaxDD in the denominator, a single day, which took only two distinct values across the
    five runs. PF and Sharpe average over every day. Calmar is the noisiest of the three
    and must not be the only vote.

    tol comes from an existing decision rather than taste: the fit_A floor over the fit_C
    baseline is 1.65/1.72 = 95.9% (INVARIANTS.md line 23), i.e. a ~4.1% drop was already
    accepted as tolerable. 5% is that, rounded out.

    calmar_floor is a CATASTROPHE BACKSTOP only, deliberately below the measured seed-noise
    minimum so it can never fire on seed choice alone.
    """
    checks: dict = {}
    ok = m_new["calmar"] >= calmar_floor
    checks["calmar_backstop"] = {
        "metric": "calmar", "value": m_new["calmar"], "threshold": calmar_floor,
        "passed": ok, "kind": "absolute backstop",
    }

    if m_prev is None:
        return ok, ("no previous freeze to pair against — absolute backstop only. "
                    "Weaker than a paired check; treat the result as provisional."), checks

    for k in ("calmar", "sharpe", "pf"):
        floor_k = m_prev[k] * (1.0 - tol)
        passed = m_new[k] >= floor_k
        checks["paired_" + k] = {
            "metric": k, "value": m_new[k], "prev": m_prev[k],
            "threshold": round(floor_k, 4), "passed": passed,
            "delta_pct": (round(100.0 * (m_new[k] - m_prev[k]) / m_prev[k], 2)
                          if m_prev[k] else None),
            "kind": "paired vs fit_end=" + str(m_prev["fit_end"]),
        }
        ok = ok and passed

    bad = [c for c in checks.values() if not c["passed"]]
    if bad:
        reason = "FAIL on " + ", ".join(c["metric"] for c in bad) + " — " + "; ".join(
            "{} {:.2f} < {:.2f}".format(c["metric"], c["value"], c["threshold"])
            for c in bad)
    else:
        reason = ("PASS — all three paired metrics within {:.0%} of fit_end={}, "
                  "and above the backstop").format(tol, m_prev["fit_end"])
    return ok, reason, checks


def run_verify(
    record:      FreezeRecord,
    labels_new:  dict,
    data_dir:    str = VERIFY_DATA_DIR,
    nkd_parquet: str = VERIFY_NKD_PARQUET,
    calmar_floor: float = CALMAR_FLOOR,
    verify_fn:   Optional[Callable] = None,
    regime_csv:  str = VERIFY_REGIME_CSV,
    fit_prev:    Optional[str] = None,
) -> VerifyResult:
    """
    Score the new fit against the incumbent, both measured on the pinned basis.

    Two things changed here on 2026-08-15, both driven by measurement.

    First, this function used to carry its own ~70-line copy of deploy_sim's pipeline, and
    the copy had drifted three ways: STRESS_MID always on (the floor lineage 2.04→1.65 is
    no-stress), no end-date clip (so the number moved daily as parquet appended), and
    data_dir taken from the caller (verify_current_freeze.py pointed it at the live cache).
    Three symptoms, one cause. It now shells out to deploy_sim, so the gate measures what
    INVARIANTS measures by construction. A separate process also rules out
    _validated_core._SWING_CACHE returning a previous run's result.

    Second, the gate is now PAIRED and votes on three metrics. See paired_verdict() for the
    measurements that forced both changes.

    Two guards run before the expensive part, both fail-closed:
      - the fit window must not swallow the evaluation window (ISSUES_LOG I2.2), checked
        first because it costs nothing;
      - the labels deploy_sim will build must hash-match labels_new, else the gate would
        score a different model than the one it gated.

    verify_fn: optional callable(labels_new) -> VerifyResult — inject for testing.
    Without it this costs two full deploy_sim runs (~2m41s each, measured 2026-08-15).
    """
    log.info("run_verify: version=%s fit_end=%s fit_prev=%s",
             record.version, record.fit_end, fit_prev)
    if verify_fn is not None:
        return verify_fn(labels_new)

    basis = {
        "data_dir":        data_dir,
        "nkd_parquet":     nkd_parquet,
        "regime_csv":      regime_csv,
        "end":             VERIFY_END,
        "train_end":       VERIFY_TRAIN_END,
        "hmm_fit_end":     record.fit_end,
        "fit_prev":        fit_prev,
        "n_contracts":     VERIFY_N_CONTRACTS,
        "slippage_ticks":  VERIFY_SLIPPAGE_TICKS,
        "include_stress":  VERIFY_INCLUDE_STRESS,
        "paired_tol":      PAIRED_TOL,
        "anchor_source":   "docs/futures/INVARIANTS.md line 22",
        "measured_at":     datetime.now(timezone.utc).isoformat(),
    }

    def _fail(detail: str, contaminated: bool = False) -> VerifyResult:
        return VerifyResult(passed=False, calmar_new=0.0, calmar_floor=calmar_floor,
                            net_new=0.0, detail=detail, basis=basis,
                            contaminated=contaminated)

    if data_dir != VERIFY_DATA_DIR:
        log.warning("run_verify: data_dir=%r is not the pinned frozen dir %r — the result "
                    "will not be comparable to the floor", data_dir, VERIFY_DATA_DIR)

    # ── Guard 1: evaluation window must not sit inside the fit window (I2.2) ────
    if pd.Timestamp(record.fit_end) > pd.Timestamp(VERIFY_END):
        return _fail(
            f"CONTAMINATED: fit_end={record.fit_end} is after the pinned evaluation end "
            f"{VERIFY_END}, so the model was fitted on the very period it is scored on. "
            f"ISSUES_LOG I2.2 measured this at +1.19 Calmar of pure MaxDD artifact. "
            f"Advance VERIFY_END (and re-derive the baseline on the new window) before "
            f"promoting a later fit — that is an operator decision, not a default.",
            contaminated=True)

    # ── Guard 2: deploy_sim must build the same labels this freeze is gating ────
    try:
        from futures._validated_core import benchmark_daily, label_regimes
        lbl_check = label_regimes(benchmark_daily(regime_csv), VERIFY_TRAIN_END,
                                  record.n_components, record.fit_end)
    except Exception as exc:
        return _fail(f"label consistency check failed to run: {exc}")

    h_gate, h_sim = _labels_hash(labels_new), _labels_hash(lbl_check)
    basis["labels_hash_gated"] = h_gate
    basis["labels_hash_deploy_sim"] = h_sim
    if h_gate != h_sim:
        return _fail(
            f"label mismatch: the gate compared labels {h_gate} but deploy_sim would build "
            f"{h_sim} from {regime_csv!r} (train_end={VERIFY_TRAIN_END}, "
            f"fit_end={record.fit_end}). Verify would score a different model than it gated. "
            f"Most likely cause: refreeze_hmm's anchor={record.anchor!r} clipped the CSV, "
            f"which deploy_sim does not do.")

    # ── Measure both sides on the same basis, same seed ─────────────────────────
    m_new, err = _deploy_sim_metrics(record.fit_end, data_dir, nkd_parquet, regime_csv)
    if m_new is None:
        return _fail(err)
    basis["command"] = m_new["command"]

    m_prev = None
    if fit_prev and fit_prev != record.fit_end:
        m_prev, err_prev = _deploy_sim_metrics(fit_prev, data_dir, nkd_parquet, regime_csv)
        if m_prev is None:
            return _fail("incumbent side of the pair failed to measure: " + err_prev)

    passed, reason, checks = paired_verdict(m_new, m_prev, calmar_floor, PAIRED_TOL)

    detail = ("{} | new fit_end={}: Calmar={:.2f} Sharpe={:.2f} PF={:.2f} net=${:,.0f}"
              .format("PASS" if passed else "FAIL", record.fit_end, m_new["calmar"],
                      m_new["sharpe"], m_new["pf"], m_new["net"]))
    if m_prev:
        detail += (" | prev fit_end={}: Calmar={:.2f} Sharpe={:.2f} PF={:.2f} net=${:,.0f}"
                   .format(m_prev["fit_end"], m_prev["calmar"], m_prev["sharpe"],
                           m_prev["pf"], m_prev["net"]))
    detail += " | " + reason

    return VerifyResult(passed=passed, calmar_new=m_new["calmar"],
                        calmar_floor=calmar_floor, net_new=m_new["net"],
                        detail=detail, basis=basis,
                        metrics_new=m_new, metrics_prev=(m_prev or {}), checks=checks)


# ── Registry (swap + rollback) ────────────────────────────────────────────────

def _load_registry(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"current": None, "history": []}


def _save_registry(reg: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


def apply_freeze(record: FreezeRecord,
                 registry_path: Path = REGISTRY_PATH) -> None:
    """
    Write record as current freeze to registry. This is the 'swap' step.
    Does NOT modify basket.py — operator must update hmm_fit_end manually
    after reviewing the RefreezeReport.
    """
    reg = _load_registry(registry_path)
    if reg["current"] is not None:
        reg["history"].insert(0, reg["current"])
        reg["history"] = reg["history"][:REGISTRY_BACKUP]
    reg["current"] = record.to_dict()
    _save_registry(reg, registry_path)
    log.info("apply_freeze: swapped to version=%s fit_end=%s",
             record.version, record.fit_end)


def rollback(registry_path: Path = REGISTRY_PATH) -> Optional[FreezeRecord]:
    """
    Restore previous freeze from registry history.
    Skips entries marked invalid=True (audit-only; not eligible for restore).
    Returns the restored record, or None if no valid history exists.
    """
    reg = _load_registry(registry_path)
    valid_idx = next(
        (i for i, e in enumerate(reg["history"]) if not e.get("invalid", False)),
        None,
    )
    if valid_idx is None:
        log.warning("rollback: no valid history to restore")
        return None
    prev = reg["history"].pop(valid_idx)
    reg["current"] = prev
    _save_registry(reg, registry_path)
    restored = FreezeRecord.from_dict(prev)
    log.warning("rollback: restored version=%s fit_end=%s",
                restored.version, restored.fit_end)
    return restored


def current_freeze(registry_path: Path = REGISTRY_PATH) -> Optional[FreezeRecord]:
    """Return the current production freeze record, or None if registry is empty."""
    reg = _load_registry(registry_path)
    if reg["current"] is None:
        return None
    return FreezeRecord.from_dict(reg["current"])


# ── Full pipeline ─────────────────────────────────────────────────────────────

def run_refreeze_pipeline(
    anchor:      str,
    fit_end:     str,
    spy_csv:     str,
    data_dir:    str,
    nkd_parquet: str,
    regime_csv:  str,
    registry_path: Path = REGISTRY_PATH,
    pending_path:  Path = PENDING_PATH,
    calmar_floor: float = CALMAR_FLOOR,
    verify_fn:   Optional[Callable] = None,
    operator_consent_verify: bool = False,
) -> RefreezeReport:
    """
    Full re-freeze pipeline:
      0. Re-alert if a prior failure flag exists (persistent operator alert)
      1. refreeze_hmm → new labels + record  [wrapped: fail → keep old model + alert]
      2. run_gate vs current freeze (or skip gate if no current)
      3. run_verify if gate == AUTO_APPROVE (or VERIFY + operator consent)
      4. apply_freeze if verify passed  [clears pending flag on success]
      5. rollback if verify failed (auto)

    operator_consent_verify: set True when operator has reviewed VERIFY-grade gate
    and explicitly approves proceeding to the verify step.

    On refreeze_hmm failure the pipeline returns early (failed=True) without raising.
    The pending flag is written so every subsequent pipeline call re-alerts the operator
    until the data issue is fixed and a run succeeds.
    """
    from global_index.notify import notify as _notify

    # Step 0: re-alert if previous failure is still unresolved
    prev_attempts = _alert_if_pending(pending_path)

    # Step 1: new labels — wrapped so a bad CSV never crashes the runner
    cur = current_freeze(registry_path)
    old_fit_end = cur.fit_end if cur else "none"
    try:
        new_record, new_labels = refreeze_hmm(anchor, fit_end, spy_csv)
    except ValueError as e:
        # G3 or malformed data — recoverable: fix CSV and retry
        attempts = prev_attempts + 1
        _write_pending_flag(fit_end, "data_missing", str(e), pending_path, attempts)
        _notify(
            "REFREEZE FAILED",
            f"Re-freeze for fit_end={fit_end} FAILED (attempt {attempts}). "
            f"Cause: {e} "
            f"Model UNCHANGED — current fit_end={old_fit_end}. "
            f"Fix: update spy_daily.csv to cover {fit_end}, then re-run.",
        )
        return RefreezeReport(
            new_record=None, gate=None, verify=None,
            swapped=False, rolled_back=False,
            message=f"FAILED (data_missing attempt={attempts}): {e}",
            failed=True, fail_type="data_missing",
        )
    except Exception as e:
        # Unexpected failure (fit crash, corrupt data, etc.) — needs investigation
        attempts = prev_attempts + 1
        _write_pending_flag(fit_end, "unexpected", str(e), pending_path, attempts)
        _notify(
            "REFREEZE FAILED CRITICAL",
            f"Re-freeze for fit_end={fit_end} FAILED UNEXPECTEDLY (attempt {attempts}). "
            f"Error: {e} "
            f"Model UNCHANGED — current fit_end={old_fit_end}. Investigate immediately.",
        )
        log.exception("refreeze_hmm unexpected failure: fit_end=%s", fit_end)
        return RefreezeReport(
            new_record=None, gate=None, verify=None,
            swapped=False, rolled_back=False,
            message=f"FAILED (unexpected attempt={attempts}): {e}",
            failed=True, fail_type="unexpected",
        )

    # refreeze_hmm succeeded — clear any pending flag
    _clear_pending_flag(pending_path)

    # Step 2: gate (cur already fetched in step 1 for error message)
    if cur is not None:
        _, cur_labels = refreeze_hmm(anchor, cur.fit_end, spy_csv)
        gate = run_gate(cur_labels, new_labels)
    else:
        gate = GateResult(
            verdict="AUTO_APPROVE", pct_change=0.0, n_diff=0, n_common=0,
            flip_breakdown={}, calm_flip_count=0,
            reason="No previous freeze — first-time freeze, auto-approve.")

    # Step 3 + 4 + 5: verify and swap
    verify: Optional[VerifyResult] = None
    swapped      = False
    rolled_back  = False
    message      = ""

    if gate.verdict == "HOLD":
        message = f"HOLD: {gate.reason}. Review flip breakdown before proceeding."

    elif gate.verdict in ("AUTO_APPROVE",
                          "VERIFY" if operator_consent_verify else ""):
        # regime_csv was accepted by this pipeline and then dropped on the floor until
        # 2026-08-15 — run_verify now needs it, so the parameter finally does something.
        verify = run_verify(new_record, new_labels, data_dir, nkd_parquet,
                            calmar_floor=calmar_floor, verify_fn=verify_fn,
                            regime_csv=regime_csv,
                            fit_prev=(cur.fit_end if cur else None))
        new_record = FreezeRecord(**{**asdict(new_record),
                                     "calmar": verify.calmar_new,
                                     "calmar_basis": verify.basis})

        if verify.passed:
            apply_freeze(new_record, registry_path)
            swapped = True
            message = (f"SWAPPED: version={new_record.version} fit_end={fit_end} "
                       f"Calmar={verify.calmar_new:.2f}")
        else:
            # Auto-rollback
            restored = rollback(registry_path)
            rolled_back = True
            message = (f"ROLLBACK: verify failed ({verify.detail}). "
                       + (f"Restored to {restored.fit_end}." if restored else
                          "No prior freeze to restore."))

    elif gate.verdict == "VERIFY":
        message = (f"VERIFY required: {gate.reason}. "
                   f"Re-run with operator_consent_verify=True to proceed.")

    return RefreezeReport(
        new_record=new_record, gate=gate, verify=verify,
        swapped=swapped, rolled_back=rolled_back, message=message)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_report(r: RefreezeReport) -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if r.failed:
        print("=" * 68)
        print(f"REFREEZE REPORT — FAILED (fail_type={r.fail_type})")
        print("=" * 68)
        print(f"\nOUTCOME: {r.message}")
        print("=" * 68)
        return
    g = r.gate
    print("=" * 68)
    print(f"REFREEZE REPORT — fit_end={r.new_record.fit_end}")
    print("=" * 68)
    print(f"\nGATE: {g.verdict}  ({g.pct_change:.2f}% change on {g.n_common} common days)")
    if g.flip_breakdown:
        print("  Flip breakdown:")
        for k, v in sorted(g.flip_breakdown.items(), key=lambda x: -x[1]):
            print(f"    {k}: {v} days")
    print(f"  Calm-flips: {g.calm_flip_count}  |  Reason: {g.reason}")
    if r.verify:
        v = r.verify
        print(f"\nVERIFY: {'PASS' if v.passed else 'FAIL'}")
        if v.contaminated:
            print("  ⚠️ CONTAMINATED — the number below is in-sample; do not promote on it.")
        if v.metrics_new:
            print(f"  {'':<16} {'Calmar':>8} {'Sharpe':>8} {'PF':>7} "
                  f"{'net $':>11} {'MaxDD $':>9}")
            for tag, mm in (("new ", v.metrics_new), ("prev", v.metrics_prev)):
                if mm:
                    print(f"  {tag + ' ' + str(mm['fit_end']):<16} {mm['calmar']:>8.2f} "
                          f"{mm['sharpe']:>8.2f} {mm['pf']:>7.2f} {mm['net']:>11,.0f} "
                          f"{mm['maxdd']:>9,.0f}")
        for name, c in v.checks.items():
            print(f"    [{'ok  ' if c['passed'] else 'FAIL'}] {name:<18} "
                  f"{c['value']:.2f} vs {c['threshold']:.2f}  ({c['kind']})")
        print(f"  {v.detail}")
        if v.basis:
            print("  measured on:")
            for k in ("data_dir", "regime_csv", "end", "n_contracts", "slippage_ticks",
                      "include_stress", "paired_tol"):
                if k in v.basis:
                    print(f"    {k:<16} {v.basis[k]}")
            if "command" in v.basis:
                print(f"    command          {v.basis['command']}")
    print(f"\nOUTCOME: {r.message}")
    print("=" * 68)
    if r.swapped:
        print("\nNEXT STEP: update futures/basket.py hmm_fit_end to:", r.new_record.fit_end)
        print("           then re-run full reconcile chain to confirm baseline.")


if __name__ == "__main__":
    import argparse, sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="RAITS futures HMM re-freeze pipeline")
    ap.add_argument("--anchor",     default="2017-01-01")
    ap.add_argument("--fit-end",    required=True)
    ap.add_argument("--spy-csv",    default="spy_daily.csv")
    ap.add_argument("--data-dir",   required=True)
    ap.add_argument("--nkd-parquet", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--consent-verify", action="store_true",
                    help="Operator consent for VERIFY-grade gate to proceed")
    ap.add_argument("--registry",   default=str(REGISTRY_PATH))
    a = ap.parse_args()

    report = run_refreeze_pipeline(
        anchor=a.anchor, fit_end=a.fit_end,
        spy_csv=a.spy_csv, data_dir=a.data_dir,
        nkd_parquet=a.nkd_parquet, regime_csv=a.regime_csv,
        registry_path=Path(a.registry),
        operator_consent_verify=a.consent_verify,
    )
    _print_report(report)
    sys.exit(0 if report.swapped else 1)
