from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests


START = pd.Timestamp("2017-01-01")
END = pd.Timestamp("2026-09-16")
CAP_PATHS = [
    Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"),
    Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2025_2026_clean_oos.csv"),
]
FILTER_PATHS = [
    Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet"),
    Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20250102_20260916_clean_oos/liquidity_filter_daily_20250102_20260916_clean_oos_px5_adv10m_unadjusted/filtered_daily_universe.parquet"),
]
CACHE_DIR = Path("raits/data/cache/external_events/sec_submissions_pit_2018_2026")
RAW_DIR = CACHE_DIR / "raw"
CIK_UNIVERSE_OUT = CACHE_DIR / "top500_cik_universe.csv"
EVENTS_OUT = CACHE_DIR / "sec_8k_item_202_events_2017_2026.csv"
STATUS_OUT = CACHE_DIR / "fetch_status.csv"
MANIFEST_OUT = CACHE_DIR / "manifest.json"
ITEM_202 = re.compile(r"(?:^|[,;\s])2\.02(?:$|[,;\s])")


def normalize_cik(values: pd.Series) -> pd.Series:
    return values.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(10)


def build_cik_universe() -> pd.DataFrame:
    cap_frames = []
    for path in CAP_PATHS:
        frame = pd.read_csv(path, low_memory=False)
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker_query"].astype(str).str.upper()
        frame["market_cap"] = pd.to_numeric(frame["market_cap"], errors="coerce")
        frame = frame[frame["status_code"].eq(200) & frame["market_cap"].notna()].copy()
        frame["rank_market_cap"] = frame.groupby("date")["market_cap"].rank(method="first", ascending=False)
        cap_frames.append(frame[frame["rank_market_cap"].le(500)][["date", "ticker", "market_cap"]])
    caps = pd.concat(cap_frames, ignore_index=True).drop_duplicates(["date", "ticker"])

    identity_frames = []
    for path in FILTER_PATHS:
        frame = pd.read_parquet(path, columns=["date", "ticker", "cik", "security_id"])
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        identity_frames.append(frame)
    identity = pd.concat(identity_frames, ignore_index=True).drop_duplicates(["date", "ticker"])
    mapped = caps.merge(identity, on=["date", "ticker"], how="left", validate="one_to_one")
    mapped["cik"] = normalize_cik(mapped["cik"])
    if mapped["cik"].isna().any():
        raise RuntimeError(f"Missing CIK for {int(mapped['cik'].isna().sum())} top500 snapshot rows")
    mapped = mapped[~mapped["cik"].eq("0000000000")].copy()
    summary = mapped.groupby("cik", as_index=False).agg(
        first_snapshot=("date", "min"),
        last_snapshot=("date", "max"),
        snapshot_rows=("date", "size"),
        tickers=("ticker", lambda s: "|".join(sorted(set(s)))),
        security_ids=("security_id", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
    )
    return summary.sort_values("cik").reset_index(drop=True)


def request_json(session: requests.Session, url: str, retries: int, sleep_seconds: float) -> dict:
    error = ""
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=60)
            if response.status_code == 200:
                time.sleep(sleep_seconds)
                return response.json()
            error = f"HTTP {response.status_code}: {response.text[:160]}"
            if response.status_code not in {403, 429, 500, 502, 503, 504}:
                break
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:180]}"
        time.sleep(max(sleep_seconds, min(2 ** attempt, 20)))
    raise RuntimeError(f"{url}: {error}")


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def load_or_fetch(session: requests.Session, url: str, path: Path, retries: int, sleep_seconds: float) -> dict:
    if path.exists() and path.stat().st_size > 0:
        return json.loads(path.read_text(encoding="utf-8"))
    payload = request_json(session, url, retries, sleep_seconds)
    write_json_atomic(path, payload)
    return payload


def archive_overlaps(row: dict[str, object]) -> bool:
    start = pd.to_datetime(row.get("filingFrom"), errors="coerce")
    end = pd.to_datetime(row.get("filingTo"), errors="coerce")
    return pd.notna(start) and pd.notna(end) and start <= END and end >= START


def columnar_rows(payload: dict, source_file: str, cik: str) -> list[dict[str, object]]:
    table = payload.get("filings", {}).get("recent") if "filings" in payload else payload
    if not isinstance(table, dict) or "accessionNumber" not in table:
        return []
    count = len(table.get("accessionNumber", []))
    rows = []
    for index in range(count):
        row = {key: values[index] if index < len(values) else None for key, values in table.items() if isinstance(values, list)}
        row["cik"] = cik
        row["source_file"] = source_file
        rows.append(row)
    return rows


def parse_acceptance_et(value: object) -> pd.Timestamp:
    if value is None or str(value).strip() == "":
        return pd.NaT
    timestamp = pd.Timestamp(str(value))
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
    return timestamp.tz_convert("America/New_York")


def build_events(ciks: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for cik in ciks:
        cik_dir = RAW_DIR / cik
        for path in sorted(cik_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows.extend(columnar_rows(payload, path.name, cik))
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["form"] = frame["form"].fillna("").astype(str)
    frame["items"] = frame.get("items", pd.Series("", index=frame.index)).fillna("").astype(str)
    frame = frame[frame["form"].eq("8-K") & frame["items"].str.contains(ITEM_202, regex=True)].copy()
    frame["accepted_et"] = frame["acceptanceDateTime"].map(parse_acceptance_et)
    frame["filingDate"] = pd.to_datetime(frame["filingDate"], errors="coerce")
    frame = frame[frame["accepted_et"].notna()].copy()
    accepted_naive = frame["accepted_et"].map(lambda value: value.tz_localize(None))
    frame = frame[(accepted_naive >= START) & (accepted_naive <= END + pd.Timedelta(days=1))]
    frame = frame.sort_values(["cik", "accepted_et", "accessionNumber"]).drop_duplicates(["cik", "accessionNumber"], keep="first")
    keep = [
        "cik", "accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "accepted_et",
        "form", "items", "primaryDocument", "isXBRL", "isInlineXBRL", "source_file",
    ]
    return frame[[column for column in keep if column in frame.columns]].reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch SEC submissions history for the PIT top500 CIK union.")
    parser.add_argument("--max-ciks", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.22)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    universe = build_cik_universe()
    universe.to_csv(CIK_UNIVERSE_OUT, index=False)
    if args.max_ciks:
        universe = universe.head(args.max_ciks)
    ciks = universe["cik"].astype(str).str.zfill(10).tolist()

    user_agent = os.environ.get("SEC_USER_AGENT", "Raits Equity Research research@raits.local").strip()
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Host": "data.sec.gov"})
    status_rows = []
    for index, cik in enumerate(ciks, start=1):
        started = time.perf_counter()
        try:
            cik_dir = RAW_DIR / cik
            main_name = f"CIK{cik}.json"
            main_url = f"https://data.sec.gov/submissions/{main_name}"
            payload = load_or_fetch(session, main_url, cik_dir / main_name, args.retries, args.sleep)
            archives = [row for row in payload.get("filings", {}).get("files", []) if archive_overlaps(row)]
            for archive in archives:
                name = str(archive["name"])
                load_or_fetch(session, f"https://data.sec.gov/submissions/{name}", cik_dir / name, args.retries, args.sleep)
            status = "OK"
            error = ""
        except Exception as exc:
            archives = []
            status = "ERROR"
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
        status_rows.append({"cik": cik, "status": status, "archives": len(archives), "seconds": time.perf_counter() - started, "error": error})
        pd.DataFrame(status_rows).to_csv(STATUS_OUT, index=False)
        if index % args.progress_every == 0 or status == "ERROR":
            print(f"ciks={index}/{len(ciks)} ok={sum(row['status']=='OK' for row in status_rows)} errors={sum(row['status']=='ERROR' for row in status_rows)}", flush=True)

    events = build_events(ciks)
    events.to_csv(EVENTS_OUT, index=False)
    manifest = {
        "script": "raits/research/stocks_sec_submissions_fetch.py",
        "source": "https://data.sec.gov/submissions/CIK##########.json plus referenced historical submissions files",
        "fair_access": {"sequential": True, "sleep_seconds": args.sleep, "max_requests_per_second": 1.0 / args.sleep, "user_agent": user_agent},
        "date_window": {"start": str(START.date()), "end": str(END.date())},
        "ciks": len(ciks),
        "status": pd.DataFrame(status_rows)["status"].value_counts().to_dict(),
        "eligible_8k_item_202_events": len(events),
        "inputs": [str(path) for path in CAP_PATHS + FILTER_PATHS],
        "outputs": [str(CIK_UNIVERSE_OUT), str(EVENTS_OUT), str(STATUS_OUT), str(RAW_DIR)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
