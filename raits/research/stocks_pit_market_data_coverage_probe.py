from __future__ import annotations

from pathlib import Path
import json
import pickle

import pandas as pd


DAILY_UNIVERSE = Path("STOCKS_PIT_IDENTITY_PROBE_DAILY_UNIVERSE_2026-09-12.csv")
FIVE_MIN_PICKLE = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
LIMITED_5M_DIR = Path("raits/data/cache/polygon_5min_pit_limited_probe_2024")

OUT_COVERAGE = Path("STOCKS_PIT_MARKET_DATA_COVERAGE_PROBE_2026-09-12.csv")
OUT_SUMMARY = Path("STOCKS_PIT_MARKET_DATA_COVERAGE_PROBE_SUMMARY_2026-09-12.csv")
OUT_FOCUS = Path("STOCKS_PIT_MARKET_DATA_COVERAGE_PROBE_FOCUS_2026-09-12.csv")
OUT_MANIFEST = Path("STOCKS_PIT_MARKET_DATA_COVERAGE_PROBE_MANIFEST_2026-09-12.json")

KEY_TIMES = ["09:30", "09:35", "10:00", "15:55", "16:00"]
FOCUS_SYMBOLS = ["AMZN", "AVGO", "GOOG", "GOOGL", "META", "NVDA", "TSLA", "SPY"]


def load_daily_universe() -> pd.DataFrame:
    df = pd.read_csv(DAILY_UNIVERSE, parse_dates=["date"])
    return df.sort_values(["probe_window", "date", "security_id"]).reset_index(drop=True)


def keybar_rows_for_frame(symbol: str, frame: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    if frame.empty:
        return rows
    x = frame.copy()
    x["date"] = pd.to_datetime(x.index.date)
    x["time"] = x.index.strftime("%H:%M")
    grouped = x.groupby("date", sort=True)
    for date, day in grouped:
        row = {
            "date": pd.Timestamp(date),
            "symbol": symbol,
            "has_5m_any": True,
            "first_5m_bar": day.index.min(),
            "last_5m_bar": day.index.max(),
            "bars_5m": int(len(day)),
        }
        times = set(day["time"])
        for key_time in KEY_TIMES:
            row[f"has_5m_{key_time.replace(':', '')}"] = key_time in times
        rows.append(row)
    return rows


def five_min_keybar_table() -> pd.DataFrame:
    rows = []
    with FIVE_MIN_PICKLE.open("rb") as f:
        bars: dict[str, pd.DataFrame] = pickle.load(f)

    for symbol, frame in bars.items():
        rows.extend(keybar_rows_for_frame(symbol, frame))

    if LIMITED_5M_DIR.exists():
        for ticker_dir in sorted(p for p in LIMITED_5M_DIR.iterdir() if p.is_dir()):
            frames = []
            for path in sorted(ticker_dir.glob("*.parquet")):
                frame = pd.read_parquet(path)
                if not isinstance(frame.index, pd.DatetimeIndex):
                    continue
                frames.append(frame)
            if frames:
                rows.extend(keybar_rows_for_frame(ticker_dir.name, pd.concat(frames).sort_index()))

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"], keep="last").reset_index(drop=True)


def classify_missing(row: pd.Series) -> str:
    if not row["has_daily_bar"]:
        return "no_daily_bar"
    if not row["has_5m_any"]:
        return "no_5m_cache_for_symbol_date"
    missing = [key_time for key_time in KEY_TIMES if not row[f"has_5m_{key_time.replace(':', '')}"]]
    if not missing:
        return "complete"
    if missing == ["16:00"]:
        return "missing_1600_only"
    return "missing_keybars:" + ",".join(missing)


def build_coverage() -> pd.DataFrame:
    daily = load_daily_universe()
    keybars = five_min_keybar_table()

    coverage = daily.merge(keybars, on=["date", "symbol"], how="left")
    coverage["has_daily_bar"] = True
    coverage["has_5m_any"] = coverage["has_5m_any"].eq(True)
    coverage["bars_5m"] = coverage["bars_5m"].fillna(0).astype(int)
    for key_time in KEY_TIMES:
        col = f"has_5m_{key_time.replace(':', '')}"
        coverage[col] = coverage[col].eq(True)
    coverage["missing_reason"] = coverage.apply(classify_missing, axis=1)

    cols = [
        "probe_window",
        "date",
        "security_id",
        "instrument_id",
        "symbol",
        "security_type",
        "eligible_final",
        "has_daily_bar",
        "has_5m_any",
        "bars_5m",
        "first_5m_bar",
        "last_5m_bar",
        *[f"has_5m_{key_time.replace(':', '')}" for key_time in KEY_TIMES],
        "missing_reason",
    ]
    return coverage[cols].reset_index(drop=True)


def build_summary(coverage: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (window, date), group in coverage.groupby(["probe_window", "date"], sort=True):
        eligible = group[group["eligible_final"].astype(bool)]
        row = {
            "probe_window": window,
            "date": date,
            "rows": int(len(group)),
            "eligibleFinalRows": int(len(eligible)),
            "rowsWithAny5m": int(group["has_5m_any"].sum()),
            "eligibleRowsWithAny5m": int(eligible["has_5m_any"].sum()),
        }
        for key_time in KEY_TIMES:
            col = f"has_5m_{key_time.replace(':', '')}"
            row[f"eligibleRowsWith{key_time.replace(':', '')}"] = int(eligible[col].sum())
        rows.append(row)
    return pd.DataFrame(rows)


def focus_rows(coverage: pd.DataFrame) -> pd.DataFrame:
    return coverage[coverage["symbol"].isin(FOCUS_SYMBOLS)].sort_values(["probe_window", "symbol", "date"]).reset_index(drop=True)


def write_manifest(coverage: pd.DataFrame, summary: pd.DataFrame, focus: pd.DataFrame) -> None:
    payload = {
        "purpose": "limited market-data coverage probe keyed by prototype security_id",
        "daily_universe": str(DAILY_UNIVERSE).replace("\\", "/"),
        "five_min_pickle": str(FIVE_MIN_PICKLE).replace("\\", "/"),
        "limited_5m_dir": str(LIMITED_5M_DIR).replace("\\", "/"),
        "coverage_scope": "daily universe is broad 2023-2024 probe; 5m coverage combines current Polygon-62 + SPY and limited PIT probe fetch",
        "not_survivorship_aware": True,
        "rows": int(len(coverage)),
        "dates": int(coverage["date"].nunique()),
        "symbols": int(coverage["symbol"].nunique()),
        "rows_with_any_5m": int(coverage["has_5m_any"].sum()),
        "eligible_final_rows": int(coverage["eligible_final"].sum()),
        "eligible_final_rows_with_any_5m": int(coverage[coverage["eligible_final"].astype(bool)]["has_5m_any"].sum()),
        "summary_rows": int(len(summary)),
        "focus_rows": int(len(focus)),
        "key_times": KEY_TIMES,
        "outputs": [
            str(OUT_COVERAGE).replace("\\", "/"),
            str(OUT_SUMMARY).replace("\\", "/"),
            str(OUT_FOCUS).replace("\\", "/"),
        ],
    }
    OUT_MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    coverage = build_coverage()
    summary = build_summary(coverage)
    focus = focus_rows(coverage)

    coverage.to_csv(OUT_COVERAGE, index=False)
    summary.to_csv(OUT_SUMMARY, index=False)
    focus.to_csv(OUT_FOCUS, index=False)
    write_manifest(coverage, summary, focus)

    print("COVERAGE_ROWS", len(coverage), "DATES", coverage["date"].nunique(), "SYMBOLS", coverage["symbol"].nunique())
    print("ROWS_WITH_ANY_5M", int(coverage["has_5m_any"].sum()))
    print("ELIGIBLE_FINAL_ROWS", int(coverage["eligible_final"].sum()))
    print("ELIGIBLE_FINAL_ROWS_WITH_ANY_5M", int(coverage[coverage["eligible_final"].astype(bool)]["has_5m_any"].sum()))
    print(summary.groupby("probe_window")[["eligibleFinalRows", "eligibleRowsWithAny5m"]].agg(["min", "median", "max"]).to_string())
    print("FOCUS")
    print(
        focus.groupby(["probe_window", "symbol", "security_id"])
        .agg(rows=("symbol", "size"), any5m=("has_5m_any", "sum"), eligible=("eligible_final", "sum"))
        .reset_index()
        .to_string(index=False)
    )
    print("WROTE", OUT_COVERAGE, OUT_SUMMARY, OUT_FOCUS, OUT_MANIFEST)


if __name__ == "__main__":
    main()
