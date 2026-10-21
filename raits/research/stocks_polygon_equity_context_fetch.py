from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
import requests


BASE = "https://api.massive.com"
OUT_DIR = Path("raits/data/cache/external_equity_context/polygon_2018_2024")
STATUS = OUT_DIR / "status.csv"
MANIFEST = OUT_DIR / "manifest.json"
MIN_DATE = pd.Timestamp("2018-01-01")
MAX_DATE = pd.Timestamp("2024-12-31")
DATASETS = {
    "dividends": ("/stocks/v1/dividends", "ex_dividend_date", 5000),
    "splits": ("/stocks/v1/splits", "execution_date", 5000),
    "short_interest": ("/stocks/v1/short-interest", "settlement_date", 5000),
    "short_volume": ("/stocks/v1/short-volume", "date", 5000),
    "edgar_index": ("/stocks/filings/vX/index", "filing_date", 50000),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if key:
        return key
    for path in (Path("config_private.py"), Path("raits/config_private.py"), Path("raits/raits/config_private.py")):
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


def add_key(url: str, key: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["apiKey"] = key
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def month_chunks(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    starts = pd.date_range(start.to_period("M").start_time, end.to_period("M").start_time, freq="MS")
    return [(max(start, month), min(end + pd.Timedelta(days=1), month + pd.offsets.MonthBegin(1))) for month in starts]


def request(session: requests.Session, url: str, params: dict[str, Any] | None, key: str,
            retries: int) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, params={**(params or {}), "apiKey": key}, timeout=120)
            if response.status_code == 429:
                time.sleep(min(60.0, 5.0 * attempt))
                continue
            if response.status_code >= 400:
                body = response.text.replace(key, "REDACTED")
                raise RuntimeError(f"HTTP {response.status_code}: {body[:300]}")
            payload = response.json()
            if payload.get("status") not in {"OK", "DELAYED"}:
                raise RuntimeError(f"API status {payload.get('status')}")
            return payload
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc).replace(key, 'REDACTED')[:400]}"
            if attempt < retries:
                time.sleep(min(30.0, 2.0 * attempt))
    raise RuntimeError(last_error)


def serializable_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        if frame[column].map(lambda value: isinstance(value, (dict, list))).any():
            frame[column] = frame[column].map(
                lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"))
                if isinstance(value, (dict, list)) else value
            )
    return frame


def fetch_chunk(dataset: str, start: pd.Timestamp, end_exclusive: pd.Timestamp, key: str,
                retries: int, sleep_seconds: float) -> tuple[pd.DataFrame, int]:
    endpoint, date_field, limit = DATASETS[dataset]
    url = BASE + endpoint
    params: dict[str, Any] | None = {
        f"{date_field}.gte": start.strftime("%Y-%m-%d"),
        f"{date_field}.lt": end_exclusive.strftime("%Y-%m-%d"),
        "sort": f"{date_field}.asc",
        "limit": limit,
    }
    rows: list[dict[str, Any]] = []
    pages = 0
    with requests.Session() as session:
        while url:
            payload = request(session, url, params, key, retries)
            pages += 1
            rows.extend(payload.get("results") or [])
            next_url = str(payload.get("next_url") or "")
            if next_url:
                host = urlsplit(next_url).netloc
                if host not in {"api.massive.com", "api.polygon.io"}:
                    raise RuntimeError(f"Unexpected pagination host: {host}")
                url = add_key(next_url, key)
                params = None
                if sleep_seconds:
                    time.sleep(sleep_seconds)
            else:
                url = ""
    return serializable_frame(rows), pages


def output_path(dataset: str, month: pd.Timestamp) -> Path:
    return OUT_DIR / dataset / f"{dataset}_{month:%Y-%m}.parquet"


def append_status(row: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{ "completedAtUtc": pd.Timestamp.now(tz="UTC").isoformat(), **row }]).to_csv(
        STATUS, mode="a", header=not STATUS.exists(), index=False
    )


def write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    frame.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(path)


def fetch_static(key: str, retries: int) -> list[dict[str, Any]]:
    specs = [
        ("trade_conditions", "https://api.polygon.io/v3/reference/conditions",
         {"asset_class": "stocks", "data_type": "trade", "limit": 1000}),
        ("quote_conditions", "https://api.polygon.io/v3/reference/conditions",
         {"asset_class": "stocks", "data_type": "quote", "limit": 1000}),
        ("exchanges", "https://api.polygon.io/v3/reference/exchanges",
         {"asset_class": "stocks", "locale": "us"}),
    ]
    outcomes = []
    with requests.Session() as session:
        for name, url, params in specs:
            path = OUT_DIR / "reference" / f"{name}.parquet"
            if path.exists() and path.stat().st_size > 0:
                outcomes.append({"dataset": name, "status": "SKIP", "rows": None, "path": str(path).replace("\\", "/")})
                continue
            payload = request(session, url, params, key, retries)
            frame = serializable_frame(payload.get("results") or [])
            write_atomic(frame, path)
            outcomes.append({"dataset": name, "status": "OK", "rows": len(frame), "path": str(path).replace("\\", "/")})
    return outcomes


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable Polygon equity context fetch; no prices or OOS performance.")
    parser.add_argument("--dataset", choices=[*DATASETS, "all"], default="all")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--max-months", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    start, end = pd.Timestamp(args.start).normalize(), pd.Timestamp(args.end).normalize()
    if start < MIN_DATE or end > MAX_DATE or start > end:
        raise SystemExit(f"Refusing range outside {MIN_DATE.date()} through {MAX_DATE.date()}")
    chunks = month_chunks(start, end)
    if args.max_months:
        chunks = chunks[:args.max_months]
    datasets = list(DATASETS) if args.dataset == "all" else [args.dataset]
    plan = [(dataset, left, right) for dataset in datasets for left, right in chunks]
    print(f"PLAN datasets={datasets} chunks={len(plan)} range={start.date()}..{end.date()}", flush=True)
    if args.dry_run:
        return
    key = load_key()
    static = fetch_static(key, args.retries)
    total_rows = total_pages = completed = skipped = 0
    for index, (dataset, left, right) in enumerate(plan, start=1):
        path = output_path(dataset, left)
        if path.exists() and path.stat().st_size > 0:
            skipped += 1
            continue
        try:
            frame, pages = fetch_chunk(dataset, left, right, key, args.retries, args.sleep)
            write_atomic(frame, path)
            row = {"dataset": dataset, "month": left.strftime("%Y-%m"), "status": "OK",
                   "rows": len(frame), "pages": pages, "bytes": path.stat().st_size,
                   "path": str(path).replace("\\", "/"), "error": ""}
            completed += 1
            total_rows += len(frame)
            total_pages += pages
        except Exception as exc:
            row = {"dataset": dataset, "month": left.strftime("%Y-%m"), "status": "ERROR",
                   "rows": 0, "pages": 0, "bytes": 0, "path": str(path).replace("\\", "/"),
                   "error": f"{type(exc).__name__}: {str(exc).replace(key, 'REDACTED')[:400]}"}
        append_status(row)
        if index % 20 == 0 or row["status"] == "ERROR":
            print(f"progress={index}/{len(plan)} completed={completed} skipped={skipped} rows={total_rows} last={row['status']}:{dataset}:{left:%Y-%m}", flush=True)
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "source": "Polygon/Massive REST API", "datasets": datasets, "dateRange": [str(start.date()), str(end.date())],
        "dateContract": "context records only; fetching does not open or score validation performance",
        "maxDateGuard": str(MAX_DATE.date()), "post2024Consumed": False,
        "existingDataNotDuplicated": ["tick trades", "five-minute aggregates", "news", "quarterly financials"],
        "staticReference": static, "chunksPlanned": len(plan), "chunksCompletedThisRun": completed,
        "chunksSkippedThisRun": skipped, "rowsThisRun": total_rows, "pagesThisRun": total_pages,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
