# -*- coding: utf-8 -*-
"""The paper-evidence gate learns the Calm 15:55 exit without changing what the gate asks for.

Before 2026-10-05 `_normalize_exit` knew three swing paths. A Calm clock exit writes
`exit_reason = "TIME_EXIT"`, which it did not recognise, so every Calm close would have been
counted as an unlabelled CLOSE — the "instrumentation gap" the gate exists to report.

The fix has two halves and both are pinned here:
  recognised   a TIME_EXIT close is a labelled exit: it is not an unlabelled one, and the gate
               says how many there were
  kept apart   it is NOT one of the three paths the gate requires, so it can neither satisfy the
               target nor turn a swing STRUCTURAL_GAP into PENDING
"""
import json
from pathlib import Path

from monitor.backend.paper_evidence_reader import _normalize_exit, read_paper_evidence
from monitor.test_dashboard_backend import _close_row, _write_minimal_paper_fixture


def _calm_close(inst="MES", day="2026-08-10") -> str:
    row = json.loads(_close_row(inst, "TIME_EXIT", day))
    row["cluster"] = "roska4_calm"
    return json.dumps(row)


def _gate(tmp_path: Path, rows: list) -> dict:
    _write_minimal_paper_fixture(tmp_path)
    (tmp_path / "trade_log.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    gates = {g["key"]: g for g in read_paper_evidence(tmp_path, route="legacy")["payload"]["gates"]}
    return gates["exit_path_coverage"]


def test_time_exit_is_a_recognised_reason_and_the_old_ones_are_unchanged():
    assert _normalize_exit("TIME_EXIT") == "TIME_EXIT"
    assert _normalize_exit("time_exit") == "TIME_EXIT"
    assert _normalize_exit("MAX_HOLD") == "MAX_HOLD"
    assert _normalize_exit("CHANDELIER") == "CHANDELIER"
    assert _normalize_exit("STP") == "STP"
    assert _normalize_exit(None) is None and _normalize_exit("something_else") is None


def test_calm_time_exits_are_not_reported_as_unlabelled(tmp_path):
    g = _gate(tmp_path, [_calm_close("MES"), _calm_close("MNQ"), _calm_close("MES")])
    assert g["metrics"]["unlabelled_exits"] == 0, "a labelled exit was counted as an instrumentation gap"
    assert g["metrics"]["time_exits"] == 3
    assert "TIME_EXIT 3" in g["evidence"]
    assert g["status"] != "STRUCTURAL_GAP"


def test_the_gate_still_asks_for_exactly_the_three_swing_paths(tmp_path):
    g = _gate(tmp_path, [_calm_close()])
    assert sorted(g["metrics"]["exits"]) == ["CHANDELIER", "MAX_HOLD", "STP"], g["metrics"]["exits"]
    assert g["metrics"]["target_each"] == 3


def test_time_exits_cannot_fill_a_swing_path(tmp_path):
    rows = ([_close_row("MES", "CHANDELIER")] * 3 + [_close_row("MYM", "MAX_HOLD")] * 3
            + [_close_row("MNQ", "STP")] * 2 + [_calm_close()] * 10)
    g = _gate(tmp_path, rows)
    assert g["status"] == "PENDING", "ten Calm exits must not make up for a missing STP exit"
    assert g["metrics"]["exits"] == {"CHANDELIER": 3, "MAX_HOLD": 3, "STP": 2}


def test_control_three_of_each_swing_path_still_passes_with_time_exits_present(tmp_path):
    rows = ([_close_row("MES", "CHANDELIER")] * 3 + [_close_row("MYM", "MAX_HOLD")] * 3
            + [_close_row("MNQ", "STP")] * 3 + [_calm_close()] * 2)
    g = _gate(tmp_path, rows)
    assert g["status"] == "PASS", g


def test_time_exits_do_not_hide_a_swing_structural_gap(tmp_path):
    rows = [_close_row("MES")] * 4 + [_calm_close()] * 3      # four swing closes with no reason
    g = _gate(tmp_path, rows)
    assert g["status"] == "STRUCTURAL_GAP", g["status"]
    assert g["metrics"]["unlabelled_exits"] == 4 and g["metrics"]["labelled_exits"] == 0
    assert g["metrics"]["time_exits"] == 3
