"""
Databento 1-minute equity OHLCV — feasibility + cost probe.
(RESEARCH ONLY — raits/raits/scripts/research/. Reads nothing from the engine,
writes nothing, modifies nothing.)

WHY THIS EXISTS
---------------
ORB_RETEST_SCALP could not be tested: the entire equity cache is 5-minute
(117,533 parquet files, all `_5min_`, modal bar delta 00:05:00, 79 RTH
bars/day). A retest-then-continuation strategy with a 2-4 bar retest window
and a 5-15 minute time stop is not testable on 5-minute bars — the retest IS
the intrabar path the bar hides. Verdict was INSUFFICIENT RESOLUTION.

Acquiring 1-minute bars from Polygon costs ~142,000 single-ticker-day calls
(~24h wall clock at the configured 100 calls/min). Databento does the same
pull as one batch job. This script decides whether that is worth doing.

WHAT IT DOES / DOES NOT DO
--------------------------
METADATA ONLY. It downloads no market data. `metadata.get_cost` and
`metadata.get_billable_size` are priced at $0 and return the exact figures
for a request without transferring it. Nothing here incurs data cost.

It answers the three questions that block the decision:

  1. WHICH dataset carries `ohlcv-1m` for our tickers, and is it consolidated
     or single-venue? Single-venue bars (XNAS.ITCH is Nasdaq prints only) have
     systematically different highs/lows than the consolidated tape the
     Polygon cache is built from — and ORB_RETEST_SCALP turns entirely on
     whether `low` touched OR_high. Dataset choice is not cosmetic here.
  2. Does history reach 2017-01, where the existing 5-minute cache starts?
     If Databento starts later, the overlap window with the ORB baseline
     shrinks and the "does retest improve ORB execution?" comparison loses
     years.
  3. What does it actually cost, at three scopes (full / 1-year pilot /
     subset pilot)?

Dataset names are DISCOVERED via `metadata.list_datasets()`, never hardcoded —
Databento has reorganised its US equities datasets before, and guessing a name
would produce a confidently wrong answer.

Requires:
    set DATABENTO_API_KEY=db-XXXXXXXX
    (same env var as global_index/fetch.py, nonequity/fetch.py, tier2/fetch.py
     — no new auth mechanism, no new key file)

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\databento_1min_cost_probe.py
"""

from __future__ import annotations

import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
CACHE_DIR = os.path.join(REPO, "raits", "data", "cache", "data")

SCHEMA = "ohlcv-1m"

# Study window — the span the existing 5-minute cache actually covers.
# Measured, not assumed: sampled parquet min/max were 2017-01 .. 2024-07.
FULL_START, FULL_END = "2017-01-03", "2024-07-31"

# Pilot: one year in which the primary hypothesis (Normal regime) has mass,
# chosen for being a plain non-crisis year — NOT chosen by looking at results.
PILOT_START, PILOT_END = "2019-01-02", "2019-12-31"

# Subset pilot: the most liquid names, enough to see whether a retest even
# occurs at workable frequency before paying for the full universe.
SUBSET = ["AAPL", "MSFT", "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL", "SPY", "QQQ"]

# ORB needs 09:30-10:15 only. Extended-hours bars roughly double the volume
# for zero benefit to this strategy. Reported so the scoping decision is
# explicit rather than accidental.
RTH_BARS_PER_DAY = 390
EXT_BARS_PER_DAY = 960


def discover_universe() -> list[str]:
    """
    The real ORB candidate pool = whatever the 5-minute cache actually holds.
    Derived from filenames so it cannot drift from the data on disk.
    """
    if not os.path.isdir(CACHE_DIR):
        return []
    pat = re.compile(r"^([A-Z.]+)_5min_.*\.parquet$")
    seen = set()
    for fn in os.listdir(CACHE_DIR):
        m = pat.match(fn)
        if m:
            seen.add(m.group(1))
    return sorted(seen)


def fmt_cost(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return str(v)


def probe_scope(client, ds: str, symbols: list[str], start: str, end: str, label: str):
    """One (dataset, symbols, window) -> (cost, billable_bytes) or None."""
    try:
        cost = client.metadata.get_cost(
            dataset=ds, symbols=symbols, schema=SCHEMA,
            start=start, end=end, stype_in="raw_symbol",
        )
        size = client.metadata.get_billable_size(
            dataset=ds, symbols=symbols, schema=SCHEMA,
            start=start, end=end, stype_in="raw_symbol",
        )
        print(f"    {label:<34} {fmt_cost(cost):>12}   "
              f"({size / 1e9:,.2f} GB billable, {len(symbols)} symbols)")
        return float(cost), int(size)
    except Exception as e:
        print(f"    {label:<34} ERROR — {type(e).__name__}: {str(e)[:120]}")
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full-only", action="store_true",
                    help="Only price the full-universe/full-history scope.")
    a = ap.parse_args()

    universe = discover_universe()

    print("=" * 78)
    print("DATABENTO ohlcv-1m PROBE  (metadata only — no data downloaded)")
    print("=" * 78)
    print(f"  repo        : {REPO}")
    print(f"  universe    : {len(universe)} tickers discovered in the 5-min cache")
    if universe:
        print(f"                {', '.join(universe[:12])}"
              f"{' ...' if len(universe) > 12 else ''}")
    print(f"  full window : {FULL_START} .. {FULL_END}")
    print(f"  pilot window: {PILOT_START} .. {PILOT_END}")
    print(f"  schema      : {SCHEMA}")

    if not universe:
        print(f"\n  ABORT: no 5-min parquet found under {CACHE_DIR}")
        print("  Nothing fetched. No cost incurred.")
        print("=" * 78)
        return

    # ── volume arithmetic, independent of the API ────────────────────────────
    # ~56 bytes per DBN ohlcv-1m record (16B header + 4 int64 prices + volume).
    # Approximate; the API's billable_size below is the authoritative figure.
    sessions = 1900   # ~trading days 2017-01 .. 2024-07
    rth_recs = len(universe) * sessions * RTH_BARS_PER_DAY
    ext_recs = len(universe) * sessions * EXT_BARS_PER_DAY
    print("\n  independent volume estimate (sanity check on the API figures):")
    print(f"    RTH only        ~{rth_recs / 1e6:,.1f}M records  "
          f"~{rth_recs * 56 / 1e9:,.1f} GB")
    print(f"    + ext. hours    ~{ext_recs / 1e6:,.1f}M records  "
          f"~{ext_recs * 56 / 1e9:,.1f} GB")
    print("    (a single get_range/batch job returns ALL hours — there is no")
    print("     RTH filter on a contiguous range request. ORB uses 09:30-10:15")
    print("     only, so the extended-hours half is paid for and discarded.)")

    key = os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        print("\n" + "=" * 78)
        print("NO API KEY — stopping before any call")
        print("=" * 78)
        print("  DATABENTO_API_KEY is not set in this shell.")
        print("  PowerShell:  $env:DATABENTO_API_KEY = 'db-XXXXXXXX'")
        print("  then rerun. Nothing was fetched. No cost incurred.")
        print("=" * 78)
        return

    import databento as db
    client = db.Historical(key)

    # ── 1. discover which datasets carry ohlcv-1m ────────────────────────────
    print("\n" + "-" * 78)
    print("STEP 1 — datasets offering ohlcv-1m")
    print("-" * 78)
    try:
        datasets = sorted(client.metadata.list_datasets())
    except Exception as e:
        print(f"  ERROR listing datasets — {type(e).__name__}: {str(e)[:200]}")
        return
    print(f"  {len(datasets)} datasets visible to this key")

    candidates = []
    for ds in datasets:
        try:
            schemas = set(client.metadata.list_schemas(dataset=ds))
        except Exception:
            continue
        if SCHEMA not in schemas:
            continue
        try:
            rng = client.metadata.get_dataset_range(dataset=ds)
        except Exception as e:
            print(f"  {ds:<16} ohlcv-1m YES | range ERROR {type(e).__name__}")
            continue
        start = str(rng.get("start", rng.get("start_date", "?")))[:10]
        end = str(rng.get("end", rng.get("end_date", "?")))[:10]
        reaches_2017 = start <= FULL_START
        print(f"  {ds:<16} history {start} .. {end}   "
              f"reaches {FULL_START}: {'YES' if reaches_2017 else 'NO'}")
        candidates.append((ds, start, end, reaches_2017))

    if not candidates:
        print("\n  No dataset offers ohlcv-1m to this key.")
        print("  Nothing fetched. No cost incurred.")
        print("=" * 78)
        return

    # ── 2. which resolve our equity tickers, and what do they cost ───────────
    print("\n" + "-" * 78)
    print("STEP 2 — cost by scope (equity datasets only; futures/options")
    print("         datasets will fail symbol resolution — that is expected")
    print("         and is itself the filter that identifies the equity ones)")
    print("-" * 78)

    results = {}
    for ds, start, end, reaches in candidates:
        # Clip the request to what the dataset actually holds, so a dataset
        # that starts late is priced on its real overlap rather than erroring.
        f_start = max(FULL_START, start)
        f_end = min(FULL_END, end)
        if f_start >= f_end:
            continue

        print(f"\n  {ds}   (usable overlap {f_start} .. {f_end})")
        scopes = [(f"FULL {len(universe)}t {f_start[:4]}-{f_end[:4]}",
                   universe, f_start, f_end)]
        if not a.full_only:
            p_start, p_end = max(PILOT_START, start), min(PILOT_END, end)
            if p_start < p_end:
                scopes.append((f"PILOT {len(universe)}t 1yr", universe, p_start, p_end))
                sub = [t for t in SUBSET if t in universe]
                if sub:
                    scopes.append((f"SUBSET {len(sub)}t 1yr", sub, p_start, p_end))

        got = []
        for label, syms, s, e in scopes:
            r = probe_scope(client, ds, syms, s, e, label)
            if r:
                got.append((label, r))
        if got:
            results[ds] = (f_start, f_end, reaches, got)

    # ── verdict ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    if not results:
        print("  No dataset both carries ohlcv-1m AND resolves our equity tickers.")
        print("  ORB_RETEST_SCALP stays blocked at INSUFFICIENT RESOLUTION.")
        print("=" * 78)
        return

    for ds, (s, e, reaches, got) in results.items():
        full = next((c for lbl, c in got if lbl.startswith("FULL")), None)
        print(f"\n  {ds}")
        print(f"    overlap with 5-min cache : {s} .. {e}")
        _reach = "YES" if reaches else "NO — the ORB comparison loses the early years"
        print(f"    reaches {FULL_START}         : {_reach}")
        if full:
            print(f"    full-scope cost          : {fmt_cost(full[0])} "
                  f"({full[1] / 1e9:,.2f} GB)")

    print("\n  BEFORE COMMITTING TO A FULL PULL — two things this probe cannot")
    print("  tell you, both of which decide whether the result is interpretable:")
    print()
    print("  1. CONSOLIDATED vs SINGLE-VENUE. A dataset covering one venue")
    print("     (e.g. Nasdaq prints only) yields 1-min highs/lows that differ")
    print("     systematically from the consolidated tape the Polygon 5-min")
    print("     cache is built from. ORB_RETEST_SCALP triggers on `low` touching")
    print("     OR_high — exactly the field that shifts. Check the dataset's")
    print("     venue coverage before choosing it.")
    print()
    print("  2. CROSS-SOURCE CONFOUND. If ORB_RETEST_SCALP runs on Databento")
    print("     bars while baseline ORB runs on Polygon bars, the required")
    print("     'does retest improve ORB execution?' comparison measures the")
    print("     data source as much as the rule change.")
    print("     Mitigation, cheap and decisive: after the pilot pull, resample")
    print("     Databento 1-min -> 5-min and reconcile against the existing")
    print("     Polygon 5-min cache on a sample of days. Match => the two arms")
    print("     are comparable. Mismatch => you know BEFORE interpreting any")
    print("     result, not after.")
    print()
    print("  Recommended order: SUBSET pilot -> reconcile vs Polygon 5-min ->")
    print("  PILOT year -> only then the full pull.")
    print("=" * 78)


if __name__ == "__main__":
    main()
