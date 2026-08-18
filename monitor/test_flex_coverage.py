"""Trần của sao kê Flex phải được nói ra, không phải bị báo như một sự cố.

Đêm 2026-08-17 job FLEX_PULL hỏng vì thiếu biến môi trường. Đặt biến xong, nó vẫn hỏng:
chạy đúng câu lệnh của scheduler lúc 00:05 ET ngày 18 — hơn 6 tiếng sau giờ đóng cửa và
gần 2 tiếng sau khung 22:20 — IBKR trả `code=1004 Statement is incomplete at this time`.
Xin tới hôm trước thì về 35KB bình thường.

Sổ của broker cho phiên đang chạy chưa tồn tại vào lúc đối chiếu chạy. Đó là **trần của
nguồn dữ liệu**, không phải hỏng hóc — và bảng không có chỗ nào ghi lại nó, nên một lệnh
Flex chưa kịp công bố trông y hệt một lệnh Flex không có, rồi bị đếm vào `unresolved` và
chặn go-live vì một câu hỏi chưa tới lượt hỏi.

Ba thứ được ghim ở đây: trần phải đo được, phải phân biệt biết-chắc với chỉ-suy-ra, và
việc phân loại lại phải thực sự tới được con số chặn — chứ không nằm trong một nhánh mà
bộ đếm khác vẫn đi vòng qua.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitor.paper_pnl_compare import _beyond_flex, _flex_coverage, _pnl_verdicts  # noqa: E402


def test_a_requested_range_is_known_exactly_and_a_last_fill_is_only_inferred():
    """Hai nguồn cho cùng một con số, và chúng không đáng tin ngang nhau.

    Khoảng đã xin nằm trong tên tệp: biết chắc bản kê phủ tới đâu, kể cả những ngày
    không có lệnh nào. Khớp lệnh cuối cùng thì chỉ suy ra — không có lệnh sau ngày đó
    KHÔNG chứng minh bản kê phủ tới đó.

    Đo được ngay trên bản kê đang dùng: nó được xin tới 13/8 nhưng khớp lệnh cuối là
    11/8. Tin vào ngày suy ra là hụt mất hai ngày, và hụt về phía nguy hiểm — biến một
    bất đồng thật thành "chưa tới lượt".
    """
    known = _flex_coverage(
        Path("flex_20260818T040413Z_q1603041_ref24_20260810-20260816.csv"),
        [{"date": "2026-08-13"}])
    assert known == {"through": "2026-08-16", "source": "requested_range", "exact": True}

    guessed = _flex_coverage(
        Path("flex_20260813T103831Z_q1603041_ref68.csv"),
        [{"date": "2026-08-11"}, {"date": "2026-08-09"}])
    assert guessed["through"] == "2026-08-11"
    assert guessed["exact"] is False, (
        "ngay suy ra bi danh dau la biet chac — phan loai lai se chay tren mot con so "
        "co the hut, va bien bat dong that thanh cho-Flex")

    assert _flex_coverage(Path("flex_x.csv"), [])["through"] is None


@pytest.mark.parametrize("exit_day, through, beyond", [
    ("2026-08-17", "2026-08-16", True),    # đóng sau tầm phủ
    ("2026-08-16", "2026-08-16", False),   # đóng đúng ngày cuối: đã nằm trong
    ("2026-08-10", "2026-08-16", False),
])
def test_only_events_after_the_boundary_count_as_awaiting(exit_day, through, beyond):
    assert _beyond_flex({"paper": {"exit_day": exit_day}}, through) is beyond


def test_not_knowing_the_boundary_keeps_the_old_answer():
    """Mặc định là báo, không phải im. Không biết trần thì không được suy diễn ra một
    lời bào chữa cho dòng đang thiếu nguồn."""
    assert _beyond_flex({"paper": {"exit_day": "2026-08-17"}}, None) is False


def test_an_entry_inside_the_window_that_closes_outside_it_is_still_awaiting():
    """Ngày để hỏi là ngày ĐÓNG nếu đã đóng. Một lệnh vào trong tầm phủ mà đóng ngoài
    tầm phủ vẫn là lệnh Flex chưa kể xong."""
    row = {"paper": {"entry_day": "2026-08-12", "exit_day": "2026-08-17"}}
    assert _beyond_flex(row, "2026-08-16") is True


def _report(rows, through, exact=True):
    return {
        "statement_pnl_compare": {
            "flex_coverage": {"through": through, "source": "requested_range", "exact": exact},
            "paper_minus_backtest_realized": 0.0,
            "paper_minus_flex_epoch_rebased_realized": 0.0,
        },
        "lifecycle_compare": {"rows": rows, "unresolved": 0,
                              "paper_minus_backtest_sum": 0.0, "paper_minus_flex_sum": 0.0},
        "open_position_parity": {}, "signal_compare": {}, "entry_compare": {}, "daily": [],
    }


_AWAITING = {
    "inst": "M2K", "direction": "LONG", "entry_day": "2026-08-12",
    "classification": "AWAITING_FLEX",
    "paper": {"status": "CLOSED", "exit_day": "2026-08-17"},
    "backtest": {"status": "CLOSED"},
    "flex": {"status": "MISSING"},
}
_REAL_GAP = dict(_AWAITING, classification="TWO_WAY_ONLY")


def test_a_row_awaiting_flex_does_not_block_the_trade_master_verdict():
    """Đây là chỗ bản vá suýt chết.

    `_pnl_verdicts` đếm nguồn thiếu bằng một vòng RIÊNG, đọc thẳng `flex: MISSING` chứ
    không đọc phân loại. Không sửa vòng đó thì dòng vẫn bị đếm, vẫn ra BREACH, và cả
    việc phân loại lại thành vô nghĩa — vá xong mà không nối vào đâu, đúng họ lỗi cả
    đợt rà soát này đi tìm.
    """
    got = _pnl_verdicts(_report([_AWAITING], "2026-08-16"))
    assert got["trade_master"]["status"] != "BREACH", (
        f"mot lenh IBKR chua cong bo van chan bang: {got['trade_master']}")
    assert any("awaiting Flex 1" in f for f in got["trade_master"]["facts"]), (
        "dong bi loai khoi so chan ma khong hien o dau — do la giau, khong phai phan loai")


def test_a_real_missing_source_still_blocks():
    """Nửa còn lại. Nếu mọi nguồn thiếu đều được tha thì luật mới chỉ là tắt cảnh báo."""
    got = _pnl_verdicts(_report([_REAL_GAP], "2026-08-16"))
    assert got["trade_master"]["status"] == "BREACH", (
        f"bat dong that khong con chan: {got['trade_master']}")


def test_the_boundary_is_stated_even_when_nothing_is_awaiting():
    """Một tổng cụt phải tự khai là cụt, kể cả khi không dòng nào bị ảnh hưởng — người
    đọc cần biết trước khi tin, chứ không phải sau."""
    got = _pnl_verdicts(_report([], "2026-08-16"))
    assert any("Flex covers through 2026-08-16" in f for f in got["trade_master"]["facts"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
