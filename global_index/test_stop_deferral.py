"""Cửa sổ không-có-stop là CÓ CHỦ ĐÍCH — ai được hưởng, ai không, và khi nào nó hết.

Live đặt STP 0–1 giây sau khi khớp. `backtest_swing_tf` kiểm stop trong khối
`if pos is not None`, chạy trước khối vào lệnh cùng vòng lặp ngày, nên vị thế mở hôm nay
mãi hôm sau mới bị xét. Đo trên 2018–2026 (model_sameday_stop.py, có cổng đối chiếu
trade-for-trade với engine): đặt ngay **−$10.832**, đặt sang ngày **+$47.166**.

Ba guard cùng phải hiểu cửa sổ này — chỗ đặt lệnh, B4, B5. Bỏ sót B4 là hỏng cả bản sửa:
nó tự đặt lại stop ở mỗi lần chạy, cửa sổ co còn ~5 phút, và bảng đo nói mốc đó vẫn âm.

Điều kiện biên quan trọng nhất ở đây là **múi giờ**. Máy chạy hệ thống đi trước ET 11
tiếng, nên `Timestamp.now()` theo giờ máy gọi sai phiên trong phần lớn ngày làm việc —
và gọi sai theo hướng nguy hiểm: đặt stop sớm một ngày, tức quay về đúng cấu hình lỗ.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.runner import ET_TZ, FuturesRunner

SWING, NKD, STRESS = "roska4_swing", "global_nkd", "roska4_stress"
TODAY = pd.Timestamp("2026-08-10")


class _P:
    def __init__(self, cluster, entry_day, inst="MES"):
        self.cluster, self.inst = cluster, inst
        self.entry_day = None if entry_day is None else pd.Timestamp(entry_day)
        self.direction, self.contracts = "SHORT", 1
        self.stop_price, self.stop_order_id = 7769.03, None


def _runner(today=TODAY):
    r = FuturesRunner.__new__(FuturesRunner)
    r._today = pd.Timestamp(today).normalize()
    return r


def test_entered_today_is_deferred():
    """Trường hợp chính: vào lệnh chiều nay thì chưa đặt STP."""
    assert _runner()._stop_deferred(_P(SWING, TODAY)) is True


def test_entered_yesterday_is_protected():
    """Cửa sổ hết hạn TỰ NÓ khi sang ngày — không cần job mới, chính B4 đặt stop."""
    assert _runner()._stop_deferred(_P(SWING, TODAY - pd.Timedelta(days=1))) is False


def test_the_window_is_exactly_one_calendar_day():
    """Sang ngày lịch là hết, khớp đúng luật engine dùng. Nếu chỗ này nới ra thì live
    chạy một luật khác backtest lần nữa, chỉ theo chiều ngược lại."""
    r = _runner()
    assert r._stop_deferred(_P(SWING, TODAY)) is True
    assert r._stop_deferred(_P(SWING, TODAY - pd.Timedelta(days=1))) is False


def test_nkd_is_included():
    """NKD chạy CÙNG backtest_swing_tf nên thừa hưởng đúng ngữ nghĩa đó. Độ lớn bằng
    tiền cho NKD thì CHƯA đo — mới chỉ đo Rổ 4 — nhưng sai lệch luật thì y hệt."""
    assert _runner()._stop_deferred(_P(NKD, TODAY, inst="MNKD")) is True


def test_stress_is_not_deferred():
    """STRESS_MID vào và ra trong cùng phiên, không chạy qua engine swing. Phép đo
    không phủ nó, nên không đụng tới: STP vẫn đặt ngay lúc khớp."""
    assert _runner()._stop_deferred(_P(STRESS, TODAY)) is False


def test_unknown_entry_day_is_protected():
    """Không biết vào ngày nào thì bảo vệ, không đoán. Hoãn nhầm nghĩa là để một vị thế
    trần vô thời hạn — hỏng nặng hơn hẳn so với đặt stop sớm."""
    assert _runner()._stop_deferred(_P(SWING, None)) is False


def test_a_stale_entry_day_far_in_the_past_is_protected():
    """Vị thế cũ mang qua nhiều ngày phải có stop, không được rơi vào cửa sổ."""
    assert _runner()._stop_deferred(_P(SWING, "2026-07-01")) is False


def test_explicit_today_overrides_the_stored_one():
    """B5 nhận `day` từ run_day; B4 chạy lúc dựng runner nên dùng giá trị đã lưu. Hai
    đường phải cho cùng câu trả lời trên cùng một ngày."""
    r = _runner(TODAY + pd.Timedelta(days=5))
    p = _P(SWING, TODAY)
    assert r._stop_deferred(p) is False           # theo _today đã lưu (đã qua cửa sổ)
    assert r._stop_deferred(p, TODAY) is True     # theo ngày truyền vào


def test_an_entry_day_in_the_future_is_protected():
    """Trạng thái hỏng, không phải cửa sổ. Bản đầu tôi viết `>=` nên ngày vào ở tương
    lai bị hoãn MÃI MÃI — vị thế trần vô thời hạn, tệ hơn hẳn cái đang đi sửa. Mọi
    trường hợp không chắc trong hàm này đều phải nghiêng về việc ĐẶT stop."""
    assert _runner()._stop_deferred(_P(SWING, TODAY + pd.Timedelta(days=1))) is False


def test_host_clock_would_name_the_wrong_session():
    """Điều kiện biên đắt nhất, nên nêu thẳng thành số.

    Máy chạy hệ thống đi trước ET 11 tiếng. 09:00 sáng ở đây là 22:00 ET NGÀY HÔM TRƯỚC.
    Lấy ngày theo giờ máy thì một vị thế vào chiều qua (giờ ET) bị coi là 'vào hôm nay'
    → hoãn thêm một ngày; còn buổi tối thì ngược lại, đặt stop sớm một ngày và rơi lại
    vào đúng cấu hình −$10.832. Neo theo ET là bắt buộc, không phải tuỳ chọn.
    """
    et = pd.Timestamp("2026-08-10 22:00", tz=ET_TZ)
    host = et.tz_convert("Asia/Ho_Chi_Minh")
    assert host.normalize().tz_localize(None) != et.normalize().tz_localize(None)
    # ngày ET là 08-10; giờ máy đã sang 08-11
    assert et.normalize().tz_localize(None) == pd.Timestamp("2026-08-10")
    assert host.normalize().tz_localize(None) == pd.Timestamp("2026-08-11")

    r = _runner(pd.Timestamp("2026-08-10"))          # đúng: neo ET
    assert r._stop_deferred(_P(SWING, "2026-08-10")) is True
    r_bad = _runner(pd.Timestamp("2026-08-11"))      # sai: neo giờ máy
    assert r_bad._stop_deferred(_P(SWING, "2026-08-10")) is False   # đặt stop sớm 1 ngày


def test_default_today_is_read_in_et():
    """Không truyền `today` thì mặc định phải là ngày ET, không phải ngày máy."""
    r = FuturesRunner.__new__(FuturesRunner)
    r._today = pd.Timestamp.now(tz=ET_TZ).normalize().tz_localize(None)
    assert r._today == pd.Timestamp.now(tz=ET_TZ).normalize().tz_localize(None)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
