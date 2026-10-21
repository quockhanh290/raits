from __future__ import annotations

from pathlib import Path

import hashlib
import json

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as base
import stocks_pit_full_lead_crisis_eventtime_audit as crisis


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_DEPLOYMENT_POLICY_AUDIT_2026-09-17"
PIT_FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)
EVENT_LEDGER = Path("STOCKS_PIT_FULL_LEAD_CRISIS_EVENTTIME_AUDIT_2026-09-17_EVENT_LEDGER.csv")
DAILY_LEDGER = Path("STOCKS_PIT_FULL_LEAD_CRISIS_EVENTTIME_AUDIT_2026-09-17_DAILY.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
CAPACITY_OUT = Path(f"{OUT_PREFIX}_CAPACITY_TOP.csv")
MISSING_OUT = Path(f"{OUT_PREFIX}_MISSING_EVENTS.csv")
SPEC_OUT = Path(f"{OUT_PREFIX}_FROZEN_SPEC.json")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

HARD_GROSS_CAP = 3.0
MARKED_GROSS_ALERT = 3.0
MARKED_GROSS_FORCE_DELEVER = 3.15
MAX_NAME_TARGET_NAV = 0.03
MAX_TRADE_ADV = 0.01
MISSING_NAME_LIMIT = 2
MISSING_NOTIONAL_NAV_LIMIT = 0.02


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def target_schedule(dates: list[pd.Timestamp]) -> pd.DataFrame:
    core = base.load_core().set_index("date")["spy_exposure"]
    pair_events = base.load_pair_events()
    crisis_schedule = crisis.crisis_weight_schedule(dates, 0.5)
    active: dict[str, dict[str, object]] = {}
    prior_satellite = pd.Series(dtype=float)
    rows = []
    for date in dates:
        base.apply_trade_events(active, pair_events.get(date, pd.DataFrame()))
        pair_weights = base.active_pair_weights(active, 0.5)
        crisis_weights = crisis_schedule.get(date, pd.Series(dtype=float))
        satellite = pair_weights.add(crisis_weights, fill_value=0.0)
        tickers = prior_satellite.index.union(satellite.index)
        delta = satellite.reindex(tickers).fillna(0.0) - prior_satellite.reindex(tickers).fillna(0.0)
        spy = float(core.get(date, 0.0))
        target_gross = abs(spy) + float(satellite.abs().sum())
        for ticker in tickers:
            rows.append({
                "date": date,
                "ticker": ticker,
                "targetWeight": float(satellite.get(ticker, 0.0)),
                "tradeWeightProxy": abs(float(delta.get(ticker, 0.0))),
                "spyTarget": spy,
                "satelliteGross": float(satellite.abs().sum()),
                "targetGross": target_gross,
            })
        prior_satellite = satellite
    return pd.DataFrame(rows)


def main() -> None:
    daily = pd.read_csv(DAILY_LEDGER, parse_dates=["date"])
    base_daily = daily[daily["scenario"].eq("base")].sort_values("date").copy()
    base_daily["priorEquity"] = base_daily["equity"] - base_daily["daily_pnl"]
    dates = list(base_daily["date"])
    targets = target_schedule(dates).merge(base_daily[["date", "priorEquity"]], on="date", how="left")
    target_tickers = sorted(targets["ticker"].dropna().astype(str).str.upper().unique())
    liquidity = pd.read_parquet(
        PIT_FILTER,
        columns=["date", "ticker", "prior_close", "adv20", "liquidity_metric_source", "eligible_final"],
        filters=[
            ("ticker", "in", target_tickers),
            ("date", ">=", min(dates).date()),
            ("date", "<=", max(dates).date()),
            ("eligible_final", "==", True),
        ],
    )
    liquidity["date"] = pd.to_datetime(liquidity["date"]).dt.normalize()
    liquidity["ticker"] = liquidity["ticker"].astype(str).str.upper()
    liquidity = liquidity.groupby(["date", "ticker"], as_index=False).agg(
        prior_close=("prior_close", "min"),
        adv20=("adv20", "min"),
        liquidity_metric_source=("liquidity_metric_source", lambda s: "ticker_fallback" if s.eq("ticker_fallback").any() else "security_id"),
        eligible_final=("eligible_final", "all"),
    )
    targets = targets.merge(liquidity, on=["date", "ticker"], how="left", validate="many_to_one")
    targets["targetNotional"] = targets["targetWeight"].abs() * targets["priorEquity"]
    targets["tradeNotionalProxy"] = targets["tradeWeightProxy"] * targets["priorEquity"]
    targets["tradeAdvParticipation"] = targets["tradeNotionalProxy"] / targets["adv20"]
    active_targets = targets[targets["targetWeight"].ne(0) | targets["tradeWeightProxy"].ne(0)].copy()
    active_targets.nlargest(100, "tradeAdvParticipation").to_csv(CAPACITY_OUT, index=False)

    events = pd.read_csv(EVENT_LEDGER, parse_dates=["timestamp"])
    stress = events[events["scenario"].eq("stress")].sort_values("timestamp").copy()
    stress["newMissingMarks"] = stress["missing_marks"].diff().fillna(stress["missing_marks"])
    stress["missingNotional"] = stress["missing_penalty"] / 0.0025
    stress["missingNotionalPctEquity"] = stress["missingNotional"] / stress["equity"]
    stress["failSafeBreach"] = (stress["newMissingMarks"] > MISSING_NAME_LIMIT) | (stress["missingNotionalPctEquity"] > MISSING_NOTIONAL_NAV_LIMIT)
    missing_events = stress[stress["newMissingMarks"].gt(0)].copy()
    missing_events.to_csv(MISSING_OUT, index=False)

    max_target_gross = float(targets.groupby("date")["targetGross"].first().max())
    max_marked_gross = float(base_daily["max_gross"].max())
    max_name_weight = float(active_targets["targetWeight"].abs().max())
    max_participation = float(active_targets["tradeAdvParticipation"].max())
    missing_adv_rows = int(active_targets["adv20"].isna().sum())
    fallback_rows = int(active_targets["liquidity_metric_source"].eq("ticker_fallback").sum())
    summary = [
        {"check": "target_gross_le_3x", "value": max_target_gross, "limit": HARD_GROSS_CAP, "status": "PASS" if max_target_gross <= HARD_GROSS_CAP else "FAIL"},
        {"check": "observed_marked_gross_le_3x", "value": max_marked_gross, "limit": MARKED_GROSS_ALERT, "status": "PASS" if max_marked_gross <= MARKED_GROSS_ALERT else "FAIL"},
        {"check": "single_name_target_le_3pct_nav", "value": max_name_weight, "limit": MAX_NAME_TARGET_NAV, "status": "PASS" if max_name_weight <= MAX_NAME_TARGET_NAV else "FAIL"},
        {"check": "trade_proxy_le_1pct_adv20", "value": max_participation, "limit": MAX_TRADE_ADV, "status": "PASS" if max_participation <= MAX_TRADE_ADV else "FAIL"},
        {"check": "all_active_targets_have_adv20", "value": missing_adv_rows, "limit": 0, "status": "PASS" if missing_adv_rows == 0 else "FAIL"},
        {"check": "ticker_fallback_target_rows", "value": fallback_rows, "limit": 0, "status": "WARN" if fallback_rows else "PASS"},
        {"check": "missing_failsafe_breach_events", "value": int(stress["failSafeBreach"].sum()), "limit": 0, "status": "FAIL" if stress["failSafeBreach"].any() else "PASS"},
        {"check": "max_simultaneous_missing_marks", "value": float(stress["newMissingMarks"].max()), "limit": MISSING_NAME_LIMIT, "status": "FAIL" if stress["newMissingMarks"].max() > MISSING_NAME_LIMIT else "PASS"},
        {"check": "max_missing_notional_pct_equity", "value": float(stress["missingNotionalPctEquity"].max()), "limit": MISSING_NOTIONAL_NAV_LIMIT, "status": "FAIL" if stress["missingNotionalPctEquity"].max() > MISSING_NOTIONAL_NAV_LIMIT else "PASS"},
    ]
    pd.DataFrame(summary).to_csv(SUMMARY_OUT, index=False)

    spec = {
        "spec_id": "stocks_pit_lead_crisis_v1_frozen_2026-09-17",
        "status": "RESEARCH_FROZEN_NOT_PRODUCTION",
        "sample": "Touched 2018-2024. 2023-2024 not clean OOS. 2025-2026 unopened.",
        "sleeves": {
            "core": "SPY lagged vt16, target cap 1.5x",
            "calendar": "SPY first five trading days of month +0.5x",
            "pairs": "quarterly same-SIC z2 hold10, target gross cap 0.5x",
            "crisis": "PIT top500 market-residual bottom10/top10 hold3, target gross cap 0.5x, new cohorts only when lagged SPY overnight20 compounded return < 0",
        },
        "portfolio_controls": {
            "hard_target_gross_cap": HARD_GROSS_CAP,
            "marked_gross_alert": MARKED_GROSS_ALERT,
            "marked_gross_force_delever_next_mark": MARKED_GROSS_FORCE_DELEVER,
            "single_name_target_nav_cap": MAX_NAME_TARGET_NAV,
            "trade_adv20_participation_cap": MAX_TRADE_ADV,
            "broker_margin_policy": "Reject risk-increasing orders unless broker buying power after the proposed order is at least 1.25x the broker requirement. Candidate requires portfolio-margin approval; do not assume Reg-T supports 2.88x gross.",
        },
        "missing_price_policy": {
            "per_name": "Never open or increase without a current executable mark. Freeze a held missing name; submit reduction/exit at its next valid mark.",
            "portfolio_trigger": f"More than {MISSING_NAME_LIMIT} simultaneously missing held names or missing held notional above {MISSING_NOTIONAL_NAV_LIMIT:.0%} NAV.",
            "action": "Block all risk-increasing orders. If breach persists for two consecutive marks, liquidate affected names at next valid marks and keep crisis/pairs sleeves disabled until one complete clean session.",
        },
        "loss_controls": {
            "annual_loss_budget": "Diagnostic only, excluded from frozen headline candidate.",
            "max_drawdown_breaker": "Excluded; tested variants failed the 18% objective.",
        },
        "execution": {"pair_and_crisis_rebalance": "09:35", "spy_rebalance": "15:55 for next session", "base_turnover_bps": 4.0, "base_financing_annual": 0.025, "base_borrow_annual": 0.01},
        "production_blockers": ["clean OOS", "missing-mark fail-safe replay", "live broker margin/buying-power validation", "spread/market-impact validation beyond ADV proxy"],
    }
    SPEC_OUT.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_deployment_policy_audit.py",
        "inputs": [str(PIT_FILTER).replace("\\", "/"), str(EVENT_LEDGER), str(DAILY_LEDGER)],
        "frozen_source_hashes": {
            str(crisis.SOURCE_SIGNALS): sha256(crisis.SOURCE_SIGNALS),
            "raits/research/stocks_pit_full_lead_crisis_eventtime_audit.py": sha256(Path("raits/research/stocks_pit_full_lead_crisis_eventtime_audit.py")),
            "raits/research/stocks_pit_full_lead_candidate_eventtime_audit.py": sha256(Path("raits/research/stocks_pit_full_lead_candidate_eventtime_audit.py")),
        },
        "outputs": [str(SUMMARY_OUT), str(CAPACITY_OUT), str(MISSING_OUT), str(SPEC_OUT)],
        "selection_warning": "Policies are frozen after touched-sample research. Audit does not constitute production validation or clean OOS evidence.",
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(pd.DataFrame(summary).to_string(index=False), flush=True)
    print("WROTE", SUMMARY_OUT, CAPACITY_OUT, MISSING_OUT, SPEC_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
