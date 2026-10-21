from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
import os
import threading
import time
from pathlib import Path

import pandas as pd
import requests


PLAN_CSV = Path("STOCKS_PIT_FULL_5MIN_FETCH_CHUNKS_2026-09-13.csv")
OUT_DIR = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
STATUS_CSV = OUT_DIR / "status.csv"
MANIFEST_JSON = OUT_DIR / "manifest.json"
INTERVAL = 5
ALLOW_OOS = False


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
    return symbol


def safe_symbol(symbol: str) -> str:
    return symbol.replace("/", "_")


def output_path(symbol: str, start: pd.Timestamp) -> Path:
    safe = safe_symbol(symbol)
    return OUT_DIR / safe / f"{safe}_{INTERVAL}m_{start.strftime('%Y-%m')}.parquet"


def load_plan(limit_symbols: list[str] | None) -> pd.DataFrame:
    if not PLAN_CSV.exists():
        raise SystemExit(f"Missing plan CSV: {PLAN_CSV}. Run stocks_pit_full_5min_fetch_plan.py first.")
    plan = pd.read_csv(PLAN_CSV, parse_dates=["start", "end"])
    if limit_symbols:
        wanted = {x.strip().upper() for x in limit_symbols if x.strip()}
        plan = plan[plan["symbol"].astype(str).str.upper().isin(wanted)].copy()
    if plan.empty:
        raise SystemExit("Fetch plan is empty after filters")
    if plan["end"].max() > pd.Timestamp("2024-12-31") and not ALLOW_OOS:
        raise SystemExit("Refusing to fetch dates after 2024-12-31")
    plan["api_ticker"] = plan["symbol"].astype(str).map(polygon_api_ticker)
    plan["output_key"] = plan["symbol"].astype(str) + "|" + plan["start"].dt.strftime("%Y-%m")
    plan = (
        plan.groupby("output_key", as_index=False)
        .agg(
            security_id=("security_id", "first"),
            symbol=("symbol", "first"),
            api_ticker=("api_ticker", "first"),
            start=("start", "min"),
            end=("end", "max"),
            eligible_days_in_chunk=("eligible_days_in_chunk", "sum"),
        )
        .drop(columns=["output_key"])
    )
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


def already_done(row: pd.Series, done: set[tuple[str, str, str]]) -> bool:
    start = pd.Timestamp(row["start"]).strftime("%Y-%m-%d")
    end = pd.Timestamp(row["end"]).strftime("%Y-%m-%d")
    symbol = str(row["symbol"])
    if (symbol, start, end) in done:
        return True
    path = output_path(symbol, pd.Timestamp(row["start"]))
    return path.exists() and path.stat().st_size > 0


def load_force_keys(path: str) -> set[tuple[str, str]]:
    if not path:
        return set()
    data = pd.read_csv(path)
    if {"symbol", "ym"}.issubset(data.columns):
        return set(zip(data["symbol"].astype(str), data["ym"].astype(str)))
    if {"symbol", "start"}.issubset(data.columns):
        start = pd.to_datetime(data["start"]).dt.strftime("%Y-%m")
        return set(zip(data["symbol"].astype(str), start.astype(str)))
    raise SystemExit(f"force keys file must have symbol+ym or symbol+start columns: {path}")


def append_status(row: dict[str, object]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    header = not STATUS_CSV.exists()
    pd.DataFrame([row]).to_csv(STATUS_CSV, mode="a", header=header, index=False)


def write_manifest(plan: pd.DataFrame, args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "purpose": "full PIT eligible Polygon 5-minute fetch",
        "source_plan": str(PLAN_CSV).replace("\\", "/"),
        "output_dir": str(OUT_DIR).replace("\\", "/"),
        "status_csv": str(STATUS_CSV).replace("\\", "/"),
        "endpoint": "/v2/aggs/ticker/{ticker}/range/5/minute/{start}/{end}",
        "adjusted": True,
        "timezone": "US/Eastern naive timestamps after UTC conversion",
        "rth_filter": "09:30 through 16:00 inclusive",
        "oos_policy": "explicitly allowed" if ALLOW_OOS else "refuses dates after 2024-12-31",
        "symbols": int(plan["symbol"].nunique()),
        "chunks": int(len(plan)),
        "min_start": str(plan["start"].min().date()),
        "max_end": str(plan["end"].max().date()),
        "limit_symbols": args.symbols,
        "resume_rule": "skip latest OK/EMPTY status rows and existing non-empty parquet files",
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    tmp = MANIFEST_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(MANIFEST_JSON)


def fetch_chunk(
    session: requests.Session,
    key: str,
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
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    frame.to_parquet(tmp, compression="snappy")
    tmp.replace(path)
    return path


def fetch_and_save_row(row: pd.Series, key: str, retries: int, sleep_seconds: float) -> dict[str, object]:
    symbol = str(row["symbol"])
    start = pd.Timestamp(row["start"])
    end = pd.Timestamp(row["end"])
    path = output_path(symbol, start)
    with requests.Session() as session:
        status, frame, error = fetch_chunk(session, key, str(row["api_ticker"]), start, end, retries, sleep_seconds)
    rows = 0
    if status == "OK" and frame is not None:
        path = save_chunk(symbol, start, frame)
        rows = int(len(frame))
    return {
        "ts_utc": pd.Timestamp.utcnow().isoformat(),
        "security_id": row["security_id"],
        "symbol": symbol,
        "api_ticker": row["api_ticker"],
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "eligible_days_in_chunk": int(row["eligible_days_in_chunk"]),
        "status": status,
        "rows": rows,
        "path": str(path).replace("\\", "/"),
        "error": error,
    }


def main() -> None:
    global PLAN_CSV, OUT_DIR, STATUS_CSV, MANIFEST_JSON, ALLOW_OOS
    parser = argparse.ArgumentParser(description="Fetch full PIT eligible Polygon adjusted 5-minute chunks.")
    parser.add_argument("--symbols", default="", help="Comma-separated ticker subset for smoke tests.")
    parser.add_argument("--max-chunks", type=int, default=0, help="Stop after N attempted chunks; 0 means all.")
    parser.add_argument("--sleep", type=float, default=0.13)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--workers", type=int, default=1, help="Concurrent fetch workers. Start low to avoid rate limits.")
    parser.add_argument("--force-keys-file", default="", help="CSV with symbol+ym or symbol+start rows to refetch even if parquet exists.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan-csv", default=str(PLAN_CSV))
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    parser.add_argument("--allow-oos", action="store_true", help="Required to access dates after 2024-12-31.")
    args = parser.parse_args()

    PLAN_CSV = Path(args.plan_csv)
    OUT_DIR = Path(args.out_dir)
    STATUS_CSV = OUT_DIR / "status.csv"
    MANIFEST_JSON = OUT_DIR / "manifest.json"
    ALLOW_OOS = bool(args.allow_oos)

    limit_symbols = args.symbols.split(",") if args.symbols else None
    plan = load_plan(limit_symbols)
    force_keys = load_force_keys(args.force_keys_file)
    if force_keys:
        plan["ym"] = plan["start"].dt.strftime("%Y-%m")
        plan = plan[plan.apply(lambda r: (str(r["symbol"]), str(r["ym"])) in force_keys, axis=1)].drop(columns=["ym"])
        if plan.empty:
            raise SystemExit("No plan rows matched --force-keys-file")
    write_manifest(plan, args)
    done = load_done_status()
    pending = [(_, row) for _, row in plan.iterrows() if force_keys or not already_done(row, done)]

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
                    "eligible_days_in_chunk": int(row["eligible_days_in_chunk"]),
                    "path": str(output_path(str(row["symbol"]), pd.Timestamp(row["start"]))).replace("\\", "/"),
                }
            )
        return

    key = load_polygon_key()
    print(f"POLYGON_KEY loaded len={len(key)} suffix={key[-4:]}")
    attempted = ok = empty = errors = skipped = 0
    selected = []
    for _, row in pending:
        if args.max_chunks and len(selected) >= args.max_chunks:
            break
        if not force_keys and already_done(row, done):
            skipped += 1
            continue
        selected.append(row)

    workers = max(1, int(args.workers))
    print(f"WORKERS {workers} SELECTED {len(selected)}")
    if workers == 1:
        for row in selected:
            attempted += 1
            result = fetch_and_save_row(row, key, args.retries, args.sleep)
            status = str(result["status"])
            if status == "OK":
                ok += 1
            elif status == "EMPTY":
                empty += 1
            else:
                errors += 1
            append_status(result)
            if attempted % 25 == 0 or status == "ERROR":
                print(
                    f"attempted={attempted} ok={ok} empty={empty} errors={errors} skipped={skipped} "
                    f"last={result['symbol']} {result['start']} {status}",
                    flush=True,
                )
            time.sleep(args.sleep)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch_and_save_row, row, key, args.retries, args.sleep) for row in selected]
            for future in as_completed(futures):
                attempted += 1
                try:
                    result = future.result()
                except Exception as exc:
                    errors += 1
                    result = {
                        "symbol": "<worker>",
                        "start": "",
                        "status": "ERROR",
                        "error": f"{type(exc).__name__}: {str(exc)[:220]}",
                    }
                    print(
                        f"attempted={attempted} ok={ok} empty={empty} errors={errors} skipped={skipped} "
                        f"last={result['symbol']} {result['start']} {result['status']} {result['error']}",
                        flush=True,
                    )
                    continue
                status = str(result["status"])
                if status == "OK":
                    ok += 1
                elif status == "EMPTY":
                    empty += 1
                else:
                    errors += 1
                append_status(result)
                if attempted % 25 == 0 or status == "ERROR":
                    print(
                        f"attempted={attempted} ok={ok} empty={empty} errors={errors} skipped={skipped} "
                        f"last={result['symbol']} {result['start']} {status}",
                        flush=True,
                    )

    print(f"DONE attempted={attempted} ok={ok} empty={empty} errors={errors} skipped={skipped}")
    print("RESUME: rerun the same command; OK/EMPTY chunks and existing parquet files are skipped.")


if __name__ == "__main__":
    main()
