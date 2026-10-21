from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

from stocks_sec_form4_transaction_fetch import aggregate_sessions, build_plan


CACHE_DIR = Path("raits/data/cache/external_events/sec_form4_transactions_2018_2024")
BULK_DIR = CACHE_DIR / "sec_quarterly_bulk"
ACCESSIONS_OUT = CACHE_DIR / "sec_form4_transaction_accessions_2018_2024.csv"
SESSIONS_OUT = CACHE_DIR / "sec_form4_transaction_sessions_2018_2024.csv"
MANIFEST_OUT = CACHE_DIR / "sec_form4_transaction_bulk_manifest_2018_2024.json"
ROOT = "https://dcm.sec.gov/files/structureddata/data/insider-transactions-data-sets"
USER_AGENT = "Raits Equity Research research@raits.local"
QUARTERS = [(2017, 4)] + [(year, quarter) for year in range(2018, 2025) for quarter in range(1, 5)]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def normalized_accession(values: pd.Series) -> pd.Series:
    return values.astype("string").str.replace("-", "", regex=False).str.strip()


def find_member(archive: zipfile.ZipFile, required: str) -> str:
    matches = [name for name in archive.namelist() if Path(name).stem.upper() == required]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one {required} table, found {matches}")
    return matches[0]


def read_table(archive: zipfile.ZipFile, table: str) -> pd.DataFrame:
    member = find_member(archive, table)
    with archive.open(member) as handle:
        frame = pd.read_csv(handle, sep="\t", dtype=str, low_memory=False)
    frame.columns = [column.strip().upper() for column in frame.columns]
    return frame


def valid_zip(path: Path) -> bool:
    if not path.exists() or not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            find_member(archive, "SUBMISSION")
            find_member(archive, "NONDERIV_TRANS")
        return True
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return False


def download_quarter(year: int, quarter: int) -> tuple[Path, str]:
    filename = f"{year}q{quarter}_form345.zip"
    path = BULK_DIR / filename
    if valid_zip(path):
        return path, "cached"
    url = f"{ROOT}/{filename}"
    last_error = "unknown"
    for attempt in range(5):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = response.read()
            temporary = path.with_suffix(".zip.part")
            temporary.write_bytes(payload)
            if not zipfile.is_zipfile(temporary):
                last_error = "invalid_zip_payload"
            else:
                temporary.replace(path)
                return path, "downloaded"
        except urllib.error.HTTPError as exc:
            last_error = f"http_{exc.code}"
            if exc.code not in {403, 429, 500, 502, 503, 504}:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"request_error:{type(exc).__name__}"
        time.sleep(min(30 * (2**attempt), 300))
    raise RuntimeError(f"Failed {url}: {last_error}")


def numeric(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce")


def first_existing(frame: pd.DataFrame, names: list[str]) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise RuntimeError(f"None of the required columns exists: {names}")


def parse_bulk(paths: list[Path], targets: pd.DataFrame) -> pd.DataFrame:
    target_ids = set(targets["accession_compact"])
    submissions: list[pd.DataFrame] = []
    transactions: list[pd.DataFrame] = []
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            sub = read_table(archive, "SUBMISSION")
            sub_accession = first_existing(sub, ["ACCESSION_NUMBER", "ACCESSIONNUMBER"])
            sub["accession_compact"] = normalized_accession(sub[sub_accession])
            sub = sub[sub["accession_compact"].isin(target_ids)].copy()
            if not sub.empty:
                issuer_column = first_existing(sub, ["ISSUERCIK", "ISSUER_CIK"])
                form_column = first_existing(sub, ["DOCUMENT_TYPE", "FORMTYPE", "FORM_TYPE"])
                sub["xml_issuer_cik"] = sub[issuer_column].astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(10)
                sub["bulk_form"] = sub[form_column].astype("string").str.strip()
                submissions.append(sub[["accession_compact", "xml_issuer_cik", "bulk_form"]])

            tx = read_table(archive, "NONDERIV_TRANS")
            tx_accession = first_existing(tx, ["ACCESSION_NUMBER", "ACCESSIONNUMBER"])
            tx["accession_compact"] = normalized_accession(tx[tx_accession])
            tx = tx[tx["accession_compact"].isin(target_ids)].copy()
            if not tx.empty:
                transactions.append(tx)
        print(f"FORM4_BULK_PARSE {path.name}", flush=True)

    submission = pd.concat(submissions, ignore_index=True).drop_duplicates("accession_compact", keep="first")
    transaction = pd.concat(transactions, ignore_index=True) if transactions else pd.DataFrame()
    target = targets.copy()
    target = target.merge(submission, on="accession_compact", how="left", validate="one_to_one")
    target["parse_status"] = "ok"
    target.loc[target["xml_issuer_cik"].isna(), "parse_status"] = "missing_bulk_submission"
    target.loc[
        target["xml_issuer_cik"].notna() & target["xml_issuer_cik"].ne(target["cik"]), "parse_status"
    ] = "issuer_cik_mismatch"
    target.loc[target["bulk_form"].notna() & target["bulk_form"].ne("4"), "parse_status"] = "form_mismatch"

    metrics = [
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
    for column in metrics:
        target[column] = 0.0
    if not transaction.empty:
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
        transaction["purchase_missing_price_count"] = (transaction["is_purchase"] & transaction["valid_price"].isna()).astype(int)
        transaction["sale_missing_price_count"] = (transaction["is_sale"] & transaction["valid_price"].isna()).astype(int)
        transaction["direct_transaction_count"] = transaction[ownership].eq("D").astype(int)
        transaction["indirect_transaction_count"] = transaction[ownership].eq("I").astype(int)
        transaction["non_derivative_transaction_count"] = 1
        totals = transaction.groupby("accession_compact", as_index=False)[metrics].sum()
        target = target.drop(columns=metrics).merge(totals, on="accession_compact", how="left", validate="one_to_one")
        target[metrics] = target[metrics].fillna(0.0)
    target.loc[target["parse_status"].ne("ok"), metrics] = 0.0
    target["fetch_status"] = "sec_quarterly_bulk"
    target["http_status"] = 200
    target["url"] = "SEC quarterly Insider Transactions Data Set; see bulk_source_zip"
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build frozen Form 4 semantics from official SEC quarterly bulk data.")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()
    BULK_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    statuses: dict[str, str] = {}
    for year, quarter in QUARTERS:
        expected = BULK_DIR / f"{year}q{quarter}_form345.zip"
        if args.skip_download:
            if not valid_zip(expected):
                raise RuntimeError(f"Missing valid bulk ZIP: {expected}")
            path, status = expected, "cached"
        else:
            path, status = download_quarter(year, quarter)
        paths.append(path)
        statuses[path.name] = status
        print(f"FORM4_BULK_FETCH {path.name} {status}", flush=True)

    sessions, plan = build_plan()
    unique = plan.drop_duplicates(["cik", "accessionNumber"], keep="first").copy()
    accessions = parse_bulk(paths, unique)
    accessions["bulk_source_zip"] = accessions["accessionNumber"].str.extract(r"-(\d\d)-")[0].map(
        lambda year: f"20{year} quarterly file"
    )
    accessions = accessions.sort_values(["cik", "accessionNumber"])
    accessions.to_csv(ACCESSIONS_OUT, index=False)
    session_frame = aggregate_sessions(plan, accessions)
    session_frame.to_csv(SESSIONS_OUT, index=False)
    manifest = {
        "script": "raits/research/stocks_sec_form4_transaction_bulk_build.py",
        "source": "Official SEC quarterly Insider Transactions Data Sets flattened from ownership XML as filed",
        "source_page": "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets",
        "quarters": [f"{year}Q{quarter}" for year, quarter in QUARTERS],
        "zip_statuses": statuses,
        "zip_hashes": {path.name: sha256(path) for path in paths},
        "planned_sessions": len(sessions),
        "planned_unique_accessions": len(unique),
        "parse_status_counts": accessions["parse_status"].value_counts(dropna=False).to_dict(),
        "purchase_transaction_count": int(accessions["purchase_transaction_count"].sum()),
        "sale_transaction_count": int(accessions["sale_transaction_count"].sum()),
        "purchase_missing_price_count": int(accessions["purchase_missing_price_count"].sum()),
        "sale_missing_price_count": int(accessions["sale_missing_price_count"].sum()),
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
