from __future__ import annotations

from pathlib import Path

import json

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as engine
from stocks_pit_full_lead_overnight_hedge import build_signals


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_PERSISTENT_SPY_HEDGE_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
STATE_OUT = Path(f"{OUT_PREFIX}_STATE.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

HEDGE_SCALE = 0.5
VARIANTS = ["control", "below_sma200", "overnight20_negative", "below_sma200_and_overnight20_negative"]


def main() -> None:
    base = engine.load_core().rename(columns={"spy_exposure": "base_spy_exposure"})
    signals = build_signals()
    source = base.merge(signals, on="date", how="left", validate="one_to_one")
    dates = list(source["date"])
    spy = engine.load_spy_prices(dates)
    common_dates = set(source["date"]).intersection(spy["date"])
    source = source[source["date"].isin(common_dates)].copy()
    spy = spy[spy["date"].isin(common_dates)].copy()
    pair_events = engine.load_pair_events()
    p935, p1555 = engine.load_pair_prices(common_dates)
    scenario_base = {"cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0}

    summaries = []
    yearly = []
    states = []
    concentration = []
    daily_frames = []
    event_frames = []
    contrib_frames = []
    qa = []
    for variant in VARIANTS:
        state = source.copy()
        state["hedge_active"] = state[variant].eq(True) if variant != "control" else False
        state["hedge_exposure"] = -HEDGE_SCALE * state["hedge_active"].astype(float)
        state["spy_exposure"] = state["base_spy_exposure"] + state["hedge_exposure"]
        core = state[["date", "spy_exposure"]].copy()
        scenario = dict(scenario_base, scenario=variant)
        daily, events, contrib = engine.simulate(scenario, core, spy, pair_events, p935, p1555)
        summary = engine.summary_row(scenario, daily, events)
        summary["hedgeScale"] = HEDGE_SCALE if variant != "control" else 0.0
        summary["hedgedDays"] = int(state["hedge_active"].sum())
        summary["hedgedDays2022"] = int(state.loc[state["date"].dt.year.eq(2022), "hedge_active"].sum())
        summaries.append(summary)
        yearly.extend(engine.yearly_rows(daily))
        concentration.extend(engine.concentration_rows(variant, contrib))
        states.append(state[["date", "base_spy_exposure", "hedge_active", "hedge_exposure", "spy_exposure", "prior_close", "lagged_sma200", "lagged_overnight20"]].assign(variant=variant))
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - engine.START_CAPITAL)
        qa.append({"scenario": variant, "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        daily_frames.append(daily)
        event_frames.append(events)
        contrib_frames.append(contrib)
        print("PERSISTENT_HEDGE", variant, summary, flush=True)

    summary = pd.DataFrame(summaries)
    control_pnl = float(summary.loc[summary["scenario"].eq("control"), "pnl"].iloc[0])
    summary["incrementalPnlVsControl"] = summary["pnl"] - control_pnl
    summary.to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.concat(states, ignore_index=True).to_csv(STATE_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENT_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_persistent_spy_hedge.py",
        "engine": "raits/research/stocks_pit_full_lead_candidate_eventtime_audit.py",
        "inputs": [str(engine.CORE_DAILY), str(engine.PAIR_EVENTS), str(engine.PAIR_PRICES).replace("\\", "/"), str(engine.SPY_BARS).replace("\\", "/")],
        "pre_registered_variants": VARIANTS,
        "hedge_rule": "Subtract 0.5x SPY exposure from the frozen core whenever the lagged state is true; hold until the state changes. Same-instrument positions are netted before turnover, financing, and PnL.",
        "attribution": "Because hedge and core use the same SPY instrument, causal hedge effect is the full-rerun difference from control, not a separately additive sleeve ledger.",
        "sample_label": "Diagnostic on touched research sample 2018-2024. No 2025-2026 opened.",
        "selection_warning": "Family was frozen before this run but was motivated by observed 2022 losses; it is not clean OOS evidence.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(STATE_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(EVENT_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, STATE_OUT, CONCENTRATION_OUT, DAILY_OUT, EVENT_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
