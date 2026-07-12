"""
global_index/verify_frozen.py — Frozen parquet manifest + integrity verify
==========================================================================
Bảo vệ ground-truth data trước khi live update bắt đầu.

Bài học: futures thiếu backup frozen → baseline $52,936 không tái tạo → KHÔNG lặp.

Frozen parquets = sealed snapshot. Provider revise sau → không fetch lại được.
Manifest (SHA-256) commit vào git → verify bất cứ lúc nào.

Modes:
  create   — hash tất cả frozen files, ghi manifest JSON (chạy 1 lần khi freeze)
  verify   — kiểm tra current files khớp manifest (chạy trước mỗi major update)
  backup   — in robocopy command để copy toàn bộ sang ổ ngoài / cloud
  status   — tóm tắt file inventory (không cần manifest)

Usage:
    cd d:\\raits
    python -m global_index.verify_frozen create
    python -m global_index.verify_frozen verify
    python -m global_index.verify_frozen backup --dest "E:\\raits_backup\\frozen"
    python -m global_index.verify_frozen status
"""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_CWD = Path.cwd()
if not ((_CWD / "global_index").is_dir() and (_CWD / "futures").is_dir()):
    sys.stderr.write(f"CWD guard FAIL: run from d:\\raits (got {_CWD})\n")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("verify_frozen")

MANIFEST_PATH = Path("data/frozen_manifest.json")

# ── Canonical frozen file inventory ──────────────────────────────────────────
# role: "baseline" = used in IS baseline / vault 2024
#        "vault2025" = used in vault 2025 OOS
#        "sim" = shim copy for deploy_sim (derived from above, rebuildable)
FROZEN_FILES = [
    # ── Primary frozen (source-of-truth, IRREPLACEABLE) ─────────────────────
    dict(path="data/cache/futures/ES_frozen_2024.parquet",
         role="baseline", note="ES through 2024-12-31; vault 2023-24 source"),
    dict(path="data/cache/futures/NQ_frozen_2024.parquet",
         role="baseline", note="NQ through 2024-12-31"),
    dict(path="data/cache/futures/YM_frozen_2024.parquet",
         role="baseline", note="YM through 2024-12-31"),
    dict(path="data/cache/futures/RTY_frozen_2024.parquet",
         role="baseline", note="RTY through 2024-12-31"),
    dict(path="global_index/data/NKD_frozen_2024.parquet",
         role="baseline", note="NKD through 2024-12-31"),

    dict(path="data/cache/futures/ES_frozen_2025.parquet",
         role="vault2025", note="ES through 2025-12-31; vault 2025 source"),
    dict(path="data/cache/futures/NQ_frozen_2025.parquet",
         role="vault2025", note="NQ through 2025-12-31"),
    dict(path="data/cache/futures/YM_frozen_2025.parquet",
         role="vault2025", note="YM through 2025-12-31"),
    dict(path="data/cache/futures/RTY_frozen_2025.parquet",
         role="vault2025", note="RTY through 2025-12-31"),
    dict(path="global_index/data/NKD_frozen_2025.parquet",
         role="vault2025", note="NKD through 2025-12-31"),
    dict(path="global_index/data/NKD_frozen_2025_clipped.parquet",
         role="vault2025", note="NKD clipped variant (no final-day partial)"),

    # ── Shim dirs (deploy_sim uses *_8y.parquet filename) ────────────────────
    # Derived from primary frozen — rebuildable via refreeze. Still checksum.
    dict(path="data/cache/futures/frozen_sim/ES_continuous_1m_8y.parquet",
         role="sim-baseline", note="shim for deploy_sim baseline (copy of ES_frozen_2024)"),
    dict(path="data/cache/futures/frozen_sim/NQ_continuous_1m_8y.parquet",
         role="sim-baseline", note="shim for deploy_sim baseline"),
    dict(path="data/cache/futures/frozen_sim/YM_continuous_1m_8y.parquet",
         role="sim-baseline", note="shim for deploy_sim baseline"),
    dict(path="data/cache/futures/frozen_sim/RTY_continuous_1m_8y.parquet",
         role="sim-baseline", note="shim for deploy_sim baseline"),

    dict(path="data/cache/futures/frozen_2025_sim/ES_continuous_1m_8y.parquet",
         role="sim-vault2025", note="shim for deploy_sim vault 2025"),
    dict(path="data/cache/futures/frozen_2025_sim/NQ_continuous_1m_8y.parquet",
         role="sim-vault2025", note="shim for deploy_sim vault 2025"),
    dict(path="data/cache/futures/frozen_2025_sim/YM_continuous_1m_8y.parquet",
         role="sim-vault2025", note="shim for deploy_sim vault 2025"),
    dict(path="data/cache/futures/frozen_2025_sim/RTY_continuous_1m_8y.parquet",
         role="sim-vault2025", note="shim for deploy_sim vault 2025"),

    dict(path="data/cache/futures/frozen_2025_clipped_sim/ES_continuous_1m_8y.parquet",
         role="sim-vault2025-clipped", note="shim for vault 2025 clipped variant"),
    dict(path="data/cache/futures/frozen_2025_clipped_sim/NQ_continuous_1m_8y.parquet",
         role="sim-vault2025-clipped", note="shim for vault 2025 clipped variant"),
    dict(path="data/cache/futures/frozen_2025_clipped_sim/YM_continuous_1m_8y.parquet",
         role="sim-vault2025-clipped", note="shim for vault 2025 clipped variant"),
    dict(path="data/cache/futures/frozen_2025_clipped_sim/RTY_continuous_1m_8y.parquet",
         role="sim-vault2025-clipped", note="shim for vault 2025 clipped variant"),
]

# Primary-only (no shims) — most critical to protect externally
PRIMARY_ROLES = {"baseline", "vault2025"}


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


# ── create ────────────────────────────────────────────────────────────────────

def cmd_create(args) -> int:
    print(f"Creating manifest → {MANIFEST_PATH}")
    print(f"Hashing {len(FROZEN_FILES)} files (SHA-256) ...\n")

    entries = {}
    missing = []
    total_bytes = 0

    for spec in FROZEN_FILES:
        p = Path(spec["path"])
        if not p.exists():
            log.warning("  MISSING  %s", p)
            missing.append(str(p))
            continue
        sz = p.stat().st_size
        total_bytes += sz
        print(f"  hashing  {p.name:<45}  {_mb(sz)}", end="", flush=True)
        digest = _sha256(p)
        entries[spec["path"]] = {
            "sha256":     digest,
            "size_bytes": sz,
            "role":       spec["role"],
            "note":       spec["note"],
        }
        print(f"  {digest[:12]}...")

    manifest = {
        "created_utc":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count":   len(entries),
        "total_mb":     round(total_bytes / 1_048_576, 1),
        "missing":      missing,
        "files":        entries,
    }

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest written: {MANIFEST_PATH}")
    print(f"  {len(entries)} files  |  {_mb(total_bytes)} total")
    if missing:
        print(f"  WARNING: {len(missing)} file(s) missing — see manifest.missing[]")
    print(f"\nNext: commit {MANIFEST_PATH} to git (hashes only, not the parquets)")
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"  git add {MANIFEST_PATH} && git commit -m \"data: frozen manifest {date_str}\"")
    return 1 if missing else 0


# ── verify ────────────────────────────────────────────────────────────────────

def cmd_verify(args) -> int:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found: {MANIFEST_PATH}")
        print(f"  Run first: python -m global_index.verify_frozen create")
        return 2

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    print(f"Manifest: {MANIFEST_PATH}  (created {manifest.get('created_utc', '?')})")
    print(f"Verifying {manifest['file_count']} files ...\n")

    ok = bad = missing = 0
    primary_bad = []

    for rel_path, meta in manifest["files"].items():
        p = Path(rel_path)
        role = meta.get("role", "?")
        if not p.exists():
            log.error("  MISSING   %-45s  [%s]", rel_path, role)
            missing += 1
            if role in PRIMARY_ROLES:
                primary_bad.append(f"MISSING: {rel_path}")
            continue

        sz = p.stat().st_size
        if sz != meta["size_bytes"]:
            log.error("  SIZE_DIFF %-45s  expected=%d actual=%d  [%s]",
                      rel_path, meta["size_bytes"], sz, role)
            bad += 1
            if role in PRIMARY_ROLES:
                primary_bad.append(f"SIZE_DIFF: {rel_path}")
            continue

        digest = _sha256(p)
        if digest != meta["sha256"]:
            log.error("  HASH_FAIL %-45s  [%s]", rel_path, role)
            log.error("            expected: %s", meta["sha256"])
            log.error("            actual:   %s", digest)
            bad += 1
            if role in PRIMARY_ROLES:
                primary_bad.append(f"HASH_FAIL: {rel_path}")
        else:
            log.info("  OK        %-45s  %s  [%s]", rel_path, _mb(sz), role)
            ok += 1

    print(f"\nResult: {ok} OK  |  {bad} FAIL  |  {missing} MISSING")

    if primary_bad:
        print(f"\n{'!'*60}")
        print(f"CRITICAL: {len(primary_bad)} PRIMARY frozen file(s) compromised:")
        for s in primary_bad:
            print(f"  {s}")
        print(f"{'!'*60}")
        print("→ STOP. Do NOT run any updates. Restore from external backup first.")
        return 2

    if bad or missing:
        print("→ Shim files may be stale — run refreeze to rebuild if needed.")
        return 1

    print("→ All frozen files intact. Safe to proceed.")
    return 0


# ── backup ────────────────────────────────────────────────────────────────────

def cmd_backup(args) -> int:
    dest = Path(args.dest) if args.dest else None
    if dest is None:
        print("ERROR: --dest required  (e.g. --dest 'E:\\raits_backup\\frozen')")
        return 2

    primary = [spec for spec in FROZEN_FILES if spec["role"] in PRIMARY_ROLES]
    dirs_to_backup = set()
    for spec in primary:
        dirs_to_backup.add(Path(spec["path"]).parent)

    print(f"Backup target: {dest}")
    print(f"Primary frozen files: {len(primary)}")
    print()

    if args.dry_run:
        print("[dry-run] Files that WOULD be backed up:")
        for spec in primary:
            p = Path(spec["path"])
            exists = "✓" if p.exists() else "MISSING"
            print(f"  {exists}  {spec['path']}  [{spec['role']}]")
        print()

    # Windows robocopy commands (one per source dir)
    print("Robocopy commands (run in PowerShell/cmd from d:\\raits):")
    for src_dir in sorted(dirs_to_backup):
        frozen_pattern = " ".join(
            f'"{Path(s["path"]).name}"'
            for s in primary
            if Path(s["path"]).parent == src_dir
        )
        dst_dir = dest / src_dir
        print(f'  robocopy "{src_dir}" "{dst_dir}" {frozen_pattern} /COPYALL /LOG+:backup_frozen.log')

    # Also backup manifest + SPY
    print(f'  robocopy "data" "{dest / "data"}" "frozen_manifest.json" /COPYALL')
    print(f'  robocopy "." "{dest}" "spy_daily.csv" "spy_daily_live.csv" /COPYALL')
    print(f'  robocopy "spy_snapshots" "{dest / "spy_snapshots"}" *.csv /COPYALL')

    if not args.dry_run:
        print("\nRun the commands above manually (or add --execute to auto-run).")

    if args.execute and not args.dry_run:
        import subprocess
        print("\nExecuting robocopy commands ...")
        for src_dir in sorted(dirs_to_backup):
            names = [Path(s["path"]).name for s in primary
                     if Path(s["path"]).parent == src_dir]
            dst_dir = dest / src_dir
            dst_dir.mkdir(parents=True, exist_ok=True)
            cmd = ["robocopy", str(src_dir), str(dst_dir)] + names + ["/COPYALL"]
            result = subprocess.run(cmd)
            # robocopy exit code 1 = files copied OK (not an error)
            if result.returncode > 1:
                log.error("robocopy failed (exit=%d) for %s", result.returncode, src_dir)

    return 0


# ── status ────────────────────────────────────────────────────────────────────

def cmd_status(args) -> int:
    print("Frozen file inventory (current state on disk):\n")
    total = 0
    for spec in FROZEN_FILES:
        p = Path(spec["path"])
        if p.exists():
            sz = p.stat().st_size
            total += sz
            mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"  ✓  {spec['role']:<20}  {_mb(sz):>9}  {mtime}  {p.name}")
        else:
            print(f"  ✗  {spec['role']:<20}  {'MISSING':>9}             {spec['path']}")
    print(f"\n  Total: {_mb(total)} across {len(FROZEN_FILES)} entries")

    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            m = json.load(f)
        print(f"\n  Manifest: {MANIFEST_PATH} (created {m.get('created_utc','?')})")
        print(f"  Run 'verify' to check integrity against manifest.")
    else:
        print(f"\n  No manifest found. Run 'create' to generate checksums.")

    # Flag temp dirs
    temp_dirs = [
        "data/cache/futures/frozen_temp",
        "data/cache/futures/frozen_2025_temp",
        "global_index/data/frozen_temp",
    ]
    found_temps = [d for d in temp_dirs if Path(d).exists()]
    if found_temps:
        print(f"\n  NOTE: temp dirs found (leftover from freeze process):")
        for d in found_temps:
            files = list(Path(d).glob("*.parquet"))
            sz = sum(f.stat().st_size for f in files)
            print(f"    {d}/  ({len(files)} files, {_mb(sz)}) — safe to delete after backup")

    return 0


# ── quick_check (fast startup guard — size + mtime, no SHA-256) ──────────────

def quick_check_manifest(manifest_path: Path = MANIFEST_PATH,
                          roles: set | None = None) -> tuple[bool, list[str]]:
    """Fast integrity check: verify file sizes match manifest.
    Uses size only (no SHA-256 — completes in <0.1s for startup use).

    Returns: (all_ok: bool, issues: list[str])

    SHA-256 catches byte-level corruption; size check catches:
      - File deleted / replaced with different file
      - File truncated
      - Accidental overwrite (almost always changes size)
    For full SHA-256 verification: python -m global_index.verify_frozen verify

    Args:
        roles: if set, only check files with matching role (default: PRIMARY_ROLES)
    """
    if roles is None:
        roles = PRIMARY_ROLES

    if not manifest_path.exists():
        return False, [
            f"MANIFEST NOT FOUND: {manifest_path}",
            "  → Run: python -m global_index.verify_frozen create",
            "  (frozen files are UNVERIFIED this session — not the same as verified OK)",
        ]

    with open(manifest_path) as f:
        manifest = json.load(f)

    issues = []
    for rel_path, meta in manifest["files"].items():
        if meta.get("role") not in roles:
            continue
        p = Path(rel_path)
        if not p.exists():
            issues.append(f"MISSING: {rel_path}")
        elif p.stat().st_size != meta["size_bytes"]:
            issues.append(
                f"SIZE_MISMATCH: {rel_path} "
                f"(expected {meta['size_bytes']}, got {p.stat().st_size})"
            )

    return len(issues) == 0, issues


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Frozen parquet manifest + integrity check")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("create",  help="Hash all frozen files → write manifest")
    sub.add_parser("verify",  help="Check files against manifest")
    sub.add_parser("status",  help="List frozen files on disk (no manifest needed)")

    bp = sub.add_parser("backup", help="Print/execute robocopy backup commands")
    bp.add_argument("--dest",    required=False, help="Backup destination path")
    bp.add_argument("--dry-run", action="store_true", help="List files only")
    bp.add_argument("--execute", action="store_true", help="Actually run robocopy")

    args = ap.parse_args()

    if args.cmd == "create":
        sys.exit(cmd_create(args))
    elif args.cmd == "verify":
        sys.exit(cmd_verify(args))
    elif args.cmd == "backup":
        sys.exit(cmd_backup(args))
    elif args.cmd == "status":
        sys.exit(cmd_status(args))


if __name__ == "__main__":
    main()
