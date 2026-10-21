from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_adaptive_opening_policy as policy
import stocks_pit_open_trade_flow as source


PREFIX = policy.PREFIX
OUTPUT = Path(f"{PREFIX}_AUDIT.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def close(left: float, right: float, tolerance: float = 1e-8) -> bool:
    return bool(np.isclose(left, right, rtol=0.0, atol=tolerance, equal_nan=True))


def main() -> None:
    summary = pd.read_csv(f"{PREFIX}_SUMMARY.csv")
    trades = pd.read_csv(f"{PREFIX}_TRADES.csv", parse_dates=["date"])
    daily = pd.read_csv(f"{PREFIX}_DAILY.csv", parse_dates=["date"])
    contrib = pd.read_csv(f"{PREFIX}_TICKER_CONTRIB.csv", parse_dates=["date"])
    yearly = pd.read_csv(f"{PREFIX}_YEARLY.csv")
    vintages = pd.read_csv(f"{PREFIX}_MODEL_VINTAGES.csv", parse_dates=["trainStart", "trainEnd"])
    selection = json.loads(Path(f"{PREFIX}_SELECTION.json").read_text(encoding="ascii"))
    manifest = json.loads(Path(f"{PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    prereg = json.loads(policy.PREREG.read_text(encoding="ascii"))
    checks: list[tuple[str, bool]] = []

    def check(name: str, value: bool) -> None:
        checks.append((name, bool(value)))

    check("prereg_frozen", prereg["frozen_before_performance"])
    check("script_hash", prereg["script_hash"] == sha256(Path(policy.__file__)))
    check("manifest_script_hash", manifest["scriptHash"] == sha256(Path(policy.__file__)))
    check("manifest_prereg_hash", manifest["preregistrationHash"] == sha256(policy.PREREG))
    check("feature_hash", manifest["featureCacheHash"] == sha256(source.FEATURES))
    check("exact_clock_hash", manifest["exactClockHash"] == sha256(source.EXACT_CLOCK))
    check("one_policy", len(summary) == 1 and summary.iloc[0]["policy"] == policy.POLICY)
    check("validation_closed", not selection["validationOpened"] and summary["scope"].eq("development").all())
    check("no_post2021_performance", trades["date"].max() <= policy.DEVELOPMENT_END
          and daily["date"].max() <= policy.DEVELOPMENT_END and contrib["date"].max() <= policy.DEVELOPMENT_END)
    check("six_legs", trades.groupby("date").size().eq(6).all())
    check("balanced_sides", trades.groupby(["date", "side"]).size().eq(3).all())
    check("sic_cap", trades.groupby(["date", "side"])["sic_description"].nunique().eq(3).all())
    check("model_month", (trades["model_month"].astype(str) == trades["date"].dt.to_period("M").astype(str)).all())
    check("entry_exact", np.allclose(trades["entry_price"], trades["open_0940"], rtol=0.0, atol=0.0))
    check("causal_exit", trades["exit_clock"].isin(["15:55", "16:00"]).all())
    check("scale_set", trades["scale"].isin([0.5, 1.0]).all())
    check("threshold_half", trades["calibrated_book_edge"].ge(policy.HALF_SCALE_EDGE - 1e-15).all())
    full = trades["scale"].eq(1.0)
    half = trades["scale"].eq(0.5)
    check("threshold_full", trades.loc[full, "calibrated_book_edge"].ge(policy.FULL_SCALE_EDGE - 1e-15).all())
    check("threshold_half_band", trades.loc[half, "calibrated_book_edge"].lt(policy.FULL_SCALE_EDGE).all())
    gross_by_day = trades.groupby("date")["target_weight"].apply(lambda x: float(x.abs().sum()))
    scale_by_day = trades.groupby("date")["scale"].first()
    check("gross_matches_scale", np.allclose(gross_by_day, scale_by_day, rtol=0.0, atol=1e-12))
    check("equal_weights", np.allclose(trades["target_weight"].abs(), trades["scale"] / 6.0,
                                       rtol=0.0, atol=1e-12))
    active_vintages = set(vintages.loc[vintages["status"].eq("active"), "month"].astype(str))
    check("active_vintage_only", set(trades["model_month"].astype(str)).issubset(active_vintages))
    check("train_before_month", (vintages["trainEnd"] < pd.PeriodIndex(vintages["month"], freq="M").to_timestamp()).all())
    check("adv_cap", (daily["max_order_adv_fraction"] <= 0.01 + 1e-12).all())

    base_daily = daily[daily["cost_bps"].eq(policy.BASE_COST_BPS_PER_SIDE)].copy()
    base_contrib = contrib[contrib["cost_bps"].eq(policy.BASE_COST_BPS_PER_SIDE)].copy()
    stress_daily = daily[daily["cost_bps"].eq(policy.STRESS_COST_BPS_PER_SIDE)].copy()
    recomputed = source.metrics(base_daily)
    concentration = source.concentration(base_contrib)
    row = summary.iloc[0]
    for key in ("pnl", "grossPnl", "cagr", "sharpe", "ddDollar", "ddPct", "activeDays",
                "tradeLegs", "tradingCost", "borrowCost", "maxOrderAdvFraction"):
        check(f"summary_{key}", close(float(row[key]), float(recomputed[key])))
    for key in ("effectiveTickerCount", "top1PositiveShare", "top3PositiveShare",
                "top5PositiveShare", "top10PositiveShare"):
        check(f"concentration_{key}", close(float(row[key]), float(concentration[key])))
    check("stress_pnl", close(float(row["stressPnl"]), float(source.metrics(stress_daily)["pnl"])))
    check("daily_ending_reconcile", close(float(base_daily["daily_pnl"].sum()),
          float(base_daily.sort_values("date").iloc[-1]["equity"] - source.INITIAL_EQUITY)))
    check("ticker_reconcile", close(float(base_daily["daily_pnl"].sum()), float(base_contrib["net_pnl"].sum())))
    check("yearly_reconcile", close(float(yearly[yearly["cost_bps"].eq(policy.BASE_COST_BPS_PER_SIDE)]["pnl"].sum()),
          float(base_daily["daily_pnl"].sum())))
    gate = bool(
        row["activeDays"] >= 100 and row["tradeLegs"] >= 600 and row["cagr"] >= 0.05
        and row["sharpe"] >= 1.0 and row["ddPct"] >= -0.10 and row["positiveYears"] >= 2
        and row["grossEdgeBpsPerActiveDay"] >= 12.0 and row["stressPnl"] > 0
        and row["effectiveTickerCount"] >= 30 and row["top10PositiveShare"] <= 0.50
    )
    check("development_gate", gate == bool(row["developmentPass"]) == selection["developmentPass"])
    failures = [name for name, passed in checks if not passed]
    result = {
        "status": "PASS" if not failures else "FAIL",
        "checks": len(checks), "failures": failures,
        "developmentPass": selection["developmentPass"],
        "validationOpened": selection["validationOpened"],
        "performanceMaxDate": str(daily["date"].max().date()),
        "activeMonths": int(vintages["status"].eq("active").sum()),
        "activeDays": int(row["activeDays"]),
        "scriptHash": sha256(Path(policy.__file__)),
        "auditScriptHash": sha256(Path(__file__)),
        "preregistrationHash": sha256(policy.PREREG),
        "post2022Consumed": False,
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))
    if failures:
        raise RuntimeError(f"Audit failures: {failures}")


if __name__ == "__main__":
    main()
