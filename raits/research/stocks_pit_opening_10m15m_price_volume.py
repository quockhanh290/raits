from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_PIT_OPENING_10M15M_PRICE_VOLUME_PREREG_2026-10-01.json")
DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRA = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
ELIGIBLE = Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet")
RAW = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
RAW_MANIFEST = RAW / "manifest.json"
PREFIX = "STOCKS_PIT_OPENING_10M15M_PRICE_VOLUME_2026-10-01"
START, DEV_END = pd.Timestamp("2018-04-27"), pd.Timestamp("2022-12-30")
VAL_START, END = pd.Timestamp("2023-01-03"), pd.Timestamp("2024-12-31")
INITIAL_EQUITY = 100_000.0
BASE_COST_BPS_PER_SIDE = 4.0
STRESS_COST_BPS_PER_SIDE = 8.0
BORROW_ANNUAL = 0.01
ENTRY_CLOCK = "09:40"
EXIT_CLOCKS = {"10m": "09:50", "15m": "09:55"}
EXIT_FALLBACKS = {
    horizon: pd.date_range(f"2000-01-01 {clock}", "2000-01-01 16:00", freq="5min").strftime("%H:%M").tolist()
    for horizon, clock in EXIT_CLOCKS.items()
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def safe_symbol(symbol: str) -> str:
    return symbol.replace("/", "_")


def rolling_beta(frame: pd.DataFrame) -> pd.Series:
    out = pd.Series(np.nan, index=frame.index, dtype=float)
    for _, group in frame.groupby("ticker", sort=False):
        group = group.sort_values("date")
        stock = group["prev_dayret"].astype(float)
        market = group["spy_prev_dayret"].astype(float)
        covariance = stock.rolling(60, min_periods=40).cov(market)
        variance = market.rolling(60, min_periods=40).var()
        out.loc[group.index] = (covariance / variance.replace(0.0, np.nan)).clip(-1.0, 4.0)
    return out


def load_signal_panel(finish: pd.Timestamp) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    daily = pd.read_pickle(DAILY)[["date", "ticker", "gap", "prev_dayret", "spy_prev_dayret", "vol20_pre"]].copy()
    intra = pd.read_pickle(INTRA)[["date", "ticker", "first5_ret", "rvol930"]].copy()
    for frame in (daily, intra):
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
        frame.drop(frame[(frame["date"] < START - pd.Timedelta(days=120)) | (frame["date"] > finish)].index, inplace=True)
    sessions = sorted(intra.loc[intra["date"].between(START, finish), "date"].drop_duplicates())

    caps = pd.read_csv(CAPS, low_memory=False)
    caps["snapshot_date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["snapshot_date", "market_cap", "ticker"], ascending=[True, False, True])
    caps["rank"] = caps.groupby("snapshot_date")["market_cap"].rank(method="first", ascending=False)
    members = caps[caps["rank"].le(500)][["snapshot_date", "ticker", "market_cap", "sic_description"]].copy()
    members["sic_description"] = members["sic_description"].fillna("UNKNOWN").astype(str)
    assigned = pd.merge_asof(pd.DataFrame({"date": sessions}), members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date"), left_on="date", right_on="snapshot_date", direction="backward")

    tickers = set(members["ticker"])
    daily = daily[daily["ticker"].isin(tickers)].sort_values(["ticker", "date"])
    daily["beta60_lag"] = rolling_beta(daily)
    panel = daily.merge(intra, on=["date", "ticker"], how="inner", validate="one_to_one")
    panel = panel.merge(assigned, on="date", how="inner", validate="many_to_one")
    panel = panel.merge(members, on=["snapshot_date", "ticker"], how="inner", validate="many_to_one")

    eligible = pd.read_parquet(ELIGIBLE, columns=["date", "ticker", "adv20"], filters=[("date", ">=", START.date()), ("date", "<=", finish.date()), ("eligible_final", "==", True)])
    eligible["date"] = pd.to_datetime(eligible["date"]).dt.normalize()
    eligible["ticker"] = eligible["ticker"].astype(str).str.upper()
    eligible = eligible.groupby(["date", "ticker"], as_index=False)["adv20"].min()
    panel = panel.merge(eligible, on=["date", "ticker"], how="inner", validate="one_to_one")

    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel = panel[panel["date"].between(START, finish) & panel["adv20"].ge(10_000_000)].copy()
    panel = panel.dropna(subset=["gap", "first5_ret", "rvol930", "beta60_lag", "sic_description"])
    panel["pit_top500_median_first5"] = panel.groupby("date")["first5_ret"].transform("median")
    panel["market_residual_first5"] = panel["first5_ret"] - panel["beta60_lag"] * panel["pit_top500_median_first5"]
    panel["sic_median_residual"] = panel.groupby(["date", "sic_description"])["market_residual_first5"].transform("median")
    panel["opening_residual"] = panel["market_residual_first5"] - panel["sic_median_residual"]
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True), sessions


def preliminary_candidates(panel: pd.DataFrame, families: set[str]) -> pd.DataFrame:
    mask = pd.Series(False, index=panel.index)
    if families.intersection({"residual_reversal", "residual_continuation"}):
        mask |= panel["opening_residual"].abs().ge(0.005)
    if families.intersection({"gap_rejection", "gap_confirmation"}):
        mask |= panel["gap"].abs().ge(0.015) & panel["first5_ret"].abs().ge(0.003)
    return panel[panel["rvol930"].ge(1.5) & mask].copy()


def raw_file_path(ticker: str, month: str) -> Path:
    safe = safe_symbol(ticker)
    return RAW / safe / f"{safe}_5m_{month}.parquet"


def extract_raw_clocks(preliminary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = preliminary[["ticker", "date"]].drop_duplicates().copy()
    keys["month"] = keys["date"].dt.strftime("%Y-%m")
    requested = {(row.ticker, row.date) for row in keys.itertuples(index=False)}
    rows: list[pd.DataFrame] = []
    inventory: list[dict[str, object]] = []
    clocks = {"09:30", ENTRY_CLOCK, *(clock for clocks in EXIT_FALLBACKS.values() for clock in clocks)}
    file_keys = list(keys[["ticker", "month"]].drop_duplicates().itertuples(index=False, name=None))

    def read_one(item: tuple[str, str]) -> tuple[pd.DataFrame | None, dict[str, object]]:
        ticker, month = item
        path = raw_file_path(str(ticker), str(month))
        record = {"ticker": ticker, "month": month, "path": str(path).replace("\\", "/"), "exists": path.exists(), "size": path.stat().st_size if path.exists() else 0}
        if not path.exists() or path.stat().st_size <= 0:
            return None, {**record, "selected_rows": 0}
        raw = pd.read_parquet(path, columns=["open", "high", "low", "close", "volume", "transactions"]).reset_index()
        raw["date"] = raw["timestamp"].dt.normalize()
        raw["clock"] = raw["timestamp"].dt.strftime("%H:%M")
        raw = raw[raw["clock"].isin(clocks) & raw["date"].map(lambda date: (ticker, date) in requested)].copy()
        raw["ticker"] = ticker
        selected = raw[["date", "clock", "ticker", "open", "high", "low", "close", "volume", "transactions"]] if not raw.empty else None
        return selected, {**record, "selected_rows": len(raw)}

    with ThreadPoolExecutor(max_workers=16) as executor:
        for selected, record in executor.map(read_one, file_keys):
            if selected is not None:
                rows.append(selected)
            inventory.append(record)
    exact = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "clock", "ticker", "open", "high", "low", "close", "volume", "transactions"])
    exact["date"] = pd.to_datetime(exact["date"]).dt.normalize()
    exact = exact.drop_duplicates(["date", "clock", "ticker"], keep="last").sort_values(["date", "ticker", "clock"])
    return exact, pd.DataFrame(inventory)


def attach_exact_prices(preliminary: pd.DataFrame, exact: pd.DataFrame) -> pd.DataFrame:
    wide = exact.pivot(index=["date", "ticker"], columns="clock", values=["open", "high", "low", "close", "volume", "transactions"])
    wide.columns = [f"{field}_{clock.replace(':', '')}" for field, clock in wide.columns]
    wide = wide.reset_index()
    x = preliminary.merge(wide, on=["date", "ticker"], how="left", validate="one_to_one")
    needed = ["open_0930", "high_0930", "low_0930", "close_0930", "volume_0930", "transactions_0930", "open_0940"]
    x["signal_entry_complete"] = x[needed].notna().all(axis=1)
    x["range_pct"] = (x["high_0930"] - x["low_0930"]) / x["open_0930"]
    spread = (x["high_0930"] - x["low_0930"]).replace(0.0, np.nan)
    x["close_location"] = (x["close_0930"] - x["low_0930"]) / spread
    x["directional_close_location"] = np.sign(x["first5_ret"]) * (2.0 * x["close_location"] - 1.0)
    x["feature_price_error_bps"] = (x["close_0930"] / (x["open_0930"] * (1.0 + x["first5_ret"])) - 1.0).abs() * 10_000.0
    return x


def candidates_for_family(exact_panel: pd.DataFrame, family: str) -> pd.DataFrame:
    base = exact_panel[exact_panel["signal_entry_complete"] & exact_panel["rvol930"].ge(1.5) & exact_panel["range_pct"].ge(0.004) & exact_panel["directional_close_location"].ge(0.25)].copy()
    if family.startswith("residual_"):
        out = base[base["opening_residual"].abs().ge(0.005)].copy()
        raw_side = np.sign(out["opening_residual"])
        out["side"] = -raw_side if family == "residual_reversal" else raw_side
        out["signal_value"] = out["opening_residual"]
    elif family == "gap_rejection":
        out = base[base["gap"].abs().ge(0.015) & base["first5_ret"].abs().ge(0.003) & base["gap"].mul(base["first5_ret"]).lt(0)].copy()
        out["side"] = np.sign(out["first5_ret"])
        out["signal_value"] = out["first5_ret"]
    elif family == "gap_confirmation":
        out = base[base["gap"].abs().ge(0.015) & base["first5_ret"].abs().ge(0.003) & base["gap"].mul(base["first5_ret"]).gt(0)].copy()
        out["side"] = np.sign(out["first5_ret"])
        out["signal_value"] = out["first5_ret"]
    else:
        raise ValueError(family)
    out["event_score"] = out["signal_value"].abs() * np.sqrt(out["rvol930"].clip(upper=10.0)) * np.sqrt((out["range_pct"] / 0.004).clip(upper=5.0))
    return out[out["side"].ne(0)].copy()


def select_side(group: pd.DataFrame, side: int) -> pd.DataFrame:
    selected = []
    sic_counts: defaultdict[str, int] = defaultdict(int)
    for row in group[group["side"].eq(side)].sort_values(["event_score", "adv20", "ticker"], ascending=[False, False, True]).itertuples():
        sic = str(row.sic_description)
        if sic_counts[sic] >= 2:
            continue
        selected.append(row.Index)
        sic_counts[sic] += 1
        if len(selected) == 5:
            break
    return group.loc[selected].copy() if selected else group.iloc[0:0].copy()


def build_trades(exact_panel: pd.DataFrame, family: str, horizon: str) -> pd.DataFrame:
    candidates = candidates_for_family(exact_panel, family)
    rows = []
    exit_columns = [f"open_{clock.replace(':', '')}" for clock in EXIT_FALLBACKS[horizon]]
    for date, group in candidates.groupby("date", sort=True):
        longs, shorts = select_side(group, 1), select_side(group, -1)
        if len(longs) != 5 or len(shorts) != 5:
            continue
        longs["target_weight"] = 0.5 / len(longs)
        shorts["target_weight"] = -0.5 / len(shorts)
        selected = pd.concat([longs, shorts], ignore_index=True)
        selected["entry_price"] = selected["open_0940"]
        available = selected[exit_columns].notna()
        if not available.any(axis=1).all():
            missing = selected.loc[~available.any(axis=1), "ticker"].tolist()
            raise RuntimeError(f"No causal same-session fallback exit by 16:00 on {date.date()}: {missing}")
        selected["exit_price"] = selected[exit_columns].bfill(axis=1).iloc[:, 0]
        selected["exit_clock"] = available.idxmax(axis=1).str.removeprefix("open_").str.replace(r"^(\d{2})(\d{2})$", r"\1:\2", regex=True)
        selected["exit_delay_minutes"] = [
            (pd.Timestamp(f"2000-01-01 {clock}") - pd.Timestamp(f"2000-01-01 {EXIT_CLOCKS[horizon]}")).seconds / 60
            for clock in selected["exit_clock"]
        ]
        selected["hold_minutes"] = [
            (pd.Timestamp(f"2000-01-01 {clock}") - pd.Timestamp(f"2000-01-01 {ENTRY_CLOCK}")).seconds / 60
            for clock in selected["exit_clock"]
        ]
        selected["raw_return"] = selected["exit_price"] / selected["entry_price"] - 1.0
        selected["signed_return"] = selected["target_weight"] * selected["raw_return"]
        selected["family"] = family
        selected["horizon"] = horizon
        selected["variant"] = family + "_" + horizon
        rows.append(selected)
    return pd.concat(rows, ignore_index=True) if rows else candidates.iloc[0:0].copy()


def simulate(variant: str, trades: pd.DataFrame, sessions: list[pd.Timestamp], cost_bps: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_date = {date: group for date, group in trades.groupby("date", sort=True)} if not trades.empty else {}
    equity = INITIAL_EQUITY
    peak = INITIAL_EQUITY
    daily_rows, contrib_rows = [], []
    for date in sessions:
        day = by_date.get(date)
        gross_pnl = cost = borrow = gross = max_order_adv_fraction = 0.0
        if day is not None and not day.empty:
            start_equity = equity
            gross = float(day["target_weight"].abs().sum())
            participation = start_equity * day["target_weight"].abs() / day["adv20"]
            max_order_adv_fraction = float(participation.max())
            if max_order_adv_fraction > 0.01 + 1e-12:
                raise RuntimeError(f"ADV participation breach: {variant} {date.date()} {max_order_adv_fraction:.6f}")
            gross_pnl = float(start_equity * day["signed_return"].sum())
            cost = start_equity * gross * 2.0 * cost_bps / 10_000.0
            short_gross = float(day.loc[day["target_weight"].lt(0), "target_weight"].abs().sum())
            borrow_by_trade = np.where(day["target_weight"].lt(0), start_equity * day["target_weight"].abs() * BORROW_ANNUAL * day["hold_minutes"] / (252.0 * 390.0), 0.0)
            borrow = float(np.sum(borrow_by_trade))
            allocation_cost = day["target_weight"].abs() / gross * cost + borrow_by_trade if gross > 0 else borrow_by_trade
            for (_, row), allocated in zip(day.iterrows(), allocation_cost):
                contrib_rows.append({"variant": variant, "cost_bps": cost_bps, "date": date, "ticker": row["ticker"],
                    "gross_pnl": start_equity * row["signed_return"], "cost_and_borrow": allocated,
                    "net_pnl": start_equity * row["signed_return"] - allocated})
            equity += gross_pnl - cost - borrow
        daily_pnl = gross_pnl - cost - borrow
        peak = max(peak, equity)
        daily_rows.append({"variant": variant, "cost_bps": cost_bps, "date": date, "equity": equity, "daily_pnl": daily_pnl,
            "gross_pnl": gross_pnl, "trading_cost": cost, "borrow_cost": borrow, "gross": gross,
            "trade_legs": 0 if day is None else len(day), "max_order_adv_fraction": max_order_adv_fraction,
            "fallback_exit_legs": 0 if day is None else int(day["exit_delay_minutes"].gt(0).sum()),
            "max_exit_delay_minutes": 0.0 if day is None else float(day["exit_delay_minutes"].max()),
            "dd_dollar": equity - peak, "dd_pct": equity / peak - 1.0})
    return pd.DataFrame(daily_rows), pd.DataFrame(contrib_rows)


def metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = daily["daily_pnl"] / (daily["equity"] - daily["daily_pnl"])
    years = max((daily["date"].max() - daily["date"].min()).days / 365.25, 1e-9)
    yearly = (1.0 + returns).groupby(daily["date"].dt.year).prod() - 1.0
    active = daily["trade_legs"].gt(0)
    return {"pnl": float(daily["daily_pnl"].sum()), "grossPnl": float(daily["gross_pnl"].sum()),
        "cagr": float((daily.iloc[-1]["equity"] / INITIAL_EQUITY) ** (1.0 / years) - 1.0),
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else np.nan,
        "ddDollar": float(daily["dd_dollar"].min()), "ddPct": float(daily["dd_pct"].min()),
        "positiveYears": int(yearly.gt(0).sum()), "activeDays": int(active.sum()), "tradeLegs": int(daily["trade_legs"].sum()),
        "fallbackExitLegs": int(daily["fallback_exit_legs"].sum()), "maxExitDelayMinutes": float(daily["max_exit_delay_minutes"].max()),
        "avgGrossActive": float(daily.loc[active, "gross"].mean()) if active.any() else 0.0,
        "tradingCost": float(daily["trading_cost"].sum()), "borrowCost": float(daily["borrow_cost"].sum())}


def concentration(contrib: pd.DataFrame) -> dict[str, object]:
    by = contrib.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False) if not contrib.empty else pd.Series(dtype=float)
    positive = by[by > 0]; positive_total = float(positive.sum()); net = float(by.sum())
    row: dict[str, object] = {"tickers": len(by), "topTicker": by.index[0] if len(by) else "",
        "effectiveTickerCount": float(positive_total**2 / positive.pow(2).sum()) if positive_total > 0 else 0.0}
    for count in (1, 3, 5, 10):
        top = float(positive.head(count).sum())
        row[f"top{count}PositiveShare"] = top / positive_total if positive_total > 0 else np.nan
        row[f"top{count}NetShare"] = top / net if net > 0 else np.nan
    return row


def run_scope(
    finish: pd.Timestamp,
    scope: str,
    variants: list[str] | None = None,
    session_start: pd.Timestamp = START,
) -> dict[str, object]:
    panel, sessions = load_signal_panel(finish)
    variants = variants or [f"{family}_{horizon}" for family in ("residual_reversal", "residual_continuation", "gap_rejection", "gap_confirmation") for horizon in EXIT_CLOCKS]
    families = {variant.rsplit("_", 1)[0] for variant in variants}
    panel = panel[panel["date"].between(session_start, finish)].copy()
    sessions = [date for date in sessions if session_start <= date <= finish]
    preliminary = preliminary_candidates(panel, families)
    exact, inventory = extract_raw_clocks(preliminary)
    exact_panel = attach_exact_prices(preliminary, exact)
    trade_frames, daily_frames, contrib_frames, rows = [], [], [], []
    for variant in variants:
        family, horizon = variant.rsplit("_", 1)
        trades = build_trades(exact_panel, family, horizon)
        trades["run_scope"] = scope
        trade_frames.append(trades)
        for cost_bps in (BASE_COST_BPS_PER_SIDE, STRESS_COST_BPS_PER_SIDE):
            daily, contrib = simulate(variant, trades, sessions, cost_bps)
            daily["run_scope"] = scope
            contrib["run_scope"] = scope
            daily_frames.append(daily)
            contrib_frames.append(contrib)
            result = metrics(daily)
            if cost_bps == BASE_COST_BPS_PER_SIDE:
                gross_edge_bps = (trades["target_weight"] * trades["raw_return"]).groupby(trades["date"]).sum().mean() * 10_000.0 if not trades.empty else np.nan
                rows.append({"variant": variant, "family": family, "horizon": horizon, "grossEdgeBpsPerActiveDay": gross_edge_bps,
                    **result, **concentration(contrib)})
    return {"panel": panel, "preliminary": preliminary, "exact": exact, "exact_panel": exact_panel, "inventory": inventory,
        "trades": pd.concat(trade_frames, ignore_index=True), "daily": pd.concat(daily_frames, ignore_index=True),
        "contrib": pd.concat(contrib_frames, ignore_index=True), "summary": pd.DataFrame(rows)}


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or prereg["implementation_freeze"]["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash is not frozen")
    dev = run_scope(DEV_END, "development")
    development = dev["summary"].copy()
    stress_metrics = []
    for variant, group in dev["daily"][dev["daily"]["cost_bps"].eq(STRESS_COST_BPS_PER_SIDE)].groupby("variant"):
        stress_metrics.append({"variant": variant, "stressPnl": metrics(group)["pnl"], "stressCagr": metrics(group)["cagr"]})
    development = development.merge(pd.DataFrame(stress_metrics), on="variant", validate="one_to_one")
    development["developmentPass"] = (development["tradeLegs"].ge(500) & development["cagr"].ge(0.08)
        & development["sharpe"].ge(1.0) & development["ddPct"].ge(-0.10) & development["positiveYears"].ge(4)
        & development["stressPnl"].gt(0) & development["grossEdgeBpsPerActiveDay"].ge(12.0)
        & development["top10PositiveShare"].le(0.50))
    development = development.sort_values(["developmentPass", "sharpe", "cagr", "variant"], ascending=[False, False, False, True])
    passing = development[development["developmentPass"]]
    validation_rows = []
    outputs = dev
    if passing.empty:
        selection = {"status": "KILL_NO_DEVELOPMENT_PASS", "selectedVariant": None, "validationOpened": False, "productionPassAllowed": False}
    else:
        selected = str(passing.iloc[0]["variant"])
        full = run_scope(END, "validation", variants=[selected], session_start=VAL_START)
        outputs = {key: pd.concat([dev[key], full[key]], ignore_index=True) if isinstance(dev[key], pd.DataFrame) and key not in {"summary"} else dev[key] for key in dev}
        selected_daily = full["daily"][(full["daily"]["variant"].eq(selected)) & full["daily"]["cost_bps"].eq(BASE_COST_BPS_PER_SIDE)]
        selected_stress = full["daily"][(full["daily"]["variant"].eq(selected)) & full["daily"]["cost_bps"].eq(STRESS_COST_BPS_PER_SIDE)]
        selected_contrib = full["contrib"][(full["contrib"]["variant"].eq(selected)) & full["contrib"]["cost_bps"].eq(BASE_COST_BPS_PER_SIDE)]
        result = metrics(selected_daily); stress_result = metrics(selected_stress)
        yearly = selected_daily.groupby(selected_daily["date"].dt.year)["daily_pnl"].sum()
        passed_validation = bool(result["pnl"] > 0 and result["sharpe"] >= 0.5 and result["ddPct"] >= -0.12 and stress_result["pnl"] > 0 and len(yearly) == 2 and yearly.gt(0).all())
        validation_rows.append({"variant": selected, "validationPass": passed_validation, "stressPnl": stress_result["pnl"], **result, **concentration(selected_contrib)})
        selection = {"status": "CONTINUE_DIAGNOSTIC" if passed_validation else "KILL_VALIDATION", "selectedVariant": selected,
            "validationOpened": True, "validationPass": passed_validation, "productionPassAllowed": False}

    daily = outputs["daily"]; contrib = outputs["contrib"]
    yearly = daily.assign(year=daily["date"].dt.year).groupby(["variant", "run_scope", "cost_bps", "year"], as_index=False).agg(
        pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"), tradingCost=("trading_cost", "sum"), borrowCost=("borrow_cost", "sum"), activeDays=("trade_legs", lambda x: int(x.gt(0).sum())), tradeLegs=("trade_legs", "sum"))
    qa_rows = []
    for (variant, scope, cost_bps), group in daily.groupby(["variant", "run_scope", "cost_bps"]):
        matching = contrib[(contrib["variant"].eq(variant)) & (contrib["run_scope"].eq(scope)) & (contrib["cost_bps"].eq(cost_bps))]
        ending = float(group.sort_values("date").iloc[-1]["equity"] - INITIAL_EQUITY)
        qa_rows.append({"variant": variant, "run_scope": scope, "cost_bps": cost_bps, "dailyPnl": group["daily_pnl"].sum(),
            "endingDelta": ending, "contribPnl": matching["net_pnl"].sum(), "dailyMinusEnding": group["daily_pnl"].sum() - ending,
            "dailyMinusContrib": group["daily_pnl"].sum() - matching["net_pnl"].sum()})
    qa = pd.DataFrame(qa_rows)
    coverage = pd.DataFrame([{"run_scope": "development", "panelRows": len(dev["panel"]), "preliminaryRows": len(dev["preliminary"]),
        "signalEntryCompleteRows": int(dev["exact_panel"]["signal_entry_complete"].sum()), "signalEntryMissingRows": int((~dev["exact_panel"]["signal_entry_complete"]).sum()),
        "rawFiles": len(dev["inventory"]), "rawFilesMissing": int((~dev["inventory"]["exists"]).sum()),
        "medianFeaturePriceErrorBps": dev["exact_panel"]["feature_price_error_bps"].median(), "maxFeaturePriceErrorBps": dev["exact_panel"]["feature_price_error_bps"].max()}])
    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False); pd.DataFrame(validation_rows).to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    outputs["trades"].to_csv(f"{PREFIX}_TRADES.csv", index=False); daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False); yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    qa.to_csv(f"{PREFIX}_QA.csv", index=False); coverage.to_csv(f"{PREFIX}_COVERAGE.csv", index=False)
    outputs["inventory"].to_csv(f"{PREFIX}_RAW_FILE_INVENTORY.csv", index=False); outputs["exact"].to_csv(f"{PREFIX}_EXACT_CLOCK_ROWS.csv", index=False)
    script = Path(__file__)
    manifest = {"script": str(script).replace("\\", "/"), "scriptHash": sha256(script), "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "selection": selection, "sample": [str(START.date()), str((END if selection["validationOpened"] else DEV_END).date())],
        "inputs": {str(DAILY): sha256(DAILY), str(INTRA): sha256(INTRA), str(CAPS): sha256(CAPS), str(ELIGIBLE): sha256(ELIGIBLE), str(RAW_MANIFEST): sha256(RAW_MANIFEST)},
        "rawFilesUsed": len(dev["inventory"]), "rawFileInventory": f"{PREFIX}_RAW_FILE_INVENTORY.csv", "oldManual62Used": False,
        "post2024Consumed": False, "productionPassAllowed": False,
        "causality": "09:30-09:35 bar and current cross-section finalize the signal after 09:35; execution is delayed to exact 09:40 open; exits are exact 09:50/09:55 opens; rolling beta and rvol baselines use prior sessions only."}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False)); print(pd.DataFrame(validation_rows).to_string(index=False)); print(json.dumps(selection, indent=2)); print(coverage.to_string(index=False))


if __name__ == "__main__":
    main()
