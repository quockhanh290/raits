from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BETA_PLUS_MEGASPREAD_AUDIT_2026-09-14"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)
BETA_DAILY = Path("STOCKS_PIT_FULL_BETA_VOLTARGET_EXPANSION_2026-09-14_DAILY.csv")

START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
VARIANT = "spy_vt16_plus_top62_top200_spread3_constituent_audit"
SPY_STREAM = "spy_vt16_cap150"
SPREAD_WEIGHT = 3.0
LONG_TOP_N = 62
SHORT_TOP_N = 200
TRADE_COST_BPS = 4.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    dd = equity - peak
    dd_pct = equity / peak - 1.0
    return float(dd.min()), float(dd_pct.min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    if std <= 0:
        return float("nan")
    return float(pnl.mean() / std * math.sqrt(252))


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def load_stock_returns() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily = daily[(daily["date"] >= START) & (daily["date"] <= END)].copy()
    daily = daily.dropna(subset=["ticker", "prev_close_1555", "close_1555"])
    daily = daily[(daily["prev_close_1555"] > 0) & (daily["close_1555"] > 0)].copy()
    daily["ret_close_to_close"] = daily["close_1555"] / daily["prev_close_1555"] - 1.0
    return daily[["date", "ticker", "ret_close_to_close"]].copy()


def load_market_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker_query"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps


def top_membership(caps: pd.DataFrame, top_n: int) -> pd.DataFrame:
    selected = caps[caps["rank_market_cap"].le(top_n)].copy()
    return (
        selected.groupby("date", sort=True)["ticker_query"]
        .apply(lambda s: set(s.astype(str)))
        .rename("ticker_set")
        .reset_index()
    )


def assign_membership_dates(dates: pd.Series, membership: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    grid = pd.DataFrame({"date": sorted(pd.to_datetime(dates).drop_duplicates())})
    assigned = pd.merge_asof(grid, membership.sort_values("date"), on="date", direction="backward")
    return {
        row.date: (row.ticker_set if isinstance(row.ticker_set, set) else set())
        for row in assigned.itertuples(index=False)
    }


def load_spy_stream() -> pd.DataFrame:
    x = pd.read_csv(BETA_DAILY, parse_dates=["date"])
    x = x[x["variant"].eq(SPY_STREAM)].sort_values("date").copy()
    x = x[(x["date"] >= START) & (x["date"] <= END)].copy()
    x["equity_lag"] = x["equity"].shift(1).fillna(START_CAPITAL)
    x["spy_ret"] = x["daily_pnl"] / x["equity_lag"]
    return x[["date", "spy_ret", "exposure", "base_ret"]].rename(
        columns={"exposure": "spy_exposure", "base_ret": "spy_base_ret"}
    )


def target_weights_for_date(group: pd.DataFrame, long_set: set[str], short_set: set[str]) -> pd.Series:
    available = set(group["ticker"])
    long_names = sorted(long_set & available)
    short_names = sorted(short_set & available)
    weights: dict[str, float] = {}
    if long_names:
        long_weight = SPREAD_WEIGHT / len(long_names)
        for ticker in long_names:
            weights[ticker] = weights.get(ticker, 0.0) + long_weight
    if short_names:
        short_weight = SPREAD_WEIGHT / len(short_names)
        for ticker in short_names:
            weights[ticker] = weights.get(ticker, 0.0) - short_weight
    return pd.Series(weights, dtype=float)


def effective_ticker_count(pnl_by_ticker: pd.Series) -> float:
    positive = pnl_by_ticker[pnl_by_ticker > 0]
    weights_source = positive if positive.sum() > 0 else pnl_by_ticker.abs()
    total = float(weights_source.sum())
    if total <= 0:
        return 0.0
    weights = weights_source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(scope: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker", sort=False)["pnl"].sum().sort_values(ascending=False)
    total = float(contrib["pnl"].sum())
    denom = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": VARIANT,
        "scope": scope,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        "topTickerPnl": float(by_ticker.iloc[0]) if not by_ticker.empty else 0.0,
        "totalPnl": total,
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denom if denom else float("nan")
    return row


def period_rows(daily: pd.DataFrame, period_col: str) -> list[dict[str, object]]:
    rows = []
    for period, group in daily.groupby(period_col, sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append(
            {
                "variant": VARIANT,
                period_col: period,
                "pnl": float(group["daily_pnl"].sum()),
                "spreadGrossPnl": float(group["spread_gross_pnl"].sum()),
                "spreadCost": float(group["spread_cost"].sum()),
                "spyPnl": float(group["spy_pnl"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "avgGrossExposure": float(group["gross_exposure"].mean()),
                "avgNetExposure": float(group["net_exposure"].mean()),
                "avgTurnover": float(group["spread_turnover"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def simulate() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    stocks = load_stock_returns()
    caps = load_market_caps()
    spy = load_spy_stream()
    dates = sorted(set(stocks["date"]) & set(spy["date"]))
    stocks = stocks[stocks["date"].isin(dates)].copy()
    spy_by_date = spy.set_index("date")

    long_by_date = assign_membership_dates(pd.Series(dates), top_membership(caps, LONG_TOP_N))
    short_by_date = assign_membership_dates(pd.Series(dates), top_membership(caps, SHORT_TOP_N))

    equity = START_CAPITAL
    prev_weights = pd.Series(dtype=float)
    daily_rows = []
    contrib_rows = []
    cost_rate = TRADE_COST_BPS / 10_000.0

    for date, group in stocks.groupby("date", sort=True):
        target = target_weights_for_date(group, long_by_date[date], short_by_date[date])
        group = group.set_index("ticker")
        rets = group["ret_close_to_close"].reindex(target.index).fillna(0.0)
        aligned_prev = prev_weights.reindex(target.index.union(prev_weights.index)).fillna(0.0)
        aligned_target = target.reindex(aligned_prev.index).fillna(0.0)
        delta = aligned_target - aligned_prev
        turnover = float(delta.abs().sum())
        gross_exposure = float(target.abs().sum())
        net_exposure = float(target.sum()) + float(spy_by_date.loc[date, "spy_exposure"])
        spread_ret_gross = float((target * rets).sum())
        spread_cost_ret = cost_rate * turnover
        spy_ret = float(spy_by_date.loc[date, "spy_ret"])
        daily_ret = spy_ret + spread_ret_gross - spread_cost_ret
        daily_pnl = equity * daily_ret
        spread_gross_pnl = equity * spread_ret_gross
        spread_cost = equity * spread_cost_ret
        spy_pnl = equity * spy_ret

        rets_for_contrib = group["ret_close_to_close"].reindex(aligned_target.index).fillna(0.0)
        ticker_pnl = equity * aligned_target * rets_for_contrib
        if spread_cost > 0 and turnover > 0:
            cost_alloc = (delta.abs() / turnover) * spread_cost
            ticker_pnl = ticker_pnl - cost_alloc
        nonzero_contrib = ticker_pnl[(aligned_target.abs() > 0) | (ticker_pnl.abs() > 0)]
        contrib_rows.extend(
            {
                "variant": VARIANT,
                "date": date,
                "ticker": ticker,
                "scope": "spread_only",
                "weight": float(aligned_target.loc[ticker]),
                "ret": float(rets_for_contrib.loc[ticker]),
                "pnl": float(pnl),
            }
            for ticker, pnl in nonzero_contrib.items()
        )
        contrib_rows.append(
            {
                "variant": VARIANT,
                "date": date,
                "ticker": "SPY_SLEEVE",
                "scope": "total_with_spy",
                "weight": float(spy_by_date.loc[date, "spy_exposure"]),
                "ret": spy_ret,
                "pnl": spy_pnl,
            }
        )
        contrib_rows.extend(
            {
                "variant": VARIANT,
                "date": date,
                "ticker": ticker,
                "scope": "total_with_spy",
                "weight": float(aligned_target.loc[ticker]),
                "ret": float(rets_for_contrib.loc[ticker]),
                "pnl": float(pnl),
            }
            for ticker, pnl in nonzero_contrib.items()
        )

        equity += daily_pnl
        daily_rows.append(
            {
                "variant": VARIANT,
                "date": date,
                "spy_ret": spy_ret,
                "spy_exposure": float(spy_by_date.loc[date, "spy_exposure"]),
                "spread_ret_gross": spread_ret_gross,
                "spread_cost_ret": spread_cost_ret,
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "spy_pnl": spy_pnl,
                "spread_gross_pnl": spread_gross_pnl,
                "spread_cost": spread_cost,
                "equity": equity,
                "spread_turnover": turnover,
                "gross_exposure": gross_exposure + float(spy_by_date.loc[date, "spy_exposure"]),
                "net_exposure": net_exposure,
                "long_names": int((target > 0).sum()),
                "short_names": int((target < 0).sum()),
            }
        )
        prev_weights = target

    daily = add_periods(pd.DataFrame(daily_rows))
    contrib = pd.DataFrame(contrib_rows)
    qa = pd.DataFrame(
        [
            {
                "variant": VARIANT,
                "stock_return_rows": int(len(stocks)),
                "stock_tickers": int(stocks["ticker"].nunique()),
                "days": int(len(daily)),
                "long_top_n": LONG_TOP_N,
                "short_top_n": SHORT_TOP_N,
                "spread_weight": SPREAD_WEIGHT,
                "trade_cost_bps": TRADE_COST_BPS,
                "avg_spread_turnover": float(daily["spread_turnover"].mean()),
                "total_spread_turnover": float(daily["spread_turnover"].sum()),
                "avg_long_names": float(daily["long_names"].mean()),
                "avg_short_names": float(daily["short_names"].mean()),
                "avg_gross_exposure": float(daily["gross_exposure"].mean()),
                "max_gross_exposure": float(daily["gross_exposure"].max()),
            }
        ]
    )
    return daily, contrib, qa


def main() -> None:
    daily, contrib, qa = simulate()
    dd, dd_pct = max_drawdown(daily["equity"])
    summary = {
        "variant": VARIANT,
        "candidate_from": "section_6_170_spy_vt16_plus_top62_top200_spread3",
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "spyPnl": float(daily["spy_pnl"].sum()),
        "spreadGrossPnl": float(daily["spread_gross_pnl"].sum()),
        "spreadCost": float(daily["spread_cost"].sum()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "avgNetExposure": float(daily["net_exposure"].mean()),
        "avgSpreadTurnover": float(daily["spread_turnover"].mean()),
        "totalSpreadTurnover": float(daily["spread_turnover"].sum()),
    }
    pd.DataFrame([summary]).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(daily, "split")).to_csv(SPLIT_OUT, index=False)
    concentration = [
        concentration_row("spread_only", contrib[contrib["scope"].eq("spread_only")]),
        concentration_row("total_with_spy", contrib[contrib["scope"].eq("total_with_spy")]),
    ]
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    daily.to_csv(DAILY_OUT, index=False)
    contrib.to_csv(CONTRIB_OUT, index=False)
    qa.to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_beta_plus_megaspread_audit.py",
        "inputs": [
            str(DAILY_FEATURES).replace("\\", "/"),
            str(MARKET_CAP_CSV).replace("\\", "/"),
            str(BETA_DAILY).replace("\\", "/"),
        ],
        "sample_period": [START.strftime("%Y-%m-%d"), END.strftime("%Y-%m-%d")],
        "candidate": VARIANT,
        "data_contract": "PIT clean daily feature cache provides close_1555/prev_close_1555 returns; Polygon market-cap snapshots provide PIT top62/top200 membership; SPY vt16 sleeve is the fixed stream generated in section 6.153.",
        "leakage_controls": "No old manual 62 ticker list. No 2025-2026 data. Top-N membership uses as-of market-cap snapshots via backward merge onto trading dates. Candidate family was selected in section 6.170; this script audits only the leading fixed row.",
        "costs": f"Spread sleeve charges {TRADE_COST_BPS} bps per dollar of absolute target-weight change. No short borrow, financing, or SPY ETF trading costs are included.",
        "rule_selection_effect": "No walk-forward or variant re-selection inside this audit. It isolates trade-selection/implementation effect versus the optimistic section 6.170 return-stream ensemble.",
        "outputs": [
            str(SUMMARY_OUT),
            str(YEARLY_OUT),
            str(SPLIT_OUT),
            str(CONCENTRATION_OUT),
            str(DAILY_OUT),
            str(CONTRIB_OUT),
            str(QA_OUT),
        ],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("SUMMARY", summary, flush=True)
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
