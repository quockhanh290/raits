"""
overnight_explore.py — characterize the Globex OVERNIGHT session (read-only)
===========================================================================
Before designing ANY overnight strategy, answer the cheap question first:
**is there tradeable structure in the ~17h outside RTH at all?**

This does NOT trade. It measures the overnight session so we know whether it
is worth building a strategy for — the same "characterize before you build"
discipline that killed NORMAL_MID early.

Sessions (US/Eastern):
    RTH         09:30–16:00
    Overnight   18:00 (prev) → 09:30 (next), split into
        Asia      18:00–02:00
        Europe    02:00–08:00
        Premarket 08:00–09:30

What it reports
    1. Range: overnight range vs RTH range (is there enough movement?).
    2. Where the movement is: mean |return| per sub-window.
    3. Momentum vs mean-reversion: does an earlier window's direction CONTINUE
       into the next (tradeable, like TF/STRESS_MID) or REVERSE (different game)?
       - corr(Asia ret, Europe ret), corr(Europe ret, Premarket ret),
         corr(overnight ret, RTH-open continuation).
    4. Activity by ET hour (which hours actually move).

Usage
    python overnight_explore.py --parquet NQ_8y.parquet
    python overnight_explore.py --parquet ES_8y.parquet --point-value 5
"""
from __future__ import annotations

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))


def session_of(t: dtime) -> str:
    if dtime(9, 30) <= t < dtime(16, 0):
        return "RTH"
    if dtime(18, 0) <= t or t < dtime(2, 0):
        return "Asia"
    if dtime(2, 0) <= t < dtime(8, 0):
        return "Europe"
    if dtime(8, 0) <= t < dtime(9, 30):
        return "Premarket"
    return "Gap"          # 16:00–18:00 maintenance/thin


def ret(series: pd.Series) -> float:
    s = series.dropna()
    if len(s) < 2 or s.iloc[0] == 0:
        return np.nan
    return float(s.iloc[-1] / s.iloc[0] - 1.0)


def main():
    ap = argparse.ArgumentParser(description="Characterize the overnight session (read-only).")
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--point-value", type=float, default=2.0)
    a = ap.parse_args()

    import gate2_edge_harness as G
    df = G.load_parquet(a.parquet)
    et = df.tz_convert("America/New_York") if df.index.tz else df.tz_localize("UTC").tz_convert("America/New_York")
    et = et.copy()
    et["t"] = et.index.time
    et["sess"] = [session_of(t) for t in et["t"]]
    # "trading day" = the RTH date a bar leads into: overnight bars (>=18:00) belong to NEXT day
    nd = et.index.normalize()
    is_evening = np.array([t >= dtime(18, 0) for t in et["t"]])
    et["tday"] = pd.DatetimeIndex(np.where(is_evening, nd + pd.Timedelta(days=1), nd)).tz_localize(None).normalize()

    print(f"\n{'='*64}\nOVERNIGHT SESSION CHARACTERIZATION | {Path(a.parquet).name}\n{'='*64}")
    print(f"Span {et.index[0].date()} → {et.index[-1].date()}")

    # ── per trading-day session aggregates ───────────────────────────────────
    rows = []
    for tday, g in et.groupby("tday"):
        rec = {"tday": tday}
        for s in ["Asia", "Europe", "Premarket", "RTH"]:
            sub = g[g["sess"] == s]
            if len(sub) >= 2:
                rec[f"{s}_rng"] = float(sub["high"].max() - sub["low"].min())
                rec[f"{s}_ret"] = ret(sub["close"])
                rec[f"{s}_lvl"] = float(sub["close"].iloc[-1])
            else:
                rec[f"{s}_rng"] = np.nan; rec[f"{s}_ret"] = np.nan; rec[f"{s}_lvl"] = np.nan
        rows.append(rec)
    d = pd.DataFrame(rows).set_index("tday").sort_index()
    d["overnight_rng"] = d[["Asia_rng", "Europe_rng", "Premarket_rng"]].sum(axis=1, min_count=1)

    # ── 1. range: overnight vs RTH ───────────────────────────────────────────
    rr = (d["overnight_rng"] / d["RTH_rng"]).replace([np.inf, -np.inf], np.nan).dropna()
    print("\n[1] RANGE  overnight vs RTH (in index points)")
    print(f"    median overnight range = {d['overnight_rng'].median():.1f} pts | "
          f"median RTH range = {d['RTH_rng'].median():.1f} pts")
    print(f"    overnight is {rr.median()*100:.0f}% of RTH range (median)  "
          f"→ {'enough to trade' if rr.median() > 0.4 else 'thin vs RTH'}")

    # ── 2. where the movement is ─────────────────────────────────────────────
    print("\n[2] MOVEMENT BY SUB-WINDOW (mean |return|, bps)")
    for s in ["Asia", "Europe", "Premarket", "RTH"]:
        v = d[f"{s}_ret"].abs().mean() * 1e4
        print(f"    {s:<10} {v:>6.1f} bps")

    # ── 3. momentum vs mean-reversion ────────────────────────────────────────
    print("\n[3] CONTINUATION TEST  (corr > 0 = momentum/tradeable, < 0 = mean-revert)")
    def corr(x, y):
        m = d[[x, y]].dropna()
        return float(m[x].corr(m[y])) if len(m) > 30 else np.nan
    c_ae = corr("Asia_ret", "Europe_ret")
    c_ep = corr("Europe_ret", "Premarket_ret")
    c_on_rth = corr("Premarket_ret", "RTH_ret")
    print(f"    Asia → Europe       corr {c_ae:+.3f}")
    print(f"    Europe → Premarket  corr {c_ep:+.3f}")
    print(f"    Premarket → RTH     corr {c_on_rth:+.3f}")

    # ── 4. activity by ET hour ───────────────────────────────────────────────
    et["minret"] = et["close"].pct_change().abs()
    byhour = et.groupby(et.index.hour)["minret"].mean() * 1e4
    print("\n[4] ACTIVITY BY ET HOUR (mean |1-min return|, bps) — top movers")
    top = byhour.sort_values(ascending=False).head(8)
    for h, v in top.items():
        tag = session_of(dtime(h, 0))
        print(f"    {h:02d}:00 ET  {v:>5.2f} bps  [{tag}]")

    # ── read ─────────────────────────────────────────────────────────────────
    print("\n" + "-" * 64)
    enough = rr.median() > 0.4
    momentum = (np.nanmean([c_ae, c_ep]) > 0.05)
    if enough and momentum:
        print("READ: overnight has decent range AND positive continuation →")
        print("      worth designing an overnight momentum strategy (then gate it).")
    elif enough and not momentum:
        print("READ: overnight moves but does NOT continue (corr≈0 or negative) →")
        print("      momentum logic (TF/STRESS_MID style) likely won't work overnight.")
        print("      Mean-reversion or news-driven only — different game, higher risk.")
    else:
        print("READ: overnight range too thin vs RTH → little to trade. Likely a dead end.")
    print("      (This only characterizes; any real strategy still needs Gates 2–5.)")
    print("-" * 64 + "\n")


if __name__ == "__main__":
    main()
