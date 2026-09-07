"""scratch/stocks_stage0_bootstrap_20260826.py — is the net distinguishable from zero?
READ-ONLY.

Trades are NOT independent draws. Several symbols routinely signal on the same session and
then share the next five days of market direction, so a trade-level bootstrap treats one
market move as many observations and reports a confidence it has not earned. The resampling
unit here is therefore the **entry session**: a day is drawn with replacement and all of its
trades come with it.

Centring the null, deliberately
-------------------------------
The p-value is computed against P&L **shifted to mean zero**, not against the raw sample. This
is the specific defect already found in this repository's own `cluster_bootstrap.py`, where an
uncentred null overstated significance by roughly 2x. The null has to be "this strategy has no
edge", and a resample of the raw winning sample is not that null — it is "this strategy has
exactly the edge it appears to have", which every sample passes.

What it can and cannot say
--------------------------
It bounds sampling noise on a fixed trade set. It says **nothing** about survivorship, about
the cost assumptions, or about whether the rule was chosen after seeing the data. A small
p-value on a survivorship-biased universe is a small p-value on a biased sample.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "_stocks_stage0_bootstrap.json"
N_BOOT = 20000
SEED = 20260826          # fixed and declared; a seed chosen after seeing a result is a choice


def cluster_bootstrap(df: pd.DataFrame, n_boot: int = N_BOOT, seed: int = SEED) -> dict:
    """Day-clustered bootstrap of total net P&L, with a mean-zero null."""
    g = df.groupby("entry_day")["net_pnl"]
    day_sum = g.sum().to_numpy(dtype=float)
    day_n = g.size().to_numpy(dtype=float)
    n_days = len(day_sum)
    if n_days < 20:
        return {"error": "only {} entry days; too few to resample".format(n_days)}

    obs_total = float(day_sum.sum())
    obs_mean_per_trade = float(df["net_pnl"].mean())
    rng = np.random.default_rng(seed)

    # --- confidence interval on the observed distribution -------------------------------
    idx = rng.integers(0, n_days, size=(n_boot, n_days))
    boot_total = day_sum[idx].sum(axis=1)
    ci = np.percentile(boot_total, [2.5, 50, 97.5])

    # --- the CENTRED null: same clustering, same day sizes, mean shifted to zero ---------
    # The shift is per TRADE, so a day carrying more trades carries more of the shift and the
    # cluster structure of the null matches the cluster structure of the sample.
    shift = obs_mean_per_trade
    null_day_sum = day_sum - shift * day_n
    assert abs(float((null_day_sum).sum())) < 1e-6 * max(abs(obs_total), 1.0), \
        "the centred null does not sum to zero; the shift was applied wrongly"
    boot_null = null_day_sum[idx].sum(axis=1)
    p_one_sided = float((boot_null >= obs_total).mean())

    return dict(
        n_trades=int(len(df)), n_entry_days=int(n_days),
        trades_per_day_mean=round(float(day_n.mean()), 2),
        trades_per_day_max=int(day_n.max()),
        observed_total=round(obs_total, 2),
        boot_ci95_low=round(float(ci[0]), 2), boot_median=round(float(ci[1]), 2),
        boot_ci95_high=round(float(ci[2]), 2),
        frac_boot_positive=round(float((boot_total > 0).mean()), 4),
        p_one_sided_vs_centred_null=round(p_one_sided, 4),
        n_boot=n_boot, seed=seed)


def main() -> int:
    led = HERE / "_stocks_stage0_ledger_B_causal_lag1_ema50.csv"
    if not led.exists():
        print("no primary ledger at", led)
        return 2
    d = pd.read_csv(led)
    d = d[d["status"] == "TAKEN"].copy()
    if d.empty:
        print("ledger has no taken trades")
        return 2

    rep: dict = {"ledger": str(led), "unit_of_resampling": "entry session (day cluster)",
                 "null": "trade P&L shifted to mean zero, same day clusters"}
    windows = {
        "full 2019-01-02..2022-12-30": d,
        "in-sample 2019-2020": d[d["entry_day"] <= "2020-12-31"],
        "out-of-sample 2021-2022": d[d["entry_day"] > "2020-12-31"],
    }
    print("=== day-clustered bootstrap, centred null ({} resamples, seed {}) ===".format(
        N_BOOT, SEED))
    for name, sub in windows.items():
        if sub.empty:
            continue
        r = cluster_bootstrap(sub)
        rep[name] = r
        if "error" in r:
            print("  {:32s} {}".format(name, r["error"]))
            continue
        print("  {:32s} n={:4d} trades on {:4d} days   net ${:>10,.0f}   "
              "95% CI [${:>9,.0f}, ${:>9,.0f}]   p={:.4f}".format(
                  name, r["n_trades"], r["n_entry_days"], r["observed_total"],
                  r["boot_ci95_low"], r["boot_ci95_high"],
                  r["p_one_sided_vs_centred_null"]))

    # A self-check that can go red: a deliberately zero-edge sample must NOT come out
    # significant. If it does, the null is mis-centred and every p-value above is worthless.
    rng = np.random.default_rng(1)
    fake = d.copy()
    fake["net_pnl"] = rng.normal(0.0, float(d["net_pnl"].std()), size=len(fake))
    chk = cluster_bootstrap(fake, n_boot=5000, seed=7)
    rep["self_check_zero_edge_sample"] = chk
    ok = chk.get("p_one_sided_vs_centred_null", 0) > 0.01
    print()
    print(("[PASS] " if ok else "[FAIL] ") +
          "SC_null_is_centred: a synthetic zero-edge sample gives p={} "
          "(must not be significant)".format(chk.get("p_one_sided_vs_centred_null")))

    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print("\nwrote", OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
