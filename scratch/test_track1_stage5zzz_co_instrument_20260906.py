"""Stage 5ZZZ-CO. Hai biểu đồ xếp chồng phải vẽ CÙNG một công cụ.

Lỗi này không làm gãy gì cả — đó là điều khiến nó sống lâu. Hai pane vẫn vẽ đẹp, trục thời
gian vẫn dóng, con trỏ chữ thập vẫn chạy; chỉ có điều một pane là S&P và pane kia là Russell.
Đo trên trang 2026-09-04 trước bản sửa:

    nến   MES   ~7.724        (bảng cấu hình của panel gán roska4_swing -> MES)
    đường M2K   ~2.979        (khối ghi CUỐI trong ngày, không ai chọn nó)

Hai lựa chọn độc lập, không chỗ nào đối chiếu. Nguyên nhân ở tầng đọc: `recorded_series`
gộp theo `slot_id`, nên với một rổ bốn công cụ, bốn khối của cùng một slot chồng lên nhau và
chỉ khối cuối sống sót. Đúng họ lỗi mà `recorded_by_instrument` đã được viết ra để chữa cho
Calm ở Stage 5ZZZ-BJ — nó chỉ chưa được chữa ở đây.

Bảng cấu hình gán mỗi sleeve MỘT công cụ, và với hai trong bốn sleeve điều đó sai:

    global_nkd     MNKD                      1    bảng đúng
    roska4_stress  (không ghi diagnostics)   0    bảng là thứ duy nhất còn lại
    roska4_calm    MES · MNQ                 2
    roska4_swing   MES · MNQ · MYM · M2K     4    bảng chỉ nói MES
"""
from __future__ import annotations

import pytest

from global_index import track1_strategy_diagnostics as sd
from monitor.backend import track1_market_view as mv

DAY = "2026-09-04"


# ── tầng đọc ───────────────────────────────────────────────────────────────────────────
def test_mot_ro_nhieu_cong_cu_khong_bi_gop_thanh_mot_chuoi():
    """Cổng gốc. Không có nó, ba phần tư việc sleeve làm biến mất mà không ai biết."""
    ins = sd.instruments_recorded(".", DAY, "roska4_swing")
    assert len(ins) >= 2, f"phép đo hỏng hoặc bằng chứng đã đổi: {ins}"

    dai = {i: len(sd.recorded_series(".", DAY, "roska4_swing", i)) for i in ins}
    assert all(n > 0 for n in dai.values()), dai
    # Mỗi công cụ giữ nguyên số slot của nó thay vì chia nhau một chuỗi.
    assert len(set(dai.values())) == 1, f"các công cụ ra số slot khác nhau: {dai}"

    gop = len(sd.recorded_series(".", DAY, "roska4_swing"))
    assert gop == max(dai.values()), (
        f"bản gộp trả {gop} slot trong khi mỗi công cụ có {dai} — nó đang trộn, không lọc")


def test_hai_cong_cu_khac_nhau_cho_ra_hai_chuoi_khac_nhau():
    """Chống một bản sửa chỉ THÊM tham số mà không dùng tới nó."""
    ins = sd.instruments_recorded(".", DAY, "roska4_swing")
    if len(ins) < 2:
        pytest.skip("ngày này chỉ ghi một công cụ")
    a = sd.recorded_series(".", DAY, "roska4_swing", ins[0])
    b = sd.recorded_series(".", DAY, "roska4_swing", ins[1])
    assert [r.get("values") for r in a] != [r.get("values") for r in b], (
        "hai công cụ trả về cùng số liệu — bộ lọc không có tác dụng")


# ── panel ──────────────────────────────────────────────────────────────────────────────
def _sleeve(inst=None, sleeve="roska4_swing"):
    p = mv.build(".", day=DAY, instrument=inst)
    return (p.get("sleeves") or {}).get(sleeve) or {}


def test_hai_pane_cua_cung_mot_the_ve_cung_mot_cong_cu():
    """Điều người đọc thật sự dựa vào. So bằng THANG GIÁ, vì đó là thứ mắt so.

    Không ghim một mã công cụ: ghim rằng hai pane không thể ở hai thang khác nhau. Một
    bản sửa khiến chúng cùng sai vẫn phải đỏ ở cổng trên.
    """
    s = _sleeve()
    bars = [b.get("close") for b in (s.get("bars") or []) if b.get("close") is not None]
    ser = [p.get("close") for p in ((s.get("strategy") or {}).get("slot_series") or [])
           if p.get("close") is not None]
    assert bars and ser, f"không đủ dữ liệu để so: {len(bars)} nến, {len(ser)} điểm"
    lech = abs(bars[-1] - ser[-1]) / max(abs(bars[-1]), 1e-9)
    assert lech < 0.02, (
        f"nến kết ở {bars[-1]}, đường kết ở {ser[-1]} — lệch {lech:.0%}. Hai pane đang vẽ "
        "hai công cụ khác nhau dưới một con trỏ chữ thập.")


def test_chon_mot_cong_cu_khac_thi_CA_HAI_pane_theo():
    """Nửa dễ quên. Nếu chip chỉ đổi nến thì ta chuyển sự lệch chứ không sửa nó."""
    s = _sleeve()
    ins = s.get("instruments") or []
    if len(ins) < 2:
        pytest.skip("sleeve này chỉ đọc một công cụ hôm nay")
    khac = next(i for i in ins if i != s.get("instrument"))
    t = _sleeve(khac)
    assert t.get("instrument") == khac
    b0 = [b.get("close") for b in (s.get("bars") or []) if b.get("close") is not None]
    b1 = [b.get("close") for b in (t.get("bars") or []) if b.get("close") is not None]
    s1 = [p.get("close") for p in ((t.get("strategy") or {}).get("slot_series") or [])
          if p.get("close") is not None]
    assert b0 and b1 and s1
    assert abs(b1[-1] - b0[-1]) / max(abs(b0[-1]), 1e-9) > 0.02, "nến không đổi theo lựa chọn"
    assert abs(b1[-1] - s1[-1]) / max(abs(b1[-1]), 1e-9) < 0.02, (
        f"đổi công cụ xong nến ở {b1[-1]} còn đường ở {s1[-1]} — chỉ một pane nghe lời")


def test_sleeve_khong_ghi_bang_chung_thi_NOI_RA_chu_khong_im():
    """Stress không ghi diagnostics per-slot nào. Một danh sách rỗng phải đọc thành "không
    có gì để đọc", không thành "sleeve này chỉ chạy một công cụ"."""
    s = _sleeve(sleeve="roska4_stress")
    assert s.get("instruments") == [], s.get("instruments")
    assert s.get("instrument_source") == "declared", s.get("instrument_source")
    assert s.get("instrument") == s.get("declared_instrument")


def test_mot_ma_khong_co_that_khong_lam_panel_gay():
    """Endpoint này nuôi một trang phải tiếp tục vẽ được; một lựa chọn sai lùi về mặc định."""
    s = _sleeve("KHONGCO")
    assert s.get("instrument") in (s.get("instruments") or [s.get("declared_instrument")])
    assert s.get("instrument_source") in ("recorded", "declared")


# ── ba trạng thái ở mặt hiển thị ───────────────────────────────────────────────────────
def _instbar(payload_sleeve: dict) -> str:
    """Chạy ĐÚNG hàm dựng hàng chip của trang, trên một payload dựng sẵn.

    Đọc mã bằng regex không chứng minh được nhánh nào chạy; nạp hàm và gọi nó thì có. Ba
    trạng thái này khác nhau ở đúng một chỗ — `s.instruments` vắng mặt, rỗng, hay có — và
    một phép kiểm đọc chuỗi sẽ xanh cho cả ba.
    """
    import json
    import os
    import subprocess
    import tempfile
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "global_index" / "dash" / "realtime"
          / "realtime.js").read_text(encoding="utf-8")
    a = js.index("function mvInstBar(s) {")
    b = js.index("function mvPriceHead(s) {", a)
    body = js[a:b]
    nl = chr(10)
    src = ("const mvEsc = x => String(x);" + nl + body + nl
           + "process.stdout.write(mvInstBar(" + json.dumps(payload_sleeve) + "));" + nl)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(src)
        path = f.name
    try:
        out = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        return out.stdout
    finally:
        os.unlink(path)


def test_truong_VANG_MAT_khong_duoc_doc_thanh_khong_co_bang_chung():
    """Bẫy đã có sẵn trong tệp này ở Stage 5ZZH và tôi vẫn mắc lại: một backend chưa khởi
    động lại không gửi trường ấy, và bản đầu đọc thành "phiên này không ghi gì" — một câu
    sai, nói chắc nịch, về một sleeve đã ghi bốn công cụ."""
    html = _instbar({"instrument": "MES"})
    assert "has not been restarted" in html, html
    assert "recorded no per-slot evidence" not in html, html


def test_truong_RONG_thi_moi_la_khong_co_bang_chung():
    html = _instbar({"instrument": "MNQ", "instruments": [], "instrument_source": "declared"})
    assert "recorded no per-slot evidence" in html, html
    assert "has not been restarted" not in html, html


def test_co_danh_sach_thi_dung_chip():
    html = _instbar({"instrument": "MES",
                     "instruments": ["MES", "MNQ", "MYM", "M2K"],
                     "instrument_source": "recorded"})
    assert html.count("data-mvinst=") == 4, html
    assert "4 read today" in html, html
    assert "has not been restarted" not in html and "no per-slot evidence" not in html
