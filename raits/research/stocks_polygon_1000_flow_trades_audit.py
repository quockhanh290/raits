from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


PLAN = Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.csv")
FETCH_SCRIPT = Path("raits/research/stocks_polygon_1000_flow_trades_fetch.py")
CACHE = Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022")
STATUS = CACHE / "status.csv"
MANIFEST = CACHE / "manifest.json"
AUDIT_CSV = Path("STOCKS_PIT_1000_FLOW_FETCH_AUDIT_2026-10-02.csv")
AUDIT_JSON = Path("STOCKS_PIT_1000_FLOW_FETCH_AUDIT_2026-10-02.json")
REQUIRED = {"sip_timestamp", "price", "size", "exchange", "ticker", "date"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def bounds(date_text: str) -> tuple[int, int]:
    start = pd.Timestamp(f"{date_text} 09:25:00", tz="US/Eastern").tz_convert("UTC")
    end = pd.Timestamp(f"{date_text} 10:05:00", tz="US/Eastern").tz_convert("UTC")
    return int(start.value), int(end.value)


def inspect(row: pd.Series) -> dict[str, object]:
    path = Path(str(row["path"]))
    result: dict[str, object] = {"date": row["date"], "ticker": row["ticker"], "path": str(path).replace("\\", "/"),
        "exists": path.exists(), "statusRows": int(row["rows"]), "parquetRows": 0, "rowMatch": False,
        "schemaOk": False, "boundsOk": False, "error": ""}
    if not path.exists():
        result["error"] = "missing"
        return result
    try:
        parquet = pq.ParquetFile(path)
        result["parquetRows"] = parquet.metadata.num_rows
        result["rowMatch"] = parquet.metadata.num_rows == int(row["rows"])
        result["schemaOk"] = REQUIRED.issubset(set(parquet.schema_arrow.names))
        index = parquet.schema_arrow.get_field_index("sip_timestamp")
        minima, maxima = [], []
        for group in range(parquet.metadata.num_row_groups):
            stats = parquet.metadata.row_group(group).column(index).statistics
            if stats is None or not stats.has_min_max:
                raise RuntimeError("missing timestamp statistics")
            minima.append(int(stats.min)); maxima.append(int(stats.max))
        start_ns, end_ns = bounds(str(row["date"]))
        result["boundsOk"] = min(minima) >= start_ns and max(maxima) < end_ns
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return result


def main() -> None:
    plan = pd.read_csv(PLAN, usecols=["date", "ticker"], dtype=str).drop_duplicates()
    status = pd.read_csv(STATUS, dtype={"date": str, "ticker": str, "status": str})
    latest = status.drop_duplicates(["date", "ticker"], keep="last")
    joined = plan.merge(latest, on=["date", "ticker"], how="outer", indicator=True, validate="one_to_one")
    completed = joined[joined["_merge"].eq("both") & joined["status"].eq("OK")].copy()
    with ThreadPoolExecutor(max_workers=16) as executor:
        audit = pd.DataFrame(executor.map(inspect, [row for _, row in completed.iterrows()]))
    audit.to_csv(AUDIT_CSV, index=False)
    manifest = json.loads(MANIFEST.read_text(encoding="ascii"))
    summary = {
        "planKeys": len(plan), "planTickers": int(plan["ticker"].nunique()), "planMaxDate": plan["date"].max(),
        "statusRows": len(status), "latestRows": len(latest), "duplicateAttempts": len(status) - len(latest),
        "latestOk": int(latest["status"].eq("OK").sum()), "latestEmpty": int(latest["status"].eq("EMPTY").sum()),
        "latestError": int(latest["status"].eq("ERROR").sum()),
        "missingKeys": int(joined["_merge"].eq("left_only").sum()), "extraKeys": int(joined["_merge"].eq("right_only").sum()),
        "files": len(audit), "filesMissing": int((~audit["exists"]).sum()),
        "rowMismatch": int((~audit["rowMatch"]).sum()), "badSchema": int((~audit["schemaOk"]).sum()),
        "outOfBounds": int((~audit["boundsOk"]).sum()), "fileErrors": int(audit["error"].astype(str).ne("").sum()),
        "parquetRows": int(audit["parquetRows"].sum()),
        "parquetBytes": int(sum(Path(path).stat().st_size for path in audit.loc[audit["exists"], "path"])),
        "scriptHash": sha256(FETCH_SCRIPT), "manifestScriptHash": manifest["script_hash"],
        "scriptHashMatch": sha256(FETCH_SCRIPT) == manifest["script_hash"],
        "planHashMatch": sha256(PLAN) == manifest["plan_hash"], "post2022Consumed": False, "pass": False,
    }
    summary["pass"] = bool(summary["latestOk"] == len(plan) and summary["latestEmpty"] == 0 and summary["latestError"] == 0
        and summary["missingKeys"] == 0 and summary["extraKeys"] == 0 and summary["filesMissing"] == 0
        and summary["rowMismatch"] == 0 and summary["badSchema"] == 0 and summary["outOfBounds"] == 0
        and summary["fileErrors"] == 0 and summary["scriptHashMatch"] and summary["planHashMatch"]
        and plan["date"].max() <= "2022-12-30")
    AUDIT_JSON.write_text(json.dumps(summary, indent=2) + "\n", encoding="ascii")
    print(json.dumps(summary, indent=2))
    if not summary["pass"]:
        raise SystemExit("Fetch audit failed")


if __name__ == "__main__":
    main()
