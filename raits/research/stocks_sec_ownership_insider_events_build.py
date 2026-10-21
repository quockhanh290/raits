from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


START = pd.Timestamp("2017-01-01")
END = pd.Timestamp("2026-09-16 23:59:59")
CACHE_DIR = Path("raits/data/cache/external_events/sec_submissions_pit_2018_2026")
RAW_DIR = CACHE_DIR / "raw"
CIK_UNIVERSE = CACHE_DIR / "top500_cik_universe.csv"
EVENTS_OUT = CACHE_DIR / "sec_ownership_insider_events_2017_2026.csv"
MANIFEST_OUT = CACHE_DIR / "sec_ownership_insider_events_2017_2026_manifest.json"
FORM_CLASS = {
    "4": "form4",
    "SC 13D": "ownership_active_initial",
    "SCHEDULE 13D": "ownership_active_initial",
    "SC 13G": "ownership_passive_initial",
    "SCHEDULE 13G": "ownership_passive_initial",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def columnar_rows(payload: dict, source_file: str, cik: str) -> list[dict[str, object]]:
    table = payload.get("filings", {}).get("recent") if "filings" in payload else payload
    if not isinstance(table, dict) or "accessionNumber" not in table:
        return []
    rows = []
    for index in range(len(table.get("accessionNumber", []))):
        row = {
            key: values[index] if index < len(values) else None
            for key, values in table.items()
            if isinstance(values, list)
        }
        row["cik"] = cik
        row["source_file"] = source_file
        rows.append(row)
    return rows


def parse_acceptance(value: object) -> pd.Timestamp:
    if value is None or not str(value).strip():
        return pd.NaT
    timestamp = pd.Timestamp(str(value))
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward")
    return timestamp.tz_convert("America/New_York")


def main() -> None:
    ciks = pd.read_csv(CIK_UNIVERSE, dtype={"cik": str})["cik"].astype(str).str.zfill(10).tolist()
    rows: list[dict[str, object]] = []
    files = 0
    for cik in ciks:
        for path in sorted((RAW_DIR / cik).glob("*.json")):
            rows.extend(columnar_rows(json.loads(path.read_text(encoding="utf-8")), path.name, cik))
            files += 1
    frame = pd.DataFrame(rows)
    frame["form"] = frame["form"].fillna("").astype(str).str.strip()
    frame = frame[frame["form"].isin(FORM_CLASS)].copy()
    frame["event_class"] = frame["form"].map(FORM_CLASS)
    frame["accepted_et"] = frame["acceptanceDateTime"].map(parse_acceptance)
    frame = frame[frame["accepted_et"].notna()].copy()
    accepted_naive = frame["accepted_et"].map(lambda value: value.tz_localize(None))
    frame = frame[(accepted_naive >= START) & (accepted_naive <= END)].copy()
    frame = frame.sort_values(["cik", "accepted_et", "accessionNumber"])
    frame = frame.drop_duplicates(["cik", "accessionNumber"], keep="first")
    keep = [
        "cik",
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "accepted_et",
        "form",
        "event_class",
        "primaryDocument",
        "source_file",
    ]
    frame[keep].to_csv(EVENTS_OUT, index=False)
    manifest = {
        "script": "raits/research/stocks_sec_ownership_insider_events_build.py",
        "source": "Previously cached SEC submissions JSON",
        "date_window": {"start": str(START.date()), "end": str(END.date())},
        "issuer_ciks": len(ciks),
        "raw_json_files": files,
        "event_rows": len(frame),
        "event_class_counts": frame["event_class"].value_counts().sort_index().to_dict(),
        "form_counts": frame["form"].value_counts().sort_index().to_dict(),
        "duplicate_cik_accession": int(frame.duplicated(["cik", "accessionNumber"]).sum()),
        "output": str(EVENTS_OUT),
        "output_sha256": sha256(EVENTS_OUT),
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
