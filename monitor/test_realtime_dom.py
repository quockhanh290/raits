"""DOM smoke tests: chạy trang realtime thật trong chromium với API bị stub.

Suite backend hiện có rất mạnh nhưng frontend chỉ được kiểm bằng
`assert "chuoi" in file`, nên mọi finding trong REALTIME_DASHBOARD_AUDIT.md đều
lọt qua. Harness này dựng Flask trên cổng tạm (static assets là thật), rồi chặn
`/api/**` để dựng đúng trạng thái cần kiểm.
"""
from __future__ import annotations

import json
import re
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
    # Stage 5AB. The page fetches this now, and an endpoint missing from this table is a
    # 404 the console-error test catches — which is how this entry came to exist.
    "/api/v1/track1-runtime": {
        "source": "track1_runtime", "route": "track1_candidate",
        "book": {"present": False}, "checkpoint": {"present": False},
        "window_coverage": {"present": True, "days": [], "latest": {}},
        "slot_timing": {"present": True, "days": {}},
        "explanations": {"present": False},
        "gates": {"blocking_now": ["B1_broker_account_or_legacy_retirement"],
                  "orders_possible": False, "orders_detail": []},
        "safety": {"jobs": [], "positions_path": "live_positions.track1.json",
                   "stop_path": "STOP_TRADING.track1", "client_id": 90, "note": ""},
    },
    # Stage 5ZZL. Present so the shared healthy-page fixture does not 404 on the market
    # view -- an unstubbed endpoint shows up as a console error and fails the healthy-page
    # test for a reason that has nothing to do with the page being healthy.
    "/api/v1/track1-market-view": {
        "market_view": {"schema": "track1_market_view/1", "route": "track1_candidate",
                        "session_date": "2026-08-14", "now_et": "13:00",
                        "levels_note": "entry levels not exposed by sleeve evidence yet",
                        "sleeves": {}},
        "regime": {"status": "UNKNOWN", "code": "no_record", "label": None,
                   "label_date": None, "age_hours": None, "detail": "no record",
                   "recent": [], "context": [], "score": None, "shift_threshold": None,
                   "score_note": "not exposed by model",
                   "threshold_note": "not exposed by model",
                   "line": "Regime label UNKNOWN: no record",
                   "verification": {"status": "UNKNOWN"}},
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
    # Thế giới MẶC ĐỊNH của bộ test là một thế giới lành: tuyến đặt được lệnh, không cổng
    # nào chặn. Không có mục này, `stub_api` để request đi thẳng xuống backend thật, và
    # trạng thái thật hôm nay — không đặt được lệnh — làm dải đầu thôi nói "nominal" trong
    # năm phép kiểm về chuyện KHÁC HẲN. Phép kiểm nào muốn trạng thái chặn thì tự ghim.
    "/api/v1/track1-runtime": {
        "route": "track1_candidate",
        "gates": {"orders_possible": True, "blocking_now": []},
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


def _all_fits_warned() -> dict:
    """A legacy session log where every one of 22 fits warned — the real 2026-08-24 shape."""
    return {"kind": "hmm_fit_diagnostic", "status": "diagnostic", "level": "WARN",
            "category": "MODEL / HMM FIT", "component": "runner", "sequence": 1,
            "ts": "2026-08-14T17:00:00Z", "attempts": 22, "completed_fits": 22,
            "non_convergence_count": 22, "message": "22/22 fits warned"}


def _view_with_fit_inputs() -> dict:
    view = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/track1-market-view"]))
    view["regime"].update({
        "status": "PASS", "code": "labelled", "label": "Calm", "label_date": "2026-08-14",
        "inputs": {"start": "2018-01-01", "fit_end": "2024-12-31",
                   "n_states": 3, "labels": 2179},
    })
    return view


def test_hmm_fit_describes_the_frozen_fit_not_the_legacy_session_count(
        realtime_server, browser_page):
    """The tile must describe the fit the live route reads, and must not print the legacy
    runner's per-session convergence count even while that log is being served.

    `hmm_fit_diagnostic` is grouped out of `live_day_MMDD.log`, a file only the legacy
    runner writes — Track 1 lists its siblings among the paths it must never touch. So in
    track1-only shadow the tile was reporting whatever day legacy last ran as today's.
    The count does not survive the move either: 22 attempts in one day is the legacy runner
    refitting per slot, and Track 1 reads one frozen fit without refitting per session.

    Reads with the test below it: that one proves this same fixture DOES produce "22 warn"
    when no Track 1 record exists, so the absence asserted here cannot pass vacuously.
    """
    stub_api(browser_page, {"/api/v1/track1-market-view": _view_with_fit_inputs(),
                            "/api/v1/session-events/": _session_events(_all_fits_warned())})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#modelFitStatus", "el => el.textContent")
    assert "3 states" in text and "2,179" in text
    assert "22" not in text
    assert "frozen fit" in browser_page.eval_on_selector("#modelFitStatus", "el => el.title")


def test_hmm_fit_falls_back_to_the_legacy_log_when_no_track_1_record_exists(
        realtime_server, browser_page):
    """Nothing was deleted: a machine with no Track 1 regime record reads exactly as before,
    and a day where every fit warned still must not read green."""
    view = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/track1-market-view"]))
    view["regime"] = None
    stub_api(browser_page, {"/api/v1/track1-market-view": view,
                            "/api/v1/session-events/": _session_events(_all_fits_warned())})
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector(
        "#modelFitStatus", "el => el.className") != "positive"
    assert "22 warn" in browser_page.eval_on_selector(
        "#modelFitStatus", "el => el.textContent")


def test_fit_end_keeps_the_track_1_value_and_is_not_rewritten_by_next_js(
        realtime_server, browser_page):
    """One element, one writer. next.js used to fill `#modelFitEnd` from the legacy
    `model_age.model_name`, so whichever renderer ran last decided the value — and the
    legacy string could silently replace one the other route had already verified. The two
    agree in production (both 2024-12-31), which is why nothing on screen showed it; here
    the legacy fixture names a different year so a rewrite would be visible.
    """
    view = _view_with_fit_inputs()
    runner = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    runner["payload"]["meta"]["operational_status"]["model_age"]["model_name"] = "fit_end=2019-01-01"
    stub_api(browser_page, {"/api/v1/track1-market-view": view,
                            "/api/v1/runner-state": runner})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_timeout(1200)
    text = browser_page.eval_on_selector("#modelFitEnd", "el => el.textContent")
    assert "2019" not in text, f"legacy value rewrote the Track 1 one: {text!r}"
    assert "Dec 31" in text
    assert "PASS" in browser_page.eval_on_selector("#modelFitEnd", "el => el.title")         or "label check" in browser_page.eval_on_selector("#modelFitEnd", "el => el.title")


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
    """M4, rewritten in Stage 5ZZF. The CONCERN is unchanged: a sharp divergence around the
    account must be visible rather than quietly averaged away. What changed is where the
    divergence is measured from.

    The original asserted the delta `996,312 - 1,000,480 = 4,168` appeared in the header. That
    subtraction crossed a currency boundary — the starting figure's own note reads
    "connect_test_paper.py, DUR125337, CAD" and the equity carried no currency at all — and it
    was drawn from a runner payload that stood 76.8 hours old while its envelope reported
    `not_expected_yet`, because in track1-only mode the legacy runner is never scheduled and
    nothing ever calls it stale. It said `Broker acct $996,731 / -$3,749` for three days after
    the account had been reset to USD 250,817.91.

    So the divergence is now measured between the RECORDED BASELINE and the legacy figure, and
    the legacy figure may appear only under its own name and only with its age. This test holds
    that, on the same scenario the original used.
    """
    runner = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    runner["payload"]["meta"]["broker_equity"] = 996312.42
    runner["payload"]["meta"]["paper_start"] = {
        "date": "2026-08-10", "equity": 1000480.0,
        "note": "connect_test_paper.py, DUR125337, CAD"}
    runner["age_seconds"] = 276575.0
    t1 = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/track1-runtime"]))
    t1["paper_account"] = {"status": "PASS", "code": "account_flat_and_funded",
                           "currency": "USD", "equity": 250817.91,
                           "account_id": "DUR125337", "expected_equity": 250000.0,
                           "expected_currency": "USD", "line": "",
                           "separate_from_shadow_evidence": True}
    stub_api(browser_page, {"/api/v1/runner-state": runner, "/api/v1/track1-runtime": t1})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#brokerAccountContext", "el => el.textContent")

    # the account the route would actually start from
    assert "250,818" in text, text
    # the divergence is stated, and the legacy number wears its own name and its age
    # Stage 5ZZH restated 5ZZF's pin. The clause became "Legacy runner state stale:" so it
    # says WHY the figure is not the account rather than only that it is old. The
    # invariant is unchanged and is what is asserted here: the legacy figure appears
    # under its own name, and never without its age.
    assert "legacy runner state" in text.lower(), text
    assert "ago" in text.lower(), "the legacy figure must never appear without its age"
    assert " ago ago" not in text.lower(), text
    assert "996,312" in text, text
    assert "ago" in text.lower(), text
    # and the cross-currency subtraction is gone in every spelling
    assert "4,168" not in text, text
    assert "Broker acct" not in text, text
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


def test_job_journal_shows_one_row_per_execution(realtime_server, browser_page):
    """Every execution gets its own row, however many share a debt.

    This used to assert the opposite: more than three known-debt runs collapsed to the
    newest one plus a summary line. That was L3's remedy for repeated debt crowding out
    distinct jobs, and the operator rejected it after seeing what it cost:

      * the header counts jobs.length and the list did not, so it read "14 jobs" above
        two rows with nothing on the page reconciling them — the night's slots looked
        lost rather than folded;
      * the summary printed the FULL debt count while one of those rows was already
        rendered above it, so two shown plus thirteen remaining came to fifteen out of
        fourteen;
      * and it named one cause, "G2 model age", for a status the backend assigns purely
        on "the child exited OK but logged an error" — nothing in the code checked that
        the cause matched, so the first debt from a different diagnostic would have been
        filed under a cause that was not its own, and hidden behind it.

    Both assertions below are discriminating: bringing the collapse back turns five rows
    into two AND puts the summary text back, so either one alone would catch it.
    """
    journal = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    journal["jobs"] = [_known_debt_job(index) for index in range(5)]
    assert journal["jobs"], "test must exercise a non-empty job list"
    stub_api(browser_page, {"/api/v1/job-journal/": journal})
    open_realtime(browser_page, realtime_server)
    rows = browser_page.eval_on_selector_all("#journal > li", "els => els.map(el => el.innerText)")
    assert rows, "journal rendered no rows"
    joined = "\n".join(rows)

    assert len(rows) == 5, (
        f"five executions must produce five rows; a collapsed list hides runs the "
        f"header still counts. got {len(rows)}")
    assert "completed with the same known debt" not in joined.lower(), (
        "the summary line is back, which means rows are being hidden behind it again")
    for index in range(5):
        assert f"LIVE_DAY_14{index * 5:02d}" in joined, (
            f"execution LIVE_DAY_14{index * 5:02d} has no row of its own")


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
        "/api/v1/runner-state": _runner_state_with(breaker={"level": level, "dd_pct_display": 4.2}),
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
    # Stage 5ZZZ-CG. Ghim MỤC ĐÍCH — "không con số nào" — chứ không ghim chuỗi `--`.
    #
    # Khi test này được viết, `--` là từ vựng duy nhất của trang cho sự vắng mặt. Từ đó
    # trang có thêm những lời từ chối CÓ TÊN: ô equity in "not measured" / "baseline
    # UNKNOWN", và ô mức sụt giờ in "unavailable" kèm lý do ở dòng dưới. Cả hai đều không
    # phải con số, nên đều thoả điều mục đích của test nói: người vận hành không được đọc
    # một con số trông sống động từ một nguồn đã chết.
    #
    # Bản assert cũ sẽ đỏ trước một cải thiện, và đã sắp đỏ vì lý do khác: ô equity sẽ in
    # "not measured" ngay khi Track 1 công bố mốc tài khoản, hoàn toàn không liên quan tới
    # nguồn nào chết. Bản mới chặt hơn ở chiều đáng chặt: bất kỳ CHỮ SỐ nào cũng đỏ, và một
    # lời từ chối có tên thì phải nói được vì sao.
    for metric in ("metricEquity", "metricRealized", "metricDrawdown", "performanceNet"):
        value = browser_page.eval_on_selector(f"#{metric}", "el => el.textContent").strip()
        assert value, f"{metric} de trong, khong noi gi"
        assert not re.search(r"\d", value), f"{metric} hien '{value}' tu nguon da chet"
        if value != "--":
            reason = browser_page.eval_on_selector(f"#{metric}", "el => el.title")
            assert len(reason.strip()) > 20, f"{metric} tu choi '{value}' ma khong noi vi sao"
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


def test_a_closed_position_stops_raising_the_runner_only_incident(realtime_server, browser_page):
    """Đo được 2026-08-17: cảnh báo đúng nội dung, sai thời điểm, sống 4 tiếng rưỡi.

    MAX_HOLD lúc 09:31 đóng M2K, ghi live_positions.json rỗng, và KHÔNG xuất bản ảnh
    chụp mới — `dump_state` chỉ chạy trong `run_day`. Cảnh báo lại đọc
    `latestSnap().open_positions`, nên nó vẫn kể chuyện trước 09:31 cho tới slot 14:05.

    Ba nguồn lúc đó: ảnh chụp 1 vị thế · live_positions.json 0 · IBKR 0. Hai nguồn nói
    rỗng và cảnh báo dựng trên cái thứ ba.

    Không phải cảnh báo vô hại: mức `incident`, và nội dung nói "logic bảo vệ sau đó có
    thể dùng trạng thái vị thế cũ" — mô tả đúng một tình huống nguy hiểm, cho một tình
    huống không tồn tại.

    live_positions.json là nguồn được ghi bởi MỌI đường đóng vị thế, không riêng
    `run_day`, nên nó là nguồn đúng cho câu "runner đang giữ gì NGAY BÂY GIỜ".
    """
    stub_api(browser_page, {
        "/api/v1/broker": _broker([], []),                      # broker rỗng
        "/api/v1/runner-state": _runner_positions(M2K_RUNNER),  # ảnh chụp còn cũ
        "/api/v1/runner-positions": _persisted_runner_positions(),   # sổ đã rỗng
    })
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText")
    assert "runner-only position" not in text, (
        f"vị thế đã đóng và ghi vào sổ, nhưng bảng vẫn báo runner đang giữ — cảnh báo "
        f"đang đọc ảnh chụp thay vì sổ: {text[:300]}")


def test_a_position_only_the_runner_believes_in_raises_an_incident(realtime_server, browser_page):
    """P2-B3. Chiều ngược lại: runner nghĩ đang giữ, broker không có. Mọi logic
    bảo vệ chạy trên một trạng thái không tồn tại.

    Đối chứng cho phép kiểm ngay trên: nếu cảnh báo bị tắt hẳn thay vì đổi nguồn, phép
    kiểm kia vẫn xanh còn cái này đỏ.
    """
    stub_api(browser_page, {
        "/api/v1/broker": _broker([], []),                    # broker rong
        "/api/v1/runner-state": _runner_positions(M2K_RUNNER),
        "/api/v1/runner-positions": _persisted_runner_positions(M2K_RUNNER),
    })
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText")
    assert "runner-only position" in text, text
    assert "OPEN" in monitor_statuses(browser_page)
    assert "nominal" not in rail_text(browser_page).lower()

# ══════════════════════════════════════════════════════════════════════════════
# Stage 5ZZF — the account line, driven with the exact numbers that were on the page
# ══════════════════════════════════════════════════════════════════════════════

def _t1_with_account(equity=250817.91, status="PASS", currency="USD"):
    """The Track 1 runtime payload carrying a recorded baseline."""
    base = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/track1-runtime"]))
    base["paper_account"] = {
        "status": status, "code": "account_flat_and_funded", "currency": currency,
        "equity": equity, "account_id": "DUR125337",
        "expected_equity": 250000.0, "expected_currency": "USD",
        "line": f"Paper account baseline: {currency} {equity:,.0f} — broker reconcile flat",
        "separate_from_shadow_evidence": True,
    }
    return base


def _runner_with_legacy_equity(equity=996730.93):
    """The runner-state payload as it actually stood: three days old, carrying a CAD-era start
    and an unlabelled equity, with a freshness that says `not_expected_yet` rather than stale."""
    rs = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    rs["freshness"] = "not_expected_yet"
    rs["age_seconds"] = 276575.0
    rs.setdefault("payload", {}).setdefault("meta", {})
    rs["payload"]["meta"]["broker_equity"] = equity
    rs["payload"]["meta"]["paper_start"] = {
        "date": "2026-07-08", "equity": 1000480.0,
        "note": "connect_test_paper.py, DUR125337, CAD"}
    return rs


def test_5zzf_the_account_line_shows_the_track1_baseline_not_the_stale_legacy_number(
        realtime_server, browser_page):
    """The page said `Broker acct $996,731 / -$3,749 since 2026-07-08` for three days after the
    account was reset to USD 250,817.91."""
    stub_api(browser_page, {
        "/api/v1/track1-runtime": _t1_with_account(),
        "/api/v1/runner-state": _runner_with_legacy_equity(),
    })
    open_realtime(browser_page, realtime_server)
    text = browser_page.inner_text("#brokerAccountContext")

    assert "250,818" in text, text
    import re as _re
    # The figure may appear ONLY inside the legacy clause. Cutting that clause out and
    # then looking for the number again is what makes this an assertion and not a wish.
    assert "996,731" not in _re.sub(r"Legacy runner state[^·]*", "", text), text
    assert "Broker acct" not in text, text
    # the old cross-currency delta is gone in every spelling
    assert "-3,749" not in text and "3,749" not in text, text


def test_5zzf_a_material_divergence_from_the_legacy_number_is_called_out(
        realtime_server, browser_page):
    stub_api(browser_page, {
        "/api/v1/track1-runtime": _t1_with_account(),
        "/api/v1/runner-state": _runner_with_legacy_equity(),
    })
    open_realtime(browser_page, realtime_server)
    text = browser_page.inner_text("#brokerAccountContext")
    # Stage 5ZZH restated 5ZZF's pin. The clause became "Legacy runner state stale:" so it
    # says WHY the figure is not the account rather than only that it is old. The
    # invariant is unchanged and is what is asserted here: the legacy figure appears
    # under its own name, and never without its age.
    assert "legacy runner state" in text.lower(), text
    assert "ago" in text.lower(), "the legacy figure must never appear without its age"
    assert " ago ago" not in text.lower(), text
    # and it says how old that number is, rather than presenting it as current
    assert "ago" in text.lower(), text
    cls = browser_page.get_attribute("#brokerAccountContext", "class") or ""
    assert "negative" in cls, "a 299% divergence rendered as an ordinary line"


def test_5zzf_a_fresh_broker_reading_sits_beside_the_baseline_not_inside_it(
        realtime_server, browser_page):
    """`/api/v1/broker` is allowed as the current broker figure and must not be confused with
    the recorded baseline. Here they differ by ordinary live drift."""
    brk = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/broker"]))
    brk["payload"]["equity"] = 250818.18
    stub_api(browser_page, {
        "/api/v1/track1-runtime": _t1_with_account(250817.91),
        "/api/v1/broker": brk,
        "/api/v1/runner-state": _runner_with_legacy_equity(250800.0),   # not material
    })
    open_realtime(browser_page, realtime_server)
    text = browser_page.inner_text("#brokerAccountContext")
    assert "Paper account" in text and "250,818" in text, text
    assert "broker now" in text.lower(), text
    # a small legacy difference is not shouted about
    # Stage 5ZZH: the clause is now "Legacy runner state stale:". A small legacy
    # difference is still not shouted about, which is what this has always asserted.
    assert "legacy runner state" not in text.lower(), text


def test_5zzf_without_a_baseline_the_legacy_number_appears_only_under_its_own_name(
        realtime_server, browser_page):
    t1 = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/track1-runtime"]))
    t1.pop("paper_account", None)
    brk = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/broker"]))
    brk["freshness"] = "stale"
    stub_api(browser_page, {
        "/api/v1/track1-runtime": t1,
        "/api/v1/broker": brk,
        "/api/v1/runner-state": _runner_with_legacy_equity(),
    })
    open_realtime(browser_page, realtime_server)
    text = browser_page.inner_text("#brokerAccountContext")
    assert "Legacy runner state" in text, text
    assert "not the current account" in text, text
    assert "Broker acct" not in text, text


def test_5zzf_a_legacy_scoped_issue_is_still_listed_and_carries_no_scope_chip(
        realtime_server, browser_page):
    """Hai nửa, và chỉ một nửa đổi.

    GIỮ NGUYÊN — một mục thuộc tuyến cũ vẫn phải NẰM TRONG danh sách. Đó là bất biến gốc
    của Stage 5ZZF: gắn nhãn, không giấu đi. Một mục biến mất là một mục không ai quay lại
    được.

    ĐÃ ĐỔI — không còn chip phạm vi. Quyết định của chủ dự án 2026-09-06. Ba chip trên một
    dòng hai dòng chữ là quá nhiều, và hai trong ba nhãn ("Shared", "Model") là từ của
    người viết mã: người đọc nhìn vào không biết chúng nghĩa gì. Phân biệt duy nhất thật sự
    đổi cách đọc — đã nghỉ hưu hay chưa — vẫn còn, ở tiêu đề nhóm thu gọn được.

    Ghim theo cả hai chiều để lần rà sau không "khôi phục" chip ấy: nó đã ở đây một lần rồi.
    """

    issues = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/open-issues"]))
    issues["issues"] = [
        {"key": "paper:pnl:paper_flex_total_mismatch", "status": "incident",
         "component": "runner", "title": "Paper vs Flex P&L total mismatch",
         "problem": "x", "first_seen": "2026-08-20T00:00:00Z",
         "last_seen": "2026-08-27T00:00:00Z", "occurrences": 1, "impact": "x",
         "action": "x", "resolution_evidence": "x", "evidence": "x",
         "route_scope": "legacy",
         "scope_reason": "compares the LEGACY paper ledger; it reads no Track 1 artefact",
         "track1_readiness_blocker": False},
    ]
    stub_api(browser_page, {"/api/v1/open-issues": issues})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#openIssueList .issue-list-row", timeout=10_000)
    # Nửa giữ nguyên: mục vẫn nằm trong danh sách.
    rows = browser_page.eval_on_selector_all(
        "#openIssueList .issue-list-row", "els => els.length")
    assert rows == 1, rows
    # Nửa đã đổi: không chip phạm vi nào, ở cả danh sách lẫn khối chi tiết.
    scope = browser_page.eval_on_selector_all(
        ".issue-scope", "els => els.map(e => e.textContent.trim())")
    assert scope == [], f"chip phạm vi đã quay lại: {scope}"
    # Và hai chip còn lại vẫn nói được nguồn và trạng thái.
    kept = browser_page.eval_on_selector_all(
        "#openIssueList .issue-origin, #openIssueList .issue-status",
        "els => els.map(e => e.textContent.trim())")
    assert len(kept) == 2, kept


# ══════════════════════════════════════════════════════════════════════════════════════
# Stage 5ZZY — the market view's setup lanes and the regime monitor.
#
# The shared fixture serves `sleeves: {}`, so every test above this line renders the market
# view as an empty panel and none of them touches the code that draws it. These build a
# sleeve that looks like the real one — the shape is copied from a measured payload, not
# invented — and check the three claims the panel makes that could be false.
# ══════════════════════════════════════════════════════════════════════════════════════
def _mv_slots(n: int, decided: int, *, signal_at: int | None = None,
              missed_at: int | None = None) -> list[dict]:
    out = []
    for i in range(n):
        hh, mm = divmod(70 + i * 5, 60)
        if i == missed_at:
            st, why = "missed", "no record was written for this slot"
        elif i == signal_at:
            st, why = "signal", "decided"
        elif i < decided:
            st, why = "no_signal", "decided"
        else:
            st, why = "future", "has not fired yet"
        out.append({"slot_id": f"TRACK1_NKD_{hh:02d}{mm:02d}", "time_et": f"{hh:02d}:{mm:02d}",
                    "status": st, "reason": why, "candidate_count": 0})
    return out


def _mv_lane(rule: str, label: str, threshold: str, slots: list[dict], *,
             gate: bool = False) -> dict:
    """One lane, built the way the backend builds it: cells follow the slots.

    `values_published` is 0 on every lane, which is what every stored session measured —
    the detectors return a verdict and not the number behind it.
    """
    cells, passed, failed = [], 0, 0
    for s in slots:
        if s["status"] == "future":
            state = "future"
        elif s["status"] == "missed":
            state = "no_record"
        elif gate:
            state, passed = "pass", passed + 1
        else:
            state = "not_published"
        cells.append({"slot_id": s["slot_id"], "time_et": s["time_et"],
                      "state": state, "value": None})
    decided = passed + failed
    return {"rule": rule, "label": label, "threshold_display": threshold,
            "comparator": "", "detail": "", "cells": cells,
            "values_published": 0, "slots_decided": decided,
            "passed": passed, "failed": failed,
            "state_display": (f"{passed}/{decided} pass" if decided
                              else "value not published by the detector")}


def _market_view(*, decided: int = 22, n: int = 22, signal_at=None, missed_at=None,
                 status: str = "complete") -> dict:
    slots = _mv_slots(n, decided, signal_at=signal_at, missed_at=missed_at)
    bars = [{"time": f"2026-08-27 {(i // 12):02d}:{(i % 12) * 5:02d}",
             "open": 66800.0 + i, "high": 66820.0 + i, "low": 66780.0 + i,
             "close": 66810.0 + i, "volume": 100 + i} for i in range(24)]
    sleeve = {
        "label": "NKD", "instrument": "MNKD", "bar_interval": "5m", "clock": "Asia/Tokyo",
        "range": {"context_start_et": "00:00", "window_start_et": "01:10",
                  "window_end_et": "02:55", "context_end_et": "03:05"},
        "status": status,
        "summary": "Complete · 22/22 slots observed · no signal",
        "coverage": {"sleeve": "global_nkd", "outcome": status,
                     "expected_slots": n, "observed_slots": decided},
        "bars": bars, "bars_session_date": "2026-08-27", "bars_note": "",
        "volume_status": "present", "slots": slots, "levels": [],
        "rule_lanes": [
            _mv_lane("gate_allow", "gate allow", "no refusal codes", slots, gate=True),
            _mv_lane("ema10_filter", "ema10 filter", "ema period 10", slots),
            _mv_lane("regime_lag_1", "regime lag 1", "lag 1", slots),
        ],
        "levels_note": "Strategy levels unavailable",
        "strategy": {"rules": [], "detail": "", "status": "not_computed_until_entry"},
        "setup_boundary": {
            "schema": "track1_setup_boundary/1", "sleeve": "global_nkd",
            "boundary_type": "entry_after_setup_only",
            "boundary_proof": "the entry comes from a per-bar signal function",
            "status": "not_applicable", "price_levels": [], "metrics": [],
            "levels_armed": False, "nearest_failed_condition": None,
            "summary": "This sleeve publishes an entry only after a setup bar forms."},
        "levels_detail": "The strategy has not published entry/reference levels yet.",
        "data_status": {"provider": "ibkr", "ok": True,
                        "latest_bar_et": "2026-08-28 15:54:00+09:00",
                        "live_rows_fetched": 1910, "splice_result": "ok",
                        "provider_reason": None},
    }
    return {"schema": "track1_market_view/1", "route": "track1_candidate",
            "session_date": "2026-08-28", "now_et": "10:42",
            "levels_note": "Strategy levels unavailable",
            "sleeves": {"global_nkd": sleeve}}


def _regime(label: str = "Calm", run: int = 21, total: int = 60) -> dict:
    ctx = ([{"date": f"2026-06-{i % 28 + 1:02d}", "label": "Normal"}
            for i in range(total - run)] +
           [{"date": f"2026-08-{i % 28 + 1:02d}", "label": label} for i in range(run)])
    return {"status": "PASS", "code": "labelled", "detail": "", "label": label,
            "label_date": "2026-08-27", "checked_at": "2026-08-28T07:34:37Z",
            "age_hours": 7.14, "recent": ctx[-5:], "context": ctx,
            "inputs": {}, "score": 0.998354,
            "score_name": "posterior probability of the labelled state",
            "shift_threshold": None, "margin": 0.996711,
            "margin_name": "probability margin over the next most likely state",
            "runner_up": "Normal",
            "state_probabilities": {"Calm": 0.998354, "Normal": 0.001643, "Stress": 3e-06},
            "posterior_agrees_with_label": True,
            "entropy_bits": 0.017627, "max_entropy_bits": 1.584963,
            "features": [
                {"name": "log_return", "label": "SPY 1-day log return",
                 "display_value": "+0.65%", "percentile_60d": 76.7,
                 "z_score_60d": 0.72, "leans": "mixed"},
                {"name": "realised_vol", "label": "Realised volatility, 5-day annualised",
                 "display_value": "5.8% annualised", "percentile_60d": 0.0,
                 "z_score_60d": -1.391, "leans": "Calm"}],
            "score_note": "", "threshold_note": "not published",
            "line": "Regime Calm as of 2026-08-27",
            "verification": {"status": "PASS", "counts": {"compared": 1761, "changed": 0}}}


def _stub_mv(page, market_view: dict, regime: dict | None = None) -> None:
    stub_api(page, {"/api/v1/track1-market-view": {
        "market_view": market_view, "regime": regime or _regime()}})


def test_every_rule_lane_draws_one_cell_per_declared_slot(realtime_server, browser_page):
    """A lane with fewer cells than slots silently shifts every cell after the gap, so a
    verdict would be read against the wrong minute. Asserted per lane, and the lane list is
    asserted non-empty first: a page that rendered no lanes at all would otherwise pass a
    loop over nothing."""
    _stub_mv(browser_page, _market_view())
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewLanes .mv2-lane")
    counts = browser_page.eval_on_selector_all(
        "#marketViewLanes .mv2-lanes .mv2-lane",
        "els => els.map(e => e.querySelectorAll('.mv2-cell').length)")
    assert counts, "the panel drew no rule lanes at all"
    assert counts == [22] * 3, counts


def test_a_lane_never_shows_a_value_the_detector_did_not_publish(realtime_server, browser_page):
    """The panel's whole claim. Measured on every stored session, every strategy rule
    carries a null value, so a lane that printed a number would be printing an invented
    one — and on this page an invented number reads as the strategy's own."""
    _stub_mv(browser_page, _market_view())
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewLanes .mv2-lane")
    rows = browser_page.eval_on_selector_all(
        "#marketViewLanes .mv2-lanes .mv2-lane .mv2-lane-value",
        "els => els.map(e => [e.textContent.trim(), e.getAttribute('title') || ''])")
    assert rows, "no lane value column rendered"
    # The gate lane DID publish verdicts and says so; the detector lanes did not. The column
    # carries the short form and the full reason stays on hover, so BOTH are asserted — a
    # column shortened to the point of saying nothing would otherwise pass.
    assert "22/22 pass" in [text for text, _ in rows]
    unpublished = [(text, title) for text, title in rows if "pass" not in text]
    assert unpublished, "no lane exercised the unpublished path"
    assert all(text == "no verdict" for text, _ in unpublished), unpublished
    assert all(title == "value not published by the detector"
               for _, title in unpublished), unpublished


def test_a_slot_that_left_no_record_does_not_draw_as_a_decided_slot(realtime_server, browser_page):
    """`missed` and `no_signal` are different facts: one is a slot that ran and found
    nothing, the other is a slot nobody watched. Drawing them alike is how absence comes to
    read as a quiet result."""
    _stub_mv(browser_page, _market_view(missed_at=9))
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewLanes .mv2-lane")
    classes = browser_page.eval_on_selector_all(
        "#marketViewLanes .mv2-lanes .mv2-lane:nth-child(2) .mv2-cell",
        "els => els.map(e => e.className)")
    assert sum("norec" in c for c in classes) == 1, classes
    assert sum("muted" in c for c in classes) == 21, classes


def test_held_days_says_at_least_when_the_run_fills_the_whole_strip(realtime_server, browser_page):
    """The context strip is 60 days. A run that reaches its start began earlier than the
    payload can see, so the exact figure is not knowable here and must not be printed as
    one."""
    _stub_mv(browser_page, _market_view(), _regime(run=60, total=60))
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#regimeFacts .rg2-held")
    text = browser_page.eval_on_selector("#regimeFacts .rg2-held", "el => el.textContent")
    assert "at least 60 days" in text, text


def test_held_days_is_exact_when_the_run_starts_inside_the_strip(realtime_server, browser_page):
    """The other half of the pair above. Without this, a bug that always said 'at least'
    would pass the test that matters."""
    _stub_mv(browser_page, _market_view(), _regime(run=21, total=60))
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#regimeFacts .rg2-held")
    text = browser_page.eval_on_selector("#regimeFacts .rg2-held", "el => el.textContent")
    assert text.strip() == "held 21 days", text


def test_the_regime_legend_names_only_states_this_model_can_produce(realtime_server, browser_page):
    """The fitted model has three states. A legend key for a fourth would show a label the
    decode can never return, and somebody would go looking for why it never appears."""
    _stub_mv(browser_page, _market_view())
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#regimeStrip .regime-legend")
    names = browser_page.eval_on_selector_all(
        "#regimeStrip .regime-legend-item", "els => els.map(e => e.textContent.trim())")
    assert names == ["Calm", "Normal", "Stress"], names


def test_switching_to_price_context_swaps_the_card_and_keeps_the_verdict(realtime_server,
                                                                        browser_page):
    """The tab changes which card is built; it must not change the answer above them."""
    _stub_mv(browser_page, _market_view())
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewLanes .mv2-lane")
    before = browser_page.eval_on_selector("#marketViewVerdict", "el => el.innerText")
    browser_page.click('[data-mv-inner="Price context"]')
    browser_page.wait_for_selector("#marketViewChart .mv2-card")
    assert browser_page.eval_on_selector("#marketViewLanes", "el => el.innerHTML") == ""
    after = browser_page.eval_on_selector("#marketViewVerdict", "el => el.innerText")
    assert after == before, (before, after)


def test_a_sleeve_with_no_rule_evidence_says_so_instead_of_drawing_an_empty_grid(
        realtime_server, browser_page):
    """Waiting is the normal morning state for two of the three sleeves. An empty lane grid
    there reads as a panel that failed to load."""
    mv = _market_view(decided=0, status="waiting")
    mv["sleeves"]["global_nkd"]["rule_lanes"] = []
    _stub_mv(browser_page, mv)
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewLanes .mv-empty")
    # Lower-cased before matching: the empty-state heading is upper-cased by CSS, so
    # `innerText` returns it upper-cased and a literal match here would pin the styling
    # rather than the sentence.
    text = browser_page.eval_on_selector("#marketViewLanes", "el => el.innerText")
    assert "no rule evidence for this session" in text.lower(), text
    assert "01:10 ET" in text, text


@pytest.mark.parametrize("width,height", [(1440, 900), (1024, 900), (390, 844)])
def test_the_populated_market_view_does_not_overflow_or_clip(realtime_server, browser_page,
                                                             width, height):
    """The two overflow tests above run against `sleeves: {}`, so the panel they measure is
    an empty box — the lane grid, the 24-cell strip and the four regime metric cells never
    exist in them. A three-column grid with two fixed columns is exactly the shape that
    survives at 1440 and breaks at 390, so it is measured with the panel populated."""
    browser_page.set_viewport_size({"width": width, "height": height})
    _stub_mv(browser_page, _market_view())
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewLanes .mv2-lane")
    overflow = browser_page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert overflow is False, f"page overflows horizontally at {width}x{height}"
    # Scoped to the two sections this test is about. Measured on 2026-08-28, the page
    # HEADER already clips at 1024 (`module-nav`, `header-live-context`) with the market
    # view empty, so an unscoped assertion here would fail on a defect that predates this
    # panel and belongs to every dashboard that shares the header.
    clipped = [c for c in browser_page.evaluate(_CLIPPED_CONTENT)
               if not c.startswith(("NAV.", "DIV.header-", "SPAN.runner-header", "B.warning"))]
    assert clipped == [], f"panel content clipped off-screen at {width}x{height}: {clipped}"


def test_a_rejected_slot_is_not_reported_as_no_signal(realtime_server, browser_page):
    """The verdict word and the reason printed beside it must be the same fact.

    Before this, the status word knew about signals and about a refused SLEEVE but not about
    a rejected SLOT, so a session where the gate refused a candidate read `NO SIGNAL · gate
    refused at 02:25 ET` — a pill contradicting itself in six words, and pointing an
    operator at the setup when the refusal came from the order gate."""
    mv = _market_view()
    slots = mv["sleeves"]["global_nkd"]["slots"]
    slots[15] = dict(slots[15], status="rejected", reason="admission_cap")
    _stub_mv(browser_page, mv)
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewVerdict .mv2-pill")
    text = browser_page.eval_on_selector("#marketViewVerdict", "el => el.innerText")
    assert "REJECTED" in text, text
    assert "NO SIGNAL" not in text, text
    assert "gate refused at 02:25 ET" in text, text


def test_no_live_bars_points_at_the_last_slot_that_saw_data(realtime_server, browser_page):
    """A refused slot leaves a row but no observation. Reading the last ROW as the last bar
    named a minute when there were already no bars — the number was real and measured the
    wrong thing."""
    mv = _market_view(decided=10)
    sleeve = mv["sleeves"]["global_nkd"]
    sleeve["slots"] = [dict(s, status="refused", reason="no_bar_provider")
                       if i >= 10 else s for i, s in enumerate(sleeve["slots"])]
    sleeve["data_status"] = {"provider": "ibkr", "ok": False, "latest_bar_et": None,
                             "live_rows_fetched": 0, "splice_result": "unknown",
                             "provider_reason": "the provider returned no rows"}
    _stub_mv(browser_page, mv)
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewVerdict .mv2-pill")
    text = browser_page.eval_on_selector("#marketViewVerdict", "el => el.innerText")
    # slot 9 is the last that decided; slot 21 is the last that left a row.
    assert "no live bars since 01:55 ET" in text, text


def _with_slot_series(mv: dict, *, series_day: str) -> dict:
    """`_market_view()` plus a per-slot series, which the price-context pane needs.

    The builder does not carry one: every sleeve it makes is refused before a rule reads a
    number, which is the common case and also the case where this pane draws nothing.
    """
    s = mv["sleeves"]["global_nkd"]
    # Nến phải phủ HẾT các slot, nếu không chart giá chỉ vẽ mark cho phần slot nằm trong
    # khoảng bar và span bị từ chối vì lệch SỐ ĐẾM — phép kiểm khi đó xanh/đỏ vì một lý do
    # không liên quan gì tới ngày. Đo được ở bản đầu: 10 mark cho 22 slot.
    s["bars"] = [{"time": f"{s['bars_session_date']} {row['time_et']}",
                  "open": 66800.0 + i, "high": 66820.0 + i, "low": 66780.0 + i,
                  "close": 66810.0 + i, "volume": 100 + i}
                 for i, row in enumerate(s["slots"])]
    s["strategy"] = dict(s["strategy"])
    s["strategy"]["slot_series"] = [
        # `slot_time`, đúng tên payload thật dùng (_slot_series ở backend). Bản đầu đặt
        # `time_et` và vẫn xanh, vì luật cũ chỉ ĐẾM slot — một fixture sai tên vẫn qua được
        # một phép kiểm không đọc tên.
        {"slot_time": row["time_et"], "close": 66800.0 + i, "ema": 66795.0 + i,
         "volume": 100 + i, "avg_volume": 95 + i}
        for i, row in enumerate(s["slots"])]
    s["strategy"]["slot_series_session"] = series_day
    return mv


def _xspan(page) -> str:
    return page.eval_on_selector(".mv2-sc-svg", "el => el.getAttribute('data-xspan')")


def _axis_state(page) -> dict:
    """Everything the sharing decision reads, so a failure names the reason itself."""
    return page.evaluate("""() => ({
        xspan: (document.querySelector('.mv2-sc-svg')||{}).dataset?.xspan ?? null,
        xaxis: document.querySelector('.market-view-section')?.getAttribute('data-xaxis'),
        marks: document.querySelectorAll('.mv-mark').length,
        seriesPts: document.querySelectorAll('.mv2-sc-dot, .mv2-sc-svg circle').length,
        priceSvg: !!document.querySelector('.mv-svg'),
      })""")


def _open_price_context(page, server, mv):
    _stub_mv(page, mv)
    open_realtime(page, server)
    page.click('[data-mv-inner="Price context"]')
    page.wait_for_selector(".mv2-sc-svg", timeout=20_000)
    page.wait_for_timeout(500)


def test_the_two_chart_panes_share_one_axis_when_they_are_the_same_session(
        realtime_server, browser_page):
    """The guard for the test below: without it, a rule that never shares would pass it.

    Same session, same slot count -> the series adopts the candle chart's slot span so a
    reader can follow one minute down from a candle to the close line.
    """
    # `_market_view()` builds its bars for 2026-08-27; name the series the same day.
    _open_price_context(browser_page, realtime_server,
                        _with_slot_series(_market_view(), series_day="2026-08-27"))
    assert _xspan(browser_page) == "shared", _axis_state(browser_page)


def test_the_panes_refuse_one_axis_when_the_candles_are_a_different_session(
        realtime_server, browser_page):
    """Đo được 2026-09-02: nến 09-01 nằm dưới các slot của 09-02, chung một trục.

    Kho bar được append mỗi ngày một lần, nên trong lúc một phiên đang chạy, bar mới nhất
    của kho là của hôm trước. Số slot vẫn khớp — 22 dù ngày nào — nên phép kiểm cũ, vốn chỉ
    đếm slot, đã nhận span và dóng slot hôm nay lên nến hôm qua, một trục, một crosshair
    đồng bộ. Câu ghi chú ngay dưới head lại viết "the crosshair matches within each pane,
    not across them": đúng về ý định, sai về thứ đang hiện ra.

    Luật 8 của hợp đồng thị giác: không hover chung khi hai chart không chung trục.
    """
    _open_price_context(browser_page, realtime_server,
                        _with_slot_series(_market_view(), series_day="2026-08-28"))
    assert _xspan(browser_page) == "own"
    assert browser_page.eval_on_selector(
        ".market-view-section", "el => el.getAttribute('data-xaxis')") == "own"
    # Và người đọc phải THẤY điều đó, không phải suy ra từ một thuộc tính.
    label = browser_page.eval_on_selector(
        ".mv2-slotchart .mv2-sc-head",
        "el => getComputedStyle(el, '::after').content")
    # Giao diện này là tiếng Anh; bản đầu tôi viết nhãn bằng tiếng Việt vào một trang
    # tiếng Anh, và phép kiểm đi theo cái sai đó.
    assert "own axis" in label, label


def test_a_thin_instruments_volume_is_not_flattened_by_its_own_busiest_minute(
        realtime_server, browser_page):
    """Đo được 2026-09-03 trên MNKD: 36 nến, đỉnh 110, trung vị 9 — gấp 12 lần.

    Chia thang theo cột cao nhất thì 19 trên 35 cột có giao dịch cao dưới 4px trong một pane
    44px, tức vô hình. Pane đọc thành MỘT cột và một vạch phẳng, mà vạch phẳng đó là một phiên
    có giao dịch ở 35 trên 36 phút của nó.
    """
    mv = _market_view()
    s = mv["sleeves"]["global_nkd"]
    spiky = [26, 18, 33, 9, 9, 24, 14, 31, 13, 24, 4, 12,
             27, 5, 22, 7, 110, 9, 6, 13, 1, 3, 7, 15]
    s["bars"] = [{**b, "volume": spiky[i % len(spiky)]} for i, b in enumerate(s["bars"])]
    _stub_mv(browser_page, mv)
    open_realtime(browser_page, realtime_server)
    browser_page.click('[data-mv-inner="Price context"]')
    browser_page.wait_for_selector(".mv-vol", timeout=20_000)
    browser_page.wait_for_timeout(400)

    hs = browser_page.eval_on_selector_all(
        ".mv-vol", "els => els.map(e => Number(e.getAttribute('height')))")
    assert len(hs) >= 20, f"không đủ cột để đo: {len(hs)}"
    traded = [h for h in hs if h > 0]
    assert len(traded) == len(hs), "có cột giao dịch bị vẽ thành 0"

    # Cột trung vị phải NHÌN THẤY được. Chia theo đỉnh thì nó ra 2,9px.
    med = sorted(traded)[len(traded) // 2]
    assert med >= 6, f"cột trung vị chỉ {med}px — vẫn bị đỉnh nuốt"
    # Điều quan trọng hơn cả chiều cao: HAI GIÁ TRỊ KHÁC NHAU KHÔNG ĐƯỢC VẼ BẰNG NHAU.
    # Bản trước cắt trần ở phân vị 90, và 110, 37, 33 cùng ra một chiều cao — ba phiên
    # giao dịch khác nhau thành một hình. Đó là lý do pane được nâng lên thay vì cắt.
    pairs = browser_page.evaluate("""() => [...document.querySelectorAll('.mv-vol')]
        .map(e => [ (e.querySelector('title')||{}).textContent || '',
                    +e.getAttribute('height') ])""")
    byval = {}
    for title, h in pairs:
        byval.setdefault(title, set()).add(round(h, 1))
    gop = {}
    for title, h in pairs:
        gop.setdefault(round(h, 1), set()).add(title)
    dinh = {h: v for h, v in gop.items() if len(v) > 1 and h > 2.01}
    assert not dinh, f"nhiều giá trị volume khác nhau vẽ cùng chiều cao: {dinh}"

    # Trục phải nói cả trần lẫn đỉnh thật, nếu không nhãn đang nói dối về thang.
    ax = browser_page.eval_on_selector_all(".mv-vol-ax", "els => els.map(e => e.textContent)")
    assert any("110" in a for a in ax), f"trục không in đỉnh thật: {ax}"


def test_a_minute_that_did_not_trade_is_not_drawn_as_one_that_did(
        realtime_server, browser_page):
    """Sàn 1,5px chỉ dành cho cột CÓ giao dịch. Zero phải giữ chiều cao 0 — phân biệt đó là
    lý do pane volume tồn tại."""
    mv = _market_view()
    s = mv["sleeves"]["global_nkd"]
    s["bars"] = [{**b, "volume": (0 if i % 3 == 0 else 20)} for i, b in enumerate(s["bars"])]
    _stub_mv(browser_page, mv)
    open_realtime(browser_page, realtime_server)
    browser_page.click('[data-mv-inner="Price context"]')
    browser_page.wait_for_selector(".mv-svg", timeout=20_000)
    browser_page.wait_for_timeout(600)
    state = browser_page.evaluate("""() => ({
        vol: document.querySelectorAll('.mv-vol').length,
        candles: document.querySelectorAll('.mv-candle, .mv-svg rect').length,
        volLabel: !!document.querySelector('.mv-vol-label'),
      })""")
    assert state["vol"], f"không vẽ cột volume nào: {state}"
    hs = browser_page.eval_on_selector_all(
        ".mv-vol", "els => els.map(e => Number(e.getAttribute('height')))")
    zeros = [h for i, h in enumerate(hs) if i % 3 == 0]
    rest = [h for i, h in enumerate(hs) if i % 3 != 0]
    assert zeros and rest, (len(zeros), len(rest))
    assert all(h == 0 for h in zeros), zeros
    assert all(h > 0 for h in rest), rest


def test_hovering_a_slot_reads_out_the_candle_beside_it(realtime_server, browser_page):
    """Số của cây nến phải nằm TRONG ô đọc, không phải trong một dải riêng dưới chart.

    realtime.js vốn đọc chúng ra `.mv-tip`, nhưng dải đó rộng nguyên khung và nằm DƯỚI plot —
    đo được top 742 trong khi plot kết thúc ở 705, tức người đang rê chuột trên cây nến được
    báo giá ở cách đó một chiều cao chart. Muc 4.7 gộp cả hai vào một ô phía trên.
    """
    _open_price_context(browser_page, realtime_server,
                        _with_slot_series(_market_view(), series_day="2026-08-27"))
    browser_page.wait_for_selector(".mv-mark", timeout=20_000)
    browser_page.hover(".mv-mark >> nth=5")
    browser_page.wait_for_timeout(400)

    txt = browser_page.eval_on_selector(".mv2-chart-readout", "el => el.textContent")
    assert "slot" in txt, txt
    for k in ("O ", "H ", "L ", "C "):
        assert k in txt, f"thiếu {k!r} trong ô đọc: {txt}"
    assert "vol" in txt, txt
    # Dải cũ phải im lặng, nếu không cùng một sự thật hiện ở hai chỗ hai kiểu.
    assert browser_page.eval_on_selector(
        ".mv-tip", "el => getComputedStyle(el).display") == "none"


def test_the_hover_rule_stands_on_the_candle_it_is_reading(realtime_server, browser_page):
    """Đo được 2026-09-03: đường nét đứt đứng ở x=592,6 trong khi tâm nến chạy 341,9 · 367,5
    … bước 25,66 — giữa hai cây nến, và O/H/L/C in cạnh nó thuộc về cây thứ ba.

    Nguyên nhân: hover tính vị trí bằng lề 8/62 còn plot vẽ bằng 34/68. Hai bản sao của một
    quyết định, và bản sao thứ hai là thứ đã trôi.
    """
    _open_price_context(browser_page, realtime_server,
                        _with_slot_series(_market_view(), series_day="2026-08-27"))
    browser_page.wait_for_selector(".mv-mark", timeout=20_000)
    browser_page.hover(".mv-mark >> nth=7")
    browser_page.wait_for_timeout(400)

    got = browser_page.evaluate("""() => {
        const lines = [...document.querySelectorAll('.mv2-xhair')]
          .filter(l => getComputedStyle(l).display !== 'none');
        const marks = [...document.querySelectorAll('.mv-mark')].map(m => +m.getAttribute('cx'));
        const x = lines.length ? parseFloat(lines[0].getAttribute('x1')) : null;
        const near = x === null ? null
          : marks.reduce((a, b) => Math.abs(b - x) < Math.abs(a - x) ? b : a);
        return { lines: lines.length, off: x === null ? null : Math.abs(near - x),
                 legacy: getComputedStyle(document.querySelector('.mv-cross')).display };
      }""")
    assert got["lines"] >= 1, got
    assert got["off"] is not None and got["off"] < 0.6, got
    # Một đường mỗi pane là muc 4.7; đường cũ chỉ phủ pane giá nên nó là bản thừa.
    assert got["legacy"] == "none", got


def test_the_plot_box_is_as_tall_as_the_chart_drawn_into_it(realtime_server, browser_page):
    """Hai con số ở hai ngôn ngữ: H của viewBox nằm trong realtime.js, chiều cao khung nằm
    trong CSS. Khi tôi nâng chart, tôi nâng mỗi svg — khung vẫn 320px và `overflow:hidden`,
    nên svg thò ra 101px và ĐÚNG 101px cuối là pane volume: cả 36 cột bị cắt đáy. Trên màn
    hình nó đọc thành "volume chỉ có một cột", trong khi thang đã đúng từ trước.

    Ghim bằng tỉ lệ dọc: vẽ đúng cỡ thì sy = 1. Lệch một con số là test đỏ.
    """
    _open_price_context(browser_page, realtime_server,
                        _with_slot_series(_market_view(), series_day="2026-08-27"))
    got = browser_page.evaluate("""() => {
        const svg = document.querySelector('#marketViewChart .mv-svg');
        if (!svg) return null;
        const vb = (svg.getAttribute('viewBox') || '').trim().split(/\s+/).map(Number);
        const box = svg.getBoundingClientRect();
        const plot = svg.closest('.mv2-plot');
        const p = plot && plot.getBoundingClientRect();
        const hits = [];
        for (const sh of document.styleSheets) { let rs;
          try { rs = sh.cssRules; } catch (e) { continue; }
          for (const r of rs) { if (!r.selectorText) continue;
            let m = false; try { m = plot && plot.matches(r.selectorText); } catch (e) {}
            if (m && r.style.getPropertyValue('height'))
              hits.push((sh.href || 'inline').split('/').pop() + ' :: ' + r.selectorText
                        + ' = ' + r.style.getPropertyValue('height')); } }
        return { vbH: vb[3], svgH: box.height, plotH: p ? p.height : null,
                 spill: p ? box.bottom - p.bottom : 0,
                 sheets: [...document.styleSheets].map(s => (s.href || 'inline').split('/').pop()),
                 heightRules: hits };
      }""")
    assert got, "không dựng được chart"
    assert got["vbH"] > 0
    sy = got["svgH"] / got["vbH"]
    assert abs(sy - 1) < 0.02, (
        f"svg vẽ ở tỉ lệ dọc {sy:.3f}: viewBox {got['vbH']} nhưng cao {got['svgH']} — {got}")
    assert got["spill"] <= 0.6, (
        f"svg thò ra khỏi khung {got['spill']:.0f}px — phần thò ra là đáy pane volume: {got}")


def test_a_series_of_slots_that_recorded_nothing_says_so_instead_of_drawing_nothing(
        realtime_server, browser_page):
    """Đo được 2026-09-03 trên rổ Stress: 18 slot, MỌI số đọc là null, và cả 18 lọt qua bộ
    lọc "có giá". `Number(null)` là 0 và `Number.isFinite(0)` là true — đúng cái bẫy mà file
    này đã tự cảnh báo ở một chỗ khác, mà bộ lọc ở đây lại viết không có nó.

    Hậu quả không phải một dòng sai mà là một CÁI CHART CỦA HƯ KHÔNG: không đường, không
    chấm, và trục giá chạy từ -Infinity tới Infinity. Câu cần hiện là "bao nhiêu slot đã ghi,
    bao nhiêu mang số" — người đọc mới biết là chưa tới lượt chứ không phải hỏng.
    """
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    for p in mv["sleeves"]["global_nkd"]["strategy"]["slot_series"]:
        for k in ("close", "ema", "volume", "avg_volume"):
            p[k] = None
    # KHÔNG dùng _open_price_context: nó chờ `.mv2-sc-svg`, mà đúng cái svg đó là thứ
    # phép kiểm này đòi KHÔNG được vẽ. Chờ nó thì test treo 20 giây rồi đỏ dù đúng hay sai.
    _stub_mv(browser_page, mv)
    open_realtime(browser_page, realtime_server)
    browser_page.click('[data-mv-inner="Price context"]')
    browser_page.wait_for_selector("#marketViewChart .mv2-card", timeout=20_000)
    browser_page.wait_for_timeout(600)

    assert browser_page.eval_on_selector_all(".mv2-sc-svg", "e => e.length") == 0, (
        "vẽ chart trong khi không slot nào mang số")
    msg = browser_page.eval_on_selector(".mv2-slotchart-empty", "el => el.textContent")
    # Phải NÓI RA có bao nhiêu slot đã ghi — con số đó là thứ phân biệt "chưa tới lượt" với
    # "hỏng". Ghim con số, không ghim câu chữ.
    ran = len(mv["sleeves"]["global_nkd"]["strategy"]["slot_series"])
    assert str(ran) in msg, f"không nói bao nhiêu slot đã ghi: {msg}"
    # Và KHÔNG được đổ lỗi cho cửa sổ. Đo được trên rổ Stress lúc 11:53 ET, một tiếng sau
    # khi cửa sổ mở lúc 10:35 với 16/24 slot đã chạy: câu cũ vẫn bảo người đọc chờ cửa sổ mở.
    assert "entry window opens" not in msg, (
        f"đổ lỗi cho cửa sổ trong khi slot đã chạy: {msg}")
    # Và không được in Infinity ra bất cứ đâu.
    body = browser_page.eval_on_selector("#marketViewChart", "el => el.textContent")
    assert "∞" not in body and "Infinity" not in body, body[:200]


def _series_x_positions(page) -> list[float]:
    """Toạ độ x của mọi chấm giá đóng cửa trên pane chuỗi, theo thứ tự vẽ."""
    return page.eval_on_selector_all(
        ".mv2-sc-svg .mv2-sc-dot-close",
        "els => els.map(e => Number(e.getAttribute('cx')))")


def _price_slot_positions(page) -> list[float]:
    """Toạ độ x của mọi mark slot trên biểu đồ nến."""
    return page.eval_on_selector_all(
        ".mv-svg .mv-mark", "els => els.map(e => Number(e.getAttribute('cx')))")


def test_one_unplaceable_slot_drops_that_slot_and_not_the_shared_axis(
        realtime_server, browser_page):
    """Thiếu một phút thì bỏ đúng slot đó, không bỏ cả trục.

    Luật cũ là `every`: chỉ cần MỘT slot mang phút mà biểu đồ nến không vẽ là cả pane
    quay về trải đều các điểm ra hết chiều ngang. Hậu quả rơi vào những slot KHÔNG hỏng —
    chúng bị đẩy khỏi cây nến ngay trên đầu chúng, đúng vào lúc người đọc cần đối chiếu
    hai pane nhất.

    Phép kiểm dựng đúng ca đó: một điểm mang phút không có trong biểu đồ nến. Mọi điểm
    còn lại phải nằm nguyên trên toạ độ mà biểu đồ nến đã đặt cho phút của nó.
    """
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    series = mv["sleeves"]["global_nkd"]["strategy"]["slot_series"]
    # Chốt chặn: phải có đủ điểm để bỏ một cái mà vẫn còn một trục.
    assert len(series) >= 4, f"chuỗi quá ngắn để phép kiểm này có nghĩa: {len(series)}"
    alien = series[2]["slot_time"]
    series[2] = dict(series[2], slot_time="03:07")  # phút không slot nào có

    _open_price_context(browser_page, realtime_server, mv)
    assert _xspan(browser_page) == "shared", (
        f"một phút thiếu vẫn làm mất cả trục chung: {_axis_state(browser_page)}")

    drawn = _series_x_positions(browser_page)
    marks = _price_slot_positions(browser_page)
    assert len(marks) >= len(series) - 1, f"biểu đồ nến chỉ vẽ {len(marks)} mark"
    assert len(drawn) == len(series) - 1, (
        f"phải bỏ đúng MỘT điểm: vẽ {len(drawn)} trên {len(series)} slot")
    # Mọi điểm còn lại phải trùng toạ độ của mark cùng phút trên biểu đồ nến.
    for cx in drawn:
        assert any(abs(cx - m) < 0.6 for m in marks), (
            f"điểm ở x={cx} không nằm trên mark nào của biểu đồ nến: {marks[:6]}…")
    # Và người đọc phải ĐỌC ĐƯỢC là có slot bị bỏ, chứ không phải tự suy ra.
    note = browser_page.eval_on_selector(
        ".mv2-slotchart", "el => el.innerText")
    assert "not drawn here" in note and "03:07" in note, (
        f"không nói ra slot nào bị bỏ; nhãn gốc là {alien!r}. Đọc được: {note[:180]!r}")


def test_a_sleeve_with_no_candles_does_not_inherit_the_previous_sleeve_axis(
        realtime_server, browser_page):
    """Bản đồ toạ độ slot phải chết cùng chart đã dựng ra nó.

    Hàm vẽ nến chỉ GHI bản đồ khi thành công, và thoát sớm khi sleeve không có bar — nên
    bản đồ của sleeve vẽ trước vẫn sống. Sleeve thứ hai không có nến nào để dóng vào lại
    tuyên bố `data-xspan="shared"` và đặt slot của mã NÀY lên các phút của nến mã KHÁC.
    Không có gì trên màn hình nói ra điều đó: trục trông vẫn bình thường.

    Bản đồ giờ bị xoá khi VÀO hàm và mang dấu mã + phiên nó được dựng từ đó.
    """
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    first = mv["sleeves"]["global_nkd"]
    # Sleeve thứ hai: cùng các phút slot, cùng chuỗi — nhưng KHÔNG có bar nào.
    second = json.loads(json.dumps(first))
    second.update({"label": "R4S", "instrument": "MES", "bars": [],
                   "summary": "No bars recorded yet for this session"})
    mv["sleeves"]["roska4_stress"] = second

    _open_price_context(browser_page, realtime_server, mv)
    # Chốt chặn: sleeve ĐẦU phải đang chung trục, nếu không phép kiểm dưới đây đạt rỗng
    # — một trang không bao giờ chung trục cũng sẽ qua.
    assert _xspan(browser_page) == "shared", (
        f"sleeve đầu chưa chung trục nên chưa có gì để kế thừa: {_axis_state(browser_page)}")

    browser_page.click('[data-mv-tab="roska4_stress"]')
    browser_page.wait_for_timeout(600)
    assert browser_page.query_selector(".mv-svg .mv-mark") is None, (
        "sleeve thứ hai vẫn vẽ mark, nên nó có nến — dựng sai ca cần kiểm")
    assert _xspan(browser_page) == "own", (
        "sleeve không có nến vẫn nhận trục của sleeve trước: "
        f"{_axis_state(browser_page)}")


def _posterior_rows(page) -> list[dict]:
    return page.eval_on_selector_all(
        "#regimePosterior .regime-post-row",
        """els => els.map(e => ({
             name: (e.querySelector('span') || {}).textContent?.trim() || '',
             value: (e.querySelector('b') || {}).textContent?.trim() || '',
             absent: e.classList.contains('regime-post-absent'),
             hasBar: !!e.querySelector('.regime-post-track')}))""")


def test_a_regime_the_model_does_not_fit_is_shown_without_a_probability(
        realtime_server, browser_page):
    """Crisis phải hiện, nhưng không được mang một con số mô hình chưa từng tính.

    Hệ thống nói về bốn chế độ — Calm / Normal / Stress / Crisis — còn mô hình chạy trên
    tuyến này fit BA: `inputs.n_states` là 3 và posterior chỉ có ba khoá. Bỏ hẳn dòng
    Crisis thì người đọc không biết cái thứ tư đi đâu; in "0.00%" thì lại khai rằng mô
    hình đã tính ra một xác suất và nó bằng không. Hai câu đó dẫn tới hai quyết định vận
    hành khác nhau.

    Dòng phải có mặt, phải tự nhận là không thuộc mô hình, và phải KHÔNG mang phần trăm.
    """
    stub_api(browser_page, {"/api/v1/track1-market-view": {
        "market_view": {"session_date": "2026-08-27", "sleeves": {}},
        "regime": _regime()}})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#regimePosterior .regime-post-row", timeout=20_000)

    rows = _posterior_rows(browser_page)
    # Chốt chặn: fixture phải đúng là mô hình BA trạng thái, nếu không phép kiểm này
    # đang đo một thế giới khác.
    priced = [r for r in rows if not r["absent"]]
    assert len(priced) == 3, f"fixture không còn là mô hình ba trạng thái: {rows}"

    crisis = [r for r in rows if r["name"].startswith("Crisis")]
    assert len(crisis) == 1, f"không có dòng Crisis: {[r['name'] for r in rows]}"
    assert crisis[0]["absent"], "dòng Crisis đang trông như một dòng có số"
    assert "%" not in crisis[0]["value"], (
        f"dòng Crisis in một xác suất mô hình chưa từng tính: {crisis[0]['value']!r}")
    assert not crisis[0]["hasBar"], "dòng Crisis vẫn vẽ thanh bar"
    # Và ba dòng kia vẫn phải giữ nguyên phần trăm của chúng.
    assert all("%" in r["value"] for r in priced), (
        f"một trạng thái có fit lại mất phần trăm: {priced}")


def _time_labels(page) -> list[dict]:
    """Nhãn thời gian của pane chuỗi, nay là span HTML chứ không còn `<text>` trong SVG.

    Luật 5 của hợp đồng cấm vẽ chữ bên trong một SVG `preserveAspectRatio="none"`, nên
    nhãn ra lớp phủ HTML và mang toạ độ dưới dạng `left: N%` của viewBox. `cx` quy ngược
    về đơn vị viewBox (W = 1000) để so được với toạ độ mark của biểu đồ nến.
    """
    return page.eval_on_selector_all(
        ".mv2-sc-labels .mv2-sc-lab",
        r"""els => els.filter(e => /^\d\d:\d\d$/.test(e.textContent))
             .map(e => { const r = e.getBoundingClientRect();
               return {t: e.textContent, cx: +(parseFloat(e.style.left) * 10).toFixed(1),
                       left: r.left, right: r.right}; })""")


def test_the_time_axis_labels_describe_the_axis_not_a_corner_of_it(
        realtime_server, browser_page):
    """Nhãn thời gian phải nói trục chạy từ đâu đến đâu, và không được đè lên nhau.

    Khi pane dùng trục của biểu đồ nến, các điểm của chuỗi có thể chỉ chiếm một góc trục:
    đo được trên phiên thật, 22 slot trải hết bề ngang nhưng chỉ 3 slot ghi được số liệu
    và cả ba nằm ở cuối cửa sổ. Lấy mốc từ chuỗi khi đó sinh ra hai lỗi cùng lúc —
    `[đầu, giữa, cuối]` của hai điểm là `[0, 0, 1]` nên nhãn đầu vẽ HAI lần khít lên nhau
    (đo được 41,7px đè), và ba nhãn dồn hết vào mép phải (đè thêm 13,3px), không ai đọc
    được trục bắt đầu từ đâu.

    Phép kiểm dựng đúng ca đó: chuỗi chỉ giữ ba slot cuối.
    """
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    strategy = mv["sleeves"]["global_nkd"]["strategy"]
    strategy["slot_series"] = strategy["slot_series"][-3:]

    _open_price_context(browser_page, realtime_server, mv)
    # Chốt chặn: phải đang dùng trục chung, nếu không đây là một ca khác hẳn.
    assert _xspan(browser_page) == "shared", _axis_state(browser_page)

    labels = _time_labels(browser_page)
    marks = _price_slot_positions(browser_page)
    assert len(labels) >= 2, f"không đủ nhãn thời gian để đo: {labels}"
    assert len(marks) >= 3, f"biểu đồ nến chỉ vẽ {len(marks)} mark"

    texts = [o["t"] for o in labels]
    assert len(set(texts)) == len(texts), f"một nhãn được vẽ nhiều lần: {texts}"
    for a, b in zip(labels, labels[1:]):
        assert a["right"] <= b["left"], (
            f"nhãn {a['t']!r} đè lên {b['t']!r} {a['right'] - b['left']:.1f}px")

    # Và hai đầu phải là hai đầu của TRỤC — đúng mark đầu và mark cuối của biểu đồ nến.
    assert abs(labels[0]["cx"] - min(marks)) < 0.6, (
        f"nhãn đầu ở {labels[0]['cx']} trong khi trục bắt đầu ở {min(marks)}")
    assert abs(labels[-1]["cx"] - max(marks)) < 0.6, (
        f"nhãn cuối ở {labels[-1]['cx']} trong khi trục kết thúc ở {max(marks)}")


def test_two_points_do_not_make_the_same_label_twice(realtime_server, browser_page):
    """Hai điểm thì `[đầu, giữa, cuối]` là `[0, 0, 1]` — nhãn đầu vẽ HAI lần khít lên nhau.

    Đúng thứ đã thấy trên trang: hai chữ "02:45" chồng nhau ở cùng một toạ độ, một cái căn
    trái một cái căn giữa, đo được 41,7px đè. Ca này chạy trên nhánh KHÔNG chung trục, nơi
    mốc vẫn lấy từ chuỗi, nên nó chạm được đúng đoạn lọc trùng — nhánh chung trục lấy mốc
    từ 22 slot của biểu đồ nến nên không bao giờ sinh ra cặp trùng.
    """
    mv = _with_slot_series(_market_view(), series_day="2026-08-28")  # khác phiên -> trục riêng
    strategy = mv["sleeves"]["global_nkd"]["strategy"]
    strategy["slot_series"] = strategy["slot_series"][:2]

    _open_price_context(browser_page, realtime_server, mv)
    # Chốt chặn: phải đúng là nhánh trục riêng, nếu không ca này không chạm đoạn cần kiểm.
    assert _xspan(browser_page) == "own", _axis_state(browser_page)

    labels = _time_labels(browser_page)
    texts = [o["t"] for o in labels]
    assert len(labels) == 2, f"hai điểm phải cho đúng hai nhãn: {texts}"
    assert len(set(texts)) == 2, f"một nhãn được vẽ hai lần: {texts}"
    assert labels[0]["right"] <= labels[1]["left"], (
        f"hai nhãn đè nhau {labels[0]['right'] - labels[1]['left']:.1f}px: {texts}")


def _quiet_job(index: int) -> dict:
    """Một lượt chạy xong mà không đụng tới lệnh nào — hàng in câu hằng số."""
    minute = index * 5
    return {
        "id": f"quiet-{index}", "job_id": f"TRACK1_NKD_01{minute:02d}",
        "job_type": "live_day", "status": "completed",
        "started_at": f"2026-08-14T18:{minute:02d}:00Z",
        "ended_at": f"2026-08-14T18:{minute:02d}:05Z",
        "duration_seconds": 5, "reason": None, "diagnostics": [], "events": [],
    }


def _failed_job() -> dict:
    return {
        "id": "broken", "job_id": "TRACK1_NKD_0200", "job_type": "live_day",
        "status": "failed", "started_at": "2026-08-14T18:40:00Z",
        "ended_at": "2026-08-14T18:40:09Z", "duration_seconds": 9,
        "reason": "IBKR refused the order", "diagnostics": [], "events": [],
    }


def _job_row_sentences(page) -> list[str]:
    return page.eval_on_selector_all(
        ".job-row .job-summary", "els => els.map(e => e.textContent.trim())")


def test_the_quiet_sentence_is_stated_once_and_a_broken_slot_keeps_its_own(
        realtime_server, browser_page):
    """Câu "chạy xong, không đụng gì" nói một lần; slot có vấn đề giữ nguyên câu của nó.

    Đo được 2026-09-04: 29 hàng, ĐÚNG HAI câu khác nhau — 28 hàng nói câu hằng số và một
    hàng nói Windows chặn ghi runner-state. Hàng có sự cố duy nhất của ngày nằm lẫn giữa
    28 dòng giống hệt nhau; riêng câu ấy chiếm 1.008px, và danh sách dài 4.228px.

    Phép kiểm dựng đúng hình dạng đó: nhiều hàng im lặng, một hàng hỏng. Hàng hỏng phải là
    hàng DUY NHẤT còn mang chữ, và dòng nguồn phải NÓI RÕ nó phủ bao nhiêu hàng — nói
    trống thì một ngày 12 im lặng / 17 có chuyện sẽ đọc thành "hôm nay êm".
    """
    journal = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    journal["jobs"] = [_quiet_job(i) for i in range(6)] + [_failed_job()]
    stub_api(browser_page, {"/api/v1/job-journal/": journal})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".job-row", timeout=20_000)

    sentences = _job_row_sentences(browser_page)
    # Chốt chặn: phải có đủ hàng, nếu không mọi assert dưới đây đạt rỗng.
    assert len(sentences) == 7, f"dựng 7 hàng nhưng đọc được {len(sentences)}"

    spoken = [s for s in sentences if s]
    assert len(spoken) == 1, f"phải còn đúng một hàng mang chữ, đang có {len(spoken)}: {spoken}"
    assert "failed" in spoken[0].lower(), f"hàng còn chữ không phải hàng hỏng: {spoken[0]!r}"

    note = browser_page.eval_on_selector_all(
        ".journal-fold-note", "els => els.map(e => e.textContent.trim())")
    assert len(note) == 1, f"phải có đúng một câu gộp, đang có {len(note)}: {note}"
    assert "6 of 7 executions" in note[0], (
        f"câu gộp không nói nó phủ bao nhiêu hàng: {note[0]!r}")
    # Và phải ĐỌC ĐƯỢC HẾT. Bản đầu đặt câu này ở dòng nguồn, chỗ chỉ rộng 208px trong
    # khi câu cần 387px — người đọc thấy "30 with …" và không biết nó phủ bao nhiêu hàng,
    # tức là gộp mà không nói gì, đúng bằng không gộp.
    fits = browser_page.eval_on_selector(
        ".journal-fold-note",
        "el => el.scrollWidth <= Math.ceil(el.getBoundingClientRect().width) + 1")
    assert fits, "câu gộp bị cắt — người đọc không biết nó phủ bao nhiêu hàng"


def test_a_day_where_nothing_repeats_keeps_every_sentence_on_its_row(
        realtime_server, browser_page):
    """Chỉ gộp khi CÓ lặp. Một hàng im lặng thì không gộp.

    Gộp một hàng không tiết kiệm gì mà lại đẩy câu ra xa hàng nó mô tả. Phép kiểm này là
    chốt chặn cho phép kiểm trên: thiếu nó, một bản sửa gộp-mọi-lúc vẫn qua được cả hai.
    """
    journal = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    journal["jobs"] = [_quiet_job(0), _failed_job()]
    stub_api(browser_page, {"/api/v1/job-journal/": journal})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".job-row", timeout=20_000)

    sentences = _job_row_sentences(browser_page)
    assert len(sentences) == 2, f"dựng 2 hàng nhưng đọc được {len(sentences)}"
    assert all(sentences), f"một hàng bị gộp mất chữ dù chỉ có một hàng im lặng: {sentences}"
    assert browser_page.query_selector(".journal-fold-note") is None, (
        "danh sách gộp dù chỉ có một hàng im lặng")


def test_the_label_date_is_stated_once_in_the_regime_card(realtime_server, browser_page):
    """Ngày nhãn và tuổi bản đọc nói một lần, ở dòng nguồn của section.

    Đo được: `daily label · 2026-09-03 · checked 5.29h ago` ở dòng nguồn, và
    `as of 2026-09-03 · checked 5.29h ago` trong ô neo — cùng ngày, cùng số giờ, cách nhau
    176px. Dòng nguồn là chỗ mọi section khác của trang đặt xuất xứ của mình, nên bản trong
    ô neo là bản đi.
    """
    stub_api(browser_page, {"/api/v1/track1-market-view": {
        "market_view": {"session_date": "2026-08-27", "sleeves": {}},
        "regime": _regime()}})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#regimePosterior .regime-post-row", timeout=20_000)

    card = browser_page.eval_on_selector(".rg2-card", "el => el.innerText")
    src = browser_page.eval_on_selector(".regime-section .source-note", "el => el.textContent")
    # Chốt chặn: dòng nguồn phải THẬT SỰ mang ngày nhãn, nếu không "chỉ một lần" là vì
    # cả hai bản đều biến mất.
    assert "daily label" in src, f"dòng nguồn không mang ngày nhãn: {src!r}"
    assert "as of" not in card, f"ô neo vẫn nhắc lại xuất xứ: {card[:160]!r}"

    note = browser_page.eval_on_selector(".regime-section .mv2-note, .rg2-foot",
                                         "el => el.innerText")
    assert "percentage points" not in note, (
        f"chân thẻ vẫn nhắc lại biên xác suất mà ô LEAD đã in: {note!r}")
    # Stage 5ZZZ-CM. Ghim NGHĨA, không ghim câu chữ. Bản cũ đòi đúng cụm "no cutoff number";
    # câu đã được viết lại cho người không có nền ("not when some number is breached") và
    # test đỏ dù điều nó bảo vệ vẫn nguyên. Điều phải đúng là: dòng này nói KHÔNG có ngưỡng
    # nào để vượt qua — bằng chữ gì cũng được.
    assert ("no cutoff" in note or "no level" in note.lower()
            or "not when some number" in note), (
        f"đã xoá nhầm nửa KHÔNG trùng ở đâu khác: {note!r}")


def test_the_market_view_chips_do_not_restate_the_sentence_above_them(
        realtime_server, browser_page):
    """Hàng chip không được nhắc lại đúng câu nằm ngay trên nó.

    Đo được hai chip cách câu tóm tắt 3px: `3 / 22 slots observed` và
    `gate allow failed 19 of 22`, trong khi câu ấy đã nói "3 of 22 slots ... gate allow
    failed on 19 of 22 decided slots". Xuất xứ bằng chứng thì phải GIỮ — nó không có ở đâu
    khác và trả lời một câu hỏi khác hẳn.
    """
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    sleeve = mv["sleeves"]["global_nkd"]
    sleeve["coverage"]["observed_slots"] = 3
    # Làn chặn phải được đọc ra từ CHÍNH các ô mà detector ghi — `mvBlockingLane` đếm
    # `state === 'fail'`, không đọc trường `failed`. Dựng tay bằng cách sửa trường tổng sẽ
    # cho một fixture mà code thật không bao giờ nhìn tới.
    lane = sleeve["rule_lanes"][0]
    for cell in lane["cells"][3:]:
        cell["state"] = "fail"
    # Xuất xứ bằng chứng đọc từ hàng phiên trên đĩa, không suy từ sự có mặt của lane —
    # và `sessions` nằm cùng cấp với `market_view` trong phản hồi, không nằm bên trong nó.
    stub_api(browser_page, {"/api/v1/track1-market-view": {
        "market_view": mv, "regime": _regime(),
        "sessions": [{"day": sleeve["bars_session_date"], "has_diagnostics": True}]}})
    open_realtime(browser_page, realtime_server)
    browser_page.click('[data-mv-inner="Price context"]')
    browser_page.wait_for_selector(".mv2-sc-svg", timeout=20_000)
    browser_page.wait_for_timeout(500)
    summary = browser_page.eval_on_selector(".mv2-reason", "el => el.textContent.trim()")
    chips = browser_page.eval_on_selector_all(
        ".mv2-verdict-meta span, .mv2-verdict-side div", "els => els.map(e => e.textContent.trim())")
    # Chốt chặn: phải có câu VÀ có chip, nếu không so sánh dưới đây không kiểm gì.
    assert summary and "slots" in summary, f"không đọc được câu tóm tắt: {summary!r}"
    assert chips, "không đọc được chip nào"

    lane = re.search(r"([a-z ]+) failed on (\d+) of (\d+)", summary)
    assert lane, f"câu tóm tắt không nêu làn chặn nên phép kiểm chưa đúng ca: {summary!r}"
    echo = f"{lane.group(1).strip()} failed {lane.group(2)} of {lane.group(3)}"
    assert echo not in chips, f"chip lặp lại nguyên câu trên nó: {echo!r} trong {chips}"
    assert not any(c.endswith("slots observed") for c in chips), (
        f"chip vẫn nhắc lại hai con số của câu: {chips}")
    assert any("recorded while the slots ran" in c or "replayed over stored bars" in c
               for c in chips), f"xoá nhầm xuất xứ bằng chứng: {chips}"


def test_the_open_detail_does_not_repeat_what_the_row_header_already_shows(
        realtime_server, browser_page):
    """Khối mở không được in lại ba thứ hàng đã in.

    Hàng in `etDateTime(job.started_at)`, `duration(job.duration_seconds)` và
    `presentation.statusLabel`. Bảng thời gian trong khối mở in ĐÚNG ba biểu thức đó —
    không phải hai chuỗi tình cờ giống nhau, mà cùng một biểu thức ở hai chỗ. Đo được
    trong một hàng đang mở: giờ 3 lần, "12s" 2 lần, "COMPLETED" 2 lần.
    """
    journal = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    journal["jobs"] = [_failed_job()]
    stub_api(browser_page, {"/api/v1/job-journal/": journal})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".job-row", timeout=20_000)
    browser_page.click(".job-row .job-trigger")
    browser_page.wait_for_selector(".job-detail", timeout=10_000)

    head = browser_page.eval_on_selector(".job-row .job-trigger", "el => el.innerText")
    body = browser_page.eval_on_selector(".job-row .job-detail", "el => el.innerText")
    # Chốt chặn: hàng phải THẬT SỰ mang ba thứ đó, nếu không "không lặp" là vô nghĩa.
    assert "9s" in head, f"hàng không in thời lượng: {head!r}"
    assert "OPEN" in head, f"hàng không in trạng thái: {head!r}"

    for token in ("9s", "OPEN"):
        assert token not in body, f"khối mở in lại {token!r} mà hàng đã in: {body!r}"
    assert "Started" not in body and "Duration" not in body and "Outcome" not in body, (
        f"bảng thời gian vẫn giữ trường hàng đã in: {body!r}")


def test_a_settled_run_opens_to_one_block_and_a_broken_one_keeps_the_contract(
        realtime_server, browser_page):
    """Hợp đồng năm phần viết cho một SỰ CỐ, không cho một lượt chạy sạch.

    Điều kiện là CẤU TRÚC — chạy xong, không sự kiện, không chẩn đoán — chứ không so chuỗi.
    Đo được trước bản sửa: khối chi tiết của một lượt như vậy cao 490px để nói cùng một
    điều bốn lần.
    """
    journal = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    journal["jobs"] = [_quiet_job(0), _quiet_job(1), _failed_job()]
    stub_api(browser_page, {"/api/v1/job-journal/": journal})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".job-row", timeout=20_000)

    browser_page.click(".job-row.status-completed .job-trigger")
    browser_page.wait_for_selector(".job-detail", timeout=10_000)
    quiet_body = browser_page.eval_on_selector(".job-detail", "el => el.innerText")
    assert "IMPACT" not in quiet_body and "EVIDENCE / RESOLUTION" not in quiet_body, (
        f"lượt chạy sạch vẫn mở ra cả hợp đồng: {quiet_body!r}")
    assert "PROBLEM" in quiet_body, f"lượt chạy sạch không nói gì cả: {quiet_body!r}"

    browser_page.click(".job-row.status-open .job-trigger")
    browser_page.wait_for_timeout(400)
    broken_body = browser_page.eval_on_selector(".job-row.status-open .job-detail",
                                                "el => el.innerText")
    # Chốt chặn ngược: hàng hỏng PHẢI giữ đủ, nếu không bản sửa đang giấu mất bằng chứng.
    for part in ("IMPACT", "ACTION", "EVIDENCE / RESOLUTION"):
        assert part in broken_body, f"hàng hỏng mất phần {part}: {broken_body!r}"


def test_a_relative_time_agrees_with_the_absolute_time_beside_it(
        realtime_server, browser_page):
    """Hai nửa của cùng một dòng không được nói về hai thời điểm khác nhau.

    Đo được 2026-09-04: ô Now Monitor ghi "MAX_HOLD_EXIT · 09:31 ET · 1m ago" trong khi
    đồng hồ trang là 12:16 ET — lệch 2 giờ 45 phút. Chuỗi "x ago" còn TỰ NHÍCH mỗi 5 phút
    trong khi 09:31 đứng yên, vì nó tính từ `latest_expected_at` — slot gần nhất bộ lập
    lịch MONG ĐỢI — chứ không phải từ lúc quyết định kia xảy ra.

    Lỗi này bốn lượt rà thiết kế không bắt được: hợp đồng quản HÌNH, còn đây là chuyện
    ĐÚNG SAI. Một mốc tương đối sai làm hỏng lòng tin vào mọi mốc tương đối khác trên
    trang, kể cả "updated 7s ago" ở header.

    Payload được GHIM chứ không đọc dữ liệu sống: bản đầu của phép kiểm này so một mốc
    tương đối tính từ `server_now` của backend với đồng hồ ET đang chạy của trang, nên nó
    xanh khi chạy riêng và đỏ khi chạy trong bộ — một phép kiểm nhấp nháy còn tệ hơn không
    có, vì nó dạy người ta bỏ qua màu đỏ.
    """
    schedule = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/schedule-status"]))
    # `server_now` 18:07:00Z = 14:07 ET. Mọi mốc dưới đây neo vào đúng con số đó.
    schedule["next_scheduled_job"] = {"job_id": "LIVE_DAY_1410", "at": "2026-08-14T18:10:00Z"}
    schedule["next_decision_job"] = {"job_id": "LIVE_DAY_1425", "at": "2026-08-14T18:25:00Z"}
    # Ô "Latest decision" lấy GIỜ TUYỆT ĐỐI từ nhật ký job, không từ payload lịch. Phải
    # dựng một job quyết định ở một mốc RÕ RÀNG KHÁC `latest_expected_at`, nếu không ô ấy
    # hiện "--" và phép kiểm không chạm được đúng chỗ đã hỏng.
    journal = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    journal["jobs"] = [{
        "id": "dec-1", "job_id": "MAX_HOLD_EXIT", "job_type": "max_hold",
        "status": "completed", "started_at": "2026-08-14T13:31:00Z",
        "ended_at": "2026-08-14T13:31:20Z", "duration_seconds": 20,
        "reason": None, "diagnostics": [], "events": [],
    }]
    stub_api(browser_page, {"/api/v1/schedule-status": schedule,
                            "/api/v1/job-journal/": journal})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector(".now-schedule-facts .schedule-fact", timeout=20_000)
    browser_page.wait_for_timeout(900)

    rows = browser_page.eval_on_selector_all(
        ".now-schedule-facts .schedule-fact",
        r"""els => els.map(e => {
              const t = e.querySelector('time');
              return {label: ((e.querySelector('span') || {}).textContent || '').trim(),
                      abs: t ? t.textContent.trim() : null,
                      txt: (e.textContent || '').replace(/\s+/g, ' ').trim()};
            })""")
    # Chốt chặn: phải có ô mang CẢ giờ tuyệt đối lẫn mốc tương đối, nếu không "không mâu
    # thuẫn" đạt được bằng cách không có gì để so.
    # `innerText` nối các nút không chèn khoảng trắng, nên chuỗi ra là "ETin 3m" — biên từ
    # không tồn tại. Bắt theo HÌNH DẠNG của mốc thời lượng thay vì theo chữ.
    SPAN = re.compile(r"(?:in|ago)?\s*(?:(\d+)h)?\s*(?:(\d+)m)")
    paired = [r for r in rows if r["abs"] and re.search(r"\d+[hm]", r["txt"])]
    assert len(paired) >= 2, f"không đủ ô có cả hai loại mốc: {rows}"

    NOW = 14 * 60 + 7          # 18:07:00Z = 14:07 ET, chính là `server_now` đã ghim
    bad = []
    for r in paired:
        # `abs` có thể mang tiền tố thứ trong tuần ("Fri 14:10 ET") khi mốc không phải hôm nay.
        a = re.search(r"(\d{2}):(\d{2})", r["abs"])
        if not a:
            continue
        want = int(a.group(1)) * 60 + int(a.group(2))
        span = SPAN.search(r["txt"].split("ET")[-1])
        mins = (int(span.group(1) or 0) * 60 + int(span.group(2) or 0)) if span else 0
        if "ago" in r["txt"]:
            mins = -mins
        if abs((NOW + mins) - want) > 1:
            bad.append(f"{r['label']}: giờ tuyệt đối {r['abs']}, nhưng mốc tương đối trong "
                       f"{r['txt'][-24:]!r} trỏ tới {(NOW + mins) // 60:02d}:{(NOW + mins) % 60:02d}")
    assert bad == [], ("mốc tương đối không khớp mốc tuyệt đối cạnh nó: "
                       + " | ".join(bad))
def test_the_latest_bar_falls_inside_the_window_the_panel_declares(
        realtime_server, browser_page):
    """Mốc bar cuối phải nằm trong cửa sổ mà chính panel ấy khai, cả hai đều nói ET.

    Đo được 2026-09-04: panel khai "window 01:10–02:55 ET" và ngay dưới ghi
    "Latest bar 15:54 ET" — rơi ngoài hẳn cửa sổ của chính nó. Nguyên nhân: backend trả
    `latest_bar_et = "2026-09-04 15:54:00+09:00"`, tức giờ TOKYO có offset ghi rõ, còn bộ
    cắt chuỗi lấy thẳng 'HH:MM' và panel nối thêm chữ " ET". Mốc thì đúng — 15:54 Tokyo là
    02:54 ET, nằm gọn trong cửa sổ — chỉ cách trình bày là sai.

    Cùng lớp với lỗi biểu đồ vẽ nến tương lai vì lẫn UTC/ET: chart đã sửa, dòng data-health
    thì không. Phép kiểm này bắt cả hai vế cùng lúc, vì nó so hai con số PHẢI có quan hệ
    với nhau thay vì ghim một chuỗi.
    """
    _open_price_context(browser_page, realtime_server,
                        _with_slot_series(_market_view(), series_day="2026-08-27"))
    text = browser_page.eval_on_selector(
        ".market-view-section", "el => el.innerText.replace(/\s+/g, ' ')")

    win = re.search(r"window (\d{2}):(\d{2})[–-](\d{2}):(\d{2}) ET", text)
    bar = re.search(r"Latest bar (\d{2}):(\d{2})", text)
    # Chốt chặn: thiếu một trong hai thì không có gì để so, và test sẽ đạt rỗng.
    assert win, f"panel không khai cửa sổ ET: {text[:150]!r}"
    assert bar, f"panel không in mốc bar cuối: {text[:150]!r}"

    lo = int(win.group(1)) * 60 + int(win.group(2))
    hi = int(win.group(3)) * 60 + int(win.group(4))
    at = int(bar.group(1)) * 60 + int(bar.group(2))
    # Cửa sổ có thể vắt qua nửa đêm; khi đó "trong cửa sổ" là ngoài đoạn [hi, lo].
    inside = (lo <= at <= hi) if lo <= hi else (at >= lo or at <= hi)
    assert inside, (
        f"bar cuối {bar.group(0)!r} rơi ngoài cửa sổ {win.group(0)!r} — "
        "hai con số này cùng nói ET nên chúng phải khớp nhau")


def test_every_sleeve_count_shares_one_denominator(realtime_server, browser_page):
    """Ba hàng đếm ba TẬP CON của cùng một nhóm sleeve, nên chúng phải nói cùng một nền.

    Đo được 2026-09-04, cùng một ngày trên cùng một trang: `across 3 sleeve(s)` ·
    `across 2 sleeve(s)` · `1/4 sleeves complete`. Không con số nào sai — chúng đếm
    "đã báo tín hiệu", "đã ghi giải thích", "đã phủ hết cửa sổ" — nhưng cả ba chỉ ghi
    "sleeve(s)", nên người đọc thấy 2, 3, 4 và không thể biết đó là ba tập khác nhau hay
    ba lần đếm sai. Phần giải thích ngày hôm nay lại là phần làm ngày hôm nay khó hiểu.
    """
    # Ghim payload: ba hàng dưới đây đếm ba tập con, và mỗi tập chỉ tồn tại khi ngày đó
    # thật sự có dữ liệu. Đọc sống thì phép kiểm treo vào một ngày chưa chạy gì — đúng lỗi
    # đã làm năm phép kiểm khác đỏ lúc ngày ET vừa sang.
    runtime = {
        "route": "track1_candidate",
        "window_coverage": {"days": ["2026-08-14"], "latest": {
            "global_nkd": {"outcome": "complete"}, "roska4_calm": {"outcome": "complete"},
            "roska4_stress": {"outcome": "partial"}, "roska4_swing": {"outcome": "partial"}}},
        "signals": {"present": True, "sleeves": {
            "global_nkd": {"observed": True, "counts": {"NO_SIGNAL": 26}},
            "roska4_calm": {"observed": True, "counts": {"SLOT_REFUSED": 19}},
            "roska4_stress": {"observed": True, "counts": {}},
            "roska4_swing": {"observed": False, "counts": {}}}},
        "explanations": {"present": True, "days": {"20260814": 24},
                         "attribution": {"20260814": {"sleeves": ["global_nkd", "roska4_stress"],
                                                      "slots": 24}}},
    }
    stub_api(browser_page, {"/api/v1/track1-runtime": runtime})
    open_realtime(browser_page, realtime_server)
    # Khối này tự nói "the slowest read on the page": đợi ĐÚNG nội dung, không đợi khung.
    browser_page.wait_for_selector(".track1-section .fact", timeout=30_000)
    browser_page.wait_for_timeout(800)
    text = browser_page.eval_on_selector(
        ".track1-section", "el => el.innerText.replace(/\s+/g, ' ')")

    pairs = re.findall(r"(\d+) of (\d+) sleeves", text)
    # Chốt chặn: dưới hai chỗ thì "cùng mẫu số" đạt được vì không có gì để so.
    assert len(pairs) >= 2, (
        f"chỉ tìm được {len(pairs)} chỗ đếm sleeve — phép kiểm chưa chạm gì: {text[:200]!r}")
    # Và không được còn chỗ nào đếm mà KHÔNG nêu mẫu số.
    bare = re.findall(r"(?<!of )\b\d+ sleeve\(s\)", text)
    assert bare == [], f"còn chỗ đếm sleeve không nêu mẫu số: {bare}"

    denoms = {int(d) for _, d in pairs}
    assert len(denoms) == 1, (
        "các hàng đếm sleeve dùng nhiều mẫu số khác nhau: "
        + ", ".join(f"{n}/{d}" for n, d in pairs))


def _runtime_with_gates(orders_possible: bool, blocking=()) -> dict:
    return {"route": "track1_candidate",
            "gates": {"orders_possible": orders_possible, "blocking_now": list(blocking)}}


def test_the_top_band_says_when_no_order_can_be_placed(realtime_server, browser_page):
    """Dải đầu phải nói ra sự thật vận hành lớn nhất: tuyến có đặt được lệnh không.

    Đo được 2026-09-04: `ORDERS POSSIBLE: no` và ba cổng đang chặn nằm ở 11px, thấp hơn
    màn hình đầu 400px, trong khi năm thứ to nhất trong màn hình đầu đều là TÊN KHUNG
    CHỨA — "Operations", "Now Monitor", "Open Issues". Một bản rà độc lập đọc trang bằng
    mắt mới gọi đây là việc số một, và phép đo đồng ý.

    Chỉ thêm dòng khi câu trả lời là KHÔNG — ngày bình thường dải đầu giữ nguyên sự tiết
    chế bản thiết kế cố ý để lại. Phép kiểm ghim CẢ HAI vế, vì thiếu vế thứ hai thì một
    bản sửa in dòng ấy mọi lúc cũng qua được.
    """
    stub_api(browser_page, {"/api/v1/track1-runtime": _runtime_with_gates(
        False, ["account_legacy_retirement", "shadow_evidence"])})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_timeout(1200)
    rail = browser_page.eval_on_selector(".system-conclusion b", "el => el.textContent")
    assert "no orders possible" in rail, f"dải đầu không nói tuyến đang chặn: {rail!r}"
    assert "shadow_evidence" in rail or "Shadow evidence" in rail, (
        f"dải đầu không nêu cổng nào đang chặn: {rail!r}")

    # Vế ngược: đặt được lệnh thì KHÔNG thêm dòng.
    stub_api(browser_page, {"/api/v1/track1-runtime": _runtime_with_gates(True)})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_timeout(1200)
    rail2 = browser_page.eval_on_selector(".system-conclusion b", "el => el.textContent")
    assert "no orders possible" not in rail2, (
        f"dải đầu vẫn báo chặn dù tuyến đặt được lệnh: {rail2!r}")


def test_the_metric_tile_and_the_table_print_the_same_probability(
        realtime_server, browser_page):
    """Cùng một xác suất thì hai chỗ phải in ra cùng một con số.

    Đo được 2026-09-04: ô CONFIDENCE in `91.1%` còn bảng STATE PROBABILITIES in `91.07%`,
    cách nhau 12px. Không con số nào sai — nhưng người đọc phải dừng lại tự hỏi hai con số
    ấy có phải một không, và đó là chi phí không ai trả cho.

    Phép kiểm ghim QUAN HỆ chứ không ghim một định dạng: dù sau này chọn mấy chữ số, hai
    chỗ vẫn phải nói giống nhau.
    """
    stub_api(browser_page, {"/api/v1/track1-market-view": {
        "market_view": {"session_date": "2026-08-27", "sleeves": {}}, "regime": _regime()}})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#regimePosterior .regime-post-row", timeout=20_000)

    conf = browser_page.eval_on_selector(".rg2-metric-val", "el => el.textContent.trim()")
    label = browser_page.eval_on_selector(
        "#regimePosterior .regime-post-row", "el => el.textContent")
    top = browser_page.eval_on_selector(
        "#regimePosterior .regime-post-row b", "el => el.textContent.trim()")
    # Chốt chặn: cả hai phải là số phần trăm, nếu không so sánh dưới đây vô nghĩa.
    assert conf.endswith("%") and top.endswith("%"), f"không đọc được hai giá trị: {conf!r} {top!r}"
    assert "Calm" in label, f"hàng đầu bảng không phải Calm: {label!r}"

    assert conf == top, (
        f"ô chỉ số in {conf!r} còn bảng in {top!r} cho cùng một xác suất")
