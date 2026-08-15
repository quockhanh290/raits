# Realtime Dashboard Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Làm cho dashboard Realtime không bao giờ hiển thị "ổn" khi hệ thống đang hỏng, và không bao giờ báo động về việc đã tự phục hồi.

**Architecture:** Toàn bộ sửa chữa nằm trong hai vùng: `monitor/backend/` (Flask read-only) và `global_index/dash/realtime/` (static frontend). Bắt đầu bằng hai test tĩnh tự-suy-diễn (không cần allowlist thủ công) chặn đúng hai Critical, rồi dựng harness Playwright chạy trang thật với API bị stub, sau đó sửa từng tầng: incident lifecycle → freshness → timestamp → metric honesty → protection verification → cleanup.

**Tech Stack:** Python 3.10+, Flask, pytest 9.0.2, Playwright (chromium 148 đã cài sẵn), vanilla ES2020 (không build step, không bundler, không `package.json`).

**Spec:** [REALTIME_DASHBOARD_AUDIT.md](../../REALTIME_DASHBOARD_AUDIT.md) — mọi task dưới đây trích ID finding (C1, C2, H1…) từ file đó.

## Global Constraints

- **KHÔNG chạm vào code giao dịch.** Cấm sửa `global_index/runner.py`, `global_index/signal_layer.py`, `global_index/ibkr_broker.py`, `futures/`, `raits/`. Nếu một fix có vẻ cần đổi payload runner (ví dụ L6, hoặc thêm `contracts` vào `dump_state`), **dừng lại và báo cáo** — đó là quyết định riêng của user, không nằm trong plan này.
- **Backend phải giữ read-only.** Chỉ `@app.get`. Test khóa `test_backend_routes_are_read_only` và `test_backend_does_not_import_runner_or_write_state` phải luôn PASS.
- **KHÔNG chạy `git add` / `git commit`.** User tự quản lý version control. Bước "Commit" trong mỗi task chỉ ghi ra **ranh giới commit dự kiến** và câu lệnh đề xuất — trình bày cho user, không tự chạy.
- **Lệnh dài để user tự chạy.** Không chạy pytest full-suite hay Playwright trong background tool; đưa lệnh cho user chạy trong terminal của họ.
- Mọi lệnh chạy từ repo root `d:\raits`.
- **Đo baseline trước khi bắt đầu**, đừng tin số viết sẵn: `python -m pytest monitor/test_dashboard_backend.py -q`. Lúc viết plan là 114; đo lại lúc 2026-08-14 10:21 là **116** vì file này đang được sửa song song ngoài phạm vi plan. Quy tắc là **số chỉ được tăng sau mỗi task**, không phải khớp một con số cố định. Các con số tuyệt đối ghi ở từng task là tương đối so với baseline bạn đo được.
- Frontend không có build step: sửa `realtime.js` là sửa trực tiếp file được serve. Không thêm dependency, không thêm `package.json`.
- Giữ nguyên nguyên tắc đã có: **không tái tạo broker truth từ runner state** (`realtime.js:736-739`), và **không trộn ledger runner với NetLiquidation của broker** (`monitor/paper_pnl_compare.json.notes`).
- Tiếng Anh cho mọi chuỗi hiển thị trên UI (khớp phần còn lại của trang). Tiếng Việt chỉ dùng trong comment giải thích quyết định.

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `monitor/test_realtime_contract.py` | **Tạo mới.** Test tĩnh về hợp đồng DOM giữa `realtime.js` ↔ `index.html`, và nhất quán chéo giữa các reader. Không cần browser. | T1, T6, T12 |
| `monitor/test_realtime_dom.py` | **Tạo mới.** Harness Playwright: dựng Flask trên cổng tạm, stub `/api/**`, assert DOM đã render. | T2, T3, T5, T7–T12 |
| `monitor/backend/schedule_status.py` | Thêm trạng thái `stale` dựa trên tuổi `observed_at`; xuất `state_age_seconds`. | T4 |
| `monitor/backend/job_journal_reader.py` | Set `lifecycle_status`/`recovered_at` cho **mọi** job `failed`/`missed`, không chỉ `stop_repair`. | T6 |
| `monitor/backend/open_issue_reader.py` | `coverage` phản ánh dòng log cuối cùng thật. | T11 |
| `monitor/backend/app.py` | Route favicon để console sạch. | T12 |
| `global_index/dash/realtime/index.html` | Bỏ `hidden` khỏi `runnerContext`; thêm dòng Broker account; đổi nhãn Protection. | T5, T9, T11 |
| `global_index/dash/realtime/realtime.js` | Phần lớn thay đổi: incident lane, freshness, timestamp, metric, protection, cleanup. | T3, T5–T12 |
| `global_index/dash/realtime/realtime.css` | Style cho trạng thái mới; xóa CSS mồ côi. | T5, T7, T12 |
| `monitor/test_dashboard_backend.py` | Mở rộng suite backend hiện có (không viết lại). | T1, T4, T6, T11 |

---

## Task 1: Hai test tĩnh chặn Critical tái diễn

Đây là task quan trọng nhất trong plan. Hai test này **tự suy ra tập id** từ chính source, không cần allowlist bảo trì bằng tay, và chúng fail **chính xác** trên C1 và C2 ở trạng thái hiện tại. Làm task này trước để mọi task sau có lưới an toàn.

**Files:**
- Create: `monitor/test_realtime_contract.py`
- Modify: `monitor/test_dashboard_backend.py` (thêm 1 test đăng ký)

**Interfaces:**
- Consumes: không có (task đầu tiên).
- Produces: `ROOT`, `DASH`, `REALTIME` (Path), `_realtime_sources() -> tuple[str, str]` — dùng lại ở T6 và T12.

- [ ] **Step 1: Viết hai test đang fail**

Tạo `monitor/test_realtime_contract.py`:

```python
"""Static contract between realtime.js and index.html.

Hai bug Critical (C1, C2 trong REALTIME_DASHBOARD_AUDIT.md) đều là cùng một
hình dạng: JS nói chuyện với một element mà HTML không cung cấp đúng cách, và
không có gì kêu lên. Hai test dưới đây suy ra tập id từ chính source nên không
có allowlist nào phải bảo trì bằng tay.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "global_index" / "dash"
REALTIME = DASH / "realtime"

_JS_LOOKUP = re.compile(r"\$\('([A-Za-z0-9_]+)'\)")
_HTML_ID = re.compile(r'id="([A-Za-z0-9_]+)"')


def _realtime_sources() -> tuple[str, str]:
    return (REALTIME / "realtime.js").read_text(encoding="utf-8"), \
           (REALTIME / "index.html").read_text(encoding="utf-8")


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
```

- [ ] **Step 2: Chạy để xác nhận cả hai FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_contract.py -v
```
Kỳ vọng: **2 failed**, với message chính xác:
- `realtime.js reads DOM ids that nothing renders … ['schedulerHealth', 'schedulerHealthValue']`
- `realtime.js writes content into elements that start hidden … ['runnerContext']`

Nếu message khác đi, dừng lại — nghĩa là source đã thay đổi so với lúc audit và phải audit lại trước khi sửa.

- [ ] **Step 3: Đăng ký vào suite chính**

Thêm vào cuối `monitor/test_dashboard_backend.py`:

```python
def test_realtime_contract_suite_exists():
    """Lưới an toàn cho C1/C2 phải luôn nằm trong repo, không bị đổi tên đi mất."""
    assert (ROOT / "monitor" / "test_realtime_contract.py").exists()
```

- [ ] **Step 4: Chạy suite chính, xác nhận không hồi quy**

Chạy:
```powershell
python -m pytest monitor/test_dashboard_backend.py -q
```
Kỳ vọng: **baseline + 1**.

- [ ] **Step 5: Ranh giới commit (user tự chạy)**

```bash
git add monitor/test_realtime_contract.py monitor/test_dashboard_backend.py
git commit -m "test: add static DOM contract guards for realtime dashboard (C1, C2)"
```

Hai test mới đang **FAIL có chủ đích** — chúng là bằng chứng bug, sẽ xanh ở T3 và T5. Nói rõ điều này khi báo cáo cho user.

---

## Task 2: Harness Playwright cho DOM smoke test

**Files:**
- Create: `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `monitor.backend.app.app` (Flask app object đã có sẵn).
- Produces:
  - fixture `realtime_server` → `str` (base URL, ví dụ `http://127.0.0.1:53412`)
  - fixture `browser_page` → `playwright.sync_api.Page`
  - `stub_api(page, overrides: dict[str, dict] | None = None) -> None`
  - `open_realtime(page, base_url: str) -> None` — điều hướng và chờ render xong
  - `rail_text(page) -> str`, `monitor_statuses(page) -> list[str]`
  - `BASE_PAYLOADS: dict[str, dict]` — payload lành mạnh mặc định, các task sau override từng mảnh

- [ ] **Step 1: Viết harness + ba test smoke**

Tạo `monitor/test_realtime_dom.py`:

```python
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
                    "model_age": {"status": "OK", "months_old": 1},
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


def test_healthy_page_loads_without_console_errors(realtime_server, browser_page):
    errors: list[str] = []
    browser_page.on("console", lambda msg: errors.append(msg.text)
                    if msg.type == "error" else None)
    browser_page.on("pageerror", lambda exc: errors.append(str(exc)))
    stub_api(browser_page)
    open_realtime(browser_page, realtime_server)
    real_errors = [item for item in errors if "favicon" not in item.lower()]
    assert not real_errors, real_errors


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_no_horizontal_page_overflow(realtime_server, browser_page, width, height):
    """Bảng rộng được phép cuộn TRONG container overflow-x:auto, nhưng trang thì không."""
    browser_page.set_viewport_size({"width": width, "height": height})
    stub_api(browser_page)
    open_realtime(browser_page, realtime_server)
    overflow = browser_page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert overflow is False, f"page overflows horizontally at {width}x{height}"
```

- [ ] **Step 2: Chạy harness, xác nhận PASS trên code hiện tại**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -v
```
Kỳ vọng: **3 passed** (1 console + 2 overflow). Đây là baseline — trang hiện tại đã sạch ở hai mặt này, và harness giờ chứng minh điều đó thay vì tin lời.

Nếu chromium chưa cài: `python -m playwright install chromium` (đã kiểm tra sẵn có ở máy này, chromium 148.0.7778.96).

- [ ] **Step 3: Ranh giới commit (user tự chạy)**

```bash
git add monitor/test_realtime_dom.py
git commit -m "test: add playwright DOM smoke harness for realtime dashboard"
```

---

## Task 3: C1 — gỡ incident IBKR/reconcile khỏi nhánh chết

**Files:**
- Modify: `global_index/dash/realtime/realtime.js:515-548` (bỏ khối `if (schedulerHealth)`), `:631` (bỏ nén gap)
- Test: `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `stub_api`, `open_realtime`, `monitor_statuses`, `_session_events`, `BASE_PAYLOADS` từ T2.
- Produces: `OPEN_TWS_OUTAGE: dict` — fixture event dùng lại ở các task sau.

- [ ] **Step 1: Viết hai test đang fail**

Thêm vào `monitor/test_realtime_dom.py`:

```python
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
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -k "tws_outage or never_silent" -v
```
Kỳ vọng: **2 failed** — `IBKR connectivity unavailable` không có trong `#nowMonitorList`.

- [ ] **Step 3: Gỡ nhánh chết**

Trong `global_index/dash/realtime/realtime.js`, xóa các dòng 517-528 (`schedulerIncidents`, `schedulerHealth`, `schedulerHealthClass`, `schedulerHealthText` và khối `if/else if`), xóa dòng 546-548 (`schedulerHealth.className = …`, `$('schedulerHealthValue')…`, `}`), và để hai vòng `forEach` push incident ở mức ngoài cùng của hàm. Kết quả đoạn 511-545 phải đọc như sau:

```js
    const openConnectivity = (state.sessionEvents?.events || []).filter(event =>
      event.kind === 'connectivity_outage' && event.status === 'open');
    const openReconcile = (state.sessionEvents?.events || []).filter(event =>
      event.kind === 'broker_reconcile_incident' && event.status === 'open');
    // Hai vòng dưới từng bị bọc trong `if ($('schedulerHealth'))`. Element đó đã bị
    // xóa khỏi index.html khi rail được rút gọn, và JS không dọn theo — nên hai alarm
    // quan trọng nhất của trang im lặng. Không có điều kiện nào ở đây là đúng:
    // incident kết nối broker và incident reconcile phải luôn được xét.
    openConnectivity.forEach(event => incidents.push({
      key: `broker:connectivity:${(event.affected_services || [event.service]).join(',')}:${event.started_at || event.ts}`,
      status: 'incident', component: 'broker', title: event.title || 'IBKR connectivity unavailable',
      problem: event.problem || event.message,
      impact: event.impact || 'The affected IBKR service may still be unavailable.',
      action: event.action || 'Check IBKR/TWS connectivity and current broker state now.',
      evidence: event.evidence || `IBKR code ${event.down_code || '--'}`
    }));
    if (!brokerPositionsMatchNow()) openReconcile.forEach(event => incidents.push({
      key: `runner:reconcile:${event.started_at || event.ts}`,
      status: 'incident', component: 'runner', title: event.title || 'Broker/runner positions do not reconcile',
      problem: event.problem || event.message,
      impact: event.impact || 'Current broker exposure cannot be inferred safely from runner state alone.',
      action: event.action || 'Reconcile IBKR positions, working stops, and runner persisted positions now.',
      evidence: event.evidence || 'B3 mismatch/orphan with no later match'
    }));
```

Xóa luôn `const twsOutageOpen = …` (dòng 515-516) — nó chỉ tồn tại để phục vụ việc nén gap sắp bị bỏ ở Step 4.

- [ ] **Step 4: Bỏ nén gap broker**

Tìm dòng bắt đầu bằng `if (!brokerUsable() && !twsOutageOpen) gaps.push({ key: 'gap:broker'` và thay bằng:

```js
    // Trước đây gap này bị nén khi có TWS outage đang mở, với lý do "đã có incident
    // riêng rồi". Lý do đó chỉ đúng nếu incident kia thực sự được push — điều đã sai
    // suốt thời gian khối trên nằm trong nhánh chết. Nén dựa trên incident CÓ THẬT
    // trong mảng, không dựa trên một cờ suy diễn.
    const connectivityIncidentShown = incidents.some(item => item.key.startsWith('broker:connectivity:'));
    if (!brokerUsable() && !connectivityIncidentShown) gaps.push({ key: 'gap:broker', status: 'unknown', component: 'broker', title: 'Broker truth unavailable', problem: 'The read-only IBKR observation is disconnected, stale, or unavailable.', impact: 'Current positions, working stops, and reconciliation cannot be verified.', action: 'Restore the read-only IBKR connection; do not reconstruct broker truth from runner state.', evidence: state.broker?.error || `broker freshness ${state.broker?.freshness || 'unknown'}` });
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/test_realtime_dom.py -v
python -m pytest monitor/test_realtime_contract.py::test_every_id_realtime_js_reads_is_actually_rendered -v
```
Kỳ vọng: `node --check` không in gì; DOM suite **5 passed**; test id contract chuyển từ FAIL sang **PASS**.

- [ ] **Step 6: Ranh giới commit (user tự chạy)**

```bash
git add global_index/dash/realtime/realtime.js monitor/test_realtime_dom.py
git commit -m "fix(realtime): surface IBKR connectivity and reconcile incidents (C1)"
```

---

## Task 4: C2 backend — freshness phải fail trên tuổi snapshot

**Files:**
- Modify: `monitor/backend/schedule_status.py:28-31` (hằng số), `:210-304` (`get_schedule_status`)
- Test: `monitor/test_dashboard_backend.py`

**Interfaces:**
- Consumes: `_iso`, `_nearby_slots`, `_patch_logs`/`_lines_through` (helper test đã có ở `test_dashboard_backend.py:30-46`).
- Produces:
  - `STATE_STALE_ALLOWANCE_SECONDS: int = 20 * 60`
  - `get_schedule_status()` trả thêm khóa `state_age_seconds: float | None`
  - enum `freshness` mở rộng thành `{"fresh", "not_expected_yet", "late", "missing", "unknown", "stale"}`

- [ ] **Step 1: Viết ba test đang fail**

Thêm vào `monitor/test_dashboard_backend.py`, ngay sau `test_older_unexplained_slot_cannot_be_hidden_by_newer_slot`:

```python
def test_stale_snapshot_cannot_be_reported_fresh(monkeypatch, tmp_path: Path):
    """C2: `observed_at` từng chỉ được dùng để kiểm tra None. Một
    live_state_data.js 90 ngày tuổi vẫn ra `fresh` trong active window, y hệt
    một file 2 phút tuổi. Đây là đường dẫn 'stale nhìn giống healthy'."""
    now = dt.datetime(2026, 8, 14, 7, 0, tzinfo=dt.timezone.utc)  # 03:00 ET, NKD window
    _patch_logs(monkeypatch, _lines_through(now.astimezone(ET)))

    recent = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(minutes=2), now=now)
    ancient = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(days=90), now=now)

    assert recent["freshness"] == "fresh"
    assert ancient["freshness"] == "stale"
    assert ancient["state_age_seconds"] > 90 * 86400 - 60


def test_stale_beats_not_expected_yet_outside_the_window(monkeypatch, tmp_path: Path):
    """Ngoài giờ chạy, 'chưa tới lượt' là câu trả lời đúng cho một snapshot mới —
    nhưng không phải cho một snapshot đã bỏ lỡ slot gần nhất."""
    now = dt.datetime(2026, 8, 14, 15, 0, tzinfo=dt.timezone.utc)  # 11:00 ET
    _patch_logs(monkeypatch, _lines_through(now.astimezone(ET)))

    fresh_enough = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(minutes=2), now=now)
    ancient = schedule_status.get_schedule_status(
        tmp_path, observed_at=now - dt.timedelta(days=30), now=now)

    assert fresh_enough["freshness"] == "not_expected_yet"
    assert ancient["freshness"] == "stale"


def test_state_age_is_none_when_nothing_was_observed(monkeypatch, tmp_path: Path):
    now = dt.datetime(2026, 8, 14, 15, 0, tzinfo=dt.timezone.utc)
    _patch_logs(monkeypatch, _lines_through(now.astimezone(ET)))
    status = schedule_status.get_schedule_status(tmp_path, observed_at=None, now=now)
    assert status["freshness"] == "missing"
    assert status["state_age_seconds"] is None
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_dashboard_backend.py -k "stale_snapshot or stale_beats or state_age_is_none" -v
```
Kỳ vọng: 3 failed — hai cái đầu vì `'fresh'`/`'not_expected_yet'` != `'stale'`, cái thứ ba vì `KeyError: 'state_age_seconds'`.

- [ ] **Step 3: Thêm hằng số**

Trong `monitor/backend/schedule_status.py`, ngay sau `STOP_REPAIR_SLOTS = tuple(...)` (dòng 31), thêm:

```python
# Bao lâu một snapshot được phép cũ hơn slot due gần nhất trước khi bị gọi là stale.
# Đây là tuổi của CHÍNH snapshot, không phải deadline của slot: slot chạy mỗi 5 phút
# nên "latest_slot + allowance" luôn nằm ở tương lai suốt active window và không bao
# giờ trôi qua — neo vào đó thì một file 90 ngày tuổi vẫn ra "fresh", đúng cái lỗ
# C2 cần bịt. 20 phút ≈ 4 slot liên tiếp không ghi được state.
STATE_STALE_ALLOWANCE_SECONDS = 20 * 60
```

- [ ] **Step 4: Tính tuổi và chèn nhánh `stale`**

Trong `get_schedule_status`, ngay **trước** dòng `if observed_at is None:` (dòng 269), chèn:

```python
    state_age_seconds = None
    stale_against_latest = False
    if observed_at is not None:
        observed_utc = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=dt.timezone.utc)
        state_age_seconds = max(0.0, round((server_now - observed_utc).total_seconds(), 3))
        if latest is not None:
            # KHÔNG neo vào `latest["at"] + allowance`: slot chạy mỗi 5 phút nên mốc đó
            # luôn ở tương lai suốt active window và không bao giờ trôi qua — đo thực tế
            # cho thấy snapshot 90 ngày tuổi lúc 14:30 ET vẫn ra False. Neo vào tuổi của
            # chính snapshot.
            stale_against_latest = (
                observed_utc < latest["at"]
                and state_age_seconds > STATE_STALE_ALLOWANCE_SECONDS
            )
```

Rồi thay toàn bộ chuỗi điều kiện (dòng 269-286) bằng:

```python
    if observed_at is None:
        freshness = "missing"
    elif stale_against_latest:
        # Đặt TRƯỚC mọi nhánh khác: một snapshot bỏ lỡ slot gần nhất không thể
        # được cứu bởi việc "chưa tới giờ slot kế tiếp".
        freshness = "stale"
    elif not trading_today or before_first:
        freshness = "not_expected_yet"
    elif overdue_unexplained:
        freshness = "late"
    elif not active_window:
        freshness = "not_expected_yet"
    elif not log_available:
        freshness = "unknown"
    else:
        state = latest_evidence["state"]
        if next_slot and next_slot["at"].date() == now_et.date():
            freshness = "fresh"
        elif state in ("executed", "failed", "skipped", "not_observed"):
            freshness = "not_expected_yet"
        else:
            freshness = "unknown"
```

Trong dict trả về, thêm ngay sau `"freshness": freshness,`:

```python
        "state_age_seconds": state_age_seconds,
```

- [ ] **Step 5: Chạy test, xác nhận PASS + không hồi quy**

Chạy:
```powershell
python -m pytest monitor/test_dashboard_backend.py -q
```
Kỳ vọng: **baseline + 4** (1 từ T1 + 3 mới). Các test freshness cũ (`market_holiday_is_not_expected_yet`, `gap_between_windows_is_not_expected_yet`, `mutex_skip_suppresses_late`, `failed_slot_is_incident_while_state_remains_fresh`) phải vẫn PASS — chúng dùng `observed_at` gần hiện tại nên không chạm nhánh mới. Nếu một trong số chúng fail, nhánh `stale` đặt sai vị trí.

- [ ] **Step 6: Kiểm tra trên dữ liệu thật (read-only)**

Chạy:
```powershell
python -X utf8 -c "import datetime as dt; from pathlib import Path; from monitor.backend.schedule_status import get_schedule_status; now=dt.datetime(2026,8,14,7,0,tzinfo=dt.timezone.utc); [print(lbl, get_schedule_status(Path('.'), observed_at=now-d, now=now)['freshness']) for lbl,d in [('2min',dt.timedelta(minutes=2)),('90d',dt.timedelta(days=90))]]"
```
Kỳ vọng: `2min fresh` / `90d stale` — đảo ngược hẳn kết quả đo trong audit (trước đây cả hai đều `fresh`).

- [ ] **Step 7: Ranh giới commit (user tự chạy)**

```bash
git add monitor/backend/schedule_status.py monitor/test_dashboard_backend.py
git commit -m "fix(monitor): fail runner freshness on snapshot age, not just scheduler log (C2)"
```

---

## Task 5: C2 frontend — đưa tuổi runner state ra màn hình

**Files:**
- Modify: `global_index/dash/realtime/index.html:37`
- Modify: `global_index/dash/realtime/realtime.js:253-259`, `:279`, `:323-329`, `:405-432`
- Modify: `global_index/dash/realtime/realtime.css`
- Test: `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `freshness: "stale"` và `age_seconds` (backend đã trả `age_seconds` sẵn từ `runner_state_reader.py:79`).
- Produces: `runnerFreshnessText(freshness, nextAt, ageSeconds)` — chữ ký mở rộng thêm tham số thứ ba.

- [ ] **Step 1: Viết hai test đang fail**

Thêm vào `monitor/test_realtime_dom.py`:

```python
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
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -k "stale_runner" -v
```
Kỳ vọng: **2 failed** — `el.hidden` là `True`.

- [ ] **Step 3: Bỏ `hidden` trong HTML**

`global_index/dash/realtime/index.html`, dòng 37 — đổi:

```html
      <b id="runnerContext" hidden>Loading</b>
```

thành:

```html
      <span class="runner-header-state"><i></i><b id="runnerContext">Loading</b></span>
```

- [ ] **Step 4: Mở rộng `runnerFreshnessText` và `renderContext`**

Thay hàm `runnerFreshnessText` (dòng 323-329) bằng:

```js
  function runnerFreshnessText(freshness, nextAt, ageSeconds) {
    if (freshness === 'fresh') return `Current · updated ${age(ageSeconds)}`;
    if (freshness === 'stale') return `Stale · last published ${age(ageSeconds)}`;
    if (freshness === 'not_expected_yet') return `On schedule · next ${etClock(nextAt)}`;
    if (freshness === 'late') return `Late · due ${etClock(nextAt)}`;
    if (freshness === 'missing') return 'No snapshot available';
    return `Timing unknown · last seen ${age(ageSeconds)}`;
  }
```

Trong `renderContext`, thay đoạn dòng 253-259 bằng:

```js
    const rf = state.runner?.freshness || 'missing';
    $('runnerContext').textContent = runnerFreshnessText(rf, state.runner?.expected_next_at, state.runner?.age_seconds);
    $('runnerContext').className = ['stale', 'late', 'missing'].includes(rf) ? 'negative'
      : rf === 'unknown' ? 'warning' : '';
```

Trong `renderMetrics` (dòng 279), thêm `stale` vào điều kiện làm mờ:

```js
    $('metrics').classList.toggle('runner-stale', ['missing', 'unknown', 'stale'].includes(state.runner?.freshness));
```

- [ ] **Step 5: Đưa vào kết luận rail**

Trong `renderRail`, thêm `stale` vào `stripScheduleBad`:

```js
    const stripScheduleBad = (stripSchedule?.open_incidents || stripSchedule?.incidents || []).length > 0
      || (stripSchedule?.unexplained_overdue || []).length > 0
      || stripFreshness === 'late'
      || stripFreshness === 'stale'
      || stripFreshness === 'missing'
      || stripEvidence?.severity === 'incident';
```

và chèn ngay sau dòng `if (stripScheduleBad) stripConditions.push('scheduler attention required');`:

```js
    if (['stale', 'late', 'missing'].includes(stripFreshness)) {
      stripConditions.push(`runner state ${stripFreshness} (${age(state.runner?.age_seconds)})`);
    }
```

*(Dòng `open_incidents || incidents` sẽ được sửa thành `??` ở T6 — để nguyên ở task này.)*

- [ ] **Step 6: Thêm style**

Kiểm tra tên biến màu đang dùng:
```powershell
rg -n "^\s+--" global_index/dash/realtime/realtime.css | head -20
```

Thêm vào `realtime.css`, cạnh `.broker-header-state`:

```css
.runner-header-state { display: inline-flex; align-items: center; gap: 6px; }
.runner-header-state i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.runner-header-state .negative { color: var(--red); }
.runner-header-state .warning { color: var(--amber); }
```

- [ ] **Step 7: Chạy test, xác nhận PASS**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/test_realtime_dom.py monitor/test_realtime_contract.py -v
```
Kỳ vọng: toàn bộ PASS — kể cả `test_no_element_is_written_to_while_permanently_hidden` (chuyển từ FAIL sang PASS) và hai test overflow ở 390px (dòng mới trong header không được làm tràn).

- [ ] **Step 8: Ranh giới commit (user tự chạy)**

```bash
git add global_index/dash/realtime/index.html global_index/dash/realtime/realtime.js global_index/dash/realtime/realtime.css monitor/test_realtime_dom.py
git commit -m "fix(realtime): show runner snapshot age and stale state in header and rail (C2)"
```

---

## Task 6: H1 — một sự thật duy nhất về "đã phục hồi chưa"

**Files:**
- Modify: `monitor/backend/job_journal_reader.py:116-160`
- Modify: `global_index/dash/realtime/realtime.js:550`
- Test: `monitor/test_dashboard_backend.py`, `monitor/test_realtime_contract.py`, `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `later_same_stream` đã được `_annotate_impact_and_action` tính sẵn (dòng 121-126).
- Produces: mọi job có `status ∈ {failed, missed}` mang `lifecycle_status ∈ {"open", "recovered"}` và `recovered_at: str | None`.

- [ ] **Step 1: Xác định định dạng log fixture**

Trước khi viết test, xác nhận reader nhận diện đúng định dạng dòng log thật:

```powershell
python -X utf8 -c "from pathlib import Path; from monitor.backend.job_journal_reader import read_job_journal; import json; print(json.dumps([{k: j.get(k) for k in ('job_id','job_type','status','reason','lifecycle_status')} for j in read_job_journal('2026-08-14', Path('.'))['jobs']][:8], indent=1))"
```

Ghi lại định dạng dòng đang được parse và dùng đúng nó trong fixture ở Step 2. Nếu fixture dưới đây không sinh ra job, chỉnh cho khớp output lệnh trên trước khi đi tiếp.

- [ ] **Step 2: Viết ba test backend đang fail**

Thêm vào `monitor/test_dashboard_backend.py`, cạnh `test_job_journal_marks_state_publish_failure_recovered_by_later_slot`:

```python
_NKD_FAIL_THEN_RECOVER = (
    "2026-08-14 01:00:00  INFO     run_scheduler — [NKD_NIGHT_0200] python -m global_index.run_live_day --clusters nkd\n"
    "2026-08-14 01:00:12  ERROR    run_scheduler — [NKD_NIGHT_0200] exited with code 1\n"
    "2026-08-14 01:30:00  INFO     run_scheduler — [NKD_NIGHT_0230] python -m global_index.run_live_day --clusters nkd\n"
    "2026-08-14 01:30:20  INFO     run_scheduler — [NKD_NIGHT_0230] completed OK\n"
)


def test_failed_decision_job_is_marked_recovered_by_a_later_clean_slot(tmp_path: Path):
    """H1: `lifecycle_status` chỉ được set cho missed+stop_repair. Sáu NKD slot
    failed lúc 02:00-02:25, rồi 02:30 chạy sạch — schedule-status biết là đã
    recover, job-journal thì không, nên Job Journal hiện 6 dòng OPEN vĩnh viễn."""
    (tmp_path / "scheduler_0814.log").write_text(_NKD_FAIL_THEN_RECOVER, encoding="utf-8")
    journal = read_job_journal("2026-08-14", tmp_path)
    failed = [job for job in journal["jobs"] if job["status"] == "failed"]
    assert failed, "fixture must produce a failed job"
    assert failed[0]["lifecycle_status"] == "recovered"
    assert failed[0]["recovered_at"] is not None


def test_failed_job_stays_open_when_nothing_ran_after(tmp_path: Path):
    (tmp_path / "scheduler_0814.log").write_text(
        "2026-08-14 01:00:00  INFO     run_scheduler — [NKD_NIGHT_0200] python -m global_index.run_live_day --clusters nkd\n"
        "2026-08-14 01:00:12  ERROR    run_scheduler — [NKD_NIGHT_0200] exited with code 1\n",
        encoding="utf-8")
    journal = read_job_journal("2026-08-14", tmp_path)
    failed = [job for job in journal["jobs"] if job["status"] == "failed"]
    assert failed[0]["lifecycle_status"] == "open"
    assert failed[0]["recovered_at"] is None


def test_every_unfinished_job_declares_a_lifecycle(tmp_path: Path):
    """Không job failed/missed nào được phép để lifecycle_status là None — đó
    chính là chỗ frontend rơi về mặc định 'chưa recover'."""
    (tmp_path / "scheduler_0814.log").write_text(_NKD_FAIL_THEN_RECOVER, encoding="utf-8")
    for job in read_job_journal("2026-08-14", tmp_path)["jobs"]:
        if job["status"] in {"failed", "missed"}:
            assert job.get("lifecycle_status") in {"open", "recovered"}, job["job_id"]
```

- [ ] **Step 3: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_dashboard_backend.py -k "recovered_by_a_later_clean or stays_open_when_nothing or declares_a_lifecycle" -v
```
Kỳ vọng: 3 failed (`None != 'recovered'`, `KeyError`, `None`).

- [ ] **Step 4: Cài đặt trong `job_journal_reader.py`**

Trong `_annotate_impact_and_action`, ngay sau khối `later_same_stream = next(...)` (kết thúc dòng 126) và **trước** `if "dump_state" in diagnostics`, chèn:

```python
        # Mọi job chưa hoàn tất phải khai báo lifecycle. Trước đây chỉ nhánh
        # missed+stop_repair làm việc này, nên job nkd_night/live_day failed rơi
        # về None và frontend đọc None là "chưa recover" — Job Journal hiện OPEN
        # vĩnh viễn cho những slot mà schedule_status đã biết là đã phục hồi.
        if job["status"] in {"failed", "missed"}:
            job["lifecycle_status"] = "recovered" if later_same_stream else "open"
            job["recovered_at"] = (
                (later_same_stream.get("ended_at") or later_same_stream.get("started_at"))
                if later_same_stream else None
            )
```

Trong nhánh `elif job["status"] == "missed":` → `if job["job_type"] == "stop_repair":`, **xóa** bốn dòng gán đã trở thành thừa (`job["lifecycle_status"] = "recovered"` + `job["recovered_at"] = …` ở dòng 144-145, và `job["lifecycle_status"] = "open"` ở dòng 152), giữ nguyên phần `impact`/`action`.

- [ ] **Step 5: Chạy backend test, xác nhận PASS**

Chạy:
```powershell
python -m pytest monitor/test_dashboard_backend.py -q
```
Kỳ vọng: **baseline + 7**. Các test cũ về `missed_stop_repair_lifecycle_recovers_at_later_sweep` và `job_journal_exposes_confirmed_missed_stop_repair` phải vẫn PASS.

- [ ] **Step 6: Viết hai test frontend đang fail**

Thêm vào `monitor/test_realtime_dom.py`:

```python
RECOVERED_SLOT = {
    "state": "failed", "reason": "exception", "severity": "incident",
    "slot_at": "2026-08-14T06:00:00Z", "slot_id": "NKD_NIGHT_0200",
    "detail": "[NKD_NIGHT_0200] ConnectionRefusedError",
    "lifecycle": "recovered", "recovered_by": "NKD_NIGHT_0230",
}


def test_recovered_schedule_incidents_are_not_shown_as_open(realtime_server, browser_page):
    """H1: rail dùng open_incidents (đúng), Now Monitor dùng incidents (sai),
    nên cùng một màn hình vừa nói 'systems nominal' vừa nói '6 incident OPEN'."""
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
```

- [ ] **Step 7: Chạy để xác nhận FAIL, rồi sửa frontend**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -k "recovered_schedule or open_schedule" -v
```
Kỳ vọng: `test_recovered_schedule_incidents_are_not_shown_as_open` **failed**.

Sửa `realtime.js` dòng 550 — đổi:

```js
    (schedule?.incidents || []).forEach(item => incidents.push({
```

thành:

```js
    // `??` chứ không phải `||`: mảng rỗng là truthy trong JS, nên `[] || incidents`
    // âm thầm rơi về danh sách đầy đủ. Đó chính là lý do panel này hiện incident
    // đã recover như OPEN trong khi rail ngay trên nói nominal.
    (schedule?.open_incidents ?? schedule?.incidents ?? []).forEach(item => incidents.push({
```

Đồng thời đổi dòng tương ứng trong `renderRail` (đã chạm ở T5) sang `??` cho nhất quán:

```js
    const stripScheduleBad = (stripSchedule?.open_incidents ?? stripSchedule?.incidents ?? []).length > 0
```

- [ ] **Step 8: Thêm test nhất quán chéo reader**

Thêm vào `monitor/test_realtime_contract.py`:

```python
def test_readers_agree_on_which_slots_are_open(tmp_path):
    """Ba reader từng cài ba thuật toán recovery khác nhau. Cùng một log phải
    cho cùng một tập 'còn mở'."""
    import datetime as dt
    from monitor.backend.job_journal_reader import read_job_journal
    from monitor.backend.open_issue_reader import read_open_issues
    from monitor.backend import schedule_status

    (tmp_path / "scheduler_0814.log").write_text(
        "2026-08-14 01:00:00  INFO     run_scheduler — [NKD_NIGHT_0200] python -m global_index.run_live_day --clusters nkd\n"
        "2026-08-14 01:00:12  ERROR    run_scheduler — [NKD_NIGHT_0200] exited with code 1\n"
        "2026-08-14 01:30:00  INFO     run_scheduler — [NKD_NIGHT_0230] python -m global_index.run_live_day --clusters nkd\n"
        "2026-08-14 01:30:20  INFO     run_scheduler — [NKD_NIGHT_0230] completed OK\n",
        encoding="utf-8",
    )
    now = dt.datetime(2026, 8, 14, 8, 0, tzinfo=dt.timezone.utc)
    status = schedule_status.get_schedule_status(tmp_path, observed_at=now, now=now)
    journal_open = [job for job in read_job_journal("2026-08-14", tmp_path)["jobs"]
                    if job.get("lifecycle_status") == "open"]
    issues_open = [item for item in read_open_issues(tmp_path)["issues"]
                   if item["status"] == "incident"]

    assert status["open_incidents"] == []
    assert journal_open == []
    assert issues_open == []
```

- [ ] **Step 9: Chạy toàn bộ, xác nhận PASS**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/test_dashboard_backend.py monitor/test_realtime_contract.py monitor/test_realtime_dom.py -q
```
Kỳ vọng: tất cả PASS.

- [ ] **Step 10: Kiểm tra trên dữ liệu thật**

Sau khi user restart backend:
```powershell
curl -s "http://127.0.0.1:5002/api/v1/job-journal/2026-08-14" | python -c "import sys,json,collections; d=json.load(sys.stdin); print(collections.Counter(j.get('lifecycle_status') for j in d['jobs']))"
```
Kỳ vọng: không còn `None` cho job `failed`; 6 slot NKD hiện `recovered`.

- [ ] **Step 11: Ranh giới commit (user tự chạy)**

```bash
git add monitor/backend/job_journal_reader.py global_index/dash/realtime/realtime.js monitor/test_dashboard_backend.py monitor/test_realtime_contract.py monitor/test_realtime_dom.py
git commit -m "fix(monitor): one recovery verdict across schedule, journal, and issue lanes (H1)"
```

---

## Task 7: H3 + H4 — không bịa giờ, không sắp xếp sai giờ

**Files:**
- Modify: `global_index/dash/realtime/realtime.js:62-64` (thêm helper), `:921-933`, `:1085-1121`, `:1285-1287`
- Modify: `global_index/dash/realtime/realtime.css`
- Test: `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `ET_ZONE` (đã có, dòng 72).
- Produces:
  - `etDateTime(iso)` — thay tên `localTime(iso)`, hành vi y nguyên
  - `sortInstant(value) -> number` — epoch millis; chuỗi thiếu offset được coi là ET
  - `decisionTime(value) -> {text: string, exact: boolean}`
  - trường `inexactTime: boolean` trên mỗi row của `journalRows`

- [ ] **Step 1: Viết ba test đang fail**

Thêm vào `monitor/test_realtime_dom.py`:

```python
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


def _journal_events_text(page) -> str:
    page.click('[data-journal-view="events"]')
    page.wait_for_selector("#journal .event-row, #journal .journal-message")
    return page.eval_on_selector("#journal", "el => el.innerText")


def test_entry_without_a_timestamp_is_not_given_a_fake_clock(realtime_server, browser_page):
    """H3: mọi event thiếu timestamp được render '14:05 ET', không phân biệt
    được với giờ thật. Cron 14:10-15:55 tồn tại chính vì entry KHÔNG xảy ra lúc
    14:05 — đây là chỗ bịa giờ gây hại nhất."""
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
    """H4: sortKey trộn '...Z' với chuỗi naive rồi so bằng localeCompare, nên một
    event 14:05 ET (=18:05Z) bị xếp như thể là 14:05 UTC."""
    stub_api(browser_page, {
        "/api/v1/runner-state": _snapshot_with_decision(_decision(entries=[_entry()])),
        "/api/v1/session-events/": _session_events({
            "kind": "market_open_filled", "status": "info", "level": "INFO",
            "category": "TRADE", "inst": "MNQ", "sequence": 1,
            "ts": "2026-08-14T16:00:00Z",  # 12:00 ET — SỚM hơn entry fallback 14:05 ET
            "message": "MNQ open filled",
        }),
    })
    open_realtime(browser_page, realtime_server)
    text = _journal_events_text(browser_page)
    # Journal sắp mới-nhất-trước: entry (14:05 ET) phải đứng TRƯỚC fill (12:00 ET).
    assert text.index("MES") < text.index("MNQ")
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -k "fake_clock or real_entry_time or mixed_timezones" -v
```
Kỳ vọng: `fake_clock` failed (`"14:05" in text`), `mixed_timezones` failed (thứ tự ngược).

- [ ] **Step 3: Thêm helper thời gian**

Trong `realtime.js`, ngay **sau** khai báo `ET_ZONE` (dòng 72) — không đặt trước, vì helper dùng biến đó — thêm:

```js
  // Một chuỗi ISO thiếu offset là giờ ET, KHÔNG phải giờ browser: mọi hằng số
  // lịch trong hệ thống được viết bằng ET. new Date() sẽ hiểu nhầm nó theo múi
  // giờ máy nếu không ép, và máy chạy scheduler ở MDT.
  const etInstant = naiveIso => {
    const asUtc = Date.parse(`${naiveIso}Z`);
    if (Number.isNaN(asUtc)) return 0;
    const shownInEt = Date.parse(new Date(asUtc).toLocaleString('en-US', { timeZone: ET_ZONE }) + 'Z');
    return asUtc + (asUtc - shownInEt);
  };
  const sortInstant = value => {
    if (!value) return 0;
    const text = String(value);
    if (/[Zz]$|[+-]\d{2}:?\d{2}$/.test(text)) return Date.parse(text);
    return etInstant(text);
  };
```

- [ ] **Step 4: Đổi tên `localTime` → `etDateTime`**

`localTime` không format giờ local — nó format ET (L2). Đổi tên tại chỗ khai báo (dòng 62) và mọi chỗ gọi:

```powershell
python -X utf8 -c "from pathlib import Path; p=Path('global_index/dash/realtime/realtime.js'); s=p.read_text(encoding='utf-8'); print('localTime occurrences:', s.count('localTime'))"
```
Sau khi đổi, chạy lại lệnh trên phải in `0`.

- [ ] **Step 5: Bỏ giờ bịa**

Thay `decisionTime` (dòng 931-933) bằng:

```js
  // Trả về cả text lẫn cờ exact. Người vận hành phải phân biệt được "fill lúc
  // 15:40" với "không ghi lại giờ fill" — cron 14:10-15:55 tồn tại chính vì
  // entry không xảy ra lúc 14:05, nên gán 14:05 cho mọi thứ là nói sai.
  function decisionTime(value) {
    return value ? { text: etDateTime(value), exact: true }
                 : { text: 'time not recorded', exact: false };
  }
```

Trong `journalRows`, sửa ba khối decision. Entry:

```js
    (decision.entries || []).forEach(entry => {
      const stamp = decisionTime(entry.entry_time);
      rows.push({
        key: `decision:entry:${entry.inst}:${entry.entry_time || day}`,
        sortKey: entry.entry_time || `${day}T14:05:00`,
        level: entry.is_same_day ? 'warn' : 'info',
        tone: entry.is_same_day ? 'deferred' : 'success',
        category: 'TRADE / ENTRY',
        time: stamp.text, inexactTime: !stamp.exact,
        message: [`Entered ${entry.inst || '--'} ${entry.direction || ''}`.trim(), entry.cluster, entry.risk_sized == null ? '' : `risk ${dollars(entry.risk_sized)}`].filter(Boolean).join(' / ')
      });
    });
```

Exit:

```js
    (decision.exits || []).filter(exit => !loggedExitSymbols.has(rootOf(exit.inst))).forEach(exit => {
      const stamp = decisionTime(exit.exit_time);
      rows.push({
        key: `decision:exit:${exit.inst}:${exit.exit_time || day}`,
        sortKey: exit.exit_time || `${day}T14:05:00`,
        level: Number(exit.pnl || 0) < 0 ? 'warn' : 'info',
        tone: 'success',
        category: 'TRADE / EXIT',
        time: stamp.text, inexactTime: !stamp.exact,
        message: [`Exited ${exit.inst || '--'} ${exit.direction || ''}`.trim(), tradeMoney(exit.pnl), exitType(exit.exit_reason, 'SIGNAL').label].filter(Boolean).join(' / ')
      });
    });
```

Rejected (dòng 1103-1111) — đổi `time: '14:05 ET'` thành `time: 'time not recorded', inexactTime: true`. Halted (dòng 1112-1120) — đổi tương tự. `sortKey` của cả hai vẫn giữ `${day}T14:05:00`: đó là vị trí sắp xếp hợp lý (slot quyết định), chỉ **không được hiển thị như giờ**.

- [ ] **Step 6: Sửa sắp xếp và hiển thị INCURRED**

Đổi dòng cuối `journalRows` (dòng 1121):

```js
    // So theo thời điểm tuyệt đối. localeCompare trên chuỗi trộn '...Z' với chuỗi
    // naive xếp một event 14:05 ET (=18:05Z) như thể nó là 14:05 UTC.
    return rows.sort((a, b) => sortInstant(b.sortKey) - sortInstant(a.sortKey)
      || Number(b.sequence || 0) - Number(a.sequence || 0));
```

Trong `renderEventJournal`, khối INCURRED (dòng 1287) — đổi `etDateTime(row.incurredAt || row.sortKey)` thành `row.incurredAt ? etDateTime(row.incurredAt) : row.time`, để `sortKey` nội bộ không bao giờ được format lại như thể là dữ liệu.

Dòng 1285 — gắn class cho giờ không chính xác:

```js
          <div class="journal-meta"><span>${esc(row.category)}</span><time class="${row.inexactTime ? 'inexact' : ''}">${esc(row.time)}</time></div>
```

- [ ] **Step 7: Thêm style**

Thêm vào `realtime.css` (dùng biến màu phụ đã có trong file — kiểm tra tên bằng lệnh ở T5 Step 6):

```css
.journal-meta time.inexact { color: var(--amber); font-style: italic; }
```

- [ ] **Step 8: Chạy test, xác nhận PASS**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/test_realtime_dom.py -q
```
Kỳ vọng: toàn bộ PASS.

- [ ] **Step 9: Ranh giới commit (user tự chạy)**

```bash
git add global_index/dash/realtime/realtime.js global_index/dash/realtime/realtime.css monitor/test_realtime_dom.py
git commit -m "fix(realtime): stop fabricating 14:05 ET and sort the journal by real instant (H3, H4, L2)"
```

---

## Task 8: H2 + M5 — metric không được nói quá điều đã đo

**Files:**
- Modify: `global_index/dash/realtime/realtime.js:4` (hằng số), `:244-251`, `:300-317`
- Test: `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `state.runner.payload.snapshots` (đếm độ dài để suy cỡ mẫu).
- Produces: `MIN_METRIC_DAYS: number = 20`.

- [ ] **Step 1: Viết ba test đang fail**

Thêm vào `monitor/test_realtime_dom.py`:

```python
def _runner_with_metrics(days: int, metrics: dict) -> dict:
    payload = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    base = payload["payload"]["snapshots"][0]
    payload["payload"]["snapshots"] = [
        dict(json.loads(json.dumps(base)), date=f"2026-08-{day:02d}")
        for day in range(1, days + 1)
    ]
    payload["payload"]["snapshots"][-1]["running_metrics"] = metrics
    return payload


def test_sharpe_is_withheld_below_the_sample_floor(realtime_server, browser_page):
    """H2: Sharpe 10.21 từ 4 quan sát ngày hiển thị ngang hàng drawdown thật.
    Chuỗi đo trong paper đi 26.96 -> 14.87 -> 11.85 -> 10.21, tức phân rã theo
    1/sqrt(n). Calmar đã bị chặn đúng cách khi thiếu lịch sử; Sharpe thì không."""
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
    """M5: màu chỉ dựa trên completed==attempts, bỏ qua non_convergence_count.
    22/22 fit cảnh báo mà ô vẫn xanh — màu của 'không cần nhìn'."""
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
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -k "sharpe or hmm_fit" -v
```
Kỳ vọng: `withheld_below_the_sample_floor` failed (`"10.21" != "--"`), `not_green_while_every_fit_warns` failed (`className == "positive"`).

- [ ] **Step 3: Cài đặt sample floor**

Thêm hằng số ngay sau `const POLL_MS = 8000;` (dòng 4):

```js
  // Sharpe/Calmar dưới ngưỡng này chỉ đang đo chính cỡ mẫu của nó.
  const MIN_METRIC_DAYS = 20;
```

Trong `renderMetrics`, sau `const running = snap?.running_metrics || {};`, thêm:

```js
    const sampleDays = (state.runner?.payload?.snapshots || []).length;
    const enoughSample = sampleDays >= MIN_METRIC_DAYS;
    const sampleNote = `n=${sampleDays} trading day(s); needs ${MIN_METRIC_DAYS}`;
```

Thay hai dòng render Calmar/Sharpe (dòng 313-314) bằng:

```js
    performanceValue('performanceCalmar', enoughSample && running.calmar != null ? Number(running.calmar).toFixed(2) : '--');
    performanceValue('performanceSharpe', enoughSample && running.sharpe != null ? Number(running.sharpe).toFixed(2) : '--', enoughSample ? running.sharpe : null);
    $('performanceCalmar').title = enoughSample ? '' : sampleNote;
    $('performanceSharpe').title = enoughSample ? '' : sampleNote;
```

- [ ] **Step 4: Sửa màu HMM fit**

Thay khối dòng 246-251 bằng:

```js
    const fitWarnings = Number(fitDiagnostic?.non_convergence_count || 0);
    $('modelFitStatus').textContent = fitDiagnostic
      ? `${fitDiagnostic.completed_fits}/${fitDiagnostic.attempts} complete${fitWarnings ? ` · ${fitWarnings} warn` : ''}`
      : 'Not observed';
    // Xanh là màu của "không cần nhìn". 22/22 fit không hội tụ trên một model 20
    // tháng tuổi không phải thứ đó, kể cả khi backend phân loại là diagnostic.
    $('modelFitStatus').className = !fitDiagnostic ? 'warning'
      : (fitDiagnostic.completed_fits === fitDiagnostic.attempts && fitWarnings === 0) ? 'positive'
      : 'warning';
    $('modelFitStatus').title = fitDiagnostic
      ? `${fitWarnings} convergence warning(s) · no documented gate failure`
      : 'No retained fit evidence';
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/test_realtime_dom.py -q
```

- [ ] **Step 6: Ranh giới commit (user tự chạy)**

```bash
git add global_index/dash/realtime/realtime.js monitor/test_realtime_dom.py
git commit -m "fix(realtime): gate Sharpe on sample size and stop greenlighting warned HMM fits (H2, M5)"
```

---

## Task 9: M1 + M2 + M6 — kiểm chứng bảo vệ position cho đúng

Ba finding này chạm cùng một cụm helper (`runnerFor`, `stopsFor`, `validStopsFor`, `metricStopsCovered`). Một reviewer sẽ nhận hoặc từ chối cả cụm, nên chúng đi chung một task.

**Files:**
- Modify: `global_index/dash/realtime/realtime.js:123-169`, `:296-299`, `:391-404`, `:573-618`
- Modify: `global_index/dash/realtime/index.html:88`
- Test: `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `contract_specs[root].tick` từ payload broker (đã có, ví dụ `M2K.tick = 0.1`).
- Produces:
  - `runnersFor(brokerPos) -> Array` (thay chỗ cần tổng hợp); `runnerFor` giữ nguyên tên, trả `runnersFor(...)[0] || null`
  - `expectedQuantity(brokerPos) -> number | null` — tổng contracts của mọi runner position khớp
  - `tickFor(brokerPos) -> number | null`
  - `stopPriceAgrees(order, brokerPos) -> boolean`
  - `protectionSummary() -> {covered, deferred, naked, total}`
  - `STOP_TICK_TOLERANCE: number = 4`

- [ ] **Step 1: Viết bốn test đang fail**

Thêm vào `monitor/test_realtime_dom.py`:

```python
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


def _good_stop(**over) -> dict:
    order = {"inst": "M2KU6", "type": "STP", "action": "SELL", "qty": 1.0,
             "aux_price": 3020.2, "lmt_price": 0.0, "status": "PreSubmitted",
             "tif": "GTC", "order_id": 288}
    order.update(over)
    return order


def test_stop_at_the_wrong_price_is_not_counted_as_protection(realtime_server, browser_page):
    """M1: validStopsFor chỉ kiểm action/qty/status. Một SELL STP đặt TRÊN giá
    thị trường cho vị thế LONG vẫn render 'Protected' xanh."""
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
    """3020.2 vs plan 3020.24 là làm tròn tick (M2K tick=0.1), không phải lỗi."""
    stub_api(browser_page, {
        "/api/v1/broker": _broker([M2K_POS], [_good_stop()]),
        "/api/v1/runner-state": _runner_positions(M2K_RUNNER),
    })
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector(
        "#metricStopsCovered", "el => el.textContent").startswith("1")


def test_two_clusters_on_one_contract_reconcile_by_total(realtime_server, browser_page):
    """M2: IBKR net thành một dòng. runnerFor trả phần tử đầu, nên swing+stress
    cùng giữ M2K sinh false 'size mismatch' VÀ đánh cả hai stop hợp lệ là invalid."""
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
    """M6: header đếm covered mà bỏ qua deferred; rail thì loại trừ deferred.
    Một position deferred hợp lệ hiện '0 / 1' trong khi rail nói nominal."""
    stub_api(browser_page, {
        "/api/v1/broker": _broker([M2K_POS], []),
        "/api/v1/runner-state": _runner_positions(dict(M2K_RUNNER, stop_deferred=True,
                                                       stop_order_id=None)),
    })
    open_realtime(browser_page, realtime_server)
    covered = browser_page.eval_on_selector("#metricStopsCovered", "el => el.textContent")
    assert "deferred" in covered.lower()
    assert "nominal" in rail_text(browser_page).lower()
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -k "wrong_price or tick_tolerance or two_clusters or deferred_stop" -v
```
Kỳ vọng: 3 failed (`wrong_price`, `two_clusters`, `deferred_stop`); `tick_tolerance` PASS sẵn — nó khóa hành vi đúng hiện có để bản sửa không phá.

- [ ] **Step 3: Thay cụm helper**

Trong `realtime.js`, thay khối dòng 123-169 bằng:

```js
  const runnersFor = brokerPos => runnerPositions().filter(pos =>
    rootOf(pos.inst) === rootOf(brokerPos.inst) && String(pos.direction).toUpperCase() === brokerDirection(brokerPos.position)
  );
  // Giữ lại cho các chỗ chỉ cần một đại diện (nhãn cluster, entry price trên card).
  const runnerFor = brokerPos => runnersFor(brokerPos)[0] || null;
  const persistedRunnerFor = pos => (state.runnerPositions?.payload?.positions || []).find(saved => {
    const samePrice = Number.isFinite(Number(pos?.entry_price)) && Number.isFinite(Number(saved?.entry_price))
      && Math.abs(Number(pos.entry_price) - Number(saved.entry_price)) < 1e-8;
    return rootOf(saved.inst) === rootOf(pos?.inst)
      && String(saved.direction || '').toUpperCase() === String(pos?.direction || '').toUpperCase()
      && String(saved.cluster || '') === String(pos?.cluster || '')
      && String(saved.entry_day || '').slice(0, 10) === String(pos?.entry_day || '').slice(0, 10)
      && samePrice
      && String(saved.stop_order_id ?? '') === String(pos?.stop_order_id ?? '');
  });
  const runnerQuantity = pos => {
    for (const value of [pos?.contracts, pos?.qty, pos?.position]) {
      if (value != null && Number.isFinite(Number(value))) return Math.abs(Number(value));
    }
    const persisted = persistedRunnerFor(pos);
    if (persisted?.contracts != null && Number.isFinite(Number(persisted.contracts)) && Number(persisted.contracts) > 0) {
      return Math.abs(Number(persisted.contracts));
    }
    return null;
  };
  // IBKR net mọi cluster thành một dòng cho mỗi contract; runner giữ chúng riêng
  // (roska4_swing và roska4_stress có thể cùng nắm một micro). So một-đối-một sinh
  // false "size mismatch" và đánh cả hai stop hợp lệ là invalid.
  const expectedQuantity = brokerPos => {
    const quantities = runnersFor(brokerPos).map(runnerQuantity);
    if (!quantities.length || quantities.some(value => value == null)) return null;
    return quantities.reduce((total, value) => total + value, 0);
  };
  const stopsFor = brokerPos => stopOrders().filter(order => contractKey(order.inst) === contractKey(brokerPos.inst));
  const expectedStopAction = brokerPos => Number(brokerPos.position) > 0 ? 'SELL' : 'BUY';
  const stopFieldsKnown = order => order.action != null && order.qty != null && Number.isFinite(Number(order.qty)) && order.status != null && order.status !== '?';
  const tickFor = brokerPos => {
    const spec = (state.broker?.payload?.contract_specs || {})[rootOf(brokerPos.inst)];
    const tick = Number(spec?.tick);
    return Number.isFinite(tick) && tick > 0 ? tick : null;
  };
  // Action + qty + status không nói gì về việc stop có nằm đúng chỗ không. Một SELL
  // STP trên giá thị trường cho vị thế LONG thỏa cả ba mà không bảo vệ gì cả.
  const STOP_TICK_TOLERANCE = 4;
  const stopPriceAgrees = (order, brokerPos) => {
    const aux = Number(order.aux_price);
    if (!Number.isFinite(aux)) return false;
    const last = Number(brokerPos.market_price);
    if (Number.isFinite(last)) {
      const long = Number(brokerPos.position) > 0;
      if (long ? aux >= last : aux <= last) return false;
    }
    const plans = runnersFor(brokerPos).map(pos => Number(pos.stop_price)).filter(Number.isFinite);
    if (!plans.length) return true;              // không có plan để so — không kết tội
    const tick = tickFor(brokerPos);
    if (tick == null) return true;               // không biết tick — không kết tội
    return plans.some(plan => Math.abs(aux - plan) <= STOP_TICK_TOLERANCE * tick);
  };
  const validStopsFor = brokerPos => {
    const candidates = stopsFor(brokerPos).filter(order =>
      stopFieldsKnown(order)
      && String(order.action).toUpperCase() === expectedStopAction(brokerPos)
      && liveStopStatuses.has(String(order.status).toUpperCase())
      && stopPriceAgrees(order, brokerPos)
    );
    // Tổng số lượng, không phải khớp từng lệnh: hai stop x1 bảo vệ đủ một position x2.
    const needed = Math.abs(Number(brokerPos.position));
    const covered = candidates.reduce((total, order) => total + Math.abs(Number(order.qty)), 0);
    return covered >= needed ? candidates : [];
  };
  const invalidStopsFor = brokerPos => {
    const valid = validStopsFor(brokerPos);
    return stopsFor(brokerPos).filter(order => stopFieldsKnown(order) && !valid.includes(order));
  };
  const unknownStopsFor = brokerPos => stopsFor(brokerPos).filter(order => !stopFieldsKnown(order));
  const orphanStops = () => stopOrders().filter(order =>
    !brokerPositions().some(pos => contractKey(pos.inst) === contractKey(order.inst))
  );
  const runnerOnly = () => runnerPositions().filter(pos =>
    !brokerPositions().some(live => rootOf(live.inst) === rootOf(pos.inst) && brokerDirection(live.position) === String(pos.direction).toUpperCase())
  );
  const protectionSummary = () => brokerPositions().reduce((acc, pos) => {
    acc.total += 1;
    if (validStopsFor(pos).length) acc.covered += 1;
    else if (runnersFor(pos).some(runner => runner.stop_deferred)) acc.deferred += 1;
    else acc.naked += 1;
    return acc;
  }, { covered: 0, deferred: 0, naked: 0, total: 0 });
  const brokerPositionsMatchNow = () => brokerUsable()
    && runnerOnly().length === 0
    && brokerPositions().every(pos => {
      const quantity = expectedQuantity(pos);
      return quantity != null && quantity === Math.abs(Number(pos.position));
    });
```

- [ ] **Step 4: Dùng helper mới ở chỗ tiêu thụ**

`renderMetrics` — thay dòng 296-299:

```js
    const protection = brokerUsable() ? protectionSummary() : null;
    $('metricStopsCovered').textContent = protection == null ? '--'
      : protection.total === 0 ? 'no positions'
      : [`${protection.covered} covered`,
         protection.deferred ? `${protection.deferred} deferred` : null,
         protection.naked ? `${protection.naked} naked` : null].filter(Boolean).join(' / ');
```

`index.html` dòng 88 — đổi nhãn và tooltip cho khớp ngữ nghĩa mới:

```html
        <div class="broker-derived"><span class="has-tip tip-right tip-bottom" tabindex="0" data-tooltip="Covered = a live stop with the right side, a sane price, and enough total quantity. Deferred = protection intentionally delayed by rule. Naked = neither.">Protection</span><b id="metricStopsCovered">--</b></div>
```

`renderMonitor` — đổi điều kiện unprotected (dòng 581):

```js
        if (runnersFor(pos).length && !runnersFor(pos).some(item => item.stop_deferred) && !stopsFor(pos).length) incidents.push({
```

và khối size mismatch (dòng 610-617):

```js
        const expectedQty = expectedQuantity(pos);
        if (expectedQty != null && expectedQty !== Math.abs(Number(pos.position))) incidents.push({
          key: `broker:size:${pos.inst}`, status: 'incident', component: 'broker', title: `${pos.inst} size mismatch`,
          problem: `IBKR holds x${Math.abs(Number(pos.position))}, while runner intent totals x${expectedQty} across ${runnersFor(pos).length} cluster(s).`,
          impact: 'Protection and exposure calculations may target the wrong quantity.',
          action: 'Reconcile broker quantity with persisted runner intent and working stop quantity.',
          evidence: `${pos.inst} broker x${Math.abs(Number(pos.position))} / runner x${expectedQty}`
        });
```

`renderRail` — đổi `stripUnprotected` (dòng 391-394) và `stripSizeProblem` (dòng 400-404):

```js
    const stripUnprotected = stripBrokerKnown ? brokerPositions().filter(position =>
      !stopsFor(position).length
      && runnersFor(position).length
      && !runnersFor(position).some(runner => runner.stop_deferred)) : [];
    const stripSizeProblem = stripBrokerKnown && brokerPositions().some(position => {
      const quantity = expectedQuantity(position);
      return runnersFor(position).length && quantity !== Math.abs(Number(position.position));
    });
```

- [ ] **Step 5: Chạy test, xác nhận PASS**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/test_realtime_dom.py -q
```
Kỳ vọng: toàn bộ PASS.

- [ ] **Step 6: Kiểm tra không hồi quy trên dữ liệu thật**

Mở `http://127.0.0.1:5002/realtime?bust=verify-t9` (sau khi user restart backend) và xác nhận: position M2K vẫn hiện `PROTECTED #288`, ô Protection hiện `1 covered`. Nếu nó chuyển thành `naked`, tolerance tick sai — kiểm tra `contract_specs.M2K.tick` có mặt trong payload broker và `rootOf('M2KU6')` trả `'M2K'`.

- [ ] **Step 7: Ranh giới commit (user tự chạy)**

```bash
git add global_index/dash/realtime/realtime.js global_index/dash/realtime/index.html monitor/test_realtime_dom.py
git commit -m "fix(realtime): verify stop price, aggregate multi-cluster quantity, split protection states (M1, M2, M6)"
```

---

## Task 10: M3 — khóa khớp position phải ổn định

**Files:**
- Modify: `global_index/dash/realtime/realtime.js` (hàm `persistedRunnerFor`, đã đặt lại ở T9)
- Test: `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `rootOf`, `runnersFor` từ T9.
- Produces: `positionKey(pos) -> string` — `inst|cluster|direction|entry_day`; `persistedRunnerFor` khớp bằng khóa này.

- [ ] **Step 1: Viết test đang fail**

Thêm vào `monitor/test_realtime_dom.py`:

```python
def test_quantity_survives_a_ratcheted_stop_id(realtime_server, browser_page):
    """M3: persistedRunnerFor đòi khớp đồng thời 6 trường, gồm float equality
    trên entry_price VÀ stop_order_id. Runner ratchet stop -> id mới trong
    live_positions.json trong khi snapshot chưa được ghi lại -> qty rơi về null,
    kéo theo telemetry gap và 'Position match: size unknown'."""
    persisted = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-positions"]))
    persisted["payload"]["positions"] = [{
        "inst": "M2K", "cluster": "roska4_swing", "direction": "LONG",
        "contracts": 1, "entry_day": "2026-08-10 00:00:00", "entry_price": 3025.3,
        "stop_price": 3022.10, "stop_order_id": "301",   # ratchet: id mới
    }]
    stub_api(browser_page, {
        "/api/v1/broker": _broker([M2K_POS], [_good_stop(order_id=301, aux_price=3022.1)]),
        # snapshot chưa được ghi lại: vẫn mang id cũ và không có contracts
        "/api/v1/runner-state": _runner_positions(dict(M2K_RUNNER, contracts=None)),
        "/api/v1/runner-positions": persisted,
    })
    open_realtime(browser_page, realtime_server)
    monitor = browser_page.eval_on_selector("#nowMonitorList", "el => el.innerText").lower()
    assert "quantity missing" not in monitor
    assert "size mismatch" not in monitor
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -k "ratcheted_stop_id" -v
```
Kỳ vọng: failed — `"quantity missing"` xuất hiện trong Now Monitor.

- [ ] **Step 3: Đổi khóa khớp**

Thay `persistedRunnerFor` (đặt ở T9 Step 3) bằng:

```js
  // Khóa ổn định: một position được định danh bởi instrument + cluster + hướng +
  // ngày vào. entry_price (so bằng float equality) và stop_order_id đều THAY ĐỔI
  // hoặc lệch giữa hai file được ghi ở hai nhịp khác nhau (live_positions.json vs
  // live_state_data.js) — dùng chúng làm điều kiện khớp biến một stop ratchet
  // bình thường thành "runner quantity missing".
  const positionKey = pos => [
    rootOf(pos?.inst),
    String(pos?.cluster || ''),
    String(pos?.direction || '').toUpperCase(),
    String(pos?.entry_day || '').slice(0, 10)
  ].join('|');
  const persistedRunnerFor = pos => (state.runnerPositions?.payload?.positions || [])
    .find(saved => positionKey(saved) === positionKey(pos));
```

- [ ] **Step 4: Chạy test, xác nhận PASS**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/test_realtime_dom.py -q
```
Kỳ vọng: toàn bộ PASS, kể cả `test_two_clusters_on_one_contract_reconcile_by_total` — hai cluster có `positionKey` khác nhau nên vẫn khớp riêng biệt, không trộn số lượng.

- [ ] **Step 5: Ranh giới commit (user tự chạy)**

```bash
git add global_index/dash/realtime/realtime.js monitor/test_realtime_dom.py
git commit -m "fix(realtime): match persisted positions on a stable key, not float price and stop id (M3)"
```

---

## Task 11: M4 + M7 + M8 — trung thực về nguồn, phạm vi, và lỗi

> **Ưu tiên đã đổi (2026-08-14): M4 nâng lên HIGH và trở thành blocker.** Phần backend
> của task này (M7) đã xong. Phần **M4 frontend** — dòng broker equity + delta vs
> `paper_start` — giờ là điều kiện "phải sửa trước khi rely", không còn là "nên sửa sớm".
> Lý do: bug định tuyến `MNKD` sang full-size `NKD` làm broker realised −$1,400 trong khi
> sleeve ledger book −$140 (10.0000×); sai multiplier không làm lệch giá vào/ra nên **không**
> panel ledger-based nào bắt được — chỉ khoảng chênh với broker mới lộ. Nếu phải chọn thứ
> tự, làm M4 trước T9/T10.

**Files:**
- Modify: `monitor/backend/open_issue_reader.py:172-176`, `:297-301`
- Modify: `global_index/dash/realtime/index.html:44-48`
- Modify: `global_index/dash/realtime/realtime.js:309-316`, `:423-432`, `:679-681`
- Modify: `global_index/dash/realtime/realtime.css`
- Test: `monitor/test_dashboard_backend.py`, `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `meta.broker_equity`, `meta.paper_start` (đã có trong payload runner-state, không cần đổi runner).
- Produces: `coverage` thêm hai khóa `evidence_ends: str` và `stale_days: int`.

- [ ] **Step 1: Viết test backend đang fail**

Thêm vào `monitor/test_dashboard_backend.py`:

```python
def test_coverage_reports_where_evidence_actually_ends(tmp_path: Path):
    """M7: coverage.to = max(dong log cuoi, hom nay), nên UI luôn quảng cáo
    'evidence … to <hôm nay>' kể cả khi scheduler chết từ nhiều ngày trước."""
    (tmp_path / "scheduler_0801.log").write_text(
        "2026-08-01 10:00:00  INFO     run_scheduler — [HEARTBEAT] ALIVE\n",
        encoding="utf-8")
    coverage = read_open_issues(tmp_path)["coverage"]
    assert coverage["evidence_ends"] == "2026-08-01"
    assert coverage["stale_days"] >= 1
```

- [ ] **Step 2: Chạy để xác nhận FAIL, rồi sửa backend**

Chạy:
```powershell
python -m pytest monitor/test_dashboard_backend.py -k "coverage_reports_where" -v
```
Kỳ vọng: `KeyError: 'evidence_ends'`.

Trong `open_issue_reader._build`, thay dòng 173-174 bằng:

```python
    first_day = stamped_lines[0][0].astimezone(ET).date()
    evidence_ends = stamped_lines[-1][0].astimezone(ET).date()
    today = dt.datetime.now(ET).date()
    # Quét phải chạy tới hôm nay để bắt slot missed, nhưng phạm vi BẰNG CHỨNG dừng
    # ở dòng log cuối cùng. Trộn hai thứ này khiến UI hứa hẹn evidence không có.
    last_day = max(evidence_ends, today)
```

và trong dict trả về (dòng 297-301), thay khóa `coverage`:

```python
        "coverage": {"from": first_day.isoformat(), "to": last_day.isoformat(),
                     "evidence_ends": evidence_ends.isoformat(),
                     "stale_days": (today - evidence_ends).days},
```

- [ ] **Step 3: Viết ba test frontend đang fail**

Thêm vào `monitor/test_realtime_dom.py`:

```python
def test_open_issue_source_admits_stale_evidence(realtime_server, browser_page):
    issues = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/open-issues"]))
    issues["coverage"] = {"from": "2026-07-30", "to": "2026-08-14",
                          "evidence_ends": "2026-08-10", "stale_days": 4}
    stub_api(browser_page, {"/api/v1/open-issues": issues})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#openIssuesSource", "el => el.textContent")
    assert "2026-08-10" in text
    assert "4 day" in text


def test_broker_account_delta_is_visible(realtime_server, browser_page):
    """M4: meta.broker_equity và meta.paper_start có trong payload nhưng không
    render ở đâu. Header nói '+$229' trong khi tài khoản paper thật -$4,168."""
    runner = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    runner["payload"]["meta"]["broker_equity"] = 996311.98
    runner["payload"]["meta"]["paper_start"] = {"date": "2026-07-08", "equity": 1000480.0}
    stub_api(browser_page, {"/api/v1/runner-state": runner})
    open_realtime(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#brokerAccountContext", "el => el.textContent")
    assert "996,312" in text
    assert "4,168" in text


def test_a_failed_source_is_named_in_words(realtime_server, browser_page):
    """M8: fatalBanner chỉ bật khi cả 5 endpoint fail; fail lẻ chỉ được báo bằng
    opacity .42, không có chữ nào, không nói nguồn nào hỏng."""
    stub_api(browser_page)
    browser_page.route(
        "**/api/v1/runner-state",
        lambda route: route.fulfill(status=500, content_type="application/json",
                                    body='{"error": "boom"}'))
    browser_page.goto(f"{realtime_server}/realtime", wait_until="domcontentloaded")
    browser_page.wait_for_selector("#statusRail .system-conclusion", timeout=10_000)
    assert "runner-state" in rail_text(browser_page).lower()
```

- [ ] **Step 4: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_dom.py -k "stale_evidence or account_delta or failed_source" -v
```
Kỳ vọng: 3 failed.

- [ ] **Step 5: Thêm dòng Broker account**

`index.html` — thêm ngay sau dòng 47 (trong `equity-zone`):

```html
        <small class="broker-account-line has-tip tip-bottom" tabindex="0" data-tooltip="The IBKR paper account's own equity, shown for context only. The runner ledger above is realised-only and re-anchors at the system epoch; the two are not the same number and are not meant to reconcile here."><span id="brokerAccountContext">--</span> <a href="/paper">Paper reconcile</a></small>
```

`realtime.js` — trong `renderMetrics`, sau khối `performanceValue('performanceMaxDd', …)`, thêm:

```js
    const brokerEquity = Number(meta.broker_equity);
    const paperStart = Number(meta.paper_start?.equity);
    $('brokerAccountContext').textContent = Number.isFinite(brokerEquity)
      ? `Broker acct ${dollars(brokerEquity)}${Number.isFinite(paperStart)
          ? ` · ${money(brokerEquity - paperStart)} since ${sessionDate(meta.paper_start?.date)}` : ''}`
      : 'Broker acct unavailable';
    $('brokerAccountContext').className = Number.isFinite(brokerEquity) && Number.isFinite(paperStart)
      && brokerEquity < paperStart ? 'negative' : '';
```

Thêm vào `realtime.css`:

```css
.broker-account-line { display: block; margin-top: 4px; opacity: .8; }
.broker-account-line .negative { color: var(--red); }
```

- [ ] **Step 6: Coverage trung thực**

`renderOpenIssues` — thay dòng 679-681:

```js
    const staleDays = Number(coverage?.stale_days || 0);
    $('openIssuesSource').textContent = coverage
      ? `${issues.length} open / evidence ${coverage.from} to ${coverage.evidence_ends || coverage.to}${staleDays > 0 ? ` (ends ${staleDays} day${staleDays === 1 ? '' : 's'} ago)` : ''}`
      : data?.error || 'Evidence coverage unavailable';
    $('openIssuesSource').className = `source-note has-tip tip-right${staleDays > 0 ? ' warning' : ''}`;
```

- [ ] **Step 7: Gọi tên nguồn hỏng**

`renderRail` — thêm ngay **sau** các `stripConditions.push(...)` hiện có và **trước** `const stripStatus = …`:

```js
    // Một nguồn hỏng lẻ trước đây chỉ được báo bằng opacity .42, không có chữ nào
    // và không nói nguồn nào. Payload cũ vẫn tiếp tục render như số hiện tại.
    const stripDeadSources = [
      ['runner-state', state.runner?.error],
      ['broker', state.broker?.error],
      ['schedule', state.schedule?.error],
      ['open-issues', state.openIssues?.error],
      ['runner-positions', state.runnerPositions?.error]
    ].filter(([, error]) => error).map(([name]) => name);
    if (stripDeadSources.length) stripConditions.push(`${stripDeadSources.join(', ')} unreachable`);
```

và thêm `|| stripDeadSources.length` vào biểu thức `stripLevel` — chú ý `stripLevel` hiện được khai báo **trước** `stripConditions`, nên phải chuyển khai báo `stripDeadSources` lên trên `stripLevel` và giữ dòng `push` ở dưới:

```js
    const stripLevel = stripScheduleBad || stripSafetyCount || stripReconcileBad || stripBreakerBad || stripDeadSources.length
      ? 'bad' : stripUnknown ? 'watch' : 'ok';
```

- [ ] **Step 8: Chạy test, xác nhận PASS**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/test_dashboard_backend.py monitor/test_realtime_dom.py -q
```
Kỳ vọng: toàn bộ PASS, kể cả hai test overflow — dòng mới trong `equity-zone` không được làm tràn ở 390px.

- [ ] **Step 9: Ranh giới commit (user tự chạy)**

```bash
git add monitor/backend/open_issue_reader.py global_index/dash/realtime/index.html global_index/dash/realtime/realtime.js global_index/dash/realtime/realtime.css monitor/test_dashboard_backend.py monitor/test_realtime_dom.py
git commit -m "fix(monitor): broker account delta, honest evidence coverage, named source failures (M4, M7, M8)"
```

---

## Task 12: L1, L3–L6 — dọn dẹp và khóa bất biến

**Files:**
- Modify: `global_index/dash/realtime/realtime.js` (xóa `renderRailLegacy`, `railItem`, `railTips`; sửa mobile open-issues)
- Modify: `global_index/dash/realtime/realtime.css` (xóa `.scheduler-health*`)
- Modify: `monitor/backend/app.py` (route favicon)
- Modify: `docs/futures/OPEN_QUESTIONS.md` (ghi L6)
- Test: `monitor/test_realtime_contract.py`, `monitor/test_realtime_dom.py`

**Interfaces:**
- Consumes: `_realtime_sources()` từ T1.
- Produces: route `GET /favicon.ico` trả 204.

- [ ] **Step 1: Viết test đang fail**

Thêm vào `monitor/test_realtime_contract.py`:

```python
def test_no_dead_render_functions_remain():
    """L1: renderRailLegacy + railItem + railTips không được gọi ở đâu. Chúng
    khai báo 9 chỉ báo (Stop protection, Position match, Risk breaker…) khiến
    người đọc code tưởng rail vẫn hiển thị chúng — rail thật có 0 mục."""
    js, _ = _realtime_sources()
    for name in ("renderRailLegacy", "railItem", "railTips"):
        assert js.count(name) == 0, f"{name} is still present but never called"


def test_no_orphan_scheduler_health_css():
    css = (REALTIME / "realtime.css").read_text(encoding="utf-8")
    assert ".scheduler-health" not in css


def test_realtime_page_has_no_write_surface():
    """Bất biến an toàn: trang này là read-only — 0 form, 0 nút lệnh, 0 control
    restart/up/down. Khóa lại bằng test để không ai vô tình thêm nút gây tác
    động broker/runner; thao tác vận hành thật thuộc về monitor/ops.py."""
    js, html = _realtime_sources()
    for verb in ("'POST'", '"POST"', "'PUT'", '"PUT"', "'DELETE'", '"DELETE"'):
        assert verb not in js, f"realtime.js issues a {verb} request"
    assert "<form" not in html.lower()


def test_realtime_never_renders_the_percent_unit_breaker_field():
    """L6: operational_status.breaker.dd_pct dùng đơn vị phần trăm (0.086) trong
    khi snapshot.drawdown_pct dùng phân số (0.00086). Sửa nguồn = sửa
    global_index/runner.py, ngoài phạm vi plan này; ít nhất khóa lại việc
    frontend không được đọc nhầm nó qua pct()."""
    js, _ = _realtime_sources()
    assert "pct(ops.breaker" not in js
    assert "breaker?.dd_pct" not in js
```

Thêm vào `monitor/test_realtime_dom.py`:

```python
def test_open_issues_stay_expanded_on_mobile(realtime_server, browser_page):
    """L4: openIssuesShell.open = !compactIssueMedia.matches, nên trên mobile
    issue duy nhất đang mở bị giấu sau <details>."""
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
    stub_api(browser_page, {"/api/v1/open-issues": issues})
    open_realtime(browser_page, realtime_server)
    assert browser_page.eval_on_selector("#openIssuesShell", "el => el.open") is True


def test_favicon_does_not_404(realtime_server, browser_page):
    response = browser_page.request.get(f"{realtime_server}/favicon.ico")
    assert response.status in (200, 204)
```

- [ ] **Step 2: Chạy để xác nhận FAIL**

Chạy:
```powershell
python -m pytest monitor/test_realtime_contract.py monitor/test_realtime_dom.py -k "dead_render or orphan_scheduler or write_surface or percent_unit or expanded_on_mobile or favicon" -v
```
Kỳ vọng: `dead_render`, `orphan_scheduler`, `expanded_on_mobile`, `favicon` failed; `write_surface` và `percent_unit` PASS sẵn (bất biến hiện đã đúng — hai test này khóa chúng lại).

- [ ] **Step 3: Xóa dead code**

Trong `realtime.js` xóa: hàm `renderRailLegacy` (toàn bộ), hàm `railItem`, hằng `railTips`.

Xác nhận:
```powershell
rg -n "renderRailLegacy|railItem|railTips" global_index/dash/realtime/
```
Kỳ vọng: không có kết quả.

Trong `realtime.css`, xóa khối `.scheduler-health*` (4 dòng).

- [ ] **Step 4: Mobile — mở Open Issues khi có issue**

Trong `renderOpenIssues`, thay:

```js
    if (state.issuesSectionOpen === null) state.issuesSectionOpen = !compactIssueMedia.matches;
    $('openIssuesShell').open = state.issuesSectionOpen;
```

bằng:

```js
    // Trên mobile section này từng đóng mặc định, giấu luôn issue duy nhất đang
    // mở sau một <details>. Thu gọn chỉ hợp lý khi không có gì để xem.
    if (state.issuesSectionOpen === null) state.issuesSectionOpen = issues.length > 0 || !compactIssueMedia.matches;
    $('openIssuesShell').open = state.issuesSectionOpen || issues.length > 0;
```

Trong handler `compactIssueMedia.addEventListener('change', …)`, thay:

```js
    state.issuesSectionOpen = !event.matches;
```

bằng:

```js
    state.issuesSectionOpen = !event.matches || (state.openIssues?.issues?.length || 0) > 0;
```

- [ ] **Step 5: Gộp dòng KNOWN DEBT trùng lặp (L3)**

Trong `renderJobJournal`, sau `const jobs = journalJobs();`, thêm:

```js
    // 16/28 dòng của một phiên là cùng một known-debt G2. Nhiễu đó che các dòng
    // thật; gộp thành một hàng tóm tắt, chi tiết vẫn mở được qua từng job.
    const debtJobs = jobs.filter(job => jobPresentation(job).status === 'known_debt');
    const shownJobs = debtJobs.length > 3
      ? [...jobs.filter(job => jobPresentation(job).status !== 'known_debt'), debtJobs[0]]
      : jobs;
    const debtSummary = debtJobs.length > 3
      ? `<li class="job-row tone-cleanup status-known_debt"><div class="journal-message">${debtJobs.length} slots completed with the same known debt (G2 model age)</div></li>`
      : '';
```

rồi đổi `jobs.map(...)` thành `shownJobs.map(...)` và `$('journal').innerHTML = jobRows || …` thành:

```js
    $('journal').innerHTML = (jobRows + debtSummary) || '<li><div class="journal-message">No scheduler jobs observed for this session.</div></li>';
```

- [ ] **Step 6: Favicon**

Trong `monitor/backend/app.py`, thêm sau route `/dash/<path:filename>`:

```python
@app.get("/favicon.ico")
def favicon():
    # Trình duyệt luôn xin favicon; một 404 trong console làm lu mờ lỗi thật.
    return "", 204
```

- [ ] **Step 7: Ghi lại L6 mà không sửa runner**

Thêm vào cuối `docs/futures/OPEN_QUESTIONS.md` (không sửa nội dung cũ):

```markdown
- `operational_status.breaker.dd_pct` phát ra ở đơn vị phần trăm (0.086) trong khi
  `snapshot.drawdown_pct` ở đơn vị phân số (0.00086) — cùng một payload, chênh 100×
  (REALTIME_DASHBOARD_AUDIT.md L6). Sửa nguồn nằm trong `global_index/runner.py` nên
  cần quyết định riêng. Dashboard hiện không render field này; bất biến được khóa ở
  `monitor/test_realtime_contract.py::test_realtime_never_renders_the_percent_unit_breaker_field`.
```

- [ ] **Step 8: Chạy toàn bộ suite**

Chạy:
```powershell
node --check global_index/dash/realtime/realtime.js
python -m pytest monitor/ -q
```
Kỳ vọng: toàn bộ PASS, không SKIP.

- [ ] **Step 9: Ranh giới commit (user tự chạy)**

```bash
git add global_index/dash/realtime/realtime.js global_index/dash/realtime/realtime.css monitor/backend/app.py monitor/test_realtime_contract.py monitor/test_realtime_dom.py docs/futures/OPEN_QUESTIONS.md
git commit -m "chore(realtime): remove dead rail code, group known debt, keep issues visible on mobile (L1, L3-L6)"
```

---

## Xác minh cuối (sau T12)

- [ ] **Toàn bộ suite**

```powershell
python -m pytest monitor/ -q
node --check global_index/dash/realtime/realtime.js
```
Kỳ vọng: không FAIL, không SKIP. Tổng test = baseline đo được ở đầu + 1 (T1 đăng ký) + 3 (T4) + 3 (T6 backend) + 1 (T11 backend) + ~28 (contract + DOM).

- [ ] **Chạy lại phép đo đã phá C2 trong audit**

```powershell
python -X utf8 -c "import datetime as dt; from pathlib import Path; from monitor.backend.schedule_status import get_schedule_status; now=dt.datetime(2026,8,14,7,0,tzinfo=dt.timezone.utc); [print(lbl, get_schedule_status(Path('.'), observed_at=now-d, now=now)['freshness']) for lbl,d in [('2min',dt.timedelta(minutes=2)),('90d',dt.timedelta(days=90))]]"
```
Kỳ vọng: `2min fresh` / `90d stale`.

- [ ] **Đối chiếu với Data Consistency Matrix của audit**

Restart backend (thao tác của user), mở `http://127.0.0.1:5002/realtime?bust=post-fix`, và xác nhận sáu ô từng ghi **no** đã chuyển:

| Ô trong matrix | Trước | Sau (kỳ vọng) |
|---|---|---|
| Runner context | không hiển thị | hiện tuổi + trạng thái |
| Now Monitor | 6× OPEN | 0 incident |
| Job Journal | 6× OPEN | 6× RECOVERED |
| Open Issues coverage | luôn là hôm nay | ngày log cuối (+ độ trễ nếu có) |
| connectivity / reconcile incidents | code chết | hiển thị khi status=open |
| HMM fit | xanh | warning + `22 warn` |
| Broker equity | không render | dòng context + delta |

- [ ] **Cập nhật audit**

Thêm một khối trạng thái ở đầu `REALTIME_DASHBOARD_AUDIT.md` liệt kê finding đã đóng và ngày đóng. **Không xóa nội dung finding** — audit là bản ghi lịch sử.

- [ ] **Cập nhật `TASK.md`** với sub-task mới, danh sách file đã chạm, và quyết định còn mở: "L6 (đơn vị `breaker.dd_pct`) để mở — cần quyết định riêng về payload runner".

---

## Thứ tự và phụ thuộc

```
T1 (static guards) ──┐
T2 (playwright)    ──┼──> T3 (C1)
                     │
                     ├──> T4 (C2 backend) ──> T5 (C2 frontend)
                     │
                     ├──> T6 (H1) ──> T7 (H3/H4) ──> T8 (H2/M5)
                     │
                     └──> T9 (M1/M2/M6) ──> T10 (M3) ──> T11 (M4/M7/M8) ──> T12 (cleanup)
```

- **T1 và T2 phải xong trước mọi thứ.** Chúng là lưới an toàn.
- **T4 phải xong trước T5** — frontend đọc `freshness: "stale"` do backend sinh ra.
- **T9 phải xong trước T10** — T10 sửa `persistedRunnerFor` mà T9 vừa đặt lại.
- **T5, T6, T11 đều chạm `renderRail`**; nếu chia người làm song song, ba task này phải tuần tự với nhau.
- **T12 chạy cuối** — xóa dead code chỉ an toàn khi chắc chắn không nhánh nào cần đến.
- T3 độc lập với nhóm T6–T8 và nhóm T9–T11 về mặt logic, nhưng cả ba đều sửa `realtime.js`, nên làm tuần tự sẽ ít rủi ro merge hơn.

## Nếu gặp bất ngờ

- **Test T1 fail với id khác `schedulerHealth`/`schedulerHealthValue`:** source đã đổi từ lúc audit. Dừng, chạy lại phép đo trong audit trước khi sửa bất cứ gì.
- **Playwright không khởi động được chromium:** chạy `python -m playwright install chromium`. Nếu vẫn hỏng: T1 và toàn bộ test backend vẫn chặn được C1/C2/H1 — báo cáo và tiếp tục các task sửa, đừng bỏ qua chúng.
- **Test backend cũ về freshness fail sau T4:** nhánh `stale` đặt sai vị trí. Nó phải nằm ngay sau `missing` và trước `not_expected_yet`.
- **Fixture log ở T6 không sinh ra job:** chạy lệnh ở T6 Step 1 để lấy định dạng dòng thật, rồi chỉnh fixture. Đừng đoán.
- **Position M2K thật chuyển thành `naked` sau T9:** `contract_specs` thiếu `tick`, hoặc `rootOf('M2KU6')` không trả `'M2K'`. `stopPriceAgrees` đã có nhánh `tick == null → true` nên nguyên nhân nhiều khả năng là `rootOf`.
- **Bất kỳ lúc nào thấy cần sửa `global_index/runner.py` hoặc code trong `futures/`, `raits/`:** dừng, báo user. Đó là code giao dịch, nằm ngoài Global Constraints.
