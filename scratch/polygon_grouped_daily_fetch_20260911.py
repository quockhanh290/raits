"""Whole-market US stock daily bars from Polygon, 2016-11 .. 2026-09-10, for rebuilding the
broad sleeve before 2023.

Two pulls, both resumable (a file that already exists is skipped):

  grouped/  one parquet per weekday: every ticker's raw (unadjusted) daily OHLCV.
            Raw on purpose: the Databento daily file the broad sleeve was built on is raw,
            and the 2023-2024 overlap must be compared in the same frame.
  types/    one parquet per month start: every ticker Polygon lists as common stock (CS)
            AS OF that date, including names delisted later. The existing classification
            file is a current snapshot and holds 1 of 10 known delisted names, so it cannot
            be reused before 2023 without keeping survivors only.

Start is 2016-11-01 so ADV20 and ret5 exist on the first 2017 session. On 2026-09-11 this
key's history reached 2016-11-01 but not 2016-06-01 (403) - it looks like a rolling window,
so the earliest months may stop being available if this is postponed.

End is the last completed session. 2025-2026 is the stocks project's SEALED out-of-sample
period: having it on disk does not open it (the Databento daily file already holds it), but
every consumer must filter to <= 2024-12-31 until the seal is lifted on purpose. Files are
laid out one folder per year so that filter is a folder choice, not a date expression.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "raits/data/cache/polygon_grouped_daily"
STATUS = OUT / "status.csv"
BASE = "https://api.polygon.io"
START, END = "2016-11-01", "2026-09-10"


def load_key() -> str:
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if key:
        return key
    spec = importlib.util.spec_from_file_location("config_private", ROOT / "config_private.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return str(mod.POLYGON_API_KEY).strip()


def get(url: str, params: dict, retries: int = 4) -> dict:
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(2.0 * attempt)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(2.0 * attempt)
    raise RuntimeError("unreachable")


def atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.{os.getpid()}.{time.time_ns()}.tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def fetch_day(day: pd.Timestamp, key: str) -> dict:
    path = OUT / "grouped" / f"{day:%Y}" / f"grouped_{day:%Y-%m-%d}.parquet"
    js = get(f"{BASE}/v2/aggs/grouped/locale/us/market/stocks/{day:%Y-%m-%d}", {"adjusted": "false", "apiKey": key})
    res = js.get("results") or []
    if not res:
        return {"kind": "grouped", "key": f"{day:%Y-%m-%d}", "status": "EMPTY", "rows": 0}
    df = pd.DataFrame(res).rename(
        columns={"T": "symbol", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "vw": "vwap", "n": "transactions", "t": "t_ms"}
    )
    df["date"] = day.normalize()
    atomic_parquet(df, path)
    return {"kind": "grouped", "key": f"{day:%Y-%m-%d}", "status": "OK", "rows": len(df)}


def fetch_types(month: pd.Timestamp, key: str) -> dict:
    path = OUT / "types" / f"cs_asof_{month:%Y-%m-%d}.parquet"
    rows: list[dict] = []
    url = f"{BASE}/v3/reference/tickers"
    params = {"market": "stocks", "type": "CS", "date": f"{month:%Y-%m-%d}", "limit": 1000, "apiKey": key}
    while True:
        js = get(url, params)
        rows.extend(js.get("results") or [])
        nxt = js.get("next_url")
        if not nxt:
            break
        url, params = nxt, {"apiKey": key}
    if not rows:
        return {"kind": "types", "key": f"{month:%Y-%m-%d}", "status": "EMPTY", "rows": 0}
    df = pd.DataFrame(rows)
    df["asof"] = month.normalize()
    atomic_parquet(df, path)
    return {"kind": "types", "key": f"{month:%Y-%m-%d}", "status": "OK", "rows": len(df)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    days = [d for d in pd.bdate_range(START, END)
            if not (OUT / "grouped" / f"{d:%Y}" / f"grouped_{d:%Y-%m-%d}.parquet").exists()]
    months = [m for m in pd.date_range(START, END, freq="MS")
              if not (OUT / "types" / f"cs_asof_{m:%Y-%m-%d}.parquet").exists()]
    # Weekdays that came back EMPTY (market holidays) are recorded and not asked again.
    if STATUS.exists():
        st = pd.read_csv(STATUS)
        empty_days = set(st.loc[(st["kind"] == "grouped") & (st["status"] == "EMPTY"), "key"])
        days = [d for d in days if f"{d:%Y-%m-%d}" not in empty_days]
    print(f"OUT {OUT}")
    print(f"pending: {len(days)} weekdays, {len(months)} month-start type lists")
    if args.dry_run:
        return

    key = load_key()
    OUT.mkdir(parents=True, exist_ok=True)
    jobs =[(fetch_types, m) for m in months] + [(fetch_day, d) for d in days]
    done = errors = 0
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        kind_of = {fetch_day: "grouped", fetch_types: "types"}
        futs = {ex.submit(fn, x, key): (kind_of[fn], x) for fn, x in jobs}
        for fut in as_completed(futs):
            name, x = futs[fut]
            try:
                rows.append({**fut.result(), "error": ""})
            except Exception as exc:
                errors += 1
                # requests puts the full URL, apiKey included, into the message.
                msg = str(exc).replace(key, "<key>")[:300]
                rows.append({"kind": name, "key": f"{x:%Y-%m-%d}", "status": "ERROR", "rows": 0, "error": msg})
            done += 1
            if done % 100 == 0 or done == len(jobs):
                print(f"progress {done}/{len(jobs)} errors={errors}", flush=True)
                pd.DataFrame(rows).to_csv(STATUS, mode="a", header=not STATUS.exists(), index=False)
                rows = []
    print("DONE. Rerun the same command to retry anything that errored; finished files are skipped.")


if __name__ == "__main__":
    main()
