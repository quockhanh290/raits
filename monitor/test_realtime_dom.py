"""DOM smoke tests: chạy trang realtime thật trong chromium với API bị stub.

Suite backend hiện có rất mạnh nhưng frontend chỉ được kiểm bằng
`assert "chuoi" in file`, nên mọi finding trong REALTIME_DASHBOARD_AUDIT.md đều
lọt qua. Harness này dựng Flask trên cổng tạm (static assets là thật), rồi chặn
`/api/**` để dựng đúng trạng thái cần kiểm.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from monitor.backend.app import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

BASE_PAYLOADS: dict[str, dict] = {
    "/api/v1/runner-state": {
        "source": "runner_state",
        "observed_at": "2026-08-14T18:06:00Z",
        "server_now": "2026-08-14T18:07:00Z",
        "age_seconds": 60.0,
        "freshness": "fresh",
        "expected_next_at": "2026-08-14T18:10:00Z",
        "error": None,
        "entry_times": {"source": "trade_log.jsonl", "observed_at": None,
                        "error": None, "filled": 0},
        "event_history": {"events": [], "malformed_lines": 0, "error": None,
                          "coverage_started_at": None},
        "payload": {
            "meta": {
                "account": 50000.0, "final_equity": 50000.0, "net_pnl": 0.0,
                "hard_dd_pct": 0.15, "system_epoch": "2026-08-10",
                "max_dd_pct": 0.0, "backtest_calmar": 1.65,
                "operational_status": {
                    "runner": {"alive": True},
                    "breaker": {"level": "OK"},
                    "regime_freshness": {"status": "OK", "last_spy_date": "2026-08-14"},
                    # P2-B4: production đang là URGENT (20 tháng, G2 HARD) chứ không phải
                    # OK. Fixture cũ mô tả một model khỏe mạnh mà hệ thống thật không có,
                    # nên mọi DOM test chạy trên một thế giới dễ hơn thực tế.
                    "model_age": {"status": "URGENT", "months_old": 20, "model_name": "fit_C"},
                    "positions": {"count": 0, "persist_match": True},
                    "refreeze": {"pending": False},
                    "regime_unreliable": False,
                },
                "events": [],
            },
            "snapshots": [{
                "date": "2026-08-14", "equity": 50000.0, "regime": "Calm",
                "drawdown_pct": 0.0, "drawdown_dollars": 0.0, "breaker_level": "OK",
                "open_positions": [],
                "running_metrics": {"calmar": None, "sharpe": None,
                                    "max_dd": None, "total_return": None},
                "decision": {"realized_today": 0, "entries": [], "exits": [],
                             "rejected_detail": [], "taken_today": {},
                             "rejected_today": {}, "halted_today": 0},
            }],
        },
    },
    "/api/v1/broker": {
        "source": "ibkr", "observed_at": "2026-08-14T18:06:55Z",
        "server_now": "2026-08-14T18:07:00Z", "age_seconds": 5.0,
        "freshness": "fresh", "connected": True, "error": None,
        "payload": {"equity": 100000.0, "unrealized_pnl": 0.0,
                    "positions": [], "orders": [], "contract_specs": {}},
    },
    "/api/v1/schedule-status": {
        "source": "scheduler_log", "server_now": "2026-08-14T18:07:00Z",
        "trading_day": True, "active_window": True, "state_slot_count": 45,
        "latest_expected_at": "2026-08-14T18:05:00Z",
        "expected_next_at": "2026-08-14T18:10:00Z",
        "next_scheduled_job": {"job_id": "LIVE_DAY_1410", "at": "2026-08-14T18:10:00Z"},
        "next_decision_job": {"job_id": "LIVE_DAY_1410", "at": "2026-08-14T18:10:00Z"},
        "freshness": "fresh", "evidence_available": True,
        "evidence": {"state": "executed", "reason": "none", "severity": "none",
                     "slot_at": "2026-08-14T18:05:00Z", "slot_id": "LIVE_DAY_1405",
                     "detail": None},
        "incidents": [], "open_incidents": [], "unexplained_overdue": [],
    },
    "/api/v1/open-issues": {
        "source": "scheduler_logs", "observed_at": "2026-08-14T18:00:00Z",
        "coverage": {"from": "2026-08-01", "to": "2026-08-14",
                     "evidence_ends": "2026-08-14", "stale_days": 0},
        "issues": [], "error": None,
    },
    "/api/v1/runner-positions": {
        "source": "runner_persisted_positions", "observed_at": "2026-08-14T18:06:00Z",
        "error": None, "payload": {"schema_version": 1, "positions": []},
    },
    "/api/v1/session-events/": {
        "source": "live_log", "day": "2026-08-14",
        "observed_at": "2026-08-14T18:06:00Z", "events": [], "error": None,
    },
    "/api/v1/job-journal/": {
        "source": "scheduler_log", "day": "2026-08-14",
        "observed_at": "2026-08-14T18:06:00Z", "jobs": [], "monitor_events": [],
        "error": None,
    },
    "/api/v1/execution-quality/": {
        "source": "trade_log.jsonl", "day": "2026-08-14",
        "fills": [], "exceptions": [], "error": None,
    },
}


@pytest.fixture(scope="module")
def realtime_server():
    """Flask thật trên cổng tạm: static assets không bị stub, chỉ API bị stub."""
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def browser_page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            yield page
        finally:
            browser.close()


def stub_api(page, overrides: dict[str, dict] | None = None) -> None:
    """Chặn mọi /api/** và trả payload tổng hợp từ BASE_PAYLOADS + overrides.

    Khóa dài hơn được so trước để '/api/v1/session-events/' không bị một prefix
    ngắn hơn nuốt mất.
    """
    payloads = dict(BASE_PAYLOADS)
    payloads.update(overrides or {})
    ordered = sorted(payloads.items(), key=lambda item: -len(item[0]))

    def handler(route):
        path = urlparse(route.request.url).path
        for prefix, body in ordered:
            if path.startswith(prefix):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(body))
                return
        route.fulfill(status=404, content_type="application/json", body="{}")

    page.route("**/api/**", handler)


def open_realtime(page, base_url: str) -> None:
    page.goto(f"{base_url}/realtime", wait_until="domcontentloaded")
    page.wait_for_selector("#statusRail .system-conclusion", timeout=10_000)


def rail_text(page) -> str:
    return page.eval_on_selector("#statusRail", "el => el.innerText")


def monitor_statuses(page) -> list[str]:
    return page.eval_on_selector_all(
        "#nowMonitorList .issue-status", "els => els.map(e => e.textContent.trim())")


def _session_events(*events) -> dict:
    return {"source": "live_log", "day": "2026-08-14",
            "observed_at": "2026-08-14T18:06:00Z", "events": list(events), "error": None}


def _snapshot_with_decision(decision: dict) -> dict:
    payload = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    payload["payload"]["snapshots"][0]["decision"] = decision
    return payload


def _decision(**over) -> dict:
    base = {"realized_today": 0, "entries": [], "exits": [], "rejected_detail": [],
            "taken_today": {}, "rejected_today": {}, "halted_today": 0}
    base.update(over)
    return base


def _entry(**over) -> dict:
    row = {"inst": "MES", "direction": "SHORT", "cluster": "roska4_swing",
           "entry_price": 7773.0, "risk_sized": 600.0, "entry_time": None,
           "is_same_day": False}
    row.update(over)
    return row


def _runner_with_metrics(days: int, metrics: dict) -> dict:
    payload = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    base = payload["payload"]["snapshots"][0]
    payload["payload"]["snapshots"] = [
        dict(json.loads(json.dumps(base)), date=f"2026-08-{day:02d}")
        for day in range(1, days + 1)
    ]
    payload["payload"]["snapshots"][-1]["running_metrics"] = metrics
    return payload


def _journal_events_text(page) -> str:
    page.click('[data-journal-view="events"]')
    page.wait_for_selector("#journal .event-row, #journal .journal-message")
    return page.eval_on_selector("#journal", "el => el.innerText")


def _stale_runner_state() -> dict:
    payload = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    payload.update({"freshness": "stale", "age_seconds": 30654.0,
                    "observed_at": "2026-08-14T06:58:51Z"})
    return payload


def test_stale_runner_state_is_visible_without_hovering(realtime_server, browser_page):
    """C2: dòng duy nhất mang tuổi snapshot nằm trong <b hidden>. Runner cũ 8.5
    giờ mà trang không nói gì ngoài Source Clocks cuối sidebar."""
    stub_api(browser_page, {"/api/v1/runner-state": _stale_runner_state()})
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector("#runnerContext", "el => el.hidden") is False
    text = browser_page.eval_on_selector("#runnerContext", "el => el.textContent")
    assert "8.5h" in text
    assert "Stale" in text


def test_stale_runner_state_downgrades_the_rail_conclusion(realtime_server, browser_page):
    """Rail là câu trả lời top-level; nó không được nói 'nominal' khi mọi con số
    runner-derived bên dưới đến từ một snapshot đã lỡ slot."""
    stub_api(browser_page, {"/api/v1/runner-state": _stale_runner_state()})
    open_realtime(browser_page, realtime_server)
    assert "nominal" not in rail_text(browser_page).lower()
    assert "runner state" in rail_text(browser_page).lower()


def test_healthy_page_loads_without_console_errors(realtime_server, browser_page):
    errors: list[str] = []
    browser_page.on("console", lambda msg: errors.append(msg.text)
                    if msg.type == "error" else None)
    browser_page.on("pageerror", lambda exc: errors.append(str(exc)))
    stub_api(browser_page)
    open_realtime(browser_page, realtime_server)
    real_errors = [item for item in errors if "favicon" not in item.lower()]
    assert not real_errors, real_errors


_CLIPPED_CONTENT = """() => {
  const de = document.documentElement;
  const scrolls = el => {
    for (let node = el; node; node = node.parentElement) {
      const overflowX = getComputedStyle(node).overflowX;
      if (overflowX === 'auto' || overflowX === 'scroll') return true;
    }
    return false;
  };
  return [...document.querySelectorAll('body *')]
    .filter(el => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.right > de.clientWidth + 1 && !scrolls(el);
    })
    .map(el => `${el.tagName}.${(el.className || '').toString().trim().split(/\\s+/)[0] || ''}`)
    .slice(0, 8);
}"""


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_no_horizontal_page_overflow(realtime_server, browser_page, width, height):
    """Bảng rộng được phép cuộn TRONG container overflow-x:auto, nhưng trang thì không."""
    browser_page.set_viewport_size({"width": width, "height": height})
    stub_api(browser_page)
    open_realtime(browser_page, realtime_server)
    overflow = browser_page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert overflow is False, f"page overflows horizontally at {width}x{height}"


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_no_content_is_clipped_off_the_right_edge(realtime_server, browser_page, width, height):
    """Kiểm tra trang có cuộn ngang không là CHƯA ĐỦ, và đã bỏ lọt một bug thật.

    Khi runnerContext thôi bị ẩn, hàng header vượt mép phải 121px ở viewport hẹp.
    Trang KHÔNG cuộn — nội dung thừa bị cắt — nên assert scrollWidth vẫn xanh
    trong khi dòng độ tươi runner nằm ngoài màn hình. Một element chỉ được phép
    vượt mép nếu nó hoặc tổ tiên của nó cuộn ngang được.
    """
    browser_page.set_viewport_size({"width": width, "height": height})
    stub_api(browser_page)
    open_realtime(browser_page, realtime_server)
    clipped = browser_page.evaluate(_CLIPPED_CONTENT)
    assert clipped == [], f"content clipped off-screen at {width}x{height}: {clipped}"


OPEN_TWS_OUTAGE = {
    "kind": "connectivity_outage", "status": "open", "service": "tws",
    "affected_services": ["tws"], "ts": "2026-08-14T17:40:00Z",
    "started_at": "2026-08-14T17:40:00Z", "level": "CRITICAL", "component": "broker",
    "title": "IBKR connectivity unavailable",
    "problem": "TWS data farm connection is down.",
    "impact": "Broker truth cannot be verified.",
    "action": "Check IBKR/TWS connectivity now.",
    "evidence": "IBKR code 2103", "down_code": 2103, "category": "IBKR",
}


def test_open_tws_outage_appears_as_an_incident(realtime_server, browser_page):
    """C1: khối push incident từng bị bọc trong `if ($('schedulerHealth'))` —
    một element không tồn tại — nên mất kết nối broker im lặng hoàn toàn."""
    stub_api(browser_page, {"/api/v1/session-events/": _session_events(OPEN_TWS_OUTAGE)})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText")
    assert "IBKR connectivity unavailable" in text
    assert browser_page.eval_on_selector(
        "#monitorClearIndicator", "el => el.hidden") is True


def test_unusable_broker_is_never_silent(realtime_server, browser_page):
    """C1 phần hai: gap 'Broker truth unavailable' từng bị nén khi có TWS outage
    đang mở, dựa trên giả định incident sẽ hiện thay. Với broker không dùng được
    VÀ outage đang mở, Now Monitor không được phép rỗng."""
    dead_broker = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/broker"]))
    dead_broker.update({"connected": False, "freshness": "unknown", "age_seconds": None,
                        "error": "connection refused"})
    stub_api(browser_page, {
        "/api/v1/broker": dead_broker,
        "/api/v1/session-events/": _session_events(OPEN_TWS_OUTAGE),
    })
    open_realtime(browser_page, realtime_server)
    assert monitor_statuses(browser_page), "Now Monitor is empty while the broker feed is dead"
    summary = browser_page.eval_on_selector("#incidentSummary", "el => el.textContent")
    assert summary.strip() != "0 incident / 0 telemetry gap"


def _recovered_nkd_window(count: int = 6) -> dict:
    """Sáu slot NKD fail 02:00-02:25 ET rồi 02:30 chạy sạch — đúng đêm 2026-08-14."""
    schedule = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/schedule-status"]))
    schedule["incidents"] = [{
        "state": "failed", "reason": "exception", "severity": "incident",
        "slot_at": f"2026-08-14T06:{minute:02d}:00Z",
        "slot_id": f"NKD_NIGHT_02{minute:02d}",
        "detail": "ConnectionRefusedError", "lifecycle": "recovered",
        "recovered_by": "NKD_NIGHT_0230",
    } for minute in range(0, count * 5, 5)]
    schedule["open_incidents"] = []
    return schedule


def test_recovered_slots_stay_countable_without_raising_an_alarm(realtime_server, browser_page):
    """Sáu slot quyết định mất trong đêm là sự thật về đêm đó, kể cả khi stream
    đã khỏe lại. Bỏ chúng khỏi lane incident là đúng; để chúng biến mất khỏi
    trang thì không — trước đây con số ấy chỉ còn lẫn trong Job Journal."""
    stub_api(browser_page, {"/api/v1/schedule-status": _recovered_nkd_window()})
    open_realtime(browser_page, realtime_server)
    summary = browser_page.eval_on_selector("#incidentSummary", "el => el.textContent")
    assert summary.startswith("0 incident / 0 telemetry gap")
    assert "6 slot(s) lost" in summary
    text = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText")
    assert "6 NKD decision slots lost" in text
    # Không phải báo động: rail vẫn nominal và không dòng nào mang nhãn OPEN.
    assert "OPEN" not in monitor_statuses(browser_page)
    assert "RECOVERED" in monitor_statuses(browser_page)
    assert "nominal" in rail_text(browser_page).lower()


def test_recovered_summary_names_the_window_and_what_fixed_it(realtime_server, browser_page):
    """Đếm được thôi chưa đủ — phải nói được cửa sổ nào mất và cái gì kéo nó về.
    Ở desktop khối detail nằm ở #nowMonitorDetail; .now-mobile-detail bị CSS ẩn
    trên viewport rộng nên không vào innerText."""
    stub_api(browser_page, {"/api/v1/schedule-status": _recovered_nkd_window()})
    open_realtime(browser_page, realtime_server)
    detail = browser_page.eval_on_selector("#nowMonitorDetail", "el => el.innerText")
    assert "02:00" in detail and "02:25" in detail
    assert "NKD_NIGHT_0230" in detail
    assert "never had a chance to fire" in detail


def test_still_open_slots_remain_a_red_incident(realtime_server, browser_page):
    """Nửa còn lại của bất biến: chưa phục hồi thì vẫn phải kêu."""
    schedule = _recovered_nkd_window(count=1)
    schedule["incidents"][0].update({"lifecycle": "open", "recovered_by": None})
    schedule["open_incidents"] = list(schedule["incidents"])
    stub_api(browser_page, {"/api/v1/schedule-status": schedule})
    open_realtime(browser_page, realtime_server)
    assert "OPEN" in monitor_statuses(browser_page)
    assert "RECOVERED" not in monitor_statuses(browser_page)


RECOVERED_SLOT = {
    "state": "failed", "reason": "exception", "severity": "incident",
    "slot_at": "2026-08-14T06:00:00Z", "slot_id": "NKD_NIGHT_0200",
    "detail": "[NKD_NIGHT_0200] ConnectionRefusedError",
    "lifecycle": "recovered", "recovered_by": "NKD_NIGHT_0230",
}


def test_recovered_schedule_incidents_are_not_shown_as_open(realtime_server, browser_page):
    """H1: rail uses open_incidents, so Now Monitor must not fall back to recovered incidents."""
    schedule = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/schedule-status"]))
    schedule["incidents"] = [RECOVERED_SLOT]
    schedule["open_incidents"] = []
    stub_api(browser_page, {"/api/v1/schedule-status": schedule})
    open_realtime(browser_page, realtime_server)
    assert "OPEN" not in monitor_statuses(browser_page)
    assert "nominal" in rail_text(browser_page).lower()


def test_open_schedule_incident_still_reaches_the_monitor(realtime_server, browser_page):
    schedule = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/schedule-status"]))
    open_slot = dict(RECOVERED_SLOT, lifecycle="open", recovered_by=None)
    schedule["incidents"] = [open_slot]
    schedule["open_incidents"] = [open_slot]
    stub_api(browser_page, {"/api/v1/schedule-status": schedule})
    open_realtime(browser_page, realtime_server)
    assert "OPEN" in monitor_statuses(browser_page)


def test_entry_without_a_timestamp_is_not_given_a_fake_clock(realtime_server, browser_page):
    stub_api(browser_page, {"/api/v1/runner-state":
                            _snapshot_with_decision(_decision(entries=[_entry()]))})
    open_realtime(browser_page, realtime_server)
    text = _journal_events_text(browser_page)
    assert "MES" in text
    assert "14:05" not in text
    assert "time not recorded" in text


def test_real_entry_time_is_shown_as_is(realtime_server, browser_page):
    stub_api(browser_page, {"/api/v1/runner-state": _snapshot_with_decision(
        _decision(entries=[_entry(entry_time="2026-08-14T19:40:00Z")]))})
    open_realtime(browser_page, realtime_server)
    assert "15:40" in _journal_events_text(browser_page)


def test_event_journal_orders_mixed_timezones_by_real_instant(realtime_server, browser_page):
    stub_api(browser_page, {
        "/api/v1/runner-state": _snapshot_with_decision(_decision(entries=[_entry()])),
        "/api/v1/session-events/": _session_events({
            "kind": "market_open_filled", "status": "info", "level": "INFO",
            "category": "TRADE", "inst": "MNQ", "sequence": 1,
            "ts": "2026-08-14T16:00:00Z",
            "message": "MNQ open filled",
        }),
    })
    open_realtime(browser_page, realtime_server)
    text = _journal_events_text(browser_page)
    assert text.index("MES") < text.index("MNQ")


def test_sharpe_is_withheld_below_the_sample_floor(realtime_server, browser_page):
    stub_api(browser_page, {"/api/v1/runner-state": _runner_with_metrics(
        4, {"calmar": None, "sharpe": 10.2112, "max_dd": 0.0, "total_return": 0.004575})})
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector(
        "#performanceSharpe", "el => el.textContent").strip() == "--"
    assert "n=4" in browser_page.eval_on_selector("#performanceSharpe", "el => el.title")


def test_sharpe_is_shown_once_the_sample_is_long_enough(realtime_server, browser_page):
    stub_api(browser_page, {"/api/v1/runner-state": _runner_with_metrics(
        25, {"calmar": 1.4, "sharpe": 0.88, "max_dd": 0.02, "total_return": 0.03})})
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector(
        "#performanceSharpe", "el => el.textContent").strip() == "0.88"


def test_hmm_fit_is_not_green_while_every_fit_warns(realtime_server, browser_page):
    stub_api(browser_page, {"/api/v1/session-events/": _session_events({
        "kind": "hmm_fit_diagnostic", "status": "diagnostic", "level": "WARN",
        "category": "MODEL / HMM FIT", "component": "runner", "sequence": 1,
        "ts": "2026-08-14T17:00:00Z", "attempts": 22, "completed_fits": 22,
        "non_convergence_count": 22, "message": "22/22 fits warned",
    })})
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector(
        "#modelFitStatus", "el => el.className") != "positive"
    assert "22 warn" in browser_page.eval_on_selector(
        "#modelFitStatus", "el => el.textContent")


def test_open_issues_coverage_names_stale_evidence_end(realtime_server, browser_page):
    """M7 frontend: coverage must name the last evidence date, not imply it reaches today."""
    issues = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/open-issues"]))
    issues["coverage"] = {"from": "2026-08-01", "to": "2026-08-14",
                          "evidence_ends": "2026-08-10", "stale_days": 4}
    stub_api(browser_page, {"/api/v1/open-issues": issues})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#openIssuesSource", "el => el.textContent")
    assert "evidence 2026-08-01 to 2026-08-10" in text
    assert "ends 4 days ago" in text
    assert browser_page.eval_on_selector(
        "#openIssuesSource", "el => el.classList.contains('warning')") is True


def test_broker_account_delta_is_visible_in_equity_header(realtime_server, browser_page):
    """M4: broker account equity can diverge sharply from the runner ledger."""
    runner = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    runner["payload"]["meta"]["broker_equity"] = 996312.42
    runner["payload"]["meta"]["paper_start"] = {"date": "2026-08-10", "equity": 1000480.0}
    stub_api(browser_page, {"/api/v1/runner-state": runner})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#brokerAccountContext", "el => el.textContent")
    assert "996,312" in text
    assert "4,168" in text
    assert browser_page.eval_on_selector(
        "#brokerAccountContext", "el => el.classList.contains('negative')") is True


def test_a_failed_source_is_named_in_words(realtime_server, browser_page):
    """M8: a single failed source must be named in the rail, not only dimmed."""
    stub_api(browser_page)
    browser_page.route(
        "**/api/v1/runner-state",
        lambda route: route.fulfill(status=500, content_type="application/json",
                                    body='{"error": "boom"}'))
    browser_page.goto(f"{realtime_server}/realtime", wait_until="domcontentloaded")
    browser_page.wait_for_selector("#statusRail .system-conclusion", timeout=10_000)
    assert "runner-state" in rail_text(browser_page).lower()


M2K_POS = {"inst": "M2KU6", "position": 1.0, "market_price": 3063.84,
           "market_value": 15319.2, "avg_cost": 15127.11, "realized_pnl": 0.0,
           "unrealized_pnl": 192.09, "sec_type": "FUT"}
M2K_RUNNER = {"inst": "M2K", "cluster": "roska4_swing", "direction": "LONG",
              "days_held": 4, "risk_sized": 602.14, "entry_day": "2026-08-10",
              "entry_price": 3025.3, "entry_time": None, "stop_price": 3020.24,
              "stop_order_id": "288", "stop_deferred": False, "contracts": 1}
M2K_SPEC = {"M2K": {"symbol": "M2K", "tick": 0.1, "tick_value": 0.5,
                    "point_value": 5.0, "local_symbol": "M2KU6", "status": "OBSERVED"}}


def _broker(positions, orders, specs=None) -> dict:
    payload = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/broker"]))
    payload["payload"]["positions"] = positions
    payload["payload"]["orders"] = orders
    payload["payload"]["contract_specs"] = specs or M2K_SPEC
    return payload


def _runner_positions(*positions) -> dict:
    payload = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    payload["payload"]["snapshots"][0]["open_positions"] = list(positions)
    return payload


def _persisted_runner_positions(*positions) -> dict:
    payload = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-positions"]))
    payload["payload"]["positions"] = list(positions)
    return payload


def _good_stop(**over) -> dict:
    order = {"inst": "M2KU6", "type": "STP", "action": "SELL", "qty": 1.0,
             "aux_price": 3020.2, "lmt_price": 0.0, "status": "PreSubmitted",
             "tif": "GTC", "order_id": 288}
    order.update(over)
    return order


def test_stop_at_the_wrong_price_is_not_counted_as_protection(realtime_server, browser_page):
    """M1: side/qty/status alone can count a non-protective stop as green."""
    stub_api(browser_page, {
        "/api/v1/broker": _broker([M2K_POS], [_good_stop(aux_price=3120.0, order_id=999)]),
        "/api/v1/runner-state": _runner_positions(M2K_RUNNER),
    })
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector(
        "#metricStopsCovered", "el => el.textContent").startswith("0")
    assert "invalid stop" in browser_page.eval_on_selector(
        "#nowMonitorList", "el => el.innerText").lower()


def test_stop_within_tick_tolerance_of_plan_still_counts(realtime_server, browser_page):
    """3020.2 vs plan 3020.24 is tick rounding for M2K, not bad protection."""
    stub_api(browser_page, {
        "/api/v1/broker": _broker([M2K_POS], [_good_stop()]),
        "/api/v1/runner-state": _runner_positions(M2K_RUNNER),
    })
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector(
        "#metricStopsCovered", "el => el.textContent").startswith("1")


def test_two_clusters_on_one_contract_reconcile_by_total(realtime_server, browser_page):
    """M2: IBKR nets one contract row while runner can carry multiple clusters."""
    stress = dict(M2K_RUNNER, cluster="roska4_stress", entry_price=3026.0,
                  stop_price=3021.0, stop_order_id="289")
    stub_api(browser_page, {
        "/api/v1/broker": _broker(
            [dict(M2K_POS, position=2.0)],
            [_good_stop(), _good_stop(order_id=289, aux_price=3021.0)]),
        "/api/v1/runner-state": _runner_positions(M2K_RUNNER, stress),
    })
    open_realtime(browser_page, realtime_server)
    monitor = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText").lower()
    assert "size mismatch" not in monitor
    assert "invalid stop" not in monitor
    assert browser_page.eval_on_selector(
        "#metricStopsCovered", "el => el.textContent").startswith("1")


def test_deferred_stop_reads_as_deferred_not_as_uncovered(realtime_server, browser_page):
    """M6: legal deferred protection should be visible as deferred, not uncovered."""
    stub_api(browser_page, {
        "/api/v1/broker": _broker([M2K_POS], []),
        "/api/v1/runner-state": _runner_positions(dict(M2K_RUNNER, stop_deferred=True,
                                                       stop_order_id=None)),
    })
    open_realtime(browser_page, realtime_server)
    covered = browser_page.eval_on_selector("#metricStopsCovered", "el => el.textContent")
    assert "deferred" in covered.lower()
    assert "nominal" in rail_text(browser_page).lower()


def test_quantity_survives_a_ratcheted_stop_id(realtime_server, browser_page):
    """M3: quantity matching must not depend on float price equality or stop id."""
    persisted = _persisted_runner_positions({
        "inst": "M2K", "cluster": "roska4_swing", "direction": "LONG",
        "contracts": 1, "entry_day": "2026-08-10 00:00:00", "entry_price": 3025.3,
        "stop_price": 3022.10, "stop_order_id": "301",
    })
    stub_api(browser_page, {
        "/api/v1/broker": _broker([M2K_POS], [_good_stop(order_id=301, aux_price=3022.1)]),
        "/api/v1/runner-state": _runner_positions(dict(M2K_RUNNER, contracts=None)),
        "/api/v1/runner-positions": persisted,
    })
    open_realtime(browser_page, realtime_server)
    monitor = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText").lower()
    assert "quantity missing" not in monitor
    assert "size mismatch" not in monitor


def test_no_dead_render_functions_remain():
    """L1: legacy rail helpers are no longer part of the rendered rail."""
    js = (ROOT / "global_index" / "dash" / "realtime" / "realtime.js").read_text(encoding="utf-8")
    for name in ("renderRailLegacy", "railItem", "railTips"):
        assert js.count(name) == 0, f"{name} is still present but never called"


def test_no_orphan_scheduler_health_css():
    css = (ROOT / "global_index" / "dash" / "realtime" / "realtime.css").read_text(encoding="utf-8")
    assert ".scheduler-health" not in css


def _known_debt_job(index: int) -> dict:
    minute = index * 5
    return {
        "id": f"job-{index}", "job_id": f"LIVE_DAY_14{minute:02d}",
        "job_type": "live_day", "status": "completed_with_debt",
        "started_at": f"2026-08-14T18:{minute:02d}:00Z",
        "ended_at": f"2026-08-14T18:{minute:02d}:30Z",
        "duration_seconds": 30,
        "reason": None,
        "diagnostics": ["G2 HARD: model age is stale"],
        "events": [],
    }


def test_job_journal_groups_repeated_known_debt_rows(realtime_server, browser_page):
    """L3: repeated known-debt executions should not crowd out distinct job rows."""
    journal = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    journal["jobs"] = [_known_debt_job(index) for index in range(5)]
    assert journal["jobs"], "test must exercise a non-empty job list"
    stub_api(browser_page, {"/api/v1/job-journal/": journal})
    open_realtime(browser_page, realtime_server)
    rows = browser_page.eval_on_selector_all("#journal > li", "els => els.map(el => el.innerText)")
    assert rows, "journal rendered no rows"
    joined = "\n".join(rows).lower()
    assert len(rows) == 2
    assert "5 slots completed with the same known debt" in joined


def test_open_issues_stay_expanded_on_mobile(realtime_server, browser_page):
    """L4: mobile must not hide existing issues behind a closed details element."""
    browser_page.set_viewport_size({"width": 390, "height": 844})
    issues = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/open-issues"]))
    issues["issues"] = [{
        "key": "known_debt:model_age", "status": "known_debt", "component": "runner",
        "title": "Model age remains HARD stale", "problem": "HMM fit is 20 months old.",
        "impact": "The stale-model guard remains active.", "action": "Complete the re-freeze.",
        "evidence": "G2 HARD", "resolution_evidence": "A later runner observation reports OK.",
        "first_seen": "2026-08-10T18:05:00Z", "last_seen": "2026-08-14T06:58:51Z",
        "occurrences": 163,
    }]
    assert issues["issues"], "test must exercise a non-empty issue list"
    stub_api(browser_page, {"/api/v1/open-issues": issues})
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector("#openIssuesShell", "el => el.open") is True


# ── AUDIT PHASE 2 nhóm B: đường dẫn chưa ai chạy ─────────────────────────────
# Ba nhánh dưới đây đã có code từ trước nhưng chưa test nào đi qua và chưa lần
# nào xảy ra thật. Đây là test CHARACTERIZATION: xanh nghĩa là nhánh vốn đã
# đúng và một "không biết" trở thành "ổn"; đỏ nghĩa là một finding thật.
# Cả ba đều là đường dẫn mất tiền.

def _runner_state_with(**meta_over) -> dict:
    payload = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    payload["payload"]["meta"]["operational_status"].update(meta_over)
    return payload


@pytest.mark.parametrize("level", ["HALTED", "SHUTDOWN"])
def test_a_tripped_circuit_breaker_is_never_reported_as_nominal(realtime_server, browser_page, level):
    """P2-B1. Circuit breaker là trạng thái quan trọng nhất trên một dashboard
    giao dịch: hệ thống tự dừng vì lỗ ngày −4% hoặc 5 lệnh thua liên tiếp.
    `stripBreakerBad` có nhánh nhưng chưa test nào đi qua — nếu nó hỏng thì hỏng
    đúng lúc mọi thứ đang tệ nhất."""
    stub_api(browser_page, {
        "/api/v1/runner-state": _runner_state_with(breaker={"level": level, "dd_pct": 4.2}),
    })
    open_realtime(browser_page, realtime_server)
    rail = rail_text(browser_page)
    assert "nominal" not in rail.lower(), rail
    assert f"risk breaker {level}" in rail, rail


def test_a_position_the_runner_does_not_know_about_raises_an_incident(realtime_server, browser_page):
    """P2-B2. IBKR giữ một vị thế runner không biết: không stop theo kế hoạch,
    không nằm trong tính toán exposure. Runner không thể quản lý thứ nó không
    thấy, nên trang phải nói ra."""
    stub_api(browser_page, {
        "/api/v1/broker": _broker([M2K_POS], [_good_stop()]),
        "/api/v1/runner-state": _runner_positions(),          # runner khong giu gi
    })
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText")
    assert "broker-only position" in text, text
    assert "OPEN" in monitor_statuses(browser_page)
    assert "nominal" not in rail_text(browser_page).lower()


def test_a_job_on_another_day_shows_which_day(realtime_server, browser_page):
    """Tối thứ Sáu, "NEXT JOB 00:20 ET" đọc như còn vài tiếng — thực ra là thứ
    Hai, cách 46 tiếng. Giờ trần chỉ đủ dùng khi mọi thứ cùng một ngày."""
    schedule = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/schedule-status"]))
    far = "2099-12-28T05:20:00Z"          # thu Hai, chac chan khac hom nay
    schedule["next_scheduled_job"] = {"job_id": "STOP_REPAIR_0020", "at": far}
    schedule["next_decision_job"] = {"job_id": "LIVE_DAY_1405", "at": far}
    stub_api(browser_page, {"/api/v1/schedule-status": schedule})
    open_realtime(browser_page, realtime_server)
    facts = browser_page.eval_on_selector("#nowScheduleFacts", "el => el.innerText")
    assert "Mon" in facts, facts
    assert "00:20 ET" in facts, facts


def _kill_endpoints(page, *paths) -> None:
    """Cho các endpoint chỉ định trả 500; phần còn lại vẫn stub bình thường."""
    stub_api(page)
    for path in paths:
        page.route(f"**{path}", lambda route: route.fulfill(
            status=500, content_type="application/json", body='{"error": "boom"}'))


def test_numbers_from_a_dead_source_are_not_shown_as_current(realtime_server, browser_page):
    """P2-A1. Khi /api/v1/runner-state chết, `state.runner` giữ payload cũ nên
    equity, drawdown và realized vẫn render như số hiện tại — chỉ mờ 42%. Người
    vận hành đọc được một con số trông sống động từ một nguồn đã chết."""
    # Phải để MỘT lần poll thành công trước rồi mới giết endpoint. Nếu nó chết
    # ngay từ đầu thì state.runner chưa từng có payload, số ra "--" vì THIẾU DỮ
    # LIỆU chứ không phải vì code kiểm lỗi — test sẽ xanh mà chẳng chứng minh gì.
    stub_api(browser_page)
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector("#metricEquity", "el => el.textContent").strip() != "--", \
        "lan poll dau phai thanh cong thi test moi co y nghia"

    browser_page.route("**/api/v1/runner-state", lambda route: route.fulfill(
        status=500, content_type="application/json", body='{"error": "boom"}'))
    browser_page.wait_for_function(
        "() => document.getElementById('metricEquity').textContent.trim() === '--'",
        timeout=20_000)
    for metric in ("metricEquity", "metricRealized", "metricDrawdown", "performanceNet"):
        value = browser_page.eval_on_selector(f"#{metric}", "el => el.textContent").strip()
        assert value == "--", f"{metric} hien '{value}' tu nguon da chet"
    # Nguồn broker vẫn sống nên số của nó KHÔNG được bị xoá theo.
    assert browser_page.eval_on_selector("#metricPositions", "el => el.textContent").strip() != "--"
    # Và trang vẫn phải nói ra nguồn nào hỏng.
    assert "runner-state" in rail_text(browser_page).lower()


def test_the_fatal_banner_speaks_only_for_a_dead_backend(realtime_server, browser_page):
    """P2-A2. Banner ghi "Monitor backend unavailable". Một endpoint chết KHÔNG
    phải backend chết — lúc đó rail gọi tên nguồn hỏng là đủ và đúng. Banner chỉ
    được xuất hiện khi mọi nguồn im lặng. Đây là ghim hành vi đúng, không phải
    sửa lỗi."""
    _kill_endpoints(browser_page, "/api/v1/runner-state")
    browser_page.goto(f"{realtime_server}/realtime", wait_until="domcontentloaded")
    browser_page.wait_for_selector("#statusRail .system-conclusion", timeout=10_000)
    assert browser_page.eval_on_selector("#fatalBanner", "el => el.hidden") is True

    browser_page.route("**/api/**", lambda route: route.fulfill(
        status=500, content_type="application/json", body='{"error": "boom"}'))
    browser_page.goto(f"{realtime_server}/realtime?all-dead=1", wait_until="domcontentloaded")
    browser_page.wait_for_function(
        "() => document.getElementById('fatalBanner') && !document.getElementById('fatalBanner').hidden",
        timeout=10_000)
    assert browser_page.eval_on_selector("#fatalBanner", "el => el.textContent").strip() \
        == "Monitor backend unavailable."


def test_a_stale_model_is_shown_as_debt_without_crying_wolf(realtime_server, browser_page):
    """P2-B4. Fixture giờ mô tả đúng production: model 20 tháng, G2 HARD. Hai
    nửa đều phải đúng — hiện ra ở header, nhưng KHÔNG kéo rail vào báo động, vì
    known debt cố ý tách khỏi lane sự cố mới. Một báo động không bao giờ tắt là
    báo động người ta ngừng đọc."""
    stub_api(browser_page)
    open_realtime(browser_page, realtime_server)
    assert "20 mo stale" in browser_page.eval_on_selector("#modelInputAge", "el => el.textContent")
    assert browser_page.eval_on_selector("#modelInputAge", "el => el.className") == "warning"
    assert "nominal" in rail_text(browser_page).lower()


def test_a_failed_refreeze_is_shown_as_debt_not_as_an_incident(realtime_server, browser_page):
    """P2-B7. `refreeze.pending` bật khi pipeline re-freeze thất bại: model cũ
    vẫn được dùng, giao dịch VẪN CHẠY, runner re-alert mỗi lần chạy. Đó là debt
    chứ không phải halt — phải hiện ra, nhưng không được kéo rail vào báo động,
    cùng cách đối xử với model age."""
    stub_api(browser_page, {"/api/v1/runner-state": _runner_state_with(
        refreeze={"pending": True, "attempts": 3, "fail_type": "data_missing"})})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText")
    assert "re-freeze" in text.lower(), text
    assert "KNOWN DEBT" in monitor_statuses(browser_page)
    assert "OPEN" not in monitor_statuses(browser_page)
    assert "nominal" in rail_text(browser_page).lower()


def test_blocked_entries_are_visible_on_the_page(realtime_server, browser_page):
    """P2-B5. `regime_unreliable` là cờ HMM stale guard G1 HARD bật khi SPY cũ
    quá 5 ngày làm việc; khi nó bật, runner chặn MỌI entry. Trang hiện độ tươi
    SPY nhưng chưa nói hệ quả — hệ thống đã ngừng vào lệnh."""
    stub_api(browser_page, {"/api/v1/runner-state": _runner_state_with(
        regime_unreliable=True,
        regime_freshness={"status": "HARD", "bday_stale": 6, "last_spy_date": "2026-08-05"})})
    open_realtime(browser_page, realtime_server)
    page_text = browser_page.eval_on_selector("main", "el => el.innerText").lower()
    assert "entries" in page_text and "blocked" in page_text, \
        "trang khong noi gi ve viec entry dang bi chan"


def test_guard_blocked_and_cap_rejected_signals_are_listed(realtime_server, browser_page):
    """P2-B6. Cả hai đã xảy ra thật (log 08-10 có REJECTED SHORT MNQ vì
    `roska4_swing gross 10.9% > cap 5.0%`) nhưng chưa test nào render chúng."""
    stub_api(browser_page, {"/api/v1/runner-state": _snapshot_with_decision(_decision(
        halted_today=2,
        rejected_detail=[{"inst": "MNQ", "direction": "SHORT", "cluster": "roska4_swing",
                          "risk_sized": 3340.54,
                          "reason": "roska4_swing gross 10.9% > cap 5.0%"}]))})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#decisionRejected", "el => el.innerText")
    assert "MNQ" in text and "cap 5.0%" in text, text
    assert "2 halted" in text, text
    assert browser_page.eval_on_selector("#decisionRejectedCount", "el => el.textContent") == "2"


def test_a_position_only_the_runner_believes_in_raises_an_incident(realtime_server, browser_page):
    """P2-B3. Chiều ngược lại: runner nghĩ đang giữ, broker không có. Mọi logic
    bảo vệ chạy trên một trạng thái không tồn tại."""
    stub_api(browser_page, {
        "/api/v1/broker": _broker([], []),                    # broker rong
        "/api/v1/runner-state": _runner_positions(M2K_RUNNER),
    })
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText")
    assert "runner-only position" in text, text
    assert "OPEN" in monitor_statuses(browser_page)
    assert "nominal" not in rail_text(browser_page).lower()
