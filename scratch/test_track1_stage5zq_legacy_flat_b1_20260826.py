"""Stage 5ZQ — B1 becomes a thing that was measured, not a thing that was signed.

Until this stage B1 was released by a signature and by nothing else: a person writing
`legacy_retired_confirmed: true` asserted a fact about an IBKR account, and no code ever asked
the account. Precondition 7 of the switch-over runbook — "legacy is flat AT THE BROKER" — had
never been checked by anything.

Two defects made that worse than it looks:

1. the dashboard's IBKR collector builds `positions` and `orders` inside try/except blocks
   that log a warning and leave the list EMPTY, then publish `connected: true, error: null`.
   So the one live source of broker truth could not tell "the account holds nothing" from
   "the call raised" — fail-open, on the exact question B1 asks;
2. `IBKRBroker.get_open_orders()` was written with an honest tri-state contract (`None` when
   it cannot testify, never `[]`) in Stage 5X and had NO CALLER.

Every assertion here is on structured payloads or AST. Nothing greps prose.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import pytest

from global_index import track1_b1 as b1
from global_index import track1_gates as g

REPO = Path(r"d:\raits")


# ══════════════════════════════════════════════════════════════════════════════
# fixtures — the shapes the real thing produces
# ══════════════════════════════════════════════════════════════════════════════

def book(tmp_path: Path, name: str, positions: list) -> b1.BookState:
    p = tmp_path / name
    p.write_text(json.dumps({"schema_version": 1, "positions": positions}), encoding="utf-8")
    return b1.read_book(p)


def flat_book(tmp_path: Path, name: str) -> b1.BookState:
    return book(tmp_path, name, [])


def evidence(*, positions=None, orders=None, minutes_ago: int = 0,
             source="ibkr_direct", connected=True, **kw) -> b1.BrokerEvidence:
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    return b1.BrokerEvidence(source=source, connected=connected,
                             observed_at=when.isoformat(),
                             positions=positions, open_orders=orders, **kw)


A_POSITION = {"instrument": "MES", "direction": "SHORT", "contracts": 1}
A_STOP = {"instrument": "MES", "order_type": "STP", "action": "BUY", "quantity": 1,
          "status": "PreSubmitted", "order_id": "14"}


# ══════════════════════════════════════════════════════════════════════════════
# 1–7. the measurement
# ══════════════════════════════════════════════════════════════════════════════

def test_1_flat_books_and_a_flat_broker_measure_pass(tmp_path):
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                   evidence(positions=[], orders=[]))
    assert r.status == b1.PASS, r.detail
    assert r.code == b1.OK


def test_2_a_legacy_book_with_positions_fails(tmp_path):
    r = b1.measure(book(tmp_path, "legacy.json", [A_POSITION]),
                   flat_book(tmp_path, "t1.json"), evidence(positions=[], orders=[]))
    assert r.status == b1.FAIL
    assert r.code == b1.LEGACY_BOOK_POSITIONS
    assert r.findings["legacy_positions"] == [A_POSITION]


def test_3_a_broker_holding_positions_fails_even_with_a_clean_file(tmp_path):
    """The whole point of precondition 7: a clean local book says this SYSTEM holds nothing.
    It says nothing about the account."""
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                   evidence(positions=[A_POSITION], orders=[A_STOP]))
    assert r.status == b1.FAIL
    assert r.code == b1.BROKER_POSITIONS
    assert r.findings["broker_positions"] == [A_POSITION]


def test_4_a_working_stop_with_nothing_behind_it_fails(tmp_path):
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                   evidence(positions=[], orders=[A_STOP]))
    assert r.status == b1.FAIL
    assert r.code == b1.ORPHAN_ORDERS
    assert len(r.findings["orphans"]) == 1
    assert r.findings["orphans"][0]["instrument"] == "MES"


def test_5_a_broker_that_could_not_be_asked_is_unknown_not_pass(tmp_path):
    for ev in (b1.broker_unavailable("gateway down"),
               evidence(positions=None, orders=[], positions_error="reqPositions raised"),
               evidence(positions=[], orders=None, orders_error="reqAllOpenOrders raised")):
        r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"), ev)
        assert r.status == b1.UNKNOWN, (ev.source, r.status, r.code)
        assert r.status != b1.PASS


def test_6_positions_are_flat_but_orders_unknown_still_holds(tmp_path):
    """Positions flat is not enough. A working stop with no position behind it is the exact
    hazard B1 is asked about, and it lives in the list that could not be read."""
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                   evidence(positions=[], orders=None, orders_error="raised"))
    assert r.status == b1.UNKNOWN
    assert r.code == b1.BROKER_ORDERS_UNKNOWN


def test_7_a_track1_book_with_positions_before_paper_fails(tmp_path):
    r = b1.measure(flat_book(tmp_path, "legacy.json"),
                   book(tmp_path, "t1.json", [A_POSITION]),
                   evidence(positions=[], orders=[]))
    assert r.status == b1.FAIL
    assert r.code == b1.TRACK1_BOOK_POSITIONS


def test_8_a_missing_book_is_unknown_never_flat(tmp_path):
    absent = b1.read_book(tmp_path / "nothing_here.json")
    assert absent.state == b1.BOOK_ABSENT
    assert not absent.flat and not absent.known
    r = b1.measure(absent, flat_book(tmp_path, "t1.json"), evidence(positions=[], orders=[]))
    assert r.status == b1.UNKNOWN
    assert r.code == b1.BOOK_MISSING


def test_9_an_unreadable_book_is_unknown(tmp_path):
    p = tmp_path / "legacy.json"
    p.write_text("{ not json", encoding="utf-8")
    r = b1.measure(b1.read_book(p), flat_book(tmp_path, "t1.json"),
                   evidence(positions=[], orders=[]))
    assert r.status == b1.UNKNOWN
    assert r.code == b1.BOOK_UNREADABLE


def test_10_a_book_without_a_positions_key_says_nothing(tmp_path):
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({"schema_version": 1, "breaker": {}}), encoding="utf-8")
    st = b1.read_book(p)
    assert st.state == b1.BOOK_BAD
    assert not st.flat


def test_11_stale_broker_evidence_is_unknown(tmp_path):
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                   evidence(positions=[], orders=[],
                            minutes_ago=b1.MAX_BROKER_OBSERVATION_MINUTES + 5))
    assert r.status == b1.UNKNOWN
    assert r.code == b1.BROKER_EVIDENCE_STALE


# ══════════════════════════════════════════════════════════════════════════════
# the fail-open collector — the defect that made the cheap path unusable
# ══════════════════════════════════════════════════════════════════════════════

def _snapshot(**inner) -> dict:
    base = {"equity": 1.0, "positions": [], "orders": []}
    base.update(inner)
    return {"connected": True, "error": None,
            "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "payload": base}


def test_12_a_snapshot_without_the_ok_flags_proves_nothing(tmp_path):
    """An old payload cannot be read as flat. Its collector turns a raised exception into an
    empty list, so its empty list is not an answer."""
    ev = b1.from_dashboard_snapshot(_snapshot())
    assert not ev.positions_known and not ev.orders_known
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"), ev)
    assert r.status == b1.UNKNOWN


def test_13_a_snapshot_that_reports_success_is_usable(tmp_path):
    ev = b1.from_dashboard_snapshot(_snapshot(positions_ok=True, orders_ok=True))
    assert ev.positions_known and ev.orders_known
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"), ev)
    assert r.status == b1.PASS


def test_14_a_snapshot_that_reports_a_failed_section_is_unknown(tmp_path):
    ev = b1.from_dashboard_snapshot(_snapshot(positions_ok=True, orders_ok=False))
    assert ev.positions_known and not ev.orders_known
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"), ev)
    assert r.status == b1.UNKNOWN
    assert r.code == b1.BROKER_ORDERS_UNKNOWN


def test_15_the_reader_starts_unable_to_testify():
    """AST over the cache literal: both flags must start False. A cache that has never been
    filled has not said the account is flat."""
    src = (REPO / "monitor/backend/ibkr_reader.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # `_cache: dict[str, Any] = {...}` is an AnnAssign, not an Assign. Both are accepted so
    # the test does not go red merely because someone adds or drops the annotation.
    cache = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "_cache":
                cache = node.value
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_cache" for t in node.targets):
            cache = node.value
    assert isinstance(cache, ast.Dict), "_cache is no longer a dict literal"
    got = {k.value: getattr(v, "value", "?") for k, v in zip(cache.keys, cache.values)
           if isinstance(k, ast.Constant)}
    assert got.get("positions_ok") is False, got
    assert got.get("orders_ok") is False, got


def test_16_each_collector_marks_its_own_success_inside_its_try():
    """AST, not a text search: the flag must be set as the LAST statement of the try body, so
    it cannot be reached when the loop above it raised."""
    src = (REPO / "monitor/backend/ibkr_reader.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_reader_thread")
    marked = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Try) or not node.body:
            continue
        last = node.body[-1]
        if (isinstance(last, ast.Assign) and len(last.targets) == 1
                and isinstance(last.targets[0], ast.Name)
                and last.targets[0].id.endswith("_ok")
                and getattr(last.value, "value", None) is True):
            marked.add(last.targets[0].id)
    assert marked == {"positions_ok", "orders_ok"}, marked


def test_17_losing_the_connection_clears_the_flags():
    """AST: the reconnect handler must set both flags False. A stale True would let a
    disconnected reader keep testifying with its last good answer."""
    src = (REPO / "monitor/backend/ibkr_reader.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_reader_thread")
    cleared = False
    for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
        if not (isinstance(call.func, ast.Name) and call.func.id == "_set"):
            continue
        if not call.args or not isinstance(call.args[0], ast.Dict):
            continue
        d = {k.value: getattr(v, "value", "?") for k, v in
             zip(call.args[0].keys, call.args[0].values) if isinstance(k, ast.Constant)}
        if d.get("connected") is False:
            assert d.get("positions_ok") is False and d.get("orders_ok") is False, d
            cleared = True
    assert cleared, "no _set({connected: False, ...}) call was found to check"


# ══════════════════════════════════════════════════════════════════════════════
# the record and the gate
# ══════════════════════════════════════════════════════════════════════════════

def test_18_no_record_is_unknown_not_pass(tmp_path):
    r = b1.latest(tmp_path)
    assert r.status == b1.UNKNOWN
    assert r.code == b1.NO_RECORD


def test_19_a_recorded_pass_is_read_back(tmp_path):
    written = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                         evidence(positions=[], orders=[]))
    b1.record(written, tmp_path, source="test")
    back = b1.latest(tmp_path)
    assert back.status == b1.PASS and back.code == b1.OK


def test_20_a_stale_record_stops_counting(tmp_path):
    written = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                         evidence(positions=[], orders=[]))
    b1.record(written, tmp_path, source="test")
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=b1.MAX_RECORD_AGE_HOURS + 1)
    back = b1.latest(tmp_path, now=later)
    assert back.status == b1.UNKNOWN
    assert back.code == b1.RECORD_STALE


def test_21_a_record_whose_status_and_code_disagree_is_refused(tmp_path):
    d = tmp_path / b1.B1_DIR
    d.mkdir(parents=True)
    (d / "track1_b1_20260826.jsonl").write_text(json.dumps({
        "status": "PASS", "code": b1.LEGACY_BOOK_POSITIONS, "detail": "forged",
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}) + "\n", encoding="utf-8")
    back = b1.latest(tmp_path)
    assert back.status == b1.UNKNOWN
    assert back.code == b1.RECORD_UNREADABLE


def test_22_a_result_cannot_file_a_failure_as_a_pass():
    with pytest.raises(ValueError):
        b1.B1Result(status=b1.PASS, code=b1.LEGACY_BOOK_POSITIONS, detail="x")
    with pytest.raises(ValueError):
        b1.B1Result(status=b1.UNKNOWN, code="not_a_code", detail="x")


def test_23_every_declared_code_carries_exactly_one_status():
    for code, status in b1.CODE_STATUS.items():
        assert status in b1.STATUSES, (code, status)
        b1.B1Result(status=status, code=code, detail="x")


def test_24_every_code_the_module_names_is_in_the_table():
    """A code constant nothing can emit, or that the table does not know, is a check that
    reads as running and does not."""
    named = {v for k, v in vars(b1).items()
             if k.isupper() and isinstance(v, str) and not k.startswith("_")
             and k not in ("PASS", "FAIL", "UNKNOWN", "SCHEMA", "B1_DIR",
                           "BOOK_READ", "BOOK_ABSENT", "BOOK_BAD")}
    assert named == set(b1.CODE_STATUS), named ^ set(b1.CODE_STATUS)


# ══════════════════════════════════════════════════════════════════════════════
# 8. the confirmation file cannot bypass the measurement
# ══════════════════════════════════════════════════════════════════════════════

B1_ID = "B1_broker_account_or_legacy_retirement"


def _b1():
    return g.BLOCKERS[B1_ID]


def _conf(**flags):
    return g.Confirmations(flags, "tester", "2026-08-26", "test")


def test_25_a_signature_alone_no_longer_releases_b1(monkeypatch):
    """This is the behaviour change. Before Stage 5ZQ this returned True."""
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (False, "UNKNOWN: nobody asked"))
    assert _b1().released(_conf(legacy_retired_confirmed=True)) is False
    assert _b1().released(_conf(separate_account_confirmed=True)) is False


def test_26_a_signature_plus_a_passing_measurement_releases_it(monkeypatch):
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (True, "PASS"))
    assert _b1().released(_conf(legacy_retired_confirmed=True)) is True


def test_27_the_measurement_alone_does_not_release_it(monkeypatch):
    """Proving the account flat this morning does not decide which route owns the login."""
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (True, "PASS"))
    assert _b1().released(_conf()) is False


def test_28_the_waiver_alone_releases_nothing(monkeypatch):
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (False, "UNKNOWN"))
    assert _b1().released(_conf(b1_measurement_waived=True)) is False


def test_29_a_waiver_beside_a_decision_bypasses_the_measurement(monkeypatch):
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (False, "UNKNOWN"))
    assert _b1().released(_conf(legacy_retired_confirmed=True,
                                b1_measurement_waived=True)) is True


def test_30_a_waiver_must_say_why(tmp_path):
    p = tmp_path / "conf.json"
    base = {"schema_version": 1, "confirmed_by": "someone", "confirmed_at": "2026-08-26",
            "legacy_retired_confirmed": True, "b1_measurement_waived": True}
    p.write_text(json.dumps(base), encoding="utf-8")
    conf, errs = g.load_confirmations(p)
    assert errs, "a waiver with no note must be refused"
    assert conf.get("legacy_retired_confirmed") is False, "an invalid file grants nothing"

    p.write_text(json.dumps({**base, "note": "Gateway offline for maintenance"}),
                 encoding="utf-8")
    conf, errs = g.load_confirmations(p)
    assert errs == []
    assert conf.get("b1_measurement_waived") is True


def test_31_the_registry_still_passes_its_own_structural_rules():
    assert g.self_check() == []


def test_32_the_ledger_publishes_the_required_measurement():
    row = next(b for b in g.as_ledger()["blockers"] if b["id"] == B1_ID)
    # Stage 5ZZK renamed this to the composite that subsumes it — same requirement plus the
    # route stamp and the account baseline. The property is that the ledger PUBLISHES what
    # B1 additionally requires, whatever it is called, and that the name resolves.
    assert row["also_requires_measurement"] == "b1_decision_evidence"
    assert row["also_requires_measurement"] in g.MEASUREMENTS
    assert row["waiver_flag"] == "b1_measurement_waived"
    assert set(row["required_measurement_now"]) == {"satisfied", "detail"}


def test_33_adding_the_requirement_can_only_tighten_a_gate(monkeypatch):
    """Every OTHER blocker must behave exactly as before: `also_requires_measurement` is
    empty for them, so `released` must still be signature-OR-measurement."""
    for bid, blk in g.BLOCKERS.items():
        if bid == B1_ID:
            continue
        assert blk.also_requires_measurement == "", bid
        assert blk.waiver_flag == "", bid


# ══════════════════════════════════════════════════════════════════════════════
# 9–10. the surroundings must not have moved
# ══════════════════════════════════════════════════════════════════════════════

def test_34_legacy_drain_safety_is_still_scheduled_in_track1_only_mode():
    """The legacy safety net drains the legacy book and must stay registered until B1 is
    closed. `make_scheduler` builds and registers jobs; it starts nothing and opens no
    connection."""
    from global_index import run_scheduler as rs

    jobs = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                            track1_shadow=True, track1_only=True).get_jobs()}
    legacy_safety = {j for j in jobs
                     if ("stop_repair" in j or "max_hold" in j or "maxhold" in j)
                     and not j.startswith("track1_")}
    assert legacy_safety, f"legacy safety disappeared from track1-only mode: {sorted(jobs)[:20]}"


def test_35_track1_orders_are_still_impossible():
    """Restated by Stage 5ZZK. The confirmation now exists — the operator placed it — so the
    two absence assertions became false by design. Orders being impossible never depended on
    that file being missing; it depends on the evidence gate, which is what is asserted."""
    assert g.may_enable_orders()[0] is False
    assert "PAPER_SHADOW_EVIDENCE" in [x.id for x in g.blocking()]
    assert not (REPO / "global_index" / g.CONFIRMATION_PATH).exists()


def test_36_b1_is_closed_by_a_decision_AND_a_measurement():
    """Restated by Stage 5ZZK, and deliberately not deleted.

    This said "B1 still blocks today", which was true for as long as nobody had decided. It
    is now closed — and the thing worth guarding is WHY: never by a signature alone. Take the
    measurement away and B1 must come straight back.
    """
    assert B1_ID not in [x.id for x in g.blocking()]
    conf, errors = g.load_confirmations(g.CONFIRMATION_PATH)
    assert errors == [] and conf.get("legacy_retired_confirmed") is True
    ok, why = g.b1_decision_evidence(".")
    assert ok is True, why
    assert B1_ID in [x.id for x in g.blocking(g.NO_CONFIRMATIONS)], (
        "B1 opens without the decision, so the signature is doing nothing")


def test_37_the_live_frame_gate_was_not_weakened():
    """It closed on the audit tool the moment that tool was named `track1_b1_audit`, which is
    the gate working. The tool moved out of the route namespace; the gate did not move."""
    released, detail = g.live_frame_wiring()
    assert released is True, detail
    assert "track1_b1" not in detail, detail


def test_38_the_measurement_module_opens_no_connection_and_the_tool_does():
    """AST, both directions. The module the live-frame gate scans must not construct a
    broker; the operator tool outside that namespace must — otherwise it asks nobody."""
    def names(path):
        return {n.id for n in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8")))
                if isinstance(n, ast.Name)} | {
               n.attr for n in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8")))
               if isinstance(n, ast.Attribute)}

    measured = names(REPO / "global_index/track1_b1.py")
    assert "IBKRBroker" not in measured
    assert not (measured & set(g.LIVE_BAR_NAMES)), measured & set(g.LIVE_BAR_NAMES)

    tool = names(REPO / "global_index/b1_audit.py")
    assert "IBKRBroker" in tool, "the audit tool no longer asks the broker anything"
    assert not (REPO / "global_index/track1_b1_audit.py").exists(), \
        "the tool is back inside the namespace the live-frame gate scans"


def test_39_the_audit_tool_writes_nothing_without_record(tmp_path, monkeypatch):
    from global_index import b1_audit

    monkeypatch.chdir(tmp_path)
    (tmp_path / "live_positions.json").write_text(
        json.dumps({"positions": []}), encoding="utf-8")
    (tmp_path / "live_positions.track1.json").write_text(
        json.dumps({"positions": []}), encoding="utf-8")
    rc = b1_audit.main(["--root", str(tmp_path), "--broker", "none"])
    assert rc == 2, "no broker evidence must exit UNKNOWN, not PASS"
    assert not (tmp_path / b1.B1_DIR).exists(), "the audit wrote evidence without --record"


def test_40_the_audit_tool_exit_code_separates_the_three_answers(tmp_path, monkeypatch):
    """A caller that cannot read the text can still tell flat from not-flat from cannot-tell."""
    from global_index import b1_audit

    monkeypatch.setattr(b1_audit.b1, "measure",
                        lambda *a, **k: b1.B1Result(b1.FAIL, b1.LEGACY_BOOK_POSITIONS, "x"))
    (tmp_path / "live_positions.json").write_text(
        json.dumps({"positions": []}), encoding="utf-8")
    (tmp_path / "live_positions.track1.json").write_text(
        json.dumps({"positions": []}), encoding="utf-8")
    assert b1_audit.main(["--root", str(tmp_path), "--broker", "none"]) == 1


def test_41_ops_status_reports_b1_without_opening_a_connection(monkeypatch):
    import monitor.ops as ops

    calls = []
    monkeypatch.setattr(b1, "latest",
                        lambda root=".", **k: (calls.append(root)
                                               or b1.B1Result(b1.PASS, b1.OK, "flat")))
    got = ops._b1_status()
    assert got["status"] == "PASS"
    assert got["line"] == "Legacy book flat, Track 1 book flat, broker flat, no working orders."
    assert calls, "ops must actually read the record rather than assuming"


def test_42_ops_b1_status_fails_to_unknown(monkeypatch):
    import monitor.ops as ops

    def boom(*a, **k):
        raise RuntimeError("record gone")

    monkeypatch.setattr(b1, "latest", boom)
    got = ops._b1_status()
    assert got["status"] == "UNKNOWN"
    assert got["status"] != "PASS"


# ══════════════════════════════════════════════════════════════════════════════
# the orphan helpers, on their own
# ══════════════════════════════════════════════════════════════════════════════

def test_43_an_order_on_a_held_instrument_is_not_an_orphan(tmp_path):
    held = book(tmp_path, "legacy.json", [{"inst": "MES"}])
    assert b1.orphan_orders([A_STOP], [], [held]) == []


def test_44_unprotected_positions_finds_the_naked_one():
    naked = b1.unprotected_positions(
        [{"instrument": "MES", "direction": "SHORT", "contracts": 1},
         {"instrument": "MYM", "direction": "LONG", "contracts": 1}],
        [{"instrument": "MES", "order_type": "STP"}])
    assert [n["instrument"] for n in naked] == ["MYM"]


def test_45_a_broker_position_reports_which_of_them_are_naked(tmp_path):
    r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                   evidence(positions=[A_POSITION], orders=[]))
    assert r.code == b1.BROKER_POSITIONS
    assert len(r.findings["unprotected"]) == 1
    assert "no working stop" in r.detail


def test_46_the_measurement_never_returns_pass_on_a_nonzero_account(tmp_path):
    """The blanket rule, checked across every shape rather than one example."""
    shapes = [
        dict(positions=[A_POSITION], orders=[]),
        dict(positions=[A_POSITION], orders=[A_STOP]),
        dict(positions=[], orders=[A_STOP]),
        dict(positions=[A_POSITION, A_POSITION], orders=[A_STOP]),
    ]
    assert shapes, "the shape list must not be empty"
    for shape in shapes:
        r = b1.measure(flat_book(tmp_path, "legacy.json"), flat_book(tmp_path, "t1.json"),
                       evidence(**shape))
        assert r.status == b1.FAIL, (shape, r.status, r.code)
