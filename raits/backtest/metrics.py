"""
raits/backtest/metrics.py
Computes all blueprint Section 8.1 / 8.2 performance metrics from
an equity curve and a trade log.

All metrics are computed after full transaction costs (net P&L only).
Designed to be called at the end of each WFO window and on Vault results.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from .data_types import Trade


# ── Public API ────────────────────────────────────────────────────────────────

def compute_metrics(
    equity_curve: pd.Series,
    trades: List[Trade],
    *,
    trading_days_per_year: int = 252,
) -> Dict[str, Any]:
    """
    Compute the full metric set required by blueprint Sections 8.1 and 8.2.

    Args:
        equity_curve: pd.Series with DatetimeIndex, values = account equity
        trades:       full trade log (open + closed; open trades are excluded)

    Returns:
        dict with all metrics. Keys match blueprint column names exactly so
        they can be compared directly against Tier 1/2/3 thresholds.
    """
    closed = [t for t in trades if not t.is_open and t.net_pnl is not None]

    if equity_curve.empty or len(closed) == 0:
        return _empty_metrics()

    # ── Trade-level stats ─────────────────────────────────────────────────────
    total_trades = len(closed)
    wins   = [t for t in closed if t.net_pnl > 0]   # type: ignore[operator]
    losses = [t for t in closed if t.net_pnl <= 0]  # type: ignore[operator]

    win_rate     = len(wins) / total_trades
    gross_profit = sum(t.net_pnl for t in wins)      # type: ignore[arg-type]
    gross_loss   = abs(sum(t.net_pnl for t in losses))  # type: ignore[arg-type]
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_win  = gross_profit / len(wins)   if wins   else 0.0
    avg_loss = gross_loss  / len(losses)  if losses else 0.0
    total_costs = sum(t.total_costs for t in closed if t.total_costs)  # type: ignore[misc]

    # ── Drawdown ──────────────────────────────────────────────────────────────
    rolling_max   = equity_curve.cummax()
    dd_series     = (equity_curve - rolling_max) / rolling_max   # always ≤ 0
    max_drawdown  = float(dd_series.min())                        # most negative value
    max_dd_end    = dd_series.idxmin()

    # Recovery time: bars from max DD trough until equity recovers the peak
    recovery_bars: Optional[int] = None
    recovery_days: Optional[int] = None
    if max_dd_end is not None:
        peak_value = rolling_max[max_dd_end]
        post_trough = equity_curve[max_dd_end:]
        recovered = post_trough[post_trough >= peak_value]
        if not recovered.empty:
            recovery_days = (recovered.index[0] - max_dd_end).days

    # ── Returns & annualization ───────────────────────────────────────────────
    initial = float(equity_curve.iloc[0])
    final   = float(equity_curve.iloc[-1])
    total_return = (final - initial) / initial

    span_days = max((equity_curve.index[-1] - equity_curve.index[0]).days, 1)
    annual_return = (1 + total_return) ** (365.25 / span_days) - 1

    # Calmar: annualized return / absolute max drawdown
    calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else float("inf")

    # ── Sharpe ───────────────────────────────────────────────────────────────
    # Use daily equity snapshots (resample to business day end)
    daily_equity  = equity_curve.resample("B").last().dropna()
    daily_returns = daily_equity.pct_change().dropna()
    sharpe = (
        daily_returns.mean() / daily_returns.std() * np.sqrt(trading_days_per_year)
        if len(daily_returns) > 1 and daily_returns.std() > 0
        else 0.0
    )

    # ── Tail risk (99th pct worst single day) ─────────────────────────────────
    tail_risk = float(daily_returns.quantile(0.01)) if len(daily_returns) > 0 else 0.0

    # ── R² vs SPY (placeholder — populated when SPY data is passed in WFO) ───
    # In Week 18 (integration test) we don't yet have SPY returns aligned to
    # trades. The WFO engine in Week 19 will supply spy_returns and call
    # compute_r_squared() separately.
    r_squared = None

    return {
        # Trade stats
        "total_trades":   total_trades,
        "win_rate":       win_rate,
        "profit_factor":  profit_factor,
        "avg_win":        avg_win,
        "avg_loss":       avg_loss,
        "gross_profit":   gross_profit,
        "gross_loss":     gross_loss,
        "total_costs":    total_costs,

        # Risk-adjusted returns
        "calmar_ratio":   calmar,
        "sharpe_ratio":   sharpe,
        "profit_factor":  profit_factor,

        # Drawdown
        "max_drawdown":   max_drawdown,      # fraction, e.g. -0.12
        "recovery_days":  recovery_days,     # None if still in DD

        # Returns
        "total_return":   total_return,
        "annual_return":  annual_return,

        # Tail risk
        "tail_risk_99":   tail_risk,

        # To be computed externally
        "r_squared_spy":  r_squared,
    }


def compute_regime_breakdown(trades: List[Trade]) -> Dict[str, Dict[str, Any]]:
    """
    Per-HMM-state performance metrics.
    Blueprint pre-Vault check: no single state should contribute >70% of profit.
    """
    closed = [t for t in trades if not t.is_open and t.net_pnl is not None]
    states = ["Calm", "Normal", "Stress"]
    total_profit = sum(t.net_pnl for t in closed if t.net_pnl and t.net_pnl > 0)  # type: ignore[misc]

    breakdown: Dict[str, Dict[str, Any]] = {}
    for state in states:
        state_trades = [t for t in closed if t.hmm_state == state]
        if not state_trades:
            breakdown[state] = {"trade_count": 0, "pct_of_profit": 0.0}
            continue

        wins = [t for t in state_trades if t.net_pnl and t.net_pnl > 0]
        state_profit = sum(t.net_pnl for t in state_trades if t.net_pnl and t.net_pnl > 0)  # type: ignore[misc]

        breakdown[state] = {
            "trade_count":    len(state_trades),
            "win_rate":       len(wins) / len(state_trades),
            "total_net_pnl":  sum(t.net_pnl for t in state_trades),  # type: ignore[misc]
            "pct_of_profit":  state_profit / total_profit if total_profit > 0 else 0.0,
        }

    return breakdown


def compute_r_squared(equity_returns: pd.Series, spy_returns: pd.Series) -> float:
    """
    Compute R² between portfolio daily returns and SPY daily returns.
    Blueprint Tier 1 threshold: R² < 0.4 (strategy has alpha, not just beta).
    Called from WFO engine in Week 19 after aligning both return series.
    """
    aligned = pd.concat([equity_returns, spy_returns], axis=1, sort=True).dropna()
    if len(aligned) < 10:
        return float("nan")
    corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
    return corr ** 2


def check_vault_tier(metrics: Dict[str, Any]) -> str:
    """
    Evaluate metrics against blueprint Section 8.2 thresholds.
    Returns: 'TIER_1' | 'TIER_2' | 'TIER_3'
    Called by the Vault test runner in Week 21.
    """
    calmar     = metrics.get("calmar_ratio", 0)
    pf         = metrics.get("profit_factor", 0)
    max_dd     = metrics.get("max_drawdown", -1)   # negative fraction
    sharpe     = metrics.get("sharpe_ratio", 0)
    win_rate   = metrics.get("win_rate", 0)
    recovery   = metrics.get("recovery_days")
    tail_risk  = metrics.get("tail_risk_99", -1)   # negative fraction
    total_ret  = metrics.get("total_return", -1)

    # Automatic Tier 3 disqualifiers (Section 8.2)
    if total_ret <= 0:
        return "TIER_3"
    if max_dd <= -0.25:
        return "TIER_3"

    # Tier 1
    tier1 = (
        calmar    > 2.0
        and pf    > 1.75
        and max_dd > -0.15        # less than 15% drawdown
        and sharpe > 1.5
        and win_rate > 0.40
        and (recovery is None or recovery < 90)
        and tail_risk > -0.04     # worst day better than -4%
    )
    if tier1:
        return "TIER_1"

    # Tier 2
    tier2 = (
        calmar    > 1.5
        and pf    > 1.5
        and max_dd > -0.18
        and sharpe > 1.2
        and win_rate > 0.35
        and (recovery is None or recovery < 120)
        and tail_risk > -0.05
    )
    if tier2:
        return "TIER_2"

    return "TIER_3"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_metrics() -> Dict[str, Any]:
    return {
        "total_trades":  0,
        "win_rate":      0.0,
        "profit_factor": 0.0,
        "calmar_ratio":  0.0,
        "sharpe_ratio":  0.0,
        "max_drawdown":  0.0,
        "total_return":  0.0,
        "annual_return": 0.0,
        "tail_risk_99":  0.0,
        "total_costs":   0.0,
        "r_squared_spy": None,
    }
