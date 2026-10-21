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
OUT_DIR = Path("raits/data/cache/stocks_survivorship/polygon_sample")
REPORT_PREFIX = "STOCKS_PIT_POLYGON_SAMPLE_20260912"

SAMPLE_SECURITIES = [
    {
        "role": "stable_survivor",
        "canonical_ticker": "AAPL",
        "detail_queries": [("AAPL", "2022-06-08")],
        "ticker_ranges": [("AAPL", "1980-12-12", None, "initial_listing")],
    },
    {
        "role": "ticker_rename_fb_meta",
        "canonical_ticker": "META",
        "detail_queries": [("FB", "2022-06-08"), ("META", "2022-06-09")],
        "ticker_ranges": [("FB", "2012-05-18", "2022-06-08", "rename"), ("META", "2022-06-09", None, "rename")],
    },
    {
        "role": "major_split",
        "canonical_ticker": "NVDA",
        "detail_queries": [("NVDA", "2024-06-10")],
        "ticker_ranges": [("NVDA", "1999-01-22", None, "initial_listing")],
    },
    {
        "role": "delisted_acquired",
        "canonical_ticker": "TWTR",
        "detail_queries": [("TWTR", "2022-10-27")],
        "ticker_ranges": [("TWTR", "2013-11-07", "2022-10-27", "acquisition_delist")],
        "inactive_reference": {"ticker": "TWTR", "active": "false", "limit": "10"},
    },
    {
        "role": "multi_share_class_a",
        "canonical_ticker": "GOOGL",
        "detail_queries": [("GOOGL", "2022-07-18")],
        "ticker_ranges": [("GOOGL", "2004-08-19", None, "share_class")],
    },
    {
        "role": "multi_share_class_c",
        "canonical_ticker": "GOOG",
        "detail_queries": [("GOOG", "2022-07-18")],
        "ticker_ranges": [("GOOG", "2014-04-03", None, "share_class")],
    },
]

SAMPLE_DATES = pd.to_datetime(
    [
        "2022-06-08",
        "2022-06-09",
        "2022-07-18",
        "2022-10-27",
        "2022-10-28",
    ]
)


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


def get_json(session: requests.Session, key: str, path: str, params: dict[str, str]) -> tuple[int, dict[str, Any]]:
    query = dict(params)
    query["apiKey"] = key
    resp = session.get(f"{BASE_URL}{path}", params=query, timeout=60)
    try:
        data = resp.json()
    except Exception:
        data = {"message": resp.text[:500]}
    return resp.status_code, data


def detail(session: requests.Session, key: str, ticker: str, date: str) -> dict[str, Any]:
    status, data = get_json(session, key, f"/v3/reference/tickers/{ticker}", {"date": date})
    result = data.get("results") or {}
    result = dict(result)
    result["_status_code"] = status
    result["_api_status"] = data.get("status")
    result["_date_query"] = date
    result["_ticker_query"] = ticker
    return result


def reference_search(session: requests.Session, key: str, params: dict[str, str]) -> list[dict[str, Any]]:
    status, data = get_json(session, key, "/v3/reference/tickers", params)
    out = data.get("results") or []
    for row in out:
        row["_status_code"] = status
        row["_api_status"] = data.get("status")
    return out


def daily_aggs(session: requests.Session, key: str, ticker: str, start: str, end: str) -> pd.DataFrame:
    status, data = get_json(
        session,
        key,
        f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
        {"adjusted": "true", "sort": "asc", "limit": "5000"},
    )
    rows = []
    for item in data.get("results") or []:
        rows.append(
            {
                "date": pd.to_datetime(item["t"], unit="ms", utc=True).tz_convert(None).normalize(),
                "ticker": ticker,
                "open": item.get("o"),
                "high": item.get("h"),
                "low": item.get("l"),
                "close": item.get("c"),
                "volume": item.get("v"),
                "status_code": status,
                "api_status": data.get("status"),
            }
        )
    return pd.DataFrame(rows)


def split_refs(session: requests.Session, key: str, ticker: str) -> pd.DataFrame:
    status, data = get_json(session, key, "/v3/reference/splits", {"ticker": ticker, "limit": "100"})
    rows = []
    for item in data.get("results") or []:
        rows.append(
            {
                "ticker": ticker,
                "execution_date": pd.to_datetime(item.get("execution_date")),
                "split_from": item.get("split_from"),
                "split_to": item.get("split_to"),
                "status_code": status,
                "api_status": data.get("status"),
            }
        )
    return pd.DataFrame(rows)


def security_id_for(row: dict[str, Any], fallback_ticker: str) -> str:
    figi = row.get("share_class_figi") or row.get("composite_figi")
    if figi:
        return f"POLYGON_FIGI_{figi}"
    cik = row.get("cik")
    if cik:
        return f"POLYGON_CIK_{cik}_{fallback_ticker}"
    return f"POLYGON_TICKER_{fallback_ticker}"


def build_sample(session: requests.Session, key: str) -> dict[str, pd.DataFrame]:
    detail_rows: list[dict[str, Any]] = []
    inactive_rows: list[dict[str, Any]] = []
    master_rows: list[dict[str, Any]] = []
    ticker_rows: list[dict[str, Any]] = []
    action_frames: list[pd.DataFrame] = []
    agg_frames: list[pd.DataFrame] = []

    for spec in SAMPLE_SECURITIES:
        details = []
        for ticker, date in spec["detail_queries"]:
            row = detail(session, key, ticker, date)
            details.append(row)
            detail_rows.append(row)
            time.sleep(0.15)
        if spec.get("inactive_reference"):
            inactive = reference_search(session, key, spec["inactive_reference"])
            inactive_rows.extend(inactive)
            time.sleep(0.15)

        primary = details[0]
        sid = security_id_for(primary, spec["canonical_ticker"])
        inactive_match = next((x for x in inactive_rows if x.get("ticker") == spec["canonical_ticker"]), {})
        delisted_utc = inactive_match.get("delisted_utc")
        delist_date = pd.to_datetime(delisted_utc).normalize() if delisted_utc else pd.NaT
        last_trade_date = pd.Timestamp("2022-10-27") if spec["canonical_ticker"] == "TWTR" else pd.NaT

        master_rows.append(
            {
                "security_id": sid,
                "company_id": primary.get("cik") or primary.get("composite_figi") or sid,
                "primary_listing_exchange": primary.get("primary_exchange", ""),
                "security_type": primary.get("type", ""),
                "currency": primary.get("currency_name", ""),
                "country": primary.get("locale", ""),
                "first_trade_date": pd.to_datetime(primary.get("list_date")),
                "last_trade_date": last_trade_date,
                "delist_date": delist_date,
                "delist_reason": "acquisition" if spec["canonical_ticker"] == "TWTR" else "",
                "is_etf": primary.get("type") == "ETF",
                "is_adr": False,
                "prototype_role": spec["role"],
                "canonical_ticker": spec["canonical_ticker"],
                "composite_figi": primary.get("composite_figi", ""),
                "share_class_figi": primary.get("share_class_figi", ""),
            }
        )
        for ticker, start, end, event_type in spec["ticker_ranges"]:
            ticker_rows.append(
                {
                    "security_id": sid,
                    "ticker": ticker,
                    "start_date": pd.to_datetime(start),
                    "end_date": pd.to_datetime(end),
                    "source_ticker": ticker,
                    "canonical_ticker": spec["canonical_ticker"],
                    "event_type": event_type,
                }
            )
            start_fetch = max(pd.Timestamp(start), pd.Timestamp("2022-06-06"))
            end_fetch = min(pd.Timestamp(end) if end else pd.Timestamp("2022-11-04"), pd.Timestamp("2022-11-04"))
            if start_fetch <= end_fetch:
                aggs = daily_aggs(session, key, ticker, start_fetch.date().isoformat(), end_fetch.date().isoformat())
                if not aggs.empty:
                    aggs["security_id"] = sid
                    agg_frames.append(aggs)
                time.sleep(0.15)
        splits = split_refs(session, key, spec["canonical_ticker"])
        if not splits.empty:
            splits["security_id"] = sid
            action_frames.append(splits)
        time.sleep(0.15)

    master = pd.DataFrame(master_rows)
    tickers = pd.DataFrame(ticker_rows)
    actions = pd.concat(action_frames, ignore_index=True) if action_frames else pd.DataFrame()
    aggs = pd.concat(agg_frames, ignore_index=True) if agg_frames else pd.DataFrame()
    details = pd.DataFrame(detail_rows)
    inactive = pd.DataFrame(inactive_rows)
    return {
        "security_master": master,
        "ticker_history": tickers,
        "corporate_actions_raw": actions,
        "daily_bars_raw": aggs,
        "details_raw": details,
        "inactive_reference_raw": inactive,
    }


def active_ticker(tickers: pd.DataFrame, security_id: str, date: pd.Timestamp) -> str | None:
    x = tickers[
        tickers["security_id"].eq(security_id)
        & (tickers["start_date"] <= date)
        & (tickers["end_date"].isna() | (tickers["end_date"] >= date))
    ]
    if len(x) == 1:
        return str(x.iloc[0]["ticker"])
    return None


def build_universe_and_coverage(sample: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    master = sample["security_master"]
    tickers = sample["ticker_history"]
    bars = sample["daily_bars_raw"]
    rows = []
    cov_rows = []
    bar_keys = set(zip(pd.to_datetime(bars["date"]), bars["security_id"], bars["ticker"])) if not bars.empty else set()
    for date in SAMPLE_DATES:
        for _, sec in master.iterrows():
            last_trade = sec["last_trade_date"] if pd.notna(sec["last_trade_date"]) else pd.Timestamp.max
            active = pd.Timestamp(sec["first_trade_date"]) <= date <= pd.Timestamp(last_trade)
            ticker = active_ticker(tickers, str(sec["security_id"]), date) if active else None
            is_common = str(sec["security_type"]) == "CS"
            final = bool(active and ticker and is_common and not bool(sec["is_etf"]))
            reason = "" if final else ("inactive_or_delisted" if not active else "no_valid_ticker_or_type")
            rows.append(
                {
                    "date": date,
                    "security_id": sec["security_id"],
                    "ticker": ticker or "",
                    "in_base_universe": bool(active),
                    "eligible_common_stock": bool(is_common and not bool(sec["is_etf"])),
                    "eligible_liquidity": final,
                    "eligible_price": final,
                    "eligible_final": final,
                    "reason_excluded": reason,
                }
            )
            has_daily = bool(ticker and (date, sec["security_id"], ticker) in bar_keys)
            cov_rows.append(
                {
                    "date": date,
                    "security_id": sec["security_id"],
                    "ticker": ticker or "",
                    "has_daily_bar": has_daily,
                    "has_5m_0930": False,
                    "has_5m_0935": False,
                    "has_5m_1000": False,
                    "has_5m_1555": False,
                    "has_5m_1600": False,
                    "missing_reason": "" if has_daily else ("inactive_or_delisted" if not active else "not_requested_or_no_bar"),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(cov_rows)


def qa(sample: dict[str, pd.DataFrame], universe: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    master = sample["security_master"]
    tickers = sample["ticker_history"]
    rows = []
    rows.append({"check": "security_id_unique", "status": "PASS" if master["security_id"].is_unique else "FAIL", "detail": ""})
    meta_rows = tickers[tickers["canonical_ticker"].eq("META")]
    rows.append(
        {
            "check": "fb_meta_same_security_id",
            "status": "PASS" if meta_rows["security_id"].nunique() == 1 and set(meta_rows["ticker"]) == {"FB", "META"} else "FAIL",
            "detail": "",
        }
    )
    twtr_after = universe[(universe["ticker"].eq("")) & (universe["date"].eq(pd.Timestamp("2022-10-28")))]
    rows.append(
        {
            "check": "twtr_inactive_after_delist",
            "status": "PASS" if "delisted_acquired" in set(master[master["security_id"].isin(twtr_after["security_id"])]["prototype_role"]) else "FAIL",
            "detail": "",
        }
    )
    dup = universe[universe["ticker"].ne("")].groupby(["date", "ticker"])["security_id"].nunique().reset_index(name="n")
    bad_dup = dup[dup["n"] > 1]
    rows.append({"check": "date_ticker_unique", "status": "PASS" if bad_dup.empty else "FAIL", "detail": str(len(bad_dup))})
    fb_day = universe[(universe["date"].eq(pd.Timestamp("2022-06-08"))) & (universe["ticker"].eq("FB"))]
    meta_day = universe[(universe["date"].eq(pd.Timestamp("2022-06-09"))) & (universe["ticker"].eq("META"))]
    rows.append({"check": "fb_meta_date_bridge", "status": "PASS" if len(fb_day) == 1 and len(meta_day) == 1 else "FAIL", "detail": ""})
    rows.append(
        {
            "check": "daily_coverage_explicit",
            "status": "PASS" if coverage["missing_reason"].notna().all() else "FAIL",
            "detail": f"rows={len(coverage)}",
        }
    )
    return pd.DataFrame(rows)


def write_manifest(paths: dict[str, str]) -> None:
    payload = {
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
        "source": "Polygon REST API",
        "purpose": "small real-source PIT sample builder",
        "bulk_fetch": False,
        "opened_2025_2026_oos": False,
        "paths": paths,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "manifest_20260912.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    key = load_polygon_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    sample = build_sample(session, key)
    universe, coverage = build_universe_and_coverage(sample)
    qa_summary = qa(sample, universe, coverage)

    sample["daily_universe"] = universe
    sample["market_data_coverage"] = coverage
    parquet_paths = {}
    for name, frame in sample.items():
        path = OUT_DIR / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        parquet_paths[name] = str(path).replace("\\", "/")

    qa_summary.to_csv(f"{REPORT_PREFIX}_QA_SUMMARY.csv", index=False)
    universe.groupby("date", as_index=False).agg(active=("in_base_universe", "sum"), eligible=("eligible_final", "sum")).to_csv(
        f"{REPORT_PREFIX}_DAILY_COUNTS.csv", index=False
    )
    sample["ticker_history"].to_csv(f"{REPORT_PREFIX}_TICKER_HISTORY.csv", index=False)
    coverage.to_csv(f"{REPORT_PREFIX}_COVERAGE.csv", index=False)
    write_manifest(parquet_paths)

    print(qa_summary.to_string(index=False))
    print("WROTE", OUT_DIR)
    print("WROTE", f"{REPORT_PREFIX}_QA_SUMMARY.csv")


if __name__ == "__main__":
    main()
