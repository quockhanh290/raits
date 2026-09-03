"""Proof that a slot which decided actually looked at data.

The gap this closes was found in the evidence rather than in the code. The 2026-08-26 night
window passed its audit — twenty-two slots, all decided, no candidates — and the human-readable
explanation for its last slot said:

    bar_timestamps: []
    data_time: null

So the ledger proved the slot DECIDED and nothing proved WHAT IT LOOKED AT. Those are
different claims. A slot that fetched nothing, spliced nothing and found no candidate produces
the same ledger row as one that pulled a thousand bars and found no candidate — and on a quiet
route, which is every route until it trades, they are indistinguishable.

Nothing here is recomputed
--------------------------
Every number in a row already exists on the objects the slot built while deciding.
`JoinedFrame` carries the provider, the rows it offered, the rows kept, the overlap it checked
and the columns it dropped; the splice report inside it carries its own outcome code, the
frozen row count, the frozen last timestamp and the first live bar kept. This module reads
those and writes them down. It computes no feature, calls no detector and touches no rule — a
diagnostics path that recomputed anything would be a second implementation beside the one that
trades, and the two would disagree on exactly the day it mattered.

What is deliberately null
-------------------------
`dropped_open_final_bar`. The fetch is causal — it keeps bars at or before the instant it was
taken — but nothing in the chain records whether the provider's final bar was still forming
when it was handed over. That is an honest unknown and is written as `null` with the reason
beside it, never omitted and never guessed. Rule five of this stage, and the same rule the
regime verification and the broker reads landed on: absence of a finding is not a finding.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

SCHEMA = "track1_data_observation/1"
ROUTE = "track1_candidate"
DIR = "global_index/track1_runtime/data_observation"

#: Why a value is null. Recorded beside the null so a reader never has to guess whether a
#: field was unknown or forgotten.
NOT_REPORTED_BY_JOIN = "not_reported_by_the_join"
NO_FRAME = "no_frame_was_built"
PRE_SCHEMA = "pre_observation_schema"

#: What the slot did with the data it observed.
DECIDED = "decided"
REFUSED = "refused"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _ts(value: Any) -> "str | None":
    if value is None:
        return None
    s = str(value)
    return None if s in ("", "None", "NaT") else s


def _frame_edges(frame: Any) -> "tuple[str | None, str | None, int | None]":
    """`(first, last, rows)` of a frame, or nulls. Reads the index; computes nothing."""
    try:
        if frame is None or len(frame) == 0:
            return None, None, 0
        idx = frame.index
        return _ts(idx.min()), _ts(idx.max()), int(len(frame))
    except Exception:                                          # noqa: BLE001
        return None, None, None


def instrument_row(joined: Any, *, history_symbol: str = "", tradable_symbol: str = "",
                   data_path: str = "", data_identity: str = "") -> dict:
    """One instrument's observation, composed from what the join already recorded.

    `joined` is a `track1_live_source.JoinedFrame`. Its `as_dict()` carries the provider, the
    row counts, the overlap it checked, the columns it dropped and — flattened in from the
    splice report — the outcome code, the frozen row count, the frozen last timestamp and the
    first live bar that was kept.
    """
    try:
        d = dict(joined.as_dict())
    except Exception as exc:                                   # noqa: BLE001
        return {"inst": str(getattr(joined, "inst", "") or ""),
                "error": f"{type(exc).__name__}: {exc}",
                "splice_result": None, "splice_result_null_reason": NO_FRAME}

    first, last, rows = _frame_edges(getattr(joined, "frame", None))
    code = str(d.get("code") or "")
    return {
        "inst": str(d.get("inst") or ""),
        "history_symbol": str(history_symbol or d.get("inst") or ""),
        "tradable_symbol": str(tradable_symbol or ""),
        "provider": str(d.get("provider") or ""),
        "data_path": str(data_path or ""),
        # `<path>:<sha256>`, the same identity the explanation record carries, so the two
        # pieces of evidence can be tied to one another without re-hashing anything.
        "data_identity": str(data_identity or ""),

        "live_rows_fetched": d.get("provider_rows"),
        # Stage 5ZZI. What the feed said, so a zero can be told from a refusal. This field was
        # emitted as null on every row for three days while the gateway was answering each
        # request with a named error.
        "provider_error": d.get("provider_error") or None,
        "live_rows_offered": d.get("live_rows_offered"),
        "live_rows_appended": d.get("live_rows_appended"),
        "live_rows_offered_but_unused": d.get("offered_but_unused"),
        "live_first_kept_ts": _ts(d.get("live_first_kept")),

        "frozen_rows": d.get("frozen_rows"),
        "frozen_last_ts": _ts(d.get("frozen_last")),

        "overlap_checked_rows": d.get("overlap_checked"),
        # The join refuses rather than returns on an overlap disagreement, so reaching here
        # with a code at all means the overlap was accepted. Reported as the code that was
        # actually produced rather than as a bare "ok".
        "overlap_result": "ok" if code else None,
        "splice_result": code or None,
        "splice_notices": list(d.get("notices") or []),
        "splice_detail": str(d.get("detail") or ""),
        "dropped_columns": list(d.get("dropped_columns") or []),

        # Honest unknown. Nothing in the chain records whether the provider's last bar was
        # still forming; the fetch is causal but that is a different guarantee.
        "dropped_open_final_bar": None,
        "dropped_open_final_bar_null_reason": NOT_REPORTED_BY_JOIN,

        "final_frame_first_ts": first,
        "final_frame_last_ts": last,
        "final_frame_rows": rows,
    }


def build_row(*, session_date: str, sleeve: str, slot_id: str, mode: str,
              instruments: list, decision_reached: bool, decision_reason: str = "",
              candidate_count: "int | None" = None, outcome: str = DECIDED,
              provider: str = "", error: str = "", error_code: str = "") -> dict:
    """One slot's data-observation row. Flat, small, and free of price data.

    Deliberately carries no bar array. The evidence a reader needs is that bars were fetched,
    how many, over what span, and what the join did with them — not the bars themselves. A row
    that embedded them would make this file grow with the market and would put prices into a
    stream whose purpose is provenance.
    """
    return {
        "schema": SCHEMA, "route": ROUTE, "session_date": str(session_date),
        "sleeve": str(sleeve), "slot_id": str(slot_id), "mode": str(mode),
        "provider": str(provider or (instruments[0].get("provider") if instruments else "")),
        "outcome": outcome,
        "instruments": list(instruments),
        "instrument_count": len(instruments),
        "decision_reached": bool(decision_reached),
        "decision_reason": str(decision_reason or ""),
        "candidate_count": candidate_count,
        "error": str(error or ""), "error_code": str(error_code or ""),
        "ts": _now(),
    }


def refusal_row(*, session_date: str, sleeve: str, slot_id: str, mode: str,
                error_code: str, error: str, provider: str = "") -> dict:
    """A slot that could not build a frame still proves it TRIED, and why it stopped.

    Written before the refusal propagates. A refused slot that left no observation row would
    be indistinguishable from one that never ran — and "nobody looked" and "we looked and were
    refused" call for different actions.
    """
    return build_row(session_date=session_date, sleeve=sleeve, slot_id=slot_id, mode=mode,
                     instruments=[], decision_reached=False, decision_reason=error_code,
                     candidate_count=None, outcome=REFUSED, provider=provider,
                     error=error, error_code=error_code)


def path_for(root: str | Path = ".", day: str | None = None) -> Path:
    d = (day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")).replace("-", "")
    return Path(root) / DIR / f"data_observation_{d}.jsonl"


def record(row: dict, *, root: str | Path = ".", day: str | None = None) -> Path:
    """Append one row. Append-only and dated, like every other evidence stream here."""
    p = path_for(root, day or str(row.get("session_date") or ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")
    return p


#: Where the bars a slot decided on are kept. A sibling of the observation stream, dated the
#: same way, because it answers for the same slot on the same session.
BARS_DIR = "global_index/track1_runtime/session_bars"


def bars_path_for(root: str | Path = ".", day: str | None = None, inst: str = "") -> Path:
    d = (day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")).replace("-", "")
    return Path(root) / BARS_DIR / f"{str(inst).upper()}_{d}.parquet"


def _as_store_clock(frame: Any) -> Any:
    """The frame on the same clock the daily parquet uses: tz-naive UTC.

    Measured 2026-09-03 by scanning every hour offset between the two files and matching on
    price: 100% of 1,546 timestamps agree at exactly -9.0 hours, and under 2% at every other
    offset. Tokyo is UTC+9, so the store's naive index is UTC while the joined frame carries
    Asia/Tokyo. A reader that normalises one of them to the sleeve's clock and leaves the
    other alone slices the two nine hours apart, and the panel would draw one source's window
    against the other's.

    Written on the store's convention rather than fixed on the way out, so there is one
    answer on disk instead of a rule every reader has to remember.
    """
    try:
        import pandas as pd

        idx = pd.DatetimeIndex(frame.index)
        if idx.tz is None:
            return frame
        out = frame.copy()
        out.index = idx.tz_convert("UTC").tz_localize(None)
        return out
    except Exception:                                          # noqa: BLE001
        return frame


def _around(frame: Any, day: str) -> Any:
    """The session and a day either side of it, not the eight years behind it.

    Measured before this existed: the joined frame is the FROZEN history with the live half
    spliced on, so one call wrote 2,052,686 rows spanning 2018-01-02 to today -- 28 MB, per
    instrument, per slot. Twenty-two slots across three instruments is about 1.8 GB of disk
    written per session window, to keep three hours of bars.

    A day either side rather than the day alone: the index carries the instrument's own clock
    and `day` is the session date on that clock, so an off-by-one between the two would
    otherwise cut away the very rows this exists to keep. Three days is still four thousand
    rows, and a wrong margin costs nothing while a wrong cut costs everything.

    Returns the frame unchanged when the index cannot be read as dates -- keeping too much is
    a cost, keeping nothing is a defect.
    """
    try:
        import datetime as _d
        import pandas as pd

        d = _d.date.fromisoformat(str(day))
        idx = pd.DatetimeIndex(frame.index)
        dates = pd.Index(idx.date)
        lo, hi = d - _d.timedelta(days=1), d + _d.timedelta(days=1)
        return frame[(dates >= lo) & (dates <= hi)]
    except Exception:                                          # noqa: BLE001
        return frame


def record_bars(frame: Any, *, root: str | Path = ".", day: str, inst: str) -> "Path | None":
    """Keep the bars the slot actually decided on, so something other than this process can read them.

    The join splices the live half of a session onto the frozen store IN MEMORY, and the store
    itself is appended once a day by the 13:45 ET pre-flight chain. So between an overnight
    window and that append -- eleven hours for the Japan sleeve -- today's bars exist nowhere
    but inside this process, and a panel asking "what did price do in the window" could only
    answer with the previous session. That is the wrong answer printed under today's label.

    One file per instrument per session, OVERWRITTEN rather than appended: every call carries
    the same session with more of it, so the last write is the complete one and twenty-two
    slots do not leave twenty-two copies. Written to a temporary name and moved into place, so
    a reader polling every eight seconds never opens a half-written file.

    Returns the path, or None when there was nothing to write. NEVER raises. This is
    bookkeeping on the slot path, and bookkeeping must not cost a slot its entry.
    """
    try:
        if frame is None or len(frame) == 0 or not str(inst).strip():
            return None
        frame = _as_store_clock(frame)
        frame = _around(frame, day)
        if frame is None or len(frame) == 0:
            return None
        p = bars_path_for(root, day, inst)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        frame.to_parquet(tmp)
        tmp.replace(p)
        return p
    except Exception:                                          # noqa: BLE001
        return None


def read(*, root: str | Path = ".", day: str) -> "tuple[list, list]":
    """`(rows, malformed)` for one session date."""
    p = path_for(root, day)
    if not p.exists():
        return [], []
    rows, bad = [], []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            v = json.loads(line)
        except json.JSONDecodeError as exc:
            bad.append(f"line {i}: {exc}")
            continue
        (rows if isinstance(v, dict) else bad).append(
            v if isinstance(v, dict) else f"line {i}: not an object")
    return rows, bad


def summary(rows: list) -> dict:
    """What a day's observation stream says, for the audit and the panel."""
    import collections

    by_slot = {str(r.get("slot_id") or ""): r for r in rows}
    providers = collections.Counter(str(r.get("provider") or "") for r in rows)
    refusals = collections.Counter(str(r.get("error_code") or "") for r in rows
                                   if str(r.get("outcome")) == REFUSED)
    splice = collections.Counter(str(i.get("splice_result") or "")
                                 for r in rows for i in (r.get("instruments") or []))
    live_rows = sum(int(i.get("live_rows_fetched") or 0)
                    for r in rows for i in (r.get("instruments") or []))
    return {"records": len(rows), "slots": sorted(by_slot),
            "providers": dict(providers), "refusals_by_reason": dict(refusals),
            "splice_results": dict(splice), "live_rows_fetched_total": live_rows}


def operator_line(row: "dict | None") -> str:
    """One sentence for the job panel. No variable names, no JSON, no thresholds.

    Three shapes, because there are three states and an operator acts differently on each.
    """
    if row is None:
        return "Data proof: not recorded by this slot version"
    if str(row.get("outcome")) == REFUSED:
        reason = str(row.get("error_code") or "").replace("_", " ") or "unknown reason"
        return f"Data refused: {reason}"
    insts = row.get("instruments") or []
    if not insts:
        return "Data proof: recorded, but no instrument was observed"
    names = "·".join(str(i.get("history_symbol") or i.get("inst") or "?") for i in insts[:3])
    bars = sum(int(i.get("live_rows_fetched") or 0) for i in insts)
    last = next((i.get("final_frame_last_ts") for i in insts if i.get("final_frame_last_ts")),
                None)
    when = str(last)[11:16] + " ET" if last and len(str(last)) >= 16 else "unknown time"
    codes = {str(i.get("splice_result") or "") for i in insts}
    splice = "splice OK" if codes == {"ok"} else "splice " + ", ".join(sorted(c for c in codes if c))
    provider = str(row.get("provider") or "unknown").upper()
    return f"Data: {provider} · {names} · {bars} live bars checked · last {when} · {splice}"
