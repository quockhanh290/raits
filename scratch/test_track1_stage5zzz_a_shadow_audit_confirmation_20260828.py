"""Stage 5ZZZ-A — a signature is not an armed order.

The shadow audit failed every sleeve, every day, from the moment the operator signed the B1
decision. Its reason was `confirmation_file_present`, and when that rule was written it was
right: the signature really was the last thing between this route and an order.

It stopped being right in stages. Stage 5S added a measured evidence gate, Stage 5ZZK gave B1 a
measured half of its own, and the operator signed on 2026-08-27 with `orders_possible` false
throughout. From then on the file records that a DECISION was made. Whether an order could be
sent is a different question with its own answer, and the audit now asks it directly.

Measured on 2026-08-28 before the change: Calm and NKD FAIL, reasons `['confirmation_file_present']`
and nothing else — on a day whose evidence was clean.

An audit that fails on every day is an audit nobody reads by the time a real breach arrives, so
most of this file is about the breaches it must still catch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_gates as G                    # noqa: E402
from global_index import track1_shadow_acceptance as sa       # noqa: E402


def _no_orders(root=REPO):
    out = sa.audit_now(root)
    check = next(c for c in out["checks"] if c.get("name") == "no_orders")
    return check["status"], str(check.get("detail", ""))


@pytest.fixture
def orders_impossible(monkeypatch):
    """The real state of this route: a blocker open, and it is a measured one."""
    monkeypatch.setattr(G, "may_enable_orders",
                        lambda *a, **k: (False, ["PAPER_SHADOW_EVIDENCE: not enough days"]))
    monkeypatch.setattr(G, "as_ledger", lambda: {"blocking_now": ["PAPER_SHADOW_EVIDENCE"]})
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the signature alone
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_a_signed_confirmation_does_not_fail_the_order_gate(orders_impossible):
    """The whole stage, in one assertion. The file is on disk; orders are impossible."""
    assert (REPO / sa.CONFIRMATION_PATH).exists(), "precondition: the decision is signed"
    status, detail = _no_orders()
    assert status == sa.OK, detail
    assert "confirmation file exists during a shadow period" not in detail


def test_the_detail_says_the_file_is_there_and_why_it_does_not_matter(orders_impossible):
    """Not hidden — reported, with the thing that IS holding orders named in the same breath."""
    _status, detail = _no_orders()
    assert "confirmation present" in detail
    assert "PAPER_SHADOW_EVIDENCE" in detail


def test_no_confirmation_and_no_orders_is_still_ok(monkeypatch, tmp_path, orders_impossible):
    (tmp_path / "global_index" / "track1_runtime").mkdir(parents=True)
    status, detail = _no_orders(tmp_path)
    assert status == sa.OK, detail
    assert "no confirmation file" in detail


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. what must STILL fail — the reason the rule existed at all
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_orders_actually_possible_during_shadow_still_fails(monkeypatch):
    monkeypatch.setattr(G, "may_enable_orders", lambda *a, **k: (True, []))
    monkeypatch.setattr(G, "as_ledger", lambda: {"blocking_now": []})
    status, detail = _no_orders()
    assert status == sa.FAIL
    assert "would not have been refused" in detail


def test_either_half_of_the_gate_saying_orders_are_possible_fails(monkeypatch):
    """Fail-closed across a registry that disagrees with itself.

    Normally the two move together - the gate reports `allowed` only when nothing is blocking -
    so a test that flips both proves nothing about either. Each is flipped alone here, because
    a reader that trusted only one of them would pass an audit on a route the other says can
    send.
    """
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    # allowed, yet something still listed as blocking
    monkeypatch.setattr(G, "may_enable_orders", lambda *a, **k: (True, []))
    monkeypatch.setattr(G, "as_ledger", lambda: {"blocking_now": ["PAPER_SHADOW_EVIDENCE"]})
    assert _no_orders()[0] == sa.FAIL, "the gate said orders are possible"
    # refused, yet nothing listed as blocking
    monkeypatch.setattr(G, "may_enable_orders",
                        lambda *a, **k: (False, ["PAPER_SHADOW_EVIDENCE: not enough days"]))
    monkeypatch.setattr(G, "as_ledger", lambda: {"blocking_now": []})
    assert _no_orders()[0] == sa.FAIL, "no blocker is open"


def test_a_confirmation_plus_orders_possible_still_fails(monkeypatch):
    """The combination the old rule was reaching for, now caught by the half that matters."""
    assert (REPO / sa.CONFIRMATION_PATH).exists()
    monkeypatch.setattr(G, "may_enable_orders", lambda *a, **k: (True, []))
    monkeypatch.setattr(G, "as_ledger", lambda: {"blocking_now": []})
    assert _no_orders()[0] == sa.FAIL


def test_the_out_of_band_approval_fails_hard(monkeypatch, orders_impossible):
    """`TRACK1_ORDERS_APPROVED` is what actually arms an order, and the gate registry
    deliberately does not read the environment — Stage 5ZZS pinned that. If this check did not
    look, an approved shadow run would pass an audit whose whole subject is whether an order
    could have been sent.

    Set through monkeypatch, inside this process, and asserted to FAIL — the opposite of arming
    anything. It is never written to a file or exported.
    """
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    status, detail = _no_orders()
    assert status == sa.FAIL
    assert "TRACK1_ORDERS_APPROVED" in detail


def test_an_order_journal_directory_fails_hard(monkeypatch, tmp_path, orders_impossible):
    (tmp_path / "global_index" / "track1_runtime" / "orders").mkdir(parents=True)
    status, detail = _no_orders(tmp_path)
    assert status == sa.FAIL
    assert "order journal" in detail


def test_an_order_mark_on_a_record_still_fails_first(monkeypatch, orders_impossible):
    """Precedence: an order that actually happened outranks every reason it should not have."""
    monkeypatch.setattr(sa, "_timing_rows", lambda *a, **k: [{"order_id": "X1"}])
    status, detail = _no_orders()
    assert status == sa.FAIL
    assert "order mark" in detail


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. the regression the stage is guarding against
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_no_code_path_treats_the_confirmation_file_as_armed_orders():
    """The file may be READ — the gate registry reads it, and so does the audit to report it.
    What must not exist is a branch that fails, blocks or arms on its presence alone."""
    src = (REPO / "global_index" / "track1_shadow_acceptance.py").read_text(encoding="utf-8")
    assert "the confirmation file exists during a shadow period" not in src
    block = src.split("# ── orders: none attempted")[1].split("# ── freshness proofs")[0]
    assert "elif confirmation:" in block, "the file is no longer reported at all"
    confirmation_branch = block.split("elif confirmation:")[1]
    assert "FAIL" not in confirmation_branch.split("else:")[0], confirmation_branch[:400]


def test_the_gate_registry_is_what_decides(monkeypatch, orders_impossible):
    """Flip only the gate and the verdict follows it, with the file untouched on disk."""
    assert _no_orders()[0] == sa.OK
    monkeypatch.setattr(G, "may_enable_orders", lambda *a, **k: (True, []))
    monkeypatch.setattr(G, "as_ledger", lambda: {"blocking_now": []})
    assert _no_orders()[0] == sa.FAIL
    assert (REPO / sa.CONFIRMATION_PATH).exists(), "the file was never the variable"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. today, per sleeve
# ══════════════════════════════════════════════════════════════════════════════════════════

DAY = "2026-08-28"


@pytest.mark.parametrize("sleeve", ["roska4_calm", "global_nkd"])
def test_todays_closed_sleeves_are_not_failed_by_the_order_gate(sleeve, orders_impossible):
    """Calm ran both phases and NKD ran its window; both were clean, and both were FAILED for
    the signature alone before this change."""
    out = sa.evaluate_sleeve(DAY, sleeve, REPO)
    assert "confirmation_file_present" not in (out.get("reasons") or [])
    assert out.get("verdict") != "FAIL", out
    for detail in out.get("details") or []:
        assert "confirmation file exists during a shadow period" not in str(detail)


def test_calm_is_not_failed_for_a_decide_with_no_setup_and_an_observe_with_no_row(
        orders_impossible):
    """Today's actual shape: DECIDE reached NO_SETUP / no_candidate and OBSERVE REFUSED with
    no_decide_row_for_this_day. Neither is an order-gate finding."""
    out = sa.evaluate_sleeve(DAY, "roska4_calm", REPO)
    reasons = out.get("reasons") or []
    assert "confirmation_file_present" not in reasons
    assert "order_mark_present" not in reasons
    assert "order_gate_not_blocking" not in reasons


def test_a_window_that_has_not_closed_is_not_passed(orders_impossible):
    """The complement: a stage that made everything pass would have hidden this too.

    Written first against "Stress and Swing have not run yet", which was true at the hour it was
    written and false eight hours later — the third time in this session that a test of mine
    pinned a state the clock moves. It asks the audit about a window that CANNOT have closed
    instead, so the assertion means the same thing at every hour.
    """
    out = sa.evaluate_sleeve("2026-12-31", "roska4_swing", REPO)
    assert out.get("verdict") != "PASS", out
    assert "confirmation_file_present" not in (out.get("reasons") or []), out


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. nothing was armed by this stage
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_orders_are_still_impossible_for_real():
    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in [r.split(":")[0] for r in reasons]


def test_the_confirmation_file_is_intact_and_signed():
    conf = REPO / sa.CONFIRMATION_PATH
    assert conf.exists(), "this stage must not delete the operator's decision"
    data = json.loads(conf.read_text(encoding="utf-8"))
    assert (data.get("confirmed_by") or "").strip()
    assert data.get("legacy_retired_confirmed") is True


def test_no_order_artefacts_exist():
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not (REPO / "global_index" / "live_positions.track1.json").exists()
