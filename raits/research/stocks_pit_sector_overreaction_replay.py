from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from stocks_pit_1520_continuation_replay import concentration, metrics, sha256, simulate


PREREG = Path("STOCKS_PIT_SECTOR_OVERREACTION_PREREG_2026-10-02.json")
FEATURES = Path("raits/data/cache/stocks_pit_1520_continuation_2018_2022/causal_features_pre1520.parquet")
FEATURE_MANIFEST = FEATURES.with_name("causal_features_pre1520_manifest.json")
SIMULATOR = Path("raits/research/stocks_pit_1520_continuation_replay.py")
PREFIX = "STOCKS_PIT_SECTOR_OVERREACTION_2026-10-02"
START, DEV_END = pd.Timestamp("2018-03-29"), pd.Timestamp("2021-12-31")
VAL_START, VAL_END = pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-30")
BASE_COST_BPS = 4.0
STRESS_COST_BPS = 8.0
VARIANTS = [
    "sector_resid_reversal_overnight",
    "sector_resid_reversal_next1520",
    "sector_exhaustion_overnight",
    "double_resid_reversal_overnight",
    "extreme_volume_reversal_overnight",
]


def add_cross_sectional_features(panel: pd.DataFrame) -> pd.DataFrame:
    x = panel.copy()
    sector_group = x.groupby(["date", "sic_description"])["intraday_return"]
    x["sector_count"] = sector_group.transform("count")
    x["sector_median_return"] = sector_group.transform("median")
    x["market_median_return"] = x.groupby("date")["intraday_return"].transform("median")
    x["sector_residual"] = x["intraday_return"] - x["sector_median_return"]
    x["market_residual"] = x["intraday_return"] - x["market_median_return"]
    return x


def candidate_pool(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    x = panel[
        panel["entry_price_1520"].gt(0)
        & panel["signal_close_1520"].ge(5.0)
        & panel["signal_dollar"].ge(1_000_000.0)
        & panel["sector_count"].ge(10)
    ].copy()
    if variant in ("sector_resid_reversal_overnight", "sector_resid_reversal_next1520"):
        x = x[x["sector_residual"].abs().ge(0.02) & x["volume_ratio"].ge(1.2)].copy()
        x["event_score"] = x["sector_residual"].abs() * x["volume_ratio"].clip(upper=3.0)
    elif variant == "sector_exhaustion_overnight":
        x = x[
            x["sector_residual"].abs().ge(0.02)
            & x["volume_ratio"].ge(1.2)
            & (np.sign(x["late_return"]) == -np.sign(x["sector_residual"]))
            & x["late_return"].abs().ge(0.003)
        ].copy()
        x["event_score"] = (
            x["sector_residual"].abs() * x["late_return"].abs() * x["volume_ratio"].clip(upper=3.0)
        )
    elif variant == "double_resid_reversal_overnight":
        x = x[
            x["sector_residual"].abs().ge(0.015)
            & x["market_residual"].abs().ge(0.02)
            & (np.sign(x["sector_residual"]) == np.sign(x["market_residual"]))
            & x["volume_ratio"].ge(1.2)
        ].copy()
        x["event_score"] = (
            x["sector_residual"].abs() * x["market_residual"].abs() * x["volume_ratio"].clip(upper=3.0)
        )
    elif variant == "extreme_volume_reversal_overnight":
        x = x[x["sector_residual"].abs().ge(0.015) & x["volume_ratio"].ge(1.8)].copy()
        x["event_score"] = x["sector_residual"].abs() * x["volume_ratio"].clip(upper=3.0)
    else:
        raise ValueError(variant)
    return x


def ranked_indices(group: pd.DataFrame, direction: int, maximum: int = 3) -> list[int]:
    side = group[group["sector_residual"].lt(0) if direction > 0 else group["sector_residual"].gt(0)]
    selected: list[int] = []
    sic_counts: defaultdict[str, int] = defaultdict(int)
    for row in side.sort_values(["event_score", "adv20", "ticker"], ascending=[False, False, True]).itertuples():
        sic = str(row.sic_description)
        if sic_counts[sic] >= 1:
            continue
        selected.append(row.Index)
        sic_counts[sic] += 1
        if len(selected) == maximum:
            break
    return selected


def build_trades(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    pool = candidate_pool(panel, variant)
    overnight = variant != "sector_resid_reversal_next1520"
    rows: list[pd.DataFrame] = []
    for date, group in pool.groupby("date", sort=True):
        long_indices = ranked_indices(group, 1)
        short_indices = ranked_indices(group, -1)
        matched = min(len(long_indices), len(short_indices))
        indices = long_indices[:matched] + short_indices[:matched]
        if not indices:
            continue
        day = group.loc[indices].copy()
        day["direction"] = [1] * matched + [-1] * matched
        day["target_weight"] = 0.10
        if overnight:
            day["exit_price"] = day["exit_0935"]
            day["exit_clock"] = day["exit_0935_clock"]
            day["exit_date"] = day["exit_0935_date"]
            day["scheduled_exit_clock"] = "09:35"
        else:
            day["exit_price"] = day["exit_1520_next"]
            day["exit_clock"] = day["exit_1520_next_clock"]
            day["exit_date"] = day["exit_1520_next_date"]
            day["scheduled_exit_clock"] = "15:20"
        day["unreplayable_exit"] = day["exit_price"].isna()
        day.loc[day["unreplayable_exit"], "exit_price"] = 0.0
        day.loc[day["unreplayable_exit"], "exit_clock"] = "WRITE_OFF"
        day.loc[day["unreplayable_exit"], "exit_date"] = day.loc[
            day["unreplayable_exit"], "next_date"
        ] + pd.Timedelta(days=5)
        day["exit_fallback"] = (
            day["exit_clock"].ne(day["scheduled_exit_clock"])
            | day["exit_date"].ne(day["next_date"])
        )
        day["raw_return"] = day["direction"] * (day["exit_price"] / day["entry_price_1520"] - 1.0)
        day.loc[day["unreplayable_exit"], "raw_return"] = -1.0
        day["variant"] = variant
        rows.append(day)
    return pd.concat(rows, ignore_index=True) if rows else pool.iloc[0:0].copy()


def run_scope(
    panel: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    scope: str,
    variants: list[str],
) -> dict[str, pd.DataFrame]:
    p = panel[panel["date"].between(start, end)].copy()
    sessions = sorted(p["date"].drop_duplicates())
    trades_all: list[pd.DataFrame] = []
    daily_all: list[pd.DataFrame] = []
    contrib_all: list[pd.DataFrame] = []
    summaries: list[dict[str, object]] = []
    for variant in variants:
        trades = build_trades(p, variant)
        trades["scope"] = scope
        trades_all.append(trades)
        base_daily = base_contrib = None
        stress_pnl = np.nan
        for cost in (BASE_COST_BPS, STRESS_COST_BPS):
            daily, contrib = simulate(variant, trades, sessions, cost, scope)
            daily_all.append(daily)
            contrib_all.append(contrib)
            if cost == BASE_COST_BPS:
                base_daily, base_contrib = daily, contrib
            else:
                stress_pnl = metrics(daily)["pnl"]
        summaries.append({
            "variant": variant,
            "stressPnl": stress_pnl,
            **metrics(base_daily),
            **concentration(base_contrib),
        })
    return {
        "summary": pd.DataFrame(summaries),
        "trades": pd.concat(trades_all, ignore_index=True),
        "daily": pd.concat(daily_all, ignore_index=True),
        "contrib": pd.concat(contrib_all, ignore_index=True),
    }


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or len(prereg["variants"]) != 5:
        raise RuntimeError("Invalid preregistration")
    feature_manifest = json.loads(FEATURE_MANIFEST.read_text(encoding="ascii"))
    if feature_manifest["output_hash"] != sha256(FEATURES) or feature_manifest["post2022_consumed"]:
        raise RuntimeError("Feature provenance failure")
    panel = pd.read_parquet(FEATURES)
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel["next_date"] = pd.to_datetime(panel["next_date"]).dt.normalize()
    panel = add_cross_sectional_features(panel)
    if panel["date"].max() > VAL_END or panel["next_date"].max() > VAL_END:
        raise RuntimeError("Post-2022 data detected")

    dev = run_scope(panel, START, DEV_END, "development", VARIANTS)
    development = dev["summary"].copy()
    development["developmentPass"] = (
        development["activeDays"].ge(200)
        & development["tradeLegs"].ge(600)
        & development["cagr"].ge(0.05)
        & development["sharpe"].ge(0.8)
        & development["ddPct"].ge(-0.12)
        & development["positiveYears"].ge(3)
        & development["grossEdgeBpsPerActiveDay"].ge(10.0)
        & development["stressPnl"].gt(0)
        & development["top10PositiveShare"].le(0.50)
    )
    development = development.sort_values(
        ["developmentPass", "sharpe", "cagr", "variant"], ascending=[False, False, False, True]
    )
    passing = development[development["developmentPass"]]
    validation = pd.DataFrame()
    outputs = dev
    if passing.empty:
        selection = {
            "status": "KILL_NO_DEVELOPMENT_PASS",
            "selectedVariant": None,
            "validationOpened": False,
            "productionPassAllowed": False,
        }
    else:
        selected = str(passing.iloc[0]["variant"])
        val = run_scope(panel, VAL_START, VAL_END, "validation", [selected])
        validation = val["summary"].copy()
        validation["validationPass"] = (
            validation["activeDays"].ge(50)
            & validation["pnl"].gt(0)
            & validation["sharpe"].ge(0.5)
            & validation["ddPct"].ge(-0.10)
            & validation["stressPnl"].gt(0)
            & validation["top10PositiveShare"].le(0.60)
        )
        passed = bool(validation.iloc[0]["validationPass"])
        selection = {
            "status": "CONTINUE_AUDIT" if passed else "KILL_VALIDATION_FAIL",
            "selectedVariant": selected,
            "validationOpened": True,
            "validationPass": passed,
            "productionPassAllowed": False,
        }
        outputs = {
            key: pd.concat([dev[key], val[key]], ignore_index=True) if key != "summary" else dev[key]
            for key in ("summary", "trades", "daily", "contrib")
        }

    daily = outputs["daily"]
    contrib = outputs["contrib"]
    yearly = daily.assign(year=daily["date"].dt.year).groupby(
        ["variant", "scope", "cost_bps", "year"], as_index=False
    ).agg(
        pnl=("daily_pnl", "sum"),
        grossPnl=("gross_pnl", "sum"),
        tradingCost=("trading_cost", "sum"),
        borrowCost=("borrow_cost", "sum"),
        activeDays=("trade_legs", lambda values: int(values.gt(0).sum())),
        tradeLegs=("trade_legs", "sum"),
        minDdDollar=("dd_dollar", "min"),
        minDdPct=("dd_pct", "min"),
    )
    qa: list[dict[str, object]] = []
    for (variant, scope, cost), group in daily.groupby(["variant", "scope", "cost_bps"]):
        match = contrib[
            contrib["variant"].eq(variant) & contrib["scope"].eq(scope) & contrib["cost_bps"].eq(cost)
        ]
        ending = float(group.sort_values("date").iloc[-1]["equity"] - 100_000.0)
        qa.append({
            "variant": variant,
            "scope": scope,
            "cost_bps": cost,
            "dailyPnl": group["daily_pnl"].sum(),
            "endingDelta": ending,
            "contribPnl": match["net_pnl"].sum(),
            "dailyMinusEnding": group["daily_pnl"].sum() - ending,
            "dailyMinusContrib": group["daily_pnl"].sum() - match["net_pnl"].sum(),
        })

    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False)
    validation.to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    outputs["trades"].to_csv(f"{PREFIX}_TRADES.csv", index=False)
    daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    pd.DataFrame(qa).to_csv(f"{PREFIX}_QA.csv", index=False)
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"),
        "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG),
        "preregistrationHash": sha256(PREREG),
        "inputs": {
            str(FEATURES).replace("\\", "/"): sha256(FEATURES),
            str(FEATURE_MANIFEST).replace("\\", "/"): sha256(FEATURE_MANIFEST),
            str(SIMULATOR).replace("\\", "/"): sha256(SIMULATOR),
        },
        "selection": selection,
        "development": [str(START.date()), str(DEV_END.date())],
        "validation": [str(VAL_START.date()), str(VAL_END.date())] if selection["validationOpened"] else None,
        "oldManual62Used": False,
        "post2022Consumed": False,
        "productionPassAllowed": False,
        "causality": "same-date PIT SIC medians and features known at exact 15:20 entry; fixed next-session exits",
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False))
    print(validation.to_string(index=False))
    print(json.dumps(selection, indent=2))
    print(pd.DataFrame(qa).to_string(index=False))


if __name__ == "__main__":
    main()
