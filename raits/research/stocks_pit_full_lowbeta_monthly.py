from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_LOWBETA_MONTHLY_2026-09-15"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)
START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
POOL_TOP_N = 500
TRADE_COST_BPS = 4.0
SHORT_BORROW_ANNUAL_RATE = 0.01

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# New pre-registered low-beta family. Monthly rebalance; weights are applied
# after the rebalance-day close, so no same-day close-to-close return is earned.
VARIANTS = [
    {"variant": "top500_lowbeta50_long_gross100", "mode": "long", "long_n": 50, "short_n": 0, "trend_gate": False},
    {"variant": "top500_lowbeta100_long_gross100", "mode": "long", "long_n": 100, "short_n": 0, "trend_gate": False},
    {"variant": "top500_lowbeta50_posret60_long_gross100", "mode": "long", "long_n": 50, "short_n": 0, "trend_gate": True},
    {"variant": "top500_lowbeta100_posret60_long_gross100", "mode": "long", "long_n": 100, "short_n": 0, "trend_gate": True},
    {"variant": "top500_lowbeta_highbeta_ls50_50_gross100", "mode": "long_short", "long_n": 50, "short_n": 50, "trend_gate": False},
    {"variant": "top500_lowbeta_highbeta_ls100_100_gross100", "mode": "long_short", "long_n": 100, "short_n": 100, "trend_gate": False},
]


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    return float((equity - peak).min()), float((equity / peak - 1.0).min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    return float(pnl.mean() / std * math.sqrt(252)) if std > 0 else float("nan")


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_daily() -> pd.DataFrame:
    x = pd.read_pickle(DAILY_FEATURES)
    x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    x["ticker"] = x["ticker"].astype(str).str.upper()
    cols = ["date", "ticker", "prev_close_1555", "close_1555", "ret60_pre"]
    x = x[(x["date"] >= START) & (x["date"] <= END)][cols].copy()
    x = x.dropna(subset=cols)
    x = x[(x["prev_close_1555"] > 0) & (x["close_1555"] > 0)].copy()
    x["ret_close_to_close"] = x["close_1555"] / x["prev_close_1555"] - 1.0
    return x[["date", "ticker", "ret_close_to_close", "ret60_pre"]].copy()


def load_pool_membership() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker_query"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    selected = caps[caps["rank_market_cap"].le(POOL_TOP_N)].copy()
    return (
        selected.groupby("date", sort=True)["ticker_query"]
        .apply(lambda s: set(s.astype(str)))
        .rename("ticker_set")
        .reset_index()
    )


def apply_pool(daily: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    assigned = pd.merge_asof(dates, membership.sort_values("date"), on="date", direction="backward")
    date_to_set = dict(zip(assigned["date"], assigned["ticker_set"]))
    sets = daily["date"].map(date_to_set)
    mask = [ticker in s if isinstance(s, set) else False for ticker, s in zip(daily["ticker"], sets)]
    return daily.loc[mask].copy()


def add_low_beta_features(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.sort_values(["ticker", "date"]).copy()
    broad = x.groupby("date", as_index=False)["ret_close_to_close"].mean().rename(columns={"ret_close_to_close": "broad_ret"})
    x = x.merge(broad, on="date", how="left")
    x["xy"] = x["ret_close_to_close"] * x["broad_ret"]
    x["xmean60"] = x.groupby("ticker")["ret_close_to_close"].transform(lambda s: s.rolling(60, min_periods=40).mean().shift(1))
    x["ymean60"] = x.groupby("ticker")["broad_ret"].transform(lambda s: s.rolling(60, min_periods=40).mean().shift(1))
    x["xymean60"] = x.groupby("ticker")["xy"].transform(lambda s: s.rolling(60, min_periods=40).mean().shift(1))
    broad_var = broad.sort_values("date").copy()
    broad_var["ymean"] = broad_var["broad_ret"].rolling(60, min_periods=40).mean().shift(1)
    broad_var["y2mean"] = (broad_var["broad_ret"] ** 2).rolling(60, min_periods=40).mean().shift(1)
    broad_var["broad_var60"] = broad_var["y2mean"] - broad_var["ymean"] ** 2
    x = x.merge(broad_var[["date", "broad_var60"]], on="date", how="left")
    cov = x["xymean60"] - x["xmean60"] * x["ymean60"]
    x["beta60_pre"] = cov / x["broad_var60"].replace(0.0, np.nan)
    return x.dropna(subset=["beta60_pre"]).copy()


def rebalance_dates(daily: pd.DataFrame) -> set[pd.Timestamp]:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    return set(dates.groupby(dates["date"].dt.to_period("M"))["date"].min().tolist())


def target_weights(group: pd.DataFrame, spec: dict[str, object]) -> pd.Series:
    ranked = group.copy()
    if spec["trend_gate"]:
        ranked = ranked[ranked["ret60_pre"] > 0].copy()
    ranked = ranked.sort_values(["beta60_pre", "ticker"], ascending=[True, True])
    weights: dict[str, float] = {}
    long_names = ranked.head(int(spec["long_n"]))["ticker"].tolist()
    if spec["mode"] == "long":
        if long_names:
            w = 1.0 / len(long_names)
            weights.update({ticker: w for ticker in long_names})
    elif spec["mode"] == "long_short":
        short_names = ranked.tail(int(spec["short_n"]))["ticker"].tolist()
        if long_names:
            w = 0.5 / len(long_names)
            weights.update({ticker: w for ticker in long_names})
        if short_names:
            w = -0.5 / len(short_names)
            for ticker in short_names:
                weights[ticker] = weights.get(ticker, 0.0) + w
    else:
        raise ValueError(str(spec["mode"]))
    return pd.Series(weights, dtype=float)


def effective_ticker_count(pnl_by_ticker: pd.Series) -> float:
    positive = pnl_by_ticker[pnl_by_ticker > 0]
    weights_source = positive if positive.sum() > 0 else pnl_by_ticker.abs()
    total = float(weights_source.sum())
    if total <= 0:
        return 0.0
    weights = weights_source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(contrib["pnl"].sum())
    denom = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
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


def simulate(spec: dict[str, object], daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_date = {date: group.set_index("ticker") for date, group in daily.groupby("date", sort=True)}
    rdates = rebalance_dates(daily)
    weights = pd.Series(dtype=float)
    pending_weights: pd.Series | None = None
    equity = START_CAPITAL
    rows = []
    contrib_rows = []
    cost_rate = TRADE_COST_BPS / 10_000.0
    borrow_daily = SHORT_BORROW_ANNUAL_RATE / 252.0
    for date in sorted(by_date):
        if pending_weights is not None:
            weights = pending_weights
            pending_weights = None
        group = by_date[date]
        rets = group["ret_close_to_close"].reindex(weights.index).fillna(0.0)
        pnl_by_ticker = equity * weights * rets if not weights.empty else pd.Series(dtype=float)
        short_gross = float(weights[weights < 0].abs().sum()) if not weights.empty else 0.0
        borrow_cost = equity * short_gross * borrow_daily
        if borrow_cost > 0 and short_gross > 0:
            alloc = weights[weights < 0].abs() / short_gross * borrow_cost
            pnl_by_ticker.loc[alloc.index] = pnl_by_ticker.loc[alloc.index] - alloc
        daily_pnl = float(pnl_by_ticker.sum()) if not pnl_by_ticker.empty else 0.0
        equity += daily_pnl
        trade_cost = 0.0
        turnover = 0.0
        if date in rdates:
            new_weights = target_weights(group.reset_index(), spec)
            aligned_old = weights.reindex(new_weights.index.union(weights.index)).fillna(0.0)
            aligned_new = new_weights.reindex(aligned_old.index).fillna(0.0)
            turnover = float((aligned_new - aligned_old).abs().sum())
            trade_cost = equity * turnover * cost_rate
            equity -= trade_cost
            if trade_cost > 0 and turnover > 0:
                cost_alloc = (aligned_new - aligned_old).abs() / turnover * trade_cost
                for ticker, cost in cost_alloc.items():
                    contrib_rows.append({"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": -float(cost)})
            pending_weights = new_weights
        contrib_rows.extend(
            {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": float(pnl)}
            for ticker, pnl in pnl_by_ticker.items()
            if abs(float(pnl)) > 0
        )
        rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_pnl": daily_pnl - trade_cost,
                "trade_cost": trade_cost,
                "borrow_cost": borrow_cost,
                "equity": equity,
                "turnover": turnover,
                "gross_exposure": float(weights.abs().sum()) if not weights.empty else 0.0,
                "net_exposure": float(weights.sum()) if not weights.empty else 0.0,
                "positions": int((weights != 0).sum()) if not weights.empty else 0,
            }
        )
    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    return out, pd.DataFrame(contrib_rows)


def summary_row(spec: dict[str, object], daily: pd.DataFrame, contrib: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "mode": spec["mode"],
        "longN": int(spec["long_n"]),
        "shortN": int(spec["short_n"]),
        "trendGate": bool(spec["trend_gate"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "tradeCost": float(daily["trade_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "avgNetExposure": float(daily["net_exposure"].mean()),
        "avgPositions": float(daily["positions"].mean()),
        "selectedTickers": int(contrib["ticker"].nunique()) if not contrib.empty else 0,
        "days": int(len(daily)),
    }


def yearly_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for (variant, year), group in daily.groupby(["variant", "year"], sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append(
            {
                "variant": variant,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "tradeCost": float(group["trade_cost"].sum()),
                "borrowCost": float(group["borrow_cost"].sum()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    daily = add_low_beta_features(apply_pool(load_daily(), load_pool_membership()))
    frames = []
    contrib_frames = []
    summaries = []
    yearly = []
    concentration = []
    for spec in VARIANTS:
        d, c = simulate(spec, daily)
        frames.append(d)
        contrib_frames.append(c)
        summaries.append(summary_row(spec, d, c))
        yearly.extend(yearly_rows(d))
        concentration.append(concentration_row(str(spec["variant"]), c))
        print("LOW_BETA", summaries[-1], flush=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    qa = pd.DataFrame(
        [
            {
                "rows": int(len(daily)),
                "tickers": int(daily["ticker"].nunique()),
                "days": int(daily["date"].nunique()),
                "medianNamesPerDay": float(daily.groupby("date")["ticker"].nunique().median()),
                "poolTopN": POOL_TOP_N,
                "betaLookback": 60,
                "betaMinPeriods": 40,
            }
        ]
    )
    qa.to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lowbeta_monthly.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "Pre-registered monthly PIT top500 low-beta selection/spread. beta60_pre uses lagged rolling covariance to broad PIT top500 return. Weights apply after rebalance-day close.",
        "costs": f"{TRADE_COST_BPS} bps turnover; {SHORT_BORROW_ANNUAL_RATE:.1%} annual borrow on short gross for long/short rows.",
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "beta60_pre is shifted one day; rebalance-day weights are applied starting the next trading day. PIT top500 via market-cap snapshots. No old manual 62 list.",
        "rule_selection_effect": "None inside diagnostic. Six variants fixed before running.",
        "variants": VARIANTS,
        "outputs": [
            str(SUMMARY_OUT),
            str(YEARLY_OUT),
            str(CONCENTRATION_OUT),
            str(DAILY_OUT),
            str(CONTRIB_OUT),
            str(QA_OUT),
        ],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
