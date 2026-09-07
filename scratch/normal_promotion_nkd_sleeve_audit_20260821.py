"""
scratch/normal_promotion_nkd_sleeve_audit_20260821.py - NKD treated as its own
sleeve. Scratch / read-only; no production file is written or modified.

Four questions, in the order that decides them:

 1. FILL. Does the engine as it stands today book NKD exits at prices that never
    traded, and what does fixing that cost? Compares three NKD books for the same
    window: production-as-is, post-hoc corrected, and engine-fixed. The last two
    must agree trade-for-trade - that extends the equivalence proof, which was
    only run on 2026, to every window.

 2. SLIPPAGE. MNKD is a $0.50-per-point contract with a 5-point tick, so one tick
    is $2.50 and the round-turn cost moves $5.00 for every extra tick per side.
    Slippage in this engine is a flat per-round-turn dollar subtraction and does
    not touch prices or signals, so the stress is exact, not a re-simulation.
    Reported against measured book depth at the actual entry and exit bars.

 3. ALPHA. Day / week / month cluster bootstrap on the floor window, which is the
    only window allowed to select. Two numbers, kept apart: the uncentred interval
    of the total, and a properly CENTRED test of H0 "mean = 0". A bootstrap that
    is not centred answers a different question and overstates significance.

 4. CONCENTRATION. Drop the single best month, then the best two, and see what
    survives.

    python scratch/normal_promotion_nkd_sleeve_audit_20260821.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

WINDOWS = ["floor", "vault2025", "vault2026"]
OLD_DUMP = "scratch/normal_sleeve_trades_{}_20260821.json"      # booked / corrected
NEW_DUMP = "scratch/normal_promotion_trades_{}_20260821.json"   # engine-fixed
N_BOOT = 20000
SEED = 20260821


def load(path: str):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pnl(trades) -> float:
    return float(sum(float(t["pnl"]) for t in trades))


def key(t) -> tuple:
    return (str(t["day"]), str(t["exit_day"]), str(t.get("entry_time")),
            str(t.get("exit_time")), str(t["direction"]))


# ---------------------------------------------------------------------------
# 3/4. bootstrap
# ---------------------------------------------------------------------------
def cluster_sums(trades, how: str) -> np.ndarray:
    """Aggregate trade P&L into clusters so overlapping holds cannot be resampled
    as if independent. Clustering is on the ENTRY day, which is when the position
    is committed."""
    buckets = {}
    for t in trades:
        d = pd.Timestamp(t["day"]).normalize()
        if how == "day":
            k = d
        elif how == "week":
            iso = d.isocalendar()
            k = (int(iso[0]), int(iso[1]))
        elif how == "month":
            k = (d.year, d.month)
        else:
            raise ValueError(how)
        buckets[k] = buckets.get(k, 0.0) + float(t["pnl"])
    return np.array([buckets[k] for k in sorted(buckets, key=str)], dtype=float)


def bootstrap(vals: np.ndarray, rng) -> dict:
    """Two separate things, deliberately not blended.

    interval  resample the observed values, look at where the TOTAL lands. This
              describes the sample; it is not a test.
    p_centred resample the values after subtracting their mean, so the resampled
              world genuinely has mean zero, and ask how often it produces a total
              at least as extreme as the one observed. This is the test.
    """
    n = len(vals)
    if n == 0:
        return dict(n=0)
    obs = float(vals.sum())
    draws = rng.choice(vals, size=(N_BOOT, n), replace=True).sum(axis=1)
    centred = vals - vals.mean()
    cdraws = rng.choice(centred, size=(N_BOOT, n), replace=True).sum(axis=1)
    return dict(n=n, observed=obs, mean_cluster=float(vals.mean()),
                p5=float(np.percentile(draws, 5)), p50=float(np.percentile(draws, 50)),
                p95=float(np.percentile(draws, 95)),
                frac_positive=float((draws > 0).mean()),
                p_centred=float((np.abs(cdraws) >= abs(obs)).mean()))


def drop_best_months(trades, k: int):
    by = {}
    for t in trades:
        d = pd.Timestamp(t["day"]).normalize()
        by.setdefault((d.year, d.month), []).append(t)
    order = sorted(by, key=lambda m: -sum(float(t["pnl"]) for t in by[m]))
    drop = set(order[:k])
    kept = [t for m, lst in by.items() if m not in drop for t in lst]
    return kept, [(m, round(sum(float(t["pnl"]) for t in by[m]))) for m in order[:k]]


# ---------------------------------------------------------------------------
# 2. slippage / depth
# ---------------------------------------------------------------------------
def depth_at_bars(trades, ndf: pd.DataFrame) -> dict:
    """Contracts actually printed in the bars this sleeve claims to trade at."""
    idx = ndf.index
    vol = ndf["volume"].to_numpy()

    def _norm(ts):
        t = pd.Timestamp(ts)
        if t.tz is None and idx.tz is not None:
            t = t.tz_localize(idx.tz)
        elif t.tz is not None and idx.tz is None:
            t = t.tz_localize(None)
        return t

    entry_5m, exit_1m = [], []
    for t in trades:
        et, xt = t.get("entry_time"), t.get("exit_time")
        if et:
            a = _norm(et)
            lo = idx.searchsorted(a, "left")
            hi = idx.searchsorted(a + pd.Timedelta(minutes=5), "left")
            if hi > lo:
                entry_5m.append(float(vol[lo:hi].sum()))
        if xt:
            j = idx.get_indexer([_norm(xt)])[0]
            if j >= 0:
                exit_1m.append(float(vol[j]))
    def q(a):
        a = np.array(a, dtype=float)
        if not len(a):
            return {}
        return {"n": int(len(a)), "p10": float(np.percentile(a, 10)),
                "median": float(np.median(a)), "p90": float(np.percentile(a, 90))}
    return {"entry_bar_5m_contracts": q(entry_5m), "exit_bar_1m_contracts": q(exit_1m)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scratch/normal_promotion_nkd_sleeve_audit_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_promotion_nkd_sleeve_audit_20260821.json")
    a = ap.parse_args()

    from global_index import specs as gi_specs
    from global_index._core import load_parquet as gi_load

    rng = np.random.default_rng(SEED)
    report, results = [], {}

    def emit(s=""):
        print(s, flush=True)
        report.append(s)

    c = gi_specs.SPECS["MNKD"]
    tick_value = c.tick * c.point_value
    emit("=" * 112)
    emit("NKD AS ITS OWN SLEEVE - PROMOTION AUDIT   (scratch / read-only)")
    emit("=" * 112)
    emit("MNKD: point_value ${:g}/pt, tick {:g} pts -> one tick = ${:.2f}. Baseline 2 ticks/side"
         .format(c.point_value, c.tick, tick_value))
    emit("= ${:.2f} slippage + ${:.2f} commission = ${:.2f} per round turn."
         .format(4 * tick_value, c.commission_rt, 4 * tick_value + c.commission_rt))
    emit("")

    # ---------------- 1. fill ----------------
    emit("#" * 112)
    emit("1. FILL - production-as-is vs post-hoc corrected vs engine-fixed")
    emit("#" * 112)
    emit("  {:<11} {:>7} {:>12} {:>12} {:>12} {:>10} {:>22}".format(
        "window", "trades", "prod-as-is$", "posthoc$", "enginefix$", "cost$",
        "posthoc==enginefix?"))
    fill = {}
    for w in WINDOWS:
        old, new = load(OLD_DUMP.format(w)), load(NEW_DUMP.format(w))
        if not old or not new:
            emit("  {:<11} missing dump - run the regen audit first".format(w))
            continue
        nkd = old["nkd_instrument"]
        booked, corr = old["booked"][nkd], old["corrected"][nkd]
        fixed = new["raw"][nkd]
        same = ([key(t) for t in corr] == [key(t) for t in fixed]
                and all(abs(float(x["pnl"]) - float(y["pnl"])) < 0.02
                        for x, y in zip(corr, fixed)))
        fill[w] = dict(trades=len(fixed), prod=pnl(booked), posthoc=pnl(corr),
                       enginefix=pnl(fixed), equivalent=bool(same))
        emit("  {:<11} {:>7} {:>12,.0f} {:>12,.0f} {:>12,.0f} {:>10,.2f} {:>22}".format(
            w, len(fixed), pnl(booked), pnl(corr), pnl(fixed),
            pnl(booked) - pnl(fixed), "PASS" if same else "FAIL"))
    emit("")
    emit("  'prod-as-is' is what the engine in the repo right now would book: the gap-through")
    emit("  test still demands a >15-minute time break, so a stop stepped over between two")
    emit("  adjacent 1-minute bars fills at the untraded stop level. 'cost' is the overstatement.")
    emit("")

    # ---------------- 2. slippage + depth ----------------
    emit("#" * 112)
    emit("2. SLIPPAGE STRESS AND MEASURED DEPTH")
    emit("#" * 112)
    slip = {}
    for w in WINDOWS:
        new = load(NEW_DUMP.format(w))
        if not new:
            continue
        nkd = new["nkd_instrument"]
        trades = new["raw"][nkd]
        base = pnl(trades)
        n = len(trades)
        rows = []
        for ticks in (2, 3, 4, 5, 6):
            extra = (ticks - 2) * 2 * tick_value * n
            rows.append((ticks, base - extra))
        slip[w] = dict(n=n, base=base, ladder={t: v for t, v in rows})
        emit("  {:<11} {} trades | net at ticks/side: {}".format(
            w, n, "  ".join("{}t ${:,.0f}".format(t, v) for t, v in rows)))
    emit("")
    emit("  breakeven slippage (ticks/side at which the sleeve's net reaches zero):")
    for w, s in slip.items():
        if s["n"]:
            be = 2 + s["base"] / (2 * tick_value * s["n"])
            emit("    {:<11} {:.2f} ticks/side".format(w, be))
    emit("")

    depth = {}
    for w in WINDOWS:
        new = load(NEW_DUMP.format(w))
        if not new:
            continue
        nkd = new["nkd_instrument"]
        parq = new["argv"][new["argv"].index("--nkd-parquet") + 1]
        ndf = gi_load(parq)
        ndf.index = ndf.index.tz_convert(c.session_tz)
        if "--start" in new["argv"]:
            ts = pd.Timestamp(new["argv"][new["argv"].index("--start") + 1]).tz_localize(ndf.index.tz)
            ndf = ndf[ndf.index >= ts]
        if "--end" in new["argv"]:
            ts = pd.Timestamp(new["argv"][new["argv"].index("--end") + 1]).tz_localize(ndf.index.tz)
            ndf = ndf[ndf.index <= ts]
        d = depth_at_bars(new["raw"][nkd], ndf)
        depth[w] = d
        e5, x1 = d["entry_bar_5m_contracts"], d["exit_bar_1m_contracts"]
        emit("  {:<11} entry 5m bar contracts p10/med/p90 = {}/{}/{}  |  "
             "exit 1m bar contracts p10/med/p90 = {}/{}/{}".format(
                 w, int(e5.get("p10", 0)), int(e5.get("median", 0)), int(e5.get("p90", 0)),
                 int(x1.get("p10", 0)), int(x1.get("median", 0)), int(x1.get("p90", 0))))
        del ndf
    emit("")

    # ---------------- 3/4. alpha and concentration ----------------
    emit("#" * 112)
    emit("3. DIRECT ALPHA - cluster bootstrap  (floor is the ONLY window allowed to select)")
    emit("#" * 112)
    boot = {}
    for w in WINDOWS:
        new = load(NEW_DUMP.format(w))
        if not new:
            continue
        nkd = new["nkd_instrument"]
        trades = new["raw"][nkd]
        emit("  {} - {} trades, net ${:,.0f}".format(w, len(trades), pnl(trades)))
        emit("    {:<7} {:>8} {:>11} {:>11} {:>11} {:>11} {:>10}".format(
            "cluster", "n", "observed$", "p5$", "p50$", "p95$", "p(centred)"))
        boot[w] = {}
        for how in ("day", "week", "month"):
            v = cluster_sums(trades, how)
            b = bootstrap(v, rng)
            boot[w][how] = b
            emit("    {:<7} {:>8} {:>11,.0f} {:>11,.0f} {:>11,.0f} {:>11,.0f} {:>10.3f}".format(
                how, b["n"], b["observed"], b["p5"], b["p50"], b["p95"], b["p_centred"]))
        emit("")
    emit("  p(centred) is the bootstrap test of H0 'mean cluster P&L = 0'. The p5..p95 band is")
    emit("  a description of the sample, not a test - a band that clears zero while p(centred)")
    emit("  does not is the ordinary signature of an uncentred bootstrap, not evidence.")
    emit("")

    emit("#" * 112)
    emit("4. CONCENTRATION - drop the best months")
    emit("#" * 112)
    conc = {}
    for w in WINDOWS:
        new = load(NEW_DUMP.format(w))
        if not new:
            continue
        nkd = new["nkd_instrument"]
        trades = new["raw"][nkd]
        row = {"full": pnl(trades)}
        parts = []
        for k in (1, 2):
            kept, dropped = drop_best_months(trades, k)
            row["drop{}".format(k)] = pnl(kept)
            parts.append("drop {} -> ${:,.0f}  (removed {})".format(
                k, pnl(kept), ", ".join("{}-{:02d} ${:,}".format(m[0], m[1], v)
                                        for m, v in dropped)))
        conc[w] = row
        emit("  {:<11} full ${:,.0f} | {}".format(w, row["full"], " | ".join(parts)))
    emit("")

    results = dict(fill=fill, slippage=slip, depth=depth, bootstrap=boot, concentration=conc,
                   tick_value=tick_value, n_boot=N_BOOT, seed=SEED)
    Path(a.out).write_text("\n".join(report) + "\n", encoding="utf-8")
    Path(a.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print("\nwrote " + a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
