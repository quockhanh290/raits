"""Stage 5ZZZ-CL. Ô mẫu chú giải giữ chiều cao 9px — và cổng này tồn tại để nó ĐỪNG bị
"sửa" về 10×4 lần thứ ba.

Hợp đồng thiết kế ghi 10×4 kèm lý do: *"swatch legend là chữ nhật 10x4, mô phỏng hình CELL
trong lane — không phải dot slot"*. Đọc một mình câu ấy thì bản sửa về 4px trông hiển nhiên
đúng, và nó đã được viết ra HAI lần:

    vòng rà trước   viết 10×4, rồi tự rút lại
    2026-09-05      tôi đề xuất 10×4 sau khi đo tỉ lệ, và đề xuất ấy SAI

Cả hai lần đều đọc luật bị đè cùng tài liệu, và bỏ qua chú thích của luật đè lên. Chú thích
ấy ghi một phép đo và một quyết định của chủ dự án ngày 2026-09-05: ở chiều cao 4px, ô "Not
yet run" (viền 1px NÉT ĐỨT #2a323d) và ô "Not reached" (viền 1px NÉT LIỀN #3a424f) trở thành
hai hộp gần như giống hệt — hai sắc xám sát nhau, phân biệt bằng một nét đứt dài 10px, tức
vài chấm. Sáu trạng thái mà hai cái không phân biệt được thì chú giải không làm được việc
của nó.

Cổng này KHÔNG ghim con số 9. Nó ghim ĐIỀU KIỆN đã dẫn tới con số ấy: sáu ô mẫu phải phân
biệt được với nhau bằng pixel. Ai tìm được cách vẽ 10×4 mà sáu ô vẫn khác nhau thì cổng cho
qua — đó mới là thứ hợp đồng thật sự đòi.
"""
from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("playwright.sync_api")

from monitor.test_realtime_dom import (  # noqa: F401,E402
    browser_page, realtime_server,
)


def _open(page, server):
    page.set_viewport_size({"width": 1900, "height": 1000})
    page.goto(f"{server}/realtime", wait_until="domcontentloaded")
    page.wait_for_selector("#statusRail .system-conclusion", timeout=25_000)
    page.wait_for_timeout(15000)
    # ĐÓNG BĂNG trang trước khi chụp. Dashboard tự vẽ lại theo nhịp poll, và bản đầu chụp
    # hai lượt cách nhau vài trăm ms nên ô mẫu bị gỡ khỏi DOM giữa chừng — lỗi báo ra là
    # "Element is not attached", trông như lỗi của trang chứ không phải của phép đo.
    page.evaluate("() => { for (let i = 1; i < 9999; i++) clearInterval(i); }")
    # Dừng đồng hồ chưa đủ: một lượt fetch còn dở vẫn về SAU đó và vẽ lại chú giải. Chặn
    # hẳn mạng rồi để nhịp cuối cùng lắng xuống. Không có bước này, cổng xanh khi chạy
    # riêng và đỏ trong lượt đầy đủ — đúng dạng lỗi mà SCRATCHPAD đã ghi một lần: đỏ nhảy
    # chỗ giữa các lượt là dấu hiệu của cuộc đua, không phải của máy chậm.
    page.route("**/api/**", lambda route: route.abort())
    page.wait_for_timeout(1500)


def _swatches(page):
    return page.query_selector_all(".mv2-legend .mv2-cell")


def _pixels(page, els=None):
    """Ảnh thật của từng ô mẫu, băm lại. So bằng pixel chứ không so bằng khai báo CSS:
    hai ô có thể khai khác nhau mà vẽ ra giống hệt, và ngược lại.

    Truy lại phần tử ngay trước mỗi lượt chụp và thử lại nếu chúng bị thay giữa chừng —
    handle cũ trở thành rác ngay khi trang vẽ lại một lần.
    """
    last = None
    for _ in range(4):
        try:
            return [hashlib.sha256(el.screenshot()).hexdigest()
                    for el in _swatches(page)]
        except Exception as exc:                       # noqa: BLE001
            last = exc
            page.wait_for_timeout(700)
    raise AssertionError(f"chú giải không đứng yên đủ lâu để chụp: {last}")


def test_sau_o_mau_chu_giai_phan_biet_duoc_voi_nhau(realtime_server, browser_page):
    """Điều kiện thật mà hợp đồng đòi. Con số 9px chỉ là cách hiện tại thoả nó."""
    _open(browser_page, realtime_server)
    els = _swatches(browser_page)
    assert len(els) >= 4, f"chỉ thấy {len(els)} ô mẫu — phép đo hỏng, không phải chú giải sạch"

    seen = _pixels(browser_page)
    dupes = {h for h in seen if seen.count(h) > 1}
    assert not dupes, (
        f"{len(dupes)} nhóm ô mẫu vẽ ra giống hệt nhau trong {len(seen)} ô — "
        "chú giải không phân biệt được trạng thái nó đang giải thích")


PAIR = ("Not yet run", "Not reached")


def _pair(page):
    """Hai ô mẫu được nêu đích danh trong lời biện minh cho 9px."""
    out = {}
    for item in page.query_selector_all(".mv2-legend .mv2-legend-item"):
        txt = (item.inner_text() or "").strip().lower()
        for name in PAIR:
            if name.lower() in txt:
                cell = item.query_selector(".mv2-cell")
                if cell:
                    out[name] = cell
    return out


def _dien_tich_lech(a_png, b_png) -> int:
    """Số subpixel lệch trên ngưỡng nhìn thấy. TUYỆT ĐỐI, không phải tỉ lệ.

    Bản đầu dùng TỈ LỆ và suýt cho ra kết luận ngược: ở 4px tỉ lệ lệch là 48,1%, ở 9px chỉ
    38,8% — trông như ô nhỏ dễ phân biệt hơn. Đó là ảo giác của mẫu số: ô ngắn lại thì viền
    chiếm gần hết diện tích, nên mọi khác biệt Ở VIỀN đều đội tỉ lệ lên. Diện tích lệch
    tuyệt đối mới là lượng tín hiệu mắt nhận được, và nó đi ngược lại: 384 -> 238.
    """
    import io

    from PIL import Image, ImageChops

    a = Image.open(io.BytesIO(a_png)).convert("RGB")
    b = Image.open(io.BytesIO(b_png)).convert("RGB")
    if a.size != b.size:
        b = b.resize(a.size)
    return sum(1 for px in ImageChops.difference(a, b).getdata() if max(px) > 8)


def test_ha_o_mau_xuong_4px_lam_YEU_tin_hieu_phan_biet(realtime_server, browser_page):
    """Ghim CƠ SỞ của quyết định 9px, không ghim con số 9.

    Tiền đề, đo lại được: "Not reached" là hộp rỗng viền LIỀN #3a424f, "Not yet run" là hộp
    rỗng viền ĐỨT #2a323d — hai hộp trong suốt chỉ khác nhau ở kiểu nét và hai sắc xám sát
    nhau. Hạ chiều cao thì phần khác biệt duy nhất ấy teo lại.

    Nếu một ngày chú giải được vẽ khác đi và 4px không còn làm yếu tín hiệu nữa, cổng này
    đỏ — và lúc đó bàn lại 10×4 là hợp lệ. Chừng nào nó còn xanh, 10×4 là bước lùi.
    """
    _open(browser_page, realtime_server)
    cells = _pair(browser_page)
    assert len(cells) == 2, f"không tìm đủ hai ô mẫu: {sorted(cells)}"

    def do(cao):
        browser_page.add_style_tag(content=(
            ".mv2-legend .mv2-legend-item .mv2-cell,"
            ".mv2-legend .mv2-cell { height: %dpx !important; }" % cao))
        browser_page.wait_for_timeout(250)
        c = _pair(browser_page)
        return _dien_tich_lech(c[PAIR[0]].screenshot(), c[PAIR[1]].screenshot())

    cao_9, cao_4 = do(9), do(4)
    assert cao_9 > 0 and cao_4 > 0, (cao_9, cao_4)
    assert cao_4 < cao_9, (
        f"ở 4px diện tích lệch là {cao_4}, ở 9px là {cao_9} — hạ xuống KHÔNG còn làm yếu "
        "tín hiệu, nên lý do giữ 9px đã hết hiệu lực; đọc lại nó trước khi tin")


def test_quyet_dinh_9px_van_con_nguyen_ven_trong_file():
    """Con số không có lý do đi kèm là con số người sau sẽ 'sửa'. Đã xảy ra hai lần."""
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "global_index" / "dash"
           / "realtime-next" / "next.css").read_text(encoding="utf-8")
    i = css.index(".mv2-legend .mv2-legend-item .mv2-cell { height: 9px; }")
    ly_do = css[max(0, i - 1200):i]
    for phai_co in ("2026-09-05", "Not yet run", "Not reached", "nét đứt"):
        assert phai_co in ly_do, f"lý do của 9px mất mảnh {phai_co!r}"
