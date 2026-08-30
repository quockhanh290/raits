"""scratch/test_track1_stage5b_runbook_fix_20260823.py — the Stage 5B gate.

    python -m pytest scratch/test_track1_stage5b_runbook_fix_20260823.py -q

Offline. No scheduler started, no IBKR, no order, no dashboard write, no network. Nothing here
creates STOP_TRADING or track1_go_live_confirmation.json — the confirmation template is parsed
from a copy written into pytest's temporary directory.

What this suite is for
----------------------
Stage 5 audited the switch-over runbook read-only and found four defects that would each have
failed at the moment of use rather than in advance. A document cannot be kept correct by being
careful, so each fix is pinned here:

  * the S4 confirmation template was REFUSED by the schema, granting zero flags
  * precondition 4's check named a local variable and raised AttributeError
  * precondition 2 claimed a live decision the route cannot yet take
  * the kill switch was placed before the scheduler SWAP, when it must precede any START

The last one is the one with teeth: `--track1-shadow` adds Track 1's jobs without removing
legacy's, so starting the scheduler in shadow mode re-arms 23 legacy entry slots.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
from pathlib import Path

import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import run_scheduler as rs  # noqa: E402
from global_index import track1_gates as g  # noqa: E402
from global_index import track1_slots as ts  # noqa: E402

RUNBOOK = Path("docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md")


@pytest.fixture(scope="module")
def book() -> str:
    assert RUNBOOK.exists(), RUNBOOK
    return RUNBOOK.read_text(encoding="utf-8")


def json_blocks(text: str) -> list:
    return re.findall(r"```json\n(.*?)```", text, flags=re.S)


# ══════════════════════════════════════════════════════════════════════════════
# 1. the S4 confirmation template
# ══════════════════════════════════════════════════════════════════════════════
def test_the_runbook_contains_exactly_one_confirmation_template(book):
    blocks = [b for b in json_blocks(book) if "confirmed_by" in b]
    assert len(blocks) == 1, f"{len(blocks)} confirmation templates — which one does an operator copy?"


def test_the_template_parses_under_the_real_schema(tmp_path, book):
    """The defect, stated as a test: copy the template, hand it to the loader, get the flag.

    Written to tmp_path on purpose. Creating the real file would arm a route.
    """
    tpl = json.loads([b for b in json_blocks(book) if "confirmed_by" in b][0]
                     .replace("<name>", "audit")
                     .replace("<YYYY-MM-DD>", "2026-08-23")
                     .replace("<why, in one sentence>", "stage 5b template check"))
    f = tmp_path / "probe.json"
    f.write_text(json.dumps(tpl), encoding="utf-8")

    conf, errs = g.load_confirmations(f)
    assert errs == [], errs
    assert conf.get("legacy_retired_confirmed") is True, dict(conf.flags)
    assert not Path(g.CONFIRMATION_PATH).exists(), "this suite must not create the real file"


def test_the_template_names_no_key_the_schema_does_not_know(book):
    tpl = json.loads([b for b in json_blocks(book) if "confirmed_by" in b][0]
                     .replace("<name>", "x").replace("<YYYY-MM-DD>", "2026-08-23")
                     .replace("<why, in one sentence>", "x"))
    unknown = set(tpl) - set(g.CONFIRMATION_FLAGS) - set(g.CONFIRMATION_META)
    assert not unknown, unknown


@pytest.mark.parametrize("gone", ["scheduler_wiring_approved",
                                  "normal_generator_isolation_accepted",
                                  "calm_a_detector_accepted_frozen"])
def test_the_removed_flags_are_not_in_the_template(book, gone):
    """Each removed flag may still be NAMED in the prose that explains why it was removed —
    that history is worth keeping — but must not appear in a block anyone would copy."""
    for b in json_blocks(book):
        assert gone not in b, f"{gone} is still inside a copyable JSON block"
    assert gone not in g.CONFIRMATION_FLAGS


def test_the_runbook_says_not_to_write_the_file_early(book):
    seg = book[book.index("**S4 — record the confirmation.**"):]
    seg = seg[:seg.index("**S5")]
    assert "Do not write this file yet" in seg
    for word in ("broker", "S3", "operator"):
        assert word in seg, word


# ══════════════════════════════════════════════════════════════════════════════
# 2. STOP_TRADING must precede any scheduler START
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def job_ids():
    """Both scheduler configurations, built and discarded. Nothing is started."""
    logging.disable(logging.CRITICAL)
    try:
        off = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                               track1_shadow=False).get_jobs()}
        on = {j.id for j in rs.make_scheduler(port=4002, dry_run=True,
                                              track1_shadow=True).get_jobs()}
    finally:
        logging.disable(logging.NOTSET)
    return off, on


def test_shadow_mode_does_not_remove_a_single_legacy_entry_slot(job_ids):
    """The measured fact the whole S0b warning rests on.

    If this ever fails because shadow mode DID start isolating Track 1, the runbook's ordering
    advice becomes over-cautious rather than wrong — but it must be re-read, not left standing
    on a fact that stopped being true.
    """
    off, on = job_ids
    legacy_entries_off = {i for i in off if i.startswith("live_day")}
    legacy_entries_on = {i for i in on if i.startswith("live_day")}
    assert legacy_entries_off == legacy_entries_on, "shadow mode changed the legacy entry slots"
    assert len(legacy_entries_on) == 23, len(legacy_entries_on)
    assert len(on - off) == 25 and (off - on) == {"stop_repair_1220"}


def test_the_runbook_puts_the_kill_switch_before_any_start_not_before_the_swap(book):
    head = book[:book.index("## 3. Switch-over, in order")]
    assert "STOP_TRADING" in head, "the kill switch is not mentioned before the steps at all"
    low = head.lower()
    assert "before any scheduler start" in low or "before the first start" in low, \
        "the runbook does not say the kill switch precedes the START"
    assert "23" in head and "does not remove" in low, \
        "the runbook does not say shadow mode keeps the legacy entry slots"


def test_the_runbook_says_the_scheduler_is_down_and_why_that_matters(book):
    head = book[:book.index("## 3. Switch-over, in order")]
    low = head.lower()
    assert "not running" in low
    assert "2026-08-21" in head, "the date the system may have stopped trading is not given"
    for word in ("deliberate", "accidental"):
        assert word in low, word


# ══════════════════════════════════════════════════════════════════════════════
# 3. precondition 4, by effect
# ══════════════════════════════════════════════════════════════════════════════
def test_no_stop_repair_sweep_lands_inside_the_stress_window(job_ids):
    off, on = job_ids
    assert "stop_repair_1220" in off, "legacy lost its 12:20 sweep — that is a behaviour change"
    assert "stop_repair_1220" not in on
    assert off - on == {"stop_repair_1220"}, off - on


def test_the_stress_slots_span_the_declared_window(job_ids):
    _off, on = job_ids
    stress = sorted(i for i in on if i.startswith("track1_stress_"))
    assert stress[0] == "track1_stress_1035" and stress[-1] == "track1_stress_1230"
    assert len(stress) == 24, len(stress)          # 10:35..12:30 inclusive, every 5 minutes
    assert "track1_calm_1000" in on


def test_the_three_copies_of_the_window_agree():
    """Scheduler, slot table and dashboard mirror each hold the window. Three copies of one
    constant is how they drift, so the equality is asserted rather than assumed."""
    assert ts.REQUIRED_ENTRY_WINDOW == rs._TRACK1_STRESS_WINDOW
    old = os.environ.get("RAITS_TRACK1_SHADOW")
    try:
        for flag in ("0", "1"):
            os.environ["RAITS_TRACK1_SHADOW"] = flag
            import monitor.backend.schedule_status as ss
            importlib.reload(ss)
            assert ss.TRACK1_STRESS_WINDOW == ts.REQUIRED_ENTRY_WINDOW
            assert ss.track1_shadow_enabled() is (flag == "1")
            assert ts.parity_report(track1_shadow=(flag == "1"))["in_parity"]
    finally:
        if old is None:
            os.environ.pop("RAITS_TRACK1_SHADOW", None)
        else:
            os.environ["RAITS_TRACK1_SHADOW"] = old


def test_the_runbook_no_longer_offers_entry_windows_as_a_check(book):
    """One mention survives on purpose — the paragraph explaining why it cannot be used. What
    must not survive is it appearing as something to run."""
    lines = [L for L in book.split("\n") if "_ENTRY_WINDOWS" in L]
    assert len(lines) == 1, lines
    assert "local variable" in lines[0], lines[0]
    table = book[book.index("| # | precondition"):book.index("### Where each precondition")]
    assert "_ENTRY_WINDOWS" not in table, "the precondition table still names it as a check"


# ══════════════════════════════════════════════════════════════════════════════
# 4. precondition 2 must not overclaim, and 5/6 must not read as regressions
# ══════════════════════════════════════════════════════════════════════════════
def test_the_live_source_still_refuses_which_is_why_the_wording_changed():
    """The measurement behind the reworded precondition. If this ever starts returning a list,
    precondition 2b has genuinely passed and the runbook's status table needs updating —
    which is a better failure than the wording quietly becoming true."""
    from global_index import track1_sleeves as SL
    with pytest.raises(NotImplementedError):
        SL.load_source("live").candidates("today")


def test_readiness_is_green_which_is_why_the_two_halves_are_split():
    from global_index import track1_live_sleeves as LS
    assert LS.readiness()["blocked"] == [], "2a is no longer green — the split needs rereading"


def test_the_runbook_splits_the_promoted_claim_from_the_live_claim(book):
    table = book[book.index("| # | precondition"):book.index("### Where each precondition")]
    assert "| 2a |" in table and "| 2b |" in table, "precondition 2 was not split"
    assert "produce a live decision" not in table.split("| 2b |")[0], \
        "the promoted-generators row still claims a live decision"

    seg = book[book.index("### Where each precondition"):]
    seg = seg[:seg.index("### How to check 4")]
    assert "never" in seg and "Track 1 can trade today" in seg, \
        "the runbook does not say plainly that the live claim is not yet true"


def test_the_runbook_says_five_and_six_are_expected_to_fail_before_the_first_shadow_run(book):
    seg = book[book.index("### Where each precondition"):]
    seg = seg[:seg.index("### How to check 4")]
    assert "EXPECTED to fail" in seg
    # Stage 5B asserted the runbook said "starting is what fixes them". Stage 5D MEASURED
    # that claim and it was false - the slots replayed history and the two recorders had no
    # callers - so this test was pinning a wrong sentence in place. What it pins now is the
    # retraction and the reason, which is what a reader actually needs.
    assert "Correction (Stage 5D)" in seg, "the runbook does not retract the earlier claim"
    assert "zero callers" in seg
    assert "live_source_not_ready" in seg, (
        "the runbook does not name what still holds 5 and 6 shut")


def test_the_five_and_six_claims_match_what_is_on_disk():
    """The runbook's status table is a measurement, so it is checked against the disk rather
    than trusted. Both must still be failing, or the table is stale."""
    import glob
    assert not glob.glob("window_coverage_*.jsonl"), "coverage exists — the table says it does not"
    assert not glob.glob("**/window_coverage_*.jsonl", recursive=True)
    assert not Path("global_index/replay_checkpoint.track1.json").exists()


# ══════════════════════════════════════════════════════════════════════════════
# 5. the broker caveat
# ══════════════════════════════════════════════════════════════════════════════
def test_the_runbook_says_local_flat_is_not_broker_flat(book):
    seg = book[book.index("### Precondition 7 is two checks"):]
    seg = seg[:seg.index("---")]
    assert "not flat until IBKR has been asked" in seg
    assert "working stop orders with no position behind them" in seg
    low = seg.lower()
    assert "never" in low and "connect" in low,         "the runbook does not say the broker half has not been checked"


def test_the_runbook_warns_the_account_holds_more_than_this_system(book):
    seg = book[book.index("**S3 — cancel every working stop"):]
    seg = seg[:seg.index("**S4")]
    assert "ever been run" in seg, "S3 does not say it has never been run"
    assert "empty account" in seg, "the runbook does not warn how to read a broker screen"


def test_nothing_in_this_suite_created_a_live_artefact():
    for f in ("track1_go_live_confirmation.json", "STOP_TRADING", "STOP_TRADING.track1",
              "live_positions.track1.json", "runner.track1.pid"):
        assert not Path(f).exists(), f
    assert os.environ.get("TRACK1_ORDERS_APPROVED") is None
    # Property, not a count. This line used to pin the blocker list to exactly one element,
    # which made it red the moment a MEASURED gate legitimately re-shut — and a measured gate
    # re-shutting is the mechanism working, not a regression. What must hold is that orders are
    # impossible and that B1 is among the reasons; an extra blocker is allowed only if it is
    # genuinely holding.
    _blockers = {b.id for b in g.blocking()}
    assert "B1_broker_account_or_legacy_retirement" in _blockers, _blockers
    assert g.may_enable_orders()[0] is False
    for _extra in _blockers - {"B1_broker_account_or_legacy_retirement"}:
        _b = g.BLOCKERS[_extra]
        assert _b.blocks_orders and not _b.released(g.NO_CONFIRMATIONS), _extra
    # Derived, not a literal: B1 plus whichever MEASURED gates are shut right now.
    # Written this way in Stage 5S because the literal had already been rewritten
    # twice by a measured gate opening and closing, and chasing that is not a test.
    _measured_shut = {b.id for b in g.BLOCKERS.values()
                      if b.released_by_measurement and not b.measure()[0]}
    assert _blockers == {"B1_broker_account_or_legacy_retirement"} | _measured_shut, _blockers
