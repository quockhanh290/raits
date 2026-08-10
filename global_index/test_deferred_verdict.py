"""Công cụ chẩn đoán phải biết cửa sổ hoãn STP — nếu không chúng hoàn tác bản vá.

`runner` cố ý KHÔNG đặt STP cho vị thế swing/NKD mở trong ngày; B4 đặt ở phiên sau
(xem `runner._stop_deferred`, đo 2018–2026: đặt ngay −$10.832 vs đặt sang ngày +$47.166).

Hai công cụ CLI đứng ngoài luồng đó:
  - `check_open_orders.py` gọi `classify()` — sẽ báo NAKED cho MỌI lệnh mới, in FAIL,
    trả exit 1, kèm dòng "Run repair_stops.py". Đây là nửa nguy hiểm hơn: một chữ NAKED
    sai mỗi ngày dạy người vận hành bỏ qua chữ đó, rồi vị thế trần thật bị lọt.
  - `repair_stops.py` import lại chính `classify()` và nhánh cuối từng là `else: # NAKED`
    → verdict mới nào cũng bị ĐẶT STOP. Đúng hành động phá bản vá.

Tập cluster được IMPORT từ runner, không chép — hai bản sao sẽ lệch, và lệch kiểu này thì
một công cụ bảo vệ vị thế mà công cụ kia để trần.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.check_open_orders import Stop, classify
from global_index.runner import _DEFERRED_STOP_CLUSTERS

TODAY = pd.Timestamp("2026-08-10")
SWING, NKD, STRESS = "roska4_swing", "global_nkd", "roska4_stress"


def _pos(inst="MES", cluster=SWING, entry_day=TODAY, stop=7769.03):
    return dict(inst=inst, direction="SHORT", cluster=cluster,
                entry_day=str(entry_day) if entry_day is not None else None,
                stop_price=stop)


def _verdicts(positions, stops=None, today=TODAY):
    return [r[0] for r in classify(positions, stops or {}, today=today)]


def test_fresh_swing_position_is_deferred_not_naked():
    """Ca chính: lệnh mở hôm nay, chưa có stop trên sàn — ĐÚNG như thiết kế."""
    assert _verdicts([_pos()]) == ["DEFERRED"]


def test_yesterdays_position_without_a_stop_is_still_naked():
    """Cửa sổ hết hạn thì cảnh báo phải quay lại. Mất nửa này là mất luôn khả năng
    phát hiện stop hỏng thật — tệ hơn hẳn cái đang đi sửa."""
    assert _verdicts([_pos(entry_day=TODAY - pd.Timedelta(days=1))]) == ["NAKED"]


def test_nkd_is_deferred_too():
    assert _verdicts([_pos(inst="MNKD", cluster=NKD)]) == ["DEFERRED"]


def test_stress_is_never_deferred():
    """STRESS_MID không chạy engine swing — adapter xét stop ngay từ bar vào lệnh."""
    assert _verdicts([_pos(cluster=STRESS)]) == ["NAKED"]


def test_unknown_entry_day_is_naked():
    """Không biết vào ngày nào thì báo động, không đoán."""
    assert _verdicts([_pos(entry_day=None)]) == ["NAKED"]


def test_a_working_stop_still_reads_OK_during_the_window():
    """Có stop rồi thì DEFERRED không được che mất — thứ tự nhánh phải đúng."""
    stops = {"MES": [Stop("BUY", 12, 7769.25, 1)]}
    assert _verdicts([_pos()], stops) == ["OK"]


def test_wrong_side_stop_during_the_window_is_still_reported():
    """Cửa sổ hoãn nói về việc CHƯA có stop. Một stop sai chiều thì vẫn nguy hiểm
    y như cũ và không được im lặng chỉ vì lệnh mới mở."""
    stops = {"MES": [Stop("SELL", 12, 7769.25, 1)]}   # SHORT cần BUY STP
    assert _verdicts([_pos()], stops) == ["WRONG-WAY"]


def test_the_cluster_set_is_shared_not_copied():
    """Nếu ai đó chép danh sách cluster sang check_open_orders thay vì import, hai bản
    sẽ lệch nhau lúc thêm sleeve mới. Chốt bằng chính đối tượng được import."""
    assert SWING in _DEFERRED_STOP_CLUSTERS and NKD in _DEFERRED_STOP_CLUSTERS
    assert STRESS not in _DEFERRED_STOP_CLUSTERS


def test_repair_stops_never_places_for_an_unknown_verdict():
    """Nhánh cuối của repair_stops từng là `else: # NAKED`, nghĩa là verdict nào mới
    thêm cũng thừa hưởng hành động phá hoại nhất trong file. Đó chính là cách DEFERRED
    lẽ ra đã âm thầm hoàn tác bản vá."""
    src = (Path(__file__).resolve().parents[1]
           / "global_index" / "repair_stops.py").read_text(encoding="utf-8")
    assert 'elif verdict == "NAKED":' in src, "NAKED phải được xử lý TƯỜNG MINH"
    assert 'else:  # NAKED' not in src, "nhánh else mặc định không được đặt stop"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
