"""
scripts/gap_fill_test.py
------------------------
Standalone backtest for Gap Fill strategy.
No engine modifications — reads cached 5-min parquets directly.

Logic:
  Gap detection : today open vs prior day close
                  MIN_GAP_PCT = 0.3%  — ignore micro-gaps / noise
                  MAX_GAP_PCT = 4.0%  — ignore news-driven blowouts
  Direction     : Gap Up  (open > prev_close) → SHORT (fade back to prev_close)
                  Gap Down (open < prev_close) → LONG  (fade up to prev_close)
  Entry timing  : 9:35 AM bar open (after first volatile bar settles)
  Skip if       : price already filled before 9:35 (no room left)
  Target        : prior close (the "fill" level)
  Stop          : ATR_MULT (1.5) × ATR beyond entry
  Min R:R       : 1.0 (reward / stop_dist)
  EOD exit      : 15:55 close if target/stop not reached
  Max trades    : 3 per day (first N in UNIVERSE order)
  Costs         : $0.005/share each way

Results reported in three slices:
  - All days
  - Calm days (SPY 5-day realized vol <= 0.12)
  - Non-Calm days

Usage:
  cd D:\\raits\\raits
  python raits/scripts/gap_fill_test.py
  python raits/scripts/gap_fill_test.py --rebuild-cache
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

MIN_GAP_PCT    = 0.003         # 0.3% minimum gap
MAX_GAP_PCT    = 0.040         # 4.0% max — above this is news-driven, too risky
ATR_MULT       = 1.5           # stop = entry ± ATR_MULT × ATR
ATR_PERIOD     = 14
MIN_RR         = 1.0           # min reward:risk to take trade
ENTRY_T        = dtime(9, 35)  # enter at open of second bar
EOD_T          = dtime(15, 55)
CALM_THRESHOLD = 0.12

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


# ── Gap Fill simulation — one day / one ticker ─────────────────────────────────
def simulate_gap_fill(day_bars: pd.DataFrame, prev_close: float,
                      ticker: str, date) -> Optional[dict]:
    all_bars = day_bars[day_bars.index.time <= EOD_T]
    if len(all_bars) < 5:
        return None

    # Gap = (today's open - prev_close) / prev_close
    today_open = float(all_bars.iloc[0]["open"])
    gap_pct    = (today_open - prev_close) / prev_close

    if abs(gap_pct) < MIN_GAP_PCT:
        return None
    if abs(gap_pct) > MAX_GAP_PCT:
        return None

    direction = "SHORT" if gap_pct > 0 else "LONG"
    target    = prev_close

    # Entry bar: first bar at or after 9:35
    entry_bars = all_bars[all_bars.index.time >= ENTRY_T]
    if entry_bars.empty:
        return None
    entry_bar  = entry_bars.iloc[0]
    entry      = float(entry_bar["open"])

    # Skip if gap already filled before our entry
    if direction == "SHORT" and entry <= prev_close:
        return None
    if direction == "LONG" and entry >= prev_close:
        return None

    # ATR from pre-entry bars
    pre_bars  = all_bars[all_bars.index.time < ENTRY_T]
    atr       = _atr(pre_bars) if len(pre_bars) >= 2 else _atr(all_bars.iloc[:5])
    stop_dist = ATR_MULT * atr

    stop_loss = (entry + stop_dist) if direction == "SHORT" else (entry - stop_dist)

    # R:R gate
    reward = abs(entry - target)
    if stop_dist <= 0 or reward / stop_dist < MIN_RR:
        return None

    # Position size
    sizing_dist = max(stop_dist, entry * 0.005)
    shares = max(1, int((ACCOUNT * MAX_RISK_PCT) / sizing_dist))
    shares = min(shares, int(ACCOUNT * 0.05 / entry))

    # Simulate exit bar-by-bar from entry bar
    exit_price  = None
    exit_reason = "EOD"

    for ts, b in entry_bars.iterrows():
        t        = ts.time()
        bar_high = float(b["high"])
        bar_low  = float(b["low"])
        bar_close = float(b["close"])

        if t >= EOD_T:
            exit_price, exit_reason = bar_close, "EOD"
            break

        if direction == "SHORT":
            if bar_high >= stop_loss:
                exit_price, exit_reason = stop_loss, "STOP_HIT"
                break
            if bar_low <= target:
                exit_price, exit_reason = target, "TARGET_HIT"
                break
        else:
            if bar_low <= stop_loss:
                exit_price, exit_reason = stop_loss, "STOP_HIT"
                break
            if bar_high >= target:
                exit_price, exit_reason = target, "TARGET_HIT"
                break

    if exit_price is None:
        if not entry_bars.empty:
            exit_price, exit_reason = float(entry_bars.iloc[-1]["close"]), "EOD"
        else:
            return None

    raw = ((exit_price - entry) * shares if direction == "LONG"
           else (entry - exit_price) * shares)
    pnl = raw - COST_PER_SHARE * shares * 2

    return {
        "date":       date,
        "ticker":     ticker,
        "dir":        direction,
        "gap_pct":    round(gap_pct * 100, 2),
        "prev_close": round(prev_close, 2),
        "entry":      round(entry, 2),
        "stop":       round(stop_loss, 2),
        "target":     round(target, 2),
        "exit":       round(exit_price, 2),
        "reason":     exit_reason,
        "shares":     shares,
        "pnl":        round(pnl, 2),
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

    # Direction breakdown
    print(f"\n  {'Direction':<15} {'Count':>6} {'WR':>6} {'AvgPnL':>9} {'Total':>10}")
    print("  " + "-" * 50)
    for d, grp in subset.groupby("dir"):
        print(f"  {d:<15} {len(grp):>6} {grp['win'].mean():>5.0%} "
              f"  ${grp['pnl'].mean():>+7.2f}  ${grp['pnl'].sum():>+8,.0f}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Gap Fill Standalone Test — 2020-2022 OOS")
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
    print(f"  {len(calm_dates)} Calm days found in full dataset", flush=True)

    print(f"Simulating gap fill across {len(UNIVERSE)} tickers...", flush=True)

    trades: List[dict] = []
    ticker_order = {t: i for i, t in enumerate(UNIVERSE)}

    for ticker in UNIVERSE:
        if ticker not in market:
            continue
        df = market[ticker]

        # Build daily close lookup
        eod = df.between_time("15:50", "16:00")
        daily_closes_s = eod.resample("B")["close"].last().dropna()
        if len(daily_closes_s) < 2:
            continue
        daily_closes  = {dt.date(): float(c) for dt, c in daily_closes_s.items()}
        dates_sorted  = sorted(daily_closes.keys())

        for i in range(1, len(dates_sorted)):
            date = dates_sorted[i]

            if date.year < 2020 or date.year > 2022:
                continue

            prev_date  = dates_sorted[i - 1]
            prev_close = daily_closes.get(prev_date)
            if prev_close is None or prev_close <= 0:
                continue

            day_ts   = pd.Timestamp(date)
            day_bars = df[df.index.normalize() == day_ts]
            if len(day_bars) < 5:
                continue

            t = simulate_gap_fill(day_bars, prev_close, ticker, date)
            if t:
                t["is_calm"]     = date in calm_dates
                t["ticker_rank"] = ticker_order[ticker]
                trades.append(t)

    if not trades:
        print("No trades generated.")
        return

    # Apply max-trades-per-day cap in UNIVERSE order
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

    # Sample trades
    print(f"\n  Sample trades (first 30):")
    print(f"  {'Date':<12} {'Ticker':<6} {'Dir':<6} {'Gap%':>6} {'Entry':>8} "
          f"{'Stop':>8} {'Target':>8} {'Exit':>8} {'Reason':<12} {'Calm':>5} {'P&L':>8}")
    print("  " + "-" * 95)
    for _, r in df_t.head(30).iterrows():
        print(f"  {str(r['date']):<12} {r['ticker']:<6} {r['dir']:<6} "
              f"{r['gap_pct']:>+5.1f}% ${r['entry']:>7.2f} ${r['stop']:>7.2f} "
              f"${r['target']:>7.2f} ${r['exit']:>7.2f} {r['reason']:<12} "
              f"{'Y' if r['is_calm'] else 'N':>5} ${r['pnl']:>+7.2f}")

    print("\n" + "=" * 70)
    print(f"  Total trades: {len(df_t)} | Net P&L: ${df_t['pnl'].sum():+,.2f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
