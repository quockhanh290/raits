from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import pandas as pd

import stocks_pit_full_feature_cache_builder as feature_builder


OOS_START = pd.Timestamp("2025-01-02")
OOS_END = pd.Timestamp("2026-09-16")
WARMUP_START = pd.Timestamp("2024-06-01")

OLD_5M_DIR = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
OOS_5M_DIR = Path("raits/data/cache/polygon_5min_pit_full_2025_2026_clean_oos")
SPY_HISTORY = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
SYMBOL_PLAN = Path("STOCKS_PIT_FULL_OOS_5MIN_FETCH_SYMBOLS_2026-09-17.csv")

PART_DIR = Path("raits/data/cache/pit_full_feature_parts_2025_2026_clean_oos")
OUT_DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2025_2026_CLEAN_OOS.pkl")
OUT_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2025_2026_CLEAN_OOS.pkl")
OUT_GAP30 = Path("raits/data/cache/stocks_gap_rvol30_features_PIT_FULL_2025_2026_CLEAN_OOS.pkl")
OUT_QA = Path("STOCKS_PIT_FULL_FEATURE_CACHE_BUILD_2025_2026_CLEAN_OOS_QA.csv")
OUT_MANIFEST = Path("STOCKS_PIT_FULL_FEATURE_CACHE_BUILD_2025_2026_CLEAN_OOS_MANIFEST.json")


def load_months(symbol_dir: Path, start: pd.Timestamp) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    if not symbol_dir.exists():
        return frames
    for path in sorted(symbol_dir.glob("*.parquet")):
        month = path.stem.rsplit("_", maxsplit=1)[-1]
        try:
            month_end = pd.Period(month, freq="M").end_time.normalize()
        except ValueError:
            continue
        if month_end < start:
            continue
        frame = pd.read_parquet(path, columns=["open", "close", "volume"])
        frames.append(frame)
    return frames


def load_symbol_with_warmup(symbol: str) -> pd.DataFrame:
    frames = load_months(OLD_5M_DIR / symbol, WARMUP_START)
    frames.extend(load_months(OOS_5M_DIR / symbol, OOS_START))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out[(out.index.normalize() >= WARMUP_START) & (out.index.normalize() <= OOS_END)]


def load_spy_with_warmup() -> pd.DataFrame:
    with SPY_HISTORY.open("rb") as handle:
        old_spy = pickle.load(handle)["SPY"][["open", "close", "volume"]].copy()
    frames = [old_spy[old_spy.index.normalize() >= WARMUP_START]]
    frames.extend(load_months(OOS_5M_DIR / "SPY", OOS_START))
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out[(out.index.normalize() >= WARMUP_START) & (out.index.normalize() <= OOS_END)]


def spy_prev_dayret(spy: pd.DataFrame) -> pd.DataFrame:
    r0930 = feature_builder.exact_time_rows(spy, "09:30", ["open"], "0930")
    r1555 = feature_builder.exact_time_rows(spy, "15:55", ["close"], "1555")
    daily = r0930.merge(r1555, on="date", how="inner").sort_values("date")
    daily["prev_open_0930"] = daily["open_0930"].shift(1)
    daily["prev_close_1555"] = daily["close_1555"].shift(1)
    daily["spy_prev_dayret"] = daily["prev_close_1555"] / daily["prev_open_0930"] - 1.0
    return daily[["date", "spy_prev_dayret"]].dropna()


def in_oos(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame[(frame["date"] >= OOS_START) & (frame["date"] <= OOS_END)].copy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build frozen 2025-2026 OOS PIT features with 2024 warm-up.")
    parser.add_argument("--progress-every", type=int, default=50)
    parser.add_argument("--rebuild-parts", action="store_true")
    args = parser.parse_args()

    plan = pd.read_csv(SYMBOL_PLAN)
    symbol_col = "ticker" if "ticker" in plan.columns else "symbol"
    symbols = sorted(set(plan[symbol_col].astype(str).str.upper()) - {"SPY"})
    missing_dirs = [symbol for symbol in symbols if not (OOS_5M_DIR / symbol).exists()]
    if missing_dirs:
        raise RuntimeError(f"OOS fetch is incomplete: {len(missing_dirs)} symbol directories absent")

    daily_dir = PART_DIR / "daily"
    p935_dir = PART_DIR / "p935"
    gap_dir = PART_DIR / "gap30"
    qa_dir = PART_DIR / "qa"
    for path in (daily_dir, p935_dir, gap_dir, qa_dir):
        path.mkdir(parents=True, exist_ok=True)

    processed = skipped = 0
    for index, symbol in enumerate(symbols, start=1):
        daily_part = daily_dir / f"{symbol}.pkl"
        p935_part = p935_dir / f"{symbol}.pkl"
        gap_part = gap_dir / f"{symbol}.pkl"
        qa_part = qa_dir / f"{symbol}.json"
        parts = (daily_part, p935_part, gap_part, qa_part)
        if not args.rebuild_parts and all(path.exists() for path in parts):
            skipped += 1
        else:
            frame = load_symbol_with_warmup(symbol)
            daily, p935, gap, qa = feature_builder.symbol_features(symbol, frame)
            daily = in_oos(daily)
            p935 = in_oos(p935)
            gap = in_oos(gap)
            qa.update(
                {
                    "oos_daily_rows": int(len(daily)),
                    "oos_intraday_0935_rows": int(len(p935)),
                    "oos_gap30_rows": int(len(gap)),
                    "raw_min": str(frame.index.min()) if not frame.empty else None,
                    "raw_max": str(frame.index.max()) if not frame.empty else None,
                }
            )
            daily.to_pickle(daily_part)
            p935.to_pickle(p935_part)
            gap.to_pickle(gap_part)
            qa_part.write_text(json.dumps(qa, sort_keys=True), encoding="utf-8")
            processed += 1
        if args.progress_every and index % args.progress_every == 0:
            print(f"symbols={index}/{len(symbols)} processed={processed} skipped={skipped}", flush=True)

    daily_parts = [pd.read_pickle(daily_dir / f"{symbol}.pkl") for symbol in symbols]
    p935_parts = [pd.read_pickle(p935_dir / f"{symbol}.pkl") for symbol in symbols]
    gap_parts = [pd.read_pickle(gap_dir / f"{symbol}.pkl") for symbol in symbols]
    qa_rows = [json.loads((qa_dir / f"{symbol}.json").read_text(encoding="utf-8")) for symbol in symbols]

    daily_all = pd.concat(daily_parts, ignore_index=True)
    p935_all = pd.concat(p935_parts, ignore_index=True)
    gap_all = pd.concat(gap_parts, ignore_index=True)
    spy = spy_prev_dayret(load_spy_with_warmup())
    daily_all = daily_all.merge(spy, on="date", how="left", validate="many_to_one").dropna(subset=["spy_prev_dayret"])
    daily_all = daily_all.sort_values(["ticker", "date"]).reset_index(drop=True)
    p935_all = p935_all.sort_values(["ticker", "date"]).reset_index(drop=True)
    gap_all = gap_all.sort_values(["ticker", "date"]).reset_index(drop=True)

    daily_all.to_pickle(OUT_DAILY)
    p935_all.to_pickle(OUT_0935)
    gap_all.to_pickle(OUT_GAP30)
    qa = pd.DataFrame(qa_rows)
    qa.loc[len(qa)] = {
        "symbol": "__TOTAL__",
        "bars": int(qa["bars"].sum()),
        "raw_dates": int(qa["raw_dates"].sum()),
        "daily_rows": int(len(daily_all)),
        "intraday_0935_rows": int(len(p935_all)),
        "gap30_rows": int(len(gap_all)),
        "oos_daily_rows": int(len(daily_all)),
        "oos_intraday_0935_rows": int(len(p935_all)),
        "oos_gap30_rows": int(len(gap_all)),
    }
    qa.to_csv(OUT_QA, index=False)
    manifest = {
        "script": "raits/research/stocks_pit_full_oos_feature_cache_builder.py",
        "sample": {"warmup_start": str(WARMUP_START.date()), "oos_start": str(OOS_START.date()), "oos_end": str(OOS_END.date())},
        "inputs": [str(OLD_5M_DIR), str(OOS_5M_DIR), str(SPY_HISTORY), str(SYMBOL_PLAN)],
        "outputs": [str(OUT_DAILY), str(OUT_0935), str(OUT_GAP30), str(OUT_QA)],
        "symbols_ex_spy": len(symbols),
        "leakage_control": "2024 raw bars provide only lagged rolling warm-up; every emitted feature row is inside the frozen OOS window.",
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"WROTE {OUT_DAILY} rows={len(daily_all)}", flush=True)
    print(f"WROTE {OUT_0935} rows={len(p935_all)}", flush=True)
    print(f"WROTE {OUT_GAP30} rows={len(gap_all)}", flush=True)


if __name__ == "__main__":
    main()
