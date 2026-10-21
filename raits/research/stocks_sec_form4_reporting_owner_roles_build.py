from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pandas as pd

from stocks_sec_form4_transaction_bulk_build import (
    BULK_DIR,
    QUARTERS,
    normalized_accession,
    read_table,
    sha256,
    valid_zip,
)


ACCESSIONS = Path(
    "raits/data/cache/external_events/sec_form4_transactions_2018_2024/"
    "sec_form4_transaction_accessions_full_corrected_2018_2024.csv"
)
OUT = Path(
    "raits/data/cache/external_events/sec_form4_transactions_2018_2024/"
    "sec_form4_reporting_owner_roles_2018_2024.csv"
)
MANIFEST = Path(
    "raits/data/cache/external_events/sec_form4_transactions_2018_2024/"
    "sec_form4_reporting_owner_roles_2018_2024_manifest.json"
)
CEO_PATTERN = re.compile(r"chief\s+executive|(?<![a-z])ceo(?![a-z])", re.IGNORECASE)
CFO_PATTERN = re.compile(r"chief\s+financial|(?<![a-z])cfo(?![a-z])", re.IGNORECASE)


def main() -> None:
    target = pd.read_csv(ACCESSIONS, usecols=["accession_compact"], dtype=str)
    target_ids = set(target["accession_compact"].astype(str))
    frames: list[pd.DataFrame] = []
    for year, quarter in QUARTERS:
        path = BULK_DIR / f"{year}q{quarter}_form345.zip"
        if not valid_zip(path):
            raise RuntimeError(f"Missing valid SEC bulk ZIP: {path}")
        with zipfile.ZipFile(path) as archive:
            owners = read_table(archive, "REPORTINGOWNER")
        owners["accession_compact"] = normalized_accession(owners["ACCESSION_NUMBER"])
        owners = owners[owners["accession_compact"].isin(target_ids)].copy()
        owners["relationship"] = owners["RPTOWNER_RELATIONSHIP"].fillna("").astype(str)
        owners["title"] = owners["RPTOWNER_TITLE"].fillna("").astype(str)
        owners["is_ceo"] = owners["title"].str.contains(CEO_PATTERN, regex=True)
        owners["is_cfo"] = owners["title"].str.contains(CFO_PATTERN, regex=True)
        owners["is_c_suite"] = owners["is_ceo"] | owners["is_cfo"]
        owners["is_nonofficer_director"] = (
            owners["relationship"].str.contains("Director", case=False, regex=False)
            & ~owners["relationship"].str.contains("Officer", case=False, regex=False)
        )
        owners["is_ten_percent_owner"] = owners["relationship"].str.contains(
            "TenPercentOwner", case=False, regex=False
        )
        grouped = owners.groupby("accession_compact", as_index=False).agg(
            reporting_owner_count=("RPTOWNERCIK", "nunique"),
            is_ceo=("is_ceo", "max"),
            is_cfo=("is_cfo", "max"),
            is_c_suite=("is_c_suite", "max"),
            is_nonofficer_director=("is_nonofficer_director", "max"),
            is_ten_percent_owner=("is_ten_percent_owner", "max"),
        )
        frames.append(grouped)
        print(f"FORM4_ROLE_BUILD {year}Q{quarter} accessions={len(grouped)}", flush=True)
    roles = pd.concat(frames, ignore_index=True).drop_duplicates("accession_compact", keep="first")
    roles = target.merge(roles, on="accession_compact", how="left", validate="one_to_one")
    roles["reporting_owner_count"] = roles["reporting_owner_count"].fillna(0).astype(int)
    role_columns = [
        "is_ceo",
        "is_cfo",
        "is_c_suite",
        "is_nonofficer_director",
        "is_ten_percent_owner",
    ]
    roles[role_columns] = roles[role_columns].fillna(False).astype(bool)
    roles.to_csv(OUT, index=False)
    manifest = {
        "script": "raits/research/stocks_sec_form4_reporting_owner_roles_build.py",
        "source": "REPORTINGOWNER.tsv from official SEC quarterly Insider Transactions Data Sets",
        "input_accessions": str(ACCESSIONS),
        "input_accessions_sha256": sha256(ACCESSIONS),
        "accessions": len(roles),
        "accessions_without_reporting_owner": int(roles["reporting_owner_count"].eq(0).sum()),
        "joint_owner_accessions": int(roles["reporting_owner_count"].gt(1).sum()),
        "role_accession_counts": {column: int(roles[column].sum()) for column in role_columns},
        "output": str(OUT),
        "output_sha256": sha256(OUT),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
