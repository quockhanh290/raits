from __future__ import annotations

from pathlib import Path

import json

import pandas as pd

import stocks_pit_full_residual_reversal_cohorts as residual
from stocks_pit_full_lead_overnight_hedge import build_signals


OUT_PREFIX = "STOCKS_PIT_FULL_RESIDUAL_CRISIS_SLEEVE_2026-09-17"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

SOURCE_SIGNALS = Path("STOCKS_PIT_FULL_RESIDUAL_REVERSAL_COHORTS_2026-09-17_SIGNALS.csv")
SOURCE_VARIANT = "market_resid_rev_10x10_hold3"
GROSS_SCALE = 0.5
VARIANTS = ["always_on_05x", "overnight20_negative_05x"]


def metrics(variant: str, daily: pd.DataFrame, signals: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = residual.max_drawdown(daily["equity"])
    pnl = float(daily["equity"].iloc[-1] - residual.START_CAPITAL)
    return {
        "variant": variant,
        "sourceVariant": SOURCE_VARIANT,
        "grossScale": GROSS_SCALE,
        "pnl": pnl,
        "grossPnlBeforeCostsBorrow": pnl + float(daily["trade_cost"].sum()) + float(daily["borrow_cost"].sum()),
        "cagr": residual.cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": residual.sharpe(daily["daily_pnl"]),
        "tradeCost": float(daily["trade_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "entrySignalRows": int(len(signals)),
        "entrySignalDays": int(signals["entry_date"].nunique()),
    }


def main() -> None:
    raw = residual.load_raw()
    source = pd.read_csv(SOURCE_SIGNALS, parse_dates=["date", "entry_date"])
    source = source[source["variant"].eq(SOURCE_VARIANT)].copy()
    regime = build_signals()[["date", "overnight20_negative"]].rename(columns={"date": "entry_date"})
    source = source.merge(regime, on="entry_date", how="left", validate="many_to_one")
    spec = {"variant": SOURCE_VARIANT, "signal": "market", "hold_days": 3}

    summaries = []
    yearly = []
    daily_frames = []
    contrib_frames = []
    qa = []
    for variant in VARIANTS:
        selected = source if variant == "always_on_05x" else source[source["overnight20_negative"].eq(True)]
        run_spec = dict(spec, variant=variant)
        daily, contrib = residual.simulate(raw, selected, run_spec, gross_scale=GROSS_SCALE)
        summaries.append(metrics(variant, daily, selected))
        yearly.extend(residual.yearly_rows(daily))
        daily_frames.append(daily)
        contrib_frames.append(contrib)
        qa.append({
            "variant": variant,
            "days": int(len(daily)),
            "maxMissingPositions": int(daily["missing_positions"].max()),
            "meanNetExposure": float(daily["net_exposure"].mean()),
            "dailyMinusEnding": float(daily["daily_pnl"].sum() - (daily["equity"].iloc[-1] - residual.START_CAPITAL)),
            "dailyMinusContrib": float(daily["daily_pnl"].sum() - contrib["pnl"].sum()),
        })
        print("CRISIS_SLEEVE", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_residual_crisis_sleeve.py",
        "engine": "raits/research/stocks_pit_full_residual_reversal_cohorts.py",
        "inputs": [str(SOURCE_SIGNALS), str(residual.DAILY_FEATURES).replace("\\", "/"), str(residual.INTRADAY_0935).replace("\\", "/"), "raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl (SPY bars only)"],
        "pre_registered_variants": VARIANTS,
        "rule": "Use frozen market-residual bottom10/top10 hold3 signals at 0.5x gross. The gated row admits a new cohort only when lagged completed-session SPY overnight20 compounded return is negative; admitted cohorts retain the full three-session hold.",
        "sample_label": "Diagnostic on touched research sample 2018-2024. No 2025-2026 opened.",
        "selection_warning": "The source sleeve was identified as 2022-positive on this same sample; conditional use is diagnostic and cannot establish clean OOS crisis alpha.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
