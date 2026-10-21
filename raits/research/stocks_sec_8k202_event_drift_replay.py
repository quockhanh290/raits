from __future__ import annotations

import argparse
import json
import math
import pickle
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_SEC_8K202_EVENT_DRIFT_PREREG_2026-09-17.json")
SEC_EVENTS = Path("raits/data/cache/external_events/sec_submissions_pit_2018_2026/sec_8k_item_202_events_2017_2026.csv")
OLD_DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
OLD_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
OOS_DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2025_2026_CLEAN_OOS.pkl")
OOS_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2025_2026_CLEAN_OOS.pkl")
CAP_PATHS = [
    Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"),
    Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2025_2026_clean_oos.csv"),
]
FILTER_PATHS = [
    Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet"),
    Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20250102_20260916_clean_oos/liquidity_filter_daily_20250102_20260916_clean_oos_px5_adv10m_unadjusted/filtered_daily_universe.parquet"),
]
DEV_PREFIX = "STOCKS_SEC_8K202_EVENT_DRIFT_DEV_2026-09-17"
OOS_PREFIX = "STOCKS_SEC_8K202_EVENT_DRIFT_OOS_2026-09-17"
DEV_SELECTION = Path(f"{DEV_PREFIX}_SELECTION.json")
OOS_FREEZE = Path("STOCKS_SEC_8K202_EVENT_DRIFT_OOS_FROZEN_2026-09-17.json")
START_CAPITAL = 100_000.0


def normalize_cik(values: pd.Series) -> pd.Series:
    return values.astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(10)


def stage_contract(stage: str) -> tuple[pd.Timestamp, pd.Timestamp, Path, Path, str]:
    if stage == "development":
        return pd.Timestamp("2018-01-02"), pd.Timestamp("2024-12-31"), OLD_DAILY, OLD_0935, DEV_PREFIX
    return pd.Timestamp("2025-01-02"), pd.Timestamp("2026-09-16"), OOS_DAILY, OOS_0935, OOS_PREFIX


def stage_previous_cutoff(stage: str) -> pd.Timestamp:
    previous_session = "2017-12-29" if stage == "development" else "2024-12-31"
    return (pd.Timestamp(previous_session).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=15)).tz_convert("UTC")


def load_features(daily_path: Path, intra_path: Path, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pd.read_pickle(daily_path)[["date", "ticker", "gap"]].copy()
    intra = pd.read_pickle(intra_path)[["date", "ticker", "entry935", "exit1555", "first5_ret", "rvol930"]].copy()
    for frame in (daily, intra):
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        frame.drop(frame[(frame["date"] < start) | (frame["date"] > end)].index, inplace=True)
    return daily, intra


def load_top500_representatives(stage: str) -> pd.DataFrame:
    paths = CAP_PATHS[:1] if stage == "development" else CAP_PATHS[1:]
    filter_paths = FILTER_PATHS[:1] if stage == "development" else FILTER_PATHS[1:]
    caps = []
    for path in paths:
        frame = pd.read_csv(path, low_memory=False)
        frame["snapshot_date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker_query"].astype(str).str.upper()
        frame["market_cap"] = pd.to_numeric(frame["market_cap"], errors="coerce")
        frame = frame[frame["status_code"].eq(200) & frame["market_cap"].notna()].copy()
        frame["rank_market_cap"] = frame.groupby("snapshot_date")["market_cap"].rank(method="first", ascending=False)
        caps.append(frame[frame["rank_market_cap"].le(500)][["snapshot_date", "ticker", "market_cap"]])
    cap = pd.concat(caps, ignore_index=True)
    identities = []
    for path in filter_paths:
        frame = pd.read_parquet(path, columns=["date", "ticker", "cik", "security_id"])
        frame["snapshot_date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        identities.append(frame[["snapshot_date", "ticker", "cik", "security_id"]])
    identity = pd.concat(identities, ignore_index=True).drop_duplicates(["snapshot_date", "ticker"])
    members = cap.merge(identity, on=["snapshot_date", "ticker"], how="left", validate="one_to_one")
    members["cik"] = normalize_cik(members["cik"])
    members = members[members["cik"].notna() & ~members["cik"].eq("0000000000")].copy()
    members = members.sort_values(["snapshot_date", "cik", "market_cap", "ticker"], ascending=[True, True, False, True])
    return members.drop_duplicates(["snapshot_date", "cik"], keep="first")


def load_eligible(stage: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    paths = FILTER_PATHS[:1] if stage == "development" else FILTER_PATHS[1:]
    frames = []
    for path in paths:
        frame = pd.read_parquet(
            path,
            columns=["date", "ticker", "adv20"],
            filters=[("date", ">=", start.date()), ("date", "<=", end.date()), ("eligible_final", "==", True)],
        )
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).groupby(["date", "ticker"], as_index=False)["adv20"].min()


def assign_sessions(events: pd.DataFrame, sessions: list[pd.Timestamp], lower_bound: pd.Timestamp) -> pd.DataFrame:
    cutoffs = pd.DatetimeIndex(
        [date.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=15) for date in sessions]
    ).tz_convert("UTC")
    accepted = pd.to_datetime(events["accepted_et"], utc=True, errors="coerce")
    indices = np.searchsorted(cutoffs.asi8, accepted.astype("int64").to_numpy(), side="right")
    valid = accepted.notna().to_numpy() & accepted.ge(lower_bound).to_numpy() & (indices < len(sessions))
    out = events.loc[valid].copy()
    out["accepted_utc"] = accepted.loc[valid].to_numpy()
    out["date"] = [sessions[index] for index in indices[valid]]
    return out.sort_values(["cik", "date", "accepted_utc", "accessionNumber"]).drop_duplicates(["cik", "date"], keep="first")


def build_signals(stage: str, start: pd.Timestamp, end: pd.Timestamp, daily: pd.DataFrame, intra: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    sessions = sorted(intra["date"].drop_duplicates())
    raw_events = pd.read_csv(SEC_EVENTS, dtype={"cik": str})
    raw_events["cik"] = raw_events["cik"].astype(str).str.zfill(10)
    assigned = assign_sessions(raw_events, sessions, stage_previous_cutoff(stage))
    assigned = assigned[(assigned["date"] >= start) & (assigned["date"] <= end)].copy()

    members = load_top500_representatives(stage)
    dates = pd.DataFrame({"date": sessions})
    snapshots = members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned_snapshots = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    assigned = assigned.merge(assigned_snapshots, on="date", how="left", validate="many_to_one")
    mapped = assigned.merge(members, on=["snapshot_date", "cik"], how="inner", validate="many_to_one")

    eligible = load_eligible(stage, start, end)
    panel = mapped.merge(eligible, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.merge(daily, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.merge(intra, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=["gap", "rvol930", "first5_ret", "entry935", "exit1555", "adv20"])
    panel["confirmed"] = (
        panel["gap"].abs().ge(0.02)
        & panel["rvol930"].ge(1.5)
        & panel["first5_ret"].abs().ge(0.0025)
        & np.sign(panel["gap"]).eq(np.sign(panel["first5_ret"]))
    )
    signals = panel[panel["confirmed"]].copy()
    signals["direction"] = np.sign(signals["gap"]).astype(int)
    signals["advParticipationAt3Pct"] = (START_CAPITAL * 0.03) / signals["adv20"]
    signals = signals.sort_values(["date", "cik", "ticker"]).drop_duplicates(["date", "cik"], keep="first")
    return mapped, signals


def price_maps(intra: pd.DataFrame) -> tuple[dict[pd.Timestamp, pd.Series], dict[pd.Timestamp, pd.Series]]:
    p935 = {date: group.set_index("ticker")["entry935"] for date, group in intra[intra["entry935"] > 0].groupby("date", sort=True)}
    p1555 = {date: group.set_index("ticker")["exit1555"] for date, group in intra[intra["exit1555"] > 0].groupby("date", sort=True)}
    return p935, p1555


def add_contrib(rows: list[dict[str, object]], scenario: str, timestamp: pd.Timestamp, ticker: str, sleeve: str, pnl: float) -> None:
    if pnl != 0.0:
        rows.append({"scenario": scenario, "timestamp": timestamp, "ticker": ticker, "sleeve": sleeve, "pnl": pnl})


def enforce_gross_cap(
    active: dict[str, dict[str, object]],
    last_prices: pd.Series,
    exact_prices: pd.Series,
    equity: float,
    cost_rate: float,
    scenario: str,
    timestamp: pd.Timestamp,
    trade_rows: list[dict[str, object]],
    contrib_rows: list[dict[str, object]],
) -> tuple[float, float]:
    values = {
        ticker: abs(
            float(state["shares"])
            * float(exact_prices[ticker] if ticker in exact_prices.index else last_prices.get(ticker, state["entry_price"]))
        )
        for ticker, state in active.items()
    }
    gross = float(sum(values.values()))
    if gross <= equity or gross <= 0.0:
        return 0.0, 0.0
    tradable = [ticker for ticker in active if ticker in exact_prices.index]
    if not tradable:
        return 0.0, 0.0
    tradable_gross = float(sum(values[ticker] for ticker in tradable))
    locked_gross = gross - tradable_gross
    target_tradable = max(
        (equity - locked_gross - cost_rate * tradable_gross) / max(1.0 - cost_rate, 1e-12),
        0.0,
    )
    scale = min(target_tradable / tradable_gross, 1.0)
    turnover = 0.0
    for ticker in tradable:
        state = active[ticker]
        old_shares = float(state["shares"])
        new_shares = old_shares * scale
        price = float(exact_prices[ticker])
        reduction = abs(old_shares - new_shares) * price
        state["shares"] = new_shares
        turnover += reduction
        trade_rows.append({"scenario": scenario, "timestamp": timestamp, "date": timestamp.normalize(), "ticker": ticker, "event": "reduce", "reason": "hard_gross_cap", "notional": reduction, "cost": reduction * cost_rate, "direction": int(state["direction"])})
        add_contrib(contrib_rows, scenario, timestamp, ticker, "event", -reduction * cost_rate)
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
    last_prices = pd.Series(dtype=float)
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
        day_start_equity = equity
        pnl935 = 0.0
        turnover935 = 0.0

        for ticker, state in list(active.items()):
            if ticker in prices935.index:
                price = float(prices935[ticker])
                prior = float(last_prices.get(ticker, price))
                pnl = float(state["shares"]) * (price - prior)
                equity += pnl
                pnl935 += pnl
                last_prices.loc[ticker] = price
                add_contrib(contrib_rows, scenario, ts935, ticker, "event", pnl)
            else:
                missing_marks += 1

        for ticker, state in list(active.items()):
            if pd.Timestamp(state["exit_date"]) < date and ticker in prices935.index:
                notional = abs(float(state["shares"]) * float(prices935[ticker]))
                cost = notional * cost_rate
                equity -= cost
                turnover935 += notional
                add_contrib(contrib_rows, scenario, ts935, ticker, "event", -cost)
                trade_rows.append({"scenario": scenario, "timestamp": ts935, "date": date, "ticker": ticker, "event": "exit", "reason": "delayed_exact_0935", "notional": notional, "cost": cost, "direction": int(state["direction"])})
                del active[ticker]
                last_prices = last_prices.drop(ticker, errors="ignore")

        cap_turnover, cap_cost = enforce_gross_cap(active, last_prices, prices935, equity, cost_rate, scenario, ts935, trade_rows, contrib_rows)
        turnover935 += cap_turnover
        equity -= cap_cost

        new_signals = signal_by_date.get(date, signals.iloc[0:0])
        candidates = new_signals[~new_signals["ticker"].isin(active)].copy()
        marked_gross = sum(abs(float(state["shares"]) * float(last_prices.get(ticker, state["entry_price"]))) for ticker, state in active.items())
        available = max(equity - marked_gross, 0.0)
        requested_each = equity * 0.03
        candidates = candidates[(requested_each / candidates["adv20"]).le(0.01)].copy()
        scale = min(1.0, available / (requested_each * len(candidates))) if len(candidates) and requested_each > 0 else 0.0
        for row in candidates.sort_values(["cik", "ticker"]).itertuples(index=False):
            if row.ticker not in prices935.index or scale <= 0:
                continue
            price = float(prices935[row.ticker])
            notional = requested_each * scale
            cost = notional * cost_rate
            equity -= cost
            turnover935 += notional
            shares = int(row.direction) * notional / price
            exit_index = min(session_index[date] + hold_sessions - 1, len(sessions) - 1)
            active[str(row.ticker)] = {"shares": shares, "direction": int(row.direction), "entry_price": price, "entry_date": date, "exit_date": sessions[exit_index], "cik": str(row.cik)}
            last_prices.loc[str(row.ticker)] = price
            add_contrib(contrib_rows, scenario, ts935, str(row.ticker), "event", -cost)
            trade_rows.append({"scenario": scenario, "timestamp": ts935, "date": date, "ticker": row.ticker, "event": "entry", "reason": "confirmed_8k202", "notional": notional, "cost": cost, "direction": int(row.direction), "cik": row.cik, "accessionNumber": row.accessionNumber})

        cap_turnover, cap_cost = enforce_gross_cap(active, last_prices, prices935, equity, cost_rate, scenario, ts935, trade_rows, contrib_rows)
        turnover935 += cap_turnover
        equity -= cap_cost

        gross935 = sum(abs(float(state["shares"]) * float(last_prices.get(ticker, state["entry_price"]))) for ticker, state in active.items())
        gross_ratio935 = gross935 / max(equity, 1e-9)
        event_rows.append({"scenario": scenario, "timestamp": ts935, "equity": equity, "event_pnl": pnl935 - turnover935 * cost_rate, "gross": gross_ratio935, "turnover": turnover935, "trade_cost": turnover935 * cost_rate, "borrow_cost": 0.0, "financing_cost": 0.0, "active_positions": len(active), "missing_marks": missing_marks})

        pnl1555 = 0.0
        turnover1555 = 0.0
        for ticker, state in list(active.items()):
            if ticker in prices1555.index:
                price = float(prices1555[ticker])
                prior = float(last_prices.get(ticker, price))
                pnl = float(state["shares"]) * (price - prior)
                equity += pnl
                pnl1555 += pnl
                last_prices.loc[ticker] = price
                add_contrib(contrib_rows, scenario, ts1555, ticker, "event", pnl)
            else:
                missing_marks += 1

        values = pd.Series({ticker: float(state["shares"]) * float(last_prices.get(ticker, state["entry_price"])) for ticker, state in active.items()}, dtype=float)
        short_gross = float(values[values < 0].abs().sum())
        gross_dollars = float(values.abs().sum())
        borrow_cost = short_gross * 0.01 / 252.0
        financing_cost = max(gross_dollars - equity, 0.0) * 0.025 / 252.0
        equity -= borrow_cost + financing_cost
        add_contrib(contrib_rows, scenario, ts1555, "_BORROW", "borrow", -borrow_cost)
        add_contrib(contrib_rows, scenario, ts1555, "_FINANCING", "financing", -financing_cost)

        for ticker, state in list(active.items()):
            if pd.Timestamp(state["exit_date"]) <= date and ticker in prices1555.index:
                notional = abs(float(state["shares"]) * float(prices1555[ticker]))
                cost = notional * cost_rate
                equity -= cost
                turnover1555 += notional
                add_contrib(contrib_rows, scenario, ts1555, ticker, "event", -cost)
                trade_rows.append({"scenario": scenario, "timestamp": ts1555, "date": date, "ticker": ticker, "event": "exit", "reason": "scheduled_1555", "notional": notional, "cost": cost, "direction": int(state["direction"])})
                del active[ticker]
                last_prices = last_prices.drop(ticker, errors="ignore")

        cap_turnover, cap_cost = enforce_gross_cap(active, last_prices, prices1555, equity, cost_rate, scenario, ts1555, trade_rows, contrib_rows)
        turnover1555 += cap_turnover
        equity -= cap_cost

        gross1555 = sum(abs(float(state["shares"]) * float(last_prices.get(ticker, state["entry_price"]))) for ticker, state in active.items())
        gross_ratio1555 = gross1555 / max(equity, 1e-9)
        event_rows.append({"scenario": scenario, "timestamp": ts1555, "equity": equity, "event_pnl": pnl1555 - borrow_cost - financing_cost - turnover1555 * cost_rate, "gross": gross_ratio1555, "turnover": turnover1555, "trade_cost": turnover1555 * cost_rate, "borrow_cost": borrow_cost, "financing_cost": financing_cost, "active_positions": len(active), "missing_marks": missing_marks})
        daily_rows.append({"scenario": scenario, "date": date, "daily_pnl": equity - day_start_equity, "equity": equity, "max_gross": max(gross_ratio935, gross_ratio1555), "entries": int((pd.DataFrame(trade_rows[-len(candidates):])["event"].eq("entry").sum()) if len(candidates) and trade_rows else 0), "active_positions": len(active), "missing_marks": missing_marks})

    return pd.DataFrame(daily_rows), pd.DataFrame(event_rows), pd.DataFrame(trade_rows), pd.DataFrame(contrib_rows)


def drawdown(equity: pd.Series, start_equity: float) -> tuple[float, float]:
    curve = pd.concat([pd.Series([start_equity]), equity.reset_index(drop=True)], ignore_index=True)
    peak = curve.cummax()
    return float((curve - peak).min()), float((curve / peak - 1.0).min())


def effective_count(contrib: pd.Series) -> float:
    positive = contrib[contrib > 0]
    if positive.empty or positive.sum() <= 0:
        return 0.0
    weights = positive / positive.sum()
    return float(1.0 / weights.pow(2).sum())


def period_metrics(
    scenario: str,
    daily: pd.DataFrame,
    trades: pd.DataFrame,
    contrib: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, object]:
    x = daily[(daily["date"] >= start) & (daily["date"] <= end)].sort_values("date").copy()
    if x.empty:
        return {"scenario": scenario, "periodStart": start, "periodEnd": end, "days": 0}
    start_equity = float(x.iloc[0]["equity"] - x.iloc[0]["daily_pnl"])
    returns = x["daily_pnl"] / (x["equity"] - x["daily_pnl"]).replace(0.0, np.nan)
    years = max((x["date"].max() - x["date"].min()).days / 365.25, 1e-9)
    dd_dollar, dd_pct = drawdown(x["equity"], start_equity)
    trade_period = trades[(trades["date"] >= start) & (trades["date"] <= end)] if not trades.empty else trades
    contrib_period = contrib[(contrib["timestamp"].dt.normalize() >= start) & (contrib["timestamp"].dt.normalize() <= end)] if not contrib.empty else contrib
    ticker_pnl = contrib_period[~contrib_period["ticker"].str.startswith("_")].groupby("ticker")["pnl"].sum().sort_values(ascending=False) if not contrib_period.empty else pd.Series(dtype=float)
    positive_total = float(ticker_pnl[ticker_pnl > 0].sum())
    row: dict[str, object] = {
        "scenario": scenario,
        "periodStart": start,
        "periodEnd": end,
        "days": int(len(x)),
        "pnl": float(x["daily_pnl"].sum()),
        "return": float(x["equity"].iloc[-1] / start_equity - 1.0),
        "cagr": float((x["equity"].iloc[-1] / start_equity) ** (1.0 / years) - 1.0),
        "ddDollar": dd_dollar,
        "ddPct": dd_pct,
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else float("nan"),
        "entries": int(trade_period["event"].eq("entry").sum()) if not trade_period.empty else 0,
        "longEntries": int((trade_period["event"].eq("entry") & trade_period["direction"].eq(1)).sum()) if not trade_period.empty else 0,
        "shortEntries": int((trade_period["event"].eq("entry") & trade_period["direction"].eq(-1)).sum()) if not trade_period.empty else 0,
        "maxGross": float(x["max_gross"].max()),
        "effectiveTickerCount": effective_count(ticker_pnl),
        "tickers": int(len(ticker_pnl)),
    }
    for n in (1, 3, 5, 10):
        top = float(ticker_pnl.head(n).clip(lower=0.0).sum())
        row[f"top{n}PositivePnlShare"] = top / positive_total if positive_total > 0 else float("nan")
    return row


def yearly_rows(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (scenario, year), group in daily.assign(year=daily["date"].dt.year).groupby(["scenario", "year"], sort=True):
        start_equity = float(group.iloc[0]["equity"] - group.iloc[0]["daily_pnl"])
        dd_dollar, dd_pct = drawdown(group["equity"], start_equity)
        returns = group["daily_pnl"] / (group["equity"] - group["daily_pnl"]).replace(0.0, np.nan)
        rows.append({"scenario": scenario, "year": int(year), "pnl": float(group["daily_pnl"].sum()), "return": float(group["equity"].iloc[-1] / start_equity - 1.0), "ddDollar": dd_dollar, "ddPct": dd_pct, "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else float("nan")})
    return pd.DataFrame(rows)


def choose_variant(metrics: pd.DataFrame, yearly: pd.DataFrame) -> dict[str, object]:
    rows = []
    for hold in (1, 3, 5):
        variant = f"sec8k202_confirm_hold{hold}"
        base_scenario = f"{variant}_cost4"
        cost8_scenario = f"{variant}_cost8"
        dev = metrics[(metrics["scenario"].eq(base_scenario)) & (metrics["periodStart"].eq(pd.Timestamp("2018-01-02")))].iloc[0]
        val = metrics[(metrics["scenario"].eq(base_scenario)) & (metrics["periodStart"].eq(pd.Timestamp("2023-01-03")))].iloc[0]
        val8 = metrics[(metrics["scenario"].eq(cost8_scenario)) & (metrics["periodStart"].eq(pd.Timestamp("2023-01-03")))].iloc[0]
        positive_years = int((yearly[(yearly["scenario"].eq(base_scenario)) & yearly["year"].between(2018, 2022)]["pnl"] > 0).sum())
        val_years = yearly[(yearly["scenario"].eq(base_scenario)) & yearly["year"].between(2023, 2024)]
        dev_pass = positive_years >= 3 and dev["ddPct"] >= -0.20 and dev["entries"] >= 100 and dev["effectiveTickerCount"] >= 20
        val_pass = val["pnl"] >= 0 and val8["pnl"] >= 0 and val["ddPct"] >= -0.15 and len(val_years) == 2 and bool((val_years["pnl"] >= 0).all())
        rows.append({"variant": variant, "holdSessions": hold, "developmentPass": bool(dev_pass), "validationPass": bool(val_pass), "positiveDevelopmentYears": positive_years, "developmentSharpe": float(dev["sharpe"]), "developmentDdPct": float(dev["ddPct"]), "developmentEntries": int(dev["entries"]), "developmentEffectiveTickerCount": float(dev["effectiveTickerCount"]), "validationPnl": float(val["pnl"]), "validationCost8Pnl": float(val8["pnl"]), "validationDdPct": float(val["ddPct"])})
    eligible = [row for row in rows if row["developmentPass"] and row["validationPass"]]
    selected = sorted(eligible, key=lambda row: (-row["developmentSharpe"], row["holdSessions"]))[0]["variant"] if eligible else None
    return {"candidates": rows, "selectedVariant": selected, "familyStatus": "OOS_ELIGIBLE" if selected else "KILL_BEFORE_OOS"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the pre-registered SEC 8-K Item 2.02 event-drift family.")
    parser.add_argument("--stage", choices=["development", "oos"], required=True)
    args = parser.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_family_performance"):
        raise RuntimeError("Family preregistration is not frozen")
    if args.stage == "oos":
        if not OOS_FREEZE.exists():
            raise RuntimeError(f"Missing OOS freeze: {OOS_FREEZE}")
        freeze = json.loads(OOS_FREEZE.read_text(encoding="utf-8"))
        if not freeze.get("selected_variant"):
            raise RuntimeError("No selected variant is frozen for OOS")

    start, end, daily_path, intra_path, prefix = stage_contract(args.stage)
    daily_features, intra_features = load_features(daily_path, intra_path, start, end)
    mapped_events, signals = build_signals(args.stage, start, end, daily_features, intra_features)
    sessions = sorted(intra_features["date"].drop_duplicates())
    p935, p1555 = price_maps(intra_features)
    daily_frames = []
    event_frames = []
    trade_frames = []
    contrib_frames = []
    metrics_rows = []
    for hold in (1, 3, 5):
        variant = f"sec8k202_confirm_hold{hold}"
        for cost_bps in (4.0, 8.0):
            daily, events, trades, contrib = simulate(variant, hold, cost_bps, sessions, signals, p935, p1555)
            daily_frames.append(daily)
            event_frames.append(events)
            trade_frames.append(trades)
            contrib_frames.append(contrib)
            if args.stage == "development":
                metrics_rows.append(period_metrics(f"{variant}_cost{int(cost_bps)}", daily, trades, contrib, pd.Timestamp("2018-01-02"), pd.Timestamp("2022-12-30")))
                metrics_rows.append(period_metrics(f"{variant}_cost{int(cost_bps)}", daily, trades, contrib, pd.Timestamp("2023-01-03"), pd.Timestamp("2024-12-31")))
            else:
                metrics_rows.append(period_metrics(f"{variant}_cost{int(cost_bps)}", daily, trades, contrib, start, end))
            print("EVENT_REPLAY", metrics_rows[-1], flush=True)

    daily_all = pd.concat(daily_frames, ignore_index=True)
    events_all = pd.concat(event_frames, ignore_index=True)
    trades_all = pd.concat(trade_frames, ignore_index=True)
    contrib_all = pd.concat(contrib_frames, ignore_index=True)
    metrics = pd.DataFrame(metrics_rows)
    yearly = yearly_rows(daily_all)
    qa = []
    for scenario, group in events_all.groupby("scenario", sort=True):
        event_pnl = float(group["event_pnl"].sum())
        daily_pnl = float(daily_all[daily_all["scenario"].eq(scenario)]["daily_pnl"].sum())
        contrib_pnl = float(contrib_all[contrib_all["scenario"].eq(scenario)]["pnl"].sum())
        ending_pnl = float(group["equity"].iloc[-1] - START_CAPITAL)
        qa.append({"scenario": scenario, "eventPnl": event_pnl, "dailyPnl": daily_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusDaily": event_pnl - daily_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})

    mapped_events.to_csv(f"{prefix}_MAPPED_EVENTS.csv", index=False)
    signals.to_csv(f"{prefix}_SIGNALS.csv", index=False)
    metrics.to_csv(f"{prefix}_SUMMARY.csv", index=False)
    yearly.to_csv(f"{prefix}_YEARLY.csv", index=False)
    daily_all.to_csv(f"{prefix}_DAILY.csv", index=False)
    events_all.to_csv(f"{prefix}_EVENT_LEDGER.csv", index=False)
    trades_all.to_csv(f"{prefix}_TRADE_LEDGER.csv", index=False)
    contrib_all.to_csv(f"{prefix}_TICKER_CONTRIB.csv", index=False)
    pd.DataFrame(qa).to_csv(f"{prefix}_QA.csv", index=False)
    selection = None
    if args.stage == "development":
        selection = choose_variant(metrics, yearly)
        DEV_SELECTION.write_text(json.dumps(selection, indent=2), encoding="utf-8")
        print("SELECTION", json.dumps(selection), flush=True)
    manifest = {
        "script": "raits/research/stocks_sec_8k202_event_drift_replay.py",
        "stage": args.stage,
        "preregistration": str(PREREG),
        "sample": {"start": str(start.date()), "end": str(end.date())},
        "inputs": [str(SEC_EVENTS), str(daily_path), str(intra_path)] + [str(path) for path in CAP_PATHS + FILTER_PATHS],
        "mapped_events": len(mapped_events),
        "signals": len(signals),
        "selection": selection,
        "outputs_prefix": prefix,
    }
    Path(f"{prefix}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
