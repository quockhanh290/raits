"""
vwap_reclaim_sim.py — VWAP Reclaim SHORT diagnostic.

Signal:
  1. SPY bearish day: SPY close at 10:15 < SPY VWAP at 10:15
  2. Stock sustained below own VWAP (>=4/6 bars below VWAP before signal bar)
  3. In 10:30-13:30: bar HIGH touches VWAP from below, but closes BELOW VWAP
     (rejection confirmed) -> SHORT at bar close

Stop:  VWAP + 0.5*ATR
Target: 2R below entry
Time stop: 14:00

Universe: SPY/QQQ/IWM (cap=2) + all stocks/sector ETFs in cache (cap=3)
Sizing: Kelly, engine-faithful (capped at 1% risk / 20% position)

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\vwap_reclaim_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_5MIN = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

ACCOUNT_START  = 50_000.0
MAX_RISK_PCT   = 0.01
MAX_POS_PCT    = 0.20
KELLY_FRAC     = 0.5
KELLY_STATS    = {"win_rate": 0.50, "avg_win": 2.50, "avg_loss": 1.50}
COMMISSION     = 0.01
TARGET_R       = 2.0
ATR_MULT_STOP  = 0.5
MAX_SLOTS_CORE = 2
MAX_SLOTS_STK  = 3
MIN_BELOW_BARS = 4   # of last 6 bars must be < VWAP before signal

CONFIRM_TIME = dtime(10, 15)
SIGNAL_START = dtime(10, 30)
SIGNAL_END   = dtime(13, 30)
TIME_STOP_T  = dtime(14, 0)

CORE_ETF = {"SPY", "QQQ", "IWM"}

# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading data...")
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

ALL_TICKERS = sorted(data_5min.keys())
print(f"Tickers: {len(ALL_TICKERS)}")

spy_idx = data_5min["SPY"].sort_index().index
all_days = sorted({ts.normalize() for ts in spy_idx if 2020 <= ts.year <= 2022})
print(f"Trading days 2020-2022: {len(all_days)}")

# ── Precompute day bars cache ─────────────────────────────────────────────────
print("Precomputing caches...")
day_bars_cache: dict = {}
for ticker in ALL_TICKERS:
    bars = data_5min[ticker].sort_index()
    for day in all_days:
        db = bars[bars.index.normalize() == day]
        if len(db) >= 4:
            day_bars_cache[(ticker, day)] = db
print(f"Cache: {len(day_bars_cache)} entries")


# ── Helpers ───────────────────────────────────────────────────────────────────
def compute_vwap(bars: pd.DataFrame) -> pd.Series:
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3
    cum_vol = bars["volume"].cumsum().replace(0, np.nan)
    return (typical * bars["volume"]).cumsum() / cum_vol


def compute_atr(bars: pd.DataFrame, period: int = 14) -> float:
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())


def kelly_size(entry_px: float, stop_px: float, equity: float) -> int:
    p  = KELLY_STATS["win_rate"]
    q  = 1.0 - p
    b  = KELLY_STATS["avg_win"] / KELLY_STATS["avg_loss"]
    fk = (p * b - q) / b
    if fk <= 0:
        return 0
    hk       = fk * KELLY_FRAC
    kelly_sh = int(equity * hk / max(entry_px, 1))
    risk_ps  = abs(entry_px - stop_px)
    if risk_ps <= 0:
        return 0
    vol_sh   = int(equity * MAX_RISK_PCT / risk_ps)
    limit_sh = int(equity * MAX_POS_PCT  / max(entry_px, 1))
    return max(0, min(kelly_sh, vol_sh, limit_sh))


# ── Core simulation ───────────────────────────────────────────────────────────
def run_sim() -> list:
    equity       = ACCOUNT_START
    trades       = []
    bearish_days = 0

    for day in all_days:
        # SPY bearish filter: close at 10:15 < VWAP at 10:15
        spy_db = day_bars_cache.get(("SPY", day))
        if spy_db is None:
            continue
        spy_morning = spy_db[spy_db.index.time <= CONFIRM_TIME]
        if len(spy_morning) < 3:
            continue
        spy_vwap = compute_vwap(spy_morning)
        if float(spy_morning.iloc[-1]["close"]) >= float(spy_vwap.iloc[-1]):
            continue
        bearish_days += 1

        slots_core = 0
        slots_stk  = 0
        entered    = set()

        for ticker in ALL_TICKERS:
            is_core = ticker in CORE_ETF
            if is_core     and slots_core >= MAX_SLOTS_CORE:
                continue
            if not is_core and slots_stk  >= MAX_SLOTS_STK:
                continue
            if ticker in entered:
                continue

            tk_db = day_bars_cache.get((ticker, day))
            if tk_db is None:
                continue

            session = tk_db[tk_db.index.time >= dtime(9, 30)].copy()
            if len(session) < 6:
                continue

            vwap_series = compute_vwap(session)

            sig_bars = session[(session.index.time >= SIGNAL_START) &
                               (session.index.time <= SIGNAL_END)]
            if len(sig_bars) < 2:
                continue

            for i in range(1, len(sig_bars)):
                curr_bar = sig_bars.iloc[i]
                prev_bar = sig_bars.iloc[i - 1]
                bar_ts   = sig_bars.index[i]

                vwap_val = float(vwap_series.loc[bar_ts])
                if pd.isna(vwap_val) or vwap_val <= 0:
                    continue

                # C1: prev bar was below VWAP
                if float(prev_bar["close"]) >= vwap_val:
                    continue

                # C2: curr bar HIGH touched VWAP from below
                if float(curr_bar["high"]) < vwap_val:
                    continue

                # C3: curr bar closed BELOW VWAP (rejection confirmed)
                curr_close = float(curr_bar["close"])
                if curr_close >= vwap_val:
                    continue

                # C4: sustained below VWAP — at least MIN_BELOW_BARS of last 6
                bars_so_far = session.loc[:bar_ts]
                last6 = bars_so_far.iloc[-7:-1]
                if len(last6) < MIN_BELOW_BARS:
                    continue
                n_below = int(
                    (last6["close"].values < vwap_series.loc[last6.index].values).sum()
                )
                if n_below < MIN_BELOW_BARS:
                    continue

                # Entry
                entry_px  = curr_close
                atr       = compute_atr(bars_so_far)
                stop_px   = vwap_val + ATR_MULT_STOP * atr
                stop_dist = stop_px - entry_px
                if stop_dist <= 0:
                    continue
                target_px = entry_px - TARGET_R * stop_dist

                n_shares = kelly_size(entry_px, stop_px, equity)
                if n_shares < 1:
                    continue

                # Forward simulate
                fwd = session[(session.index > bar_ts) &
                              (session.index.time <= TIME_STOP_T)]
                exit_px = entry_px
                reason  = "TIME_STOP"
                for _, b in fwd.iterrows():
                    bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
                    if bh >= stop_px:
                        exit_px = stop_px
                        reason  = "STOP_HIT"
                        break
                    if bl <= target_px:
                        exit_px = target_px
                        reason  = "TARGET_HIT"
                        break
                    exit_px = bc

                net_pnl = (entry_px - exit_px) * n_shares - n_shares * COMMISSION * 2
                equity += net_pnl

                trades.append(dict(
                    ticker=ticker, day=day, year=str(day.year),
                    bar_ts=bar_ts, entry_px=entry_px,
                    vwap=vwap_val, stop_px=stop_px,
                    stop_dist=stop_dist, target_px=target_px,
                    shares=n_shares, exit_px=exit_px,
                    reason=reason, net_pnl=net_pnl, win=net_pnl > 0,
                    is_core=is_core,
                ))
                entered.add(ticker)
                if is_core:
                    slots_core += 1
                else:
                    slots_stk += 1
                break  # one entry per ticker per day

    print(f"  SPY-bearish days: {bearish_days}/{len(all_days)}")
    return trades


# ── Reporting ─────────────────────────────────────────────────────────────────
def report(trades: list):
    if not trades:
        print("  0 trades — signal never fired")
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
    p            = float((boot <= 0).mean())
    ci_lo, ci_hi = float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))
    sig          = "SIGNIFICANT" if p < 0.05 else "not significant"

    print(f"\n  {len(df)}t  P&L={total:+,.0f}  WR={wr:.0f}%  avg/t={avg:+.1f}"
          f"  shares={df['shares'].mean():.0f}  stop={df['stop_dist'].mean():.2f}")
    print(f"  p={p:.3f}  CI=[{ci_lo:+,.0f}, {ci_hi:+,.0f}]  {sig}")

    for yr in ["2020", "2021", "2022"]:
        y = df[df["year"] == yr]
        if len(y):
            print(f"    {yr}: {len(y):3}t  {y['net_pnl'].sum():>+8,.0f}"
                  f"  WR={y['win'].mean()*100:.0f}%  avg={y['net_pnl'].mean():+.1f}")

    by_r = df.groupby("reason")["net_pnl"].agg(n="count", total="sum")
    for r_, row in by_r.iterrows():
        print(f"    {r_:<14}: {int(row['n'])}t  {row['total']:>+8,.0f}")

    core = df[df["is_core"]]
    stk  = df[~df["is_core"]]
    if len(core):
        print(f"    Core ETF  : {len(core)}t  {core['net_pnl'].sum():>+8,.0f}"
              f"  WR={core['win'].mean()*100:.0f}%")
    if len(stk):
        print(f"    Stocks+ETF: {len(stk)}t  {stk['net_pnl'].sum():>+8,.0f}"
              f"  WR={stk['win'].mean()*100:.0f}%")

    tk_pnl = df.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
    top5   = "  ".join(f"{t}({v:+,.0f})" for t, v in tk_pnl.head(5).items())
    bot5   = "  ".join(f"{t}({v:+,.0f})" for t, v in tk_pnl.tail(5).items())
    print(f"    Top-5:    {top5}")
    print(f"    Bottom-5: {bot5}")


# ── Main ──────────────────────────────────────────────────────────────────────
HDR = "=" * 65
print(f"\nRunning VWAP Reclaim SHORT sim...")
trades = run_sim()

print(f"\n{HDR}")
print(f"  VWAP RECLAIM SHORT  —  2020-2022")
print(f"  SPY<VWAP@10:15  |  bounce+reject VWAP 10:30-13:30  |  exit@14:00")
print(f"  Stop=VWAP+{ATR_MULT_STOP}xATR  |  Target={TARGET_R}R  |  MIN_BELOW={MIN_BELOW_BARS}/6 bars")
print(f"{HDR}")
report(trades)
print(f"{HDR}\n")
