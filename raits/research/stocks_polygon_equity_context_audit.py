from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


ROOT = Path("raits/data/cache/external_equity_context/polygon_2018_2024")
FETCHER = Path("raits/research/stocks_polygon_equity_context_fetch.py")
MANIFEST = ROOT / "manifest.json"
STATUS = ROOT / "status.csv"
OUTPUT = Path("STOCKS_POLYGON_EQUITY_CONTEXT_AUDIT_2026-10-03.json")
SPECS = {
    "dividends": ("ex_dividend_date", ["id"]),
    "splits": ("execution_date", ["id"]),
    "short_interest": ("settlement_date", ["ticker", "settlement_date"]),
    "short_volume": ("date", ["ticker", "date"]),
    "edgar_index": ("filing_date", []),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="ascii"))
    if manifest["scriptHash"] != sha256(FETCHER):
        raise RuntimeError("Fetcher hash mismatch")
    status = pd.read_csv(STATUS)
    latest = status.drop_duplicates(["dataset", "month"], keep="last")
    if len(latest) != 420 or not latest["status"].eq("OK").all():
        raise RuntimeError("Incomplete or failed monthly fetch")
    results = []
    for dataset, (date_field, duplicate_key) in SPECS.items():
        files = sorted((ROOT / dataset).glob("*.parquet"))
        if len(files) != 84:
            raise RuntimeError(f"Expected 84 monthly files for {dataset}, got {len(files)}")
        rows = duplicate_rows = out_of_month = 0
        minimum = maximum = None
        bytes_total = 0
        for path in files:
            bytes_total += path.stat().st_size
            schema = set(pq.ParquetFile(path).schema_arrow.names)
            month_text = path.stem[-7:]
            month = pd.Period(month_text, freq="M")
            if not schema:
                continue
            needed = list(dict.fromkeys([date_field, *duplicate_key])) if duplicate_key else list(schema)
            if not set(needed).issubset(schema):
                raise RuntimeError(f"Missing columns in {path}: {sorted(set(needed) - schema)}")
            frame = pd.read_parquet(path, columns=needed)
            rows += len(frame)
            dates = pd.to_datetime(frame[date_field], errors="coerce")
            if dates.isna().any():
                raise RuntimeError(f"Invalid dates in {path}")
            out_of_month += int((dates.dt.to_period("M") != month).sum())
            if len(dates):
                file_min, file_max = dates.min(), dates.max()
                minimum = file_min if minimum is None else min(minimum, file_min)
                maximum = file_max if maximum is None else max(maximum, file_max)
            duplicate_rows += int(frame.duplicated(duplicate_key if duplicate_key else None).sum())
        if out_of_month:
            raise RuntimeError(f"{dataset}: out_of_month={out_of_month}")
        results.append({"dataset": dataset, "files": len(files), "rows": rows,
                        "minDate": str(minimum.date()) if minimum is not None else None,
                        "maxDate": str(maximum.date()) if maximum is not None else None,
                        "duplicates": duplicate_rows, "outOfMonth": out_of_month, "bytes": bytes_total})
    payload = {
        "status": "PASS_WITH_RAW_EDGAR_DUPLICATES", "fetcher": str(FETCHER).replace("\\", "/"), "fetcherHash": sha256(FETCHER),
        "manifestHash": sha256(MANIFEST), "statusHash": sha256(STATUS), "monthlyChunks": len(latest),
        "results": results, "post2024Consumed": False,
        "notes": ["short_volume is empty before 2024-02-06, so it cannot support 2018-2021 development",
                  "EDGAR accession numbers legitimately map to multiple filer/ticker rows; exact duplicate rows are retained in raw cache and must be dropped downstream",
                  "reference condition and exchange tables are covered by the fetch manifest"],
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
