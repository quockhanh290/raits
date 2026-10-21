from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests


PLAN_CSV = Path("STOCKS_PIT_LIMITED_5MIN_FETCH_CHUNKS_2026-09-12.csv")
OUT_DIR = Path("raits/data/cache/polygon_5min_pit_limited_probe_2024")
STATUS_CSV = OUT_DIR / "status.csv"
MANIFEST_JSON = OUT_DIR / "manifest.json"
INTERVAL = 5


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


def polygon_api_ticker(symbol: str) -> str:
    # Polygon's REST endpoint accepts most class-share symbols with dots. Keep the
    # raw daily-universe ticker here and let status rows expose any exceptions.
    return symbol


def load_plan(limit_symbols: list[str] | None) -> pd.DataFrame:
    plan = pd.read_csv(PLAN_CSV, parse_dates=["start", "end"])
    if limit_symbols:
        wanted = {x.strip().upper() for x in limit_symbols if x.strip()}
        plan = plan[plan["symbol"].astype(str).str.upper().isin(wanted)].copy()
    if plan.empty:
        raise SystemExit("Fetch plan is empty after filters")
    if plan["end"].max() > pd.Timestamp("2024-12-31"):
        raise SystemExit("Refusing to fetch dates after 2024-12-31")
    plan["api_ticker"] = plan["symbol"].astype(str).map(polygon_api_ticker)
    return plan.sort_values(["symbol", "start"]).reset_index(drop=True)


def load_done_status() -> set[tuple[str, str, str]]:
    if not STATUS_CSV.exists():
        return set()
    status = pd.read_csv(STATUS_CSV)
    required = {"symbol", "start", "end", "status"}
    if status.empty or not required.issubset(status.columns):
        return set()
    latest = status.drop_duplicates(["symbol", "start", "end"], keep="last")
    done = latest[latest["status"].isin(["OK", "EMPTY"])]
    return set(zip(done["symbol"].astype(str), done["start"].astype(str), done["end"].astype(str)))


def output_path(symbol: str, start: pd.Timestamp) -> Path:
    return OUT_DIR / symbol / f"{symbol}_{INTERVAL}m_{start.strftime('%Y-%m')}.parquet"


def already_done(row: pd.Series, done: set[tuple[str, str, str]]) -> bool:
    start = pd.Timestamp(row["start"]).strftime("%Y-%m-%d")
    end = pd.Timestamp(row["end"]).strftime("%Y-%m-%d")
    symbol = str(row["symbol"])
    if (symbol, start, end) in done:
        return True
    path = output_path(symbol, pd.Timestamp(row["start"]))
    return path.exists() and path.stat().st_size > 0


def append_status(row: dict[str, object]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    header = not STATUS_CSV.exists()
    pd.DataFrame([row]).to_csv(STATUS_CSV, mode="a", header=header, index=False)


def write_manifest(plan: pd.DataFrame, args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "purpose": "limited Polygon 5m fetch for PIT probe-window eligible symbols",
        "source_plan": str(PLAN_CSV).replace("\\", "/"),
        "output_dir": str(OUT_DIR).replace("\\", "/"),
        "status_csv": str(STATUS_CSV).replace("\\", "/"),
        "adjusted": True,
        "timezone": "US/Eastern naive timestamps after UTC conversion",
        "rth_filter": "09:30 through 16:00 inclusive",
        "oos_policy": "refuses dates after 2024-12-31",
        "symbols": int(plan["symbol"].nunique()),
        "chunks": int(len(plan)),
        "min_start": str(plan["start"].min().date()),
        "max_end": str(plan["end"].max().date()),
        "limit_symbols": args.symbols,
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    tmp = MANIFEST_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MANIFEST_JSON)


def fetch_chunk(
    session: requests.Session,
    key: str,
    symbol: str,
    api_ticker: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    retries: int,
    sleep_seconds: float,
) -> tuple[str, pd.DataFrame | None, str]:
    start_text = start.strftime("%Y-%m-%d")
    end_text = end.strftime("%Y-%m-%d")
    url = f"https://api.polygon.io/v2/aggs/ticker/{api_ticker}/range/{INTERVAL}/minute/{start_text}/{end_text}"
    params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key}
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                time.sleep(max(10.0, sleep_seconds * 10.0))
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


def save_chunk(symbol: str, start: pd.Timestamp, frame: pd.DataFrame) -> Path:
    path = output_path(symbol, start)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    frame.to_parquet(tmp, compression="snappy")
    tmp.replace(path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch limited PIT probe Polygon adjusted 5-minute chunks.")
    parser.add_argument("--symbols", default="", help="Comma-separated ticker subset for smoke tests.")
    parser.add_argument("--max-chunks", type=int, default=0, help="Stop after N attempted chunks; 0 means all.")
    parser.add_argument("--sleep", type=float, default=0.13)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    limit_symbols = args.symbols.split(",") if args.symbols else None
    plan = load_plan(limit_symbols)
    write_manifest(plan, args)
    done = load_done_status()
    pending = [(_, row) for _, row in plan.iterrows() if not already_done(row, done)]

    print(f"OUT_DIR {OUT_DIR}")
    print(f"SYMBOLS {plan['symbol'].nunique()} CHUNKS {len(plan)} DONE {len(plan) - len(pending)} PENDING {len(pending)}")
    if args.dry_run:
        for _, row in pending[:10]:
            print(
                {
                    "symbol": row["symbol"],
                    "api_ticker": row["api_ticker"],
                    "start": pd.Timestamp(row["start"]).strftime("%Y-%m-%d"),
                    "end": pd.Timestamp(row["end"]).strftime("%Y-%m-%d"),
                    "path": str(output_path(str(row["symbol"]), pd.Timestamp(row["start"]))).replace("\\", "/"),
                }
            )
        return

    key = load_polygon_key()
    print(f"POLYGON_KEY loaded len={len(key)} suffix={key[-4:]}")
    session = requests.Session()
    attempted = ok = empty = errors = skipped = 0
    for _, row in pending:
        if args.max_chunks and attempted >= args.max_chunks:
            break
        if already_done(row, done):
            skipped += 1
            continue
        attempted += 1
        symbol = str(row["symbol"])
        start = pd.Timestamp(row["start"])
        end = pd.Timestamp(row["end"])
        status, frame, error = fetch_chunk(session, key, symbol, str(row["api_ticker"]), start, end, args.retries, args.sleep)
        rows = 0
        path = output_path(symbol, start)
        if status == "OK" and frame is not None:
            path = save_chunk(symbol, start, frame)
            rows = int(len(frame))
            ok += 1
        elif status == "EMPTY":
            empty += 1
        else:
            errors += 1
        append_status(
            {
                "ts_utc": pd.Timestamp.utcnow().isoformat(),
                "security_id": row["security_id"],
                "instrument_id": int(row["instrument_id"]),
                "symbol": symbol,
                "api_ticker": row["api_ticker"],
                "start": start.strftime("%Y-%m-%d"),
                "end": end.strftime("%Y-%m-%d"),
                "status": status,
                "rows": rows,
                "path": str(path).replace("\\", "/"),
                "error": error,
            }
        )
        if attempted % 25 == 0 or status == "ERROR":
            print(f"attempted={attempted} ok={ok} empty={empty} errors={errors} skipped={skipped} last={symbol} {start.date()} {status}", flush=True)
        time.sleep(args.sleep)

    print(f"DONE attempted={attempted} ok={ok} empty={empty} errors={errors} skipped={skipped}")
    print("RESUME: rerun the same command; OK/EMPTY chunks and existing parquet files are skipped.")


if __name__ == "__main__":
    main()
