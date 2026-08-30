"""Stage 5ZZZ-T - the gate's AST scan is memoised on file content identity.

This is a SAFETY file, so the tests are built around one question: can the cache ever answer
"I saw the file and it was clean" for a file it has not actually seen in its current state?
Every case below is an attempt to make that happen.

The two invalidation tests are deliberately adversarial. A same-SIZE edit is used to prove
mtime is load-bearing, and a same-MTIME edit to prove size is; either key part alone would
pass a naive test and miss a real one.
"""
import ast
import os
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_gates as G  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    G._IDENT_CACHE.clear()
    yield
    G._IDENT_CACHE.clear()


def _count_parses(fn):
    """Run `fn`, return (result, number of ast.parse calls it made)."""
    n = {"c": 0}
    orig = ast.parse

    def counting(*a, **k):
        n["c"] += 1
        return orig(*a, **k)

    G.ast.parse = counting
    try:
        return fn(), n["c"]
    finally:
        G.ast.parse = orig


# ═══════════════════════════════════════════════════════════════════════════════════════
# 1. it caches, and it caches the right thing
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_same_file_identity_is_parsed_once(tmp_path):
    f = tmp_path / "track1_probe.py"
    f.write_text("import alpha\n", encoding="utf-8")

    first, n1 = _count_parses(lambda: G._identifiers(f))
    second, n2 = _count_parses(lambda: G._identifiers(f))

    assert "alpha" in first, first
    assert first == second
    assert n1 == 1, "the first call must actually parse"
    assert n2 == 0, "the second call parsed again - the cache is not being used"


def test_the_cache_key_is_path_mtime_and_size(tmp_path):
    f = tmp_path / "track1_probe.py"
    f.write_text("import alpha\n", encoding="utf-8")
    G._identifiers(f)
    st = f.stat()
    assert list(G._IDENT_CACHE) == [(str(f.resolve()), st.st_mtime_ns, st.st_size)]


def test_two_different_files_do_not_share_an_entry(tmp_path):
    a = tmp_path / "track1_a.py"
    b = tmp_path / "track1_b.py"
    a.write_text("import alpha\n", encoding="utf-8")
    b.write_text("import bravo\n", encoding="utf-8")
    assert "alpha" in G._identifiers(a)
    assert "bravo" in G._identifiers(b)
    assert "alpha" not in G._identifiers(b)


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2. invalidation - the part that decides whether this is safe
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_a_same_size_edit_is_caught_by_mtime(tmp_path):
    """`import alpha` and `import bravo` are the SAME LENGTH. Only mtime can see this, so a
    key without mtime would serve the old identifiers for new content."""
    f = tmp_path / "track1_probe.py"
    f.write_text("import alpha\n", encoding="utf-8")
    size_before = f.stat().st_size          # on-disk, not len() - Windows rewrites newlines
    before = G._identifiers(f)
    assert "alpha" in before and "bravo" not in before

    time.sleep(0.01)
    f.write_text("import bravo\n", encoding="utf-8")
    assert f.stat().st_size == size_before, "the edit must be the same size on disk"

    after = G._identifiers(f)
    assert "bravo" in after, "a same-size edit was served from a stale cache"
    assert "alpha" not in after


def test_a_same_mtime_edit_is_caught_by_size(tmp_path):
    """The timestamp is forced back to what it was, so mtime cannot see this edit. Only size
    can, which is why size is in the key."""
    f = tmp_path / "track1_probe.py"
    f.write_text("import alpha\n", encoding="utf-8")
    st = f.stat()
    before = G._identifiers(f)
    assert "charlie" not in before

    f.write_text("import alpha\nimport charlie\n", encoding="utf-8")
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert f.stat().st_mtime_ns == st.st_mtime_ns, "the timestamp must be unchanged"
    assert f.stat().st_size != st.st_size

    after = G._identifiers(f)
    assert "charlie" in after, "a same-mtime edit was served from a stale cache"


def test_no_stale_safety_result_survives_a_source_change(tmp_path):
    """The whole point, stated as the gate sees it: a module that gains a live-bar fetcher
    must stop looking clean."""
    (tmp_path / "track1_probe.py").write_text("import os\n", encoding="utf-8")
    clean = G._identifiers(tmp_path / "track1_probe.py")
    assert not (clean & G.LIVE_BAR_NAMES)

    time.sleep(0.01)
    (tmp_path / "track1_probe.py").write_text("from ib_insync import IB\n", encoding="utf-8")
    dirty = G._identifiers(tmp_path / "track1_probe.py")
    assert dirty & G.LIVE_BAR_NAMES, "a module that started fetching live bars still reads clean"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 3. the cached object cannot be edited underneath the next caller
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_the_cached_identifier_set_is_immutable(tmp_path):
    f = tmp_path / "track1_probe.py"
    f.write_text("import alpha\n", encoding="utf-8")
    names = G._identifiers(f)
    assert isinstance(names, frozenset)
    with pytest.raises(AttributeError):
        names.add("ib_insync")               # type: ignore[attr-defined]
    assert "ib_insync" not in G._identifiers(f)


# ═══════════════════════════════════════════════════════════════════════════════════════
# 4. fail-closed on a file it cannot read
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_a_missing_file_raises_and_is_never_cached(tmp_path):
    missing = tmp_path / "track1_gone.py"
    with pytest.raises(OSError):
        G._identifiers(missing)
    assert not G._IDENT_CACHE, "a file that could not be read left a cache entry"


def test_a_file_that_disappears_after_being_cached_still_raises(tmp_path):
    """'I cannot see the file' must never be answered from 'I saw it once and it was fine'."""
    f = tmp_path / "track1_probe.py"
    f.write_text("import alpha\n", encoding="utf-8")
    assert "alpha" in G._identifiers(f)
    f.unlink()
    with pytest.raises(OSError):
        G._identifiers(f)


def test_unparseable_source_still_raises(tmp_path):
    f = tmp_path / "track1_bad.py"
    f.write_text("def (((\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        G._identifiers(f)


# ═══════════════════════════════════════════════════════════════════════════════════════
# 5. the gate itself is unchanged
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_blocking_is_identical_with_a_cold_and_a_warm_cache():
    G._IDENT_CACHE.clear()
    cold = sorted(b.id for b in G.blocking())
    warm = sorted(b.id for b in G.blocking())
    assert cold == warm
    assert "PAPER_SHADOW_EVIDENCE" in cold


def test_the_wiring_measurement_is_identical_cold_and_warm():
    G._IDENT_CACHE.clear()
    cold = G.live_frame_wiring()
    warm = G.live_frame_wiring()
    assert cold == warm, (cold, warm)


def test_the_full_ledger_is_identical_cold_and_warm():
    """Not just the summary: every blocker's measured_now, which is where a cached wiring
    result would show up if it were wrong."""
    import json

    G._IDENT_CACHE.clear()
    cold = json.dumps(G.as_ledger(), sort_keys=True, default=str)
    warm = json.dumps(G.as_ledger(), sort_keys=True, default=str)
    assert cold == warm


def test_no_gate_decision_is_cached_only_identifiers():
    """The cache must hold parsed names and nothing else. A blocker list or a measurement
    result in here would be a decision remembered against a file timestamp."""
    G._IDENT_CACHE.clear()
    G.blocking()
    assert G._IDENT_CACHE, "nothing was cached; this test would pass on an empty dict"
    for k, v in G._IDENT_CACHE.items():
        assert isinstance(v, frozenset), (k, type(v))
        assert all(isinstance(x, str) for x in v)


# ═══════════════════════════════════════════════════════════════════════════════════════
# 6. orders stay impossible
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_paper_shadow_evidence_still_blocks():
    ok, why = G.may_enable_orders()
    assert ok is False, why
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}


def test_the_env_var_alone_does_not_open_orders(monkeypatch):
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    G._IDENT_CACHE.clear()
    ok, _ = G.may_enable_orders()
    assert ok is False, "an environment variable opened the order gate"
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in G.blocking()}


def test_the_confirmation_and_override_grant_no_order_authority():
    import json

    from global_index import track1_swing_paper_override as SO

    rec = json.loads((REPO / G.CONFIRMATION_PATH).read_text(encoding="utf-8"))
    assert [k for k in rec if "order" in k.lower() or "approv" in k.lower()] == []
    ov = SO.load()
    assert ov.valid
    assert ov.grants_orders is False
    assert ov.satisfies_shadow_evidence is False
    assert G.may_enable_orders()[0] is False


def test_no_orders_directory_and_no_subprocess_in_the_gate_path():
    tree = ast.parse((REPO / "global_index" / "track1_gates.py").read_text(encoding="utf-8"))
    banned = {"subprocess", "ib_insync", "socket", "requests", "urllib"}
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names.add((n.module or "").split(".")[0])
    assert not (names & banned), names & banned
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
