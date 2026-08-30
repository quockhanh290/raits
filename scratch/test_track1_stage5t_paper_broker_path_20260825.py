"""Stage 5T — the paper order boundary: what is absent, and what the seam must obey.

READ-ONLY of production data. No scheduler, no backend, no broker, no connection, no order, no
confirmation file, no `--allow-orders` anywhere.

Two jobs
--------
1. **Pin the absence.** Stage 5S found that "paper mode" does not exist. That fact is load
   bearing — every safety claim in this sequence rests on it — so it is asserted rather than
   remembered, and the day someone builds the path these tests must be changed ON PURPOSE.
2. **Pin the seam.** The one piece that can be built without a broker is the translation from
   an admitted candidate to a `broker.Order`, and it is held to the identity Stages 5Q-7 and
   5Q-9 established: bars from NKD, orders to MNK, quantity from the candidate.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(r"d:\raits")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import run_live_day_track1 as R              # noqa: E402
from global_index import track1_gates as gates                 # noqa: E402
from global_index import track1_live_source as src             # noqa: E402
from global_index import track1_paper_order as po              # noqa: E402
from global_index import track1_params as tp                   # noqa: E402
from global_index import track1_signal_layer as T              # noqa: E402
from global_index.ibkr_broker import ibkr_symbol_and_exchange  # noqa: E402


def cand(inst="MNKD", sleeve="global_nkd", qty=1, direction="SHORT"):
    return T.Candidate(trade_id=f"{sleeve}::{inst}", sleeve=sleeve, instrument=inst,
                       direction=direction, qty=qty, risk_dollars=100.0,
                       entry_time=pd.Timestamp("2026-08-25 14:15", tz="Asia/Tokyo"))


def _fn(module, name):
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name)


# ══════════════════════════════════════════════════════════════════════════════
# 1. The absence, pinned
# ══════════════════════════════════════════════════════════════════════════════

def test_run_shadow_still_builds_a_broker_that_cannot_send():
    """Armed or not, the route holds `NoOrderBroker`. When paper is built this test must be
    changed deliberately — that is the point of it."""
    fn = _fn(R, "run_shadow")
    made = [n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "NoOrderBroker" in made
    assert "IBKRBroker" not in made
    with pytest.raises(RuntimeError):
        R.NoOrderBroker().send_order(object())


def test_ibkr_broker_is_never_constructed_in_the_track1_runner():
    src_text = Path(R.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src_text)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "IBKRBroker"]
    assert calls == []


def test_the_scheduler_slot_path_takes_no_order_gate_at_all():
    """`observe_live_slot` is what the scheduler drives. It has no order-gate parameter and no
    reference to one, so `--allow-orders` cannot reach it even if every gate were released."""
    fn = _fn(R, "observe_live_slot")
    args = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
    assert "order_gate" not in args and "allow_orders" not in args
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "OrderGate" not in names


def test_no_order_can_be_sent_from_anywhere_in_the_track1_runner():
    src_text = Path(R.__file__).read_text(encoding="utf-8")
    for token in ("placeOrder", "MarketOrder", "LimitOrder", "reqIds"):
        assert token not in src_text, token


def test_the_executor_protocol_has_no_implementation_yet():
    stub = po.UnbuiltPaperExecutor()
    assert isinstance(stub, po.Track1OrderExecutor)
    for call in (lambda: stub.open_position(None),
                 lambda: stub.close_position(None, "x"),
                 lambda: stub.place_protective_stop(None),
                 lambda: stub.switch_same_symbol(None, None)):
        with pytest.raises(po.PaperOrderRefused) as e:
            call()
        assert e.value.code == po.NOT_IMPLEMENTED


def test_this_module_cannot_reach_a_broker():
    """The floor plan is not the building.

    Parsed, not grepped. The first version searched the source for the string "ib_insync" and
    went red on the module's own docstring, which says it does not import it — the fourth time
    a substring check in this project has matched the prose describing the thing it forbids.
    """
    tree = ast.parse(Path(po.__file__).read_text(encoding="utf-8"))

    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    assert "ib_insync" not in imported

    called = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Name):
            called.add(n.func.id)
        elif isinstance(n.func, ast.Attribute):
            called.add(n.func.attr)
    for forbidden in ("placeOrder", "connect", "IBKRBroker", "send_order", "reqHistoricalData"):
        assert forbidden not in called, forbidden


# ══════════════════════════════════════════════════════════════════════════════
# 2. The seam: candidate -> Order
# ══════════════════════════════════════════════════════════════════════════════

def test_mnkd_orders_the_micro_while_its_bars_come_from_the_full_size():
    """The whole identity split, spent in one place."""
    o = po.candidate_to_order(cand("MNKD"), ref_day="2026-08-25")
    assert o.inst == "MNKD"                                   # the RUNNER name goes on the order
    assert ibkr_symbol_and_exchange(o.inst)[0] == "MNK"       # the broker routes it to the micro
    assert src.history_symbol(o.inst) == "NKD"                # bars still come from full size
    assert "NKD" != ibkr_symbol_and_exchange(o.inst)[0]


def test_the_order_never_carries_the_history_symbol():
    """The 5Q-7 defect in reverse. If the data symbol ever reached an order, MNKD would trade
    the $5 contract at ten times the intended size."""
    for inst in ("MES", "MNQ", "MYM", "M2K", "MNKD"):
        sleeve = "global_nkd" if inst == "MNKD" else "roska4_swing"
        o = po.candidate_to_order(cand(inst, sleeve, qty=1, direction="LONG"),
                                  ref_day="2026-08-25")
        assert o.inst == inst
        if inst == "MNKD":
            assert src.history_symbol(inst) != ibkr_symbol_and_exchange(inst)[0]


def test_quantity_comes_from_the_candidate_not_the_instrument():
    """MNQ is one micro under Normal and seven under Stress on the same day."""
    a = po.candidate_to_order(cand("MNQ", "roska4_swing", qty=1), ref_day="2026-08-25")
    b = po.candidate_to_order(cand("MNQ", "roska4_stress", qty=7), ref_day="2026-08-25")
    assert (a.contracts, a.cluster) == (1, "roska4_swing")
    assert (b.contracts, b.cluster) == (7, "roska4_stress")
    assert tp.SLEEVE_QTY["roska4_stress"] == 7


@pytest.mark.parametrize("qty", [0, -1])
def test_a_non_positive_quantity_is_refused_not_rounded(qty):
    with pytest.raises(po.PaperOrderRefused) as e:
        po.candidate_to_order(cand("MES", "roska4_swing", qty=qty), ref_day="2026-08-25")
    assert e.value.code == po.QTY_INVALID


def test_ref_day_is_required_and_never_guessed_from_a_tokyo_stamp():
    with pytest.raises(po.PaperOrderRefused) as e:
        po.candidate_to_order(cand("MNKD"), ref_day=None)
    assert e.value.code == po.REF_DAY_MISSING
    # and it is not derivable by accident: the entry stamp is AWARE Tokyo
    assert cand("MNKD").entry_time.tzinfo is not None


def test_identity_drift_between_the_params_hash_and_the_broker_map_is_refused(monkeypatch):
    """The two must agree about what MNKD trades. If they ever disagree, one of them describes
    a different contract — and that is the 2026-08-14 defect, from the other direction."""
    import global_index.ibkr_broker as B
    monkeypatch.setitem(B._RAITS_TO_IBKR, "MNKD", "NKD")      # the defect, re-injected
    with pytest.raises(po.PaperOrderRefused) as e:
        po.candidate_to_order(cand("MNKD"), ref_day="2026-08-25")
    assert e.value.code == po.IDENTITY_DRIFT
    assert "10.0000x" in e.value.detail


def test_an_order_may_only_be_built_from_an_admitted_decision():
    taken = T.Decision(cand("MES", "roska4_swing"), T.TAKE, "")
    po.assert_admitted(taken)
    for verdict in (T.REJECT_CAP, T.REJECT_FAMILY_CAP, T.SUPPRESS_SAME_SYMBOL):
        with pytest.raises(po.PaperOrderRefused) as e:
            po.assert_admitted(T.Decision(cand("MES", "roska4_swing"), verdict, "why"))
        assert e.value.code == po.NOT_ADMITTED


# ══════════════════════════════════════════════════════════════════════════════
# 3. What must never change from shadow
# ══════════════════════════════════════════════════════════════════════════════

def test_the_invariant_list_names_every_thing_that_must_not_move():
    """Written as data so a test can walk it rather than as prose nothing checks."""
    what = {w for w, _where, _why in po.MUST_BE_IDENTICAL}
    for needed in ("live frame + splice guard", "freshness gate", "sizing basis",
                   "admission + caps", "explanations", "checkpoint + params hash"):
        assert needed in what, needed
    assert all(where and why for _w, where, why in po.MUST_BE_IDENTICAL)
    assert len(po.MAY_DIFFER) >= 3


def test_every_module_named_in_the_invariant_list_actually_exists():
    """A list of things that must not move is worthless if it names something that is not
    there. Only the dotted module prefixes are resolved — the list is prose about WHERE."""
    import importlib
    for _what, where, _why in po.MUST_BE_IDENTICAL:
        for token in where.replace("/", " ").split():
            if not token.startswith(("track1_", "global_index.")):
                continue
            mod = token.split(".")[0] if token.startswith("track1_") else token
            mod = mod if mod.startswith("global_index") else f"global_index.{mod}"
            importlib.import_module(mod)


def test_sizing_basis_is_the_one_the_measured_book_was_admitted_under():
    """5Q-9. If a paper implementation changed this, the shadow evidence would stop describing
    the thing that trades."""
    assert tp.SIZING_BASIS["roska4_swing"] == tp.SIZING_ARTIFACT_ATR
    assert tp.SIZING_BASIS["global_nkd"] == tp.SIZING_ARTIFACT_ATR
    assert tp.SIZING_BASIS["roska4_calm"] == tp.SIZING_TRUE_STOP
    assert tp.SIZING_BASIS["roska4_stress"] == tp.SIZING_TRUE_STOP


# ══════════════════════════════════════════════════════════════════════════════
# 4. The gates that must still hold
# ══════════════════════════════════════════════════════════════════════════════

def test_all_four_gates_still_hold_and_the_evidence_one_cannot_be_signed():
    blocking = {b.id for b in gates.blocking()}
    assert "B1_broker_account_or_legacy_retirement" in blocking
    assert "PAPER_SHADOW_EVIDENCE" in blocking
    assert gates.BLOCKERS["PAPER_SHADOW_EVIDENCE"].released_by == ()
    assert gates.may_enable_orders()[0] is False


def test_no_scheduler_or_ops_path_requests_orders():
    for f in ("global_index/run_scheduler.py", "monitor/ops.py"):
        tree = ast.parse(Path(f).read_text(encoding="utf-8"))
        lits = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value == "--allow-orders"]
        assert lits == [], f


def test_nothing_in_this_suite_armed_anything():
    import os
    assert not Path(gates.CONFIRMATION_PATH).exists()
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "")
