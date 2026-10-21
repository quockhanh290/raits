from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_WFO_0935_WEEKLY_RANKER_2026-09-17"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
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
RIDGE_ALPHA = 25.0

RAW_FEATURES = [
    "gap",
    "first5_ret",
    "log_rvol930",
    "ret20_pre",
    "ret60_pre",
    "vol20_pre",
    "gap_x_first5",
    "open_to_0935",
    "abs_gap",
]
FEATURES = [f"xs_{name}" for name in RAW_FEATURES]

# Pre-registered before measuring. All variants use the same yearly WFO scores.
VARIANTS = [
    {"variant": "wfo0935_top50_long_gross100", "mode": "long", "long_n": 50, "short_n": 0, "gross": 1.0},
    {"variant": "wfo0935_top100_long_gross100", "mode": "long", "long_n": 100, "short_n": 0, "gross": 1.0},
    {"variant": "wfo0935_ls50_50_gross100", "mode": "long_short", "long_n": 50, "short_n": 50, "gross": 1.0},
    {"variant": "wfo0935_ls100_100_gross100", "mode": "long_short", "long_n": 100, "short_n": 100, "gross": 1.0},
]

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
MODEL_OUT = Path(f"{OUT_PREFIX}_MODEL_COEFS.csv")
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


def load_panel() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily_cols = ["date", "ticker", "gap", "ret20_pre", "ret60_pre", "vol20_pre"]

    intra = pd.read_pickle(INTRADAY_0935)
    intra["date"] = pd.to_datetime(intra["date"]).dt.normalize()
    intra["ticker"] = intra["ticker"].astype(str).str.upper()
    intra_cols = ["date", "ticker", "entry935", "first5_ret", "rvol930"]

    x = daily[daily_cols].merge(intra[intra_cols], on=["date", "ticker"], how="inner")
    x = x[(x["date"] >= START) & (x["date"] <= END)].copy()
    x = x.dropna(subset=[*daily_cols, "entry935", "first5_ret", "rvol930"])
    x = x[(x["entry935"] > 0) & (x["vol20_pre"] > 0) & (x["rvol930"] >= 0)].copy()
    x["log_rvol930"] = np.log1p(x["rvol930"].clip(lower=0, upper=100))
    x["gap_x_first5"] = x["gap"] * x["first5_ret"]
    x["open_to_0935"] = (1.0 + x["gap"]) * (1.0 + x["first5_ret"]) - 1.0
    x["abs_gap"] = x["gap"].abs()
    return x.sort_values(["date", "ticker"]).reset_index(drop=True)


def load_pool_membership() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    selected = caps[caps["rank_market_cap"].le(POOL_TOP_N)].copy()
    return selected[["date", "ticker"]].rename(columns={"date": "snapshot_date"})


def apply_pool(panel: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(panel["date"].drop_duplicates())})
    snapshots = membership[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    x = panel.merge(assigned, on="date", how="inner")
    x = x.merge(membership, on=["snapshot_date", "ticker"], how="inner")
    return x.drop(columns="snapshot_date").copy()


def add_xs_features(panel: pd.DataFrame) -> pd.DataFrame:
    x = panel.copy()
    for feature in RAW_FEATURES:
        lo = x.groupby("date")[feature].transform(lambda s: s.quantile(0.01))
        hi = x.groupby("date")[feature].transform(lambda s: s.quantile(0.99))
        clipped = x[feature].clip(lower=lo, upper=hi)
        mean = clipped.groupby(x["date"]).transform("mean")
        std = clipped.groupby(x["date"]).transform("std").replace(0, np.nan)
        x[f"xs_{feature}"] = (clipped - mean) / std
    return x.dropna(subset=FEATURES).copy()


def weekly_rows(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    calendar = pd.DataFrame({"date": sorted(panel["date"].drop_duplicates())})
    calendar["week"] = calendar["date"].dt.to_period("W-FRI")
    rebalance_dates = calendar.groupby("week", sort=True)["date"].min().tolist()
    weekly = panel[panel["date"].isin(rebalance_dates)].copy()

    date_map = pd.DataFrame({"date": rebalance_dates})
    date_map["label_end_date"] = date_map["date"].shift(-1)
    weekly = weekly.merge(date_map, on="date", how="left")
    end_prices = weekly[["date", "ticker", "entry935"]].rename(
        columns={"date": "label_end_date", "entry935": "label_end_entry935"}
    )
    weekly = weekly.merge(end_prices, on=["label_end_date", "ticker"], how="left")
    weekly["target_next_week"] = weekly["label_end_entry935"] / weekly["entry935"] - 1.0
    return weekly, rebalance_dates


def fit_ridge(train: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    clean = train.dropna(subset=[*FEATURES, "target_next_week"]).copy()
    x = clean[FEATURES].to_numpy(dtype=float)
    y = clean["target_next_week"].to_numpy(dtype=float)
    mu = x.mean(axis=0)
    sigma = x.std(axis=0)
    sigma[sigma == 0] = 1.0
    z = (x - mu) / sigma
    design = np.column_stack([np.ones(len(z)), z])
    penalty = np.eye(design.shape[1]) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    coef = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return coef, mu, sigma


def model_by_year(weekly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    scored_frames = []
    coef_rows = []
    qa_rows = []
    for year in range(2019, 2025):
        cutoff = pd.Timestamp(year=year, month=1, day=1)
        train = weekly[(weekly["date"] < cutoff) & (weekly["label_end_date"] < cutoff)].copy()
        test = weekly[weekly["date"].dt.year.eq(year)].copy()
        train_clean = train.dropna(subset=[*FEATURES, "target_next_week"])
        if train_clean.empty or test.empty:
            continue
        coef, mu, sigma = fit_ridge(train_clean)
        design = np.column_stack([np.ones(len(test)), (test[FEATURES].to_numpy(dtype=float) - mu) / sigma])
        test["pred_next_week"] = design @ coef
        scored_frames.append(test)

        coef_rows.append({"testYear": year, "feature": "intercept", "coef": float(coef[0]), "mean": np.nan, "std": np.nan})
        for i, feature in enumerate(FEATURES, start=1):
            coef_rows.append(
                {"testYear": year, "feature": feature, "coef": float(coef[i]), "mean": float(mu[i - 1]), "std": float(sigma[i - 1])}
            )

        valid = test.dropna(subset=["target_next_week"])
        daily_ic = valid.groupby("date").apply(
            lambda g: g["pred_next_week"].corr(g["target_next_week"], method="spearman"),
            include_groups=False,
        )
        qa_rows.append(
            {
                "testYear": year,
                "trainRows": int(len(train_clean)),
                "testRows": int(len(test)),
                "testWeeks": int(test["date"].nunique()),
                "meanWeeklyRankIC": float(daily_ic.mean()),
                "positiveICShare": float((daily_ic > 0).mean()),
            }
        )
    return pd.concat(scored_frames, ignore_index=True), pd.DataFrame(coef_rows), pd.DataFrame(qa_rows)


def target_weights(group: pd.DataFrame, spec: dict[str, object]) -> pd.Series:
    ranked = group.sort_values(["pred_next_week", "ticker"], ascending=[False, True])
    weights: dict[str, float] = {}
    if spec["mode"] == "long":
        names = ranked.head(int(spec["long_n"]))["ticker"].tolist()
        if names:
            weight = float(spec["gross"]) / len(names)
            weights.update({ticker: weight for ticker in names})
    else:
        longs = ranked.head(int(spec["long_n"]))["ticker"].tolist()
        shorts = ranked.tail(int(spec["short_n"]))["ticker"].tolist()
        if longs:
            weight = float(spec["gross"]) / 2.0 / len(longs)
            weights.update({ticker: weight for ticker in longs})
        if shorts:
            weight = -float(spec["gross"]) / 2.0 / len(shorts)
            for ticker in shorts:
                weights[ticker] = weights.get(ticker, 0.0) + weight
    return pd.Series(weights, dtype=float)


def simulate(
    spec: dict[str, object], panel: pd.DataFrame, scored: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    price_by_date = {date: group.set_index("ticker")["entry935"] for date, group in panel.groupby("date", sort=True)}
    scores_by_date = {date: group for date, group in scored.groupby("date", sort=True)}
    equity = START_CAPITAL
    weights = pd.Series(dtype=float)
    previous_prices = pd.Series(dtype=float)
    rows = []
    contrib_rows = []
    for date in sorted(price_by_date):
        prices = price_by_date[date]
        common = weights.index.intersection(prices.index).intersection(previous_prices.index)
        returns = prices.reindex(common) / previous_prices.reindex(common) - 1.0
        pnl_by_ticker = equity * weights.reindex(common) * returns if len(common) else pd.Series(dtype=float)
        missing_positions = int(len(weights.index.difference(common)))
        short_gross = float(weights[weights < 0].abs().sum()) if not weights.empty else 0.0
        borrow_cost = equity * short_gross * SHORT_BORROW_ANNUAL_RATE / 252.0
        if borrow_cost > 0 and short_gross > 0:
            allocation = weights[weights < 0].abs() / short_gross * borrow_cost
            for ticker, cost in allocation.items():
                pnl_by_ticker.loc[ticker] = pnl_by_ticker.get(ticker, 0.0) - cost
        daily_pnl = float(pnl_by_ticker.sum()) if not pnl_by_ticker.empty else 0.0
        equity += daily_pnl

        turnover = 0.0
        trade_cost = 0.0
        if date in scores_by_date:
            new_weights = target_weights(scores_by_date[date], spec)
            tickers = weights.index.union(new_weights.index)
            old_aligned = weights.reindex(tickers).fillna(0.0)
            new_aligned = new_weights.reindex(tickers).fillna(0.0)
            turnover = float((new_aligned - old_aligned).abs().sum())
            trade_cost = equity * turnover * TRADE_COST_BPS / 10_000.0
            equity -= trade_cost
            if turnover > 0:
                cost_alloc = (new_aligned - old_aligned).abs() / turnover * trade_cost
                contrib_rows.extend(
                    {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": -float(cost)}
                    for ticker, cost in cost_alloc.items()
                )
            weights = new_weights

        contrib_rows.extend(
            {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": float(pnl)}
            for ticker, pnl in pnl_by_ticker.items()
            if float(pnl) != 0.0
        )
        rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_pnl": daily_pnl - trade_cost,
                "equity": equity,
                "trade_cost": trade_cost,
                "borrow_cost": borrow_cost,
                "turnover": turnover,
                "gross_exposure": float(weights.abs().sum()) if not weights.empty else 0.0,
                "net_exposure": float(weights.sum()) if not weights.empty else 0.0,
                "positions": int((weights != 0).sum()),
                "missing_positions": missing_positions,
            }
        )
        previous_prices = prices
    daily = pd.DataFrame(rows)
    daily = daily[daily["date"] >= scored["date"].min()].copy()
    daily["year"] = daily["date"].dt.year
    return daily, pd.DataFrame(contrib_rows)


def effective_ticker_count(pnl_by_ticker: pd.Series) -> float:
    positive = pnl_by_ticker[pnl_by_ticker > 0]
    source = positive if positive.sum() > 0 else pnl_by_ticker.abs()
    total = float(source.sum())
    if total <= 0:
        return 0.0
    weights = source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(by_ticker.sum())
    denominator = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        "topTickerPnl": float(by_ticker.iloc[0]) if not by_ticker.empty else 0.0,
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum())
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denominator if denominator else float("nan")
    return row


def summary_row(spec: dict[str, object], daily: pd.DataFrame, contrib: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "mode": spec["mode"],
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "tradeCost": float(daily["trade_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "avgPositions": float(daily["positions"].mean()),
        "selectedTickers": int(contrib["ticker"].nunique()),
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
            }
        )
    return rows


def main() -> None:
    raw = load_panel()
    panel = add_xs_features(apply_pool(raw, load_pool_membership()))
    weekly, rebalance_dates = weekly_rows(panel)
    scored, coefs, qa = model_by_year(weekly)

    summaries = []
    yearly = []
    concentration = []
    daily_frames = []
    contrib_frames = []
    for spec in VARIANTS:
        # Mark held names from the broad PIT price panel even if a quarterly
        # snapshot change removes them from the top500 selection pool.
        daily, contrib = simulate(spec, raw, scored)
        summaries.append(summary_row(spec, daily, contrib))
        yearly.extend(yearly_rows(daily))
        concentration.append(concentration_row(str(spec["variant"]), contrib))
        daily_frames.append(daily)
        contrib_frames.append(contrib)
        print("WFO_0935", summaries[-1], flush=True)

    qa["panelRows"] = len(panel)
    qa["panelTickers"] = panel["ticker"].nunique()
    qa["rebalanceDates"] = len(rebalance_dates)
    qa["maxMissingPositionsPerDay"] = max(int(frame["missing_positions"].max()) for frame in daily_frames)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    coefs.to_csv(MODEL_OUT, index=False)
    qa.to_csv(QA_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_wfo_0935_weekly_ranker.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(INTRADAY_0935).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "PIT top500 weekly 09:35 cross-sectional ridge ranker; yearly expanding walk-forward training and next-week 09:35 holding returns.",
        "features": FEATURES,
        "target": "Next global rebalance-date 09:35 price return. Training rows require label_end_date strictly before the test-year cutoff.",
        "costs": f"{TRADE_COST_BPS} bps target-weight turnover and {SHORT_BORROW_ANNUAL_RATE:.1%} annual borrow on short gross.",
        "sample_label": "Research/touched 2018-2024 only; 2019-2024 are walk-forward years. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "leakage_controls": "09:35-known features only; yearly expanding WFO with purged boundary labels; PIT market-cap membership via backward snapshot assignment; no old manual 62 list.",
        "rule_selection_effect": "None inside this diagnostic. Features, interactions, ridge alpha, weekly schedule, target and four variants were fixed before measuring.",
        "trade_selection_effect": "All weekly membership and ranks are rebuilt from PIT inputs and each year's frozen model; no ticker-PnL subtraction.",
        "variants": VARIANTS,
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(CONTRIB_OUT), str(MODEL_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, MODEL_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
