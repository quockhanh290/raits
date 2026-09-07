"""
EMA_MOMENTUM_SCALP — Stage A phenomenon screen on 5-minute bars.
(RESEARCH ONLY — raits/raits/scripts/research/. Reads production classes and
the local cache; modifies nothing.)

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This is a SCREEN, not the specified test. The spec requires 1-minute execution
bars. The 1-minute data on disk covers 09:30-10:44 only (bought for a different
study), which cannot host this setup at all: a 5-minute EMA20 needs 100 minutes
of bars and that window holds 75. Buying the missing hours costs $216 for all
three session buckets, against ~$46 of remaining budget.

So this runs the phenomenon question on the 5-minute Polygon cache — 75
tickers, full session, 2017-2022, all three buckets, six years — for $0. Its
purpose is to decide whether spending the remaining budget on 1-minute data is
justified, per the spec's own staged design ("Nếu phenomenon này không tồn tại,
không mở rộng parameter grid").

WHAT A 5-MINUTE SCREEN CANNOT ANSWER
------------------------------------
P(+1R before -1R) is an INTRABAR ORDERING question, and the spec explicitly
forbids inferring stop/target order from 5-minute OHLC. When one bar spans both
levels the true order is unknown, so this reports BOUNDS instead of a number:
    conservative = that bar counts as the stop
    optimistic   = that bar counts as the target
The truth is between them. A screen that passes only under the optimistic bound
has not passed.

The 3-minute excursion mark in the spec is unavailable at 5-minute resolution;
marks are 5/10/15 minutes = 1/2/3 bars.

DOCUMENTED SUBSTITUTIONS
------------------------
EMA is CONTINUOUS across sessions, not reset daily.
    TrendFollowStrategy is fed today's bars only, and that is why production
    only trades it from 14:00 — a daily-reset EMA20 needs 20 bars, i.e. 11:10
    at the earliest, which makes the spec's 09:45-11:00 bucket structurally
    impossible to test. A continuous EMA keeps all three buckets testable.
    Documented, not silent: production uses the daily-reset form.
Universe is the 75-ticker 5-minute cache, not the 37-name production
    CANDIDATE_POOL. It is a superset of it.
Regime labels come from the `hmm_state` field on realised trades in
    results_20260707_110323.pkl — the engine's own labels, not reconstructed.
    They exist only for dates that produced a trade, so coverage is partial and
    non-random; the breakdown states its own coverage.

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\ema_momentum_scalp_test.py
"""

from __future__ import annotations

import argparse
import hashlib
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

CACHE = _ROOT / "raits" / "data" / "cache" / "data"
SNAP = _ROOT / "raits" / "data" / "cache" / "snapshots" / "results_20260707_110323.pkl"
WORK = _ROOT / "raits" / "data" / "cache" / "research_daily"
BARS_CACHE = WORK / "ema_scalp_5min_rth.parquet"
PER_TICKER = WORK / "ema_scalp_5min"

START, END = "2017-01-03", "2022-12-31"
RTH_OPEN, RTH_CLOSE = "09:30", "15:55"

EMA_FAST, EMA_SLOW = 9, 20
VOL_LOOKBACK = 10
SLOPE_BARS = 3
MAX_RISK_PCT = 0.010          # spec §8: reject if risk > 1.0% of entry
MARKS = (1, 2, 3)             # bars after entry = 5 / 10 / 15 minutes

# Stage A core config — fixed before looking at anything.
CORE = dict(hod=0.010, zone="EMA9", pull_vol=1.0, res_vol=1.2, buf=0.0005)

BUCKETS = [("09:45-11:00", "09:45", "11:00"),
           ("11:00-14:00", "11:00", "14:00"),
           ("14:00-15:45", "14:00", "15:45")]


# ──────────────────────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────────────────────

def _cache_path(t: str, day: pd.Timestamp) -> Path:
    d = day.date()
    h = hashlib.md5(f"{t}_{d}_{d}_5min".encode()).hexdigest()
    return CACHE / f"{t}_5min_{h}.parquet"


def _build_one(t: str, days) -> int:
    """Assemble one ticker's RTH history and cache it. Returns row count.

    Cached PER TICKER on purpose. The first version built all 75 in memory and
    wrote a single file at the end; a timeout during the final concat threw
    away 50 minutes of I/O. Per-ticker files cost at most one ticker's work.
    """
    out = PER_TICKER / f"{t}.parquet"
    if out.exists():
        return -1
    parts = []
    for day in days:
        p = _cache_path(t, day)
        if not p.exists():
            continue
        try:
            x = pd.read_parquet(p)
        except Exception:
            continue
        x = x.between_time(RTH_OPEN, RTH_CLOSE)
        if not x.empty:
            parts.append(x)
    if not parts:
        return 0
    d = pd.concat(parts)
    d = d[~d.index.duplicated(keep="first")].sort_index()
    d["symbol"] = t
    d = d.reset_index()
    tc = next(c for c in d.columns if c not in
              ("open", "high", "low", "close", "volume", "vwap",
               "transactions", "symbol"))
    d = d.rename(columns={tc: "ts"})
    d["ts"] = pd.to_datetime(d["ts"])
    d = d[["symbol", "ts", "open", "high", "low", "close", "volume"]]
    tmp = out.with_suffix(".tmp")
    d.to_parquet(tmp)
    tmp.replace(out)          # atomic: a killed run never leaves a partial file
    return len(d)


def load_bars(workers: int = 8) -> pd.DataFrame:
    import re
    from concurrent.futures import ThreadPoolExecutor, as_completed
    PER_TICKER.mkdir(parents=True, exist_ok=True)
    tick = sorted({m.group(1) for m in
                   (re.match(r"^([A-Z.]+)_5min_", f.name) for f in CACHE.glob("*.parquet"))
                   if m})
    days = list(pd.bdate_range(START, END))
    todo = [t for t in tick if not (PER_TICKER / f"{t}.parquet").exists()]
    print(f"  tickers {len(tick)} | cached {len(tick) - len(todo)} | "
          f"to build {len(todo)}  ({len(days)} sessions each)")
    if todo:
        import time
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_build_one, t, days): t for t in todo}
            for i, f in enumerate(as_completed(futs), 1):
                try:
                    f.result()
                except Exception as e:
                    print(f"    {futs[f]}: {type(e).__name__}: {str(e)[:60]}")
                if i % 10 == 0 or i == len(todo):
                    el = time.time() - t0
                    print(f"    {i}/{len(todo)}  {el / 60:.1f}m  "
                          f"ETA {el / i * (len(todo) - i) / 60:.1f}m", flush=True)
    frames = [pd.read_parquet(p) for p in sorted(PER_TICKER.glob("*.parquet"))]
    b = pd.concat(frames, ignore_index=True)
    print(f"  bars: {len(b):,} rows from {len(frames)} tickers")
    return b


def load_regime() -> dict:
    """Engine-produced hmm_state per date, from realised trades. Partial by
    construction — only dates that produced a trade carry a label."""
    if not SNAP.exists():
        return {}
    w = pickle.load(open(SNAP, "rb"))
    seen = {}
    for win in w:
        for t in win["trades"]:
            d = pd.Timestamp(t.entry_time).normalize()
            s = getattr(t, "hmm_state", None)
            if s:
                seen.setdefault(d, set()).add(str(s))
    # Days with more than one state are the intraday volatility override
    # switching mid-session; drop them rather than pick one arbitrarily.
    return {d: next(iter(v)) for d, v in seen.items() if len(v) == 1}


# ──────────────────────────────────────────────────────────────────────────────
# Setup detection
# ──────────────────────────────────────────────────────────────────────────────

def prepare(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("ts").reset_index(drop=True)
    g["date"] = g["ts"].dt.normalize()
    g["ema_f"] = g["close"].ewm(span=EMA_FAST, adjust=False).mean()
    g["ema_s"] = g["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    g["slope_up"] = g["ema_s"] > g["ema_s"].shift(SLOPE_BARS)
    g["slope_dn"] = g["ema_s"] < g["ema_s"].shift(SLOPE_BARS)
    g["avg_vol"] = g["volume"].rolling(VOL_LOOKBACK).mean().shift(1)
    # HOD/LOD so far TODAY — expanding within the session, never future.
    gb = g.groupby("date")
    g["hod"] = gb["high"].cummax()
    g["lod"] = gb["low"].cummin()
    g["bar_of_day"] = gb.cumcount()
    return g


def find_setups(g: pd.DataFrame, cfg: dict) -> list:
    """Pullback -> resume, LONG and SHORT. Uses only bars up to the resume bar."""
    hod_tol, zone, pv, rv, buf = (cfg["hod"], cfg["zone"], cfg["pull_vol"],
                                  cfg["res_vol"], cfg["buf"])
    out = []
    o, h, l, c = (g["open"].values, g["high"].values,
                  g["low"].values, g["close"].values)
    ef, es, av = g["ema_f"].values, g["ema_s"].values, g["avg_vol"].values
    vol, hod, lod = g["volume"].values, g["hod"].values, g["lod"].values
    up, dn = g["slope_up"].values, g["slope_dn"].values
    bod, ts, date = g["bar_of_day"].values, g["ts"].values, g["date"].values
    n = len(g)

    for i in range(VOL_LOOKBACK + SLOPE_BARS, n - max(MARKS) - 2):
        if not np.isfinite(av[i]) or av[i] <= 0 or bod[i] < 3:
            continue
        # bar i is the RESUME bar; bar i-1 is the PULLBACK bar.
        p = i - 1
        if date[p] != date[i]:
            continue

        for direction in ("LONG", "SHORT"):
            if direction == "LONG":
                if not (c[i] > es[i] and up[i]):
                    continue
                if hod[i] <= 0 or (hod[i] - c[i]) / hod[i] > hod_tol:
                    continue
                zone_hi = ef[p] if zone == "EMA9" else max(ef[p], es[p])
                zone_lo = ef[p] if zone == "EMA9" else min(ef[p], es[p])
                touched = l[p] <= zone_hi
                intact = c[p] > es[p] * (1 - 0.003)      # not far below EMA20
                if not (touched and intact and l[p] >= zone_lo * 0.985):
                    continue
                if not (vol[p] < pv * av[p]):
                    continue
                if not (c[i] > o[i] and c[i] > ef[i] and c[i] > c[p]):
                    continue
                if not (vol[i] > rv * av[i]):
                    continue
                entry = o[i + 1]
                stop = l[p] * (1 - buf)
                risk = entry - stop
            else:
                if not (c[i] < es[i] and dn[i]):
                    continue
                if lod[i] <= 0 or (c[i] - lod[i]) / lod[i] > hod_tol:
                    continue
                zone_lo = ef[p] if zone == "EMA9" else min(ef[p], es[p])
                zone_hi = ef[p] if zone == "EMA9" else max(ef[p], es[p])
                touched = h[p] >= zone_lo
                intact = c[p] < es[p] * (1 + 0.003)
                if not (touched and intact and h[p] <= zone_hi * 1.015):
                    continue
                if not (vol[p] < pv * av[p]):
                    continue
                if not (c[i] < o[i] and c[i] < ef[i] and c[i] < c[p]):
                    continue
                if not (vol[i] > rv * av[i]):
                    continue
                entry = o[i + 1]
                stop = h[p] * (1 + buf)
                risk = stop - entry

            if risk <= 0 or risk / entry > MAX_RISK_PCT:
                continue

            # ── excursions, in R, from the entry bar forward ────────────────
            sgn = 1.0 if direction == "LONG" else -1.0
            mfe, mae, hit1, hit15, hitstop = {}, {}, None, None, None
            run_hi = run_lo = 0.0
            for k in range(1, max(MARKS) + 1):
                j = i + k
                if j >= n or date[j] != date[i]:
                    break
                fav = sgn * (h[j] - entry) if direction == "LONG" else sgn * (l[j] - entry)
                adv = sgn * (l[j] - entry) if direction == "LONG" else sgn * (h[j] - entry)
                run_hi = max(run_hi, fav / risk)
                run_lo = min(run_lo, adv / risk)
                if k in MARKS:
                    mfe[k], mae[k] = run_hi, run_lo
                # First bar to touch +1R / +1.5R / -1R. When one bar touches
                # both, the order is unknowable here — recorded as ambiguous.
                if hit1 is None and run_hi >= 1.0:
                    hit1 = (k, run_lo <= -1.0)
                if hit15 is None and run_hi >= 1.5:
                    hit15 = (k, run_lo <= -1.0)
                if hitstop is None and run_lo <= -1.0:
                    hitstop = (k, run_hi >= 1.0)
            if not mfe:
                continue

            out.append(dict(
                symbol=g["symbol"].iloc[0], ts=pd.Timestamp(ts[i]),
                date=pd.Timestamp(date[i]), direction=direction,
                entry=float(entry), stop=float(stop),
                risk_pct=100.0 * risk / entry,
                mfe={k: mfe.get(k, np.nan) for k in MARKS},
                mae={k: mae.get(k, np.nan) for k in MARKS},
                hit1=hit1, hit15=hit15, hitstop=hitstop,
            ))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Path statistics with explicit bounds
# ──────────────────────────────────────────────────────────────────────────────

def path_stats(recs: list, level="hit1") -> dict:
    """P(target before -1R) as CONSERVATIVE and OPTIMISTIC bounds.

    A bar that spans both levels is ambiguous at 5-minute resolution. The
    conservative bound calls it a stop, the optimistic one calls it a target.
    Reporting a single number here would be exactly the inference the spec
    forbids.
    """
    n = len(recs)
    if not n:
        return {}
    cons = opt = amb = 0
    for r in recs:
        hit, stop = r[level], r["hitstop"]
        if hit is None:
            continue
        if stop is None:
            cons += 1
            opt += 1
            continue
        hk, h_amb = hit
        sk, _ = stop
        if hk < sk:
            cons += 1
            opt += 1
        elif sk < hk:
            pass
        else:
            amb += 1
            opt += 1
    return dict(n=n, cons=cons / n, opt=opt / n, amb=amb / n)


def describe(recs: list, label: str, indent="  "):
    if not recs:
        print(f"{indent}{label:<26} (none)")
        return
    n = len(recs)
    row = f"{indent}{label:<26}{n:>7}"
    for k in MARKS:
        v = np.nanmean([r["mfe"][k] for r in recs])
        row += f"{v:>8.3f}"
    for k in MARKS:
        v = np.nanmean([r["mae"][k] for r in recs])
        row += f"{v:>8.3f}"
    p1, p15 = path_stats(recs, "hit1"), path_stats(recs, "hit15")
    row += f"{100 * p1['cons']:>7.1f}%{100 * p1['opt']:>7.1f}%"
    row += f"{100 * p15['cons']:>7.1f}%{100 * p15['opt']:>7.1f}%"
    print(row)


def header(indent="  "):
    print(f"{indent}{'group':<26}{'n':>7}"
          + "".join(f"{f'MFE{5*k}':>8}" for k in MARKS)
          + "".join(f"{f'MAE{5*k}':>8}" for k in MARKS)
          + f"{'+1R lo':>7}{'hi':>7}{'+1.5 lo':>7}{'hi':>7}")


def bucket_of(ts) -> str:
    hm = ts.strftime("%H:%M")
    for name, a, b in BUCKETS:
        if a <= hm < b:
            return name
    return "other"


# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage-b", action="store_true",
                    help="also sweep the 16 entry variants")
    a = ap.parse_args()

    print("=" * 110)
    print("EMA_MOMENTUM_SCALP — Stage A phenomenon screen (5-minute bars)")
    print("=" * 110)
    print("  NOTE: this is a SCREEN. Execution-grade 1-minute bars for these")
    print("  hours do not exist on disk and cost $216 to buy. See docstring.")

    bars = load_bars()
    regime = load_regime()
    print(f"  regime labels: {len(regime):,} dates from engine trades "
          f"(partial by construction)")

    prepared = {s: prepare(g) for s, g in bars.groupby("symbol")}
    print(f"  tickers {len(prepared)} | sessions "
          f"{bars['ts'].dt.normalize().nunique():,} | bars {len(bars):,}")

    print("\n  core config:", CORE)
    recs = []
    for s, g in prepared.items():
        recs += find_setups(g, CORE)
    print(f"\n  SETUPS: {len(recs):,}")
    if not recs:
        print("  No setups — nothing to screen.")
        return

    rp = np.array([r["risk_pct"] for r in recs])
    print(f"  risk distance %: mean {rp.mean():.3f}  median {np.median(rp):.3f}  "
          f"p90 {np.percentile(rp, 90):.3f}  (cap {100 * MAX_RISK_PCT:.1f})")

    print("\n" + "=" * 110)
    print("STAGE A — excursion (R units) and path, with AMBIGUITY BOUNDS")
    print("=" * 110)
    header()
    describe(recs, "ALL")
    for d in ("LONG", "SHORT"):
        describe([r for r in recs if r["direction"] == d], d)
    print()
    for name, _, _ in BUCKETS:
        describe([r for r in recs if bucket_of(r["ts"]) == name], name)
    print()
    for y in sorted({r["date"].year for r in recs}):
        describe([r for r in recs if r["date"].year == y], str(y))

    if regime:
        print()
        lab = [(r, regime.get(r["date"])) for r in recs]
        cov = sum(1 for _, s in lab if s) / len(lab)
        for st in ("Calm", "Normal", "Stress", "Crisis"):
            describe([r for r, s in lab if s == st], f"regime {st}")
        print(f"  regime label coverage: {100 * cov:.1f}% of setups "
              f"(labels exist only on days that produced an engine trade)")
    else:
        print("\n  REGIME BREAKDOWN UNAVAILABLE")

    print("\n  top tickers by setup count:")
    vc = pd.Series([r["symbol"] for r in recs]).value_counts()
    print(f"  top 5 = {100 * vc.head(5).sum() / len(recs):.1f}% of all setups: "
          f"{', '.join(f'{k}({v})' for k, v in vc.head(5).items())}")

    if a.stage_b:
        print("\n" + "=" * 110)
        print("STAGE B — entry-variant robustness")
        print("=" * 110)
        header()
        for hod in (0.010, 0.015):
            for zone in ("EMA9", "EMA9-20"):
                for pv in (1.0, 0.8):
                    for rv in (1.2, 1.5):
                        cfg = dict(hod=hod, zone=zone, pull_vol=pv,
                                   res_vol=rv, buf=CORE["buf"])
                        rr = []
                        for s, g in prepared.items():
                            rr += find_setups(g, cfg)
                        describe(rr, f"hod{hod:.3f} {zone} p{pv} r{rv}")

    print("\n" + "=" * 110)
    print("HOW TO READ")
    print("=" * 110)
    print("  '+1R lo/hi' are the CONSERVATIVE and OPTIMISTIC bounds on")
    print("  P(+1R before -1R). The true value lies between them. A screen that")
    print("  clears the bar only on the optimistic side has NOT cleared it.")
    print("  Kill criterion (spec §18): P(+1R before -1R) <= 50% is a fail.")
    print("=" * 110)


if __name__ == "__main__":
    main()
