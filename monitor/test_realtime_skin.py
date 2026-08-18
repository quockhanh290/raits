"""Bất biến của lớp thiết kế trên /realtime.

Mỗi test ở đây tương ứng một lỗi ĐÃ xảy ra trong lúc dựng, và mỗi lỗi đó đã sống
sót qua nhiều lượt tự kiểm bằng mắt hoặc bằng một phép đo nhìn nhầm chỗ. Docstring
của từng test ghi lại ca thật, vì một test không nói được nó bảo vệ điều gì thì
người sau sẽ xoá nó khi nó cản đường.

Vì sao là file riêng: `test_realtime_dom.py` đang được một phiên khác sửa. Fixture
ở đây là bản riêng, còn `stub_api` / `BASE_PAYLOADS` / `open_realtime` thì dùng
lại của file kia — trùng lặp payload sẽ tạo ra một bộ dữ liệu thứ hai trôi khỏi
bản gốc.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

from monitor.backend.app import app
from monitor.test_realtime_dom import (  # noqa: F401  (helper, không phải fixture)
    M2K_RUNNER,
    _broker,
    _persisted_runner_positions,
    _runner_positions,
    open_realtime,
    stub_api,
)

from playwright.sync_api import sync_playwright  # noqa: E402

DASH = Path(__file__).resolve().parents[1] / "global_index" / "dash"


@pytest.fixture(scope="module")
def skin_server():
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
def skin_page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            yield page
        finally:
            browser.close()


# ── Phần tử bị che khuất thì không va chạm với ai ──────────────────────────────
# `Range.getClientRects()` trả hình học cho cả dòng đã bị cắt và không bao giờ
# được vẽ. Bỏ qua bước này thì mọi thẻ tóm tắt dùng `-webkit-line-clamp` đều bị
# báo là chữ đè chữ, và mọi dòng cuộn khỏi mép một khung `overflow:auto` cũng vậy.
# Danh sách phải đủ bốn: hidden, clip, auto, scroll.
_OUT_OF_VIEW = """
  (el, rect) => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (!/hidden|clip|auto|scroll/.test(cs.overflowY + ' ' + cs.overflowX)) continue;
      const b = p.getBoundingClientRect();
      if (rect.top >= b.bottom - 1 || rect.bottom <= b.top + 1) return true;
      if (rect.left >= b.right - 1 || rect.right <= b.left + 1) return true;
    }
    return false;
  }
"""

_TEXT_COLLISIONS = """
() => {
  // Bố trí xong KHÔNG có nghĩa là được vẽ. Nội dung của `<details>` đóng nằm
  // dưới `content-visibility: hidden`: `getBoundingClientRect()` vẫn trả kích
  // thước cũ, còn `elementFromPoint` tại tâm nó trả về phần tử phía sau. Bỏ qua
  // bước này thì mỗi khối thu gọn thành một chùm "chữ đè chữ" giả — đã đo:
  // /paper Gates ở 390px báo 397 va chạm, lọc đúng còn 0, và 348 trên 693 node
  // được đếm là ma.
  const notPainted = el => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.contentVisibility === 'hidden' || cs.visibility === 'hidden') return true;
      const parent = p.parentElement;
      if (parent && parent.tagName === 'DETAILS' && !parent.open && p.tagName !== 'SUMMARY')
        return true;
    }
    return false;
  };
  const outOfView = %s;
  const leaves = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (!n.nodeValue.trim()) continue;
    if (n.parentElement.closest('[hidden]') || notPainted(n.parentElement)) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    for (const rect of r.getClientRects()) {
      if (rect.width < 1 || rect.height < 1) continue;
      if (outOfView(n.parentElement, rect)) continue;
      leaves.push({ t: n.nodeValue.trim().slice(0, 30), el: n.parentElement, rect });
    }
  }
  const hits = [];
  for (let i = 0; i < leaves.length; i++)
    for (let j = i + 1; j < leaves.length; j++) {
      const a = leaves[i].rect, b = leaves[j].rect;
      if (leaves[i].el.contains(leaves[j].el) || leaves[j].el.contains(leaves[i].el)) continue;
      const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (ox > 1 && oy > 3) hits.push(leaves[i].t + '  X  ' + leaves[j].t);
    }
  return { measured: leaves.length, hits };
}
""" % _OUT_OF_VIEW


def test_realtime_serves_the_skin_it_was_designed_with(skin_server, skin_page):
    """Đo được 2026-08-17: trang thật không nạp skin nào, suốt hàng chục lượt.

    Toàn bộ thiết kế được dựng và đo trên `preview.html?skin=e`, trong khi
    `/realtime` chỉ nạp fonts + realtime.css + next.css. Mọi báo cáo "0 va chạm,
    màu đã khớp" đều đúng ở chỗ đo và **vô nghĩa ở chỗ người dùng nhìn**: trên
    trang thật, vạch bên thẻ sự cố vẫn là #8b72ff của bảng nền và khung chi tiết
    không có vạch nào.

    Không có phép kiểm nào kêu, vì thiếu một `<link>` thì trang vẫn chạy — chỉ là
    chạy với giao diện khác. Đây là phép kiểm rẻ nhất bắt được điều đó.
    """
    stub_api(skin_page)
    open_realtime(skin_page, skin_server)
    loaded = skin_page.evaluate(
        "() => [...document.styleSheets].map(s => (s.href || '').split('/').pop())")
    assert any(name.startswith("skin-") for name in loaded), (
        f"/realtime không nạp skin nào; chỉ có: {loaded}")
    for required in ("next.css", "fonts.css"):
        assert required in loaded, f"thiếu {required}; đang nạp: {loaded}"
    scripts = skin_page.evaluate(
        "() => [...document.scripts].map(s => (s.src || '').split('/').pop())")
    assert "next.js" in scripts, f"thiếu lớp bổ sung next.js; đang nạp: {scripts}"


def test_every_element_the_script_writes_to_is_on_the_page(skin_server, skin_page):
    """Đo được 2026-08-17: `#schedulerContext` biến mất khỏi route mới.

    `realtime.js:377` bọc nó trong `if (spEl)`, nên **không có gì sập** — nó chỉ
    im lặng ngừng báo `Scheduler DOWN`, `Scheduler xN RUNNING` và
    `RUNNING OLD CRON`. Hai scheduler chạy cùng lúc chính là thứ đã làm hỏng sáu
    slot vào lệnh; dòng "on schedule" ở nhật ký trả lời câu hỏi khác và tooltip
    của nó nói rõ như vậy.

    Danh sách id được RÚT TỪ chính realtime.js chứ không viết cứng ở đây: viết
    cứng thì thêm một `$('...')` mới sẽ không ai kiểm, và test sẽ ghim một bản
    chụp thay vì ghim hợp đồng.
    """
    source = (DASH / "realtime" / "realtime.js").read_text(encoding="utf-8")
    # Bỏ comment trước khi rút. `realtime.js:665` giữ một ghi chú nhắc rằng
    # `$('schedulerHealth')` đã bị gỡ và VÌ SAO — đọc cả comment thì test đòi một
    # element mà việc xoá nó chính là bản sửa.
    stripped = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    stripped = re.sub(r"^\s*//.*$", "", stripped, flags=re.M)
    wanted = sorted(set(re.findall(r"\$\('([A-Za-z][A-Za-z0-9_-]*)'\)", stripped)))
    assert len(wanted) > 30, f"chỉ rút được {len(wanted)} id — regex hỏng, không phải trang sạch"

    stub_api(skin_page)
    open_realtime(skin_page, skin_server)
    counts = skin_page.evaluate(
        "ids => Object.fromEntries(ids.map(i => [i, document.querySelectorAll('#' + CSS.escape(i)).length]))",
        wanted)
    missing = sorted(i for i, c in counts.items() if c == 0)
    duplicated = sorted(i for i, c in counts.items() if c > 1)
    assert not missing, f"realtime.js ghi vào các id không có trên trang: {missing}"
    assert not duplicated, f"id xuất hiện nhiều hơn một lần: {duplicated}"


@pytest.mark.parametrize("width,height", [(1900, 1000), (1440, 900), (390, 844)])
def test_no_text_sits_on_top_of_other_text(skin_server, skin_page, width, height):
    """Cạm bẫy gốc của cả đợt rà soát: chữ vượt mép và bị CẮT, `scrollWidth` vẫn xanh.

    Ca thật đã đo: header trải 608px trong viewport 487px. Phép kiểm cuộn ngang
    không thấy gì vì trang không cuộn — phần thừa bị cắt.

    Phép kiểm này so hình chữ nhật TỪNG DÒNG của từng node văn bản. Nó chỉ có
    nghĩa khi loại được phần đã bị che: nếu không, mọi thẻ kẹp dòng và mọi khung
    cuộn đều báo đỏ giả — đã dính đúng hai lần, một lần 2 báo giả, một lần 11.
    """
    skin_page.set_viewport_size({"width": width, "height": height})
    stub_api(skin_page)
    open_realtime(skin_page, skin_server)
    result = skin_page.evaluate(_TEXT_COLLISIONS)
    assert result["measured"] > 60, (
        f"chỉ đo được {result['measured']} node ở {width}x{height} — trang chưa render, "
        "một khẳng định 'không va chạm' trên đó không kiểm gì cả")
    assert result["hits"] == [], (
        f"chữ đè chữ ở {width}x{height}: {result['hits'][:6]}")


def test_the_font_control_actually_changes_the_font(skin_server, skin_page):
    """Đo được 2026-08-17: bộ đổi font đã chết dưới skin, không có gì kêu.

    Bộ điều khiển ghi lựa chọn vào `<html data-font>` và bảng nền biến nó thành
    `--font-ui`. Skin lại khai `--mono` là một giá trị cứng, nên nó đọc một biến
    không ai ghi: bấm Courier hay System thì `data-font` đổi, `--font-ui` đổi, và
    **font hiển thị đứng yên**.

    Vì thế test này không so biến CSS — nó lái đúng cái `<select>` và đọc
    `fontFamily` đã tính. So biến sẽ xanh trong đúng cái trạng thái hỏng này.
    """
    stub_api(skin_page)
    open_realtime(skin_page, skin_server)
    rendered = skin_page.evaluate("""
        async () => {
          const sel = document.getElementById('fontSelector');
          const sample = document.getElementById('metricEquity');
          const seen = [];
          for (const f of ['cascadia', 'jetbrains', 'courier', 'system', 'ibm-plex']) {
            sel.value = f;
            sel.dispatchEvent(new Event('change', { bubbles: true }));
            await new Promise(r => setTimeout(r, 120));
            seen.push(getComputedStyle(sample).fontFamily);
          }
          return seen;
        }""")
    assert len(set(rendered)) == len(rendered), (
        "hai lựa chọn font cho ra cùng một họ chữ — bộ điều khiển không tới được "
        f"thứ đang vẽ: {rendered}")


def test_no_card_sits_inside_a_card_inside_a_card(skin_server, skin_page):
    """Đo được 2026-08-16: 13 chỗ lồng thẻ, và bộ dò đầu tiên bỏ sót một nửa.

    Bộ dò ban đầu đòi phải có CẢ viền lẫn nền mới tính là thẻ, nên nó không thấy
    `.decision-shell` và `.table-wrap` — hai khối có viền đủ bốn cạnh trên nền
    trong suốt. Chủ dự án nhìn ra trước phép đo.

    Điều kiện dưới đây là "từ ba cạnh có viền TRỞ LÊN, HOẶC có nền kèm bo góc".
    """
    stub_api(skin_page)
    open_realtime(skin_page, skin_server)
    nested = skin_page.evaluate("""
        () => {
          const isCard = el => {
            const cs = getComputedStyle(el);
            const sides = ['Top', 'Right', 'Bottom', 'Left'].filter(s =>
              parseFloat(cs['border' + s + 'Width']) > 0
              && cs['border' + s + 'Style'] !== 'none'
              && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(cs['border' + s + 'Color'])).length;
            const filled = !/rgba\\(0, 0, 0, 0\\)|transparent/.test(cs.backgroundColor);
            return sides >= 3 || (filled && parseFloat(cs.borderRadius) > 0);
          };
          const out = [];
          document.querySelectorAll('main *').forEach(el => {
            const r = el.getBoundingClientRect();
            if (r.width < 60 || r.height < 30) return;   // chip và chấm không phải thẻ
            if (!isCard(el)) return;
            let depth = 0;
            for (let p = el.parentElement; p && p !== document.body; p = p.parentElement)
              if (isCard(p)) depth++;
            if (depth >= 2) out.push((el.className || el.tagName).toString().slice(0, 40));
          });
          return out;
        }""")
    assert nested == [], f"thẻ lồng trong thẻ lồng trong thẻ: {nested}"


def test_a_status_chip_carries_its_state_in_the_letters(skin_server, skin_page):
    """Đo được 2026-08-17: chip KNOWN DEBT trùng đúng màu tím của chip RUNNER.

    Nguyên nhân là chính bản sửa trước đó: khai lại `--violet` cho khớp bản dựng,
    mà không rà xem bảng nền còn dùng token ấy ở đâu. `realtime.css:219` dùng nó
    cho một nghĩa hoàn toàn khác, nên nguồn và trạng thái đội cùng một màu.

    Bất biến: viền chip trung tính, màu nằm ở chữ. Như thế hai chip cạnh nhau
    không bao giờ nhòe vào nhau, và trạng thái vẫn đọc được khi không phân biệt
    được màu.
    """
    # Payload mặc định không có sự cố nào, nên trang không vẽ chip nào và phép
    # kiểm sẽ duyệt một danh sách rỗng — xanh mà chưa kiểm gì. Dựng đúng một sự
    # cố: runner giữ vị thế mà broker không có.
    stub_api(skin_page, {
        "/api/v1/broker": _broker([], []),
        "/api/v1/runner-state": _runner_positions(M2K_RUNNER),
        "/api/v1/runner-positions": _persisted_runner_positions(M2K_RUNNER),
    })
    open_realtime(skin_page, skin_server)
    chips = skin_page.evaluate("""
        () => [...document.querySelectorAll('.issue-origin, .event-status, .issue-status')]
          .map(el => {
            const cs = getComputedStyle(el);
            return { cls: el.className, text: el.textContent.trim(),
                     border: cs.borderTopColor, color: cs.color };
          })""")
    assert chips, "không có chip nào trên trang — test này chưa kiểm gì"
    for chip in chips:
        assert chip["text"], f"chip không có chữ, trạng thái chỉ mã hoá bằng màu: {chip}"
        assert chip["border"] != chip["color"], (
            f"chip tô viền cùng màu chữ, thành một khối màu: {chip}")


# ── Luật được viết ra ≠ luật có tác dụng ──────────────────────────────────────
# Shorthand không đọc lại được tin cậy qua `getPropertyValue`, nên quy về longhand.
_LONGHAND = {
    "border": ("border-top-width", "border-top-color"),
    "border-left": ("border-left-width", "border-left-color"),
    "border-bottom": ("border-bottom-width", "border-bottom-color"),
    "background": ("background-color", "background-image"),
    "flex": ("flex-grow", "flex-basis"),
}


def _component_rules() -> list[tuple[str, tuple[str, ...]]]:
    """(danh sách selector, các thuộc tính được khai báo) cho từng luật."""
    text = (DASH / "shared" / "components.css").read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    rules = []
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        props: list[str] = []
        for decl in body.split(";"):
            name = decl.split(":")[0].strip().lower()
            if not name:
                continue
            props.extend(_LONGHAND.get(name, (name,)))
        if props:
            rules.append((selectors.strip(), tuple(dict.fromkeys(props))))
    return rules


_FINGERPRINT = """
([selector, props]) => {
  const pseudo = selector.includes('::') ? '::' + selector.split('::')[1].trim() : null;
  const base = pseudo ? selector.split('::')[0].trim() : selector;
  const els = [...document.querySelectorAll(base)]
    .filter(e => e.getBoundingClientRect().width > 0);
  if (!els.length) return null;
  const cs = getComputedStyle(els[0], pseudo);
  return props.map(p => p + '=' + cs.getPropertyValue(p)).join(' | ');
}
"""


def test_every_rule_in_the_shared_sheet_actually_wins(skin_server, skin_page):
    """Một luật CSS không áp được thì im lặng — trang trông y hệt lúc chưa có nó.

    Ca thật, hai lần trong cùng một lượt dựng. (1) Luật chip trỏ vào
    `.gate-state`, nhưng `paper.css` tô trạng thái qua `.gate-state.pass` —
    specificity cao hơn, luật mới thua sạch. (2) Luật tab viết
    `input:checked + label`, trong khi bốn `<input>` nằm TRƯỚC `.paper-tab-nav`
    chứ không kề nhãn nào. Cả hai lần trang vẫn dựng, không lỗi console, và một
    ảnh chụp nhìn qua vẫn thấy "đã đổi" — vì các luật KHÁC trong cùng file thì
    áp được.

    Test này bật/tắt chính stylesheet đó và bắt trang phải đổi. Selector nào
    không có phần tử nào trên payload hiện tại thì báo là CHƯA xác minh được,
    chứ không đếm là đạt.
    """
    rules = _component_rules()
    assert len(rules) >= 5, f"chỉ đọc được {len(rules)} luật — bộ phân tích hỏng"

    page = skin_page
    page.goto(f"{skin_server}/paper", wait_until="domcontentloaded")
    page.wait_for_selector(".blocker-card", timeout=90_000)
    page.wait_for_timeout(800)

    toggle = """(off) => {
      const s = [...document.styleSheets].find(x => (x.href||'').includes('components.css'));
      if (!s) return 'KHÔNG-NẠP';
      s.disabled = off; return s.disabled;
    }"""
    assert page.evaluate(toggle, False) != "KHÔNG-NẠP", "/paper không nạp components.css"

    tabs = page.eval_on_selector_all(
        ".paper-tab-nav label", "els => els.map(e => e.textContent.trim())")
    assert tabs, "không thấy tab nào — test sẽ đạt trên một trang rỗng"

    verdict: dict[str, str] = {}
    for index in range(len(tabs)):
        page.eval_on_selector_all(
            ".paper-tab-nav label", "(els, i) => els[i] && els[i].click()", index)
        page.wait_for_timeout(400)
        for selectors, props in rules:
            if verdict.get(selectors) == "áp được":
                continue
            for selector in (s.strip() for s in selectors.split(",")):
                page.evaluate(toggle, True)
                before = page.evaluate(_FINGERPRINT, [selector, list(props)])
                page.evaluate(toggle, False)
                after = page.evaluate(_FINGERPRINT, [selector, list(props)])
                if after is None:
                    verdict.setdefault(selectors, "không có phần tử nào")
                elif before != after:
                    verdict[selectors] = "áp được"
                    break
                else:
                    verdict[selectors] = f"KHÔNG ĐỔI GÌ ({selector}: {after})"

    inert = {k: v for k, v in verdict.items() if v.startswith("KHÔNG ĐỔI")}
    assert not inert, "luật có phần tử để áp mà không đổi được gì:\n" + "\n".join(
        f"  {k}\n    {v}" for k, v in inert.items())

    # Ngưỡng theo TỈ LỆ, không theo con số cứng: một con số cứng sẽ khoá đúng
    # payload của hôm nay. Lúc viết là 32/42 luật chứng minh được; 10 selector
    # còn lại thuộc các panel chỉ dựng khi dữ liệu có, nên không kiểm được ở đây.
    # Nếu tỉ lệ tụt xuống dưới một nửa thì phần lớn tệp đang không được kiểm gì.
    applied = [k for k, v in verdict.items() if v == "áp được"]
    assert len(applied) >= len(rules) // 2, (
        f"chỉ {len(applied)}/{len(rules)} luật chứng minh được là có tác dụng; "
        f"phần còn lại: { {k: v for k, v in verdict.items() if v != 'áp được'} }")


# Luật này bị đè hoàn toàn trên /paper, và đã bị đè y hệt trong chính paper.css:
# mọi `span` trong `section.paper-metrics` đều nằm trong một `.blocker-card`, nơi
# `.blocker-card span` đặt sau và cùng specificity. Ghi ra đây để một luật MỚI
# rơi vào tình trạng đó thì test đỏ, chứ không lẫn vào nền.
_DA_BIET_BI_DE = {".paper-metrics span"}

_WINS_WITH_ITS_OWN_VALUE = """
() => {
  const sheet = [...document.styleSheets].find(s => (s.href||'').includes('components.css'));
  if (!sheet) return null;
  const px = (v, el) => v.endsWith('em')
    ? parseFloat(v) * parseFloat(getComputedStyle(el).fontSize) : parseFloat(v);
  const out = {};
  for (const r of sheet.cssRules) {
    if (!r.selectorText || !/font-(weight|size)/.test(r.cssText)) continue;
    const want = {};
    for (const p of ['font-weight', 'font-size', 'letter-spacing']) {
      const v = r.style.getPropertyValue(p); if (v) want[p] = v.trim();
    }
    if (!Object.keys(want).length) continue;
    for (const sel of r.selectorText.split(',').map(s => s.trim())) {
      const els = [...document.querySelectorAll(sel)]
        .filter(e => e.getBoundingClientRect().width > 0);
      if (!els.length) { out[sel] = out[sel] || 'không có phần tử'; continue; }
      const win = els.some(el => Object.keys(want).every(p => {
        const got = getComputedStyle(el).getPropertyValue(p).trim();
        return p === 'font-weight' ? got === want[p]
             : Math.abs(px(got, el) - px(want[p], el)) < 0.06;
      }));
      if (win) out[sel] = 'thắng';
      else if (out[sel] !== 'thắng') out[sel] = 'bị đè hoàn toàn';
    }
  }
  return out;
}
"""


def test_each_type_rule_reaches_the_value_it_declares(skin_server, skin_page):
    """"Có đổi" chưa đủ — phải đổi ĐÚNG thứ nó khai.

    Ca thật, và là ca người dùng nhìn thấy còn phép đo thì không. Lớp chữ được
    sinh ra gom theo họ: mọi luật chip vào một khối, mọi luật nhãn vào khối sau.
    Việc gom đó ĐẢO trật tự của `paper.css`. `<span>BREACH</span>` khớp cả
    `.blocker-card span` lẫn `.paper-metrics span` — cùng specificity, nên luật
    đứng sau thắng. Gốc xếp `.paper-metrics span` trước; bản gom xếp sau. Kết
    quả: mọi chip nhận cỡ nhãn 11px thay vì 9px.

    Phép kiểm trước đó vẫn xanh, vì luật *có* đổi một thứ gì đó — chỉ là đổi
    sang giá trị của luật khác. Test này đọc giá trị khai trong từng luật rồi
    đòi ít nhất một phần tử tính ra đúng giá trị ấy.
    """
    page = skin_page
    page.goto(f"{skin_server}/paper", wait_until="domcontentloaded")
    page.wait_for_selector(".blocker-card", timeout=90_000)
    page.wait_for_timeout(800)

    tabs = page.eval_on_selector_all(
        ".paper-tab-nav label", "els => els.map(e => e.textContent.trim())")
    assert tabs, "không thấy tab nào — test sẽ đạt trên một trang rỗng"

    merged: dict[str, str] = {}
    for index in range(len(tabs)):
        page.eval_on_selector_all(
            ".paper-tab-nav label", "(els, i) => els[i] && els[i].click()", index)
        page.wait_for_timeout(400)
        result = page.evaluate(_WINS_WITH_ITS_OWN_VALUE)
        assert result is not None, "/paper không nạp components.css"
        # Chỉ được NÂNG hạng, không được hạ. Bản đầu ghi đè thẳng, và một tab
        # sau đó — nơi selector không có phần tử nào — đã xoá mất phán quyết
        # "bị đè hoàn toàn" của tab trước: tiêm đúng lỗi cascade vào mà test
        # vẫn xanh.
        hang = {"không có phần tử": 0, "bị đè hoàn toàn": 1, "thắng": 2}
        for selector, state in result.items():
            if hang[state] > hang.get(merged.get(selector, "không có phần tử"), 0):
                merged[selector] = state

    won = [s for s, v in merged.items() if v == "thắng"]
    assert len(won) >= 20, f"chỉ {len(won)} selector đạt đúng giá trị: {merged}"

    overridden = {s for s, v in merged.items() if v == "bị đè hoàn toàn"}
    assert overridden <= _DA_BIET_BI_DE, (
        "luật bị đè hoàn toàn — kiểm lại trật tự so với paper.css: "
        f"{sorted(overridden - _DA_BIET_BI_DE)}")
