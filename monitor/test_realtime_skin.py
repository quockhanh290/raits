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
    _market_view,
    _persisted_runner_positions,
    _runner_positions,
    _stub_mv,
    open_realtime,
    stub_api,
    BASE_PAYLOADS,
)

from playwright.sync_api import sync_playwright  # noqa: E402

DASH = Path(__file__).resolve().parents[1] / "global_index" / "dash"


def _stub_journal(page):
    """Ghim một nhật ký có job, để `.job-row` tồn tại bất kể hôm nay đã chạy gì.

    Đo được 2026-09-05 lúc 00:0x ET: ngày vừa sang, chưa job nào chạy, nên trang in
    "0 jobs / 2026-09-05" và NĂM phép kiểm đợi `.job-row` cùng treo 30 giây rồi đỏ.
    Trang không sai — phép kiểm sai, vì nó neo vào một thứ chỉ có mặt ở một số giờ trong
    ngày. Cùng lớp với mọi lỗi "chỉ hiện ở trạng thái khác" đã bắt được hôm nay, lần này
    do chính tôi gieo.
    """
    journal = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    journal["jobs"] = [{
        "id": f"skin-{i}", "job_id": f"TRACK1_NKD_01{i * 5:02d}",
        "job_type": "track1_strategy_slot", "status": "completed",
        "started_at": f"2026-08-14T18:{i * 5:02d}:00Z",
        "ended_at": f"2026-08-14T18:{i * 5:02d}:05Z", "duration_seconds": 5,
        "reason": None, "diagnostics": [], "events": [],
    } for i in range(3)]
    stub_api(page, {"/api/v1/job-journal/": journal})


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


# ── Chỉ so phần chữ NGƯỜI ĐỌC THẤY ĐƯỢC ───────────────────────────────────────
# `Range.getClientRects()` trả hình học cho cả phần đã bị cắt và không bao giờ
# được vẽ. Bỏ qua bước này thì mọi thẻ tóm tắt dùng `-webkit-line-clamp` bị báo là
# chữ đè chữ, và mọi dòng cuộn khỏi mép một khung `overflow:auto` cũng vậy.
#
# Bản đầu hỏi "hình này có nằm HOÀN TOÀN ngoài khung cắt không" và bỏ qua nếu có.
# Nó bỏ sót đúng cái ca ở giữa: một nhãn bị cắt MỘT NỬA vẫn giữ nguyên hình học và
# đè lên nhãn bên cạnh bằng phần mực không ai vẽ ra. Đo trên dải chạy regime ở
# 390px: 3 cặp bị báo, đúng 3 nhãn bị cắt, và số cặp có HỘP đè nhau là 0.
#
# Nên bây giờ GIAO hình với mọi khung cắt rồi so bằng phần giao. Một luật bao trùm
# cả hai ca: nằm hoàn toàn ngoài thì phần giao rỗng. Cắt theo TỪNG TRỤC, vì
# overflow-y không cắt chiều ngang — chỗ mà bản đầu gộp hai trục lại.
_VISIBLE_RECT = """
  (el, rect) => {
    let top = rect.top, bottom = rect.bottom, left = rect.left, right = rect.right;
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      const clipX = cs.overflowX !== 'visible';
      const clipY = cs.overflowY !== 'visible';
      if (!clipX && !clipY) continue;
      const b = p.getBoundingClientRect();
      if (clipY) { top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom); }
      if (clipX) { left = Math.max(left, b.left); right = Math.min(right, b.right); }
    }
    if (right - left < 1 || bottom - top < 1) return null;
    return { top, bottom, left, right, width: right - left, height: bottom - top };
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
  const visibleRect = %s;
  const leaves = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (!n.nodeValue.trim()) continue;
    if (n.parentElement.closest('[hidden]') || notPainted(n.parentElement)) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    for (const rect of r.getClientRects()) {
      if (rect.width < 1 || rect.height < 1) continue;
      const vis = visibleRect(n.parentElement, rect);
      if (!vis) continue;
      leaves.push({ t: n.nodeValue.trim().slice(0, 30), el: n.parentElement, rect: vis });
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
""" % _VISIBLE_RECT


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

    # Phép kiểm này kỳ vọng 0, nên tự nó không phân biệt được "trang sạch" với "bộ dò
    # không còn dò gì". Dựng đúng một ca đè THẬT — hai dòng chữ không nằm trong khung
    # cắt nào — và đòi nó bị bắt, rồi dọn đi.
    proved = skin_page.evaluate("""(js) => {
        const box = document.createElement('div');
        box.id = 'collisionSelfCheck';
        box.style.cssText = 'position:fixed;top:140px;left:140px;z-index:9999';
        box.innerHTML = '<span style="position:absolute;left:0;top:0;font-size:14px">AAAAAAAA</span>'
                      + '<span style="position:absolute;left:9px;top:0;font-size:14px">BBBBBBBB</span>';
        document.body.appendChild(box);
        box.getBoundingClientRect();
        const found = eval('(' + js + ')')().hits.filter(
          h => h.includes('AAAAAAAA') || h.includes('BBBBBBBB'));
        box.remove();
        return found;
      }""", _TEXT_COLLISIONS)
    assert proved, ("bộ dò không bắt được một ca đè chữ dựng sẵn — con số 0 ở trên "
                    "không nói lên điều gì")


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


CALM_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "track1_market_view_20260831.json"


def _calm_phase_columns(page, names):
    """Với mỗi mã: các cột pha nằm trong khoảng ngang của tiêu đề mã đó.

    Đo bằng HÌNH HỌC, không bằng tên class. Bản đầu tìm "một phần tử chứa riêng mã này và
    mang cả hai pha", tức nó ghim bố cục panel-mỗi-mã. Bố cục đổi sang một bảng chung thì
    phần tử ấy không còn tồn tại — nhưng điều test bảo vệ thì vẫn còn nguyên: DECIDE và
    OBSERVE của cùng một mã phải NẰM CẠNH NHAU, để đọc được cái gì đã đổi mà không phải so
    chéo qua hơn một màn hình. Hỏi đúng câu đó thì cả hai bố cục đều trả lời được.
    """
    return page.evaluate(
        """(names) => {
          const root = document.getElementById('calmSection');
          if (!root) return null;
          // Tên mã xuất hiện ở HAI hàng tiêu đề: hàng của bảng chính và hàng của bảng
          // GATES bên dưới. Lấy cả hai thì tiêu đề GATES nằm bên phải sẽ cắt mất cột
          // OBSERVE của mã cuối. Chỉ giữ hàng TRÊN CÙNG.
          let heads = [...root.querySelectorAll('*')].filter(el => {
            const own = [...el.childNodes].filter(n => n.nodeType === 3)
              .map(n => n.textContent).join('').trim();
            return names.includes(own);
          });
          if (heads.length) {
            const top = Math.min(...heads.map(e => e.getBoundingClientRect().top));
            heads = heads.filter(e => e.getBoundingClientRect().top < top + 6);
          }
          const cols = [...root.querySelectorAll('*')].filter(el => {
            const own = [...el.childNodes].filter(n => n.nodeType === 3)
              .map(n => n.textContent).join('').trim().toUpperCase();
            return own === 'DECIDE' || own === 'OBSERVE';
          }).map(el => {
            const r = el.getBoundingClientRect();
            return { txt: el.textContent.trim().toUpperCase(),
                     mid: r.left + r.width / 2, top: r.top };
          });
          const out = {};
          for (const name of names) {
            const h = heads.find(e => {
              const own = [...e.childNodes].filter(n => n.nodeType === 3)
                .map(n => n.textContent).join('').trim();
              return own === name;
            });
            if (!h) { out[name] = null; continue; }
            // Khoảng ngang mà mã này chiếm: từ tiêu đề của nó tới tiêu đề mã kế tiếp.
            const hr = h.getBoundingClientRect();
            const nexts = heads.map(e => e.getBoundingClientRect())
              .filter(r => r.left > hr.left + 1).map(r => r.left);
            const right = nexts.length ? Math.min(...nexts) : Infinity;
            out[name] = cols
              .filter(c => c.mid >= hr.left - 1 && c.mid < right && c.top >= hr.top - 1)
              .map(c => c.txt);
          }
          return out;
        }""",
        names)


def test_calm_shows_both_phases_inside_one_instrument_panel(skin_server, skin_page):
    """Thẻ Calm phải ghép theo MÃ, không phải theo PHA.

    Bản thiết kế đặt DECIDE và OBSERVE cạnh nhau trong cùng một panel cho mỗi mã,
    và tự nói vì sao ngay dưới bảng: "Only the two priced rows change; the rest was
    fixed before the open." Chỉ nhìn thấy được điều đó khi hai cột nằm cạnh nhau.

    Trang đang chia ngược lại — một thẻ cho DECIDE, một thẻ cho OBSERVE, mỗi thẻ
    liệt kê cả hai mã — nên muốn biết giá nào đã đổi thì phải so chéo giữa hai thẻ
    cách nhau hơn một màn hình.

    Payload là bản THẬT của phiên 2026-08-31 lấy nguyên từ endpoint, không dựng tay:
    một payload viết tay sẽ trôi khỏi hình dạng thật và test sẽ canh một thứ không
    tồn tại. Đó cũng là phiên mà bản thiết kế được dựng từ đó.
    """
    payload = json.loads(CALM_FIXTURE.read_text(encoding="utf-8"))
    stub_api(skin_page, {"/api/v1/track1-market-view": payload})
    open_realtime(skin_page, skin_server)
    skin_page.wait_for_selector("#calmSection", timeout=30_000)
    skin_page.wait_for_timeout(900)

    names = ["MES", "MNQ"]
    cols = _calm_phase_columns(skin_page, names)
    assert cols is not None, "không có #calmSection trên trang"
    # Chốt chặn: không tìm được tiêu đề mã nào thì mọi assert dưới đây đạt rỗng.
    assert all(cols.get(n) is not None for n in names), (
        f"không thấy tiêu đề của mã nào trên thẻ Calm: {cols}")
    for n in names:
        assert [c for c in cols[n] if c == "DECIDE"] and [c for c in cols[n] if c == "OBSERVE"], (
            f"{n} không có CẢ HAI pha cạnh nhau; đọc được {cols}")


def test_calm_instrument_panel_states_how_many_gates_it_met(skin_server, skin_page):
    """Mỗi mã phải tự nói đã qua bao nhiêu cổng.

    Bản thiết kế in "4 / 4 gates met" ngay cạnh tên mã, nên người đọc biết cái
    setup này dựa trên bao nhiêu điều kiện mà không phải đếm chấm. Trang hiện vẽ
    các cổng nhưng không có tổng, và cũng không có nhãn GATES để biết cụm đó là gì.

    Tổng phải rút từ payload chứ không viết cứng: nếu số cổng đổi mà dòng này vẫn
    in 4 thì nó thành một lời mô tả đã rời khỏi thứ nó mô tả.
    """
    payload = json.loads(CALM_FIXTURE.read_text(encoding="utf-8"))
    phases = payload["market_view"]["calm"]["phases"]
    gate_count = max(len(p.get("gates") or []) for p in phases.values())
    assert gate_count > 0, "payload không có cổng nào — test này sẽ không kiểm được gì"

    stub_api(skin_page, {"/api/v1/track1-market-view": payload})
    open_realtime(skin_page, skin_server)
    skin_page.wait_for_selector("#calmSection", timeout=30_000)
    skin_page.wait_for_timeout(900)

    text = skin_page.eval_on_selector(
        "#calmSection", "el => el.textContent.replace(/\s+/g, ' ')")
    tallies = re.findall(r"(\d+)\s*/\s*(\d+)\s*gates met", text)
    assert len(tallies) >= 2, f"thiếu tổng cổng cho từng mã; đọc được {tallies}"
    for met, total in tallies:
        assert int(total) == gate_count, (
            f"tổng cổng in ra {total} nhưng payload có {gate_count} — "
            "con số viết cứng sẽ nói sai khi luật đổi")


# ── Chữ trong pane bị kéo giãn ────────────────────────────────────────────────
# Không dựng chuỗi tham chiếu bằng HTML: bản đầu làm thế và sai hai lần liền —
# thiếu `text-transform` thì nhãn viết hoa bằng CSS lệch 18%, và hộp HTML còn dôi
# một nấc letter-spacing cuối chuỗi mà hộp SVG không có. `getComputedTextLength()`
# trả bề rộng chữ theo đơn vị user của chính SVG, không chịu ảnh hưởng của phép
# biến đổi đang sửa lỗi, nên nó so được mà không phải sao chép thuộc tính font nào.
_LABEL_ASPECT = r"""
  () => {
    const svg = document.querySelector('.market-view-section .mv-svg');
    if (!svg) return { labels: 0, skew: 1, skewed: [] };
    const vb = (svg.getAttribute('viewBox') || '').trim().split(/\s+/).map(Number);
    const box = svg.getBoundingClientRect();
    const sx = vb.length === 4 && vb[2] ? box.width / vb[2] : 1;
    const sy = vb.length === 4 && vb[3] ? box.height / vb[3] : 1;
    const out = [...svg.querySelectorAll('text')].map(el => {
      const adv = el.getComputedTextLength();
      // Phóng đều thì chữ vẫn đúng dáng; chỉ phóng LỆCH mới là lỗi. Nên chia bề
      // rộng thật cho bề rộng lẽ ra phải có nếu pane phóng đều theo chiều dọc.
      return { txt: el.textContent.trim(),
               aspect: adv && sy ? box.width && el.getBoundingClientRect().width / (adv * sy) : 1 };
    });
    return { labels: out.length, par: svg.getAttribute('preserveAspectRatio'),
             skew: sy ? sx / sy : 1,
             aspects: out };
  }
"""


def test_no_chart_draws_text_inside_a_stretched_pane(skin_server, skin_page):
    """Luật 5 của hợp đồng, theo đúng tiêu chí nó viết ra.

    Trước: pane giá đặt `preserveAspectRatio="none"` để kéo hình học cho vừa khung, và
    phép kéo ấy không phân biệt hình học với chữ — đo được 2026-09-02, nhãn giá rộng gấp
    1,606 lần bề rộng đúng của nó. Bản vá khi đó là phản-co từng nhãn theo tỉ lệ đo được:
    chữa được triệu chứng, nhưng phải chạy lại mỗi lần khung đổi kích thước, và vẫn để
    nguyên cấu trúc mà luật cấm.

    Hợp đồng cấm CẤU TRÚC, không đặt mức méo cho phép, và nói rõ vì sao: bản design không
    có một thẻ `<text>` nào trong toàn bộ file — trục của nó là HTML bên cạnh — nên không
    chỗ nào méo được. Tiêu chí của luật là một câu: `svg[preserveAspectRatio="none"] text`
    phải rỗng.

    Nhãn giờ là span HTML phủ lên SVG, định vị bằng phần trăm của viewBox. SVG kéo giãn
    lấp đầy khung nên phép quy đổi ấy là ánh xạ chính xác, còn chữ thì nằm ngoài hệ toạ độ
    bị kéo. Phép kiểm này ghim cả hai vế: không còn `<text>`, VÀ nhãn HTML vẫn có mặt —
    thiếu vế sau thì xoá sạch nhãn đi cũng qua được.
    """
    skin_page.set_viewport_size({"width": 1900, "height": 1000})
    skin_page.goto(f"{skin_server}/realtime", wait_until="domcontentloaded")
    skin_page.wait_for_selector('[data-mv-inner="Price context"]', timeout=30_000)
    skin_page.click('[data-mv-inner="Price context"]')
    skin_page.wait_for_selector(".mv-labels .mv-lab", timeout=20_000)
    skin_page.wait_for_timeout(600)

    got = skin_page.evaluate("""() => {
      const svgs = [...document.querySelectorAll('svg[preserveAspectRatio="none"]')];
      const skew = svgs.map(sv => { const vb = (sv.getAttribute('viewBox') || '').split(/\s+/).map(Number);
        const b = sv.getBoundingClientRect();
        return (vb.length === 4 && vb[2] && b.width) ? +((b.width / vb[2]) / (b.height / vb[3])).toFixed(3) : 1; });
      return {panes: svgs.length,
              skew: skew,
              svg_text: document.querySelectorAll('svg[preserveAspectRatio="none"] text').length,
              html_price: document.querySelectorAll('.mv-labels .mv-lab').length,
              html_series: document.querySelectorAll('.mv2-sc-labels .mv2-sc-lab').length};
    }""")
    # Hai chốt chặn. Thứ nhất: phải CÓ pane kéo lệch, nếu không luật này không có việc.
    assert got["panes"] >= 1, f"không có pane nào đặt preserveAspectRatio=none: {got}"
    assert any(abs(k - 1) > 0.05 for k in got["skew"]), (
        f"không pane nào đang thật sự kéo lệch — phép kiểm hết việc, xem lại: {got}")
    # Thứ hai: phải CÓ nhãn, nếu không "0 thẻ text" đạt được bằng cách xoá hết chữ.
    assert got["html_price"] >= 5 and got["html_series"] >= 3, (
        f"nhãn HTML biến mất — 0 thẻ <text> khi đó không chứng minh gì: {got}")

    assert got["svg_text"] == 0, (
        f"còn {got['svg_text']} thẻ <text> trong SVG kéo lệch (tỉ lệ kéo {got['skew']})")
# ── Thẻ regime: lề và cột ─────────────────────────────────────────────────────
_REGIME_CELLS = """() => [...document.querySelectorAll(
    '.rg2-anchor-cell, .rg2-post-cell, .rg2-feat-cell, .rg2-metric')]
  .map(el => ({id: el.id || '', cls: el.className,
               mt: getComputedStyle(el).marginTop,
               h: +el.getBoundingClientRect().height.toFixed(1)}))"""

_FEATURE_LABELS = """() => [...document.querySelectorAll('#regimeFeatures .rg2-feat')]
  .map(row => { const el = row.querySelector('.rg2-feat-label'); if (!el) return null;
    const c = getComputedStyle(el);
    return {txt: el.textContent.trim(),
            h: +el.getBoundingClientRect().height.toFixed(1),
            lh: +parseFloat(c.lineHeight).toFixed(1),
            w: +el.getBoundingClientRect().width.toFixed(1),
            row_h: +row.getBoundingClientRect().height.toFixed(1)}; })
  .filter(Boolean)"""


def test_no_cell_in_the_regime_card_carries_a_margin_its_siblings_do_not(skin_server, skin_page):
    """Một ô của lưới thì không được mang lề riêng.

    `#regimePosterior` và `#regimeFeatures` giữ `margin-top: 10px` từ hồi chúng còn là
    block độc lập dưới `.mv-setup`. Khi chúng thành ô của lưới trong thẻ regime — nơi mọi
    ô anh em đều lề 0 — cái lề cũ đẩy cả hàng rời khỏi đường viền của chính nó và làm mép
    trên dày 23px trong khi mép dưới vẫn 13px.

    Đây là dạng lỗi "luật cũ sống sót qua một lần đổi vai", nên phép kiểm hỏi theo vai:
    ô nào cũng phải có lề như ô bên cạnh, chứ không ghim riêng hai cái id.
    """
    payload = json.loads(CALM_FIXTURE.read_text(encoding="utf-8"))
    stub_api(skin_page, {"/api/v1/track1-market-view": payload})
    open_realtime(skin_page, skin_server)
    skin_page.wait_for_selector("#regimePosterior .regime-post-row", timeout=30_000)
    skin_page.wait_for_timeout(600)

    cells = skin_page.evaluate(_REGIME_CELLS)
    # Chốt chặn: không có ô nào thì mọi assert dưới đây đạt rỗng.
    assert len(cells) >= 4, f"không đọc được ô nào của thẻ regime: {cells}"
    offenders = [c for c in cells if c["mt"] not in ("0px", "")]
    assert offenders == [], (
        "ô của thẻ regime mang lề riêng, đẩy nó khỏi đường viền của chính nó: "
        + ", ".join(f"{c['id'] or c['cls']}={c['mt']}" for c in offenders))


def test_a_feature_label_is_not_starved_by_the_columns_beside_it(skin_server, skin_page):
    """Nhãn feature không được bị bóp tới mức xuống nhiều dòng.

    `.rg2-feat` là `1fr auto auto`, và MỖI hàng là một lưới riêng — nên hàng nào có hai
    cột `auto` rộng thì cột `1fr` của nhãn hẹp lại. Đo trên trang thật: cùng bề ngang
    331,5px, nhãn hàng một được 161,3px và cao một dòng; nhãn hàng hai chỉ được 76,2px
    nên "Realised volatility, 5-day annualised" xuống bốn dòng, cao 67,6px.

    Hậu quả không nằm ở hàng đó: một nhãn bị bóp kéo cả hàng thẻ cao lên, và hộp State
    probabilities bên cạnh bị kéo theo — 13px phía trên nhưng 52,2px trống phía dưới.

    Ngưỡng là hai dòng chứ không phải một: một nhãn dài xuống hai dòng là bình thường,
    bốn dòng là cột đã bị bóp.
    """
    payload = json.loads(CALM_FIXTURE.read_text(encoding="utf-8"))
    stub_api(skin_page, {"/api/v1/track1-market-view": payload})
    open_realtime(skin_page, skin_server)
    skin_page.wait_for_selector("#regimeFeatures .rg2-feat", timeout=30_000)
    skin_page.wait_for_timeout(600)

    labels = skin_page.evaluate(_FEATURE_LABELS)
    # Hai chốt chặn. Thứ nhất: có nhãn để đo. Thứ hai: có ít nhất một nhãn ĐỦ DÀI để
    # một cột bị bóp sẽ làm nó xuống dòng — thiếu chốt này thì một ngày nào đó mọi nhãn
    # rút còn hai chữ, không gì xuống dòng được nữa, và test vẫn xanh mà không kiểm gì.
    assert len(labels) >= 2, f"không đọc được nhãn feature nào: {labels}"
    assert any(len(o["txt"]) >= 25 for o in labels), (
        f"không nhãn nào đủ dài để phép kiểm này còn việc: {[o['txt'] for o in labels]}")

    wrapped = [o for o in labels if o["lh"] > 0 and o["h"] > o["lh"] * 2.05]
    assert wrapped == [], (
        "cột nhãn bị bóp, nhãn xuống quá hai dòng và kéo cao cả hàng thẻ: "
        + ", ".join(f"{o['txt']!r} rộng {o['w']}px cao {o['h']}px "
                    f"(~{o['h'] / o['lh']:.1f} dòng)" for o in wrapped))


def test_the_probability_bars_do_not_touch_their_own_heading(skin_server, skin_page):
    """Dãy bar phải rời khỏi dòng chữ đứng trên nó.

    Đo được 0px: hàng bar đầu tiên bắt đầu đúng ngay mép dưới hộp chữ "STATE
    PROBABILITIES". Hai thứ cộng lại mới ra con số đó — `.mv2-kicker` đặt line-height
    bằng đúng cỡ chữ nên hộp chữ ôm sát glyph, không còn chút đệm nào; và khối chứa bar
    không tự đặt lề trên.

    Ngưỡng không chọn cho vừa mắt: chính thẻ này đã có quy ước cho cùng loại tiêu đề —
    mỗi ô chỉ số đặt 6px giữa kicker và giá trị của nó. Kiểm ở 4px để một bản sửa khác
    cùng ý đồ vẫn qua được.
    """
    payload = json.loads(CALM_FIXTURE.read_text(encoding="utf-8"))
    stub_api(skin_page, {"/api/v1/track1-market-view": payload})
    open_realtime(skin_page, skin_server)
    skin_page.wait_for_selector("#regimePosterior .regime-post-row", timeout=30_000)
    skin_page.wait_for_timeout(600)

    got = skin_page.evaluate("""() => {
      const p = document.getElementById('regimePosterior');
      const k = p && p.querySelector('.mv2-kicker');
      const r = p && p.querySelector('.regime-post-row');
      if (!k || !r) return null;
      return {gap: +(r.getBoundingClientRect().top - k.getBoundingClientRect().bottom).toFixed(1),
              kicker: k.textContent.trim(),
              rows: p.querySelectorAll('.regime-post-row').length};
    }""")
    # Chốt chặn: thiếu tiêu đề hoặc thiếu bar thì không có gì để đo, và một assert về
    # khoảng cách giữa hai thứ không tồn tại sẽ đạt rỗng.
    assert got is not None, "không thấy tiêu đề hoặc hàng bar trong hộp xác suất"
    assert got["rows"] >= 2, f"chỉ có {got['rows']} hàng bar, chưa đủ để đo: {got}"

    assert got["gap"] >= 4, (
        f"dãy bar dính vào tiêu đề {got['kicker']!r}: cách {got['gap']}px")


def test_the_probability_rows_are_not_stacked_on_top_of_each_other(skin_server, skin_page):
    """Các dòng Calm / Normal / Stress / Crisis phải rời nhau ra.

    Đo được: khe 3px giữa hai hàng cao 15,6px — 19% một dòng chữ, nên bốn hàng đọc thành
    một khối liền. 6px là đơn vị đã có sẵn trong CHÍNH thẻ này: cùng khoảng cách giữa
    kicker và giá trị ở mỗi ô chỉ số, và giữa kicker với dãy bar ngay trên nó. Kiểm ở 5px
    để một bản sửa khác cùng ý đồ vẫn qua được.
    """
    payload = json.loads(CALM_FIXTURE.read_text(encoding="utf-8"))
    stub_api(skin_page, {"/api/v1/track1-market-view": payload})
    open_realtime(skin_page, skin_server)
    skin_page.wait_for_selector("#regimePosterior .regime-post-row", timeout=30_000)
    skin_page.wait_for_timeout(600)

    got = skin_page.evaluate("""() => {
      const rows = [...document.querySelectorAll('#regimePosterior .regime-post-row')];
      const gaps = [];
      for (let i = 1; i < rows.length; i++)
        gaps.push(+(rows[i].getBoundingClientRect().top
                    - rows[i - 1].getBoundingClientRect().bottom).toFixed(1));
      return {n: rows.length, gaps,
              h: rows.length ? +rows[0].getBoundingClientRect().height.toFixed(1) : null};
    }""")
    # Chốt chặn: dưới ba hàng thì không có đủ khe để phép kiểm này nói được điều gì.
    assert got["n"] >= 3, f"chỉ có {got['n']} hàng xác suất: {got}"
    assert got["gaps"], f"không đo được khe nào: {got}"

    tight = [g for g in got["gaps"] if g < 5]
    assert tight == [], (
        f"các dòng xác suất dính nhau: khe {got['gaps']} trên hàng cao {got['h']}px")


def test_an_open_job_reads_as_one_card_not_a_card_inside_a_card(skin_server, skin_page):
    """Khối chi tiết là PHẦN CỦA hàng, không phải một thẻ thứ hai nằm trong nó.

    Đo được ba dấu hiệu cộng lại: khối mang `margin: 0 10px 12px 18px`, một viền TRÁI
    riêng, và một nền khác nền hàng — nên nó trôi lơ lửng bên trong thẻ hàng với đường bao
    của chính mình. Bản thiết kế tả nó bằng đúng một câu: "border-top divider, bg #0b0d11".

    Phép kiểm hỏi theo thứ NGƯỜI ĐỌC thấy, không theo tên thuộc tính: chữ trong khối mở
    phải thẳng hàng với chữ ở phần bấm ngay trên nó, và khối không được có viền dọc riêng.
    """
    _stub_journal(skin_page)
    skin_page.goto(f"{skin_server}/realtime", wait_until="domcontentloaded")
    skin_page.wait_for_selector(".job-row .job-trigger", timeout=30_000)
    skin_page.click(".job-row .job-trigger")
    skin_page.wait_for_selector(".job-detail", timeout=15_000)
    skin_page.wait_for_timeout(400)

    got = skin_page.evaluate("""() => {
      const row = document.querySelector('.job-row.selected') || document.querySelector('.job-row');
      const trig = row.querySelector('.job-trigger');
      const detail = row.querySelector('.job-detail');
      if (!detail) return null;
      const c = getComputedStyle(detail);
      const name = trig.querySelector('.job-name');
      const firstBlock = [...detail.children].find(e => e.getBoundingClientRect().height > 2);
      const inner = firstBlock && (firstBlock.querySelector('b, span, dt') || firstBlock);
      return {
        left_border: parseFloat(c.borderLeftWidth),
        right_border: parseFloat(c.borderRightWidth),
        margin_left: parseFloat(c.marginLeft),
        head_text_x: name ? Math.round(name.getBoundingClientRect().left) : null,
        body_text_x: inner ? Math.round(inner.getBoundingClientRect().left) : null,
      };
    }""")
    # Chốt chặn: không mở được khối thì không có gì để đo.
    assert got is not None, "không mở được khối chi tiết"
    assert got["head_text_x"] is not None and got["body_text_x"] is not None, (
        f"không đọc được mép chữ của một trong hai phần: {got}")

    assert got["left_border"] == 0 and got["right_border"] == 0, (
        f"khối chi tiết vẫn có viền dọc riêng: {got}")
    assert got["margin_left"] == 0, f"khối chi tiết vẫn thụt vào trong hàng: {got}"
    assert abs(got["head_text_x"] - got["body_text_x"]) <= 1, (
        f"chữ trong khối mở không thẳng hàng với chữ ở hàng: {got}")


_NEXT_CSS = DASH / "realtime-next" / "next.css"

_SHEET_PROBE = """([rules]) => {
  const snap = [];
  rules.forEach(([sel, props]) => {
    let els = [];
    try { els = [...document.querySelectorAll(sel)]; } catch (e) { snap.push('ERR'); return; }
    els = els.filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 || r.height > 0; });
    if (!els.length) { snap.push('NONE'); return; }
    snap.push(els.slice(0, 20).map(e => {
      const c = getComputedStyle(e); return props.map(p => c[p]).join('|'); }).join('#'));
  });
  return snap;
}"""

_SHEET_TOGGLE = """([name, off]) => {
  let n = 0;
  for (const s of document.styleSheets) {
    try { if (s.href && s.href.includes(name)) { s.disabled = off; n++; } } catch (e) {}
  }
  return n;
}"""

_LONGHAND_CSS = {
    "padding": ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft"),
    "margin": ("marginTop", "marginRight", "marginBottom", "marginLeft"),
    "border": ("borderTopWidth", "borderTopStyle", "borderTopColor"),
    "gap": ("rowGap", "columnGap"),
    "font": ("fontSize", "fontWeight", "fontFamily"),
    "background": ("backgroundColor",),
    "inset": ("top", "right", "bottom", "left"),
}


def _next_css_rules() -> list[tuple[str, tuple[str, ...]]]:
    text = re.sub(r"/\*.*?\*/", "", _NEXT_CSS.read_text(encoding="utf-8"), flags=re.S)
    out = []
    for selectors, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", text):
        sel = selectors.strip()
        if not sel or sel.startswith("@") or "::" in sel or "%" in sel:
            continue
        props: list[str] = []
        for decl in body.split(";"):
            name = decl.split(":")[0].strip().lower()
            if not name or name.startswith("--"):
                continue
            props.extend(_LONGHAND_CSS.get(
                name, (re.sub(r"-(\w)", lambda m: m.group(1).upper(), name),)))
        if props:
            out.append((sel, tuple(dict.fromkeys(props))))
    return out


def test_no_rule_in_next_css_is_masked_by_the_skin_loaded_after_it(skin_server, skin_page):
    """Không luật nào của `next.css` được phép bị `skin-e.css` che.

    `skin-e.css` nạp SAU `next.css`, nên một luật cùng specificity ở next.css thua sạch
    mà không báo gì: trang trông y hệt lúc chưa có luật đó, không lỗi console, và một
    ảnh chụp nhìn qua vẫn thấy "đã đổi" — vì các luật KHÁC trong cùng file thì áp được.

    Lớp lỗi này xảy ra HAI lần trong một ngày làm việc, và một lần nữa ở dạng họ hàng
    (`.regime-post-nostate` thua `realtime.css`). Rà tay ngày 2026-09-04 đếm được 11
    luật như vậy trong `next.css`; tất cả đã xoá. Phép kiểm này giữ con số đó ở 0.

    Bộ kiểm anh em `test_every_rule_in_the_shared_sheet_actually_wins` làm cùng việc cho
    `shared/components.css`; `next.css` trước nay chưa ai quét.

    Cách đo: chụp giá trị tính toán ba lần — cả hai sheet bật, tắt next.css, tắt skin-e.
    Một luật bị che khi tắt next.css KHÔNG đổi gì (nó không đóng góp) mà tắt skin-e THÌ
    đổi (skin-e mới là bên quyết).
    """
    rules = _next_css_rules()
    assert len(rules) >= 50, f"chỉ đọc được {len(rules)} luật — bộ phân tích hỏng"

    _stub_journal(skin_page)
    skin_page.goto(f"{skin_server}/realtime", wait_until="domcontentloaded")
    skin_page.wait_for_selector(".job-row", timeout=30_000)
    skin_page.wait_for_timeout(1200)

    both = skin_page.evaluate(_SHEET_PROBE, [rules])
    assert skin_page.evaluate(_SHEET_TOGGLE, ["/next.css", True]) == 1, "không tắt được next.css"
    skin_page.wait_for_timeout(300)
    no_next = skin_page.evaluate(_SHEET_PROBE, [rules])
    skin_page.evaluate(_SHEET_TOGGLE, ["/next.css", False])
    assert skin_page.evaluate(_SHEET_TOGGLE, ["/skin-e.css", True]) == 1, "không tắt được skin-e"
    skin_page.wait_for_timeout(300)
    no_skin = skin_page.evaluate(_SHEET_PROBE, [rules])
    skin_page.evaluate(_SHEET_TOGGLE, ["/skin-e.css", False])

    # Chốt chặn: phải có luật ĐO ĐƯỢC, nếu không mọi assert dưới đây đạt rỗng — một
    # payload không dựng section nào sẽ cho "NONE" hết và test vẫn xanh.
    measurable = [i for i, v in enumerate(both) if v not in ("NONE", "ERR")]
    assert len(measurable) >= 30, (
        f"chỉ {len(measurable)} luật có phần tử khớp — payload này không đo được gì")

    masked = [rules[i][0] for i in measurable
              if both[i] == no_next[i] and both[i] != no_skin[i]]
    assert masked == [], (
        "luật ở next.css bị skin-e.css che, nên nó không làm gì cả:\n  "
        + "\n  ".join(sorted(set(masked))))


def test_the_right_column_has_one_content_edge(skin_server, skin_page):
    """Cột phải chỉ được có MỘT mép nội dung, và hai tiêu đề của nó cùng một mốc.

    Đo thẳng trên `Realtime Dashboard.dc.html`: mọi thứ trong cột phải bắt đầu ở x=1538 —
    thẻ job, thanh tab, và cả hàng Source Clocks; chỉ chữ tiêu đề lùi thêm 15px vì vạch
    accent 3px cộng gap 12px. Hai tiêu đề "Job journal" và "Source Clocks" nằm CÙNG x.

    Bản đang chạy từng có HAI mép — 23px cho nhật ký, 49px cho Source Clocks — nên hai
    tiêu đề lệch nhau 26px và mắt quét dọc cột thấy răng cưa. `.section-band` mặc định
    `padding: 24px 26px`; `.journal-section` khai `padding: 0` để nhường đệm cho chính
    cột, còn `.source-section` không được khai nên giữ 26px.

    Ngưỡng 2px chứ không phải 0: một thẻ có viền 1px thì chữ trong nó lệch 1px so với
    chữ không nằm trong thẻ, và đó không phải lỗi.
    """
    _stub_journal(skin_page)
    skin_page.goto(f"{skin_server}/realtime", wait_until="domcontentloaded")
    skin_page.wait_for_selector(".job-row", timeout=30_000)
    skin_page.wait_for_timeout(1000)

    got = skin_page.evaluate("""() => {
      const col = document.querySelector('.journal-column');
      if (!col) return null;
      const cr = col.getBoundingClientRect();
      const firstText = el => {
        const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        let n, best = null;
        while ((n = w.nextNode())) {
          if (!(n.nodeValue || '').trim()) continue;
          const rg = document.createRange(); rg.selectNodeContents(n);
          const r = rg.getBoundingClientRect();
          if (r.width < 1) continue;
          if (!best || r.top < best.top - 2 || (Math.abs(r.top - best.top) <= 2 && r.left < best.left))
            best = {top: r.top, left: r.left};
        }
        return best;
      };
      const heads = [...col.querySelectorAll('.section-band .section-heading')]
        .map(h => { const b = firstText(h);
          return b ? {x: Math.round(b.left - cr.left),
                      sec: String(h.closest('.section-band').className).slice(0, 30)} : null; })
        .filter(Boolean);
      const card = col.querySelector('.job-row');
      const rows = col.querySelector('.source-section dl');
      return {heads,
              card_edge: card ? Math.round(card.getBoundingClientRect().left - cr.left) : null,
              rows_edge: rows ? Math.round(rows.getBoundingClientRect().left - cr.left) : null};
    }""")
    # Chốt chặn: thiếu cột, thiếu tiêu đề, hoặc thiếu một trong hai khối thì mọi assert
    # dưới đây đạt rỗng.
    assert got is not None, "không thấy cột nhật ký"
    assert len(got["heads"]) >= 2, f"cột phải chỉ đọc được {len(got['heads'])} tiêu đề: {got}"
    assert got["card_edge"] is not None and got["rows_edge"] is not None, (
        f"thiếu thẻ job hoặc hàng Source Clocks: {got}")

    xs = [h["x"] for h in got["heads"]]
    assert max(xs) - min(xs) <= 2, (
        "hai tiêu đề của cột phải không cùng mốc: "
        + ", ".join(f"{h['sec']}={h['x']}px" for h in got["heads"]))
    assert abs(got["card_edge"] - got["rows_edge"]) <= 2, (
        f"cột phải có hai mép nội dung: thẻ job ở {got['card_edge']}px, "
        f"hàng Source Clocks ở {got['rows_edge']}px")


def test_every_token_with_a_fallback_is_actually_declared(skin_server, skin_page):
    """Một token không tồn tại thì mọi chỗ dùng nó lặng lẽ lấy giá trị dự phòng.

    `var(--x, #abc)` không bao giờ báo lỗi: nếu `--x` chưa khai ở đâu, trang vẫn dựng,
    console vẫn sạch, và màu hiện ra là con số viết cứng trong ngoặc — thường là màu của
    bảng cũ, nằm ngoài thang.

    Lớp lỗi này xảy ra BA lần trong một ngày làm việc:
      `--mv-dim` / `--mv-fg`  → 15 chỗ rơi về hai bậc xám ngoài thang
      `--accent`              → 6 chỗ, trong đó có chấm chế độ Normal, nơi màu LÀ thông điệp
      `--ok` / `--mv-hair`    → một sắc xanh lá thứ tư và một bậc viền thứ sáu

    Cái cuối mãi mới lộ vì chip mang nó chỉ hiện khi phiên CÓ ghi chẩn đoán runtime — một
    lượt rà chỉ thấy trạng thái nó tình cờ gặp. Phép kiểm này không phụ thuộc trạng thái:
    nó đọc token từ FILE và hỏi trình duyệt xem token ấy có giá trị hay không.
    """
    # Quét CẢ BA sheet, không chỉ sheet nền: một token chưa khai trong next.css hay
    # skin-e.css cũng lặng lẽ rơi về giá trị dự phòng đúng như trong realtime.css.
    css = "".join((DASH / rel).read_text(encoding="utf-8") for rel in (
        "realtime/realtime.css", "realtime-next/next.css", "realtime-next/skin-e.css"))
    names = sorted(set(re.findall(r"var\((--[a-z0-9-]+)\s*,", css)))
    # Chốt chặn: không đọc được token nào thì phép kiểm này không kiểm gì.
    assert len(names) >= 8, f"chỉ đọc được {len(names)} token có giá trị dự phòng — bộ đọc hỏng"

    _stub_journal(skin_page)
    skin_page.goto(f"{skin_server}/realtime", wait_until="domcontentloaded")
    skin_page.wait_for_selector(".job-row", timeout=30_000)
    skin_page.wait_for_timeout(600)

    resolved = skin_page.evaluate(
        """(names) => { const c = getComputedStyle(document.documentElement);
             return names.map(n => [n, c.getPropertyValue(n).trim()]); }""", names)
    # Một token đặt INLINE trên từng element (style="--ax:…") cũng là đã khai — nó chỉ
    # không ở `:root`, nên đọc ở documentElement ra rỗng. Bản đầu báo `--ax` và
    # `--calm-cols` là chưa khai; cả hai đều được JS ghi thẳng vào style của element.
    js = "".join((DASH / rel).read_text(encoding="utf-8") for rel in (
        "realtime/realtime.js", "realtime-next/next.js"))
    inline = {m for m in names if (m + ":") in js}
    missing = [n for n, v in resolved if not v and n not in inline]
    assert missing == [], (
        "token được dùng kèm giá trị dự phòng nhưng chưa khai ở đâu, nên mọi chỗ dùng "
        "nó đang lấy con số viết cứng: " + ", ".join(missing))


def test_no_card_is_nested_inside_another_card(skin_server, skin_page):
    """Luật 3 của hợp đồng: chia bằng vạch trong, không lồng thẻ.

    Tiêu chí chữ nghĩa của luật — "border-radius ≥ 6px và background khác trong suốt, nằm
    trong một element cũng thoả hai điều đó" — bắt nhầm HEADER của thẻ. Đo trên trang:
    `#modelInputsZone` có `margin: 0`, bán kính `8px 8px 0 0` (chỉ hai góc trên), nền
    `inset #0b0d11` và một vạch hairline phía dưới. Đó đúng là thứ bảng token quy định
    ("inset — header/footer trong card"), không phải thẻ lồng thẻ.

    Spec đã tự nhận điểm mù này cho luật 1/4/6 và viết lại chúng "có phạm vi, có cách
    đếm, có ngoại lệ ghi thẳng"; luật 3 chưa được viết lại. Đây là tiêu chí phân biệt, đo
    được: một thẻ LỒNG thì trôi bên trong thẻ cha — có lề — và bo CẢ BỐN góc. Một header
    thì lề bằng 0 và chỉ bo hai góc nó chia chung với cha.
    """
    _stub_journal(skin_page)
    skin_page.goto(f"{skin_server}/realtime", wait_until="domcontentloaded")
    skin_page.wait_for_selector(".job-row", timeout=30_000)
    skin_page.wait_for_timeout(1200)

    got = skin_page.evaluate("""() => {
      const vis = e => { const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1; };
      const CHIPY = /chip|badge|pill|tab|btn|button|dot|key|swatch/i;
      const corners = c => ['borderTopLeftRadius','borderTopRightRadius',
                            'borderBottomRightRadius','borderBottomLeftRadius']
                            .map(k => parseFloat(c[k]) || 0);
      const surface = e => {
        const r = e.getBoundingClientRect(), c = getComputedStyle(e);
        if (r.width * r.height < 600 || CHIPY.test(String(e.className))) return null;
        if (c.backgroundColor === 'rgba(0, 0, 0, 0)' || c.backgroundColor === 'transparent') return null;
        const rad = corners(c);
        const margin = ['marginTop','marginRight','marginBottom','marginLeft']
          .map(k => parseFloat(c[k]) || 0);
        return {el: e, allFour: rad.every(v => v >= 6), floats: margin.some(v => v > 0),
                cls: String(e.className).slice(0, 34), rad: rad.join('/'), mar: c.margin};
      };
      const all = [...document.querySelectorAll('body *')].filter(vis).map(surface).filter(Boolean);
      const cardish = all.filter(o => o.allFour);
      const nested = cardish.filter(o => o.floats &&
        cardish.some(p => p !== o && p.el.contains(o.el)));
      return {surfaces: all.length, cards: cardish.length,
              nested: nested.map(o => `${o.cls} (rad ${o.rad}, margin ${o.mar})`)};
    }""")
    # Chốt chặn: không có bề mặt nào để xét thì phép kiểm đạt rỗng.
    assert got["cards"] >= 5, f"chỉ thấy {got['cards']} thẻ — không đủ để kiểm: {got}"
    assert got["nested"] == [], (
        "thẻ lồng trong thẻ — hợp đồng nói chia bằng vạch trong:\n  "
        + "\n  ".join(got["nested"]))


def test_the_figure_size_is_used_only_when_there_is_a_figure(skin_server, skin_page):
    """Bậc chữ lớn của ô equity chỉ dùng khi ô ấy giữ một CON SỐ.

    Thang chữ của hợp đồng dành bậc 30px cho "số paper equity". Khi tuyến chưa đo được, ô
    ấy giữ một lời từ chối có tên — "not measured", "baseline UNKNOWN", hoặc "--" — và lời
    từ chối đó ĐÚNG: không để trống, không mượn số của tuyến khác. Nhưng nó không phải một
    con số, và đo được 2026-09-04 nó là CHỮ TO NHẤT TOÀN TRANG (30px), trong khi câu trả
    lời "hệ thống có khoẻ không" là 15px và "ORDERS POSSIBLE: no" là 11px.

    Bản đầu của phép kiểm này hỏi "chữ to nhất trang có phải con số không" và KHÔNG tin
    được: máy chủ của bộ test không nối broker nên ô equity đọc "--" chứ không phải
    "not measured", và thứ to nhất đổi theo dữ liệu từng lần chạy. Một phép kiểm mà chủ thể
    của nó đổi theo dữ liệu thì không giữ được bất biến nào — nó đã cho một đột biến đi qua.

    Bản này hỏi một câu tất định về CHÍNH ô đó: có chữ số thì mới được mang bậc chữ lớn.
    """
    # Ép ĐÚNG nhánh cần kiểm. Máy chủ của bộ test có một con số thật ($50,408) nên nhánh
    # "từ chối" không bao giờ chạy, và một đột biến gỡ bản sửa vẫn đi qua được — phép kiểm
    # khi đó chỉ chứng minh rằng một con số thì được phép to.
    runtime = {"route": "track1_candidate",
               "paper_account": {"status": "UNKNOWN", "line": "baseline UNKNOWN"}}
    stub_api(skin_page, {"/api/v1/track1-runtime": runtime})
    skin_page.goto(f"{skin_server}/realtime", wait_until="domcontentloaded")
    skin_page.wait_for_selector("#metricEquity", timeout=30_000)
    skin_page.wait_for_timeout(1200)

    got = skin_page.evaluate("""() => {
      const e = document.getElementById('metricEquity');
      if (!e) return null;
      const c = getComputedStyle(e);
      return {text: (e.textContent || '').trim(),
              size: Math.round(parseFloat(c.fontSize)),
              cls: e.className};
    }""")
    # Chốt chặn: không có ô thì không có gì để kiểm.
    assert got is not None, "không thấy ô paper equity"
    assert got["text"], f"ô paper equity rỗng: {got}"

    has_figure = bool(re.search(r"\d", got["text"]))
    if has_figure:
        assert got["size"] >= 20, (
            f"ô đang giữ một con số nhưng không mang bậc chữ lớn: {got}")
    else:
        assert got["size"] < 20, (
            f"ô đang giữ một lời từ chối, không phải con số, mà vẫn mang bậc chữ dành cho "
            f"một con số: {got['size']}px cho {got['text']!r}")
