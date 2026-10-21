from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_WASHOUT_REBOUND_PULSE_2026-09-14"
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
TRIGGER_QA_OUT = Path(f"{OUT_PREFIX}_TRIGGER_QA.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Pre-registered crash/washout rebound family.
# Trigger is known after close on date t; exposure earns t close to t+1 close.
VARIANTS = [
    {"variant": "top500_broadret_m2_hold1_gross100", "pool": 500, "trigger": "broad_ret", "op": "<=", "threshold": -0.02, "hold_days": 1, "gross": 1.0},
    {"variant": "top500_broadret_m3_hold1_gross100", "pool": 500, "trigger": "broad_ret", "op": "<=", "threshold": -0.03, "hold_days": 1, "gross": 1.0},
    {"variant": "top500_adv20_hold1_gross100", "pool": 500, "trigger": "adv_frac", "op": "<=", "threshold": 0.20, "hold_days": 1, "gross": 1.0},
    {"variant": "top500_adv25_hold3_gross100", "pool": 500, "trigger": "adv_frac", "op": "<=", "threshold": 0.25, "hold_days": 3, "gross": 1.0},
    {"variant": "top500_broadret_m2_hold3_gross100", "pool": 500, "trigger": "broad_ret", "op": "<=", "threshold": -0.02, "hold_days": 3, "gross": 1.0},
    {"variant": "top100_broadret_m2_hold3_gross150", "pool": 100, "trigger": "broad_ret", "op": "<=", "threshold": -0.02, "hold_days": 3, "gross": 1.5},
    {"variant": "top500_gapdown35_hold1_gross100", "pool": 500, "trigger": "gapdown_frac", "op": ">=", "threshold": 0.35, "hold_days": 1, "gross": 1.0},
    {"variant": "top500_broadret_m15_adv30_hold3_gross100", "pool": 500, "trigger": "combo_broadret_adv", "op": "combo", "threshold": 0.0, "hold_days": 3, "gross": 1.0},
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
    daily = daily.dropna(subset=["ticker", "close_1555", "prev_close_1555", "gap"])
    daily = daily[(daily["close_1555"] > 0) & (daily["prev_close_1555"] > 0)].copy()
    daily = daily.sort_values(["ticker", "date"])
    daily["ret_close_to_close"] = daily["close_1555"] / daily["prev_close_1555"] - 1.0
    daily["next_close_1555"] = daily.groupby("ticker")["close_1555"].shift(-1)
    daily["next_date"] = daily.groupby("ticker")["date"].shift(-1)
    daily["ret_next"] = daily["next_close_1555"] / daily["close_1555"] - 1.0
    return daily.dropna(subset=["ret_next", "next_date"]).copy()


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


def prepare_top_pool(daily: pd.DataFrame, caps: pd.DataFrame, pool: int) -> pd.DataFrame:
    assigned = cap_snapshot_for_dates(caps, daily["date"])
    x = daily.merge(assigned, on="date", how="inner")
    x = x.merge(caps, left_on=["snapshot_date", "ticker"], right_on=["date", "ticker"], how="inner", suffixes=("", "_cap"))
    return x[x["rank_market_cap"].le(pool)].copy()


def build_breadth(daily: pd.DataFrame) -> pd.DataFrame:
    return (
        daily.groupby("date", sort=True)
        .agg(
            names=("ticker", "nunique"),
            broad_ret=("ret_close_to_close", "mean"),
            adv_frac=("ret_close_to_close", lambda s: float((s > 0).mean())),
            gapdown_frac=("gap", lambda s: float((s < -0.01).mean())),
        )
        .reset_index()
    )


def trigger_mask(breadth: pd.DataFrame, spec: dict[str, object]) -> pd.Series:
    trigger = str(spec["trigger"])
    op = str(spec["op"])
    threshold = float(spec["threshold"])
    if trigger == "combo_broadret_adv":
        return (breadth["broad_ret"] <= -0.015) & (breadth["adv_frac"] <= 0.30)
    values = breadth[trigger]
    if op == "<=":
        return values <= threshold
    if op == ">=":
        return values >= threshold
    raise ValueError(f"unsupported trigger/op: {trigger}/{op}")


def exposure_by_date(breadth: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    x = breadth[["date"]].copy()
    x["trigger_on"] = trigger_mask(breadth, spec)
    hold = int(spec["hold_days"])
    x["active"] = x["trigger_on"].rolling(hold, min_periods=1).max().astype(bool)
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


def simulate(pool_daily: pd.DataFrame, breadth: pd.DataFrame, spec: dict[str, object]) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame, dict[str, object]]:
    exposure = exposure_by_date(breadth, spec)
    x = pool_daily.merge(exposure, on="date", how="inner")
    equity = START_CAPITAL
    was_active = False
    daily_rows = []
    contrib_rows = []
    gross = float(spec["gross"])
    for date, group in x.groupby("date", sort=True):
        group = group.copy()
        active = bool(group["active"].iloc[0])
        names = int(group["ticker"].nunique())
        daily_pnl = 0.0
        daily_gross_pnl = 0.0
        cost_drag = 0.0
        if active:
            weight = gross / names
            group["pnl_before_costs"] = equity * weight * group["ret_next"]
            cost = gross * COST_BPS_PER_SIDE / 10_000.0 if not was_active else 0.0
            group["cost"] = equity * cost / names
            group["pnl"] = group["pnl_before_costs"] - group["cost"]
            daily_pnl = float(group["pnl"].sum())
            daily_gross_pnl = float(group["pnl_before_costs"].sum())
            cost_drag = daily_pnl - daily_gross_pnl
            contrib_rows.append(group[["date", "ticker", "pnl"]].assign(variant=spec["variant"]))
        equity += daily_pnl
        daily_rows.append(
            {
                "variant": spec["variant"],
                "date": pd.Timestamp(date),
                "daily_pnl": daily_pnl,
                "gross_pnl_before_costs": daily_gross_pnl,
                "cost_drag": cost_drag,
                "equity": equity,
                "gross": gross if active else 0.0,
                "active": active,
                "trigger_on": bool(group["trigger_on"].iloc[0]),
                "names": names if active else 0,
            }
        )
        was_active = active
    daily = add_periods(pd.DataFrame(daily_rows))
    contrib = pd.concat(contrib_rows, ignore_index=True) if contrib_rows else pd.DataFrame(columns=["date", "ticker", "pnl", "variant"])
    dd, dd_pct = max_drawdown(daily["equity"])
    summary = {
        "variant": spec["variant"],
        "pool": int(spec["pool"]),
        "trigger": spec["trigger"],
        "op": spec["op"],
        "threshold": float(spec["threshold"]),
        "holdDays": int(spec["hold_days"]),
        "gross": gross,
        "pnl": float(daily["daily_pnl"].sum()),
        "grossPnlBeforeCosts": float(daily["gross_pnl_before_costs"].sum()),
        "costDrag": float(daily["cost_drag"].sum()),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "activeDays": int(daily["active"].sum()),
        "triggerDays": int(daily["trigger_on"].sum()),
        "pctActiveDays": float(daily["active"].mean()),
        "selectedTickers": int(contrib["ticker"].nunique()) if not contrib.empty else 0,
        "avgNamesActive": float(daily.loc[daily["active"], "names"].mean()) if daily["active"].any() else 0.0,
    }
    trigger_qa = {
        "variant": spec["variant"],
        "triggerDays": summary["triggerDays"],
        "activeDays": summary["activeDays"],
        "pctActiveDays": summary["pctActiveDays"],
        "avgNamesActive": summary["avgNamesActive"],
    }
    return summary, daily, contrib, trigger_qa


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
                "activeDays": int(group["active"].sum()),
                "triggerDays": int(group["trigger_on"].sum()),
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
    total = float(contrib["pnl"].sum()) if not contrib.empty else 0.0
    denom = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        "topTickerPnl": float(by_ticker.iloc[0]) if not by_ticker.empty else 0.0,
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denom if denom else float("nan")
    return row


def main() -> None:
    daily = load_daily()
    caps = load_caps()
    breadth = build_breadth(daily)
    pool_cache: dict[int, pd.DataFrame] = {}
    summaries = []
    daily_frames = []
    contrib_frames = []
    trigger_qa = []
    concentrations = []
    for spec in VARIANTS:
        pool = int(spec["pool"])
        if pool not in pool_cache:
            pool_cache[pool] = prepare_top_pool(daily, caps, pool)
        summary, daily_out, contrib, qa = simulate(pool_cache[pool], breadth, spec)
        summaries.append(summary)
        daily_frames.append(daily_out)
        contrib_frames.append(contrib)
        trigger_qa.append(qa)
        concentrations.append(concentration_row(str(spec["variant"]), contrib))
        print("VARIANT", spec["variant"], summary, flush=True)
    all_daily = pd.concat(daily_frames, ignore_index=True)
    all_contrib = pd.concat(contrib_frames, ignore_index=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "year")).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(period_rows(all_daily, "split")).to_csv(SPLIT_OUT, index=False)
    pd.DataFrame(concentrations).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(trigger_qa).to_csv(TRIGGER_QA_OUT, index=False)
    all_daily.to_csv(DAILY_OUT, index=False)
    all_contrib.to_csv(CONTRIB_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_washout_rebound_pulse.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "sample_period": [START.strftime("%Y-%m-%d"), END.strftime("%Y-%m-%d")],
        "universe": "PIT quarterly market-cap top100/top500 stocks from broad PIT daily feature cache.",
        "entry_exit": "Trigger known after close on date t; exposure earns t close to t+1 close; hold_days extends active exposure for subsequent close-to-close intervals.",
        "leakage_controls": "Trigger uses date-t close/breadth information only; returns start after trigger date close.",
        "variants": VARIANTS,
        "costs": f"{COST_BPS_PER_SIDE} bps entry cost when pulse turns active; no explicit exit cost because cash transition is modeled as return stream diagnostic.",
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "old_62_usage": "None.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SPLIT_OUT), str(CONCENTRATION_OUT), str(TRIGGER_QA_OUT), str(DAILY_OUT), str(CONTRIB_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SPLIT_OUT, CONCENTRATION_OUT, TRIGGER_QA_OUT, DAILY_OUT, CONTRIB_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
