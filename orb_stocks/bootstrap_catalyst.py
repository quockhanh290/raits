"""
bootstrap_catalyst.py — Step 3: is_idiosyncratic vs price-based outcome
(EXPERIMENTAL harness, orb_stocks/)  — RESEARCH ONLY.

Outcome metric sidesteps the disputed STRESS_ORB_STK dollar P&L entirely: it uses
the sim's own recorded entry_px / exit_px (exit already reflects the sim's
STOP/TARGET/TIME exit LOGIC), so:
    pct_return = (entry_px - exit_px) / entry_px      # SHORT: +ve = profitable
    R_multiple = (entry_px - exit_px) / stop_dist     # stop_dist = stop_px - entry_px
No shares / Kelly / account-equity anywhere.

Sources of the outcome per event:
  - STRESS_ORB_STK events  -> sim t_v3 trade records (entry_px, exit_px, stop_dist)
  - ORB events             -> snapshot Trade (entry_price, exit_price, stop)

Step 1 correction applied: AMD 2022-09-01 (legal_regulatory_action) -> idiosyncratic
(the only one of the 5 rule-tension events whose type is 'clearly stock-specific').

STOP after this — research only. No engine changes, no re-enable.

Run:
    cd d:\\raits
    python orb_stocks\\bootstrap_catalyst.py
"""

from __future__ import annotations

import os
import sys
import io
import pickle
import contextlib
import collections

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "raits", "raits", "scripts"))

CACHE_DIR = os.path.join(REPO, "raits", "data", "cache")
CATALYST = os.path.join(CACHE_DIR, "news", "orb_event_catalyst.parquet")
EVENT_INDEX = os.path.join(CACHE_DIR, "news", "orb_event_index.parquet")
SNAPSHOT = os.path.join(CACHE_DIR, "snapshots", "results_20260707_110323.pkl")
OUT = os.path.join(CACHE_DIR, "news", "orb_event_outcome.parquet")

WS, WE = pd.Timestamp("2021-04-01"), pd.Timestamp("2022-12-31")
N_BOOT = 10_000
SEED = 42

# Step-1 correction: exactly one event (type-based rule).
CORRECTIONS = {("AMD", "2022-09-01"): True}


def stress_outcomes():
    """(ticker, date_iso) -> dict(entry_px, exit_px, stop_dist) from sim t_v3."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import stress_orb_stk_sim as sim
    out = {}
    for t in sim.t_v3:
        d = pd.Timestamp(t["day"]).normalize()
        if not (WS <= d <= WE):
            continue
        out[(t["ticker"], d.date().isoformat())] = {
            "entry_px": float(t["entry_px"]),
            "exit_px": float(t["exit_px"]),
            "stop_dist": float(t["stop_dist"]),
        }
    return out


def orb_outcomes():
    """(ticker, date_iso) -> dict from snapshot ORB SHORT trades."""
    with open(SNAPSHOT, "rb") as f:
        windows = pickle.load(f)
    out = {}
    for w in windows:
        for t in w["trades"]:
            if getattr(t, "strategy", None) != "ORB" or getattr(t, "direction", None) != "SHORT":
                continue
            d = pd.Timestamp(t.entry_time).normalize()
            if not (WS <= d <= WE):
                continue
            entry, exitp, stop = float(t.entry_price), float(t.exit_price), float(t.stop)
            out[(t.ticker, d.date().isoformat())] = {
                "entry_px": entry, "exit_px": exitp,
                "stop_dist": stop - entry,  # SHORT stop is above entry
            }
    return out


def boot_mean_diff(a, b, rng, n=N_BOOT):
    """Bootstrap distribution of mean(a) - mean(b)."""
    a, b = np.asarray(a), np.asarray(b)
    diffs = np.empty(n)
    for i in range(n):
        diffs[i] = rng.choice(a, len(a), replace=True).mean() - \
                   rng.choice(b, len(b), replace=True).mean()
    return diffs


def perm_pvalue(a, b, rng, n=N_BOOT):
    """Two-sided permutation p-value for difference in means."""
    a, b = np.asarray(a), np.asarray(b)
    obs = a.mean() - b.mean()
    pool = np.concatenate([a, b])
    na = len(a)
    count = 0
    for _ in range(n):
        rng.shuffle(pool)
        d = pool[:na].mean() - pool[na:].mean()
        if abs(d) >= abs(obs):
            count += 1
    return (count + 1) / (n + 1)


def main():
    print("=" * 78)
    print("ORB STOCKS — STEP 3: is_idiosyncratic vs price-based outcome (RESEARCH ONLY)")
    print("=" * 78)

    cat = pd.read_parquet(CATALYST).reset_index()
    cat["date_iso"] = cat["date"].apply(lambda x: pd.Timestamp(x).date().isoformat())
    # 'source' (ORB / STRESS_ORB_STK) lives in the event index — join it in.
    ev = pd.read_parquet(EVENT_INDEX).reset_index()[["ticker", "date", "source"]]
    ev["date_iso"] = ev["date"].apply(lambda x: pd.Timestamp(x).date().isoformat())
    cat = cat.merge(ev[["ticker", "date_iso", "source"]], on=["ticker", "date_iso"], how="left")
    assert cat["source"].notna().all(), "source join left NaNs"

    # ── Step 1: apply corrections ─────────────────────────────────────────
    cat["is_idio_orig"] = cat["is_idiosyncratic"]
    changed = []
    for i, r in cat.iterrows():
        key = (r["ticker"], r["date_iso"])
        if key in CORRECTIONS and bool(r["is_idiosyncratic"]) != CORRECTIONS[key]:
            cat.at[i, "is_idiosyncratic"] = CORRECTIONS[key]
            changed.append((r["ticker"], r["date_iso"], r["catalyst_type"],
                            bool(r["is_idio_orig"]), CORRECTIONS[key]))
    print(f"\nStep 1 — label corrections applied: {len(changed)}")
    for tk, ds, ct, was, now in changed:
        print(f"  {tk} {ds} [{ct}]: is_idiosyncratic {was} -> {now}")
    print(f"  is_idiosyncratic now: True={int(cat['is_idiosyncratic'].sum())} "
          f"False={int((~cat['is_idiosyncratic']).sum())}")

    # ── Step 2: outcome per event ─────────────────────────────────────────
    print("\nStep 2 — computing price-based outcome (importing sim, ~60s)...")
    stress = stress_outcomes()
    orb = orb_outcomes()

    recs, unmatched = [], []
    for _, r in cat.iterrows():
        key = (r["ticker"], r["date_iso"])
        src = r["source"]
        o = stress.get(key) if src == "STRESS_ORB_STK" else orb.get(key)
        if o is None:
            unmatched.append((src, *key))
            continue
        entry, exitp, sd = o["entry_px"], o["exit_px"], o["stop_dist"]
        pct = (entry - exitp) / entry if entry else np.nan          # SHORT
        rmult = (entry - exitp) / sd if sd and sd > 0 else np.nan
        recs.append({
            "ticker": r["ticker"], "date": r["date_iso"], "source": src,
            "is_idiosyncratic": bool(r["is_idiosyncratic"]),
            "catalyst_type": r["catalyst_type"],
            "magnitude_signal": r["magnitude_signal"],
            "entry_px": entry, "exit_px": exitp,
            "pct_return": pct, "R_multiple": rmult,
        })

    df = pd.DataFrame(recs)
    print(f"  matched outcomes: {len(df)}/{len(cat)} | unmatched: {len(unmatched)}")
    if unmatched:
        for u in unmatched:
            print(f"    UNMATCHED: {u}")

    # ── Data-quality gate: intraday shorts here move <5%; |pct|>25% == corrupt
    # bars (entry/exit price artifact). This catches bad-bar days that the
    # gap_suspect filter (extreme-gap only) missed — e.g. META 2021-10-04
    # (entry $14 vs real ~$330). Report and drop before the bootstrap.
    PCT_MAX = 0.25
    df["outcome_suspect"] = df["pct_return"].abs() > PCT_MAX
    dropped = df[df["outcome_suspect"]]
    print(f"\n  data-quality drop (|pct_return|>{PCT_MAX:.0%} = corrupt bars): {len(dropped)}")
    for _, r in dropped.iterrows():
        print(f"    DROP {r['ticker']} {r['date']}: entry={r['entry_px']:.2f} "
              f"exit={r['exit_px']:.2f} pct={r['pct_return']*100:+.0f}%")
    df.to_parquet(OUT, index=False)
    df = df[~df["outcome_suspect"]].copy()
    print(f"  clean population for bootstrap: {len(df)}")

    # ── Step 3: bootstrap A vs B ──────────────────────────────────────────
    A = df[df["is_idiosyncratic"]]["pct_return"].dropna().values   # idiosyncratic
    B = df[~df["is_idiosyncratic"]]["pct_return"].dropna().values  # macro/no-clear
    rng = np.random.default_rng(SEED)

    print(f"\n{'=' * 78}")
    print("Step 3 — BOOTSTRAP: idiosyncratic (A) vs non-idiosyncratic (B)")
    print(f"{'=' * 78}")
    for label, g in [("A idiosyncratic", A), ("B non-idio    ", B)]:
        wr = (g > 0).mean() * 100
        print(f"  {label}: n={len(g):3}  mean_pct={g.mean()*100:+.3f}%  "
              f"median={np.median(g)*100:+.3f}%  win_rate={wr:.0f}%  sd={g.std()*100:.2f}%")

    diffs = boot_mean_diff(A, B, np.random.default_rng(SEED))
    obs = A.mean() - B.mean()
    ci_lo, ci_hi = np.percentile(diffs, [2.5, 97.5])
    frac_gt0 = (diffs > 0).mean()
    pval = perm_pvalue(A, B, np.random.default_rng(SEED + 1))
    print(f"\n  observed mean diff (A-B): {obs*100:+.3f}%")
    print(f"  bootstrap 95% CI of diff: [{ci_lo*100:+.3f}%, {ci_hi*100:+.3f}%]")
    print(f"  bootstrap P(A>B)        : {frac_gt0:.3f}")
    print(f"  permutation p-value(2s) : {pval:.4f}  "
          f"{'(significant @0.05)' if pval < 0.05 else '(NOT significant @0.05)'}")

    # R-multiple secondary
    Ar = df[df["is_idiosyncratic"]]["R_multiple"].dropna().values
    Br = df[~df["is_idiosyncratic"]]["R_multiple"].dropna().values
    print(f"\n  R-multiple: A mean={Ar.mean():+.3f} (n={len(Ar)}) | "
          f"B mean={Br.mean():+.3f} (n={len(Br)})")

    # ── Time / ticker clustering of idiosyncratic group ───────────────────
    idio = df[df["is_idiosyncratic"]].copy()
    print(f"\n{'-' * 78}")
    print(f"CLUSTERING CHECK — idiosyncratic group (n={len(idio)})")
    print(f"{'-' * 78}")
    dts = pd.to_datetime(idio["date"])
    print(f"  distinct dates : {idio['date'].nunique()} "
          f"({idio['date'].min()} .. {idio['date'].max()})")
    print(f"  distinct tickers: {idio['ticker'].nunique()}  "
          f"{dict(idio['ticker'].value_counts().head(6))}")
    mc = collections.Counter(dts.dt.to_period('M').astype(str))
    print(f"  by month: {dict(sorted(mc.items()))}")
    dd = collections.Counter(idio['date'])
    multi = {d: n for d, n in dd.items() if n > 1}
    print(f"  dates with >1 idiosyncratic event (correlated-day risk): "
          f"{multi if multi else 'none'}")

    # ── Step 5: descriptive within idiosyncratic ──────────────────────────
    print(f"\n{'-' * 78}")
    print("Step 5 — DESCRIPTIVE within idiosyncratic (n small per subtype)")
    print(f"{'-' * 78}")
    for col in ["catalyst_type", "magnitude_signal"]:
        print(f"  by {col}:")
        for k, grp in idio.groupby(col):
            g = grp["pct_return"].dropna().values
            wr = (g > 0).mean() * 100 if len(g) else 0
            print(f"    {k:<26} n={len(g):2}  mean_pct={g.mean()*100:+.3f}%  win={wr:.0f}%")

    print(f"\n{'=' * 78}")
    print("CAVEATS (read before interpreting)")
    print(f"{'=' * 78}")
    print("- DIRECTIONAL / EXPLORATORY only. n=38 idiosyncratic is far thinner than")
    print("  the 3-full-year standard used for H1/H2/H3. NOT a GO/NO-GO verdict.")
    print("- The underlying STRESS_ORB_STK setup is itself unvalidated/reverted; this")
    print("  tests 'catalyst type ~ outcome CONDITIONAL on the setup firing', not")
    print("  'should this be traded live'.")
    print("- Outcome = price move entry->exit (sim exit logic), NO sizing. The")
    print("  disputed $ P&L is not used.")
    print(f"\nWritten: {OUT}")
    print("=" * 78)


if __name__ == "__main__":
    main()
