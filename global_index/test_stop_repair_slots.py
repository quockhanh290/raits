"""Quét sửa stop: chỉ nằm trong khoảng trống, và không được biến thành đường vào lệnh.

Job này thêm 19 lần dựng runner mỗi ngày vào một hệ đang chạy. Hai cách nó có thể hỏng, cả
hai đều im lặng:

  * **chen vào cửa sổ vào lệnh** — mỗi lần dựng runner là một lượt B3 nữa, tức một cơ hội
    nữa dính MISMATCH giả và halt entry. Ngoài cửa sổ thì halt không tốn gì; trong cửa sổ
    thì nó ăn mất chính lệnh mà cửa sổ tồn tại để bắt.
  * **được cho gọi `run_day`** — lúc đó nó sinh tín hiệu, và một lần chạy lúc 11:20 sẽ đóng
    vị thế STRESS_MID sớm ba tiếng. Đó là lý do `test_stress_slot_invariant` miễn trừ các
    job này; miễn trừ ấy chỉ đúng chừng nào `signal_fn` còn rỗng và `run_day` còn không được
    gọi. Test dưới ghim đúng hai điều kiện đó.

Xem `docs/futures/OPERATIONS.md`, mục "Khung thời gian đặt lệnh — CÓ CHỦ ĐÍCH".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("apscheduler")

from global_index.run_scheduler import make_scheduler

# Hai cửa sổ vào lệnh, quy về ET. NKD: 14:00-15:55 JST = 01:00-02:55 ET (hè).
ENTRY_WINDOWS = [((1, 0), (2, 55)), ((14, 0), (15, 55))]
MAXHOLD = (9, 31)


def _jobs():
    sched = make_scheduler(port=4002, dry_run=True)
    try:
        return list(sched.get_jobs())
    finally:
        sched.shutdown(wait=False) if sched.running else None


def _hhmm(job):
    f = {str(x.name): str(x) for x in job.trigger.fields}
    try:
        return int(f["hour"]), int(f["minute"])
    except (KeyError, ValueError):
        return None


def _repair_slots():
    return sorted(_hhmm(j) for j in _jobs() if j.id.startswith("stop_repair"))


def _src(name):
    return (Path(__file__).resolve().parents[1] / "global_index" / name).read_text(
        encoding="utf-8")


# ── vị trí ───────────────────────────────────────────────────────────────────

def test_no_repair_slot_lands_in_an_entry_window():
    """Bất biến chính. Một lượt B3 thừa bên trong cửa sổ có thể halt entry đúng lúc cửa sổ
    đang làm việc của nó."""
    bad = [s for s in _repair_slots()
           for lo, hi in ENTRY_WINDOWS if lo <= s <= hi]
    assert not bad, f"slot quet sua nam trong cua so vao lenh: {bad}"


def test_no_repair_slot_collides_with_the_maxhold_job():
    """09:31 đóng vị thế đủ hạn. Một runner khác dựng cùng lúc sẽ tranh clientId và
    tranh live_positions.json."""
    assert MAXHOLD not in _repair_slots()


def test_the_repair_slots_cover_all_three_gaps():
    """Ba khoảng trống đo được: 15:55->01:10 (9h15), 02:55->09:31 (6h36),
    09:31->14:05 (4h34). Mỗi khoảng phải có ít nhất một slot, nếu không thì lỗ vẫn còn và
    job này chỉ tạo cảm giác đã lấp."""
    slots = _repair_slots()
    def _any_in(lo, hi):
        return any(lo <= s <= hi for s in slots)
    assert _any_in((16, 0), (23, 59)) or _any_in((0, 0), (1, 0)), "ho 15:55-01:10 chua phu"
    assert _any_in((3, 0), (9, 30)), "ho 02:55-09:31 chua phu"
    assert _any_in((9, 32), (14, 4)), "ho 09:31-14:05 chua phu"


def test_every_gap_hour_is_covered_at_most_once():
    """Không có hai slot cùng giờ — hai runner cùng lúc là tranh chấp, không phải dự phòng."""
    slots = _repair_slots()
    assert len(slots) == len(set(slots))


# ── điều kiện làm cho việc miễn trừ bất biến STRESS là hợp lệ ────────────────

def test_the_repair_job_never_generates_signals():
    """`signal_fn` rỗng là nửa đầu của lý do job này vô hại với STRESS_MID."""
    src = _src("run_stop_repair.py")
    assert "signal_fn=lambda d, b, h: ([], [])" in src, \
        "signal_fn khong con rong — job quet sua co the sinh lenh"


def test_the_repair_job_never_calls_run_day():
    """Nửa sau. `diff_desired_vs_held` chỉ chạy trong `run_day`; gọi nó ở đây thì một lần
    quét lúc 11:20 sẽ đóng vị thế STRESS_MID sớm ba tiếng, và test_stress_slot_invariant
    đang miễn trừ chính các job này nên sẽ không bắt được."""
    src = _src("run_stop_repair.py")
    for forbidden in ("run_day(", "run_maxhold_exit("):
        assert forbidden not in src, f"run_stop_repair goi {forbidden} — mien tru khong con dung"


def test_the_repair_job_passes_both_today_and_now():
    """Runner tự đọc đồng hồ nếu thiếu, và hai khái niệm "hôm nay" trong một lần chạy là
    cách cửa sổ hoãn bị tính sai."""
    src = _src("run_stop_repair.py")
    assert "today=now.normalize()" in src and "now=now," in src


def test_the_repair_job_shares_the_runners_client_id():
    """Bản đầu của test này khẳng định điều NGƯỢC LẠI — rằng job phải có id riêng "để khỏi
    đá nhau ra khỏi Gateway". Giả định đó sai, và cái sai lộ ra cùng ngày:

    IBKR chỉ nhận lệnh huỷ từ **chính clientId đã đặt lệnh**. B4 trong job này ĐẶT stop; đặt
    bằng id riêng thì sau này runner (id 1) không huỷ được chính stop đó khi đóng vị thế, và
    mỗi lần đóng lại để lại một lệnh mồ côi — thứ khi khớp sẽ MỞ một vị thế ngược chiều.

    Chuyện đá nhau được xử bằng LỊCH chứ không bằng id: các slot quét sửa nằm ở phút :20
    trong ba khoảng trống, không giao với slot nào khác (xem test ở trên).

    Bất biến đầy đủ nằm ở `test_stop_client_id.py`."""
    src = _src("run_stop_repair.py")
    assert '"--client-id", type=int, default=1' in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
