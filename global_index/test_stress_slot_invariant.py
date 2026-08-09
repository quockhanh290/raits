"""Bất biến giữ cho STRESS_MID chạy đúng luật: KHÔNG slot nào giữa 10:20 và 14:05 ET.

`_mark_held_unchanged` không được gọi cho cluster stress, nên `diff_desired_vs_held`
thấy khoá `(inst, "roska4_stress")` vắng trong `desired` và đóng vị thế ở **lần chạy kế
tiếp** — bất kể lần đó là khi nào.

Với lịch hiện tại lần kế tiếp là slot 14:05, gần đúng mốc 14:00 của `StressMidAdapter`,
và đó là lý do sleeve giữ được ~91% luật đã kiểm định (đo `model_stress_exits.py`:
+$12.850 vs +$14.151). Thêm một slot xen giữa buổi sáng thì vị thế bị đóng sau vài phút
và sleeve tụt xuống **−$450** — im lặng, không guard nào kêu, không log nào đỏ.

Đó là loại hỏng mà chú thích không chặn được: người thêm slot mới sẽ không đọc chú thích
nằm ở job khác. Nên bất biến được viết thành test.

Sửa bằng cách thêm `_mark_held_unchanged` cho stress là SAI — khi đó không gì đóng vị thế
nữa và nó qua đêm. Muốn bỏ bất biến này thì phải cho stress một luật thoát tường minh
trước, không phải dựa vào nhánh dự phòng của diff.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("apscheduler")

from global_index.run_scheduler import make_scheduler

# Các job KHÔNG gọi generate_today_signals nên không đóng vị thế stress.
# maxhold_exit chạy run_maxhold_exit (module riêng, signal_fn trả rỗng);
# preflight chỉ cập nhật parquet + spy csv; heartbeat chỉ ghi log.
_HARMLESS = {"heartbeat", "maxhold_exit", "preflight"}

STRESS_H, STRESS_M = 10, 20
AFTERNOON_H, AFTERNOON_M = 14, 5


def _jobs():
    sched = make_scheduler(port=4002, dry_run=True)
    try:
        return list(sched.get_jobs())
    finally:
        sched.shutdown(wait=False) if sched.running else None


def _hhmm(job):
    """(hour, minute) của cron job, hoặc None nếu không cố định."""
    f = {str(x.name): str(x) for x in job.trigger.fields}
    try:
        return int(f["hour"]), int(f["minute"])
    except (KeyError, ValueError):
        return None


def test_the_stress_slot_exists_at_1020_et():
    j = [x for x in _jobs() if x.id == "stress_mid"]
    assert j, "khong tim thay job stress_mid"
    assert _hhmm(j[0]) == (STRESS_H, STRESS_M)


def test_nothing_calls_run_live_day_between_1020_and_1405():
    """Bất biến chính. Một job mới nằm trong khoảng này sẽ đóng vị thế stress sớm
    và kéo sleeve từ +$12.850 xuống −$450 mà không phát ra tín hiệu nào."""
    offenders = []
    for job in _jobs():
        if job.id in _HARMLESS or job.id == "stress_mid":
            continue
        hm = _hhmm(job)
        if hm is None:
            continue
        if (STRESS_H, STRESS_M) < hm < (AFTERNOON_H, AFTERNOON_M):
            offenders.append((job.id, hm))
    assert not offenders, (
        "job goi run_live_day trong khoang 10:20-14:05 ET se dong vi the STRESS_MID "
        f"som: {offenders}. Xem docstring — bo bat bien nay doi hoi cho stress mot "
        "luat thoat tuong minh truoc.")


def test_the_afternoon_slot_is_the_one_that_closes_stress():
    """Nửa còn lại: phải CÓ một slot ở 14:05, nếu không thì không gì đóng vị thế
    stress cả và nó qua đêm — hỏng theo chiều ngược lại."""
    assert any(_hhmm(j) == (AFTERNOON_H, AFTERNOON_M) for j in _jobs()), \
        "khong con slot 14:05 — vi the stress se khong duoc dong"


def test_only_the_morning_slot_carries_stress_entry():
    """Slot chiều mà cũng bật --stress-entry thì nó vào lệnh bằng tín hiệu 10:15 ở
    giá 14:05 — đúng hình dạng độ trễ đã làm hỏng sleeve swing."""
    src = (Path(__file__).resolve().parents[1]
           / "global_index" / "run_scheduler.py").read_text(encoding="utf-8")
    assert src.count("stress_entry=True") == 1, \
        "chi duy nhat job 10:20 duoc truyen stress_entry=True"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
