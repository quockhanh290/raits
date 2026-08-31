"""Stage 5ZZZ-AX. A SESSION beside the snapshot.

`recorded_for` returns the LAST block, which answers "what did the detector decide" and not
"what has the session been doing". A snapshot of this sleeve is actively misleading: slots fire
on the five-minute boundary, so the newest bar is seconds old and its volume reads 0. Measured
across 2026-08-31, the thirteen slots that carried numbers read

    volume        0  0  0  0  5  0  6  14  0  0  4  1  0
    ten-bar avg   5.8 ..................................  32.0

-- a column of zeros beside a baseline that grew five-fold. No single slot can show that.
"""
from __future__ import annotations

import json

import pytest

from global_index import track1_strategy_diagnostics as sd
from monitor.backend import track1_market_view as mv


def _write(root, day: str, **over) -> None:
    block = {
        "schema": sd.SCHEMA,
        "diagnostics_source": sd.RECORDED,
        "sleeve": "global_nkd",
        "slot_id": "NKD_NIGHT_0205",
        "slot_time": "02:05",
        "session_date": day,
        "bars_evaluated": 12,
        "last_bar_ts": "2026-08-31 15:05:00+09:00",
        "last_bar_complete": False,
        "rows": [
            {"label": "Trend filter (EMA 10)", "value": 66128.65},
            {"label": "Close used", "value": 66110.0},
            {"label": "Daily ATR", "value": 1548.93},
            {"label": "Volume", "value": 0.0},
            {"label": "Average volume (10 bars)", "value": 3.2},
        ],
    }
    block.update(over)
    p = sd.path_for(str(root), day)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(block, default=str) + "\n")


@pytest.fixture()
def root(tmp_path):
    return tmp_path


def test_every_recorded_slot_comes_back_not_only_the_last(root):
    """The defect this exists to fix: one slot cannot show a session."""
    for t in ("02:05", "02:10", "02:15"):
        _write(root, "20260831", slot_time=t, slot_id="NKD_NIGHT_" + t.replace(":", ""))
    series = sd.recorded_series(root, "20260831", "global_nkd")
    assert [p["slot_time"] for p in series] == ["02:05", "02:10", "02:15"]


def test_the_series_is_in_slot_order_however_the_file_was_written(root):
    """Blocks are APPENDED, and a re-run lands out of order. The line must not zigzag."""
    for t in ("02:15", "02:05", "02:10"):
        _write(root, "20260831", slot_time=t, slot_id="NKD_NIGHT_" + t.replace(":", ""))
    series = sd.recorded_series(root, "20260831", "global_nkd")
    assert [p["slot_time"] for p in series] == ["02:05", "02:10", "02:15"]


def test_a_rerun_slot_appears_once_and_the_later_write_wins(root):
    """Same rule `recorded_for` applies: the last block for a slot is the slot."""
    _write(root, "20260831", bars_evaluated=12)
    _write(root, "20260831", bars_evaluated=99)
    series = sd.recorded_series(root, "20260831", "global_nkd")
    assert len(series) == 1
    assert series[0]["bars_evaluated"] == 99


def test_a_reconstruction_never_joins_the_line(root):
    """A replay reads the persisted store, whose last bar can be a previous session."""
    _write(root, "20260831", slot_time="02:05")
    _write(root, "20260831", slot_time="02:10", slot_id="NKD_NIGHT_0210",
           diagnostics_source="RECONSTRUCTED")
    series = sd.recorded_series(root, "20260831", "global_nkd")
    assert [p["slot_time"] for p in series] == ["02:05"]


def test_another_sleeve_does_not_leak_into_this_one(root):
    _write(root, "20260831", slot_time="02:05")
    _write(root, "20260831", slot_time="14:10", sleeve="roska4_swing",
           slot_id="LIVE_DAY_1410")
    series = sd.recorded_series(root, "20260831", "global_nkd")
    assert len(series) == 1 and series[0]["slot_time"] == "02:05"


def test_the_point_carries_what_the_chart_draws_and_not_the_whole_block(root):
    """Narrow on purpose: this rides an endpoint that is polled."""
    _write(root, "20260831")
    point = mv._slot_series(root, "20260831", "global_nkd")[0]
    assert point["ema"] == 66128.65, "the EMA label carries its period, so it is matched by prefix"
    assert point["close"] == 66110.0
    assert point["volume"] == 0.0
    assert point["avg_volume"] == 3.2
    assert point["last_bar_complete"] is False, (
        "without this the chart cannot say why a volume of 0 is not a dead market")
    assert "gates" not in point and "bar_gate_grid" not in point and "rows" not in point


def test_a_missing_row_becomes_none_rather_than_disappearing(root):
    """A gap in the line is a fact about the session; a shorter list hides it."""
    _write(root, "20260831", rows=[{"label": "Close used", "value": 66110.0}])
    point = mv._slot_series(root, "20260831", "global_nkd")[0]
    assert point["close"] == 66110.0
    assert point["ema"] is None and point["volume"] is None


def test_a_day_with_nothing_recorded_is_an_empty_line_not_an_error(root):
    assert sd.recorded_series(root, "20260831", "global_nkd") == []
    assert mv._slot_series(root, "20260831", "global_nkd") == []
