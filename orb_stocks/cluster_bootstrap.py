"""
cluster_bootstrap.py — Step 3 rigor check: date-block (cluster) bootstrap
(EXPERIMENTAL harness, orb_stocks/)  — RESEARCH ONLY.

Same-date events are correlated (a Stress-regime selloff hits many stocks the same
day), so event-level resampling treats them as independent and overstates
confidence. This re-runs the idiosyncratic-vs-non comparison resampling by DATE
(cluster), not by event, and reports how much the honest number moved.

Reads orb_event_outcome.parquet (corrected is_idiosyncratic, pct_return,
outcome_suspect) — no sim import needed.
"""

from __future__ import annotations

import os
import sys
import collections

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "raits", "data", "cache", "news", "orb_event_outcome.parquet")
N_BOOT = 10_000
SEED = 42


def dist_by_date(dates):
    """{events-on-a-date: how many such dates}."""
    per = collections.Counter(dates)
    return dict(sorted(collections.Counter(per.values()).items()))


def main():
    df = pd.read_parquet(OUT)
    df = df[~df["outcome_suspect"]].copy()          # 147 clean
    df["date"] = df["date"].astype(str)
    A = df[df["is_idiosyncratic"]]
    B = df[~df["is_idiosyncratic"]]

    print("=" * 78)
    print("STEP 3 RIGOR — date-block (cluster) bootstrap  (RESEARCH ONLY)")
    print(f"clean events: {len(df)}  | A idiosyncratic={len(A)}  B non-idio={len(B)}")
    print("=" * 78)

    # ── 1. Clustering for BOTH groups ─────────────────────────────────────
    print("\n1. DATE-CLUSTERING (events-per-date -> #dates)")
    for lab, g in [("A idiosyncratic", A), ("B non-idiosyncratic", B), ("ALL", df)]:
        d = g["date"].values
        per = collections.Counter(d)
        top = collections.Counter(per).most_common()
        print(f"  {lab:<20}: {len(g)} events on {g['date'].nunique()} dates | "
              f"max/date={max(per.values())} | events-per-date dist={dist_by_date(d)}")

    # mixed dates (>=1 A and >=1 B on the same date)
    a_dates = set(A["date"]); b_dates = set(B["date"])
    mixed = sorted(a_dates & b_dates)
    n_mixed_events = len(df[df["date"].isin(mixed)])
    print(f"\n  MIXED dates (both A and B present): {len(mixed)} dates, "
          f"{n_mixed_events} events")
    for d in mixed:
        na = len(A[A['date'] == d]); nb = len(B[B['date'] == d])
        print(f"    {d}: A={na} B={nb}")

    # ── Per-date aggregates for the block bootstrap (vectorized) ──────────
    dates = sorted(df["date"].unique())
    di = {d: i for i, d in enumerate(dates)}
    nd = len(dates)
    aSum = np.zeros(nd); aCnt = np.zeros(nd)
    bSum = np.zeros(nd); bCnt = np.zeros(nd)
    for _, r in df.iterrows():
        i = di[r["date"]]
        if r["is_idiosyncratic"]:
            aSum[i] += r["pct_return"]; aCnt[i] += 1
        else:
            bSum[i] += r["pct_return"]; bCnt[i] += 1

    a = A["pct_return"].values; b = B["pct_return"].values
    obs = a.mean() - b.mean()

    # ── EVENT-level bootstrap (the original / naive) for comparison ───────
    rng = np.random.default_rng(SEED)
    ev = np.empty(N_BOOT)
    for i in range(N_BOOT):
        ev[i] = rng.choice(a, len(a), replace=True).mean() - \
                rng.choice(b, len(b), replace=True).mean()
    ev_lo, ev_hi = np.percentile(ev, [2.5, 97.5])

    # ── DATE-BLOCK bootstrap: resample dates, take ALL their events ───────
    rng = np.random.default_rng(SEED)
    blk = np.full(N_BOOT, np.nan)
    for i in range(N_BOOT):
        draw = rng.integers(0, nd, nd)      # resample dates with replacement
        nA = aCnt[draw].sum(); nB = bCnt[draw].sum()
        if nA == 0 or nB == 0:
            continue
        blk[i] = aSum[draw].sum() / nA - bSum[draw].sum() / nB
    blk = blk[~np.isnan(blk)]
    blk_lo, blk_hi = np.percentile(blk, [2.5, 97.5])
    blk_p_gt0 = (blk > 0).mean()
    # two-sided cluster bootstrap p (fraction on the null side, doubled)
    blk_p2 = 2 * min((blk <= 0).mean(), (blk >= 0).mean())

    # ── Cluster permutation: shuffle A/B labels WITHIN each mixed date ────
    # Pure-group dates contribute fixed values; only mixed dates have label
    # freedom. Denominators (group counts) are fixed, so only numerators move.
    fixedA = A[~A["date"].isin(mixed)]["pct_return"].sum()
    fixedB = B[~B["date"].isin(mixed)]["pct_return"].sum()
    nA_tot = len(a); nB_tot = len(b)
    mixed_blocks = []
    for d in mixed:
        r = df[df["date"] == d]["pct_return"].values
        kA = int((df[df["date"] == d]["is_idiosyncratic"]).sum())
        mixed_blocks.append((r, kA))
    rng = np.random.default_rng(SEED + 1)
    if mixed_blocks:
        cnt = 0
        for _ in range(N_BOOT):
            sumA = fixedA; sumB = fixedB
            for r, kA in mixed_blocks:
                idx = rng.permutation(len(r))
                sumA += r[idx[:kA]].sum(); sumB += r[idx[kA:]].sum()
            d_ = sumA / nA_tot - sumB / nB_tot
            if abs(d_) >= abs(obs):
                cnt += 1
        perm_p = (cnt + 1) / (N_BOOT + 1)
    else:
        perm_p = None

    # ── Report ────────────────────────────────────────────────────────────
    print(f"\n{'=' * 78}")
    print("2/3. BOOTSTRAP COMPARISON  (outcome = pct_return, SHORT; no sizing)")
    print(f"{'=' * 78}")
    print(f"  observed mean diff (A-B): {obs*100:+.3f}%\n")
    print(f"  {'method':<28}{'95% CI of diff':<28}{'P(A>B)':<9}")
    print(f"  {'EVENT-level (naive)':<28}"
          f"[{ev_lo*100:+.3f}%, {ev_hi*100:+.3f}%]{'':<6}{(ev>0).mean():.3f}")
    print(f"  {'DATE-BLOCK (cluster)':<28}"
          f"[{blk_lo*100:+.3f}%, {blk_hi*100:+.3f}%]{'':<6}{blk_p_gt0:.3f}")
    print(f"\n  DATE-BLOCK two-sided cluster-bootstrap p : {blk_p2:.4f}")
    if perm_p is not None:
        print(f"  within-date stratified permutation p     : {perm_p:.4f}  "
              f"(uses {len(mixed)} mixed dates for label freedom)")
    print(f"\n  ci width  event-level : {(ev_hi-ev_lo)*100:.3f}%")
    print(f"  ci width  date-block  : {(blk_hi-blk_lo)*100:.3f}%  "
          f"(x{(blk_hi-blk_lo)/(ev_hi-ev_lo):.2f} vs event-level)")

    print(f"\n{'-' * 78}")
    print("INTERPRETATION")
    print(f"{'-' * 78}")
    crosses = blk_lo <= 0 <= blk_hi
    print(f"  date-block CI {'CROSSES zero' if crosses else 'excludes zero'}; "
          f"sig @0.05: {'NO' if blk_p2 >= 0.05 else 'YES'} (cluster p={blk_p2:.3f})")
    print("=" * 78)


if __name__ == "__main__":
    main()
