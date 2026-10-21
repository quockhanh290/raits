from __future__ import annotations

import argparse
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


BASE_URL = "https://api.polygon.io"
ROOT_DIR = Path("raits/data/cache/stocks_survivorship")
SNAPSHOT_SAMPLE_DIR = ROOT_DIR / "polygon_universe_snapshot"
PAGE_LIMIT = 1000
REPORT_PREFIX = "STOCKS_PIT_POLYGON_BULK_UNIVERSE_20260912"


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


def request_json(
    session: requests.Session,
    key: str,
    url_or_path: str,
    params: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any], str]:
    query = dict(params or {})
    if url_or_path.startswith("http"):
        url = url_or_path
        if "apiKey=" not in url:
            query["apiKey"] = key
    else:
        url = f"{BASE_URL}{url_or_path}"
        query["apiKey"] = key
    try:
        resp = session.get(url, params=query, timeout=60)
    except requests.RequestException as exc:
        raise SystemExit(f"Polygon request failed for {url_or_path}: {type(exc).__name__}") from None
    try:
        data = resp.json()
    except Exception:
        data = {"message": resp.text[:500]}
    return resp.status_code, data, resp.url.replace(key, "REDACTED")


def date_schedule(start: str, end: str, frequency: str, allow_oos: bool = False) -> list[pd.Timestamp]:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if end_ts > pd.Timestamp("2024-12-31") and not allow_oos:
        raise SystemExit("Refusing to open 2025-2026 OOS; end must be <= 2024-12-31")
    if frequency == "daily":
        dates = pd.bdate_range(start_ts, end_ts)
    elif frequency == "weekly":
        dates = pd.date_range(start_ts, end_ts, freq="W-FRI")
        if start_ts not in dates:
            dates = dates.insert(0, start_ts)
    elif frequency == "monthly":
        dates = pd.date_range(start_ts, end_ts, freq="BME")
        if start_ts not in dates:
            dates = dates.insert(0, start_ts)
    else:
        raise SystemExit(f"Unknown frequency: {frequency}")
    return [pd.Timestamp(x).normalize() for x in dates if start_ts <= pd.Timestamp(x) <= end_ts]


def output_dir(args: argparse.Namespace) -> Path:
    tag = args.tag or f"{args.frequency}_{args.start}_{args.end}".replace("-", "")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in tag)
    return ROOT_DIR / "polygon_universe_bulk" / safe


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


def security_id_from_identity(identity: str) -> str:
    return "POLYGON_" + identity.replace(":", "_")


def instrument_exclusion_reason(row: pd.Series) -> str:
    name = str(row.get("name", "") or "").lower()
    ticker = str(row.get("ticker", "") or "").upper()
    if " etf" in f" {name}" or name.endswith(" etf"):
        return "name_etf"
    if " fund" in f" {name}" or name.endswith(" fund"):
        return "name_fund"
    if "preferred" in name or " pfd" in f" {name}" or " pfd " in name:
        return "name_preferred"
    if "warrant" in name:
        return "name_warrant"
    if " right" in f" {name}" or name.endswith(" right"):
        return "name_right"
    unit_like_name = (
        " unit ben" in name
        or " paired share unit" in name
        or " acquisition corporation unit" in name
        or " acquisition corp. unit" in name
        or name.endswith(" unit")
    )
    unit_like_ticker = ticker.endswith("U") or ticker.endswith(".U") or ticker.endswith("-U")
    if unit_like_name and unit_like_ticker:
        return "name_unit"
    return ""


def load_sample_snapshot(date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    snapshot_path = SNAPSHOT_SAMPLE_DIR / "universe_snapshot.parquet"
    pages_path = SNAPSHOT_SAMPLE_DIR / "page_manifest.parquet"
    if not snapshot_path.exists() or not pages_path.exists():
        return None
    snapshot = pd.read_parquet(snapshot_path)
    snapshot["date"] = pd.to_datetime(snapshot["date"])
    rows = snapshot[snapshot["date"].eq(date)].copy()
    if rows.empty:
        return None
    pages = pd.read_parquet(pages_path)
    pages["date"] = pages["date"].astype(str)
    page_rows = pages[pages["date"].eq(date.date().isoformat())].copy()
    if page_rows.empty:
        return None
    page_rows["cache_source"] = "polygon_universe_snapshot_sample"
    rows["cache_source"] = "polygon_universe_snapshot_sample"
    return rows.reset_index(drop=True), page_rows.reset_index(drop=True)


def fetch_snapshot_date(session: requests.Session, key: str, date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    pages: list[dict[str, object]] = []
    date_s = date.date().isoformat()
    path_or_url = "/v3/reference/tickers"
    params = {
        "date": date_s,
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
                "date": date_s,
                "page": page,
                "status_code": status,
                "api_status": data.get("status"),
                "result_count": len(results),
                "next_url_present": bool(next_url),
                "request_url": safe_url,
                "sample_first": results[0].get("ticker") if results else "",
                "sample_last": results[-1].get("ticker") if results else "",
                "message": data.get("message", ""),
                "cache_source": "polygon_api",
            }
        )
        for item in results:
            rows.append(
                {
                    "date": date,
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
                    "cache_source": "polygon_api",
                }
            )
        if status >= 400 or not next_url:
            break
        path_or_url = next_url
        params = {}
        time.sleep(0.15)
    return pd.DataFrame(rows), pd.DataFrame(pages)


def load_or_fetch_snapshot(
    session: requests.Session,
    key: str,
    out_dir: Path,
    date: pd.Timestamp,
    force: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_dir = out_dir / "raw_snapshots"
    page_dir = out_dir / "page_manifests"
    raw_dir.mkdir(parents=True, exist_ok=True)
    page_dir.mkdir(parents=True, exist_ok=True)
    date_s = date.date().isoformat()
    raw_path = raw_dir / f"{date_s}.parquet"
    page_path = page_dir / f"{date_s}.parquet"
    if not force and raw_path.exists() and page_path.exists():
        rows = pd.read_parquet(raw_path)
        pages = pd.read_parquet(page_path)
        rows["date"] = pd.to_datetime(rows["date"])
        return rows, pages
    if not force:
        sample = load_sample_snapshot(date)
        if sample is not None:
            rows, pages = sample
            rows.to_parquet(raw_path, index=False)
            pages.to_parquet(page_path, index=False)
            return rows, pages
    rows, pages = fetch_snapshot_date(session, key, date)
    rows.to_parquet(raw_path, index=False)
    pages.to_parquet(page_path, index=False)
    return rows, pages


def duplicate_rows(snapshot: pd.DataFrame) -> pd.DataFrame:
    x = snapshot.copy()
    x["identity_key"] = x.apply(identity_key, axis=1)
    sizes = x.groupby(["date", "identity_key"], as_index=False).size()
    dup_keys = sizes[sizes["size"] > 1][["date", "identity_key"]]
    if dup_keys.empty:
        return pd.DataFrame(columns=x.columns)
    return x.merge(dup_keys, on=["date", "identity_key"], how="inner").sort_values(["date", "identity_key", "ticker"])


def fetch_event_evidence(session: requests.Session, key: str, duplicates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in duplicates.iterrows():
        date = pd.Timestamp(row["date"]).normalize()
        date_s = date.date().isoformat()
        ticker = str(row["ticker"])
        identity = str(row["identity_key"])
        detail_status, detail_payload, _ = request_json(session, key, f"/v3/reference/tickers/{ticker}", {"date": date_s})
        detail_result = detail_payload.get("results") or {}
        time.sleep(0.15)
        start = (date - pd.Timedelta(days=5)).date().isoformat()
        end = (date + pd.Timedelta(days=5)).date().isoformat()
        agg_status, agg_payload, _ = request_json(
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
                "detail_composite_figi": detail_result.get("composite_figi", ""),
                "detail_share_class_figi": detail_result.get("share_class_figi", ""),
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


def load_or_fetch_event_evidence(session: requests.Session, key: str, out_dir: Path, snapshot: pd.DataFrame) -> pd.DataFrame:
    evidence_path = out_dir / "duplicate_identity_event_evidence.parquet"
    dups = duplicate_rows(snapshot)
    required = {
        (pd.Timestamp(row["date"]).normalize(), str(row["identity_key"]), str(row["ticker"]))
        for _, row in dups.iterrows()
    }
    if evidence_path.exists():
        cached = pd.read_parquet(evidence_path)
        if not cached.empty:
            cached["date"] = pd.to_datetime(cached["date"])
        present = {
            (pd.Timestamp(row["date"]).normalize(), str(row["identity_key"]), str(row["ticker"]))
            for _, row in cached.iterrows()
        }
        if required.issubset(present):
            return cached
    if dups.empty:
        return pd.DataFrame()
    evidence = fetch_event_evidence(session, key, dups)
    evidence.to_parquet(evidence_path, index=False)
    return evidence


def event_bar_present(evidence: pd.DataFrame, identity: str, ticker: str, date: pd.Timestamp) -> bool:
    if evidence.empty:
        return False
    rows = evidence[
        evidence["date"].eq(date.normalize())
        & evidence["identity_key"].eq(identity)
        & evidence["ticker"].eq(ticker)
    ]
    return not rows.empty and bool(rows.iloc[0].get("event_bar_present", False))


def detail_identity_match(evidence: pd.DataFrame, identity: str, ticker: str, date: pd.Timestamp) -> bool:
    if evidence.empty:
        return False
    rows = evidence[
        evidence["date"].eq(date.normalize())
        & evidence["identity_key"].eq(identity)
        & evidence["ticker"].eq(ticker)
    ]
    if rows.empty:
        return False
    row = rows.iloc[0]
    if identity.startswith("SHARE_FIGI:"):
        return str(row.get("detail_share_class_figi", "")) == identity.split(":", 1)[1]
    if identity.startswith("COMPOSITE_FIGI:"):
        return str(row.get("detail_composite_figi", "")) == identity.split(":", 1)[1]
    return False


def choose_duplicate_row(group: pd.DataFrame, evidence: pd.DataFrame) -> tuple[int, str, str]:
    date = pd.Timestamp(group["date"].iloc[0]).normalize()
    identity = str(group["identity_key"].iloc[0])
    candidates = []
    for idx, row in group.iterrows():
        ticker = str(row["ticker"])
        event_bar = event_bar_present(evidence, identity, ticker, date)
        detail_match = detail_identity_match(evidence, identity, ticker, date)
        last_updated = pd.to_datetime(row.get("last_updated_utc"), errors="coerce")
        candidates.append(
            {
                "idx": idx,
                "ticker": ticker,
                "event_bar": event_bar,
                "detail_match": detail_match,
                "score": (
                    int(event_bar),
                    int(detail_match),
                    last_updated.value if pd.notna(last_updated) else -1,
                ),
            }
        )
    candidates = sorted(candidates, key=lambda x: (x["score"], x["ticker"]), reverse=True)
    chosen = candidates[0]
    reasons = []
    if chosen["event_bar"]:
        reasons.append("event_daily_bar")
    if chosen["detail_match"]:
        reasons.append("event_detail_identity")
    if not reasons:
        reasons.append("last_updated_then_ticker")
    return int(chosen["idx"]), str(chosen["ticker"]), "+".join(reasons)


def resolve_snapshot(snapshot: pd.DataFrame, evidence: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    x = snapshot.copy()
    x["identity_key"] = x.apply(identity_key, axis=1)
    keep_indices: list[int] = []
    resolutions: list[dict[str, object]] = []
    for (date, identity), group in x.groupby(["date", "identity_key"], sort=True):
        if len(group) == 1:
            keep_indices.append(int(group.index[0]))
            continue
        chosen_idx, chosen_ticker, reason = choose_duplicate_row(group, evidence)
        keep_indices.append(chosen_idx)
        resolutions.append(
            {
                "date": pd.Timestamp(date).normalize(),
                "identity_key": identity,
                "row_count": int(len(group)),
                "tickers": ",".join(group["ticker"].astype(str).sort_values()),
                "chosen_ticker": chosen_ticker,
                "resolution_reason": reason,
                "names": " | ".join(group["name"].astype(str)),
            }
        )
    resolved = x.loc[sorted(keep_indices)].copy().reset_index(drop=True)
    resolved["security_id"] = resolved["identity_key"].map(security_id_from_identity)
    resolved["in_base_universe"] = True
    resolved["eligible_polygon_common_stock"] = resolved["type"].eq("CS") & resolved["active"].astype(bool)
    resolved["instrument_exclusion_reason"] = resolved.apply(instrument_exclusion_reason, axis=1)
    resolved["eligible_common_stock"] = (
        resolved["eligible_polygon_common_stock"] & resolved["instrument_exclusion_reason"].eq("")
    )
    resolved["eligible_liquidity"] = pd.NA
    resolved["eligible_price"] = pd.NA
    resolved["eligible_final"] = resolved["eligible_common_stock"]
    resolved["reason_excluded"] = resolved.apply(
        lambda row: ""
        if bool(row["eligible_final"])
        else (row["instrument_exclusion_reason"] or "not_active_common_stock"),
        axis=1,
    )
    return resolved, pd.DataFrame(resolutions)


def possible_non_common_by_name(resolved: pd.DataFrame) -> pd.DataFrame:
    patterns = {
        "fund": r"\bfund\b",
        "etf": r"\betf\b",
        "trust": r"\btrust\b",
        "preferred": r"\bpreferred\b|\bpfd\b",
        "unit": r"\bunit\b",
        "warrant": r"\bwarrant\b",
        "right": r"\bright\b",
    }
    rows = []
    names = resolved["name"].fillna("").astype(str)
    for label, pattern in patterns.items():
        mask = names.str.contains(pattern, case=False, regex=True)
        sample = resolved.loc[mask, ["ticker", "name"]].drop_duplicates().head(10)
        rows.append(
            {
                "pattern": label,
                "rows": int(mask.sum()),
                "unique_security_id": int(resolved.loc[mask, "security_id"].nunique()),
                "sample_tickers": ",".join(sample["ticker"].astype(str)),
                "sample_names": " | ".join(sample["name"].astype(str)),
            }
        )
    return pd.DataFrame(rows)


def instrument_exclusion_summary(resolved: pd.DataFrame) -> pd.DataFrame:
    excluded = resolved[resolved["instrument_exclusion_reason"].astype(str).ne("")].copy()
    if excluded.empty:
        return pd.DataFrame(columns=["reason_excluded", "rows", "unique_security_id", "sample_tickers"])
    return (
        excluded.groupby("instrument_exclusion_reason")
        .agg(
            rows=("ticker", "count"),
            unique_security_id=("security_id", "nunique"),
            sample_tickers=("ticker", lambda s: ",".join(pd.Series(s).astype(str).drop_duplicates().head(12))),
        )
        .reset_index()
        .rename(columns={"instrument_exclusion_reason": "reason_excluded"})
        .sort_values(["rows", "reason_excluded"], ascending=[False, True])
    )


def qa(
    raw: pd.DataFrame,
    resolved: pd.DataFrame,
    pages: pd.DataFrame,
    resolutions: pd.DataFrame,
    name_flags: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    counts = []
    for date, raw_group in raw.groupby("date"):
        res_group = resolved[resolved["date"].eq(date)]
        page_group = pages[pages["date"].astype(str).eq(pd.Timestamp(date).date().isoformat())]
        counts.append(
            {
                "date": pd.Timestamp(date).normalize(),
                "raw_rows": int(len(raw_group)),
                "resolved_rows": int(len(res_group)),
                "dropped_duplicate_identity_rows": int(len(raw_group) - len(res_group)),
                "raw_unique_tickers": int(raw_group["ticker"].nunique()),
                "resolved_unique_security_id": int(res_group["security_id"].nunique()),
                "eligible_final_rows": int(res_group["eligible_final"].sum()),
                "excluded_instrument_rows": int(res_group["instrument_exclusion_reason"].astype(str).ne("").sum()),
                "pages": int(page_group["page"].max()) if not page_group.empty else 0,
                "pagination_complete": bool(not page_group.empty and not bool(page_group.iloc[-1]["next_url_present"])),
            }
        )
    counts_df = pd.DataFrame(counts)
    dup_identity = resolved.groupby(["date", "identity_key"]).size().reset_index(name="n")
    dup_ticker = resolved.groupby(["date", "ticker"]).size().reset_index(name="n")
    qa_rows = [
        {
            "check": "resolved_identity_unique_by_date",
            "status": "PASS" if dup_identity[dup_identity["n"] > 1].empty else "FAIL",
            "detail": str(len(dup_identity[dup_identity["n"] > 1])),
        },
        {
            "check": "resolved_ticker_unique_by_date",
            "status": "PASS" if dup_ticker[dup_ticker["n"] > 1].empty else "FAIL",
            "detail": str(len(dup_ticker[dup_ticker["n"] > 1])),
        },
        {
            "check": "pagination_complete",
            "status": "PASS" if counts_df["pagination_complete"].all() else "FAIL",
            "detail": f"dates={len(counts_df)}",
        },
        {
            "check": "duplicate_groups_recorded",
            "status": "PASS" if len(resolutions) == int(counts_df["dropped_duplicate_identity_rows"].sum()) else "WARN",
            "detail": f"groups={len(resolutions)} dropped_rows={int(counts_df['dropped_duplicate_identity_rows'].sum())}",
        },
        {
            "check": "daily_universe_has_security_id",
            "status": "PASS" if resolved["security_id"].astype(str).ne("").all() else "FAIL",
            "detail": "",
        },
        {
            "check": "instrument_exclusion_layer_present",
            "status": "PASS" if "instrument_exclusion_reason" in resolved.columns else "FAIL",
            "detail": f"excluded_rows={int(resolved['instrument_exclusion_reason'].astype(str).ne('').sum())}",
        },
        {
            "check": "possible_non_common_name_flags",
            "status": "WARN" if int(name_flags["rows"].sum()) > 0 else "PASS",
            "detail": f"rows={int(name_flags['rows'].sum())} unique_sum={int(name_flags['unique_security_id'].sum())}",
        },
    ]
    return pd.DataFrame(qa_rows), counts_df


def write_manifest(out_dir: Path, args: argparse.Namespace, dates: list[pd.Timestamp], paths: dict[str, str]) -> None:
    payload = {
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
        "source": "Polygon /v3/reference/tickers active CS snapshots",
        "purpose": "bulk PIT active common-stock universe snapshots with identity resolution",
        "start": args.start,
        "end": args.end,
        "frequency": args.frequency,
        "dates": [d.date().isoformat() for d in dates],
        "page_limit": PAGE_LIMIT,
        "opened_2025_2026_oos": False,
        "paths": paths,
    }
    (out_dir / "manifest_20260912.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build PIT Polygon active common-stock universe snapshots.")
    parser.add_argument("--start", default="2022-06-08")
    parser.add_argument("--end", default="2022-06-10")
    parser.add_argument("--frequency", choices=["daily", "weekly", "monthly"], default="daily")
    parser.add_argument("--tag", default="pilot_20220608_20220610_daily")
    parser.add_argument("--max-dates", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dates = date_schedule(args.start, args.end, args.frequency)
    if args.max_dates > 0:
        dates = dates[: args.max_dates]
    if not dates:
        raise SystemExit("No dates selected")

    out_dir = output_dir(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = load_polygon_key()
    raw_frames = []
    page_frames = []
    with requests.Session() as session:
        for date in dates:
            rows, pages = load_or_fetch_snapshot(session, key, out_dir, date, args.force)
            raw_frames.append(rows)
            page_frames.append(pages)
            print(date.date().isoformat(), "rows", len(rows), "pages", len(pages), flush=True)
        raw = pd.concat(raw_frames, ignore_index=True)
        pages = pd.concat(page_frames, ignore_index=True)
        raw["date"] = pd.to_datetime(raw["date"])
        evidence = load_or_fetch_event_evidence(session, key, out_dir, raw)

    if not evidence.empty:
        evidence["date"] = pd.to_datetime(evidence["date"])
    resolved, resolutions = resolve_snapshot(raw, evidence)
    name_flags = possible_non_common_by_name(resolved)
    exclusion_summary = instrument_exclusion_summary(resolved)
    qa_summary, daily_counts = qa(raw, resolved, pages, resolutions, name_flags)

    paths = {
        "raw_universe_snapshot": str((out_dir / "raw_universe_snapshot.parquet")).replace("\\", "/"),
        "page_manifest": str((out_dir / "page_manifest.parquet")).replace("\\", "/"),
        "daily_universe": str((out_dir / "daily_universe.parquet")).replace("\\", "/"),
        "duplicate_identity_resolutions": str((out_dir / "duplicate_identity_resolutions.parquet")).replace("\\", "/"),
        "duplicate_identity_event_evidence": str((out_dir / "duplicate_identity_event_evidence.parquet")).replace("\\", "/"),
        "daily_counts": str((out_dir / "daily_counts.parquet")).replace("\\", "/"),
        "possible_non_common_name_flags": str((out_dir / "possible_non_common_name_flags.parquet")).replace("\\", "/"),
        "instrument_exclusion_summary": str((out_dir / "instrument_exclusion_summary.parquet")).replace("\\", "/"),
    }
    raw.to_parquet(out_dir / "raw_universe_snapshot.parquet", index=False)
    pages.to_parquet(out_dir / "page_manifest.parquet", index=False)
    resolved.to_parquet(out_dir / "daily_universe.parquet", index=False)
    resolutions.to_parquet(out_dir / "duplicate_identity_resolutions.parquet", index=False)
    if not evidence.empty:
        evidence.to_parquet(out_dir / "duplicate_identity_event_evidence.parquet", index=False)
    daily_counts.to_parquet(out_dir / "daily_counts.parquet", index=False)
    name_flags.to_parquet(out_dir / "possible_non_common_name_flags.parquet", index=False)
    exclusion_summary.to_parquet(out_dir / "instrument_exclusion_summary.parquet", index=False)

    suffix = (args.tag or f"{args.frequency}_{args.start}_{args.end}").upper().replace("-", "")
    resolved.to_csv(f"{REPORT_PREFIX}_{suffix}_DAILY_UNIVERSE.csv", index=False)
    resolutions.to_csv(f"{REPORT_PREFIX}_{suffix}_DUPLICATE_RESOLUTIONS.csv", index=False)
    evidence.to_csv(f"{REPORT_PREFIX}_{suffix}_EVENT_EVIDENCE.csv", index=False)
    daily_counts.to_csv(f"{REPORT_PREFIX}_{suffix}_DAILY_COUNTS.csv", index=False)
    name_flags.to_csv(f"{REPORT_PREFIX}_{suffix}_POSSIBLE_NON_COMMON_NAME_FLAGS.csv", index=False)
    exclusion_summary.to_csv(f"{REPORT_PREFIX}_{suffix}_INSTRUMENT_EXCLUSION_SUMMARY.csv", index=False)
    qa_summary.to_csv(f"{REPORT_PREFIX}_{suffix}_QA_SUMMARY.csv", index=False)
    write_manifest(out_dir, args, dates, paths)

    print(qa_summary.to_string(index=False))
    print(exclusion_summary.to_string(index=False))
    print(name_flags.to_string(index=False))
    print(daily_counts.to_string(index=False))
    if not resolutions.empty:
        print(resolutions.to_string(index=False))
    print("WROTE", out_dir)


if __name__ == "__main__":
    main()
