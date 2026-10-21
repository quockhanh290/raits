from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from stocks_sec_ownership_insider_reaction_replay import START_CAPITAL, yearly_rows
from stocks_sec_form4_transaction_reaction_replay import extended_metrics


PREREG = Path("STOCKS_SEC_13D_SICPAIR_DRIFT_PREREG_2026-09-24.json")
EVENTS = Path(
    "raits/data/cache/external_events/sec_submissions_pit_2018_2026/"
    "sec_ownership_insider_events_2017_2026.csv"
)
INTRADAY = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
CAP = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)
FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)
BENCHMARK = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
PREFIX = "STOCKS_SEC_13D_SICPAIR_DRIFT_DEV_2026-09-24"
DEV_START = pd.Timestamp("2018-04-27")
DEV_END = pd.Timestamp("2022-12-30")
VAL_START = pd.Timestamp("2023-01-03")
VAL_END = pd.Timestamp("2024-12-31")
LOWER_BOUND = pd.Timestamp("2017-12-29 09:15", tz="America/New_York").tz_convert("UTC")
CANDIDATES = [
    {"variant": "active13d_sicpair_hold20", "hold_sessions": 20},
    {"variant": "active13d_sicpair_hold60", "hold_sessions": 60},
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def normalize_cik(values: pd.Series) -> pd.Series:
    return values.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(10)


def load_intraday() -> pd.DataFrame:
    frame = pd.read_pickle(INTRADAY)[["date", "ticker", "entry935", "exit1555"]].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    frame = frame[frame["date"].between(DEV_START, VAL_END)].copy()
    return frame.replace([np.inf, -np.inf], np.nan)


def load_members() -> pd.DataFrame:
    cap = pd.read_csv(CAP, low_memory=False)
    cap["snapshot_date"] = pd.to_datetime(cap["date"]).dt.normalize()
    cap["ticker"] = cap["ticker_query"].astype(str).str.upper()
    cap["market_cap"] = pd.to_numeric(cap["market_cap"], errors="coerce")
    cap["sic_description"] = cap["sic_description"].fillna("").astype(str).str.strip().str.upper()
    cap = cap[cap["status_code"].eq(200) & cap["market_cap"].gt(0)].copy()
    cap["rank_market_cap"] = cap.groupby("snapshot_date")["market_cap"].rank(
        method="first", ascending=False
    )
    cap = cap[cap["rank_market_cap"].le(500)][
        ["snapshot_date", "ticker", "market_cap", "sic_description"]
    ]
    identity = pd.read_parquet(FILTER, columns=["date", "ticker", "cik", "security_id"])
    identity["snapshot_date"] = pd.to_datetime(identity["date"]).dt.normalize()
    identity["ticker"] = identity["ticker"].astype(str).str.upper()
    identity = identity[["snapshot_date", "ticker", "cik", "security_id"]].drop_duplicates(
        ["snapshot_date", "ticker"]
    )
    members = cap.merge(identity, on=["snapshot_date", "ticker"], how="left", validate="one_to_one")
    members["cik"] = normalize_cik(members["cik"])
    members = members[
        members["cik"].notna()
        & ~members["cik"].eq("0000000000")
        & members["sic_description"].ne("")
    ].copy()
    members = members.sort_values(
        ["snapshot_date", "cik", "market_cap", "ticker"],
        ascending=[True, True, False, True],
    )
    return members.drop_duplicates(["snapshot_date", "cik"], keep="first")


def load_eligible() -> pd.DataFrame:
    frame = pd.read_parquet(
        FILTER,
        columns=["date", "ticker", "adv20"],
        filters=[
            ("date", ">=", DEV_START.date()),
            ("date", "<=", VAL_END.date()),
            ("eligible_final", "==", True),
        ],
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    return frame.groupby(["date", "ticker"], as_index=False)["adv20"].min()


def assign_events(sessions: list[pd.Timestamp]) -> pd.DataFrame:
    events = pd.read_csv(EVENTS, dtype={"cik": str, "accessionNumber": str})
    events = events[events["event_class"].eq("ownership_active_initial")].copy()
    events["cik"] = normalize_cik(events["cik"])
    accepted = pd.to_datetime(events["accepted_et"], utc=True, errors="coerce")
    cutoffs = pd.DatetimeIndex(
        [date.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=15) for date in sessions]
    ).tz_convert("UTC")
    indices = np.searchsorted(cutoffs.asi8, accepted.astype("int64").to_numpy(), side="right")
    valid = accepted.notna().to_numpy() & accepted.ge(LOWER_BOUND).to_numpy() & (indices < len(sessions))
    assigned = events.loc[valid].copy()
    assigned["accepted_utc"] = accepted.loc[valid].to_numpy()
    assigned["date"] = pd.to_datetime([sessions[index] for index in indices[valid]]).normalize()
    assigned = assigned[assigned["date"].between(DEV_START, VAL_END)].copy()
    assigned = assigned.sort_values(["cik", "date", "accepted_utc", "accessionNumber"])
    return assigned.drop_duplicates(["cik", "date"], keep="first")


def build_pairs(intra: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    sessions = sorted(intra["date"].drop_duplicates())
    events = assign_events(sessions)
    members = load_members()
    snapshots = members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    session_snapshots = pd.merge_asof(
        pd.DataFrame({"date": sessions}),
        snapshots,
        left_on="date",
        right_on="snapshot_date",
        direction="backward",
    )
    mapped = events.merge(session_snapshots, on="date", how="inner", validate="many_to_one")
    target_members = members.rename(
        columns={
            "ticker": "target_ticker",
            "market_cap": "target_market_cap",
            "security_id": "target_security_id",
        }
    )
    mapped = mapped.merge(target_members, on=["snapshot_date", "cik"], how="inner", validate="many_to_one")
    current = load_eligible().merge(intra, on=["date", "ticker"], how="inner", validate="one_to_one")
    current = current[current["entry935"].gt(0)].copy()
    current_by_date = {date: group.set_index("ticker") for date, group in current.groupby("date", sort=True)}
    member_groups = {
        key: group.copy()
        for key, group in members.groupby(["snapshot_date", "sic_description"], sort=False)
    }
    rows: list[dict[str, object]] = []
    no_peer = 0
    no_target_price = 0
    for row in mapped.sort_values(["date", "accepted_utc", "cik", "target_ticker"]).itertuples(index=False):
        day = current_by_date.get(row.date)
        if day is None or row.target_ticker not in day.index:
            no_target_price += 1
            continue
        group = member_groups.get((row.snapshot_date, row.sic_description))
        if group is None:
            no_peer += 1
            continue
        candidates = group[
            group["ticker"].ne(row.target_ticker)
            & group["cik"].ne(row.cik)
            & group["ticker"].isin(day.index)
        ].copy()
        if candidates.empty:
            no_peer += 1
            continue
        candidates["cap_distance"] = (
            np.log(candidates["market_cap"]) - np.log(float(row.target_market_cap))
        ).abs()
        peer = candidates.sort_values(["cap_distance", "ticker"]).iloc[0]
        target_day = day.loc[row.target_ticker]
        peer_day = day.loc[peer["ticker"]]
        rows.append(
            {
                "date": row.date,
                "accepted_utc": row.accepted_utc,
                "accessionNumber": row.accessionNumber,
                "target_cik": row.cik,
                "target_ticker": row.target_ticker,
                "target_market_cap": row.target_market_cap,
                "target_adv20": float(target_day["adv20"]),
                "peer_cik": peer["cik"],
                "peer_ticker": peer["ticker"],
                "peer_market_cap": peer["market_cap"],
                "peer_adv20": float(peer_day["adv20"]),
                "sic_description": row.sic_description,
                "cap_distance": float(peer["cap_distance"]),
            }
        )
    pairs = pd.DataFrame(rows)
    qa = {
        "assignedInitial13dEvents": int(len(events)),
        "mappedTop500Events": int(len(mapped)),
        "executablePairsBeforeCompleteHold": int(len(pairs)),
        "missingTargetEntry": no_target_price,
        "missingSameSicPeer": no_peer,
    }
    return pairs, qa


def price_maps(intra: pd.DataFrame) -> tuple[dict[pd.Timestamp, pd.Series], dict[pd.Timestamp, pd.Series]]:
    p935 = {
        date: group.set_index("ticker")["entry935"]
        for date, group in intra[intra["entry935"].gt(0)].groupby("date", sort=True)
    }
    p1555 = {
        date: group.set_index("ticker")["exit1555"]
        for date, group in intra[intra["exit1555"].gt(0)].groupby("date", sort=True)
    }
    return p935, p1555


def add_contrib(
    rows: list[dict[str, object]],
    scenario: str,
    timestamp: pd.Timestamp,
    ticker: str,
    sleeve: str,
    pnl: float,
) -> None:
    if pnl != 0.0:
        rows.append(
            {
                "scenario": scenario,
                "timestamp": timestamp,
                "ticker": ticker,
                "sleeve": sleeve,
                "pnl": pnl,
            }
        )


def pair_gross(state: dict[str, object], prices: pd.Series) -> float:
    return float(
        sum(
            abs(float(leg["shares"]) * float(prices.get(ticker, leg["last_price"])))
            for ticker, leg in state["legs"].items()
        )
    )


def mark_pairs(
    active: dict[str, dict[str, object]],
    prices: pd.Series,
    scenario: str,
    timestamp: pd.Timestamp,
    contrib: list[dict[str, object]],
) -> tuple[float, int]:
    pnl_total = 0.0
    missing = 0
    for state in active.values():
        for ticker, leg in state["legs"].items():
            if ticker in prices.index:
                price = float(prices[ticker])
                pnl = float(leg["shares"]) * (price - float(leg["last_price"]))
                leg["last_price"] = price
                pnl_total += pnl
                add_contrib(contrib, scenario, timestamp, ticker, str(leg["role"]), pnl)
            else:
                missing += 1
    return pnl_total, missing


def close_pair(
    pair_id: str,
    state: dict[str, object],
    prices: pd.Series,
    cost_rate: float,
    scenario: str,
    timestamp: pd.Timestamp,
    reason: str,
    trades: list[dict[str, object]],
    contrib: list[dict[str, object]],
) -> tuple[float, float]:
    turnover = 0.0
    for ticker, leg in state["legs"].items():
        price = float(prices[ticker])
        notional = abs(float(leg["shares"]) * price)
        cost = notional * cost_rate
        turnover += notional
        add_contrib(contrib, scenario, timestamp, ticker, str(leg["role"]), -cost)
        trades.append(
            {
                "scenario": scenario,
                "timestamp": timestamp,
                "date": timestamp.normalize(),
                "pair_id": pair_id,
                "ticker": ticker,
                "role": leg["role"],
                "event": "leg_exit",
                "reason": reason,
                "notional": notional,
                "cost": cost,
                "direction": int(np.sign(float(leg["shares"]))),
            }
        )
    return turnover, turnover * cost_rate


def enforce_pair_gross(
    active: dict[str, dict[str, object]],
    prices: pd.Series,
    equity: float,
    cost_rate: float,
    scenario: str,
    timestamp: pd.Timestamp,
    trades: list[dict[str, object]],
    contrib: list[dict[str, object]],
) -> tuple[float, float]:
    gross_by_pair = {pair_id: pair_gross(state, prices) for pair_id, state in active.items()}
    gross = float(sum(gross_by_pair.values()))
    if gross <= equity or gross <= 0.0:
        return 0.0, 0.0
    tradable = [
        pair_id
        for pair_id, state in active.items()
        if all(ticker in prices.index for ticker in state["legs"])
    ]
    tradable_gross = float(sum(gross_by_pair[pair_id] for pair_id in tradable))
    locked_gross = gross - tradable_gross
    if tradable_gross <= 0.0:
        return 0.0, 0.0
    target = max((equity - locked_gross - cost_rate * tradable_gross) / max(1.0 - cost_rate, 1e-12), 0.0)
    scale = min(target / tradable_gross, 1.0)
    turnover = 0.0
    for pair_id in tradable:
        for ticker, leg in active[pair_id]["legs"].items():
            old_shares = float(leg["shares"])
            new_shares = old_shares * scale
            reduction = abs(old_shares - new_shares) * float(prices[ticker])
            leg["shares"] = new_shares
            turnover += reduction
            cost = reduction * cost_rate
            add_contrib(contrib, scenario, timestamp, ticker, str(leg["role"]), -cost)
            trades.append(
                {
                    "scenario": scenario,
                    "timestamp": timestamp,
                    "date": timestamp.normalize(),
                    "pair_id": pair_id,
                    "ticker": ticker,
                    "role": leg["role"],
                    "event": "leg_reduce",
                    "reason": "hard_gross_cap",
                    "notional": reduction,
                    "cost": cost,
                    "direction": int(np.sign(old_shares)),
                }
            )
    return turnover, turnover * cost_rate


def simulate(
    variant: str,
    hold_sessions: int,
    cost_bps: float,
    sessions: list[pd.Timestamp],
    signals: pd.DataFrame,
    p935: dict[pd.Timestamp, pd.Series],
    p1555: dict[pd.Timestamp, pd.Series],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scenario = f"{variant}_cost{int(cost_bps)}"
    cost_rate = cost_bps / 10_000.0
    signal_by_date = {date: group for date, group in signals.groupby("date", sort=True)}
    session_index = {date: index for index, date in enumerate(sessions)}
    equity = START_CAPITAL
    active: dict[str, dict[str, object]] = {}
    daily_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    contrib_rows: list[dict[str, object]] = []
    missing_marks = 0

    for date in sessions:
        ts935 = date + pd.Timedelta(hours=9, minutes=35)
        ts1555 = date + pd.Timedelta(hours=15, minutes=55)
        prices935 = p935.get(date, pd.Series(dtype=float))
        prices1555 = p1555.get(date, pd.Series(dtype=float))
        day_start = equity
        pnl935, missing = mark_pairs(active, prices935, scenario, ts935, contrib_rows)
        missing_marks += missing
        equity += pnl935
        turnover935 = 0.0
        for pair_id, state in list(active.items()):
            if pd.Timestamp(state["exit_date"]) < date and all(
                ticker in prices935.index for ticker in state["legs"]
            ):
                turnover, cost = close_pair(
                    pair_id, state, prices935, cost_rate, scenario, ts935,
                    "delayed_exact_0935", trade_rows, contrib_rows,
                )
                turnover935 += turnover
                equity -= cost
                del active[pair_id]

        cap_turnover, cap_cost = enforce_pair_gross(
            active, prices935, equity, cost_rate, scenario, ts935, trade_rows, contrib_rows
        )
        turnover935 += cap_turnover
        equity -= cap_cost

        new_signals = signal_by_date.get(date, signals.iloc[0:0])
        active_tickers = {
            ticker for state in active.values() for ticker in state["legs"]
        }
        admitted = []
        used = set(active_tickers)
        requested_leg = equity * 0.03
        for row in new_signals.sort_values(
            ["accepted_utc", "accessionNumber", "target_ticker", "peer_ticker"]
        ).itertuples(index=False):
            tickers = {row.target_ticker, row.peer_ticker}
            if tickers & used:
                continue
            if not tickers.issubset(prices935.index):
                continue
            if requested_leg / float(row.target_adv20) > 0.01:
                continue
            if requested_leg / float(row.peer_adv20) > 0.01:
                continue
            admitted.append(row)
            used.update(tickers)
        current_gross = float(sum(pair_gross(state, prices935) for state in active.values()))
        available = max(equity - current_gross, 0.0)
        scale = min(1.0, available / (2.0 * requested_leg * len(admitted))) if admitted else 0.0
        pair_entries = 0
        for row in admitted:
            if scale <= 0.0:
                break
            leg_notional = requested_leg * scale
            pair_id = f"{row.date.date()}|{row.accessionNumber}|{row.target_ticker}|{row.peer_ticker}"
            exit_index = session_index[date] + hold_sessions - 1
            if exit_index >= len(sessions):
                continue
            legs = {}
            for ticker, direction, role in (
                (row.target_ticker, 1, "target"),
                (row.peer_ticker, -1, "peer"),
            ):
                price = float(prices935[ticker])
                shares = direction * leg_notional / price
                cost = leg_notional * cost_rate
                equity -= cost
                turnover935 += leg_notional
                add_contrib(contrib_rows, scenario, ts935, ticker, role, -cost)
                trade_rows.append(
                    {
                        "scenario": scenario,
                        "timestamp": ts935,
                        "date": date,
                        "pair_id": pair_id,
                        "ticker": ticker,
                        "role": role,
                        "event": "leg_entry",
                        "reason": "initial_13d_same_sic_peer",
                        "notional": leg_notional,
                        "cost": cost,
                        "direction": direction,
                        "accessionNumber": row.accessionNumber,
                    }
                )
                legs[ticker] = {
                    "shares": shares,
                    "last_price": price,
                    "role": role,
                }
            active[pair_id] = {
                "legs": legs,
                "exit_date": sessions[exit_index],
                "accessionNumber": row.accessionNumber,
            }
            pair_entries += 1

        cap_turnover, cap_cost = enforce_pair_gross(
            active, prices935, equity, cost_rate, scenario, ts935, trade_rows, contrib_rows
        )
        turnover935 += cap_turnover
        equity -= cap_cost
        gross935 = float(sum(pair_gross(state, prices935) for state in active.values())) / max(equity, 1e-9)
        event_rows.append(
            {
                "scenario": scenario,
                "timestamp": ts935,
                "equity": equity,
                "event_pnl": pnl935 - turnover935 * cost_rate,
                "gross": gross935,
                "turnover": turnover935,
                "trade_cost": turnover935 * cost_rate,
                "borrow_cost": 0.0,
                "financing_cost": 0.0,
                "active_pairs": len(active),
                "missing_marks": missing_marks,
            }
        )

        pnl1555, missing = mark_pairs(active, prices1555, scenario, ts1555, contrib_rows)
        missing_marks += missing
        equity += pnl1555
        short_gross = float(
            sum(
                abs(float(leg["shares"]) * float(leg["last_price"]))
                for state in active.values()
                for leg in state["legs"].values()
                if float(leg["shares"]) < 0
            )
        )
        gross_dollars = float(sum(pair_gross(state, prices1555) for state in active.values()))
        borrow_cost = short_gross * 0.01 / 252.0
        financing_cost = max(gross_dollars - equity, 0.0) * 0.025 / 252.0
        equity -= borrow_cost + financing_cost
        add_contrib(contrib_rows, scenario, ts1555, "_BORROW", "borrow", -borrow_cost)
        add_contrib(contrib_rows, scenario, ts1555, "_FINANCING", "financing", -financing_cost)
        turnover1555 = 0.0
        for pair_id, state in list(active.items()):
            if pd.Timestamp(state["exit_date"]) <= date and all(
                ticker in prices1555.index for ticker in state["legs"]
            ):
                turnover, cost = close_pair(
                    pair_id, state, prices1555, cost_rate, scenario, ts1555,
                    "scheduled_1555", trade_rows, contrib_rows,
                )
                turnover1555 += turnover
                equity -= cost
                del active[pair_id]
        cap_turnover, cap_cost = enforce_pair_gross(
            active, prices1555, equity, cost_rate, scenario, ts1555, trade_rows, contrib_rows
        )
        turnover1555 += cap_turnover
        equity -= cap_cost
        gross1555 = float(sum(pair_gross(state, prices1555) for state in active.values())) / max(equity, 1e-9)
        event_rows.append(
            {
                "scenario": scenario,
                "timestamp": ts1555,
                "equity": equity,
                "event_pnl": pnl1555 - borrow_cost - financing_cost - turnover1555 * cost_rate,
                "gross": gross1555,
                "turnover": turnover1555,
                "trade_cost": turnover1555 * cost_rate,
                "borrow_cost": borrow_cost,
                "financing_cost": financing_cost,
                "active_pairs": len(active),
                "missing_marks": missing_marks,
            }
        )
        daily_rows.append(
            {
                "scenario": scenario,
                "date": date,
                "daily_pnl": equity - day_start,
                "equity": equity,
                "max_gross": max(gross935, gross1555),
                "entries": pair_entries,
                "active_pairs": len(active),
                "missing_marks": missing_marks,
            }
        )
    return (
        pd.DataFrame(daily_rows),
        pd.DataFrame(event_rows),
        pd.DataFrame(trade_rows),
        pd.DataFrame(contrib_rows),
    )


def complete_hold_filter(
    signals: pd.DataFrame, sessions: list[pd.Timestamp], hold_sessions: int
) -> pd.DataFrame:
    if len(sessions) < hold_sessions:
        return signals.iloc[0:0].copy()
    return signals[signals["date"].isin(set(sessions[: len(sessions) - hold_sessions + 1]))].copy()


def benchmark_stats(daily: pd.DataFrame) -> dict[str, float]:
    benchmark = pd.read_csv(BENCHMARK, parse_dates=["date"])
    benchmark = benchmark[benchmark["variant"].eq("broad_pit_equal_weight")][["date", "daily_ret"]]
    merged = daily.merge(benchmark, on="date", how="inner", validate="one_to_one")
    merged["portfolio_return"] = merged["daily_pnl"] / (merged["equity"] - merged["daily_pnl"])
    merged = merged.dropna(subset=["portfolio_return", "daily_ret"])
    beta = float(merged[["portfolio_return", "daily_ret"]].cov().iloc[0, 1] / merged["daily_ret"].var())
    residual = merged["portfolio_return"] - beta * merged["daily_ret"]
    return {
        "marketBeta": beta,
        "marketCorrelation": float(merged["portfolio_return"].corr(merged["daily_ret"])),
        "annualizedResidualAlpha": float(residual.mean() * 252),
        "residualSharpe": float(residual.mean() / residual.std() * np.sqrt(252))
        if residual.std() > 0
        else float("nan"),
    }


def metric_row(metrics: pd.DataFrame, scenario: str, stage: str) -> pd.Series:
    rows = metrics[metrics["scenario"].eq(scenario) & metrics["bookStage"].eq(stage)]
    if len(rows) != 1:
        raise RuntimeError(f"Expected one row for {scenario}/{stage}, found {len(rows)}")
    return rows.iloc[0]


def choose_variant(metrics: pd.DataFrame, yearly: pd.DataFrame) -> dict[str, object]:
    rows = []
    for candidate in CANDIDATES:
        variant = candidate["variant"]
        dev = metric_row(metrics, f"{variant}_cost4", "development")
        dev8 = metric_row(metrics, f"{variant}_cost8", "development")
        val = metric_row(metrics, f"{variant}_cost4", "validation")
        val8 = metric_row(metrics, f"{variant}_cost8", "validation")
        dev_years = yearly[
            yearly["scenario"].eq(f"{variant}_cost4") & yearly["year"].between(2018, 2022)
        ]
        val_years = yearly[
            yearly["scenario"].eq(f"{variant}_cost4") & yearly["year"].between(2023, 2024)
        ]
        positive_years = int(dev_years["pnl"].gt(0).sum())
        dev_pass = bool(
            positive_years >= 3
            and dev["cagr"] >= 0.02
            and dev["sharpe"] >= 0.5
            and dev["pnl"] > 0
            and dev8["pnl"] > 0
            and dev["ddPct"] >= -0.12
            and dev["entries"] >= 50
            and dev["effectiveTickerCount"] >= 20
            and dev["top10PositivePnlShare"] <= 0.65
            and abs(dev["marketBeta"]) <= 0.25
        )
        val_pass = bool(
            val["pnl"] > 0
            and val8["pnl"] > 0
            and len(val_years) == 2
            and val_years["pnl"].ge(0).all()
            and val["ddPct"] >= -0.10
            and val["entries"] >= 20
            and val["effectiveTickerCount"] >= 10
            and val["top10PositivePnlShare"] <= 0.75
            and abs(val["marketBeta"]) <= 0.25
        )
        rows.append(
            {
                "variant": variant,
                "developmentPass": dev_pass,
                "validationPass": val_pass,
                "positiveDevelopmentYears": positive_years,
                "developmentPnl": float(dev["pnl"]),
                "developmentStress8Pnl": float(dev8["pnl"]),
                "developmentCagr": float(dev["cagr"]),
                "developmentSharpe": float(dev["sharpe"]),
                "developmentStress8Sharpe": float(dev8["sharpe"]),
                "developmentDdDollar": float(dev["ddDollar"]),
                "developmentDdPct": float(dev["ddPct"]),
                "developmentEntries": int(dev["entries"]),
                "developmentEffectiveTickerCount": float(dev["effectiveTickerCount"]),
                "developmentTop10Share": float(dev["top10PositivePnlShare"]),
                "developmentMarketBeta": float(dev["marketBeta"]),
                "validationPnl": float(val["pnl"]),
                "validationStress8Pnl": float(val8["pnl"]),
                "validationDdPct": float(val["ddPct"]),
                "validationEntries": int(val["entries"]),
                "validationEffectiveTickerCount": float(val["effectiveTickerCount"]),
                "validationTop10Share": float(val["top10PositivePnlShare"]),
                "validationMarketBeta": float(val["marketBeta"]),
            }
        )
    eligible = [row for row in rows if row["developmentPass"]]
    eligible.sort(
        key=lambda row: (
            -row["developmentStress8Sharpe"],
            -row["developmentSharpe"],
            -row["developmentEntries"],
            int(row["variant"].split("hold")[-1]),
        )
    )
    selected = eligible[0] if eligible else None
    return {
        "candidates": rows,
        "selectedOnDevelopment": selected["variant"] if selected else None,
        "selectedValidationPass": bool(selected and selected["validationPass"]),
        "familyStatus": "CONTINUE_NEEDS_AUDIT"
        if selected and selected["validationPass"]
        else "KILL_BEFORE_OOS",
        "selectionAudit": "One development-only hold selection; validation cannot substitute the other hold.",
    }


def main() -> None:
    argparse.ArgumentParser(description="Replay preregistered initial-13D same-SIC pair drift.").parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_family_performance"):
        raise RuntimeError("Family preregistration is not frozen")
    intra = load_intraday()
    pairs, pair_qa = build_pairs(intra)
    all_daily = []
    all_events = []
    all_trades = []
    all_contrib = []
    metrics_rows = []
    signal_counts: dict[str, dict[str, int]] = {}
    for candidate in CANDIDATES:
        variant = candidate["variant"]
        hold = candidate["hold_sessions"]
        signal_counts[variant] = {}
        for stage, start, end in (
            ("development", DEV_START, DEV_END),
            ("validation", VAL_START, VAL_END),
        ):
            stage_intra = intra[intra["date"].between(start, end)].copy()
            sessions = sorted(stage_intra["date"].drop_duplicates())
            signals = pairs[pairs["date"].between(start, end)].copy()
            signals = complete_hold_filter(signals, sessions, hold)
            signal_counts[variant][stage] = int(len(signals))
            p935, p1555 = price_maps(stage_intra)
            for cost_bps in (4.0, 8.0):
                scenario = f"{variant}_cost{int(cost_bps)}"
                daily, events, trades, contrib = simulate(
                    variant, hold, cost_bps, sessions, signals, p935, p1555
                )
                for frame in (daily, events, trades, contrib):
                    frame["bookStage"] = stage
                row = extended_metrics(scenario, daily, events, trades, contrib, start, end)
                pair_entry_rows = trades[trades["event"].eq("leg_entry") & trades["role"].eq("target")]
                row["entries"] = int(len(pair_entry_rows))
                row["longEntries"] = int(len(pair_entry_rows))
                row["shortEntries"] = int(len(pair_entry_rows))
                row["tickerCount"] = int(
                    trades.loc[trades["event"].eq("leg_entry"), "ticker"].nunique()
                )
                row.update(benchmark_stats(daily))
                row["bookStage"] = stage
                metrics_rows.append(row)
                all_daily.append(daily)
                all_events.append(events)
                all_trades.append(trades)
                all_contrib.append(contrib)
                print("13D_SICPAIR", variant, stage, int(cost_bps), row["pnl"], flush=True)

    daily_all = pd.concat(all_daily, ignore_index=True)
    events_all = pd.concat(all_events, ignore_index=True)
    trades_all = pd.concat(all_trades, ignore_index=True)
    contrib_all = pd.concat(all_contrib, ignore_index=True)
    metrics = pd.DataFrame(metrics_rows)
    yearly = yearly_rows(daily_all)
    qa_rows = []
    for (scenario, stage), group in events_all.groupby(["scenario", "bookStage"], sort=True):
        daily = daily_all[daily_all["scenario"].eq(scenario) & daily_all["bookStage"].eq(stage)]
        contrib = contrib_all[
            contrib_all["scenario"].eq(scenario) & contrib_all["bookStage"].eq(stage)
        ]
        event_pnl = float(group["event_pnl"].sum())
        daily_pnl = float(daily["daily_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(group.iloc[-1]["equity"] - START_CAPITAL)
        qa_rows.append(
            {
                "scenario": scenario,
                "bookStage": stage,
                "eventPnl": event_pnl,
                "dailyPnl": daily_pnl,
                "contribPnl": contrib_pnl,
                "endingPnl": ending_pnl,
                "eventMinusDaily": event_pnl - daily_pnl,
                "eventMinusContrib": event_pnl - contrib_pnl,
                "eventMinusEnding": event_pnl - ending_pnl,
                "maxGross": float(group["gross"].max()),
                "missingMarks": int(group["missing_marks"].max()),
                "activePairsAtEnd": int(group.iloc[-1]["active_pairs"]),
            }
        )
    qa = pd.DataFrame(qa_rows)
    selection = choose_variant(metrics, yearly)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    pairs.to_csv(f"{PREFIX}_PAIRS.csv", index=False)
    metrics.to_csv(f"{PREFIX}_SUMMARY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    daily_all.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    events_all.to_csv(f"{PREFIX}_EVENT_LEDGER.csv", index=False)
    trades_all.to_csv(f"{PREFIX}_TRADE_LEDGER.csv", index=False)
    contrib_all.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)
    qa.to_csv(f"{PREFIX}_QA.csv", index=False)
    manifest = {
        "script": "raits/research/stocks_sec_13d_sicpair_drift_replay.py",
        "preregistration": str(PREREG),
        "adaptiveResearch": True,
        "stageIsolation": "Independent USD 100k books; complete scheduled holds only.",
        "oos_2025_2026_consumed": False,
        "inputs": [str(EVENTS), str(INTRADAY), str(CAP), str(FILTER), str(BENCHMARK)],
        "input_hashes": {str(path): sha256(path) for path in [EVENTS, CAP, BENCHMARK]},
        "pair_qa": pair_qa,
        "candidate_signal_counts": signal_counts,
        "selection": selection,
        "outputs_prefix": PREFIX,
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("13D_SICPAIR_SELECTION", json.dumps(selection), flush=True)


if __name__ == "__main__":
    main()
