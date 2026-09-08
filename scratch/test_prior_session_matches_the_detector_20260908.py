"""Cổng phải chọn ĐÚNG phiên trước mà bộ dò dùng. TỆP MỚI.

Chuyện đã xảy ra
----------------
Sáng 08/09 cả hai slot Calm bị từ chối với `partial_coverage`. Dữ liệu hôm đó lành lặn —
`today_span` và `staleness` đều qua. Chỗ đỏ là `prior_rth`:

    bar cuối trong khoảng là 2026-09-07 12:55, cần tới 2026-09-07 16:00

Cổng chọn "phiên trước" bằng một hàm chỉ biết nhảy qua cuối tuần. Thứ Ba lùi một ngày ra
thứ Hai — Labor Day, CME đóng 13:00. Một lỗi dữ liệu được báo vào đúng ngày dữ liệu lành.

Bản sửa đầu của tôi cũng sai, và vì sao
---------------------------------------
Tôi thay bằng lịch NYSE, rồi thêm "hỏi phiên đó đóng lúc mấy giờ" để nuốt các ngày nửa buổi.
Đo ra thì nó **lệch với chính bộ dò** ở đúng 5 ngày: bộ dò BỎ HẲN phiên nửa buổi và lùi thêm
một phiên nữa, còn luật lịch của tôi nhận phiên nửa buổi ấy. Cổng sẽ đi kiểm dữ liệu của một
ngày mà chiến lược không đọc.

`track1_calm_a.rth_sessions` đã ghi sẵn lý do, và đã thử lịch trước tôi:

    trading_calendar gọi 2019-12-24 và 2023-11-24 là ngày giao dịch, đúng — sàn có mở. Thứ
    bộ dò không dùng được là một phiên không có bar cuối, vì khi đó giá đóng và biên độ của
    nó được đo ở 13:00 và mang nghĩa khác.

Kèm giá phải trả: "với luật lịch, floor mất 5 dòng và thêm 2 dòng mà bản ghi không có."

Nên luật đúng là hỏi CHÍNH DỮ LIỆU: phiên gần nhất có bar cuối. Nó bỏ ngày lễ (không bar
nào) và bỏ nửa phiên (không bar cuối) bằng cùng một câu, và không thể trôi khỏi bộ dò vì cả
hai là một câu.

Điều tệp này canh
-----------------
Hai thứ, và thiếu thứ hai thì thứ nhất thành fail-open:

    1. cổng chọn cùng ngày với bộ dò
    2. bước qua một phiên ĐẦY ĐỦ thì phải TỪ CHỐI — đó là mất dữ liệu, không phải ngày nghỉ
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import global_index.track1_intraday as TI            # noqa: E402

PARQUET = "data/cache/futures/ES_continuous_1m_8y.parquet"


def _frames():
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from global_index.track1_live_source import frozen_frame

        df = frozen_frame("MES", str(REPO / PARQUET))
        bars = df.resample("5min").agg({"open": "first", "high": "max", "low": "min",
                                        "close": "last", "volume": "sum"}).dropna()
        return df, bars
    finally:
        logging.disable(logging.NOTSET)


def _validate(day: str, bars=None, df=None, **kw):
    if bars is None:
        df, bars = _frames()
    return TI.validate("roska4_calm", bars,
                       now_et=pd.Timestamp(f"{day} 10:02", tz="America/New_York"),
                       entry_quote_index=df.index, **kw)


def _prior(day: str, idx):
    return TI._prev_full_session(idx, pd.Timestamp(day), "16:00")


# ── ca đã xảy ra ─────────────────────────────────────────────────────────────

def test_the_day_after_labor_day_is_allowed():
    v = _validate("2026-09-08")
    assert v.allow, [(c.name, c.code, c.detail) for c in v.checks if c.code != TI.OK]


def test_the_day_after_a_half_session_is_allowed():
    """01/12/2025 — hôm trước là thứ Sáu sau Lễ Tạ ơn."""
    v = _validate("2025-12-01")
    assert v.allow, [(c.name, c.code, c.detail) for c in v.checks if c.code != TI.OK]


def test_an_ordinary_day_is_unchanged():
    v = _validate("2026-09-04")
    assert v.allow, [(c.name, c.code, c.detail) for c in v.checks if c.code != TI.OK]


# ── không được trôi khỏi bộ dò ───────────────────────────────────────────────

DAYS = ["2026-09-08", "2025-12-01", "2024-12-02", "2025-07-07", "2026-09-04",
        "2026-01-02", "2026-07-06", "2025-12-26", "2024-09-23", "2025-02-18",
        "2026-05-26", "2026-01-20"]


def test_the_gate_picks_the_same_prior_session_as_the_detector():
    """Đây là phép kiểm quan trọng nhất trong tệp.

    Hai nơi cùng phát biểu "phiên trước là ngày nào" là hai nơi có thể trôi khỏi nhau, và
    lần trôi vừa rồi là bản sửa của chính tôi. Ghim bằng cách bắt chúng khớp trên 12 ngày,
    gồm mọi ngày lễ và mọi nửa phiên trong hai năm gần đây.
    """
    from global_index.track1_calm_a import CalmAParams, rth_sessions

    df, bars = _frames()
    idx = TI._naive(pd.DatetimeIndex(bars.index))
    sess = rth_sessions(df, CalmAParams())
    assert len(sess) > 100, "bảng phiên rỗng thì mọi so sánh dưới đây tự đồng ý với chính nó"

    lech = []
    for d in DAYS:
        gate, _stepped = _prior(d, idx)
        prev = [x for x in sess.index if x < pd.Timestamp(d)]
        if gate.date() != prev[-1].date():
            lech.append((d, str(gate.date()), str(prev[-1].date())))
    assert not lech, lech


def test_a_half_session_is_stepped_over_not_accepted():
    """Bản sửa đầu của tôi nhận nó. Bộ dò thì không, nên cổng cũng không được."""
    df, bars = _frames()
    idx = TI._naive(pd.DatetimeIndex(bars.index))
    gate, stepped = _prior("2025-12-01", idx)
    assert gate.date() == dt.date(2025, 11, 26), gate
    assert dt.date(2025, 11, 28) in [d.date() for d in stepped]


def test_a_holiday_is_stepped_over():
    df, bars = _frames()
    idx = TI._naive(pd.DatetimeIndex(bars.index))
    gate, stepped = _prior("2026-09-08", idx)
    assert gate.date() == dt.date(2026, 9, 4), gate
    assert dt.date(2026, 9, 7) in [d.date() for d in stepped]


# ── và vẫn phải từ chối được ─────────────────────────────────────────────────

def test_stepping_over_a_full_session_refuses():
    """23/09/2024 bước qua 20/09 — một phiên NYSE đầy đủ mà tệp không có bar RTH nào.

    Không có phép kiểm này thì luật "hỏi dữ liệu" trở thành fail-open: một ngày mất dữ liệu
    trông y hệt một ngày nghỉ, và sleeve quyết định trên giá đóng cửa của hai phiên trước mà
    không có gì trên hồ sơ nói ra điều đó.
    """
    v = _validate("2024-09-23")
    assert not v.allow
    detail = " ".join(str(c.detail) for c in v.checks if c.name == "prior_rth")
    assert "2024-09-20" in detail, detail


def test_the_refusal_names_the_date_rather_than_a_code():
    v = _validate("2024-09-23")
    detail = " ".join(str(c.detail) for c in v.checks if c.name == "prior_rth")
    assert "data outage" in detail and "market fact" in detail, detail


def test_without_a_calendar_a_skip_cannot_be_explained_and_refuses(monkeypatch):
    """Không có lịch thì không nói được ngày bị bước qua là ngày nghỉ hay ngày mất dữ liệu.
    Hai thứ đó dẫn tới hai hành động khác nhau, nên gộp chúng là mở toang chốt."""
    import builtins

    real = builtins.__import__

    def no_calendar(name, *a, **k):
        if name == "raits.live.trading_calendar":
            raise ImportError("không có lịch")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_calendar)
    v = _validate("2026-09-08")
    assert not v.allow
    detail = " ".join(str(c.detail) for c in v.checks if c.name == "prior_rth")
    assert "no calendar" in detail, detail


def test_a_day_with_nothing_stepped_over_asks_no_calendar_at_all():
    """Ngày thường không bước qua gì, nên không có gì phải giải thích."""
    df, bars = _frames()
    idx = TI._naive(pd.DatetimeIndex(bars.index))
    _gate, stepped = _prior("2026-09-04", idx)
    assert stepped == []
    assert TI._skip_is_explained([]) is None


# ── đường thoát và biên ──────────────────────────────────────────────────────

def test_an_explicit_prior_day_from_the_caller_still_wins():
    """`prior_session_day` là đường thoát của người gọi; bản sửa không được nuốt nó."""
    v = _validate("2026-09-08", **{"prior_session_day": pd.Timestamp("2026-09-07")})
    assert not v.allow, "người gọi chỉ đích danh ngày lễ mà cổng vẫn cho qua"


def test_the_walk_is_bounded():
    """Vòng lùi ngày không có trần là vòng chờ dữ liệu hỏng."""
    empty = pd.DatetimeIndex([])
    gate, stepped = TI._prev_full_session(empty, pd.Timestamp("2026-09-08"), "16:00")
    assert len(stepped) <= 14
    assert gate is not None


def test_an_unanswerable_frame_falls_back_and_that_direction_refuses():
    """Khung quá ngắn để trả lời thì quay về luật cuối tuần — tức gọi tên ngày lễ, tức TỪ
    CHỐI ở phép kiểm khoảng. Ghi ra để không ai nhầm một lời từ chối im lặng với sự thật."""
    empty = pd.DatetimeIndex([])
    gate, _ = TI._prev_full_session(empty, pd.Timestamp("2026-09-08"), "16:00")
    assert gate.date() == dt.date(2026, 9, 7)
