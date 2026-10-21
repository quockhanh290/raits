from __future__ import annotations

from pathlib import Path

import json

import numpy as np
import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as base
import stocks_pit_full_lead_crisis_eventtime_audit as crisis
import stocks_pit_full_lead_missing_price_replay as prices


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_ADV_EXECUTION_REPLAY_2026-09-17"
COVERAGE = prices.COVERAGE_OUT
TRADE_AUDIT = Path("STOCKS_PIT_FULL_LEAD_CAPACITY_MARGIN_AUDIT_2026-09-17_TRADE_AUDIT.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Frozen before measuring. All rows rebuild holdings, carry, costs, and compounding.
SCENARIOS = [
    {"scenario": "price_replay_control", "adv_gate": False, "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01},
    {"scenario": "adv_gate_base4", "adv_gate": True, "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01},
    {"scenario": "adv_gate_cost8", "adv_gate": True, "cost_bps": 8.0, "financing": 0.025, "borrow": 0.01},
    {"scenario": "adv_gate_severe12", "adv_gate": True, "cost_bps": 12.0, "financing": 0.05, "borrow": 0.03},
]


def replay_price_maps(common: set[pd.Timestamp]) -> tuple[dict[pd.Timestamp, pd.Series], dict[pd.Timestamp, pd.Series], dict[pd.Timestamp, pd.Series], dict[pd.Timestamp, pd.Series]]:
    feature935, feature1555 = base.load_pair_prices(common)
    exact935 = prices.copy_maps(feature935)
    exact1555 = prices.copy_maps(feature1555)
    mark935 = prices.copy_maps(feature935)
    mark1555 = prices.copy_maps(feature1555)
    coverage = pd.read_csv(COVERAGE, parse_dates=["date"])
    for row in coverage.itertuples(index=False):
        if row.event == "both" or not np.isfinite(row.price):
            continue
        date = pd.Timestamp(row.date).normalize()
        if row.event == "0935":
            if row.source == "raw_exact":
                prices.put(exact935, date, row.ticker, float(row.price))
                prices.put(mark935, date, row.ticker, float(row.price))
            elif row.source == "raw_asof":
                prices.put(mark935, date, row.ticker, float(row.price))
        elif row.event == "1555":
            if row.source == "raw_exact":
                prices.put(exact1555, date, row.ticker, float(row.price))
                prices.put(mark1555, date, row.ticker, float(row.price))
            elif row.source == "raw_asof":
                prices.put(mark1555, date, row.ticker, float(row.price))
    return exact935, exact1555, mark935, mark1555


def main() -> None:
    core = base.load_core()
    spy = base.load_spy_prices(list(core["date"]))
    common = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common)].copy()
    spy = spy[spy["date"].isin(common)].copy()
    dates = sorted(common)
    pair_events = base.load_pair_events()
    schedule = crisis.crisis_weight_schedule(dates, 0.5)
    exact935, exact1555, mark935, mark1555 = replay_price_maps(common)

    trade_audit = pd.read_csv(TRADE_AUDIT, parse_dates=["date"])
    blocked = {
        (pd.Timestamp(row.date).normalize(), str(row.ticker).upper())
        for row in trade_audit[trade_audit["policyAction"].eq("BLOCK_RISK_INCREASE")].itertuples(index=False)
    }
    summaries = []
    yearly = []
    concentration = []
    event_frames = []
    contrib_frames = []
    qa = []
    for spec in SCENARIOS:
        scenario = {
            "scenario": spec["scenario"], "crisis_scale": 0.5,
            "cost_bps": spec["cost_bps"], "financing": spec["financing"],
            "borrow": spec["borrow"], "missing_bps": 0.0,
        }
        daily, events, contrib = crisis.simulate(
            scenario, core, spy, pair_events, exact935, exact1555, schedule,
            name_cap=0.03, hard_gross_cap=3.0,
            missing_name_limit=2, missing_notional_limit=0.02,
            mark935=mark935, mark1555=mark1555, require_current_execution=True,
            blocked_risk_increases=blocked if spec["adv_gate"] else None,
        )
        summary = base.summary_row(scenario, daily, events)
        summary.update({
            "advGate": spec["adv_gate"],
            "advBlockedEventMarks": int(events["adv_blocked_count"].fillna(0).gt(0).sum()),
            "advBlockedOrders": int(events["adv_blocked_count"].fillna(0).sum()),
            "failSafeBreaches": int(events["fail_safe_breach"].sum()),
            "disabledEventMarks": int(events["policy_disabled"].sum()),
        })
        summaries.append(summary)
        yearly.extend(base.yearly_rows(daily))
        concentration.extend(prices.concentration_rows(str(spec["scenario"]), contrib))
        event_frames.append(events)
        contrib_frames.append(contrib)
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - base.START_CAPITAL)
        qa.append({"scenario": spec["scenario"], "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        print("ADV_EXECUTION_REPLAY", summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENT_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_adv_execution_replay.py",
        "engine": "raits/research/stocks_pit_full_lead_crisis_eventtime_audit.py",
        "inputs": [str(base.CORE_DAILY), str(base.PAIR_EVENTS), str(crisis.SOURCE_SIGNALS), str(COVERAGE), str(TRADE_AUDIT), str(base.SPY_BARS).replace("\\", "/")],
        "pre_registered_scenarios": SCENARIOS,
        "adv_policy": "Current eligible PIT ADV20 is required for every risk increase. A sign flip may close the existing side but may not establish the opposite side. Reductions and exits remain permitted.",
        "execution_stress": "Uniform all-in turnover costs at 4, 8, and 12 bps. Severe also uses 5% annual financing and 3% annual short borrow.",
        "sample_label": "Touched research 2018-2024 only. No 2025-2026 opened.",
        "selection_warning": "Frozen operational replay; no source rule or ticker re-selection.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(EVENT_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, EVENT_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
