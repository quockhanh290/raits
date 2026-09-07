"""Lịch chạy hỏi CME, không hỏi sàn chứng khoán Mỹ. TỆP MỚI.

Bảng lịch trên trang hỏi `is_trading_day`, và docstring của hàm đó viết thẳng: "True nếu NYSE
mở". Tuyến này không giao dịch cổ phiếu Mỹ — các sleeve là hợp đồng tương lai chỉ số trên CME,
và một trong số đó là Nikkei, thứ chẳng liên quan gì tới ngày lễ Mỹ.

Hai lịch trùng nhau vào ngày thường và tách nhau đúng vào ngày lễ Mỹ — tức đúng lúc trang phải
nói đúng. Đối chiếu với số thanh dữ liệu NKD đã lưu:

    Labor Day 2023 / 2024 / 2025    CME mở,  NYSE đóng,  672 / 860 / 596 thanh
    Thanksgiving 2025               CME mở,  NYSE đóng,  431 thanh
    Good Friday 2024 / 2025         cả hai đóng,           0 thanh

Ngày 2026-09-07 là Labor Day. Bộ lập lịch nổ 92 job vì cron của nó chỉ biết "thứ Hai đến thứ
Sáu"; bảng lịch báo 0 slot. Nên trang chỉ ra job kế tiếp trễ nguyên một ngày, và không có dòng
nào cho những thứ thật sự đã chạy.

Vì sao KHÔNG dùng luật "cứ ngày trong tuần là chạy": Good Friday là ngày trong tuần và CME
đóng thật. Luật ấy sẽ bịa ra nguyên một ngày slot trễ hạn. Bản sửa đầu tiên của tôi đúng là
luật ấy, và một phép kiểm có sẵn bắt được ngay — nó ghim Good Friday, và nó ghim đúng.
"""
from __future__ import annotations

import datetime as dt
import logging
import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from raits.live.trading_calendar import is_futures_session, is_trading_day  # noqa: E402

#: (ngày, CME mở?, NYSE mở?) — cột CME đối chiếu được với số thanh NKD đã lưu.
CASES = [
    ("2023-09-04", True,  False),   # Labor Day, 672 thanh
    ("2024-09-02", True,  False),   # Labor Day, 860 thanh
    ("2025-09-01", True,  False),   # Labor Day, 596 thanh
    ("2025-11-27", True,  False),   # Thanksgiving, 431 thanh
    ("2024-03-29", False, False),   # Good Friday, 0 thanh
    ("2025-04-18", False, False),   # Good Friday, 0 thanh
    ("2026-09-08", True,  True),    # thứ Ba thường — hai lịch phải đồng ý
    ("2026-09-05", False, False),   # thứ Bảy
]


@pytest.mark.parametrize("day, cme, _nyse", CASES)
def test_the_futures_calendar_matches_the_exchange_that_trades(day, cme, _nyse):
    assert is_futures_session(dt.date.fromisoformat(day)) is cme, day


def test_the_two_calendars_disagree_on_exactly_the_holidays_futures_trade():
    """Nếu phép kiểm này thành rỗng thì cả tệp không kiểm gì — hai lịch giống hệt nhau
    thì việc thay lịch chẳng sửa được gì."""
    differ = [d for d, cme, nyse in CASES if cme != nyse]
    assert differ, "hai lịch không khác nhau ở đâu cả — bản sửa vô nghĩa"
    for d in differ:
        day = dt.date.fromisoformat(d)
        assert is_futures_session(day) is True
        assert is_trading_day(day) is False, f"{d}: NYSE lẽ ra phải đóng"


def test_the_equity_calendar_is_left_alone():
    """`is_trading_day` vẫn phải trả lời về NYSE. Nó là câu hỏi ĐÚNG cho dữ liệu SPY —
    SPY không có giá vào ngày lễ Mỹ, và cổng độ tươi cần biết điều đó. Đổi nghĩa nó là
    mang lỗi cũ sang một cái tên mới."""
    assert is_trading_day(dt.date(2025, 9, 1)) is False       # Labor Day
    assert is_trading_day(dt.date(2026, 9, 8)) is True        # thứ Ba thường


# ── bảng lịch trên trang ─────────────────────────────────────────────────────

def _mirror(day: dt.date, track1_only: bool = True) -> int:
    logging.disable(logging.CRITICAL)
    try:
        import monitor.backend.schedule_status as ss

        tok = ss._MODE_OVERRIDE.set(track1_only)
        try:
            return len(ss._scheduled_slots_for(day))
        finally:
            ss._MODE_OVERRIDE.reset(tok)
    finally:
        logging.disable(logging.NOTSET)


def test_a_us_holiday_that_cme_trades_gets_its_slots_mirrored():
    n = _mirror(dt.date(2026, 9, 7))            # Labor Day
    assert n > 50, f"{n} slot cho Labor Day — trang lại đang im lặng về một ngày có chạy"


def test_a_day_cme_is_shut_mirrors_nothing():
    assert _mirror(dt.date(2026, 4, 3)) == 0    # Good Friday
    assert _mirror(dt.date(2026, 9, 5)) == 0    # thứ Bảy


def test_the_holiday_and_the_ordinary_day_mirror_the_same_slots():
    """Ngày lễ mà CME mở là một phiên đầy đủ với bộ lập lịch — cron không phân biệt."""
    assert _mirror(dt.date(2026, 9, 7)) == _mirror(dt.date(2026, 9, 8))


def test_the_mirror_and_the_scheduler_still_agree_in_every_mode():
    from global_index import track1_slots as ts

    logging.disable(logging.CRITICAL)
    try:
        for kw in ({}, {"track1_shadow": True},
                   {"track1_shadow": True, "track1_only": True}):
            r = ts.parity_report(**kw)
            assert r["in_parity"], (kw, r.get("only_in_dashboard_mirror"),
                                    r.get("only_in_scheduler"))
    finally:
        logging.disable(logging.NOTSET)


def test_an_unknown_session_reads_as_a_day_the_scheduler_runs():
    """Không có thư viện lịch thì câu trả lời trung thực là câu của chính bộ lập lịch:
    cron không tra lịch nào cả, nó nổ vào mọi ngày trong tuần. Đọc "không có phiên" ở đây
    là quay lại đúng lỗi vừa sửa — trang im lặng về những job đã chạy."""
    import monitor.backend.schedule_status as ss

    orig = ss.is_futures_session
    try:
        ss.is_futures_session = lambda d: None
        assert ss.scheduler_registers_on(dt.date(2026, 9, 7)) is True   # thứ Hai
        assert ss.scheduler_registers_on(dt.date(2026, 9, 5)) is False  # thứ Bảy
    finally:
        ss.is_futures_session = orig
