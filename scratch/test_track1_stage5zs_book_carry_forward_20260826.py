"""Stage 5ZS — a safety sweep stops being able to rewrite the route's book in legacy shape.

Measured 2026-08-26 09:31:13 ET. `TRACK1_MAX_HOLD_EXIT` ran with every route argument the
scheduler can give it — its own positions path, kill switch, lock file, client id 90, trade
log and `--route track1_candidate` — and then `FuturesRunner._persist_state` wrote the file in
the only shape it knew:

    schema_version 2 -> 1
    route, window, cut_instant, cur_day, equity, peak_equity, day_start_equity,
    booked_counter, counters                                          -> all nine dropped
    breaker: {peak_equity: 50000.0, last_broker_equity: 996881.46}    -> invented

`positions` was `[]` before and after, which is exactly why it was quiet — and why it would
not have been quiet on the first day the route held something.

Three layers are fixed and each is tested separately, because they fail independently:

  the writer         a route-stamped sweep preserves the envelope it read
  the carry-forward  a book at the route's path that is not the route's book is REFUSED,
                     and only declared fields are carried — never a foreign `breaker`
  the entry points   the book gets the same one-contract treatment the trade log got in 5ZG

Legacy is asserted unchanged at every layer.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from global_index import run_live_day_track1 as rl
from global_index import runner as R
from global_index import safety_book as sb
from global_index import track1_slots as ts

REPO = Path(r"d:\raits")
CUT = pd.Timestamp("2026-08-26 12:30:00-04:00")


# ══════════════════════════════════════════════════════════════════════════════
# the exact shape the 09:31 sweep left behind
# ══════════════════════════════════════════════════════════════════════════════

#: Copied field-for-field off the live file, so this suite reproduces the real event and not
#: an idea of it.
CORRUPT_0931 = {
    "schema_version": 1,
    "positions": [],
    "breaker": {"peak_equity": 50000.0, "max_dd_dollars": 0.0, "max_dd_pct": 0.0,
                "system_equity": 50000.0, "last_broker_equity": 996881.46},
}

VALID_BOOK = {
    "schema_version": 2, "route": "track1_candidate", "window": "live",
    "cut_instant": "2026-08-26T02:55:01.102676-04:00", "equity": 0.0,
    "cur_day": "2026-08-26", "peak_equity": 0.0, "day_start_equity": 0.0,
    "positions": [], "booked_counter": {}, "counters": {},
}


def write(tmp_path: Path, body: dict, name: str = "live_positions.track1.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════════════════════════
# A. carry-forward
# ══════════════════════════════════════════════════════════════════════════════

def test_1_the_0931_shape_is_refused_not_carried(tmp_path):
    """The regression that reproduces the live event."""
    p = write(tmp_path, CORRUPT_0931)
    with pytest.raises(RuntimeError) as e:
        rl._carry_forward_book(str(p), CUT)
    assert "route=None" in str(e.value)


def test_2_a_downgraded_schema_is_refused_even_when_route_survives(tmp_path):
    p = write(tmp_path, {**VALID_BOOK, "schema_version": 1})
    with pytest.raises(RuntimeError) as e:
        rl._carry_forward_book(str(p), CUT)
    assert "schema_version" in str(e.value)


def test_3_a_foreign_route_is_refused(tmp_path):
    p = write(tmp_path, {**VALID_BOOK, "route": "legacy"})
    with pytest.raises(RuntimeError):
        rl._carry_forward_book(str(p), CUT)


def test_4_a_valid_book_keeps_every_schema_2_field(tmp_path):
    p = write(tmp_path, {**VALID_BOOK, "equity": 123.5, "peak_equity": 7.0,
                         "day_start_equity": 5.0, "booked_counter": {"MES": 2},
                         "counters": {"x": 1}})
    state, src = rl._carry_forward_book(str(p), CUT)
    assert src == str(p)
    assert state["equity"] == 123.5
    assert state["peak_equity"] == 7.0
    assert state["day_start_equity"] == 5.0
    assert state["booked_counter"] == {"MES": 2}
    assert state["counters"] == {"x": 1}
    # and restamped for this cut
    assert state["schema_version"] == ts.TRACK1_BOOK_SCHEMA
    assert state["route"] == ts.TRACK1_ROUTE
    assert state["cut_instant"] == CUT.isoformat()


def test_5_a_foreign_breaker_block_is_never_inherited(tmp_path):
    """`dict(prev)` copied every key, so a legacy breaker with an account-scale equity
    travelled into the Track 1 book and would have stayed there."""
    p = write(tmp_path, {**VALID_BOOK,
                         "breaker": {"peak_equity": 50000.0, "last_broker_equity": 996881.46},
                         "some_other_legacy_field": 1})
    state, _ = rl._carry_forward_book(str(p), CUT)
    assert "breaker" not in state
    assert "some_other_legacy_field" not in state
    assert set(state) == set(VALID_BOOK)


def test_6_a_field_the_previous_book_lacked_comes_back_at_its_default(tmp_path):
    """Absent must not stay absent, or a reader has to guess which of the two it is."""
    thin = {k: v for k, v in VALID_BOOK.items() if k not in ("counters", "booked_counter")}
    p = write(tmp_path, thin)
    state, _ = rl._carry_forward_book(str(p), CUT)
    assert state["counters"] == {}
    assert state["booked_counter"] == {}


def test_7_a_missing_book_is_a_fresh_one_and_says_so(tmp_path):
    state, src = rl._carry_forward_book(str(tmp_path / "nope.json"), CUT)
    assert src is None, "a created book must not claim it was carried from somewhere"
    assert state["positions"] == []
    assert state["route"] == ts.TRACK1_ROUTE


def test_8_an_unreadable_book_is_refused_not_treated_as_empty(tmp_path):
    p = tmp_path / "b.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RuntimeError):
        rl._carry_forward_book(str(p), CUT)


def test_9_positions_are_carried_never_synthesised(tmp_path):
    pos = [{"inst": "MES", "direction": "SHORT", "contracts": 1}]
    p = write(tmp_path, {**VALID_BOOK, "positions": pos})
    state, _ = rl._carry_forward_book(str(p), CUT)
    assert state["positions"] == pos


# ══════════════════════════════════════════════════════════════════════════════
# B. the writer
# ══════════════════════════════════════════════════════════════════════════════

def _stub(tmp_path: Path, *, route, envelope):
    """A stub carrying exactly the attributes the real `_persist_state` reads, so the REAL
    method runs rather than a paraphrase of it."""
    return SimpleNamespace(
        _positions_path=tmp_path / "book.json",
        _trade_log_route=route,
        _loaded_book_envelope=envelope,
        _max_dd_dollars=0.0, _max_dd_pct=0.0, _last_broker_equity=996881.46,
        _system_epoch=None, _paper_start=None,
        state=SimpleNamespace(open_positions=[], equity=50000.0, cur_day=None,
                              breaker=SimpleNamespace(peak_equity=50000.0,
                                                      _day_start_equity=None)),
    )


def test_10_a_route_stamped_sweep_preserves_the_envelope_it_read(tmp_path):
    env = {k: v for k, v in VALID_BOOK.items() if k != "positions"}
    s = _stub(tmp_path, route="track1_candidate", envelope=env)
    R.FuturesRunner._persist_state(s)
    got = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))
    assert got["schema_version"] == 2
    assert got["route"] == "track1_candidate"
    assert got["cut_instant"] == VALID_BOOK["cut_instant"]
    assert got["booked_counter"] == {}
    assert "breaker" not in got, "the legacy breaker was written into the Track 1 book"
    assert got["positions"] == []


def test_11_the_legacy_path_is_byte_for_byte_what_it_was(tmp_path):
    """No route, no envelope: the payload must be the legacy one, unchanged."""
    s = _stub(tmp_path, route=None, envelope={})
    R.FuturesRunner._persist_state(s)
    got = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))
    assert got["schema_version"] == 1
    assert set(got) == {"schema_version", "positions", "breaker"}
    assert got["breaker"]["peak_equity"] == 50000.0
    assert got["breaker"]["last_broker_equity"] == 996881.46


def test_12_a_legacy_run_that_happens_to_have_an_envelope_still_writes_legacy(tmp_path):
    """The gate is the ROUTE, not the presence of an envelope. A legacy sweep reading a file
    with extra keys must not start preserving them."""
    s = _stub(tmp_path, route=None, envelope={"schema_version": 2, "route": "x"})
    R.FuturesRunner._persist_state(s)
    got = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))
    assert got["schema_version"] == 1
    assert "breaker" in got


def test_13_a_route_stamped_sweep_with_no_envelope_falls_through_to_legacy(tmp_path):
    """Nothing to preserve. Inventing a schema-2 envelope here would be this method deciding
    a format it does not own."""
    s = _stub(tmp_path, route="track1_candidate", envelope={})
    R.FuturesRunner._persist_state(s)
    got = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))
    assert got["schema_version"] == 1


def test_13b_the_loader_actually_stashes_the_envelope_the_writer_reads():
    """The chain the writer tests cannot reach.

    Tests 10-13 inject `_loaded_book_envelope` into a stub, so the loader could be deleted
    entirely and they would all stay green — the mutation sweep proved exactly that. The
    honest fix would be to run the real loader, and there is no way to: it lives inside
    `FuturesRunner.__init__`, which requires a broker, a guard, contracts, a signal function
    and a breaker, and this repo has no offline construction path for it.

    So the chain is pinned structurally, and the two halves are DERIVED from each other
    rather than written twice: whatever attribute `_persist_state` reads must be the one the
    loader assigns. A rename that touched only one side fails here.
    """
    tree = ast.parse((REPO / "global_index/runner.py").read_text(encoding="utf-8"))

    persist = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_persist_state")
    read_attrs = {n.attr for n in ast.walk(persist)
                  if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load)
                  and n.attr.startswith("_loaded_book")}
    assert read_attrs, "_persist_state no longer reads any loaded-book attribute"

    init = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    assigned = {t.attr for n in ast.walk(init) if isinstance(n, ast.Assign)
                for t in n.targets
                if isinstance(t, ast.Attribute) and t.attr.startswith("_loaded_book")}
    assert read_attrs <= assigned, (
        f"_persist_state reads {sorted(read_attrs)} and __init__ assigns {sorted(assigned)} — "
        f"the loader is not filling what the writer reads")

    # and the stash must happen where a dict payload is parsed, not unconditionally
    dict_branch = [n for n in ast.walk(init) if isinstance(n, ast.If)
                   and any(isinstance(a, ast.Assign)
                           and any(isinstance(t, ast.Attribute)
                                   and t.attr in read_attrs for t in a.targets)
                           for a in ast.walk(n))]
    assert dict_branch, "the stash is not inside any conditional — it would run on a list book"


def test_14_the_writer_reproduces_the_0931_corruption_without_the_fix(tmp_path):
    """The control. Feed the stub a schema-2 envelope but NO route — which is what the
    loader+writer combination effectively did before the fix — and the legacy shape comes
    out, foreign breaker and all. If this ever stops reproducing, the fix above is being
    credited for something else."""
    s = _stub(tmp_path, route=None, envelope={k: v for k, v in VALID_BOOK.items()
                                              if k != "positions"})
    R.FuturesRunner._persist_state(s)
    got = json.loads((tmp_path / "book.json").read_text(encoding="utf-8"))
    assert got["schema_version"] == 1
    assert "route" not in got
    assert got["breaker"]["peak_equity"] == 50000.0


# ══════════════════════════════════════════════════════════════════════════════
# C. the entry-point contract
# ══════════════════════════════════════════════════════════════════════════════

def test_15_the_legacy_book_with_no_route_is_untouched(tmp_path):
    dest, route = sb.resolve(None, None, tmp_path)
    assert dest == tmp_path / sb.DEFAULT_BOOK
    assert route is None


def test_16_a_route_with_the_legacy_book_is_refused(tmp_path):
    with pytest.raises(sb.BookRefused):
        sb.resolve("live_positions.json", "track1_candidate", tmp_path)


def test_16b_a_route_with_some_other_path_is_allowed(tmp_path):
    """Deliberately narrower than the first draft of this rule, which required the canonical
    Track 1 filename for any routed run. That forbade a harness or an alternate root using
    its own path and broke four Stage 5ZG tests exercising the trade-log contract with a
    temporary book — a false positive, not a caught hazard. The hazard is the LEGACY book,
    and that is what test_16 pins.

    The file is CREATED, and legacy-shaped on purpose. The first version of this test used a
    path that did not exist, so `dest.exists()` short-circuited the envelope check and the
    test could not tell a narrow rule from a wide one — the mutation sweep caught exactly
    that. A harness book exists and looks nothing like a Track 1 book; that is the case.
    """
    other = tmp_path / "book.json"
    other.write_text(json.dumps({"schema_version": 1, "breaker": {}}), encoding="utf-8")
    dest, route = sb.resolve(str(other), "track1_candidate", tmp_path)
    assert dest.name == "book.json"
    assert route == "track1_candidate"


def test_17_the_track1_book_without_a_route_is_refused(tmp_path):
    with pytest.raises(sb.BookRefused) as e:
        sb.resolve("live_positions.track1.json", None, tmp_path)
    assert "legacy shape" in str(e.value)


def test_18_an_unknown_route_is_refused(tmp_path):
    with pytest.raises(sb.BookRefused):
        sb.resolve("live_positions.track1.json", "some_other_route", tmp_path)


def test_19_a_missing_track1_book_is_allowed(tmp_path):
    """Absence is the normal shadow state and both scripts return early on it."""
    dest, route = sb.resolve("live_positions.track1.json", "track1_candidate", tmp_path)
    assert dest.name == "live_positions.track1.json"
    assert route == "track1_candidate"


def test_20_a_corrupt_track1_book_is_refused(tmp_path):
    write(tmp_path, CORRUPT_0931)
    with pytest.raises(sb.BookRefused) as e:
        sb.resolve("live_positions.track1.json", "track1_candidate", tmp_path)
    assert "route=None" in str(e.value)


def test_21_a_valid_track1_book_is_allowed(tmp_path):
    write(tmp_path, VALID_BOOK)
    dest, route = sb.resolve("live_positions.track1.json", "track1_candidate", tmp_path)
    assert route == "track1_candidate"


@pytest.mark.parametrize("body,state", [
    (CORRUPT_0931, "corrupt"),
    ({**VALID_BOOK, "schema_version": 1}, "corrupt"),
    ({**VALID_BOOK, "positions": "not a list"}, "corrupt"),
    (VALID_BOOK, "track1"),
])
def test_22_inspect_names_the_state_and_never_raises(tmp_path, body, state):
    p = write(tmp_path, body)
    got = sb.inspect(p)
    assert got["state"] == state
    assert got["ok"] is (state == "track1")
    if state == "corrupt":
        assert got["why"], "a refusal must say why"


def test_23_missing_and_corrupt_are_different_states(tmp_path):
    """The distinction the whole contract rests on."""
    missing = sb.inspect(tmp_path / "nope.json")
    corrupt = sb.inspect(write(tmp_path, CORRUPT_0931))
    assert missing["state"] == "missing"
    assert corrupt["state"] == "corrupt"
    assert missing["state"] != corrupt["state"]


def test_24_inspect_reports_foreign_keys_rather_than_dropping_them_silently(tmp_path):
    p = write(tmp_path, CORRUPT_0931)
    assert sb.inspect(p)["foreign_keys"] == ["breaker"]


# ══════════════════════════════════════════════════════════════════════════════
# D. both entry points are actually wired, and legacy still runs
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("mod", ["run_maxhold_exit", "run_stop_repair"])
def test_25_both_safety_scripts_consult_the_book_contract(mod):
    """AST at the call site, not a text search for the import. A module can import a guard
    and never call it — that is the defect class this repo has hit before."""
    tree = ast.parse((REPO / "global_index" / f"{mod}.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "resolve"
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "safety_book"]
    assert calls, f"{mod} imports the contract but never asks it anything"


@pytest.mark.parametrize("mod", ["run_maxhold_exit", "run_stop_repair"])
def test_26_the_book_check_runs_before_the_positions_check(mod):
    """Same reasoning as Stage 5ZG's trade-log probe: both scripts return early when the
    positions file is absent, which is every run during shadow. A check after that return
    would never execute."""
    src = (REPO / "global_index" / f"{mod}.py").read_text(encoding="utf-8")
    guard = src.index("safety_book.resolve")
    early_return = src.index("if not pos_path.exists()")
    assert guard < early_return, f"{mod} checks the book after it may have returned"


def test_27_the_legacy_argv_the_scheduler_sends_still_runs(tmp_path):
    """End to end, in a subprocess, with the exact argv from the scheduler log — minus the
    broker, via --dry-run. Legacy must not have acquired a new refusal."""
    legacy = tmp_path / "live_positions.json"
    legacy.write_text(json.dumps({"schema_version": 1, "positions": [], "breaker": {}}),
                      encoding="utf-8")
    p = subprocess.run(
        [sys.executable, "-m", "global_index.run_maxhold_exit",
         "--positions-path", "live_positions.json", "--port", "4002", "--dry-run"],
        cwd=REPO, capture_output=True, text=True, timeout=180)
    assert "[book]" not in (p.stdout + p.stderr), "legacy acquired a book refusal"


def test_28_the_track1_argv_refuses_on_the_live_corrupt_book():
    """The live file is corrupt right now, so this is the real refusal, not a fixture one.
    It is skipped once the book is repaired — and the skip is the signal that it was."""
    live = REPO / ts.TRACK1_POSITIONS_PATH
    if sb.inspect(live)["ok"]:
        pytest.skip("the live book has been repaired; this refusal no longer applies")
    p = subprocess.run(
        [sys.executable, "-m", "global_index.run_maxhold_exit",
         "--positions-path", ts.TRACK1_POSITIONS_PATH,
         "--stop-path", ts.TRACK1_STOP_PATH, "--lock-path", ts.TRACK1_LOCK_PATH,
         "--client-id", "90", "--trade-log-path", ts.TRACK1_TRADE_LOG_PATH,
         "--route", "track1_candidate", "--port", "4002", "--dry-run"],
        cwd=REPO, capture_output=True, text=True, timeout=180)
    assert "[book]" in (p.stdout + p.stderr)
    assert p.returncode == 1


# ══════════════════════════════════════════════════════════════════════════════
# E. one number, three modules
# ══════════════════════════════════════════════════════════════════════════════

def test_29_the_schema_number_is_declared_once():
    from global_index import track1_paper_executor as ex

    assert rl.BOOK_SCHEMA == ts.TRACK1_BOOK_SCHEMA
    assert ex.BOOK_SCHEMA == ts.TRACK1_BOOK_SCHEMA


def test_30_the_repair_writes_exactly_the_book_the_route_would_accept(tmp_path):
    """A repair that produced a book the route then refused would be worse than none."""
    from global_index import b1_book_repair as rep

    fresh = rep.fresh_book(__import__("datetime").datetime(2026, 8, 26, 12, 0))
    p = write(tmp_path, fresh)
    assert sb.inspect(p)["ok"], sb.inspect(p)["why"]
    state, _ = rl._carry_forward_book(str(p), CUT)
    assert state["route"] == ts.TRACK1_ROUTE


def test_31_the_repair_refuses_when_the_route_has_traded(tmp_path):
    from global_index import b1_book_repair as rep

    write(tmp_path, CORRUPT_0931)
    log = tmp_path / ts.TRACK1_TRADE_LOG_PATH
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"type": "CLOSE", "route": "track1_candidate"}) + "\n",
                   encoding="utf-8")
    p = rep.plan(tmp_path)
    assert p["can_repair"] is False
    assert any("guess about money" in w for w in p["problems"]), p["problems"]


def test_32_the_repair_refuses_over_an_open_position(tmp_path):
    from global_index import b1_book_repair as rep

    write(tmp_path, {**CORRUPT_0931, "positions": [{"inst": "MES"}]})
    p = rep.plan(tmp_path)
    assert p["can_repair"] is False
    assert any("position" in w for w in p["problems"])


def test_33_the_repair_is_a_dry_run_unless_told_otherwise(tmp_path):
    from global_index import b1_book_repair as rep

    book = write(tmp_path, CORRUPT_0931)
    before = book.read_text(encoding="utf-8")
    rc = rep.main(["--root", str(tmp_path)])
    assert rc == 0
    assert book.read_text(encoding="utf-8") == before, "the dry run wrote"


def test_34b_b1_no_longer_calls_a_corrupt_track1_book_flat(tmp_path):
    """B1's Track 1 half asked one question — how many positions — and a legacy-shaped file
    over the route's path still carries `positions: []`. Measured 2026-08-26: B1 reported
    "Track 1 book flat" about a book that was not the route's book at all. Flat and
    unrecognisable are different facts and a gate must not read them the same."""
    from global_index import track1_b1 as b1

    p = write(tmp_path, CORRUPT_0931)
    assert b1.read_book(p).flat is True, "the control: the generic reader still sees a list"
    checked = b1.read_track1_book(p)
    assert checked.flat is False
    assert checked.state == b1.BOOK_BAD
    assert checked.error

    good = write(tmp_path, VALID_BOOK, name="good.json")
    assert b1.read_track1_book(good).flat is True


def test_34c_the_b1_audit_uses_the_route_aware_reader():
    """AST at the call site: importing the stricter reader and calling the loose one is the
    defect class this repo has hit before."""
    tree = ast.parse((REPO / "global_index/b1_audit.py").read_text(encoding="utf-8"))
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {n.func.attr for n in ast.walk(main)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "read_track1_book" in called, "the audit still reads the route's book loosely"


def test_34_orders_are_still_impossible():
    from global_index import track1_gates as g

    assert g.may_enable_orders()[0] is False
    assert not (REPO / g.CONFIRMATION_PATH).exists()
