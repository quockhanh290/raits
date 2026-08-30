"""Stage 5ZN — the stop the strategy decided on is written down, and the lifecycle has verbs.

Nothing here sends an order, constructs an IBKRBroker, or writes into the runtime tree. Every
journal, book and checkpoint path is under `tmp_path`; the fake broker raises if anything asks
it to send, so a send would fail loudly rather than pass quietly.

The gap, measured before it was built
--------------------------------------
`Candidate` carries `stop_price` — the strategy works it out and it survives admission — and
`candidate_to_order` builds an `Order` with nowhere to put it. `OrderRecord` had nowhere
either. So the planned stop reached the edge of the order path and was dropped, and the
protective stop was placed later by the safety sweep in another process, with nothing anywhere
holding both the intended price and the placed one.

An abandoned stop left by a close on 2026-08-10 filled and opened a position the opposite way.
That is why a stop with no record is an accounting hole rather than untidiness.
"""
from __future__ import annotations

import ast
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from global_index import track1_paper_executor as E              # noqa: E402
from global_index import track1_paper_order as po                # noqa: E402
from global_index import track1_planned_stop as ps               # noqa: E402
from global_index import track1_order_journal as journal         # noqa: E402
from global_index import track1_order_state as st                # noqa: E402
from global_index import track1_slots as ts                      # noqa: E402

REPO = Path(r"d:\raits")
_IMPORTED_AT = time.time()
DAY = "2026-08-26"


# ══════════════════════════════════════════════════════════════════════════════
# fakes — nothing here can reach a socket
# ══════════════════════════════════════════════════════════════════════════════

class Gate:
    allow_orders = True


class NeverSends:
    """Every capability the executor requires, and a send that fails loudly."""
    def send_order(self, order, *, on_submit=None):
        raise AssertionError("send_order was reached — this stage must send nothing")
    def get_positions(self): return None
    def get_open_orders(self): return None
    def get_order_status(self, order_id): return "NOT_FOUND"
    def find_execution(self, order_id, inst=None): return None
    def cancel_order(self, order_id): return False
    def place_stop(self, *a, **k):
        raise AssertionError("place_stop was reached — this stage must send nothing")


@dataclass
class Cand:
    trade_id: str = "t-1"
    sleeve: str = "roska4_swing"
    instrument: str = "MES"
    direction: str = "long"
    qty: int = 1
    entry_price: float | None = 5000.0
    stop_price: float | None = 4950.0
    source: str = "test"
    risk_dollars: float = 100.0
    meta: dict = field(default_factory=dict)


class Held:
    def __init__(self, instrument="MES", sleeve="roska4_swing"):
        self.instrument, self.sleeve = instrument, sleeve


def a_book(root: Path, *, positions=()) -> Path:
    p = root / ts.TRACK1_POSITIONS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                             "window": "live", "cut_instant": f"{DAY}T15:55:01-04:00",
                             "cur_day": DAY, "equity": 0.0,
                             "positions": list(positions)}), encoding="utf-8")
    return p


def a_position(inst="MES", sleeve="roska4_swing", qty=1) -> dict:
    return {"instrument": inst, "sleeve": sleeve, "direction": "long", "qty": qty,
            "entry_price": 5000.0, "stop_price": 4950.0,
            "entry_time": f"{DAY}T14:05:00"}


@pytest.fixture
def ex(tmp_path):
    return E.Track1OrderExecutor(broker=NeverSends(), gate=Gate(), journal_root=str(tmp_path))


def journal_rows(root: Path) -> list:
    d = root / "global_index" / "track1_runtime" / "orders"
    if not d.is_dir():
        return []
    return [json.loads(l) for f in sorted(d.glob("*.jsonl"))
            for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# A. the planned stop is CARRIED, never computed
# ══════════════════════════════════════════════════════════════════════════════

def test_1_an_admitted_entry_produces_a_record_carrying_the_stop_fields():
    order, plan = po.plan_entry(Cand(), ref_day=DAY, slot_id="TRACK1_SWING_1405",
                                params_hash="sha256:abc", stop_type="fixed_2x_atr")
    assert plan.stop_price == 4950.0
    assert plan.stop_distance == 50.0
    for f in ("inst", "tradable_symbol", "direction", "qty", "stop_price", "stop_type",
              "stop_distance", "entry_price", "ref_day", "sleeve", "slot_id", "params_hash"):
        assert hasattr(plan, f), f
    assert plan.slot_id == "TRACK1_SWING_1405" and plan.params_hash == "sha256:abc"
    assert order.inst == "MES" and order.action == "OPEN"


def test_the_stop_is_copied_not_recomputed():
    """No arithmetic on the price itself — an odd stop the strategy chose survives intact."""
    plan = ps.from_candidate(Cand(stop_price=4937.63), ref_day=DAY)
    assert plan.stop_price == 4937.63


def test_the_module_does_no_stop_arithmetic_beyond_the_distance():
    """A second implementation beside the one that trades is how the planned stop and the
    meant stop quietly become two numbers. Checked by AST over the module's own operators."""
    tree = ast.parse((REPO / "global_index" / "track1_planned_stop.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "from_candidate")
    ops = [n for n in ast.walk(fn) if isinstance(n, ast.BinOp)]
    # exactly the two subtractions that make `stop_distance`, and nothing else
    assert all(isinstance(o.op, ast.Sub) for o in ops), [type(o.op).__name__ for o in ops]
    assert len(ops) == 2, len(ops)


@pytest.mark.parametrize("kw,code", [
    ({"stop_price": None}, ps.NO_STOP_PRICE),
    ({"stop_price": "not a price"}, ps.STOP_NOT_A_NUMBER),
    ({"stop_price": float("nan")}, ps.STOP_NOT_A_NUMBER),
    ({"qty": 0}, ps.NO_QTY),
    ({"qty": None}, ps.NO_QTY),
    ({"stop_price": 5100.0}, ps.STOP_WRONG_SIDE),
])
def test_2_an_entry_without_a_usable_stop_refuses(kw, code):
    with pytest.raises(ps.PlannedStopMissing) as exc:
        ps.from_candidate(Cand(**kw), ref_day=DAY)
    assert exc.value.code == code


def test_a_long_whose_stop_sits_above_entry_is_refused_before_the_broker_sees_it():
    """It is not a stop, it is a target, and it would trigger at once."""
    with pytest.raises(ps.PlannedStopMissing) as exc:
        po.plan_entry(Cand(stop_price=5100.0), ref_day=DAY)
    assert exc.value.code == ps.STOP_WRONG_SIDE


def test_2b_assert_sendable_refuses_a_missing_plan():
    order = po.candidate_to_order(Cand(), ref_day=DAY)
    with pytest.raises(ps.PlannedStopMissing):
        ps.assert_sendable(order, None)


def test_a_plan_for_another_instrument_protects_nothing():
    order = po.candidate_to_order(Cand(instrument="MES"), ref_day=DAY)
    plan = ps.from_candidate(Cand(instrument="MNQ"), ref_day=DAY)
    with pytest.raises(ps.PlannedStopMissing):
        ps.assert_sendable(order, plan)


def test_a_plan_covering_fewer_contracts_than_the_order_is_refused():
    order = po.candidate_to_order(Cand(qty=2), ref_day=DAY)
    plan = ps.from_candidate(Cand(qty=1), ref_day=DAY)
    with pytest.raises(ps.PlannedStopMissing) as exc:
        ps.assert_sendable(order, plan)
    assert "partly-protected" in exc.value.detail


# ══════════════════════════════════════════════════════════════════════════════
# B. the field additions are append-only
# ══════════════════════════════════════════════════════════════════════════════

def test_3_the_stop_fields_are_appended_last_and_default(monkeypatch):
    import dataclasses
    for cls, names in ((st.OrderRecord, ["planned_stop_price", "planned_stop_type",
                                         "planned_stop_distance"]),
                       (journal.JournalRecord, ["planned_stop_price", "planned_stop_type",
                                                "planned_stop_distance", "qty"])):
        fields = [f.name for f in dataclasses.fields(cls)]
        assert fields[-len(names):] == names, fields
        for f in dataclasses.fields(cls):
            if f.name in names:
                assert f.default is not dataclasses.MISSING, f.name


def test_3b_a_caller_written_before_this_stage_still_constructs():
    r = st.OrderRecord("t", "roska4_swing", "MES", "MES", "long", 1, st.INTENDED, DAY)
    assert r.planned_stop_price is None
    j = journal.JournalRecord(idempotency_key="k", state=st.INTENDED, ref_day=DAY,
                              sleeve="s", instrument="MES", tradable_symbol="MES",
                              action="OPEN", candidate_id="c", created_at="t", slot_id="x")
    assert j.planned_stop_price is None and j.qty == 0


def test_3c_the_legacy_order_and_fill_shapes_are_untouched():
    """`Order` and `Fill` are shared with the legacy route. Neither gained a stop field."""
    import dataclasses
    from global_index.broker import Order, Fill
    assert not any("stop" in f.name for f in dataclasses.fields(Order)), \
        [f.name for f in dataclasses.fields(Order)]
    assert not any("planned" in f.name for f in dataclasses.fields(Fill))


# ══════════════════════════════════════════════════════════════════════════════
# C. close_position
# ══════════════════════════════════════════════════════════════════════════════

def test_4_close_refuses_when_the_book_does_not_exist(ex, tmp_path):
    with pytest.raises(E.PaperExecutorRefused) as exc:
        ex.close_position(Held(), "max_hold", ref_day=DAY)
    assert exc.value.code == E.NO_BOOK
    assert journal_rows(tmp_path) == [], "a refused close left a journal row"


def test_4b_close_refuses_when_the_book_holds_no_such_position(ex, tmp_path):
    a_book(tmp_path, positions=[])
    with pytest.raises(E.PaperExecutorRefused) as exc:
        ex.close_position(Held(), "max_hold", ref_day=DAY)
    assert exc.value.code == E.NO_SUCH_POSITION
    assert journal_rows(tmp_path) == []


def test_4c_close_refuses_for_a_different_instrument(ex, tmp_path):
    a_book(tmp_path, positions=[a_position("MNQ")])
    with pytest.raises(E.PaperExecutorRefused):
        ex.close_position(Held("MES"), "max_hold", ref_day=DAY)


def test_5_a_close_reduces_exposure_only_and_sends_nothing(ex, tmp_path):
    a_book(tmp_path, positions=[a_position()])
    intent = ex.close_position(Held(), "max_hold", ref_day=DAY)
    assert intent.kind == "close"
    assert intent.reduces_exposure is True
    assert intent.sent is False
    assert intent.order.action == "CLOSE"
    rows = journal_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["state"] == st.INTENDED
    assert rows[0]["planned_stop_price"] is None, "a close carries no protection of its own"


# ══════════════════════════════════════════════════════════════════════════════
# D. place_protective_stop
# ══════════════════════════════════════════════════════════════════════════════

def test_6_the_protective_stop_refuses_without_a_plan(ex, tmp_path):
    with pytest.raises(E.PaperExecutorRefused) as exc:
        ex.place_protective_stop(Held(), ref_day=DAY)
    assert exc.value.code == E.NO_PLANNED_STOP
    assert journal_rows(tmp_path) == []


def test_6b_with_a_plan_it_journals_the_price_and_sends_nothing(ex, tmp_path):
    _order, plan = po.plan_entry(Cand(), ref_day=DAY, stop_type="fixed_2x_atr")
    intent = ex.place_protective_stop(Held(), plan=plan, ref_day=DAY)
    assert intent.kind == "protective_stop" and intent.sent is False
    rows = journal_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["planned_stop_price"] == 4950.0
    assert rows[0]["planned_stop_type"] == "fixed_2x_atr"
    assert rows[0]["planned_stop_distance"] == 50.0
    assert rows[0]["qty"] == 1
    assert rows[0]["action"] == "STOP"


def test_a_plan_carrying_no_price_is_refused(ex):
    bad = ps.PlannedStop(inst="MES", tradable_symbol="MES", direction="long", qty=1,
                         stop_price=float("nan"))
    with pytest.raises(E.PaperExecutorRefused):
        ex.place_protective_stop(Held(), plan=bad, ref_day=DAY)


# ══════════════════════════════════════════════════════════════════════════════
# E. switch_same_symbol
# ══════════════════════════════════════════════════════════════════════════════

def test_7_a_switch_journals_close_and_open_as_separate_legs(ex, tmp_path):
    a_book(tmp_path, positions=[a_position()])

    class Dec:
        candidate = Cand(trade_id="t-new")

    out = ex.switch_same_symbol(Dec(), Held(), ref_day=DAY, slot_id="TRACK1_SWING_1410")
    assert out.close.kind == "close" and out.open.kind == "open"
    assert out.sent is False
    rows = journal_rows(tmp_path)
    assert len(rows) == 2, rows
    assert sorted(r["action"] for r in rows) == ["CLOSE", "OPEN"]
    open_row = next(r for r in rows if r["action"] == "OPEN")
    assert open_row["planned_stop_price"] == 4950.0, "the open leg lost its plan"
    assert len({r["idempotency_key"] for r in rows}) == 2, "the legs share one key"


def test_7b_a_switch_to_a_different_symbol_is_refused(ex, tmp_path):
    a_book(tmp_path, positions=[a_position("MES")])

    class Dec:
        candidate = Cand(instrument="MNQ")

    with pytest.raises(E.PaperExecutorRefused) as exc:
        ex.switch_same_symbol(Dec(), Held("MES"), ref_day=DAY)
    assert exc.value.code == E.NOT_SAME_SYMBOL


def test_7c_the_close_leg_is_journalled_before_the_open_leg(ex, tmp_path):
    """A switch that opened before it closed would double exposure for the gap."""
    a_book(tmp_path, positions=[a_position()])

    class Dec:
        candidate = Cand()

    ex.switch_same_symbol(Dec(), Held(), ref_day=DAY)
    rows = journal_rows(tmp_path)
    assert rows[0]["action"] == "CLOSE" and rows[1]["action"] == "OPEN"


def test_7d_a_switch_with_no_position_to_displace_refuses_before_journalling(ex, tmp_path):
    a_book(tmp_path, positions=[])

    class Dec:
        candidate = Cand()

    with pytest.raises(E.PaperExecutorRefused):
        ex.switch_same_symbol(Dec(), Held(), ref_day=DAY)
    assert journal_rows(tmp_path) == [], "a refused switch left half a record"


# ══════════════════════════════════════════════════════════════════════════════
# F. nothing sends, nothing imports a broker library
# ══════════════════════════════════════════════════════════════════════════════

def test_8_the_executor_imports_no_ib_insync_and_names_no_ibkr_broker():
    tree = ast.parse((REPO / "global_index" / "track1_paper_executor.py").read_text(
        encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any("ib_insync" in m for m in mods), sorted(mods)
    assert not any("ibkr_broker" in m for m in mods), sorted(mods)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "IBKRBroker" not in names


@pytest.mark.parametrize("verb", ["close_position", "place_protective_stop",
                                  "switch_same_symbol"])
def test_the_three_new_verbs_never_call_the_broker(verb):
    """Structural: none of them touches `self.broker` at all."""
    import inspect
    src = inspect.getsource(getattr(E.Track1OrderExecutor, verb))
    tree = ast.parse(src.lstrip())
    attrs = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute)
             and n.attr == "broker"]
    assert attrs == [], f"{verb} reaches for the broker"


def test_9_the_live_slot_path_still_cannot_send_orders():
    from global_index import run_live_day_track1 as R
    b = R.NoOrderBroker()
    for call in (lambda: b.send_order(object()),
                 lambda: b.cancel_order("x"),
                 lambda: b.get_equity()):
        with pytest.raises(RuntimeError):
            call()


def test_10_the_slot_path_builds_no_order_broker_by_default():
    import inspect
    from global_index import run_live_day_track1 as R
    tree = ast.parse(inspect.getsource(R))
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and isinstance(n.value, ast.Call)
               and getattr(n.value.func, "id", "") == "NoOrderBroker"]
    assert assigns, "the slot path no longer builds a NoOrderBroker"
    named = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "IBKRBroker" not in named, "the slot path can now construct a live broker"


def test_11_no_allow_orders_appears_in_anything_this_stage_touched():
    for rel in ("global_index/track1_planned_stop.py",
                "global_index/track1_paper_executor.py",
                "global_index/track1_paper_order.py",
                "global_index/track1_order_journal.py",
                "global_index/track1_order_state.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        lits = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not any("--allow-orders" in l for l in lits), rel


# ══════════════════════════════════════════════════════════════════════════════
# G. the book — carried, never synthesised over
# ══════════════════════════════════════════════════════════════════════════════

def test_the_executor_book_path_is_the_one_the_system_writes():
    """It was `global_index/live_positions.track1.json` — a path the book has never occupied.

    `read_book` treats a missing file as an empty book, so that constant made
    `reconcile_at_startup` compare an ALWAYS-empty book against the broker and conclude the
    route was flat whatever it held. It never fired because nothing imports the executor.
    """
    assert E.BOOK_PATH == ts.TRACK1_POSITIONS_PATH == "live_positions.track1.json"
    from global_index import track1_shadow_acceptance as acc
    assert acc.CHECKPOINT_BOOK_PATH == E.BOOK_PATH


def test_12_a_window_close_carries_an_existing_book_forward(tmp_path):
    import pandas as pd
    from global_index import run_live_day_track1 as R
    bk, ck = tmp_path / "book.json", tmp_path / "ck.json"
    bk.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                              "window": "live", "cut_instant": "2026-08-25T15:55:01-04:00",
                              "cur_day": "2026-08-25", "equity": 0.0,
                              "positions": [a_position()]}), encoding="utf-8")
    out = R.write_route_checkpoint("roska4_swing",
                                   now_et=pd.Timestamp(f"{DAY} 15:55:01"),
                                   regime_csv="spy_daily_live.csv", data_paths={}, frames={},
                                   path=str(ck), book_path=str(bk))
    after = json.loads(bk.read_text(encoding="utf-8"))
    assert len(after["positions"]) == 1, "the close erased a position"
    assert after["cut_instant"][:10] == DAY, "the book was not restamped"
    assert out["positions_carried"] == 1
    assert out["book_carried_from"] == str(bk)


def test_12b_a_first_ever_close_creates_a_flat_book_and_says_so(tmp_path):
    import pandas as pd
    from global_index import run_live_day_track1 as R
    ck, bk = tmp_path / "ck.json", tmp_path / "book.json"
    out = R.write_route_checkpoint("roska4_swing", now_et=pd.Timestamp(f"{DAY} 15:55:01"),
                                   regime_csv="spy_daily_live.csv", data_paths={}, frames={},
                                   path=str(ck), book_path=str(bk))
    assert out["book_carried_from"] is None, "a created book claimed it was carried"
    assert out["positions_carried"] == 0


def test_12c_an_unreadable_book_refuses_the_write_rather_than_erasing_it(tmp_path):
    import pandas as pd
    from global_index import run_live_day_track1 as R
    bk, ck = tmp_path / "book.json", tmp_path / "ck.json"
    bk.write_text("{ truncated", encoding="utf-8")
    with pytest.raises(RuntimeError):
        R.write_route_checkpoint("roska4_swing", now_et=pd.Timestamp(f"{DAY} 15:55:01"),
                                 regime_csv="spy_daily_live.csv", data_paths={}, frames={},
                                 path=str(ck), book_path=str(bk))
    assert bk.read_text(encoding="utf-8") == "{ truncated", "the bad book was overwritten"


def test_12d_a_book_stamped_with_another_route_is_refused(tmp_path):
    import pandas as pd
    from global_index import run_live_day_track1 as R
    bk, ck = tmp_path / "book.json", tmp_path / "ck.json"
    bk.write_text(json.dumps({"schema_version": 2, "route": "legacy_r4", "positions": []}),
                  encoding="utf-8")
    with pytest.raises(RuntimeError):
        R.write_route_checkpoint("roska4_swing", now_et=pd.Timestamp(f"{DAY} 15:55:01"),
                                 regime_csv="spy_daily_live.csv", data_paths={}, frames={},
                                 path=str(ck), book_path=str(bk))


def test_11b_the_book_advances_only_on_a_confirmed_fill(ex, tmp_path):
    """Intending a close leaves the book exactly as it was."""
    bk = a_book(tmp_path, positions=[a_position()])
    before = bk.read_text(encoding="utf-8")
    ex.close_position(Held(), "max_hold", ref_day=DAY)
    assert bk.read_text(encoding="utf-8") == before, "an INTENT moved the book"


def test_13_reconcile_answers_match_mismatch_or_unknown(ex, tmp_path):
    a_book(tmp_path, positions=[a_position()])
    match = ex.reconcile_at_startup(
        broker_positions=[st.Position(instrument="MES", direction="long", contracts=1)],
        shared_account=False)
    assert match.verdict == st.MATCH, match
    assert match.blocks_entries is False

    mismatch = ex.reconcile_at_startup(
        broker_positions=[st.Position(instrument="MES", direction="long", contracts=2)],
        shared_account=False)
    assert mismatch.verdict == st.MISMATCH
    assert mismatch.blocks_entries is True

    unknown = ex.reconcile_at_startup(broker_positions=None, shared_account=False)
    assert unknown.verdict == st.RECONCILE_UNKNOWN
    assert unknown.blocks_entries is True
    assert unknown.allows_exits is True, "exits must stay open while the book is confused"
    assert unknown.verdict != st.MATCH, "UNKNOWN became MATCH"


def test_12e_missing_book_is_not_read_as_a_flat_match(ex, tmp_path):
    """`read_book` calls a missing file empty, which is right for a route that has held
    nothing — and is exactly why the executor's book path had to be the real one."""
    assert not (tmp_path / ts.TRACK1_POSITIONS_PATH).exists()
    positions, detail = ex._book_positions()
    assert positions == [] and "does not exist" in detail


# ══════════════════════════════════════════════════════════════════════════════
# H. legacy and identity untouched
# ══════════════════════════════════════════════════════════════════════════════

def test_14_the_legacy_runner_and_safety_entry_points_were_not_touched():
    """The stop fields live on Track 1 records. Nothing legacy reads them."""
    for rel in ("global_index/run_live_day.py", "global_index/run_stop_repair.py",
                "global_index/run_maxhold_exit.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        lits = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not any("planned_stop" in l for l in lits), rel
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "planned_stop_price" not in names, rel


def test_15_the_strategy_identity_is_unaffected():
    from global_index import track1_params as tp
    from global_index import route_checkpoint as rc
    from global_index.run_live_day_track1 import default_data_paths
    dp = default_data_paths()
    before = {(s, i): tp.sleeve_identity(s, i, regime_csv="spy_daily_live.csv",
                                         data_path=dp[i], fill_law=tp.LIVE_FILL_LAW)
              for s in rc.CHECKPOINTED_SLEEVES for i in tp.SLEEVE_INSTRUMENTS.get(s, ())}
    po.plan_entry(Cand(), ref_day=DAY)          # exercise the new path
    after = {(s, i): tp.sleeve_identity(s, i, regime_csv="spy_daily_live.csv",
                                        data_path=dp[i], fill_law=tp.LIVE_FILL_LAW)
             for s in rc.CHECKPOINTED_SLEEVES for i in tp.SLEEVE_INSTRUMENTS.get(s, ())}
    assert before == after


def test_15b_the_planned_stop_module_touches_no_signal_or_rule_module():
    tree = ast.parse((REPO / "global_index" / "track1_planned_stop.py").read_text(
        encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    bad = [m for m in mods if any(k in m for k in ("signal", "normal_r4", "calm", "sleeves"))]
    assert bad == [], bad


# ══════════════════════════════════════════════════════════════════════════════
# I. reporting says planned-stop ready, never broker-stop verified
# ══════════════════════════════════════════════════════════════════════════════

def test_the_report_separates_planned_from_broker_verified(tmp_path):
    from global_index import track1_report as tr
    life = tr.report(tmp_path)["lifecycle"]
    assert life["planned_stop_ready"] is True
    assert life["broker_stop_verified"] is False
    assert life["verbs_send_orders"] is False
    assert all(life["lifecycle_verbs"].values()), life["lifecycle_verbs"]
    assert "needs paper" in life["broker_stop_reason"]


def test_the_reports_declared_verbs_match_the_real_executor():
    """`track1_report` declares the verb names instead of importing the executor, so that
    nothing which runs holds an import of the order path. The claim is checked HERE, where a
    test may import anything — otherwise the declaration is a sentence nobody verifies."""
    from global_index import track1_report as tr
    for name in tr.LIFECYCLE_VERBS:
        assert hasattr(E.Track1OrderExecutor, name), name
    assert set(tr.LIFECYCLE_VERBS) == {"open_position", "close_position",
                                       "place_protective_stop", "switch_same_symbol"}


def test_the_report_still_imports_nothing_from_the_order_path():
    tree = ast.parse((REPO / "global_index" / "track1_report.py").read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    bad = [m for m in mods if "paper_executor" in m or "order_journal" in m
           or "order_state" in m]
    assert bad == [], bad


def test_the_report_never_claims_a_broker_stop_anywhere(tmp_path):
    from global_index import track1_report as tr
    payload = json.dumps(tr.report(tmp_path))
    assert '"broker_stop_verified": true' not in payload.lower()
    assert '"broker_verified": true' not in payload.lower()


# ══════════════════════════════════════════════════════════════════════════════
# J. nothing real was touched
# ══════════════════════════════════════════════════════════════════════════════

def test_orders_are_still_impossible():
    from global_index import track1_gates as g
    allowed, reasons = g.may_enable_orders()
    assert allowed is False
    ids = [r.split(":")[0] for r in reasons]
    for want in ("B1_broker_account_or_legacy_retirement", "PAPER_SHADOW_EVIDENCE"):
        assert want in ids, ids


def test_no_production_artefact_was_written_by_this_run():
    for name in ("live_positions.track1.json", "global_index/replay_checkpoint.track1.json",
                 "global_index/track1_runtime/trade_log.track1.jsonl", "trade_log.jsonl",
                 "global_index/preflight_state.json"):
        p = REPO / name
        if p.exists():
            assert p.stat().st_mtime < _IMPORTED_AT, name


def test_no_real_order_journal_was_created():
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists(), (
        "a real order journal directory appeared")


def test_no_confirmation_file_appeared():
    assert not (REPO / "track1_go_live_confirmation.json").exists()


def test_the_preflight_record_is_a_rolling_real_preflight_window():
    p = REPO / "global_index" / "preflight_state.json"
    if not p.exists():
        pytest.skip("no pre-flight record on this machine")
    days = sorted(json.loads(p.read_text(encoding="utf-8")))
    assert len(days) == 7, days
    assert days == sorted(set(days)), days
    assert all(d <= "2026-08-26" for d in days), days
    assert days[-1] == "2026-08-26", (
        "the real 13:45 ET pre-flight has run by this stage; the test pins the rolling "
        f"window property rather than the operator-restored list from before it ran: {days}")
