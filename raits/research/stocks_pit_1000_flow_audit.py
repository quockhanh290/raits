from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "STOCKS_PIT_1000_FLOW_2026-10-02"
SCRIPT = Path("raits/research/stocks_pit_1000_flow_replay.py")
PREREG = Path("STOCKS_PIT_1000_FLOW_PREREG_2026-10-02.json")
FEATURES = Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022/causal_features_pre1000.parquet")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    manifest = json.loads(Path(f"{PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    selection = json.loads(Path(f"{PREFIX}_SELECTION.json").read_text(encoding="ascii"))
    dev = pd.read_csv(f"{PREFIX}_DEVELOPMENT.csv")
    daily = pd.read_csv(f"{PREFIX}_DAILY.csv", parse_dates=["date"])
    trades = pd.read_csv(f"{PREFIX}_TRADES.csv", parse_dates=["date"])
    contrib = pd.read_csv(f"{PREFIX}_TICKER_CONTRIB.csv", parse_dates=["date"])
    qa = pd.read_csv(f"{PREFIX}_QA.csv")
    features = pd.read_parquet(FEATURES, columns=["date", "ticker", "max_signal_sip_timestamp", "signal_end_ns"])
    base = daily[daily["cost_bps"].eq(4.0)].copy()
    yearly = base.assign(year=base["date"].dt.year).groupby(["variant", "year"], as_index=False).agg(
        pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"), tradingCost=("trading_cost", "sum"),
        activeDays=("trade_legs", lambda x: int(x.gt(0).sum())), tradeLegs=("trade_legs", "sum"),
        minDdDollar=("dd_dollar", "min"), minDdPct=("dd_pct", "min"))
    yearly.to_csv(f"{PREFIX}_AUDIT_YEARLY.csv", index=False)
    concentration = []
    for variant, group in contrib[contrib["cost_bps"].eq(4.0)].groupby("variant"):
        by = group.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
        positive = by[by.gt(0)]; total = float(positive.sum())
        row = {"variant": variant, "tickers": len(by),
               "effectiveTickerCount": float(total**2 / positive.pow(2).sum()) if total > 0 else 0.0}
        for n in (1, 3, 5, 10):
            row[f"top{n}PositiveShare"] = float(positive.head(n).sum() / total) if total > 0 else np.nan
        concentration.append(row)
    pd.DataFrame(concentration).to_csv(f"{PREFIX}_AUDIT_CONCENTRATION.csv", index=False)
    execution = trades.groupby("variant", as_index=False).agg(tradeLegs=("ticker", "size"), activeDays=("date", "nunique"),
        maxAbsWeight=("target_weight", "max"), fallbackExitLegs=("exit_fallback", "sum"))
    execution["maxAdvFraction"] = execution["variant"].map(base.groupby("variant")["max_order_adv_fraction"].max())
    execution.to_csv(f"{PREFIX}_AUDIT_EXECUTION.csv", index=False)
    sic = trades.groupby(["variant", "date", "sic_description"]).size()
    day_names = trades.groupby(["variant", "date"]).size()
    summary = {
        "scriptHash": sha256(SCRIPT), "manifestScriptHash": manifest["scriptHash"],
        "scriptHashMatch": sha256(SCRIPT) == manifest["scriptHash"],
        "preregHash": sha256(PREREG), "manifestPreregHash": manifest["preregistrationHash"],
        "preregHashMatch": sha256(PREREG) == manifest["preregistrationHash"],
        "featureHash": sha256(FEATURES), "manifestFeatureHash": manifest["inputs"][str(FEATURES).replace("\\", "/")],
        "featureHashMatch": sha256(FEATURES) == manifest["inputs"][str(FEATURES).replace("\\", "/")],
        "developmentRows": len(dev), "developmentPasses": int(dev["developmentPass"].sum()),
        "dailyMaxDate": str(daily["date"].max().date()), "tradeMaxDate": str(trades["date"].max().date()),
        "post2021PerformanceRows": int(daily["date"].gt("2021-12-31").sum() + trades["date"].gt("2021-12-31").sum()),
        "featureClockViolations": int(features["max_signal_sip_timestamp"].ge(features["signal_end_ns"]).sum()),
        "sicCapViolations": int(sic.gt(1).sum()), "nameCountViolations": int(day_names.gt(3).sum()),
        "weightViolations": int((trades["target_weight"] - 0.20).abs().gt(1e-12).sum()),
        "advCapViolations": int(base["max_order_adv_fraction"].gt(0.01 + 1e-12).sum()),
        "maxReconciliationError": float(qa[["dailyMinusEnding", "dailyMinusContrib"]].abs().to_numpy().max()),
        "selection": selection, "validationOpened": bool(selection["validationOpened"]),
        "post2022Consumed": False, "pass": False,
    }
    summary["pass"] = bool(summary["scriptHashMatch"] and summary["preregHashMatch"] and summary["featureHashMatch"]
        and summary["developmentRows"] == 5 and summary["developmentPasses"] == 0
        and summary["post2021PerformanceRows"] == 0 and summary["featureClockViolations"] == 0
        and summary["sicCapViolations"] == 0 and summary["nameCountViolations"] == 0
        and summary["weightViolations"] == 0 and summary["advCapViolations"] == 0
        and summary["maxReconciliationError"] < 1e-8 and not summary["validationOpened"])
    Path(f"{PREFIX}_AUDIT_MANIFEST.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="ascii")
    print(json.dumps(summary, indent=2))
    if not summary["pass"]:
        raise SystemExit("Replay audit failed")


if __name__ == "__main__":
    main()
