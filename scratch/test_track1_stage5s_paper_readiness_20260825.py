"""Stage 5S — the paper-readiness gate: explicit, machine-checkable, and unable to fail open.

READ-ONLY of production data. No scheduler, no backend, no broker, no order, no confirmation
file. Every audit record these tests read is written under `tmp_path`.

The defect this closes
----------------------
Before Stage 5S every condition on the order gate was about AUTHORISATION and none was about
EVIDENCE: B1 is a decision on disk, the live-frame gate measures wiring,
`TRACK1_ORDERS_APPROVED` is an out-of-band approval, `--allow-orders` is a request.
`track1_shadow_acceptance` computes daily whether the route did what it was supposed to, and
nothing that decides whether orders may be sent had ever read it.

Measured: with a confirmation file releasing B1 and **zero** judgeable shadow days,
`may_enable_orders()` returned **True** before this stage and returns **False** after it.

The two halves this file holds open
-----------------------------------
1. the gate must REFUSE on missing, stale, failing or unreadable evidence, and
2. it must still be able to OPEN — a gate that can never move is not a gate, it is a wall
   with a story attached.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(r"d:\raits")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_gates as gates                 # noqa: E402
from global_index import track1_paper_readiness as pr          # noqa: E402
from global_index import track1_shadow_acceptance as acc       # noqa: E402

SLEEVES = ("roska4_swing", "roska4_calm", "roska4_stress", "global_nkd")


def write_day(root: Path, day: str, *, day_verdict=acc.AUDIT_PASS,
              sleeve_verdicts=None, route=acc.AUDIT_ROUTE) -> None:
    """One day's audit records, in the shape the real audit writes them."""
    d = root / acc.AUDITS_DIR
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"track1_audit_{day.replace('-', '')}.jsonl"
    sv = sleeve_verdicts or {s: acc.AUDIT_PASS for s in SLEEVES}
    rows = [{"schema": "x", "scope": "sleeve", "sleeve": s, "session_day": day,
             "route": route, "verdict": v, "runtime_p95_s": 3.0}
            for s, v in sv.items()]
    rows.append({"schema": "x", "scope": "day", "sleeve": None, "session_day": day,
                 "route": route, "verdict": day_verdict})
    with f.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def calm_intent(root: Path, day: str) -> None:
    """Stage 5ZX. The Calm decision evidence a judgeable day now carries.

    A clean shadow period grew a part. Until 5ZX the Calm slot fired at the entry instant and
    refused every morning, so no day could carry its evidence and the gate did not ask for it.
    Now the sleeve decides at half past nine and records the reference afterwards, and a day
    without both halves is a day the route was not watching Calm on.

    Written through the module's own builders, not as hand-made dicts: a fixture that invents
    its own row shape stops agreeing with the schema the moment the schema moves, and would
    keep this test green through exactly the change it should catch.
    """
    from global_index import track1_shadow_intent as si

    be = {"setup": "calm_a", "instrument": "MES", "direction": "LONG", "qty": 1,
          "stop_rule": "entry - 1.5 x daily_atr",
          "risk_inputs": {"daily_atr_causal": 68.55, "point_value": 5.0,
                          "stop_atr_mult": 1.5, "stop_distance": 102.825},
          "entry_reference_time": "10:00", "intent": "would_send_at_entry_reference_time"}
    si.append(si.decide_row("TRACK1_CALM_DECIDE_0932", day, status=si.RECORDED,
                            reason_code=si.OK, before_entry=be), root=root, day=day)
    si.append(si.observe_row("TRACK1_CALM_OBSERVE_1002", day, status=si.RECORDED,
                             reason_code=si.OK, before_entry=be,
                             after_reference={"entry_reference_price": 7680.75,
                                              "planned_stop": si.planned_stop_from(
                                                  7680.75, 68.55, 1.5)}),
              root=root, day=day)


def account_baseline(root: Path) -> None:
    """Stage 5ZZE. The paper account the route would start from, proven against the broker.

    A clean shadow period grew a part again. Five judgeable mornings say the route watched
    correctly; they say nothing about which account it would start from — and on 2026-08-27 the
    B1 record was still inside its own window while carrying an equity 299% away from the stated
    baseline, because the account had been reset underneath it and B1's window is about
    positions and orders, not about accounts.

    Built through the module's own measure/record rather than as a hand-made row: a fixture that
    invents its own shape stops agreeing with the schema the moment the schema moves, and would
    keep this test green through exactly the change it should catch.
    """
    from global_index import track1_account_baseline as ab
    from global_index import track1_b1 as b1

    flat = b1.BookState(path="x", state=b1.BOOK_READ, count=0, positions=[], error="")
    ev = b1.from_direct_probe({"source": "ibkr_direct", "connected": True,
                               "observed_at": ab._now(), "positions": [], "open_orders": []})
    acct = ab.from_account_values(
        [{"tag": "NetLiquidation", "currency": "USD", "value": 250_000.0}],
        account_id="DU_TEST")
    ab.record(ab.measure(acct, b1.measure(flat, flat, ev)), root, source="test-fixture")


def good_period(root: Path, days=("2026-08-17", "2026-08-18", "2026-08-19",
                                  "2026-08-20", "2026-08-21")) -> None:
    for d in days:
        write_day(root, d)
        calm_intent(root, d)
    account_baseline(root)


# ══════════════════════════════════════════════════════════════════════════════
# It can OPEN — otherwise nothing below proves anything
# ══════════════════════════════════════════════════════════════════════════════

def test_a_clean_shadow_period_satisfies_the_evidence_gate(tmp_path):
    good_period(tmp_path)
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["ready"] is True, [c for c in r["checks"] if c["status"] != "ok"]
    assert pr.gate_measurement(tmp_path)[0] is True


def test_with_evidence_AND_a_confirmation_the_order_gate_would_arm(tmp_path, monkeypatch):
    """The control. If this cannot pass, every refusal in this file is decoration."""
    good_period(tmp_path)
    monkeypatch.setattr(gates, "shadow_evidence",
                        lambda root=".": pr.gate_measurement(tmp_path))
    monkeypatch.setitem(gates.MEASUREMENTS, "shadow_evidence",
                        lambda root=".": pr.gate_measurement(tmp_path))
    # Stage 5ZL added a second measured gate, and this control has to satisfy every measured
    # gate or it stops being a control and becomes a test of which gates existed the day it
    # was written. The regime verification is answered from the same temp root.
    from global_index import regime_verify as rv
    rv.record(rv.VerifyResult(status=rv.PASS, code=rv.OK, detail="control",
                              checked_at=rv._now()), root=tmp_path, source="test")
    monkeypatch.setitem(gates.MEASUREMENTS, "regime_labels_verified",
                        lambda root=".": gates.regime_labels_verified(tmp_path))
    conf = gates.Confirmations({"legacy_retired_confirmed": True}, "t", "t", "(t)")
    ok, why = gates.may_enable_orders(conf)
    assert ok is True, why


# ══════════════════════════════════════════════════════════════════════════════
# It REFUSES on missing, stale, failing or unreadable evidence
# ══════════════════════════════════════════════════════════════════════════════

def test_no_evidence_at_all_is_refused(tmp_path):
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["ready"] is False
    names = {c["name"] for c in r["checks"] if c["status"] != "ok"}
    assert "judgeable_days" in names
    assert "evidence_is_recent" in names


def test_absence_is_never_a_pass_even_with_the_directory_present(tmp_path):
    (tmp_path / acc.AUDITS_DIR).mkdir(parents=True)
    assert pr.readiness(tmp_path, today="2026-08-24")["ready"] is False


def test_too_few_judgeable_days_is_refused(tmp_path):
    good_period(tmp_path, days=("2026-08-20", "2026-08-21"))
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["ready"] is False
    c = next(c for c in r["checks"] if c["name"] == "judgeable_days")
    assert c["have"] == 2 and c["required"] == pr.REQUIRED_JUDGEABLE_DAYS


def test_not_enough_data_yet_days_do_not_count_as_judgeable(tmp_path):
    """A window that closed before the scheduler started is not a day that went well."""
    good_period(tmp_path, days=("2026-08-20", "2026-08-21"))
    for d in ("2026-08-17", "2026-08-18", "2026-08-19"):
        write_day(tmp_path, d, day_verdict=acc.AUDIT_NOT_ENOUGH_DATA_YET)
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["ready"] is False
    assert r["detail"]["judgeable_days"] == ["2026-08-20", "2026-08-21"]


def test_a_failing_day_inside_the_window_is_refused(tmp_path):
    good_period(tmp_path)
    write_day(tmp_path, "2026-08-24", day_verdict=acc.AUDIT_FAIL)
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["ready"] is False
    c = next(c for c in r["checks"] if c["name"] == "no_failing_days")
    assert c["failing"] == ["2026-08-24"]


def test_stale_evidence_is_refused_however_clean_it_was(tmp_path):
    """Five perfect days in August do not make December ready."""
    good_period(tmp_path)
    r = pr.readiness(tmp_path, today="2026-12-01")
    assert r["ready"] is False
    c = next(c for c in r["checks"] if c["name"] == "evidence_is_recent")
    assert c["age_days"] > pr.MAX_EVIDENCE_AGE_DAYS


def test_a_sleeve_that_never_passed_is_refused(tmp_path):
    sv = {s: acc.AUDIT_PASS for s in SLEEVES}
    sv["global_nkd"] = acc.AUDIT_WARN
    for d in ("2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"):
        write_day(tmp_path, d, sleeve_verdicts=sv)
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["ready"] is False
    c = next(c for c in r["checks"] if c["name"] == "every_sleeve_passed_at_least_once")
    assert c["missing"] == ["global_nkd"]


def test_one_warn_day_is_tolerated_and_two_are_not(tmp_path):
    """WARN is "it worked and something is worth looking at" — p95 over the 240s target but
    under the 300s ceiling is the ordinary case. One is tolerated so a single slow afternoon
    cannot decide the gate; two are not, so the target keeps meaning something.

    Both cases are BUILT rather than produced by editing the first one's text: the first
    attempt rewrote the file and its replace landed on a sleeve verdict instead of the day
    verdict, so the "two WARN days" case still had one.
    """
    days = ("2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21")

    one = tmp_path / "one"
    for i, d in enumerate(days):
        write_day(one, d, day_verdict=acc.AUDIT_WARN if i < 1 else acc.AUDIT_PASS)
        calm_intent(one, d)          # Stage 5ZX: a judgeable day now carries Calm evidence
    account_baseline(one)            # Stage 5ZZE: and the account it would start from
    r1 = pr.readiness(one, today="2026-08-24")
    assert [c["warning"] for c in r1["checks"]
            if c["name"] == "warn_days_within_allowance"] == [["2026-08-17"]]
    assert r1["ready"] is True

    two = tmp_path / "two"
    for i, d in enumerate(days):
        write_day(two, d, day_verdict=acc.AUDIT_WARN if i < 2 else acc.AUDIT_PASS)
        calm_intent(two, d)
    account_baseline(two)
    r2 = pr.readiness(two, today="2026-08-24")
    c = next(c for c in r2["checks"] if c["name"] == "warn_days_within_allowance")
    assert c["warning"] == ["2026-08-17", "2026-08-18"]
    assert len(c["warning"]) > pr.MAX_WARN_DAYS
    assert r2["ready"] is False


def test_an_unreadable_audit_line_counts_against_readiness(tmp_path):
    good_period(tmp_path)
    f = next((tmp_path / acc.AUDITS_DIR).glob("*.jsonl"))
    f.write_text(f.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["ready"] is False
    c = next(c for c in r["checks"] if c["name"] == "audit_records_readable")
    assert c["unreadable"] == 1


def test_records_for_another_route_are_ignored_not_counted(tmp_path):
    for d in ("2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"):
        write_day(tmp_path, d, route="legacy")
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["ready"] is False
    assert r["detail"]["judgeable_days"] == []


def test_the_later_record_for_a_day_wins(tmp_path):
    """A sleeve is audited when its window closes and again in the daily sweep. Taking the
    FIRST would grade it on a moment when its peers had not run."""
    good_period(tmp_path, days=("2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20"))
    write_day(tmp_path, "2026-08-21", day_verdict=acc.AUDIT_FAIL)
    write_day(tmp_path, "2026-08-21", day_verdict=acc.AUDIT_PASS)
    calm_intent(tmp_path, "2026-08-21")
    account_baseline(tmp_path)
    r = pr.readiness(tmp_path, today="2026-08-24")
    assert r["detail"]["days"]["2026-08-21"]["verdict"] == acc.AUDIT_PASS
    assert r["ready"] is True


def test_the_measurement_fails_closed_when_it_cannot_run(monkeypatch):
    """Unknown is not the same as ready. This is the one place where getting that backwards
    would OPEN a gate — the shape `scheduler_processes()` returning [] for "I could not tell"
    already cost this project six entry slots."""
    monkeypatch.setattr(pr, "readiness",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    released, detail = pr.gate_measurement(".")
    assert released is False
    assert "unknown is not the same as ready" in detail


# ══════════════════════════════════════════════════════════════════════════════
# The gate registry
# ══════════════════════════════════════════════════════════════════════════════

def test_the_blocker_is_registered_and_blocks_orders():
    b = gates.BLOCKERS["PAPER_SHADOW_EVIDENCE"]
    assert b.blocks_orders is True
    assert b.status == gates.MEASURED_GATE
    assert b.released_by == (), "evidence must not be releasable by a confirmation flag"
    assert b.released_by_measurement == "shadow_evidence"
    assert gates.self_check() == []


def test_a_confirmation_file_alone_no_longer_arms_the_gate():
    """The defect, pinned. With B1 released and no shadow evidence, `may_enable_orders`
    returned True before Stage 5S."""
    conf = gates.Confirmations({"legacy_retired_confirmed": True}, "t", "t", "(t)")
    ok, why = gates.may_enable_orders(conf)
    assert ok is False
    assert any("PAPER_SHADOW_EVIDENCE" in w for w in why)


def test_removing_the_evidence_blocker_is_what_the_defect_looked_like(monkeypatch):
    """The counterfactual, run rather than described."""
    saved = dict(gates.BLOCKERS)
    try:
        gates.BLOCKERS.pop("PAPER_SHADOW_EVIDENCE")
        # Stage 5ZL: the counterfactual is about the EVIDENCE blocker, so every other measured
        # gate must be out of the way or this asserts something it does not mean.
        gates.BLOCKERS.pop("REGIME_LABEL_VERIFICATION")
        conf = gates.Confirmations({"legacy_retired_confirmed": True}, "t", "t", "(t)")
        assert gates.may_enable_orders(conf)[0] is True
    finally:
        gates.BLOCKERS.clear()
        gates.BLOCKERS.update(saved)
    assert gates.may_enable_orders(
        gates.Confirmations({"legacy_retired_confirmed": True}, "t", "t", "(t)"))[0] is False


# ══════════════════════════════════════════════════════════════════════════════
# No accidental go-live path
# ══════════════════════════════════════════════════════════════════════════════

def test_the_scheduler_never_passes_allow_orders():
    src = Path("global_index/run_scheduler.py").read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value == "--allow-orders"]
    assert literals == [], "the scheduler builds an argv containing --allow-orders"


def test_ops_never_passes_allow_orders_or_sets_the_approval_env():
    src = Path("monitor/ops.py").read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    bad = [n.value for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and n.value in ("--allow-orders",)]
    assert bad == []
    # it may MENTION the env var to report it; it must never assign it
    assigns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant)
               and n.slice.value == "TRACK1_ORDERS_APPROVED"
               and isinstance(getattr(n, "ctx", None), ast.Store)]
    assert assigns == [], "ops.py assigns TRACK1_ORDERS_APPROVED"


def test_the_runner_holds_a_broker_that_cannot_send(monkeypatch):
    """Even fully armed, `run_shadow` hands the route a NoOrderBroker whose send_order raises.
    Paper mode — swapping in a real broker — is NOT implemented, and this pins that so the day
    it is, someone has to change this test on purpose."""
    import ast

    from global_index import run_live_day_track1 as R
    tree = ast.parse(Path(R.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_shadow")
    made = [n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "NoOrderBroker" in made
    assert "IBKRBroker" not in made
    with pytest.raises(RuntimeError):
        R.NoOrderBroker().send_order(object())


def test_the_route_never_writes_legacy_state():
    from global_index import run_live_day_track1 as R
    assert "live_positions.json" in R.LEGACY_PATHS
    assert "global_index/replay_checkpoint.json" in R.LEGACY_PATHS


# ══════════════════════════════════════════════════════════════════════════════
# The evidence the gate reads is DURABLE, not scratch
# ══════════════════════════════════════════════════════════════════════════════

def test_the_acceptance_gate_reads_the_durable_runtime_root_not_scratch():
    for const in (acc.COVERAGE_DIR, acc.TIMING_DIR, acc.AUDITS_DIR):
        assert const.startswith("global_index/track1_runtime/"), const
        assert "scratch" not in const, const


def test_the_thresholds_are_gathered_in_one_place():
    """They are judgement calls, not derived quantities. A reader has to be able to find them
    without grepping a checker."""
    for name in ("REQUIRED_JUDGEABLE_DAYS", "MAX_FAIL_DAYS", "MAX_WARN_DAYS",
                 "MAX_EVIDENCE_AGE_DAYS", "REQUIRED_SLEEVES"):
        assert hasattr(pr, name), name
    r = pr.readiness(".", today="2026-08-24")
    assert r["thresholds"]["REQUIRED_JUDGEABLE_DAYS"] == pr.REQUIRED_JUDGEABLE_DAYS
    assert r["thresholds"]["runtime_p95_required_s"] == acc.RUNTIME_P95_REQUIRED_S
    assert r["thresholds"]["runtime_p95_target_s"] == acc.RUNTIME_P95_TARGET_S


def test_no_confirmation_file_was_created_by_this_suite():
    """Stage 5ZZS. An eleventh test of the same family, found by running the adjacent suites.

    It asserted the absence of a file Stage 5ZZJ deliberately placed. What the suite can still
    hold is that IT did not write one, and a file this suite had written would be unsigned.
    """
    import os
    conf = Path(gates.CONFIRMATION_PATH)
    if conf.exists():
        c, errors = gates.load_confirmations(gates.CONFIRMATION_PATH)
        assert errors == [], errors
        assert (c.confirmed_by or "").strip(), "an unsigned decision appeared on disk"
        # and readiness must not have become "ready" because of it
        allowed, _why = gates.may_enable_orders()
        assert allowed is False, "a signed decision must not make orders possible"
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "")
