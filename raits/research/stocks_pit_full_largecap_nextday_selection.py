from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_LARGECAP_NEXTDAY_SELECTION_2026-09-14"
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
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered large-cap next-day stock-selection family.
# Signals are measured on date t; holdings earn t close to t+1 close.
VARIANTS = [
    {"variant": "top500_ret20_top20_gross100", "pool": 500, "selector": "high", "signal": "ret20_pre", "top_n": 20, "gross": 1.0, "filter": "none"},
    {"variant": "top500_ret20_top50_gross100", "pool": 500, "selector": "high", "signal": "ret20_pre", "top_n": 50, "gross": 1.0, "filter": "none"},
    {"variant": "top200_ret20_top20_gross100", "pool": 200, "selector": "high", "signal": "ret20_pre", "top_n": 20, "gross": 1.0, "filter": "none"},
    {"variant": "top500_ret60vol_top20_gross100", "pool": 500, "selector": "high", "signal": "ret60_over_vol20", "top_n": 20, "gross": 1.0, "filter": "none"},
    {"variant": "top500_prevday_bottom20_gross100", "pool": 500, "selector": "low", "signal": "prev_dayret", "top_n": 20, "gross": 1.0, "filter": "ret60_positive"},
    {"variant": "top500_prevday_bottom50_gross100", "pool": 500, "selector": "low", "signal": "prev_dayret", "top_n": 50, "gross": 1.0, "filter": "ret60_positive"},
    {"variant": "top500_gap_bottom20_gross100", "pool": 500, "selector": "low", "signal": "gap", "top_n": 20, "gross": 1.0, "filter": "ret60_positive"},
    {"variant": "top500_ret20_top20_gross150", "pool": 500, "selector": "high", "signal": "ret20_pre", "top_n": 20, "gross": 1.5, "filter": "none"},
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
    cols = ["ticker", "date", "close_1555", "ret20_pre", "ret60_pre", "vol20_pre", "prev_dayret", "gap"]
    daily = daily.dropna(subset=cols)
    daily = daily[(daily["close_1555"] > 0) & (daily["vol20_pre"] > 0)].copy()
    daily = daily.sort_values(["ticker", "date"])
    daily["next_close_1555"] = daily.groupby("ticker")["close_1555"].shift(-1)
    daily["next_date"] = daily.groupby("ticker")["date"].shift(-1)
    daily["next_ret_close_to_close"] = daily["next_close_1555"] / daily["close_1555"] - 1.0
    daily["ret60_over_vol20"] = daily["ret60_pre"] / daily["vol20_pre"]
    return daily.dropna(subset=["next_ret_close_to_close", "next_date"]).copy()


def load_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps[["date", "ticker", "market_cap", "rank_market_cap"]].copy()


def cap_snapshot_for_dates(caps: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    date_df = pd.DataFrame({"date": sorted(dates.drop_duplicates())})
    snapshot_dates = caps[["date"]].drop_duplicates().sort_values("date").rename(columns={"date": "snapshot_date"})
    return pd.merge_asof(date_df, snapshot_dates, left_on="date", right_on="snapshot_date", direction="backward")


def prepare_candidates(daily: pd.DataFrame, caps: pd.DataFrame, pool: int) -> pd.DataFrame:
    assigned = cap_snapshot_for_dates(caps, daily["date"])
    x = daily.merge(assigned, on="date", how="inner")
    x = x.merge(caps, left_on=["snapshot_date", "ticker"], right_on=["date", "ticker"], how="inner", suffixes=("", "_cap"))
    x = x[x["rank_market_cap"].le(pool)].copy()
    return x


def apply_filter(candidates: pd.DataFrame, filter_name: str) -> pd.DataFrame:
    if filter_name == "none":
        return candidates
    if filter_name == "ret60_positive":
        return candidates[candidates["ret60_pre"] > 0].copy()
    raise ValueError(f"unsupported filter: {filter_name}")


def select_trades(candidates: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    x = apply_filter(candidates, str(spec["filter"]))
    ascending = str(spec["selector"]) == "low"
    x = x.dropna(subset=[str(spec["signal"]), "next_ret_close_to_close"]).copy()
    x = x.sort_values(["date", str(spec["signal"])], ascending=[True, ascending])
    x["rank"] = x.groupby("date").cumcount() + 1
    x = x[x["rank"].le(int(spec["top_n"]))].copy()
    x["variant"] = str(spec["variant"])
    x["gross"] = float(spec["gross"])
    x["entry_date"] = x["date"]
    x["exit_date"] = x["next_date"]
    x["gross_ret"] = x["next_ret_close_to_close"]
    return x


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


def simulate(trades: pd.DataFrame, spec: dict[str, object]) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    equity = START_CAPITAL
    prev_holdings: set[str] = set()
    daily_rows = []
    trade_rows = []
    gross = float(spec["gross"])
    for date, group in trades.groupby("entry_date", sort=True):
        group = group.copy()
        current = set(group["ticker"].astype(str))
        turnover = len(current.symmetric_difference(prev_holdings)) / max(len(current), 1)
        cost = gross * turnover * COST_BPS_PER_SIDE / 10_000.0
        group["weight"] = gross / len(group)
        group["pnl_before_costs"] = equity * group["weight"] * group["gross_ret"]
        group["cost"] = equity * cost / len(group)
        group["pnl"] = group["pnl_before_costs"] - group["cost"]
        daily_pnl = float(group["pnl"].sum())
        daily_gross_pnl = float(group["pnl_before_costs"].sum())
        equity += daily_pnl
        daily_rows.append(
            {
                "variant": spec["variant"],
                "date": pd.Timestamp(date),
                "exit_date": group["exit_date"].max(),
                "daily_pnl": daily_pnl,
                "gross_pnl_before_costs": daily_gross_pnl,
                "cost_drag": daily_pnl - daily_gross_pnl,
                "equity": equity,
                "gross": gross,
                "names": int(len(group)),
                "turnover": float(turnover),
            }
        )
        trade_rows.append(group)
        prev_holdings = current
    daily = add_periods(pd.DataFrame(daily_rows))
    out_trades = pd.concat(trade_rows, ignore_index=True)
    dd, dd_pct = max_drawdown(daily["equity"])
    summary = {
        "variant": spec["variant"],
        "pool": int(spec["pool"]),
        "selector": spec["selector"],
        "signal": spec["signal"],
        "topN": int(spec["top_n"]),
        "gross": gross,
        "filter": spec["filter"],
        "pnl": float(daily["daily_pnl"].sum()),
        "grossPnlBeforeCosts": float(daily["gross_pnl_before_costs"].sum()),
        "costDrag": float(daily["cost_drag"].sum()),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "trades": int(len(out_trades)),
        "selectedTickers": int(out_trades["ticker"].nunique()),
        "avgNames": float(daily["names"].mean()),
        "avgTurnover": float(daily["turnover"].mean()),
    }
    return summary, daily, out_trades


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
    candidate_cache: dict[int, pd.DataFrame] = {}
    summaries = []
    daily_frames = []
    trade_frames = []
    concentrations = []
    for spec in VARIANTS:
        pool = int(spec["pool"])
        if pool not in candidate_cache:
            candidate_cache[pool] = prepare_candidates(daily, caps, pool)
        trades = select_trades(candidate_cache[pool], spec)
        summary, daily_out, trade_out = simulate(trades, spec)
        summaries.append(summary)
        daily_frames.append(daily_out)
        trade_frames.append(trade_out)
        concentrations.append(concentration_row(str(spec["variant"]), trade_out))
        print("VARIANT", spec["variant"], summary, flush=True)
    all_daily = pd.concat(daily_frames, ignore_index=True)
    all_trades = pd.concat(trade_frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "split")).to_csv(SPLIT_OUT, index=False)
    pd.DataFrame(concentrations).to_csv(CONCENTRATION_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    all_trades.to_csv(TRADES_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_largecap_nextday_selection.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "sample_period": [START.strftime("%Y-%m-%d"), END.strftime("%Y-%m-%d")],
        "universe": "PIT quarterly market-cap top-N eligible stocks from broad PIT daily feature cache.",
        "entry_exit": "Signals on date t; simulated return from t 15:55 close to next available ticker close.",
        "leakage_controls": "Selection uses only date-t features and latest prior/equal market-cap snapshot; return starts after selection date close.",
        "variants": VARIANTS,
        "costs": f"{COST_BPS_PER_SIDE} bps per side approximated from holding turnover.",
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(TRADES_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, CONCENTRATION_OUT, DAILY_OUT, TRADES_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
