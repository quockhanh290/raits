"""
fetch_stress_orb_news.py — Step B: fetch news for the extended SHORT population
(EXPERIMENTAL harness, orb_stocks/)

Population (155 events, all SHORT):
  - 144 STRESS_ORB_STK candidate days (V3 engine-faithful variant from the harvest)
  -   7 ORB gap-down shorts meeting STRESS_ORB_STK's >=1.5% gap-down threshold
        (MU, CVX, ADBE, AMAT-0110, INTU-0110, GS, NVDA)   [in_primary_151=True]
  -   4 ORB tagged-but-excluded shorts                     [in_primary_151=False]
        3 gap-up reversals: AMD 2021-04-28, AMAT 2021-08-20, AMAT 2022-01-13
        1 sub-threshold gap-down: MA 2022-01-06 (-1.27%)

primary bootstrap population = the 151 (in_primary_151=True); the 4 are cached and
tagged for a possible footnote, per instruction.

Reuses raits/data/raits_news.py verbatim (fetch_news_for_universe / build_news_index)
— nothing in that module is rewritten. STRESS_ORB_STK trigger days come from the
committed sim, run unmodified (imported → read t_v3). No engine re-enable, orb.py
untouched. No LLM / bootstrap code here.

Run:
    cd d:\\raits
    python orb_stocks\\fetch_stress_orb_news.py
"""

from __future__ import annotations

import os
import sys
import io
import pickle
import contextlib
import collections
from datetime import time as dtime
from zoneinfo import ZoneInfo

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "raits", "raits", "scripts"))

from raits.strategies.universe_scanner import CANDIDATE_POOL
from raits.data.raits_news import fetch_news_for_universe, build_news_index
from check_news_coverage import _load_api_key

EASTERN = ZoneInfo("America/New_York")
POOL = set(CANDIDATE_POOL)
WINDOW_START = pd.Timestamp("2021-04-01")
WINDOW_END   = pd.Timestamp("2022-12-31")
CACHE_DIR = os.path.join(REPO, "raits", "data", "cache")
ORB_SNAPSHOT = os.path.join(CACHE_DIR, "snapshots", "results_20260707_110323.pkl")
EVENT_INDEX_OUT = os.path.join(CACHE_DIR, "news", "orb_event_index.parquet")

# The 7 qualifying + 4 excluded ORB shorts (settled with user).
ORB_QUALIFYING = {  # in_primary_151 = True
    ("MU", "2021-06-18"), ("CVX", "2021-08-19"), ("ADBE", "2021-12-14"),
    ("AMAT", "2022-01-10"), ("INTU", "2022-01-10"), ("GS", "2022-01-24"),
    ("NVDA", "2022-01-24"),
}
ORB_EXCLUDED = {  # in_primary_151 = False, tagged for footnote
    ("AMD", "2021-04-28"), ("AMAT", "2021-08-20"), ("AMAT", "2022-01-13"),
    ("MA", "2022-01-06"),
}


def compute_gap(data_5min, ticker, day) -> float | None:
    """Signed gap_pct (session_open vs prev business-day close) — sim's method."""
    if ticker not in data_5min:
        return None
    bars = data_5min[ticker].sort_index()
    day = pd.Timestamp(day).normalize()
    daily_last = bars.resample("B")["close"].last().dropna()
    idx = list(daily_last.index)
    pos = next((i for i, x in enumerate(idx) if x.normalize() == day), None)
    if not pos or pos <= 0:
        return None
    prev_c = float(daily_last.iloc[pos - 1])
    db = bars[bars.index.normalize() == day]
    ob = db[db.index.time >= dtime(9, 30)]
    if ob.empty or prev_c <= 0:
        return None
    session_open = float(ob.iloc[0]["open"])
    return (session_open - prev_c) / prev_c


def load_orb_shorts(snapshot):
    """The 11 ORB SHORT events with their regime (hmm_state) from the snapshot."""
    with open(snapshot, "rb") as f:
        windows = pickle.load(f)
    out = {}
    for w in windows:
        for t in w["trades"]:
            if getattr(t, "strategy", None) != "ORB":
                continue
            if getattr(t, "direction", None) != "SHORT":
                continue
            et = pd.Timestamp(t.entry_time).normalize()
            if WINDOW_START <= et <= WINDOW_END and t.ticker in POOL:
                out[(t.ticker, et.date().isoformat())] = getattr(t, "hmm_state", None)
    return out


def main():
    print("=" * 78)
    print("ORB STOCKS — STEP B: fetch news for extended SHORT population (155 events)")
    print("=" * 78)

    # ── Run committed sim once (get V3 pairs + shared 5min data) ──────────
    print("Running stress_orb_stk_sim.py (unmodified, ~30-60s)...")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import stress_orb_stk_sim as sim
    data_5min = sim.data_5min
    print("  sim run complete.\n")

    # ── Build the 155-event list with metadata ────────────────────────────
    events = []  # dict per (ticker, date)

    # 144 STRESS_ORB_STK (V3), in-window, pool-only
    stk_pairs = set()
    for t in sim.t_v3:
        d = pd.Timestamp(t["day"]).normalize()
        if t["ticker"] in POOL and WINDOW_START <= d <= WINDOW_END:
            stk_pairs.add((t["ticker"], d.date().isoformat()))
    for (tk, ds) in sorted(stk_pairs):
        events.append(dict(ticker=tk, date=ds, source="STRESS_ORB_STK",
                           direction="SHORT", regime="Stress",
                           in_primary_151=True))

    # 11 ORB shorts (7 qualifying + 4 excluded), regime from snapshot
    orb_regime = load_orb_shorts(ORB_SNAPSHOT)
    for (tk, ds) in sorted(ORB_QUALIFYING | ORB_EXCLUDED):
        in_primary = (tk, ds) in ORB_QUALIFYING
        events.append(dict(ticker=tk, date=ds, source="ORB", direction="SHORT",
                           regime=orb_regime.get((tk, ds)),
                           in_primary_151=in_primary))

    # gap_pct for all; flag data-quality anomalies (corrupt bars → phantom gaps).
    # Real large-cap overnight gaps don't exceed ~15%; anything beyond is a bad-bar
    # artifact (e.g. META's spurious ~$12-16 opening bars on some 2021-22 days),
    # which means the sim's trigger on that day is phantom, not a real setup.
    for ev in events:
        g = compute_gap(data_5min, ev["ticker"], ev["date"])
        ev["gap_pct"] = round(g * 100, 3) if g is not None else None
        ev["gap_suspect"] = (g is None) or (g < -0.15)

    n_primary = sum(1 for e in events if e["in_primary_151"])
    print(f"Events assembled: {len(events)} total "
          f"({n_primary} primary, {len(events)-n_primary} tagged-excluded)")
    by_src = collections.Counter(e["source"] for e in events)
    print(f"  by source: {dict(by_src)}")

    # ── Determine (ticker, month) cells; fetch uncached only ──────────────
    ticker_months = collections.defaultdict(set)
    for e in events:
        d = pd.Timestamp(e["date"])
        ticker_months[e["ticker"]].add((d.year, d.month))

    news_dir = os.path.join(CACHE_DIR, "news")
    existing = set()
    for fn in os.listdir(news_dir) if os.path.isdir(news_dir) else []:
        if fn.endswith(".json") and "_news_" in fn:
            tk = fn.split("_news_")[0]
            ym = fn.split("_news_")[1].split("_")[0]
            y, m = ym.split("-")
            existing.add((tk, int(y), int(m)))

    all_cells = {(tk, y, m) for tk, mos in ticker_months.items() for (y, m) in mos}
    to_fetch = all_cells - existing
    print(f"\n(ticker,month) cells: {len(all_cells)} total | "
          f"already cached: {len(all_cells & existing)} | to fetch: {len(to_fetch)}")

    api_key = _load_api_key()
    manifest = {}
    print(f"\n--- Fetching uncached cells (cache: {news_dir}) ---")
    for tk in sorted(ticker_months):
        months = sorted(ticker_months[tk])
        m = fetch_news_for_universe(
            tickers=[tk], start_date=WINDOW_START, end_date=WINDOW_END,
            api_key=api_key, cache_dir=CACHE_DIR, months=months, verbose=False,
        )
        manifest.update(m)

    # ── Build article index over all population tickers ───────────────────
    pop_tickers = sorted({e["ticker"] for e in events})
    idx = build_news_index(CACHE_DIR, tickers=pop_tickers, dates=None)

    # ── Per-event same-day + rough pre-09:30 article presence ─────────────
    # Group article ET datetimes by (ticker, ET-date).
    same_day = collections.defaultdict(int)
    premkt = collections.defaultdict(int)
    if not idx.empty:
        tmp = idx.reset_index()
        tmp["et_dt"] = pd.to_datetime(tmp["published_utc"].str.replace("Z", "+00:00"),
                                      utc=True).dt.tz_convert(EASTERN)
        for _, row in tmp.iterrows():
            key = (row["ticker"], pd.Timestamp(row["date"]).date().isoformat())
            same_day[key] += 1
            if row["et_dt"].time() <= dtime(9, 29, 59):
                premkt[key] += 1

    for e in events:
        key = (e["ticker"], e["date"])
        e["n_same_day_articles"] = same_day.get(key, 0)
        e["n_premkt_articles"]   = premkt.get(key, 0)

    # ── Persist combined event index ──────────────────────────────────────
    ev_df = (pd.DataFrame(events)
             .assign(date=lambda x: pd.to_datetime(x["date"]))
             .set_index(["ticker", "date"])
             .sort_index())
    ev_df.to_parquet(EVENT_INDEX_OUT)

    # ── Combined summary ──────────────────────────────────────────────────
    # total articles across the whole news cache (Step 1 + Step B)
    import json
    total_articles = 0
    for fn in os.listdir(news_dir):
        if fn.endswith(".json") and "_news_" in fn:
            try:
                with open(os.path.join(news_dir, fn), "r", encoding="utf-8") as f:
                    import json
                    total_articles += json.load(f).get("n_articles", 0)
            except Exception:
                pass

    errs = [k for k, v in manifest.items() if v is None]
    print(f"\n{'=' * 78}")
    print("STEP B — COMBINED SUMMARY")
    print("=" * 78)
    print(f"News cache files on disk : {len([f for f in os.listdir(news_dir) if f.endswith('.json')])}")
    print(f"Total articles cached    : {total_articles}  (Step 1 was 2,278)")
    print(f"Fetch errors this run    : {len(errs)}  {sorted(errs) if errs else ''}")

    prim = [e for e in events if e["in_primary_151"]]
    excl = [e for e in events if not e["in_primary_151"]]

    def presence(evs):
        sd = sum(1 for e in evs if e["n_same_day_articles"] > 0)
        pm = sum(1 for e in evs if e["n_premkt_articles"] > 0)
        return sd, pm

    for label, evs in [("PRIMARY (151)", prim), ("EXCLUDED-tagged (4)", excl),
                       ("ALL (155)", events)]:
        sd, pm = presence(evs)
        print(f"\n  {label}: {len(evs)} events")
        print(f"    with >=1 same-day article (any time)      : {sd}/{len(evs)}")
        print(f"    with >=1 article before 09:30 ET (ROUGH)  : {pm}/{len(evs)}")

    print("\n  by source (primary population):")
    for src in ["STRESS_ORB_STK", "ORB"]:
        evs = [e for e in prim if e["source"] == src]
        if evs:
            sd, pm = presence(evs)
            print(f"    {src:<15} {len(evs):>3} events | same-day {sd} | pre-09:30 {pm}")

    suspects = [e for e in events if e.get("gap_suspect")]
    if suspects:
        print(f"\n  DATA-QUALITY FLAG — {len(suspects)} event(s) with corrupt-bar phantom gaps")
        print(f"  (gap < -15%: bad opening bars → sim trigger is phantom, recommend DROP):")
        for e in suspects:
            print(f"    {e['source']:<15} {e['ticker']:<5} {e['date']}  "
                  f"gap={e['gap_pct']}%  in_primary_151={e['in_primary_151']}")

    clean = [e['gap_pct'] for e in prim if e['gap_pct'] is not None and not e.get('gap_suspect')]
    print(f"\n  gap_pct range (primary, excl. suspects): "
          f"{min(clean):.2f}% .. {max(clean):.2f}%")
    print(f"  regime spread (primary): "
          f"{dict(collections.Counter(e['regime'] for e in prim))}")

    print(f"\n  Combined event index written: {EVENT_INDEX_OUT}")
    print("  columns: source, direction, regime, gap_pct, in_primary_151,")
    print("           n_same_day_articles, n_premkt_articles")

    print(f"\n{'-' * 78}")
    print("CAVEATS")
    print("- 'pre-09:30 ET' count is ROUGH: it counts only SAME-ET-DAY articles")
    print("  timestamped before 09:30. It does NOT count prior-evening/overnight")
    print("  catalysts (published the day before after close), which ARE pre-market")
    print("  and would INCREASE the usable count. Exact join is Step 2/3's job.")
    print("- Article text = title + Polygon 'description' only (no full body).")
    print("=" * 78)


if __name__ == "__main__":
    main()
