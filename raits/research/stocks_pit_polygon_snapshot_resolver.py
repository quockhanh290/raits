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
SNAPSHOT_DIR = Path("raits/data/cache/stocks_survivorship/polygon_universe_snapshot")
SAMPLE_DIR = Path("raits/data/cache/stocks_survivorship/polygon_sample")
OUT_DIR = Path("raits/data/cache/stocks_survivorship/polygon_universe_resolved_sample")
REPORT_PREFIX = "STOCKS_PIT_POLYGON_UNIVERSE_RESOLVED_20260912"
EVENT_EVIDENCE_PATH = OUT_DIR / "duplicate_identity_event_evidence.parquet"


def identity_key(row: pd.Series) -> str:
    share = str(row.get("share_class_figi", "") or "")
    comp = str(row.get("composite_figi", "") or "")
    cik = str(row.get("cik", "") or "")
    ticker = str(row.get("ticker", "") or "")
    if share and share.lower() != "nan":
        return f"SHARE_FIGI:{share}"
    if comp and comp.lower() != "nan":
        return f"COMPOSITE_FIGI:{comp}"
    if cik and cik.lower() != "nan":
        return f"CIK_TICKER:{cik}:{ticker}"
    return f"TICKER:{ticker}"


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    snapshot = pd.read_parquet(SNAPSHOT_DIR / "universe_snapshot.parquet")
    snapshot["date"] = pd.to_datetime(snapshot["date"])
    ticker_history_path = SAMPLE_DIR / "ticker_history.parquet"
    bars_path = SAMPLE_DIR / "daily_bars_raw.parquet"
    ticker_history = pd.read_parquet(ticker_history_path) if ticker_history_path.exists() else pd.DataFrame()
    bars = pd.read_parquet(bars_path) if bars_path.exists() else pd.DataFrame()
    if not ticker_history.empty:
        ticker_history["start_date"] = pd.to_datetime(ticker_history["start_date"])
        ticker_history["end_date"] = pd.to_datetime(ticker_history["end_date"])
    if not bars.empty:
        bars["date"] = pd.to_datetime(bars["date"])
    return snapshot, ticker_history, bars


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
    try:
        resp = session.get(f"{BASE_URL}{path}", params=query, timeout=60)
    except requests.RequestException as exc:
        raise SystemExit(f"Polygon request failed for {path}: {type(exc).__name__}") from None
    try:
        data = resp.json()
    except Exception:
        data = {"message": resp.text[:500]}
    return resp.status_code, data


def event_duplicate_groups(snapshot: pd.DataFrame) -> pd.DataFrame:
    x = snapshot.copy()
    x["identity_key"] = x.apply(identity_key, axis=1)
    sizes = x.groupby(["date", "identity_key"], as_index=False).size()
    dup_keys = sizes[sizes["size"] > 1][["date", "identity_key"]]
    if dup_keys.empty:
        return pd.DataFrame(columns=x.columns)
    return x.merge(dup_keys, on=["date", "identity_key"], how="inner").sort_values(["date", "identity_key", "ticker"])


def fetch_event_evidence(snapshot: pd.DataFrame) -> pd.DataFrame:
    duplicate_rows = event_duplicate_groups(snapshot)
    if duplicate_rows.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "identity_key",
                "ticker",
                "detail_status_code",
                "detail_api_status",
                "detail_active",
                "detail_name",
                "detail_composite_figi",
                "detail_share_class_figi",
                "detail_last_updated_utc",
                "agg_status_code",
                "agg_api_status",
                "event_bar_present",
                "bar_count_window",
                "first_bar_date",
                "last_bar_date",
            ]
        )

    key = load_polygon_key()
    rows: list[dict[str, object]] = []
    with requests.Session() as session:
        for _, row in duplicate_rows.iterrows():
            date = pd.Timestamp(row["date"]).normalize()
            date_s = date.date().isoformat()
            ticker = str(row["ticker"])
            identity = str(row["identity_key"])
            detail_status, detail_payload = get_json(session, key, f"/v3/reference/tickers/{ticker}", {"date": date_s})
            detail_result = detail_payload.get("results") or {}
            time.sleep(0.15)

            start = (date - pd.Timedelta(days=5)).date().isoformat()
            end = (date + pd.Timedelta(days=5)).date().isoformat()
            agg_status, agg_payload = get_json(
                session,
                key,
                f"/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                {"adjusted": "true", "sort": "asc", "limit": "5000"},
            )
            bar_dates = [
                pd.to_datetime(item["t"], unit="ms", utc=True).tz_convert(None).normalize()
                for item in agg_payload.get("results") or []
                if "t" in item
            ]
            rows.append(
                {
                    "date": date,
                    "identity_key": identity,
                    "ticker": ticker,
                    "detail_status_code": detail_status,
                    "detail_api_status": detail_payload.get("status"),
                    "detail_active": detail_result.get("active"),
                    "detail_name": detail_result.get("name", ""),
                    "detail_composite_figi": detail_result.get("composite_figi", ""),
                    "detail_share_class_figi": detail_result.get("share_class_figi", ""),
                    "detail_last_updated_utc": detail_result.get("last_updated_utc", ""),
                    "agg_status_code": agg_status,
                    "agg_api_status": agg_payload.get("status"),
                    "event_bar_present": date in set(bar_dates),
                    "bar_count_window": len(bar_dates),
                    "first_bar_date": min(bar_dates) if bar_dates else pd.NaT,
                    "last_bar_date": max(bar_dates) if bar_dates else pd.NaT,
                }
            )
            time.sleep(0.15)
    return pd.DataFrame(rows)


def load_or_fetch_event_evidence(snapshot: pd.DataFrame) -> pd.DataFrame:
    duplicate_rows = event_duplicate_groups(snapshot)
    required = {
        (pd.Timestamp(row["date"]).normalize(), str(row["identity_key"]), str(row["ticker"]))
        for _, row in duplicate_rows.iterrows()
    }
    if EVENT_EVIDENCE_PATH.exists():
        cached = pd.read_parquet(EVENT_EVIDENCE_PATH)
        if not cached.empty:
            cached["date"] = pd.to_datetime(cached["date"])
        present = {
            (pd.Timestamp(row["date"]).normalize(), str(row["identity_key"]), str(row["ticker"]))
            for _, row in cached.iterrows()
        }
        if required.issubset(present):
            return cached
    return fetch_event_evidence(snapshot)


def valid_by_sample_history(ticker_history: pd.DataFrame, identity: str, ticker: str, date: pd.Timestamp) -> bool:
    if ticker_history.empty:
        return False
    share = identity.split(":", 1)[1] if identity.startswith("SHARE_FIGI:") else ""
    matches = ticker_history[
        ticker_history["security_id"].astype(str).str.contains(share, regex=False)
        & ticker_history["ticker"].eq(ticker)
        & (ticker_history["start_date"] <= date)
        & (ticker_history["end_date"].isna() | (ticker_history["end_date"] >= date))
    ]
    return not matches.empty


def has_sample_bar(bars: pd.DataFrame, ticker: str, date: pd.Timestamp) -> bool:
    if bars.empty:
        return False
    return not bars[bars["ticker"].eq(ticker) & bars["date"].eq(date)].empty


def event_bar_present(event_evidence: pd.DataFrame, identity: str, ticker: str, date: pd.Timestamp) -> bool:
    if event_evidence.empty:
        return False
    matches = event_evidence[
        event_evidence["identity_key"].eq(identity)
        & event_evidence["ticker"].eq(ticker)
        & event_evidence["date"].eq(date.normalize())
    ]
    return not matches.empty and bool(matches.iloc[0].get("event_bar_present", False))


def detail_identity_match(event_evidence: pd.DataFrame, identity: str, ticker: str, date: pd.Timestamp) -> bool:
    if event_evidence.empty:
        return False
    matches = event_evidence[
        event_evidence["identity_key"].eq(identity)
        & event_evidence["ticker"].eq(ticker)
        & event_evidence["date"].eq(date.normalize())
    ]
    if matches.empty:
        return False
    row = matches.iloc[0]
    if identity.startswith("SHARE_FIGI:"):
        return str(row.get("detail_share_class_figi", "")) == identity.split(":", 1)[1]
    if identity.startswith("COMPOSITE_FIGI:"):
        return str(row.get("detail_composite_figi", "")) == identity.split(":", 1)[1]
    return False


def choose_row(
    group: pd.DataFrame,
    ticker_history: pd.DataFrame,
    bars: pd.DataFrame,
    event_evidence: pd.DataFrame,
) -> tuple[int, str, str]:
    date = pd.Timestamp(group["date"].iloc[0])
    identity = str(group["identity_key"].iloc[0])
    candidates = []
    for idx, row in group.iterrows():
        ticker = str(row["ticker"])
        history_valid = valid_by_sample_history(ticker_history, identity, ticker, date)
        event_bar = event_bar_present(event_evidence, identity, ticker, date)
        detail_match = detail_identity_match(event_evidence, identity, ticker, date)
        bar_present = has_sample_bar(bars, ticker, date)
        # Higher is better. History is strongest, then actual sample bar, then most recent
        # last_updated_utc, then lexicographic ticker for deterministic tie-break.
        last_updated = pd.to_datetime(row.get("last_updated_utc"), errors="coerce")
        candidates.append(
            {
                "idx": idx,
                "ticker": ticker,
                "history_valid": history_valid,
                "event_bar": event_bar,
                "detail_match": detail_match,
                "bar_present": bar_present,
                "last_updated": last_updated,
                "score": (
                    int(history_valid),
                    int(event_bar),
                    int(bar_present),
                    int(detail_match),
                    last_updated.value if pd.notna(last_updated) else -1,
                ),
            }
        )
    candidates = sorted(candidates, key=lambda x: (x["score"], x["ticker"]), reverse=True)
    chosen = candidates[0]
    reason_parts = []
    if chosen["history_valid"]:
        reason_parts.append("sample_ticker_history")
    if chosen["event_bar"]:
        reason_parts.append("event_daily_bar")
    if chosen["bar_present"]:
        reason_parts.append("sample_daily_bar")
    if chosen["detail_match"]:
        reason_parts.append("event_detail_identity")
    if not reason_parts:
        reason_parts.append("last_updated_then_ticker")
    return int(chosen["idx"]), str(chosen["ticker"]), "+".join(reason_parts)


def resolve(
    snapshot: pd.DataFrame,
    ticker_history: pd.DataFrame,
    bars: pd.DataFrame,
    event_evidence: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    x = snapshot.copy()
    x["identity_key"] = x.apply(identity_key, axis=1)
    resolved_indices: list[int] = []
    resolution_rows: list[dict[str, object]] = []

    for (date, identity), group in x.groupby(["date", "identity_key"], sort=True):
        if len(group) == 1:
            resolved_indices.append(int(group.index[0]))
            continue
        chosen_idx, chosen_ticker, reason = choose_row(group, ticker_history, bars, event_evidence)
        resolved_indices.append(chosen_idx)
        resolution_rows.append(
            {
                "date": pd.Timestamp(date),
                "identity_key": identity,
                "row_count": int(len(group)),
                "tickers": ",".join(group["ticker"].astype(str).sort_values()),
                "chosen_ticker": chosen_ticker,
                "resolution_reason": reason,
                "names": " | ".join(group["name"].astype(str)),
            }
        )

    resolved = x.loc[sorted(resolved_indices)].copy().reset_index(drop=True)
    resolutions = pd.DataFrame(resolution_rows)

    counts = []
    raw_counts = x.groupby("date").size()
    resolved_counts = resolved.groupby("date").size()
    for date in sorted(raw_counts.index):
        counts.append(
            {
                "date": pd.Timestamp(date),
                "raw_rows": int(raw_counts.loc[date]),
                "resolved_rows": int(resolved_counts.loc[date]),
                "dropped_duplicate_identity_rows": int(raw_counts.loc[date] - resolved_counts.loc[date]),
                "raw_unique_tickers": int(x[x["date"].eq(date)]["ticker"].nunique()),
                "resolved_unique_identity": int(resolved[resolved["date"].eq(date)]["identity_key"].nunique()),
            }
        )
    return resolved, resolutions, pd.DataFrame(counts)


def qa(resolved: pd.DataFrame, resolutions: pd.DataFrame, counts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    dup_identity = resolved.groupby(["date", "identity_key"]).size().reset_index(name="n")
    bad_identity = dup_identity[dup_identity["n"] > 1]
    rows.append(
        {
            "check": "resolved_identity_unique_by_date",
            "status": "PASS" if bad_identity.empty else "FAIL",
            "detail": str(len(bad_identity)),
        }
    )
    rows.append(
        {
            "check": "duplicate_groups_recorded",
            "status": "PASS" if len(resolutions) == int(counts["dropped_duplicate_identity_rows"].sum()) else "WARN",
            "detail": f"groups={len(resolutions)} dropped_rows={int(counts['dropped_duplicate_identity_rows'].sum())}",
        }
    )
    meta = resolutions[resolutions["tickers"].eq("FB,META")]
    rows.append(
        {
            "check": "fb_meta_resolved_to_meta_on_2022_06_09",
            "status": "PASS" if not meta.empty and str(meta.iloc[0]["chosen_ticker"]) == "META" else "FAIL",
            "detail": "",
        }
    )
    hous = resolutions[resolutions["tickers"].eq("HOUS,RLGY")]
    rows.append(
        {
            "check": "hous_rlgy_resolved_by_event_bar",
            "status": "PASS"
            if not hous.empty and "event_daily_bar" in str(hous.iloc[0]["resolution_reason"])
            else "FAIL",
            "detail": f"{hous.iloc[0]['chosen_ticker']} {hous.iloc[0]['resolution_reason']}" if not hous.empty else "",
        }
    )
    return pd.DataFrame(rows)


def write_manifest(paths: dict[str, str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
        "purpose": "resolve duplicate identity rows in Polygon active common-stock snapshot sample",
        "source_snapshot_dir": str(SNAPSHOT_DIR).replace("\\", "/"),
        "bulk_fetch": False,
        "paths": paths,
    }
    (OUT_DIR / "manifest_20260912.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot, ticker_history, bars = load_inputs()
    event_evidence = load_or_fetch_event_evidence(snapshot)
    if not event_evidence.empty:
        event_evidence["date"] = pd.to_datetime(event_evidence["date"])
        event_evidence.to_parquet(EVENT_EVIDENCE_PATH, index=False)
    resolved, resolutions, counts = resolve(snapshot, ticker_history, bars, event_evidence)
    qa_summary = qa(resolved, resolutions, counts)

    resolved_path = OUT_DIR / "resolved_universe_snapshot.parquet"
    resolutions_path = OUT_DIR / "duplicate_identity_resolutions.parquet"
    counts_path = OUT_DIR / "resolved_daily_counts.parquet"
    resolved.to_parquet(resolved_path, index=False)
    resolutions.to_parquet(resolutions_path, index=False)
    counts.to_parquet(counts_path, index=False)

    resolved.to_csv(f"{REPORT_PREFIX}_ROWS.csv", index=False)
    resolutions.to_csv(f"{REPORT_PREFIX}_DUPLICATE_RESOLUTIONS.csv", index=False)
    counts.to_csv(f"{REPORT_PREFIX}_DAILY_COUNTS.csv", index=False)
    event_evidence.to_csv(f"{REPORT_PREFIX}_EVENT_EVIDENCE.csv", index=False)
    qa_summary.to_csv(f"{REPORT_PREFIX}_QA_SUMMARY.csv", index=False)
    write_manifest(
        {
            "resolved_universe_snapshot": str(resolved_path).replace("\\", "/"),
            "duplicate_identity_resolutions": str(resolutions_path).replace("\\", "/"),
            "resolved_daily_counts": str(counts_path).replace("\\", "/"),
            "duplicate_identity_event_evidence": str(EVENT_EVIDENCE_PATH).replace("\\", "/"),
        }
    )

    print(qa_summary.to_string(index=False))
    print(event_evidence.to_string(index=False))
    print(resolutions.to_string(index=False))
    print("WROTE", OUT_DIR)


if __name__ == "__main__":
    main()
