"""Stage 5ZZZ-CQ. Nhãn mức giá: không chồng nhau, và không rơi ra ngoài khung.

Hai lỗi, cùng một gốc — thang giá và chỗ đặt chữ được quyết định độc lập với nhau, rồi
không ai đối chiếu. Đo trên trang, sleeve Stress 2026-09-04:

    chồng nhau     "Trigger (pre-session low) · not armed"  y=1163
                   "Session open · not armed"               y=1157
                   cách nhau 6px, mỗi nhãn cao 11px — hai câu in đè, không câu nào đọc được

    rơi ra ngoài   khoảng nến    29.477,75 → 29.692,00
                   Planned stop  29.715,69   cao hơn đỉnh 23,69 điểm
                   đường và nhãn nằm nửa trong nửa ngoài mép trên

Cả hai đều không làm gãy gì. Biểu đồ vẫn vẽ, trục vẫn đúng, chỉ có chữ là không đọc được —
nên chúng sống cho tới khi có người nhìn.

Cổng chạy trên TRANG THẬT: hình học của chữ không suy ra được từ mã.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

from monitor.test_realtime_dom import (  # noqa: F401,E402
    browser_page, realtime_server,
)

# Sleeve nào công bố mức giá thì đo sleeve ấy. Stress là sleeve duy nhất hôm nay tính mức
# trước khi cổng rổ chạy, nên nó là chỗ duy nhất hai lỗi này hiện ra.
SLEEVE = "roska4_stress"

_JS = """
() => {
  const labs = [...document.querySelectorAll('.mv-level-label')].map(e => {
    const r = e.getBoundingClientRect();
    return {t: e.textContent.trim(), top: Math.round(r.top), bottom: Math.round(r.bottom),
            h: Math.round(r.height)};
  });
  const plot = document.querySelector('.mv2-plot') || document.querySelector('.mv2-card');
  const p = plot ? plot.getBoundingClientRect() : null;
  const lines = [...document.querySelectorAll('.mv-level')].map(e => {
    const r = e.getBoundingClientRect();
    return {top: Math.round(r.top)};
  });
  return {labs, lines, plot: p ? {top: Math.round(p.top), bottom: Math.round(p.bottom)} : null};
}
"""


def _open_price_tab(page, server):
    page.set_viewport_size({"width": 1900, "height": 1400})
    page.goto(f"{server}/realtime", wait_until="domcontentloaded")
    page.wait_for_selector("#statusRail .system-conclusion", timeout=25_000)
    page.wait_for_timeout(15000)
    page.click(f'[data-mv-tab="{SLEEVE}"]')
    page.wait_for_timeout(2500)
    tab = page.query_selector("text=Price context")
    if tab:
        tab.click()
    # CHỜ ĐÚNG THỨ CẦN, không ngủ một khoảng cố định. Các mức giá của sleeve này đến từ một
    # lát cắt được tính trong nền: lượt gọi đầu trả về rỗng và panel điền vào ở lượt sau.
    # Một `wait_for_timeout(3000)` xanh hay đỏ tuỳ máy chạy nhanh hay chậm hôm ấy, và một
    # cổng chập chờn dạy người ta bỏ qua nó.
    page.wait_for_selector(".mv-level-label", timeout=45_000)
    page.wait_for_timeout(500)
    return page.evaluate(_JS)


def test_khong_hai_nhan_muc_gia_nao_in_de_len_nhau(realtime_server, browser_page):
    """Nhãn được đặt tại toạ độ giá của chính nó, và bản đầu không có bước hỏi xem chỗ ấy
    đã có ai đứng chưa. Hai mức giá gần nhau thì hai câu chồng lên nhau."""
    r = _open_price_tab(browser_page, realtime_server)
    labs = r["labs"]
    # Cổng duyệt danh sách thì phải chứng minh danh sách không rỗng — và ở đây còn phải
    # chứng minh nó chứa ĐỦ để có thể chồng: một nhãn thì không bao giờ chồng ai.
    assert len(labs) >= 2, f"chỉ thấy {len(labs)} nhãn — phép đo hỏng, không phải trang sạch"

    va_cham = []
    for i, a in enumerate(labs):
        for b in labs[i + 1:]:
            if abs(a["top"] - b["top"]) < max(a["h"], b["h"]):
                va_cham.append((a["t"][:30], b["t"][:30], abs(a["top"] - b["top"])))
    assert not va_cham, "nhãn in đè lên nhau:\n" + "\n".join(
        f"  {x} / {y} — cách nhau {d}px" for x, y, d in va_cham)


def test_moi_muc_gia_duoc_ve_deu_nam_TRON_trong_khung(realtime_server, browser_page):
    """Thang giá tính từ NẾN, rồi các mức được vẽ chồng lên — nên một mức ngoài khoảng nến
    bị cắt ở mép và đọc như lỗi vẽ. Khoảng cách từ giá tới mức dừng lỗ chính là thứ người
    đọc muốn thấy, nên nới thang mới đúng, không phải cắt."""
    r = _open_price_tab(browser_page, realtime_server)
    plot = r["plot"]
    assert plot, "không tìm thấy khung biểu đồ"
    assert r["lines"], "không có đường mức giá nào để kiểm"

    ngoai = [l for l in r["lines"] if l["top"] < plot["top"] or l["top"] > plot["bottom"]]
    assert not ngoai, f"{len(ngoai)} đường mức giá nằm ngoài khung: {ngoai}"

    cat = [a for a in r["labs"]
           if a["top"] < plot["top"] or a["bottom"] > plot["bottom"]]
    assert not cat, "nhãn bị mép khung cắt:\n" + "\n".join(
        f"  {a['t'][:40]} (top {a['top']}, khung {plot['top']}–{plot['bottom']})" for a in cat)


def test_thang_gia_noi_ra_de_chua_muc_giá_chu_khong_bo_muc_di(realtime_server, browser_page):
    """Nửa còn lại của bản sửa. Nếu chỉ LỌC những mức ngoài khoảng thì cổng trên vẫn xanh
    trong khi thông tin đã biến mất — đúng thứ mà 'bản sửa làm bớt hiển thị' phải nói ra."""
    r = _open_price_tab(browser_page, realtime_server)
    assert len(r["lines"]) == len(r["labs"]), (
        f"{len(r['lines'])} đường nhưng {len(r['labs'])} nhãn — một trong hai bị bỏ rơi")
    assert len(r["lines"]) >= 3, (
        f"chỉ còn {len(r['lines'])} mức giá được vẽ; sleeve này công bố ba. Một mức bị lọc "
        "đi thay vì được nới thang để chứa.")
