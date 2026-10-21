from __future__ import annotations

from pathlib import Path

import json

import numpy as np
import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as base
import stocks_pit_full_lead_deployment_policy_audit as deployment


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_CAPACITY_MARGIN_AUDIT_2026-09-17"
FINAL_EVENTS = Path("STOCKS_PIT_FULL_LEAD_MISSING_PRICE_REPLAY_2026-09-17_EVENT_LEDGER.csv")
PIT_FILTER = deployment.PIT_FILTER
TRADE_OUT = Path(f"{OUT_PREFIX}_TRADE_AUDIT.csv")
CAPACITY_OUT = Path(f"{OUT_PREFIX}_CAPACITY_SUMMARY.csv")
MARGIN_DAILY_OUT = Path(f"{OUT_PREFIX}_MARGIN_DAILY.csv")
MARGIN_OUT = Path(f"{OUT_PREFIX}_MARGIN_SUMMARY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

FINAL_SCENARIO = "raw_asof5_namecap3_missingfs"
NAME_CAP = 0.03
GROSS_CAP = 3.0
ADV_LIMIT = 0.01
EXIT_ADV_MAX_AGE_DAYS = 10
MARGIN_MODELS = {
    "regt_initial": {"spy": 0.50, "long": 0.50, "short": 0.50},
    "regt_maintenance": {"spy": 0.25, "long": 0.25, "short": 0.30},
    "pm_house": {"spy": 0.15, "long": 0.25, "short": 0.30},
    "pm_stressed": {"spy": 0.20, "long": 0.30, "short": 0.40},
}
MARGIN_BUFFER = 1.25


def capped_targets(dates: list[pd.Timestamp]) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = deployment.target_schedule(dates)
    rows = []
    margin_rows = []
    prior = pd.Series(dtype=float)
    for date, group in raw.groupby("date", sort=True):
        target = group.set_index("ticker")["targetWeight"].astype(float)
        spy = float(group["spyTarget"].iloc[0])
        scale = 1.0
        if not target.empty and float(target.abs().max()) > NAME_CAP:
            scale = min(scale, NAME_CAP / float(target.abs().max()))
        target *= scale
        allowed_satellite = max(GROSS_CAP - abs(spy), 0.0)
        satellite_gross = float(target.abs().sum())
        if satellite_gross > allowed_satellite and satellite_gross > 0.0:
            target *= allowed_satellite / satellite_gross
            scale *= allowed_satellite / satellite_gross
        names = prior.index.union(target.index)
        current = target.reindex(names).fillna(0.0)
        previous = prior.reindex(names).fillna(0.0)
        delta = current - previous
        for ticker in names:
            old = float(previous[ticker])
            new = float(current[ticker])
            change = float(delta[ticker])
            if abs(change) <= 1e-15:
                continue
            risk_increasing = (old == 0.0 and new != 0.0) or (np.sign(old) != np.sign(new) and new != 0.0) or (np.sign(old) == np.sign(new) and abs(new) > abs(old))
            rows.append({"date": date, "ticker": ticker, "priorWeight": old, "targetWeight": new, "tradeWeight": change, "riskIncreasing": risk_increasing, "targetScale": scale})
        margin_rows.append({
            "date": date,
            "spyGross": abs(spy),
            "satelliteLongGross": float(target[target > 0.0].sum()),
            "satelliteShortGross": float(target[target < 0.0].abs().sum()),
            "targetGross": abs(spy) + float(target.abs().sum()),
            "targetScale": scale,
        })
        prior = target[target.ne(0.0)]
    return pd.DataFrame(rows), pd.DataFrame(margin_rows)


def eligible_liquidity_panel(tickers: list[str], dates: list[pd.Timestamp]) -> pd.DataFrame:
    panel = pd.read_parquet(
        PIT_FILTER,
        columns=["date", "ticker", "adv20", "liquidity_metric_source"],
        filters=[("ticker", "in", tickers), ("date", ">=", min(dates).date()), ("date", "<=", max(dates).date()), ("eligible_final", "==", True)],
    )
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel["ticker"] = panel["ticker"].astype(str).str.upper()
    return panel.groupby(["date", "ticker"], as_index=False).agg(
        eligibleAdv=("adv20", "min"),
        fallback=("liquidity_metric_source", lambda s: bool(s.eq("ticker_fallback").any())),
    )


def exit_only_liquidity(missing: pd.DataFrame) -> pd.DataFrame:
    if missing.empty:
        return pd.DataFrame(columns=["date", "ticker", "anyAdv"])
    tickers = sorted(missing["ticker"].unique())
    panel = pd.read_parquet(
        PIT_FILTER,
        columns=["date", "ticker", "adv20", "ticker_adv20"],
        filters=[("ticker", "in", tickers), ("date", ">=", missing["date"].min().date()), ("date", "<=", missing["date"].max().date())],
    )
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel["ticker"] = panel["ticker"].astype(str).str.upper()
    wanted = pd.MultiIndex.from_frame(missing[["date", "ticker"]].drop_duplicates())
    panel = panel[pd.MultiIndex.from_frame(panel[["date", "ticker"]]).isin(wanted)].copy()
    panel["anyAdv"] = panel[["adv20", "ticker_adv20"]].min(axis=1, skipna=True)
    return panel.groupby(["date", "ticker"], as_index=False)["anyAdv"].min()


def main() -> None:
    events = pd.read_csv(FINAL_EVENTS, parse_dates=["timestamp"])
    final = events[events["scenario"].eq(FINAL_SCENARIO)].copy()
    final["date"] = final["timestamp"].dt.normalize()
    equity935 = final[final["event"].eq("mark_rebalance_0935")][["date", "equity"]]
    dates = sorted(equity935["date"].unique())
    trades, margin_daily = capped_targets(dates)
    trades["ticker"] = trades["ticker"].astype(str).str.upper()
    panel = eligible_liquidity_panel(sorted(trades["ticker"].unique()), dates)
    trades = trades.merge(panel, on=["date", "ticker"], how="left", validate="many_to_one")
    exits = exit_only_liquidity(trades[trades["eligibleAdv"].isna()][["date", "ticker"]])
    trades = trades.merge(exits, on=["date", "ticker"], how="left", validate="many_to_one")

    history = panel[panel["eligibleAdv"].notna()][["date", "ticker", "eligibleAdv"]].rename(columns={"date": "eligibleDate"}).sort_values(["eligibleDate", "ticker"])
    left2 = trades[["date", "ticker"]].reset_index().sort_values(["date", "ticker"])
    prior2 = pd.merge_asof(left2, history, left_on="date", right_on="eligibleDate", by="ticker", direction="backward", allow_exact_matches=True).set_index("index")
    trades["lastEligibleDate"] = prior2["eligibleDate"]
    trades["lastEligibleAdv"] = prior2["eligibleAdv"]
    trades["advAgeDays"] = (trades["date"] - trades["lastEligibleDate"]).dt.days

    trades["capacityAdv"] = trades["eligibleAdv"]
    reduction = ~trades["riskIncreasing"]
    use_any = reduction & trades["capacityAdv"].isna() & trades["anyAdv"].notna()
    trades.loc[use_any, "capacityAdv"] = trades.loc[use_any, "anyAdv"]
    use_history = reduction & trades["capacityAdv"].isna() & trades["lastEligibleAdv"].notna() & trades["advAgeDays"].le(EXIT_ADV_MAX_AGE_DAYS)
    trades.loc[use_history, "capacityAdv"] = trades.loc[use_history, "lastEligibleAdv"]
    trades["advSource"] = np.select(
        [trades["eligibleAdv"].notna(), use_any, use_history],
        ["current_eligible", "current_exit_only", "recent_eligible_exit"],
        default="unresolved",
    )
    trades["policyAction"] = np.where(
        trades["riskIncreasing"] & trades["eligibleAdv"].isna(),
        "BLOCK_RISK_INCREASE",
        np.where(trades["capacityAdv"].isna(), "EXIT_WITHOUT_ADV_ESTIMATE", "ALLOW"),
    )
    trades = trades.merge(equity935, on="date", how="left", validate="many_to_one")
    trades["tradeNotional"] = trades["tradeWeight"].abs() * trades["equity"]
    trades["advParticipation"] = trades["tradeNotional"] / trades["capacityAdv"]
    trades.to_csv(TRADE_OUT, index=False)

    fallback_trade_rows = int(trades["fallback"].astype("boolean").fillna(False).sum())
    capacity_summary = [
        {"check": "trade_rows", "value": len(trades), "limit": np.nan, "status": "INFO"},
        {"check": "risk_increase_rows_missing_current_eligible_adv", "value": int(((trades["riskIncreasing"]) & trades["eligibleAdv"].isna()).sum()), "limit": 0, "status": "FAIL" if ((trades["riskIncreasing"]) & trades["eligibleAdv"].isna()).any() else "PASS"},
        {"check": "reduction_rows_using_exit_only_adv", "value": int(use_any.sum()), "limit": 0, "status": "INFO"},
        {"check": "reduction_rows_using_recent_adv", "value": int(use_history.sum()), "limit": 0, "status": "INFO"},
        {"check": "exit_rows_without_adv_estimate", "value": int(trades["policyAction"].eq("EXIT_WITHOUT_ADV_ESTIMATE").sum()), "limit": 0, "status": "WARN" if trades["policyAction"].eq("EXIT_WITHOUT_ADV_ESTIMATE").any() else "PASS"},
        {"check": "max_trade_adv_participation", "value": float(trades["advParticipation"].max()), "limit": ADV_LIMIT, "status": "PASS" if trades["advParticipation"].max() <= ADV_LIMIT else "FAIL"},
        {"check": "ticker_fallback_trade_rows", "value": fallback_trade_rows, "limit": 0, "status": "WARN" if fallback_trade_rows else "PASS"},
    ]
    pd.DataFrame(capacity_summary).to_csv(CAPACITY_OUT, index=False)

    margin_rows = []
    for model, rates in MARGIN_MODELS.items():
        requirement = margin_daily["spyGross"] * rates["spy"] + margin_daily["satelliteLongGross"] * rates["long"] + margin_daily["satelliteShortGross"] * rates["short"]
        buffered = requirement * MARGIN_BUFFER
        margin_daily[f"{model}RequirementNav"] = requirement
        margin_daily[f"{model}BufferedNav"] = buffered
        margin_rows.append({
            "model": model,
            "buffer": MARGIN_BUFFER,
            "maxRequirementNav": float(requirement.max()),
            "maxBufferedRequirementNav": float(buffered.max()),
            "breachDays": int(buffered.gt(1.0).sum()),
            "status": "PASS" if not buffered.gt(1.0).any() else "FAIL",
        })
    margin_daily.to_csv(MARGIN_DAILY_OUT, index=False)
    pd.DataFrame(margin_rows).to_csv(MARGIN_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_capacity_margin_audit.py",
        "inputs": [str(FINAL_EVENTS), str(PIT_FILTER).replace("\\", "/"), str(base.CORE_DAILY), str(base.PAIR_EVENTS)],
        "sample_label": "Touched research 2018-2024 only. No 2025-2026 opened.",
        "capacity_policy": "Risk increases require current eligible PIT ADV20. Reductions may use current non-eligible ADV or the latest eligible ADV no more than ten calendar days old. Missing exit ADV never blocks an exit.",
        "margin_models": MARGIN_MODELS,
        "margin_buffer": MARGIN_BUFFER,
        "selection_warning": "Operational audit of the frozen target schedule; no rule or ticker re-selection.",
        "outputs": [str(TRADE_OUT), str(CAPACITY_OUT), str(MARGIN_DAILY_OUT), str(MARGIN_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(pd.DataFrame(capacity_summary).to_string(index=False), flush=True)
    print(pd.DataFrame(margin_rows).to_string(index=False), flush=True)
    print("WROTE", TRADE_OUT, CAPACITY_OUT, MARGIN_DAILY_OUT, MARGIN_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
