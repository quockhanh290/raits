"""Giờ vũ trang stop là RIÊNG cho từng sleeve — không sleeve nào dùng giờ của sleeve kia.

Một hằng số duy nhất — **14 giờ sau ranh giới ngày phiên của chính sleeve đó** — nhưng vì
hai sleeve chạy hai đồng hồ khác nhau nên nó rơi vào hai giờ ET khác nhau:

    roska4_swing   14:00 America/New_York  → job đặt: slot 14:05 ET
    global_nkd     14:00 Asia/Tokyo         → job đặt: slot đêm 01:10 ET

Khai bằng MÚI GIỜ, không phải giờ ET cố định: chênh lệch ET↔JST đổi theo DST (hè 13h,
đông 14h), nên "01:00 ET" đúng vào mùa hè nhưng thành 15:00 JST vào mùa đông.

Con số 14h không phải đỉnh của một bảng: hai phép walk-forward ĐỘC LẬP (Rổ 4 và MNKD,
hai đồng hồ, hai bộ dữ liệu) đều hội tụ về nó — Rổ 4 h*=14h ở 6/7 năm, MNKD 7/7.

Vì sao phải có test này: vị từ cũ chỉ so `entry_day == today`, nên CẢ HAI sleeve đều được
đặt stop ở job đầu tiên của ngày kế tiếp — tình cờ là slot đêm 01:10. Đúng cho NKD
(14h JST), sai cho Rổ 4 (mới 1,17h sau ranh giới ngày ET). Đo được khoảng chênh:
Rổ 4 ở 1,17h cho +$41.505 ngoài mẫu, ở 14h cho +$116.530.

Rò giờ giữa hai sleeve không sinh lỗi nào — nó chỉ làm một sleeve mất tiền trong im lặng.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.runner import _ARM_BY_CLUSTER, FuturesRunner

SWING, NKD, STRESS = "roska4_swing", "global_nkd", "roska4_stress"
ENTRY = pd.Timestamp("2026-08-10")          # thứ Hai


class _P:
    def __init__(self, cluster, entry_day=ENTRY, inst="MES"):
        self.cluster, self.inst = cluster, inst
        self.entry_day = None if entry_day is None else pd.Timestamp(entry_day)
        self.direction, self.contracts = "SHORT", 1
        self.stop_price, self.stop_order_id = 7769.03, None


def _r():
    return FuturesRunner.__new__(FuturesRunner)


def _at(hh, mm=0, day_offset=1):
    """Mốc thời gian ET, mặc định là ngày SAU ngày vào lệnh."""
    return ENTRY + pd.Timedelta(days=day_offset) + pd.Timedelta(hours=hh, minutes=mm)


# ── Rổ 4: vũ trang 14:00 ET ──────────────────────────────────────────────────

def test_swing_still_deferred_at_the_night_slot():
    """01:10 ET là giờ ĐÚNG của NKD. Áp nó cho Rổ 4 là bug cũ — mất $75k ngoài mẫu."""
    assert _r()._stop_deferred(_P(SWING), now=_at(1, 10)) is True


def test_swing_still_deferred_at_maxhold_and_stress_slots():
    """09:31 và 10:20 cũng chưa tới giờ của Rổ 4."""
    assert _r()._stop_deferred(_P(SWING), now=_at(9, 31)) is True
    assert _r()._stop_deferred(_P(SWING), now=_at(10, 20)) is True


def test_swing_arms_at_the_first_trading_slot():
    """14:05 — job đầu tiên sau 14:00 ET."""
    assert _r()._stop_deferred(_P(SWING), now=_at(13, 59)) is True
    assert _r()._stop_deferred(_P(SWING), now=_at(14, 5)) is False


# ── NKD: vũ trang 01:00 ET (= 14:00 JST) ─────────────────────────────────────

def test_nkd_arms_at_the_night_slot():
    """NKD đã đúng sẵn — slot đêm rơi vào 14:10 JST. Test này giữ nó khỏi bị dời."""
    p = _P(NKD, inst="MNKD")
    assert _r()._stop_deferred(p, now=_at(0, 59)) is True
    assert _r()._stop_deferred(p, now=_at(1, 10)) is False


def test_nkd_is_not_pushed_to_the_swing_hour():
    """Nếu ai đó áp giờ Rổ 4 cho NKD, NKD mất ~$3.900 (14,17h -> 27,08h trên đồng hồ
    Tokyo). Chốt bằng cách khẳng định NKD ĐÃ vũ trang trước 14:00 ET."""
    assert _r()._stop_deferred(_P(NKD, inst="MNKD"), now=_at(12, 0)) is False


# ── không rò giữa hai sleeve ─────────────────────────────────────────────────

@pytest.mark.parametrize("hh,mm,swing_deferred,nkd_deferred", [
    (0, 30, True,  True),    # trước cả hai
    (1, 10, True,  False),   # slot đêm: NKD vũ trang, Rổ 4 CHƯA
    (9, 31, True,  False),
    (14, 5, False, False),   # slot giao dịch: cả hai đã vũ trang
])
def test_the_two_sleeves_arm_at_different_times(hh, mm, swing_deferred, nkd_deferred):
    """Bảng này LÀ luật. Mỗi ô sai là một sleeve chạy giờ của sleeve kia."""
    r = _r()
    assert r._stop_deferred(_P(SWING), now=_at(hh, mm)) is swing_deferred
    assert r._stop_deferred(_P(NKD, inst="MNKD"), now=_at(hh, mm)) is nkd_deferred


def test_stress_is_in_neither_table():
    """STRESS_MID không hoãn — adapter của nó xét stop ngay từ bar vào lệnh."""
    assert STRESS not in _ARM_BY_CLUSTER
    assert _r()._stop_deferred(_P(STRESS), now=_at(0, 30)) is False


def test_the_arm_table_holds_one_row_per_deferred_sleeve():
    """Thêm sleeve mới vào tập hoãn mà quên khai giờ => nó rơi vào `arm is None` và
    KHÔNG được hoãn. Sai an toàn (đặt stop ngay), nhưng phải thấy được."""
    from global_index.runner import _DEFERRED_STOP_CLUSTERS
    assert set(_ARM_BY_CLUSTER) == set(_DEFERRED_STOP_CLUSTERS)


# ── các cạnh vẫn phải giữ ────────────────────────────────────────────────────

def test_same_day_is_always_deferred_for_both():
    """Ngày vào lệnh: chưa sleeve nào vũ trang, kể cả sau giờ của mình."""
    r = _r()
    assert r._stop_deferred(_P(SWING), now=_at(15, 0, day_offset=0)) is True
    assert r._stop_deferred(_P(NKD, inst="MNKD"), now=_at(3, 0, day_offset=0)) is True


def test_an_old_position_is_never_deferred():
    assert _r()._stop_deferred(_P(SWING, entry_day="2026-07-01"), now=_at(1, 10)) is False


def test_unknown_entry_day_is_protected():
    assert _r()._stop_deferred(_P(SWING, entry_day=None), now=_at(1, 10)) is False


def test_an_entry_day_in_the_future_is_protected():
    """Trạng thái hỏng, không phải cửa sổ — hoãn tiếp sẽ để vị thế trần vô thời hạn."""
    assert _r()._stop_deferred(_P(SWING, entry_day=ENTRY + pd.Timedelta(days=3)),
                               now=_at(1, 10)) is False


def test_neither_sleeve_arms_at_a_session_boundary():
    """Vũ trang tại ranh giới phiên là hố đã đo: nghỉ CME 17:00–18:00 ET làm tỉ lệ thoát
    GAP vọt từ 6% lên 40% và P&L sụp từ +$128.863 xuống −$1.091. NKD có hố tương tự tại
    khoảng nghỉ 06:00–08:45 JST.

    Kiểm trên ĐỒNG HỒ CỦA CHÍNH SLEEVE — kiểm bằng giờ ET sẽ bỏ sót NKD."""
    # Đo từ chính parquet, không đoán theo giờ sàn: NKD có ĐÚNG MỘT khoảng nghỉ, và
    # nó là nghỉ bảo trì CME 17:00–18:00 ET nhìn trên đồng hồ Tokyo — bar mở lại lúc
    # 07:00 JST (mùa hè) hoặc 08:00 JST (mùa đông), nên dải chắn phải phủ cả hai.
    # Bản đầu tôi khai thêm một khoảng nghỉ 15:15–16:30 JST theo giờ OSE — dữ liệu cho
    # thấy nó KHÔNG tồn tại ở hợp đồng này (mật độ bar lúc 14:00 và 15:00 đều bình
    # thường). Một hằng số bịa trong test chỉ tạo ra cảm giác an toàn.
    breaks = {"America/New_York": [(17, 18)],      # nghỉ CME, đo từ dữ liệu Rổ 4
              "Asia/Tokyo": [(6, 8.5)]}            # cùng khoảng nghỉ đó, giờ Tokyo
    for cluster, (tz, hh, mm) in _ARM_BY_CLUSTER.items():
        t = hh + mm / 60
        for lo, hi in breaks.get(tz, []):
            assert not (lo <= t < hi), f"{cluster} vu trang trong nghi phien {lo}-{hi} {tz}"


@pytest.mark.parametrize("entry_day,arm_et_hour", [
    ("2026-07-15", 1),    # EDT: JST = ET+13 -> 14:00 JST = 01:00 ET
    ("2026-01-15", 0),    # EST: JST = ET+14 -> 14:00 JST = 00:00 ET
])
def test_nkd_arm_time_follows_dst(entry_day, arm_et_hour):
    """Khai "01:00 ET" cố định thì mùa đông thành 15:00 JST — trôi một tiếng khỏi luật,
    mỗi năm hai lần, không có gì báo. Neo theo Asia/Tokyo thì giờ ET tự dịch.

    Hiện tại việc này CHƯA đổi hành vi (không có job nào giữa 00:00 và 01:10 ET, nên cả
    hai cách đều rơi vào slot 01:10). Nó sẽ đổi ngay khi ai đó thêm một slot sớm hơn."""
    r = _r()
    p = _P(NKD, entry_day=entry_day, inst="MNKD")
    d1 = pd.Timestamp(entry_day) + pd.Timedelta(days=1)
    assert r._stop_deferred(p, now=d1 + pd.Timedelta(hours=arm_et_hour,
                                                     minutes=-1)) is True
    assert r._stop_deferred(p, now=d1 + pd.Timedelta(hours=arm_et_hour)) is False


def test_swing_arm_time_does_not_move_with_dst():
    """Rổ 4 neo theo chính ET nên DST không dịch nó — kiểm để chắc việc khai bằng múi
    giờ không vô tình làm sleeve này trôi."""
    r = _r()
    for d in ("2026-07-15", "2026-01-15"):
        p = _P(SWING, entry_day=d)
        d1 = pd.Timestamp(d) + pd.Timedelta(days=1)
        assert r._stop_deferred(p, now=d1 + pd.Timedelta(hours=13, minutes=59)) is True
        assert r._stop_deferred(p, now=d1 + pd.Timedelta(hours=14)) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
