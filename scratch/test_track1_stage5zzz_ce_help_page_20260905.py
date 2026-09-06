"""Stage 5ZZZ-CE. The help page, and the two ways it can rot.

A help page is the one artefact nothing breaks when it goes wrong. The dashboard keeps
rendering, the numbers keep being right, and the sentence explaining them quietly stops being
true. Two failure modes, one gate each:

  ORPHANS   a panel is added and nobody writes its section, or a section is renamed and the
            link from the panel lands on nothing. Neither shows up as an error -- the browser
            just scrolls to the top of the page and the reader assumes they missed it.

  DRIFT     a number in the prose stops matching the thing it describes. `1.585` is the most
            dangerous one on the page: it is log2(3) and nothing about it says so, so the day
            a fourth regime state is added it becomes a confidently wrong ceiling that a
            reader has no way to check.

The prose itself is hand-written on purpose -- generated explanations read like the thing they
are explaining, which is the problem. What is pinned here is only the load-bearing numbers.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from monitor.test_realtime_dom import (  # noqa: F401,E402
    browser_page, realtime_server,
)

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "global_index" / "dash" / "realtime"
INDEX = (DASH / "index.html").read_text(encoding="utf-8")
# `realtime-next` KHÔNG dùng chung markup — nó là bản sao riêng, và cũ hơn: nó thiếu hẳn ba
# khung Market View, Calm và Regime. Bản đầu chỉ kiểm một file, nên trang mà chủ dự án đang
# xem có ĐÚNG 0 điểm vào trang trợ giúp và không cổng nào thấy.
NEXT_INDEX = (DASH.parent / "realtime-next" / "index.html").read_text(encoding="utf-8")
HELP = (DASH / "help.html").read_text(encoding="utf-8")


# -- the link between the two pages --------------------------------------------------------
def _panels():
    """(heading text, anchor or None) for every panel on the dashboard.

    Cut on the HEADINGS, not on `<section>`: sections nest -- the decision block holds three
    of them -- and a first version that split on the tag ran a panel's chunk into the next
    one, which would have credited a panel with the anchor belonging to its neighbour.
    """
    heads = list(re.finditer(r"<h[12][^>]*>(.*?)</h[12]>", INDEX, re.S))
    out = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(INDEX)
        anchor = re.search(r'data-help="([a-z0-9-]+)"', INDEX[h.end():end])
        # `Open Positions` carries a `legacy / drain` badge INSIDE its heading; the
        # panel's name is what precedes it.
        text = re.sub(r"<[^>]+>", "", h.group(1).split("<", 1)[0]).strip()
        out.append((text, anchor.group(1) if anchor else None))
    return out


def _help_headings():
    return dict(re.findall(
        r'<section class="help" id="([a-z0-9-]+)">\s*<h2>(.*?)</h2>', HELP, re.S))


def _help_anchors():
    return set(re.findall(r'<section class="help" id="([a-z0-9-]+)"', HELP))


def test_the_dashboard_has_the_panels_this_test_thinks_it_has():
    """The gate below is vacuous if the split finds nothing. Eleven panels carry a heading."""
    panels = _panels()
    assert len(panels) >= 11, panels
    assert "Now Monitor" in [t for t, _ in panels]
    assert "Source Clocks" in [t for t, _ in panels]


def test_every_panel_names_a_help_section():
    missing = [t for t, a in _panels() if not a]
    assert not missing, f"panels with no help anchor: {missing}"


def test_every_anchor_a_panel_names_exists_on_the_help_page():
    anchors = _help_anchors()
    assert anchors, "the help page has no sections"
    dangling = sorted({a for _, a in _panels() if a and a not in anchors})
    assert not dangling, f"links into nothing: {dangling}"


def test_no_help_section_is_unreachable():
    """A section nothing links to is a section nobody reads. `vocabulary` is the exception --
    it is shared by all of them and reached from the contents list at the top."""
    named = {a for _, a in _panels() if a}
    orphans = sorted(_help_anchors() - named - {"vocabulary"})
    assert not orphans, f"sections no panel links to: {orphans}"


def test_the_contents_list_reaches_every_section():
    linked = set(re.findall(r'<a href="#([a-z0-9-]+)"', HELP))
    assert not _help_anchors() - linked, sorted(_help_anchors() - linked)


# -- the numbers -----------------------------------------------------------------------------
def _body():
    return HELP.split("<body>", 1)[1]


def test_the_entropy_ceiling_is_log2_of_the_state_count():
    """The one number on the page a reader cannot sanity-check for themselves.

    Written as "EVERY such number" rather than "this number appears somewhere": the ceiling is
    quoted twice, so a substring check passes while one of the two sentences is wrong. Mutation
    caught exactly that -- changing one of the pair left the gate green.
    """
    from global_index.track1_regime_record import N_STATES

    want = f"{math.log2(N_STATES):.3f}"
    quoted = set(re.findall(r"(?<![\d.])1\.\d+", _body()))
    assert quoted, "the page no longer states the ceiling at all"
    assert quoted == {want}, f"with {N_STATES} states the ceiling is {want}; page says {quoted}"


def test_the_frozen_fit_date_is_the_one_the_model_uses():
    from global_index.track1_regime_record import FIT_END

    year, month, day = FIT_END.split("-")
    month_name = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][int(month)]
    assert f"{month_name} {int(day)}, {year}" in HELP, FIT_END


def test_the_sleeve_hours_are_the_scheduled_hours():
    """Quoted in the vocabulary so a reader can tell which panel is even supposed to be busy.
    Read from the table the market view itself is built from."""
    from monitor.backend.track1_market_view import SLEEVES

    assert len(SLEEVES) == 3, SLEEVES.keys()
    for key, s in SLEEVES.items():
        span = f"{s['window_start']}&ndash;{s['window_end']}"
        assert span in HELP, f"{key}: the page does not say {span}"


def test_no_clock_time_on_the_page_is_invented():
    """Stronger than checking each time is present, and for the same reason as the ceiling:
    the Calm phases are quoted in three places, so "09:32 appears somewhere" stays true while
    two of the three say something else. This says every time on the page is a REAL scheduled
    time, and that none has gone missing.
    """
    from global_index.track1_slots import TRACK1_SLOTS
    from monitor.backend.track1_market_view import SLEEVES

    calm = [s for s in TRACK1_SLOTS if s.sleeve == "roska4_calm"]
    assert len(calm) == 2, calm
    scheduled = {f"{s.hour:02d}:{s.minute:02d}" for s in calm}
    for sl in SLEEVES.values():
        scheduled |= {sl["window_start"], sl["window_end"]}

    on_page = set(re.findall(r"(?<![\d:])([0-2]\d:[0-5]\d)(?![\d:])", _body()))
    assert on_page == scheduled, (
        f"invented: {sorted(on_page - scheduled)} / dropped: {sorted(scheduled - on_page)}")


def test_the_slot_count_and_the_cadence_are_the_real_ones():
    from global_index.track1_slots import TRACK1_SLOTS

    assert f"{len(TRACK1_SLOTS)} of them" in HELP, len(TRACK1_SLOTS)
    window = sorted(s.hour * 60 + s.minute for s in TRACK1_SLOTS
                    if s.sleeve == "roska4_stress")
    gaps = {b - a for a, b in zip(window, window[1:])}
    assert gaps == {5}, gaps
    assert "every five minutes" in " ".join(HELP.split())


# -- how it is written ------------------------------------------------------------------------
@pytest.mark.parametrize("banned, why", [
    (".py", "a file name"),
    ("Stage 5", "an internal work-item code"),
    ("()", "a function name"),
])
def test_the_page_points_at_mechanisms_not_at_source_code(banned, why):
    """The register agreed for this page: a reader with no background must get through it.
    Naming the file something lives in helps only a reader who already knew the answer."""
    assert banned not in _body(), f"the help text contains {why}: {banned!r}"


def test_the_page_needs_nothing_to_render():
    """It is read when something is broken. A help page that fetches is a help page that can
    be down at exactly the moment it is wanted."""
    assert "<script" not in HELP
    assert "fetch(" not in HELP


def test_the_page_is_served():
    from monitor.backend.app import app

    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/realtime/help" in rules, sorted(rules)


def test_the_link_survives_a_rerender():
    """Nearly every `source-note` on the dashboard has its `textContent` rewritten on each
    poll. A handler bound to the text would last one cycle; this one is bound to the element."""
    js = (DASH / "realtime.js").read_text(encoding="utf-8")
    block = js.split("querySelectorAll('[data-help]')", 1)[1][:900]
    assert "addEventListener('click'" in block
    assert "innerHTML" not in block, "the wiring rewrites the line it is attached to"


def test_a_help_section_carries_the_panels_own_name():
    """Otherwise a rename leaves the reader hunting for a heading that is no longer there --
    and the link still works, which is worse than one that visibly breaks."""
    named = {a: t for t, a in _panels() if a}
    checked = 0
    for anchor, heading in _help_headings().items():
        if anchor not in named:
            continue
        got = re.sub(r"<[^>]+>", "", heading)
        got = " ".join(got.replace("&middot;", "·").split())
        want = " ".join(named[anchor].replace("&middot;", "·").split())
        assert got == want, f"help says {got!r}, the dashboard says {want!r}"
        checked += 1
    assert checked >= 11, f"only {checked} sections were compared"


# ── liên kết phải BẤM ĐƯỢC, đo trên trang thật ─────────────────────────────────────────
@pytest.mark.parametrize("path", ["/realtime", "/realtime-next"])
def test_moi_neo_tro_giup_van_bam_duoc_sau_nhieu_luot_ve(
        realtime_server, browser_page, path):
    """Cổng đọc mã nguồn xanh trong khi HAI lối vào đã tàng hình trên trang thật.

    Bản đầu gắn một lớp CSS vào từng phần tử lúc khởi tạo và tô kiểu theo lớp đó. Đo được:
    `openIssuesSource` và `marketViewSource` mất lớp ngay sau lượt vẽ đầu tiên, vì bộ dựng
    của chúng gán đè `el.className = '...'`. Hai mục khác có cùng `has-tip` thì vẫn giữ, nên
    nhìn qua không ra quy luật — và không phép kiểm tĩnh nào thấy được, vì mã gắn lớp vẫn
    nguyên ở đó.

    Chính xác chúng mất gì: vẫn bấm được, nhưng mất gạch chân và con trỏ tay. Đột biến bắt
    tôi ở chỗ này — tôi đã viết "hai liên kết chết" và nó không đúng. Một lối vào không ai
    nhìn thấy vẫn là một lối vào không ai dùng, nên vẫn phải sửa; chỉ là sửa ở CSS.

    Cổng này vì thế hỏi cả hai: bấm có mở đúng neo không, VÀ trên màn hình có dấu hiệu nào
    nói rằng bấm được không.
    """
    browser_page.goto(f"{realtime_server}{path}", wait_until="domcontentloaded")
    browser_page.wait_for_selector("#statusRail .system-conclusion", timeout=25_000)
    browser_page.wait_for_timeout(6000)

    browser_page.evaluate("() => { window.__opened = [];"
                          " window.open = u => { window.__opened.push(u); return null; }; }")
    anchors = browser_page.evaluate(
        "() => [...document.querySelectorAll('[data-help]')].map(e => e.dataset.help)")
    assert len(anchors) >= 8, f"chỉ thấy {len(anchors)} neo — trang mất điểm vào trợ giúp"
    assert len(set(anchors)) == len(anchors), f"neo trùng: {anchors}"

    for a in anchors:
        browser_page.eval_on_selector(f"[data-help='{a}']", "el => el.click()")
    opened = browser_page.evaluate("() => window.__opened")
    dead = [a for a in anchors if f"/realtime/help#{a}" not in opened]
    assert not dead, f"bấm không mở được: {dead}"

    for a in anchors:
        style = browser_page.eval_on_selector(
            f"[data-help='{a}']",
            "el => getComputedStyle(el).cursor + '|' + (el.getAttribute('role') || '-')")
        assert style == "pointer|link", (a, style)


def test_ban_thiet_ke_lai_cung_co_diem_vao_trang_tro_giup():
    """Mỗi khung nó CÓ đều phải có neo. Nó thiếu ba khung so với trang gốc — đó là việc
    khác, nhưng thiếu khung không phải lý do để những khung còn lại mất lối vào."""
    anchors = set(re.findall(r'data-help="([a-z0-9-]+)"', NEXT_INDEX))
    assert len(anchors) >= 8, sorted(anchors)
    assert not anchors - _help_anchors(), sorted(anchors - _help_anchors())
    heads = list(re.finditer(r"<h[12][^>]*>(.*?)</h[12]>", NEXT_INDEX, re.S))
    missing = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(NEXT_INDEX)
        if not re.search(r'data-help="', NEXT_INDEX[h.end():end]):
            missing.append(re.sub(r"<[^>]+>", "", h.group(1).split("<", 1)[0]).strip())
    assert not missing, f"khung không có lối vào trợ giúp: {missing}"
