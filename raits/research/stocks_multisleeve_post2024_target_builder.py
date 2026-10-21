from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_lead_clean_oos_replay as oos
import stocks_pit_full_rolling_sic_pairs as pairs


START = pd.Timestamp("2025-01-02")
END = pd.Timestamp("2026-09-16")
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


def pair_targets(
    daily: pd.DataFrame, intra: pd.DataFrame, caps: pd.DataFrame, sessions: list[pd.Timestamp]
) -> tuple[pd.DataFrame, dict[pd.Timestamp, set[str]], pd.DataFrame, pd.DataFrame]:
    raw = oos.make_pair_raw(daily, intra)
    formations = pairs.form_pairs(raw, caps, "quarterly")
    signals = pairs.build_signals(raw, formations, "quarterly")
    signals = signals[signals["execution_date"].between(START, END)].copy()
    decision_by_date = {date: group for date, group in signals.groupby("execution_date", sort=True)}
    all_raw_dates = sorted(raw["date"].drop_duplicates())
    previous_date = {date: all_raw_dates[index - 1] for index, date in enumerate(all_raw_dates) if index > 0}
    active: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    active_tickers: dict[pd.Timestamp, set[str]] = {}
    empty = signals.iloc[0:0]
    for day_index, date in enumerate(sessions):
        decisions = decision_by_date.get(date, empty)
        decision_map = {row.pair_id: row for row in decisions.itertuples(index=False)}
        for pair_id, state in list(active.items()):
            signal = decision_map.get(pair_id)
            held_days = day_index - int(state["entry_index"])
            direction = int(state["direction"])
            reason = None
            if signal is None:
                reason = "formation_drop"
            elif abs(float(signal.zscore)) <= pairs.EXIT_Z or direction * float(signal.zscore) >= 0:
                reason = "mean_revert"
            elif held_days >= 10:
                reason = "timeout"
            if reason:
                event_rows.append({"date": date, "pair_id": pair_id, "event": "exit", "reason": reason,
                    "zscore": float(signal.zscore) if signal else np.nan})
                del active[pair_id]
        slots = pairs.MAX_ACTIVE_PAIRS - len(active)
        if slots > 0 and not decisions.empty:
            candidates = decisions[~decisions["pair_id"].isin(active)].copy()
            candidates = candidates[candidates["zscore"].abs() >= pairs.ENTRY_Z]
            candidates["abs_z"] = candidates["zscore"].abs()
            candidates = candidates.sort_values(["abs_z", "pair_id"], ascending=[False, True]).head(slots)
            for signal in candidates.itertuples(index=False):
                direction = -1 if signal.zscore > 0 else 1
                active[signal.pair_id] = {
                    "ticker_a": signal.ticker_a, "ticker_b": signal.ticker_b,
                    "direction": direction, "entry_index": day_index,
                }
                event_rows.append({"date": date, "pair_id": signal.pair_id, "event": "entry", "reason": "z_entry", "zscore": float(signal.zscore)})
        weights: dict[str, float] = {}
        if active:
            pair_gross = 1.0 / len(active)
            for state in active.values():
                direction = int(state["direction"])
                ticker_a, ticker_b = str(state["ticker_a"]), str(state["ticker_b"])
                weights[ticker_a] = weights.get(ticker_a, 0.0) + direction * pair_gross / 2.0
                weights[ticker_b] = weights.get(ticker_b, 0.0) - direction * pair_gross / 2.0
        signal_date = previous_date.get(date, date)
        signal_time = event_timestamp(signal_date, "1555")
        if weights:
            rows.extend({"effective_date": date, "clock": "0935", "signal_timestamp": signal_time,
                "source": "pairs", "ticker": ticker, "source_target_weight": weight} for ticker, weight in sorted(weights.items()))
        else:
            rows.append({"effective_date": date, "clock": "0935", "signal_timestamp": signal_time,
                "source": "pairs", "ticker": FLAT_TICKER, "source_target_weight": 0.0})
        active_tickers[date] = set(weights)
    return pd.DataFrame(rows), active_tickers, formations, pd.DataFrame(event_rows)


def calendar_targets(sessions: list[pd.Timestamp]) -> pd.DataFrame:
    session_frame = pd.DataFrame({"date": sessions})
    session_frame["month"] = session_frame["date"].dt.to_period("M")
    session_frame["td_from_start"] = session_frame.groupby("month").cumcount() + 1
    td_lookup = session_frame.set_index("date")["td_from_start"]
    rows = []
    for index, date in enumerate(sessions):
        following = sessions[index + 1] if index + 1 < len(sessions) else None
        exposure = 2.5 if following is not None and int(td_lookup.loc[following]) <= 5 else 0.0
        rows.append({"effective_date": date, "clock": "1555",
            "signal_timestamp": event_timestamp(date, "1555") - pd.Timedelta(minutes=1),
            "source": "calendar", "ticker": "SPY" if exposure else FLAT_TICKER,
            "source_target_weight": exposure})
    return pd.DataFrame(rows)


def market_packet(
    sessions: list[pd.Timestamp], active_tickers: dict[pd.Timestamp, set[str]]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    all_tickers = set().union(*(active_tickers[date] for date in sessions)).union({"SPY"})
    exact935, exact1555, _, _, coverage = oos.price_maps(all_tickers, set(sessions))
    eligible = pd.read_parquet(
        oos.PIT_FILTER, columns=["date", "ticker", "adv20"],
        filters=[("date", ">=", START.date()), ("date", "<=", END.date())],
    )
    eligible["date"] = pd.to_datetime(eligible["date"]).dt.normalize()
    eligible["ticker"] = eligible["ticker"].astype(str).str.upper()
    adv = eligible.groupby(["date", "ticker"])["adv20"].min().to_dict()
    rows = []
    # Include every potential constituent at every clock so the execution runner can
    # keep marking and eventually close a residual position after a missing exact bar.
    required = all_tickers
    for date in sessions:
        for clock, prices in (("0935", exact935.get(date, pd.Series(dtype=float))), ("1555", exact1555.get(date, pd.Series(dtype=float)))):
            timestamp = event_timestamp(date, clock)
            for ticker in sorted(required):
                if ticker not in prices.index or not np.isfinite(float(prices[ticker])):
                    continue
                rows.append({"effective_date": date, "clock": clock, "timestamp": timestamp, "ticker": ticker,
                    "price": float(prices[ticker]), "adv20": 1_000_000_000_000.0 if ticker == "SPY" else float(adv.get((date, ticker), 0.0)),
                    "borrow_available": True, "asset_type": "etf" if ticker == "SPY" else "stock"})
    return pd.DataFrame(rows).sort_values(["timestamp", "ticker"]), coverage


def main() -> None:
    parser = argparse.ArgumentParser(description="Build approved touched post-2024 implementation-replay packets for the frozen 75/25 lead.")
    parser.add_argument("--output-prefix", default="STOCKS_MULTISLEEVE_POST2024_IMPLEMENTATION_REPLAY_INPUT")
    args = parser.parse_args()
    daily, intra = oos.load_feature_panel()
    caps = oos.load_caps()
    _, spy, _ = oos.spy_frames()
    sessions = sorted(spy.loc[spy["date"].between(START, END), "date"].drop_duplicates())
    pair_rows, active_tickers, formations, pair_events = pair_targets(daily, intra, caps, sessions)
    targets = pd.concat([pair_rows, calendar_targets(sessions)], ignore_index=True).sort_values(["effective_date", "clock", "source", "ticker"])
    market, coverage = market_packet(sessions, active_tickers)
    target_path = Path(f"{args.output_prefix}_TARGETS.csv")
    market_path = Path(f"{args.output_prefix}_MARKET.csv")
    targets.to_csv(target_path, index=False)
    market.to_csv(market_path, index=False)
    formations.to_csv(f"{args.output_prefix}_PAIR_FORMATIONS.csv", index=False)
    pair_events.to_csv(f"{args.output_prefix}_PAIR_EVENTS.csv", index=False)
    coverage.to_csv(f"{args.output_prefix}_PRICE_COVERAGE.csv", index=False)
    input_files = [oos.OLD_DAILY, oos.OLD_0935, oos.OOS_DAILY, oos.OOS_0935, oos.OLD_CAPS, oos.OOS_CAPS, oos.PIT_FILTER,
        Path("STOCKS_PIT_FULL_LEAD_CLEAN_OOS_2026-09-17_MANIFEST.json")]
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "sample": [str(START.date()), str(END.date())], "sessions": len(sessions),
        "targets": str(target_path), "targetsHash": sha256(target_path),
        "market": str(market_path), "marketHash": sha256(market_path),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in input_files},
        "raw5minDirectory": str(oos.features.OOS_5M_DIR).replace("\\", "/"),
        "rules": "Quarterly top500 same-SIC z2 hold10 max10 pairs at 75%; next-session first-five SPY x2.5 at 25%.",
        "assumptions": {"borrow_available": True, "spy_adv20": 1000000000000.0,
            "classification": "Touched implementation replay, not clean OOS and not forward paper PnL."},
        "oldManual62UsedForSelection": False, "post2024ApprovalRecorded": True,
    }
    Path(f"{args.output_prefix}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print({"sessions": len(sessions), "targets": len(targets), "market": len(market), "formations": len(formations), "pairEvents": len(pair_events)})


if __name__ == "__main__":
    main()
