from pathlib import Path

from monitor.backend import track1_market_view as market_view
from monitor.test_realtime_dom import (
    _market_view,
    _stub_mv,
    browser_page,
    open_realtime,
    realtime_server,
)


assert browser_page and realtime_server


ROOT = Path(__file__).resolve().parents[1]


def test_admission_lane_distinguishes_no_candidate_from_a_rejection():
    slots = []
    rows = []
    for i in range(22):
        hhmm = f"{1 + (10 + i * 5) // 60:02d}:{(10 + i * 5) % 60:02d}"
        slot_id = f"TRACK1_NKD_{hhmm.replace(':', '')}"
        slots.append({"slot_id": slot_id, "time_et": hhmm,
                      "status": "no_signal" if i < 4 else "rejected"})
        admission = ({
            "rule": "admission_cap_result",
            "passed": None,
            "source": "not_reached",
            "not_reached": True,
            "detail": "no candidate reached admission",
            "threshold": "admitted",
        } if i < 4 else {
            "rule": "admission_cap_result",
            "passed": False,
            "source": "measured",
            "detail": "0 admitted, 1 refused",
            "threshold": "admitted",
        })
        rows.append({"sleeve": "global_nkd", "slot_id": slot_id,
                     "accepted": 0, "rejected": 0 if i < 4 else 1,
                     "rule_checks": [admission]})

    lane = market_view._rule_lanes(rows, "global_nkd", slots)[0]

    assert [cell["state"] for cell in lane["cells"][:4]] == [
        market_view.CELL_NOT_APPLICABLE,
    ] * 4
    assert [cell["state"] for cell in lane["cells"][4:]] == [market_view.CELL_FAIL] * 18
    assert lane["state_display"] == "0 admitted · 18 rejected · 4 no candidate"


def test_swing_admission_lane_counts_candidates_inside_a_mixed_slot():
    slots = [
        {"slot_id": "TRACK1_SWING_1545", "time_et": "15:45", "status": "rejected"},
        {"slot_id": "TRACK1_SWING_1550", "time_et": "15:50",
         "status": "accepted_shadow"},
        {"slot_id": "TRACK1_SWING_1555", "time_et": "15:55", "status": "rejected"},
    ]
    counts = [(0, 1), (1, 1), (0, 2)]
    rows = []
    for slot, (accepted, rejected) in zip(slots, counts):
        rows.append({
            "sleeve": "roska4_swing", "slot_id": slot["slot_id"],
            "accepted": accepted, "rejected": rejected,
            "rule_checks": [{
                "rule": "admission_cap_result", "passed": accepted > 0 and rejected == 0,
                "source": "measured", "threshold": "admitted",
                "detail": f"{accepted} admitted, {rejected} refused",
            }],
        })

    lane = market_view._rule_lanes(rows, "roska4_swing", slots)[0]

    assert [cell["state"] for cell in lane["cells"]] == [
        market_view.CELL_FAIL, market_view.CELL_MIXED, market_view.CELL_FAIL,
    ]
    assert lane["cells"][1]["reason"] == "1 admitted · 1 rejected in this slot"
    assert lane["state_display"] == "1 admitted · 4 rejected"


def test_detector_grid_names_the_first_setup_early_stop():
    strategy = {"diagnostics": {
        "setup": True,
        "last_bar_ts": "2026-09-29 14:25:00+09:00",
        "bar_gate_grid": {
            "bars": ["2026-09-29 14:10:00+09:00", "2026-09-29 14:25:00+09:00"],
            "rows": [{"gate": "regime", "cells": "PP", "passed": 2, "reached": 2}],
        },
    }}

    grid = market_view._bar_grid_payload(strategy)

    assert grid["scan_stop"] == {
        "reason": "first_setup_selected",
        "bar_time": "2026-09-29 14:25:00+09:00",
        "detail": ("Detector stopped after selecting the first setup; later slots still "
                   "ran admission against that setup."),
    }


def test_frontend_renders_no_candidate_and_first_setup_stop_as_distinct_states():
    js = (ROOT / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    css = (ROOT / "global_index/dash/realtime/realtime.css").read_text(encoding="utf-8")

    assert "not_applicable:{ cls: 'na'" in js
    assert "No candidate" in js
    assert "not scanned after first setup" in js
    assert "later slots still ran admission" in js
    assert ".mv2-cell.na" in css
    assert ".mv2-cell.mixed" in css
    assert ".mv2-cell.stopped" in css


def test_nkd_tabs_show_admission_ran_and_detector_stopped(
        realtime_server, browser_page):
    market = _market_view(n=22, decided=22)
    sleeve = market["sleeves"]["global_nkd"]
    slots = sleeve["slots"]
    rows = []
    for i, slot in enumerate(slots):
        slot["status"] = "no_signal" if i < 4 else "rejected"
        admission = ({
            "rule": "admission_cap_result", "passed": None,
            "source": "not_reached", "not_reached": True,
            "detail": "no candidate reached admission", "threshold": "admitted",
        } if i < 4 else {
            "rule": "admission_cap_result", "passed": False,
            "source": "measured", "detail": "0 admitted, 1 refused",
            "threshold": "admitted",
        })
        rows.append({"sleeve": "global_nkd", "slot_id": slot["slot_id"],
                     "accepted": 0, "rejected": 0 if i < 4 else 1,
                     "rule_checks": [admission]})
    sleeve["rule_lanes"] = market_view._rule_lanes(rows, "global_nkd", slots)
    sleeve["bar_grid"] = {
        "bars": [
            "2026-09-29 14:10:00+09:00", "2026-09-29 14:15:00+09:00",
            "2026-09-29 14:20:00+09:00", "2026-09-29 14:25:00+09:00",
        ],
        "rows": [{"gate": "regime", "cells": "PPPP", "passed": 4,
                  "reached": 4, "threshold": ["Normal"]}],
        "scan_stop": {
            "reason": "first_setup_selected",
            "bar_time": "2026-09-29 14:25:00+09:00",
            "detail": ("Detector stopped after selecting the first setup; later slots still "
                       "ran admission against that setup."),
        },
    }

    _stub_mv(browser_page, market)
    open_realtime(browser_page, realtime_server)

    admission_row = browser_page.locator(".mv2-lane", has_text="admission cap result").first
    assert "0 admitted · 18 rejected · 4 no candidate" in admission_row.inner_text()
    assert admission_row.locator(".mv2-cell.na").count() == 4
    assert admission_row.locator(".mv2-cell.bad").count() == 18

    browser_page.get_by_role("tab", name="Detector rules").click()
    browser_page.wait_for_selector(".mv2-cell.stopped")
    assert browser_page.locator(".mv2-cell.stopped").count() == 18
    assert "stopped after first setup 14:25 JST" in browser_page.locator(
        ".mv2-bargrid .mv2-head-right").inner_text()
