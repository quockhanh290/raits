# -*- coding: utf-8 -*-
"""The decision heading must name the day it is showing, and say when that is not today.

Found on 2026-09-27, a Sunday. Nothing had run since Friday, so the panel rendered Friday's
Nikkei entry — correctly, because it shows the newest snapshot and a quiet day should still show
the last day that decided. But the heading was the hardcoded string "Today's Decision", so the
operator read a two-day-old entry as today's and asked why there was an order on a closed market.

The date was already on screen, in the source note beside the heading. That was not enough. A
reader scans the heading first, which is the whole reason a heading may not assert something the
data does not support.

What is NOT being changed, and is asserted here so nobody changes it by accident: the panel still
selects the newest snapshot. Showing nothing on a quiet day would be worse.
"""
import json
import re
from pathlib import Path

import pytest

JS = Path("global_index/dash/realtime/realtime.js")
HTML = Path("global_index/dash/realtime/index.html")


def test_the_heading_is_not_a_hardcoded_claim_about_today():
    html = HTML.read_text(encoding="utf-8")
    assert "<h2>Today's Decision</h2>" not in html, (
        "the heading asserts today in static markup again, so it is right only on days when the "
        "newest snapshot happens to be today")
    assert 'id="decisionHeading"' in html, "the heading needs an id for the render to set it"


def test_the_render_sets_the_heading_from_the_snapshot_day():
    src = JS.read_text(encoding="utf-8")
    block = src[src.index("const decisionDay ="):src.index("const decisionDay =") + 900]
    assert "decisionHeading" in block
    assert "snap.date" in block, "the heading must be derived from the snapshot's own day"
    assert "etToday()" in block, (
        "today must come from the ET helper that honours the server clock, not from the browser")
    assert "not today" in block, "the heading must say plainly when the day shown is not today"


def test_all_three_cases_are_distinguishable():
    """Same day, another day, and no day at all must each produce different heading text."""
    src = JS.read_text(encoding="utf-8")
    start = src.index("const decisionDay =")
    block = src[start:start + 900]
    texts = re.findall(r"headingEl\.textContent = ([^;]+);", block)
    assert len(texts) == 3, ("expected three distinct headings — today, another day, and no day "
                             "recorded — found %d: %r" % (len(texts), texts))
    assert len(set(texts)) == 3, "two of the three cases render the same text: %r" % (texts,)


def test_the_newest_snapshot_is_still_what_is_shown():
    """The control. If a fix ever made the panel show only today, a quiet day would show nothing."""
    src = JS.read_text(encoding="utf-8")
    assert "renderDecisions(snap)" in src
    assert "const snap = latestSnap()" in src, (
        "the panel must still render the newest snapshot; showing nothing on a quiet day is worse "
        "than showing the last day that decided, provided the heading says which day that is")


def test_the_live_records_make_this_case_real_rather_than_hypothetical():
    """Not a mutation test — a statement that the situation this guards against is the live one."""
    days = sorted(p.name for p in Path("global_index/track1_runtime/window_coverage").glob("*.jsonl"))
    if not days:
        pytest.skip("no window coverage records on this machine")
    newest = days[-1]
    assert re.search(r"\d{8}", newest), newest
    # The point: a gap between the newest record and today is normal — weekends, holidays, any
    # quiet stretch — which is exactly why the heading cannot assume they are the same day.
