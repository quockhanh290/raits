from __future__ import annotations

from pathlib import Path

import pandas as pd

import stocks_polygon62_regime_overlay_sweep as overlay
import stocks_polygon_2018_2024_no_ml_pipeline as poly


OUT_PREFIX = "STOCKS_POLYGON62_LOCAL_HOLD_VOL20_FAIR_SIZING"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY_2018_2024.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY_2018_2024.csv")

PORTFOLIOS = {
    "A": poly.LEAD_PORTFOLIOS["A_polygon62_no_intraday_cap40"],
    "B": poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"],
}


def nth_exit_dates(px: pd.DataFrame, hold: int) -> pd.DataFrame:
    out = px[["date", "ticker"]].drop_duplicates().sort_values(["ticker", "date"]).copy()
    out[f"exit_date_{hold}"] = out.groupby("ticker")["date"].shift(-(hold - 1))
    return out


def apply_variant(daily_px: pd.DataFrame, signals: pd.DataFrame, hold: int | None, sizing_hold: int | None) -> pd.DataFrame:
    if hold is None:
        return signals.copy()
    exits = nth_exit_dates(daily_px, hold)
    out = signals.merge(exits, on=["date", "ticker"], how="left")
    mask = (
        out["sleeve"].eq("local_xs_full_s10")
        & out["vol20_020"].astype(bool)
        & out[f"exit_date_{hold}"].notna()
    )
    out.loc[mask, "exit_date"] = out.loc[mask, f"exit_date_{hold}"]
    out.loc[mask, "candidate_exit_hold"] = hold
    if sizing_hold is not None:
        out.loc[mask, "hold_days"] = sizing_hold
        out.loc[mask, "candidate_sizing_hold"] = sizing_hold
    return out.drop(columns=[f"exit_date_{hold}"])


def yearly_metrics(equity: pd.DataFrame, variant: str) -> pd.DataFrame:
    rows = []
    for portfolio, group_port in equity.groupby("portfolio", sort=True):
        for year, group in group_port.assign(year=group_port["date"].dt.year).groupby("year", sort=True):
            curve = group["daily_pnl"].cumsum()
            rows.append(
                {
                    "portfolio": portfolio,
                    "variant": variant,
                    "year": int(year),
                    "days": int(len(group)),
                    "pnl": float(group["daily_pnl"].sum()),
                    "ddSubset": float((curve - curve.cummax()).min()),
                    "sharpe": float(group["daily_pnl"].mean() / group["daily_pnl"].std() * (252**0.5))
                    if group["daily_pnl"].std() > 0
                    else None,
                    "avgGross": float(group["gross"].mean()),
                    "maxGross": float(group["gross"].max()),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    daily_px, base_signals = overlay.load_inputs()
    variants = {
        "base_hold20": (None, None),
        "hold5_engine_sizing": (5, 5),
        "hold5_fixed_hold20_sizing": (5, 20),
        "hold10_engine_sizing": (10, 10),
        "hold10_fixed_hold20_sizing": (10, 20),
    }
    summary_rows = []
    yearly_frames = []
    for variant, (exit_hold, sizing_hold) in variants.items():
        signals = apply_variant(daily_px, base_signals, exit_hold, sizing_hold)
        for prefix, cfg in PORTFOLIOS.items():
            name = f"{prefix}_polygon62_{variant}"
            summary, eq, _ = poly.simulate(name, cfg, signals, daily_px)
            summary_rows.append({"variant": variant, "exitHold": exit_hold or 20, "sizingHold": sizing_hold or 20, **summary})
            yearly_frames.append(yearly_metrics(eq, variant))
            print(name, f"pnl={summary['pnl']:.2f}", f"dd={summary['dd']:.2f}", f"sharpe={summary['sharpe']:.3f}", flush=True)
    pd.DataFrame(summary_rows).to_csv(SUMMARY_OUT, index=False)
    pd.concat(yearly_frames, ignore_index=True).to_csv(YEARLY_OUT, index=False)
    print("WROTE", SUMMARY_OUT, YEARLY_OUT)


if __name__ == "__main__":
    main()
