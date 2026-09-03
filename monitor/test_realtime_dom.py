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


def test_5zzf_open_issues_carry_their_route_scope_as_a_chip(realtime_server, browser_page):
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
    browser_page.wait_for_selector("#openIssueList .issue-scope", timeout=10_000)
    chips = browser_page.eval_on_selector_all(
        "#openIssueList .issue-scope", "els => els.map(e => e.textContent.trim())")
    assert "LEGACY" in chips, chips
    # the issue is still listed — labelled, not removed
    rows = browser_page.eval_on_selector_all(
        "#openIssueList .issue-list-row", "els => els.length")
    assert rows == 1, rows


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
