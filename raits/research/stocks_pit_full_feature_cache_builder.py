from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


PIT_5M_DIR = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
SPY_BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
OUT_DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
OUT_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
OUT_GAP30 = Path("raits/data/cache/stocks_gap_rvol30_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
PART_DIR = Path("raits/data/cache/pit_full_feature_parts_2018_2024_nowarmup")
OUT_QA = Path("STOCKS_PIT_FULL_FEATURE_CACHE_BUILD_2018_2024_NOWARMUP_QA.csv")
MAX_INTRADAY_ADJ_PRICE_RATIO = 2.0


def load_symbol_frame(symbol_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(symbol_dir.glob("*.parquet")):
        frame = pd.read_parquet(path, columns=["open", "close", "volume"])
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def max_adj_ratio_by_date(df: pd.DataFrame) -> pd.Series:
    close = df["close"].astype(float)
    open_ = df["open"].astype(float)
    dates = pd.Series(df.index.normalize(), index=df.index)
    prev_close = close.groupby(dates, sort=False).shift(1)
    ratios = pd.concat(
        [
            close / prev_close,
            prev_close / close,
            open_ / prev_close,
            prev_close / open_,
        ],
        axis=1,
    ).replace([np.inf, -np.inf], np.nan)
    return ratios.max(axis=1).groupby(dates, sort=False).max()


def exact_time_rows(df: pd.DataFrame, hhmm: str, cols: list[str], suffix: str) -> pd.DataFrame:
    time_value = pd.Timestamp(hhmm).time()
    rows = df[df.index.time == time_value].copy()
    if rows.empty:
        out = pd.DataFrame(columns=["date", *[f"{col}_{suffix}" for col in cols]])
        out["date"] = pd.to_datetime(out["date"])
        return out
    rows["date"] = rows.index.normalize()
    rows = rows[["date", *cols]].drop_duplicates("date", keep="last")
    rows = rows.rename(columns={col: f"{col}_{suffix}" for col in cols})
    rows["date"] = pd.to_datetime(rows["date"])
    return rows


def symbol_features(symbol: str, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    qa = {
        "symbol": symbol,
        "bars": int(len(df)),
        "raw_dates": int(pd.Series(df.index.normalize()).nunique()) if not df.empty else 0,
        "daily_rows_pre_filter": 0,
        "daily_rows": 0,
        "intraday_0935_rows": 0,
        "gap30_rows": 0,
    }
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), qa

    ratio_series = max_adj_ratio_by_date(df).rename("max_adj_price_ratio")
    ratio = pd.DataFrame({"date": ratio_series.index, "max_adj_price_ratio": ratio_series.to_numpy()})
    r0930 = exact_time_rows(df, "09:30", ["open", "close", "volume"], "0930")
    r0935 = exact_time_rows(df, "09:35", ["open"], "0935")
    r1000 = exact_time_rows(df, "10:00", ["open"], "1000")
    r1555 = exact_time_rows(df, "15:55", ["close"], "1555")
    vol30 = df[(df.index.time >= pd.Timestamp("09:30").time()) & (df.index.time <= pd.Timestamp("09:55").time())].copy()
    if not vol30.empty:
        vol30["date"] = vol30.index.normalize()
        vol30 = vol30.groupby("date", as_index=False)["volume"].sum().rename(columns={"volume": "vol30"})
    else:
        vol30 = pd.DataFrame(columns=["date", "vol30"])
        vol30["date"] = pd.to_datetime(vol30["date"])

    daily = r0930.merge(r0935, on="date", how="inner").merge(r1555, on="date", how="inner").merge(ratio, on="date", how="left")
    daily["ticker"] = symbol
    daily["date"] = pd.to_datetime(daily["date"])
    qa["daily_rows_pre_filter"] = int(len(daily))
    if daily.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), qa
    daily = daily.sort_values("date").copy()
    daily["prev_open_0930"] = daily["open_0930"].shift(1)
    daily["prev_close_1555"] = daily["close_1555"].shift(1)
    daily["prev_dayret"] = daily["prev_close_1555"] / daily["prev_open_0930"] - 1.0
    daily["gap"] = daily["open_0930"] / daily["prev_close_1555"] - 1.0
    daily["ret_open_to_1555"] = daily["close_1555"] / daily["open_0930"] - 1.0
    daily["ret_0935_to_1555"] = daily["close_1555"] / daily["open_0935"] - 1.0
    daily["ret20_pre"] = daily["prev_close_1555"] / daily["close_1555"].shift(20) - 1.0
    daily["ret60_pre"] = daily["prev_close_1555"] / daily["close_1555"].shift(60) - 1.0
    daily["vol20_pre"] = daily["prev_dayret"].rolling(20).std()
    daily["year"] = daily["date"].dt.year.astype("int32")
    daily = daily.replace([np.inf, -np.inf], np.nan)
    daily = daily.dropna(
        subset=[
            "open_0930",
            "open_0935",
            "close_1555",
            "prev_open_0930",
            "prev_close_1555",
            "prev_dayret",
            "gap",
            "ret20_pre",
            "ret60_pre",
            "vol20_pre",
            "max_adj_price_ratio",
        ]
    )
    daily = daily[
        (daily["open_0930"] > 3.0)
        & (daily["open_0935"] > 3.0)
        & (daily["close_1555"] > 3.0)
        & (daily["prev_open_0930"] > 3.0)
        & (daily["prev_close_1555"] > 3.0)
        & (daily["gap"].abs() <= 0.30)
        & (daily["max_adj_price_ratio"] <= MAX_INTRADAY_ADJ_PRICE_RATIO)
        & (daily["prev_dayret"].abs() <= 0.50)
    ].copy()

    p935 = daily[
        [
            "date",
            "ticker",
            "open_0930",
            "close_0930",
            "volume_0930",
            "open_0935",
            "close_1555",
            "max_adj_price_ratio",
        ]
    ].copy()
    p935["date"] = pd.to_datetime(p935["date"])
    p935["first5_ret"] = p935["close_0930"] / p935["open_0930"] - 1.0
    p935["ret935_eod"] = p935["close_1555"] / p935["open_0935"] - 1.0
    p935["vol930_avg20"] = p935["volume_0930"].shift(1).rolling(20).mean()
    p935["rvol930"] = p935["volume_0930"] / p935["vol930_avg20"]
    p935["year"] = p935["date"].dt.year.astype("int32")
    p935 = p935.dropna()
    p935 = p935[
        (p935["open_0930"] > 3.0)
        & (p935["close_0930"] > 3.0)
        & (p935["open_0935"] > 3.0)
        & (p935["close_1555"] > 3.0)
        & (p935["volume_0930"] > 0.0)
        & (p935["first5_ret"].abs() < 0.5)
        & (p935["max_adj_price_ratio"] <= MAX_INTRADAY_ADJ_PRICE_RATIO)
    ].copy()
    p935 = p935.rename(columns={"open_0930": "open930", "close_0930": "close930", "volume_0930": "vol930", "open_0935": "entry935", "close_1555": "exit1555"})

    gap = daily[["date", "ticker", "open_0930", "close_1555", "prev_close_1555", "max_adj_price_ratio"]].merge(r1000, on="date", how="inner").merge(vol30, on="date", how="left")
    gap["date"] = pd.to_datetime(gap["date"])
    if gap.empty:
        gap = pd.DataFrame(
            columns=[
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
        )
    else:
        gap["ret1000_eod"] = gap["close_1555"] / gap["open_1000"] - 1.0
        gap["vol30_avg20"] = gap["vol30"].shift(1).rolling(20).mean()
        gap["rvol30"] = gap["vol30"] / gap["vol30_avg20"]
        gap["gap"] = gap["open_0930"] / gap["prev_close_1555"] - 1.0
        gap["year"] = gap["date"].dt.year.astype("int32")
        gap = gap.replace([np.inf, -np.inf], np.nan).dropna()
        gap = gap[
            (gap["open_0930"] > 3.0)
            & (gap["open_1000"] > 3.0)
            & (gap["close_1555"] > 3.0)
            & (gap["prev_close_1555"] > 3.0)
            & (gap["vol30"] > 0.0)
            & (gap["gap"].abs() <= 0.30)
            & (gap["max_adj_price_ratio"] <= MAX_INTRADAY_ADJ_PRICE_RATIO)
        ].copy()
        gap = gap.rename(columns={"prev_close_1555": "prev_close", "open_0930": "open930", "open_1000": "entry1000", "close_1555": "exit1555"})

    daily_cols = [
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
        "ret60_pre",
        "vol20_pre",
    ]
    p935_cols = ["date", "ticker", "open930", "close930", "vol930", "entry935", "exit1555", "first5_ret", "ret935_eod", "vol930_avg20", "rvol930", "year"]
    gap_cols = ["date", "ticker", "prev_close", "open930", "entry1000", "exit1555", "vol30", "gap", "ret1000_eod", "vol30_avg20", "rvol30", "year"]

    qa["daily_rows"] = int(len(daily))
    qa["intraday_0935_rows"] = int(len(p935))
    qa["gap30_rows"] = int(len(gap))
    return daily[daily_cols], p935[p935_cols], gap[gap_cols], qa


def spy_prev_dayret() -> pd.DataFrame:
    with SPY_BARS.open("rb") as f:
        bars = pickle.load(f)
    spy = bars["SPY"].sort_index()
    r0930 = exact_time_rows(spy, "09:30", ["open"], "0930")
    r1555 = exact_time_rows(spy, "15:55", ["close"], "1555")
    daily = r0930.merge(r1555, on="date", how="inner").sort_values("date")
    daily["prev_open_0930"] = daily["open_0930"].shift(1)
    daily["prev_close_1555"] = daily["close_1555"].shift(1)
    daily["spy_prev_dayret"] = daily["prev_close_1555"] / daily["prev_open_0930"] - 1.0
    return daily[["date", "spy_prev_dayret"]].dropna()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build broad PIT feature caches from 5-minute parquet files.")
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=250)
    args = parser.parse_args()

    symbol_dirs = sorted([p for p in PIT_5M_DIR.iterdir() if p.is_dir()])
    if args.max_symbols:
        symbol_dirs = symbol_dirs[: args.max_symbols]
    daily_dir = PART_DIR / "daily"
    p935_dir = PART_DIR / "p935"
    gap_dir = PART_DIR / "gap30"
    qa_dir = PART_DIR / "qa"
    for path in [daily_dir, p935_dir, gap_dir, qa_dir]:
        path.mkdir(parents=True, exist_ok=True)
    processed = skipped = 0
    for idx, symbol_dir in enumerate(symbol_dirs, start=1):
        symbol = symbol_dir.name
        daily_part = daily_dir / f"{symbol}.pkl"
        p935_part = p935_dir / f"{symbol}.pkl"
        gap_part = gap_dir / f"{symbol}.pkl"
        qa_part = qa_dir / f"{symbol}.json"
        if daily_part.exists() and p935_part.exists() and gap_part.exists() and qa_part.exists():
            skipped += 1
            if args.progress_every and idx % args.progress_every == 0:
                print(f"symbols={idx} processed={processed} skipped={skipped}", flush=True)
            continue
        frame = load_symbol_frame(symbol_dir)
        daily, p935, gap, qa = symbol_features(symbol, frame)
        daily.to_pickle(daily_part)
        p935.to_pickle(p935_part)
        gap.to_pickle(gap_part)
        qa_part.write_text(json.dumps(qa, sort_keys=True), encoding="utf-8")
        processed += 1
        if args.progress_every and idx % args.progress_every == 0:
            print(f"symbols={idx} processed={processed} skipped={skipped}", flush=True)

    daily_parts = [pd.read_pickle(path) for path in sorted(daily_dir.glob("*.pkl"))]
    p935_parts = [pd.read_pickle(path) for path in sorted(p935_dir.glob("*.pkl"))]
    gap_parts = [pd.read_pickle(path) for path in sorted(gap_dir.glob("*.pkl"))]
    qa_rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(qa_dir.glob("*.json"))]

    daily_all = pd.concat(daily_parts, ignore_index=True) if daily_parts else pd.DataFrame()
    spy = spy_prev_dayret()
    daily_all = daily_all.merge(spy, on="date", how="left").dropna(subset=["spy_prev_dayret"])
    daily_all = daily_all[
        [
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
    ].sort_values(["ticker", "date"]).reset_index(drop=True)
    p935_all = pd.concat(p935_parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True) if p935_parts else pd.DataFrame()
    gap_all = pd.concat(gap_parts, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True) if gap_parts else pd.DataFrame()
    qa = pd.DataFrame(qa_rows)
    qa.loc[len(qa)] = {
        "symbol": "__TOTAL__",
        "bars": int(qa["bars"].sum()),
        "raw_dates": int(qa["raw_dates"].sum()),
        "daily_rows_pre_filter": int(qa["daily_rows_pre_filter"].sum()),
        "daily_rows": int(len(daily_all)),
        "intraday_0935_rows": int(len(p935_all)),
        "gap30_rows": int(len(gap_all)),
    }

    daily_all.to_pickle(OUT_DAILY)
    p935_all.to_pickle(OUT_0935)
    gap_all.to_pickle(OUT_GAP30)
    qa.to_csv(OUT_QA, index=False)
    print("WROTE", OUT_DAILY, len(daily_all))
    print("WROTE", OUT_0935, len(p935_all))
    print("WROTE", OUT_GAP30, len(gap_all))
    print("WROTE", OUT_QA)


if __name__ == "__main__":
    main()
