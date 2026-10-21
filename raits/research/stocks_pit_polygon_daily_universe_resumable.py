from __future__ import annotations

import argparse
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


BUILDER_PATH = Path(__file__).with_name("stocks_pit_polygon_bulk_universe_builder.py")
REPORT_PREFIX = "STOCKS_PIT_POLYGON_BULK_UNIVERSE_20260912"


def load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("stocks_pit_polygon_bulk_universe_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Unable to load builder from {BUILDER_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def safe_tag(tag: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in tag)


def out_dir(builder: Any, tag: str) -> Path:
    return builder.ROOT_DIR / "polygon_universe_bulk" / safe_tag(tag)


def status_path(run_dir: Path) -> Path:
    return run_dir / "resumable_status.csv"


def load_status(run_dir: Path) -> pd.DataFrame:
    path = status_path(run_dir)
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "date",
                "status",
                "rows",
                "pages",
                "elapsed_sec",
                "attempts",
                "updated_at_utc",
                "error",
            ]
        )
    return pd.read_csv(path, dtype={"date": str, "status": str, "error": str})


def write_status(run_dir: Path, status: pd.DataFrame) -> None:
    status = status.sort_values("date").reset_index(drop=True)
    status.to_csv(status_path(run_dir), index=False)


def upsert_status(run_dir: Path, row: dict[str, object]) -> None:
    status = load_status(run_dir)
    date_s = str(row["date"])
    old_attempts = 0
    if not status.empty and date_s in set(status["date"].astype(str)):
        existing = status[status["date"].astype(str).eq(date_s)].iloc[-1]
        old_attempts = int(existing.get("attempts", 0) or 0)
        status = status[~status["date"].astype(str).eq(date_s)].copy()
    row["attempts"] = old_attempts + 1
    row["updated_at_utc"] = pd.Timestamp.utcnow().isoformat()
    status = pd.concat([status, pd.DataFrame([row])], ignore_index=True)
    write_status(run_dir, status)


def selected_dates(builder: Any, args: argparse.Namespace) -> list[pd.Timestamp]:
    dates = builder.date_schedule(args.start, args.end, "daily", allow_oos=args.allow_oos)
    if args.max_dates > 0:
        dates = dates[: args.max_dates]
    if not dates:
        raise SystemExit("No dates selected")
    return dates


def raw_paths(run_dir: Path, date: pd.Timestamp) -> tuple[Path, Path]:
    date_s = date.date().isoformat()
    return run_dir / "raw_snapshots" / f"{date_s}.parquet", run_dir / "page_manifests" / f"{date_s}.parquet"


def date_is_complete(run_dir: Path, date: pd.Timestamp) -> bool:
    raw_path, page_path = raw_paths(run_dir, date)
    if not raw_path.exists() or not page_path.exists():
        return False
    try:
        pages = pd.read_parquet(page_path)
    except Exception:
        return False
    if pages.empty:
        return False
    return not bool(pages.iloc[-1].get("next_url_present", True))


def fetch_dates(builder: Any, args: argparse.Namespace) -> None:
    dates = selected_dates(builder, args)
    run_dir = out_dir(builder, args.tag)
    run_dir.mkdir(parents=True, exist_ok=True)
    status = load_status(run_dir)
    ok_dates = set(status.loc[status["status"].eq("OK"), "date"].astype(str)) if not status.empty else set()
    key = builder.load_polygon_key()

    total = len(dates)
    done = 0
    with requests.Session() as session:
        for idx, date in enumerate(dates, start=1):
            date_s = date.date().isoformat()
            if not args.force and date_s in ok_dates and date_is_complete(run_dir, date):
                done += 1
                if done % max(args.progress_every, 1) == 0:
                    print(f"SKIP {done}/{total} {date_s}", flush=True)
                continue
            start = time.monotonic()
            try:
                rows, pages = builder.load_or_fetch_snapshot(session, key, run_dir, date, args.force)
                elapsed = time.monotonic() - start
                complete = not pages.empty and not bool(pages.iloc[-1].get("next_url_present", True))
                status_value = "OK" if complete else "INCOMPLETE"
                upsert_status(
                    run_dir,
                    {
                        "date": date_s,
                        "status": status_value,
                        "rows": int(len(rows)),
                        "pages": int(len(pages)),
                        "elapsed_sec": round(elapsed, 3),
                        "error": "",
                    },
                )
                print(f"{idx}/{total} {date_s} {status_value} rows={len(rows)} pages={len(pages)}", flush=True)
            except Exception as exc:  # keep the resumable ledger even when one date fails
                elapsed = time.monotonic() - start
                upsert_status(
                    run_dir,
                    {
                        "date": date_s,
                        "status": "ERROR",
                        "rows": 0,
                        "pages": 0,
                        "elapsed_sec": round(elapsed, 3),
                        "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                    },
                )
                print(f"{idx}/{total} {date_s} ERROR {type(exc).__name__}", flush=True)
                if not args.keep_going:
                    raise

    status = load_status(run_dir)
    ok = int(status["status"].eq("OK").sum())
    errors = int(status["status"].eq("ERROR").sum())
    incomplete = int(status["status"].eq("INCOMPLETE").sum())
    print(f"FETCH_STATUS tag={args.tag} ok={ok} incomplete={incomplete} errors={errors} target_dates={total}")


def assemble(builder: Any, args: argparse.Namespace) -> None:
    dates = selected_dates(builder, args)
    run_dir = out_dir(builder, args.tag)
    missing = [d.date().isoformat() for d in dates if not date_is_complete(run_dir, d)]
    if missing:
        sample = ", ".join(missing[:10])
        raise SystemExit(f"Cannot assemble; missing/incomplete dates={len(missing)} sample={sample}")

    raw_frames = []
    page_frames = []
    for date in dates:
        raw_path, page_path = raw_paths(run_dir, date)
        raw = pd.read_parquet(raw_path)
        pages = pd.read_parquet(page_path)
        raw["date"] = pd.to_datetime(raw["date"])
        raw_frames.append(raw)
        page_frames.append(pages)
    raw_all = pd.concat(raw_frames, ignore_index=True)
    pages_all = pd.concat(page_frames, ignore_index=True)

    key = builder.load_polygon_key()
    with requests.Session() as session:
        evidence = builder.load_or_fetch_event_evidence(session, key, run_dir, raw_all)
    if not evidence.empty:
        evidence["date"] = pd.to_datetime(evidence["date"])

    resolved, resolutions = builder.resolve_snapshot(raw_all, evidence)
    name_flags = builder.possible_non_common_by_name(resolved)
    exclusion_summary = builder.instrument_exclusion_summary(resolved)
    qa_summary, daily_counts = builder.qa(raw_all, resolved, pages_all, resolutions, name_flags)

    paths = {
        "raw_universe_snapshot": str((run_dir / "raw_universe_snapshot.parquet")).replace("\\", "/"),
        "page_manifest": str((run_dir / "page_manifest.parquet")).replace("\\", "/"),
        "daily_universe": str((run_dir / "daily_universe.parquet")).replace("\\", "/"),
        "duplicate_identity_resolutions": str((run_dir / "duplicate_identity_resolutions.parquet")).replace("\\", "/"),
        "duplicate_identity_event_evidence": str((run_dir / "duplicate_identity_event_evidence.parquet")).replace("\\", "/"),
        "daily_counts": str((run_dir / "daily_counts.parquet")).replace("\\", "/"),
        "possible_non_common_name_flags": str((run_dir / "possible_non_common_name_flags.parquet")).replace("\\", "/"),
        "instrument_exclusion_summary": str((run_dir / "instrument_exclusion_summary.parquet")).replace("\\", "/"),
        "resumable_status": str(status_path(run_dir)).replace("\\", "/"),
    }
    raw_all.to_parquet(run_dir / "raw_universe_snapshot.parquet", index=False)
    pages_all.to_parquet(run_dir / "page_manifest.parquet", index=False)
    resolved.to_parquet(run_dir / "daily_universe.parquet", index=False)
    resolutions.to_parquet(run_dir / "duplicate_identity_resolutions.parquet", index=False)
    evidence.to_parquet(run_dir / "duplicate_identity_event_evidence.parquet", index=False)
    daily_counts.to_parquet(run_dir / "daily_counts.parquet", index=False)
    name_flags.to_parquet(run_dir / "possible_non_common_name_flags.parquet", index=False)
    exclusion_summary.to_parquet(run_dir / "instrument_exclusion_summary.parquet", index=False)

    suffix = args.tag.upper().replace("-", "")
    resolved.to_csv(f"{REPORT_PREFIX}_{suffix}_DAILY_UNIVERSE.csv", index=False)
    resolutions.to_csv(f"{REPORT_PREFIX}_{suffix}_DUPLICATE_RESOLUTIONS.csv", index=False)
    evidence.to_csv(f"{REPORT_PREFIX}_{suffix}_EVENT_EVIDENCE.csv", index=False)
    daily_counts.to_csv(f"{REPORT_PREFIX}_{suffix}_DAILY_COUNTS.csv", index=False)
    name_flags.to_csv(f"{REPORT_PREFIX}_{suffix}_POSSIBLE_NON_COMMON_NAME_FLAGS.csv", index=False)
    exclusion_summary.to_csv(f"{REPORT_PREFIX}_{suffix}_INSTRUMENT_EXCLUSION_SUMMARY.csv", index=False)
    qa_summary.to_csv(f"{REPORT_PREFIX}_{suffix}_QA_SUMMARY.csv", index=False)

    manifest = {
        "created_at_utc": pd.Timestamp.utcnow().isoformat(),
        "source": "Polygon /v3/reference/tickers active CS snapshots",
        "purpose": "resumable daily PIT active common-stock universe snapshots with identity resolution",
        "start": args.start,
        "end": args.end,
        "frequency": "daily",
        "dates": [d.date().isoformat() for d in dates],
        "page_limit": builder.PAGE_LIMIT,
        "opened_2025_2026_oos": bool(args.allow_oos and pd.Timestamp(args.end) > pd.Timestamp("2024-12-31")),
        "resumable": True,
        "paths": paths,
    }
    (run_dir / "manifest_20260912.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(qa_summary.to_string(index=False))
    print(exclusion_summary.to_string(index=False))
    print(daily_counts.describe(include="all").to_string())
    print("ASSEMBLED", run_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resumable daily PIT Polygon universe builder.")
    parser.add_argument("--mode", choices=["fetch", "assemble", "fetch-assemble"], default="fetch")
    parser.add_argument("--start", default="2018-01-02")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--tag", default="daily_20180102_20241231_resumable")
    parser.add_argument("--max-dates", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--allow-oos", action="store_true", help="Required to access dates after 2024-12-31.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if pd.Timestamp(args.end) > pd.Timestamp("2024-12-31") and not args.allow_oos:
        raise SystemExit("Refusing to open 2025-2026 OOS; end must be <= 2024-12-31")
    builder = load_builder()
    if args.mode in {"fetch", "fetch-assemble"}:
        fetch_dates(builder, args)
    if args.mode in {"assemble", "fetch-assemble"}:
        assemble(builder, args)


if __name__ == "__main__":
    main()
