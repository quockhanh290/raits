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
    ("global_index/run_scheduler.py", "_prev_scheduled_day"):
        "hỏi scheduler_registers_on, không đếm — vòng weekday còn lại chỉ là đường dự phòng "
        "khi không nạp được lịch, và nó rơi đúng về luật cũ chứ không sang luật mới",
    ("global_index/track1_slots.py", "_first_weekday"):
        "không phải luật phiên trước — đi TỚI từ một ngày ghim cứng, cho một phép kiểm",
    ("monitor/backend/track1_runtime_reader.py", "_closed_since"):
        "hỏi lịch, không đếm — đi qua từng ngày và hỏi is_trading_day",
}

#: Những nơi ĐANG SỐNG và ĐANG mù ngày lễ. Rỗng, và đó là điều phải giữ.
#:
#: Từng có một: `run_scheduler._prev_bday`, bỏ cửa sổ NKD ba đêm mỗi năm. Đã sửa. Hai mục
#: còn mù trong sổ trên đều không sống: một là đường dự phòng cuối, một là mã chết.
BLIND_AND_LIVE: set = set()


#: Hình dạng THỨ HAI của cùng câu hỏi: `shift()` trên một chuỗi theo ngày. Máy quét vòng lặp
#: ở trên không thấy chúng, và chỗ lệch duy nhất tôi tìm được trong tuyến nằm đúng ở đây.
#:
#: Phạm vi cố ý hẹp — chỉ các tệp của tuyến Track 1 và bộ sinh bảng cơ sở. Đăng ký toàn kho
#: sẽ kéo vào hàng chục chỗ tính lợi suất và ATR không liên quan tới "phiên trước", và một sổ
#: đầy tiếng ồn là một sổ không ai đọc.
SHIFT_SCOPE = ("global_index/track1_", "monitor/backend/track1_",
               "global_index/generate_replay_snapshots.py")

#: (tệp, hàm) -> (số lần shift, phán quyết)
SHIFT_REVIEWED: dict = {
    ("global_index/generate_replay_snapshots.py", "<module>"): (1,
        "nhãn chế độ lùi 1 ngày trên chuỗi SPY ngày — chuỗi đó chỉ chứa ngày giao dịch, nên "
        "lùi một hàng đúng là phiên trước"),
    ("global_index/track1_normal_filters.py", "slot_volume_frame"): (2,
        "một cái là bar 5 phút liền trước, không phải phiên; cái kia nhóm theo giờ trong ngày "
        "nên là cùng khung giờ của phiên trước — nửa phiên tự rơi ra ở các khung buổi chiều"),
    ("global_index/track1_normal_filters.py", "prev_rth_range_map"): (1,
        "LỆCH ĐÃ BIẾT — nhận nửa phiên làm phiên trước, còn Calm thì bỏ. Đo được: đổi lại sẽ "
        "làm 40 ngày đổi giá trị và ĐÚNG 1 ngày đổi kết luận, và phá tính tái lập 1.223 dòng"),
    ("global_index/track1_normal_filters.py", "spy_feature_frame"): (6,
        "toàn bộ là độ trễ trên chuỗi SPY ngày, chuỗi chỉ chứa ngày giao dịch nên lùi hàng "
        "đúng là lùi phiên; không cái nào tự định nghĩa phiên trước theo lịch"),
}


def _shift_sites() -> dict:
    """{(tệp, hàm): số lần .shift(...)} trong phạm vi tuyến."""
    out: dict = {}
    for root in ROOTS:
        for f in sorted((REPO / root).rglob("*.py")):
            rel = str(f.relative_to(REPO)).replace("\\", "/")
            if "test_" in f.name or not rel.startswith(SHIFT_SCOPE):
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
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "shift"):
                    k = (rel, fn_of.get(id(n), "<module>"))
                    out[k] = out.get(k, 0) + 1
    return out


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


def test_no_live_rule_is_blind_any_more():
    """Trần bằng không. Một ca mới không được lặng lẽ xuất hiện."""
    assert BLIND_AND_LIVE == set(), BLIND_AND_LIVE


def test_the_scheduler_case_is_measured_not_asserted():
    """Ba đêm ấy vẫn là ba đêm luật CŨ sẽ hỏng, và luật MỚI thì không.

    Đo lại cả hai chiều mỗi lần chạy, chứ không tin lời tôi viết trong sổ. Nếu lịch đổi và
    ba đêm ấy không còn là ba đêm nữa, phép kiểm này đỏ và bắt đọc lại.
    """
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        import global_index.run_scheduler as rs
        from monitor.backend.schedule_status import scheduler_registers_on
    finally:
        logging.disable(logging.NOTSET)

    would_have_broken, still_broken = [], []
    for d in ("2025-12-26", "2026-01-02", "2026-04-06"):
        day = dt.date.fromisoformat(d)
        if not scheduler_registers_on(day):
            continue
        if scheduler_registers_on(_prev_weekday(day)) is False:
            would_have_broken.append(d)
        if scheduler_registers_on(rs._prev_scheduled_day(day)) is not True:
            still_broken.append(d)
    assert would_have_broken == ["2025-12-26", "2026-01-02", "2026-04-06"], would_have_broken
    assert still_broken == [], still_broken


# ── hình dạng thứ hai: shift() trên chuỗi theo ngày ──────────────────────────

def test_the_shift_scan_finds_something_at_all():
    assert len(_shift_sites()) >= 3, _shift_sites()


def test_every_shift_in_the_route_is_in_the_register():
    """Một luật "phiên trước" viết bằng `shift(1)` là vô hình với máy quét vòng lặp. Sổ này
    là chỗ nó không vô hình nữa."""
    sites = _shift_sites()
    unknown = {k: v for k, v in sites.items() if k not in SHIFT_REVIEWED}
    assert not unknown, (
        f"shift() trong tuyến mà chưa có trong sổ: {unknown}. Đọc nó, rồi nói nó là bar liền "
        f"trước, phiên liền trước, hay một luật lịch tự chế.")


def test_the_shift_counts_still_match():
    """Đếm, không chỉ có mặt: thêm một `shift` vào một hàm đã duyệt cũng là một luật mới."""
    sites = _shift_sites()
    drift = {k: (sites.get(k), n) for k, (n, _why) in SHIFT_REVIEWED.items()
             if sites.get(k) != n}
    assert not drift, f"số lần shift đã đổi (thấy, đã ghi): {drift}"


def test_every_shift_entry_says_something_checkable():
    for k, (_n, why) in SHIFT_REVIEWED.items():
        assert len(why.split()) >= 10, k


def test_the_known_divergence_is_still_exactly_one_day():
    """Chỗ lệch R4 được GHIM bằng số đo, không bằng lời.

    Nếu nó lớn lên — thêm ngày đổi kết luận — phép kiểm này đỏ và bắt đọc lại. Nếu ai sửa nó,
    cũng đỏ, và đó là tin tốt cần được ghi vào sổ chứ không được trôi qua.
    """
    import logging
    import warnings

    import numpy as np

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from global_index.track1_live_source import frozen_frame
        from global_index.track1_normal_filters import (FLOOR_RANGE_P90, RTH_END, RTH_START)
        from raits.live.trading_calendar import is_early_close
    finally:
        logging.disable(logging.NOTSET)

    df = frozen_frame("MES", str(REPO / "data/cache/futures/ES_continuous_1m_8y.parquet"))
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    d = df.copy()
    d.index = idx
    rth = d[(d.index.time >= RTH_START) & (d.index.time <= RTH_END)]
    g = rth.groupby(rth.index.normalize())
    daily = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(),
                          "close": g["close"].last()})
    rng = (daily["high"] - daily["low"]) / daily["close"].abs().clip(lower=1e-9)

    now = rng.shift(1)
    full = [x for x in rng.index if not is_early_close(x.date())]
    aligned = rng.reindex(full).shift(1).reindex(rng.index).ffill()

    flips = [x.date() for x in rng.index
             if np.isfinite(now.get(x, np.nan)) and np.isfinite(aligned.get(x, np.nan))
             and (now[x] <= FLOOR_RANGE_P90) != (aligned[x] <= FLOOR_RANGE_P90)]
    assert flips == [dt.date(2018, 12, 24)], flips
