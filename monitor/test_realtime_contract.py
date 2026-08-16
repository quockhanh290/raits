"""Static contract between realtime.js and index.html.

Hai bug Critical (C1, C2 trong REALTIME_DASHBOARD_AUDIT.md) đều là cùng một
hình dạng: JS nói chuyện với một element mà HTML không cung cấp đúng cách, và
không có gì kêu lên. Hai test dưới đây suy ra tập id từ chính source nên không
có allowlist nào phải bảo trì bằng tay.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from monitor.backend.app import app

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "global_index" / "dash"
REALTIME = DASH / "realtime"

_JS_LOOKUP = re.compile(r"\$\('([A-Za-z0-9_]+)'\)")
_HTML_ID = re.compile(r'id="([A-Za-z0-9_]+)"')
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)


def _realtime_sources() -> tuple[str, str]:
    """JS đã lọc comment cả-dòng, cộng HTML thô.

    Guard dưới đây grep trên source, nên một comment giải thích chính cái bug nó
    canh — ví dụ nhắc tới lookup schedulerHealth đã bị gỡ — sẽ bị bắt như thể
    vẫn là code đang chạy. Chỉ bỏ dòng bắt đầu bằng //: code thật không bao giờ
    nằm trên một dòng như vậy, nên khả năng bắt true positive không đổi.
    """
    js = (REALTIME / "realtime.js").read_text(encoding="utf-8")
    return _LINE_COMMENT.sub("", js), (REALTIME / "index.html").read_text(encoding="utf-8")


def test_every_id_realtime_js_reads_is_actually_rendered():
    """C1: `if ($('schedulerHealth'))` bọc quanh incident push cho IBKR
    connectivity và broker/runner reconcile. Element đó không tồn tại, nên hai
    alarm quan trọng nhất của trang im lặng vĩnh viễn.

    Id được tạo động qua innerHTML trong chính realtime.js (railClockEt,
    railClockZones) được chấp nhận — chúng có nguồn gốc kiểm chứng được.
    """
    js, html = _realtime_sources()
    referenced = set(_JS_LOOKUP.findall(js))
    rendered = set(_HTML_ID.findall(html)) | set(_HTML_ID.findall(js))
    missing = sorted(referenced - rendered)
    assert not missing, (
        "realtime.js reads DOM ids that nothing renders; every branch guarded on "
        f"them is dead code: {missing}"
    )


def test_no_element_is_written_to_while_permanently_hidden():
    """C2: index.html đặt `hidden` trên runnerContext, realtime.js ghi
    textContent + className vào nó, và không có chỗ nào bỏ hidden. Dòng duy
    nhất mang tuổi/độ tươi của runner state vì thế vô hình.
    """
    js, html = _realtime_sources()
    hidden_ids = set(re.findall(r'id="([A-Za-z0-9_]+)"[^>]*\bhidden\b', html))
    written_to = {
        match for match in _JS_LOOKUP.findall(js)
        if re.search(rf"\$\('{re.escape(match)}'\)\.(textContent|innerHTML|className)\s*=", js)
    }
    unhide_missing = sorted(
        item for item in hidden_ids & written_to
        if not re.search(rf"\$\('{re.escape(item)}'\)\.hidden\s*=", js)
    )
    assert not unhide_missing, (
        "realtime.js writes content into elements that start hidden and are never "
        f"unhidden: {unhide_missing}"
    )


def test_realtime_page_has_no_write_surface():
    """Bất biến an toàn: trang này read-only — 0 form, 0 nút lệnh, 0 control
    restart/up/down. Đó là điểm mạnh nhất của nó: không thao tác nào trên trang
    có thể chạm tới broker hay runner. Thao tác vận hành thật thuộc về
    monitor/ops.py. Khóa lại bằng test để không ai vô tình thêm nút.
    """
    js, html = _realtime_sources()
    for verb in ("'POST'", '"POST"', "'PUT'", '"PUT"', "'DELETE'", '"DELETE"', "'PATCH'", '"PATCH"'):
        assert verb not in js, f"realtime.js issues a {verb} request"
    assert "<form" not in html.lower()


def test_realtime_never_renders_the_percent_unit_breaker_field():
    """L6: operational_status.breaker phát drawdown ở đơn vị PHẦN TRĂM (0.086)
    trong khi snapshot.drawdown_pct cạnh nó là PHÂN SỐ (0.00086) — cùng payload,
    chênh 100x. Đã đóng 2026-08-15 bằng cách đưa đơn vị vào tên field
    (`dd_pct_display`), nhưng cái tên chỉ cảnh báo được người đọc nó; test này
    khoá phần realtime.js không đọc nó chút nào — trang này lấy drawdown từ
    snapshot, và trộn hai nguồn khác đơn vị là cách sai 100x quay lại.

    Tiền tố khớp cả tên mới: `breaker.dd_pct` là tiền tố của
    `breaker.dd_pct_display`, nên một dòng dùng tên mới vẫn bị bắt ở đây. Đó là
    chủ đích — cấm là cấm mọi tên.
    """
    js, _ = _realtime_sources()
    assert "pct(ops.breaker" not in js
    assert "breaker?.dd_pct" not in js
    assert "breaker.dd_pct" not in js


def test_the_one_place_that_does_read_the_percent_unit_field_formats_it_as_percent():
    """Mặt kia của L6. shared/live.js:176 CÓ đọc field này, và phải đọc qua
    fmtPctAlready — hàm tồn tại song song với fmtPct chính vì payload có hai đơn
    vị. Đổi nó thành fmtPct/pct sẽ nhân thêm 100: 0.086% hiện thành 8.60%, tức
    một breaker đang bình thường trông như sắp chạm trần 15%.

    Test trên chỉ chứng minh realtime.js KHÔNG đọc — bản thân nó không thể đỏ
    khi consumer thật hỏng. Đây là test đỏ được: đổi fmtPctAlready → fmtPct ở
    dòng đó là đủ.
    """
    live_js = (DASH / "shared" / "live.js").read_text(encoding="utf-8")
    reading = [line.strip() for line in live_js.splitlines()
               if "dd_pct_display" in line]
    assert reading, ("shared/live.js không còn đọc breaker.dd_pct_display — nếu cố ý "
                     "bỏ thì xoá test này, đừng để nó xanh trên tập rỗng")
    bad = [line for line in reading if re.search(r"(?<!Already)\bfmtPct\(|[^A-Za-z]pct\(", line)]
    assert not bad, (
        "breaker drawdown đã ở đơn vị phần trăm; formatter nhân 100 lần nữa sẽ "
        f"báo sai 100x: {bad}")


def test_no_dashboard_has_a_write_surface():
    """Bất biến read-only cho CẢ BỐN dashboard, không riêng realtime.

    Audit chỉ khẳng định được điều này cho realtime vì phạm vi nó chỉ có vậy.
    Quét lại toàn bộ `global_index/dash/*/` cho thấy analytics, paper và reports
    cũng sạch — nên khóa luôn cả bốn. Backend đã chỉ có @app.get; đây là nửa
    còn lại của cùng một bảo đảm, ở phía trình duyệt.
    """
    offenders = []
    for folder in sorted((DASH).iterdir()):
        html = folder / "index.html"
        scripts = list(folder.glob("*.js")) if folder.is_dir() else []
        if not folder.is_dir() or not html.exists():
            continue
        markup = html.read_text(encoding="utf-8", errors="replace")
        if "<form" in markup.lower():
            offenders.append(f"{folder.name}/index.html has a <form>")
        for script in scripts:
            source = script.read_text(encoding="utf-8", errors="replace")
            for verb in ("POST", "PUT", "DELETE", "PATCH"):
                if f"'{verb}'" in source or f'"{verb}"' in source:
                    offenders.append(f"{folder.name}/{script.name} mentions {verb}")
    assert not offenders, offenders


# ── Hợp đồng payload API ─────────────────────────────────────────────────────
# Blocker #6 của REALTIME_DASHBOARD_AUDIT.md. Frontend đọc các khóa này không qua
# lớp trung gian nào; một field bị đổi tên hay một giá trị enum mới sẽ làm panel
# render "--" hoặc rơi vào nhánh mặc định mà không có gì kêu lên.

_FRESHNESS_VALUES = {"fresh", "not_expected_yet", "late", "missing", "unknown", "stale"}
_LIFECYCLE_VALUES = {"open", "recovered"}
_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _get(path: str) -> dict:
    response = app.test_client().get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.get_json()


def test_runner_state_payload_contract():
    body = _get("/api/v1/runner-state")
    assert {"source", "observed_at", "server_now", "age_seconds", "freshness",
            "expected_next_at", "error", "payload", "entry_times",
            "event_history"} <= set(body)
    assert body["freshness"] in _FRESHNESS_VALUES, body["freshness"]
    assert body["age_seconds"] is None or isinstance(body["age_seconds"], (int, float))
    for key in ("observed_at", "server_now"):
        assert body[key] is None or _ISO_UTC.match(body[key]), (key, body[key])


def test_schedule_status_payload_contract():
    body = _get("/api/v1/schedule-status")
    assert {"source", "server_now", "trading_day", "active_window", "state_slot_count",
            "latest_expected_at", "expected_next_at", "next_scheduled_job",
            "next_decision_job", "freshness", "state_age_seconds", "evidence_available",
            "evidence", "incidents", "open_incidents", "unexplained_overdue"} <= set(body)
    assert body["freshness"] in _FRESHNESS_VALUES, body["freshness"]
    assert body["state_age_seconds"] is None or isinstance(body["state_age_seconds"], (int, float))


def _schedule_with_one_failed_slot(tmp_path):
    """Dựng dữ liệu CÓ incident thay vì hy vọng log thật hôm nay có sẵn.

    Hai test dưới duyệt danh sách incident rồi assert. Chạy trên log production,
    một ngày sạch cho danh sách rỗng, vòng lặp không chạy lần nào, và test xanh
    mà chẳng kiểm được gì — đúng cái bẫy đã làm hỏng fixture của H1 lần đầu.
    """
    import datetime as dt
    from monitor.backend import schedule_status

    launch = "python -m global_index.run_live_day --clusters nkd"
    (tmp_path / "scheduler_0814.log").write_text(
        f"2026-08-14 01:00:00  INFO     run_scheduler — [NKD_NIGHT_0200] {launch}\n"
        "2026-08-14 01:00:12  ERROR    run_scheduler — [NKD_NIGHT_0200] exited with code 1\n",
        encoding="utf-8")
    now = dt.datetime(2026, 8, 14, 7, 0, tzinfo=dt.timezone.utc)
    return schedule_status.get_schedule_status(tmp_path, observed_at=now, now=now)


def test_every_schedule_incident_declares_its_lifecycle(tmp_path):
    """H1 diễn đạt thành hợp đồng: `lifecycle` là thứ Now Monitor dựa vào để
    quyết định có kêu hay không. Một incident thiếu nó sẽ rơi vào nhánh mặc
    định — đúng cái đã làm 6 slot đã phục hồi hiện thành OPEN suốt cả ngày."""
    body = _schedule_with_one_failed_slot(tmp_path)
    assert body["incidents"], "fixture must produce at least one incident"
    for item in body["incidents"]:
        assert item.get("lifecycle") in _LIFECYCLE_VALUES, item
        assert "recovered_by" in item, item
        assert item["slot_at"] is None or _ISO_UTC.match(item["slot_at"]), item


def test_open_incidents_is_a_subset_of_incidents(tmp_path):
    """Rail đọc open_incidents, Job Journal đọc incidents. Nếu hai danh sách trôi
    khỏi nhau thì hai vùng của cùng một màn hình lại nói hai chuyện khác nhau —
    đúng lỗi H1, chỉ là ở tầng dữ liệu."""
    body = _schedule_with_one_failed_slot(tmp_path)
    assert body["incidents"] and body["open_incidents"], "fixture must exercise both lists"
    all_slots = {(item["slot_id"], item["slot_at"]) for item in body["incidents"]}
    open_slots = {(item["slot_id"], item["slot_at"]) for item in body["open_incidents"]}
    assert open_slots <= all_slots, open_slots - all_slots
    assert all(item["lifecycle"] == "open" for item in body["open_incidents"])


# P2-C1: tám endpoint còn lại chưa có hợp đồng nào. Frontend đọc thẳng các khóa
# này, nên một field bị đổi tên sẽ làm panel render "--" hoặc rơi vào nhánh mặc
# định mà không gì kêu lên. Mỗi mục khai báo khóa BẮT BUỘC và khóa nào là danh sách.
_TODAY = dt.date.today().isoformat()
_ENDPOINT_CONTRACTS = {
    "/api/v1/broker": (
        {"source", "observed_at", "server_now", "age_seconds", "freshness", "connected",
         "error", "payload"},
        {"payload": {"equity", "unrealized_pnl", "positions", "orders", "contract_specs"}},
        ["payload.positions", "payload.orders"]),
    "/api/v1/runner-positions": (
        {"source", "observed_at", "error", "payload"}, {}, []),
    "/api/v1/open-issues": (
        {"source", "observed_at", "coverage", "issues", "error"},
        {"coverage": {"from", "to", "evidence_ends", "stale_days"}}, ["issues"]),
    f"/api/v1/session-events/{_TODAY}": (
        {"source", "day", "observed_at", "events", "error"}, {}, ["events"]),
    f"/api/v1/job-journal/{_TODAY}": (
        {"source", "day", "observed_at", "jobs", "monitor_events", "error"}, {},
        ["jobs", "monitor_events"]),
    f"/api/v1/execution-quality/{_TODAY}": (
        {"source", "day", "fills", "exceptions"}, {}, ["fills", "exceptions"]),
    f"/api/v1/reports/{_TODAY}": ({"day", "daily"}, {}, []),
    "/api/v1/paper-evidence": ({"source"}, {}, []),
}


def _dig(body: dict, path: str):
    for part in path.split("."):
        body = body[part]
    return body


@pytest.mark.parametrize("path", sorted(_ENDPOINT_CONTRACTS))
def test_every_realtime_endpoint_keeps_its_payload_contract(path):
    required, nested, lists = _ENDPOINT_CONTRACTS[path]
    body = _get(path)
    assert required <= set(body), f"{path} thieu khoa: {sorted(required - set(body))}"
    for key, sub in nested.items():
        assert sub <= set(body[key]), f"{path}.{key} thieu: {sorted(sub - set(body[key]))}"
    for key in lists:
        assert isinstance(_dig(body, key), list), f"{path}.{key} phai la list"
    for key in ("observed_at", "server_now"):
        if body.get(key) is not None:
            assert _ISO_UTC.match(body[key]), (path, key, body[key])


def test_the_endpoint_contract_covers_every_route_the_page_calls():
    """Chống pass rỗng ở tầng danh sách: nếu frontend gọi thêm một endpoint mới
    mà không ai thêm hợp đồng, test trên vẫn xanh vì nó chỉ duyệt những gì đã
    khai báo. Đối chiếu với đường dẫn thật mà realtime.js fetch."""
    js, _ = _realtime_sources()
    # Dừng ở backtick/nháy chứ KHÔNG dừng ở ')', vì đường dẫn động là
    # `/api/v1/session-events/${encodeURIComponent(sessionDay)}` — cắt ở ')' đầu
    # tiên sẽ băm đôi chuỗi và test tự đỏ vì lỗi của chính nó.
    called = {re.sub(r"\$\{[^}]*\}", "", m).rstrip("/")
              for m in re.findall(r"fetchJson\(`?'?(/api/v1/[^`']*)", js)}
    covered = {p.rsplit("/", 1)[0] if re.search(r"/\d{4}-\d{2}-\d{2}$", p) else p
               for p in _ENDPOINT_CONTRACTS}
    covered |= {"/api/v1/runner-state", "/api/v1/schedule-status"}
    missing = sorted(c for c in called if c not in covered)
    assert not missing, f"realtime.js goi endpoint chua co hop dong: {missing}"


def test_all_four_readers_agree_on_which_slots_are_open(tmp_path):
    """H1 ở mức hệ thống. Bốn lane từng cài bốn cách hiểu "đã phục hồi chưa":
    schedule_status có _annotate_incident_lifecycle, open_issue_reader có
    later_recovery riêng, job_journal_reader chỉ set cho missed+stop_repair, và
    report_reader thì suy từ lifecycle_status của job_journal — nên khi
    job_journal trả None, report_reader đếm luôn 6 slot đã phục hồi là "open".

    Cùng một log phải cho cùng một kết luận ở cả bốn nơi. Đây là bước 8 của
    Task 6 trong plan, rơi vào khe giữa hai người thực thi nên chưa ai làm.
    """
    import datetime as dt
    from monitor.backend import schedule_status
    from monitor.backend.job_journal_reader import read_job_journal
    from monitor.backend.open_issue_reader import read_open_issues
    from monitor.backend.report_reader import read_report

    launch = "python -m global_index.run_live_day --clusters nkd"
    (tmp_path / "scheduler_0814.log").write_text(
        f"2026-08-14 01:00:00  INFO     run_scheduler — [NKD_NIGHT_0200] {launch}\n"
        "2026-08-14 01:00:12  ERROR    run_scheduler — [NKD_NIGHT_0200] exited with code 1\n"
        f"2026-08-14 01:30:00  INFO     run_scheduler — [NKD_NIGHT_0230] {launch}\n"
        "2026-08-14 01:30:20  INFO     run_scheduler — [NKD_NIGHT_0230] completed OK\n",
        encoding="utf-8")
    now = dt.datetime(2026, 8, 14, 8, 0, tzinfo=dt.timezone.utc)

    status = schedule_status.get_schedule_status(tmp_path, observed_at=now, now=now)
    journal = read_job_journal("2026-08-14", tmp_path)["jobs"]
    issues = read_open_issues(tmp_path)["issues"]
    daily = read_report("2026-08-14", tmp_path)["daily"]

    failed = [job for job in journal if job["status"] == "failed"]
    assert failed, "fixture must produce a failed job for this to mean anything"
    assert status["incidents"], "fixture must produce a schedule incident"

    # Cả bốn lane: không còn gì MỞ.
    assert status["open_incidents"] == []
    # Phải so với tập giá trị hợp lệ, KHÔNG so `== "open"`: khi lifecycle_status là
    # None (đúng bug đang canh) thì `None == "open"` là False và một assertion
    # dạng lọc-rồi-so-rỗng vẫn xanh, không bắt được gì.
    assert all(job.get("lifecycle_status") == "recovered" for job in failed), \
        [(job["job_id"], job.get("lifecycle_status")) for job in failed]
    assert [item for item in issues if item["status"] == "incident"] == []
    assert daily["open_incident_count"] == 0

    # Nhưng KHÔNG lane nào được xoá sự thật: thất bại vẫn phải còn trong bản ghi.
    assert len(status["incidents"]) >= 1
    assert daily["incident_count"] >= 1
    assert all(item["lifecycle_status"] == "recovered" for item in daily["incidents"])


def test_live_schedule_endpoint_matches_the_same_contract():
    """Fixture kiểm luật; dòng này kiểm đường dây thật — endpoint có nối đúng
    reader không. Không duyệt phần tử nào nên không có nguy cơ pass rỗng."""
    body = _get("/api/v1/schedule-status")
    assert isinstance(body["incidents"], list)
    assert isinstance(body["open_incidents"], list)
    assert len(body["open_incidents"]) <= len(body["incidents"])


def test_the_nightly_evidence_jobs_are_typed_and_name_what_their_failure_costs():
    """Two jobs were attached to the scheduler on 2026-08-15 (broker-statement pull and
    P&L rebuild) and were invisible here: the journal anchored on `-m global_index.` and
    they launch `-m monitor.`. They would have run every evening and appeared as nothing
    at all -- success and failure alike -- on the page built to show whether jobs ran.

    Typed rather than left as "other" so the journal can state the real cost, which is
    not a halted trade: it is the paper ledger no longer being checked against the money
    IBKR actually moved. That check reading 0.00 while the account was $1,260 out is the
    reason it exists.
    """
    import tempfile
    from pathlib import Path

    from monitor.backend.job_journal_reader import _parse

    log = (
        "2026-08-16 16:40:22  INFO     run_scheduler - [FLEX_PULL] py -m monitor.flex_pull\n"
        "2026-08-16 16:40:30  INFO     run_scheduler - [FLEX_PULL] completed OK\n"
        "2026-08-16 16:40:30  INFO     run_scheduler - [PAPER_PNL] py -m monitor.paper_pnl_compare\n"
        "2026-08-16 16:40:48  ERROR    run_scheduler - [PAPER_PNL] exited with code 1\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "scheduler_0816.log"
        path.write_text(log, encoding="utf-8")
        jobs = {j["job_id"]: j for j in (_parse([path], "2026-08-16", []).get("jobs") or [])}

    assert set(jobs) == {"FLEX_PULL", "PAPER_PNL"}, (
        f"a scheduler job is missing from the journal: {sorted(jobs)}")
    assert jobs["FLEX_PULL"]["job_type"] == "flex_pull"
    assert jobs["PAPER_PNL"]["job_type"] == "paper_pnl"

    failed = jobs["PAPER_PNL"]
    assert failed["status"] == "failed"
    assert "not reconciled against actual Flex P&L" in failed["impact"]
    # The cost must not read as a trading incident; nothing is halted and no position is
    # at risk. Saying otherwise trains the reader to discount the lane.
    assert "No trading action" in failed["action"]
    assert "paper_pnl_compare.py" in failed["action"], "must say how to clear it"
