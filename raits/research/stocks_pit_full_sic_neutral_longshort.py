from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_SIC_NEUTRAL_LONGSHORT_2026-09-14"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)

START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
COST_BPS_PER_SIDE = 4.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SPLIT_OUT = Path(f"{OUT_PREFIX}_SPLITS.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
TRADES_OUT = Path(f"{OUT_PREFIX}_TRADES.csv")
REBALANCE_OUT = Path(f"{OUT_PREFIX}_REBALANCES.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered SIC-neutral long/short family.
# Rebalance date features select names; returns start next trading day.
VARIANTS = [
    {"variant": "top500_ret60vol_sicpair1_weekly_gross200", "pool": 500, "signal": "ret60_over_vol20", "pairs_per_bucket": 1, "freq": "weekly", "gross": 2.0, "min_bucket": 6},
    {"variant": "top500_ret60vol_sicpair2_weekly_gross200", "pool": 500, "signal": "ret60_over_vol20", "pairs_per_bucket": 2, "freq": "weekly", "gross": 2.0, "min_bucket": 8},
    {"variant": "top500_ret20_sicpair1_weekly_gross200", "pool": 500, "signal": "ret20_pre", "pairs_per_bucket": 1, "freq": "weekly", "gross": 2.0, "min_bucket": 6},
    {"variant": "top500_ret60vol_sicpair1_monthly_gross200", "pool": 500, "signal": "ret60_over_vol20", "pairs_per_bucket": 1, "freq": "monthly", "gross": 2.0, "min_bucket": 6},
    {"variant": "top500_ret60vol_sicpair2_monthly_gross200", "pool": 500, "signal": "ret60_over_vol20", "pairs_per_bucket": 2, "freq": "monthly", "gross": 2.0, "min_bucket": 8},
    {"variant": "top500_ret60vol_sicpair1_weekly_gross100", "pool": 500, "signal": "ret60_over_vol20", "pairs_per_bucket": 1, "freq": "weekly", "gross": 1.0, "min_bucket": 6},
]


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


def load_daily() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily[(daily["date"] >= START) & (daily["date"] <= END)].copy()
    cols = ["ticker", "date", "close_1555", "ret20_pre", "ret60_pre", "vol20_pre"]
    daily = daily.dropna(subset=cols)
    daily = daily[(daily["close_1555"] > 0) & (daily["vol20_pre"] > 0)].copy()
    daily = daily.sort_values(["ticker", "date"])
    daily["next_close_1555"] = daily.groupby("ticker")["close_1555"].shift(-1)
    daily["next_date"] = daily.groupby("ticker")["date"].shift(-1)
    daily["ret_next"] = daily["next_close_1555"] / daily["close_1555"] - 1.0
    daily["ret60_over_vol20"] = daily["ret60_pre"] / daily["vol20_pre"]
    daily["week"] = daily["date"].dt.to_period("W-FRI")
    daily["month"] = daily["date"].dt.to_period("M")
    return daily.dropna(subset=["ret_next", "next_date"]).copy()


def load_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps["sic_bucket"] = caps["sic_description"].fillna("UNKNOWN").astype(str).str.upper()
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps[["date", "ticker", "market_cap", "rank_market_cap", "sic_bucket"]].copy()


def cap_snapshot_for_dates(caps: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    date_df = pd.DataFrame({"date": sorted(dates.drop_duplicates())})
    snapshot_dates = caps[["date"]].drop_duplicates().sort_values("date").rename(columns={"date": "snapshot_date"})
    return pd.merge_asof(date_df, snapshot_dates, left_on="date", right_on="snapshot_date", direction="backward")


def rebalance_dates(daily: pd.DataFrame, freq: str) -> pd.DataFrame:
    if freq == "weekly":
        return daily.groupby("week", as_index=False)["date"].max().sort_values("date")
    if freq == "monthly":
        return daily.groupby("month", as_index=False)["date"].max().sort_values("date")
    raise ValueError(f"unsupported freq: {freq}")


def prepare_candidates(daily: pd.DataFrame, caps: pd.DataFrame, pool: int, freq: str) -> pd.DataFrame:
    rebs = rebalance_dates(daily, freq)
    assigned = cap_snapshot_for_dates(caps, rebs["date"])
    rebs = rebs.merge(assigned, on="date", how="inner")
    keys = ["date"]
    x = daily.merge(rebs[keys + ["snapshot_date"]], on="date", how="inner")
    x = x.merge(caps, left_on=["snapshot_date", "ticker"], right_on=["date", "ticker"], how="inner", suffixes=("", "_cap"))
    return x[x["rank_market_cap"].le(pool)].copy()


def select_rebalances(candidates: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    rows = []
    signal = str(spec["signal"])
    k = int(spec["pairs_per_bucket"])
    min_bucket = int(spec["min_bucket"])
    for date, day in candidates.dropna(subset=[signal]).groupby("date", sort=True):
        for bucket, group in day.groupby("sic_bucket", sort=False):
            if len(group) < min_bucket:
                continue
            ordered = group.sort_values(signal, ascending=False)
            longs = ordered.head(k).copy()
            shorts = ordered.tail(k).copy()
            if len(longs) < k or len(shorts) < k:
                continue
            longs["side"] = 1
            shorts["side"] = -1
            selected = pd.concat([longs, shorts], ignore_index=True)
            selected["bucket"] = bucket
            selected["rebalance_date"] = date
            rows.append(selected)
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    out["variant"] = str(spec["variant"])
    return out


def holdings_panel(daily: pd.DataFrame, selected: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    rebs = selected[["rebalance_date"]].drop_duplicates().sort_values("rebalance_date")
    next_date = pd.Series(dates["date"].iloc[1:].to_numpy(), index=dates["date"].iloc[:-1]).to_dict()
    rebs["start_date"] = rebs["rebalance_date"].map(next_date)
    assigned = pd.merge_asof(dates, rebs.dropna(subset=["start_date"]), left_on="date", right_on="start_date", direction="backward")
    h = assigned.dropna(subset=["rebalance_date"]).merge(
        selected[["variant", "rebalance_date", "ticker", "side", "bucket"]],
        on="rebalance_date",
        how="inner",
    )
    returns = daily[["date", "ticker", "ret_next", "next_date"]]
    return h.merge(returns, on=["date", "ticker"], how="inner")


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def simulate(panel: pd.DataFrame, spec: dict[str, object]) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    equity = START_CAPITAL
    gross = float(spec["gross"])
    prev_positions: set[tuple[str, int]] = set()
    daily_rows = []
    trade_rows = []
    for date, group in panel.groupby("date", sort=True):
        group = group.copy()
        current = set(zip(group["ticker"].astype(str), group["side"].astype(int)))
        turnover = len(current.symmetric_difference(prev_positions)) / max(len(current), 1)
        cost = gross * turnover * COST_BPS_PER_SIDE / 10_000.0
        long_count = max(int((group["side"] > 0).sum()), 1)
        short_count = max(int((group["side"] < 0).sum()), 1)
        group["weight"] = np.where(group["side"] > 0, (gross / 2.0) / long_count, -(gross / 2.0) / short_count)
        group["pnl_before_costs"] = equity * group["weight"] * group["ret_next"]
        group["cost"] = equity * cost / len(group)
        group["pnl"] = group["pnl_before_costs"] - group["cost"]
        daily_pnl = float(group["pnl"].sum())
        daily_gross_pnl = float(group["pnl_before_costs"].sum())
        equity += daily_pnl
        daily_rows.append(
            {
                "variant": spec["variant"],
                "date": pd.Timestamp(date),
                "daily_pnl": daily_pnl,
                "gross_pnl_before_costs": daily_gross_pnl,
                "cost_drag": daily_pnl - daily_gross_pnl,
                "equity": equity,
                "gross": gross,
                "positions": int(len(group)),
                "longs": int((group["side"] > 0).sum()),
                "shorts": int((group["side"] < 0).sum()),
                "buckets": int(group["bucket"].nunique()),
                "turnover": float(turnover),
            }
        )
        trade_rows.append(group)
        prev_positions = current
    daily = add_periods(pd.DataFrame(daily_rows))
    trades = pd.concat(trade_rows, ignore_index=True)
    dd, dd_pct = max_drawdown(daily["equity"])
    summary = {
        "variant": spec["variant"],
        "pool": int(spec["pool"]),
        "signal": spec["signal"],
        "pairsPerBucket": int(spec["pairs_per_bucket"]),
        "freq": spec["freq"],
        "gross": gross,
        "minBucket": int(spec["min_bucket"]),
        "pnl": float(daily["daily_pnl"].sum()),
        "grossPnlBeforeCosts": float(daily["gross_pnl_before_costs"].sum()),
        "costDrag": float(daily["cost_drag"].sum()),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "selectedTickers": int(trades["ticker"].nunique()),
        "avgPositions": float(daily["positions"].mean()),
        "avgBuckets": float(daily["buckets"].mean()),
        "avgTurnover": float(daily["turnover"].mean()),
    }
    return summary, daily, trades


def period_rows(daily: pd.DataFrame, period_col: str) -> list[dict[str, object]]:
    rows = []
    for (variant, period), group in daily.groupby(["variant", period_col], sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append(
            {
                "variant": variant,
                period_col: period,
                "pnl": float(group["daily_pnl"].sum()),
                "grossPnlBeforeCosts": float(group["gross_pnl_before_costs"].sum()),
                "costDrag": float(group["cost_drag"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "days": int(len(group)),
                "avgTurnover": float(group["turnover"].mean()),
            }
        )
    return rows


def effective_ticker_count(pnl_by_ticker: pd.Series) -> float:
    positive = pnl_by_ticker[pnl_by_ticker > 0]
    weights_source = positive if positive.sum() > 0 else pnl_by_ticker.abs()
    total = float(weights_source.sum())
    if total <= 0:
        return 0.0
    weights = weights_source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, trades: pd.DataFrame) -> dict[str, object]:
    by_ticker = trades.groupby("ticker", sort=False)["pnl"].sum().sort_values(ascending=False)
    total = float(trades["pnl"].sum())
    denom = total if total > 0 else float(by_ticker.abs().sum())
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
        row[f"top{n}Share"] = top / denom if denom else float("nan")
    return row


def main() -> None:
    daily = load_daily()
    caps = load_caps()
    candidate_cache: dict[tuple[int, str], pd.DataFrame] = {}
    summaries = []
    daily_frames = []
    trade_frames = []
    rebalance_frames = []
    concentrations = []
    for spec in VARIANTS:
        key = (int(spec["pool"]), str(spec["freq"]))
        if key not in candidate_cache:
            candidate_cache[key] = prepare_candidates(daily, caps, key[0], key[1])
        selected = select_rebalances(candidate_cache[key], spec)
        panel = holdings_panel(daily, selected)
        summary, daily_out, trades = simulate(panel, spec)
        summaries.append(summary)
        daily_frames.append(daily_out)
        trade_frames.append(trades)
        rebalance_frames.append(selected)
        concentrations.append(concentration_row(str(spec["variant"]), trades))
        print("VARIANT", spec["variant"], summary, flush=True)
    all_daily = pd.concat(daily_frames, ignore_index=True)
    all_trades = pd.concat(trade_frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "split")).to_csv(SPLIT_OUT, index=False)
    pd.DataFrame(concentrations).to_csv(CONCENTRATION_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    all_trades.to_csv(TRADES_OUT, index=False)
    pd.concat(rebalance_frames, ignore_index=True).to_csv(REBALANCE_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_sic_neutral_longshort.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "sample_period": [START.strftime("%Y-%m-%d"), END.strftime("%Y-%m-%d")],
        "universe": "PIT quarterly market-cap top500 stocks bucketed by raw Polygon sic_description.",
        "entry_exit": "Signals at rebalance close; holdings begin next trading day and hold until next rebalance.",
        "leakage_controls": "Selection uses only rebalance-date features and latest prior/equal market-cap snapshot; returns start after selection date.",
        "variants": VARIANTS,
        "costs": f"{COST_BPS_PER_SIDE} bps per side approximated from position turnover.",
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(TRADES_OUT), str(REBALANCE_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, CONCENTRATION_OUT, DAILY_OUT, TRADES_OUT, REBALANCE_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
