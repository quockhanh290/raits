from __future__ import annotations

from pathlib import Path

import pandas as pd

import stocks_polygon62_regime_overlay_sweep as overlay
import stocks_polygon_2018_2024_no_ml_pipeline as poly


OUT_PREFIX = "STOCKS_POLYGON62_LOCAL_HOLD5_VOL20"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY_2018_2024.csv")
EQUITY_OUT = Path(f"{OUT_PREFIX}_EQUITY_2018_2024.csv")
TRADES_OUT = Path(f"{OUT_PREFIX}_TRADES_2018_2024.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY_2018_2024.csv")

PORTFOLIOS = {
    "A_polygon62_local_hold5_vol20": poly.LEAD_PORTFOLIOS["A_polygon62_no_intraday_cap40"],
    "B_polygon62_local_hold5_vol20": poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"],
}


def nth_exit_dates(px: pd.DataFrame, hold: int) -> pd.DataFrame:
    out = px[["date", "ticker"]].drop_duplicates().sort_values(["ticker", "date"]).copy()
    out[f"exit_date_{hold}"] = out.groupby("ticker")["date"].shift(-(hold - 1))
    return out


def candidate_signals(daily_px: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    exit5 = nth_exit_dates(daily_px, 5)
    out = signals.merge(exit5, on=["date", "ticker"], how="left")
    mask = (
        out["sleeve"].eq("local_xs_full_s10")
        & out["vol20_020"].astype(bool)
        & out["exit_date_5"].notna()
    )
    out.loc[mask, "exit_date"] = out.loc[mask, "exit_date_5"]
    out.loc[mask, "hold_days"] = 5
    out["candidateRule"] = ""
    out.loc[mask, "candidateRule"] = "local_hold5_when_spy_prev_vol20_ge_2pct"
    return out.drop(columns=["exit_date_5"])


def yearly_metrics(equity: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for portfolio, port_eq in equity.groupby("portfolio", sort=True):
        for year, group in port_eq.assign(year=port_eq["date"].dt.year).groupby("year", sort=True):
            curve = group["daily_pnl"].cumsum()
            rows.append(
                {
                    "portfolio": portfolio,
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
    daily_px, signals = overlay.load_inputs()
    signals = candidate_signals(daily_px, signals)

    summaries = []
    equities = []
    trades = []
    for name, cfg in PORTFOLIOS.items():
        summary, eq, tr = poly.simulate(name, cfg, signals, daily_px)
        summaries.append(summary)
        equities.append(eq)
        trades.append(tr)
        changed = signals[
            signals["sleeve"].eq("local_xs_full_s10")
            & signals["candidateRule"].ne("")
            & signals["date"].between(pd.Timestamp(summary["start"]), pd.Timestamp(summary["end"]))
        ]
        print(name, summary, "local_hold5_signal_rows", len(changed), flush=True)

    summary_df = pd.DataFrame(summaries)
    equity_df = pd.concat(equities, ignore_index=True)
    trades_df = pd.concat(trades, ignore_index=True)

    summary_df.to_csv(SUMMARY_OUT, index=False)
    equity_df.to_csv(EQUITY_OUT, index=False)
    trades_df.to_csv(TRADES_OUT, index=False)
    yearly_metrics(equity_df).to_csv(YEARLY_OUT, index=False)
    print("WROTE", SUMMARY_OUT, EQUITY_OUT, TRADES_OUT, YEARLY_OUT)


if __name__ == "__main__":
    main()
