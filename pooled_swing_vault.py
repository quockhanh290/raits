"""
pooled_swing_vault.py — one-shot VAULT for the swing-TF BASKET (frozen param)
============================================================================
Final OOS gate for the swing-TF engine. Everything before was < 2023; this
tests the FROZEN param (chosen by pooled WFO) on the untouched 2023-2024 slice.
ONE-WAY DOOR: burns 2023-2024 as OOS evidence.

Unlike STRESS_MID (which had 0 trades in calm 2023-24), swing TF trades year-
round → the vault has real sample. HMM is fit ≤ --hmm-fit-end (never sees the
vault); regime SPY-based; param FROZEN (not tuned on vault). Basket = 1 micro
each, daily P&L summed. Reports per-YEAR breakdown (a continuous strategy should
be spread across years, not carried by one).

    python pooled_swing_vault.py --instruments "ES=...:5,NQ=...:2,YM=...:0.5,RTY=...:5" \
        --regime-csv spy_daily.csv --vault-start 2023-01-01 --hmm-fit-end 2024-12-31 \
        --ema-period 30 --chandelier-atr-mult 2.5 --i-understand-one-shot
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path.cwd()))


def _isfloat(s):
    try:
        float(s); return True
    except ValueError:
        return False


def parse_instrument(spec):
    """NAME=path:point_value[:tick] → (name, path, point_value, tick)."""
    name, rest = spec.split("=", 1)
    toks = rest.split(":")
    nums = []
    while toks and _isfloat(toks[-1]):
        nums.insert(0, float(toks.pop()))
    return name.strip(), ":".join(toks).strip(), nums[0], (nums[1] if len(nums) > 1 else 0.25)


def metrics(daily: pd.Series) -> dict:
    if daily.empty:
        return dict(n=0, pnl=0, pf=0, calmar=0, sharpe=0, expect=0, maxdd=0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    w = daily[daily > 0].sum(); l = -daily[daily < 0].sum()
    return dict(n=int((daily != 0).sum()), pnl=float(daily.sum()),
                pf=float(w/l) if l > 1e-9 else float("inf"),
                calmar=float(ann/dd) if dd > 1e-9 else float("inf"),
                sharpe=float(daily.mean()/daily.std()*np.sqrt(252)) if daily.std() > 1e-9 else 0.0,
                expect=float(daily[daily != 0].mean()) if (daily != 0).any() else 0.0, maxdd=dd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--vault-start", default="2023-01-01")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    ap.add_argument("--hmm-components", type=int, default=3)
    ap.add_argument("--ema-period", type=int, default=30)
    ap.add_argument("--chandelier-atr-mult", type=float, default=2.5)
    ap.add_argument("--max-hold-days", type=int, default=5)
    ap.add_argument("--slippage-ticks", type=float, default=1.0,
                    help="slippage per side in ticks (raise to stress-test fills)")
    ap.add_argument("--no-gap-fill", action="store_true",
                    help="disable gap-through modeling (optimistic baseline)")
    ap.add_argument("--i-understand-one-shot", action="store_true")
    a = ap.parse_args()
    if not a.i_understand_one_shot:
        print("\nONE-WAY DOOR. Freeze the param, then re-run with --i-understand-one-shot.\n")
        return

    import gate2_edge_harness as G
    from swing_tf_harness import backtest_swing_tf

    vstart = pd.Timestamp(a.vault_start)
    daily_bench = G.benchmark_daily(a.regime_csv)
    labels = G.label_regimes(daily_bench, a.hmm_train_end, a.hmm_components, a.hmm_fit_end)

    print(f"\n{'='*70}\nPOOLED SWING-TF VAULT (one-shot) | ema={a.ema_period} mult={a.chandelier_atr_mult}\n{'='*70}")
    print(f"Vault {vstart.date()}+ | HMM fit ≤ {a.hmm_fit_end} | regime SPY | FROZEN param\n")

    vault_days = {d for d in labels if d >= vstart}
    per_inst, all_rows = {}, []
    for spec in a.instruments.split(","):
        name, pq, pv, tick = parse_instrument(spec)
        df = G.load_parquet(pq)
        cost = G.FuturesCost(point_value=pv, tick=tick, slippage_ticks_per_side=a.slippage_ticks)
        trs = backtest_swing_tf(df, labels, cost, ema_period=a.ema_period,
                                chandelier_atr_mult=a.chandelier_atr_mult,
                                max_hold_days=a.max_hold_days, entry_days=vault_days,
                                gap_fill=not a.no_gap_fill)
        s = pd.Series({pd.Timestamp(r["day"]): 0 for r in trs})
        d = pd.DataFrame([(pd.Timestamp(r["day"]), r["pnl"]) for r in trs],
                         columns=["day", "pnl"]) if trs else pd.DataFrame(columns=["day", "pnl"])
        per_inst[name] = d
        for r in trs:
            all_rows.append((pd.Timestamp(r["day"]), r["pnl"]))
        net = d["pnl"].sum() if len(d) else 0.0
        print(f"  {name:<5} {len(d):>4} trades  net ${net:>9,.0f}")

    if not all_rows:
        print("\n[NO-GO] no trades in vault."); return
    basket = pd.DataFrame(all_rows, columns=["day", "pnl"]).groupby("day")["pnl"].sum().sort_index()
    m = metrics(basket)

    print(f"\nPOOLED BASKET (1 micro each)")
    print(f"  trade-days {m['n']} | net ${m['pnl']:,.0f} | PF {m['pf']:.2f} | "
          f"MaxDD ${m['maxdd']:,.0f} | Calmar {m['calmar']:.2f} | Sharpe {m['sharpe']:.2f}")

    print("\nPER-YEAR (continuous strategy → should be spread, not carried by one):")
    for yr, g in basket.groupby(basket.index.year):
        print(f"  {yr}  {int((g!=0).sum()):>4} days  net ${g.sum():>9,.0f}")

    c1, c2, c3 = m["calmar"] >= 1.0, m["pf"] > 1.0, m["expect"] > 0
    print("\nPre-registered GO criteria:")
    print(f"  Calmar ≥ 1.0   {'PASS' if c1 else 'FAIL'} ({m['calmar']:.2f})")
    print(f"  PF > 1.0       {'PASS' if c2 else 'FAIL'} ({m['pf']:.2f})")
    print(f"  expectancy > 0 {'PASS' if c3 else 'FAIL'} (${m['expect']:.2f})")
    go = c1 and c2 and c3
    print("\n" + "-"*70)
    print(f"VERDICT: [{'GO' if go else 'NO-GO'}] " +
          ("swing-TF basket confirmed OOS on untouched 2023-2024 → engine is deployable."
           if go else "vault did not confirm."))
    print("-"*70 + "\n")


if __name__ == "__main__":
    main()
