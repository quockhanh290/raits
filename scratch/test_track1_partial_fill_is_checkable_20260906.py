"""Một lần khớp một phần phải đối chiếu được với ý định. TỆP MỚI.

Vì sao tệp này tồn tại
----------------------
Bản rà runner xếp lỗi "khớp một phần" vào diện để lại, và lý do đo được là đúng — cho đường
cũ: mỗi lệnh một hợp đồng, mà lệnh thị trường một hợp đồng thì không khớp một phần được.

Track 1 không đi qua đường đó. Sleeve Stress gửi **7 hợp đồng MNQ**, và số lượng đi trên chính
dòng tín hiệu chứ không lấy từ hằng số. Nên tiền đề giữ lỗi ấy ở mức "để lại" không theo sang.

Đo được trước bản sửa, với một môi giới trả về khớp 3 trên 7 đã đặt:

    nhật ký ghi   filled_qty=3   qty=0

Ba hợp đồng trên không có gì. Nhật ký ĐÃ định nghĩa `qty` đúng để bắt trường hợp này — tài
liệu của trường nói thẳng là số hợp đồng "trước đây chỉ ngụ ý trong lệnh và mất trên đường vào
nhật ký, khiến một lần khớp một phần không thể đối chiếu với ý định" — và không ai điền nó.
Trường có, mục đích ghi rõ, chưa được nối vào.

Cái các phép kiểm dưới đây ghim
-------------------------------
Không phải "khớp một phần được xử lý đúng" — đường từ lần khớp sang sổ sang lệnh dừng chưa
tồn tại, nên không có gì để ghim về nó. Chúng ghim thứ phải đúng TRƯỚC khi đường đó được nối:
**số đã đặt và số đã khớp cùng nằm trên một dòng, nên phần thiếu là một phép trừ chứ không
phải một suy đoán.**

Không gửi lệnh thật, không kết nối, không cần Gateway. Môi giới là đồ giả và nó không đi ra
đâu cả — đó là toàn bộ lý do trường hợp này kiểm được hôm nay thay vì sau lệnh thật đầu tiên.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_order_journal as J            # noqa: E402
from global_index import track1_order_state as st             # noqa: E402
from global_index import track1_paper_executor as X           # noqa: E402
from global_index import track1_signal_layer as T             # noqa: E402
from global_index.broker import Fill                          # noqa: E402

DAY = "2026-09-04"

#: Kích thước thật của sleeve Stress. Không phải con số bịa cho test: nó là số hợp đồng
#: sleeve ấy gửi, và là lý do lập luận "một hợp đồng không khớp một phần được" không dùng
#: được ở đây.
STRESS_QTY = 7


class ArmedGate:
    allow_orders = True


class PartialBroker:
    """Nhận bao nhiêu cũng chỉ khớp `filled`. Không đi ra đâu."""

    def __init__(self, filled: int):
        self.filled = filled
        self.calls: list = []

    def send_order(self, order, **kw):
        self.calls.append(order)
        return Fill(inst=order.inst, action="OPEN", direction="long",
                    contracts=order.contracts, cluster=order.cluster,
                    status="PARTIAL", filled_qty=self.filled, avg_price=20100.25)

    def get_positions(self): return []
    def get_order_status(self, *a, **k): return None
    def cancel_order(self, *a, **k): return None
    def place_stop(self, *a, **k): return None


def _decision(qty: int = STRESS_QTY):
    c = T.Candidate(trade_id="partial_probe", sleeve="roska4_stress", instrument="MNQ",
                    direction="long", qty=qty, risk_dollars=250.0,
                    entry_time=f"{DAY} 10:35:00", meta={})
    return T.Decision(candidate=c, verdict=T.TAKE)


def _run(tmp_path, *, ordered=STRESS_QTY, filled=3):
    broker = PartialBroker(filled)
    ex = X.Track1OrderExecutor(broker=broker, gate=ArmedGate(), journal_root=tmp_path,
                               now_fn=lambda: dt.datetime(2026, 9, 4, 14, 35))
    fill = ex.open_position(_decision(ordered), ref_day=DAY, slot_id="PARTIAL_PROBE")
    rows, invalid = J.read(root=tmp_path, day=DAY)
    assert not invalid, invalid
    return broker, fill, rows


# ── 1. tiền đề: sleeve này thật sự gửi nhiều hơn một hợp đồng ────────────────

def test_the_route_sends_more_than_one_contract_so_a_partial_fill_is_reachable(tmp_path):
    """Nếu điều này thành sai thì mọi phép kiểm dưới đây mất lý do tồn tại — và đó là
    thông tin, không phải phiền toái. Nó ghim chính tiền đề mà bản rà cũ dựa vào."""
    broker, _fill, _rows = _run(tmp_path)
    assert broker.calls, "không có lệnh nào được gửi; phép kiểm không đo gì cả"
    assert broker.calls[0].contracts > 1, (
        "lệnh chỉ một hợp đồng thì không khớp một phần được, và cả tệp này thành thừa")


# ── 2. cái chính: hai con số phải cùng nằm trên một dòng ─────────────────────

def test_the_ordered_size_is_on_the_row_beside_the_filled_size(tmp_path):
    """Dòng kết cục phải mang CẢ số đã đặt lẫn số đã khớp.

    Trước bản sửa dòng này đọc ra `filled_qty=3, qty=0` — ba hợp đồng trên không có gì.
    """
    _broker, _fill, rows = _run(tmp_path, ordered=STRESS_QTY, filled=3)
    terminal = [r for r in rows if r.state in st.TERMINAL]
    assert terminal, "không có dòng kết cục nào; không có gì để kiểm"
    row = terminal[-1]
    assert row.state == st.PARTIAL, row.state
    assert row.filled_qty == 3, row.filled_qty
    assert row.qty == STRESS_QTY, (
        f"dòng ghi qty={row.qty}, phải là {STRESS_QTY} — thiếu số đã đặt thì phần chưa "
        f"khớp không tính ra được, và đó chính là con số quyết định lệnh dừng đặt theo mấy")


def test_the_shortfall_is_arithmetic_rather_than_an_inference(tmp_path):
    """Phần thiếu phải lấy ra được từ chính một dòng, không cần đi tìm lệnh gốc."""
    _broker, _fill, rows = _run(tmp_path, ordered=STRESS_QTY, filled=3)
    row = [r for r in rows if r.state in st.TERMINAL][-1]
    assert row.qty - row.filled_qty == 4, (
        f"phần chưa khớp tính ra {row.qty - row.filled_qty}, phải là 4")


# ── 3. mọi trạng thái đều mang kích thước, kể cả khi không ai trả lời ────────

def test_every_row_carries_the_size_including_the_ones_before_any_answer(tmp_path):
    """Một dòng ý định mà không ai trả lời vẫn phải nói nó lớn bằng nào.

    Đây là điều kiện để một kết cục KHÔNG BIẾT có kích thước. Một lệnh có thể đang sống ở
    môi giới mà mình không nhìn thấy; "không biết bao nhiêu hợp đồng" và "không biết kết cục"
    là hai chuyện, và gộp lại thì lệnh mồ côi không ước lượng được rủi ro.
    """
    _broker, _fill, rows = _run(tmp_path)
    assert len(rows) >= 2, rows
    for r in rows:
        assert r.qty == STRESS_QTY, (
            f"dòng {r.state!r} ghi qty={r.qty}; mọi dòng phải mang kích thước nó nói về")


def test_a_full_fill_still_records_both_numbers_and_they_agree(tmp_path):
    """Đối chứng: khớp đủ thì hai số bằng nhau. Không có nó, một bản sửa gán cứng
    `qty = filled_qty` sẽ làm mọi phép kiểm trên xanh mà không kiểm gì."""
    _broker, _fill, rows = _run(tmp_path, ordered=STRESS_QTY, filled=STRESS_QTY)
    row = [r for r in rows if r.state in st.TERMINAL][-1]
    assert row.qty == STRESS_QTY and row.filled_qty == STRESS_QTY
    assert row.qty - row.filled_qty == 0


def test_qty_comes_from_the_order_not_from_the_fill(tmp_path):
    """Ghim đúng NGUỒN của con số.

    Nếu `qty` được lấy từ kết quả trả về thay vì từ lệnh đã gửi, thì nó luôn bằng số đã
    khớp và phần thiếu luôn bằng 0 — một phép kiểm không bao giờ đỏ. Khớp 0 trên 7 là
    trường hợp tách hai nguồn ra xa nhau nhất.
    """
    _broker, _fill, rows = _run(tmp_path, ordered=STRESS_QTY, filled=0)
    row = [r for r in rows if r.state in st.TERMINAL][-1]
    assert row.filled_qty == 0, row.filled_qty
    assert row.qty == STRESS_QTY, (
        f"qty={row.qty} với 0 hợp đồng khớp — con số đang bị lấy từ kết quả trả về "
        f"chứ không phải từ lệnh đã gửi")
