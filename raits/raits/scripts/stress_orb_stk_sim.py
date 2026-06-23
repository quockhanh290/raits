"""
stress_orb_stk_sim.py — Engine-faithful STRESS_ORB individual stocks diagnostic.

Root-cause analysis of sim +$5,581 vs engine -$2,568.

Runs 4 variants to isolate which factor drives the discrepancy:

  V1  Original     — no co-confirm, fixed $500/stop_dist, stop=0.5×ATR
  V2  Kelly        — no co-confirm, Kelly sizing,          stop=0.5×ATR
  V3  Engine-best  — ETF co-confirm, Kelly sizing,         stop=0.5×ATR
  V4  Engine-wide  — ETF co-confirm, Kelly sizing,         stop=1.0×ATR

Reports per-year: trades, WR, avg P&L/trade, total P&L, bootstrap p.

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\stress_orb_stk_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

# ── Config matching engine defaults ──────────────────────────────────────────
ACCOUNT_START = 50_000.0
MAX_RISK_PCT  = 0.01          # PositionSizer default
MAX_POS_PCT   = 0.20          # PositionSizer default
KELLY_FRAC    = 0.5           # half-Kelly
KELLY_STATS   = {"win_rate": 0.50, "avg_win": 3.0, "avg_loss": 2.0}  # engine fallback for STRESS_ORB
MAX_SLOTS     = 3             # stocks per Stress day
MIN_GAP_PCT   = 0.015         # gap down ≥1.5%
TARGET_R      = 2.0
COMMISSION    = 0.01          # $0.01/share each way

OR_END         = dtime(9, 35)
SIGNAL_START   = dtime(9, 35)
SIGNAL_END     = dtime(10, 15)
EXIT_TIME      = dtime(10, 15)

ETF_UNIVERSE = ["SPY", "QQQ", "IWM"]
STOCK_UNIVERSE_RAW = [
    "TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
    "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
    "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM",
    "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM",
]


# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading data...")
with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

STOCK_UNIVERSE = [tk for tk in STOCK_UNIVERSE_RAW if tk in data_5min]
print(f"Stock universe: {len(STOCK_UNIVERSE)} tickers")


# ── Extract Stress days from results pkl (not hardcoded) ─────────────────────
stress_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Stress":
            stress_days.add(pd.to_datetime(t.entry_time).normalize())
stress_days = sorted(stress_days)
print(f"Stress regime days: {len(stress_days)}")
by_yr = {}
for d in stress_days:
    by_yr.setdefault(str(d.year), []).append(d)
for yr, days in sorted(by_yr.items()):
    print(f"  {yr}: {len(days)} Stress days")


# ── Helpers ───────────────────────────────────────────────────────────────────
def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())


def kelly_size(entry_px, stop_px, equity):
    """Min(Kelly, VolTarget, PositionLimit) — matches engine PositionSizer."""
    p = KELLY_STATS["win_rate"]
    q = 1.0 - p
    b = KELLY_STATS["avg_win"] / KELLY_STATS["avg_loss"]
    full_kelly = (p * b - q) / b
    if full_kelly <= 0:
        return 0
    half_kelly_frac = full_kelly * KELLY_FRAC

    kelly_sh = int(equity * half_kelly_frac / entry_px)
    risk_ps  = abs(entry_px - stop_px)
    if risk_ps <= 0:
        return 0
    vol_sh   = int(equity * MAX_RISK_PCT / risk_ps)
    limit_sh = int(equity * MAX_POS_PCT  / entry_px)

    return max(0, min(kelly_sh, vol_sh, limit_sh))


# ── Precompute caches ─────────────────────────────────────────────────────────
print("Precomputing caches...")
prev_close_map: dict = {}
day_bars_cache: dict = {}

for ticker in ETF_UNIVERSE + STOCK_UNIVERSE:
    if ticker not in data_5min:
        continue
    bars = data_5min[ticker].sort_index()
    daily_last = bars.resample("B")["close"].last().dropna()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i - 1])
    for day in stress_days:
        db = bars[bars.index.normalize() == day]
        if len(db) >= 2:
            day_bars_cache[(ticker, day)] = db

print(f"Cache: {len(day_bars_cache)} (ticker, day) pairs")


# ── Core simulation ───────────────────────────────────────────────────────────
def run_scenario(atr_mult_stop: float, use_etf_confirm: bool,
                 fixed_size: float = None,
                 or_end: dtime = OR_END,
                 signal_start_t: dtime = SIGNAL_START) -> list:
    """
    atr_mult_stop  : stop = or_high + atr_mult_stop * atr
    use_etf_confirm: require ≥1 ETF bar.low < ETF OR_low before stock entry
    fixed_size     : None → Kelly sizing; float → shares = int(fixed_size / stop_dist)
    or_end         : exclusive upper bound for OR window (default 9:35 = single 9:30 bar)
    signal_start_t : first signal bar (default 9:35; use 9:45 for 15-min OR framework)
    """
    equity = ACCOUNT_START
    trades = []

    for day in stress_days:
        # ── ETF OR ranges ─────────────────────────────────────────────────────
        etf_or_ranges = {}
        for etf in ETF_UNIVERSE:
            db = day_bars_cache.get((etf, day))
            if db is None:
                continue
            or_bars = db[db.index.time < or_end]
            if or_bars.empty:
                continue
            etf_or_ranges[etf] = (float(or_bars["high"].max()), float(or_bars["low"].min()))

        if not etf_or_ranges:
            continue

        # ── Stock OR ranges (gap-down ≥1.5%) ─────────────────────────────────
        stk_or_ranges = {}
        for ticker in STOCK_UNIVERSE:
            db = day_bars_cache.get((ticker, day))
            if db is None:
                continue
            prev_c = prev_close_map.get((ticker, day))
            if not prev_c or prev_c <= 0:
                continue

            open_bars = db[db.index.time >= dtime(9, 30)]
            if open_bars.empty:
                continue
            session_open = float(open_bars.iloc[0]["open"])
            gap_pct = (session_open - prev_c) / prev_c
            if gap_pct >= -MIN_GAP_PCT:
                continue

            or_bars = db[db.index.time < or_end]
            if or_bars.empty:
                continue
            or_high  = float(or_bars["high"].max())
            or_low   = float(or_bars["low"].min())
            or_range = or_high - or_low
            if or_range <= 0:
                continue

            atr = compute_atr(or_bars)
            if atr <= 0:
                continue
            if or_range < 0.5 * atr or or_range > 5 * atr:
                continue

            stk_or_ranges[ticker] = (or_high, or_low, atr)

        if not stk_or_ranges:
            continue

        # ── Signal bar timestamps from SPY ────────────────────────────────────
        spy_db = day_bars_cache.get(("SPY", day))
        if spy_db is None:
            continue
        sig_idx = spy_db.index[
            (spy_db.index.time >= signal_start_t) &
            (spy_db.index.time <= SIGNAL_END)
        ]
        if sig_idx.empty:
            continue

        # ── Bar-by-bar loop ───────────────────────────────────────────────────
        slots   = 0
        entered = set()

        for bar_ts in sig_idx:
            if slots >= MAX_SLOTS:
                break

            # ETF co-confirm: ≥1 ETF current bar low < ETF OR low
            if use_etf_confirm:
                etf_ok = False
                for etf, (etf_or_h, etf_or_l) in etf_or_ranges.items():
                    etf_db = day_bars_cache.get((etf, day))
                    if etf_db is None:
                        continue
                    etf_so_far = etf_db.loc[:bar_ts]
                    if etf_so_far.empty:
                        continue
                    if float(etf_so_far.iloc[-1]["low"]) < etf_or_l:
                        etf_ok = True
                        break
                if not etf_ok:
                    continue

            # Scan stocks for OR-low breakdown
            for ticker, (or_high, or_low, atr) in stk_or_ranges.items():
                if slots >= MAX_SLOTS:
                    break
                if ticker in entered:
                    continue

                stk_db = day_bars_cache.get((ticker, day))
                if stk_db is None:
                    continue
                stk_so_far = stk_db.loc[:bar_ts]
                if stk_so_far.empty:
                    continue
                # Only signal on the current bar (not a stale bar from earlier)
                if stk_so_far.index[-1] != bar_ts:
                    continue

                stk_bar   = stk_so_far.iloc[-1]
                bar_low   = float(stk_bar["low"])
                bar_close = float(stk_bar["close"])

                if not (bar_low < or_low and bar_close < or_low):
                    continue

                entry_px  = bar_close
                stop_px   = or_high + atr_mult_stop * atr
                stop_dist = stop_px - entry_px
                if stop_dist <= 0:
                    continue
                target_px = entry_px - TARGET_R * stop_dist

                # Position sizing
                if fixed_size is not None:
                    n_shares = max(1, int(fixed_size / stop_dist))
                else:
                    n_shares = kelly_size(entry_px, stop_px, equity)
                    if n_shares < 1:
                        continue

                # Forward simulate to EXIT_TIME
                fwd = stk_db[
                    (stk_db.index > bar_ts) &
                    (stk_db.index.time <= EXIT_TIME)
                ]
                exit_px = entry_px
                reason  = "TIME_STOP"
                for _, b in fwd.iterrows():
                    bh = float(b["high"])
                    bl = float(b["low"])
                    bc = float(b["close"])
                    if bh >= stop_px:
                        exit_px = stop_px
                        reason  = "STOP_HIT"
                        break
                    if bl <= target_px:
                        exit_px = target_px
                        reason  = "TARGET_HIT"
                        break
                    exit_px = bc

                gross   = (entry_px - exit_px) * n_shares  # SHORT
                comm    = n_shares * COMMISSION * 2
                net_pnl = gross - comm

                if fixed_size is None:
                    equity += net_pnl

                trades.append(dict(
                    ticker=ticker, day=day, year=str(day.year),
                    bar_ts=bar_ts, entry_px=entry_px,
                    stop_px=stop_px, stop_dist=stop_dist, target_px=target_px,
                    shares=n_shares, exit_px=exit_px, reason=reason,
                    net_pnl=net_pnl, win=net_pnl > 0,
                ))
                entered.add(ticker)
                slots += 1

    return trades


# ── Reporting ─────────────────────────────────────────────────────────────────
def report(label, trades):
    if not trades:
        print(f"\n  [{label}] — 0 trades")
        return

    df    = pd.DataFrame(trades)
    total = df["net_pnl"].sum()
    wr    = df["win"].mean() * 100
    avg   = df["net_pnl"].mean()

    rng  = np.random.default_rng(42)
    boot = np.array([
        rng.choice(df["net_pnl"].values, size=len(df), replace=True).sum()
        for _ in range(10_000)
    ])
    p         = float((boot <= 0).mean())
    ci_lo, ci_hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))

    print(f"\n  [{label}]")
    print(f"  {len(df)}t  P&L={total:+,.0f}  WR={wr:.0f}%  avg/t={avg:+.1f}"
          f"  shares={df['shares'].mean():.0f}  stop_dist={df['stop_dist'].mean():.2f}")

    for yr in ["2020", "2021", "2022"]:
        y = df[df["year"] == yr]
        if len(y):
            print(f"    {yr}: {len(y):3}t  {y['net_pnl'].sum():>+8,.0f}"
                  f"  WR={y['win'].mean()*100:.0f}%  avg={y['net_pnl'].mean():+.1f}")

    by_r = df.groupby("reason")["net_pnl"].agg(n="count", total="sum")
    for r_, row in by_r.iterrows():
        print(f"    {r_:<14}: {int(row['n'])}t  {row['total']:>+8,.0f}")

    # Top-5 tickers
    tk_pnl = df.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
    top5   = tk_pnl.head(5).sum()
    top5p  = top5 / total * 100 if total else 0
    print(f"    Top-5 tickers: {top5:+,.0f} ({top5p:.0f}%)")
    for tk, pnl in tk_pnl.head(5).items():
        print(f"      {tk:<6} {pnl:>+8,.0f}")

    sig_str = "✓ significant" if p < 0.05 else "✗ not significant"
    print(f"  Bootstrap: p={p:.3f}  95%CI=[{ci_lo:+,.0f}, {ci_hi:+,.0f}]  {sig_str}")


# ── Run all variants ──────────────────────────────────────────────────────────
print("\nRunning scenarios (this may take 30-60s)...")

t_v1 = run_scenario(0.5, use_etf_confirm=False, fixed_size=500.0)
print("  V1 done")
t_v2 = run_scenario(0.5, use_etf_confirm=False, fixed_size=None)
print("  V2 done")
t_v3 = run_scenario(0.5, use_etf_confirm=True,  fixed_size=None)
print("  V3 done")
t_v4 = run_scenario(1.0, use_etf_confirm=True,  fixed_size=None)
print("  V4 done")
# V5: engine framework timing — OR=15min (9:30-9:44), signals start 9:45
t_v5 = run_scenario(0.5, use_etf_confirm=True,  fixed_size=None,
                    or_end=dtime(9, 45), signal_start_t=dtime(9, 45))
print("  V5 done")


# ── Print results ─────────────────────────────────────────────────────────────
HDR = "=" * 70
print(f"\n{HDR}")
print(f"  STRESS_ORB STOCKS — ROOT CAUSE DIAGNOSTIC")
print(f"  Baseline engine: ~$14,932 over 3 years")
print(f"  Original stocks sim: ~+$5,581  |  Failed engine: -$2,568")
print(f"{HDR}")

print(f"\n  Stress days by year:")
for yr in ["2020", "2021", "2022"]:
    n = sum(1 for d in stress_days if str(d.year) == yr)
    print(f"    {yr}: {n} days")

report("V1: Original   (no-confirm, $500,  OR=5min,  sig=9:35)", t_v1)
report("V2: Kelly      (no-confirm, Kelly, OR=5min,  sig=9:35)", t_v2)
report("V3: Engine-best(co-confirm, Kelly, OR=5min,  sig=9:35)", t_v3)
report("V4: Engine-wide(co-confirm, Kelly, OR=5min,  sig=9:35, stop=1.0×)", t_v4)
report("V5: Engine-fw  (co-confirm, Kelly, OR=15min, sig=9:45)", t_v5)

v1_pnl = sum(t["net_pnl"] for t in t_v1)
v2_pnl = sum(t["net_pnl"] for t in t_v2)
v3_pnl = sum(t["net_pnl"] for t in t_v3)
v4_pnl = sum(t["net_pnl"] for t in t_v4)
v5_pnl = sum(t["net_pnl"] for t in t_v5)

print(f"\n{HDR}")
print(f"  FACTOR ISOLATION (P&L delta per step)")
print(f"  V1→V2  sizing ($500 → Kelly):              {v2_pnl-v1_pnl:>+8,.0f}")
print(f"  V2→V3  co-confirm (off → on):              {v3_pnl-v2_pnl:>+8,.0f}")
print(f"  V3→V4  stop (0.5×ATR → 1.0×ATR):          {v4_pnl-v3_pnl:>+8,.0f}")
print(f"  V3→V5  OR+timing (5min/9:35 → 15min/9:45):{v5_pnl-v3_pnl:>+8,.0f}")
print(f"  V1→V4  total (original sim → all factors): {v4_pnl-v1_pnl:>+8,.0f}")
print(f"{HDR}")

print(f"\n  VERDICT:")
for label, pnl, trades in [("V3 (5min OR, 9:35, 0.5×ATR)", v3_pnl, t_v3),
                            ("V5 (15min OR, 9:45, 0.5×ATR)", v5_pnl, t_v5)]:
    n = len(trades)
    status = "POSITIVE" if pnl > 0 else "NEGATIVE"
    print(f"  {label}: {status} {pnl:+,.0f}  ({n}t)")
print()
drivers = {
    "stop width V3→V4":      abs(v4_pnl - v3_pnl),
    "co-confirm V2→V3":      abs(v3_pnl - v2_pnl),
    "OR+timing V3→V5":       abs(v5_pnl - v3_pnl),
    "sizing V1→V2":          abs(v2_pnl - v1_pnl),
}
top_driver = max(drivers, key=drivers.get)
print(f"  Primary regression driver: {top_driver} ({drivers[top_driver]:,.0f})")
print()
