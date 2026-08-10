"""Đếm phiên đối chiếu sạch để quyết định lúc nào chuyển sang resume.

Đường giao dịch hiện chạy REPLAY ĐẦY ĐỦ mỗi slot (run_day ~5 phút, đủ chậm để lỡ slot).
Resume chỉ replay phần chưa replay — nhanh hơn nhiều — nhưng chỉ được chuyển khi có bằng
chứng nó cho ra CÙNG kết quả. Bằng chứng là dòng `DOI CHIEU KHOP` do slot cuối chạy
`--shadow-verify` sinh ra.

Chỗ dễ tự lừa mình: **một phiên thiếu mã không phải "chưa đủ dữ liệu"**. Ngày 07/08 slot
15:55 chỉ sinh dòng cho MNKD, và nếu chỉ đếm "có dòng KHỚP" thì phiên đó tính là đạt trong
khi bốn mã còn lại chưa ai hỏi tới. Nên luật là **đủ cả 5 mã**, và một mã LỆCH thì cả chuỗi
về 0 chứ không phải trừ một.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.session_report import (RESUME_STREAK_NEEDED, SHADOW_INSTS,
                                         resume_progress, shadow_history)

ALL = set(SHADOW_INSTS)


def _day(khop=(), lech=()):
    return {"khop": set(khop), "lech": set(lech)}


def test_a_full_clean_day_counts():
    streak, rows = resume_progress({"2026-08-07": _day(ALL)}, "2026-08-07", 5)
    assert streak == 1
    assert rows[0][2] == "ĐẠT"


def test_a_day_missing_one_instrument_does_not_count():
    """Hình dạng thật ngày 07/08 ở slot 15:55: chỉ MNKD có dòng. Bốn mã kia không phải
    'khớp ngầm' — chúng chưa được hỏi."""
    streak, rows = resume_progress({"2026-08-07": _day({"MNKD"})}, "2026-08-07", 5)
    assert streak == 0
    assert "thiếu" in rows[0][2]
    for inst in ALL - {"MNKD"}:
        assert inst in rows[0][2]


def test_one_mismatch_resets_the_whole_streak():
    """LỆCH không phải 'trừ một phiên'. Nó nghĩa là resume cho kết quả KHÁC — mọi phiên
    sạch trước đó không còn nói lên điều gì về bản code hiện tại."""
    hist = {f"2026-08-0{i}": _day(ALL) for i in range(1, 5)}
    hist["2026-08-05"] = _day(ALL - {"MES"}, {"MES"})
    streak, _rows = resume_progress(hist, "2026-08-05", 5)
    assert streak == 0


def test_the_streak_counts_only_consecutive_days_up_to_the_report_day():
    hist = {"2026-08-03": _day(ALL), "2026-08-04": _day({"MES"}),
            "2026-08-05": _day(ALL), "2026-08-06": _day(ALL)}
    assert resume_progress(hist, "2026-08-06", 5)[0] == 2
    # ngày sau ngày báo cáo không được tính vào
    assert resume_progress(hist, "2026-08-05", 5)[0] == 1


def test_a_mismatch_is_named_not_just_counted():
    """Người đọc cần biết MÃ NÀO lệch — đó là chỗ bắt đầu điều tra."""
    streak, rows = resume_progress({"2026-08-07": _day(ALL - {"MYM"}, {"MYM"})},
                                   "2026-08-07", 5)
    assert streak == 0 and "MYM" in rows[0][2] and "LỆCH" in rows[0][2]


def test_no_history_is_not_a_pass():
    """Không có phiên nào thì chuỗi phải là 0, không phải 'chưa thấy lỗi nên coi như đạt'."""
    assert resume_progress({}, "2026-08-10", 5) == (0, [])


def test_the_threshold_is_a_visible_constant():
    """Ngưỡng là phán đoán chứ không phải kết quả đo, nên nó phải nằm ở chỗ nhìn thấy và
    đổi được, không chôn trong thân hàm."""
    assert isinstance(RESUME_STREAK_NEEDED, int) and RESUME_STREAK_NEEDED >= 1


def test_history_reads_the_real_log_shape(tmp_path):
    """Đúng định dạng dòng mà run_live_day sinh ra."""
    (tmp_path / "live_day_0807.log").write_text(
        "2026-08-07 02:15:29  INFO     run_live_day - "
        "[shadow] MES: DOI CHIEU KHOP — day du == resume\n"
        "2026-08-07 02:17:05  INFO     run_live_day - "
        "[shadow] MNQ: DOI CHIEU LECH — day du != resume\n",
        encoding="utf-8")
    hist = shadow_history(tmp_path)
    assert hist["2026-08-07"]["khop"] == {"MES"}
    assert hist["2026-08-07"]["lech"] == {"MNQ"}


def test_history_ignores_lines_written_by_tests(tmp_path):
    """Log cũ còn lẫn dòng do pytest sinh ra; đếm nhầm chúng là tự cho mình bằng chứng."""
    (tmp_path / "live_day_0807.log").write_text(
        "2026-08-07 02:15:29  INFO     run_live_day - "
        "[shadow] MES: DOI CHIEU KHOP — day du == resume (injected engine failure)\n",
        encoding="utf-8")
    assert shadow_history(tmp_path) == {}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
