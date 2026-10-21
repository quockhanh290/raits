from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_sec_8k202_event_drift_replay as event_engine


PREREG = Path("STOCKS_POLYGON_FINANCIAL_CHANGE_DRIFT_PREREG_2026-09-24.json")
FINANCIAL_DIR = Path("raits/data/cache/external_events/polygon_2018_2024/financials")
INTRA = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
PREFIX = "STOCKS_POLYGON_FINANCIAL_CHANGE_DRIFT_2026-09-24"
START, DEV_END = pd.Timestamp("2018-04-27"), pd.Timestamp("2022-12-30")
VAL_START, END = pd.Timestamp("2023-01-03"), pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def field_value(raw: str, statement: str, field: str) -> float:
    try:
        return float(json.loads(raw).get(statement, {}).get(field, {}).get("value", np.nan))
    except (TypeError, ValueError, json.JSONDecodeError):
        return np.nan


def load_financial_features() -> pd.DataFrame:
    columns = ["cik", "company_name", "end_date", "filing_date", "fiscal_period", "fiscal_year", "source_filing_url", "financials_json"]
    frames = [pd.read_parquet(path, columns=columns) for path in sorted(FINANCIAL_DIR.glob("financials_*.parquet"))]
    x = pd.concat(frames, ignore_index=True)
    x["cik"] = event_engine.normalize_cik(x["cik"])
    x["filing_date"] = pd.to_datetime(x["filing_date"], errors="coerce").dt.normalize()
    x["end_date"] = pd.to_datetime(x["end_date"], errors="coerce").dt.normalize()
    x["fiscal_year"] = pd.to_numeric(x["fiscal_year"], errors="coerce")
    x["fiscal_period"] = x["fiscal_period"].astype(str).str.upper()
    x = x[x["fiscal_period"].isin(["Q1", "Q2", "Q3", "Q4"]) & x["fiscal_year"].notna() & x["filing_date"].notna()].copy()
    x = x.sort_values(["cik", "fiscal_year", "fiscal_period", "end_date", "filing_date", "source_filing_url"])
    x = x.drop_duplicates(["cik", "fiscal_year", "fiscal_period", "end_date"], keep="first")
    x["revenue"] = [field_value(raw, "income_statement", "revenues") for raw in x["financials_json"]]
    x["operating_income"] = [field_value(raw, "income_statement", "operating_income_loss") for raw in x["financials_json"]]
    x = x.replace([np.inf, -np.inf], np.nan)
    x["operating_margin"] = x["operating_income"] / x["revenue"]
    prior = x[["cik", "fiscal_period", "fiscal_year", "revenue", "operating_margin"]].copy()
    prior["fiscal_year"] += 1
    prior = prior.rename(columns={"revenue": "prior_revenue", "operating_margin": "prior_operating_margin"})
    x = x.merge(prior, on=["cik", "fiscal_period", "fiscal_year"], how="left", validate="many_to_one")
    x["revenue_yoy"] = x["revenue"] / x["prior_revenue"] - 1.0
    x["margin_change_yoy"] = x["operating_margin"] - x["prior_operating_margin"]
    valid = x["revenue"].gt(0) & x["prior_revenue"].gt(0) & x["revenue_yoy"].abs().le(3.0)
    valid &= x["operating_margin"].between(-2.0, 2.0) & x["prior_operating_margin"].between(-2.0, 2.0)
    valid &= x["margin_change_yoy"].abs().le(1.0)
    return x.loc[valid, ["cik", "company_name", "end_date", "filing_date", "fiscal_period", "fiscal_year", "source_filing_url", "revenue_yoy", "operating_margin", "margin_change_yoy"]].copy()


def map_events(features: pd.DataFrame, intra: pd.DataFrame) -> pd.DataFrame:
    sessions = pd.DatetimeIndex(sorted(intra["date"].drop_duplicates()))
    indices = np.searchsorted(sessions.values, features["filing_date"].values, side="right")
    valid = indices < len(sessions)
    events = features.loc[valid].copy()
    events["date"] = sessions[indices[valid]]
    events = events[events["date"].between(START, END)].copy()
    members = event_engine.load_top500_representatives("development")
    dates = pd.DataFrame({"date": sessions})
    snapshots = members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    events = events.merge(assigned, on="date", how="left", validate="many_to_one")
    events = events.merge(members, on=["snapshot_date", "cik"], how="inner", validate="many_to_one")
    eligible = event_engine.load_eligible("development", START, END)
    events = events.merge(eligible, on=["date", "ticker"], how="inner", validate="many_to_one")
    events = events[events["adv20"].ge(10_000_000)].copy()
    events = events.merge(intra[["date", "ticker", "entry935", "exit1555"]], on=["date", "ticker"], how="inner", validate="many_to_one")
    events = events.dropna(subset=["entry935", "exit1555"]).sort_values(["date", "cik", "filing_date", "source_filing_url"])
    events = events.drop_duplicates(["date", "cik"], keep="first")
    events["accessionNumber"] = events["source_filing_url"].astype(str).str.rsplit("/", n=1).str[-1]
    return events


def variant_signals(events: pd.DataFrame, name: str) -> pd.DataFrame:
    x = events.copy()
    if name.startswith("revenue_yoy20"):
        x["direction"] = np.select([x["revenue_yoy"].ge(0.20), x["revenue_yoy"].le(-0.20)], [1, -1], default=0)
    elif name.startswith("margin_yoy5"):
        x["direction"] = np.select([x["margin_change_yoy"].ge(0.05), x["margin_change_yoy"].le(-0.05)], [1, -1], default=0)
    else:
        positive = x["revenue_yoy"].ge(0.10) & x["margin_change_yoy"].ge(0.02)
        negative = x["revenue_yoy"].le(-0.10) & x["margin_change_yoy"].le(-0.02)
        x["direction"] = np.select([positive, negative], [1, -1], default=0)
    return x[x["direction"].ne(0)].copy()


def metrics(daily: pd.DataFrame, begin: pd.Timestamp, finish: pd.Timestamp) -> dict[str, object]:
    x = daily[daily["date"].between(begin, finish)].copy()
    prior = x["equity"] - x["daily_pnl"]
    returns = x["daily_pnl"] / prior
    start_equity = float(prior.iloc[0])
    curve = pd.concat([pd.Series([start_equity]), x["equity"].reset_index(drop=True)], ignore_index=True)
    peak = curve.cummax()
    years = max((x["date"].max() - x["date"].min()).days / 365.25, 1e-9)
    yearly = (1.0 + returns).groupby(x["date"].dt.year).prod() - 1.0
    return {"days": len(x), "pnl": x["daily_pnl"].sum(), "cagr": (x["equity"].iloc[-1] / start_equity) ** (1.0 / years) - 1.0,
        "sharpe": returns.mean() / returns.std() * math.sqrt(252) if returns.std() > 0 else np.nan,
        "ddDollar": (curve - peak).min(), "ddPct": (curve / peak - 1.0).min(), "positiveYears": int(yearly.gt(0).sum())}


def concentration(contrib: pd.DataFrame, begin: pd.Timestamp, finish: pd.Timestamp) -> dict[str, object]:
    x = contrib.copy()
    x["date"] = pd.to_datetime(x["timestamp"]).dt.tz_localize(None).dt.normalize()
    x = x[x["date"].between(begin, finish) & ~x["ticker"].astype(str).str.startswith("_")]
    by = x.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(x["pnl"].sum())
    positive = by[by > 0]
    basis = positive if positive.sum() > 0 else by.abs()
    weights = basis / basis.sum() if basis.sum() else basis
    row: dict[str, object] = {"tickers": len(by), "effectiveTickerCount": 1.0 / weights.pow(2).sum() if len(weights) else 0.0, "topTicker": by.index[0] if len(by) else ""}
    denominator = total if total > 0 else float(by.abs().sum())
    for n in (1, 3, 5, 10):
        value = float(by.head(n).sum())
        row[f"top{n}Pnl"], row[f"top{n}Share"] = value, value / denominator if denominator else np.nan
    return row


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_performance") or prereg["implementation_freeze"]["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash is not frozen")
    intra = pd.read_pickle(INTRA)[["date", "ticker", "entry935", "exit1555"]].copy()
    intra["date"] = pd.to_datetime(intra["date"]).dt.normalize()
    intra["ticker"] = intra["ticker"].astype(str).str.upper()
    intra = intra[intra["date"].between(START, END)].copy()
    sessions = sorted(intra["date"].drop_duplicates())
    dev_intra = intra[intra["date"].between(START, DEV_END)].copy()
    dev_sessions = sorted(dev_intra["date"].drop_duplicates())
    dev_p935, dev_p1555 = event_engine.price_maps(dev_intra)
    p935, p1555 = event_engine.price_maps(intra)
    features = load_financial_features()
    mapped = map_events(features, intra)

    dev_rows, daily_frames, event_frames, trade_frames, contrib_frames, signal_frames = [], [], [], [], [], []
    dev_cache = {}
    for spec in prereg["variants"]:
        name, hold = spec["name"], int(spec["hold_sessions"])
        signals = variant_signals(mapped, name)
        dev_signals = signals[signals["date"].between(START, DEV_END)].copy()
        signal_frames.append(dev_signals.assign(variant=name, run_scope="development_search"))
        for cost in (4.0, 8.0):
            daily, events, trades, contrib = event_engine.simulate(name, hold, cost, dev_sessions, dev_signals, dev_p935, dev_p1555)
            trades["reason"] = trades["reason"].replace("confirmed_8k202", "polygon_financial_change")
            daily_frames.append(daily.assign(run_scope="development_search")); event_frames.append(events.assign(run_scope="development_search")); trade_frames.append(trades.assign(run_scope="development_search")); contrib_frames.append(contrib.assign(run_scope="development_search"))
            dev_cache[(name, int(cost))] = (daily, trades, contrib)
        base_daily, base_trades, base_contrib = dev_cache[(name, 4)]
        stress_daily, stress_trades, _ = dev_cache[(name, 8)]
        base_result = metrics(base_daily, START, DEV_END)
        stress_result = metrics(stress_daily, START, DEV_END)
        entries = int((base_trades["event"].eq("entry") & base_trades["date"].between(START, DEV_END)).sum())
        conc = concentration(base_contrib, START, DEV_END)
        passed = bool(entries >= 100 and base_result["cagr"] >= 0.02 and base_result["sharpe"] >= 0.50 and base_result["ddPct"] >= -0.10 and base_result["positiveYears"] >= 3 and stress_result["pnl"] > 0)
        dev_rows.append({"variant": name, "developmentPass": passed, "entries": entries, **base_result,
            "stressPnl": stress_result["pnl"], "stressCagr": stress_result["cagr"], **conc})
    development = pd.DataFrame(dev_rows).sort_values(["developmentPass", "sharpe", "cagr", "ddPct", "variant"], ascending=[False, False, False, False, True])
    passing = development[development["developmentPass"].eq(True)]
    validation_rows = []
    if passing.empty:
        selection = {"selectedVariant": None, "status": "KILL_NO_DEVELOPMENT_PASS", "validationOpened": False, "productionPassAllowed": False}
    else:
        selected = str(passing.iloc[0]["variant"])
        selected_spec = next(spec for spec in prereg["variants"] if spec["name"] == selected)
        selected_signals = variant_signals(mapped, selected)
        signal_frames.append(selected_signals.assign(variant=selected, run_scope="selected_full"))
        selected_full = {}
        for cost in (4.0, 8.0):
            daily, events, trades, contrib = event_engine.simulate(selected, int(selected_spec["hold_sessions"]), cost, sessions, selected_signals, p935, p1555)
            trades["reason"] = trades["reason"].replace("confirmed_8k202", "polygon_financial_change")
            daily_frames.append(daily.assign(run_scope="selected_full")); event_frames.append(events.assign(run_scope="selected_full")); trade_frames.append(trades.assign(run_scope="selected_full")); contrib_frames.append(contrib.assign(run_scope="selected_full"))
            selected_full[int(cost)] = (daily, trades, contrib)
        base_daily, base_trades, base_contrib = selected_full[4]
        stress_daily, stress_trades, _ = selected_full[8]
        base_result = metrics(base_daily, VAL_START, END)
        stress_result = metrics(stress_daily, VAL_START, END)
        years = base_daily[base_daily["date"].between(VAL_START, END)].assign(year=lambda z: z["date"].dt.year).groupby("year")["daily_pnl"].sum()
        conc = concentration(base_contrib, VAL_START, END)
        entries = int((base_trades["event"].eq("entry") & base_trades["date"].between(VAL_START, END)).sum())
        validation_pass = bool(base_result["pnl"] > 0 and len(years) == 2 and years.ge(0).all() and base_result["sharpe"] >= 0.30 and stress_result["pnl"] > 0 and base_result["ddPct"] >= -0.12)
        validation_rows.append({"variant": selected, "validationPass": validation_pass, "entries": entries, **base_result,
            "stressPnl": stress_result["pnl"], "stressCagr": stress_result["cagr"], **conc})
        selection = {"selectedVariant": selected, "developmentRank": 1, "validationPass": validation_pass,
            "status": "CONTINUE_DIAGNOSTIC" if validation_pass else "KILL_VALIDATION", "productionPassAllowed": False}

    all_daily = pd.concat(daily_frames, ignore_index=True)
    all_trades = pd.concat(trade_frames, ignore_index=True)
    all_contrib = pd.concat(contrib_frames, ignore_index=True)
    all_events = pd.concat(event_frames, ignore_index=True)
    all_signals = pd.concat(signal_frames, ignore_index=True)
    yearly_rows = []
    for (scenario, run_scope, year), group in all_daily.assign(year=all_daily["date"].dt.year).groupby(["scenario", "run_scope", "year"], sort=True):
        begin_equity = float(group.iloc[0]["equity"] - group.iloc[0]["daily_pnl"])
        curve = pd.concat([pd.Series([begin_equity]), group["equity"].reset_index(drop=True)], ignore_index=True)
        peak = curve.cummax()
        prior = group["equity"] - group["daily_pnl"]
        returns = group["daily_pnl"] / prior
        yearly_rows.append({"scenario": scenario, "run_scope": run_scope, "year": int(year), "pnl": group["daily_pnl"].sum(),
            "return": group.iloc[-1]["equity"] / begin_equity - 1.0, "sharpe": returns.mean() / returns.std() * math.sqrt(252) if returns.std() > 0 else np.nan,
            "ddDollar": (curve - peak).min(), "ddPct": (curve / peak - 1.0).min()})
    yearly = pd.DataFrame(yearly_rows)
    qa_rows = []
    for (scenario, run_scope), group in all_daily.groupby(["scenario", "run_scope"], sort=True):
        contrib = all_contrib[(all_contrib["scenario"].eq(scenario)) & (all_contrib["run_scope"].eq(run_scope))]
        event = all_events[(all_events["scenario"].eq(scenario)) & (all_events["run_scope"].eq(run_scope))]
        ending_delta = float(group.iloc[-1]["equity"] - START_CAPITAL)
        qa_rows.append({"scenario": scenario, "run_scope": run_scope, "dailyPnl": group["daily_pnl"].sum(), "endingDelta": ending_delta,
            "contribPnl": contrib["pnl"].sum(), "eventPnl": event["event_pnl"].sum(),
            "dailyMinusEnding": group["daily_pnl"].sum() - ending_delta, "dailyMinusContrib": group["daily_pnl"].sum() - contrib["pnl"].sum(),
            "dailyMinusEvents": group["daily_pnl"].sum() - event["event_pnl"].sum(), "missingMarks": event["missing_marks"].max()})
    qa = pd.DataFrame(qa_rows)
    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False)
    pd.DataFrame(validation_rows).to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    mapped.to_csv(f"{PREFIX}_MAPPED_FILINGS.csv", index=False)
    all_signals.to_csv(f"{PREFIX}_SIGNALS.csv", index=False)
    all_daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    qa.to_csv(f"{PREFIX}_QA.csv", index=False)
    all_events.to_csv(f"{PREFIX}_EVENT_LEDGER.csv", index=False)
    all_trades.to_csv(f"{PREFIX}_TRADE_LEDGER.csv", index=False)
    all_contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)

    financial_files = sorted(FINANCIAL_DIR.glob("financials_*.parquet"))
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "financialInputCount": len(financial_files), "financialInputHashes": {path.name: sha256(path) for path in financial_files},
        "otherInputs": {str(INTRA).replace("\\", "/"): sha256(INTRA), str(event_engine.CAP_PATHS[0]).replace("\\", "/"): sha256(event_engine.CAP_PATHS[0]), str(event_engine.FILTER_PATHS[0]).replace("\\", "/"): sha256(event_engine.FILTER_PATHS[0])},
        "rawFinancialRows": 125679, "featureRowsAfterYoYAndGuards": len(features), "mappedEligibleFilings": len(mapped),
        "outputs": [f"{PREFIX}_{suffix}" for suffix in ("DEVELOPMENT.csv", "VALIDATION.csv", "SELECTION.json", "MAPPED_FILINGS.csv", "SIGNALS.csv", "DAILY.csv", "YEARLY.csv", "QA.csv", "EVENT_LEDGER.csv", "TRADE_LEDGER.csv", "TICKER_CONTRIB.csv", "MANIFEST.json")],
        "selection": selection, "oos2025_2026Consumed": False, "oldManual62Used": False, "productionPassAllowed": False,
        "ruleSelectionEffect": "One of six pre-registered variants selected on 2018-2022 only; validation cannot replace it.",
        "tradeSelectionEffect": "Full PIT CIK/ticker mapping, eligibility, ADV, overlap, exact-price availability, and hard gross cap are replayed."}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(development.to_string(index=False), flush=True)
    print(pd.DataFrame(validation_rows).to_string(index=False), flush=True)
    print(json.dumps(selection, indent=2), flush=True)


if __name__ == "__main__":
    main()
