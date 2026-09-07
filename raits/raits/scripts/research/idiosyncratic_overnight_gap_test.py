"""
IDIOSYNCRATIC_OVERNIGHT_GAP_INTRADAY — does the stock-specific part of an
overnight move predict the session that follows?
(RESEARCH ONLY. Reads the local cache; modifies no production code.)

THE QUESTION (spec §2, §6)
--------------------------
Strip the market and sector component out of each stock's overnight move and
rank what is left. Do the biggest idiosyncratic gappers keep going, or do they
fade? Direction is not assumed — the top-minus-bottom spread carries its sign.

This is an information-shock study, not the old gap-fill rule: previous close
is never a target, only a descriptive reference (spec §18).

WHY SIGNAL B IS NOT AN INDEPENDENT SIGNAL (spec §3)
---------------------------------------------------
`stock_gap - market_gap` subtracts the SAME constant from every stock on a
given day, so it cannot reorder the cross-section. Market-adjusted rank is the
raw rank, exactly. This was confirmed empirically in the previous study, where
the two rows matched to every printed decimal. It is therefore used only where
levels matter — the absolute-magnitude bins of §12 — never as a third ranking.

The same algebra collapses the "market and sector" decomposition:
    (stock - market) - (sector - market) = stock - sector
so there is one residualisation here, not two.

TWO EXECUTION PRICES, BECAUSE THE ANSWER MAY DIFFER (spec §21, §22)
-------------------------------------------------------------------
Stage A prices the signal at the 09:30 open — theoretical, and the reference
the phenomenon is defined on. Stage B re-prices everything at the 09:35 open,
the first bar a real order could realistically have filled. If the edge lives
only in the first five minutes it is not tradable with this data, and that is
mechanism C rather than a positive result.

DATA CHECKS DONE BEFORE WRITING THIS (spec §1.8)
------------------------------------------------
* The 5-minute cache is split-ADJUSTED, so overnight gaps are not corporate
  actions. Verified: of 110,791 gaps none exceed 50%, and the six largest are
  all identifiable news events (BIIB +42.7% on the 2022 lecanemab readout,
  NFLX -29.6% on the 2022 subscriber miss, META -24.6% on Q3 2022).
* Previous close is the prior SESSION's 15:55 bar close, taken by shifting the
  session index — not the calendar — so weekends and holidays cannot
  manufacture a multi-day "overnight" move.
* The 15:55 close is the last RTH print, not the official closing auction.
  Stated rather than assumed.

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\idiosyncratic_overnight_gap_test.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[3]
for p in (str(_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from cross_sectional_intraday_rs_test import (        # noqa: E402
    SECTOR, NON_STOCK, SECTOR_ETFS, MARKET, CACHE, WORK,
    label_at, daily_spread, boot_days, bps, MIN_STOCKS,
)

PANELS = WORK / "gap_panels"
OPEN_L, OPEN2_L, EOD_L = "09:30", "09:35", "15:50"      # bar LABELS
HORIZONS = [("10:00", 30), ("10:30", 60), ("11:00", 90),
            ("12:00", 150), ("14:00", 270), ("EOD", None)]
SEGMENTS = [("open->10:00", OPEN_L, "10:00"), ("10:00->11:00", "10:00", "11:00"),
            ("11:00->12:00", "11:00", "12:00"), ("12:00->EOD", "12:00", "EOD")]
ABS_BINS = [(0.000, 0.005), (0.005, 0.010), (0.010, 0.020),
            (0.020, 0.030), (0.030, 9.0)]
DIVERGENCE = 0.01           # spec §15, declared before running
COST_SIDES = (2.0, 5.0)
OPEN_SLIP = (0.0, 5.0, 10.0)
N_SHUFFLE = 200      # Control A needs a distribution, not a draw


def build_panels():
    """open/high/low/close/volume by (date, bar-label) x ticker."""
    PANELS.mkdir(parents=True, exist_ok=True)
    need = ["open", "high", "low", "close", "volume"]
    if all((PANELS / f"{c}.parquet").exists() for c in need):
        out = {c: pd.read_parquet(PANELS / f"{c}.parquet") for c in need}
        print(f"  panels: cached  {out['close'].shape}")
        return out
    files = sorted(CACHE.glob("*.parquet"))
    parts = []
    for n, f in enumerate(files, 1):
        d = pd.read_parquet(f)
        d["ts"] = pd.to_datetime(d["ts"])
        d["date"] = d["ts"].dt.normalize()
        d["lab"] = d["ts"].dt.strftime("%H:%M")
        d["sym"] = f.stem
        parts.append(d[["date", "lab", "sym"] + need])
        if n % 25 == 0 or n == len(files):
            print(f"    loaded {n}/{len(files)}", flush=True)
    long = pd.concat(parts, ignore_index=True)
    del parts
    out = {}
    for c in need:
        p = long.pivot_table(index=["date", "lab"], columns="sym", values=c)
        p.to_parquet(PANELS / f"{c}.parquet")
        out[c] = p
        print(f"    pivoted {c}", flush=True)
    return out


def at(panel: pd.DataFrame, lab: str) -> pd.DataFrame:
    return panel.xs(lab, level="lab")


def price_at(close: pd.DataFrame, hhmm: str) -> pd.DataFrame:
    """Price at wall-clock `hhmm` = close of the bar labelled hhmm-5min."""
    return at(close, EOD_L if hhmm == "EOD" else label_at(hhmm))


def summarise(d: pd.DataFrame, label: str, extra=""):
    if d is None or not len(d):
        print(f"  {label:<26} (none)")
        return None
    b = boot_days(d["spread"].to_numpy())
    if not b:
        print(f"  {label:<26} (thin)")
        return None
    qs = [bps(d[f"q{i}"].mean()) for i in range(1, 6) if f"q{i}" in d]
    print(f"  {label:<26}{len(d):>7,}" + "".join(f"{q:>8.1f}" for q in qs)
          + f"{bps(b['mean']):>9.2f}"
          + f"{f'[{bps(b[chr(108)+chr(111)]):+.1f},{bps(b[chr(104)+chr(105)]):+.1f}]':>19}"
          + f"{b['p_le0']:>8.3f}{d['ic'].mean():>9.4f}"
          + f"{100*(d['ic'] > 0).mean():>6.0f}%{extra}")
    return b


def head(indent="  "):
    print(f"{indent}{'config':<26}{'days':>7}"
          + "".join(f"{f'Q{i}':>8}" for i in range(1, 6))
          + f"{'T-B':>9}{'95% CI':>19}{'P(<=0)':>8}{'IC':>9}{'%IC>0':>7}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()

    print("=" * 122)
    print("IDIOSYNCRATIC_OVERNIGHT_GAP_INTRADAY")
    print("=" * 122)
    P = build_panels()
    close, opn, hi, lo, vol = (P["close"], P["open"], P["high"], P["low"], P["volume"])
    syms = list(close.columns)
    stocks = [s for s in syms if s not in NON_STOCK and s in SECTOR]
    dates = at(close, OPEN_L).index
    print(f"  tickers {len(syms)} | stocks {len(stocks)} | sessions {len(dates):,} "
          f"| {dates.min().date()} .. {dates.max().date()}")

    o930, o935 = at(opn, OPEN_L), at(opn, OPEN2_L)
    prev_close = at(close, EOD_L).shift(1)          # session shift, not calendar

    gap = o930 / prev_close - 1.0
    sec_gap = pd.DataFrame(
        {s: (o930[SECTOR[s]] / prev_close[SECTOR[s]] - 1.0) for s in stocks
         if SECTOR[s] in syms})
    mkt_gap = o930[MARKET] / prev_close[MARKET] - 1.0
    idio = gap[sec_gap.columns] - sec_gap
    stocks = list(idio.columns)
    print(f"  sector-adjustable stocks: {len(stocks)}  "
          f"(gap = 09:30 open / prior session 15:55 close - 1)")

    # forward returns from each execution reference
    fwd930, fwd935 = {}, {}
    for hh, _ in HORIZONS:
        pt = price_at(close, hh)
        fwd930[hh] = pt[stocks] / o930[stocks] - 1.0
        fwd935[hh] = pt[stocks] / o935[stocks] - 1.0

    # ── Stage A ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 122)
    print("STAGE A — signal at 09:30 open.  Q1 = most negative gap, Q5 = most positive")
    print("=" * 122)
    head()
    A = {}
    for name, sig in (("raw gap", gap[stocks]), ("idio (sector-adj)", idio)):
        for hh, _ in HORIZONS:
            d = daily_spread(sig, fwd930[hh])
            A[(name, hh)] = d
            summarise(d, f"{name} -> {hh}")
        print()

    # ── Stage B: executable 09:35 ───────────────────────────────────────────
    print("=" * 122)
    print("STAGE B — identical signal, executable 09:35 entry (spec §21, §22)")
    print("=" * 122)
    head()
    B = {}
    for hh, _ in HORIZONS:
        d = daily_spread(idio, fwd935[hh])
        B[hh] = d
        summarise(d, f"idio 09:35 -> {hh}")

    print("\n  09:30 vs 09:35 on the same signal (T-B bps):")
    print(f"    {'horizon':<10}{'09:30':>10}{'09:35':>10}{'lost in 5 min':>16}")
    for hh, _ in HORIZONS:
        a = A[("idio (sector-adj)", hh)]["spread"].mean()
        b = B[hh]["spread"].mean()
        print(f"    {hh:<10}{bps(a):>10.2f}{bps(b):>10.2f}{bps(a - b):>16.2f}")

    # ── §17 opening-response decomposition ──────────────────────────────────
    print("\n" + "=" * 122)
    print("OPENING RESPONSE — where does the move happen? (spec §17)")
    print("=" * 122)
    head()
    for label, a_, b_ in SEGMENTS:
        pa = o930[stocks] if a_ == OPEN_L else price_at(close, a_)[stocks]
        pb = price_at(close, b_)[stocks]
        summarise(daily_spread(idio, pb / pa - 1.0), f"idio seg {label}")

    # ── §12/§13 absolute magnitude and asymmetry ────────────────────────────
    print("\n" + "=" * 122)
    print("ABSOLUTE |idio gap| BINS — signed continuation return (spec §12, §13)")
    print("=" * 122)
    print("  positive gap: return as-is.  negative gap: return x -1.")
    print("  So POSITIVE here = continuation, NEGATIVE = reversal.\n")
    print(f"  {'bin':<14}{'side':<6}{'n':>9}" +
          "".join(f"{h:>11}" for h, _ in HORIZONS))
    gi = idio.stack().dropna()
    for lo_b, hi_b in ABS_BINS:
        for side in ("pos", "neg"):
            m = ((gi.abs() >= lo_b) & (gi.abs() < hi_b) &
                 ((gi > 0) if side == "pos" else (gi < 0)))
            sel = gi[m]
            if len(sel) < 200:
                continue
            cells = []
            for hh, _ in HORIZONS:
                f = fwd930[hh].stack().dropna().reindex(sel.index)
                sgn = 1.0 if side == "pos" else -1.0
                cells.append(f"{bps((sgn * f).mean()):>11.2f}")
            nm = f"{100*lo_b:.1f}-{100*hi_b:.1f}%" if hi_b < 9 else f">{100*lo_b:.0f}%"
            print(f"  {nm:<14}{side:<6}{len(sel):>9,}" + "".join(cells))

    # ── §23 controls ────────────────────────────────────────────────────────
    print("\n" + "=" * 122)
    print("CONTROLS (spec §23)")
    print("=" * 122)
    head()
    # Control A must be a NULL DISTRIBUTION, not one draw. A single shuffle
    # gave -4.26 bps here, roughly 3 sd from centre, which read as a real
    # effect and would have made the true signal look only half as strong as
    # it is. N draws, then place the observation against their spread.
    rng = np.random.default_rng(11)
    null = []
    for _ in range(N_SHUFFLE):
        sh = pd.DataFrame(rng.permuted(idio.to_numpy(), axis=1),
                          index=idio.index, columns=idio.columns)
        dd = daily_spread(sh, fwd930["EOD"])
        if len(dd):
            null.append(dd["spread"].mean())
    null = np.array(null)
    obs = A[("idio (sector-adj)", "EOD")]["spread"].mean()
    print(f"  A random shuffle, {len(null)} draws -> EOD: null mean "
          f"{bps(null.mean()):+.2f} bps  sd {bps(null.std()):.2f}  "
          f"95% [{bps(np.percentile(null, 2.5)):+.2f},"
          f"{bps(np.percentile(null, 97.5)):+.2f}]")
    print(f"    observed {bps(obs):+.2f} bps   "
          f"P(null <= observed) = {(null <= obs).mean():.4f}")
    prev_ret = (at(close, EOD_L)[stocks] / o930[stocks] - 1.0).shift(1)
    summarise(daily_spread(prev_ret, fwd930["EOD"]), "B prev-day return -> EOD")
    summarise(daily_spread(sec_gap[stocks], fwd930["EOD"]), "C sector gap only -> EOD")
    summarise(daily_spread(gap[stocks], fwd930["EOD"]), "  (raw gap, reference)")

    # ── §11 legs, §20 costs, §21 slippage, §28 breadth ──────────────────────
    print("\n" + "=" * 122)
    print("LEGS, COSTS AND BREADTH — idio signal, 09:30 (spec §11, §20, §21, §28)")
    print("=" * 122)
    print("  Cost = 4 x per-side bps (two legs, opened and closed).")
    print(f"\n  {'horizon':<9}{'gross':>9}{'posleg':>9}{'negleg':>9}"
          f"{'net@2':>9}{'net@5':>9}{'+5slip':>9}{'+10slip':>9}"
          f"{'win%':>7}{'p5':>9}{'p50':>9}{'p95':>9}{'skew':>7}")
    for hh, _ in HORIZONS:
        d = A[("idio (sector-adj)", hh)]
        g = bps(d["spread"].mean())
        n2 = g - 4 * COST_SIDES[0]
        print(f"  {hh:<9}{g:>9.2f}{bps(d['long_leg'].mean()):>9.2f}"
              f"{bps(d['short_leg'].mean()):>9.2f}"
              f"{n2:>9.2f}{g - 4 * COST_SIDES[1]:>9.2f}"
              f"{n2 - 2 * OPEN_SLIP[1]:>9.2f}{n2 - 2 * OPEN_SLIP[2]:>9.2f}"
              f"{100*(d['spread'] > 0).mean():>6.0f}%"
              f"{bps(d['spread'].quantile(.05)):>9.1f}"
              f"{bps(d['spread'].median()):>9.1f}"
              f"{bps(d['spread'].quantile(.95)):>9.1f}{d['spread'].skew():>7.2f}")

    # ── §14/§15/§16/§19 conditioning ────────────────────────────────────────
    print("\n" + "=" * 122)
    print("CONDITIONING — diagnostic only (spec §14, §15, §16, §19)")
    print("=" * 122)
    dEOD = A[("idio (sector-adj)", "EOD")].set_index("date")
    ms = pd.cut(mkt_gap.reindex(dEOD.index), [-9, -0.005, 0.005, 9],
                labels=["mkt down", "flat", "mkt up"])
    print("  market overnight gap: " + "  ".join(
        f"{k}:{bps(v):+.1f}" for k, v in
        dEOD.groupby(ms, observed=True)["spread"].mean().items()))

    # sector confirmation vs divergence, and prior-day interaction: stock level
    gs = gap[stocks].stack().dropna()
    ss = sec_gap[stocks].stack().dropna().reindex(gs.index)
    fe = fwd930["EOD"].stack().dropna().reindex(gs.index)
    pr = prev_ret.stack().dropna().reindex(gs.index)
    sgn = np.sign(gs)
    conf = (np.sign(gs) == np.sign(ss))
    div = (gs - ss).abs() >= DIVERGENCE
    print(f"\n  sector confirm/divergence (signed continuation return to EOD, "
          f"threshold |stock-sector| >= {DIVERGENCE:.0%}):")
    for nm, m in (("confirmed", conf), ("opposite sector", ~conf),
                  ("strong idio", div), ("weak idio", ~div)):
        v = (sgn * fe)[m]
        print(f"    {nm:<18}{len(v):>9,}  {bps(v.mean()):>+8.2f} bps")
    print("\n  prior-day x overnight (signed continuation to EOD):")
    for pn, pm in (("prior up", pr > 0), ("prior down", pr <= 0)):
        for gn, gm in (("gap +", gs > 0), ("gap -", gs < 0)):
            v = (sgn * fe)[pm & gm]
            if len(v) > 200:
                print(f"    {pn:<11}{gn:<7}{len(v):>9,}  {bps(v.mean()):>+8.2f} bps")

    # RVOL on the opening 30 minutes
    ovol = vol.loc[(slice(None), ["09:30", "09:35", "09:40", "09:45", "09:50", "09:55"]), :]
    ovol = ovol.groupby(level="date").sum()[stocks]
    rv = ovol / ovol.rolling(20).mean().shift(1)
    rvs = rv.stack().dropna().reindex(gs.index)
    tb = pd.qcut(rvs.dropna(), 3, labels=["low", "mid", "high"])
    print("\n  opening-30m RVOL tercile (signed continuation to EOD):")
    for k in ("low", "mid", "high"):
        v = (sgn * fe)[tb[tb == k].index]
        print(f"    {k:<6}{len(v):>9,}  {bps(v.mean()):>+8.2f} bps")

    # ── §18 gap-fill descriptive ────────────────────────────────────────────
    print("\n" + "=" * 122)
    print("GAP-FILL — descriptive only, never used as a target (spec §18)")
    print("=" * 122)
    day_lo = lo.groupby(level="date").min()[stocks]
    day_hi = hi.groupby(level="date").max()[stocks]
    pc = prev_close[stocks]
    filled = np.where(gs > 0,
                      day_lo.stack().dropna().reindex(gs.index) <= pc.stack().dropna().reindex(gs.index),
                      day_hi.stack().dropna().reindex(gs.index) >= pc.stack().dropna().reindex(gs.index))
    filled = pd.Series(filled, index=gs.index)
    print(f"  gap-fill probability overall: {100*filled.mean():.1f}%  (n={len(filled):,})")
    for lo_b, hi_b in ABS_BINS:
        m = (gs.abs() >= lo_b) & (gs.abs() < hi_b)
        if m.sum() < 200:
            continue
        nm = f"{100*lo_b:.1f}-{100*hi_b:.1f}%" if hi_b < 9 else f">{100*lo_b:.0f}%"
        v = (sgn * fe)[m]
        print(f"    |gap| {nm:<12} fill {100*filled[m].mean():>5.1f}%   "
              f"signed EOD {bps(v.mean()):>+7.2f} bps")

    # ── §25/§26/§27/§29 ─────────────────────────────────────────────────────
    print("\n" + "=" * 122)
    print("YEAR / TICKER / SECTOR / TAILS (spec §25-§29)")
    print("=" * 122)
    for hh in ("11:00", "EOD"):
        d = A[("idio (sector-adj)", hh)].set_index("date")
        ys = d.groupby(d.index.year)["spread"].agg(["size", "mean"])
        print(f"  {hh:<6} year: " + "  ".join(
            f"{y}:{bps(r['mean']):+.1f}({int(r['size'])})" for y, r in ys.iterrows()))
    d = A[("idio (sector-adj)", "EOD")]
    cnt = {}
    for row in list(d["top_names"]) + list(d["bot_names"]):
        for s in row.split("|"):
            cnt[s] = cnt.get(s, 0) + 1
    vc = pd.Series(cnt).sort_values(ascending=False)
    tot = vc.sum()
    print(f"\n  ticker concentration in buckets: top5 {100*vc.head(5).sum()/tot:.1f}%  "
          f"top10 {100*vc.head(10).sum()/tot:.1f}%   "
          f"({', '.join(vc.head(5).index)})")
    for side in ("top_names", "bot_names"):
        sc = {}
        for row in d[side]:
            for s in row.split("|"):
                if s in SECTOR:
                    sc[SECTOR[s]] = sc.get(SECTOR[s], 0) + 1
        t = sum(sc.values()) or 1
        mx = max(sc, key=sc.get)
        print(f"  sector weight {side.replace('_names',''):<4}: max {mx} "
              f"{100*sc[mx]/t:.1f}%   "
              + " ".join(f"{k}:{100*v/t:.0f}%" for k, v in
                         sorted(sc.items(), key=lambda x: -x[1])[:5]))
    print(f"\n  extreme-bucket outcome tails (idio EOD, daily T-B):")
    s = d["spread"]
    print("    " + "  ".join(f"p{int(q*100)}:{bps(s.quantile(q)):+.0f}"
                             for q in (.01, .05, .10, .90, .95, .99)))
    print("=" * 122)


if __name__ == "__main__":
    main()
