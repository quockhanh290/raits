"""Báo cáo phiên chạy KHI VIỆC CUỐI CÙNG TRONG NGÀY XONG — không phải theo giờ cố định.

Báo cáo đọc log **theo ngày lịch**, nên bất cứ việc nào chạy sau nó đều rơi vào vùng không
bao giờ được báo cáo: bản hôm sau chỉ đọc những dòng mang ngày hôm sau.

Tôi đã đoán sai hai lần. Đặt cron 16:00 vì nghĩ phiên kết thúc ở slot giao dịch cuối
(15:55) — sai, còn 8 việc chạy sau đó tới 23:20. Rồi đặt 23:50 — vẫn là đoán, vì lượt quét
23:20 chạy quá 30 phút thì báo cáo lại ra trước khi nó xong. Cả hai lần cùng một lỗi: lấy
một con số thay cho một điều kiện.

Cách đúng: APScheduler không có sự kiện "đã chạy hết", nhưng có sự kiện "một việc vừa xong".
Bám vào sự kiện của việc có giờ muộn nhất, và việc đó thì TÍNH RA từ lịch. Thêm một việc
muộn hơn thì báo cáo tự dời theo.

Kèm lưới an toàn: việc cuối không chạy thì sự kiện không bao giờ tới và ngày đó mất báo cáo
— đúng loại im lặng mà báo cáo sinh ra để chống, nên nó không được tự dính vào.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("apscheduler")

from global_index.run_scheduler import make_scheduler

_GI = Path(__file__).resolve().parents[1] / "global_index"
FALLBACK = (23, 55)


def _slots():
    sched = make_scheduler(port=4002, dry_run=True)
    try:
        out = []
        for j in sched.get_jobs():
            if j.id == "heartbeat":
                continue
            f = {str(x.name): str(x) for x in j.trigger.fields}
            try:
                out.append((int(f["hour"]), int(f["minute"]), j.id))
            except (KeyError, ValueError):
                continue
        return sorted(out)
    finally:
        if getattr(sched, "running", False):
            sched.shutdown(wait=False)


def _sched():
    return make_scheduler(port=4002, dry_run=True)


# ── cơ chế ───────────────────────────────────────────────────────────────────

def test_the_report_is_bound_to_a_job_event_not_a_clock():
    """Có đúng một listener, và nó tồn tại để chạy báo cáo."""
    sched = _sched()
    try:
        assert len(sched._listeners) == 1, "khong co listener nao bam su kien job"
    finally:
        if getattr(sched, "running", False):
            sched.shutdown(wait=False)


def test_the_trigger_job_is_computed_not_hardcoded():
    """Việc cuối phải được tính từ lịch. Viết cứng thì thêm một việc muộn hơn sẽ lặng lẽ
    đẩy nó ra ngoài vùng báo cáo."""
    src = (_GI / "run_scheduler.py").read_text(encoding="utf-8")
    assert "_LAST_JOB_ID = sorted(_fixed)" in src, \
        "viec cuoi dang duoc viet cung thay vi tinh ra tu lich"


def test_the_last_real_job_runs_before_the_fallback():
    """Bất biến chính. Lưới an toàn 23:55 chỉ đúng khi nó nằm SAU việc cuối thật — nếu một
    việc chạy muộn hơn 23:55, lưới sẽ bắn trước, đặt cờ, và làm câm chính đường kích hoạt
    thật."""
    real = [(h, m, j) for h, m, j in _slots() if j != "session_report_fallback"]
    assert real, "khong dung duoc lich"
    hh, mm, jid = real[-1]
    assert (hh, mm) < FALLBACK, (
        f"viec {jid} chay luc {hh:02d}:{mm:02d}, sau ca luoi an toan "
        f"{FALLBACK[0]:02d}:{FALLBACK[1]:02d} — luoi se ban truoc va lam cam kich hoat that")


def test_the_fallback_exists():
    """Việc cuối không chạy (scheduler lên muộn) thì sự kiện không bao giờ tới."""
    assert any(j == "session_report_fallback" for _h, _m, j in _slots())


def test_the_fallback_is_the_last_thing_in_the_day():
    assert _slots()[-1][2] == "session_report_fallback"


def test_the_fallback_does_not_double_report():
    """Nó phải kiểm cờ trong ngày trước khi chạy, nếu không mỗi ngày sẽ có hai báo cáo và
    cái thứ hai sẽ ghi đè file của cái thứ nhất."""
    src = (_GI / "run_scheduler.py").read_text(encoding="utf-8")
    assert "if _report_done.get(_et_today().isoformat()):" in src


# ── bản thân báo cáo ─────────────────────────────────────────────────────────

def test_the_report_does_not_touch_the_broker():
    """Chỉ đọc log và file trạng thái. Nối IBKR là thêm một kết nối và một lượt B3 nữa —
    không đáng cho một việc chỉ để đọc."""
    src = (_GI / "session_report.py").read_text(encoding="utf-8")
    for forbidden in ("IBKRBroker", "reqAllOpenOrders", "ib_insync"):
        assert forbidden not in src, f"session_report cham broker qua {forbidden}"


def test_the_report_writes_a_dated_file():
    """Mã thoát 1 chỉ đưa phần đuôi vào log scheduler. File có ngày là bản lưu đầy đủ."""
    src = (_GI / "run_scheduler.py").read_text(encoding="utf-8")
    assert "bao_cao_" in src and "--out" in src


def test_the_report_listens_to_errors_too():
    """Một việc cuối bị LỖI thì càng cần báo cáo, không phải càng ít."""
    src = (_GI / "run_scheduler.py").read_text(encoding="utf-8")
    assert "EVENT_JOB_EXECUTED | EVENT_JOB_ERROR" in src


# ── báo cáo ngày quá khứ không được nói về hiện tại ──────────────────────────

def test_a_past_date_does_not_print_current_positions(tmp_path):
    """`live_positions.json` chỉ giữ trạng thái HIỆN TẠI. Bản đầu in nó ra trong mọi báo
    cáo, nên báo cáo ngày 07/08 nói "đang giữ MNKD vào lệnh ngày 10/08" — một câu vô nghĩa
    nhưng đọc rất xuôi, tức đúng loại sai nguy hiểm nhất trong một bản báo cáo."""
    from global_index.session_report import build
    (tmp_path / "live_day_0807.log").write_text(
        "2026-08-07 10:00:00  INFO     run_live_day - [LIVE_DAY_1405] completed OK\n",
        encoding="utf-8")
    text, _need = build("2026-08-07", tmp_path)
    assert "KHÔNG áp dụng" in text
    assert "hợp đồng   (" not in text, "van in vi the hien tai vao bao cao ngay qua khu"


def test_a_past_date_does_not_flag_missing_jobs(tmp_path):
    """Điểm danh đối chiếu với lịch HIỆN TẠI. Lịch đổi theo thời gian, nên với ngày quá khứ
    một việc 'không chạy' có thể chỉ là chưa tồn tại — 19 lượt quét sửa thêm hôm 10/08 hiện
    ra như sự cố trong báo cáo ngày 07/08."""
    from global_index.session_report import build
    # 10:00 giờ máy, KHÔNG phải 23:00. Dấu thời gian trong log là giờ máy và báo cáo đổi
    # sang ET, nên một mốc sát nửa đêm sẽ rơi sang ngày ET kế tiếp và bài test tự hỏng —
    # đúng cái bẫy mà phép đổi sinh ra để chống, gặp ngay trong chính fixture của nó.
    (tmp_path / "live_day_0807.log").write_text(
        "2026-08-07 10:00:00  INFO     run_live_day - [LIVE_DAY_1405] completed OK\n",
        encoding="utf-8")
    text, need = build("2026-08-07", tmp_path)
    assert "KHÔNG KIỂM ĐƯỢC CHO NGÀY QUÁ KHỨ" in text
    assert need is False, "danh sach viec 'khong chay' cua ngay qua khu khong duoc quyet ma thoat"


def test_html_report_is_self_contained_and_uses_the_structured_report(tmp_path):
    from global_index.session_report import collect_session_report, render_html

    (tmp_path / "live_day_0810.log").write_text(
        "2026-08-10 10:00:00  INFO     run_live_day - [LIVE_DAY_1405] completed OK\n"
        "2026-08-10 10:01:00  ERROR    guard - B4 NAKED MES\n"
        "2026-08-10 10:02:00  INFO     run_live_day - [shadow] MES: DOI CHIEU KHOP\n",
        encoding="utf-8")
    report = collect_session_report("2026-08-10", tmp_path)
    page = render_html(report)
    assert "<!doctype html>" in page
    assert "<style>" in page
    assert "http://" not in page and "https://" not in page
    assert "Dòng thời gian trong ngày" in page
    assert "Chuyển sang resume" in page


def test_html_past_date_does_not_print_current_positions_or_missing_job_list(tmp_path):
    from global_index.session_report import collect_session_report, render_html

    (tmp_path / "live_day_0807.log").write_text(
        "2026-08-07 10:00:00  INFO     run_live_day - [LIVE_DAY_1405] completed OK\n",
        encoding="utf-8")
    (tmp_path / "live_positions.json").write_text(
        '{"positions":[{"inst":"MES","direction":"LONG","contracts":1,'
        '"entry_day":"2026-08-10","entry_price":100,"stop_price":95,'
        '"stop_order_id":null,"cluster":"roska4_swing"}]}',
        encoding="utf-8")
    report = collect_session_report("2026-08-07", tmp_path)
    page = render_html(report)
    missing_panel = page.split('class="panel missing-jobs"', 1)[1].split("</section>", 1)[0]
    assert "entry_price" not in page
    assert "2026-08-10" not in page
    assert "<ul><li>" not in missing_panel


# ── giờ trong log là giờ MÁY, báo cáo nói giờ ET ─────────────────────────────

def test_log_timestamps_are_converted_to_et():
    """Máy hiện chạy MST (ET − 2h) nhưng log ghi giờ máy, còn báo cáo tự khai "mọi giờ là
    giờ ET". Bản đầu lấy thẳng chuỗi trong log — sai hai lần, và lần thứ hai nặng hơn."""
    import datetime as _dt

    from global_index.session_report import _to_et
    d, t = _to_et("2026-08-10", "12:00:00")
    off = (_dt.datetime.fromisoformat(f"{d} {t}")
           - _dt.datetime.fromisoformat("2026-08-10 12:00:00"))
    local = _dt.datetime(2026, 8, 10, 12).astimezone()
    from zoneinfo import ZoneInfo
    want = (local.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
            - _dt.datetime(2026, 8, 10, 12))
    assert off == want, "khong doi tu gio may sang gio ET"


def test_the_night_window_lands_on_the_right_et_day():
    """Lỗi nặng hơn: RANH GIỚI NGÀY. Cửa sổ đêm NKD 01:10-02:55 ET là 23:10-00:55 giờ máy
    (MST), tức vắt qua nửa đêm CỦA MÁY. Gom theo ngày của log thì báo cáo ngày D bỏ sót
    cửa sổ đêm của chính ngày D và gộp nhầm cửa sổ đêm ngày D+1 — nên nkd_night_01xx hiện
    ra như 'không chạy' trong khi chúng chạy bình thường.

    Test chỉ có nghĩa khi máy KHÔNG chạy giờ ET; trên máy ET thì độ lệch bằng 0 và không
    có gì để kiểm."""
    import datetime as _dt

    from zoneinfo import ZoneInfo

    from global_index.session_report import _to_et
    probe = _dt.datetime(2026, 8, 10, 23, 10).astimezone()
    et = probe.astimezone(ZoneInfo("America/New_York"))
    if et.date() == probe.date():
        pytest.skip("may dang chay gio ET — khong co ranh gioi ngay de kiem")
    assert _to_et("2026-08-10", "23:10:00")[0] == et.date().isoformat()


def test_the_report_file_is_written_with_a_bom(tmp_path, monkeypatch):
    """Windows đoán bảng mã theo code page của console khi file không có BOM, nên
    `type bao_cao_0810.txt` in ra "BÃO CÃO PHIÃŠN" thay vì "BÁO CÁO PHIÊN".

    Một báo cáo không đọc được bằng cách mở thông thường thì coi như không tồn tại — lỗi
    này không làm test nào đỏ, không làm log nào đỏ, chỉ làm bản báo cáo vô dụng đúng lúc
    có người mở nó ra đọc."""
    import codecs
    import sys as _sys

    from global_index import session_report as sr
    out = tmp_path / "bao_cao.txt"
    monkeypatch.setattr(_sys, "argv", ["session_report", "--root", str(tmp_path),
                                       "--out", str(out)])
    sr.main()
    assert out.read_bytes()[:3] == codecs.BOM_UTF8, "thieu BOM UTF-8"
    assert "BÁO CÁO PHIÊN" in out.read_text(encoding="utf-8-sig")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
