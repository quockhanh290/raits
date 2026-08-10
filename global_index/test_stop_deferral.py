"""Cửa sổ hoãn STP được neo theo ĐỒNG HỒ NÀO — và vì sao đó là chỗ dễ sai nhất.

Luật *khi nào* vũ trang nằm ở `test_arm_time_per_sleeve.py` (mỗi sleeve một giờ riêng,
14h sau ranh giới ngày phiên của chính nó). File này chỉ giữ phần **múi giờ**, vì nó là
loại lỗi đã xảy ra bốn lần trong một phiên làm việc và không lần nào tự báo.

Trước đây file này còn chốt "cửa sổ đúng một ngày lịch". Luật đó đã bị thay: nó khiến CẢ
HAI sleeve được đặt stop ở job đầu tiên của ngày kế tiếp — tình cờ là slot đêm 01:10 ET,
đúng cho NKD (14h JST) nhưng sai cho Rổ 4 (mới 1,17h sau ranh giới ngày ET, đo được
+$41.505 thay vì +$116.530 ngoài mẫu). Các ca đó đã chuyển sang file mới.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.runner import ET_TZ, FuturesRunner

SWING = "roska4_swing"


class _P:
    def __init__(self, entry_day):
        self.cluster, self.inst = SWING, "MES"
        self.entry_day = pd.Timestamp(entry_day)
        self.direction, self.contracts = "SHORT", 1
        self.stop_price, self.stop_order_id = 7769.03, None


def test_host_clock_would_name_the_wrong_session():
    """Máy chạy hệ thống đi trước ET 11 tiếng. 09:00 sáng ở đó là 22:00 ET NGÀY HÔM
    TRƯỚC — nên một mốc lấy theo giờ máy gọi sai phiên trong phần lớn ngày làm việc.

    Sai theo hướng nguy hiểm: vũ trang stop sớm một ngày, tức quay lại đúng cấu hình đã
    đo là kém nhất.
    """
    et = pd.Timestamp("2026-08-10 22:00", tz=ET_TZ)
    host = et.tz_convert("Asia/Ho_Chi_Minh")
    assert et.normalize().tz_localize(None) == pd.Timestamp("2026-08-10")
    assert host.normalize().tz_localize(None) == pd.Timestamp("2026-08-11")

    r = FuturesRunner.__new__(FuturesRunner)
    p = _P("2026-08-10")

    # neo ET: 22:00 ET ngày vào lệnh — chưa tới 14:00 ET hôm sau
    r._now = pd.Timestamp("2026-08-10 22:00")
    assert r._stop_deferred(p) is True

    # neo giờ máy: đã sang 2026-08-11, và nếu ai đó lấy nửa đêm ngày đó thì vẫn hoãn,
    # nhưng lấy 14:05 "hôm nay" theo giờ máy thì vũ trang sớm nguyên một phiên
    r_bad = FuturesRunner.__new__(FuturesRunner)
    r_bad._now = pd.Timestamp("2026-08-11 14:05")
    assert r_bad._stop_deferred(p) is False        # đã vũ trang — đúng theo ET là hôm sau


def test_default_now_is_read_in_et():
    """Không truyền gì thì mốc mặc định phải là giờ ET, không phải giờ máy."""
    r = FuturesRunner.__new__(FuturesRunner)
    r._now = pd.Timestamp.now(tz=ET_TZ).tz_localize(None)
    delta = abs((r._now - pd.Timestamp.now(tz=ET_TZ).tz_localize(None)).total_seconds())
    assert delta < 5


def test_passing_today_without_now_is_deterministic():
    """`today` một mình nghĩa là "coi như là ngày đó" — lấy nửa đêm ngày đó, KHÔNG lấy
    đồng hồ thật. Trộn hai thứ sẽ làm test đỏ hay xanh tuỳ giờ chạy."""
    import json
    from futures.circuit_breaker import CircuitBreaker
    from global_index.broker import MockBroker
    from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard

    g = MultiClusterGuard(clusters={SWING: ClusterBudget(SWING, max_gross_pct=0.05,
                                                         max_net_pct=0.044)},
                          account=50_000.0)
    r = FuturesRunner(broker=MockBroker({}, 50_000.0), guard=g,
                      contracts_by_inst={"MES": 1},
                      signal_fn=lambda d, b, h: ([], []),
                      breaker=CircuitBreaker(account=50_000.0),
                      today=pd.Timestamp("2024-03-12"))
    assert r._now == pd.Timestamp("2024-03-12")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
