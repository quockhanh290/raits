"""
futures/simulate_maxhold_noise_maxdd.py — MaxDD impact của 1-phút execution noise
==================================================================================
Câu hỏi: std 23.86 $/trade của 1-phút drift (09:30→09:31) có mở rộng MaxDD thật không?
Mean ≈ 0 → P&L trung bình không đổi. Nhưng noise thêm variance → equity path nhấp nhô hơn
→ DD có thể sâu hơn, đặc biệt khi adverse drifts cluster.

Phương pháp: bootstrap Monte Carlo 2000 sims.
  - Với mỗi MAX_HOLD trade, có empirical drift observation (từ data thật).
  - Mỗi sim: resample drifts với replacement → thêm vào P&L → tính equity curve → MaxDD.
  - Kết quả: distribution of MaxDD dưới 1-phút execution noise.
  - So sánh với baseline MaxDD (không noise) → noise có material không?

Run:
    cd d:\\raits
    python futures/simulate_maxhold_noise_maxdd.py
    python futures/simulate_maxhold_noise_maxdd.py --n-sims 5000
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


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float(np.max(peak - equity))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir",       default="data/cache/futures/frozen_sim")
    ap.add_argument("--regime-csv",     default="spy_daily_live.csv")
    ap.add_argument("--hmm-fit-end",    default="2024-12-31")
    ap.add_argument("--end",            default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--account",        type=float, default=50_000.0)
    ap.add_argument("--n-sims",         type=int,   default=2000)
    ap.add_argument("--seed",           type=int,   default=42)
    a = ap.parse_args()

    rng      = np.random.default_rng(a.seed)
    data_dir = Path(a.data_dir)

    print(f"Loading parquets from {data_dir} ...")
    bench  = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, "2018-01-01", 3, a.hmm_fit_end)
    costs  = costs_for_basket(slippage_ticks=a.slippage_ticks)

    dfs = {}
    for n, c in BASKET.items():
        df = load_parquet(str(data_dir / data_filename(c)))
        if a.end:
            df = df[df.index <= pd.Timestamp(a.end).tz_localize(df.index.tz)]
        dfs[n] = df

    print("Running backtest ...")
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)

    # ── 1. Collect per-trade drift observations ───────────────────────────────
    # drift_per_trade[i] = signed $-drift for MAX_HOLD trade i (positive = favorable)
    mh_records = []   # (exit_day: Timestamp, backtest_pnl: float, drift: float|None)

    for inst, trades in swing.items():
        c  = BASKET[inst]
        df = dfs[inst]
        for t in trades:
            exit_day = pd.Timestamp(t["exit_day"])
            pnl      = float(t["pnl"])

            if t.get("reason") != "MAX_HOLD":
                # non-MAX_HOLD: drift = 0 (no 1-min lag)
                continue

            drift = None
            et = t.get("exit_time")
            if et is not None:
                ts_931 = et + pd.Timedelta(minutes=1)
                bar931 = df[df.index == ts_931]
                if not bar931.empty:
                    p930 = float(t["exit"])
                    p931 = float(bar931["open"].iloc[0])
                    if t["direction"] == "LONG":
                        drift = (p931 - p930) * c.point_value
                    else:
                        drift = (p930 - p931) * c.point_value

            mh_records.append(dict(exit_day=exit_day, pnl=pnl, drift=drift, inst=inst))

    # ── 2. Build baseline daily P&L from ALL trades ───────────────────────────
    daily_baseline: dict[pd.Timestamp, float] = {}
    for inst, trades in swing.items():
        for t in trades:
            d = pd.Timestamp(t["exit_day"])
            daily_baseline[d] = daily_baseline.get(d, 0.0) + float(t["pnl"])

    dates = sorted(daily_baseline.keys())
    pnl_base = np.array([daily_baseline[d] for d in dates])
    date_idx = {d: i for i, d in enumerate(dates)}

    equity_base  = a.account + np.cumsum(pnl_base)
    baseline_mdd = max_drawdown(equity_base)

    # ── 3. Prepare MC inputs ──────────────────────────────────────────────────
    # Only use records with measured drift (non-None)
    valid = [r for r in mh_records if r["drift"] is not None]
    missing = len(mh_records) - len(valid)

    drift_arr   = np.array([r["drift"] for r in valid])
    exit_idxs   = np.array([date_idx[r["exit_day"]] for r in valid])  # index into pnl_base

    if len(drift_arr) == 0:
        print("No MAX_HOLD drift observations — cannot simulate.")
        return

    print(f"\nBaseline MaxDD (n=1, Rổ 4, no noise): ${baseline_mdd:,.2f}")
    print(f"MAX_HOLD trades with drift data:       {len(valid)} (skipped {missing} — no 09:31 bar)")
    print(f"Drift distribution:  mean={drift_arr.mean():+.2f}$  std={drift_arr.std():.2f}$")
    print(f"Running {a.n_sims:,} bootstrap Monte Carlo sims ...")

    # ── 4. Monte Carlo ────────────────────────────────────────────────────────
    mc_mdds = np.empty(a.n_sims)
    for i in range(a.n_sims):
        sampled = rng.choice(drift_arr, size=len(drift_arr), replace=True)
        pnl_noised = pnl_base.copy()
        np.add.at(pnl_noised, exit_idxs, sampled)
        eq = a.account + np.cumsum(pnl_noised)
        mc_mdds[i] = max_drawdown(eq)

    p5, p25, p50, p75, p95 = np.percentile(mc_mdds, [5, 25, 50, 75, 95])

    # ── 5. Report ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"MaxDD distribution under 1-min execution noise")
    print(f"{'='*60}")
    print(f"  Baseline (no noise):  ${baseline_mdd:>8,.2f}")
    print(f"  MC P5  (best 5%):     ${p5:>8,.2f}  ({(p5 -baseline_mdd)/baseline_mdd*100:+5.1f}%)")
    print(f"  MC P25:               ${p25:>8,.2f}  ({(p25-baseline_mdd)/baseline_mdd*100:+5.1f}%)")
    print(f"  MC P50 (median):      ${p50:>8,.2f}  ({(p50-baseline_mdd)/baseline_mdd*100:+5.1f}%)")
    print(f"  MC P75:               ${p75:>8,.2f}  ({(p75-baseline_mdd)/baseline_mdd*100:+5.1f}%)")
    print(f"  MC P95 (worst 5%):    ${p95:>8,.2f}  ({(p95-baseline_mdd)/baseline_mdd*100:+5.1f}%)")
    print(f"  MC max (worst):       ${mc_mdds.max():>8,.2f}  ({(mc_mdds.max()-baseline_mdd)/baseline_mdd*100:+5.1f}%)")

    # Sizer impact
    print(f"\nSizer: does noise push n_contracts down? (target 10% DD = ${a.account*0.10:,.0f})")
    target_dd  = a.account * 0.10
    n_base     = max(1, int(target_dd / baseline_mdd))
    n_p95      = max(1, int(target_dd / p95))
    n_worst    = max(1, int(target_dd / mc_mdds.max()))
    print(f"  baseline DD=${baseline_mdd:,.0f} → n={n_base}")
    print(f"  P95      DD=${p95:,.0f} → n={n_p95}")
    print(f"  worst    DD=${mc_mdds.max():,.0f} → n={n_worst}")
    if n_base == n_p95:
        print(f"  → n_contracts STABLE (n={n_base}) through P95 noise scenario")
    else:
        print(f"  → n_contracts DROPS {n_base}→{n_p95} at P95 — review DD budget")

    pct_p95 = (p95 - baseline_mdd) / baseline_mdd * 100
    print(f"\nConclusion:")
    if pct_p95 < 10:
        print(f"  P95 noise inflates MaxDD by {pct_p95:.1f}% → IMMATERIAL")
        print(f"  Baseline DD budget remains valid; no adjustment needed.")
    elif pct_p95 < 25:
        print(f"  P95 noise inflates MaxDD by {pct_p95:.1f}% → MODERATE")
        print(f"  Live DD may exceed backtest by ~{pct_p95:.0f}% in bad-noise scenarios.")
        print(f"  Consider noting this in INVARIANTS as live execution headroom.")
    else:
        print(f"  P95 noise inflates MaxDD by {pct_p95:.1f}% → MATERIAL")
        print(f"  Live execution noise can materially deepen DD — add buffer or reduce n.")


if __name__ == "__main__":
    main()
