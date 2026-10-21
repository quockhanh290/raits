from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

import pandas as pd
import requests


START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2021-12-31")
OUT_DIR = Path("raits/data/cache/stocks_pit_1520_continuation_2018_2022")
OUTPUT = OUT_DIR / "spy_1520_open_2018_2021.parquet"
MANIFEST = OUT_DIR / "spy_1520_open_2018_2021_manifest.json"
BASE_URL = "https://api.polygon.io"


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


def fetch_range(start: pd.Timestamp, end: pd.Timestamp, key: str) -> pd.DataFrame:
    url = f"{BASE_URL}/v2/aggs/ticker/SPY/range/5/minute/{start.date()}/{end.date()}"
    params = {"adjusted": "false", "sort": "asc", "limit": 50000, "apiKey": key}
    last_error = ""
    for attempt in range(1, 6):
        try:
            response = requests.get(url, params=params, timeout=90)
            if response.status_code == 429:
                time.sleep(5.0 * attempt)
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text.replace(key, 'REDACTED')[:300]}")
            payload = response.json()
            rows = payload.get("results") or []
            frame = pd.DataFrame(rows)
            if frame.empty or not {"t", "o"}.issubset(frame.columns):
                raise RuntimeError(f"No aggregate rows for {start.date()} through {end.date()}")
            return frame
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc).replace(key, 'REDACTED')[:400]}"
            if attempt < 5:
                time.sleep(2.0 * attempt)
    raise RuntimeError(last_error)


def main() -> None:
    key = load_polygon_key()
    month_starts = pd.date_range(START.replace(day=1), END, freq="MS")
    ranges = [(max(START, month), min(END, month + pd.offsets.MonthEnd(0))) for month in month_starts]
    frames = [fetch_range(start, end, key) for start, end in ranges]
    raw = pd.concat(frames, ignore_index=True).drop_duplicates("t", keep="last")
    timestamp = pd.to_datetime(raw["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    output = pd.DataFrame({
        "date": timestamp.dt.tz_localize(None).dt.normalize(),
        "clock": timestamp.dt.strftime("%H:%M"),
        "open": pd.to_numeric(raw["o"], errors="coerce"),
        "polygon_timestamp_ms": raw["t"].astype("int64"),
    })
    output = output[
        output["date"].between(START, END) & output["clock"].eq("15:20") & output["open"].gt(0)
    ].drop_duplicates("date", keep="last").sort_values("date")
    if output.empty or output["date"].min() != START or output["date"].max() != END:
        raise RuntimeError("SPY benchmark boundary failure")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output.to_parquet(OUTPUT, index=False)
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"),
        "scriptHash": sha256(Path(__file__)),
        "ticker": "SPY",
        "polygonEndpoint": "/v2/aggs/ticker/SPY/range/5/minute/{from}/{to}",
        "adjusted": False,
        "clock": "15:20 America/New_York five-minute aggregate open",
        "dateRange": [str(output["date"].min().date()), str(output["date"].max().date())],
        "rows": len(output),
        "output": str(OUTPUT).replace("\\", "/"),
        "outputHash": sha256(OUTPUT),
        "post2021Consumed": False,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
