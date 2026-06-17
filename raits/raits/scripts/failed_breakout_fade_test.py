"""
scripts/failed_breakout_fade_test.py
-------------------------------------
Standalone backtest for Failed Breakout Fade strategy.
No engine modifications — reads cached 5-min parquets directly.

Hypothesis: ORB breakouts on large-cap momentum stocks fail ~56% of the time.
When a breakout fails (price re-enters the range), trapped breakout traders
must exit, creating momentum in the OPPOSITE direction.

State machine per stock per day:
  WATCH    → detect ORB breakout (9:45-10:15, close outside range + vol)
  BREAKOUT → wait for failure  (bar closes back inside range, up to 11:30)
  FADE     → enter OPPOSITE direction at next bar open

Logic:
  Range window    : 9:30–9:45 (orb_range_minutes=15, same as WFO)
  Breakout window : 9:45–10:15 (same as ORB signal window)
  Failure window  : 9:45–11:30 (failure can lag breakout by up to 1.5 hrs)
  Failure confirm : any bar that closes BACK INSIDE the ORB range after breakout
  Entry direction : OPPOSITE of original breakout
                    (LONG breakout failed → SHORT fade)
                    (SHORT breakout failed → LONG fade)
  Entry timing    : open of bar after failure bar
  Stop            : range_high × 1.005 (SHORT fade) / range_low × 0.995 (LONG fade)
                    0.5% buffer outside the range level — structural invalidation
  Exit            : EOD at 15:55 or stop hit (no trailing — consistent with
                    momentum_cont_test.py final version)
  Max trades      : 3 per day (UNIVERSE order)
  Costs           : $0.005/share each way

Regime hypothesis: expected to work better in Calm (ranging) regime.

Usage:
  cd D:\\raits\\raits
  python raits/scripts/failed_breakout_fade_test.py
  python raits/scripts/failed_breakout_fade_test.py --rebuild-cache
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

ORB_RANGE_END_T = dtime(9, 45)
BREAKOUT_END_T  = dtime(10, 15)
FAILURE_END_T   = dtime(11, 30)
EOD_T           = dtime(15, 55)

VOL_MULT_BREAKOUT   = 1.5
STOP_BUFFER_PCT     = 0.005   # 0.5% outside range level
MAX_FAILURE_LAG_MIN = 15      # only trade fast failures (≤15 min from breakout)
CALM_THRESHOLD      = 0.12
STRESS_THRESHOLD    = 0.25    # proxy for Stress regime (HMM not available standalone)

UNIVERSE = [
    "TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL",
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
    "MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM",
]


# ── Regime day detection ───────────────────────────────────────────────────────
def _compute_regime_dates(spy: pd.DataFrame) -> tuple[set, set]:
    """Return (calm_dates, stress_dates) based on 5-day SPY realized vol."""
    daily_close = (spy.between_time("15:50", "16:00")
                      .resample("B")["close"].last().dropna())
    daily_ret   = daily_close.pct_change().dropna()
    calm, stress = set(), set()
    dates = daily_close.index.tolist()
    for i in range(5, len(dates)):
        rv = np.std(daily_ret.iloc[i-5:i].values) * np.sqrt(252)
        if rv <= CALM_THRESHOLD:
            calm.add(dates[i].date())
        elif rv > STRESS_THRESHOLD:
            stress.add(dates[i].date())
    return calm, stress


# ── Simulate one day / one ticker ──────────────────────────────────────────────
def simulate_fade(day_bars: pd.DataFrame,
                  ticker: str, date) -> Optional[dict]:
    all_bars = day_bars[day_bars.index.time <= EOD_T]
    if len(all_bars) < 10:
        return None

    # ── Step 0: Build ORB range ──────────────────────────────────────────────
    range_bars = all_bars[all_bars.index.time < ORB_RANGE_END_T]
    if len(range_bars) < 3:
        return None

    range_high  = float(range_bars["high"].max())
    range_low   = float(range_bars["low"].min())
    range_width = range_high - range_low
    if range_width <= 0:
        return None

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
            breakout_ts, breakout_dir = ts, "LONG"
            break
        elif close < range_low:
            breakout_ts, breakout_dir = ts, "SHORT"
            break

    if breakout_ts is None:
        return None

    # ── Step 2: Find failure bar (close back inside range, up to 11:30) ─────
    # A LONG breakout fails when a subsequent bar closes below range_high.
    # A SHORT breakout fails when a subsequent bar closes above range_low.
    post_breakout = all_bars[
        (all_bars.index > breakout_ts) &
        (all_bars.index.time < FAILURE_END_T)
    ]
    if len(post_breakout) < 2:
        return None

    failure_ts = None

    for ts, bar in post_breakout.iterrows():
        close = float(bar["close"])
        if breakout_dir == "LONG" and close < range_high:
            failure_ts = ts
            break
        elif breakout_dir == "SHORT" and close > range_low:
            failure_ts = ts
            break

    if failure_ts is None:
        return None  # breakout held — no fade trade

    failure_lag = (failure_ts - breakout_ts).seconds // 60
    if failure_lag > MAX_FAILURE_LAG_MIN:
        return None  # slow failure — no trapped buyer/seller pressure

    # ── Step 3: Entry at open of next bar after failure confirmation ─────────
    post_failure = all_bars[all_bars.index > failure_ts]
    if post_failure.empty:
        return None

    entry_bar_row = post_failure.iloc[0]
    if entry_bar_row.name.time() >= FAILURE_END_T:
        return None  # too late

    entry     = float(entry_bar_row["open"])
    fade_dir  = "SHORT" if breakout_dir == "LONG" else "LONG"

    # Stop: 0.5% outside the range boundary (structural invalidation)
    if fade_dir == "SHORT":
        stop_loss = round(range_high * (1.0 + STOP_BUFFER_PCT), 2)
    else:
        stop_loss = round(range_low * (1.0 - STOP_BUFFER_PCT), 2)

    stop_dist = abs(entry - stop_loss)
    if stop_dist < 0.01:
        return None

    # Sanity: max 5% stop (avoids oversized risk on wide-range days)
    if stop_dist > entry * 0.05:
        return None

    # Check entry side is correct (entry should be inside or near range)
    if fade_dir == "SHORT" and entry >= stop_loss:
        return None  # entry already above stop — invalid
    if fade_dir == "LONG" and entry <= stop_loss:
        return None

    # Position size
    sizing_dist = max(stop_dist, entry * 0.005)
    shares = max(1, int((ACCOUNT * MAX_RISK_PCT) / sizing_dist))
    shares = min(shares, int(ACCOUNT * 0.05 / entry))

    # ── Step 4: Simulate exit — range stop only, hold to EOD ─────────────────
    remaining  = all_bars[all_bars.index >= entry_bar_row.name]
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

        if fade_dir == "SHORT":
            if bar_high >= stop_loss:
                exit_price, exit_reason = stop_loss, "STOP_HIT"
                break
        else:
            if bar_low <= stop_loss:
                exit_price, exit_reason = stop_loss, "STOP_HIT"
                break

    if exit_price is None:
        if not remaining.empty:
            exit_price, exit_reason = float(remaining.iloc[-1]["close"]), "EOD"
        else:
            return None

    raw = ((exit_price - entry) * shares if fade_dir == "LONG"
           else (entry - exit_price) * shares)
    pnl = raw - COST_PER_SHARE * shares * 2

    return {
        "date":          date,
        "ticker":        ticker,
        "breakout_dir":  breakout_dir,
        "fade_dir":      fade_dir,
        "range_high":    round(range_high, 2),
        "range_low":     round(range_low, 2),
        "entry":         round(entry, 2),
        "stop":          round(stop_loss, 2),
        "stop_dist_pct": round(stop_dist / entry * 100, 2),
        "exit":          round(exit_price, 2),
        "reason":        exit_reason,
        "bars_held":     bars_held,
        "failure_lag":   failure_lag,
        "shares":        shares,
        "pnl":           round(pnl, 2),
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

    print(f"\n  {'Fade Dir':<15} {'Count':>6} {'WR':>6} {'AvgPnL':>9} {'Total':>10}")
    print("  " + "-" * 50)
    for d, grp in subset.groupby("fade_dir"):
        print(f"  {d:<15} {len(grp):>6} {grp['win'].mean():>5.0%} "
              f"  ${grp['pnl'].mean():>+7.2f}  ${grp['pnl'].sum():>+8,.0f}")

    print(f"\n  {'Orig Breakout':<15} {'Count':>6} {'WR':>6} {'AvgPnL':>9} {'Total':>10}")
    print("  " + "-" * 50)
    for d, grp in subset.groupby("breakout_dir"):
        print(f"  {d:<15} {len(grp):>6} {grp['win'].mean():>5.0%} "
              f"  ${grp['pnl'].mean():>+7.2f}  ${grp['pnl'].sum():>+8,.0f}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Failed Breakout Fade Test — 2020-2022 OOS")
    print("Hypothesis: fade ORB breakouts that fail (re-enter range)")
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

    print("Computing regime days...", flush=True)
    calm_dates, stress_dates = _compute_regime_dates(spy)
    print(f"  {len(calm_dates)} Calm days, {len(stress_dates)} Stress days in full dataset", flush=True)

    print(f"Simulating {len(UNIVERSE)} tickers...", flush=True)

    trades: List[dict] = []
    ticker_order = {t: i for i, t in enumerate(UNIVERSE)}

    all_days = sorted(spy.index.normalize().unique())
    oos_days = [d for d in all_days if 2020 <= d.year <= 2022]

    for ticker in UNIVERSE:
        if ticker not in market:
            continue
        df = market[ticker]

        for day_ts in oos_days:
            mask     = df.index.normalize() == day_ts
            day_bars = df[mask]
            if len(day_bars) < 10:
                continue

            t = simulate_fade(day_bars, ticker, day_ts.date())
            if t:
                t["is_calm"]     = day_ts.date() in calm_dates
                t["is_stress"]   = day_ts.date() in stress_dates
                t["ticker_rank"] = ticker_order[ticker]
                trades.append(t)

    if not trades:
        print("No trades generated.")
        return

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

    # ── Option B: Fade only when ORB not active (Calm + Stress) ──────────────
    # Engine: ORB fires in Normal regime only (Calm→VWAP_MR, Stress→TF)
    # Proxy: Calm = vol ≤ 0.12, Stress = vol > 0.25, Normal = in between
    df_orb_off = df_t[df_t["is_calm"] | df_t["is_stress"]]
    df_normal  = df_t[~df_t["is_calm"] & ~df_t["is_stress"]]
    print(f"\n{'=' * 70}")
    print(f"  OPTION B — Fade fires only when ORB not active")
    print(f"  Regime proxy: Calm (vol≤0.12) + Stress (vol>0.25)")
    print(f"  Normal days ({len(df_normal)} trades) blocked — ORB would conflict")
    print(f"{'=' * 70}")
    print_summary("OPTION B: CALM + STRESS (ORB off)", df_orb_off)
    print_summary("  Calm only",   df_t[df_t["is_calm"]])
    print_summary("  Stress only", df_t[df_t["is_stress"]])

    # Failure lag analysis
    print(f"\n{'=' * 70}")
    print(f"  FAILURE LAG (minutes from breakout to re-entry)")
    print(f"{'=' * 70}")
    for cutoff, label in [(5, "≤5 min (immediate)"), (15, "≤15 min"),
                          (30, "≤30 min"), (60, "≤60 min")]:
        n = (df_t["failure_lag"] <= cutoff).sum()
        print(f"  {label:<25}: {n:>4}  ({n/len(df_t):.0%})")
    print(f"  {'Avg lag':<25}: {df_t['failure_lag'].mean():.0f} min")
    print(f"  {'Median lag':<25}: {df_t['failure_lag'].median():.0f} min")

    # By failure lag bucket — does faster failure = better fade edge?
    print(f"\n  WR by failure lag:")
    df_t["lag_bucket"] = pd.cut(df_t["failure_lag"],
                                 bins=[0, 5, 15, 30, 60, 999],
                                 labels=["0-5m", "5-15m", "15-30m", "30-60m", "60m+"])
    for bucket, grp in df_t.groupby("lag_bucket", observed=True):
        print(f"  {str(bucket):<10}: {len(grp):>4} trades, "
              f"WR {grp['win'].mean():.0%}, "
              f"Avg ${grp['pnl'].mean():>+.2f}, "
              f"PF {grp[grp['win']]['pnl'].sum() / abs(grp[~grp['win']]['pnl'].sum()):.2f}"
              if grp[~grp["win"]]["pnl"].sum() != 0 else
              f"  {str(bucket):<10}: {len(grp):>4} trades, WR {grp['win'].mean():.0%}")

    # Sample trades
    print(f"\n  Sample trades (first 30):")
    print(f"  {'Date':<12} {'Ticker':<6} {'Orig':<6} {'Fade':<6} "
          f"{'Lag':>5} {'Entry':>8} {'Stop':>8} {'Exit':>8} "
          f"{'Reason':<12} {'Calm':>5} {'P&L':>8}")
    print("  " + "-" * 95)
    for _, r in df_t.head(30).iterrows():
        print(f"  {str(r['date']):<12} {r['ticker']:<6} {r['breakout_dir']:<6} "
              f"{r['fade_dir']:<6} {r['failure_lag']:>4}m "
              f"${r['entry']:>7.2f} ${r['stop']:>7.2f} ${r['exit']:>7.2f} "
              f"{r['reason']:<12} {'Y' if r['is_calm'] else 'N':>5} "
              f"${r['pnl']:>+7.2f}")

    print("\n" + "=" * 70)
    print(f"  Total trades: {len(df_t)} | Net P&L: ${df_t['pnl'].sum():+,.2f}")
    total_ticker_days = len(UNIVERSE) * len(oos_days)
    print(f"  Signal rate:  {len(df_t)}/{total_ticker_days} = {len(df_t)/total_ticker_days:.1%}")
    print("=" * 70)

    # ── Drawdown Analysis ─────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  DRAWDOWN ANALYSIS")
    print(f"{'=' * 70}")

    daily = (df_t.groupby("date")["pnl"].sum()
               .reset_index()
               .sort_values("date"))
    daily["cum_pnl"]  = daily["pnl"].cumsum()
    daily["peak"]     = daily["cum_pnl"].cummax()
    daily["drawdown"] = daily["cum_pnl"] - daily["peak"]

    max_dd = daily["drawdown"].min()

    # Max drawdown duration (consecutive days below peak)
    max_dd_days = current_dd_days = 0
    for dd in daily["drawdown"]:
        if dd < 0:
            current_dd_days += 1
            max_dd_days = max(max_dd_days, current_dd_days)
        else:
            current_dd_days = 0

    # Recovery: find when worst DD started and when it recovered
    worst_idx  = daily["drawdown"].idxmin()
    peak_before = daily.loc[:worst_idx, "cum_pnl"].idxmax()
    recovery    = daily.loc[worst_idx:][daily.loc[worst_idx:, "drawdown"] >= 0]
    recovery_date = str(recovery.iloc[0]["date"]) if not recovery.empty else "not yet"

    print(f"  Max Drawdown:        ${max_dd:+,.2f}")
    print(f"  Max DD start:        {daily.loc[peak_before, 'date']}")
    print(f"  Max DD trough:       {daily.loc[worst_idx, 'date']}")
    print(f"  Recovery by:         {recovery_date}")
    print(f"  Max DD duration:     {max_dd_days} trading days below peak")

    # Consecutive losses
    df_sorted      = df_t.sort_values("date")
    max_consec_loss = curr = 0
    for win in df_sorted["win"]:
        curr = curr + 1 if not win else 0
        max_consec_loss = max(max_consec_loss, curr)
    print(f"  Max consec losses:   {max_consec_loss} trades")

    # Calmar proxy: annualized return / max drawdown
    ann_return = df_t["pnl"].sum() / 3.0   # 3 OOS years
    calmar = ann_return / abs(max_dd) if max_dd != 0 else float("inf")
    print(f"  Calmar (proxy):      {calmar:.2f}  "
          f"(ann ${ann_return:+,.0f} / MaxDD ${abs(max_dd):,.0f})")

    # ── ORB Conflict Analysis ─────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  ORB CONFLICT ANALYSIS")
    print(f"{'=' * 70}")
    print(f"""
  Every Fade trade is triggered by an ORB breakout (same detection logic).
  ORB would ALSO enter on that breakout in the same direction.
  When Fade fires (opposite direction), ORB is still open.

  Timeline:
    T+0  : breakout bar closes → ORB entry next bar
    T+5  : ORB is now in trade (LONG or SHORT)
    T+{df_t['failure_lag'].median():.0f}  : failure confirmed (median lag)
    T+{df_t['failure_lag'].median()+5:.0f} : Fade entry (next bar after failure)
    → ORB has been open for ~{df_t['failure_lag'].median()+5:.0f} min when Fade fires

  During this window, ORB stop (at range_low for LONG) is NOT hit yet —
  failure only requires price to re-enter range, not reach range_low.

  Conflicts: ~{len(df_t)}/{len(df_t)} Fade trades (100%) run while ORB is open.
""")
    print(f"  Options for engine integration:")
    print(f"    A) Fade entry = ORB exit signal (exit ORB, enter Fade same bar)")
    print(f"    B) Fade blocked if ORB open on same ticker")
    print(f"    C) Fade and ORB use shared position slot (one replaces the other)")
    print(f"")
    print(f"  Recommendation: Option A — cleaner, captures both legs.")
    print(f"  Net effect: ORB+Fade = enter on breakout, reverse if fails ≤15 min.")


if __name__ == "__main__":
    main()
