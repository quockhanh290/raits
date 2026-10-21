"""Stage 5ZZP — the rewritten policy tests, proved able to fail.

Fifteen assertions across three suites pinned the world as it stood before 2026-09-24: orders
impossible, no confirmation file, no order journal, the arming flag present in no source file.
The operator ended that state on purpose — paper orders now run inside the session — so those
fifteen went red at once. Every one was rewritten to assert the RULE instead of the world.

That is the dangerous kind of edit. A test rewritten until it passes is indistinguishable, from
the outside, from a test rewritten until it checks nothing, and this repo has caught itself
shipping the second kind: *"test xanh mà không kiểm gì"* — green while measuring nothing. The
project's own rule is that a measurement has to be able to come out red.

So this file mutates the thing each rewritten test claims to guard and asserts the test NOTICES.
A mutation that leaves its test green is reported by name, because that test is decoration.

Nothing here writes to the real tree. Source-scanning tests are pointed at a mutated COPY under
`tmp_path` by rebinding the suite module's `REPO`; registry tests are mutated with monkeypatch on
the live objects. Both leave production files untouched — mutating them on disk while the
scheduler is up would hand a real slot a patched module.
"""
from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

W = importlib.import_module("scratch.test_track1_stage5w_paper_executor_20260825")
Z = importlib.import_module("scratch.test_track1_stage5z_callsite_dryrun_20260825")
G5 = importlib.import_module("scratch.test_track1_stage5zzg_order_send_wire_20260827")


# ── the harness ──────────────────────────────────────────────────────────────────────────────

#: Every file the source-scanning tests read. A mutant tree needs all of them, not just the one
#: being mutated, or the test fails on a missing file and the mutation proves nothing.
SCANNED = (
    "global_index/run_scheduler.py",
    "monitor/ops.py",
)


def mutant_repo(tmp_path: Path, rel: str, old: str, new: str) -> Path:
    """A throwaway tree holding the scanned files, with one edit applied to one of them."""
    root = tmp_path / "mutant"
    for f in SCANNED:
        dst = root / f
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / f, dst)
    target = root / rel
    text = target.read_text(encoding="utf-8")
    assert text.count(old) == 1, (
        "the mutation anchor %r appears %d times in %s; the mutation would be ambiguous and a "
        "green result would mean nothing" % (old, text.count(old), rel))
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return root


def must_fail(fn, *args, **kwargs):
    """Run a test function and report whether it refused. `True` means the test has teeth."""
    try:
        fn(*args, **kwargs)
    except AssertionError:
        return True
    except Exception as exc:                                          # noqa: BLE001
        # A test that dies of a TypeError under mutation did not detect anything; it broke.
        raise AssertionError(
            "the test raised %s instead of asserting: %s" % (type(exc).__name__, exc)) from exc
    return False


# ── 1. the arming flag: it may exist now, it may not appear unguarded ────────────────────────

UNGUARDED = (
    '+ (["--allow-orders"] if allow_orders else []),',
    '+ ["--allow-orders"],',
)


def test_M1_an_unguarded_flag_in_the_slot_argv_is_caught_by_5Z(tmp_path, monkeypatch):
    """The collapse that matters most. Drop the branch and every slot the scheduler spawns is
    armed, whoever started it — including the logon task that now brings this machine back."""
    root = mutant_repo(tmp_path, "global_index/run_scheduler.py", *UNGUARDED)
    monkeypatch.setattr(Z, "REPO", root)
    assert must_fail(Z.test_38_no_scheduler_or_ops_path_sends_on_its_own), \
        "5Z test_38 stayed green while the scheduler armed every slot unconditionally"


def test_M2_the_same_mutation_is_caught_by_5ZZG(tmp_path, monkeypatch):
    """Two suites guard the same line on purpose, and they disagree about how to look at it —
    5Z walks the AST, 5ZZG reads the lines. Both have to notice."""
    root = mutant_repo(tmp_path, "global_index/run_scheduler.py", *UNGUARDED)
    monkeypatch.setattr(G5, "REPO", root)
    assert must_fail(G5.test_20_the_order_flag_appears_only_behind_an_explicit_request,
                     "global_index/run_scheduler.py"), \
        "5ZZG test_20 stayed green while the flag reached an argv with no branch"


def test_M3_an_unguarded_flag_in_ops_is_caught(tmp_path, monkeypatch):
    """The other launcher. `ops up` is what a person actually types, so an ops-side default
    would arm without the word appearing on anybody's command line."""
    # Anchored on the comment under it: `if allow_orders:` appears three times in ops.py, and
    # this is the one that puts the flag on the scheduler's own argv.
    root = mutant_repo(tmp_path, "monitor/ops.py",
                       "    if allow_orders:\n        # Both halves",
                       "    if True:\n        # Both halves")
    monkeypatch.setattr(G5, "REPO", root)
    assert must_fail(G5.test_20_the_order_flag_appears_only_behind_an_explicit_request,
                     "monitor/ops.py"), \
        "5ZZG test_20 stayed green while ops appended the flag on every start"


def test_M4_a_scheduler_that_defaults_to_armed_is_caught(tmp_path, monkeypatch):
    """This is the reboot case in one character. `= True` and a scheduler restarted by the
    logon task comes back able to send, with nobody at the machine."""
    root = mutant_repo(tmp_path, "global_index/run_scheduler.py",
                       "allow_orders: bool = False", "allow_orders: bool = True")
    monkeypatch.setattr(W, "REPO", root)
    assert must_fail(W.test_34_the_slot_takes_an_order_gate_and_defaults_it_shut,
                     tmp_path), \
        "5W test_34 stayed green while make_scheduler defaulted to armed"


def test_M5_a_broker_reached_from_a_launcher_is_caught(tmp_path, monkeypatch):
    """The two facts test_38 kept from its old form. Either launcher building its own broker
    would put a send outside the gated wire entirely."""
    root = mutant_repo(tmp_path, "monitor/ops.py",
                       "def main(argv: list[str] | None = None) -> int:",
                       "def _leak(b):\n    return b.send_order(None)\n\n\n"
                       "def main(argv: list[str] | None = None) -> int:")
    monkeypatch.setattr(Z, "REPO", root)
    assert must_fail(Z.test_38_no_scheduler_or_ops_path_sends_on_its_own), \
        "5Z test_38 stayed green while ops called send_order itself"


# ── 2. the gate: an override must never read as a gate that opened ───────────────────────────

def test_M6_an_override_that_stops_reporting_itself_is_caught(monkeypatch):
    """The whole reason the evidence gate was overridden rather than switched off. If
    `overridden()` goes quiet, orders are allowed with a failing gate and nothing on the record
    says which evidence was produced and which was waived."""
    from global_index import track1_gates as G

    allowed, _ = G.may_enable_orders()
    if not allowed:
        pytest.skip("nothing is armed; test_39 takes its blocked branch and this cannot apply")

    monkeypatch.setattr(G, "overridden", lambda conf=None: [])
    assert must_fail(Z.test_39_an_open_gate_still_says_how_it_opened), \
        "5Z test_39 stayed green while an override reported nothing"


def test_M7_an_override_reported_with_no_reason_is_caught(monkeypatch):
    """Half-silence counts. A waiver on the record with an empty reason tells a reader in
    December that something was stepped over and not what to go and look at."""
    from global_index import track1_gates as G

    if not G.may_enable_orders()[0]:
        pytest.skip("nothing is armed")

    real = G.overridden()
    if not real:
        pytest.skip("nothing is overridden right now")
    monkeypatch.setattr(G, "overridden", lambda conf=None: [(b, "") for b, _ in real])
    assert must_fail(Z.test_39_an_open_gate_still_says_how_it_opened), \
        "5Z test_39 stayed green while a waiver carried no reason"


def test_M8_a_blocker_both_released_and_overridden_is_caught(monkeypatch):
    """The collapse of the third state into the first. `released() is True` on something being
    overridden would make waived evidence indistinguishable from produced evidence."""
    from global_index import track1_gates as G

    if not G.may_enable_orders()[0]:
        pytest.skip("nothing is armed")

    released = [b for b in G.BLOCKERS.values()
                if b.blocks_orders and b.released(G.current_confirmations())]
    if not released:
        pytest.skip("no released order-holding blocker to mislabel")
    monkeypatch.setattr(G, "overridden", lambda conf=None: [(released[0], "waived")])
    assert must_fail(Z.test_39_an_open_gate_still_says_how_it_opened), \
        "5Z test_39 stayed green while one blocker was released and overridden at once"


# ── 3. the rehearsal must not quote its own synthetic gate as production's ───────────────────

def test_M9_a_rehearsal_reporting_its_own_gate_as_production_is_caught(monkeypatch, tmp_path):
    """What the gate stage exists for. If the stage starts echoing the synthetic answer, a
    rehearsal transcript reads as evidence that production was open."""
    from global_index import track1_paper_executor as X

    class _Synthetic:
        allow_orders = True
        reasons = ()
        synthetic = True

    monkeypatch.setattr(X, "production_gate", lambda: _Synthetic())
    monkeypatch.setattr(Z.CS.ex, "production_gate", lambda: _Synthetic(), raising=False)

    from global_index import track1_gates as G
    monkeypatch.setattr(G, "may_enable_orders", lambda conf=None: (False, ["BLOCKED: x"]))

    assert must_fail(Z.test_16_the_gate_stage_reports_the_REAL_answer_not_the_synthetic_one,
                     tmp_path), \
        "5Z test_16 stayed green while the stage reported the synthetic gate as production's"


def test_M10_a_production_gate_that_carries_its_own_opinion_is_caught(monkeypatch):
    """A gate object holding a cached answer instead of asking the registry is how a stale
    `False` survived in these tests for a month in the first place — in the other direction."""
    from global_index import track1_gates as G
    from global_index import track1_paper_executor as X

    class _Cached:
        allow_orders = not G.may_enable_orders()[0]
        reasons = ()
        synthetic = False

    monkeypatch.setattr(X, "production_gate", lambda: _Cached())
    assert must_fail(Z.test_17_the_synthetic_gate_is_a_different_type_from_the_production_one), \
        "5Z test_17 stayed green while the production gate disagreed with the registry"


def test_M11_a_synthetic_object_on_the_production_path_is_caught(monkeypatch):
    from global_index import track1_gates as G
    from global_index import track1_paper_executor as X

    class _Sneaky:
        allow_orders = G.may_enable_orders()[0]
        reasons = ()
        synthetic = True                       # a rehearsal object, returned as production's

    monkeypatch.setattr(X, "production_gate", lambda: _Sneaky())
    assert must_fail(Z.test_17_the_synthetic_gate_is_a_different_type_from_the_production_one), \
        "5Z test_17 stayed green while production_gate returned a synthetic object"


# ── 4. the executor stays reachable only through the two named seams ─────────────────────────

def test_M12_a_new_production_importer_of_the_executor_is_caught(tmp_path, monkeypatch):
    """The one thing test_33 exists for: a THIRD module naming the executor is a new road to a
    live order. Proved on a mutant tree, because the real one must keep exactly two."""
    root = tmp_path / "mutant33"
    (root / "global_index").mkdir(parents=True)
    (root / "global_index" / "track1_paper_send.py").write_text(
        "from global_index import track1_paper_executor as ex\n", encoding="utf-8")
    (root / "global_index" / "innocent_helper.py").write_text(
        "from global_index import track1_paper_executor\n", encoding="utf-8")
    monkeypatch.setattr(W, "REPO", root)
    assert must_fail(W.test_33_nothing_in_production_imports_the_executor, tmp_path), \
        "5W test_33 stayed green while a new production module imported the executor"


def test_M13_a_docstring_mention_is_not_treated_as_an_importer(tmp_path, monkeypatch):
    """The other direction, and the reason test_33 parses imports instead of scanning text. A
    module that only TALKS about the executor is not a path to a broker, and a test that says
    otherwise gets edited into silence the next time it cries wolf."""
    root = tmp_path / "mutant33b"
    (root / "global_index").mkdir(parents=True)
    (root / "global_index" / "track1_paper_send.py").write_text(
        "from global_index import track1_paper_executor as ex\n", encoding="utf-8")
    (root / "global_index" / "prose_only.py").write_text(
        '"""This module never touches track1_paper_executor."""\n'
        "# track1_paper_executor is mentioned here and nowhere else\n", encoding="utf-8")
    monkeypatch.setattr(W, "REPO", root)
    W.test_33_nothing_in_production_imports_the_executor(tmp_path)      # must NOT raise


# ── 5. the suite writes nothing into the real order journal ──────────────────────────────────

def test_M14_a_write_into_the_orders_tree_is_caught(tmp_path, monkeypatch):
    """test_41 can only be mutated one way without writing to production evidence: point the
    listing at a temp tree, add a file, and confirm the comparison sees it. The old form —
    `not ORDERS_DIR.exists()` — could not have seen this at all once the directory existed."""
    fake = tmp_path / "orders"
    (fake / "2026-09-24").mkdir(parents=True)
    (fake / "2026-09-24" / "sent.jsonl").write_text('{"a": 1}\n', encoding="utf-8")

    monkeypatch.setattr(Z, "REPO", tmp_path)
    monkeypatch.setattr(Z.J, "ORDERS_DIR", "orders", raising=False)
    before = Z._orders_tree_listing()
    assert before, "the seeded tree read as empty; the listing helper is measuring nothing"

    monkeypatch.setattr(Z, "_ORDERS_AT_IMPORT", before)
    Z.test_41_this_suite_wrote_nothing_into_the_real_runtime_tree()     # unchanged: passes

    (fake / "2026-09-24" / "sent.jsonl").write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    assert must_fail(Z.test_41_this_suite_wrote_nothing_into_the_real_runtime_tree), \
        "test_41 stayed green while a line was appended to an existing journal file"


def test_M15_a_new_file_in_the_orders_tree_is_caught(tmp_path, monkeypatch):
    fake = tmp_path / "orders"
    fake.mkdir()
    (fake / "a.jsonl").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(Z, "REPO", tmp_path)
    monkeypatch.setattr(Z.J, "ORDERS_DIR", "orders", raising=False)
    monkeypatch.setattr(Z, "_ORDERS_AT_IMPORT", Z._orders_tree_listing())
    (fake / "b.jsonl").write_text("y\n", encoding="utf-8")
    assert must_fail(Z.test_41_this_suite_wrote_nothing_into_the_real_runtime_tree), \
        "test_41 stayed green while a new file appeared in the journal"


# ── 6. and the rewrite did not quietly drop a test ───────────────────────────────────────────

def test_M16_every_rewritten_test_still_exists_under_a_readable_name():
    """A rewrite can also fail by deletion. These sixteen names are the fifteen that were
    rewritten plus the one helper test_41 now depends on; each must still be collected."""
    expected = {
        W: ("test_33_nothing_in_production_imports_the_executor",
            "test_34_the_slot_takes_an_order_gate_and_defaults_it_shut",
            "test_36_the_executor_refuses_a_gate_that_is_not_ARMED",
            "test_37_the_ambient_shell_never_carries_the_approval",
            "test_38_only_an_explicit_operator_request_passes_the_order_flag"),
        Z: ("test_16_the_gate_stage_reports_the_REAL_answer_not_the_synthetic_one",
            "test_17_the_synthetic_gate_is_a_different_type_from_the_production_one",
            "test_38_no_scheduler_or_ops_path_sends_on_its_own",
            "test_39_an_open_gate_still_says_how_it_opened",
            "test_41_this_suite_wrote_nothing_into_the_real_runtime_tree",
            "_orders_tree_listing"),
        G5: ("test_20_the_order_flag_appears_only_behind_an_explicit_request",
             "test_22_the_scheduler_builds_the_order_flag_in_exactly_one_branch",
             "test_24_orders_need_both_factors_and_an_override_reports_itself",
             "test_26_the_executor_is_reachable_only_through_a_wall_or_the_gate"),
    }
    missing = [(m.__name__.rsplit(".", 1)[-1], n)
               for m, names in expected.items() for n in names
               if not callable(getattr(m, n, None))]
    assert missing == [], missing


# ── 7. the rolling pre-flight window: the clause a literal list could not express ─────────────

ZN = importlib.import_module("scratch.test_track1_stage5zn_planned_stop_lifecycle_20260826")


def _preflight_repo(tmp_path, days):
    root = tmp_path / "pf"
    (root / "global_index").mkdir(parents=True)
    import json as _json
    (root / "global_index" / "preflight_state.json").write_text(
        _json.dumps({d: True for d in days}), encoding="utf-8")
    return root


def _et_today():
    import datetime as dt
    import zoneinfo
    return dt.datetime.now(zoneinfo.ZoneInfo("America/New_York")).date()


def _rolling(n=7, end_offset=0):
    import datetime as dt
    end = _et_today() - dt.timedelta(days=end_offset)
    return [(end - dt.timedelta(days=i)).isoformat() for i in range(n)]


def test_M17_a_healthy_rolling_window_passes(tmp_path, monkeypatch):
    """First, that the rewritten rule accepts a good record — otherwise M18-M20 prove nothing,
    because a rule that refuses everything also refuses every mutation."""
    monkeypatch.setattr(ZN, "REPO", _preflight_repo(tmp_path, _rolling()))
    ZN.test_the_preflight_record_is_a_rolling_real_preflight_window()


def test_M18_a_window_frozen_in_the_past_is_caught(tmp_path, monkeypatch):
    """The clause the literal date list could never express, and the one that matters: a record
    that stopped being written looks identical to a healthy one from its shape alone. Seven unique
    days, none in the future — and the 13:45 ET pre-flight has not run in a month."""
    monkeypatch.setattr(ZN, "REPO", _preflight_repo(tmp_path, _rolling(end_offset=30)))
    assert must_fail(ZN.test_the_preflight_record_is_a_rolling_real_preflight_window), \
        "a pre-flight record 30 days stale passed as a healthy rolling window"


def test_M19_a_day_the_preflight_cannot_have_set_is_caught(tmp_path, monkeypatch):
    """The 5ZL incident itself: a day in the record that the real 13:45 ET pre-flight never set.
    A future date is the version of that a test can state without ambiguity."""
    import datetime as dt

    days = _rolling(6) + [(_et_today() + dt.timedelta(days=3)).isoformat()]
    monkeypatch.setattr(ZN, "REPO", _preflight_repo(tmp_path, days))
    assert must_fail(ZN.test_the_preflight_record_is_a_rolling_real_preflight_window), \
        "a record holding a future day passed"


def test_M20_a_window_that_grew_is_caught(tmp_path, monkeypatch):
    """Eight days is not a seven-day window; a record that grows is not rolling."""
    monkeypatch.setattr(ZN, "REPO", _preflight_repo(tmp_path, _rolling(8)))
    assert must_fail(ZN.test_the_preflight_record_is_a_rolling_real_preflight_window), \
        "an eight-day record passed as a seven-day window"
