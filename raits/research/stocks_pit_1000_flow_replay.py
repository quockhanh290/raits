from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_PIT_1000_FLOW_PREREG_2026-10-02.json")
PLAN = Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.csv")
PLAN_MANIFEST = Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.json")
EXACT = Path("STOCKS_PIT_1000_FLOW_EXACT_CLOCK_ROWS_2026-10-02.csv")
FEATURES = Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022/causal_features_pre1000.parquet")
FEATURE_MANIFEST = FEATURES.with_name("causal_features_pre1000_manifest.json")
DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
PREFIX = "STOCKS_PIT_1000_FLOW_2026-10-02"
START, DEV_END = pd.Timestamp("2018-03-29"), pd.Timestamp("2021-12-31")
VAL_START, VAL_END = pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-30")
INITIAL_EQUITY = 100_000.0
BASE_COST_BPS = 4.0
STRESS_COST_BPS = 8.0
VARIANTS = ["yday_reclaim_price", "yday_reclaim_flow", "yday_reclaim_acceleration",
            "gapup_confirm_price", "gapup_confirm_flow"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_panel() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    plan = pd.read_csv(PLAN, parse_dates=["date"])
    features = pd.read_parquet(FEATURES)
    features["date"] = pd.to_datetime(features["date"]).dt.normalize()
    exact = pd.read_csv(EXACT, parse_dates=["date"])
    wide = exact.pivot(index=["date", "ticker"], columns="clock", values=["open", "close"])
    wide.columns = [f"{field}_{clock.replace(':', '')}" for field, clock in wide.columns]
    wide = wide.reset_index()[["date", "ticker", "open_1005", "close_1555", "open_1600"]]
    panel = plan.merge(features, on=["date", "ticker"], how="inner", validate="one_to_one")
    panel = panel.merge(wide, on=["date", "ticker"], how="left", validate="one_to_one")
    panel["reclaim_1000"] = panel["signal_price_1000"] / panel["open_0930"] - 1.0
    if len(panel) != 28_225 or panel["max_signal_sip_timestamp"].ge(panel["signal_end_ns"]).any():
        raise RuntimeError("Coverage or feature-clock failure")
    daily = pd.read_pickle(DAILY, columns=None) if False else pd.read_pickle(DAILY)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    sessions = sorted(daily.loc[daily["date"].between(START, VAL_END), "date"].drop_duplicates())
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True), sessions


def candidates(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    x = panel[panel["signal_complete"] & panel["entry_complete"] & panel["signal_trades"].ge(100)
              & panel["signal_dollar"].ge(1_000_000.0)].copy()
    if variant.startswith("yday_"):
        x = x[x["yday_precandidate"] & x["reclaim_1000"].gt(0)].copy()
        score = -x["prev_dayret"]
        if variant == "yday_reclaim_flow":
            x = x[x["flow_imbalance_30m"].ge(0.05) & x["flow_imbalance_last5"].ge(0.05)].copy()
            score = -x["prev_dayret"] * (1.0 + x["flow_imbalance_30m"] + x["flow_imbalance_last5"])
        elif variant == "yday_reclaim_acceleration":
            x = x[x["flow_acceleration"].ge(0.25) & x["flow_imbalance_last5"].gt(0)].copy()
            score = -x["prev_dayret"] * (1.0 + x["flow_acceleration"])
    elif variant.startswith("gapup_"):
        x = x[x["gapup_precandidate"] & x["reclaim_1000"].gt(0)].copy()
        score = x["gap"] * (1.0 + x["reclaim_1000"].clip(lower=0, upper=0.10) * 10.0)
        if variant == "gapup_confirm_flow":
            x = x[x["flow_imbalance_30m"].ge(0.05) & x["flow_imbalance_last5"].ge(0.05)].copy()
            score = score * (1.0 + x["flow_imbalance_30m"] + x["flow_imbalance_last5"])
    else:
        raise ValueError(variant)
    x["event_score"] = score
    return x


def build_trades(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    pool = candidates(panel, variant)
    rows = []
    for date, group in pool.groupby("date", sort=True):
        selected, sic_counts = [], defaultdict(int)
        for row in group.sort_values(["event_score", "adv20", "ticker"], ascending=[False, False, True]).itertuples():
            sic = str(row.sic_description)
            if sic_counts[sic] >= 1:
                continue
            selected.append(row.Index); sic_counts[sic] += 1
            if len(selected) == 3:
                break
        if not selected:
            continue
        day = group.loc[selected].copy()
        day["entry_price"] = day["open_1005"]
        day["exit_price"] = day["close_1555"]
        fallback = day["exit_price"].isna() & day["open_1600"].notna()
        day.loc[fallback, "exit_price"] = day.loc[fallback, "open_1600"]
        day["exit_fallback"] = fallback
        if day["exit_price"].isna().any():
            raise RuntimeError(f"No same-session exit after selection: {variant} {date.date()}")
        day["target_weight"] = 0.20
        day["raw_return"] = day["exit_price"] / day["entry_price"] - 1.0
        day["variant"] = variant
        rows.append(day)
    return pd.concat(rows, ignore_index=True) if rows else pool.iloc[0:0].copy()


def simulate(variant: str, trades: pd.DataFrame, sessions: list[pd.Timestamp], cost_bps: float, scope: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_date = {date: group for date, group in trades.groupby("date", sort=True)}
    equity, peak = INITIAL_EQUITY, INITIAL_EQUITY
    daily_rows, contrib_rows = [], []
    for date in sessions:
        day = by_date.get(date)
        gross_pnl = cost = gross = max_adv = 0.0
        if day is not None and not day.empty:
            start = equity
            gross = float(day["target_weight"].sum())
            max_adv = float((start * day["target_weight"] / day["adv20"]).max())
            if max_adv > 0.01 + 1e-12:
                raise RuntimeError("ADV cap breach")
            gross_pnl = float((start * day["target_weight"] * day["raw_return"]).sum())
            cost = start * gross * 2.0 * cost_bps / 10_000.0
            allocation = day["target_weight"] / gross * cost
            for (_, trade), allocated in zip(day.iterrows(), allocation):
                leg = start * trade["target_weight"] * trade["raw_return"]
                contrib_rows.append({"variant": variant, "scope": scope, "cost_bps": cost_bps, "date": date,
                    "ticker": trade["ticker"], "gross_pnl": leg, "cost": allocated, "net_pnl": leg - allocated})
            equity += gross_pnl - cost
        peak = max(peak, equity)
        daily_rows.append({"variant": variant, "scope": scope, "cost_bps": cost_bps, "date": date,
            "equity": equity, "daily_pnl": gross_pnl - cost, "gross_pnl": gross_pnl, "trading_cost": cost,
            "gross": gross, "trade_legs": 0 if day is None else len(day), "max_order_adv_fraction": max_adv,
            "fallback_exit_legs": 0 if day is None else int(day["exit_fallback"].sum()),
            "dd_dollar": equity - peak, "dd_pct": equity / peak - 1.0})
    return pd.DataFrame(daily_rows), pd.DataFrame(contrib_rows)


def metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = daily["daily_pnl"] / (daily["equity"] - daily["daily_pnl"])
    years = max((daily["date"].max() - daily["date"].min()).days / 365.25, 1e-9)
    yearly = (1 + returns).groupby(daily["date"].dt.year).prod() - 1
    active = daily["trade_legs"].gt(0)
    return {"pnl": float(daily["daily_pnl"].sum()), "grossPnl": float(daily["gross_pnl"].sum()),
        "cagr": float((daily.iloc[-1]["equity"] / INITIAL_EQUITY) ** (1 / years) - 1),
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else np.nan,
        "ddDollar": float(daily["dd_dollar"].min()), "ddPct": float(daily["dd_pct"].min()),
        "positiveYears": int(yearly.gt(0).sum()), "activeDays": int(active.sum()),
        "tradeLegs": int(daily["trade_legs"].sum()), "tradingCost": float(daily["trading_cost"].sum()),
        "maxOrderAdvFraction": float(daily["max_order_adv_fraction"].max()),
        "fallbackExitLegs": int(daily["fallback_exit_legs"].sum())}


def concentration(contrib: pd.DataFrame) -> dict[str, float | str]:
    by = contrib.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
    positive = by[by.gt(0)]; total = float(positive.sum())
    row: dict[str, float | str] = {"tickers": len(by), "topTicker": by.index[0] if len(by) else "",
        "effectiveTickerCount": float(total**2 / positive.pow(2).sum()) if total > 0 else 0.0}
    for n in (1, 3, 5, 10):
        row[f"top{n}PositiveShare"] = float(positive.head(n).sum() / total) if total > 0 else np.nan
    return row


def run_scope(panel: pd.DataFrame, sessions: list[pd.Timestamp], start: pd.Timestamp, end: pd.Timestamp,
              scope: str, variants: list[str]) -> dict[str, pd.DataFrame]:
    p = panel[panel["date"].between(start, end)].copy(); s = [d for d in sessions if start <= d <= end]
    trades_all, daily_all, contrib_all, summaries = [], [], [], []
    for variant in variants:
        trades = build_trades(p, variant); trades["scope"] = scope; trades_all.append(trades)
        base_daily = base_contrib = None; stress_pnl = np.nan
        for cost in (BASE_COST_BPS, STRESS_COST_BPS):
            daily, contrib = simulate(variant, trades, s, cost, scope)
            daily_all.append(daily); contrib_all.append(contrib)
            if cost == BASE_COST_BPS: base_daily, base_contrib = daily, contrib
            else: stress_pnl = metrics(daily)["pnl"]
        result = metrics(base_daily)
        edge = ((trades["target_weight"] * trades["raw_return"]).groupby(trades["date"]).sum().mean() * 10_000
                if len(trades) else np.nan)
        summaries.append({"variant": variant, "grossEdgeBpsPerActiveDay": edge, "stressPnl": stress_pnl,
                          **result, **concentration(base_contrib)})
    return {"summary": pd.DataFrame(summaries), "trades": pd.concat(trades_all, ignore_index=True),
        "daily": pd.concat(daily_all, ignore_index=True), "contrib": pd.concat(contrib_all, ignore_index=True)}


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or prereg["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration mismatch")
    panel, sessions = load_panel()
    dev = run_scope(panel, sessions, START, DEV_END, "development", VARIANTS)
    development = dev["summary"].copy()
    development["developmentPass"] = (development["activeDays"].ge(100) & development["tradeLegs"].ge(300)
        & development["cagr"].ge(0.05) & development["sharpe"].ge(0.8) & development["ddPct"].ge(-0.12)
        & development["positiveYears"].ge(3) & development["grossEdgeBpsPerActiveDay"].ge(10.0)
        & development["stressPnl"].gt(0) & development["top10PositiveShare"].le(0.50))
    development = development.sort_values(["developmentPass", "sharpe", "cagr", "variant"], ascending=[False, False, False, True])
    passing = development[development["developmentPass"]]
    validation = pd.DataFrame(); outputs = dev
    if passing.empty:
        selection = {"status": "KILL_NO_DEVELOPMENT_PASS", "selectedVariant": None, "validationOpened": False, "productionPassAllowed": False}
    else:
        selected = str(passing.iloc[0]["variant"])
        val = run_scope(panel, sessions, VAL_START, VAL_END, "validation", [selected])
        validation = val["summary"].copy()
        validation["validationPass"] = (validation["activeDays"].ge(20) & validation["pnl"].gt(0)
            & validation["sharpe"].ge(0.5) & validation["ddPct"].ge(-0.10) & validation["stressPnl"].gt(0)
            & validation["top10PositiveShare"].le(0.60))
        passed = bool(validation.iloc[0]["validationPass"])
        selection = {"status": "CONTINUE_AUDIT" if passed else "KILL_VALIDATION_FAIL", "selectedVariant": selected,
                     "validationOpened": True, "validationPass": passed, "productionPassAllowed": False}
        outputs = {key: pd.concat([dev[key], val[key]], ignore_index=True) if key != "summary" else dev[key]
                   for key in ("summary", "trades", "daily", "contrib")}
    daily, contrib = outputs["daily"], outputs["contrib"]
    yearly = daily.assign(year=daily["date"].dt.year).groupby(["variant", "scope", "cost_bps", "year"], as_index=False).agg(
        pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"), tradingCost=("trading_cost", "sum"),
        activeDays=("trade_legs", lambda x: int(x.gt(0).sum())), tradeLegs=("trade_legs", "sum"))
    qa = []
    for (variant, scope, cost), group in daily.groupby(["variant", "scope", "cost_bps"]):
        match = contrib[(contrib["variant"].eq(variant)) & (contrib["scope"].eq(scope)) & (contrib["cost_bps"].eq(cost))]
        ending = float(group.sort_values("date").iloc[-1]["equity"] - INITIAL_EQUITY)
        qa.append({"variant": variant, "scope": scope, "cost_bps": cost, "dailyPnl": group["daily_pnl"].sum(),
                   "endingDelta": ending, "contribPnl": match["net_pnl"].sum(),
                   "dailyMinusEnding": group["daily_pnl"].sum() - ending,
                   "dailyMinusContrib": group["daily_pnl"].sum() - match["net_pnl"].sum()})
    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False); validation.to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    outputs["trades"].to_csv(f"{PREFIX}_TRADES.csv", index=False); daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False); yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    pd.DataFrame(qa).to_csv(f"{PREFIX}_QA.csv", index=False)
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "inputs": {str(p).replace("\\", "/"): sha256(p) for p in (PLAN, PLAN_MANIFEST, EXACT, FEATURES, FEATURE_MANIFEST)},
        "selection": selection, "development": [str(START.date()), str(DEV_END.date())],
        "validation": [str(VAL_START.date()), str(VAL_END.date())] if selection["validationOpened"] else None,
        "oldManual62Used": False, "post2022Consumed": False, "productionPassAllowed": False,
        "causality": "SIP trades strictly before 10:00; exact 10:05 entry; exact 15:55 close with post-selection 16:00-open fallback"}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False)); print(validation.to_string(index=False)); print(json.dumps(selection, indent=2)); print(pd.DataFrame(qa).to_string(index=False))


if __name__ == "__main__":
    main()
