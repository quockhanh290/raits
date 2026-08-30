"""Stage 5ZZZ-R - the restart put the Stage 5ZZZ-Q fix into the running scheduler.

These tests pin the things a restart is allowed to change (the process) and the things it
must not (the mode, the job composition, the order gate, the source tree). They are written
to be able to go red: every list is asserted non-empty before it is walked, and the
"no legacy entry job" test first proves the legacy set DOES contain the jobs it is looking
for, so a lookup that silently matches nothing cannot read as a pass.
"""
import os
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import psutil                                                    # noqa: E402

from global_index import run_live_day_track1 as RUN              # noqa: E402
from global_index import track1_gates as GATES                   # noqa: E402
from global_index import track1_replay_parity as PARITY          # noqa: E402
from global_index import track1_slots as TS                      # noqa: E402

RUNTIME_TRADING_FILES = (
    "global_index/track1_live_source.py",
    "global_index/track1_signals.py",
    "global_index/run_live_day_track1.py",
    "global_index/track1_normal_r4.py",
    "global_index/run_scheduler.py",
)


def _schedulers():
    """Live scheduler processes, excluding this test process.

    The exclusion is not cosmetic: a token scan over cmdlines matched this very
    measurement command earlier in the stage, because the command contained the token
    it was searching for.
    """
    me = os.getpid()
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        if p.info["pid"] == me:
            continue
        cl = " ".join(p.info["cmdline"] or [])
        if "global_index.run_scheduler" in cl and "-m" in cl:
            out.append((p.info["pid"], cl))
    return out


# ═══════════════════════════════════════════════════════════════════════════════════════
# 1. the restart itself
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_restart_left_exactly_one_scheduler():
    """Two schedulers racing clientId=1 has really happened here and cost six entry slots."""
    procs = _schedulers()
    assert len(procs) == 1, f"expected exactly one scheduler, found {procs}"


def test_the_running_scheduler_is_still_track1_only_shadow():
    procs = _schedulers()
    assert procs, "no scheduler running; this test would otherwise pass on nothing"
    _, cl = procs[0]
    assert "--track1-only-shadow" in cl, cl
    assert "--allow-orders" not in cl, cl


def test_the_restart_did_not_touch_any_runtime_trading_file():
    """A restart replaces a process. It must not rewrite the source it starts from."""
    procs = _schedulers()
    assert procs, "no scheduler running"
    started = psutil.Process(procs[0][0]).create_time()
    for rel in RUNTIME_TRADING_FILES:
        p = REPO / rel
        assert p.exists(), rel
        assert p.stat().st_mtime < started, (
            f"{rel} was modified after the scheduler started - the restart, or something "
            f"during it, wrote to a runtime trading file")


# ═══════════════════════════════════════════════════════════════════════════════════════
# 2. job composition
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_track1_only_mode_registers_no_legacy_entry_job():
    only = TS.scheduler_slot_ids(track1_only=True)
    legacy = TS.legacy_scheduler_slot_ids()
    assert only, "empty job set - the assertion below would pass on nothing"

    def entry_jobs(ids):
        return sorted(i for i in ids if "live_day" in i.lower())

    # First prove the search term finds something where it should. Without this, a renamed
    # job id would make the real assertion vacuously true.
    assert entry_jobs(legacy), "no live_day job found in the LEGACY set; the token is stale"
    assert entry_jobs(only) == [], entry_jobs(only)


def test_the_track1_slot_table_is_the_expected_size():
    assert len(TS.track1_slot_ids()) == 71


# ═══════════════════════════════════════════════════════════════════════════════════════
# 3. the fix is the one now loaded
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_post_fix_swing_regime_basis_is_causal_d1():
    assert RUN.SLEEVE_REGIME_BASIS["roska4_swing"] == "causal_d1"
    assert RUN._signal_regime_basis("roska4_swing") == "causal_d1"


def test_the_live_swing_call_site_still_builds_the_lagged_object():
    """The map above is a label. This checks the code the scheduler actually imported."""
    import inspect

    from global_index import track1_live_source as LS

    src = inspect.getsource(LS)
    swing = src[src.index("def _swing_candidates"):]
    swing = swing[:swing.index("\n    def ")]
    assert "lag_days=1" in swing, "the recorded basis says causal_d1; the call site no longer is"


# ═══════════════════════════════════════════════════════════════════════════════════════
# 4. old evidence, and what cannot become a pass
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_pre_fix_evidence_does_not_report_pass():
    report = PARITY.parity()
    sleeves = report["sleeves"]
    assert sleeves, "no sleeves in the parity report"
    for name, body in sleeves.items():
        assert body["verdict"] != PARITY.PASS, (
            f"{name} reports PASS on evidence written before the fix")
        info = body.get("pre_fix_informational")
        if info:
            assert info["verdict"] != PARITY.PASS, name


def test_an_empty_params_hash_is_unknown_and_never_pass():
    chk = PARITY._check("params_hash", "", None)
    assert chk.verdict == PARITY.UNKNOWN
    assert chk.verdict != PARITY.PASS


def test_a_field_that_does_match_still_can_pass():
    """Guards the test above from being true merely because _check never returns PASS."""
    chk = PARITY._check("route", "track1_candidate", "track1_candidate")
    assert chk.verdict == PARITY.PASS


def test_parity_releases_no_gate():
    report = PARITY.parity()
    assert report["counts_toward_paper_shadow_evidence"] is False


# ═══════════════════════════════════════════════════════════════════════════════════════
# 5. orders remain impossible
# ═══════════════════════════════════════════════════════════════════════════════════════

def test_no_order_path_is_reachable():
    ok, why = GATES.may_enable_orders()
    assert ok is False, why
    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in GATES.blocking()}
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not os.environ.get("TRACK1_ORDERS_APPROVED")


def test_the_confirmation_record_is_present_and_carries_no_order_approval():
    """The record confirms LEGACY RETIREMENT. It is not an order approval, and the point of
    this test is that it has no field which could become one - measured, after a first
    version of this test guessed both the path and a field that does not exist."""
    import json

    p = REPO / GATES.CONFIRMATION_PATH
    assert p.exists(), f"the confirmation record is missing at {p}"
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert rec.get("legacy_retired_confirmed") is True, rec
    approval_fields = [k for k in rec if "order" in k.lower() or "approv" in k.lower()]
    assert approval_fields == [], approval_fields
