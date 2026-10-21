from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "STOCKS_PIT_OPEN_TRADE_FLOW_2026-10-01"
SCRIPT = Path("raits/research/stocks_pit_open_trade_flow.py")
PREREG = Path("STOCKS_PIT_OPEN_TRADE_FLOW_PREREG_2026-10-01.json")
FEATURES = Path("raits/data/cache/polygon_stock_trades_open_2018_2022/causal_features_pre0935.parquet")
MANIFEST = Path(f"{PREFIX}_MANIFEST.json")
SELECTION = Path(f"{PREFIX}_SELECTION.json")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="ascii"))
    selection = json.loads(SELECTION.read_text(encoding="ascii"))
    development = pd.read_csv(f"{PREFIX}_DEVELOPMENT.csv")
    daily = pd.read_csv(f"{PREFIX}_DAILY.csv", parse_dates=["date"])
    trades = pd.read_csv(f"{PREFIX}_TRADES.csv", parse_dates=["date"])
    contrib = pd.read_csv(f"{PREFIX}_TICKER_CONTRIB.csv", parse_dates=["date"])
    qa = pd.read_csv(f"{PREFIX}_QA.csv")
    features = pd.read_parquet(FEATURES, columns=["date", "ticker", "max_signal_sip_timestamp", "signal_end_ns"])

    base_daily = daily[daily["cost_bps"].eq(4.0)].copy()
    yearly = base_daily.assign(year=base_daily["date"].dt.year).groupby(["variant", "year"], as_index=False).agg(
        pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"), tradingCost=("trading_cost", "sum"),
        borrowCost=("borrow_cost", "sum"), activeDays=("trade_legs", lambda x: int(x.gt(0).sum())),
        tradeLegs=("trade_legs", "sum"), minDdDollar=("dd_dollar", "min"), minDdPct=("dd_pct", "min"),
    )
    yearly.to_csv(f"{PREFIX}_AUDIT_YEARLY.csv", index=False)

    concentration_rows: list[dict[str, object]] = []
    for variant, group in contrib[contrib["cost_bps"].eq(4.0)].groupby("variant"):
        by = group.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
        positive = by[by.gt(0)]
        total = float(positive.sum())
        row: dict[str, object] = {"variant": variant, "tickers": len(by),
            "effectiveTickerCount": float(total**2 / positive.pow(2).sum()) if total > 0 else 0.0}
        for count in (1, 3, 5, 10):
            row[f"top{count}PositiveShare"] = float(positive.head(count).sum() / total) if total > 0 else np.nan
        concentration_rows.append(row)
    concentration = pd.DataFrame(concentration_rows)
    concentration.to_csv(f"{PREFIX}_AUDIT_CONCENTRATION.csv", index=False)

    execution = trades.groupby("variant", as_index=False).agg(
        tradeLegs=("ticker", "size"), activeDays=("date", "nunique"),
        maxAbsWeight=("target_weight", lambda x: float(x.abs().max())),
        maxAdvFraction=("adv20", lambda _: 0.0),
        fallbackExitLegs=("exit_delay_minutes", lambda x: int(x.gt(0).sum())),
        maxExitDelayMinutes=("exit_delay_minutes", "max"),
    )
    max_adv = base_daily.groupby("variant")["max_order_adv_fraction"].max()
    execution["maxAdvFraction"] = execution["variant"].map(max_adv)
    execution.to_csv(f"{PREFIX}_AUDIT_EXECUTION.csv", index=False)

    side_counts = trades.assign(side=np.sign(trades["target_weight"])).groupby(["variant", "date", "side"]).size()
    sic_counts = trades.assign(side=np.sign(trades["target_weight"])).groupby(
        ["variant", "date", "side", "sic_description"]
    ).size()
    summary = {
        "scriptHash": sha256(SCRIPT),
        "manifestScriptHash": manifest["scriptHash"],
        "scriptHashMatch": sha256(SCRIPT) == manifest["scriptHash"],
        "preregHash": sha256(PREREG),
        "manifestPreregHash": manifest["preregistrationHash"],
        "preregHashMatch": sha256(PREREG) == manifest["preregistrationHash"],
        "featureHash": sha256(FEATURES),
        "manifestFeatureHash": manifest["featureCacheHash"],
        "featureHashMatch": sha256(FEATURES) == manifest["featureCacheHash"],
        "selection": selection,
        "developmentRows": len(development),
        "developmentPasses": int(development["developmentPass"].sum()),
        "dailyMaxDate": str(daily["date"].max().date()),
        "tradeMaxDate": str(trades["date"].max().date()),
        "post2021PerformanceRows": int(daily["date"].gt("2021-12-31").sum() + trades["date"].gt("2021-12-31").sum()),
        "featureRows": len(features),
        "featureClockViolations": int(features["max_signal_sip_timestamp"].ge(features["signal_end_ns"]).sum()),
        "sideCountViolations": int(side_counts.ne(3).sum()),
        "sicCapViolations": int(sic_counts.gt(1).sum()),
        "weightViolations": int((trades["target_weight"].abs() - 1.0 / 6.0).abs().gt(1e-12).sum()),
        "advCapViolations": int(base_daily["max_order_adv_fraction"].gt(0.01 + 1e-12).sum()),
        "maxReconciliationError": float(qa[["dailyMinusEnding", "dailyMinusContrib"]].abs().to_numpy().max()),
        "validationOpened": bool(selection["validationOpened"]),
        "post2022Consumed": False,
        "pass": False,
    }
    summary["pass"] = bool(
        summary["scriptHashMatch"] and summary["preregHashMatch"] and summary["featureHashMatch"]
        and summary["developmentRows"] == 5 and summary["developmentPasses"] == 0
        and summary["post2021PerformanceRows"] == 0 and summary["featureClockViolations"] == 0
        and summary["sideCountViolations"] == 0 and summary["sicCapViolations"] == 0
        and summary["weightViolations"] == 0 and summary["advCapViolations"] == 0
        and summary["maxReconciliationError"] < 1e-8 and not summary["validationOpened"]
    )
    Path(f"{PREFIX}_AUDIT_MANIFEST.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="ascii")
    print(json.dumps(summary, indent=2))
    if not summary["pass"]:
        raise SystemExit("Trade-flow replay audit failed")


if __name__ == "__main__":
    main()
