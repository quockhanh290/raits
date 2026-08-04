"""
Opening Imbalance Research — Databento feasibility probe (revisit condition #4).
(EXPERIMENTAL harness, orb_stocks/imbalance_research/)  — RESEARCH ONLY.

The Polygon study (FINDINGS.md) could NOT test the hypothesis as written:
Polygon has no auction-imbalance endpoint (404) and no NBBO entitlement (403),
so only a tick-rule PROXY was testable. Databento's SDK exposes an `imbalance`
schema whose record type carries `side`, `total_imbalance_qty`, `paired_qty`,
`ref_price` and `ind_match_price` — i.e. the actual NYSE/Nasdaq auction
imbalance (NOII), the input the hypothesis was originally about.

This script answers three questions using METADATA ONLY — it downloads no
market data and (apart from metadata calls) incurs no data cost:

  1. Does the `imbalance` schema exist for the datasets our tickers list on?
  2. Does history cover the study window 2021-04-28 .. 2022-12-27?
  3. What would the actual fetch COST, in USD and bytes?

Nothing is fetched here. Run this, read the cost, THEN decide.

The 31-ticker event universe splits across listing venues, so both primary
datasets are probed:
    XNAS.ITCH   — Nasdaq TotalView-ITCH (Nasdaq-listed names)
    XNYS.PILLAR — NYSE Integrated       (NYSE-listed names)
ARCX.PILLAR / BATS.PITCH / EDGX.PITCH are probed too, for completeness: a
venue that merely TRADES a name does not run its opening auction, so only the
LISTING venue's imbalance feed is the real auction imbalance. Treat non-listing
venues as diagnostic, not as a substitute.

Requires:
    set DATABENTO_API_KEY=db-XXXXXXXX      (same env var as global_index/fetch.py
                                            and nonequity/fetch.py — no new
                                            auth mechanism, no new key file)

Run:
    cd d:\\raits
    python orb_stocks\\imbalance_research\\check_databento_imbalance.py
"""

from __future__ import annotations

import os
import sys

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
EVENT_INDEX = os.path.join(REPO, "raits", "data", "cache", "news",
                           "orb_event_index.parquet")

# Study window — must match FINDINGS.md / the event index exactly.
WS, WE = "2021-04-28", "2022-12-27"

DATASETS = [
    ("XNAS.ITCH",   "Nasdaq TotalView-ITCH — listing venue for Nasdaq names"),
    ("XNYS.PILLAR", "NYSE Integrated — listing venue for NYSE names"),
    ("ARCX.PILLAR", "NYSE Arca (diagnostic — not a listing venue for our pool)"),
    ("BATS.PITCH",  "Cboe BZX (diagnostic)"),
    ("EDGX.PITCH",  "Cboe EDGX (diagnostic)"),
]

SCHEMA = "imbalance"


def main() -> None:
    key = os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        print("=" * 78)
        print("DATABENTO IMBALANCE PROBE — NO API KEY")
        print("=" * 78)
        print("  DATABENTO_API_KEY is not set in this shell.")
        print("  Same env var the existing fetchers use "
              "(global_index/fetch.py, nonequity/fetch.py).")
        print("\n  PowerShell:  $env:DATABENTO_API_KEY = 'db-XXXXXXXX'")
        print("  then rerun this script.")
        print("\n  Nothing was fetched. No cost incurred.")
        print("=" * 78)
        return

    import databento as db
    client = db.Historical(key)

    tickers = sorted(pd.read_parquet(EVENT_INDEX).reset_index()["ticker"].unique())

    print("=" * 78)
    print("DATABENTO IMBALANCE PROBE  (metadata only — no data downloaded)")
    print(f"study window: {WS} .. {WE}   |   {len(tickers)} tickers")
    print("=" * 78)

    usable = []

    for ds, why in DATASETS:
        print(f"\n{'-' * 78}")
        print(f"DATASET {ds}")
        print(f"  role: {why}")
        print(f"{'-' * 78}")

        # 1. schema present?
        try:
            schemas = list(client.metadata.list_schemas(dataset=ds))
        except Exception as e:
            print(f"  SCHEMAS: ERROR — {type(e).__name__}: {str(e)[:150]}")
            continue
        has = SCHEMA in schemas
        print(f"  '{SCHEMA}' schema available: {'YES' if has else 'NO'}")
        if not has:
            print(f"    (schemas offered: {', '.join(sorted(schemas))[:200]})")
            continue

        # 2. history covers the window?
        try:
            rng = client.metadata.get_dataset_range(dataset=ds)
        except Exception as e:
            print(f"  RANGE: ERROR — {type(e).__name__}: {str(e)[:150]}")
            continue
        start = str(rng.get("start", rng.get("start_date", "?")))
        end = str(rng.get("end", rng.get("end_date", "?")))
        covers = start[:10] <= WS and end[:10] >= WE
        print(f"  history: {start[:10]} .. {end[:10]}")
        print(f"  covers study window: {'YES' if covers else 'NO'}")
        if not covers:
            print("    -> cannot test the study window on this dataset")
            continue

        # 3. which of our tickers resolve here, and what does it cost?
        try:
            cost = client.metadata.get_cost(
                dataset=ds, symbols=tickers, schema=SCHEMA,
                start=WS, end=WE, stype_in="raw_symbol",
            )
            size = client.metadata.get_billable_size(
                dataset=ds, symbols=tickers, schema=SCHEMA,
                start=WS, end=WE, stype_in="raw_symbol",
            )
            print(f"  COST for all {len(tickers)} tickers, full window: "
                  f"${cost:,.2f}   ({size / 1e6:,.1f} MB billable)")
            usable.append((ds, cost, size))
        except Exception as e:
            print(f"  COST: ERROR — {type(e).__name__}: {str(e)[:200]}")
            print("    (a symbol-resolution failure here usually means some "
                  "tickers do not list on this venue — expected for the "
                  "diagnostic datasets)")

    # ── verdict ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 78}")
    print("VERDICT")
    print("=" * 78)
    if not usable:
        print("  No dataset offers `imbalance` over the study window.")
        print("  Revisit condition #4 stays blocked.")
    else:
        total = sum(c for _, c, _ in usable[:2])   # the two listing venues
        print(f"  `imbalance` IS available over {WS}..{WE} on:")
        for ds, c, s in usable:
            print(f"    {ds:<14} ${c:,.2f}  ({s / 1e6:,.1f} MB)")
        print(f"\n  Combined cost for the two LISTING venues "
              f"(XNAS + XNYS): ~${total:,.2f}")
        print("\n  This unblocks the hypothesis the Polygon study could not test:")
        print("    - real auction imbalance (side + total_imbalance_qty +")
        print("      paired_qty + ind_match_price), not a tick-rule proxy")
        print("    - measured at the auction itself, not 09:00-09:30 pre-open flow")
        print("\n  Before fetching, decide the SCOPE. The binding constraint in")
        print("  the Polygon study was MIXED-DATE COUNT (23), not event count —")
        print("  fetching the same 155 events buys a better-measured variable on")
        print("  the SAME thin conditional sample. Widening the event population")
        print("  (more dates carrying both arms) is what actually adds power.")
    print("=" * 78)


if __name__ == "__main__":
    main()
