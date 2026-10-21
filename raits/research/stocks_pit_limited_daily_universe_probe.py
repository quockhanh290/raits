from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd


DAILY_PATH = Path("raits/data/cache/research_daily/databento_ohlcv1d.parquet")
CLASS_PATH = Path("raits/data/cache/research_daily/universe_classification.parquet")

OUT_UNIVERSE = Path("STOCKS_PIT_LIMITED_DAILY_UNIVERSE_ROWS_2026-09-12.csv")
OUT_COUNTS = Path("STOCKS_PIT_LIMITED_DAILY_UNIVERSE_COUNTS_2026-09-12.csv")
OUT_FOCUS = Path("STOCKS_PIT_LIMITED_DAILY_UNIVERSE_FOCUS_SYMBOLS_2026-09-12.csv")
OUT_MANIFEST = Path("STOCKS_PIT_LIMITED_DAILY_UNIVERSE_MANIFEST_2026-09-12.json")

START = pd.Timestamp("2023-03-28")
END = pd.Timestamp("2024-12-31")
MIN_PRICE = 3.0
MIN_ADV20 = 10_000_000.0

WINDOWS = {
    "nvda_split_2024_06": (pd.Timestamp("2024-05-20"), pd.Timestamp("2024-06-28")),
    "avgo_split_2024_07": (pd.Timestamp("2024-06-24"), pd.Timestamp("2024-07-26")),
    "year_end_2024_liquidity": (pd.Timestamp("2024-12-02"), pd.Timestamp("2024-12-31")),
}

FOCUS_SYMBOLS = ["NVDA", "AVGO", "META", "GOOGL", "GOOG", "AMZN", "TSLA", "SPY"]


def load_daily() -> pd.DataFrame:
    daily = pd.read_parquet(
        DAILY_PATH,
        columns=["symbol", "date", "open", "high", "low", "close", "volume"],
        filters=[("date", ">=", START), ("date", "<=", END)],
    )
    daily["date"] = pd.to_datetime(daily["date"])
    daily["symbol"] = daily["symbol"].astype(str)
    daily = daily.dropna(subset=["symbol", "date", "open", "close", "volume"])
    daily = daily[(daily["open"] > 0.0) & (daily["close"] > 0.0) & (daily["volume"] >= 0.0)].copy()
    return daily.sort_values(["symbol", "date"]).reset_index(drop=True)


def load_classification() -> pd.DataFrame:
    cls = pd.read_parquet(CLASS_PATH)
    cls["symbol"] = cls["symbol"].astype(str)
    return cls[["symbol", "security_type", "instrument_class", "cfi", "asset"]].drop_duplicates("symbol")


def assign_windows(df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for name, (start, end) in WINDOWS.items():
        part = df[(df["date"] >= start) & (df["date"] <= end)].copy()
        part["probe_window"] = name
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def build_universe_rows() -> pd.DataFrame:
    daily = load_daily()
    cls = load_classification()
    daily = daily.merge(cls, on="symbol", how="left")
    daily["security_type"] = daily["security_type"].fillna("UNKNOWN")
    daily["is_common_stock"] = daily["security_type"].eq("C")

    grouped = daily.groupby("symbol", sort=False)
    daily["prev_close"] = grouped["close"].shift(1)
    daily["prev_dollar"] = daily["prev_close"] * grouped["volume"].shift(1)
    daily["adv20_prior"] = grouped["prev_dollar"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    daily["eligible_price"] = daily["prev_close"] >= MIN_PRICE
    daily["eligible_liquidity"] = daily["adv20_prior"] >= MIN_ADV20
    daily["eligible_final"] = daily["is_common_stock"] & daily["eligible_price"] & daily["eligible_liquidity"]

    daily["security_id_prototype"] = "SYM:" + daily["symbol"]
    daily["reason_excluded"] = ""
    daily.loc[~daily["is_common_stock"], "reason_excluded"] = "not_common_stock"
    daily.loc[daily["is_common_stock"] & ~daily["eligible_price"], "reason_excluded"] = "price_filter"
    daily.loc[
        daily["is_common_stock"] & daily["eligible_price"] & ~daily["eligible_liquidity"],
        "reason_excluded",
    ] = "liquidity_filter"
    daily.loc[daily["eligible_final"], "reason_excluded"] = ""

    rows = assign_windows(daily)
    return rows[
        [
            "probe_window",
            "date",
            "security_id_prototype",
            "symbol",
            "security_type",
            "instrument_class",
            "cfi",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "prev_close",
            "adv20_prior",
            "is_common_stock",
            "eligible_price",
            "eligible_liquidity",
            "eligible_final",
            "reason_excluded",
        ]
    ].reset_index(drop=True)


def daily_counts(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (window, date), group in rows.groupby(["probe_window", "date"], sort=True):
        out.append(
            {
                "probe_window": window,
                "date": date,
                "rows": int(len(group)),
                "symbols": int(group["symbol"].nunique()),
                "commonRows": int(group["is_common_stock"].sum()),
                "priceEligibleRows": int((group["is_common_stock"] & group["eligible_price"]).sum()),
                "liquidityEligibleRows": int((group["is_common_stock"] & group["eligible_liquidity"]).sum()),
                "eligibleFinalRows": int(group["eligible_final"].sum()),
                "medianAdv20PriorEligible": float(group.loc[group["eligible_final"], "adv20_prior"].median())
                if group["eligible_final"].any()
                else np.nan,
                "minAdv20PriorEligible": float(group.loc[group["eligible_final"], "adv20_prior"].min())
                if group["eligible_final"].any()
                else np.nan,
            }
        )
    return pd.DataFrame(out)


def focus_rows(rows: pd.DataFrame) -> pd.DataFrame:
    return rows[rows["symbol"].isin(FOCUS_SYMBOLS)].sort_values(["probe_window", "symbol", "date"]).reset_index(drop=True)


def write_manifest(rows: pd.DataFrame, counts: pd.DataFrame, focus: pd.DataFrame) -> None:
    payload = {
        "purpose": "limited PIT-style full-daily universe + liquidity-filter probe",
        "source_daily": str(DAILY_PATH).replace("\\", "/"),
        "source_classification": str(CLASS_PATH).replace("\\", "/"),
        "date_policy": "hard restricted to 2023-03-28 through 2024-12-31; does not inspect 2025-2026 OOS rows",
        "identity_policy": "prototype only; security_id_prototype is symbol-based and not survivorship-safe",
        "filters": {
            "security_type": "C common stocks only",
            "min_prior_close": MIN_PRICE,
            "min_prior_adv20": MIN_ADV20,
            "adv20_causality": "uses prior close and prior volume only, rolling 20 with min_periods=10",
        },
        "windows": {name: [str(start.date()), str(end.date())] for name, (start, end) in WINDOWS.items()},
        "rows": int(len(rows)),
        "dates": int(rows["date"].nunique()),
        "symbols": int(rows["symbol"].nunique()),
        "eligible_final_symbol_dates": int(rows["eligible_final"].sum()),
        "counts_rows": int(len(counts)),
        "focus_rows": int(len(focus)),
        "outputs": [
            str(OUT_UNIVERSE).replace("\\", "/"),
            str(OUT_COUNTS).replace("\\", "/"),
            str(OUT_FOCUS).replace("\\", "/"),
        ],
    }
    OUT_MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    rows = build_universe_rows()
    counts = daily_counts(rows)
    focus = focus_rows(rows)

    rows.to_csv(OUT_UNIVERSE, index=False)
    counts.to_csv(OUT_COUNTS, index=False)
    focus.to_csv(OUT_FOCUS, index=False)
    write_manifest(rows, counts, focus)

    print("ROWS", len(rows), "DATES", rows["date"].nunique(), "SYMBOLS", rows["symbol"].nunique())
    print("ELIGIBLE_FINAL_SYMBOL_DATES", int(rows["eligible_final"].sum()))
    print(counts.groupby("probe_window")["eligibleFinalRows"].agg(["min", "median", "max"]).to_string())
    print("FOCUS")
    print(
        focus.groupby(["probe_window", "symbol"])
        .agg(rows=("symbol", "size"), eligible=("eligible_final", "sum"), first=("date", "min"), last=("date", "max"))
        .reset_index()
        .to_string(index=False)
    )
    print("WROTE", OUT_UNIVERSE, OUT_COUNTS, OUT_FOCUS, OUT_MANIFEST)


if __name__ == "__main__":
    main()
