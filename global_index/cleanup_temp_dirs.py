"""
global_index/cleanup_temp_dirs.py
===================================
Hash-compare temp dirs vs candidate matches before any deletion.

Reports SAFE_TO_DELETE (has identical copy elsewhere in repo) vs UNIQUE
(no matching copy found — DO NOT delete).

NEVER deletes automatically. Always print-only unless --execute is passed,
and even then only SAFE_TO_DELETE files.

Usage:
    cd d:\\raits

    # Dry-run: report only (no deletions)
    python -m global_index.cleanup_temp_dirs

    # Execute: delete only files confirmed SAFE (have identical copy)
    python -m global_index.cleanup_temp_dirs --execute

    # Single temp dir
    python -m global_index.cleanup_temp_dirs --temp-dir data/cache/futures/frozen_temp

Background (analysis from 2026-07-12):
    frozen_temp/        raw files 42-47 MB  — differ from main cache raw (9 MB) → UNIQUE
    frozen_2025_temp/   processed sizes match frozen_2025_sim/; raw may be unique
    global_index/data/frozen_temp/NKD_raw (22.6 MB) ≠ main NKD_raw (5.2 MB) → UNIQUE
    → NOTHING was auto-deleted; this script must confirm before any removal.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path

_CWD = Path.cwd()
if not ((_CWD / "global_index").is_dir() and (_CWD / "futures").is_dir()):
    sys.stderr.write(f"CWD guard FAIL: run from d:\\raits\n"); sys.exit(1)
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("cleanup_temp_dirs")

# Default temp dirs to scan (relative to CWD)
DEFAULT_TEMP_DIRS = [
    Path("data/cache/futures/frozen_temp"),
    Path("data/cache/futures/frozen_2025_temp"),
    Path("global_index/data/frozen_temp"),
]

# Candidate search roots — where we look for copies
CANDIDATE_ROOTS = [
    Path("data/cache/futures"),
    Path("global_index/data"),
]

CHUNK = 1 << 20   # 1 MB read chunks for SHA-256


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024 ** 2:
        return f"{n/1024:.1f} KB"
    elif n < 1024 ** 3:
        return f"{n/1024**2:.1f} MB"
    return f"{n/1024**3:.2f} GB"


def collect_candidates(roots: list[Path], exclude_dirs: list[Path]) -> dict[int, list[Path]]:
    """Walk roots and build size→paths index (excludes files inside temp dirs)."""
    exclude_abs = {d.resolve() for d in exclude_dirs if d.exists()}
    by_size: dict[int, list[Path]] = {}
    for root in roots:
        if not root.exists():
            continue
        for f in root.rglob("*"):
            if not f.is_file():
                continue
            # skip files that live inside temp dirs
            if any(f.resolve().is_relative_to(ex) for ex in exclude_abs):
                continue
            try:
                sz = f.stat().st_size
            except OSError:
                continue
            by_size.setdefault(sz, []).append(f)
    return by_size


def find_identical_copy(path: Path, by_size: dict[int, list[Path]]) -> Path | None:
    """Return first path with same size AND same SHA-256, else None."""
    try:
        sz = path.stat().st_size
    except OSError:
        return None
    candidates = by_size.get(sz, [])
    if not candidates:
        return None
    src_hash = sha256_file(path)
    for cand in candidates:
        try:
            if sha256_file(cand) == src_hash:
                return cand
        except OSError:
            continue
    return None


def scan_temp_dirs(temp_dirs: list[Path], candidate_roots: list[Path]) -> dict:
    """
    For each file in temp_dirs, find if an identical copy exists elsewhere.
    Returns:
        {
            "safe":   [(temp_file, copy_path), ...],  # identical copy found
            "unique": [temp_file, ...],               # no copy — DO NOT DELETE
            "missing_dirs": [dir, ...],               # temp dir doesn't exist
        }
    """
    existing_temp = [d for d in temp_dirs if d.exists()]
    missing_dirs  = [d for d in temp_dirs if not d.exists()]

    if missing_dirs:
        for d in missing_dirs:
            log.info("Temp dir not found (already cleaned?): %s", d)

    log.info("Building candidate index from %d roots ...", len(candidate_roots))
    by_size = collect_candidates(candidate_roots, exclude_dirs=existing_temp)

    total_files = 0
    safe: list[tuple[Path, Path]] = []
    unique: list[Path] = []

    for temp_dir in existing_temp:
        log.info("\nScanning: %s", temp_dir)
        files = sorted(f for f in temp_dir.rglob("*") if f.is_file())
        for f in files:
            total_files += 1
            sz = f.stat().st_size
            log.info("  %-55s  %s", f.relative_to(temp_dir), _fmt_bytes(sz))
            copy = find_identical_copy(f, by_size)
            if copy:
                log.info("    → SAFE (identical copy: %s)", copy)
                safe.append((f, copy))
            else:
                log.info("    → UNIQUE — no copy found; DO NOT DELETE")
                unique.append(f)

    return {
        "safe":         safe,
        "unique":       unique,
        "missing_dirs": missing_dirs,
        "total_files":  total_files,
    }


def print_report(result: dict) -> None:
    safe   = result["safe"]
    unique = result["unique"]
    print()
    print("=" * 72)
    print("CLEANUP TEMP DIRS — REPORT")
    print("=" * 72)
    print(f"\nTotal files scanned: {result['total_files']}")
    print(f"  SAFE TO DELETE:  {len(safe)}")
    print(f"  UNIQUE (keep):   {len(unique)}")

    if unique:
        print("\n── UNIQUE (DO NOT DELETE) ──────────────────────────────────────────")
        for f in unique:
            print(f"  {f}  ({_fmt_bytes(f.stat().st_size)})")
        print("\n  These files have no identical copy anywhere in the search roots.")
        print("  Investigate before removing.")

    if safe:
        print("\n── SAFE TO DELETE (identical copy confirmed) ───────────────────────")
        for f, copy in safe:
            print(f"  {f}  → copy: {copy}")

    if not safe and not unique:
        print("\nNo files found in temp dirs (all dirs empty or missing).")

    print()
    if safe and not unique:
        print("All temp files have confirmed copies. Safe to run with --execute.")
    elif safe and unique:
        print("WARNING: mix of SAFE and UNIQUE files.")
        print("  --execute will only delete SAFE files; UNIQUE files are always preserved.")
    elif not safe:
        print("Nothing to delete (no safe duplicates found).")
    print("=" * 72)


def execute_deletions(safe: list[tuple[Path, Path]]) -> None:
    if not safe:
        print("Nothing to delete.")
        return
    deleted = 0
    errors  = []
    print(f"\nDeleting {len(safe)} confirmed-duplicate file(s) ...")
    for f, copy in safe:
        try:
            f.unlink()
            print(f"  DELETED: {f}")
            deleted += 1
        except OSError as e:
            print(f"  ERROR: {f} — {e}")
            errors.append(f)

    # Remove now-empty temp dirs
    all_temp_parents = {f.parent for f, _ in safe}
    for d in sorted(all_temp_parents, reverse=True):
        try:
            remaining = list(d.iterdir())
            if not remaining:
                d.rmdir()
                print(f"  REMOVED empty dir: {d}")
        except OSError:
            pass

    print(f"\nDone: {deleted} deleted, {len(errors)} errors")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Hash-compare temp dirs vs repo — report SAFE vs UNIQUE before any deletion"
    )
    ap.add_argument(
        "--temp-dir", nargs="*", default=None,
        help="Temp dirs to scan (default: frozen_temp, frozen_2025_temp, global_index/data/frozen_temp)"
    )
    ap.add_argument(
        "--execute", action="store_true",
        help="Delete confirmed-safe files (identical copy found). Never deletes UNIQUE files."
    )
    a = ap.parse_args()

    temp_dirs = [Path(d) for d in a.temp_dir] if a.temp_dir else DEFAULT_TEMP_DIRS

    print("=" * 72)
    print("cleanup_temp_dirs")
    print(f"  mode:      {'EXECUTE (will delete SAFE files)' if a.execute else 'DRY-RUN (report only)'}")
    print(f"  temp dirs: {[str(d) for d in temp_dirs]}")
    print("=" * 72)

    result = scan_temp_dirs(temp_dirs, CANDIDATE_ROOTS)
    print_report(result)

    if a.execute:
        if result["unique"]:
            print(f"\nWARNING: {len(result['unique'])} UNIQUE file(s) will NOT be deleted.")
        if result["safe"]:
            ans = input("\nType YES to proceed with deletion: ").strip()
            if ans != "YES":
                print("Aborted.")
                return
        execute_deletions(result["safe"])
    else:
        if result["safe"]:
            print("\nRe-run with --execute to delete confirmed-safe files.")


if __name__ == "__main__":
    main()
