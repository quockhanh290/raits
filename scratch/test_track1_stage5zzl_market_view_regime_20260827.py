"""Stage 5ZZL — the market view, the regime monitor, and the things neither may invent.

Two panels, and the same discipline behind both: **render only what something else decided.**

The strategy publishes no prices. Every rule in the signal diagnostics carries
`source: not_exposed_by_sleeve` with a null value, so there is no entry, stop or target to
draw — and a line at a level nobody published is a line an operator would trade against. The
model publishes a regime label and nothing underneath it: no score, no probability, no shift
threshold, so "distance to a regime change" has nothing to read.

Both of those are said in words on the page. These tests hold that they stay said, and that
neither panel starts computing its way around the gap.

Nothing here connects to a broker or writes to the runtime tree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.backend import track1_market_view as mv             # noqa: E402
from global_index import track1_regime_record as rr              # noqa: E402

JS = ROOT / "global_index" / "dash" / "realtime" / "realtime.js"
HTML = ROOT / "global_index" / "dash" / "realtime" / "index.html"
CSS = ROOT / "global_index" / "dash" / "realtime" / "realtime.css"


def _payload():
    return mv.build(ROOT)


# ── backend: shape and ranges ───────────────────────────────────────────────────────────
def test_all_three_sleeves_are_present_with_their_own_windows():
    """The WINDOWS are the contract; they are the sleeve's trading hours and are not derived."""
    p = _payload()
    assert sorted(p["sleeves"]) == ["global_nkd", "roska4_stress", "roska4_swing"]
    want = {"global_nkd": ("01:10", "02:55"),
            "roska4_stress": ("10:35", "12:30"),
            "roska4_swing": ("14:05", "15:55")}
    for sleeve, (ws, we) in want.items():
        r = p["sleeves"][sleeve]["range"]
        assert (r["window_start_et"], r["window_end_et"]) == (ws, we), sleeve


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def test_every_sleeve_draws_the_same_span_around_its_own_window():
    """Stage 5ZZZ-BY. Pinned as a RELATIONSHIP, because pinning the four clock strings is what
    let them drift in the first place.

    They were written out per sleeve and only three of the six offsets agreed. Measured
    2026-08-31: leads of -70, -65 and -275 minutes with tails of +10, +10 and +10 -- the tail
    agreeing by coincidence between three separately typed strings. Stress and Swing both
    started at the RTH open, so a sleeve whose window sits late in the day drew four and a half
    hours of run-up that carries nothing about it: eighty candles for twenty-three slots, with
    the bars that matter squeezed into the right-hand quarter.
    """
    p = _payload()
    spans = {}
    for sleeve, s in p["sleeves"].items():
        r = s["range"]
        spans[sleeve] = (_mins(r["context_start_et"]) - _mins(r["window_start_et"]),
                         _mins(r["context_end_et"]) - _mins(r["window_end_et"]))
    assert spans, "no sleeve published a range -- the probe is wrong"
    assert len(set(spans.values())) == 1, spans
    lead, tail = next(iter(spans.values()))
    assert (lead, tail) == (-mv.CHART_LEAD_MINUTES, mv.CHART_TAIL_MINUTES), spans


def test_the_span_comes_from_the_constants_not_from_a_second_copy():
    """One number for the lead and one for the tail. A sleeve carrying its own would be the
    same defect returning under a different name."""
    for sleeve, spec in mv.SLEEVES.items():
        assert spec["context_start"] == mv._shift_hhmm(
            spec["window_start"], -mv.CHART_LEAD_MINUTES), sleeve
        assert spec["context_end"] == mv._shift_hhmm(
            spec["window_end"], mv.CHART_TAIL_MINUTES), sleeve


def test_a_window_near_midnight_clamps_instead_of_wrapping():
    """A 00:10 open would take its lead-in to 23:10 the evening before, and the slice asks for
    bars BETWEEN start and end -- it would come back empty. An hour of missing run-up is a
    smaller lie than an empty chart."""
    assert mv._shift_hhmm("00:10", -60) == "00:00"
    assert mv._shift_hhmm("23:55", 10) == "23:59"
    assert mv._shift_hhmm("10:35", -60) == "09:35"


def test_calm_is_deliberately_absent():
    """Calm is a two-phase one-shot contract. A candle chart of a single decision instant
    would draw a window it does not have."""
    assert "roska4_calm" not in _payload()["sleeves"]
    assert "roska4_calm" not in mv.SLEEVES


def test_bars_stay_inside_the_declared_context_range():
    p = _payload()
    for sleeve, s in p["sleeves"].items():
        bars = s.get("bars") or []
        if not bars:
            continue
        r = s["range"]
        clocks = [b["time"].split(" ")[1] for b in bars]
        assert min(clocks) >= r["context_start_et"], (sleeve, min(clocks))
        assert max(clocks) <= r["context_end_et"], (sleeve, max(clocks))


def test_bars_are_five_minute_and_ohlc_consistent():
    p = _payload()
    for sleeve, s in p["sleeves"].items():
        for b in (s.get("bars") or [])[:40]:
            assert b["low"] <= b["open"] <= b["high"], (sleeve, b)
            assert b["low"] <= b["close"] <= b["high"], (sleeve, b)
            assert int(b["time"][-2:]) % mv.BAR_MINUTES == 0, b


def test_the_session_the_bars_came_from_is_reported():
    """The parquet is appended once a day and the live half is spliced in memory and thrown
    away, so 'today' is normally empty. Substituting the newest stored session silently would
    make a stale chart look current."""
    p = _payload()
    for s in p["sleeves"].values():
        if s.get("bars"):
            assert s.get("bars_session_date")
            if s["bars_session_date"] != p["session_date"]:
                assert s.get("bars_note"), "a substituted session with no explanation"
                assert s["bars_session_date"] in s["summary"]


# ── backend: levels are never invented ──────────────────────────────────────────────────
def test_levels_are_not_exposed_and_say_so():
    """The finding this panel had to be built around."""
    p = _payload()
    for sleeve, s in p["sleeves"].items():
        assert s["levels"] == [], f"{sleeve} produced a level from evidence that has none"
        assert s["levels_note"] == mv.LEVELS_NOT_EXPOSED
        # Stage 5ZZM reworded this to `Strategy levels unavailable`. The invariant is
        # unchanged and is what is asserted: the summary SAYS the levels are missing rather
        # than leaving the reader to notice no lines were drawn.
        assert (mv.LEVELS_NOT_EXPOSED.lower() in s["summary"].lower()
                or s["status"] == "waiting")


def test_a_level_is_only_ever_taken_from_a_measured_rule():
    """The scan must not promote a rule the sleeve declined to expose."""
    rows = [{"sleeve": "roska4_stress", "slot_id": "S1", "rule_checks": [
        {"rule": "entry_price", "value": 21000.0, "source": "not_exposed_by_sleeve"},
        {"rule": "stop_price", "value": None, "source": "measured"},
        {"rule": "gate_allow", "value": 1.0, "source": "measured"},
    ]}]
    assert mv._levels(rows, "roska4_stress") == []


def test_a_measured_price_rule_would_be_drawn():
    """Written as a scan rather than `return []` so the day a detector publishes a price it
    appears without anyone remembering this function exists. Pinned so that stays true."""
    rows = [{"sleeve": "roska4_stress", "slot_id": "S1", "rule_checks": [
        {"rule": "entry_price", "value": 21000.5, "source": "measured"}]}]
    got = mv._levels(rows, "roska4_stress")
    assert got and got[0]["kind"] == "entry" and got[0]["price"] == 21000.5
    assert got[0]["source"] == "strategy_evidence"


# ── backend: slots ──────────────────────────────────────────────────────────────────────
def test_every_declared_slot_gets_a_marker():
    from global_index import track1_slots as ts
    p = _payload()
    for sleeve, s in p["sleeves"].items():
        declared = {x.id for x in ts.TRACK1_SLOTS if x.sleeve == sleeve}
        drawn = {x["slot_id"] for x in s["slots"]}
        assert declared <= drawn, f"{sleeve} lost {declared - drawn}"


def test_a_slot_that_has_not_fired_is_future_not_missing():
    rows: list = []
    slots = mv._slots_for("roska4_swing", rows, "09:00")
    assert slots and all(x["status"] == mv.SLOT_FUTURE for x in slots)


def test_a_slot_past_its_time_with_no_record_is_missed_not_no_signal():
    """Absence is not a quiet result. This route has been bitten by that before."""
    slots = mv._slots_for("roska4_swing", [], "23:59")
    assert slots and all(x["status"] == mv.SLOT_MISSED for x in slots)
    assert all(x["status"] != mv.SLOT_NO_SIGNAL for x in slots)


def test_slot_counts_come_from_the_window_ledger_not_from_the_markers():
    """A refused slot leaves a row here and is not an observation there. Printing the marker
    count as 'observed' reported 24/24 for a sleeve the ledger recorded as 18 of 24."""
    slots = [{"slot_id": "a", "time_et": "10:35", "status": mv.SLOT_REFUSED,
              "reason": "", "candidate_count": 0}] * 24
    line = mv._summary("roska4_stress", mv.ST_INCOMPLETE, slots, [], {},
                       None, "2026-08-27", {"observed_slots": 18, "expected_slots": 24})
    assert "18/24" in line and "24/24" not in line


# ── backend: data status ────────────────────────────────────────────────────────────────
def test_no_observation_is_not_a_data_refusal():
    """Measured on 2026-08-27: Swing had recorded nothing because its window had not opened.
    Calling that 'data refused' sends an operator to inspect a feed that is working."""
    data = {"provider_reason": "this sleeve recorded no observation for this instrument",
            "ok": None}
    line = mv._summary("roska4_swing", mv.ST_WAITING, [], [], data, None, "2026-08-27", {})
    assert "Data refused" not in line
    assert "Waiting" in line


def test_a_real_provider_refusal_is_surfaced():
    data = {"provider_reason": "IBKR 162: Historical Market Data Service error message",
            "ok": False}
    line = mv._summary("roska4_stress", mv.ST_REFUSED, [], [], data, None, "2026-08-27", {})
    assert "Data refused" in line and "IBKR 162" in line


def test_data_status_keeps_three_states():
    p = _payload()
    for s in p["sleeves"].values():
        d = s["data_status"]
        for key in ("provider", "ok", "latest_bar_et", "live_rows_fetched",
                    "splice_result", "provider_reason"):
            assert key in d
        assert d["ok"] in (True, False, None), "ok must keep its 'nobody looked' state"


def test_the_payload_never_raises_on_a_broken_root(tmp_path):
    """A panel that 500s tells an operator less than one that says which part it could not
    read."""
    p = mv.build(tmp_path)
    assert sorted(p["sleeves"]) == ["global_nkd", "roska4_stress", "roska4_swing"]
    for s in p["sleeves"].values():
        assert s["bars"] == [] or isinstance(s["bars"], list)
        assert s["summary"]


def test_the_builder_opens_no_connection():
    text = (ROOT / "monitor" / "backend" / "track1_market_view.py").read_text(encoding="utf-8")
    for forbidden in ("IBKRBroker", "reqHistoricalData", "fetch_bars", "connect("):
        assert forbidden not in text, forbidden


# ── regime ──────────────────────────────────────────────────────────────────────────────
def test_regime_reports_label_and_verification():
    r = mv.regime(ROOT)
    assert r["status"] in ("PASS", "UNKNOWN")
    assert "verification" in r
    assert "line" in r and r["line"]


def test_regime_names_the_missing_threshold_and_publishes_the_score():
    """Corrected by Stage 5ZZP, and the correction is the interesting part.

    This asserted that the model published NOTHING under the label, which was read off the
    return type of `label_regimes` — a series of strings. The ENGINE has `predict_proba`, so a
    posterior exists and is now recorded: `not returned` was never the same as `not computed`.

    The threshold half stands, and stands for a stronger reason than before: Viterbi compares
    states against each other rather than against a cut, so there is no threshold to be near.
    """
    r = mv.regime(ROOT)
    assert r["shift_threshold"] is None
    assert "Viterbi" in r["threshold_note"], r["threshold_note"]
    if r["status"] == "PASS":
        assert r["score"] is not None and 0.0 <= r["score"] <= 1.0, r["score"]
        assert r["score_name"] == rr.SCORE_NAME


def test_a_missing_regime_record_is_unknown_not_calm(tmp_path):
    """Failing to a label would be the worst available default: Calm is the permissive
    regime, and a labeller that could not run must not read like one that answered 'safe'."""
    rec = rr.latest(tmp_path)
    assert rec.status == rr.UNREADABLE
    assert rec.label is None
    assert "never measured" in rec.detail or "no regime" in rec.detail.lower()


def test_a_stale_regime_record_is_unknown(tmp_path):
    rr.record(rr.RegimeRecord(status=rr.OK, code="labelled", label="Calm",
                              label_date="2026-08-01",
                              checked_at="2026-08-01T00:00:00+00:00"), root=tmp_path)
    rec = rr.latest(tmp_path)
    assert rec.status == rr.UNREADABLE and rec.code == "record_stale"


def test_the_age_cap_is_resolved_at_call_time(tmp_path, monkeypatch):
    """Bound as a default it would freeze at import and patching the constant would change
    nothing while appearing to — a trap this project has now been caught by twice."""
    rr.record(rr.RegimeRecord(status=rr.OK, code="labelled", label="Calm",
                              label_date="2026-08-26",
                              checked_at="2026-08-26T00:00:00+00:00"), root=tmp_path)
    monkeypatch.setattr(rr, "MAX_RECORD_AGE_HOURS", 100_000)
    assert rr.latest(tmp_path).status == rr.OK
    monkeypatch.setattr(rr, "MAX_RECORD_AGE_HOURS", 1)
    assert rr.latest(tmp_path).status == rr.UNREADABLE


def test_the_recorder_carries_the_inputs_that_produced_the_label():
    """A label without the fit window that produced it is a label nobody can reproduce —
    the FreezeRecord mistake this project already made once."""
    rec = rr.latest(ROOT)
    if rec.status != rr.OK:
        pytest.skip("no regime record on this checkout")
    for key in ("benchmark_csv", "start", "n_states", "fit_end"):
        assert key in rec.inputs, key


# ── the page ────────────────────────────────────────────────────────────────────────────
def _js(strip_comments: bool = True) -> str:
    text = JS.read_text(encoding="utf-8")
    if not strip_comments:
        return text
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            i = n if j < 0 else j + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def test_the_page_declares_both_panels():
    html = HTML.read_text(encoding="utf-8")
    assert "Track 1 Market View" in html
    assert "Regime Monitor" in html
    assert 'id="marketViewChart"' in html and 'id="regimeFacts"' in html


def test_the_regime_panel_is_not_a_tab_of_the_chart():
    """They answer different questions on different clocks — one intraday and per sleeve, the
    other daily and route-wide."""
    html = HTML.read_text(encoding="utf-8")
    assert html.index("Track 1 Market View") < html.index("Regime Monitor")
    assert "regime-section" in html and "market-view-section" in html
    mv_block = html[html.index("market-view-section"):html.index("regime-section")]
    assert "Regime" not in mv_block


def test_no_external_script_is_loaded_by_the_operator_page():
    """The measured reason this chart is hand-drawn. If a CDN tag ever appears here it is a
    decision someone should have to make on purpose."""
    html = HTML.read_text(encoding="utf-8")
    for host in ("https://", "http://", "cdn.", "unpkg", "jsdelivr"):
        assert f'src="{host}' not in html, host


def _mv_block(strip_comments: bool = True) -> str:
    """Only the code this stage added. Scoped deliberately: the page has long-standing prose
    that NAMES the model ("The HMM stale guard is hard-tripped"), and a whole-file search for
    that word fails on a label rather than on a computation. The first version of this test
    did exactly that."""
    code = _js(strip_comments)
    start = code.index("const MV_ORDER")
    end = code.index("function renderOpenIssues")
    return code[start:end]


def test_the_page_does_not_compute_strategy_or_regime_values():
    block = _mv_block()
    for forbidden in ("label_regimes", "benchmark_daily", "decode(", "atr(", "stdev(",
                      "entryPrice =", "computeLevel", "Math.exp", "Math.log"):
        assert forbidden not in block, forbidden
    assert "state.marketView" in block, "the page must read the payload it is given"
    # Every value it draws is addressed out of the payload rather than derived.
    # Stage 5ZZR moved the levels under the boundary that publishes them; the point of this
    # check is that each value is ADDRESSED out of the payload, not which key it sits at.
    for read in ("sleeve.bars", "sleeve.slots", "sleeve.setup_boundary", "r.label"):
        assert read in block, read


def test_no_raw_field_names_reach_the_visible_labels():
    """`gate_allow`, `breadth_down_count`, `splice_result` are names for the code.

    Stage 5ZZM: `splice_result` now appears as a KEY in the translation table, which is the
    opposite of the problem — it is there so the token never reaches a screen. The map is cut
    out before scanning, and the DOM test below is what actually proves nothing raw is
    rendered.
    """
    code = _mv_block()
    start = code.index("const MV_WORDS")
    table = code[start:code.index("}", start)]
    outside = code.replace(table, "")
    for raw in ("'gate_allow'", '"gate_allow"', "breadth_down_count"):
        assert raw not in outside, raw
    assert "Splice result" not in outside


def test_the_chart_uses_the_sleeve_clock_rather_than_the_viewers():
    """These stamps are wall-clock on the sleeve's own exchange clock. Handing them to a Date
    would reinterpret them in the browser's zone — the thirteen-hour class of error this
    project already paid for once."""
    code = _mv_block()
    assert "function mvClock" in code
    tail = code[code.index("function mvClock"):]
    assert "new Date" not in tail[:400]


def test_marker_vocabulary_distinguishes_future_from_missing():
    code = _mv_block()
    assert "future:" in code and "missed:" in code
    assert "hollow: true" in code


# ═══════════════════════════════════════════════════════════════════════════════════════
# DOM — the real page in a real browser, API stubbed
# ═══════════════════════════════════════════════════════════════════════════════════════
pytest.importorskip("playwright.sync_api")
from monitor.test_realtime_dom import (           # noqa: E402
    BASE_PAYLOADS, browser_page, open_realtime, realtime_server, stub_api)

assert browser_page and realtime_server           # re-exported fixtures, used by pytest


def _bars(n=12, start="09:30"):
    h, m = int(start[:2]), int(start[3:])
    out = []
    for i in range(n):
        t = h * 60 + m + i * 5
        out.append({"time": f"2026-08-26 {t // 60:02d}:{t % 60:02d}",
                    "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100.5 + i})
    return out


def _sleeve(label, inst, ws, we, bars=None, slots=None, status="complete", **kw):
    d = {"label": label, "instrument": inst, "bar_interval": "5m", "clock": "America/New_York",
         "range": {"context_start_et": "09:30", "window_start_et": ws,
                   "window_end_et": we, "context_end_et": "16:05"},
         "status": status,
         # Stage 5ZZZ-F. The stub said "entry levels not exposed", which the backend stopped
         # saying in Stage 5ZZM. A DOM test that feeds a page the old wording and then demands
         # the page not show it is asking the page to censor its own data source; the fixture
         # was the thing that was stale.
         "summary": f"{status.title()} - 3/3 slots observed - no signal - "
                    f"Strategy levels unavailable",
         # Bars generated from the sleeve's OWN window start, not a shared 09:30. The first
         # version handed NKD 09:30 bars for a 01:10-02:55 window, so no bar fell inside the
         # band and the band test failed on the fixture rather than on the code.
         "bars": bars if bars is not None else _bars(start=ws),
         "bars_session_date": "2026-08-26", "bars_note": "",
         "slots": slots if slots is not None else
                  [{"slot_id": "A", "time_et": ws, "status": "no_signal",
                    "reason": "decided", "candidate_count": 0}],
         # Stage 5ZZM: taken from the backend constant rather than retyped, so the fixture
         # cannot drift away from the copy the page actually receives. It was a hardcoded
         # copy of the OLD phrase, which meant the layout probe reported the old wording as
         # still visible after the backend had stopped emitting it.
         "levels": [], "levels_note": mv.LEVELS_NOT_EXPOSED,
         "levels_detail": mv.LEVELS_DETAIL,
         "data_status": {"provider": "ibkr", "ok": True, "latest_bar_et": "2026-08-26 15:55",
                         "live_rows_fetched": 120, "splice_result": "ok",
                         "provider_reason": None}}
    d.update(kw)
    return d


def _mv_payload():
    return {"market_view": {"schema": "track1_market_view/1", "route": "track1_candidate",
                            "session_date": "2026-08-27", "now_et": "13:00",
                            "levels_note": "Strategy levels unavailable",
                            "sleeves": {
                                "global_nkd": _sleeve("NKD", "MNKD", "01:10", "02:55"),
                                "roska4_stress": _sleeve("Stress", "MNQ", "10:35", "12:30"),
                                "roska4_swing": _sleeve("Swing", "MES", "14:05", "15:55")}},
            "regime": {"status": "PASS", "code": "labelled", "label": "Calm",
                       "label_date": "2026-08-26", "age_hours": 0.3,
                       "detail": "2174 label(s)", "line": "Regime Calm as of 2026-08-26",
                       "recent": [{"date": "2026-08-26", "label": "Calm"}],
                       "context": [{"date": "2026-08-26", "label": "Calm"}] * 60,
                       # Stage 5ZZP: the score is real now, so the fixture carries one.
                       "score": 0.9984,
                       "score_name": "posterior probability of the labelled state",
                       "shift_threshold": None,
                       "margin": 0.9967,
                       "margin_name": "probability margin over the next most likely state",
                       "runner_up": "Normal",
                       "state_probabilities": {"Calm": 0.9984, "Normal": 0.0016,
                                               "Stress": 0.0},
                       "posterior_agrees_with_label": True,
                       "score_note": "",
                       # Derived, not copied. A fixture holding its own transcription of a
                       # production string goes stale silently — this one already had, and the
                       # DOM tests then asserted against wording the model no longer used.
                       "threshold_note": rr.NO_THRESHOLD,
                       "verification": {"status": "PASS",
                                        "detail": "1761 compared, none changed"}}}


def _open(page, server, payload=None):
    stub_api(page, {"/api/v1/track1-market-view": payload or _mv_payload()})
    open_realtime(page, server)
    page.wait_for_selector("#marketViewTabs .mv-tab", timeout=10_000)


def test_dom_the_panel_renders_with_three_tabs(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    tabs = browser_page.eval_on_selector_all(
        "#marketViewTabs .mv-tab", "els => els.map(e => e.textContent.trim())")
    assert tabs == ["NKD", "Stress", "Swing"], tabs


def test_dom_a_chart_is_drawn(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    assert browser_page.eval_on_selector_all("#marketViewChart .mv-body", "e => e.length") > 0
    assert browser_page.eval_on_selector_all("#marketViewChart .mv-band", "e => e.length") == 1


def test_dom_slot_markers_are_drawn(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    assert browser_page.eval_on_selector_all("#marketViewChart .mv-mark", "e => e.length") >= 1


def test_dom_the_empty_state_is_intentional(browser_page, realtime_server):
    """Not a blank black rectangle: it says what is missing and why."""
    p = _mv_payload()
    p["market_view"]["sleeves"]["global_nkd"] = _sleeve(
        "NKD", "MNKD", "01:10", "02:55", bars=[],
        bars_note="no persisted bars for 2026-08-27")
    _open(browser_page, realtime_server, p)
    text = browser_page.eval_on_selector("#marketViewChart", "el => el.innerText")
    # `.mv-empty b` is uppercased by CSS, so innerText comes back shouting. Compared
    # case-insensitively rather than pinned to the rendered casing.
    # Stage 5ZZM reworded the heading and made the second line name the stored session
    # instead of echoing the internal note. Still one intentional empty state, still no SVG.
    assert "no bars available for this session" in text.lower(), text
    assert "2026-08-26" in text
    assert browser_page.eval_on_selector_all("#marketViewChart .mv-svg", "e => e.length") == 0


def test_dom_a_provider_refusal_is_shown(browser_page, realtime_server):
    p = _mv_payload()
    s = p["market_view"]["sleeves"]["global_nkd"]
    s["status"] = "refused"
    s["summary"] = "Data refused - IBKR 162: Historical Market Data Service error - no live bars"
    s["data_status"]["provider_reason"] = "IBKR 162: Historical Market Data Service error"
    s["data_status"]["ok"] = False
    _open(browser_page, realtime_server, p)
    # Stage 5ZZM: the summary is chips now. The refusal shows as the status chip and a
    # `No live bars` chip, and the provider's own words stay reachable on hover and in the
    # footer — the invariant is that the reason is still FINDABLE, not that it is a sentence.
    chips = browser_page.eval_on_selector_all(
        "#marketViewSummary .mv-chip", "els => els.map(e => e.textContent.trim())")
    assert "DATA REFUSED" in chips and "No live bars" in chips, chips
    reachable = browser_page.eval_on_selector(".market-view-section", "el => el.innerHTML")
    assert "IBKR 162" in reachable


def test_dom_the_missing_levels_are_said_in_words(browser_page, realtime_server):
    """Stage 5ZZM reworded it. The panel must still SAY the levels are missing — silence
    would read as 'the strategy had no view', which is a different claim."""
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector(".market-view-section", "el => el.innerText")
    assert "strategy levels unavailable" in text.lower(), text


def test_dom_switching_tabs_keeps_the_panel_height(browser_page, realtime_server):
    """A panel that resizes under the pointer is a panel an operator misclicks."""
    _open(browser_page, realtime_server)
    h0 = browser_page.eval_on_selector("#marketViewChart",
                                       "el => el.getBoundingClientRect().height")
    for tab in ("Stress", "Swing"):
        browser_page.click("#marketViewTabs .mv-tab:has-text(\"" + tab + "\")")
        h = browser_page.eval_on_selector("#marketViewChart",
                                          "el => el.getBoundingClientRect().height")
        assert abs(h - h0) < 1.0, f"{tab} changed the panel height {h0} -> {h}"


def test_dom_an_empty_tab_keeps_the_same_height(browser_page, realtime_server):
    p = _mv_payload()
    p["market_view"]["sleeves"]["roska4_swing"] = _sleeve(
        "Swing", "MES", "14:05", "15:55", bars=[], bars_note="no bars")
    _open(browser_page, realtime_server, p)
    h0 = browser_page.eval_on_selector("#marketViewChart",
                                       "el => el.getBoundingClientRect().height")
    browser_page.click("#marketViewTabs .mv-tab:has-text(\"Swing\")")
    h = browser_page.eval_on_selector("#marketViewChart",
                                      "el => el.getBoundingClientRect().height")
    assert abs(h - h0) < 1.0, f"the empty state changed the height {h0} -> {h}"


def test_dom_the_regime_panel_shows_label_and_verification(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector(".regime-section", "el => el.innerText")
    assert "Calm" in text
    assert "2026-08-26" in text
    # Stage 5ZZP: the score is PUBLISHED now — `Score not published` was read off the
    # return type of `label_regimes`, and the engine has `predict_proba`. The invariant moves
    # to the threshold, which genuinely does not exist and must still be named.
    assert "99.8%" in text, text
    # Stage 5ZZZ-F. The words changed and the invariant did not. The panel now carries a
    # "Shift threshold" row reading "None published", and under it the RECORD's own sentence
    # explaining why there is no cut to be near. Pinning the old phrase pinned the wording;
    # what has to hold is that a reader looking for "how close is it to flipping" is told the
    # number does not exist rather than being left to notice its absence.
    low = text.lower()
    assert "shift threshold" in low and "none published" in low, text
    assert "no cutoff number to breach" in low or "no threshold" in low, text


def test_dom_the_regime_label_never_appears_without_its_age(browser_page, realtime_server):
    """'Calm' from a reading nobody refreshed in three days is not the same statement as
    'Calm' from this morning."""
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#regimeFacts", "el => el.innerText")
    assert "Calm" in text and ("ago" in text or "as of" in text)


def test_dom_the_regime_rows_are_styled_like_the_track1_rows(browser_page, realtime_server):
    """One label language on the page.

    The fact-row rules were scoped to `#track1Facts` only, so the regime panel reused the
    markup and inherited none of the styling: label `inline` at 14px instead of `block` at
    11px, and the row `block` instead of `flex column`. On the page that put the label and
    its value on one line with nothing between them -- "RegimeCalm as of 2026-08-26". Caught
    by comparing the computed styles rather than by looking at a screenshot.
    """
    _open(browser_page, realtime_server)
    # Stage 5ZZZ-F. Restated for the rebuilt regime panel. The panel was split into an
    # anchor cell (`#regimeFacts`, `.rg2-anchor`) and a metrics cell (`#regimeMetrics`,
    # `.rg2-metric`), so assertions scoped to the anchor were looking in the half that no
    # longer holds the numbers. The PROPERTY is unchanged and is what is asserted.
    # The regime panel no longer reuses the `#track1Facts` row markup - it has its own
    # `.rg2-metric` cells - so the two cannot be compared class for class any more. The
    # property that mattered survives in a different form: the SAME kicker element labels a
    # value here and in the market view, so there is still one label language on the page.
    js = "el => getComputedStyle(el).display + '|' + getComputedStyle(el).fontSize"
    a = browser_page.eval_on_selector("#regimeMetrics .rg2-metric .mv2-kicker", js)
    b = browser_page.eval_on_selector("#marketViewSetup .mv2-kicker", js)
    assert a == b, (a, b)


def test_dom_the_regime_label_and_its_value_are_on_separate_lines(browser_page,
                                                                 realtime_server):
    _open(browser_page, realtime_server)
    # Stage 5ZZZ-F. Restated for the rebuilt regime panel. The panel was split into an
    # anchor cell (`#regimeFacts`, `.rg2-anchor`) and a metrics cell (`#regimeMetrics`,
    # `.rg2-metric`), so assertions scoped to the anchor were looking in the half that no
    # longer holds the numbers. The PROPERTY is unchanged and is what is asserted.
    text = browser_page.eval_on_selector("#regimeMetrics .rg2-metric", "el => el.innerText")
    assert chr(10) in text, f"label and value share a line: {text!r}"
    assert "RegimeCalm" not in text.replace(" ", "")


def test_dom_no_raw_variable_names_are_visible(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    for sel in (".market-view-section", ".regime-section"):
        text = browser_page.eval_on_selector(sel, "el => el.innerText")
        for raw in ("gate_allow", "breadth_down_count", "splice_result", "provider_reason",
                    "live_rows_fetched", "bars_session_date"):
            assert raw not in text, f"{raw} visible in {sel}"


@pytest.mark.parametrize("width", [375, 720, 1440])
def test_dom_nothing_overflows(browser_page, realtime_server, width):
    browser_page.set_viewport_size({"width": width, "height": 900})
    _open(browser_page, realtime_server)
    over = browser_page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, f"page scrolls horizontally by {over}px at {width}px"
    for sel in (".market-view-section", ".regime-section", "#marketViewChart"):
        d = browser_page.eval_on_selector(sel, "el => el.scrollWidth - el.clientWidth")
        assert d <= 1, f"{sel} overflows by {d}px at {width}px"


def test_dom_a_failed_market_view_request_leaves_the_rest_of_the_page(browser_page,
                                                                     realtime_server):
    """Its own endpoint and its own failure: a backend that has not been restarted since this
    was added must not take the poll down with it."""
    stub_api(browser_page, {})
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector("#track1Facts", "el => el.innerText").strip()
    assert browser_page.eval_on_selector("#statusRail", "el => el.innerText").strip()


# ═══════════════════════════════════════════════════════════════════════════════════════
# Stage 5ZZM — visual polish. Chips instead of a sentence, plain English instead of field
# names, and a legend so the marker colours mean something without a tooltip.
#
# The facts underneath are unchanged and are still asserted above; these hold the PRESENTATION
# so a later edit cannot quietly put the field names back.
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_levels_copy_is_plain_english():
    """`entry levels not exposed by sleeve evidence yet` was accurate and named an internal
    concept. The fact is the same; the words are now the operator's."""
    assert mv.LEVELS_NOT_EXPOSED == "Strategy levels unavailable"
    assert "not exposed" not in mv.LEVELS_NOT_EXPOSED
    assert mv.LEVELS_DETAIL.startswith("The strategy has not published")
    for s in _payload()["sleeves"].values():
        assert s["levels_note"] == mv.LEVELS_NOT_EXPOSED
        assert s["levels_detail"] == mv.LEVELS_DETAIL


def test_the_old_phrase_is_gone_from_the_backend():
    text = (ROOT / "monitor" / "backend" / "track1_market_view.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert "entry levels not exposed by sleeve evidence yet" not in body


def test_internal_tokens_have_a_translation():
    """`splice_result` -> `Data join` and the rest. Asserted on the map itself so a missing
    entry is visible here rather than as a field name on somebody's screen."""
    code = _mv_block()
    for internal, plain in (("splice_result", "Data join"),
                            ("not_exposed_by_sleeve", "Not published"),
                            ("provider_lag", "Data delayed"),
                            ("gate_refused", "Gate refused")):
        assert internal in code and plain in code, internal


def test_an_untranslated_token_is_shown_rather_than_swallowed():
    """A phrase nobody has mapped yet should be visible so somebody maps it, not folded into
    'unknown' where it disappears."""
    code = _mv_block()
    assert "replace(/_/g, ' ')" in code


def test_dom_the_summary_is_chips_not_a_sentence(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    chips = browser_page.eval_on_selector_all(
        "#marketViewSummary .mv-chip", "els => els.map(e => e.textContent.trim())")
    assert len(chips) >= 3, chips
    # The old comma-joined sentence must not survive alongside them.
    raw = browser_page.eval_on_selector("#marketViewSummary", "el => el.innerHTML")
    assert "slots observed ·" not in raw


def test_dom_the_status_chip_uses_the_agreed_vocabulary(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    first = browser_page.eval_on_selector(
        "#marketViewSummary .mv-chip", "el => el.textContent.trim()")
    assert first in ("NO SIGNAL", "SIGNAL", "LIVE", "COMPLETE", "WAITING",
                     "DATA REFUSED", "REFUSED", "INCOMPLETE", "UNKNOWN"), first


def test_dom_a_data_refusal_wins_the_status_chip(browser_page, realtime_server):
    """If the feed did not answer, what the slots did is a smaller fact than why."""
    p = _mv_payload()
    s = p["market_view"]["sleeves"]["global_nkd"]
    s["data_status"]["ok"] = False
    s["data_status"]["provider_reason"] = "IBKR 162: Historical Market Data Service error"
    _open(browser_page, realtime_server, p)
    first = browser_page.eval_on_selector(
        "#marketViewSummary .mv-chip", "el => el.textContent.trim()")
    assert first == "DATA REFUSED", first


def test_dom_strategy_levels_unavailable_is_a_chip(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    chips = browser_page.eval_on_selector_all(
        "#marketViewSummary .mv-chip", "els => els.map(e => e.textContent.trim())")
    assert "Strategy levels unavailable".upper() in [c.upper() for c in chips], chips


def test_dom_the_old_levels_phrase_is_nowhere_on_the_panel(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector(".market-view-section", "el => el.innerText")
    assert "entry levels not exposed" not in text.lower()


def test_dom_the_levels_chip_explains_itself_on_hover(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    tip = browser_page.eval_on_selector_all(
        "#marketViewSummary .mv-chip[data-tooltip]",
        "els => els.map(e => e.getAttribute('data-tooltip'))")
    assert any("has not published entry" in (t or "") for t in tip), tip


def test_dom_the_footer_does_not_repeat_a_chip(browser_page, realtime_server):
    """The footer used to restate the levels note the chips now carry, so one sentence
    appeared twice on one panel."""
    _open(browser_page, realtime_server)
    note = browser_page.eval_on_selector("#marketViewNote", "el => el.textContent").strip()
    assert "Strategy levels unavailable" not in note
    assert note == "" or len(note.split("·")) <= 2, note


def test_dom_the_marker_legend_renders(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    words = browser_page.eval_on_selector_all(
        "#marketViewChart .mv-legend-item", "els => els.map(e => e.textContent.trim())")
    assert words == ["No signal", "Signal", "Refused", "No record", "Not yet"], words


def test_dom_the_legend_does_not_change_the_panel_height(browser_page, realtime_server):
    """It is laid over the chart's foot rather than added below it, so a sleeve with bars and
    a sleeve without one occupy the same box."""
    p = _mv_payload()
    p["market_view"]["sleeves"]["roska4_swing"] = _sleeve(
        "Swing", "MES", "14:05", "15:55", bars=[], bars_note="no bars")
    _open(browser_page, realtime_server, p)
    h0 = browser_page.eval_on_selector("#marketViewChart",
                                       "el => el.getBoundingClientRect().height")
    browser_page.click('#marketViewTabs .mv-tab:has-text("Swing")')
    h1 = browser_page.eval_on_selector("#marketViewChart",
                                       "el => el.getBoundingClientRect().height")
    assert abs(h1 - h0) <= 2.0, f"{h0} -> {h1}"


def test_dom_slot_markers_sit_on_their_own_lane(browser_page, realtime_server):
    """Attached to a baseline above the time axis rather than dropped on the plot floor,
    which is what made them read as stray ink."""
    _open(browser_page, realtime_server)
    assert browser_page.eval_on_selector_all("#marketViewChart .mv-lane", "e => e.length") == 1
    lane = browser_page.eval_on_selector("#marketViewChart .mv-lane",
                                         "el => Number(el.getAttribute('y1'))")
    ys = browser_page.eval_on_selector_all(
        "#marketViewChart .mv-mark", "els => els.map(e => Number(e.getAttribute('cy')))")
    assert ys and all(abs(y - lane) < 0.5 for y in ys), (lane, ys[:5])


def test_dom_the_window_band_is_labelled_when_it_fits(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    labels = browser_page.eval_on_selector_all(
        "#marketViewChart .mv-band-label", "els => els.map(e => e.textContent)")
    assert labels == [] or labels == ["Window"], labels


def test_dom_the_empty_state_uses_the_agreed_words(browser_page, realtime_server):
    p = _mv_payload()
    p["market_view"]["sleeves"]["global_nkd"] = _sleeve(
        "NKD", "MNKD", "01:10", "02:55", bars=[], bars_note="no persisted bars")
    _open(browser_page, realtime_server, p)
    text = browser_page.eval_on_selector("#marketViewChart", "el => el.innerText")
    assert "no bars available for this session" in text.lower(), text
    assert "2026-08-26" in text, "the latest stored session should still be offered"


def test_dom_the_stored_session_reads_as_metadata_not_a_warning(browser_page, realtime_server):
    """On an ordinary day the store simply has not been appended yet. Painting that amber
    would cry wolf every morning."""
    _open(browser_page, realtime_server)
    tone = browser_page.eval_on_selector_all(
        "#marketViewSummary .mv-chip",
        "els => els.filter(e => e.textContent.includes('Stored session'))"
        ".map(e => e.className)")
    assert tone and all("muted" in c for c in tone), tone
    assert all("bad" not in c and "warn" not in c for c in tone)


# ── regime ──────────────────────────────────────────────────────────────────────────────
def test_dom_the_regime_label_is_the_visual_anchor(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    # Stage 5ZZZ-F. Restated for the rebuilt regime panel. The panel was split into an
    # anchor cell (`#regimeFacts`, `.rg2-anchor`) and a metrics cell (`#regimeMetrics`,
    # `.rg2-metric`), so assertions scoped to the anchor were looking in the half that no
    # longer holds the numbers. The PROPERTY is unchanged and is what is asserted.
    text = browser_page.eval_on_selector(".rg2-anchor", "el => el.innerText")
    assert "Calm" in text and "as of 2026-08-26" in text, text
    assert "checked" in browser_page.eval_on_selector(".regime-section",
                                                      "el => el.innerText")
    size = browser_page.eval_on_selector(
        ".rg2-anchor b", "el => parseFloat(getComputedStyle(el).fontSize)")
    row = browser_page.eval_on_selector(
        "#regimeMetrics .rg2-metric-val", "el => parseFloat(getComputedStyle(el).fontSize)")
    assert size > row, f"the label ({size}px) must read larger than a fact value ({row}px)"


def test_dom_the_label_check_is_plain_english(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#regimeFacts", "el => el.innerText")
    assert "Label check passed" in text, text
    assert "label(s) compared through" not in text, "the log sentence is still being printed"


def test_the_check_line_reports_drift_when_there_is_some():
    code = _mv_block()
    assert "Label check found drift" in code
    assert "Label check has not run" in code


def test_dom_the_score_is_shown_and_the_threshold_is_named_absent(browser_page,
                                                                   realtime_server):
    """Stage 5ZZP. The threshold half stands, and now stands on the mechanism rather than on
    how far the page could see: Viterbi has no cut to be near."""
    _open(browser_page, realtime_server)
    # Stage 5ZZZ-F. Restated for the rebuilt regime panel. The panel was split into an
    # anchor cell (`#regimeFacts`, `.rg2-anchor`) and a metrics cell (`#regimeMetrics`,
    # `.rg2-metric`), so assertions scoped to the anchor were looking in the half that no
    # longer holds the numbers. The PROPERTY is unchanged and is what is asserted.
    text = browser_page.eval_on_selector(".regime-section", "el => el.innerText")
    # Labels are uppercased by CSS, so compared case-insensitively rather than pinned to the
    # rendered casing — the same trap Stage 5ZZM hit on the empty-state heading.
    low = text.lower()
    assert "confidence" in low and "99.8%" in text, text
    assert ("lead" in low and "runner-up" in low) and "Normal" in text, text
    assert "shift threshold" in low and "none published" in low, (
        "the absent threshold must be named")
    assert "Score not published" not in text, "the corrected claim survives"


def test_dom_the_missing_fields_explain_themselves_on_hover(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    # Stage 5ZZZ-F. Restated for the rebuilt regime panel. The panel was split into an
    # anchor cell (`#regimeFacts`, `.rg2-anchor`) and a metrics cell (`#regimeMetrics`,
    # `.rg2-metric`), so assertions scoped to the anchor were looking in the half that no
    # longer holds the numbers. The PROPERTY is unchanged and is what is asserted.
    # Stage 5ZZZ-F. These explanations are no longer behind a hover: each metric carries its
    # note as visible text under the value. That is strictly stronger than the tooltip this
    # test was written for - a reader gets the caveat without knowing to look for it - so the
    # assertion moves to the rendered text rather than to the attribute.
    notes = browser_page.eval_on_selector_all(
        "#regimeMetrics .rg2-metric-note", "els => els.map(e => e.textContent)")
    joined = " ".join(n or "" for n in notes).lower()
    assert "posterior mass" in joined or "posterior probability" in joined, notes
    assert "closest competing state" in joined, notes
    assert "viterbi" in joined or "no cutoff number" in joined, notes


def test_dom_no_distance_to_shift_is_implied(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector(".regime-section", "el => el.innerText").lower()
    for phrase in ("distance to", "close to a shift", "near threshold", "% to "):
        assert phrase not in text or "nothing to measure a distance" in text, phrase


def test_dom_the_regime_strip_has_a_legend(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    # Stage 5ZZZ-F. The legend is DERIVED from the states the payload declares, and this
    # model has three. The old fixed four-word list printed "Crisis" for a three-state model,
    # which is a state the model cannot emit - a legend entry for a thing that does not exist.
    # So the assertion becomes the relationship rather than the literal list.
    words = browser_page.eval_on_selector_all(
        "#regimeStrip .regime-legend-item", "els => els.map(e => e.textContent.trim())")
    assert words, "the strip must carry a legend"
    assert set(words) <= {"Calm", "Normal", "Stress", "Crisis"}, words
    assert "Calm" in words and "Normal" in words


def test_dom_the_strip_labels_its_two_rows(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#regimeStrip", "el => el.innerText")
    assert "trading days" in text.lower(), text
    assert "last 1" in text.lower() or "Last" in text


def test_dom_the_regime_run_is_quieter_than_the_recent_row(browser_page, realtime_server):
    """Sixty cells at full strength read as a barcode. The run is context; the last-N row is
    what gets read."""
    _open(browser_page, realtime_server)
    op = browser_page.eval_on_selector(".regime-run",
                                       "el => parseFloat(getComputedStyle(el).opacity)")
    assert op < 1.0, op
