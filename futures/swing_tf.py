"""
futures/swing_tf.py — swing TREND_FOLLOW engine (production wrapper, GĐ0)
========================================================================
Approach (a): wrap the VALIDATED backtest_swing_tf so production == validated
numbers BY CONSTRUCTION (identical code path). Gives the runner/sizer a clean
class interface. Reconcile is automatic; reconcile_gd0.py documents it and
catches future drift.

Dependency: futures._validated_core (internalized validated logic) + raits.*
(raits.hmm for regimes, raits.strategies.trend_follow for entry). No root scripts.
"""
from __future__ import annotations
from dataclasses import dataclass

from futures.basket import BASKET, SWING_TF_PARAM, REGIME, data_filename
from futures.cost import FuturesCost


@dataclass
class SwingTFEngine:
    """Swing trend-follow engine for one or more instruments. Stateless backtest
    wrappers now; live position-state interface lands in GĐ4 (runner + IBKR)."""
    ema_period: int = SWING_TF_PARAM["ema_period"]
    chandelier_atr_mult: float = SWING_TF_PARAM["chandelier_atr_mult"]
    max_hold_days: int = SWING_TF_PARAM["max_hold_days"]

    # ── validated backtest (single instrument) ────────────────────────────────
    def backtest(self, df, labels, cost, *, entry_days=None, gap_fill=True):
        """Run the validated swing backtest for ONE instrument → list of trade dicts.
        Reuses backtest_swing_tf — the exact code that produced WFO 2.31 / vault 3.21."""
        from futures._validated_core import backtest_swing_tf
        return backtest_swing_tf(
            df, labels, cost,
            ema_period=self.ema_period,
            chandelier_atr_mult=self.chandelier_atr_mult,
            max_hold_days=self.max_hold_days,
            entry_days=entry_days, gap_fill=gap_fill)

    # ── validated backtest (basket) ───────────────────────────────────────────
    def backtest_basket(self, dfs: dict, labels, costs: dict, *, gap_fill=True):
        """dfs / costs: dict instrument -> df / FuturesCost.
        Returns dict instrument -> list of trade dicts."""
        return {name: self.backtest(dfs[name], labels, costs[name], gap_fill=gap_fill)
                for name in dfs}

    # ── live signal: the position the engine WANTS to hold right now ───────────
    def desired_position(self, df, labels, cost):
        """Run the validated backtest on data-through-now and return the OPEN
        position at the end (the live target). Live runner reconciles the broker
        to this → live == backtest by construction. Returns dict or None:
        {direction, entry, stop, entry_day}."""
        from futures._validated_core import backtest_swing_tf
        _, pos = backtest_swing_tf(
            df, labels, cost,
            ema_period=self.ema_period,
            chandelier_atr_mult=self.chandelier_atr_mult,
            max_hold_days=self.max_hold_days, return_open=True)
        if pos is None:
            return None
        return dict(direction=pos["dir"], entry=float(pos["entry"]),
                    stop=float(pos["stop"]), entry_day=pos["entry_day"])

    def desired_basket(self, dfs: dict, labels, costs: dict):
        """dict instrument -> desired_position (or None) across the basket."""
        return {name: self.desired_position(dfs[name], labels, costs[name]) for name in dfs}


def costs_for_basket(slippage_ticks: float = 1.0) -> dict:
    """FuturesCost per basket instrument, using exchange tick specs from basket.py."""
    return {name: FuturesCost(point_value=c.point_value, tick=c.tick,
                              slippage_ticks_per_side=slippage_ticks)
            for name, c in BASKET.items()}


def load_basket(data_dir: str, vault_start: str | None = None):
    """Load each basket instrument's parquet. Returns dict instrument -> DataFrame.
    If vault_start given, keeps only bars BEFORE it (WFO region)."""
    from futures._validated_core import load_parquet
    import pandas as pd
    from pathlib import Path
    dfs = {}
    for name, c in BASKET.items():
        df = load_parquet(str(Path(data_dir) / data_filename(c)))
        if vault_start:
            vs = pd.Timestamp(vault_start)
            df = df[df.index < vs.tz_localize(df.index.tz)]
        dfs[name] = df
    return dfs


def basket_labels(regime_csv: str, hmm_train_end: str = "2018-01-01",
                  vault_cut: str | None = None):
    """Regime labels via the VALIDATED path (label_regimes / raw HMM, SPY-based)."""
    from futures._validated_core import benchmark_daily, label_regimes
    import pandas as pd
    daily = benchmark_daily(regime_csv)
    if vault_cut:
        daily = daily[daily.index < pd.Timestamp(vault_cut)]
    return label_regimes(daily, hmm_train_end, REGIME["n_components"], REGIME["hmm_fit_end"])
