"""
scripts/irb_test.py
--------------------
Standalone backtest for Intraday Range Breakout (IRB) strategy.
No engine modifications — reads cached 5-min parquets directly.

Logic:
  Range window  : 9:30–11:00  → track high/low
  Signal window : 11:00–14:00 → breakout detection
  Entry         : next bar open after signal bar
  Stop          : range_high (LONG) / range_low (SHORT)
  Target        : entry ± range_width × 1.5
  Filters       : close > range_high/low  (breakout close confirmation)
                  volume > 1.5× avg(10 bars before signal)
                  range_width >= 0.5× ATR
  Calm only     : SPY 5-day realized vol <= 0.12
  Max trades    : 3 per day (first signals in universe order)
  Costs         : $0.005/share each way

Usage:
  cd D:\\raits\\raits
  python raits/scripts/irb_test.py
"""

import sys, os, warnings
warnings.filterwarnings("ignore")

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import pandas as pd
import numpy as np
from datetime import time as dtime
from typing import List, Optional

from raits.data_cache import load_market_data

# ── Config ───────────────────────────────────────────────────────────────────
ACCOUNT        = 50_000.0
MAX_RISK_PCT   = 0.01          # 1% per trade = $500
MAX_TRADES_DAY = 3
COST_PER_SHARE = 0.005         # commission + slippage each way

RANGE_END_T    = dtime(11, 0)
SIGNAL_END_T   = dtime(14, 0)
EOD_T          = dtime(15, 55)

VOL_MULT       = 1.5           # breakout bar vol > VOL_MULT × avg_10
MIN_RANGE_ATR  = 0.5           # range_width >= MIN_RANGE_ATR × ATR
TARGET_RR      = 1.5           # target = entry ± range_width × TARGET_RR
ATR_PERIOD     = 14
CALM_THRESHOLD = 0.12          # SPY 5-day annualized realized vol

UNIVERSE = [
    # Mega-cap / momentum stocks
    "TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL",
    # Phase 1
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
    # Phase 2
    "MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM",
    # ETFs (MR universe)
    "XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY",
    "GLD", "QQQ", "IWM",
]



# ── Calm day detection ────────────────────────────────────────────────────────
def compute_calm_dates(spy: pd.DataFrame) -> set:
    """Dates where SPY 5-day realized vol <= CALM_THRESHOLD."""
    daily_close = (spy.between_time("15:50", "16:00")
                      .resample("B")["close"].last().dropna())
    daily_ret   = daily_close.pct_change().dropna()
    calm = set()
    dates = daily_close.index.tolist()
    for i in range(5, len(dates)):
        rv = np.std(daily_ret.iloc[i-5:i].values) * np.sqrt(252)
        if rv <= CALM_THRESHOLD:
            calm.add(dates[i].date())
    return calm


# ── ATR helper ────────────────────────────────────────────────────────────────
def _atr(bars: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    if len(bars) < 2:
        return float(bars["high"].iloc[-1] - bars["low"].iloc[-1]) if len(bars) else 0.01
    hi, lo, cl = bars["high"].values, bars["low"].values, bars["close"].values
    tr = np.maximum(hi[1:] - lo[1:],
                    np.abs(hi[1:] - cl[:-1]),
                    np.abs(lo[1:] - cl[:-1]))
    n = min(period, len(tr))
    return float(np.mean(tr[-n:])) if n > 0 else 0.01


# ── IRB simulation — one day / one ticker ─────────────────────────────────────
def simulate_irb(day_bars: pd.DataFrame, ticker: str, date) -> Optional[dict]:
    # Split bars by window
    range_bars  = day_bars[day_bars.index.time < RANGE_END_T]
    all_bars    = day_bars[day_bars.index.time < dtime(15, 56)]
    signal_bars = day_bars[(day_bars.index.time >= RANGE_END_T) &
                           (day_bars.index.time < SIGNAL_END_T)]

    if len(range_bars) < 8 or len(signal_bars) < 2 or len(all_bars) < 15:
        return None

    # Build range
    range_high  = float(range_bars["high"].max())
    range_low   = float(range_bars["low"].min())
    range_width = range_high - range_low
    if range_width <= 0:
        return None

    # ATR filter
    atr = _atr(range_bars)
    if range_width < MIN_RANGE_ATR * atr:
        return None

    # Build index lookup for volume avg — O(1) lookup
    all_idx    = list(all_bars.index)
    idx_lookup = {ts: i for i, ts in enumerate(all_idx)}

    # Scan signal window for breakout
    sig_ts = sig_dir = None
    for ts, bar in signal_bars.iterrows():
        close = float(bar["close"])
        vol   = float(bar["volume"])

        pos = idx_lookup.get(ts, -1)
        if pos < 10:
            continue
        avg_vol = float(all_bars["volume"].iloc[pos-10:pos].mean())
        if avg_vol <= 0:
            continue
        if vol < VOL_MULT * avg_vol:
            continue

        if close > range_high:
            sig_ts, sig_dir = ts, "LONG"
            break
        if close < range_low:
            sig_ts, sig_dir = ts, "SHORT"
            break

    if sig_ts is None:
        return None

    # Entry: next bar open. pos is already set from the loop's last idx_lookup hit.
    if pos + 1 >= len(all_idx):
        return None
    entry_bar = all_bars.iloc[pos + 1]
    entry     = float(entry_bar["open"])

    # Stop and target
    if sig_dir == "LONG":
        stop   = range_high
        target = entry + range_width * TARGET_RR
        if entry <= stop:      # gapped back below range — skip
            return None
    else:
        stop   = range_low
        target = entry - range_width * TARGET_RR
        if entry >= stop:      # gapped back above range — skip
            return None

    stop_dist = abs(entry - stop)
    if stop_dist < 0.01:
        return None

    # Position size: floor at max(0.5×ATR, 0.5% of price) and cap at 5% notional.
    sizing_dist = max(stop_dist, 0.5 * atr, entry * 0.005)
    shares = max(1, int((ACCOUNT * MAX_RISK_PCT) / sizing_dist))
    shares = min(shares, int(ACCOUNT * 0.05 / entry))  # max 5% account notional per trade

    # Simulate exit starting from entry bar (pos+1) — check high/low on entry bar too.
    remaining = all_bars.iloc[pos + 1:]
    exit_price  = None
    exit_reason = "EOD"

    for ts2, b in remaining.iterrows():
        t         = ts2.time()
        bar_high  = float(b["high"])
        bar_low   = float(b["low"])
        bar_close = float(b["close"])

        if t >= EOD_T:
            exit_price  = bar_close
            exit_reason = "EOD"
            break

        if sig_dir == "LONG":
            if bar_low <= stop:
                exit_price, exit_reason = stop, "STOP_HIT"
                break
            if bar_high >= target:
                exit_price, exit_reason = target, "TARGET_HIT"
                break
        else:
            if bar_high >= stop:
                exit_price, exit_reason = stop, "STOP_HIT"
                break
            if bar_low <= target:
                exit_price, exit_reason = target, "TARGET_HIT"
                break

    if exit_price is None:
        if len(remaining):
            exit_price  = float(remaining.iloc[-1]["close"])
            exit_reason = "EOD"
        else:
            exit_price  = entry
            exit_reason = "EOD"

    # P&L
    raw = ((exit_price - entry) * shares if sig_dir == "LONG"
           else (entry - exit_price) * shares)
    pnl = raw - COST_PER_SHARE * shares * 2

    return {
        "date":     date,
        "ticker":   ticker,
        "dir":      sig_dir,
        "entry":    round(entry, 2),
        "stop":     round(stop, 2),
        "target":   round(target, 2),
        "exit":     round(exit_price, 2),
        "reason":   exit_reason,
        "shares":   shares,
        "pnl":      round(pnl, 2),
    }


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("IRB Standalone Test — Calm Days Only")
    print("=" * 60)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-cache", action="store_true",
                        help="Force re-read parquets and rebuild data cache pkl")
    args = parser.parse_args()

    market = load_market_data(rebuild=args.rebuild_cache)
    spy = market.get("SPY", pd.DataFrame())
    if spy.empty:
        print("[FAIL] SPY missing — run with --rebuild-cache")
        return

    print("Computing Calm days from SPY realized vol...", flush=True)
    calm_dates = compute_calm_dates(spy)
    print(f"  {len(calm_dates)} Calm days found", flush=True)

    all_days = sorted(spy.index.normalize().unique())
    calm_days = [d for d in all_days if d.date() in calm_dates]
    print(f"Simulating {len(calm_days)} Calm trading days...\n")

    trades: List[dict] = []
    for day in calm_days:
        day_trades: List[dict] = []
        for ticker in UNIVERSE:
            if ticker not in market:
                continue
            df = market[ticker]
            mask     = df.index.normalize() == day
            day_bars = df[mask]
            if len(day_bars) < 20:
                continue
            t = simulate_irb(day_bars, ticker, day.date())
            if t:
                day_trades.append(t)
            if len(day_trades) >= MAX_TRADES_DAY:
                break
        trades.extend(day_trades)

    if not trades:
        print("No trades generated.")
        return

    df_t = pd.DataFrame(trades)
    df_t["year"] = pd.to_datetime(df_t["date"]).dt.year
    df_t["win"]  = df_t["pnl"] > 0

    # ── Summary ──────────────────────────────────────────────────────────────
    print("=" * 60)
    print("  IRB RESULTS — CALM DAYS")
    print("=" * 60)
    print(f"\n  {'':18} {'2020':>8} {'2021':>8} {'2022':>8} {'Total':>8}")
    print("  " + "-" * 50)

    rows = {}
    for year in [2020, 2021, 2022]:
        y = df_t[df_t["year"] == year]
        rows[year] = y

    metrics = {
        "Trades":   lambda y: f"{len(y):>8}",
        "Win %":    lambda y: f"{y['win'].mean():>7.1%}",
        "Avg P&L":  lambda y: f"${y['pnl'].mean():>+7.2f}",
        "Total $":  lambda y: f"${y['pnl'].sum():>+7,.0f}",
    }
    for label, fn in metrics.items():
        vals = "".join(fn(rows[yr]) for yr in [2020, 2021, 2022])
        total_fn = fn(df_t)
        print(f"  {label:<18}{vals} {total_fn:>8}")

    wins   = df_t[df_t["win"]]["pnl"]
    losses = df_t[~df_t["win"]]["pnl"]
    pf     = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    print(f"\n  Profit Factor: {pf:.2f}")
    print(f"  Avg Win:  ${wins.mean():+.2f}" if len(wins) else "  Avg Win: n/a")
    print(f"  Avg Loss: ${losses.mean():+.2f}" if len(losses) else "  Avg Loss: n/a")

    # ── Exit breakdown ────────────────────────────────────────────────────────
    print(f"\n  {'Exit Reason':<15} {'Count':>6} {'WR':>6} {'AvgPnL':>9} {'Total':>10}")
    print("  " + "-" * 50)
    for reason, grp in df_t.groupby("reason"):
        print(f"  {reason:<15} {len(grp):>6} {grp['win'].mean():>5.0%} "
              f"  ${grp['pnl'].mean():>+7.2f}  ${grp['pnl'].sum():>+8,.0f}")

    # ── Sample trades ─────────────────────────────────────────────────────────
    print(f"\n  Sample trades (first 30):")
    print(f"  {'Date':<12} {'Ticker':<6} {'Dir':<6} {'Entry':>8} {'Stop':>8} "
          f"{'Target':>8} {'Exit':>8} {'Reason':<12} {'P&L':>8}")
    print("  " + "-" * 82)
    for _, r in df_t.head(30).iterrows():
        print(f"  {str(r['date']):<12} {r['ticker']:<6} {r['dir']:<6} "
              f"${r['entry']:>7.2f} ${r['stop']:>7.2f} ${r['target']:>7.2f} "
              f"${r['exit']:>7.2f} {r['reason']:<12} ${r['pnl']:>+7.2f}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
