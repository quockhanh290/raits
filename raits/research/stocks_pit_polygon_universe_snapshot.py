from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


BASE_URL = "https://api.polygon.io"
OUT_DIR = Path("raits/data/cache/stocks_survivorship/polygon_universe_snapshot")
REPORT_PREFIX = "STOCKS_PIT_POLYGON_UNIVERSE_SNAPSHOT_20260912"
SNAPSHOT_DATES = ["2022-06-08", "2022-06-09", "2022-10-27", "2022-10-28"]
PAGE_LIMIT = 1000


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


def request_json(session: requests.Session, key: str, url_or_path: str, params: dict[str, str] | None = None) -> tuple[int, dict[str, Any], str]:
    params = dict(params or {})
    if url_or_path.startswith("http"):
        url = url_or_path
        if "apiKey=" not in url:
            params["apiKey"] = key
    else:
        url = f"{BASE_URL}{url_or_path}"
        params["apiKey"] = key
    resp = session.get(url, params=params, timeout=60)
    try:
        data = resp.json()
    except Exception:
        data = {"message": resp.text[:500]}
    safe_url = resp.url.replace(key, "REDACTED")
    return resp.status_code, data, safe_url


def fetch_snapshot_date(session: requests.Session, key: str, date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    path_or_url = "/v3/reference/tickers"
    params = {
        "date": date,
        "market": "stocks",
        "type": "CS",
        "active": "true",
        "limit": str(PAGE_LIMIT),
        "sort": "ticker",
        "order": "asc",
    }
    page = 0
    while True:
        page += 1
        status, data, safe_url = request_json(session, key, path_or_url, params)
        results = data.get("results") or []
        next_url = data.get("next_url") or ""
        pages.append(
            {
                "date": date,
                "page": page,
                "status_code": status,
                "api_status": data.get("status"),
                "result_count": len(results),
                "next_url_present": bool(next_url),
                "request_url": safe_url,
                "sample_first": results[0].get("ticker") if results else "",
                "sample_last": results[-1].get("ticker") if results else "",
                "message": data.get("message", ""),
            }
        )
        for item in results:
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "ticker": item.get("ticker", ""),
                    "name": item.get("name", ""),
                    "market": item.get("market", ""),
                    "locale": item.get("locale", ""),
                    "primary_exchange": item.get("primary_exchange", ""),
                    "type": item.get("type", ""),
                    "active": item.get("active"),
                    "currency_name": item.get("currency_name", ""),
                    "cik": item.get("cik", ""),
                    "composite_figi": item.get("composite_figi", ""),
                    "share_class_figi": item.get("share_class_figi", ""),
                    "last_updated_utc": item.get("last_updated_utc", ""),
                }
            )
        if status >= 400 or not next_url:
            break
        path_or_url = next_url
        params = {}
        time.sleep(0.15)
    return pd.DataFrame(rows), pd.DataFrame(pages)


def duplicate_share_class_figi(universe: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for date, group in universe.groupby("date"):
        x = group[group["share_class_figi"].astype(str).ne("") & group["share_class_figi"].notna()].copy()
        dup = x[x["share_class_figi"].duplicated(keep=False)].copy()
        if not dup.empty:
            dup["date"] = pd.Timestamp(date)
            frames.append(dup.sort_values(["share_class_figi", "ticker"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=universe.columns)


def qa(universe: pd.DataFrame, pages: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    duplicate_figi_rows = duplicate_share_class_figi(universe)
    daily_counts = universe.groupby("date", as_index=False).agg(
        rows=("ticker", "count"),
        tickers=("ticker", "nunique"),
        share_class_figi_present=("share_class_figi", lambda s: int(s.astype(str).ne("").sum())),
        composite_figi_present=("composite_figi", lambda s: int(s.astype(str).ne("").sum())),
    )
    for date, group in universe.groupby("date"):
        dup_ticker = group[group["ticker"].duplicated(keep=False)]
        dup_share_figi = duplicate_figi_rows[duplicate_figi_rows["date"].eq(pd.Timestamp(date))]
        rows.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "check": "ticker_unique_within_date",
                "status": "PASS" if dup_ticker.empty else "FAIL",
                "detail": str(len(dup_ticker)),
            }
        )
        rows.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "check": "share_class_figi_unique_within_date",
                "status": "PASS" if dup_share_figi.empty else "FAIL",
                "detail": f"rows={len(dup_share_figi)} groups={dup_share_figi['share_class_figi'].nunique() if not dup_share_figi.empty else 0}",
            }
        )
        rows.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "check": "all_rows_common_stock_active",
                "status": "PASS" if group["type"].eq("CS").all() and group["active"].astype(bool).all() else "FAIL",
                "detail": "",
            }
        )
        rows.append(
            {
                "date": pd.Timestamp(date).date().isoformat(),
                "check": "pagination_completed",
                "status": "PASS" if not pages[pages["date"].eq(pd.Timestamp(date).date().isoformat())].empty and not bool(pages[pages["date"].eq(pd.Timestamp(date).date().isoformat())].iloc[-1]["next_url_present"]) else "FAIL",
                "detail": f"pages={int(pages[pages['date'].eq(pd.Timestamp(date).date().isoformat())]['page'].max())}",
            }
        )
    return pd.DataFrame(rows), daily_counts, duplicate_figi_rows


def write_manifest(paths: dict[str, str], pages: pd.DataFrame) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
        "source": "Polygon /v3/reference/tickers",
        "purpose": "paginated active common-stock snapshot sample",
        "dates": SNAPSHOT_DATES,
        "page_limit": PAGE_LIMIT,
        "bulk_fetch": False,
        "opened_2025_2026_oos": False,
        "total_pages": int(len(pages)),
        "paths": paths,
    }
    (OUT_DIR / "manifest_20260912.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    key = load_polygon_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    universe_frames = []
    page_frames = []
    for date in SNAPSHOT_DATES:
        universe, pages = fetch_snapshot_date(session, key, date)
        universe_frames.append(universe)
        page_frames.append(pages)
        print(date, "rows", len(universe), "pages", len(pages), flush=True)
    universe_all = pd.concat(universe_frames, ignore_index=True)
    pages_all = pd.concat(page_frames, ignore_index=True)
    qa_summary, daily_counts, duplicate_figi_rows = qa(universe_all, pages_all)

    paths = {
        "universe_snapshot": str((OUT_DIR / "universe_snapshot.parquet")).replace("\\", "/"),
        "page_manifest": str((OUT_DIR / "page_manifest.parquet")).replace("\\", "/"),
    }
    universe_all.to_parquet(OUT_DIR / "universe_snapshot.parquet", index=False)
    pages_all.to_parquet(OUT_DIR / "page_manifest.parquet", index=False)
    universe_all.to_csv(f"{REPORT_PREFIX}_ROWS.csv", index=False)
    pages_all.to_csv(f"{REPORT_PREFIX}_PAGES.csv", index=False)
    duplicate_figi_rows.to_csv(f"{REPORT_PREFIX}_DUPLICATE_SHARE_CLASS_FIGI.csv", index=False)
    qa_summary.to_csv(f"{REPORT_PREFIX}_QA_SUMMARY.csv", index=False)
    daily_counts.to_csv(f"{REPORT_PREFIX}_DAILY_COUNTS.csv", index=False)
    write_manifest(paths, pages_all)

    print(qa_summary.to_string(index=False))
    print("WROTE", OUT_DIR)


if __name__ == "__main__":
    main()
