from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd


START = pd.Timestamp("2017-01-01")
END = pd.Timestamp("2026-09-16 23:59:59")
CACHE_DIR = Path("raits/data/cache/external_events/sec_submissions_pit_2018_2026")
RAW_DIR = CACHE_DIR / "raw"
CIK_UNIVERSE = CACHE_DIR / "top500_cik_universe.csv"
EVENTS_OUT = CACHE_DIR / "sec_8k_material_events_2017_2026.csv"
MANIFEST_OUT = CACHE_DIR / "sec_8k_material_events_2017_2026_manifest.json"
ITEM_PATTERN = re.compile(r"\d+\.\d+")


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
    count = len(table.get("accessionNumber", []))
    rows = []
    for index in range(count):
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


def item_tokens(value: object) -> frozenset[str]:
    return frozenset(ITEM_PATTERN.findall(str(value or "")))


def classify(items: frozenset[str]) -> str | None:
    if "2.02" in items:
        return None
    if items.intersection({"1.01", "2.01"}):
        return "deal"
    if "5.02" in items:
        return "governance"
    return None


def main() -> None:
    universe = pd.read_csv(CIK_UNIVERSE, dtype={"cik": str})
    ciks = universe["cik"].astype(str).str.zfill(10).sort_values().tolist()
    rows: list[dict[str, object]] = []
    files = 0
    for cik in ciks:
        for path in sorted((RAW_DIR / cik).glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows.extend(columnar_rows(payload, path.name, cik))
            files += 1
    frame = pd.DataFrame(rows)
    frame["form"] = frame["form"].fillna("").astype(str)
    frame = frame[frame["form"].eq("8-K")].copy()
    frame["items"] = frame.get("items", pd.Series("", index=frame.index)).fillna("").astype(str)
    frame["item_tokens"] = frame["items"].map(item_tokens)
    frame["event_class"] = frame["item_tokens"].map(classify)
    frame = frame[frame["event_class"].notna()].copy()
    frame["accepted_et"] = frame["acceptanceDateTime"].map(parse_acceptance)
    frame = frame[frame["accepted_et"].notna()].copy()
    accepted_naive = frame["accepted_et"].map(lambda value: value.tz_localize(None))
    frame = frame[(accepted_naive >= START) & (accepted_naive <= END)].copy()
    frame["item_tokens"] = frame["item_tokens"].map(lambda values: "|".join(sorted(values)))
    frame = frame.sort_values(["cik", "accepted_et", "accessionNumber", "event_class"])
    frame = frame.drop_duplicates(["cik", "accessionNumber", "event_class"], keep="first")
    keep = [
        "cik",
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "accepted_et",
        "form",
        "items",
        "item_tokens",
        "event_class",
        "primaryDocument",
        "isXBRL",
        "isInlineXBRL",
        "source_file",
    ]
    frame[keep].to_csv(EVENTS_OUT, index=False)
    manifest = {
        "script": "raits/research/stocks_sec_material_events_build.py",
        "source": "Previously cached SEC submissions JSON",
        "date_window": {"start": str(START.date()), "end": str(END.date())},
        "ciks": len(ciks),
        "raw_json_files": files,
        "event_rows": len(frame),
        "event_class_counts": frame["event_class"].value_counts().sort_index().to_dict(),
        "unique_accessions": int(frame["accessionNumber"].nunique()),
        "duplicate_cik_accession_class": int(frame.duplicated(["cik", "accessionNumber", "event_class"]).sum()),
        "output": str(EVENTS_OUT),
        "output_sha256": sha256(EVENTS_OUT),
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
