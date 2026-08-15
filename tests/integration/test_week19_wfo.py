"""
tests/integration/test_week19_wfo.py

Week 19: Walk-Forward Optimization tests.

Test classes:
  TestParamGrid          — grid definition, aggregation, dominance check
  TestWFOWindowSchedule  — window slicing, burn-in, partial final window
  TestWFOEngine          — full run on synthetic data, report structure
  TestProductionParams   — YAML save/load round-trip, snapping to valid grid

Run from RAITS project root:
  python -m pytest tests/integration/test_week19_wfo.py -v
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
import logging
import tempfile
import unittest
from datetime import date
from typing import Dict, List

import numpy as np
import pandas as pd

def setUpModule():
    # See the twin in test_week18_e2e.py: this was a module-level, process-wide
    # logging.disable() that ran during collection and silenced the whole session.
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)

from raits.backtest.wfo_grid import (
    all_param_combinations,
    aggregate_params,
    check_window_dominance,
    WindowResult,
    ProductionParams,
    _nearest,
    ORB_RANGE_VALUES,
    VWAP_BB_STD_VALUES,
    EMA_PERIOD_VALUES,
)
from raits.backtest.wfo import WFOEngine, WFOConfig


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_window_result(
    idx: int = 1,
    orb: int = 15,
    std: float = 2.0,
    ema: int = 30,
    oos_calmar: float = 1.5,
    oos_net_profit: float = 1000.0,
) -> WindowResult:
    return WindowResult(
        window_idx=idx,
        train_start="2019-01-02", train_end="2021-12-31",
        test_start="2022-01-03",  test_end="2022-12-30",
        best_orb_range=orb,
        best_bb_std=std,
        best_ema_period=ema,
        train_calmar=2.0,
        oos_calmar=oos_calmar,
        oos_sharpe=1.2,
        oos_max_dd=-0.10,
        oos_profit_factor=1.6,
        oos_win_rate=0.55,
        oos_total_return=0.08,
        oos_total_trades=42,
        oos_net_profit=oos_net_profit,
    )


def _make_spy_bars(
    start: str,
    end: str,
    base: float = 460.0,
    seed: int = 42,
) -> pd.DataFrame:
    """5-min SPY bars from start to end."""
    rng = np.random.default_rng(abs(hash(seed)) % (2**31))
    days = pd.bdate_range(start, end)
    records = []
    price = base
    for day in days:
        times = pd.date_range(
            start=day.replace(hour=9, minute=30),
            end=day.replace(hour=15, minute=55),
            freq="5min",
        )
        for ts in times:
            ret = rng.normal(0, 0.003)
            price = max(price * (1 + ret), 1.0)
            spread = abs(rng.normal(0, 0.001)) * price
            records.append({
                "open":   round(price * (1 - 0.001), 2),
                "high":   round(price + spread, 2),
                "low":    round(price - spread, 2),
                "close":  round(price, 2),
                "volume": int(rng.integers(500_000, 2_000_000)),
            })
    idx = []
    for day in days:
        idx.extend(pd.date_range(
            start=day.replace(hour=9, minute=30),
            end=day.replace(hour=15, minute=55),
            freq="5min",
        ).tolist())
    return pd.DataFrame(records, index=pd.DatetimeIndex(idx[:len(records)]))


def _make_market_data_wfo(
    tickers: List[str],
    start: str,
    end: str,
) -> Dict[str, pd.DataFrame]:
    data = {}
    for ticker in tickers:
        base = 100.0 + abs(hash(ticker)) % 300
        seed = abs(hash(ticker)) % (2**20)
        data[ticker] = _make_spy_bars(start, end, base=base, seed=seed)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestParamGrid(unittest.TestCase):
    """Grid definition, aggregation, dominance check."""

    def test_grid_has_exactly_27_combinations(self):
        combos = all_param_combinations()
        self.assertEqual(len(combos), 27)

    def test_all_combos_use_valid_values(self):
        for orb, std, ema in all_param_combinations():
            self.assertIn(orb, ORB_RANGE_VALUES,  f"Invalid ORB: {orb}")
            self.assertIn(std, VWAP_BB_STD_VALUES, f"Invalid BB std: {std}")
            self.assertIn(ema, EMA_PERIOD_VALUES,  f"Invalid EMA: {ema}")

    def test_no_duplicate_combos(self):
        combos = all_param_combinations()
        self.assertEqual(len(combos), len(set(combos)))

    # ── Aggregation ───────────────────────────────────────────────────────────

    def test_mean_aggregation_snaps_to_grid(self):
        windows = [
            _make_window_result(1, orb=10, std=1.5, ema=20),
            _make_window_result(2, orb=20, std=2.5, ema=50),
            _make_window_result(3, orb=15, std=2.0, ema=30),
        ]
        params = aggregate_params(windows, method="MEAN")
        # Means: ORB=15, std=2.0, EMA=33.3→30
        self.assertIn(params.orb_range_minutes, ORB_RANGE_VALUES)
        self.assertIn(params.vwap_bb_std,       VWAP_BB_STD_VALUES)
        self.assertIn(params.ema_period,         EMA_PERIOD_VALUES)
        self.assertEqual(params.aggregation_method, "MEAN")

    def test_mode_aggregation_picks_most_frequent(self):
        windows = [
            _make_window_result(1, orb=15, std=2.0, ema=30),
            _make_window_result(2, orb=15, std=2.0, ema=20),
            _make_window_result(3, orb=20, std=2.0, ema=30),
        ]
        params = aggregate_params(windows, method="MODE")
        self.assertEqual(params.orb_range_minutes, 15)
        self.assertEqual(params.vwap_bb_std, 2.0)
        self.assertEqual(params.ema_period,  30)

    def test_calmar_weighted_aggregation(self):
        windows = [
            _make_window_result(1, orb=10, std=1.5, ema=20, oos_calmar=0.5),
            _make_window_result(2, orb=20, std=2.5, ema=50, oos_calmar=3.0),
        ]
        params = aggregate_params(windows, method="CALMAR_WEIGHTED")
        # High-calmar window (20, 2.5, 50) should pull params toward those values
        self.assertIn(params.orb_range_minutes, ORB_RANGE_VALUES)
        self.assertGreater(params.orb_range_minutes, 10)   # pulled toward 20

    def test_single_window_aggregation(self):
        windows = [_make_window_result(1, orb=15, std=2.0, ema=30)]
        params = aggregate_params(windows, method="MEAN")
        self.assertEqual(params.orb_range_minutes, 15)
        self.assertEqual(params.vwap_bb_std, 2.0)
        self.assertEqual(params.ema_period, 30)

    def test_aggregation_raises_on_empty_windows(self):
        with self.assertRaises(ValueError):
            aggregate_params([], method="MEAN")

    def test_unknown_method_raises(self):
        windows = [_make_window_result(1)]
        with self.assertRaises(ValueError):
            aggregate_params(windows, method="BOGUS")

    # ── Dominance check ───────────────────────────────────────────────────────

    def test_dominance_check_passes_when_balanced(self):
        windows = [
            _make_window_result(1, oos_net_profit=400.0),
            _make_window_result(2, oos_net_profit=350.0),
            _make_window_result(3, oos_net_profit=250.0),
        ]
        result = check_window_dominance(windows)
        self.assertTrue(result["passes"], "Balanced windows should pass")

    def test_dominance_check_fails_when_one_window_dominates(self):
        windows = [
            _make_window_result(1, oos_net_profit=900.0),   # 90% of profit
            _make_window_result(2, oos_net_profit=50.0),
            _make_window_result(3, oos_net_profit=50.0),
        ]
        result = check_window_dominance(windows)
        self.assertFalse(result["passes"])
        self.assertTrue(result["window_contributions"][0]["exceeds_60pct"])

    def test_dominance_check_at_exactly_60pct_passes(self):
        windows = [
            _make_window_result(1, oos_net_profit=600.0),   # exactly 60%
            _make_window_result(2, oos_net_profit=400.0),
        ]
        result = check_window_dominance(windows)
        # 60% is not > 60%, so passes
        self.assertTrue(result["passes"])

    def test_dominance_reports_all_windows(self):
        windows = [_make_window_result(i, oos_net_profit=333.0) for i in range(1, 4)]
        result = check_window_dominance(windows)
        self.assertEqual(len(result["window_contributions"]), 3)

    # ── Nearest-grid helper ───────────────────────────────────────────────────

    def test_nearest_snaps_correctly(self):
        self.assertEqual(_nearest(12, [10, 15, 20]), 10)
        self.assertEqual(_nearest(13, [10, 15, 20]), 15)
        self.assertEqual(_nearest(18, [10, 15, 20]), 20)
        self.assertAlmostEqual(_nearest(1.8, [1.5, 2.0, 2.5]), 2.0)


class TestProductionParams(unittest.TestCase):
    """YAML serialization, from_yaml_file round-trip."""

    def test_to_yaml_str_contains_all_fields(self):
        p = ProductionParams(
            orb_range_minutes=15,
            vwap_bb_std=2.0,
            ema_period=30,
            aggregation_method="MEAN",
        )
        yaml_str = p.to_yaml_str()
        self.assertIn("orb_range_minutes: 15", yaml_str)
        self.assertIn("vwap_bb_std: 2.0",      yaml_str)
        self.assertIn("ema_period: 30",         yaml_str)

    def test_yaml_round_trip(self):
        p = ProductionParams(
            orb_range_minutes=20,
            vwap_bb_std=2.5,
            ema_period=50,
            aggregation_method="MODE",
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(p.to_yaml_str())
            fname = f.name

        loaded = ProductionParams.from_yaml_file(fname)
        self.assertEqual(loaded.orb_range_minutes, 20)
        self.assertAlmostEqual(loaded.vwap_bb_std, 2.5)
        self.assertEqual(loaded.ema_period, 50)
        os.unlink(fname)

    def test_to_dict_has_all_keys(self):
        p = ProductionParams(15, 2.0, 30, "MEAN")
        d = p.to_dict()
        for key in ["orb_range_minutes", "vwap_bb_std", "ema_period", "aggregation_method"]:
            self.assertIn(key, d)


class TestWFOWindowSchedule(unittest.TestCase):
    """Window slicing: correct number, no overlap, correct boundary dates."""

    def _engine(self, start: str, end: str) -> WFOEngine:
        cfg = WFOConfig(
            full_dataset_start=start,
            full_dataset_end=end,
            universe=["AAPL"],
            train_years=3,
            test_years=1,
            log_level="WARNING",
        )
        return WFOEngine(cfg)

    def _spy(self, start: str, end: str) -> pd.DataFrame:
        return _make_spy_bars(start, end)

    def test_7year_dataset_produces_3_windows(self):
        """3yr train + 1yr test, rolling by 1yr → 3 OOS windows in 7yr dataset."""
        engine = self._engine("2018-01-02", "2024-06-30")
        spy = self._spy("2018-01-02", "2024-06-30")
        windows = engine._build_windows(spy)
        # Should have 3 full windows + possibly a partial 4th
        self.assertGreaterEqual(len(windows), 3)

    def test_test_periods_do_not_overlap(self):
        engine = self._engine("2018-01-02", "2024-06-30")
        spy = self._spy("2018-01-02", "2024-06-30")
        windows = engine._build_windows(spy)
        for i in range(len(windows) - 1):
            _, _, _, test_end_i   = windows[i]
            _, _, test_start_i1, _ = windows[i + 1]
            self.assertLess(
                test_end_i, test_start_i1,
                f"Window {i+1} test end {test_end_i} overlaps window {i+2} test start {test_start_i1}",
            )

    def test_vault_boundary_is_15pct_from_end(self):
        engine = self._engine("2018-01-02", "2024-06-30")
        spy = self._spy("2018-01-02", "2024-06-30")
        market_data = {"SPY": spy}
        boundary = engine._compute_vault_boundary(market_data)
        days = spy.index.normalize().unique()
        expected_idx = int(len(days) * 0.85)
        expected_boundary = pd.Timestamp(days[expected_idx])
        self.assertEqual(boundary, expected_boundary)

    def test_insufficient_data_raises(self):
        engine = self._engine("2023-01-02", "2023-06-30")
        spy = self._spy("2023-01-02", "2023-06-30")   # only ~6 months
        with self.assertRaises(ValueError):
            engine._build_windows(spy)

    def test_slice_before_vault_excludes_vault_data(self):
        engine = self._engine("2018-01-02", "2024-06-30")
        spy = self._spy("2018-01-02", "2024-06-30")
        market_data = {"SPY": spy}
        boundary = engine._compute_vault_boundary(market_data)
        wfo_data = engine._slice_before(market_data, boundary)
        self.assertTrue((wfo_data["SPY"].index < boundary).all())


class TestWFOEngine(unittest.TestCase):
    """
    WFO engine orchestration tests — report structure and integrity.

    BacktestEngine.run() is patched to return a deterministic fast result,
    so we test the orchestration logic (window scheduling, aggregation,
    dominance check, save/load) without running 81 real backtests.
    The actual backtest correctness is covered by TestFullBacktestRun.
    """

    START = "2018-01-02"
    END   = "2024-06-30"

    @classmethod
    def _make_mock_result(cls):
        """Minimal BacktestResult that compute_metrics can handle."""
        from unittest.mock import MagicMock
        from raits.backtest.data_types import BacktestResult, BacktestConfig
        from raits.backtest.data_types import Trade
        from raits.backtest.metrics import compute_metrics, compute_regime_breakdown
        import uuid
        from datetime import datetime

        n = 30
        idx = pd.date_range("2022-01-03", periods=n, freq="B")
        equity = pd.Series(25_000.0 + np.linspace(0, 800, n), index=idx, name="equity")

        trades = []
        for i in range(8):
            t = Trade(
                trade_id=str(uuid.uuid4())[:8],
                ticker="AAPL", strategy="ORB", direction="LONG",
                entry_time=datetime(2022, 1, 3 + i, 9, 45),
                entry_price=150.0, shares=10, stop=147.0, target=156.0,
                hmm_state="Normal", limiting_factor="VOL_TARGET",
            )
            t.exit_time   = datetime(2022, 1, 3 + i, 15, 30)
            t.exit_price  = 155.0 if i % 3 != 0 else 147.5
            t.exit_reason = "TARGET_HIT" if i % 3 != 0 else "STOP_HIT"
            t.total_costs = 2.0
            t.gross_pnl   = (t.exit_price - t.entry_price) * t.shares
            t.net_pnl     = t.gross_pnl - t.total_costs
            trades.append(t)

        metrics = compute_metrics(equity, trades)
        regime_breakdown = compute_regime_breakdown(trades)
        return BacktestResult(
            config=BacktestConfig(),
            equity_curve=equity,
            trade_log=trades,
            session_summaries=[],
            metrics=metrics,
            regime_breakdown=regime_breakdown,
        )

    @classmethod
    def setUpClass(cls):
        """Run WFO with BacktestEngine.run patched — tests orchestration only."""
        from unittest.mock import patch
        tickers = ["SPY", "AAPL", "MSFT"]
        cls.market_data = _make_market_data_wfo(tickers, cls.START, cls.END)
        cfg = WFOConfig(
            full_dataset_start=cls.START,
            full_dataset_end=cls.END,
            vault_fraction=0.15,
            train_years=3,
            test_years=1,
            universe=["AAPL", "MSFT"],
            account_equity=25_000.0,
            log_level="WARNING",
        )
        cls.engine = WFOEngine(cfg)
        with patch("raits.backtest.wfo.BacktestEngine") as MockEngine:
            MockEngine.return_value.run.return_value = cls._make_mock_result()
            cls.report = cls.engine.run(cls.market_data)

    # ── Report structure ──────────────────────────────────────────────────────

    def test_report_is_not_none(self):
        self.assertIsNotNone(self.report)

    def test_report_has_window_results(self):
        self.assertIsInstance(self.report.window_results, list)
        self.assertGreater(len(self.report.window_results), 0)

    def test_report_has_production_params(self):
        p = self.report.production_params
        self.assertIn(p.orb_range_minutes, ORB_RANGE_VALUES)
        self.assertIn(p.vwap_bb_std,       VWAP_BB_STD_VALUES)
        self.assertIn(p.ema_period,         EMA_PERIOD_VALUES)

    def test_report_has_stitched_metrics(self):
        m = self.report.stitched_metrics
        for key in ["calmar_ratio", "sharpe_ratio", "max_drawdown", "win_rate",
                    "profit_factor", "total_return", "total_trades"]:
            self.assertIn(key, m, f"Missing metric: {key}")

    def test_report_has_vault_boundary(self):
        self.assertIsNotNone(self.report.vault_boundary)
        # Should be parseable as a date
        pd.Timestamp(self.report.vault_boundary)

    def test_report_has_dominance_check(self):
        d = self.report.dominance_check
        self.assertIn("passes", d)
        self.assertIn("window_contributions", d)
        self.assertIsInstance(d["window_contributions"], list)

    def test_each_window_has_best_params_from_valid_grid(self):
        for wr in self.report.window_results:
            self.assertIn(wr.best_orb_range,  ORB_RANGE_VALUES,  f"Window {wr.window_idx}")
            self.assertIn(wr.best_bb_std,     VWAP_BB_STD_VALUES, f"Window {wr.window_idx}")
            self.assertIn(wr.best_ema_period, EMA_PERIOD_VALUES,  f"Window {wr.window_idx}")

    def test_each_window_has_train_calmar_set(self):
        """Train Calmar must be set — it's what selected the best params."""
        for wr in self.report.window_results:
            self.assertIsNotNone(wr.train_calmar, f"Window {wr.window_idx} missing train_calmar")

    def test_wfo_and_proceed_flags_are_booleans(self):
        self.assertIsInstance(self.report.wfo_passes,      bool)
        self.assertIsInstance(self.report.proceed_to_vault, bool)

    def test_proceed_implies_wfo_passes(self):
        """If proceed_to_vault is True, wfo_passes must also be True."""
        if self.report.proceed_to_vault:
            self.assertTrue(self.report.wfo_passes)

    def test_summary_string_contains_key_sections(self):
        s = self.report.summary()
        self.assertIn("Walk-Forward Optimization Report", s)
        self.assertIn("Vault boundary", s)
        self.assertIn("Production Parameters", s)
        self.assertIn("Verdict", s)

    # ── Save / load ───────────────────────────────────────────────────────────

    def test_report_saves_yaml_and_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.report.save(tmpdir)
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "final_params.yaml")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "wfo_report.json")))

    def test_saved_yaml_loads_correctly(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.report.save(tmpdir)
            loaded = ProductionParams.from_yaml_file(
                os.path.join(tmpdir, "final_params.yaml")
            )
            self.assertEqual(loaded.orb_range_minutes, self.report.production_params.orb_range_minutes)
            self.assertAlmostEqual(loaded.vwap_bb_std, self.report.production_params.vwap_bb_std)
            self.assertEqual(loaded.ema_period, self.report.production_params.ema_period)

    def test_saved_json_is_valid_and_contains_windows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.report.save(tmpdir)
            with open(os.path.join(tmpdir, "wfo_report.json")) as f:
                data = json.load(f)
            self.assertIn("windows", data)
            self.assertIn("vault_boundary", data)
            self.assertIn("production_params", data)
            self.assertGreater(len(data["windows"]), 0)


class TestWFOConsistencyChecks(unittest.TestCase):
    """
    Checks on the WFO framework itself — not on results, but on the
    mathematical properties the blueprint requires.
    """

    def test_27_grid_combinations_are_exhaustive(self):
        """Every valid combination must appear exactly once."""
        seen = set()
        for orb, std, ema in all_param_combinations():
            key = (orb, std, ema)
            self.assertNotIn(key, seen, f"Duplicate: {key}")
            seen.add(key)
        # Verify completeness
        expected = len(ORB_RANGE_VALUES) * len(VWAP_BB_STD_VALUES) * len(EMA_PERIOD_VALUES)
        self.assertEqual(len(seen), expected)

    def test_aggregated_params_always_on_valid_grid(self):
        """Regardless of window values, aggregated params must be grid-valid."""
        import random
        rng = random.Random(42)
        for _ in range(50):
            windows = [
                _make_window_result(
                    i,
                    orb=rng.choice(ORB_RANGE_VALUES),
                    std=rng.choice(VWAP_BB_STD_VALUES),
                    ema=rng.choice(EMA_PERIOD_VALUES),
                    oos_calmar=rng.uniform(0.5, 3.0),
                )
                for i in range(1, rng.randint(2, 5))
            ]
            for method in ["MEAN", "MODE", "CALMAR_WEIGHTED"]:
                params = aggregate_params(windows, method)
                self.assertIn(params.orb_range_minutes, ORB_RANGE_VALUES,
                              f"{method}: invalid ORB {params.orb_range_minutes}")
                self.assertIn(params.vwap_bb_std, VWAP_BB_STD_VALUES,
                              f"{method}: invalid std {params.vwap_bb_std}")
                self.assertIn(params.ema_period, EMA_PERIOD_VALUES,
                              f"{method}: invalid EMA {params.ema_period}")

    def test_dominance_contributions_sum_to_one(self):
        windows = [_make_window_result(i, oos_net_profit=float(100 * (i + 1))) for i in range(3)]
        result = check_window_dominance(windows)
        total_pct = sum(wc["pct_contribution"] for wc in result["window_contributions"])
        self.assertAlmostEqual(total_pct, 1.0, places=6)


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
