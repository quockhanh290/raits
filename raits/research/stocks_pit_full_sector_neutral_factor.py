from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_SECTOR_NEUTRAL_FACTOR_2026-09-15"
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

# New pre-registered family: sector/SIC-neutral factor spreads. This is meant
# to remove market beta structurally instead of using equity stops.
VARIANTS = [
    {"variant": "sic_neutral_ret60_q20_weekly_gross100", "score": "ret60", "quantile": 0.20, "freq": "W-MON", "gross": 1.0},
    {"variant": "sic_neutral_ret60_q30_weekly_gross100", "score": "ret60", "quantile": 0.30, "freq": "W-MON", "gross": 1.0},
    {"variant": "sic_neutral_ret60_lowvol_q20_weekly_gross100", "score": "ret60_lowvol", "quantile": 0.20, "freq": "W-MON", "gross": 1.0},
    {"variant": "sic_neutral_reversal20_q20_weekly_gross100", "score": "reversal20", "quantile": 0.20, "freq": "W-MON", "gross": 1.0},
    {"variant": "sic_neutral_ret60_q20_monthly_gross100", "score": "ret60", "quantile": 0.20, "freq": "M", "gross": 1.0},
    {"variant": "sic_neutral_ret60_lowvol_q20_monthly_gross100", "score": "ret60_lowvol", "quantile": 0.20, "freq": "M", "gross": 1.0},
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
    needed = ["date", "ticker", "prev_close_1555", "close_1555", "ret20_pre", "ret60_pre", "vol20_pre"]
    x = x[(x["date"] >= START) & (x["date"] <= END)][needed].copy()
    x = x.dropna(subset=needed)
    x = x[(x["prev_close_1555"] > 0) & (x["close_1555"] > 0) & (x["vol20_pre"] > 0)].copy()
    x["ret_close_to_close"] = x["close_1555"] / x["prev_close_1555"] - 1.0
    return x[["date", "ticker", "ret_close_to_close", "ret20_pre", "ret60_pre", "vol20_pre"]].copy()


def load_caps() -> pd.DataFrame:
    x = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    x["ticker_query"] = x["ticker_query"].astype(str).str.upper()
    x["market_cap"] = pd.to_numeric(x["market_cap"], errors="coerce")
    x["sic_description"] = x["sic_description"].fillna("UNKNOWN").astype(str)
    x = x[x["status_code"].eq(200) & x["market_cap"].notna()].copy()
    x = x.sort_values(["date", "market_cap"], ascending=[True, False])
    x["rank_market_cap"] = x.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return x[x["rank_market_cap"].le(POOL_TOP_N)][["date", "ticker_query", "sic_description", "rank_market_cap"]].copy()


def apply_asof_caps(daily: pd.DataFrame, caps: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for ticker, group in daily.groupby("ticker", sort=False):
        cap_t = caps[caps["ticker_query"].eq(ticker)].sort_values("date")
        if cap_t.empty:
            continue
        joined = pd.merge_asof(group.sort_values("date"), cap_t, on="date", direction="backward")
        joined = joined[joined["rank_market_cap"].notna()].copy()
        frames.append(joined)
    out = pd.concat(frames, ignore_index=True)
    out["sector"] = out["sic_description"].fillna("UNKNOWN").astype(str)
    return out


def rebalance_dates(daily: pd.DataFrame, freq: str) -> set[pd.Timestamp]:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    if freq == "M":
        key = dates["date"].dt.to_period("M")
    else:
        key = dates["date"].dt.to_period(freq)
    return set(dates.groupby(key)["date"].min().tolist())


def score_frame(group: pd.DataFrame, score: str) -> pd.DataFrame:
    x = group.copy()
    if score == "ret60":
        x["score_value"] = x["ret60_pre"]
    elif score == "ret60_lowvol":
        mom = x["ret60_pre"].rank(pct=True)
        lowvol = (-x["vol20_pre"]).rank(pct=True)
        x["score_value"] = 0.65 * mom + 0.35 * lowvol
    elif score == "reversal20":
        x["score_value"] = -x["ret20_pre"]
    else:
        raise ValueError(score)
    return x


def target_weights(group: pd.DataFrame, spec: dict[str, object]) -> pd.Series:
    pieces = []
    sector_groups = [(sector, g) for sector, g in group.groupby("sector") if len(g) >= 10]
    if not sector_groups:
        return pd.Series(dtype=float)
    sector_gross = float(spec["gross"]) / len(sector_groups)
    q = float(spec["quantile"])
    for _sector, sector_group in sector_groups:
        scored = score_frame(sector_group, str(spec["score"])).sort_values(["score_value", "ticker"])
        n = max(1, int(math.floor(len(scored) * q)))
        long_names = scored.tail(n)["ticker"].tolist()
        short_names = scored.head(n)["ticker"].tolist()
        weights: dict[str, float] = {}
        for ticker in long_names:
            weights[ticker] = weights.get(ticker, 0.0) + sector_gross / 2.0 / len(long_names)
        for ticker in short_names:
            weights[ticker] = weights.get(ticker, 0.0) - sector_gross / 2.0 / len(short_names)
        pieces.append(pd.Series(weights, dtype=float))
    if not pieces:
        return pd.Series(dtype=float)
    return pd.concat(pieces).groupby(level=0).sum()


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
    rdates = rebalance_dates(daily, str(spec["freq"]))
    weights = pd.Series(dtype=float)
    equity = START_CAPITAL
    rows = []
    contrib_rows = []
    cost_rate = TRADE_COST_BPS / 10_000.0
    borrow_daily = SHORT_BORROW_ANNUAL_RATE / 252.0
    for date in sorted(by_date):
        group = by_date[date]
        rets = group["ret_close_to_close"].reindex(weights.index).fillna(0.0)
        pnl_by_ticker = equity * weights * rets if not weights.empty else pd.Series(dtype=float)
        short_gross = float(weights[weights < 0].abs().sum()) if not weights.empty else 0.0
        borrow_cost = equity * short_gross * borrow_daily
        if borrow_cost > 0 and short_gross > 0:
            short_alloc = weights[weights < 0].abs() / short_gross * borrow_cost
            pnl_by_ticker.loc[short_alloc.index] = pnl_by_ticker.loc[short_alloc.index] - short_alloc
        gross_pnl = float(pnl_by_ticker.sum())
        equity += gross_pnl
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
                "daily_pnl": gross_pnl - trade_cost,
                "borrow_cost": borrow_cost,
                "trade_cost": trade_cost,
                "equity": equity,
                "turnover": turnover,
                "gross_exposure": float(weights.abs().sum()) if not weights.empty else 0.0,
                "net_exposure": float(weights.sum()) if not weights.empty else 0.0,
                "short_gross": float(weights[weights < 0].abs().sum()) if not weights.empty else 0.0,
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
        "score": spec["score"],
        "quantile": float(spec["quantile"]),
        "freq": spec["freq"],
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
    daily = apply_asof_caps(load_daily(), load_caps())
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
        print("SECTOR_NEUTRAL", summaries[-1], flush=True)
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
                "sectors": int(daily["sector"].nunique()),
                "medianNamesPerDay": float(daily.groupby("date")["ticker"].nunique().median()),
                "poolTopN": POOL_TOP_N,
            }
        ]
    )
    qa.to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_sector_neutral_factor.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "Pre-registered SIC-neutral long/short factor spreads inside PIT top500. Long and short quantiles selected within each SIC description group.",
        "costs": f"{TRADE_COST_BPS} bps turnover and {SHORT_BORROW_ANNUAL_RATE:.1%} annual borrow on short gross.",
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "Uses PIT market-cap snapshots via per-ticker as-of merge and lagged ret20_pre/ret60_pre/vol20_pre features. No old manual 62 list.",
        "rule_selection_effect": "None inside diagnostic. Factor definitions, quantiles, and rebalance frequencies fixed before running.",
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
