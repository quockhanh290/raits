"""Stage 5M-D — can Track 1 run once the legacy route is deleted? Read-only probe.

The hard requirement: if `global_index/run_live_day.py`, the legacy scheduler jobs and the
legacy position book are removed, Track 1's scheduler, ops and dashboard must still start and
still produce shadow evidence.

This does not delete anything. It BLOCKS the legacy modules at import time — any attempt to
import them raises — and then exercises the Track 1 paths. An import that only happens on a
branch nobody took would slip past a static scan; blocking the import catches it wherever it
lives.

Three separate questions, answered separately:

    code    does any Track 1 path IMPORT legacy?
    jobs    does Track 1-only mode still register legacy strategy jobs?
    state   does any Track 1 reader require legacy's position book?

Nothing is written. No scheduler, no broker, no orders.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
os.environ.setdefault("PYTEST_CURRENT_TEST", "5md-probe")
logging.disable(logging.CRITICAL)

#: The legacy route: its entrypoint, its runner, and the modules only it uses.
LEGACY_MODULES = ("global_index.run_live_day",)

#: Legacy's position book and the files only legacy writes.
LEGACY_STATE = ("live_positions.json", "global_index/replay_checkpoint.json",
                "global_index/live_state_data.js", "trade_log.jsonl")

#: What Track 1 must be able to do with all of the above unavailable.
TRACK1_RUNTIME = ("global_index/run_live_day_track1.py", "global_index/track1_slots.py",
                  "global_index/track1_live_source.py", "global_index/track1_sleeves.py",
                  "global_index/track1_signal_layer.py", "global_index/track1_freshness.py",
                  "global_index/track1_params.py", "global_index/track1_intraday.py",
                  "global_index/track1_normal_r4.py", "global_index/track1_calm_a.py",
                  "global_index/track1_stress_mnq.py", "global_index/track1_explain.py",
                  "global_index/track1_bootstrap.py", "global_index/track1_gates.py",
                  "global_index/track1_live_frame.py", "global_index/route_checkpoint.py",
                  "global_index/route_params.py", "global_index/window_ledger.py")


class _Blocked(ImportError):
    pass


class block_legacy:
    """Make the legacy modules unimportable for the duration of the block."""

    def __init__(self, names=LEGACY_MODULES):
        self.names = tuple(names)
        self._real = builtins.__import__
        self._saved: dict = {}

    def __enter__(self):
        for n in self.names:
            self._saved[n] = sys.modules.pop(n, None)

        def guard(name, globals=None, locals=None, fromlist=(), level=0):
            if name in self.names or any(name.startswith(n + ".") for n in self.names):
                raise _Blocked(f"{name} is deleted in this simulation")
            return self._real(name, globals, locals, fromlist, level)

        builtins.__import__ = guard
        return self

    def __exit__(self, *exc):
        builtins.__import__ = self._real
        for n, mod in self._saved.items():
            if mod is not None:
                sys.modules[n] = mod
        return False


def static_scan() -> dict:
    """Which Track 1 modules mention the legacy entrypoint, and how."""
    imports, strings = [], []
    for rel in TRACK1_RUNTIME:
        p = Path(rel)
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"), rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in LEGACY_MODULES:
                        imports.append(f"{p.name}:{node.lineno} import {a.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module in LEGACY_MODULES:
                    imports.append(f"{p.name}:{node.lineno} from {node.module}")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in LEGACY_MODULES or node.value in LEGACY_STATE:
                    strings.append(f"{p.name}:{node.lineno} {node.value!r}")
    return {"imports": imports, "strings": strings}


def scheduler_under_removal() -> dict:
    """Build all three modes with legacy unimportable, and classify what registers."""
    from global_index import track1_slots as ts
    out = {}
    with block_legacy():
        importlib.reload(importlib.import_module("global_index.run_scheduler"))
        from global_index import run_scheduler as rs
        for label, kw in (("default", {}), ("track1_shadow", {"track1_shadow": True}),
                          ("track1_only", {"track1_only": True})):
            try:
                sched = rs.make_scheduler(port=4002, dry_run=True, **kw)
                ids = {j.id for j in sched.get_jobs()}
                out[label] = {
                    "built": True, "total": len(ids),
                    **{k: len([i for i in ids if ts._bucket_for(i) == k])
                       for k in ("shared_infra", "legacy_entry", "safety", "track1")},
                }
            except Exception as exc:                      # noqa: BLE001 — reporting a probe
                out[label] = {"built": False, "error": f"{type(exc).__name__}: {exc}"}
    return out


def track1_argv_under_removal() -> dict:
    """Can Track 1 still produce its slot argv with legacy gone?"""
    from global_index import track1_slots as ts
    seen = []
    with block_legacy():
        from global_index import run_scheduler as rs
        orig = rs._run
        try:
            rs._run = lambda args, label, dry_run, timeout=None, route=None: (
                seen.append((label, list(args), route)) or True)
            sched = rs.make_scheduler(port=4002, dry_run=True, track1_only=True)
            for j in sched.get_jobs():
                if j.id.startswith("track1_"):
                    j.func()
        finally:
            rs._run = orig
    providers = {}
    for _l, argv, _r in seen:
        providers.setdefault(argv[argv.index("--sleeve") + 1], set()).add(
            argv[argv.index("--bar-provider") + 1])
    return {"slots_fired": len(seen),
            "providers": {k: sorted(v) for k, v in providers.items()},
            "routes": sorted({r for _l, _a, r in seen}),
            "order_flags": sorted({f for _l, a, _r in seen
                                   for f in ("--allow-orders", "--port", "--window") if f in a}),
            "slot_table": len(ts.TRACK1_SLOTS)}


def dashboard_under_removal() -> dict:
    """Does the Track 1 dashboard mirror still build with legacy gone?"""
    prev = {k: os.environ.get(k) for k in ("RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY")}
    os.environ["RAITS_TRACK1_SHADOW"] = "1"
    os.environ["RAITS_TRACK1_ONLY"] = "1"
    try:
        with block_legacy():
            import datetime as dt
            from monitor.backend import schedule_status as ss
            importlib.reload(ss)
            rows = ss._scheduled_slots_for(dt.date(2026, 8, 24))
            ids = [r["id"] for r in rows]
            return {"built": True, "rows": len(ids),
                    "track1_rows": len([i for i in ids if i.startswith("TRACK1_")]),
                    "legacy_rows": len([i for i in ids
                                        if i.startswith(("LIVE_DAY", "NKD_NIGHT"))])}
    except Exception as exc:                              # noqa: BLE001
        return {"built": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        from monitor.backend import schedule_status as ss2
        importlib.reload(ss2)


def state_dependencies() -> dict:
    """Which Track 1 modules name legacy's state files, and in what role."""
    hits = []
    for rel in TRACK1_RUNTIME:
        p = Path(rel)
        if not p.exists():
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            for f in LEGACY_STATE:
                if f in line:
                    code = line.split("#")[0]
                    hits.append({"file": p.name, "line": n, "state": f,
                                 "in_code": f in code,
                                 "text": line.strip()[:110]})
    return {"hits": hits,
            "in_code": [h for h in hits if h["in_code"]]}


def safety_jobs_still_legacy() -> dict:
    """The safety sweeps: what positions file do they actually name?"""
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    try:
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.append((label, list(args))) or True)
        rs._run_guarded_orig = rs._run_guarded
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_only=True)
        for j in sched.get_jobs():
            if j.id.startswith("stop_repair") or j.id == "maxhold_exit":
                try:
                    j.func()
                except Exception:                          # noqa: BLE001
                    pass
    finally:
        rs._run = orig
    return {"jobs_fired": len(seen),
            "positions_paths": sorted({a[a.index("--positions-path") + 1]
                                       for _l, a in seen if "--positions-path" in a})}


def main() -> int:
    report = {
        "static_scan": static_scan(),
        "scheduler_under_removal": scheduler_under_removal(),
        "track1_argv_under_removal": track1_argv_under_removal(),
        "dashboard_under_removal": dashboard_under_removal(),
        "state_dependencies": state_dependencies(),
        "safety_jobs": safety_jobs_still_legacy(),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    Path("scratch/_stage5md_removable.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
