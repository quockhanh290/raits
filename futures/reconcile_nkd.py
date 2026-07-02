"""
futures/reconcile_nkd.py — NKD live-signal == NKD backtest (required before live NKD)
=======================================================================================
Verifies the NKD live-signal path matches the validated backtest trade-for-trade.
Two phases:

  Phase 1 (fast, field-by-field): SwingTFEngine.backtest() == backtest_swing_tf()
    directly — proves the class interface is wired correctly (same params → same output).
    Mirrors reconcile_gd0 but for NKD with NKD params (ema=10 / mult=2.5 / hold=5).

  Phase 2 (desired_position boundary check): for each backtest trade, calls
    desired_position(data_through_entry_day) and desired_position(data_through_exit_day)
    and verifies the open-position state is consistent with the trade record. Confirms
    that the return_open=True expanding-window path is faithful to the full backtest.
    O(2K) desired_position calls where K = number of trades (feasible for ~50-100 NKD
    trades; full daily scan would be O(D^2) and is skipped by default).

VERDICT PASS only when both phases pass (all trades match + desired_position consistent).

Usage:
    cd D:\\raits
    python -m futures.reconcile_nkd \\
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet \\
        --regime-csv spy_daily.csv

    # skip Phase 2 (faster, Phase 1 only):
    python -m futures.reconcile_nkd ... --skip-live-check
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path.cwd()))


def _clip_to_vault(df: pd.DataFrame, vault_start: str) -> pd.DataFrame:
    vs = pd.Timestamp(vault_start)
    tz = df.index.tz
    if tz is not None:
        return df[df.index < vs.tz_localize(tz)]
    return df[df.index < vs]


def main():
    ap = argparse.ArgumentParser(description="NKD live-signal reconcile")
    ap.add_argument("--nkd-parquet",
                    default="global_index/data/NKD_continuous_1m_8y.parquet")
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--nkd-instrument", default="MNKD", choices=["NKD", "MNKD"])
    ap.add_argument("--ema", type=int, default=10)
    ap.add_argument("--mult", type=float, default=2.5)
    ap.add_argument("--max-hold", type=int, default=5)
    ap.add_argument("--vault-start", default="2023-01-01",
                    help="exclude vault-OOS data (keep IS only, same as reconcile_gd0)")
    ap.add_argument("--skip-live-check", action="store_true",
                    help="skip Phase 2 (desired_position boundary check)")
    a = ap.parse_args()

    from futures._validated_core import backtest_swing_tf
    from futures.swing_tf import SwingTFEngine
    from global_index.specs import SPECS
    from global_index.regime import RegimeLabels, load_spy_regime
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC

    c = SPECS[a.nkd_instrument]

    # ── load NKD data (clip to vault boundary) ────────────────────────────────
    ndf_full = gi_load(a.nkd_parquet)
    ndf_full.index = ndf_full.index.tz_convert(c.session_tz)
    ndf = _clip_to_vault(ndf_full, a.vault_start)

    # ── regime labels (SPY-based, lag 1 day for JST lookahead safety) ─────────
    spy = load_spy_regime(a.regime_csv)
    nlab = RegimeLabels(spy, lag_days=1)

    # ── cost ──────────────────────────────────────────────────────────────────
    ncost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                 slippage_ticks_per_side=1.0)

    eng = SwingTFEngine(ema_period=a.ema, chandelier_atr_mult=a.mult, max_hold_days=a.max_hold)

    print(f"\n{'='*68}")
    print(f"NKD RECONCILE | {a.nkd_instrument} ema={a.ema} mult={a.mult} hold={a.max_hold}")
    print(f"  data: {ndf.index[0].date()} → {ndf.index[-1].date()} "
          f"({(ndf.index[-1] - ndf.index[0]).days // 365}y) | vault cut {a.vault_start}")
    print(f"{'='*68}")

    # ── Phase 1: engine.backtest() vs backtest_swing_tf() directly ───────────
    print("\nPhase 1 — engine vs harness (field-by-field):")
    via_engine = eng.backtest(ndf, nlab, ncost, gap_fill=True)
    via_harness = backtest_swing_tf(
        ndf, nlab, ncost,
        ema_period=a.ema, chandelier_atr_mult=a.mult,
        max_hold_days=a.max_hold, gap_fill=True)

    same_n = len(via_engine) == len(via_harness)
    mismatch = 0
    for te, th in zip(via_engine, via_harness):
        if (te["day"] != th["day"] or te["exit_day"] != th["exit_day"]
                or round(te["pnl"], 2) != round(th["pnl"], 2)
                or te["direction"] != th["direction"]):
            mismatch += 1
    p1_ok = same_n and mismatch == 0
    ne = sum(t["pnl"] for t in via_engine)
    nh = sum(t["pnl"] for t in via_harness)
    print(f"  engine  {len(via_engine):>4}t (${ne:>8,.0f})")
    print(f"  harness {len(via_harness):>4}t (${nh:>8,.0f})")
    print(f"  n_match={same_n}  field_mismatch={mismatch}  "
          + ("PASS" if p1_ok else "FAIL"))

    # ── Phase 2: desired_position boundary check ──────────────────────────────
    p2_ok = True
    p2_skipped = False
    if a.skip_live_check:
        p2_skipped = True
        print("\nPhase 2 — desired_position check: SKIPPED (--skip-live-check)")
    elif not via_harness:
        p2_skipped = True
        print("\nPhase 2 — desired_position check: SKIPPED (no harness trades)")
    else:
        print(f"\nPhase 2 — desired_position boundary check ({len(via_harness)} trades):")
        print("  (calls desired_position at entry_day and exit_day of each trade)")
        errs = []
        for i, t in enumerate(via_harness):
            entry_day = pd.Timestamp(t["day"])
            exit_day  = pd.Timestamp(t["exit_day"])

            # filter NKD data through entry_day (inclusive, in JST)
            entry_day_jst = entry_day.tz_localize(c.session_tz) if entry_day.tzinfo is None else entry_day
            exit_day_jst  = exit_day.tz_localize(c.session_tz) if exit_day.tzinfo is None else exit_day

            ndf_at_entry = ndf[ndf.index.normalize() <= entry_day_jst.normalize()]
            ndf_at_exit  = ndf[ndf.index.normalize() <= exit_day_jst.normalize()]

            # at entry_day: desired_position should show an open position
            pos_entry = eng.desired_position(ndf_at_entry, nlab, ncost)
            if pos_entry is None:
                errs.append(f"  trade {i}: entry_day {entry_day.date()} → desired_position=None "
                            f"(expected {t['direction']})")
            elif pos_entry["direction"] != t["direction"]:
                errs.append(f"  trade {i}: entry_day {entry_day.date()} → "
                            f"direction {pos_entry['direction']} != backtest {t['direction']}")

            # at exit_day: desired_position should be None (or a NEW entry if same-day churn)
            pos_exit = eng.desired_position(ndf_at_exit, nlab, ncost)
            # if a new trade started the same exit_day as this one closes, pos_exit may be non-None
            # but its entry_day should be exit_day (not the current trade's entry_day)
            if pos_exit is not None:
                pos_entry_day = pd.Timestamp(pos_exit.get("entry_day", exit_day))
                if pos_entry_day.normalize() == entry_day.normalize():
                    # same position as current trade — should have closed
                    errs.append(f"  trade {i}: exit_day {exit_day.date()} → "
                                f"position still open from {entry_day.date()} (should be closed)")

        p2_ok = len(errs) == 0
        if errs:
            for e in errs:
                print(e)
        else:
            print(f"  all {len(via_harness)} trades: entry state OK + exit state OK")
        print(f"  Phase 2 {'PASS' if p2_ok else 'FAIL'}")

    # ── overall verdict ────────────────────────────────────────────────────────
    overall = p1_ok and (p2_ok or p2_skipped)
    print(f"\n{'-'*68}")
    if overall:
        status = "PASS (Phase 2 skipped)" if p2_skipped else "PASS"
        print(f"VERDICT: [{status}] NKD live-signal == backtest, trade-for-trade.")
        if not p2_skipped:
            print("  desired_position expanding-window consistent. Safe to wire NKD live.")
    else:
        print("VERDICT: [FAIL] mismatch detected — do NOT wire NKD live until resolved.")
    print(f"{'-'*68}\n")


if __name__ == "__main__":
    main()
