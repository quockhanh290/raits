from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_sec_form4_purchase_drift_replay as base


PREREG = Path("STOCKS_SEC_FORM4_ROLE_PURCHASE_DRIFT_PREREG_2026-09-24.json")
ROLES = Path(
    "raits/data/cache/external_events/sec_form4_transactions_2018_2024/"
    "sec_form4_reporting_owner_roles_2018_2024.csv"
)
PREFIX = "STOCKS_SEC_FORM4_ROLE_PURCHASE_DRIFT_DEV_2026-09-24"
SELECTION_OUT = Path(f"{PREFIX}_SELECTION.json")
ROLE_NAMES = ["ceo", "cfo", "c_suite", "nonofficer_director", "ten_percent_owner"]
CANDIDATES = [
    {
        "variant": "form4_ceo_purchase_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["ceo_purchase_transaction_count"].ge(1),
    },
    {
        "variant": "form4_cfo_purchase_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["cfo_purchase_transaction_count"].ge(1),
    },
    {
        "variant": "form4_csuite_purchase100k_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["c_suite_purchase_dollars"].ge(100_000),
    },
    {
        "variant": "form4_nonofficer_director_purchase100k_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["nonofficer_director_purchase_dollars"].ge(100_000),
    },
    {
        "variant": "form4_tenpercent_purchase100k_hold20",
        "hold_sessions": 20,
        "filter": lambda frame: frame["ten_percent_owner_purchase_dollars"].ge(100_000),
    },
]


def role_session_events() -> tuple[pd.DataFrame, dict[str, object]]:
    accessions = pd.read_csv(
        base.ACCESSIONS,
        dtype={"cik": str, "accessionNumber": str, "accession_compact": str},
    )
    roles = pd.read_csv(ROLES, dtype={"accession_compact": str})
    accessions["accession_compact"] = accessions["accession_compact"].astype(str).str.strip()
    roles["accession_compact"] = roles["accession_compact"].astype(str).str.strip()
    role_columns = [f"is_{name}" for name in ROLE_NAMES]
    roles[role_columns] = roles[role_columns].astype(str).apply(lambda column: column.str.lower().eq("true"))
    accessions = accessions.merge(
        roles[["accession_compact", "reporting_owner_count"] + role_columns],
        on="accession_compact",
        how="inner",
        validate="one_to_one",
    )
    accessions = accessions[accessions["parse_status"].eq("ok")].copy()
    accessions["cik"] = accessions["cik"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)
    accessions["accepted_utc"] = pd.to_datetime(accessions["accepted_utc"], utc=True, errors="coerce")
    accessions = accessions[
        accessions["accepted_utc"].ge(base.LOWER_BOUND)
        & accessions["accepted_utc"].le(pd.Timestamp("2024-12-31 23:59:59", tz="UTC"))
    ].copy()
    for name in ROLE_NAMES:
        accessions[f"{name}_purchase_transaction_count"] = (
            accessions["purchase_transaction_count"] * accessions[f"is_{name}"].astype(int)
        )
        accessions[f"{name}_purchase_dollars"] = (
            accessions["purchase_dollars"] * accessions[f"is_{name}"].astype(int)
        )
        accessions[f"{name}_purchase_accessions"] = (
            accessions["purchase_transaction_count"].ge(1) & accessions[f"is_{name}"]
        ).astype(int)
    accessions["joint_owner_purchase_accession"] = (
        accessions["purchase_transaction_count"].ge(1) & accessions["reporting_owner_count"].gt(1)
    ).astype(int)

    calendar = pd.read_parquet(base.FILTER, columns=["date"])
    sessions = sorted(pd.to_datetime(calendar["date"]).dt.normalize().drop_duplicates())
    cutoffs = pd.DatetimeIndex(
        [date.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=15) for date in sessions]
    ).tz_convert("UTC")
    accepted = accessions["accepted_utc"]
    indices = np.searchsorted(cutoffs.asi8, accepted.astype("int64").to_numpy(), side="right")
    valid = accepted.notna().to_numpy() & (indices < len(sessions))
    assigned = accessions.loc[valid].copy()
    assigned["date"] = pd.to_datetime([sessions[index] for index in indices[valid]]).normalize()
    assigned = assigned[assigned["date"].between(base.DEV_START, base.VAL_END)].copy()
    aggregations: dict[str, tuple[str, object]] = {
        "accepted_utc": ("accepted_utc", "min"),
        "accessionNumber": ("accessionNumber", lambda values: "|".join(sorted(set(values.astype(str))))),
        "filing_count": ("accessionNumber", "nunique"),
        "joint_owner_purchase_accessions": ("joint_owner_purchase_accession", "sum"),
    }
    for name in ROLE_NAMES:
        aggregations[f"{name}_purchase_transaction_count"] = (f"{name}_purchase_transaction_count", "sum")
        aggregations[f"{name}_purchase_dollars"] = (f"{name}_purchase_dollars", "sum")
        aggregations[f"{name}_purchase_accessions"] = (f"{name}_purchase_accessions", "sum")
    events = assigned.groupby(["cik", "date"], as_index=False).agg(**aggregations)
    qa = {
        "sourceAccessions": int(len(accessions)),
        "assignedAccessionsInExecutableDateRange": int(len(assigned)),
        "issuerSessions": int(len(events)),
        "jointOwnerPurchaseAccessions": int(assigned["joint_owner_purchase_accession"].sum()),
        "rolePurchaseAccessions": {
            name: int(assigned[f"{name}_purchase_accessions"].sum()) for name in ROLE_NAMES
        },
    }
    return events, qa


def build_signals(intra: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    events, event_qa = role_session_events()
    sessions = sorted(intra["date"].drop_duplicates())
    members = base.load_top500_representatives("development")
    dates = pd.DataFrame({"date": sessions})
    snapshots = members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned_snapshots = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    mapped = events.merge(assigned_snapshots, on="date", how="inner", validate="many_to_one")
    mapped = mapped.merge(members, on=["snapshot_date", "cik"], how="inner", validate="many_to_one")
    eligible = base.load_eligible("development", base.DEV_START, base.VAL_END)
    panel = mapped.merge(eligible, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.merge(intra, on=["date", "ticker"], how="inner", validate="many_to_one")
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=["entry935", "exit1555", "adv20"])
    panel = panel[(panel["entry935"] > 0) & (panel["exit1555"] > 0)].copy()
    panel["direction"] = 1
    panel["event_class"] = "form4_role_purchase_drift"
    panel["reaction"] = "none"
    panel["advParticipationAt3Pct"] = (base.START_CAPITAL * 0.03) / panel["adv20"]
    panel = panel.sort_values(["date", "cik", "ticker"]).drop_duplicates(["date", "cik"], keep="first")
    role_session_counts = {
        candidate["variant"]: int(candidate["filter"](panel).sum()) for candidate in CANDIDATES
    }
    qa = event_qa | {
        "mappedTop500IssuerSessions": int(len(mapped)),
        "eligibleExactPriceIssuerSessions": int(len(panel)),
        "eligibleRoleSessionCountsBeforeCompleteHold": role_session_counts,
    }
    return panel, qa


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
            and dev["entries"] >= 75
            and dev["effectiveTickerCount"] >= 20
            and dev["top10PositivePnlShare"] <= 0.65
        )
        val_pass = bool(
            val["pnl"] > 0
            and val8["pnl"] > 0
            and len(val_years) == 2
            and (val_years["pnl"] >= 0).all()
            and val["ddPct"] >= -0.10
            and val["entries"] >= 25
            and val["effectiveTickerCount"] >= 10
            and val["top10PositivePnlShare"] <= 0.75
        )
        rows.append(
            {
                "variant": variant,
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
        key=lambda row: (-row["developmentSharpe"], -row["developmentStress8Sharpe"], -row["developmentEntries"], row["variant"]),
    )
    selected = ranked[0] if ranked else None
    validation_pass = bool(selected and selected["validationPass"])
    return {
        "candidates": rows,
        "selectedOnDevelopment": selected["variant"] if selected else None,
        "selectedValidationPass": validation_pass,
        "familyStatus": "CONTINUE_NEEDS_AUDIT" if validation_pass else "KILL_BEFORE_OOS",
        "selectionAudit": "One development-only role selection; validation cannot substitute another role.",
    }


def main() -> None:
    argparse.ArgumentParser(description="Replay preregistered Form 4 role-conditioned purchase drift.").parse_args()
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_family_performance"):
        raise RuntimeError("Family preregistration is not frozen")
    intra = base.load_intraday()
    signals, signal_qa = build_signals(intra)
    all_daily: list[pd.DataFrame] = []
    all_events: list[pd.DataFrame] = []
    all_trades: list[pd.DataFrame] = []
    all_contrib: list[pd.DataFrame] = []
    metrics_rows: list[dict[str, object]] = []
    candidate_counts: dict[str, dict[str, int]] = {}
    stages = [("development", base.DEV_START, base.DEV_END), ("validation", base.VAL_START, base.VAL_END)]
    for candidate in CANDIDATES:
        variant = candidate["variant"]
        filtered = signals[candidate["filter"](signals)].copy()
        candidate_counts[variant] = {}
        for stage, start, end in stages:
            stage_intra = intra[intra["date"].between(start, end)].copy()
            sessions = sorted(stage_intra["date"].drop_duplicates())
            stage_signals = filtered[filtered["date"].between(start, end)].copy()
            stage_signals = base.complete_hold_filter(stage_signals, sessions, 20)
            candidate_counts[variant][stage] = int(len(stage_signals))
            p935, p1555 = base.price_maps(stage_intra)
            for cost_bps in (4.0, 8.0):
                scenario = f"{variant}_cost{int(cost_bps)}"
                daily, events, trades, contrib = base.simulate(
                    variant, 20, cost_bps, sessions, stage_signals, p935, p1555
                )
                for frame in (daily, events, trades, contrib):
                    frame["bookStage"] = stage
                all_daily.append(daily)
                all_events.append(events)
                all_trades.append(trades)
                all_contrib.append(contrib)
                row = base.extended_metrics(scenario, daily, events, trades, contrib, start, end)
                row["bookStage"] = stage
                metrics_rows.append(row)
                print("ROLE_PURCHASE", variant, stage, int(cost_bps), row["pnl"], flush=True)

    daily_all = pd.concat(all_daily, ignore_index=True)
    events_all = pd.concat(all_events, ignore_index=True)
    trades_all = pd.concat(all_trades, ignore_index=True)
    contrib_all = pd.concat(all_contrib, ignore_index=True)
    metrics = pd.DataFrame(metrics_rows)
    yearly = base.yearly_rows(daily_all)
    qa_rows = []
    for (scenario, stage), group in events_all.groupby(["scenario", "bookStage"], sort=True):
        daily_group = daily_all[daily_all["scenario"].eq(scenario) & daily_all["bookStage"].eq(stage)]
        contrib_group = contrib_all[
            contrib_all["scenario"].eq(scenario) & contrib_all["bookStage"].eq(stage)
        ]
        event_pnl = float(group["event_pnl"].sum())
        daily_pnl = float(daily_group["daily_pnl"].sum())
        contrib_pnl = float(contrib_group["pnl"].sum())
        ending_pnl = float(group.iloc[-1]["equity"] - base.START_CAPITAL)
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
        "script": "raits/research/stocks_sec_form4_role_purchase_drift_replay.py",
        "preregistration": str(PREREG),
        "adaptiveResearch": True,
        "stageIsolation": "Independent $100k books with complete hold20 only",
        "oos_2025_2026_consumed": False,
        "inputs": [str(base.ACCESSIONS), str(ROLES), str(base.INTRADAY), str(base.CAP), str(base.FILTER)],
        "input_hashes": {str(path): base.sha256(path) for path in [base.ACCESSIONS, ROLES, base.CAP]},
        "signal_qa": signal_qa,
        "candidate_signal_counts": candidate_counts,
        "selection": selection,
        "outputs_prefix": PREFIX,
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("ROLE_PURCHASE_SELECTION", json.dumps(selection), flush=True)


if __name__ == "__main__":
    main()
