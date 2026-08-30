"""Stage 5ZR — the B1 decision is prepared, previewed, and deliberately not recorded.

Stage 5ZQ measured the account flat and gave B1 a second half. This stage builds the step
between the measurement and the commitment: a template that cannot arm anything by accident,
and a previewer that answers "what would this file open?" without the file being placed.

The decision itself is NOT recorded, and the reason is measured rather than cautious: neither
decision is true today. `legacy_retired_confirmed` says legacy has stopped trading — and
legacy is dormant because of a command-line flag, not retired: `track1-only-shadow` registers
0 legacy strategy jobs and the default mode registers 45. `separate_account_confirmed` says
Track 1 has its own login, and there is one account.

Every assertion is on structured payloads, AST, or observed file access. Nothing greps prose.
"""
from __future__ import annotations

import ast
import builtins
import datetime as dt
import json
from pathlib import Path

import pytest

from global_index import track1_b1 as b1
from global_index import track1_b1_decision as bd
from global_index import track1_gates as g

REPO = Path(r"d:\raits")
TEMPLATE = REPO / "scratch/track1_b1_decision_template_20260826.json"
LIVE = REPO / g.CONFIRMATION_PATH
B1_ID = "B1_broker_account_or_legacy_retirement"


def _decision_file(tmp_path: Path, **over) -> Path:
    body = {"schema_version": 1, "confirmed_by": "operator", "confirmed_at": "2026-08-26"}
    body.update(over)
    p = tmp_path / "candidate.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _fresh_pass(tmp_root: Path, *, hours_ago: float = 0.0) -> None:
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)
    d = tmp_root / b1.B1_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / "track1_b1_20260826.jsonl").write_text(json.dumps({
        "status": b1.PASS, "code": b1.OK, "detail": "flat",
        "checked_at": when.isoformat()}) + "\n", encoding="utf-8")


def _conf(**flags):
    return g.Confirmations(flags, "tester", "2026-08-26", "test")


# ══════════════════════════════════════════════════════════════════════════════
# 1–3. the two halves, and neither is the other
# ══════════════════════════════════════════════════════════════════════════════

def test_1_measurement_passes_but_no_decision_means_b1_still_blocks(monkeypatch):
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence", lambda root=".": (True, "PASS"))
    assert g.BLOCKERS[B1_ID].released(_conf()) is False
    assert B1_ID in [b.id for b in g.blocking(_conf())]


@pytest.mark.parametrize("state,detail", [
    ("missing", "no record at all"),
    ("stale", "older than the allowance"),
])
def test_2_a_decision_without_a_usable_measurement_still_blocks(tmp_path, monkeypatch, state,
                                                                detail):
    if state == "stale":
        _fresh_pass(tmp_path, hours_ago=b1.MAX_RECORD_AGE_HOURS + 1)
    got = b1.latest(tmp_path)
    assert got.status == b1.UNKNOWN, (state, got.status)

    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (b1.latest(tmp_path).status == b1.PASS, detail))
    assert g.BLOCKERS[B1_ID].released(_conf(legacy_retired_confirmed=True)) is False


def test_3_a_decision_with_a_fresh_pass_releases_b1(tmp_path, monkeypatch):
    _fresh_pass(tmp_path)
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (b1.latest(tmp_path).status == b1.PASS, "x"))
    assert g.BLOCKERS[B1_ID].released(_conf(legacy_retired_confirmed=True)) is True
    assert g.BLOCKERS[B1_ID].released(_conf(separate_account_confirmed=True)) is True


# ══════════════════════════════════════════════════════════════════════════════
# 4–6. the waiver, and what releasing B1 does NOT do
# ══════════════════════════════════════════════════════════════════════════════

def test_4_a_waiver_without_a_reason_is_refused(tmp_path):
    p = _decision_file(tmp_path, legacy_retired_confirmed=True, b1_measurement_waived=True)
    conf, errs = g.load_confirmations(p)
    assert errs, "a waiver with no note must be refused"
    assert conf.get("legacy_retired_confirmed") is False, "a refused file grants NOTHING"


def test_5_a_waiver_with_a_reason_bypasses_only_the_measurement(tmp_path, monkeypatch):
    p = _decision_file(tmp_path, legacy_retired_confirmed=True, b1_measurement_waived=True,
                       note="IB Gateway offline for maintenance")
    conf, errs = g.load_confirmations(p)
    assert errs == []
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (False, "UNKNOWN — nobody asked"))
    assert g.BLOCKERS[B1_ID].released(conf) is True, "the waiver must bypass the measurement"
    still = [b.id for b in g.blocking(conf)]
    assert "PAPER_SHADOW_EVIDENCE" in still
    # Stage 5ZZJ. REGIME_LABEL_VERIFICATION was pinned here as still blocking; it was released
    # by its own measurement on 2026-08-26, so the pin failed for a reason that has nothing to
    # do with B1. Expressed as the property this test is actually about: a waiver bypasses the
    # MEASUREMENT half of B1 and touches no other gate.
    assert B1_ID not in still
    assert set(still) == {b.id for b in g.blocking() if b.id != B1_ID}
    assert g.may_enable_orders(conf)[0] is False


def test_6_releasing_b1_does_not_make_orders_possible(monkeypatch):
    """The whole point of the stage. B1 opening is not the gate opening."""
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence", lambda root=".": (True, "PASS"))
    for flag in ("legacy_retired_confirmed", "separate_account_confirmed"):
        conf = _conf(**{flag: True})
        blocking = [b.id for b in g.blocking(conf)]
        assert B1_ID not in blocking, flag
        assert blocking, "something must still be blocking"
        assert g.may_enable_orders(conf)[0] is False, flag


def test_7_no_confirmation_flag_can_release_a_measured_gate():
    """Structural, not situational: a MEASURED_GATE with any releasing flag would be a gate a
    signature could open. `self_check` enforces it; this asserts the enforcement is live."""
    for bid, b in g.BLOCKERS.items():
        if b.status == g.MEASURED_GATE:
            assert b.released_by == (), bid
    assert g.self_check() == []


# ══════════════════════════════════════════════════════════════════════════════
# 7–8. nothing here can send an order
# ══════════════════════════════════════════════════════════════════════════════

def test_8_the_template_carries_no_order_approval_field():
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    keys = {k.lower() for k in raw}
    for forbidden in ("track1_orders_approved", "allow_orders", "orders_approved",
                      "arm", "armed"):
        assert forbidden not in keys, forbidden
    assert raw.get("legacy_retired_confirmed") is False
    assert raw.get("separate_account_confirmed") is False


def test_9_no_track1_slot_argv_carries_allow_orders():
    """AST over the scheduler's slot builder: the flag must not appear in any argv list the
    slot constructs. A text search over this function matches its own comment, which says the
    flag is absent — that exact trap produced a red test claiming a shadow slot could request
    orders, and it was false."""
    src = (REPO / "global_index/run_scheduler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_track1_body"), None)
    assert fn is not None, "_track1_body moved; this test is measuring nothing"
    literals = [n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert literals, "no string literals found — the argv builder moved"
    assert "--allow-orders" not in literals
    assert "--port" not in literals


def test_10_the_route_still_constructs_no_order_capable_broker():
    """Opening every gate produces a route that cannot send. Asserted by AST rather than by
    trusting the runbook paragraph that says so."""
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    assert "NoOrderBroker" in names
    assert "IBKRBroker" not in names


# ══════════════════════════════════════════════════════════════════════════════
# 9. legacy drain safety survives a B1 decision
# ══════════════════════════════════════════════════════════════════════════════

def test_11_legacy_drain_safety_is_scheduled_regardless_of_any_decision():
    """The scheduler is built from flags, not from the confirmation file. Recording a decision
    cannot remove the drain — retiring legacy is a separate, ordered procedure."""
    from global_index import run_scheduler as rs

    jobs = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                            track1_shadow=True, track1_only=True).get_jobs()}
    drain = {j for j in jobs if not j.startswith("track1_")
             and ("stop_repair" in j or "max_hold" in j or "maxhold" in j)}
    assert len(drain) >= 10, sorted(drain)

    tree = ast.parse((REPO / "global_index/run_scheduler.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "load_confirmations" not in (names | attrs), \
        "the scheduler now reads the confirmation file — a decision could change what runs"


def test_12_legacy_is_dormant_by_a_flag_not_retired():
    """The measured fact behind this stage's refusal to record a decision."""
    from global_index import run_scheduler as rs

    def entry_jobs(**kw):
        jobs = [j.id for j in rs.make_scheduler(port=4002, dry_run=True, **kw).get_jobs()]
        return [j for j in jobs if not j.startswith("track1_") and "live_day" in j]

    assert entry_jobs(track1_shadow=True, track1_only=True) == []
    assert len(entry_jobs(track1_shadow=False)) > 20, "legacy entry jobs vanished entirely"


# ══════════════════════════════════════════════════════════════════════════════
# the template is inert, and the previewer never writes
# ══════════════════════════════════════════════════════════════════════════════

def test_13_the_template_copied_verbatim_to_the_live_path_grants_nothing(tmp_path):
    """The realistic accident is a verbatim copy, so the template must refuse by construction
    rather than by instruction."""
    dest = tmp_path / g.CONFIRMATION_PATH
    dest.write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    conf, errs = g.load_confirmations(dest)
    assert errs, "the template validated — it could be copied into place and work"
    for flag in g.CONFIRMATION_FLAGS:
        assert conf.get(flag) is False, flag


def test_14_the_template_refuses_for_more_than_one_independent_reason(tmp_path):
    """One reason is a typo away from disappearing, so the template must have at least two —
    and this test proves the plural by ABLATION rather than by asserting it.

    Rewritten after the mutation sweep. The first version stripped the underscore keys and
    checked the file still refused; it stayed green when the underscore guard was removed from
    the template altogether, because it was removing that guard itself. A test that performs
    the mutation it is meant to detect cannot detect it. Each defence is now removed in turn
    and refusal must survive every single removal.
    """
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    ablations = {
        "no underscore keys": {k: v for k, v in raw.items() if not k.startswith("_")},
        "operator named": {**raw, "confirmed_by": "someone", "confirmed_at": "2026-08-26"},
    }
    assert len(ablations) >= 2, "the ablation set must actually contain alternatives"

    for label, body in ablations.items():
        dest = tmp_path / f"{abs(hash(label))}.json"
        dest.write_text(json.dumps(body), encoding="utf-8")
        conf, errs = g.load_confirmations(dest)
        assert errs, (f"with '{label}' the template VALIDATES — it is now one edit from being "
                      f"copied into place and working")
        for flag in g.CONFIRMATION_FLAGS:
            assert conf.get(flag) is False, (label, flag)

    # and the plural is the point: removing every defence at once must be what it takes
    armed = {k: v for k, v in raw.items() if not k.startswith("_")}
    armed.update(confirmed_by="someone", confirmed_at="2026-08-26")
    dest = tmp_path / "armed.json"
    dest.write_text(json.dumps(armed), encoding="utf-8")
    _, errs = g.load_confirmations(dest)
    assert errs == [], ("this control must validate; if it does not, the ablations above are "
                        "passing for a reason nobody has identified")


def test_15_the_previewer_writes_nothing_anywhere(tmp_path, monkeypatch):
    """Behavioural, not a promise: every file opened for writing is recorded, and the list
    must be empty. A literal scan would miss a path built by concatenation."""
    opened: list = []
    real_open = builtins.open

    def watching(file, mode="r", *a, **kw):
        if any(ch in str(mode) for ch in ("w", "a", "x", "+")):
            opened.append(str(file))
        return real_open(file, mode, *a, **kw)

    real_write = Path.write_text

    def watching_write(self, *a, **kw):
        opened.append(str(self))
        return real_write(self, *a, **kw)

    p = _decision_file(tmp_path, legacy_retired_confirmed=True)
    monkeypatch.setattr(builtins, "open", watching)
    monkeypatch.setattr(Path, "write_text", watching_write)
    try:
        pv = bd.preview(p, ".")
        bd.render(pv)
    finally:
        monkeypatch.undo()
    assert opened == [], opened


def test_16_the_previewer_module_has_no_write_call_at_all():
    """AST backstop for the behavioural test above: a write on a branch the preview did not
    take would pass test_15 and still be a write."""
    #: `replace` is deliberately NOT in this list. `Path.replace` moves a file, but
    #: `str.replace` is how an ISO timestamp's trailing Z is normalised, and AST cannot tell
    #: the two apart by name alone — the first version of this test flagged
    #: `checked_at.replace("Z", "+00:00")` as a filesystem write. A check that fires on a
    #: string method would be silenced by whoever hit it next, which is worse than not having
    #: it. The behavioural test above is the one that would catch a real `Path.replace`,
    #: because it watches what is actually opened for writing.
    WRITERS = ("write_text", "write_bytes", "mkdir", "unlink", "rename", "touch", "record")
    bad = []
    for n in ast.walk(tree := ast.parse(
            (REPO / "global_index/track1_b1_decision.py").read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in WRITERS:
                bad.append(f"{n.func.attr}:{n.lineno}")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open":
            bad.append(f"open:{n.lineno}")
    assert bad == [], bad

    # and it must not have imported a way to move files either
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    assert "shutil" not in imported, imported


def test_17_the_previewer_never_names_the_live_confirmation_path():
    """It previews candidates. A default that pointed at the live file would make an
    accidental bare invocation read — and eventually be trusted to write — the real thing."""
    src = (REPO / "global_index/track1_b1_decision.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert g.CONFIRMATION_PATH not in literals


# ══════════════════════════════════════════════════════════════════════════════
# the preview itself
# ══════════════════════════════════════════════════════════════════════════════

def test_18_the_preview_reports_what_would_open_and_what_would_not(tmp_path):
    p = _decision_file(tmp_path, legacy_retired_confirmed=True)
    pv = bd.preview(p, ".")
    assert pv.valid
    assert pv.decisions == ["legacy_retired_confirmed"]
    assert pv.would_release == [B1_ID]
    # Stage 5ZZJ. Was a literal pair including REGIME_LABEL_VERIFICATION, which its own
    # measurement released on 2026-08-26. A list of gate ids frozen into an assertion goes
    # stale every time a gate closes, and it goes red for a reason unrelated to the test's
    # subject. The property: the preview reports everything still blocking EXCEPT B1.
    assert "PAPER_SHADOW_EVIDENCE" in pv.would_still_block
    assert B1_ID not in pv.would_still_block
    assert set(pv.would_still_block) == {b.id for b in g.blocking() if b.id != B1_ID}
    assert pv.would_orders_be_possible is False


def test_19_the_preview_warns_that_legacy_is_dormant_not_retired(tmp_path):
    p = _decision_file(tmp_path, legacy_retired_confirmed=True)
    pv = bd.preview(p, ".")
    assert pv.legacy_entry_capability in (bd.LEGACY_ENTRY_NONE, bd.LEGACY_ENTRY_PRESENT,
                                          bd.LEGACY_ENTRY_UNKNOWN)
    assert pv.warnings, "recording a retirement claim must never preview silently"


def test_20_setting_both_decisions_is_reported_as_saying_neither(tmp_path):
    p = _decision_file(tmp_path, legacy_retired_confirmed=True,
                       separate_account_confirmed=True)
    pv = bd.preview(p, ".")
    assert len(pv.decisions) == 2
    assert any("mutually exclusive" in w for w in pv.warnings), pv.warnings


def test_21_a_missing_file_previews_as_granting_nothing(tmp_path):
    pv = bd.preview(tmp_path / "nope.json", ".")
    assert pv.exists is False and pv.valid is False
    assert pv.would_release == []
    assert pv.would_orders_be_possible is False


def test_22_legacy_entry_capability_has_three_values_not_two():
    """`unknown` must exist and must not be spelled the same as `none`. A scheduler that
    cannot be read is not a scheduler that is safe."""
    assert len({bd.LEGACY_ENTRY_NONE, bd.LEGACY_ENTRY_PRESENT, bd.LEGACY_ENTRY_UNKNOWN}) == 3
    assert bd._legacy_entry_capability()[0] in (bd.LEGACY_ENTRY_NONE, bd.LEGACY_ENTRY_PRESENT,
                                                bd.LEGACY_ENTRY_UNKNOWN)


@pytest.mark.parametrize("procs,cmdlines,expect", [
    ([], "", bd.LEGACY_ENTRY_UNKNOWN),
    ([{"pid": 1}], "python run_scheduler.py --track1-only-shadow", bd.LEGACY_ENTRY_NONE),
    ([{"pid": 1}], "python run_scheduler.py", bd.LEGACY_ENTRY_PRESENT),
])
def test_22b_an_unreadable_scheduler_is_unknown_not_none(monkeypatch, procs, cmdlines, expect):
    """Behavioural, and it exists because the AST version of this test proved nothing.

    That version listed the constants returned anywhere in the function and required all
    three. Changing the no-scheduler branch from UNKNOWN to NONE left all three still present
    — the exception handler still returned UNKNOWN — so the test stayed green while the
    function had started reporting "legacy cannot enter" about a scheduler it could not see.
    Caught by the mutation sweep. The branch is now exercised instead of inventoried.
    """
    from monitor import ops

    monkeypatch.setattr(ops, "scheduler_processes", lambda: procs)
    monkeypatch.setattr(ops, "scheduler_command_lines", lambda p: cmdlines)
    got, why = bd._legacy_entry_capability()
    assert got == expect, (procs, cmdlines, got, why)
    assert why, "every answer must say how it was reached"


# ══════════════════════════════════════════════════════════════════════════════
# the world, unchanged
# ══════════════════════════════════════════════════════════════════════════════

def test_23_this_stage_created_no_confirmation_file():
    """Restated by Stage 5ZZK. The file now EXISTS — the operator placed it on 2026-08-27,
    which is the thing the whole B1 sequence was working towards. What this test has always
    been about is that *this stage* did not create it, and that no stray copy appeared in the
    package directory. If a file is present it must be the operator's, and it must validate:
    a confirmation nobody can parse is worse than none at all.
    """
    assert not (REPO / "global_index" / g.CONFIRMATION_PATH).exists(), (
        "a confirmation appeared inside the package directory")
    if LIVE.exists():
        _conf, errors = g.load_confirmations(LIVE)
        assert errors == [], f"the confirmation on disk does not validate: {errors}"


def test_24_orders_are_still_impossible():
    """Restated by Stage 5ZZK: B1 no longer blocks, because the operator decided and the
    evidence passes — that is the gate working, not a regression. The invariant this test
    exists for is untouched, and it is the one that matters."""
    import os

    assert g.may_enable_orders()[0] is False
    assert "PAPER_SHADOW_EVIDENCE" in [b.id for b in g.blocking()], (
        "orders became impossible for some reason other than the evidence gate")
    assert os.environ.get("TRACK1_ORDERS_APPROVED") is None


def test_25_no_order_journal_exists():
    assert not (REPO / "global_index/track1_runtime/orders").exists()


def test_26_the_readiness_report_describes_b1_as_two_halves():
    """Its closing paragraph said B1 was released by "a confirmation file" — true until
    Stage 5ZQ and quietly wrong afterwards. Structured, not a text search: the function must
    consult BOTH the confirmation and the measurement."""
    from global_index import track1_paper_readiness as pr

    lines = pr.b1_lines(".")
    assert any(l.strip().startswith("decision") for l in lines), lines
    assert any(l.strip().startswith("measurement") for l in lines), lines
    assert any("orders_possible" in l for l in lines), lines

    tree = ast.parse((REPO / "global_index/track1_paper_readiness.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "b1_lines")
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "load_confirmations" in attrs, "the decision half is not consulted"
    assert "latest" in attrs, "the measurement half is not consulted"
