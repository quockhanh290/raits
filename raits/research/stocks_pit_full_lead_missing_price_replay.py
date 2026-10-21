from __future__ import annotations

from pathlib import Path

import json

import numpy as np
import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as base
import stocks_pit_full_lead_crisis_eventtime_audit as crisis
import stocks_pit_full_lead_deployment_policy_audit as deployment


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_MISSING_PRICE_REPLAY_2026-09-17"
RAW_5M = Path("raits/data/cache/polygon_5min_pit_full_2018_2024")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
COVERAGE_OUT = Path(f"{OUT_PREFIX}_COVERAGE.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

# Frozen before this replay. Previous-bar prices are marks only, never executions.
MAX_MARK_AGE_MINUTES = 5
SCENARIOS = [
    {"scenario": "feature_exact_namecap3", "raw_exact": False, "asof_marks": False, "fail_safe": False},
    {"scenario": "raw_exact_namecap3", "raw_exact": True, "asof_marks": False, "fail_safe": False},
    {"scenario": "raw_asof5_namecap3_missingfs", "raw_exact": True, "asof_marks": True, "fail_safe": True},
]


def put(prices: dict[pd.Timestamp, pd.Series], date: pd.Timestamp, ticker: str, value: float) -> None:
    series = prices.setdefault(date, pd.Series(dtype=float))
    series.loc[ticker] = value


def copy_maps(source: dict[pd.Timestamp, pd.Series]) -> dict[pd.Timestamp, pd.Series]:
    return {date: values.copy() for date, values in source.items()}


def concentration_rows(scenario: str, contrib: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    selections = (
        ("total_ex_carry", contrib[~contrib["ticker"].isin(["_FINANCING", "_BORROW"])]),
        ("satellites", contrib[contrib["sleeve"].eq("satellites")]),
    )
    for scope, selected in selections:
        by_ticker = selected.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        denominator = float(selected["pnl"].sum())
        if denominator <= 0.0:
            denominator = float(by_ticker.abs().sum())
        row: dict[str, object] = {
            "scenario": scenario,
            "scope": scope,
            "tickers": int(len(by_ticker)),
            "effectiveTickerCount": base.effective_ticker_count(by_ticker),
            "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        }
        for n in (1, 3, 5, 10):
            top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
            row[f"top{n}Pnl"] = top
            row[f"top{n}Share"] = top / denominator if denominator else float("nan")
        rows.append(row)
    return rows


def raw_price_overlays(requests: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    requests = requests.copy()
    requests["month"] = requests["date"].dt.strftime("%Y-%m")
    for (ticker, month), group in requests.groupby(["ticker", "month"], sort=True):
        path = RAW_5M / ticker / f"{ticker}_5m_{month}.parquet"
        if not path.exists():
            for date in group["date"]:
                rows.append({"date": date, "ticker": ticker, "event": "both", "source": "unresolved_file", "price": np.nan, "ageMinutes": np.nan})
            continue
        bars = pd.read_parquet(path, columns=["open", "close"]).sort_index()
        bars.index = pd.to_datetime(bars.index)
        for date in group["date"]:
            for hhmm, field, event in [("09:35", "open", "0935"), ("15:55", "close", "1555")]:
                timestamp = date + pd.Timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:]))
                if timestamp in bars.index and np.isfinite(float(bars.loc[timestamp, field])):
                    rows.append({"date": date, "ticker": ticker, "event": event, "source": "raw_exact", "price": float(bars.loc[timestamp, field]), "ageMinutes": 0.0})
                    continue
                day = bars[(bars.index.normalize() == date) & (bars.index < timestamp)]
                if day.empty:
                    rows.append({"date": date, "ticker": ticker, "event": event, "source": "unresolved_no_prior_bar", "price": np.nan, "ageMinutes": np.nan})
                    continue
                prior_ts = day.index[-1]
                availability = prior_ts + pd.Timedelta(minutes=5)
                age = (timestamp - availability).total_seconds() / 60.0
                price = float(day.iloc[-1]["close"])
                source = "raw_asof" if 0.0 <= age <= MAX_MARK_AGE_MINUTES and np.isfinite(price) else "unresolved_stale"
                rows.append({"date": date, "ticker": ticker, "event": event, "source": source, "price": price if source == "raw_asof" else np.nan, "ageMinutes": age})
    return pd.DataFrame(rows)


def main() -> None:
    core = base.load_core()
    spy = base.load_spy_prices(list(core["date"]))
    common = set(core["date"]).intersection(spy["date"])
    core = core[core["date"].isin(common)].copy()
    spy = spy[spy["date"].isin(common)].copy()
    dates = sorted(common)
    pair_events = base.load_pair_events()
    feature935, feature1555 = base.load_pair_prices(common)
    schedule = crisis.crisis_weight_schedule(dates, 0.5)

    targets = deployment.target_schedule(dates)
    requests = targets.loc[
        targets["targetWeight"].ne(0.0) | targets["tradeWeightProxy"].ne(0.0), ["date", "ticker"]
    ].drop_duplicates()
    requests["ticker"] = requests["ticker"].astype(str).str.upper()
    coverage = raw_price_overlays(requests)
    coverage.to_csv(COVERAGE_OUT, index=False)

    exact935 = copy_maps(feature935)
    exact1555 = copy_maps(feature1555)
    mark935 = copy_maps(feature935)
    mark1555 = copy_maps(feature1555)
    for row in coverage.itertuples(index=False):
        if row.event == "both" or not np.isfinite(row.price):
            continue
        if row.event == "0935":
            if row.source == "raw_exact":
                put(exact935, row.date, row.ticker, row.price)
                put(mark935, row.date, row.ticker, row.price)
            elif row.source == "raw_asof":
                put(mark935, row.date, row.ticker, row.price)
        elif row.event == "1555":
            if row.source == "raw_exact":
                put(exact1555, row.date, row.ticker, row.price)
                put(mark1555, row.date, row.ticker, row.price)
            elif row.source == "raw_asof":
                put(mark1555, row.date, row.ticker, row.price)

    summaries = []
    yearly = []
    event_frames = []
    contrib_frames = []
    concentration = []
    qa = []
    for spec in SCENARIOS:
        p935 = exact935 if spec["raw_exact"] else feature935
        p1555 = exact1555 if spec["raw_exact"] else feature1555
        m935 = mark935 if spec["asof_marks"] else p935
        m1555 = mark1555 if spec["asof_marks"] else p1555
        scenario = {"scenario": spec["scenario"], "crisis_scale": 0.5, "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0}
        daily, events, contrib = crisis.simulate(
            scenario, core, spy, pair_events, p935, p1555, schedule,
            name_cap=0.03, hard_gross_cap=3.0,
            missing_name_limit=2 if spec["fail_safe"] else None,
            missing_notional_limit=0.02 if spec["fail_safe"] else None,
            mark935=m935, mark1555=m1555, require_current_execution=True,
        )
        summary = base.summary_row(scenario, daily, events)
        summary.update({
            "failSafeBreaches": int(events["fail_safe_breach"].sum()),
            "disabledEventMarks": int(events["policy_disabled"].sum()),
            "capEventMarks": int(events["target_cap_scale"].lt(1.0).sum()),
        })
        summaries.append(summary)
        yearly.extend(base.yearly_rows(daily))
        concentration.extend(concentration_rows(str(spec["scenario"]), contrib))
        event_frames.append(events)
        contrib_frames.append(contrib)
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - base.START_CAPITAL)
        qa.append({"scenario": spec["scenario"], "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        print("MISSING_REPLAY", summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENT_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_missing_price_replay.py",
        "engine": "raits/research/stocks_pit_full_lead_crisis_eventtime_audit.py",
        "inputs": [str(base.CORE_DAILY), str(base.PAIR_EVENTS), str(crisis.SOURCE_SIGNALS), str(base.PAIR_PRICES).replace("\\", "/"), str(base.SPY_BARS).replace("\\", "/"), str(RAW_5M).replace("\\", "/")],
        "pre_registered_scenarios": SCENARIOS,
        "price_contract": "Raw exact 09:35 open is executable. A prior raw bar close available by event time and no more than five minutes old is mark-only. Missing exact execution freezes an existing holding and blocks opening/increasing that name.",
        "sample_label": "Touched research 2018-2024 only. No 2025-2026 opened.",
        "selection_warning": "Operational replay of frozen signals and controls, not clean OOS evidence.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(COVERAGE_OUT), str(CONCENTRATION_OUT), str(EVENT_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("COVERAGE", coverage.groupby(["event", "source"]).size().to_dict(), flush=True)
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, COVERAGE_OUT, CONCENTRATION_OUT, EVENT_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
