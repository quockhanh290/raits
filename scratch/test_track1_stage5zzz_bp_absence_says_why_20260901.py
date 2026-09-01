"""Stage 5ZZZ-BP. Four places the dashboard showed an absence and gave no reason.

All four are one defect family, and the family is the expensive one: a reader cannot tell
"this has not happened yet" from "this is broken", so either every blank gets investigated or
none of them do.

  1. The Daily ATR row read "Unavailable" on every slot of a Calm session. Measured on MNKD,
     2026-09-01, slot TRACK1_NKD_0255: the card carried `ATR (14 x 5-min bars) 54.29`,
     `Daily ATR Unavailable` and `Regime Calm` with a failed verdict. Nothing was unavailable
     -- the detector answered the regime gate and returned, and never reached the daily ATR.
  2. The slot chart printed no session date while the candle chart above it prints
     "Stored session <day>" whenever its bars are older than the panel's day. On 2026-09-01
     the two sat side by side showing the 28th and the 1st with nothing saying so.
  3. The surge-threshold legend entry vanished when no slot reached the surge gate.
  4. Nothing said that the regime gate had refused every slot, so the four series on the chart
     were readings no rule had consumed.

Tests 2-4 are drawn by the page; what is pinned here is the CONTRACT the page needs -- the
verdict and the session date arriving in the payload. A sentence the renderer cannot build
because the field is absent is the failure mode those three had in the first place.
"""
from __future__ import annotations

import pytest

from global_index import track1_strategy_diagnostics as SD


# -- 1. the Daily ATR row says which gate returned first ----------------------------------
def _obs(*gates):
    o = SD.NormalR4Observer()
    for g in gates:
        o({"kind": "gate", **g})
    return o


def test_a_gate_that_returned_first_is_named_not_called_unavailable():
    """The measured card: regime refused, daily ATR never reported, row read "Unavailable"."""
    o = _obs({"gate": "session_bars", "passed": True},
             {"gate": "regime", "value": "Calm", "passed": False})
    missing, detail = o.daily_atr_absence()
    assert missing == SD.MISSING_NOT_REACHED, missing
    assert "regime" in detail, detail
    assert "returned before reporting" in detail, detail


def test_the_row_renders_the_reason_as_its_value():
    """A detail nobody opens is not a reason. The word has to occupy the value's own field."""
    o = _obs({"gate": "session_bars", "passed": True},
             {"gate": "regime", "value": "Calm", "passed": False})
    rows = {r["label"]: r for r in o.rows(ema_period=10)}
    assert rows["Daily ATR"]["display_value"] == "Not reached", rows["Daily ATR"]
    assert rows["Daily ATR"]["display_value"] != "Unavailable"


def test_a_gate_that_reported_a_number_still_prints_the_number():
    """The fix must not turn a working row into a sentence."""
    o = _obs({"gate": "session_bars", "passed": True},
             {"gate": "regime", "value": "Normal", "passed": True},
             {"gate": "daily_atr", "value": 1548.93, "passed": True})
    missing, detail = o.daily_atr_absence()
    assert missing == "", missing
    assert "not read on this slot" not in detail, detail
    rows = {r["label"]: r for r in o.rows(ema_period=10)}
    assert rows["Daily ATR"]["display_value"] == "1,548.93", rows["Daily ATR"]


def test_a_gate_that_was_reached_and_came_back_empty_is_not_called_not_reached():
    """The distinction the new word exists to make. Reached-and-empty is the one worth
    investigating; not-reached is the route working. Collapsing them loses the alarm."""
    o = _obs({"gate": "session_bars", "passed": True},
             {"gate": "regime", "value": "Calm", "passed": False},
             {"gate": "daily_atr", "value": None, "passed": False})
    missing, _ = o.daily_atr_absence()
    assert missing == SD.MISSING_DATA, missing


def test_a_slot_with_no_refusal_at_all_does_not_invent_a_gate_name():
    """No gate failed, so there is nothing to name. Naming one would be a guess printed as a
    fact, which is the shape of defect this whole module was written against."""
    o = _obs({"gate": "session_bars", "passed": True})
    missing, detail = o.daily_atr_absence()
    assert missing == SD.MISSING_DATA, missing
    assert "returned before reporting" not in detail, detail


def test_the_reason_is_derived_from_the_gate_list_not_from_a_written_order():
    """Whichever gate actually refused is the one named -- the module does not own the order
    and must not hard-code it. A reordered detector would otherwise print the wrong cause."""
    o = _obs({"gate": "session_bars", "value": 3, "passed": False})
    missing, detail = o.daily_atr_absence()
    assert missing == SD.MISSING_NOT_REACHED, missing
    assert "session_bars" in detail and "regime" not in detail, detail


# -- 2. the regime verdict travels with the session ---------------------------------------
def _write(root, day, sleeve, slot, regime, passed):
    SD.record({
        "schema": 1, "sleeve": sleeve, "slot_id": slot, "slot_time": slot[-4:],
        "session_date": day, "diagnostics_source": SD.RECORDED,
        "bars_evaluated": 3, "last_bar_ts": None, "last_bar_complete": None,
        "rows": [{"label": "Close used", "value": 66175.0, "passed": None},
                 {"label": "Regime", "value": regime, "passed": passed}],
    }, root=root, day=day)


@pytest.fixture()
def refused_session(tmp_path):
    day = "2026-09-01"
    for i, slot in enumerate(("TRACK1_NKD_0110", "TRACK1_NKD_0255")):
        _write(tmp_path, day, "global_nkd", slot, "Calm", False)
    return tmp_path, day


def test_the_session_carries_the_verdict_not_only_the_label(refused_session):
    """`values` is {label: value} and drops `passed`. A chart built from it can print "Calm"
    and cannot say Calm is the answer that stopped every slot."""
    root, day = refused_session
    series = SD.recorded_series(root, day, "global_nkd")
    assert len(series) == 2, series
    assert [p["regime"] for p in series] == ["Calm", "Calm"]
    assert [p["regime_passed"] for p in series] == [False, False]


def test_a_slot_that_recorded_no_verdict_reports_none_not_false(refused_session):
    """Three states, as everywhere else in this module: passed / failed / never answered.
    Folding "not answered" into "failed" would let the page print a refusal nobody made."""
    root, day = refused_session
    SD.record({
        "schema": 1, "sleeve": "global_nkd", "slot_id": "TRACK1_NKD_0300",
        "slot_time": "0300", "session_date": day, "diagnostics_source": SD.RECORDED,
        "rows": [{"label": "Close used", "value": 1.0, "passed": None}]}, root=root, day=day)
    series = SD.recorded_series(root, day, "global_nkd")
    last = [p for p in series if p["slot_id"] == "TRACK1_NKD_0300"][0]
    assert last["regime_passed"] is None, last
    assert last["regime"] is None, last


def test_the_verdict_survives_the_trip_to_the_page(refused_session):
    """The panel builds its own narrow point per slot. A field that stops here is a field the
    chart cannot draw a sentence from."""
    from monitor.backend import track1_market_view as MV
    root, day = refused_session
    pts = MV._slot_series(root, day, "global_nkd")
    assert len(pts) == 2, pts
    assert all(p["regime_passed"] is False for p in pts), pts
    assert all(p["regime"] == "Calm" for p in pts), pts


def test_the_chart_is_told_which_session_it_is_drawing():
    """Two charts, two days, one of them labelled -- the reason the 28th and the 1st sat side
    by side unremarked. The date has to be set wherever the series is, from the SAME variable
    that selected the data; a second source could name a day the points did not come from."""
    import ast
    import inspect
    from monitor.backend import track1_market_view as MV

    def _publishes_series(node):
        """`<something>["slot_series"] = _slot_series(root, day, sleeve)` and nothing else."""
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            return None
        t = node.targets[0]
        if not (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                and t.slice.value == "slot_series"):
            return None
        if not (isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", "") == "_slot_series"):
            return None
        return ast.unparse(node.value.args[1])          # the day the points came from

    tree = ast.parse(inspect.getsource(MV))
    found = 0
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for a, b in zip(body, body[1:]):
            day = _publishes_series(a)
            if day is None:
                continue
            found += 1
            src_b = ast.unparse(b)
            assert "slot_series_session" in src_b, (
                "a slot series is published without naming its session: " + ast.unparse(a))
            assert src_b.endswith("= " + day), (
                "the session named is not the day the points were selected with: "
                + src_b + " vs " + day)
    assert found == 2, ("expected both publishing sites to be checked, saw %d" % found)


def test_the_block_the_live_slot_writes_carries_the_reason():
    """The call site, not the helper. Reproduces the gate pattern the 02:55 slot actually
    recorded on 2026-09-01 -- `["session_bars", "regime"]` and no `daily_atr` entry -- and
    checks the block that would be written today. Testing `rows()` alone leaves the writer
    free to build its rows some other way, which is the gap that lets a mechanism be correct,
    documented, and wired to nothing.
    """
    o = _obs({"gate": "session_bars", "value": 22, "passed": True},
             {"gate": "regime", "value": "Calm", "threshold": "Normal", "passed": False})
    blk = SD.normal_r4_block(sleeve="global_nkd", slot_id="TRACK1_NKD_0255", ema_period=10,
                             observer=o, setup=None)
    row = [r for r in blk["rows"] if r["label"] == "Daily ATR"][0]
    assert row["display_value"] == "Not reached", row
    assert "regime" in (row["detail"] or ""), row
    assert [g.get("gate") for g in (blk.get("gates") or [])] == ["session_bars", "regime"], blk


# -- 3. a block already on disk gets the same sentence, without being rewritten ------------
def _stored_0255():
    """A block as the OLD writer left it for TRACK1_NKD_0255 on 2026-09-01.

    Built by the real writer -- so every key the panel indexes is present and correctly
    shaped -- and then the one row is put back to the string the old code actually printed,
    which the store still holds. Hand-rolling the dict instead hid a missing `threshold` key
    and then a missing `summary`: a fixture trimmed to what the code under test happens to
    read stops standing in for the store it is impersonating.
    """
    o = _obs({"gate": "session_bars", "value": 180, "passed": True},
             {"gate": "regime", "value": "Calm", "threshold": ["Normal"], "passed": False})
    blk = SD.normal_r4_block(sleeve="global_nkd", slot_id="TRACK1_NKD_0255", ema_period=10,
                             observer=o, setup=None)
    blk["rows"] = [dict(r, missing=None, display_value="Unavailable")
                   if r["label"] == "Daily ATR" else r for r in blk["rows"]]
    return blk


def test_a_block_written_before_the_fix_still_gets_the_reason():
    """Measured: the 02:55 block kept saying "Unavailable" for the rest of the day, because a
    block carries the display string its writer chose. Everything needed to say better was
    already on disk -- no value on the row, a refusal in the gates, no daily_atr entry."""
    out = SD.explain_recorded_absences(_stored_0255())
    row = [r for r in out["rows"] if r["label"] == "Daily ATR"][0]
    assert row["display_value"] == "Not reached", row
    assert "regime" in row["detail"], row
    assert row["missing"] == SD.MISSING_NOT_REACHED, row


def test_the_stored_block_itself_is_never_touched():
    """Reading a record must not edit it. The store is the trail an audit exists to protect,
    and a display fix that reaches back into it destroys what the slot actually said."""
    src = _stored_0255()
    before = [dict(r) for r in src["rows"]]
    SD.explain_recorded_absences(src)
    assert src["rows"] == before, src["rows"]
    kept = [r for r in src["rows"] if r["label"] == "Daily ATR"][0]
    assert kept["display_value"] == "Unavailable", kept


def test_a_blank_with_no_reason_keeps_its_original_wording():
    """Conservative on purpose. Replacing one blank with a differently worded blank tells the
    reader nothing and loses what the writer chose to say."""
    blk = _stored_0255()
    blk["gates"] = [{"gate": "session_bars", "passed": True}]
    out = SD.explain_recorded_absences(blk)
    row = [r for r in out["rows"] if r["label"] == "Daily ATR"][0]
    assert row["display_value"] == "Unavailable", row


def test_a_row_that_carries_a_number_is_left_alone():
    """The re-render must never overwrite a reading."""
    blk = _stored_0255()
    blk["gates"].append({"gate": "daily_atr", "value": 1548.93, "passed": True})
    blk["rows"][1] = {"label": "Daily ATR", "value": 1548.93, "display_value": "1,548.93",
                      "missing": None, "detail": ""}
    out = SD.explain_recorded_absences(blk)
    row = [r for r in out["rows"] if r["label"] == "Daily ATR"][0]
    assert row["display_value"] == "1,548.93", row


def test_the_panel_applies_it_to_what_it_read():
    """The call site. A derivation nothing calls is the failure mode this repo has hit before:
    correct code, written docs, grep-verified, and wired to no entry point."""
    from monitor.backend import track1_market_view as MV
    blk = dict(_stored_0255(), nearest_failed_condition=None, slot_time="0255",
               bars_evaluated=22, last_bar_ts=None, last_bar_complete=None)
    out = MV._apply_r4_block({}, blk)
    row = [r for r in out["diagnostics"]["rows"] if r["label"] == "Daily ATR"][0]
    assert row["display_value"] == "Not reached", row
    rule = [r for r in out["rules"] if r["label"] == "Daily ATR"][0]
    assert rule["display_value"] == "Not reached", rule
