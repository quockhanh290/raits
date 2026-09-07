from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.harness import ARM_LIVE, Cfg, _cache, _correct, _make_sig


def spy_features(spy_csv: str) -> pd.DataFrame:
    close = pd.read_csv(spy_csv, parse_dates=["date"]).set_index("date")["close"].sort_index()
    ret = close.pct_change()
    prev = close.shift(1)
    out = pd.DataFrame(index=close.index)
    out["spy_ret5"] = prev / close.shift(6) - 1.0
    out["spy_ret20"] = prev / close.shift(21) - 1.0
    out["spy_ret60"] = prev / close.shift(61) - 1.0
    out["spy_rv20"] = ret.rolling(20).std().shift(1) * np.sqrt(252)
    out["spy_rv60"] = ret.rolling(60).std().shift(1) * np.sqrt(252)
    out["spy_dd63"] = prev / close.rolling(63).max().shift(1) - 1.0
    out["spy_dd126"] = prev / close.rolling(126).max().shift(1) - 1.0
    out["spy_above_sma50"] = prev > close.rolling(50).mean().shift(1)
    out["spy_above_sma200"] = prev > close.rolling(200).mean().shift(1)
    out["spy_sma50_gt_200"] = close.rolling(50).mean().shift(1) > close.rolling(200).mean().shift(1)
    return out


def trade_rows(args) -> pd.DataFrame:
    from futures.basket import BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import run_loop

    labels = basket_labels(args.regime_csv)
    costs = costs_for_basket(slippage_ticks=2.0)
    dfs = load_basket(args.data_dir)
    cfg = Cfg(fix_fill=True, arm_hours=ARM_LIVE, ratchet=False, roska4_only=False,
              ema=args.ema, stop_basis=args.stop_basis)
    rows = []
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
        trades, _ = run_loop(
            df, labels, costs[inst], strat=strat, ema_period=args.ema, mult=2.5,
            max_hold_days=5, cache=cache, same_day_stop=False, stop_slip_ticks=0.0,
            sig_cache=sig, stop_active_hour=ARM_LIVE, ratchet=False,
        )
        trades, _, _ = _correct(trades, df, BASKET[inst].point_value, ARM_LIVE)
        for t in trades:
            day = pd.Timestamp(t["day"]).normalize()
            rows.append({
                "day": day,
                "year": day.year,
                "inst": inst,
                "direction": t["direction"],
                "pnl": float(t["pnl"]),
                "reason": t["reason"],
                "hold_days": int(t["hold_days"]),
            })
    out = pd.DataFrame(rows)
    feat = spy_features(args.regime_csv)
    out = out.join(feat, on="day")
    out["month"] = out["day"].dt.month
    out["dow"] = out["day"].dt.dayofweek
    return out


def metric(df: pd.DataFrame) -> tuple[int, float, float, float]:
    if df.empty:
        return 0, 0.0, 0.0, 0.0
    wins = df.loc[df.pnl > 0, "pnl"].sum()
    losses = -df.loc[df.pnl < 0, "pnl"].sum()
    pf = float(wins / losses) if losses > 0 else float("inf")
    return len(df), float(df.pnl.sum()), pf, float(df.pnl.mean())


def print_group(title: str, df: pd.DataFrame, groups: list[tuple[str, pd.Series]]) -> None:
    print()
    print(title)
    print(f"  {'group':<24} {'n':>5} {'pnl':>10} {'pf':>6} {'exp':>8} {'2021n':>6} {'2021pnl':>10}")
    for name, mask in groups:
        sub = df[mask.fillna(False)]
        n, pnl, pf, exp = metric(sub)
        sub21 = sub[sub.year == 2021]
        n21, pnl21, _, _ = metric(sub21)
        print(f"  {name:<24} {n:>5} ${pnl:>9,.0f} {pf:>6.2f} ${exp:>7.2f} {n21:>6} ${pnl21:>9,.0f}")


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

    df = trade_rows(args)
    out_path = Path("scratch/candidate_features.csv")
    df.to_csv(out_path, index=False)

    print(f"wrote {out_path} rows={len(df)}")
    for scope, sub in [("all", df), ("2021", df[df.year == 2021]), ("not2021", df[df.year != 2021])]:
        n, pnl, pf, exp = metric(sub)
        print(f"{scope:<8} n={n:4d} pnl=${pnl:>9,.0f} pf={pf:>5.2f} exp=${exp:>7.2f}")

    print()
    print("feature medians: 2021 vs not2021")
    for c in ["spy_ret5", "spy_ret20", "spy_ret60", "spy_rv20", "spy_rv60", "spy_dd63", "spy_dd126"]:
        print(f"  {c:<12} 2021={df[df.year==2021][c].median():>8.3%}  other={df[df.year!=2021][c].median():>8.3%}")

    print_group("by direction", df, [
        ("LONG", df.direction == "LONG"),
        ("SHORT", df.direction == "SHORT"),
    ])
    print_group("by instrument", df, [(inst, df.inst == inst) for inst in sorted(df.inst.unique())])
    print_group("market filters", df, [
        ("rv20 < 15%", df.spy_rv20 < 0.15),
        ("rv20 15-25%", (df.spy_rv20 >= 0.15) & (df.spy_rv20 < 0.25)),
        ("rv20 >= 25%", df.spy_rv20 >= 0.25),
        ("dd63 > -3%", df.spy_dd63 > -0.03),
        ("dd63 -8..-3%", (df.spy_dd63 <= -0.03) & (df.spy_dd63 > -0.08)),
        ("dd63 <= -8%", df.spy_dd63 <= -0.08),
        ("ret20 > 0", df.spy_ret20 > 0),
        ("ret20 <= 0", df.spy_ret20 <= 0),
        ("above sma50", df.spy_above_sma50 == True),
        ("below sma50", df.spy_above_sma50 == False),
        ("above sma200", df.spy_above_sma200 == True),
        ("below sma200", df.spy_above_sma200 == False),
    ])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
