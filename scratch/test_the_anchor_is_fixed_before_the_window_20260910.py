"""Sổ neo được sửa TRƯỚC khi cửa sổ mở, không phải sau. TỆP MỚI.

Chuyện đã xảy ra
----------------
Đêm 10/09 IBKR chuyển chuỗi liên tục NKD sang kỳ hạn tháng 12. Mười hai slot NKD từ chối
với `series_rolled`: bar đến từ NKDZ6, lịch sử neo trên NKDU6. Việc neo lại chỉ nằm trong
job 13:45, nên nó sửa được — mười hai tiếng SAU khi cửa sổ đã trôi qua.

Lần tới đắt hơn. Rổ Mỹ đáo hạn 18/09 và IBKR roll trước đáo hạn một ngày, nên roll dự kiến
~17/09. Calm (10:00) và Stress (10:35–12:30) đều chạy TRƯỚC 13:45 — cả hai mất trọn ngày.

Điều đã được cân nhắc và bác bỏ, không phải điều này
----------------------------------------------------
Ngay trong job 13:45 có một đoạn ghi chú bác bỏ việc "thêm một lần làm mới trước phiên
sáng", vì các slot sáng của Tuyến 1 vốn chạy trên pre-flight của NGÀY TRƯỚC cộng bar sống
từ broker, và đó là hợp đồng mọi con số của tuyến này được tạo ra dưới nó.

Hai job ở đây **không** làm việc bị bác bỏ ấy. Chúng không ghi một bar nào: bar cuối trong
tệp parquet không đổi, nên `required_data_through` không đổi, và cổng tươi mới thấy y hệt
những gì nó thấy hôm qua. Thứ duy nhất chúng chạm là **sổ neo** — và chỉ vào ngày hợp đồng
thật sự đổi, ~4 lần một năm.

Điều tệp này canh
-----------------
    1. hai job tồn tại, đúng giờ, và nằm TRƯỚC job đầu tiên chúng che
    2. chúng chạy ở chế độ chỉ-neo, và KHÔNG mang cờ sửa bar biên
    3. chúng không đụng vào hồ sơ pre-flight — một thất bại ở đây không được khoá cả ngày
    4. chúng HIỆN RA trong nhật ký công việc; một job chạy mà không ai thấy là chuyện kho
       này đã trả giá đúng ba giờ sau khi viết bài học đó vào báo cáo
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: (id job, giờ, phút, job đầu tiên nó che, giờ:phút của job ấy)
WANT = [
    ("anchor_check_0055", 0, 55, "track1_nkd_0110", (1, 10)),
    ("anchor_check_0916", 9, 16, "track1_maxhold_exit", (9, 31)),
]


def _sched():
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        import global_index.run_scheduler as rs

        return rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    finally:
        logging.disable(logging.NOTSET)


def _jobs():
    out = {}
    for j in _sched().get_jobs():
        f = {str(x.name): str(x) for x in j.trigger.fields}
        out[j.id] = (f.get("hour"), f.get("minute"), f.get("day_of_week"), j.name, j)
    return out


# ── giờ giấc ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("job_id,hour,minute,_g,_gt", WANT)
def test_the_job_is_registered_at_its_hour(job_id, hour, minute, _g, _gt):
    j = _jobs().get(job_id)
    assert j, f"{job_id} chưa được đăng ký"
    assert (int(j[0]), int(j[1])) == (hour, minute), j[:2]


@pytest.mark.parametrize("job_id,hour,minute,guarded,gt", WANT)
def test_it_lands_before_the_slot_it_protects(job_id, hour, minute, guarded, gt):
    """Neo sau khi cửa sổ mở thì không neo gì cả — đó chính là hiện trạng đang sửa.

    So bằng giờ ĐÃ ĐĂNG KÝ của cả hai job, không bằng hằng số ở bảng trên. Bản đầu của phép
    kiểm này lấy `hour`/`minute` từ tham số, nên khi dời job sang 01:55 — tức sau cửa sổ nó
    phải che — nó vẫn xanh: nó đang so hai con số của chính nó với nhau.
    """
    js = _jobs()
    assert job_id in js and guarded in js, f"{job_id} hoặc {guarded} biến mất"
    assert (int(js[guarded][0]), int(js[guarded][1])) == gt, js[guarded][:2]
    ran = int(js[job_id][0]) * 60 + int(js[job_id][1])
    assert ran < gt[0] * 60 + gt[1], (js[job_id][:2], gt)
    # Mười lăm phút là khoảng chủ dự án chọn: đủ cho một lượt fetch ~20 giây và một lần thử
    # lại, mà không sớm tới mức bar chồng lấn thưa đi.
    assert gt[0] * 60 + gt[1] - ran <= 20, "cách cửa sổ quá xa — dữ liệu đo sẽ cũ hơn cần thiết"


@pytest.mark.parametrize("job_id,_h,_m,_g,_gt", WANT)
def test_it_runs_on_weekdays(job_id, _h, _m, _g, _gt):
    assert _jobs()[job_id][2] == "mon-fri"


def test_the_scheduler_is_still_et_native():
    """Cả hai giờ trên là giờ ET. Nếu bộ lập lịch đổi sang giờ máy thì 00:55 ở Calgary là
    một thời điểm khác hẳn, và job sẽ chạy sau cửa sổ nó định che."""
    assert str(_sched().timezone) == "America/New_York"


# ── nó chạy đúng cái gì ─────────────────────────────────────────────────────

def _body(job_id: str) -> str:
    """Thân job CỘNG thân mọi hàm nó gọi qua closure.

    Hai job này uỷ thác cho một hàm dùng chung, nên đọc riêng lớp vỏ thì thấy hai dòng gọi
    và không thấy lệnh nào — phép kiểm sẽ đỏ vì lý do sai. Đi theo closure là cách hỏi đúng
    câu: **job này rốt cuộc chạy cái gì.**
    """
    fn = _jobs()[job_id][4].func
    out = [inspect.getsource(fn)]
    for cell in (fn.__closure__ or ()):
        try:
            v = cell.cell_contents
        except ValueError:
            continue
        if callable(v) and getattr(v, "__module__", "") == "global_index.run_scheduler":
            out.append(inspect.getsource(v))
    assert len(out) > 1, f"{job_id} không uỷ thác cho hàm nào — phép kiểm mất chỗ để nhìn"
    return "\n".join(out)


@pytest.mark.parametrize("job_id,_h,_m,_g,_gt", WANT)
def test_it_asks_for_the_anchor_only(job_id, _h, _m, _g, _gt):
    src = _body(job_id)
    assert "--reanchor-only" in src, src[:400]
    assert "update_ibkr_daily" in src


@pytest.mark.parametrize("job_id,_h,_m,_g,_gt", WANT)
def test_it_does_not_carry_the_boundary_repair_flag(job_id, _h, _m, _g, _gt):
    """`--repair-boundary` là đường duy nhất trong tệp ấy ghi đè một bar đã có. Nó thuộc về
    job 13:45, nơi có người đọc kết quả. Mười lăm phút trước khi cửa sổ mở thì không."""
    assert "--repair-boundary" not in _body(job_id)


@pytest.mark.parametrize("job_id,_h,_m,_g,_gt", WANT)
def test_it_does_not_touch_the_preflight_record(job_id, _h, _m, _g, _gt):
    """Hồ sơ pre-flight quyết định cả ngày có giao dịch hay không. Một job phụ trợ thất bại
    không được quyền khoá ngày — và cũng không được quyền MỞ ngày."""
    src = _body(job_id)
    assert "_preflight_ok" not in src, src[:400]
    assert "_save_preflight_state" not in src


@pytest.mark.parametrize("job_id,_h,_m,_g,_gt", WANT)
def test_it_uses_its_own_gateway_client_id(job_id, _h, _m, _g, _gt):
    """Hai kết nối cùng clientId tranh nhau. `run_live_day` dùng 1, pre-flight dùng 2 — nên
    job này phải khai một số riêng, không để mặc định."""
    assert "--client-id" in _body(job_id)


# ── nó phải hiện ra ở đâu đó ────────────────────────────────────────────────

@pytest.mark.parametrize("job_id,hour,minute,_g,_gt", WANT)
def test_the_name_carries_the_time_the_journal_reads(job_id, hour, minute, _g, _gt):
    """Bộ đọc nhật ký lấy giờ từ ĐUÔI tên job. Tên không có đuôi ấy thì một lần lỡ slot
    không quy được về giờ nào."""
    assert _jobs()[job_id][3].endswith(f"{hour:02d}:{minute:02d} ET"), _jobs()[job_id][3]


@pytest.mark.parametrize("job_id,_h,_m,_g,_gt", WANT)
def test_the_journal_recognises_the_name(job_id, _h, _m, _g, _gt):
    """Ca đã xảy ra: hai job gắn vào bộ lập lịch, chạy mỗi tối, bộ đọc nhật ký không thấy gì
    cả — cả khi thành công lẫn khi hỏng. Bộ đọc trả `None` rồi bỏ qua, nó không kêu."""
    from monitor.backend.job_journal_reader import _job_id_from_name

    got = _job_id_from_name(_jobs()[job_id][3])
    assert got is not None, f"nhật ký không nhận ra {_jobs()[job_id][3]!r}"
    assert got.startswith("ANCHOR_CHECK"), got


@pytest.mark.parametrize("job_id,_h,_m,_g,_gt", WANT)
def test_it_gets_its_own_stream_not_the_catch_all(job_id, _h, _m, _g, _gt):
    """`other` là thùng chứa chung, và một thùng chứa chung không phải một luồng: đã có lần
    một lượt quét sửa stop đóng hộ một lần làm mới dữ liệu hỏng, vì cả hai rơi vào `other`."""
    from monitor.backend.job_journal_reader import _job_id_from_name, _job_type

    t = _job_type(_job_id_from_name(_jobs()[job_id][3]))
    assert t not in ("other", ""), t
    assert t == "anchor_check", t


def test_one_implementation_two_callers():
    """Một luật an toàn có hai bản là hai luật, và chỉ một bản được đọc vào ngày nó quan
    trọng. Nên: đúng MỘT chỗ trong bộ lập lịch viết ra cái cờ ấy, và đúng HAI job chạy tới
    nó — không job thứ ba nào lặng lẽ neo lại vào một giờ không ai xem xét."""
    import global_index.run_scheduler as rs

    src = inspect.getsource(rs)
    assert src.count('"--reanchor-only"') == 1, src.count('"--reanchor-only"')

    callers = [jid for jid, v in _jobs().items()
               if jid.startswith("anchor_check")]
    assert sorted(callers) == sorted(w[0] for w in WANT), callers
    assert all("--reanchor-only" in _body(c) for c in callers)


# ── bảng gương trên bảng điều khiển ─────────────────────────────────────────

def test_the_dashboard_mirror_knows_about_them():
    """Bảng `PIPELINE_FIXED_SLOTS` là danh sách job mà bảng điều khiển BIẾT. Chú thích của
    chính nó nói: một job bộ lập lịch chạy mà bảng không biết là một dòng quá hạn ma mỗi
    ngày. Ba nấc SPY đã sống nhiều tuần ở đúng tình trạng ấy."""
    import datetime as dt

    import monitor.backend.schedule_status as ss

    day = dt.date(2026, 9, 9)                     # thứ Tư thường
    seen = {sl["id"]: sl["at"] for sl in ss._scheduled_slots_for(day)}
    assert len(seen) > 20, len(seen)              # lịch rỗng thì phép kiểm xanh trên hư không
    js = _jobs()
    for job_id, hour, minute, _g, _gt in WANT:
        key = f"ANCHOR_CHECK_{hour:02d}{minute:02d}"
        assert key in seen, f"{key} không có dòng nào trong bảng gương"
        assert (seen[key].hour, seen[key].minute) == (int(js[job_id][0]), int(js[job_id][1])), (
            key, "gương", seen[key], "lịch", js[job_id][:2])


def test_they_are_not_in_the_decision_pipeline():
    """Bảng chuỗi-quyết-định nuôi trường `next_decision_job`, và một trong hai bảng điều
    khiển vẽ trường ấy thành thanh đếm ngược mang tiêu đề **CỬA SỔ VÀO LỆNH**.

    Hai job này không đặt lệnh nào và không mở cửa sổ nào. Đặt chúng ở đó là nói với người
    vận hành rằng 09:16 là một cơ hội giao dịch. Bản đầu của tôi đặt đúng vào đó, và phép
    kiểm "tách job vận hành khỏi chuỗi ra quyết định" trong bộ dashboard đã bắt được.

    Chúng nằm đúng chỗ các lượt quét sửa stop đang nằm: thấy được trên lịch, vắng khỏi chuỗi
    ra quyết định.
    """
    import datetime as dt

    import monitor.backend.schedule_status as ss

    day = dt.date(2026, 9, 9)
    pipeline = {sl["id"] for sl in ss._pipeline_slots_for(day)}
    scheduled = {sl["id"] for sl in ss._scheduled_slots_for(day)}
    assert pipeline, "bảng chuỗi rỗng — phép kiểm mất chỗ để nhìn"
    for _jid, hour, minute, _g, _gt in WANT:
        key = f"ANCHOR_CHECK_{hour:02d}{minute:02d}"
        assert key in scheduled, key
        assert key not in pipeline, f"{key} bị xếp vào chuỗi ra quyết định"


def test_no_timed_job_is_missing_from_the_mirror():
    """Phép kiểm ĐĂNG KIỂM, không phải phép kiểm cho hai job này.

    Hai bản sửa trước đã thêm job rồi quên bảng gương, và cả hai lần chỉ lộ ra vì có người
    hỏi. Nên thay vì thêm một dòng nữa cho hai job hôm nay, đếm cả sổ: mọi job có giờ cố
    định mà bộ đọc nhật ký nhận ra tên, đều phải có một dòng trong bảng gương — hoặc nằm
    trong danh sách miễn trừ có ghi lý do ngay dưới đây.

    Trần cố định: danh sách miễn trừ không được dài ra mà không ai đọc.
    """
    import monitor.backend.schedule_status as ss
    from monitor.backend.job_journal_reader import _job_id_from_name

    #: Job có giờ nhưng CỐ Ý không nằm trong bảng gương, kèm lý do.
    EXEMPT = {
        # Chạy tối Chủ nhật, không phải Mon-Fri; bảng gương dựng theo ngày giao dịch.
        "spy_weekend_pre_nkd_check": "chạy Chủ nhật, ngoài lưới ngày giao dịch",
        # Lưới an toàn cho báo cáo phiên. Đường chính bám vào SỰ KIỆN "việc cuối vừa xong",
        # nên vào một ngày bình thường cron 23:55 tự thoát mà không làm gì. Một dòng gương
        # cho nó sẽ báo thiếu vào MỌI ngày chạy tốt — đúng thứ bảng gương sinh ra để tránh.
        # Chính chú thích của `_scheduled_slots_for` đã loại nó ra, và phép kiểm này chỉ
        # ghi lại điều đó chứ không phát hiện ra nó.
        "session_report_fallback": "lưới an toàn, chỉ chạy khi đường chính hỏng",
    }
    # Bảng gương THẬT là thứ `_scheduled_slots_for` dựng ra, không phải riêng bảng chuỗi
    # quyết định — đó cũng là thứ phép đối chiếu lịch↔gương đọc.
    import datetime as dt

    mirror = {sl["id"] for sl in ss._scheduled_slots_for(dt.date(2026, 9, 9))}
    assert len(mirror) > 20, len(mirror)
    js = _jobs()
    missing = []
    for jid, (hour, minute, dow, name, _job) in js.items():
        if jid == "heartbeat" or jid.startswith(("track1_nkd_", "track1_stress_",
                                                 "track1_swing_", "track1_calm_",
                                                 "track1_stop_repair", "track1_audit_")):
            continue                       # gương riêng của Tuyến 1, đã có phép kiểm khác
        if jid in EXEMPT:
            continue
        key = _job_id_from_name(name)
        if key is None:
            continue                       # phép kiểm "nhật ký nhận ra tên" ở trên canh chỗ này
        if key not in mirror:
            missing.append((jid, name, key))
    assert len(EXEMPT) <= 2, f"danh sách miễn trừ dài ra: {EXEMPT}"
    assert not missing, missing


def test_the_scheduler_id_and_the_mirror_id_are_the_same_name():
    """Bảng gương được tra bằng ID job, không bằng tên hiển thị. Bản đầu của hai job này
    mang tiền tố `track1_` trong khi dòng gương là `ANCHOR_CHECK_0055`, nên cả hai bên đều
    CÓ job mà phép đối chiếu vẫn báo lệch — mỗi bên thấy một id lạ.

    Đó không phải chuyện đặt tên: id lệch thì bảng điều khiển dựng một dòng quá hạn không
    bao giờ khớp, và một sự cố ma cho một job chạy đúng.
    """
    from global_index import track1_slots as t1

    for flag in (False, True):
        r = t1.parity_report(track1_shadow=flag)
        assert r["in_parity"], (flag, r["only_in_scheduler"], r["only_in_dashboard_mirror"])


def test_the_route_table_names_them():
    """`route_classification` liệt kê MỌI job bộ lập lịch đăng ký, chia theo ai sở hữu, và
    id không khớp luật nào rơi vào `unclassified`.

    Bốn job trước đã được thêm rồi mới đặt tên ở đây một chặng sau — mỗi lần đều do chính
    phép kiểm đăng kiểm ấy đỏ lên mà lộ. Lần này phép kiểm đó đang đỏ SẴN vì một lý do khác
    (bucket `legacy_drain_safety` rỗng trong chế độ chỉ-Tuyến-1), nên hai job mới suýt lọt
    vào một dòng đỏ có sẵn mà không làm con số nào nhúc nhích. Phép kiểm này hỏi thẳng.
    """
    from global_index import track1_slots as t1

    for flag in (False, True):
        r = t1.route_classification(port=7497, track1_shadow=flag)
        assert r["total"] > 50, r["total"]      # sổ rỗng thì phép kiểm xanh trên hư không
        assert not r["unclassified"], (flag, r["unclassified"])
        assert set(w[0] for w in WANT) <= set(r["shared_infra"]), r["shared_infra"]
    for job_id, _h, _m, _g, _gt in WANT:
        assert job_id in t1.SHARED_INFRA_JOBS, job_id
        assert len(t1.SHARED_INFRA_JOBS[job_id].split()) >= 15, job_id


@pytest.mark.parametrize("job_id,_h,_m,_g,_gt", WANT)
def test_it_asks_for_a_wider_window_than_the_daily_append(job_id, _h, _m, _g, _gt):
    """Bar chồng lấn là thứ đo được BẬC chênh, và một lần roll không đo được bậc thì bị từ
    chối thẳng. Nên cách rẻ nhất để không phải dùng tới lời từ chối ấy là xin nhiều lịch sử
    hơn — đo được: một tuần và ba ngày đều dưới ba giây, mà sức chịu tệp cũ tăng từ 3 phiên
    lên 5."""
    src = _body(job_id)
    assert '"--duration", "1 W"' in src, src[-500:]


def test_the_daily_append_keeps_its_own_window():
    """Nới cửa sổ cho job neo, KHÔNG nới cho job 13:45. Đổi mặc định của cả tệp là đổi hành
    vi của đường ghi bar hằng ngày — một thay đổi rộng hơn hẳn thứ đang cần, và nó nằm trên
    đúng đường mã đã gây ra sự cố 05/08."""
    import global_index.update_ibkr_daily as U

    assert U._argparser().parse_args([]).duration == "3 D"
