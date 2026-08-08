"""global_index/test_live_history.py — build the dashboard's history from what exists

dump_state emits a single snapshot with `entries: []`, `exits: []`, per-cluster P&L of
zero and empty cluster stats, so in live mode the dashboard's Closed Trades, Daily P&L,
Per-Cluster P&L, Regime Attribution, Cluster Statistics and Holding Distribution are all
blank. Not a rendering fault: nobody ever wrote the data.

Everything needed is already on disk and already reconciled against IBKR's statement —
trade_log.jsonl for the fills, paper_history.json for the daily equity marks. So the
snapshot list is a pure function of those two, with no third store to drift out of step
with them.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.live_history import build_snapshots, closed_trades, cumulative

CL = "roska4_swing"


def _open(inst, day, price, cluster=CL, direction="LONG", contracts=1, regime="Normal"):
    return {"type": "OPEN", "inst": inst, "cluster": cluster, "direction": direction,
            "contracts": contracts, "entry_day": day, "fill_price": price,
            "regime": regime, "status": "FILLED"}


def _close(inst, entry_day, exit_day, price, cluster=CL, direction="LONG",
           contracts=1, reason="signal"):
    return {"type": "CLOSE", "inst": inst, "cluster": cluster, "direction": direction,
            "contracts": contracts, "entry_day": entry_day, "exit_day": exit_day,
            "fill_price": price, "exit_reason": reason, "status": "FILLED"}


# MES is $5 a point: 7767.00 → 7737.50 long loses 147.50.
_LOG = [
    _open("MES", "2026-08-05", 7767.00),
    _close("MES", "2026-08-05", "2026-08-06", 7737.50),
    _open("M2K", "2026-08-05", 3033.00, direction="SHORT", regime="Calm"),
    _close("M2K", "2026-08-05", "2026-08-06", 3038.60, direction="SHORT", reason="STP"),
    _open("MYM", "2026-08-03", 53345.00),
    _close("MYM", "2026-08-03", "2026-08-05", 54702.00),
]


# ── pairing ───────────────────────────────────────────────────────────────────

def test_lh1_a_close_is_paired_with_its_open():
    trades = {(t["inst"], t["entry_day"]): t for t in closed_trades(_LOG)}
    mes = trades[("MES", "2026-08-05")]
    assert mes["entry_price"] == pytest.approx(7767.00)
    assert mes["exit_price"] == pytest.approx(7737.50)
    assert mes["pnl"] == pytest.approx(-147.50)


def test_lh2_a_short_loses_when_it_covers_higher():
    trades = {t["inst"]: t for t in closed_trades(_LOG)}
    assert trades["M2K"]["pnl"] == pytest.approx(-28.00)


def test_lh3_hold_days_come_from_the_two_dates():
    trades = {t["inst"]: t for t in closed_trades(_LOG)}
    assert trades["MYM"]["hold_days"] == 2
    assert trades["MES"]["hold_days"] == 1


def test_lh4_an_unpairable_close_is_kept_but_not_priced():
    """The 2026-08-03 entries were lost to a status bug. Dropping those closes would
    hide trades that happened; pricing them at zero would invent a result."""
    log = [_close("MES", "2026-08-03", "2026-08-05", 7771.50)]
    (t,) = closed_trades(log)
    assert t["entry_price"] is None
    assert t["pnl"] is None, "no entry price means no P&L, not a P&L of zero"


# ── cumulative analytics ──────────────────────────────────────────────────────

def test_lh5_pnl_splits_by_cluster_and_by_entry_regime():
    a = cumulative(closed_trades(_LOG), upto="2026-08-06")
    assert a["per_cluster_pnl"][CL] == pytest.approx(-147.50 - 28.00 + 678.50)
    # Regime is the one recorded at entry, which is what attribution means.
    assert a["regime_attribution"]["Calm"] == pytest.approx(-28.00)
    assert a["regime_attribution"]["Normal"] == pytest.approx(-147.50 + 678.50)


def test_lh6_cumulative_stops_at_the_day_asked_for():
    """The dashboard's slider asks for the state as at a past day."""
    a = cumulative(closed_trades(_LOG), upto="2026-08-05")
    assert a["per_cluster_pnl"][CL] == pytest.approx(678.50), "only MYM had closed by then"
    assert a["cluster_stats"][CL]["trade_count"] == 1


def test_lh7_cluster_stats_read_as_the_dashboard_expects():
    a = cumulative(closed_trades(_LOG), upto="2026-08-06")
    s = a["cluster_stats"][CL]
    assert s["trade_count"] == 3
    assert s["win_rate"] == pytest.approx(1 / 3)
    assert s["avg_win"] == pytest.approx(678.50)
    assert s["largest_loss"] == pytest.approx(-147.50)


def test_lh8_unpriced_trades_are_excluded_from_the_money_but_still_counted():
    log = _LOG + [_close("MNQ", "2026-08-03", "2026-08-06", 1.0, cluster=CL)]
    a = cumulative(closed_trades(log), upto="2026-08-06")
    assert a["per_cluster_pnl"][CL] == pytest.approx(-147.50 - 28.00 + 678.50), (
        "a trade with no entry price must not be booked at zero"
    )
    assert a["cluster_stats"][CL]["unpriced"] == 1, "but it must not vanish either"


# ── snapshots ─────────────────────────────────────────────────────────────────

_HISTORY = {"account": 50000.0, "epoch": "2026-08-03",
            "days": {"2026-08-05": 50678.50, "2026-08-06": 50503.00}}


def test_lh9_one_snapshot_per_day_of_the_equity_curve():
    snaps = build_snapshots(_LOG, _HISTORY)
    assert [s["date"] for s in snaps] == ["2026-08-05", "2026-08-06"]
    assert snaps[0]["equity"] == pytest.approx(50678.50)


def test_lh10_each_day_carries_only_the_exits_that_happened_that_day():
    """The dashboard stamps every exit with its snapshot's date, so putting the whole
    history on one snapshot would date every trade to today."""
    snaps = {s["date"]: s for s in build_snapshots(_LOG, _HISTORY)}
    assert [e["inst"] for e in snaps["2026-08-05"]["decision"]["exits"]] == ["MYM"]
    assert sorted(e["inst"] for e in snaps["2026-08-06"]["decision"]["exits"]) == ["M2K", "MES"]


def test_lh11_realised_today_is_that_day_alone():
    snaps = {s["date"]: s for s in build_snapshots(_LOG, _HISTORY)}
    assert snaps["2026-08-06"]["decision"]["realized_today"] == pytest.approx(-175.50)
    assert snaps["2026-08-05"]["decision"]["realized_today"] == pytest.approx(678.50)


def test_lh12_analytics_on_each_snapshot_are_cumulative_to_that_day():
    snaps = {s["date"]: s for s in build_snapshots(_LOG, _HISTORY)}
    assert snaps["2026-08-05"]["per_cluster_pnl"][CL] == pytest.approx(678.50)
    assert snaps["2026-08-06"]["per_cluster_pnl"][CL] == pytest.approx(503.00)


def test_lh13_no_equity_marks_means_no_snapshots_not_a_crash():
    assert build_snapshots(_LOG, {"account": 50000.0, "days": {}}) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
