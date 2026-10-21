from __future__ import annotations

from pathlib import Path

import json

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as base
import stocks_pit_full_lead_crisis_eventtime_audit as crisis


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_CRISIS_SCALE_DIAGNOSTIC_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")
SCALES = [0.0, 0.5, 0.75, 1.0, 1.5]


def main() -> None:
    core = base.load_core()
    dates = list(core["date"])
    spy = base.load_spy_prices(dates)
    common = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common)].copy()
    spy = spy[spy["date"].isin(common)].copy()
    dates = sorted(common)
    pair_events = base.load_pair_events()
    p935, p1555 = base.load_pair_prices(common)
    summaries = []
    yearly = []
    concentration = []
    qa = []
    for scale in SCALES:
        scenario = {"scenario": f"crisis_{scale:g}x", "crisis_scale": scale, "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0}
        schedule = crisis.crisis_weight_schedule(dates, scale)
        daily, events, contrib = crisis.simulate(scenario, core, spy, pair_events, p935, p1555, schedule)
        summary = base.summary_row(scenario, daily, events)
        summary["crisisScale"] = scale
        summaries.append(summary)
        yearly.extend(base.yearly_rows(daily))
        concentration.extend(base.concentration_rows(str(scenario["scenario"]), contrib))
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - base.START_CAPITAL)
        qa.append({"scenario": scenario["scenario"], "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        print("CRISIS_SCALE", summary, flush=True)
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_crisis_scale_diagnostic.py",
        "engine": "raits/research/stocks_pit_full_lead_crisis_eventtime_audit.py",
        "inputs": [str(base.CORE_DAILY), str(base.PAIR_EVENTS), str(crisis.SOURCE_SIGNALS), str(base.PAIR_PRICES).replace("\\", "/"), str(base.SPY_BARS).replace("\\", "/")],
        "pre_registered_scales": SCALES,
        "fixed_costs": "4 bps turnover, 2.5% annual financing, 1% annual short borrow, zero missing-mark penalty.",
        "selection_warning": "Pure post-selection sizing diagnostic on touched 2018-2024. The 2022 result must not be used to select a production scale.",
        "sample_label": "Touched research 2018-2024 only. No 2025-2026 opened.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
