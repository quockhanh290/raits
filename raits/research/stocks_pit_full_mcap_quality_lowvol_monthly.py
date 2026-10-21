from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_MCAP_QUALITY_LOWVOL_MONTHLY_2026-09-14"
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
REBALANCE_OUT = Path(f"{OUT_PREFIX}_REBALANCES.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"variant": "pool500_lowvol50_gross100", "pool": 500, "selector": "lowvol", "top_n": 50, "gross": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "pool500_lowvol100_gross100", "pool": 500, "selector": "lowvol", "top_n": 100, "gross": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "pool500_ret60vol50_gross100", "pool": 500, "selector": "ret60_over_vol", "top_n": 50, "gross": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "pool500_ret60pos_lowvol50_gross100", "pool": 500, "selector": "ret60_positive_lowvol", "top_n": 50, "gross": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "pool200_lowvol50_gross100", "pool": 200, "selector": "lowvol", "top_n": 50, "gross": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "pool200_ret60vol50_gross100", "pool": 200, "selector": "ret60_over_vol", "top_n": 50, "gross": 1.0, "target_vol": None, "max_exposure": 1.0},
    {"variant": "pool500_lowvol50_vt20_cap200", "pool": 500, "selector": "lowvol", "top_n": 50, "gross": 1.0, "target_vol": 0.20, "max_exposure": 2.0},
    {"variant": "pool500_ret60vol50_vt20_cap200", "pool": 500, "selector": "ret60_over_vol", "top_n": 50, "gross": 1.0, "target_vol": 0.20, "max_exposure": 2.0},
    {"variant": "pool500_ret60pos_lowvol50_vt25_cap250", "pool": 500, "selector": "ret60_positive_lowvol", "top_n": 50, "gross": 1.0, "target_vol": 0.25, "max_exposure": 2.5},
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
    daily = daily.dropna(subset=["ticker", "prev_close_1555", "close_1555", "ret60_pre", "vol20_pre"])
    daily = daily[(daily["prev_close_1555"] > 0) & (daily["close_1555"] > 0) & (daily["vol20_pre"] > 0)].copy()
    daily["ret_close_to_close"] = daily["close_1555"] / daily["prev_close_1555"] - 1.0
    daily["month"] = daily["date"].dt.to_period("M")
    return daily[["date", "month", "ticker", "ret_close_to_close", "ret60_pre", "vol20_pre"]].copy()


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
    snapshots = caps[["date"]].drop_duplicates().sort_values("date").rename(columns={"date": "snapshot_date"})
    return pd.merge_asof(date_df, snapshots, left_on="date", right_on="snapshot_date", direction="backward")


def select_candidates(candidates: pd.DataFrame, selector: str, top_n: int) -> pd.DataFrame:
    x = candidates.copy()
    if selector == "lowvol":
        return x.sort_values(["vol20_pre", "rank_market_cap"], ascending=[True, True]).head(top_n)
    if selector == "ret60_over_vol":
        x["score"] = x["ret60_pre"] / x["vol20_pre"]
        return x.sort_values(["score", "rank_market_cap"], ascending=[False, True]).head(top_n)
    if selector == "ret60_positive_lowvol":
        positive = x[x["ret60_pre"] > 0].copy()
        source = positive if len(positive) >= top_n else x
        return source.sort_values(["vol20_pre", "rank_market_cap"], ascending=[True, True]).head(top_n)
    raise ValueError(f"unknown selector {selector}")


def build_rebalances(daily: pd.DataFrame, caps: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    first_dates = daily.groupby("month", as_index=False)["date"].min().sort_values("date")
    first_dates = first_dates.merge(cap_snapshot_for_dates(caps, first_dates["date"]), on="date", how="left")
    cap_by_date = {date: group for date, group in caps.groupby("date", sort=False)}
    daily_by_date = {date: group for date, group in daily.groupby("date", sort=False)}
    rows = []
    for rebalance_date, snapshot_date in first_dates[["date", "snapshot_date"]].itertuples(index=False):
        if pd.isna(snapshot_date) or rebalance_date not in daily_by_date:
            continue
        pool = cap_by_date[pd.Timestamp(snapshot_date)]
        pool = pool[pool["rank_market_cap"].le(int(spec["pool"]))][["ticker", "market_cap", "rank_market_cap"]]
        candidates = daily_by_date[pd.Timestamp(rebalance_date)].merge(pool, on="ticker", how="inner")
        selected = select_candidates(candidates, str(spec["selector"]), int(spec["top_n"]))
        for row in selected.itertuples(index=False):
            rows.append(
                {
                    "variant": spec["variant"],
                    "rebalance_date": rebalance_date,
                    "snapshot_date": snapshot_date,
                    "ticker": row.ticker,
                    "ret60_pre": float(row.ret60_pre),
                    "vol20_pre": float(row.vol20_pre),
                    "rank_market_cap": float(row.rank_market_cap),
                    "market_cap": float(row.market_cap),
                }
            )
    rebalances = pd.DataFrame(rows)
    dates = sorted(daily["date"].drop_duplicates())
    next_date = pd.Series(dates, index=dates).shift(-1).to_dict()
    rebalances["effective_date"] = rebalances["rebalance_date"].map(next_date)
    return rebalances.dropna(subset=["effective_date"]).copy()


def holdings_by_day(daily: pd.DataFrame, rebalances: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    rebalance_dates = rebalances[["effective_date", "rebalance_date"]].drop_duplicates().sort_values("effective_date")
    assigned = pd.merge_asof(dates, rebalance_dates, left_on="date", right_on="effective_date", direction="backward")
    h = assigned.dropna(subset=["rebalance_date"]).merge(rebalances, on="rebalance_date", how="inner")
    effective_col = "effective_date_x" if "effective_date_x" in h.columns else "effective_date"
    h = h.rename(columns={effective_col: "effective_date"})
    return h[["date", "ticker", "variant", "rebalance_date", "effective_date"]].copy()


def base_daily_returns(spec: dict[str, object], daily: pd.DataFrame, rebalances: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    holdings = holdings_by_day(daily, rebalances)
    panel = holdings.merge(daily[["date", "ticker", "ret_close_to_close"]], on=["date", "ticker"], how="inner")
    prev_holdings: set[str] = set()
    daily_rows = []
    contrib_rows = []
    gross = float(spec["gross"])
    for date, group in panel.groupby("date", sort=True):
        current = set(group["ticker"].astype(str))
        turnover = len(current.symmetric_difference(prev_holdings)) / max(len(current), 1)
        cost = gross * turnover * COST_BPS_PER_SIDE / 10_000.0
        group = group.copy()
        group["weight"] = gross / len(group)
        gross_ret = float((group["weight"] * group["ret_close_to_close"]).sum())
        net_ret = gross_ret - cost
        daily_rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "base_ret": net_ret,
                "gross_ret": gross_ret,
                "turnover": turnover,
                "names": int(len(group)),
            }
        )
        group["base_weighted_ret"] = group["weight"] * group["ret_close_to_close"] - cost / len(group)
        contrib_rows.append(group[["date", "ticker", "base_weighted_ret"]].assign(variant=spec["variant"]))
        prev_holdings = current
    return pd.DataFrame(daily_rows), pd.concat(contrib_rows, ignore_index=True)


def apply_voltarget(spec: dict[str, object], base: pd.DataFrame, contrib: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    x = base.copy()
    if spec["target_vol"] is None:
        x["exposure"] = 1.0
    else:
        realized = x["base_ret"].rolling(20, min_periods=20).std().shift(1) * math.sqrt(252)
        exposure = float(spec["target_vol"]) / realized.replace(0.0, np.nan)
        x["exposure"] = exposure.clip(lower=0.0, upper=float(spec["max_exposure"])).fillna(1.0)
    equity = START_CAPITAL
    rows = []
    for row in x.itertuples(index=False):
        daily_pnl = equity * float(row.exposure) * float(row.base_ret)
        equity += daily_pnl
        rows.append(
            {
                "variant": row.variant,
                "date": row.date,
                "base_ret": float(row.base_ret),
                "exposure": float(row.exposure),
                "daily_pnl": daily_pnl,
                "equity": equity,
                "turnover": float(row.turnover),
                "names": int(row.names),
            }
        )
    out = add_periods(pd.DataFrame(rows))
    scale = out[["date", "exposure", "equity"]].copy()
    scale["equity_lag"] = scale["equity"].shift(1).fillna(START_CAPITAL)
    contrib_out = contrib.merge(scale[["date", "exposure", "equity_lag"]], on="date", how="inner")
    contrib_out["pnl"] = contrib_out["equity_lag"] * contrib_out["exposure"] * contrib_out["base_weighted_ret"]
    dd, dd_pct = max_drawdown(out["equity"])
    summary = {
        "variant": spec["variant"],
        "pool": int(spec["pool"]),
        "selector": spec["selector"],
        "top_n": int(spec["top_n"]),
        "targetVol": spec["target_vol"],
        "maxExposure": float(spec["max_exposure"]),
        "pnl": float(out["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(out["equity"], out["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(out["daily_pnl"]),
        "days": int(len(out)),
        "avgExposure": float(out["exposure"].mean()),
        "maxExposureRealized": float(out["exposure"].max()),
        "avgNames": float(out["names"].mean()),
        "avgTurnover": float(out["turnover"].mean()),
        "selectedTickers": int(contrib_out["ticker"].nunique()),
    }
    return summary, out, contrib_out[["date", "ticker", "pnl", "variant"]]


def add_periods(daily: pd.DataFrame) -> pd.DataFrame:
    x = daily.copy()
    x["year"] = x["date"].dt.year
    x["split"] = np.select(
        [x["year"].le(2021), x["year"].eq(2022), x["year"].ge(2023)],
        ["2018_2021_research", "2022_stress", "2023_2024_touched"],
        default="other",
    )
    return x


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
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "avgExposure": float(group["exposure"].mean()),
                "days": int(len(group)),
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


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker", sort=False)["pnl"].sum().sort_values(ascending=False)
    total = float(contrib["pnl"].sum())
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
    summaries = []
    daily_frames = []
    contrib_frames = []
    rebalance_frames = []
    concentration = []
    for spec in VARIANTS:
        rebalances = build_rebalances(daily, caps, spec)
        base, contrib_base = base_daily_returns(spec, daily, rebalances)
        summary, daily_out, contrib = apply_voltarget(spec, base, contrib_base)
        summaries.append(summary)
        daily_frames.append(daily_out)
        contrib_frames.append(contrib)
        rebalance_frames.append(rebalances)
        concentration.append(concentration_row(str(spec["variant"]), contrib))
        print("VARIANT", spec["variant"], summary, flush=True)
    all_daily = pd.concat(daily_frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "split")).to_csv(SPLIT_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(rebalance_frames, ignore_index=True).to_csv(REBALANCE_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_mcap_quality_lowvol_monthly.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "sample_label": "Research/in-sample diagnostics across 2018-2024. 2023-2024 is touched validation, not clean unseen OOS.",
        "causality": "Monthly selection uses prior ret60_pre/vol20_pre and PIT market-cap snapshot; holdings start next trading day. Vol target is shifted by one day.",
        "variants": VARIANTS,
        "costs": f"{COST_BPS_PER_SIDE} bps per side approximated from monthly holding turnover.",
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(CONCENTRATION_OUT), str(REBALANCE_OUT), str(DAILY_OUT), str(CONTRIB_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, CONCENTRATION_OUT, REBALANCE_OUT, DAILY_OUT, CONTRIB_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
