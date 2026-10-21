from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PREFIX = "STOCKS_PIT_1520_CONTINUATION_2026-10-02"
PREREG = Path("STOCKS_PIT_1520_CONTINUATION_PREREG_2026-10-02.json")
REPLAY = Path("raits/research/stocks_pit_1520_continuation_replay.py")
FEATURES = Path("raits/data/cache/stocks_pit_1520_continuation_2018_2022/causal_features_pre1520.parquet")
FEATURE_MANIFEST = FEATURES.with_name("causal_features_pre1520_manifest.json")
SPY_CACHE = Path("raits/data/cache/stocks_pit_1520_continuation_2018_2022/spy_1520_open_2018_2021.parquet")
SPY_MANIFEST = SPY_CACHE.with_name("spy_1520_open_2018_2021_manifest.json")
START, END = pd.Timestamp("2018-03-29"), pd.Timestamp("2021-12-31")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def benchmark_metrics(name: str, frame: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame]:
    x = frame.sort_values("date").copy()
    returns = x["return"].astype(float)
    equity = (1.0 + returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    years = (x["date"].max() - x["date"].min()).days / 365.25
    yearly = (1.0 + returns).groupby(x["date"].dt.year).prod() - 1.0
    summary = {
        "benchmark": name,
        "observations": len(x),
        "totalReturn": float(equity.iloc[-1] - 1.0),
        "cagr": float(equity.iloc[-1] ** (1.0 / years) - 1.0),
        "sharpe": float(returns.mean() / returns.std() * math.sqrt(252)),
        "ddPct": float(drawdown.min()),
    }
    yearly_frame = yearly.rename("return").reset_index().rename(columns={"date": "year"})
    yearly_frame["benchmark"] = name
    return summary, yearly_frame[["benchmark", "year", "return"]]


def spy_benchmark(sessions: list[pd.Timestamp]) -> pd.DataFrame:
    manifest = json.loads(SPY_MANIFEST.read_text(encoding="ascii"))
    if manifest["outputHash"] != sha256(SPY_CACHE) or not manifest["post2021Consumed"] is False:
        raise RuntimeError("SPY benchmark provenance failure")
    raw = pd.read_parquet(SPY_CACHE)
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()
    prices = raw.drop_duplicates("date", keep="last").set_index("date")["open"]
    rows = []
    for date, next_date in zip(sessions[:-1], sessions[1:]):
        if date in prices.index and next_date in prices.index:
            rows.append({"date": date, "return": float(prices.loc[next_date] / prices.loc[date] - 1.0)})
    return pd.DataFrame(rows)


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    replay_manifest = json.loads(Path(f"{PREFIX}_MANIFEST.json").read_text(encoding="ascii"))
    feature_manifest = json.loads(FEATURE_MANIFEST.read_text(encoding="ascii"))
    selection = json.loads(Path(f"{PREFIX}_SELECTION.json").read_text(encoding="ascii"))
    dev = pd.read_csv(f"{PREFIX}_DEVELOPMENT.csv")
    daily = pd.read_csv(f"{PREFIX}_DAILY.csv", parse_dates=["date"])
    trades = pd.read_csv(f"{PREFIX}_TRADES.csv", parse_dates=["date", "next_date", "exit_date"])
    contrib = pd.read_csv(f"{PREFIX}_TICKER_CONTRIB.csv", parse_dates=["date"])
    qa = pd.read_csv(f"{PREFIX}_QA.csv")
    features = pd.read_parquet(FEATURES, columns=["date", "ticker", "next_date"])
    features["date"] = pd.to_datetime(features["date"]).dt.normalize()

    base = daily[daily["cost_bps"].eq(4.0)].copy()
    execution = trades.groupby("variant", as_index=False).agg(
        activeDays=("date", "nunique"),
        tradeLegs=("ticker", "size"),
        maxAbsWeight=("target_weight", "max"),
        maxDailyGross=("target_weight", lambda values: np.nan),
        fallbackExitLegs=("exit_fallback", "sum"),
        unreplayableExitLegs=("unreplayable_exit", "sum"),
    )
    daily_gross = trades.groupby(["variant", "date"])["target_weight"].sum().groupby("variant").max()
    execution["maxDailyGross"] = execution["variant"].map(daily_gross)
    execution["maxAdvFraction"] = execution["variant"].map(base.groupby("variant")["max_order_adv_fraction"].max())
    execution.to_csv(f"{PREFIX}_AUDIT_EXECUTION.csv", index=False)

    concentration = dev[[
        "variant", "tickers", "effectiveTickerCount", "top1PositiveShare", "top3PositiveShare",
        "top5PositiveShare", "top10PositiveShare",
    ]].copy()
    concentration.to_csv(f"{PREFIX}_AUDIT_CONCENTRATION.csv", index=False)

    yearly = pd.read_csv(f"{PREFIX}_YEARLY.csv")
    yearly[yearly["cost_bps"].eq(4.0)].to_csv(f"{PREFIX}_AUDIT_YEARLY.csv", index=False)

    benchmark_daily = pd.read_csv(f"{PREFIX}_BENCHMARK_DAILY.csv", parse_dates=["date"])
    benchmark_summaries: list[dict[str, object]] = []
    benchmark_yearly: list[pd.DataFrame] = []
    for name, group in benchmark_daily.groupby("benchmark"):
        summary, years = benchmark_metrics(name, group)
        benchmark_summaries.append(summary)
        benchmark_yearly.append(years)
    sessions = sorted(features.loc[features["date"].between(START, END), "date"].drop_duplicates())
    spy = spy_benchmark(sessions)
    spy_summary, spy_years = benchmark_metrics("SPY", spy)
    benchmark_summaries.append(spy_summary)
    benchmark_yearly.append(spy_years)
    pd.DataFrame(benchmark_summaries).to_csv(f"{PREFIX}_AUDIT_BENCHMARK.csv", index=False)
    pd.concat(benchmark_yearly, ignore_index=True).to_csv(f"{PREFIX}_AUDIT_BENCHMARK_YEARLY.csv", index=False)

    sic_side = trades.groupby(["variant", "date", "direction", "sic_description"]).size()
    names = trades.groupby(["variant", "date"]).size()
    gross = trades.groupby(["variant", "date"])["target_weight"].sum()
    ls = trades[~trades["variant"].eq("pullback_resume_long_next1520")]
    side_counts = ls.groupby(["variant", "date", "direction"]).size().unstack(fill_value=0)
    sign_violations = int(
        ((trades["direction"].gt(0) & trades["intraday_return"].le(0))
         | (trades["direction"].lt(0) & trades["intraday_return"].ge(0))).sum()
    )
    summary = {
        "replayScriptHash": sha256(REPLAY),
        "preregisteredScriptHash": prereg["script_hash"],
        "manifestScriptHash": replay_manifest["scriptHash"],
        "scriptHashMatch": sha256(REPLAY) == prereg["script_hash"] == replay_manifest["scriptHash"],
        "preregHash": sha256(PREREG),
        "manifestPreregHash": replay_manifest["preregistrationHash"],
        "preregHashMatch": sha256(PREREG) == replay_manifest["preregistrationHash"],
        "featureHash": sha256(FEATURES),
        "featureManifestHash": feature_manifest["output_hash"],
        "featureHashMatch": sha256(FEATURES) == feature_manifest["output_hash"],
        "developmentRows": len(dev),
        "developmentPasses": int(dev["developmentPass"].sum()),
        "dailyMaxDate": str(daily["date"].max().date()),
        "tradeMaxDate": str(trades["date"].max().date()),
        "post2021PerformanceRows": int(daily["date"].gt(END).sum() + trades["date"].gt(END).sum()),
        "validationOpened": bool(selection["validationOpened"]),
        "sicSideViolations": int(sic_side.gt(1).sum()),
        "nameCountViolations": int(names.gt(6).sum()),
        "grossCapViolations": int(gross.gt(0.6 + 1e-12).sum()),
        "matchedSideViolations": int(side_counts.get(1, 0).ne(side_counts.get(-1, 0)).sum()),
        "directionSignViolations": sign_violations,
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
        and summary["developmentRows"] == 5
        and summary["developmentPasses"] == 0
        and summary["post2021PerformanceRows"] == 0
        and not summary["validationOpened"]
        and summary["sicSideViolations"] == 0
        and summary["nameCountViolations"] == 0
        and summary["grossCapViolations"] == 0
        and summary["matchedSideViolations"] == 0
        and summary["directionSignViolations"] == 0
        and summary["advCapViolations"] == 0
        and summary["maxExitDelayDays"] <= 5
        and summary["maxReconciliationError"] < 1e-8
    )
    Path(f"{PREFIX}_AUDIT_MANIFEST.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="ascii")
    print(json.dumps(summary, indent=2))
    print(pd.DataFrame(benchmark_summaries).to_string(index=False))
    if not summary["pass"]:
        raise SystemExit("Audit failed")


if __name__ == "__main__":
    main()
