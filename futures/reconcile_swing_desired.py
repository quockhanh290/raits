"""
futures/reconcile_swing_desired.py
===================================
Verify SwingTFEngine.desired_position() expanding-window == backtest_basket
for all 4 Rổ-4 instruments (MES / MNQ / MYM / M2K).

Closes the last live-signal gap: STRESS (reconcile_stress) and NKD (reconcile_nkd)
already verified. Swing TF machinery is identical to NKD (same backtest_swing_tf,
different ema_period=30 and 4 independent per-instrument calls).

Phase 1 (fast): backtest per instrument == backtest_swing_tf harness, trade-for-trade.
  Mirrors reconcile_gd0 exactly. Re-runs to confirm no drift.

Phase 2 (desired_position boundary check): for a sample of backtest trades per
  instrument, calls desired_position(data_through_entry_day) and
  desired_position(data_through_exit_day), verifies state is consistent.
  Default: 20 samples/instrument (80 total × 2 calls = 160 desired_position calls).
  --max-samples 0 to run all trades (slow, mirrors reconcile_nkd Phase 2 fully).

Usage (from d:\\raits):
    python -m futures.reconcile_swing_desired ^
        --data-dir data\\cache\\futures ^
        --regime-csv spy_daily.csv

    # full Phase 2 (slower — all trades):
    python -m futures.reconcile_swing_desired ... --max-samples 0

    # skip Phase 2:
    python -m futures.reconcile_swing_desired ... --skip-live-check
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path.cwd()))

ET = "America/New_York"


def main():
    ap = argparse.ArgumentParser(description="Swing TF desired_position reconcile")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--vault-start", default="2023-01-01",
                    help="keep IS data only (matches reconcile_gd0 default)")
    ap.add_argument("--max-samples", type=int, default=20,
                    help="max trades to boundary-check per instrument (0=all, default=20)")
    ap.add_argument("--skip-live-check", action="store_true",
                    help="skip Phase 2 (desired_position boundary check)")
    a = ap.parse_args()

    from futures.swing_tf import SwingTFEngine, costs_for_basket, load_basket, basket_labels
    from futures.basket import BASKET, SWING_TF_PARAM
    from futures._validated_core import backtest_swing_tf

    dfs    = load_basket(a.data_dir, vault_start=a.vault_start)
    labels = basket_labels(a.regime_csv, vault_cut=a.vault_start)
    costs  = costs_for_basket()
    eng    = SwingTFEngine()

    print(f"\n{'='*70}")
    print(f"SWING DESIRED_POSITION RECONCILE | "
          f"ema={eng.ema_period} mult={eng.chandelier_atr_mult} hold={eng.max_hold_days}")
    print(f"  instruments: {list(BASKET.keys())}  vault_cut={a.vault_start}")
    print(f"{'='*70}")

    # ── Phase 1: backtest per instrument == backtest_swing_tf harness ──────────
    print("\nPhase 1 — backtest (trade-for-trade, mirrors reconcile_gd0):")
    p1_ok = True
    backtest_by_inst: dict = {}
    for name in BASKET:
        via_eng = eng.backtest(dfs[name], labels, costs[name])
        via_har = backtest_swing_tf(
            dfs[name], labels, costs[name],
            ema_period=SWING_TF_PARAM["ema_period"],
            chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
            max_hold_days=SWING_TF_PARAM["max_hold_days"])
        same_n    = len(via_eng) == len(via_har)
        mismatch  = sum(
            1 for te, th in zip(via_eng, via_har)
            if (te["day"] != th["day"] or te["exit_day"] != th["exit_day"]
                or round(te["pnl"], 2) != round(th["pnl"], 2)
                or te["direction"] != th["direction"]))
        ok = same_n and mismatch == 0; p1_ok &= ok
        pnl = sum(t["pnl"] for t in via_eng)
        backtest_by_inst[name] = via_eng
        print(f"  {name:<4} {len(via_eng):>4}t  ${pnl:>8,.0f}  "
              f"{'MATCH' if ok else f'DIFF n_same={same_n} mismatch={mismatch}'}")
    print(f"  Phase 1 {'PASS' if p1_ok else 'FAIL'}")

    # ── Phase 2: desired_position boundary check ───────────────────────────────
    p2_ok   = True
    p2_skip = a.skip_live_check
    if p2_skip:
        print("\nPhase 2 — desired_position: SKIPPED (--skip-live-check)")
    else:
        ns = a.max_samples
        label = "all" if ns == 0 else f"max {ns}/inst"
        print(f"\nPhase 2 — desired_position boundary check ({label} samples):")
        print("  entry_day: desired_position should return this trade")
        print("  exit_day:  desired_position should NOT return this trade")

        for name in BASKET:
            df    = dfs[name]
            costs_n = costs[name]
            trades  = backtest_by_inst[name]
            if not trades:
                print(f"  {name:<4}  0 trades — skip"); continue

            # select systematic sample spread evenly across trade list
            if ns == 0 or ns >= len(trades):
                sample = trades
            else:
                step   = max(1, len(trades) // ns)
                sample = [trades[i] for i in range(0, len(trades), step)][:ns]

            errs: list = []
            for idx, t in enumerate(sample):
                entry_day = pd.Timestamp(t["day"])           # tz-naive midnight
                exit_day  = pd.Timestamp(t["exit_day"])

                # Slice df through entry_day (inclusive): all ET bars whose
                # tz-aware date == entry_day.date (i.e., index.normalize() <= entry_day_et)
                entry_et  = entry_day.tz_localize(ET)
                exit_et   = exit_day.tz_localize(ET)
                df_entry  = df[df.index.normalize() <= entry_et]
                df_exit   = df[df.index.normalize() <= exit_et]

                # check at entry_day: must return this trade
                pos_e = eng.desired_position(df_entry, labels, costs_n)
                if pos_e is None:
                    errs.append(f"    trade {idx} entry {entry_day.date()} "
                                f"→ desired_position=None (expected {t['direction']})")
                else:
                    got_dir  = pos_e["direction"]
                    got_ed   = pd.Timestamp(pos_e["entry_day"]).normalize().date()
                    got_entr = round(float(pos_e["entry"]), 2)
                    exp_entr = round(float(t["entry"]), 2)
                    if got_dir != t["direction"]:
                        errs.append(f"    trade {idx} entry {entry_day.date()} "
                                    f"→ direction {got_dir} != {t['direction']}")
                    elif got_ed != entry_day.date():
                        errs.append(f"    trade {idx} entry {entry_day.date()} "
                                    f"→ entry_day got {got_ed} expected {entry_day.date()}")
                    elif got_entr != exp_entr:
                        errs.append(f"    trade {idx} entry {entry_day.date()} "
                                    f"→ entry px {got_entr} != {exp_entr}")

                # check at exit_day: must NOT still show this trade open
                pos_x = eng.desired_position(df_exit, labels, costs_n)
                if pos_x is not None:
                    x_ed = pd.Timestamp(pos_x.get("entry_day", exit_day)).normalize().date()
                    if x_ed == entry_day.date():
                        errs.append(f"    trade {idx} exit {exit_day.date()} "
                                    f"→ position still open from {entry_day.date()} "
                                    f"(should be closed)")

            status = "PASS" if not errs else "FAIL"
            n_checked = len(sample)
            print(f"  {name:<4}  {n_checked}/{len(trades)} trades checked  {status}")
            for e in errs:
                print(e)
            if errs:
                p2_ok = False

    # ── overall verdict ────────────────────────────────────────────────────────
    overall = p1_ok and (p2_ok or p2_skip)
    print(f"\n{'-'*70}")
    if overall:
        tag = "PASS (Phase 2 skipped)" if p2_skip else "PASS"
        print(f"VERDICT: [{tag}] Swing desired_position == backtest, all 4 instruments.")
        if not p2_skip:
            print("  desired_position expanding-window consistent. Safe to wire swing live.")
    else:
        print("VERDICT: [FAIL] mismatch detected — see above. Do NOT wire swing live.")
    print(f"{'-'*70}\n")


if __name__ == "__main__":
    main()
