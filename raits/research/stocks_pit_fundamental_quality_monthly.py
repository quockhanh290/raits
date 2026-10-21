from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_sec_8k202_event_drift_replay as identity


PREREG = Path("STOCKS_PIT_FUNDAMENTAL_QUALITY_MONTHLY_PREREG_2026-09-24.json")
FINANCIAL_DIR = Path("raits/data/cache/external_events/polygon_2018_2024/financials")
INTRA = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
PREFIX = "STOCKS_PIT_FUNDAMENTAL_QUALITY_MONTHLY_2026-09-24"
START, DEV_END = pd.Timestamp("2018-04-27"), pd.Timestamp("2022-12-30")
VAL_START, END = pd.Timestamp("2023-01-03"), pd.Timestamp("2024-12-31")
INITIAL_EQUITY = 100_000.0
FACTOR_COLUMNS = ["operating_margin", "gross_margin", "roa", "cfo_assets", "current_ratio", "inverse_leverage", "accrual_quality"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def field_value(raw: str, statement: str, field: str) -> float:
    try:
        return float(json.loads(raw).get(statement, {}).get(field, {}).get("value", np.nan))
    except (TypeError, ValueError, json.JSONDecodeError):
        return np.nan


def load_financials() -> pd.DataFrame:
    columns = ["cik", "end_date", "filing_date", "fiscal_period", "fiscal_year", "timeframe", "source_filing_url", "financials_json"]
    frames = [pd.read_parquet(path, columns=columns) for path in sorted(FINANCIAL_DIR.glob("financials_*.parquet"))]
    x = pd.concat(frames, ignore_index=True)
    x["cik"] = identity.normalize_cik(x["cik"])
    x["end_date"] = pd.to_datetime(x["end_date"], errors="coerce").dt.normalize()
    x["filing_date"] = pd.to_datetime(x["filing_date"], errors="coerce").dt.normalize()
    x = x[x["timeframe"].eq("quarterly") & x["fiscal_period"].isin(["Q1", "Q2", "Q3", "Q4"])].copy()
    x = x[x["cik"].notna() & x["filing_date"].notna() & x["end_date"].lt(x["filing_date"])].copy()
    specs = {
        "revenue": ("income_statement", "revenues"),
        "gross_profit": ("income_statement", "gross_profit"),
        "operating_income": ("income_statement", "operating_income_loss"),
        "net_income": ("income_statement", "net_income_loss"),
        "cfo": ("cash_flow_statement", "net_cash_flow_from_operating_activities"),
        "assets": ("balance_sheet", "assets"),
        "liabilities": ("balance_sheet", "liabilities"),
        "current_assets": ("balance_sheet", "current_assets"),
        "current_liabilities": ("balance_sheet", "current_liabilities"),
    }
    for name, (statement, field) in specs.items():
        x[name] = [field_value(raw, statement, field) for raw in x["financials_json"]]
    positive_assets = x["assets"].gt(0)
    x["operating_margin"] = x["operating_income"] / x["revenue"]
    x["gross_margin"] = x["gross_profit"] / x["revenue"]
    x["roa"] = x["net_income"] / x["assets"]
    x["cfo_assets"] = x["cfo"] / x["assets"]
    x["current_ratio"] = x["current_assets"] / x["current_liabilities"]
    x["inverse_leverage"] = -x["liabilities"] / x["assets"]
    x["accrual_quality"] = (x["cfo"] - x["net_income"]) / x["assets"]
    x.loc[~positive_assets, FACTOR_COLUMNS] = np.nan
    x = x.replace([np.inf, -np.inf], np.nan)
    x.loc[~x["revenue"].gt(0), ["operating_margin", "gross_margin"]] = np.nan
    x.loc[~x["current_liabilities"].gt(0), "current_ratio"] = np.nan
    x = x.sort_values(["cik", "filing_date", "end_date", "source_filing_url"])
    return x.drop_duplicates(["cik", "filing_date", "end_date"], keep="first")


def load_market_data() -> tuple[pd.DataFrame, list[pd.Timestamp], dict[pd.Timestamp, pd.Series]]:
    intra = pd.read_pickle(INTRA)[["date", "ticker", "entry935"]].copy()
    intra["date"] = pd.to_datetime(intra["date"]).dt.normalize()
    intra["ticker"] = intra["ticker"].astype(str).str.upper()
    intra = intra[intra["date"].between(START, END) & intra["entry935"].gt(0)].drop_duplicates(["date", "ticker"])
    sessions = sorted(intra["date"].drop_duplicates())
    price_maps = {date: group.set_index("ticker")["entry935"] for date, group in intra.groupby("date", sort=True)}
    return intra, sessions, price_maps


def load_members() -> pd.DataFrame:
    members = identity.load_top500_representatives("development")
    caps = pd.read_csv(CAPS, low_memory=False)
    caps["snapshot_date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps = caps[["snapshot_date", "ticker", "sic_description"]].drop_duplicates(["snapshot_date", "ticker"])
    members = members.merge(caps, on=["snapshot_date", "ticker"], how="left", validate="one_to_one")
    members["sic_description"] = members["sic_description"].fillna("UNKNOWN").astype(str)
    return members


def robust_z(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame[column].astype(float)
    lo, hi = values.quantile([0.025, 0.975])
    clipped = values.clip(lo, hi)
    global_std = clipped.std(ddof=0)
    global_z = (clipped - clipped.mean()) / global_std if global_std > 0 else pd.Series(0.0, index=frame.index)
    counts = frame.groupby("sic_description")[column].transform("count")
    means = clipped.groupby(frame["sic_description"]).transform("mean")
    stds = clipped.groupby(frame["sic_description"]).transform(lambda s: s.std(ddof=0))
    local = (clipped - means) / stds.replace(0.0, np.nan)
    return local.where(counts.ge(5), global_z).fillna(global_z)


def choose_sector_capped(frame: pd.DataFrame, score: str, count: int, ascending: bool) -> list[str]:
    chosen: list[str] = []
    sector_counts: defaultdict[str, int] = defaultdict(int)
    for row in frame.sort_values([score, "market_cap", "ticker"], ascending=[ascending, False, True]).itertuples():
        sector = str(row.sic_description)
        if sector_counts[sector] >= 3:
            continue
        chosen.append(str(row.ticker))
        sector_counts[sector] += 1
        if len(chosen) == count:
            break
    return chosen


def build_monthly_panels(financials: pd.DataFrame, members: pd.DataFrame, sessions: list[pd.Timestamp], price_maps: dict[pd.Timestamp, pd.Series]) -> tuple[pd.DataFrame, dict[str, dict[pd.Timestamp, dict[str, float]]]]:
    monthly = [date for index, date in enumerate(sessions) if index == 0 or date.month != sessions[index - 1].month]
    snapshots = members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned = pd.merge_asof(pd.DataFrame({"date": monthly}), snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    eligible = identity.load_eligible("development", START, END)
    panels = []
    targets: dict[str, dict[pd.Timestamp, dict[str, float]]] = {name: {} for name in ("profitability_long30", "balance_quality_long30", "composite_long30", "composite_ls30", "top500_equal_weight")}
    for date, snapshot_date in assigned.itertuples(index=False):
        universe = members[members["snapshot_date"].eq(snapshot_date)].copy()
        universe = universe.merge(eligible.loc[eligible["date"].eq(date), ["ticker", "adv20"]], on="ticker", how="inner", validate="one_to_one")
        universe = universe[universe["adv20"].ge(10_000_000) & universe["ticker"].isin(price_maps[date].index)].copy()
        known = financials[financials["filing_date"].lt(date) & financials["filing_date"].ge(date - pd.Timedelta(days=200))]
        known = known.sort_values(["cik", "filing_date", "end_date"]).drop_duplicates("cik", keep="last")
        panel = universe.merge(known[["cik", "filing_date", "end_date", *FACTOR_COLUMNS]], on="cik", how="inner", validate="many_to_one")
        for column in FACTOR_COLUMNS:
            panel[f"z_{column}"] = robust_z(panel, column)
        profit = [f"z_{name}" for name in ("operating_margin", "gross_margin", "roa", "cfo_assets")]
        balance = [f"z_{name}" for name in ("current_ratio", "inverse_leverage", "accrual_quality")]
        panel["profitability_score"] = panel[profit].mean(axis=1, skipna=True).where(panel[profit].notna().sum(axis=1).ge(3))
        panel["balance_score"] = panel[balance].mean(axis=1, skipna=True).where(panel[balance].notna().sum(axis=1).ge(2))
        panel["composite_score"] = panel[[*profit, *balance]].mean(axis=1, skipna=True).where(panel[[*profit, *balance]].notna().sum(axis=1).ge(5))
        panel["date"] = date
        panel["filing_age_days"] = (date - panel["filing_date"]).dt.days
        panels.append(panel)
        for name, score in (("profitability_long30", "profitability_score"), ("balance_quality_long30", "balance_score"), ("composite_long30", "composite_score")):
            selected = choose_sector_capped(panel.dropna(subset=[score]), score, 30, ascending=False)
            targets[name][date] = {ticker: 0.95 / len(selected) for ticker in selected} if selected else {}
        valid = panel.dropna(subset=["composite_score"])
        longs = choose_sector_capped(valid, "composite_score", 30, ascending=False)
        shorts = choose_sector_capped(valid[~valid["ticker"].isin(longs)], "composite_score", 30, ascending=True)
        targets["composite_ls30"][date] = ({ticker: 0.475 / len(longs) for ticker in longs} | {ticker: -0.475 / len(shorts) for ticker in shorts}) if longs and shorts else {}
        benchmark = universe.sort_values(["market_cap", "ticker"], ascending=[False, True])["ticker"].tolist()
        targets["top500_equal_weight"][date] = {ticker: 0.95 / len(benchmark) for ticker in benchmark} if benchmark else {}
    return pd.concat(panels, ignore_index=True), targets


def simulate(name: str, targets: dict[pd.Timestamp, dict[str, float]], sessions: list[pd.Timestamp], price_maps: dict[pd.Timestamp, pd.Series], cost_bps: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    positions: dict[str, float] = {}
    last_prices: dict[str, float] = {}
    cash = INITIAL_EQUITY
    peak = INITIAL_EQUITY
    daily_rows, trade_rows, contrib_rows = [], [], []
    for date in sessions:
        exact = price_maps.get(date, pd.Series(dtype=float))
        mark_pnl = 0.0
        missing = 0
        for ticker, shares in list(positions.items()):
            old = last_prices[ticker]
            if ticker in exact.index and np.isfinite(float(exact[ticker])):
                new = float(exact[ticker]); last_prices[ticker] = new
                pnl = shares * (new - old); mark_pnl += pnl
                if pnl:
                    contrib_rows.append({"scenario": name, "date": date, "ticker": ticker, "component": "mark", "pnl": pnl})
            else:
                missing += 1
        equity_before_cost = cash + sum(shares * last_prices[ticker] for ticker, shares in positions.items())
        short_gross = sum(abs(shares * last_prices[ticker]) for ticker, shares in positions.items() if shares < 0)
        borrow = short_gross * 0.01 / 252.0
        cash -= borrow
        if borrow:
            contrib_rows.append({"scenario": name, "date": date, "ticker": "__BORROW__", "component": "borrow", "pnl": -borrow})
        turnover = cost = 0.0
        if date in targets:
            desired = targets[date]
            tradable = set(desired).union(ticker for ticker in positions if ticker in exact.index)
            equity = cash + sum(shares * last_prices[ticker] for ticker, shares in positions.items())
            for ticker in sorted(tradable):
                if ticker not in exact.index or not np.isfinite(float(exact[ticker])):
                    continue
                price = float(exact[ticker]); last_prices[ticker] = price
                old_shares = positions.get(ticker, 0.0)
                target_shares = desired.get(ticker, 0.0) * equity / price
                cash -= (target_shares - old_shares) * price
                traded = abs(target_shares - old_shares) * price
                turnover += traded
                if abs(target_shares) < 1e-12:
                    positions.pop(ticker, None)
                else:
                    positions[ticker] = target_shares
                if traded:
                    trade_rows.append({"scenario": name, "date": date, "ticker": ticker, "old_shares": old_shares, "new_shares": target_shares, "price": price, "turnover": traded})
            cost = turnover * cost_bps / 10_000.0
            cash -= cost
            if cost:
                contrib_rows.append({"scenario": name, "date": date, "ticker": "__TRADING_COST__", "component": "cost", "pnl": -cost})
        equity = cash + sum(shares * last_prices[ticker] for ticker, shares in positions.items())
        event_pnl = equity - (daily_rows[-1]["equity"] if daily_rows else INITIAL_EQUITY)
        peak = max(peak, equity)
        gross = sum(abs(shares * last_prices[ticker]) for ticker, shares in positions.items()) / equity if equity > 0 else np.nan
        daily_rows.append({"scenario": name, "date": date, "equity": equity, "daily_pnl": event_pnl, "mark_pnl": mark_pnl,
            "turnover": turnover, "trading_cost": cost, "borrow_cost": borrow, "gross": gross, "positions": len(positions),
            "missing_marks": missing, "dd_dollar": equity - peak, "dd_pct": equity / peak - 1.0})
    return pd.DataFrame(daily_rows), pd.DataFrame(trade_rows), pd.DataFrame(contrib_rows)


def metrics(daily: pd.DataFrame, begin: pd.Timestamp, finish: pd.Timestamp) -> dict[str, float]:
    x = daily[daily["date"].between(begin, finish)].copy()
    start_equity = float(x.iloc[0]["equity"] - x.iloc[0]["daily_pnl"])
    returns = x["daily_pnl"] / (x["equity"] - x["daily_pnl"])
    years = max((x.iloc[-1]["date"] - x.iloc[0]["date"]).days / 365.25, 1e-9)
    curve = pd.concat([pd.Series([start_equity]), x["equity"].reset_index(drop=True)], ignore_index=True)
    peak = curve.cummax()
    yearly = x.assign(ret=returns).groupby(x["date"].dt.year)["ret"].apply(lambda r: (1.0 + r).prod() - 1.0)
    return {"pnl": float(x["daily_pnl"].sum()), "cagr": float((x.iloc[-1]["equity"] / start_equity) ** (1.0 / years) - 1.0),
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else np.nan,
        "ddDollar": float((curve - peak).min()), "ddPct": float((curve / peak - 1.0).min()),
        "positiveYears": int(yearly.gt(0).sum()), "avgGross": float(x["gross"].mean()), "maxGross": float(x["gross"].max()),
        "turnover": float(x["turnover"].sum()), "cost": float(x["trading_cost"].sum()), "borrow": float(x["borrow_cost"].sum()),
        "maxMissingMarks": int(x["missing_marks"].max())}


def concentration(contrib: pd.DataFrame, begin: pd.Timestamp, finish: pd.Timestamp) -> dict[str, object]:
    x = contrib[contrib["date"].between(begin, finish) & ~contrib["ticker"].str.startswith("__")]
    by = x.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    positive = by[by > 0]; positive_total = float(positive.sum()); net = float(by.sum())
    row: dict[str, object] = {"tickers": len(by), "topTicker": by.index[0] if len(by) else "",
        "effectiveTickerCount": float(positive_total**2 / positive.pow(2).sum()) if positive_total > 0 else 0.0}
    for count in (1, 3, 5, 10):
        top = float(positive.head(count).sum())
        row[f"top{count}PositiveShare"] = top / positive_total if positive_total else np.nan
        row[f"top{count}NetShare"] = top / net if net > 0 else np.nan
    return row


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or prereg["implementation_freeze"]["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash is not frozen")
    financials = load_financials()
    _, sessions, price_maps = load_market_data()
    members = load_members()
    dev_sessions = [date for date in sessions if date <= DEV_END]
    dev_prices = {date: price_maps[date] for date in dev_sessions}
    panels, targets = build_monthly_panels(financials, members, dev_sessions, dev_prices)
    variants = [row["name"] for row in prereg["variants"]]
    daily_frames, trade_frames, contrib_frames, dev_rows = [], [], [], []
    runs: dict[tuple[str, float], tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]] = {}
    for name in [*variants, "top500_equal_weight"]:
        for cost in ([4.0, 8.0] if name in variants else [4.0]):
            result = simulate(name, targets[name], dev_sessions, dev_prices, cost)
            runs[(name, cost)] = result
            daily_frames.append(result[0].assign(run_scope="development_search" if name in variants else "benchmark" , cost_bps=cost))
            trade_frames.append(result[1].assign(run_scope="development_search" if name in variants else "benchmark", cost_bps=cost))
            contrib_frames.append(result[2].assign(run_scope="development_search" if name in variants else "benchmark", cost_bps=cost))
    benchmark_metrics = metrics(runs[("top500_equal_weight", 4.0)][0], START, DEV_END)
    for spec in prereg["variants"]:
        name = spec["name"]
        daily, _, contrib = runs[(name, 4.0)]
        base = metrics(daily, START, DEV_END); stress = metrics(runs[(name, 8.0)][0], START, DEV_END)
        active_cagr = base["cagr"] - benchmark_metrics["cagr"] if spec["book"] == "long_only" else base["cagr"]
        passed = bool(base["cagr"] >= spec["gate"]["min_cagr"] and active_cagr >= spec["gate"]["min_active_cagr"]
            and base["sharpe"] >= 0.60 and base["ddPct"] >= -0.25 and base["positiveYears"] >= 4 and stress["pnl"] > 0)
        dev_rows.append({"variant": name, "book": spec["book"], "developmentPass": passed, "activeCagr": active_cagr,
            "benchmarkCagr": benchmark_metrics["cagr"], "stressPnl": stress["pnl"], "stressCagr": stress["cagr"], **base,
            **concentration(contrib, START, DEV_END)})
    development = pd.DataFrame(dev_rows).sort_values(["developmentPass", "sharpe", "cagr"], ascending=False)
    passing = development[development["developmentPass"]]
    validation_rows = []
    if passing.empty:
        selection = {"status": "KILL_NO_DEVELOPMENT_PASS", "selectedVariant": None, "validationOpened": False, "productionPassAllowed": False}
    else:
        selected = str(passing.iloc[0]["variant"]); spec = next(row for row in prereg["variants"] if row["name"] == selected)
        panels, full_targets = build_monthly_panels(financials, members, sessions, price_maps)
        selected_runs = {}
        for cost in (4.0, 8.0):
            result = simulate(selected, full_targets[selected], sessions, price_maps, cost)
            selected_runs[cost] = result
            daily_frames.append(result[0].assign(run_scope="selected_full", cost_bps=cost))
            trade_frames.append(result[1].assign(run_scope="selected_full", cost_bps=cost))
            contrib_frames.append(result[2].assign(run_scope="selected_full", cost_bps=cost))
        benchmark_full = simulate("top500_equal_weight", full_targets["top500_equal_weight"], sessions, price_maps, 4.0)
        daily_frames.append(benchmark_full[0].assign(run_scope="selected_full_benchmark", cost_bps=4.0))
        trade_frames.append(benchmark_full[1].assign(run_scope="selected_full_benchmark", cost_bps=4.0))
        contrib_frames.append(benchmark_full[2].assign(run_scope="selected_full_benchmark", cost_bps=4.0))
        base_daily, _, base_contrib = selected_runs[4.0]
        val = metrics(base_daily, VAL_START, END); val_stress = metrics(selected_runs[8.0][0], VAL_START, END)
        val_bench = metrics(benchmark_full[0], VAL_START, END)
        active = val["cagr"] - val_bench["cagr"] if spec["book"] == "long_only" else val["cagr"]
        val_daily = base_daily[base_daily["date"].between(VAL_START, END)].copy()
        years = val_daily.groupby(val_daily["date"].dt.year)["daily_pnl"].sum()
        val_pass = bool(val["pnl"] > 0 and active > 0 and val["ddPct"] >= -0.25 and val_stress["pnl"] > 0 and len(years) == 2 and years.gt(0).all())
        validation_rows.append({"variant": selected, "validationPass": val_pass, "activeCagr": active, "benchmarkCagr": val_bench["cagr"],
            "stressPnl": val_stress["pnl"], **val, **concentration(base_contrib, VAL_START, END)})
        selection = {"status": "CONTINUE_DIAGNOSTIC" if val_pass else "KILL_VALIDATION", "selectedVariant": selected,
            "validationOpened": True, "validationPass": val_pass, "productionPassAllowed": False}
    all_daily = pd.concat(daily_frames, ignore_index=True); all_trades = pd.concat(trade_frames, ignore_index=True); all_contrib = pd.concat(contrib_frames, ignore_index=True)
    yearly = all_daily.assign(year=all_daily["date"].dt.year).groupby(["scenario", "run_scope", "cost_bps", "year"], as_index=False).agg(pnl=("daily_pnl", "sum"), tradingCost=("trading_cost", "sum"), borrowCost=("borrow_cost", "sum"), avgGross=("gross", "mean"), maxGross=("gross", "max"), maxMissingMarks=("missing_marks", "max"))
    coverage = panels.groupby("date").agg(members=("ticker", "size"), profitability=("profitability_score", "count"), balance=("balance_score", "count"), composite=("composite_score", "count"), filingAgeMedian=("filing_age_days", "median")).reset_index()
    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False); pd.DataFrame(validation_rows).to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    panels.to_csv(f"{PREFIX}_FACTOR_PANEL.csv", index=False); coverage.to_csv(f"{PREFIX}_COVERAGE.csv", index=False)
    all_daily.to_csv(f"{PREFIX}_DAILY.csv", index=False); yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    all_trades.to_csv(f"{PREFIX}_TRADES.csv", index=False); all_contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)
    financial_files = sorted(FINANCIAL_DIR.glob("financials_*.parquet"))
    measured_end = END if selection["validationOpened"] else DEV_END
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)), "preregistration": str(PREREG),
        "preregistrationHash": sha256(PREREG), "sample": [str(START.date()), str(measured_end.date())], "developmentEnd": str(DEV_END.date()),
        "validationStart": str(VAL_START.date()), "selection": selection, "oldManual62Used": False, "oos2025_2026Consumed": False,
        "invalidRunPreserved": "STOCKS_PIT_FUNDAMENTAL_QUALITY_MONTHLY_2026-09-24_INVALID_PREMATURE_VALIDATION_*",
        "inputs": {str(INTRA): sha256(INTRA), str(CAPS): sha256(CAPS), str(identity.FILTER_PATHS[0]): sha256(identity.FILTER_PATHS[0])},
        "financialInputHashes": {path.name: sha256(path) for path in financial_files}, "productionPassAllowed": False}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False)); print(pd.DataFrame(validation_rows).to_string(index=False)); print(json.dumps(selection, indent=2))


if __name__ == "__main__":
    main()
