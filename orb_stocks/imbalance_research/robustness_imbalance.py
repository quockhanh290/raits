"""
Opening Imbalance Research — STEP 3b: robustness / concentration checks.
(EXPERIMENTAL harness, orb_stocks/imbalance_research/)  — RESEARCH ONLY.

Step 3 returned GO on the primary cell. This project has a documented failure
mode of GO verdicts that turn out to rest on a handful of rows (PE_SHORT: top-3
trades = 58% of P&L, jackknife k=3 -> p=0.055; GF_SHORT: N=12 degenerate). A GO
that has not survived a concentration check is not a GO yet.

Four checks, all on the PRIMARY cell (window='late', outcome='pct_return'),
all using the CENTRED within-date permutation from bootstrap_imbalance.py:

  1. Leave-one-TICKER-out  — 6 tickers carry >=10 of the 144 events. If
     dropping any single ticker breaks the result, the effect is that ticker's.
  2. Leave-one-DATE-out    — the deciding test runs on 23 mixed dates. If one
     date carries it, it is a single-day artifact.
  3. Winsorised outcome    — recompute at +-2 sd. pct_return has fat tails
     (the catalyst study had to drop |pct|>25% corrupt bars); a mean-difference
     driven by two extreme rows is not a filter you can trade.
  4. Year split            — 2021 (n=33 events) vs 2022 (n=122). An effect
     present in only one year is a regime artifact, which is exactly what the
     Stress-heavy 2022 population invites.

Run:
    cd d:\\raits
    python orb_stocks\\imbalance_research\\robustness_imbalance.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
FEATURES = os.path.join(HERE, "imbalance_features.parquet")
OUTCOME = os.path.join(REPO, "raits", "data", "cache", "news",
                       "orb_event_outcome.parquet")

N_BOOT = 10_000
SEED = 49
MIN_TRADES = 30
W, M = "late", "pct_return"


def within_date_p(df: pd.DataFrame, metric: str = M, seed: int = SEED):
    """Centred within-date conditional permutation (see bootstrap_imbalance.py)."""
    A = df[df["aligned"]]
    B = df[~df["aligned"]]
    if len(A) < 3 or len(B) < 3:
        return None
    mixed = sorted(set(A["date"]) & set(B["date"]))
    if not mixed:
        return None
    obs = A[metric].mean() - B[metric].mean()
    fixedA = A[~A["date"].isin(mixed)][metric].sum()
    fixedB = B[~B["date"].isin(mixed)][metric].sum()
    nA, nB = len(A), len(B)
    blocks = [(df[df["date"] == d][metric].values,
               int(df[df["date"] == d]["aligned"].sum())) for d in mixed]

    rng = np.random.default_rng(seed)
    draws = np.empty(N_BOOT)
    for i in range(N_BOOT):
        sA, sB = fixedA, fixedB
        for vals, kA in blocks:
            idx = rng.permutation(len(vals))
            sA += vals[idx[:kA]].sum()
            sB += vals[idx[kA:]].sum()
        draws[i] = sA / nA - sB / nB
    c = draws.mean()
    p = ((np.abs(draws - c) >= abs(obs - c)).sum() + 1) / (N_BOOT + 1)
    return dict(p=p, obs=obs, n=len(df), n_mixed=len(mixed),
                nA=nA, nB=nB)


def load() -> pd.DataFrame:
    feat = pd.read_parquet(FEATURES)
    outc = pd.read_parquet(OUTCOME)
    outc = outc[~outc["outcome_suspect"]].copy()
    feat["date"] = feat["date"].astype(str)
    outc["date"] = outc["date"].astype(str)
    df = feat.merge(outc[["ticker", "date", "pct_return", "R_multiple"]],
                    on=["ticker", "date"], how="inner")
    df = df[(df[f"{W}_n_classified"] >= MIN_TRADES)
            & df[f"{W}_imb_ratio_vol"].notna()
            & df[M].notna()].copy()
    df["aligned"] = df[f"{W}_imb_ratio_vol"] < 0
    return df[df[f"{W}_imb_ratio_vol"] != 0].copy()


def main() -> None:
    df = load()
    base = within_date_p(df)
    print("=" * 78)
    print("STEP 3b — ROBUSTNESS / CONCENTRATION  (primary cell only)")
    print(f"cell: window='{W}' outcome='{M}'   RESEARCH ONLY")
    print("=" * 78)
    print(f"  baseline: n={base['n']} (A={base['nA']} B={base['nB']}) "
          f"mixed_dates={base['n_mixed']}")
    print(f"  baseline: diff={base['obs'] * 100:+.3f}%  within-date p={base['p']:.4f}\n")

    # ── 1. leave-one-ticker-out ───────────────────────────────────────────
    print("-" * 78)
    print("1. LEAVE-ONE-TICKER-OUT  (tickers with >=4 events)")
    print("-" * 78)
    counts = df["ticker"].value_counts()
    big = counts[counts >= 4].index.tolist()
    print(f"   {'dropped':<10}{'n_ev':>5}{'n_left':>8}{'diff':>10}{'p':>9}  flag")
    worst_p, worst_tk = base["p"], None
    for tk in big:
        sub = df[df["ticker"] != tk]
        r = within_date_p(sub)
        if r is None:
            print(f"   {tk:<10}{counts[tk]:>5}{'':>8}   degenerate after drop")
            continue
        flag = ""
        if r["p"] >= 0.05:
            flag = "  <== breaks p<0.05"
        if r["p"] > worst_p:
            worst_p, worst_tk = r["p"], tk
        print(f"   {tk:<10}{counts[tk]:>5}{r['n']:>8}"
              f"{r['obs'] * 100:>+9.3f}%{r['p']:>9.4f}{flag}")
    print(f"\n   worst case: dropping {worst_tk} -> p={worst_p:.4f}")

    # ── 2. leave-one-date-out (mixed dates only — they carry the test) ────
    print("\n" + "-" * 78)
    print("2. LEAVE-ONE-DATE-OUT  (mixed dates only — these carry the test)")
    print("-" * 78)
    A = df[df["aligned"]]; B = df[~df["aligned"]]
    mixed = sorted(set(A["date"]) & set(B["date"]))
    rows = []
    for d in mixed:
        r = within_date_p(df[df["date"] != d])
        if r:
            rows.append((d, int((df["date"] == d).sum()), r["obs"], r["p"]))
    rows.sort(key=lambda x: -x[3])
    print(f"   {'dropped date':<14}{'n_ev':>5}{'diff':>10}{'p':>9}  (worst 6 shown)")
    for d, n, o, p in rows[:6]:
        flag = "  <== breaks p<0.05" if p >= 0.05 else ""
        print(f"   {d:<14}{n:>5}{o * 100:>+9.3f}%{p:>9.4f}{flag}")
    n_break = sum(1 for _, _, _, p in rows if p >= 0.05)
    print(f"\n   dates whose removal breaks p<0.05: {n_break}/{len(rows)}")

    # ── 3. winsorised outcome ─────────────────────────────────────────────
    print("\n" + "-" * 78)
    print("3. WINSORISED OUTCOME (tail sensitivity)")
    print("-" * 78)
    for k in (3.0, 2.0):
        w = df.copy()
        mu, sd = w[M].mean(), w[M].std()
        lo, hi = mu - k * sd, mu + k * sd
        n_clip = int(((w[M] < lo) | (w[M] > hi)).sum())
        w[M] = w[M].clip(lo, hi)
        r = within_date_p(w)
        flag = "  <== breaks p<0.05" if r["p"] >= 0.05 else ""
        print(f"   +-{k:.0f} sd (clipped {n_clip:2} rows): "
              f"diff={r['obs'] * 100:+.3f}%  p={r['p']:.4f}{flag}")

    # ── 4. year split ─────────────────────────────────────────────────────
    print("\n" + "-" * 78)
    print("4. YEAR SPLIT (is this one regime only?)")
    print("-" * 78)
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for yr, g in df.groupby("year"):
        r = within_date_p(g)
        if r is None:
            print(f"   {yr}: n={len(g)} — too few / no mixed dates to test")
            continue
        a = g[g["aligned"]][M]; b = g[~g["aligned"]][M]
        print(f"   {yr}: n={r['n']:3} (A={r['nA']:3} B={r['nB']:2}) "
              f"mixed_dates={r['n_mixed']:2}  "
              f"A_mean={a.mean() * 100:+.3f}% B_mean={b.mean() * 100:+.3f}%  "
              f"diff={r['obs'] * 100:+.3f}%  p={r['p']:.4f}")

    print("\n" + "=" * 78)
    print("READ: a GO that survives 1-4 is a GO. A GO that breaks on any single")
    print("ticker or single date is a concentration artifact and must be")
    print("downgraded to monitor regardless of the headline p-value.")
    print("=" * 78)


if __name__ == "__main__":
    main()
