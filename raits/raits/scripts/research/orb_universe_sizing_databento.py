"""
ORB gapper-universe sizing, measured on Databento daily bars.
(RESEARCH ONLY — raits/raits/scripts/research/. Touches no production code.)

WHY DATABENTO AND NOT POLYGON FOR THIS STEP
-------------------------------------------
Two reasons, the first of which is methodological and matters more than cost.

1. SURVIVORSHIP. Sizing a gapper universe needs the list of tickers that
   traded AT THE TIME, not the list that still trades today. Pulling
   "current US common stocks" from a reference endpoint and applying it
   backwards silently drops every delisted, acquired, or renamed name — and
   delisted names are disproportionately the volatile ones a gapper strategy
   would have selected. Databento's ALL_SYMBOLS over a historical range
   returns what actually traded in that range, so the bias never enters.

2. ONE FRAME. The universe is selected on daily bars and the strategy is
   executed on 1-minute bars. If those come from different vendors, the
   selection and the execution disagree in ways nothing downstream can
   detect. Sizing on the SAME dataset and the SAME window that will later
   be bought for 1-minute keeps a single frame end to end.

WHAT IT DOES
------------
Phase 1 (default, FREE — metadata only, downloads nothing):
    Discovers datasets carrying BOTH ohlcv-1d and ohlcv-1m (a dataset is only
    useful here if it can serve both the sizing and the eventual execution
    pull), reports history coverage, and prices ohlcv-1d over ALL_SYMBOLS.

Phase 2 (--fetch, COSTS MONEY, requires --approve-cost):
    Downloads the daily bars priced in phase 1 and caches them to parquet.

Phase 3 (--analyze, free, runs on the phase-2 cache):
    Measures the point-in-time gap-rate distribution, runs the REAL
    ORBUniverseScanner over the widened pool on a rolling T-1 basis, and
    projects ORB_RETEST_SCALP trade count using the conversion rates measured
    by orb_breakout_funnel_count.py.

WHY THE SCANNER IS REUSED UNCHANGED
-----------------------------------
ORBUniverseScanner ranks by gap_freq x followthrough over a trailing 60-day
window using T-1 data. That is point-in-time by construction. Hand-picking
tickers from a full-sample gap table (TSLA, MU, AMD ...) would be look-ahead:
the ranking would encode outcomes the strategy could not have known. So the
POOL is widened and top_n is raised, but the ranking rule is untouched.

CONVERSION — anchored end-to-end on realised trades
---------------------------------------------------
Only the GAP leg of ORBStrategy.run_scanner is computable from daily bars; the
price band and the two-path opening-volume test are intraday. Measured on
2017-2022, that omission matters a lot: 3,174 ticker-days clear gap>=1.5% but
run_scanner passes only 870 of them (27.4%).

So the projection uses ONE ratio measured against reality rather than a product
of per-stage rates:
    gap>=1.5% ticker-days  3,174   ->   ORB trades booked  80   =  2.52%
See the R_GAPONLY_TO_ORB comment for why end-to-end beats decomposition here.

Self-check on the anchor: 3,174 x 2.52% x 1.114 = 89.1, reproducing the 89 that
orb_breakout_funnel_count.py reported independently for the same period.

Requires:
    set DATABENTO_API_KEY=db-XXXXXXXX

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\orb_universe_sizing_databento.py
    python raits\\raits\\scripts\\research\\orb_universe_sizing_databento.py --fetch --approve-cost
    python raits\\raits\\scripts\\research\\orb_universe_sizing_databento.py --analyze
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from raits.strategies.universe_scanner import ORBUniverseScanner  # noqa: E402

OUT_DIR = _ROOT / "raits" / "data" / "cache" / "research_daily"
DAILY_PARQUET = OUT_DIR / "databento_ohlcv1d.parquet"

# Target window = the consolidated-dataset era. Chosen because the consolidated
# US equity datasets begin 2023-03-28 (measured by databento_1min_cost_probe.py)
# and because a wide mid-cap gapper universe cannot be served by single-venue
# data without severe high/low truncation.
WIN_START, WIN_END = "2023-03-28", "2026-08-01"

SIZING_SCHEMA = "ohlcv-1d"
EXEC_SCHEMA = "ohlcv-1m"

# ── Conversion: gap-only ticker-days -> trades ───────────────────────────────
#
# This script can only apply the GAP leg of ORBStrategy.run_scanner. The other
# two legs (price band, and the two-path volume test comparing the opening
# 5-minute bar against its own 20-day average) need intraday bars, which daily
# data does not contain. So `scanner_pass` here is a gap-only count and needs a
# conversion measured against reality, not a chain of per-stage guesses.
#
# Measured on 2017-2022 (top_n=10, the real ORBUniverseScanner over the daily
# cache — its ticker-day count reproduced the funnel's 14,490 exactly):
#     gap>=1.5% ticker-days                 3,174
#     ORB trades actually booked               80   (results_20260707_110323.pkl)
#     -> END-TO-END                         2.52%
#
# End-to-end is used deliberately instead of multiplying per-stage rates. The
# funnel that produced those per-stage rates fed run_scanner premarket_volume=0
# (it loaded only 09:30-10:20 bars) whereas the engine passes real pre-market
# volume, so the funnel was STRICTER at the volume leg and looser at the regime
# leg. A single ratio anchored on the realised trade count absorbs both errors;
# decomposing them would require knowing which stage each cut belongs to.
R_GAPONLY_TO_ORB = 80 / 3174

# ORB_RETEST_SCALP triggers off BREAKOUTS, while the 80 above are CONFIRMED
# entries. Funnel-measured on the same run: retest/breakout = 61.6% at the
# 0.20% tolerance, confirm/breakout = 55.3%. So the retest population is
# 61.6/55.3 = 1.114x the confirmed population.
# CAVEAT: both ratios were measured on the volume-confirmed subset; on a wider
# pool they may differ. Second-order relative to the 2.52% anchor.
R_RETEST_VS_CONFIRM = 0.616 / 0.553

# The spec's "2-4 bars" means 2-4 MINUTES at 1-minute resolution. The funnel's
# proxy allowed 4 bars of 5-minute data = 20 minutes of lookahead, so its
# retest rate is inflated. Halving is a rough, explicitly-stated discount.
R_WINDOW_DISCOUNT = 0.5

# Scanner settings. top_n is the lever the widened pool unlocks; the RANKING
# rule is deliberately left at library defaults.
TOP_N_GRID = (10, 15, 25, 40)

# Scanner-equivalent daily gate, applied for the gap-rate measurement only.
GAP_THRESHOLD = 0.015
MIN_PRICE, MAX_PRICE = 10.0, 1000.0

# Above this, an overnight move is a corporate action, not a gap. Databento
# ohlcv is UNADJUSTED, so reverse splits show up as astronomical gaps (AKTS:
# prev_close $0.0167 -> open $27.09). A ranker that scores on gap frequency
# will happily chase them, so they are excluded rather than merely noted.
# 50% is deliberately loose: real single-name overnight moves that large are
# rare but do happen (buyouts, biotech readouts), and the cost of keeping a
# few genuine ones is far lower than the cost of admitting split artifacts.
MAX_REAL_GAP = 0.50


def _client():
    key = os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        print("=" * 78)
        print("NO API KEY — nothing fetched, no cost incurred")
        print("=" * 78)
        print("  PowerShell:  $env:DATABENTO_API_KEY = 'db-XXXXXXXX'")
        return None
    import databento as db
    return db.Historical(key)


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — metadata only
# ──────────────────────────────────────────────────────────────────────────────

def phase1(client) -> list:
    print("=" * 78)
    print("PHASE 1 — dataset discovery + ohlcv-1d cost (metadata only, $0)")
    print("=" * 78)
    print(f"  window : {WIN_START} .. {WIN_END}")

    try:
        datasets = sorted(client.metadata.list_datasets())
    except Exception as e:
        print(f"  ERROR listing datasets — {type(e).__name__}: {str(e)[:200]}")
        return []

    usable = []
    for ds in datasets:
        try:
            schemas = set(client.metadata.list_schemas(dataset=ds))
        except Exception:
            continue
        # Only datasets that can serve BOTH steps are worth sizing on — sizing
        # on a dataset you cannot later execute against reintroduces the
        # two-vendor problem this script exists to avoid.
        if not {SIZING_SCHEMA, EXEC_SCHEMA} <= schemas:
            continue
        try:
            rng = client.metadata.get_dataset_range(dataset=ds)
        except Exception:
            continue
        start = str(rng.get("start", rng.get("start_date", "?")))[:10]
        end = str(rng.get("end", rng.get("end_date", "?")))[:10]
        if end < WIN_START:
            continue

        s, e = max(WIN_START, start), min(WIN_END, end)
        print(f"\n  {ds:<16} history {start} .. {end}")
        print(f"  {'':<16} usable overlap {s} .. {e}")

        # ALL_SYMBOLS is the whole point: it yields the instruments that
        # actually traded in the window, delistings included.
        got = False
        for sym_arg, label in (("ALL_SYMBOLS", "ALL_SYMBOLS"),
                               (["ALL_SYMBOLS"], "['ALL_SYMBOLS']")):
            try:
                cost = client.metadata.get_cost(
                    dataset=ds, symbols=sym_arg, schema=SIZING_SCHEMA,
                    start=s, end=e,
                )
                size = client.metadata.get_billable_size(
                    dataset=ds, symbols=sym_arg, schema=SIZING_SCHEMA,
                    start=s, end=e,
                )
                print(f"  {'':<16} ohlcv-1d {label:<16} ${float(cost):>8,.2f}"
                      f"   ({size / 1e6:,.1f} MB)")
                usable.append({"dataset": ds, "start": s, "end": e,
                               "cost": float(cost), "size": int(size),
                               "sym_arg": sym_arg})
                got = True
                break
            except Exception as e2:
                print(f"  {'':<16} ohlcv-1d {label:<16} ERROR — "
                      f"{type(e2).__name__}: {str(e2)[:100]}")
        if not got:
            print(f"  {'':<16} -> ALL_SYMBOLS not accepted here; skipping")

    print("\n" + "-" * 78)
    if not usable:
        print("  No dataset serves both ohlcv-1d and ohlcv-1m over the window.")
    else:
        usable.sort(key=lambda r: r["cost"])
        print("  CHEAPEST FIRST")
        for r in usable:
            print(f"    {r['dataset']:<16} ${r['cost']:>8,.2f}   "
                  f"{r['start']} .. {r['end']}")
        print("\n  Sizing on daily bars is cheap because a day is 390x fewer")
        print("  records than a minute. Fetch the cheapest dataset that is")
        print("  CONSOLIDATED — a single-venue daily bar gives a distorted")
        print("  open/prev-close, which is exactly what the gap measurement is.")
    print("-" * 78)
    return usable


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — fetch (costs money)
# ──────────────────────────────────────────────────────────────────────────────

def phase2(client, choice: dict) -> None:
    print("\n" + "=" * 78)
    print("PHASE 2 — fetching daily bars (THIS COSTS MONEY)")
    print("=" * 78)
    print(f"  dataset : {choice['dataset']}")
    print(f"  window  : {choice['start']} .. {choice['end']}")
    print(f"  quoted  : ${choice['cost']:,.2f}  ({choice['size'] / 1e6:,.1f} MB)")

    data = client.timeseries.get_range(
        dataset=choice["dataset"], schema=SIZING_SCHEMA,
        symbols=choice["sym_arg"], start=choice["start"], end=choice["end"],
    )
    try:
        df = data.to_df(map_symbols=True)
    except TypeError:
        df = data.to_df()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(DAILY_PARQUET)
    print(f"\n  rows written : {len(df):,}")
    print(f"  path         : {DAILY_PARQUET}")
    cols = list(df.columns)
    print(f"  columns      : {cols}")
    # Presence of the column is NOT enough: an ALL_SYMBOLS request returns the
    # column fully null when the store carries no symbology mapping. Check the
    # values, not the schema.
    mapped = int(df["symbol"].notna().sum()) if "symbol" in cols else 0
    if mapped == 0:
        print(f"\n  WARNING: `symbol` is empty for all {len(df):,} rows —")
        print("  symbols did not map. The price data is fine and is saved; only")
        print("  the ticker mapping is missing. Recover it WITHOUT re-buying:")
        print("      --resolve-symbols")
    else:
        print(f"  symbols mapped: {mapped:,} / {len(df):,} rows")


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2b — repair symbology (no data transferred, so no data charge)
# ──────────────────────────────────────────────────────────────────────────────

def phase_resolve(client, dataset: str) -> None:
    """
    An ALL_SYMBOLS ohlcv request can come back with instrument_id populated but
    `symbol` entirely null — the store carries no symbology mapping to apply.
    The bars themselves are complete, so this repairs the mapping in place
    rather than re-purchasing anything.

    instrument_id is NOT a stable key across time: the same id can denote
    different tickers in different date intervals. symbology.resolve returns
    interval-scoped mappings, so the join below is interval-aware (merge_asof
    on the interval start, then an explicit end-date check). Treating the id
    as a fixed key would silently glue two different companies together.
    """
    print("\n" + "=" * 78)
    print("PHASE 2b — resolving instrument_id -> ticker")
    print("=" * 78)
    if not DAILY_PARQUET.exists():
        print(f"  No cache at {DAILY_PARQUET}")
        return

    df = pd.read_parquet(DAILY_PARQUET)
    ids = sorted(int(i) for i in df["instrument_id"].unique())
    d0 = pd.Timestamp(df.index.min()).date()
    d1 = (pd.Timestamp(df.index.max()) + pd.Timedelta(days=1)).date()
    print(f"  instrument_ids : {len(ids):,}")
    print(f"  date range     : {d0} .. {d1}")

    CHUNK = 2000   # API limit, per resolve() docstring
    rows = []
    for k in range(0, len(ids), CHUNK):
        part = ids[k:k + CHUNK]
        try:
            res = client.symbology.resolve(
                dataset=dataset, symbols=[str(i) for i in part],
                stype_in="instrument_id", stype_out="raw_symbol",
                start_date=str(d0), end_date=str(d1),
            )
        except Exception as e:
            print(f"  chunk {k // CHUNK + 1}: ERROR — {type(e).__name__}: {str(e)[:160]}")
            continue
        mappings = res.get("result", res) or {}
        for key, entries in mappings.items():
            for ent in entries or []:
                rows.append({
                    "instrument_id": int(key),
                    "d0": pd.Timestamp(ent["d0"]),
                    "d1": pd.Timestamp(ent["d1"]),
                    "symbol": ent["s"],
                })
        print(f"  chunk {k // CHUNK + 1}/{(len(ids) + CHUNK - 1) // CHUNK}: "
              f"{len(rows):,} mappings so far", flush=True)

    if not rows:
        print("\n  No mappings returned — cannot repair. Nothing written.")
        return

    m = pd.DataFrame(rows).sort_values(["d0", "instrument_id"])
    print(f"\n  mappings       : {len(m):,}")
    print(f"  ids covered    : {m['instrument_id'].nunique():,} / {len(ids):,}")
    multi = int((m.groupby("instrument_id").size() > 1).sum())
    print(f"  ids whose ticker CHANGES over the window: {multi:,}")

    left = df.reset_index().rename(columns={"index": "ts_event"})
    left["date"] = pd.to_datetime(left["ts_event"]).dt.tz_localize(None).dt.normalize()
    left = left.sort_values("date")
    left = left.drop(columns=["symbol"], errors="ignore")

    # merge_asof demands identical dtypes on BOTH join keys, and the two frames
    # disagree on both: parquet round-trips instrument_id as uint32 while the
    # mapping frame builds int64, and the parquet timestamps are ns while
    # Timestamps constructed from resolve's date strings come back as us.
    # Pin every join key explicitly instead of trusting either side's inference.
    right = m.rename(columns={"d0": "date"}).copy()
    for f in (left, right):
        f["instrument_id"] = f["instrument_id"].astype("int64")
        f["date"] = f["date"].astype("datetime64[ns]")
    right["d1"] = right["d1"].astype("datetime64[ns]")
    left = left.sort_values("date")
    right = right.sort_values("date")

    joined = pd.merge_asof(
        left, right,
        on="date", by="instrument_id", direction="backward",
    )
    # merge_asof only honours the interval START; drop rows past the interval end.
    bad = joined["d1"].notna() & (joined["date"] >= joined["d1"])
    joined.loc[bad, "symbol"] = None
    joined = joined.drop(columns=["d1"])

    ok = int(joined["symbol"].notna().sum())
    print(f"  rows mapped    : {ok:,} / {len(joined):,} "
          f"({100.0 * ok / max(len(joined), 1):.1f}%)")
    if bad.any():
        print(f"  rows dropped for falling past the interval end: {int(bad.sum()):,}")
    if ok == 0:
        print("\n  Still zero — not writing. Inspect the resolve response shape.")
        return

    joined = joined.set_index("ts_event")
    joined.to_parquet(DAILY_PARQUET)
    print(f"  written        : {DAILY_PARQUET}")
    print("  Now run:  --analyze")


# ──────────────────────────────────────────────────────────────────────────────
# Vectorised equivalent of ORBUniverseScanner.scan
# ──────────────────────────────────────────────────────────────────────────────
#
# WHY THIS EXISTS
# ---------------
# ORBUniverseScanner.scan re-slices the ENTIRE pool on every call:
#     df = daily_data[t]; df = df[df.index.normalize() <= scan_date]
# That is an O(n) mask plus a fresh .normalize() allocation per (ticker, day).
# At 5,000 symbols x 168 sampled days that is 840,000 of them, and it dominates
# the whole script's runtime.
#
# The production class is NOT modified — it is untouchable and it stays the
# reference. This computes the identical quantities with groupby().rolling(),
# turning 840k Python-level slices into a handful of vectorised passes.
#
# EQUIVALENCE IS ASSERTED, NOT ASSUMED. --verify-scanner runs both this and the
# real class over the 37-ticker daily cache and requires the selected lists to
# match exactly, day by day. A fast reimplementation that silently disagrees
# would corrupt every number downstream while looking perfectly plausible.
#
# Details that must match exactly, from the class body:
#   * window = last (lookback_days + 1) EXISTING rows, then .iloc[1:] -> the
#     60 observations ending at scan_date. A trailing global rolling(60) over
#     each symbol's own consecutive rows is the same thing; a calendar-day
#     window would NOT be (symbols do not trade every day).
#   * gap_pct uses the previous EXISTING row's close, so groupby().shift(1).
#   * NaN gap (prev_close missing/zero) compares False, i.e. "not a gap".
#   * followthrough = mean over gap days only; 0.0 when there are none.
#   * filters: >= lookback+1 bars, trailing-20 mean volume >= min_avg_volume,
#     gap_freq >= min_gap_freq.
#   * ranking: list.sort(key=score, reverse=True) is STABLE, so ties keep the
#     pool's iteration order -> tie-break on pool index, never on symbol name.

def vectorised_scores(long_df: pd.DataFrame, pool_index: dict,
                      lookback_days: int = 60, gap_threshold: float = 0.01,
                      min_gap_freq: float = 0.05,
                      min_avg_volume: float = 500_000) -> pd.DataFrame:
    d = long_df.sort_values(["symbol", "date"]).copy()
    g = d.groupby("symbol", sort=False)

    prev_close = g["close"].shift(1)
    gap_dir = d["open"] - prev_close
    gap_pct = gap_dir.abs() / prev_close
    intraday = d["close"] - d["open"]

    is_gap = (gap_pct >= gap_threshold).fillna(False)
    ft_ok = is_gap & ((gap_dir * intraday) > 0).fillna(False)

    d["_is_gap"] = is_gap.astype(float)
    d["_ft_ok"] = ft_ok.astype(float)

    gg = d.groupby("symbol", sort=False)
    n_gap = gg["_is_gap"].rolling(lookback_days).sum().reset_index(level=0, drop=True)
    n_ft = gg["_ft_ok"].rolling(lookback_days).sum().reset_index(level=0, drop=True)
    avg_vol = gg["volume"].rolling(20).mean().reset_index(level=0, drop=True)
    bars = gg.cumcount() + 1

    gap_freq = n_gap / lookback_days
    followthrough = (n_ft / n_gap).fillna(0.0)

    out = pd.DataFrame({
        "date": d["date"].values,
        "symbol": d["symbol"].values,
        "score": (gap_freq * followthrough).values,
        "gap_freq": gap_freq.values,
        "eligible": ((bars >= lookback_days + 1)
                     & (avg_vol >= min_avg_volume)
                     & (gap_freq >= min_gap_freq)).values,
    })
    out["pool_ix"] = out["symbol"].map(pool_index).fillna(1 << 30).astype("int64")
    return out


def select_topn(scores_today: pd.DataFrame, top_n: int) -> list:
    e = scores_today[scores_today["eligible"]]
    if e.empty:
        return []
    e = e.sort_values(["score", "pool_ix"], ascending=[False, True], kind="mergesort")
    return e["symbol"].head(top_n).tolist()


def verify_scanner(n_days: int = 60, top_n: int = 40) -> bool:
    """Assert the vectorised path reproduces ORBUniverseScanner exactly."""
    import glob
    print("=" * 78)
    print("VERIFY — vectorised scanner vs the real ORBUniverseScanner")
    print("=" * 78)
    daily, rows = {}, []
    for f in glob.glob(str(_ROOT / "raits" / "data" / "cache" / "daily" / "*_daily_*.parquet")):
        t = os.path.basename(f).split("_daily_")[0]
        x = pd.read_parquet(f)
        x = x[(x.index >= "2017-01-01") & (x.index <= "2022-12-31")]
        if len(x) <= 60:
            continue
        daily[t] = x
        r = x.reset_index()
        r.columns = ["date"] + list(r.columns[1:])
        r["symbol"] = t
        rows.append(r[["symbol", "date", "open", "high", "low", "close", "volume"]])
    if not rows:
        print("  no daily cache found — cannot verify")
        return False

    long_df = pd.concat(rows, ignore_index=True)
    long_df["date"] = pd.to_datetime(long_df["date"]).dt.normalize()
    pool = sorted(daily)
    pool_index = {s: i for i, s in enumerate(pool)}

    sc = ORBUniverseScanner(top_n=top_n)          # default pool = CANDIDATE_POOL
    sc_pool = ORBUniverseScanner(top_n=top_n, candidate_pool=pool)
    _ = sc                                        # kept for documentation only
    scores = vectorised_scores(long_df, pool_index)
    by_day = {d: g for d, g in scores.groupby("date")}

    dates = sorted(long_df["date"].unique())
    test = dates[-n_days:]
    ok, bad = 0, []
    for d0 in test:
        want = sc_pool.scan(daily, pd.Timestamp(d0))
        got = select_topn(by_day.get(d0, scores.iloc[0:0]), top_n)
        if want == got:
            ok += 1
        else:
            bad.append((d0, want, got))

    print(f"  days compared : {len(test)}")
    print(f"  exact match   : {ok}/{len(test)}")
    if bad:
        print(f"  MISMATCHES    : {len(bad)} — showing first 3")
        for d0, w, gt in bad[:3]:
            print(f"    {pd.Timestamp(d0).date()}")
            print(f"      real : {w}")
            print(f"      fast : {gt}")
        print("\n  VERDICT: FAIL — do not use --fast; the numbers would be wrong.")
        return False
    print("\n  VERDICT: PASS — vectorised path is exact; --fast is safe.")
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Dataset validation — which feed actually carries the consolidated tape?
# ──────────────────────────────────────────────────────────────────────────────
#
# EQUS.MINI looked like the obvious buy: consolidated-sounding name, right
# window, $12 for daily and $54 for the 1-minute execution pull. Measured
# against the Polygon daily cache over their 2023-03-28..2024-12-31 overlap, it
# carries a MEDIAN 5.2% of consolidated volume — AAPL 1.56M shares on a day
# AAPL traded ~50M. It is a thin slice, not a tape.
#
# That is disqualifying for ORB_RETEST_SCALP specifically: the whole strategy
# turns on whether `low` came within 0.10-0.30% of OR_high, and a feed missing
# 95% of prints under-detects touches systematically, in one direction, while
# also producing an OR that is too narrow. Both errors push the same way.
#
# So: measure every candidate the same way BEFORE buying its 1-minute data.
# Daily bars for 38 tickers over one year cost cents.
#
# TWO ADJUSTMENTS THE COMPARISON MUST MAKE, or it reports nonsense:
#
#   1. Databento ohlcv is RAW; Polygon daily is SPLIT-ADJUSTED retroactively.
#      NVDA on 2024-06-03 reads $1,154.50 (Databento, the price that actually
#      traded) vs $115.00 (Polygon, adjusted for the 10:1 split a week later).
#      Neither is wrong. So the split factor is recovered per symbol as
#      f = median(close_db / close_pg) and divided out.
#   2. Adjusted VOLUME scales inversely to adjusted price, so Polygon's volume
#      is f times the real figure. True coverage is therefore
#          db_volume * f / pg_volume
#      Forgetting the f makes a 10:1-split name look 10x worse than it is.
#
# PASS = coverage near 1.0. EQUS.MINI scores ~0.05 and is kept in the candidate
# list on purpose, as a known-bad control: if it does not come last, the
# measurement itself is broken.

VAL_START, VAL_END = "2024-01-02", "2024-12-31"

VALIDATION_CANDIDATES = [
    "DBEQ.BASIC",       # the leading candidate — ~2x EQUS.MINI's instrument count
    "EQUS.MINI",        # known-bad control, must come out worst
    "XNAS.ITCH",        # single venue, for contrast
    "XNYS.PILLAR",      # single venue, for contrast
    "IEXG.TOPS",
    "EPRL.DOM",
    "MEMX.MEMOIR",
    "XCIS.TRADESBBO",
    "XNAS.BASIC",
]


def _polygon_daily(start: str, end: str) -> pd.DataFrame:
    import glob
    rows = []
    for f in glob.glob(str(_ROOT / "raits" / "data" / "cache" / "daily" / "*_daily_*.parquet")):
        t = os.path.basename(f).split("_daily_")[0]
        x = pd.read_parquet(f)
        x = x[(x.index >= start) & (x.index <= end)]
        if x.empty:
            continue
        r = x.reset_index()
        r.columns = ["date"] + list(r.columns[1:])
        r["symbol"] = t
        rows.append(r[["symbol", "date", "open", "high", "low", "close", "volume"]])
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out


def _fetch_daily(client, dataset: str, symbols: list) -> pd.DataFrame:
    data = client.timeseries.get_range(
        dataset=dataset, schema=SIZING_SCHEMA, symbols=symbols,
        start=VAL_START, end=VAL_END, stype_in="raw_symbol",
    )
    try:
        df = data.to_df(map_symbols=True)
    except TypeError:
        df = data.to_df()
    df = df.reset_index()
    tc = next((c for c in ("ts_event", "index", "date") if c in df.columns), None)
    df["date"] = pd.to_datetime(df[tc]).dt.tz_localize(None).dt.normalize()

    if "symbol" not in df.columns or df["symbol"].notna().sum() == 0:
        ids = sorted(int(i) for i in df["instrument_id"].unique())
        res = client.symbology.resolve(
            dataset=dataset, symbols=[str(i) for i in ids],
            stype_in="instrument_id", stype_out="raw_symbol",
            start_date=VAL_START, end_date=VAL_END,
        )
        first = {}
        for k, ents in (res.get("result", res) or {}).items():
            if ents:
                first[int(k)] = ents[0]["s"]
        df["symbol"] = df["instrument_id"].astype("int64").map(first)
    return df[["symbol", "date", "open", "high", "low", "close", "volume"]]


def validate_datasets(client, approve: bool) -> None:
    print("=" * 78)
    print("DATASET VALIDATION — consolidated-tape coverage vs the Polygon cache")
    print("=" * 78)
    print(f"  window : {VAL_START} .. {VAL_END}")

    pg = _polygon_daily(VAL_START, VAL_END)
    if pg.empty:
        print("  No Polygon daily cache in this window — cannot validate.")
        return
    syms = sorted(pg["symbol"].unique())
    print(f"  anchor : {len(syms)} tickers from the Polygon daily cache, "
          f"{len(pg):,} ticker-days")

    print("\n  quotes (metadata only, $0):")
    quotes = []
    for ds in VALIDATION_CANDIDATES:
        try:
            c = client.metadata.get_cost(
                dataset=ds, symbols=syms, schema=SIZING_SCHEMA,
                start=VAL_START, end=VAL_END, stype_in="raw_symbol",
            )
            print(f"    {ds:<16} ${float(c):>7.2f}")
            quotes.append((ds, float(c)))
        except Exception as e:
            print(f"    {ds:<16} ERROR — {type(e).__name__}: {str(e)[:90]}")
    if not quotes:
        return
    total = sum(c for _, c in quotes)
    print(f"    {'TOTAL':<16} ${total:>7.2f}")

    if not approve:
        print("\n  Nothing downloaded. Re-run with --approve-cost to fetch and")
        print("  measure. The total above is what it will charge.")
        print("=" * 78)
        return

    print(f"\n  {'dataset':<16}{'coverage':>10}{'p10':>8}{'p90':>8}"
          f"{'px resid':>10}{'tickers':>9}")
    results = []
    for ds, _ in quotes:
        try:
            db = _fetch_daily(client, ds, syms)
        except Exception as e:
            print(f"  {ds:<16} FETCH ERROR — {type(e).__name__}: {str(e)[:60]}")
            continue
        m = pg.merge(db, on=["symbol", "date"], suffixes=("_pg", "_db"))
        if m.empty:
            print(f"  {ds:<16} no overlapping rows")
            continue

        # split factor per symbol, recovered from the price ratio
        m["f"] = m["close_db"] / m["close_pg"]
        fmed = m.groupby("symbol")["f"].median()
        m["fs"] = m["symbol"].map(fmed)

        cov = (m["volume_db"] * m["fs"]) / m["volume_pg"].replace(0, pd.NA)
        cov = pd.to_numeric(cov, errors="coerce").dropna()

        # price residual AFTER dividing out the split factor: what is left is
        # genuine disagreement between the two feeds.
        resid = ((m["close_db"] / m["fs"]) - m["close_pg"]).abs() / m["close_pg"]
        resid = resid.dropna()

        print(f"  {ds:<16}{cov.median():>10.3f}{cov.quantile(.10):>8.3f}"
              f"{cov.quantile(.90):>8.3f}{100 * resid.median():>9.3f}%"
              f"{m['symbol'].nunique():>9}")
        results.append((ds, float(cov.median()), float(resid.median())))

    print("\n" + "-" * 78)
    if results:
        results.sort(key=lambda r: -r[1])
        best, bcov, bres = results[0]
        print(f"  BEST COVERAGE: {best}  ({bcov:.3f} of consolidated volume, "
              f"price residual {100 * bres:.3f}%)")
        ctrl = [r for r in results if r[0] == "EQUS.MINI"]
        if ctrl and ctrl[0][1] > 0.20:
            print("  WARNING: the known-bad control EQUS.MINI scored above 0.20.")
            print("  It measured ~0.05 previously, so THIS MEASUREMENT is suspect —")
            print("  do not act on the table above.")
        if bcov < 0.80:
            print("\n  NO dataset carries the consolidated tape. ORB_RETEST_SCALP")
            print("  is blocked on DATA QUALITY, not on sample size: a feed this")
            print("  incomplete cannot resolve a 0.10-0.30% retest tolerance.")
        else:
            print(f"\n  {best} is fit for the 1-minute pull. Price it with")
            print(f"  --price-1min --dataset {best}")
    print("=" * 78)


# ──────────────────────────────────────────────────────────────────────────────
# Extremes test — the criterion that actually matters
# ──────────────────────────────────────────────────────────────────────────────
#
# --validate-datasets scored feeds on VOLUME coverage, and by that measure
# everything fails: best single venue 0.303 (XNAS.ITCH), and the lit venues
# measured sum to well under 1.0 because a large share of US equity volume
# prints off-exchange, which no exchange feed carries.
#
# But volume was the wrong proxy. ORB_RETEST_SCALP never asks how much traded;
# it asks whether `low` came within 0.10-0.30% of OR_high. That is a question
# about price EXTREMES. Off-exchange executions generally happen at or inside
# the prevailing quote, which lit venues set, so the daily high and low can be
# nearly complete even when volume is not.
#
# So this measures the thing the strategy depends on: does max(high) / min(low)
# across the lit venues reproduce the consolidated high/low?
#
# PASS CRITERION, fixed in advance: merged high/low residual must sit well
# below 0.10%, the tightest retest tolerance in the spec. A feed whose error is
# the same size as the signal cannot test the signal.

LIT_VENUES = [
    "XNAS.ITCH", "XNYS.PILLAR", "ARCX.PILLAR", "BATS.PITCH", "BATY.PITCH",
    "EDGA.PITCH", "EDGX.PITCH", "XBOS.ITCH", "XPSX.ITCH", "XASE.PILLAR",
    "IEXG.TOPS", "MEMX.MEMOIR", "XCIS.TRADESBBO", "EPRL.DOM",
]


def validate_extremes(client, approve: bool) -> None:
    print("=" * 78)
    print("EXTREMES TEST — can merged lit venues reproduce consolidated H/L?")
    print("=" * 78)
    print(f"  window : {VAL_START} .. {VAL_END}")

    pg = _polygon_daily(VAL_START, VAL_END)
    if pg.empty:
        print("  No Polygon daily cache in this window.")
        return
    syms = sorted(pg["symbol"].unique())
    print(f"  anchor : {len(syms)} tickers, {len(pg):,} ticker-days")

    print("\n  quotes (metadata only, $0):")
    quotes = []
    for ds in LIT_VENUES:
        try:
            c = client.metadata.get_cost(
                dataset=ds, symbols=syms, schema=SIZING_SCHEMA,
                start=VAL_START, end=VAL_END, stype_in="raw_symbol",
            )
            print(f"    {ds:<16} ${float(c):>6.2f}")
            quotes.append(ds)
        except Exception as e:
            print(f"    {ds:<16} ERROR — {type(e).__name__}: {str(e)[:70]}")
    if not approve:
        print("\n  Nothing downloaded. Re-run with --approve-cost.")
        print("=" * 78)
        return

    frames = []
    for ds in quotes:
        try:
            d = _fetch_daily(client, ds, syms)
            d["venue"] = ds
            frames.append(d)
            print(f"  fetched {ds:<16} {len(d):,} rows", flush=True)
        except Exception as e:
            print(f"  {ds:<16} FETCH ERROR — {type(e).__name__}: {str(e)[:60]}")
    if not frames:
        return
    allv = pd.concat(frames, ignore_index=True)

    # Split factor per symbol, from the single deepest venue (most reliable
    # close). Databento is raw, Polygon is retro-adjusted — see validate_datasets.
    ref = allv[allv["venue"] == "XNAS.ITCH"]
    fj = ref.merge(pg, on=["symbol", "date"], suffixes=("_db", "_pg"))
    fmed = (fj["close_db"] / fj["close_pg"]).groupby(fj["symbol"]).median()

    merged = allv.groupby(["symbol", "date"]).agg(
        high=("high", "max"), low=("low", "min")).reset_index()
    m = merged.merge(pg, on=["symbol", "date"], suffixes=("_db", "_pg"))
    m["f"] = m["symbol"].map(fmed)
    m = m[m["f"].notna()]

    print(f"\n  {'feed':<22}{'high resid':>12}{'low resid':>12}{'p95 H':>10}{'p95 L':>10}")

    def _report(label, hi, lo, base):
        rh = (hi / base["f"] - base["high_pg"]).abs() / base["high_pg"]
        rl = (lo / base["f"] - base["low_pg"]).abs() / base["low_pg"]
        print(f"  {label:<22}{100 * rh.median():>11.4f}%{100 * rl.median():>11.4f}%"
              f"{100 * rh.quantile(.95):>9.3f}%{100 * rl.quantile(.95):>9.3f}%")
        return float(rh.median()), float(rl.median())

    single = allv[allv["venue"] == "XNAS.ITCH"].merge(
        pg, on=["symbol", "date"], suffixes=("_db", "_pg"))
    single["f"] = single["symbol"].map(fmed)
    single = single[single["f"].notna()]
    _report("XNAS.ITCH alone", single["high_db"], single["low_db"], single)
    mh, ml = _report(f"merged {len(quotes)} lit venues", m["high_db"], m["low_db"], m)

    print("\n" + "-" * 78)
    worst = max(mh, ml)
    print(f"  merged worst-side median residual: {100 * worst:.4f}%")
    print(f"  tightest retest tolerance in spec : 0.1000%")
    if worst < 0.0002:
        print("\n  PASS — the merged lit tape reproduces consolidated extremes to")
        print("  well inside the tolerance. The volume deficit does NOT block the")
        print("  study; buy the 1-minute data for the merged venue set.")
    elif worst < 0.0005:
        print("\n  MARGINAL — residual is a fifth of the tolerance or better, but")
        print("  not negligible. Usable only if the 0.10% tolerance arm is dropped")
        print("  and the study runs at 0.20-0.30%.")
    else:
        print("\n  FAIL — residual is the same order as the signal. Merging does")
        print("  not rescue it; ORB_RETEST_SCALP stays blocked on data quality.")
    print("=" * 78)


# ──────────────────────────────────────────────────────────────────────────────
# Extremes test, done properly — on 1-minute bars restricted to RTH
# ──────────────────────────────────────────────────────────────────────────────
#
# The ohlcv-1d version of this test was INVALID and its "MARGINAL" verdict is
# void. It compared different sessions:
#
#   Polygon daily is RTH-ONLY. Measured against the local Polygon 5-minute
#   cache over 430 ticker-days in 2021: daily high equals the 09:30-15:59 high
#   on 98.8% of days (low: 99.8%), but equals the full 04:00-20:00 high on only
#   54.2% (low: 55.6%).
#
#   Databento ohlcv-1d aggregates the whole session. So its high is >= the RTH
#   high, and merging MORE venues adds MORE extended-hours prints, pushing the
#   merged high further above Polygon's RTH high.
#
# That is exactly the signature observed: merging made the residual WORSE
# (0.0342% -> 0.0419%), which is impossible if both sides measured the same
# session — max() over more venues can only move toward the true extreme.
# A monotonic relation running backwards is the tell that the slice is wrong,
# not that the data is bad.
#
# The fix is to buy ohlcv-1m, cut it to 09:30-15:59 ET, and aggregate the daily
# high/low ourselves. Small scope: a handful of tickers over one month is
# enough to measure a residual, and it costs a couple of dollars.
#
# TIMEZONE: Databento timestamps are UTC. The cut must happen after converting
# to America/New_York, not by subtracting a fixed offset — the sample window is
# in EDT and a fixed -5 would slice an hour off the wrong end.

EXT_TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "JPM", "XOM", "AMD", "MU", "GS", "KO"]
EXT_START, EXT_END = "2024-06-03", "2024-06-28"


def validate_extremes_1m(client, approve: bool) -> None:
    print("=" * 78)
    print("EXTREMES TEST v2 — 1-minute bars, cut to RTH (09:30-15:59 ET)")
    print("=" * 78)
    print(f"  window  : {EXT_START} .. {EXT_END}")
    print(f"  tickers : {len(EXT_TICKERS)}  ({', '.join(EXT_TICKERS)})")
    print("  NOTE    : supersedes the ohlcv-1d extremes test, which compared")
    print("            Databento full-session against Polygon RTH and is void.")

    pg = _polygon_daily(EXT_START, EXT_END)
    pg = pg[pg["symbol"].isin(EXT_TICKERS)]
    if pg.empty:
        print("\n  No Polygon daily rows for these tickers/window.")
        return
    print(f"  anchor  : {len(pg):,} ticker-days from the Polygon daily cache")

    print("\n  quotes (metadata only, $0):")
    quotes, total = [], 0.0
    for ds in LIT_VENUES:
        try:
            c = float(client.metadata.get_cost(
                dataset=ds, symbols=EXT_TICKERS, schema=EXEC_SCHEMA,
                start=EXT_START, end=EXT_END, stype_in="raw_symbol",
            ))
            print(f"    {ds:<16} ${c:>6.2f}")
            quotes.append(ds)
            total += c
        except Exception as e:
            print(f"    {ds:<16} ERROR — {type(e).__name__}: {str(e)[:70]}")
    print(f"    {'TOTAL':<16} ${total:>6.2f}")

    if not approve:
        print("\n  Nothing downloaded. Re-run with --approve-cost.")
        print("=" * 78)
        return

    frames = []
    for ds in quotes:
        try:
            data = client.timeseries.get_range(
                dataset=ds, schema=EXEC_SCHEMA, symbols=EXT_TICKERS,
                start=EXT_START, end=EXT_END, stype_in="raw_symbol",
            )
            try:
                d = data.to_df(map_symbols=True)
            except TypeError:
                d = data.to_df()
            d = d.reset_index()
            tc = next(c for c in ("ts_event", "index") if c in d.columns)
            ts = pd.to_datetime(d[tc], utc=True).dt.tz_convert("America/New_York")
            d["et"] = ts
            d["date"] = ts.dt.tz_localize(None).dt.normalize()
            d["t"] = ts.dt.time
            rth = d[(d["t"] >= pd.Timestamp("09:30").time())
                    & (d["t"] <= pd.Timestamp("15:59").time())]
            agg = rth.groupby(["symbol", "date"]).agg(
                high=("high", "max"), low=("low", "min")).reset_index()
            agg["venue"] = ds
            frames.append(agg)
            print(f"  {ds:<16} {len(d):,} bars -> {len(rth):,} RTH -> "
                  f"{len(agg):,} ticker-days", flush=True)
        except Exception as e:
            print(f"  {ds:<16} ERROR — {type(e).__name__}: {str(e)[:70]}")
    if not frames:
        return
    allv = pd.concat(frames, ignore_index=True)

    ref = allv[allv["venue"] == "XNAS.ITCH"].merge(pg, on=["symbol", "date"],
                                                   suffixes=("_db", "_pg"))
    fmed = (ref["high_db"] / ref["high_pg"]).groupby(ref["symbol"]).median()

    print(f"\n  {'feed':<24}{'high resid':>12}{'low resid':>12}"
          f"{'p95 H':>10}{'p95 L':>10}")

    def _rep(label, frame):
        j = frame.merge(pg, on=["symbol", "date"], suffixes=("_db", "_pg"))
        j["f"] = j["symbol"].map(fmed)
        j = j[j["f"].notna()]
        if j.empty:
            print(f"  {label:<24}  no overlap")
            return None
        rh = (j["high_db"] / j["f"] - j["high_pg"]).abs() / j["high_pg"]
        rl = (j["low_db"] / j["f"] - j["low_pg"]).abs() / j["low_pg"]
        print(f"  {label:<24}{100 * rh.median():>11.4f}%{100 * rl.median():>11.4f}%"
              f"{100 * rh.quantile(.95):>9.4f}%{100 * rl.quantile(.95):>9.4f}%")
        return max(float(rh.median()), float(rl.median()))

    single = _rep("XNAS.ITCH alone",
                  allv[allv["venue"] == "XNAS.ITCH"][["symbol", "date", "high", "low"]])
    merged_frame = allv.groupby(["symbol", "date"]).agg(
        high=("high", "max"), low=("low", "min")).reset_index()
    merged = _rep(f"merged {len(quotes)} lit venues", merged_frame)

    print("\n" + "-" * 78)
    if single is None or merged is None:
        print("  Could not compute both legs.")
        print("=" * 78)
        return

    # The monotonic self-check that caught the ohlcv-1d error. Merging can only
    # move max()/min() toward the true extreme, so the merged residual must not
    # exceed the single-venue one. If it does, the slice is wrong again.
    print(f"  single-venue residual : {100 * single:.4f}%")
    print(f"  merged residual       : {100 * merged:.4f}%")
    if merged > single * 1.05:
        print("\n  SELF-CHECK FAILED: merging made the residual WORSE, which is")
        print("  impossible when both sides measure the same session. Something")
        print("  in the slice is still misaligned — do NOT read the verdict below.")
        print("=" * 78)
        return
    print("  self-check: merged <= single  OK")

    print(f"\n  tightest retest tolerance in spec : 0.1000%")
    if merged < 0.0002:
        print("\n  PASS — merged lit venues reproduce consolidated RTH extremes")
        print("  well inside the tolerance. Buy the 1-minute data for this venue")
        print("  set; the volume deficit does not block the study.")
    elif merged < 0.0005:
        print("\n  MARGINAL — usable only with the 0.10% tolerance arm dropped;")
        print("  run the study at 0.20-0.30% only.")
    else:
        print("\n  FAIL — residual is the same order as the signal. The strategy")
        print("  cannot be tested on exchange feeds; it needs a SIP/TRF-inclusive")
        print("  consolidated source.")
    print("=" * 78)


# ──────────────────────────────────────────────────────────────────────────────
# Extremes test on the REAL universe, with a venue-set cost/quality tradeoff
# ──────────────────────────────────────────────────────────────────────────────
#
# validate_extremes_1m() passed, but on the wrong names: 10 mega-caps. The study
# universe is 322 gappers, mostly mid- and small-cap, where a given exchange's
# share of prints is completely different. Nasdaq prints ~30% of AAPL; for a
# NYSE-listed mid-cap it is far less, and for a small-cap it may be negligible.
# So that PASS does not transfer, and this re-runs it on a random sample of the
# actual selected symbols.
#
# It also answers the money question. Extrapolating the 10-ticker quotes to the
# full study (269,836 ticker-days, ~1,500x the sample):
#     merged 14 lit venues   ~$900
#     XNAS.ITCH alone        ~$120
# and XNAS alone was already inside tolerance on the median AND better in the
# tail (p95 high 0.204% vs 0.371% merged — max() over 14 venues is not robust,
# it picks up any single venue's odd prints). So the cheapest sufficient venue
# set is worth finding rather than assuming more venues is better.
#
# POLYGON REFERENCE IS FETCHED UNADJUSTED. Every previous comparison had to
# recover a split factor because Polygon's cache is adjusted and Databento is
# raw. fetch_daily_bars(adjusted=False) removes that entire correction, and
# with it a whole class of error.

UNIV_CONFIGS = {
    "XNAS.ITCH alone": ["XNAS.ITCH"],
    "top-5 venues": ["XNAS.ITCH", "XNYS.PILLAR", "ARCX.PILLAR",
                     "BATS.PITCH", "EDGX.PITCH"],
    "all 14 lit venues": LIT_VENUES,
}

POLY_SAMPLE = OUT_DIR / "polygon_sample_daily_raw.parquet"
VENUE_CACHE = OUT_DIR / "venue_rth_daily.parquet"


def _polygon_sample(n: int, seed: int = 7) -> pd.DataFrame:
    """Fetch UNADJUSTED Polygon daily bars for a random sample of the selected
    universe. One API call per ticker for the whole range, so ~n calls."""
    import importlib.util as ilu
    import random

    if POLY_SAMPLE.exists():
        df = pd.read_parquet(POLY_SAMPLE)
        print(f"  polygon reference: cached, {df['symbol'].nunique()} tickers, "
              f"{len(df):,} rows")
        return df

    sym_file = OUT_DIR / "scanner_selected_symbols.txt"
    if not sym_file.exists():
        print(f"  No symbol list at {sym_file} — run --analyze first.")
        return pd.DataFrame()
    pool = [x.strip() for x in sym_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    random.Random(seed).shuffle(pool)
    picks = pool[:n]
    print(f"  sampling {len(picks)} of {len(pool)} selected symbols (seed={seed})")

    key = None
    for c in (_ROOT / "config_private.py", _ROOT / "raits" / "config_private.py"):
        if c.exists():
            spec = ilu.spec_from_file_location("config_private", str(c))
            mod = ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            key = getattr(mod, "POLYGON_API_KEY", None)
            if key:
                print(f"  polygon key: {c}")
                break
    if not key:
        print("  config_private.py / POLYGON_API_KEY not found.")
        return pd.DataFrame()

    from raits.data.raits_polygon_fetcher import PolygonDataFetcher
    f = PolygonDataFetcher(api_key=key)
    s, e = datetime.fromisoformat(EXT_START), datetime.fromisoformat(EXT_END)
    rows = []
    for t in picks:
        try:
            h = f.fetch_daily_bars(ticker=t, start_date=s, end_date=e,
                                   adjusted=False, use_cache=False)
            d = h.to_dataframe().reset_index()
            d.rename(columns={"timestamp": "date"}, inplace=True)
            d.columns = [c.lower() for c in d.columns]
            if d.empty:
                print(f"    {t:<6} EMPTY")
                continue
            d["symbol"] = t
            d["date"] = pd.to_datetime(d["date"]).dt.normalize()
            rows.append(d[["symbol", "date", "open", "high", "low", "close", "volume"]])
            print(f"    {t:<6} {len(d)} days")
        except Exception as ex:
            print(f"    {t:<6} ERROR {type(ex).__name__}: {str(ex)[:60]}")
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(POLY_SAMPLE)
    print(f"  cached -> {POLY_SAMPLE}")
    return out


CLASS_CACHE = OUT_DIR / "universe_classification.parquet"


def classify_universe(client, approve: bool, dataset: str = "XNAS.ITCH") -> None:
    """
    Split the selected universe into common stock vs ETF/ETN/other.

    WHY THIS MATTERS MORE THAN IT LOOKS
    -----------------------------------
    ORBUniverseScanner ranks by gap FREQUENCY. Leveraged and inverse ETFs gap
    by construction — they track a multiplied index and decay — so a
    gap-frequency ranker hunts them down systematically. It is not noise in the
    universe, it is a bias in the selection rule.

    The 18-symbol validation sample bore that out: ETHD, ETHT, SVIX, UVXY,
    BITX, PSLV, GDXD, UVIX. And they are the worst data too — ETHD's daily
    high/low disagrees with the consolidated tape by a median 1.29%, against
    0.006-0.04% for ordinary stocks in the same price band.

    Excluding them is an a-priori call on strategy logic — ORB is specified for
    news-driven single-name gappers (FDA, earnings, analyst action) — not a
    call made after seeing returns. It has to happen BEFORE the 1-minute pull,
    because it changes both n and the bill.

    NO ASSUMED CODES. The distribution of security_type / instrument_class is
    printed as it comes back; the keep-list is chosen after seeing real values,
    not from a guessed mapping.

    security_type DECODED from unambiguous examples in the pool (2026-08):
        C  common stock            AAPL, ABBV, AAL          KEEP
        O  ordinary shares         ACN, ALLE, AER, ALC      KEEP (foreign-
                                                            incorporated, trades
                                                            like US common)
        A  ADR                     ASML, ARM, ARGX, AMX     JUDGEMENT — an ADR
                                                            gaps on its home
                                                            market's overnight
                                                            session, which is
                                                            mechanical, not the
                                                            news catalyst ORB
                                                            was specified for
        Q  ETF / ETN               AAPB, AAPD, AAXJ         DROP - gap by
                                                            construction
        P  preferred               ABR-D, ACP-A, ADC-A      DROP
        S  benef. interest         AGD, AWP, BCX / AKR      DROP - CEFs and
                                                            REITs, thin
        L  limited partnership     ARLP, BIP, CQP, DKL      DROP
        W  warrant                 CORZW, IONQ+, RGTIW      DROP - derivative
        U  unit                    AQNU, BTSGU, NEE-R       DROP - SPAC units
        V  royalty trust           CRT, MSB, PBT, SBR       DROP - thin
    """
    print("=" * 78)
    print("UNIVERSE CLASSIFICATION — common stock vs ETF/ETN")
    print("=" * 78)
    # Classify the WHOLE tradeable pool, not just the 322 already selected.
    # Filtering the selected list would leave holes; filtering the POOL makes
    # the scanner backfill with the next-ranked common stock, which is what a
    # study run without ETFs would actually have picked.
    syms = []
    if DAILY_PARQUET.exists():
        d = pd.read_parquet(DAILY_PARQUET)
        if "symbol" in d.columns and d["symbol"].notna().any():
            liq = d[(d["close"] >= MIN_PRICE) & (d["close"] <= MAX_PRICE)]
            cnt = liq.groupby("symbol").size()
            syms = sorted(cnt[cnt >= 100].index.astype(str).tolist())
            print(f"  source  : tradeable pool from {DAILY_PARQUET.name}")
    if not syms:
        sym_file = OUT_DIR / "scanner_selected_symbols.txt"
        if not sym_file.exists():
            print(f"  No pool and no {sym_file} — run --analyze first.")
            return
        syms = [x.strip() for x in sym_file.read_text(encoding="utf-8").splitlines() if x.strip()]
        print("  source  : selected-symbol list (pool unavailable)")
    print(f"  dataset : {dataset}")
    print(f"  symbols : {len(syms):,}")

    try:
        schemas = set(client.metadata.list_schemas(dataset=dataset))
    except Exception as e:
        print(f"  ERROR listing schemas — {type(e).__name__}: {str(e)[:150]}")
        return
    if "definition" not in schemas:
        print(f"  `definition` not offered on {dataset}.")
        print(f"  schemas: {', '.join(sorted(schemas))[:200]}")
        return

    # Definitions are emitted per session, so a few days is plenty — but they
    # only describe instruments that EXIST on those days. A single mid-window
    # probe left 1,699 names (17.9% of the pool) unclassified, and 86% of them
    # first traded AFTER that date: they are new listings, not missing data.
    # Probing near both ends of the study window covers old and new alike.
    DEF_WINDOWS = [("2024-06-03", "2024-06-06"), ("2026-06-01", "2026-06-04")]
    d0, d1 = DEF_WINDOWS[0]
    # The API caps a request at 2,000 symbols, and the pool is ~9,500. Chunk
    # rather than switching to ALL_SYMBOLS: ALL_SYMBOLS would pull every
    # instrument the venue lists, including thousands outside the pool, and
    # the point here is to classify exactly the names the scanner can pick.
    CHUNK = 2000
    parts = [syms[i:i + CHUNK] for i in range(0, len(syms), CHUNK)]
    print(f"  batches : {len(parts)} x <= {CHUNK} symbols")

    cost = size = 0.0
    for k, part in enumerate(parts, 1):
        try:
            cost += float(client.metadata.get_cost(
                dataset=dataset, symbols=part, schema="definition",
                start=d0, end=d1, stype_in="raw_symbol"))
            size += int(client.metadata.get_billable_size(
                dataset=dataset, symbols=part, schema="definition",
                start=d0, end=d1, stype_in="raw_symbol"))
        except Exception as e:
            print(f"  batch {k}: COST ERROR — {type(e).__name__}: {str(e)[:140]}")
    print(f"\n  definition {d0}..{d1}: ${cost:,.2f}  ({size / 1e6:,.2f} MB)")

    if not approve:
        print("\n  Nothing downloaded. Re-run with --approve-cost.")
        print("=" * 78)
        return

    chunks = []
    for k, part in enumerate(parts, 1):
        try:
            data = client.timeseries.get_range(
                dataset=dataset, schema="definition", symbols=part,
                start=d0, end=d1, stype_in="raw_symbol")
            try:
                x = data.to_df(map_symbols=True)
            except TypeError:
                x = data.to_df()
            chunks.append(x.reset_index())
            print(f"  batch {k}/{len(parts)}: {len(x):,} rows", flush=True)
        except Exception as e:
            print(f"  batch {k}/{len(parts)}: ERROR — {type(e).__name__}: {str(e)[:120]}")
    if not chunks:
        print("  Nothing returned.")
        return
    df = pd.concat(chunks, ignore_index=True)
    print(f"  rows: {len(df):,}")

    cols = [c for c in ("raw_symbol", "symbol", "security_type",
                        "instrument_class", "cfi", "asset") if c in df.columns]
    print(f"  columns present: {cols}")
    if not cols:
        print("  No classification columns returned.")
        return
    symcol = "raw_symbol" if "raw_symbol" in df.columns else "symbol"
    keep = [c for c in cols if c != symcol]
    latest = df.drop_duplicates(subset=[symcol], keep="last")[[symcol] + keep]

    for c in keep:
        vc = latest[c].astype(str).value_counts()
        print(f"\n  distribution of `{c}` ({latest[c].nunique()} distinct):")
        for v, n in vc.head(15).items():
            print(f"    {str(v)[:28]:<30} {n:>5}")

    # A single venue's directory does not list every symbol (not listed there,
    # or delisted mid-window). Sweep the leftovers on the other listing venue —
    # also free — rather than leaving part of the pool unclassified, which
    # would silently default those names into whichever bucket the filter used.
    missing = sorted(set(syms) - set(latest[symcol].astype(str)))
    if missing:
        # Retry on the LATE window first — the diagnosis showed the leftovers
        # are overwhelmingly instruments listed after the early probe date.
        # Same venue, later date; a different venue was tried before and
        # recovered exactly zero, which is what pointed at timing not coverage.
        l0, l1 = DEF_WINDOWS[1]
        print(f"\n  unresolved on {dataset} @ {d0}: {len(missing)}")
        print(f"  retrying the same venue at {l0}..{l1} (new listings)")
        got2 = []
        for k in range(0, len(missing), CHUNK):
            part = missing[k:k + CHUNK]
            try:
                d2 = client.timeseries.get_range(
                    dataset=dataset, schema="definition", symbols=part,
                    start=l0, end=l1, stype_in="raw_symbol")
                try:
                    x = d2.to_df(map_symbols=True)
                except TypeError:
                    x = d2.to_df()
                got2.append(x.reset_index())
            except Exception as e:
                print(f"    batch {k // CHUNK + 1}: {type(e).__name__}: {str(e)[:90]}")
        if got2:
            x = pd.concat(got2, ignore_index=True)
            sc2 = "raw_symbol" if "raw_symbol" in x.columns else "symbol"
            add = x.drop_duplicates(subset=[sc2], keep="last")
            add = add[[sc2] + [c for c in keep if c in add.columns]]
            add = add.rename(columns={sc2: symcol})
            latest = pd.concat([latest, add], ignore_index=True)
        still = len(set(syms) - set(latest[symcol].astype(str)))
        print(f"  recovered {len(missing) - still:,}; "
              f"still unresolved: {still} "
              f"({100 * still / max(len(syms), 1):.1f}% of pool)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    latest.to_parquet(CLASS_CACHE)
    print(f"\n  written: {CLASS_CACHE}  ({len(latest):,} classified)")
    if "security_type" in latest.columns:
        print("\n  final security_type counts:")
        print(latest["security_type"].astype(str).value_counts().to_string())
    print("\n  NEXT: read the distribution above, decide which values are common")
    print("  stock, then filter the symbol list on those values and re-run")
    print("  --analyze to get the post-exclusion n. Do NOT assume a code")
    print("  mapping — the values printed here are the ground truth.")
    print("=" * 78)


def price_window(client, dataset: str = "XNAS.ITCH") -> None:
    """
    Does slicing the request to ORB's actual hours cut the bill proportionally?

    Every quote so far assumed a contiguous full-range request, which returns
    04:00-20:00 — 960 minutes a day. ORB forms its range 09:30-09:45 and signals
    to 10:15; allowing room for the retest window and time stop, 09:30-10:45 is
    75 minutes, under 8% of the session. If Databento bills by bytes returned
    (it bills by billable size, so it should), requesting only those hours costs
    ~8% of the full pull.

    That would move the full study from ~$231 to roughly $20 — turning the
    budget from the binding constraint into a non-issue. It is worth one free
    metadata call before redesigning the study around a smaller scope.

    The cost is quoted three ways on the same day so the comparison is clean:
    full session, RTH only, and the ORB window. Times are converted per-day
    through America/New_York — a fixed UTC offset would be an hour wrong on one
    side of a DST boundary, which is exactly the kind of slice error that shows
    up as a plausible-but-wrong number.
    """
    print("=" * 78)
    print("WINDOW PRICING — does an intraday slice cut the bill?")
    print("=" * 78)
    sym_file = OUT_DIR / "scanner_selected_symbols.txt"
    if not sym_file.exists():
        print(f"  No symbol list at {sym_file} — run --analyze first.")
        return
    syms = [x.strip() for x in sym_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"  dataset : {dataset}")
    print(f"  symbols : {len(syms):,}")

    # Two probe days, one in EST and one in EDT, so a DST mistake cannot hide.
    probes = ["2024-06-05", "2024-12-04"]
    slices = [("full session", "04:00", "20:00"),
              ("RTH 09:30-16:00", "09:30", "16:00"),
              ("ORB 09:30-10:45", "09:30", "10:45")]

    print(f"\n  {'day':<12}{'slice':<18}{'cost':>10}{'MB':>10}{'vs full':>10}")
    ratios = []
    for day in probes:
        base = None
        for label, t0, t1 in slices:
            s = pd.Timestamp(f"{day} {t0}", tz="America/New_York").tz_convert("UTC")
            e = pd.Timestamp(f"{day} {t1}", tz="America/New_York").tz_convert("UTC")
            try:
                c = float(client.metadata.get_cost(
                    dataset=dataset, symbols=syms, schema=EXEC_SCHEMA,
                    start=s.isoformat(), end=e.isoformat(), stype_in="raw_symbol"))
                z = int(client.metadata.get_billable_size(
                    dataset=dataset, symbols=syms, schema=EXEC_SCHEMA,
                    start=s.isoformat(), end=e.isoformat(), stype_in="raw_symbol"))
            except Exception as ex:
                print(f"  {day:<12}{label:<18} ERROR — {type(ex).__name__}: {str(ex)[:60]}")
                continue
            if base is None:
                base = z or 1
            print(f"  {day:<12}{label:<18}${c:>9.4f}{z / 1e6:>10.2f}"
                  f"{z / base:>9.1%}")
            if label.startswith("ORB"):
                ratios.append(z / base)
        print()

    print("-" * 78)
    if not ratios:
        print("  Could not price the slices.")
        print("=" * 78)
        return
    r = sum(ratios) / len(ratios)
    print(f"  ORB window is {r:.1%} of a full session's billable bytes.")
    if r > 0.60:
        print("\n  NO SAVING — billing does not follow the intraday slice, so the")
        print("  full-session estimates stand. Scope must be cut some other way.")
    else:
        print(f"\n  SAVING IS REAL. Applying {r:.1%} to the full-study estimates:")
        for label, est in (("XNAS.ITCH alone", 53), ("top-5 venues", 231),
                           ("all 14 lit venues", 401)):
            print(f"    {label:<22} ${est:>4} -> ${est * r:>6.0f}")
        print("\n  Caveat: one contiguous request cannot express 'this window on")
        print("  every day', so this becomes ~838 per-day requests. Databento")
        print("  bills by bytes, not by request, so the saving should hold — but")
        print("  quote the real batch before committing.")
    print("=" * 78)


def diagnose_universe() -> None:
    """
    Where does the p95 tail live?

    A median of 0.0000% with a p95 of ~1.09% is bimodal, not noisy: most
    ticker-days match the consolidated tape EXACTLY and a small set is badly
    wrong. That shape points at specific broken SYMBOLS rather than diffuse
    error — with 18 tickers, one fully mismatched name is 5.5% of rows, which
    is exactly where the p95 sits.

    The distinction decides the project. Diffuse 1% error means the strategy
    cannot be tested on this data at all. A couple of bad symbols means the
    feed is sound and those names need excluding or explaining.

    Free: runs on the cached frames, fetches nothing.
    """
    print("=" * 78)
    print("DIAGNOSIS — where the residual tail comes from")
    print("=" * 78)
    if not (VENUE_CACHE.exists() and POLY_SAMPLE.exists()):
        print("  Missing cache. Run --validate-universe --approve-cost first")
        print("  (that run now persists the venue frames).")
        return
    allv = pd.read_parquet(VENUE_CACHE)
    pg = pd.read_parquet(POLY_SAMPLE)

    merged = allv[allv["venue"].isin(UNIV_CONFIGS["top-5 venues"])]
    merged = merged.groupby(["symbol", "date"]).agg(
        high=("high", "max"), low=("low", "min")).reset_index()
    j = merged.merge(pg, on=["symbol", "date"], suffixes=("_db", "_pg"))
    j["rh"] = (j["high_db"] - j["high_pg"]).abs() / j["high_pg"]
    j["rl"] = (j["low_db"] - j["low_pg"]).abs() / j["low_pg"]
    j["worst"] = j[["rh", "rl"]].max(axis=1)

    per = j.groupby("symbol").agg(
        n=("worst", "size"), med=("worst", "median"),
        p95=("worst", lambda x: x.quantile(.95)), mx=("worst", "max"),
        exact=("worst", lambda x: float((x < 1e-9).mean())),
    ).sort_values("med", ascending=False)

    print(f"  {len(j):,} ticker-days, top-5 venue merge\n")
    print(f"  {'symbol':<8}{'n':>5}{'median':>10}{'p95':>10}{'max':>11}{'exact':>8}")
    for sym, r in per.iterrows():
        print(f"  {sym:<8}{int(r['n']):>5}{100 * r['med']:>9.4f}%"
              f"{100 * r['p95']:>9.4f}%{100 * r['mx']:>10.3f}%{100 * r['exact']:>7.0f}%")

    bad = per[per["med"] > 0.001]
    print(f"\n  symbols with median residual > 0.10%: {len(bad)} of {len(per)}")
    if len(bad):
        keep = j[~j["symbol"].isin(bad.index)]
        print(f"  excluding them, {len(keep):,} of {len(j):,} ticker-days remain:")
        print(f"    median {100 * keep['worst'].median():.4f}%"
              f"   p95 {100 * keep['worst'].quantile(.95):.4f}%"
              f"   p99 {100 * keep['worst'].quantile(.99):.4f}%")
        print("\n  If the tail collapses once these are removed, the feed is")
        print("  sound and the problem is symbol-specific — ticker reuse, a halt,")
        print("  or a corporate action inside the window. If it does NOT")
        print("  collapse, the error is diffuse and the study is not viable here.")
    else:
        print("  No single symbol dominates — the tail is diffuse.")

    print("\n  worst 8 ticker-days:")
    print(j.nlargest(8, "worst")[
        ["symbol", "date", "high_db", "high_pg", "low_db", "low_pg", "worst"]
    ].to_string(index=False))
    print("=" * 78)


def validate_universe(client, approve: bool, n: int = 20) -> None:
    print("=" * 78)
    print("EXTREMES TEST v3 — on the REAL selected universe, venue-set tradeoff")
    print("=" * 78)
    print(f"  window : {EXT_START} .. {EXT_END}")
    print("  NOTE   : v2 passed on 10 mega-caps, which does not transfer to a")
    print("           mid/small-cap gapper universe. This is the valid test.")

    print("\n  building the consolidated reference (Polygon, UNADJUSTED):")
    pg = _polygon_sample(n)
    if pg.empty:
        print("  Cannot proceed without a reference.")
        return
    syms = sorted(pg["symbol"].unique())
    print(f"\n  reference: {len(syms)} tickers, {len(pg):,} ticker-days")

    venues = sorted({v for vs in UNIV_CONFIGS.values() for v in vs})
    print("\n  quotes for the sample (metadata only, $0):")
    got, total = [], 0.0
    for ds in venues:
        try:
            c = float(client.metadata.get_cost(
                dataset=ds, symbols=syms, schema=EXEC_SCHEMA,
                start=EXT_START, end=EXT_END, stype_in="raw_symbol",
            ))
            print(f"    {ds:<16} ${c:>6.2f}")
            got.append(ds)
            total += c
        except Exception as e:
            print(f"    {ds:<16} ERROR — {type(e).__name__}: {str(e)[:70]}")
    print(f"    {'TOTAL':<16} ${total:>6.2f}")

    if not approve:
        print("\n  Nothing downloaded from Databento. Re-run with --approve-cost.")
        print("=" * 78)
        return

    frames = {}
    for ds in got:
        try:
            data = client.timeseries.get_range(
                dataset=ds, schema=EXEC_SCHEMA, symbols=syms,
                start=EXT_START, end=EXT_END, stype_in="raw_symbol",
            )
            try:
                d = data.to_df(map_symbols=True)
            except TypeError:
                d = data.to_df()
            d = d.reset_index()
            tc = next(c for c in ("ts_event", "index") if c in d.columns)
            ts = pd.to_datetime(d[tc], utc=True).dt.tz_convert("America/New_York")
            d["date"] = ts.dt.tz_localize(None).dt.normalize()
            d["t"] = ts.dt.time
            rth = d[(d["t"] >= pd.Timestamp("09:30").time())
                    & (d["t"] <= pd.Timestamp("15:59").time())]
            frames[ds] = rth.groupby(["symbol", "date"]).agg(
                high=("high", "max"), low=("low", "min")).reset_index()
            frames[ds]["venue"] = ds
            print(f"  {ds:<16} {len(rth):,} RTH bars -> {len(frames[ds]):,} ticker-days",
                  flush=True)
        except Exception as e:
            print(f"  {ds:<16} ERROR — {type(e).__name__}: {str(e)[:70]}")

    # Persist so the per-symbol diagnosis can be re-run for free.
    if frames:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        pd.concat(frames.values(), ignore_index=True).to_parquet(VENUE_CACHE)
        print(f"  cached venue frames -> {VENUE_CACHE}")

    print(f"\n  {'config':<22}{'high resid':>12}{'low resid':>12}"
          f"{'p95 H':>10}{'p95 L':>10}{'cover':>8}")
    results = {}
    for label, vs in UNIV_CONFIGS.items():
        have = [v for v in vs if v in frames]
        if not have:
            continue
        merged = pd.concat([frames[v] for v in have], ignore_index=True)
        merged = merged.groupby(["symbol", "date"]).agg(
            high=("high", "max"), low=("low", "min")).reset_index()
        j = merged.merge(pg, on=["symbol", "date"], suffixes=("_db", "_pg"))
        if j.empty:
            continue
        # Polygon is unadjusted here, so NO split factor is applied.
        rh = (j["high_db"] - j["high_pg"]).abs() / j["high_pg"]
        rl = (j["low_db"] - j["low_pg"]).abs() / j["low_pg"]
        cover = len(j) / max(len(pg), 1)
        print(f"  {label:<22}{100 * rh.median():>11.4f}%{100 * rl.median():>11.4f}%"
              f"{100 * rh.quantile(.95):>9.4f}%{100 * rl.quantile(.95):>9.4f}%"
              f"{100 * cover:>7.0f}%")
        results[label] = (max(float(rh.median()), float(rl.median())),
                          max(float(rh.quantile(.95)), float(rl.quantile(.95))))

    print("\n" + "-" * 78)
    if not results:
        print("  No config produced overlapping rows.")
        print("=" * 78)
        return

    # Extrapolate each config to the full study, from this sample's quotes.
    ticker_days_sample = len(pg)
    ticker_days_study = 322 * 838
    factor = ticker_days_study / max(ticker_days_sample, 1)
    print(f"  full-study extrapolation (x{factor:,.0f} this sample):")
    per_venue = {}
    for ds in got:
        try:
            per_venue[ds] = float(client.metadata.get_cost(
                dataset=ds, symbols=syms, schema=EXEC_SCHEMA,
                start=EXT_START, end=EXT_END, stype_in="raw_symbol"))
        except Exception:
            per_venue[ds] = 0.0

    print(f"\n  {'config':<22}{'median':>10}{'p95':>10}{'est. full cost':>16}")
    ok_cfgs = []
    for label, vs in UNIV_CONFIGS.items():
        if label not in results:
            continue
        med, p95 = results[label]
        est = sum(per_venue.get(v, 0.0) for v in vs) * factor
        verdict = "PASS" if med < 0.0002 else ("MARGINAL" if med < 0.0005 else "FAIL")
        print(f"  {label:<22}{100 * med:>9.4f}%{100 * p95:>9.4f}%"
              f"${est:>14,.0f}   {verdict}")
        if med < 0.0005:
            ok_cfgs.append((label, med, est))

    print("\n" + "-" * 78)
    if not ok_cfgs:
        print("  NO venue set reaches tolerance on the real universe.")
        print("  ORB_RETEST_SCALP is blocked on data quality — it needs a")
        print("  SIP/TRF-inclusive consolidated feed, not exchange feeds.")
    else:
        ok_cfgs.sort(key=lambda r: r[2])
        lbl, med, est = ok_cfgs[0]
        print(f"  CHEAPEST SUFFICIENT: {lbl}")
        print(f"    median residual {100 * med:.4f}%   est. full-study cost ${est:,.0f}")
        print("\n  Check the p95 column before committing: a median inside")
        print("  tolerance with a p95 several times outside it means occasional")
        print("  bad prints, which for this strategy means occasional false")
        print("  breakouts and false retest touches.")
    print("=" * 78)


# ──────────────────────────────────────────────────────────────────────────────
# Price the real execution pull (metadata only, $0)
# ──────────────────────────────────────────────────────────────────────────────

def price_1min(client, dataset: str) -> None:
    """
    Quote ohlcv-1m for ONLY the symbols the scanner actually selects.

    This is the payoff of sizing first. An ALL_SYMBOLS 1-minute pull spans
    ~9,500 tradeable names; the scanner ever picks a few hundred. Quoting the
    narrow list turns a four-figure bill into a two- or three-figure one.

    Note the window covers ALL hours: a contiguous range request has no RTH
    filter, and ORB only uses 09:30-10:15. The quote below therefore includes
    extended-hours bars that will be fetched and discarded.
    """
    sym_file = OUT_DIR / "scanner_selected_symbols.txt"
    print("=" * 78)
    print("PRICING ohlcv-1m for the selected universe (metadata only, $0)")
    print("=" * 78)
    if not sym_file.exists():
        print(f"  No symbol list at {sym_file}")
        print("  Run --analyze first (it writes the list).")
        return
    syms = [x.strip() for x in sym_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"  dataset : {dataset}")
    print(f"  window  : {WIN_START} .. {WIN_END}")
    print(f"  symbols : {len(syms):,}")

    try:
        cost = client.metadata.get_cost(
            dataset=dataset, symbols=syms, schema=EXEC_SCHEMA,
            start=WIN_START, end=WIN_END, stype_in="raw_symbol",
        )
        size = client.metadata.get_billable_size(
            dataset=dataset, symbols=syms, schema=EXEC_SCHEMA,
            start=WIN_START, end=WIN_END, stype_in="raw_symbol",
        )
        print(f"\n  ohlcv-1m, selected symbols : ${float(cost):,.2f}"
              f"   ({size / 1e9:,.2f} GB)")
    except Exception as e:
        print(f"\n  ERROR — {type(e).__name__}: {str(e)[:220]}")
        print("  A symbology failure here usually means some selected tickers")
        print("  were delisted or renamed inside the window — resolve those")
        print("  before quoting, or drop them and quote the remainder.")
        return

    try:
        all_cost = client.metadata.get_cost(
            dataset=dataset, symbols="ALL_SYMBOLS", schema=EXEC_SCHEMA,
            start=WIN_START, end=WIN_END,
        )
        print(f"  ohlcv-1m, ALL_SYMBOLS      : ${float(all_cost):,.2f}"
              f"   <- what sizing first avoided")
    except Exception:
        pass
    print("=" * 78)


# ──────────────────────────────────────────────────────────────────────────────
# Phase 3 — analyze (free)
# ──────────────────────────────────────────────────────────────────────────────

def phase3(day_stride: int = 5, exclude_types: set | None = None) -> None:
    print("\n" + "=" * 78)
    print("PHASE 3 — universe sizing (free, runs on the cached daily bars)")
    print("=" * 78)

    if not DAILY_PARQUET.exists():
        print(f"  No cache at {DAILY_PARQUET}")
        print("  Run phase 2 first:  --fetch --approve-cost")
        return

    df = pd.read_parquet(DAILY_PARQUET)
    if "symbol" not in df.columns or df["symbol"].notna().sum() == 0:
        # Fail loudly here. Without this guard the all-null symbol column makes
        # groupby("symbol") drop every row, and the whole phase reports a
        # perfectly formatted table of zeros as though it were a finding.
        print(f"  ABORT: `symbol` is empty for all {len(df):,} rows.")
        print("  The bars are intact — only the ticker mapping is missing.")
        print("  Repair it without re-buying:  --resolve-symbols")
        return

    df = df.reset_index()
    tcol = next((c for c in ("ts_event", "index", "date") if c in df.columns), None)
    if tcol is None:
        print(f"  ABORT: no timestamp column found in {list(df.columns)}")
        return
    df["date"] = pd.to_datetime(df[tcol]).dt.tz_localize(None).dt.normalize()

    need = {"open", "high", "low", "close", "volume"}
    if not need <= set(df.columns):
        print(f"  ABORT: missing OHLCV columns; have {list(df.columns)}")
        return

    print(f"  rows    : {len(df):,}")
    print(f"  symbols : {df['symbol'].nunique():,}")
    print(f"  dates   : {df['date'].min().date()} .. {df['date'].max().date()}")

    # ── gap-rate distribution (descriptive; NOT a selection rule) ────────────
    df = df.sort_values(["symbol", "date"])
    df["prev_close"] = df.groupby("symbol")["close"].shift(1)
    df = df[df["prev_close"] > 0]
    df["gap"] = (df["open"] - df["prev_close"]).abs() / df["prev_close"]

    liquid = df[(df["close"] >= MIN_PRICE) & (df["close"] <= MAX_PRICE)]
    per_sym = liquid.groupby("symbol").agg(
        n=("gap", "size"), med_gap=("gap", "median"),
        rate=("gap", lambda g: (g >= GAP_THRESHOLD).mean()),
        adv=("volume", "median"),
    )
    per_sym = per_sym[per_sym["n"] >= 100]

    print(f"\n  tradeable symbols (price ${MIN_PRICE:.0f}-{MAX_PRICE:.0f}, "
          f">=100 bars): {len(per_sym):,}")
    print(f"  median gap across symbols        : {100 * per_sym['med_gap'].median():.2f}%")
    print(f"  symbols with gap>=1.5% on >20% of days: "
          f"{int((per_sym['rate'] > 0.20).sum()):,}")
    print(f"  symbols with gap>=1.5% on >30% of days: "
          f"{int((per_sym['rate'] > 0.30).sum()):,}")
    print("\n  (descriptive only — the universe is NOT selected from this table;"
          "\n   selection happens point-in-time via ORBUniverseScanner below)")

    # ── rolling, point-in-time scanner over the widened pool ────────────────
    pool = sorted(per_sym.index.tolist())

    # Exclusion by security type happens HERE, on the pool, before ranking.
    # Filtering the scanner's OUTPUT instead would leave gaps where an ETF was
    # picked; removing them from the input makes the scanner backfill with the
    # next-ranked common stock — which is the universe a study run without ETFs
    # would actually have traded.
    if exclude_types:
        if not CLASS_CACHE.exists():
            print(f"\n  --exclude-types given but {CLASS_CACHE.name} is missing.")
            print("  Run --classify-universe --approve-cost first.")
            return
        cls = pd.read_parquet(CLASS_CACHE)
        sc = "raw_symbol" if "raw_symbol" in cls.columns else "symbol"
        drop_map = dict(zip(cls[sc].astype(str), cls["security_type"].astype(str)))
        drop = {s for s in pool if drop_map.get(s) in exclude_types}
        unknown = [s for s in pool if s not in drop_map]
        print(f"\n  excluding security_type {sorted(exclude_types)}: "
              f"{len(drop):,} of {len(pool):,} symbols dropped")
        print(f"  unclassified (kept): {len(unknown):,} "
              f"({100 * len(unknown) / max(len(pool), 1):.1f}% of pool)")
        if unknown:
            print("  NOTE: unclassified names are KEPT. If that share is large,")
            print("  the exclusion is only partial and n below is an upper bound.")
        pool = [s for s in pool if s not in drop]
    dates = sorted(df["date"].unique())

    # Two exact optimisations, neither of which changes a single selection:
    #
    #  1. vectorised_scores() replaces ORBUniverseScanner's per-(ticker, day)
    #     re-slicing with groupby().rolling(). Proven identical by
    #     --verify-scanner (60/60 days exact on the 37-ticker daily cache).
    #  2. Rank ONCE at max(TOP_N_GRID) and take prefixes. The class sorts by
    #     score and only then truncates with [:top_n], so the top-10 is always
    #     the first 10 of the top-40.
    #
    # With both, the full-stride run is affordable, so day_stride now defaults
    # to 1 in practice — sampling was only ever a concession to the slow path.
    import time as _time
    t0 = _time.time()
    print(f"\n  scoring {len(pool):,} symbols x {len(dates):,} days "
          f"(vectorised; verified exact vs ORBUniverseScanner) ...", flush=True)

    # Two filters that the production path never needed, because production's
    # daily_data is 37 vetted mega-caps. A 9,454-name ALL_SYMBOLS universe is a
    # different animal and both of these are load-bearing:
    #
    #  (a) PRICE BAND AT SCORING TIME, not just pool-selection time. A symbol
    #      qualifies for the pool via its $10+ era, but its penny era was still
    #      feeding the rolling gap score and still counted as a gap-only pass.
    #      ORBStrategy.run_scanner rejects out-of-band prices at trade time, so
    #      counting those days as tradeable setups overstates n.
    #
    #  (b) CORPORATE ACTIONS. Databento ohlcv is unadjusted, so a reverse split
    #      appears as an enormous gap: AKTS prints prev_close $0.0167 -> open
    #      $27.09, a "gap" of 162,000%. 99 of the 347 symbols selected on the
    #      unfiltered run carried at least one >100% event. Those are not
    #      tradeable gaps and a gap-frequency ranker actively seeks them out.
    #      Anything beyond MAX_REAL_GAP is treated as a corporate action.
    tradeable = df[(df["close"] >= MIN_PRICE) & (df["close"] <= MAX_PRICE)]
    n_before = len(tradeable)
    tradeable = tradeable[tradeable["gap"] <= MAX_REAL_GAP]
    print(f"  price band + corporate-action filter: "
          f"{n_before - len(tradeable):,} rows dropped "
          f"({100 * (n_before - len(tradeable)) / max(n_before, 1):.3f}% "
          f"were gaps > {MAX_REAL_GAP:.0%})")

    long_df = tradeable[tradeable["symbol"].isin(pool)][
        ["symbol", "date", "open", "high", "low", "close", "volume"]
    ]
    df = tradeable   # everything downstream counts tradeable rows only
    pool_index = {s: i for i, s in enumerate(pool)}
    scores = vectorised_scores(long_df, pool_index)
    by_day_scores = {d: g for d, g in scores.groupby("date")}
    print(f"  scored in {_time.time() - t0:.0f}s", flush=True)

    sample_dates = list(range(1, len(dates), max(1, day_stride)))
    scale = len(dates) / max(len(sample_dates), 1)
    print(f"  sampling every {day_stride} day(s): {len(sample_dates):,} of "
          f"{len(dates):,} days, scaled by {scale:.2f}x")
    print(f"  {'top_n':>6}{'ticker-days':>14}{'gap-only':>14}"
          f"{'n(ORB)':>11}{'n(retest)':>11}{'n(4min)':>11}")

    by_date = {d: g for d, g in df.groupby("date")}
    selected_symbols: set = set()
    max_top_n = max(TOP_N_GRID)
    ticker_days = {n: 0 for n in TOP_N_GRID}
    scanner_pass = {n: 0 for n in TOP_N_GRID}

    empty = scores.iloc[0:0]
    for i in sample_dates:
        day, prev = dates[i], dates[i - 1]
        ranked = select_topn(by_day_scores.get(prev, empty), max_top_n)
        if not ranked:
            continue
        today = by_date.get(day)
        selected_symbols.update(ranked)
        for n in TOP_N_GRID:
            uni = ranked[:n]
            ticker_days[n] += len(uni)
            if today is None:
                continue
            hit = today[today["symbol"].isin(uni)]
            scanner_pass[n] += int((hit["gap"] >= GAP_THRESHOLD).sum())

    for n in TOP_N_GRID:
        td = ticker_days[n] * scale
        sp = scanner_pass[n] * scale
        n_orb = sp * R_GAPONLY_TO_ORB
        n_ret = n_orb * R_RETEST_VS_CONFIRM
        n_real = n_ret * R_WINDOW_DISCOUNT
        print(f"  {n:>6}{td:>14,.0f}{sp:>14,.0f}"
              f"{n_orb:>11,.0f}{n_ret:>11,.0f}{n_real:>11,.0f}")

    # The payoff of sizing first: the 1-minute pull only needs the symbols the
    # scanner ever selects, not ALL_SYMBOLS. This set is what to buy.
    print(f"\n  distinct symbols ever selected (any top_n, sampled days): "
          f"{len(selected_symbols):,}")
    print(f"  vs {len(per_sym):,} tradeable symbols -> the ohlcv-1m pull can be")
    print(f"  scoped to ~{100 * len(selected_symbols) / max(len(per_sym), 1):.0f}% "
          f"of the universe.")
    sym_out = OUT_DIR / "scanner_selected_symbols.txt"
    sym_out.write_text("\n".join(sorted(selected_symbols)), encoding="utf-8")
    print(f"  written: {sym_out}")
    if day_stride > 1:
        print("  NOTE: sampled days under-count the selected set — a symbol picked")
        print("  only on skipped days is missed. Re-run with --day-stride 1 before")
        print("  using this list as the actual purchase scope.")
    else:
        print("  Every day walked (stride 1) — this list IS the purchase scope.")

    if not len(dates):
        print("\n  No dates survived filtering — nothing to size.")
        return
    # dates come from .unique() on a datetime64 column, which yields Timestamps
    # in some pandas versions and numpy datetime64 in others. Go through
    # pd.Timestamp so the subtraction is a Timedelta either way.
    span_yrs = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 365.25
    print(f"\n  span walked: {span_yrs:.1f} years")
    print("\n  n(ORB)    = ORB entries, via the end-to-end 2.52% anchor")
    print("  n(retest) = retest population, 1.114x the confirmed one")
    print("  n(4min)   = the above halved for the spec's 4-minute retest window")
    print("              vs the funnel proxy's 20-minute one.  READ THIS COLUMN.")
    print()
    print("  CAVEAT at high top_n: the 2.52% anchor was measured at top_n=10")
    print("  with MAX_ORB=2 / MAX_TOTAL=8 in force. Raising top_n multiplies")
    print("  signal density but not the caps, so they bind harder and the")
    print("  linear scaling above OVERSTATES n at top_n 25 and 40.")
    print("\n  Compare against the pre-committed thresholds:")
    print("    n >= 200  -> buy the 1-minute data; the spec's breakdowns work")
    print("    n 80-200  -> buy, but narrow the spec to a paired comparison first")
    print("    n <  80   -> do not buy; sample-limited regardless of resolution")
    print("=" * 78)


def _excl(v: str):
    return {x.strip() for x in v.split(",") if x.strip()} or None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true", help="download daily bars (COSTS MONEY)")
    ap.add_argument("--approve-cost", action="store_true",
                    help="required alongside --fetch; explicit spend approval")
    ap.add_argument("--dataset", default=None, help="force a dataset for --fetch")
    ap.add_argument("--analyze", action="store_true", help="run phase 3 on the cache")
    ap.add_argument("--exclude-types", default="",
                    help="comma-separated security_type codes to drop from the pool, e.g. Q or Q,A")
    ap.add_argument("--classify-universe", action="store_true",
                    help="split the selected universe into common stock vs ETF/ETN")
    ap.add_argument("--price-window", action="store_true",
                    help="quote an intraday-sliced request vs a full session (free)")
    ap.add_argument("--diagnose-universe", action="store_true",
                    help="free per-symbol breakdown of the residual tail (uses cache)")
    ap.add_argument("--validate-universe", action="store_true",
                    help="extremes test on the REAL selected universe + venue-set cost tradeoff")
    ap.add_argument("--sample-n", type=int, default=20,
                    help="how many selected symbols to sample for --validate-universe")
    ap.add_argument("--validate-extremes-1m", action="store_true",
                    help="RTH-correct extremes test on 1-minute bars (supersedes --validate-extremes)")
    ap.add_argument("--validate-extremes", action="store_true",
                    help="test whether merged lit venues reproduce consolidated high/low")
    ap.add_argument("--validate-datasets", action="store_true",
                    help="measure consolidated-tape coverage of each candidate vs Polygon")
    ap.add_argument("--price-1min", action="store_true",
                    help="price the ohlcv-1m pull for the selected symbols (metadata only, $0)")
    ap.add_argument("--verify-scanner", action="store_true",
                    help="prove the vectorised scanner matches the real one, then exit")
    ap.add_argument("--resolve-symbols", action="store_true",
                    help="repair instrument_id -> ticker on the cache (no data charge)")
    ap.add_argument("--day-stride", type=int, default=1,
                    help="sample every Nth day in phase 3 (default 1 = every day)")
    a = ap.parse_args()

    if a.verify_scanner:
        verify_scanner()
        return

    if a.classify_universe:
        client = _client()
        if client is None:
            return
        classify_universe(client, a.approve_cost, a.dataset or "XNAS.ITCH")
        return

    if a.price_window:
        client = _client()
        if client is None:
            return
        price_window(client, a.dataset or "XNAS.ITCH")
        return

    if a.diagnose_universe:
        diagnose_universe()
        return

    if a.validate_universe:
        client = _client()
        if client is None:
            return
        validate_universe(client, a.approve_cost, a.sample_n)
        return

    if a.validate_extremes_1m:
        client = _client()
        if client is None:
            return
        validate_extremes_1m(client, a.approve_cost)
        return

    if a.validate_extremes:
        client = _client()
        if client is None:
            return
        validate_extremes(client, a.approve_cost)
        return

    if a.validate_datasets:
        client = _client()
        if client is None:
            return
        validate_datasets(client, a.approve_cost)
        return

    if a.price_1min:
        client = _client()
        if client is None:
            return
        price_1min(client, a.dataset or "EQUS.MINI")
        return

    if a.analyze and not a.fetch and not a.resolve_symbols:
        phase3(a.day_stride, _excl(a.exclude_types))
        return

    if a.resolve_symbols:
        client = _client()
        if client is None:
            return
        phase_resolve(client, a.dataset or "EQUS.MINI")
        if a.analyze:
            phase3(a.day_stride, _excl(a.exclude_types))
        return

    client = _client()
    if client is None:
        return

    usable = phase1(client)

    if not a.fetch:
        print("\n  Nothing was downloaded. No cost incurred.")
        print("  To fetch:  --fetch --approve-cost [--dataset NAME]")
        return

    if not a.approve_cost:
        print("\n  --fetch given without --approve-cost. Refusing to spend.")
        print("  Re-run with both flags once the quoted cost above is acceptable.")
        return
    if not usable:
        print("\n  Nothing fetchable.")
        return

    # No auto-pick. "Cheapest" is the wrong objective and picking it silently
    # would be a real error: the cheapest row in a live run was an 11-month
    # dataset, and other cheap rows are options/futures/European venues that
    # merely happen to quote a low price for our window. Dataset choice is a
    # judgement about coverage, so it must be stated explicitly.
    if not a.dataset:
        print("\n  --dataset is REQUIRED for --fetch. There is no sensible")
        print("  default: the cheapest quote is not the right dataset. Pick one")
        print("  that (a) is US equities, (b) is consolidated rather than a")
        print("  single venue, and (c) spans the full window above.")
        return
    m = [r for r in usable if r["dataset"] == a.dataset]
    if not m:
        print(f"\n  --dataset {a.dataset} is not in the usable list above.")
        return
    choice = m[0]

    phase2(client, choice)
    phase3(a.day_stride, _excl(a.exclude_types))


if __name__ == "__main__":
    main()
