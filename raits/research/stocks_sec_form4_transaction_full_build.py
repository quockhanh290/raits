from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from stocks_sec_form4_transaction_bulk_build import (
    BULK_DIR,
    QUARTERS,
    first_existing,
    normalized_accession,
    numeric,
    read_table,
    sha256,
    valid_zip,
)
import zipfile


EVENTS = Path("raits/data/cache/external_events/sec_submissions_pit_2018_2026/sec_ownership_insider_events_2017_2026.csv")
FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet"
)
CACHE_DIR = Path("raits/data/cache/external_events/sec_form4_transactions_2018_2024")
ACCESSIONS_OUT = CACHE_DIR / "sec_form4_transaction_accessions_full_corrected_2018_2024.csv"
SESSIONS_OUT = CACHE_DIR / "sec_form4_transaction_sessions_corrected_2018_2024.csv"
MANIFEST_OUT = CACHE_DIR / "sec_form4_transaction_full_corrected_manifest_2018_2024.json"
LOWER_BOUND = pd.Timestamp("2017-12-29 09:15", tz="America/New_York").tz_convert("UTC")
END_ACCEPTED = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
METRICS = [
    "non_derivative_transaction_count",
    "purchase_transaction_count",
    "sale_transaction_count",
    "purchase_missing_price_count",
    "sale_missing_price_count",
    "purchase_shares",
    "sale_shares",
    "purchase_dollars",
    "sale_dollars",
    "direct_transaction_count",
    "indirect_transaction_count",
]


def event_inventory() -> pd.DataFrame:
    events = pd.read_csv(EVENTS, dtype={"cik": str, "accessionNumber": str})
    events = events[events["event_class"].eq("form4")].copy()
    events["accepted_utc"] = pd.to_datetime(events["accepted_et"], utc=True, errors="coerce")
    events = events[events["accepted_utc"].between(LOWER_BOUND, END_ACCEPTED)].copy()
    events["accession_compact"] = normalized_accession(events["accessionNumber"])
    events = events.sort_values(["accession_compact", "accepted_utc", "cik"])
    return events.drop_duplicates("accession_compact", keep="first")[[
        "accession_compact", "accessionNumber", "accepted_utc", "primaryDocument"
    ]]


def summarize_transactions(transaction: pd.DataFrame) -> pd.DataFrame:
    if transaction.empty:
        return pd.DataFrame(columns=["accession_compact"] + METRICS)
    code = first_existing(transaction, ["TRANS_CODE", "TRANSACTION_CODE"])
    acquired = first_existing(transaction, ["TRANS_ACQUIRED_DISP_CD", "TRANS_ACQUIRED_DISPOSED_CODE"])
    shares_column = first_existing(transaction, ["TRANS_SHARES", "TRANSACTION_SHARES"])
    price_column = first_existing(transaction, ["TRANS_PRICEPERSHARE", "TRANS_PRICE_PER_SHARE"])
    ownership = first_existing(transaction, ["DIRECT_INDIRECT_OWNERSHIP", "DIRECT_OR_INDIRECT_OWNERSHIP"])
    transaction["shares"] = numeric(transaction[shares_column])
    transaction["price"] = numeric(transaction[price_column])
    transaction["valid_shares"] = transaction["shares"].where(transaction["shares"].gt(0))
    transaction["valid_price"] = transaction["price"].where(transaction["price"].gt(0))
    transaction["is_purchase"] = transaction[code].eq("P") & transaction[acquired].eq("A")
    transaction["is_sale"] = transaction[code].eq("S") & transaction[acquired].eq("D")
    transaction["purchase_dollars"] = (
        transaction["valid_shares"] * transaction["valid_price"]
    ).where(transaction["is_purchase"], 0.0).fillna(0.0)
    transaction["sale_dollars"] = (
        transaction["valid_shares"] * transaction["valid_price"]
    ).where(transaction["is_sale"], 0.0).fillna(0.0)
    transaction["purchase_shares"] = transaction["valid_shares"].where(transaction["is_purchase"], 0.0).fillna(0.0)
    transaction["sale_shares"] = transaction["valid_shares"].where(transaction["is_sale"], 0.0).fillna(0.0)
    transaction["purchase_transaction_count"] = transaction["is_purchase"].astype(int)
    transaction["sale_transaction_count"] = transaction["is_sale"].astype(int)
    transaction["purchase_missing_price_count"] = (
        transaction["is_purchase"] & transaction["valid_price"].isna()
    ).astype(int)
    transaction["sale_missing_price_count"] = (
        transaction["is_sale"] & transaction["valid_price"].isna()
    ).astype(int)
    transaction["direct_transaction_count"] = transaction[ownership].eq("D").astype(int)
    transaction["indirect_transaction_count"] = transaction[ownership].eq("I").astype(int)
    transaction["non_derivative_transaction_count"] = 1
    return transaction.groupby("accession_compact", as_index=False)[METRICS].sum()


def parse_quarters(target_ids: set[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for year, quarter in QUARTERS:
        path = BULK_DIR / f"{year}q{quarter}_form345.zip"
        if not valid_zip(path):
            raise RuntimeError(f"Missing valid SEC bulk ZIP: {path}")
        with zipfile.ZipFile(path) as archive:
            submission = read_table(archive, "SUBMISSION")
            accession_column = first_existing(submission, ["ACCESSION_NUMBER", "ACCESSIONNUMBER"])
            submission["accession_compact"] = normalized_accession(submission[accession_column])
            submission = submission[submission["accession_compact"].isin(target_ids)].copy()
            form_column = first_existing(submission, ["DOCUMENT_TYPE", "FORMTYPE", "FORM_TYPE"])
            issuer_column = first_existing(submission, ["ISSUERCIK", "ISSUER_CIK"])
            submission = submission[submission[form_column].astype(str).str.strip().eq("4")].copy()
            submission["cik"] = (
                submission[issuer_column].astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(10)
            )
            submission = submission[["accession_compact", "cik"]].drop_duplicates("accession_compact")

            transaction = read_table(archive, "NONDERIV_TRANS")
            tx_accession = first_existing(transaction, ["ACCESSION_NUMBER", "ACCESSIONNUMBER"])
            transaction["accession_compact"] = normalized_accession(transaction[tx_accession])
            transaction = transaction[transaction["accession_compact"].isin(set(submission["accession_compact"]))].copy()
            totals = summarize_transactions(transaction)
            frame = submission.merge(totals, on="accession_compact", how="left", validate="one_to_one")
            frame[METRICS] = frame[METRICS].fillna(0.0)
            frame["bulk_quarter"] = f"{year}Q{quarter}"
            frames.append(frame)
        print(f"FORM4_FULL_PARSE {year}Q{quarter} accessions={len(frame)}", flush=True)
    return pd.concat(frames, ignore_index=True).drop_duplicates("accession_compact", keep="first")


def assign_sessions(accessions: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    calendar = pd.read_parquet(FILTER, columns=["date"])
    sessions = sorted(pd.to_datetime(calendar["date"]).dt.normalize().drop_duplicates())
    cutoffs = pd.DatetimeIndex(
        [date.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=15) for date in sessions]
    ).tz_convert("UTC")
    accepted = pd.to_datetime(accessions["accepted_utc"], utc=True, errors="coerce")
    indices = np.searchsorted(cutoffs.asi8, accepted.astype("int64").to_numpy(), side="right")
    valid = accepted.notna().to_numpy() & accepted.ge(LOWER_BOUND).to_numpy() & (indices < len(sessions))
    assigned = accessions.loc[valid].copy()
    assigned["date"] = [sessions[index] for index in indices[valid]]
    session = assigned.groupby(["cik", "date"], as_index=False).agg(
        accessionNumber=("accessionNumber", lambda values: "|".join(sorted(set(values.astype(str))))),
        filing_count=("accession_compact", "nunique"),
        parsed_accessions=("accession_compact", "size"),
        accepted_utc=("accepted_utc", "min"),
        **{column: (column, "sum") for column in METRICS},
    )
    session["net_purchase_dollars"] = session["purchase_dollars"] - session["sale_dollars"]
    clusters = session[session["filing_count"].ge(3)].sort_values(["date", "cik"]).copy()
    qa = {
        "calendarStart": str(sessions[0].date()),
        "calendarEnd": str(sessions[-1].date()),
        "calendarSessions": len(sessions),
        "assignedAccessions": len(assigned),
        "issuerSessionsAll": len(session),
        "issuerCluster3Sessions": len(clusters),
        "minimumClusterCount": int(clusters["filing_count"].min()) if len(clusters) else 0,
    }
    return clusters, qa


def main() -> None:
    events = event_inventory()
    parsed = parse_quarters(set(events["accession_compact"]))
    accessions = events.merge(parsed, on="accession_compact", how="left", validate="one_to_one")
    accessions["parse_status"] = np.where(accessions["cik"].notna(), "ok", "missing_bulk_submission")
    accessions[METRICS] = accessions[METRICS].fillna(0.0)
    accessions.to_csv(ACCESSIONS_OUT, index=False)
    valid = accessions[accessions["parse_status"].eq("ok")].copy()
    sessions, calendar_qa = assign_sessions(valid)
    sessions.to_csv(SESSIONS_OUT, index=False)
    manifest = {
        "script": "raits/research/stocks_sec_form4_transaction_full_build.py",
        "correction": "Uses full PIT trading calendar for SEC acceptance assignment; does not use feature-cache dates as the calendar.",
        "inputs": [str(EVENTS), str(FILTER)] + [
            str(BULK_DIR / f"{year}q{quarter}_form345.zip") for year, quarter in QUARTERS
        ],
        "input_hashes": {
            str(EVENTS): sha256(EVENTS),
            **{
                str(BULK_DIR / f"{year}q{quarter}_form345.zip"): sha256(
                    BULK_DIR / f"{year}q{quarter}_form345.zip"
                )
                for year, quarter in QUARTERS
            },
        },
        "accepted_row_cutoff_utc": str(END_ACCEPTED),
        "source_event_accessions": len(events),
        "parse_status_counts": accessions["parse_status"].value_counts(dropna=False).to_dict(),
        "purchase_transaction_count": int(accessions["purchase_transaction_count"].sum()),
        "sale_transaction_count": int(accessions["sale_transaction_count"].sum()),
        "purchase_missing_price_count": int(accessions["purchase_missing_price_count"].sum()),
        "sale_missing_price_count": int(accessions["sale_missing_price_count"].sum()),
        "calendar_qa": calendar_qa,
        "outputs": {
            "accessions": str(ACCESSIONS_OUT),
            "accessions_sha256": sha256(ACCESSIONS_OUT),
            "sessions": str(SESSIONS_OUT),
            "sessions_sha256": sha256(SESSIONS_OUT),
        },
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
