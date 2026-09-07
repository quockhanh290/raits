"""Did the regime labels move, and do we actually know?

Three answers, never two. The version this replaces returned a count of drifted dates and
returned **0** from four different places that had not verified anything at all:

    cannot import futures._validated_core  -> 0
    could not load the CSVs                -> 0
    label_regimes raised                   -> 0
    no overlapping dates to compare        -> 0, and logged "HMM stable"

Zero is also what a clean run returns. So "I could not check" and "I checked and it was fine"
were the same number — and the one call site, `update_spy_csv` line 300, discarded it anyway.
A drift of fifty labels logged a WARNING nobody reads, returned a number nobody consumed, in a
process that exited 0, from a child whose non-error output the scheduler throws away. Invisible
from end to end, in the check that guards which sleeve is allowed to trade.

The fourth path is the one worth pausing on. With no overlapping dates the old code took the
INFO branch and printed *"Regime labels unchanged (0 dates verified) — HMM stable"*. A
statement about nothing, phrased as reassurance.

What this module does NOT do
----------------------------
It does not decide anything. It reports. Whether a DRIFT stops a job, skips a day or holds the
paper gate is a decision each caller makes and states out loud — see `update_spy_csv --verify-
strict`, the scheduler's two SPY jobs, and `track1_gates.REGIME_LABEL_VERIFICATION`. Putting
the consequence here would have made one policy for callers with very different stakes: the
13:45 pre-flight gates the whole trading day, and the 16:20 refresh gates nothing.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

SCHEMA = "regime_verify/1"

#: Verification ran and found no changed label.
PASS = "PASS"
#: Verification ran and labels moved. The engine's view of history changed.
DRIFT = "DRIFT"
#: Verification could not run, or ran and proved nothing. NEVER reported as PASS.
UNKNOWN = "UNKNOWN"

STATUSES = (PASS, DRIFT, UNKNOWN)

# ── codes. One per distinct condition, because "it did not verify" is not a diagnosis ──
OK = "ok"
LABELS_CHANGED = "labels_changed"
NO_ENGINE = "engine_unavailable"
UNREADABLE = "inputs_unreadable"
LABELLING_FAILED = "labelling_failed"
NO_OVERLAP = "no_overlapping_dates"
NO_SNAPSHOT = "no_snapshot"
NO_RECORD = "no_record"
RECORD_UNREADABLE = "record_unreadable"
RECORD_STALE = "record_stale"

#: Every code, and which status it can carry. A code that could be either would be a code
#: that has not been thought through.
CODE_STATUS = {
    OK: PASS,
    LABELS_CHANGED: DRIFT,
    NO_ENGINE: UNKNOWN,
    UNREADABLE: UNKNOWN,
    LABELLING_FAILED: UNKNOWN,
    NO_OVERLAP: UNKNOWN,
    NO_SNAPSHOT: UNKNOWN,
    NO_RECORD: UNKNOWN,
    RECORD_UNREADABLE: UNKNOWN,
    RECORD_STALE: UNKNOWN,
}

#: Where the status lands so a reader other than the job itself can find it. Route-neutral,
#: beside `preflight_state.json`, because the check is shared infra: legacy's pre-flight runs
#: exactly the same verification.
VERIFY_DIR = "global_index/regime_verify"

#: How old the newest record may be before readiness treats it as no record at all. Seven
#: calendar days covers a holiday week. A judgement call, named, and moving it changes what
#: "recently verified" means and nothing else.
MAX_RECORD_AGE_DAYS = 7


@dataclass(frozen=True)
class VerifyResult:
    status: str
    code: str
    detail: str = ""
    checked_at: str = ""
    #: What was compared. Paths only — never the contents, which can be large and can carry
    #: values nobody meant to publish.
    inputs: dict = field(default_factory=dict)
    #: Dates compared, dates changed, and a short sample. Empty when nothing was compared,
    #: which is itself the finding on the `no_overlapping_dates` path.
    counts: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}; one of {STATUSES}")
        want = CODE_STATUS.get(self.code)
        if want is not None and want != self.status:
            raise ValueError(
                f"code {self.code!r} carries status {want!r}, not {self.status!r} — a code "
                f"that can mean two things is a code nobody can act on")

    @property
    def ok(self) -> bool:
        """True only for PASS. UNKNOWN is not ok; that is the whole point of this module."""
        return self.status == PASS

    @property
    def blocks_paper(self) -> bool:
        return self.status != PASS

    def as_dict(self) -> dict:
        return {"schema": SCHEMA, **asdict(self)}

    def one_line(self) -> str:
        return f"{self.status} ({self.code}): {self.detail}"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _result(status: str, code: str, detail: str, **kw) -> VerifyResult:
    return VerifyResult(status=status, code=code, detail=detail, checked_at=_now(), **kw)


# ══════════════════════════════════════════════════════════════════════════════
# the verification
# ══════════════════════════════════════════════════════════════════════════════

def verify_labels(snap_path, new_csv, check_end: str = "2024-12-31") -> VerifyResult:
    """Compare HMM regime labels between the pre-update snapshot and the updated series.

    Labels are `HMM.decode(prices)`. Prices unchanged plus engine unchanged means labels
    unchanged — but a refit with the same prices and a different seed, code or fit end gives
    DIFFERENT labels, and a price comparison walks straight past that. This compares the
    labels themselves, which is why it exists beside the price check rather than instead of it.

    Every early return that used to be `0` is an `UNKNOWN` with its own code.
    """
    snap_path = Path(snap_path) if snap_path else None
    new_csv = Path(new_csv)
    inputs = {"snapshot": str(snap_path) if snap_path else None, "updated": str(new_csv),
              "check_end": check_end}

    if snap_path is None or not snap_path.exists():
        return _result(UNKNOWN, NO_SNAPSHOT,
                       f"no pre-update snapshot to compare against ({snap_path}), so nothing "
                       f"can be said about whether the labels moved",
                       inputs=inputs)

    try:
        from futures._validated_core import benchmark_daily, label_regimes
    except ImportError as exc:
        return _result(UNKNOWN, NO_ENGINE,
                       f"cannot import futures._validated_core ({exc}), so the labels were "
                       f"never computed — this is not 'no drift', it is 'no check'",
                       inputs=inputs)

    try:
        old_bench = benchmark_daily(str(snap_path))
        new_bench = benchmark_daily(str(new_csv))
    except Exception as exc:                                    # noqa: BLE001
        return _result(UNKNOWN, UNREADABLE,
                       f"could not load one of the series ({type(exc).__name__}: {exc})",
                       inputs=inputs)

    hmm_train_end, n_components = "2018-01-01", 3
    try:
        old_labels = label_regimes(old_bench, hmm_train_end, n_components, check_end)
        new_labels = label_regimes(new_bench, hmm_train_end, n_components, check_end)
    except Exception as exc:                                    # noqa: BLE001
        return _result(UNKNOWN, LABELLING_FAILED,
                       f"label_regimes raised ({type(exc).__name__}: {exc}), so neither side "
                       f"of the comparison exists",
                       inputs=inputs)

    import pandas as pd
    cutoff = pd.Timestamp(check_end)
    old_labels, new_labels = pd.Series(old_labels), pd.Series(new_labels)
    common = old_labels.index.intersection(new_labels.index)
    common = common[common <= cutoff]

    if len(common) == 0:
        # The subtlest of the four old collapses: this took the INFO branch and printed
        # "Regime labels unchanged (0 dates verified) — HMM stable". A statement about
        # nothing, phrased as reassurance.
        return _result(UNKNOWN, NO_OVERLAP,
                       f"the two series share no dates at or before {check_end}, so zero "
                       f"labels were compared — 'no differences found' here means 'nothing "
                       f"was looked at'",
                       inputs=inputs, counts={"compared": 0, "changed": 0})

    changed = [d for d in common if old_labels.get(d) != new_labels.get(d)]
    counts = {"compared": int(len(common)), "changed": int(len(changed)),
              "sample": [str(pd.Timestamp(d).date()) for d in changed[:10]]}

    if changed:
        return _result(DRIFT, LABELS_CHANGED,
                       f"{len(changed)} of {len(common)} label(s) changed through {check_end} "
                       f"(e.g. {counts['sample']}). Causes to separate: the price source "
                       f"revised history, the engine's settings moved, or a refit landed on a "
                       f"different seed",
                       inputs=inputs, counts=counts)

    return _result(PASS, OK,
                   f"{len(common)} label(s) compared through {check_end}, none changed",
                   inputs=inputs, counts=counts)


# ══════════════════════════════════════════════════════════════════════════════
# the record — so a reader other than the job can find the answer
# ══════════════════════════════════════════════════════════════════════════════

def record_path(root: str | Path = ".", day: str | None = None) -> Path:
    d = day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
    return Path(root) / VERIFY_DIR / f"regime_verify_{d}.jsonl"


def record(result: VerifyResult, root: str | Path = ".", *, source: str = "") -> Path:
    """Append one result. Append-only and dated, like every other evidence file here.

    A verification whose answer exists only in a log line is a verification nobody can gate
    on: the scheduler keeps only CRITICAL and ERROR from a child that exited 0, so an INFO
    'labels unchanged' never reaches the journal at all.
    """
    p = record_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {**result.as_dict(), "source": source}
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return p


def latest(root: str | Path = ".", *, now: Any = None,
           max_age_days: int = MAX_RECORD_AGE_DAYS) -> VerifyResult:
    """The newest recorded result, or an UNKNOWN saying why there is none.

    Absence is never a pass. A day nobody verified and a day that verified clean must not read
    the same, which is the same rule the window ledger applies to slots.
    """
    d = Path(root) / VERIFY_DIR
    files = sorted(d.glob("regime_verify_*.jsonl")) if d.is_dir() else []
    rows: list = []
    for f in files:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
        except Exception as exc:                                # noqa: BLE001
            return _result(UNKNOWN, RECORD_UNREADABLE,
                           f"{f.name} could not be read ({type(exc).__name__}: {exc}), so the "
                           f"verification history cannot be trusted whole")
    if not rows:
        return _result(UNKNOWN, NO_RECORD,
                       f"no verification has been recorded under {VERIFY_DIR} — a check that "
                       f"never ran is not a check that passed")

    rows.sort(key=lambda r: str(r.get("checked_at") or ""))
    newest = rows[-1]
    status = str(newest.get("status") or "")
    if status not in STATUSES:
        return _result(UNKNOWN, RECORD_UNREADABLE,
                       f"the newest record carries status {status!r}, which is not one of "
                       f"{STATUSES}")

    stamp = str(newest.get("checked_at") or "")
    try:
        when = _dt.datetime.fromisoformat(stamp)
        ref = now or _dt.datetime.now(_dt.timezone.utc)
        if isinstance(ref, str):
            ref = _dt.datetime.fromisoformat(ref)
        if when.tzinfo is None:
            when = when.replace(tzinfo=_dt.timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=_dt.timezone.utc)
        age = (ref - when).days
    except Exception:                                           # noqa: BLE001
        return _result(UNKNOWN, RECORD_UNREADABLE,
                       f"the newest record's checked_at {stamp!r} is unparseable")

    if age > max_age_days:
        return _result(UNKNOWN, RECORD_STALE,
                       f"the newest verification is {age} day(s) old, past the "
                       f"{max_age_days}-day allowance — it describes a series that has been "
                       f"updated since",
                       inputs=dict(newest.get("inputs") or {}),
                       counts=dict(newest.get("counts") or {}))

    return VerifyResult(status=status, code=str(newest.get("code") or ""),
                        detail=str(newest.get("detail") or ""), checked_at=stamp,
                        inputs=dict(newest.get("inputs") or {}),
                        counts=dict(newest.get("counts") or {}))
