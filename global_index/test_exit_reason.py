"""global_index/test_exit_reason.py — every close records which path it took.

The exit_path_coverage gate read "Chandelier 0 | MAX_HOLD 0 | STP 0" against four CLOSE
fills that had already happened. It was not short of samples; nothing was writing the
samples down. Three separate holes:

  ER1-ER3  the signal-exit CLOSE row carried no exit_reason, because the engine's own
           reason (CHANDELIER / GAP / MAX_HOLD) was discarded at `_, pos = backtest(...)`
  ER4-ER5  run_maxhold_exit booked the money and emitted an event but never wrote a
           trade-log row at all
  ER6      _retry_pending_exits, likewise

ER7-ER9 hold the line that the fix stays observational: it must not be able to change a
decision, because it sits on the live signal path.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futures.circuit_breaker import CircuitBreaker
from futures.swing_tf import SwingTFEngine
from global_index.broker import Fill, MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"
DAY0 = pd.Timestamp("2024-03-04")
DAY5 = pd.Timestamp("2024-03-11")


def _runner(broker, tmp_path, trade_log=True):
    return FuturesRunner(
        broker=broker,
        guard=MultiClusterGuard(clusters={
            CLUSTER: ClusterBudget(CLUSTER, max_gross_pct=0.05, max_net_pct=0.044),
        }, account=ACCOUNT),
        contracts_by_inst={},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
        trade_log_path=(tmp_path / "trades.jsonl") if trade_log else None,
    )


def _closes(tmp_path):
    path = tmp_path / "trades.jsonl"
    if not path.exists():
        return []
    return [r for r in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
            if r.get("type") == "CLOSE"]


def _pos(entry_day=DAY0, **kw):
    return OpenPos(inst="MES", direction="LONG", contracts=1, risk_dollars=500.0,
                   cluster=CLUSTER, entry_day=entry_day, stop_price=4950.0, **kw)


# ── the engine's reason survives the trip out of the backtest ─────────────────

def _bars(days, close_start=5000.0, step=1.0):
    idx = pd.date_range("2024-01-02 09:30", periods=days * 7, freq="h")
    px = [close_start + i * step for i in range(len(idx))]
    return pd.DataFrame({"open": px, "high": [p + 2 for p in px],
                         "low": [p - 2 for p in px], "close": px,
                         "volume": [1000] * len(idx)}, index=idx)


class _FillingBroker(MockBroker):
    """MockBroker leaves avg_price at 0.0; the runner's signal-exit trade row is written
    only when a fill has a price, so an offline broker never exercises that path."""

    PRICE = 5100.0

    def send_order(self, o):
        f = super().send_order(o)
        f.avg_price = self.PRICE
        f.filled_qty = o.contracts
        return f


def test_er7_capturing_the_reason_cannot_change_the_signal():
    """The whole fix must be observational: it runs inside the live signal path.

    Same inputs, one call collecting reasons and one not -- the desired position they
    return has to be identical, or the reason capture has become a decision.
    """
    engine = SwingTFEngine()
    df = _bars(60)
    labels = {d.date(): "Normal" for d in pd.date_range("2024-01-01", periods=400)}
    from futures.swing_tf import costs_for_basket
    cost = costs_for_basket(2.0)["MES"]

    without = engine.desired_position(df, labels, cost)
    sink = {}
    with_reason = engine.desired_position(df, labels, cost, reason_out=sink)
    assert without == with_reason, "reason capture changed the desired position"


def test_er8_a_stale_close_is_not_relabelled_as_todays_exit():
    """Reporting trades[-1] unconditionally would carry an old reason forward forever.

    A position closed last week would relabel today's exit with last week's reason,
    which is worse than no label: it reads as evidence.
    """
    sink = {}
    df = _bars(10)
    trades = [{"reason": "CHANDELIER", "exit_day": pd.Timestamp("2020-01-02").date()}]
    SwingTFEngine._record_exit_reason(sink, trades, df)
    assert sink == {}, "a close from another day must not be reported as today's"

    trades = [{"reason": "MAX_HOLD", "exit_day": pd.Timestamp(df.index[-1]).date()}]
    SwingTFEngine._record_exit_reason(sink, trades, df)
    assert sink["reason"] == "MAX_HOLD"


def test_er9_decide_day_never_reads_the_reason():
    # Structural, not behavioural: the field must stay invisible to the risk brain, so
    # no future edit can quietly make an exit label affect sizing or admission.
    import inspect

    from global_index import live_decision

    assert "exit_reason" not in inspect.getsource(live_decision.decide_day)


# ── the signal-exit CLOSE row carries it ──────────────────────────────────────

def test_er1_signal_exit_writes_its_reason_to_the_trade_log(tmp_path):
    runner = _runner(_FillingBroker({}, ACCOUNT), tmp_path)
    p = _pos()
    p.exit_reason = "CHANDELIER"
    runner.state.open_positions.append(p)
    runner.signal_fn = lambda d, b, h: ([], [p])

    runner.run_day(DAY5)

    rows = _closes(tmp_path)
    assert rows, "no CLOSE row was written for a signal exit"
    assert rows[-1]["exit_reason"] == "CHANDELIER"


def test_er2_an_unattributed_exit_is_recorded_as_none_not_guessed(tmp_path):
    # An exit labelled by assumption is worse evidence than an exit labelled not at all:
    # the gate would count a sample it does not have.
    runner = _runner(_FillingBroker({}, ACCOUNT), tmp_path)
    p = _pos()
    runner.state.open_positions.append(p)
    runner.signal_fn = lambda d, b, h: ([], [p])

    runner.run_day(DAY5)

    rows = _closes(tmp_path)
    assert rows, "no CLOSE row was written"
    assert rows[-1]["exit_reason"] is None


# ── the two paths that wrote nothing at all ───────────────────────────────────

def test_er4_max_hold_exit_writes_a_close_row(tmp_path):
    """This path booked the P&L and emitted an event but never wrote a trade row.

    exit_path_coverage counts MAX_HOLD from the trade log, so every max-hold exit the
    system has ever made was invisible to the gate meant to observe it.
    """
    broker = MockBroker({}, ACCOUNT)
    runner = _runner(broker, tmp_path)
    runner.state.open_positions.append(_pos(stop_order_id="stp-abc"))

    closed = runner.run_maxhold_exit(DAY5, max_hold_days=5)

    assert ("MES", CLUSTER) in closed
    rows = _closes(tmp_path)
    assert len(rows) == 1, f"expected exactly one CLOSE row, got {len(rows)}"
    assert rows[0]["exit_reason"] == "MAX_HOLD"
    assert rows[0]["entry_day"] == str(DAY0.date())
    assert rows[0]["exit_day"] == str(DAY5.date())


def test_er5_a_failed_max_hold_close_writes_no_row(tmp_path):
    # The position stays open for retry; a CLOSE row here would book an exit that did
    # not happen.
    class _Fail(MockBroker):
        def send_order(self, o):
            if o.action == "CLOSE":
                return Fill(o.inst, o.action, o.direction, o.contracts, o.cluster,
                            status="FAILED", error_msg="mock")
            return super().send_order(o)

    runner = _runner(_Fail({}, ACCOUNT), tmp_path)
    runner.state.open_positions.append(_pos())

    runner.run_maxhold_exit(DAY5, max_hold_days=5)

    assert _closes(tmp_path) == []
    assert runner.state.open_positions[0].exit_pending is True


def test_er6_a_retried_exit_writes_a_close_row_keeping_its_original_reason(tmp_path):
    broker = MockBroker({}, ACCOUNT)
    runner = _runner(broker, tmp_path)
    p = _pos(exit_pending=True)
    p.exit_reason = "CHANDELIER"
    runner.state.open_positions.append(p)

    runner._retry_pending_exits(DAY5)

    rows = _closes(tmp_path)
    assert len(rows) == 1
    assert rows[0]["retried"] is True
    assert rows[0]["exit_reason"] == "CHANDELIER", (
        "the retry is how the exit happened, not why -- the original reason must survive"
    )


def test_er3_a_retry_with_no_attributed_reason_says_retry(tmp_path):
    runner = _runner(MockBroker({}, ACCOUNT), tmp_path)
    runner.state.open_positions.append(_pos(exit_pending=True))

    runner._retry_pending_exits(DAY5)

    rows = _closes(tmp_path)
    assert len(rows) == 1 and rows[0]["exit_reason"] == "RETRY"


# ── Khung giờ: vì sao nhãn chưa từng tới được sổ trên đường sống ─────────────

def _tz_frame(tz, day="2026-08-11"):
    idx = pd.date_range(f"{day} 09:30", periods=3, freq="1min", tz=tz)
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                         "volume": 1}, index=idx)


@pytest.mark.parametrize("tz", ["America/New_York", "Asia/Tokyo", None])
def test_the_reason_survives_a_frame_that_carries_a_timezone(tz):
    """Bản đầu so một `Timestamp` naive dựng từ chuỗi ngày với `df.index[-1]` mang múi
    giờ. Phép `!=` giữa hai loại đó KHÔNG ném lỗi — nó chỉ luôn trả True. Nên điều kiện
    không bao giờ thoả trên đường sống, và hàm chưa từng gán được nhãn nào.

    Không có ngoại lệ, không có log, không có giá trị sai — chỉ một trường luôn rỗng.
    Và chú thích ở cả runner lẫn signal_layer đều nói rỗng là hợp lệ ("None khi lớp tín
    hiệu không quy được — không bao giờ đoán"), nên lời giải thích đúng đắn ấy che mất
    việc nó LUÔN rỗng.

    Đo được 2026-08-18: cả 4 lệnh đóng trong kỳ giấy không mang lý do, exit_path_coverage
    đứng ở 0/0/0, và đồng hồ 60 ngày chạy trên một cổng không thể tiến.
    """
    sink = {}
    SwingTFEngine._record_exit_reason(
        sink, [{"reason": "CHANDELIER", "exit_day": "2026-08-11"}], _tz_frame(tz))
    assert sink.get("reason") == "CHANDELIER", (
        f"khung tz={tz}: nhan bi mat — day la loi da lam ca ky giay khong co mau thoat")


@pytest.mark.parametrize("tz", ["America/New_York", None])
def test_a_trade_that_closed_on_another_day_is_still_refused(tz):
    """Nửa còn lại, và là nửa quan trọng hơn. Bỏ hẳn phép kiểm ngày cũng làm phép kiểm
    trên xanh — nhưng khi đó một lệnh đóng tuần trước sẽ dán nhãn cho lệnh thoát hôm
    nay, tức bịa ra bằng chứng thay vì thiếu bằng chứng."""
    sink = {}
    SwingTFEngine._record_exit_reason(
        sink, [{"reason": "CHANDELIER", "exit_day": "2026-08-04"}], _tz_frame(tz))
    assert sink == {}, f"khung tz={tz}: gan nhan cua mot ngay khac"


def test_asking_for_the_reason_does_not_change_what_the_backtest_returns():
    """Hàm này nằm trong `futures/`, nên phải chứng minh nó không đụng tới kết quả.

    Nó chỉ ghi vào `reason_out`; không chạm `trades`, không chạm vị thế mở. Đo bằng
    cách chạy hai lần trên cùng dữ liệu — một lần có xin lý do, một lần không — và so
    từng trường, chứ không so tổng.
    """
    frame = _tz_frame("America/New_York")
    trades = [{"reason": "CHANDELIER", "exit_day": "2026-08-11", "pnl": 12.5}]
    before = json.loads(json.dumps(trades))

    sink = {}
    SwingTFEngine._record_exit_reason(sink, trades, frame)

    assert trades == before, "ham da sua doi danh sach lenh"
    assert sink == {"reason": "CHANDELIER", "exit_day": "2026-08-11"}
