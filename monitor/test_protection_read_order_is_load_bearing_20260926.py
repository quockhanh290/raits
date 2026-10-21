# -*- coding: utf-8 -*-
"""The empty-book branch must be tested BEFORE the broker-unreadable branch.

One function now decides the protection read for all three panels of the paper tab, which is why
three panels can no longer disagree about an empty book. It handles four combinations, and the
DOM suite pins the answers. What the DOM suite cannot show is that the ORDER of two branches
inside that function is what produces one of those answers: put the unknown-source check first
and an empty book with an unreadable broker starts reading as unknown again, which is the exact
defect the batch was written to remove, pointed the other way.

So this file lifts the function out of the page, runs it, and then runs a copy with those two
branches swapped. If the swap does not change the answer, the ordering is not load-bearing and
the assertion protecting it is decoration -- and this test fails and says so.

No file is modified. The mutation exists only inside the browser context for the length of one
evaluation.
"""
import re
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                                    # pragma: no cover
    pytest.skip("playwright is not installed", allow_module_level=True)

PAPER_JS = Path("global_index/dash/paper/paper.js")
ZERO_HEAD = "if (Number(positionCount) === 0) {"
UNKNOWN_HEAD = "if (String(sourceStatus).toUpperCase() === 'UNKNOWN') {"


def _extract(source: str, opening: str) -> str:
    """Return `opening` plus its balanced body, so a block can be moved as one piece."""
    start = source.index(opening)
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError("unbalanced braces after %r" % opening)


@pytest.fixture(scope="module")
def blocks():
    src = PAPER_JS.read_text(encoding="utf-8")
    fn = _extract(src, "function protectionRead(")
    zero = _extract(fn, ZERO_HEAD)
    unknown = _extract(fn, UNKNOWN_HEAD)
    assert fn.index(zero) < fn.index(unknown), (
        "the empty-book branch is no longer first in the source. That IS the defect this file "
        "exists to catch, so it fails here rather than in the swap below")
    swapped = fn.replace(zero, "@@ZERO@@").replace(unknown, zero).replace("@@ZERO@@", unknown)
    assert swapped != fn
    return fn, swapped


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        try:
            yield pg
        finally:
            browser.close()


def _verdicts(page, fn_source: str) -> dict:
    """Run the function over the four combinations and return verdict plus tone for each."""
    script = """
    (fnSource) => {
      const make = new Function(fnSource + '; return protectionRead;');
      const f = make();
      const out = {};
      const cases = {
        no_positions_no_broker:  [0, 0, 'UNKNOWN'],
        no_positions_broker_ok:  [0, 0, 'PASS'],
        positions_no_broker:     [0, 2, 'UNKNOWN'],
        positions_broker_ok:     [2, 2, 'PASS'],
      };
      for (const [name, args] of Object.entries(cases)) {
        const r = f(args[0], args[1], args[2]);
        out[name] = { verdict: r.verdict, tone: r.tone, label: r.label };
      }
      return out;
    }
    """
    return page.evaluate(script, fn_source)


def test_the_four_combinations_read_as_they_should(page, blocks):
    fn, _ = blocks
    got = _verdicts(page, fn)
    for name, value in sorted(got.items()):
        print("AS SHIPPED  %-24s %s" % (name, value))

    assert got["no_positions_no_broker"]["tone"] == "neutral", got
    assert got["no_positions_no_broker"]["label"] == "0/0", got
    assert got["no_positions_broker_ok"]["tone"] == "neutral", got
    assert got["positions_no_broker"]["verdict"] == "UNKNOWN", got
    assert got["positions_broker_ok"]["verdict"] == "PASS", got


def test_swapping_the_two_branches_breaks_the_empty_book_answer(page, blocks):
    """Without this, the ordering assertion above passes for a function that does not need it."""
    fn, swapped = blocks
    shipped = _verdicts(page, fn)
    mutated = _verdicts(page, swapped)
    for name in sorted(mutated):
        print("BRANCHES SWAPPED  %-24s %s" % (name, mutated[name]))

    assert mutated["no_positions_no_broker"] != shipped["no_positions_no_broker"], (
        "swapping the empty-book and unknown-source branches changed nothing, so the order is "
        "not what produces the empty-book answer and the test beside this one proves less than "
        "it claims: %r" % (mutated["no_positions_no_broker"],))
    assert mutated["no_positions_no_broker"]["verdict"] == "UNKNOWN", mutated
    assert mutated["positions_no_broker"] == shipped["positions_no_broker"], (
        "the swap must only affect the empty-book case; a position with an unreadable broker "
        "reads unknown either way: %r" % (mutated["positions_no_broker"],))
