"""Stage 5ZZG — the SEND wire, and the proof it stays shut.

Until now the executor, the journal, the order mapping and the stop plan were all built and
**nothing called them**. That was safe, and it was also untestable: "the wire is missing" is not
a state anybody can assert about, and a wire built later under time pressure is a wire built
without these tests.

Measured before a line was written, and unchanged after:

    orders_possible          False
    blocking                 B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
    confirmation file        ABSENT
    TRACK1_ORDERS_APPROVED   unset
    track1_runtime/orders    ABSENT

**No broker is contacted anywhere in this file.** Every broker is a stub, every journal root is
a tmp_path, and no test arms the real gate.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "monitor"))

from global_index import track1_order_state as st  # noqa: E402
from global_index import track1_paper_send as ps  # noqa: E402


# ── stubs ────────────────────────────────────────────────────────────────────

class _Gate:
    def __init__(self, armed: bool):
        self.allow_orders = armed


class _Cand:
    def __init__(self, tid="calm_a::MES::2026-08-27"):
        self.trade_id = tid
        self.sleeve = "roska4_calm"
        self.instrument = "MES"
        self.direction = "LONG"
        self.qty = 1
        self.entry_price = 5000.0
        self.stop_price = 4982.0
        self.risk_dollars = 90.0


class _Decision:
    def __init__(self, verdict, cand=None):
        self.verdict = verdict
        self.candidate = cand or _Cand()


class _Fill:
    def __init__(self, status=st.FILLED, order_id="OID-1", filled_qty=1, avg_price=5000.0):
        self.status = status
        self.order_id = order_id
        self.filled_qty = filled_qty
        self.avg_price = avg_price
        self.commission = 0.35
        self.error_msg = ""


class _Broker:
    """Everything the executor requires, and nothing that reaches a network."""

    def __init__(self, fill=None, raises=None, receipt_id=None):
        self.calls: list = []
        self._fill = fill or _Fill()
        self._raises = raises
        self._receipt_id = receipt_id

    # `on_submit` is NAMED rather than swallowed by **kw: `accepts_receipt` inspects the
    # signature, so a stub that hides it behind **kw is a stub the executor decides cannot
    # report an order id — and the receipt test would skip while proving nothing.
    def send_order(self, order, on_submit=None, **kw):
        self.calls.append(order)
        if on_submit and self._receipt_id:
            on_submit(type("R", (), {"order_id": self._receipt_id})())
        if self._raises:
            raise self._raises
        return self._fill

    # The five the executor requires, measured from broker_capability_report rather than
    # guessed: cancel_order, get_order_status, get_positions, place_stop, send_order.
    def get_order_status(self, order_id):
        return {"order_id": order_id, "status": st.FILLED}

    def place_stop(self, *a, **k):
        return _Fill(status=st.FILLED, order_id="STOP-1")

    def get_open_orders(self):
        return []

    def get_positions(self):
        return []

    def cancel_order(self, *a, **k):
        return True

    def get_equity(self):
        return 250_000.0


def _take():
    from global_index import track1_signal_layer as T
    return _Decision(T.TAKE)


def _skip():
    from global_index import track1_signal_layer as T
    verdicts = [v for v in (getattr(T, n, None) for n in dir(T))
                if isinstance(v, str) and v and v != T.TAKE]
    return _Decision(verdicts[0] if verdicts else "skip")


def _journal_rows(root) -> list:
    out = []
    for f in Path(root).rglob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 1-4  the gate is shut
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_a_closed_gate_sends_nothing_and_builds_nothing(tmp_path):
    b = _Broker()
    s = ps.maybe_send_orders([_take(), _take()], order_gate=_Gate(False), broker=b,
                             ref_day="2026-08-27", slot_id="X", root=tmp_path)
    assert s.status == ps.GATE_CLOSED
    assert s.sent == 0 and s.executor_built is False
    assert b.calls == [], "the broker was called with the gate shut"
    assert not list(tmp_path.rglob("*.jsonl")), "a journal row was written"
    assert not (tmp_path / "global_index" / "track1_runtime" / "orders").exists()


def test_2_a_closed_gate_does_not_even_load_the_order_layer():
    """Asserted in a SUBPROCESS. Once any earlier test has armed the gate the module is in
    `sys.modules` for the rest of the session, and an in-process check would pass on a module
    somebody else imported."""
    import subprocess

    code = (
        "import sys\n"
        "from global_index import track1_paper_send as ps\n"
        "class G:\n    allow_orders = False\n"
        "ps.maybe_send_orders([1, 2], order_gate=G(), ref_day='2026-08-27')\n"
        "loaded = [m for m in ('global_index.track1_paper_executor',\n"
        "                      'global_index.track1_order_journal') if m in sys.modules]\n"
        "print('LOADED:' + ','.join(loaded))\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    assert "LOADED:" in r.stdout, r.stdout
    assert r.stdout.strip().endswith("LOADED:"), \
        f"the order layer was imported with the gate shut: {r.stdout.strip()}"


def test_3_the_gate_check_comes_before_the_import():
    """The ordering IS the contract. An import above the check would make test_2 unprovable."""
    src = Path(REPO / "global_index/track1_paper_send.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "maybe_send_orders")
    body = ast.unparse(fn)
    assert body.index("_armed(order_gate)") < body.index("track1_paper_executor")


def test_4_a_closed_gate_is_not_fatal(tmp_path):
    s = ps.maybe_send_orders([_take()], order_gate=_Gate(False), ref_day="2026-08-27",
                             root=tmp_path)
    assert s.fatal is False
    assert "send_order calls: 0" in s.one_line()


# ═══════════════════════════════════════════════════════════════════════════════
# 5-9  the gate is open, with a stub broker
# ═══════════════════════════════════════════════════════════════════════════════

def test_5_an_admitted_decision_reaches_the_broker(tmp_path):
    b = _Broker()
    s = ps.maybe_send_orders([_take()], order_gate=_Gate(True), broker=b,
                             ref_day="2026-08-27", slot_id="TRACK1_CALM_1000", root=tmp_path)
    assert s.status == ps.SENT
    assert s.sent == 1 and s.filled == 1 and s.executor_built is True
    assert len(b.calls) == 1


def test_6_a_decision_the_cap_gate_did_not_take_is_never_sent(tmp_path):
    b = _Broker()
    s = ps.maybe_send_orders([_skip(), _skip()], order_gate=_Gate(True), broker=b,
                             ref_day="2026-08-27", root=tmp_path)
    assert s.status == ps.NOTHING_ADMITTED
    assert s.offered == 2 and s.admitted == 0 and s.sent == 0
    assert b.calls == []
    assert not list(tmp_path.rglob("*.jsonl"))


def test_7_only_the_admitted_half_of_a_mixed_slot_is_sent(tmp_path):
    b = _Broker()
    s = ps.maybe_send_orders([_skip(), _take(), _skip()], order_gate=_Gate(True), broker=b,
                             ref_day="2026-08-27", root=tmp_path)
    assert s.offered == 3 and s.admitted == 1 and s.sent == 1
    assert len(b.calls) == 1


def test_8_the_journal_walks_intended_then_submitted_then_the_outcome(tmp_path):
    b = _Broker(fill=_Fill(status=st.FILLED))
    ps.maybe_send_orders([_take()], order_gate=_Gate(True), broker=b,
                         ref_day="2026-08-27", root=tmp_path)
    states = [r["state"] for r in _journal_rows(tmp_path)]
    assert states, "nothing was journalled"
    assert states[0] == st.INTENDED, states
    assert st.SUBMITTED in states, states
    assert states[-1] == st.FILLED, states
    assert states.index(st.INTENDED) < states.index(st.SUBMITTED) < len(states) - 1


@pytest.mark.parametrize("status,field", [
    (st.FILLED, "filled"), (st.PARTIAL, "partial"), (st.REJECTED, "rejected"),
])
def test_9_each_outcome_is_counted_under_its_own_name(tmp_path, status, field):
    b = _Broker(fill=_Fill(status=status))
    s = ps.maybe_send_orders([_take()], order_gate=_Gate(True), broker=b,
                             ref_day="2026-08-27", root=tmp_path)
    assert getattr(s, field) == 1, s.as_dict()
    assert _journal_rows(tmp_path)[-1]["state"] == status


# ═══════════════════════════════════════════════════════════════════════════════
# 10-12  a broker that raises is UNKNOWN, never REJECTED
# ═══════════════════════════════════════════════════════════════════════════════

def test_10_a_raising_broker_writes_UNKNOWN_and_is_fatal(tmp_path):
    b = _Broker(raises=TimeoutError("gateway went away"))
    s = ps.maybe_send_orders([_take()], order_gate=_Gate(True), broker=b,
                             ref_day="2026-08-27", root=tmp_path)
    assert s.unknown == 1
    assert s.rejected == 0, "an order whose fate is unknown was counted as refused"
    assert s.fatal is True
    assert s.errors and "TimeoutError" in s.errors[0]

    states = [r["state"] for r in _journal_rows(tmp_path)]
    assert states[-1] == st.UNKNOWN, states
    assert st.REJECTED not in states, states


def test_11_the_unknown_row_carries_the_error_and_the_key(tmp_path):
    b = _Broker(raises=RuntimeError("boom"))
    ps.maybe_send_orders([_take()], order_gate=_Gate(True), broker=b,
                         ref_day="2026-08-27", root=tmp_path)
    row = _journal_rows(tmp_path)[-1]
    assert row["state"] == st.UNKNOWN
    assert "boom" in str(row.get("error", ""))
    assert row.get("idempotency_key"), "the unresolved row cannot be looked up"


def test_12_one_bad_send_does_not_hide_a_good_one(tmp_path):
    """A slot with two admitted decisions must report both outcomes, not stop at the first."""
    class _Mixed(_Broker):
        def send_order(self, order, **kw):
            self.calls.append(order)
            if len(self.calls) == 1:
                raise TimeoutError("first one vanished")
            return _Fill(status=st.FILLED)

    b = _Mixed()
    d2 = _take()
    d2.candidate = _Cand("calm_a::MNQ::2026-08-27")
    s = ps.maybe_send_orders([_take(), d2], order_gate=_Gate(True), broker=b,
                             ref_day="2026-08-27", root=tmp_path)
    assert s.sent == 2 and s.unknown == 1 and s.filled == 1
    assert s.fatal is True


# ═══════════════════════════════════════════════════════════════════════════════
# 13-14  the receipt, and the missing broker
# ═══════════════════════════════════════════════════════════════════════════════

def test_13_a_broker_receipt_writes_the_order_id_as_an_amendment(tmp_path):
    from global_index import track1_paper_executor as ex

    b = _Broker(receipt_id="OID-RECEIPT")
    if not ex.accepts_receipt(b):
        pytest.skip("this stub's send_order does not advertise the receipt callback")
    ps.maybe_send_orders([_take()], order_gate=_Gate(True), broker=b,
                         ref_day="2026-08-27", root=tmp_path)
    rows = _journal_rows(tmp_path)
    ids = [r.get("order_id") for r in rows if r.get("order_id")]
    assert "OID-RECEIPT" in ids, rows
    submitted = [r for r in rows if r["state"] == st.SUBMITTED]
    assert len(submitted) >= 2, "the receipt did not add a second SUBMITTED row"


def test_14_armed_with_no_broker_refuses_rather_than_building_one(tmp_path):
    with pytest.raises(ps.SendRefused) as e:
        ps.maybe_send_orders([_take()], order_gate=_Gate(True), broker=None,
                             ref_day="2026-08-27", root=tmp_path)
    assert ps.NO_BROKER in str(e.value)
    assert "never constructs one" in str(e.value)
    assert not list(tmp_path.rglob("*.jsonl"))


def test_15_the_send_module_never_names_a_broker_class():
    src = Path(REPO / "global_index/track1_paper_send.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("IBKRBroker", "ib_insync", "connect"):
        assert forbidden not in names, f"the send module reaches for {forbidden}"


# ═══════════════════════════════════════════════════════════════════════════════
# 16-19  the slot, and main
# ═══════════════════════════════════════════════════════════════════════════════

def test_16_the_slot_passes_the_gate_and_the_broker_it_already_holds():
    src = Path(REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    body = ast.unparse(fn)
    assert "order_gate=gate" in body and "broker=broker" in body
    # and it is the SAME broker the bars came from — no second construction anywhere in main
    assert body.count("build_bar_provider") == 1
    assert "IBKRBroker(" not in body


def test_17_the_send_runs_after_the_coverage_row():
    """Nothing written after the coverage row may be the reason a slot loses it."""
    src = Path(REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    body = ast.unparse(fn)
    assert "maybe_send_orders" in body
    assert body.index("wl.slot_observed") < body.index("maybe_send_orders")


def test_18_the_hardcoded_zero_claim_is_gone():
    """`print("send_order calls: 0")` was true every day it was printed and true because
    nothing could send, not because anything had counted."""
    src = Path(REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
    assert 'print("send_order calls: 0")' not in code
    assert "_send.get('fatal')" in code or '_send.get("fatal")' in code


def test_19_an_unresolved_order_does_not_exit_zero():
    src = Path(REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    i = src.index('if _send.get("fatal")')
    seg = src[i:i + 900]
    assert "return 3" in seg, "an order whose fate is unknown returned a success code"
    assert "NOT a rejection" in seg


# ═══════════════════════════════════════════════════════════════════════════════
# 20-24  the scheduler still cannot reach any of it
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", ["global_index/run_scheduler.py", "monitor/ops.py"])
def test_20_no_scheduler_or_ops_source_contains_the_order_flag(path):
    src = Path(REPO / path).read_text(encoding="utf-8")
    code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
    assert "--allow-orders" not in code, f"{path} can arm orders"


def test_21_no_track1_slot_argv_carries_the_order_flag():
    from global_index import track1_slots as ts

    assert ts.TRACK1_SLOTS, "no slots — this test would pass on an empty table"
    for s in ts.TRACK1_SLOTS:
        argv = ["--source", "live-shadow", "--sleeve", s.sleeve, "--slot-id", s.id,
                "--bar-provider", "ibkr"] + (["--phase", s.phase] if s.phase else [])
        assert "--allow-orders" not in argv, s.id


def test_22_the_scheduler_body_builds_no_order_flag_in_any_branch():
    """Read from the real launcher body, both branches of its conditional."""
    src = Path(REPO / "global_index/run_scheduler.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_track1_body")
    assert "allow-orders" not in ast.unparse(fn)


def test_23_the_environment_flag_is_still_required():
    from global_index import track1_gates as gates

    src = Path(gates.__file__).read_text(encoding="utf-8")
    assert "TRACK1_ORDERS_APPROVED" in src
    import os
    assert os.environ.get("TRACK1_ORDERS_APPROVED") is None, \
        "this session has armed the approval flag — no test may do that"


def test_24_orders_are_still_impossible_and_nothing_was_armed():
    from global_index import track1_gates as gates

    possible, blocking = gates.may_enable_orders()
    assert possible is False
    assert blocking
    assert not Path(REPO / "track1_go_live_confirmation.json").exists()
    assert not Path(REPO / "global_index/track1_runtime/orders").exists(), \
        "an order journal appeared in the production tree"


def test_25_the_live_frame_gate_did_not_close():
    """A new `track1_*` module that constructed a broker would shut it and invent a blocker."""
    from global_index import track1_gates as gates

    ok, _detail = gates.live_frame_wiring("global_index")
    assert ok is True
    assert "track1_paper_send" in gates.route_modules("global_index")


# ═══════════════════════════════════════════════════════════════════════════════
# 26  the invariant the old tests held, restated rather than dropped
# ═══════════════════════════════════════════════════════════════════════════════

#: Every production module allowed to name the executor, and what stands between it and a real
#: order. Two, not one — the dry-run callsite from Stage 5Z reaches it too, and pretending
#: otherwise would be a tidier sentence than the truth.
EXECUTOR_IMPORTERS = {
    "track1_paper_send.py": "the gated send: the import sits past the gate check, so an "
                            "unarmed run never loads the order layer at all",
    "track1_paper_callsite.py": "the dry run: it hands the executor a RefusingBroker whose "
                                "send_order raises rather than returning a synthetic fill, and "
                                "whose CAN_TESTIFY is False so its empty reads are never read "
                                "as 'flat'",
}


def test_26_the_executor_is_reachable_only_through_a_wall_or_the_gate(tmp_path):
    """The old invariant was "nothing imports the executor". That was true, and this stage makes
    it false BY DESIGN, so it is replaced rather than deleted — and replaced with what is
    actually the case rather than with a neater version of it.

    Two modules may name the executor. One is walled (a broker that refuses everything), one is
    gated (the import happens past the check). A third appearing here is a new path to a broker
    and this test is the only thing that would say so.
    """
    importers = []
    for f in sorted((REPO / "global_index").glob("*.py")):
        if f.name == "track1_paper_executor.py":
            continue
        code = "\n".join(ln.split("#")[0]
                          for ln in f.read_text(encoding="utf-8").splitlines())
        if "track1_paper_executor" in code:
            importers.append(f.name)

    assert set(importers) == set(EXECUTOR_IMPORTERS), {
        "unexpected": sorted(set(importers) - set(EXECUTOR_IMPORTERS)),
        "missing": sorted(set(EXECUTOR_IMPORTERS) - set(importers))}

    # the walled one really is walled
    from global_index import track1_paper_callsite as cs

    wall = cs.RefusingBroker()
    assert wall.CAN_TESTIFY is False
    with pytest.raises(Exception):
        wall.send_order(object())

    # and the gated one really is gated
    b = _Broker()
    closed = ps.maybe_send_orders([_take()], order_gate=_Gate(False), broker=b,
                                  ref_day="2026-08-27", root=tmp_path)
    assert closed.executor_built is False and b.calls == []


# ═══════════════════════════════════════════════════════════════════════════════
# mutations
# ═══════════════════════════════════════════════════════════════════════════════

def _must_fail(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except AssertionError:
        return True
    return False


def test_M1_the_gate_stops_being_checked_mutation(monkeypatch, tmp_path):
    """Collapse: the first line of defence is removed.

    With `_armed` forced true a closed gate walks past the check — and the SECOND line holds:
    the executor's own constructor refuses an unarmed gate and raises. That is the layering
    working, and this test says which layer caught it rather than counting a crash as a pass.
    The broker must still not have been called either way.
    """
    monkeypatch.setattr(ps, "_armed", lambda gate: True)
    b = _Broker()
    with pytest.raises(Exception) as e:
        ps.maybe_send_orders([_take()], order_gate=_Gate(False), broker=b,
                             ref_day="2026-08-27", root=tmp_path)
    assert "not_armed" in str(e.value).lower() or "does not permit" in str(e.value)
    assert b.calls == [], "the broker was reached with the gate shut"
    assert not list(tmp_path.rglob("*.jsonl")), "a journal row was written past a shut gate"


def test_M2_unknown_counted_as_rejected_mutation(monkeypatch, tmp_path):
    """Collapse: an order whose fate is unknown is filed as refused."""
    real = ps.maybe_send_orders

    def _mutated(decisions, **kw):
        s = real(decisions, **kw)
        return ps.SendSummary(**{**s.as_dict(), "unknown": 0, "rejected": s.unknown,
                                 "errors": [], "fatal": False}
                              | {}) if False else ps.SendSummary(
            status=s.status, reason=s.reason, offered=s.offered, admitted=s.admitted,
            sent=s.sent, filled=s.filled, partial=s.partial, rejected=s.unknown,
            unknown=0, errors=[], executor_built=s.executor_built)

    monkeypatch.setattr(ps, "maybe_send_orders", _mutated)
    assert _must_fail(test_10_a_raising_broker_writes_UNKNOWN_and_is_fatal, tmp_path), \
        "test_10 stayed green while an unknown outcome was counted as a rejection"


def test_M3_non_admitted_decisions_start_sending_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(ps, "_admitted", lambda decisions: list(decisions or ()))
    assert _must_fail(test_6_a_decision_the_cap_gate_did_not_take_is_never_sent, tmp_path), \
        "test_6 stayed green while an unadmitted decision was sent"


def test_M4_the_scheduler_gains_the_order_flag_mutation(monkeypatch, tmp_path):
    """Collapse: somebody adds `--allow-orders` to the launcher."""
    real_read = Path.read_text

    def _spiked(self, *a, **k):
        txt = real_read(self, *a, **k)
        if self.name == "run_scheduler.py":
            return txt.replace('"--bar-provider", provider]',
                               '"--bar-provider", provider, "--allow-orders"]')
        return txt

    monkeypatch.setattr(Path, "read_text", _spiked)
    assert _must_fail(test_20_no_scheduler_or_ops_source_contains_the_order_flag,
                      "global_index/run_scheduler.py"), \
        "test_20 stayed green while the scheduler could arm orders"
