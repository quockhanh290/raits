from __future__ import annotations

from pathlib import Path

import json

import pandas as pd

import stocks_pit_full_residual_reversal_cohorts as residual
from stocks_pit_full_lead_overnight_hedge import build_signals


OUT_PREFIX = "STOCKS_PIT_FULL_RESIDUAL_CRISIS_COST_STRESS_2026-09-17"
SOURCE_SIGNALS = Path("STOCKS_PIT_FULL_RESIDUAL_REVERSAL_COHORTS_2026-09-17_SIGNALS.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")
COSTS = [4.0, 8.0, 12.0]


def main() -> None:
    raw = residual.load_raw()
    signals = pd.read_csv(SOURCE_SIGNALS, parse_dates=["date", "entry_date"])
    signals = signals[signals["variant"].eq("market_resid_rev_10x10_hold3")].copy()
    regime = build_signals()[["date", "overnight20_negative"]].rename(columns={"date": "entry_date"})
    signals = signals.merge(regime, on="entry_date", how="left", validate="many_to_one")
    signals = signals[signals["overnight20_negative"].eq(True)].copy()
    summaries = []
    yearly = []
    qa = []
    original_cost = residual.TRADE_COST_BPS
    try:
        for cost in COSTS:
            residual.TRADE_COST_BPS = cost
            variant = f"overnight20_negative_05x_cost{int(cost)}"
            spec = {"variant": variant, "signal": "market", "hold_days": 3}
            daily, contrib = residual.simulate(raw, signals, spec, gross_scale=0.5)
            summary = residual.summary_row(spec, daily, signals)
            summary["costBps"] = cost
            summaries.append(summary)
            yearly.extend(residual.yearly_rows(daily))
            qa.append({"variant": variant, "dailyMinusEnding": float(daily["daily_pnl"].sum() - (daily["equity"].iloc[-1] - residual.START_CAPITAL)), "dailyMinusContrib": float(daily["daily_pnl"].sum() - contrib["pnl"].sum())})
            print("CRISIS_COST", summary, flush=True)
    finally:
        residual.TRADE_COST_BPS = original_cost
    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_residual_crisis_cost_stress.py",
        "engine": "raits/research/stocks_pit_full_residual_reversal_cohorts.py",
        "inputs": [str(SOURCE_SIGNALS), str(residual.DAILY_FEATURES).replace("\\", "/"), str(residual.INTRADAY_0935).replace("\\", "/"), "raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl (SPY bars only)"],
        "frozen_candidate": "Market-residual bottom10/top10 hold3, 0.5x gross, admit cohorts only when lagged SPY overnight20 is negative.",
        "pre_registered_cost_bps": COSTS,
        "sample_label": "Touched research 2018-2024 only. No 2025-2026 opened.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
