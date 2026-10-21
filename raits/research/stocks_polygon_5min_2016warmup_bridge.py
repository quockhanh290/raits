from __future__ import annotations

from pathlib import Path
import pickle

import numpy as np
import pandas as pd


WARMUP_DIR = Path("raits/data/cache/polygon_5min_2016_2017_warmup_62")
BASE_DIR = Path("raits/data/cache/polygon_5min_2018_2024_62")
OUT_PICKLE = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
SUMMARY_OUT = Path("STOCKS_POLYGON_5MIN_2016WARMUP_2018_2024_62_QA_SUMMARY_2026-09-11.csv")
KEYBAR_OUT = Path("STOCKS_POLYGON_5MIN_2016WARMUP_2018_2024_62_QA_KEYBARS_2026-09-11.csv")

ALL_COLS = ["open", "high", "low", "close", "volume", "vwap", "transactions"]


def load_dir(path: Path) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    if not path.exists():
        raise SystemExit(f"Missing Polygon cache directory: {path}")
    for ticker_dir in sorted(p for p in path.iterdir() if p.is_dir() and not p.name.startswith("_")):
        frames = []
        for parquet in sorted(ticker_dir.glob("*.parquet")):
            frame = pd.read_parquet(parquet)
            if not isinstance(frame.index, pd.DatetimeIndex):
                raise ValueError(f"{parquet} index is not DatetimeIndex")
            frames.append(frame)
        if frames:
            out[ticker_dir.name] = pd.concat(frames).sort_index()
    return out


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for col in ALL_COLS:
        if col not in out.columns:
            out[col] = np.nan
    out = out[~out.index.duplicated(keep="last")]
    return out[ALL_COLS].astype(float).sort_index()


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
            "rows": int(len(df)),
            "days": int(len(dates)),
            "minTs": df.index.min(),
            "maxTs": df.index.max(),
            "duplicateIndex": int(df.index.duplicated().sum()),
            "hasBadSort": not df.index.is_monotonic_increasing,
        }
        for tm in ["09:30", "09:35", "10:00", "15:55", "16:00"]:
            count = int((df.index.strftime("%H:%M") == tm).sum())
            row[f"rows_{tm.replace(':', '')}"] = count
            row[f"missingDays_{tm.replace(':', '')}"] = int(len(dates) - count)
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    warmup = load_dir(WARMUP_DIR)
    base = load_dir(BASE_DIR)
    tickers = sorted(set(warmup) | set(base))
    missing_warmup = sorted(set(base) - set(warmup))
    if missing_warmup:
        raise SystemExit(f"Warmup cache is missing tickers: {', '.join(missing_warmup[:20])}")

    combined = {}
    for ticker in tickers:
        parts = []
        if ticker in warmup:
            parts.append(warmup[ticker])
        if ticker in base:
            parts.append(base[ticker])
        combined[ticker] = normalize(pd.concat(parts).sort_index())

    write_pickle_atomic(combined, OUT_PICKLE)
    keybars = keybar_frame(combined)
    summary = pd.DataFrame(
        [
            {
                "source": "polygon_5min_2016warmup_2018_2024_62",
                "tickers": len(combined),
                "rows": int(sum(len(x) for x in combined.values())),
                "minTs": min(x.index.min() for x in combined.values()),
                "maxTs": max(x.index.max() for x in combined.values()),
                "outputPickle": str(OUT_PICKLE).replace("\\", "/"),
                "outputPickleBytes": OUT_PICKLE.stat().st_size,
                "duplicateIndexTickers": int(keybars[keybars["duplicateIndex"].ne(0)].shape[0]),
                "badSortTickers": int(keybars[keybars["hasBadSort"]].shape[0]),
            }
        ]
    )
    summary.to_csv(SUMMARY_OUT, index=False)
    keybars.to_csv(KEYBAR_OUT, index=False)
    print(summary.to_string(index=False))
    print("WROTE", OUT_PICKLE, SUMMARY_OUT, KEYBAR_OUT)


if __name__ == "__main__":
    main()
