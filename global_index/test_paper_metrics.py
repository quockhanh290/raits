"""
global_index/test_paper_metrics.py — live equity curve + running_metrics

The dashboard's CALMAR / SHARPE / MAX DD / RETURN bar rendered as dashes because
renderMetricsBar reads snap.running_metrics and dump_state never wrote it. It could
not: live mode holds one snapshot per run and every cron slot is a separate process,
so no equity curve existed anywhere. generate_replay_snapshots.py said as much —
"Populated by runner.dump_state() during live paper trading (not yet written)".

_record_paper_day accumulates one end-of-day mark per date; _running_metrics turns
those into daily P&L and runs them through deploy_sim.metrics, the same formulas the
backtest uses, so a live Calmar is comparable with the 1.65 floor.

  PM1: a mark is persisted and survives a fresh process
  PM2: 22 slots in one day leave ONE entry, last write wins (no double counting)
  PM3: one day -> nulls (Calmar over a single point is not a number to show)
  PM4: daily series sums to exactly equity - account
  PM5: metrics match deploy_sim on the same series
  PM6: zero-drawdown Calmar is inf -> null, not a printed number
  PM7: a corrupt history file degrades to empty, it does not crash the runner
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futures.circuit_breaker import CircuitBreaker
from global_index.broker import MockBroker
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"


def _runner(tmp_path, equity=ACCOUNT):
    return FuturesRunner(
        broker=MockBroker({}, equity),
        guard=MultiClusterGuard(account=ACCOUNT, clusters={
            CLUSTER: ClusterBudget(CLUSTER, max_gross_pct=0.05, max_net_pct=0.044)}),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
        live_state_path=tmp_path / "live.js",
        paper_history_path=tmp_path / "paper_history.json",
    )


def _seed(r, marks):
    """marks: [(date, equity)] applied in order."""
    hist = {}
    for d, eq in marks:
        hist = r._record_paper_day(pd.Timestamp(d), eq)
    return hist


# ── persistence ───────────────────────────────────────────────────────────────

def test_pm1_mark_survives_a_new_process(tmp_path):
    _seed(_runner(tmp_path), [("2026-08-04", 50_120.0)])
    hist = json.loads((tmp_path / "paper_history.json").read_text())
    assert hist["days"] == {"2026-08-04": 50_120.0}
    # fresh runner, same files — the curve must still be there
    r2 = _runner(tmp_path)
    hist2 = r2._record_paper_day(pd.Timestamp("2026-08-05"), 50_300.0)
    assert sorted(hist2["days"]) == ["2026-08-04", "2026-08-05"]


def test_pm2_many_slots_one_day_is_one_entry(tmp_path):
    """22 continuous slots write the same date; the close must win, not accumulate."""
    r = _runner(tmp_path)
    for i in range(22):
        hist = r._record_paper_day(pd.Timestamp("2026-08-04"), 50_000.0 + i)
    assert list(hist["days"]) == ["2026-08-04"], "one entry per date"
    assert hist["days"]["2026-08-04"] == 50_021.0, "last write wins"


# ── metrics ───────────────────────────────────────────────────────────────────

def test_pm3_single_day_returns_nulls(tmp_path):
    r = _runner(tmp_path)
    hist = _seed(r, [("2026-08-04", 50_120.0)])
    assert r._running_metrics(hist) == {"calmar": None, "sharpe": None,
                                        "max_dd": None, "total_return": None}


def test_pm4_daily_series_sums_to_net_pnl(tmp_path):
    """First day measured from ACCOUNT, so the series must close the gap exactly."""
    r = _runner(tmp_path)
    marks = [("2026-08-04", 50_400.0), ("2026-08-05", 50_100.0), ("2026-08-06", 50_950.0)]
    m = r._running_metrics(_seed(r, marks))
    assert m["total_return"] == pytest.approx((50_950.0 - ACCOUNT) / ACCOUNT)


def test_pm5_matches_deploy_sim_on_the_same_series(tmp_path):
    """Live Calmar must be the backtest's formula, or comparing it to the floor lies."""
    from global_index.deploy_sim import metrics as ref
    r = _runner(tmp_path)
    marks = [("2026-08-04", 50_400.0), ("2026-08-05", 50_100.0),
             ("2026-08-06", 50_950.0), ("2026-08-07", 50_600.0)]
    m = r._running_metrics(_seed(r, marks))

    eq = pd.Series({pd.Timestamp(d): v for d, v in marks}).sort_index()
    daily = eq.diff(); daily.iloc[0] = eq.iloc[0] - ACCOUNT
    exp = ref(daily)
    assert m["calmar"] == pytest.approx(round(exp["calmar"], 4))
    assert m["sharpe"] == pytest.approx(round(exp["sharpe"], 4))
    assert m["max_dd"] == pytest.approx(round(exp["maxdd"], 2))


def test_pm6_infinite_calmar_is_null(tmp_path):
    """Monotonic gains early in paper give zero drawdown → inf. Show a dash."""
    r = _runner(tmp_path)
    m = r._running_metrics(_seed(r, [("2026-08-04", 50_100.0), ("2026-08-05", 50_200.0)]))
    assert m["calmar"] is None
    assert m["max_dd"] == pytest.approx(0.0)


def test_pm7_corrupt_history_does_not_crash(tmp_path):
    (tmp_path / "paper_history.json").write_text("{ this is not json")
    r = _runner(tmp_path)
    hist = r._record_paper_day(pd.Timestamp("2026-08-04"), 50_120.0)
    assert hist["days"] == {"2026-08-04": 50_120.0}, "must start fresh, not raise"


def test_pm8_dump_state_publishes_running_metrics(tmp_path):
    """End to end: the field the dashboard reads is actually in the payload."""
    r = _runner(tmp_path)
    _seed(r, [("2026-08-04", 50_400.0), ("2026-08-05", 50_100.0)])
    r.dump_state(pd.Timestamp("2026-08-06"))
    raw = (tmp_path / "live.js").read_text(encoding="utf-8")
    d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    rm = d["snapshots"][0]["running_metrics"]
    assert set(rm) == {"calmar", "sharpe", "max_dd", "total_return"}
    assert rm["max_dd"] is not None, "three marks is enough for a drawdown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
