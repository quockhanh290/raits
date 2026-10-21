from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_PIT_1520_CONTINUATION_PREREG_2026-10-02.json")
FEATURES = Path("raits/data/cache/stocks_pit_1520_continuation_2018_2022/causal_features_pre1520.parquet")
FEATURE_MANIFEST = FEATURES.with_name("causal_features_pre1520_manifest.json")
PREFIX = "STOCKS_PIT_1520_CONTINUATION_2026-10-02"
START, DEV_END = pd.Timestamp("2018-03-29"), pd.Timestamp("2021-12-31")
VAL_START, VAL_END = pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-30")
INITIAL_EQUITY = 100_000.0
BASE_COST_BPS = 4.0
STRESS_COST_BPS = 8.0
SHORT_BORROW_ANNUAL = 0.01
VARIANTS = [
    "cs_momo_ls_overnight",
    "cs_momo_ls_next1520",
    "volume_confirmed_ls_next1520",
    "persistent_late_ls_next1520",
    "pullback_resume_long_next1520",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def candidate_pool(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    x = panel[
        panel["entry_price_1520"].gt(0)
        & panel["signal_close_1520"].ge(5.0)
        & panel["signal_dollar"].ge(1_000_000.0)
        & panel["intraday_return"].abs().ge(0.01)
    ].copy()
    if variant == "volume_confirmed_ls_next1520":
        x = x[x["volume_ratio"].ge(1.2)].copy()
        x["event_score"] = x["intraday_return"].abs() * x["volume_ratio"].clip(upper=3.0)
    elif variant == "persistent_late_ls_next1520":
        x = x[x["persistent_direction"]].copy()
        x["event_score"] = x["intraday_return"].abs() * x["late_return"].abs()
    elif variant == "pullback_resume_long_next1520":
        x = x[x["fixed_pullback_resume"] & x["pullback_direction"].eq("LONG")].copy()
        x["event_score"] = x["intraday_return"] * x["resume_volume_ratio"].clip(upper=5.0)
    elif variant in ("cs_momo_ls_overnight", "cs_momo_ls_next1520"):
        x["event_score"] = x["intraday_return"].abs()
    else:
        raise ValueError(variant)
    return x


def ranked_indices(group: pd.DataFrame, direction: int, maximum: int) -> list[int]:
    side = group[group["intraday_return"].gt(0) if direction > 0 else group["intraday_return"].lt(0)]
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
    rows: list[pd.DataFrame] = []
    long_only = variant == "pullback_resume_long_next1520"
    overnight = variant == "cs_momo_ls_overnight"
    for date, group in pool.groupby("date", sort=True):
        long_indices = ranked_indices(group, 1, 3)
        if long_only:
            indices = long_indices
            directions = [1] * len(indices)
            weight = 0.20
        else:
            short_indices = ranked_indices(group, -1, 3)
            matched = min(len(long_indices), len(short_indices))
            indices = long_indices[:matched] + short_indices[:matched]
            directions = [1] * matched + [-1] * matched
            weight = 0.10
        if not indices:
            continue
        day = group.loc[indices].copy()
        day["direction"] = directions
        day["target_weight"] = weight
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


def simulate(
    variant: str,
    trades: pd.DataFrame,
    sessions: list[pd.Timestamp],
    cost_bps: float,
    scope: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_date = {date: group for date, group in trades.groupby("date", sort=True)}
    equity = peak = INITIAL_EQUITY
    daily_rows: list[dict[str, object]] = []
    contrib_rows: list[dict[str, object]] = []
    for date in sessions:
        day = by_date.get(date)
        gross_pnl = trading_cost = borrow_cost = gross = max_adv = 0.0
        start = equity
        if day is not None and not day.empty:
            gross = float(day["target_weight"].sum())
            entry_notionals = start * day["target_weight"].astype(float)
            max_adv = float((entry_notionals / day["adv20"]).max())
            if max_adv > 0.01 + 1e-12:
                raise RuntimeError(f"ADV cap breach: {variant} {date.date()} {max_adv}")
            signed_returns = day["raw_return"].astype(float)
            gross_legs = entry_notionals * signed_returns
            exit_notionals = entry_notionals * day["exit_price"].astype(float) / day["entry_price_1520"].astype(float)
            leg_trading_cost = (entry_notionals + exit_notionals) * cost_bps / 10_000.0
            hold_days = (pd.to_datetime(day["exit_date"]) - pd.to_datetime(day["date"])).dt.days.clip(lower=1)
            leg_borrow = np.where(
                day["direction"].lt(0), entry_notionals * SHORT_BORROW_ANNUAL * hold_days / 365.0, 0.0
            )
            gross_pnl = float(gross_legs.sum())
            trading_cost = float(leg_trading_cost.sum())
            borrow_cost = float(np.sum(leg_borrow))
            for i, (_, trade) in enumerate(day.iterrows()):
                net = float(gross_legs.iloc[i] - leg_trading_cost.iloc[i] - leg_borrow[i])
                contrib_rows.append({
                    "variant": variant,
                    "scope": scope,
                    "cost_bps": cost_bps,
                    "date": date,
                    "ticker": trade["ticker"],
                    "direction": int(trade["direction"]),
                    "gross_pnl": float(gross_legs.iloc[i]),
                    "trading_cost": float(leg_trading_cost.iloc[i]),
                    "borrow_cost": float(leg_borrow[i]),
                    "net_pnl": net,
                })
            equity += gross_pnl - trading_cost - borrow_cost
        peak = max(peak, equity)
        daily_rows.append({
            "variant": variant,
            "scope": scope,
            "cost_bps": cost_bps,
            "date": date,
            "starting_equity": start,
            "equity": equity,
            "daily_pnl": gross_pnl - trading_cost - borrow_cost,
            "gross_pnl": gross_pnl,
            "trading_cost": trading_cost,
            "borrow_cost": borrow_cost,
            "gross": gross,
            "trade_legs": 0 if day is None else len(day),
            "max_order_adv_fraction": max_adv,
            "fallback_exit_legs": 0 if day is None else int(day["exit_fallback"].sum()),
            "dd_dollar": equity - peak,
            "dd_pct": equity / peak - 1.0,
        })
    return pd.DataFrame(daily_rows), pd.DataFrame(contrib_rows)


def metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = daily["daily_pnl"] / daily["starting_equity"]
    years = max((daily["date"].max() - daily["date"].min()).days / 365.25, 1e-9)
    yearly = (1.0 + returns).groupby(daily["date"].dt.year).prod() - 1.0
    active = daily["trade_legs"].gt(0)
    return {
        "pnl": float(daily["daily_pnl"].sum()),
        "grossPnl": float(daily["gross_pnl"].sum()),
        "cagr": float((daily.iloc[-1]["equity"] / INITIAL_EQUITY) ** (1.0 / years) - 1.0),
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else np.nan,
        "ddDollar": float(daily["dd_dollar"].min()),
        "ddPct": float(daily["dd_pct"].min()),
        "positiveYears": int(yearly.gt(0).sum()),
        "activeDays": int(active.sum()),
        "tradeLegs": int(daily["trade_legs"].sum()),
        "tradingCost": float(daily["trading_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()),
        "maxOrderAdvFraction": float(daily["max_order_adv_fraction"].max()),
        "fallbackExitLegs": int(daily["fallback_exit_legs"].sum()),
        "grossEdgeBpsPerActiveDay": float(
            (daily.loc[active, "gross_pnl"] / daily.loc[active, "starting_equity"]).mean() * 10_000.0
        ) if active.any() else np.nan,
    }


def concentration(contrib: pd.DataFrame) -> dict[str, float | str]:
    by = contrib.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
    positive = by[by.gt(0)]
    total = float(positive.sum())
    row: dict[str, float | str] = {
        "tickers": len(by),
        "topTicker": by.index[0] if len(by) else "",
        "effectiveTickerCount": float(total**2 / positive.pow(2).sum()) if total > 0 else 0.0,
    }
    for n in (1, 3, 5, 10):
        row[f"top{n}PositiveShare"] = float(positive.head(n).sum() / total) if total > 0 else np.nan
    return row


def run_scope(
    panel: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    scope: str,
    variants: list[str],
) -> dict[str, pd.DataFrame]:
    p = panel[panel["date"].between(start, end)].copy()
    sessions = sorted(p["date"].drop_duplicates())
    trade_frames: list[pd.DataFrame] = []
    daily_frames: list[pd.DataFrame] = []
    contrib_frames: list[pd.DataFrame] = []
    summaries: list[dict[str, object]] = []
    for variant in variants:
        trades = build_trades(p, variant)
        trades["scope"] = scope
        trade_frames.append(trades)
        base_daily = base_contrib = None
        stress_pnl = np.nan
        for cost in (BASE_COST_BPS, STRESS_COST_BPS):
            daily, contrib = simulate(variant, trades, sessions, cost, scope)
            daily_frames.append(daily)
            contrib_frames.append(contrib)
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
        "trades": pd.concat(trade_frames, ignore_index=True),
        "daily": pd.concat(daily_frames, ignore_index=True),
        "contrib": pd.concat(contrib_frames, ignore_index=True),
    }


def benchmark(panel: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    x = panel[panel["date"].between(start, end) & panel["exit_1520_next"].notna()].copy()
    x["return"] = x["exit_1520_next"] / x["entry_price_1520"] - 1.0
    equal_weight = x.groupby("date", as_index=False)["return"].mean().assign(benchmark="equal_weight_eligible")
    spy = x[x["ticker"].eq("SPY")][["date", "return"]].assign(benchmark="SPY")
    rows = pd.concat([equal_weight, spy], ignore_index=True)
    return rows.sort_values(["benchmark", "date"])


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or len(prereg["variants"]) != 5:
        raise RuntimeError("Invalid preregistration")
    manifest = json.loads(FEATURE_MANIFEST.read_text(encoding="ascii"))
    if manifest["output_hash"] != sha256(FEATURES) or manifest["post2022_consumed"]:
        raise RuntimeError("Feature provenance failure")
    panel = pd.read_parquet(FEATURES)
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel["next_date"] = pd.to_datetime(panel["next_date"]).dt.normalize()
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
        ending = float(group.sort_values("date").iloc[-1]["equity"] - INITIAL_EQUITY)
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
    benchmark(panel, START, DEV_END).to_csv(f"{PREFIX}_BENCHMARK_DAILY.csv", index=False)
    replay_manifest = {
        "script": str(Path(__file__)).replace("\\", "/"),
        "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG),
        "preregistrationHash": sha256(PREREG),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in (FEATURES, FEATURE_MANIFEST)},
        "selection": selection,
        "development": [str(START.date()), str(DEV_END.date())],
        "validation": [str(VAL_START.date()), str(VAL_END.date())] if selection["validationOpened"] else None,
        "oldManual62Used": False,
        "post2022Consumed": False,
        "productionPassAllowed": False,
        "causality": "five-minute bars timestamped before 15:20; exact 15:20 entry; pre-registered next-session exit",
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(replay_manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False))
    print(validation.to_string(index=False))
    print(json.dumps(selection, indent=2))
    print(pd.DataFrame(qa).to_string(index=False))


if __name__ == "__main__":
    main()
