from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import requests


OUTPUT = Path("STOCKS_POLYGON_EQUITY_DATA_ENTITLEMENT_PROBE_2026-10-03.json")
PROBE_DATE = pd.Timestamp("2021-06-15")
MAX_ALLOWED_DATE = pd.Timestamp("2021-12-31")


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


def ns(clock: str) -> int:
    return int(pd.Timestamp(f"{PROBE_DATE.date()} {clock}", tz="America/New_York").tz_convert("UTC").value)


def specs() -> list[dict[str, Any]]:
    return [
        {"name": "historical_trades", "host": "https://api.polygon.io", "path": "/v3/trades/AAPL",
         "params": {"timestamp.gte": ns("09:30:00"), "timestamp.lt": ns("09:30:01"), "limit": 1, "sort": "timestamp"},
         "pit_use": "causal with sip_timestamp"},
        {"name": "historical_nbbo_quotes", "host": "https://api.polygon.io", "path": "/v3/quotes/AAPL",
         "params": {"timestamp.gte": ns("09:30:00"), "timestamp.lt": ns("09:30:01"), "limit": 1, "sort": "timestamp"},
         "pit_use": "causal with sip_timestamp"},
        {"name": "one_second_aggregates", "host": "https://api.polygon.io",
         "path": "/v2/aggs/ticker/AAPL/range/1/second/2021-06-15/2021-06-15",
         "params": {"adjusted": "false", "limit": 1, "sort": "asc"}, "pit_use": "bar-end causal only"},
        {"name": "news", "host": "https://api.polygon.io", "path": "/v2/reference/news",
         "params": {"ticker": "AAPL", "published_utc.gte": "2021-06-15T00:00:00Z",
                    "published_utc.lt": "2021-06-16T00:00:00Z", "limit": 1, "sort": "published_utc"},
         "pit_use": "causal with published_utc"},
        {"name": "quarterly_financials", "host": "https://api.polygon.io", "path": "/vX/reference/financials",
         "params": {"ticker": "AAPL", "filing_date.gte": "2021-01-01", "filing_date.lte": "2021-12-31",
                    "timeframe": "quarterly", "limit": 1, "sort": "filing_date"},
         "pit_use": "daily PIT by filing_date; no intraday release time"},
        {"name": "dividends", "host": "https://api.massive.com", "path": "/stocks/v1/dividends",
         "params": {"ticker": "AAPL", "ex_dividend_date.gte": "2021-01-01",
                    "ex_dividend_date.lte": "2021-12-31", "limit": 1, "sort": "ex_dividend_date.asc"},
         "pit_use": "ex-date known; declaration_date required for predictive use"},
        {"name": "splits", "host": "https://api.massive.com", "path": "/stocks/v1/splits",
         "params": {"ticker": "AAPL", "execution_date.gte": "2018-01-01",
                    "execution_date.lte": "2021-12-31", "limit": 1, "sort": "execution_date.asc"},
         "pit_use": "execution adjustment; not alpha by itself"},
        {"name": "short_interest", "host": "https://api.massive.com", "path": "/stocks/v1/short-interest",
         "params": {"ticker": "AAPL", "settlement_date.gte": "2021-01-01",
                    "settlement_date.lte": "2021-12-31", "limit": 1, "sort": "settlement_date.asc"},
         "pit_use": "must lag by dissemination/publication date"},
        {"name": "short_volume", "host": "https://api.massive.com", "path": "/stocks/v1/short-volume",
         "params": {"ticker": "AAPL", "date.gte": "2021-06-01", "date.lte": "2021-06-30",
                    "limit": 1, "sort": "date.asc"}, "pit_use": "usable no earlier than next session"},
        {"name": "edgar_index", "host": "https://api.massive.com", "path": "/stocks/filings/vX/index",
         "params": {"ticker": "AAPL", "filing_date.gte": "2021-01-01", "filing_date.lte": "2021-12-31",
                    "limit": 1, "sort": "filing_date.asc"}, "pit_use": "daily PIT by filing timestamp/date returned"},
        {"name": "benzinga_earnings", "host": "https://api.massive.com", "path": "/benzinga/v1/earnings",
         "params": {"ticker": "AAPL", "date.gte": "2021-01-01", "date.lte": "2021-12-31",
                    "limit": 1, "sort": "date.asc"},
         "pit_use": "diagnostic until revision history proves point-in-time"},
        {"name": "benzinga_guidance", "host": "https://api.massive.com", "path": "/benzinga/v1/guidance",
         "params": {"ticker": "AAPL", "date.gte": "2021-01-01", "date.lte": "2021-12-31",
                    "limit": 1, "sort": "date.asc"},
         "pit_use": "diagnostic until revision history proves point-in-time"},
        {"name": "trade_conditions", "host": "https://api.polygon.io", "path": "/v3/reference/conditions",
         "params": {"asset_class": "stocks", "data_type": "trade", "limit": 1},
         "pit_use": "static decode table"},
        {"name": "quote_conditions", "host": "https://api.polygon.io", "path": "/v3/reference/conditions",
         "params": {"asset_class": "stocks", "data_type": "quote", "limit": 1},
         "pit_use": "static decode table"},
        {"name": "exchanges", "host": "https://api.polygon.io", "path": "/v3/reference/exchanges",
         "params": {"asset_class": "stocks", "locale": "us"}, "pit_use": "static decode table"},
    ]


def probe(session: requests.Session, spec: dict[str, Any], key: str) -> dict[str, Any]:
    response = session.get(spec["host"] + spec["path"], params={**spec["params"], "apiKey": key}, timeout=90)
    body = response.text.replace(key, "REDACTED")
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    results = payload.get("results")
    count = len(results) if isinstance(results, list) else (1 if isinstance(results, dict) else 0)
    fields: list[str] = []
    if isinstance(results, list) and results and isinstance(results[0], dict):
        fields = sorted(results[0])
    elif isinstance(results, dict):
        fields = sorted(results)
    return {
        "name": spec["name"], "endpoint": spec["path"], "host": spec["host"],
        "httpStatus": response.status_code, "apiStatus": payload.get("status"), "resultCount": count,
        "accessible": response.status_code == 200, "sampleFields": fields,
        "pitUse": spec["pit_use"], "error": "" if response.status_code == 200 else body[:300],
    }


def main() -> None:
    if PROBE_DATE > MAX_ALLOWED_DATE:
        raise RuntimeError("Probe date crossed locked boundary")
    key = load_polygon_key()
    with requests.Session() as session:
        rows = [probe(session, spec, key) for spec in specs()]
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"),
        "scriptHash": sha256(Path(__file__)),
        "probeDate": str(PROBE_DATE.date()),
        "maxAllowedDate": str(MAX_ALLOWED_DATE.date()),
        "post2021Consumed": False,
        "scope": "equities only; bounded entitlement/schema probes, one result maximum per endpoint",
        "results": rows,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
