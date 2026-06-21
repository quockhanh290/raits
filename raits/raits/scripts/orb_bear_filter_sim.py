"""
orb_bear_filter_sim.py — SPY 200MA filter cho ORB trong bear market.

Hypothesis: ORB fail trong 2022 bear market vì breakouts không follow through
khi market trend đang down. Filter: skip ORB khi SPY close < SPY 200-day MA.

Approach: retroactive — load ORB trades từ PKL, apply filter, compare P&L delta.

Usage:
    cd D:\raits\raits
    python raits\scripts\orb_bear_filter_sim.py
"""
import sys, os, pickle, glob as _glob
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
CACHE_5MIN  = r'd:\raits\raits\data\cache\data'

# ── Load SPY 5-min → derive daily closes ─────────────────────────────
print("Loading SPY 5-min parquets...")
spy_files = _glob.glob(os.path.join(CACHE_5MIN, "SPY_5min_*.parquet"))
print(f"  Found {len(spy_files)} SPY parquet files")

spy_frames = [pd.read_parquet(f) for f in spy_files]
spy = pd.concat(spy_frames)
spy.index = pd.DatetimeIndex(spy.index)
spy.columns = [c.lower() for c in spy.columns]
spy = spy.sort_index()
spy = spy[~spy.index.duplicated(keep="last")]  # keep last bar of duplicates
spy = spy.between_time("09:30", "16:00")

# Daily close = last bar close each day
spy_daily = spy["close"].groupby(spy.index.normalize()).last().rename("close")
spy_daily = spy_daily.sort_index()

# SPY 200-day MA
spy_daily = spy_daily.to_frame()
spy_daily["ma200"] = spy_daily["close"].rolling(200).mean()
spy_daily["above_ma200"] = spy_daily["close"] > spy_daily["ma200"]

print(f"  SPY daily: {len(spy_daily)} days, {spy_daily.index[0].date()} → {spy_daily.index[-1].date()}")
print(f"  Days above 200MA: {spy_daily['above_ma200'].sum()} / {spy_daily['above_ma200'].notna().sum()}")

# ── Load PKL trades ───────────────────────────────────────────────────
print("\nLoading window_debug results...")
with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)

orb_trades = []
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "strategy", "") == "ORB":
            entry_time = pd.to_datetime(t.entry_time)
            exit_time  = pd.to_datetime(t.exit_time)
            entry_day  = entry_time.normalize()
            pnl = getattr(t, "net_pnl", 0)
            direction = getattr(t, "direction", "LONG")
            hmm = getattr(t, "hmm_state", "")
            ticker = getattr(t, "ticker", "")
            orb_trades.append(dict(
                ticker=ticker,
                day=entry_day,
                year=str(entry_day.year),
                direction=direction,
                hmm_state=hmm,
                entry_time=entry_time,
                net_pnl=pnl,
                win=pnl > 0,
            ))

if not orb_trades:
    print("No ORB trades found in PKL!"); sys.exit(1)

df = pd.DataFrame(orb_trades)
print(f"  Total ORB trades: {len(df)}")

# ── Attach SPY 200MA status ───────────────────────────────────────────
df["spy_above_200ma"] = df["day"].map(spy_daily["above_ma200"])
df["ma200_val"]       = df["day"].map(spy_daily["ma200"])
df["spy_close"]       = df["day"].map(spy_daily["close"])

no_ma = df["spy_above_200ma"].isna().sum()
if no_ma:
    print(f"  Warning: {no_ma} trades with no MA200 data (early dates) → treated as ABOVE")
    df["spy_above_200ma"] = df["spy_above_200ma"].fillna(True)

# ── Baseline ──────────────────────────────────────────────────────────
def show_breakdown(label, subset):
    if subset.empty:
        print(f"  {label}: 0 trades"); return
    t  = subset["net_pnl"].sum()
    wr = subset["win"].mean() * 100
    print(f"  {label}: {len(subset)}t  P&L={t:+,.0f}  WR={wr:.0f}%  avg={t/len(subset):+.0f}/trade")

print(f"\n{'='*60}")
print(f"  ORB BEAR MARKET FILTER SIM")
print(f"{'='*60}")

print("\n── BASELINE (no filter) ─────────────────────────────────────")
show_breakdown("ALL ORB", df)
for yr in ["2020","2021","2022"]:
    show_breakdown(f"  {yr}", df[df["year"]==yr])

print("\n── BY DIRECTION ─────────────────────────────────────────────")
for yr in ["2020","2021","2022"]:
    y = df[df["year"]==yr]
    for d in ["LONG","SHORT"]:
        sub = y[y["direction"]==d]
        if len(sub): show_breakdown(f"  {yr} {d}", sub)

print("\n── SPY 200MA STATUS BREAKDOWN ───────────────────────────────")
above = df[df["spy_above_200ma"]]
below = df[~df["spy_above_200ma"]]
show_breakdown("SPY > 200MA", above)
show_breakdown("SPY < 200MA", below)
print()
for yr in ["2020","2021","2022"]:
    y_above = df[(df["year"]==yr) &  df["spy_above_200ma"]]
    y_below = df[(df["year"]==yr) & ~df["spy_above_200ma"]]
    if len(y_above): show_breakdown(f"  {yr} SPY>200MA", y_above)
    if len(y_below): show_breakdown(f"  {yr} SPY<200MA", y_below)

# ── Filter: skip ORB when SPY < 200MA ────────────────────────────────
print("\n── WITH 200MA FILTER (skip ORB when SPY below 200MA) ────────")
filtered = df[df["spy_above_200ma"]]
skipped  = df[~df["spy_above_200ma"]]

baseline_pnl = df["net_pnl"].sum()
filtered_pnl = filtered["net_pnl"].sum()
delta        = filtered_pnl - baseline_pnl

show_breakdown("Kept trades", filtered)
show_breakdown("Skipped trades (below 200MA)", skipped)
print(f"\n  Delta vs baseline: {delta:+,.0f}")
print(f"  Baseline:          {baseline_pnl:+,.0f}")
print(f"  With filter:       {filtered_pnl:+,.0f}")

# Year breakdown with filter
print()
for yr in ["2020","2021","2022"]:
    base = df[df["year"]==yr]["net_pnl"].sum()
    filt = filtered[filtered["year"]==yr]["net_pnl"].sum()
    skp  = skipped[skipped["year"]==yr]
    n_skp = len(skp)
    d = filt - base
    print(f"  {yr}: baseline={base:+,.0f}  filtered={filt:+,.0f}  delta={d:+,.0f}  skipped={n_skp}t")

# ── Direction analysis of skipped trades ─────────────────────────────
if not skipped.empty:
    print(f"\n── SKIPPED TRADES DETAIL ────────────────────────────────────")
    for d in ["LONG","SHORT"]:
        sub = skipped[skipped["direction"]==d]
        if len(sub): show_breakdown(f"  Skipped {d}", sub)

    print(f"\n  Skipped by year:")
    for yr in skipped["year"].unique():
        y = skipped[skipped["year"]==yr]
        show_breakdown(f"    {yr}", y)

# ── Bootstrap on delta ────────────────────────────────────────────────
if not skipped.empty:
    # Test: is the P&L we avoided (skipped) significantly negative?
    outcomes = skipped["net_pnl"].values
    observed = outcomes.sum()
    rng = np.random.default_rng(42)
    boot = np.array([rng.choice(outcomes, size=len(outcomes), replace=True).sum()
                     for _ in range(10_000)])
    p = (boot >= 0).mean()  # fraction where skipped P&L was positive (we'd want to keep them)
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    print(f"\n── BOOTSTRAP (skipped trades) ───────────────────────────────")
    print(f"  Skipped P&L:  {observed:+,.0f}")
    print(f"  95%CI:        [{ci_lo:+,.0f}, {ci_hi:+,.0f}]")
    print(f"  P(skipped≥0): {p:.3f}  {'← bad filter (good trades skipped)' if p > 0.5 else '← good filter (losing trades avoided)'}")

# ── Trade list for 2022 ───────────────────────────────────────────────
print(f"\n── ORB TRADES 2022 (detail) ─────────────────────────────────")
trades_2022 = df[df["year"]=="2022"].sort_values("day")
print(f"  {'Date':<12} {'Ticker':<8} {'Dir':<6} {'HMM':<8} {'SPY>200MA':<10} {'P&L':>8}")
for _, r in trades_2022.iterrows():
    flag = "YES" if r["spy_above_200ma"] else "NO "
    print(f"  {str(r['day'].date()):<12} {r['ticker']:<8} {r['direction']:<6} {r['hmm_state']:<8} {flag:<10} {r['net_pnl']:>+8,.0f}")
