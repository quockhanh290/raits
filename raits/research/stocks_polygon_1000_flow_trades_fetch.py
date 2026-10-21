from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

import pandas as pd
import requests


PLAN = Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.csv")
PLAN_MANIFEST = Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.json")
OUT_DIR = Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022")
STATUS = OUT_DIR / "status.csv"
MANIFEST = OUT_DIR / "manifest.json"
BASE_URL = "https://api.polygon.io"
START_CLOCK = "09:25:00"
END_CLOCK = "10:05:00"
MAX_DATE = pd.Timestamp("2022-12-30")
PAGE_LIMIT = 50_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_polygon_key() -> str:
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


def safe_symbol(symbol: str) -> str:
    return symbol.replace("/", "_")


def output_path(symbol: str, date: pd.Timestamp) -> Path:
    safe = safe_symbol(symbol)
    return OUT_DIR / date.strftime("%Y") / date.strftime("%m") / safe / f"{safe}_{date:%Y-%m-%d}_trades.parquet"


def load_plan() -> pd.DataFrame:
    plan = pd.read_csv(PLAN, usecols=["date", "ticker"], parse_dates=["date"])
    plan["date"] = plan["date"].dt.normalize()
    plan["ticker"] = plan["ticker"].astype(str).str.upper()
    plan = plan.drop_duplicates().sort_values(["date", "ticker"]).reset_index(drop=True)
    if plan.empty or plan["date"].max() > MAX_DATE:
        raise SystemExit("Refusing empty plan or dates after 2022-12-30")
    return plan


def load_done() -> set[tuple[str, str]]:
    if not STATUS.exists():
        return set()
    status = pd.read_csv(STATUS, dtype=str)
    if status.empty or not {"date", "ticker", "status"}.issubset(status.columns):
        return set()
    latest = status.drop_duplicates(["date", "ticker"], keep="last")
    latest = latest[latest["status"].isin(["OK", "EMPTY"])]
    return set(zip(latest["date"], latest["ticker"]))


def bounds_ns(date: pd.Timestamp) -> tuple[int, int]:
    day = date.strftime("%Y-%m-%d")
    start = pd.Timestamp(f"{day} {START_CLOCK}", tz="US/Eastern").tz_convert("UTC")
    end = pd.Timestamp(f"{day} {END_CLOCK}", tz="US/Eastern").tz_convert("UTC")
    return int(start.value), int(end.value)


def get_json(session: requests.Session, url: str, params: dict[str, object], key: str, retries: int) -> dict[str, object]:
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, params=params, timeout=90)
            if response.status_code == 429:
                time.sleep(min(60.0, 5.0 * attempt))
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text.replace(key, 'REDACTED')[:300]}")
            return response.json()
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc).replace(key, 'REDACTED')[:400]}"
            if attempt < retries:
                time.sleep(min(30.0, 2.0 * attempt))
    raise RuntimeError(last_error)


def fetch_one(item: tuple[pd.Timestamp, str], key: str, retries: int) -> dict[str, object]:
    date, ticker = item
    start_ns, end_ns = bounds_ns(date)
    url = f"{BASE_URL}/v3/trades/{ticker}"
    params: dict[str, object] = {"timestamp.gte": start_ns, "timestamp.lt": end_ns, "order": "asc",
                                 "sort": "timestamp", "limit": PAGE_LIMIT, "apiKey": key}
    pages: list[pd.DataFrame] = []
    page_count = 0
    with requests.Session() as session:
        while url:
            payload = get_json(session, url, params, key, retries)
            page_count += 1
            results = payload.get("results") or []
            if results:
                pages.append(pd.DataFrame(results))
            next_url = str(payload.get("next_url") or "")
            if not next_url:
                break
            parsed = urlparse(next_url)
            if parsed.netloc not in {"api.polygon.io", "api.massive.com"}:
                raise RuntimeError(f"Unexpected pagination host: {parsed.netloc}")
            url, params = next_url, {"apiKey": key}

    path = output_path(ticker, date)
    if not pages:
        return {"date": date.strftime("%Y-%m-%d"), "ticker": ticker, "status": "EMPTY", "rows": 0,
                "pages": page_count, "bytes": 0, "path": str(path).replace("\\", "/"), "error": ""}
    frame = pd.concat(pages, ignore_index=True)
    required = {"sip_timestamp", "price", "size"}
    if not required.issubset(frame.columns):
        raise RuntimeError(f"Missing fields: {sorted(required - set(frame.columns))}")
    frame["ticker"] = ticker
    frame["date"] = date.strftime("%Y-%m-%d")
    dedup = [column for column in ("sip_timestamp", "exchange", "id") if column in frame.columns]
    frame = frame.drop_duplicates(subset=dedup).sort_values(
        [column for column in ("sip_timestamp", "sequence_number") if column in frame.columns]
    )
    observed = frame["sip_timestamp"].astype("int64")
    if observed.min() < start_ns or observed.max() >= end_ns:
        raise RuntimeError("Polygon returned out-of-window trades")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(path)
    return {"date": date.strftime("%Y-%m-%d"), "ticker": ticker, "status": "OK", "rows": len(frame),
            "pages": page_count, "bytes": path.stat().st_size, "path": str(path).replace("\\", "/"), "error": ""}


def append_status(result: dict[str, object]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    row = {"completed_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), **result}
    pd.DataFrame([row]).to_csv(STATUS, mode="a", header=not STATUS.exists(), index=False)


def write_manifest(plan: pd.DataFrame, args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "purpose": "PIT YDAY-crash and gap-up 10:00 flow research",
        "script": str(Path(__file__)).replace("\\", "/"), "script_hash": sha256(Path(__file__)),
        "plan": str(PLAN), "plan_hash": sha256(PLAN),
        "plan_manifest": str(PLAN_MANIFEST), "plan_manifest_hash": sha256(PLAN_MANIFEST),
        "endpoint": "/v3/trades/{ticker}", "timestamp_field": "sip_timestamp",
        "window": {"start_inclusive_et": START_CLOCK, "end_exclusive_et": END_CLOCK},
        "causality": "10:00 signals may use only SIP arrivals strictly before 10:00 ET; 10:00-10:05 trades are execution diagnostics only",
        "date_range": [str(plan["date"].min().date()), str(plan["date"].max().date())],
        "ticker_days": len(plan), "tickers": int(plan["ticker"].nunique()),
        "old_manual_62_used": False, "post2022_allowed": False,
        "requested_limit": args.limit, "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    tmp = MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    tmp.replace(MANIFEST)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--retries", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        raise SystemExit("workers must be 1..16")
    plan = load_plan()
    write_manifest(plan, args)
    done = load_done()
    work = [(row.date, row.ticker) for row in plan.itertuples(index=False)
            if (row.date.strftime("%Y-%m-%d"), row.ticker) not in done and not output_path(row.ticker, row.date).exists()]
    if args.limit > 0:
        work = work[:args.limit]
    if not work:
        print("No unfinished ticker-days")
        return
    key = load_polygon_key()
    totals = {"OK": 0, "EMPTY": 0, "ERROR": 0, "rows": 0, "bytes": 0, "pages": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch_one, item, key, args.retries): item for item in work}
        for completed, future in enumerate(as_completed(futures), start=1):
            date, ticker = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"date": date.strftime("%Y-%m-%d"), "ticker": ticker, "status": "ERROR", "rows": 0,
                          "pages": 0, "bytes": 0, "path": str(output_path(ticker, date)).replace("\\", "/"),
                          "error": f"{type(exc).__name__}: {str(exc).replace(key, 'REDACTED')[:400]}"}
            append_status(result)
            totals[result["status"]] += 1
            for field in ("rows", "bytes", "pages"):
                totals[field] += int(result[field])
            if completed % 500 == 0 or completed == len(work):
                print(f"{completed}/{len(work)} OK={totals['OK']} EMPTY={totals['EMPTY']} ERROR={totals['ERROR']} "
                      f"rows={totals['rows']:,} GB={totals['bytes'] / 1e9:.2f} pages={totals['pages']}", flush=True)


if __name__ == "__main__":
    main()
