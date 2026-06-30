"""
futures/reconcile_gd0.py — GĐ0 reconcile: futures engine == validated harness
=============================================================================
Proves SwingTFEngine.backtest produces trade-for-trade IDENTICAL output to
calling backtest_swing_tf directly (the code that produced the official WFO/vault
numbers). With approach (a) this is true by construction; the test documents it
and will catch any drift when the logic is later internalized (refactor stage b).

Run from repo root:
    python -m futures.reconcile_gd0 --data-dir data\\cache\\futures --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--vault-start", default="2023-01-01")
    a = ap.parse_args()

    from futures.swing_tf import SwingTFEngine, costs_for_basket, load_basket, basket_labels
    from futures.basket import BASKET, SWING_TF_PARAM
    from futures._validated_core import backtest_swing_tf

    print(f"\n{'='*66}\nGĐ0 RECONCILE | futures.SwingTFEngine vs validated harness\n{'='*66}")
    dfs = load_basket(a.data_dir, vault_start=a.vault_start)
    labels = basket_labels(a.regime_csv, vault_cut=a.vault_start)
    costs = costs_for_basket()
    eng = SwingTFEngine()

    all_ok = True
    for name in BASKET:
        # engine path
        via_engine = eng.backtest(dfs[name], labels, costs[name])
        # direct harness path (same params from basket)
        via_harness = backtest_swing_tf(
            dfs[name], labels, costs[name],
            ema_period=SWING_TF_PARAM["ema_period"],
            chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
            max_hold_days=SWING_TF_PARAM["max_hold_days"])

        same_n = len(via_engine) == len(via_harness)
        # field-by-field on entry/exit/pnl
        mismatch = 0
        for te, th in zip(via_engine, via_harness):
            if (te["day"] != th["day"] or te["exit_day"] != th["exit_day"]
                    or round(te["pnl"], 2) != round(th["pnl"], 2)
                    or te["direction"] != th["direction"]):
                mismatch += 1
        ok = same_n and mismatch == 0
        all_ok &= ok
        ne = sum(t["pnl"] for t in via_engine); nh = sum(t["pnl"] for t in via_harness)
        print(f"  {name:<4} engine {len(via_engine):>4}t (${ne:>8,.0f}) | "
              f"harness {len(via_harness):>4}t (${nh:>8,.0f}) | "
              f"{'MATCH' if ok else f'DIFF n={not same_n} mism={mismatch}'}")

    print("-"*66)
    print(f"VERDICT: [{'PASS' if all_ok else 'FAIL'}] "
          + ("futures engine == validated harness, trade-for-trade. GĐ0 done."
             if all_ok else "drift detected — investigate before proceeding."))
    print("-"*66 + "\n")


if __name__ == "__main__":
    main()
