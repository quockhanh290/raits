"""DOM smoke tests for the paper evidence page: real chromium, real payload.

These four checks were run by hand a dozen times while auditing this page and then
thrown away each time, so they were verification, never a fence. One of them found a
real defect: M4, where three tables were clipped on mobile with no way to scroll them,
because `overflow-x: hidden` was set outside a media query and beat `.trade-table`.

The payload is the real one from read_paper_evidence, not a fixture. The checks are
structural -- tabs, navigation targets, overflow -- and a synthetic payload would need
all seventeen coverage keys to exercise them, at which point it is the real payload with
extra chances to drift.

Note on check 3: "the page does not scroll horizontally" does NOT prove nothing
overflows. Content past the edge can be CLIPPED instead of scrolled, and then
scrollWidth == clientWidth while the content is simply unreachable -- that is exactly
how M4 hid. Check 4 is the one that catches it, per container.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from monitor.backend.app import app  # noqa: E402
from monitor.backend.paper_evidence_reader import read_paper_evidence  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

TABS = ["overview", "gates", "coverage", "gaps"]


@pytest.fixture(scope="module")
def paper_payload():
    return read_paper_evidence(ROOT)


@pytest.fixture(scope="module")
def paper_server():
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            yield pg
        finally:
            browser.close()


def open_paper(page, base_url: str, payload: dict, width: int = 1440) -> None:
    """Serve the captured payload so a slow cold scan cannot make the test flaky."""
    page.set_viewport_size({"width": width, "height": 1000})
    # Drop any handler from an earlier open_paper on this page. The checks below open
    # the same page twice with two different payloads -- a state and its control -- and
    # a stale handler would quietly serve the first payload to the second render, which
    # is a green result produced by never testing the second state.
    page.unroute("**/api/v1/paper-evidence*")
    page.route("**/api/v1/paper-evidence*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(payload)))
    page.goto(f"{base_url}/paper", wait_until="domcontentloaded")
    page.wait_for_selector("#readinessBlockers .blocker-card", timeout=30_000)


def test_every_tab_shows_its_own_panel(paper_server, page, paper_payload):
    open_paper(page, paper_server, paper_payload)
    for tab in TABS:
        page.click(f"label[for='paper-tab-{tab}']")
        page.wait_for_timeout(150)
        checked = page.eval_on_selector(
            f"#paper-tab-{tab}", "el => el.checked")
        assert checked, f"clicking the {tab} tab label did not select it"
        visible = page.evaluate(
            "() => [...document.querySelectorAll('.paper-tab-panel')]"
            ".filter(e => e.offsetParent !== null).length")
        assert visible >= 1, f"no panel is visible on the {tab} tab"


def test_every_navigation_button_opens_the_panel_it_names(paper_server, page, paper_payload):
    """A button that opens the wrong panel is worse than no button: H5 shipped one that
    sent the reader to runner_freshness for TWS restart evidence."""
    open_paper(page, paper_server, paper_payload)
    coverage = {c["key"]: c["title"] for c in paper_payload["payload"]["coverage"]}

    # Buttons live on several tabs, and clicking one navigates to Coverage -- so the rest
    # go invisible. Walk tab by tab and return to the tab after each click.
    seen: set[str] = set()
    for tab in TABS:
        page.click(f"label[for='paper-tab-{tab}']")
        page.wait_for_timeout(200)
        keys = page.evaluate(
            "() => [...document.querySelectorAll('[data-coverage-ref],[data-gap-related]')]"
            ".filter(e => e.offsetParent !== null)"
            ".map(e => e.dataset.coverageRef || e.dataset.gapRelated)")
        for key in sorted(set(keys)):
            assert key in coverage, f"a button points at {key!r}, which is not a coverage panel"
            if key in seen:
                continue
            seen.add(key)
            page.click(f"label[for='paper-tab-{tab}']")
            page.wait_for_timeout(150)
            page.click(f"[data-coverage-ref='{key}'], [data-gap-related='{key}']")
            page.wait_for_timeout(350)
            heading = page.eval_on_selector(".coverage-detail h3", "el => el.textContent")
            assert heading == coverage[key], (
                f"button for {key!r} opened {heading!r}, expected {coverage[key]!r}")
    assert seen, "the page exposes no drill-down buttons at all"


@pytest.mark.parametrize("width", [1440, 1024, 390])
def test_the_page_itself_never_scrolls_sideways(paper_server, page, paper_payload, width):
    open_paper(page, paper_server, paper_payload, width=width)
    for tab in TABS:
        page.click(f"label[for='paper-tab-{tab}']")
        page.wait_for_timeout(200)
        scroll, client = page.evaluate(
            "() => [document.documentElement.scrollWidth,"
            " document.documentElement.clientWidth]")
        assert scroll <= client, (
            f"{tab} tab at {width}px scrolls sideways: {scroll} > {client}")


@pytest.mark.parametrize("width", [1440, 390])
def test_a_clipped_table_can_always_be_scrolled(paper_server, page, paper_payload, width):
    """The check that found M4.

    A table wider than its container must scroll inside it. If it does not, the columns
    past the edge are simply unreachable -- and the page-level check above stays green
    the whole time, because clipped content does not create page scroll.
    """
    open_paper(page, paper_server, paper_payload, width=width)
    offenders = []
    for tab in TABS:
        page.click(f"label[for='paper-tab-{tab}']")
        page.wait_for_timeout(200)
        # Open every coverage detail so the tables inside them are measured too.
        if tab == "coverage":
            for key in [c["key"] for c in paper_payload["payload"]["coverage"]]:
                button = page.query_selector(f"[data-coverage-key='{key}']")
                if button:
                    button.click()
                    page.wait_for_timeout(200)
                    offenders.extend(_clipped_tables(page, f"{tab}/{key}"))
        else:
            offenders.extend(_clipped_tables(page, tab))
    assert not offenders, f"clipped and unscrollable at {width}px: {offenders[:6]}"


def _clipped_tables(page, where: str) -> list[str]:
    rows = page.evaluate(
        "() => [...document.querySelectorAll('.trade-table')]"
        ".filter(e => e.offsetParent !== null && e.scrollWidth - e.clientWidth > 1)"
        ".filter(e => !['auto','scroll'].includes(getComputedStyle(e).overflowX))"
        ".map(e => e.className)")
    return [f"{where}:{name}" for name in rows]


# ---------------------------------------------------------------------------
# Verdict logic. The four checks above are structural -- tabs, targets, overflow --
# and cannot see a panel that renders perfectly while saying the wrong thing.
#
# Each check below drives a state AND its control through the real page, because a
# panel that always shows the safe answer passes a one-sided check without deciding
# anything. Where the two must differ, the test asserts they differ.


def _mutate(payload: dict, gate_status: dict | None = None,
            coverage_status: dict | None = None,
            coverage_metrics: dict | None = None,
            pnl: dict | None = None) -> dict:
    """A deep copy of the real payload with named fields moved."""
    out = json.loads(json.dumps(payload))
    body = out["payload"]
    for key, status in (gate_status or {}).items():
        for gate in body["gates"]:
            if gate["key"] == key:
                gate["status"] = status
                break
        else:
            raise AssertionError(f"no gate {key!r} in the payload to mutate")
    for key, status in (coverage_status or {}).items():
        for item in body["coverage"]:
            if item["key"] == key:
                item["status"] = status
                break
        else:
            raise AssertionError(f"no coverage item {key!r} in the payload to mutate")
    for key, metrics in (coverage_metrics or {}).items():
        for item in body["coverage"]:
            if item["key"] == key:
                item.setdefault("metrics", {}).update(metrics)
                break
        else:
            raise AssertionError(f"no coverage item {key!r} in the payload to mutate")
    if pnl:
        for item in body["coverage"]:
            if item["key"] == "paper_vs_backtest":
                item["metrics"]["trade_compare"]["statement_pnl_compare"].update(pnl)
                break
        else:
            raise AssertionError("no paper_vs_backtest coverage item to mutate")
    return out


def _chip(page, container_id: str, needle: str) -> tuple[str, str]:
    """The (text, tone) of the one reason chip mentioning `needle`."""
    found = page.evaluate(
        "([id, needle]) => [...document.querySelectorAll('#' + id + ' span')]"
        ".filter(e => e.textContent.includes(needle))"
        ".map(e => [e.textContent, e.className])",
        [container_id, needle])
    assert len(found) == 1, (
        f"expected exactly one chip in #{container_id} mentioning {needle!r}, "
        f"found {len(found)}: {found}. Without it this check asserts nothing.")
    return found[0][0], found[0][1]


def test_an_empty_book_is_not_reported_as_unprotected(paper_server, page, paper_payload):
    """No open positions means nothing to protect -- not a protection failure.

    Three panels answered this differently: the B3 chip painted 0/0 the same red as a
    live position with no stop, the metric beside it amber, and only the detail panel
    said the question had not arisen. `positionCount && ...` is why: with no positions
    that leading 0 is falsy and the expression falls into the failure arm.
    """
    empty = _mutate(paper_payload, coverage_metrics={
        "current_protection": {"positions": 0, "protected": 0, "unprotected": 0}})
    open_paper(page, paper_server, empty)
    text_empty, tone_empty = _chip(page, "b3ProgressReason", "protected")
    assert "0/0" in text_empty, f"the empty-book chip did not render 0/0: {text_empty!r}"
    assert "bad" not in tone_empty, (
        f"an empty book is painted as a protection failure: {text_empty!r} -> {tone_empty!r}")

    # Control: a real unprotected position must still be red, or the check above is
    # satisfied by a panel that simply never reports anything.
    unsafe = _mutate(paper_payload, coverage_metrics={
        "current_protection": {"positions": 2, "protected": 1, "unprotected": 1}})
    open_paper(page, paper_server, unsafe)
    text_unsafe, tone_unsafe = _chip(page, "b3ProgressReason", "protected")
    assert "1/2" in text_unsafe, f"the control chip did not render 1/2: {text_unsafe!r}"
    assert "bad" in tone_unsafe, (
        f"a position with no stop is not painted as a failure: {text_unsafe!r} -> {tone_unsafe!r}")
    assert tone_empty != tone_unsafe, "the two states render identically; the chip decides nothing"


def _c1_gate(payload: dict, **metrics):
    out = _mutate(payload)
    for gate in out["payload"]["gates"]:
        if gate["key"] == "c1_slippage":
            gate["metrics"].update(metrics)
            return out
    raise AssertionError("no c1_slippage gate to mutate")


def test_a_measured_slippage_breach_reaches_the_c1_verdict_card(paper_server, page, paper_payload):
    """The card summarising the panel must not be calmer than the panel.

    It chose its colour with `x === 'QUALITY_BREACH' ? 'watch' : 'watch'` -- both arms
    the same -- while the OPEN-mean chip and every per-instrument card below it went
    red on that same condition.
    """
    def verdict_tone():
        found = page.evaluate(
            "() => [...document.querySelectorAll('#c1MetricGroups article.c1-metric')]"
            ".filter(e => e.textContent.includes('Panel verdict'))"
            ".map(e => e.className)")
        assert len(found) == 1, f"expected one C1 verdict card, found {len(found)}"
        return found[0]

    open_paper(page, paper_server,
               _c1_gate(paper_payload, open_breaching_instruments=["MES"], stp_over_limit=False))
    tone_breach = verdict_tone()
    assert "bad" in tone_breach, f"a measured slippage breach renders calm: {tone_breach!r}"

    open_paper(page, paper_server,
               _c1_gate(paper_payload, open_breaching_instruments=[], stp_over_limit=False))
    tone_clean = verdict_tone()
    assert "bad" not in tone_clean, f"a clean panel renders as a breach: {tone_clean!r}"
    assert tone_breach != tone_clean, "both states render the same; the card decides nothing"


def test_an_unreadable_ledger_figure_is_not_reported_as_reconciled(paper_server, page, paper_payload):
    """`Number(null || 0) < 0.005` is true, so a missing figure read as a match.

    This block computes its own verdict -- unlike the four tables under the Trades and
    Timeline sub-tabs, whose verdicts come from monitor/paper_pnl_compare.json and
    override whatever the page derives. What this function decides is what is shown.
    """
    def ledger_verdict():
        page.click("label[for='paper-tab-coverage']")
        page.wait_for_timeout(250)
        found = page.evaluate(
            "() => [...document.querySelectorAll('.table-verdict')]"
            ".filter(e => (e.querySelector('b') || {}).textContent === 'Realtime ledger source')"
            ".map(e => (e.querySelector('.fill-result') || {}).textContent)")
        assert len(found) == 1, f"expected one realtime-ledger verdict, found {len(found)}"
        return found[0]

    open_paper(page, paper_server,
               _mutate(paper_payload, pnl={"ledger_aligned_minus_system_ledger_pnl": None}))
    missing = ledger_verdict()
    assert missing != "PASS", f"an unreadable ledger figure reports as reconciled: {missing!r}"

    open_paper(page, paper_server,
               _mutate(paper_payload, pnl={"ledger_aligned_minus_system_ledger_pnl": 0.0}))
    aligned = ledger_verdict()
    assert aligned == "PASS", f"a genuinely aligned ledger does not report PASS: {aligned!r}"

    open_paper(page, paper_server,
               _mutate(paper_payload, pnl={"ledger_aligned_minus_system_ledger_pnl": 250.0}))
    apart = ledger_verdict()
    assert apart == "BREACH", f"a $250 ledger gap does not report BREACH: {apart!r}"
    assert len({missing, aligned, apart}) == 3, (
        f"the three states do not produce three verdicts: {missing!r} {aligned!r} {apart!r}")


def test_a_composite_status_is_never_greener_than_its_primary(paper_server, page, paper_payload):
    """"Worst of the relevant statuses" -- which the last line inverted.

    It read "if anything here passed, the composite passed", so a primary of OBSERVED
    beside one PASS reference came out PASS. Nothing PASSes today, which is why this
    has never fired: it arms itself on the day the first gate goes green.
    """
    def stp_status():
        return page.eval_on_selector("#stpProgressStatus", "el => el.textContent")

    passing_refs = {"stp_placement": "PASS", "current_protection": "PASS"}
    open_paper(page, paper_server, _mutate(
        paper_payload, gate_status={"stp_verification": "OBSERVED"},
        coverage_status=passing_refs))
    got = stp_status()
    assert got != "PASS", f"an OBSERVED gate is reported PASS because a reference passed: {got!r}"
    assert got == "OBSERVED", f"expected the primary to survive, got {got!r}"

    # The mirror, which "PASS only when everything passed" would have left open: a
    # passing gate beside a reference that reached no verdict is still not a pass. The
    # panel's own note says a placement problem keeps it red even when verification
    # passes, so the references are allowed to make it worse -- in both directions.
    open_paper(page, paper_server, _mutate(
        paper_payload, gate_status={"stp_verification": "PASS"},
        coverage_status={"stp_placement": "PASS", "current_protection": "OBSERVED"}))
    got_mirror = stp_status()
    assert got_mirror == "OBSERVED", (
        f"a passing gate outranks an unresolved reference: {got_mirror!r}")

    # A measured breach must not fall through either: QUALITY_BREACH is not === 'BREACH'
    # and holds no GAP or NEEDS, so it used to reach the final line as an ordinary status.
    open_paper(page, paper_server, _mutate(
        paper_payload, gate_status={"stp_verification": "QUALITY_BREACH"},
        coverage_status=passing_refs))
    got_breach = stp_status()
    assert got_breach == "QUALITY_BREACH", (
        f"a measured breach is not carried into the composite: {got_breach!r}")

    # Control: all three passing must still produce PASS, or the rule above is just
    # "never say PASS", which would pass this file and tell the reader nothing.
    open_paper(page, paper_server, _mutate(
        paper_payload, gate_status={"stp_verification": "PASS"},
        coverage_status=passing_refs))
    got_clean = stp_status()
    assert got_clean == "PASS", f"three passing inputs do not produce PASS: {got_clean!r}"
