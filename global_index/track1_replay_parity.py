"""Did the live slot decide what the code decides? A read-only comparison.

The dashboard can show that evidence exists. This asks a different question: replay the same
decision from the recorded context and check the answer matches. It reads; it never writes, never
connects to a broker, never touches a gate, and never marks anything satisfied.

The four verdicts, and the one rule that matters
------------------------------------------------
    PASS               replay reproduced the live decision on every comparable field
    FAIL               replay and live disagree on a field that was comparable
    UNKNOWN            evidence missing, or the context cannot be reconstructed
    NOT_YET_OBSERVED   no live slot has run since the fixes this parity is about

**UNKNOWN never becomes PASS.** A slot whose params hash was not recorded is not a slot that
matched; it is a slot that cannot be checked, and those are different facts about the route.

`NOT_YET_OBSERVED` is likewise not a soft PASS. It is the answer when the code changed after the
last session ran, which is exactly the situation this module was written in.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA = "track1_replay_parity/1"
ROUTE = "track1_candidate"

PASS, FAIL, UNKNOWN, NOT_YET = "PASS", "FAIL", "UNKNOWN", "NOT_YET_OBSERVED"

#: Stage 5ZZZ-Q. Two more, so an old row is described rather than judged by rules it predates.
#:
#:   PRE_FIX_MISMATCH   the row disagrees with today's code, and it was written by yesterday's.
#:                      A real difference, and not a fault of the slot that wrote it.
#:   NOT_APPLICABLE     the field did not exist when the row was written.
#:
#: Neither is a PASS, and old runtime evidence is never rewritten to make it one.
PRE_FIX_MISMATCH, NOT_APPLICABLE = "PRE_FIX_MISMATCH", "NOT_APPLICABLE"

#: The runtime files whose changes this parity is about. A live slot that ran BEFORE the newest
#: of these did not exercise the path being checked, however well it matches.
FIX_FILES = (
    "global_index/track1_normal_r4.py",
    "global_index/track1_live_source.py",
    "global_index/track1_strategy_diagnostics.py",
    "global_index/run_live_day_track1.py",
)

SLEEVES = ("global_nkd", "roska4_stress", "roska4_calm", "roska4_swing")

#: Where each sleeve's live decision is recorded.
SIGNALS_DIR = ("global_index", "track1_runtime", "signals")
INTENT_DIR = ("global_index", "track1_runtime", "shadow_intent")
DIAG_DIR = ("global_index", "track1_runtime", "strategy_diagnostics")


@dataclass
class FieldCheck:
    name: str
    live: object = None
    replay: object = None
    verdict: str = UNKNOWN
    note: str = ""


@dataclass
class SlotParity:
    sleeve: str
    session_date: str
    slot_id: str = ""
    slot_time: str = ""
    verdict: str = UNKNOWN
    reason: str = ""
    live_ran_at: str = ""
    post_fix: bool = False
    checks: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["checks"] = [asdict(c) if not isinstance(c, dict) else c for c in self.checks]
        return d


def fix_cutoff(root: str | Path = ".") -> dict:
    """The newest mtime among the files this parity is about, as an ISO string."""
    import datetime as _dt

    stamps = {}
    for rel in FIX_FILES:
        p = Path(root) / rel
        if p.exists():
            stamps[rel] = _dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(
                timespec="seconds")
    newest = max(stamps.values()) if stamps else ""
    return {"per_file": stamps, "cutoff": newest}


def _read_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:                                      # noqa: BLE001
                continue
    return out


def live_rows(root: str | Path = ".", day: str | None = None) -> list:
    """Every recorded live signal row, newest file first when no day is given."""
    d = Path(root).joinpath(*SIGNALS_DIR)
    files = sorted(d.glob("track1_signals_*.jsonl"))
    if day:
        files = [f for f in files if day.replace("-", "") in f.name]
    rows = []
    for f in files:
        stamp = ""
        try:
            import datetime as _dt

            stamp = _dt.datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds")
        except Exception:                                          # noqa: BLE001
            pass
        for r in _read_jsonl(f):
            r["_file"] = f.name
            r["_file_mtime"] = stamp
            rows.append(r)
    return rows


def newest_slot(root: str | Path = ".", sleeve: str = "") -> dict | None:
    rows = [r for r in live_rows(root) if r.get("sleeve") == sleeve]
    if not rows:
        return None
    return sorted(rows, key=lambda r: (str(r.get("session_date")),
                                       str(r.get("slot_time"))))[-1]


def _check(name, live, rep, *, comparable=True, note="", norm=None) -> FieldCheck:
    if not comparable or live in (None, "") or rep in (None, ""):
        return FieldCheck(name, live, rep, UNKNOWN,
                          note or "not recorded live, or not reconstructable")
    a, b = (norm(live), norm(rep)) if norm else (str(live), str(rep))
    return FieldCheck(name, live, rep, PASS if a == b else FAIL, note)


def _basename(v) -> str:
    """Compare data identity on the FILE, not on how each side spells the path.

    Measured: the live row records `global_index/data/NKD_continuous_1m_8y.parquet` while the
    reconstruction records `NKD_continuous_1m_8y.parquet`. Those are the same file, and a naive
    string comparison reports a mismatch that is really a reporting inconsistency. A false FAIL
    is worse than an honest UNKNOWN, because someone acts on it. The inconsistency itself is
    reported separately as an evidence-format gap rather than hidden by this helper.
    """
    return Path(str(v)).name


def replay_slot(root: str | Path, row: dict) -> dict:
    """Reconstruct the decision context and re-run the same detector. Read-only.

    Reuses the market view's reconstruction, which Stages 5ZZZ-B and 5ZZZ-G established mirrors
    the live call sites exactly - same parameters, same labels object, same detector. Writing a
    second reconstruction here would be a second implementation, and the whole point of a parity
    check is that both sides come from one.
    """
    sleeve = row.get("sleeve")
    day = row.get("session_date")
    out = {"reconstructable": False, "reason": "", "sleeve": sleeve, "session_date": day}
    try:
        from monitor.backend import track1_market_view as mv

        if sleeve in ("global_nkd", "roska4_swing"):
            spec = mv.SLEEVES[sleeve]
            st = mv._strategy(Path(root), sleeve, day, spec, now=None)
            diag = st.get("diagnostics") or {}
            gates = {g.get("gate"): g for g in (diag.get("gates") or [])}
            out.update({
                "reconstructable": True,
                "instrument": spec["instrument"],
                "status": st.get("status"),
                "detail": st.get("detail"),
                "regime_label": (gates.get("regime") or {}).get("value"),
                "regime_basis": diag.get("regime_basis"),
                "data_source_identity": diag.get("data_source_identity"),
                "diagnostics_source": diag.get("diagnostics_source"),
                "nearest_failed": (diag.get("nearest_failed_condition") or {}).get("label")
                if isinstance(diag.get("nearest_failed_condition"), dict) else None,
            })
        elif sleeve == "roska4_stress":
            spec = mv.SLEEVES[sleeve]
            st = mv._strategy(Path(root), sleeve, day, spec, now=None)
            out.update({
                "reconstructable": True, "instrument": spec["instrument"],
                "status": st.get("status"), "detail": st.get("detail"),
                "first_failed": (st.get("first_failed") or {}).get("label")
                if isinstance(st.get("first_failed"), dict) else st.get("first_failed"),
                "decided_at_et": st.get("decided_at_et"),
                "diagnostics_source": st.get("diagnostics_source"),
            })
        elif sleeve == "roska4_calm":
            from global_index import track1_strategy_diagnostics as sd

            phases = sd.calm_blocks(Path(root), day)
            out.update({
                "reconstructable": True, "instrument": "MES/MNQ",
                "phases": {k: {"status": v.get("status"),
                               "reason_code": v.get("reason_code"),
                               "diagnostics_source": v.get("diagnostics_source"),
                               "price_levels": len(v.get("price_levels") or []),
                               "rows": [r.get("label") for r in (v.get("rows") or [])]}
                           for k, v in phases.items()},
            })
        else:
            out["reason"] = f"no replay path for sleeve {sleeve!r}"
    except Exception as exc:                                       # noqa: BLE001
        out["reason"] = f"{type(exc).__name__}: {exc}"
    return out


def compare_slot(root: str | Path, row: dict, cutoff: str) -> SlotParity:
    """One slot, live against replay. Never upgrades a missing field to a match."""
    sp = SlotParity(sleeve=row.get("sleeve", ""), session_date=str(row.get("session_date")),
                    slot_id=str(row.get("slot_id") or ""),
                    slot_time=str(row.get("slot_time") or ""),
                    live_ran_at=str(row.get("_file_mtime") or ""))
    sp.post_fix = bool(cutoff and sp.live_ran_at and sp.live_ran_at >= cutoff)

    rep = replay_slot(root, row)
    if not rep.get("reconstructable"):
        sp.verdict = UNKNOWN
        sp.reason = rep.get("reason") or "the decision context could not be reconstructed"
        return sp

    checks = [
        _check("route", row.get("route") or ROUTE, ROUTE),
        _check("sleeve", row.get("sleeve"), rep.get("sleeve")),
        _check("session_date", row.get("session_date"), rep.get("session_date")),
        _check("data_source_identity", row.get("data_source_identity"),
               rep.get("data_source_identity"), norm=_basename,
               note="compared on the file name; the two sides spell the path differently"),
        # Recorded empty on every live row inspected - a real evidence gap, reported as UNKNOWN
        # rather than quietly skipped.
        _check("params_hash", row.get("params_hash"), rep.get("params_hash"),
               note="live rows record an empty params_hash"),
    ]
    if sp.sleeve in ("global_nkd", "roska4_swing"):
        # Stage 5ZZZ-Q. The live row now records the basis, so this IS a live-vs-replay
        # comparison. A row written before that field existed gets NOT_APPLICABLE - it is not a
        # match and it is not the slot's fault.
        basis = rep.get("regime_basis")
        recorded = row.get("regime_basis")
        detector_is_causal = basis is not None and "own label" not in str(basis)

        if not recorded:
            checks.append(FieldCheck(
                "regime_basis_recorded_vs_detector", recorded, basis,
                NOT_APPLICABLE if not sp.post_fix else UNKNOWN,
                "the row predates the regime_basis field" if not sp.post_fix
                else "a post-fix row should record its basis and did not"))
        else:
            agrees = (recorded == "causal_d1") == detector_is_causal
            checks.append(FieldCheck(
                "regime_basis_recorded_vs_detector", recorded, basis,
                PASS if agrees else FAIL,
                "the row's recorded basis against the object the detector was handed"))

        if sp.sleeve == "roska4_swing":
            same_day = basis is not None and "own label" in str(basis)
            checks.append(FieldCheck(
                "swing_regime_basis_is_causal_d1",
                "causal D-1 (declared paper identity)", basis,
                FAIL if same_day else (PASS if basis else UNKNOWN),
                "the detector's own basis, from the reconstruction that mirrors the live "
                "call site"))
    if sp.sleeve == "roska4_calm":
        ph = rep.get("phases") or {}
        dec = ph.get("decide") or {}
        leaked = [r for r in (dec.get("rows") or [])
                  if r and ("Planned stop" in str(r) or "Entry reference" == str(r))]
        checks.append(FieldCheck("calm_decide_has_no_observe_value", None, leaked,
                                 PASS if not leaked else FAIL,
                                 "DECIDE must carry no OBSERVE-only value"))
        checks.append(FieldCheck("calm_decide_has_no_price_level", None,
                                 dec.get("price_levels"),
                                 PASS if dec.get("price_levels") == 0 else FAIL))

    sp.checks = checks
    verdicts = {c.verdict for c in checks}
    # NOT_APPLICABLE does not block a PASS - the field genuinely did not exist - but a slot
    # carrying one can only ever be described as PRE_FIX, never as a clean match.
    comparable = verdicts - {NOT_APPLICABLE}
    if FAIL in comparable:
        sp.verdict = PRE_FIX_MISMATCH if not sp.post_fix else FAIL
        sp.reason = ("a comparable field disagrees; the row predates the current code"
                     if not sp.post_fix else "at least one comparable field disagrees")
    elif PASS in comparable and UNKNOWN in comparable:
        sp.verdict = UNKNOWN
        sp.reason = ("some fields matched but others could not be compared; a partial match is "
                     "not a pass")
    elif comparable == {PASS}:
        if sp.post_fix:
            sp.verdict, sp.reason = PASS, "every comparable field matched"
        else:
            sp.verdict = PRE_FIX_MISMATCH if NOT_APPLICABLE in verdicts else UNKNOWN
            sp.reason = ("every comparable field matched, but the row predates the current "
                         "code and cannot evidence it")
    else:
        sp.verdict, sp.reason = UNKNOWN, "nothing comparable was recorded"
    return sp


def parity(root: str | Path = ".") -> dict:
    """The whole picture: per sleeve, the newest live slot and what it can prove."""
    cut = fix_cutoff(root)
    cutoff = cut["cutoff"]
    diag_dir = Path(root).joinpath(*DIAG_DIR)

    out = {"schema": SCHEMA, "route": ROUTE, "fix_cutoff": cut,
           "runtime_diagnostics_store_present": diag_dir.exists(),
           "counts_toward_paper_shadow_evidence": False,
           "note": ("Read-only. This module releases no gate and marks no evidence satisfied. "
                    "UNKNOWN is never reported as PASS."),
           "sleeves": {}}

    for sleeve in SLEEVES:
        row = newest_slot(root, sleeve)
        if row is None:
            out["sleeves"][sleeve] = {"verdict": NOT_YET,
                                      "reason": "no live slot recorded for this sleeve at all"}
            continue
        sp = compare_slot(root, row, cutoff)
        if not sp.post_fix:
            # The decisive rule: a slot that predates the fixes did not exercise this path.
            out["sleeves"][sleeve] = {
                "verdict": NOT_YET,
                "reason": (f"the newest live slot ran at {sp.live_ran_at}, before the newest "
                           f"relevant fix at {cutoff}"),
                "newest_live_slot": {"slot_id": sp.slot_id, "slot_time": sp.slot_time,
                                     "session_date": sp.session_date,
                                     "live_ran_at": sp.live_ran_at},
                "pre_fix_informational": sp.as_dict(),
            }
            continue
        out["sleeves"][sleeve] = sp.as_dict()

    verdicts = [v.get("verdict") for v in out["sleeves"].values()]
    out["summary"] = {v: verdicts.count(v)
                      for v in (PASS, FAIL, UNKNOWN, NOT_YET, PRE_FIX_MISMATCH,
                                NOT_APPLICABLE)}
    out["all_post_fix_observed"] = NOT_YET not in verdicts
    return out
