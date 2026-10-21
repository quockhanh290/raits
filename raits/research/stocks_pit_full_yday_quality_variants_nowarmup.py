from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_no_intraday_replay_nowarmup as base


OUT_PREFIX = "STOCKS_PIT_FULL_YDAY_QUALITY_VARIANTS_NOWARMUP_2026-09-13"
PIT_FILTER = base.pit_gate.PIT_FILTER


VARIANTS = {
    "base": lambda sig: pd.Series(True, index=sig.index),
    "yday_price_ge_10": lambda sig: (~sig["sleeve"].eq("yday_ex6_actual")) | (sig["prior_close"] >= 10),
    "yday_price_ge_15": lambda sig: (~sig["sleeve"].eq("yday_ex6_actual")) | (sig["prior_close"] >= 15),
    "yday_vol20_le_6": lambda sig: (~sig["sleeve"].eq("yday_ex6_actual")) | (sig["vol20_pre"] <= 0.06),
    "yday_price_ge_10_vol20_le_6": lambda sig: (~sig["sleeve"].eq("yday_ex6_actual"))
    | ((sig["prior_close"] >= 10) & (sig["vol20_pre"] <= 0.06)),
    "yday_price_ge_15_vol20_le_6": lambda sig: (~sig["sleeve"].eq("yday_ex6_actual"))
    | ((sig["prior_close"] >= 15) & (sig["vol20_pre"] <= 0.06)),
}


def add_quality_columns(signals: pd.DataFrame) -> pd.DataFrame:
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    quality = daily[["date", "ticker", "vol20_pre", "ret60_pre"]].copy()
    pit = pd.read_parquet(PIT_FILTER, columns=["date", "ticker", "prior_close", "adv20", "liquidity_metric_source"])
    pit["date"] = pd.to_datetime(pit["date"])
    pit = pit.drop_duplicates(["date", "ticker"])
    out = signals.merge(quality, on=["date", "ticker"], how="left").merge(pit, on=["date", "ticker"], how="left")
    return out


def main() -> None:
    base.configure_poly()
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    intraday = pd.read_pickle(base.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])

    if not base.BROAD_TRADES.exists():
        base.poly.build_broad_trades(daily)
    if not base.LOCAL_TRADES.exists():
        base.poly.build_local_trades(daily)
    if not base.YDAY_TRADES.exists():
        base.build_yday_trades_from_daily(daily)

    daily_px = base.poly.load_daily_prices_from_polygon(daily)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    intraday_px = intraday[["date", "ticker", "open930", "entry935", "exit1555"]].copy()
    signals = base.load_signals_no_intraday(daily_px, intraday_px)
    gate = base.pit_gate.load_pit_gate()
    gated_signals, gate_qa, _, _ = base.pit_gate.apply_pit_gate(signals, gate)
    gated_signals = add_quality_columns(gated_signals)

    summaries = []
    yearly_rows = []
    qa_rows = []
    for variant, mask_fn in VARIANTS.items():
        variant_signals = gated_signals[mask_fn(gated_signals)].copy()
        for sleeve, group in gated_signals.groupby("sleeve", sort=True):
            kept = variant_signals[variant_signals["sleeve"].eq(sleeve)]
            qa_rows.append(
                {
                    "variant": variant,
                    "sleeve": sleeve,
                    "signals_before": int(len(group)),
                    "signals_after": int(len(kept)),
                    "removed": int(len(group) - len(kept)),
                }
            )
        for portfolio_name, cfg in base.PORTFOLIOS.items():
            name = portfolio_name.replace("nowarmup", f"{variant}_nowarmup")
            summary, eq, _ = base.poly.simulate(name, cfg, variant_signals, daily_px)
            summary["variant"] = variant
            summaries.append(summary)
            for year, group in eq.assign(year=eq["date"].dt.year).groupby("year", sort=True):
                std = float(group["daily_pnl"].std())
                curve = group["daily_pnl"].cumsum()
                yearly_rows.append(
                    {
                        "variant": variant,
                        "portfolio": name,
                        "year": int(year),
                        "pnl": float(group["daily_pnl"].sum()),
                        "ddSubset": float((curve - curve.cummax()).min()),
                        "sharpe": float(group["daily_pnl"].mean() / std * np.sqrt(252)) if std > 0 else np.nan,
                    }
                )
            print("VARIANT", variant, name, summary, flush=True)

    pd.DataFrame(summaries).to_csv(f"{OUT_PREFIX}_SUMMARY.csv", index=False)
    pd.DataFrame(yearly_rows).to_csv(f"{OUT_PREFIX}_YEARLY.csv", index=False)
    pd.DataFrame(qa_rows).to_csv(f"{OUT_PREFIX}_SIGNAL_QA.csv", index=False)
    print("WROTE", OUT_PREFIX)


if __name__ == "__main__":
    main()
