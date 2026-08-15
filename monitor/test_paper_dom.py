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
