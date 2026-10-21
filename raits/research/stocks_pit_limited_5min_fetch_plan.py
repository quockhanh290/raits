from __future__ import annotations

from pathlib import Path
import calendar
import json

import pandas as pd


COVERAGE = Path("STOCKS_PIT_MARKET_DATA_COVERAGE_PROBE_2026-09-12.csv")
OUT_CHUNKS = Path("STOCKS_PIT_LIMITED_5MIN_FETCH_CHUNKS_2026-09-12.csv")
OUT_SYMBOLS = Path("STOCKS_PIT_LIMITED_5MIN_FETCH_SYMBOLS_2026-09-12.csv")
OUT_MANIFEST = Path("STOCKS_PIT_LIMITED_5MIN_FETCH_MANIFEST_2026-09-12.json")

OUT_DIR = Path("raits/data/cache/polygon_5min_pit_limited_probe_2024")


def month_bounds(start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    months: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    cur = pd.Timestamp(start.year, start.month, 1)
    while cur <= end:
        last = calendar.monthrange(cur.year, cur.month)[1]
        m_start = max(start, cur)
        m_end = min(end, pd.Timestamp(cur.year, cur.month, last))
        months.append((m_start, m_end))
        cur = cur + pd.DateOffset(months=1)
    return months


def load_missing_coverage() -> pd.DataFrame:
    coverage = pd.read_csv(COVERAGE, parse_dates=["date"])
    missing = coverage[coverage["eligible_final"].astype(bool) & ~coverage["has_5m_any"].astype(bool)].copy()
    return missing.sort_values(["symbol", "date"]).reset_index(drop=True)


def build_symbol_summary(missing: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (security_id, symbol), group in missing.groupby(["security_id", "symbol"], sort=True):
        rows.append(
            {
                "security_id": security_id,
                "instrument_id": int(group["instrument_id"].iloc[0]),
                "symbol": symbol,
                "missingEligibleDays": int(group["date"].nunique()),
                "firstMissingDate": group["date"].min().date(),
                "lastMissingDate": group["date"].max().date(),
                "probeWindows": ",".join(sorted(group["probe_window"].unique())),
            }
        )
    return pd.DataFrame(rows).sort_values(["missingEligibleDays", "symbol"], ascending=[False, True]).reset_index(drop=True)


def build_chunks(missing: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (security_id, symbol), group in missing.groupby(["security_id", "symbol"], sort=True):
        dates = group["date"].sort_values()
        start = pd.Timestamp(dates.min())
        end = pd.Timestamp(dates.max())
        for chunk_start, chunk_end in month_bounds(start, end):
            month_mask = (group["date"] >= chunk_start) & (group["date"] <= chunk_end)
            if not month_mask.any():
                continue
            path = OUT_DIR / symbol / f"{symbol}_5m_{chunk_start.strftime('%Y-%m')}.parquet"
            rows.append(
                {
                    "security_id": security_id,
                    "instrument_id": int(group["instrument_id"].iloc[0]),
                    "symbol": symbol,
                    "api_ticker": symbol,
                    "start": chunk_start.date(),
                    "end": chunk_end.date(),
                    "missingEligibleDaysInChunk": int(group.loc[month_mask, "date"].nunique()),
                    "probeWindows": ",".join(sorted(group.loc[month_mask, "probe_window"].unique())),
                    "path": str(path).replace("\\", "/"),
                }
            )
    return pd.DataFrame(rows).sort_values(["symbol", "start"]).reset_index(drop=True)


def write_manifest(symbols: pd.DataFrame, chunks: pd.DataFrame, missing: pd.DataFrame) -> None:
    payload = {
        "purpose": "limited Polygon 5m fetch plan for PIT probe-window eligible symbols missing from current Polygon-62 cache",
        "source_coverage": str(COVERAGE).replace("\\", "/"),
        "output_dir": str(OUT_DIR).replace("\\", "/"),
        "date_policy": "only dates already present in 2024 probe windows; does not request 2025-2026",
        "eligible_missing_symbol_days": int(len(missing)),
        "symbols": int(symbols["symbol"].nunique()) if not symbols.empty else 0,
        "chunks": int(len(chunks)),
        "min_start": str(chunks["start"].min()) if not chunks.empty else "",
        "max_end": str(chunks["end"].max()) if not chunks.empty else "",
        "outputs": [
            str(OUT_SYMBOLS).replace("\\", "/"),
            str(OUT_CHUNKS).replace("\\", "/"),
        ],
    }
    OUT_MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    missing = load_missing_coverage()
    symbols = build_symbol_summary(missing)
    chunks = build_chunks(missing)
    symbols.to_csv(OUT_SYMBOLS, index=False)
    chunks.to_csv(OUT_CHUNKS, index=False)
    write_manifest(symbols, chunks, missing)

    print("MISSING_ELIGIBLE_SYMBOL_DAYS", len(missing))
    print("SYMBOLS", symbols["symbol"].nunique() if not symbols.empty else 0)
    print("CHUNKS", len(chunks))
    print("DATE_RANGE", chunks["start"].min() if not chunks.empty else "", chunks["end"].max() if not chunks.empty else "")
    print("TOP_SYMBOLS")
    print(symbols.head(25).to_string(index=False))
    print("WROTE", OUT_SYMBOLS, OUT_CHUNKS, OUT_MANIFEST)


if __name__ == "__main__":
    main()
