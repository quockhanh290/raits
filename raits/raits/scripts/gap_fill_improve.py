"""
Gap Fill — P&L improvement grid.

Baseline: LONG only, gap 1.5-3%, retrace ≥50%, exit at prev_close (TARGET_HIT).
           31t, +$2,318, WR=83%

Hypotheses:
  A) Target extension: stock continues past prev_close → let it run
     - target = prev_close          (baseline)
     - target = prev_close + 25% of gap_size
     - target = prev_close + 50% of gap_size
     - trail from prev_close (once hit, switch to trailing stop, no fixed exit)
     - no fixed target (chandelier trail to 13:30)

  B) Gap upper bound: more signals
     - gap ≤ 3% (baseline: 31t)
     - gap ≤ 4%
     - gap ≤ 5%

Grid: target_mode × gap_upper  (5 × 3 = 15 combinations)
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

with open(PKL_RESULTS, "rb") as f: results = pickle.load(f)
with open(PKL_5MIN,    "rb") as f: data_5min = pickle.load(f)
for tk in data_5min: data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

rows = []
for w in results:
    for t in w.get("trades",[]):
        d = vars(t).copy(); d["year"] = w.get("label","?"); rows.append(d)
df_all = pd.DataFrame(rows)
df_all["entry_time"] = pd.to_datetime(df_all["entry_time"])
tf_normal = df_all[(df_all["strategy"]=="TREND_FOLLOW") & (df_all["hmm_state"]=="Normal")].copy()
tf_normal["date"] = tf_normal["entry_time"].dt.normalize()
normal_days = sorted(tf_normal["date"].unique())
available_tickers = [tk for tk in data_5min if tk != "SPY"]

spy = data_5min["SPY"].sort_index().copy()
spy["tp"]      = (spy["high"]+spy["low"]+spy["close"])/3
spy["tpv"]     = spy["tp"]*spy["volume"]
spy["date"]    = spy.index.normalize()
spy["cum_tpv"] = spy.groupby("date")["tpv"].cumsum()
spy["cum_vol"] = spy.groupby("date")["volume"].cumsum()
spy["vwap"]    = spy["cum_tpv"] / spy["cum_vol"]
spy["above"]   = spy["close"] > spy["vwap"]
_spy_dict = spy["above"].reindex(
    pd.date_range(spy.index[0], spy.index[-1], freq="5min"), method="ffill"
).to_dict()
def spy_bull(ts): return _spy_dict.get(ts.floor("5min"), None)

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

print("Precomputing caches...")
prev_close_map = {}
day_bars_cache = {}
for ticker in available_tickers:
    if ticker not in data_5min: continue
    bars = data_5min[ticker].sort_index()
    bars["date"] = bars.index.normalize()
    daily_last = bars.groupby("date")["close"].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i-1])
for day in normal_days:
    for ticker in available_tickers:
        if ticker not in data_5min: continue
        db = data_5min[ticker][data_5min[ticker].index.normalize()==day].sort_index()
        if len(db) >= 8: day_bars_cache[(ticker, day)] = db

def simulate_gap_fill(ticker, day, day_bars, target_mode, gap_upper):
    """
    target_mode:
      "prev_close"       → baseline: exit when price hits prev_close
      "extend_25"        → target = prev_close + 0.25 × gap_size
      "extend_50"        → target = prev_close + 0.50 × gap_size
      "trail_from_fill"  → once prev_close hit, switch to trailing stop (no fixed target)
      "trail_only"       → no fixed target, chandelier trail to 13:30
    """
    prev_c = prev_close_map.get((ticker, day))
    if prev_c is None or prev_c <= 0: return None

    first_bar = day_bars[day_bars.index.time >= dtime(9,30)]
    if first_bar.empty: return None
    session_open = float(first_bar.iloc[0]["open"])
    gap_pct  = (session_open - prev_c) / prev_c
    gap_size = session_open - prev_c

    if abs(gap_pct) < 0.015 or abs(gap_pct) > gap_upper: return None
    if gap_pct >= 0: return None  # LONG only → gap down (session_open < prev_c)

    pre_entry = day_bars[day_bars.index.time <= dtime(10,30)]
    if pre_entry.empty: return None
    px_1030 = float(pre_entry.iloc[-1]["close"])

    retrace = (session_open - px_1030) / gap_size if gap_size != 0 else 0
    if not (0.50 <= retrace <= 0.85): return None

    morning_lod = float(pre_entry["low"].min())
    atr = compute_atr(pre_entry)
    if atr <= 0: return None

    # SPY filter
    if spy_bull(pre_entry.index[-1]) is False: return None

    entry_px  = px_1030
    stop_px   = morning_lod - 0.1 * atr
    stop_dist = abs(entry_px - stop_px)
    if stop_dist <= 0: return None
    shares    = max(1, int(500 / stop_dist))

    # Target setup
    if target_mode == "prev_close":
        target_px = prev_c
    elif target_mode == "extend_25":
        target_px = prev_c + 0.25 * abs(gap_size)
    elif target_mode == "extend_50":
        target_px = prev_c + 0.50 * abs(gap_size)
    elif target_mode in ("trail_from_fill", "trail_only"):
        target_px = prev_c  # used as trigger for trail_from_fill; ignored for trail_only
    else:
        target_px = prev_c

    bars_after = day_bars[day_bars.index.time > dtime(10,30)]
    bars_after = bars_after[bars_after.index.time < dtime(13,30)]

    trailing = stop_px; exit_px = entry_px; reason = "TIME_STOP"
    fill_hit = False  # for trail_from_fill mode

    for _, b in bars_after.iterrows():
        # Check for fill (trail_from_fill: once hit, switch to pure trail)
        if target_mode == "trail_from_fill" and not fill_hit:
            if float(b["high"]) >= prev_c:
                fill_hit = True
                # Reset trailing stop to current price level
                trailing = float(b["close"]) - stop_dist

        # Trail update
        trailing = max(trailing, float(b["high"]) - stop_dist)

        # Stop check
        if float(b["low"]) <= trailing:
            exit_px = trailing; reason = "STOP_HIT"; break

        # Fixed target check (not for trail modes)
        if target_mode not in ("trail_from_fill", "trail_only"):
            if float(b["high"]) >= target_px:
                exit_px = target_px; reason = "TARGET_HIT"; break

        exit_px = float(b["close"])

    pnl = exit_px - entry_px
    net = pnl * shares - shares * 0.01 * 2
    return dict(ticker=ticker, date=day, year=str(day.year),
                gap_pct=round(abs(gap_pct)*100,2),
                retrace=round(retrace,2),
                entry_px=entry_px, exit_px=exit_px,
                exit_reason=reason, net_pnl=net, shares=shares, win=net>0)

current_sys = sum(sum(t.net_pnl for t in w.get("trades",[])) for w in results)

TARGET_MODES = [
    ("prev_close",      "target=prev_close (baseline)"),
    ("extend_25",       "target=fill+25% gap"),
    ("extend_50",       "target=fill+50% gap"),
    ("trail_from_fill", "trail after fill"),
    ("trail_only",      "trail only (no target)"),
]
GAP_UPPERS = [0.03, 0.04, 0.05]

print(f"\n{'='*82}")
print(f"  GAP FILL — Target Extension × Gap Upper Bound  [LONG, retrace≥50%, stop=morning_lod]")
print(f"  Current system: ${current_sys:>+,.0f}")
print(f"{'='*82}")
print(f"  {'Target mode':<28} {'gap≤':>5} {'n':>5} {'P&L':>9} {'WR':>5} {'avg':>7} {'sys':>10} {'TGT%':>6} {'20':>8} {'21':>8} {'22':>8}")
print(f"  {'─'*90}")

best_pnl = -999999; best_sim = None; best_label = ""

for mode, mode_label in TARGET_MODES:
    for gap_upper in GAP_UPPERS:
        sigs = []
        for day in normal_days:
            for ticker in available_tickers:
                db = day_bars_cache.get((ticker, day))
                if db is None: continue
                r = simulate_gap_fill(ticker, day, db, mode, gap_upper)
                if r: sigs.append(r)
        if not sigs:
            print(f"  {mode_label:<28} {gap_upper*100:.0f}% {'—':>5}"); continue
        sim = pd.DataFrame(sigs)
        pnl  = sim["net_pnl"].sum()
        wr   = sim["win"].mean()*100
        avg  = sim["net_pnl"].mean()
        sys_ = current_sys + pnl
        tgt_ = (sim["exit_reason"]=="TARGET_HIT").mean()*100
        y20  = sim[sim["year"]=="2020"]["net_pnl"].sum()
        y21  = sim[sim["year"]=="2021"]["net_pnl"].sum()
        y22  = sim[sim["year"]=="2022"]["net_pnl"].sum()
        marker = " ◄" if (pnl > best_pnl) else ""
        print(f"  {mode_label:<28} {gap_upper*100:.0f}% {len(sim):>5} {pnl:>+9,.0f} {wr:>4.0f}% {avg:>+7.1f} {sys_:>+10,.0f} {tgt_:>5.0f}% "
              f"{y20:>+8,.0f} {y21:>+8,.0f} {y22:>+8,.0f}{marker}")
        if pnl > best_pnl:
            best_pnl = pnl; best_sim = sim; best_label = f"{mode_label}, gap≤{gap_upper*100:.0f}%"
    print()

# Detail on best
if best_sim is not None:
    print(f"{'='*82}")
    print(f"  BEST: {best_label}  →  ${best_pnl:>+,.0f}  |  System ${current_sys+best_pnl:>+,.0f}")
    print(f"{'='*82}")
    for r in best_sim["exit_reason"].unique():
        s = best_sim[best_sim["exit_reason"]==r]
        print(f"  {r:<14} {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%  avg=${s['net_pnl'].mean():>+.1f}")
    print()
    for yr in ["2020","2021","2022"]:
        s = best_sim[best_sim["year"]==yr]
        if len(s):
            print(f"  {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+8,.0f}  WR={s['win'].mean()*100:.0f}%")
    tk = best_sim.groupby("ticker")["net_pnl"].agg(n="count", total="sum")
    print(f"\n  Tickers (top 10):")
    print(tk.sort_values("total", ascending=False).head(10).to_string())
