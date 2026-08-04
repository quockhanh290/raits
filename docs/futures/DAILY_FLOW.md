# DAILY_FLOW — Chuỗi command một ngày trading
_Nguồn: run_scheduler.py, run_live_day.py, run_maxhold_exit.py, update_ibkr_daily.py,_
_update_spy_csv.py, runner.py. Đọc code thật — không đoán._
_Cập nhật: 2026-07-14. Xem thêm: [PIPELINE_FLOW.md](PIPELINE_FLOW.md) (nội bộ run_day) · [DAILY_UPDATE_RUNBOOK.md](DAILY_UPDATE_RUNBOOK.md) (data safety)._

---

## TỔNG QUAN TIMELINE ET

```
SÁNG (trước 09:31)   MANUAL: start scheduler (nếu reboot đêm qua), check_next_entry
09:31 ET  Mon-Fri    AUTO:  MAX_HOLD exit → close position ≥5 ngày → persist state
13:45 ET  Mon-Fri    AUTO:  Pre-flight chain (blocking): update_ibkr_daily → update_spy_csv
14:05 ET  Mon-Fri    AUTO:  run_live_day (initial slot — chỉ nếu pre-flight OK)
14:10 ET  ┐
14:15 ET  │ AUTO:  Continuous runner (mỗi 5 phút) — TF entry capture
...        │         Xem lý do: module docstring run_scheduler.py
15:55 ET  ┘ AUTO:  Slot cuối — 100% TF entries trong window có thể fire
ĐÊM (sau 17:00 ET)   Không process nào chạy. STP GTC nằm trên sàn IBKR.
HÔM SAU 09:31 ET     Vòng lặp lặp lại.
```

---

## 0. MANUAL — Những việc PHẢI làm tay

| Việc | Command | Khi nào |
|------|---------|---------|
| Start scheduler | `cd d:\raits && pythonw -m global_index.run_scheduler --port 4002` | Đầu ngày (hoặc sau reboot). **PHẢI trước 13:45 ET.** |
| Check regime + entry | `python global_index\check_next_entry.py` | Mỗi sáng sau khi scheduler chạy (hoặc sau spy_csv update) |
| Verify --print-signals (P0c) | Xem mục 3B bên dưới | Ngày Normal/Stress có entry, **làm tay**, không qua scheduler |
| Monitor backend | `python monitor\start_backend.py` | Tùy ý — read-only, không ảnh hưởng trading |

> **Phân biệt AUTO vs MANUAL:**
> Scheduler (`pythonw -m global_index.run_scheduler`) là process **giữ sống** — tự fire 09:31/13:45/14:05.
> Nếu máy reboot qua đêm → scheduler chết → phải `pythonw` lại TRƯỚC 13:45.
> Mọi việc còn lại (check_next_entry, P0c, monitor) là thủ công.

---

## 1. JOB 09:31 ET — MAX_HOLD EXIT

**Nguồn:** `run_scheduler.py:88–94` → `run_maxhold_exit.py`

```python
# run_scheduler.py:88
@sched.scheduled_job("cron", day_of_week="mon-fri", hour=9, minute=31, ...)
def job_maxhold():
    _run([sys.executable, "-m", "global_index.run_maxhold_exit",
          "--positions-path", "live_positions.json",
          "--port", str(port)],
         label="MAX_HOLD_EXIT", dry_run=dry_run)
```

**Chuỗi thực thi:**

```
run_maxhold_exit.main()
  │
  ├─ load live_positions.json (runner.state.open_positions)
  ├─ IBKRBroker.connect()  clientId=2 (KHÁC run_live_day clientId=1)
  ├─ time.sleep(5)
  ├─ log từng position: hold N ngày, max_hold=5, → CLOSE hay keep
  │
  └─ runner.run_maxhold_exit(today, max_hold_days=5)   [runner.py:564]
       ├─ với mỗi position có hold >= max_hold_days:
       │    ├─ broker.send_order(Order CLOSE)
       │    ├─ broker.cancel_order(stop_order_id)  ← cancel STP GTC
       │    └─ xóa position khỏi state.open_positions
       │       (nếu fail → exit_pending=True → retry tại 14:05 run_day)
       └─ _persist_state()   ← GHI live_positions.json
          [KHÔNG dump_state — live_state_path=None → không ghi live_state_data.js]
  │
  └─ broker.disconnect() → process EXIT
```

**Quan trọng:**
- `live_state_data.js` KHÔNG được cập nhật tại 09:31 (live_state_path không truyền vào FuturesRunner).
- Position bị đóng được xóa khỏi state trước 14:05 → run_day sẽ không thấy và không double-close.
- Nếu CLOSE fail: `exit_pending=True` persist → `_retry_pending_exits()` tại 14:05 (`runner.py:540`).

---

## 2. JOB 13:45 ET — PRE-FLIGHT CHAIN (blocking, fail-closed)

**Nguồn:** `run_scheduler.py:99–133`

```python
@sched.scheduled_job("cron", day_of_week="mon-fri", hour=13, minute=45, ...)
def job_preflight():
    # BƯỚC 1 (blocking):
    ibkr_ok = _run([sys.executable, "-m", "global_index.update_ibkr_daily",
                    "--port", str(port)], label="IBKR_UPDATE", dry_run=dry_run)
    if not ibkr_ok:
        _preflight_ok[today] = False
        return          # ← DỪNG, không chạy bước 2

    # BƯỚC 2 (chỉ chạy nếu bước 1 OK):
    spy_ok = _run([..., "global_index.update_spy_csv", "--csv", regime_csv,
                   "--api-key", polygon_api_key], label="SPY_UPDATE", dry_run=dry_run)
    if not spy_ok:
        _preflight_ok[today] = False
        return

    _preflight_ok[today] = True  # ← chỉ set True khi CẢ HAI xong
```

### Bước 1: update_ibkr_daily

**Nguồn:** `update_ibkr_daily.py:145+`

- Fetch 1-min bars từ IBKR cho **5 instruments** (MES, MNQ, MYM, M2K) + NKD.
- Append vào parquet: `data/cache/futures/{instrument}.parquet` + `global_index/data/NKD_continuous_1m_8y.parquet`.
- History invariant check: verify ≥200 bar đầu KHÔNG thay đổi sau append (bắt bug splice/offset).
- Nếu bất kỳ instrument fail: `sys.exit(1)` → returncode=1 → `ibkr_ok=False` → chain dừng.

### Bước 2: update_spy_csv

**Nguồn:** `update_spy_csv.py:206+`

- Fetch SPY adjusted close từ Polygon.io (30-day overlap re-fetch để giữ consistency).
- Verify regime labels: `label_regimes(old_spy)` vs `label_regimes(new_spy)` — nếu label thay đổi log warning.
- Ghi `spy_daily_live.csv` (atomic write).
- `sys.exit(1)` nếu fetch fail (Polygon key thiếu) → `spy_ok=False`.

### Fail-closed flag logic

```
_preflight_ok[today]:
  True   → ibkr_daily + spy_csv CẢ HAI thành công → run_live_day CHẠY
  False  → ít nhất 1 bước fail → run_live_day BỊ SKIP (log ERROR)
  None   → scheduler restart / crash / khởi động sau 13:45 → run_live_day BỊ SKIP
```

> Flag in-memory (dict `_preflight_ok`). Mất khi scheduler restart.
> Nếu restart sau 13:45: flag=None → live_day skip ngày đó. Recover: chạy update thủ công.

---

## 3. JOBS 14:05–15:55 ET — RUN_LIVE_DAY (23 slots)

**Nguồn:** `run_scheduler.py` — `_live_day_body()` + `job_live_day()` + `_CONT_SLOTS` loop

**Initial slot (14:05):** registered với `@sched.scheduled_job`, gọi `_live_day_body("LIVE_DAY_1405", first_slot=True)`.

**Continuous runner (14:10–15:55, mỗi 5 phút):** 22 slots đăng ký qua `sched.add_job()` trong vòng lặp `_CONT_SLOTS`. Tất cả gọi `_live_day_body(slot_id)` — cùng pre-flight gate, cùng command.

**Lý do continuous runner:** tại 14:05 chỉ có 1 bar trong TF window → 0% same-day entry capture. Xem module docstring `run_scheduler.py` để biết full analysis.

```python
# Tất cả 23 slots gọi cùng command (qua _live_day_body):
_run([sys.executable, "-m", "global_index.run_live_day",
      "--data-dir",        data_dir,
      "--nkd-parquet",     nkd_parquet,
      "--regime-csv",      regime_csv,
      "--live-state-path", live_state_path,
      "--port",            str(port)],
     label=slot_id, dry_run=dry_run)
```

**Pre-flight gate:** tất cả slots check `_preflight_ok[today]`. First slot (14:05) log ERROR khi fail; slots sau log WARNING/DEBUG (tránh spam 22 lần).

> ⚠️ **Scheduler KHÔNG truyền `--print-signals`** → tất cả slots vào **nhánh full run (order)**.
> P0c (verify --print-signals) phải chạy tay, không qua scheduler.

### 3A. Nhánh FULL RUN (scheduler, P2+)

Args: không có `--print-signals`, không có `--dry-run` (trừ khi scheduler start với `--dry-run`).

```
run_live_day.main()
  │
  ├─ today = now(ET).normalize()  [run_live_day.py:120]
  ├─ Load parquet: dfs[inst] cho 5 instruments + NKD  [run_live_day.py:152–156]
  ├─ label_regimes(spy_csv, train_end=2018-01-01, hmm_fit_end=2024-12-31)
  │    → swing_labels (dict day→regime)
  │
  ├─ a.dry_run=False and a.print_signals=False
  │    → signal_fn THẬT [run_live_day.py:234–261]:
  │         concat_swing = frozen_parquet + live IBKR bars
  │         return generate_today_signals(swing_engine, concat_swing, ...)
  │
  ├─ IBKRBroker.connect()  clientId=1
  ├─ FuturesRunner(broker, signal_fn, live_state_path=..., regime_fn=_regime)
  │
  └─ runner.run_day(today)   [runner.py:~740–1168]
       ├─ _handle_rollover_if_needed(today)   [runner.py:626]
       ├─ _through = today + Timedelta(23h59m)  [runner.py:745]
       ├─ bars = broker.fetch_bars(inst, through=_through)  [runner.py:746]
       │    → IBKR cap tại now (~14:05 ET) → bars gồm overnight + 14:00-14:05
       ├─ signal_fn(today, bars, held)
       │    → generate_today_signals() → backtest_swing_tf() trên concat
       │    → entry_day==today → entries[] + exits[]
       │    ⚠️ G1 HMMStaleGuard CHƯA WIRE (I5.12): hmm_stale_guard=None → không check staleness.
       │       Freshness chỉ qua pre-flight flag (update_ibkr_daily + update_spy_csv).
       ├─ _retry_pending_exits()   [nếu có exit_pending từ 09:31 fail]
       ├─ decide_day() → risk checks, place_order (OPEN), place_stop (STP GTC)
       │    ├─ CircuitBreaker check (DD -4% hoặc 5 loss liên tiếp → HALT)
       │    ├─ MultiClusterGuard check (net exposure per cluster)
       │    └─ broker.send_order(OPEN) → broker.place_stop(STP GTC)
       ├─ regime capture: _regime_fn(day) → _last_regime  [runner.py:~810]
       ├─ _persist_state()   → live_positions.json  [runner.py:1164]
       └─ dump_state(day)    → live_state_data.js   [runner.py:1166]
            (atomic write qua .tmp → os.replace)

  └─ broker.disconnect() → process EXIT
```

### 3B. Nhánh --print-signals (P0c, MANUAL — KHÔNG qua scheduler)

```powershell
cd d:\raits
python -m global_index.run_live_day `
  --data-dir data/cache/futures `
  --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet `
  --regime-csv spy_daily_live.csv --port 4002 `
  --print-signals
```

```
run_live_day.main()
  │
  ├─ (load parquet + labels như nhánh full)
  ├─ a.print_signals=True → signal_fn THẬT (không empty)
  │
  ├─ [run_live_day.py:264] if a.print_signals:
  │    ├─ IBKRBroker.connect()  clientId=1
  │    ├─ time.sleep(15)
  │    ├─ _ps_through = today + Timedelta(23h59m)   ← FIX I5.11 (2026-07-14)
  │    ├─ _ps_bars = broker.fetch_bars(inst, through=_ps_through)
  │    │    → IBKR cap tại now → bars đến ~14:05 ET (cùng cutoff run_day)
  │    ├─ signal_fn(today, _ps_bars, _ps_held)
  │    │    → generate_today_signals() → entries[], exits[]
  │    ├─ PRINT output:
  │    │    regime / held / bars: MES✓Nb / entries / exits
  │    │    [nếu entry: inst direction ×N cluster exit pnl_sized]
  │    ├─ broker.disconnect()
  │    └─ return   ← [run_live_day.py:328] EXIT — KHÔNG gọi FuturesRunner, KHÔNG order
  │
  [KHÔNG _persist_state, KHÔNG dump_state, KHÔNG order]
```

**Gate P0b-B:** Chạy --print-signals sát ±2 phút với `desired_basket()` offline cùng cutoff.

### 3C. Nhánh --dry-run (scheduler start với --dry-run)

`_run(..., dry_run=True)` → log "dry-run — command NOT executed" → subprocess KHÔNG chạy.
run_live_day không được invoke. Khác với run_live_day `--dry-run` (chạy nhưng signal_fn empty).

---

## 4. PERSIST VÀ DUMP_STATE — GHI GÌ, LÚC NÀO

| File | Ghi bởi | Thời điểm |
|------|---------|-----------|
| `live_positions.json` | `_persist_state()` | Sau run_maxhold_exit (09:31) + sau run_day (14:05) |
| `live_state_data.js` | `dump_state(day)` | Chỉ cuối run_day (14:05), atomic via .tmp |
| `live_positions.json` | run_day exit_pending retry | Bên trong run_day nếu retry pending exit |

`dump_state` chỉ chạy nếu `live_state_path` được truyền → run_day (scheduler truyền `--live-state-path`).
`run_maxhold_exit` không truyền → dashboard không cập nhật tại 09:31.

---

## 5. ĐÊM (sau 15:55 ET)

Không process nào của RAITS chạy sau khi run_day kết thúc (~14:05–14:10 ET).

Bảo vệ vị thế overnight: **STP GTC** đặt trên sàn IBKR sau fill OPEN.
- GTC = Good Till Cancelled → sống qua đêm, qua TWS restart 17:00 ET.
- `runner.py:place_stop` lưu `stop_order_id` vào `live_positions.json`.
- Sáng hôm sau B3 cold-start verify: `STP-VERIFY` tìm order trong `openTrades()` / `find_execution()`.

---

## 6. PHASE MAPPING (nhánh nào dùng phase nào)

| Phase | Scheduler chạy? | Nhánh run_live_day | Ghi order? |
|-------|-----------------|--------------------|-----------|
| P0b/P0c | KHÔNG — làm tay | `--print-signals` | KHÔNG |
| P1 (timing verify) | CÓ — `--dry-run` scheduler | command không execute | KHÔNG |
| P2+ (order thật) | CÓ — normal scheduler | full run (3A) | CÓ |

> Xem chi tiết phase → [PAPER_ROUTE.md](PAPER_ROUTE.md)

---

## 7. VERIFY NHANH (checklist mỗi ngày)

```
□ Scheduler sống? (pythonw process còn trong Task Manager)
□ Nếu reboot đêm qua → start lại TRƯỚC 13:45 ET
□ python global_index\check_next_entry.py → regime hôm nay? có entry không?
□ 13:45: xem log scheduler [PRE-FLIGHT] OK
□ 14:05: xem log scheduler [LIVE_DAY_1405] completed OK
□ 14:10–15:55: continuous runner log [LIVE_DAY_14xx] (Normal/Stress: chờ slot capture entry)
□ [P0c DONE 2026-07-30] Nếu cần re-verify: chạy p0c_verify_swing.py --port 4002 (hoặc p0c_verify_mnkd.py cho NKD)
```

---

## 8. FILE THAM CHIẾU

| File | Dùng khi |
|------|---------|
| `run_scheduler.py` — `_live_day_body`, `_CONT_SLOTS` | Xem 23 slots (14:05–15:55), pre-flight gate, lý do continuous runner |
| `run_maxhold_exit.py:64–142` | MAX_HOLD exit logic + clientId=2 |
| `update_ibkr_daily.py:145+` | IBKR parquet append, fail-exit |
| `update_spy_csv.py:206+` | Polygon fetch, overlap 30d, regime verify |
| `run_live_day.py:229–365` | Nhánh dry_run / print_signals / full run |
| `runner.py:564` | `run_maxhold_exit()` (cancel STP, persist) |
| `runner.py:740–1168` | `run_day()` (fetch, signal, order, persist, dump) |
| `runner.py:1164–1166` | `_persist_state()` + `dump_state()` cuối run_day |
