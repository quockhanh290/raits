from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


SOURCE_KEYS = Path("STOCKS_PIT_OPENING_10M15M_PRICE_VOLUME_2026-10-01_EXACT_CLOCK_ROWS.csv")
FETCH_SCRIPT = Path("raits/research/stocks_polygon_open_trades_fetch.py")
CACHE = Path("raits/data/cache/polygon_stock_trades_open_2018_2022")
STATUS = CACHE / "status.csv"
MANIFEST = CACHE / "manifest.json"
AUDIT_CSV = Path("STOCKS_POLYGON_OPEN_TRADES_FETCH_AUDIT_2026-10-01.csv")
AUDIT_JSON = Path("STOCKS_POLYGON_OPEN_TRADES_FETCH_AUDIT_2026-10-01.json")
REQUIRED_COLUMNS = {"sip_timestamp", "price", "size", "exchange", "ticker", "date"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def bounds_ns(date_text: str) -> tuple[int, int]:
    start = pd.Timestamp(f"{date_text} 09:25:00", tz="US/Eastern").tz_convert("UTC")
    end = pd.Timestamp(f"{date_text} 09:40:00", tz="US/Eastern").tz_convert("UTC")
    return int(start.value), int(end.value)


def inspect_file(row: pd.Series) -> dict[str, object]:
    path = Path(str(row["path"]))
    result: dict[str, object] = {
        "date": row["date"], "ticker": row["ticker"], "path": str(path).replace("\\", "/"),
        "exists": path.exists(), "status_rows": int(row["rows"]), "parquet_rows": 0,
        "row_match": False, "schema_ok": False, "bounds_ok": False, "error": "",
    }
    if not path.exists():
        result["error"] = "missing file"
        return result
    try:
        parquet = pq.ParquetFile(path)
        result["parquet_rows"] = parquet.metadata.num_rows
        result["row_match"] = parquet.metadata.num_rows == int(row["rows"])
        names = set(parquet.schema_arrow.names)
        result["schema_ok"] = REQUIRED_COLUMNS.issubset(names)
        sip_index = parquet.schema_arrow.get_field_index("sip_timestamp")
        minima: list[int] = []
        maxima: list[int] = []
        for group_index in range(parquet.metadata.num_row_groups):
            stats = parquet.metadata.row_group(group_index).column(sip_index).statistics
            if stats is None or not stats.has_min_max:
                raise RuntimeError("missing sip_timestamp parquet statistics")
            minima.append(int(stats.min))
            maxima.append(int(stats.max))
        start_ns, end_ns = bounds_ns(str(row["date"]))
        result["min_sip_timestamp"] = min(minima)
        result["max_sip_timestamp"] = max(maxima)
        result["bounds_ok"] = min(minima) >= start_ns and max(maxima) < end_ns
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return result


def main() -> None:
    source = pd.read_csv(SOURCE_KEYS, usecols=["date", "ticker"], dtype=str).drop_duplicates()
    source["ticker"] = source["ticker"].str.upper()
    if source["date"].max() > "2022-12-30":
        raise RuntimeError("Source plan crosses 2022 boundary")

    status = pd.read_csv(STATUS, dtype={"date": str, "ticker": str, "status": str})
    latest = status.drop_duplicates(["date", "ticker"], keep="last")
    duplicates = len(status) - len(latest)
    joined = source.merge(latest, on=["date", "ticker"], how="outer", indicator=True, validate="one_to_one")
    missing_status = int(joined["_merge"].eq("left_only").sum())
    extra_status = int(joined["_merge"].eq("right_only").sum())
    completed = joined[joined["_merge"].eq("both") & joined["status"].eq("OK")].copy()

    with ThreadPoolExecutor(max_workers=16) as executor:
        audit = pd.DataFrame(executor.map(inspect_file, [row for _, row in completed.iterrows()]))
    audit.to_csv(AUDIT_CSV, index=False)

    manifest = json.loads(MANIFEST.read_text(encoding="ascii"))
    summary = {
        "source_ticker_days": len(source),
        "source_tickers": int(source["ticker"].nunique()),
        "source_min_date": source["date"].min(),
        "source_max_date": source["date"].max(),
        "status_rows": len(status),
        "status_duplicate_attempts": duplicates,
        "latest_status_rows": len(latest),
        "latest_ok": int(latest["status"].eq("OK").sum()),
        "latest_empty": int(latest["status"].eq("EMPTY").sum()),
        "latest_error": int(latest["status"].eq("ERROR").sum()),
        "missing_status_keys": missing_status,
        "extra_status_keys": extra_status,
        "files_audited": len(audit),
        "files_missing": int((~audit["exists"]).sum()),
        "files_row_mismatch": int((~audit["row_match"]).sum()),
        "files_bad_schema": int((~audit["schema_ok"]).sum()),
        "files_out_of_bounds": int((~audit["bounds_ok"]).sum()),
        "files_with_error": int(audit["error"].astype(str).ne("").sum()),
        "parquet_rows": int(audit["parquet_rows"].sum()),
        "parquet_bytes": int(sum(Path(path).stat().st_size for path in audit.loc[audit["exists"], "path"])),
        "fetch_script_hash": sha256(FETCH_SCRIPT),
        "manifest_script_hash": manifest["script_hash"],
        "script_hash_match": sha256(FETCH_SCRIPT) == manifest["script_hash"],
        "source_keys_hash": sha256(SOURCE_KEYS),
        "manifest_source_keys_hash": manifest["source_keys_hash"],
        "source_keys_hash_match": sha256(SOURCE_KEYS) == manifest["source_keys_hash"],
        "post2022_consumed": False,
        "pass": False,
    }
    summary["pass"] = bool(
        missing_status == 0 and extra_status == 0 and summary["latest_ok"] == len(source)
        and summary["latest_empty"] == 0 and summary["latest_error"] == 0
        and summary["files_missing"] == 0 and summary["files_row_mismatch"] == 0
        and summary["files_bad_schema"] == 0 and summary["files_out_of_bounds"] == 0
        and summary["files_with_error"] == 0 and summary["script_hash_match"]
        and summary["source_keys_hash_match"] and source["date"].max() <= "2022-12-30"
    )
    AUDIT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="ascii")
    print(json.dumps(summary, indent=2))
    if not summary["pass"]:
        raise SystemExit("Fetch audit failed")


if __name__ == "__main__":
    main()
