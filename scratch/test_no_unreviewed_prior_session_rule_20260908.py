"""Không nơi nào được tự nghĩ ra "phiên trước" mà chưa ai duyệt. TỆP MỚI.

Vì sao có tệp này
-----------------
Sáng 08/09 Calm từ chối vì cổng đếm lùi một ngày, chỉ tránh cuối tuần, và rơi trúng Labor
Day. Đã sửa chỗ đó. Nhưng sửa một chỗ không ngăn được chỗ thứ hai — và chỗ thứ hai **đã tồn
tại**: bộ lập lịch có hàm riêng của nó, cùng luật, cùng lỗi, ở tệp khác.

Đo được: ba đêm mỗi năm — sau Giáng sinh, sau Tết dương, sau Good Friday — toàn bộ cửa sổ
NKD đêm bị bỏ, kèm thông báo đổ lỗi cho *"scheduler restart hoặc lỡ job 13:45"*. Slot có được
đăng ký, CME có phiên, dữ liệu lành lặn. Chỉ là bản ghi preflight của "ngày trước" không tồn
tại, vì "ngày trước" được đếm ra là một ngày lễ.

Ba lần cùng một gốc trong cùng một kho: `track1_freshness` đã viết đúng bài học này vào một
docstring rồi để nó ở lại trong tệp đó; `track1_intraday` mắc lại; `run_scheduler` vẫn đang
mắc. Không ai làm sai — chỉ là không có chỗ nào liệt kê chúng cạnh nhau.

Đây là chỗ đó.

Ba phần
-------
    A. mọi nơi đếm lùi ngày phải nằm trong sổ, kèm phán quyết
    B. sleeve nào hỏi "phiên trước" thì cổng phải chọn cùng ngày với bộ dò
    C. số nơi còn mù ngày lễ có TRẦN — cái thứ ba không được lặng lẽ xuất hiện
"""
from __future__ import annotations

import ast
import datetime as dt
import pathlib
import sys

import pandas as pd
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ROOTS = ("global_index", "futures", "raits/live", "monitor/backend")

#: Mọi nơi tự đếm lùi ngày lịch để tìm "hôm trước". Khoá là (tệp, hàm bao quanh).
#:
#: Thêm một dòng vào đây là một quyết định, không phải một thủ tục: nó có nghĩa là ai đó đã
#: đọc chỗ ấy và nói được nó dùng lịch, dùng dữ liệu, hay đang mù ngày lễ.
REVIEWED: dict = {
    ("global_index/track1_intraday.py", "_prev_business_day"):
        "mù ngày lễ CÓ CHỦ ĐÍCH — chỉ là đường dự phòng cuối của _prev_full_session, và "
        "hướng nó rơi vào là TỪ CHỐI",
    ("global_index/track1_freshness.py", "prev_business_day"):
        "mù ngày lễ, nhưng MÃ CHẾT — không nơi nào gọi; docstring cạnh nó đã ghi đúng lỗi này",
    ("global_index/run_scheduler.py", "_prev_bday"):
        "MÙ NGÀY LỄ VÀ ĐANG SỐNG — bỏ cửa sổ NKD 3 đêm mỗi năm; chưa ai quyết sửa",
    ("global_index/track1_slots.py", "_first_weekday"):
        "không phải luật phiên trước — đi TỚI từ một ngày ghim cứng, cho một phép kiểm",
    ("monitor/backend/track1_runtime_reader.py", "_closed_since"):
        "hỏi lịch, không đếm — đi qua từng ngày và hỏi is_trading_day",
}

#: Trong số trên, những nơi ĐANG SỐNG và ĐANG mù ngày lễ. Trần, không phải danh sách gợi ý.
BLIND_AND_LIVE = {("global_index/run_scheduler.py", "_prev_bday")}


def _walk_sites() -> dict:
    """{(tệp, hàm): dòng} cho mọi vòng lặp lùi ngày dựa trên weekday()."""
    out = {}
    for root in ROOTS:
        for f in sorted((REPO / root).rglob("*.py")):
            if "test_" in f.name or "_test" in f.name:
                continue
            try:
                src = f.read_text(encoding="utf-8")
                tree = ast.parse(src)
            except Exception:                                # noqa: BLE001
                continue
            fn_of = {}
            for n in ast.walk(tree):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for c in ast.walk(n):
                        fn_of[id(c)] = n.name
            rel = str(f.relative_to(REPO)).replace("\\", "/")
            for n in ast.walk(tree):
                if not isinstance(n, (ast.While, ast.For)):
                    continue
                seg = ast.get_source_segment(src, n) or ""
                if "weekday()" in seg and "days=1" in seg:
                    out[(rel, fn_of.get(id(n), "<module>"))] = n.lineno
    return out


# ── A. sổ đăng ký ────────────────────────────────────────────────────────────

def test_the_scan_finds_something_at_all():
    """Một máy quét trả về rỗng sẽ làm mọi phép kiểm dưới đây xanh mà không kiểm gì."""
    assert len(_walk_sites()) >= 4, _walk_sites()


def test_every_day_walking_rule_is_in_the_register():
    """Chỗ mới xuất hiện mà chưa ai đọc thì đỏ ngay, chứ không đợi một sáng thứ Ba."""
    unknown = {k: v for k, v in _walk_sites().items() if k not in REVIEWED}
    assert not unknown, (
        f"nơi tự đếm lùi ngày mà chưa có trong sổ: {unknown}. Đọc nó, rồi thêm một dòng vào "
        f"REVIEWED nói nó dùng lịch, dùng dữ liệu, hay đang mù ngày lễ.")


def test_the_register_has_no_entries_for_code_that_moved():
    """Sổ trỏ vào hàm đã đổi tên là sổ xanh vì không còn gì để canh."""
    sites = _walk_sites()
    stale = [k for k in REVIEWED if k not in sites]
    assert not stale, f"mục trong sổ không còn ứng với mã nào: {stale}"


def test_every_entry_says_something_checkable():
    for k, why in REVIEWED.items():
        assert len(why.split()) >= 8, k


# ── B. cổng phải chọn cùng ngày với bộ dò ────────────────────────────────────

HOLIDAY_DATES = ["2026-09-08", "2025-12-01", "2024-12-02", "2025-07-07", "2026-09-04",
                 "2026-01-02", "2026-07-06", "2025-12-26", "2025-02-18", "2026-01-20"]


def test_only_the_sleeves_we_reconciled_ask_for_a_prior_session():
    """Sleeve mới bật `needs_prior_rth` mà chưa đối chiếu với bộ dò của nó thì đỏ.

    Đó chính là cách chỗ hỏng vừa rồi sống sót: một yêu cầu được khai báo, và không ai hỏi
    xem cái gì trả lời nó.
    """
    from global_index.track1_intraday import PHASE_REQUIREMENTS, REQUIREMENTS

    asking = {k if isinstance(k, str) else k[0]
              for k, r in list(REQUIREMENTS.items()) + list(PHASE_REQUIREMENTS.items())
              if getattr(r, "needs_prior_rth", False)}
    assert asking == {"roska4_calm"}, (
        f"{asking - {'roska4_calm'}} hỏi phiên trước mà chưa có phép đối chiếu — thêm nó vào "
        f"test_the_gate_and_the_detector_agree bên dưới trước khi cho chạy")


def test_the_gate_and_the_detector_agree():
    """Hai nơi cùng phát biểu "phiên trước là ngày nào" là hai nơi có thể trôi khỏi nhau."""
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        import global_index.track1_intraday as TI
        from global_index.track1_calm_a import CalmAParams, rth_sessions
        from global_index.track1_live_source import frozen_frame

        df = frozen_frame("MES", str(REPO / "data/cache/futures/ES_continuous_1m_8y.parquet"))
        bars = df.resample("5min").agg({"open": "first", "high": "max", "low": "min",
                                        "close": "last", "volume": "sum"}).dropna()
        idx = TI._naive(pd.DatetimeIndex(bars.index))
        sess = rth_sessions(df, CalmAParams())
    finally:
        logging.disable(logging.NOTSET)

    assert len(sess) > 100, "bảng phiên rỗng thì so sánh dưới đây tự đồng ý với chính nó"
    lech = []
    for d in HOLIDAY_DATES:
        gate, _ = TI._prev_full_session(idx, pd.Timestamp(d), "16:00")
        prev = [x for x in sess.index if x < pd.Timestamp(d)]
        if gate.date() != prev[-1].date():
            lech.append((d, str(gate.date()), str(prev[-1].date())))
    assert not lech, lech


# ── C. trần cho những nơi còn mù ─────────────────────────────────────────────

def _prev_weekday(d: dt.date) -> dt.date:
    x = d - dt.timedelta(days=1)
    while x.weekday() >= 5:
        x -= dt.timedelta(days=1)
    return x


def test_the_two_documented_blind_rules_are_still_blind_and_still_named():
    """Ghim HÀNH VI, không ghim mã nguồn. Nếu ai sửa chúng, phép kiểm này đỏ và bảo cập nhật
    sổ — một tin tốt cần được ghi lại chứ không được trôi qua im lặng."""
    import global_index.track1_freshness as F
    import global_index.track1_intraday as TI

    after_holiday = pd.Timestamp("2026-09-08")
    assert TI._prev_business_day(after_holiday).date() == dt.date(2026, 9, 7)
    assert F.prev_business_day(after_holiday).date() == dt.date(2026, 9, 7)


def test_the_dead_one_is_still_dead():
    """Mã chết vô hại. Mã chết được ai đó gọi vào thì thành ca thứ tư."""
    import ast as _ast

    callers = []
    for root in ROOTS:
        for f in (REPO / root).rglob("*.py"):
            if "test_" in f.name:
                continue
            try:
                tree = _ast.parse(f.read_text(encoding="utf-8"))
            except Exception:                                # noqa: BLE001
                continue
            for n in _ast.walk(tree):
                if (isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
                        and n.func.id == "prev_business_day"):
                    callers.append(str(f.relative_to(REPO)))
    assert not callers, f"prev_business_day không còn là mã chết — {callers} gọi nó"


def test_the_live_blind_rule_is_capped_at_one():
    """Trần. Ca thứ ba không được lặng lẽ xuất hiện."""
    assert len(BLIND_AND_LIVE) == 1, BLIND_AND_LIVE
    assert BLIND_AND_LIVE <= set(REVIEWED)


def test_the_scheduler_case_is_measured_not_asserted():
    """Ba đêm mỗi năm, và phép kiểm này đo lại chứ không tin lời tôi viết trong sổ."""
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from monitor.backend.schedule_status import scheduler_registers_on
    finally:
        logging.disable(logging.NOTSET)

    bad = []
    for d in ("2025-12-26", "2026-01-02", "2026-04-06"):
        day = dt.date.fromisoformat(d)
        prior = _prev_weekday(day)
        if scheduler_registers_on(day) and scheduler_registers_on(prior) is False:
            bad.append((d, str(prior)))
    assert len(bad) == 3, (
        f"số đêm bị bỏ đã đổi ({bad}) — hoặc ai đó đã sửa, hoặc lịch đã đổi. Cả hai đều cần "
        f"cập nhật sổ chứ không được trôi qua")
