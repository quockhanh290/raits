"""
scripts/momentum_cont_test.py
------------------------------
Standalone backtest for Momentum Continuation strategy.
No engine modifications — reads cached 5-min parquets directly.

Concept: trade the RETEST of an ORB breakout, not the initial breakout.
  After ORB breaks out, wait for price to pull back to the breakout level,
  then enter when momentum resumes. Reduces false breakout entries.

State machine per stock per day:
  WATCH      → waiting for ORB breakout (9:45-10:15)
  BREAKOUT   → breakout confirmed, waiting for pullback
  PULLBACK   → retest detected, waiting for resume bar
  ENTRY      → resume confirmed, enter next bar open

Logic:
  Range window      : 9:30–9:45 (orb_range_minutes=15, consistent with WFO)
  Breakout window   : 9:45–10:15 (same as ORB signal window)
  Pullback window   : up to 11:30 (give time for flag to form)
  Breakout trigger  : bar closes outside range + volume > 1.5× avg
  Pullback trigger  : subsequent bar's extreme comes within 0.5% of breakout level
  Resume trigger    : bar after pullback closes back in breakout direction
  Entry             : open of bar after resume
  Stop              : pullback bar extreme (structural, not ATR-based)
  Trailing exit     : Chandelier trailing stop (highest_high - 2.5×ATR for LONG)
  EOD exit          : 15:55 close
  Max trades        : 3 per day (first N in UNIVERSE order)
  Costs             : $0.005/share each way

Universe: same 8 mega-caps as the main backtest ORB universe.

Usage:
  cd D:\\raits\\raits
  python raits/scripts/momentum_cont_test.py
  python raits/scripts/momentum_cont_test.py --rebuild-cache
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

# ── Config ────────────────────────────────────────────────────────────────────
ACCOUNT        = 50_000.0
MAX_RISK_PCT   = 0.01
MAX_TRADES_DAY = 3
COST_PER_SHARE = 0.005

ORB_RANGE_END_T   = dtime(9, 45)   # end of range formation window
BREAKOUT_END_T    = dtime(10, 15)  # no new breakout detections after this
PULLBACK_END_T    = dtime(11, 30)  # no new entries after 11:30
EOD_T             = dtime(15, 55)

VOL_MULT_BREAKOUT    = 1.5    # breakout bar volume > 1.5× pre-range avg
PULLBACK_THRESHOLD   = 0.005  # pullback bar extreme within 0.5% of breakout level
CHANDELIER_ATR_MULT  = 2.5    # trailing stop = highest_high - 2.5×ATR
ATR_PERIOD           = 10     # use opening range bars for ATR estimate
CALM_THRESHOLD       = 0.12

UNIVERSE = [
    "TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL",
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
    "MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM",
]


# ── Calm day detection ─────────────────────────────────────────────────────────
def compute_calm_dates(spy: pd.DataFrame) -> set:
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


# ── ATR helper ─────────────────────────────────────────────────────────────────
def _atr(bars: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    if len(bars) < 2:
        return float(bars["high"].iloc[-1] - bars["low"].iloc[-1]) if len(bars) else 0.01
    hi = bars["high"].values
    lo = bars["low"].values
    cl = bars["close"].values
    tr = np.maximum(hi[1:] - lo[1:],
                    np.abs(hi[1:] - cl[:-1]),
                    np.abs(lo[1:] - cl[:-1]))
    n = min(period, len(tr))
    return float(np.mean(tr[-n:])) if n > 0 else 0.01


# ── Simulate one day / one ticker ──────────────────────────────────────────────
def simulate_momentum_cont(day_bars: pd.DataFrame,
                           ticker: str, date) -> Optional[dict]:
    all_bars = day_bars[day_bars.index.time <= EOD_T]
    if len(all_bars) < 10:
        return None

    # ── Step 0: Build ORB range ──────────────────────────────────────────────
    range_bars = all_bars[all_bars.index.time < ORB_RANGE_END_T]
    if len(range_bars) < 3:
        return None

    range_high = float(range_bars["high"].max())
    range_low  = float(range_bars["low"].min())
    range_width = range_high - range_low
    if range_width <= 0:
        return None

    # Volume baseline from range bars
    avg_vol = float(range_bars["volume"].mean())
    if avg_vol <= 0:
        return None

    # ── Step 1: Find breakout bar (9:45-10:15) ───────────────────────────────
    breakout_bars = all_bars[
        (all_bars.index.time >= ORB_RANGE_END_T) &
        (all_bars.index.time < BREAKOUT_END_T)
    ]
    if len(breakout_bars) < 2:
        return None

    breakout_ts  = None
    breakout_dir = None

    for ts, bar in breakout_bars.iterrows():
        close = float(bar["close"])
        vol   = float(bar["volume"])

        if vol < VOL_MULT_BREAKOUT * avg_vol:
            continue

        if close > range_high:
            breakout_ts  = ts
            breakout_dir = "LONG"
            break
        elif close < range_low:
            breakout_ts  = ts
            breakout_dir = "SHORT"
            break

    if breakout_ts is None:
        return None  # no confirmed breakout in signal window

    # ── Step 2: Find pullback bar (after breakout, up to 11:30) ─────────────
    # Pullback = bar whose extreme comes back within PULLBACK_THRESHOLD of
    # the breakout level (range_high for LONG, range_low for SHORT).
    post_breakout = all_bars[
        (all_bars.index > breakout_ts) &
        (all_bars.index.time < PULLBACK_END_T)
    ]
    if len(post_breakout) < 2:
        return None

    pullback_ts  = None
    pullback_bar = None

    for ts, bar in post_breakout.iterrows():
        if breakout_dir == "LONG":
            # LONG: bar's low comes back down within 0.5% above range_high
            if float(bar["low"]) <= range_high * (1.0 + PULLBACK_THRESHOLD):
                pullback_ts  = ts
                pullback_bar = bar
                break
        else:  # SHORT
            # SHORT: bar's high bounces back up within 0.5% below range_low
            if float(bar["high"]) >= range_low * (1.0 - PULLBACK_THRESHOLD):
                pullback_ts  = ts
                pullback_bar = bar
                break

    if pullback_ts is None:
        return None  # no pullback/retest — skip

    # Validate: pullback bar must not break the range in opposite direction.
    # (Protects against a bar that wicks through the range = failed breakout)
    if breakout_dir == "LONG" and float(pullback_bar["close"]) < range_low:
        return None
    if breakout_dir == "SHORT" and float(pullback_bar["close"]) > range_high:
        return None

    # ── Step 3: Find resume bar (bar after pullback that re-confirms direction)
    post_pullback = all_bars[
        (all_bars.index > pullback_ts) &
        (all_bars.index.time < PULLBACK_END_T)
    ]
    if len(post_pullback) < 2:
        return None

    resume_ts = None

    pullback_high = float(pullback_bar["high"])
    pullback_low  = float(pullback_bar["low"])

    for ts, bar in post_pullback.iterrows():
        if breakout_dir == "LONG":
            if float(bar["close"]) > pullback_high:
                resume_ts = ts
                break
        else:
            if float(bar["close"]) < pullback_low:
                resume_ts = ts
                break

    if resume_ts is None:
        return None  # momentum didn't resume after pullback — no trade

    # ── Step 4: Entry at open of next bar after resume ───────────────────────
    post_resume = all_bars[all_bars.index > resume_ts]
    if post_resume.empty:
        return None

    entry_bar_row = post_resume.iloc[0]
    if entry_bar_row.name.time() >= PULLBACK_END_T:
        return None  # too late to enter

    entry = float(entry_bar_row["open"])

    # Stop: breakout level (range_high / range_low).
    # Using pullback_bar.low was too tight — a 5-min bar's range is just
    # noise. The trade is only invalid when price re-enters the ORB range,
    # which is the correct structural invalidation level.
    if breakout_dir == "LONG":
        stop_loss = round(range_high - 0.01, 2)
    else:
        stop_loss = round(range_low + 0.01, 2)

    stop_dist = abs(entry - stop_loss)
    if stop_dist < 0.01:
        return None

    # Sanity: stop_dist shouldn't exceed 5% of price (ATR sanity)
    if stop_dist > entry * 0.05:
        return None

    # Position size
    sizing_dist = max(stop_dist, entry * 0.005)
    shares = max(1, int((ACCOUNT * MAX_RISK_PCT) / sizing_dist))
    shares = min(shares, int(ACCOUNT * 0.05 / entry))

    # ── Step 5: Simulate exit — range stop only, hold to EOD ────────────────
    # Chandelier trailing removed: it exits 46% of trades at 35% WR (below
    # breakeven), cutting trades that would otherwise reach EOD at 88% WR.
    # Test: maximize EOD exposure with only structural stop.
    remaining = all_bars[all_bars.index >= entry_bar_row.name]

    exit_price  = None
    exit_reason = "EOD"
    bars_held   = 0

    for ts, b in remaining.iterrows():
        t         = ts.time()
        bar_high  = float(b["high"])
        bar_low   = float(b["low"])
        bar_close = float(b["close"])
        bars_held += 1

        if t >= EOD_T:
            exit_price, exit_reason = bar_close, "EOD"
            break

        if breakout_dir == "LONG":
            if bar_low <= stop_loss:
                exit_price, exit_reason = stop_loss, "STOP_HIT"
                break
        else:
            if bar_high >= stop_loss:
                exit_price, exit_reason = stop_loss, "STOP_HIT"
                break

    if exit_price is None:
        if not remaining.empty:
            exit_price, exit_reason = float(remaining.iloc[-1]["close"]), "EOD"
        else:
            return None

    raw = ((exit_price - entry) * shares if breakout_dir == "LONG"
           else (entry - exit_price) * shares)
    pnl = raw - COST_PER_SHARE * shares * 2

    stop_dist_pct = abs(entry - stop_loss) / entry * 100

    return {
        "date":           date,
        "ticker":         ticker,
        "dir":            breakout_dir,
        "range_high":     round(range_high, 2),
        "range_low":      round(range_low, 2),
        "entry":          round(entry, 2),
        "stop":           round(stop_loss, 2),
        "stop_dist_pct":  round(stop_dist_pct, 2),
        "exit":           round(exit_price, 2),
        "reason":         exit_reason,
        "bars_held":      bars_held,
        "shares":         shares,
        "pnl":          round(pnl, 2),
    }


# ── Print summary block ────────────────────────────────────────────────────────
def print_summary(label: str, subset: pd.DataFrame):
    if subset.empty:
        print(f"\n{label}: No trades")
        return
    print(f"\n{'=' * 70}")
    print(f"  {label}  (n={len(subset)})")
    print(f"{'=' * 70}")
    print(f"  {'':18} {'2020':>8} {'2021':>8} {'2022':>8} {'Total':>8}")
    print("  " + "-" * 55)

    rows = {yr: subset[subset["year"] == yr] for yr in [2020, 2021, 2022]}

    def fmt(fn, y):
        return fn(y) if len(y) else f"{'n/a':>8}"

    metrics = {
        "Trades":   lambda y: f"{len(y):>8}",
        "Win %":    lambda y: f"{y['win'].mean():>7.1%}",
        "Avg P&L":  lambda y: f"${y['pnl'].mean():>+7.2f}",
        "Total $":  lambda y: f"${y['pnl'].sum():>+7,.0f}",
    }
    for m_label, fn in metrics.items():
        vals = "".join(fmt(fn, rows[yr]) for yr in [2020, 2021, 2022])
        print(f"  {m_label:<18}{vals} {fn(subset):>8}")

    wins   = subset[subset["win"]]["pnl"]
    losses = subset[~subset["win"]]["pnl"]
    pf     = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    print(f"\n  Profit Factor: {pf:.2f}")
    if len(wins):
        print(f"  Avg Win:  ${wins.mean():+.2f}")
    if len(losses):
        print(f"  Avg Loss: ${losses.mean():+.2f}")

    print(f"\n  {'Exit Reason':<15} {'Count':>6} {'WR':>6} {'AvgPnL':>9} {'Total':>10}")
    print("  " + "-" * 50)
    for reason, grp in subset.groupby("reason"):
        print(f"  {reason:<15} {len(grp):>6} {grp['win'].mean():>5.0%} "
              f"  ${grp['pnl'].mean():>+7.2f}  ${grp['pnl'].sum():>+8,.0f}")

    print(f"\n  {'Direction':<15} {'Count':>6} {'WR':>6} {'AvgPnL':>9} {'Total':>10}")
    print("  " + "-" * 50)
    for d, grp in subset.groupby("dir"):
        print(f"  {d:<15} {len(grp):>6} {grp['win'].mean():>5.0%} "
              f"  ${grp['pnl'].mean():>+7.2f}  ${grp['pnl'].sum():>+8,.0f}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Momentum Continuation Test — 2020-2022 OOS")
    print("State machine: breakout → pullback → resume → trailing stop")
    print("=" * 70)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-cache", action="store_true",
                        help="Force re-read parquets and rebuild pkl")
    args = parser.parse_args()

    market = load_market_data(rebuild=args.rebuild_cache)
    spy    = market.get("SPY", pd.DataFrame())
    if spy.empty:
        print("[FAIL] SPY missing — run with --rebuild-cache")
        return

    print("Computing Calm days...", flush=True)
    calm_dates = compute_calm_dates(spy)
    print(f"  {len(calm_dates)} Calm days in full dataset", flush=True)

    print(f"Simulating {len(UNIVERSE)} tickers...", flush=True)

    trades: List[dict] = []
    ticker_order = {t: i for i, t in enumerate(UNIVERSE)}

    all_days = sorted(spy.index.normalize().unique())
    oos_days = [d for d in all_days if 2020 <= d.year <= 2022]

    for ticker in UNIVERSE:
        if ticker not in market:
            print(f"  [WARN] {ticker} not in market data — skipped")
            continue
        df = market[ticker]

        for day_ts in oos_days:
            mask     = df.index.normalize() == day_ts
            day_bars = df[mask]
            if len(day_bars) < 10:
                continue

            t = simulate_momentum_cont(day_bars, ticker, day_ts.date())
            if t:
                t["is_calm"]     = day_ts.date() in calm_dates
                t["ticker_rank"] = ticker_order[ticker]
                trades.append(t)

    if not trades:
        print("No trades generated.")
        return

    # Apply max-trades-per-day cap (UNIVERSE order)
    df_t = pd.DataFrame(trades)
    df_t = (df_t.sort_values(["date", "ticker_rank"])
                .groupby("date")
                .head(MAX_TRADES_DAY)
                .reset_index(drop=True))
    df_t["year"] = pd.to_datetime(df_t["date"]).dt.year
    df_t["win"]  = df_t["pnl"] > 0

    print_summary("ALL DAYS",      df_t)
    print_summary("CALM DAYS",     df_t[df_t["is_calm"]])
    print_summary("NON-CALM DAYS", df_t[~df_t["is_calm"]])

    # ── STOP_HIT Diagnostic ──────────────────────────────────────────────────
    stops = df_t[df_t["reason"] == "STOP_HIT"].copy()
    print(f"\n{'=' * 70}")
    print(f"  STOP_HIT DIAGNOSTIC  (n={len(stops)})")
    print(f"{'=' * 70}")

    # Timing: how quickly are we stopped out?
    print(f"\n  Bars held before STOP_HIT (5-min bars):")
    for cutoff, label in [(1, "1 bar (≤5 min)"), (2, "2 bars (≤10 min)"),
                          (4, "4 bars (≤20 min)"), (12, "12 bars (≤1 hr)")]:
        n = (stops["bars_held"] <= cutoff).sum()
        print(f"    {label:<22}: {n:>4}  ({n/len(stops):.0%})")
    print(f"    {'Avg bars held':<22}: {stops['bars_held'].mean():.1f}")
    print(f"    {'Median bars held':<22}: {stops['bars_held'].median():.0f}")

    # Stop distance distribution
    print(f"\n  Stop distance (entry→range level) as % of price:")
    for cutoff, label in [(0.5, "≤0.5%"), (1.0, "≤1.0%"), (2.0, "≤2.0%"), (3.0, "≤3.0%")]:
        n = (stops["stop_dist_pct"] <= cutoff).sum()
        print(f"    {label:<8}: {n:>4}  ({n/len(stops):.0%})")
    print(f"    {'Avg dist':<8}: {stops['stop_dist_pct'].mean():.2f}%")

    # Worst tickers by total STOP_HIT loss
    print(f"\n  Worst tickers (STOP_HIT total loss):")
    ticker_loss = (stops.groupby("ticker")["pnl"]
                        .agg(["sum", "count"])
                        .sort_values("sum")
                        .head(10))
    for ticker, row in ticker_loss.iterrows():
        print(f"    {ticker:<6}: ${row['sum']:>+8,.0f}  ({int(row['count'])} stops)")

    # Worst losing trades overall
    print(f"\n  10 largest individual losses:")
    print(f"  {'Date':<12} {'Ticker':<6} {'Dir':<6} {'Stop%':>6} {'Bars':>5} {'P&L':>9}")
    print("  " + "-" * 50)
    for _, r in df_t.nsmallest(10, "pnl").iterrows():
        print(f"  {str(r['date']):<12} {r['ticker']:<6} {r['dir']:<6} "
              f"{r['stop_dist_pct']:>5.1f}% {r['bars_held']:>5} ${r['pnl']:>+8.2f}")

    # Sample trades
    print(f"\n  Sample trades (first 30):")
    print(f"  {'Date':<12} {'Ticker':<6} {'Dir':<6} {'Entry':>8} {'Stop':>8} "
          f"{'Exit':>8} {'Reason':<12} {'Calm':>5} {'P&L':>8}")
    print("  " + "-" * 80)
    for _, r in df_t.head(30).iterrows():
        print(f"  {str(r['date']):<12} {r['ticker']:<6} {r['dir']:<6} "
              f"${r['entry']:>7.2f} ${r['stop']:>7.2f} ${r['exit']:>7.2f} "
              f"{r['reason']:<12} {'Y' if r['is_calm'] else 'N':>5} ${r['pnl']:>+7.2f}")

    print("\n" + "=" * 70)
    print(f"  Total trades: {len(df_t)} | Net P&L: ${df_t['pnl'].sum():+,.2f}")

    # Filter rate info
    total_ticker_days = len(UNIVERSE) * len(oos_days)
    print(f"  Signal rate: {len(df_t)}/{total_ticker_days} "
          f"ticker-days = {len(df_t)/total_ticker_days:.1%}")
    print("=" * 70)


if __name__ == "__main__":
    main()
