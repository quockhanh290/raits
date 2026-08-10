"""Mọi tiến trình chạm tới STP phải dùng CHUNG một clientId.

IBKR chỉ nhận lệnh huỷ từ **chính clientId đã đặt lệnh**. `ibkr_broker.cancel_order` đã biết
điều này từ 2026-08-06 (chú thích: *"MYM #10 refused cancels from clientIds 1, 77 and 82,
then cancelled first try from 93, the id that placed it"*) — nhưng kiến trúc thì chưa:

    run_live_day      clientId 1    ĐẶT stop
    run_maxhold_exit  clientId 2    HUỶ stop khi đóng vị thế   ← không bao giờ thành công
    repair_stops      clientId 86   HUỶ orphan/wrong-way        ← không bao giờ thành công

Hệ quả không phải một cảnh báo bị bỏ lỡ mà là **mỗi lần MAX_HOLD đóng vị thế lại để lại một
STP mồ côi**, và MAX_HOLD chiếm 15% số lệnh. Một STP mồ côi khi khớp sẽ MỞ một vị thế ngược
chiều — nó không vô hại, nó là một lệnh vào không ai đặt.

Xảy ra thật 2026-08-10: MYM đóng lúc 09:31, `cancel_order('12')` thất bại, lệnh BUY STP treo
ở 54709.00 suốt buổi. Không log nào nhắc tới nó (xem `test_run_echoes_critical.py`), và chỉ
lộ ra khi đi hỏi thẳng IBKR. Huỷ được ngay lần đầu sau khi nối lại bằng đúng clientId chủ.

Test này rẻ và thô — nó đọc mã nguồn. Nhưng lỗi nó chặn thì không rẻ, và không có test đơn vị
nào bắt được vì đó là hành vi của IBKR chứ không phải của mã ta viết.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_GI = Path(__file__).resolve().parents[1] / "global_index"

# Những tiến trình ĐẶT hoặc HUỶ stop. Phải cùng một id.
STOP_TOUCHING = ["run_live_day.py", "run_maxhold_exit.py", "run_stop_repair.py"]

# Chỉ ĐỌC, không bao giờ chạm order — được phép dùng id riêng để khỏi đá nhau.
READ_ONLY = ["check_open_orders.py"]


def _default_client_id(fname: str) -> int:
    src = (_GI / fname).read_text(encoding="utf-8")
    m = re.search(r'"--client-id"[^)]*?default=(\d+)', src, re.S)
    assert m, f"{fname}: khong tim thay default cua --client-id"
    return int(m.group(1))


def test_every_stop_touching_process_shares_one_client_id():
    """Bất biến chính. Lệch nhau một chữ số là mỗi lần đóng vị thế để lại một lệnh mồ côi."""
    ids = {f: _default_client_id(f) for f in STOP_TOUCHING}
    assert len(set(ids.values())) == 1, (
        f"clientId lech nhau giua cac tien trinh dat/huy stop: {ids}. "
        "IBKR chi nhan lenh huy tu clientId da dat lenh.")


def test_that_shared_id_is_the_runners():
    """Phải là id của runner, vì runner là nơi ĐẶT phần lớn stop. Đổi cả cụm sang một id
    khác thì mọi stop đã đặt trước đó thành không huỷ được."""
    assert _default_client_id("run_live_day.py") == 1
    for f in STOP_TOUCHING:
        assert _default_client_id(f) == 1, f


def test_read_only_tools_may_keep_their_own_id():
    """Nửa còn lại: công cụ chỉ đọc KHÔNG được ép về id 1 — chạy nó khi scheduler đang sống
    sẽ đá runner ra khỏi Gateway."""
    for f in READ_ONLY:
        assert _default_client_id(f) != 1, f


def test_repair_stops_keeps_its_own_id_but_says_why_a_cancel_failed():
    """`repair_stops` là công cụ tay, chạy với scheduler đã dừng, và nó phải huỷ được lệnh do
    BẤT KỲ id nào đặt — nên nó không thể có một id đúng cố định. Bù lại, khi huỷ hụt nó phải
    chỉ ra đúng cách chạy lại; nếu không, người vận hành chỉ thấy 'FAILED' và không biết là
    do sai chủ sở hữu."""
    src = (_GI / "repair_stops.py").read_text(encoding="utf-8")
    assert "--client-id N --execute" in src, \
        "huy hut ma khong dua lenh chay lai — nguoi van hanh se khong doan ra la sai chu"


def test_cancel_order_names_the_owning_client():
    """`cancel_order` phải nêu TÊN chủ sở hữu khi huỷ hụt. Đó là thứ biến 'nó hỏng' thành
    một chỉ dẫn thi hành được."""
    src = (_GI / "ibkr_broker.py").read_text(encoding="utf-8")
    assert "placed by clientId=" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
