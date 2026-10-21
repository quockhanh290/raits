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
OUT_PREFIX = "STOCKS_PIT_SOURCE_PROBE_POLYGON_20260912"
OUT_DIR = Path("raits/data/cache/stocks_survivorship/source_probe_polygon")


DETAIL_CASES = [
    ("stable_survivor", "AAPL", "2022-06-08"),
    ("rename_before", "FB", "2022-06-08"),
    ("rename_after", "META", "2022-06-09"),
    ("delist_last_active", "TWTR", "2022-10-27"),
    ("delist_after", "TWTR", "2022-10-28"),
    ("split_name", "NVDA", "2024-06-10"),
    ("share_class_a", "GOOGL", "2022-07-18"),
    ("share_class_c", "GOOG", "2022-07-18"),
]

REFERENCE_SEARCHES = [
    ("TWTR_active_false", {"ticker": "TWTR", "active": "false", "limit": "10"}),
    ("TWTR_search", {"search": "TWTR", "active": "false", "limit": "10"}),
    ("FB_active_false", {"ticker": "FB", "active": "false", "limit": "10"}),
    ("META_active_true", {"ticker": "META", "active": "true", "limit": "10"}),
    ("GOOG_search", {"search": "GOOG", "active": "true", "limit": "10"}),
]

SPLIT_CASES = [
    ("NVDA_2021_split", "NVDA", "2021-07-01", "2021-07-31"),
    ("NVDA_2024_split", "NVDA", "2024-06-01", "2024-06-30"),
    ("GOOGL_2022_split", "GOOGL", "2022-07-01", "2022-07-31"),
    ("GOOG_2022_split", "GOOG", "2022-07-01", "2022-07-31"),
]

AGG_CASES = [
    ("TWTR_delist_window", "TWTR", "2022-10-24", "2022-11-04"),
    ("FB_rename_before", "FB", "2022-06-06", "2022-06-10"),
    ("META_rename_after", "META", "2022-06-06", "2022-06-13"),
]

UNIVERSE_PAGE_CASES = [
    ("active_common_2022_06_08", {"date": "2022-06-08", "market": "stocks", "type": "CS", "active": "true", "limit": "1000"}),
    ("active_common_2022_10_27", {"date": "2022-10-27", "market": "stocks", "type": "CS", "active": "true", "limit": "1000"}),
    ("inactive_common_page", {"market": "stocks", "type": "CS", "active": "false", "limit": "1000"}),
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
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        key = str(getattr(mod, "POLYGON_API_KEY", "")).strip()
        if key:
            return key
    raise SystemExit("POLYGON_API_KEY not found")


def redact(value: str, key: str) -> str:
    return value.replace(key, "REDACTED") if key else value


def get_json(session: requests.Session, key: str, path: str, params: dict[str, str]) -> tuple[int, dict[str, Any]]:
    query = dict(params)
    query["apiKey"] = key
    url = f"{BASE_URL}{path}"
    resp = session.get(url, params=query, timeout=60)
    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": redact(resp.text[:500], key)}
    return resp.status_code, data


def flat_details(label: str, ticker: str, date: str, status_code: int, data: dict[str, Any]) -> dict[str, Any]:
    result = data.get("results") or {}
    branding = result.get("branding") or {}
    return {
        "label": label,
        "ticker_query": ticker,
        "date_query": date,
        "status_code": status_code,
        "api_status": data.get("status"),
        "request_id": data.get("request_id"),
        "ticker": result.get("ticker"),
        "name": result.get("name"),
        "market": result.get("market"),
        "locale": result.get("locale"),
        "primary_exchange": result.get("primary_exchange"),
        "type": result.get("type"),
        "active": result.get("active"),
        "currency_name": result.get("currency_name"),
        "cik": result.get("cik"),
        "composite_figi": result.get("composite_figi"),
        "share_class_figi": result.get("share_class_figi"),
        "homepage_url": result.get("homepage_url"),
        "logo_url_present": bool(branding.get("logo_url")),
        "list_date": result.get("list_date"),
        "delisted_utc": result.get("delisted_utc"),
        "sic_code": result.get("sic_code"),
        "sic_description": result.get("sic_description"),
        "raw_keys": ",".join(sorted(result.keys())) if isinstance(result, dict) else "",
        "message": data.get("message", ""),
    }


def probe_details(session: requests.Session, key: str) -> pd.DataFrame:
    rows = []
    for label, ticker, date in DETAIL_CASES:
        status, data = get_json(session, key, f"/v3/reference/tickers/{ticker}", {"date": date})
        rows.append(flat_details(label, ticker, date, status, data))
        time.sleep(0.15)
    return pd.DataFrame(rows)


def probe_reference_search(session: requests.Session, key: str) -> pd.DataFrame:
    rows = []
    for label, params in REFERENCE_SEARCHES:
        status, data = get_json(session, key, "/v3/reference/tickers", params)
        results = data.get("results") or []
        rows.append(
            {
                "label": label,
                "status_code": status,
                "api_status": data.get("status"),
                "result_count": len(results),
                "tickers": ",".join(str(x.get("ticker", "")) for x in results[:10]),
                "names": " | ".join(str(x.get("name", "")) for x in results[:5]),
                "types": ",".join(str(x.get("type", "")) for x in results[:10]),
                "active_values": ",".join(str(x.get("active", "")) for x in results[:10]),
                "raw_keys_first": ",".join(sorted(results[0].keys())) if results else "",
                "message": data.get("message", ""),
            }
        )
        time.sleep(0.15)
    return pd.DataFrame(rows)


def probe_splits(session: requests.Session, key: str) -> pd.DataFrame:
    rows = []
    for label, ticker, start, end in SPLIT_CASES:
        status, data = get_json(
            session,
            key,
            "/v3/reference/splits",
            {"ticker": ticker, "execution_date.gte": start, "execution_date.lte": end, "limit": "10"},
        )
        results = data.get("results") or []
        if not results:
            rows.append(
                {
                    "label": label,
                    "ticker": ticker,
                    "status_code": status,
                    "api_status": data.get("status"),
                    "result_count": 0,
                    "execution_date": "",
                    "split_from": None,
                    "split_to": None,
                    "message": data.get("message", ""),
                }
            )
        for item in results:
            rows.append(
                {
                    "label": label,
                    "ticker": ticker,
                    "status_code": status,
                    "api_status": data.get("status"),
                    "result_count": len(results),
                    "execution_date": item.get("execution_date"),
                    "split_from": item.get("split_from"),
                    "split_to": item.get("split_to"),
                    "message": data.get("message", ""),
                }
            )
        time.sleep(0.15)
    return pd.DataFrame(rows)


def probe_aggs(session: requests.Session, key: str) -> pd.DataFrame:
    rows = []
    for label, ticker, start, end in AGG_CASES:
        status, data = get_json(
            session,
            key,
            f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
            {"adjusted": "true", "sort": "asc", "limit": "5000"},
        )
        results = data.get("results") or []
        dates = []
        closes = []
        for item in results:
            if "t" in item:
                dates.append(pd.to_datetime(item["t"], unit="ms", utc=True).date().isoformat())
                closes.append(item.get("c"))
        rows.append(
            {
                "label": label,
                "ticker": ticker,
                "start": start,
                "end": end,
                "status_code": status,
                "api_status": data.get("status"),
                "result_count": len(results),
                "first_date": dates[0] if dates else "",
                "last_date": dates[-1] if dates else "",
                "dates": ",".join(dates),
                "first_close": closes[0] if closes else None,
                "last_close": closes[-1] if closes else None,
                "message": data.get("message", ""),
            }
        )
        time.sleep(0.15)
    return pd.DataFrame(rows)


def probe_universe_pages(session: requests.Session, key: str) -> pd.DataFrame:
    rows = []
    for label, params in UNIVERSE_PAGE_CASES:
        status, data = get_json(session, key, "/v3/reference/tickers", params)
        results = data.get("results") or []
        tickers = [str(x.get("ticker", "")) for x in results]
        rows.append(
            {
                "label": label,
                "status_code": status,
                "api_status": data.get("status"),
                "first_page_count": len(results),
                "next_url_present": bool(data.get("next_url")),
                "sample_tickers": ",".join(tickers[:20]),
                "twtr_present": "TWTR" in set(tickers),
                "fb_present": "FB" in set(tickers),
                "meta_present": "META" in set(tickers),
                "message": data.get("message", ""),
            }
        )
        time.sleep(0.15)
    return pd.DataFrame(rows)


def evaluate(details: pd.DataFrame, searches: pd.DataFrame, splits: pd.DataFrame, aggs: pd.DataFrame, universe_pages: pd.DataFrame) -> pd.DataFrame:
    rows = []
    has_figi = details["composite_figi"].notna().any() or details["share_class_figi"].notna().any()
    rows.append(
        {
            "capability": "stable_security_identifier",
            "status": "PARTIAL" if has_figi else "FAIL",
            "evidence": "ticker details expose composite_figi/share_class_figi for listed names; need delisted coverage audit",
        }
    )
    fb = details[(details["ticker_query"].eq("FB")) & (details["date_query"].eq("2022-06-08"))]
    meta = details[(details["ticker_query"].eq("META")) & (details["date_query"].eq("2022-06-09"))]
    rows.append(
        {
            "capability": "ticker_rename_point_in_time_details",
            "status": "PASS" if not fb.empty and not meta.empty and fb.iloc[0]["status_code"] == 200 and meta.iloc[0]["status_code"] == 200 else "WARN",
            "evidence": "FB/META date-specific details queried",
        }
    )
    twtr_inactive = searches[searches["label"].eq("TWTR_active_false")]
    rows.append(
        {
            "capability": "delisted_ticker_reference",
            "status": "PASS" if not twtr_inactive.empty and int(twtr_inactive.iloc[0]["result_count"]) > 0 else "WARN",
            "evidence": "TWTR active=false reference search result count",
        }
    )
    split_hits = splits[splits["result_count"].fillna(0).astype(int) > 0]
    rows.append(
        {
            "capability": "split_reference",
            "status": "PASS" if not split_hits.empty else "FAIL",
            "evidence": "reference splits endpoint queried for NVDA and GOOG/GOOGL",
        }
    )
    twtr_aggs = aggs[aggs["label"].eq("TWTR_delist_window")]
    rows.append(
        {
            "capability": "delisted_market_data_smoke",
            "status": "PASS" if not twtr_aggs.empty and int(twtr_aggs.iloc[0]["result_count"]) > 0 else "WARN",
            "evidence": "TWTR adjusted daily aggs around delist window queried",
        }
    )
    rows.append(
        {
            "capability": "production_pit_sufficiency",
            "status": "WARN",
            "evidence": "Polygon probe can support pieces, but full pagination, delisted identity, and durable security_id policy still need source-level validation",
        }
    )
    active_pages = universe_pages[universe_pages["label"].str.startswith("active_common")]
    rows.append(
        {
            "capability": "active_common_universe_page",
            "status": "PASS" if not active_pages.empty and active_pages["next_url_present"].any() else "WARN",
            "evidence": "reference tickers endpoint returns paginated active common-stock pages by date",
        }
    )
    return pd.DataFrame(rows)


def write_manifest(paths: dict[str, str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
        "source": "Polygon REST API",
        "purpose": "small survivorship-aware source capability probe",
        "bulk_fetch": False,
        "opened_2025_2026_oos": False,
        "paths": paths,
    }
    (OUT_DIR / "manifest_20260912.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    key = load_polygon_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    details = probe_details(session, key)
    searches = probe_reference_search(session, key)
    splits = probe_splits(session, key)
    aggs = probe_aggs(session, key)
    universe_pages = probe_universe_pages(session, key)
    summary = evaluate(details, searches, splits, aggs, universe_pages)

    files = {
        "summary": f"{OUT_PREFIX}_SUMMARY.csv",
        "DETAILS": f"{OUT_PREFIX}_DETAILS.csv",
        "REFERENCE_SEARCH": f"{OUT_PREFIX}_REFERENCE_SEARCH.csv",
        "SPLITS": f"{OUT_PREFIX}_SPLITS.csv",
        "AGGS": f"{OUT_PREFIX}_AGGS.csv",
        "UNIVERSE_PAGES": f"{OUT_PREFIX}_UNIVERSE_PAGES.csv",
    }
    summary.to_csv(files["summary"], index=False)
    details.to_csv(files["DETAILS"], index=False)
    searches.to_csv(files["REFERENCE_SEARCH"], index=False)
    splits.to_csv(files["SPLITS"], index=False)
    aggs.to_csv(files["AGGS"], index=False)
    universe_pages.to_csv(files["UNIVERSE_PAGES"], index=False)
    write_manifest(files)

    print(summary.to_string(index=False))
    print("WROTE", ", ".join(files.values()))


if __name__ == "__main__":
    main()
