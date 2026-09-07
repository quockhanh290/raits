from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.harness import ARM_LIVE, Cfg, _cache, _correct, _make_sig


def stats(rows):
    if not rows:
        return 0, 0.0, 0.0
    pnl = [float(r["pnl"]) for r in rows]
    wins = sum(x for x in pnl if x > 0)
    loss = -sum(x for x in pnl if x < 0)
    return len(rows), sum(pnl), (wins / loss if loss else float("inf"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--stop-basis", type=float, default=2.0)
    ap.add_argument("--allowed", nargs="+", default=["Normal"])
    args = ap.parse_args()

    from futures.basket import BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import run_loop

    labels = basket_labels(args.regime_csv)
    costs = costs_for_basket(slippage_ticks=2.0)
    dfs = load_basket(args.data_dir)
    cfg = Cfg(fix_fill=True, arm_hours=ARM_LIVE, ratchet=False, roska4_only=False,
              ema=args.ema, stop_basis=args.stop_basis)

    all_rows = []
    for inst, df in dfs.items():
        start = pd.Timestamp(args.start).tz_localize(df.index.tz)
        end = pd.Timestamp(args.end).tz_localize(df.index.tz)
        df = df[(df.index >= start) & (df.index <= end)]
        cache, datr = _cache(df)
        scfg = dict(TrendFollowStrategy().config)
        scfg["allowed_regimes"] = list(args.allowed)
        scfg["ema_period"] = args.ema
        scfg["chandelier_atr_mult"] = 2.5
        strat = TrendFollowStrategy(scfg)
        sig = _make_sig(cache, datr, labels, strat, args.ema, set(args.allowed), cfg, True)
        tr, _ = run_loop(
            df,
            labels,
            costs[inst],
            strat=strat,
            ema_period=args.ema,
            mult=2.5,
            max_hold_days=5,
            cache=cache,
            same_day_stop=False,
            stop_slip_ticks=0.0,
            sig_cache=sig,
            stop_active_hour=ARM_LIVE,
            ratchet=False,
        )
        tr, _, _ = _correct(tr, df, BASKET[inst].point_value, ARM_LIVE)
        for t in tr:
            t["inst"] = inst
            all_rows.append(t)

    print(f"trades={len(all_rows)} allowed={','.join(args.allowed)} ema={args.ema} stop_basis={args.stop_basis}")
    print()
    print("by_inst:")
    for inst in sorted({r["inst"] for r in all_rows}):
        n, pnl, pf = stats([r for r in all_rows if r["inst"] == inst])
        print(f"  {inst}: n={n:4d} pnl=${pnl:>9,.0f} pf={pf:>5.2f}")
    print()
    print("by_year:")
    years = sorted({pd.Timestamp(r["day"]).year for r in all_rows})
    for y in years:
        rs = [r for r in all_rows if pd.Timestamp(r["day"]).year == y]
        n, pnl, pf = stats(rs)
        print(f"  {y}: n={n:4d} pnl=${pnl:>9,.0f} pf={pf:>5.2f}")
    print()
    print("by_year_inst:")
    for y in years:
        line = [str(y)]
        for inst in sorted({r["inst"] for r in all_rows}):
            _, pnl, _ = stats([r for r in all_rows if pd.Timestamp(r["day"]).year == y and r["inst"] == inst])
            line.append(f"{inst}=${pnl:,.0f}")
        print("  " + "  ".join(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
