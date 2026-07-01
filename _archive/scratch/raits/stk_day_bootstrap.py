"""
stk_day_bootstrap.py — Day-level bootstrap for STRESS_ORB_STK V2.

Trade-level bootstrap (previous) is overoptimistic because multiple trades
on the same day are correlated. Day-level bootstrap resamples whole days
(preserving intra-day correlations) → more conservative p-value.

Also re-runs with updated sizing: kelly_fraction=0.75, max_position_pct=0.40.

Usage:
    cd d:\\raits\\raits
    python stk_day_bootstrap.py
"""
import sys, os, glob, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

# ── Config ────────────────────────────────────────────────────────────────────
SNAPSHOT    = r'd:\raits\raits\data\cache\snapshots\results_20260624_200216.pkl'
CACHE_5MIN  = r'd:\raits\raits\data\cache\data'
IS_START    = "2017-01-03"
IS_END      = "2022-12-31"

KELLY_FRAC      = 0.75   # updated from 0.50
MAX_POS_PCT     = 0.40   # updated from 0.20
MAX_RISK_PCT    = 0.015
ACCOUNT_START   = 50_000.0
KELLY_STATS     = {"win_rate": 0.50, "avg_win": 3.0, "avg_loss": 2.0}
MAX_SLOTS       = 3
MIN_GAP_PCT     = 0.015
TARGET_R        = 2.0
COMMISSION      = 0.01
OR_END          = dtime(9, 35)
SIGNAL_START    = dtime(9, 35)
SIGNAL_END      = dtime(10, 15)
EXIT_TIME       = dtime(10, 15)

STOCK_UNIVERSE_RAW = [
    "TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
    "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
    "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX",
    "CSCO","GS","CRM","JPM","MU","HON","MA","NFLX","INTC",
    "V","GILD","BIIB","MMM",
]


def load_5min(tickers):
    market_data = {}
    start_ts = pd.Timestamp(IS_START)
    end_ts   = pd.Timestamp(IS_END) + pd.Timedelta("1D")
    for t in tickers:
        files = glob.glob(os.path.join(CACHE_5MIN, f"{t}_5min_*.parquet"))
        if not files:
            continue
        frames = []
        for f in files:
            try: frames.append(pd.read_parquet(f))
            except Exception: pass
        if not frames: continue
        df = pd.concat(frames)
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        df = df[(df.index >= start_ts) & (df.index < end_ts)]
        df = df.between_time("09:30", "16:00")
        if not df.empty:
            market_data[t] = df
    return market_data


def get_stress_days():
    with open(SNAPSHOT, "rb") as f:
        r = pickle.load(f)
    all_trades = [t for w in r for t in w["trades"]]
    days = set(
        pd.to_datetime(t.entry_time).normalize()
        for t in all_trades if getattr(t, "hmm_state", "") == "Stress"
    )
    return sorted(days)


def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())


def kelly_size(entry_px, stop_px, equity):
    p, q = KELLY_STATS["win_rate"], 1 - KELLY_STATS["win_rate"]
    b    = KELLY_STATS["avg_win"] / KELLY_STATS["avg_loss"]
    fk   = (p * b - q) / b
    if fk <= 0: return 0
    kelly_sh = int(equity * fk * KELLY_FRAC / entry_px)
    risk_ps  = abs(entry_px - stop_px)
    if risk_ps <= 0: return 0
    vol_sh   = int(equity * MAX_RISK_PCT / risk_ps)
    limit_sh = int(equity * MAX_POS_PCT  / entry_px)
    return max(0, min(kelly_sh, vol_sh, limit_sh))


def run_sim(stress_days, market_data):
    equity = ACCOUNT_START
    trades = []

    prev_close_map = {}
    for ticker, df in market_data.items():
        daily_last = df.resample("B")["close"].last().dropna()
        dates = daily_last.index.tolist()
        for i in range(1, len(dates)):
            prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i - 1])

    for day in stress_days:
        stk_or_ranges = {}
        for ticker in STOCK_UNIVERSE_RAW:
            if ticker not in market_data: continue
            df = market_data[ticker]
            db = df[df.index.normalize() == day]
            if db.empty: continue
            prev_c = prev_close_map.get((ticker, day))
            if not prev_c or prev_c <= 0: continue
            open_bars = db[db.index.time >= dtime(9, 30)]
            if open_bars.empty: continue
            session_open = float(open_bars.iloc[0]["open"])
            gap_pct = (session_open - prev_c) / prev_c
            if gap_pct >= -MIN_GAP_PCT: continue
            or_bars = db[db.index.time < OR_END]
            if or_bars.empty: continue
            or_high   = float(or_bars["high"].max())
            or_low    = float(or_bars["low"].min())
            or_range  = or_high - or_low
            if or_range <= 0: continue
            atr = compute_atr(or_bars)
            if atr <= 0: continue
            if or_range < 0.5 * atr or or_range > 5 * atr: continue
            stk_or_ranges[ticker] = (or_high, or_low, atr, gap_pct)

        if not stk_or_ranges: continue

        if "SPY" not in market_data: continue
        spy_df = market_data["SPY"]
        spy_db = spy_df[spy_df.index.normalize() == day]
        if spy_db.empty: continue
        sig_idx = spy_db.index[
            (spy_db.index.time >= SIGNAL_START) &
            (spy_db.index.time <= SIGNAL_END)
        ]
        if sig_idx.empty: continue

        slots, entered = 0, set()
        day_trades = []
        for bar_ts in sig_idx:
            if slots >= MAX_SLOTS: break
            for ticker, (or_high, or_low, atr, gap_pct) in stk_or_ranges.items():
                if slots >= MAX_SLOTS: break
                if ticker in entered: continue
                df = market_data[ticker]
                db = df[df.index.normalize() == day]
                stk_so_far = db.loc[:bar_ts]
                if stk_so_far.empty: continue
                if stk_so_far.index[-1] != bar_ts: continue
                stk_bar   = stk_so_far.iloc[-1]
                bar_low   = float(stk_bar["low"])
                bar_close = float(stk_bar["close"])
                if not (bar_low < or_low and bar_close < or_low): continue

                entry_px  = bar_close
                stop_px   = or_high + 0.5 * atr
                stop_dist = stop_px - entry_px
                if stop_dist <= 0: continue
                target_px = entry_px - TARGET_R * stop_dist

                n_shares = kelly_size(entry_px, stop_px, equity)
                if n_shares < 1: continue

                fwd = db[(db.index > bar_ts) & (db.index.time <= EXIT_TIME)]
                exit_px, reason = entry_px, "TIME_STOP"
                for _, b in fwd.iterrows():
                    bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
                    if bh >= stop_px:   exit_px = stop_px;   reason = "STOP_HIT";   break
                    if bl <= target_px: exit_px = target_px; reason = "TARGET_HIT"; break
                    exit_px = bc

                net_pnl = (entry_px - exit_px) * n_shares - n_shares * COMMISSION * 2
                equity += net_pnl

                day_trades.append(dict(
                    ticker=ticker, day=day, year=day.year,
                    entry_time=bar_ts, entry_px=entry_px,
                    stop_px=stop_px, stop_dist=stop_dist,
                    gap_pct=round(gap_pct * 100, 2),
                    shares=n_shares, exit_px=exit_px, reason=reason,
                    net_pnl=net_pnl,
                ))
                entered.add(ticker); slots += 1

        trades.extend(day_trades)

    return pd.DataFrame(trades)


def bootstrap_trade(pnl_arr, n=10_000, seed=42):
    rng  = np.random.default_rng(seed)
    boot = np.array([rng.choice(pnl_arr, size=len(pnl_arr), replace=True).sum()
                     for _ in range(n)])
    p    = float((boot <= 0).mean())
    lo, hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))
    return p, lo, hi


def bootstrap_day(df, n=10_000, seed=42):
    day_pnl = df.groupby("day")["net_pnl"].sum().values
    rng  = np.random.default_rng(seed)
    boot = np.array([rng.choice(day_pnl, size=len(day_pnl), replace=True).sum()
                     for _ in range(n)])
    p    = float((boot <= 0).mean())
    lo, hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))
    return p, lo, hi


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    SEP = "=" * 68

    print("Loading stress days from snapshot...")
    stress_days = get_stress_days()
    print(f"  {len(stress_days)} stress days | {stress_days[0].date()} → {stress_days[-1].date()}")

    print("\nLoading 5-min data...")
    tickers = ["SPY"] + STOCK_UNIVERSE_RAW
    market_data = load_5min(tickers)
    loaded = [t for t in STOCK_UNIVERSE_RAW if t in market_data]
    print(f"  Loaded {len(loaded)}/{len(STOCK_UNIVERSE_RAW)} stocks + SPY")

    print("\nRunning V2 sim (kelly=0.75, max_pos=0.40)...")
    df = run_sim(stress_days, market_data)

    if df.empty:
        print("  NO TRADES generated.")
        sys.exit(0)

    total = df["net_pnl"].sum()
    wr    = (df["net_pnl"] > 0).mean() * 100
    avg   = df["net_pnl"].mean()
    n_days_traded = df["day"].nunique()

    print(f"\n{SEP}")
    print(f"  STRESS_ORB_STK V2 — kelly=0.75 | max_pos=0.40")
    print(SEP)
    print(f"  {len(df)}t across {n_days_traded} days  |  P&L={total:+,.0f}  WR={wr:.0f}%  avg={avg:+.1f}/t")
    print(f"  Shares avg: {df['shares'].mean():.0f}  stop_dist avg: {df['stop_dist'].mean():.2f}")

    # Year breakdown
    print(f"\n  {'Year':<6} {'N':>4} {'Days':>5} {'WR':>5} {'Avg/t':>7} {'Total':>9}")
    print(f"  {'─'*44}")
    for yr, g in df.groupby("year"):
        d = g["day"].nunique()
        print(f"  {yr:<6} {len(g):>4} {d:>5} {(g['net_pnl']>0).mean()*100:>4.0f}%"
              f" {g['net_pnl'].mean():>+7.1f} {g['net_pnl'].sum():>+9,.0f}")

    # Bootstrap comparison
    print(f"\n  {'─'*44}")
    print(f"  Bootstrap (10,000 iterations)")
    print(f"  {'─'*44}")

    p_t, lo_t, hi_t = bootstrap_trade(df["net_pnl"].values)
    p_d, lo_d, hi_d = bootstrap_day(df)

    print(f"  Trade-level ({len(df)} draws):")
    print(f"    p={p_t:.3f}  95%CI=[{lo_t:+,.0f}, {hi_t:+,.0f}]")
    verdict_t = "CONFIRMED" if p_t < 0.05 else ("BORDERLINE" if p_t < 0.10 else "NO EDGE")
    print(f"    → {verdict_t}")

    print(f"\n  Day-level ({n_days_traded} draws — accounts for intra-day correlation):")
    print(f"    p={p_d:.3f}  95%CI=[{lo_d:+,.0f}, {hi_d:+,.0f}]")
    verdict_d = "CONFIRMED" if p_d < 0.05 else ("BORDERLINE" if p_d < 0.10 else "NO EDGE")
    print(f"    → {verdict_d}")

    print(f"\n  H2 2022 concentration check:")
    h2_22 = df[(df["year"] == 2022) & (df["day"].apply(lambda d: d.month >= 7))]
    print(f"    H2-2022: {len(h2_22)}t  P&L={h2_22['net_pnl'].sum():+,.0f}"
          f"  ({h2_22['net_pnl'].sum()/total*100:.0f}% of total)")
    ex_h2 = df[~((df["year"] == 2022) & (df["day"].apply(lambda d: d.month >= 7)))]
    if not ex_h2.empty:
        p_ex, lo_ex, hi_ex = bootstrap_day(ex_h2)
        print(f"    Excluding H2-2022: {len(ex_h2)}t  P&L={ex_h2['net_pnl'].sum():+,.0f}")
        print(f"    Day-level p={p_ex:.3f}  CI=[{lo_ex:+,.0f}, {hi_ex:+,.0f}]")

    print(f"\n{SEP}\n")
