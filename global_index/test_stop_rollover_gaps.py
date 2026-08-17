"""Ba lỗ hổng stop tìm ra ở lượt soi lại (2026-08-10) — hai ở C2 rollover, một ở classify.

Chúng không lộ ra ở lượt sửa trước vì lượt đó soi câu hỏi *"stop này thuộc vị thế nào"*.
Ba cái ở đây thuộc câu hỏi khác: *"chuyện gì xảy ra khi hợp đồng đổi tháng"*.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.check_open_orders import Stop, classify

TODAY = "2026-08-11"
OLD = "2026-08-03"


def _p(inst="MES", direction="LONG", cluster="roska4_swing", contracts=1,
       stop_order_id=None, entry_day=OLD):
    return {"inst": inst, "direction": direction, "cluster": cluster,
            "contracts": contracts, "stop_price": 7000.0,
            "stop_order_id": stop_order_id, "entry_day": entry_day}


# ── classify: lệnh MÌNH GHI được nhận trước ──────────────────────────────────

def test_the_position_claims_its_own_recorded_order_first():
    """Hình dạng sau rollover khi C2 huỷ KHÔNG thành công: hai STP cùng chiều trên cùng mã,
    khác tháng đáo hạn, và `live_positions.json` không ghi expiry nên side + size không tách
    được chúng.

    Nhận theo thứ tự danh sách sẽ trao cho vị thế cái đến trước — có thể là stop của hợp
    đồng đã chết — rồi báo stop THẬT là thừa, và repair_stops sẽ huỷ đúng cái đang bảo vệ."""
    stops = {"MES": [Stop("SELL", 11, 6900.0, 1),      # hợp đồng cũ, huỷ hụt
                     Stop("SELL", 22, 6950.0, 1)]}     # hợp đồng mới — cái thật
    rows = classify([_p(stop_order_id="22")], stops, today=TODAY)
    assert rows[0][0] == "OK"
    assert rows[0][3].order_id == 22, "vi the phai nhan dung lenh no ghi"
    assert [r[0] for r in rows[1:]] == ["HAZARD"]
    assert rows[1][3].order_id == 11, "lenh hop dong cu moi la cai thua"


def test_a_recorded_id_on_the_wrong_side_is_not_claimed():
    """Id đã ghi không phải giấy thông hành. Một STP SELL nằm dưới vị thế SHORT sẽ NHÂN ĐÔI
    vị thế — đúng hình dạng MYM ngày 2026-08-05."""
    stops = {"MES": [Stop("SELL", 11, 6900.0, 1)]}
    rows = classify([_p(direction="SHORT", stop_order_id="11")], stops, today=TODAY)
    assert rows[0][0] == "WRONG-WAY"


def test_a_stale_recorded_id_still_falls_back_to_side():
    """Id trỏ vào lệnh không còn tồn tại thì vẫn phải nhận stop đúng chiều đang chạy —
    nếu không, mọi trôi id sẽ thành NAKED giả."""
    stops = {"MES": [Stop("SELL", 99, 6900.0, 1)]}
    rows = classify([_p(stop_order_id="11")], stops, today=TODAY)
    assert rows[0][0] == "OK" and rows[0][3].order_id == 99


def test_the_recorded_order_counts_toward_coverage_not_beyond_it():
    """Lệnh mình ghi nhận trước, phần thiếu lấy tiếp theo chiều — nhưng không lấy quá."""
    stops = {"MES": [Stop("SELL", 11, 6900.0, 1), Stop("SELL", 22, 6950.0, 1),
                     Stop("SELL", 33, 6980.0, 1)]}
    rows = classify([_p(contracts=2, stop_order_id="33")], stops, today=TODAY)
    assert rows[0][0] == "OK"
    assert {c.order_id for c in [rows[0][3]]} <= {33}
    assert [r[0] for r in rows[1:]] == ["HAZARD"], "chi mot lenh du ra"


# ── C2 rollover ──────────────────────────────────────────────────────────────

class _Pos:
    """Stands in for OpenPos, and every field it declares is present.

    It used to name only the five attributes this file happened to read. When the roll
    path started asking for the contract month, the missing attribute raised inside the
    `except Exception` that wraps place_stop — so the stop was silently never placed and
    the failure surfaced as "no stop", not as a broken fake. That is the M3 defect
    exactly: a hand-rolled double drifting from the real type, with a broad except
    turning the mismatch into a wrong answer instead of a crash.

    Built from the dataclass rather than listed by hand, so the next field added to
    OpenPos cannot reopen the same hole.
    """

    def __init__(self, entry_day=OLD, stop_price=7000.0, stop_order_id="11"):
        import dataclasses
        from global_index.live_decision import OpenPos
        for f in dataclasses.fields(OpenPos):
            setattr(self, f.name,
                    None if f.default is dataclasses.MISSING else f.default)
        self.inst, self.direction, self.contracts = "MES", "LONG", 1
        self.cluster, self.entry_day = "roska4_swing", pd.Timestamp(entry_day)
        self.stop_price, self.stop_order_id = stop_price, stop_order_id


class _Fill:
    def __init__(self, px):
        self.avg_price = px


def _roll(pos, shift=40.0, deferred=False, accept=True):
    """Gọi THẲNG `FuturesRunner._roll_stop` — không chép lại logic.

    Bản đầu của file này dựng lại nhánh giá của C2 trong chính helper rồi assert lên nó,
    tức chỉ chứng minh bản chép là đúng với chính nó. Đó là lý do `_roll_stop` được tách
    ra khỏi `_handle_rollover`."""
    from global_index.runner import FuturesRunner
    r = FuturesRunner.__new__(FuturesRunner)
    r._stop_deferred = lambda _p, now=None: deferred
    placed = []

    class _B:
        @staticmethod
        def place_stop(inst, direction, contracts, stop_price, cluster, contract_month=None):
            placed.append(stop_price)
            return "new-77" if accept else ""

    r.broker = _B()
    r._roll_stop(pos, shift)
    return pos, placed


def test_the_rolled_level_is_recorded_even_when_the_order_is_refused():
    """Trước: `pos.stop_price` chỉ được ghi khi lệnh ĐƯỢC nhận. Bị từ chối thì mức của hợp
    đồng CŨ ở lại trên sổ, và B4 — vốn chỉ đặt khi "đã biết mức" — sẽ đặt mức cũ đó lên
    thang giá hợp đồng mới ở phiên sau. Sai đúng bằng khoảng chênh hai hợp đồng."""
    pos, _ = _roll(_Pos(), accept=False)
    assert pos.stop_price == 7040.0, "muc da dich phai o lai tren so du lenh bi tu choi"


def test_a_position_rolled_inside_its_window_is_not_armed_early():
    """Rollover không dời `entry_day`, nên cửa sổ hoãn không đổi. Đặt stop ở đây là vũ trang
    sớm cho đúng một vị thế, chỉ vì hợp đồng của nó tình cờ đổi tháng."""
    pos, placed = _roll(_Pos(), deferred=True)
    assert placed == [], "khong duoc dat stop trong cua so hoan"
    assert pos.stop_order_id is None
    assert pos.stop_price == 7040.0, "van phai ghi muc de B4 dat duoc o gio vu trang"


def test_a_normal_roll_still_places_at_the_shifted_level():
    pos, placed = _roll(_Pos())
    assert placed == [7040.0]
    assert pos.stop_order_id == "new-77" and pos.stop_price == 7040.0


def test_a_roll_with_no_recorded_level_places_nothing():
    """Không biết mức thì chỉ được kêu, không được đoán — đặt bừa một mức là đặt một lệnh
    thoát ở giá không ai tính."""
    pos, placed = _roll(_Pos(stop_price=None))
    assert placed == [] and pos.stop_price is None


def test_a_refused_placement_leaves_no_id_in_the_book():
    """Lúc `_roll_stop` được gọi, `_handle_rollover` đã huỷ stop cũ và xoá id — nên trạng
    thái vào là None. Lệnh mới bị từ chối thì phải VẪN là None: bịa một id vào đây là ghi
    bằng chứng sai, và khi đóng vị thế `cancel_order` sẽ huỷ một con ma rồi báo ORPHAN.

    Assertion cũ là `in (None, "11")` — nhận cả hai nên không khẳng định gì."""
    pos, placed = _roll(_Pos(stop_order_id=None), accept=False)
    assert placed == [7040.0], "van phai THU dat, chi la bi tu choi"
    assert pos.stop_order_id is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
