from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_DEFENSIVE_LARGECAP_MONTHLY_2026-09-15"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)
START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
TRADE_COST_BPS = 4.0
FINANCING_ANNUAL_RATE = 0.025
POOL_TOP_N = 500

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered defensive large-cap family. All selection variables are lagged
# feature-cache fields available before the close-to-close return being earned.
VARIANTS = [
    {"variant": "top500_lowvol50_gross100", "score": "low_vol", "select_n": 50, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_lowvol100_gross100", "score": "low_vol", "select_n": 100, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_posmom_lowvol50_gross100", "score": "posmom_lowvol", "select_n": 50, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_posmom_lowvol100_gross100", "score": "posmom_lowvol", "select_n": 100, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_mom60_lowvol50_gross100", "score": "mom60_lowvol", "select_n": 50, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_lowvol50_vt16_cap150", "score": "low_vol", "select_n": 50, "gross": 1.0, "target_vol": 0.16, "cap": 1.5},
    {"variant": "top500_posmom_lowvol50_vt16_cap150", "score": "posmom_lowvol", "select_n": 50, "gross": 1.0, "target_vol": 0.16, "cap": 1.5},
    {"variant": "top500_lowvol50_vt20_cap200", "score": "low_vol", "select_n": 50, "gross": 1.0, "target_vol": 0.20, "cap": 2.0},
    {"variant": "top500_posmom_lowvol50_vt20_cap200", "score": "posmom_lowvol", "select_n": 50, "gross": 1.0, "target_vol": 0.20, "cap": 2.0},
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
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily = daily[(daily["date"] >= START) & (daily["date"] <= END)].copy()
    daily = daily.dropna(subset=["ticker", "prev_close_1555", "close_1555", "ret60_pre", "vol20_pre"])
    daily = daily[(daily["prev_close_1555"] > 0) & (daily["close_1555"] > 0) & (daily["vol20_pre"] > 0)].copy()
    daily["ret_close_to_close"] = daily["close_1555"] / daily["prev_close_1555"] - 1.0
    return daily[["date", "ticker", "ret_close_to_close", "ret60_pre", "vol20_pre"]].copy()


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


def rebalance_dates(daily: pd.DataFrame) -> list[pd.Timestamp]:
    x = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    return x.groupby(x["date"].dt.to_period("M"))["date"].min().tolist()


def select_names(group: pd.DataFrame, spec: dict[str, object]) -> list[str]:
    x = group.copy()
    if spec["score"] == "low_vol":
        x["score_value"] = -x["vol20_pre"]
    elif spec["score"] == "posmom_lowvol":
        x = x[x["ret60_pre"] > 0].copy()
        x["score_value"] = -x["vol20_pre"]
    elif spec["score"] == "mom60_lowvol":
        vol_rank = x["vol20_pre"].rank(pct=True, ascending=True)
        mom_rank = x["ret60_pre"].rank(pct=True, ascending=False)
        x["score_value"] = -(0.65 * vol_rank + 0.35 * mom_rank)
    else:
        raise ValueError(str(spec["score"]))
    return x.sort_values(["score_value", "ticker"], ascending=[False, True]).head(int(spec["select_n"]))["ticker"].tolist()


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
    rdates = set(rebalance_dates(daily))
    dates = sorted(by_date)
    equity = START_CAPITAL
    current_names: list[str] = []
    prev_weights = pd.Series(dtype=float)
    realized_rets: list[float] = []
    rows = []
    contrib_rows = []
    cost_rate = TRADE_COST_BPS / 10_000.0

    for date in dates:
        group = by_date[date]
        if date in rdates or not current_names:
            current_names = select_names(group.reset_index(), spec)
        base_weights = pd.Series(0.0, index=pd.Index(current_names, dtype=str))
        if current_names:
            base_weights.loc[current_names] = float(spec["gross"]) / len(current_names)
        base_ret_series = group["ret_close_to_close"].reindex(base_weights.index).fillna(0.0)
        base_ret = float((base_weights * base_ret_series).sum())
        if spec["target_vol"] is None or len(realized_rets) < 20:
            exposure = 1.0
        else:
            realized_vol = float(pd.Series(realized_rets[-20:]).std() * math.sqrt(252))
            exposure = float(spec["target_vol"]) / realized_vol if realized_vol > 0 else 1.0
            exposure = min(max(exposure, 0.0), float(spec["cap"]))
        target_weights = exposure * base_weights
        aligned_prev = prev_weights.reindex(target_weights.index.union(prev_weights.index)).fillna(0.0)
        aligned_target = target_weights.reindex(aligned_prev.index).fillna(0.0)
        turnover = float((aligned_target - aligned_prev).abs().sum())
        financing_drag = max(float(aligned_target.abs().sum()) - 1.0, 0.0) * FINANCING_ANNUAL_RATE / 252.0
        turnover_drag = turnover * cost_rate
        gross_ret = float((target_weights * base_ret_series).sum())
        daily_ret = gross_ret - financing_drag - turnover_drag
        daily_pnl = equity * daily_ret
        gross_pnl = equity * gross_ret
        trade_cost = equity * turnover_drag
        financing_cost = equity * financing_drag
        rets_for_contrib = group["ret_close_to_close"].reindex(aligned_target.index).fillna(0.0)
        ticker_pnl = equity * aligned_target * rets_for_contrib
        if trade_cost > 0 and turnover > 0:
            cost_alloc = (aligned_target - aligned_prev).abs() / turnover * trade_cost
            ticker_pnl = ticker_pnl - cost_alloc
        if financing_cost > 0 and float(aligned_target.abs().sum()) > 0:
            fin_alloc = aligned_target.abs() / float(aligned_target.abs().sum()) * financing_cost
            ticker_pnl = ticker_pnl - fin_alloc
        equity += daily_pnl
        realized_rets.append(base_ret)
        rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "base_ret": base_ret,
                "exposure": exposure,
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "gross_pnl_before_cost": gross_pnl,
                "trade_cost": trade_cost,
                "financing_cost": financing_cost,
                "equity": equity,
                "turnover": turnover,
                "gross_exposure": float(aligned_target.abs().sum()),
                "names": len(current_names),
            }
        )
        contrib_rows.extend(
            {
                "variant": spec["variant"],
                "date": date,
                "ticker": ticker,
                "pnl": float(pnl),
            }
            for ticker, pnl in ticker_pnl.items()
            if abs(float(pnl)) > 0
        )
        prev_weights = target_weights

    daily_out = pd.DataFrame(rows)
    daily_out["year"] = daily_out["date"].dt.year
    return daily_out, pd.DataFrame(contrib_rows)


def summary_row(spec: dict[str, object], daily: pd.DataFrame, contrib: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "score": spec["score"],
        "selectN": int(spec["select_n"]),
        "targetVol": float(spec["target_vol"]) if spec["target_vol"] is not None else np.nan,
        "cap": float(spec["cap"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "tradeCost": float(daily["trade_cost"].sum()),
        "financingCost": float(daily["financing_cost"].sum()),
        "avgExposure": float(daily["exposure"].mean()),
        "maxExposure": float(daily["exposure"].max()),
        "avgTurnover": float(daily["turnover"].mean()),
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
                "financingCost": float(group["financing_cost"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "avgExposure": float(group["exposure"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    raw = load_daily()
    daily = apply_pool(raw, load_pool_membership())
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
        print("DEFENSIVE", summaries[-1], flush=True)
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
            }
        ]
    )
    qa.to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_defensive_largecap_monthly.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "Pre-registered monthly defensive large-cap selection from PIT top500 using lagged vol20_pre and ret60_pre.",
        "costs": f"{TRADE_COST_BPS} bps per dollar of target-weight turnover; {FINANCING_ANNUAL_RATE:.1%} annual financing on gross above 1x for vol-target rows.",
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "Selection uses PIT market-cap top500 and feature columns ret60_pre/vol20_pre already known before same-day close-to-close return. Rebalance is first trading day of month. No old manual 62 list.",
        "rule_selection_effect": "None inside diagnostic. Score family, select counts, gross, target vol, and caps fixed before running.",
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
