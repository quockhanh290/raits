from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from global_index import replay_checkpoint
from global_index import route_checkpoint
from global_index import track1_live_source
from global_index import track1_normal_r4 as normal_r4
from global_index import track1_signal_layer as signal_layer
from global_index.runner import FuturesRunner, _openpos_from_dict


HERE = Path(__file__).parent
ROOT = HERE.parent
GOLDEN = HERE / "test_entrydate_golden.json"

LIVE_ROWS = [
    {"trade_id": "normal_r4::M2K::2026-09-24", "sleeve": "roska4_swing",
     "instrument": "M2K", "direction": "LONG", "qty": 1, "risk_dollars": 469.4643,
     "entry_time": "2026-09-24 15:55:00", "entry_price": 2857.0,
     "stop_price": 2782.785714285714, "order_id": "30"},
    {"trade_id": "normal_r4::MYM::2026-09-24", "sleeve": "roska4_swing",
     "instrument": "MYM", "direction": "LONG", "qty": 1, "risk_dollars": 677.9464,
     "entry_time": "2026-09-24 15:55:00", "entry_price": 51732.0,
     "stop_price": 50662.28571428572, "order_id": "28"},
    {"trade_id": "global_nkd::MNKD::2026-09-25", "sleeve": "global_nkd",
     "instrument": "MNKD", "direction": "LONG", "qty": 1,
     "risk_dollars": 1761.6071428571427, "entry_time": "2026-09-25 14:20:00+09:00",
     "entry_price": 66145.0, "stop_price": 63321.42857142857, "order_id": "40"},
    {"trade_id": "normal_r4::MES::2026-09-25", "sleeve": "roska4_swing",
     "instrument": "MES", "direction": "LONG", "qty": 1,
     "risk_dollars": 908.2589285714287, "entry_time": "15:00",
     "entry_price": 7797.25, "stop_price": 7652.178571428572, "order_id": "68"},
]

CONSUMER_FILES = [
    "ibkr_broker.py", "generate_replay_snapshots.py", "replay_checkpoint.py",
    "route_checkpoint.py", "runner.py", "run_live_day_track1.py",
    "track1_book_backfill.py", "track1_bootstrap.py", "track1_calm_a.py",
    "track1_explain.py", "track1_live_source.py", "track1_normal_r4.py",
    "track1_paper_order.py", "track1_paper_send.py", "track1_signals.py",
    "track1_signal_layer.py", "track1_strategy_diagnostics.py",
    "track1_stress_mnq.py", "track1_trade_log_backfill.py",
    "verify_concat_desired.py", "_core.py",
]


def _row(**overrides):
    row = {"instrument": "MES", "direction": "LONG", "qty": 1,
           "risk_dollars": 100.0, "sleeve": "roska4_swing"}
    row.update(overrides)
    return row


def _values(row):
    return json.loads(json.dumps(dataclasses.asdict(_openpos_from_dict(row)), default=str))


def _digest(values):
    raw = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def test_p1_1_live_swing_setup_keeps_the_signal_date(monkeypatch):
    day = pd.Timestamp("2026-09-25")
    bars = pd.DataFrame(
        {"close": [1.0, 1.0]},
        index=pd.DatetimeIndex(["2026-09-25 14:00", "2026-09-25 15:00"]),
    )
    monkeypatch.setattr(normal_r4, "_cache_for", lambda *_: {
        "b5": {day: bars}, "datr": pd.Series([10.0], index=[day])})
    monkeypatch.setattr(normal_r4, "_strategy", lambda *_: object())
    monkeypatch.setattr(normal_r4, "make_signal_fn", lambda *_args, **_kwargs: object())
    bar_ts = pd.Timestamp("2026-09-25 15:00")
    monkeypatch.setattr(normal_r4, "_scan_window", lambda *_args, **_kwargs: (
        bar_ts, {"direction": "LONG", "entry_price": 100.0, "initial_stop": 90.0}))

    setup = normal_r4.detect_entry_for_slot(
        bars, {day: "Normal"}, "MES", day, bar_ts, normal_r4.NormalR4Params(),
        short_days=set(), apply_context_filter=False)

    assert setup is not None
    assert setup.entry_time == "2026-09-25 15:00:00"
    assert setup.signal_bar == bar_ts


def test_p1_2_all_twenty_one_consumers_are_surveyed_and_timestamp_safe():
    assert len(CONSUMER_FILES) == 21
    for name in CONSUMER_FILES:
        text = (HERE / name).read_text(encoding="utf-8")
        assert re.search(r"\bentry_time\b", text), name

    full = "2026-09-25 15:00:00"
    assert signal_layer._hhmm_on(full, "America/New_York") == "15:00"
    assert signal_layer.window_verdict("roska4_swing", full) == signal_layer.window_verdict(
        "roska4_swing", "15:00")
    assert replay_checkpoint._pos_from_json({"entry_time": full})["entry_time"] == pd.Timestamp(full)
    assert route_checkpoint._pos_from_json({"entry_time": full})["entry_time"] == pd.Timestamp(full)
    assert "entry_time=setup.entry_time" in inspect.getsource(
        track1_live_source.LiveTrack1Source._swing_candidates)


def test_p1_3_nkd_aware_stamp_path_is_untouched_and_byte_identical():
    source = inspect.getsource(track1_live_source.LiveTrack1Source._nkd_candidates)
    assert "entry_time=pd.Timestamp(setup.signal_bar)" in source
    stamp = "2026-09-25 14:20:00+09:00"
    assert str(pd.Timestamp(stamp)) == stamp


def test_p2_1_dated_entry_times_yield_et_naive_and_tokyo_dates():
    assert _openpos_from_dict(_row(entry_time="2026-09-24 15:55:00")).entry_day == pd.Timestamp(
        "2026-09-24")
    assert _openpos_from_dict(_row(entry_time="2026-09-25 14:20:00+09:00")).entry_day == pd.Timestamp(
        "2026-09-25")


def test_p2_2_bare_clock_does_not_guess_and_remains_not_deferred():
    pos = _openpos_from_dict(_row(entry_time="15:00"))
    assert pos.entry_day is None
    assert FuturesRunner.__new__(FuturesRunner)._stop_deferred(
        pos, now=pd.Timestamp("2026-09-25 16:30")) is False


def test_p2_3_explicit_entry_day_wins_when_no_date_can_be_derived():
    pos = _openpos_from_dict(_row(entry_day="2026-09-23", entry_time="15:00"))
    assert pos.entry_day == pd.Timestamp("2026-09-23")


def test_p2_4_disagreeing_entry_day_and_entry_time_raise_with_both_field_names():
    with pytest.raises(ValueError, match="entry_day/entry_time"):
        _openpos_from_dict(_row(entry_day="2026-09-23",
                                entry_time="2026-09-24 15:00:00"))


def test_p2_5_four_measured_rows_split_due_deferred_and_absent_date():
    runner = FuturesRunner.__new__(FuturesRunner)
    now = pd.Timestamp("2026-09-25 16:30")
    positions = {row["instrument"]: _openpos_from_dict(row) for row in LIVE_ROWS}
    outcomes = {inst: runner._stop_deferred(pos, now=now) for inst, pos in positions.items()}

    assert outcomes == {"M2K": False, "MYM": False, "MNKD": True, "MES": False}
    assert positions["MES"].entry_day is None, (
        "MES is not deferred because its entry date is absent, not because an arm time was computed")


def test_p2_6_every_on_disk_row_matches_the_nonempty_prechange_golden():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    base_rows = []
    live_rows = []
    observed_files = []
    for name, expected_count in golden["files"]:
        payload = json.loads((ROOT / name).read_text(encoding="utf-8"))
        rows = list(payload.get("positions") or [])
        assert len(rows) == expected_count, name
        observed_files.append((name, len(rows)))
        (live_rows if name == "live_positions.track1.json" else base_rows).extend(rows)

    assert observed_files == [tuple(item) for item in golden["files"]]
    assert len(base_rows) + len(live_rows) == golden["row_count"] == 14
    assert golden["raised_count"] == 0
    assert base_rows and live_rows

    changed = []
    expected = golden["base_records"]
    assert len(base_rows) == len(expected)
    for index, (row, (_golden_index, before_hash, before_day)) in enumerate(zip(base_rows, expected)):
        values = _values(row)
        if values["entry_day"] != before_day:
            assert re.match(r"^\d{4}-\d{2}-\d{2}", str(row.get("entry_time") or ""))
            assert values["entry_day"][:10] == row["entry_time"][:10]
            changed.append(("base", index))
        assert _digest(dict(values, entry_day=before_day)) == before_hash

    expected_live = golden["live_records"]
    assert len(live_rows) == len(expected_live)
    for row, (inst, before_hash, before_day) in zip(live_rows, expected_live):
        assert row["instrument"] == inst
        values = _values(row)
        if values["entry_day"] != before_day:
            assert re.match(r"^\d{4}-\d{2}-\d{2}", str(row.get("entry_time") or ""))
            assert values["entry_day"][:10] == row["entry_time"][:10]
            changed.append(("live", inst))
        assert _digest(dict(values, entry_day=before_day)) == before_hash

    # MES joined this list on 2026-09-26, when the operator ran Part 3 and gave that row the
    # date its own fill journal already carried. Before that it was the one live row still
    # loading with no entry_day, because the live setup builder had stamped a bare clock.
    # The V2 report said this line must be updated at that moment and not before, and this is
    # that moment. Its digest still matches the pre-change hash, which is the point: only the
    # derived date moved, and every other loaded value on that row is byte-identical.
    assert changed == [
        ("base", 5), ("base", 6), ("base", 7),
        ("live", "M2K"), ("live", "MYM"), ("live", "MNKD"), ("live", "MES"),
    ]
