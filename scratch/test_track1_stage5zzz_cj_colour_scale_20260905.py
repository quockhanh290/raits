"""Stage 5ZZZ-CJ. Thang màu của bản thiết kế, đo trên trang đang chạy.

Bản rà `DESIGN_AUDIT_2026-09-04.md` đã đo đúng việc này một lần và đóng nó ở **0 màu ngoài
thang** cho cả hai khổ. Nhưng phép đo ấy chạy TAY, chưa từng thành cổng — và đo lại hôm nay
ra **4 màu** ở khổ rộng. Nó trôi lại, im lặng, trong vòng một ngày. Bốn màu ấy đã được đưa
về thang (khối `CJ` cuối `next.css`) và đo lại ra 0 ở cả bốn tổ hợp trang × khổ; cái còn lại
sau phiên này là CỔNG, thứ mà lần trước không có.

Đó chính là hình dạng lỗi mà bản rà kia mô tả ở trục thứ hai: một luật, một con số, một kết
luận đúng — rồi không có gì giữ nó. Ba phép kiểm khác của bản rà ấy ĐÃ thành cổng
(`test_every_rule_in_the_shared_sheet_actually_wins`,
`test_no_rule_in_next_css_is_masked_by_the_skin_loaded_after_it`,
`test_every_token_with_a_fallback_is_actually_declared`) và cả ba vẫn xanh. Trục màu thì
không ai ghim, và nó là trục duy nhất trôi.

CÁCH ĐO giữ nguyên của bản rà, để hai lần đo so được với nhau: thang hợp lệ **suy từ tài
liệu**, không gõ tay — mọi mã hex xuất hiện trong `DESIGN_SPEC.md`, `SECTION_ANATOMY.md` và
chính file design. Bản rà đếm 50 · 32 · 52 → 57 màu riêng biệt; phép đo này phải ra đúng
những con số ấy, và nó tự kiểm điều đó trước khi kết luận gì.

GIỚI HẠN — thừa hưởng nguyên từ bản rà, và phải đọc trước khi dùng con số này. Cổng chỉ đo
thứ **đang hiện** trên payload hôm nay. Mọi trạng thái phải bấm mới ra — hàng issue được
chọn, `<details>` đang đóng, tab Detector rules, thanh trạng thái ở `watch`/`bad` — đều
không nằm trong lượt đo. Đột biến đã chứng minh điều đó là thật chứ không phải lời cảnh báo
lịch sự: đổi `--panel` sang một màu ngoài thang, cổng vẫn xanh, vì hai chỗ duy nhất dùng nó
là dòng issue đang chọn và nút journal đang bật. "Xanh" ở đây nghĩa là "không thấy màu lạ ở
những chỗ nhìn được", không phải "trang sạch".
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from monitor.test_realtime_dom import (  # noqa: F401,E402
    browser_page, realtime_server,
)

DASH = Path(__file__).resolve().parent.parent / "global_index" / "dash"
DOCS = ("DESIGN_SPEC.md", "SECTION_ANATOMY.md", "Realtime Dashboard.dc.html")

#: Không còn nợ nào. Danh sách này từng có bốn mục và cả bốn đã được đưa về thang trong
#: cùng phiên — xem khối `CJ` ở cuối `next.css`. Giữ lại cái tên rỗng, không xoá: mục đích
#: của nó là chỗ để GHI khi có nợ mới, và một danh sách rỗng nói rõ hơn là không có danh
#: sách. Thêm mục vào đây thì phải kèm chỗ nó sống và lý do chưa sửa.
KNOWN_DEBT: dict[str, str] = {}


_JS = """
() => {
  const hex = c => {
    const m = c.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);
    if (!m) return null;
    if (m[4] !== undefined && parseFloat(m[4]) === 0) return null;   // trong suốt
    return '#' + [1,2,3].map(i => (+m[i]).toString(16).padStart(2,'0')).join('');
  };
  const out = [];
  const seen = new Set();
  const add = (axis, v, el) => {
    if (!v) return;
    const k = axis + v;
    if (seen.has(k)) return;
    seen.add(k);
    out.push({ axis, colour: v,
               where: (el.id ? '#' + el.id
                       : el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0])
                      .slice(0, 40) });
  };
  document.querySelectorAll('body *').forEach(el => {
    if (el.offsetParent === null) return;
    const cs = getComputedStyle(el);
    add('text', hex(cs.color), el);
    add('bg', hex(cs.backgroundColor), el);
    if (parseFloat(cs.borderTopWidth) || parseFloat(cs.borderLeftWidth))
      add('border', hex(cs.borderTopColor), el);
    if (cs.textDecorationLine !== 'none') add('deco', hex(cs.textDecorationColor), el);
  });
  return out;
}
"""


def _palette():
    def expand(h):
        h = h.lower()
        return "#" + "".join(c * 2 for c in h[1:]) if len(h) == 4 else h

    per_doc, allowed = {}, set()
    for name in DOCS:
        text = (DASH / name).read_text(encoding="utf-8", errors="ignore")
        hits = {expand(x) for x in
                re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", text)}
        per_doc[name] = hits
        allowed |= hits
    return allowed, per_doc


def test_thang_mau_van_suy_ra_dung_nhu_ban_ra_da_dem():
    """Tự kiểm phép đo trước khi dùng nó.

    Nếu một tài liệu bị đổi tên, bị cắt, hay bị đọc sai mã hoá thì thang co lại và cổng dưới
    sẽ báo hàng loạt màu "ngoài thang" — một kết quả trông rất giống một phát hiện lớn và
    hoàn toàn sai. Con số của bản rà là 50 · 32 · 52 → 57.
    """
    allowed, per_doc = _palette()
    assert len(per_doc["DESIGN_SPEC.md"]) == 50, len(per_doc["DESIGN_SPEC.md"])
    assert len(per_doc["SECTION_ANATOMY.md"]) == 32, len(per_doc["SECTION_ANATOMY.md"])
    assert len(per_doc["Realtime Dashboard.dc.html"]) == 52
    assert len(allowed) == 57, len(allowed)


@pytest.mark.parametrize("path", ["/realtime", "/realtime-next"])
@pytest.mark.parametrize("width", [1900, 390])
def test_khong_mau_moi_nao_ngoai_thang_ban_thiet_ke(
        realtime_server, browser_page, path, width):
    """Cổng bắt cái MỚI. Nợ cũ đã ghim ở `KNOWN_DEBT` kèm chỗ nó sống.

    Đây là trục duy nhất trong bản rà 2026-09-04 không được ghim thành cổng, và là trục duy
    nhất trôi lại: đóng ở 0, đo lại một ngày sau ra 4.
    """
    allowed, _ = _palette()
    browser_page.set_viewport_size({"width": width, "height": 1000})
    browser_page.goto(f"{realtime_server}{path}", wait_until="domcontentloaded")
    browser_page.wait_for_selector("#statusRail .system-conclusion", timeout=25_000)
    browser_page.wait_for_timeout(6000)

    rows = browser_page.evaluate(_JS)
    # Cổng duyệt danh sách thì phải chứng minh danh sách không rỗng — và ở đây còn phải
    # chứng minh nó thấy được một lượng màu hợp lý, không phải ba cái.
    assert len(rows) >= 20, f"chỉ đo được {len(rows)} cặp trục/màu — phép đo hỏng"

    fresh = [r for r in rows
             if r["colour"] not in allowed and r["colour"] not in KNOWN_DEBT]
    assert not fresh, "màu mới ngoài thang:\n" + "\n".join(
        f"  {r['axis']:7s} {r['colour']}  {r['where']}" for r in fresh)


def test_moi_muc_no_ghim_phai_thuc_su_con_tren_trang(realtime_server, browser_page):
    """Ghim theo HAI chiều, và đây là chiều hay bị quên.

    Một mục nợ đã được sửa mà không ai gỡ khỏi danh sách thì danh sách thành lời mô tả đã
    rời khỏi thứ nó mô tả — và lần sau màu ấy quay lại, cổng sẽ im lặng cho qua. Cổng này
    đã làm đúng việc đó một lần: bốn mục ban đầu được sửa xong thì nó đỏ, buộc phải gỡ.
    """
    if not KNOWN_DEBT:
        pytest.skip("không còn nợ nào để đối chiếu")
    browser_page.set_viewport_size({"width": 1900, "height": 1000})
    browser_page.goto(f"{realtime_server}/realtime", wait_until="domcontentloaded")
    browser_page.wait_for_selector("#statusRail .system-conclusion", timeout=25_000)
    browser_page.wait_for_timeout(6000)
    seen = {r["colour"] for r in browser_page.evaluate(_JS)}
    gone = sorted(c for c in KNOWN_DEBT if c not in seen)
    assert not gone, f"đã sửa rồi thì gỡ khỏi KNOWN_DEBT: {gone}"
