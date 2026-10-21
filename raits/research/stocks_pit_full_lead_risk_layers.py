from __future__ import annotations

from pathlib import Path

import json

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as engine


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_RISK_LAYERS_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
TRIGGER_OUT = Path(f"{OUT_PREFIX}_TRIGGERS.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
SLEEVE_OUT = Path(f"{OUT_PREFIX}_SLEEVE_ATTRIBUTION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Frozen before measurement. No threshold scan: one economically interpretable value per layer.
VARIANTS = [
    {"variant": "baseline", "spy_cap": None, "annual_loss_limit": None},
    {"variant": "target_gross2", "spy_cap": 1.5, "annual_loss_limit": None},
    {"variant": "annual_loss10", "spy_cap": None, "annual_loss_limit": 0.10},
    {"variant": "target_gross2_annual_loss10", "spy_cap": 1.5, "annual_loss_limit": 0.10},
]


def main() -> None:
    core = engine.load_core()
    dates = list(core["date"])
    spy = engine.load_spy_prices(dates)
    common_dates = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common_dates)].copy()
    spy = spy[spy["date"].isin(common_dates)].copy()
    pair_events = engine.load_pair_events()
    p935, p1555 = engine.load_pair_prices(common_dates)
    base_scenario = {"cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0}

    summaries = []
    yearly = []
    triggers = []
    concentration = []
    sleeves = []
    daily_frames = []
    event_frames = []
    qa = []
    for spec in VARIANTS:
        scenario = dict(base_scenario, scenario=spec["variant"])
        daily, events, contrib = engine.simulate(
            scenario, core, spy, pair_events, p935, p1555,
            spy_exposure_cap=spec["spy_cap"], annual_loss_limit=spec["annual_loss_limit"],
        )
        summary = engine.summary_row(scenario, daily, events)
        summary["spyExposureCap"] = spec["spy_cap"]
        summary["annualLossLimit"] = spec["annual_loss_limit"]
        summary["lockedDays"] = int(daily["risk_locked"].sum())
        summaries.append(summary)
        yearly.extend(engine.yearly_rows(daily))
        concentration.extend(engine.concentration_rows(spec["variant"], contrib))
        for sleeve, pnl in contrib.groupby("sleeve")["pnl"].sum().items():
            sleeves.append({"scenario": spec["variant"], "sleeve": sleeve, "pnl": float(pnl)})
        prior = events["risk_locked"].shift(fill_value=False)
        fired = events[events["risk_locked"] & ~prior]
        for row in fired.itertuples(index=False):
            triggers.append({"scenario": spec["variant"], "timestamp": row.timestamp, "equityAfterLiquidation": row.equity})
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - engine.START_CAPITAL)
        qa.append({"scenario": spec["variant"], "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        daily_frames.append(daily)
        event_frames.append(events)
        print("RISK", spec["variant"], summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(triggers, columns=["scenario", "timestamp", "equityAfterLiquidation"]).to_csv(TRIGGER_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(sleeves).to_csv(SLEEVE_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENT_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_risk_layers.py",
        "engine": "raits/research/stocks_pit_full_lead_candidate_eventtime_audit.py",
        "inputs": [str(engine.CORE_DAILY), str(engine.PAIR_EVENTS), str(engine.PAIR_PRICES).replace("\\", "/"), str(engine.SPY_BARS).replace("\\", "/")],
        "pre_registered_variants": VARIANTS,
        "target_gross_rule": "Reserve 0.5x target gross for frozen pairs and cap SPY target at 1.5x, giving a 2.0x target-gross budget. Mark-to-market gross can temporarily exceed 2.0x between rebalances.",
        "loss_budget_rule": "At the first 15:55 equity mark at or below 90% of start-of-calendar-year equity, liquidate SPY and pairs at that 15:55 mark, charge turnover, remain flat through year-end, and reset for the next calendar year.",
        "sample_label": "Diagnostic on touched research sample 2018-2024. No 2025-2026 opened.",
        "selection_warning": "Risk family was frozen before this run, but it was motivated by the already-observed 2022 loss. It is diagnostic, not unseen OOS evidence.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(TRIGGER_OUT), str(CONCENTRATION_OUT), str(SLEEVE_OUT), str(DAILY_OUT), str(EVENT_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, TRIGGER_OUT, CONCENTRATION_OUT, SLEEVE_OUT, DAILY_OUT, EVENT_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
