"""Track 1 strategy diagnostics — the variables a sleeve actually decided on. Stage 5ZZZ-B.

WHAT THIS IS FOR
----------------
Stage 5ZZR gave the dashboard a strategy-native panel and then had to print
"Not reported by detector" beside all four of the variables NKD and Swing decide on. The values
existed — `_scan_window` computes the trend filter, the ATR and the ten-bar average volume for
every bar it looks at — and then discarded them. This module is where they come out.

THE ONE RULE IT IS BUILT AROUND
-------------------------------
Nothing here computes a strategy value. It LISTENS.

`track1_normal_r4` grew an `observer` seam in this stage: an optional listener that
`detect_entry_for_slot` and `_scan_window` call with what they just computed, whose return value
is discarded and whose exceptions are swallowed. So every number this module reports came out of
the same call the live slot makes, with the same parameters, on the same bars.

The alternative — recomputing an EMA here — is a second implementation of a rule the committed
artifacts were generated with, and the detector's own docstring says why that is not acceptable:
"A second implementation of an entry rule proves nothing about the first."

TWO SOURCES, NEVER MIXED
------------------------
    recorded_runtime      written by the slot itself, while it was deciding
    reconstructed_today   computed afterwards from the bars available now, for a slot earlier
                          today that left no record

A reconstruction is not evidence. It is an answer to "what would the detector see", asked after
the fact, and it carries `reconstructed_at`, `reconstructed_through` and a warning saying so.
Nothing here may satisfy a readiness gate, an audit verdict or an order gate, and the backend
that calls it keeps the two apart rather than merging them into one field.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

SCHEMA = "track1_strategy_diagnostics/1"

RECORDED = "recorded_runtime"
RECONSTRUCTED = "reconstructed_today"
NOT_YET_RUN = "not_yet_run"

#: The sentence a reconstructed block carries, in one place so the page cannot soften it.
RECONSTRUCTION_WARNING = "computed after the fact; not official runtime evidence"

#: Why a value is not there. Same vocabulary Stage 5ZZR gave the panel, so a reader meets one
#: set of words rather than one per producer.
MISSING_NOT_YET = "not_yet"
MISSING_NO_RECORD = "no_record"
MISSING_REFUSED = "refused"
MISSING_DATA = "missing_data"
MISSING_NOT_REPORTED = "not_reported_by_detector"


def _num(value) -> "float | None":
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None      # NaN / inf -> None


def _bar_had_closed(bar_ts, now, *, minutes: int = 5):
    """Had the bar the detector LAST EVALUATED closed by the time the slot ran?

    Stage 5ZZZ-AW. Answered here because this is the only place holding both halves: the
    detector reports its clock, the observer keeps its last bar, and neither knows the other.

    Returns None -- never a guess -- when either half is missing or unparseable. "We did not
    measure" and "the bar had closed" are the two answers this field exists to keep apart, and
    a bool cannot hold three states.
    """
    if not bar_ts or not now:
        return None
    try:
        b = _dt.datetime.fromisoformat(str(bar_ts))
        n = _dt.datetime.fromisoformat(str(now))
        # The caller converts `now` into the frame's own clock before truncating, so when one
        # side carries a tz and the other does not they are already the same wall clock.
        if (b.tzinfo is None) != (n.tzinfo is None):
            b, n = b.replace(tzinfo=None), n.replace(tzinfo=None)
        return bool(b + _dt.timedelta(minutes=minutes) <= n)
    except Exception:                                          # noqa: BLE001
        return None


def _row(label: str, value, *, unit: str = "", threshold=None, comparator: str = "",
         passed=None, detail: str = "", missing: str = "") -> dict:
    """One named variable, with what it was compared against when there is a comparison.

    `display_value` is built here rather than on the page: the page must not decide how many
    decimals a price carries, and a value that is absent has to say WHY in the same field a
    number would have occupied, or the reader is left to guess.
    """
    num = _num(value)
    if missing:
        display = {MISSING_NOT_YET: "Not yet run",
                   MISSING_NO_RECORD: "No record",
                   MISSING_REFUSED: "Refused",
                   MISSING_DATA: "Data unavailable",
                   MISSING_NOT_REPORTED: "Not reported by detector"}.get(missing, "Unavailable")
    elif num is None:
        display = str(value) if value not in (None, "") else "Unavailable"
    elif unit == "price":
        display = f"{num:,.2f}"
    elif unit == "ratio":
        display = f"{num:.2f}x"
    elif unit == "count":
        display = f"{num:,.0f}"
    else:
        display = f"{num:,.4f}".rstrip("0").rstrip(".")
    # Stage 5ZZZ-BC. A value smaller than the format can show must not print as "0".
    #
    # The rules this module now carries are not all prices. `avg_gap` is a fraction compared
    # against -0.001, and four decimals stripped of trailing zeros renders 1.2e-05 as "0" --
    # a reading indistinguishable from a true zero, beside a threshold three decimals up.
    # Measured on the real basket, 2026-08-28: the row read "0" while the detector's own
    # sentence in the same block read the full number.
    if num is not None and num != 0:
        suffix = "x" if str(display).endswith("x") else ""
        try:
            if float(str(display).replace(",", "").rstrip("x")) == 0:
                # The unit marker survives the reformat: dropping it turns a ratio into a
                # bare number and the reader loses what it is a ratio OF.
                display = f"{num:.3g}{suffix}"
        except ValueError:
            pass
    return {"label": label, "value": num if num is not None else value,
            "display_value": display, "unit": unit, "threshold": threshold,
            "comparator": comparator, "passed": passed, "detail": detail,
            "missing": missing or None}


class NormalR4Observer:
    """Collects what `detect_entry_for_slot` computed, without touching what it decided.

    Keeps the LAST bar it was told about, because that is the bar the sleeve's state is read
    from at the moment the slot ran, and every gate in the order it was answered — so a
    "nearest failed condition" is the first gate that said no, not a guess at one.
    """

    def __init__(self) -> None:
        self.gates: list[dict] = []
        #: Stage 5ZZZ-AL. A SECOND channel, and the separation is the whole point of it.
        #:
        #: `gates` holds SLOT-level gates — five of them at most, one pass through the
        #: detector: measured on 2026-08-10, `session_bars`, `regime`, `daily_atr`,
        #: `bars_so_far`, `setup_bar`. `first_failed_gate` reads that list in order and takes
        #: the first refusal, and the panel prints it as the reason the SLOT found nothing.
        #:
        #: The gates the engine and the sleeve wrapper report fire per BAR, inside the window
        #: scan — which runs between `bars_so_far` and `setup_bar`. Appending them to `gates`
        #: would put up to 154 events (22 bars x 4 engine gates + 3 wrapper gates) into that
        #: slot, and the first per-bar refusal would be reached BEFORE `setup_bar`. The panel
        #: for 2026-08-10 would have turned from
        #:      setup_bar — "no bar in the window so far signalled"   (about the session)
        #: into
        #:      volume_resume_surge — one bar's reading, 22 bars before the conclusion
        #: and not rarely: `volume_resume_surge` refuses 388 of the 397 bars that reach it.
        #:
        #: So they live here, `first_failed_gate` never sees them, and the slot-level meaning
        #: is preserved BY CONSTRUCTION rather than by remembering to be careful.
        self.bar_gates: list[dict] = []
        self.last_bar: dict | None = None
        #: Stage 5ZZZ-AW. When the slot ran, and whether its newest bar had closed by then.
        #: Its own channel for the same reason `bar_gates` is: `first_failed_gate` walks
        #: `gates` in order, and a clock is not a gate.
        self.clock: dict = {}
        self.bars_seen = 0
        self.signal: dict | None = None

    def __call__(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "gate":
            self.gates.append({k: v for k, v in event.items() if k != "kind"})
        elif kind == "bar_gate":
            self.bar_gates.append({k: v for k, v in event.items() if k != "kind"})
        elif kind == "clock":
            self.clock = {k: v for k, v in event.items() if k != "kind"}
        elif kind == "bar":
            self.bars_seen += 1
            self.last_bar = event
            if event.get("signal"):
                self.signal = dict(event["signal"])

    # ── what the collected state means ───────────────────────────────────────────────────
    @property
    def first_failed_gate(self) -> "dict | None":
        return next((g for g in self.gates if g.get("passed") is False), None)

    #: Set by whoever built the block, from `regime_basis()`. Empty until then, and the row
    #: falls back to the older wording rather than claiming a basis nobody supplied.
    regime_detail: str = "handed to the detector, not computed here"

    #: One character per bar. `NOT_REACHED` is the one that had to exist: the gates are
    #: ordered and the first refusal returns, so a bar blocked on the EMA never reaches the
    #: volume test — and "did not run" is not "ran and passed".
    CELL_PASS = "P"
    CELL_FAIL = "F"
    CELL_NOT_REACHED = "-"

    def bar_gate_grid(self) -> dict:
        """One row per rule, one CELL PER BAR, plus each row's own tally.

        Stage 5ZZZ-AM. The unit is the BAR, and that is a measured fact rather than a choice.
        Cutting the window at every five-minute mark through a real session and re-asking the
        detector: 865 verdicts were computed across the session, 80 of them distinct, and
        **not one verdict ever changed between cuts**. A bar's answer is fixed the moment the
        bar closes.

        That is what makes a grid possible at all. The panel used to draw one cell per SLOT,
        which has no single value — the 14:10 slot has seen one bar and the 15:55 slot has
        seen twenty-two, and within one slot a rule can be answered twelve times pass and ten
        times fail. Anchored on the bar instead, every cell has exactly one value, forever.

        Stored as a STRING per row, not a list of dicts. A slot can produce 154 cells and
        every slot of every session persists a block; this repo already carries one array
        nobody capped, which reached 360 KB inside a 426 KB file. Twenty-two characters do
        not.

        `reached` and `passed` on each row are the funnel, derived here so the two readings
        cannot disagree: the panel's summary and its cells come out of the same pass.
        """
        bars: list = []
        seen: dict = {}
        order: list = []
        rows: dict = {}
        for e in self.bar_gates:
            name = str(e.get("gate") or "")
            if not name:
                continue
            ts = str(e.get("bar_ts"))
            if ts not in seen:
                seen[ts] = len(bars)
                bars.append(ts)
            if name not in rows:
                order.append(name)
                rows[name] = {"gate": name, "cells": {}, "reached": 0, "passed": 0,
                              "threshold": e.get("threshold"),
                              "comparator": str(e.get("comparator") or ""),
                              "last_value": None}
            r = rows[name]
            r["cells"][seen[ts]] = self.CELL_PASS if e.get("passed") else self.CELL_FAIL
            r["reached"] += 1
            if e.get("passed"):
                r["passed"] += 1
            r["last_value"] = e.get("value")
        out_rows = []
        for name in order:
            r = rows[name]
            cells = "".join(r["cells"].get(i, self.CELL_NOT_REACHED)
                            for i in range(len(bars)))
            out_rows.append({"gate": name, "cells": cells, "reached": r["reached"],
                             "passed": r["passed"], "threshold": r["threshold"],
                             "comparator": r["comparator"], "last_value": r["last_value"]})
        return {"bars": bars, "rows": out_rows,
                "legend": {self.CELL_PASS: "passed", self.CELL_FAIL: "failed",
                           self.CELL_NOT_REACHED: "an earlier gate returned first"}}

    @property
    def daily_atr_gate(self) -> "dict | None":
        """The SLOT-level daily-ATR gate, which carries the number the STOP is built from.

        Stage 5ZZZ-AY. The row labelled "Daily ATR" was never the daily ATR. `_scan_window`
        computes `atr14(hist)` on the FIVE-MINUTE frame it is walking -- a fourteen-bar, roughly
        seventy-minute range -- and the row printed it under a name that says one day. Measured
        on MNKD for 2026-08-28: the row read 55, the daily ATR the stop is sized from read
        1,548.93. Twenty-eight times apart, and the number that actually places the stop
        appeared nowhere on the page.

        Copied from the gate, like the regime verdict. `detect_entry_for_slot` already reports
        it as `daily_atr` with the value attached; recomputing it here would be a second
        implementation of the thing the stop is built from.
        """
        return next((g for g in self.gates if g.get("gate") == "daily_atr"), None)

    @property
    def regime_gate(self) -> "dict | None":
        """The SLOT-level regime gate, when the detector reported one.

        Stage 5ZZZ-AW. Seven of these eight rows are measurements and carry no verdict on
        purpose -- see the paragraph on "Close minus EMA", where stamping one produced a 52.7%
        agreement with the gate it was read as reporting. `Regime` is the exception, and the
        only one: the detector reports a gate of that name, with that value, against that
        threshold, and the row was printing "NOT REPORTED" beside a verdict sitting a few
        fields away in the same block. Nothing is recomputed here -- the gate is copied.
        """
        return next((g for g in self.gates if g.get("gate") == "regime"), None)

    def rows(self, *, ema_period: int) -> list[dict]:
        """The four variables this sleeve decides on, plus the price they were measured at."""
        bar = self.last_bar
        rg = self.regime_gate or {}
        dag = self.daily_atr_gate or {}
        if bar is None:
            why = MISSING_DATA if self.first_failed_gate else MISSING_NOT_REPORTED
            return [_row(f"Trend filter (EMA {ema_period})", None, missing=why),
                    _row("Close used", None, missing=why),
                    _row("Close minus EMA", None, missing=why),
                    _row("ATR (14 x 5-min bars)", None, missing=why),
                    _row("Daily ATR", dag.get("value"),
                         unit="price" if dag.get("value") is not None else "",
                         missing="" if dag.get("value") is not None else why,
                         detail="the daily range the stop distance is sized from"),
                    _row("Volume", None, missing=why),
                    _row("Average volume (10 bars)", None, missing=why),
                    _row("Volume vs average", None, missing=why),
                    _row("Regime", rg.get("value"), threshold=rg.get("threshold"),
                         comparator="in" if rg else "", passed=rg.get("passed"),
                         missing="" if rg.get("value") is not None else why,
                         detail=self.regime_detail)]

        resume = bar.get("resume_bar")
        close = _num(getattr(resume, "close", None) if resume is not None else None)
        volume = _num(getattr(resume, "volume", None) if resume is not None else None)
        ema = _num(bar.get("ema"))
        atr = _num(bar.get("atr"))
        avgv = _num(bar.get("avgv"))
        gap = None if (ema is None or close is None) else close - ema
        ratio = None if (avgv in (None, 0) or volume is None) else volume / avgv
        return [
            _row(f"Trend filter (EMA {ema_period})", ema, unit="price",
                 detail="the sleeve's own period, from the detector"),
            _row("Close used", close, unit="price",
                 detail=f"the bar the detector last evaluated: {bar.get('bar_ts')}"),
            # Stage 5ZZZ-AJ. A MEASUREMENT, and no longer a verdict.
            #
            # This carried `passed = gap > 0` and read as the sleeve's EMA filter having been
            # checked and met. It was neither that filter nor the bar that filter looks at:
            #
            #   the filter   |pullback_bar.close - ema| / ema <= ema_proximity_pct (0.005)
            #                a PROXIMITY test, on bar[-2]
            #   this row     resume_bar.close - ema > 0
            #                a SIGN test, on bar[-1] — which is the DIRECTION gate, a
            #                different gate one step later in the same function
            #
            # Measured on the real stores, 3,999 bars per sleeve, comparing this row's answer
            # against the engine gate it was read as reporting:
            #
            #   NKD    agree 52.7%  ·  row says PASSED where the gate refuses 1.9%  ·
            #          row says FAILED where the gate allows 45.4%
            #   Swing  agree 53.8%  ·  3.1%  ·  43.1%
            #
            # A coin flip, and wrong in both directions. The 45.4% is every SHORT setup, whose
            # gap is negative by construction. The 1.9% is the dangerous half: the worst bar
            # printed "passed" here while sitting 7.06% from the EMA, against a 0.50%
            # threshold — fourteen times over the limit the engine refuses at.
            #
            # Recomputing the real test here instead would be a second implementation of a
            # rule that trades — the defect this module's own contract exists to refuse. So
            # the number stays, the tick mark goes, and the verdict waits for the detector to
            # report which gate it stopped at.
            _row("Close minus EMA", gap, unit="price",
                 detail="the last evaluated bar's close against the trend filter. NOT the "
                        "sleeve's EMA test, which measures the PULLBACK bar's distance to "
                        "the EMA against a proximity threshold and whose verdict the "
                        "detector does not return"),
            _row("ATR (14 x 5-min bars)", atr, unit="price",
                 detail="fourteen bars of the frame being walked, about seventy minutes. "
                        "NOT the daily range -- that is the row below, and it is the one the "
                        "stop distance is built from"),
            _row("Daily ATR", dag.get("value"),
                 unit="price" if dag.get("value") is not None else "",
                 detail="the daily range the stop distance is sized from"),
            _row("Volume", volume, unit="count"),
            _row("Average volume (10 bars)", avgv, unit="count",
                 detail="taken by position inside the window, looking backward"),
            _row("Volume vs average", ratio, unit="ratio"),
            _row("Regime", bar.get("regime") or rg.get("value") or None,
                 threshold=rg.get("threshold"), comparator="in" if rg else "",
                 passed=rg.get("passed"), detail=self.regime_detail),
        ]


#: Stage 5ZZZ-G. What KIND of regime object a detector was handed, described from the object
#: itself rather than from the sleeve's name.
#:
#: Two sleeves run this same detector and the panel showed one of them "Calm" and the other
#: "Unavailable" on the same session, with nothing on the page to explain it. The explanation is
#: that they are handed different objects: NKD gets the label as of the PREVIOUS session, Swing
#: gets the map itself and the detector looks up the session's own row - which does not exist
#: until that session's close. Neither value was wrong; the page just could not say why they
#: differed, and an operator cannot audit a difference nobody names.
REGIME_BASIS_PREV_SESSION = "previous session (lag 1)"
REGIME_BASIS_SAME_SESSION = "this session's own label"
REGIME_BASIS_UNKNOWN = "unrecognised label object"


def regime_basis(labels) -> str:
    """Describe the labels object, by asking IT rather than by knowing which sleeve called.

    Derived, because a hand-written map from sleeve to basis is a map that goes stale the first
    time a call site changes and says the opposite of what the detector actually saw.
    """
    lag = getattr(labels, "lag", None)
    if lag is not None:
        try:
            n = int(lag)
        except (TypeError, ValueError):
            return REGIME_BASIS_UNKNOWN
        return REGIME_BASIS_PREV_SESSION if n == 1 else f"{n} sessions back"
    if hasattr(labels, "get"):
        return REGIME_BASIS_SAME_SESSION
    return REGIME_BASIS_UNKNOWN


class StressObserver:
    """Collects the basket state the Stress detector already computed. Decides nothing.

    Stage 5ZZZ-BB. Stress is the sleeve that needed this least and got it last, because it
    answers every entry condition in FULL: `entry_conditions` is `all()` over the table
    `entry_checks` walks, and each row of that table already carries a value, a threshold, a
    comparator and a verdict. None of it reached the slot, so the panel printed "value not
    published" beside four rules the detector had answered carefully.

    One event, not a stream: the basket is judged once per slot, so there is no per-bar channel
    here and nothing that could outrank a slot-level refusal the way `bar_gates` would.
    """

    def __init__(self) -> None:
        self.state: dict = {}

    def __call__(self, event: dict) -> None:
        if event.get("kind") == "basket_state":
            self.state = {k: v for k, v in event.items() if k != "kind"}

    @property
    def checks(self) -> list:
        return list(self.state.get("checks") or [])

    @property
    def first_failed(self) -> "dict | None":
        """The first refusal IN THE DETECTOR'S OWN ORDER, not the first one found."""
        want = self.state.get("first_failed")
        for c in self.checks:
            if c.get("id") == want:
                return c
        return next((c for c in self.checks if c.get("passed") is False), None)

    def rows(self) -> list:
        """One row per entry condition, in the order the detector evaluates them.

        Verdicts are COPIED. Unlike the Normal-R4 rows -- where seven of eight are measurements
        with no verdict and stamping one agreed with its gate 52.7% of the time -- every row
        here IS the condition: same value, same threshold, same comparator, same answer, taken
        from the list `entry_conditions` reduces over.
        """
        out = []
        for c in self.checks:
            applicable = c.get("applicable") is not False
            out.append(_row(str(c.get("label") or c.get("id") or ""), c.get("value"),
                            unit=str(c.get("unit") or ""),
                            threshold=c.get("threshold"),
                            comparator=str(c.get("comparator") or ""),
                            passed=(c.get("passed") if applicable else None),
                            detail=("" if applicable else
                                    "threshold is unset for this sleeve, so the detector "
                                    "does not compare it and it does not vote")))
        return out


def stress_block(*, sleeve: str, slot_id: str, observer: StressObserver,
                 setups=None, params_hash: str = "", data_identity: str = "",
                 source: str = RECORDED) -> dict:
    """One Stress diagnostics block for a slot, in the shape every other sleeve publishes.

    Deliberately the SAME keys as `normal_r4_block`, so the panel does not need a second
    reader and a future field lands on both sleeves or on neither.
    """
    rows = observer.rows()
    first = observer.first_failed
    st = observer.state or {}
    n_setups = len(setups or [])
    return {
        "schema": SCHEMA,
        "diagnostics_source": source,
        "sleeve": sleeve,
        "slot_id": slot_id,
        "detector": "track1_stress_mnq",
        "params_hash": params_hash,
        "data_source_identity": data_identity,
        "session_date": str(st.get("day") or "")[:10],
        "slot_ran_at": st.get("now"),
        "rows": rows,
        # The basket is judged once, so these ARE the slot gates -- copied, not re-derived.
        "gates": [{"gate": c.get("id"), "passed": c.get("passed"),
                   "value": c.get("value"), "threshold": c.get("threshold"),
                   "detail": "%s %s needs %s %s" % (c.get("label"), c.get("value"),
                                                    c.get("comparator"), c.get("threshold"))}
                  for c in observer.checks],
        "bar_gate_grid": {"bars": [], "rows": [], "legend": {}},
        "bars_evaluated": None,
        "last_bar_ts": None,
        "last_bar_complete": None,
        "setup": bool(st.get("set_up")),
        "price_levels": [],
        "levels_armed": False,
        "nearest_failed_condition": (
            None if first is None else
            {"gate": first.get("id"), "detail": first.get("label"),
             "value": first.get("value"), "threshold": first.get("threshold")}),
        "summary": (("A setup formed and %d entry candidate(s) followed" % n_setups)
                    if st.get("set_up") and n_setups
                    else "The basket set up; no instrument broke its pre-entry low"
                    if st.get("set_up")
                    else (st.get("detail") or "The basket did not set up")),
        "reason": st.get("reason") or "",
    }


def normal_r4_block(*, sleeve: str, slot_id: str, ema_period: int, observer: NormalR4Observer,
                    setup, params_hash: str = "", data_identity: str = "",
                    source: str = RECORDED, reconstructed_through=None,
                    regime_basis_note: str = "") -> dict:
    """One sleeve's diagnostics block for a slot, from what the detector reported."""
    # Stage 5ZZZ-G. Set BEFORE the rows are built, because the Regime row reads it. The note
    # travels on the block too, so a reader who has only the JSON can still tell which of the
    # two regime objects produced the value they are looking at.
    if regime_basis_note:
        observer.regime_detail = (f"{regime_basis_note} - handed to the detector, "
                                  f"not computed here")
    gate = observer.first_failed_gate
    rows = observer.rows(ema_period=ema_period)
    last_bar_ts = None
    if observer.last_bar is not None:
        last_bar_ts = str(observer.last_bar.get("bar_ts"))

    levels: list[dict] = []
    if setup is not None:
        entry = _num(getattr(setup, "entry", None) or getattr(setup, "entry_price", None))
        stop = _num(getattr(setup, "stop", None) or getattr(setup, "initial_stop", None))
        if entry is not None:
            levels.append({"kind": "entry", "label": "Entry", "price": round(entry, 4),
                           "armed": True})
        if stop is not None:
            levels.append({"kind": "stop", "label": "Stop", "price": round(stop, 4),
                           "armed": True})

    block = {
        "schema": SCHEMA,
        "diagnostics_source": source,
        "sleeve": sleeve,
        "slot_id": slot_id,
        "detector": "track1_normal_r4",
        "params_hash": params_hash,
        "data_source_identity": data_identity,
        # Stage 5ZZZ-G. Which regime object the detector was handed. Empty when the caller did
        # not say - never guessed from the sleeve's name, because the whole point is to report
        # what the detector actually saw rather than what it is supposed to see.
        "regime_basis": regime_basis_note or "",
        "last_bar_ts": last_bar_ts,
        # Stage 5ZZZ-AW. None when nobody said what the clock was -- never guessed, because
        # "we did not measure" and "the bar had closed" are the two answers this field exists
        # to keep apart.
        "last_bar_complete": _bar_had_closed(last_bar_ts, (observer.clock or {}).get("now")),
        "slot_ran_at": (observer.clock or {}).get("now"),
        "bars_evaluated": observer.bars_seen,
        "rows": rows,
        "gates": observer.gates,
        # Stage 5ZZZ-AM. Beside `gates`, never merged into it — see `bar_gates`. Compacted
        # here rather than at the reader, so the persisted record can never carry the raw
        # per-bar events even if a future caller forgets to.
        "bar_gate_grid": observer.bar_gate_grid(),
        "setup": setup is not None,
        "price_levels": levels,
        "levels_armed": bool(levels),
        "nearest_failed_condition": (
            None if gate is None else
            {"gate": gate.get("gate"), "detail": gate.get("detail"),
             "value": gate.get("value"), "threshold": gate.get("threshold")}),
        "summary": ("A setup formed and the entry is shown" if setup is not None
                    else (gate or {}).get("detail")
                    or "no bar in the window has signalled so far"),
    }
    if source == RECONSTRUCTED:
        block["reconstructed_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(
            timespec="seconds")
        block["reconstructed_through"] = (str(reconstructed_through)
                                          if reconstructed_through is not None else None)
        block["warning"] = RECONSTRUCTION_WARNING
    return block


def not_yet_run_block(*, sleeve: str, slot_id: str, detector: str, at: str = "") -> dict:
    """A slot whose time has not come. Named rather than left blank, and never reconstructed."""
    return {
        "schema": SCHEMA,
        "diagnostics_source": NOT_YET_RUN,
        "sleeve": sleeve,
        "slot_id": slot_id,
        "detector": detector,
        "rows": [],
        "gates": [],
        "setup": None,
        "price_levels": [],
        "levels_armed": False,
        "nearest_failed_condition": None,
        "summary": (f"scheduled for {at}; it has not run yet" if at
                    else "this slot has not run yet"),
    }


# ══════════════════════════════════════════════════════════════════════════════════════════
# The runtime store. Append-only and dated, the same shape as every other evidence stream on
# this route, so a reader that can read one can read this.
#
# OBSERVABILITY ONLY. Nothing here is consulted by a gate, an audit verdict or a decision, and
# the caller writes it AFTER the coverage row for the reason that file states twice already:
# the coverage row is the evidence the audit counts, and a diagnostics failure must never be
# the reason a slot loses it.
# ══════════════════════════════════════════════════════════════════════════════════════════

RUNTIME_SUBDIR = ("global_index", "track1_runtime", "strategy_diagnostics")


def path_for(root, day: str):
    from pathlib import Path as _P
    compact = str(day).replace("-", "")
    return _P(root).joinpath(*RUNTIME_SUBDIR) / f"track1_strategy_diagnostics_{compact}.jsonl"


def record(block: dict, *, root="." , day: str | None = None):
    """Append one diagnostics block. Returns the path written."""
    import json
    p = path_for(root, day or str(block.get("session_date") or ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(block, default=str) + "\n")
    return p


def read(*, root=".", day: str) -> list:
    """Every block for one day, newest last. A missing file is an empty day, not an error."""
    import json
    p = path_for(root, day)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:                                          # noqa: BLE001
            continue
    return out


def recorded_series(root, day: str, sleeve: str) -> list:
    """EVERY recorded slot for one sleeve on one day, oldest first -- a session, not a snapshot.

    Stage 5ZZZ-AX. `recorded_for` returns the LAST block, which is the right answer for "what
    did the detector decide" and the wrong one for "what has the session been doing". The panel
    only ever had the snapshot, and a snapshot of this sleeve is actively misleading: slots fire
    on the five-minute boundary, so the newest bar is seconds old and its volume reads 0.
    Measured across 2026-08-31, the thirteen slots that carried numbers read

        volume       0  0  0  0  5  0  6  14  0  0  4  1  0
        ten-bar avg  5.8 ... 32.0

    -- a column of zeros beside a baseline that grew five-fold. No single slot can show that.

    Duplicated slot ids collapse to the LAST one, matching `recorded_for`, so a slot that was
    re-run does not appear twice on the line.
    """
    seen: dict = {}
    for block in read(root=root, day=day):
        if block.get("diagnostics_source") != RECORDED or block.get("sleeve") != sleeve:
            continue
        key = block.get("slot_id") or block.get("slot_time") or len(seen)
        seen[key] = block
    out = []
    for block in seen.values():
        values = {r.get("label"): r.get("value") for r in (block.get("rows") or [])}
        out.append({
            "slot_id": block.get("slot_id"),
            "slot_time": block.get("slot_time"),
            "bars_evaluated": block.get("bars_evaluated"),
            "last_bar_ts": block.get("last_bar_ts"),
            # Whether the newest bar had CLOSED. The reason a volume of 0 is a reading of a
            # bar seconds old rather than a dead market, and the line cannot say so without it.
            "last_bar_complete": block.get("last_bar_complete"),
            "values": values,
        })
    out.sort(key=lambda r: str(r.get("slot_time") or ""))
    return out


def recorded_for(root, day: str, sleeve: str, slot_id: str = "") -> "dict | None":
    """The most recent RECORDED block for a slot, or None.

    `slot_id` narrows when given. The LAST matching block wins, matching how every other
    reader on this route treats a repeated row.
    """
    hit = None
    for block in read(root=root, day=day):
        if block.get("diagnostics_source") != RECORDED:
            continue
        if block.get("sleeve") != sleeve:
            continue
        if slot_id and block.get("slot_id") != slot_id:
            continue
        hit = block
    return hit


# ══════════════════════════════════════════════════════════════════════════════════════════
# Calm — two phases, and the line between them. Stage 5ZZZ-E.
#
# WHAT WAS ALREADY THERE, AND WHY NOTHING HERE WRITES AT RUNTIME
# --------------------------------------------------------------
# Calm already records both phases while it runs. `_write_shadow_intent` appends a DECIDE row at
# 09:32 and an OBSERVE row at 10:02, every path, including the refusals — "silence is the one
# outcome that is not allowed". Adding a second runtime writer would put two accounts of one
# phase on disk, and the day they disagreed nobody could say which was the slot.
#
# So the runtime half of this stage is a READER. The reconstruction below is the only thing that
# computes, and only for a phase whose time has passed with no row.
#
# WHERE THE LINE IS, AND WHY IT IS NOT A JUDGEMENT CALL
# -----------------------------------------------------
# `detect_entry_for_day` IS `detect_setup_before_entry` plus two values:
#
#     entry        today's 10:00 bar open
#     entry_time   the timestamp of that bar
#
# Everything else on `CalmSetup` arrives from `CalmPreEntry`, which is fixed by 09:31. So the
# DECIDE-knowable set is exactly `CalmPreEntry`'s fields, and the OBSERVE-only set is exactly
# what `CalmSetup` adds — plus anything derived from `entry`, which is the planned stop and the
# risk it implies.
#
# That split is DERIVED from the two dataclasses rather than written out here, and a test
# asserts it against them. A hand-kept list of forbidden fields is a list that will one day be
# missing the field somebody just added.
#
# `open_loc_prev_range` is the trap worth naming. It reads like a price feature and is computed
# entirely from the 09:30 open, so it is DECIDE-knowable — the detector's own docstring flags it
# for exactly this reason.
# ══════════════════════════════════════════════════════════════════════════════════════════

CALM_DECIDE = "decide"
CALM_OBSERVE = "observe"


def calm_decide_fields() -> frozenset:
    """The field names a DECIDE block may carry, from `CalmPreEntry` itself."""
    from global_index.track1_calm_a import CalmPreEntry

    return frozenset(CalmPreEntry.__dataclass_fields__)


def calm_observe_only_fields() -> frozenset:
    """What the entry bar adds, from the two dataclasses — never a hand-kept list."""
    from global_index.track1_calm_a import CalmPreEntry, CalmSetup

    added = frozenset(CalmSetup.__dataclass_fields__) - frozenset(CalmPreEntry.__dataclass_fields__)
    # `planned_stop` and `risk_dollars` are not dataclass fields; they are computed FROM `entry`,
    # so they belong on the observe side by the same rule that puts `entry` there.
    return added | {"planned_stop", "entry_reference_price", "risk_dollars"}


def _calm_block(*, phase: str, source: str, slot_id: str, at: str, summary: str,
                rows=None, levels=None, **extra) -> dict:
    block = {
        "schema": SCHEMA,
        "diagnostics_source": source,
        "sleeve": "roska4_calm",
        "phase": phase,
        "slot_id": slot_id,
        "detector": "track1_calm_a",
        "scheduled_at": at,
        "rows": list(rows or []),
        "gates": [],
        "price_levels": list(levels or []),
        "levels_armed": bool(levels),
        "nearest_failed_condition": None,
        "summary": summary,
    }
    block.update(extra)
    return block


def _calm_decide_rows(before_entry: dict, params) -> list:
    """A DECIDE card. Every value here is fixed by 09:31.

    The stop appears as its RULE and not as a level. "entry - 1.5 x daily ATR" is fully known at
    half past nine; the number it evaluates to waits for ten o'clock, and printing a number now
    would be printing the one thing this phase is not allowed to know.
    """
    ri = (before_entry or {}).get("risk_inputs") or {}
    return [
        _row("Instrument", (before_entry or {}).get("instrument")),
        _row("Direction", (before_entry or {}).get("direction")),
        _row("Daily ATR (causal)", ri.get("daily_atr_causal"), unit="price",
             detail="fixed before the session opened"),
        _row("Stop rule", (before_entry or {}).get("stop_rule"),
             detail="the rule is known now; the level it evaluates to waits for the entry bar"),
        _row("Stop distance", ri.get("stop_distance"), unit="price",
             detail="a DISTANCE, not a level - it needs no entry price"),
        _row("Risk if taken", ri.get("risk_dollars"), unit="price",
             detail="the distance priced at this instrument's point value"),
        _row("Entry reference time", (before_entry or {}).get("entry_reference_time"),
             detail="when the entry price will be read, not what it will be"),
    ]


def _calm_observe_rows(before_entry: dict, after_reference: dict) -> list:
    """An OBSERVE card. Carries the matched DECIDE row's values plus what the entry bar added."""
    ri = (before_entry or {}).get("risk_inputs") or {}
    ar = after_reference or {}
    return [
        _row("Instrument", (before_entry or {}).get("instrument")),
        _row("Entry reference", ar.get("entry_reference_price"), unit="price",
             detail="today's 10:00 bar open - the bar the rule transacts at"),
        _row("Planned stop", ar.get("planned_stop"), unit="price",
             detail="the DECIDE rule, now that it has a price to evaluate against"),
        _row("Daily ATR (causal)", ri.get("daily_atr_causal"), unit="price"),
        _row("Stop distance", ri.get("stop_distance"), unit="price"),
        _row("Risk if taken", ri.get("risk_dollars"), unit="price"),
    ]


def _calm_instrument(rec: dict) -> str:
    """Which instrument a recorded Calm row is about, from the row itself."""
    for holder in (rec.get("before_entry"), rec.get("after_reference"), rec):
        if isinstance(holder, dict) and holder.get("instrument"):
            return str(holder["instrument"])
    return ""


def _calm_instrument_view(rec: dict, phase: str, params) -> dict:
    """One instrument's account of a phase, in the same shape the phase block carries.

    Stage 5ZZZ-BH. Built for every row the phase recorded, not just the last, so a basket
    sleeve stops showing one of its instruments and silently dropping the others.
    """
    be = rec.get("before_entry") or {}
    ar = rec.get("after_reference") or {}
    if phase == CALM_DECIDE:
        body = _calm_decide_rows(be, params) if be else []
    else:
        body = _calm_observe_rows(be, ar) if ar else []
    return {
        "instrument": _calm_instrument(rec),
        "direction": str(be.get("direction") or ""),
        "rows": body,
        "status": str(rec.get("status") or ""),
        "reason_code": str(rec.get("reason_code") or ""),
        # A planned stop belongs to the phase that reads the reference price, and to the
        # instrument it was computed for. Guarded by the phase for the same reason the block
        # above is: one malformed row must not print a stop at half past nine.
        "price_levels": ([{"kind": "stop", "label": "Planned stop",
                           "price": round(float(ar["planned_stop"]), 4), "armed": False}]
                         if (phase == CALM_OBSERVE and ar.get("planned_stop") is not None)
                         else []),
    }


def calm_blocks(root, day: str, now=None, *, slots=None) -> dict:
    """`{phase: block}` for Calm on one session. Reads the recorded stream; writes nothing.

    Order of preference, per phase, and it is the whole point of the function:

        a recorded row for that phase      -> recorded_runtime
        the phase's time has passed, none  -> reconstructed_today
        the phase's time has not come      -> not_yet_run, and never reconstructed
    """
    import pandas as pd
    from global_index import track1_calm_a as CA
    from global_index import track1_shadow_intent as si

    params = CA.CalmAParams()
    times = {CALM_DECIDE: ("TRACK1_CALM_DECIDE_0932", "09:32"),
             CALM_OBSERVE: ("TRACK1_CALM_OBSERVE_1002", "10:02")}
    ref = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="America/New_York")
    ref_naive = ref.tz_convert("America/New_York").tz_localize(None) if ref.tzinfo else ref
    same_day = str(pd.Timestamp(day).date()) == str(ref_naive.date())

    try:
        rows = si.read_day(root, str(pd.Timestamp(day).date()))
    except Exception:                                              # noqa: BLE001
        rows = []

    out: dict = {}
    for phase, (slot_id, hhmm) in times.items():
        want = si.DECIDE if phase == CALM_DECIDE else si.OBSERVE
        mine = [r for r in rows if r.get("phase") == want]
        due = pd.Timestamp(f"{pd.Timestamp(day).date()} {hhmm}")
        passed = (not same_day) or ref_naive >= due

        # The instant is checked BEFORE the record, and the order matters. A caller asking what
        # 09:32 looked like at 09:00 is asking about a phase that had not run yet, and handing
        # back the row it wrote half an hour later would be answering a different question with
        # a real artefact - the most convincing way to be wrong.
        if not passed:
            out[phase] = not_yet_run_block(sleeve="roska4_calm", slot_id=slot_id,
                                           detector="track1_calm_a", at=f"{hhmm} ET")
            out[phase]["phase"] = phase
            continue

        if mine:
            # Stage 5ZZZ-BH. `mine[-1]` used to be the whole answer, and it threw the rest
            # away without a word.
            #
            # This sleeve trades a BASKET: measured on 2026-08-31 it recorded two setups in
            # one phase, MES and MNQ, with different numbers --
            #
            #     prior_rth_close_bottom_third   MES 0.1555   MNQ 0.1581
            #     prior_rth_down_close           MES -0.0030  MNQ -0.0044
            #
            # -- and the panel showed one card, carrying MNQ because it was written last,
            # with no instrument named on it and nothing to say a second setup existed. An
            # operator reading a single stop level had no way to know half the sleeve's day
            # was missing.
            #
            # The dict stays keyed by phase, because the two phases ARE the sleeve's shape and
            # every reader is built on that. What changes is that the block now carries every
            # instrument the phase recorded, and NAMES the one whose values sit at the top
            # level -- so the pick is stated instead of silent.
            rec = mine[-1]
            be = rec.get("before_entry") or {}
            ar = rec.get("after_reference") or {}
            status = str(rec.get("status") or "")
            code = str(rec.get("reason_code") or "")
            if phase == CALM_DECIDE:
                body = _calm_decide_rows(be, params) if be else []
                summary = ("A setup was recorded; the entry price waits for 10:00" if be
                           else f"No setup recorded at 09:32 - {code}")
            else:
                body = _calm_observe_rows(be, ar) if ar else []
                summary = ("The entry reference was read and the stop evaluated" if ar
                           else f"Nothing observed - {code}")
            out[phase] = _calm_block(
                phase=phase, source=RECORDED, slot_id=slot_id, at=hhmm, summary=summary,
                rows=body,
                # Stage 5ZZZ-E, after a mutation came back green honestly. Until this line the
                # DECIDE card carried no level only because a DECIDE row on disk happens to have
                # no `after_reference` - the leak was prevented by the DATA, not by the code, and
                # one malformed row would have printed a stop price at half past nine. The phase
                # now decides it.
                levels=([{"kind": "stop", "label": "Planned stop",
                          "price": round(float(ar["planned_stop"]), 4), "armed": False}]
                        if (phase == CALM_OBSERVE and ar.get("planned_stop") is not None)
                        else []),
                status=status, reason_code=code,
                params_hash=rec.get("params_hash") or "",
                data_source_identity=rec.get("data_identity") or "",
                matched_decide=(bool(be) if phase == CALM_OBSERVE else None),
                instrument=_calm_instrument(rec),
                instruments=[_calm_instrument_view(r, phase, params) for r in mine],
                instrument_count=len(mine))
            # Stage 5ZZZ-AR. The recorded row says WHAT happened; the gates say WHY, and they
            # live in a different stream.
            #
            # The obvious move was to add a `gates` field to the shadow-intent row. It was
            # measured and rejected: that record has SIX readers, two of them gates
            # (`track1_paper_readiness`, `track1_replay_parity`), and the stream is four rows
            # old. Changing the shape of a running evidence record to carry a diagnostic is a
            # large blast radius for an observability field.
            #
            # The diagnostics stream already exists, already carries `gates`, and is where the
            # other two sleeves put exactly this. So the intent row is left untouched and the
            # gates are merged in on READ. When no diagnostics block exists -- every day before
            # the writer lands, and every day the slot did not run -- this adds nothing and the
            # panel is what it was.
            _merge_recorded_gates(out[phase], root, day, slot_id)
            continue

        out[phase] = _calm_reconstruct(root, day, phase, slot_id, hhmm, params, out)
    return out


def _merge_recorded_gates(block: dict, root, day, slot_id: str) -> None:
    """Add the gates the slot recorded for this phase, and nothing else.

    Only `gates` and the first refusal are taken. The recorded row remains the authority on
    status, rows and levels: a diagnostics block that could overwrite those would be a second
    account of the same phase, and the day the two disagreed nobody could say which was the
    slot.
    """
    try:
        rec = recorded_for(root, str(day), "roska4_calm", slot_id)
        gates = list((rec or {}).get("gates") or [])
        if not gates:
            return
        block["gates"] = gates
        block["nearest_failed_condition"] = next(
            (g for g in gates if g.get("passed") is False), None)
    except Exception:                                              # noqa: BLE001
        pass


def _calm_reconstruct(root, day, phase, slot_id, hhmm, params, so_far: dict) -> dict:
    """A phase whose time has passed and which left no row. Computes; never writes.

    The OBSERVE half refuses without a DECIDE, exactly as the live path does. An observe answer
    standing alone would say a reference price was seen and imply a decision behind it that
    nobody can point to, and that collapse is what the two phases exist to prevent - a
    reconstruction is not a licence to do it after the fact.
    """
    import datetime as _d
    import pandas as pd

    common = dict(phase=phase, source=RECONSTRUCTED, slot_id=slot_id, at=hhmm)
    stamp = {"reconstructed_at": _d.datetime.now(_d.timezone.utc).isoformat(timespec="seconds"),
             "warning": RECONSTRUCTION_WARNING, "reconstructed_through": str(day)}

    if phase == CALM_OBSERVE:
        decide = so_far.get(CALM_DECIDE) or {}
        has_setup = bool(decide.get("rows"))
        if not has_setup:
            return _calm_block(
                **common, summary="No DECIDE row for this day, so there is nothing to observe",
                rows=[], **stamp, matched_decide=False,
                reason_code="no_decide_row_for_this_day", status="REFUSED")

    try:
        from global_index import track1_calm_a as CA
        from monitor.backend import track1_market_view as mv

        frames = {}
        for inst in params.instruments:
            path = mv._store_path(inst)
            if path and Path(path).exists():
                frames[inst] = pd.read_parquet(path)
        if not frames:
            return _calm_block(**common, summary="no persisted bar store for Calm's instruments",
                               rows=[], **stamp, missing=MISSING_DATA)
        labels = mv._label_map(Path(root))
        found = []
        # Stage 5ZZZ-AQ. Collect each instrument's gates so a session that did NOT set up can
        # say which condition stopped it. Before this the replay reported "did not set up" and
        # nothing else, which is the same silence the detector used to be incapable of
        # breaking. Per instrument, because two instruments can fail at different conditions
        # and merging them would produce a reason that belongs to neither.
        seen_gates: dict = {}
        for inst, frame in frames.items():
            _g: list = []
            pre = CA.detect_setup_before_entry(frame, labels, inst, pd.Timestamp(day), params,
                                               observer=lambda e, _g=_g: (
                                                   _g.append({k: v for k, v in e.items()
                                                              if k != "kind"})
                                                   if e.get("kind") == "gate" else None))
            seen_gates[inst] = _g
            if pre is not None:
                found.append((inst, pre))

        def _gates_for(inst_name):
            g = list(seen_gates.get(inst_name) or [])
            first_failed = next((x for x in g if x.get("passed") is False), None)
            return {"gates": g, "nearest_failed_condition": first_failed}

        if not found:
            # The first instrument's account, NAMED as that instrument's: this branch means no
            # instrument set up, and picking one silently would read as a statement about the
            # sleeve rather than about one contract.
            first_inst = next(iter(frames))
            g = _gates_for(first_inst)
            why = (g["nearest_failed_condition"] or {}).get("gate")
            return _calm_block(**common, rows=[], **stamp,
                               summary=("Replayed: this session did not set up"
                                        + (f" — {first_inst} stopped at {why}" if why else "")),
                               status="NO_SETUP", reason_code="no_candidate", **g)
        inst, pre = found[0]
        be = {"instrument": inst, "direction": pre.direction,
              "stop_rule": "entry - %s x daily_atr" % params.disaster_stop_atr_mult,
              "entry_reference_time": params.entry_time, "risk_inputs": {}}
        if phase == CALM_DECIDE:
            # Only the gates this phase is allowed to know. `detect_setup_before_entry` is the
            # only thing that emitted here, and everything it reports is fixed by 09:31 --
            # `entry_time_valid` comes from `detect_entry_for_day`, which this branch does not
            # call, so the phase boundary is kept by which function ran rather than by a filter
            # someone has to remember to apply.
            return _calm_block(**common, rows=_calm_decide_rows(be, params), **stamp,
                               summary="Replayed: this session set up before the entry bar",
                               status="RECORDED", reason_code="ok", **_gates_for(inst))
        ref, _ts = CA._bar_open_at(frames[inst], pd.Timestamp(day).normalize(),
                                   params.entry_time)
        if ref is None:
            return _calm_block(**common, rows=[], **stamp, matched_decide=True,
                               summary="Replayed: the entry reference bar is not readable",
                               status="REFUSED", reason_code="entry_reference_not_readable")
        ar = {"entry_reference_price": float(ref), "planned_stop": None}
        return _calm_block(**common, rows=_calm_observe_rows(be, ar), **stamp,
                           matched_decide=True, status="RECORDED", reason_code="ok",
                           summary="Replayed: the entry reference was read")
    except Exception as exc:                                       # noqa: BLE001
        return _calm_block(**common, rows=[], **stamp, missing=MISSING_DATA,
                           summary=f"could not be replayed ({type(exc).__name__})")
