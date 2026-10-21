from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import argparse
import importlib.util
import json
import os
import time

import pandas as pd
import requests


START = "2018-01-01"
END = "2024-12-31"
INTERVAL = 5
ROOT = Path(__file__).resolve().parents[2]
SYMBOL_SOURCE = ROOT / "raits/data/cache/stocks_intraday_0935_features_CAUSEQA_2026-09-10.pkl"
OUT_DIR = ROOT / "raits/data/cache/polygon_5min_2018_2024_62"
STATUS_OUT = ROOT / "STOCKS_POLYGON_5MIN_2018_2024_62_FETCH_STATUS_2026-09-11.csv"
SMOKE_STATUS_OUT = ROOT / "STOCKS_POLYGON_5MIN_2018_2024_62_SMOKE_STATUS_2026-09-11.csv"
MANIFEST_OUT = ROOT / "STOCKS_POLYGON_5MIN_2018_2024_62_MANIFEST_2026-09-11.json"
BASE_URL = "https://api.polygon.io"
META_RENAME_DATE = pd.Timestamp("2022-06-09")


@dataclass(frozen=True)
class Task:
    ticker: str
    api_ticker: str
    start: str
    end: str
    out_path: Path


def load_polygon_key() -> str:
    env_key = os.environ.get("POLYGON_API_KEY", "").strip()
    if env_key:
        return env_key
    config = ROOT / "config_private.py"
    if not config.exists():
        raise SystemExit("POLYGON_API_KEY not found in env or config_private.py")
    spec = importlib.util.spec_from_file_location("config_private", config)
    if spec is None or spec.loader is None:
        raise SystemExit(f"could not load {config}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    key = getattr(module, "POLYGON_API_KEY", "")
    if not key:
        raise SystemExit("POLYGON_API_KEY missing in config_private.py")
    return str(key).strip()


def load_symbols() -> list[str]:
    df = pd.read_pickle(SYMBOL_SOURCE)
    return sorted(df["ticker"].astype(str).unique())


def month_ranges(start: str, end: str) -> list[tuple[str, str]]:
    starts = pd.date_range(pd.Timestamp(start).replace(day=1), pd.Timestamp(end), freq="MS")
    out = []
    final = pd.Timestamp(end)
    first = pd.Timestamp(start)
    for m in starts:
        s = max(m, first)
        e = min(m + pd.offsets.MonthEnd(0), final)
        if s <= e:
            out.append((s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")))
    return out


def api_ticker_for(ticker: str, start: str) -> str:
    if ticker == "META" and pd.Timestamp(start) < META_RENAME_DATE:
        return "FB"
    return ticker


def build_tasks(symbols: list[str], start: str, end: str, force: bool) -> list[Task]:
    tasks = []
    for ticker in symbols:
        ticker_dir = OUT_DIR / ticker
        for s, e in month_ranges(start, end):
            out_path = ticker_dir / f"{ticker}_5m_{s[:7]}.parquet"
            if output_complete(out_path) and not force:
                continue
            tasks.append(Task(ticker, api_ticker_for(ticker, s), s, e, out_path))
    return tasks


def output_complete(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.{os.getpid()}.{time.time_ns()}.tmp{path.suffix}")
    df.to_parquet(tmp, compression="snappy")
    tmp.replace(path)


def fetch_task(task: Task, key: str, retries: int, sleep_ms: int) -> dict[str, object]:
    url = f"{BASE_URL}/v2/aggs/ticker/{task.api_ticker}/range/{INTERVAL}/minute/{task.start}/{task.end}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key}
    started = time.time()
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(max(1.0, attempt * 2.0))
                continue
            if response.status_code != 200:
                return row(task, "ERROR", 0, response.status_code, response.text[:500], started)
            data = response.json()
            results = data.get("results") or []
            if not results:
                return row(task, "EMPTY", 0, response.status_code, data.get("status", ""), started)
            df = pd.DataFrame(results)
            df = df.rename(
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
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df["timestamp"] = df["timestamp"].dt.tz_convert("US/Eastern").dt.tz_localize(None)
            keep = ["timestamp", "open", "high", "low", "close", "volume"]
            if "vwap" in df.columns:
                keep.append("vwap")
            if "transactions" in df.columns:
                keep.append("transactions")
            df = df[keep].set_index("timestamp").sort_index()
            df = df.between_time("09:30", "16:00")
            if df.empty:
                return row(task, "EMPTY_RTH", 0, response.status_code, data.get("status", ""), started)
            atomic_write_parquet(df, task.out_path)
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
            return row(task, "OK", len(df), response.status_code, "", started)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(max(1.0, attempt * 2.0))
    return row(task, "ERROR", 0, 0, last_error[:500], started)


def row(task: Task, status: str, rows: int, http_status: int, error: str, started: float) -> dict[str, object]:
    return {
        "ticker": task.ticker,
        "apiTicker": task.api_ticker,
        "start": task.start,
        "end": task.end,
        "status": status,
        "rows": rows,
        "httpStatus": http_status,
        "seconds": round(time.time() - started, 3),
        "path": str(task.out_path.relative_to(ROOT)).replace("\\", "/"),
        "error": error,
    }


def write_status(rows: list[dict[str, object]], path: Path = STATUS_OUT, merge_existing: bool = True) -> None:
    current = pd.DataFrame(rows)
    if merge_existing and path.exists():
        try:
            previous = pd.read_csv(path)
            current = pd.concat([previous, current], ignore_index=True)
        except Exception:
            pass
    if current.empty:
        return
    keys = ["ticker", "apiTicker", "start", "end", "path"]
    current = current.drop_duplicates(keys, keep="last").sort_values(["ticker", "start", "apiTicker"])
    tmp = path.with_name(f".{path.stem}.{os.getpid()}.{time.time_ns()}.tmp{path.suffix}")
    current.to_csv(tmp, index=False)
    tmp.replace(path)


def smoke_test(key: str, symbols: list[str]) -> None:
    probes = [
        Task("AAPL", "AAPL", "2018-01-02", "2018-01-02", OUT_DIR / "_smoke" / "AAPL_2018-01-02.parquet"),
        Task("META", "FB", "2018-01-02", "2018-01-02", OUT_DIR / "_smoke" / "META_FB_2018-01-02.parquet"),
    ]
    if "AVGO" in symbols:
        probes.append(Task("AVGO", "AVGO", "2024-07-15", "2024-07-15", OUT_DIR / "_smoke" / "AVGO_2024-07-15.parquet"))
    rows = [fetch_task(t, key, retries=2, sleep_ms=0) for t in probes]
    write_status(rows, path=SMOKE_STATUS_OUT, merge_existing=False)
    bad = [r for r in rows if r["status"] == "ERROR"]
    print(pd.DataFrame(rows).to_string(index=False))
    if bad:
        raise SystemExit("smoke test failed; not starting full fetch")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Polygon adjusted 5-minute bars for current 62-stock research universe.")
    parser.add_argument("--start", default=START)
    parser.add_argument("--end", default=END)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--sleep-ms", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    args = parser.parse_args()

    key = load_polygon_key()
    symbols = load_symbols()
    print(f"symbols={len(symbols)} start={args.start} end={args.end} out={OUT_DIR}")
    print(f"key length={len(key)} prefix={key[:6]} suffix={key[-4:]}")

    smoke_test(key, symbols)
    if args.smoke_only:
        print(f"WROTE {SMOKE_STATUS_OUT}")
        return

    tasks = build_tasks(symbols, args.start, args.end, args.force)
    manifest = {
        "source": "polygon.io",
        "schema": "aggs range 5/minute adjusted=true",
        "start": args.start,
        "end": args.end,
        "symbolSource": str(SYMBOL_SOURCE.relative_to(ROOT)).replace("\\", "/"),
        "symbols": symbols,
        "outputDir": str(OUT_DIR.relative_to(ROOT)).replace("\\", "/"),
        "statusCsv": str(STATUS_OUT.relative_to(ROOT)).replace("\\", "/"),
        "workers": args.workers,
        "retries": args.retries,
        "sleepMs": args.sleep_ms,
        "force": args.force,
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"tasks={len(tasks)}")
    if not tasks:
        print("nothing to fetch")
        return

    rows: list[dict[str, object]] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(fetch_task, task, key, args.retries, args.sleep_ms) for task in tasks]
        for future in as_completed(futures):
            rows.append(future.result())
            completed += 1
            if completed % 100 == 0 or completed == len(tasks):
                ok = sum(1 for r in rows if r["status"] == "OK")
                empty = sum(1 for r in rows if str(r["status"]).startswith("EMPTY"))
                err = sum(1 for r in rows if r["status"] == "ERROR")
                print(f"progress {completed}/{len(tasks)} ok={ok} empty={empty} error={err}", flush=True)
                write_status(rows)
    write_status(rows)
    print(f"WROTE {STATUS_OUT}")
    print(f"WROTE {MANIFEST_OUT}")


if __name__ == "__main__":
    main()
