"""Stage 5ZZZ-CG. Khối Book đọc tuyến đang chạy, và một số không phải nói mình từ đâu ra.

Chạy TRANG THẬT trong chromium với API bị chặn, không grep mã nguồn: cái phải đúng là con
số hiện trên màn hình, không phải dòng lệnh sinh ra nó.

Đo được 2026-09-05 trên máy thật, trước bản sửa. Ảnh chụp cuối cùng của runner đã nghỉ hưu
là 289,8 giờ — 12,1 ngày — tuổi, và bốn con số của khối Book đọc từ nó:

    drawdown_pct 0.0 · drawdown_dollars 0.0 · max_dd_pct 0.0 · hard_dd_pct 0.15
    cluster_exposure {global_nkd 0.0, roska4_stress 0.0, roska4_swing 0.0}

Cả bốn đều là số không. Một số không từ nguồn đã chết đọc giống hệt một ngày yên bình, và
ô Gross còn khoá theo đúng tên ba sleeve của Track 1 nên nó trông như đang báo cáo tuyến
đang chạy. Track 1 giữ sổ riêng, đang sống, và nội dung là `peak_equity 0.0` — nghĩa là mức
sụt KHÔNG XÁC ĐỊNH, không phải bằng không.
"""
from __future__ import annotations

import copy

import pytest

pytest.importorskip("playwright.sync_api")

from monitor.test_realtime_dom import (  # noqa: F401,E402
    BASE_PAYLOADS, _stale_runner_state, browser_page, open_realtime, realtime_server,
    stub_api,
)


def _t1(book=None, error=None) -> dict:
    t1 = copy.deepcopy(BASE_PAYLOADS["/api/v1/track1-runtime"])
    t1["book"] = {"present": False} if book is None else {"present": True, "payload": book}
    if error:
        t1["error"] = error
    return t1


def _book(**over) -> dict:
    base = {"route": "track1_candidate", "cur_day": "2026-09-04", "schema_version": 2,
            "equity": 0.0, "day_start_equity": 0.0, "peak_equity": 0.0, "positions": []}
    base.update(over)
    return base


def _text(page, sel: str) -> str:
    return page.eval_on_selector(sel, "el => el.textContent.trim()")


def _open(page, server, book=None, error=None, legacy_stale=True):
    """Mặc định dựng đúng thế giới của hôm nay: tuyến cũ đã nghỉ.

    Công tắc chuyển nguồn là "tuyến cũ đã nghỉ", không phải "endpoint Track 1 có trả lời".
    Bản đầu của tôi dùng vế sau và làm đỏ ba phép kiểm sẵn có — đúng: khi runner cũ còn
    sống thì Sharpe và mức sụt của nó là của chính nó.
    """
    over = {"/api/v1/track1-runtime": _t1(book, error)}
    if legacy_stale:
        over["/api/v1/runner-state"] = _stale_runner_state()
    stub_api(page, over)
    open_realtime(page, server)


# ── mức sụt ────────────────────────────────────────────────────────────────────────────
def test_dinh_bang_khong_la_khong_xac_dinh_chu_khong_phai_bang_khong(
        realtime_server, browser_page):
    """Trạng thái thật của hôm nay, và là trạng thái mỗi ngày trong chế độ bóng.

    `0.00% of 15.00% hard limit` đọc là "còn xa giới hạn". Sự thật là chưa từng có giao dịch
    nào để có đường cong mà sụt.
    """
    _open(browser_page, realtime_server, _book())
    got = _text(browser_page, "#metricDrawdown")
    assert got == "not traded", got
    assert "0.00%" not in got
    assert "no equity booked" in _text(browser_page, "#metricDrawdownLimit").lower()
    assert "undefined, not zero" in browser_page.eval_on_selector(
        "#metricDrawdown", "el => el.title")


def test_mot_duong_cong_that_duoc_do_bang_so_cua_chinh_tuyen_do(
        realtime_server, browser_page):
    """Cổng này chứng minh bản sửa không phải là "in chữ thay vì in số": khi Track 1 CÓ
    đường cong thì con số hiện ra, và nó là số của Track 1 chứ không phải 0.0 của ảnh chụp
    cũ đang nằm sẵn trong cùng payload."""
    _open(browser_page, realtime_server, _book(peak_equity=100000.0, equity=92000.0))
    assert _text(browser_page, "#metricDrawdown") == "8.00%"
    assert "8,000" in _text(browser_page, "#metricDrawdownAmount")


def test_tran_cua_tuyen_khac_khong_duoc_muon(realtime_server, browser_page):
    """15% là `RISK["max_drawdown_pct"]` mà runner cũ đọc. Track 1 không công bố trần rút
    vốn ở đâu — đã quét `safety`, `gates`, `route`, `checkpoint`. Gán nó cho tuyến này là
    bịa một ràng buộc."""
    _open(browser_page, realtime_server, _book(peak_equity=100000.0, equity=92000.0))
    line = _text(browser_page, "#metricDrawdownLimit")
    assert "15.00%" not in line, line
    assert "hard limit" not in line.lower(), line
    # Ô này là NHÃN, không phải chỗ để một câu: đổ câu vào đây làm nó tràn 231–462px sang
    # thẻ bên cạnh, đo được trên trang thật. Nhãn nói ngắn, lý do đầy đủ ở tooltip.
    assert "no published limit" in line.lower(), line
    tip = browser_page.eval_on_selector("#metricDrawdown", "el => el.title")
    assert "publishes no" in tip and "scale" in tip, tip


def test_track1_im_lang_thi_khong_lui_ve_con_so_cu(realtime_server, browser_page):
    """Đường lui mới là cơ chế đã tạo ra nhầm lẫn ban đầu: nguồn mới im lặng một nhịp và
    màn hình lập tức mặc lại con số 12 ngày tuổi mà không nói gì."""
    _open(browser_page, realtime_server, None, error="track1-runtime request failed")
    got = _text(browser_page, "#metricDrawdown")
    assert got == "unavailable", got
    assert "0.00%" not in _text(browser_page, "#metricDrawdownLimit")
    assert "not substituted" in browser_page.eval_on_selector(
        "#metricDrawdown", "el => el.title")


def test_moi_su_vang_mat_o_o_rui_ro_deu_co_ten(realtime_server, browser_page):
    """`--` cạnh một thanh đo bằng 0 vẫn đọc như "trong hạn". Ô này không bao giờ được để
    trống mà không nói vì sao."""
    for book, err in ((_book(), None), (None, "boom")):
        _open(browser_page, realtime_server, book, err)
        assert _text(browser_page, "#metricDrawdown") not in ("", "--")
        # Nhãn ngắn phải NÓI ĐƯỢC trạng thái; câu đầy đủ nằm ở tooltip của cả hai phần tử.
        label = _text(browser_page, "#metricDrawdownLimit")
        assert 8 < len(label) < 32, f"nhãn dài ngắn bất thường: {label!r}"
        assert "%" not in label, f"nhãn vẫn mượn một tỉ lệ: {label!r}"
        for sel in ("#metricDrawdown", "#metricDrawdownLimit"):
            tip = browser_page.eval_on_selector(sel, "el => el.title")
            assert len(tip.strip()) > 40, (sel, tip)


# ── Gross ──────────────────────────────────────────────────────────────────────────────
def test_gross_duoc_ai_do_viet_tren_trang_realtime(realtime_server, browser_page):
    """Trước bản sửa, người viết duy nhất của ô này nằm trong lớp phủ giao diện của bản
    thiết kế lại — nên trên `/realtime` nó in `--` vĩnh viễn, và không phép kiểm nào nhận
    ra vì `--` là đúng thứ HTML khai sẵn."""
    _open(browser_page, realtime_server, _book())
    assert _text(browser_page, "#metricGrossExposure") == "0.0%"
    assert "own book" in browser_page.eval_on_selector("#metricGrossExposure", "el => el.title")


def test_co_vi_the_ma_chua_co_von_thi_dem_chu_khong_chia(realtime_server, browser_page):
    """Một tỉ lệ chia cho không là một con số bịa. Trạng thái này có thật: sổ ghi vị thế
    trước khi ghi vốn."""
    # Vị thế PHẢI có giá trị danh nghĩa. Bản đầu để chúng rỗng, nên nhánh chia và nhánh đếm
    # cho ra cùng một chuỗi và cổng xanh dù cơ chế bảo vệ bị gỡ — đột biến bắt được.
    _open(browser_page, realtime_server, _book(
        positions=[{"symbol": "MES", "notional": 23000.0},
                   {"symbol": "MNQ", "notional": 41000.0}]))
    got = _text(browser_page, "#metricGrossExposure")
    assert got == "2 held", got
    assert "%" not in got, f"chia cho vốn bằng không: {got}"


def test_gross_khong_lui_ve_anh_chup_cu_khi_track1_im_lang(realtime_server, browser_page):
    _open(browser_page, realtime_server, None, error="boom")
    got = _text(browser_page, "#metricGrossExposure")
    assert got == "n/a", got


# ── các tỉ số ──────────────────────────────────────────────────────────────────────────
def test_ly_do_vang_mat_phai_la_ly_do_cua_tuyen_dang_hien(realtime_server, browser_page):
    """`n=11 trading day(s); needs 20` đếm ngày của runner cũ. Ở chế độ Track 1 nó trả lời
    một câu hỏi không ai hỏi: vấn đề không phải mẫu còn ngắn."""
    _open(browser_page, realtime_server, _book())
    for sel in ("#performanceSharpe", "#performanceCalmar", "#performanceMaxDd"):
        assert _text(browser_page, sel) == "--", sel
        title = browser_page.eval_on_selector(sel, "el => el.title")
        assert "equity curve" in title, (sel, title)
        assert "needs" not in title, (sel, title)


def test_tuyen_cu_con_song_thi_so_cua_no_van_hien(realtime_server, browser_page):
    """Nửa còn lại của công tắc, và là nửa dễ quên.

    Bản sửa này KHÔNG phải "luôn luôn in chữ thay cho số". Khi runner cũ còn tươi, mức sụt
    của nó là mức sụt thật của tuyến đang chạy và phải hiện — kể cả khi Track 1 cũng có mặt.
    Không có phép kiểm này thì một bản sửa quá tay sẽ xanh.
    """
    _open(browser_page, realtime_server, _book(), legacy_stale=False)
    got = _text(browser_page, "#metricDrawdown")
    assert got == "0.00%", got
    assert "15.00%" in _text(browser_page, "#metricDrawdownLimit")


def _gauge(page) -> float:
    return float(page.eval_on_selector(
        "#metricDrawdownFill", "el => parseFloat(el.style.width) || 0"))


def test_thanh_do_khong_duoc_lap_day_theo_tran_cua_tuyen_khac(
        realtime_server, browser_page):
    """Lỗ hổng do đột biến tìm ra: dòng chữ dưới ô được ghi đè nên mọi phép kiểm bằng chữ
    đều mù trước trần 15% bị mượn lại — nhưng con số ấy vẫn chảy vào TỈ LỆ LẤP ĐẦY của
    thanh đo. Một thanh lấp 53% là một câu khẳng định về rủi ro, chỉ là nó không có chữ."""
    _open(browser_page, realtime_server, _book(peak_equity=100000.0, equity=92000.0))
    assert _gauge(browser_page) == 0.0, "thanh đo lấp theo một trần không ai công bố"


def test_thanh_do_van_lam_viec_cho_tuyen_cu_khi_tuyen_do_con_song(
        realtime_server, browser_page):
    """Nửa kia: cổng trên không được nghiệm đúng chỉ vì thanh đo đã chết hẳn."""
    _open(browser_page, realtime_server, _book(), legacy_stale=False)
    stub_api(browser_page, {"/api/v1/runner-state": _drawn_down_runner()})
    browser_page.reload(wait_until="domcontentloaded")
    browser_page.wait_for_selector("#statusRail .system-conclusion", timeout=10_000)
    assert _gauge(browser_page) > 0.0, "thanh đo không còn phản ứng với mức sụt thật"


def _drawn_down_runner() -> dict:
    r = copy.deepcopy(BASE_PAYLOADS["/api/v1/runner-state"])
    snaps = r["payload"].setdefault("snapshots", [])
    snap = copy.deepcopy(snaps[-1]) if snaps else {}
    snap.update({"drawdown_pct": 0.08, "drawdown_dollars": 8000.0})
    r["payload"]["snapshots"] = [snap]
    return r
