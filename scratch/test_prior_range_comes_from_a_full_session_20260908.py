"""Biên độ "hôm qua" phải đo trên một phiên ĐẦY ĐỦ. TỆP MỚI.

Bộ lọc này làm gì
-----------------
Trước khi vào lệnh, Normal-R4 hỏi: hôm qua giá chạy rộng bao nhiêu? Rộng quá ngưỡng thì đứng
ngoài. Ngưỡng `FLOOR_RANGE_P90` được tính trên các phiên **đầy đủ 6,5 giờ**.

Nó đang hỏi sai ngày
--------------------
`prev_rth_range_map` lấy `rng.shift(1)` — hàng liền trước của chuỗi ngày. Hàng đó tồn tại
với BẤT KỲ ngày nào có bar, kể cả ngày chỉ có một phần phiên. Hai loại ngày lọt vào:

    nửa phiên        3,5 giờ  → biên độ nhỏ hơn về cơ học, đem so ngưỡng của 6,5 giờ
    dữ liệu thủng    tệp cụt  → biên độ đo trên phần còn sót

Ca đắt nhất, đo được: **M2K ngày 01/07/2020**. Phiên trước, 30/06/2020, có **41 bar trên
391, dừng lúc 10:10** — một trong các artifact Databento đã biết. Bộ lọc đo "biên độ hôm
qua" trên bốn mươi phút dữ liệu, ra một con số bé, kết luận hôm qua yên tĩnh, và cho lệnh
đi. Ngày đó không hề yên tĩnh; tệp chỉ có bốn mươi phút.

Vì sao không dùng lịch
----------------------
Lịch chỉ bắt được nửa phiên, không bắt được ngày dữ liệu thủng. Và MNKD chạy trên đồng hồ
Tokyo — hỏi lịch NYSE về một phiên Nhật là đúng loại sai đã sửa hai lần trong tuần này.

Hỏi dữ liệu thì một câu trả lời cả hai: **phiên này có in ra bar cuối không.**

Cái giá, đo trước khi sửa
-------------------------
14 ngày đổi phán quyết trên năm công cụ (~1,6 ngày/năm), trong đó **2 ngày trùng một dòng đã
chốt** — M2K 01/07/2020 và MNQ 06/07/2026, cả hai lọt→chặn. Nên 1.223 → 1.221, và lời khẳng
định "tái lập chính xác" trong sổ blocker phải viết lại. Lãi/lỗ của hai dòng ấy là +136,76
và −143,24; con số đó KHÔNG phải lý do sửa, và được ghi ra đây để nó không lặng lẽ trở thành
lý do.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import global_index.track1_normal_filters as NF        # noqa: E402

PARQUETS = {
    "MES": "data/cache/futures/ES_continuous_1m_8y.parquet",
    "MNQ": "data/cache/futures/NQ_continuous_1m_8y.parquet",
    "M2K": "data/cache/futures/RTY_continuous_1m_8y.parquet",
    "MNKD": "global_index/data/NKD_continuous_1m_8y.parquet",
}


def _frame(inst: str):
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from global_index.track1_live_source import frozen_frame

        return frozen_frame(inst, str(REPO / PARQUETS[inst]))
    finally:
        logging.disable(logging.NOTSET)


def _ranges(inst: str):
    """{ngày -> biên độ RTH CỦA CHÍNH ngày đó} và tập ngày có bar cuối."""
    df = _frame(inst)
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    d = df.copy()
    d.index = idx
    rth = d[(d.index.time >= NF.RTH_START) & (d.index.time <= NF.RTH_END)]
    g = rth.groupby(rth.index.normalize())
    daily = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(),
                          "close": g["close"].last()})
    own = (daily["high"] - daily["low"]) / daily["close"].abs().clip(lower=1e-9)
    full = {dd for dd, gg in rth.groupby(rth.index.normalize())
            if (gg.index.time == NF.RTH_END).any()}
    return own, full


# ── ca đắt nhất ──────────────────────────────────────────────────────────────

def test_the_day_after_a_truncated_session_reaches_past_it():
    """01/07/2020 — hôm trước chỉ có 41/391 bar, dừng 10:10."""
    own, _full = _ranges("M2K")
    m = NF.prev_rth_range_map(_frame("M2K"))
    got = m[pd.Timestamp("2020-07-01")]
    assert got != pytest.approx(float(own[pd.Timestamp("2020-06-30")])), "vẫn lấy ngày cụt"
    assert got == pytest.approx(float(own[pd.Timestamp("2020-06-29")]))


def test_that_day_is_now_blocked_by_the_filter():
    m = NF.prev_rth_range_map(_frame("M2K"))
    assert m[pd.Timestamp("2020-07-01")] > NF.FLOOR_RANGE_P90


def test_the_day_after_a_half_session_reaches_past_it():
    """06/07/2026 — hôm trước là nửa buổi Quốc khánh, 210 bar dừng 12:59."""
    own, _full = _ranges("MNQ")
    m = NF.prev_rth_range_map(_frame("MNQ"))
    got = m[pd.Timestamp("2026-07-06")]
    assert got != pytest.approx(float(own[pd.Timestamp("2026-07-03")])), "vẫn lấy nửa phiên"
    assert got > NF.FLOOR_RANGE_P90


# ── tính chất, không phải ngày cụ thể ────────────────────────────────────────

@pytest.mark.parametrize("inst", ["MES", "MNQ", "M2K", "MNKD"])
def test_every_value_comes_from_a_session_that_ran_to_its_end(inst):
    """Phép kiểm mạnh nhất trong tệp: KHÔNG ngày nào trong bảng lấy giá trị từ một phiên
    thiếu bar cuối. Ghim tính chất nên nó vẫn canh được khi dữ liệu đổi."""
    own, full = _ranges(inst)
    m = NF.prev_rth_range_map(_frame(inst))
    assert len(m) > 500, len(m)
    ok = {round(float(own[d]), 12) for d in full if d in own.index}
    bad = [(str(k.date()), v) for k, v in m.items() if round(float(v), 12) not in ok]
    assert not bad[:5], bad[:5]


@pytest.mark.parametrize("inst", ["MES", "MNQ", "M2K", "MNKD"])
def test_it_asks_no_calendar(inst):
    """MNKD chạy trên đồng hồ Tokyo. Một luật hỏi lịch NYSE về phiên Nhật là loại sai kho này
    đã trả giá hai lần trong tuần."""
    import inspect

    src = inspect.getsource(NF.prev_rth_range_map)
    assert "trading_calendar" not in src and "is_early_close" not in src, src[:200]


def test_an_ordinary_day_is_unchanged():
    """Ngày thường sau một ngày thường: vẫn là hôm qua, không đổi gì."""
    own, _ = _ranges("MES")
    m = NF.prev_rth_range_map(_frame("MES"))
    assert m[pd.Timestamp("2026-09-04")] == pytest.approx(
        float(own[pd.Timestamp("2026-09-03")]))


def test_the_map_is_not_much_smaller_than_before():
    """Một luật chặt quá tay sẽ làm bảng teo lại và bộ lọc mất đầu vào ở hàng trăm ngày."""
    m = NF.prev_rth_range_map(_frame("MES"))
    own, _ = _ranges("MES")
    assert len(m) >= len(own) - 120, (len(m), len(own))


def test_an_empty_frame_still_returns_an_empty_map():
    assert NF.prev_rth_range_map(_frame("MES").iloc[:0]) == {}


# ── bản chuyển phải giống bản gốc ────────────────────────────────────────────

def test_the_promoted_copy_and_the_scratch_original_still_agree():
    """Cổng `SLEEVE_normal_r4` khẳng định bản sản xuất là bản sao trung thành. Sửa một bản mà
    quên bản kia thì cổng ấy đúng khi kêu — nên phép kiểm này đứng cạnh bản sửa."""
    import scratch.normal_promotion_filter_lib_20260821 as orig

    df = _frame("MES")
    a = orig.prev_rth_range_map(df)
    b = NF.prev_rth_range_map(df)
    assert set(a) == set(b), (len(a), len(b))
    diff = [str(k.date()) for k in a if float(a[k]) != float(b[k])]
    assert not diff[:5], diff[:5]
