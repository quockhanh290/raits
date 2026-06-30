"""
gate5_vault.py — RAITS × MES Gate 5: one-shot fresh-vault test
==============================================================
STANDALONE, READ-ONLY. Runs the FROZEN param (chosen by Gate 4) ONCE on the
reserved vault slice (everything >= --vault-start, which Gate 4 never touched),
and reports GO / NO-GO against pre-registered criteria.

VAULT DISCIPLINE: run this exactly ONCE per strategy. The vault is a one-way
door — if you iterate on it, it is burned and no longer out-of-sample.

Pre-registered GO criteria (lock before running):
    Calmar ≥ 1.0   AND   PF > 1.0   AND   expectancy > 0   (after futures cost)

Reuses gate2_edge_harness; engine untouched.

Usage
-----
    python gate5_vault.py --parquet ES_7y.parquet --strategy trend_follow \\
        --hmm-train-end 2020-01-01 --vault-start 2024-01-01 \\
        --params "ema_period=20,chandelier_atr_mult=2.5"

    python gate5_vault.py --parquet ES_7y.parquet --strategy stress_mid \\
        --hmm-train-end 2020-01-01 --vault-start 2024-01-01 \\
        --params "target_rr=2.0,max_stop_pct=0.015"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))

PASS = {"calmar": 1.0, "pf": 1.0, "expect": 0.0}


def parse_params(s: str) -> dict:
    out = {}
    for kv in (s or "").split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=")
        k = k.strip(); v = v.strip()
        out[k] = int(v) if v.isdigit() else float(v)
    return out


def metrics(trades) -> dict:
    if not trades:
        return {"n": 0, "pnl": 0.0, "calmar": 0.0, "sharpe": 0.0, "pf": 0.0,
                "expect": 0.0, "wr": 0.0, "maxdd": 0.0}
    df = pd.DataFrame({"day": [pd.Timestamp(t.day).normalize() for t in trades],
                       "pnl": [t.pnl for t in trades]})
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum(); peak = eq.cummax(); max_dd = float((peak - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    ann = daily.sum() / span
    calmar = (ann / max_dd) if max_dd > 1e-9 else float("inf")
    sharpe = (daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 1e-9 else 0.0
    wins = daily[daily > 0].sum(); losses = abs(daily[daily < 0].sum())
    pf = (wins / losses) if losses > 1e-9 else float("inf")
    pnls = np.array([t.pnl for t in trades])
    return {"n": len(trades), "pnl": float(daily.sum()), "calmar": float(calmar),
            "sharpe": float(sharpe), "pf": float(pf), "expect": float(pnls.mean()),
            "wr": float((pnls > 0).mean() * 100), "maxdd": max_dd}


def main():
    ap = argparse.ArgumentParser(description="Gate 5: one-shot vault (read-only).")
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--strategy", choices=["trend_follow", "stress_mid"], required=True)
    ap.add_argument("--hmm-train-end", default="2020-01-01")
    ap.add_argument("--hmm-fit-end", default=None,
                    help="fit HMM on a fixed diverse window (incl. stress) — must match Gate 4")
    ap.add_argument("--vault-start", required=True, help="vault = everything >= this date")
    ap.add_argument("--params", default="", help='e.g. "ema_period=20,chandelier_atr_mult=2.5"')
    ap.add_argument("--hmm-components", type=int, default=3)
    ap.add_argument("--regime-csv", default=None, help="SPY daily CSV (date,close) for instrument-agnostic regime")
    ap.add_argument("--point-value", type=float, default=5.0)
    ap.add_argument("--i-understand-one-shot", action="store_true",
                    help="acknowledge the vault is run ONCE and burned after")
    a = ap.parse_args()

    import gate2_edge_harness as G

    if not a.i_understand_one_shot:
        print("\nVAULT IS A ONE-WAY DOOR. Running this burns the vault as OOS evidence.\n"
              "Re-run with --i-understand-one-shot once you are sure the param is frozen.\n")
        return

    params = parse_params(a.params)
    print(f"\n{'='*68}\nGATE 5 VAULT (one-shot) | {a.strategy} | params={params}\n{'='*68}")
    df = G.load_parquet(a.parquet)
    daily = G.benchmark_daily(a.regime_csv) if a.regime_csv else G.daily_close_series(df)
    labels = G.label_regimes(daily, a.hmm_train_end, a.hmm_components, a.hmm_fit_end)
    cost = G.FuturesCost(point_value=a.point_value)

    vstart = pd.Timestamp(a.vault_start)
    adapter = G.ADAPTERS[a.strategy](params)
    trades = []
    for day, g in df.groupby(df.index.normalize()):
        key = pd.Timestamp(day).tz_localize(None).normalize()
        if key < vstart:
            continue                                  # vault slice only
        if labels.get(key) not in adapter.allowed:
            continue
        trades.extend(adapter.run_day(G.resample_5m(g), labels[key], cost))

    m = metrics(trades)
    print(f"Vault window: {vstart.date()} → {df.index[-1].date()}")
    print(f"Trades: {m['n']} | Net ${m['pnl']:,.0f} | WR {m['wr']:.0f}% | MaxDD ${m['maxdd']:,.0f}")
    print(f"Calmar {m['calmar']:.2f} | Sharpe {m['sharpe']:.2f} | PF {m['pf']:.2f} | "
          f"expectancy ${m['expect']:.2f}")

    print("\nPre-registered GO criteria:")
    c1 = m["calmar"] >= PASS["calmar"]; c2 = m["pf"] > PASS["pf"]; c3 = m["expect"] > PASS["expect"]
    print(f"  Calmar ≥ {PASS['calmar']}      {'PASS' if c1 else 'FAIL'}  ({m['calmar']:.2f})")
    print(f"  PF > {PASS['pf']}          {'PASS' if c2 else 'FAIL'}  ({m['pf']:.2f})")
    print(f"  expectancy > 0    {'PASS' if c3 else 'FAIL'}  (${m['expect']:.2f})")

    print("\n" + "-" * 68)
    if c1 and c2 and c3:
        print("VERDICT: [GO] vault confirms the edge OOS on untouched data.")
        print("         → proceed to position sizing + paper (sim) on the real futures broker.")
    else:
        print("VERDICT: [NO-GO] vault did not confirm. Log the lesson; do NOT re-run on this slice.")
    print("-" * 68 + "\n")


if __name__ == "__main__":
    main()
