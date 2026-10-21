from __future__ import annotations

from pathlib import Path

import datetime as dt
import json
import math
import pickle

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_CANDIDATE_EVENTTIME_AUDIT_2026-09-17"
CORE_DAILY = Path("STOCKS_PIT_FULL_BETA_PLUS_CALENDAR_OVERLAY_2026-09-14_DAILY.csv")
PAIR_EVENTS = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_TRADE_EVENTS.csv")
PAIR_PRICES = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
SPY_BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
CORE_VARIANT = "spyvt16c150_plus_spy_first5_x05_fin25_cost4"
PAIR_VARIANT = "sic_pairs_quarterly_z2_hold10"
PAIR_SCALE = 0.5
START_CAPITAL = 100_000.0

# Frozen before measuring. Candidate rules and pair scale never change.
SCENARIOS = [
    {"scenario": "core_control", "pair_scale": 0.0, "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "base", "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "cost8", "cost_bps": 8.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "stress", "cost_bps": 8.0, "financing": 0.05, "borrow": 0.02, "missing_bps": 25.0},
    {"scenario": "severe", "cost_bps": 12.0, "financing": 0.05, "borrow": 0.03, "missing_bps": 50.0},
]

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
SLEEVE_OUT = Path(f"{OUT_PREFIX}_SLEEVE_ATTRIBUTION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    return float((equity - peak).min()), float((equity / peak - 1.0).min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    return float(pnl.mean() / std * math.sqrt(252)) if std > 0 else float("nan")


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_core() -> pd.DataFrame:
    x = pd.read_csv(CORE_DAILY, parse_dates=["date"])
    x = x[x["variant"].eq(CORE_VARIANT)].sort_values("date").copy()
    x["spy_exposure"] = x["beta_exposure"] + x["overlay_exposure"]
    return x[["date", "spy_exposure"]]


def load_pair_events() -> dict[pd.Timestamp, pd.DataFrame]:
    x = pd.read_csv(PAIR_EVENTS, parse_dates=["date"])
    x = x[x["variant"].eq(PAIR_VARIANT)].copy()
    return {date: group for date, group in x.groupby("date", sort=True)}


def load_pair_prices(dates: set[pd.Timestamp]) -> tuple[dict[pd.Timestamp, pd.Series], dict[pd.Timestamp, pd.Series]]:
    x = pd.read_pickle(PAIR_PRICES)
    x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    x["ticker"] = x["ticker"].astype(str).str.upper()
    x = x[x["date"].isin(dates)][["date", "ticker", "entry935", "exit1555"]].copy()
    x935 = x[x["entry935"] > 0]
    x1555 = x[x["exit1555"] > 0]
    p935 = {date: group.set_index("ticker")["entry935"] for date, group in x935.groupby("date", sort=True)}
    p1555 = {date: group.set_index("ticker")["exit1555"] for date, group in x1555.groupby("date", sort=True)}
    return p935, p1555


def load_spy_prices(dates: list[pd.Timestamp]) -> pd.DataFrame:
    with SPY_BARS.open("rb") as handle:
        bars = pickle.load(handle)["SPY"].copy().reset_index()
    time_col = "timestamp" if "timestamp" in bars.columns else bars.columns[0]
    bars["ts"] = pd.to_datetime(bars[time_col])
    bars["date"] = bars["ts"].dt.normalize()
    bars["time"] = bars["ts"].dt.time
    at935 = bars[bars["time"].eq(dt.time(9, 35))][["date", "open"]].rename(columns={"open": "spy935"})
    at1555 = bars[bars["time"].eq(dt.time(15, 55))][["date", "close"]].rename(columns={"close": "spy1555"})
    daily = at935.merge(at1555, on="date", how="inner").sort_values("date")
    daily["prev_spy1555"] = daily["spy1555"].shift(1)
    return daily[daily["date"].isin(dates)].dropna(subset=["prev_spy1555"]).copy()


def active_pair_weights(active: dict[str, dict[str, object]], pair_scale: float) -> pd.Series:
    if not active:
        return pd.Series(dtype=float)
    pair_gross = pair_scale / len(active)
    weights: dict[str, float] = {}
    for state in active.values():
        direction = int(state["direction"])
        ticker_a = str(state["ticker_a"])
        ticker_b = str(state["ticker_b"])
        weights[ticker_a] = weights.get(ticker_a, 0.0) + direction * pair_gross / 2.0
        weights[ticker_b] = weights.get(ticker_b, 0.0) - direction * pair_gross / 2.0
    return pd.Series(weights, dtype=float)


def apply_trade_events(active: dict[str, dict[str, object]], events: pd.DataFrame) -> None:
    if events.empty:
        return
    for row in events[events["event"].eq("exit")].itertuples(index=False):
        active.pop(str(row.pair_id), None)
    for row in events[events["event"].eq("entry")].itertuples(index=False):
        ticker_a, ticker_b = str(row.pair_id).split("|", maxsplit=1)
        active[str(row.pair_id)] = {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "direction": -1 if float(row.zscore) > 0 else 1,
        }


def effective_ticker_count(by_ticker: pd.Series) -> float:
    positive = by_ticker[by_ticker > 0]
    source = positive if positive.sum() > 0 else by_ticker.abs()
    total = float(source.sum())
    if total <= 0:
        return 0.0
    weights = source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_rows(scenario: str, contrib: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for scope, selected in (
        ("total_ex_carry", contrib[~contrib["ticker"].isin(["_FINANCING", "_BORROW"])]),
        ("pairs_only", contrib[contrib["sleeve"].eq("pairs")]),
    ):
        by_ticker = selected.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        denominator = float(contrib["pnl"].sum()) if scope == "total_ex_carry" else float(selected["pnl"].sum())
        if denominator <= 0:
            denominator = float(by_ticker.abs().sum())
        row: dict[str, object] = {
            "scenario": scenario,
            "scope": scope,
            "tickers": int(len(by_ticker)),
            "effectiveTickerCount": effective_ticker_count(by_ticker),
            "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        }
        for n in (1, 3, 5, 10):
            top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
            row[f"top{n}Pnl"] = top
            row[f"top{n}Share"] = top / denominator if denominator else float("nan")
        rows.append(row)
    return rows


def simulate(
    scenario: dict[str, object], core: pd.DataFrame, spy: pd.DataFrame,
    pair_events: dict[pd.Timestamp, pd.DataFrame], p935: dict[pd.Timestamp, pd.Series],
    p1555: dict[pd.Timestamp, pd.Series], spy_exposure_cap: float | None = None,
    annual_loss_limit: float | None = None, max_dd_limit: float | None = None,
    reentry_policy: str | None = None, reentry_signal: dict[pd.Timestamp, bool] | None = None,
    overnight_hedge_signal: dict[pd.Timestamp, bool] | None = None,
    overnight_hedge_scale: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scenario_name = str(scenario["scenario"])
    cost_rate = float(scenario["cost_bps"]) / 10_000.0
    financing_rate = float(scenario["financing"]) / 252.0
    borrow_rate = float(scenario["borrow"]) / 252.0
    missing_rate = float(scenario["missing_bps"]) / 10_000.0
    pair_scale = float(scenario.get("pair_scale", PAIR_SCALE))
    source = core.merge(spy, on="date", how="inner").sort_values("date").reset_index(drop=True)

    equity = START_CAPITAL
    active: dict[str, dict[str, object]] = {}
    pair_shares = pd.Series(dtype=float)
    pair_last_price = pd.Series(dtype=float)
    spy_shares = 0.0
    spy_last_price = float(source.iloc[0]["prev_spy1555"])
    hedge_shares = 0.0
    hedge_last_price = spy_last_price
    event_rows = []
    contrib_rows = []
    missing_marks = 0
    risk_locked = False
    current_year = int(source.iloc[0]["date"].year)
    year_start_equity = equity
    running_peak = START_CAPITAL
    dd_pending = False
    lock_trigger_date: pd.Timestamp | None = None
    locked_sessions = 0

    first_exposure = float(source.iloc[0]["spy_exposure"])
    if spy_exposure_cap is not None:
        first_exposure = min(first_exposure, spy_exposure_cap)
    initial_target = equity * first_exposure
    initial_turnover_cost = abs(initial_target) * cost_rate
    equity -= initial_turnover_cost
    spy_shares = initial_target / spy_last_price
    contrib_rows.append({"scenario": scenario_name, "timestamp": source.iloc[0]["date"] + pd.Timedelta(hours=9, minutes=29), "ticker": "SPY", "sleeve": "core", "pnl": -initial_turnover_cost})
    initial_hedge_cost = 0.0
    initial_hedge_financing = 0.0
    initial_hedge_borrow = 0.0
    first_date = pd.Timestamp(source.iloc[0]["date"])
    if overnight_hedge_scale > 0 and bool((overnight_hedge_signal or {}).get(first_date, False)):
        hedge_notional = equity * overnight_hedge_scale
        initial_hedge_cost = hedge_notional * cost_rate
        initial_hedge_financing = equity * (max(first_exposure + overnight_hedge_scale - 1.0, 0.0) - max(first_exposure - 1.0, 0.0)) * financing_rate
        initial_hedge_borrow = hedge_notional * borrow_rate
        equity -= initial_hedge_cost + initial_hedge_financing + initial_hedge_borrow
        hedge_shares = -hedge_notional / hedge_last_price
        contrib_rows.extend([
            {"scenario": scenario_name, "timestamp": first_date + pd.Timedelta(hours=9, minutes=29), "ticker": "SPY_HEDGE", "sleeve": "hedge", "pnl": -initial_hedge_cost},
            {"scenario": scenario_name, "timestamp": first_date + pd.Timedelta(hours=9, minutes=29), "ticker": "_FINANCING", "sleeve": "financing", "pnl": -initial_hedge_financing},
            {"scenario": scenario_name, "timestamp": first_date + pd.Timedelta(hours=9, minutes=29), "ticker": "_BORROW", "sleeve": "borrow", "pnl": -initial_hedge_borrow},
        ])
    initial_total_cost = initial_turnover_cost + initial_hedge_cost + initial_hedge_financing + initial_hedge_borrow
    event_rows.append({"scenario": scenario_name, "timestamp": first_date + pd.Timedelta(hours=9, minutes=29), "event": "initial_spy", "event_pnl": -initial_total_cost, "equity": equity, "gross_exposure": first_exposure + (overnight_hedge_scale if hedge_shares else 0.0), "missing_marks": 0, "turnover_cost": initial_turnover_cost + initial_hedge_cost, "financing_cost": initial_hedge_financing, "borrow_cost": initial_hedge_borrow, "missing_penalty": 0.0, "risk_locked": False})

    for index, row in source.iterrows():
        date = pd.Timestamp(row["date"])
        if risk_locked and max_dd_limit is not None:
            unlock = False
            if reentry_policy == "next_quarter" and lock_trigger_date is not None:
                unlock = (int(date.year), int(date.quarter)) != (int(lock_trigger_date.year), int(lock_trigger_date.quarter))
            elif reentry_policy == "cooldown_63":
                if locked_sessions >= 63:
                    unlock = True
                else:
                    locked_sessions += 1
            elif reentry_policy == "spy_above_sma200":
                unlock = bool((reentry_signal or {}).get(date, False))
            if unlock:
                risk_locked = False
                running_peak = equity
                dd_pending = False
                lock_trigger_date = None
                locked_sessions = 0
        if int(date.year) != current_year:
            current_year = int(date.year)
            year_start_equity = equity
            if max_dd_limit is None:
                risk_locked = False
        prices935 = p935.get(date, pd.Series(dtype=float))
        prices1555 = p1555.get(date, pd.Series(dtype=float))

        # 09:35 mark: SPY overnight/opening leg plus pairs from prior 15:55.
        spy_price935 = float(row["spy935"])
        spy_pnl_935 = spy_shares * (spy_price935 - spy_last_price)
        equity += spy_pnl_935
        spy_last_price = spy_price935
        contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=9, minutes=35), "ticker": "SPY", "sleeve": "core", "pnl": spy_pnl_935})

        hedge_pnl_935 = hedge_shares * (spy_price935 - hedge_last_price)
        hedge_close_cost = abs(hedge_shares * spy_price935) * cost_rate
        equity += hedge_pnl_935 - hedge_close_cost
        if hedge_shares:
            contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=9, minutes=35), "ticker": "SPY_HEDGE", "sleeve": "hedge", "pnl": hedge_pnl_935 - hedge_close_cost})
        hedge_shares = 0.0
        hedge_last_price = spy_price935

        pair_pnl_935 = 0.0
        missing_notional_935 = 0.0
        for ticker, shares in pair_shares.items():
            if ticker in prices935.index:
                price = float(prices935[ticker])
            else:
                price = float(pair_last_price.get(ticker, np.nan))
                missing_notional_935 += abs(float(shares) * price) if np.isfinite(price) else 0.0
                missing_marks += 1
            if not np.isfinite(price):
                continue
            prior = float(pair_last_price.get(ticker, price))
            pnl = float(shares) * (price - prior)
            pair_pnl_935 += pnl
            pair_last_price.loc[ticker] = price
            contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=9, minutes=35), "ticker": ticker, "sleeve": "pairs", "pnl": pnl})
        equity += pair_pnl_935
        missing_penalty_935 = missing_notional_935 * missing_rate
        if missing_penalty_935:
            equity -= missing_penalty_935
            contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=9, minutes=35), "ticker": "_MISSING", "sleeve": "execution", "pnl": -missing_penalty_935})

        apply_trade_events(active, pair_events.get(date, pd.DataFrame()))
        target_weights = active_pair_weights(active, pair_scale) if not risk_locked else pd.Series(dtype=float)
        all_tickers = pair_shares.index.union(target_weights.index)
        target_dollars = target_weights.reindex(all_tickers).fillna(0.0) * equity
        current_dollars = pd.Series(0.0, index=all_tickers)
        execution_prices = pd.Series(index=all_tickers, dtype=float)
        for ticker in all_tickers:
            price = float(prices935[ticker]) if ticker in prices935.index else float(pair_last_price.get(ticker, np.nan))
            execution_prices.loc[ticker] = price
            if ticker in pair_shares.index and np.isfinite(price):
                current_dollars.loc[ticker] = float(pair_shares[ticker]) * price
        trade_dollars = (target_dollars - current_dollars).abs()
        pair_turnover_cost = float(trade_dollars.sum()) * cost_rate
        if pair_turnover_cost > 0 and float(trade_dollars.sum()) > 0:
            for ticker, value in trade_dollars.items():
                cost = pair_turnover_cost * float(value) / float(trade_dollars.sum())
                contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=9, minutes=35), "ticker": ticker, "sleeve": "pairs", "pnl": -cost})
        equity -= pair_turnover_cost
        new_shares = {}
        for ticker, target in target_dollars.items():
            price = float(execution_prices[ticker])
            if np.isfinite(price) and price > 0 and float(target) != 0:
                new_shares[ticker] = float(target) / price
                pair_last_price.loc[ticker] = price
        pair_shares = pd.Series(new_shares, dtype=float)

        running_peak = max(running_peak, equity)
        if max_dd_limit is not None and not risk_locked and equity <= running_peak * (1.0 - max_dd_limit):
            dd_pending = True

        gross_935 = abs(spy_shares * spy_price935) / equity + (pair_shares * pair_last_price.reindex(pair_shares.index)).abs().sum() / equity
        event_pnl_935 = spy_pnl_935 + hedge_pnl_935 + pair_pnl_935 - hedge_close_cost - missing_penalty_935 - pair_turnover_cost
        event_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=9, minutes=35), "event": "mark_rebalance_0935", "event_pnl": event_pnl_935, "equity": equity, "gross_exposure": float(gross_935), "missing_marks": missing_marks, "turnover_cost": pair_turnover_cost + hedge_close_cost, "financing_cost": 0.0, "borrow_cost": 0.0, "missing_penalty": missing_penalty_935, "risk_locked": risk_locked})

        # 15:55 mark both sleeves on the same shared account.
        spy_price1555 = float(row["spy1555"])
        spy_pnl_1555 = spy_shares * (spy_price1555 - spy_last_price)
        equity += spy_pnl_1555
        spy_last_price = spy_price1555
        contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": "SPY", "sleeve": "core", "pnl": spy_pnl_1555})

        pair_pnl_1555 = 0.0
        missing_notional_1555 = 0.0
        for ticker, shares in pair_shares.items():
            if ticker in prices1555.index:
                price = float(prices1555[ticker])
            else:
                price = float(pair_last_price.get(ticker, np.nan))
                missing_notional_1555 += abs(float(shares) * price) if np.isfinite(price) else 0.0
                missing_marks += 1
            if not np.isfinite(price):
                continue
            prior = float(pair_last_price.get(ticker, price))
            pnl = float(shares) * (price - prior)
            pair_pnl_1555 += pnl
            pair_last_price.loc[ticker] = price
            contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": ticker, "sleeve": "pairs", "pnl": pnl})
        equity += pair_pnl_1555
        missing_penalty_1555 = missing_notional_1555 * missing_rate
        equity -= missing_penalty_1555
        if missing_penalty_1555:
            contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": "_MISSING", "sleeve": "execution", "pnl": -missing_penalty_1555})

        spy_notional = abs(spy_shares * spy_price1555)
        pair_values = pair_shares * pair_last_price.reindex(pair_shares.index)
        pair_gross_dollars = float(pair_values.abs().sum())
        pair_short_dollars = float(pair_values[pair_values < 0].abs().sum())
        gross_ratio = (spy_notional + pair_gross_dollars) / equity
        financing_cost = equity * max(gross_ratio - 1.0, 0.0) * financing_rate
        borrow_cost = pair_short_dollars * borrow_rate
        equity -= financing_cost + borrow_cost
        if financing_cost:
            contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": "_FINANCING", "sleeve": "financing", "pnl": -financing_cost})
        if borrow_cost:
            contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": "_BORROW", "sleeve": "borrow", "pnl": -borrow_cost})

        running_peak = max(running_peak, equity)
        annual_trigger = annual_loss_limit is not None and not risk_locked and equity <= year_start_equity * (1.0 - annual_loss_limit)
        dd_trigger = max_dd_limit is not None and not risk_locked and (dd_pending or equity <= running_peak * (1.0 - max_dd_limit))
        pair_liquidation_cost = 0.0
        if annual_trigger or dd_trigger:
            risk_locked = True
            if dd_trigger:
                lock_trigger_date = date
                locked_sessions = 0
                dd_pending = False
            pair_liquidation_cost = pair_gross_dollars * cost_rate
            if pair_liquidation_cost > 0 and pair_gross_dollars > 0:
                for ticker, value in pair_values.abs().items():
                    cost = pair_liquidation_cost * float(value) / pair_gross_dollars
                    contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": ticker, "sleeve": "pairs", "pnl": -cost})
            equity -= pair_liquidation_cost
            pair_shares = pd.Series(dtype=float)

        spy_turnover_cost = 0.0
        next_exposure = 0.0
        if index + 1 < len(source):
            next_exposure = float(source.iloc[index + 1]["spy_exposure"])
            if spy_exposure_cap is not None:
                next_exposure = min(next_exposure, spy_exposure_cap)
            next_date = pd.Timestamp(source.iloc[index + 1]["date"])
            if risk_locked and max_dd_limit is not None:
                next_exposure = 0.0
            elif risk_locked and int(next_date.year) == current_year:
                next_exposure = 0.0
            target_spy_dollars = equity * next_exposure
            current_spy_dollars = spy_shares * spy_price1555
            spy_trade_dollars = abs(target_spy_dollars - current_spy_dollars)
            spy_turnover_cost = spy_trade_dollars * cost_rate
            equity -= spy_turnover_cost
            spy_shares = target_spy_dollars / spy_price1555
            if spy_turnover_cost:
                contrib_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": "SPY", "sleeve": "core", "pnl": -spy_turnover_cost})

        hedge_entry_cost = 0.0
        hedge_financing_cost = 0.0
        hedge_borrow_cost = 0.0
        hedge_gross = 0.0
        if index + 1 < len(source):
            next_date = pd.Timestamp(source.iloc[index + 1]["date"])
            hedge_on = not risk_locked and overnight_hedge_scale > 0 and bool((overnight_hedge_signal or {}).get(next_date, False))
            if hedge_on:
                hedge_notional = equity * overnight_hedge_scale
                hedge_entry_cost = hedge_notional * cost_rate
                base_gross_after = abs(spy_shares * spy_price1555) / equity + pair_gross_dollars / equity
                hedge_financing_cost = equity * (max(base_gross_after + overnight_hedge_scale - 1.0, 0.0) - max(base_gross_after - 1.0, 0.0)) * financing_rate
                hedge_borrow_cost = hedge_notional * borrow_rate
                equity -= hedge_entry_cost + hedge_financing_cost + hedge_borrow_cost
                hedge_shares = -hedge_notional / spy_price1555
                hedge_last_price = spy_price1555
                hedge_gross = overnight_hedge_scale
                contrib_rows.extend([
                    {"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": "SPY_HEDGE", "sleeve": "hedge", "pnl": -hedge_entry_cost},
                    {"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": "_FINANCING", "sleeve": "financing", "pnl": -hedge_financing_cost},
                    {"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "ticker": "_BORROW", "sleeve": "borrow", "pnl": -hedge_borrow_cost},
                ])

        event_pnl_1555 = spy_pnl_1555 + pair_pnl_1555 - missing_penalty_1555 - financing_cost - borrow_cost - pair_liquidation_cost - spy_turnover_cost - hedge_entry_cost - hedge_financing_cost - hedge_borrow_cost
        event_rows.append({"scenario": scenario_name, "timestamp": date + pd.Timedelta(hours=15, minutes=55), "event": "mark_rebalance_1555", "event_pnl": event_pnl_1555, "equity": equity, "gross_exposure": max(gross_ratio, gross_ratio + hedge_gross), "missing_marks": missing_marks, "turnover_cost": pair_liquidation_cost + spy_turnover_cost + hedge_entry_cost, "financing_cost": financing_cost + hedge_financing_cost, "borrow_cost": borrow_cost + hedge_borrow_cost, "missing_penalty": missing_penalty_1555, "risk_locked": risk_locked})

    events = pd.DataFrame(event_rows)
    contrib = pd.DataFrame(contrib_rows)
    daily = events.assign(date=events["timestamp"].dt.normalize()).groupby(["scenario", "date"], as_index=False).agg(
        daily_pnl=("event_pnl", "sum"), equity=("equity", "last"), max_gross=("gross_exposure", "max"),
        turnover_cost=("turnover_cost", "sum"), financing_cost=("financing_cost", "sum"),
        borrow_cost=("borrow_cost", "sum"), missing_penalty=("missing_penalty", "sum"), missing_marks=("missing_marks", "max"),
        risk_locked=("risk_locked", "max"),
    )
    daily["year"] = daily["date"].dt.year
    return daily, events, contrib


def summary_row(scenario: dict[str, object], daily: pd.DataFrame, events: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(events["equity"])
    return {
        "scenario": scenario["scenario"],
        "pairScale": float(scenario.get("pair_scale", PAIR_SCALE)),
        "costBps": scenario["cost_bps"],
        "financingAnnual": scenario["financing"],
        "borrowAnnual": scenario["borrow"],
        "missingPenaltyBps": scenario["missing_bps"],
        "pnl": float(events["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(events["equity"], events["timestamp"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "turnoverCost": float(events["turnover_cost"].sum()),
        "financingCost": float(events["financing_cost"].sum()),
        "borrowCost": float(events["borrow_cost"].sum()),
        "missingPenalty": float(events["missing_penalty"].sum()),
        "maxGrossExposure": float(events["gross_exposure"].max()),
        "missingMarks": int(events["missing_marks"].max()),
    }


def yearly_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for (scenario, year), group in daily.groupby(["scenario", "year"], sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append({"scenario": scenario, "year": int(year), "pnl": float(group["daily_pnl"].sum()), "ddDollarSubset": dd, "ddPctSubset": dd_pct, "sharpe": sharpe(group["daily_pnl"])})
    return rows


def main() -> None:
    core = load_core()
    dates = list(core["date"])
    spy = load_spy_prices(dates)
    common_dates = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common_dates)].copy()
    spy = spy[spy["date"].isin(common_dates)].copy()
    pair_events = load_pair_events()
    p935, p1555 = load_pair_prices(common_dates)

    summaries = []
    yearly = []
    concentration = []
    sleeve_rows = []
    daily_frames = []
    event_frames = []
    contrib_frames = []
    qa_rows = []
    for scenario in SCENARIOS:
        daily, events, contrib = simulate(scenario, core, spy, pair_events, p935, p1555)
        summaries.append(summary_row(scenario, daily, events))
        yearly.extend(yearly_rows(daily))
        concentration.extend(concentration_rows(str(scenario["scenario"]), contrib))
        for sleeve, pnl in contrib.groupby("sleeve")["pnl"].sum().items():
            sleeve_rows.append({"scenario": scenario["scenario"], "sleeve": sleeve, "pnl": float(pnl)})
        daily_frames.append(daily)
        event_frames.append(events)
        contrib_frames.append(contrib)
        qa_rows.append({"scenario": scenario["scenario"], "eventPnl": float(events["event_pnl"].sum()), "contribPnl": float(contrib["pnl"].sum()), "endingPnl": float(events["equity"].iloc[-1] - START_CAPITAL), "eventMinusContrib": float(events["event_pnl"].sum() - contrib["pnl"].sum()), "eventMinusEnding": float(events["event_pnl"].sum() - (events["equity"].iloc[-1] - START_CAPITAL))})
        print("EVENTTIME", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(sleeve_rows).to_csv(SLEEVE_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENT_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa_rows).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_candidate_eventtime_audit.py",
        "inputs": [str(CORE_DAILY), str(PAIR_EVENTS), str(PAIR_PRICES).replace("\\", "/"), str(SPY_BARS).replace("\\", "/")],
        "frozen_candidate": "SPY vt16 cap150 plus first-five-trading-days 0.5x plus quarterly same-SIC pairs 0.5x",
        "method": "Single shared-equity event engine with dollar holdings. Both SPY and pairs mark at 09:35 and 15:55; pair events execute at 09:35 and SPY target exposure rebalances at 15:55 for the next session.",
        "mark_policy": "Open positions are marked through final 15:55 and remain open; no artificial terminal liquidation. Missing prices carry the last mark and receive scenario penalty.",
        "scenarios": SCENARIOS,
        "sample_label": "Research/touched 2018-2024 only. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "leakage_controls": "Core exposures and pair trade events are frozen causal source outputs. Event execution uses local SPY and broad-PIT 09:35/15:55 prices. No old manual 62 equity selection; old cache supplies SPY benchmark bars only.",
        "rule_selection_effect": "None. Candidate rules, pair scale and stress matrix were frozen before measurement.",
        "trade_selection_effect": "No source rule re-selection. Shared dollar holdings, event compounding, turnover, financing, borrow and missing-price penalties are rebuilt from events.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(SLEEVE_OUT), str(DAILY_OUT), str(EVENT_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, SLEEVE_OUT, DAILY_OUT, EVENT_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
