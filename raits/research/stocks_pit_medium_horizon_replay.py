from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_PIT_MEDIUM_HORIZON_PREREG_2026-10-03.json")
DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
ELIGIBLE = Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet")
PREFIX = "STOCKS_PIT_MEDIUM_HORIZON_2026-10-03"
START, DEV_END = pd.Timestamp("2018-03-29"), pd.Timestamp("2021-12-31")
VAL_START, VAL_END = pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-30")
INITIAL_EQUITY = 100_000.0
BASE_COST_BPS, STRESS_COST_BPS = 4.0, 8.0
SHORT_BORROW_ANNUAL = 0.01
VARIANTS = [
    "weekly_sector_momo20",
    "weekly_sector_momo60",
    "weekly_sector_reversal20",
    "weekly_consistent_lowvol_momo",
    "monthly_sector_blend_momo",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp]]:
    daily = pd.read_pickle(DAILY)[
        ["date", "ticker", "open_0935", "close_1555", "gap", "ret20_pre", "ret60_pre", "vol20_pre"]
    ].copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily = daily[daily["date"].between(START, VAL_END)].copy()
    sessions = sorted(daily["date"].drop_duplicates())
    prices = daily[["date", "ticker", "open_0935", "close_1555"]].drop_duplicates(["date", "ticker"])

    caps = pd.read_csv(CAPS, low_memory=False)
    caps["snapshot_date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["snapshot_date", "market_cap", "ticker"], ascending=[True, False, True])
    caps["rank"] = caps.groupby("snapshot_date")["market_cap"].rank(method="first", ascending=False)
    members = caps[caps["rank"].le(500)][
        ["snapshot_date", "ticker", "market_cap", "sic_description"]
    ].copy()
    members["sic_description"] = members["sic_description"].fillna("UNKNOWN").astype(str)
    assigned = pd.merge_asof(
        pd.DataFrame({"date": sessions}),
        members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date"),
        left_on="date",
        right_on="snapshot_date",
        direction="backward",
    )
    panel = daily.merge(assigned, on="date", how="inner", validate="many_to_one")
    panel = panel.merge(members, on=["snapshot_date", "ticker"], how="inner", validate="many_to_one")

    eligible = pd.read_parquet(
        ELIGIBLE,
        columns=["date", "ticker", "adv20"],
        filters=[("date", ">=", START.date()), ("date", "<=", VAL_END.date()), ("eligible_final", "==", True)],
    )
    eligible["date"] = pd.to_datetime(eligible["date"]).dt.normalize()
    eligible["ticker"] = eligible["ticker"].astype(str).str.upper()
    eligible = eligible.groupby(["date", "ticker"], as_index=False)["adv20"].min()
    panel = panel.merge(eligible, on=["date", "ticker"], how="inner", validate="one_to_one")
    panel = panel[
        panel["adv20"].ge(10_000_000.0)
        & panel["open_0935"].ge(5.0)
        & panel["gap"].abs().le(0.30)
        & panel["ret20_pre"].notna()
        & panel["ret60_pre"].notna()
        & panel["vol20_pre"].notna()
    ].copy()
    sector = panel.groupby(["date", "sic_description"])
    panel["sector_count"] = sector["ticker"].transform("count")
    panel["sector_ret20_median"] = sector["ret20_pre"].transform("median")
    panel["sector_ret60_median"] = sector["ret60_pre"].transform("median")
    panel["resid20"] = panel["ret20_pre"] - panel["sector_ret20_median"]
    panel["resid60"] = panel["ret60_pre"] - panel["sector_ret60_median"]
    panel["market_vol_median"] = panel.groupby("date")["vol20_pre"].transform("median")
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True), prices, sessions


def rebalance_maps(sessions: list[pd.Timestamp]) -> tuple[dict[pd.Timestamp, pd.Timestamp], dict[pd.Timestamp, pd.Timestamp]]:
    frame = pd.DataFrame({"date": sessions})
    frame["week"] = frame["date"].dt.to_period("W-SUN")
    frame["month"] = frame["date"].dt.to_period("M")
    weekly = frame.groupby("week", sort=True)["date"].min().tolist()
    monthly = frame.groupby("month", sort=True)["date"].min().tolist()
    return (
        {date: weekly[i + 1] for i, date in enumerate(weekly[:-1])},
        {date: monthly[i + 1] for i, date in enumerate(monthly[:-1])},
    )


def candidate_pool(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    x = panel[panel["sector_count"].ge(10)].copy()
    if variant == "weekly_sector_momo20":
        x = x[x["resid20"].abs().ge(0.03)].copy()
        x["event_score"] = x["resid20"].abs()
        x["signal_sign"] = np.sign(x["resid20"])
    elif variant == "weekly_sector_momo60":
        x = x[x["resid60"].abs().ge(0.05)].copy()
        x["event_score"] = x["resid60"].abs()
        x["signal_sign"] = np.sign(x["resid60"])
    elif variant == "weekly_sector_reversal20":
        x = x[x["resid20"].abs().ge(0.05)].copy()
        x["event_score"] = x["resid20"].abs()
        x["signal_sign"] = -np.sign(x["resid20"])
    elif variant == "weekly_consistent_lowvol_momo":
        x = x[
            (np.sign(x["resid20"]) == np.sign(x["resid60"]))
            & x["resid20"].abs().ge(0.02)
            & x["resid60"].abs().ge(0.03)
            & x["vol20_pre"].le(x["market_vol_median"])
        ].copy()
        x["event_score"] = x["resid20"].abs() + 0.5 * x["resid60"].abs()
        x["signal_sign"] = np.sign(x["resid20"])
    elif variant == "monthly_sector_blend_momo":
        x = x[
            (np.sign(x["resid20"]) == np.sign(x["resid60"]))
            & x["resid20"].abs().ge(0.02)
            & x["resid60"].abs().ge(0.05)
        ].copy()
        x["event_score"] = x["resid20"].abs() + 0.5 * x["resid60"].abs()
        x["signal_sign"] = np.sign(x["resid20"])
    else:
        raise ValueError(variant)
    return x


def ranked_indices(group: pd.DataFrame, direction: int) -> list[int]:
    side = group[group["signal_sign"].eq(direction)]
    selected: list[int] = []
    sic_counts: defaultdict[str, int] = defaultdict(int)
    for row in side.sort_values(["event_score", "adv20", "ticker"], ascending=[False, False, True]).itertuples():
        sic = str(row.sic_description)
        if sic_counts[sic] >= 1:
            continue
        selected.append(row.Index)
        sic_counts[sic] += 1
        if len(selected) == 5:
            break
    return selected


def build_trades(
    panel: pd.DataFrame,
    prices: pd.DataFrame,
    weekly_map: dict[pd.Timestamp, pd.Timestamp],
    monthly_map: dict[pd.Timestamp, pd.Timestamp],
    variant: str,
    scope_end: pd.Timestamp,
) -> pd.DataFrame:
    schedule = monthly_map if variant == "monthly_sector_blend_momo" else weekly_map
    pool = candidate_pool(panel, variant)
    pool = pool[pool["date"].isin(schedule)].copy()
    exit_prices = prices.rename(columns={"date": "planned_exit_date", "open_0935": "exit_price_0935"})[
        ["planned_exit_date", "ticker", "exit_price_0935"]
    ]
    rows: list[pd.DataFrame] = []
    for date, group in pool.groupby("date", sort=True):
        planned_exit = schedule.get(date)
        if planned_exit is None or planned_exit > scope_end:
            continue
        long_indices = ranked_indices(group, 1)
        short_indices = ranked_indices(group, -1)
        matched = min(len(long_indices), len(short_indices))
        indices = long_indices[:matched] + short_indices[:matched]
        if not indices:
            continue
        day = group.loc[indices].copy()
        day["direction"] = [1] * matched + [-1] * matched
        day["target_weight"] = 0.05
        day["planned_exit_date"] = planned_exit
        day = day.merge(exit_prices, on=["planned_exit_date", "ticker"], how="left", validate="one_to_one")
        day["unreplayable_exit"] = day["exit_price_0935"].isna() | day["exit_price_0935"].le(0)
        day["raw_return"] = day["direction"] * (day["exit_price_0935"] / day["open_0935"] - 1.0)
        day.loc[day["unreplayable_exit"], "raw_return"] = -1.0
        day["variant"] = variant
        rows.append(day)
    return pd.concat(rows, ignore_index=True) if rows else pool.iloc[0:0].copy()


def simulate(
    variant: str,
    trades: pd.DataFrame,
    prices: pd.DataFrame,
    sessions: list[pd.Timestamp],
    cost_bps: float,
    scope: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    entry_groups = {date: group for date, group in trades.groupby("date", sort=True)}
    close_lookup = prices.set_index(["date", "ticker"])["close_1555"]
    cash = INITIAL_EQUITY
    previous_equity = peak = INITIAL_EQUITY
    positions: list[dict[str, object]] = []
    daily_rows: list[dict[str, object]] = []
    contrib_rows: list[dict[str, object]] = []
    max_adv_seen = 0.0
    for date in sessions:
        if date < trades["date"].min() if not trades.empty else False:
            continue
        day_cost = day_borrow = 0.0
        gross_realized = 0.0
        survivors: list[dict[str, object]] = []
        for position in positions:
            if position["exit_date"] != date:
                survivors.append(position)
                continue
            if position["unreplayable"]:
                cash += position["shares"] * position["entry_price"]
                gross_leg = -position["entry_notional"]
                cash += gross_leg
                exit_notional = 0.0
            else:
                exit_price = position["exit_price"]
                cash += position["shares"] * exit_price
                gross_leg = position["direction"] * position["entry_notional"] * (
                    exit_price / position["entry_price"] - 1.0
                )
                exit_notional = abs(position["shares"]) * exit_price
            exit_cost = exit_notional * cost_bps / 10_000.0
            hold_days = max((date - position["entry_date"]).days, 1)
            borrow = (
                position["entry_notional"] * SHORT_BORROW_ANNUAL * hold_days / 365.0
                if position["direction"] < 0 else 0.0
            )
            cash -= exit_cost + borrow
            day_cost += exit_cost
            day_borrow += borrow
            gross_realized += gross_leg
            net_leg = gross_leg - position["entry_cost"] - exit_cost - borrow
            contrib_rows.append({
                "variant": variant, "scope": scope, "cost_bps": cost_bps,
                "date": date, "entry_date": position["entry_date"], "ticker": position["ticker"],
                "direction": position["direction"], "gross_pnl": gross_leg,
                "trading_cost": position["entry_cost"] + exit_cost, "borrow_cost": borrow,
                "net_pnl": net_leg, "entry_equity": position["entry_equity"],
            })
        positions = survivors

        day = entry_groups.get(date)
        entry_legs = 0
        if day is not None and not day.empty:
            if positions:
                raise RuntimeError(f"Overlapping cohort before entry: {variant} {date.date()}")
            entry_equity = cash
            for trade in day.itertuples(index=False):
                notional = entry_equity * float(trade.target_weight)
                adv_fraction = notional / float(trade.adv20)
                max_adv_seen = max(max_adv_seen, adv_fraction)
                if adv_fraction > 0.01 + 1e-12:
                    raise RuntimeError("ADV cap breach")
                direction = int(trade.direction)
                shares = direction * notional / float(trade.open_0935)
                entry_cost = notional * cost_bps / 10_000.0
                cash -= shares * float(trade.open_0935) + entry_cost
                day_cost += entry_cost
                positions.append({
                    "ticker": trade.ticker, "direction": direction, "shares": shares,
                    "entry_price": float(trade.open_0935), "entry_notional": notional,
                    "entry_cost": entry_cost, "entry_date": date,
                    "exit_date": pd.Timestamp(trade.planned_exit_date),
                    "exit_price": float(trade.exit_price_0935) if not trade.unreplayable_exit else np.nan,
                    "unreplayable": bool(trade.unreplayable_exit), "entry_equity": entry_equity,
                    "last_mark": float(trade.open_0935),
                })
            entry_legs = len(day)

        marked_value = 0.0
        for position in positions:
            key = (date, position["ticker"])
            mark = close_lookup.get(key, np.nan)
            if pd.notna(mark) and float(mark) > 0:
                position["last_mark"] = float(mark)
            marked_value += position["shares"] * position["last_mark"]
        equity = cash + marked_value
        daily_pnl = equity - previous_equity
        gross_mtm = daily_pnl + day_cost + day_borrow
        peak = max(peak, equity)
        gross_exposure = sum(abs(position["shares"] * position["last_mark"]) for position in positions)
        daily_rows.append({
            "variant": variant, "scope": scope, "cost_bps": cost_bps, "date": date,
            "starting_equity": previous_equity, "equity": equity, "daily_pnl": daily_pnl,
            "gross_pnl": gross_mtm, "trading_cost": day_cost, "borrow_cost": day_borrow,
            "gross": gross_exposure / equity if equity > 0 else np.nan, "trade_legs": entry_legs,
            "max_order_adv_fraction": max_adv_seen, "unreplayable_exit_legs": 0 if day is None else int(day["unreplayable_exit"].sum()),
            "dd_dollar": equity - peak, "dd_pct": equity / peak - 1.0,
        })
        previous_equity = equity
    if positions:
        raise RuntimeError(f"Open positions after scope end: {variant}")
    return pd.DataFrame(daily_rows), pd.DataFrame(contrib_rows)


def metrics(daily: pd.DataFrame, contrib: pd.DataFrame) -> dict[str, float]:
    returns = daily["daily_pnl"] / daily["starting_equity"]
    years = max((daily["date"].max() - daily["date"].min()).days / 365.25, 1e-9)
    yearly = (1.0 + returns).groupby(daily["date"].dt.year).prod() - 1.0
    active = daily["trade_legs"].gt(0)
    cohort_gross = contrib.groupby("entry_date").agg(gross=("gross_pnl", "sum"), equity=("entry_equity", "first"))
    return {
        "pnl": float(daily["daily_pnl"].sum()), "grossPnl": float(contrib["gross_pnl"].sum()),
        "cagr": float((daily.iloc[-1]["equity"] / INITIAL_EQUITY) ** (1.0 / years) - 1.0),
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else np.nan,
        "ddDollar": float(daily["dd_dollar"].min()), "ddPct": float(daily["dd_pct"].min()),
        "positiveYears": int(yearly.gt(0).sum()), "activeDays": int(active.sum()),
        "tradeLegs": int(daily["trade_legs"].sum()), "tradingCost": float(daily["trading_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()),
        "maxOrderAdvFraction": float(daily["max_order_adv_fraction"].max()),
        "unreplayableExitLegs": int(daily["unreplayable_exit_legs"].sum()),
        "grossEdgeBpsPerActiveCohort": float((cohort_gross["gross"] / cohort_gross["equity"]).mean() * 10_000.0),
    }


def concentration(contrib: pd.DataFrame) -> dict[str, float | str]:
    by = contrib.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
    positive = by[by.gt(0)]
    total = float(positive.sum())
    row: dict[str, float | str] = {
        "tickers": len(by), "topTicker": by.index[0] if len(by) else "",
        "effectiveTickerCount": float(total**2 / positive.pow(2).sum()) if total > 0 else 0.0,
    }
    for n in (1, 3, 5, 10):
        row[f"top{n}PositiveShare"] = float(positive.head(n).sum() / total) if total > 0 else np.nan
    return row


def run_scope(panel: pd.DataFrame, prices: pd.DataFrame, sessions: list[pd.Timestamp],
              weekly_map: dict[pd.Timestamp, pd.Timestamp], monthly_map: dict[pd.Timestamp, pd.Timestamp],
              start: pd.Timestamp, end: pd.Timestamp, scope: str, variants: list[str]) -> dict[str, pd.DataFrame]:
    p = panel[panel["date"].between(start, end)].copy()
    s = [date for date in sessions if start <= date <= end]
    trades_all, daily_all, contrib_all, summaries = [], [], [], []
    for variant in variants:
        trades = build_trades(p, prices, weekly_map, monthly_map, variant, end)
        trades["scope"] = scope
        trades_all.append(trades)
        base_daily = base_contrib = None
        stress_pnl = np.nan
        for cost in (BASE_COST_BPS, STRESS_COST_BPS):
            daily, contrib = simulate(variant, trades, prices, s, cost, scope)
            daily_all.append(daily); contrib_all.append(contrib)
            if cost == BASE_COST_BPS:
                base_daily, base_contrib = daily, contrib
            else:
                stress_pnl = metrics(daily, contrib)["pnl"]
        summaries.append({"variant": variant, "stressPnl": stress_pnl,
                          **metrics(base_daily, base_contrib), **concentration(base_contrib)})
    return {"summary": pd.DataFrame(summaries), "trades": pd.concat(trades_all, ignore_index=True),
            "daily": pd.concat(daily_all, ignore_index=True), "contrib": pd.concat(contrib_all, ignore_index=True)}


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or len(prereg["variants"]) != 5:
        raise RuntimeError("Invalid preregistration")
    panel, prices, sessions = load_data()
    weekly_map, monthly_map = rebalance_maps(sessions)
    dev = run_scope(panel, prices, sessions, weekly_map, monthly_map, START, DEV_END, "development", VARIANTS)
    development = dev["summary"].copy()
    monthly = development["variant"].eq("monthly_sector_blend_momo")
    breadth = ((~monthly & development["activeDays"].ge(100) & development["tradeLegs"].ge(600))
               | (monthly & development["activeDays"].ge(36) & development["tradeLegs"].ge(300)))
    edge_gate = np.where(monthly, 25.0, 10.0)
    development["developmentPass"] = (
        breadth & development["cagr"].ge(0.05) & development["sharpe"].ge(0.8)
        & development["ddPct"].ge(-0.12) & development["positiveYears"].ge(3)
        & development["grossEdgeBpsPerActiveCohort"].ge(edge_gate)
        & development["stressPnl"].gt(0) & development["top10PositiveShare"].le(0.50)
    )
    development = development.sort_values(["developmentPass", "sharpe", "cagr", "variant"], ascending=[False, False, False, True])
    passing = development[development["developmentPass"]]
    validation = pd.DataFrame(); outputs = dev
    if passing.empty:
        selection = {"status": "KILL_NO_DEVELOPMENT_PASS", "selectedVariant": None,
                     "validationOpened": False, "productionPassAllowed": False}
    else:
        selected = str(passing.iloc[0]["variant"])
        val = run_scope(panel, prices, sessions, weekly_map, monthly_map, VAL_START, VAL_END, "validation", [selected])
        validation = val["summary"].copy()
        min_active = 9 if selected.startswith("monthly") else 25
        validation["validationPass"] = (
            validation["activeDays"].ge(min_active) & validation["pnl"].gt(0)
            & validation["sharpe"].ge(0.5) & validation["ddPct"].ge(-0.10)
            & validation["stressPnl"].gt(0) & validation["top10PositiveShare"].le(0.60)
        )
        passed = bool(validation.iloc[0]["validationPass"])
        selection = {"status": "CONTINUE_AUDIT" if passed else "KILL_VALIDATION_FAIL",
                     "selectedVariant": selected, "validationOpened": True,
                     "validationPass": passed, "productionPassAllowed": False}
        outputs = {key: pd.concat([dev[key], val[key]], ignore_index=True) if key != "summary" else dev[key]
                   for key in ("summary", "trades", "daily", "contrib")}

    daily, contrib = outputs["daily"], outputs["contrib"]
    yearly = daily.assign(year=daily["date"].dt.year).groupby(["variant", "scope", "cost_bps", "year"], as_index=False).agg(
        pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"), tradingCost=("trading_cost", "sum"),
        borrowCost=("borrow_cost", "sum"), activeDays=("trade_legs", lambda values: int(values.gt(0).sum())),
        tradeLegs=("trade_legs", "sum"), minDdDollar=("dd_dollar", "min"), minDdPct=("dd_pct", "min"))
    qa = []
    for (variant, scope, cost), group in daily.groupby(["variant", "scope", "cost_bps"]):
        match = contrib[(contrib["variant"].eq(variant)) & (contrib["scope"].eq(scope)) & (contrib["cost_bps"].eq(cost))]
        ending = float(group.sort_values("date").iloc[-1]["equity"] - INITIAL_EQUITY)
        qa.append({"variant": variant, "scope": scope, "cost_bps": cost,
                   "dailyPnl": group["daily_pnl"].sum(), "endingDelta": ending,
                   "contribPnl": match["net_pnl"].sum(), "dailyMinusEnding": group["daily_pnl"].sum() - ending,
                   "dailyMinusContrib": group["daily_pnl"].sum() - match["net_pnl"].sum()})
    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False); validation.to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    outputs["trades"].to_csv(f"{PREFIX}_TRADES.csv", index=False); daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False); yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    pd.DataFrame(qa).to_csv(f"{PREFIX}_QA.csv", index=False)
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
                "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
                "inputs": {str(path).replace("\\", "/"): sha256(path) for path in (DAILY, CAPS, ELIGIBLE)},
                "selection": selection, "development": [str(START.date()), str(DEV_END.date())],
                "validation": [str(VAL_START.date()), str(VAL_END.date())] if selection["validationOpened"] else None,
                "oldManual62Used": False, "post2022Consumed": False, "productionPassAllowed": False,
                "causality": "T-1 daily signals; exact 09:35 non-overlapping weekly/monthly cohorts; daily MTM"}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False)); print(validation.to_string(index=False)); print(json.dumps(selection, indent=2)); print(pd.DataFrame(qa).to_string(index=False))


if __name__ == "__main__":
    main()
