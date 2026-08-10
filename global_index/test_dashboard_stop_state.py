"""global_index/test_dashboard_stop_state.py — the dashboard must be able to tell the
two kinds of "no stop" apart.

Since the deferral fix, a position with no STP means one of two opposite things: it is
inside its deliberate stop-free window (swing/NKD, entry day — the validated engine only
tests the stop from the day after, and placing it at the fill costs the edge), or it is
genuinely unprotected.

dump_state carries neither the stop nor the window, so the panel cannot show either. The
operator then gets the same trap check_open_orders just had fixed: either alarm every
day a position opens, or learn to ignore the alarm and miss the day it is real.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futures.circuit_breaker import CircuitBreaker
from global_index.broker import MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner

ACCOUNT = 50_000.0
DAY1 = pd.Timestamp("2024-03-11")
DAY2 = pd.Timestamp("2024-03-12")


def _guard():
    return MultiClusterGuard(account=ACCOUNT, clusters={
        "roska4_swing":  ClusterBudget("roska4_swing", max_gross_pct=0.05, max_net_pct=0.044),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
    })


def _pos(cluster, entry_day, stop_order_id=None, stop_price=4950.0, entry_price=5000.0):
    return OpenPos(inst="MES", direction="LONG", contracts=1, risk_dollars=500.0,
                   cluster=cluster, entry_day=entry_day, stop_price=stop_price,
                   stop_order_id=stop_order_id, entry_price=entry_price)


def _snapshot(tmp_path, position, today, now=None):
    r = FuturesRunner(
        broker=MockBroker({}, ACCOUNT), guard=_guard(), contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []), breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json", live_state_path=tmp_path / "live.js",
        today=today,
        # Gio vu trang la rieng tung sleeve (14:00 ET swing / 01:00 ET NKD), nen phai
        # noi ro moc thoi gian; mac dinh nua dem = truoc ca hai gio.
        now=now,
    )
    r.state.open_positions = [position]
    r.dump_state(today)
    raw = (tmp_path / "live.js").read_text(encoding="utf-8")
    d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    return d["snapshots"][-1]["open_positions"][0]


def test_ds1_a_swing_position_opened_today_is_marked_deferred(tmp_path):
    """No stop yet, and that is correct — the panel has to say so rather than alarm."""
    p = _snapshot(tmp_path, _pos("roska4_swing", DAY1), today=DAY1)
    assert p["stop_deferred"] is True
    assert p["stop_order_id"] is None
    assert p["stop_price"] == pytest.approx(4950.0), (
        "the level must travel even before the order does — B4 places it tomorrow from "
        "this number, and the panel shows what is coming"
    )


def test_ds2_the_window_closes_the_next_day(tmp_path):
    """Sau 14:05 ET — gio vu trang cua swing — B4 da dat, khong con doc la deferred.

    Truoc day chi can sang ngay la du; gio phai qua dung gio cua SLEEVE do."""
    p = _snapshot(tmp_path, _pos("roska4_swing", DAY1, stop_order_id="stp-1"),
                  today=DAY2, now=DAY2 + pd.Timedelta(hours=14, minutes=5))
    assert p["stop_deferred"] is False
    assert p["stop_order_id"] == "stp-1"


def test_ds3_a_stress_position_is_never_deferred(tmp_path):
    """roska4_stress is not in the deferred set: it opens and closes inside a session.

    Missing stop there is genuinely missing, and marking it deferred would hide it.
    """
    p = _snapshot(tmp_path, _pos("roska4_stress", DAY1), today=DAY1)
    assert p["stop_deferred"] is False
    assert p["stop_order_id"] is None


def test_ds4_the_entry_price_travels(tmp_path):
    """It was hardcoded None while OpenPos already carried it."""
    p = _snapshot(tmp_path, _pos("roska4_swing", DAY1, entry_price=5001.25), today=DAY1)
    assert p["entry_price"] == pytest.approx(5001.25)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
