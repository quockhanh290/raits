"""
Opening Imbalance Research — STEP 1: data coverage / feasibility go-no-go.
(EXPERIMENTAL harness, orb_stocks/imbalance_research/)  — RESEARCH ONLY.

Mirrors the role of orb_stocks/check_news_coverage.py in the catalyst study:
answer ONE question before building anything else —

    "Is there enough usable opening-imbalance data for the 155 ORB /
     STRESS_ORB_STK events to make a statistical test worth running?"

This is NOT feature construction (Step 2), NOT a statistical test (Step 3),
and it touches NO production code.

────────────────────────────────────────────────────────────────────────────
WHAT 'IMBALANCE' CAN ACTUALLY MEAN HERE  (read before interpreting output)
────────────────────────────────────────────────────────────────────────────
The prompt's first choice is the official NYSE / Nasdaq opening auction
imbalance (NYSE Order Imbalance Info / Nasdaq NOII, disseminated from ~09:28
ET). Section A probes for it. If Polygon does not carry it, and NBBO quotes
are not entitled, then canonical Lee-Ready (1991) — which compares each trade
to the prevailing quote midpoint — is NOT constructible either.

The remaining fallback is the TICK RULE: Lee-Ready's own tie-breaker, applied
standalone (classify a trade buyer-initiated if it prints above the previous
different price, seller-initiated if below, carry the last sign on a zero
tick). It is a strictly weaker classifier than quote-based Lee-Ready.

Call it what it is in every downstream write-up:
    pre-open signed order flow (tick rule)   ≠   opening auction imbalance
Different object, measured over a different window, from a different
mechanism. Section A prints exactly which of the three is available so the
verdict is not overstated later.

────────────────────────────────────────────────────────────────────────────
PRE-COMMITTED GO / NO-GO THRESHOLDS  (fixed before the first fetch)
────────────────────────────────────────────────────────────────────────────
These are judgment floors chosen for this study, not literature benchmarks.

  GO      : >=80% of clean events have >=MIN_TRADES classifiable trades in at
            least one measurement window, AND both 2021 and 2022 clear 70%
            individually (so the test is not a single-year artifact), AND
            >=25 distinct dates survive (Step 3's within-date permutation
            needs mixed dates to have any label freedom at all).
  MARGINAL: 50-80% overall coverage -> proceed only on the covered subset,
            and report the excluded population's composition (a coverage
            filter that correlates with cap size IS a selection effect).
  NO-GO   : <50%, or one year collapses, or <25 distinct dates.

MIN_TRADES = 30: with fewer signed trades the imbalance ratio's own sampling
noise (sd ~ 1/sqrt(n) ~ 18% at n=30) swamps any plausible effect. This is a
floor for the ratio to be estimable at all, not a claim about power.

────────────────────────────────────────────────────────────────────────────
Two measurement windows are BOTH measured; the choice between them is
deferred to the data (prompt requirement #4 — do not impose a variable):
    LATE  09:00-09:30 ET  — closest in time to the real auction imbalance
    FULL  04:00-09:30 ET  — full pre-market, more trades, weaker analogy

Side effect (deliberate): the signed aggregates computed here are CACHED to
imbalance_coverage.parquet so Step 2 never refetches ticks. Aggregates are
kept raw enough (buy/sell/unclassified volume and trade counts per window) to
build direction / magnitude / zscore variants without another API pass.

Run:
    cd d:\\raits
    python orb_stocks\\imbalance_research\\check_imbalance_coverage.py --sample 12
    python orb_stocks\\imbalance_research\\check_imbalance_coverage.py          # all 155
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EVENT_INDEX = os.path.join(REPO, "raits", "data", "cache", "news", "orb_event_index.parquet")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PARQUET = os.path.join(OUT_DIR, "imbalance_coverage.parquet")

BASE = "https://api.polygon.io"
ET = ZoneInfo("America/New_York")

# Measurement windows, ET (start_h, start_m, end_h, end_m)
WINDOWS = {
    "late": (9, 0, 9, 30),    # ~auction-imbalance analogue
    "full": (4, 0, 9, 30),    # whole pre-market session
}

MIN_TRADES = 30
GO_OVERALL = 0.80
GO_PER_YEAR = 0.70
GO_MIN_DATES = 25
NOGO_OVERALL = 0.50

PAGE_LIMIT = 50_000
MAX_PAGES = 20          # 1M trades/event ceiling; nothing legitimate hits this
REQ_TIMEOUT = 120


# ──────────────────────────────────────────────────────────────────────────
# API key — same pattern as orb_stocks/check_news_coverage.py
# ──────────────────────────────────────────────────────────────────────────
def _load_api_key() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(here, "..", "..", "config_private.py"),
        os.path.join(here, "..", "config_private.py"),
        "config_private.py",
    ):
        if os.path.exists(candidate):
            spec = importlib.util.spec_from_file_location("config_private", candidate)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            key = getattr(mod, "POLYGON_API_KEY", None)
            if key:
                return key
    key = os.environ.get("POLYGON_API_KEY", "")
    if not key:
        sys.exit("FATAL: POLYGON_API_KEY not found in config_private.py or env var.")
    return key


def _get(url: str, key: str, retries: int = 4):
    """GET with apiKey appended; returns (http_status, parsed_or_text)."""
    sep = "&" if "?" in url else "?"
    full = f"{url}{sep}apiKey={key}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(full, timeout=REQ_TIMEOUT) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            if e.code == 429:                      # rate limited — back off
                time.sleep(2 ** attempt)
                continue
            return e.code, body
        except Exception as e:
            if attempt == retries - 1:
                return "ERR", str(e)[:300]
            time.sleep(1.5 * (attempt + 1))
    return "ERR", "retries exhausted"


# ──────────────────────────────────────────────────────────────────────────
# SECTION A — what imbalance data does this key actually entitle?
# ──────────────────────────────────────────────────────────────────────────
def section_a(key: str) -> dict:
    print("=" * 78)
    print("SECTION A — ENTITLEMENT PROBE (which imbalance object is buildable?)")
    print("=" * 78)

    probes = [
        ("official imbalance v3", f"{BASE}/v3/reference/imbalances?ticker=AAPL",
         "NYSE/Nasdaq published auction imbalance"),
        ("official imbalance v1", f"{BASE}/v1/imbalances/AAPL",
         "NYSE/Nasdaq published auction imbalance (legacy path)"),
        ("NBBO quotes v3", f"{BASE}/v3/quotes/AAPL"
                           "?timestamp.gte=2022-06-03T13:00:00Z"
                           "&timestamp.lt=2022-06-03T13:05:00Z&limit=5",
         "required for canonical quote-based Lee-Ready"),
        ("trades v3", f"{BASE}/v3/trades/AAPL"
                      "?timestamp.gte=2022-06-03T13:00:00Z"
                      "&timestamp.lt=2022-06-03T13:05:00Z&limit=5",
         "required for the tick-rule fallback"),
    ]

    avail = {}
    for name, url, why in probes:
        st, body = _get(url, key)
        ok = (st == 200 and isinstance(body, dict)
              and body.get("status") in ("OK", "DELAYED")
              and len(body.get("results") or []) > 0)
        # A 200/OK with 0 results on a known-active window still means entitled;
        # only 403/404 are hard negatives.
        entitled = st == 200 and isinstance(body, dict) and body.get("status") in ("OK", "DELAYED")
        avail[name] = entitled
        msg = ""
        if isinstance(body, dict):
            msg = str(body.get("message", ""))[:90]
        else:
            msg = str(body)[:90]
        flag = "AVAILABLE" if entitled else "NOT AVAILABLE"
        print(f"\n  [{flag:<13}] {name}   (http {st})")
        print(f"      needed for: {why}")
        if not entitled:
            print(f"      response  : {msg}")
        elif not ok:
            print(f"      note      : entitled but 0 rows on this probe window")

    print(f"\n{'-' * 78}")
    if avail.get("official imbalance v3") or avail.get("official imbalance v1"):
        mode = "OFFICIAL_AUCTION_IMBALANCE"
        print("  MODE: official auction imbalance available — use it, skip the proxy.")
    elif avail.get("NBBO quotes v3") and avail.get("trades v3"):
        mode = "LEE_READY_QUOTE"
        print("  MODE: no official imbalance; quotes+trades entitled -> canonical")
        print("        quote-based Lee-Ready is constructible.")
    elif avail.get("trades v3"):
        mode = "TICK_RULE"
        print("  MODE: no official imbalance, NO NBBO quotes -> canonical Lee-Ready")
        print("        is NOT constructible. Only the TICK RULE fallback remains.")
        print("        Downstream this measures PRE-OPEN SIGNED ORDER FLOW, which is")
        print("        NOT the opening auction imbalance. Do not conflate them.")
    else:
        mode = "NONE"
        print("  MODE: no usable source. Stop here.")
    print("-" * 78)
    return {"mode": mode, "entitlements": avail}


# ──────────────────────────────────────────────────────────────────────────
# Tick-rule classification
# ──────────────────────────────────────────────────────────────────────────
def _fetch_trades(ticker: str, gte_utc: str, lt_utc: str, key: str):
    """All trades in [gte, lt) as list of dicts. Paginates via next_url."""
    url = (f"{BASE}/v3/trades/{ticker}?timestamp.gte={gte_utc}"
           f"&timestamp.lt={lt_utc}&order=asc&sort=timestamp&limit={PAGE_LIMIT}")
    rows, pages = [], 0
    while url and pages < MAX_PAGES:
        st, body = _get(url, key)
        if st != 200 or not isinstance(body, dict):
            return rows, f"http {st}: {str(body)[:120]}"
        rows.extend(body.get("results") or [])
        nxt = body.get("next_url")
        url = nxt if nxt else None
        pages += 1
        time.sleep(0.05)
    return rows, None


def tick_rule_aggregate(trades: list) -> dict:
    """
    Tick rule (Lee-Ready fallback, standalone — no quotes available).

      price > last different price -> buyer-initiated  (+1)
      price < last different price -> seller-initiated (-1)
      price == last price          -> carry previous sign (zero-tick rule)
      no prior different price yet -> unclassified

    Returns raw counts/volumes so Step 2 can derive direction, magnitude and
    z-scored variants without refetching.
    """
    if not trades:
        return dict(n_trades=0, n_buy=0, n_sell=0, n_unclass=0,
                    buy_vol=0.0, sell_vol=0.0, unclass_vol=0.0, total_vol=0.0,
                    first_px=np.nan, last_px=np.nan, vwap=np.nan)

    # Polygon returns descending by default; we requested asc, but re-sort
    # defensively — tick-rule sign is order-dependent and a mis-sort silently
    # inverts the measurement.
    tr = sorted(trades, key=lambda t: (t.get("sip_timestamp", 0),
                                       t.get("sequence_number", 0)))

    n_buy = n_sell = n_unclass = 0
    buy_vol = sell_vol = unclass_vol = 0.0
    px_sum = 0.0
    last_px = None
    last_sign = 0

    for t in tr:
        px = t.get("price")
        sz = float(t.get("size") or 0.0)
        if px is None:
            continue
        px = float(px)
        if last_px is None:
            sign = 0
        elif px > last_px:
            sign = 1
        elif px < last_px:
            sign = -1
        else:
            sign = last_sign          # zero tick -> carry
        if sign == 1:
            n_buy += 1; buy_vol += sz
        elif sign == -1:
            n_sell += 1; sell_vol += sz
        else:
            n_unclass += 1; unclass_vol += sz
        px_sum += px * sz
        if last_px is None or px != last_px:
            last_px = px
            if sign != 0:
                last_sign = sign

    total_vol = buy_vol + sell_vol + unclass_vol
    return dict(
        n_trades=len(tr), n_buy=n_buy, n_sell=n_sell, n_unclass=n_unclass,
        buy_vol=buy_vol, sell_vol=sell_vol, unclass_vol=unclass_vol,
        total_vol=total_vol,
        first_px=float(tr[0].get("price", np.nan)),
        last_px=float(tr[-1].get("price", np.nan)),
        vwap=(px_sum / total_vol) if total_vol > 0 else np.nan,
    )


def _utc_bounds(day: pd.Timestamp, h0, m0, h1, m1):
    """ET wall-clock window -> UTC ISO strings. DST-correct (2021 EDT vs Dec EST)."""
    d = pd.Timestamp(day).date()
    start = pd.Timestamp(f"{d} {h0:02d}:{m0:02d}:00", tz=ET).tz_convert("UTC")
    end = pd.Timestamp(f"{d} {h1:02d}:{m1:02d}:00", tz=ET).tz_convert("UTC")
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


# ──────────────────────────────────────────────────────────────────────────
# SECTION B — per-event coverage over the real event population
# ──────────────────────────────────────────────────────────────────────────
def section_b(events: pd.DataFrame, key: str) -> pd.DataFrame:
    print(f"\n{'=' * 78}")
    print(f"SECTION B — PER-EVENT TICK COVERAGE  ({len(events)} events)")
    print("=" * 78)
    print(f"  windows: " + ", ".join(
        f"{k}={h0:02d}:{m0:02d}-{h1:02d}:{m1:02d} ET"
        for k, (h0, m0, h1, m1) in WINDOWS.items()))
    print(f"  MIN_TRADES (per-window usability floor) = {MIN_TRADES}\n")

    recs = []
    t_start = time.time()
    for i, (_, ev) in enumerate(events.iterrows(), 1):
        tk, day = ev["ticker"], pd.Timestamp(ev["date"])
        rec = {
            "ticker": tk,
            "date": day.date().isoformat(),
            "source": ev["source"],
            "direction": ev["direction"],
            "regime": ev["regime"],
            "gap_pct": ev.get("gap_pct", np.nan),
            "gap_suspect": bool(ev.get("gap_suspect", False)),
        }
        errs = []
        for wname, (h0, m0, h1, m1) in WINDOWS.items():
            gte, lt = _utc_bounds(day, h0, m0, h1, m1)
            trades, err = _fetch_trades(tk, gte, lt, key)
            if err:
                errs.append(f"{wname}:{err}")
            agg = tick_rule_aggregate(trades)
            for k, v in agg.items():
                rec[f"{wname}_{k}"] = v
            n_classified = agg["n_buy"] + agg["n_sell"]
            rec[f"{wname}_n_classified"] = n_classified
            rec[f"{wname}_usable"] = n_classified >= MIN_TRADES
        rec["fetch_error"] = "; ".join(errs) if errs else ""
        recs.append(rec)

        if i % 10 == 0 or i == len(events):
            el = time.time() - t_start
            print(f"  ... {i}/{len(events)} events  ({el:.0f}s elapsed, "
                  f"{el / i:.1f}s/event)")

    return pd.DataFrame(recs)


# ──────────────────────────────────────────────────────────────────────────
# SECTION C — coverage structure (era, ticker, liquidity tier)
# ──────────────────────────────────────────────────────────────────────────
def section_c(df: pd.DataFrame) -> None:
    print(f"\n{'=' * 78}")
    print("SECTION C — COVERAGE STRUCTURE")
    print("=" * 78)

    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year

    for w in WINDOWS:
        u = f"{w}_usable"
        n = f"{w}_n_classified"
        print(f"\n  WINDOW '{w}'")
        print(f"    usable events (>= {MIN_TRADES} classified): "
              f"{int(df[u].sum())}/{len(df)}  ({df[u].mean() * 100:.1f}%)")
        q = df[n].quantile([0.0, 0.10, 0.25, 0.50, 0.75, 0.90, 1.0])
        print(f"    classified-trade count percentiles: "
              f"min={q[0.0]:.0f} p10={q[0.10]:.0f} p25={q[0.25]:.0f} "
              f"med={q[0.50]:.0f} p75={q[0.75]:.0f} p90={q[0.90]:.0f} "
              f"max={q[1.0]:.0f}")
        print(f"    by year:")
        for yr, g in df.groupby("year"):
            print(f"      {yr}: {int(g[u].sum())}/{len(g)} "
                  f"({g[u].mean() * 100:.1f}%)  median n={g[n].median():.0f}")

    # Liquidity tier is measured, not assumed: rank tickers by their own median
    # full-window pre-market volume across their events.
    print(f"\n  PER-TICKER (median full-window classified trades, all events)")
    per = (df.groupby("ticker")
             .agg(n_events=("date", "size"),
                  med_full=("full_n_classified", "median"),
                  med_late=("late_n_classified", "median"),
                  usable_full=("full_usable", "mean"),
                  usable_late=("late_usable", "mean"))
             .sort_values("med_full", ascending=False))
    print(f"    {'ticker':<8}{'n_ev':>5}{'med_full':>10}{'med_late':>10}"
          f"{'use_full':>10}{'use_late':>10}")
    for tk, r in per.iterrows():
        print(f"    {tk:<8}{int(r.n_events):>5}{r.med_full:>10.0f}"
              f"{r.med_late:>10.0f}{r.usable_full * 100:>9.0f}%"
              f"{r.usable_late * 100:>9.0f}%")

    # A coverage filter that correlates with liquidity IS a selection effect —
    # surface it now, not in Step 3.
    print(f"\n  SELECTION-EFFECT CHECK (does usability track the event's own gap?)")
    for w in WINDOWS:
        sub = df[df["gap_pct"].notna()]
        if len(sub) > 5 and sub[f"{w}_usable"].nunique() > 1:
            a = sub[sub[f"{w}_usable"]]["gap_pct"].abs()
            b = sub[~sub[f"{w}_usable"]]["gap_pct"].abs()
            # gap_pct is stored in PERCENT units already (-2.77 == -2.77%)
            print(f"    {w}: mean |gap| usable={a.mean():.2f}% (n={len(a)}) "
                  f"vs excluded={b.mean():.2f}% (n={len(b)})")
        else:
            print(f"    {w}: all events on one side — no split to compare")

    # Date-level survival drives Step 3's within-date permutation power.
    print(f"\n  DATE STRUCTURE (drives Step 3 within-date permutation power)")
    print(f"    distinct dates, all events        : {df['date'].nunique()}")
    for w in WINDOWS:
        sub = df[df[f"{w}_usable"]]
        multi = sub.groupby("date").size()
        print(f"    {w}: usable events on {sub['date'].nunique()} dates | "
              f"dates with >=2 usable events = {int((multi >= 2).sum())}")


# ──────────────────────────────────────────────────────────────────────────
# SECTION D — verdict against the pre-committed thresholds
# ──────────────────────────────────────────────────────────────────────────
def section_d(df: pd.DataFrame, mode: str, sampled: bool) -> None:
    print(f"\n{'=' * 78}")
    print("SECTION D — GO / NO-GO VERDICT (pre-committed thresholds)")
    print("=" * 78)

    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year

    best_w, best_rate = None, -1.0
    for w in WINDOWS:
        r = df[f"{w}_usable"].mean()
        if r > best_rate:
            best_w, best_rate = w, r

    per_year = df.groupby("year")[f"{best_w}_usable"].mean()
    n_dates = df[df[f"{best_w}_usable"]]["date"].nunique()

    print(f"  best window            : '{best_w}'")
    print(f"  overall usable rate    : {best_rate * 100:.1f}%   "
          f"(GO>={GO_OVERALL * 100:.0f}%, NO-GO<{NOGO_OVERALL * 100:.0f}%)")
    for yr, v in per_year.items():
        print(f"  {yr} usable rate        : {v * 100:.1f}%   "
              f"(GO>={GO_PER_YEAR * 100:.0f}%)")
    print(f"  distinct usable dates  : {n_dates}   (GO>={GO_MIN_DATES})")

    year_ok = bool((per_year >= GO_PER_YEAR).all()) and len(per_year) >= 2
    if best_rate >= GO_OVERALL and year_ok and n_dates >= GO_MIN_DATES:
        verdict = "GO"
    elif best_rate < NOGO_OVERALL or not year_ok or n_dates < GO_MIN_DATES:
        verdict = "NO-GO"
    else:
        verdict = "MARGINAL"

    print(f"\n  VERDICT: {verdict}")
    if verdict == "GO":
        print("  -> proceed to Step 2 (feature construction + confound check)")
    elif verdict == "MARGINAL":
        print("  -> Step 2 permitted ONLY on the covered subset; the excluded")
        print("     population's composition must be reported as a selection effect.")
    else:
        print("  -> STOP. Record the coverage result; do not build Step 2.")

    if mode == "TICK_RULE":
        print(f"\n  SCOPE CAVEAT (carries into every downstream claim):")
        print("  This measures pre-open SIGNED ORDER FLOW via the tick rule, not the")
        print("  official opening auction imbalance, and not quote-based Lee-Ready.")
        print("  A null result does NOT clear the official-imbalance hypothesis.")
    if sampled:
        print(f"\n  NOTE: --sample was used. This verdict is provisional; rerun on the")
        print("  full event population before acting on it.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0,
                    help="Fetch only the first N events (spread across years) "
                         "for a fast provisional read. 0 = all events.")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="Reuse imbalance_coverage.parquet; only re-run C/D.")
    ap.add_argument("--resume", action="store_true",
                    help="Skip (ticker,date) pairs already in the cache and "
                         "append the rest. Lets the ~15-min full fetch be run "
                         "in several shorter passes.")
    ap.add_argument("--max-events", type=int, default=0,
                    help="With --resume: fetch at most N new events this pass, "
                         "then write and exit. 0 = no limit.")
    a = ap.parse_args()

    key = _load_api_key()

    print("=" * 78)
    print("OPENING IMBALANCE RESEARCH — STEP 1: COVERAGE / FEASIBILITY")
    print("RESEARCH ONLY — no production code touched.")
    print("=" * 78)

    probe = section_a(key)
    if probe["mode"] == "NONE":
        print("\nNo usable imbalance source. STOP — nothing to build.")
        return

    if a.skip_fetch and os.path.exists(OUT_PARQUET):
        df = pd.read_parquet(OUT_PARQUET)
        print(f"\n[--skip-fetch] reusing {OUT_PARQUET} ({len(df)} events)")
        sampled = False
    else:
        events = pd.read_parquet(EVENT_INDEX).reset_index()
        events["date"] = pd.to_datetime(events["date"])
        events = events.sort_values(["date", "ticker"]).reset_index(drop=True)
        sampled = a.sample > 0
        if sampled:
            # stratify the sample across years so a fast read still sees both eras
            events = (events.groupby(events["date"].dt.year, group_keys=False)
                            .apply(lambda g: g.head(max(1, a.sample // 2))))
            print(f"\n[--sample {a.sample}] using {len(events)} events "
                  f"(stratified by year)")
        prev = None
        if a.resume and os.path.exists(OUT_PARQUET):
            prev = pd.read_parquet(OUT_PARQUET)
            done = set(zip(prev["ticker"], prev["date"]))
            before = len(events)
            events = events[~events.apply(
                lambda r: (r["ticker"],
                           pd.Timestamp(r["date"]).date().isoformat()) in done,
                axis=1)]
            print(f"\n[--resume] {len(prev)} events already cached; "
                  f"{len(events)} of {before} remain")
            if a.max_events and len(events) > a.max_events:
                events = events.head(a.max_events)
                print(f"[--max-events {a.max_events}] fetching "
                      f"{len(events)} this pass")

        if len(events) == 0:
            df = prev
            print("  nothing left to fetch — cache is complete")
        else:
            df = section_b(events, key)
            if prev is not None:
                df = pd.concat([prev, df], ignore_index=True)
            df.to_parquet(OUT_PARQUET, index=False)
            print(f"\n  cached signed aggregates -> {OUT_PARQUET} "
                  f"({len(df)} events total)")
            remaining = 155 - len(df)
            if a.resume and remaining > 0:
                print(f"  {remaining} events still to fetch — rerun with "
                      f"--resume to continue")

    errs = df[df["fetch_error"] != ""] if "fetch_error" in df else df.iloc[:0]
    if len(errs):
        print(f"\n  FETCH ERRORS on {len(errs)} events:")
        for _, r in errs.head(15).iterrows():
            print(f"    {r['ticker']} {r['date']}: {r['fetch_error']}")

    section_c(df)
    section_d(df, probe["mode"], sampled)
    print("=" * 78)


if __name__ == "__main__":
    main()
