"""
futures/analyze_maxhold_drift.py — measure 09:30→09:31 price drift on MAX_HOLD exits
=====================================================================================
Đo signed drift: giá bar 09:30 (backtest exit) vs giá bar 09:31 (live fill ~09:31 ET).
Mục đích: xác nhận "2-tick slippage cover 1-phút drift" đúng hay không.

2-tick slippage = spread cùng thời điểm (bid/ask).
1-phút drift = giá di chuyển từ 09:30 đến 09:31 (khác loại, cần đo riêng).

Positive signed drift = live fill TỐT HƠN backtest (favorable):
  - LONG exit: giá 09:31 > 09:30 → ta bán cao hơn → tốt hơn
  - SHORT exit: giá 09:31 < 09:30 → ta mua thấp hơn → tốt hơn

Run:
    cd d:\\raits
    python futures/analyze_maxhold_drift.py
    python futures/analyze_maxhold_drift.py --data-dir data/cache/futures/frozen_sim
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from futures._validated_core import load_parquet, benchmark_daily, label_regimes
from futures.basket import BASKET, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket

ET = "America/New_York"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",   default="data/cache/futures/frozen_sim")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    ap.add_argument("--end",        default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    a = ap.parse_args()

    data_dir = Path(a.data_dir)
    print(f"Loading parquets from: {data_dir}")

    bench = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, "2018-01-01", 3, a.hmm_fit_end)
    costs  = costs_for_basket(slippage_ticks=a.slippage_ticks)

    dfs = {}
    for n, c in BASKET.items():
        path = data_dir / data_filename(c)
        df = load_parquet(str(path))
        if a.end:
            end_ts = pd.Timestamp(a.end).tz_localize(df.index.tz)
            df = df[df.index <= end_ts]
        dfs[n] = df

    print(f"Running backtest (slippage={a.slippage_ticks}t) ...")
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)

    results = []
    missing = []

    for inst, trades in swing.items():
        c  = BASKET[inst]
        df = dfs[inst]  # TZ-aware ET index

        for t in trades:
            if t.get("reason") != "MAX_HOLD":
                continue

            exit_time_930 = t.get("exit_time")
            if exit_time_930 is None:
                missing.append((inst, t.get("exit_day")))
                continue

            # exit_time is TZ-aware ET 09:30 bar timestamp
            exit_time_931 = exit_time_930 + pd.Timedelta(minutes=1)

            # look up 09:31 bar
            bar_931 = df[df.index == exit_time_931]
            if bar_931.empty:
                missing.append((inst, exit_time_931))
                continue

            price_930 = t["exit"]           # backtest exit price (bar open at 09:30)
            price_931 = float(bar_931["open"].iloc[0])

            # Sanity: verify 09:30 open in raw data matches backtest exit
            bar_930_raw = df[df.index == exit_time_930]
            if not bar_930_raw.empty:
                raw_930 = float(bar_930_raw["open"].iloc[0])
                if abs(raw_930 - price_930) > c.tick * 5:
                    print(f"  WARN mismatch {inst} {exit_time_930}: "
                          f"raw={raw_930} backtest={price_930}")

            # Signed drift (positive = favorable for our position)
            if t["direction"] == "LONG":
                drift_pts = price_931 - price_930
            else:
                drift_pts = price_930 - price_931

            drift_usd = drift_pts * c.point_value

            results.append({
                "inst":       inst,
                "exit_day":   str(t.get("exit_day", "")),
                "direction":  t["direction"],
                "price_930":  price_930,
                "price_931":  price_931,
                "drift_pts":  drift_pts,
                "drift_usd":  drift_usd,
                "pv":         c.point_value,
                "tick_val":   c.tick * c.point_value,
            })

    if missing:
        print(f"\nWARN: {len(missing)} MAX_HOLD trades skipped (no exit_time or no 09:31 bar)")
        for m in missing[:5]:
            print(f"  {m}")

    if not results:
        print("No MAX_HOLD trades found")
        return

    df_r = pd.DataFrame(results)

    print(f"\n{'='*64}")
    print(f"MAX_HOLD 1-min drift:  09:30 bar open  →  09:31 bar open")
    print(f"{'='*64}")
    print(f"Trades: {len(df_r)}  (MAX_HOLD exits only, basket Rổ 4, n=1)")

    print(f"\nSigned drift (+ = favorable, - = adverse):")
    print(f"  mean    {df_r['drift_usd'].mean():+8.2f} $/trade")
    print(f"  median  {df_r['drift_usd'].median():+8.2f} $/trade")
    print(f"  std     {df_r['drift_usd'].std():8.2f} $/trade")
    print(f"  min     {df_r['drift_usd'].min():+8.2f} $/trade")
    print(f"  max     {df_r['drift_usd'].max():+8.2f} $/trade")
    print(f"\n  favorable (drift > 0): {(df_r['drift_usd'] > 0).sum():3d} trades")
    print(f"  neutral  (drift = 0):  {(df_r['drift_usd'] == 0).sum():3d} trades")
    print(f"  adverse  (drift < 0):  {(df_r['drift_usd'] < 0).sum():3d} trades")

    total = df_r["drift_usd"].sum()
    print(f"\nTotal P&L impact (n=1): {total:+,.2f} USD")
    print(f"Avg per trade:          {total/len(df_r):+.2f} USD")

    print(f"\nPer instrument (all MAX_HOLD exits):")
    for inst, grp in df_r.groupby("inst"):
        tick_val = grp["tick_val"].iloc[0]
        mean_abs = grp["drift_usd"].abs().mean()
        print(f"  {inst:4s}: n={len(grp):3d}  "
              f"mean drift={grp['drift_usd'].mean():+.2f}$  "
              f"|drift| avg={mean_abs:.2f}$  "
              f"total={grp['drift_usd'].sum():+,.2f}$  "
              f"(1 tick=${tick_val:.2f})")

    print(f"\nAbsolute |drift| vs 2-tick budget:")
    for inst, grp in df_r.groupby("inst"):
        tick_val = grp["tick_val"].iloc[0]
        mean_abs = grp["drift_usd"].abs().mean()
        budget   = 2 * tick_val
        pct      = mean_abs / budget * 100 if budget > 0 else 0
        flag     = "OK" if mean_abs <= budget else "EXCEEDS BUDGET"
        print(f"  {inst:4s}: |drift| avg={mean_abs:.2f}$  "
              f"vs 2-tick={budget:.2f}$  → {pct:.0f}%  [{flag}]")

    print(f"\nConclusion:")
    mean_drift = df_r["drift_usd"].mean()
    if abs(mean_drift) < 0.50:
        print(f"  mean drift {mean_drift:+.2f}$/trade ≈ 0 → fire time 09:31 không có bias")
        print(f"  09:31 OK for live (drift random, near-zero mean)")
    elif mean_drift < 0:
        print(f"  mean drift {mean_drift:+.2f}$/trade ADVERSE → live consistently worse than backtest")
        print(f"  → Consider firing 09:30 (khớp open) hoặc adjust baseline expectation")
    else:
        print(f"  mean drift {mean_drift:+.2f}$/trade FAVORABLE → live consistently better")
        print(f"  → Conservative OK (baseline understates)")


if __name__ == "__main__":
    main()
