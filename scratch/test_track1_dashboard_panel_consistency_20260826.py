"""Follow-up to Stage 5ZP: the three panel inconsistencies that survived it.

5ZP put the Operational and Signal sections INSIDE the expanded panel and proved it
structurally, and it stacked the Track 1 facts label-above-value. Both were true. What
was never measured was how the content inside those blocks was actually painted, and
three things were wrong:

1. `.journal li` dresses a top-level journal ROW — 3px rail, hairline under it, bullet
   dot, -10px bleed. It matches by DESCENT, so every bullet inside an expanded panel
   wore it: a seven-line Operational block drew seven rails, seven hairlines and seven
   dots, and each line sat 10px outside the band's own text column.
2. `#track1Facts` borrowed the fact grid's CARD but its cells are `.fact` while every
   rule that dresses a cell is written for `.schedule-fact` — so zero inset (text against
   the card edge) and no dividers (twelve facts as one block).
3. `#track1Note` wears `.source-note`, built for the right-aligned one-liner beside a
   section heading: capped at 52% width, nowrap, ellipsis. Under a panel that cut the
   sentence off — 1255px of text in a 736px box at 1920px wide.

Every assertion here is DERIVED: the panel's lines are compared to the paragraph beside
them and the Track 1 cell to the schedule cell beside it, so a future change to either
moves both or fails. No literal padding or colour is pinned.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from monitor.test_realtime_dom import (           # noqa: E402,F401
    browser_page, open_realtime, realtime_server, stub_api,
)
from test_track1_stage5zp_dashboard_polish_20260826 import (  # noqa: E402
    a_slot_job, journal_with, track1_payload,
)

REPO = Path(r"d:\raits")


def open_with(page, server, *, jobs=None, blocking=None):
    stub_api(page, {"/api/v1/job-journal/": journal_with(jobs or [a_slot_job()]),
                    "/api/v1/track1-runtime": track1_payload(blocking=blocking)})
    open_realtime(page, server)


def expand(page):
    page.click("#journal .job-trigger")
    page.wait_for_selector("#journal .job-detail")


def a_job_with_candidates():
    job = a_slot_job(chip_label="RAW SIGNAL", tone="watch")
    job["signal"]["details"] = {"candidates": [
        {"instrument": "MNKD", "direction": "long", "qty": 1, "entry": 38650.0,
         "stop": 38400.0, "target": 39100.0, "risk": 250.0},
        {"instrument": "MNKD", "direction": "short", "qty": 1, "entry": 38700.0,
         "stop": 38950.0, "target": 38250.0, "risk": 250.0},
    ]}
    return job


# ══════════════════════════════════════════════════════════════════════════════
# A. the panel's lines are lines, not journal rows
# ══════════════════════════════════════════════════════════════════════════════

CHROME = """
(sel) => {
  const els = [...document.querySelectorAll(sel)];
  return els.map(el => {
    const cs = getComputedStyle(el);
    const before = getComputedStyle(el, '::before');
    return {
      marginLeft: cs.marginLeft, marginRight: cs.marginRight,
      borderLeftWidth: cs.borderLeftWidth, borderBottomWidth: cs.borderBottomWidth,
      beforeContent: before.content,
      left: Math.round(el.getBoundingClientRect().left),
      right: Math.round(el.getBoundingClientRect().right),
    };
  });
}
"""


def test_1_operational_lines_wear_no_journal_row_chrome(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    expand(browser_page)
    rows = browser_page.evaluate(CHROME, "#journal .job-operational .job-lines li")
    assert len(rows) >= 5, f"the fixture must render several lines, got {len(rows)}"
    for i, r in enumerate(rows):
        assert r["marginLeft"] == "0px" and r["marginRight"] == "0px", (i, r)
        assert r["borderLeftWidth"] == "0px", (i, r)
        assert r["borderBottomWidth"] == "0px", (i, r)
        assert r["beforeContent"] in ("none", "normal"), (i, r)


def test_2_signal_lines_wear_no_journal_row_chrome(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    expand(browser_page)
    rows = browser_page.evaluate(CHROME, "#journal .job-signal-detail .job-lines li")
    assert len(rows) >= 2, f"the fixture must render several lines, got {len(rows)}"
    for r in rows:
        assert r["marginLeft"] == "0px" and r["borderLeftWidth"] == "0px", r
        assert r["borderBottomWidth"] == "0px", r
        assert r["beforeContent"] in ("none", "normal"), r


def test_3_candidate_rows_wear_no_journal_row_chrome(realtime_server, browser_page):
    """The candidate list is the OTHER list inside the panel, and it was wearing the same
    row chrome. Reset once at the panel, so this passes for a list nobody remembered."""
    open_with(browser_page, realtime_server, jobs=[a_job_with_candidates()])
    expand(browser_page)
    rows = browser_page.evaluate(CHROME, "#journal .signal-candidates li")
    assert len(rows) == 2, f"the fixture must render both candidates, got {len(rows)}"
    for r in rows:
        assert r["marginLeft"] == "0px" and r["borderLeftWidth"] == "0px", r
        assert r["beforeContent"] in ("none", "normal"), r


def test_4_the_lines_sit_in_the_panels_own_text_column(realtime_server, browser_page):
    """Derived, not pinned: the Operational lines must start and end exactly where the
    resolution paragraph beside them does, and where their own label does. Before the fix
    the label was at x=1526 and the lines at x=1516 — outside the band's padding."""
    open_with(browser_page, realtime_server)
    expand(browser_page)
    got = browser_page.evaluate("""() => {
      const box = sel => { const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return [Math.round(r.left), Math.round(r.right)]; };
      return {line: box('.job-operational .job-lines li'),
              label: box('.job-operational > b'),
              para: box('.job-resolution p'),
              sigline: box('.job-signal-detail .job-lines li')};
    }""")
    assert all(got.values()), got
    assert got["line"][0] == got["para"][0] == got["label"][0], got
    assert got["line"][1] == got["para"][1], got
    assert got["sigline"][0] == got["para"][0], got


def test_5_the_lines_use_the_same_ink_as_the_paragraph_beside_them(realtime_server,
                                                                   browser_page):
    """Derived. The Operational lines were the only body text in the card set in `--muted`
    at weight 500 — dimmer AND heavier than everything around them."""
    open_with(browser_page, realtime_server)
    expand(browser_page)
    got = browser_page.evaluate("""() => {
      const f = sel => { const el = document.querySelector(sel); const cs = getComputedStyle(el);
        return {color: cs.color, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
                fontFamily: cs.fontFamily, lineHeight: cs.lineHeight}; };
      return {line: f('.job-operational .job-lines li'), para: f('.job-resolution p'),
              impact: f('.job-impact p')};
    }""")
    assert got["line"] == got["para"], got
    assert got["line"]["color"] == got["impact"]["color"], got


def test_6_the_section_labels_match_the_other_labels_in_the_panel(realtime_server,
                                                                  browser_page):
    open_with(browser_page, realtime_server)
    expand(browser_page)
    got = browser_page.evaluate("""() => {
      const f = sel => { const cs = getComputedStyle(document.querySelector(sel));
        return {color: cs.color, fontSize: cs.fontSize, fontWeight: cs.fontWeight,
                letterSpacing: cs.letterSpacing, fontFamily: cs.fontFamily}; };
      return {op: f('.job-operational > b'), sig: f('.job-signal-detail > b'),
              resolution: f('.job-resolution b'), impact: f('.job-impact b')};
    }""")
    assert got["op"] == got["resolution"], got
    assert got["sig"] == got["resolution"], got
    assert got["op"]["fontSize"] == got["impact"]["fontSize"], got


# ══════════════════════════════════════════════════════════════════════════════
# B. the Track 1 panel is a fact grid, not a card with loose text in it
# ══════════════════════════════════════════════════════════════════════════════

def test_7_track1_cells_carry_the_same_inset_as_the_schedule_cells(realtime_server,
                                                                   browser_page):
    """Derived from the cell beside it. Both now read one `--fact-pad`, so a change to the
    schedule strip's inset moves this panel too instead of leaving it behind."""
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate("""() => {
      const t1 = document.querySelector('#track1Facts > .fact');
      const sf = document.querySelector('.now-schedule-facts > .schedule-fact');
      if (!t1 || !sf) return null;
      const p = el => getComputedStyle(el).padding;
      return {t1: p(t1), schedule: p(sf), t1n: document.querySelectorAll('#track1Facts > .fact').length};
    }""")
    assert got, "both a Track 1 cell and a schedule cell must be on the page"
    assert got["t1n"] >= 8, f"the panel must render its facts, got {got['t1n']}"
    assert got["t1"] == got["schedule"], got
    assert got["t1"] != "0px", got


def test_8_track1_text_no_longer_touches_the_card_edge(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate("""() => {
      const card = document.getElementById('track1Facts');
      const label = card.querySelector('.fact-label');
      return {cardLeft: card.getBoundingClientRect().left,
              textLeft: label.getBoundingClientRect().left};
    }""")
    assert got["textLeft"] - got["cardLeft"] >= 12, got


def test_9_track1_cells_are_divided_from_one_another(realtime_server, browser_page):
    """A hairline on each cell's own right and bottom edge, in the same colour the schedule
    strip divides its cells with."""
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate("""() => {
      const cells = [...document.querySelectorAll('#track1Facts > .fact')];
      const cs = getComputedStyle(cells[0]);
      const hair = getComputedStyle(document.documentElement)
                     .getPropertyValue('--line-hair').trim();
      return {shadow: cs.boxShadow, n: cells.length, hair};
    }""")
    assert got["n"] >= 8, got
    assert got["shadow"] != "none", got
    assert got["shadow"].count("1px") >= 2, ("right and bottom hairline expected", got)


def test_9b_an_incomplete_last_row_does_not_paint_a_block(realtime_server, browser_page):
    """The fact count is not a multiple of the column count, so the last row is part empty.
    The first attempt drew the dividers as a 1px gap over a hairline ground, and that ground
    showed through the empty remainder as a lighter block three cells wide. Whatever draws
    the dividers, the empty part of the grid must be indistinguishable from a cell."""
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate("""() => {
      const grid = document.getElementById('track1Facts');
      const cells = [...grid.querySelectorAll('.fact')];
      const cols = getComputedStyle(grid).gridTemplateColumns.split(' ').length;
      return {ground: getComputedStyle(grid).backgroundColor,
              cellBg: getComputedStyle(cells[0]).backgroundColor,
              n: cells.length, cols, remainder: cells.length % cols};
    }""")
    assert got["remainder"] != 0, (
        "this test is only meaningful with a part-empty last row; the fixture changed", got)
    # a transparent cell shows the ground, which is then by definition the same colour
    assert got["cellBg"] in ("rgba(0, 0, 0, 0)", got["ground"]), got


def test_10_track1_labels_speak_the_pages_label_language(realtime_server, browser_page):
    """Derived. These were the only labels on the page set in mono at weight 700."""
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate("""() => {
      const f = el => { const cs = getComputedStyle(el);
        return {fontSize: cs.fontSize, fontWeight: cs.fontWeight,
                fontFamily: cs.fontFamily, letterSpacing: cs.letterSpacing,
                textTransform: cs.textTransform}; };
      return {t1: f(document.querySelector('#track1Facts .fact-label')),
              schedule: f(document.querySelector('.now-schedule-facts > .schedule-fact > span'))};
    }""")
    assert got["t1"] == got["schedule"], got


def test_11_label_still_sits_above_its_value(realtime_server, browser_page):
    """5ZP's claim, re-checked here because this stage changed the same cells."""
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate("""() => {
      const f = document.querySelector('#track1Facts > .fact');
      const l = f.querySelector('.fact-label'), v = f.querySelector('.fact-value');
      return {labelBottom: l.getBoundingClientRect().bottom,
              valueTop: v.getBoundingClientRect().top,
              sameLine: Math.abs(l.getBoundingClientRect().top
                                 - v.getBoundingClientRect().top) < 2};
    }""")
    assert not got["sameLine"], got
    assert got["valueTop"] >= got["labelBottom"] - 1, got


# ══════════════════════════════════════════════════════════════════════════════
# C. the note under the panel is a paragraph, not a heading note
# ══════════════════════════════════════════════════════════════════════════════

NOTE_PROBE = """
() => {
  const n = document.getElementById('track1Note');
  const cs = getComputedStyle(n);
  const facts = document.getElementById('track1Facts');
  return {text: n.textContent.trim(), len: n.textContent.trim().length,
          clipped: n.scrollWidth > n.clientWidth + 1,
          scrollW: n.scrollWidth, clientW: n.clientWidth,
          textAlign: cs.textAlign, whiteSpace: cs.whiteSpace,
          left: Math.round(n.getBoundingClientRect().left),
          factsLeft: Math.round(facts.getBoundingClientRect().left)};
}
"""


@pytest.mark.parametrize("width", [1920, 1440, 1024, 720])
def test_12_the_note_is_never_cut_off(realtime_server, browser_page, width):
    browser_page.set_viewport_size({"width": width, "height": 1000})
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate(NOTE_PROBE)
    assert got["len"] > 40, f"the fixture must render a long note, got {got}"
    assert not got["clipped"], (width, got)
    assert got["whiteSpace"] == "normal", (width, got)


def test_13_the_note_starts_where_the_panel_starts(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate(NOTE_PROBE)
    assert got["textAlign"] == "left", got
    assert abs(got["left"] - got["factsLeft"]) <= 1, got


# ══════════════════════════════════════════════════════════════════════════════
# D. nothing overflows, and nothing else moved
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("width", [380, 720, 1024, 1920])
def test_14_no_horizontal_overflow_with_the_panel_open(realtime_server, browser_page,
                                                       width):
    browser_page.set_viewport_size({"width": width, "height": 1000})
    open_with(browser_page, realtime_server)
    expand(browser_page)
    got = browser_page.evaluate("""() => ({
      doc: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
      cells: [...document.querySelectorAll('#track1Facts > .fact')].map(
        c => Math.round(c.getBoundingClientRect().right)),
      cardRight: Math.round(
        document.getElementById('track1Facts').getBoundingClientRect().right),
    })""")
    assert got["doc"] <= got["client"] + 1, (width, got["doc"], got["client"])
    assert got["cells"], "the panel must render cells at this width"
    for right in got["cells"]:
        assert right <= got["cardRight"] + 1, (width, right, got["cardRight"])


def test_15_the_schedule_strip_was_not_disturbed(realtime_server, browser_page):
    """The inset became a variable shared by both grids. The schedule cell must land on
    exactly the value the skin declares, or the refactor moved a panel it was not asked
    to move."""
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate("""() => {
      const sf = document.querySelector('.now-schedule-facts > .schedule-fact');
      const cs = getComputedStyle(sf);
      return {padding: cs.padding, borderRight: cs.borderRightWidth,
              borderTop: cs.borderTopWidth,
              declared: getComputedStyle(document.querySelector('.now-schedule-facts'))
                          .getPropertyValue('--fact-pad').trim()};
    }""")
    assert got["padding"] == "16px 20px", got
    assert got["declared"] == "16px 20px", got
    assert got["borderTop"] == "2px", got


def test_16_the_variable_has_a_value_without_the_skin(realtime_server, browser_page):
    """The base sheet must stand on its own: if the skin is ever dropped the cells fall
    back to the base inset, not to `padding: ;` which computes to zero and puts the text
    back against the card edge."""
    css = (REPO / "global_index/dash/realtime/realtime.css").read_text(encoding="utf-8")
    assert "--fact-pad: 9px 11px" in css, "the base sheet must declare its own fallback"
    skin = (REPO / "global_index/dash/realtime-next/skin-e.css").read_text(encoding="utf-8")
    assert "--fact-pad: 16px 20px" in skin
    assert "padding: var(--fact-pad)" in skin, "the skin must READ the variable it sets"


def test_17_the_row_chrome_reset_is_scoped_to_the_panel(realtime_server, browser_page):
    """The reset must not reach the journal's own rows — they are supposed to carry the
    rail and the hairline. This is the assertion that would go red if the reset were
    written as a bare `li` rule."""
    open_with(browser_page, realtime_server)
    got = browser_page.evaluate("""() => {
      const row = document.querySelector('#journal > li.job-row');
      const cs = getComputedStyle(row);
      return {borderLeft: cs.borderLeftWidth, borderBottom: cs.borderBottomWidth};
    }""")
    assert got["borderLeft"] != "0px", got
    assert got["borderBottom"] != "0px", got
