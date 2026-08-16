"""Tiến trình con thoát mã 0 mà đã kêu CRITICAL thì KHÔNG được im lặng.

Sự cố 2026-08-10, tìm ra bằng cách đi hỏi thẳng IBKR chứ không phải bằng log:

  * 09:31 MAX_HOLD đóng vị thế MYM. Lệnh CLOSE thành công → `run_maxhold_exit` thoát 0.
  * Nhưng `cancel_order('12')` thất bại. Runner đã kêu đúng lúc đó:
    `STP ORPHAN: cancel_order(12) returned False ... will open an unintended position
    when it fires`.
  * `_run` bắt stdout/stderr của con **rồi vứt đi** vì `returncode == 0`, và ghi vào log
    đúng một dòng: `completed OK`.
  * Lệnh BUY STP mồ côi treo trên sàn suốt buổi. Nếu MYM chạm 54708.68 nó khớp và MỞ một
    vị thế LONG không ai đặt.

Guard đã bắn đúng; ống dẫn ném nó đi. Đó là lý do lọc phải theo **mức độ**, không theo **mã
thoát**: "thành công" của một tiến trình chỉ nói lên việc nó làm xong việc chính, không nói
lên rằng mọi việc phụ đều ổn.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("apscheduler")

from global_index import run_scheduler as rs


class _Result:
    def __init__(self, rc, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _capture(monkeypatch, result):
    """Chạy _run với subprocess giả, trả (ok, các dòng log ERROR, các dòng log INFO)."""
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **k: result)
    errs, infos = [], []
    monkeypatch.setattr(rs.log, "error", lambda m, *a: errs.append(m % a if a else m))
    monkeypatch.setattr(rs.log, "info", lambda m, *a: infos.append(m % a if a else m))
    ok = rs._run(["x"], label="T", dry_run=False)
    return ok, errs, infos


ORPHAN = ("2026-08-10 09:31:02  CRITICAL  global_index.runner — STP ORPHAN: "
          "cancel_order(12) returned False for MYM/roska4_swing")


def test_a_critical_line_survives_a_zero_exit(monkeypatch):
    """Ca đã xảy ra thật."""
    ok, errs, _ = _capture(monkeypatch, _Result(0, out=ORPHAN))
    assert ok is True, "van phai bao thanh cong — viec chinh da xong"
    assert any("STP ORPHAN" in e for e in errs), "dong CRITICAL bi nuot"


def test_an_error_line_survives_too(monkeypatch):
    ok, errs, _ = _capture(
        monkeypatch, _Result(0, err="2026-08-10  ERROR  runner — place_stop raised"))
    assert ok is True
    assert any("place_stop raised" in e for e in errs)


def test_a_hung_child_is_killed_instead_of_holding_the_session(monkeypatch):
    """H5. subprocess.run had no timeout, so a child that never returns never returns.

    Slots are serialised by _slot_lock. A run_live_day that hangs holds it for the rest
    of the session and every later slot logs only "SKIPPED — previous run_live_day still
    in flight", at WARNING — the same line a perfectly normal overlap produces, because
    a run takes ~5.5 min in a 5-minute slot. The trading day ends and the log looks
    ordinary.

    The waits inside the broker all have ceilings; the synchronous ib_insync calls
    (qualifyContracts, reqAllOpenOrders, reqExecutions, reqHistoricalData) do not, and
    nothing above them could cut one short.
    """
    calls = {}

    def _boom(*a, **k):
        calls["timeout"] = k.get("timeout")
        raise rs.subprocess.TimeoutExpired(cmd=a[0] if a else ["x"],
                                           timeout=k.get("timeout") or 0)

    monkeypatch.setattr(rs.subprocess, "run", _boom)
    errs = []
    monkeypatch.setattr(rs.log, "error", lambda m, *a: errs.append(m % a if a else m))
    monkeypatch.setattr(rs.log, "critical", lambda m, *a: errs.append(m % a if a else m))
    monkeypatch.setattr(rs.log, "info", lambda m, *a: None)

    ok = rs._run(["x"], label="T", dry_run=False)

    assert calls.get("timeout"), (
        "subprocess.run was called with no timeout, so a hung child is waited on "
        "forever and the slot mutex is never released")
    assert ok is False, "a killed run must not report success"
    assert any("TIMEOUT" in e.upper() for e in errs), (
        f"the failure has to name itself; sharing wording with an ordinary overlap is "
        f"what made a dead session unreadable. logged={errs}")


def test_an_overlap_and_a_dead_session_do_not_read_the_same():
    """The other half of H5, and the half a timeout alone does not fix.

    One slot overlapping the previous is routine and must stay quiet. A run that has
    held the mutex far longer than any run legitimately takes is a dead session, and it
    has to say so in different words — otherwise the operator is reading the same
    WARNING either way.
    """
    routine = rs._inflight_report(elapsed_secs=90.0)
    stuck = rs._inflight_report(elapsed_secs=45 * 60.0)

    assert routine.level == "warning", "a normal overlap must not cry wolf"
    assert stuck.level in ("error", "critical"), (
        "a mutex held for 45 minutes is not an overlap; it has to escalate so "
        "run_scheduler's own CRITICAL/ERROR echo picks it up")
    assert "90" in routine.message or "1.5" in routine.message, (
        f"the message must carry HOW LONG, or the two cases stay indistinguishable: "
        f"{routine.message}")
    assert routine.message != stuck.message


def test_a_clean_run_stays_quiet(monkeypatch):
    """Nửa còn lại: chạy trơn thì vẫn chỉ một dòng INFO. Một bản vá làm log ồn lên mỗi slot
    sẽ tự đánh mất tác dụng của chính nó."""
    ok, errs, infos = _capture(monkeypatch, _Result(0, out="MAX_HOLD EXIT COMPLETE\nclosed: 1"))
    assert ok is True
    assert errs == []
    assert any("completed OK" in i for i in infos)


def test_a_real_failure_still_reports_the_exit_code(monkeypatch):
    ok, errs, _ = _capture(monkeypatch, _Result(1, err="Traceback ...\nValueError: boom"))
    assert ok is False
    assert any("exited with code 1" in e for e in errs)


def test_the_echo_is_bounded(monkeypatch):
    """Con có thể in hàng nghìn dòng. Chỉ lấy phần đuôi — không để một lần chạy bệnh làm
    ngập file log mà mọi cảnh báo khác trôi mất."""
    flood = "\n".join(f"CRITICAL dong {i}" for i in range(500))
    _ok, errs, _ = _capture(monkeypatch, _Result(0, out=flood))
    assert len(errs) <= rs._FAIL_TAIL_LINES + 1


def test_it_does_not_match_the_word_inside_ordinary_text(monkeypatch):
    """Lọc theo chuỗi thì phải chấp nhận nó thô. Ghim hành vi hiện tại để ai đó siết lại
    (ví dụ khớp theo cột mức độ) biết mình đang đổi cái gì."""
    ok, errs, _ = _capture(monkeypatch, _Result(0, out="no CRITICAL issues found"))
    assert ok is True
    # 1 dong tieu de + 1 dong noi dung. Khop tho theo chuoi: bao dong gia con hon bo sot.
    assert len(errs) == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
