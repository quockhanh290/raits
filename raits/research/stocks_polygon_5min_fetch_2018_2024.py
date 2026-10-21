from __future__ import annotations

import argparse
import calendar
import importlib.util
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


START = "2018-01-01"
END = "2024-12-31"
INTERVAL = 5
OUT_DIR = Path("raits/data/cache/polygon_5min_2018_2024_62")
STATUS_CSV = OUT_DIR / "status.csv"
MANIFEST_JSON = OUT_DIR / "manifest.json"
UNIVERSE_SOURCE = Path("raits/data/cache/stocks_intraday_0935_features_CAUSEQA_2026-09-10.pkl")
META_RENAME_DATE = pd.Timestamp("2022-06-09")


@dataclass(frozen=True)
class Chunk:
    cache_ticker: str
    api_ticker: str
    start: str
    end: str
    path: str


def load_polygon_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if key:
        return key

    for path in [
        Path("config_private.py"),
        Path("raits/config_private.py"),
        Path("raits/raits/config_private.py"),
    ]:
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location("config_private", path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        key = str(getattr(mod, "POLYGON_API_KEY", "")).strip()
        if key:
            return key
    raise SystemExit("POLYGON_API_KEY not found in env or config_private.py")


def load_universe(limit_tickers: list[str] | None) -> list[str]:
    df = pd.read_pickle(UNIVERSE_SOURCE)
    tickers = sorted(df["ticker"].astype(str).unique())
    if limit_tickers:
        wanted = {x.strip().upper() for x in limit_tickers if x.strip()}
        tickers = sorted(wanted)
    if not tickers:
        raise SystemExit("No tickers selected")
    return tickers


def month_ranges(start: str, end: str) -> list[tuple[str, str]]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    months = []
    cur = pd.Timestamp(date(start_ts.year, start_ts.month, 1))
    while cur <= end_ts:
        last_day = calendar.monthrange(cur.year, cur.month)[1]
        m_start = max(start_ts, cur)
        m_end = min(end_ts, pd.Timestamp(date(cur.year, cur.month, last_day)))
        months.append((m_start.strftime("%Y-%m-%d"), m_end.strftime("%Y-%m-%d")))
        cur = cur + pd.DateOffset(months=1)
    return months


def api_ticker_for(cache_ticker: str, chunk_start: str) -> str:
    if cache_ticker == "META" and pd.Timestamp(chunk_start) < META_RENAME_DATE:
        return "FB"
    return cache_ticker


def output_path(cache_ticker: str, start: str, end: str) -> Path:
    del end
    return OUT_DIR / cache_ticker / f"{cache_ticker}_{INTERVAL}m_{start[:7]}.parquet"


def build_chunks(tickers: Iterable[str], start: str, end: str) -> list[Chunk]:
    chunks = []
    for ticker in tickers:
        for chunk_start, chunk_end in month_ranges(start, end):
            chunks.append(
                Chunk(
                    cache_ticker=ticker,
                    api_ticker=api_ticker_for(ticker, chunk_start),
                    start=chunk_start,
                    end=chunk_end,
                    path=str(output_path(ticker, chunk_start, chunk_end)).replace("\\", "/"),
                )
            )
    return chunks


def load_done_status() -> set[tuple[str, str, str]]:
    if not STATUS_CSV.exists():
        return set()
    status = pd.read_csv(STATUS_CSV)
    if status.empty or not {"cache_ticker", "start", "end", "status"}.issubset(status.columns):
        return set()
    latest = status.drop_duplicates(["cache_ticker", "start", "end"], keep="last")
    done = latest[latest["status"].isin(["OK", "EMPTY"])]
    return set(zip(done["cache_ticker"].astype(str), done["start"].astype(str), done["end"].astype(str)))


def append_status(row: dict[str, object]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    header = not STATUS_CSV.exists()
    pd.DataFrame([row]).to_csv(STATUS_CSV, mode="a", header=header, index=False)


def write_manifest(tickers: list[str], chunks: list[Chunk], args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "Polygon aggregates REST API",
        "endpoint": "/v2/aggs/ticker/{ticker}/range/5/minute/{start}/{end}",
        "adjusted": True,
        "timezone": "US/Eastern naive timestamps after UTC conversion",
        "rth_filter": "09:30 through 16:00 inclusive",
        "start": args.start,
        "end": args.end,
        "oos_policy": "does not request dates after 2024-12-31",
        "tickers": tickers,
        "chunk_count": len(chunks),
        "output_dir": str(OUT_DIR).replace("\\", "/"),
        "status_csv": str(STATUS_CSV).replace("\\", "/"),
        "resume_rule": "skip existing OK/EMPTY chunk statuses and existing non-empty parquet files",
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    tmp = MANIFEST_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MANIFEST_JSON)


def fetch_chunk(session: requests.Session, key: str, chunk: Chunk, retries: int, sleep_seconds: float) -> tuple[str, pd.DataFrame | None, str]:
    url = f"https://api.polygon.io/v2/aggs/ticker/{chunk.api_ticker}/range/{INTERVAL}/minute/{chunk.start}/{chunk.end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key}
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                wait = max(10.0, sleep_seconds * 10.0)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                body = resp.text.replace(key, "REDACTED") if key else resp.text
                return "ERROR", None, f"HTTP {resp.status_code}: {body[:220]}"
            data = resp.json()
            results = data.get("results") or []
            if not results:
                return "EMPTY", None, str(data.get("status", "no results"))
            frame = pd.DataFrame(results)
            frame = frame.rename(
                columns={
                    "o": "open",
                    "h": "high",
                    "l": "low",
                    "c": "close",
                    "v": "volume",
                    "vw": "vwap",
                    "n": "transactions",
                    "t": "timestamp",
                }
            )
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
            frame["timestamp"] = frame["timestamp"].dt.tz_convert("US/Eastern").dt.tz_localize(None)
            keep = ["timestamp", "open", "high", "low", "close", "volume"]
            for col in ["vwap", "transactions"]:
                if col in frame.columns:
                    keep.append(col)
            frame = frame[keep].set_index("timestamp").sort_index()
            frame = frame.between_time("09:30", "16:00")
            if frame.empty:
                return "EMPTY", None, "no RTH bars"
            return "OK", frame, ""
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:220]}"
            if key:
                last_error = last_error.replace(key, "REDACTED")
            if attempt < retries:
                time.sleep(max(sleep_seconds, 1.0) * attempt)
    return "ERROR", None, last_error


def save_chunk(chunk: Chunk, frame: pd.DataFrame) -> None:
    path = Path(chunk.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, compression="snappy")
    tmp.replace(path)


def already_done(chunk: Chunk, done: set[tuple[str, str, str]]) -> bool:
    if (chunk.cache_ticker, chunk.start, chunk.end) in done:
        return True
    path = Path(chunk.path)
    return path.exists() and path.stat().st_size > 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch resumable Polygon adjusted 5-minute bars for current stocks universe.")
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--tickers", default="", help="Comma-separated ticker subset for smoke tests.")
    parser.add_argument("--max-chunks", type=int, default=0, help="Stop after N chunks attempted; 0 means all.")
    parser.add_argument("--sleep", type=float, default=0.13, help="Pause between requests.")
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if pd.Timestamp(args.end) > pd.Timestamp("2024-12-31"):
        raise SystemExit("Refusing to open dates after 2024-12-31")

    tickers = load_universe(args.tickers.split(",") if args.tickers else None)
    chunks = build_chunks(tickers, args.start, args.end)
    write_manifest(tickers, chunks, args)
    done = load_done_status()
    pending = [chunk for chunk in chunks if not already_done(chunk, done)]

    print(f"OUT_DIR {OUT_DIR}")
    print(f"TICKERS {len(tickers)} CHUNKS {len(chunks)} DONE {len(chunks) - len(pending)} PENDING {len(pending)}")
    if args.dry_run:
        for chunk in pending[:10]:
            print(asdict(chunk))
        return

    key = load_polygon_key()
    print(f"POLYGON_KEY loaded len={len(key)} suffix={key[-4:]}")

    session = requests.Session()
    attempted = ok = empty = errors = skipped = 0
    for chunk in pending:
        if args.max_chunks and attempted >= args.max_chunks:
            break
        if already_done(chunk, done):
            skipped += 1
            continue
        attempted += 1
        status, frame, error = fetch_chunk(session, key, chunk, args.retries, args.sleep)
        rows = 0
        if status == "OK" and frame is not None:
            save_chunk(chunk, frame)
            rows = int(len(frame))
            ok += 1
        elif status == "EMPTY":
            empty += 1
        else:
            errors += 1
        append_status(
            {
                "ts_utc": pd.Timestamp.utcnow().isoformat(),
                "cache_ticker": chunk.cache_ticker,
                "api_ticker": chunk.api_ticker,
                "start": chunk.start,
                "end": chunk.end,
                "status": status,
                "rows": rows,
                "path": chunk.path,
                "error": error,
            }
        )
        if attempted % 25 == 0 or status == "ERROR":
            print(f"attempted={attempted} ok={ok} empty={empty} errors={errors} skipped={skipped} last={chunk.cache_ticker} {chunk.start} {status}", flush=True)
        time.sleep(args.sleep)

    print(f"DONE attempted={attempted} ok={ok} empty={empty} errors={errors} skipped={skipped}")
    print(f"RESUME: rerun the same command; OK/EMPTY chunks and existing parquet files are skipped.")


if __name__ == "__main__":
    main()
