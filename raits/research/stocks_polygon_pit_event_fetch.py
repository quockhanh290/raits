from __future__ import annotations

from pathlib import Path

import argparse
import importlib.util
import json
import os
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
import requests


BASE_URL = "https://api.polygon.io"
OUT_DIR = Path("raits/data/cache/external_events/polygon_2018_2024")
STATUS_CSV = OUT_DIR / "status.csv"
MANIFEST_JSON = OUT_DIR / "manifest.json"
MIN_DATE = pd.Timestamp("2018-01-01")
MAX_DATE = pd.Timestamp("2024-12-31")

FINANCIAL_COLUMNS = [
    "cik",
    "company_name",
    "start_date",
    "end_date",
    "filing_date",
    "fiscal_period",
    "fiscal_year",
    "timeframe",
    "sic",
    "source_filing_url",
    "source_filing_file_url",
    "financials_json",
]
NEWS_COLUMNS = [
    "id",
    "published_utc",
    "title",
    "description",
    "author",
    "article_url",
    "amp_url",
    "publisher_name",
    "publisher_homepage_url",
    "publisher_logo_url",
    "publisher_favicon_url",
    "tickers_json",
    "keywords_json",
]


def load_polygon_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if key:
        return key
    for path in [Path("config_private.py"), Path("raits/config_private.py"), Path("raits/raits/config_private.py")]:
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location("config_private", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        key = str(getattr(module, "POLYGON_API_KEY", "")).strip()
        if key:
            return key
    raise SystemExit("POLYGON_API_KEY not found")


def month_chunks(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    starts = pd.date_range(start.to_period("M").start_time, end.to_period("M").start_time, freq="MS")
    return [(max(value, start), min(value + pd.offsets.MonthBegin(1), end + pd.Timedelta(days=1))) for value in starts]


def add_key(url: str, key: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["apiKey"] = key
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def request_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None,
    key: str,
    retries: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, params={**(params or {}), "apiKey": key}, timeout=60)
        except requests.RequestException as exc:
            if attempt == retries:
                raise RuntimeError(f"Polygon request failed: {type(exc).__name__}") from None
            time.sleep(sleep_seconds * attempt)
            continue
        if response.status_code == 429:
            time.sleep(max(10.0, sleep_seconds * attempt * 5.0))
            continue
        if response.status_code >= 400:
            raise RuntimeError(f"Polygon HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        if payload.get("status") not in {"OK", "DELAYED"}:
            raise RuntimeError(f"Polygon status={payload.get('status')}")
        return payload
    raise RuntimeError("Polygon retry loop exhausted")


def normalize_financial(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cik": row.get("cik"),
        "company_name": row.get("company_name"),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
        "filing_date": row.get("filing_date"),
        "fiscal_period": row.get("fiscal_period"),
        "fiscal_year": row.get("fiscal_year"),
        "timeframe": row.get("timeframe"),
        "sic": row.get("sic"),
        "source_filing_url": row.get("source_filing_url"),
        "source_filing_file_url": row.get("source_filing_file_url"),
        "financials_json": json.dumps(row.get("financials") or {}, sort_keys=True, separators=(",", ":")),
    }


def normalize_news(row: dict[str, Any]) -> dict[str, Any]:
    publisher = row.get("publisher") or {}
    return {
        "id": row.get("id"),
        "published_utc": row.get("published_utc"),
        "title": row.get("title"),
        "description": row.get("description"),
        "author": row.get("author"),
        "article_url": row.get("article_url"),
        "amp_url": row.get("amp_url"),
        "publisher_name": publisher.get("name"),
        "publisher_homepage_url": publisher.get("homepage_url"),
        "publisher_logo_url": publisher.get("logo_url"),
        "publisher_favicon_url": publisher.get("favicon_url"),
        "tickers_json": json.dumps(row.get("tickers") or [], separators=(",", ":")),
        "keywords_json": json.dumps(row.get("keywords") or [], separators=(",", ":")),
    }


def fetch_chunk(
    dataset: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    key: str,
    retries: int,
    sleep_seconds: float,
) -> tuple[pd.DataFrame, int]:
    if dataset == "financials":
        url = f"{BASE_URL}/vX/reference/financials"
        params: dict[str, Any] = {
            "filing_date.gte": start.strftime("%Y-%m-%d"),
            "filing_date.lt": end_exclusive.strftime("%Y-%m-%d"),
            "timeframe": "quarterly",
            "limit": 100,
            "sort": "filing_date",
            "order": "asc",
        }
        normalize = normalize_financial
        columns = FINANCIAL_COLUMNS
    elif dataset == "news":
        url = f"{BASE_URL}/v2/reference/news"
        params = {
            "published_utc.gte": start.strftime("%Y-%m-%dT00:00:00Z"),
            "published_utc.lt": end_exclusive.strftime("%Y-%m-%dT00:00:00Z"),
            "limit": 1000,
            "sort": "published_utc",
            "order": "asc",
        }
        normalize = normalize_news
        columns = NEWS_COLUMNS
    else:
        raise ValueError(dataset)

    session = requests.Session()
    rows: list[dict[str, Any]] = []
    pages = 0
    while url:
        payload = request_page(session, url, params, key, retries, sleep_seconds)
        pages += 1
        rows.extend(normalize(row) for row in (payload.get("results") or []))
        next_url = payload.get("next_url")
        url = add_key(str(next_url), key) if next_url else ""
        params = None
        if sleep_seconds > 0 and url:
            time.sleep(sleep_seconds)
    return pd.DataFrame(rows, columns=columns), pages


def output_path(dataset: str, start: pd.Timestamp) -> Path:
    return OUT_DIR / dataset / f"{dataset}_{start.strftime('%Y-%m')}.parquet"


def append_status(row: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(STATUS_CSV, mode="a", header=not STATUS_CSV.exists(), index=False)


def write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, index=False)
    tmp.replace(path)


def write_manifest(args: argparse.Namespace, chunks: list[tuple[pd.Timestamp, pd.Timestamp]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "script": "raits/research/stocks_polygon_pit_event_fetch.py",
        "source": "Polygon REST API",
        "datasets": args.dataset,
        "start": args.start,
        "end": args.end,
        "oos_guard": "Hard refusal for any end date after 2024-12-31.",
        "chunking": "calendar month; existing non-empty parquet files are skipped",
        "financials_endpoint": "/vX/reference/financials filtered by filing_date and quarterly timeframe",
        "news_endpoint": "/v2/reference/news filtered by published_utc",
        "financials_pit_timestamp": "filing_date; exact intraday publication time is unavailable",
        "news_pit_timestamp": "published_utc",
        "chunks_planned": len(chunks),
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    tmp = MANIFEST_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MANIFEST_JSON)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch resumable Polygon PIT financial filing and news events.")
    parser.add_argument("--dataset", choices=["financials", "news", "both"], default="both")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--max-months", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = pd.Timestamp(args.start).normalize()
    end = pd.Timestamp(args.end).normalize()
    if start < MIN_DATE or end > MAX_DATE or start > end:
        raise SystemExit(f"Refusing range outside {MIN_DATE.date()} through {MAX_DATE.date()}")
    chunks = month_chunks(start, end)
    if args.max_months > 0:
        chunks = chunks[: args.max_months]
    datasets = ["financials", "news"] if args.dataset == "both" else [args.dataset]
    print(f"PLAN datasets={datasets} months={len(chunks)} range={start.date()}..{end.date()}", flush=True)
    if args.dry_run:
        return
    key = load_polygon_key()
    write_manifest(args, chunks)
    for dataset in datasets:
        for chunk_start, chunk_end in chunks:
            path = output_path(dataset, chunk_start)
            if path.exists() and path.stat().st_size > 0:
                print(f"SKIP {dataset} {chunk_start:%Y-%m}", flush=True)
                continue
            started = time.time()
            try:
                frame, pages = fetch_chunk(dataset, chunk_start, chunk_end, key, args.retries, args.sleep)
                write_atomic(frame, path)
                status = "OK"
                error = ""
            except Exception as exc:
                frame = pd.DataFrame()
                pages = 0
                status = "ERROR"
                error = f"{type(exc).__name__}: {exc}"
            append_status(
                {
                    "dataset": dataset,
                    "month": chunk_start.strftime("%Y-%m"),
                    "status": status,
                    "rows": len(frame),
                    "pages": pages,
                    "elapsed_seconds": round(time.time() - started, 3),
                    "error": error,
                    "updated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                }
            )
            print(f"{status} {dataset} {chunk_start:%Y-%m} rows={len(frame)} pages={pages} {error}", flush=True)
            if status == "ERROR":
                raise SystemExit(error)


if __name__ == "__main__":
    main()
