from __future__ import annotations

import argparse
import importlib.util
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


BASE_URL = "https://api.polygon.io"
PIT_DAILY = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)
OUT_DIR = Path("raits/data/cache/external_universes/market_cap_polygon")
OUT_CSV = OUT_DIR / "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
MANIFEST = OUT_DIR / "polygon_market_cap_snapshots_pit_eligible_2018_2024_manifest.json"

thread_local = threading.local()


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
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        key = str(getattr(mod, "POLYGON_API_KEY", "")).strip()
        if key:
            return key
    raise SystemExit("POLYGON_API_KEY not found")


def session() -> requests.Session:
    sess = getattr(thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        thread_local.session = sess
    return sess


def to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return np.nan
        return float(value)
    except Exception:
        return np.nan


def load_daily(path: Path = PIT_DAILY) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=["date", "ticker", "prior_close", "eligible_final"])
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["ticker"] = df["ticker"].astype(str).str.upper()
    df = df[df["eligible_final"].fillna(False)].copy()
    return df.sort_values(["date", "ticker"]).drop_duplicates(["date", "ticker"], keep="first")


def snapshot_dates(daily: pd.DataFrame, start: str, end: str, frequency: str) -> list[pd.Timestamp]:
    dates = pd.Series(sorted(daily.loc[daily["date"].between(start, end), "date"].drop_duplicates()))
    if frequency == "daily":
        return [pd.Timestamp(x) for x in dates]
    frame = pd.DataFrame({"date": dates})
    if frequency == "monthly":
        frame["bucket"] = frame["date"].dt.to_period("M")
    elif frequency == "quarterly":
        frame["bucket"] = frame["date"].dt.to_period("Q")
    elif frequency == "yearly":
        frame["bucket"] = frame["date"].dt.to_period("Y")
    else:
        raise ValueError(f"unsupported frequency: {frequency}")
    return [pd.Timestamp(x) for x in frame.groupby("bucket", sort=True)["date"].first().tolist()]


def load_done(path: Path) -> set[tuple[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    done = pd.read_csv(path, usecols=["date", "ticker_query", "status_code"])
    done = done[done["status_code"].notna()]
    return set(zip(done["date"].astype(str), done["ticker_query"].astype(str)))


def fetch_one(key: str, date: str, ticker: str, prior_close: float, max_retries: int) -> dict[str, Any]:
    url = f"{BASE_URL}/v3/reference/tickers/{ticker}"
    params = {"date": date, "apiKey": key}
    status_code = -1
    payload: dict[str, Any] = {}
    message = ""
    for attempt in range(max_retries + 1):
        try:
            resp = session().get(url, params=params, timeout=60)
            status_code = int(resp.status_code)
            try:
                payload = resp.json()
            except Exception:
                payload = {"status": "json_error", "message": resp.text[:300]}
            message = str(payload.get("message", ""))
            if status_code != 429 and status_code < 500:
                break
            wait = float(resp.headers.get("Retry-After", "0") or 0)
            time.sleep(wait if wait > 0 else min(2.0 * (attempt + 1), 10.0))
        except Exception as exc:
            message = repr(exc)
            time.sleep(min(2.0 * (attempt + 1), 10.0))

    result = payload.get("results") or {}
    market_cap = to_float(result.get("market_cap"))
    weighted_shares = to_float(result.get("weighted_shares_outstanding"))
    cap_from_weighted = prior_close * weighted_shares if np.isfinite(prior_close * weighted_shares) else np.nan
    return {
        "date": date,
        "ticker_query": ticker,
        "status_code": status_code,
        "api_status": payload.get("status"),
        "ticker_result": result.get("ticker"),
        "active": result.get("active"),
        "primary_exchange": result.get("primary_exchange"),
        "type": result.get("type"),
        "sic_description": result.get("sic_description"),
        "list_date": result.get("list_date"),
        "delisted_utc": result.get("delisted_utc"),
        "market_cap": market_cap,
        "weighted_shares_outstanding": weighted_shares,
        "pit_prior_close": prior_close,
        "cap_from_weighted_shares": cap_from_weighted,
        "market_cap_to_weighted_implied": market_cap / cap_from_weighted
        if cap_from_weighted and np.isfinite(cap_from_weighted)
        else np.nan,
        "message": message,
    }


def append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    pd.DataFrame(rows).to_csv(path, mode="a", header=not path.exists(), index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-02")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--frequency", choices=["daily", "monthly", "quarterly", "yearly"], default="quarterly")
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--max-calls", type=int, default=0, help="0 means all pending calls")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--flush-every", type=int, default=250)
    parser.add_argument("--pit-daily", default=str(PIT_DAILY))
    parser.add_argument("--out-csv", default=str(OUT_CSV))
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--allow-oos", action="store_true", help="Required to access dates after 2024-12-31.")
    args = parser.parse_args()

    pit_daily = Path(args.pit_daily)
    out_csv = Path(args.out_csv)
    manifest_path = Path(args.manifest)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if pd.Timestamp(args.end) > pd.Timestamp("2024-12-31") and not args.allow_oos:
        raise SystemExit("Refusing to open 2025-2026 OOS")
    key = load_polygon_key()
    daily = load_daily(pit_daily)
    dates = snapshot_dates(daily, args.start, args.end, args.frequency)
    date_strings = [d.strftime("%Y-%m-%d") for d in dates]
    done = load_done(out_csv)

    tasks: list[tuple[str, str, float]] = []
    for date_ts, date_str in zip(dates, date_strings):
        snap = daily[daily["date"].eq(date_ts)]
        for row in snap.itertuples(index=False):
            ticker = str(row.ticker)
            if (date_str, ticker) in done:
                continue
            tasks.append((date_str, ticker, float(row.prior_close)))
    total_pending_before_cap = len(tasks)
    if args.max_calls and len(tasks) > args.max_calls:
        tasks = tasks[: args.max_calls]

    started = time.time()
    written = 0
    buffer: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch_one, key, d, t, pc, args.max_retries) for d, t, pc in tasks]
        for idx, fut in enumerate(as_completed(futures), start=1):
            buffer.append(fut.result())
            if len(buffer) >= args.flush_every:
                append_rows(out_csv, buffer)
                written += len(buffer)
                buffer.clear()
                elapsed = max(time.time() - started, 1e-9)
                print(
                    json.dumps(
                        {
                            "written_this_run": written,
                            "completed_this_run": idx,
                            "selected_this_run": len(tasks),
                            "total_pending_before_cap": total_pending_before_cap,
                            "rate_per_min": round(idx / elapsed * 60, 1),
                        }
                    ),
                    flush=True,
                )
    append_rows(out_csv, buffer)
    written += len(buffer)

    all_done = load_done(out_csv)
    manifest = {
        "source": "Polygon /v3/reference/tickers/{ticker}?date=YYYY-MM-DD",
        "pit_daily": str(pit_daily).replace("\\", "/"),
        "out_csv": str(out_csv).replace("\\", "/"),
        "start": args.start,
        "end": args.end,
        "frequency": args.frequency,
        "snapshot_dates": date_strings,
        "snapshot_count": len(date_strings),
        "workers": args.workers,
        "written_this_run": written,
        "done_rows_total": len(all_done),
        "pending_before_cap_this_run": total_pending_before_cap,
        "selected_this_run": len(tasks),
        "elapsed_sec": round(time.time() - started, 3),
        "opened_2025_2026_oos": bool(args.allow_oos and pd.Timestamp(args.end) > pd.Timestamp("2024-12-31")),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
