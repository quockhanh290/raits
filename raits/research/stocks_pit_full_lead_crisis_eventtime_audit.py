from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as base
import stocks_pit_full_residual_reversal_cohorts as residual
from stocks_pit_full_lead_overnight_hedge import build_signals


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_CRISIS_EVENTTIME_AUDIT_2026-09-17"
SOURCE_SIGNALS = Path("STOCKS_PIT_FULL_RESIDUAL_REVERSAL_COHORTS_2026-09-17_SIGNALS.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

SCENARIOS = [
    {"scenario": "control", "crisis_scale": 0.0, "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "base", "crisis_scale": 0.5, "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "cost8", "crisis_scale": 0.5, "cost_bps": 8.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "stress", "crisis_scale": 0.5, "cost_bps": 8.0, "financing": 0.05, "borrow": 0.02, "missing_bps": 25.0},
]


def crisis_weight_schedule(dates: list[pd.Timestamp], scale: float) -> dict[pd.Timestamp, pd.Series]:
    if scale == 0:
        return {date: pd.Series(dtype=float) for date in dates}
    signals = pd.read_csv(SOURCE_SIGNALS, parse_dates=["date", "entry_date"])
    signals = signals[signals["variant"].eq("market_resid_rev_10x10_hold3")].copy()
    regime = build_signals()[["date", "overnight20_negative"]].rename(columns={"date": "entry_date"})
    signals = signals.merge(regime, on="entry_date", how="left", validate="many_to_one")
    signals = signals[signals["overnight20_negative"].eq(True)]
    by_entry = {date: group for date, group in signals.groupby("entry_date", sort=True)}
    cohorts: list[tuple[int, pd.Series]] = []
    schedule = {}
    for day_index, date in enumerate(dates):
        cohorts = [(start, weights) for start, weights in cohorts if day_index - start < 3]
        new_signals = by_entry.get(date, signals.iloc[0:0])
        new_weights = residual.cohort_weights(new_signals, 3, gross_scale=scale)
        if not new_weights.empty:
            cohorts.append((day_index, new_weights))
        schedule[date] = residual.aggregate_cohorts(cohorts)
    return schedule


def add_pnl(rows: list[dict[str, object]], scenario: str, timestamp: pd.Timestamp, ticker: str, sleeve: str, pnl: float) -> None:
    if pnl != 0:
        rows.append({"scenario": scenario, "timestamp": timestamp, "ticker": ticker, "sleeve": sleeve, "pnl": pnl})


def simulate(
    scenario: dict[str, object], core: pd.DataFrame, spy: pd.DataFrame,
    pair_events: dict[pd.Timestamp, pd.DataFrame], p935: dict[pd.Timestamp, pd.Series],
    p1555: dict[pd.Timestamp, pd.Series], crisis_schedule: dict[pd.Timestamp, pd.Series],
    name_cap: float | None = None, hard_gross_cap: float | None = None,
    missing_name_limit: int | None = None, missing_notional_limit: float | None = None,
    mark935: dict[pd.Timestamp, pd.Series] | None = None,
    mark1555: dict[pd.Timestamp, pd.Series] | None = None,
    require_current_execution: bool = False,
    blocked_risk_increases: set[tuple[pd.Timestamp, str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    name = str(scenario["scenario"])
    cost_rate = float(scenario["cost_bps"]) / 10_000.0
    financing_rate = float(scenario["financing"]) / 252.0
    borrow_rate = float(scenario["borrow"]) / 252.0
    missing_rate = float(scenario["missing_bps"]) / 10_000.0
    enforce_missing_policy = require_current_execution or missing_name_limit is not None or missing_notional_limit is not None
    source = core.merge(spy, on="date", how="inner").sort_values("date").reset_index(drop=True)
    equity = base.START_CAPITAL
    pair_active: dict[str, dict[str, object]] = {}
    satellite_shares = pd.Series(dtype=float)
    satellite_last = pd.Series(dtype=float)
    spy_last = float(source.iloc[0]["prev_spy1555"])
    spy_target = equity * float(source.iloc[0]["spy_exposure"])
    initial_cost = abs(spy_target) * cost_rate
    equity -= initial_cost
    spy_shares = spy_target / spy_last
    contrib = []
    events = []
    first_ts = pd.Timestamp(source.iloc[0]["date"]) + pd.Timedelta(hours=9, minutes=29)
    add_pnl(contrib, name, first_ts, "SPY", "core", -initial_cost)
    events.append({"scenario": name, "timestamp": first_ts, "event": "initial_spy", "event_pnl": -initial_cost, "equity": equity, "gross_exposure": abs(spy_target) / equity, "turnover_cost": initial_cost, "financing_cost": 0.0, "borrow_cost": 0.0, "missing_penalty": 0.0, "missing_marks": 0})
    missing_marks = 0
    policy_disabled = False
    reenable_next_session = False
    fail_safe_breaches = 0
    name_cap_events = 0
    gross_cap_events = 0

    for index, row in source.iterrows():
        date = pd.Timestamp(row["date"])
        if reenable_next_session:
            policy_disabled = False
            reenable_next_session = False
        ts935 = date + pd.Timedelta(hours=9, minutes=35)
        ts1555 = date + pd.Timedelta(hours=15, minutes=55)
        prices935 = p935.get(date, pd.Series(dtype=float))
        prices1555 = p1555.get(date, pd.Series(dtype=float))
        marks935 = (mark935 if mark935 is not None else p935).get(date, pd.Series(dtype=float))
        marks1555 = (mark1555 if mark1555 is not None else p1555).get(date, pd.Series(dtype=float))

        spy_price935 = float(row["spy935"])
        spy_pnl = spy_shares * (spy_price935 - spy_last)
        equity += spy_pnl
        spy_last = spy_price935
        add_pnl(contrib, name, ts935, "SPY", "core", spy_pnl)

        satellite_pnl = 0.0
        missing_notional = 0.0
        missing_tickers_935: set[str] = set()
        for ticker, shares in satellite_shares.items():
            if ticker in marks935.index:
                price = float(marks935[ticker])
            else:
                price = float(satellite_last.get(ticker, np.nan))
                missing_notional += abs(float(shares) * price) if np.isfinite(price) else 0.0
                missing_marks += 1
                missing_tickers_935.add(str(ticker))
            if not np.isfinite(price):
                continue
            prior = float(satellite_last.get(ticker, price))
            pnl = float(shares) * (price - prior)
            satellite_pnl += pnl
            satellite_last.loc[ticker] = price
            add_pnl(contrib, name, ts935, ticker, "satellites", pnl)
        equity += satellite_pnl
        missing_penalty = missing_notional * missing_rate
        equity -= missing_penalty
        add_pnl(contrib, name, ts935, "_MISSING", "execution", -missing_penalty)
        fail_safe_935 = (
            (missing_name_limit is not None and len(missing_tickers_935) > missing_name_limit)
            or (missing_notional_limit is not None and missing_notional / max(equity, 1e-9) > missing_notional_limit)
        )
        if fail_safe_935:
            policy_disabled = True
            fail_safe_breaches += 1

        base.apply_trade_events(pair_active, pair_events.get(date, pd.DataFrame()))
        pair_weights = base.active_pair_weights(pair_active, base.PAIR_SCALE)
        crisis_weights = crisis_schedule.get(date, pd.Series(dtype=float))
        target_weights = pair_weights.add(crisis_weights, fill_value=0.0)
        if policy_disabled:
            target_weights = pd.Series(dtype=float)
        cap_scale = 1.0
        if name_cap is not None and not target_weights.empty:
            max_name = float(target_weights.abs().max())
            if max_name > name_cap:
                cap_scale = min(cap_scale, name_cap / max_name)
                name_cap_events += 1
        if hard_gross_cap is not None and not target_weights.empty:
            spy_gross = abs(spy_shares * spy_price935) / max(equity, 1e-9)
            satellite_gross_target = float(target_weights.abs().sum())
            allowed = max(hard_gross_cap - spy_gross, 0.0)
            if satellite_gross_target > allowed:
                cap_scale = min(cap_scale, allowed / satellite_gross_target if satellite_gross_target else 1.0)
                gross_cap_events += 1
        target_weights = target_weights * cap_scale
        tickers = satellite_shares.index.union(target_weights.index)
        target_dollars = target_weights.reindex(tickers).fillna(0.0) * equity
        current_dollars = pd.Series(0.0, index=tickers)
        execution_prices = pd.Series(index=tickers, dtype=float)
        blocked_tickers: list[str] = []
        for ticker in tickers:
            price = (
                float(prices935[ticker])
                if ticker in prices935.index
                else (float("nan") if enforce_missing_policy else float(satellite_last.get(ticker, np.nan)))
            )
            execution_prices.loc[ticker] = price
            mark_price = float(marks935[ticker]) if ticker in marks935.index else float(satellite_last.get(ticker, np.nan))
            if ticker in satellite_shares.index and np.isfinite(mark_price):
                current_dollars.loc[ticker] = float(satellite_shares[ticker]) * mark_price
            if enforce_missing_policy and ticker not in prices935.index:
                target_dollars.loc[ticker] = current_dollars.loc[ticker]
            if blocked_risk_increases is not None and (date, str(ticker)) in blocked_risk_increases:
                current = float(current_dollars.loc[ticker])
                target = float(target_dollars.loc[ticker])
                if current == 0.0 or target == 0.0:
                    target_dollars.loc[ticker] = 0.0
                elif np.sign(current) != np.sign(target):
                    target_dollars.loc[ticker] = 0.0
                elif abs(target) > abs(current):
                    target_dollars.loc[ticker] = current
                blocked_tickers.append(str(ticker))
        trade_dollars = (target_dollars - current_dollars).abs()
        turnover_cost = float(trade_dollars.sum()) * cost_rate
        equity -= turnover_cost
        if turnover_cost and float(trade_dollars.sum()) > 0:
            for ticker, value in trade_dollars.items():
                add_pnl(contrib, name, ts935, ticker, "satellites", -turnover_cost * float(value) / float(trade_dollars.sum()))
        new_shares = {}
        for ticker, target in target_dollars.items():
            price = float(execution_prices[ticker])
            if np.isfinite(price) and price > 0 and float(target) != 0:
                new_shares[ticker] = float(target) / price
                satellite_last.loc[ticker] = price
            elif float(target) != 0 and ticker in satellite_shares.index:
                # Missing exact execution freezes the existing position. The
                # as-of price is mark-only and must not synthesize a trade.
                new_shares[ticker] = float(satellite_shares[ticker])
        satellite_shares = pd.Series(new_shares, dtype=float)
        marked_satellite = satellite_shares * satellite_last.reindex(satellite_shares.index)
        gross935 = abs(spy_shares * spy_price935) / equity + float(marked_satellite.abs().sum()) / equity
        event_pnl = spy_pnl + satellite_pnl - missing_penalty - turnover_cost
        events.append({"scenario": name, "timestamp": ts935, "event": "mark_rebalance_0935", "event_pnl": event_pnl, "equity": equity, "gross_exposure": gross935, "turnover_cost": turnover_cost, "financing_cost": 0.0, "borrow_cost": 0.0, "missing_penalty": missing_penalty, "missing_marks": missing_marks, "missing_this_event": len(missing_tickers_935), "missing_tickers": "|".join(sorted(missing_tickers_935)), "missing_notional": missing_notional, "fail_safe_breach": fail_safe_935, "policy_disabled": policy_disabled, "target_cap_scale": cap_scale, "adv_blocked_count": len(blocked_tickers), "adv_blocked_tickers": "|".join(sorted(blocked_tickers))})

        spy_price1555 = float(row["spy1555"])
        spy_pnl = spy_shares * (spy_price1555 - spy_last)
        equity += spy_pnl
        spy_last = spy_price1555
        add_pnl(contrib, name, ts1555, "SPY", "core", spy_pnl)
        satellite_pnl = 0.0
        missing_notional = 0.0
        missing_tickers_1555: set[str] = set()
        for ticker, shares in satellite_shares.items():
            if ticker in marks1555.index:
                price = float(marks1555[ticker])
            else:
                price = float(satellite_last.get(ticker, np.nan))
                missing_notional += abs(float(shares) * price) if np.isfinite(price) else 0.0
                missing_marks += 1
                missing_tickers_1555.add(str(ticker))
            if not np.isfinite(price):
                continue
            prior = float(satellite_last.get(ticker, price))
            pnl = float(shares) * (price - prior)
            satellite_pnl += pnl
            satellite_last.loc[ticker] = price
            add_pnl(contrib, name, ts1555, ticker, "satellites", pnl)
        equity += satellite_pnl
        missing_penalty = missing_notional * missing_rate
        equity -= missing_penalty
        add_pnl(contrib, name, ts1555, "_MISSING", "execution", -missing_penalty)
        fail_safe_1555 = (
            (missing_name_limit is not None and len(missing_tickers_1555) > missing_name_limit)
            or (missing_notional_limit is not None and missing_notional / max(equity, 1e-9) > missing_notional_limit)
        )
        if fail_safe_1555:
            policy_disabled = True
            fail_safe_breaches += 1
        elif policy_disabled and not missing_tickers_935 and not missing_tickers_1555:
            reenable_next_session = True

        satellite_values = satellite_shares * satellite_last.reindex(satellite_shares.index)
        satellite_gross = float(satellite_values.abs().sum())
        short_gross = float(satellite_values[satellite_values < 0].abs().sum())
        gross_ratio = (abs(spy_shares * spy_price1555) + satellite_gross) / equity
        financing_cost = equity * max(gross_ratio - 1.0, 0.0) * financing_rate
        borrow_cost = short_gross * borrow_rate
        equity -= financing_cost + borrow_cost
        add_pnl(contrib, name, ts1555, "_FINANCING", "financing", -financing_cost)
        add_pnl(contrib, name, ts1555, "_BORROW", "borrow", -borrow_cost)

        spy_turnover_cost = 0.0
        if index + 1 < len(source):
            next_exposure = float(source.iloc[index + 1]["spy_exposure"])
            if policy_disabled:
                current_exposure = max(spy_shares * spy_price1555 / max(equity, 1e-9), 0.0)
                next_exposure = min(next_exposure, current_exposure)
            if hard_gross_cap is not None:
                satellite_current_gross = satellite_gross / max(equity, 1e-9)
                next_exposure = min(next_exposure, max(hard_gross_cap - satellite_current_gross, 0.0))
            target_spy = equity * next_exposure
            current_spy = spy_shares * spy_price1555
            spy_turnover_cost = abs(target_spy - current_spy) * cost_rate
            equity -= spy_turnover_cost
            spy_shares = target_spy / spy_price1555
            add_pnl(contrib, name, ts1555, "SPY", "core", -spy_turnover_cost)
        event_pnl = spy_pnl + satellite_pnl - missing_penalty - financing_cost - borrow_cost - spy_turnover_cost
        events.append({"scenario": name, "timestamp": ts1555, "event": "mark_rebalance_1555", "event_pnl": event_pnl, "equity": equity, "gross_exposure": gross_ratio, "turnover_cost": spy_turnover_cost, "financing_cost": financing_cost, "borrow_cost": borrow_cost, "missing_penalty": missing_penalty, "missing_marks": missing_marks, "missing_this_event": len(missing_tickers_1555), "missing_tickers": "|".join(sorted(missing_tickers_1555)), "missing_notional": missing_notional, "fail_safe_breach": fail_safe_1555, "policy_disabled": policy_disabled, "target_cap_scale": 1.0})

    events = pd.DataFrame(events)
    contrib = pd.DataFrame(contrib)
    daily = events.assign(date=events["timestamp"].dt.normalize()).groupby(["scenario", "date"], as_index=False).agg(
        daily_pnl=("event_pnl", "sum"), equity=("equity", "last"), max_gross=("gross_exposure", "max"),
        turnover_cost=("turnover_cost", "sum"), financing_cost=("financing_cost", "sum"), borrow_cost=("borrow_cost", "sum"),
        missing_penalty=("missing_penalty", "sum"), missing_marks=("missing_marks", "max"),
        fail_safe_breach=("fail_safe_breach", "max"), policy_disabled=("policy_disabled", "max"),
        min_target_cap_scale=("target_cap_scale", "min"),
    )
    daily["year"] = daily["date"].dt.year
    return daily, events, contrib


def main() -> None:
    core = base.load_core()
    dates = list(core["date"])
    spy = base.load_spy_prices(dates)
    common = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common)].copy()
    spy = spy[spy["date"].isin(common)].copy()
    dates = sorted(common)
    pair_events = base.load_pair_events()
    p935, p1555 = base.load_pair_prices(common)
    summaries = []
    yearly = []
    concentration = []
    daily_frames = []
    event_frames = []
    contrib_frames = []
    qa = []
    for scenario in SCENARIOS:
        schedule = crisis_weight_schedule(dates, float(scenario["crisis_scale"]))
        daily, events, contrib = simulate(scenario, core, spy, pair_events, p935, p1555, schedule)
        summaries.append(base.summary_row(scenario, daily, events))
        yearly.extend(base.yearly_rows(daily))
        concentration.extend(base.concentration_rows(str(scenario["scenario"]), contrib))
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - base.START_CAPITAL)
        qa.append({"scenario": scenario["scenario"], "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        daily_frames.append(daily)
        event_frames.append(events)
        contrib_frames.append(contrib)
        print("CRISIS_EVENTTIME", summaries[-1], flush=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENT_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_crisis_eventtime_audit.py",
        "inputs": [str(base.CORE_DAILY), str(base.PAIR_EVENTS), str(SOURCE_SIGNALS), str(base.PAIR_PRICES).replace("\\", "/"), str(base.SPY_BARS).replace("\\", "/")],
        "frozen_candidate": "Lead SPY core plus pairs 0.5x plus gated market-residual hold3 crisis sleeve 0.5x.",
        "method": "Single shared-equity event engine. SPY, pairs, and crisis constituents mark at 09:35 and 15:55. Pair and crisis ticker targets are netted before turnover, financing, and borrow.",
        "scenarios": SCENARIOS,
        "sample_label": "Touched research 2018-2024 only. No 2025-2026 opened.",
        "selection_warning": "Crisis source and gate were selected after observing 2022. Exact execution removes clock/accounting ambiguity but cannot create clean OOS evidence.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(EVENT_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, EVENT_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
