"""Hàng SPY phải tự giải thích ngày của nó. TỆP MỚI.

Vì sao có tệp này
-----------------
Hàng ấy ghi `SPY daily file covers 2026-09-04` và dừng ở đó. Sáng thứ Ba sau Labor Day, ngày
đó đã lùi bốn ngày lịch, và trên màn hình không có gì để phân biệt hai cách đọc:

    thị trường đóng cửa            -> không ai phải làm gì
    job làm mới chưa chạy          -> có người phải dậy đi kiểm

Chỉ một trong hai đáng để gọi người. Cùng một hình dạng lỗi với hàng lời từ chối: con số
đúng, và không có gì trên màn hình nói rằng chợ đã đóng.

Điều nó canh
------------
Phần giải thích phải **suy ra từ lịch**, không viết cứng — nếu không nó sẽ mô tả một luật mà
bản thân yêu cầu không còn đi theo, đúng như những lời mô tả khác đã trôi trong kho này. Và
khi lịch không trả lời được thì hàng phải **im lặng**, chứ không được ngụ ý là chợ đóng.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from monitor.backend import track1_runtime_reader as R      # noqa: E402
from raits.live import trading_calendar as CAL              # noqa: E402

LABOR_DAY = dt.date(2026, 9, 7)
FRIDAY = dt.date(2026, 9, 4)


# ── tên ngày nghỉ ────────────────────────────────────────────────────────────

def test_the_holiday_has_a_name():
    assert CAL.holiday_name(LABOR_DAY) == "Labor Day"


def test_naming_is_not_a_trading_day_check():
    """Không tên KHÔNG có nghĩa là chợ mở. Bản dự phòng viết tay của module này mang ngày mà
    không mang tên, nên nếu thiếu thư viện thì mọi ngày trong năm đều trả None."""
    assert CAL.holiday_name(FRIDAY) is None          # phiên bình thường, cũng None
    assert CAL.is_trading_day(FRIDAY) is True        # câu hỏi "mở hay đóng" hỏi chỗ khác


def test_a_calendar_that_cannot_answer_yields_no_name(monkeypatch):
    monkeypatch.setattr(CAL, "_holiday_names", lambda year: None)
    assert CAL.holiday_name(LABOR_DAY) is None


# ── khoảng trống được suy ra ─────────────────────────────────────────────────

def test_the_gap_is_listed_with_the_holiday_named():
    got = R._closed_since(FRIDAY, LABOR_DAY)
    assert [c["label"] for c in got] == ["Sat", "Sun", "Labor Day"]
    assert [c["date"] for c in got] == ["2026-09-05", "2026-09-06", "2026-09-07"]


def test_the_gap_still_reads_the_day_after_the_holiday():
    """Đây là ngày làm người đọc bối rối nhất: chợ mở lại, mà con số vẫn là thứ Sáu."""
    got = R._closed_since(FRIDAY, dt.date(2026, 9, 8))
    assert [c["date"] for c in got] == ["2026-09-05", "2026-09-06", "2026-09-07"]


def test_an_ordinary_day_has_nothing_to_explain():
    """Thứ Sáu hỏi thứ Năm. Không có khoảng trống, nên hàng phải giữ nguyên như cũ."""
    assert R._closed_since(dt.date(2026, 9, 3), FRIDAY) == []


def test_the_gap_is_derived_from_the_calendar_not_written_down(monkeypatch):
    """Nếu lịch đổi ý về một ngày, câu giải thích phải đổi theo — không thì nó là một lời mô
    tả viết cứng, và những lời như thế đã trôi khỏi thứ chúng mô tả năm lần trong kho này."""
    monkeypatch.setattr(CAL, "is_trading_day", lambda d: True)
    assert R._closed_since(FRIDAY, LABOR_DAY) == []


def test_a_calendar_that_raises_says_nothing_at_all(monkeypatch):
    """"Không trả lời được" không được gộp vào "chợ đóng" — đó chính là cách một chốt chặn
    mở toang. Ở đây hậu quả nhẹ hơn, nhưng hướng an toàn vẫn là im lặng."""
    def boom(d):
        raise RuntimeError("lịch không đọc được")

    monkeypatch.setattr(CAL, "is_trading_day", boom)
    assert R._closed_since(FRIDAY, LABOR_DAY) == []


def test_an_unnamed_weekday_closure_says_no_session_not_its_weekday(monkeypatch):
    """"Monday" là một sự thật ai cũng thấy trên tờ lịch và không giải thích gì cả."""
    monkeypatch.setattr(CAL, "is_trading_day", lambda d: False)
    monkeypatch.setattr(CAL, "holiday_name", lambda d: None)
    got = R._closed_since(FRIDAY, LABOR_DAY)
    assert got[-1]["label"] == "no session", got


def test_the_walk_is_bounded():
    """Một vòng lặp đi lùi theo ngày mà không có trần là một vòng lặp chờ dữ liệu hỏng."""
    assert len(R._closed_since(dt.date(2026, 1, 1), dt.date(2026, 12, 31))) <= 14


# ── câu chữ ──────────────────────────────────────────────────────────────────

def test_the_month_is_named_once_inside_one_month():
    got = R._closed_phrase(R._closed_since(FRIDAY, LABOR_DAY))
    assert got == "Sat 5, Sun 6, Labor Day 7 Sep", got


def test_the_month_is_named_per_day_across_a_boundary():
    """Số ngày trần trụi mất nghĩa khi vắt qua tháng, và khoảng nghỉ Tết dương lịch đúng là
    chỗ người ta sẽ đọc dòng này."""
    got = R._closed_phrase([{"date": "2026-12-31", "label": "no session"},
                            {"date": "2027-01-01", "label": "New Year"}])
    assert got == "no session 31 Dec, New Year 1 Jan", got


def test_the_day_number_is_not_zero_padded():
    assert "Sat 05" not in R._closed_phrase(R._closed_since(FRIDAY, LABOR_DAY))


# ── hàng thật trên bảng ──────────────────────────────────────────────────────

def _row() -> dict:
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        return R.read_track1_runtime(REPO).get("spy_daily") or {}
    finally:
        logging.disable(logging.NOTSET)


def _row_on(day_et: str) -> dict:
    """Hàng đó như nó sẽ hiện vào một ngày CỐ ĐỊNH.

    Đồng hồ bị đóng băng chứ không đọc thật. Bản đầu của tệp này neo vào "hôm nay" và sẽ đỏ
    vào sáng 09/09 khi yêu cầu nhảy sang phiên khác — chỗ đó không đo hàng, nó đo cái lịch.
    """
    import datetime as _d
    import logging
    import warnings
    from zoneinfo import ZoneInfo

    frozen = _d.datetime.fromisoformat(day_et).replace(tzinfo=ZoneInfo("America/New_York"))
    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(R, "_today_et", lambda: frozen)
        try:
            return R.read_track1_runtime(REPO).get("spy_daily") or {}
        finally:
            logging.disable(logging.NOTSET)


def test_the_row_explains_itself_on_labor_day():
    r = _row_on("2026-09-07T20:00")
    assert r["required"] == "2026-09-04", r
    assert "Labor Day" in r["line"] and "Nothing has printed since" in r["line"], r["line"]


def test_the_row_still_explains_itself_the_morning_after():
    """Sáng thứ Ba là lúc dòng này đáng giá nhất: chợ đã mở lại, mà con số vẫn là thứ Sáu."""
    r = _row_on("2026-09-08T09:00")
    assert r["required"] == "2026-09-04", r
    assert "Sat 5, Sun 6, Labor Day 7 Sep" in r["line"], r["line"]


def test_an_ordinary_morning_says_nothing_extra():
    """Thứ Sáu hỏi thứ Năm. Không có gì phải giải thích, nên không được thêm chữ nào."""
    r = _row_on("2026-09-04T09:00")
    assert r["required"] == "2026-09-03", r
    assert r["closed_since"] == [], r
    assert "Nothing has printed since" not in r["line"], r["line"]


def test_the_structured_gap_reconciles_with_the_sentence():
    """Câu chữ và dữ liệu phải nói cùng một điều — hai nơi cùng phát biểu một sự thật là hai
    nơi có thể trôi khỏi nhau."""
    r = _row_on("2026-09-08T09:00")
    assert len(r["closed_since"]) == 3, r
    for c in r["closed_since"]:
        assert c["label"] in r["line"], (c, r["line"])


def test_the_live_row_never_contradicts_its_own_gap():
    """Đúng với MỌI ngày, kể cả ngày mai: có khoảng trống thì phải nói ra, không có thì không
    được nói."""
    r = _row()
    said = "Nothing has printed since" in (r.get("line") or "")
    assert said == bool(r.get("closed_since")), r


def test_the_row_is_not_marked_as_a_problem():
    """Ngày lễ không phải sự cố — cùng luật với dấu hổ phách ở hàng lời từ chối."""
    js = (REPO / "global_index" / "dash" / "realtime" / "realtime.js").read_text(
        encoding="utf-8")
    block = js[js.index("function spyTone()"):]
    block = block[:block.index("\n    }")]
    assert "covers_required_day" in block and "return ''" in block, block
