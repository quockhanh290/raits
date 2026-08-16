"""
global_index/test_stp.py — STP (stop order) placement + B3 STP-exit detection tests

Tests:
  STP1: STP HOÃN sang phiên sau ở ngày vào lệnh (mức stop vẫn được ghi lại)
  STP1b: sang ngày, B4 đặt STP — cửa sổ tự hết hạn, không cần job mới
  STP2: stop_price + stop_order_id serialised to / from JSON (cold-start round-trip)
  STP3: place_stop() NOT called for same-day entries (STRESS_MID)
  STP4: place_stop() NOT called when OPEN fill is CANCELLED
  STP5: B3 STP EXIT — IBKR shows 0 but stop_order_id is FILLED → auto-clear, no halt
  STP6: B3 MISMATCH with stop_order_id NOT_FOUND → CRITICAL + halt (with STP hint)
  STP7: B3 MISMATCH without stop_order_id → original CRITICAL behavior unchanged
  STP10: B5 IM trong cửa sổ hoãn có chủ đích
  STP10b: B5 vẫn KÊU khi stop mất thật, sau khi cửa sổ đã qua

Vì sao STP1 đổi: live cũ đặt STP 0–1 giây sau khi khớp, còn engine chỉ xét stop từ ngày
hôm sau. Đó là hai luật thoát khác nhau, và khoảng cách không nhỏ — đo 2018–2026 trên
Rổ 4: đặt ngay −$10.832, đặt sang ngày +$47.166 (model_sameday_stop.py).
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.broker import BrokerPosition, Fill, MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard  # noqa: F401
from global_index.runner import FuturesRunner, _openpos_from_dict, _openpos_to_dict
from futures.circuit_breaker import CircuitBreaker

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"
DAY1 = pd.Timestamp("2024-03-11")
DAY2 = pd.Timestamp("2024-03-12")


# ── helpers ───────────────────────────────────────────────────────────────────

class _RecordingMockBroker(MockBroker):
    """MockBroker that records place_stop / cancel_order / get_order_status calls."""

    def __init__(self, bars, account, stp_status="PENDING"):
        super().__init__(bars, account)
        self.stp_calls: list[dict] = []
        self.cancel_calls: list[str] = []
        self._stp_status = stp_status  # returned by get_order_status()

    def place_stop(self, inst, direction, contracts, stop_price, cluster):
        order_id = f"stp-{inst}-{len(self.stp_calls)}"
        self.stp_calls.append(dict(
            inst=inst, direction=direction, contracts=contracts,
            stop_price=stop_price, cluster=cluster, order_id=order_id,
        ))
        return order_id

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        return True

    def get_order_status(self, order_id):
        return self._stp_status


class _CancelledOpenBroker(MockBroker):
    """Returns CANCELLED for OPEN orders — simulates entry timeout."""

    def send_order(self, o):
        if o.action == "OPEN":
            return Fill(o.inst, o.action, o.direction, o.contracts, o.cluster,
                        status="CANCELLED", error_msg="entry timeout")
        return super().send_order(o)

    def place_stop(self, inst, _d, _c, _sp, _cl):
        raise AssertionError("place_stop must NOT be called after CANCELLED OPEN")

    def cancel_order(self, _oid): return True
    def get_order_status(self, _oid): return "PENDING"


def _make_guard():
    return MultiClusterGuard(clusters={
        "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=0.05, max_net_pct=0.044),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
        "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.02,  max_net_pct=0.02),
    }, account=ACCOUNT)


def _multi_day_signal(day, bars, held):
    """DAY1: open a multi-day swing position (exit_day = DAY2)."""
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=CLUSTER,
                     risk_sized=500.0, entry=5000.0, stop=4950.0,
                     exit=DAY2, pnl_sized=150.0)], []
    # DAY2: close the position
    return [], ([held[0]] if held else [])


def _sameday_signal(day, bars, held):
    """Open and close on the same day (STRESS_MID style)."""
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=CLUSTER,
                     risk_sized=500.0, entry=5000.0, stop=4950.0,
                     exit=DAY1, pnl_sized=100.0)], []
    return [], []



def _runner_on(broker, tmp_path, today, signal_fn=None):
    """Runner mới cho một ngày cụ thể, dùng lại broker + file trạng thái.

    B4 chạy trong __init__, nên đây là cách duy nhất đi qua đường "hôm sau mới đặt
    STP" mà không gọi thẳng vào ruột. Truyền today tường minh: mặc định là ngày ET
    hiện tại, mà mọi ngày trong test đều nằm ở 2024.
    """
    return FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=signal_fn or _multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
        today=today,
        # Gio vu trang gio la RIENG tung sleeve (14:00 ET cho swing, 01:00 ET cho NKD),
        # nen `today` mot minh khong con du — phai noi ro moc thoi gian. 14:05 la slot
        # giao dich dau tien, tuc da qua ca hai gio.
        now=pd.Timestamp(today) + pd.Timedelta(hours=14, minutes=5),
    )


# ── STP1: STP hoãn sang phiên sau, rồi B4 đặt ────────────────────────────────

def test_stp1_stp_is_deferred_on_the_entry_day(tmp_path):
    """Không đặt STP ngay lúc khớp — nhưng PHẢI ghi lại mức stop.

    Live cũ đặt STP 0–1 giây sau khi khớp. Engine chỉ xét stop từ ngày hôm sau (khối
    thoát chạy trước khối vào lệnh trong cùng vòng lặp ngày), nên đó là một luật thoát
    chặt hơn hẳn luật đã kiểm định. Đo 2018–2026 trên Rổ 4: đặt ngay −$10.832, đặt sang
    ngày +$47.166.

    `stop_price` vẫn phải được ghi: thiếu nó thì B4 không đặt được hôm sau ("chỉ đặt lại
    khi đã biết mức"), và vị thế trần suốt đời thay vì đúng một phiên.
    """
    broker = _RecordingMockBroker({}, ACCOUNT)
    runner = _runner_on(broker, tmp_path, DAY1)
    runner.run_day(DAY1)

    assert broker.stp_calls == [], (
        f"STP phải hoãn sang phiên sau, nhưng đã gửi lên broker: {broker.stp_calls}")

    pos = runner.state.open_positions[0]
    assert pos.stop_price == 4950.0, "mức stop phải được ghi lại dù chưa đặt lệnh"
    assert pos.stop_order_id is None

    deferred = [e for e in runner._events
                if e.get("context", {}).get("deferred") is True]
    assert deferred, f"việc hoãn phải nói ra, không im lặng. events={runner._events}"


def test_stp1b_stp_is_placed_once_the_entry_day_has_passed(tmp_path):
    """Cửa sổ tự hết hạn: sang ngày, B4 đặt stop. Không có job mới nào cả.

    Đây là nửa còn lại của bản sửa và là nửa dễ quên. Bỏ nửa này thì "hoãn" thành
    "không bao giờ đặt".
    """
    broker = _RecordingMockBroker({}, ACCOUNT)
    _runner_on(broker, tmp_path, DAY1).run_day(DAY1)
    assert broker.stp_calls == []

    _runner_on(broker, tmp_path, DAY2)      # B4 chạy ngay trong __init__

    assert len(broker.stp_calls) == 1, (
        f"B4 phải đặt STP ở ngày kế tiếp, stp_calls={broker.stp_calls}")
    c = broker.stp_calls[0]
    assert (c["inst"], c["direction"], c["stop_price"], c["cluster"]) ==            ("MES", "LONG", 4950.0, CLUSTER)


# ── STP2: round-trip JSON serialisation ──────────────────────────────────────

def test_stp2_json_roundtrip():
    p = OpenPos(
        inst="MES", direction="LONG", contracts=1, risk_dollars=500.0,
        cluster=CLUSTER, entry_day=pd.Timestamp("2024-03-11"),
        stop_price=4950.0, stop_order_id="ibkr-123",
    )
    d = _openpos_to_dict(p)
    assert d["stop_price"] == 4950.0
    assert d["stop_order_id"] == "ibkr-123"

    restored = _openpos_from_dict(d)
    assert restored.stop_price == 4950.0
    assert restored.stop_order_id == "ibkr-123"


def test_stp2b_json_roundtrip_no_stp():
    """Legacy positions without stop fields load with None defaults."""
    raw = dict(
        inst="MNQ", direction="SHORT", contracts=1, risk_dollars=400.0,
        cluster="swing_tf_MNQ_SHORT", entry_day="2024-03-11",
    )
    p = _openpos_from_dict(raw)
    assert p.stop_price is None
    assert p.stop_order_id is None


# ── STP3: no place_stop for same-day entries ─────────────────────────────────

def test_stp3_no_stp_for_sameday_entry():
    broker = _RecordingMockBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_sameday_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
    )
    runner.run_day(DAY1)
    assert broker.stp_calls == [], "place_stop must NOT be called for same-day entries"


# ── STP4: no place_stop when OPEN fill is CANCELLED ──────────────────────────

def test_stp4_no_stp_when_open_cancelled(tmp_path):
    """C2. A cancelled entry must leave NOTHING behind — not a stop, and not a position.

    This test used to have no assert at all. It leaned entirely on
    `_CancelledOpenBroker.place_stop` raising, which checks exactly one thing: no stop
    was placed. The four questions that actually make up C2 went unasked, and all four
    answered wrong (RUNNER_AUDIT.md §4.1):

      * is the position still in state.open_positions?   it was
      * did it persist to disk with entry_price=None?    it did
      * was any trade_log line written?                  none
      * was any event emitted?                           none

    Root cause: decide_day books the position before the order goes out, and
    `send_order` never returns "FAILED" for an OPEN — all three failure paths return
    "CANCELLED" (ibkr_broker.py:678/:724/:741), so the handler at runner.py:1770 that
    tested `== "FAILED"` was dead code.
    """
    broker = _CancelledOpenBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
        trade_log_path=tmp_path / "trade_log.jsonl",
        today=DAY1,
        now=pd.Timestamp(DAY1) + pd.Timedelta(hours=14, minutes=5),
    )
    # Must not raise (asserting inside _CancelledOpenBroker.place_stop)
    runner.run_day(DAY1)

    assert runner.state.open_positions == [], (
        "the broker holds nothing — a cancelled entry must not leave a position in the "
        f"book. Left behind: "
        f"{[(p.inst, p.contracts, p.entry_price) for p in runner.state.open_positions]}")

    saved = json.loads((tmp_path / "pos.json").read_text(encoding="utf-8"))["positions"]
    assert saved == [], (
        f"the ghost was persisted to disk, so the next slot's B3 will compare it against "
        f"an empty broker and halt every sleeve's entries: {saved}")

    cancelled_events = [e for e in runner._events
                        if "CANCEL" in e.get("message", "").upper()]
    assert cancelled_events, (
        "a cancelled entry must not be silent: no trade_log line, no event and no ERROR "
        f"is how this went unnoticed. events={runner._events}")


def test_stp4b_cancelled_entry_does_not_produce_a_close_next_day(tmp_path):
    """C2, the part that costs money.

    With the ghost in the book, the exit day sends `CLOSE MES LONG` for a position the
    broker never opened. `send_order` maps CLOSE+LONG to a SELL market order
    (ibkr_broker.py:631) and checks no position anywhere, so that order does not close
    anything — it OPENS a short, with no stop, in no ledger.
    """
    broker = _CancelledOpenBroker({}, ACCOUNT)

    def _mk(today):
        return FuturesRunner(
            broker=broker, guard=_make_guard(),
            contracts_by_inst={"MES": 1},
            signal_fn=_multi_day_signal,
            breaker=CircuitBreaker(account=ACCOUNT),
            positions_path=tmp_path / "pos.json",
            trade_log_path=tmp_path / "trade_log.jsonl",
            today=today,
            now=pd.Timestamp(today) + pd.Timedelta(hours=14, minutes=5),
        )

    _mk(DAY1).run_day(DAY1)
    sent_before = len(broker.fills)
    _mk(DAY2).run_day(DAY2)

    closes = [f for f in broker.fills[sent_before:] if f.action == "CLOSE"]
    assert not closes, (
        f"a CLOSE went to the broker for a position it never held — that is a naked "
        f"short, not an exit. closes={[(f.inst, f.direction, f.contracts) for f in closes]}")


# ── STP5: B3 STP EXIT auto-clear ─────────────────────────────────────────────

def test_stp5_b3_stp_exit_auto_clear(tmp_path):
    pos_file = tmp_path / "pos.json"

    # Write a persisted position with stop_order_id
    state = {
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": 4950.0, "stop_order_id": "ibkr-456",
        }],
        "breaker": {},
    }
    pos_file.write_text(json.dumps(state))

    # Broker reports 0 positions (STP filled overnight) and status=FILLED
    broker = _RecordingMockBroker({}, ACCOUNT, stp_status="FILLED")
    # get_positions returns [] — IBKR has no open position
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )

    # B3 STP EXIT: auto-cleared, no halt
    assert not runner._b3_halt_entries, "STP EXIT: halt must NOT fire"
    assert runner.state.open_positions == [], "STP EXIT: position must be cleared from state"


# ── STP6: B3 MISMATCH with stop_order_id NOT_FOUND → CRITICAL + halt ─────────

def test_stp6_b3_mismatch_stp_not_found_halts(tmp_path):
    pos_file = tmp_path / "pos.json"
    state = {
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": 4950.0, "stop_order_id": "ibkr-789",
        }],
        "breaker": {},
    }
    pos_file.write_text(json.dumps(state))

    broker = _RecordingMockBroker({}, ACCOUNT, stp_status="NOT_FOUND")
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )

    assert runner._b3_halt_entries, "STP NOT_FOUND mismatch must still halt entries"
    assert len(runner.state.open_positions) == 1, "Position remains in state pending resolution"


# ── STP7: B3 MISMATCH without stop_order_id → original behavior ──────────────

def test_stp7_b3_mismatch_no_stp_still_halts(tmp_path):
    pos_file = tmp_path / "pos.json"
    state = {
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
        }],
        "breaker": {},
    }
    pos_file.write_text(json.dumps(state))

    # IBKR has 0 MES (no stop_order_id, so it's a genuine orphan)
    broker = MockBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )

    assert runner._b3_halt_entries, "Orphan (no STP) mismatch must halt entries"


# ── STP8: cancel_order called on successful CLOSE for position with stop_order_id ──

def test_stp8_cancel_called_on_close(tmp_path):
    """When runner sends CLOSE for a multi-day position that has a GTC stop,
    cancel_order(stop_order_id) must be called so the orphan stop cannot
    create an unintended position after the LONG/SHORT is gone."""
    broker = _RecordingMockBroker({}, ACCOUNT)

    # DAY1: vào lệnh — STP hoãn, chưa có gì để huỷ
    _runner_on(broker, tmp_path, DAY1).run_day(DAY1)
    assert broker.stp_calls == [], "STP phải hoãn ở ngày vào lệnh"

    # DAY2: B4 đặt STP lúc dựng runner, rồi phiên đó đóng vị thế → phải huỷ
    runner = _runner_on(broker, tmp_path, DAY2)
    assert len(broker.stp_calls) == 1, "B4 phải đặt STP ở ngày kế tiếp"
    placed_id = broker.stp_calls[0]["order_id"]

    runner.run_day(DAY2)
    assert runner.state.open_positions == [], "Position must be closed on DAY2"
    assert placed_id in broker.cancel_calls, (
        f"cancel_order({placed_id!r}) not called on CLOSE; "
        f"cancel_calls={broker.cancel_calls}"
    )


# ── STP9: cancel_order returning False must raise an orphan alert ────────────

class _CancelFailsBroker(_RecordingMockBroker):
    """cancel_order reports failure the way IBKRBroker does — by returning False,
    not by raising. Seen live 2026-08-05: two GTC stops stayed working at IBKR for
    days while the runner logged 'cancelled' for both."""

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        return False


def test_stp9_orphan_alert_when_cancel_fails(tmp_path):
    """A stop that could not be cancelled is still live at the broker and will fire
    against a position that no longer exists. The runner must say so."""
    broker = _CancelFailsBroker({}, ACCOUNT)
    _runner_on(broker, tmp_path, DAY1).run_day(DAY1)

    runner = _runner_on(broker, tmp_path, DAY2)     # B4 đặt STP ở ngày kế tiếp
    assert broker.stp_calls, "B4 phải đặt STP trước khi test việc huỷ"
    placed_id = broker.stp_calls[0]["order_id"]

    runner.run_day(DAY2)
    assert placed_id in broker.cancel_calls, "cancel_order must still be attempted"

    orphan = [e for e in runner._events
              if e["level"] == "CRITICAL" and e["category"] == "ORDER"]
    assert orphan, (
        "cancel_order returned False but no CRITICAL/ORDER event was emitted — "
        f"the orphan stop {placed_id!r} is invisible. events={runner._events}"
    )
    assert placed_id in orphan[0]["message"], (
        f"orphan alert must name the order id; got {orphan[0]['message']!r}"
    )


# ── B4: naked-position check (open at broker, no stop order) ─────────────────

def _naked_broker(stop_working=False, working_raises=None):
    """MockBroker holding one MES LONG at the broker, for B4 tests."""
    b = _RecordingMockBroker({}, ACCOUNT)
    b._positions = [BrokerPosition("MES", "LONG", 1, CLUSTER, DAY1, None, 0.0)]
    if working_raises is not None:
        b.has_working_stop = lambda _inst, _dir=None, _n=None: (
            (_ for _ in ()).throw(working_raises))
    else:
        # B4 now asks the per-position form (inst, direction, contracts); the fake must
        # accept it or the call raises TypeError, B4 declines to place, and the test
        # passes for the wrong reason.
        b.has_working_stop = lambda _inst, _dir=None, _n=None: stop_working
    return b


def _naked_file(tmp_path, stop_price=None, stop_order_id=None):
    pos_file = tmp_path / "pos.json"
    pos_file.write_text(json.dumps({
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": stop_price, "stop_order_id": stop_order_id,
        }],
        "breaker": {},
    }))
    return pos_file


def _make_runner(broker, pos_file):
    return FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )


def test_b4_1_replaces_stop_when_level_known_and_none_working(tmp_path):
    """stop_price known + no working stop at broker → re-place, record orderId."""
    broker = _naked_broker(stop_working=False)
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert len(broker.stp_calls) == 1, "B4 must re-place the missing stop"
    assert broker.stp_calls[0]["stop_price"] == 4950.0
    assert runner.state.open_positions[0].stop_order_id == broker.stp_calls[0]["order_id"]
    assert not runner._b3_halt_entries, "B4 must not halt entries"


def test_b4_2_no_duplicate_when_stop_already_working(tmp_path):
    """A stop is already live at the broker → must NOT stack a second one."""
    broker = _naked_broker(stop_working=True)
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert broker.stp_calls == [], "duplicate STP would double-close and flip the position"
    assert runner._b4_naked_stops == [("MES", CLUSTER)]


def test_b4_3_alerts_when_stop_price_unknown(tmp_path):
    """The live 2026-08-03 case: OPEN misread as Cancelled → both fields None.
    Level is unknown, so B4 can only alert — never guess a stop level."""
    broker = _naked_broker(stop_working=False)
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=None))

    assert broker.stp_calls == [], "no level known → must not place"
    assert runner._b4_naked_stops == [("MES", CLUSTER)]
    assert not runner._b3_halt_entries, "naked position is not a state mismatch"
    assert len(runner.state.open_positions) == 1, "position must stay in state"


def test_b4_4_no_place_when_broker_cannot_report_working_stops(tmp_path):
    """Broker can't answer has_working_stop → alert, don't place blind."""
    broker = _naked_broker(working_raises=NotImplementedError())
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert broker.stp_calls == [], "unverifiable → duplicate-stop risk → must not place"
    assert runner._b4_naked_stops == [("MES", CLUSTER)]


def test_b4_5_noharm_position_with_stop_is_not_naked(tmp_path):
    """Position already carrying a stop_order_id → B4 stays silent."""
    broker = _naked_broker(stop_working=False)
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0,
                                              stop_order_id="ibkr-111"))

    assert broker.stp_calls == [], "already protected — nothing to do"
    assert runner._b4_naked_stops == []
    assert not runner._b3_halt_entries


# ── B4.6/B4.7: a recorded stop_order_id is not evidence of a working stop ────
#
# Live 2026-08-05: place_stop returned client-side ids 62/66/70, which were persisted
# to live_positions.json. B4's trigger was `stop_order_id is None`, so three naked
# positions read as protected and B4 — the guard written for exactly this — stayed
# silent. Detection must key off broker truth, not off the field the broken path wrote.


def _reporting_broker(working: dict):
    """MockBroker that CAN report working stops (unlike plain MockBroker → None)."""
    b = _naked_broker(stop_working=bool(working))
    b.get_working_stops = lambda: {k: list(v) for k, v in working.items()}
    return b


def test_b4_6_fabricated_stop_id_with_no_working_stop_is_naked(tmp_path):
    """stop_order_id recorded, but the broker holds no stop for that instrument."""
    broker = _reporting_broker({})          # broker answers: nothing is working
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0,
                                              stop_order_id="62"))

    assert runner._b4_naked_stops == [("MES", CLUSTER)], (
        "a recorded stop_order_id must not suppress B4 when the broker reports "
        "no working stop — this is the 2026-08-05 failure"
    )
    assert len(broker.stp_calls) == 1, "level is known and nothing is working → re-place"


def test_b4_8_expiry_aware_check_overrides_the_symbol_level_one(tmp_path):
    """has_working_stop khớp theo SYMBOL. Sau một lần roll mà cancel thất bại, stop của hợp
    đồng ĐÃ CHẾT vẫn sống trên cùng mã, nên nó trả True cho một vị thế đang trần — và B4 sẽ
    ghi `STP ID DRIFT` (cảnh báo) thay vì đặt lại stop.

    `unprotected_positions` khớp theo (mã, expiry, bên) và cộng số hợp đồng, nên khi hai bên
    bất đồng thì nó là bên đúng. Test này ghim thứ tự ưu tiên đó."""
    broker = _naked_broker(stop_working=True)          # symbol-level: "da duoc phu"
    broker.unprotected_positions = lambda: [
        {"inst": "MES", "expiry": "20261218", "qty": 1, "covered": 0,
         "stop_expiries": ["20260918"]}]                # contract-level: TRAN
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert len(broker.stp_calls) == 1, (
        "B4 phai tin unprotected_positions va dat lai stop; tin has_working_stop se de vi "
        "the tran voi mot dong WARNING noi rang no da duoc bao ve")


def test_b4_9_no_override_when_the_broker_cannot_answer(tmp_path):
    """`unprotected_positions` trả None nghĩa là "không kết luận được" (MockBroker, offline).
    Khi đó KHÔNG được ghi đè — phải giữ nguyên hành vi cũ, nếu không mọi broker không trả lời
    được sẽ bị coi như đang báo trần."""
    broker = _naked_broker(stop_working=True)
    broker.unprotected_positions = lambda: None
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert broker.stp_calls == [], "None la 'khong biet', khong phai 'tran'"


def test_b4_10_no_override_when_the_contract_check_agrees(tmp_path):
    """Hai bên cùng nói đã được phủ → không đặt gì. Chặn chiều hỏng ngược lại: một bản sửa
    quá tay sẽ đặt stop chồng lên vị thế vốn đã có stop."""
    broker = _naked_broker(stop_working=True)
    broker.unprotected_positions = lambda: []
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert broker.stp_calls == []


def test_b4_7_working_stop_at_broker_is_not_naked(tmp_path):
    """Broker confirms a stop is working → B4 silent, no duplicate placed."""
    # The id must be the one the position recorded: B4 asks "is MY stop still working",
    # so a stop belonging to another position on the same contract no longer counts.
    broker = _reporting_broker({"MES": ["62"]})
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0,
                                              stop_order_id="62"))

    assert runner._b4_naked_stops == []
    assert broker.stp_calls == [], "must not stack a second STP on a protected position"


# ── STP10: end-of-session sweep — a naked position must not wait for tomorrow ─
#
# B4 runs at startup, so a stop that fails to reach IBKR is only noticed on the NEXT
# slot — or, if the scheduler has finished for the day, not until tomorrow. On
# 2026-08-05 the entries ran at 14:40 ET and the gap was found that evening by hand.
# The runner already knows the answer before it disconnects; it just never asked.


class _StopFailsBroker(_RecordingMockBroker):
    """place_stop báo thất bại kiểu IBKRBroker — trả chuỗi rỗng, không ném lỗi.
    Dùng để dựng một vị thế thật sự không có stop SAU khi cửa sổ hoãn đã qua."""

    def place_stop(self, inst, direction, contracts, stop_price, cluster):
        super().place_stop(inst, direction, contracts, stop_price, cluster)
        return ""

    def get_working_stops(self):
        return {}                              # broker: không có stop nào đang chạy

    def has_working_stop(self, _inst, direction=None, contracts=None):
        return False


def _hold_signal(day, bars, held):
    """Mở ở DAY1 rồi GIỮ — để B5 có vị thế mở mà xét ở DAY2."""
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=CLUSTER,
                     risk_sized=500.0, entry=5000.0, stop=4950.0,
                     exit=None, pnl_sized=150.0)], []
    return [], []


def test_stp10_session_end_stays_quiet_during_the_deliberate_window(tmp_path):
    """Ngày vào lệnh: không có STP là ĐÚNG, nên B5 phải im.

    Báo CRITICAL mỗi phiên cho một chuyện cố ý sẽ dạy người vận hành bỏ qua đúng cái
    cảnh báo có nghĩa. Đây là nửa 'không được kêu' của B5.
    """
    broker = _StopFailsBroker({}, ACCOUNT)
    runner = _runner_on(broker, tmp_path, DAY1, signal_fn=_hold_signal)
    runner.run_day(DAY1)

    assert runner.state.open_positions, "phải có vị thế mở thì test mới có nghĩa"
    unprotected = [e for e in runner._events
                   if e["level"] == "CRITICAL" and "UNPROTECTED" in e["message"]]
    assert not unprotected, (
        "vị thế đang trong cửa sổ hoãn CÓ CHỦ ĐÍCH mà B5 vẫn kêu CRITICAL — "
        f"cảnh báo sẽ bị nhờn. events={runner._events}")


def test_stp10b_session_end_flags_position_with_no_working_stop(tmp_path):
    """After entries, before disconnect: every open position must have a live stop.

    Bản gốc chạy trên ngày vào lệnh, mà giờ ngày đó không có stop là đúng. Nội dung
    test thì vẫn nguyên giá trị — nó bắt stop MẤT THẬT — nên chỉ dời sang sau cửa sổ:
    B4 thử đặt ở DAY2 và thất bại, vị thế trần thật, B5 phải nói ra.
    """
    broker = _StopFailsBroker({}, ACCOUNT)
    _runner_on(broker, tmp_path, DAY1, signal_fn=_hold_signal).run_day(DAY1)

    runner = _runner_on(broker, tmp_path, DAY2, signal_fn=_hold_signal)
    assert broker.stp_calls, "B4 phải THỬ đặt stop ở ngày kế tiếp"
    assert runner.state.open_positions[0].stop_order_id is None, "và đã thất bại"

    runner.run_day(DAY2)

    assert runner.state.open_positions, "position must be open for this test to mean anything"
    unprotected = [e for e in runner._events
                   if e["level"] == "CRITICAL" and e["category"] == "ORDER"
                   and "UNPROTECTED" in e["message"]]
    assert unprotected, (
        "position is open and the broker reports no working stop, but the session "
        f"ended without saying so. events={runner._events}"
    )
    assert "MES" in unprotected[0]["message"]


def test_stp11_session_end_silent_when_stop_is_working(tmp_path):
    """Broker confirms the stop → no alert. Guards against crying wolf every slot."""
    broker = _RecordingMockBroker({}, ACCOUNT)
    # {inst: [orderId, ...]} and the check is now "is the id THIS position recorded
    # still working", so the fake must name the id the runner actually stored.
    broker.get_working_stops = lambda: {"MES": ["stp-MES-0"]}
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )

    runner.run_day(DAY1)

    unprotected = [e for e in runner._events
                   if e["level"] == "CRITICAL" and "UNPROTECTED" in e["message"]]
    assert unprotected == [], f"stop is working — must stay quiet. got {unprotected}"


def test_stp12_session_end_quiet_when_broker_cannot_report(tmp_path):
    """MockBroker answers None → no claim either way, no alert (reconcile unchanged)."""
    broker = _RecordingMockBroker({}, ACCOUNT)   # inherits get_working_stops → None
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )

    runner.run_day(DAY1)

    unprotected = [e for e in runner._events
                   if e["level"] == "CRITICAL" and "UNPROTECTED" in e["message"]]
    assert unprotected == [], "a broker that cannot testify must not trigger alarms"


# ── STP13: a stop-triggered exit must leave a trade record ───────────────────
#
# When a stop fires, the runner sends no order — so nothing on the send_order path
# writes a trade record, and the exit price of the trade is never captured. Chandelier
# stops are 79.5% of exits, so this is most of them.
#
# B3's STP-VERIFY branch is the one place that both notices the exit and holds the fill:
# it asks IBKR, gets price/size/time/permId back, and used to keep only "yes it filled".
# Measured 2026-08-07: reqExecutions served that fill on the day and had forgotten it by
# the next, so this is the only moment it can be recorded.


class _StopFilledBroker(_RecordingMockBroker):
    """IBKR holds no position; the recorded stop shows as gone but did execute."""

    def __init__(self, bars, account, fill):
        super().__init__(bars, account, stp_status="NOT_FOUND")
        self._fill = fill

    def find_execution(self, order_id, inst=None):
        return dict(self._fill) if str(order_id) == "ibkr-456" else None


def test_stp13_stop_exit_is_written_to_the_trade_log(tmp_path):
    pos_file = tmp_path / "pos.json"
    pos_file.write_text(json.dumps({
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": 4950.0, "stop_order_id": "ibkr-456",
        }],
        "breaker": {},
    }))
    log_path = tmp_path / "trade_log.jsonl"
    broker = _StopFilledBroker({}, ACCOUNT, fill={
        "order_id": 456, "perm_id": 375088794,
        "price": 4948.75, "shares": 1, "time": "2024-03-12 14:31:02",
    })

    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
        trade_log_path=log_path,
    )

    assert runner.state.open_positions == [], "position must be cleared"
    assert log_path.exists(), (
        "the stop fill was confirmed and then not recorded anywhere — nothing else "
        "writes a trade record for a stop-triggered exit"
    )
    recs = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    closes = [r for r in recs if r.get("type") == "CLOSE"]
    assert len(closes) == 1, f"expected one CLOSE record, got {recs}"
    c = closes[0]
    assert c["fill_price"] == pytest.approx(4948.75), "the exit price is the point"
    assert c["perm_id"] == 375088794, "permId is the stable key across clients"
    # Joined with what only the runner knows — IBKR cannot supply any of these.
    assert (c["inst"], c["cluster"], c["direction"]) == ("MES", CLUSTER, "LONG")
    assert c["entry_day"] == "2024-03-11"
    assert c["exit_reason"] == "STP", "must be distinguishable from a signal exit"


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# ── STP11: cửa sổ hoãn theo TỪNG SLEEVE ──────────────────────────────────────
#
# Sáu test ở trên đều chạy MES/roska4_swing. Bản sửa lại đụng tới cả ba sleeve, và
# hai sleeve còn lại rẽ theo hai hướng NGƯỢC NHAU — nên không sleeve nào được suy ra
# từ sleeve kia.

NKD_CLUSTER, STRESS_CLUSTER = "global_nkd", "roska4_stress"


def _nkd_hold_signal(day, bars, held):
    """MNKD mở ở DAY1 rồi giữ. Cùng engine với Rổ 4 (backtest_swing_tf), khác tham số
    (ema=10) và khác đồng hồ phiên (JST) — nên cùng ngữ nghĩa stop, và phải hoãn."""
    if day == DAY1:
        return [dict(inst="MNKD", direction="LONG", cluster=NKD_CLUSTER,
                     risk_sized=400.0, entry=38000.0, stop=37600.0,
                     exit=None, pnl_sized=120.0)], []
    return [], []


def _stress_hold_signal(day, bars, held):
    """STRESS_MID mở rồi giữ — trạng thái BẤT THƯỜNG, vì nó là mô hình vào-ra trong
    phiên. Dựng ra để chốt nhánh phòng thủ: nếu một vị thế stress lỡ sống sót thì nó
    phải được đặt stop NGAY, không thừa hưởng luật đo trên engine khác."""
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=STRESS_CLUSTER,
                     risk_sized=300.0, entry=5000.0, stop=4950.0,
                     exit=None, pnl_sized=80.0)], []
    return [], []


def test_stp11_nkd_is_deferred_like_swing(tmp_path):
    """MNKD chạy cùng backtest_swing_tf nên thừa hưởng cùng luật stop-từ-hôm-sau.

    ĐỘ LỚN bằng tiền cho MNKD đo riêng (model_sameday_stop_nkd.py) — Rổ 4 không suy ra
    được vì khác ema, khác đồng hồ phiên, khác nhãn chế độ.
    """
    broker = _RecordingMockBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MNKD": 1},
        signal_fn=_nkd_hold_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json", today=DAY1,
        now=DAY1 + pd.Timedelta(hours=14, minutes=5),
    )
    runner.run_day(DAY1)

    assert broker.stp_calls == [], f"MNKD phải hoãn STP, đã gửi: {broker.stp_calls}"
    pos = runner.state.open_positions[0]
    assert pos.cluster == NKD_CLUSTER
    assert pos.stop_price == 37600.0, "mức stop vẫn phải được ghi để B4 đặt hôm sau"
    assert pos.stop_order_id is None


def test_stp11b_nkd_gets_its_stop_the_next_day(tmp_path):
    broker = _RecordingMockBroker({}, ACCOUNT)
    FuturesRunner(
        broker=broker, guard=_make_guard(), contracts_by_inst={"MNKD": 1},
        signal_fn=_nkd_hold_signal, breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json", today=DAY1,
        now=DAY1 + pd.Timedelta(hours=14, minutes=5),
    ).run_day(DAY1)

    FuturesRunner(
        broker=broker, guard=_make_guard(), contracts_by_inst={"MNKD": 1},
        signal_fn=_nkd_hold_signal, breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json", today=DAY2,
        now=DAY2 + pd.Timedelta(hours=14, minutes=5),
    )
    assert len(broker.stp_calls) == 1, f"B4 phải đặt STP cho MNKD, {broker.stp_calls}"
    assert broker.stp_calls[0]["inst"] == "MNKD"
    assert broker.stp_calls[0]["stop_price"] == 37600.0


def test_stp11c_stress_is_not_deferred(tmp_path):
    """Hướng NGƯỢC LẠI với hai test trên, và đó là lý do phải test riêng.

    ⚠ Test này kiểm một đường HIỆN KHÔNG CHẠY trong production. STRESS_MID chưa được
    nối: run_live_day truyền stress_bars_1015={} và scheduler không có slot ~10:15 ET,
    nên nhánh vào lệnh stress không bao giờ chạy. Đừng đọc test này thành "stress đang
    được bảo vệ" — hiện không có vị thế stress nào để mà bảo vệ.

    Lý do vẫn phải chốt: candidate stress KHÔNG có trường "exit", nên decide_day giữ nó
    lại như mọi vị thế khác (`if newp.exit_day == day` là False) và nó SẼ tới khối STP
    ngay khi sleeve được bật. Khi đó nó phải được đặt stop NGAY, không thừa hưởng luật
    hoãn vốn đo trên engine swing.
    """
    broker = _RecordingMockBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(), contracts_by_inst={"MES": 1},
        signal_fn=_stress_hold_signal, breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json", today=DAY1,
        now=DAY1 + pd.Timedelta(hours=14, minutes=5),
    )
    runner.run_day(DAY1)

    assert len(broker.stp_calls) == 1, (
        f"stress KHÔNG được hoãn — nó không chạy engine swing. {broker.stp_calls}")
    assert broker.stp_calls[0]["cluster"] == STRESS_CLUSTER
    assert runner.state.open_positions[0].stop_order_id is not None

# ── STP12: cả 5 instrument, không chỉ 1 mã đại diện mỗi cluster ──────────────

_ALL_FIVE = [("MES", CLUSTER, 5000.0, 4950.0),
             ("MNQ", CLUSTER, 17000.0, 16900.0),
             ("MYM", CLUSTER, 38000.0, 37800.0),
             ("M2K", CLUSTER, 2000.0, 1980.0),
             ("MNKD", NKD_CLUSTER, 38000.0, 37600.0)]


@pytest.mark.parametrize("inst,cluster,entry,stop", _ALL_FIVE)
def test_stp12_every_live_instrument_defers(tmp_path, inst, cluster, entry, stop):
    """`_stop_deferred` chỉ đọc cluster, không đọc tên mã — nên về lập luận thì MES đại
    diện được cho MNQ/MYM/M2K. Chốt bằng assertion vì lập luận là thứ trượt được: chỉ
    cần một chỗ nào đó rẽ nhánh theo instrument (point value, tick, sizing) là đủ hỏng,
    và sẽ hỏng âm thầm — vị thế có STP đặt ngay lúc khớp, đúng cấu hình lỗ.
    """
    broker = _RecordingMockBroker({}, ACCOUNT)

    def _sig(day, bars, held):
        if day == DAY1:
            return [dict(inst=inst, direction="LONG", cluster=cluster,
                         risk_sized=400.0, entry=entry, stop=stop,
                         exit=None, pnl_sized=100.0)], []
        return [], []

    runner = FuturesRunner(
        broker=broker, guard=_make_guard(), contracts_by_inst={inst: 1},
        signal_fn=_sig, breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json", today=DAY1,
        now=DAY1 + pd.Timedelta(hours=14, minutes=5),
    )
    runner.run_day(DAY1)

    assert broker.stp_calls == [], f"{inst} phải hoãn STP, đã gửi: {broker.stp_calls}"
    pos = runner.state.open_positions[0]
    assert pos.inst == inst and pos.cluster == cluster
    assert pos.stop_price == stop, "mức stop vẫn phải ghi để B4 đặt hôm sau"
    assert pos.stop_order_id is None


@pytest.mark.parametrize("inst,cluster,entry,stop", _ALL_FIVE)
def test_stp12b_every_live_instrument_gets_its_stop_next_day(tmp_path, inst, cluster,
                                                             entry, stop):
    """Nửa còn lại: hoãn mà không bao giờ đặt thì tệ hơn hẳn đặt ngay."""
    broker = _RecordingMockBroker({}, ACCOUNT)

    def _sig(day, bars, held):
        if day == DAY1:
            return [dict(inst=inst, direction="LONG", cluster=cluster,
                         risk_sized=400.0, entry=entry, stop=stop,
                         exit=None, pnl_sized=100.0)], []
        return [], []

    kw = dict(broker=broker, guard=_make_guard(), contracts_by_inst={inst: 1},
              signal_fn=_sig, breaker=CircuitBreaker(account=ACCOUNT),
              positions_path=tmp_path / "pos.json")
    FuturesRunner(today=DAY1, now=DAY1 + pd.Timedelta(hours=14, minutes=5),
                  **kw).run_day(DAY1)
    assert broker.stp_calls == []

    FuturesRunner(today=DAY2, now=DAY2 + pd.Timedelta(hours=14, minutes=5),
                  **kw)                        # B4 chạy trong __init__
    assert len(broker.stp_calls) == 1, f"{inst}: B4 phải đặt STP, {broker.stp_calls}"
    assert broker.stp_calls[0]["inst"] == inst
    assert broker.stp_calls[0]["stop_price"] == stop

# ── STP13: lối thoát PHỔ BIẾN nhất phải được ghi sổ ──────────────────────────
#
# Nhánh `_stp_status == "FILLED"` từng chỉ dọn vị thế rồi thôi, trong khi nhánh dự
# phòng NOT_FOUND (hiếm hơn nhiều) mới gọi _book_realised + _record_stop_exit. Ngược
# đời: stop báo FILLED là đường thoát THƯỜNG GẶP — chandelier chiếm ~79,5% số lệnh
# thoát — nên sổ mà circuit breaker đọc không nhúc nhích cho phần lớn giao dịch.
# Đo trên trade_log.jsonl thật: 13 OPEN, 6 CLOSE.


class _FillReportingBroker(_RecordingMockBroker):
    """Báo STP đã khớp, và trả được giá khớp thật qua reqExecutions."""

    def __init__(self, bars, account, price=4948.25, shares=1):
        super().__init__(bars, account, stp_status="FILLED")
        self._exec = {"price": price, "shares": shares,
                      "time": "2024-03-12 09:31:00", "permId": 777}

    def find_execution(self, order_id, inst=None):
        return dict(self._exec)


class _AmnesiacBroker(_RecordingMockBroker):
    """Báo FILLED nhưng đã quên bản ghi khớp — reqExecutions chỉ nhớ ~2 ngày."""

    def __init__(self, bars, account):
        super().__init__(bars, account, stp_status="FILLED")

    def find_execution(self, order_id, inst=None):
        return None


def _persisted(tmp_path, stop_price=4950.0, entry_price=5000.0):
    f = tmp_path / "pos.json"
    f.write_text(json.dumps({
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "entry_price": entry_price,
            "stop_price": stop_price, "stop_order_id": "ibkr-456",
        }],
        "breaker": {},
    }))
    return f


def _runner_with(broker, pos_file, log_path):
    return FuturesRunner(
        broker=broker, guard=_make_guard(), contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file, trade_log_path=log_path, today=DAY2,
    )


def _closes(log_path):
    if not Path(log_path).exists():
        return []
    return [json.loads(l) for l in Path(log_path).read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("type") == "CLOSE"]


def test_stp13_a_filled_stop_writes_the_close_record(tmp_path):
    """Không có gì khác ghi bản ghi này: runner không gửi lệnh nào khi stop tự khớp,
    nên đường send_order — vốn log mọi fill khác — không bao giờ chạy."""
    log_path = tmp_path / "trades.jsonl"
    runner = _runner_with(_FillReportingBroker({}, ACCOUNT), _persisted(tmp_path), log_path)

    assert runner.state.open_positions == [], "vị thế phải được dọn"
    rows = _closes(log_path)
    assert len(rows) == 1, f"phải có đúng 1 bản ghi CLOSE, có {len(rows)}"
    assert rows[0]["inst"] == "MES"


def test_stp13b_the_actual_fill_price_is_used_not_the_placed_level(tmp_path):
    """Giá khớp thật (4948.25) khác mức đã đặt (4950.00) — chênh 1.75 điểm chính là
    trượt giá của lệnh dừng. Ghi mức đã đặt thay vì giá khớp sẽ xoá mất đúng con số
    cần đo, và luôn theo hướng có lợi."""
    log_path = tmp_path / "trades.jsonl"
    _runner_with(_FillReportingBroker({}, ACCOUNT, price=4948.25),
                 _persisted(tmp_path, stop_price=4950.0), log_path)
    row = _closes(log_path)[0]
    # Bản ghi giữ CẢ HAI vế — và đó chính là phép đo trượt giá lệnh dừng:
    # fill_price - expected_stop. Ghi mỗi mức đã đặt sẽ xoá mất con số này, và
    # luôn xoá theo hướng có lợi.
    assert row["fill_price"] == pytest.approx(4948.25), f"giá khớp thật: {row}"
    assert row["expected_stop"] == pytest.approx(4950.0), f"mức đã đặt: {row}"
    assert row["fill_price"] - row["expected_stop"] == pytest.approx(-1.75)
    assert row["source"] == "B3_STP_EXIT", "phải ghi đúng nhánh đã phát hiện"


def test_stp13c_the_ledger_moves_on_a_stop_exit(tmp_path):
    """Sổ sleeve là equity mà circuit breaker đọc. Không ghi = breaker canh một mức
    vốn chưa từng tồn tại, đúng điều docstring của _book_realised cảnh báo."""
    b = _FillReportingBroker({}, ACCOUNT, price=4948.25)
    runner = _runner_with(b, _persisted(tmp_path), tmp_path / "t.jsonl")
    # LONG 5000 → 4948.25 = lỗ 51.75 điểm; dấu ÂM là điều phải thấy
    assert runner.state.equity < ACCOUNT, (
        f"sổ phải giảm sau khi stop khớp lỗ; equity={runner.state.equity}")


class _CancelFailsWithStatus(_CancelFailsBroker):
    """The existing _CancelFailsBroker, with the order's REAL state made explicit.

    That is the whole point of M2: cancel_order returning False says nothing on its own.
    reqAllOpenOrders is filtered on `not isDone()`, so a stop that has already FILLED is
    absent from it and cancel_order returns False for the most benign reason available.
    """

    def __init__(self, bars, account, real_status):
        super().__init__(bars, account, stp_status=real_status)


def _orphan_events(runner):
    return [e for e in runner._events
            if "ORPHAN" in (e.get("message") or "").upper()]


def _close_with(broker, tmp_path):
    """DAY1 opens, DAY2 closes — the close is what cancels the stop."""
    _runner_on(broker, tmp_path, DAY1).run_day(DAY1)
    r2 = _runner_on(broker, tmp_path, DAY2)
    r2.run_day(DAY2)
    return r2


def test_stp14_a_stop_that_already_filled_is_not_called_an_orphan(tmp_path):
    """M2. cancel_order returns False for a stop that has already fired, and the runner
    announced the exact opposite of the truth.

    `reqAllOpenOrders()` is filtered with `not t.isDone()`, so a FILLED stop is simply
    not in the list, `matching` is empty and the method returns False. The runner then
    logged CRITICAL: "the stop is still working at the broker and will open an
    unintended position when it fires." It is not working. It fired.

    This matters beyond the wording. run_scheduler lifts every CRITICAL/ERROR line out
    of a child's output into the scheduler log — a mechanism added precisely because a
    REAL "STP ORPHAN" was swallowed on 2026-08-10. Manufacturing false ones spends the
    credibility of the alarm that incident bought.
    """
    runner = _close_with(_CancelFailsWithStatus({}, ACCOUNT, "FILLED"), tmp_path)

    orphans = _orphan_events(runner)
    assert not orphans, (
        f"the stop had already filled; calling it a live orphan sends the operator to "
        f"TWS to cancel an order that does not exist: {orphans}")


def test_stp14b_a_stop_that_is_still_live_is_still_an_orphan(tmp_path):
    """The control, and the reason this fix is not simply "stop alarming".

    A stop that genuinely remains working after a failed cancel is the dangerous case
    the alarm exists for — live 2026-08-05 carried two, one of which would have doubled
    a short rather than closing it. If this test does not stay red-capable, the fix
    above is indistinguishable from deleting the guard.
    """
    runner = _close_with(_CancelFailsWithStatus({}, ACCOUNT, "PENDING"), tmp_path)

    orphans = _orphan_events(runner)
    assert orphans, (
        "the stop is still live at the broker after a failed cancel and nothing said "
        "so — this is the case the alarm was written for")
    assert any(e.get("level") == "CRITICAL" for e in orphans), (
        f"a live orphaned stop must stay CRITICAL: {orphans}")


def test_stp14c_an_unlocatable_stop_does_not_claim_to_be_live(tmp_path):
    """NOT_FOUND is not evidence of anything. The old message asserted the stop was
    "still working at the broker" without ever having asked, which is the same defect
    as the audit's "a check that compares a value with itself": a claim with no
    measurement behind it."""
    runner = _close_with(_CancelFailsWithStatus({}, ACCOUNT, "NOT_FOUND"), tmp_path)

    said = " ".join((e.get("message") or "") for e in runner._events)
    assert "still live at broker" not in said, (
        f"the broker could not locate the order, so the runner cannot testify that it "
        f"is working: {said}")


def test_stp13e_a_forgotten_fill_still_reaches_the_trade_log(tmp_path):
    """H4 path B. The money moves; the order book has to say so too.

    stp13d below already pins that this path BOOKS the loss and warns the price is an
    estimate. What nothing pinned is the trade log: _book_realised ran and
    _record_stop_exit did not, so equity fell while trade_log.jsonl gained no row.

    Everything derived from the trade log is then short by exactly that trade —
    including paper_epoch_closed_realized, the headline P&L figure — and the gap has a
    ready-made explanation sitting next to it (ledger_offset_explanation:
    MATCH_PRE_EPOCH_CARRY_FILL) that would absorb the discrepancy without anyone
    looking. A systematically biased number with an excuse attached is worse than a
    missing one.

    Reachable whenever a stop fires and is noticed more than ~2 days later, which is
    the Sunday-reopen sweep's whole purpose (83ac849).
    """
    log_path = tmp_path / "t.jsonl"
    runner = _runner_with(_AmnesiacBroker({}, ACCOUNT), _persisted(tmp_path), log_path)

    assert runner.state.equity < ACCOUNT, (
        "precondition: this path must have booked the loss, or the test below proves "
        "nothing about a gap between the two ledgers")

    closes = _closes(log_path)
    assert closes, (
        "equity moved but the trade log gained no CLOSE row, so every figure derived "
        "from it is short by this trade")
    assert closes[0].get("fill_price_estimated") is True, (
        "the row carries the PLACED level, not a real fill price. Unmarked it is "
        "indistinguishable from a genuine fill and the estimate spreads silently: "
        f"{closes[0]}")


def test_stp13g_a_stop_exit_records_the_money_it_booked(tmp_path):
    """PAPER_DASHBOARD_AUDIT C6, the half the schema fix did not close.

    Unifying the CLOSE schema gave every row a pnl_sized key. The stop-exit writer
    still left it null — while _book_realised had already moved that exact amount into
    the sleeve ledger. So the row exists, the money moved, and the column that says how
    much is blank.

    That matters more here than anywhere else: chandelier stops are 79.5% of exits, so
    this is the majority of the ledger, and any figure rebuilt from trade_log.jsonl was
    reading zero for most of the P&L it is supposed to explain.

    The value is TAKEN from _book_realised, which already returns what it added. Not
    recomputed from fill_price and entry_price — that would be a second answer to the
    same question, and M4 is the standing lesson about two sources for one number.
    """
    log_path = tmp_path / "t.jsonl"
    runner = _runner_with(_AmnesiacBroker({}, ACCOUNT), _persisted(tmp_path), log_path)

    booked = ACCOUNT - runner.state.equity
    assert booked > 0, (
        f"precondition: the stop exit must have moved the ledger, else this proves "
        f"nothing. equity={runner.state.equity}")

    closes = _closes(log_path)
    assert closes, "no CLOSE row at all — that is stp13e's job, not this one"
    assert closes[0].get("pnl_sized") is not None, (
        f"the ledger moved by {booked:.2f} and the row says nothing: {closes[0]}")
    assert closes[0]["pnl_sized"] == pytest.approx(-booked), (
        f"the row must carry what was actually booked ({-booked:.2f}), not a "
        f"recomputation: got {closes[0]['pnl_sized']}")


def test_stp13f_a_same_day_round_trip_reaches_the_trade_log(tmp_path):
    """H4 path F. Two real orders, money booked, and not one line written.

    A same-day trade never becomes an OpenPos, so it misses the exits loop that logs
    every other close — and it also never went through the entry logging, so BOTH sides
    are missing. Currently zero impact only because the STRESS_MID cron at 10:20 is off;
    it becomes live the moment that sleeve is switched on.
    """
    class _PricedBroker(_RecordingMockBroker):
        """MockBroker returns avg_price 0.0, and the same-day block is gated on a real
        price — correctly, since it must not book or log a fill it has no price for. A
        broker that never reports one cannot reach the path under test."""

        def send_order(self, o):
            f = super().send_order(o)
            return Fill(o.inst, o.action, o.direction, o.contracts, o.cluster,
                        pnl_sized=f.pnl_sized, status="FILLED",
                        avg_price=5000.0 if o.action == "OPEN" else 5010.0)

    log_path = tmp_path / "t.jsonl"
    broker = _PricedBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(), contracts_by_inst={"MES": 1},
        signal_fn=_sameday_signal, breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json", trade_log_path=log_path,
        today=DAY1, now=pd.Timestamp(DAY1) + pd.Timedelta(hours=14, minutes=5),
    )
    runner.run_day(DAY1)

    rows = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines()] \
        if log_path.exists() else []
    kinds = [r.get("type") for r in rows]

    assert "OPEN" in kinds and "CLOSE" in kinds, (
        f"a same-day round trip sent two real orders and left no record of either; "
        f"live_history.build_snapshots would see neither side. rows={rows}")


def test_stp13d_a_forgotten_fill_is_booked_but_labelled_an_estimate(tmp_path, caplog):
    """reqExecutions chỉ nhớ ~2 ngày. IBKR nói FILLED nên vị thế CHẮC CHẮN đã đóng —
    bỏ qua sẽ làm sổ sai theo chiều ngược lại. Ghi theo mức đã đặt, nhưng phải NÓI
    rằng đó là ước lượng: một xấp xỉ im lặng là cách sổ trôi mà không ai biết."""
    import logging
    log_path = tmp_path / "t.jsonl"
    with caplog.at_level(logging.WARNING):
        runner = _runner_with(_AmnesiacBroker({}, ACCOUNT), _persisted(tmp_path), log_path)
    assert runner.state.open_positions == []
    assert runner.state.equity < ACCOUNT, "vẫn phải ghi sổ, không được bỏ qua"
    assert any("UOC LUONG" in r.message or "UOC LUONG" in str(r.msg)
               for r in caplog.records),         "phải cảnh báo rằng con số là ước lượng, không phải giá khớp thật"

