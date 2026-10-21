from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_1000_flow_replay as core


PREREG = Path("STOCKS_PIT_1000_TAPE_PREREG_2026-10-03.json")
TAPE = Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022/causal_tape_features_pre1000.parquet")
TAPE_MANIFEST = TAPE.with_name("causal_tape_features_pre1000_manifest.json")
PREFIX = "STOCKS_PIT_1000_TAPE_2026-10-03"
VARIANTS = [
    "yday_large_lit_sponsorship",
    "yday_broad_venue_confirmation",
    "yday_opening_print_absorption",
    "gapup_large_lit_sponsorship",
    "gapup_sweep_confirmation",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_panel() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    panel, sessions = core.load_panel()
    tape = pd.read_parquet(TAPE)
    tape["date"] = pd.to_datetime(tape["date"]).dt.normalize()
    keep = ["date", "ticker"] + [
        column for column in tape.columns
        if column not in {"date", "ticker"} and column not in panel.columns
    ]
    panel = panel.merge(tape[keep], on=["date", "ticker"], how="inner", validate="one_to_one")
    if len(panel) != 28_225:
        raise RuntimeError("Tape feature coverage mismatch")
    return panel.sort_values(["date", "ticker"]).reset_index(drop=True), sessions


def candidates(panel: pd.DataFrame, variant: str) -> pd.DataFrame:
    x = panel[
        panel["signal_complete"] & panel["entry_complete"]
        & panel["signal_trades"].ge(100) & panel["signal_dollar"].ge(1_000_000.0)
        & panel["reclaim_1000"].gt(0)
    ].copy()
    if variant.startswith("yday_"):
        x = x[x["yday_precandidate"]].copy()
        score = -x["prev_dayret"]
        if variant == "yday_large_lit_sponsorship":
            x = x[x["large_lit_flow_imbalance"].ge(0.10)
                  & x["large_trade_dollar_share_fixed100k"].ge(0.05)].copy()
            score = -x["prev_dayret"] * (1.0 + x["large_lit_flow_imbalance"])
        elif variant == "yday_broad_venue_confirmation":
            x = x[x["lit_flow_imbalance"].gt(0) & x["unique_exchanges"].ge(5)
                  & x["exchange_dollar_hhi"].le(0.35)].copy()
            score = -x["prev_dayret"] * (2.0 - x["exchange_dollar_hhi"] + 0.05 * x["unique_exchanges"].clip(upper=10))
        elif variant == "yday_opening_print_absorption":
            x = x[x["official_open_dollar_share"].ge(0.01)
                  & x["official_open_discount_to_signal_vwap"].le(-0.002)
                  & x["large_lit_flow_imbalance"].gt(0)].copy()
            absorption = (-x["official_open_discount_to_signal_vwap"] * 10.0).clip(upper=0.5)
            score = -x["prev_dayret"] * (1.0 + absorption + x["large_lit_flow_imbalance"])
        else:
            raise ValueError(variant)
    elif variant.startswith("gapup_"):
        x = x[x["gapup_precandidate"]].copy()
        score = x["gap"] * (1.0 + x["reclaim_1000"].clip(lower=0, upper=0.10) * 10.0)
        if variant == "gapup_large_lit_sponsorship":
            x = x[x["large_lit_flow_imbalance"].ge(0.10)
                  & x["large_trade_dollar_share_fixed100k"].ge(0.05)].copy()
            score = score * (1.0 + x["large_lit_flow_imbalance"])
        elif variant == "gapup_sweep_confirmation":
            x = x[x["lit_flow_imbalance"].gt(0) & x["sweep_dollar_share"].ge(0.01)
                  & x["exchange_dollar_hhi"].le(0.45)].copy()
            score = score * (1.0 + 5.0 * x["sweep_dollar_share"].clip(upper=0.20) + x["lit_flow_imbalance"])
        else:
            raise ValueError(variant)
    else:
        raise ValueError(variant)
    x["event_score"] = score
    return x


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or prereg["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration mismatch")
    core.candidates = candidates
    panel, sessions = load_panel()
    dev = core.run_scope(panel, sessions, core.START, core.DEV_END, "development", VARIANTS)
    development = dev["summary"].copy()
    development["developmentPass"] = (
        development["activeDays"].ge(100) & development["tradeLegs"].ge(300)
        & development["cagr"].ge(0.05) & development["sharpe"].ge(0.8)
        & development["ddPct"].ge(-0.12) & development["positiveYears"].ge(3)
        & development["grossEdgeBpsPerActiveDay"].ge(10.0)
        & development["stressPnl"].gt(0) & development["top10PositiveShare"].le(0.50)
    )
    development = development.sort_values(
        ["developmentPass", "sharpe", "cagr", "variant"], ascending=[False, False, False, True]
    )
    passing = development[development["developmentPass"]]
    validation = pd.DataFrame()
    outputs = dev
    if passing.empty:
        selection = {"status": "KILL_NO_DEVELOPMENT_PASS", "selectedVariant": None,
                     "validationOpened": False, "productionPassAllowed": False}
    else:
        selected = str(passing.iloc[0]["variant"])
        val = core.run_scope(panel, sessions, core.VAL_START, core.VAL_END, "validation", [selected])
        validation = val["summary"].copy()
        validation["validationPass"] = (
            validation["activeDays"].ge(20) & validation["pnl"].gt(0)
            & validation["sharpe"].ge(0.5) & validation["ddPct"].ge(-0.10)
            & validation["stressPnl"].gt(0) & validation["top10PositiveShare"].le(0.60)
        )
        passed = bool(validation.iloc[0]["validationPass"])
        selection = {"status": "CONTINUE_AUDIT" if passed else "KILL_VALIDATION_FAIL",
                     "selectedVariant": selected, "validationOpened": True,
                     "validationPass": passed, "productionPassAllowed": False}
        outputs = {key: pd.concat([dev[key], val[key]], ignore_index=True) if key != "summary" else dev[key]
                   for key in ("summary", "trades", "daily", "contrib")}

    daily, contrib = outputs["daily"], outputs["contrib"]
    yearly = daily.assign(year=daily["date"].dt.year).groupby(
        ["variant", "scope", "cost_bps", "year"], as_index=False
    ).agg(pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"),
          tradingCost=("trading_cost", "sum"), activeDays=("trade_legs", lambda values: int(values.gt(0).sum())),
          tradeLegs=("trade_legs", "sum"))
    qa = []
    for (variant, scope, cost), group in daily.groupby(["variant", "scope", "cost_bps"]):
        match = contrib[(contrib["variant"] == variant) & (contrib["scope"] == scope)
                        & (contrib["cost_bps"] == cost)]
        ending = float(group.sort_values("date").iloc[-1]["equity"] - core.INITIAL_EQUITY)
        qa.append({"variant": variant, "scope": scope, "cost_bps": cost,
                   "dailyPnl": group["daily_pnl"].sum(), "endingDelta": ending,
                   "contribPnl": match["net_pnl"].sum(),
                   "dailyMinusEnding": group["daily_pnl"].sum() - ending,
                   "dailyMinusContrib": group["daily_pnl"].sum() - match["net_pnl"].sum()})
    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False)
    validation.to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    outputs["trades"].to_csv(f"{PREFIX}_TRADES.csv", index=False)
    daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    pd.DataFrame(qa).to_csv(f"{PREFIX}_QA.csv", index=False)
    dependencies = [core.PLAN, core.PLAN_MANIFEST, core.EXACT, core.FEATURES, core.FEATURE_MANIFEST,
                    TAPE, TAPE_MANIFEST, Path(core.__file__)]
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in dependencies},
        "selection": selection, "development": [str(core.START.date()), str(core.DEV_END.date())],
        "validation": [str(core.VAL_START.date()), str(core.VAL_END.date())] if selection["validationOpened"] else None,
        "oldManual62Used": False, "post2022Consumed": False, "productionPassAllowed": False,
        "causality": "trade tape uses SIP arrivals strictly before 10:00; exact 10:05 entry; existing audited portfolio engine",
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(development.to_string(index=False))
    print(validation.to_string(index=False))
    print(json.dumps(selection, indent=2))
    print(pd.DataFrame(qa).to_string(index=False))


if __name__ == "__main__":
    main()
