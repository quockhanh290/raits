from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "STOCKS_PIT_1000_TAPE_2026-10-03"
SCRIPT = Path("raits/research/stocks_pit_1000_tape_replay.py")
PREREG = Path("STOCKS_PIT_1000_TAPE_PREREG_2026-10-03.json")
FEATURES = Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022/causal_tape_features_pre1000.parquet")
FEATURE_MANIFEST = FEATURES.with_name("causal_tape_features_pre1000_manifest.json")
VARIANTS = {
    "yday_large_lit_sponsorship", "yday_broad_venue_confirmation",
    "yday_opening_print_absorption", "gapup_large_lit_sponsorship", "gapup_sweep_confirmation",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    manifest = json.loads(Path(f"{PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    feature_manifest = json.loads(FEATURE_MANIFEST.read_text(encoding="ascii"))
    selection = json.loads(Path(f"{PREFIX}_SELECTION.json").read_text(encoding="ascii"))
    development = pd.read_csv(f"{PREFIX}_DEVELOPMENT.csv")
    validation = pd.read_csv(f"{PREFIX}_VALIDATION.csv")
    trades = pd.read_csv(f"{PREFIX}_TRADES.csv", parse_dates=["date"])
    daily = pd.read_csv(f"{PREFIX}_DAILY.csv", parse_dates=["date"])
    contrib = pd.read_csv(f"{PREFIX}_TICKER_CONTRIB.csv")
    qa = pd.read_csv(f"{PREFIX}_QA.csv")
    features = pd.read_parquet(FEATURES, columns=["date", "ticker", "signal_trades",
                                "max_signal_sip_timestamp", "signal_end_ns"])

    check(sha256(SCRIPT) == prereg["script_hash"] == manifest["scriptHash"], "script hash mismatch")
    check(sha256(PREREG) == manifest["preregistrationHash"], "prereg hash mismatch")
    for path, expected in manifest["inputs"].items():
        check(sha256(Path(path)) == expected, f"input hash mismatch: {path}")
    check(sha256(FEATURES) == feature_manifest["outputHash"], "feature hash mismatch")
    check(len(features) == 28_225 and not features.duplicated(["date", "ticker"]).any(), "feature coverage")
    check(features["signal_trades"].gt(0).all(), "empty signal feature")
    check(features["max_signal_sip_timestamp"].lt(features["signal_end_ns"]).all(), "feature clock violation")

    check(set(development["variant"]) == VARIANTS and len(development) == 5, "frozen family mismatch")
    passers = development.loc[development["developmentPass"].astype(bool), "variant"].tolist()
    check(passers == ["yday_broad_venue_confirmation"], "unexpected development selection")
    check(selection["selectedVariant"] == passers[0] and selection["validationOpened"], "selection mismatch")
    check(selection["status"] == "KILL_VALIDATION_FAIL", "validation verdict mismatch")
    check(len(validation) == 1 and validation.iloc[0]["variant"] == passers[0], "validation scope mismatch")
    check(not bool(validation.iloc[0]["validationPass"]), "unexpected validation pass")
    validation_trades = trades[trades["scope"].eq("validation")]
    check(validation_trades["variant"].eq(passers[0]).all(), "non-selected rule entered validation")
    check(validation_trades["date"].dt.year.eq(2022).all(), "validation date violation")
    check(trades.loc[trades["scope"].eq("development"), "date"].max() <= pd.Timestamp("2021-12-31"), "development leak")
    check(trades["target_weight"].eq(0.20).all(), "weight violation")
    check(trades.groupby(["variant", "scope", "date"]).size().le(3).all(), "name cap violation")
    check(trades.groupby(["variant", "scope", "date", "sic_description"]).size().le(1).all(), "SIC cap violation")
    check(trades["reclaim_1000"].gt(0).all(), "price confirmation violation")
    check(trades["signal_trades"].ge(100).all() & trades["signal_dollar"].ge(1_000_000).all(), "liquidity filter")
    check(trades.loc[trades["variant"].str.startswith("yday_"), "yday_precandidate"].astype(bool).all(), "YDAY precursor")
    check(trades.loc[trades["variant"].str.startswith("gapup_"), "gapup_precandidate"].astype(bool).all(), "gap precursor")

    subset = trades[trades["variant"].isin(["yday_large_lit_sponsorship", "gapup_large_lit_sponsorship"])]
    check(subset["large_lit_flow_imbalance"].ge(0.10).all(), "large-lit imbalance rule")
    check(subset["large_trade_dollar_share_fixed100k"].ge(0.05).all(), "large trade share rule")
    subset = trades[trades["variant"].eq("yday_broad_venue_confirmation")]
    check(subset["lit_flow_imbalance"].gt(0).all() & subset["unique_exchanges"].ge(5).all()
          & subset["exchange_dollar_hhi"].le(0.35).all(), "broad venue rule")
    subset = trades[trades["variant"].eq("yday_opening_print_absorption")]
    check(subset["official_open_dollar_share"].ge(0.01).all()
          & subset["official_open_discount_to_signal_vwap"].le(-0.002).all()
          & subset["large_lit_flow_imbalance"].gt(0).all(), "opening absorption rule")
    subset = trades[trades["variant"].eq("gapup_sweep_confirmation")]
    check(subset["lit_flow_imbalance"].gt(0).all() & subset["sweep_dollar_share"].ge(0.01).all()
          & subset["exchange_dollar_hhi"].le(0.45).all(), "sweep rule")

    check(daily["gross"].le(0.6000001).all(), "gross cap violation")
    check(daily["max_order_adv_fraction"].le(0.0100001).all(), "ADV cap violation")
    check((daily["dd_dollar"] <= 1e-8).all() and (daily["dd_pct"] <= 1e-8).all(), "drawdown sign")
    check(qa["dailyMinusEnding"].abs().max() < 1e-6, "ending reconciliation")
    check(qa["dailyMinusContrib"].abs().max() < 1e-6, "contribution reconciliation")
    for summary in pd.concat([development.assign(scope="development"), validation.assign(scope="validation")]).itertuples(index=False):
        d = daily[(daily["variant"] == summary.variant) & (daily["scope"] == summary.scope) & daily["cost_bps"].eq(4.0)]
        c = contrib[(contrib["variant"] == summary.variant) & (contrib["scope"] == summary.scope) & contrib["cost_bps"].eq(4.0)]
        check(abs(d["daily_pnl"].sum() - summary.pnl) < 1e-6, f"summary pnl: {summary.variant}/{summary.scope}")
        by = c.groupby("ticker")["net_pnl"].sum().sort_values(ascending=False)
        positive = by[by > 0]
        for n, field in [(1, "top1PositiveShare"), (3, "top3PositiveShare"), (5, "top5PositiveShare"), (10, "top10PositiveShare")]:
            expected = positive.head(n).sum() / positive.sum()
            check(abs(expected - getattr(summary, field)) < 1e-10, f"concentration: {summary.variant}/{summary.scope}/{n}")

    result = {"status": "PASS", "checks": 33, "selection": selection,
              "maxDevelopmentDate": str(trades.loc[trades["scope"].eq("development"), "date"].max().date()),
              "maxValidationDate": str(validation_trades["date"].max().date()),
              "post2022Consumed": False, "scriptHash": sha256(SCRIPT)}
    Path(f"{PREFIX}_AUDIT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
