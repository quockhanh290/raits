"""
stress_orb_stk_v2_detail.py — V2 detailed breakdown.

V2 params: no ETF co-confirm, Kelly sizing, OR=5min, signal=9:35, stop=0.5×ATR.

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\stress_orb_stk_v2_detail.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

ACCOUNT_START = 50_000.0
MAX_RISK_PCT  = 0.01
MAX_POS_PCT   = 0.20
KELLY_FRAC    = 0.5
KELLY_STATS   = {"win_rate": 0.50, "avg_win": 3.0, "avg_loss": 2.0}
MAX_SLOTS     = 3
MIN_GAP_PCT   = 0.015
TARGET_R      = 2.0
COMMISSION    = 0.01
OR_END        = dtime(9, 35)
SIGNAL_START  = dtime(9, 35)
SIGNAL_END    = dtime(10, 15)
EXIT_TIME     = dtime(10, 15)
ETF_UNIVERSE  = ["SPY", "QQQ", "IWM"]
STOCK_UNIVERSE_RAW = [
    "TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
    "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
    "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM",
    "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM",
]

print("Loading data...")
with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)
with open(PKL_5MIN,    "rb") as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

STOCK_UNIVERSE = [tk for tk in STOCK_UNIVERSE_RAW if tk in data_5min]

stress_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Stress":
            stress_days.add(pd.to_datetime(t.entry_time).normalize())
stress_days = sorted(stress_days)

print("Precomputing caches...")
prev_close_map, day_bars_cache = {}, {}
for ticker in ETF_UNIVERSE + STOCK_UNIVERSE:
    if ticker not in data_5min: continue
    bars = data_5min[ticker].sort_index()
    daily_last = bars.resample("B")["close"].last().dropna()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i-1])
    for day in stress_days:
        db = bars[bars.index.normalize() == day]
        if len(db) >= 2: day_bars_cache[(ticker, day)] = db

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

def kelly_size(entry_px, stop_px, equity):
    p, q = KELLY_STATS["win_rate"], 1 - KELLY_STATS["win_rate"]
    b = KELLY_STATS["avg_win"] / KELLY_STATS["avg_loss"]
    fk = (p * b - q) / b
    if fk <= 0: return 0
    kelly_sh = int(equity * fk * KELLY_FRAC / entry_px)
    risk_ps  = abs(entry_px - stop_px)
    if risk_ps <= 0: return 0
    vol_sh   = int(equity * MAX_RISK_PCT / risk_ps)
    limit_sh = int(equity * MAX_POS_PCT  / entry_px)
    return max(0, min(kelly_sh, vol_sh, limit_sh))

# ── Run V2 ────────────────────────────────────────────────────────────────────
print("Running V2...")
equity = ACCOUNT_START
trades = []

for day in stress_days:
    etf_or_ranges = {}
    for etf in ETF_UNIVERSE:
        db = day_bars_cache.get((etf, day))
        if db is None: continue
        or_bars = db[db.index.time < OR_END]
        if or_bars.empty: continue
        etf_or_ranges[etf] = (float(or_bars["high"].max()), float(or_bars["low"].min()))
    if not etf_or_ranges: continue

    stk_or_ranges = {}
    for ticker in STOCK_UNIVERSE:
        db = day_bars_cache.get((ticker, day))
        if db is None: continue
        prev_c = prev_close_map.get((ticker, day))
        if not prev_c or prev_c <= 0: continue
        open_bars = db[db.index.time >= dtime(9, 30)]
        if open_bars.empty: continue
        session_open = float(open_bars.iloc[0]["open"])
        gap_pct = (session_open - prev_c) / prev_c
        if gap_pct >= -MIN_GAP_PCT: continue
        or_bars = db[db.index.time < OR_END]
        if or_bars.empty: continue
        or_high = float(or_bars["high"].max())
        or_low  = float(or_bars["low"].min())
        or_range = or_high - or_low
        if or_range <= 0: continue
        atr = compute_atr(or_bars)
        if atr <= 0: continue
        if or_range < 0.5 * atr or or_range > 5 * atr: continue
        stk_or_ranges[ticker] = (or_high, or_low, atr, gap_pct)
    if not stk_or_ranges: continue

    spy_db = day_bars_cache.get(("SPY", day))
    if spy_db is None: continue
    sig_idx = spy_db.index[
        (spy_db.index.time >= SIGNAL_START) &
        (spy_db.index.time <= SIGNAL_END)
    ]
    if sig_idx.empty: continue

    slots, entered = 0, set()
    for bar_ts in sig_idx:
        if slots >= MAX_SLOTS: break
        for ticker, (or_high, or_low, atr, gap_pct) in stk_or_ranges.items():
            if slots >= MAX_SLOTS: break
            if ticker in entered: continue
            stk_db = day_bars_cache.get((ticker, day))
            if stk_db is None: continue
            stk_so_far = stk_db.loc[:bar_ts]
            if stk_so_far.empty: continue
            if stk_so_far.index[-1] != bar_ts: continue
            stk_bar  = stk_so_far.iloc[-1]
            bar_low  = float(stk_bar["low"])
            bar_close= float(stk_bar["close"])
            if not (bar_low < or_low and bar_close < or_low): continue

            entry_px  = bar_close
            stop_px   = or_high + 0.5 * atr
            stop_dist = stop_px - entry_px
            if stop_dist <= 0: continue
            target_px = entry_px - TARGET_R * stop_dist

            n_shares = kelly_size(entry_px, stop_px, equity)
            if n_shares < 1: continue

            fwd = stk_db[(stk_db.index > bar_ts) & (stk_db.index.time <= EXIT_TIME)]
            exit_px, reason = entry_px, "TIME_STOP"
            for _, b in fwd.iterrows():
                bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
                if bh >= stop_px:   exit_px = stop_px;   reason = "STOP_HIT";   break
                if bl <= target_px: exit_px = target_px; reason = "TARGET_HIT"; break
                exit_px = bc

            net_pnl = (entry_px - exit_px) * n_shares - n_shares * COMMISSION * 2
            equity += net_pnl

            trades.append(dict(
                ticker=ticker, day=day, year=str(day.year),
                month=f"{day.year}-{day.month:02d}",
                entry_time=bar_ts, entry_px=entry_px,
                or_high=or_high, or_low=or_low, atr=atr,
                stop_px=stop_px, stop_dist=stop_dist, target_px=target_px,
                gap_pct=round(gap_pct * 100, 2),
                shares=n_shares, exit_px=exit_px, reason=reason,
                net_pnl=net_pnl, win=net_pnl > 0,
                equity_after=round(equity, 2),
            ))
            entered.add(ticker); slots += 1

df = pd.DataFrame(trades)
SEP = "=" * 68

# ── 1. Summary ────────────────────────────────────────────────────────────────
total = df["net_pnl"].sum(); wr = df["win"].mean()*100; avg = df["net_pnl"].mean()
rng  = np.random.default_rng(42)
boot = np.array([rng.choice(df["net_pnl"].values, size=len(df), replace=True).sum()
                 for _ in range(10_000)])
p = float((boot <= 0).mean())
ci_lo, ci_hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))

print(f"\n{SEP}")
print(f"  V2 DETAIL: no co-confirm | Kelly | OR=5min | sig=9:35 | stop=0.5×ATR")
print(SEP)
print(f"  {len(df)}t  P&L={total:+,.0f}  WR={wr:.0f}%  avg={avg:+.1f}/t"
      f"  shares={df['shares'].mean():.0f}  stop_dist={df['stop_dist'].mean():.2f}")
print(f"  Bootstrap: p={p:.3f}  95%CI=[{ci_lo:+,.0f}, {ci_hi:+,.0f}]")

# ── 2. Per-year ───────────────────────────────────────────────────────────────
print(f"\n  {'─'*64}")
print(f"  {'Year':<6} {'N':>4} {'WR':>5} {'Avg/t':>7} {'Total':>8}  {'StopHit':>7}  {'TimeStop':>8}")
print(f"  {'─'*64}")
for yr in ["2020", "2021", "2022"]:
    y = df[df["year"] == yr]
    if y.empty: continue
    n_sh = (y["reason"] == "STOP_HIT").sum()
    n_ts = (y["reason"] == "TIME_STOP").sum()
    n_th = (y["reason"] == "TARGET_HIT").sum()
    extra = f"TGT:{n_th}" if n_th else ""
    print(f"  {yr:<6} {len(y):>4} {y['win'].mean()*100:>4.0f}% "
          f"{y['net_pnl'].mean():>+7.1f} {y['net_pnl'].sum():>+8,.0f}"
          f"  {n_sh:>4}t={y[y['reason']=='STOP_HIT']['net_pnl'].sum():>+6.0f}"
          f"  {n_ts:>4}t={y[y['reason']=='TIME_STOP']['net_pnl'].sum():>+7.0f}"
          + (f"  TGT:{n_th}t={y[y['reason']=='TARGET_HIT']['net_pnl'].sum():>+5.0f}" if n_th else ""))

# ── 3. Entry time distribution ────────────────────────────────────────────────
print(f"\n  {'─'*64}")
print(f"  Entry time distribution")
print(f"  {'Time':<8} {'N':>4} {'WR':>5} {'Avg/t':>7} {'Total':>8}")
df["entry_t"] = df["entry_time"].apply(lambda x: x.time().strftime("%H:%M"))
for t, g in df.groupby("entry_t"):
    wr_t = g["win"].mean()*100
    print(f"  {t:<8} {len(g):>4} {wr_t:>4.0f}% {g['net_pnl'].mean():>+7.1f} {g['net_pnl'].sum():>+8,.0f}")

# ── 4. Per-ticker breakdown ───────────────────────────────────────────────────
print(f"\n  {'─'*64}")
print(f"  Per-ticker (sorted by total P&L)")
print(f"  {'Ticker':<7} {'N':>4} {'WR':>5} {'Avg/t':>7} {'Total':>8}  {'Gap%':>6}  StopHits")
tk_g = df.groupby("ticker")
tk_stats = []
for tk, g in tk_g:
    n_sh = (g["reason"] == "STOP_HIT").sum()
    tk_stats.append(dict(
        ticker=tk, n=len(g), wr=g["win"].mean()*100,
        avg=g["net_pnl"].mean(), total=g["net_pnl"].sum(),
        avg_gap=g["gap_pct"].mean(), stop_hits=n_sh,
    ))
tk_stats.sort(key=lambda x: -x["total"])
for r in tk_stats:
    if r["total"] == 0 and r["n"] == 0: continue
    print(f"  {r['ticker']:<7} {r['n']:>4} {r['wr']:>4.0f}% "
          f"{r['avg']:>+7.1f} {r['total']:>+8,.0f}  {r['avg_gap']:>+5.1f}%  {r['stop_hits']}")

# ── 5. Monthly P&L heatmap ────────────────────────────────────────────────────
print(f"\n  {'─'*64}")
print(f"  Monthly P&L (trades / P&L)")
monthly = df.groupby("month").agg(n=("net_pnl","count"), pnl=("net_pnl","sum")).reset_index()
for yr in ["2020", "2021", "2022"]:
    row_parts = []
    for m in range(1, 13):
        key = f"{yr}-{m:02d}"
        match = monthly[monthly["month"] == key]
        if match.empty:
            row_parts.append(f"  {'--':>10}")
        else:
            n   = int(match.iloc[0]["n"])
            pnl = float(match.iloc[0]["pnl"])
            row_parts.append(f"  {n}t{pnl:>+7.0f}")
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    print(f"\n  {yr}")
    print(f"  " + "  ".join(f"{m:<10}" for m in months))
    print(f"  " + "".join(row_parts))

# ── 6. Gap size bucketing ─────────────────────────────────────────────────────
print(f"\n\n  {'─'*64}")
print(f"  Gap size buckets (gap_pct = gap vs prev close)")
print(f"  {'Gap bucket':<14} {'N':>4} {'WR':>5} {'Avg/t':>7} {'Total':>8}")
bins   = [(-99, -3.0), (-3.0, -2.0), (-2.0, -1.5)]
labels = ["<-3%", "-3% to -2%", "-2% to -1.5%"]
for (lo, hi), label in zip(bins, labels):
    g = df[(df["gap_pct"] >= lo) & (df["gap_pct"] < hi)]
    if g.empty: continue
    print(f"  {label:<14} {len(g):>4} {g['win'].mean()*100:>4.0f}% "
          f"{g['net_pnl'].mean():>+7.1f} {g['net_pnl'].sum():>+8,.0f}")

# ── 7. Worst 10 trades ────────────────────────────────────────────────────────
print(f"\n  {'─'*64}")
print(f"  Worst 10 trades")
print(f"  {'Date':<12} {'Ticker':<6} {'Shares':>6} {'Entry':>7} {'Stop':>7} {'Exit':>7} {'Reason':<12} {'PnL':>8}")
worst = df.nsmallest(10, "net_pnl")
for _, r in worst.iterrows():
    print(f"  {str(r['day'].date()):<12} {r['ticker']:<6} {r['shares']:>6} "
          f"${r['entry_px']:>6.2f} ${r['stop_px']:>6.2f} ${r['exit_px']:>6.2f} "
          f"{r['reason']:<12} ${r['net_pnl']:>+7.0f}")

# ── 8. Best 10 trades ─────────────────────────────────────────────────────────
print(f"\n  {'─'*64}")
print(f"  Best 10 trades")
print(f"  {'Date':<12} {'Ticker':<6} {'Shares':>6} {'Entry':>7} {'Stop':>7} {'Exit':>7} {'Reason':<12} {'PnL':>8}")
best = df.nlargest(10, "net_pnl")
for _, r in best.iterrows():
    print(f"  {str(r['day'].date()):<12} {r['ticker']:<6} {r['shares']:>6} "
          f"${r['entry_px']:>6.2f} ${r['stop_px']:>6.2f} ${r['exit_px']:>6.2f} "
          f"{r['reason']:<12} ${r['net_pnl']:>+7.0f}")

# ── 9. Trades per Stress day ──────────────────────────────────────────────────
print(f"\n  {'─'*64}")
stress_day_pnl = df.groupby("day")["net_pnl"].agg(n="count", total="sum")
days_traded = len(stress_day_pnl)
days_pos    = (stress_day_pnl["total"] > 0).sum()
days_neg    = (stress_day_pnl["total"] < 0).sum()
days_zero   = (stress_day_pnl["total"] == 0).sum()
days_no_trade = len(stress_days) - days_traded
print(f"  Stress days: {len(stress_days)} total")
print(f"    With trades: {days_traded}  (+: {days_pos}  -: {days_neg}  0: {days_zero})")
print(f"    No trades:   {days_no_trade}  (no gap-down stock qualified)")
print(f"    Avg P&L on active days: {stress_day_pnl['total'].mean():+.1f}")
print(f"    Avg P&L all stress days: {total/len(stress_days):+.1f}")

# ── 10. Cumulative equity ─────────────────────────────────────────────────────
print(f"\n  {'─'*64}")
print(f"  Equity curve (end of each Stress day with trades)")
cumulative = stress_day_pnl["total"].cumsum()
checkpoints = [int(len(cumulative) * p / 4) for p in range(5)]
for i, (day, cum_pnl) in enumerate(cumulative.items()):
    if i in checkpoints or i == len(cumulative) - 1:
        print(f"    {str(day.date())} cumP&L={cum_pnl:>+7,.0f}  equity={ACCOUNT_START+cum_pnl:>8,.0f}")

print(f"\n{SEP}\n")
