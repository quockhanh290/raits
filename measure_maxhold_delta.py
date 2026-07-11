"""
measure_maxhold_delta.py
------------------------
Đo signed delta P&L cho MAX_HOLD exits:
  backtest: opn[0] = open của 1m bar đầu tiên (~00:00 ET) trên exit_day
  live:     GTC STP @ initial_stop (nếu trigger trước 14:05 ET)
            hoặc close của bar đầu tiên >= 14:05 ET (cron market exit)

383 trades (~15% swing) — delay backtest→live ~14h.

Phân loại:
  STP : initial_stop triggered trong [00:00, 14:05) ET trên exit_day
  CRON: không trigger STP → cron exit lúc 14:05 ET
  MISS: không tìm được bar 14:05 hoặc không có dữ liệu exit_day

Signed delta (từ góc độ system):
  LONG:  delta_pts = live_exit - bt_exit  (âm = live kém hơn backtest)
  SHORT: delta_pts = bt_exit - live_exit

Usage:
    cd d:\\raits
    python measure_maxhold_delta.py
"""

import sys
sys.path.insert(0, r"d:\raits")

import numpy as np
import pandas as pd
from pathlib import Path

from futures.basket import BASKET, REGIME, SWING_TF_PARAM, data_filename
from futures.swing_tf import costs_for_basket
from futures._validated_core import (
    load_parquet, benchmark_daily, label_regimes,
    _swing_cache, atr14,
)
from raits.strategies.trend_follow import TrendFollowStrategy

DATA_DIR  = Path(r"d:\raits\data\cache\futures\frozen_sim")
CRON_TIME   = pd.Timedelta(hours=14, minutes=5)   # current live: 14:05 ET
CRON_TIME_B = pd.Timedelta(hours=9,  minutes=30)  # Option B: RTH open 09:30 ET

MULT     = float(SWING_TF_PARAM["chandelier_atr_mult"])   # 2.5
EMA_P    = int(SWING_TF_PARAM["ema_period"])              # 30
MAX_HOLD = int(SWING_TF_PARAM["max_hold_days"])           # 5


# ── modified backtest: saves initial_stop + ratcheted_stop in MAX_HOLD trades ──

def backtest_maxhold_tagged(df, labels, cost,
                            ema_period=30, chandelier_atr_mult=2.5,
                            max_hold_days=5, gap_fill=True):
    """
    Identical to _validated_core.backtest_swing_tf except MAX_HOLD trade dicts
    carry two extra fields:
        initial_stop   – chandelier stop at entry (GTC STP level in live)
        ratcheted_stop – ratcheted stop on exit_day (backtest's effective stop)
    Standalone copy; never modifies validated core.
    """
    s = TrendFollowStrategy({**TrendFollowStrategy().config,
                             "ema_period": ema_period,
                             "chandelier_atr_mult": chandelier_atr_mult})
    allowed = set(s.config["allowed_regimes"])
    c = _swing_cache(df)
    datr, days, hl, b5, ts = c["datr"], c["days"], c["hl"], c["b5"], c.get("ts", {})
    mult = chandelier_atr_mult
    trades = []
    pos = None

    for day in days:
        exit_ts_today = None
        if pos is not None:
            hold = (day - pos["entry_day"]).days
            if hold >= max_hold_days:
                op = float(hl[day][2][0])
                pts = (op - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - op)
                _ts_exit = ts.get(day)
                trades.append(dict(
                    day=pos["entry_day"].date(),
                    exit_day=day.date(),
                    exit_day_ts=day,              # tz-naive normalized Timestamp
                    regime=pos["regime"],
                    direction=pos["dir"],
                    entry=round(pos["entry"], 2),
                    bt_exit=round(op, 2),
                    bt_pts=round(pts, 2),
                    bt_pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                    hold_days=hold,
                    reason="MAX_HOLD",
                    initial_stop=round(pos["initial_stop"], 2),
                    ratcheted_stop=round(pos["stop"], 2),
                ))
                pos = None
                exit_ts_today = _ts_exit[0] if _ts_exit is not None and len(_ts_exit) > 0 else None
            else:
                high, low, opn, isg = hl[day]
                da = float(datr.asof(day)) if len(datr) else np.nan
                if not np.isnan(da) and da > 0 and len(high):
                    if pos["dir"] == "LONG":
                        run_full = np.maximum.accumulate(np.maximum(high, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = np.maximum.accumulate(
                            np.maximum(run_prev - mult * da, pos["stop"]))
                        hit = np.where(low <= stop_prev)[0]
                    else:
                        run_full = np.minimum.accumulate(np.minimum(low, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = np.minimum.accumulate(
                            np.minimum(run_prev + mult * da, pos["stop"]))
                        hit = np.where(high >= stop_prev)[0]
                    if len(hit):
                        i = hit[0]; stp = float(stop_prev[i])
                        gapped = gap_fill and bool(isg[i]) and (
                            (pos["dir"] == "LONG"  and float(opn[i]) < stp) or
                            (pos["dir"] == "SHORT" and float(opn[i]) > stp))
                        ex     = float(opn[i]) if gapped else stp
                        reason = "GAP" if gapped else "CHANDELIER"
                        pts    = (ex - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - ex)
                        _ts_exit = ts.get(day)
                        trades.append(dict(
                            day=pos["entry_day"].date(), exit_day=day.date(),
                            regime=pos["regime"], direction=pos["dir"],
                            entry=round(pos["entry"], 2), exit=round(ex, 2),
                            points=round(pts, 2),
                            pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                            hold_days=hold, reason=reason,
                        ))
                        pos = None
                        exit_ts_today = _ts_exit[i] if _ts_exit is not None and i < len(_ts_exit) else None
                    else:
                        if pos["dir"] == "LONG":
                            pos["stop"] = float(np.maximum(pos["stop"], run_full[-1] - mult * da))
                        else:
                            pos["stop"] = float(np.minimum(pos["stop"], run_full[-1] + mult * da))
                        pos["extreme"] = float(run_full[-1])

        if pos is None:
            reg = labels.get(day)
            if reg in allowed:
                bars5 = b5[day]; win = bars5.between_time("14:00", "15:55")
                if exit_ts_today is not None:
                    win = win[win.index > exit_ts_today]
                    if len(win) < 2:
                        continue
                idx = list(win.index)
                for n in range(1, len(idx)):
                    hist = bars5.loc[:idx[n]]
                    if len(hist) < max(ema_period, 14) + 1:
                        continue
                    ema  = s.calculate_ema(hist, ema_period)
                    atr  = atr14(hist)
                    avgv = float(win["volume"].iloc[max(0, n - 11):n - 1].mean())
                    if np.isnan(atr) or np.isnan(avgv):
                        continue
                    sig = s.generate_signal(win.loc[idx[n - 1]], win.loc[idx[n]],
                                            ema, atr, reg, avgv)
                    if sig:
                        pos = dict(
                            dir=sig["direction"], entry=sig["entry_price"],
                            entry_day=day, regime=reg,
                            extreme=sig["entry_price"],
                            stop=sig["initial_stop"],
                            initial_stop=sig["initial_stop"],  # saved separately; ratchet starts here
                            entry_time=idx[n],
                        )
                        break
    return trades


def _check_stp_in_window(pre_cron_bars, direction, initial_stop):
    """Return (fill, ts) if STP triggered in window, else (None, None)."""
    for ts_bar, bar in pre_cron_bars.iterrows():
        if direction == "LONG":
            if float(bar["low"]) <= initial_stop:
                fill = float(bar["open"]) if float(bar["open"]) <= initial_stop else initial_stop
                return fill, ts_bar
        else:
            if float(bar["high"]) >= initial_stop:
                fill = float(bar["open"]) if float(bar["open"]) >= initial_stop else initial_stop
                return fill, ts_bar
    return None, None


def find_live_exit(day_bars_naive, trade, cron_td=None):
    """
    Simulate live exit for a MAX_HOLD trade.
    cron_td: pd.Timedelta for cron time (default=CRON_TIME=14:05, Option B=CRON_TIME_B=09:30).
    Returns (price, exit_type ["STP"|"CRON"|"MISS"], stp_ts_or_None)
    """
    if cron_td is None:
        cron_td = CRON_TIME
    if day_bars_naive is None or len(day_bars_naive) == 0:
        return None, "MISS", None

    direction    = trade["direction"]
    initial_stop = trade["initial_stop"]

    bt_bar_ts       = day_bars_naive.index[0]
    bt_date         = bt_bar_ts.normalize()
    cron_threshold  = bt_date + cron_td

    pre_cron  = day_bars_naive[
        (day_bars_naive.index >= bt_bar_ts) & (day_bars_naive.index < cron_threshold)
    ]
    cron_bars = day_bars_naive[day_bars_naive.index >= cron_threshold]

    stp_fill, stp_ts = _check_stp_in_window(pre_cron, direction, initial_stop)
    if stp_fill is not None:
        return stp_fill, "STP", stp_ts

    if len(cron_bars) == 0:
        return None, "MISS", None
    return float(cron_bars.iloc[0]["open"]), "CRON", None


# ── load ──────────────────────────────────────────────────────────────────────
print("=" * 72)
print("measure_maxhold_delta — MAX_HOLD exits: backtest opn[0] vs live exit")
print(f"  data-dir: {DATA_DIR}")
print(f"  mult={MULT}, ema_period={EMA_P}, max_hold={MAX_HOLD}")
print("=" * 72)

print("\n[1] Loading parquet + running tagged backtest...")
dfs    = {n: load_parquet(str(DATA_DIR / data_filename(c))) for n, c in BASKET.items()}
labels = label_regimes(benchmark_daily(r"d:\raits\spy_daily_live.csv"),
                       "2018-01-01", 3, REGIME["hmm_fit_end"])
costs  = costs_for_basket(slippage_ticks=2.0)

bt = {}
for inst, df in dfs.items():
    bt[inst] = backtest_maxhold_tagged(
        df, labels, costs[inst],
        ema_period=EMA_P, chandelier_atr_mult=MULT, max_hold_days=MAX_HOLD,
    )
    mh = [t for t in bt[inst] if t.get("reason") == "MAX_HOLD"]
    print(f"  {inst}: {len(bt[inst])} total trades  -> {len(mh)} MAX_HOLD")

# ── build tz-naive dfs for bar lookup ─────────────────────────────────────────
dfs_naive = {}
for inst, df in dfs.items():
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    df2 = df.copy(); df2.index = idx
    dfs_naive[inst] = df2

# ── measure delta for each MAX_HOLD trade ────────────────────────────────────
print("\n[2] Measuring live vs backtest delta for MAX_HOLD trades...")

rows = []
for inst in BASKET:
    pv = costs[inst].point_value
    rt = costs[inst].round_turn_cost()
    df_n = dfs_naive[inst]

    for trade in bt[inst]:
        if trade.get("reason") != "MAX_HOLD":
            continue

        exit_day_ts = pd.Timestamp(trade["exit_day_ts"])   # tz-naive normalized

        # Get all 1-min bars for exit_day
        day_bars = df_n[df_n.index.normalize() == exit_day_ts]

        live_price, exit_type, stp_ts = find_live_exit(
            day_bars if len(day_bars) > 0 else None, trade
        )

        # Option B: simulate 09:30 ET cron (instead of 14:05 ET)
        b_price, b_type, b_stp_ts = find_live_exit(
            day_bars if len(day_bars) > 0 else None, trade, cron_td=CRON_TIME_B
        )

        # For current STP-exit trades: record 14:05 ET counterfactual (no-STP)
        cron_price_cf = None
        if exit_type == "STP" and len(day_bars) > 0:
            cron_thresh = day_bars.index[0].normalize() + CRON_TIME
            cron_cf = day_bars[day_bars.index >= cron_thresh]
            if len(cron_cf) > 0:
                cron_price_cf = float(cron_cf.iloc[0]["open"])

        if live_price is None:
            rows.append({**trade, "inst": inst, "pv": pv,
                         "live_exit": None, "exit_type": "MISS",
                         "delta_pts": None, "delta_pnl": None,
                         "cron_cf": None, "stp_vs_cron_pnl": None,
                         "b_exit": None, "b_type": "MISS", "b_delta_pnl": None})
            continue

        bt_exit   = trade["bt_exit"]
        direction = trade["direction"]

        if direction == "LONG":
            delta_pts    = live_price - bt_exit
            stp_vs_cron  = (live_price - cron_price_cf) if cron_price_cf is not None else None
            b_delta_pts  = (b_price - bt_exit) if b_price is not None else None
        else:
            delta_pts    = bt_exit - live_price
            stp_vs_cron  = (cron_price_cf - live_price) if cron_price_cf is not None else None
            b_delta_pts  = (bt_exit - b_price) if b_price is not None else None

        delta_pnl        = delta_pts * pv
        stp_vs_cron_pnl  = (stp_vs_cron * pv) if stp_vs_cron is not None else None
        b_delta_pnl      = (b_delta_pts * pv) if b_delta_pts is not None else None

        rows.append({
            **trade, "inst": inst, "pv": pv,
            "live_exit": round(live_price, 4),
            "exit_type": exit_type,
            "stp_ts": stp_ts,
            "delta_pts": round(delta_pts, 4),
            "delta_pnl": round(delta_pnl, 2),
            "cron_cf": round(cron_price_cf, 4) if cron_price_cf is not None else None,
            "stp_vs_cron_pnl": round(stp_vs_cron_pnl, 2) if stp_vs_cron_pnl is not None else None,
            "b_exit": round(b_price, 4) if b_price is not None else None,
            "b_type": b_type,
            "b_stp_ts": b_stp_ts,
            "b_delta_pnl": round(b_delta_pnl, 2) if b_delta_pnl is not None else None,
        })

df_res = pd.DataFrame(rows)
mh = df_res[df_res["reason"] == "MAX_HOLD"].copy()

# ── report ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("MAX_HOLD EXIT DELTA REPORT")
print("=" * 72)

total_mh = len(mh)
n_stp  = (mh["exit_type"] == "STP").sum()
n_cron = (mh["exit_type"] == "CRON").sum()
n_miss = (mh["exit_type"] == "MISS").sum()

print(f"\nTotal MAX_HOLD trades: {total_mh}")
print(f"  STP triggered (before 14:05 ET): {n_stp}  ({100*n_stp/total_mh:.1f}%)")
print(f"  CRON exit (14:05 ET)           : {n_cron}  ({100*n_cron/total_mh:.1f}%)")
print(f"  MISS (no bar data)             : {n_miss}")

valid = mh[mh["delta_pnl"].notna()]

# ── CRON exits ────────────────────────────────────────────────────────────────
cron_rows = valid[valid["exit_type"] == "CRON"]
if len(cron_rows):
    print(f"\n── CRON exits ({len(cron_rows)} trades) ──")
    print(f"  Mean delta_pts per trade : {cron_rows['delta_pts'].mean():.3f} pts")
    print(f"  Std  delta_pts           : {cron_rows['delta_pts'].std():.3f} pts")
    print(f"  Mean delta_pnl per trade : ${cron_rows['delta_pnl'].mean():.2f}")
    print(f"  Total delta_pnl / 6yr   : ${cron_rows['delta_pnl'].sum():.2f}")
    n_pos = (cron_rows["delta_pnl"] > 0).sum()
    n_neg = (cron_rows["delta_pnl"] < 0).sum()
    print(f"  Live better (>0): {n_pos} ({100*n_pos/len(cron_rows):.0f}%)  "
          f"  Live worse (<0): {n_neg} ({100*n_neg/len(cron_rows):.0f}%)")
    q25, q50, q75 = cron_rows["delta_pnl"].quantile([0.25, 0.5, 0.75])
    print(f"  Percentiles [25/50/75]: ${q25:.2f} / ${q50:.2f} / ${q75:.2f}")

    # Per instrument
    print(f"\n  Per instrument (CRON):")
    for inst in BASKET:
        sub = cron_rows[cron_rows["inst"] == inst]
        if len(sub):
            print(f"    {inst}: {len(sub)} trades  mean={sub['delta_pnl'].mean():.2f}  "
                  f"total={sub['delta_pnl'].sum():.2f}")

# ── STP exits ────────────────────────────────────────────────────────────────
stp_rows = valid[valid["exit_type"] == "STP"]
if len(stp_rows):
    print(f"\n── STP exits ({len(stp_rows)} trades: initial_stop triggered before 14:05 ET) ──")
    print(f"  Mean delta_pts per trade : {stp_rows['delta_pts'].mean():.3f} pts")
    print(f"  Mean delta_pnl per trade : ${stp_rows['delta_pnl'].mean():.2f}")
    print(f"  Total delta_pnl / 6yr   : ${stp_rows['delta_pnl'].sum():.2f}")
    # STP-protection counterfactual: STP vs no-STP (14:05 ET)
    cf = stp_rows["stp_vs_cron_pnl"].dropna()
    if len(cf):
        n_stp_better = (cf > 0).sum()   # STP exit > counterfactual 14:05 ET
        n_stp_worse  = (cf < 0).sum()
        print(f"\n  STP counterfactual (STP fill vs no-STP 14:05 ET price, N={len(cf)}):")
        print(f"    STP better than 14:05 ET: {n_stp_better} trades ({100*n_stp_better/len(cf):.0f}%)")
        print(f"    STP worse than 14:05 ET : {n_stp_worse} trades ({100*n_stp_worse/len(cf):.0f}%)")
        print(f"    Mean STP vs 14:05 ET    : ${cf.mean():.2f}/trade")
        print(f"    Total STP vs 14:05 ET   : ${cf.sum():.2f}/6yr")
        print(f"    (positive = STP exited at better price than no-STP 14:05 ET would)")

# ── COMBINED ────────────────────────────────────────────────────────────────
if len(valid):
    total_delta = valid["delta_pnl"].sum()
    mean_delta  = valid["delta_pnl"].mean()
    print(f"\n── COMBINED (CRON + STP exits, N={len(valid)}) ──")
    print(f"  Total delta_pnl / 6yr   : ${total_delta:.2f}")
    print(f"  Mean delta_pnl per trade : ${mean_delta:.2f}")
    n_pos = (valid["delta_pnl"] > 0).sum()
    n_neg = (valid["delta_pnl"] < 0).sum()
    print(f"  Live better (>0): {n_pos} ({100*n_pos/len(valid):.0f}%)  "
          f"  Live worse (<0): {n_neg} ({100*n_neg/len(valid):.0f}%)")

    print(f"\n── Per instrument (ALL MAX_HOLD) ──")
    for inst in BASKET:
        sub = valid[valid["inst"] == inst]
        if len(sub):
            cron_n = (sub["exit_type"] == "CRON").sum()
            stp_n  = (sub["exit_type"] == "STP").sum()
            print(f"  {inst}: {len(sub)} trades  (CRON={cron_n} STP={stp_n})  "
                  f"mean_delta={sub['delta_pnl'].mean():.2f}  "
                  f"total={sub['delta_pnl'].sum():.2f}")

    # Vault (backtest) total for MAX_HOLD trades
    vault_total = mh["bt_pnl"].sum()
    print(f"\n── Vault vs paper (MAX_HOLD trades) ──")
    print(f"  Vault MAX_HOLD total P&L  : ${vault_total:.2f}/6yr")
    print(f"  Expected paper gap        : ${total_delta:.2f}/6yr  ({total_delta/6:.0f}/yr)")
    print(f"  Paper MAX_HOLD expected   : ${vault_total + total_delta:.2f}/6yr")
    print(f"  Real gap: live holds 14h past design 'exit at 00:00 ET open'.")

    # ── OPTION B: 09:30 ET cron vs backtest midnight ─────────────────────────
    b_valid = mh[mh["b_delta_pnl"].notna()].copy()
    if len(b_valid):
        # STP window classification: use b_type for STP trades
        # b_type=="STP"  → trigger 00:00-09:30 ET (B still STP, cannot save)
        # b_type=="CRON" → trigger 09:30-14:05 ET (B catches as 09:30 CRON exit)
        stp_trades  = mh[mh["exit_type"] == "STP"]
        stp_pre_b   = stp_trades[stp_trades["b_type"] == "STP"]   # B can't help
        stp_post_b  = stp_trades[stp_trades["b_type"] == "CRON"]  # B catches these

        print(f"\n-- Option B: 09:30 ET cron (vs current 14:05 ET) --")
        print(f"  {len(stp_trades)} STP trades by trigger time:")
        print(f"    00:00-09:30 ET (B cannot save): {len(stp_pre_b)} trades")
        print(f"    09:30-14:05 ET (B saves these): {len(stp_post_b)} trades  "
              f"(drag={mh.loc[stp_post_b.index,'delta_pnl'].sum():+.0f} current)")

        b_cron = b_valid[b_valid["b_type"] == "CRON"]
        b_stp  = b_valid[b_valid["b_type"] == "STP"]
        b_total = b_valid["b_delta_pnl"].sum()
        cur_total = valid["delta_pnl"].sum()
        print(f"\n  Option B vs backtest midnight:")
        print(f"    B CRON trades ({len(b_cron)}): {b_valid.loc[b_cron.index,'b_delta_pnl'].sum():+.0f}")
        print(f"    B STP  trades ({len(b_stp)}):  {b_valid.loc[b_stp.index,'b_delta_pnl'].sum():+.0f}")
        print(f"    B combined total : ${b_total:+.2f}/6yr  ({b_total/6:+.0f}/yr)")
        print(f"    Current (14:05)  : ${cur_total:+.2f}/6yr  ({cur_total/6:+.0f}/yr)")
        improvement = b_total - cur_total
        print(f"    B improvement    : ${improvement:+.2f}/6yr  ({improvement/6:+.0f}/yr)")

        # Year-by-year B vs current
        b_valid2 = b_valid.copy()
        b_valid2["year"] = pd.to_datetime(b_valid2["exit_day"]).dt.year
        print(f"\n  Year-by-year: current (14:05) vs B (09:30) vs backtest midnight")
        print(f"  {'Year':<6} {'cur_14:05':>10} {'B_09:30':>10} {'B_improve':>10}  note")
        years2 = sorted(b_valid2["year"].unique())
        for yr in years2:
            yr_b   = b_valid2[b_valid2["year"] == yr]
            yr_cur = valid[pd.to_datetime(valid["exit_day"]).dt.year == yr] if "exit_day" in valid.columns else yr_b
            cur_d  = yr_cur["delta_pnl"].sum() if len(yr_cur) else 0
            b_d    = yr_b["b_delta_pnl"].sum()
            imp    = b_d - cur_d
            note   = " +trend" if b_d > cur_d else (" same" if abs(imp) < 50 else " worse")
            print(f"  {yr:<6} {cur_d:>+10.0f} {b_d:>+10.0f} {imp:>+10.0f} {note}")

    # ── YEAR-BY-YEAR breakdown ────────────────────────────────────────────────
    valid2 = valid.copy()
    valid2["year"] = pd.to_datetime(valid2["exit_day"]).dt.year
    print(f"\n── Year-by-year MAX_HOLD delta (vs vault midnight exit) ──")
    print(f"  {'Year':<6} {'N':>4} {'CRON':>5} {'STP':>4}  "
          f"{'CRON_delta':>11} {'STP_delta':>11} {'Combined':>11}  worst_STP")
    years = sorted(valid2["year"].unique())
    worst_year, worst_val = None, 0
    for yr in years:
        yr_rows  = valid2[valid2["year"] == yr]
        yr_cron  = yr_rows[yr_rows["exit_type"] == "CRON"]
        yr_stp   = yr_rows[yr_rows["exit_type"] == "STP"]
        cron_d   = yr_cron["delta_pnl"].sum()
        stp_d    = yr_stp["delta_pnl"].sum()
        combined = cron_d + stp_d
        worst_stp_trade = yr_stp["delta_pnl"].min() if len(yr_stp) > 0 else 0
        flag = " ← WORST" if combined == min(
            (valid2[valid2["year"]==y]["delta_pnl"].sum() for y in years)) else ""
        print(f"  {yr:<6} {len(yr_rows):>4} {len(yr_cron):>5} {len(yr_stp):>4}  "
              f"{cron_d:>+11.0f} {stp_d:>+11.0f} {combined:>+11.0f}  "
              f"{worst_stp_trade:>+.0f}{flag}")
        if combined < worst_val:
            worst_val, worst_year = combined, yr
    print()
    yr_deltas = [valid2[valid2["year"]==y]["delta_pnl"].sum() for y in years]
    print(f"  Best year : ${max(yr_deltas):+.0f}   Worst year: ${min(yr_deltas):+.0f}")
    print(f"  Years negative: {sum(1 for d in yr_deltas if d < 0)}/{len(years)}  "
          f"  STP trades/yr: {len(valid2[valid2['exit_type']=='STP'])/len(years):.1f} avg")

print()
