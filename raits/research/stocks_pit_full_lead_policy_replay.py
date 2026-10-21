from __future__ import annotations

from pathlib import Path

import json

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as base
import stocks_pit_full_lead_crisis_eventtime_audit as crisis


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_POLICY_REPLAY_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
POLICY_OUT = Path(f"{OUT_PREFIX}_POLICY_EVENTS.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

SCENARIOS = [
    {"scenario": "unconstrained_control", "name_cap": None, "hard_gross_cap": None, "missing_name_limit": None, "missing_notional_limit": None},
    {"scenario": "namecap3_gross3", "name_cap": 0.03, "hard_gross_cap": 3.0, "missing_name_limit": None, "missing_notional_limit": None},
    {"scenario": "namecap3_gross3_missingfs", "name_cap": 0.03, "hard_gross_cap": 3.0, "missing_name_limit": 2, "missing_notional_limit": 0.02},
]


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
    schedule = crisis.crisis_weight_schedule(dates, 0.5)
    summaries = []
    yearly = []
    policy_rows = []
    concentration = []
    daily_frames = []
    event_frames = []
    contrib_frames = []
    qa = []
    for spec in SCENARIOS:
        scenario = {"scenario": spec["scenario"], "crisis_scale": 0.5, "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0}
        daily, events, contrib = crisis.simulate(
            scenario, core, spy, pair_events, p935, p1555, schedule,
            name_cap=spec["name_cap"], hard_gross_cap=spec["hard_gross_cap"],
            missing_name_limit=spec["missing_name_limit"], missing_notional_limit=spec["missing_notional_limit"],
        )
        summary = base.summary_row(scenario, daily, events)
        summary.update({
            "nameCap": spec["name_cap"], "hardGrossCap": spec["hard_gross_cap"],
            "failSafeBreaches": int(events["fail_safe_breach"].eq(True).sum()),
            "disabledEventMarks": int(events["policy_disabled"].eq(True).sum()),
            "capEventMarks": int(events["target_cap_scale"].fillna(1.0).lt(1.0).sum()),
            "minTargetCapScale": float(events["target_cap_scale"].fillna(1.0).min()),
        })
        summaries.append(summary)
        yearly.extend(base.yearly_rows(daily))
        concentration.extend(base.concentration_rows(str(spec["scenario"]), contrib))
        selected_policy = events[
            events["fail_safe_breach"].eq(True)
            | events["policy_disabled"].eq(True)
            | events["target_cap_scale"].fillna(1.0).lt(1.0)
        ].copy()
        policy_rows.append(selected_policy)
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - base.START_CAPITAL)
        qa.append({"scenario": spec["scenario"], "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        daily_frames.append(daily)
        event_frames.append(events)
        contrib_frames.append(contrib)
        print("POLICY_REPLAY", summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.concat(policy_rows, ignore_index=True).to_csv(POLICY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENT_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_policy_replay.py",
        "engine": "raits/research/stocks_pit_full_lead_crisis_eventtime_audit.py",
        "inputs": [str(base.CORE_DAILY), str(base.PAIR_EVENTS), str(crisis.SOURCE_SIGNALS), str(base.PAIR_PRICES).replace("\\", "/"), str(base.SPY_BARS).replace("\\", "/")],
        "pre_registered_scenarios": SCENARIOS,
        "name_cap_method": "When aggregate net satellite target exceeds 3% NAV in any name, proportionally scale the entire pair-plus-crisis target vector. This preserves all pair/cohort relationships and leaves unavailable gross in cash; no post-hoc PnL clipping or invented runner-up trade.",
        "missing_policy": "No trade on a missing executable mark; held missing names freeze. A breach (>2 missing held names or >2% NAV stale notional) disables satellite targets and blocks SPY risk increases. Valid satellites exit at 09:35; missing names exit on their next valid mark. Re-enable only after one complete clean 09:35/15:55 session.",
        "sample_label": "Touched research 2018-2024 only. No 2025-2026 opened.",
        "selection_warning": "Operational replay of frozen policies, not new edge evidence.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(POLICY_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(EVENT_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, POLICY_OUT, CONCENTRATION_OUT, DAILY_OUT, EVENT_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
