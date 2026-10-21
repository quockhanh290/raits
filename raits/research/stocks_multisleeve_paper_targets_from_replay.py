from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd


PAIR_VARIANT = "sic_pairs_quarterly_z2_hold10"
CALENDAR_VARIANT = "spy_first5_x25_fin25_cost4"
PAIR_DAILY = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_DAILY.csv")
PAIR_SIGNALS = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_SIGNALS.csv")
PAIR_EVENTS = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_TRADE_EVENTS.csv")
CALENDAR_DAILY = Path("STOCKS_PIT_FULL_TURN_OF_MONTH_COSTAWARE_2026-09-14_DAILY.csv")
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY_FEATURES = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
ELIGIBLE = Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet")
SPY_BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
FLAT_TICKER = "__FLAT__"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def event_timestamp(date: pd.Timestamp, clock: str) -> pd.Timestamp:
    hour, minute = (9, 35) if clock == "0935" else (15, 55)
    return (date.tz_localize("America/New_York") + pd.Timedelta(hours=hour, minutes=minute)).tz_convert("UTC")


def reconstruct_pair_targets() -> tuple[pd.DataFrame, dict[pd.Timestamp, set[str]]]:
    daily = pd.read_csv(PAIR_DAILY, parse_dates=["date"])
    dates = sorted(daily.loc[daily["variant"].eq(PAIR_VARIANT), "date"].drop_duplicates())
    signals = pd.read_csv(PAIR_SIGNALS, parse_dates=["signal_date", "execution_date"])
    signals = signals[signals["frequency"].eq("quarterly")].copy()
    signal_lookup = signals.sort_values(["execution_date", "pair_id", "signal_date"]).drop_duplicates(["execution_date", "pair_id"], keep="last").set_index(["execution_date", "pair_id"])
    events = pd.read_csv(PAIR_EVENTS, parse_dates=["date"])
    events = events[events["variant"].eq(PAIR_VARIANT)].copy()
    events_by_date = {date: group for date, group in events.groupby("date", sort=True)}
    active: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    active_tickers: dict[pd.Timestamp, set[str]] = {}
    for index, date in enumerate(dates):
        day_events = events_by_date.get(date, events.iloc[0:0])
        for event in day_events[day_events["event"].eq("exit")].itertuples(index=False):
            active.pop(event.pair_id, None)
        for event in day_events[day_events["event"].eq("entry")].itertuples(index=False):
            try:
                signal = signal_lookup.loc[(date, event.pair_id)]
            except KeyError as exc:
                raise RuntimeError(f"Missing signal for pair entry {date.date()} {event.pair_id}") from exc
            active[event.pair_id] = {
                "ticker_a": str(signal.ticker_a), "ticker_b": str(signal.ticker_b),
                "direction": -1 if float(signal.zscore) > 0 else 1,
            }
        weights: dict[str, float] = {}
        if active:
            pair_gross = 1.0 / len(active)
            for state in active.values():
                direction = int(state["direction"])
                ticker_a, ticker_b = str(state["ticker_a"]), str(state["ticker_b"])
                weights[ticker_a] = weights.get(ticker_a, 0.0) + direction * pair_gross / 2.0
                weights[ticker_b] = weights.get(ticker_b, 0.0) - direction * pair_gross / 2.0
        previous_date = dates[max(index - 1, 0)]
        signal_time = event_timestamp(previous_date, "1555")
        if weights:
            rows.extend({"effective_date": date, "clock": "0935", "signal_timestamp": signal_time,
                "source": "pairs", "ticker": ticker, "source_target_weight": weight} for ticker, weight in sorted(weights.items()))
        else:
            rows.append({"effective_date": date, "clock": "0935", "signal_timestamp": signal_time,
                "source": "pairs", "ticker": FLAT_TICKER, "source_target_weight": 0.0})
        active_tickers[date] = set(weights)
    return pd.DataFrame(rows), active_tickers


def calendar_targets(dates: list[pd.Timestamp]) -> pd.DataFrame:
    calendar = pd.read_csv(CALENDAR_DAILY, parse_dates=["date"])
    calendar = calendar[calendar["variant"].eq(CALENDAR_VARIANT)].sort_values("date").set_index("date")
    all_dates = list(calendar.index)
    next_date = {date: all_dates[index + 1] for index, date in enumerate(all_dates[:-1])}
    rows = []
    for date in dates:
        following = next_date.get(date)
        exposure = float(calendar.at[following, "exposure"]) if following in calendar.index else 0.0
        rows.append({
            "effective_date": date, "clock": "1555", "signal_timestamp": event_timestamp(date, "1555") - pd.Timedelta(minutes=1),
            "source": "calendar", "ticker": "SPY" if exposure else FLAT_TICKER, "source_target_weight": exposure,
        })
    return pd.DataFrame(rows)


def spy_prices() -> pd.DataFrame:
    with SPY_BARS.open("rb") as handle:
        bars = pickle.load(handle)["SPY"].reset_index()
    timestamp_col = "timestamp" if "timestamp" in bars.columns else "ts"
    bars["timestamp_local"] = pd.to_datetime(bars[timestamp_col])
    bars["effective_date"] = bars["timestamp_local"].dt.normalize()
    bars["clock"] = bars["timestamp_local"].dt.strftime("%H%M")
    return bars[bars["clock"].isin({"0935", "1555"})][["effective_date", "clock", "close"]].rename(columns={"close": "price"})


def build_market(start: pd.Timestamp, end: pd.Timestamp, active_tickers: dict[pd.Timestamp, set[str]]) -> pd.DataFrame:
    intra = pd.read_pickle(INTRADAY_FEATURES)[["date", "ticker", "entry935"]].copy()
    daily = pd.read_pickle(DAILY_FEATURES)[["date", "ticker", "close_1555"]].copy()
    for frame in (intra, daily):
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
    intra = intra[intra["date"].between(start, end)].rename(columns={"entry935": "price"})
    daily = daily[daily["date"].between(start, end)].rename(columns={"close_1555": "price"})
    eligible = pd.read_parquet(
        ELIGIBLE, columns=["date", "ticker", "adv20"],
        filters=[("date", ">=", start.date()), ("date", "<=", end.date()), ("eligible_final", "==", True)],
    )
    eligible["date"] = pd.to_datetime(eligible["date"]).dt.normalize()
    eligible["ticker"] = eligible["ticker"].astype(str).str.upper()
    eligible = eligible.groupby(["date", "ticker"], as_index=False)["adv20"].min()
    spy = spy_prices()
    rows: list[dict[str, object]] = []
    all_dates = sorted(active_tickers)
    for index, date in enumerate(all_dates):
        if date < start or date > end:
            continue
        prior_tickers = active_tickers[all_dates[index - 1]] if index > 0 else set()
        tickers = active_tickers[date].union(prior_tickers)
        for clock, prices in (("0935", intra), ("1555", daily)):
            subset = prices[prices["date"].eq(date) & prices["ticker"].isin(tickers)].merge(
                eligible[eligible["date"].eq(date)], on=["date", "ticker"], how="left", validate="one_to_one"
            )
            timestamp = event_timestamp(date, clock)
            rows.extend({"effective_date": date, "clock": clock, "timestamp": timestamp, "ticker": row.ticker,
                "price": float(row.price), "adv20": float(row.adv20) if pd.notna(row.adv20) else 0.0,
                "borrow_available": True, "asset_type": "stock"} for row in subset.itertuples(index=False) if pd.notna(row.price) and row.price > 0)
            spy_row = spy[(spy["effective_date"].eq(date)) & spy["clock"].eq(clock)]
            if not spy_row.empty:
                rows.append({"effective_date": date, "clock": clock, "timestamp": timestamp, "ticker": "SPY",
                    "price": float(spy_row.iloc[-1]["price"]), "adv20": 1_000_000_000_000.0,
                    "borrow_available": True, "asset_type": "etf"})
    return pd.DataFrame(rows).sort_values(["timestamp", "ticker"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a historical plumbing packet from frozen lead artifacts.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-prefix", default="STOCKS_MULTISLEEVE_FORWARD_PAPER_DRYRUN_INPUT")
    args = parser.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if end > pd.Timestamp("2024-12-31"):
        raise RuntimeError("This replay adapter is historical-only and refuses post-2024 dates")
    if start > end:
        raise ValueError("start must not exceed end")
    pair_targets, active_tickers = reconstruct_pair_targets()
    dates = sorted(date for date in active_tickers if start <= date <= end)
    targets = pd.concat([
        pair_targets[pair_targets["effective_date"].between(start, end)], calendar_targets(dates)
    ], ignore_index=True).sort_values(["effective_date", "clock", "source", "ticker"])
    market = build_market(start, end, {date: active_tickers[date] for date in dates})
    target_path = Path(f"{args.output_prefix}_TARGETS.csv")
    market_path = Path(f"{args.output_prefix}_MARKET.csv")
    targets.to_csv(target_path, index=False)
    market.to_csv(market_path, index=False)
    inputs = [PAIR_DAILY, PAIR_SIGNALS, PAIR_EVENTS, CALENDAR_DAILY, DAILY_FEATURES, INTRADAY_FEATURES, ELIGIBLE, SPY_BARS]
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "start": str(start.date()), "end": str(end.date()), "targets": str(target_path), "market": str(market_path),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in inputs},
        "assumptions": {
            "purpose": "Historical plumbing/ledger test only; not new performance evidence.",
            "stock_borrow_available": True,
            "spy_adv20": 1000000000000.0,
            "pair_target_reconstruction": "Frozen quarterly pair events and signals; equal gross per active pair.",
            "calendar_timing": "15:55 target uses the already-frozen next-session first-five exposure."
        },
        "oos2025_2026Consumed": False,
    }
    Path(f"{args.output_prefix}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print({"targetRows": len(targets), "marketRows": len(market), "dates": len(dates), "targets": str(target_path), "market": str(market_path)})


if __name__ == "__main__":
    main()
