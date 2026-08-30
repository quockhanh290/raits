"""Stage 5ZZF — the dashboard was subtracting across a currency boundary, three days late.

Measured on the live endpoints before anything was changed:

    /api/v1/track1-runtime  paper_account   USD 250,817.91   PASS    <- correct
    /api/v1/broker          payload.equity      250,818.18   fresh   <- correct, live drift
    /api/v1/runner-state    meta.broker_equity  996,730.93           <- 76.8 hours old
                            meta.paper_start    1,000,480.00 "CAD"   <- a different era

and the line the page drew from the last two:

    Broker acct $996,731 / -$3,749 since 2026-07-08

Two faults in one sentence. The subtraction crossed a currency boundary — the start carries its
own note saying CAD and the equity carries no currency at all — and the payload was three days
old while its envelope said `freshness: not_expected_yet`, because in track1-only mode the legacy
runner is never scheduled, so nothing ever calls it stale.

Nothing here connects to a broker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "monitor"))

from monitor.backend import open_issue_reader as oir  # noqa: E402

JS = (REPO / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# 1-5  open issues are scoped, and nothing is removed
# ═══════════════════════════════════════════════════════════════════════════════

def _issues(*keys, status="incident"):
    return [{"key": k, "status": status, "component": "runner", "title": k} for k in keys]


def test_1_legacy_paper_issues_are_scoped_legacy_and_are_not_track1_blockers():
    got = oir._scoped(_issues("paper:lifecycle:unresolved",
                              "paper:pnl:paper_flex_total_mismatch",
                              "paper:decision_path:unresolved"))
    for i in got:
        assert i["route_scope"] == oir.SCOPE_LEGACY, i["key"]
        assert i["track1_readiness_blocker"] is False
        assert "no Track 1 artefact" in i["scope_reason"]


def test_2_scheduler_and_debt_get_their_own_scopes():
    sched = oir._scoped(_issues("job:session_report:missed"))[0]
    assert sched["route_scope"] == oir.SCOPE_SCHEDULER
    assert "both routes" in sched["scope_reason"]

    debt = oir._scoped(_issues("known_debt:model_age", status="known_debt"))[0]
    assert debt["route_scope"] == oir.SCOPE_DEBT
    assert "does not disappear" in debt["scope_reason"]


def test_3_a_track1_issue_would_be_scoped_track1():
    got = oir._scoped(_issues("track1:window:uncovered"))[0]
    assert got["route_scope"] == oir.SCOPE_TRACK1
    # and even a Track 1-scoped issue does not declare itself a readiness blocker
    assert got["track1_readiness_blocker"] is False


def test_4_nothing_is_deleted_hidden_or_downgraded():
    """The whole point. An issue that was open stays open, keeps its evidence and its place."""
    before = _issues("paper:lifecycle:unresolved", "job:session_report:missed")
    before.append({"key": "known_debt:model_age", "status": "known_debt",
                   "component": "runner", "title": "Model age"})
    snapshot = json.loads(json.dumps(before))

    after = oir._scoped(before)
    assert len(after) == len(snapshot), "an issue disappeared"
    for old, new in zip(snapshot, after):
        for field in old:
            assert new[field] == old[field], f"{field} was changed on {old['key']}"
    added = set(after[0]) - set(snapshot[0])
    assert added == {"route_scope", "scope_reason", "track1_readiness_blocker"}, added


def test_5_the_reader_says_where_track1_blockers_actually_come_from():
    """A log parser must not hold a second opinion about what blocks orders."""
    assert oir.TRACK1_BLOCKERS_ARE_DECIDED_BY == "global_index.track1_gates.blocking()"
    # `read_open_issues` memoises on a file/date signature. Without clearing it this asks a
    # cached answer from whenever it was first called, which is not a measurement of the code
    # as it stands — and it is what let a mutation of the builder change nothing at all.
    oir._cache.clear()
    d = oir.read_open_issues(REPO)
    assert d["issues"], "no issues at all — this test would pass on an empty list"
    assert d.get("track1_readiness_blockers_come_from") == oir.TRACK1_BLOCKERS_ARE_DECIDED_BY
    assert isinstance(d.get("scopes"), list)
    for i in d["issues"]:
        assert i["route_scope"] in (oir.SCOPE_TRACK1, oir.SCOPE_LEGACY,
                                    oir.SCOPE_SCHEDULER, oir.SCOPE_DEBT)
        assert i["track1_readiness_blocker"] is False


def _issue_count() -> int:
    oir._cache.clear()
    return len(oir.read_open_issues(REPO)["issues"])


def test_6_a_clean_track1_baseline_clears_no_legacy_issue(tmp_path):
    """Recording a passing account baseline is not a reason for a legacy reconciliation issue
    to go away, and the two must not be wired to each other at all."""
    from global_index import track1_account_baseline as ab
    from global_index import track1_b1 as b1

    before = _issue_count()
    assert before, "no issues to begin with — this test would pass on an empty list"
    flat = b1.BookState(path="x", state=b1.BOOK_READ, count=0, positions=[], error="")
    ev = b1.from_direct_probe({"source": "ibkr_direct", "connected": True,
                               "observed_at": ab._now(), "positions": [], "open_orders": []})
    acct = ab.from_account_values(
        [{"tag": "NetLiquidation", "currency": "USD", "value": 250_000.0}])
    ab.record(ab.measure(acct, b1.measure(flat, flat, ev)), tmp_path)

    after = _issue_count()
    assert after == before, "recording a baseline changed the open-issue count"


# ═══════════════════════════════════════════════════════════════════════════════
# 7-11  the equity line reads from the right source
# ═══════════════════════════════════════════════════════════════════════════════

def _equity_block() -> str:
    """The account-line code, bounded at its own end.

    The first version took a fixed 3,000 characters and ran past the function into
    `runnerFreshnessText`, so an assertion about what the account line does was reading a
    different function's source. A slice with no end is a slice that will one day contain the
    next thing somebody writes.
    """
    i = JS.index("const acct = state.track1?.paper_account")
    j = JS.index("el.className = tone;", i)
    return JS[i:j]


def _code_only(text: str) -> str:
    """`text` with `//` comments removed.

    Substring assertions over source read prose as code. This file's own comments quote the old
    label — "Broker acct $996,731" — to record what was wrong, and a test searching the raw
    text finds the quotation and reports the defect it describes. That trap has now caught this
    project four times; the reader strips comments before looking.
    """
    out = []
    for line in text.splitlines():
        k = line.find("//")
        # not inside a string: good enough here, and a false trim would only make the check
        # stricter rather than looser
        out.append(line if k < 0 else line[:k])
    return "\n".join(out)


JS_CODE = _code_only(JS)


def test_7_the_track1_baseline_is_read_first():
    b = _equity_block()
    assert "state.track1?.paper_account" in b
    # and it is preferred over both other sources
    assert b.index("state.track1?.paper_account") < b.index("meta.broker_equity")


def test_8_the_legacy_number_may_never_be_called_the_broker_account():
    """It said `Broker acct $996,731` for three days after the reset."""
    b = _equity_block()
    assert "Broker acct" not in JS_CODE, "the old label is still rendered by the page"
    # and it survives in the comments on purpose, as the record of what was wrong
    assert "Broker acct" in JS, "the note explaining what this replaced was deleted too"
    assert "Legacy runner state" in b, "the legacy figure has no name of its own"
    # and wherever it appears it carries its age
    legacy_line = b[b.index("Legacy runner state"):b.index("Legacy runner state") + 260]
    assert "age(legacyAgeS)" in legacy_line, "the legacy figure is shown without its age"


def test_9_the_cross_currency_subtraction_is_gone():
    """`meta.broker_equity - meta.paper_start.equity` mixed an unlabelled number with one whose
    own note says CAD, and printed the difference with a dollar sign."""
    assert "brokerEquity - paperStart" not in JS_CODE
    assert "paper_start?.equity" not in JS_CODE, \
        "the CAD-era starting figure is still being read into a visible number"


def test_10_a_fresh_broker_reading_is_labelled_and_not_merged():
    b = _equity_block()
    assert "state.broker?.payload?.equity" in b
    assert "broker now" in b, "the live reading has no label of its own"
    assert "brokerUsable()" in b, "a stale broker reading could be shown as current"


def test_11_a_material_divergence_is_called_out():
    # Stage 5ZZH renamed the clause to "Legacy runner state ${legacyStale ? 'stale: ' : ''}"
    # so it says WHY the figure is not the account. The pin follows the clause; the three
    # things it has always asserted are unchanged: the legacy figure is named, there IS a
    # threshold, and crossing it turns the line negative instead of sitting there quietly.
    b = _equity_block()
    assert "Legacy runner state" in b
    assert "> 0.10" in b, "there is no threshold, so nothing can be 'material'"
    seg = b[b.index("Legacy runner state"):]
    assert "tone = 'negative'" in seg[:400]


def test_12_no_raw_field_names_reach_the_visible_text():
    b = _equity_block()
    visible = [ln for ln in b.splitlines()
               if "text =" in ln or "text +=" in ln]
    assert visible, "no visible text was built — this test would pass on nothing"
    for ln in visible:
        for raw in ("broker_equity", "paper_start", "paper_account", "runner_state",
                    "age_seconds"):
            assert raw not in ln, f"raw field name in visible text: {ln.strip()}"


# ═══════════════════════════════════════════════════════════════════════════════
# 13-14  the panel still reads the baseline, not B1's old equity
# ═══════════════════════════════════════════════════════════════════════════════

def test_13_the_track1_panel_reads_the_account_baseline(tmp_path):
    from monitor.backend import track1_runtime_reader as rd

    src = Path(rd.__file__).read_text(encoding="utf-8")
    assert "track1_account_baseline" in src
    # B1's own recorded equity must not be the source of the panel's account figure
    i = src.index("def _paper_account")
    body = src[i:i + 2500]
    assert "track1_b1" not in body, \
        "the panel reads B1's equity, which is the number that was three hundred per cent wrong"


def test_14_the_panel_block_and_the_issue_list_are_different_things():
    from monitor.backend import track1_runtime_reader as rd

    d = rd._paper_account(REPO)
    assert d["separate_from_shadow_evidence"] is True
    assert "issues" not in d and "open_issues" not in d


# ═══════════════════════════════════════════════════════════════════════════════
# 15  the freshness model that could not report a stopped producer
# ═══════════════════════════════════════════════════════════════════════════════

def test_15_the_page_does_not_trust_runner_freshness_for_the_account_line():
    """Measured: the runner-state envelope reported `not_expected_yet` at 76.8 hours old,
    because in track1-only mode the legacy runner is never scheduled and `expected_next_at`
    keeps sliding forward. A freshness model that assumes its producer still runs cannot report
    a producer that has stopped — so the account line does not ask it."""
    b = _equity_block()
    assert "not_expected_yet" not in b
    assert "state.runner?.freshness" not in b, \
        "the account line gates on a freshness that cannot go stale in this mode"
    # it uses the age instead, which is a fact rather than a schedule
    assert "state.runner?.age_seconds" in b


# ═══════════════════════════════════════════════════════════════════════════════
# mutations
# ═══════════════════════════════════════════════════════════════════════════════

def _must_fail(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except AssertionError:
        return True
    return False


def test_M1_legacy_issues_promoted_to_track1_mutation(monkeypatch):
    """Collapse: a legacy paper issue starts claiming it blocks Track 1."""
    monkeypatch.setattr(oir, "_route_scope",
                        lambda issue: (oir.SCOPE_TRACK1, "mutated"))
    assert _must_fail(test_1_legacy_paper_issues_are_scoped_legacy_and_are_not_track1_blockers), \
        "test_1 stayed green while a legacy issue was scoped to Track 1"


def test_M2_scoping_starts_dropping_issues_mutation(monkeypatch):
    """Collapse: the classifier quietly filters instead of labelling."""
    monkeypatch.setattr(oir, "_scoped",
                        lambda issues: [i for i in issues if not i["key"].startswith("paper:")])
    oir._cache.clear()
    try:
        assert _must_fail(test_4_nothing_is_deleted_hidden_or_downgraded), \
            "test_4 stayed green while scoping removed issues from the list"
    finally:
        oir._cache.clear()


def test_M3_the_reader_starts_declaring_its_own_blockers_mutation(monkeypatch):
    monkeypatch.setattr(oir, "_scoped",
                        lambda issues: [dict(i, route_scope=oir.SCOPE_TRACK1,
                                             scope_reason="m",
                                             track1_readiness_blocker=True) for i in issues])
    oir._cache.clear()
    try:
        assert _must_fail(test_5_the_reader_says_where_track1_blockers_actually_come_from), \
            "test_5 stayed green while the log parser declared its own readiness blockers"
    finally:
        # leave no mutated answer behind for whatever runs next
        oir._cache.clear()
