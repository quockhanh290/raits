from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


PLAN_CSV = Path("STOCKS_PIT_FULL_5MIN_FETCH_CHUNKS_2026-09-13.csv")
FILTERED_UNIVERSE = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)
OUT_DIR = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
OUT_PREFIX = "STOCKS_PIT_FULL_5MIN_COVERAGE_AUDIT_2026-09-13"
INTERVAL = 5
REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume", "timestamp"}


def safe_symbol(symbol: str) -> str:
    return symbol.replace("/", "_")


def output_path(symbol: str, start: pd.Timestamp) -> Path:
    safe = safe_symbol(symbol)
    return OUT_DIR / safe / f"{safe}_{INTERVAL}m_{start.strftime('%Y-%m')}.parquet"


def load_plan() -> tuple[pd.DataFrame, int]:
    plan = pd.read_csv(PLAN_CSV, parse_dates=["start", "end"])
    raw_rows = len(plan)
    plan["output_key"] = plan["symbol"].astype(str) + "|" + plan["start"].dt.strftime("%Y-%m")
    plan = (
        plan.groupby("output_key", as_index=False)
        .agg(
            security_id=("security_id", "first"),
            symbol=("symbol", "first"),
            api_ticker=("api_ticker", "first"),
            start=("start", "min"),
            end=("end", "max"),
            eligible_days_in_chunk=("eligible_days_in_chunk", "sum"),
        )
        .drop(columns=["output_key"])
        .sort_values(["symbol", "start"])
        .reset_index(drop=True)
    )
    plan["path"] = [str(output_path(str(r.symbol), pd.Timestamp(r.start))).replace("\\", "/") for r in plan.itertuples()]
    return plan, raw_rows


def load_expected_dates() -> pd.DataFrame:
    cols = ["date", "ticker", "eligible_final"]
    daily = pd.read_parquet(FILTERED_UNIVERSE, columns=cols)
    daily = daily[daily["eligible_final"].astype(bool)].copy()
    daily = daily.rename(columns={"ticker": "symbol"})
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ym"] = daily["date"].dt.strftime("%Y-%m")
    return daily[["symbol", "ym", "date"]].drop_duplicates()


def audit_file(row: pd.Series, expected_dates: set[pd.Timestamp]) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    symbol = str(row["symbol"])
    start = pd.Timestamp(row["start"])
    end = pd.Timestamp(row["end"])
    path = Path(str(row["path"]))
    rec: dict[str, object] = {
        "symbol": symbol,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "path": str(path).replace("\\", "/"),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "read_ok": False,
        "rows": 0,
        "min_ts": "",
        "max_ts": "",
        "bar_dates": 0,
        "expected_eligible_dates": len(expected_dates),
        "covered_eligible_dates": 0,
        "missing_eligible_dates": 0,
        "off_month_rows": 0,
        "off_rth_rows": 0,
        "duplicate_timestamps": 0,
        "missing_required_columns": "",
        "status": "FAIL",
        "error": "",
    }
    issues: list[dict[str, object]] = []
    missing_rows: list[dict[str, object]] = []
    if not path.exists():
        rec["error"] = "missing file"
        issues.append({**rec, "issue": "missing_file"})
        return rec, issues, missing_rows
    if path.stat().st_size <= 0:
        rec["error"] = "empty file"
        issues.append({**rec, "issue": "empty_file"})
        return rec, issues, missing_rows
    try:
        pf = pq.ParquetFile(path)
        schema_names = set(pf.schema_arrow.names)
        missing_cols = sorted(REQUIRED_COLUMNS - schema_names)
        rec["missing_required_columns"] = ",".join(missing_cols)
        rec["rows"] = int(pf.metadata.num_rows)
        if missing_cols:
            rec["error"] = "missing required columns"
            issues.append({**rec, "issue": "missing_required_columns"})
            return rec, issues, missing_rows
        table = pq.read_table(path, columns=["timestamp"])
        ts = table.column("timestamp").to_pandas()
        ts = pd.to_datetime(ts)
        rec["read_ok"] = True
        if len(ts) != int(rec["rows"]):
            issues.append({**rec, "issue": "metadata_row_count_mismatch"})
        if len(ts) == 0:
            rec["error"] = "zero timestamp rows"
            issues.append({**rec, "issue": "zero_rows"})
            return rec, issues, missing_rows
        dates = ts.dt.normalize()
        times = ts.dt.time
        rec["min_ts"] = str(ts.min())
        rec["max_ts"] = str(ts.max())
        rec["bar_dates"] = int(dates.nunique())
        rec["off_month_rows"] = int(((ts < start) | (ts > (end + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)))).sum())
        rec["off_rth_rows"] = int(((times < pd.Timestamp("09:30").time()) | (times > pd.Timestamp("16:00").time())).sum())
        rec["duplicate_timestamps"] = int(ts.duplicated().sum())
        covered = set(dates.drop_duplicates())
        missing = sorted(expected_dates - covered)
        rec["covered_eligible_dates"] = len(expected_dates - set(missing))
        rec["missing_eligible_dates"] = len(missing)
        for missing_date in missing:
            missing_rows.append(
                {
                    "symbol": symbol,
                    "ym": start.strftime("%Y-%m"),
                    "missing_date": missing_date.strftime("%Y-%m-%d"),
                    "path": str(path).replace("\\", "/"),
                }
            )
        for key in ["off_month_rows", "off_rth_rows", "duplicate_timestamps", "missing_eligible_dates"]:
            if int(rec[key]) > 0:
                issues.append({**rec, "issue": key})
        rec["status"] = "PASS" if not issues else "WARN"
        return rec, issues, missing_rows
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        issues.append({**rec, "issue": "read_error"})
        return rec, issues, missing_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit broad PIT 5-minute parquet coverage.")
    parser.add_argument("--max-files", type=int, default=0, help="Limit files for smoke tests.")
    parser.add_argument("--progress-every", type=int, default=5000)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    plan, raw_plan_rows = load_plan()
    expected = load_expected_dates()
    grouped_expected = {
        (str(symbol), str(ym)): set(group["date"])
        for (symbol, ym), group in expected.groupby(["symbol", "ym"], sort=False)
    }

    selected = plan if args.max_files <= 0 else plan.head(args.max_files).copy()
    rows: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    missing: list[dict[str, object]] = []
    def run_one(item: tuple[int, pd.Series]) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
        _, row = item
        ym = pd.Timestamp(row["start"]).strftime("%Y-%m")
        return audit_file(row, grouped_expected.get((str(row["symbol"]), ym), set()))

    items = list(selected.iterrows())
    workers = max(1, int(args.workers))
    if workers == 1:
        iterator = (run_one(item) for item in items)
        for done, (rec, issue_rows, missing_rows) in enumerate(iterator, start=1):
            rows.append(rec)
            issues.extend(issue_rows)
            missing.extend(missing_rows)
            if args.progress_every and done % args.progress_every == 0:
                print(f"audit_files={done} issues={len(issues)} missing_dates={len(missing)}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_one, item) for item in items]
            for done, future in enumerate(as_completed(futures), start=1):
                rec, issue_rows, missing_rows = future.result()
                rows.append(rec)
                issues.extend(issue_rows)
                missing.extend(missing_rows)
                if args.progress_every and done % args.progress_every == 0:
                    print(f"audit_files={done} issues={len(issues)} missing_dates={len(missing)}", flush=True)

    file_df = pd.DataFrame(rows)
    issue_df = pd.DataFrame(issues)
    missing_df = pd.DataFrame(missing)
    summary = {
        "raw_plan_rows": int(raw_plan_rows),
        "dedup_plan_rows": int(len(plan)),
        "audited_files": int(len(file_df)),
        "files_pass": int((file_df["status"] == "PASS").sum()) if not file_df.empty else 0,
        "files_warn": int((file_df["status"] == "WARN").sum()) if not file_df.empty else 0,
        "files_fail": int((file_df["status"] == "FAIL").sum()) if not file_df.empty else 0,
        "files_exist": int(file_df["exists"].sum()) if not file_df.empty else 0,
        "files_read_ok": int(file_df["read_ok"].sum()) if not file_df.empty else 0,
        "total_rows": int(file_df["rows"].sum()) if not file_df.empty else 0,
        "total_size_bytes": int(file_df["size_bytes"].sum()) if not file_df.empty else 0,
        "symbols": int(plan["symbol"].nunique()),
        "expected_eligible_symbol_days": int(len(expected)),
        "covered_eligible_symbol_days": int(file_df["covered_eligible_dates"].sum()) if not file_df.empty else 0,
        "missing_eligible_symbol_days": int(file_df["missing_eligible_dates"].sum()) if not file_df.empty else 0,
        "off_month_rows": int(file_df["off_month_rows"].sum()) if not file_df.empty else 0,
        "off_rth_rows": int(file_df["off_rth_rows"].sum()) if not file_df.empty else 0,
        "duplicate_timestamps": int(file_df["duplicate_timestamps"].sum()) if not file_df.empty else 0,
        "issue_rows": int(len(issue_df)),
    }

    file_df.to_csv(f"{OUT_PREFIX}_FILES.csv", index=False)
    issue_df.to_csv(f"{OUT_PREFIX}_ISSUES.csv", index=False)
    missing_df.to_csv(f"{OUT_PREFIX}_MISSING_ELIGIBLE_DATES.csv", index=False)
    Path(f"{OUT_PREFIX}_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    pd.DataFrame([summary]).to_csv(f"{OUT_PREFIX}_SUMMARY.csv", index=False)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
