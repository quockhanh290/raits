"""Giờ đặt STP hoãn là bao nhiêu — và vì sao nó không được trôi trong im lặng.

`_stop_deferred` chỉ nói "hoãn cho tới khi qua ngày vào lệnh". Nó KHÔNG nói mấy giờ.
Giờ thật là **hệ quả phụ**: B4 đặt STP, B4 chạy trong `FuturesRunner.__init__`, nên việc
đặt xảy ra ở **job nào dựng runner đầu tiên trong ngày**. Không ai thiết kế mốc đó.

Tôi đã đoán sai hai lần bằng cách đọc code:
  lần 1 — tưởng 14:05 (slot giao dịch)      → thực ra 09:31 (run_maxhold_exit dựng runner)
  lần 2 — tưởng 09:31                        → thực ra 01:10 (slot đêm NKD dựng trước)

Lần 2 chỉ lộ ra khi có người hỏi. Cả hai lần đều là đọc một chỗ rồi kết luận, không kiểm
job nào chạy trước.

Giờ đặt QUAN TRỌNG — đo được (model_stop_activation_gap.py, cổng đối chiếu từng lệnh,
Rổ 4 2018–2026):

    engine (ranh giới ngày)   +$47.166   MaxDD $8.234
    01:10 ET  (hiện tại)      +$49.885   MaxDD $8.234   <- gần như trùng engine
    09:31 ET                  +$92.666   MaxDD $7.144
    không có stop             -$46.369   MaxDD $60.138

Chênh giữa 01:10 và 09:31 là **$42.781**. Nên nếu giờ đặt trôi mà không ai biết, hệ thống
đổi hành vi ở mức đó — im lặng, không log, không guard. Đó là thứ các test dưới đây chốt.

⚠️ Các số trên KHÔNG phải lý do để chuyển sang 09:31. Chọn mốc theo đỉnh P&L backtest là
curve fitting; 01:10 ít nhất còn trùng luật engine. Muốn đổi thì phải kiểm định tử tế
trước (quét nhiều mốc, tách năm, kiểm vault).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("apscheduler")

from futures.circuit_breaker import CircuitBreaker
from global_index.broker import BrokerPosition, MockBroker
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner
from global_index.run_scheduler import make_scheduler

_ROOT = Path(__file__).resolve().parents[1]
DAY1, DAY2 = pd.Timestamp("2024-03-11"), pd.Timestamp("2024-03-12")
SWING = "roska4_swing"

# Job dựng FuturesRunner (→ chạy B4 → đặt STP hoãn). heartbeat chỉ ghi log; preflight
# chỉ cập nhật parquet + spy csv. Mọi job còn lại đi qua run_live_day hoặc
# run_maxhold_exit, cả hai đều dựng runner.
_NO_RUNNER = {"heartbeat", "preflight"}

PLACEMENT_HOUR, PLACEMENT_MIN = 1, 10        # nkd_night_0110


class _Rec(MockBroker):
    """Broker giữ sẵn vị thế MES — B4 chỉ coi một vị thế là cần bảo vệ khi BROKER xác
    nhận nó đang mở (`broker_key.get(...) > 0`). Không có nó thì B4 im, và test sẽ xanh
    vì lý do sai."""

    def __init__(self):
        super().__init__({}, 50_000.0)
        self.stp_calls: list = []
        self._positions = [BrokerPosition(inst="MES", direction="LONG", contracts=1,
                                          cluster=SWING, entry_day=DAY1)]

    def place_stop(self, inst, direction, contracts, stop_price, cluster):
        self.stp_calls.append(dict(inst=inst, stop_price=stop_price))
        return f"stp-{inst}"


def _guard():
    return MultiClusterGuard(clusters={
        SWING: ClusterBudget(SWING, max_gross_pct=0.05, max_net_pct=0.044),
        "global_nkd": ClusterBudget("global_nkd", max_gross_pct=0.02, max_net_pct=0.02),
    }, account=50_000.0)


def _state_file(tmp_path):
    import json
    f = tmp_path / "pos.json"
    f.write_text(json.dumps({
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1, "risk_dollars": 500.0,
            "cluster": SWING, "entry_day": str(DAY1.date()), "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False, "entry_price": 5000.0,
            "stop_price": 4950.0, "stop_order_id": None,
        }],
        "breaker": {},
    }))
    return f


def _hhmm(job):
    f = {str(x.name): str(x) for x in job.trigger.fields}
    try:
        return int(f["hour"]), int(f["minute"])
    except (KeyError, ValueError):
        return None


def _jobs():
    sched = make_scheduler(port=4002, dry_run=True)
    return list(sched.get_jobs())


def test_the_stop_is_placed_by_init_not_by_run_day(tmp_path):
    """Đây là gốc của mọi thứ: B4 nằm trong __init__, nên việc đặt STP xảy ra ở JOB
    NÀO DỰNG RUNNER ĐẦU TIÊN — không phải ở slot giao dịch. Ai chuyển B4 sang run_day
    sẽ dời giờ đặt sang 14:05 mà không có gì báo."""
    b = _Rec()
    FuturesRunner(broker=b, guard=_guard(), contracts_by_inst={"MES": 1},
                  signal_fn=lambda d, x, h: ([], []),
                  breaker=CircuitBreaker(account=50_000.0),
                  positions_path=_state_file(tmp_path), today=DAY2)
    assert len(b.stp_calls) == 1, (
        f"B4 phải đặt STP ngay trong __init__, chưa gọi run_day. {b.stp_calls}")
    assert b.stp_calls[0]["stop_price"] == 4950.0


def test_b4_is_not_cluster_filtered(tmp_path):
    """Slot đêm chạy `--clusters nkd`, nhưng cổng cluster nằm ở `generate_today_signals`
    — nó chặn việc SINH LỆNH, không chặn B3/B4. Nhờ vậy vị thế Rổ 4 vẫn được đặt stop
    lúc 01:10.

    Thêm một bộ lọc cluster vào B4 sẽ dời giờ đặt của Rổ 4 từ 01:10 sang 09:31 — đo
    được là $42.781 khác biệt — và đồng thời làm B4 thôi bắt vị thế trần thật trong
    quãng đó. Nếu có ai cố tình muốn thế thì phải sửa test này, tức là phải nhìn thấy
    hệ quả."""
    b = _Rec()
    FuturesRunner(broker=b, guard=_guard(), contracts_by_inst={"MES": 1},
                  signal_fn=lambda d, x, h: ([], []),
                  breaker=CircuitBreaker(account=50_000.0),
                  positions_path=_state_file(tmp_path), today=DAY2)
    assert [c["inst"] for c in b.stp_calls] == ["MES"], (
        "vi the roska4_swing phai duoc dat stop du run dang gate sang nkd")


def test_the_first_runner_building_job_is_0110_et():
    """Giờ đặt STP = giờ của job dựng runner sớm nhất. Hiện là slot đêm NKD 01:10 ET.

    Test này là thứ lẽ ra đã chặn hai lần đoán sai của tôi. Nếu ai bỏ slot đêm (ví dụ
    gỡ NKD khỏi hệ thống), giờ đặt của Rổ 4 tự lùi về 09:31 — một sleeve đổi hành vi
    vì một sleeve khác bị gỡ."""
    times = [(_hhmm(j), j.id) for j in _jobs()
             if j.id not in _NO_RUNNER and _hhmm(j) is not None]
    assert times, "khong doc duoc gio cua job nao — test rong"
    earliest, jid = min(times)
    assert earliest == (PLACEMENT_HOUR, PLACEMENT_MIN), (
        f"job dung runner som nhat la {jid} luc {earliest} — gio dat STP hoan da DOI. "
        f"Do duoc: 01:10 cho +$49.885 (~= engine), 09:31 cho +$92.666. Doi gio nay la "
        f"doi hanh vi he thong o muc $42.781, phai la quyet dinh co chu dich.")


def test_maxhold_is_the_fallback_that_builds_a_runner():
    """Khi slot đêm trượt (thiếu bản ghi pre-flight ngày trước), job MAX_HOLD 09:31 là
    chỗ đặt STP. Nó chỉ làm được vậy vì dựng FuturesRunner — một liên kết không hiển
    nhiên khi đọc tên file."""
    src = (_ROOT / "global_index" / "run_maxhold_exit.py").read_text(encoding="utf-8")
    assert "FuturesRunner(" in src, (
        "run_maxhold_exit thoi khong dung FuturesRunner => khong con duong du phong "
        "dat STP hoan; no se lui toi slot 14:05")
    assert any(_hhmm(j) == (9, 31) for j in _jobs() if j.id == "maxhold_exit")


def test_no_job_between_placement_and_the_trading_window_is_assumed():
    """Chốt lại rằng giờ đặt là MỘT giá trị xác định, không phải "job nào chạy trước thì
    đặt" một cách ngẫu nhiên: mọi job dựng runner khác đều phải MUỘN hơn 01:10."""
    times = sorted({_hhmm(j) for j in _jobs()
                    if j.id not in _NO_RUNNER and _hhmm(j) is not None})
    assert times[0] == (PLACEMENT_HOUR, PLACEMENT_MIN)
    assert all(t > (PLACEMENT_HOUR, PLACEMENT_MIN) for t in times[1:])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
