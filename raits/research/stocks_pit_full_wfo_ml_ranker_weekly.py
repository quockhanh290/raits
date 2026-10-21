from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_WFO_ML_RANKER_WEEKLY_2026-09-15"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)
START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
POOL_TOP_N = 500
HORIZON_DAYS = 5
TRADE_COST_BPS = 4.0
SHORT_BORROW_ANNUAL_RATE = 0.01
RIDGE_ALPHA = 25.0

FEATURES = [
    "prev_dayret",
    "gap",
    "ret_open_to_1555",
    "ret20_pre",
    "ret60_pre",
    "vol20_pre",
    "spy_prev_dayret",
]

VARIANTS = [
    {"variant": "wfo_ridge_top20_long_gross100", "mode": "long", "long_n": 20, "short_n": 0, "gross": 1.0},
    {"variant": "wfo_ridge_top50_long_gross100", "mode": "long", "long_n": 50, "short_n": 0, "gross": 1.0},
    {"variant": "wfo_ridge_top100_long_gross100", "mode": "long", "long_n": 100, "short_n": 0, "gross": 1.0},
    {"variant": "wfo_ridge_ls50_50_gross100", "mode": "long_short", "long_n": 50, "short_n": 50, "gross": 1.0},
    {"variant": "wfo_ridge_ls100_100_gross100", "mode": "long_short", "long_n": 100, "short_n": 100, "gross": 1.0},
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


def load_daily() -> pd.DataFrame:
    x = pd.read_pickle(DAILY_FEATURES)
    x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    x["ticker"] = x["ticker"].astype(str).str.upper()
    cols = ["date", "ticker", "prev_close_1555", "close_1555", *FEATURES]
    x = x[(x["date"] >= START) & (x["date"] <= END)][cols].copy()
    x = x.dropna(subset=cols)
    x = x[(x["prev_close_1555"] > 0) & (x["close_1555"] > 0) & (x["vol20_pre"] > 0)].copy()
    x["ret_close_to_close"] = x["close_1555"] / x["prev_close_1555"] - 1.0
    x = x.sort_values(["ticker", "date"]).copy()
    forward = 1.0
    for i in range(1, HORIZON_DAYS + 1):
        forward = forward * (1.0 + x.groupby("ticker")["ret_close_to_close"].shift(-i))
    x["target_fwd5"] = forward - 1.0
    return x[["date", "ticker", "ret_close_to_close", "target_fwd5", *FEATURES]].copy()


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


def fit_ridge(train: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    clean = train.dropna(subset=[*FEATURES, "target_fwd5"]).copy()
    x = clean[FEATURES].to_numpy(dtype=float)
    y = clean["target_fwd5"].to_numpy(dtype=float)
    mu = x.mean(axis=0)
    sigma = x.std(axis=0)
    sigma[sigma == 0] = 1.0
    z = (x - mu) / sigma
    design = np.column_stack([np.ones(len(z)), z])
    penalty = np.eye(design.shape[1]) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    coef = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return coef, mu, sigma


def score_frame(frame: pd.DataFrame, coef: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> pd.DataFrame:
    x = frame[FEATURES].to_numpy(dtype=float)
    z = (x - mu) / sigma
    design = np.column_stack([np.ones(len(z)), z])
    out = frame.copy()
    out["pred_fwd5"] = design @ coef
    return out


def model_by_year(daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    scored = []
    coefs = []
    for year in range(2019, 2025):
        train = daily[daily["date"].dt.year < year]
        test = daily[daily["date"].dt.year == year]
        if train.empty or test.empty:
            continue
        coef, mu, sigma = fit_ridge(train)
        scored.append(score_frame(test, coef, mu, sigma))
        coefs.append({"testYear": year, "feature": "intercept", "coef": float(coef[0]), "mean": np.nan, "std": np.nan})
        for i, feature in enumerate(FEATURES, start=1):
            coefs.append({"testYear": year, "feature": feature, "coef": float(coef[i]), "mean": float(mu[i - 1]), "std": float(sigma[i - 1])})
    return pd.concat(scored, ignore_index=True), pd.DataFrame(coefs)


def rebalance_dates(scored: pd.DataFrame) -> set[pd.Timestamp]:
    dates = pd.DataFrame({"date": sorted(scored["date"].drop_duplicates())})
    return set(dates.groupby(dates["date"].dt.to_period("W-MON"))["date"].min().tolist())


def target_weights(group: pd.DataFrame, spec: dict[str, object]) -> pd.Series:
    ranked = group.sort_values(["pred_fwd5", "ticker"], ascending=[False, True])
    weights: dict[str, float] = {}
    if spec["mode"] == "long":
        names = ranked.head(int(spec["long_n"]))["ticker"].tolist()
        if names:
            w = float(spec["gross"]) / len(names)
            weights.update({ticker: w for ticker in names})
    elif spec["mode"] == "long_short":
        long_names = ranked.head(int(spec["long_n"]))["ticker"].tolist()
        short_names = ranked.tail(int(spec["short_n"]))["ticker"].tolist()
        if long_names:
            w = float(spec["gross"]) / 2.0 / len(long_names)
            weights.update({ticker: w for ticker in long_names})
        if short_names:
            w = -float(spec["gross"]) / 2.0 / len(short_names)
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


def simulate(spec: dict[str, object], scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_date = {date: group.set_index("ticker") for date, group in scored.groupby("date", sort=True)}
    rdates = rebalance_dates(scored)
    equity = START_CAPITAL
    weights = pd.Series(dtype=float)
    rows = []
    contrib_rows = []
    cost_rate = TRADE_COST_BPS / 10_000.0
    borrow_daily = SHORT_BORROW_ANNUAL_RATE / 252.0
    for date in sorted(by_date):
        group = by_date[date]
        rets = group["ret_close_to_close"].reindex(weights.index).fillna(0.0)
        gross_ret = float((weights * rets).sum()) if not weights.empty else 0.0
        short_gross = float(weights[weights < 0].abs().sum()) if not weights.empty else 0.0
        borrow_drag = short_gross * borrow_daily
        pnl_by_ticker = equity * weights * rets if not weights.empty else pd.Series(dtype=float)
        borrow_cost = equity * borrow_drag
        if borrow_cost > 0 and short_gross > 0:
            short_alloc = weights[weights < 0].abs() / short_gross * borrow_cost
            pnl_by_ticker.loc[short_alloc.index] = pnl_by_ticker.loc[short_alloc.index] - short_alloc
        daily_ret_before_rebalance = gross_ret - borrow_drag
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
            weights = new_weights

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
                "daily_ret": (daily_pnl - trade_cost) / (equity - daily_pnl + trade_cost) if (equity - daily_pnl + trade_cost) > 0 else np.nan,
                "gross_ret_before_cost": gross_ret,
                "borrow_cost": borrow_cost,
                "trade_cost": trade_cost,
                "equity": equity,
                "turnover": turnover,
                "gross_exposure": float(weights.abs().sum()) if not weights.empty else 0.0,
                "net_exposure": float(weights.sum()) if not weights.empty else 0.0,
                "short_gross": short_gross,
                "positions": int((weights != 0).sum()) if not weights.empty else 0,
                "daily_ret_before_rebalance": daily_ret_before_rebalance,
            }
        )
    daily = pd.DataFrame(rows)
    daily["year"] = daily["date"].dt.year
    return daily, pd.DataFrame(contrib_rows)


def summary_row(spec: dict[str, object], daily: pd.DataFrame, contrib: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "mode": spec["mode"],
        "longN": int(spec["long_n"]),
        "shortN": int(spec["short_n"]),
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
                "tradeCost": float(group["trade_cost"].sum()),
                "borrowCost": float(group["borrow_cost"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    raw = load_daily()
    daily = apply_pool(raw, load_pool_membership())
    scored, coefs = model_by_year(daily)
    frames = []
    contrib_frames = []
    summaries = []
    yearly = []
    concentration = []
    for spec in VARIANTS:
        d, c = simulate(spec, scored)
        frames.append(d)
        contrib_frames.append(c)
        summaries.append(summary_row(spec, d, c))
        yearly.extend(yearly_rows(d))
        concentration.append(concentration_row(str(spec["variant"]), c))
        print("WFO_ML", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    coefs.to_csv(MODEL_OUT, index=False)
    qa = pd.DataFrame(
        [
            {
                "trainStart": raw["date"].min().strftime("%Y-%m-%d"),
                "scoredStart": scored["date"].min().strftime("%Y-%m-%d"),
                "scoredEnd": scored["date"].max().strftime("%Y-%m-%d"),
                "rows": int(len(scored)),
                "tickers": int(scored["ticker"].nunique()),
                "days": int(scored["date"].nunique()),
                "poolTopN": POOL_TOP_N,
                "horizonDays": HORIZON_DAYS,
                "ridgeAlpha": RIDGE_ALPHA,
            }
        ]
    )
    qa.to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_wfo_ml_ranker_weekly.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "Expanding yearly walk-forward ridge ranker predicts next 5 trading-day close-to-close return from lagged/PIT features, then weekly rebalances top/bottom ranked PIT top500 names.",
        "features": FEATURES,
        "target": "target_fwd5 uses returns strictly after the feature date; simulated positions enter after the rebalance-day close.",
        "costs": f"{TRADE_COST_BPS} bps target-weight turnover; {SHORT_BORROW_ANNUAL_RATE:.1%} annual borrow on short gross for long/short rows.",
        "sample_label": "Research/touched 2018-2024 only; 2019-2024 are walk-forward years. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "leakage_controls": "Each test year model trains only on rows dated before that year. PIT market-cap top500 membership via backward merge. No old manual 62 list.",
        "rule_selection_effect": "None inside diagnostic. Feature set, ridge alpha, rebalance frequency, and variants fixed before running.",
        "variants": VARIANTS,
        "outputs": [
            str(SUMMARY_OUT),
            str(YEARLY_OUT),
            str(CONCENTRATION_OUT),
            str(DAILY_OUT),
            str(CONTRIB_OUT),
            str(MODEL_OUT),
            str(QA_OUT),
        ],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, MODEL_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
