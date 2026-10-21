from __future__ import annotations

import copy
import datetime as dt
import json
import re
import string
import subprocess
from pathlib import Path

from monitor.backend.job_journal_reader import _parse, read_job_journal
from monitor.backend.track1_market_view import _jobs_for_day, _next_protection_job, _slots_for
from monitor.test_realtime_dom import (
    BASE_PAYLOADS,
    _market_view,
    _stub_mv,
    browser_page,
    open_realtime,
    realtime_server,
    stub_api,
)

assert browser_page and realtime_server

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "global_index" / "dash" / "realtime" / "realtime.js"


def _synthetic_journal(tmp_path: Path) -> dict:
    log = tmp_path / "scheduler_0925.log"
    log.write_text("\n".join([
        "2026-09-25 05:10:00 INFO run_scheduler — [TRACK1_NKD_0110] python.exe -m global_index.run_live_day_track1",
        "2026-09-25 05:10:02 ERROR run_scheduler — [TRACK1_NKD_0110] exited with code 2",
        "2026-09-25 05:10:02 ERROR run_scheduler — [TRACK1_NKD_0110] stdout: REFUSED - order sending was requested and is not available:",
        "2026-09-25 05:10:02 ERROR run_scheduler — [TRACK1_NKD_0110] stdout: Nothing was run. Re-run without --allow-orders for a shadow pass.",
        "2026-09-25 06:00:00 INFO run_scheduler — [TRACK1_NKD_0200] python.exe -m global_index.run_live_day_track1",
        "2026-09-25 06:00:04 ERROR run_scheduler — [TRACK1_NKD_0200] exited with code 1",
        "2026-09-25 06:00:04 ERROR run_scheduler — [TRACK1_NKD_0200] stderr: ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection",
        "2026-09-25 06:05:00 INFO run_scheduler — [TRACK1_NKD_0205] python.exe -m global_index.run_live_day_track1",
        "2026-09-25 06:05:02 INFO run_scheduler — [TRACK1_NKD_0205] completed OK",
        "2026-09-25 06:05:02 INFO run_scheduler — [TRACK1_NKD_0205] stdout: ordinary clean output",
    ]), encoding="utf-8")
    return _parse([log], "2026-09-25", [], tmp_path)


def test_g1_g21_three_slot_states_and_clean_output_guard(tmp_path):
    journal = _synthetic_journal(tmp_path)
    jobs = {job["job_id"]: job for job in journal["jobs"]}
    assert "Order sending was refused" in jobs["TRACK1_NKD_0110"]["impact"]
    assert "WinError 1225" in jobs["TRACK1_NKD_0200"]["impact"]
    assert jobs["TRACK1_NKD_0205"]["diagnostics"] == []

    indexed = _jobs_for_day(journal, "2026-09-25")
    slots = {slot["slot_id"]: slot for slot in
             _slots_for("global_nkd", [], "02:05", indexed, set())}
    assert slots["TRACK1_NKD_0110"]["status"] == "fired_no_record"
    assert "Order sending was refused" in slots["TRACK1_NKD_0110"]["reason"]
    assert slots["TRACK1_NKD_0200"]["status"] == "fired_no_record"
    assert "WinError 1225" in slots["TRACK1_NKD_0200"]["reason"]
    assert slots["TRACK1_NKD_0120"] == {
        "slot_id": "TRACK1_NKD_0120", "time_et": "01:20", "status": "missed",
        "reason": "the scheduler did not launch this slot", "candidate_count": 0,
    }


def test_g1_job_index_rejects_wrong_payload_and_execution_dates(tmp_path):
    journal = _synthetic_journal(tmp_path)
    assert _jobs_for_day({**journal, "day": "2026-09-24"}, "2026-09-25") == {}
    prior = copy.deepcopy(journal)
    prior["jobs"][0]["started_at"] = "2026-09-24T05:10:00Z"
    indexed = _jobs_for_day(prior, "2026-09-25")
    assert "TRACK1_NKD_0110" not in indexed


def test_g22_existing_non_child_diagnostic_counts_do_not_move():
    journal = read_job_journal("2026-09-25", ROOT)
    counts = {job["job_id"]: len(job["diagnostics"]) for job in journal["jobs"]}
    assert counts["ANCHOR_CHECK_0055"] == 1
    assert counts["TRACK1_STOP_REPAIR_1020"] == 4


def test_g4_fill_join_uses_full_dated_trade_id():
    base = {
        "sleeve": "global_nkd", "slot_id": "TRACK1_NKD_0125", "slot_time": "01:25",
        "status": "SIGNAL_ACCEPTED_SHADOW", "reason": "shadow_only", "raw_candidates": 1,
        "candidates": [{"instrument": "MNKD", "trade_id": "global_nkd::MNKD::2026-09-25"}],
    }
    filled = {"global_nkd::MNKD::2026-09-25"}
    matched = {slot["slot_id"]: slot for slot in
               _slots_for("global_nkd", [base], "02:55", {}, filled)}
    assert matched["TRACK1_NKD_0125"]["reason"] == "shadow_only"
    assert matched["TRACK1_NKD_0125"]["execution"] == {
        "state": "filled", "trade_id": "global_nkd::MNKD::2026-09-25",
        "source": "paper_send",
    }

    other_day = copy.deepcopy(base)
    other_day["candidates"][0]["trade_id"] = "global_nkd::MNKD::2026-09-24"
    unmatched = {slot["slot_id"]: slot for slot in
               _slots_for("global_nkd", [other_day], "02:55", {}, filled)}
    assert unmatched["TRACK1_NKD_0125"] == {
        "slot_id": "TRACK1_NKD_0125", "time_et": "01:25",
        "status": "accepted_shadow", "raw_status": "SIGNAL_ACCEPTED_SHADOW",
        "reason": "shadow_only", "candidate_count": 1,
    }


def test_slot_strip_maps_the_complete_producer_vocabulary_without_guessing():
    from global_index import track1_signals as sig
    from monitor.backend import track1_market_view as mv

    expected = {
        sig.SLOT_REFUSED: "refused",
        sig.NO_SIGNAL: "no_signal",
        sig.RAW_SIGNAL_FOUND: "candidate",
        sig.SIGNAL_REJECTED: "rejected",
        sig.SIGNAL_ACCEPTED_SHADOW: "accepted_shadow",
    }
    assert set(mv._STATUS_MAP) == set(sig.STATUSES)
    assert mv._STATUS_MAP == expected
    assert len(set(expected.values())) == len(expected), "two producer outcomes look identical"


def test_live_session_slot_outcomes_are_recognised_and_stress_is_unchanged():
    from collections import Counter
    from monitor.backend import track1_market_view as mv

    rows = mv._signal_rows(ROOT, "2026-09-25")
    before_unknown = {"global_nkd": 17, "roska4_swing": 11, "roska4_stress": 0}
    expected_after = {
        "global_nkd": Counter({"rejected": 10, "accepted_shadow": 7, "missed": 5}),
        "roska4_swing": Counter({"no_signal": 12, "rejected": 10,
                                  "accepted_shadow": 1}),
        "roska4_stress": Counter({"no_signal": 24}),
    }
    for sleeve, expected in expected_after.items():
        slots = mv._slots_for(sleeve, rows, "23:59", {}, set())
        assert len([s for s in slots if s["status"] == "unknown"]) == 0, (
            sleeve, before_unknown[sleeve], slots)
        assert Counter(s["status"] for s in slots) == expected


def test_candidate_count_alignment_and_raw_unknown_survive_the_reader():
    from monitor.backend import track1_market_view as mv

    rows = mv._signal_rows(ROOT, "2026-09-25")
    slots = mv._slots_for("roska4_swing", rows, "23:59", {}, set())
    by_id = {s["slot_id"]: s for s in slots}
    assert by_id["TRACK1_SWING_1510"]["status"] == "rejected"
    assert by_id["TRACK1_SWING_1510"]["candidate_count"] == 2
    assert by_id["TRACK1_SWING_1405"]["status"] == "no_signal"
    assert by_id["TRACK1_SWING_1405"]["candidate_count"] == 0

    idx = next(i for i, s in enumerate(slots) if s["slot_id"] == "TRACK1_SWING_1510")
    lanes = mv._rule_lanes(rows, "roska4_swing", slots)
    assert lanes and all(lane["cells"][idx]["slot_id"] == "TRACK1_SWING_1510"
                         for lane in lanes)

    unknown = {"sleeve": "global_nkd", "slot_id": "TRACK1_NKD_0110",
               "slot_time": "01:10", "status": "FUTURE_PRODUCER_WORD",
               "reason": "fixture", "raw_candidates": 3}
    mark = mv._slots_for("global_nkd", [unknown], "02:55", {}, set())[0]
    assert mark["status"] == "unknown"
    assert mark["raw_status"] == "FUTURE_PRODUCER_WORD"
    assert mark["candidate_count"] == 3


def test_slot_marks_name_outcome_candidate_count_and_unknown_raw_word(
        browser_page, realtime_server):
    market = _market_view()
    slots = market["sleeves"]["global_nkd"]["slots"]
    slots[0].update({"status": "accepted_shadow", "raw_status": "SIGNAL_ACCEPTED_SHADOW",
                     "reason": "shadow_only", "candidate_count": 1})
    slots[1].update({"status": "rejected", "raw_status": "SIGNAL_REJECTED",
                     "reason": "suppress_same_sleeve", "candidate_count": 2})
    slots[2].update({"status": "no_signal", "raw_status": "NO_SIGNAL",
                     "reason": "decided", "candidate_count": 0})
    slots[3].update({"status": "unknown", "raw_status": "FUTURE_PRODUCER_WORD",
                     "reason": "fixture", "candidate_count": 3})
    _stub_mv(browser_page, market)
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".mv2-slot")
    titles = browser_page.eval_on_selector_all(
        ".mv2-slot", "els => els.slice(0, 4).map(e => e.getAttribute('title'))")
    assert "admitted in shadow" in titles[0].lower() and "1 candidate" in titles[0]
    assert "rejected" in titles[1].lower() and "2 candidates" in titles[1]
    assert "no signal" in titles[2].lower() and "0 candidates" in titles[2]
    assert "unrecognised status: FUTURE_PRODUCER_WORD" in titles[3]
    legend = browser_page.eval_on_selector(".mv2-legend-slots", "el => el.innerText")
    assert "admitted in shadow" in legend.lower()
    assert "rejected" in legend.lower()
    assert "no signal" in legend.lower()
    assert "unknown" in legend.lower()


def test_stress_nonverdict_lanes_name_the_recorded_setup_failures():
    from monitor.backend import track1_market_view as mv

    rows = mv._signal_rows(ROOT, "2026-09-25")
    slots = mv._slots_for("roska4_stress", rows, "23:59", {}, set())
    lanes = {lane["rule"]: lane for lane in mv._rule_lanes(rows, "roska4_stress", slots)}
    setup = ("mnq_only_short_setup", "pre_high_stop_reference",
             "stop_within_max_pct", "rr_target_computed")
    admission = ("same_symbol_suppression", "family_cap", "cluster_cap")
    cause = "setup stopped at gapdown count and avg gap"
    for name in setup:
        assert lanes[name]["uniform_nonverdict"] == "not_published"
        assert lanes[name]["state_display"] == f"not computed - {cause}"
    for name in admission:
        assert lanes[name]["uniform_nonverdict"] == "not_reached"
        assert lanes[name]["state_display"] == f"not reached - {cause}"

    # The six decided lanes are the control and retain their exact verdict counts.
    assert [(lanes[n]["passed"], lanes[n]["failed"]) for n in (
        "gate_allow", "freshness_allow", "breadth_down_count", "gapdown_count",
        "wide_count", "avg_gap")] == [(24, 0), (24, 0), (24, 0), (0, 24),
                                       (24, 0), (0, 24)]


def test_a_real_gate_failure_is_named_as_the_blocker_not_erased():
    from monitor.backend import track1_market_view as mv

    slots, rows = [], []
    setup = ("mnq_only_short_setup", "pre_high_stop_reference",
             "stop_within_max_pct", "rr_target_computed")
    admission = ("same_symbol_suppression", "family_cap", "cluster_cap")
    for i, hhmm in enumerate(("10:35", "10:40")):
        slot_id = f"TRACK1_STRESS_{hhmm.replace(':', '')}"
        slots.append({"slot_id": slot_id, "time_et": hhmm, "status": "refused"})
        checks = [{"rule": "gate_allow", "passed": False, "source": "measured"}]
        checks += [{"rule": name, "passed": None, "source": "not_exposed_by_sleeve"}
                   for name in setup]
        checks += [{"rule": name, "passed": None, "source": "not_reached",
                    "not_reached": True} for name in admission]
        rows.append({"sleeve": "roska4_stress", "slot_id": slot_id,
                     "rule_checks": checks})

    lanes = {lane["rule"]: lane for lane in mv._rule_lanes(rows, "roska4_stress", slots)}
    for name in setup:
        assert lanes[name]["state_display"] == (
            "not computed - gate stopped the slot: gate allow failed")
    for name in admission:
        assert lanes[name]["state_display"] == (
            "not reached - gate stopped the slot: gate allow failed")


def test_nonverdict_without_a_recorded_blocker_does_not_blame_a_passed_gate():
    from monitor.backend import track1_market_view as mv

    slots = [{"slot_id": "TRACK1_STRESS_1035", "time_et": "10:35",
              "status": "no_signal"}]
    rows = [{"sleeve": "roska4_stress", "slot_id": "TRACK1_STRESS_1035",
             "rule_checks": [
                 {"rule": "gate_allow", "passed": True, "source": "measured"},
                 {"rule": "family_cap", "passed": None, "source": "not_reached",
                  "not_reached": True},
             ]}]
    lane = {x["rule"]: x for x in mv._rule_lanes(rows, "roska4_stress", slots)}["family_cap"]
    assert lane["state_display"] == (
        "not reached - stopping rule not identified in recorded payload")
    assert "gate stopped" not in lane["state_display"]


def test_uniform_nonverdict_lanes_are_legible_without_hover_and_fail_stays_primary(
        browser_page, realtime_server):
    from monitor.backend import track1_market_view as mv_reader

    rows = mv_reader._signal_rows(ROOT, "2026-09-25")
    slots = mv_reader._slots_for("roska4_stress", rows, "23:59", {}, set())
    lanes = mv_reader._rule_lanes(rows, "roska4_stress", slots)
    market = _market_view(n=24, decided=24)
    sleeve = market["sleeves"]["global_nkd"]
    sleeve.update({"label": "Stress", "slots": slots, "rule_lanes": lanes})
    _stub_mv(browser_page, market)
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".mv2-lane.absence-not_published")

    visible = browser_page.eval_on_selector_all(
        ".mv2-lane-value", "els => els.map(e => e.innerText.trim())")
    assert visible.count("not computed - setup stopped at gapdown count and avg gap") == 4
    assert visible.count("not reached - setup stopped at gapdown count and avg gap") == 3
    assert browser_page.locator(".mv2-lane.absence-not_published").count() == 4
    assert browser_page.locator(".mv2-lane.absence-not_reached").count() == 3

    styles = browser_page.evaluate("""() => {
      const rows = [...document.querySelectorAll('.mv2-lane')];
      const byName = name => rows.find(r =>
        r.querySelector('.mv2-lane-label')?.textContent.trim() === name);
      const take = name => {
        const row = byName(name), cell = row.querySelector('.mv2-cell');
        return { rowBg: getComputedStyle(row).backgroundColor,
                 cellBg: getComputedStyle(cell).backgroundColor,
                 border: getComputedStyle(cell).borderStyle };
      };
      return { fail: take('gapdown count'), unpublished: take('mnq only short setup'),
               unreached: take('family cap') };
    }""")
    assert styles["fail"]["rowBg"] != styles["unpublished"]["rowBg"]
    assert styles["fail"]["cellBg"] != styles["unpublished"]["cellBg"]
    assert styles["unpublished"]["cellBg"] != styles["unreached"]["cellBg"]
    assert styles["unreached"]["border"] == "dashed"

    idx = 8
    assert all(lane["cells"][idx]["slot_id"] == slots[idx]["slot_id"] for lane in lanes)


def _issue(scope, key):
    row = {
        "key": key, "status": "incident", "component": "scheduler", "title": key,
        "problem": "measured problem", "impact": "measured impact", "action": "review",
        "evidence": "evidence", "resolution_evidence": "resolution", "occurrences": 1,
        "first_seen": "2026-09-25T12:00:00Z", "last_seen": "2026-09-25T12:00:00Z",
        "counts_as_active": True,
    }
    if scope is not None:
        row["route_scope"] = scope
    return row


def test_g3_absent_and_unmapped_issue_scopes_render_visible_unknown(browser_page, realtime_server):
    payload = {"source": "test", "issues": [_issue(None, "absent"),
               _issue("new_route", "unmapped")], "active_count": 2, "error": None}
    stub_api(browser_page, {"/api/v1/open-issues": payload})
    open_realtime(browser_page, realtime_server)
    labels = browser_page.eval_on_selector_all(
        ".issue-list-row .issue-scope", "els => els.map(e => e.textContent.trim())")
    assert labels == ["UNKNOWN SCOPE", "UNKNOWN SCOPE"]


def test_item4_dom_shows_decision_and_fill_as_separate_facts(browser_page, realtime_server):
    market = _market_view(signal_at=0)
    slot = market["sleeves"]["global_nkd"]["slots"][0]
    slot.update({"status": "unknown", "reason": "shadow_only",
                 "execution": {"state": "filled", "trade_id": "global_nkd::MNKD::2026-08-27"}})
    _stub_mv(browser_page, market)
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".mv2-slot")
    title = browser_page.get_attribute(".mv2-slot", "title")
    assert "shadow only" in title.lower()
    assert "order filled" in title.lower()


def _runner_without_snapshot_positions(day="2026-09-25"):
    payload = copy.deepcopy(BASE_PAYLOADS["/api/v1/runner-state"])
    payload["payload"]["snapshots"][0]["date"] = day
    payload["payload"]["snapshots"][0].pop("open_positions", None)
    return payload


def _persisted(*positions):
    payload = copy.deepcopy(BASE_PAYLOADS["/api/v1/runner-positions"])
    payload["payload"]["positions"] = list(positions)
    return payload


def _broker(*symbols):
    payload = copy.deepcopy(BASE_PAYLOADS["/api/v1/broker"])
    payload["payload"]["positions"] = [
        {"inst": symbol, "position": 1, "market_price": 101, "avg_cost": 100,
         "market_value": 101, "realized_pnl": 0, "unrealized_pnl": 1, "sec_type": "FUT"}
        for symbol in symbols
    ]
    payload["payload"]["orders"] = []
    payload["payload"]["contract_specs"] = {}
    return payload


def _book_row(instrument="MNKD", **overrides):
    row = {"instrument": instrument, "sleeve": "global_nkd", "direction": "LONG",
           "qty": 1, "entry_time": "2026-09-23 01:25:00-04:00", "entry_price": 100,
           "risk_dollars": 469.4643, "stop_price": 90}
    row.update(overrides)
    return row


def test_g81_g82_g94_book_fields_and_mnk_contract_render(browser_page, realtime_server):
    stub_api(browser_page, {
        "/api/v1/runner-state": _runner_without_snapshot_positions(),
        "/api/v1/runner-positions": _persisted(_book_row()),
        "/api/v1/broker": _broker("MNKZ6"),
    })
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".position-card")
    card = browser_page.locator(".position-card").first
    assert card.locator(".position-cluster").inner_text() == "global_nkd"
    assert "2026-09-23" in card.locator(".fact-opened").inner_text()
    assert card.locator(".fact-held b").inner_text() == "2d"
    assert card.locator(".fact-risk b").inner_text() == "$469"
    assert "runner unmatched" not in card.inner_text().lower()


def test_g83_existing_snapshot_risk_and_age_are_unchanged(browser_page, realtime_server):
    runner = copy.deepcopy(BASE_PAYLOADS["/api/v1/runner-state"])
    runner["payload"]["snapshots"][0]["open_positions"] = [{
        "inst": "M2K", "cluster": "roska4_swing", "direction": "LONG", "contracts": 1,
        "entry_day": "2026-08-10", "entry_price": 100, "days_held": 4,
        "risk_sized": 602.14, "stop_price": 90,
    }]
    stub_api(browser_page, {"/api/v1/runner-state": runner, "/api/v1/broker": _broker("M2KZ6")})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".position-card")
    assert browser_page.locator(".fact-held b").inner_text() == "4d"
    assert browser_page.locator(".fact-risk b").inner_text() == "$602"


def test_g84_missing_age_and_risk_are_not_reported_as_zero(browser_page, realtime_server):
    stub_api(browser_page, {
        "/api/v1/runner-state": _runner_without_snapshot_positions(),
        "/api/v1/runner-positions": _persisted(_book_row(entry_time="", risk_dollars=None)),
        "/api/v1/broker": _broker("MNKZ6"),
    })
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".position-card")
    assert browser_page.locator(".fact-held b").inner_text() == "not recorded"
    assert browser_page.locator(".fact-risk b").inner_text() == "not recorded"


def _root_table(symbols):
    code = JS.read_text(encoding="utf-8")
    roots = re.search(r"const roots = \[[^;]+;", code).group(0)
    root_of = re.search(r"const rootOf = symbol => \{.*?\n  \};", code, re.S).group(0)
    script = roots + "\n" + root_of + "\nconsole.log(JSON.stringify(Object.fromEntries(" \
        + json.dumps(symbols) + ".map(s => [s, rootOf(s)]))));"
    result = subprocess.run(["node", "--input-type=module", "-e", script], check=True,
                            capture_output=True, text=True)
    return json.loads(result.stdout)


def test_g91_every_mnk_month_letter_resolves_to_mnkd():
    symbols = [f"MNK{letter}6" for letter in string.ascii_uppercase]
    assert _root_table(symbols) == {symbol: "MNKD" for symbol in symbols}


def test_g92_other_live_symbol_roots_are_unchanged():
    expected = {"M2KZ6": "M2K", "MYMZ6": "MYM", "MESZ6": "MES", "MNQZ6": "MNQ",
                "M2K": "M2K", "MYM": "MYM", "MNKD": "MNKD", "NKDZ6": "MNKD"}
    assert _root_table(list(expected)) == expected


def test_g93_unknown_symbol_keeps_existing_fallback_and_stays_unmatched(
        browser_page, realtime_server):
    assert _root_table(["XYZQ6"]) == {"XYZQ6": "XYZQ"}
    stub_api(browser_page, {
        "/api/v1/runner-state": _runner_without_snapshot_positions(),
        "/api/v1/runner-positions": _persisted(_book_row()),
        "/api/v1/broker": _broker("XYZQ6"),
    })
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".position-card")
    assert "runner unmatched" in browser_page.locator(".position-card").inner_text().lower()


SAFETY_JOBS = ["track1_maxhold_exit"] + [
    f"track1_stop_repair_{hour:02d}20" for hour in (0, 4, 6, 8, 10, 16, 18, 20, 22)
]


def _track1_runtime(*positions):
    payload = {
        "source": "test", "route": "track1_candidate", "error": None,
        "gates": {"blocking_now": [], "orders_possible": True},
        "safety": {"jobs": SAFETY_JOBS},
        "book": {
        "present": True,
        "payload": {"equity": 0, "peak_equity": 0, "positions": list(positions)},
        },
    }
    payload["paper_account"] = {
        "status": "PASS", "headline_usable": True, "currency": "USD", "equity": 251752,
    }
    return payload


def _broker_rows(rows, orders=(), server_now="2026-09-25T17:00:00Z"):
    payload = copy.deepcopy(BASE_PAYLOADS["/api/v1/broker"])
    payload["server_now"] = server_now
    payload["payload"]["positions"] = list(rows)
    payload["payload"]["orders"] = list(orders)
    payload["payload"]["contract_specs"] = {}
    return payload


def _live_pos(inst, direction="LONG"):
    return {"inst": inst, "position": 1 if direction == "LONG" else -1,
            "market_price": 101, "avg_cost": 100, "market_value": 101,
            "realized_pnl": 0, "unrealized_pnl": 1, "sec_type": "FUT"}


def _protection_page(browser_page, realtime_server, books, live, *,
                     orders=(), server_now="2026-09-25T17:00:00Z"):
    schedule = copy.deepcopy(BASE_PAYLOADS["/api/v1/schedule-status"])
    schedule["server_now"] = server_now
    schedule["next_scheduled_job"] = {
        "job_id": "TRACK1_SWING_1405", "at": "2026-09-25T18:05:00Z"}
    schedule["next_decision_job"] = {
        "job_id": "SPY_REFRESH_PM", "at": "2026-09-25T22:20:00Z"}
    market = copy.deepcopy(BASE_PAYLOADS["/api/v1/track1-market-view"])
    market["market_view"]["next_protection_job"] = {
        "job_id": "TRACK1_STOP_REPAIR_1620", "at": "2026-09-25T20:20:00+00:00"}
    stub_api(browser_page, {
        "/api/v1/runner-state": _runner_without_snapshot_positions(),
        "/api/v1/runner-positions": _persisted(*books),
        "/api/v1/broker": _broker_rows(live, orders, server_now),
        "/api/v1/schedule-status": schedule,
        "/api/v1/track1-runtime": _track1_runtime(*books),
        "/api/v1/track1-market-view": market,
    })
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#nowScheduleFacts .schedule-fact")


def test_g101_backend_uses_canonical_safety_schedule():
    job = _next_protection_job(dt.datetime(2026, 9, 25, 17, 57, tzinfo=dt.timezone.utc))
    assert job == {
        "job_id": "TRACK1_STOP_REPAIR_1620", "at": "2026-09-25T20:20:00+00:00"}


def test_g101_g103_naked_position_adds_next_protection_without_replacing_next_job(
        browser_page, realtime_server):
    book = _book_row(instrument="M2K", sleeve="roska4_swing",
                     entry_time="2026-09-23 15:55:00")
    _protection_page(browser_page, realtime_server, [book], [_live_pos("M2KZ6")],
                     server_now="2026-09-25T17:57:00Z")
    browser_page.wait_for_timeout(2_000)
    facts = browser_page.locator("#nowScheduleFacts").inner_text()
    assert "NEXT PROTECTION" in facts, {
        "facts": facts,
        "protection": browser_page.locator("#metricStopsCovered").inner_text(),
    }
    assert "NEXT JOB\nTRACK1_SWING_1405" in facts
    # 2026-09-26. This asserted a bare clock and the panel prints a weekday in front of it.
    # The renderer is right and this line was behind it: all three rows of the bar carry a
    # weekday, and a protection job shown as 16:20 ET alone cannot be told from the same job
    # tomorrow — which is exactly the question an operator is asking when they read this row.
    # The weekday is asserted here rather than stripped out, so a renderer that drops it again
    # fails instead of passing quietly.
    assert "NEXT PROTECTION\nTRACK1_STOP_REPAIR_1620\nFri 16:20 ET" in facts
    assert "NEXT JOB\nTRACK1_SWING_1405\nFri 14:05 ET" in facts, (
        "the weekday must be on every row of the bar, not only the one this test grew around")


def test_g102_protected_or_empty_book_keeps_the_existing_schedule_bar(
        browser_page, realtime_server):
    book = _book_row(instrument="M2K", sleeve="roska4_swing",
                     entry_time="2026-09-23 15:55:00")
    stop = {"inst": "M2KZ6", "type": "STP", "action": "SELL", "qty": 1,
            "aux_price": 90, "status": "Submitted", "order_id": 7}
    _protection_page(browser_page, realtime_server, [book], [_live_pos("M2KZ6")], orders=[stop])
    assert "Next protection" not in browser_page.locator("#nowScheduleFacts").inner_text()
    assert browser_page.locator("#nowScheduleFacts .schedule-fact").count() == 4


def test_g102_empty_book_keeps_the_existing_schedule_bar(browser_page, realtime_server):
    _protection_page(browser_page, realtime_server, [], [])
    assert "Next protection" not in browser_page.locator("#nowScheduleFacts").inner_text()
    assert browser_page.locator("#nowScheduleFacts .schedule-fact").count() == 4


def test_g104_g111_g112_g113_each_sleeve_uses_its_own_arming_clock(
        browser_page, realtime_server):
    books = [
        _book_row(instrument="M2K", sleeve="roska4_swing", direction="LONG",
                  entry_time="2026-09-24 15:55:00"),
        _book_row(instrument="MYM", sleeve="roska4_stress", direction="LONG",
                  entry_time="2026-09-23 11:00:00"),
        _book_row(instrument="MNKD", sleeve="global_nkd", direction="LONG",
                  entry_time="2026-09-25 01:25:00"),
        _book_row(instrument="MNKD", sleeve="global_nkd", direction="SHORT",
                  entry_time="2026-09-23 01:25:00"),
    ]
    live = [_live_pos("M2KZ6"), _live_pos("MYMZ6"),
            _live_pos("MNKZ6"), _live_pos("NKDZ6", "SHORT")]
    _protection_page(browser_page, realtime_server, books, live)
    browser_page.wait_for_function("document.querySelector('#metricStopsCovered').textContent !== '--'")
    protection = browser_page.locator("#metricStopsCovered").inner_text().lower()
    assert protection == "0 covered / 2 deferred / 2 naked"


def test_g114_unmatched_position_is_unknown_not_deferred(browser_page, realtime_server):
    _protection_page(browser_page, realtime_server, [], [_live_pos("XYZQ6")])
    browser_page.wait_for_function("document.querySelector('#metricStopsCovered').textContent !== '--'")
    protection = browser_page.locator("#metricStopsCovered").inner_text().lower()
    assert protection == "0 covered / 1 unknown"
    assert "deferred" not in protection and "naked" not in protection


def _staleness_page(browser_page, realtime_server, *, age_seconds):
    runner = copy.deepcopy(BASE_PAYLOADS["/api/v1/runner-state"])
    runner["age_seconds"] = age_seconds
    runner["freshness"] = "fresh"
    book = _book_row(instrument="M2K", sleeve="roska4_swing")
    stub_api(browser_page, {
        "/api/v1/runner-state": runner,
        "/api/v1/track1-runtime": _track1_runtime(book),
    })
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_function("document.querySelector('#metricEquity').textContent.includes('251,752')")


def test_g121_g122_g124_retired_runner_age_does_not_dim_track1_values(
        browser_page, realtime_server):
    _staleness_page(browser_page, realtime_server, age_seconds=48 * 3600)
    opacities = browser_page.evaluate("""() => ({
      equity: getComputedStyle(document.querySelector('#metricEquity').closest('.equity-zone')).opacity,
      gross: getComputedStyle(document.querySelector('#metricGrossExposure').parentElement).opacity,
      realized: getComputedStyle(document.querySelector('#metricRealized').parentElement).opacity,
      decision: getComputedStyle(document.querySelector('#decisionSection')).opacity,
      stale: document.querySelector('#metrics').classList.contains('runner-stale'),
      freshness: document.querySelector('#metrics').className
    })""")
    assert opacities["equity"] == "1"
    assert opacities["gross"] == "1"
    assert opacities["realized"] == "1"
    assert opacities["decision"] == "1"
    assert opacities["stale"] is False


def test_g123_recent_retired_runner_envelope_also_dims_nothing(browser_page, realtime_server):
    _staleness_page(browser_page, realtime_server, age_seconds=60)
    assert browser_page.locator("#metrics").evaluate("el => el.classList.contains('runner-stale')") is False
    opacities = browser_page.evaluate("""() => [
      document.querySelector('#metricEquity').closest('.equity-zone'),
      document.querySelector('#metricGrossExposure').parentElement,
      document.querySelector('#metricRealized').parentElement
    ].map(el => getComputedStyle(el).opacity)""")
    assert opacities == ["1", "1", "1"]
