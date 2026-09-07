"""
HOD_CONSOLIDATION_BREAKOUT_SCALP — Stage A phenomenon study with controls.
(RESEARCH ONLY — raits/raits/scripts/research/. Reads the local cache only;
modifies no production code.)

THE QUESTION (spec §2, §11)
---------------------------
After a compression near the running HOD/LOD resolves into a volume-confirmed
breakout, does price expand DIRECTIONALLY over the next 5-15 minutes, or is it
symmetric diffusion that merely looks directional because volatility rose?

The centrepiece is the CONTROL (spec §11). Measuring the breakout group alone
cannot separate edge from volatility: a compressed range near the high is a
low-volatility state, and anything following it will show larger excursions in
both directions. So every breakout is compared against matched non-events.

TWO CONTROLS, both matched on the same consolidation
----------------------------------------------------
C1  VOLUME-FAIL: the same consolidation broke out, but breakout volume did NOT
    clear the threshold. Identical ticker, day, time bucket, consolidation
    width, direction and HOD distance — the ONLY difference is the volume
    trigger. This isolates exactly what the trigger is supposed to add.
C2  NO-BREAKOUT: the consolidation formed near HOD/LOD and simply did not
    break out within the window. Forward excursion is measured from the same
    bar index. This isolates what the breakout itself adds over the context.

If TREATED does not beat C1, the volume rule adds nothing.
If TREATED does not beat C2, the breakout adds nothing.

RESOLUTION — run at BOTH, because the answer could depend on it (spec §3)
------------------------------------------------------------------------
5-minute : 75 tickers, 2017-2022, full session, all three buckets.
           A "5-bar consolidation" is then 25 MINUTES, not 5 — a materially
           rarer and different phenomenon than the spec implies.
1-minute : 314 tickers, 2023-2026, but only 09:30-10:44 (bought for another
           study). True spec resolution; covers part of one bucket only.
Neither alone is sufficient. Agreement between them is the useful signal.

Intrabar ordering is unknowable when one bar spans both levels, so path
probabilities are reported as CONSERVATIVE/OPTIMISTIC bounds plus the measured
AMBIGUITY RATE. Spec §3: a high ambiguity rate downgrades the verdict.

ANTI-BIAS (spec §23) — enforced in code, not by intention
---------------------------------------------------------
* HOD/LOD is an expanding cummax/cummin over bars strictly BEFORE the signal.
* The breakout bar is excluded from the consolidation range and its volume
  average.
* Entry is the NEXT bar's open, never the breakout close.
* One setup per consolidation event, with a cooldown (spec §8) — see _dedupe.

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\hod_consolidation_breakout_test.py
    python raits\\raits\\scripts\\research\\hod_consolidation_breakout_test.py --res 1min
"""

from __future__ import annotations

import argparse
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

WORK = _ROOT / "raits" / "data" / "cache" / "research_daily"
PER_TICKER_5M = WORK / "ema_scalp_5min"
BARS_1M = _ROOT / "raits" / "data" / "cache" / "orb_1min" / "_consolidated_1m.parquet"
SNAP = _ROOT / "raits" / "data" / "cache" / "snapshots" / "results_20260707_110323.pkl"

# Stage A core config — fixed before looking at anything (spec §10).
CORE = dict(hod=0.010, cons_bars=5, max_range=0.0035, vol_mult=1.5)
MAX_RISK_PCT = 0.010
BUFFER = 0.0005

BUCKETS = [("09:45-11:00", "09:45", "11:00"),
           ("11:00-14:00", "11:00", "14:00"),
           ("14:00-15:45", "14:00", "15:45")]


def marks_for(res: str):
    """Excursion marks in BARS for 5/10/15 minutes at this resolution."""
    return (5, 10, 15) if res == "1min" else (1, 2, 3)


def cooldown_bars(res: str) -> int:
    return 10 if res == "1min" else 2          # spec §8: >= 10 minutes


# ──────────────────────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────────────────────

def load(res: str) -> pd.DataFrame:
    if res == "5min":
        files = sorted(PER_TICKER_5M.glob("*.parquet"))
        if not files:
            print(f"  No 5-min per-ticker cache at {PER_TICKER_5M}")
            print("  Run ema_momentum_scalp_test.py once to build it.")
            return pd.DataFrame()
        b = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
    else:
        if not BARS_1M.exists():
            print(f"  No 1-min bars at {BARS_1M}")
            return pd.DataFrame()
        b = pd.read_parquet(BARS_1M)
    b["ts"] = pd.to_datetime(b["ts"])
    return b.sort_values(["symbol", "ts"])


def load_regime() -> dict:
    """Engine hmm_state per date, from realised trades. Partial and
    non-random by construction — only days that produced a trade are labelled.
    Spec §19 forbids inferring the missing ones."""
    if not SNAP.exists():
        return {}
    seen = {}
    for win in pickle.load(open(SNAP, "rb")):
        for t in win["trades"]:
            s = getattr(t, "hmm_state", None)
            if s:
                seen.setdefault(pd.Timestamp(t.entry_time).normalize(), set()).add(str(s))
    return {d: next(iter(v)) for d, v in seen.items() if len(v) == 1}


# ──────────────────────────────────────────────────────────────────────────────
# Event detection
# ──────────────────────────────────────────────────────────────────────────────

def prepare(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("ts").reset_index(drop=True)
    g["date"] = g["ts"].dt.normalize()
    gb = g.groupby("date")
    # Strictly-prior running extremes: shift(1) so the current bar can never
    # contribute to the HOD it is being compared against.
    g["hod"] = gb["high"].cummax().groupby(g["date"]).shift(1)
    g["lod"] = gb["low"].cummin().groupby(g["date"]).shift(1)
    g["bod"] = gb.cumcount()
    return g


def scan(g: pd.DataFrame, cfg: dict, res: str) -> list:
    """Return every consolidation-near-extreme event, tagged TREATED / C1 / C2.

    All three groups come from the SAME consolidation population, so they are
    matched on ticker, day, time, width and direction by construction rather
    than by a post-hoc pairing step.
    """
    nb, rng_max, hod_tol, vmult = (cfg["cons_bars"], cfg["max_range"],
                                   cfg["hod"], cfg["vol_mult"])
    MK = marks_for(res)
    CD = cooldown_bars(res)
    o, h, l, c = (g["open"].values, g["high"].values,
                  g["low"].values, g["close"].values)
    v, hod, lod = g["volume"].values, g["hod"].values, g["lod"].values
    date, ts, bod = g["date"].values, g["ts"].values, g["bod"].values
    sym = g["symbol"].iloc[0]
    n = len(g)
    out = []
    last_signal = {"LONG": -10**9, "SHORT": -10**9}
    last_level = {"LONG": None, "SHORT": None}

    for i in range(2 * nb + 1, n - max(MK) - 2):
        # Consolidation = bars [i-nb, i-1]; bar i is the candidate breakout.
        # The breakout bar is excluded from both range and volume (spec §5/§6).
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
        prange = (h[p0:s0].max() - l[p0:s0].min()) / mid if mid else np.nan
        if not (cvol > 0 and pvol > 0 and cvol < pvol):     # §6 compression
            continue

        for direction in ("LONG", "SHORT"):
            if direction == "LONG":
                ref = hod[i]
                if not np.isfinite(ref) or ref <= 0:
                    continue
                if (ref - c[i - 1]) / ref > hod_tol:        # context: near HOD
                    continue
                broke = c[i] > ch and c[i] >= ref * (1 - 0.0005) and c[i] > o[i]
                entry, risk_lvl = o[i + 1], cl
                risk = entry - cl * (1 - BUFFER)
            else:
                ref = lod[i]
                if not np.isfinite(ref) or ref <= 0:
                    continue
                if (c[i - 1] - ref) / ref > hod_tol:
                    continue
                broke = c[i] < cl and c[i] <= ref * (1 + 0.0005) and c[i] < o[i]
                entry, risk_lvl = o[i + 1], ch
                risk = ch * (1 + BUFFER) - entry

            if risk <= 0 or risk / entry > MAX_RISK_PCT:
                continue

            vol_ok = v[i] > vmult * cvol
            if broke and vol_ok:
                group = "TREATED"
            elif broke:
                group = "C1_volfail"
            else:
                group = "C2_nobreak"

            # ── dedupe (spec §8) ────────────────────────────────────────────
            # A signalled level is consumed: no further signal on the same
            # breakout level until the cooldown elapses AND price has traded
            # back inside the consolidation. Without this a single trend
            # emits a signal on every bar and inflates n with copies of one
            # event.
            if group == "TREATED":
                lvl = last_level[direction]
                cooled = (i - last_signal[direction]) >= CD
                re_entered = lvl is None or (
                    (l[i] <= lvl) if direction == "LONG" else (h[i] >= lvl))
                if not (cooled or re_entered):
                    continue
                last_signal[direction] = i
                last_level[direction] = ch if direction == "LONG" else cl

            # ── forward excursion in R ──────────────────────────────────────
            sgn = 1.0 if direction == "LONG" else -1.0
            mfe, mae, sret = {}, {}, {}
            hi = lo = 0.0
            hit = {0.5: None, 1.0: None, 1.5: None}
            stop = {0.5: None, 1.0: None}
            for k in range(1, max(MK) + 1):
                j = i + k
                if j >= n or date[j] != date[i]:
                    break
                fav = sgn * ((h[j] if direction == "LONG" else l[j]) - entry)
                adv = sgn * ((l[j] if direction == "LONG" else h[j]) - entry)
                hi, lo = max(hi, fav / risk), min(lo, adv / risk)
                for L in (0.5, 1.0, 1.5):
                    if hit[L] is None and hi >= L:
                        hit[L] = k
                for L in (0.5, 1.0):
                    if stop[L] is None and lo <= -L:
                        stop[L] = k
                if k in MK:
                    mfe[k], mae[k] = hi, lo
                    sret[k] = 100.0 * sgn * (c[j] - entry) / entry
            if not mfe:
                continue
            # FLAT TUPLE, not a dict of dicts.
            #
            # The first version stored one dict per event holding five nested
            # dicts. C2_nobreak is by far the largest group — most
            # consolidations never break out — so that came to millions of
            # records at ~2 KB each and drove RSS past 6 GB with 3 GB of
            # system memory left. Flat floats are ~150 bytes and land in a
            # DataFrame of primitives instead of a graph of Python objects.
            nan = np.nan
            out.append((
                sym, ts[i], date[i], direction, group, float(entry),
                100.0 * risk / entry, 100.0 * width,
                width / prange if prange and prange > 0 else nan,
                mfe.get(MK[0], nan), mfe.get(MK[1], nan), mfe.get(MK[2], nan),
                mae.get(MK[0], nan), mae.get(MK[1], nan), mae.get(MK[2], nan),
                sret.get(MK[0], nan), sret.get(MK[1], nan), sret.get(MK[2], nan),
                hit[0.5] or 0, hit[1.0] or 0, hit[1.5] or 0,
                stop[0.5] or 0, stop[1.0] or 0,
            ))
    return out


COLS = ["symbol", "ts", "date", "direction", "group", "entry",
        "risk_pct", "width_pct", "contraction",
        "mfe1", "mfe2", "mfe3", "mae1", "mae2", "mae3",
        "sret1", "sret2", "sret3",
        "hit05", "hit10", "hit15", "stop05", "stop10"]
# hit/stop columns hold the BAR INDEX of first touch, 0 meaning "never".


def to_frame(rows: list) -> pd.DataFrame:
    d = pd.DataFrame(rows, columns=COLS)
    d["ts"] = pd.to_datetime(d["ts"])
    d["date"] = pd.to_datetime(d["date"])
    for c in ("direction", "group", "symbol"):
        d[c] = d[c].astype("category")
    return d


# ──────────────────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────────────────

def path_prob(d: pd.DataFrame, hit_col: str, stop_col: str):
    """P(target before stop) as bounds, plus the measured ambiguity rate.

    hit/stop columns hold the bar index of first touch, 0 = never touched.
    A tie (same bar) is unknowable from OHLC, so it sits in the gap between
    the conservative and optimistic bounds rather than being resolved.
    """
    n = len(d)
    if not n:
        return None
    hb, sb = d[hit_col].to_numpy(), d[stop_col].to_numpy()
    hit, stop = hb > 0, sb > 0
    win = hit & (~stop | (hb < sb))
    amb = hit & stop & (hb == sb)
    return win.sum() / n, (win.sum() + amb.sum()) / n, amb.sum() / n


def row(d: pd.DataFrame, label: str, indent="  "):
    if not len(d):
        print(f"{indent}{label:<24} (none)")
        return
    line = f"{indent}{label:<24}{len(d):>9,}"
    for c in ("mfe1", "mfe2", "mfe3", "mae1", "mae2", "mae3"):
        line += f"{d[c].mean():>8.3f}"
    line += f"{d['sret3'].mean():>9.4f}"
    for hc, sc in (("hit05", "stop05"), ("hit10", "stop10"), ("hit15", "stop10")):
        p = path_prob(d, hc, sc)
        line += f"{100 * p[0]:>7.1f}%" if p else f"{'-':>8}"
    print(line)


def head(indent="  "):
    print(f"{indent}{'group':<24}{'n':>9}"
          + "".join(f"{f'MFE{m}':>8}" for m in ("5m", "10m", "15m"))
          + "".join(f"{f'MAE{m}':>8}" for m in ("5m", "10m", "15m"))
          + f"{'sret15':>9}{'+.5R':>8}{'+1R':>8}{'+1.5R':>8}")


def bucket_of(ts) -> str:
    hm = ts.strftime("%H:%M")
    for name, a, b in BUCKETS:
        if a <= hm < b:
            return name
    return "other"


BOOT_MAX_N = 200_000
BOOT_CELLS = 20_000_000        # index elements held at once


def boot(x, n_boot=10_000, seed=42):
    """Bootstrap the mean without materialising an (n_boot x n) index matrix.

    The first version did exactly that and asked for 224 GiB on the 3.0M-row
    control group. Two changes:

    1. CHUNKED over n_boot, so peak memory is bounded by BOOT_CELLS regardless
       of sample size.
    2. Samples above BOOT_MAX_N are randomly SUBSAMPLED first, and the result
       says so. Subsampling widens the interval — it can never manufacture
       significance, only fail to detect it. That is the safe direction for a
       control group, whose job is to be beaten.
    """
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    n_full = len(x)
    if n_full < 20:
        return None
    rng = np.random.default_rng(seed)
    sub = n_full > BOOT_MAX_N
    if sub:
        x = rng.choice(x, size=BOOT_MAX_N, replace=False)
    n = len(x)
    batch = max(1, BOOT_CELLS // n)
    means = np.empty(n_boot, dtype=float)
    done = 0
    while done < n_boot:
        k = min(batch, n_boot - done)
        idx = rng.integers(0, n, size=(k, n))
        means[done:done + k] = x[idx].mean(axis=1)
        done += k
    return dict(mean=float(x.mean()), lo=float(np.percentile(means, 2.5)),
                hi=float(np.percentile(means, 97.5)),
                p_le0=float((means <= 0).mean()),
                n=n_full, sub=sub)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--res", choices=["5min", "1min"], default="5min")
    a = ap.parse_args()
    MK = marks_for(a.res)

    print("=" * 118, flush=True)
    print(f"HOD_CONSOLIDATION_BREAKOUT_SCALP — Stage A + controls  [{a.res}]")
    print("=" * 118, flush=True)
    bars = load(a.res)
    if bars.empty:
        return
    span = "25 min" if a.res == "5min" else "5 min"
    print(f"  bars {len(bars):,} | tickers {bars['symbol'].nunique()} | "
          f"sessions {bars['ts'].dt.normalize().nunique():,} | "
          f"{bars['ts'].min().date()} .. {bars['ts'].max().date()}")
    print(f"  NOTE: a {CORE['cons_bars']}-bar consolidation is {span} at this "
          f"resolution.")
    if a.res == "1min":
        print("  NOTE: 1-min bars cover 09:30-10:44 only — one partial bucket.")
    print(f"  marks: {MK} bars = 5/10/15 minutes", flush=True)

    # Cache the scanned events. Three runs have now been lost to a failure
    # AFTER the expensive part — a timeout during a final concat, an OOM, and
    # a bootstrap allocation. The scan is the costly step; persist it so a
    # reporting bug costs seconds to retry instead of twenty minutes.
    ev_cache = WORK / f"hod_cons_events_{a.res}.parquet"
    if ev_cache.exists():
        d = pd.read_parquet(ev_cache)
        for cc in ("direction", "group", "symbol"):
            d[cc] = d[cc].astype("category")
        print(f"  events: cached {len(d):,} from {ev_cache.name}", flush=True)
    else:
        rows = []
        syms = list(bars.groupby("symbol"))
        for n, (s, g) in enumerate(syms, 1):
            rows += scan(prepare(g), CORE, a.res)
            if n % 25 == 0 or n == len(syms):
                print(f"    scanned {n}/{len(syms)} tickers, "
                      f"{len(rows):,} events", flush=True)
        if not rows:
            print("\n  No events found.")
            return
        d = to_frame(rows)
        del rows
        tmp = ev_cache.with_suffix(".tmp")
        d.to_parquet(tmp)
        tmp.replace(ev_cache)
        print(f"  events cached -> {ev_cache.name}", flush=True)
    print(f"  frame memory: {d.memory_usage(deep=True).sum() / 1e6:,.0f} MB",
          flush=True)

    vc = d["group"].value_counts()
    print(f"\n  SIGNAL FUNNEL (core config {CORE})")
    print(f"    consolidations near extreme, compressed, valid risk : {len(d):,}")
    for k in ("TREATED", "C1_volfail", "C2_nobreak"):
        print(f"      {k:<14} {int(vc.get(k, 0)):>9,}")

    T = d[d["group"] == "TREATED"]
    if len(T):
        rp = T["risk_pct"]
        print(f"\n  risk distance % (TREATED): mean {rp.mean():.3f} "
              f"median {rp.median():.3f} p10 {rp.quantile(.10):.3f} "
              f"p90 {rp.quantile(.90):.3f}")
        for bps in (2, 5):
            rt = 2 * bps / 100.0
            frac = rt / rp.median()
            print(f"    round-trip {bps} bps = {rt:.3f}% of price = "
                  f"{100 * frac:.0f}% of median risk"
                  + ("   <-- COSTS DOMINATE" if frac > 0.20 else ""))
        print(f"    contraction ratio (cons/prev range): median "
              f"{T['contraction'].median():.3f}")

    print("\n" + "=" * 118)
    print("STAGE A — excursion in R, signed return %, path probs "
          "(conservative bound)")
    print("=" * 118)
    head()
    for k in ("TREATED", "C1_volfail", "C2_nobreak"):
        row(d[d["group"] == k], k)

    amb = path_prob(T, "hit10", "stop10")
    if amb:
        flag = ("LOW — the ordering caveat is immaterial here" if amb[2] < 0.02
                else "HIGH — spec section 3 requires downgrading the verdict")
        print(f"\n  ambiguity rate (one bar spans +1R and -1R): "
              f"{100 * amb[2]:.2f}%   {flag}")
        print(f"  P(+1R before -1R): conservative {100 * amb[0]:.1f}%  "
              f"optimistic {100 * amb[1]:.1f}%")

    print("\n  WHY THE CONTROL COMPARISON USES sret, NOT R:")
    print("    C2_nobreak did not break out, so its entry sits inside the")
    print("    consolidation and its risk denominator (entry - cons_low) is")
    print("    tiny. That inflates its R-normalised MFE/MAE without meaning")
    print("    anything. Signed return in % shares one denominator across all")
    print("    three groups and is the only like-for-like measure here.")
    print("\n  CONTROL COMPARISON — signed return at 15m (direction-adjusted)")
    means = {}
    for k in ("TREATED", "C1_volfail", "C2_nobreak"):
        b = boot(d.loc[d["group"] == k, "sret3"].to_numpy())
        if not b:
            print(f"    {k:<14} insufficient sample")
            continue
        means[k] = b["mean"]
        tag = f"  [boot on {BOOT_MAX_N:,} of {b['n']:,}]" if b["sub"] else ""
        print(f"    {k:<14} mean {b['mean']:+.4f}%  95% CI "
              f"[{b['lo']:+.4f},{b['hi']:+.4f}]  P(<=0) {b['p_le0']:.3f}{tag}")
    for k in ("C1_volfail", "C2_nobreak"):
        if "TREATED" in means and k in means:
            print(f"    TREATED minus {k:<12} {means['TREATED'] - means[k]:+.4f}%")

    print("\n" + "=" * 118)
    print("BREAKDOWN — TREATED only")
    print("=" * 118)
    head()
    for dr in ("LONG", "SHORT"):
        row(T[T["direction"] == dr], dr)
    print()
    tb = T["ts"].dt.strftime("%H:%M")
    for name, lo, hi in BUCKETS:
        row(T[(tb >= lo) & (tb < hi)], name)
    print()
    for y in sorted(T["date"].dt.year.unique()):
        row(T[T["date"].dt.year == y], str(y))

    regime = load_regime()
    if regime and a.res == "5min":
        print()
        lab = T["date"].map(regime)
        for st in ("Calm", "Normal", "Stress"):
            row(T[lab == st], f"regime {st}")
        cov = lab.notna().mean()
        print(f"  regime coverage {100 * cov:.1f}%  "
              f"(labelled {int(lab.notna().sum()):,} / "
              f"unlabelled {int(lab.isna().sum()):,})")
    else:
        print("\n  REGIME BREAKDOWN UNAVAILABLE for this resolution/period")

    if len(T):
        vt = T["symbol"].value_counts()
        top5 = list(vt.head(5).index)
        print(f"\n  ticker concentration: top5 "
              f"{100 * vt.head(5).sum() / len(T):.1f}%  "
              f"top10 {100 * vt.head(10).sum() / len(T):.1f}%")
        b_all = boot(T["sret3"].to_numpy())
        b_ex = boot(T.loc[~T["symbol"].isin(top5), "sret3"].to_numpy())
        if b_all and b_ex:
            print(f"    signed return 15m: all {b_all['mean']:+.4f}%  "
                  f"excluding top5 {b_ex['mean']:+.4f}%")

    print("\n" + "=" * 118)
    print("KILL CRITERIA (spec section 21)")
    print("=" * 118)
    print("  MFE ~ |MAE| and signed return ~ 0  -> diffusion, not direction")
    print("  TREATED not beating C1_volfail     -> the volume rule adds nothing")
    print("  TREATED not beating C2_nobreak     -> the breakout adds nothing")
    print("=" * 118)


if __name__ == "__main__":
    main()
