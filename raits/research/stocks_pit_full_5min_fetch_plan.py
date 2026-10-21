from __future__ import annotations

import argparse
import calendar
import json
from pathlib import Path

import pandas as pd


PIT_FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)
OUT_DIR = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
OUT_CHUNKS = Path("STOCKS_PIT_FULL_5MIN_FETCH_CHUNKS_2026-09-13.csv")
OUT_SYMBOLS = Path("STOCKS_PIT_FULL_5MIN_FETCH_SYMBOLS_2026-09-13.csv")
OUT_MANIFEST = Path("STOCKS_PIT_FULL_5MIN_FETCH_MANIFEST_2026-09-13.json")


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


def load_eligible() -> pd.DataFrame:
    cols = ["date", "ticker", "security_id", "eligible_final", "liquidity_metric_source"]
    df = pd.read_parquet(PIT_FILTER, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str)
    df = df[df["eligible_final"].astype(bool)].copy()
    if df["date"].max() > pd.Timestamp("2024-12-31"):
        raise SystemExit("Refusing to plan dates after 2024-12-31")
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


def output_path(symbol: str, start: pd.Timestamp) -> Path:
    safe = symbol.replace("/", "_")
    return OUT_DIR / safe / f"{safe}_5m_{start.strftime('%Y-%m')}.parquet"


def build_symbol_summary(eligible: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (security_id, symbol), group in eligible.groupby(["security_id", "ticker"], sort=True):
        rows.append(
            {
                "security_id": security_id,
                "symbol": symbol,
                "eligible_days": int(group["date"].nunique()),
                "first_eligible_date": group["date"].min().date(),
                "last_eligible_date": group["date"].max().date(),
                "ticker_fallback_days": int((group["liquidity_metric_source"].fillna("") == "ticker_fallback").sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["eligible_days", "symbol"], ascending=[False, True]).reset_index(drop=True)


def build_chunks(eligible: pd.DataFrame, symbols: pd.DataFrame, max_symbols: int) -> pd.DataFrame:
    allowed_symbols = None
    if max_symbols > 0:
        allowed_symbols = set(symbols.head(max_symbols)["symbol"].astype(str))
    rows = []
    grouped = eligible.groupby(["security_id", "ticker"], sort=True)
    for (security_id, symbol), group in grouped:
        symbol = str(symbol)
        if allowed_symbols is not None and symbol not in allowed_symbols:
            continue
        for chunk_start, chunk_end in month_bounds(group["date"].min(), group["date"].max()):
            mask = group["date"].between(chunk_start, chunk_end)
            if not mask.any():
                continue
            rows.append(
                {
                    "security_id": security_id,
                    "symbol": symbol,
                    "api_ticker": symbol,
                    "start": chunk_start.date(),
                    "end": chunk_end.date(),
                    "eligible_days_in_chunk": int(group.loc[mask, "date"].nunique()),
                    "path": str(output_path(symbol, chunk_start)).replace("\\", "/"),
                }
            )
    return pd.DataFrame(rows).sort_values(["symbol", "start"]).reset_index(drop=True)


def write_manifest(symbols: pd.DataFrame, chunks: pd.DataFrame, eligible: pd.DataFrame, args: argparse.Namespace) -> None:
    payload = {
        "purpose": "full PIT eligible Polygon 5-minute fetch plan for 2018-2024",
        "source_filter": str(PIT_FILTER).replace("\\", "/"),
        "output_dir": str(OUT_DIR).replace("\\", "/"),
        "eligible_symbol_days": int(len(eligible)),
        "symbols_total": int(symbols["symbol"].nunique()) if not symbols.empty else 0,
        "symbols_planned": int(chunks["symbol"].nunique()) if not chunks.empty else 0,
        "chunks": int(len(chunks)),
        "min_start": str(chunks["start"].min()) if not chunks.empty else "",
        "max_end": str(chunks["end"].max()) if not chunks.empty else "",
        "max_symbols": args.max_symbols,
        "outputs": [str(OUT_SYMBOLS).replace("\\", "/"), str(OUT_CHUNKS).replace("\\", "/")],
        "oos_policy": "refuses dates after 2024-12-31",
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
    }
    OUT_MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build full PIT 5-minute fetch plan from eligible daily universe.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Plan only top N symbols by eligible days; 0 means all.")
    args = parser.parse_args()

    eligible = load_eligible()
    symbols = build_symbol_summary(eligible)
    chunks = build_chunks(eligible, symbols, args.max_symbols)
    symbols.to_csv(OUT_SYMBOLS, index=False)
    chunks.to_csv(OUT_CHUNKS, index=False)
    write_manifest(symbols, chunks, eligible, args)

    print("ELIGIBLE_SYMBOL_DAYS", len(eligible))
    print("SYMBOLS_TOTAL", symbols["symbol"].nunique() if not symbols.empty else 0)
    print("SYMBOLS_PLANNED", chunks["symbol"].nunique() if not chunks.empty else 0)
    print("CHUNKS", len(chunks))
    print("DATE_RANGE", chunks["start"].min() if not chunks.empty else "", chunks["end"].max() if not chunks.empty else "")
    print("TOP_SYMBOLS")
    print(symbols.head(25).to_string(index=False))
    print("WROTE", OUT_SYMBOLS, OUT_CHUNKS, OUT_MANIFEST)


if __name__ == "__main__":
    main()
