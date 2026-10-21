from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


PROTOCOL = Path("STOCKS_MULTISLEEVE_FORWARD_PAPER_PROTOCOL_2026-09-24.json")
POST_2024_GUARD = pd.Timestamp("2024-12-31")
SOURCE_WEIGHTS = {"pairs": 0.75, "calendar": 0.25}
SOURCE_CLOCKS = {"pairs": "0935", "calendar": "1555"}
FLAT_TICKER = "__FLAT__"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


@dataclass
class AccountState:
    name: str
    scale: float
    gross_cap: float
    dd_halt: float
    initial_equity: float
    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    last_prices: dict[str, float] = field(default_factory=dict)
    asset_types: dict[str, str] = field(default_factory=dict)
    stale_sessions: dict[str, int] = field(default_factory=dict)
    stale_increment_date: dict[str, pd.Timestamp] = field(default_factory=dict)
    peak_equity: float = 0.0
    prior_event_equity: float = 0.0
    status: str = "ACTIVE"
    hard_violations: int = 0

    def __post_init__(self) -> None:
        self.peak_equity = self.initial_equity
        self.prior_event_equity = self.initial_equity


def load_protocol() -> dict[str, object]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    expected = protocol["implementation_freeze"]["script_hash"]
    if expected.startswith("TO_BE_"):
        raise RuntimeError("Protocol script hash has not been frozen")
    if expected != sha256(Path(__file__)):
        raise RuntimeError("Runner hash does not match frozen protocol")
    return protocol


def load_inputs(target_path: Path, market_path: Path, allow_post_2024: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    targets = pd.read_csv(target_path, dtype={"clock": str})
    market = pd.read_csv(market_path, dtype={"clock": str})
    target_required = {"effective_date", "clock", "signal_timestamp", "source", "ticker", "source_target_weight"}
    market_required = {"effective_date", "clock", "timestamp", "ticker", "price", "adv20", "borrow_available", "asset_type"}
    if missing := target_required.difference(targets.columns):
        raise ValueError(f"Targets missing columns: {sorted(missing)}")
    if missing := market_required.difference(market.columns):
        raise ValueError(f"Market missing columns: {sorted(missing)}")
    for frame in (targets, market):
        frame["effective_date"] = pd.to_datetime(frame["effective_date"], errors="raise").dt.normalize()
        frame["clock"] = frame["clock"].astype(str).str.zfill(4)
        frame["ticker"] = frame["ticker"].astype(str).str.upper().str.strip()
    targets["signal_timestamp"] = pd.to_datetime(targets["signal_timestamp"], utc=True, errors="raise")
    market["timestamp"] = pd.to_datetime(market["timestamp"], utc=True, errors="raise")
    targets["source_target_weight"] = pd.to_numeric(targets["source_target_weight"], errors="raise")
    market["price"] = pd.to_numeric(market["price"], errors="raise")
    market["adv20"] = pd.to_numeric(market["adv20"], errors="raise")
    market["borrow_available"] = market["borrow_available"].map(parse_bool)
    if not set(targets["clock"]).issubset({"0935", "1555"}) or not set(market["clock"]).issubset({"0935", "1555"}):
        raise ValueError("Only 0935 and 1555 clocks are allowed")
    if not set(targets["source"]).issubset(SOURCE_WEIGHTS):
        raise ValueError("Unknown target source")
    bad_clock = targets[targets.apply(lambda row: SOURCE_CLOCKS[row["source"]] != row["clock"], axis=1)]
    if not bad_clock.empty:
        raise ValueError("Target source is assigned to the wrong execution clock")
    if not set(market["asset_type"]).issubset({"stock", "etf"}):
        raise ValueError("asset_type must be stock or etf")
    if (market["price"] <= 0).any() or (market["adv20"] < 0).any():
        raise ValueError("Market price must be positive and ADV nonnegative")
    if targets.duplicated(["effective_date", "clock", "source", "ticker"]).any():
        raise ValueError("Duplicate target rows")
    if market.duplicated(["effective_date", "clock", "ticker"]).any():
        raise ValueError("Duplicate market rows")
    if market.groupby(["effective_date", "clock"])["timestamp"].nunique().gt(1).any():
        raise ValueError("Each date/clock market packet must have one timestamp")
    event_times = market[["effective_date", "clock", "timestamp"]].drop_duplicates()
    checked = targets.merge(event_times, on=["effective_date", "clock"], how="left", validate="many_to_one")
    if checked["timestamp"].isna().any():
        raise ValueError("Every target snapshot requires a matching market packet")
    if (checked["signal_timestamp"] > checked["timestamp"]).any():
        raise ValueError("Causality violation: signal timestamp is after fill timestamp")
    if not allow_post_2024 and max(targets["effective_date"].max(), market["effective_date"].max()) > POST_2024_GUARD:
        raise RuntimeError("Post-2024 input refused; explicit --allow-post-2024 approval is required")
    flat = targets[targets["ticker"].eq(FLAT_TICKER)]
    if (flat["source_target_weight"].abs() > 1e-12).any():
        raise ValueError("__FLAT__ rows must have zero weight")
    return targets.sort_values(["effective_date", "clock", "source", "ticker"]), market.sort_values("timestamp")


def marked_equity(state: AccountState) -> float:
    return float(state.cash + sum(shares * state.last_prices[ticker] for ticker, shares in state.positions.items()))


def source_target_update(source_targets: dict[str, dict[str, float]], packet: pd.DataFrame) -> None:
    for source, group in packet.groupby("source", sort=True):
        declares_flat = group["ticker"].eq(FLAT_TICKER).any()
        snapshot = {
            str(row.ticker): float(row.source_target_weight)
            for row in group.itertuples(index=False)
            if str(row.ticker) != FLAT_TICKER and abs(float(row.source_target_weight)) > 1e-15
        }
        if not snapshot and not declares_flat:
            raise ValueError(f"Empty {source} snapshot must contain {FLAT_TICKER}")
        if source == "pairs" and sum(abs(value) for value in snapshot.values()) > 1.000001:
            raise ValueError("Pair source target gross exceeds 1.0")
        if source == "calendar" and (set(snapshot).difference({"SPY"}) or any(value not in {0.0, 2.5} for value in snapshot.values())):
            raise ValueError("Calendar source must be SPY exposure 0.0 or 2.5")
        source_targets[source] = snapshot


def aggregate_targets(source_targets: dict[str, dict[str, float]], state: AccountState) -> dict[str, float]:
    combined: dict[str, float] = {}
    for source, snapshot in source_targets.items():
        multiplier = SOURCE_WEIGHTS[source] * state.scale
        for ticker, source_weight in snapshot.items():
            combined[ticker] = combined.get(ticker, 0.0) + source_weight * multiplier
    return combined


def target_with_caps(
    raw_targets: dict[str, float], state: AccountState, market_map: dict[str, object], protocol: dict[str, object]
) -> tuple[dict[str, float], list[dict[str, object]]]:
    policy = protocol["execution_policy"]
    capped: dict[str, float] = {}
    issues: list[dict[str, object]] = []
    for ticker, weight in raw_targets.items():
        row = market_map.get(ticker)
        asset_type = str(row.asset_type) if row is not None else state.asset_types.get(ticker)
        if asset_type is None:
            issues.append({"ticker": ticker, "reason": "missing_asset_type"})
            continue
        limit = float(policy["etf_single_name_abs_weight_cap"] if asset_type == "etf" else policy["stock_single_name_abs_weight_cap"])
        capped[ticker] = float(np.clip(weight, -limit, limit))
        if abs(weight) > limit + 1e-12:
            issues.append({"ticker": ticker, "reason": "single_name_cap", "requested_weight": weight, "capped_weight": capped[ticker]})
    gross = sum(abs(value) for value in capped.values())
    if gross > state.gross_cap:
        factor = state.gross_cap / gross
        capped = {ticker: weight * factor for ticker, weight in capped.items()}
        issues.append({"ticker": "__BOOK__", "reason": "gross_cap", "requested_gross": gross, "scale_factor": factor})
    return capped, issues


def run_account_event(
    state: AccountState,
    event_date: pd.Timestamp,
    clock: str,
    timestamp: pd.Timestamp,
    market_packet: pd.DataFrame,
    source_targets: dict[str, dict[str, float]],
    rebalance_tickers: set[str],
    protocol: dict[str, object],
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    policy = protocol["execution_policy"]
    market_map = {row.ticker: row for row in market_packet.itertuples(index=False)}
    ticker_pnl: dict[str, dict[str, float]] = {}
    issues: list[dict[str, object]] = []
    for ticker, shares in list(state.positions.items()):
        old_price = state.last_prices[ticker]
        row = market_map.get(ticker)
        if row is None:
            if state.stale_increment_date.get(ticker) != event_date:
                state.stale_sessions[ticker] = state.stale_sessions.get(ticker, 0) + 1
                state.stale_increment_date[ticker] = event_date
            issues.append({"ticker": ticker, "reason": "missing_position_mark", "stale_sessions": state.stale_sessions[ticker]})
            if state.stale_sessions[ticker] > 1:
                state.hard_violations += 1
            continue
        new_price = float(row.price)
        ticker_pnl.setdefault(ticker, {"mark_pnl": 0.0, "slippage_cost": 0.0, "borrow_cost": 0.0, "financing_cost": 0.0})
        ticker_pnl[ticker]["mark_pnl"] += shares * (new_price - old_price)
        state.last_prices[ticker] = new_price
        state.asset_types[ticker] = str(row.asset_type)
        state.stale_sessions[ticker] = 0

    borrow_cost = 0.0
    financing_cost = 0.0
    equity_before_carry = marked_equity(state)
    values_before = {ticker: shares * state.last_prices[ticker] for ticker, shares in state.positions.items()}
    if clock == "1555" and equity_before_carry > 0:
        short_values = {ticker: abs(value) for ticker, value in values_before.items() if value < 0}
        short_gross = sum(short_values.values())
        gross_dollars = sum(abs(value) for value in values_before.values())
        borrow_cost = short_gross * float(policy["short_borrow_annual_rate"]) / 252.0
        financing_cost = max(gross_dollars - equity_before_carry, 0.0) * float(policy["financing_annual_rate_on_gross_above_1x"]) / 252.0
        state.cash -= borrow_cost + financing_cost
        if short_gross > 0:
            for ticker, value in short_values.items():
                ticker_pnl.setdefault(ticker, {"mark_pnl": 0.0, "slippage_cost": 0.0, "borrow_cost": 0.0, "financing_cost": 0.0})
                ticker_pnl[ticker]["borrow_cost"] += borrow_cost * value / short_gross
        if gross_dollars > 0:
            for ticker, value in values_before.items():
                ticker_pnl.setdefault(ticker, {"mark_pnl": 0.0, "slippage_cost": 0.0, "borrow_cost": 0.0, "financing_cost": 0.0})
                ticker_pnl[ticker]["financing_cost"] += financing_cost * abs(value) / gross_dollars

    pretrade_equity = marked_equity(state)
    raw_targets = {} if state.status.startswith("HALTED") else aggregate_targets(source_targets, state)
    target_weights, cap_issues = target_with_caps(raw_targets, state, market_map, protocol)
    issues.extend(cap_issues)
    stale_risk_freeze = any(value > 0 for value in state.stale_sessions.values())
    order_rows: list[dict[str, object]] = []
    all_tickers = sorted(set(state.positions).union(target_weights) if state.status.startswith("HALTED") else rebalance_tickers)
    turnover_dollars = 0.0
    slippage_cost = 0.0
    for ticker in all_tickers:
        current_shares = state.positions.get(ticker, 0.0)
        row = market_map.get(ticker)
        requested_weight = target_weights.get(ticker, 0.0)
        if row is None:
            order_rows.append({"ticker": ticker, "requested_weight": requested_weight, "requested_shares": np.nan,
                "filled_shares": 0.0, "fill_price": np.nan, "status": "REJECTED", "reason": "missing_exact_price"})
            continue
        price = float(row.price)
        desired_shares = requested_weight * pretrade_equity / price
        requested_delta = desired_shares - current_shares
        fill_delta = requested_delta
        reasons: list[str] = []
        if stale_risk_freeze and abs(desired_shares) > abs(current_shares) + 1e-12:
            fill_delta = 0.0
            reasons.append("stale_book_risk_freeze")
        if desired_shares < 0 and desired_shares < current_shares and not bool(row.borrow_available):
            fill_delta = -current_shares if current_shares > 0 else max(fill_delta, 0.0)
            reasons.append("borrow_unavailable")
        adv_limit = float(row.adv20) * float(policy["order_adv_participation_cap"])
        requested_notional = abs(fill_delta) * price
        if requested_notional > adv_limit and price > 0:
            fill_delta = math.copysign(adv_limit / price, fill_delta)
            reasons.append("adv_partial")
        if abs(fill_delta) <= 1e-12:
            status = "REJECTED" if abs(requested_delta) > 1e-12 else "NO_ORDER"
            order_rows.append({"ticker": ticker, "requested_weight": requested_weight, "requested_shares": requested_delta,
                "filled_shares": 0.0, "fill_price": np.nan, "status": status, "reason": "|".join(reasons)})
            continue
        fill_price = price * (1.0 + math.copysign(float(policy["simulated_half_spread_and_slippage_bps_per_traded_dollar"]) / 10_000.0, fill_delta))
        cost = abs(fill_delta) * abs(fill_price - price)
        state.cash -= fill_delta * fill_price
        new_shares = current_shares + fill_delta
        if abs(new_shares) <= 1e-12:
            state.positions.pop(ticker, None)
        else:
            state.positions[ticker] = new_shares
        state.last_prices[ticker] = price
        state.asset_types[ticker] = str(row.asset_type)
        state.stale_sessions[ticker] = 0
        turnover_dollars += abs(fill_delta) * price
        slippage_cost += cost
        ticker_pnl.setdefault(ticker, {"mark_pnl": 0.0, "slippage_cost": 0.0, "borrow_cost": 0.0, "financing_cost": 0.0})
        ticker_pnl[ticker]["slippage_cost"] += cost
        order_rows.append({"ticker": ticker, "requested_weight": requested_weight, "requested_shares": requested_delta,
            "filled_shares": fill_delta, "fill_price": fill_price, "status": "PARTIAL" if abs(fill_delta - requested_delta) > 1e-10 else "FILLED",
            "reason": "|".join(reasons)})

    ending_equity = marked_equity(state)
    state.peak_equity = max(state.peak_equity, ending_equity)
    drawdown_dollar = ending_equity - state.peak_equity
    drawdown_pct = ending_equity / state.peak_equity - 1.0 if state.peak_equity > 0 else -1.0
    if drawdown_pct <= state.dd_halt and state.status == "ACTIVE":
        state.status = "HALTED_DRAWDOWN"
        issues.append({"ticker": "__BOOK__", "reason": "drawdown_halt", "drawdown_pct": drawdown_pct})
    values_after = {ticker: shares * state.last_prices[ticker] for ticker, shares in state.positions.items()}
    gross_dollars = sum(abs(value) for value in values_after.values())
    net_dollars = sum(values_after.values())
    gross = gross_dollars / max(ending_equity, 1e-9)
    net = net_dollars / max(ending_equity, 1e-9)
    if gross > state.gross_cap + 1e-6:
        state.hard_violations += 1
        issues.append({"ticker": "__BOOK__", "reason": "post_fill_gross_violation", "gross": gross})
    event_pnl = ending_equity - state.prior_event_equity
    pnl_rows = []
    for ticker, components in ticker_pnl.items():
        pnl_rows.append({"ticker": ticker, **components, "net_pnl": components["mark_pnl"] - components["slippage_cost"] - components["borrow_cost"] - components["financing_cost"]})
    event_row = {
        "equity": ending_equity, "cash": state.cash, "event_pnl": event_pnl, "gross": gross, "net": net,
        "turnover_dollars": turnover_dollars, "turnover": turnover_dollars / max(pretrade_equity, 1e-9),
        "slippage_cost": slippage_cost, "borrow_cost": borrow_cost, "financing_cost": financing_cost,
        "drawdown_dollar": drawdown_dollar, "drawdown_pct": drawdown_pct, "positions": len(state.positions),
        "stale_positions": sum(value > 0 for value in state.stale_sessions.values()), "status": state.status,
        "hard_violations": state.hard_violations,
    }
    position_rows = [
        {"ticker": ticker, "shares": shares, "mark_price": state.last_prices[ticker], "market_value": values_after[ticker],
         "actual_weight": values_after[ticker] / max(ending_equity, 1e-9), "target_weight": target_weights.get(ticker, 0.0),
         "asset_type": state.asset_types[ticker], "stale_sessions": state.stale_sessions.get(ticker, 0)}
        for ticker, shares in sorted(state.positions.items())
    ]
    issue_rows = [{**issue, "issue_type": "HARD" if issue.get("reason") in {"drawdown_halt", "post_fill_gross_violation"} or issue.get("stale_sessions", 0) > 1 else "CONTROL"} for issue in issues]
    state.prior_event_equity = ending_equity
    return event_row, order_rows, position_rows, pnl_rows + issue_rows


def concentration(ticker_pnl: pd.DataFrame, total_pnl: float) -> dict[str, object]:
    if ticker_pnl.empty:
        return {"effectiveTickerCount": 0.0, **{f"top{n}Share": np.nan for n in (1, 3, 5, 10)}}
    by = ticker_pnl.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
    positive = by[by > 0]
    effective = float(positive.sum() ** 2 / positive.pow(2).sum()) if not positive.empty else 0.0
    denominator = total_pnl if total_pnl > 0 else float(positive.sum())
    result: dict[str, object] = {"effectiveTickerCount": effective, "topTicker": by.index[0] if len(by) else None}
    for count in (1, 3, 5, 10):
        result[f"top{count}Share"] = float(by.head(count).sum() / denominator) if denominator > 0 else np.nan
    return result


def run_batch(targets: pd.DataFrame, market: pd.DataFrame, protocol: dict[str, object]) -> dict[str, pd.DataFrame]:
    accounts = [
        AccountState(
            name=str(spec["account"]), scale=float(spec["scale"]), gross_cap=float(spec["gross_cap"]),
            dd_halt=float(spec["max_drawdown_halt"]), initial_equity=float(spec["initial_equity"]), cash=float(spec["initial_equity"]),
        )
        for spec in protocol["accounts"]
    ]
    source_targets: dict[str, dict[str, float]] = {"pairs": {}, "calendar": {}}
    events: list[dict[str, object]] = []
    orders: list[dict[str, object]] = []
    positions: list[dict[str, object]] = []
    pnl_rows: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    market_events = market[["effective_date", "clock", "timestamp"]].drop_duplicates().sort_values("timestamp")
    for event in market_events.itertuples(index=False):
        target_packet = targets[(targets["effective_date"].eq(event.effective_date)) & targets["clock"].eq(event.clock)]
        updated_sources = set(target_packet["source"])
        prior_source_tickers = {source: set(source_targets[source]) for source in updated_sources}
        source_target_update(source_targets, target_packet)
        rebalance_tickers = set().union(*(
            prior_source_tickers[source].union(source_targets[source]) for source in updated_sources
        )) if updated_sources else set()
        market_packet = market[(market["effective_date"].eq(event.effective_date)) & market["clock"].eq(event.clock)]
        for state in accounts:
            event_row, order_rows, position_rows, mixed_rows = run_account_event(
                state, event.effective_date, event.clock, event.timestamp, market_packet, source_targets, rebalance_tickers, protocol
            )
            common = {"account": state.name, "effective_date": event.effective_date, "clock": event.clock, "timestamp": event.timestamp}
            events.append({**common, **event_row})
            orders.extend({**common, **row} for row in order_rows)
            positions.extend({**common, **row} for row in position_rows)
            for row in mixed_rows:
                if "issue_type" in row:
                    issues.append({**common, **row})
                else:
                    pnl_rows.append({**common, **row})
    event_df = pd.DataFrame(events)
    order_df = pd.DataFrame(orders)
    position_df = pd.DataFrame(positions)
    pnl_df = pd.DataFrame(pnl_rows)
    issue_df = pd.DataFrame(issues)
    summary_rows = []
    qa_rows = []
    for state in accounts:
        account_events = event_df[event_df["account"].eq(state.name)].copy()
        account_pnl = pnl_df[pnl_df["account"].eq(state.name)].copy()
        start = account_events.iloc[0]
        end = account_events.iloc[-1]
        total_pnl = float(end["equity"] - state.initial_equity)
        peak = account_events["equity"].cummax()
        years = max((account_events["effective_date"].max() - account_events["effective_date"].min()).days / 365.25, 1 / 365.25)
        returns = account_events["event_pnl"] / (account_events["equity"] - account_events["event_pnl"]).clip(lower=1e-9)
        sharpe = float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else np.nan
        summary_rows.append({
            "account": state.name, "start": start["effective_date"], "end": end["effective_date"],
            "sessions": int(account_events["effective_date"].nunique()), "events": len(account_events),
            "endingEquity": float(end["equity"]), "pnl": total_pnl,
            "cagr": float((end["equity"] / state.initial_equity) ** (1 / years) - 1.0), "sharpe": sharpe,
            "ddDollar": float((account_events["equity"] - peak).min()), "ddPct": float((account_events["equity"] / peak - 1.0).min()),
            "maxGross": float(account_events["gross"].max()), "maxNetAbs": float(account_events["net"].abs().max()),
            "turnoverDollars": float(account_events["turnover_dollars"].sum()),
            "slippageCost": float(account_events["slippage_cost"].sum()), "borrowCost": float(account_events["borrow_cost"].sum()),
            "financingCost": float(account_events["financing_cost"].sum()),
            "rejectedOrders": int(order_df[(order_df["account"].eq(state.name)) & order_df["status"].eq("REJECTED")].shape[0]),
            "partialOrders": int(order_df[(order_df["account"].eq(state.name)) & order_df["status"].eq("PARTIAL")].shape[0]),
            "hardViolations": int(state.hard_violations), "status": state.status, **concentration(account_pnl, total_pnl),
        })
        ticker_total = float(account_pnl["net_pnl"].sum()) if not account_pnl.empty else 0.0
        qa_rows.append({
            "account": state.name, "endingMinusInitial": total_pnl, "eventPnl": float(account_events["event_pnl"].sum()),
            "tickerPnl": ticker_total, "eventReconciliation": total_pnl - float(account_events["event_pnl"].sum()),
            "tickerReconciliation": total_pnl - ticker_total,
            "maxBalanceSheetError": float((account_events["equity"] - account_events["cash"] - position_df[position_df["account"].eq(state.name)].groupby("timestamp")["market_value"].sum().reindex(account_events["timestamp"]).fillna(0.0).to_numpy()).abs().max()),
        })
    return {
        "ACCOUNT_EVENTS": event_df, "ORDERS": order_df, "POSITIONS": position_df, "TICKER_PNL": pnl_df,
        "ISSUES": issue_df, "SUMMARY": pd.DataFrame(summary_rows), "QA": pd.DataFrame(qa_rows),
    }


def self_test(protocol: dict[str, object]) -> None:
    dates = [pd.Timestamp("2024-12-27"), pd.Timestamp("2024-12-30")]
    target_rows = []
    market_rows = []
    for index, date in enumerate(dates):
        for clock, hour, minute in (("0935", 14, 35), ("1555", 20, 55)):
            timestamp = pd.Timestamp(date.date(), tz="UTC") + pd.Timedelta(hours=hour, minutes=minute)
            for ticker, price, asset, borrow in (("AAA", 100 + index, "stock", True), ("BBB", 50 - index, "stock", True), ("SPY", 400 + index, "etf", True)):
                market_rows.append({"effective_date": date, "clock": clock, "timestamp": timestamp, "ticker": ticker,
                    "price": price, "adv20": 100_000_000.0, "borrow_available": borrow, "asset_type": asset})
            if clock == "0935":
                if index == 0:
                    target_rows.extend([
                        {"effective_date": date, "clock": clock, "signal_timestamp": timestamp - pd.Timedelta(minutes=1), "source": "pairs", "ticker": "AAA", "source_target_weight": 0.5},
                        {"effective_date": date, "clock": clock, "signal_timestamp": timestamp - pd.Timedelta(minutes=1), "source": "pairs", "ticker": "BBB", "source_target_weight": -0.5},
                    ])
                else:
                    target_rows.append({"effective_date": date, "clock": clock, "signal_timestamp": timestamp - pd.Timedelta(minutes=1), "source": "pairs", "ticker": FLAT_TICKER, "source_target_weight": 0.0})
            else:
                target_rows.append({"effective_date": date, "clock": clock, "signal_timestamp": timestamp - pd.Timedelta(minutes=1), "source": "calendar", "ticker": "SPY" if index == 0 else FLAT_TICKER, "source_target_weight": 2.5 if index == 0 else 0.0})
    targets = pd.DataFrame(target_rows)
    market = pd.DataFrame(market_rows)
    results = run_batch(targets, market, protocol)
    assert len(results["SUMMARY"]) == 2
    assert results["QA"]["eventReconciliation"].abs().max() < 1e-8
    assert results["QA"]["tickerReconciliation"].abs().max() < 1e-8
    assert results["QA"]["maxBalanceSheetError"].abs().max() < 1e-8
    assert results["ACCOUNT_EVENTS"].groupby("account")["gross"].max().le(pd.Series({"lead_1x_primary": 1.4, "lead_15x_challenger": 2.1})).all()
    print("SELF_TEST_PASS")
    print(results["SUMMARY"].to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic forward-paper execution runner for the frozen 75/25 lead.")
    parser.add_argument("--targets", type=Path)
    parser.add_argument("--market", type=Path)
    parser.add_argument("--output-prefix", default="STOCKS_MULTISLEEVE_FORWARD_PAPER")
    parser.add_argument("--allow-post-2024", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    protocol = load_protocol()
    if args.self_test:
        self_test(protocol)
        return
    if args.targets is None or args.market is None:
        parser.error("--targets and --market are required unless --self-test is used")
    targets, market = load_inputs(args.targets, args.market, args.allow_post_2024)
    results = run_batch(targets, market, protocol)
    for suffix, frame in results.items():
        frame.to_csv(f"{args.output_prefix}_{suffix}.csv", index=False)
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "protocol": str(PROTOCOL), "protocolHash": sha256(PROTOCOL),
        "targets": str(args.targets).replace("\\", "/"), "targetsHash": sha256(args.targets),
        "market": str(args.market).replace("\\", "/"), "marketHash": sha256(args.market),
        "post2024Override": bool(args.allow_post_2024), "accounts": protocol["accounts"],
        "outputs": [f"{args.output_prefix}_{suffix}.csv" for suffix in results],
        "productionPassAllowed": False,
    }
    Path(f"{args.output_prefix}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(results["SUMMARY"].to_string(index=False))
    print(results["QA"].to_string(index=False))


if __name__ == "__main__":
    main()
