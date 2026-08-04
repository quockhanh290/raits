"""
ORB Stocks — Step 0: Polygon news coverage check.

Purpose (ONLY this):
    Answer a single go/no-go question before building anything else —
    "Does Polygon have enough historical NEWS coverage for our universe and
    period to make a catalyst/news-text pipeline worth building?"

This is NOT the fetch/cache module, NOT LLM classification, NOT a backtest.
It calls Polygon's news endpoint (/v2/reference/news via
RESTClient.list_ticker_news) for a handful of (ticker, month) probes and
prints coverage stats so we can eyeball density and spot zero/near-zero holes.

Auth pattern mirrors the existing Polygon scripts (audit_spy_exdiv.py,
update_spy_csv.py): read POLYGON_API_KEY from config_private.py, falling back
to the POLYGON_API_KEY environment variable. No new key, no new auth mechanism.

Run:
    cd d:\\raits
    python orb_stocks\\check_news_coverage.py
"""

from __future__ import annotations

import os
import sys
import importlib.util

from polygon import RESTClient

# Windows consoles default to cp1252 and choke on non-ASCII; force UTF-8 so
# headlines with unicode don't crash the print loop.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ──────────────────────────────────────────────────────────────────────────
# API key — same pattern as _archive/scratch/audit_spy_exdiv.py
# ──────────────────────────────────────────────────────────────────────────
def _load_api_key() -> str:
    """config_private.POLYGON_API_KEY, else POLYGON_API_KEY env var."""
    # Look for config_private.py at the repo root regardless of CWD.
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        os.path.join(here, "..", "config_private.py"),   # d:\raits\config_private.py
        os.path.join(here, "config_private.py"),
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
        sys.exit(
            "FATAL: POLYGON_API_KEY not found in config_private.py or env var.\n"
            "Key lives in config_private.py at the repo root (gitignored)."
        )
    return key


# ──────────────────────────────────────────────────────────────────────────
# Probes: (ticker, why-it-was-chosen) × (year-month) — deliberately small.
# Tickers drawn from strategies/universe_scanner.py CANDIDATE_POOL + SPY.
# ──────────────────────────────────────────────────────────────────────────
TICKERS = [
    ("AAPL", "mega-cap (primary probe)"),
    ("MSFT", "mega-cap"),
    ("EBAY", "mid-size within the pool"),
    ("HON",  "mid-size within the pool (industrial)"),
    ("SPY",  "benchmark"),
]

# (label, gte, lte) — one 2020 month and one 2022 month to compare eras.
PERIODS = [
    ("2020-01", "2020-01-01", "2020-01-31"),
    ("2022-06", "2022-06-01", "2022-06-30"),
]

MAX_ARTICLES = 2000   # hard cap so a runaway paginator can't spin forever

# Coverage-onset scan: 2020-01 came back empty for the whole universe, which
# smells like a plan-based historical cutoff rather than "no news existed".
# Walk AAPL month-by-month to find where Polygon's news history actually begins.
ONSET_MONTHS = [
    ("2020-01", "2020-01-01", "2020-01-31"),
    ("2020-04", "2020-04-01", "2020-04-30"),
    ("2020-07", "2020-07-01", "2020-07-31"),
    ("2020-10", "2020-10-01", "2020-10-31"),
    ("2021-01", "2021-01-01", "2021-01-31"),
    ("2021-04", "2021-04-01", "2021-04-30"),
    ("2021-07", "2021-07-01", "2021-07-31"),
    ("2021-10", "2021-10-01", "2021-10-31"),
]


def probe(client: RESTClient, ticker: str, gte: str, lte: str) -> dict:
    """Fetch news for one ticker/month; return count + date span + samples."""
    articles = []
    try:
        it = client.list_ticker_news(
            ticker=ticker,
            published_utc_gte=gte,
            published_utc_lte=lte,
            order="asc",
            sort="published_utc",
            limit=1000,
        )
        for art in it:
            articles.append(art)
            if len(articles) >= MAX_ARTICLES:
                break
    except Exception as exc:  # rate limit, plan restriction, network, etc.
        return {"error": f"{type(exc).__name__}: {exc}"}

    pubs = [getattr(a, "published_utc", None) for a in articles]
    pubs = [p for p in pubs if p]
    pubs_sorted = sorted(pubs)

    samples = []
    for a in articles[:3]:
        samples.append(
            (getattr(a, "published_utc", "?"), (getattr(a, "title", "") or "").strip())
        )

    return {
        "count": len(articles),
        "capped": len(articles) >= MAX_ARTICLES,
        "earliest": pubs_sorted[0] if pubs_sorted else None,
        "latest": pubs_sorted[-1] if pubs_sorted else None,
        "samples": samples,
    }


def main() -> None:
    key = _load_api_key()
    client = RESTClient(key)

    print("=" * 78)
    print("ORB STOCKS — STEP 0: Polygon news coverage check")
    print(f"Endpoint: /v2/reference/news (RESTClient.list_ticker_news)")
    print(f"Article cap per probe: {MAX_ARTICLES}")
    print("=" * 78)

    # Wide table of counts first (easy to scan for zeros), details below.
    summary = {}  # (ticker, period_label) -> count-or-ERR

    for period_label, gte, lte in PERIODS:
        print(f"\n{'#' * 78}")
        print(f"# PERIOD {period_label}  ({gte} .. {lte})")
        print(f"{'#' * 78}")

        for ticker, why in TICKERS:
            res = probe(client, ticker, gte, lte)
            header = f"\n[{ticker}]  ({why})"
            print(header)

            if "error" in res:
                print(f"    ERROR: {res['error']}")
                summary[(ticker, period_label)] = "ERR"
                continue

            cap_note = "  (CAPPED — more exist)" if res["capped"] else ""
            print(f"    articles returned : {res['count']}{cap_note}")
            print(f"    earliest published: {res['earliest']}")
            print(f"    latest   published: {res['latest']}")
            if res["samples"]:
                print(f"    sample headlines  :")
                for pub, title in res["samples"]:
                    title_short = (title[:90] + "…") if len(title) > 90 else title
                    print(f"        - [{pub}] {title_short}")
            else:
                print(f"    sample headlines  : (none)")

            summary[(ticker, period_label)] = res["count"]

    # ── Compact matrix + zero/near-zero flags ─────────────────────────────
    print(f"\n{'=' * 78}")
    print("SUMMARY MATRIX  (article count per ticker × period)")
    print("=" * 78)
    period_labels = [p[0] for p in PERIODS]
    print(f"{'ticker':<8}" + "".join(f"{pl:>12}" for pl in period_labels))
    for ticker, _why in TICKERS:
        row = f"{ticker:<8}"
        for pl in period_labels:
            row += f"{str(summary.get((ticker, pl), '?')):>12}"
        print(row)

    # Flag anything zero / near-zero (<5) — that's the decision signal.
    print(f"\n{'-' * 78}")
    flags = []
    for (ticker, pl), val in summary.items():
        if val == "ERR":
            flags.append(f"  ⚠ {ticker} / {pl}: request ERROR (see above)")
        elif isinstance(val, int) and val < 5:
            flags.append(f"  ⚠ {ticker} / {pl}: near-zero ({val} articles)")
    if flags:
        print("FLAGS (zero / near-zero / error - coverage concern):")
        for f in flags:
            print(f)
    else:
        print("FLAGS: none - every probe returned >=5 articles.")
    print("=" * 78)

    # ── Coverage-onset scan (AAPL, month-by-month 2020-2021) ──────────────
    print(f"\n{'=' * 78}")
    print("COVERAGE-ONSET SCAN  (AAPL, to locate where Polygon news begins)")
    print("=" * 78)
    print(f"{'month':<10}{'articles':>10}   earliest_published")
    for label, gte, lte in ONSET_MONTHS:
        res = probe(client, "AAPL", gte, lte)
        if "error" in res:
            print(f"{label:<10}{'ERR':>10}   {res['error']}")
        else:
            print(f"{label:<10}{res['count']:>10}   {res['earliest']}")
    print("=" * 78)


if __name__ == "__main__":
    main()
