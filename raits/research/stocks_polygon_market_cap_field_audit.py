from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


BASE_URL = "https://api.polygon.io"
OUT_PREFIX = "STOCKS_POLYGON_MARKET_CAP_FIELD_AUDIT_2026-09-14"
OUT_DIR = Path("raits/data/cache/external_universes/market_cap_polygon")
CSV_OUT = OUT_DIR / f"{OUT_PREFIX}.csv"
SUMMARY_OUT = OUT_DIR / f"{OUT_PREFIX}_SUMMARY.json"

PIT_DAILY = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)

DATES = ["2018-01-02", "2020-01-02", "2022-01-03", "2024-12-31"]
TICKERS = [
    "AAPL",
    "MSFT",
    "AMZN",
    "NVDA",
    "TSLA",
    "META",
    "GOOGL",
    "JPM",
    "JNJ",
    "XOM",
    "MU",
    "ORCL",
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


def polygon_get(session: requests.Session, key: str, ticker: str, date: str) -> tuple[int, dict[str, Any]]:
    resp = session.get(
        f"{BASE_URL}/v3/reference/tickers/{ticker}",
        params={"date": date, "apiKey": key},
        timeout=60,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"status": "json_error", "message": resp.text[:300]}
    return resp.status_code, data


def load_pit_prices() -> pd.DataFrame:
    df = pd.read_parquet(PIT_DAILY, columns=["date", "ticker", "prior_close", "eligible_final"])
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["ticker"] = df["ticker"].astype(str).str.upper()
    return df.sort_values(["date", "ticker"]).drop_duplicates(["date", "ticker"], keep="first")


def to_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return np.nan
        return float(value)
    except Exception:
        return np.nan


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    key = load_polygon_key()
    pit = load_pit_prices()
    pit_lookup = pit.set_index(["date", "ticker"])

    rows: list[dict[str, Any]] = []
    with requests.Session() as session:
        for date in DATES:
            date_ts = pd.Timestamp(date)
            for ticker in TICKERS:
                status_code, payload = polygon_get(session, key, ticker, date)
                result = payload.get("results") or {}
                try:
                    pit_row = pit_lookup.loc[(date_ts, ticker)]
                except KeyError:
                    pit_row = None

                prior_close = to_float(pit_row["prior_close"]) if pit_row is not None else np.nan
                market_cap = to_float(result.get("market_cap"))
                weighted_shares = to_float(result.get("weighted_shares_outstanding"))
                share_class_shares = to_float(result.get("share_class_shares_outstanding"))
                cap_from_weighted = prior_close * weighted_shares if np.isfinite(prior_close * weighted_shares) else np.nan
                cap_from_share_class = (
                    prior_close * share_class_shares if np.isfinite(prior_close * share_class_shares) else np.nan
                )

                rows.append(
                    {
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
                        "market_cap": market_cap,
                        "weighted_shares_outstanding": weighted_shares,
                        "share_class_shares_outstanding": share_class_shares,
                        "pit_prior_close": prior_close,
                        "pit_eligible_final": bool(pit_row["eligible_final"]) if pit_row is not None else None,
                        "cap_from_weighted_shares": cap_from_weighted,
                        "cap_from_share_class_shares": cap_from_share_class,
                        "market_cap_to_weighted_implied": market_cap / cap_from_weighted
                        if cap_from_weighted and np.isfinite(cap_from_weighted)
                        else np.nan,
                        "market_cap_to_share_class_implied": market_cap / cap_from_share_class
                        if cap_from_share_class and np.isfinite(cap_from_share_class)
                        else np.nan,
                        "message": payload.get("message", ""),
                    }
                )
                time.sleep(0.12)

    out = pd.DataFrame(rows)
    out.to_csv(CSV_OUT, index=False)

    ok = out[out["status_code"].eq(200) & out["market_cap"].notna() & out["pit_prior_close"].notna()].copy()
    summary = {
        "rows": int(len(out)),
        "ok_rows": int(len(ok)),
        "dates": DATES,
        "tickers": TICKERS,
        "weighted_ratio_median": float(ok["market_cap_to_weighted_implied"].median()) if not ok.empty else None,
        "weighted_ratio_min": float(ok["market_cap_to_weighted_implied"].min()) if not ok.empty else None,
        "weighted_ratio_max": float(ok["market_cap_to_weighted_implied"].max()) if not ok.empty else None,
        "share_class_ratio_median": float(ok["market_cap_to_share_class_implied"].median()) if not ok.empty else None,
        "share_class_ratio_min": float(ok["market_cap_to_share_class_implied"].min()) if not ok.empty else None,
        "share_class_ratio_max": float(ok["market_cap_to_share_class_implied"].max()) if not ok.empty else None,
        "interpretation": (
            "Ratios near 1 imply Polygon historical market_cap/shares line up with local PIT prices; "
            "large date-dependent ratios imply field is not safe for point-in-time ranking."
        ),
    }
    SUMMARY_OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"WROTE {CSV_OUT}", flush=True)
    print(f"WROTE {SUMMARY_OUT}", flush=True)


if __name__ == "__main__":
    main()
