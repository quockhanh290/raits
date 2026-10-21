from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


PREFIX = "STOCKS_PIT_SECTOR_OVERREACTION_2026-10-02"
PREREG = Path("STOCKS_PIT_SECTOR_OVERREACTION_PREREG_2026-10-02.json")
REPLAY = Path("raits/research/stocks_pit_sector_overreaction_replay.py")
SIMULATOR = Path("raits/research/stocks_pit_1520_continuation_replay.py")
FEATURES = Path("raits/data/cache/stocks_pit_1520_continuation_2018_2022/causal_features_pre1520.parquet")
END = pd.Timestamp("2021-12-31")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    manifest = json.loads(Path(f"{PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    selection = json.loads(Path(f"{PREFIX}_SELECTION.json").read_text(encoding="ascii"))
    dev = pd.read_csv(f"{PREFIX}_DEVELOPMENT.csv")
    daily = pd.read_csv(f"{PREFIX}_DAILY.csv", parse_dates=["date"])
    trades = pd.read_csv(f"{PREFIX}_TRADES.csv", parse_dates=["date", "next_date", "exit_date"])
    qa = pd.read_csv(f"{PREFIX}_QA.csv")
    yearly = pd.read_csv(f"{PREFIX}_YEARLY.csv")
    base = daily[daily["cost_bps"].eq(4.0)].copy()

    yearly[yearly["cost_bps"].eq(4.0)].to_csv(f"{PREFIX}_AUDIT_YEARLY.csv", index=False)
    dev[[
        "variant", "tickers", "effectiveTickerCount", "top1PositiveShare", "top3PositiveShare",
        "top5PositiveShare", "top10PositiveShare",
    ]].to_csv(f"{PREFIX}_AUDIT_CONCENTRATION.csv", index=False)
    execution = trades.groupby("variant", as_index=False).agg(
        activeDays=("date", "nunique"),
        tradeLegs=("ticker", "size"),
        fallbackExitLegs=("exit_fallback", "sum"),
        unreplayableExitLegs=("unreplayable_exit", "sum"),
        minSectorCount=("sector_count", "min"),
    )
    execution["maxDailyGross"] = execution["variant"].map(
        trades.groupby(["variant", "date"])["target_weight"].sum().groupby("variant").max()
    )
    execution["maxAdvFraction"] = execution["variant"].map(
        base.groupby("variant")["max_order_adv_fraction"].max()
    )
    execution.to_csv(f"{PREFIX}_AUDIT_EXECUTION.csv", index=False)

    sic_side = trades.groupby(["variant", "date", "direction", "sic_description"]).size()
    names = trades.groupby(["variant", "date"]).size()
    gross = trades.groupby(["variant", "date"])["target_weight"].sum()
    side_counts = trades.groupby(["variant", "date", "direction"]).size().unstack(fill_value=0)
    direction_violations = int(
        ((trades["direction"].gt(0) & trades["sector_residual"].ge(0))
         | (trades["direction"].lt(0) & trades["sector_residual"].le(0))).sum()
    )
    summary = {
        "replayScriptHash": sha256(REPLAY),
        "preregisteredScriptHash": prereg["script_hash"],
        "manifestScriptHash": manifest["scriptHash"],
        "scriptHashMatch": sha256(REPLAY) == prereg["script_hash"] == manifest["scriptHash"],
        "preregHash": sha256(PREREG),
        "manifestPreregHash": manifest["preregistrationHash"],
        "preregHashMatch": sha256(PREREG) == manifest["preregistrationHash"],
        "featureHash": sha256(FEATURES),
        "manifestFeatureHash": manifest["inputs"][str(FEATURES).replace("\\", "/")],
        "featureHashMatch": sha256(FEATURES) == manifest["inputs"][str(FEATURES).replace("\\", "/")],
        "simulatorHash": sha256(SIMULATOR),
        "manifestSimulatorHash": manifest["inputs"][str(SIMULATOR).replace("\\", "/")],
        "simulatorHashMatch": sha256(SIMULATOR) == manifest["inputs"][str(SIMULATOR).replace("\\", "/")],
        "developmentRows": len(dev),
        "developmentPasses": int(dev["developmentPass"].sum()),
        "dailyMaxDate": str(daily["date"].max().date()),
        "tradeMaxDate": str(trades["date"].max().date()),
        "post2021PerformanceRows": int(daily["date"].gt(END).sum() + trades["date"].gt(END).sum()),
        "validationOpened": bool(selection["validationOpened"]),
        "sectorCountViolations": int(trades["sector_count"].lt(10).sum()),
        "directionResidualViolations": direction_violations,
        "sicSideViolations": int(sic_side.gt(1).sum()),
        "nameCountViolations": int(names.gt(6).sum()),
        "grossCapViolations": int(gross.gt(0.6 + 1e-12).sum()),
        "matchedSideViolations": int(side_counts[1].ne(side_counts[-1]).sum()),
        "advCapViolations": int(base["max_order_adv_fraction"].gt(0.01 + 1e-12).sum()),
        "unreplayableExitLegs": int(trades["unreplayable_exit"].sum()),
        "maxExitDelayDays": int((trades["exit_date"] - trades["next_date"]).dt.days.max()),
        "maxReconciliationError": float(qa[["dailyMinusEnding", "dailyMinusContrib"]].abs().to_numpy().max()),
        "selection": selection,
        "oldManual62Used": False,
        "post2022Consumed": False,
        "pass": False,
    }
    summary["pass"] = bool(
        summary["scriptHashMatch"]
        and summary["preregHashMatch"]
        and summary["featureHashMatch"]
        and summary["simulatorHashMatch"]
        and summary["developmentRows"] == 5
        and summary["developmentPasses"] == 0
        and summary["post2021PerformanceRows"] == 0
        and not summary["validationOpened"]
        and summary["sectorCountViolations"] == 0
        and summary["directionResidualViolations"] == 0
        and summary["sicSideViolations"] == 0
        and summary["nameCountViolations"] == 0
        and summary["grossCapViolations"] == 0
        and summary["matchedSideViolations"] == 0
        and summary["advCapViolations"] == 0
        and summary["maxExitDelayDays"] <= 5
        and summary["maxReconciliationError"] < 1e-8
    )
    Path(f"{PREFIX}_AUDIT_MANIFEST.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="ascii")
    print(json.dumps(summary, indent=2))
    if not summary["pass"]:
        raise SystemExit("Audit failed")


if __name__ == "__main__":
    main()
