from __future__ import annotations

from pathlib import Path

import datetime as dt
import json
import pickle

import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as engine


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_2022_GUARD_DIAGNOSTIC_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
STATE_OUT = Path(f"{OUT_PREFIX}_STATE.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Frozen before measurement. These are deliberately coarse lagged guards, not a threshold scan.
VARIANTS = [
    "baseline",
    "overlay_off_below_sma200",
    "overlay_off_ret20_le_m8",
    "beta75_overlay_off_below_sma200",
    "cap075_below_sma200",
]


def load_spy_regime() -> pd.DataFrame:
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
        .rename(columns={"close": "spy_close"})
    )
    closes["prev_close"] = closes["spy_close"].shift(1)
    closes["prev_sma200"] = closes["spy_close"].rolling(200, min_periods=200).mean().shift(1)
    closes["prev_ret20"] = closes["spy_close"].pct_change(20).shift(1)
    closes["below_sma200"] = closes["prev_close"] < closes["prev_sma200"]
    closes["ret20_le_m8"] = closes["prev_ret20"] <= -0.08
    return closes[["date", "prev_close", "prev_sma200", "prev_ret20", "below_sma200", "ret20_le_m8"]]


def guarded_core(base: pd.DataFrame, regime: pd.DataFrame, variant: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = base.merge(regime, on="date", how="left", validate="one_to_one")
    source["base_exposure"] = source["beta_exposure"] + source["overlay_exposure"]
    if variant == "baseline":
        source["spy_exposure"] = source["base_exposure"]
        source["guard_active"] = False
    elif variant == "overlay_off_below_sma200":
        source["guard_active"] = source["below_sma200"]
        source["spy_exposure"] = source["beta_exposure"] + source["overlay_exposure"].where(~source["guard_active"], 0.0)
    elif variant == "overlay_off_ret20_le_m8":
        source["guard_active"] = source["ret20_le_m8"]
        source["spy_exposure"] = source["beta_exposure"] + source["overlay_exposure"].where(~source["guard_active"], 0.0)
    elif variant == "beta75_overlay_off_below_sma200":
        source["guard_active"] = source["below_sma200"]
        source["spy_exposure"] = source["base_exposure"]
        source.loc[source["guard_active"], "spy_exposure"] = 0.75 * source.loc[source["guard_active"], "beta_exposure"]
    elif variant == "cap075_below_sma200":
        source["guard_active"] = source["below_sma200"]
        source["spy_exposure"] = source["base_exposure"]
        source.loc[source["guard_active"], "spy_exposure"] = source.loc[source["guard_active"], "base_exposure"].clip(upper=0.75)
    else:
        raise ValueError(variant)
    core = source[["date", "spy_exposure"]].copy()
    state = source[["date", "beta_exposure", "overlay_exposure", "base_exposure", "spy_exposure", "prev_close", "prev_sma200", "prev_ret20", "below_sma200", "ret20_le_m8", "guard_active"]].copy()
    state.insert(0, "variant", variant)
    return core, state


def main() -> None:
    raw = pd.read_csv(engine.CORE_DAILY, parse_dates=["date"])
    raw = raw[raw["variant"].eq(engine.CORE_VARIANT)].sort_values("date").copy()
    regime = load_spy_regime()
    dates = list(raw["date"])
    spy = engine.load_spy_prices(dates)
    common_dates = set(raw["date"]).intersection(spy["date"])
    raw = raw[raw["date"].isin(common_dates)].copy()
    spy = spy[spy["date"].isin(common_dates)].copy()
    pair_events = engine.load_pair_events()
    p935, p1555 = engine.load_pair_prices(common_dates)
    scenario = {"scenario": "base", "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0}

    summaries = []
    yearly = []
    states = []
    daily_frames = []
    for variant in VARIANTS:
        core, state = guarded_core(raw, regime, variant)
        run_scenario = dict(scenario, scenario=variant)
        daily, events, _ = engine.simulate(run_scenario, core, spy, pair_events, p935, p1555)
        summary = engine.summary_row(run_scenario, daily, events)
        summary["guardDays"] = int(state["guard_active"].sum())
        summary["guardDays2022"] = int(state.loc[state["date"].dt.year.eq(2022), "guard_active"].sum())
        summaries.append(summary)
        yearly.extend(engine.yearly_rows(daily))
        states.append(state)
        daily_frames.append(daily)
        print("GUARD", variant, summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.concat(states, ignore_index=True).to_csv(STATE_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_2022_guard_diagnostic.py",
        "inputs": [str(engine.CORE_DAILY), str(engine.PAIR_EVENTS), str(engine.PAIR_PRICES).replace("\\", "/"), str(engine.SPY_BARS).replace("\\", "/")],
        "pre_registered_variants": VARIANTS,
        "rules": {
            "overlay_off_below_sma200": "Keep beta; set first-five overlay to zero when prior SPY 15:55 close is below lagged 200-session SMA.",
            "overlay_off_ret20_le_m8": "Keep beta; set first-five overlay to zero when lagged SPY 20-session return is <= -8%.",
            "beta75_overlay_off_below_sma200": "When below lagged SMA200, set SPY exposure to 75% of the frozen vt16 beta and remove overlay.",
            "cap075_below_sma200": "When below lagged SMA200, cap total frozen SPY exposure at 0.75x.",
        },
        "sample_label": "Diagnostic on touched research sample 2018-2024. No 2025-2026 opened.",
        "selection_warning": "This family was frozen before this run, but 2022 motivated the family. Results are diagnostic and cannot establish clean OOS robustness.",
        "execution": "Same shared-equity event-time engine, pairs, costs, financing, borrow and marks as section 6.193; only next-session SPY target exposure changes.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(STATE_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, STATE_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
