from __future__ import annotations

from pathlib import Path

import json

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as engine
from stocks_pit_full_lead_overnight_hedge import build_signals


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_PERSISTENT_HEDGE_STRESS_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
SLEEVE_OUT = Path(f"{OUT_PREFIX}_SLEEVE_ATTRIBUTION.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

SCENARIOS = [
    {"scenario": "base", "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "cost8", "cost_bps": 8.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "stress", "cost_bps": 8.0, "financing": 0.05, "borrow": 0.02, "missing_bps": 25.0},
    {"scenario": "severe", "cost_bps": 12.0, "financing": 0.05, "borrow": 0.03, "missing_bps": 50.0},
]


def main() -> None:
    core = engine.load_core().rename(columns={"spy_exposure": "base_spy_exposure"})
    signals = build_signals()[["date", "overnight20_negative"]]
    core = core.merge(signals, on="date", how="left", validate="one_to_one")
    core["spy_exposure"] = core["base_spy_exposure"] - 0.5 * core["overnight20_negative"].eq(True).astype(float)
    core = core[["date", "spy_exposure"]]
    dates = list(core["date"])
    spy = engine.load_spy_prices(dates)
    common_dates = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common_dates)].copy()
    spy = spy[spy["date"].isin(common_dates)].copy()
    pair_events = engine.load_pair_events()
    p935, p1555 = engine.load_pair_prices(common_dates)

    summaries = []
    yearly = []
    concentration = []
    sleeves = []
    qa = []
    for scenario in SCENARIOS:
        daily, events, contrib = engine.simulate(scenario, core, spy, pair_events, p935, p1555)
        summaries.append(engine.summary_row(scenario, daily, events))
        yearly.extend(engine.yearly_rows(daily))
        concentration.extend(engine.concentration_rows(str(scenario["scenario"]), contrib))
        for sleeve, pnl in contrib.groupby("sleeve")["pnl"].sum().items():
            sleeves.append({"scenario": scenario["scenario"], "sleeve": sleeve, "pnl": float(pnl)})
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - engine.START_CAPITAL)
        qa.append({"scenario": scenario["scenario"], "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        print("PERSISTENT_STRESS", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(sleeves).to_csv(SLEEVE_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_persistent_hedge_stress.py",
        "engine": "raits/research/stocks_pit_full_lead_candidate_eventtime_audit.py",
        "inputs": [str(engine.CORE_DAILY), str(engine.PAIR_EVENTS), str(engine.PAIR_PRICES).replace("\\", "/"), str(engine.SPY_BARS).replace("\\", "/")],
        "frozen_candidate": "Lead core plus pairs, with persistent -0.5x SPY exposure while lagged completed-session overnight20 compounded return is negative.",
        "pre_registered_scenarios": SCENARIOS,
        "sample_label": "Diagnostic on touched research sample 2018-2024. No 2025-2026 opened.",
        "selection_warning": "Candidate was selected from the three-row persistent hedge diagnostic on the same touched sample; stress survival cannot establish clean robustness.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(SLEEVE_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, SLEEVE_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
