from __future__ import annotations

import argparse
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
ROOT_DIR = Path("raits/data/cache/stocks_survivorship")
REPORT_PREFIX = "STOCKS_PIT_POLYGON_LIQUIDITY_FILTER_20260912"


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


def request_json(session: requests.Session, key: str, path: str, params: dict[str, str]) -> tuple[int, dict[str, Any]]:
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


def grouped_cache_dir(adjusted: bool) -> Path:
    return ROOT_DIR / ("polygon_grouped_daily_adjusted" if adjusted else "polygon_grouped_daily_unadjusted")


def cache_path(date: pd.Timestamp, cache_dir: Path) -> Path:
    return cache_dir / f"{date.date().isoformat()}.parquet"


def grouped_daily_schema() -> list[str]:
    return [
        "date",
        "ticker",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vwap",
        "transactions",
        "status_code",
        "api_status",
        "result_count",
    ]


def fetch_grouped_daily(session: requests.Session, key: str, date: pd.Timestamp, adjusted: bool) -> pd.DataFrame:
    date_s = date.date().isoformat()
    status, data = request_json(
        session,
        key,
        f"/v2/aggs/grouped/locale/us/market/stocks/{date_s}",
        {"adjusted": "true" if adjusted else "false", "include_otc": "false"},
    )
    rows = []
    for item in data.get("results") or []:
        rows.append(
            {
                "date": date,
                "ticker": item.get("T", ""),
                "open": item.get("o"),
                "high": item.get("h"),
                "low": item.get("l"),
                "close": item.get("c"),
                "volume": item.get("v"),
                "vwap": item.get("vw"),
                "transactions": item.get("n"),
                "status_code": status,
                "api_status": data.get("status"),
                "result_count": data.get("resultsCount", len(data.get("results") or [])),
            }
        )
    return pd.DataFrame(rows, columns=grouped_daily_schema())


def load_or_fetch_grouped_daily(
    session: requests.Session,
    key: str,
    date: pd.Timestamp,
    force: bool,
    cache_dir: Path,
    adjusted: bool,
) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(date, cache_dir)
    if path.exists() and not force:
        frame = pd.read_parquet(path)
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"])
        return frame
    frame = fetch_grouped_daily(session, key, date, adjusted)
    frame.to_parquet(path, index=False)
    time.sleep(0.15)
    return frame


def required_bar_dates(universe_dates: pd.Series, lookback: int, allow_oos: bool = False) -> list[pd.Timestamp]:
    min_date = pd.to_datetime(universe_dates).min().normalize() - pd.Timedelta(days=max(45, lookback * 4))
    max_date = pd.to_datetime(universe_dates).max().normalize()
    if max_date > pd.Timestamp("2024-12-31") and not allow_oos:
        raise SystemExit("Refusing to open 2025-2026 OOS")
    return [pd.Timestamp(x).normalize() for x in pd.bdate_range(min_date, max_date)]


def ticker_security_ranges(universe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pairs = universe[["date", "ticker", "security_id"]].dropna().drop_duplicates().copy()
    pairs["date"] = pd.to_datetime(pairs["date"])
    ranges = (
        pairs.groupby(["ticker", "security_id"], as_index=False)
        .agg(start_date=("date", "min"), end_date=("date", "max"), observations=("date", "count"))
        .sort_values(["ticker", "start_date", "security_id"])
    )
    counts = ranges.groupby("ticker")["security_id"].nunique().reset_index(name="security_id_count")
    ambiguous_tickers = set(counts[counts["security_id_count"].gt(1)]["ticker"].astype(str))
    ambiguous = ranges[ranges["ticker"].astype(str).isin(ambiguous_tickers)].copy()
    usable = ranges[~ranges["ticker"].astype(str).isin(ambiguous_tickers)].copy()
    return usable, ambiguous


def assign_bar_security_ids(bars: pd.DataFrame, universe: pd.DataFrame, lookback: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    ranges, ambiguous = ticker_security_ranges(universe)
    if ranges.empty:
        bars = bars.copy()
        bars["bar_security_id"] = pd.NA
        return bars, ambiguous
    global_start = pd.to_datetime(universe["date"]).min().normalize()
    warmup_start = global_start - pd.Timedelta(days=max(45, lookback * 4))
    ranges.loc[ranges["start_date"].eq(global_start), "start_date"] = warmup_start
    assigned_parts = []
    for ticker, bar_group in bars.groupby("ticker", sort=False):
        ticker_ranges = ranges[ranges["ticker"].eq(ticker)]
        if ticker_ranges.empty:
            chunk = bar_group.copy()
            chunk["bar_security_id"] = pd.NA
            assigned_parts.append(chunk)
            continue
        chunks = []
        for _, row in ticker_ranges.iterrows():
            mask = bar_group["date"].between(pd.Timestamp(row["start_date"]), pd.Timestamp(row["end_date"]))
            if not mask.any():
                continue
            chunk = bar_group.loc[mask].copy()
            chunk["bar_security_id"] = str(row["security_id"])
            chunks.append(chunk)
        if chunks:
            used_index = pd.concat(chunks).index
            unused = bar_group.loc[~bar_group.index.isin(used_index)].copy()
            unused["bar_security_id"] = pd.NA
            assigned_parts.extend(chunks)
            if not unused.empty:
                assigned_parts.append(unused)
        else:
            chunk = bar_group.copy()
            chunk["bar_security_id"] = pd.NA
            assigned_parts.append(chunk)
    out = pd.concat(assigned_parts, ignore_index=False).sort_index()
    return out, ambiguous


def load_bars_for_universe(
    universe: pd.DataFrame,
    lookback: int,
    force: bool,
    progress_every: int,
    adjusted: bool,
    allow_oos: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = required_bar_dates(universe["date"], lookback, allow_oos=allow_oos)
    key = load_polygon_key()
    cache_dir = grouped_cache_dir(adjusted)
    frames = []
    manifest_rows = []
    with requests.Session() as session:
        for i, date in enumerate(dates, start=1):
            path = cache_path(date, cache_dir)
            cache_hit = path.exists() and not force
            frame = load_or_fetch_grouped_daily(session, key, date, force, cache_dir, adjusted)
            frames.append(frame)
            manifest_rows.append(
                {
                    "date": date,
                    "rows": int(len(frame)),
                    "cache_hit": bool(cache_hit),
                    "status_code": int(frame["status_code"].iloc[0]) if not frame.empty else pd.NA,
                    "api_status": str(frame["api_status"].iloc[0]) if not frame.empty else "",
                }
            )
            if progress_every > 0 and (i == 1 or i == len(dates) or i % progress_every == 0 or not cache_hit):
                print(
                    f"{i}/{len(dates)}",
                    date.date().isoformat(),
                    "grouped_rows",
                    len(frame),
                    "cache_hit",
                    cache_hit,
                    flush=True,
                )
    bars = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame(columns=grouped_daily_schema())
    if not bars.empty:
        bars["date"] = pd.to_datetime(bars["date"])
        bars["dollar_volume"] = bars["close"].astype(float) * bars["volume"].astype(float)
        bars = bars.sort_values(["ticker", "date"]).reset_index(drop=True)
        ticker_grouped = bars.groupby("ticker", sort=False)
        bars["ticker_adv20"] = ticker_grouped["dollar_volume"].transform(lambda s: s.rolling(20, min_periods=10).mean())
        bars["ticker_adv20_obs"] = ticker_grouped["dollar_volume"].transform(lambda s: s.rolling(20, min_periods=10).count())
        bars, ambiguous = assign_bar_security_ids(bars, universe, lookback)
        bars["security_adv20"] = pd.NA
        bars["security_adv20_obs"] = pd.NA
        bars["_source_index"] = bars.index
        mapped = bars[bars["bar_security_id"].notna()].copy()
        mapped = mapped.sort_values(["bar_security_id", "date"]).reset_index(drop=True)
        grouped = mapped.groupby("bar_security_id", sort=False)
        mapped["security_adv20"] = grouped["dollar_volume"].transform(lambda s: s.rolling(20, min_periods=10).mean())
        mapped["security_adv20_obs"] = grouped["dollar_volume"].transform(lambda s: s.rolling(20, min_periods=10).count())
        bars.loc[mapped["_source_index"], "security_adv20"] = mapped["security_adv20"].to_numpy()
        bars.loc[mapped["_source_index"], "security_adv20_obs"] = mapped["security_adv20_obs"].to_numpy()
        bars = bars.drop(columns=["_source_index"])
    else:
        ambiguous = pd.DataFrame(columns=["ticker", "security_id"])
    return bars, pd.DataFrame(manifest_rows), ambiguous


def latest_prior_metrics(bars_before_date: pd.DataFrame) -> pd.DataFrame:
    if bars_before_date.empty:
        return pd.DataFrame(columns=["security_id", "prior_bar_ticker", "prior_bar_date", "prior_close", "adv20", "adv20_obs"])
    mapped = bars_before_date[bars_before_date["bar_security_id"].notna()].copy()
    if mapped.empty:
        return pd.DataFrame(columns=["security_id", "prior_bar_ticker", "prior_bar_date", "prior_close", "adv20", "adv20_obs"])
    last = mapped.sort_values(["bar_security_id", "date"]).groupby("bar_security_id", as_index=False).tail(1)
    out = last.rename(
        columns={
            "bar_security_id": "security_id",
            "ticker": "prior_bar_ticker",
            "date": "prior_bar_date",
            "close": "prior_close",
            "security_adv20": "adv20",
            "security_adv20_obs": "adv20_obs",
        }
    )[["security_id", "prior_bar_ticker", "prior_bar_date", "prior_close", "adv20", "adv20_obs"]]
    out["liquidity_metric_source"] = "security_id"
    return out


def latest_prior_ticker_metrics(bars_before_date: pd.DataFrame) -> pd.DataFrame:
    if bars_before_date.empty:
        return pd.DataFrame(columns=["ticker", "ticker_prior_bar_date", "ticker_prior_close", "ticker_adv20", "ticker_adv20_obs"])
    last = bars_before_date.sort_values(["ticker", "date"]).groupby("ticker", as_index=False).tail(1)
    return last.rename(
        columns={
            "date": "ticker_prior_bar_date",
            "close": "ticker_prior_close",
        }
    )[["ticker", "ticker_prior_bar_date", "ticker_prior_close", "ticker_adv20", "ticker_adv20_obs"]]


def _merge_asof_by(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    by: str,
    left_on: str,
    right_on: str,
) -> pd.DataFrame:
    if left.empty or right.empty:
        return left.copy()
    parts = []
    right_groups = {str(key): group.sort_values(right_on) for key, group in right.groupby(by, sort=False)}
    for key, left_group in left.groupby(by, sort=False):
        match = right_groups.get(str(key))
        if match is None or match.empty:
            parts.append(left_group.copy())
            continue
        chunk = pd.merge_asof(
            left_group.sort_values(left_on),
            match,
            left_on=left_on,
            right_on=right_on,
            direction="backward",
            allow_exact_matches=False,
        )
        if f"{by}_x" in chunk.columns:
            if by in chunk.columns:
                chunk = chunk.drop(columns=[by])
            chunk = chunk.rename(columns={f"{by}_x": by})
        elif by not in chunk.columns and f"{by}_left" in chunk.columns:
            chunk = chunk.rename(columns={f"{by}_left": by})
        if f"{by}_y" in chunk.columns:
            chunk = chunk.drop(columns=[f"{by}_y"])
        parts.append(chunk)
    return pd.concat(parts, ignore_index=True)


def apply_filters(
    universe: pd.DataFrame,
    bars: pd.DataFrame,
    min_price: float,
    min_adv20: float,
    min_obs: int,
) -> pd.DataFrame:
    base = universe.copy()
    base["_row_id"] = np.arange(len(base), dtype=np.int64)
    base["ticker"] = base["ticker"].astype(str)
    base["security_id"] = base["security_id"].astype(str)

    current = bars[["date", "ticker"]].drop_duplicates().copy()
    current["ticker"] = current["ticker"].astype(str)
    current["has_current_daily_bar"] = True
    merged = base.merge(current, on=["date", "ticker"], how="left")
    merged["has_current_daily_bar"] = merged["has_current_daily_bar"].fillna(False)

    sec_metrics = bars[bars["bar_security_id"].notna()].copy()
    if not sec_metrics.empty:
        sec_metrics["security_id"] = sec_metrics["bar_security_id"].astype(str)
        sec_metrics = sec_metrics.rename(
            columns={
                "ticker": "prior_bar_ticker",
                "date": "prior_bar_date",
                "close": "prior_close",
                "security_adv20": "adv20",
                "security_adv20_obs": "adv20_obs",
            }
        )[["security_id", "prior_bar_ticker", "prior_bar_date", "prior_close", "adv20", "adv20_obs"]]
        sec_metrics["liquidity_metric_source"] = "security_id"
        merged = _merge_asof_by(
            merged,
            sec_metrics,
            by="security_id",
            left_on="date",
            right_on="prior_bar_date",
        )
    else:
        merged["prior_bar_ticker"] = pd.NA
        merged["prior_bar_date"] = pd.NaT
        merged["prior_close"] = pd.NA
        merged["adv20"] = pd.NA
        merged["adv20_obs"] = pd.NA
        merged["liquidity_metric_source"] = ""

    ticker_metrics = bars.rename(
        columns={
            "date": "ticker_prior_bar_date",
            "close": "ticker_prior_close",
        }
    )[["ticker", "ticker_prior_bar_date", "ticker_prior_close", "ticker_adv20", "ticker_adv20_obs"]].copy()
    ticker_metrics["ticker"] = ticker_metrics["ticker"].astype(str)
    merged = _merge_asof_by(
        merged,
        ticker_metrics,
        by="ticker",
        left_on="date",
        right_on="ticker_prior_bar_date",
    )

    needs_fallback = merged["prior_close"].isna() & merged["ticker_prior_close"].notna()
    merged.loc[needs_fallback, "prior_bar_ticker"] = merged.loc[needs_fallback, "ticker"]
    merged.loc[needs_fallback, "prior_bar_date"] = merged.loc[needs_fallback, "ticker_prior_bar_date"]
    merged.loc[needs_fallback, "prior_close"] = merged.loc[needs_fallback, "ticker_prior_close"]
    merged.loc[needs_fallback, "adv20"] = merged.loc[needs_fallback, "ticker_adv20"]
    merged.loc[needs_fallback, "adv20_obs"] = merged.loc[needs_fallback, "ticker_adv20_obs"]
    merged["liquidity_metric_source"] = merged["liquidity_metric_source"].fillna("")
    merged.loc[needs_fallback, "liquidity_metric_source"] = "ticker_fallback"
    merged["eligible_price"] = merged["prior_close"].astype(float) >= min_price
    merged["eligible_liquidity"] = (
        (merged["adv20"].astype(float) >= min_adv20)
        & (merged["adv20_obs"].fillna(0).astype(float) >= float(min_obs))
    )
    merged["eligible_final"] = (
        merged["eligible_common_stock"].astype(bool)
        & merged["eligible_price"].astype(bool)
        & merged["eligible_liquidity"].astype(bool)
        & merged["has_current_daily_bar"].astype(bool)
    )

    existing_reason = merged["reason_excluded"].fillna("").astype(str)
    merged["reason_excluded"] = np.select(
        [
            merged["eligible_final"].astype(bool),
            existing_reason.ne(""),
            ~merged["has_current_daily_bar"].astype(bool),
            merged["prior_close"].isna(),
            ~merged["eligible_price"].astype(bool),
            ~merged["eligible_liquidity"].astype(bool),
        ],
        [
            "",
            existing_reason,
            "no_current_daily_bar",
            "no_prior_daily_bar",
            "prior_close_below_min",
            "adv20_below_min",
        ],
        default="unknown_filter_exclusion",
    )
    return merged.sort_values("_row_id").drop(columns=["_row_id"]).reset_index(drop=True)


def summarize_daily(filtered: pd.DataFrame) -> pd.DataFrame:
    return (
        filtered.groupby("date")
        .agg(
            rows=("ticker", "count"),
            common_stock_rows=("eligible_common_stock", "sum"),
            price_eligible_rows=("eligible_price", "sum"),
            liquidity_eligible_rows=("eligible_liquidity", "sum"),
            current_daily_bar_rows=("has_current_daily_bar", "sum"),
            final_eligible_rows=("eligible_final", "sum"),
            ticker_fallback_rows=("liquidity_metric_source", lambda s: int((s == "ticker_fallback").sum())),
            no_current_daily_bar=("reason_excluded", lambda s: int((s == "no_current_daily_bar").sum())),
            no_prior_daily_bar=("reason_excluded", lambda s: int((s == "no_prior_daily_bar").sum())),
            prior_close_below_min=("reason_excluded", lambda s: int((s == "prior_close_below_min").sum())),
            adv20_below_min=("reason_excluded", lambda s: int((s == "adv20_below_min").sum())),
        )
        .reset_index()
    )


def summarize_reasons(filtered: pd.DataFrame) -> pd.DataFrame:
    excluded = filtered[filtered["reason_excluded"].astype(str).ne("")].copy()
    if excluded.empty:
        return pd.DataFrame(columns=["reason_excluded", "rows", "unique_security_id", "sample_tickers"])
    return (
        excluded.groupby("reason_excluded")
        .agg(
            rows=("ticker", "count"),
            unique_security_id=("security_id", "nunique"),
            sample_tickers=("ticker", lambda s: ",".join(pd.Series(s).astype(str).drop_duplicates().head(12))),
        )
        .reset_index()
        .sort_values(["rows", "reason_excluded"], ascending=[False, True])
    )


def qa(
    filtered: pd.DataFrame,
    bars: pd.DataFrame,
    ambiguous_ticker_map: pd.DataFrame,
    min_price: float,
    min_adv20: float,
    min_obs: int,
) -> pd.DataFrame:
    future_leak = filtered[
        filtered["prior_bar_date"].notna()
        & (pd.to_datetime(filtered["prior_bar_date"]) >= pd.to_datetime(filtered["date"]))
    ]
    rows = [
        {
            "check": "no_future_bar_used",
            "status": "PASS" if future_leak.empty else "FAIL",
            "detail": str(len(future_leak)),
        },
        {
            "check": "filtered_universe_has_security_id",
            "status": "PASS" if filtered["security_id"].astype(str).ne("").all() else "FAIL",
            "detail": "",
        },
        {
            "check": "price_filter_applied",
            "status": "PASS" if filtered["eligible_price"].notna().all() else "FAIL",
            "detail": f"min_price={min_price:g}",
        },
        {
            "check": "liquidity_filter_applied",
            "status": "PASS" if filtered["eligible_liquidity"].notna().all() else "FAIL",
            "detail": f"min_adv20={min_adv20:g} min_obs={min_obs}",
        },
        {
            "check": "grouped_daily_bars_loaded",
            "status": "PASS" if not bars.empty else "FAIL",
            "detail": f"rows={len(bars)} dates={bars['date'].nunique() if not bars.empty else 0}",
        },
        {
            "check": "ambiguous_ticker_security_map",
            "status": "WARN" if not ambiguous_ticker_map.empty else "PASS",
            "detail": f"rows={len(ambiguous_ticker_map)} tickers={ambiguous_ticker_map['ticker'].nunique() if not ambiguous_ticker_map.empty else 0}",
        },
        {
            "check": "ticker_fallback_used",
            "status": "WARN" if int((filtered["liquidity_metric_source"] == "ticker_fallback").sum()) > 0 else "PASS",
            "detail": f"rows={int((filtered['liquidity_metric_source'] == 'ticker_fallback').sum())}",
        },
    ]
    return pd.DataFrame(rows)


def output_dir(input_dir: Path, args: argparse.Namespace) -> Path:
    tag = args.tag or f"px{args.min_price:g}_adv{int(args.min_adv20)}_lb{args.lookback}_obs{args.min_obs}"
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in tag)
    return input_dir / f"liquidity_filter_{safe}"


def write_manifest(out_dir: Path, input_dir: Path, args: argparse.Namespace, paths: dict[str, str]) -> None:
    payload = {
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
        "source": "Polygon grouped daily adjusted bars",
        "purpose": "apply prior-window price and liquidity filters to PIT universe",
        "input_dir": str(input_dir).replace("\\", "/"),
        "lookback": args.lookback,
        "min_price": args.min_price,
        "min_adv20": args.min_adv20,
        "min_obs": args.min_obs,
        "grouped_daily_adjusted": args.adjusted_bars,
        "grouped_cache_dir": str(grouped_cache_dir(args.adjusted_bars)).replace("\\", "/"),
        "opened_2025_2026_oos": bool(args.allow_oos),
        "paths": paths,
    }
    (out_dir / "manifest_20260912.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply prior-window price/liquidity filters to PIT Polygon universe.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--lookback", type=int, default=20)
    parser.add_argument("--min-obs", type=int, default=10)
    parser.add_argument("--min-price", type=float, default=5.0)
    parser.add_argument("--min-adv20", type=float, default=10_000_000.0)
    parser.add_argument("--force-bars", action="store_true")
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--skip-filtered-csv", action="store_true")
    parser.add_argument("--adjusted-bars", dest="adjusted_bars", action="store_true", default=True)
    parser.add_argument("--unadjusted-bars", dest="adjusted_bars", action="store_false")
    parser.add_argument("--allow-oos", action="store_true", help="Required to access dates after 2024-12-31.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir)
    universe_path = input_dir / "daily_universe.parquet"
    if not universe_path.exists():
        raise SystemExit(f"Missing daily_universe.parquet in {input_dir}")
    universe = pd.read_parquet(universe_path)
    universe["date"] = pd.to_datetime(universe["date"])
    if universe["date"].max() > pd.Timestamp("2024-12-31") and not args.allow_oos:
        raise SystemExit("Refusing to open 2025-2026 OOS")

    out_dir = output_dir(input_dir, args)
    out_dir.mkdir(parents=True, exist_ok=True)
    bars, grouped_manifest, ambiguous_ticker_map = load_bars_for_universe(
        universe,
        args.lookback,
        args.force_bars,
        args.progress_every,
        args.adjusted_bars,
        allow_oos=args.allow_oos,
    )
    filtered = apply_filters(universe, bars, args.min_price, args.min_adv20, args.min_obs)
    daily_counts = summarize_daily(filtered)
    reason_summary = summarize_reasons(filtered)
    qa_summary = qa(filtered, bars, ambiguous_ticker_map, args.min_price, args.min_adv20, args.min_obs)

    paths = {
        "filtered_daily_universe": str((out_dir / "filtered_daily_universe.parquet")).replace("\\", "/"),
        "daily_counts": str((out_dir / "daily_counts.parquet")).replace("\\", "/"),
        "reason_summary": str((out_dir / "reason_summary.parquet")).replace("\\", "/"),
        "grouped_daily_manifest": str((out_dir / "grouped_daily_manifest.parquet")).replace("\\", "/"),
        "ambiguous_ticker_security_map": str((out_dir / "ambiguous_ticker_security_map.parquet")).replace("\\", "/"),
        "qa_summary": str((out_dir / "qa_summary.parquet")).replace("\\", "/"),
    }
    filtered.to_parquet(out_dir / "filtered_daily_universe.parquet", index=False)
    daily_counts.to_parquet(out_dir / "daily_counts.parquet", index=False)
    reason_summary.to_parquet(out_dir / "reason_summary.parquet", index=False)
    grouped_manifest.to_parquet(out_dir / "grouped_daily_manifest.parquet", index=False)
    ambiguous_ticker_map.to_parquet(out_dir / "ambiguous_ticker_security_map.parquet", index=False)
    qa_summary.to_parquet(out_dir / "qa_summary.parquet", index=False)

    suffix = (args.tag or input_dir.name).upper().replace("-", "")
    if not args.skip_filtered_csv:
        filtered.to_csv(f"{REPORT_PREFIX}_{suffix}_FILTERED_DAILY_UNIVERSE.csv", index=False)
    daily_counts.to_csv(f"{REPORT_PREFIX}_{suffix}_DAILY_COUNTS.csv", index=False)
    reason_summary.to_csv(f"{REPORT_PREFIX}_{suffix}_REASON_SUMMARY.csv", index=False)
    grouped_manifest.to_csv(f"{REPORT_PREFIX}_{suffix}_GROUPED_DAILY_MANIFEST.csv", index=False)
    ambiguous_ticker_map.to_csv(f"{REPORT_PREFIX}_{suffix}_AMBIGUOUS_TICKER_SECURITY_MAP.csv", index=False)
    qa_summary.to_csv(f"{REPORT_PREFIX}_{suffix}_QA_SUMMARY.csv", index=False)
    write_manifest(out_dir, input_dir, args, paths)

    print(qa_summary.to_string(index=False))
    print(daily_counts.to_string(index=False))
    print(reason_summary.to_string(index=False))
    print("WROTE", out_dir)


if __name__ == "__main__":
    main()
