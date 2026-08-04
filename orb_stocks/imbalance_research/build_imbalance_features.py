"""
Opening Imbalance Research — STEP 2: feature construction + confound check.
(EXPERIMENTAL harness, orb_stocks/imbalance_research/)  — RESEARCH ONLY.

Inputs  : imbalance_coverage.parquet          (Step 1 signed aggregates)
          raits/data/cache/news/orb_event_index.parquet   (gap_pct, regime, ...)
Output  : imbalance_features.parquet

Does THREE things and stops:

  1. Builds the candidate imbalance features from Step 1's cached aggregates.
  2. Reports their DISTRIBUTION before any test is chosen — prompt requirement
     #4: do not impose magnitude (or any variable) as the test variable if the
     population is structurally skewed. The catalyst study's lesson was that
     is_idiosyncratic (a clean binary) was testable where catalyst magnitude
     was not; the analogous call is made here from the printed distribution.
  3. Reports CONFOUNDING with the price-action features already tested dead in
     H1-H3 (gap_pct, and a pre-market-volume rank proxy for RVol) — prompt
     requirement #2. If signed flow is just gap/volume wearing a hat, the
     Step 3 result is uninterpretable as "new information".

────────────────────────────────────────────────────────────────────────────
FEATURE DEFINITIONS
────────────────────────────────────────────────────────────────────────────
Per measurement window w in {late 09:00-09:30 ET, full 04:00-09:30 ET}:

  imb_ratio_vol = (buy_vol - sell_vol) / (buy_vol + sell_vol)       in [-1, 1]
  imb_ratio_cnt = (n_buy - n_sell)   / (n_buy + n_sell)             in [-1, 1]
      Both reported: volume-weighted is the economically meaningful one but is
      dominated by a handful of block prints in thin pre-market tape; the
      count-weighted version is robust to that. Divergence between them is
      itself diagnostic and is printed.

  imb_direction = sign(imb_ratio_vol)
      The PRIMARY candidate. All 155 events are SHORT, so:
          aligned = sell-side flow (imb_ratio_vol < 0), agrees with the trade
          against = buy-side  flow (imb_ratio_vol > 0)
      Needs no baseline, no standardisation, no distributional assumption.

  imb_magnitude = |imb_ratio_vol|
      SECONDARY. Only promoted to a test variable if section 2 shows the
      distribution supports it.

  imb_z_loo = leave-one-out within-ticker z-score of imb_ratio_vol
      SECONDARY. Baseline is the SAME TICKER's OTHER events, excluding the
      event itself (so an event cannot standardise against itself). This
      satisfies "baseline của chính mã đó, không so toàn thị trường" and
      removes the ticker level + market-wide macro level in one step.

      CAVEAT, stated plainly: this baseline is built from EVENT days only, not
      from all trading days. It therefore removes the ticker's typical
      signed-flow level, but NOT the "this is an event day" conditioning. A
      true all-days baseline needs ~21 extra fetch-days per ticker (~650
      requests, ~30-60 min); that is deliberately deferred and is listed as a
      revisit condition if Step 3 lands on "monitor". Computed only for
      tickers with >= MIN_TICKER_EVENTS events; NaN otherwise.

  premkt_vol_rank = within-ticker percentile rank of full-window total_vol
      Confound probe standing in for RVol. NOT true relative volume (that
      needs a 20-day average-volume baseline); it is a within-ticker ordinal
      of pre-market activity, which is the specific confound that matters —
      "is signed flow just a restatement of how busy the pre-market was?"

Run:
    cd d:\\raits
    python orb_stocks\\imbalance_research\\build_imbalance_features.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from scipy import stats

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
COVERAGE = os.path.join(HERE, "imbalance_coverage.parquet")
EVENT_INDEX = os.path.join(REPO, "raits", "data", "cache", "news", "orb_event_index.parquet")
OUT = os.path.join(HERE, "imbalance_features.parquet")

WINDOWS = ["late", "full"]
MIN_TICKER_EVENTS = 4       # floor for a leave-one-out within-ticker baseline
MIN_TRADES = 30             # must match Step 1's usability floor


def _ratio(pos, neg):
    tot = pos + neg
    return np.where(tot > 0, (pos - neg) / np.where(tot > 0, tot, 1), np.nan)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for w in WINDOWS:
        out[f"{w}_imb_ratio_vol"] = _ratio(out[f"{w}_buy_vol"].values,
                                           out[f"{w}_sell_vol"].values)
        out[f"{w}_imb_ratio_cnt"] = _ratio(out[f"{w}_n_buy"].values.astype(float),
                                           out[f"{w}_n_sell"].values.astype(float))
        out[f"{w}_imb_direction"] = np.sign(out[f"{w}_imb_ratio_vol"])
        out[f"{w}_imb_magnitude"] = out[f"{w}_imb_ratio_vol"].abs()
        # unclassified share — a quality flag on the tick rule itself
        tot = out[f"{w}_total_vol"].replace(0, np.nan)
        out[f"{w}_unclass_share"] = out[f"{w}_unclass_vol"] / tot

    # leave-one-out within-ticker z-score (event-day baseline; see docstring)
    for w in WINDOWS:
        col = f"{w}_imb_ratio_vol"
        z = pd.Series(np.nan, index=out.index, dtype=float)
        for tk, g in out.groupby("ticker"):
            if len(g) < MIN_TICKER_EVENTS:
                continue
            v = g[col]
            n = v.notna().sum()
            if n < MIN_TICKER_EVENTS:
                continue
            s, ss = v.sum(), (v ** 2).sum()
            for idx in g.index:
                x = out.at[idx, col]
                if pd.isna(x):
                    continue
                m_oth = (s - x) / (n - 1)
                var_oth = max((ss - x ** 2) / (n - 1) - m_oth ** 2, 0.0)
                sd_oth = np.sqrt(var_oth * (n - 1) / max(n - 2, 1))
                z.at[idx] = (x - m_oth) / sd_oth if sd_oth > 0 else np.nan
        out[f"{w}_imb_z_loo"] = z

    # within-ticker percentile rank of pre-market volume (RVol confound probe)
    out["premkt_vol_rank"] = (out.groupby("ticker")["full_total_vol"]
                                 .rank(pct=True))
    return out


def section_distribution(df: pd.DataFrame) -> dict:
    print("=" * 78)
    print("SECTION 2 — DISTRIBUTION CHECK (choose the test variable FROM the data)")
    print("=" * 78)
    print("  Prompt requirement #4: do not impose magnitude as the test variable")
    print("  if the population is structurally skewed. Decide from what follows.\n")

    picks = {}
    for w in WINDOWS:
        v = df[f"{w}_imb_ratio_vol"].dropna()
        print(f"  WINDOW '{w}'  (n={len(v)} with a defined ratio)")
        if len(v) == 0:
            print("    no usable rows\n")
            continue
        q = v.quantile([0, .05, .25, .5, .75, .95, 1])
        print(f"    imb_ratio_vol: mean={v.mean():+.4f} sd={v.std():.4f} "
              f"skew={stats.skew(v):+.3f} kurt={stats.kurtosis(v):+.3f}")
        print(f"      percentiles : min={q[0]:+.3f} p5={q[.05]:+.3f} "
              f"p25={q[.25]:+.3f} med={q[.5]:+.3f} p75={q[.75]:+.3f} "
              f"p95={q[.95]:+.3f} max={q[1]:+.3f}")
        n_pos, n_neg = int((v > 0).sum()), int((v < 0).sum())
        print(f"      sign split  : buy-side {n_pos} / sell-side {n_neg} "
              f"({n_pos / len(v) * 100:.0f}% buy-side)")
        # degenerate = ratio pinned at +-1 (one-sided tape, no real imbalance info)
        deg = int((v.abs() > 0.99).sum())
        print(f"      degenerate |ratio|>0.99 (one-sided tape): {deg} "
              f"({deg / len(v) * 100:.0f}%)")
        # vol- vs count-weighted agreement: block-print sensitivity
        both = df[[f"{w}_imb_ratio_vol", f"{w}_imb_ratio_cnt"]].dropna()
        if len(both) > 2:
            agree = (np.sign(both.iloc[:, 0]) == np.sign(both.iloc[:, 1])).mean()
            r = stats.spearmanr(both.iloc[:, 0], both.iloc[:, 1]).correlation
            print(f"      vol vs cnt  : sign agreement {agree * 100:.0f}%, "
                  f"spearman {r:+.3f}")
        u = df[f"{w}_unclass_share"].dropna()
        if len(u):
            print(f"      tick-rule unclassified volume share: "
                  f"med={u.median() * 100:.1f}% p90={u.quantile(.9) * 100:.1f}%")

        # Verdict on whether magnitude is a defensible test variable here.
        mag_ok = (deg / len(v) < 0.25) and (abs(stats.skew(v.abs())) < 2.0)
        bal_ok = 0.25 <= n_pos / len(v) <= 0.75
        print(f"      -> direction testable (sign split not degenerate): "
              f"{'YES' if bal_ok else 'NO'}")
        print(f"      -> magnitude testable (not pinned/heavily skewed): "
              f"{'YES' if mag_ok else 'NO'}")
        picks[w] = {"direction_ok": bal_ok, "magnitude_ok": mag_ok,
                    "n": len(v), "n_pos": n_pos, "n_neg": n_neg}
        print()
    return picks


def section_confound(df: pd.DataFrame) -> None:
    print("=" * 78)
    print("SECTION 3 — CONFOUND CHECK vs price-action features already tested (H1-H3)")
    print("=" * 78)
    print("  Prompt requirement #2. High correlation here means a Step 3 result")
    print("  is NOT independent evidence — it would be H1-H3 restated.\n")

    probes = [("gap_pct", "signed gap (H1-H3 price action)"),
              ("premkt_vol_rank", "within-ticker pre-market volume rank (RVol proxy)")]

    for w in WINDOWS:
        print(f"  WINDOW '{w}'")
        for feat, flabel in [(f"{w}_imb_ratio_vol", "imb_ratio_vol"),
                             (f"{w}_imb_magnitude", "imb_magnitude")]:
            for pcol, plabel in probes:
                sub = df[[feat, pcol]].dropna()
                if len(sub) < 8:
                    print(f"    {flabel:<14} vs {plabel:<48} n<8, skipped")
                    continue
                pr = stats.pearsonr(sub[feat], sub[pcol])
                sr = stats.spearmanr(sub[feat], sub[pcol])
                flag = ""
                if abs(sr.correlation) >= 0.5:
                    flag = "  <== HIGH: likely the same information"
                elif abs(sr.correlation) >= 0.3:
                    flag = "  <-- moderate: report alongside any Step 3 result"
                print(f"    {flabel:<14} vs {plabel:<48} "
                      f"n={len(sub):3} pearson={pr[0]:+.3f} "
                      f"spearman={sr.correlation:+.3f} (p={sr.pvalue:.3f}){flag}")
        # sign-level confound: does the flow sign just track the gap sign?
        sub = df[[f"{w}_imb_direction", "gap_pct"]].dropna()
        if len(sub) >= 8:
            si = np.sign(sub[f"{w}_imb_direction"]).values
            sg = np.sign(sub["gap_pct"]).values
            agree = float((si == sg).mean())
            # Raw agreement is NOT interpretable here: this population is
            # overwhelmingly down-gap AND overwhelmingly sell-side, so two
            # unrelated variables would still "agree" most of the time. Compare
            # against the chance rate implied by the two marginals, and report
            # Cohen's kappa (agreement in excess of chance).
            p_i = float((si < 0).mean()); p_g = float((sg < 0).mean())
            chance = p_i * p_g + (1 - p_i) * (1 - p_g)
            kappa = (agree - chance) / (1 - chance) if chance < 1 else np.nan
            print(f"    sign(imb) == sign(gap): {agree * 100:.0f}% of {len(sub)} events")
            print(f"      marginals: sell-side flow {p_i * 100:.0f}%, "
                  f"down-gap {p_g * 100:.0f}% -> chance agreement {chance * 100:.0f}%")
            print(f"      Cohen's kappa = {kappa:+.3f}  "
                  f"({'no association beyond base rates' if abs(kappa) < 0.2 else 'real association — treat as confounded'})")
        print()


def main() -> None:
    if not os.path.exists(COVERAGE):
        sys.exit(f"FATAL: {COVERAGE} not found — run Step 1 "
                 f"(check_imbalance_coverage.py) first.")

    cov = pd.read_parquet(COVERAGE)
    print("=" * 78)
    print("OPENING IMBALANCE RESEARCH — STEP 2: FEATURES + CONFOUND CHECK")
    print("RESEARCH ONLY — no production code touched.")
    print("=" * 78)
    print(f"  loaded {len(cov)} events from Step 1 cache")

    # Join regime / gap_pct etc. from the shared event index (same index the
    # catalyst study used — reused deliberately, not rebuilt).
    ev = pd.read_parquet(EVENT_INDEX).reset_index()
    ev["date"] = pd.to_datetime(ev["date"]).dt.date.astype(str)
    keep = ["ticker", "date", "in_primary_151", "n_same_day_articles",
            "n_premkt_articles"]
    cov = cov.merge(ev[keep], on=["ticker", "date"], how="left")

    # Usability + data-quality gates, applied and REPORTED (never silent).
    n0 = len(cov)
    gs = int(cov["gap_suspect"].sum())
    cov = cov[~cov["gap_suspect"]].copy()
    print(f"  dropped gap_suspect (corrupt bars, same gate as catalyst study): {gs}")

    df = build_features(cov)

    for w in WINDOWS:
        n_us = int((df[f"{w}_n_classified"] >= MIN_TRADES).sum())
        print(f"  window '{w}': {n_us}/{len(df)} events clear the "
              f"{MIN_TRADES}-classified-trade floor")
    print(f"  carried forward: {len(df)} of {n0} events\n")

    picks = section_distribution(df)
    section_confound(df)

    df.to_parquet(OUT, index=False)

    print("=" * 78)
    print("STEP 2 HANDOFF")
    print("=" * 78)
    for w, p in picks.items():
        prim = "direction" if p["direction_ok"] else \
               ("magnitude" if p["magnitude_ok"] else "NONE — population degenerate")
        print(f"  window '{w}': n={p['n']}, sell-side={p['n_neg']} buy-side={p['n_pos']}"
              f"  -> primary test variable: {prim}")
    print(f"\n  written: {OUT}")
    print("  next: python orb_stocks\\imbalance_research\\bootstrap_imbalance.py")
    print("=" * 78)


if __name__ == "__main__":
    main()
