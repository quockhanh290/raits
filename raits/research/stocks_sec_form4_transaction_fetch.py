from __future__ import annotations

import argparse
import hashlib
import json
import math
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

import pandas as pd


SIGNALS = Path("STOCKS_SEC_OWNERSHIP_INSIDER_REACTION_DEV_2026-09-17_SIGNALS.csv")
EVENTS = Path("raits/data/cache/external_events/sec_submissions_pit_2018_2026/sec_ownership_insider_events_2017_2026.csv")
CACHE_DIR = Path("raits/data/cache/external_events/sec_form4_transactions_2018_2024")
RAW_DIR = CACHE_DIR / "raw_xml"
ACCESSIONS_OUT = CACHE_DIR / "sec_form4_transaction_accessions_2018_2024.csv"
SESSIONS_OUT = CACHE_DIR / "sec_form4_transaction_sessions_2018_2024.csv"
MANIFEST_OUT = CACHE_DIR / "sec_form4_transaction_manifest_2018_2024.json"
USER_AGENT = "Raits Equity Research research@raits.local"
ARCHIVE_ROOT = "https://www.sec.gov/Archives/edgar/data"
START = pd.Timestamp("2018-01-02")
END = pd.Timestamp("2024-12-31")
REQUEST_INTERVAL_SECONDS = 0.14
WORKERS = 4


class RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.lock = threading.Lock()
        self.next_start = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = max(self.next_start - now, 0.0)
            self.next_start = max(self.next_start, now) + self.interval
        if delay:
            time.sleep(delay)


RATE_LIMITER = RateLimiter(REQUEST_INTERVAL_SECONDS)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(element: ET.Element, name: str) -> ET.Element | None:
    return next((node for node in list(element) if local_name(node.tag) == name), None)


def nested_text(element: ET.Element, *names: str) -> str | None:
    node: ET.Element | None = element
    for name in names:
        if node is None:
            return None
        node = child(node, name)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def finite_positive(value: str | None) -> float | None:
    try:
        number = float(value) if value is not None else math.nan
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def parse_xml(path: Path, expected_cik: str) -> dict[str, object]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return {"parse_status": f"parse_error:{type(exc).__name__}"}
    if local_name(root.tag) != "ownershipDocument":
        return {"parse_status": f"unexpected_root:{local_name(root.tag)}"}
    issuer = next((node for node in root.iter() if local_name(node.tag) == "issuer"), None)
    issuer_cik = nested_text(issuer, "issuerCik") if issuer is not None else None
    normalized = str(issuer_cik or "").zfill(10)
    if normalized != expected_cik:
        return {"parse_status": "issuer_cik_mismatch", "xml_issuer_cik": normalized}

    result: dict[str, object] = {
        "parse_status": "ok",
        "xml_issuer_cik": normalized,
        "non_derivative_transaction_count": 0,
        "purchase_transaction_count": 0,
        "sale_transaction_count": 0,
        "purchase_missing_price_count": 0,
        "sale_missing_price_count": 0,
        "purchase_shares": 0.0,
        "sale_shares": 0.0,
        "purchase_dollars": 0.0,
        "sale_dollars": 0.0,
        "direct_transaction_count": 0,
        "indirect_transaction_count": 0,
    }
    for transaction in (node for node in root.iter() if local_name(node.tag) == "nonDerivativeTransaction"):
        result["non_derivative_transaction_count"] += 1
        code = nested_text(transaction, "transactionCoding", "transactionCode")
        acquired_disposed = nested_text(
            transaction, "transactionAmounts", "transactionAcquiredDisposedCode", "value"
        )
        shares = finite_positive(nested_text(transaction, "transactionAmounts", "transactionShares", "value"))
        price = finite_positive(
            nested_text(transaction, "transactionAmounts", "transactionPricePerShare", "value")
        )
        ownership = nested_text(transaction, "ownershipNature", "directOrIndirectOwnership", "value")
        if ownership == "D":
            result["direct_transaction_count"] += 1
        elif ownership == "I":
            result["indirect_transaction_count"] += 1

        side = "purchase" if code == "P" and acquired_disposed == "A" else "sale" if code == "S" and acquired_disposed == "D" else None
        if side is None:
            continue
        result[f"{side}_transaction_count"] += 1
        if shares is not None:
            result[f"{side}_shares"] += shares
        if price is None:
            result[f"{side}_missing_price_count"] += 1
        elif shares is not None:
            result[f"{side}_dollars"] += shares * price
    return result


def build_plan() -> tuple[pd.DataFrame, pd.DataFrame]:
    signals = pd.read_csv(SIGNALS, dtype={"cik": str, "accessionNumber": str})
    signals["cik"] = signals["cik"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)
    signals["date"] = pd.to_datetime(signals["date"]).dt.normalize()
    sessions = signals[
        signals["event_class"].eq("form4_cluster3")
        & signals["reaction"].eq("confirmed")
        & signals["date"].between(START, END)
    ][["cik", "date", "ticker", "accessionNumber", "filing_count"]].copy()
    sessions = sessions.drop_duplicates(["cik", "date"], keep="first")
    exploded = sessions.assign(accessionNumber=sessions["accessionNumber"].str.split("|")).explode("accessionNumber")
    exploded["accessionNumber"] = exploded["accessionNumber"].str.strip()

    events = pd.read_csv(EVENTS, dtype={"cik": str, "accessionNumber": str})
    events["cik"] = events["cik"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(10)
    events = events[events["form"].astype(str).eq("4")][["cik", "accessionNumber", "primaryDocument"]]
    events = events.drop_duplicates(["cik", "accessionNumber"], keep="first")
    plan = exploded.merge(events, on=["cik", "accessionNumber"], how="left", validate="many_to_one")
    plan["primary_basename"] = plan["primaryDocument"].fillna("").map(lambda value: PurePosixPath(value).name)
    unique = plan.drop_duplicates(["cik", "accessionNumber"], keep="first").copy()
    unique["accession_compact"] = unique["accessionNumber"].str.replace("-", "", regex=False)
    unique["url"] = unique.apply(
        lambda row: f"{ARCHIVE_ROOT}/{int(row.cik)}/{row.accession_compact}/{row.primary_basename}", axis=1
    )
    unique["cache_path"] = unique.apply(
        lambda row: str(RAW_DIR / row.cik / f"{row.accession_compact}.xml"), axis=1
    )
    return sessions, plan.merge(
        unique[["cik", "accessionNumber", "accession_compact", "url", "cache_path"]],
        on=["cik", "accessionNumber"],
        how="left",
        validate="many_to_one",
    )


def fetch_one(row: dict[str, object]) -> dict[str, object]:
    path = Path(str(row["cache_path"]))
    base = {
        "cik": str(row["cik"]),
        "accessionNumber": str(row["accessionNumber"]),
        "primaryDocument": str(row.get("primaryDocument", "")),
        "url": str(row["url"]),
        "cache_path": str(path),
    }
    if not str(row.get("primary_basename", "")):
        return base | {"fetch_status": "missing_primary_document", "http_status": None}
    if path.exists() and parse_xml(path, str(row["cik"])).get("parse_status") == "ok":
        return base | {"fetch_status": "cached", "http_status": 200}

    path.parent.mkdir(parents=True, exist_ok=True)
    last_error = "unknown"
    last_status: int | None = None
    for attempt in range(5):
        RATE_LIMITER.wait()
        request = urllib.request.Request(
            str(row["url"]),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", "Host": "www.sec.gov"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                last_status = int(response.status)
            if not payload.lstrip().startswith(b"<"):
                last_error = "non_xml_payload"
            else:
                temporary = path.with_suffix(".xml.part")
                temporary.write_bytes(payload)
                temporary.replace(path)
                parsed = parse_xml(path, str(row["cik"]))
                if parsed.get("parse_status") == "ok":
                    return base | {"fetch_status": "downloaded", "http_status": last_status}
                last_error = str(parsed.get("parse_status"))
        except urllib.error.HTTPError as exc:
            last_status = int(exc.code)
            last_error = f"http_{exc.code}"
            if exc.code not in {403, 429, 500, 502, 503, 504}:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"request_error:{type(exc).__name__}"
        time.sleep(min(2**attempt, 16))
    return base | {"fetch_status": last_error, "http_status": last_status}


def aggregate_sessions(plan: pd.DataFrame, accessions: pd.DataFrame) -> pd.DataFrame:
    parsed_columns = [
        "parse_status",
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
    joined = plan.merge(
        accessions[["cik", "accessionNumber"] + parsed_columns],
        on=["cik", "accessionNumber"],
        how="left",
        validate="many_to_one",
    )
    joined["parsed_accession"] = joined["parse_status"].eq("ok").astype(int)
    numeric = [column for column in parsed_columns if column != "parse_status"]
    joined[numeric] = joined[numeric].fillna(0.0)
    aggregations: dict[str, tuple[str, str]] = {
        "ticker": ("ticker", "first"),
        "accessionNumber": ("accessionNumber", lambda values: "|".join(sorted(set(values.astype(str))))),
        "planned_accessions": ("accessionNumber", "nunique"),
        "parsed_accessions": ("parsed_accession", "sum"),
    }
    aggregations.update({column: (column, "sum") for column in numeric})
    sessions = joined.groupby(["cik", "date"], as_index=False).agg(**aggregations)
    sessions["net_purchase_dollars"] = sessions["purchase_dollars"] - sessions["sale_dollars"]
    return sessions.sort_values(["date", "cik"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch and parse the frozen 2018-2024 Form 4 XML set.")
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sessions, plan = build_plan()
    unique = plan.drop_duplicates(["cik", "accessionNumber"], keep="first").copy()
    if len(sessions) != 779 or len(unique) != 5832:
        raise RuntimeError(f"Frozen fetch-set mismatch: sessions={len(sessions)}, accessions={len(unique)}")

    rows: list[dict[str, object]] = []
    records = unique.to_dict(orient="records")
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(fetch_one, row): row for row in records}
        for completed, future in enumerate(as_completed(futures), start=1):
            fetched = future.result()
            parsed = parse_xml(Path(str(fetched["cache_path"])), str(fetched["cik"])) if Path(str(fetched["cache_path"])).exists() else {"parse_status": "no_file"}
            rows.append(fetched | parsed)
            if completed % 250 == 0 or completed == len(futures):
                print(f"FORM4_FETCH {completed}/{len(futures)}", flush=True)

    accessions = pd.DataFrame(rows).sort_values(["cik", "accessionNumber"])
    accessions.to_csv(ACCESSIONS_OUT, index=False)
    session_frame = aggregate_sessions(plan, accessions)
    session_frame.to_csv(SESSIONS_OUT, index=False)
    parse_counts = accessions["parse_status"].value_counts(dropna=False).to_dict()
    manifest = {
        "script": "raits/research/stocks_sec_form4_transaction_fetch.py",
        "source": "SEC Archives ownershipDocument XML",
        "sample": {"start": str(START.date()), "end": str(END.date())},
        "declared_user_agent": USER_AGENT,
        "minimum_request_start_interval_seconds": REQUEST_INTERVAL_SECONDS,
        "workers": max(1, args.workers),
        "planned_sessions": len(sessions),
        "planned_unique_accessions": len(unique),
        "parse_status_counts": parse_counts,
        "purchase_transaction_count": int(accessions["purchase_transaction_count"].fillna(0).sum()),
        "sale_transaction_count": int(accessions["sale_transaction_count"].fillna(0).sum()),
        "purchase_missing_price_count": int(accessions["purchase_missing_price_count"].fillna(0).sum()),
        "sale_missing_price_count": int(accessions["sale_missing_price_count"].fillna(0).sum()),
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
