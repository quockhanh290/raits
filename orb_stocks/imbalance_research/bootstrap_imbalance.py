"""
Opening Imbalance Research — STEP 3: three-layer statistical test.
(EXPERIMENTAL harness, orb_stocks/imbalance_research/)  — RESEARCH ONLY.

Inputs : imbalance_features.parquet                       (Step 2)
         raits/data/cache/news/orb_event_outcome.parquet   (catalyst study —
             pct_return / R_multiple already derived from the sim's own
             entry_px/exit_px, with the |pct|>25% corrupt-bar gate applied.
             REUSED, not rebuilt: the outcome definition must be identical to
             the catalyst study's or the two results are not comparable.)

────────────────────────────────────────────────────────────────────────────
THE THREE LAYERS  (run in this order; layer 3 is the decision, not layer 1)
────────────────────────────────────────────────────────────────────────────
  1. NAIVE EVENT BOOTSTRAP
        Resample events i.i.d. Overstates confidence whenever several events
        share a date (a Stress-regime selloff hits many stocks at once).
        Reported for continuity with the catalyst study, NOT for deciding.

  2. DATE-CLUSTER BOOTSTRAP
        Resample DATES with replacement, take all of each date's events.
        Also reports the design effect and the effective n it implies.

  3. WITHIN-DATE CONDITIONAL PERMUTATION           <-- THE DECIDING TEST
        Restricted to dates carrying BOTH an aligned and an against event;
        shuffle the aligned/against labels only within those dates. Anything
        that is a property of the DAY (market-wide selloff, VIX level, regime)
        is held fixed by construction, so what survives is attributable to the
        imbalance label itself.

        This is the exact test that killed the catalyst hypothesis: the naive
        layer showed +0.32% with P(A>B)=0.94, and the within-date permutation
        returned p=0.524 — i.e. a between-date artifact, not a causal effect.

────────────────────────────────────────────────────────────────────────────
MULTIPLICITY — pre-committed before looking at any result
────────────────────────────────────────────────────────────────────────────
Two windows x two outcome metrics = 4 possible tests. Cherry-picking the best
of four is how a dead hypothesis gets resurrected. Therefore:

  PRIMARY   : window 'late' (09:00-09:30 ET, the auction-imbalance analogue)
              x pct_return.  The verdict is read off THIS cell.
  SECONDARY : everything else. Reported for consistency-of-direction only. A
              secondary cell cannot promote a verdict; it can only downgrade
              one (if the primary is positive but secondaries point the other
              way, that is incoherence, not confirmation).

────────────────────────────────────────────────────────────────────────────
VERDICT TIERS  (same three tiers as the catalyst study)
────────────────────────────────────────────────────────────────────────────
  GO      : within-date p < 0.05 AND direction consistent across layers 1-3
            AND Step 2 reported no high confound (|spearman| >= 0.5) with
            gap_pct / pre-market volume.
  MONITOR : within-date p in [0.05, 0.20] with a consistent direction across
            all three layers. Records what additional evidence would settle it.
  DEAD    : within-date p > 0.20, or direction flips between layers, or the
            effect is explained by a Step 2 confound.

Run:
    cd d:\\raits
    python orb_stocks\\imbalance_research\\bootstrap_imbalance.py
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
OUT = os.path.join(HERE, "imbalance_test_results.parquet")

N_BOOT = 10_000
SEED = 42
MIN_TRADES = 30

PRIMARY_WINDOW = "late"
PRIMARY_METRIC = "pct_return"
CELLS = [("late", "pct_return"), ("late", "R_multiple"),
         ("full", "pct_return"), ("full", "R_multiple")]


# ──────────────────────────────────────────────────────────────────────────
# Clustering diagnostics
# ──────────────────────────────────────────────────────────────────────────
def icc_and_effective_n(values: np.ndarray, groups: np.ndarray):
    """
    One-way random-effects ICC and the cluster-adjusted effective n.

        design_effect = 1 + (m0 - 1) * ICC
        n_eff         = n / design_effect

    m0 is the standard adjusted average cluster size (not the raw mean), which
    corrects for unequal cluster sizes. ICC is floored at 0 — a negative
    variance-component estimate means "no detectable clustering", and letting
    it go negative would inflate n_eff above n.
    """
    dfm = pd.DataFrame({"v": values, "g": groups})
    k = dfm["g"].nunique()
    n = len(dfm)
    if k < 2 or n <= k:
        return np.nan, np.nan, np.nan, np.nan

    sizes = dfm.groupby("g").size().values
    grand = dfm["v"].mean()
    gm = dfm.groupby("g")["v"].mean()

    ssb = float((sizes * (gm.values - grand) ** 2).sum())
    ssw = float(((dfm["v"] - dfm["g"].map(gm)) ** 2).sum())
    msb = ssb / (k - 1)
    msw = ssw / (n - k)

    m0 = (n - (sizes ** 2).sum() / n) / (k - 1)
    denom = msb + (m0 - 1) * msw
    icc = 0.0 if denom <= 0 else max((msb - msw) / denom, 0.0)

    m_bar = n / k
    deff = 1 + (m_bar - 1) * icc
    return icc, deff, n / deff, m_bar


# ──────────────────────────────────────────────────────────────────────────
# Layer 1 — naive event-level
# ──────────────────────────────────────────────────────────────────────────
def layer1(a: np.ndarray, b: np.ndarray, rng_seed: int):
    rng = np.random.default_rng(rng_seed)
    diffs = np.empty(N_BOOT)
    for i in range(N_BOOT):
        diffs[i] = (rng.choice(a, len(a), replace=True).mean()
                    - rng.choice(b, len(b), replace=True).mean())
    lo, hi = np.percentile(diffs, [2.5, 97.5])

    rng2 = np.random.default_rng(rng_seed + 1)
    obs = a.mean() - b.mean()
    pool = np.concatenate([a, b])
    na = len(a)
    cnt = 0
    for _ in range(N_BOOT):
        rng2.shuffle(pool)
        if abs(pool[:na].mean() - pool[na:].mean()) >= abs(obs):
            cnt += 1
    return dict(obs=obs, ci=(lo, hi), p_gt0=float((diffs > 0).mean()),
                perm_p=(cnt + 1) / (N_BOOT + 1))


# ──────────────────────────────────────────────────────────────────────────
# Layer 2 — date-cluster bootstrap
# ──────────────────────────────────────────────────────────────────────────
def layer2(df: pd.DataFrame, metric: str, rng_seed: int):
    dates = sorted(df["date"].unique())
    di = {d: i for i, d in enumerate(dates)}
    nd = len(dates)
    aSum = np.zeros(nd); aCnt = np.zeros(nd)
    bSum = np.zeros(nd); bCnt = np.zeros(nd)
    for _, r in df.iterrows():
        i = di[r["date"]]
        if r["aligned"]:
            aSum[i] += r[metric]; aCnt[i] += 1
        else:
            bSum[i] += r[metric]; bCnt[i] += 1

    rng = np.random.default_rng(rng_seed)
    blk = np.full(N_BOOT, np.nan)
    for i in range(N_BOOT):
        draw = rng.integers(0, nd, nd)
        nA = aCnt[draw].sum(); nB = bCnt[draw].sum()
        if nA == 0 or nB == 0:
            continue
        blk[i] = aSum[draw].sum() / nA - bSum[draw].sum() / nB
    blk = blk[~np.isnan(blk)]
    lo, hi = np.percentile(blk, [2.5, 97.5])
    p2 = 2 * min((blk <= 0).mean(), (blk >= 0).mean())
    return dict(ci=(lo, hi), p_gt0=float((blk > 0).mean()),
                cluster_p=float(min(p2, 1.0)), n_valid=len(blk))


# ──────────────────────────────────────────────────────────────────────────
# Layer 3 — within-date conditional permutation (the deciding test)
# ──────────────────────────────────────────────────────────────────────────
def layer3(df: pd.DataFrame, metric: str, rng_seed: int):
    A = df[df["aligned"]]; B = df[~df["aligned"]]
    a_dates = set(A["date"]); b_dates = set(B["date"])
    mixed = sorted(a_dates & b_dates)
    if not mixed:
        return dict(perm_p=None, n_mixed_dates=0, n_mixed_events=0,
                    obs=np.nan, note="no mixed dates — test has zero label freedom")

    obs = A[metric].mean() - B[metric].mean()
    fixedA = A[~A["date"].isin(mixed)][metric].sum()
    fixedB = B[~B["date"].isin(mixed)][metric].sum()
    nA, nB = len(A), len(B)

    blocks = []
    for d in mixed:
        sub = df[df["date"] == d]
        blocks.append((sub[metric].values, int(sub["aligned"].sum())))

    rng = np.random.default_rng(rng_seed)
    draws = np.empty(N_BOOT)
    for i in range(N_BOOT):
        sA, sB = fixedA, fixedB
        for vals, kA in blocks:
            idx = rng.permutation(len(vals))
            sA += vals[idx[:kA]].sum()
            sB += vals[idx[kA:]].sum()
        draws[i] = sA / nA - sB / nB

    # ── CENTERING (do not remove) ─────────────────────────────────────────
    # Events on pure (non-mixed) dates have no label freedom, so their
    # contribution is a CONSTANT that appears in obs and in every permuted
    # draw alike. The null distribution is therefore centred on that offset,
    # NOT on zero. Testing |perm| >= |obs| against zero — which is what
    # orb_stocks/cluster_bootstrap.py does — measures distance from the wrong
    # origin and is anti-conservative whenever the offset shares obs's sign.
    #
    # Measured on the primary cell of this study: null centre = +0.00122,
    # uncentred p = 0.0127 vs centred p = 0.0263 — the uncentred form
    # overstated significance by ~2x. Both p-values are reported; `perm_p`
    # is the CENTRED one and is what the verdict reads.
    centre = float(draws.mean())
    cnt_c = int((np.abs(draws - centre) >= abs(obs - centre)).sum())
    cnt_u = int((np.abs(draws) >= abs(obs)).sum())
    n_mixed_events = int(df["date"].isin(mixed).sum())
    return dict(perm_p=(cnt_c + 1) / (N_BOOT + 1),
                perm_p_uncentred=(cnt_u + 1) / (N_BOOT + 1),
                null_centre=centre, null_sd=float(draws.std()),
                z=(obs - centre) / draws.std() if draws.std() > 0 else np.nan,
                n_mixed_dates=len(mixed), n_mixed_events=n_mixed_events,
                obs=obs, note="")


# ──────────────────────────────────────────────────────────────────────────
def run_cell(df: pd.DataFrame, window: str, metric: str, primary: bool):
    tag = "PRIMARY" if primary else "secondary"
    print(f"\n{'=' * 78}")
    print(f"CELL [{tag}]  window='{window}'  outcome='{metric}'")
    print("=" * 78)

    sub = df[(df[f"{window}_n_classified"] >= MIN_TRADES)
             & df[f"{window}_imb_ratio_vol"].notna()
             & df[metric].notna()].copy()
    # All events in this population are SHORT: aligned == sell-side pre-open flow.
    sub["aligned"] = sub[f"{window}_imb_ratio_vol"] < 0
    sub = sub[sub[f"{window}_imb_ratio_vol"] != 0]

    A = sub[sub["aligned"]][metric].values
    B = sub[~sub["aligned"]][metric].values
    print(f"  population: n={len(sub)} on {sub['date'].nunique()} dates "
          f"| aligned(sell-side)={len(A)}  against(buy-side)={len(B)}")
    if len(A) < 5 or len(B) < 5:
        print("  SKIPPED: one arm has <5 events — no test is meaningful here.")
        return None

    for lab, g in [("A aligned ", A), ("B against ", B)]:
        wr = (g > 0).mean() * 100
        scale = 100 if metric == "pct_return" else 1
        unit = "%" if metric == "pct_return" else "R"
        print(f"    {lab}: n={len(g):3} mean={g.mean() * scale:+.3f}{unit} "
              f"median={np.median(g) * scale:+.3f}{unit} "
              f"win_rate={wr:.0f}% sd={g.std() * scale:.2f}{unit}")

    icc, deff, n_eff, m_bar = icc_and_effective_n(sub[metric].values,
                                                  sub["date"].values)
    print(f"\n  CLUSTERING: {len(sub)} events / {sub['date'].nunique()} dates "
          f"(mean {m_bar:.2f} events per date)")
    print(f"    ICC={icc:.4f}  design_effect={deff:.3f}  "
          f"EFFECTIVE n={n_eff:.1f} (vs raw n={len(sub)})")

    scale = 100 if metric == "pct_return" else 1
    unit = "%" if metric == "pct_return" else "R"

    l1 = layer1(A, B, SEED)
    print(f"\n  LAYER 1 — naive event bootstrap (NOT the decision)")
    print(f"    observed diff (A-B) : {l1['obs'] * scale:+.3f}{unit}")
    print(f"    95% CI              : [{l1['ci'][0] * scale:+.3f}, "
          f"{l1['ci'][1] * scale:+.3f}]{unit}")
    print(f"    P(A>B)              : {l1['p_gt0']:.3f}")
    print(f"    permutation p (2s)  : {l1['perm_p']:.4f}")

    l2 = layer2(sub, metric, SEED)
    print(f"\n  LAYER 2 — date-cluster bootstrap")
    print(f"    95% CI              : [{l2['ci'][0] * scale:+.3f}, "
          f"{l2['ci'][1] * scale:+.3f}]{unit}")
    print(f"    P(A>B)              : {l2['p_gt0']:.3f}")
    print(f"    cluster p (2s)      : {l2['cluster_p']:.4f}")
    w1 = l1["ci"][1] - l1["ci"][0]; w2 = l2["ci"][1] - l2["ci"][0]
    print(f"    CI width vs layer 1 : x{w2 / w1:.2f}")

    l3 = layer3(sub, metric, SEED + 7)
    print(f"\n  LAYER 3 — within-date conditional permutation  <== DECIDES")
    print(f"    mixed dates (both arms present): {l3['n_mixed_dates']} "
          f"carrying {l3['n_mixed_events']} events")
    if l3["perm_p"] is None:
        print(f"    {l3['note']}")
    else:
        print(f"    null centre={l3['null_centre'] * scale:+.4f}{unit} "
              f"sd={l3['null_sd'] * scale:.4f}{unit} | obs z={l3['z']:+.2f}")
        print(f"    within-date permutation p (2s) : {l3['perm_p']:.4f}  "
              f"[CENTRED — the one the verdict uses]")
        print(f"      (uncentred, cluster_bootstrap.py-style: "
              f"{l3['perm_p_uncentred']:.4f} — reported only to show the bias)")
        if l3["n_mixed_dates"] < 8:
            print(f"    WARNING: only {l3['n_mixed_dates']} mixed dates — this "
                  f"test is underpowered; a high p here is weak evidence of "
                  f"absence, not evidence of absence.")

    # direction consistency across the three layers
    dirs = [np.sign(l1["obs"]),
            np.sign(l2["p_gt0"] - 0.5),
            np.sign(l3["obs"]) if l3["perm_p"] is not None else np.nan]
    consistent = len({d for d in dirs if not np.isnan(d)}) == 1
    print(f"\n  direction consistent across layers: "
          f"{'YES' if consistent else 'NO'}  (signs={dirs})")

    return dict(window=window, metric=metric, primary=primary,
                n=len(sub), n_dates=sub["date"].nunique(),
                n_aligned=len(A), n_against=len(B),
                mean_a=A.mean(), mean_b=B.mean(),
                wr_a=float((A > 0).mean()), wr_b=float((B > 0).mean()),
                icc=icc, design_effect=deff, n_eff=n_eff,
                naive_p=l1["perm_p"], naive_p_gt0=l1["p_gt0"], obs=l1["obs"],
                cluster_p=l2["cluster_p"], cluster_p_gt0=l2["p_gt0"],
                within_date_p=l3["perm_p"],
                within_date_p_uncentred=l3.get("perm_p_uncentred", np.nan),
                null_centre=l3.get("null_centre", np.nan),
                n_mixed_dates=l3["n_mixed_dates"],
                n_mixed_events=l3["n_mixed_events"], consistent=consistent)


def main() -> None:
    if not os.path.exists(FEATURES):
        sys.exit(f"FATAL: {FEATURES} not found — run Step 2 "
                 f"(build_imbalance_features.py) first.")

    feat = pd.read_parquet(FEATURES)
    outc = pd.read_parquet(OUTCOME)
    outc = outc[~outc["outcome_suspect"]].copy()

    print("=" * 78)
    print("OPENING IMBALANCE RESEARCH — STEP 3: THREE-LAYER TEST")
    print("RESEARCH ONLY — no production code touched, no merge implied.")
    print("=" * 78)
    print(f"  features : {len(feat)} events (Step 2)")
    print(f"  outcomes : {len(outc)} clean events (catalyst study, reused)")

    feat["date"] = feat["date"].astype(str)
    outc["date"] = outc["date"].astype(str)
    df = feat.merge(outc[["ticker", "date", "pct_return", "R_multiple",
                          "is_idiosyncratic"]],
                    on=["ticker", "date"], how="inner")
    print(f"  joined   : {len(df)} events with BOTH imbalance and outcome")
    lost = len(feat) - len(df)
    if lost:
        print(f"  ({lost} feature rows had no outcome record — the catalyst "
              f"study's own unmatched set; not a new loss)")

    results = []
    for w, m in CELLS:
        primary = (w == PRIMARY_WINDOW and m == PRIMARY_METRIC)
        r = run_cell(df, w, m, primary)
        if r:
            results.append(r)

    if not results:
        print("\nNo testable cell. STOP.")
        return

    res = pd.DataFrame(results)
    res.to_parquet(OUT, index=False)

    # ── Verdict, read off the PRIMARY cell only ───────────────────────────
    print(f"\n{'=' * 78}")
    print("VERDICT")
    print("=" * 78)
    prim = res[res["primary"]]
    if prim.empty:
        print("  PRIMARY cell was not testable -> DEAD by design "
              "(no pre-committed cell survived).")
        return
    p = prim.iloc[0]

    print(f"  primary cell: window='{p.window}' outcome='{p.metric}'")
    print(f"    raw n={int(p.n)}  EFFECTIVE n={p.n_eff:.1f} "
          f"(ICC={p.icc:.4f}, design effect={p.design_effect:.3f})")
    print(f"    aligned n={int(p.n_aligned)} vs against n={int(p.n_against)}")
    print(f"    layer 1 naive p        = {p.naive_p:.4f}")
    print(f"    layer 2 cluster p      = {p.cluster_p:.4f}")
    wd = p.within_date_p
    print(f"    layer 3 within-date p  = "
          f"{'n/a (no mixed dates)' if pd.isna(wd) else f'{wd:.4f}'}   <== decides")
    print(f"    direction consistent   = {bool(p.consistent)}")

    if pd.isna(wd):
        tier = "DEAD"
        why = "no mixed dates — the deciding test cannot be run at all"
    elif wd < 0.05 and p.consistent:
        tier = "GO"
        why = "within-date p<0.05 with a direction consistent across all three layers"
    elif wd <= 0.20 and p.consistent:
        tier = "MONITOR"
        why = "within-date p in [0.05,0.20], direction consistent"
    else:
        tier = "DEAD"
        why = ("within-date p>0.20" if wd > 0.20
               else "direction flips between layers")

    print(f"\n  TIER: {tier}   ({why})")
    if tier == "GO":
        print("    NOT FINAL — this tier is provisional until robustness passes.")
        print("    Run: python orb_stocks\\imbalance_research\\robustness_imbalance.py")
        print("    A GO that breaks on any single ticker or single date is a")
        print("    concentration artifact and is downgraded to MONITOR regardless")
        print("    of the p-value here. (On the 2026-08-03 run it WAS downgraded:")
        print("    dropping QCOM -> p=0.102, dropping NVDA -> p=0.065, and the")
        print("    effect is 2022-only. See FINDINGS.md.)")
        print("    NOTE: GO means 'enough basis to DESIGN a filter/confirm layer'.")
        print("    It does NOT authorise a merge into production. That is a")
        print("    separate decision, taken separately. Re-read Step 2's confound")
        print("    section before treating this as new information.")
    elif tier == "MONITOR":
        print("    Revisit conditions (what would actually settle this):")
        print("      1. A true all-days within-ticker baseline (~21 extra")
        print("         fetch-days x 31 tickers) so imb_z_loo stops being")
        print("         conditioned on event days.")
        print("      2. More mixed dates. The deciding test's power is set by")
        print(f"         mixed-date count, currently {int(p.n_mixed_dates)}.")
        print("      3. Official auction imbalance or NBBO quotes. The tick-rule")
        print("         proxy is a strictly weaker classifier; a real signal could")
        print("         be attenuated below detection by classification error.")
    else:
        print("    Record and stop. Do not build Step 4.")

    print(f"\n  secondary cells (direction-consistency only, cannot promote):")
    for _, r in res[~res["primary"]].iterrows():
        wdr = "n/a" if pd.isna(r.within_date_p) else f"{r.within_date_p:.4f}"
        print(f"    {r.window:<5} {r.metric:<12} n={int(r.n):3} "
              f"diff={r.obs:+.5f} naive_p={r.naive_p:.3f} "
              f"cluster_p={r.cluster_p:.3f} within_p={wdr}")

    print(f"\n  written: {OUT}")
    print("=" * 78)


if __name__ == "__main__":
    main()
