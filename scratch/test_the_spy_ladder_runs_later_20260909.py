"""Thang lấy SPY buổi tối lùi lại hai tiếng. TỆP MỚI.

Đo được trước khi đổi
---------------------
Mười một phiên liên tiếp, cả ba nấc buổi tối đều hỏng và chỉ nấc 00:45 lấy được:

    25-26/08          16:20 ĐƯỢC
    27/08 → 09/09     16:20 hỏng · 16:45 hỏng · 17:15 hỏng · 00:45 ĐƯỢC (7/7 lần nó chạy)

Cả ba nấc nói cùng một câu: *"chuỗi vẫn dừng ở hôm qua, chưa tới hôm nay — nhà cung cấp chưa
có"*. Và nhật ký đêm 08/09 tự ghi lại kết luận: *"nấc 17:15 đang chạy trước lúc nhà cung cấp
sẵn sàng, ít nhất là vào một số ngày."*

Ba lần báo hỏng mỗi ngày cho một chuyện không hỏng là một báo động người ta học cách bỏ qua —
kho này đã trả giá cho đúng chuyện đó một lần.

Chỗ tôi đã nêu và chủ dự án đã quyết khác
------------------------------------------
Tôi đề xuất đổi thứ mà thang HỎI: nó đòi giá đóng cửa của CHÍNH ngày vừa đóng, trong khi mọi
cổng đóng băng chỉ cần phiên TRƯỚC (`required_daily_close_through`). Đổi câu hỏi thì nấc 16:20
sẽ thành công ngay và không cần dời giờ nào.

Chủ dự án chọn **giữ nguyên câu hỏi và dời giờ thêm hai tiếng**. Ghi lại ở đây để lần sau
không ai đọc bản sửa này như thể nó là phương án duy nhất được cân nhắc.

Điều tệp này canh
-----------------
Ba nấc lùi đúng hai tiếng, thứ tự giữ nguyên, và nấc cuối vẫn phải nằm TRƯỚC lượt 00:45 —
nếu không thì cái lưới cuối cùng không còn là lưới cuối cùng.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: (id, giờ, phút) sau khi dời. Cũ là 16:20 / 16:45 / 17:15 — cả ba nằm TRƯỚC lúc dữ liệu về.
#:
#: Bằng chứng đã có sẵn trong kho, ở chính khối chú thích của thang: "giá đóng cửa 2026-09-01
#: vắng lúc 17:15 ET và đã có lúc 00:05 ET". Nên thang cũ dồn cả ba nấc vào khoảng chắc chắn
#: chưa có, và nấc duy nhất lấy được là lượt 00:45 sáng hôm sau.
#:
#: Thang mới TRẢI QUA khoảng ấy thay vì dồn trước nó. Ba nấc cách nhau gần đều, nấc cuối ở
#: 22:00 — vẫn trước 00:05 nên chưa chắc trúng, nhưng nằm trong vùng có thể trúng, khác hẳn
#: vùng chắc chắn trượt.
WANT = {
    "spy_refresh_pm": (18, 20),
    "spy_refresh_pm_r1": (20, 10),
    "spy_refresh_pm_r2": (22, 0),
}
LAST_CHANCE = ("spy_last_chance_pre_nkd", 0, 45)


def _jobs():
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        import global_index.run_scheduler as rs

        sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    finally:
        logging.disable(logging.NOTSET)
    out = {}
    for j in sched.get_jobs():
        f = {str(x.name): str(x) for x in j.trigger.fields}
        out[j.id] = (f.get("hour"), f.get("minute"), f.get("day_of_week"), j.name)
    return out


@pytest.mark.parametrize("job_id,hour,minute", [(k, *v) for k, v in WANT.items()])
def test_each_rung_moved_two_hours_later(job_id, hour, minute):
    j = _jobs().get(job_id)
    assert j, f"{job_id} không còn được đăng ký"
    assert (int(j[0]), int(j[1])) == (hour, minute), (job_id, j[:2])


def test_the_rungs_are_still_in_order():
    """Một thang mà nấc sau chạy trước nấc trước thì không còn là thang."""
    js = _jobs()
    times = [(int(js[k][0]) * 60 + int(js[k][1])) for k in
             ("spy_refresh_pm", "spy_refresh_pm_r1", "spy_refresh_pm_r2")]
    assert times == sorted(times), times
    assert len(set(times)) == 3, times


def test_the_last_rung_still_lands_before_the_overnight_look():
    """00:45 là lưới cuối trước cửa sổ NKD 01:10. Nấc buổi tối phải ở TRƯỚC nó, không thì
    thứ tự đảo và cái lưới cuối cùng thành cái lưới đầu tiên."""
    js = _jobs()
    lc = js.get(LAST_CHANCE[0])
    assert lc, "nấc 00:45 biến mất"
    assert (int(lc[0]), int(lc[1])) == (LAST_CHANCE[1], LAST_CHANCE[2]), lc[:2]
    r2 = js["spy_refresh_pm_r2"]
    assert int(r2[0]) > int(lc[0]), "nấc cuối buổi tối không còn nằm trong cùng buổi tối"
    assert int(r2[0]) < 24, "nấc cuối vắt qua nửa đêm — lúc đó nó không còn là nấc buổi tối"


def test_they_still_run_on_weekdays_only():
    js = _jobs()
    for k in WANT:
        assert js[k][2] == "mon-fri", (k, js[k][2])


def test_the_names_say_the_new_time():
    """Tên job hiện trên bảng và trong nhật ký. Một cái tên nói 16:20 cho một job chạy 18:20
    là đúng loại lời mô tả đã trôi khỏi thứ nó mô tả năm lần trong kho này."""
    js = _jobs()
    for k, (h, m) in WANT.items():
        assert f"{h:02d}:{m:02d}" in js[k][3], (k, js[k][3])


def test_nothing_else_moved():
    """Dời ba nấc, không dời cái gì khác. Bản sửa nào cũng dễ kéo theo hàng xóm."""
    js = _jobs()
    for k, want in (("track1_stop_repair_1620", (16, 20)),
                    ("track1_stop_repair_1820", (18, 20)),
                    ("track1_stop_repair_2020", (20, 20)),
                    ("track1_stop_repair_2220", (22, 20)),
                    ("preflight", (13, 45))):
        if k in js:
            assert (int(js[k][0]), int(js[k][1])) == want, (k, js[k][:2])


def test_the_ladder_does_not_hold_the_slot_mutex():
    """Nấc 18:20 trùng phút với `stop_repair_1820`. Vô hại — và phép kiểm này ghim lý do,
    chứ không để người sau phải tự suy: SPY refresh không đi qua `_run_guarded`, nên không
    ai bị bỏ vì tranh khoá. Nếu ai đó bọc nó vào khoá thì cú trùng phút thành một slot mất."""
    import inspect

    import global_index.run_scheduler as rs

    src = inspect.getsource(rs.make_scheduler)
    start = src.index('id="spy_refresh_pm"')
    body = src[start:src.index('id="spy_last_chance_pre_nkd"')]
    assert "_run_guarded" not in body, "thang SPY giờ giữ khoá — cú trùng phút 18:20 sẽ nuốt một job"
