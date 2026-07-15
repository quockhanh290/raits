"""
pyramid_wfo.py — GATE + max_units sweep cho pyramiding variant (IS-only, read-only)
==================================================================================
RESEARCH — TÁCH khỏi production/vault. Không đụng runner/paper/sealed files.

Copy cấu trúc fold + stitched aggregation của pooled_swing_wfo.py NHƯNG:
  - SWAP engine → futures._validated_core (causal) qua futures.swing_tf_pyramid
    (KHÔNG import root swing_tf_harness dirty).                       (design #1)
  - FREEZE ema=30 / mult=2.5 (không grid re-select) → isolate max_units. (design #5)
  - Sweep max_units {1,2,3,4}, giữ tổng risk cố định (w=1/max_units).   (design #2)
  - Aggregation = STITCHED single equity curve (pool tất cả OOS test-window trades),
    KHÔNG bootstrap, KHÔNG mean-of-folds — y hệt pooled_swing_wfo.       (design 2e)

IS-ONLY: vault_start = 2023-01-01 HARDCODE. Chỉ load bars < vault_start; labels
< vault_start. Vault 2023-2024 / 2025 KHÔNG BAO GIỜ chạm.

⚠️ GATE TRƯỚC SWEEP: max_units=1 phải == _validated_core.backtest_swing_tf
trade-for-trade EXACT (day/exit_day/direction/entry/exit/pnl). FAIL ≥1 trade → DỪNG.

    python pyramid_wfo.py            # dùng default: Rổ4, spy_daily_live.csv, 2-tick
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

VAULT_START   = "2023-01-01"      # HARDCODE — IS-only, không chạm vault
HMM_TRAIN_END = "2018-01-01"
TRAIN_MONTHS  = 18
TEST_MONTHS   = 6
EMA, MULT, MAXHOLD = 30, 2.5, 5   # frozen production params (design #5)
SWEEP = [1, 2, 3, 4]
SLIPPAGE_TICKS = 2.0              # convention 2-tick/side (INVARIANTS)


# ── metrics: trade-level WR/expectancy + stitched daily-equity Calmar/MaxDD ──────
def metrics(trade_rows):
    """trade_rows: list of dict có 'day' (entry day) + 'pnl'. Stitched daily equity."""
    if not trade_rows:
        return dict(n=0, net=0.0, calmar=0.0, pf=0.0, expect=0.0, maxdd=0.0, wr=0.0)
    df = pd.DataFrame(trade_rows)
    daily = df.groupby(pd.to_datetime(df["day"]))["pnl"].sum().sort_index()
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    win = daily[daily > 0].sum(); loss = -daily[daily < 0].sum()
    pnl = df["pnl"].to_numpy()
    return dict(n=len(df), net=float(pnl.sum()),
                calmar=float(ann / dd) if dd > 1e-9 else float("inf"),
                pf=float(win / loss) if loss > 1e-9 else float("inf"),
                expect=float(pnl.mean()),
                maxdd=dd, wr=float((pnl > 0).mean() * 100.0))


def fold_windows(last_day, train_end=HMM_TRAIN_END,
                 train_months=TRAIN_MONTHS, test_months=TEST_MONTHS):
    """Rolling 18mo train / 6mo test, step 6mo — CHÍNH XÁC pooled_swing_wfo.
    Trả list (test_lo, test_hi). Chỉ dùng test windows (param đã freeze → không cần train)."""
    start = pd.Timestamp(train_end)
    tl = pd.DateOffset(months=train_months); te = pd.DateOffset(months=test_months)
    tcur = start; wins = []
    while tcur + tl + te <= last_day + pd.DateOffset(days=1):
        te_lo = tcur + tl; te_hi = te_lo + te
        wins.append((te_lo, te_hi))
        tcur = tcur + te
    return wins


def run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",   default="data/cache/futures")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    a = ap.parse_args()

    from futures.swing_tf import load_basket, basket_labels, costs_for_basket
    from futures._validated_core import backtest_swing_tf
    from futures.swing_tf_pyramid import backtest_swing_tf_pyramid
    from futures.basket import BASKET

    print("=" * 74)
    print("PYRAMID WFO — GATE + max_units sweep (IS-only < %s, causal engine)" % VAULT_START)
    print("=" * 74)
    print("params: ema=%d mult=%.1f max_hold=%d | slippage=%.0f-tick | Rổ4 %s"
          % (EMA, MULT, MAXHOLD, SLIPPAGE_TICKS, list(BASKET)))

    # ── load IS-only data + labels (both < vault_start) ─────────────────────────
    dfs    = load_basket(a.data_dir, vault_start=VAULT_START)
    labels = basket_labels(a.regime_csv, hmm_train_end=HMM_TRAIN_END, vault_cut=VAULT_START)
    costs  = costs_for_basket(slippage_ticks=SLIPPAGE_TICKS)
    for name, df in dfs.items():
        print("  loaded %-4s %s bars  (< %s)" % (name, f"{len(df):,}", VAULT_START))

    # ════════════════════════════════════════════════════════════════════════
    # GATE — max_units=1 == _validated_core.backtest_swing_tf trade-for-trade
    # ════════════════════════════════════════════════════════════════════════
    print("\n" + "-" * 74)
    print("GATE: pyramid(max_units=1) vs _validated_core.backtest_swing_tf (EXACT)")
    print("-" * 74)
    CHK = ("day", "exit_day", "direction", "entry", "exit", "pnl")
    gate_ok = True
    for name, df in dfs.items():
        base = backtest_swing_tf(df, labels, costs[name], ema_period=EMA,
                                 chandelier_atr_mult=MULT, max_hold_days=MAXHOLD)
        pyr1 = backtest_swing_tf_pyramid(df, labels, costs[name], ema_period=EMA,
                                         chandelier_atr_mult=MULT, max_hold_days=MAXHOLD,
                                         max_units=1)
        mism = []
        if len(base) != len(pyr1):
            mism.append("COUNT base=%d pyr=%d" % (len(base), len(pyr1)))
        for i, (b, p) in enumerate(zip(base, pyr1)):
            diff = {k: (b[k], p[k]) for k in CHK if b[k] != p[k]}
            if diff:
                mism.append("trade#%d %s" % (i, diff))
        if mism:
            gate_ok = False
            print("  %-4s ✗ FAIL  (%d trades)" % (name, len(base)))
            for m in mism[:5]:
                print("        %s" % m)
        else:
            print("  %-4s ✓ PASS  %d trades exact" % (name, len(base)))

    if not gate_ok:
        print("\n[GATE FAIL] Anchor lệch → DỪNG. KHÔNG sweep trên nền lệch. Sửa variant.")
        return 1
    print("\n[GATE PASS] max_units=1 == baseline exact → tin nền, chạy sweep {2,3,4}.")

    # ════════════════════════════════════════════════════════════════════════
    # SWEEP — max_units {1,2,3,4}, stitched OOS aggregation
    # ════════════════════════════════════════════════════════════════════════
    all_days = sorted(pd.Timestamp(d) for d in labels.keys())
    wins = fold_windows(all_days[-1])
    print("\n" + "-" * 74)
    print("SWEEP: %d folds [train %dmo → test %dmo, step %dmo], OOS %s→%s"
          % (len(wins), TRAIN_MONTHS, TEST_MONTHS, TEST_MONTHS,
             wins[0][0].date(), wins[-1][1].date()))
    print("-" * 74)

    def in_oos(d):
        return any(lo <= d < hi for (lo, hi) in wins)

    results = {}          # max_units -> stitched metrics
    fold_cal = {}         # max_units -> [per-fold calmar]
    for mu in SWEEP:
        tbi = {name: backtest_swing_tf_pyramid(dfs[name], labels, costs[name],
                                               ema_period=EMA, chandelier_atr_mult=MULT,
                                               max_hold_days=MAXHOLD, max_units=mu)
               for name in dfs}
        all_tr = [dict(day=pd.Timestamp(r["day"]), pnl=r["pnl"], units=r.get("units", 1))
                  for name in tbi for r in tbi[name]]
        oos = [r for r in all_tr if in_oos(r["day"])]
        results[mu] = metrics(oos)
        results[mu]["avg_units"] = float(np.mean([r["units"] for r in oos])) if oos else 1.0
        cals = []
        for (lo, hi) in wins:
            fr = [r for r in all_tr if lo <= r["day"] < hi]
            fm = metrics(fr)
            if fm["n"] >= 5:
                cals.append(fm["calmar"])
        fold_cal[mu] = cals

    # ── report table ────────────────────────────────────────────────────────
    print("\nSTITCHED OOS (risk-normalized: w=1/max_units, so $ comparable across units)\n")
    hdr = ("max_units", "trades", "avg_u", "net$", "Calmar", "PF", "expect$", "MaxDD$", "WR%")
    print("  %-9s %7s %6s %10s %8s %6s %9s %9s %6s" % hdr)
    for mu in SWEEP:
        m = results[mu]
        print("  %-9d %7d %6.2f %10s %8.2f %6.2f %9.2f %9s %6.1f" % (
            mu, m["n"], m["avg_units"], f"{m['net']:,.0f}", m["calmar"],
            m["pf"], m["expect"], f"{m['maxdd']:,.0f}", m["wr"]))

    print("\nPer-fold Calmar (fold-to-fold variance → noise floor):")
    for mu in SWEEP:
        cals = fold_cal[mu]
        arr = np.array([c for c in cals if np.isfinite(c)])
        sd = float(arr.std()) if len(arr) > 1 else 0.0
        print("  max_units=%d  folds=%d  mean=%.2f  std=%.2f  vals=[%s]"
              % (mu, len(cals), (arr.mean() if len(arr) else 0.0), sd,
                 ", ".join(f"{c:.2f}" for c in cals)))

    # ── verdict: best + marginal/noise flag ───────────────────────────────────
    base_cal = results[1]["calmar"]
    best_mu = max(SWEEP, key=lambda u: results[u]["calmar"])
    best_cal = results[best_mu]["calmar"]
    gap = best_cal - base_cal
    noise = float(np.array([c for c in fold_cal[1] if np.isfinite(c)]).std()) if len(fold_cal[1]) > 1 else 0.0

    print("\n" + "-" * 74)
    print("VERDICT")
    print("-" * 74)
    print("  baseline max_units=1 : Calmar %.2f  net $%s" % (base_cal, f"{results[1]['net']:,.0f}"))
    print("  best      max_units=%d : Calmar %.2f  net $%s  (Δcalmar=%+.2f vs baseline)"
          % (best_mu, best_cal, f"{results[best_mu]['net']:,.0f}", gap))
    print("  fold-to-fold noise (std of baseline per-fold Calmar) : %.2f" % noise)
    if best_mu == 1:
        print("\n  → KHÔNG có max_units>1 nào cải thiện Calmar. Pyramiding KHÔNG add edge (IS).")
    elif gap < noise:
        print("\n  ⚠️ MARGINAL / NOISE: Δcalmar %+.2f < fold-to-fold std %.2f."
              % (gap, noise))
        print("     KHÔNG declare winner — gap nhỏ hơn fold variance = có thể là noise.")
    else:
        print("\n  → best = max_units=%d (Δcalmar %+.2f ≥ noise %.2f). Signal vượt noise floor."
              % (best_mu, gap, noise))
        print("     NHƯNG: đây IS-only. Confirmatory vault run trên best = follow-up RIÊNG (sau review).")
    print("\n  STOP sau report. KHÔNG chạm vault (IS-only, vault_start=%s hardcode)." % VAULT_START)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
