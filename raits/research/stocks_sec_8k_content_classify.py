from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

import stocks_sec_8k_content_fetch as fetcher


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


COMPILED = {
    name: [re.compile(pattern, re.I | re.S) for pattern in patterns]
    for name, patterns in fetcher.PATTERNS.items()
}


def classify_row(row: dict[str, object]) -> dict[str, object] | None:
    path = Path(str(row["cache_path"]))
    if not path.exists() or path.stat().st_size == 0:
        return None
    with gzip.open(path, "rb") as handle:
        raw = handle.read().decode("utf-8", errors="replace")
    normalized = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).lower()
    acceptance = re.search(r"<ACCEPTANCE-DATETIME>\s*(\d{14})", raw, re.I)
    flags = {name: any(pattern.search(normalized) for pattern in patterns) for name, patterns in COMPILED.items()}
    return {
        "stage": row["stage"], "cik": str(row["cik"]).zfill(10), "ticker": row["ticker"],
        "filing_date": row["filing_date"], "accession_number": row["accession_number"],
        "filing_url": row["filing_url"], "acceptance_datetime": acceptance.group(1) if acceptance else "",
        "text_chars": len(normalized), **flags,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parallel local classifier for frozen SEC 8-K content cache.")
    parser.add_argument("--stage", choices=sorted(fetcher.STAGES), default="discovery")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--year", type=int, default=0)
    parser.add_argument("--combine", action="store_true")
    args = parser.parse_args()
    plan_path = fetcher.CACHE / f"plan_{args.stage}.csv"
    status_path = fetcher.CACHE / f"status_{args.stage}.csv"
    plan = pd.read_csv(plan_path, dtype={"cik": str, "accession_number": str})
    status = pd.read_csv(status_path)
    fetched = int(plan["cache_path"].map(lambda value: Path(value).exists()).sum())
    explicit_failures = int(status["status"].eq("ERROR").sum())
    unresolved = max(0, len(plan) - fetched - explicit_failures)
    if unresolved:
        raise RuntimeError(f"refusing incomplete coverage: unresolved={unresolved}")
    first_year, last_year = fetcher.STAGES[args.stage]
    if args.combine:
        parts = [fetcher.CACHE / f"labels_{args.stage}_{year}.csv" for year in range(first_year, last_year + 1)]
        if not all(path.exists() for path in parts):
            raise RuntimeError("refusing combine with missing yearly label part")
        labels = pd.concat([pd.read_csv(path, dtype={"cik": str, "accession_number": str}) for path in parts], ignore_index=True)
        if len(labels) != fetched:
            raise RuntimeError(f"combined rows {len(labels)} != fetched files {fetched}")
        labels_path = fetcher.CACHE / f"labels_{args.stage}.csv"
        labels.to_csv(labels_path, index=False)
        payload = {
            "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
            "fetchScriptHash": sha256(Path(fetcher.__file__)), "stage": args.stage,
            "plannedAccessions": len(plan), "fetchedAccessions": fetched,
            "explicitFailures": explicit_failures, "unresolvedAccessions": unresolved,
            "labelRows": len(labels), "missingAcceptanceTimestamp": int(labels["acceptance_datetime"].fillna("").eq("").sum()),
            "classCounts": {name: int(labels[name].sum()) for name in fetcher.PATTERNS},
            "labels": str(labels_path).replace("\\", "/"), "labelsHash": sha256(labels_path),
            "yearlyParts": {str(year): sha256(fetcher.CACHE / f"labels_{args.stage}_{year}.csv") for year in range(first_year, last_year + 1)},
            "post2021Consumed": False,
        }
        (fetcher.CACHE / f"classification_manifest_{args.stage}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="ascii"
        )
        print(json.dumps(payload, indent=2), flush=True)
        return
    if args.year:
        if not first_year <= args.year <= last_year:
            raise RuntimeError("year outside frozen stage")
        year_values = pd.to_datetime(plan["filing_date"]).dt.year
        subset = plan[year_values.eq(args.year)].copy()
        rows = []
        for index, row in enumerate(subset.to_dict("records"), start=1):
            result = classify_row(row)
            if result is not None:
                rows.append(result)
            if index % 1000 == 0:
                print(f"CLASSIFY {args.year} {index}/{len(subset)}", flush=True)
        part = pd.DataFrame(rows)
        part_path = fetcher.CACHE / f"labels_{args.stage}_{args.year}.csv"
        part.to_csv(part_path, index=False)
        print(json.dumps({"year": args.year, "planned": len(subset), "labels": len(part),
                          "path": str(part_path).replace("\\", "/"), "hash": sha256(part_path)}, indent=2), flush=True)
        return
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for index, row in enumerate(executor.map(classify_row, plan.to_dict("records"), chunksize=4), start=1):
            rows.append(row)
            if index % 1000 == 0:
                print(f"CLASSIFY {index}/{len(plan)}", flush=True)
    labels = pd.DataFrame([row for row in rows if row is not None])
    if len(labels) != fetched:
        raise RuntimeError(f"classified rows {len(labels)} != fetched files {fetched}")
    labels_path = fetcher.CACHE / f"labels_{args.stage}.csv"
    labels.to_csv(labels_path, index=False)
    payload = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "fetchScriptHash": sha256(Path(fetcher.__file__)), "stage": args.stage,
        "plannedAccessions": len(plan), "fetchedAccessions": fetched,
        "explicitFailures": explicit_failures, "unresolvedAccessions": unresolved,
        "labelRows": len(labels), "missingAcceptanceTimestamp": int(labels["acceptance_datetime"].fillna("").eq("").sum()),
        "classCounts": {name: int(labels[name].sum()) for name in fetcher.PATTERNS},
        "labels": str(labels_path).replace("\\", "/"), "labelsHash": sha256(labels_path),
        "post2021Consumed": False,
    }
    (fetcher.CACHE / f"classification_manifest_{args.stage}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="ascii"
    )
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
