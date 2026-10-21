from __future__ import annotations

from pathlib import Path

import datetime as dt
import json
import pickle

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as engine


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_OVERNIGHT_HEDGE_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SIGNAL_OUT = Path(f"{OUT_PREFIX}_SIGNALS.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
SLEEVE_OUT = Path(f"{OUT_PREFIX}_SLEEVE_ATTRIBUTION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

HEDGE_SCALE = 0.5
VARIANTS = ["control", "below_sma200", "overnight20_negative", "below_sma200_and_overnight20_negative"]


def build_signals() -> pd.DataFrame:
    with engine.SPY_BARS.open("rb") as handle:
        bars = pickle.load(handle)["SPY"].copy().reset_index()
    time_col = "timestamp" if "timestamp" in bars.columns else bars.columns[0]
    bars["ts"] = pd.to_datetime(bars[time_col])
    bars["date"] = bars["ts"].dt.normalize()
    bars["time"] = bars["ts"].dt.time
    p935 = bars[bars["time"].eq(dt.time(9, 35))][["date", "open"]].drop_duplicates("date", keep="last").rename(columns={"open": "p935"})
    p1555 = bars[bars["time"].eq(dt.time(15, 55))][["date", "close"]].drop_duplicates("date", keep="last").rename(columns={"close": "p1555"})
    x = p1555.merge(p935, on="date", how="inner").sort_values("date")
    x["prev1555"] = x["p1555"].shift(1)
    x["overnight_ret"] = x["p935"] / x["prev1555"] - 1.0
    x["prior_close"] = x["p1555"].shift(1)
    x["lagged_sma200"] = x["p1555"].rolling(200, min_periods=200).mean().shift(1)
    x["lagged_overnight20"] = ((1.0 + x["overnight_ret"]).rolling(20, min_periods=20).apply(lambda v: v.prod(), raw=True) - 1.0).shift(1)
    x["below_sma200"] = x["prior_close"] < x["lagged_sma200"]
    x["overnight20_negative"] = x["lagged_overnight20"] < 0.0
    x["below_sma200_and_overnight20_negative"] = x["below_sma200"] & x["overnight20_negative"]
    x["control"] = False
    return x[["date", "prior_close", "lagged_sma200", "lagged_overnight20"] + VARIANTS]


def main() -> None:
    core = engine.load_core()
    dates = list(core["date"])
    spy = engine.load_spy_prices(dates)
    common_dates = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common_dates)].copy()
    spy = spy[spy["date"].isin(common_dates)].copy()
    signals = build_signals()
    signals = signals[signals["date"].isin(common_dates)].copy()
    pair_events = engine.load_pair_events()
    p935, p1555 = engine.load_pair_prices(common_dates)
    base_scenario = {"cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0}

    summaries = []
    yearly = []
    concentration = []
    sleeves = []
    daily_frames = []
    event_frames = []
    contrib_frames = []
    qa = []
    for variant in VARIANTS:
        signal = signals.set_index("date")[variant].astype(bool).to_dict()
        scenario = dict(base_scenario, scenario=variant)
        daily, events, contrib = engine.simulate(
            scenario, core, spy, pair_events, p935, p1555,
            overnight_hedge_signal=signal, overnight_hedge_scale=HEDGE_SCALE if variant != "control" else 0.0,
        )
        summary = engine.summary_row(scenario, daily, events)
        summary["hedgeScale"] = HEDGE_SCALE if variant != "control" else 0.0
        summary["hedgedNights"] = int(signals[variant].sum())
        summary["hedgedNights2022"] = int(signals.loc[signals["date"].dt.year.eq(2022), variant].sum())
        summaries.append(summary)
        yearly.extend(engine.yearly_rows(daily))
        concentration.extend(engine.concentration_rows(variant, contrib))
        for sleeve, pnl in contrib.groupby("sleeve")["pnl"].sum().items():
            sleeves.append({"scenario": variant, "sleeve": sleeve, "pnl": float(pnl)})
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - engine.START_CAPITAL)
        qa.append({"scenario": variant, "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        daily_frames.append(daily)
        event_frames.append(events)
        contrib_frames.append(contrib)
        print("OVERNIGHT_HEDGE", variant, summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    signals.to_csv(SIGNAL_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(sleeves).to_csv(SLEEVE_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENT_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_overnight_hedge.py",
        "engine": "raits/research/stocks_pit_full_lead_candidate_eventtime_audit.py",
        "inputs": [str(engine.CORE_DAILY), str(engine.PAIR_EVENTS), str(engine.PAIR_PRICES).replace("\\", "/"), str(engine.SPY_BARS).replace("\\", "/")],
        "pre_registered_variants": VARIANTS,
        "hedge_rule": "When the lagged signal is true, short SPY at 0.5x equity at 15:55 and cover next session at 09:35. Charge 4 bps on both entry and exit, 1% annual borrow, and incremental 2.5% financing for the overnight gross.",
        "signal_rules": {
            "below_sma200": "Prior SPY 15:55 close below the 200-session SMA calculated through that same prior close.",
            "overnight20_negative": "Compounded SPY close-to-09:35 return over the prior 20 completed sessions is negative.",
            "below_sma200_and_overnight20_negative": "Both lagged conditions true.",
        },
        "sample_label": "Diagnostic on touched research sample 2018-2024. No 2025-2026 opened.",
        "selection_warning": "Family was frozen before this run but was motivated by observed 2022 overnight losses; it is not clean OOS evidence.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(SIGNAL_OUT), str(CONCENTRATION_OUT), str(SLEEVE_OUT), str(DAILY_OUT), str(EVENT_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SIGNAL_OUT, CONCENTRATION_OUT, SLEEVE_OUT, DAILY_OUT, EVENT_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
