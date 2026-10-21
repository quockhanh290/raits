from __future__ import annotations

from pathlib import Path

import datetime as dt
import json
import pickle

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as engine


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_MAXDD_CIRCUIT_BREAKERS_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
TRIGGER_OUT = Path(f"{OUT_PREFIX}_TRIGGERS.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
SLEEVE_OUT = Path(f"{OUT_PREFIX}_SLEEVE_ATTRIBUTION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Frozen in the user-visible pre-registration before measurement.
VARIANTS = [
    {"variant": "gross2_control", "max_dd": None, "reentry": None},
    {"variant": "dd10_next_quarter", "max_dd": 0.10, "reentry": "next_quarter"},
    {"variant": "dd125_cooldown63", "max_dd": 0.125, "reentry": "cooldown_63"},
    {"variant": "dd15_spy_sma200", "max_dd": 0.15, "reentry": "spy_above_sma200"},
]


def lagged_spy_above_sma200() -> dict[pd.Timestamp, bool]:
    with engine.SPY_BARS.open("rb") as handle:
        bars = pickle.load(handle)["SPY"].copy().reset_index()
    time_col = "timestamp" if "timestamp" in bars.columns else bars.columns[0]
    bars["ts"] = pd.to_datetime(bars[time_col])
    bars["date"] = bars["ts"].dt.normalize()
    bars["time"] = bars["ts"].dt.time
    closes = (
        bars[bars["time"].eq(dt.time(15, 55))][["date", "close"]]
        .drop_duplicates("date", keep="last")
        .sort_values("date")
    )
    closes["prior_close"] = closes["close"].shift(1)
    closes["lagged_sma200"] = closes["close"].rolling(200, min_periods=200).mean().shift(1)
    closes["signal"] = closes["prior_close"] > closes["lagged_sma200"]
    return closes.set_index("date")["signal"].fillna(False).to_dict()


def main() -> None:
    core = engine.load_core()
    dates = list(core["date"])
    spy = engine.load_spy_prices(dates)
    common_dates = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common_dates)].copy()
    spy = spy[spy["date"].isin(common_dates)].copy()
    pair_events = engine.load_pair_events()
    p935, p1555 = engine.load_pair_prices(common_dates)
    reentry_signal = lagged_spy_above_sma200()
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
            spy_exposure_cap=1.5, max_dd_limit=spec["max_dd"],
            reentry_policy=spec["reentry"], reentry_signal=reentry_signal,
        )
        summary = engine.summary_row(scenario, daily, events)
        summary["maxDdLimit"] = spec["max_dd"]
        summary["reentryPolicy"] = spec["reentry"]
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
        print("MAXDD", spec["variant"], summary, flush=True)

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
        "script": "raits/research/stocks_pit_full_lead_maxdd_circuit_breakers.py",
        "engine": "raits/research/stocks_pit_full_lead_candidate_eventtime_audit.py",
        "inputs": [str(engine.CORE_DAILY), str(engine.PAIR_EVENTS), str(engine.PAIR_PRICES).replace("\\", "/"), str(engine.SPY_BARS).replace("\\", "/")],
        "pre_registered_variants": VARIANTS,
        "gross_policy": "All rows reserve 0.5x target gross for pairs and cap SPY target at 1.5x; marked gross can drift above 2.0x.",
        "trigger_policy": "Running high-water equity is evaluated at 09:35 and 15:55. A breach at either mark liquidates SPY and pairs at that session's 15:55 mark with turnover cost.",
        "reentry_policy": "On re-entry the high-water mark resets to current equity. Re-entry becomes active after the named condition and SPY resumes at that session's 15:55 rebalance; pairs resume at 09:35.",
        "sample_label": "Diagnostic on touched research sample 2018-2024. No 2025-2026 opened.",
        "selection_warning": "Family was publicly frozen before this run but was motivated by observed drawdowns; it is not unseen OOS evidence.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(TRIGGER_OUT), str(CONCENTRATION_OUT), str(SLEEVE_OUT), str(DAILY_OUT), str(EVENT_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, TRIGGER_OUT, CONCENTRATION_OUT, SLEEVE_OUT, DAILY_OUT, EVENT_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
