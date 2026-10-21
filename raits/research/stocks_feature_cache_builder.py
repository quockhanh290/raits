from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import stocks_wfo_clean_retest as yday


BARS = Path("raits/data/cache/window_debug_5min.pkl")
DIFF_TOL = 1e-9

CLEAN_DAILY_ORIG = Path("raits/data/cache/stocks_clean_daily_features_2026-09-08.pkl")
INTRADAY_0935_ORIG = Path("raits/data/cache/stocks_intraday_0935_features_2026-09-08.pkl")
GAP_RVOL30_ORIG = Path("raits/data/cache/stocks_gap_rvol30_features_2026-09-08.pkl")

CLEAN_DAILY_REGEN = Path("raits/data/cache/stocks_clean_daily_features_CAUSEQA_2026-09-10.pkl")
INTRADAY_0935_REGEN = Path("raits/data/cache/stocks_intraday_0935_features_CAUSEQA_2026-09-10.pkl")
GAP_RVOL30_REGEN = Path("raits/data/cache/stocks_gap_rvol30_features_CAUSEQA_2026-09-10.pkl")

VERIFY_OUT = Path("STOCKS_FEATURE_CACHE_CAUSEQA_VERIFY_2026-09-10.csv")
MAX_INTRADAY_ADJ_PRICE_RATIO = 2.0

ETF_LIKE = {"SPY", "QQQ", "IWM", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "GLD"}

CLEAN_DAILY_COLUMNS = [
    "date",
    "ticker",
    "open_0930",
    "close_0930",
    "open_0935",
    "close_1555",
    "volume_0930",
    "prev_open_0930",
    "prev_close_1555",
    "prev_dayret",
    "gap",
    "ret_open_to_1555",
    "ret_0935_to_1555",
    "ret20_pre",
    "year",
    "spy_prev_dayret",
    "ret60_pre",
    "vol20_pre",
]

INTRADAY_0935_COLUMNS = [
    "date",
    "ticker",
    "open930",
    "close930",
    "vol930",
    "entry935",
    "exit1555",
    "first5_ret",
    "ret935_eod",
    "vol930_avg20",
    "rvol930",
    "year",
]

GAP_RVOL30_COLUMNS = [
    "date",
    "ticker",
    "prev_close",
    "open930",
    "entry1000",
    "exit1555",
    "vol30",
    "gap",
    "ret1000_eod",
    "vol30_avg20",
    "rvol30",
    "year",
]


def load_bars() -> dict[str, pd.DataFrame]:
    with BARS.open("rb") as f:
        return pickle.load(f)


def build_clean_daily(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    daily, _ = yday.build_daily_table(bars, "skip")
    daily = daily.sort_values(["ticker", "date"]).copy()
    grouped = daily.groupby("ticker", sort=False)
    daily["ret60_pre"] = grouped["prev_close_1555"].transform(lambda s: s / s.shift(60) - 1.0)
    daily["vol20_pre"] = grouped["prev_dayret"].transform(lambda s: s.rolling(20).std())
    return daily.dropna(subset=["ret60_pre", "vol20_pre"])[CLEAN_DAILY_COLUMNS].reset_index(drop=True)


def bar_value(day: pd.DataFrame, date: pd.Timestamp, time_text: str, field: str) -> float:
    ts = pd.Timestamp(f"{date.date()} {time_text}")
    if ts not in day.index:
        return np.nan
    return float(day.loc[ts, field])


def max_intraday_adj_price_ratio(day: pd.DataFrame) -> float:
    opens = day["open"].astype(float).to_numpy()
    closes = day["close"].astype(float).to_numpy()
    if len(closes) < 2:
        return np.nan
    prev_close = closes[:-1]
    curr_close = closes[1:]
    curr_open = opens[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.column_stack(
            [
                curr_close / prev_close,
                prev_close / curr_close,
                curr_open / prev_close,
                prev_close / curr_open,
            ]
        )
    ratios[~np.isfinite(ratios)] = np.nan
    if np.isnan(ratios).all():
        return np.nan
    return float(np.nanmax(ratios))


def intraday_rows(bars: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows_0935 = []
    rows_1000 = []
    for ticker, frame in bars.items():
        if ticker in ETF_LIKE:
            continue
        df = frame.copy()
        df["date"] = pd.to_datetime(df.index.date)
        for date, day in df.groupby("date", sort=True):
            date = pd.Timestamp(date)
            vol30 = float(day.between_time("09:30", "09:55")["volume"].sum())
            max_adj_price_ratio = max_intraday_adj_price_ratio(day)
            rows_0935.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "open930": bar_value(day, date, "09:30", "open"),
                    "close930": bar_value(day, date, "09:30", "close"),
                    "vol930": bar_value(day, date, "09:30", "volume"),
                    "entry935": bar_value(day, date, "09:35", "open"),
                    "exit1555": bar_value(day, date, "15:55", "close"),
                    "max_adj_price_ratio": max_adj_price_ratio,
                }
            )
            rows_1000.append(
                {
                    "date": date,
                    "ticker": ticker,
                    "open930": bar_value(day, date, "09:30", "open"),
                    "entry1000": bar_value(day, date, "10:00", "open"),
                    "exit1555": bar_value(day, date, "15:55", "close"),
                    "vol30": vol30,
                    "max_adj_price_ratio": max_adj_price_ratio,
                }
            )
    return pd.DataFrame(rows_0935), pd.DataFrame(rows_1000)


def build_intraday_0935(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.dropna().sort_values(["ticker", "date"]).copy()
    out["first5_ret"] = out["close930"] / out["open930"] - 1.0
    out["ret935_eod"] = out["exit1555"] / out["entry935"] - 1.0
    out["vol930_avg20"] = out.groupby("ticker")["vol930"].transform(lambda s: s.shift(1).rolling(20).mean())
    out["rvol930"] = out["vol930"] / out["vol930_avg20"]
    out["year"] = out["date"].dt.year.astype("int32")
    out = out.dropna()
    out = out[
        (out["open930"] > 3.0)
        & (out["close930"] > 3.0)
        & (out["entry935"] > 3.0)
        & (out["exit1555"] > 3.0)
        & (out["vol930"] > 0.0)
        & (out["first5_ret"].abs() < 0.5)
        & (out["max_adj_price_ratio"] <= MAX_INTRADAY_ADJ_PRICE_RATIO)
    ].copy()
    return out[INTRADAY_0935_COLUMNS].reset_index(drop=True)


def build_gap_rvol30(rows: pd.DataFrame, rows_0935: pd.DataFrame) -> pd.DataFrame:
    out = rows.dropna().sort_values(["ticker", "date"]).copy()
    out["ret1000_eod"] = out["exit1555"] / out["entry1000"] - 1.0
    out["vol30_avg20"] = out.groupby("ticker")["vol30"].transform(lambda s: s.shift(1).rolling(20).mean())
    prev_close = rows_0935.dropna(subset=["date", "ticker", "exit1555"]).sort_values(["ticker", "date"]).copy()
    prev_close["prev_close"] = prev_close.groupby("ticker")["exit1555"].shift(1)
    prev_close = prev_close[["date", "ticker", "prev_close"]]
    out = out.merge(prev_close, on=["date", "ticker"], how="left")
    out["gap"] = out["open930"] / out["prev_close"] - 1.0
    out["rvol30"] = out["vol30"] / out["vol30_avg20"]
    out["year"] = out["date"].dt.year.astype("int32")
    out = out.dropna()
    out = out[
        (out["date"] > pd.Timestamp("2017-02-01"))
        & (out["open930"] > 3.0)
        & (out["entry1000"] > 3.0)
        & (out["exit1555"] > 3.0)
        & (out["prev_close"] > 3.0)
        & (out["vol30"] > 0.0)
        & (out["gap"].abs() <= 0.30)
        & (out["max_adj_price_ratio"] <= MAX_INTRADAY_ADJ_PRICE_RATIO)
    ].copy()
    return out[GAP_RVOL30_COLUMNS].reset_index(drop=True)


def compare(name: str, original_path: Path, regen: pd.DataFrame, key: list[str]) -> dict[str, object]:
    original = pd.read_pickle(original_path)
    row: dict[str, object] = {
        "cache": name,
        "original": str(original_path),
        "regenRows": len(regen),
        "originalRows": len(original),
        "legacyRowDelta": len(regen) - len(original),
        "sameColumns": list(original.columns) == list(regen.columns),
        "sameKeys": False,
        "sharedRows": None,
        "legacyOnlyRows": None,
        "regenOnlyRows": None,
        "diffColumns": None,
        "maxAbsDiff": None,
        "nonNumericDiffColumns": None,
        "nanPatternDiffColumns": None,
        "diffTolerance": DIFF_TOL,
        "status": "FAIL",
    }
    if not row["sameColumns"]:
        return row
    orig_idx = pd.MultiIndex.from_frame(original[key].drop_duplicates().sort_values(key).reset_index(drop=True))
    reg_idx = pd.MultiIndex.from_frame(regen[key].drop_duplicates().sort_values(key).reset_index(drop=True))
    row["sameKeys"] = orig_idx.equals(reg_idx)
    shared_idx = orig_idx.intersection(reg_idx)
    row["sharedRows"] = len(shared_idx)
    row["legacyOnlyRows"] = len(orig_idx.difference(reg_idx))
    row["regenOnlyRows"] = len(reg_idx.difference(orig_idx))
    orig = original.set_index(key).loc[shared_idx].reset_index()
    reg = regen.set_index(key).loc[shared_idx].reset_index()
    diff_cols = 0
    non_numeric_diff_cols = 0
    nan_pattern_diff_cols = 0
    max_abs = 0.0
    for col in original.columns:
        if col in key:
            continue
        orig_num = pd.to_numeric(orig[col], errors="coerce")
        reg_num = pd.to_numeric(reg[col], errors="coerce")
        orig_numeric = (orig_num.notna() | orig[col].isna()).all()
        reg_numeric = (reg_num.notna() | reg[col].isna()).all()
        if orig_numeric and reg_numeric:
            if not orig_num.isna().equals(reg_num.isna()):
                diff_cols += 1
                nan_pattern_diff_cols += 1
                continue
            diff = (orig_num - reg_num).abs().max()
            diff = 0.0 if pd.isna(diff) else float(diff)
            max_abs = max(max_abs, diff)
            if diff > DIFF_TOL:
                diff_cols += 1
            continue

        same_values = orig[col].fillna("<NA>").astype(str).equals(reg[col].fillna("<NA>").astype(str))
        if not same_values:
            diff_cols += 1
            non_numeric_diff_cols += 1
    row["diffColumns"] = diff_cols
    row["maxAbsDiff"] = max_abs
    row["nonNumericDiffColumns"] = non_numeric_diff_cols
    row["nanPatternDiffColumns"] = nan_pattern_diff_cols
    if row["sameKeys"] and diff_cols == 0:
        row["status"] = "PASS"
    elif diff_cols == 0:
        row["status"] = "CHANGED_VS_LEGACY"
    else:
        row["status"] = "FAIL"
    return row


def main() -> None:
    bars = load_bars()
    daily_base, counters = yday.build_daily_table(bars, "skip")
    clean = build_clean_daily(bars)
    rows_0935, rows_1000 = intraday_rows(bars)
    intraday_0935 = build_intraday_0935(rows_0935)
    gap_rvol30 = build_gap_rvol30(rows_1000, rows_0935)

    clean.to_pickle(CLEAN_DAILY_REGEN)
    intraday_0935.to_pickle(INTRADAY_0935_REGEN)
    gap_rvol30.to_pickle(GAP_RVOL30_REGEN)

    rows = [
        compare("stocks_clean_daily_features", CLEAN_DAILY_ORIG, clean, ["date", "ticker"]),
        compare("stocks_intraday_0935_features", INTRADAY_0935_ORIG, intraday_0935, ["date", "ticker"]),
        compare("stocks_gap_rvol30_features", GAP_RVOL30_ORIG, gap_rvol30, ["date", "ticker"]),
    ]
    out = pd.DataFrame(rows)
    out["bars"] = str(BARS)
    out["rawTickers"] = counters["raw_tickers"]
    out.to_csv(VERIFY_OUT, index=False)
    print(out.to_string(index=False))
    print("WROTE", CLEAN_DAILY_REGEN, INTRADAY_0935_REGEN, GAP_RVOL30_REGEN, VERIFY_OUT)


if __name__ == "__main__":
    main()
