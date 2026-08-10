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
                  positions_path=_state_file(tmp_path), today=DAY2,
                  now=DAY2 + pd.Timedelta(hours=14, minutes=5))
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
                  positions_path=_state_file(tmp_path), today=DAY2,
                  now=DAY2 + pd.Timedelta(hours=14, minutes=5))
    assert [c["inst"] for c in b.stp_calls] == ["MES"], (
        "vi the roska4_swing phai duoc dat stop du run dang gate sang nkd")


def test_no_job_can_arm_a_sleeve_before_its_arm_time():
    """Thay cho hai test cũ, vốn khẳng định "giờ đặt STP = job dựng runner SỚM NHẤT".

    Tiền đề đó đúng cho tới `_ARM_BY_CLUSTER`: hồi đó vị từ chỉ so `entry_day == today`,
    nên vị thế được đặt stop ở job đầu tiên của ngày kế tiếp — tình cờ là slot đêm 01:10.
    Giờ thì `_stop_deferred` mới là thứ quyết định, và nó khai theo ĐỒNG HỒ CỦA SLEEVE.

    Bất biến mà hai test kia thực sự bảo vệ vẫn còn giá trị và mạnh hơn ở dạng này: **thêm
    một job vào lịch không được vũ trang sleeve nào sớm hơn giờ của chính nó**. Đó là điều
    khiến việc thêm lượt quét sửa stop trở nên an toàn — nếu không, mỗi job mới lại là một
    lần đổi hành vi hệ thống trong im lặng.

    Kiểm trên lịch THẬT, cả hai mùa, vì chênh ET↔JST đổi theo DST.
    """
    from global_index.runner import _ARM_BY_CLUSTER, ET_TZ, FuturesRunner
    r = FuturesRunner.__new__(FuturesRunner)

    class _P:
        def __init__(self, cluster, entry_day):
            self.cluster, self.entry_day = cluster, pd.Timestamp(entry_day)
            self.inst, self.direction, self.contracts = "X", "LONG", 1

    slots = sorted({_hhmm(j) for j in _jobs()
                    if j.id not in _NO_RUNNER and _hhmm(j) is not None})
    assert slots, "khong doc duoc gio cua job nao — test rong"

    for entry in ("2026-08-10", "2026-01-12"):        # EDT và EST
        d1 = pd.Timestamp(entry) + pd.Timedelta(days=1)
        for cluster, (tz, hh, mm) in _ARM_BY_CLUSTER.items():
            arm = (pd.Timestamp(f"{(d1).date()} {hh:02d}:{mm:02d}", tz=tz)
                   .tz_convert(ET_TZ).tz_localize(None))
            for sh, sm in slots:
                now = d1 + pd.Timedelta(hours=sh, minutes=sm)
                armed = not r._stop_deferred(_P(cluster, entry), now=now)
                assert armed == (now >= arm), (
                    f"{cluster} vao {entry}: slot {sh:02d}:{sm:02d} "
                    f"{'DAT' if armed else 'HOAN'} nhung gio vu trang la "
                    f"{arm.strftime('%H:%M')} ET")


def test_the_night_sweep_arms_nkd_earlier_in_winter_and_that_is_correct():
    """Ghi lại một thay đổi hành vi THẬT do lượt quét 00:20 gây ra, để nó không bị phát
    hiện lại như một điều bất ngờ.

    Mùa hè: 14:00 JST = 01:00 ET, nên 00:20 còn trong cửa sổ hoãn — không đổi gì.
    Mùa đông: 14:00 JST = 00:00 ET, nên 00:20 ĐẶT được stop, sớm hơn 01:10 trước đây.

    Đó là đi VỀ PHÍA luật chứ không rời xa: 00:20 ET mùa đông là 14:20 JST (20 phút sau
    mốc), còn 01:10 ET là 15:10 JST (70 phút sau). Rổ 4 không đổi ở cả hai mùa."""
    from global_index.runner import FuturesRunner
    r = FuturesRunner.__new__(FuturesRunner)

    class _P:
        def __init__(self, cluster, entry_day):
            self.cluster, self.entry_day = cluster, pd.Timestamp(entry_day)
            self.inst = "MNKD"

    at0020 = lambda e: pd.Timestamp(e) + pd.Timedelta(days=1, minutes=20)
    assert r._stop_deferred(_P("global_nkd", "2026-08-10"),
                            now=at0020("2026-08-10")) is True, "he: 00:20 phai con hoan"
    assert r._stop_deferred(_P("global_nkd", "2026-01-12"),
                            now=at0020("2026-01-12")) is False, "dong: 00:20 phai dat duoc"
    assert r._stop_deferred(_P("roska4_swing", "2026-01-12"),
                            now=at0020("2026-01-12")) is True, "Ro 4 khong duoc doi"


def test_maxhold_is_the_fallback_that_builds_a_runner():
    """Khi slot đêm trượt (thiếu bản ghi pre-flight ngày trước), job MAX_HOLD 09:31 là
    chỗ đặt STP. Nó chỉ làm được vậy vì dựng FuturesRunner — một liên kết không hiển
    nhiên khi đọc tên file."""
    src = (_ROOT / "global_index" / "run_maxhold_exit.py").read_text(encoding="utf-8")
    assert "FuturesRunner(" in src, (
        "run_maxhold_exit thoi khong dung FuturesRunner => khong con duong du phong "
        "dat STP hoan; no se lui toi slot 14:05")
    assert any(_hhmm(j) == (9, 31) for j in _jobs() if j.id == "maxhold_exit")


# `test_no_job_between_placement_and_the_trading_window_is_assumed` đã bị BỎ ở đây.
#
# Nó khẳng định mọi job dựng runner đều phải muộn hơn 01:10, để giờ đặt STP là "một giá trị
# xác định, không phải job nào chạy trước thì đặt". Tiền đề đó chết cùng `_ARM_BY_CLUSTER`:
# giờ đặt không còn do thứ tự job quyết định mà do vị từ `_stop_deferred`, khai theo đồng hồ
# của từng sleeve. Lượt quét sửa stop 00:20 làm nó đỏ, và nó đỏ vì đã lỗi thời chứ không
# phải vì có gì hỏng.
#
# Bất biến nó thực sự bảo vệ — thêm job mới không được đổi giờ vũ trang của sleeve nào —
# nằm ở `test_no_job_can_arm_a_sleeve_before_its_arm_time` phía trên, kiểm trên lịch thật và
# cả hai mùa DST, tức mạnh hơn bản cũ.


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
