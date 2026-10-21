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
    load_features,
    load_top500_representatives,
    period_metrics,
    price_maps,
    simulate,
    yearly_rows,
)


PREREG = Path("STOCKS_SEC_FORM4_TRANSACTION_REACTION_PREREG_2026-09-18.json")
TRANSACTIONS = Path(
    "raits/data/cache/external_events/sec_form4_transactions_2018_2024/sec_form4_transaction_sessions_corrected_2018_2024.csv"
)
ACCESSIONS = Path(
    "raits/data/cache/external_events/sec_form4_transactions_2018_2024/sec_form4_transaction_accessions_full_corrected_2018_2024.csv"
)
DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
CAP = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet"
)
PREFIX = "STOCKS_SEC_FORM4_TRANSACTION_REACTION_DEV_2026-09-18"
SELECTION_OUT = Path(f"{PREFIX}_SELECTION.json")
START = pd.Timestamp("2018-01-02")
END = pd.Timestamp("2024-12-31")
DEV_START = pd.Timestamp("2018-01-02")
DEV_END = pd.Timestamp("2022-12-30")
VAL_START = pd.Timestamp("2023-01-03")
VAL_END = pd.Timestamp("2024-12-31")
CANDIDATES = [
    {
        "variant": "form4_any_purchase_confirm_hold3",
        "hold_sessions": 3,
        "filter": lambda frame: frame["purchase_transaction_count"].ge(1),
    },
    {
        "variant": "form4_purchase100k_confirm_hold3",
        "hold_sessions": 3,
        "filter": lambda frame: frame["purchase_dollars"].ge(100_000),
    },
    {
        "variant": "form4_netpurchase100k_confirm_hold5",
        "hold_sessions": 5,
        "filter": lambda frame: frame["net_purchase_dollars"].ge(100_000),
    },
    {
        "variant": "form4_sale1m_confirm_hold3",
        "hold_sessions": 3,
        "filter": lambda frame: frame["sale_dollars"].ge(1_000_000),
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def build_market_signals(daily: pd.DataFrame, intra: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    transactions = pd.read_csv(TRANSACTIONS, dtype={"cik": str})
    transactions["cik"] = transactions["cik"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)
    transactions["date"] = pd.to_datetime(transactions["date"]).dt.normalize()
    transactions = transactions[transactions["date"].between(START, END)].copy()
    if "ticker" in transactions:
        transactions = transactions.rename(columns={"ticker": "source_signal_ticker"})
    if transactions.duplicated(["cik", "date"]).any() or transactions["filing_count"].lt(3).any():
        raise RuntimeError("Corrected transaction sessions violate issuer/session cluster3 uniqueness")
    planned_transaction_sessions = len(transactions)
    invalid_issuer_cluster_sessions = 0

    if "accessionNumber" not in transactions:
        raise RuntimeError("Transaction sessions are missing exact session-level accession provenance")

    sessions = sorted(intra["date"].drop_duplicates())
    members = load_top500_representatives("development")
    dates = pd.DataFrame({"date": sessions})
    snapshots = members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned_snapshots = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    mapped = transactions.merge(assigned_snapshots, on="date", how="left", validate="many_to_one")
    mapped = mapped.merge(members, on=["snapshot_date", "cik"], how="inner", validate="many_to_one")

    eligible = load_eligible("development", START, END)
    panel = mapped.merge(eligible, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.merge(daily, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.merge(intra, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["gap", "rvol930", "first5_ret", "entry935", "exit1555", "adv20"]
    )
    gate = (
        panel["gap"].abs().ge(0.01)
        & panel["rvol930"].ge(1.25)
        & panel["first5_ret"].abs().ge(0.002)
        & np.sign(panel["gap"]).eq(np.sign(panel["first5_ret"]))
    )
    signals = panel[gate].copy()
    signals["direction"] = np.sign(signals["gap"]).astype(int)
    signals["event_class"] = "form4_transaction_cluster3"
    signals["reaction"] = "confirmed"
    signals["advParticipationAt3Pct"] = (START_CAPITAL * 0.03) / signals["adv20"]
    signals = signals.sort_values(["date", "cik", "ticker"]).drop_duplicates(["date", "cik"], keep="first")
    qa = {
        "plannedMetadataTransactionSessions": int(planned_transaction_sessions),
        "validIssuerClusterSessions": int(len(transactions)),
        "invalidIssuerClusterSessionsExcluded": invalid_issuer_cluster_sessions,
        "mappedTop500Sessions": int(len(mapped)),
        "eligibleFeatureSessions": int(len(panel)),
        "reconfirmedMarketGateSessions": int(len(signals)),
        "transactionSessionsWithAllAccessionsParsed": int(
            (transactions["parsed_accessions"] == transactions["filing_count"]).sum()
        ),
        "transactionSessionsWithAnyParseFailure": int(
            (transactions["parsed_accessions"] != transactions["filing_count"]).sum()
        ),
    }
    return signals, qa


def extended_metrics(
    scenario: str,
    daily: pd.DataFrame,
    events: pd.DataFrame,
    trades: pd.DataFrame,
    contrib: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> dict[str, object]:
    row = period_metrics(scenario, daily, trades, contrib, start, end)
    event_period = events[
        events["timestamp"].dt.normalize().between(start, end)
    ] if not events.empty else events
    trade_period = trades[trades["date"].between(start, end)] if not trades.empty else trades
    row.update(
        {
            "turnover": float(event_period["turnover"].sum()) if not event_period.empty else 0.0,
            "tradeCost": float(event_period["trade_cost"].sum()) if not event_period.empty else 0.0,
            "borrowCost": float(event_period["borrow_cost"].sum()) if not event_period.empty else 0.0,
            "financingCost": float(event_period["financing_cost"].sum()) if not event_period.empty else 0.0,
            "averageGross": float(event_period["gross"].mean()) if not event_period.empty else 0.0,
            "tickerCount": int(trade_period.loc[trade_period["event"].eq("entry"), "ticker"].nunique())
            if not trade_period.empty
            else 0,
        }
    )
    return row


def metric_row(metrics: pd.DataFrame, scenario: str, start: pd.Timestamp) -> pd.Series:
    matches = metrics[metrics["scenario"].eq(scenario) & metrics["periodStart"].eq(start)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one metric row for {scenario} at {start.date()}, found {len(matches)}")
    return matches.iloc[0]


def choose_variant(metrics: pd.DataFrame, yearly: pd.DataFrame) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for candidate in CANDIDATES:
        variant = candidate["variant"]
        base = metric_row(metrics, f"{variant}_cost4", DEV_START)
        stress = metric_row(metrics, f"{variant}_cost8", DEV_START)
        validation = metric_row(metrics, f"{variant}_cost4", VAL_START)
        validation_stress = metric_row(metrics, f"{variant}_cost8", VAL_START)
        dev_years = yearly[
            yearly["scenario"].eq(f"{variant}_cost4") & yearly["year"].between(2018, 2022)
        ]
        validation_years = yearly[
            yearly["scenario"].eq(f"{variant}_cost4") & yearly["year"].between(2023, 2024)
        ]
        positive_dev_years = int((dev_years["pnl"] > 0).sum())
        development_pass = bool(
            positive_dev_years >= 3
            and base["pnl"] > 0
            and stress["pnl"] > 0
            and base["ddPct"] >= -0.15
            and base["entries"] >= 30
            and base["effectiveTickerCount"] >= 10
            and base["top10PositivePnlShare"] <= 0.75
        )
        validation_pass = bool(
            validation["pnl"] > 0
            and validation_stress["pnl"] > 0
            and len(validation_years) == 2
            and (validation_years["pnl"] >= 0).all()
            and validation["ddPct"] >= -0.10
            and validation["entries"] >= 15
            and validation["effectiveTickerCount"] >= 8
            and validation["top10PositivePnlShare"] <= 0.75
        )
        rows.append(
            {
                "variant": variant,
                "holdSessions": candidate["hold_sessions"],
                "developmentPass": development_pass,
                "validationPass": validation_pass,
                "positiveDevelopmentYears": positive_dev_years,
                "developmentPnl": float(base["pnl"]),
                "developmentStress8Pnl": float(stress["pnl"]),
                "developmentSharpe": float(base["sharpe"]),
                "developmentStress8Sharpe": float(stress["sharpe"]),
                "developmentDdDollar": float(base["ddDollar"]),
                "developmentDdPct": float(base["ddPct"]),
                "developmentEntries": int(base["entries"]),
                "developmentEffectiveTickerCount": float(base["effectiveTickerCount"]),
                "developmentTop10Share": float(base["top10PositivePnlShare"]),
                "validationPnl": float(validation["pnl"]),
                "validationStress8Pnl": float(validation_stress["pnl"]),
                "validationDdDollar": float(validation["ddDollar"]),
                "validationDdPct": float(validation["ddPct"]),
                "validationEntries": int(validation["entries"]),
                "validationEffectiveTickerCount": float(validation["effectiveTickerCount"]),
                "validationTop10Share": float(validation["top10PositivePnlShare"]),
            }
        )
    development_eligible = [row for row in rows if row["developmentPass"]]
    ranked = sorted(
        development_eligible,
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
        "familyStatus": "CONTINUE_NO_OOS_BY_TERMINAL_POLICY" if validation_pass else "KILL_BEFORE_OOS",
        "selectionAudit": "Variant ranked on 2018-2022 only; 2023-2024 cannot replace the selected variant.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the final preregistered transaction-level Form 4 family.")
    parser.parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_transaction_level_performance"):
        raise RuntimeError("Transaction-level preregistration is not frozen")
    if "2025" in str(TRANSACTIONS) or "2026" in str(TRANSACTIONS):
        raise RuntimeError("OOS paths are prohibited for this replay")

    daily, intra = load_features(DAILY, INTRADAY, START, END)
    signals, signal_qa = build_market_signals(daily, intra)
    sessions = sorted(intra["date"].drop_duplicates())
    p935, p1555 = price_maps(intra)
    daily_frames: list[pd.DataFrame] = []
    event_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    contrib_frames: list[pd.DataFrame] = []
    metric_rows: list[dict[str, object]] = []
    candidate_counts: dict[str, int] = {}

    for candidate in CANDIDATES:
        variant = candidate["variant"]
        candidate_signals = signals[candidate["filter"](signals)].copy()
        candidate_counts[variant] = len(candidate_signals)
        for cost_bps in (4.0, 8.0):
            scenario = f"{variant}_cost{int(cost_bps)}"
            day, event, trade, contrib = simulate(
                variant,
                candidate["hold_sessions"],
                cost_bps,
                sessions,
                candidate_signals,
                p935,
                p1555,
            )
            daily_frames.append(day)
            event_frames.append(event)
            trade_frames.append(trade)
            contrib_frames.append(contrib)
            metric_rows.append(extended_metrics(scenario, day, event, trade, contrib, DEV_START, DEV_END))
            metric_rows.append(extended_metrics(scenario, day, event, trade, contrib, VAL_START, VAL_END))
            print("FORM4_REPLAY", scenario, metric_rows[-2]["pnl"], metric_rows[-1]["pnl"], flush=True)

    daily_all = pd.concat(daily_frames, ignore_index=True)
    events_all = pd.concat(event_frames, ignore_index=True)
    trades_all = pd.concat(trade_frames, ignore_index=True)
    contrib_all = pd.concat(contrib_frames, ignore_index=True)
    metrics = pd.DataFrame(metric_rows)
    yearly = yearly_rows(daily_all)
    qa_rows = []
    for scenario, group in events_all.groupby("scenario", sort=True):
        event_pnl = float(group["event_pnl"].sum())
        day_pnl = float(daily_all.loc[daily_all["scenario"].eq(scenario), "daily_pnl"].sum())
        contrib_pnl = float(contrib_all.loc[contrib_all["scenario"].eq(scenario), "pnl"].sum())
        ending_pnl = float(group.iloc[-1]["equity"] - START_CAPITAL)
        qa_rows.append(
            {
                "scenario": scenario,
                "eventPnl": event_pnl,
                "dailyPnl": day_pnl,
                "contribPnl": contrib_pnl,
                "endingPnl": ending_pnl,
                "eventMinusDaily": event_pnl - day_pnl,
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
        "script": "raits/research/stocks_sec_form4_transaction_reaction_replay.py",
        "stage": "development_and_validation_only",
        "preregistration": str(PREREG),
        "sample": {"start": str(START.date()), "end": str(END.date())},
        "development": {"start": str(DEV_START.date()), "end": str(DEV_END.date())},
        "validation": {"start": str(VAL_START.date()), "end": str(VAL_END.date())},
        "oos_2025_2026_opened": False,
        "inputs": [str(TRANSACTIONS), str(ACCESSIONS), str(DAILY), str(INTRADAY), str(CAP), str(FILTER)],
        "input_hashes": {str(path): sha256(path) for path in [TRANSACTIONS, ACCESSIONS, CAP]},
        "signal_qa": signal_qa,
        "candidate_signal_counts": candidate_counts,
        "selection": selection,
        "outputs_prefix": PREFIX,
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("FORM4_SELECTION", json.dumps(selection), flush=True)


if __name__ == "__main__":
    main()
