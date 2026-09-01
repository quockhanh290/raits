"""Stage 5ZZZ-BU. Two rows that read as a contradiction, and both numbers were right.

Measured on the page 2026-09-01:

    Runner observed    08-24, 02:58 ET
    Runner freshness   fresh

-- the runner is healthy, and last spoke eight days ago. The freshness value is not about the
runner at all: `fresh` is set when the schedule has another slot later today, and in
track1-only mode the legacy runner is never due, so it says `fresh` for a snapshot of any age.
The module that computes it says so in its own first line -- "schedule-relative runner
freshness" -- and the row label had dropped the half that made it true. Measured age at the
time: 724,658 seconds, 201.3 hours.

Stage 5ZZH had already found this and answered it for ONE block, deliberately leaving the
legacy field alone because other panels read it and measuring age instead. The clocks block
was not that block, and carried its own reading.

WHAT THIS FILE DOES AND DOES NOT COVER. The behaviour was verified in a browser against the
live backend -- both rows re-read from the rendered DOM, and the metrics block confirmed still
dimmed, so extracting the shared rule did not break its first caller. What is pinned here is
STRUCTURAL: that one definition of the rule exists and that every block asking the question
calls it. That is the shape the defect had -- a second block answering for itself -- and it is
what a future edit is most likely to undo. A rendered-DOM assertion would be stronger and
belongs with the Playwright suite, which does not run alongside itself.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "global_index/dash/realtime/realtime.js"


@pytest.fixture(scope="module")
def js() -> str:
    src = JS.read_text(encoding="utf-8")
    assert len(src) > 10_000, "the renderer did not load; every assertion below would pass"
    return src


def test_the_staleness_rule_is_defined_exactly_once(js):
    """The defect's shape. Two blocks answering "is the legacy snapshot retired" separately is
    how one of them ended up saying `fresh` beside an eight-day-old timestamp."""
    assert len(re.findall(r"function legacyRunnerStale\s*\(", js)) == 1, js.count("legacyRunnerStale")
    inline = re.findall(r"\['missing',\s*'unknown',\s*'stale'\]", js)
    assert len(inline) == 1, ("the rule is written out in %d places; it must live in the "
                              "function only" % len(inline))


def test_every_block_that_asks_the_question_calls_that_one_rule(js):
    """Two callers today: the metrics/decision band and the clocks list. A third block copying
    the expression instead is the regression this guards."""
    # The declaration is `function legacyRunnerStale()`, which matches a bare call pattern
    # too. Counting it as a caller made this assertion survive a mutation that deleted a real
    # call site -- it read "two callers" when there was one and a definition.
    calls = re.findall(r"(?<!function )legacyRunnerStale\s*\(\s*\)", js)
    assert len(calls) >= 2, calls


def test_the_clocks_row_no_longer_claims_to_measure_the_runners_health(js):
    """The label is the whole defect: `fresh` is true, and "Runner freshness" is not what it
    is true ABOUT."""
    block = js[js.index("function renderClocks"):]
    block = block[:block.index("$('sourceClocks')")]
    assert "'Runner freshness'" not in block, block
    assert "'Schedule freshness'" in block, block
    assert "not the runner" in block, "the row does not say what the value is not about"


def test_the_observation_row_names_the_route_it_belongs_to(js):
    """An eight-day-old timestamp is correct on a machine running track1-only shadow, and
    unreadable without being told which route wrote it."""
    block = js[js.index("function renderClocks"):]
    block = block[:block.index("$('sourceClocks')")]
    assert "legacy route, retired" in block, block
    assert "legacyRunnerStale()" in block, "the note must be conditional on the measurement"


def test_the_legacy_freshness_field_itself_is_still_published(js):
    """Stage 5ZZH left it alone on purpose -- it is legacy contract and other panels read it.
    Renaming a display label must not turn into dropping the field."""
    block = js[js.index("function renderClocks"):]
    block = block[:block.index("$('sourceClocks')")]
    assert "state.runner?.freshness" in block, block
