"""Cửa sổ NKD đêm không được biến mất chỉ vì hôm trước là ngày lễ. TỆP MỚI.

Chuyện đo được
--------------
Slot NKD chạy 01:10–01:55 ET, tức là TRƯỚC job preflight 13:45 của chính ngày đó. Nên chúng
tra bản ghi preflight của "hôm trước". Hàm tìm "hôm trước" chỉ biết tránh cuối tuần.

Ba đêm mỗi năm nó tra trúng một ngày CME đóng hẳn, ngày đó bộ lập lịch không đăng ký gì nên
không có bản ghi nào, và nhánh `flag is None` — fail-closed, đúng hướng — bỏ **toàn bộ** cửa
sổ. Kèm thông báo:

    "SKIPPED — no pre-flight record for <ngày> (scheduler restart or missed 13:45 job)"

Cả hai nguyên nhân nó nêu đều sai. Bộ lập lịch không restart, job 13:45 không lỡ — hôm ấy
đơn giản là không có job nào để lỡ.

    đêm         hôm-trước nó tra      hậu quả
    26/12/2025  25/12 Giáng sinh      bỏ cả cửa sổ
    02/01/2026  01/01 Tết dương       bỏ cả cửa sổ
    06/04/2026  03/04 Good Friday     bỏ cả cửa sổ

Labor Day thì không sao: CME có phiên nên preflight vẫn chạy và vẫn ghi. Chỉ ba ngày CME
đóng hẳn mới cắn.

Luật đúng
---------
Không phải "ngày thường liền trước", mà là **ngày liền trước bộ lập lịch có đăng ký** — vì
đó mới là ngày có thể tồn tại một bản ghi preflight. Câu hỏi ấy đã có người trả lời rồi:
`scheduler_registers_on`, hỏi lịch CME, và đọc "không biết" thành "có" đúng như cron vốn làm.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: (đêm slot NKD chạy, ngày phải tra bản ghi preflight)
NIGHTS = [
    ("2025-12-26", "2025-12-24"),   # bỏ Giáng sinh
    ("2026-01-02", "2025-12-31"),   # bỏ Tết dương
    ("2026-04-06", "2026-04-02"),   # bỏ Good Friday và cuối tuần
    ("2026-09-08", "2026-09-07"),   # Labor Day: CME CÓ phiên, không được bỏ
    ("2026-09-04", "2026-09-03"),   # ngày thường, không đổi gì
    ("2026-09-07", "2026-09-04"),   # thứ Hai: vẫn phải nhảy qua cuối tuần
]


def _fn():
    import global_index.run_scheduler as rs

    return rs._prev_scheduled_day


@pytest.mark.parametrize("night,want", NIGHTS)
def test_it_lands_on_a_day_the_scheduler_registered(night, want):
    got = _fn()(dt.date.fromisoformat(night))
    assert got == dt.date.fromisoformat(want), f"{night}: {got} != {want}"


def test_every_answer_is_a_day_that_could_hold_a_record():
    """Phép kiểm trên ghim ngày cụ thể; phép kiểm này ghim TÍNH CHẤT, nên nó vẫn canh được
    khi lịch đổi và ngày cụ thể không còn đúng."""
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from monitor.backend.schedule_status import scheduler_registers_on
    finally:
        logging.disable(logging.NOTSET)

    fn = _fn()
    d = dt.date(2025, 12, 1)
    checked = 0
    while d < dt.date(2026, 9, 8):
        if scheduler_registers_on(d):
            assert scheduler_registers_on(fn(d)) is True, (d, fn(d))
            checked += 1
        d += dt.timedelta(days=1)
    assert checked > 150, checked


def test_it_never_returns_the_day_itself_or_later():
    fn = _fn()
    for night, _ in NIGHTS:
        d = dt.date.fromisoformat(night)
        assert fn(d) < d


def test_the_walk_is_bounded():
    """Vòng lùi ngày không có trần là vòng chờ lịch hỏng."""
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        import monitor.backend.schedule_status as ss
    finally:
        logging.disable(logging.NOTSET)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "scheduler_registers_on", lambda d: False)
        got = _fn()(dt.date(2026, 9, 8))
    assert (dt.date(2026, 9, 8) - got).days <= 15


def test_a_calendar_that_cannot_answer_degrades_to_the_old_weekday_rule(monkeypatch):
    """Không có lịch thì không tệ hơn hôm nay — và không được tệ hơn.

    "Không biết" ở đây đọc thành "có đăng ký", đúng như cron vốn làm: nó không tra lịch nào
    và bắn vào mọi ngày thường.
    """
    import builtins

    real = builtins.__import__

    def no_status(name, *a, **k):
        if name == "monitor.backend.schedule_status":
            raise ImportError("không có")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_status)
    assert _fn()(dt.date(2025, 12, 26)) == dt.date(2025, 12, 25)   # luật cũ, y nguyên


def test_the_old_closure_is_gone():
    """Hàm cũ nằm trong một closure nên không ai kiểm được nó. Đó là một phần lý do nó sống
    lâu như vậy — kéo nó ra cấp module là điều kiện để có phép kiểm này."""
    src = (REPO / "global_index" / "run_scheduler.py").read_text(encoding="utf-8")
    assert "def _prev_bday(" not in src
    assert "def _prev_scheduled_day(" in src
