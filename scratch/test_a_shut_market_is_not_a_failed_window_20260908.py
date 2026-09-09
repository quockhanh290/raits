"""Chợ đóng cửa không phải một cửa sổ hỏng. TỆP MỚI.

Câu hỏi của chủ dự án
---------------------
    "vậy thì phải xem swing chặn như vậy là đúng hay là sai? nếu ko có bar thì chặn là đúng
     rồi, vì sao lại đánh giá là fail?"

Đúng. Ngày Labor Day 07/09/2026, CME đóng lúc 13:00. Cửa sổ Swing là 14:05–15:55 — nằm trọn
sau giờ đóng. Hai mươi ba slot chạy, nhìn, thấy không có bar nào, và từ chối. **Đó là hành vi
đúng.** Không có bar nào để nhìn, và cũng không thể có.

Sổ đánh giá chấm cả hai mươi ba là `observed_hard_refusal`, và cả ngày thành FAIL.

Vì sao nó chấm thế
------------------
`classify_slot_row` tính một slot là "đã quan sát đúng thiết kế" khi và chỉ khi mọi mã từ
chối của nó nằm trong `{too_early, too_late}` — tức dải quyết định của sleeve đang đóng.
Docstring của `evaluate_sleeve` nói thẳng phần còn lại:

    Một slot không lấy được bar, không dựng được nguồn, đọc khung cũ... thì không — và cái
    đó vẫn là hỏng.

Câu ấy gộp hai chuyện vào một: **không lấy được bar vì hệ hỏng**, và **không có bar vì chợ
đóng**. Chuyện thứ nhất phải gọi người dậy; chuyện thứ hai thì không.

Vì sao chuyện này không nhỏ
---------------------------
Sổ đánh giá shadow là **cổng chặn gửi lệnh**, và ngưỡng của nó là 0 ngày FAIL trên 5 ngày
xét. Nên mỗi ngày lễ tự khoá cổng go-live thêm năm ngày xét nữa, vì một hành vi đúng.

Tầng phân loại đã biết tách hai chuyện đó — `track1_refusal_cause` trả về `market_closed` và
`system_fault` là hai nguyên nhân khác nhau, đo trên 112 lời từ chối có thật. Nó chỉ chưa
được ai hỏi ở chỗ này.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import global_index.track1_shadow_acceptance as A     # noqa: E402

LABOR_DAY = "2026-09-07"


def _row(**kw) -> dict:
    base = {"route": "track1_candidate", "sleeve": "roska4_swing", "date": LABOR_DAY,
            "event": "slot_observed", "slot_id": "TRACK1_SWING_1405", "decided": False,
            "reason": "gate_refused", "detail": "missing_session,stale", "candidates": None}
    base.update(kw)
    return base


# ── ca đã xảy ra ─────────────────────────────────────────────────────────────

def test_a_slot_refused_because_the_market_was_shut_counts_as_observed():
    assert A.classify_slot_row(_row()) == A.SLOT_MARKET_CLOSED


def test_that_class_proves_somebody_looked():
    assert A.SLOT_MARKET_CLOSED in A.OBSERVED_CLASSES


def test_it_is_kept_apart_from_the_clock_being_shut():
    """Hai sự thật khác nhau: dải quyết định đóng, và thị trường đóng. Gộp chúng là mất một
    thứ mà người đọc hồ sơ cần phân biệt."""
    assert A.SLOT_MARKET_CLOSED != A.SLOT_WINDOW_SHUT


def test_the_labor_day_swing_window_is_no_longer_a_failure():
    """Cả hai mươi ba slot, trên bản ghi thật của ngày đó."""
    import json

    p = REPO / "global_index/track1_runtime/window_coverage/window_coverage_20260907.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    swing = [r for r in rows
             if r.get("sleeve") == "roska4_swing" and r.get("event") == "slot_observed"]
    assert len(swing) == 23, len(swing)
    classes = {A.classify_slot_row(r) for r in swing}
    assert classes == {A.SLOT_MARKET_CLOSED}, classes


# ── và vẫn phải bắt được lỗi thật ────────────────────────────────────────────

def test_a_real_system_fault_is_still_a_hard_refusal():
    """04/09 NKD: mười chín slot bị `overlap_disagreement` — hai nửa dữ liệu bất đồng. Chợ
    mở, dữ liệu sai. Cái đó vẫn phải là hỏng."""
    r = _row(sleeve="global_nkd", date="2026-09-04", slot_id="TRACK1_NKD_0110",
             detail="overlap_disagreement")
    assert A.classify_slot_row(r) == A.SLOT_HARD_REFUSAL


def test_a_session_that_was_open_and_still_refused_is_a_hard_refusal():
    """Chợ mở suốt cửa sổ mà cổng vẫn chặn — dữ liệu đáng lẽ phải có."""
    r = _row(date="2026-09-04", detail="missing_session,stale")   # 04/09 là phiên đầy đủ
    assert A.classify_slot_row(r) == A.SLOT_HARD_REFUSAL


def test_the_clock_codes_are_unchanged():
    from global_index import track1_intraday as intra

    assert A.classify_slot_row(_row(detail=intra.TOO_EARLY)) == A.SLOT_WINDOW_SHUT
    assert A.classify_slot_row(_row(detail=intra.TOO_LATE)) == A.SLOT_WINDOW_SHUT


def test_a_decided_slot_is_unchanged():
    assert A.classify_slot_row(_row(decided=True, candidates=None)) == A.SLOT_NO_ACTION
    assert A.classify_slot_row(_row(decided=True, candidates=[{"x": 1}])) == A.SLOT_DECISION


def test_a_non_gate_refusal_is_still_a_hard_refusal():
    assert A.classify_slot_row(_row(reason="provider_error", detail="")) == A.SLOT_HARD_REFUSAL


def test_an_empty_detail_is_still_a_hard_refusal():
    """Cổng luôn ghi mã của nó, nên rỗng nghĩa là có gì đó viết một dòng hàm này không đọc
    được — và đoán theo hướng dễ dãi là cách một lỗi im lặng thành một điểm đạt."""
    assert A.classify_slot_row(_row(detail="")) == A.SLOT_HARD_REFUSAL


def test_a_row_that_is_not_a_row_is_still_a_hard_refusal():
    assert A.classify_slot_row("không phải dict") == A.SLOT_HARD_REFUSAL


def test_a_classifier_that_cannot_answer_fails_closed(monkeypatch):
    """Không phân loại được thì giữ nguyên "hỏng". Hướng an toàn, và là hướng cũ.

    Bản đầu của phép kiểm này chặn `__import__` theo tên đầy đủ và không bao giờ nổ — vì
    `from global_index import X` truyền tên `"global_index"`, còn `X` nằm trong `fromlist`.
    Phá thẳng vào hàm phân loại thì không có chỗ cho nhầm lẫn đó.
    """
    from global_index import track1_refusal_cause as rc

    def boom(*a, **k):
        raise RuntimeError("tầng phân loại hỏng")

    monkeypatch.setattr(rc, "classify_slot", boom)
    assert A.classify_slot_row(_row()) == A.SLOT_HARD_REFUSAL


def test_an_unknown_cause_is_not_treated_as_a_shut_market():
    """Chỉ `market_closed` mới mở đường này. `unknown` thì không — không biết không phải là
    một lời bào chữa."""
    r = _row(sleeve="không_có_sleeve_này", detail="missing_session")
    assert A.classify_slot_row(r) == A.SLOT_HARD_REFUSAL
