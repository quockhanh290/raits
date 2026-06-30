"""
pooled_vault.py — one-shot VAULT for the STRESS_MID basket (frozen params)
=========================================================================
Single-instrument vault gave 16 trades (Calmar noise). Pooling the correlated
index basket gives ~5x trades in the vault window → metrics with actual
statistical weight. This is a ONE-WAY DOOR: it burns the chosen vault window
as OOS evidence.

HONEST SCOPE (read before trusting the verdict):
  The only OOS-able window that CONTAINS stress is 2022 (2023-24 had zero stress
  days). 2022 is also the episode that carried ~82% of the basket's P&L. So a GO
  here confirms the frozen strategy works OOS in a 2022-type slow bear with an
  adequate sample — it does NOT prove robustness to other stress types (2020 was
  breakeven). Treat GO as "the conditional edge is real and measured", not "a
  steady edge".

Params are FROZEN (not tuned on the vault). HMM is fit on data strictly before
the vault (default fit-end 2021-12-31, includes 2018-Q4 + 2020 COVID so it learns
stress). Regime is SPY-based.

    python pooled_vault.py --instruments "ES=...:5,NQ=...:2,YM=...:0.5,RTY=...:5,NKD=...:5" \
        --regime-csv spy_daily.csv --vault-start 2022-01-01 --hmm-fit-end 2021-12-31 \
        --params "target_rr=2.0,max_stop_pct=0.015" --i-understand-one-shot
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path.cwd()))

EPISODES = [("2022-bear", "2022-01-01", "2022-12-31"),
            ("2023+",     "2023-01-01", "2030-12-31")]

def metrics(pnls: np.ndarray) -> dict:
    n = len(pnls)
    if n == 0:
        return dict(n=0, pnl=0, wr=0, pf=0, expect=0, maxdd=0, calmar=0, sharpe=0)
    eq = np.cumsum(pnls); dd = float(np.maximum.accumulate(eq).max() - eq.min() if n else 0)
    dd = float((np.maximum.accumulate(eq) - eq).max())
    w = pnls[pnls > 0].sum(); l = -pnls[pnls < 0].sum()
    ann = pnls.mean() * 252
    return dict(n=n, pnl=float(pnls.sum()), wr=float((pnls > 0).mean()*100),
                pf=float(w/l) if l > 0 else np.inf, expect=float(pnls.mean()),
                maxdd=dd, calmar=float(ann/dd) if dd > 0 else np.inf,
                sharpe=float(pnls.mean()/pnls.std()*np.sqrt(252)) if pnls.std() > 0 else np.nan)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instruments", required=True, help='NAME=parquet:pointvalue,...')
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--strategy", default="stress_mid")
    ap.add_argument("--params", default="target_rr=2.0,max_stop_pct=0.015")
    ap.add_argument("--vault-start", default="2022-01-01")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end", default="2021-12-31")
    ap.add_argument("--hmm-components", type=int, default=3)
    ap.add_argument("--i-understand-one-shot", action="store_true")
    a = ap.parse_args()

    if not a.i_understand_one_shot:
        print("\nVAULT IS A ONE-WAY DOOR. Re-run with --i-understand-one-shot once the\n"
              "params are frozen and you accept this burns the window as OOS evidence.\n")
        return

    import gate2_edge_harness as G
    def parse_params(s):
        out = {}
        for kv in s.split(","):
            k, v = kv.split("="); out[k.strip()] = float(v)
        return out
    params = parse_params(a.params)
    vstart = pd.Timestamp(a.vault_start)
    daily = G.benchmark_daily(a.regime_csv)
    labels = G.label_regimes(daily, a.hmm_train_end, a.hmm_components, a.hmm_fit_end)

    print(f"\n{'='*70}\nPOOLED VAULT (one-shot) | {a.strategy} | params={params}\n{'='*70}")
    print(f"Vault start {vstart.date()} | HMM fit ≤ {a.hmm_fit_end} | regime SPY\n")

    per_inst = {}
    all_rows = []
    for spec in a.instruments.split(","):
        name, rest = spec.split("=")
        pq, pv = rest.rsplit(":", 1)
        name, pv = name.strip(), float(pv)
        df = G.load_parquet(pq.strip())
        cost = G.FuturesCost(point_value=pv)
        adapter = G.ADAPTERS[a.strategy](params)
        tr = []
        for day, g in df.groupby(df.index.normalize()):
            key = pd.Timestamp(day).tz_localize(None).normalize()
            if key < vstart or labels.get(key) not in adapter.allowed:
                continue
            for t in adapter.run_day(G.resample_5m(g), labels[key], cost):
                tr.append((key, t.pnl)); all_rows.append((key, t.pnl))
        pnls = np.array([p for _, p in tr])
        per_inst[name] = metrics(pnls)
        print(f"  {name:<5} {per_inst[name]['n']:>4} trades  "
              f"net ${per_inst[name]['pnl']:>8,.0f}  PF {per_inst[name]['pf']:.2f}")

    # pooled by day (basket = sum across instruments per day)
    if not all_rows:
        print("\n[NO-GO] zero trades in vault window — no stress labelled. Nothing to judge.")
        return
    pooled = pd.DataFrame(all_rows, columns=["day", "pnl"])
    daily_basket = pooled.groupby("day")["pnl"].sum().sort_index()
    m = metrics(daily_basket.to_numpy())

    print(f"\nPOOLED BASKET (daily, 1 micro each)")
    print(f"  trade-days {m['n']} | net ${m['pnl']:,.0f} | WR {m['wr']:.0f}% | "
          f"PF {m['pf']:.2f} | MaxDD ${m['maxdd']:,.0f} | Calmar {m['calmar']:.2f} | Sharpe {m['sharpe']:.2f}")

    # per-episode within the vault
    print("\nWITHIN-VAULT EPISODES:")
    for ep, s, e in EPISODES:
        sub = daily_basket[(daily_basket.index >= pd.Timestamp(s)) & (daily_basket.index <= pd.Timestamp(e))]
        if len(sub):
            print(f"  {ep:<10} {len(sub):>4} days  net ${sub.sum():>9,.0f}")
        else:
            print(f"  {ep:<10}    0 days  (no stress labelled)")

    PASS = dict(calmar=1.0, pf=1.0, expect=0.0)
    c1, c2, c3 = m["calmar"] >= PASS["calmar"], m["pf"] > PASS["pf"], m["expect"] > PASS["expect"]
    print("\nPre-registered GO criteria:")
    print(f"  Calmar ≥ 1.0   {'PASS' if c1 else 'FAIL'} ({m['calmar']:.2f})")
    print(f"  PF > 1.0       {'PASS' if c2 else 'FAIL'} ({m['pf']:.2f})")
    print(f"  expectancy > 0 {'PASS' if c3 else 'FAIL'} (${m['expect']:.2f})")
    go = c1 and c2 and c3
    print("\n" + "-"*70)
    print(f"VERDICT: [{'GO' if go else 'NO-GO'}] " +
          ("pooled basket confirms the conditional edge OOS with adequate sample."
           if go else "vault did not confirm."))
    print("  SCOPE: this validates a 2022-type bear only; 2020-type stress was breakeven.")
    print("  Treat as a CONDITIONAL stress sleeve, not a steady engine.")
    print("-"*70 + "\n")

if __name__ == "__main__":
    main()
