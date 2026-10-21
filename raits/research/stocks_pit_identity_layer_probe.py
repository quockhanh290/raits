from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pandas as pd


DAILY_PATH = Path("raits/data/cache/research_daily/databento_ohlcv1d.parquet")
CLASS_PATH = Path("raits/data/cache/research_daily/universe_classification.parquet")

OUT_SECURITY_MASTER = Path("STOCKS_PIT_IDENTITY_PROBE_SECURITY_MASTER_2026-09-12.csv")
OUT_TICKER_HISTORY = Path("STOCKS_PIT_IDENTITY_PROBE_TICKER_HISTORY_2026-09-12.csv")
OUT_DAILY_UNIVERSE = Path("STOCKS_PIT_IDENTITY_PROBE_DAILY_UNIVERSE_2026-09-12.csv")
OUT_QA = Path("STOCKS_PIT_IDENTITY_PROBE_QA_2026-09-12.csv")
OUT_FOCUS = Path("STOCKS_PIT_IDENTITY_PROBE_FOCUS_SYMBOLS_2026-09-12.csv")
OUT_MANIFEST = Path("STOCKS_PIT_IDENTITY_PROBE_MANIFEST_2026-09-12.json")

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
        columns=["instrument_id", "symbol", "date", "open", "high", "low", "close", "volume"],
        filters=[("date", ">=", START), ("date", "<=", END)],
    )
    daily["date"] = pd.to_datetime(daily["date"])
    daily["symbol"] = daily["symbol"].astype(str)
    daily["security_id"] = "DBENTO:" + daily["instrument_id"].astype(str)
    daily = daily.dropna(subset=["instrument_id", "symbol", "date", "open", "close", "volume"])
    daily = daily[(daily["open"] > 0.0) & (daily["close"] > 0.0) & (daily["volume"] >= 0.0)].copy()
    return daily.sort_values(["security_id", "date"]).reset_index(drop=True)


def load_classification() -> pd.DataFrame:
    cls = pd.read_parquet(CLASS_PATH)
    cls["symbol"] = cls["symbol"].astype(str)
    return cls[["symbol", "security_type", "instrument_class", "cfi", "asset"]].drop_duplicates("symbol")


def window_mask(df: pd.DataFrame) -> pd.Series:
    mask = pd.Series(False, index=df.index)
    for start, end in WINDOWS.values():
        mask |= (df["date"] >= start) & (df["date"] <= end)
    return mask


def add_pit_filters(daily: pd.DataFrame) -> pd.DataFrame:
    cls = load_classification()
    out = daily.merge(cls, on="symbol", how="left")
    out["security_type"] = out["security_type"].fillna("UNKNOWN")
    out["is_common_stock"] = out["security_type"].eq("C")

    grouped = out.groupby("security_id", sort=False)
    out["prev_close"] = grouped["close"].shift(1)
    out["prev_volume"] = grouped["volume"].shift(1)
    out["prev_dollar"] = out["prev_close"] * out["prev_volume"]
    out["adv20_prior"] = grouped["prev_dollar"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    out["eligible_price"] = out["prev_close"] >= MIN_PRICE
    out["eligible_liquidity"] = out["adv20_prior"] >= MIN_ADV20
    out["eligible_final"] = out["is_common_stock"] & out["eligible_price"] & out["eligible_liquidity"]
    out["reason_excluded"] = ""
    out.loc[~out["is_common_stock"], "reason_excluded"] = "not_common_stock"
    out.loc[out["is_common_stock"] & ~out["eligible_price"], "reason_excluded"] = "price_filter"
    out.loc[
        out["is_common_stock"] & out["eligible_price"] & ~out["eligible_liquidity"],
        "reason_excluded",
    ] = "liquidity_filter"
    out.loc[out["eligible_final"], "reason_excluded"] = ""
    return out


def build_security_master(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for security_id, group in daily.groupby("security_id", sort=True):
        symbols = sorted(group["symbol"].unique())
        row = {
            "security_id": security_id,
            "instrument_id": int(group["instrument_id"].iloc[0]),
            "canonical_symbol": symbols[-1],
            "symbol_count_in_window": len(symbols),
            "symbols_in_window": ",".join(symbols),
            "first_seen_date": group["date"].min(),
            "last_seen_date": group["date"].max(),
            "security_type": group["security_type"].dropna().mode().iloc[0] if group["security_type"].notna().any() else "UNKNOWN",
            "instrument_class": group["instrument_class"].dropna().mode().iloc[0] if group["instrument_class"].notna().any() else "",
            "cfi": group["cfi"].dropna().mode().iloc[0] if group["cfi"].notna().any() else "",
            "asset": group["asset"].dropna().mode().iloc[0] if group["asset"].notna().any() else "",
            "is_common_stock": bool(group["is_common_stock"].any()),
            "eligible_final_days": int(group["eligible_final"].sum()),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def build_ticker_history(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (security_id, symbol), group in daily.groupby(["security_id", "symbol"], sort=True):
        rows.append(
            {
                "security_id": security_id,
                "instrument_id": int(group["instrument_id"].iloc[0]),
                "ticker": symbol,
                "start_date": group["date"].min(),
                "end_date": group["date"].max(),
                "observed_days": int(group["date"].nunique()),
                "source": "databento_daily_probe",
                "event_type": "observed_symbol_span",
            }
        )
    return pd.DataFrame(rows)


def build_daily_universe(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, (start, end) in WINDOWS.items():
        part = daily[(daily["date"] >= start) & (daily["date"] <= end)].copy()
        part["probe_window"] = name
        rows.append(part)
    out = pd.concat(rows, ignore_index=True)
    return out[
        [
            "probe_window",
            "date",
            "security_id",
            "instrument_id",
            "symbol",
            "security_type",
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


def qa_rows(daily: pd.DataFrame, master: pd.DataFrame, ticker_history: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    symbol_id_counts = daily.groupby("symbol")["security_id"].nunique()
    id_symbol_counts = daily.groupby("security_id")["symbol"].nunique()
    duplicated_daily_keys = int(daily.duplicated(["date", "security_id"]).sum())
    duplicated_universe_keys = int(universe.duplicated(["probe_window", "date", "security_id"]).sum())

    checks = [
        {
            "check": "daily_rows",
            "value": int(len(daily)),
            "status": "INFO",
            "detail": "date-filtered daily rows before probe-window slicing",
        },
        {
            "check": "security_master_rows",
            "value": int(len(master)),
            "status": "INFO",
            "detail": "one row per prototype security_id",
        },
        {
            "check": "ticker_history_rows",
            "value": int(len(ticker_history)),
            "status": "INFO",
            "detail": "one observed symbol span per prototype security_id/ticker",
        },
        {
            "check": "symbols_with_multiple_security_ids",
            "value": int((symbol_id_counts > 1).sum()),
            "status": "PASS" if int((symbol_id_counts > 1).sum()) == 0 else "WARN",
            "detail": "prototype window should not have ambiguous symbol mapping",
        },
        {
            "check": "security_ids_with_multiple_symbols",
            "value": int((id_symbol_counts > 1).sum()),
            "status": "PASS" if int((id_symbol_counts > 1).sum()) == 0 else "WARN",
            "detail": "no ticker changes observed in this limited 2023-2024 window",
        },
        {
            "check": "duplicate_daily_date_security_id",
            "value": duplicated_daily_keys,
            "status": "PASS" if duplicated_daily_keys == 0 else "FAIL",
            "detail": "daily identity key uniqueness",
        },
        {
            "check": "duplicate_universe_window_date_security_id",
            "value": duplicated_universe_keys,
            "status": "PASS" if duplicated_universe_keys == 0 else "FAIL",
            "detail": "probe-window identity key uniqueness",
        },
        {
            "check": "eligible_final_symbol_days",
            "value": int(universe["eligible_final"].sum()),
            "status": "INFO",
            "detail": "PIT-style eligible common stock symbol-days in probe windows",
        },
    ]
    return pd.DataFrame(checks)


def focus_rows(universe: pd.DataFrame) -> pd.DataFrame:
    return universe[universe["symbol"].isin(FOCUS_SYMBOLS)].sort_values(["probe_window", "symbol", "date"]).reset_index(drop=True)


def write_manifest(master: pd.DataFrame, ticker_history: pd.DataFrame, universe: pd.DataFrame, qa: pd.DataFrame) -> None:
    payload = {
        "purpose": "identity-layer probe for limited PIT-style daily universe",
        "source_daily": str(DAILY_PATH).replace("\\", "/"),
        "source_classification": str(CLASS_PATH).replace("\\", "/"),
        "date_policy": "parquet filters restrict to 2023-03-28 through 2024-12-31",
        "identity_policy": "prototype security_id uses Databento instrument_id as DBENTO:{instrument_id}",
        "survivorship_status": "not survivorship-aware yet; no delisted/ticker-change history before source start",
        "filters": {
            "security_type": "C common stocks only",
            "min_prior_close": MIN_PRICE,
            "min_prior_adv20": MIN_ADV20,
            "adv20_causality": "uses prior close and prior volume only, rolling 20 with min_periods=10",
        },
        "windows": {name: [str(start.date()), str(end.date())] for name, (start, end) in WINDOWS.items()},
        "security_master_rows": int(len(master)),
        "ticker_history_rows": int(len(ticker_history)),
        "daily_universe_rows": int(len(universe)),
        "eligible_final_symbol_days": int(universe["eligible_final"].sum()),
        "qa_status_counts": qa["status"].value_counts().to_dict(),
        "outputs": [
            str(OUT_SECURITY_MASTER).replace("\\", "/"),
            str(OUT_TICKER_HISTORY).replace("\\", "/"),
            str(OUT_DAILY_UNIVERSE).replace("\\", "/"),
            str(OUT_QA).replace("\\", "/"),
            str(OUT_FOCUS).replace("\\", "/"),
        ],
    }
    OUT_MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    daily = add_pit_filters(load_daily())
    master = build_security_master(daily)
    ticker_history = build_ticker_history(daily)
    universe = build_daily_universe(daily)
    qa = qa_rows(daily, master, ticker_history, universe)
    focus = focus_rows(universe)

    master.to_csv(OUT_SECURITY_MASTER, index=False)
    ticker_history.to_csv(OUT_TICKER_HISTORY, index=False)
    universe.to_csv(OUT_DAILY_UNIVERSE, index=False)
    qa.to_csv(OUT_QA, index=False)
    focus.to_csv(OUT_FOCUS, index=False)
    write_manifest(master, ticker_history, universe, qa)

    print("MASTER", len(master), "TICKER_HISTORY", len(ticker_history), "UNIVERSE", len(universe))
    print(qa.to_string(index=False))
    print("FOCUS")
    print(
        focus.groupby(["probe_window", "symbol", "security_id"])
        .agg(rows=("symbol", "size"), eligible=("eligible_final", "sum"), first=("date", "min"), last=("date", "max"))
        .reset_index()
        .to_string(index=False)
    )
    print("WROTE", OUT_SECURITY_MASTER, OUT_TICKER_HISTORY, OUT_DAILY_UNIVERSE, OUT_QA, OUT_FOCUS, OUT_MANIFEST)


if __name__ == "__main__":
    main()
