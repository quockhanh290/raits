from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_RESIDUAL_REVERSAL_COHORTS_2026-09-17"
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

# Fixed before measuring. A cohort starts at 09:35 on the trading day after
# the residual-return signal and has gross 1 / hold_days.
VARIANTS = [
    {"variant": "market_resid_rev_10x10_hold3", "signal": "market", "hold_days": 3},
    {"variant": "market_resid_rev_10x10_hold5", "signal": "market", "hold_days": 5},
    {"variant": "sic_resid_rev_pair1_hold3", "signal": "sic", "hold_days": 3},
    {"variant": "sic_resid_rev_pair1_hold5", "signal": "sic", "hold_days": 5},
]

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
SIGNALS_OUT = Path(f"{OUT_PREFIX}_SIGNALS.csv")
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


def load_raw() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    intra = pd.read_pickle(INTRADAY_0935)
    intra["date"] = pd.to_datetime(intra["date"]).dt.normalize()
    intra["ticker"] = intra["ticker"].astype(str).str.upper()
    x = daily[["date", "ticker", "prev_dayret", "vol20_pre"]].merge(
        intra[["date", "ticker", "entry935"]], on=["date", "ticker"], how="inner"
    )
    x = x[(x["date"] >= START) & (x["date"] <= END)].copy()
    x = x.dropna(subset=["date", "ticker", "prev_dayret", "vol20_pre", "entry935"])
    x = x[(x["entry935"] > 0) & (x["vol20_pre"] > 0)].copy()
    return x.sort_values(["date", "ticker"]).reset_index(drop=True)


def load_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps["sic_bucket"] = caps["sic_description"].fillna("UNKNOWN").astype(str).str.upper()
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps[caps["rank_market_cap"].le(POOL_TOP_N)][["date", "ticker", "sic_bucket"]].rename(
        columns={"date": "snapshot_date"}
    )


def apply_pool(raw: pd.DataFrame, caps: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(raw["date"].drop_duplicates())})
    snapshots = caps[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    x = raw.merge(assigned, on="date", how="inner")
    return x.merge(caps, on=["snapshot_date", "ticker"], how="inner").drop(columns="snapshot_date")


def add_residuals(pool: pd.DataFrame) -> pd.DataFrame:
    x = pool.copy()
    x["market_median_ret"] = x.groupby("date")["prev_dayret"].transform("median")
    x["market_resid"] = x["prev_dayret"] - x["market_median_ret"]
    bucket_count = x.groupby(["date", "sic_bucket"])["ticker"].transform("size")
    x["sic_median_ret"] = x.groupby(["date", "sic_bucket"])["prev_dayret"].transform("median")
    x["sic_resid"] = x["prev_dayret"] - x["sic_median_ret"]
    x["sic_bucket_count"] = bucket_count
    dates = sorted(x["date"].drop_duplicates())
    next_date = pd.Series(dates[1:], index=dates[:-1]).to_dict()
    x["entry_date"] = x["date"].map(next_date)
    return x.dropna(subset=["entry_date"]).copy()


def select_signals(panel: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    rows = []
    if spec["signal"] == "market":
        for date, group in panel.groupby("date", sort=True):
            ordered = group.sort_values(["market_resid", "ticker"])
            longs = ordered.head(10).copy()
            shorts = ordered.tail(10).copy()
            longs["side"] = 1
            shorts["side"] = -1
            rows.extend([longs, shorts])
    else:
        eligible = panel[panel["sic_bucket_count"] >= 8]
        for (_, _), group in eligible.groupby(["date", "sic_bucket"], sort=True):
            ordered = group.sort_values(["sic_resid", "ticker"])
            long = ordered.head(1).copy()
            short = ordered.tail(1).copy()
            long["side"] = 1
            short["side"] = -1
            rows.extend([long, short])
    out = pd.concat(rows, ignore_index=True)
    out["variant"] = spec["variant"]
    out["signal_name"] = spec["signal"]
    out["signal_value"] = np.where(out["signal_name"].eq("market"), out["market_resid"], out["sic_resid"])
    return out


def cohort_weights(signals: pd.DataFrame, hold_days: int, gross_scale: float = 1.0) -> pd.Series:
    if signals.empty:
        return pd.Series(dtype=float)
    cohort_gross = gross_scale / hold_days
    weights: dict[str, float] = {}
    for side in (1, -1):
        names = signals[signals["side"].eq(side)]["ticker"].tolist()
        if not names:
            continue
        weight = side * cohort_gross / 2.0 / len(names)
        for ticker in names:
            weights[ticker] = weights.get(ticker, 0.0) + weight
    return pd.Series(weights, dtype=float)


def aggregate_cohorts(cohorts: list[tuple[int, pd.Series]]) -> pd.Series:
    if not cohorts:
        return pd.Series(dtype=float)
    out = pd.concat([weights.rename(i) for i, (_, weights) in enumerate(cohorts)], axis=1).fillna(0).sum(axis=1)
    return out[out.ne(0)].copy()


def simulate(
    raw: pd.DataFrame, signals: pd.DataFrame, spec: dict[str, object], gross_scale: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = sorted(raw["date"].drop_duplicates())
    prices_by_date = {date: group.set_index("ticker")["entry935"] for date, group in raw.groupby("date", sort=True)}
    signals_by_entry = {date: group for date, group in signals.groupby("entry_date", sort=True)}
    hold_days = int(spec["hold_days"])
    equity = START_CAPITAL
    previous_prices = pd.Series(dtype=float)
    weights = pd.Series(dtype=float)
    cohorts: list[tuple[int, pd.Series]] = []
    daily_rows = []
    contrib_rows = []

    for day_index, date in enumerate(dates):
        prices = prices_by_date[date]
        common = weights.index.intersection(prices.index).intersection(previous_prices.index)
        returns = prices.reindex(common) / previous_prices.reindex(common) - 1.0
        pnl_by_ticker = equity * weights.reindex(common) * returns if len(common) else pd.Series(dtype=float)
        short_gross = float(weights[weights < 0].abs().sum()) if not weights.empty else 0.0
        borrow_cost = equity * short_gross * SHORT_BORROW_ANNUAL_RATE / 252.0
        if borrow_cost > 0 and short_gross > 0:
            allocation = weights[weights < 0].abs() / short_gross * borrow_cost
            for ticker, cost in allocation.items():
                pnl_by_ticker.loc[ticker] = pnl_by_ticker.get(ticker, 0.0) - cost
        daily_pnl = float(pnl_by_ticker.sum()) if not pnl_by_ticker.empty else 0.0
        equity += daily_pnl

        cohorts = [(start, cohort) for start, cohort in cohorts if day_index - start < hold_days]
        new_signals = signals_by_entry.get(date, signals.iloc[0:0])
        new_cohort = cohort_weights(new_signals, hold_days, gross_scale)
        if not new_cohort.empty:
            cohorts.append((day_index, new_cohort))
        new_weights = aggregate_cohorts(cohorts)

        tickers = weights.index.union(new_weights.index)
        old_aligned = weights.reindex(tickers).fillna(0.0)
        new_aligned = new_weights.reindex(tickers).fillna(0.0)
        turnover = float((new_aligned - old_aligned).abs().sum())
        trade_cost = equity * turnover * TRADE_COST_BPS / 10_000.0
        equity -= trade_cost
        if turnover > 0:
            allocation = (new_aligned - old_aligned).abs() / turnover * trade_cost
            contrib_rows.extend(
                {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": -float(cost)}
                for ticker, cost in allocation.items()
            )
        contrib_rows.extend(
            {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": float(pnl)}
            for ticker, pnl in pnl_by_ticker.items()
            if float(pnl) != 0.0
        )
        weights = new_weights
        daily_rows.append(
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
                "positions": int(weights.ne(0).sum()),
                "new_signals": int(len(new_signals)),
                "missing_positions": int(len(weights.index.difference(prices.index))),
            }
        )
        previous_prices = prices
    daily = pd.DataFrame(daily_rows)
    daily["year"] = daily["date"].dt.year
    return daily, pd.DataFrame(contrib_rows)


def effective_ticker_count(by_ticker: pd.Series) -> float:
    positive = by_ticker[by_ticker > 0]
    source = positive if positive.sum() > 0 else by_ticker.abs()
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
        "topTicker": str(by_ticker.index[0]),
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum())
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denominator if denominator else float("nan")
    return row


def summary_row(spec: dict[str, object], daily: pd.DataFrame, signals: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    pnl = float(daily["equity"].iloc[-1] - START_CAPITAL)
    trade_cost = float(daily["trade_cost"].sum())
    borrow_cost = float(daily["borrow_cost"].sum())
    return {
        "variant": spec["variant"],
        "signal": spec["signal"],
        "holdDays": int(spec["hold_days"]),
        "pnl": pnl,
        "grossPnlBeforeCostsBorrow": pnl + trade_cost + borrow_cost,
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "tradeCost": trade_cost,
        "borrowCost": borrow_cost,
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "signals": int(len(signals)),
        "selectedTickers": int(signals["ticker"].nunique()),
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
    raw = load_raw()
    panel = add_residuals(apply_pool(raw, load_caps()))
    summaries = []
    yearly = []
    concentration = []
    daily_frames = []
    contrib_frames = []
    signal_frames = []
    qa_rows = []
    for spec in VARIANTS:
        signals = select_signals(panel, spec)
        daily, contrib = simulate(raw, signals, spec)
        summaries.append(summary_row(spec, daily, signals))
        yearly.extend(yearly_rows(daily))
        concentration.append(concentration_row(str(spec["variant"]), contrib))
        daily_frames.append(daily)
        contrib_frames.append(contrib)
        signal_frames.append(signals)
        qa_rows.append(
            {
                "variant": spec["variant"],
                "days": int(len(daily)),
                "signalDays": int(signals["date"].nunique()),
                "maxMissingPositions": int(daily["missing_positions"].max()),
                "meanNetExposure": float(daily["net_exposure"].mean()),
            }
        )
        print("RESIDUAL_REVERSAL", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.concat(signal_frames, ignore_index=True).to_csv(SIGNALS_OUT, index=False)
    pd.DataFrame(qa_rows).to_csv(QA_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_residual_reversal_cohorts.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(INTRADAY_0935).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "PIT top500 prior-day idiosyncratic residual reversal; signal after close, enter next trading day at 09:35, overlapping market- or SIC-neutral cohorts.",
        "signal_rules": {
            "market": "prev_dayret minus PIT top500 cross-sectional median; long bottom10 and short top10",
            "sic": "prev_dayret minus same-date SIC median; one loser/winner pair per bucket with at least eight members",
        },
        "costs": f"{TRADE_COST_BPS} bps aggregate target-weight turnover and {SHORT_BORROW_ANNUAL_RATE:.1%} annual borrow on short gross.",
        "sample_label": "Research/touched 2018-2024 only. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "leakage_controls": "Signal uses completed prior session return; execution starts next session at 09:35; PIT market-cap/SIC membership uses backward snapshots; held names marked from broad PIT prices; no old manual 62 list.",
        "rule_selection_effect": "None. Residual definitions, tails/pairs, entry time, hold3/hold5 family, gross and costs were fixed before measuring.",
        "trade_selection_effect": "Daily candidate sets and full overlapping cohorts are rebuilt from PIT inputs; no ticker-PnL subtraction or post-period ticker selection.",
        "variants": VARIANTS,
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(CONTRIB_OUT), str(SIGNALS_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, SIGNALS_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
