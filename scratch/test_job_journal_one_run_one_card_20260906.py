"""Một lần chạy là một thẻ, và job dùng chung không phải là job của tuyến cũ. TỆP MỚI.

Hai chuyện, cùng một panel.

MỘT LẦN CHẠY, MỘT THẺ
---------------------
Đo trên nhật ký thật ngày 2026-09-06. Job SPY chiều Chủ nhật chạy ĐÚNG MỘT LẦN, từ 16:00:00
đến 16:00:22, và panel hiện BA thẻ: lần chạy thật 22 giây, cộng hai thẻ 0 giây.

Hai thẻ giả dựng từ hai dòng của chính job đó — câu cảnh báo nói vì sao nó cần chạy, và câu
báo đã phục hồi sau khi xong. Cả hai mang trạng thái *hoàn tất*, nên lý do một job phải chạy,
và tin tốt của nó, mỗi cái hiện ra như một lượt chạy đã xong. Dòng tổng ở đầu panel khi đó
đếm **năm** lượt trong khi có **ba**, và đó là con số người vận hành đọc đầu tiên.

Nhánh sinh ra chúng có lý do đúng: vài job chỉ ghi một dòng rồi thôi, và trước đó chúng không
hiện lên ở đâu — kể cả lượt chạy mọi thứ đều tốt. Nhưng nó quyết định ngay tại dòng đang đọc,
mà một dòng không thể tự biết nhãn của nó có khởi chạy một tiến trình con ở ba dòng sau hay
không.

JOB DÙNG CHUNG KHÔNG PHẢI JOB CỦA TUYẾN CŨ
------------------------------------------
Trang chỉ có hai nhóm và suy nhóm thứ hai bằng loại trừ: không mang tiền tố Track 1 thì là
tuyến cũ. Nên job SPY bị gắn nhãn tuyến cũ — trong khi hai trong số chúng tồn tại **vì** sleeve
Nikkei của Track 1: cửa sổ Nikkei mở tối Chủ nhật, nên dòng SPY của thứ Sáu phải có trên đĩa
trước đó.

Bộ lập lịch đã vạch đúng lằn ranh này và nói ra: chế độ chỉ-Track-1 được mô tả là "Track 1 cộng
hạ tầng dùng chung". Khái niệm đó dừng ở bộ lập lịch. Các phép kiểm dưới đây ghim nó ở chỗ
người ta đọc.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from monitor.backend import job_journal_reader as R      # noqa: E402

#: Đúng hình dạng nhật ký thật của một job có: câu cảnh báo trước, câu lệnh, hoàn tất, rồi
#: câu kết quả. Chép từ scheduler_0906.log, rút gọn, khoá API bỏ đi.
LOG_ONE_RUN = """\
2026-09-06 16:00:00  WARNING  run_scheduler — [SPY_WEEKEND_PRE_NKD_CHECK] the daily series ends on 2026-09-03 and 2026-09-04 is needed before the next overnight window.
2026-09-06 16:00:00  INFO     run_scheduler — [SPY_WEEKEND_PRE_NKD_CHECK] C:\\Python311\\pythonw.exe -m global_index.update_spy_csv --csv spy_daily_live.csv --verify-strict
2026-09-06 16:00:22  INFO     run_scheduler — [SPY_WEEKEND_PRE_NKD_CHECK] completed OK
2026-09-06 16:00:22  WARNING  run_scheduler — [SPY_WEEKEND_PRE_NKD_CHECK] RECOVERED — 2026-09-04 arrived on the weekend.
"""

#: Nhãn chỉ ghi đúng một dòng và không khởi chạy gì. Nhánh một-dòng tồn tại VÌ những nhãn như
#: thế, nên bản sửa phải giữ chúng lại — không thì nó đổi một lỗi lấy một lỗi khác.
LOG_SINGLE_LINE = """\
2026-09-06 12:00:00  CRITICAL run_scheduler — [MAXHOLD_T1] a Track 1 position may be past five days and was not closed.
"""


def _read(tmp_path, text, day="2026-09-06"):
    (tmp_path / "scheduler_0906.log").write_text(text, encoding="utf-8")
    return R._parse([tmp_path / "scheduler_0906.log"], day, [], tmp_path)


def _cards(out, job_id):
    return [j for j in out["jobs"] if j["job_id"] == job_id]


# ── một lần chạy, một thẻ ────────────────────────────────────────────────────

def test_one_execution_produces_one_card(tmp_path):
    cards = _cards(_read(tmp_path, LOG_ONE_RUN), "SPY_WEEKEND_PRE_NKD_CHECK")
    assert len(cards) == 1, (
        f"{len(cards)} thẻ cho một lần chạy; các dòng phụ của job lại thành lượt chạy: "
        + "; ".join(f"{c['duration_seconds']}s {str(c['reason'])[:40]}" for c in cards))


def test_the_card_carries_the_real_duration(tmp_path):
    """Thẻ duy nhất phải là lần chạy thật, không phải một trong hai thẻ 0 giây."""
    card = _cards(_read(tmp_path, LOG_ONE_RUN), "SPY_WEEKEND_PRE_NKD_CHECK")[0]
    assert card["duration_seconds"] == 22, card["duration_seconds"]


def test_no_zero_second_card_is_created_for_a_job_that_launched(tmp_path):
    """Ghim riêng hình dạng của lỗi: 0 giây là dấu vân tay của thẻ giả."""
    cards = _cards(_read(tmp_path, LOG_ONE_RUN), "SPY_WEEKEND_PRE_NKD_CHECK")
    assert [c["duration_seconds"] for c in cards] == [22]


def test_the_two_stray_lines_are_kept_on_the_card_not_dropped(tmp_path):
    """Gộp thẻ lại KHÔNG được làm mất chữ.

    Một bản sửa làm bớt số dòng hiển thị phải trả lời được thứ bị bớt đi đâu. Ở đây: vào
    phần chẩn đoán của chính thẻ mà chúng vốn nói về.
    """
    card = _cards(_read(tmp_path, LOG_ONE_RUN), "SPY_WEEKEND_PRE_NKD_CHECK")[0]
    blob = " | ".join(card["diagnostics"])
    assert "the daily series ends on 2026-09-03" in blob, card["diagnostics"]
    assert "RECOVERED" in blob, card["diagnostics"]


def test_a_label_that_never_launches_still_gets_its_card(tmp_path):
    """Đối chứng, và nó là nửa quan trọng hơn.

    Nhánh một-dòng được thêm vì năm nhãn chưa từng hiện lên thành thẻ — trong đó có cổng
    13:45 quyết định phiên có chạy hay không. Bản sửa thu hẹp nhánh ấy, nên phải chứng minh
    nó chưa đóng hẳn: một nhãn KHÔNG khởi chạy gì vẫn phải có thẻ.
    """
    cards = _cards(_read(tmp_path, LOG_SINGLE_LINE), "MAXHOLD_T1")
    assert len(cards) == 1, "nhãn một-dòng mất thẻ — bản sửa đã đi quá xa"
    assert cards[0]["status"] == "failed", cards[0]["status"]


# ── tuyến: ba nhóm, không phải hai ───────────────────────────────────────────

def test_a_shared_job_is_not_labelled_as_the_retiring_route(tmp_path):
    card = _cards(_read(tmp_path, LOG_ONE_RUN), "SPY_WEEKEND_PRE_NKD_CHECK")[0]
    assert card["route"] == R.ROUTE_SHARED, (
        f"job SPY mang nhãn {card['route']!r}; nó phục vụ cả hai tuyến, và hai trong nhóm "
        f"SPY tồn tại vì cửa sổ Nikkei của Track 1")


@pytest.mark.parametrize("job_type, expected", [
    ("spy_weekend_pre_nkd_check", R.ROUTE_SHARED),
    ("spy_last_chance_pre_nkd", R.ROUTE_SHARED),
    ("spy_refresh_pm", R.ROUTE_SHARED),
    ("preflight", R.ROUTE_SHARED),
    ("session_report", R.ROUTE_SHARED),
    ("track1_safety_stop_repair", R.ROUTE_TRACK1),
    ("track1_window_audit", R.ROUTE_TRACK1),
    # Bị bỏ hẳn ở chế độ chỉ-Track-1 — đo được, không phải phân loại theo cảm tính.
    ("live_day", R.ROUTE_LEGACY),
    ("nkd_night", R.ROUTE_LEGACY),
    # An toàn của tuyến cũ: vẫn chạy, nhưng canh cuốn sổ đang cạn của tuyến cũ.
    ("stop_repair", R.ROUTE_LEGACY),
    ("max_hold", R.ROUTE_LEGACY),
])
def test_every_job_type_lands_in_the_route_that_owns_it(job_type, expected):
    assert R.job_route(job_type) == expected


def test_the_route_split_matches_what_the_scheduler_actually_drops():
    """Ghim vào phép đo, không vào ý kiến.

    Chế độ chỉ-Track-1 bỏ hẳn một danh sách job. Mọi thứ trong danh sách đó là tuyến cũ theo
    định nghĩa, và không thứ nào được gọi là dùng chung. Nếu ai đó thêm một nhãn vào nhóm
    dùng chung mà bộ lập lịch vẫn bỏ nó, phép kiểm này đỏ.
    """
    from global_index import track1_slots as ts

    dropped = set(ts.legacy_retirement_candidates(4002, track1_shadow=True))
    assert dropped, "danh sách rỗng — phép kiểm sẽ pass mà không kiểm gì"
    for job_id in dropped:
        base = job_id.rsplit("_", 1)[0] if job_id[-4:].isdigit() else job_id
        assert R.job_route(base) != R.ROUTE_SHARED, (
            f"{job_id} bị bộ lập lịch bỏ ở chế độ chỉ-Track-1, nên nó không thể là hạ tầng "
            f"dùng chung")
