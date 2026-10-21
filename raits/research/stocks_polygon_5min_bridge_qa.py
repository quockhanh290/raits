from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pandas as pd


POLYGON_DIR = Path("raits/data/cache/polygon_5min_2018_2024_62")
OLD_PICKLE = Path("raits/data/cache/window_debug_5min.pkl")
OUT_PICKLE = Path("raits/data/cache/window_debug_5min_POLYGON_2018_2024_62.pkl")
SUMMARY_OUT = Path("STOCKS_POLYGON_5MIN_2018_2024_62_QA_SUMMARY_2026-09-11.csv")
KEYBAR_OUT = Path("STOCKS_POLYGON_5MIN_2018_2024_62_QA_KEYBARS_2026-09-11.csv")
OVERLAP_OUT = Path("STOCKS_POLYGON_5MIN_2018_2024_62_QA_OVERLAP_2026-09-11.csv")
SPLIT_OUT = Path("STOCKS_POLYGON_5MIN_2018_2024_62_QA_SPLITS_2026-09-11.csv")
MISSING_OUT = Path("STOCKS_POLYGON_5MIN_2018_2024_62_QA_MISSING_KEYBARS_2026-09-11.csv")

KEY_TIMES = ["09:30", "09:35", "10:00", "15:55", "16:00"]
REQUIRED_TIMES = ["09:30", "09:35", "10:00", "15:55"]
PRICE_COLS = ["open", "high", "low", "close", "vwap"]
ALL_COLS = ["open", "high", "low", "close", "volume", "vwap", "transactions"]
KNOWN_OPEN_HALT_DATES = {pd.Timestamp("2020-03-09"), pd.Timestamp("2020-03-16")}
KNOWN_EARLY_CLOSE_DATES = {
    pd.Timestamp(x)
    for x in [
        "2018-07-03",
        "2018-11-23",
        "2018-12-24",
        "2019-07-03",
        "2019-11-29",
        "2019-12-24",
        "2020-11-27",
        "2020-12-24",
        "2021-11-26",
        "2022-11-25",
        "2023-07-03",
        "2023-11-24",
        "2024-07-03",
        "2024-11-29",
        "2024-12-24",
    ]
}


def load_polygon_cache() -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for ticker_dir in sorted(p for p in POLYGON_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")):
        frames = []
        for path in sorted(ticker_dir.glob("*.parquet")):
            df = pd.read_parquet(path)
            if not isinstance(df.index, pd.DatetimeIndex):
                raise ValueError(f"{path} index is not DatetimeIndex")
            frames.append(df)
        if not frames:
            continue
        ticker = ticker_dir.name
        x = pd.concat(frames).sort_index()
        x = x[~x.index.duplicated(keep="last")]
        for col in ALL_COLS:
            if col not in x.columns:
                x[col] = np.nan
        out[ticker] = x[ALL_COLS].astype(float)
    return out


def write_pickle_atomic(obj: object, path: Path) -> None:
    tmp = path.with_suffix(".pkl.tmp")
    with tmp.open("wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def keybar_frame(cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for ticker, df in cache.items():
        dates = pd.Series(df.index.normalize()).drop_duplicates()
        row = {
            "ticker": ticker,
            "rows": len(df),
            "days": len(dates),
            "minTs": df.index.min(),
            "maxTs": df.index.max(),
            "duplicateIndex": int(df.index.duplicated().sum()),
            "hasBadSort": not df.index.is_monotonic_increasing,
        }
        for tm in KEY_TIMES:
            count = int((df.index.strftime("%H:%M") == tm).sum())
            row[f"rows_{tm.replace(':', '')}"] = count
            row[f"missingDays_{tm.replace(':', '')}"] = int(len(dates) - count)
        rows.append(row)
    return pd.DataFrame(rows)


def missing_keybar_frame(cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for ticker, df in cache.items():
        for date, day in df.groupby(df.index.normalize(), sort=True):
            times = set(day.index.strftime("%H:%M"))
            for tm in REQUIRED_TIMES:
                if tm in times:
                    continue
                date_ts = pd.Timestamp(date)
                expected_reason = ""
                if tm == "09:35" and date_ts in KNOWN_OPEN_HALT_DATES:
                    expected_reason = "known_open_circuit_breaker"
                if tm == "15:55" and date_ts in KNOWN_EARLY_CLOSE_DATES:
                    expected_reason = "known_early_close"
                rows.append(
                    {
                        "ticker": ticker,
                        "date": date_ts.date(),
                        "missingTime": tm,
                        "barsOnDay": len(day),
                        "firstBar": day.index.min(),
                        "lastBar": day.index.max(),
                        "expectedReason": expected_reason,
                        "unexpected": expected_reason == "",
                    }
                )
    return pd.DataFrame(rows)


def daily_key_prices(cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for ticker, df in cache.items():
        for date, day in df.groupby(df.index.normalize(), sort=True):
            def val(tm: str, col: str) -> float:
                ts = pd.Timestamp(f"{pd.Timestamp(date).date()} {tm}")
                if ts in day.index:
                    return float(day.loc[ts, col])
                return np.nan

            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "ticker": ticker,
                    "open930": val("09:30", "open"),
                    "entry935": val("09:35", "open"),
                    "entry1000": val("10:00", "open"),
                    "exit1555": val("15:55", "close"),
                    "close1600": val("16:00", "close"),
                    "volume930": val("09:30", "volume"),
                }
            )
    return pd.DataFrame(rows)


def compare_overlap(old_cache: dict[str, pd.DataFrame], new_cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    old = daily_key_prices(old_cache)
    new = daily_key_prices(new_cache)
    common = old.merge(new, on=["date", "ticker"], suffixes=("_old", "_polygon"))
    rows = []
    for ticker, group in common.groupby("ticker"):
        row = {"ticker": ticker, "sharedDays": len(group), "start": group["date"].min(), "end": group["date"].max()}
        for col in ["open930", "entry935", "entry1000", "exit1555", "close1600"]:
            a = group[f"{col}_old"].astype(float)
            b = group[f"{col}_polygon"].astype(float)
            mask = a.notna() & b.notna() & (a > 0) & (b > 0)
            rel = (b[mask] / a[mask] - 1.0).abs()
            row[f"{col}_n"] = int(mask.sum())
            row[f"{col}_corr"] = float(a[mask].corr(b[mask])) if mask.sum() > 2 else np.nan
            row[f"{col}_medianAbsRelDiff"] = float(rel.median()) if len(rel) else np.nan
            row[f"{col}_p99AbsRelDiff"] = float(rel.quantile(0.99)) if len(rel) else np.nan
            row[f"{col}_maxAbsRelDiff"] = float(rel.max()) if len(rel) else np.nan
        old_ret = group["exit1555_old"] / group["entry935_old"] - 1.0
        new_ret = group["exit1555_polygon"] / group["entry935_polygon"] - 1.0
        mask = old_ret.notna() & new_ret.notna()
        row["ret935_1555_corr"] = float(old_ret[mask].corr(new_ret[mask])) if mask.sum() > 2 else np.nan
        row["ret935_1555_meanOld"] = float(old_ret[mask].mean()) if mask.any() else np.nan
        row["ret935_1555_meanPolygon"] = float(new_ret[mask].mean()) if mask.any() else np.nan
        row["ret935_1555_meanDiff"] = float((new_ret[mask] - old_ret[mask]).mean()) if mask.any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def split_sanity(cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    checks = [
        ("META", "2022-06-08", "2022-06-09"),
        ("GOOGL", "2022-07-15", "2022-07-18"),
        ("AMZN", "2022-06-03", "2022-06-06"),
        ("NVDA", "2024-06-07", "2024-06-10"),
        ("AVGO", "2024-07-12", "2024-07-15"),
        ("TSLA", "2022-08-24", "2022-08-25"),
    ]
    rows = []
    daily = daily_key_prices(cache)
    for ticker, before, after in checks:
        x = daily[daily["ticker"].eq(ticker)].set_index("date")
        before_ts = pd.Timestamp(before)
        after_ts = pd.Timestamp(after)
        b = x.loc[before_ts] if before_ts in x.index else None
        a = x.loc[after_ts] if after_ts in x.index else None
        rows.append(
            {
                "ticker": ticker,
                "before": before,
                "after": after,
                "beforeClose1600": float(b["close1600"]) if b is not None else np.nan,
                "afterOpen930": float(a["open930"]) if a is not None else np.nan,
                "gapAfterSplit": float(a["open930"] / b["close1600"] - 1.0) if b is not None and a is not None else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    polygon_cache = load_polygon_cache()
    write_pickle_atomic(polygon_cache, OUT_PICKLE)

    with OLD_PICKLE.open("rb") as f:
        old_cache = pickle.load(f)

    keybars = keybar_frame(polygon_cache)
    missing = missing_keybar_frame(polygon_cache)
    overlap = compare_overlap(old_cache, polygon_cache)
    split = split_sanity(polygon_cache)

    summary = pd.DataFrame(
        [
            {
                "source": "polygon_5min_2018_2024_62",
                "tickers": len(polygon_cache),
                "rows": int(sum(len(x) for x in polygon_cache.values())),
                "minTs": min(x.index.min() for x in polygon_cache.values()),
                "maxTs": max(x.index.max() for x in polygon_cache.values()),
                "outputPickle": str(OUT_PICKLE).replace("\\", "/"),
                "outputPickleBytes": OUT_PICKLE.stat().st_size,
                "duplicateIndexTickers": int(keybars[keybars["duplicateIndex"].ne(0)].shape[0]),
                "badSortTickers": int(keybars[keybars["hasBadSort"]].shape[0]),
                "requiredMissingRows": int(len(missing)),
                "unexpectedMissingRows": int(missing["unexpected"].sum()) if not missing.empty else 0,
                "medianRet9351555Corr": float(overlap["ret935_1555_corr"].median()),
                "minRet9351555Corr": float(overlap["ret935_1555_corr"].min()),
            }
        ]
    )
    summary.to_csv(SUMMARY_OUT, index=False)
    keybars.to_csv(KEYBAR_OUT, index=False)
    missing.to_csv(MISSING_OUT, index=False)
    overlap.to_csv(OVERLAP_OUT, index=False)
    split.to_csv(SPLIT_OUT, index=False)

    print(summary.to_string(index=False))
    print("WROTE", OUT_PICKLE)
    print("WROTE", SUMMARY_OUT, KEYBAR_OUT, MISSING_OUT, OVERLAP_OUT, SPLIT_OUT)


if __name__ == "__main__":
    main()
