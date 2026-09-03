"""What the market did inside a sleeve's window, and what the route did about it. Stage 5ZZL.

This is an OPERATIONAL view, not an analysis one. It exists to answer four questions an
operator asks when a sleeve reports nothing:

    what did price do in the window
    which slots ran, and which refused
    are the strategy's entry levels known
    is there a data problem underneath the silence

and to answer them from evidence that already exists. It computes no strategy value, decides
nothing, and opens no connection.

Where each field comes from — measured on 2026-08-27
----------------------------------------------------
    bars        the instrument parquet, day-sliced and resampled. NOT the broker: the dashboard
                has no safe pattern for a live fetch, and the one this route uses is the
                slot's own.
    slots       the signal-diagnostics rows the route writes per slot, plus the slot table for
                slots that have not fired yet
    levels      NOTHING. Every strategy rule in the diagnostics carries
                `source: not_exposed_by_sleeve` — the detectors return a decision and not the
                numbers behind it, so there is no entry price, stop or target to draw. That is
                reported as `not_exposed` rather than approximated, because a line drawn at a
                level nobody published is a line an operator would trade against.
    data status the data-observation row, including the provider error Stage 5ZZI wired in

The honest state of the bars, and why the empty case is the normal one
----------------------------------------------------------------------
The parquet is appended once a day, and the live half of each session is spliced in memory
inside the slot process and then thrown away. So **today's bars are not persisted anywhere**:
measured on 2026-08-27 the newest bar in every instrument store was 2026-08-26 17:44, while the
overnight sleeve had fetched and used nearly two thousand of today's. A chart of "today" would
therefore be empty on every normal day, which is a chart nobody would trust.

So a sleeve reports the most recent session the store actually covers, says which session that
is, and says plainly when it is not today. An empty answer names the reason instead of being
drawn as a blank rectangle.
"""
from __future__ import annotations

import collections
import datetime as _dt
import re
import threading as _threading

from global_index import track1_strategy_diagnostics as _sd
import time as _time
import json
from pathlib import Path
from typing import Any

SCHEMA = "track1_market_view/1"
ROUTE = "track1_candidate"
ET = "America/New_York"

#: One chart per sleeve, with the context each one is read in. The window is the sleeve's own
#: trading window; the context is the run-up and run-down an operator needs to see around it.
#: Calm is deliberately absent — it is a two-phase one-shot contract and a candle chart of a
#: single decision instant would suggest a window it does not have.
#: Stage 5ZZZ-BY. The chart span is DERIVED from each sleeve's own window, not written out.
#:
#: The four values were hand-written per sleeve and only three of them agreed. Measured on
#: 2026-08-31, each sleeve's drawn range against its own window:
#:
#:     NKD     00:00 - 03:05    lead  -70 min    tail  +10 min
#:     Stress  09:30 - 12:40    lead  -65 min    tail  +10 min
#:     Swing   09:30 - 16:05    lead -275 min    tail  +10 min
#:
#: The tail agreed by coincidence -- three separately typed strings that happened to land on
#: the same offset -- and the lead did not agree at all. Stress and Swing both started at the
#: RTH open, so a sleeve whose window sits late in the day drew four and a half hours of
#: run-up: on Swing that is eighty candles for a window of twenty-three slots, and the bars
#: that matter are squeezed into the right-hand quarter of the chart.
#:
#: Derived now, so the three can no longer drift apart and the span means the same thing on
#: every tab: one hour before the window opens, ten minutes after it closes.
#:
#: Nothing computes from this. It slices the bars for the chart and is published as `range`;
#: no rule, threshold or verdict reads it, and no EMA is built from the drawn bars.
CHART_LEAD_MINUTES = 60
CHART_TAIL_MINUTES = 10


def _shift_hhmm(hhmm: str, minutes: int) -> str:
    """`HH:MM` moved by minutes, CLAMPED to the day rather than wrapped.

    A window opening near midnight would otherwise take its lead-in to the previous evening --
    23:10 for a 00:10 open -- and the slice, which asks for bars BETWEEN start and end, would
    come back empty. An hour of missing run-up is a smaller lie than an empty chart.
    """
    total = int(hhmm[:2]) * 60 + int(hhmm[3:]) + minutes
    total = max(0, min(total, 24 * 60 - 1))
    return "%02d:%02d" % divmod(total, 60)


def _chart_span(window_start: str, window_end: str) -> dict:
    return {"context_start": _shift_hhmm(window_start, -CHART_LEAD_MINUTES),
            "window_start": window_start, "window_end": window_end,
            "context_end": _shift_hhmm(window_end, CHART_TAIL_MINUTES)}


SLEEVES: dict = {
    "global_nkd": {
        "label": "NKD", "instrument": "MNKD", "clock": "Asia/Tokyo",
        **_chart_span("01:10", "02:55")},
    "roska4_stress": {
        "label": "Stress", "instrument": "MNQ", "clock": ET,
        **_chart_span("10:35", "12:30")},
    "roska4_swing": {
        "label": "Swing", "instrument": "MES", "clock": ET,
        **_chart_span("14:05", "15:55")},
}

BAR_MINUTES = 5

#: Slot marker vocabulary. `future` is its own value and not a missing one: a slot that has not
#: fired yet and a slot that fired and was never recorded must not draw the same.
SLOT_NO_SIGNAL = "no_signal"
SLOT_SIGNAL = "signal"
SLOT_REJECTED = "rejected"
SLOT_REFUSED = "refused"
SLOT_MISSED = "missed"
SLOT_FUTURE = "future"
SLOT_UNKNOWN = "unknown"

_STATUS_MAP = {"NO_SIGNAL": SLOT_NO_SIGNAL, "SIGNAL": SLOT_SIGNAL, "ACCEPTED": SLOT_SIGNAL,
               "CANDIDATE": SLOT_SIGNAL, "REJECTED": SLOT_REJECTED,
               "SLOT_REFUSED": SLOT_REFUSED, "REFUSED": SLOT_REFUSED}

#: Sleeve-level states.
ST_NOT_STARTED = "not_started"
ST_WAITING = "waiting"
ST_LIVE = "live"
ST_COMPLETE = "complete"
ST_REFUSED = "refused"
ST_INCOMPLETE = "incomplete"
#: Stage 5ZZZ-BW. The window ledger's own word, not a new one.
#:
#: `unobserved` means no `window_closed` record exists -- the ledger fail-closes on purpose:
#: "a window that opened and then vanished is not in progress after the fact, it is a window
#: nobody can vouch for". That is a DIFFERENT fact from `incomplete`, where the window did
#: close and counted fewer slots than expected: one says the coverage is short, the other says
#: nobody can attest to it at all.
#:
#: It used to fall through to `unknown`, which is the catch-all for "this code has no name for
#: this". Measured across the six sessions on disk, eighteen sleeve-days: seventeen carried the
#: right word and one did not -- Swing on 2026-08-28, nine of twenty-three slots observed and
#: no closing record, printed UNKNOWN in amber. The panel knew exactly what had happened and
#: said it could not tell.
ST_UNOBSERVED = "unobserved"
ST_UNKNOWN = "unknown"

#: Stage 5ZZM. Plain English, because this string is read by an operator and not by a
#: developer. It was `entry levels not exposed by sleeve evidence yet` — accurate, and it named
#: an internal concept ("exposed by sleeve evidence") that means nothing to whoever is deciding
#: whether to trust the chart. The fact underneath is unchanged: nothing published a price.
LEVELS_NOT_EXPOSED = "Strategy levels unavailable"

#: Named once rather than spelled in three places; it is the same word the diagnostics module
#: stamps on a block and the page keys its badge off.
RECONSTRUCTED_TODAY = "reconstructed_today"

#: The long form, for a tooltip. Says what is missing AND what the chart is still showing, so
#: the absence does not read as "this panel is broken".
LEVELS_DETAIL = ("The strategy has not published entry/reference levels for this sleeve yet. "
                 "The chart only renders prices and slot outcomes.")

#: Stage 5ZZZ-F. The third state, which did not exist when the two above were written: a level
#: the detector computed for a gate that did not pass. "Unavailable" is wrong about it and
#: silence is worse - an operator reading a trigger price needs to know it is not in play.
LEVELS_COMPUTED_UNARMED = "Levels computed but not armed"
LEVELS_UNARMED_DETAIL = ("The detector published these prices for this session, but the setup "
                         "gate did not pass, so they are not in play. They are drawn muted.")

#: Parquet day-slices, keyed by (path, mtime, day). The store is memory-mapped and a slice
#: measured at 0.05s, but a dashboard polls: without this every poll re-reads three files.
_bar_cache: dict = {}
_CACHE_MAX = 12

#: The Stress basket's daily slices, keyed by the four stores' modification times. Stage 5ZZQ.
#:
#: Stage 5ZZP added the sleeve diagnostic and called `daily_slices` on every request. Measured
#: on the running backend: **9.86s cold and 3.9s warm**, of which `daily_slices` alone was
#: 3.24s — a page that polls could not afford it, and the endpoint had been 0.11s warm one
#: stage earlier. The regression was mine.
#:
#: Keyed on MTIMES rather than on a clock, so a store that is appended invalidates the entry
#: rather than a stale slice being served until a timer expires. There is no TTL for the same
#: reason: a TTL would hand back a stale answer as a fresh one for the length of the timer,
#: which is the failure this route keeps finding in other clothes.
_slice_cache: dict = {}
_SLICE_CACHE_MAX = 3

#: Stage 5ZZZ-S. The cache above is right; filling it INLINE was the problem. On a cold miss it
#: read four parquet stores and sliced them on the request path — measured 6.5s, and on the
#: first request after a backend restart it runs while three other warm-up workers are already
#: saturating the CPU, which is how a 11s request became a 55s one.
#:
#: The mtime key is deliberately kept EXACTLY as it was. Only *when* the value is computed
#: changed, never *what invalidates it* — a TTL here was considered and rejected upstream, for
#: the good reason that it hands back a stale answer as a fresh one.
_slice_inflight: dict = {}


def _slice_warm(key, paths, need, params) -> str:
    """Start filling the slice cache for `key`; return the state to report meanwhile.

    `warming` while a worker is running, `failed: ...` if the last attempt raised. Never
    silently empty: a panel that cannot say which of the two it is tells an operator nothing.
    """
    with _recon_lock:
        state = _slice_inflight.get(key)
        if state == "running":
            return "warming"
        _slice_inflight[key] = "running"

    def _fill():
        import pandas as pd

        from global_index import track1_stress_mnq as SM
        try:
            frames = {i: pd.read_parquet(paths[i]) for i in need}
            value = SM.daily_slices(frames, params)
            with _recon_lock:
                if len(_slice_cache) >= _SLICE_CACHE_MAX:
                    _slice_cache.clear()
                _slice_cache[key] = value
                _slice_inflight[key] = "done"
        except Exception as exc:                                  # noqa: BLE001
            with _recon_lock:
                _slice_inflight[key] = f"failed: {type(exc).__name__}: {exc}"

    _threading.Thread(target=_fill, daemon=True).start()
    return "warming"


# ── bars ────────────────────────────────────────────────────────────────────────────────
def _store_path(inst: str) -> "str | None":
    try:
        from global_index import run_live_day_track1 as rl

        return (rl.default_data_paths() or {}).get(inst)
    except Exception:                                             # noqa: BLE001
        return None


def _sliced(inst: str, day: str, spec: dict) -> tuple:
    """`(bars, session_day, note)` for one instrument, from the persisted store only.

    `session_day` is the day the bars are actually FROM, which is not always the day asked
    for — see the module docstring. Returned rather than silently substituted.
    """
    import pandas as pd

    path = _store_path(inst)
    if not path or not Path(path).exists():
        return [], None, f"no persisted bar store for {inst}"

    try:
        mtime = Path(path).stat().st_mtime
        key = (str(path), mtime, day, spec["context_start"], spec["context_end"])
        if key in _bar_cache:
            return _bar_cache[key]
        frame = pd.read_parquet(path)
        idx = pd.DatetimeIndex(frame.index)
        if idx.tz is not None:
            idx = idx.tz_convert(spec["clock"]).tz_localize(None)
        frame = frame.copy()
        frame.index = idx
        want = pd.Timestamp(day).date()
        have = idx.normalize().date if hasattr(idx.normalize(), "date") else None
        days = pd.Index(idx.date)
        if want not in set(days):
            # The normal case, and it is stated rather than papered over: fall back to the
            # newest session the store DOES cover, and hand the caller its date so the page
            # can say which day it is looking at.
            newest = max(set(days))
            note = (f"no persisted bars for {day}; showing the most recent stored session "
                    f"{newest.isoformat()}")
            want = newest
        else:
            note = ""
        sel = frame[days == want]
        start = pd.Timestamp(f"{want} {spec['context_start']}")
        end = pd.Timestamp(f"{want} {spec['context_end']}")
        sel = sel[(pd.DatetimeIndex(sel.index) >= start) & (pd.DatetimeIndex(sel.index) <= end)]
        if not len(sel):
            out = ([], want.isoformat(),
                   note or f"the stored session {want.isoformat()} has no bars between "
                           f"{spec['context_start']} and {spec['context_end']}")
        else:
            # Stage 5ZZP. Volume, when the store has it — and it does, in every instrument.
            # Stage 5ZZL aggregated only OHLC and so reported no volume at all; the column was
            # there the whole time. Summed across the 5-minute bucket, which is the only
            # correct aggregation for a traded quantity.
            has_volume = "volume" in sel.columns
            how = {"open": "first", "high": "max", "low": "min", "close": "last"}
            if has_volume:
                how["volume"] = "sum"
            agg = sel.resample(f"{BAR_MINUTES}min").agg(how).dropna(
                subset=["open", "high", "low", "close"])
            bars = [{"time": pd.Timestamp(t).strftime("%Y-%m-%d %H:%M"),
                     "open": round(float(r.open), 4), "high": round(float(r.high), 4),
                     "low": round(float(r.low), 4), "close": round(float(r.close), 4),
                     **({"volume": int(r.volume)} if has_volume and r.volume == r.volume
                        else {})}
                    for t, r in agg.iterrows()]
            out = (bars, want.isoformat(), note)
        if len(_bar_cache) >= _CACHE_MAX:
            _bar_cache.clear()
        _bar_cache[key] = out
        return out
    except Exception as exc:                                      # noqa: BLE001
        return [], None, f"the bar store could not be read ({type(exc).__name__}: {exc})"


def _volume_status(bars: list) -> str:
    """Whether these bars carry a traded quantity, and whether it is ever non-zero.

    Measured 2026-08-27: MNQ and MES report volume on every bar; MNKD reports it on 270 of the
    last 500 and averages 2.5 — a genuinely thin instrument. A pane drawn from all-zero volume
    says "nothing traded", which is a claim about the market rather than about the store, so
    the two cases are named separately.
    """
    if not bars:
        return "not_available"
    with_v = [b for b in bars if "volume" in b]
    if not with_v:
        return "not_available"
    if len(with_v) < len(bars):
        return "partial"
    return "present" if any(b["volume"] for b in with_v) else "present_but_zero"


# ── slots ───────────────────────────────────────────────────────────────────────────────
def _signal_rows(root: Path, day: str) -> list:
    f = Path(root, "global_index/track1_runtime/signals") / f"track1_signals_{day.replace('-', '')}.jsonl"
    if not f.is_file():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:                                     # noqa: BLE001
                continue
    return out


def _slots_for(sleeve: str, rows: list, now_hhmm: "str | None") -> list:
    """Every slot the table declares, married to whatever the route recorded about it."""
    try:
        from global_index import track1_slots as ts

        declared = [s for s in ts.TRACK1_SLOTS if s.sleeve == sleeve]
    except Exception:                                             # noqa: BLE001
        declared = []

    seen: dict = {}
    for r in rows:
        if r.get("sleeve") != sleeve:
            continue
        seen[str(r.get("slot_id") or "")] = r

    out = []
    for s in declared:
        hhmm = f"{s.hour:02d}:{s.minute:02d}"
        r = seen.pop(s.id, None)
        if r is not None:
            raw = str(r.get("status") or "")
            out.append({"slot_id": s.id, "time_et": hhmm,
                        "status": _STATUS_MAP.get(raw, SLOT_UNKNOWN),
                        "reason": str(r.get("reason") or ""),
                        "candidate_count": int(r.get("raw_candidates") or 0)})
        elif now_hhmm is not None and hhmm > now_hhmm:
            out.append({"slot_id": s.id, "time_et": hhmm, "status": SLOT_FUTURE,
                        "reason": "has not fired yet", "candidate_count": 0})
        else:
            # Past its time and nothing recorded. NOT the same as "no signal" — nobody
            # watched, and this route has been bitten before by absence reading as a quiet
            # result.
            out.append({"slot_id": s.id, "time_et": hhmm, "status": SLOT_MISSED,
                        "reason": "no record was written for this slot",
                        "candidate_count": 0})
    for slot_id, r in seen.items():          # recorded but not declared — surfaced, not hidden
        out.append({"slot_id": slot_id, "time_et": str(r.get("slot_time") or ""),
                    "status": _STATUS_MAP.get(str(r.get("status") or ""), SLOT_UNKNOWN),
                    "reason": str(r.get("reason") or ""),
                    "candidate_count": int(r.get("raw_candidates") or 0)})
    return sorted(out, key=lambda s: s["time_et"])


# ── rule lanes ──────────────────────────────────────────────────────────────────────────
#: Stage 5ZZY. One row per strategy rule, one cell per slot. Six cell states, and the
#: distinction between the last three is the whole reason this exists.
CELL_PASS = "pass"
CELL_FAIL = "fail"
CELL_NOT_REACHED = "not_reached"        # the gate stopped the slot before this rule ran
CELL_NOT_PUBLISHED = "not_published"    # the detector evaluated it and returned no verdict
CELL_NO_RECORD = "no_record"            # the slot's time passed and nothing was written
CELL_FUTURE = "future"                  # its time has not come

#: What a lane with no decided slot should SAY, per dominant absence. Five distinct answers,
#: because "the gate stopped every slot before this rule ran" and "the detector ran it and
#: returned nothing" send an operator to two different places.
_LANE_ABSENCE = {
    CELL_NOT_REACHED: "not reached — the gate stopped the slot first",
    CELL_NOT_PUBLISHED: "value not published by the detector",
    CELL_NO_RECORD: "no record was written for these slots",
    CELL_FUTURE: "has not run yet",
}

_CELL_FROM_SOURCE = {"not_reached": CELL_NOT_REACHED,
                     "not_exposed_by_sleeve": CELL_NOT_PUBLISHED,
                     "not_reported_by_detector": CELL_NOT_PUBLISHED}


def _threshold_display(raw) -> str:
    """The rule's own published threshold, rendered without inventing one.

    The detectors publish these as scalars (`true`, `"no refusal codes"`) and as one-key
    dicts (`{"breadth_min": 4}`, `{"ema_period": 10}`). Both are real and both are shown;
    a rule that published nothing gets an empty string rather than a plausible default,
    because a threshold nobody published is a bar an operator would measure against.

    A third shape turned up that this docstring did not list: a LIST of allowed values.
    `track1_normal_r4` publishes the regimes its sleeve trades, and with no branch for
    a sequence the value fell through to `str(raw)` — so the lane on /realtime read
    `needs ['Normal']`, with Python's brackets and quotes printed onto an operations
    page. Measured on the 2026-08-31 session. Sequences are now worded, so the
    "needs …" the UI writes beside them stays a sentence.
    """
    if raw is None:
        return ""
    if isinstance(raw, dict):
        if not raw:
            return ""
        return " · ".join(f"{k.replace('_', ' ')} {v}" for k, v in raw.items())
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (list, tuple, set, frozenset)):
        # A set has no order of its own; sorting keeps the same payload rendering the
        # same way twice rather than shuffling between polls.
        members = [str(v) for v in (sorted(raw) if isinstance(raw, (set, frozenset)) else raw)]
        members = [m for m in members if m != ""]
        if not members:
            return ""
        if len(members) == 1:
            return members[0]
        return " or ".join([", ".join(members[:-1]), members[-1]])
    return str(raw)


_LIST_LITERAL = re.compile(r"\[\s*((?:'[^']*'|\"[^\"]*\")(?:\s*,\s*(?:'[^']*'|\"[^\"]*\"))*)\s*\]")


def _words_for_list_literals(text):
    """Turn a Python list literal inside a display string into words.

    The detectors build some of their prose with f-strings, and one of them
    interpolates a list: `track1_normal_r4` writes "this sleeve trades
    {sorted(ALLOWED_REGIMES)}", which arrives here as
    `this sleeve trades ['Normal']` and was printed onto /realtime in two places.
    Brackets and quotes are Python's syntax, not an operator's.

    Only BRACKETED lists are rewritten. Bare single quotes are deliberately left
    alone: pairing them off would turn "today's own row and tomorrow's" into
    something with the middle eaten, and prose apostrophes are far more common in
    these strings than quoted tokens. A bracket cannot be mistaken for prose; a
    quote can.

    The real repair belongs in the detector that writes the sentence, but that
    file is the engine's, not the dashboard's — so the display layer refuses to
    pass the artifact on rather than reaching across to fix it.
    """
    if not text or not isinstance(text, str):
        return text

    def _wordify(match: "re.Match") -> str:
        members = [m[1:-1] for m in re.findall(r"'[^']*'|\"[^\"]*\"", match.group(1))]
        members = [m for m in members if m != ""]
        if not members:
            return ""
        if len(members) == 1:
            return members[0]
        return " or ".join([", ".join(members[:-1]), members[-1]])

    return _LIST_LITERAL.sub(_wordify, text)


def _scrub_list_literals(node):
    """Apply `_words_for_list_literals` to every string in a payload.

    Placed at the exit rather than on the three fields caught so far. Chasing
    fields was losing: `threshold_display` was fixed and two places still printed
    it, `setup_boundary` was fixed and `strategy.detail` still did. Any detector
    that interpolates a list into prose reaches a page the same way, and none of
    them will announce it.

    Real lists keep their type — only strings are rewritten — so structured data
    like `threshold: ["Normal"]` stays a list for the front end to word itself.
    """
    if isinstance(node, str):
        return _words_for_list_literals(node)
    if isinstance(node, dict):
        return {k: _scrub_list_literals(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_scrub_list_literals(v) for v in node]
    return node


def _not_entry_conditions() -> dict:
    """Read from the table that declares the rules, never restated here.

    A copy of these three names in this file is a copy that goes stale the first time one is
    renamed, and the panel would then silently promote an exit parameter back into the entry
    lanes. Empty on an import failure, which puts every rule back in the lanes — noisy, and
    the direction a failure here is allowed to break in.
    """
    try:
        from global_index import track1_signals as _sig

        return dict(getattr(_sig, "NOT_ENTRY_CONDITIONS", {}) or {})
    except Exception:                                             # noqa: BLE001
        return {}


_NOT_ENTRY_CONDITIONS = _not_entry_conditions()


def _per_bar_rules(sleeve: str) -> set:
    """Declared rules a per-SLOT cell cannot hold, read from where the rules are declared.

    Stage 5ZZZ-AS. These leave the lanes for the bar grid, and the classification is derived
    from which CHANNEL the detector reports each gate through -- not from a list here. Stress
    and Calm answer every rule once per slot and lose nothing.
    """
    try:
        from global_index import track1_signals as _sig

        return set(_sig.per_bar_rule_names(sleeve))
    except Exception:                                             # noqa: BLE001
        return set()


def _declared_config(rows: list, sleeve: str) -> list:
    """The sleeve's declared parameters that are NOT entry conditions, shown as facts.

    Stage 5ZZZ-AJ. These sat in the rule lanes and reported "value not published" on every
    slot of every stored session — correctly, and permanently, because none of them is a test
    a slot can pass or fail. One is the window the bars are sliced to before the detector even
    runs; the other two govern a position that does not exist yet at entry time.

    Presented with their thresholds and their reason, so the panel says what the sleeve is
    CONFIGURED to do instead of implying it checked something and could not say what.
    """
    out: list = []
    seen: set = set()
    for r in rows:
        if r.get("sleeve") != sleeve:
            continue
        for c in r.get("rule_checks") or []:
            name = str(c.get("rule") or "")
            if name not in _NOT_ENTRY_CONDITIONS or name in seen:
                continue
            seen.add(name)
            out.append({"rule": name, "label": name.replace("_", " "),
                        "threshold_display": _threshold_display(c.get("threshold")),
                        "reason": _NOT_ENTRY_CONDITIONS[name]})
    return out


def _rule_lanes(rows: list, sleeve: str, slots: list) -> list:
    """Per-slot outcome for every rule this sleeve's detector declares.

    Measured across every stored session (2026-08-25 … 2026-08-28, four days, all sleeves):
    **every strategy rule carries `value: null`** and `source: not_exposed_by_sleeve`. Only
    `gate_allow` and `freshness_allow` are `measured`, and even they publish a verdict without
    a number. So these lanes draw the sequence of VERDICTS the route recorded, and each lane
    says whether a value was ever published rather than plotting one that was not.

    This is the honest shape of the panel's centre. A lane of numbers here would have to
    invent every point on it, and the numbers would be read as the strategy's own.
    """
    _per_bar = _per_bar_rules(sleeve)
    by_slot: dict = {}
    for r in rows:
        if r.get("sleeve") != sleeve:
            continue
        by_slot[str(r.get("slot_id") or "")] = r

    # Rule ORDER comes from the recorded rows, so a detector that adds a rule shows it here
    # without anyone editing a list. Declared once, in the order the route evaluates them.
    order: list = []
    meta: dict = {}
    for r in rows:
        if r.get("sleeve") != sleeve:
            continue
        for c in r.get("rule_checks") or []:
            name = str(c.get("rule") or "")
            if not name:
                continue
            if name in _per_bar:
                # Stage 5ZZZ-AS. Drawn in the bar grid instead, where each cell is one bar and
                # therefore holds exactly one verdict. A lane cell is a SLOT, and within one
                # slot this rule is answered once per bar -- measured on a real session, twelve
                # times pass and ten times fail. There is no single value to put here, which is
                # why it has read "value not published" on every slot record ever written.
                continue
            if name in _NOT_ENTRY_CONDITIONS:
                # Stage 5ZZZ-AJ. Kept out of the lanes, not out of the payload: these are
                # declared by the sleeve and recorded on every row, but none of them is a
                # test a slot can pass or fail, so a lane for them is an empty lane FOREVER —
                # and an operator who learns to skip a permanently empty lane skips the ones
                # beside it that will fill. `_declared_config` reports them as what they are.
                continue
            if name not in meta:
                order.append(name)
                meta[name] = {"threshold": c.get("threshold"),
                              "comparator": str(c.get("comparator") or ""),
                              "detail": str(c.get("detail") or "")}
            elif meta[name].get("threshold") in (None, {}, "") and c.get("threshold") not in (None, {}, ""):
                meta[name]["threshold"] = c.get("threshold")

    lanes = []
    for name in order:
        cells, published = [], 0
        passes = fails = 0
        for s in slots:
            row = by_slot.get(s["slot_id"])
            if row is None:
                cells.append({"slot_id": s["slot_id"], "time_et": s["time_et"],
                              "state": CELL_FUTURE if s["status"] == SLOT_FUTURE
                                       else CELL_NO_RECORD})
                continue
            check = next((c for c in (row.get("rule_checks") or [])
                          if str(c.get("rule") or "") == name), None)
            if check is None:
                # The rule was not evaluated for this slot at all. Not the same as failing it.
                cells.append({"slot_id": s["slot_id"], "time_et": s["time_et"],
                              "state": CELL_NOT_REACHED})
                continue
            value = check.get("value")
            has_value = isinstance(value, (int, float, str)) and not isinstance(value, bool)
            if has_value:
                published += 1
            passed = check.get("passed")
            if passed is True:
                state, passes = CELL_PASS, passes + 1
            elif passed is False:
                state, fails = CELL_FAIL, fails + 1
            elif check.get("not_reached"):
                state = CELL_NOT_REACHED
            else:
                state = _CELL_FROM_SOURCE.get(str(check.get("source") or ""),
                                              CELL_NOT_PUBLISHED)
            cells.append({"slot_id": s["slot_id"], "time_et": s["time_et"], "state": state,
                          "value": value if has_value else None})

        decided = passes + fails
        lanes.append({
            "rule": name,
            "label": name.replace("_", " "),
            "threshold_display": _threshold_display(meta[name]["threshold"]),
            "comparator": meta[name]["comparator"],
            "detail": meta[name]["detail"],
            "cells": cells,
            # The measurable honesty claim, carried in the payload rather than asserted in
            # the UI: how many of this lane's cells came with a number behind them.
            "values_published": published,
            "slots_decided": decided,
            "passed": passes,
            "failed": fails,
            # One line for the lane's right-hand column, and when there is no verdict it
            # names WHICH absence this is. The first version said "value not published" for
            # every undecided lane, including lanes whose slots were stopped by the gate
            # before the rule ran — two different facts printed as one sentence, which is the
            # exact collapse the missing-reason vocabulary above exists to prevent.
            "state_display": (f"{passes}/{decided} pass" if decided
                              else _LANE_ABSENCE.get(
                                  collections.Counter(
                                      c["state"] for c in cells).most_common(1)[0][0],
                                  "no verdict recorded")),
        })
    return lanes


# ── levels ──────────────────────────────────────────────────────────────────────────────
def _levels(rows: list, sleeve: str) -> list:
    """Whatever the sleeve actually published. Today: nothing.

    Every rule in the diagnostics carries `source: not_exposed_by_sleeve` and a null value —
    the detectors return a verdict, not the numbers behind it. So this returns an empty list
    and the caller says so in words. It is written as a scan rather than as `return []` so
    that the day a detector starts publishing a price, it appears here without anyone having
    to remember this function exists.
    """
    out = []
    for r in rows:
        if r.get("sleeve") != sleeve:
            continue
        for check in r.get("rule_checks") or []:
            if check.get("source") != "measured":
                continue
            value = check.get("value")
            name = str(check.get("rule") or "")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            if not any(w in name for w in ("price", "entry", "stop", "target", "level")):
                continue
            out.append({"kind": ("entry" if "entry" in name else
                                 "stop" if "stop" in name else
                                 "target" if "target" in name else "reference"),
                        "label": name.replace("_", " "), "price": float(value),
                        "source": "strategy_evidence", "slot_id": str(r.get("slot_id") or "")})
    return out


#: Stage 5ZZP. What each sleeve's detector actually publishes, so the panel can say what is
#: missing rather than showing an empty list for four different reasons.
NOT_COMPUTED_UNTIL_ENTRY = "not_computed_until_entry"
NOT_AVAILABLE = "not_available"
NOT_APPLICABLE = "not_applicable"

#: Stage 5ZZQ. How a sleeve's setup FORMS, read from its detector rather than assumed.
#:
#: The distinction the panel needs is not "does this sleeve have an entry level" but "is there
#: anything a PRICE LINE could honestly be drawn at before a candidate exists". For Stress
#: there is not: the setup is decided by counts and an average across a four-instrument basket
#: at 10:30, and no single price on the chart is the thing being waited for. Drawing a line
#: there would invent a trigger the strategy does not have.
#: Stage 5ZZR. Why a value is absent, kept as five distinct answers. The panel renders each
#: differently, and collapsing any two of them is how "nobody looked" comes to read as
#: "we looked and there was nothing".
MISSING_NOT_YET = "not_yet"                       # its time has not come
MISSING_NO_RECORD = "no_record"                   # its time passed and nothing was written
MISSING_REFUSED = "refused"                       # it ran and declined
MISSING_DATA = "missing_data"                     # the inputs were not there
MISSING_NOT_REPORTED = "not_reported_by_detector"  # computed inside, never returned


#: Stage 5ZZZ-AX. The four series the setup card charts, mapped from the row labels the
#: detector publishes. Named here rather than on the page: the page must not have to know
#: which of the eight rows are commensurable, and a label that changes shape should break the
#: chart loudly rather than draw a flat line.
_SERIES_LABELS = {
    "close": "Close used",
    "ema": None,          # resolved per sleeve: the period is in the label
    "atr": "ATR (14 x 5-min bars)",
    "daily_atr": "Daily ATR",
    "volume": "Volume",
    "avg_volume": "Average volume (10 bars)",
}


def _slot_series(root, day: str, sleeve: str) -> list:
    """One point per recorded slot, carrying only what the chart draws.

    Kept narrow on purpose. The blocks hold gates, grids and price levels, and shipping those
    per slot would multiply the payload of an endpoint that is polled.
    """
    out = []
    for rec in _sd.recorded_series(root, day, sleeve):
        vals = rec.get("values") or {}
        ema = next((v for k, v in vals.items() if str(k).startswith("Trend filter")), None)
        # Stage 5ZZZ-BO. The threshold the surge gate actually compared against, copied from
        # the slot's own grid row. NOT recomputed, and NOT read from the declared table: that
        # table maps both per-bar volume gates onto one name whose threshold
        # (`rel_volume_max` 2.0 on `rvol_slot20`) is neither gate's. The engine compares the
        # resume bar against the ten-bar average times its own multiple, and reports that
        # number on the gate. Absent on a day the gate was never reached, which is honest:
        # there was no threshold, because nothing was compared.
        point = {"slot_time": rec.get("slot_time"), "bars": rec.get("bars_evaluated"),
                 "last_bar_ts": rec.get("last_bar_ts"),
                 "last_bar_complete": rec.get("last_bar_complete"), "ema": ema,
                 "surge_threshold": rec.get("surge_threshold"),
                 # Stage 5ZZZ-BP. Copied, never recomputed. The chart draws four series on a
                 # day the regime gate refused every slot, and without the verdict it has no
                 # way to say that nothing it shows was consumed by a rule.
                 "regime": rec.get("regime"), "regime_passed": rec.get("regime_passed")}
        for key, label in _SERIES_LABELS.items():
            if label:
                point[key] = vals.get(label)
        out.append(point)
    return out

PRICE_BOUNDARY = "price_boundary"
METRIC_BOUNDARY = "metric_boundary"
ENTRY_AFTER_SETUP_ONLY = "entry_after_setup_only"
TWO_PHASE = "two_phase"
NOT_PUBLISHABLE = "not_publishable"

#: Proof, from source, for each classification — carried in the payload so the claim travels
#: with the data instead of living only in a report nobody has open.
BOUNDARY_KIND: dict = {
    "roska4_stress": (METRIC_BOUNDARY,
                      "track1_stress_mnq.entry_conditions compares four basket COUNTS and an "
                      "average gap against StressParams; no single price is the trigger, so a "
                      "price line before setup would be invented"),
    "global_nkd": (ENTRY_AFTER_SETUP_ONLY,
                   "track1_normal_r4.detect_entry_for_slot returns SwingSetup(entry, stop) "
                   "when a bar signals and None otherwise; the entry comes from a per-bar "
                   "signal function, not from a standing level that exists beforehand"),
    "roska4_swing": (ENTRY_AFTER_SETUP_ONLY,
                     "same detector as global_nkd at a different ema_period"),
    "roska4_calm": (TWO_PHASE,
                    "track1_calm_a runs a DECIDE half and an OBSERVE half; the 10:00 reference "
                    "and the planned stop are OBSERVE-only and must not appear at DECIDE"),
}


def _pct(v) -> str:
    try:
        return f"{float(v) * 100:+.2f}%"
    except (TypeError, ValueError):
        return str(v)


def _settle_levels_note(blk: dict) -> None:
    """Say "no levels" only when there are none to show, from ANY source.

    Measured on 2026-08-28, and this is the finding the stage was opened on: the Stress sleeve
    published a trigger at 29,592.50, a planned stop at 29,652.62 and a session open at
    29,615.25 - and the chip above them read "Strategy levels unavailable". The note was
    computed from the SIGNAL ROWS alone, which is where levels used to come from, and it kept
    answering for a question the diagnostics stages had since answered elsewhere.

    A panel that contradicts itself in two places costs more than one that says nothing: the
    reader has to work out which half to believe, and there is no way to do that from the page.

    The three states are kept apart, because they are three different facts for an operator:
      levels exist and are ARMED     -> nothing to say; the chart draws them
      levels exist and are NOT armed -> say so, in the sleeve's own words
      no levels at all               -> the original note, unchanged
    """
    st = blk.get("strategy") or {}
    sb = blk.get("setup_boundary") or {}
    published = list(blk.get("levels") or []) or list(
        st.get("price_levels") or sb.get("price_levels") or [])
    if not published:
        return                                       # LEVELS_NOT_EXPOSED already stands
    armed = bool(st.get("levels_armed") or sb.get("levels_armed"))
    if armed:
        blk["levels_note"], blk["levels_detail"] = "", ""
        return
    # The sleeve's own sentence where it wrote one - it names the hour and the gate, which a
    # sentence composed here could only restate less exactly.
    blk["levels_note"] = st.get("levels_note") or sb.get("levels_note") or LEVELS_COMPUTED_UNARMED
    blk["levels_detail"] = LEVELS_UNARMED_DETAIL


def _setup_boundary(sleeve: str, spec: dict, strategy: dict, slots: list) -> dict:
    """What would have to happen for a candidate to exist, in the sleeve's own terms.

    Never invents a price. `price_levels` stays empty for every sleeve whose setup is not a
    price comparison, and the panel is told WHY by `boundary_type` rather than being left to
    infer it from an empty list.
    """
    kind, proof = BOUNDARY_KIND.get(sleeve, (NOT_PUBLISHABLE, "no classification recorded"))
    out = {"schema": "track1_setup_boundary/1", "sleeve": sleeve,
           "boundary_type": kind, "boundary_proof": proof, "side": "none",
           "status": NOT_AVAILABLE, "price_levels": [], "metrics": [],
           "nearest_failed_condition": None, "summary": ""}

    st = strategy or {}
    if kind == METRIC_BOUNDARY:
        if st.get("status") in ("missing_bars", "session_not_judgeable"):
            out["status"] = "missing_data"
            out["summary"] = f"Setup not judgeable · {st.get('detail') or ''}".strip(" ·")
            return out
        rules = st.get("rules") or []
        if not rules:
            out["summary"] = "Setup metrics not read"
            return out
        out["status"] = "available"
        out["side"] = "short"          # the Stress sleeve is short-only by construction
        # Stage 5ZZZ-B. Stress is reconstructed too, and says so. `basket_state` is computed
        # now, from the persisted bar store, for a gate that was decided at 10:30 — which is
        # exactly what "reconstructed" means. It read as blank until this stage, and a panel
        # that labels three sleeves and leaves the fourth unlabelled invites the reader to
        # assume the unlabelled one is the recorded one.
        out["diagnostics_source"] = (strategy or {}).get("diagnostics_source") or RECONSTRUCTED_TODAY
        out["decided_at_et"] = st.get("decided_at_et") or ""
        # Levels travel in the payload whatever their state; `armed` decides whether the page
        # may DRAW them. Withholding them entirely would hide a number an operator wants to
        # read, and drawing an unarmed one would put a trigger on the chart that is not live.
        out["price_levels"] = list(st.get("price_levels") or [])
        out["levels_armed"] = bool(st.get("levels_armed"))
        out["levels_note"] = st.get("levels_note") or ""
        for r in rules:
            value, thr = r.get("value"), r.get("threshold")
            cmp_ = r.get("comparator") or ""
            frac = r.get("unit") == "fraction"
            distance = None
            if isinstance(value, (int, float)) and isinstance(thr, (int, float)):
                distance = (thr - value) if cmp_ == ">=" else (value - thr)
                distance = round(float(distance), 6)
            metric = {"id": r.get("id"), "label": r.get("label"),
                      "value": value, "threshold": thr, "comparator": cmp_,
                      "unit": r.get("unit"), "passed": r.get("passed"),
                      "distance": None if (distance is None or r.get("passed")) else distance,
                      "source": r.get("source")}
            if frac:
                metric["display_value"] = _pct(value)
                metric["display_threshold"] = f"{cmp_} {_pct(thr)}"
                if metric["distance"] is not None:
                    metric["display_distance"] = (f"{abs(distance) * 100:.2f} percentage "
                                                  f"points away")
            else:
                metric["display_value"] = str(value)
                metric["display_threshold"] = f"{cmp_} {thr}"
                if metric["distance"] is not None:
                    noun = "more" if cmp_ == ">=" else "fewer"
                    metric["display_distance"] = f"{abs(distance):g} {noun} needed"
            out["metrics"].append(metric)

        failed = [m for m in out["metrics"] if m["passed"] is False]
        if not failed:
            out["summary"] = "Setup conditions met"
        else:
            # The NEAREST failure, not the first: an operator asks how close the day came, and
            # the first-declared rule is an ordering accident rather than an answer.
            def _closeness(m):
                d = m.get("distance")
                if d is None:
                    return float("inf")
                span = abs(m["threshold"]) or 1.0
                return abs(d) / span
            near = sorted(failed, key=_closeness)[0]
            out["nearest_failed_condition"] = {
                "id": near["id"], "label": near["label"],
                "display": f"{near['label']} {near['display_value']}, "
                           f"needs {near['display_threshold']}",
                "source": "sleeve_detector"}
            out["summary"] = (f"No setup · {near['label']} "
                              f"{near.get('display_distance') or 'short of its threshold'}")
        return out

    if kind == ENTRY_AFTER_SETUP_ONLY:
        out["status"] = NOT_APPLICABLE
        out["summary"] = "Entry forms only after a setup bar appears"
        # Stage 5ZZR. The four things this detector actually consumes, named so an operator can
        # see WHAT is looked at even while the values are unreported.
        #
        # These are `make_signal_fn(prev_bar, resume_bar, ema, atr, regime, avgv)` — the EMA at
        # this sleeve's own period, the daily ATR, the regime label and the ten-bar average
        # volume. They are computed inside `_scan_window` and not returned, which is the same
        # shape the Stress rule values had before Stage 5ZZP and is fixable the same way.
        #
        # They are NOT the basket metrics. Breadth, gapdown count and basket gap belong to
        # `track1_stress_mnq` and this detector never evaluates them; listing them here would
        # say this sleeve checks something it does not.
        # Stage 5ZZZ-B. The values themselves, now that the detector reports them.
        #
        # Stage 5ZZR wrote the paragraph above and could only name the variables. The sleeve
        # grew an observer seam in this stage, so what stood here as four "Not reported by
        # detector" cards is the numbers the detector actually looked at — and the block says
        # whether they were RECORDED by the slot or RECONSTRUCTED afterwards.
        #
        # The fallback is kept, not deleted. A session whose bars are not on disk, or a day the
        # detector could not be replayed for, still has to say something, and "not reported" is
        # the honest answer there rather than a blank card.
        diag = (strategy or {}).get("diagnostics") or {}
        rows = diag.get("rows") or []
        period = 10 if sleeve == "global_nkd" else 50
        if rows:
            out["diagnostics_source"] = diag.get("diagnostics_source")
            out["last_bar_ts"] = diag.get("last_bar_ts")
            # Stage 5ZZZ-AW. Whether that bar had CLOSED when the slot ran. NKD slots fire on
            # the five-minute boundary, so its newest bar is seconds old and its volume reads
            # near zero at nearly every slot -- a true reading of a bar that has barely begun.
            # None means nobody measured it, and the page must not print it as "still forming".
            out["last_bar_complete"] = diag.get("last_bar_complete")
            out["slot_ran_at"] = diag.get("slot_ran_at")
            out["bars_evaluated"] = diag.get("bars_evaluated")
            out["reconstructed_at"] = diag.get("reconstructed_at")
            out["reconstructed_through"] = diag.get("reconstructed_through")
            out["warning"] = diag.get("warning") or ""
            out["summary"] = diag.get("summary") or out["summary"]
            out["nearest_failed_condition"] = diag.get("nearest_failed_condition")
            out["price_levels"] = diag.get("price_levels") or []
            out["levels_armed"] = bool(diag.get("levels_armed"))
            for r in rows:
                out["metrics"].append({
                    "id": None, "label": r["label"], "value": r["value"],
                    "threshold": r["threshold"], "comparator": r["comparator"],
                    "unit": r["unit"], "passed": r["passed"], "distance": None,
                    # Stage 5ZZZ-AW. The Regime row now carries a verdict, and a verdict
                    # without what it was measured against is half a sentence.
                    "display_value": r["display_value"],
                    "display_threshold": (", ".join(str(x) for x in r["threshold"])
                                          if isinstance(r["threshold"], (list, tuple))
                                          else ("" if r["threshold"] is None
                                                else str(r["threshold"]))),
                    "missing": r["missing"],
                    "source": r["missing"] or diag.get("diagnostics_source")})
            return out
        out["diagnostics_source"] = diag.get("diagnostics_source") or MISSING_NOT_REPORTED
        for label in (f"Trend filter (EMA {period})", "Volume vs 10-bar average",
                      "ATR (14 x 5-min bars)", "Daily ATR", "Regime"):
            out["metrics"].append({
                "id": None, "label": label, "value": None, "threshold": None,
                "comparator": "", "unit": None, "passed": None, "distance": None,
                "display_value": "Not reported by detector",
                "display_threshold": "", "missing": MISSING_NOT_REPORTED,
                "source": MISSING_NOT_REPORTED})
        return out
    if kind == TWO_PHASE:
        out["status"] = NOT_APPLICABLE
        out["summary"] = "Two-phase sleeve; setup values are phase-specific"
        return out
    out["status"] = NOT_PUBLISHABLE
    return out


#: Stage 5ZZZ-B. The reconstruction is EXPENSIVE and this endpoint is polled.
#:
#: Measured before this cache existed: 57s per warm build. `_cache_for` — the detector's own
#: EMA/ATR pass over the whole 3.3-million-row frame — is 14.3s and is not internally memoised,
#: and the reconstruction calls it four times. `read_parquet` is 0.15s of that; the frame is not
#: the problem, the pass over it is.
#:
#: Shortening the frame is not available as a fix. The EMA is recursive over the full history, so
#: a truncated frame produces different numbers than the detector saw — and a reconstruction that
#: does not match what the detector would see is worth nothing.
#:
#: So: stale-but-usable, refreshed out of band. The same pattern `schedule_status._running_
#: schedulers` uses for the process scan, and for the same reason — a page that waits a minute
#: for a panel is a page nobody keeps open. The TTL is the bar cadence, because that is the only
#: interval on which the answer can actually change: the window truncates on five-minute bars.
_RECON_TTL_SECONDS = 300.0
_recon_cache: dict = {}
_recon_lock = _threading.Lock()


def _recon_refresh(key, fn) -> None:
    try:
        value, err = fn(), ""
    except Exception as exc:                                      # noqa: BLE001
        value = (_recon_cache.get(key) or {}).get("value")
        err = f"{type(exc).__name__}: {exc}"
    with _recon_lock:
        _recon_cache[key] = {"at": _time.monotonic(), "value": value,
                             "refreshing": False, "error": err}


def _recon_cached(key, fn):
    """Serve the last answer immediately; compute in the background, never inline.

    Stage 5ZZZ-S changed the COLD branch. It used to pay the reconstruction inline, on the
    reasoning that showing an empty panel on first load was worse than waiting. Measured, that
    wait is **71s** in a fresh process — the four `_swing_cache` passes resample the whole bar
    history, 11,410 `resample_5m` calls — and it blocks the ENTIRE market-view payload, not
    just the one panel that needs it. Every other sleeve, the regime block and the levels note
    all wait behind a panel they do not depend on.

    So the cold branch now spawns the same worker the aged-out branch already used and returns
    nothing for this key. The caller renders that as an explicit `warming` state naming why —
    which is not the empty panel the original trade was avoiding, because an empty panel says
    nothing and this one says what it is doing and that it will fill in.
    """
    with _recon_lock:
        entry = _recon_cache.get(key)
        if entry is not None:
            age = _time.monotonic() - entry["at"]
            if age < _RECON_TTL_SECONDS or entry.get("refreshing"):
                return entry["value"]
            entry["refreshing"] = True
        else:
            # Claim the key BEFORE releasing the lock. This endpoint is polled, so without the
            # placeholder every poll during the first 71s would spawn its own worker and they
            # would all recompute the same thing.
            _recon_cache[key] = {"at": _time.monotonic(), "value": None,
                                 "refreshing": True, "error": ""}
    _threading.Thread(target=_recon_refresh, args=(key, fn), daemon=True).start()
    with _recon_lock:
        return (_recon_cache.get(key) or {}).get("value")


def warm(root, *, day=None, timeout=300.0, poll=0.5) -> bool:
    """Build repeatedly until every deferred panel has been computed. `True` if all settled.

    For TESTS and offline callers. **The request path must never call this** — a request that
    waits is the exact thing Stage 5ZZZ-S removed. It exists because a caller that wants to
    assert on rule values needs the values, and the honest way to get them is to wait for the
    same background worker a browser would wait for, rather than to weaken the assertion.
    """
    deadline = _time.monotonic() + timeout
    while True:
        payload = build(root, day=day) if day else build(root)
        pending = [n for n, b in (payload.get("sleeves") or {}).items()
                   if "still being computed" in ((b.get("strategy") or {}).get("detail") or "")]
        if "still being computed" in ((payload.get("calm") or {}).get("unavailable") or ""):
            pending.append("roska4_calm")
        if not pending:
            return True
        if _time.monotonic() >= deadline:
            return False
        _time.sleep(poll)


def _recon_state(key) -> tuple:
    """`(state, error)` for a key: absent, warming, failed or ready.

    Kept separate from the value so the caller can tell "still computing" from "computed and
    there was nothing", and report the difference instead of collapsing both to empty.
    """
    with _recon_lock:
        entry = _recon_cache.get(key)
    if entry is None:
        return "absent", ""
    if entry.get("value") is None:
        return ("warming", "") if entry.get("refreshing") else ("failed", entry.get("error", ""))
    return "ready", entry.get("error", "")


#: The regime label map is the same call the live slot makes, with the parameters the route's
#: own regime record names. Cached on the CSV's mtime because it fits an HMM, and this endpoint
#: is polled — Stage 5ZZQ measured what an uncached per-request model fit does to a page.
_label_cache: dict = {}


def _label_map(root: Path) -> dict:
    """`{day: regime}` exactly as `track1_live_source._label_map` builds it.

    Same function, same parameters, read from the record the route publishes rather than
    restated here — the alternative is a second copy of the model's configuration that drifts
    from the one the sleeve decided under.
    """
    import pandas as pd
    from futures._validated_core import benchmark_daily, label_regimes

    rec = regime(root) or {}
    inputs = rec.get("inputs") or {}
    csv = inputs.get("benchmark_csv") or "spy_daily_live.csv"
    start = inputs.get("start") or "2018-01-01"
    states = int(inputs.get("n_states") or 3)
    fit_end = inputs.get("fit_end")
    path = Path(root) / csv
    key = (str(path), path.stat().st_mtime if path.exists() else 0, start, states, fit_end)
    hit = _label_cache.get(key)
    if hit is None:
        raw = label_regimes(benchmark_daily(str(path)), start, states, fit_end)
        hit = {pd.Timestamp(k).normalize(): v for k, v in raw.items()}
        _label_cache.clear()
        _label_cache[key] = hit
    return hit


def _normal_r4_reconstruction(root: Path, sleeve: str, day: str, spec: dict,
                              out: dict, *, now=None) -> dict:
    """Replay the detector for one session and report what it looked at.

    The parameters are the ones the live slot uses, taken from `track1_live_source`'s own call
    sites rather than chosen here: NKD runs a ten-bar trend filter with the context filter OFF,
    Swing runs the default period with it ON. Getting either wrong would report a sleeve on
    rules it does not use.
    """
    import pandas as pd
    from global_index import track1_normal_r4 as NR
    from global_index import track1_params as tp
    from global_index import track1_strategy_diagnostics as SD

    inst = spec["instrument"]
    path = _store_path(inst)
    if not path or not Path(path).exists():
        out["detail"] = f"no persisted bar store for {inst}"
        return out

    frame = pd.read_parquet(path)
    labels_raw = _label_map(root)
    if sleeve == "global_nkd":
        from global_index.regime import RegimeLabels
        labels = RegimeLabels(pd.Series(labels_raw).sort_index(), lag_days=1)
        params = NR.NormalR4Params(ema_period=10, fill_law=tp.LIVE_FILL_LAW)
        context = False
    else:
        # Stage 5ZZZ-Q. Swing now reads the previous session's label, exactly as NKD does and
        # exactly as the artifact regeneration wraps it. This mirrors the live call site, which
        # is the only thing this reconstruction is for: a replay handed a different regime
        # object from the slot would show what the slot did NOT see.
        from global_index.regime import RegimeLabels as _RL

        labels = _RL(pd.Series(labels_raw).sort_index(), lag_days=1)
        params = NR.NormalR4Params(fill_law=tp.LIVE_FILL_LAW)
        context = True

    regime_csv = str(Path(root) / ((regime(root) or {}).get("inputs") or {})
                     .get("benchmark_csv", "spy_daily_live.csv"))
    short_days = NR.short_days_from_csv(regime_csv, params.spy_short_filter)

    # The caller's clock, defaulting to now. `build(now=...)` sets the instant the whole
    # payload describes, and a reconstruction that ignored it would answer about a different
    # moment than the page it appears on — and would make "stops at now" untestable, because
    # no test could ask it about a moment other than the present.
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=ET)
    obs = SD.NormalR4Observer()
    setup = NR.detect_entry_for_slot(frame, labels, inst, pd.Timestamp(day), now, params,
                                     short_days=short_days,
                                     apply_context_filter=context, observer=obs)

    # Stage 5ZZZ-B. If the detector stopped at a gate BEFORE it reached the bars, walk the
    # window for observation only.
    #
    # The reason this is worth doing: on a Calm morning the answer "this sleeve trades Normal"
    # is correct and complete about the DECISION, and tells an operator nothing about what the
    # instrument is doing. The four variables the sleeve would decide on exist either way, and
    # the point of the panel is to show them.
    #
    # It is the SAME `_scan_window` the detector calls, with the same strategy, the same
    # parameters and the same signal function. Its return value is thrown away — nothing here
    # decides anything, and the gate that already refused stays refused and stays reported.
    # Recomputing an EMA locally would have been the alternative, and that is the second
    # implementation this sleeve's own docstring forbids.
    if setup is None and obs.last_bar is None:
        try:
            _observe_window_only(frame, labels, inst, day, now, params, context, obs)
        except Exception:                                          # noqa: BLE001
            pass

    block = SD.normal_r4_block(
        sleeve=sleeve, slot_id="", ema_period=params.ema_period, observer=obs, setup=setup,
        data_identity=f"{Path(path).name}", source=SD.RECONSTRUCTED,
        reconstructed_through=now,
        # Stage 5ZZZ-G. Described from the object that was actually passed above, so the panel
        # can say WHY two sleeves running one detector report different regimes.
        regime_basis_note=SD.regime_basis(labels))

    return _apply_r4_block(out, block)


def _apply_r4_block(out: dict, block: dict) -> dict:
    """Map one diagnostics block onto the strategy payload, whatever produced it.

    Stage 5ZZZ-AH. This was the tail of the RECONSTRUCTION and could therefore only ever
    describe a replay. It reads no source label and decides nothing from one - it copies the
    block's own `diagnostics_source` outward - so the identical mapping serves a block the slot
    RECORDED while it ran. Both are built by the same `normal_r4_block`, from the same observer
    contract; the only difference between them is which of the two wrote it, and that is the
    one thing this function must pass through rather than flatten.
    """
    # Stage 5ZZZ-BP. A block carries the display string its writer chose, so a wording fix
    # reached the screen only from the next slot on. Applied to the COPY the panel draws; the
    # stored record is untouched and keeps saying what the slot said when it ran.
    block = _sd.explain_recorded_absences(block)
    out["diagnostics"] = block
    # Stage 5ZZZ-F. The source, on the block the payload contract is read from. It was reachable
    # only at `strategy.diagnostics.diagnostics_source`, one level down, so anything reading the
    # strategy block itself saw an unlabelled answer - and an unlabelled reconstruction read as a
    # recorded one, which is the single distinction these stages exist to keep.
    out["diagnostics_source"] = block["diagnostics_source"]
    out["rules"] = [
        {"id": None, "label": r["label"], "value": r["value"], "threshold": r["threshold"],
         "comparator": r["comparator"], "unit": r["unit"], "passed": r["passed"],
         "display_value": r["display_value"], "display_threshold": "",
         "source": block["diagnostics_source"], "missing": r["missing"]}
        for r in block["rows"]]
    out["first_failed"] = block["nearest_failed_condition"]
    out["detail"] = block["summary"]
    out["status"] = "set_up" if block["setup"] else "no_setup"
    out["price_levels"] = block["price_levels"]
    out["levels_armed"] = block["levels_armed"]
    out["levels_note"] = "" if block["levels_armed"] else block["summary"]
    return out


def _observe_window_only(frame, labels, inst, day, now, params, context, obs) -> None:
    """Delegates. Stage 5ZZZ-AV promoted the body into the detector module, where the live slot
    can reach it too -- two copies of the window set-up is two chances to drift, and the clock
    handling in it is the trap that once overwrote 1,050 frozen NKD bars."""
    from global_index import track1_normal_r4 as NR

    NR.observe_window_only(frame, labels, day, now, params,
                           apply_context_filter=bool(context), observer=obs)


def _apply_stress_block(out: dict, block: dict) -> dict:
    """One recorded Stress block, mapped into the fields the panel already reads.

    Stage 5ZZZ-BB. The SAME field names the reconstruction fills, so the page needs no second
    reader and cannot end up describing the two sources differently. Nothing is recomputed:
    every value, threshold, comparator and verdict is copied from what the detector reported
    when the slot ran.

    Rows and gates are built from ONE list in ONE order by `stress_block`, so they pair by
    POSITION. Pairing by label would look tidier and would be wrong the day two conditions
    share a display string.
    """
    gates = block.get("gates") or []
    rows = block.get("rows") or []
    rules = []
    for i, g in enumerate(gates):
        r = rows[i] if i < len(rows) else {}
        # A row whose verdict is None is a condition the detector did not compare -- a
        # nullable threshold left unset. It is reported, and it does not vote.
        applicable = r.get("passed") is not None
        rules.append({
            "id": g.get("gate"),
            "label": r.get("label") or g.get("gate"),
            "value": g.get("value"),
            "threshold": g.get("threshold"),
            "comparator": r.get("comparator") or "",
            "unit": r.get("unit") or "",
            "passed": g.get("passed"),
            "source": "sleeve_detector" if applicable else NOT_APPLICABLE,
        })
    out["rules"] = rules
    out["first_failed"] = (block.get("nearest_failed_condition") or {}).get("gate")
    out["diagnostics_source"] = block.get("diagnostics_source")
    out["detail"] = block.get("summary") or ""
    out["status"] = "set_up" if block.get("setup") else (block.get("reason") or "unknown")
    return out


def _strategy(root: Path, sleeve: str, day: str, spec: dict, *, now=None) -> dict:
    """The sleeve's own rule values for this session, from the detector.

    Only Stress is wired here, and that is a scope statement rather than an oversight:

      Stress   `basket_state` returns every rule value, its threshold and which one failed
               first. Reported in full.
      NKD      the detector returns `SwingSetup(entry, stop, daily_atr, regime)` when a setup
      Swing    exists and `None` when it does not, so entry and stop ARE published on a
               signal day and there is nothing to publish on a quiet one. Naming that as
               `not_computed_until_entry` is the honest answer; inventing a distance to an
               entry the detector never formed would not be.
      Calm     `entry_conditions` already returns a dict of its own rule values, but the live
               path reaches it through the two-phase contract and the DECIDE half must not be
               shown values the OBSERVE half produces. Left unwired rather than wired wrongly.

    Never raises: a panel that 500s tells an operator less than one that names the part it
    could not read.
    """
    out = {"sleeve": sleeve, "instrument": spec["instrument"], "session_date": day,
           "rules": [], "entry": None, "risk": None, "price_levels": [],
           "levels_armed": False, "levels_note": "",
           "status": NOT_AVAILABLE, "detail": "", "first_failed": None}
    if sleeve in ("global_nkd", "roska4_swing"):
        # Stage 5ZZZ-B. The four variables this sleeve decides on, RECONSTRUCTED for today.
        #
        # Until this stage the answer here was "there are no pre-entry rule values to publish",
        # which was true of the detector's RETURN and false of the detector. It computes a trend
        # filter, an ATR and a ten-bar average volume for every bar it looks at and discarded
        # them; the sleeve grew an observer seam so they come out.
        #
        # This is a RECONSTRUCTION and it says so. It reads the persisted bar store rather than
        # the live provider join the slot itself used, so its last bar can differ from the one
        # the slot saw. Nothing here may satisfy a gate.
        try:
            # A caller that named an instant gets that instant, computed. Only the LIVE path —
            # `now=None`, which is what the endpoint uses — is served from the cache.
            #
            # The key is deliberately stable: sleeve, day and store. Putting the clock or the
            # file's mtime in it would mint a new key every bar, and a new key has nothing to
            # serve stale, so every append would pay the full minute inline. Freshness is the
            # TTL's job, and `last_bar_ts` on the block says exactly which bar the answer used.
            # Stage 5ZZZ-AH. What the SLOT recorded beats what the dashboard can replay, and
            # it is asked for first rather than used as a fallback.
            #
            # The replay reads the persisted bar store; the slot read the live provider join.
            # Those are not the same data, and the block says so - the reconstruction carries
            # "computed after the fact; not official runtime evidence" precisely because its
            # last bar can differ from the one the slot decided on. So a session that HAS a
            # recorded block was being described by a replay of itself, with the weaker of two
            # available answers shown as though it were the only one.
            #
            # Read on every call rather than cached: the file is one small block per slot per
            # sleeve, and a cache here would serve a session's early slots after later ones
            # had been written. The replay is the expensive path and keeps its cache.
            recorded = _sd.recorded_for(root, day, sleeve)
            if recorded and (recorded.get("rows") or []):
                blk = _apply_r4_block(dict(out), recorded)
                # Stage 5ZZZ-AX. The SESSION beside the snapshot. Same file, same read, one
                # small block per slot -- so this costs an extra pass over a list already in
                # memory, and the panel stops having to infer a session from one slot.
                blk["slot_series"] = _slot_series(root, day, sleeve)
                blk["slot_series_session"] = day
                return blk
            if now is not None:
                return _normal_r4_reconstruction(root, sleeve, day, spec, out, now=now)
            _key = (sleeve, day, str(_store_path(spec["instrument"])))
            cached = _recon_cached(
                _key, lambda: _normal_r4_reconstruction(root, sleeve, day, spec, dict(out),
                                                        now=None))
            if cached is not None:
                return cached
            # Stage 5ZZZ-S: say which of the two it is. "Still computing" and "computed and
            # came back empty" are different facts about the route, and an empty panel that
            # means either is the same as an empty panel that means nothing.
            _state, _err = _recon_state(_key)
            out["status"] = NOT_AVAILABLE
            if _state in ("warming", "absent"):
                out["detail"] = (
                    "the detector replay for this session is still being computed. The first "
                    "request after a backend restart pays a full pass over the bar history; "
                    "it is running now and this panel fills in on a later poll.")
            elif _err:
                out["detail"] = f"the detector could not be replayed for this session ({_err})"
            else:
                out["detail"] = ("the detector replay returned nothing for this session")
            return out
        except Exception as exc:                                  # noqa: BLE001
            out["detail"] = (f"the detector could not be replayed for this session "
                             f"({type(exc).__name__}: {exc})")
            out["status"] = NOT_AVAILABLE
            return out
    if sleeve != "roska4_stress":
        out["detail"] = ("this sleeve's detector returns an entry and a stop when a setup "
                         "exists and nothing when it does not, so there are no pre-entry "
                         "rule values to publish")
        out["status"] = NOT_COMPUTED_UNTIL_ENTRY
        return out
    # Stage 5ZZZ-BB. The slot's OWN account first, the replay only when there is none.
    #
    # The reconstruction below reads the parquet stores and judges the basket again. That is a
    # fair answer for a session nobody recorded, and the wrong one for a session that WAS
    # recorded: the store is appended after a session closes, so during a live session its
    # newest bars are the previous day's. Same asymmetry the Normal-R4 branch settled -- old
    # numbers under a card labelled with today's session are worse than none.
    recorded = _sd.recorded_for(root, day, sleeve)
    if recorded and (recorded.get("rows") or []):
        blk = _apply_stress_block(dict(out), recorded)
        blk["slot_series"] = _slot_series(root, day, sleeve)
        blk["slot_series_session"] = day
        return blk
    try:
        import pandas as pd
        from global_index import track1_stress_mnq as SM
        from global_index import run_live_day_track1 as rl

        paths = rl.default_data_paths() or {}
        need = sorted(set(SM.BREADTH_BASKET) | set(SM.StressParams().instruments))
        if any(i not in paths for i in need):
            out["detail"] = "the basket's bar stores are not all configured"
            return out
        params = SM.StressParams()
        key = tuple(sorted((i, Path(paths[i]).stat().st_mtime) for i in need))
        hit = _slice_cache.get(key)
        if hit is None and now is not None:
            # A caller that named an instant gets that instant, computed — the same rule the
            # sleeve reconstructions follow. Only the LIVE path (`now=None`, what the endpoint
            # uses) is served from the cache and deferred.
            frames = {i: pd.read_parquet(paths[i]) for i in need}
            hit = SM.daily_slices(frames, params)
            if len(_slice_cache) >= _SLICE_CACHE_MAX:
                _slice_cache.clear()
            _slice_cache[key] = hit
        if hit is None:
            # Stage 5ZZZ-S: computed in the background instead of on the request path. The
            # key, and therefore what invalidates this, is unchanged.
            _st = _slice_warm(key, paths, need, params)
            out["status"] = NOT_AVAILABLE
            out["detail"] = (
                "the basket's daily slices are still being computed; the first request after "
                "a backend restart reads the four bar stores, and this panel fills in on a "
                "later poll" if _st == "warming" else
                f"the basket's daily slices could not be computed ({_st})")
            return out
        bars, prev_close = hit
        state = SM.basket_state(pd.Timestamp(day), bars, prev_close, params)
        out["rules"] = [
            {"id": c["id"], "label": c["label"], "value": c["value"],
             "threshold": c["threshold"], "comparator": c["comparator"],
             "unit": c["unit"], "passed": c["passed"],
             "source": "sleeve_detector" if c["applicable"] else NOT_APPLICABLE}
            for c in state.get("checks") or []]
        out["first_failed"] = state.get("first_failed")
        # Stage 5ZZZ-F. Stress is a reconstruction too and now says so on its own block: this is
        # `basket_state` computed now, from the persisted store, for a gate decided at 10:30.
        out["diagnostics_source"] = RECONSTRUCTED_TODAY
        # ...and the hour it was decided at, taken from the detector's own parameter rather
        # than written here. An operator reading four metric values needs to know they are the
        # 10:30 bar's values and not this minute's, and the panel had stopped saying so - the
        # only surviving mention was inside the sentence about unarmed levels, which does not
        # appear at all on a day the gate passes.
        out["decided_at_et"] = str(params.setup_time)
        out["detail"] = state.get("detail") or ""
        out["status"] = "set_up" if state.get("set_up") else (state.get("reason") or "unknown")

        # Stage 5ZZR. The price stage, which Stage 5ZZQ reported as absent and which is not.
        #
        # `session_context` returns `pre_low` and `pre_high` for every judgeable session,
        # whether or not the basket gate passed, and `first_low_break` scans for a 1-minute low
        # through `pre_low` between 10:35 and now. So the trigger IS a real published price —
        # measured on 2026-08-27, a day the gate FAILED: MNQ pre_low 29,575.25, pre_high
        # 29,632.75, giving a planned stop of 29,662.38.
        #
        # `armed` is what keeps the earlier rule intact. A level computed but not in play must
        # not be drawn on the chart, and the difference between "no level exists" and "the
        # level exists and the gate did not pass" is exactly what an operator is asking about.
        ctx = (state.get("contexts") or {}).get(spec["instrument"]) or {}
        armed = bool(state.get("set_up"))
        if ctx.get("pre_low") is not None:
            out["price_levels"] = [
                {"kind": "setup_trigger", "label": "Trigger (pre-session low)",
                 "price": round(float(ctx["pre_low"]), 4), "armed": armed,
                 "source": "sleeve_detector",
                 "detail": "the first one-minute low through this level is the entry"},
                {"kind": "stop", "label": "Planned stop",
                 "price": round(float(SM.stop_price(ctx["pre_high"], params)), 4),
                 "armed": armed, "source": "sleeve_detector",
                 "detail": "the pre-session high plus the configured pad"},
                {"kind": "reference", "label": "Session open",
                 "price": round(float(ctx["open"]), 4), "armed": armed,
                 "source": "sleeve_detector", "detail": ""},
            ]
            out["levels_armed"] = armed
            out["levels_note"] = ("" if armed else
                                  "Trigger levels were computed at 10:30 but are not armed — "
                                  "the setup gate did not pass")
        # Stop and target are pure functions of the pre-setup high and the entry, so they are
        # knowable the moment the basket sets up — but only then. Before that there is no
        # entry to anchor them to, which is a different fact from "not available".
        if state.get("set_up"):
            out["risk"] = {"source": NOT_COMPUTED_UNTIL_ENTRY,
                           "detail": "the stop follows the pre-setup high once an instrument "
                                     "breaks its low; no break, no anchor"}
    except Exception as exc:                                      # noqa: BLE001
        out["detail"] = f"the sleeve diagnostic could not be read ({type(exc).__name__}: {exc})"
    return out


# ── data status ─────────────────────────────────────────────────────────────────────────
def _data_status(root: Path, day: str, sleeve: str, inst: str) -> dict:
    f = (Path(root, "global_index/track1_runtime/data_observation")
         / f"data_observation_{day.replace('-', '')}.jsonl")
    out = {"provider": None, "ok": None, "latest_bar_et": None, "live_rows_fetched": None,
           "splice_result": "unknown", "provider_reason": None}
    if not f.is_file():
        out["provider_reason"] = "no data observation was recorded for this day"
        return out
    last = None
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:                                         # noqa: BLE001
            continue
        if r.get("sleeve") != sleeve:
            continue
        for i in r.get("instruments") or []:
            if i.get("inst") == inst:
                last = i
    if last is None:
        out["provider_reason"] = "this sleeve recorded no observation for this instrument"
        return out
    fetched = last.get("live_rows_fetched")
    return {"provider": last.get("provider"),
            # Three states. `None` is "nobody looked", which is not the same as False.
            "ok": None if fetched is None else (fetched > 0 or not last.get("provider_error")),
            "latest_bar_et": last.get("final_frame_last_ts"),
            "live_rows_fetched": fetched,
            "splice_result": last.get("splice_result") or "unknown",
            "provider_reason": last.get("provider_error")}


# ── assembly ────────────────────────────────────────────────────────────────────────────
def _summary(sleeve: str, status: str, slots: list, levels: list, data: dict,
             session_day: "str | None", asked_day: str, coverage: dict) -> str:
    """One line, and every number in it comes from the thing that owns that number.

    The first version counted the slot markers itself and printed "24/24 observed" for a
    sleeve the window ledger recorded as 18 of 24 — because a refused slot leaves a row here
    and is not an observation there. Two definitions of "observed" on one page is how an
    operator ends up trusting the wrong one, so the count now comes from the ledger and the
    markers only draw.
    """
    obs = (coverage or {}).get("observed_slots")
    exp = (coverage or {}).get("expected_slots")
    counted = f"{obs}/{exp}" if obs is not None and exp is not None else f"{len(slots)}"

    # A provider that SAID something is a refusal. A sleeve that recorded nothing is not:
    # measured on 2026-08-27, Swing had written no observation because its window had not
    # opened, and calling that "data refused" would have sent an operator to inspect a feed
    # that was working. `ok is None` means nobody looked.
    if data.get("provider_reason") and data.get("ok") is False:
        return f"Data refused · {data['provider_reason']} · no live bars"

    if status == ST_WAITING:
        head = f"Waiting · window has not opened · {exp or len(slots)} slots scheduled"
    elif status == ST_COMPLETE:
        head = f"Complete · {counted} slots observed"
    elif status == ST_INCOMPLETE:
        head = f"Incomplete · {counted} slots observed"
    elif status == ST_LIVE:
        head = f"Live · {counted} slots observed"
    elif status == ST_REFUSED:
        head = f"Refused · {counted} slots observed"
    elif status == ST_NOT_STARTED:
        head = f"Not started · {exp or len(slots)} slots scheduled"
    else:
        head = f"Unknown · {counted} slots observed"

    refused = sum(1 for x in slots if x["status"] == SLOT_REFUSED)
    signals = sum(1 for x in slots if x["status"] == SLOT_SIGNAL)
    head += " · no signal" if not signals else f" · {signals} signal(s)"
    if refused:
        head += f" · {refused} refused"
    if status != ST_WAITING and not levels:
        head += " · " + LEVELS_NOT_EXPOSED.lower()
    if session_day and session_day != asked_day:
        head += f" · bars from {session_day}"
    return head


def _anchor_day(today: str) -> str:
    """The day the panel should describe: today when today is a trading day, else the last one.

    Stage 5ZZZ-AG. The panel used to describe TODAY unconditionally, and on a Saturday or a
    Sunday that meant a whole page of absences on a day the route was never scheduled to run:
    22 NKD slots labelled "no record was written for this slot" for a session that does not
    exist. An alarm that fires every weekend is an alarm nobody reads by Monday.

    The rule is "last TRADING day", NOT "last day that has data", and the difference is the
    only reason this function is worth writing. They give the same answer on a weekend. They
    give opposite answers on the day that matters:

        Wednesday, scheduler dead, nothing recorded
          last day WITH DATA  -> shows Tuesday, complete, green. The outage is invisible.
          last TRADING day    -> shows Wednesday, 24 empty slots. The outage is the screen.

    So this consults the calendar and never the evidence. A trading day with no evidence still
    anchors here, and the emptiness is the finding.
    """
    try:
        from global_index import track1_freshness as _fresh

        if _fresh._is_trading_day(today):
            return today
        return _fresh.prev_trading_day(today).strftime("%Y-%m-%d")
    except Exception:                                             # noqa: BLE001
        # Never a reason to fail the payload: an unresolvable calendar falls back to today,
        # which is the behaviour that existed before this function and is merely noisy.
        return today


def _calendar_source() -> str:
    """Which calendar decided the anchor. Reported, because the fallback is weekday-only and
    a holiday would then be anchored on as though the market had been open."""
    try:
        from global_index import track1_freshness as _fresh

        return _fresh.calendar_source()
    except Exception:                                             # noqa: BLE001
        return "unavailable"


def _coverage(root: Path, day: str | None = None) -> dict:
    """The window ledger's own verdict per sleeve, FOR THE DAY THE PANEL IS SHOWING.

    Stage 5ZZZ-AG. This took the ledger's LATEST day whatever day the panel was on, and the
    two part company exactly when it matters. Measured on Sunday 2026-08-30: the summary line
    read "Complete · 22/22 slots observed" — Friday's count — printed directly above a strip
    of 22 of Sunday's slots with no record in any of them. Two days in one sentence, and the
    half that reassures was the half that was not about today.

    Asking the ledger for the day being shown also keeps the alarm working. On a trading day
    where nothing ran, `wl.status` has no `window_closed` record for that date and answers
    `unobserved / 0 observed / absence is the signal` — which is the whole point. Falling back
    to "the last day that has data" would have answered `complete` and hidden it.
    """
    try:
        from monitor.backend import track1_runtime_reader as tr

        full = tr._coverage(root) or {}
        if day is None:
            return full.get("latest") or {}
        import global_index.window_ledger as wl
        from global_index.track1_params import WINDOWS_ET

        d = root / tr.COVERAGE_DIR
        rows: list = []
        if d.is_dir():
            for f in sorted(d.glob("window_coverage_*.jsonl")):
                try:
                    rows.extend(json.loads(line) for line in
                                f.read_text(encoding="utf-8").splitlines() if line.strip())
                except Exception:                                 # noqa: BLE001
                    continue
        return {sleeve: wl.status(rows, sleeve, day) for sleeve in WINDOWS_ET}
    except Exception:                                             # noqa: BLE001
        return {}


def _sleeve_status(slots: list, coverage: dict, spec: dict, now_hhmm: str) -> str:
    """The window ledger's verdict, wherever the ledger has one.

    Time-of-day is only consulted when the ledger has said nothing yet. Deciding this from the
    clock while a ledger entry existed is how the first version reported a sleeve `complete`
    that the ledger had recorded as incomplete — the panel disagreeing with the record it is
    supposed to be showing.
    """
    outcome = str((coverage or {}).get("outcome") or "")
    if outcome == "complete":
        return ST_COMPLETE
    if outcome == "incomplete":
        # Still inside its own window, so "incomplete" only means "not finished yet".
        return ST_LIVE if now_hhmm <= spec["window_end"] else ST_INCOMPLETE
    # Nothing from the ledger. Before the window opens there is nothing to be wrong about,
    # and this is checked BEFORE the refusal branch: a stray recorded refusal from an
    # out-of-hours manual run would otherwise paint a sleeve red hours before it was due.
    if now_hhmm < spec["window_start"]:
        return ST_WAITING
    refused = [x for x in slots if x["status"] == SLOT_REFUSED]
    decided = [x for x in slots if x["status"] in (SLOT_NO_SIGNAL, SLOT_SIGNAL)]
    if refused and not decided:
        return ST_REFUSED
    if not [x for x in slots if x["status"] != SLOT_FUTURE]:
        return ST_NOT_STARTED
    if any(x["status"] == SLOT_FUTURE for x in slots):
        return ST_LIVE
    # Stage 5ZZZ-BW. The ledger's verdict, kept instead of collapsed. Reached only after the
    # window has ended -- the `waiting` branch above still owns the hours before it opens, so
    # a sleeve whose window has not come is not accused of losing a closing record it was
    # never due to write. `unknown` stays the true catch-all.
    if outcome == ST_UNOBSERVED:
        return ST_UNOBSERVED
    return ST_UNKNOWN


#: Stores whose per-day file proves a session exists to look at. `signals` is the spine --
#: every slot writes a row, whether it found something or not -- and `strategy_diagnostics` is
#: added because a day could in principle carry diagnostics and no signal row.
_SESSION_STORES = ("signals", "strategy_diagnostics")


def available_sessions(root: str | Path = ".", *, limit: int = 7,
                       today: str | None = None) -> list:
    """The sessions on disk, newest first -- discovered, never a calendar range.

    Stage 5ZZZ-BQ. A picker offering a range would hand the operator days that were never
    recorded, and an empty panel for a day nothing ever wrote is the absence-with-no-reason
    this panel has spent several stages removing. Measured 2026-09-01: the signal store holds
    25/08 through 01/09 while per-slot diagnostics begin 31/08, so the two answers differ and
    each day says which it has.

    `has_diagnostics` is what the session CHART needs; a day without it can still show the
    condition rows, because those can be replayed from the bars. Saying which is which is the
    difference between "nothing here" and "nothing was recorded here".

    Stage 5ZZZ-BV. TRADING days only, from the same calendar `_anchor_day` uses.

    A file on disk is not a session. 2026-08-29 was a Saturday and carried two rows -- a swing
    slot the gate refused -- and the first version of this picker offered it as a session to
    review. Opening it would have anchored the whole band on a day the market was shut, which
    is the exact page `_anchor_day` exists to prevent: twenty-two slots reading "no record was
    written" for a session that never existed.

    Nothing is lost by dropping it. Those rows stay in the signal journal and the job journal,
    where a refused weekend slot belongs; what they are not is a session.
    """
    import re

    root = Path(root)
    seen: dict = {}
    for store in _SESSION_STORES:
        d = root / "global_index" / "track1_runtime" / store
        if not d.is_dir():
            continue
        for f in d.glob("*.jsonl"):
            m = re.search(r"(20\d{6})", f.name)
            if not m:
                continue
            iso = "%s-%s-%s" % (m.group(1)[:4], m.group(1)[4:6], m.group(1)[6:])
            row = seen.setdefault(iso, {"day": iso, "has_signals": False,
                                        "has_diagnostics": False})
            if store == "signals":
                row["has_signals"] = True
            else:
                row["has_diagnostics"] = True
    # The live row is the day the panel ANCHORS on, not the calendar date. On a Saturday those
    # differ, and offering the calendar date would put a non-session at the top of the list
    # while the band below it described Friday.
    live = _anchor_day(today) if today else ""
    if live and live not in seen:
        seen[live] = {"day": live, "has_signals": False, "has_diagnostics": False}
    out = [seen[k] for k in sorted(seen, reverse=True) if _is_session(k)]
    for row in out:
        row["is_today"] = bool(live) and row["day"] == live
    return out[:limit] if limit else out


def _is_session(day: str) -> bool:
    """Was the market open on this date? The project's own calendar answers, never a weekday
    test written here -- a holiday looks like a trading day to anything that only counts days
    of the week, and `calendar_source()` reports which of the two is in force."""
    try:
        import pandas as pd

        from global_index import track1_freshness as _fresh

        return bool(_fresh._is_trading_day(pd.Timestamp(day)))
    except Exception:                                             # noqa: BLE001
        # A picker that empties itself because a calendar could not be loaded is worse than one
        # that offers a weekend. The band still labels whatever is opened.
        return True


def build(root: str | Path = ".", *, day: str | None = None, now: Any = None,
          coverage: dict | None = None) -> dict:
    """The whole payload. Read-only, offline, and it never raises: a panel that 500s tells the
    operator less than a panel that says which part it could not read."""
    import pandas as pd

    root = Path(root)
    ref = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz=ET)
    ref_et = ref.tz_convert(ET) if ref.tzinfo else ref
    today = ref_et.strftime("%Y-%m-%d")
    asked = day or _anchor_day(today)
    is_today = asked == today

    # The clock only judges slots on the day the clock belongs to. Sunday's 09:00 must not be
    # used to call Friday's 10:35 slot "has not fired yet" — Friday is over, and every slot on
    # a closed day is judged by whether a record exists, not by where the hands are now.
    now_hhmm = ref_et.strftime("%H:%M") if is_today else "23:59"

    rows = _signal_rows(root, asked)
    cov = coverage if coverage is not None else _coverage(root, asked)
    out: dict = {"schema": SCHEMA, "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                 "route": ROUTE, "session_date": asked, "now_et": ref_et.strftime("%H:%M"),
                 # Stated, never inferred. A panel showing Friday on a Sunday has to say so in
                 # the payload, or the page has no honest way to label it and the reader takes
                 # a closed session for the live one.
                 "today_et": today, "session_is_today": is_today,
                 "session_anchor": ("today" if is_today else "last_trading_day"),
                 "session_anchor_reason": (
                     "" if is_today else
                     f"{today} is not a trading day; showing the last one, {asked}"),
                 "calendar_source": _calendar_source(),
                 "levels_note": LEVELS_NOT_EXPOSED, "sleeves": {}}

    # Stage 5ZZZ-E. Calm, as TWO cards rather than one sleeve.
    #
    # It is not in `SLEEVES` and is not being added to it: every entry there is a sleeve with a
    # continuous window, one instrument and a bar chart, and Calm is two instants half an hour
    # apart on a contract that forbids the first from seeing what the second learns. Squeezing
    # it into that shape would have meant one card, and one card is where the leak would live.
    #
    # Wrapped, because a diagnostics panel must not be the reason the rest of the payload 500s.
    try:
        _calm = {"sleeve": "roska4_calm", "label": "Calm", "session_date": asked}
        if now is not None:
            # A caller that named an instant gets that instant, computed — same rule the
            # sleeve reconstructions follow.
            _calm["phases"] = _sd.calm_blocks(root, asked, now=now)
        else:
            # Stage 5ZZZ-S. Measured at 15.0s on a cold process, and it was inline: the whole
            # payload waited on it. Same background pattern as the sleeve reconstructions.
            _ckey = ("calm_blocks", asked, str(root))
            _phases = _recon_cached(_ckey, lambda: _sd.calm_blocks(root, asked, now=None))
            if _phases is None:
                _st, _e = _recon_state(_ckey)
                _calm["phases"] = {}
                _calm["unavailable"] = (
                    "still being computed; the first request after a backend restart pays a "
                    "full pass over the bar history, and this panel fills in on a later poll"
                    if _st in ("warming", "absent") else
                    (f"could not be computed ({_e})" if _e else "returned nothing"))
            else:
                _calm["phases"] = _phases
        out["calm"] = _calm
    except Exception as exc:                                       # noqa: BLE001
        out["calm"] = {"sleeve": "roska4_calm", "label": "Calm", "session_date": asked,
                       "phases": {}, "error": f"{type(exc).__name__}: {exc}"}

    for sleeve, spec in SLEEVES.items():
        try:
            slots = _slots_for(sleeve, rows, now_hhmm)  # noqa: E501  (settled below)
            bars, session_day, note = _sliced(spec["instrument"], asked, spec)
            levels = _levels(rows, sleeve)
            data = _data_status(root, asked, sleeve, spec["instrument"])
            status = _sleeve_status(slots, cov.get(sleeve) or {}, spec, now_hhmm)
            out["sleeves"][sleeve] = {
                "label": spec["label"], "instrument": spec["instrument"],
                "bar_interval": f"{BAR_MINUTES}m", "clock": spec["clock"],
                "range": {"context_start_et": spec["context_start"],
                          "window_start_et": spec["window_start"],
                          "window_end_et": spec["window_end"],
                          "context_end_et": spec["context_end"]},
                "status": status,
                "summary": _summary(sleeve, status, slots, levels, data, session_day, asked,
                                    cov.get(sleeve) or {}),
                "coverage": cov.get(sleeve) or {},
                "bars": bars, "bars_session_date": session_day, "bars_note": note,
                # Stage 5ZZP. Three states, never two. `not_available` is a store with no
                # column; `present_but_empty` is a column of zeros, which MNKD genuinely has
                # on thin bars and which must not be drawn as "no trading happened".
                "volume_status": _volume_status(bars),
                "slots": slots, "levels": levels,
                # Stage 5ZZY. One row per declared rule, one cell per slot, built from the
                # SAME diagnostics rows the slots came from — no second read, no new file.
                "rule_lanes": _rule_lanes(rows, sleeve, slots),
                # Stage 5ZZZ-AJ. Beside the lanes, never inside them: what the sleeve is
                # configured to do, as opposed to what a slot decided.
                "declared_config": _declared_config(rows, sleeve),
                "levels_note": None if levels else LEVELS_NOT_EXPOSED,
                # Stage 5ZZP. The sleeve's own rule values, where the detector publishes them.
                "strategy": _strategy(root, sleeve, asked, spec, now=now),  # the CALLER's instant, not the derived one:
                #   `ref` is never None, so passing it made every request look like a
                #   caller naming an instant and bypass the cache entirely.
                # Stage 5ZZQ. What would have to happen for a candidate to exist. Built from
                # the diagnostic above rather than from a second read of the detector.
                "setup_boundary": None,     # filled in below, once `strategy` is in hand
                "levels_detail": None if levels else LEVELS_DETAIL,
                "data_status": data,
            }
            blk = out["sleeves"][sleeve]
            blk["setup_boundary"] = _setup_boundary(sleeve, spec, blk["strategy"],
                                                    blk["slots"])
            # Stage 5ZZZ-AM. The per-BAR grid, lifted to where a renderer can reach it.
            #
            # It is a different axis from `rule_lanes` and must stay one: a lane cell is a
            # SLOT and a grid cell is a BAR. Measured on a real session, the two cannot be
            # merged — within a single slot `volume_pullback_declined` is answered twelve
            # times pass and ten times fail, so the slot cell has no value, while every bar
            # cell has exactly one and never changes (865 verdicts recomputed across a
            # session, 80 distinct, zero ever different).
            blk["bar_grid"] = ((blk.get("strategy") or {}).get("diagnostics")
                               or {}).get("bar_gate_grid") or None
            _settle_levels_note(blk)
        except Exception as exc:                                  # noqa: BLE001
            out["sleeves"][sleeve] = {
                "label": spec["label"], "instrument": spec["instrument"],
                "status": ST_UNKNOWN, "bars": [], "slots": [], "levels": [],
                "summary": f"This sleeve's view could not be built "
                           f"({type(exc).__name__}: {exc})",
                "error": f"{type(exc).__name__}: {exc}"}

    # Stage 5ZZZ-F. One string cannot describe three sleeves that now disagree. Stress publishes
    # a trigger, a stop and a session open; the other two publish nothing. The payload-wide note
    # asserted "Strategy levels unavailable" for all of them BEFORE any sleeve was built, and
    # that stopped being true the moment the diagnostics stages landed. It is derived from the
    # sleeves instead, and speaks only when every sleeve agrees.
    _notes = {(v.get("levels_note") or "") for v in out["sleeves"].values()}
    out["levels_note"] = _notes.pop() if len(_notes) == 1 else ""
    # One gate on the way out. See _scrub_list_literals for why this is not done
    # field by field.
    return _scrub_list_literals(out)


def regime(root: str | Path = ".") -> dict:
    """The regime panel's payload, read from the recorded label. Never computes it."""
    from global_index import track1_regime_record as rr

    try:
        rec = rr.latest(root)
    except Exception as exc:                                      # noqa: BLE001
        return {"status": "UNKNOWN", "code": "reader_failed",
                "detail": f"{type(exc).__name__}: {exc}",
                "label": None, "recent": [], "context": [],
                "score": None, "score_name": rr.SCORE_NAME, "shift_threshold": None,
                "margin": None, "margin_name": rr.MARGIN_NAME, "runner_up": None,
                "state_probabilities": {}, "posterior_agrees_with_label": None,
                "entropy_bits": None, "max_entropy_bits": None, "features": [],
                "score_note": "the regime record could not be read",
                "threshold_note": rr.NO_THRESHOLD,
                "verification": {"status": "UNKNOWN"}}
    age = rr.age_hours(rec)
    out = {"status": rec.status, "code": rec.code, "detail": rec.detail,
           "label": rec.label, "label_date": rec.label_date,
           "checked_at": rec.checked_at,
           "age_hours": None if age is None else round(age, 2),
           "recent": list(rec.recent), "context": list(rec.context),
           "inputs": dict(rec.inputs),
           # Named, never omitted. The model returns strings; there is no number under them,
           # so a "distance to shift" display has nothing to read and says so.
           # Stage 5ZZP. The score is real now; the margin stands where a threshold distance
           # would go, and is named as a margin so nobody reads it as one.
           "score": rec.score, "score_name": rec.score_name,
           "shift_threshold": rec.shift_threshold,
           "margin": rec.margin, "margin_name": rec.margin_name,
           "runner_up": rec.runner_up,
           "state_probabilities": dict(rec.state_probabilities or {}),
           "posterior_agrees_with_label": rec.posterior_agrees_with_label,
           # Stage 5ZZQ. Entropy of the whole posterior, and the two features the model is
           # actually fitted on. A margin says how far the leader is ahead of ONE rival;
           # entropy says how spread the distribution is.
           "entropy_bits": rec.entropy_bits, "max_entropy_bits": rec.max_entropy_bits,
           "features": list(rec.features or []),
           "score_note": rec.score_note, "threshold_note": rec.threshold_note,
           "line": rr.operator_line(rec)}
    try:
        from global_index import regime_verify as rv

        v = rv.latest(root) if hasattr(rv, "latest") else None
        out["verification"] = (v.as_dict() if v is not None and hasattr(v, "as_dict")
                               else {"status": "UNKNOWN",
                                     "detail": "no verification reader available"})
    except Exception as exc:                                      # noqa: BLE001
        out["verification"] = {"status": "UNKNOWN",
                               "detail": f"{type(exc).__name__}: {exc}"}

    return out
