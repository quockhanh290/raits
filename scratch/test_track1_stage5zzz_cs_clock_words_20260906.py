"""Stage 5ZZZ-CS. Bảng Source Clocks không được in mã máy.

Đo trên trang trước bản sửa:

    Schedule freshness    not_expected_yet · whether another slot is due today, …
    Schedule evidence     not_scheduled / none

`not_expected_yet` là từ của người viết bộ lập lịch. `not_scheduled / none` còn tệ hơn: hai
mã ghép bằng dấu gạch chéo, trông như một tỉ số, và nửa sau (`none`) là chỗ giữ chỗ chứ
không mang tin gì.

Bản ghi giữ nguyên mã của nó — mã là thứ máy đọc và là thứ đối soát về sau. Chỉ câu người
đọc thấy là đổi.

CỔNG QUAN TRỌNG NHẤT Ở ĐÂY không phải là "hôm nay không có mã trên màn hình" — hôm nay chỉ
có hai mã trong sáu, và một phép kiểm nhìn màn hình sẽ xanh cho bốn mã chưa từng xuất hiện.
Nó đọc DANH SÁCH MÃ TỪ CHÍNH backend và đòi mỗi mã có một câu. Thêm một trạng thái mới ở
`schedule_status.py` mà quên dịch thì đỏ, trước khi nó kịp lên màn hình của ai.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "global_index" / "dash" / "realtime" / "realtime.js").read_text(encoding="utf-8")
BE = (ROOT / "monitor" / "backend" / "schedule_status.py").read_text(encoding="utf-8")


def _map(name: str) -> set:
    """Các khoá của một bảng dịch trong realtime.js."""
    m = re.search(re.escape(name) + r"\s*=\s*\{(.*?)\n  \};", JS, re.S)
    assert m, f"không tìm thấy bảng {name}"
    return set(re.findall(r"^\s*([a-z_]+):", m.group(1), re.M))


def test_moi_gia_tri_freshness_backend_co_the_sinh_ra_deu_co_cau():
    """Đọc tập mã từ NGUỒN sinh ra nó, không gõ tay. Một danh sách gõ tay sẽ đứng yên đúng
    lúc backend thêm trạng thái mới — và đó là lúc cổng cần đỏ nhất."""
    backend = set(re.findall(r'freshness\s*=\s*"([a-z_]+)"', BE))
    assert len(backend) >= 5, f"chỉ trích được {backend} — regex hỏng, không phải backend gọn"
    thieu = sorted(backend - _map("MV_FRESHNESS_WORDS"))
    assert not thieu, f"mã freshness chưa có câu người đọc: {thieu}"


def test_moi_trang_thai_evidence_backend_co_the_sinh_ra_deu_co_cau():
    backend = set(re.findall(r'"state":\s*"([a-z_]+)"', BE))
    assert len(backend) >= 5, f"chỉ trích được {backend} — regex hỏng"
    thieu = sorted(backend - _map("MV_EVIDENCE_WORDS"))
    assert not thieu, f"trạng thái evidence chưa có câu người đọc: {thieu}"


def test_khong_cau_dich_nao_lai_la_mot_ma_may():
    """Chống một bản 'dịch' chỉ chép lại mã. `not_expected_yet: 'not_expected_yet'` sẽ làm
    hai cổng trên xanh mà không sửa gì cả."""
    for name in ("MV_FRESHNESS_WORDS", "MV_EVIDENCE_WORDS"):
        m = re.search(re.escape(name) + r"\s*=\s*\{(.*?)\n  \};", JS, re.S)
        for key, phrase in re.findall(r"^\s*([a-z_]+):\s*'([^']*)'", m.group(1), re.M):
            assert "_" not in phrase, f"{name}.{key} vẫn là mã máy: {phrase!r}"
            assert phrase != key, f"{name}.{key} dịch thành chính nó"
            assert " " in phrase, f"{name}.{key} không phải một câu: {phrase!r}"


def test_ma_la_duoc_in_NGUYEN_chu_khong_bi_nuot():
    """Ba trạng thái, không gộp. Một bộ dịch im lặng nuốt mã nó chưa biết biến một trạng
    thái mới thành ô trống, và ô trống là thứ không ai đi tìm."""
    fn = JS[JS.index("function mvFreshnessWords("):]
    fn = fn[:fn.index("\n  const MV_EVIDENCE_WORDS")]
    assert "|| key" in fn, "mã lạ không được in nguyên: " + fn[:200]


def test_ly_do_rong_khong_bi_ghep_vao_cau():
    """`not_scheduled / none` ra đời vì nửa sau được ghép vô điều kiện. `none` và `unknown`
    là chỗ giữ chỗ; nói chúng ra là thêm chữ mà không thêm tin."""
    m = re.search(r"MV_EVIDENCE_MUTE\s*=\s*\[(.*?)\]", JS, re.S)
    assert m, "không còn danh sách lý do bị làm thinh"
    assert "'none'" in m.group(1) and "'unknown'" in m.group(1), m.group(1)


@pytest.mark.parametrize("cam", ["not_expected_yet", "not_scheduled", " / none"])
def test_ba_chuoi_cu_khong_con_trong_ma_dung(cam):
    """Ghim đúng ba thứ đã hiện trên màn hình, để không ai vô tình dựng lại."""
    start = JS.index("function renderClocks()")
    body = JS[start:start + 4000]
    assert cam not in body, f"{cam!r} quay lại trong renderClocks"
