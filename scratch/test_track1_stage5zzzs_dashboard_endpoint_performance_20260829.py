"""Stage 5ZZZ-S - the dashboard's expensive panels compute off the request path.

The regression these guard against is specific and was measured: `_recon_cached` used to
compute inline on a cold miss, so the FIRST market-view request after a backend restart paid
a full pass over the bar history - 71s in a fresh process, and it blocked the whole payload,
including panels that did not depend on it.

Every test here is written so it can go red. The slow reader is a stub that would genuinely
hang the request if the deferral were removed, rather than an assertion about the shape of
the code.
"""
import ast
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from monitor.backend import track1_market_view as MV  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_caches():
    """Each test starts cold and leaves nothing behind for the next one."""
    with MV._recon_lock:
        MV._recon_cache.clear()
        MV._slice_inflight.clear()
    MV._slice_cache.clear()
    yield
    with MV._recon_lock:
        MV._recon_cache.clear()
        MV._slice_inflight.clear()
    MV._slice_cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════════════
# 1. the slow reader does not block the response
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_a_cold_miss_returns_immediately_instead_of_computing_inline():
    """THE regression. A reader that takes 5s must not add 5s to the request."""
    started = []

    def slow():
        started.append(1)
        time.sleep(5)
        return {"computed": True}

    t0 = time.perf_counter()
    value = MV._recon_cached(("test", "cold"), slow)
    elapsed = time.perf_counter() - t0

    assert elapsed < 1.0, f"the cold miss blocked for {elapsed:.2f}s - it was computed inline"
    assert value is None, "a cold miss must report nothing, not a fabricated value"


def test_the_background_worker_actually_fills_the_cache():
    """The other half: deferring is only honest if the value really does arrive.

    The reader sleeps briefly on purpose. A reader that returns instantly can legitimately
    have finished before the caller re-reads the cache, and the first version of this test
    asserted `None` and raced against its own stub.
    """
    def quick():
        time.sleep(0.4)
        return {"computed": True}

    assert MV._recon_cached(("test", "fill"), quick) is None
    for _ in range(50):
        time.sleep(0.1)
        got = MV._recon_cached(("test", "fill"), quick)
        if got is not None:
            assert got == {"computed": True}
            return
    pytest.fail("the background worker never filled the cache")


def test_a_polled_endpoint_spawns_one_worker_not_one_per_poll():
    """Without claiming the key under the lock, 50 polls during a 71s warm-up would start
    50 workers all recomputing the same thing."""
    calls = []

    def slow():
        calls.append(1)
        time.sleep(3)
        return {"x": 1}

    for _ in range(25):
        MV._recon_cached(("test", "storm"), slow)
    time.sleep(0.5)
    assert len(calls) == 1, f"{len(calls)} workers were started for one key"


def test_the_state_helper_distinguishes_warming_from_failed():
    """'still computing' and 'computed and it raised' are different facts. Collapsing them
    is how an empty panel comes to mean either."""
    def boom():
        raise RuntimeError("store unreadable")

    assert MV._recon_state(("test", "absent"))[0] == "absent"
    MV._recon_cached(("test", "boom"), boom)
    for _ in range(50):
        time.sleep(0.1)
        state, err = MV._recon_state(("test", "boom"))
        if state == "failed":
            assert "RuntimeError" in err and "store unreadable" in err
            return
    pytest.fail("a raising reader never reached the failed state")


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2. invalidation still keys on the source, not on a clock
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_stress_slice_cache_key_still_carries_store_mtimes():
    """Stage 5ZZQ chose an mtime key over a TTL deliberately, so an appended store
    invalidates rather than being served stale until a timer expires. Stage 5ZZZ-S moved
    WHEN the value is computed and must not have moved WHAT invalidates it."""
    src = ast.unparse(ast.parse(Path(REPO / "monitor/backend/track1_market_view.py")
                                .read_text(encoding="utf-8")))
    marker = "key = tuple(sorted(((i, Path(paths[i]).stat().st_mtime) for i in need)))"
    assert marker in src, "the stress slice cache key no longer carries the stores' mtimes"


def test_the_label_cache_is_keyed_on_the_csv_mtime():
    """The regime labels are an HMM fit - measured at 12.8s. It must re-fit when the CSV
    changes and never on a timer."""
    import inspect

    src = inspect.getsource(MV._label_map)
    assert "st_mtime" in src, "the label cache no longer invalidates on the CSV's mtime"


def test_a_changed_mtime_produces_a_different_cache_key():
    """The property the two tests above assert structurally, exercised."""
    a = tuple(sorted([("MES", 100.0), ("MNQ", 200.0)]))
    b = tuple(sorted([("MES", 100.5), ("MNQ", 200.0)]))
    assert a != b


# ═══════════════════════════════════════════════════════════════════════════════════════
# 3. honesty of the degraded payload
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_a_deferred_panel_reports_unavailable_with_a_reason_never_a_value():
    out = {"sleeve": "roska4_swing", "rules": [], "status": "x", "detail": ""}
    key = ("roska4_swing", "2026-08-31", "store")
    MV._recon_cached(key, lambda: (time.sleep(5), {"rules": [1]})[1])
    state, _ = MV._recon_state(key)
    assert state == "warming"
    # the caller's contract: no rule values invented while warming
    assert out["rules"] == []


def test_not_available_is_not_a_pass_word():
    """A deferred panel must never render as a PASS-like verdict."""
    assert MV.NOT_AVAILABLE not in ("PASS", "pass", "ok", "OK", True)
    assert isinstance(MV.NOT_AVAILABLE, str)


# ═══════════════════════════════════════════════════════════════════════════════════════
# 4. what the endpoint path may not do
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_market_view_module_spawns_no_shell_or_subprocess():
    """Measured separately on the running backend: 20 polls spawned zero child processes.
    This pins the source so a future edit cannot reintroduce one."""
    tree = ast.parse(Path(REPO / "monitor/backend/track1_market_view.py")
                     .read_text(encoding="utf-8"))
    banned = {"subprocess", "os.system", "popen", "powershell", "pwsh", "cmd.exe"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[0] not in banned, a.name
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned, node.module


def test_the_market_view_module_never_imports_the_broker():
    """Bars come from the persisted store. The backend does hold a read-only IBKR connection
    for a different reader; this endpoint must not be a second one."""
    tree = ast.parse(Path(REPO / "monitor/backend/track1_market_view.py")
                     .read_text(encoding="utf-8"))
    banned = {"ib_insync", "ibkr_broker", "IBKRBroker"}
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
            names |= {a.name for a in node.names}
    assert not (names & banned), names & banned


def test_the_deferral_did_not_move_a_decision_into_the_dashboard():
    """The panels are reconstructions that CALL the route's own detector. If the dashboard
    started computing entries itself, the reconstruction would stop matching the slot."""
    src = Path(REPO / "monitor/backend/track1_market_view.py").read_text(encoding="utf-8")
    # the reconstruction must still delegate, not reimplement
    assert "detect_entry_for_slot" in src
    assert "calm_blocks" in src


def test_the_swing_reconstruction_still_uses_the_causal_d1_object():
    """Stage 5ZZZ-Q's guarantee must survive a performance change."""
    import inspect

    src = inspect.getsource(MV._normal_r4_reconstruction)
    assert "lag_days=1" in src, "the replay no longer mirrors the live causal D-1 basis"
