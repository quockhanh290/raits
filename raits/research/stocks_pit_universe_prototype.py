from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


OUT_DIR = Path("raits/data/cache/stocks_survivorship/prototype")
REPORT_PREFIX = "STOCKS_PIT_UNIVERSE_PROTOTYPE_20260912"


def date_range() -> pd.DatetimeIndex:
    return pd.bdate_range("2022-06-06", "2022-11-04")


def security_master() -> pd.DataFrame:
    rows = [
        {
            "security_id": "US000001",
            "company_id": "COMP_AAPL",
            "primary_listing_exchange": "XNAS",
            "security_type": "common_stock",
            "currency": "USD",
            "country": "US",
            "first_trade_date": "1980-12-12",
            "last_trade_date": None,
            "delist_date": None,
            "delist_reason": "",
            "is_etf": False,
            "is_adr": False,
            "prototype_role": "stable_survivor",
        },
        {
            "security_id": "US000002",
            "company_id": "COMP_META",
            "primary_listing_exchange": "XNAS",
            "security_type": "common_stock",
            "currency": "USD",
            "country": "US",
            "first_trade_date": "2012-05-18",
            "last_trade_date": None,
            "delist_date": None,
            "delist_reason": "",
            "is_etf": False,
            "is_adr": False,
            "prototype_role": "ticker_rename_fb_meta",
        },
        {
            "security_id": "US000003",
            "company_id": "COMP_NVDA",
            "primary_listing_exchange": "XNAS",
            "security_type": "common_stock",
            "currency": "USD",
            "country": "US",
            "first_trade_date": "1999-01-22",
            "last_trade_date": None,
            "delist_date": None,
            "delist_reason": "",
            "is_etf": False,
            "is_adr": False,
            "prototype_role": "major_split",
        },
        {
            "security_id": "US000004",
            "company_id": "COMP_TWTR",
            "primary_listing_exchange": "XNYS",
            "security_type": "common_stock",
            "currency": "USD",
            "country": "US",
            "first_trade_date": "2013-11-07",
            "last_trade_date": "2022-10-27",
            "delist_date": "2022-10-28",
            "delist_reason": "acquisition",
            "is_etf": False,
            "is_adr": False,
            "prototype_role": "delisted_acquired",
        },
        {
            "security_id": "US000005",
            "company_id": "COMP_ALPHABET",
            "primary_listing_exchange": "XNAS",
            "security_type": "common_stock_class_a",
            "currency": "USD",
            "country": "US",
            "first_trade_date": "2004-08-19",
            "last_trade_date": None,
            "delist_date": None,
            "delist_reason": "",
            "is_etf": False,
            "is_adr": False,
            "prototype_role": "multi_share_class_a",
        },
        {
            "security_id": "US000006",
            "company_id": "COMP_ALPHABET",
            "primary_listing_exchange": "XNAS",
            "security_type": "common_stock_class_c",
            "currency": "USD",
            "country": "US",
            "first_trade_date": "2014-04-03",
            "last_trade_date": None,
            "delist_date": None,
            "delist_reason": "",
            "is_etf": False,
            "is_adr": False,
            "prototype_role": "multi_share_class_c",
        },
    ]
    out = pd.DataFrame(rows)
    for col in ["first_trade_date", "last_trade_date", "delist_date"]:
        out[col] = pd.to_datetime(out[col])
    return out


def ticker_history() -> pd.DataFrame:
    rows = [
        ("US000001", "AAPL", "1980-12-12", None, "AAPL", "AAPL", "initial_listing"),
        ("US000002", "FB", "2012-05-18", "2022-06-08", "FB", "META", "rename"),
        ("US000002", "META", "2022-06-09", None, "META", "META", "rename"),
        ("US000003", "NVDA", "1999-01-22", None, "NVDA", "NVDA", "initial_listing"),
        ("US000004", "TWTR", "2013-11-07", "2022-10-27", "TWTR", "TWTR", "acquisition_delist"),
        ("US000005", "GOOGL", "2004-08-19", None, "GOOGL", "GOOGL", "share_class"),
        ("US000006", "GOOG", "2014-04-03", None, "GOOG", "GOOG", "share_class"),
    ]
    out = pd.DataFrame(
        rows,
        columns=["security_id", "ticker", "start_date", "end_date", "source_ticker", "canonical_ticker", "event_type"],
    )
    out["start_date"] = pd.to_datetime(out["start_date"])
    out["end_date"] = pd.to_datetime(out["end_date"])
    return out


def corporate_actions() -> pd.DataFrame:
    rows = [
        {
            "security_id": "US000003",
            "ex_date": "2021-07-20",
            "action_type": "split",
            "split_ratio": 4.0,
            "cash_amount": np.nan,
            "adjustment_factor": 0.25,
            "source_timestamp": "2021-07-19 20:00:00",
        },
        {
            "security_id": "US000003",
            "ex_date": "2024-06-10",
            "action_type": "split",
            "split_ratio": 10.0,
            "cash_amount": np.nan,
            "adjustment_factor": 0.10,
            "source_timestamp": "2024-06-07 20:00:00",
        },
        {
            "security_id": "US000004",
            "ex_date": "2022-10-28",
            "action_type": "merger_cash",
            "split_ratio": np.nan,
            "cash_amount": 54.20,
            "adjustment_factor": np.nan,
            "source_timestamp": "2022-10-27 20:00:00",
        },
    ]
    out = pd.DataFrame(rows)
    out["ex_date"] = pd.to_datetime(out["ex_date"])
    out["source_timestamp"] = pd.to_datetime(out["source_timestamp"])
    return out


def active_ticker_for(tickers: pd.DataFrame, security_id: str, date: pd.Timestamp) -> str | None:
    x = tickers[
        tickers["security_id"].eq(security_id)
        & (tickers["start_date"] <= date)
        & (tickers["end_date"].isna() | (tickers["end_date"] >= date))
    ]
    if x.empty:
        return None
    if len(x) != 1:
        raise ValueError(f"ambiguous ticker for {security_id} on {date.date()}")
    return str(x.iloc[0]["ticker"])


def daily_universe(master: pd.DataFrame, tickers: pd.DataFrame) -> pd.DataFrame:
    dates = date_range()
    rows = []
    for date in dates:
        for _, sec in master.iterrows():
            first = pd.Timestamp(sec["first_trade_date"])
            last = pd.Timestamp(sec["last_trade_date"]) if pd.notna(sec["last_trade_date"]) else pd.Timestamp.max
            active = first <= date <= last
            ticker = active_ticker_for(tickers, str(sec["security_id"]), date) if active else None
            eligible_common = str(sec["security_type"]).startswith("common_stock") and not bool(sec["is_etf"])
            eligible_price = active and date >= pd.Timestamp("2022-06-10")
            eligible_liquidity = active and date >= pd.Timestamp("2022-06-13")
            eligible_final = bool(active and eligible_common and eligible_price and eligible_liquidity and ticker)
            reason = ""
            if not active:
                reason = "inactive_or_delisted"
            elif not eligible_common:
                reason = "not_common_stock"
            elif not eligible_price:
                reason = "price_warmup"
            elif not eligible_liquidity:
                reason = "liquidity_warmup"
            rows.append(
                {
                    "date": date,
                    "security_id": sec["security_id"],
                    "ticker": ticker or "",
                    "in_base_universe": bool(active),
                    "eligible_common_stock": bool(eligible_common),
                    "eligible_liquidity": bool(eligible_liquidity),
                    "eligible_price": bool(eligible_price),
                    "eligible_final": eligible_final,
                    "reason_excluded": reason,
                }
            )
    return pd.DataFrame(rows)


def market_data_coverage(universe: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in universe.iterrows():
        active = bool(row["in_base_universe"])
        early_close = pd.Timestamp(row["date"]) == pd.Timestamp("2022-11-25")
        missing_0935 = pd.Timestamp(row["date"]) == pd.Timestamp("2022-06-13") and row["ticker"] == "META"
        rows.append(
            {
                "date": row["date"],
                "security_id": row["security_id"],
                "ticker": row["ticker"],
                "has_daily_bar": active,
                "has_5m_0930": active,
                "has_5m_0935": active and not missing_0935,
                "has_5m_1000": active,
                "has_5m_1555": active and not early_close,
                "has_5m_1600": active and not early_close,
                "missing_reason": "synthetic_missing_0935" if missing_0935 else ("known_early_close" if early_close else ""),
            }
        )
    return pd.DataFrame(rows)


def prototype_features_signals_trades(universe: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    features = universe[universe["eligible_final"]].copy()
    features["ret5_pre_clean"] = features.groupby("security_id").cumcount() / 1000.0 - 0.03
    features["open_0930"] = 50.0 + features.groupby("security_id").cumcount().astype(float)
    features["close_1555"] = features["open_0930"] * (1.0 + features["ret5_pre_clean"] / 10.0)
    features = features[["date", "security_id", "ticker", "ret5_pre_clean", "open_0930", "close_1555"]]

    signals = features.sort_values(["date", "ret5_pre_clean", "security_id"]).groupby("date", group_keys=False).head(3).copy()
    signals["sleeve"] = "prototype_local_xs"
    signals["side"] = 1
    signals["entry_price"] = signals["open_0930"]
    signals["planned_exit_date"] = signals.groupby("security_id")["date"].shift(-4)
    signals = signals.dropna(subset=["planned_exit_date"]).copy()
    signals["signal_id"] = np.arange(1, len(signals) + 1)
    signals = signals[
        ["signal_id", "date", "security_id", "ticker", "sleeve", "side", "entry_price", "planned_exit_date", "ret5_pre_clean"]
    ]

    trades = signals.copy()
    trades["trade_id"] = trades["signal_id"]
    trades["exit_date"] = trades["planned_exit_date"]
    trades["exit_price"] = trades["entry_price"] * (1.0 - trades["ret5_pre_clean"])
    trades["pnl"] = 100.0 * (trades["exit_price"] / trades["entry_price"] - 1.0)
    trades = trades[
        ["trade_id", "signal_id", "date", "exit_date", "security_id", "ticker", "sleeve", "entry_price", "exit_price", "pnl"]
    ]

    concentration = trades.groupby(["security_id", "ticker"], as_index=False).agg(trades=("trade_id", "count"), pnl=("pnl", "sum"))
    return features, signals, trades, concentration


def qa(master: pd.DataFrame, tickers: pd.DataFrame, universe: pd.DataFrame, coverage: pd.DataFrame, features: pd.DataFrame, signals: pd.DataFrame, trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []

    rows.append({"check": "security_id_unique", "status": "PASS" if master["security_id"].is_unique else "FAIL", "detail": ""})

    overlap_failures = []
    for sid, group in tickers.sort_values(["security_id", "start_date"]).groupby("security_id"):
        prev_end = None
        for _, row in group.iterrows():
            if prev_end is not None and pd.notna(prev_end) and row["start_date"] <= prev_end:
                overlap_failures.append(sid)
            prev_end = row["end_date"]
    rows.append(
        {
            "check": "ticker_ranges_non_overlapping_by_security",
            "status": "PASS" if not overlap_failures else "FAIL",
            "detail": ",".join(sorted(set(overlap_failures))),
        }
    )

    active_ticker_dupes = (
        universe[universe["in_base_universe"]]
        .groupby(["date", "ticker"])["security_id"]
        .nunique()
        .reset_index(name="security_ids")
    )
    ticker_ambiguous = active_ticker_dupes[(active_ticker_dupes["ticker"].ne("")) & (active_ticker_dupes["security_ids"] > 1)]
    rows.append(
        {
            "check": "date_ticker_maps_to_one_security",
            "status": "PASS" if ticker_ambiguous.empty else "FAIL",
            "detail": str(len(ticker_ambiguous)),
        }
    )

    twtr_after = universe[(universe["security_id"].eq("US000004")) & (universe["date"] >= pd.Timestamp("2022-10-28"))]
    rows.append(
        {
            "check": "delisted_absent_after_delist",
            "status": "PASS" if not twtr_after["in_base_universe"].any() else "FAIL",
            "detail": "TWTR inactive from 2022-10-28",
        }
    )

    meta_before = universe[(universe["security_id"].eq("US000002")) & (universe["date"].eq(pd.Timestamp("2022-06-08")))]
    meta_after = universe[(universe["security_id"].eq("US000002")) & (universe["date"].eq(pd.Timestamp("2022-06-09")))]
    rows.append(
        {
            "check": "fb_meta_ticker_bridge",
            "status": "PASS"
            if str(meta_before.iloc[0]["ticker"]) == "FB" and str(meta_after.iloc[0]["ticker"]) == "META"
            else "FAIL",
            "detail": "FB valid through 2022-06-08, META from 2022-06-09",
        }
    )

    for name, frame in [("features", features), ("signals", signals), ("trades", trades)]:
        missing = int(frame["security_id"].isna().sum()) if "security_id" in frame else len(frame)
        rows.append({"check": f"{name}_has_security_id", "status": "PASS" if missing == 0 else "FAIL", "detail": str(missing)})

    signal_valid = signals.merge(
        universe[["date", "security_id", "ticker", "eligible_final"]],
        on=["date", "security_id", "ticker"],
        how="left",
    )
    bad_signals = signal_valid[~signal_valid["eligible_final"].fillna(False)]
    rows.append(
        {
            "check": "signals_use_valid_date_ticker_security",
            "status": "PASS" if bad_signals.empty else "FAIL",
            "detail": str(len(bad_signals)),
        }
    )

    missing_keybars = coverage[
        coverage["has_daily_bar"]
        & (~coverage["has_5m_0935"] | ~coverage["has_5m_1555"] | ~coverage["has_5m_1600"])
    ]
    rows.append(
        {
            "check": "missing_keybars_explicit",
            "status": "PASS" if not missing_keybars.empty and missing_keybars["missing_reason"].ne("").all() else "FAIL",
            "detail": str(len(missing_keybars)),
        }
    )

    daily_counts = universe.groupby("date", as_index=False).agg(
        base_universe=("in_base_universe", "sum"),
        eligible_final=("eligible_final", "sum"),
    )
    ticker_events = tickers[tickers["event_type"].ne("initial_listing")].copy()
    return pd.DataFrame(rows), daily_counts, ticker_events


def write_manifest(paths: dict[str, str]) -> None:
    manifest = {
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
        "purpose": "synthetic PIT survivorship-aware universe prototype",
        "no_strategy_result": True,
        "scoring_oos_opened": False,
        "paths": paths,
    }
    manifest_path = OUT_DIR / "manifests" / "source_manifest_20260912.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    master = security_master()
    tickers = ticker_history()
    actions = corporate_actions()
    universe = daily_universe(master, tickers)
    coverage = market_data_coverage(universe)
    features, signals, trades, concentration = prototype_features_signals_trades(universe)
    qa_summary, daily_counts, ticker_events = qa(master, tickers, universe, coverage, features, signals, trades)

    parquet_paths = {
        "security_master": OUT_DIR / "security_master.parquet",
        "ticker_history": OUT_DIR / "ticker_history.parquet",
        "corporate_actions": OUT_DIR / "corporate_actions.parquet",
        "daily_universe": OUT_DIR / "daily_universe.parquet",
        "market_data_coverage": OUT_DIR / "market_data_coverage.parquet",
        "prototype_features": OUT_DIR / "prototype_features.parquet",
        "prototype_signals": OUT_DIR / "prototype_signals.parquet",
        "prototype_trades": OUT_DIR / "prototype_trades.parquet",
        "prototype_concentration": OUT_DIR / "prototype_concentration.parquet",
    }
    frames = {
        "security_master": master,
        "ticker_history": tickers,
        "corporate_actions": actions,
        "daily_universe": universe,
        "market_data_coverage": coverage,
        "prototype_features": features,
        "prototype_signals": signals,
        "prototype_trades": trades,
        "prototype_concentration": concentration,
    }
    for name, path in parquet_paths.items():
        frames[name].to_parquet(path, index=False)

    qa_summary.to_csv(f"{REPORT_PREFIX}_QA_SUMMARY.csv", index=False)
    daily_counts.to_csv(f"{REPORT_PREFIX}_DAILY_COUNTS.csv", index=False)
    ticker_events.to_csv(f"{REPORT_PREFIX}_TICKER_EVENTS.csv", index=False)
    concentration.to_csv(f"{REPORT_PREFIX}_CONCENTRATION.csv", index=False)
    write_manifest({name: str(path).replace("\\", "/") for name, path in parquet_paths.items()})

    print(qa_summary.to_string(index=False))
    print("WROTE", OUT_DIR)
    print("WROTE", f"{REPORT_PREFIX}_QA_SUMMARY.csv")


if __name__ == "__main__":
    main()
