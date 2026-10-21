from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


SOURCE = Path("STOCKS_SEC_FORM4_PURCHASE_DRIFT_DEV_2026-09-24_DAILY.csv")
BENCHMARK = Path("STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14_DAILY.csv")
OUT = Path("STOCKS_SEC_FORM4_PURCHASE_DRIFT_DEV_2026-09-24_BENCHMARK_AUDIT.csv")
MANIFEST = Path("STOCKS_SEC_FORM4_PURCHASE_DRIFT_DEV_2026-09-24_BENCHMARK_AUDIT_MANIFEST.json")


def main() -> None:
    daily = pd.read_csv(SOURCE, parse_dates=["date"])
    daily = daily[daily["scenario"].str.endswith("_cost4")].copy()
    daily["portfolio_return"] = daily["daily_pnl"] / (daily["equity"] - daily["daily_pnl"])
    benchmark = pd.read_csv(BENCHMARK, parse_dates=["date"])
    benchmark = benchmark[benchmark["variant"].eq("broad_pit_equal_weight")][["date", "daily_ret"]]
    rows = []
    for (scenario, stage), group in daily.groupby(["scenario", "bookStage"], sort=True):
        merged = group.merge(benchmark, on="date", how="inner", validate="one_to_one").dropna(
            subset=["portfolio_return", "daily_ret"]
        )
        market_variance = float(merged["daily_ret"].var())
        beta = float(merged[["portfolio_return", "daily_ret"]].cov().iloc[0, 1] / market_variance)
        residual = merged["portfolio_return"] - beta * merged["daily_ret"]
        correlation = float(merged["portfolio_return"].corr(merged["daily_ret"]))
        rows.append(
            {
                "scenario": scenario,
                "bookStage": stage,
                "days": len(merged),
                "marketBeta": beta,
                "correlation": correlation,
                "rSquared": correlation**2,
                "annualizedPortfolioMeanReturn": float(merged["portfolio_return"].mean() * 252),
                "annualizedBenchmarkMeanReturn": float(merged["daily_ret"].mean() * 252),
                "annualizedResidualAlpha": float(residual.mean() * 252),
                "residualSharpe": float(residual.mean() / residual.std() * np.sqrt(252))
                if residual.std() > 0
                else float("nan"),
            }
        )
    result = pd.DataFrame(rows)
    result.to_csv(OUT, index=False)
    manifest = {
        "script": "raits/research/stocks_sec_form4_purchase_drift_benchmark_audit.py",
        "purpose": "Fixed post-result attribution only; cannot change family selection.",
        "source": str(SOURCE),
        "benchmark": str(BENCHMARK),
        "output": str(OUT),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(result.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
