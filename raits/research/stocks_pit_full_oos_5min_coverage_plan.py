from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


START = pd.Timestamp("2025-01-02")
END = pd.Timestamp("2026-09-16")
SYMBOLS_CSV = Path("STOCKS_PIT_FULL_OOS_5MIN_FETCH_SYMBOLS_2026-09-17.csv")
OUT_DIR = Path("raits/data/cache/polygon_5min_pit_full_2025_2026_clean_oos")
PLAN_OUT = Path("STOCKS_PIT_FULL_OOS_5MIN_FULL_COVERAGE_CHUNKS_2026-09-17.csv")
MANIFEST_OUT = Path("STOCKS_PIT_FULL_OOS_5MIN_FULL_COVERAGE_MANIFEST_2026-09-17.json")


def main() -> None:
    symbols_frame = pd.read_csv(SYMBOLS_CSV)
    symbol_col = "symbol" if "symbol" in symbols_frame.columns else "ticker"
    symbols = sorted(symbols_frame[symbol_col].astype(str).str.upper().unique())
    rows = []
    for symbol in symbols:
        for period in pd.period_range(START, END, freq="M"):
            chunk_start = max(START, period.start_time.normalize())
            chunk_end = min(END, period.end_time.normalize())
            eligible_days = len(pd.bdate_range(chunk_start, chunk_end))
            safe = symbol.replace("/", "_")
            rows.append(
                {
                    "security_id": f"OOS_TICKER_{symbol}",
                    "symbol": symbol,
                    "api_ticker": symbol,
                    "start": chunk_start.date(),
                    "end": chunk_end.date(),
                    "eligible_days_in_chunk": eligible_days,
                    "path": str(OUT_DIR / safe / f"{safe}_5m_{period}.parquet").replace("\\", "/"),
                }
            )
    plan = pd.DataFrame(rows)
    plan.to_csv(PLAN_OUT, index=False)
    manifest = {
        "purpose": "Post-first-run input coverage correction: full OOS months for every pre-registered top500-union ticker plus SPY.",
        "reason": "Membership-month-only raw coverage cannot mark or exit a position that remains open after a quarterly membership boundary.",
        "scope_control": "Cross-product of the entire pre-registered symbol union and every OOS month; no ticker is chosen from observed PnL or missing-event output.",
        "symbols_input": str(SYMBOLS_CSV),
        "output_dir": str(OUT_DIR),
        "start": str(START.date()),
        "end": str(END.date()),
        "symbols": len(symbols),
        "chunks": len(plan),
        "output": str(PLAN_OUT),
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
