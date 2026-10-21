"""monitor/test_track1_runtime_timing_20260924.py — track1-runtime walks the explanation tree once.

Plan stage 5. The plan's 55.8 s for /api/v1/track1-runtime was not reproducible on 2026-09-24
evening; measured then, before any change:

    warm, 5 calls                     3.35 – 3.69 s
    cold, first call after restart    16.6 s, alongside the paper-evidence warm-up thread (13.0 s)
    paper-evidence warm-up, backend log: 57 – 80.8 s every restart until plan stage 4 moved it to
    Track 1 (13 – 18.6 s after) — the likeliest source of the 55.8 s, measured the same afternoon
    as runner-state at 21.1 s, i.e. under contention. Stated as likeliest, not proven.

Per component (cProfile, warm): `_explanations` 3.58 s of the total, 2.79 s of that in `rglob`,
27,346 `stat` calls — the tree was walked once to list the days and once more PER DAY inside
`explanation_files`. Changed to one walk grouped by day: 3.07 s -> 0.96 s, output IDENTICAL to a
copy saved before the change (20 days, 1,178 rows). The next hot spot is `attribution_from_path`
(two `Path.resolve()` per file, 0.52 s) in the acceptance gate's own module; not touched.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import monitor.backend.track1_runtime_reader as rr
from global_index import track1_shadow_acceptance as acc


def _tree(root: Path) -> None:
    """All three layouts `explanation_files` promises to find, across two days."""
    base = root / rr.SHADOW_DIR / "explanations"
    rows = lambda n: "".join(json.dumps({"i": i}) + "\n" for i in range(n))   # noqa: E731
    files = {
        base / "explanations_20260923.jsonl": 2,                                   # flat
        base / "live_2026-09-23" / "explanations_20260923.jsonl": 3,              # 5Q
        base / "live_2026-09-24" / "roska4_swing" / "TRACK1_SWING_1555"
        / "explanations_20260924.jsonl": 4,                                        # 5Q-2
        base / "live_2026-09-24" / "global_nkd" / "NKD_NIGHT_0110"
        / "explanations_20260924.jsonl": 1,
    }
    for path, n in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rows(n), encoding="utf-8")


def _per_day_reference(root: Path) -> dict:
    """The algorithm as it stood BEFORE stage 5: the resolver called once per day."""
    d = root / rr.SHADOW_DIR / "explanations"
    days = sorted({f.stem.replace("explanations_", "") for f in d.rglob("explanations_*.jsonl")})
    out = {"present": True, "days": {}, "attribution": {}}
    for day in days:
        files = acc.explanation_files(root, day)
        out["days"][day] = sum(
            sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
            for f in files)
        attrib = [acc.explanation_attribution(f, root) for f in files]
        out["attribution"][day] = {
            "files": len(files),
            "sleeves": sorted({a["sleeve"] for a in attrib if a["sleeve"]}),
            "slots": len({a["slot_id"] for a in attrib if a["slot_id"]}),
            "shapes": sorted({a["shape"] for a in attrib}),
        }
    return out


def test_one_walk_gives_exactly_the_per_day_answer(tmp_path):
    _tree(tmp_path)
    ref = _per_day_reference(tmp_path)
    assert ref["days"] == {"20260923": 5, "20260924": 5}, "the fixture did not build three layouts"
    assert rr._explanations(tmp_path) == ref


def test_the_resolver_is_called_once_per_request_not_once_per_day(tmp_path, monkeypatch):
    _tree(tmp_path)
    calls = []
    real = acc.explanation_files
    monkeypatch.setattr(acc, "explanation_files",
                        lambda root, day="", **k: calls.append(day) or real(root, day, **k))
    rr._explanations(tmp_path)
    assert calls == [""], f"the tree was walked {len(calls)} times: {calls}"


def test_history_cache_returns_stale_snapshot_while_refreshing(tmp_path, monkeypatch):
    """An expired history snapshot must never put its multi-second scan on the poll path."""
    rr.invalidate_history_cache()
    calls = []

    def build(_root):
        calls.append(len(calls) + 1)
        time.sleep(0.05)
        return {"window_coverage": {"generation": calls[-1]},
                "explanations": {}, "audits": {}}

    monkeypatch.setattr(rr, "_build_history", build)
    monkeypatch.setattr(rr, "_HISTORY_TTL_SECONDS", 0.01)
    assert rr._history(tmp_path)["window_coverage"]["generation"] == 1

    time.sleep(0.02)
    started = time.perf_counter()
    stale = rr._history(tmp_path)
    elapsed = time.perf_counter() - started
    assert stale["window_coverage"]["generation"] == 1
    assert elapsed < 0.04, f"stale read blocked for {elapsed:.3f}s"

    deadline = time.monotonic() + 1
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    while time.monotonic() < deadline:
        with rr._history_cache_lock:
            if not rr._history_cache[str(tmp_path.resolve())]["refreshing"]:
                break
        time.sleep(0.01)
    assert rr._history(tmp_path)["window_coverage"]["generation"] == 2
    rr.invalidate_history_cache()
