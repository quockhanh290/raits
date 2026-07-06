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
from dataclasses import asdict, dataclass
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
CALMAR_FLOOR    = 2.38       # degradation floor from fit_A; do not promote below this
PENDING_PATH    = Path("models/hmm/refreeze_pending.json")  # G3 fail-flag

COMMON_START    = "2019-01-01"   # start of gate comparison window


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class FreezeRecord:
    version:     str         # "futures_{fit_end}_{yyyymmdd_HHMMSS}"
    fit_end:     str         # "2024-12-31"
    anchor:      str         # "2018-01-01"
    n_components: int        # 3 (futures uses 3-state HMM)
    labels_hash: str         # SHA-256 of sorted labels for integrity check
    frozen_at:   str         # ISO datetime UTC
    calmar:      float       # Calmar ratio from verify step (0.0 if skipped)
    note:        str = ""    # operator note

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

def run_verify(
    record:      FreezeRecord,
    labels_new:  dict,
    data_dir:    str,
    nkd_parquet: str,
    calmar_floor: float = CALMAR_FLOOR,
    verify_fn:   Optional[Callable] = None,
) -> VerifyResult:
    """
    Lightweight deploy_sim Calmar check with new labels.
    verify_fn: optional callable(labels_new) -> VerifyResult — inject for testing.
    If None, runs full deploy_sim replay (expensive, ~3 min).
    """
    log.info("run_verify: version=%s fit_end=%s", record.version, record.fit_end)
    if verify_fn is not None:
        return verify_fn(labels_new)

    # Full verify: run deploy_sim.replay programmatically
    try:
        import numpy as np
        from pathlib import Path as P
        from futures.basket import BASKET, REGIME, RISK, SWING_TF_PARAM, data_filename
        from futures.swing_tf import SwingTFEngine, costs_for_basket
        from futures.stress_mid import StressMidEngine
        from futures.circuit_breaker import CircuitBreaker
        from futures._validated_core import load_parquet, daily_atr_series
        from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
        from global_index import specs as gi_specs
        from global_index.regime import RegimeLabels
        from global_index.net_exposure_multi import MultiClusterGuard
        from global_index.signal_layer import CLUSTER_SWING, CLUSTER_STRESS, CLUSTER_NKD, ROSKA4_MULT, NKD_MULT
        from global_index.deploy_sim import replay as deploy_replay, metrics

        ACCOUNT  = float(RISK["account"])
        SLIPPAGE = 2.0
        NKD_INST = "MNKD"
        NKD_EMA  = 10

        dfs   = {n: load_parquet(str(P(data_dir) / data_filename(c))) for n, c in BASKET.items()}
        c_nkd = gi_specs.SPECS[NKD_INST]
        ndf   = gi_load(nkd_parquet)
        ndf.index = ndf.index.tz_convert(c_nkd.session_tz)

        # Convert new labels to RegimeLabels
        lbl_s     = pd.Series(labels_new).sort_index()
        lbl_s.index = (pd.DatetimeIndex(lbl_s.index)
                       .tz_localize(None).normalize())
        nkd_labels = RegimeLabels(lbl_s, lag_days=1)

        costs_2t  = costs_for_basket(slippage_ticks=SLIPPAGE)
        swing_bt  = SwingTFEngine().backtest_basket(dfs, labels_new, costs_2t)
        ncost_2t  = GIFC(point_value=c_nkd.point_value, tick=c_nkd.tick,
                         commission_rt=c_nkd.commission_rt,
                         slippage_ticks_per_side=SLIPPAGE)
        nkd_bt    = __import__("futures._validated_core", fromlist=["backtest_swing_tf"]
                                ).backtest_swing_tf(
            ndf, nkd_labels, ncost_2t, ema_period=NKD_EMA,
            chandelier_atr_mult=NKD_MULT, max_hold_days=5, gap_fill=True)
        stress_bt = StressMidEngine().backtest_basket(dfs, labels_new, costs_2t)

        atr_swing = {n: daily_atr_series(df) for n, df in dfs.items()}
        atr_nkd   = daily_atr_series(ndf)
        pv        = {n: c.point_value for n, c in BASKET.items()}
        pv[NKD_INST] = c_nkd.point_value

        def _rr(atr_s, mult, pv_, ed, n):
            try:
                av = atr_s.asof(pd.Timestamp(ed))
            except Exception:
                av = float(atr_s.median())
            if av is None or (isinstance(av, float) and pd.isna(av)):
                av = float(atr_s.median())
            return n * mult * float(av) * pv_

        all_tr = []
        for inst, lst in swing_bt.items():
            for t in lst:
                all_tr.append(dict(inst=inst, cluster=CLUSTER_SWING,
                    entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                    direction=t["direction"],
                    risk_sized=_rr(atr_swing[inst], ROSKA4_MULT, pv[inst], t["day"], 1),
                    pnl_sized=t["pnl"]))
        for inst, lst in stress_bt.items():
            for t in lst:
                all_tr.append(dict(inst=inst, cluster=CLUSTER_STRESS,
                    entry=pd.Timestamp(t["day"]), exit=pd.Timestamp(t["exit_day"]),
                    direction=t["direction"],
                    risk_sized=_rr(atr_swing[inst], ROSKA4_MULT, pv[inst], t["day"], 1),
                    pnl_sized=t["pnl"]))
        for t in nkd_bt:
            ed = pd.Timestamp(t["day"]).tz_localize(None)
            xd = pd.Timestamp(t["exit_day"]).tz_localize(None) if t.get("exit_day") else ed
            all_tr.append(dict(inst=NKD_INST, cluster=CLUSTER_NKD,
                entry=ed, exit=xd, direction=t["direction"],
                risk_sized=_rr(atr_nkd, NKD_MULT, pv[NKD_INST], ed, 1),
                pnl_sized=t["pnl"]))

        cb    = {n: 1 for n in list(BASKET) + [NKD_INST]}
        daily, _ = deploy_replay(all_tr, ACCOUNT, MultiClusterGuard(account=ACCOUNT), cb, None)
        m     = metrics(daily)
        calmar_new = m.get("calmar", 0.0)
        net_new    = float(daily.sum())
        passed     = calmar_new >= calmar_floor
        detail     = (f"Calmar={calmar_new:.2f} net=${net_new:,.0f} "
                      f"{'PASS' if passed else f'FAIL (floor={calmar_floor})'}")
        return VerifyResult(passed=passed, calmar_new=calmar_new,
                            calmar_floor=calmar_floor, net_new=net_new, detail=detail)

    except Exception as exc:
        return VerifyResult(passed=False, calmar_new=0.0, calmar_floor=calmar_floor,
                            net_new=0.0, detail=f"verify exception: {exc}")


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
    Returns the restored record, or None if no history.
    """
    reg = _load_registry(registry_path)
    if not reg["history"]:
        log.warning("rollback: no history to restore")
        return None
    prev = reg["history"].pop(0)
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
        verify = run_verify(new_record, new_labels, data_dir, nkd_parquet,
                            calmar_floor=calmar_floor, verify_fn=verify_fn)
        new_record = FreezeRecord(**{**asdict(new_record), "calmar": verify.calmar_new})

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
        print(f"\nVERIFY: {'PASS' if v.passed else 'FAIL'}  {v.detail}")
    print(f"\nOUTCOME: {r.message}")
    print("=" * 68)
    if r.swapped:
        print("\nNEXT STEP: update futures/basket.py hmm_fit_end to:", r.new_record.fit_end)
        print("           then re-run full reconcile chain to confirm baseline.")


if __name__ == "__main__":
    import argparse, sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="RAITS futures HMM re-freeze pipeline")
    ap.add_argument("--anchor",     default="2018-01-01")
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
