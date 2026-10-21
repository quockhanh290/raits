from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests


EDGAR = Path("raits/data/cache/external_equity_context/polygon_2018_2024/edgar_index")
CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
CACHE = Path("raits/data/cache/external_events/sec_8k_content_2018_2021")
STAGES = {"discovery": (2018, 2020), "replication": (2021, 2021)}
MAX_BYTES = 30 * 1024 * 1024

PATTERNS = {
    "buyback_authorization": [
        r"(?:authorized|approved|adopted).{0,180}(?:share|stock) repurchase (?:program|plan)",
        r"(?:share|stock) repurchase (?:program|plan).{0,180}(?:authorized|approved|adopted)",
    ],
    "workforce_reduction": [
        r"reduction in (?:its |the )?(?:global )?workforce", r"reduction[- ]in[- ]force",
        r"(?:layoff|lay-off)s? of .{0,80}(?:employees|workers)", r"eliminat(?:e|ing|ion of).{0,80}(?:positions|employees)",
    ],
    "going_concern_distress": [
        r"substantial doubt.{0,240}(?:ability|company).{0,160}continue as a going concern",
        r"ability to continue as a going concern.{0,240}substantial doubt",
    ],
    "financial_restatement": [
        r"(?:financial statements|financial results).{0,180}should no longer be relied upon",
        r"non-reliance on previously issued financial statements", r"will restate.{0,180}financial statements",
    ],
    "cyber_incident": [
        r"cybersecurity incident", r"cyber incident", r"ransomware (?:attack|incident)",
        r"(?:material )?data breach", r"unauthorized access.{0,120}(?:systems|network|data)",
    ],
    "strategic_alternatives": [
        r"(?:review|explor(?:e|ing)|evaluate|consider).{0,180}strategic alternatives",
        r"strategic alternatives.{0,180}(?:review|process|explor(?:e|ing)|evaluate|consider)",
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def build_plan(stage: str) -> pd.DataFrame:
    first_year, last_year = STAGES[stage]
    files = [path for path in sorted(EDGAR.glob("*.parquet")) if first_year <= int(path.stem[-7:-3]) <= last_year]
    rows = pd.concat([
        pd.read_parquet(path, columns=["cik", "form_type", "filing_date", "filing_url", "accession_number", "ticker"])
        for path in files
    ], ignore_index=True).drop_duplicates()
    rows["filing_date"] = pd.to_datetime(rows["filing_date"]).dt.normalize()
    rows["ticker"] = rows["ticker"].astype("string").str.upper()
    rows = rows[rows["form_type"].eq("8-K") & rows["ticker"].notna()].copy()

    caps = pd.read_csv(CAPS, low_memory=False)
    caps["snapshot_date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["snapshot_date", "market_cap", "ticker"], ascending=[True, False, True])
    caps["rank"] = caps.groupby("snapshot_date").cumcount() + 1
    members = caps[caps["rank"].le(500)][["snapshot_date", "ticker"]]
    dates = pd.DataFrame({"filing_date": sorted(rows["filing_date"].unique())})
    assigned = pd.merge_asof(
        dates, members[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date"),
        left_on="filing_date", right_on="snapshot_date", direction="backward",
    )
    plan = rows.merge(assigned, on="filing_date", how="inner").merge(
        members, on=["snapshot_date", "ticker"], how="inner"
    )
    plan = plan.sort_values(["filing_date", "accession_number", "ticker"])
    plan = plan.drop_duplicates("accession_number", keep="first").reset_index(drop=True)
    plan["stage"] = stage
    plan["cache_path"] = plan.apply(
        lambda row: str(CACHE / "raw" / str(row.filing_date.year) / f"{row.accession_number}.txt.gz").replace("\\", "/"), axis=1
    )
    return plan


class RateLimiter:
    def __init__(self, interval: float):
        self.interval = interval
        self.lock = threading.Lock()
        self.next_time = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_time - now)
            self.next_time = max(now, self.next_time) + self.interval
        if delay:
            time.sleep(delay)


def fetch_one(row: dict[str, object], limiter: RateLimiter, user_agent: str, retries: int) -> dict[str, object]:
    path = Path(str(row["cache_path"]))
    base = {"accession_number": row["accession_number"], "cache_path": str(path).replace("\\", "/")}
    if path.exists() and path.stat().st_size > 0:
        return {**base, "status": "SKIP", "http_status": 200, "bytes": path.stat().st_size, "error": ""}
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            limiter.wait()
            response = requests.get(
                str(row["filing_url"]),
                headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Host": "www.sec.gov"},
                timeout=120,
            )
            if response.status_code in {429, 403}:
                time.sleep(min(30.0, attempt * 3.0)); continue
            response.raise_for_status()
            content = response.content
            if len(content) > MAX_BYTES:
                raise RuntimeError(f"submission exceeds {MAX_BYTES} bytes")
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
            with gzip.open(temp, "wb", compresslevel=6) as handle:
                handle.write(content)
            temp.replace(path)
            return {**base, "status": "OK", "http_status": response.status_code, "bytes": path.stat().st_size, "error": ""}
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            time.sleep(min(10.0, attempt * 1.5))
    return {**base, "status": "ERROR", "http_status": None, "bytes": 0, "error": last_error}


def classify(plan: pd.DataFrame) -> pd.DataFrame:
    compiled = {name: [re.compile(pattern, re.I | re.S) for pattern in patterns] for name, patterns in PATTERNS.items()}
    output = []
    for row in plan.itertuples(index=False):
        path = Path(row.cache_path)
        if not path.exists() or path.stat().st_size == 0:
            continue
        with gzip.open(path, "rb") as handle:
            raw = handle.read().decode("utf-8", errors="replace")
        normalized = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).lower()
        acceptance = re.search(r"<ACCEPTANCE-DATETIME>\s*(\d{14})", raw, re.I)
        flags = {name: any(pattern.search(normalized) for pattern in patterns) for name, patterns in compiled.items()}
        output.append({
            "stage": row.stage, "cik": str(row.cik).zfill(10), "ticker": row.ticker,
            "filing_date": row.filing_date, "accession_number": row.accession_number,
            "filing_url": row.filing_url,
            "acceptance_datetime": acceptance.group(1) if acceptance else "",
            "text_chars": len(normalized), **flags,
        })
    return pd.DataFrame(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable SEC 8-K content fetch for frozen PIT top500 accessions.")
    parser.add_argument("--stage", choices=sorted(STAGES), default="discovery")
    parser.add_argument("--max-files", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--requests-per-second", type=float, default=6.0)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--classify-only", action="store_true")
    args = parser.parse_args()
    if args.requests_per_second <= 0 or args.requests_per_second > 8:
        raise SystemExit("requests-per-second must be in (0, 8]")

    CACHE.mkdir(parents=True, exist_ok=True)
    plan = build_plan(args.stage)
    plan_path = CACHE / f"plan_{args.stage}.csv"
    plan.to_csv(plan_path, index=False)
    print(f"PLAN stage={args.stage} accessions={len(plan)} years={STAGES[args.stage]}", flush=True)
    if args.dry_run:
        return

    pending = plan[~plan["cache_path"].map(lambda value: Path(value).exists())].copy()
    if args.classify_only:
        pending = pending.iloc[0:0].copy()
    if args.max_files:
        pending = pending.head(args.max_files)
    limiter = RateLimiter(1.0 / args.requests_per_second)
    user_agent = os.environ.get("SEC_USER_AGENT", "Raits Equity Research research@raits.local").strip()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(fetch_one, row, limiter, user_agent, args.retries) for row in pending.to_dict("records")]
        for index, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if index % 250 == 0:
                print(f"FETCH {index}/{len(futures)} errors={sum(row['status']=='ERROR' for row in rows)}", flush=True)
    status_path = CACHE / f"status_{args.stage}.csv"
    prior = pd.read_csv(status_path) if status_path.exists() else pd.DataFrame()
    status = pd.concat([prior, pd.DataFrame(rows)], ignore_index=True)
    if not status.empty:
        status = status.drop_duplicates("accession_number", keep="last").sort_values("accession_number")
    status.to_csv(status_path, index=False)
    if args.fetch_only:
        fetched = int(plan["cache_path"].map(lambda value: Path(value).exists()).sum())
        print(json.dumps({"stage": args.stage, "planned": len(plan), "fetched": fetched,
                          "remaining": len(plan) - fetched, "fetchOnly": True}, indent=2), flush=True)
        return

    labels_path = CACHE / f"labels_{args.stage}.csv"
    fetched = int(plan["cache_path"].map(lambda value: Path(value).exists()).sum())
    explicit_failures = int(status["status"].eq("ERROR").sum()) if not status.empty else 0
    unresolved = max(0, len(plan) - fetched - explicit_failures)
    labels = classify(plan) if unresolved == 0 else pd.DataFrame()
    if unresolved == 0:
        labels.to_csv(labels_path, index=False)
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "stage": args.stage, "years": list(STAGES[args.stage]), "plannedAccessions": len(plan),
        "fetchedAccessions": fetched, "explicitFailures": explicit_failures,
        "unresolvedAccessions": unresolved, "complete": unresolved == 0,
        "labelRows": len(labels), "classCounts": {name: int(labels.get(name, pd.Series(dtype=bool)).sum()) for name in PATTERNS},
        "fairAccess": {"workers": args.workers, "requestsPerSecond": args.requests_per_second, "userAgent": user_agent},
        "maxSubmissionBytes": MAX_BYTES, "post2021Consumed": False,
        "plan": str(plan_path).replace("\\", "/"),
        "labels": str(labels_path).replace("\\", "/") if unresolved == 0 else None,
    }
    (CACHE / f"manifest_{args.stage}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
