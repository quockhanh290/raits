"""
bull_calm_strats.py -- IS only (2017-2022), standalone, read-only

Tests THREE pre-committed bull/Calm strategy hypotheses on daily stock bars.

BONFERRONI CORRECTION: 3 simultaneous tests -> alpha = 0.05/3 = 0.0167.
A strategy PASSES only if bootstrap p < 0.0167 AND beats buy-and-hold.

STRATEGY A -- EMA20 Dip:
  Regime : Close > SMA50 > SMA200  AND  ATR(14)/Close < 3%
  Setup  : Low <= EMA20  AND  40 <= RSI(14) <= 55
  Trigger: Close > High[prev] (confirmation bar), fill next open
  Stop   : Low[signal] - 0.5 * ATR(14)[signal]  (intraday: low <= stop)
  Exit   : 50% at roll_high_20[signal] (intraday: high >= target);
           remaining 50% when Close < EMA20

STRATEGY B -- Breakout Retest:
  Regime : Close > SMA50 > SMA200
  Setup  : Close breaks above prior 20-session high (roll_high_20_prev)
           THEN price retests breakout level within sessions 3-10
  Trigger: Green close on retest day AND Close >= breakout_level, fill next open
  Stop   : breakout_level  (intraday: low <= stop)
  Exit   : 2R target (intraday: high >= 2R)  OR  Close < EMA20

STRATEGY C -- Inside Bar Continuation:
  Regime : Close > EMA20 > SMA50 > SMA200  AND  ATR(14)/Close < 3%
  Setup  : Inside bar (High <= prev_High  AND  Low >= prev_Low)
  Entry  : Buy-stop at inside-bar High next session (gap-up -> fill at open)
  Stop   : inside-bar Low  (intraday: low <= stop)
  Exit   : 2R target (intraday: high >= 2R)  OR  Close < EMA10

All: time stop at 20 sessions (30 for Strategy A which has two-phase exit).
Cost model: $5 flat commission per side + 0.05% slippage per side on trade value.
            $10,000 position per trade (int shares).  ~$20 round-trip.

Buy-and-hold counterfactual: same entry (same open, same shares);
  exits at CLOSE on same day as strategy final exit.
  For intraday fills (stop/target): strategy gets the intraday price,
  BAH gets the EOD close.  Edge = strategy_net - bah_net.

Regime proxy: SPY 5-day realized vol, IS tercile -> Calm / Normal / Stress.
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRADE_SIZE    = 10_000.0    # $ per trade
COMM          = 5.0         # $ flat commission per side
SLIPPAGE      = 0.0005      # 0.05% per side slippage
ATR_WINDOW    = 14
RSI_WINDOW    = 14
EMA10_WINDOW  = 10
EMA20_WINDOW  = 20
SMA50_WINDOW  = 50
SMA200_WINDOW = 200
ROLL_HIGH     = 20          # sessions for rolling high
TIME_STOP_A   = 30          # max sessions for Strategy A (two-phase)
TIME_STOP_B   = 20          # max sessions for Strategy B
TIME_STOP_C   = 20          # max sessions for Strategy C
ATR_LIMIT     = 0.03        # ATR/Close < 3%  (low-vol regime filter)
DIP_RSI_LO    = 40
DIP_RSI_HI    = 55
RETEST_NEAR   = 0.02        # "near breakout" = within 2% above
RETEST_MIN_D  = 3           # retest must be >= 3 sessions after breakout
RETEST_MAX_D  = 10          # retest must be <= 10 sessions after breakout
N_BOOT        = 1000
BOOT_SEED     = 42
BONFERRONI_P  = 0.0167      # 0.05 / 3
IS_START      = "2017-01-01"
IS_END        = "2022-12-31"
VOL_WINDOW    = 5

UNIVERSE = [
    "AAPL", "ADBE", "AMAT", "AMD",  "AMGN", "AMZN", "AVGO", "BIIB",
    "COST", "CRM",  "CSCO", "CVX",  "EBAY", "GILD", "GOOGL","GS",
    "HON",  "INTC", "INTU", "JPM",  "MA",   "META", "MMM",  "MS",
    "MSFT", "MU",   "NFLX", "NVDA", "ORCL", "QCOM", "REGN", "SBUX",
    "TSLA", "TXN",  "V",    "VRTX", "XOM",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Indicator helpers (pure functions, all testable in isolation)
# ---------------------------------------------------------------------------

def compute_sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def compute_ema(close: pd.Series, window: int) -> pd.Series:
    return close.ewm(span=window, adjust=False).mean()


def compute_rsi(close: pd.Series, window: int = RSI_WINDOW) -> pd.Series:
    delta    = close.diff()
    gain     = delta.clip(lower=0.0)
    loss     = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    # Avoid divide-by-zero: when avg_loss ~ 0 (no downward moves), RS → ∞, RSI → 100
    rs = avg_gain / avg_loss.replace(0.0, 1e-10)
    return 100.0 - 100.0 / (1.0 + rs)


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                window: int = ATR_WINDOW) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()


def compute_all_indicators(close: pd.Series, high: pd.Series, low: pd.Series,
                           ) -> dict[str, pd.Series]:
    """Compute all indicators needed by the three strategies."""
    return {
        "sma50"          : compute_sma(close, SMA50_WINDOW),
        "sma200"         : compute_sma(close, SMA200_WINDOW),
        "ema10"          : compute_ema(close, EMA10_WINDOW),
        "ema20"          : compute_ema(close, EMA20_WINDOW),
        "atr14"          : compute_atr(high, low, close, ATR_WINDOW),
        "rsi14"          : compute_rsi(close, RSI_WINDOW),
        "roll_high20"    : close.rolling(ROLL_HIGH, min_periods=ROLL_HIGH).max(),
        # Breakout uses PRIOR 20-session high (not including today)
        "roll_high20_prev": close.shift(1).rolling(ROLL_HIGH, min_periods=ROLL_HIGH).max(),
    }


# ---------------------------------------------------------------------------
# Shared trade-recording helper
# ---------------------------------------------------------------------------

def _make_trade(ticker, strategy, entry_date, exit_date, entry_px, exit_px,
                bah_exit_px, shares, hold_days, exit_reason, n_shares_entry,
                costs, bah_costs):
    gross   = (exit_px - entry_px) * shares
    net     = gross - costs
    bah_g   = (bah_exit_px - entry_px) * n_shares_entry
    bah_net = bah_g - bah_costs
    return {
        "strategy"    : strategy,
        "ticker"      : ticker,
        "entry_date"  : entry_date,
        "exit_date"   : exit_date,
        "entry_px"    : entry_px,
        "exit_px"     : exit_px,
        "bah_exit_px" : bah_exit_px,
        "shares"      : shares,
        "hold_days"   : hold_days,
        "exit_reason" : exit_reason,
        "gross_pnl"   : gross,
        "costs"       : costs,
        "net_pnl"     : net,
        "bah_net_pnl" : bah_net,
        "edge"        : net - bah_net,
    }


# ---------------------------------------------------------------------------
# STRATEGY A -- EMA20 Dip
# ---------------------------------------------------------------------------

def simulate_a(ticker, close, open_, high, low,
               sma50, sma200, ema20, atr14, rsi14, roll_high20,
               trade_size=TRADE_SIZE, comm=COMM, slippage=SLIPPAGE):
    """
    Two-phase exit:
      Phase 1: sell half when HIGH >= roll_high20[signal] -> fill at roll_high20
      Phase 2: sell remaining when CLOSE < EMA20 -> fill at close
      BAH: enters at same open, exits at CLOSE on Phase-2 exit day.
    """
    n      = len(close)
    trades = []

    in_trade = False
    phase1_hit = False
    entry_px = entry_date = entry_cost = None
    stop_price = peak_target = 0.0
    n_total = shares_half = shares_rem = 0
    hold_days = phase2_hold_days = p1_hold_days = 0
    p1_exit_px = p1_exit_cost = 0.0

    i = 1
    while i < n:
        c   = close.iloc[i];  o   = open_.iloc[i]
        h   = high.iloc[i];   l   = low.iloc[i]
        s50 = sma50.iloc[i];  s200 = sma200.iloc[i]
        e20 = ema20.iloc[i];  a14  = atr14.iloc[i]
        r14 = rsi14.iloc[i];  rh   = roll_high20.iloc[i]
        d   = close.index[i]; hprev = high.iloc[i - 1]

        if not in_trade:
            if any(pd.isna(v) for v in (c, s50, s200, e20, a14, r14, rh)):
                i += 1; continue

            if (c > s50 and s50 > s200                   # uptrend
                    and a14 / c < ATR_LIMIT               # low vol
                    and l <= e20                          # low touched EMA20
                    and DIP_RSI_LO <= r14 <= DIP_RSI_HI  # RSI window
                    and c > hprev                         # confirmation
                    and i + 1 < n):

                fo = open_.iloc[i + 1]
                if pd.isna(fo) or fo <= 0:
                    i += 1; continue
                ns = int(trade_size / fo)
                if ns < 2:          # need >= 2 shares for partial exit
                    i += 1; continue

                in_trade    = True
                phase1_hit  = False
                entry_px    = fo
                entry_date  = close.index[i + 1]
                entry_cost  = comm + slippage * fo * ns
                stop_price  = l - 0.5 * a14
                peak_target = rh
                n_total     = ns
                shares_half = ns // 2
                shares_rem  = ns - shares_half
                hold_days   = phase2_hold_days = 0
                p1_exit_px  = p1_exit_cost = 0.0
                i = i + 1
                continue

            i += 1; continue

        # --- IN TRADE ---
        if pd.isna(c) or pd.isna(e20):
            hold_days += 1; i += 1; continue

        if not phase1_hit:
            hold_days += 1
            bah_close = c

            # Stop-loss (intraday low touches stop)
            if (not pd.isna(low.iloc[i])) and low.iloc[i] <= stop_price:
                ep  = stop_price
                c1  = comm + slippage * ep * n_total
                tc  = entry_cost + c1
                bah_c = comm + slippage * bah_close * n_total
                trades.append(_make_trade(
                    ticker, "A", entry_date, d, entry_px, ep, bah_close,
                    n_total, hold_days, "STOP_LOSS", n_total, tc,
                    entry_cost + bah_c,
                ))
                in_trade = False

            # Phase-1 target (intraday high touches peak)
            elif (not pd.isna(h)) and h >= peak_target:
                phase1_hit    = True
                p1_exit_px    = peak_target
                p1_exit_cost  = comm + slippage * peak_target * shares_half
                p1_hold_days  = hold_days   # save to cap phase2 duration
                # stay in trade for phase 2

            # Time stop (no partial exit yet)
            elif hold_days >= TIME_STOP_A:
                ep  = c
                c1  = comm + slippage * ep * n_total
                tc  = entry_cost + c1
                bah_c = comm + slippage * c * n_total
                trades.append(_make_trade(
                    ticker, "A", entry_date, d, entry_px, ep, c,
                    n_total, hold_days, "TIME_STOP", n_total, tc,
                    entry_cost + bah_c,
                ))
                in_trade = False

        else:   # phase 1 hit, managing remaining
            phase2_hold_days += 1
            bah_close = c

            exit_p2 = None
            reason  = None

            p2_budget = max(1, TIME_STOP_A - p1_hold_days)
            if c < e20:
                exit_p2 = c;  reason = "PHASE1_THEN_EMA20"
            elif phase2_hold_days >= p2_budget:
                exit_p2 = c;  reason = "PHASE1_THEN_TIMEOUT"

            if exit_p2 is not None:
                p2_exit_cost = comm + slippage * exit_p2 * shares_rem
                total_cost   = entry_cost + p1_exit_cost + p2_exit_cost
                gross = ((p1_exit_px - entry_px) * shares_half
                         + (exit_p2   - entry_px) * shares_rem)
                net   = gross - total_cost

                bah_exit_cost = entry_cost + comm + slippage * bah_close * n_total
                bah_gross     = (bah_close - entry_px) * n_total
                bah_net       = bah_gross - bah_exit_cost

                trades.append({
                    "strategy"    : "A",
                    "ticker"      : ticker,
                    "entry_date"  : entry_date,
                    "exit_date"   : d,
                    "entry_px"    : entry_px,
                    "exit_px"     : (p1_exit_px * shares_half + exit_p2 * shares_rem) / n_total,
                    "bah_exit_px" : bah_close,
                    "shares"      : n_total,
                    "hold_days"   : hold_days + phase2_hold_days,
                    "exit_reason" : reason,
                    "gross_pnl"   : gross,
                    "costs"       : total_cost,
                    "net_pnl"     : net,
                    "bah_net_pnl" : bah_net,
                    "edge"        : net - bah_net,
                })
                in_trade = False

        i += 1

    return trades


# ---------------------------------------------------------------------------
# STRATEGY B -- Breakout Retest
# ---------------------------------------------------------------------------

def simulate_b(ticker, close, open_, high, low,
               sma50, sma200, ema20, roll_high20_prev,
               trade_size=TRADE_SIZE, comm=COMM, slippage=SLIPPAGE):
    """
    Tracks a two-phase setup: (1) breakout above prior 20-session high,
    (2) retest within sessions 3-10.  Enters on green close on retest day.
    Stop: breakout_level.  Exit: 2R or close < EMA20.
    """
    n      = len(close)
    trades = []

    in_trade        = False
    tracking_retest = False
    breakout_level  = 0.0
    days_since_bo   = 0

    entry_px = entry_date = entry_cost = None
    stop_px  = target_2r  = 0.0
    hold_days = 0

    i = 1
    while i < n:
        c   = close.iloc[i];  o   = open_.iloc[i]
        h   = high.iloc[i];   l   = low.iloc[i]
        s50 = sma50.iloc[i];  s200 = sma200.iloc[i]
        e20 = ema20.iloc[i];  rh_prev = roll_high20_prev.iloc[i]
        d   = close.index[i]
        c_prev = close.iloc[i - 1]

        # --- IN TRADE ---
        if in_trade:
            if pd.isna(c):
                hold_days += 1; i += 1; continue
            hold_days += 1
            bah_close = c

            exit_px = None; reason = None

            # Stop: intraday low <= breakout_level
            if (not pd.isna(l)) and l <= stop_px:
                exit_px = stop_px;  reason = "STOP_LOSS"
            # 2R target: intraday high >= target
            elif (not pd.isna(h)) and h >= target_2r:
                exit_px = target_2r;  reason = "TARGET_2R"
            # EMA20 trailing stop
            elif (not pd.isna(e20)) and c < e20:
                exit_px = c;  reason = "EMA20_STOP"
            # Time stop
            elif hold_days >= TIME_STOP_B:
                exit_px = c;  reason = "TIME_STOP"

            if exit_px is not None:
                c1   = comm + slippage * exit_px * entry_shares
                tc   = entry_cost + c1
                bah_c = comm + slippage * bah_close * entry_shares
                trades.append(_make_trade(
                    ticker, "B", entry_date, d, entry_px, exit_px, bah_close,
                    entry_shares, hold_days, reason, entry_shares, tc,
                    entry_cost + bah_c,
                ))
                in_trade = False

            i += 1; continue

        # --- SETUP TRACKING ---
        any_nan = any(pd.isna(v) for v in (c, s50, s200, e20, rh_prev))

        if tracking_retest and not any_nan:
            days_since_bo += 1

            if days_since_bo > RETEST_MAX_D:
                tracking_retest = False   # expired; fall through to breakout check
            elif days_since_bo >= RETEST_MIN_D:
                # Valid retest window: price came back near breakout level?
                retest = (
                    (not pd.isna(l)) and l <= breakout_level * (1.0 + RETEST_NEAR)
                    and c >= breakout_level              # still above level
                    and c > c_prev                       # green close
                    and c > s50 and s50 > s200           # uptrend still holds
                    and i + 1 < n
                )
                if retest:
                    fo = open_.iloc[i + 1]
                    if pd.isna(fo) or fo <= 0:
                        tracking_retest = False; i += 1; continue
                    ns = int(trade_size / fo)
                    if ns == 0:
                        tracking_retest = False; i += 1; continue

                    risk     = fo - stop_px   # stop_px = breakout_level set at BO
                    if risk <= 0:
                        tracking_retest = False; i += 1; continue
                    target_2r = fo + 2.0 * risk

                    in_trade      = True
                    tracking_retest = False
                    entry_px      = fo
                    entry_date    = close.index[i + 1]
                    entry_cost    = comm + slippage * fo * ns
                    entry_shares  = ns
                    hold_days     = 0
                    i = i + 1
                    continue

        if not any_nan and not tracking_retest:
            # Check for new breakout
            uptrend = c > s50 and s50 > s200
            if uptrend and c > rh_prev:
                tracking_retest = True
                breakout_level  = float(rh_prev)
                stop_px         = breakout_level
                days_since_bo   = 0

        i += 1

    return trades


# ---------------------------------------------------------------------------
# STRATEGY C -- Inside Bar Continuation
# ---------------------------------------------------------------------------

def simulate_c(ticker, close, open_, high, low,
               sma50, sma200, ema10, ema20, atr14,
               trade_size=TRADE_SIZE, comm=COMM, slippage=SLIPPAGE):
    """
    Inside bar continuation.
    Regime: Close > EMA20 > SMA50 > SMA200, ATR/Close < 3%.
    Setup: inside bar (High<=prev_High, Low>=prev_Low).
    Entry: buy-stop at inside_bar_high next session; if gap-up, fill at open.
    Stop: inside_bar_low.  Exit: 2R or Close < EMA10.
    """
    n      = len(close)
    trades = []

    in_trade      = False
    pending_entry = False
    ib_high = ib_low = 0.0

    entry_px = entry_date = entry_cost = None
    stop_px  = target_2r  = 0.0
    hold_days = 0
    entry_shares = 0

    i = 1
    while i < n:
        c   = close.iloc[i];  o   = open_.iloc[i]
        h   = high.iloc[i];   l   = low.iloc[i]
        s50 = sma50.iloc[i];  s200 = sma200.iloc[i]
        e10 = ema10.iloc[i];  e20  = ema20.iloc[i]
        a14 = atr14.iloc[i];  d    = close.index[i]

        # --- IN TRADE ---
        if in_trade:
            if pd.isna(c):
                hold_days += 1; i += 1; continue
            hold_days += 1
            bah_close = c

            exit_px = None; reason = None

            if (not pd.isna(l)) and l <= stop_px:
                exit_px = stop_px;  reason = "STOP_LOSS"
            elif (not pd.isna(h)) and h >= target_2r:
                exit_px = target_2r;  reason = "TARGET_2R"
            elif (not pd.isna(e10)) and c < e10:
                exit_px = c;  reason = "EMA10_STOP"
            elif hold_days >= TIME_STOP_C:
                exit_px = c;  reason = "TIME_STOP"

            if exit_px is not None:
                c1    = comm + slippage * exit_px * entry_shares
                tc    = entry_cost + c1
                bah_c = comm + slippage * bah_close * entry_shares
                trades.append(_make_trade(
                    ticker, "C", entry_date, d, entry_px, exit_px,
                    bah_close, entry_shares, hold_days, reason,
                    entry_shares, tc, entry_cost + bah_c,
                ))
                in_trade = False

            i += 1; continue

        # --- PENDING ENTRY (buy-stop active) ---
        if pending_entry:
            triggered = False
            fill_px   = None
            if not pd.isna(o) and o > ib_high:
                # Gap-up: fill at open
                fill_px   = o
                triggered = True
            elif not pd.isna(h) and h >= ib_high:
                # Intraday trigger: fill at ib_high
                fill_px   = ib_high
                triggered = True

            if triggered and fill_px is not None and fill_px > 0:
                ns = int(trade_size / fill_px)
                if ns > 0:
                    risk = fill_px - ib_low
                    if risk > 0:
                        in_trade      = True
                        entry_px      = fill_px
                        entry_date    = d
                        entry_cost    = comm + slippage * fill_px * ns
                        stop_px       = ib_low
                        target_2r     = fill_px + 2.0 * risk
                        entry_shares  = ns
                        hold_days     = 0

                        # Process this day as in-trade (first hold day)
                        bah_close = c
                        hold_days += 1
                        exit_px = None; reason = None
                        if (not pd.isna(l)) and l <= stop_px:
                            exit_px = stop_px;  reason = "STOP_LOSS"
                        elif (not pd.isna(h)) and h >= target_2r:
                            exit_px = target_2r;  reason = "TARGET_2R"
                        elif (not pd.isna(e10)) and c < e10:
                            exit_px = c;  reason = "EMA10_STOP"

                        if exit_px is not None:
                            c1   = comm + slippage * exit_px * ns
                            tc   = entry_cost + c1
                            bah_c = comm + slippage * bah_close * ns
                            bh_pnl = (bah_close - entry_px) * ns - (entry_cost + bah_c)
                            trades.append({
                                "strategy": "C", "ticker": ticker,
                                "entry_date": entry_date, "exit_date": d,
                                "entry_px": entry_px, "exit_px": exit_px,
                                "bah_exit_px": bah_close, "shares": ns,
                                "hold_days": hold_days, "exit_reason": reason,
                                "gross_pnl": (exit_px - entry_px) * ns,
                                "costs": tc, "net_pnl": (exit_px - entry_px) * ns - tc,
                                "bah_net_pnl": bh_pnl,
                                "edge": (exit_px - entry_px) * ns - tc - bh_pnl,
                            })
                            in_trade = False

            pending_entry = False
            i += 1; continue

        # --- OUT OF TRADE ---
        any_nan = any(pd.isna(v) for v in (c, s50, s200, e10, e20, a14, h, l))
        if any_nan:
            i += 1; continue

        h_prev = high.iloc[i - 1];  l_prev = low.iloc[i - 1]
        if pd.isna(h_prev) or pd.isna(l_prev):
            i += 1; continue

        regime_ok = (c > e20) and (e20 > s50) and (s50 > s200) and (a14 / c < ATR_LIMIT)
        inside    = (h <= h_prev) and (l >= l_prev)

        if regime_ok and inside and i + 1 < n:
            ib_high       = h
            ib_low        = l
            pending_entry = True

        i += 1

    return trades


# ---------------------------------------------------------------------------
# Analysis utilities (same pattern as dip_buy_sim)
# ---------------------------------------------------------------------------

def compute_stats(df: pd.DataFrame, strategy_label: str) -> dict:
    if df.empty:
        return {"strategy": strategy_label, "n_trades": 0}
    wins   = df.loc[df["net_pnl"] > 0, "net_pnl"]
    losses = df.loc[df["net_pnl"] <= 0, "net_pnl"]
    pf = (float(wins.sum()) / abs(float(losses.sum()))
          if len(losses) > 0 and abs(losses.sum()) > 0
          else float("inf") if len(wins) > 0 else 0.0)
    eq  = df.sort_values("exit_date")["net_pnl"].cumsum()
    mdd = float((eq - eq.cummax()).min())
    return {
        "strategy"      : strategy_label,
        "n_trades"      : len(df),
        "win_rate"      : float(len(wins) / len(df)),
        "total_net_pnl" : float(df["net_pnl"].sum()),
        "avg_win"       : float(wins.mean()) if len(wins) else 0.0,
        "avg_loss"      : float(losses.mean()) if len(losses) else 0.0,
        "profit_factor" : pf,
        "avg_hold_days" : float(df["hold_days"].mean()),
        "max_drawdown"  : mdd,
    }


def bootstrap_pvalue(edges: np.ndarray, n_boot: int = N_BOOT,
                     seed: int = BOOT_SEED) -> float:
    if len(edges) == 0:
        return 1.0
    rng   = np.random.default_rng(seed)
    means = np.array([
        rng.choice(edges, size=len(edges), replace=True).mean()
        for _ in range(n_boot)
    ])
    return float(np.mean(means <= 0.0))


def compute_vol_proxy(spy_close: pd.Series) -> pd.Series:
    log_ret = np.log(spy_close / spy_close.shift(1))
    rvol    = log_ret.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std() * np.sqrt(252)
    is_rv   = rvol.loc[IS_START:IS_END].dropna()
    t33, t67 = float(is_rv.quantile(0.333)), float(is_rv.quantile(0.667))

    def _lbl(v):
        if pd.isna(v):   return None
        if v < t33:      return "Calm"
        if v < t67:      return "Normal"
        return "Stress"

    return rvol.loc[IS_START:IS_END].map(_lbl)


def _map_proxy(vol_proxy: pd.Series, date) -> str:
    try:
        d = pd.Timestamp(date).normalize()
        if d in vol_proxy.index:
            v = vol_proxy.loc[d]
            return v if v is not None else "Unknown"
        idx = vol_proxy.index.get_indexer([d], method="nearest")
        if idx[0] >= 0:
            v = vol_proxy.iloc[idx[0]]
            return v if v is not None else "Unknown"
    except Exception:
        pass
    return "Unknown"


def compute_portfolio_bah(tickers: list[str], cache_dir: Path) -> dict:
    rets = {}
    for tkr in tickers:
        files = sorted(cache_dir.glob(f"{tkr}_daily_*.parquet"))
        if not files:
            continue
        df  = pd.read_parquet(files[0])
        is_ = df.loc[IS_START:IS_END, "close"].dropna()
        if len(is_) < 5:
            rets[tkr] = float("nan"); continue
        rets[tkr] = float(is_.iloc[-1] / is_.iloc[0] - 1.0)
    valid  = {k: v for k, v in rets.items() if not pd.isna(v)}
    eq_ret = float(np.mean(list(valid.values()))) if valid else float("nan")
    return {"per_ticker": rets, "equal_weight_return": eq_ret, "n_stocks": len(valid)}


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_edge_distributions(dfs: dict[str, pd.DataFrame], output_path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle("Bull/Calm Strategies: Per-Trade Edge vs Buy-and-Hold (IS 2017-2022)")
    for ax, (label, df) in zip(axes, dfs.items()):
        edges   = df["edge"].dropna().values if not df.empty else np.array([])
        nonzero = edges[edges != 0.0]
        if len(nonzero) > 0:
            ax.hist(nonzero, bins=30, color="steelblue", edgecolor="white", alpha=0.8)
        else:
            ax.text(0.5, 0.5, "All edges = 0", ha="center", va="center",
                    transform=ax.transAxes)
        ax.axvline(0, color="red", lw=1.5, ls="--")
        if len(edges) > 0:
            ax.axvline(edges.mean(), color="orange", lw=1.5,
                       label=f"Mean ${edges.mean():.0f}")
        ax.set_title(f"Strategy {label}")
        ax.set_xlabel("Edge ($): strategy - BAH")
        ax.legend(fontsize=8)
        n, npos, nneg = len(edges), int((edges > 0).sum()), int((edges < 0).sum())
        ax.text(0.02, 0.97, f"n={n} beat={npos} lose={nneg}",
                transform=ax.transAxes, va="top", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow"))
    plt.tight_layout()
    plt.savefig(str(output_path), dpi=120)
    plt.close()
    print(f"Plot saved: {output_path}")


# ---------------------------------------------------------------------------
# Main analysis driver
# ---------------------------------------------------------------------------

def analyze(spy_daily_path: Path, cache_dir: Path, output_dir: Path) -> None:
    # Load SPY for vol proxy
    spy_df    = pd.read_parquet(spy_daily_path)
    spy_close = spy_df["close"].loc[:IS_END]
    vol_proxy = compute_vol_proxy(spy_close)

    # Run simulation over all stocks
    all_a: list[dict] = []
    all_b: list[dict] = []
    all_c: list[dict] = []
    skipped: list[str] = []

    for tkr in UNIVERSE:
        files = sorted(cache_dir.glob(f"{tkr}_daily_*.parquet"))
        if not files:
            skipped.append(tkr); continue
        df = pd.read_parquet(files[0]).loc[IS_START:IS_END].copy()
        if len(df) < SMA200_WINDOW + 10:
            skipped.append(tkr); continue

        close = df["close"]; open_ = df["open"]
        high  = df["high"];  low   = df["low"]

        ind = compute_all_indicators(close, high, low)

        all_a.extend(simulate_a(tkr, close, open_, high, low,
                                ind["sma50"], ind["sma200"], ind["ema20"],
                                ind["atr14"], ind["rsi14"], ind["roll_high20"]))
        all_b.extend(simulate_b(tkr, close, open_, high, low,
                                ind["sma50"], ind["sma200"], ind["ema20"],
                                ind["roll_high20_prev"]))
        all_c.extend(simulate_c(tkr, close, open_, high, low,
                                ind["sma50"], ind["sma200"], ind["ema10"],
                                ind["ema20"], ind["atr14"]))

    if skipped:
        print(f"  Skipped: {skipped}")

    dfs = {
        "A": pd.DataFrame(all_a),
        "B": pd.DataFrame(all_b),
        "C": pd.DataFrame(all_c),
    }

    # Tag regime proxy
    for df in dfs.values():
        if df.empty:
            df["hmm_proxy"] = pd.Series(dtype=str); continue
        df["hmm_proxy"] = df["entry_date"].apply(
            lambda d: _map_proxy(vol_proxy, d))

    stats = {k: compute_stats(df, k) for k, df in dfs.items()}
    pvals = {}
    for k, df in dfs.items():
        edges     = df["edge"].values if not df.empty else np.array([])
        pvals[k]  = bootstrap_pvalue(edges)

    bah = compute_portfolio_bah(UNIVERSE, cache_dir)

    # -- Print results ------------------------------------------------------
    SEP = "=" * 70
    print()
    print(SEP)
    print("  BULL/CALM STRATEGIES -- IS 2017-2022  (3 simultaneous tests)")
    print(SEP)
    print()
    print("BONFERRONI CORRECTION: alpha = 0.05/3 = 0.0167")
    print("PASS requires: bootstrap p < 0.0167 AND beats buy-and-hold-same-stock.")
    print()
    print("COST MODEL: $5/side + 0.05%/side slippage, $10k/trade. ~$20 round-trip.")
    print()
    print("CAVEATS:")
    print("  Pre-committed rules; no tuning. BAH-same-stock is the honest benchmark.")
    print("  In-sample only (2017-2022). 2023+ sealed.")
    print("  META: only ~290 IS bars (starts 2021-06-30).")
    print("  CANDIDATE_POOL fixed in advance (known-universe mild survivorship bias).")
    print()

    strategy_desc = {
        "A": "EMA20 Dip  (two-phase exit: 50%@peak, 50%@EMA20 break)",
        "B": "Breakout Retest  (2R target OR EMA20 stop)",
        "C": "Inside Bar Continuation  (2R target OR EMA10 stop)",
    }

    for k in ("A", "B", "C"):
        df  = dfs[k]
        st  = stats[k]
        pv  = pvals[k]
        print(f"{'-' * 70}")
        print(f"  STRATEGY {k} -- {strategy_desc[k]}")
        print(f"{'-' * 70}")
        print(f"  n_trades      : {st.get('n_trades', 0)}")
        if st.get("n_trades", 0) < 30:
            print("  ** WARNING: fewer than 30 trades -- result statistically weak **")
        if st.get("n_trades", 0) > 0:
            print(f"  win_rate      : {st['win_rate']:.1%}")
            print(f"  total net P&L : ${st['total_net_pnl']:,.0f}")
            print(f"  avg win       : ${st['avg_win']:,.0f}  |  avg loss: ${st['avg_loss']:,.0f}")
            print(f"  profit factor : {st['profit_factor']:.2f}")
            print(f"  avg hold days : {st['avg_hold_days']:.1f}")
            print(f"  max drawdown  : ${st['max_drawdown']:,.0f}")
            print()
            # Exit breakdown
            print("  Exit breakdown:")
            for r, cnt in df["exit_reason"].value_counts().items():
                print(f"    {r:<22} {cnt:>4}  ({cnt/len(df):.0%})")
            print()
            # vs BAH
            tot_bah  = float(df["bah_net_pnl"].sum())
            tot_strat = float(df["net_pnl"].sum())
            n_beat   = int((df["edge"] > 0).sum())
            n_lose   = int((df["edge"] < 0).sum())
            n_tie    = len(df) - n_beat - n_lose
            print("  vs BUY-AND-HOLD same stock, same period:")
            print(f"    strategy total  : ${tot_strat:>10,.0f}")
            print(f"    BAH total       : ${tot_bah:>10,.0f}")
            print(f"    net $ advantage : ${float(df['edge'].sum()):>+10,.0f}")
            print(f"    beat={n_beat}  lose={n_lose}  tie={n_tie}"
                  f"  ({n_beat/len(df):.0%} beat rate)")
            print()
            # Regime
            dist  = df["hmm_proxy"].value_counts()
            total = len(df)
            parts = "  ".join(
                f"{s}={dist.get(s,0)} ({dist.get(s,0)/total:.0%})"
                for s in ("Calm", "Normal", "Stress")
            )
            print(f"  Regime (vol proxy): {parts}")
            calm_pct = dist.get("Calm", 0) / total
            if calm_pct < 0.30:
                print(f"  ** NOTE: only {calm_pct:.0%} Calm trades -- does NOT fill Calm gap **")
            print()
            # Bootstrap
            verdict = "PASS" if (pv < BONFERRONI_P and tot_strat > tot_bah) else "DEAD"
            print(f"  Bootstrap p-value : {pv:.4f}  (raw p)")
            print(f"  Bonferroni thresh : {BONFERRONI_P:.4f}  (p must be < this to pass)")
            print(f"  Verdict           : {verdict}")
            if verdict == "DEAD":
                if pv >= BONFERRONI_P:
                    print(f"    -> p={pv:.4f} >= {BONFERRONI_P} (not significant at Bonferroni threshold)")
                if tot_strat <= tot_bah:
                    print(f"    -> strategy ({tot_strat:,.0f}) does not beat BAH ({tot_bah:,.0f})")
        print()

    # Summary table
    print(f"{'=' * 70}")
    print("  SUMMARY TABLE")
    print(f"{'=' * 70}")
    print(f"  {'Strat':<8} {'n_trades':>9} {'net_P&L':>10} {'BAH_P&L':>10}"
          f" {'beat%':>7} {'p_raw':>8} {'vs_0.0167':>10} {'Verdict'}")
    print(f"  {'-'*8} {'-'*9} {'-'*10} {'-'*10} {'-'*7} {'-'*8} {'-'*10} {'-'*7}")
    for k in ("A", "B", "C"):
        df = dfs[k]; st = stats[k]; pv = pvals[k]
        if st.get("n_trades", 0) == 0:
            print(f"  {k:<8} {'0':>9} {'n/a':>10} {'n/a':>10} {'n/a':>7}"
                  f" {'n/a':>8} {'n/a':>10} DEAD")
            continue
        n_beat    = int((df["edge"] > 0).sum())
        beat_pct  = f"{n_beat/len(df):.0%}"
        net       = df["net_pnl"].sum()
        bah_tot   = df["bah_net_pnl"].sum()
        pass_str  = "PASS" if (pv < BONFERRONI_P and net > bah_tot) else "DEAD"
        sig       = "YES" if pv < BONFERRONI_P else "no"
        print(f"  {k:<8} {st['n_trades']:>9} ${net:>9,.0f} ${bah_tot:>9,.0f}"
              f" {beat_pct:>7} {pv:>8.4f} {sig:>10} {pass_str}")

    print()
    ew = bah.get("equal_weight_return", float("nan"))
    print(f"  Equal-weight basket 2017-2022: {ew:.1%} avg return (reference bar).")
    print()

    # How many fired in Calm?
    n_calm_dominant = 0
    for k in ("A", "B", "C"):
        df = dfs[k]
        if df.empty: continue
        calm_pct = (df["hmm_proxy"] == "Calm").sum() / len(df)
        if calm_pct >= 0.30:
            n_calm_dominant += 1
    print(f"  Strategies with >=30% Calm-regime trades (the actual target): "
          f"{n_calm_dominant} / 3")
    print()
    n_pass = sum(
        1 for k in ("A","B","C")
        if (pvals[k] < BONFERRONI_P
            and dfs[k]["net_pnl"].sum() > dfs[k]["bah_net_pnl"].sum())
    )
    print(f"  Overall verdict: {n_pass}/3 strategies PASS Bonferroni + beats-hold bar.")
    print(SEP)

    plot_edge_distributions(dfs, output_dir / "bull_calm_edge_distribution.png")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_spy() -> Path:
    return _REPO_ROOT/"raits"/"data"/"cache"/"daily"/"SPY_daily_2007_2024.parquet"

def _default_cache() -> Path:
    return _REPO_ROOT/"raits"/"data"/"cache"/"daily"

def _default_out() -> Path:
    return _REPO_ROOT/"raits"/"configs"

def main() -> None:
    p = argparse.ArgumentParser(description="Bull/Calm strategy trio -- IS only")
    p.add_argument("--spy-daily",  type=Path, default=_default_spy())
    p.add_argument("--cache-dir",  type=Path, default=_default_cache())
    p.add_argument("--output-dir", type=Path, default=_default_out())
    args = p.parse_args()
    if not args.spy_daily.exists():
        sys.exit(f"SPY daily not found: {args.spy_daily}")
    if not args.cache_dir.is_dir():
        sys.exit(f"Cache dir not found: {args.cache_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    analyze(args.spy_daily, args.cache_dir, args.output_dir)

if __name__ == "__main__":
    main()
