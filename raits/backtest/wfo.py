"""
raits/backtest/wfo.py
Walk-Forward Optimization engine -- Week 19.

Implements blueprint Section 7.2-7.4:
  - Rolling 3-year training / 1-year test windows
  - 252-bar burn-in on first window
  - 27-combination grid search on training data (optimize by Calmar)
  - Parameters frozen → OOS test run
  - Stitched equity curve from OOS periods only
  - 60% window-dominance check
  - Arithmetic-mean parameter aggregation → ProductionParams
  - Production params saved to configs/final_params.yaml

Usage:
    from raits.backtest.wfo import WFOEngine, WFOConfig
    from raits.backtest.wfo_grid import ProductionParams

    cfg = WFOConfig(
        full_dataset_start="2018-01-02",
        full_dataset_end="2024-06-30",
        vault_fraction=0.15,
    )
    engine = WFOEngine(cfg)
    report = engine.run(market_data)        # market_data: Dict[ticker → DataFrame]
    print(report.summary())
    report.save("configs/")
"""

from __future__ import annotations
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .data_types import BacktestConfig, BacktestResult
from .engine import BacktestEngine
from .metrics import compute_metrics, compute_r_squared, check_vault_tier
from .wfo_grid import (
    WindowResult,
    ProductionParams,
    all_param_combinations,
    aggregate_params,
    check_window_dominance,
    ORB_RANGE_VALUES,
    VWAP_BB_STD_VALUES,
    EMA_PERIOD_VALUES,
)

logger = logging.getLogger("RAITS.wfo")


# ── WFO configuration ─────────────────────────────────────────────────────────

@dataclass
class WFOConfig:
    """
    All settings that control the WFO run.
    These are fixed per blueprint Section 7.2 and must not be changed
    after the first WFO window has been run.
    """
    full_dataset_start: str = "2018-01-02"
    full_dataset_end:   str = "2024-06-30"
    vault_fraction:     float = 0.15       # 15% held out (Section 7.5)

    # Window sizes (blueprint-specified, not optimized)
    train_years: float = 3
    test_years:  float = 1
    burn_in_days: int = 252    # first year of first window excluded

    # Universe
    universe: List[str] = field(
        default_factory=lambda: ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
    )
    orb_universe: List[str] = field(default_factory=list)
    account_equity: float = 25_000.0

    # Grid search
    optimize_metric: str = "calmar_ratio"   # always Calmar per blueprint
    aggregation_method: str = "MEAN"        # MEAN | MODE | CALMAR_WEIGHTED

    # Engine flags
    enable_costs:     bool = True
    enable_pdt_guard: bool = True
    log_level:        str  = "WARNING"      # suppress verbose logs during grid search


# ── WFO report ────────────────────────────────────────────────────────────────

@dataclass
class WFOReport:
    """Complete output from one WFO run."""
    config:             WFOConfig
    window_results:     List[WindowResult]
    production_params:  ProductionParams
    stitched_metrics:   Dict[str, Any]
    dominance_check:    Dict[str, Any]
    vault_boundary:     str            # ISO date — data on/after this is Vault
    spy_r_squared:      Optional[float]

    # Derived convenience fields
    wfo_passes:         bool = False   # True if stitched metrics meet Section 8.1 targets
    proceed_to_vault:   bool = False   # True if WFO passes AND no red flags

    def summary(self) -> str:
        m = self.stitched_metrics
        lines = [
            "=" * 70,
            "RAITS Walk-Forward Optimization Report",
            f"  Dataset:        {self.config.full_dataset_start} -> {self.config.full_dataset_end}",
            f"  Vault boundary: {self.vault_boundary} (15% held out)",
            f"  Windows run:    {len(self.window_results)}",
            "",
            "-- Stitched OOS Performance (all windows combined) --------------",
            f"  Calmar ratio:   {m.get('calmar_ratio',0):.2f}  (target >2.0)",
            f"  Profit factor:  {m.get('profit_factor',0):.2f}  (target >1.75)",
            f"  Max drawdown:   {m.get('max_drawdown',0):.1%}  (target <15%)",
            f"  Sharpe ratio:   {m.get('sharpe_ratio',0):.2f}  (target >1.5)",
            f"  Win rate:       {m.get('win_rate',0):.1%}  (target >40%)",
            f"  Total return:   {m.get('total_return',0):.1%}",
            f"  Total trades:   {m.get('total_trades',0)}",
            f"  Total costs:    ${m.get('total_costs',0):.2f}",
            f"  R² vs SPY:      {self.spy_r_squared:.3f}  (target <0.4)"
                if self.spy_r_squared is not None else "  R² vs SPY:      N/A",
            "",
            "-- Window Dominance Check ---------------------------------------",
        ]
        for wc in self.dominance_check.get("window_contributions", []):
            flag = " ⚠️  >60% — UNSTABLE" if wc["exceeds_60pct"] else ""
            lines.append(
                f"  Window {wc['window']}: {wc['pct_contribution']:.1%} of profit"
                f"  (${wc['net_profit']:.0f}){flag}"
            )
        lines += [
            f"  Dominance check: {'PASS [OK]' if self.dominance_check['passes'] else 'FAIL [FAIL]'}",
            "",
            "-- Production Parameters (locked for Vault) ---------------------",
            f"  ORB range:      {self.production_params.orb_range_minutes} min",
            f"  VWAP BB std:    {self.production_params.vwap_bb_std} sigma",
            f"  EMA period:     {self.production_params.ema_period} bars",
            f"  Method:         {self.production_params.aggregation_method}",
            "",
            f"-- Verdict ------------------------------------------------------",
            f"  WFO targets met:    {'YES [OK]' if self.wfo_passes else 'NO [FAIL]'}",
            f"  Proceed to Vault:   {'YES [OK]' if self.proceed_to_vault else 'NO -- fix issues first [FAIL]'}",
            "=" * 70,
        ]
        return "\n".join(lines)

    def save(self, output_dir: str = "configs") -> None:
        """Save production params (YAML) and full report (JSON)."""
        os.makedirs(output_dir, exist_ok=True)

        # Production params → YAML (used by Vault runner)
        yaml_path = os.path.join(output_dir, "final_params.yaml")
        with open(yaml_path, "w") as f:
            f.write(self.production_params.to_yaml_str())
        logger.info(f"Production params saved -> {yaml_path}")

        # Full report → JSON (audit trail)
        report_path = os.path.join(output_dir, "wfo_report.json")
        report_dict = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "vault_boundary": self.vault_boundary,
            "wfo_passes": self.wfo_passes,
            "proceed_to_vault": self.proceed_to_vault,
            "stitched_metrics": self.stitched_metrics,
            "dominance_check": self.dominance_check,
            "production_params": asdict(self.production_params),
            "spy_r_squared": self.spy_r_squared,
            "windows": [asdict(w) for w in self.window_results],
        }
        with open(report_path, "w") as f:
            json.dump(report_dict, f, indent=2, default=str)
        logger.info(f"WFO report saved -> {report_path}")


# ── WFO Engine ────────────────────────────────────────────────────────────────

class WFOEngine:
    """
    Week 19: Walk-Forward Optimization engine.

    Orchestrates the full WFO process per blueprint Sections 7.1-7.4:

      1. Carve out Vault data (15%) — never touched here
      2. Build rolling training/test windows
      3. For each window:
         a. Grid search 27 param combos on training data → pick best by Calmar
         b. Freeze params, run OOS test on test data
         c. Record WindowResult
      4. Stitch OOS equity curves
      5. Check 60% window dominance
      6. Aggregate production params (arithmetic mean by default)
      7. Compute composite metrics on stitched curve
      8. Produce WFOReport
    """

    # WFO target thresholds (Section 8.1) — aspirational, not Vault survival thresholds
    WFO_TARGETS = {
        "calmar_ratio":   2.0,
        "profit_factor":  1.75,
        "max_drawdown":  -0.15,   # more negative = worse
        "sharpe_ratio":   1.5,
        "win_rate":       0.40,
    }

    def __init__(self, config: WFOConfig):
        self.cfg = config
        logging.basicConfig(
            level=getattr(logging, config.log_level, logging.WARNING),
            format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, market_data: Dict[str, pd.DataFrame]) -> WFOReport:
        """
        Execute the full WFO run.

        Args:
            market_data: Dict[ticker → 5-min OHLCV DataFrame].
                         Must include 'SPY'. Index must be DatetimeIndex.

        Returns:
            WFOReport with production params and all window metrics.
        """
        logger.warning("=" * 60)
        logger.warning("WFO ENGINE STARTING")
        logger.warning(f"Dataset: {self.cfg.full_dataset_start} -> {self.cfg.full_dataset_end}")
        logger.warning(f"Vault fraction: {self.cfg.vault_fraction:.0%}")
        logger.warning("=" * 60)

        # ── Step 1: carve Vault boundary ──────────────────────────────────────
        vault_boundary = self._compute_vault_boundary(market_data)
        logger.warning(f"Vault boundary: {vault_boundary} (data from here onward is LOCKED)")

        # WFO only uses data BEFORE the vault boundary
        wfo_data = self._slice_before(market_data, vault_boundary)
        spy_wfo = wfo_data.get("SPY", pd.DataFrame())

        # ── Step 2: build window schedule ─────────────────────────────────────
        windows = self._build_windows(spy_wfo)
        logger.warning(f"WFO windows scheduled: {len(windows)}")
        for i, (ts, te, oos_s, oos_e) in enumerate(windows):
            logger.warning(f"  Window {i+1}: train {ts.date()}->{te.date()}  test {oos_s.date()}->{oos_e.date()}")

        # ── Step 3: run each window ───────────────────────────────────────────
        window_results: List[WindowResult] = []
        for idx, (train_s, train_e, test_s, test_e) in enumerate(windows, start=1):
            logger.warning(f"\n-- Window {idx}/{len(windows)} --------------")
            result = self._run_window(
                window_idx=idx,
                train_start=train_s,
                train_end=train_e,
                test_start=test_s,
                test_end=test_e,
                market_data=wfo_data,
            )
            window_results.append(result)
            logger.warning(
                f"Window {idx} OOS: Calmar={result.oos_calmar:.2f}  "
                f"Sharpe={result.oos_sharpe:.2f}  MaxDD={result.oos_max_dd:.1%}  "
                f"PF={result.oos_profit_factor:.2f}  Params={result.best_params()}"
            )

        # ── Step 4: stitch OOS equity curves ──────────────────────────────────
        stitched_curve = self._stitch_oos_curves(window_results, wfo_data)

        # ── Step 5: compute stitched metrics ──────────────────────────────────
        all_oos_trades = self._collect_oos_trades(window_results, wfo_data)
        stitched_metrics = compute_metrics(stitched_curve, all_oos_trades)

        # R² vs SPY on stitched curve
        spy_r2 = self._compute_spy_r2(stitched_curve, spy_wfo)
        stitched_metrics["r_squared_spy"] = spy_r2

        # ── Step 6: 60% dominance check ───────────────────────────────────────
        dominance = check_window_dominance(window_results)

        # ── Step 7: aggregate production params ───────────────────────────────
        production_params = aggregate_params(window_results, self.cfg.aggregation_method)
        logger.warning(f"\nProduction params ({self.cfg.aggregation_method}): {asdict(production_params)}")

        # ── Step 8: verdict ───────────────────────────────────────────────────
        wfo_passes = self._check_wfo_targets(stitched_metrics)
        proceed = wfo_passes and dominance["passes"]

        if not wfo_passes:
            logger.warning(
                "⚠️  WFO targets not met. DO NOT run Vault test. "
                "Re-evaluate strategy logic first."
            )
        elif not dominance["passes"]:
            logger.warning(
                "⚠️  Window dominance check failed. Strategy is unstable. "
                "DO NOT run Vault test."
            )
        else:
            logger.warning("[OK]  WFO targets met. Dominance check passed. Ready for cooling-off period.")

        return WFOReport(
            config=self.cfg,
            window_results=window_results,
            production_params=production_params,
            stitched_metrics=stitched_metrics,
            dominance_check=dominance,
            vault_boundary=str(vault_boundary.date()),
            spy_r_squared=spy_r2,
            wfo_passes=wfo_passes,
            proceed_to_vault=proceed,
        )

    # ── Window execution ──────────────────────────────────────────────────────

    def _run_window(
        self,
        window_idx: int,
        train_start: pd.Timestamp,
        train_end: pd.Timestamp,
        test_start: pd.Timestamp,
        test_end: pd.Timestamp,
        market_data: Dict[str, pd.DataFrame],
    ) -> WindowResult:
        """Grid-search on training data, then OOS test with best params."""

        train_data = self._slice(market_data, train_start, train_end)
        test_data  = self._slice(market_data, test_start,  test_end)

        # ── Grid search on training data ──────────────────────────────────────
        best_calmar = -999.0
        best_combo: Tuple[int, float, int] = (15, 2.0, 30)   # sensible default

        combos = all_param_combinations()
        logger.warning(f"  Grid search: {len(combos)} combinations on train data...")
        t0 = time.time()

        for combo_idx, (orb_min, bb_std, ema_per) in enumerate(combos):
            try:
                cfg = self._make_config(
                    start=str(train_start.date()),
                    end=str(train_end.date()),
                    orb=orb_min, std=bb_std, ema=ema_per,
                )
                result = BacktestEngine(cfg).run(train_data)
                calmar = result.metrics.get("calmar_ratio", -999.0)
                if calmar > best_calmar:
                    best_calmar = calmar
                    best_combo = (orb_min, bb_std, ema_per)
            except Exception as e:
                logger.warning(f"    Combo {combo_idx+1} failed: {type(e).__name__}: {e}")
                continue

        elapsed = time.time() - t0
        logger.warning(
            f"  Grid search done in {elapsed:.1f}s  "
            f"Best: ORB={best_combo[0]}min BB={best_combo[1]}sigma EMA={best_combo[2]}  "
            f"Train Calmar={best_calmar:.2f}"
        )

        # ── OOS test with frozen params ───────────────────────────────────────
        oos_cfg = self._make_config(
            start=str(test_start.date()),
            end=str(test_end.date()),
            orb=best_combo[0], std=best_combo[1], ema=best_combo[2],
        )
        oos_result = BacktestEngine(oos_cfg).run(test_data)
        m = oos_result.metrics

        # Net profit for dominance check ($ delta on equity curve)
        eq = oos_result.equity_curve
        net_profit = float(eq.iloc[-1] - eq.iloc[0]) if not eq.empty else 0.0

        return WindowResult(
            window_idx=window_idx,
            train_start=str(train_start.date()),
            train_end=str(train_end.date()),
            test_start=str(test_start.date()),
            test_end=str(test_end.date()),
            best_orb_range=best_combo[0],
            best_bb_std=best_combo[1],
            best_ema_period=best_combo[2],
            train_calmar=best_calmar,
            oos_calmar=m.get("calmar_ratio", 0.0),
            oos_sharpe=m.get("sharpe_ratio", 0.0),
            oos_max_dd=m.get("max_drawdown", 0.0),
            oos_profit_factor=m.get("profit_factor", 0.0),
            oos_win_rate=m.get("win_rate", 0.0),
            oos_total_return=m.get("total_return", 0.0),
            oos_total_trades=m.get("total_trades", 0),
            oos_net_profit=net_profit,
        )

    # ── Stitching ─────────────────────────────────────────────────────────────

    def _stitch_oos_curves(
        self,
        window_results: List[WindowResult],
        market_data: Dict[str, pd.DataFrame],
    ) -> pd.Series:
        """
        Re-run each OOS window with its best params and concatenate the
        equity curves into one continuous series.
        Training-period results are completely discarded.
        """
        curves: List[pd.Series] = []
        running_equity = self.cfg.account_equity

        for wr in window_results:
            test_data = self._slice(
                market_data,
                pd.Timestamp(wr.test_start),
                pd.Timestamp(wr.test_end),
            )
            cfg = self._make_config(
                start=wr.test_start, end=wr.test_end,
                orb=wr.best_orb_range, std=wr.best_bb_std, ema=wr.best_ema_period,
                account_equity=running_equity,
            )
            result = BacktestEngine(cfg).run(test_data)
            curve = result.equity_curve
            if not curve.empty:
                curves.append(curve)
                running_equity = float(curve.iloc[-1])   # carry forward equity

        if not curves:
            return pd.Series(dtype=float, name="equity")

        stitched = pd.concat(curves)
        stitched = stitched[~stitched.index.duplicated(keep="last")]
        return stitched.sort_index()

    def _collect_oos_trades(
        self,
        window_results: List[WindowResult],
        market_data: Dict[str, pd.DataFrame],
    ) -> list:
        """Re-run each OOS window and collect all trades for composite metrics."""
        all_trades = []
        for wr in window_results:
            test_data = self._slice(
                market_data,
                pd.Timestamp(wr.test_start),
                pd.Timestamp(wr.test_end),
            )
            cfg = self._make_config(
                start=wr.test_start, end=wr.test_end,
                orb=wr.best_orb_range, std=wr.best_bb_std, ema=wr.best_ema_period,
            )
            result = BacktestEngine(cfg).run(test_data)
            all_trades.extend(result.trade_log)
        return all_trades

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _compute_vault_boundary(self, market_data: Dict[str, pd.DataFrame]) -> pd.Timestamp:
        """Return the Timestamp where Vault data begins (15% from the end)."""
        spy = market_data.get("SPY", pd.DataFrame())
        if spy.empty:
            raise ValueError("SPY data required to compute vault boundary")
        days = spy.index.normalize().unique().sort_values()
        vault_start_idx = int(len(days) * (1 - self.cfg.vault_fraction))
        return pd.Timestamp(days[vault_start_idx])

    def _build_windows(
        self, spy_data: pd.DataFrame
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
        """
        Build rolling (train_start, train_end, test_start, test_end) tuples.
        Blueprint: 3-year train, 1-year test, rolling by 1 year.
        Window 0 is burn-in only (252 days, no OOS test) — skipped here,
        the engine handles burn-in internally via the HMM warm-up.
        """
        days = spy_data.index.normalize().unique().sort_values()
        trading_year = 252
        train_days = max(int(self.cfg.train_years * trading_year), 5)
        test_days  = max(int(self.cfg.test_years  * trading_year), 3)

        if len(days) < train_days + test_days:
            raise ValueError(
                f"Insufficient data for WFO. Need >="
                f"{train_days + test_days} trading days, "
                f"got {len(days)}."
            )

        windows = []
        offset = 0
        while True:
            train_start_idx = offset
            train_end_idx   = offset + train_days - 1
            test_start_idx  = train_end_idx + 1
            test_end_idx    = test_start_idx + test_days - 1

            if test_end_idx >= len(days):
                # Partial final test window — include if at least 63 trading days
                if test_start_idx < len(days):
                    test_end_idx = len(days) - 1
                    if (test_end_idx - test_start_idx) >= 63:
                        windows.append((
                            pd.Timestamp(days[train_start_idx]),
                            pd.Timestamp(days[train_end_idx]),
                            pd.Timestamp(days[test_start_idx]),
                            pd.Timestamp(days[test_end_idx]),
                        ))
                break

            windows.append((
                pd.Timestamp(days[train_start_idx]),
                pd.Timestamp(days[train_end_idx]),
                pd.Timestamp(days[test_start_idx]),
                pd.Timestamp(days[test_end_idx]),
            ))
            offset += test_days    # slide by 1 year (rolling windows per blueprint)

        return windows

    def _slice(
        self,
        market_data: Dict[str, pd.DataFrame],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> Dict[str, pd.DataFrame]:
        result = {}
        for ticker, df in market_data.items():
            sliced = df[(df.index >= start) & (df.index <= end + pd.Timedelta("1D"))]
            if not sliced.empty:
                result[ticker] = sliced
        return result

    def _slice_before(
        self,
        market_data: Dict[str, pd.DataFrame],
        boundary: pd.Timestamp,
    ) -> Dict[str, pd.DataFrame]:
        return {
            ticker: df[df.index < boundary]
            for ticker, df in market_data.items()
            if not df[df.index < boundary].empty
        }

    def _make_config(
        self,
        start: str,
        end: str,
        orb: int,
        std: float,
        ema: int,
        account_equity: float = None,
    ) -> BacktestConfig:
        return BacktestConfig(
            account_equity=account_equity or self.cfg.account_equity,
            start_date=start,
            end_date=end,
            universe=self.cfg.universe,
            orb_universe=self.cfg.orb_universe,
            orb_range_minutes=orb,
            vwap_bb_std=std,
            ema_period=ema,
            enable_costs=self.cfg.enable_costs,
            enable_pdt_guard=self.cfg.enable_pdt_guard,
            log_level=self.cfg.log_level,
        )

    def _check_wfo_targets(self, metrics: Dict[str, Any]) -> bool:
        """Return True if stitched metrics meet all Section 8.1 aspirational targets."""
        return (
            metrics.get("calmar_ratio",  0)  >= self.WFO_TARGETS["calmar_ratio"]
            and metrics.get("profit_factor", 0) >= self.WFO_TARGETS["profit_factor"]
            and metrics.get("max_drawdown",  0) >= self.WFO_TARGETS["max_drawdown"]
            and metrics.get("sharpe_ratio",  0) >= self.WFO_TARGETS["sharpe_ratio"]
            and metrics.get("win_rate",      0) >= self.WFO_TARGETS["win_rate"]
        )

    def _compute_spy_r2(
        self,
        stitched_curve: pd.Series,
        spy_data: pd.DataFrame,
    ) -> Optional[float]:
        """Compute R² between daily portfolio returns and SPY returns."""
        try:
            if stitched_curve.empty or spy_data.empty:
                return None
            daily_equity  = stitched_curve.resample("B").last().dropna()
            port_returns  = daily_equity.pct_change().dropna()
            spy_daily     = spy_data["close"].resample("B").last().dropna()
            spy_returns   = spy_daily.pct_change().dropna()
            return compute_r_squared(port_returns, spy_returns)
        except Exception as e:
            logger.debug(f"R² computation failed: {e}")
            return None
