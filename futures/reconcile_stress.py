"""
futures/reconcile_stress.py — STRESS_MID entry_signal == adapter entry
=====================================================================
entry_signal (live path) is a hand re-extraction of the StressMidAdapter's entry
rule. This proves they make the IDENTICAL entry decision on real Stress days —
critical because the live signal sees only bars THROUGH 10:15, while the adapter
computes over the full day. They must agree on: whether to enter, the entry
price, the stop, and the target.

    python -m futures.reconcile_stress --data-dir data\\cache\\futures \\
        --regime-csv spy_daily.csv [--instrument MES]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--instrument", default="MES", help="MES/MNQ/MYM/M2K")
    a = ap.parse_args()

    from futures._validated_core import load_parquet, StressMidAdapter, resample_5m
    from futures.basket import BASKET, data_filename
    from futures.stress_mid import StressMidEngine
    from futures.swing_tf import costs_for_basket, basket_labels

    c = BASKET[a.instrument]
    df = load_parquet(str(Path(a.data_dir) / data_filename(c)))
    labels = basket_labels(a.regime_csv)
    cost = costs_for_basket()[a.instrument]
    eng = StressMidEngine()
    adapter = StressMidAdapter({
        "target_rr": eng.target_rr, "max_stop_pct": eng.max_stop_pct, "stop_pad": eng.stop_pad})

    print(f"\n{'='*68}\nSTRESS_MID reconcile | {a.instrument} | entry_signal (live) vs adapter\n{'='*68}")

    n_stress = n_both_enter = n_both_skip = n_mismatch = 0
    mismatches = []
    for day, g in df.groupby(df.index.normalize()):
        key = pd.Timestamp(day).tz_localize(None).normalize()
        if labels.get(key) != "Stress":
            continue
        n_stress += 1
        bars5 = resample_5m(g)

        # adapter: full-day run → did it enter? (a returned trade means it entered)
        adapter_trades = adapter.run_day(bars5, "Stress", cost)
        adapter_entered = len(adapter_trades) > 0

        # live: entry_signal sees only bars through 10:15
        through_1015 = bars5[bars5.index.time <= pd.Timestamp("10:15").time()]
        live = eng.entry_signal(through_1015, "Stress")
        live_entered = live is not None

        if adapter_entered and live_entered:
            n_both_enter += 1
            am = adapter_trades[0].meta
            # compare entry, stop, target (rounded)
            ok = (round(adapter_trades[0].entry, 2) == round(live["entry"], 2)
                  and round(am["stop"], 2) == round(live["stop"], 2)
                  and round(am["target"], 2) == round(live["target"], 2))
            if not ok:
                n_mismatch += 1
                mismatches.append((key.date(), "values",
                                   f"adapter e={adapter_trades[0].entry:.2f} s={am['stop']:.2f} t={am['target']:.2f}",
                                   f"live e={live['entry']:.2f} s={live['stop']:.2f} t={live['target']:.2f}"))
        elif not adapter_entered and not live_entered:
            n_both_skip += 1
        else:
            n_mismatch += 1
            mismatches.append((key.date(), "decision",
                               f"adapter={'ENTER' if adapter_entered else 'skip'}",
                               f"live={'ENTER' if live_entered else 'skip'}"))

    print(f"  Stress days: {n_stress}")
    print(f"  both ENTER (values match): {n_both_enter - sum(1 for m in mismatches if m[1]=='values')}")
    print(f"  both SKIP: {n_both_skip}")
    print(f"  mismatches: {n_mismatch}")
    for d, kind, av, lv in mismatches[:15]:
        print(f"    {d} [{kind}] {av} | {lv}")
    print("-"*68)
    ok = n_mismatch == 0
    print(f"VERDICT: [{'PASS' if ok else 'FAIL'}] "
          + ("entry_signal == adapter on all Stress days. Live STRESS_MID == backtest."
             if ok else f"{n_mismatch} divergence(s) — entry_signal needs fixing before live."))
    print("-"*68 + "\n")


if __name__ == "__main__":
    main()
