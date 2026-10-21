from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from stocks_sec_ownership_insider_reaction_replay import (
    START_CAPITAL,
    load_eligible,
    load_top500_representatives,
    period_metrics,
    price_maps,
    simulate,
    yearly_rows,
)
from stocks_sec_form4_transaction_reaction_replay import extended_metrics


PREREG = Path("STOCKS_SEC_FORM4_PURCHASE_DRIFT_PREREG_2026-09-24.json")
ACCESSIONS = Path(
    "raits/data/cache/external_events/sec_form4_transactions_2018_2024/"
    "sec_form4_transaction_accessions_full_corrected_2018_2024.csv"
)
INTRADAY = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
CAP = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet"
)
PREFIX = "STOCKS_SEC_FORM4_PURCHASE_DRIFT_DEV_2026-09-24"
SELECTION_OUT = Path(f"{PREFIX}_SELECTION.json")
DEV_START = pd.Timestamp("2018-04-27")
DEV_END = pd.Timestamp("2022-12-30")
VAL_START = pd.Timestamp("2023-01-03")
VAL_END = pd.Timestamp("2024-12-31")
LOWER_BOUND = pd.Timestamp("2017-12-29 09:15", tz="America/New_York").tz_convert("UTC")
CANDIDATES = [
    {
        "variant": "form4_any_purchase_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["purchase_transaction_count"].ge(1),
    },
    {
        "variant": "form4_purchase100k_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["purchase_dollars"].ge(100_000),
    },
    {
        "variant": "form4_netpurchase100k_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["net_purchase_dollars"].ge(100_000),
    },
    {
        "variant": "form4_netpurchase100k_hold60",
        "hold_sessions": 60,
        "filter": lambda frame: frame["net_purchase_dollars"].ge(100_000),
    },
    {
        "variant": "form4_multiaccession_purchase100k_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["purchase_accessions"].ge(2) & frame["purchase_dollars"].ge(100_000),
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_intraday() -> pd.DataFrame:
    intra = pd.read_pickle(INTRADAY)[
        ["date", "ticker", "entry935", "exit1555", "first5_ret", "rvol930"]
    ].copy()
    intra["date"] = pd.to_datetime(intra["date"]).dt.normalize()
    intra["ticker"] = intra["ticker"].astype(str).str.upper()
    intra = intra[intra["date"].between(DEV_START, VAL_END)].copy()
    return intra


def assign_and_aggregate_accessions() -> tuple[pd.DataFrame, dict[str, object]]:
    accessions = pd.read_csv(ACCESSIONS, dtype={"cik": str, "accessionNumber": str})
    accessions = accessions[accessions["parse_status"].eq("ok")].copy()
    accessions["cik"] = accessions["cik"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)
    accessions["accepted_utc"] = pd.to_datetime(accessions["accepted_utc"], utc=True, errors="coerce")
    accessions = accessions[
        accessions["accepted_utc"].ge(LOWER_BOUND)
        & accessions["accepted_utc"].le(pd.Timestamp("2024-12-31 23:59:59", tz="UTC"))
    ].copy()
    accessions["has_purchase"] = accessions["purchase_transaction_count"].ge(1).astype(int)

    calendar = pd.read_parquet(FILTER, columns=["date"])
    sessions = sorted(pd.to_datetime(calendar["date"]).dt.normalize().drop_duplicates())
    cutoffs = pd.DatetimeIndex(
        [date.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=15) for date in sessions]
    ).tz_convert("UTC")
    accepted = accessions["accepted_utc"]
    indices = np.searchsorted(cutoffs.asi8, accepted.astype("int64").to_numpy(), side="right")
    valid = accepted.notna().to_numpy() & (indices < len(sessions))
    assigned = accessions.loc[valid].copy()
    assigned["date"] = [sessions[index] for index in indices[valid]]
    assigned = assigned[assigned["date"].between(DEV_START, VAL_END)].copy()
    session_events = assigned.groupby(["cik", "date"], as_index=False).agg(
        accepted_utc=("accepted_utc", "min"),
        accessionNumber=("accessionNumber", lambda values: "|".join(sorted(set(values.astype(str))))),
        filing_count=("accessionNumber", "nunique"),
        purchase_accessions=("has_purchase", "sum"),
        purchase_transaction_count=("purchase_transaction_count", "sum"),
        sale_transaction_count=("sale_transaction_count", "sum"),
        purchase_missing_price_count=("purchase_missing_price_count", "sum"),
        sale_missing_price_count=("sale_missing_price_count", "sum"),
        purchase_dollars=("purchase_dollars", "sum"),
        sale_dollars=("sale_dollars", "sum"),
    )
    session_events["net_purchase_dollars"] = session_events["purchase_dollars"] - session_events["sale_dollars"]
    qa = {
        "sourceAccessions": int(len(accessions)),
        "assignedAccessionsInExecutableDateRange": int(len(assigned)),
        "issuerSessions": int(len(session_events)),
        "issuerSessionsWithPurchase": int(session_events["purchase_transaction_count"].ge(1).sum()),
        "purchaseTransactions": int(session_events["purchase_transaction_count"].sum()),
        "purchaseMissingPriceTransactions": int(session_events["purchase_missing_price_count"].sum()),
    }
    return session_events, qa


def build_signals(intra: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    events, event_qa = assign_and_aggregate_accessions()
    sessions = sorted(intra["date"].drop_duplicates())
    members = load_top500_representatives("development")
    dates = pd.DataFrame({"date": sessions})
    snapshots = members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned_snapshots = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    mapped = events.merge(assigned_snapshots, on="date", how="inner", validate="many_to_one")
    mapped = mapped.merge(members, on=["snapshot_date", "cik"], how="inner", validate="many_to_one")
    eligible = load_eligible("development", DEV_START, VAL_END)
    panel = mapped.merge(eligible, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.merge(intra, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=["entry935", "exit1555", "adv20"])
    panel = panel[(panel["entry935"] > 0) & (panel["exit1555"] > 0)].copy()
    panel["direction"] = 1
    panel["event_class"] = "form4_open_market_purchase_drift"
    panel["reaction"] = "none"
    panel["advParticipationAt3Pct"] = (START_CAPITAL * 0.03) / panel["adv20"]
    panel = panel.sort_values(["date", "cik", "ticker"]).drop_duplicates(["date", "cik"], keep="first")
    qa = event_qa | {
        "mappedTop500IssuerSessions": int(len(mapped)),
        "eligibleExactPriceIssuerSessions": int(len(panel)),
        "eligibleExactPricePurchaseSessions": int(panel["purchase_transaction_count"].ge(1).sum()),
    }
    return panel, qa


def complete_hold_filter(signals: pd.DataFrame, sessions: list[pd.Timestamp], hold: int) -> pd.DataFrame:
    last_entry_index = len(sessions) - hold
    if last_entry_index < 0:
        return signals.iloc[0:0].copy()
    eligible_dates = set(sessions[: last_entry_index + 1])
    return signals[signals["date"].isin(eligible_dates)].copy()


def metric_row(metrics: pd.DataFrame, scenario: str, stage: str) -> pd.Series:
    matches = metrics[metrics["scenario"].eq(scenario) & metrics["bookStage"].eq(stage)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one metric row for {scenario}/{stage}, found {len(matches)}")
    return matches.iloc[0]


def choose_variant(metrics: pd.DataFrame, yearly: pd.DataFrame) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for candidate in CANDIDATES:
        variant = candidate["variant"]
        dev = metric_row(metrics, f"{variant}_cost4", "development")
        dev8 = metric_row(metrics, f"{variant}_cost8", "development")
        val = metric_row(metrics, f"{variant}_cost4", "validation")
        val8 = metric_row(metrics, f"{variant}_cost8", "validation")
        dev_years = yearly[
            yearly["scenario"].eq(f"{variant}_cost4") & yearly["year"].between(2018, 2022)
        ]
        val_years = yearly[
            yearly["scenario"].eq(f"{variant}_cost4") & yearly["year"].between(2023, 2024)
        ]
        positive_years = int((dev_years["pnl"] > 0).sum())
        dev_pass = bool(
            positive_years >= 3
            and dev["pnl"] > 0
            and dev8["pnl"] > 0
            and dev["ddPct"] >= -0.15
            and dev["entries"] >= 100
            and dev["effectiveTickerCount"] >= 25
            and dev["top10PositivePnlShare"] <= 0.60
        )
        val_pass = bool(
            val["pnl"] > 0
            and val8["pnl"] > 0
            and len(val_years) == 2
            and (val_years["pnl"] >= 0).all()
            and val["ddPct"] >= -0.10
            and val["entries"] >= 40
            and val["effectiveTickerCount"] >= 15
            and val["top10PositivePnlShare"] <= 0.70
        )
        rows.append(
            {
                "variant": variant,
                "holdSessions": candidate["hold_sessions"],
                "developmentPass": dev_pass,
                "validationPass": val_pass,
                "positiveDevelopmentYears": positive_years,
                "developmentPnl": float(dev["pnl"]),
                "developmentStress8Pnl": float(dev8["pnl"]),
                "developmentSharpe": float(dev["sharpe"]),
                "developmentStress8Sharpe": float(dev8["sharpe"]),
                "developmentDdDollar": float(dev["ddDollar"]),
                "developmentDdPct": float(dev["ddPct"]),
                "developmentEntries": int(dev["entries"]),
                "developmentEffectiveTickerCount": float(dev["effectiveTickerCount"]),
                "developmentTop10Share": float(dev["top10PositivePnlShare"]),
                "validationPnl": float(val["pnl"]),
                "validationStress8Pnl": float(val8["pnl"]),
                "validationSharpe": float(val["sharpe"]),
                "validationDdDollar": float(val["ddDollar"]),
                "validationDdPct": float(val["ddPct"]),
                "validationEntries": int(val["entries"]),
                "validationEffectiveTickerCount": float(val["effectiveTickerCount"]),
                "validationTop10Share": float(val["top10PositivePnlShare"]),
            }
        )
    ranked = sorted(
        [row for row in rows if row["developmentPass"]],
        key=lambda row: (
            -row["developmentSharpe"],
            -row["developmentStress8Sharpe"],
            -row["developmentEntries"],
            row["holdSessions"],
        ),
    )
    selected = ranked[0] if ranked else None
    validation_pass = bool(selected and selected["validationPass"])
    return {
        "candidates": rows,
        "selectedOnDevelopment": selected["variant"] if selected else None,
        "selectedValidationPass": validation_pass,
        "familyStatus": "CONTINUE_NEEDS_AUDIT" if validation_pass else "KILL_BEFORE_OOS",
        "selectionAudit": "One selection on the independent 2018-2022 book; validation cannot substitute a runner-up.",
    }


def main() -> None:
    argparse.ArgumentParser(description="Replay preregistered PIT Form 4 open-market purchase drift.").parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_family_performance"):
        raise RuntimeError("Family preregistration is not frozen")
    intra = load_intraday()
    signals, signal_qa = build_signals(intra)
    all_daily: list[pd.DataFrame] = []
    all_events: list[pd.DataFrame] = []
    all_trades: list[pd.DataFrame] = []
    all_contrib: list[pd.DataFrame] = []
    metrics_rows: list[dict[str, object]] = []
    candidate_counts: dict[str, dict[str, int]] = {}
    stage_contracts = [
        ("development", DEV_START, DEV_END),
        ("validation", VAL_START, VAL_END),
    ]
    for candidate in CANDIDATES:
        variant = candidate["variant"]
        filtered = signals[candidate["filter"](signals)].copy()
        candidate_counts[variant] = {}
        for stage, start, end in stage_contracts:
            stage_intra = intra[intra["date"].between(start, end)].copy()
            stage_sessions = sorted(stage_intra["date"].drop_duplicates())
            stage_signals = filtered[filtered["date"].between(start, end)].copy()
            stage_signals = complete_hold_filter(stage_signals, stage_sessions, candidate["hold_sessions"])
            candidate_counts[variant][stage] = int(len(stage_signals))
            p935, p1555 = price_maps(stage_intra)
            for cost_bps in (4.0, 8.0):
                scenario = f"{variant}_cost{int(cost_bps)}"
                daily, events, trades, contrib = simulate(
                    variant,
                    candidate["hold_sessions"],
                    cost_bps,
                    stage_sessions,
                    stage_signals,
                    p935,
                    p1555,
                )
                for frame in (daily, events, trades, contrib):
                    frame["bookStage"] = stage
                all_daily.append(daily)
                all_events.append(events)
                all_trades.append(trades)
                all_contrib.append(contrib)
                row = extended_metrics(scenario, daily, events, trades, contrib, start, end)
                row["bookStage"] = stage
                metrics_rows.append(row)
                print("PURCHASE_DRIFT", variant, stage, int(cost_bps), row["pnl"], flush=True)

    daily_all = pd.concat(all_daily, ignore_index=True)
    events_all = pd.concat(all_events, ignore_index=True)
    trades_all = pd.concat(all_trades, ignore_index=True)
    contrib_all = pd.concat(all_contrib, ignore_index=True)
    metrics = pd.DataFrame(metrics_rows)
    yearly = yearly_rows(daily_all)
    qa_rows = []
    for (scenario, stage), group in events_all.groupby(["scenario", "bookStage"], sort=True):
        daily_group = daily_all[daily_all["scenario"].eq(scenario) & daily_all["bookStage"].eq(stage)]
        contrib_group = contrib_all[
            contrib_all["scenario"].eq(scenario) & contrib_all["bookStage"].eq(stage)
        ]
        event_pnl = float(group["event_pnl"].sum())
        daily_pnl = float(daily_group["daily_pnl"].sum())
        contrib_pnl = float(contrib_group["pnl"].sum())
        ending_pnl = float(group.iloc[-1]["equity"] - START_CAPITAL)
        qa_rows.append(
            {
                "scenario": scenario,
                "bookStage": stage,
                "eventPnl": event_pnl,
                "dailyPnl": daily_pnl,
                "contribPnl": contrib_pnl,
                "endingPnl": ending_pnl,
                "eventMinusDaily": event_pnl - daily_pnl,
                "eventMinusContrib": event_pnl - contrib_pnl,
                "eventMinusEnding": event_pnl - ending_pnl,
                "maxGross": float(group["gross"].max()),
                "missingMarks": int(group["missing_marks"].max()),
            }
        )
    qa = pd.DataFrame(qa_rows)
    selection = choose_variant(metrics, yearly)
    SELECTION_OUT.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    signals.to_csv(f"{PREFIX}_SIGNALS.csv", index=False)
    metrics.to_csv(f"{PREFIX}_SUMMARY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    daily_all.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    events_all.to_csv(f"{PREFIX}_EVENT_LEDGER.csv", index=False)
    trades_all.to_csv(f"{PREFIX}_TRADE_LEDGER.csv", index=False)
    contrib_all.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)
    qa.to_csv(f"{PREFIX}_QA.csv", index=False)
    manifest = {
        "script": "raits/research/stocks_sec_form4_purchase_drift_replay.py",
        "preregistration": str(PREREG),
        "stageIsolation": "Independent $100k books; complete holds only; no carry across 2022/2023 boundary.",
        "oos_2025_2026_consumed": False,
        "inputs": [str(ACCESSIONS), str(INTRADAY), str(CAP), str(FILTER)],
        "input_hashes": {str(path): sha256(path) for path in [ACCESSIONS, CAP]},
        "signal_qa": signal_qa,
        "candidate_signal_counts": candidate_counts,
        "selection": selection,
        "outputs_prefix": PREFIX,
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("PURCHASE_DRIFT_SELECTION", json.dumps(selection), flush=True)


if __name__ == "__main__":
    main()
