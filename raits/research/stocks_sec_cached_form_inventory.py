from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


CACHE_DIR = Path("raits/data/cache/external_events/sec_submissions_pit_2018_2026")
RAW_DIR = CACHE_DIR / "raw"
CIK_UNIVERSE = CACHE_DIR / "top500_cik_universe.csv"
OUT = CACHE_DIR / "sec_cached_form_inventory_2017_2026.csv"
MANIFEST = CACHE_DIR / "sec_cached_form_inventory_2017_2026_manifest.json"
START = pd.Timestamp("2017-01-01")
END = pd.Timestamp("2026-09-16")


def columnar_rows(payload: dict, cik: str) -> list[dict[str, object]]:
    table = payload.get("filings", {}).get("recent") if "filings" in payload else payload
    if not isinstance(table, dict) or "accessionNumber" not in table:
        return []
    rows = []
    for index in range(len(table.get("accessionNumber", []))):
        rows.append(
            {
                "cik": cik,
                "accessionNumber": table.get("accessionNumber", [None])[index],
                "filingDate": table.get("filingDate", [None])[index],
                "acceptanceDateTime": table.get("acceptanceDateTime", [None])[index]
                if index < len(table.get("acceptanceDateTime", []))
                else None,
                "form": table.get("form", [None])[index] if index < len(table.get("form", [])) else None,
            }
        )
    return rows


def main() -> None:
    ciks = pd.read_csv(CIK_UNIVERSE, dtype={"cik": str})["cik"].astype(str).str.zfill(10).tolist()
    rows: list[dict[str, object]] = []
    files = 0
    for cik in ciks:
        for path in sorted((RAW_DIR / cik).glob("*.json")):
            rows.extend(columnar_rows(json.loads(path.read_text(encoding="utf-8")), cik))
            files += 1
    frame = pd.DataFrame(rows)
    frame["filingDate"] = pd.to_datetime(frame["filingDate"], errors="coerce")
    frame["form"] = frame["form"].fillna("").astype(str).str.strip()
    frame = frame[frame["filingDate"].between(START, END)].copy()
    frame = frame.drop_duplicates(["cik", "accessionNumber"], keep="first")
    frame["year"] = frame["filingDate"].dt.year
    inventory = (
        frame.groupby(["form", "year"], as_index=False)
        .agg(filings=("accessionNumber", "size"), issuer_ciks=("cik", "nunique"))
        .sort_values(["form", "year"])
    )
    inventory.to_csv(OUT, index=False)
    totals = (
        frame.groupby("form")
        .agg(filings=("accessionNumber", "size"), issuer_ciks=("cik", "nunique"))
        .sort_values("filings", ascending=False)
    )
    target_forms = ["4", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A", "6-K", "10-Q", "10-K", "8-K"]
    manifest = {
        "script": "raits/research/stocks_sec_cached_form_inventory.py",
        "source": "Previously cached SEC submissions JSON for PIT top500 issuer CIK union",
        "date_window": {"start": str(START.date()), "end": str(END.date())},
        "issuer_ciks": len(ciks),
        "raw_json_files": files,
        "unique_filings": len(frame),
        "target_form_totals": {
            form: {
                "filings": int(totals.loc[form, "filings"]) if form in totals.index else 0,
                "issuer_ciks": int(totals.loc[form, "issuer_ciks"]) if form in totals.index else 0,
            }
            for form in target_forms
        },
        "top_forms": totals.head(20).reset_index().to_dict(orient="records"),
        "output": str(OUT),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
