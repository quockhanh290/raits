from __future__ import annotations

from pathlib import Path

import json
import math

import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_RESIDUAL_CRISIS_BRIDGE_2026-09-17"
LEAD_DAILY = Path("STOCKS_PIT_FULL_LEAD_CANDIDATE_EVENTTIME_AUDIT_2026-09-17_DAILY.csv")
CRISIS_DAILY = Path("STOCKS_PIT_FULL_RESIDUAL_CRISIS_SLEEVE_2026-09-17_DAILY.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")
START_CAPITAL = 100_000.0


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    return float((equity - peak).min()), float((equity / peak - 1).min())


def main() -> None:
    lead = pd.read_csv(LEAD_DAILY, parse_dates=["date"])
    lead = lead[lead["scenario"].eq("base")].sort_values("date").copy()
    lead["prior_equity"] = lead["equity"] - lead["daily_pnl"]
    lead["lead_ret"] = lead["daily_pnl"] / lead["prior_equity"]
    crisis = pd.read_csv(CRISIS_DAILY, parse_dates=["date"])
    crisis = crisis[crisis["variant"].eq("overnight20_negative_05x")].sort_values("date").copy()
    crisis["prior_equity"] = crisis["equity"] - crisis["daily_pnl"]
    crisis["crisis_ret"] = crisis["daily_pnl"] / crisis["prior_equity"]
    x = lead[["date", "lead_ret", "max_gross"]].merge(
        crisis[["date", "crisis_ret", "gross_exposure"]], on="date", how="inner", validate="one_to_one"
    )

    rows = []
    summaries = []
    yearly = []
    for variant in ("lead_control", "lead_plus_crisis05"):
        equity = START_CAPITAL
        daily_rows = []
        for row in x.itertuples(index=False):
            crisis_ret = float(row.crisis_ret) if variant == "lead_plus_crisis05" else 0.0
            crisis_gross = float(row.gross_exposure) if variant == "lead_plus_crisis05" else 0.0
            incremental_financing_ret = (
                max(float(row.max_gross) + crisis_gross - 1.0, 0.0)
                - max(float(row.max_gross) - 1.0, 0.0)
            ) * 0.025 / 252.0
            daily_ret = float(row.lead_ret) + crisis_ret - incremental_financing_ret
            pnl = equity * daily_ret
            equity += pnl
            daily_rows.append({"variant": variant, "date": row.date, "daily_pnl": pnl, "equity": equity, "lead_ret": row.lead_ret, "crisis_ret": crisis_ret, "incremental_financing_ret": incremental_financing_ret, "gross_proxy": float(row.max_gross) + crisis_gross})
        daily = pd.DataFrame(daily_rows)
        dd, dd_pct = max_drawdown(daily["equity"])
        years = (daily["date"].max() - daily["date"].min()).days / 365.25
        summaries.append({
            "variant": variant,
            "pnl": float(equity - START_CAPITAL),
            "cagr": float((equity / START_CAPITAL) ** (1.0 / years) - 1.0),
            "ddDollar": dd,
            "ddPct": dd_pct,
            "sharpe": float(daily["daily_pnl"].mean() / daily["daily_pnl"].std() * math.sqrt(252)),
            "incrementalFinancing": float((daily["incremental_financing_ret"] * (daily["equity"] - daily["daily_pnl"])).sum()),
            "maxGrossProxy": float(daily["gross_proxy"].max()),
        })
        daily["year"] = daily["date"].dt.year
        for year, group in daily.groupby("year"):
            curve = START_CAPITAL + group["daily_pnl"].cumsum()
            yd, ydp = max_drawdown(curve)
            yearly.append({"variant": variant, "year": int(year), "pnl": float(group["daily_pnl"].sum()), "ddDollarSubset": yd, "ddPctSubset": ydp})
        rows.append(daily)
        print("CRISIS_BRIDGE", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.concat(rows, ignore_index=True).to_csv(DAILY_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_residual_crisis_bridge.py",
        "inputs": [str(LEAD_DAILY), str(CRISIS_DAILY)],
        "method": "Shared-equity daily bridge: apply lead and frozen gated-crisis source returns to one opening equity and charge incremental 2.5% financing on proxy gross above the lead gross.",
        "limitation": "Lead and crisis source clocks differ inside the day (lead has 09:35 and 15:55 marks; crisis is 09:35-to-09:35). This is a high-signal bridge diagnostic, not final constituent event-time execution evidence.",
        "sample_label": "Touched research 2018-2024 only. No 2025-2026 opened.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
