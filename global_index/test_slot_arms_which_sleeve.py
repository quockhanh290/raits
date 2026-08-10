"""Slot nào đặt stop cho sleeve nào — chạy trên ĐÚNG lịch slot của scheduler.

`test_arm_time_per_sleeve.py` ghim giờ vũ trang. File này ghim thứ khác: hệ quả của giờ đó
khi gặp lịch chạy thật, tức câu hỏi người vận hành thực sự hỏi — *"1 giờ sáng thì cái gì
được đặt stop?"*

Câu trả lời có hai vế và chúng KHÁC NHAU:

    vị thế MỚI (vào lệnh hôm qua)   slot đêm 01:10 → chỉ NKD    slot 14:05 → chỉ Rổ 4
    vị thế CŨ (đã qua cửa sổ hoãn)  slot đêm 01:10 → CẢ HAI     slot 14:05 → cả hai

Vế thứ hai không phải rò rỉ. B4 chạy trong `FuturesRunner.__init__` nên mọi job dựng runner
đều chạy nó trên toàn bộ sổ, và cờ `--clusters` chỉ giới hạn `generate_today_signals` chứ
không giới hạn B4. Đó là chủ đích: B4 làm hai việc gộp một —

  * **vũ trang lần đầu**, phải theo sleeve, và `_stop_deferred` là cái quyết định;
  * **sửa chữa** một vị thế đã qua cửa sổ mà mất stop, KHÔNG được theo sleeve — bắt một vị
    thế Rổ 4 trần chờ tới 14:05 là 13 tiếng không có lý do.

Lọc B4 theo cluster sẽ giết vế hai; bỏ `_stop_deferred` sẽ giết vế một (slot đêm vũ trang
Rổ 4 sớm 13 tiếng — chênh +$41.505 → +$116.530 ngoài mẫu).

Xem `docs/futures/OPERATIONS.md`, mục "Khung thời gian đặt lệnh — CÓ CHỦ ĐÍCH".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.runner import FuturesRunner

SWING, NKD = "roska4_swing", "global_nkd"

# Đúng lịch của run_scheduler, theo thứ tự trong ngày. Giữ ở đây dưới dạng dữ liệu để test
# nói được câu "slot ĐẦU TIÊN" — điều mà một mốc lẻ không nói được.
NIGHT = [(1, m) for m in range(10, 60, 5)] + [(2, m) for m in range(0, 60, 5)]
DAY = [(9, 31), (14, 5)] + [(14, m) for m in range(10, 60, 5)] \
      + [(15, m) for m in range(0, 60, 5)]
SLOTS = NIGHT + DAY


class _P:
    def __init__(self, cluster, entry_day):
        self.cluster = cluster
        self.entry_day = pd.Timestamp(entry_day)
        self.inst = "MNKD" if cluster == NKD else "MES"
        self.direction, self.contracts = "LONG", 1
        self.stop_price, self.stop_order_id = 100.0, None


def _first_armed(cluster, entry_day, on_day):
    """Slot ĐẦU TIÊN trong ngày `on_day` mà B4 được phép đặt stop cho vị thế này."""
    r = FuturesRunner.__new__(FuturesRunner)
    p = _P(cluster, entry_day)
    d = pd.Timestamp(on_day)
    for hh, mm in SLOTS:
        if not r._stop_deferred(p, now=d + pd.Timedelta(hours=hh, minutes=mm)):
            return (hh, mm)
    return None


# ── vế 1: vũ trang lần đầu — mỗi slot chỉ chạm sleeve của nó ─────────────────

def test_a_fresh_nkd_position_arms_at_the_night_slot():
    assert _first_armed(NKD, "2026-08-10", "2026-08-11") == (1, 10)


def test_a_fresh_swing_position_skips_every_night_slot():
    """22 slot đêm đi qua mà không đụng vào vị thế Rổ 4 mở hôm qua. Đây là bản sửa hôm
    2026-08-10: vị từ cũ chỉ so `entry_day == today` nên slot 01:10 vũ trang cả hai."""
    got = _first_armed(SWING, "2026-08-10", "2026-08-11")
    assert got == (14, 5)
    assert got not in NIGHT


def test_a_fresh_swing_position_also_skips_the_0931_slot():
    """09:31 MAX_HOLD cũng dựng runner, nên cũng là một cơ hội đặt stop — và cũng phải
    trượt qua vị thế Rổ 4 còn trong cửa sổ."""
    assert _first_armed(SWING, "2026-08-10", "2026-08-11") != (9, 31)


# ── vế 2: sửa chữa — mọi slot chạm mọi sleeve ────────────────────────────────

def test_an_old_swing_position_is_repaired_at_the_night_slot():
    """KHÔNG phải rò rỉ giờ vũ trang. Vị thế đã qua cửa sổ mà mất stop phải được đặt lại ở
    slot gần nhất, kể cả slot đêm — chờ tới 14:05 là 13 tiếng trần vô cớ.

    Hệ quả vận hành: `B4 REPLACED: MES/roska4_swing` lúc 1 giờ sáng là guard đang làm việc,
    không phải lỗi; nó có nghĩa vị thế đó đã mất stop từ TRƯỚC."""
    assert _first_armed(SWING, "2026-08-03", "2026-08-11") == (1, 10)


def test_an_old_nkd_position_is_repaired_at_the_night_slot_too():
    assert _first_armed(NKD, "2026-08-03", "2026-08-11") == (1, 10)


# ── DST: giờ ET dịch, kết luận thì không ─────────────────────────────────────

@pytest.mark.parametrize("entry_day,next_day", [
    ("2026-08-10", "2026-08-11"),   # EDT — 14:00 JST = 01:00 ET
    ("2026-01-12", "2026-01-13"),   # EST — 14:00 JST = 00:00 ET
])
def test_the_answer_does_not_move_with_dst(entry_day, next_day):
    """Mùa đông mốc vũ trang NKD lùi về 00:00 ET, nhưng slot đầu tiên vẫn là 01:10 vì không
    có job nào giữa 00:00 và 01:10. Rổ 4 neo theo chính ET nên không dịch.

    Test này tồn tại để bản sửa "khai bằng múi giờ" không bị đổi ngược về giờ ET cố định —
    đổi ngược sẽ đúng nửa năm và sai nửa năm, mỗi năm hai lần, không có gì báo."""
    assert _first_armed(NKD, entry_day, next_day) == (1, 10)
    assert _first_armed(SWING, entry_day, next_day) == (14, 5)


def test_the_two_sleeves_never_arm_at_the_same_slot():
    """Bất biến gói gọn cả thiết kế: với vị thế MỚI, hai sleeve không bao giờ được vũ trang
    ở cùng một slot. Bằng nhau nghĩa là một sleeve đang chạy giờ của sleeve kia."""
    assert _first_armed(NKD, "2026-08-10", "2026-08-11") \
        != _first_armed(SWING, "2026-08-10", "2026-08-11")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
