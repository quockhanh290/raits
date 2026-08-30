"""Stage 5ZZK — the gate that could not see the decision.

The operator placed a valid, hash-verified B1 decision. Every measurement passed. `ops status`
went on printing B1 as blocking, and it would have gone on printing it forever.

`blocking()` took `NO_CONFIRMATIONS` as its default, so with no argument it answered a question
nobody was asking: *what would still block if the operator had signed nothing?* Exactly one
caller in the repo passed confirmations — the live-shadow entry point. The status command, the
readiness report, the dashboard reader, the ledger and the order executor all took the default.

It failed CLOSED, so nothing unsafe followed. But a gate that cannot be seen to open is a gate
nobody can finish.

These tests hold the fix and, more importantly, the seven ways B1 must still refuse. Nothing
here connects to a broker or writes to the production confirmation path.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import track1_account_baseline as ab           # noqa: E402
from global_index import track1_b1 as b1                         # noqa: E402
from global_index import track1_b1_decision as dec               # noqa: E402
from global_index import track1_gates as g                       # noqa: E402

B1_ID = "B1_broker_account_or_legacy_retirement"
SHADOW_ID = "PAPER_SHADOW_EVIDENCE"
ACCOUNT = "DUR125337"

#: The canonical fixture — the operator's real decision, byte-for-byte. Item 11: the preview
#: and the gate are exercised against THIS, so "they agree on the schema" is demonstrated
#: rather than asserted.
CANONICAL = json.loads(
    (ROOT / "track1_go_live_confirmation.json").read_text(encoding="utf-8"))


# ── fakes for the two records the gate reads ────────────────────────────────────────────
class _Audit:
    def __init__(self, status=b1.PASS, book_path="live_positions.track1.json",
                 account_id=None):
        self.status, self.code = status, "legacy_and_broker_flat"
        self.checked_at, self.detail = "2026-08-27T16:04:17.115797+00:00", "measured"
        broker = {"positions": [], "open_orders": [], "equity": 250_819.13}
        if account_id:
            broker["account_id"] = account_id
        self.inputs = {"broker": broker,
                       "legacy_book": {"count": 0},
                       "track1_book": {"count": 0, "path": book_path}}


class _Baseline:
    def __init__(self, status="PASS", account_id=ACCOUNT):
        self.status, self.code = status, "account_flat_and_funded"
        self.checked_at, self.detail = "2026-08-27T11:29:47.831562+00:00", "measured"
        self.inputs = {"account": {"account_id": account_id, "currency": "USD",
                                   "equity": 250_817.91}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A complete, passing world under tmp_path. Each test spoils one thing."""
    book = tmp_path / "live_positions.track1.json"
    book.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                                "positions": []}), encoding="utf-8")
    conf_path = tmp_path / "track1_go_live_confirmation.json"
    conf_path.write_text(json.dumps(CANONICAL), encoding="utf-8")

    state = {"audit": _Audit(book_path=str(book)), "baseline": _Baseline(),
             "conf_path": conf_path, "book": book, "root": tmp_path}
    monkeypatch.setattr(b1, "latest", lambda *a, **k: state["audit"])
    monkeypatch.setattr(ab, "latest", lambda *a, **k: state["baseline"])
    monkeypatch.setattr(g, "CONFIRMATION_PATH", str(conf_path))
    return state


def _blocking():
    """Exactly what a caller with no arguments gets — the path this stage is about."""
    return [b.id for b in g.blocking()]


# ── item 1: the real schema is accepted ─────────────────────────────────────────────────
def test_the_real_confirmation_is_accepted_when_the_evidence_passes(world):
    assert CANONICAL["legacy_retired_confirmed"] is True
    assert B1_ID not in _blocking(), g.b1_decision_evidence(world["root"])[1]


def test_the_canonical_fixture_is_the_operators_actual_file():
    """If the file on disk ever stops matching what these tests exercise, this suite is
    testing a schema nobody uses. Item 11."""
    on_disk = json.loads((ROOT / "track1_go_live_confirmation.json").read_text(encoding="utf-8"))
    assert on_disk == CANONICAL
    conf, errors = g.load_confirmations(ROOT / "track1_go_live_confirmation.json")
    assert errors == []
    assert conf.get("legacy_retired_confirmed") is True


def test_the_preview_and_the_gate_share_one_parser(world):
    """Item 11, as a property rather than a claim: the preview reads its file through
    `track1_gates.load_confirmations`, so there is no second schema to drift."""
    text = (ROOT / "global_index" / "track1_b1_decision.py").read_text(encoding="utf-8")
    assert "_g.load_confirmations(" in text
    assert "json.loads" not in text, "the preview must not parse the confirmation itself"
    pv = dec.preview(world["conf_path"], world["root"])
    assert pv.valid and pv.decisions == ["legacy_retired_confirmed"]


# ── items 2–7: the refusals ─────────────────────────────────────────────────────────────
def test_a_missing_confirmation_keeps_b1_blocked(world, monkeypatch):
    world["conf_path"].unlink()
    assert B1_ID in _blocking()


def test_a_confirmation_with_no_decision_keeps_b1_blocked(world):
    """Item 7 — a signed file that decides nothing. It validates; it grants nothing."""
    payload = {k: v for k, v in CANONICAL.items() if k != "legacy_retired_confirmed"}
    world["conf_path"].write_text(json.dumps(payload), encoding="utf-8")
    conf, errors = g.load_confirmations(world["conf_path"])
    assert errors == [], "this file is VALID — the point is that valid is not the same as decided"
    assert B1_ID in _blocking()


def test_a_book_stamped_with_another_route_keeps_b1_blocked(world):
    """Item 3. B1 exists because one login is one position book; a book carrying another
    route's stamp is not this route's book."""
    world["book"].write_text(json.dumps({"schema_version": 2, "route": "legacy",
                                         "positions": []}), encoding="utf-8")
    assert B1_ID in _blocking()
    ok, why = g.b1_decision_evidence(world["root"])
    assert ok is False and "not 'track1_candidate'" in why


def test_a_book_with_no_route_stamp_keeps_b1_blocked(world):
    world["book"].write_text(json.dumps({"schema_version": 2, "positions": []}),
                             encoding="utf-8")
    assert B1_ID in _blocking()


def test_an_unreadable_book_keeps_b1_blocked(world):
    world["book"].write_text("{not json", encoding="utf-8")
    assert B1_ID in _blocking()
    assert g.b1_decision_evidence(world["root"])[0] is False


def test_a_mismatched_account_keeps_b1_blocked(world):
    """Item 4. The audit and the baseline describing different logins is the exact failure
    this gate is for."""
    world["audit"] = _Audit(book_path=str(world["book"]), account_id="DU999999")
    assert B1_ID in _blocking()
    ok, why = g.b1_decision_evidence(world["root"])
    assert ok is False and "account mismatch" in why


def test_matching_accounts_do_not_block(world):
    world["audit"] = _Audit(book_path=str(world["book"]), account_id=ACCOUNT)
    assert B1_ID not in _blocking()


@pytest.mark.parametrize("status", ["FAIL", "UNKNOWN"])
def test_a_stale_or_failed_b1_measurement_keeps_b1_blocked(world, status):
    """Item 5. UNKNOWN included on purpose: 'I could not ask the account' must not open a
    gate that 'I asked and it was flat' opens."""
    world["audit"] = _Audit(status=status, book_path=str(world["book"]))
    assert B1_ID in _blocking()


@pytest.mark.parametrize("status", ["FAIL", "UNKNOWN"])
def test_a_stale_or_failed_account_baseline_keeps_b1_blocked(world, status):
    """Item 6 — and this one was NOT checked before this stage."""
    world["baseline"] = _Baseline(status=status)
    assert B1_ID in _blocking()


def test_a_baseline_that_names_no_account_keeps_b1_blocked(world):
    world["baseline"] = _Baseline(account_id=None)
    assert B1_ID in _blocking()


def test_an_unreadable_baseline_fails_closed(world, monkeypatch):
    monkeypatch.setattr(ab, "latest",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
    assert B1_ID in _blocking()
    ok, why = g.b1_decision_evidence(world["root"])
    assert ok is False and "failing closed" in why


def test_file_existence_alone_does_not_release_b1(world):
    """Part C.4, stated as its own test because it is the thing a reader will doubt."""
    world["audit"] = _Audit(status="UNKNOWN", book_path=str(world["book"]))
    assert world["conf_path"].exists()
    conf, errors = g.load_confirmations(world["conf_path"])
    assert errors == [] and conf.get("legacy_retired_confirmed") is True
    assert B1_ID in _blocking(), "a valid file released the gate with no passing evidence"


# ── items 8–9: it releases only B1, and arms nothing ────────────────────────────────────
def test_a_valid_decision_releases_only_b1(world):
    after = _blocking()
    assert B1_ID not in after
    assert SHADOW_ID in after, "the evidence gate must be untouched by a signature"


def test_a_valid_decision_does_not_make_orders_possible(world):
    possible, reasons = g.may_enable_orders()
    assert possible is False
    assert any(SHADOW_ID in r for r in reasons)


def test_every_clause_of_the_evidence_produces_words(world):
    """The defect this function was born with: two clauses compared fields that are not
    recorded, so both were `if value and value != expected` — a check that never fires,
    reading in the reasons list exactly like a check that passed.
    """
    ok, why = g.b1_decision_evidence(world["root"])
    assert ok is True
    for expected in ("B1 audit", "book route", "account baseline", "account "):
        assert expected in why, f"{expected!r} clause produced no words: {why}"


def test_the_uncheckable_clause_says_so_rather_than_passing_quietly(world):
    """The B1 audit records no account id, so the two records cannot be cross-checked. That
    is reported as unchecked, not counted as a pass."""
    _ok, why = g.b1_decision_evidence(world["root"])
    assert "NOT CHECKED" in why


# ── item 10: the two reporters agree ────────────────────────────────────────────────────
def test_ops_status_and_blocking_agree():
    """Run against the REAL state, in a subprocess, because that disagreement is the whole
    reason this stage exists — and an in-process check would share the import that was
    already fixed."""
    out = subprocess.run([sys.executable, "monitor/ops.py", "status"],
                         cwd=ROOT, capture_output=True, text=True, timeout=300).stdout
    line = [l for l in out.splitlines() if l.startswith("track1_blocking=")]
    assert line, out[-2000:]
    from_ops = line[0].split("track1_blocking=")[1].split(" orders_possible=")[0]
    from_gates = str([b.id for b in g.blocking()])
    assert from_ops == from_gates, f"ops says {from_ops}, gates says {from_gates}"


def test_the_no_argument_default_reads_the_signed_file():
    """The regression this stage is. `blocking()` and `blocking(NO_CONFIRMATIONS)` must NOT
    be the same call any more."""
    import inspect
    sig = inspect.signature(g.blocking)
    assert sig.parameters["conf"].default is None, (
        "the default is a standing confirmation object again — it must mean 'read the file'")
    assert [b.id for b in g.blocking(g.NO_CONFIRMATIONS)] != [b.id for b in g.blocking()], (
        "the signed view and the unsigned view are identical, so the file is not being read")


def test_an_unreadable_confirmation_file_falls_back_to_nothing_granted(tmp_path, monkeypatch):
    bad = tmp_path / "track1_go_live_confirmation.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(g, "CONFIRMATION_PATH", str(bad))
    # `get` answers False for a flag that is not set — not None. Worth pinning: an assertion
    # written against the wrong falsy value passes for the wrong reason as easily as it fails.
    assert g.current_confirmations(str(bad)).get("legacy_retired_confirmed") is False
    assert B1_ID in _blocking()


def test_current_confirmations_fails_closed_when_the_loader_itself_raises(monkeypatch):
    """The last-resort guard, exercised on purpose.

    `load_confirmations` answers bad JSON with NO_CONFIRMATIONS rather than by raising, so the
    `except` inside `current_confirmations` never fires in ordinary use — which means a
    mutation that rewrites it changes nothing and reports GREEN. That is not a sleeping guard,
    it is an unreachable one, and the difference matters: unreachable code that LOOKS like a
    safety net is how a real failure later finds nothing underneath it.

    So the raise is forced here. A loader that blows up — an unreadable mode, a path that
    explodes on `exists()` — must still grant nothing.
    """
    def boom(*a, **k):
        raise OSError("the confirmation path could not be examined at all")

    monkeypatch.setattr(g, "load_confirmations", boom)
    conf = g.current_confirmations()
    assert conf.get("legacy_retired_confirmed") is False
    assert B1_ID in _blocking(), "a loader that raised opened the gate"


# ── safety ──────────────────────────────────────────────────────────────────────────────
def test_orders_remain_impossible_in_the_real_world():
    import os
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")
    assert not (ROOT / "global_index" / "track1_runtime" / "orders").exists()
    possible, _ = g.may_enable_orders()
    assert possible is False
    assert SHADOW_ID in [b.id for b in g.blocking()]


def test_no_allow_orders_in_the_scheduler_or_ops_call_paths():
    def stripped(path: Path) -> str:
        return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                         if not l.strip().startswith("#"))

    for rel in ("global_index/run_scheduler.py", "monitor/ops.py"):
        assert "--allow-orders" not in stripped(ROOT / rel), rel


def test_reading_the_confirmation_cannot_arm_anything(monkeypatch):
    """The change makes a signed decision VISIBLE. It must not make it sufficient.

    Asserted behaviourally rather than by hunting for a string: the gate registry's own
    evidence prose NAMES the approval variable, so a substring search finds it and proves
    nothing about whether it is read. Setting it must change nothing here.
    """
    before = [b.id for b in g.blocking()]
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    assert [b.id for b in g.blocking()] == before
    assert g.may_enable_orders()[0] is False, (
        "the approval variable reached the gate registry, which decides blockers only")
