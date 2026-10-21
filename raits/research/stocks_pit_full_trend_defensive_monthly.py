from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_TREND_DEFENSIVE_MONTHLY_2026-09-15"
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

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"variant": "top500_trend60_volcap60_top50_gross100", "pool": 500, "select_n": 50, "vol_pct_max": 0.60, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_trend60_volcap60_top100_gross100", "pool": 500, "select_n": 100, "vol_pct_max": 0.60, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_trend60_volcap40_top50_gross100", "pool": 500, "select_n": 50, "vol_pct_max": 0.40, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_trend60_volcap40_top100_gross100", "pool": 500, "select_n": 100, "vol_pct_max": 0.40, "gross": 1.0, "target_vol": None, "cap": 1.0},
    {"variant": "top500_trend60_volcap60_top50_vt16_cap150", "pool": 500, "select_n": 50, "vol_pct_max": 0.60, "gross": 1.0, "target_vol": 0.16, "cap": 1.5},
    {"variant": "top500_trend60_volcap40_top50_vt16_cap150", "pool": 500, "select_n": 50, "vol_pct_max": 0.40, "gross": 1.0, "target_vol": 0.16, "cap": 1.5},
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
    x = x[(x["date"] >= START) & (x["date"] <= END)].copy()
    x = x.dropna(subset=["ticker", "prev_close_1555", "close_1555", "ret20_pre", "ret60_pre", "vol20_pre"])
    x = x[(x["prev_close_1555"] > 0) & (x["close_1555"] > 0) & (x["vol20_pre"] > 0)].copy()
    x["ret_close_to_close"] = x["close_1555"] / x["prev_close_1555"] - 1.0
    return x[["date", "ticker", "ret_close_to_close", "ret20_pre", "ret60_pre", "vol20_pre"]].copy()


def load_caps() -> pd.DataFrame:
    x = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    x["ticker_query"] = x["ticker_query"].astype(str).str.upper()
    x["market_cap"] = pd.to_numeric(x["market_cap"], errors="coerce")
    x = x[x["status_code"].eq(200) & x["market_cap"].notna()].copy()
    x = x.sort_values(["date", "market_cap"], ascending=[True, False])
    x["rank_market_cap"] = x.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return x


def apply_pool(daily: pd.DataFrame, caps: pd.DataFrame, pool: int) -> pd.DataFrame:
    selected = caps[caps["rank_market_cap"].le(pool)].copy()
    membership = (
        selected.groupby("date", sort=True)["ticker_query"]
        .apply(lambda s: set(s.astype(str)))
        .rename("ticker_set")
        .reset_index()
    )
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    assigned = pd.merge_asof(dates, membership.sort_values("date"), on="date", direction="backward")
    date_to_set = dict(zip(assigned["date"], assigned["ticker_set"]))
    sets = daily["date"].map(date_to_set)
    mask = [ticker in s if isinstance(s, set) else False for ticker, s in zip(daily["ticker"], sets)]
    return daily.loc[mask].copy()


def rebalance_dates(daily: pd.DataFrame) -> set[pd.Timestamp]:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    return set(dates.groupby(dates["date"].dt.to_period("M"))["date"].min().tolist())


def select_names(group: pd.DataFrame, spec: dict[str, object]) -> list[str]:
    x = group.copy()
    x["vol_pct"] = x["vol20_pre"].rank(pct=True, ascending=True)
    x = x[(x["ret20_pre"] > 0) & (x["ret60_pre"] > 0) & (x["vol_pct"] <= float(spec["vol_pct_max"]))].copy()
    if x.empty:
        return []
    x["score"] = x["ret60_pre"].rank(pct=True, ascending=False) + x["vol20_pre"].rank(pct=True, ascending=True)
    return x.sort_values(["score", "ticker"]).head(int(spec["select_n"]))["ticker"].tolist()


def simulate(spec: dict[str, object], daily: pd.DataFrame) -> pd.DataFrame:
    by_date = {date: group.set_index("ticker") for date, group in daily.groupby("date", sort=True)}
    rdates = rebalance_dates(daily)
    equity = START_CAPITAL
    names: list[str] = []
    prev_weights = pd.Series(dtype=float)
    base_rets: list[float] = []
    rows = []
    cost_rate = TRADE_COST_BPS / 10_000.0
    for date in sorted(by_date):
        group = by_date[date]
        if date in rdates or not names:
            names = select_names(group.reset_index(), spec)
        base_weights = pd.Series(dtype=float)
        if names:
            base_weights = pd.Series(float(spec["gross"]) / len(names), index=pd.Index(names, dtype=str))
        rets = group["ret_close_to_close"].reindex(base_weights.index).fillna(0.0)
        base_ret = float((base_weights * rets).sum()) if not base_weights.empty else 0.0
        if spec["target_vol"] is None or len(base_rets) < 20:
            exposure = 1.0
        else:
            realized = float(pd.Series(base_rets[-20:]).std() * math.sqrt(252))
            exposure = min(float(spec["cap"]), max(0.0, float(spec["target_vol"]) / realized)) if realized > 0 else 1.0
        target_weights = exposure * base_weights
        aligned_prev = prev_weights.reindex(target_weights.index.union(prev_weights.index)).fillna(0.0)
        aligned_target = target_weights.reindex(aligned_prev.index).fillna(0.0)
        turnover = float((aligned_target - aligned_prev).abs().sum())
        turnover_drag = turnover * cost_rate
        financing_drag = max(float(aligned_target.abs().sum()) - 1.0, 0.0) * FINANCING_ANNUAL_RATE / 252.0
        daily_ret = exposure * base_ret - turnover_drag - financing_drag
        daily_pnl = equity * daily_ret
        equity += daily_pnl
        base_rets.append(base_ret)
        rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_ret": daily_ret,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "base_ret": base_ret,
                "exposure": exposure,
                "gross_exposure": float(aligned_target.abs().sum()),
                "turnover": turnover,
                "trade_cost": equity * turnover_drag,
                "financing_cost": equity * financing_drag,
                "names": len(names),
            }
        )
        prev_weights = target_weights
    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    return out


def summary_row(daily: pd.DataFrame, spec: dict[str, object]) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "selectN": int(spec["select_n"]),
        "volPctMax": float(spec["vol_pct_max"]),
        "targetVol": float(spec["target_vol"]) if spec["target_vol"] is not None else np.nan,
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "tradeCost": float(daily["trade_cost"].sum()),
        "financingCost": float(daily["financing_cost"].sum()),
        "avgExposure": float(daily["exposure"].mean()),
        "avgNames": float(daily["names"].mean()),
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
                "avgExposure": float(group["exposure"].mean()),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    raw = load_daily()
    caps = load_caps()
    pool = apply_pool(raw, caps, 500)
    frames = []
    summaries = []
    yearly = []
    for spec in VARIANTS:
        daily = simulate(spec, pool)
        frames.append(daily)
        summaries.append(summary_row(daily, spec))
        yearly.extend(yearly_rows(daily))
        print("TREND_DEF", summaries[-1], flush=True)
    all_daily = pd.concat(frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_trend_defensive_monthly.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "Pre-registered monthly top500 trend-defensive selection: ret20_pre>0, ret60_pre>0, vol20_pre percentile cap, ranked by trend and low vol.",
        "costs": f"{TRADE_COST_BPS} bps turnover; {FINANCING_ANNUAL_RATE:.1%} annual financing above 1x for vol-target rows.",
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "Selection uses PIT market-cap top500 and lagged feature-cache fields only. No old manual 62 list.",
        "rule_selection_effect": "None inside diagnostic. Six variants fixed before running.",
        "variants": VARIANTS,
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
