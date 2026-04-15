"""
raits/backtest/wfo_grid.py
Parameter grid definition and aggregation for Walk-Forward Optimization.

Blueprint Section 7.1: exactly 3 hyperparameters, 3 values each → 27 combinations.
All other parameters are fixed (never optimized).

Aggregation (Section 7.3):
  Method A — arithmetic mean (default, recommended)
  Method B — mode (most frequent value)
  Method C — Calmar-weighted mean (advanced)
"""

from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from itertools import product
from statistics import mode as stat_mode
from typing import List, Tuple


# ── The 27-combination grid (Section 7.1) ─────────────────────────────────────

ORB_RANGE_VALUES:  List[int]   = [10, 15, 20]       # minutes
VWAP_BB_STD_VALUES: List[float] = [1.5, 2.0, 2.5]   # σ
EMA_PERIOD_VALUES:  List[int]   = [20, 30, 50]       # bars (5-min chart)


def all_param_combinations() -> List[Tuple[int, float, int]]:
    """Return all 27 (orb_range, bb_std, ema_period) combinations."""
    combos = list(product(ORB_RANGE_VALUES, VWAP_BB_STD_VALUES, EMA_PERIOD_VALUES))
    assert len(combos) == 27, f"Expected 27 combinations, got {len(combos)}"
    return combos


# ── Per-window result ──────────────────────────────────────────────────────────

@dataclass
class WindowResult:
    """Stores the output of one WFO window (train → test)."""
    window_idx:      int
    train_start:     str
    train_end:       str
    test_start:      str
    test_end:        str

    # Best params found on training data
    best_orb_range:  int
    best_bb_std:     float
    best_ema_period: int
    train_calmar:    float    # Calmar that selected these params

    # OOS performance (on test data with frozen params)
    oos_calmar:      float
    oos_sharpe:      float
    oos_max_dd:      float
    oos_profit_factor: float
    oos_win_rate:    float
    oos_total_return: float
    oos_total_trades: int
    oos_net_profit:  float    # absolute $, for 60% dominance check

    def best_params(self) -> Tuple[int, float, int]:
        return (self.best_orb_range, self.best_bb_std, self.best_ema_period)


# ── Production parameter aggregation ──────────────────────────────────────────

@dataclass
class ProductionParams:
    """
    Final locked parameters for Vault test and live deployment.
    Produced by aggregating window results per Section 7.3.
    """
    orb_range_minutes: int
    vwap_bb_std:       float
    ema_period:        int
    aggregation_method: str   # MEAN | MODE | CALMAR_WEIGHTED

    def to_dict(self) -> dict:
        return asdict(self)

    def to_yaml_str(self) -> str:
        return (
            f"# RAITS Production Parameters — locked for Vault test\n"
            f"# Aggregation method: {self.aggregation_method}\n"
            f"# DO NOT MODIFY after Vault test begins\n"
            f"orb_range_minutes: {self.orb_range_minutes}\n"
            f"vwap_bb_std: {self.vwap_bb_std}\n"
            f"ema_period: {self.ema_period}\n"
        )

    @classmethod
    def from_yaml_file(cls, path: str) -> "ProductionParams":
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(
            orb_range_minutes=int(data["orb_range_minutes"]),
            vwap_bb_std=float(data["vwap_bb_std"]),
            ema_period=int(data["ema_period"]),
            aggregation_method=data.get("aggregation_method", "MEAN"),
        )


def aggregate_params(
    window_results: List[WindowResult],
    method: str = "MEAN",
) -> ProductionParams:
    """
    Aggregate best-params from each WFO window into production values.

    Method A (MEAN):  arithmetic mean, rounded to nearest valid grid value.
    Method B (MODE):  most frequent value across windows.
    Method C (CALMAR_WEIGHTED): weight each window's params by its OOS Calmar.

    Blueprint recommendation: use MEAN unless parameters show clear clustering.
    """
    if not window_results:
        raise ValueError("No window results to aggregate")

    orbs  = [r.best_orb_range  for r in window_results]
    stds  = [r.best_bb_std     for r in window_results]
    emas  = [r.best_ema_period for r in window_results]

    if method == "MEAN":
        raw_orb = sum(orbs) / len(orbs)
        raw_std = sum(stds) / len(stds)
        raw_ema = sum(emas) / len(emas)
        # Snap to nearest valid grid value
        final_orb = _nearest(int(round(raw_orb)), ORB_RANGE_VALUES)
        final_std = _nearest(round(raw_std, 1),    VWAP_BB_STD_VALUES)
        final_ema = _nearest(int(round(raw_ema)),  EMA_PERIOD_VALUES)

    elif method == "MODE":
        final_orb = stat_mode(orbs)
        final_std = stat_mode(stds)
        final_ema = stat_mode(emas)

    elif method == "CALMAR_WEIGHTED":
        weights = [max(r.oos_calmar, 0.01) for r in window_results]
        total_w = sum(weights)
        final_orb = _nearest(
            int(round(sum(o * w for o, w in zip(orbs, weights)) / total_w)),
            ORB_RANGE_VALUES,
        )
        final_std = _nearest(
            round(sum(s * w for s, w in zip(stds, weights)) / total_w, 1),
            VWAP_BB_STD_VALUES,
        )
        final_ema = _nearest(
            int(round(sum(e * w for e, w in zip(emas, weights)) / total_w)),
            EMA_PERIOD_VALUES,
        )
    else:
        raise ValueError(f"Unknown aggregation method: {method!r}")

    return ProductionParams(
        orb_range_minutes=final_orb,
        vwap_bb_std=final_std,
        ema_period=final_ema,
        aggregation_method=method,
    )


def check_window_dominance(window_results: List[WindowResult]) -> dict:
    """
    Blueprint Section 7.4: no single OOS window should contribute >60% of
    total profit. Returns a dict with pct_contribution per window and
    a 'passes' boolean.
    """
    profits = [r.oos_net_profit for r in window_results]
    total   = sum(profits)

    result = {"passes": True, "window_contributions": [], "total_profit": total}

    for i, (r, p) in enumerate(zip(window_results, profits)):
        pct = p / total if total != 0 else 0.0
        result["window_contributions"].append({
            "window": r.window_idx,
            "net_profit": p,
            "pct_contribution": pct,
            "exceeds_60pct": pct > 0.60,
        })
        if pct > 0.60:
            result["passes"] = False

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nearest(value, grid: list):
    """Snap value to nearest element in the valid grid."""
    return min(grid, key=lambda g: abs(g - value))
