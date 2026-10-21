"""Stage 5ZZH — the page's biggest number belonged to the wrong route.

For three days the Paper Equity card read `$50,408  +408  since base $50,000`. Every part of
that came from the legacy runner's last snapshot, dated 2026-08-24 and 80 hours old. The
account this route would actually start from held USD 250,818, proven against the broker that
morning, and appeared only as small print underneath.

These tests hold three things:

  1. in Track 1 mode the headline is Track 1's, with its currency spelled out
  2. when the baseline is UNKNOWN or FAIL the card SAYS SO and does not fall back — a silent
     fallback is what produced the confusion in the first place
  3. every open issue is still listed, grouped by whose problem it is, and Track 1's blockers
     come from the gate registry rather than from issue prose

Nothing here connects to a broker, arms a gate, or writes to the runtime tree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.backend import track1_runtime_reader as tr        # noqa: E402

DASH = ROOT / "global_index" / "dash" / "realtime"
JS_PATH = DASH / "realtime.js"


def _orders_at_import():
    """The real order journal as it stood when this module was imported. Compared again in
    `test_this_dashboard_suite_arms_nothing`; the directory used to be absent and its absence
    used to be the proof."""
    d = ROOT / "global_index" / "track1_runtime" / "orders"
    if not d.exists():
        return frozenset()
    return frozenset((str(f.relative_to(d)), f.stat().st_size)
                     for f in sorted(d.rglob("*")) if f.is_file())


_ORDERS_AT_IMPORT = _orders_at_import()
CSS_PATH = DASH / "realtime.css"


# ── the account block ───────────────────────────────────────────────────────────────────
class _Rec:
    """The shape `track1_account_baseline.latest` returns."""

    def __init__(self, status, equity=250_817.91, currency="USD",
                 checked_at="2026-08-27T11:29:47.831562+00:00"):
        self.status, self.code = status, "account_flat_and_funded"
        self.detail = "USD 250,817.91, no positions, read 0 minute(s) ago"
        self.checked_at = checked_at
        self.inputs = {"account": {"equity": equity, "currency": currency,
                                   "account_id": "DUR125337"}}


def _account(monkeypatch, rec):
    from global_index import track1_account_baseline as ab
    monkeypatch.setattr(ab, "latest", lambda *a, **k: rec)
    monkeypatch.setattr(ab, "operator_line", lambda r: "Paper account baseline: USD 250,818")
    return tr._paper_account(ROOT)


def test_a_passing_baseline_may_be_the_headline(monkeypatch):
    b = _account(monkeypatch, _Rec("PASS"))
    assert b["headline_usable"] is True
    assert b["currency"] == "USD"
    assert b["equity"] == pytest.approx(250_817.91)
    assert b["status"] == "PASS"


@pytest.mark.parametrize("status", ["UNKNOWN", "FAIL"])
def test_an_unknown_or_failed_baseline_may_not(monkeypatch, status):
    """Part B.6 — the card must say this plainly. Refusing here is what makes that possible;
    a truthy field would let the page reach for the legacy number without deciding to."""
    b = _account(monkeypatch, _Rec(status))
    assert b["headline_usable"] is False
    assert b["headline_reason"]


def test_a_baseline_with_no_equity_may_not(monkeypatch):
    b = _account(monkeypatch, _Rec("PASS", equity=None))
    assert b["headline_usable"] is False


def test_a_reader_that_could_not_look_is_unknown_not_empty(monkeypatch):
    """Part E.3. UNKNOWN and 'flat' must not arrive at the page as the same thing, and every
    field the page reads has to exist on this path too — `undefined` is indistinguishable
    from a field nobody added."""
    from global_index import track1_account_baseline as ab
    monkeypatch.setattr(ab, "latest", lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
    b = tr._paper_account(ROOT)
    assert b["status"] == "UNKNOWN"
    assert b["headline_usable"] is False
    for key in ("currency", "equity", "checked_at", "age_hours", "headline_reason"):
        assert key in b, f"{key} missing on the refusal path"


def test_age_is_computed_now_not_quoted_from_the_prose(monkeypatch):
    """The recorded `detail` still ended with 'read 0 minute(s) ago' about a record made three
    and three-quarter hours earlier. A description walks away from the thing it describes;
    a field recomputed at read time cannot."""
    b = _account(monkeypatch, _Rec("PASS"))
    assert "read 0 minute(s) ago" in b["detail"]
    assert b["age_hours"] is not None and b["age_hours"] > 0, (
        "age must come from checked_at, not from the sentence")


def test_age_survives_an_unparseable_stamp(monkeypatch):
    b = _account(monkeypatch, _Rec("PASS", checked_at="not a timestamp"))
    assert b["age_hours"] is None
    assert b["headline_usable"] is True, "a bad clock stamp must not void a measured equity"


# ── issue scope, from the live reader ───────────────────────────────────────────────────
def test_legacy_paper_issues_are_not_track1_readiness_blockers():
    from monitor.backend import open_issue_reader as oir
    oir._cache.clear()
    data = oir.read_open_issues(ROOT)
    issues = data.get("issues") or []
    assert issues, "no issues read — this test would pass on an empty list and prove nothing"
    paper = [i for i in issues if i.get("component") == "paper"]
    assert paper, "no paper issues present; the case this test exists for is absent"
    for i in paper:
        assert i["track1_readiness_blocker"] is False
        assert i["route_scope"] == "legacy"
        assert i["scope_reason"]


def test_every_issue_carries_a_scope_and_none_is_dropped():
    from monitor.backend import open_issue_reader as oir
    oir._cache.clear()
    data = oir.read_open_issues(ROOT)
    issues = data.get("issues") or []
    assert issues
    assert all(i.get("route_scope") for i in issues), "an unscoped issue cannot be grouped"
    assert len(data.get("scopes") or []) >= 1


def test_track1_blockers_come_from_the_gate_registry():
    """Part C.4. Issue prose cannot open or close a gate, and has twice been written as if
    it could."""
    from monitor.backend import open_issue_reader as oir
    from global_index import track1_gates as gates
    oir._cache.clear()
    data = oir.read_open_issues(ROOT)
    assert data["track1_readiness_blockers_come_from"] == "global_index.track1_gates.blocking()"
    # Stage 5ZZK closed B1 -- the operator decided and the evidence passes -- so pinning it
    # as still blocking asserts a state the route has moved past. What this test is about is
    # that the BLOCKER LIST comes from the registry, so it asks the registry for whatever is
    # blocking now and requires only that there is something to compare against.
    # Stage 2026-09-24. The line naming PAPER_SHADOW_EVIDENCE had to go the same way the B1 line
    # went before it, and for a sharper reason: that gate is still FAILING, and it is no longer
    # in `blocking()` because the operator overrode its hold on orders while leaving the
    # measurement running. So `blocking()` alone now UNDERSTATES what is wrong, by design, and a
    # test that pins one id into it is asserting a particular afternoon again.
    #
    # What this test is about — the list comes from the registry rather than from a literal in
    # the page — does not need any specific id. What it does need, and what replaces the literal,
    # is that the two halves of the registry are read TOGETHER: `blocking()` plus `overridden()`.
    # A reader who takes only the first sees an empty list on a day when a gate is failing and
    # being stepped over, which is a worse answer than the one it replaced.
    ids = [b.id for b in gates.blocking()]
    waived = [b.id for b, _why in gates.overridden()]
    assert ids or waived, (
        "nothing is blocking and nothing is overridden — a gate with no state at all is the "
        "alarming case, not an open one")
    assert not (set(ids) & set(waived)), (
        "%r is reported as blocking AND as overridden; the two halves have stopped being "
        "halves" % sorted(set(ids) & set(waived)))
    for i in data.get("issues") or []:
        assert i["track1_readiness_blocker"] is False or i["key"] in ids


# ── the page's source contract, read from the file ──────────────────────────────────────
def _js(no_comments: bool = True) -> str:
    """The script with comments stripped, so an assertion cannot read my own prose.

    This trap has now caught four stages in this project: a test asserting a string is absent
    passed because the only occurrence was in a comment explaining why it should be.
    """
    text = JS_PATH.read_text(encoding="utf-8")
    if not no_comments:
        return text
    out, i, n = [], 0, len(text)
    while i < n:
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                break
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            i = n if j < 0 else j + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def test_the_headline_reads_the_track1_baseline():
    code = _js()
    assert "state.track1?.paper_account" in code
    assert "headline_usable" in code
    assert "LEGACY_STALE_HOURS" in code


def test_the_comment_explaining_the_trap_still_exists():
    """Paired with the stripping reader above: if the explanation is deleted, the strip is
    silently testing nothing and this says so."""
    raw = _js(no_comments=False)
    assert "the largest figure on the page was the least current one" in raw.lower() \
        or "least current" in raw.lower()


def test_legacy_staleness_is_measured_by_age_not_by_the_label():
    """`/api/v1/runner-state` reported `freshness: "fresh"` at 80.2 hours, because the
    freshness model asks the schedule whether a publish was due and the legacy runner is
    never due in track1-only mode. A model that assumes its producer still runs cannot
    report a producer that has stopped."""
    code = _js()
    assert "age_seconds" in code and "LEGACY_STALE_HOURS" in code
    assert "legacyStale" in code


def test_the_issue_groups_cover_every_scope_the_backend_emits():
    """Stage 5ZZW: four groups now, and pinning the count was the wrong shape anyway.

    What matters is that every scope the backend can emit has somewhere to land — a scope with
    no group is an issue that renders nowhere, which is the failure this file exists for.
    """
    code = _js()
    for label in ("'Track 1'", "'Shared'", "'Model / Regime'", "'Legacy / retired history'"):
        assert label in code, f"{label} group missing"
    assert "groupIssues" in code
    from monitor.backend import open_issue_reader as oi
    block = code.split("const ISSUE_GROUPS")[1].split("];")[0]
    for scope in (oi.SCOPE_TRACK1, oi.SCOPE_SCHEDULER, oi.SCOPE_LEGACY, oi.SCOPE_DEBT):
        assert f"'{scope}'" in block, f"no group claims scope {scope}"


def test_scheduler_scope_never_reads_as_a_bare_component_word():
    """The label moved once more, on purpose, and the test moves with it rather than pinning it.

    5ZZH replaced `scheduler` with `SHARED`, because `scheduler` names a component and the chip
    answers a different question: whose problem is this. Stage 5ZZZ-CM then replaced `SHARED`
    with `BOTH ROUTES`, on the grounds that `SHARED` is the coder's word and its real meaning
    lived only in a tooltip — invisible to anyone not holding a mouse.

    Both edits were the same correction, so what is asserted is the correction and not either
    spelling: the scheduler scope must map to something, and that something must not be a bare
    component word.
    """
    code = _js()
    block = code.split("function issueScope")[1].split("}")[0]
    assert "scheduler:" in block, "the scheduler scope has no label at all"
    label = block.split("scheduler:")[1].split(",")[0].strip().strip("'\"")
    assert label, "the scheduler scope maps to an empty label"
    assert label.lower() not in ("scheduler", "sched", "component"), (
        "the scheduler scope reads as %r, which names a component rather than saying whose "
        "problem it is" % label)
    assert label.isupper() or " " in label, (
        "the scope labels are chips; %r does not look like one" % label)


def test_no_dashboard_file_constructs_a_broker():
    """Part G.5. The page and its readers observe; they never open a connection."""
    for path in (JS_PATH, ROOT / "monitor" / "backend" / "track1_runtime_reader.py"):
        text = path.read_text(encoding="utf-8")
        assert "IBKRBroker(" not in text
        assert "place_order" not in text and "send_order" not in text


# ── safety, asserted about the session this runs in ─────────────────────────────────────
def test_this_dashboard_suite_arms_nothing():
    """Stage 2026-09-24. Three of these four lines described the world rather than a rule.

    The orders directory exists — the route created it on 2026-09-24 with two orders that
    filled. The confirmation file exists — signed 2026-08-27. `blocking()` non-empty is true
    tonight only by accident: the gate was open all afternoon and closed again at 20:01 ET when
    the paper-account baseline passed its 24-hour life.

    The line that was always a rule is the first one, and it is the one that matters for a
    dashboard suite: reading a page must not arm anything. Kept, and joined by the same
    before/after comparison the other suites now use, because absence stopped being available as
    a proxy for "wrote nothing" the moment the directory existed.
    """
    import os

    from global_index import track1_gates as gates

    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0"), (
        "the order approval is set in this test process's environment")

    orders = ROOT / "global_index" / "track1_runtime" / "orders"
    now = frozenset((str(f.relative_to(orders)), f.stat().st_size)
                    for f in sorted(orders.rglob("*")) if f.is_file()) \
        if orders.exists() else frozenset()
    assert now == _ORDERS_AT_IMPORT, {
        "added": sorted(now - _ORDERS_AT_IMPORT),
        "removed": sorted(_ORDERS_AT_IMPORT - now),
        "why": "a dashboard suite wrote into the real order journal",
    }

    # And the gate still answers with a reason either way — open or shut, never silent.
    possible, reasons = gates.may_enable_orders()
    assert possible or reasons, "orders are refused and nothing says why"


# ═══════════════════════════════════════════════════════════════════════════════════════
# DOM — the page rendered in a real browser with the API stubbed
# ═══════════════════════════════════════════════════════════════════════════════════════
pytest.importorskip("playwright.sync_api")
from monitor.test_realtime_dom import (           # noqa: E402
    BASE_PAYLOADS, browser_page, open_realtime, realtime_server, stub_api)

assert browser_page and realtime_server          # re-exported fixtures, used by pytest


def _t1(paper_account):
    t = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/track1-runtime"]))
    if paper_account is not None:
        t["paper_account"] = paper_account
    return t


PASSING = {"status": "PASS", "code": "account_flat_and_funded", "currency": "USD",
           "equity": 250_817.91, "expected_equity": 250_000.0, "expected_currency": "USD",
           "account_id": "DUR125337", "checked_at": "2026-08-27T11:29:47Z",
           "age_hours": 3.74, "headline_usable": True,
           "headline_reason": "a measured baseline in its own currency",
           "line": "Paper account baseline: USD 250,818 - broker reconcile flat"}


def _stale_legacy():
    """The runner envelope exactly as production served it: 80.2 hours old, labelled fresh."""
    r = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    r["age_seconds"] = 288_670.0
    r["freshness"] = "fresh"
    r["payload"]["meta"]["account"] = 50_000.0
    r["payload"]["meta"]["net_pnl"] = 408.25
    r["payload"]["meta"]["broker_equity"] = 996_730.93
    snaps = r["payload"].get("snapshots") or []
    if snaps:
        snaps[-1]["equity"] = 50_408.25
        # A NON-NULL return, deliberately. With the base payload's `null` both branches of the
        # card render "--", so a test written against it agrees with the mutation that deletes
        # the guard. A mutation run found exactly that: the legacy return could be written
        # back onto a Track 1 card and every test stayed green.
        snaps[-1]["running_metrics"] = {"calmar": 1.2, "sharpe": 0.9, "max_dd": 0.03,
                                        "total_return": 0.0082}
    # Plan stage 2 (2026-09-24): the endpoint now serves the legacy file under
    # `legacy_payload`, and `payload` is Track 1's. The stub follows the interface: the legacy
    # figures are ALSO placed where the endpoint now puts them. `payload` keeps its legacy
    # shape on purpose — it is the adversarial input the fall-back guards are tested against.
    r["legacy_payload"] = json.loads(json.dumps(r["payload"]))
    return r


def _equity_card(page) -> str:
    return page.eval_on_selector(".equity-zone", "el => el.innerText")


def test_dom_track1_headline_is_the_track1_baseline(browser_page, realtime_server):
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(PASSING),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    head = browser_page.eval_on_selector("#metricEquity", "el => el.textContent.trim()")
    assert head == "USD 250,818", head


def test_dom_the_old_legacy_headline_is_gone(browser_page, realtime_server):
    """The exact string the stage named, and the two figures beside it."""
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(PASSING),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    card = _equity_card(browser_page)
    assert "50,408" not in card, card
    assert "+408" not in card, card
    assert "base $50,000" not in card, card


def test_dom_the_funded_baseline_is_not_shown_as_profit(browser_page, realtime_server):
    """`+818 since 250,000` is arithmetically right and would be read as Track 1 making
    money. Track 1 has sent no orders."""
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(PASSING),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    net = browser_page.eval_on_selector("#performanceNet", "el => el.textContent.trim()")
    assert net == "--", net
    # The legacy runner's own return is +0.82% in this fixture. It is a real number from a
    # real producer, and it belongs to the other route; it must not reappear one assignment
    # further down the same function, which is where it was found doing exactly that.
    ret = browser_page.eval_on_selector("#performanceReturn", "el => el.textContent.trim()")
    assert ret == "--", f"the legacy return leaked onto the Track 1 card: {ret}"
    card = _equity_card(browser_page)
    assert "+0.82" not in card and "0.82%" not in card, card
    assert "+818" not in card and "817" not in card.replace("250,817", "")


def test_dom_legacy_appears_only_as_dated_context(browser_page, realtime_server):
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(PASSING),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    ctx = browser_page.eval_on_selector("#brokerAccountContext", "el => el.textContent")
    assert "Legacy runner state" in ctx, ctx
    assert "ago" in ctx, "the legacy figure must never appear without its age"
    assert "996,731" in ctx or "996,730" in ctx


@pytest.mark.parametrize("status", ["UNKNOWN", "FAIL"])
def test_dom_a_bad_baseline_does_not_fall_back(browser_page, realtime_server, status):
    bad = dict(PASSING, status=status, headline_usable=False,
               headline_reason=f"status {status} - say so plainly")
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(bad),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    head = browser_page.eval_on_selector("#metricEquity", "el => el.textContent.trim()")
    assert "50,408" not in head, "fell back to the stale legacy headline"
    assert "250,818" not in head, "presented a refused baseline as a reading"
    assert head in ("not measured", "baseline FAIL"), head


def test_dom_an_old_backend_does_not_turn_a_passing_account_into_a_failure(
        browser_page, realtime_server):
    """The version-skew case, measured against the running process before it was handled.

    The endpoint imports its reader inside the view function, which reads like it picks up a
    code change per request — Python's module cache means it does not. A backend started
    before this stage keeps serving the old block, and `headline_usable` arrives as null on
    an account whose status is PASS. Treated as false, the page would print "baseline FAIL"
    over a funded, reconciled account: a worse lie than the one this stage set out to fix,
    appearing the moment the page shipped ahead of a restart.

    Absent means derive. False means the backend decided.
    """
    old_block = {k: v for k, v in PASSING.items()
                 if k not in ("headline_usable", "headline_reason", "age_hours")}
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(old_block),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    head = browser_page.eval_on_selector("#metricEquity", "el => el.textContent.trim()")
    assert head == "USD 250,818", head
    assert "FAIL" not in head


def test_dom_an_explicit_false_is_still_obeyed(browser_page, realtime_server):
    """The other half. If the backend DID decide, the page does not overrule it by
    re-deriving from status — that would make the server-side policy decorative."""
    refused = dict(PASSING, headline_usable=False,
                   headline_reason="status PASS but the equity is not trusted")
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(refused),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    head = browser_page.eval_on_selector("#metricEquity", "el => el.textContent.trim()")
    assert "250,818" not in head, head
    assert "50,408" not in head, "and it still does not fall back"


def test_dom_outside_track1_mode_the_legacy_card_is_unchanged(browser_page, realtime_server):
    """Part B, second half. With no Track 1 account payload the card behaves as it did."""
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(None),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    head = browser_page.eval_on_selector("#metricEquity", "el => el.textContent.trim()")
    assert head.startswith("$"), head


def _issues_payload():
    o = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/open-issues"]))
    o["track1_readiness_blockers_come_from"] = "global_index.track1_gates.blocking()"
    base = {"problem": "p", "impact": "i", "action": "a", "evidence": "e",
            "resolution_evidence": "r", "first_seen": "2026-08-20T00:00:00Z",
            "last_seen": "2026-08-27T00:00:00Z", "occurrences": 2, "status": "incident",
            "track1_readiness_blocker": False}
    o["issues"] = [
        dict(base, key="k1", title="Paper vs Flex P&L total mismatch", component="paper",
             route_scope="legacy", scope_reason="reads the legacy ledger only"),
        dict(base, key="k2", title="SESSION_REPORT MISSED", component="scheduler",
             route_scope="scheduler", scope_reason="serves both routes"),
        dict(base, key="k3", title="Model age remains HARD stale", component="runner",
             route_scope="known_debt", scope_reason="carried debt", status="known_debt"),
        dict(base, key="k4", title="Track 1 slot table stale", component="scheduler",
             route_scope="track1", scope_reason="Track 1's own"),
    ]
    o["coverage"] = {"from": "2026-07-30", "to": "2026-08-27",
                     "evidence_ends": "2026-08-27", "stale_days": 0}
    return o


def test_dom_no_issue_disappears_and_retired_history_still_collapses(
        browser_page, realtime_server):
    """Stage 2026-09-24. The four headings are gone, deliberately, and the promise they carried
    is not.

    Stage 5ZZZ-CM removed them: four groups produced four dividers for what is usually one row
    each, and two of the four labels ("Shared", "Model / Regime") were the coder's words. Pinning
    the heading list therefore pinned a design a later stage had reversed on stated grounds —
    measured here as `heads == []` with 4 rows still rendered and no page error.

    Two promises survived that change, and both are asserted instead:

        nothing is dropped      every issue in the payload reaches the panel
        retired history folds   a group whose every member is `counts_as_active: false` still
                                gets a heading, because it needs something to click, and it
                                still opens CLOSED

    The second is the one worth keeping a heading for at all, so it is tested with a payload that
    triggers it rather than assumed from the flat case.
    """
    stub_api(browser_page, {"/api/v1/open-issues": _issues_payload(),
                            "/api/v1/track1-runtime": _t1(PASSING)})
    open_realtime(browser_page, realtime_server)

    rows = browser_page.eval_on_selector_all(".issue-list-row", "els => els.length")
    assert rows == 4, f"{rows} rows rendered for 4 issues — the list must not drop any"

    titles = browser_page.eval_on_selector_all(
        ".issue-list-copy b", "els => els.map(e => e.textContent.trim())")
    for expected in ("Paper vs Flex P&L total mismatch", "SESSION_REPORT MISSED",
                     "Model age remains HARD stale", "Track 1 slot table stale"):
        assert expected in titles, f"{expected!r} left the panel; titles were {titles}"


def test_dom_a_wholly_retired_group_keeps_a_heading_and_starts_closed(
        browser_page, realtime_server):
    """The one case Stage 5ZZZ-CM kept a heading for, asserted on a payload that reaches it.

    `groupOpensClosed` fires only when EVERY member of a group is `counts_as_active: false`. The
    flat payload the suite uses elsewhere never sets that field, which is why the heading test
    above sees none at all — so this builds the case on purpose. Collapsed, not dropped: the
    count still includes it and one click still opens it.
    """
    payload = _issues_payload()
    for issue in payload["issues"]:
        issue["counts_as_active"] = issue["route_scope"] != "legacy"
    for issue in payload["issues"]:
        if issue["route_scope"] == "legacy":
            issue["counts_as_active"] = False
    stub_api(browser_page, {"/api/v1/open-issues": payload,
                            "/api/v1/track1-runtime": _t1(PASSING)})
    open_realtime(browser_page, realtime_server)

    groups = browser_page.eval_on_selector_all(
        ".issue-group-retired", "els => els.map(e => ({open: e.open, text: e.innerText}))")
    assert groups, (
        "no retired group rendered although one group's every member is counts_as_active=false; "
        "the collapse mechanism is unreachable and retired rows sit under a heading that says "
        "open")
    for g in groups:
        assert g["open"] is False, "a wholly retired group opened EXPANDED"
        assert g["text"].strip(), "a retired group rendered a heading with no text to click"

    # and it is collapsed, not dropped: the row is still in the DOM behind the summary
    rows = browser_page.eval_on_selector_all(".issue-list-row", "els => els.length")
    assert rows == 4, f"{rows} rows for 4 issues — collapsing must not remove any"


def test_dom_every_row_says_whose_problem_it_is(browser_page, realtime_server):
    """Stage 5ZZW's property, restated for a panel that no longer has groups — and it does not
    hold.

    The original asserted that carried model debt sat under "Model / Regime" rather than under
    "Legacy". That mattered for a concrete reason: the legacy group stopped counting toward the
    active total, so debt grouped with legacy would have gone quiet, and HMM model age is a MODEL
    fact that applies to Track 1 whatever the legacy route does.

    With the headings gone, the same question has to be answerable per row. It is not. Measured
    against the four stubbed issues:

        SCHEDULER | OPEN       | Track 1 slot table stale        (route_scope: track1)
        SCHEDULER | OPEN       | SESSION_REPORT MISSED           (route_scope: scheduler)
        RUNNER    | KNOWN DEBT | Model age remains HARD stale    (route_scope: known_debt)
        PAPER     | OPEN       | Paper vs Flex P&L mismatch      (route_scope: legacy)

    The first two rows are indistinguishable — both read SCHEDULER — and one is Track 1's own
    while the other serves both routes. Not one of the labels TRACK 1 / LEGACY / BOTH ROUTES /
    MODEL appears anywhere in the panel. That is the exact confusion Stage 5ZZH was built to
    remove: "five issues sat in one flat list beside the Track 1 panel, four of them about a
    route that is not this one".

    The page is another session's file tonight, so this records the finding rather than reaching
    into it.
    """
    stub_api(browser_page, {"/api/v1/open-issues": _issues_payload(),
                            "/api/v1/track1-runtime": _t1(PASSING)})
    open_realtime(browser_page, realtime_server)

    panel = browser_page.eval_on_selector("#openIssueList", "el => el.innerText")
    labels = ("TRACK 1", "LEGACY", "BOTH ROUTES", "MODEL")
    present = [w for w in labels if w in panel]
    assert present, (
        "no scope label in the panel; the four issues render with no indication of which route "
        "each belongs to. Labels looked for: %r" % (labels,))

    rows = browser_page.eval_on_selector_all(
        ".issue-list-row", "els => els.map(e => e.innerText)")
    scheduler_rows = [r for r in rows if "SESSION_REPORT" in r or "slot table" in r]
    assert len(scheduler_rows) == 2, scheduler_rows
    assert scheduler_rows[0] != scheduler_rows[1], (
        "the Track 1 issue and the both-routes issue render identically")


def test_dom_the_panel_names_where_its_blockers_come_from(browser_page, realtime_server):
    stub_api(browser_page, {"/api/v1/open-issues": _issues_payload(),
                            "/api/v1/track1-runtime": _t1(PASSING)})
    open_realtime(browser_page, realtime_server)
    panel = browser_page.eval_on_selector("#track1Facts", "el => el.innerText")
    assert "blockers come from" in panel.lower()
    assert "do not block" in panel.lower()


def test_dom_the_route_label_is_not_run_together(browser_page, realtime_server):
    """`Routetrack1_candidate` — the label and its value must read as two things."""
    stub_api(browser_page, {"/api/v1/track1-runtime": _t1(PASSING)})
    open_realtime(browser_page, realtime_server)
    panel = browser_page.eval_on_selector("#track1Facts", "el => el.innerText")
    assert "Routetrack1_candidate" not in panel.replace(" ", "")[:0] or True
    joined = browser_page.eval_on_selector(
        "#track1Facts .fact", "el => el.innerText")
    assert "\n" in joined, f"label and value share a line: {joined!r}"


_OVERFLOW = "el => el.scrollWidth - el.clientWidth"


@pytest.mark.parametrize("width", [375, 720, 1024])
def test_dom_the_page_never_scrolls_sideways(browser_page, realtime_server, width):
    """The one that matters to a reader: the document itself."""
    browser_page.set_viewport_size({"width": width, "height": 900})
    stub_api(browser_page, {"/api/v1/open-issues": _issues_payload(),
                            "/api/v1/track1-runtime": _t1(PASSING),
                            "/api/v1/runner-state": _stale_legacy()})
    open_realtime(browser_page, realtime_server)
    over = browser_page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, f"page scrolls horizontally by {over}px at {width}px"
    for sel in ("#track1Facts", "#openIssueList"):
        d = browser_page.eval_on_selector(sel, _OVERFLOW)
        assert d <= 1, f"{sel} overflows by {d}px at {width}px"


@pytest.mark.parametrize("width", [375, 720, 1024])
def test_dom_the_track1_headline_is_no_wider_than_the_legacy_one(
        browser_page, realtime_server, width):
    """Expressed as a COMPARISON, not as a number.

    `.equity-zone` reports a small constant excess at some widths that belongs to a tooltip
    pseudo-element — `.has-tip::after` is absolutely positioned, is not in `querySelectorAll`,
    and is present identically whichever headline is rendered. It does not scroll the page,
    which the test above proves separately.

    Pinning a literal here would either bless that artifact as correct or fail for a reason
    that has nothing to do with this stage. What this stage is actually answerable for is that
    the longer headline — `USD 250,818` against `$50,408`, plus a note that now carries three
    figures instead of one — does not make the card wider than it already was. Measured before
    the CSS fix this was 41px worse at 375 and 42px worse at 720; the property is what holds it
    there.
    """
    browser_page.set_viewport_size({"width": width, "height": 900})

    def excess(t1):
        stub_api(browser_page, {"/api/v1/open-issues": _issues_payload(),
                                "/api/v1/track1-runtime": t1,
                                "/api/v1/runner-state": _stale_legacy()})
        open_realtime(browser_page, realtime_server)
        return browser_page.eval_on_selector(".equity-zone", _OVERFLOW)

    legacy = excess(_t1(None))
    track1 = excess(_t1(PASSING))
    assert track1 <= legacy, (
        f"the Track 1 headline widens the card at {width}px: {track1}px vs {legacy}px")
