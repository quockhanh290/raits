"""
gap_fill_window_sim.py — Sim mở entry window GAP_FILL từ 10:30 → 11:30.

Baseline: chỉ scan 1 lần lúc 10:30
Extended: scan thêm lúc 11:00 và 11:30 cho stocks chưa được enter

Conditions giữ nguyên:
  - Gap down 1.5-3% vs prev close
  - Retrace 50-85% at scan time
  - SPY above VWAP
  - Stop = LOD_to_scan_time - 0.1×ATR
  - Target = prev_close + 50% gap
  - Exit = target / stop / 13:30

Usage:
    cd D:\raits\raits
    python raits\scripts\gap_fill_window_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

print("Loading data...")
with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)
with open(PKL_5MIN,    "rb") as f: data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Identify Normal regime days from GAP_FILL trades in results
normal_days = set()
for w in results:
    for t in w.get("trades", []):
        s = getattr(t, "strategy", None)
        h = getattr(t, "hmm_state", None)
        if h == "Normal":
            et = pd.to_datetime(t.entry_time).normalize()
            normal_days.add(et)
# Also add days with ORB or TF trades in Normal
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", None) == "Normal":
            normal_days.add(pd.to_datetime(t.entry_time).normalize())

normal_days = sorted(normal_days)
print(f"Normal regime days found: {len(normal_days)}")

# Same universe as window_debug (excluding index ETFs used as filters)
UNIVERSE = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1   = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
            "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM"]
PHASE2   = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
STOCK_UNIVERSE = set(UNIVERSE + PHASE1 + PHASE2)
available_tickers = [tk for tk in data_5min if tk in STOCK_UNIVERSE]

# SPY VWAP lookup
spy = data_5min.get("SPY", pd.DataFrame()).sort_index().copy()
if not spy.empty:
    spy["tp"]      = (spy["high"] + spy["low"] + spy["close"]) / 3
    spy["tpv"]     = spy["tp"] * spy["volume"]
    spy["date"]    = spy.index.normalize()
    spy["cum_tpv"] = spy.groupby("date")["tpv"].cumsum()
    spy["cum_vol"] = spy.groupby("date")["volume"].cumsum()
    spy["vwap"]    = spy["cum_tpv"] / spy["cum_vol"]
    spy["above"]   = spy["close"] > spy["vwap"]

def spy_above_vwap(ts):
    if spy.empty:
        return True
    row = spy[spy.index <= ts]
    if row.empty:
        return False
    return bool(row.iloc[-1]["above"])

def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

# Precompute prev close
print("Precomputing prev close map...")
prev_close_map = {}
for ticker in available_tickers:
    if ticker not in data_5min:
        continue
    bars = data_5min[ticker].sort_index()
    bars_d = bars.copy()
    bars_d["date"] = bars_d.index.normalize()
    daily_last = bars_d.groupby("date")["close"].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i - 1])

from datetime import datetime, timedelta
_base = datetime(2000, 1, 1, 10, 30)
SCAN_TIMES = [(_base + timedelta(minutes=5*i)).time() for i in range(13)]  # 10:30..11:30
EXIT_TIME  = dtime(13, 30)

def try_entry(ticker, day, scan_time, prev_c, all_day_bars):
    """Try to enter at scan_time. Returns trade dict or None."""
    bars_pre = all_day_bars[all_day_bars.index.time <= scan_time]
    if len(bars_pre) < 4:
        return None

    first_bar = bars_pre[bars_pre.index.time >= dtime(9, 30)]
    if first_bar.empty:
        return None
    session_open = float(first_bar.iloc[0]["open"])
    gap_pct  = (session_open - prev_c) / prev_c
    gap_size = session_open - prev_c

    # Gap down 1.5-3%
    if gap_pct >= 0 or abs(gap_pct) < 0.015 or abs(gap_pct) > 0.03:
        return None

    px_scan = float(bars_pre.iloc[-1]["close"])
    retrace = (session_open - px_scan) / gap_size if gap_size != 0 else 0

    if not (0.50 <= retrace <= 0.85):
        return None

    # SPY above VWAP
    if not spy_above_vwap(bars_pre.index[-1]):
        return None

    morning_lod = float(bars_pre["low"].min())
    atr = compute_atr(bars_pre)
    if atr <= 0:
        return None

    stop_px   = morning_lod - 0.1 * atr
    stop_dist = abs(px_scan - stop_px)
    if stop_dist <= 0:
        return None

    target_px = prev_c + 0.50 * abs(gap_size)
    entry_px  = px_scan
    shares    = max(1, int(500 / stop_dist))

    # Simulate forward from scan_time to EXIT_TIME
    bars_after = all_day_bars[
        (all_day_bars.index.time > scan_time) &
        (all_day_bars.index.time <= EXIT_TIME)
    ]

    exit_px = entry_px
    reason  = "TIME_STOP"
    for _, b in bars_after.iterrows():
        if float(b["low"]) <= stop_px:
            exit_px = stop_px
            reason  = "STOP_HIT"
            break
        if float(b["high"]) >= target_px:
            exit_px = target_px
            reason  = "TARGET_HIT"
            break
        exit_px = float(b["close"])

    net_pnl = (exit_px - entry_px) * shares - shares * 0.01 * 2
    return dict(
        ticker=ticker, day=day, year=str(day.year),
        scan_time=str(scan_time), entry_px=entry_px,
        exit_px=exit_px, reason=reason,
        gap_pct=round(abs(gap_pct) * 100, 2),
        retrace=round(retrace, 2),
        shares=shares, net_pnl=net_pnl, win=net_pnl > 0,
    )

MAX_GF = 3   # mirror engine MAX_GAP_FILL

print("Running simulation...")
baseline_trades = []   # 10:30 only
extended_trades = []   # 11:00 + 11:30 ADDITIONAL only

for day in normal_days:
    entered_tickers = set()
    slots_used = {st: 0 for st in SCAN_TIMES}

    for scan_time in SCAN_TIMES:
        for ticker in available_tickers:
            if ticker not in data_5min:
                continue
            if ticker in entered_tickers:
                continue
            # Cap at MAX_GF slots per scan time
            if slots_used[scan_time] >= MAX_GF:
                break
            all_day = data_5min[ticker][data_5min[ticker].index.normalize() == day].sort_index()
            if len(all_day) < 4:
                continue
            prev_c = prev_close_map.get((ticker, day))
            if prev_c is None:
                continue

            trade = try_entry(ticker, day, scan_time, prev_c, all_day)
            if trade is None:
                continue

            entered_tickers.add(ticker)
            slots_used[scan_time] += 1
            if scan_time == dtime(10, 30):
                baseline_trades.append(trade)
                extended_trades.append(trade)
            else:
                extended_trades.append({**trade, "is_new": True, "scan_time": str(scan_time)})

# Split into baseline and truly new trades
new_trades = [t for t in extended_trades if t.get("is_new")]

def show(label, trades):
    if not trades:
        print(f"  {label}: 0 trades")
        return
    df = pd.DataFrame(trades)
    total = df["net_pnl"].sum()
    wr    = df["win"].mean() * 100
    avg   = df["net_pnl"].mean()
    n     = len(df)
    print(f"\n  {label}: {n}t  P&L={total:+,.0f}  WR={wr:.0f}%  avg={avg:+.1f}/trade")
    for yr in ["2020", "2021", "2022"]:
        y = df[df["year"] == yr]
        if len(y):
            ywr = y["win"].mean() * 100
            print(f"    {yr}: {len(y):3}t  P&L={y['net_pnl'].sum():+8,.0f}  WR={ywr:.0f}%")
    by_reason = df.groupby("reason")["net_pnl"].agg(n="count", total="sum")
    for r, row in by_reason.iterrows():
        print(f"    {r:<14}: {int(row['n'])}t  {row['total']:+,.0f}")

print(f"\n{'='*60}")
print(f"  GAP FILL WINDOW EXTENSION SIM")
print(f"{'='*60}")
show("Baseline (10:30 only)", baseline_trades)
show("NEW trades (11:00 + 11:30)", new_trades)
show("TOTAL (baseline + new)", extended_trades)

# By scan time
print(f"\n  Breakdown by scan time:")
for st in SCAN_TIMES:
    t_st = [t for t in extended_trades if t["scan_time"] == str(st)]
    if t_st:
        df_st = pd.DataFrame(t_st)
        pnl = df_st["net_pnl"].sum()
        wr  = df_st["win"].mean() * 100
        print(f"    {st}: {len(t_st):3}t  P&L={pnl:+,.0f}  WR={wr:.0f}%")

# ── Ticker concentration (new trades only) ──────────────────────────
import numpy as np
if new_trades:
    df_new = pd.DataFrame(new_trades)
    tk_grp = df_new.groupby("ticker")["net_pnl"].agg(n="count", total="sum").sort_values("total", ascending=False)
    total_new_pnl = df_new["net_pnl"].sum()
    top3_pnl = tk_grp["total"].head(3).sum()
    print(f"\n{'='*60}")
    print(f"  TICKER CONCENTRATION (new trades)")
    print(f"  Total P&L: {total_new_pnl:+,.0f}  |  Top-3 tickers: {top3_pnl:+,.0f} ({top3_pnl/total_new_pnl*100:.0f}%)")
    print(f"  {'Ticker':<8} {'N':>4} {'P&L':>9}")
    for tk, row in tk_grp.iterrows():
        bar = "█" * int(abs(row["total"]) / max(abs(tk_grp["total"].max()), 1) * 20)
        sign = "+" if row["total"] >= 0 else ""
        print(f"  {tk:<8} {int(row['n']):>4} {sign}{row['total']:>8,.0f}  {bar}")

# ── Bootstrap test (new trades P&L) ─────────────────────────────────
if new_trades:
    df_new = pd.DataFrame(new_trades)
    outcomes = df_new["net_pnl"].values
    observed = outcomes.sum()
    N_BOOT = 10_000
    rng = np.random.default_rng(42)
    boot_sums = np.array([rng.choice(outcomes, size=len(outcomes), replace=True).sum()
                          for _ in range(N_BOOT)])
    p_val = (boot_sums <= 0).mean()          # fraction of bootstrap samples ≤ 0
    ci_lo, ci_hi = np.percentile(boot_sums, [2.5, 97.5])
    print(f"\n{'='*60}")
    print(f"  BOOTSTRAP TEST (new trades, N={N_BOOT:,})")
    print(f"  Observed P&L  : {observed:+,.0f}")
    print(f"  95% CI        : [{ci_lo:+,.0f}, {ci_hi:+,.0f}]")
    print(f"  P(sum≤0)      : {p_val:.3f}  {'✓ significant' if p_val < 0.05 else '✗ NOT significant'}")
    print(f"  Mean boot sum : {boot_sums.mean():+,.0f}")
    print(f"  Verdict: {'Edge likely REAL' if p_val < 0.05 else 'Cannot rule out luck'}")
