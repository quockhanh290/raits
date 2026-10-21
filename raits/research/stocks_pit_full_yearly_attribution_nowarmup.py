from __future__ import annotations

from pathlib import Path

import pandas as pd

import stocks_pit_full_no_intraday_replay_nowarmup as base
from stocks_pit_full_ticker_fallback_impact_nowarmup import VARIANTS, add_quality_columns


OUT_PREFIX = "STOCKS_PIT_FULL_YEARLY_ATTRIBUTION_NOWARMUP_2026-09-13"
YDAY = "yday_ex6_actual"

SCENARIOS = {
    "base_all": ("base", "all"),
    "base_drop_any_fallback": ("base", "drop_any_fallback"),
    "drop_yday": ("drop_yday", "all"),
    "price_15_100_drop_any_fallback": ("price_15_100", "drop_any_fallback"),
    "ret60_le_neg20_drop_any_fallback": ("ret60_le_neg20", "drop_any_fallback"),
    "ret60_le_neg20_price_15_100_drop_any_fallback": ("ret60_le_neg20_price_15_100", "drop_any_fallback"),
}


def scenario_mask(signals: pd.DataFrame, variant: str, fallback_policy: str) -> pd.Series:
    if variant == "drop_yday":
        mask = ~signals["sleeve"].eq(YDAY)
    else:
        mask = VARIANTS[variant](signals)
    if fallback_policy == "drop_any_fallback":
        mask &= ~signals["is_ticker_fallback"]
    elif fallback_policy == "drop_yday_fallback":
        mask &= ~(signals["sleeve"].eq(YDAY) & signals["is_ticker_fallback"])
    return mask


def max_drawdown_period(eq: pd.DataFrame) -> tuple[float, pd.Timestamp, pd.Timestamp]:
    curve = eq[["date", "daily_pnl"]].copy()
    curve["cum"] = curve["daily_pnl"].cumsum()
    curve["peak"] = curve["cum"].cummax()
    curve["dd"] = curve["cum"] - curve["peak"]
    trough_idx = curve["dd"].idxmin()
    trough = curve.loc[trough_idx, "date"]
    peak_level = curve.loc[trough_idx, "peak"]
    peak_rows = curve.loc[:trough_idx]
    peak = peak_rows[peak_rows["cum"].eq(peak_level)].iloc[-1]["date"]
    return float(curve.loc[trough_idx, "dd"]), pd.Timestamp(peak), pd.Timestamp(trough)


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
    gated_signals, _, _, _ = base.pit_gate.apply_pit_gate(signals, gate)
    gated_signals = add_quality_columns(gated_signals)
    gated_signals["is_ticker_fallback"] = gated_signals["liquidity_metric_source"].fillna("").eq("ticker_fallback")

    cfg = base.PORTFOLIOS["B_pit_full_no_intraday_nowarmup_cap40"]
    yearly_rows = []
    sleeve_year_rows = []
    dd_period_rows = []
    dd_sleeve_rows = []

    for scenario, (variant, fallback_policy) in SCENARIOS.items():
        scenario_signals = gated_signals[scenario_mask(gated_signals, variant, fallback_policy)].copy()
        summary, eq, trades = base.poly.simulate(f"B_{scenario}", cfg, scenario_signals, daily_px)
        eq["year"] = eq["date"].dt.year
        trades["year"] = pd.to_datetime(trades["date"]).dt.year

        for year, group in eq.groupby("year", sort=True):
            dd, peak, trough = max_drawdown_period(group.reset_index(drop=True))
            yearly_rows.append(
                {
                    "scenario": scenario,
                    "year": int(year),
                    "pnl": float(group["daily_pnl"].sum()),
                    "dd": dd,
                    "dd_peak": peak.date(),
                    "dd_trough": trough.date(),
                }
            )
            period_trades = trades[
                (pd.to_datetime(trades["date"]) >= peak) & (pd.to_datetime(trades["date"]) <= trough)
            ]
            for sleeve, sg in period_trades.groupby("sleeve", sort=True):
                dd_sleeve_rows.append(
                    {
                        "scenario": scenario,
                        "year": int(year),
                        "dd_peak": peak.date(),
                        "dd_trough": trough.date(),
                        "sleeve": sleeve,
                        "period_trades": int(len(sg)),
                        "period_trade_pnl": float(sg["pnl"].sum()),
                    }
                )

        for keys, group in trades.groupby(["year", "sleeve"], sort=True):
            year, sleeve = keys
            sleeve_year_rows.append(
                {
                    "scenario": scenario,
                    "year": int(year),
                    "sleeve": sleeve,
                    "trades": int(len(group)),
                    "pnl": float(group["pnl"].sum()),
                    "avg_pnl": float(group["pnl"].mean()),
                    "win_rate": float((group["pnl"] > 0).mean()),
                }
            )
        print("SCENARIO", scenario, summary, flush=True)

    pd.DataFrame(yearly_rows).to_csv(f"{OUT_PREFIX}_YEARLY_DD.csv", index=False)
    pd.DataFrame(sleeve_year_rows).to_csv(f"{OUT_PREFIX}_SLEEVE_YEAR.csv", index=False)
    pd.DataFrame(dd_period_rows).to_csv(f"{OUT_PREFIX}_DD_PERIODS.csv", index=False)
    pd.DataFrame(dd_sleeve_rows).to_csv(f"{OUT_PREFIX}_DD_PERIOD_SLEEVE_TRADES.csv", index=False)
    print("WROTE", OUT_PREFIX)


if __name__ == "__main__":
    main()
