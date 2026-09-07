"""
HOD_BREAKOUT_FORWARD_DRIFT — does the 15-minute signal keep paying?
(RESEARCH ONLY. Reads the local cache; modifies no production code.)

THE ONE QUESTION (spec §2)
--------------------------
The HOD_CONSOLIDATION_BREAKOUT trigger showed real but tiny directional
information at 15 minutes: +1.15 bps on 1-minute bars, against a 4-10 bps
round-trip cost hurdle. This measures the SHAPE of that drift as the horizon
extends — decay, plateau, fat tail, broad drift, or reversal (spec §24).

WHY THIS RUNS ON 5-MINUTE BARS
------------------------------
The 1-minute data on disk stops at 10:44 ET, so it cannot observe +30m, let
alone EOD. Buying the missing session for the full 314-name universe costs
$183; an 80-name sample costs $45, which is the entire remaining budget and
would also gut the ticker-concentration analysis (spec §18) that this study
needs.

The 5-minute cache already covers the full session, six years and all three
buckets, for $0. Its LEVEL is not comparable — the same trigger measured
+0.10 bps at 15m there against +1.15 bps at 1-minute, an order of magnitude
apart, because a "5-bar consolidation" is 25 minutes rather than 5. But the
SHAPE — the ratio of drift at 60m to drift at 15m — is what spec §24 asks for,
and ratios survive a level difference that levels do not.

Read every absolute number here as indicative only. The classification is the
deliverable.

SIGNAL IS LOCKED (spec §1, §23)
-------------------------------
CORE, MAX_RISK_PCT, BUFFER, the cooldown and prepare() are IMPORTED from
hod_consolidation_breakout_test.py rather than restated, so they cannot drift.
The forward-measurement code is new, so --verify-signal re-runs the original
scan on a sample and asserts this module produces an identical event set
(timestamp, direction, group). If the trigger changed, that check fails.

CENSORING (spec §17) — no silent truncation
-------------------------------------------
Every horizon uses only signals with that many bars remaining in the SAME
session. A 120-minute figure therefore excludes late-session signals, and the
eligible n is reported per horizon. Missing horizons are never backfilled with
EOD; that would silently mix two definitions.

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\hod_breakout_forward_drift.py --verify-signal
    python raits\\raits\\scripts\\research\\hod_breakout_forward_drift.py
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

from hod_consolidation_breakout_test import (          # noqa: E402
    CORE, MAX_RISK_PCT, BUFFER, PER_TICKER_5M, WORK, BUCKETS,
    prepare, cooldown_bars, scan as scan_original,
)

# 5-minute bars: horizon in MINUTES -> bars.
HORIZONS = [(5, 1), (10, 2), (15, 3), (30, 6), (45, 9),
            (60, 12), (90, 18), (120, 24)]
HMAX = max(b for _, b in HORIZONS)
R_LEVELS = (0.5, 1.0, 1.5, 2.0, 3.0)
PCT_LEVELS = (0.25, 0.50, 1.00)

# C2 is ~96% of all events and is only ever used as a control mean. Keeping
# every one costs memory for no precision that matters; every Nth is kept,
# deterministically (no outcome involved in the choice). Subsampling widens
# the control's interval, which can only make TREATED look WORSE, never better.
C2_KEEP_EVERY = 10

EVENTS = WORK / "hod_fwd_events_5min.parquet"


def scan_forward(g: pd.DataFrame, cfg: dict) -> list:
    """Same trigger as scan_original; measures far more of the future.

    The trigger block below is a literal transcription of the locked version.
    --verify-signal asserts the two produce identical event sets.
    """
    nb, rng_max, hod_tol, vmult = (cfg["cons_bars"], cfg["max_range"],
                                   cfg["hod"], cfg["vol_mult"])
    CD = cooldown_bars("5min")
    o, h, l, c = (g["open"].values, g["high"].values,
                  g["low"].values, g["close"].values)
    v, hod, lod = g["volume"].values, g["hod"].values, g["lod"].values
    date, ts, bod = g["date"].values, g["ts"].values, g["bod"].values
    sym = g["symbol"].iloc[0]
    n = len(g)
    out = []
    last_signal = {"LONG": -10**9, "SHORT": -10**9}
    last_level = {"LONG": None, "SHORT": None}
    c2n = 0

    # Last bar index of each session, for the EOD horizon.
    eod_of = {}
    for k in range(n):
        eod_of[date[k]] = k

    # Identical bound to the locked scanner (it used n - max(marks) - 2 with
    # marks maxing at 3). Detection must match exactly; horizon censoring is
    # applied later, per spec §17, not by narrowing the event set here.
    for i in range(2 * nb + 1, n - 5):
        s0, s1 = i - nb, i
        if date[s0] != date[i] or bod[i] < nb + 3:
            continue
        ch, cl = h[s0:s1].max(), l[s0:s1].min()
        mid = 0.5 * (ch + cl)
        if mid <= 0:
            continue
        width = (ch - cl) / mid
        if width > rng_max:
            continue
        cvol = v[s0:s1].mean()
        p0 = s0 - nb
        if p0 < 0 or date[p0] != date[i]:
            continue
        pvol = v[p0:s0].mean()
        if not (cvol > 0 and pvol > 0 and cvol < pvol):
            continue

        for direction in ("LONG", "SHORT"):
            if direction == "LONG":
                ref = hod[i]
                if not np.isfinite(ref) or ref <= 0:
                    continue
                if (ref - c[i - 1]) / ref > hod_tol:
                    continue
                broke = c[i] > ch and c[i] >= ref * (1 - 0.0005) and c[i] > o[i]
                entry = o[i + 1]
                risk = entry - cl * (1 - BUFFER)
            else:
                ref = lod[i]
                if not np.isfinite(ref) or ref <= 0:
                    continue
                if (c[i - 1] - ref) / ref > hod_tol:
                    continue
                broke = c[i] < cl and c[i] <= ref * (1 + 0.0005) and c[i] < o[i]
                entry = o[i + 1]
                risk = ch * (1 + BUFFER) - entry
            if risk <= 0 or risk / entry > MAX_RISK_PCT:
                continue

            vol_ok = v[i] > vmult * cvol
            group = ("TREATED" if (broke and vol_ok)
                     else "C1_volfail" if broke else "C2_nobreak")
            if group == "TREATED":
                lvl = last_level[direction]
                cooled = (i - last_signal[direction]) >= CD
                re_entered = lvl is None or (
                    (l[i] <= lvl) if direction == "LONG" else (h[i] >= lvl))
                if not (cooled or re_entered):
                    continue
                last_signal[direction] = i
                last_level[direction] = ch if direction == "LONG" else cl
            elif group == "C2_nobreak":
                c2n += 1
                if c2n % C2_KEEP_EVERY:
                    continue

            # ── forward measurement ─────────────────────────────────────────
            # Entry is the OPEN of bar i+1, so bar i+1 is the first bar of
            # exposure and its high/low count. Measuring from i+2 would skip
            # the entry bar's own excursion — the locked scanner starts at
            # j = i + 1, and this must match it.
            last = eod_of[date[i]]
            avail = last - i                # bars of exposure inside the session
            if avail < 1:
                continue
            sgn = 1.0 if direction == "LONG" else -1.0
            sret, mfe, mae = {}, {}, {}
            hi = lo = 0.0
            t_r = {L: 0 for L in R_LEVELS}
            t_stop = {0.5: 0, 1.0: 0}
            t_pct = {P: 0 for P in PCT_LEVELS}
            best, worst, t_best, t_worst = 0.0, 0.0, 0, 0
            for k in range(1, avail + 1):
                j = i + k
                fav = sgn * ((h[j] if direction == "LONG" else l[j]) - entry)
                adv = sgn * ((l[j] if direction == "LONG" else h[j]) - entry)
                fr, ar = fav / risk, adv / risk
                if fr > hi:
                    hi, t_best = fr, k
                if ar < lo:
                    lo, t_worst = ar, k
                best, worst = hi, lo
                for L in R_LEVELS:
                    if not t_r[L] and hi >= L:
                        t_r[L] = k
                for L in (0.5, 1.0):
                    if not t_stop[L] and lo <= -L:
                        t_stop[L] = k
                pf = 100.0 * sgn * ((h[j] if direction == "LONG" else l[j]) - entry) / entry
                for P in PCT_LEVELS:
                    if not t_pct[P] and pf >= P:
                        t_pct[P] = k
                if k <= HMAX:
                    mfe[k], mae[k] = hi, lo
                    sret[k] = 100.0 * sgn * (c[j] - entry) / entry
            eod_ret = 100.0 * sgn * (c[last] - entry) / entry
            nan = np.nan
            rec = [sym, ts[i], date[i], direction, group, float(entry),
                   100.0 * risk / entry, 100.0 * width, int(avail)]
            for _, b in HORIZONS:
                rec += [sret.get(b, nan), mfe.get(b, nan), mae.get(b, nan)]
            rec += [eod_ret, best, worst, t_best, t_worst]
            rec += [t_r[L] for L in R_LEVELS]
            rec += [t_stop[0.5], t_stop[1.0]]
            rec += [t_pct[P] for P in PCT_LEVELS]
            out.append(tuple(rec))
    return out


COLS = (["symbol", "ts", "date", "direction", "group", "entry",
         "risk_pct", "width_pct", "avail"]
        + [f"{k}{m}" for m, _ in HORIZONS for k in ("sret", "mfe", "mae")]
        + ["sret_eod", "mfe_eod", "mae_eod", "t_mfe", "t_mae"]
        + [f"t_r{int(L * 10)}" for L in R_LEVELS]
        + ["t_stop05", "t_stop10"]
        + [f"t_p{int(P * 100)}" for P in PCT_LEVELS])


def to_frame(rows):
    d = pd.DataFrame(rows, columns=COLS)
    d["ts"] = pd.to_datetime(d["ts"])
    d["date"] = pd.to_datetime(d["date"])
    for cc in ("symbol", "direction", "group"):
        d[cc] = d[cc].astype("category")
    return d


# ──────────────────────────────────────────────────────────────────────────────

def boot(x, n_boot=10_000, seed=42, clusters=None):
    """Trade-level, or CLUSTER bootstrap when `clusters` is given (spec §20).

    Signals from one ticker-day share a session and are not independent;
    resampling them individually understates the interval. Cluster resampling
    draws whole ticker-days with replacement, which is the primary inference.
    """
    x = np.asarray(x, float)
    ok = ~np.isnan(x)
    x = x[ok]
    if len(x) < 20:
        return None
    rng = np.random.default_rng(seed)
    if clusters is None:
        n = len(x)
        batch = max(1, 20_000_000 // n)
        means = np.empty(n_boot)
        done = 0
        while done < n_boot:
            k = min(batch, n_boot - done)
            means[done:done + k] = x[rng.integers(0, n, size=(k, n))].mean(axis=1)
            done += k
    else:
        cl = np.asarray(clusters)[ok]
        _, inv = np.unique(cl, return_inverse=True)
        order = np.argsort(inv, kind="stable")
        xs, invs = x[order], inv[order]
        edges = np.searchsorted(invs, np.arange(invs[-1] + 2))
        sums = np.add.reduceat(xs, edges[:-1])
        cnts = np.diff(edges)
        keep = cnts > 0
        sums, cnts = sums[keep], cnts[keep]
        g = len(sums)
        means = np.empty(n_boot)
        for b in range(n_boot):
            idx = rng.integers(0, g, size=g)
            means[b] = sums[idx].sum() / cnts[idx].sum()
    return dict(mean=float(x.mean()), lo=float(np.percentile(means, 2.5)),
                hi=float(np.percentile(means, 97.5)),
                p_le0=float((means <= 0).mean()), n=int(len(x)))


def bps(v):
    return 100.0 * v          # percent -> basis points


def verify_signal():
    """Assert the locked trigger is byte-identical in behaviour (spec §1)."""
    print("=" * 100)
    print("VERIFY — forward scanner reproduces the locked trigger exactly")
    print("=" * 100)
    files = sorted(PER_TICKER_5M.glob("*.parquet"))[:6]
    ok = True
    for f in files:
        g = prepare(pd.read_parquet(f))
        a = scan_original(g, CORE, "5min")
        b = scan_forward(g, CORE)
        # compare only TREATED and C1 (C2 is deliberately subsampled here)
        sa = {(r[1], r[3], r[4]) for r in a if r[4] != "C2_nobreak"}
        sb = {(r[1], r[3], r[4]) for r in b if r[4] != "C2_nobreak"}
        same = sa == sb
        ok &= same
        print(f"  {f.stem:<8} locked {len(sa):>6,} | forward {len(sb):>6,}  "
              f"{'IDENTICAL' if same else 'DIFFERS <-- SIGNAL DRIFTED'}")
    print(f"\n  VERDICT: {'PASS — signal is locked' if ok else 'FAIL'}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify-signal", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()

    if a.verify_signal:
        verify_signal()
        return

    print("=" * 100)
    print("HOD_BREAKOUT_FORWARD_DRIFT — shape of the drift curve  [5-minute]")
    print("=" * 100)
    print("  LEVELS ARE NOT COMPARABLE to the 1-minute study (0.10 vs 1.15 bps")
    print("  at 15m). The SHAPE — drift(60m)/drift(15m) — is the deliverable.")

    if EVENTS.exists() and not a.rebuild:
        d = pd.read_parquet(EVENTS)
        for cc in ("symbol", "direction", "group"):
            d[cc] = d[cc].astype("category")
        print(f"  events: cached {len(d):,}")
    else:
        files = sorted(PER_TICKER_5M.glob("*.parquet"))
        rows = []
        for n, f in enumerate(files, 1):
            rows += scan_forward(prepare(pd.read_parquet(f)), CORE)
            if n % 25 == 0 or n == len(files):
                print(f"    scanned {n}/{len(files)}, {len(rows):,} events",
                      flush=True)
        d = to_frame(rows)
        del rows
        tmp = EVENTS.with_suffix(".tmp")
        d.to_parquet(tmp)
        tmp.replace(EVENTS)
        print(f"  cached -> {EVENTS.name}")

    T = d[d["group"] == "TREATED"]
    print(f"\n  events {len(d):,} | TREATED {len(T):,} | "
          f"C1 {int((d['group'] == 'C1_volfail').sum()):,} | "
          f"C2 {int((d['group'] == 'C2_nobreak').sum()):,} "
          f"(every {C2_KEEP_EVERY}th kept)")

    spd = T.groupby(["symbol", "date"], observed=True).size()
    print(f"  signals per ticker-day: mean {spd.mean():.2f} "
          f"median {spd.median():.0f} p95 {spd.quantile(.95):.0f}")

    # ── §17 censoring + §6 drift curve ──────────────────────────────────────
    print("\n" + "=" * 100)
    print("FORWARD DRIFT CURVE — TREATED, direction-adjusted (spec §6, §17)")
    print("=" * 100)
    print(f"  {'horizon':<10}{'eligible n':>12}{'mean bps':>11}{'median':>10}"
          f"{'95% CI (bps)':>22}{'P(>0)':>9}{'-4bps':>9}{'-10bps':>9}")
    curve = {}
    for m, b in HORIZONS + [("EOD", None)]:
        col = "sret_eod" if b is None else f"sret{m}"
        s = T[col].dropna()
        if len(s) < 20:
            continue
        bt = boot(s.to_numpy())
        curve[m] = bt["mean"]
        print(f"  {str(m) + ('m' if b else ''):<10}{len(s):>12,}"
              f"{bps(bt['mean']):>11.2f}{bps(s.median()):>10.2f}"
              f"{f'[{bps(bt[chr(108)+chr(111)]):+.2f},{bps(bt[chr(104)+chr(105)]):+.2f}]':>22}"
              f"{(s > 0).mean():>9.3f}"
              f"{bps(bt['mean']) - 4:>9.2f}{bps(bt['mean']) - 10:>9.2f}")

    # ── §13 break-even ──────────────────────────────────────────────────────
    print("\n  BREAK-EVEN round-trip cost = gross edge (spec §13)")
    for m in (15, 30, 60, 120, "EOD"):
        if m in curve:
            print(f"    {str(m):<6} {bps(curve[m]):>7.2f} bps")
    first4 = next((m for m, _ in HORIZONS if curve.get(m, 0) and bps(curve[m]) > 4), None)
    first10 = next((m for m, _ in HORIZONS if curve.get(m, 0) and bps(curve[m]) > 10), None)
    print(f"    first horizon above 4 bps : {first4 or 'NEVER'}")
    print(f"    first horizon above 10 bps: {first10 or 'NEVER'}")

    # ── §11 controls at every horizon ───────────────────────────────────────
    print("\n" + "=" * 100)
    print("CONTROL SPREAD — does TREATED pull away as horizon grows? (spec §11)")
    print("=" * 100)
    print(f"  {'horizon':<10}{'TREATED':>10}{'C1':>10}{'C2':>10}"
          f"{'T-C1':>10}{'T-C2':>10}   (bps)")
    for m, b in HORIZONS + [("EOD", None)]:
        col = "sret_eod" if b is None else f"sret{m}"
        vals = {}
        for k in ("TREATED", "C1_volfail", "C2_nobreak"):
            s = d.loc[d["group"] == k, col].dropna()
            vals[k] = s.mean() if len(s) >= 20 else np.nan
        print(f"  {str(m) + ('m' if b else ''):<10}{bps(vals['TREATED']):>10.2f}"
              f"{bps(vals['C1_volfail']):>10.2f}{bps(vals['C2_nobreak']):>10.2f}"
              f"{bps(vals['TREATED'] - vals['C1_volfail']):>10.2f}"
              f"{bps(vals['TREATED'] - vals['C2_nobreak']):>10.2f}")

    # ── §7 MFE/MAE curve ────────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("MFE / MAE CURVE — TREATED, in R (spec §7)")
    print("=" * 100)
    print(f"  {'horizon':<10}{'mean MFE':>10}{'med':>8}{'p75':>8}{'p90':>8}"
          f"{'p95':>8}{'mean MAE':>10}{'med':>8}{'MFE/|MAE|':>11}")
    for m, b in HORIZONS + [("EOD", None)]:
        fc = "mfe_eod" if b is None else f"mfe{m}"
        ac = "mae_eod" if b is None else f"mae{m}"
        f_, a_ = T[fc].dropna(), T[ac].dropna()
        if len(f_) < 20:
            continue
        print(f"  {str(m) + ('m' if b else ''):<10}{f_.mean():>10.3f}"
              f"{f_.median():>8.3f}{f_.quantile(.75):>8.3f}"
              f"{f_.quantile(.90):>8.3f}{f_.quantile(.95):>8.3f}"
              f"{a_.mean():>10.3f}{a_.median():>8.3f}"
              f"{abs(f_.mean() / a_.mean()):>11.3f}")

    # ── §8 distribution / fat tail ──────────────────────────────────────────
    print("\n" + "=" * 100)
    print("DISTRIBUTION — is the mean broad drift or a few runners? (spec §8)")
    print("=" * 100)
    qs = [.01, .05, .10, .25, .50, .75, .90, .95, .99]
    print(f"  {'horizon':<8}" + "".join(f"{f'p{int(q*100)}':>9}" for q in qs)
          + f"{'skew':>8}")
    for m, b in [(15, 3), (30, 6), (60, 12), (120, 24), ("EOD", None)]:
        col = "sret_eod" if b is None else f"sret{m}"
        s = T[col].dropna()
        if len(s) < 20:
            continue
        print(f"  {str(m):<8}" + "".join(f"{bps(s.quantile(q)):>9.1f}" for q in qs)
              + f"{s.skew():>8.2f}")
    print(f"\n  {'horizon':<8}{'>+25bps':>10}{'>+50bps':>10}{'>+100bps':>10}"
          f"{'<-25bps':>10}{'<-50bps':>10}{'<-100bps':>10}")
    for m, b in [(15, 3), (30, 6), (60, 12), (120, 24), ("EOD", None)]:
        col = "sret_eod" if b is None else f"sret{m}"
        s = T[col].dropna()
        if len(s) < 20:
            continue
        print(f"  {str(m):<8}" + "".join(f"{100 * (s > t).mean():>9.2f}%"
                                        for t in (.25, .50, 1.00))
              + "".join(f"{100 * (s < -t).mean():>9.2f}%"
                        for t in (.25, .50, 1.00)))

    # ── §10 R path across horizons ──────────────────────────────────────────
    print("\n" + "=" * 100)
    print("R-PATH — P(+XR before -1R) within each horizon (spec §10)")
    print("=" * 100)
    print(f"  {'horizon':<10}{'+0.5R/-0.5R':>13}" +
          "".join(f"{f'+{L}R':>9}" for L in (1.0, 1.5, 2.0, 3.0)))
    for m, b in [(15, 3), (30, 6), (60, 12), (120, 24), ("EOD", None)]:
        lim = T["avail"] if b is None else np.minimum(T["avail"], b)
        cells = []
        h05, s05 = T["t_r5"].to_numpy(), T["t_stop05"].to_numpy()
        lv = lim.to_numpy()
        w = ((h05 > 0) & (h05 <= lv) &
             ((s05 == 0) | (s05 > lv) | (h05 < s05)))
        cells.append(w.mean())
        s10 = T["t_stop10"].to_numpy()
        for L, cname in ((1.0, "t_r10"), (1.5, "t_r15"), (2.0, "t_r20"), (3.0, "t_r30")):
            hx = T[cname].to_numpy()
            w = ((hx > 0) & (hx <= lv) &
                 ((s10 == 0) | (s10 > lv) | (hx < s10)))
            cells.append(w.mean())
        print(f"  {str(m):<10}{100 * cells[0]:>12.1f}%" +
              "".join(f"{100 * x:>8.1f}%" for x in cells[1:]))

    # ── §9 time-to-X ────────────────────────────────────────────────────────
    print("\n  TIME-TO (bars of 5 min; only signals that reached it) — spec §9")
    for nm, col in (("+0.25%", "t_p25"), ("+0.50%", "t_p50"),
                    ("+1.00%", "t_p100"), ("+1R", "t_r10"), ("+2R", "t_r20")):
        s = T.loc[T[col] > 0, col]
        if len(s):
            print(f"    {nm:<8} reached {100 * len(s) / len(T):>5.1f}%   "
                  f"median {5 * s.median():>5.0f} min   p90 {5 * s.quantile(.9):>5.0f} min")
    for nm, col in (("max favourable", "t_mfe"), ("max adverse", "t_mae")):
        s = T.loc[T[col] > 0, col]
        if len(s):
            print(f"    {nm:<15} median {5 * s.median():>5.0f} min")

    # ── §19/§20 bootstrap, trade vs cluster ─────────────────────────────────
    print("\n" + "=" * 100)
    print("BOOTSTRAP — trade-level vs CLUSTER by ticker-day (spec §19, §20)")
    print("=" * 100)
    cl = (T["symbol"].astype(str) + "|" + T["date"].astype(str)).to_numpy()
    print(f"  {'horizon':<10}{'trade mean':>12}{'trade CI':>22}"
          f"{'cluster CI':>22}{'cluster P(<=0)':>16}")
    for m, b in [(15, 3), (30, 6), (60, 12), (120, 24), ("EOD", None)]:
        col = "sret_eod" if b is None else f"sret{m}"
        s = T[col]
        bt, bc = boot(s.to_numpy()), boot(s.to_numpy(), clusters=cl)
        if not bt or not bc:
            continue
        print(f"  {str(m):<10}{bps(bt['mean']):>12.2f}"
              f"{f'[{bps(bt[chr(108)+chr(111)]):+.2f},{bps(bt[chr(104)+chr(105)]):+.2f}]':>22}"
              f"{f'[{bps(bc[chr(108)+chr(111)]):+.2f},{bps(bc[chr(104)+chr(105)]):+.2f}]':>22}"
              f"{bc['p_le0']:>16.3f}")

    # ── breakdowns ──────────────────────────────────────────────────────────
    print("\n" + "=" * 100)
    print("BREAKDOWNS — mean signed return, bps (spec §14, §15, §16, §18)")
    print("=" * 100)
    hs = [(15, 3), (30, 6), (60, 12), (120, 24), ("EOD", None)]

    def brk(sub, label):
        cells = []
        for m, b in hs:
            col = "sret_eod" if b is None else f"sret{m}"
            s = sub[col].dropna()
            cells.append(f"{bps(s.mean()):>9.2f}" if len(s) >= 20 else f"{'-':>9}")
        print(f"  {label:<22}{len(sub):>9,}" + "".join(cells))

    print(f"  {'group':<22}{'n':>9}" + "".join(f"{str(m):>9}" for m, _ in hs))
    for dr in ("LONG", "SHORT"):
        brk(T[T["direction"] == dr], dr)
    print()
    tb = T["ts"].dt.strftime("%H:%M")
    for name, lo, hi in [("09:45-11:00", "09:45", "11:00"),
                         ("11:00-14:00", "11:00", "14:00"),
                         ("14:00-15:15", "14:00", "15:15")]:
        brk(T[(tb >= lo) & (tb < hi)], name)
    print()
    for y in sorted(T["date"].dt.year.unique()):
        brk(T[T["date"].dt.year == y], str(y))
    print()
    vc = T["symbol"].value_counts()
    for k in (5, 10):
        top = list(vc.head(k).index)
        brk(T[~T["symbol"].isin(top)], f"excluding top{k}")
    print(f"  top5 = {100 * vc.head(5).sum() / len(T):.1f}% of signals, "
          f"top10 = {100 * vc.head(10).sum() / len(T):.1f}%")

    print("\n  REGIME ANALYSIS NOT AVAILABLE FOR THIS DATASET (spec §22): the")
    print("  engine labels cover 2017-2022 and this 5-minute study is the same")
    print("  period, but the 1-minute study it stands in for is 2023-2026.")
    print("  Mixing them would misattribute regimes across datasets.")
    print("=" * 100)


if __name__ == "__main__":
    main()
