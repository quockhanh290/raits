# monitor/TRACE.md — data map trước khi build dashboard

**Nguyên tắc:** Đo trước khi build. File này map TẤT CẢ data thật runner/IBKR cung cấp
(nguồn + format + timing + gap) để build dashboard sau không mù.

`monitor/` chỉ ĐỌC. KHÔNG import/sửa `runner.py`, `_validated_core.py`, hay bất kỳ logic giao dịch.

---

## 3 loại data — tổng quan

| Loại | Nguồn | Real-time đêm? | Cập nhật khi |
|------|-------|---------------|-------------|
| **Loại 1** — IBKR query | Gateway 4002 (ib_insync) | ✅ 24h | Luôn available (con connect) |
| **Loại 2** — live_state snapshot | `live_state_data.js` (file) | ❌ Stale | Cuối `run_day()` ~14:05 ET |
| **Loại 3** — runner events | `meta.events` trong live_state | ❌ Stale | Cuối `run_day()` cùng lúc |

**Key insight:** Đêm (sau 15:55 ET đến ~09:31 ET hôm sau) chỉ Loại 1 là live. Loại 2+3 stale từ lần `run_day` cuối.

---

## Loại 1 — IBKR Query (real-time 24h)

Query trực tiếp Gateway 4002 via ib_insync. Không cần runner chạy.

### Các method IBKRBroker hiện có (global_index/ibkr_broker.py)

| Method | Trả về | Notes |
|--------|--------|-------|
| `get_equity()` | `float` NetLiquidation | Bao gồm unrealized PnL baked in. Retry 4×2-5s. |
| `get_positions()` | `list[BrokerPosition]` | inst/direction/contracts. **KHÔNG có**: entry_price, entry_time, cluster. Retry-stable 4×2s. |
| `get_order_status(order_id)` | `str` ("FILLED"/"NOT_FOUND"/...) | Dùng `ib.openTrades()` lọc theo orderId. |
| `find_execution(order_id)` | `bool` | `reqExecutions()` — IB server history 2-day lookback. ~5s. |

### IBKR data available nhưng CHƯA dùng trong IBKRBroker

| ib_insync call | Data | Có 24h? | Notes |
|----------------|------|---------|-------|
| `ib.portfolio()` | `PortfolioItem` mỗi vị thế: `unrealizedPNL`, `realizedPNL`, `marketValue`, `averageCost` | ✅ | Auto-subscribe on connect. `averageCost` ≈ entry price proxy. |
| `ib.accountValues()` tag `"UnrealizedPNL"` | Tổng unrealized PnL account | ✅ | Đã dùng cho `NetLiquidation`; `UnrealizedPNL` tag cùng `accountValues()` call. |
| `ib.openTrades()` | Tất cả orders đang mở (STP GTC, pending) | ✅ | Hiện dùng trong `get_order_status`. Dashboard có thể dùng trực tiếp. |

### Unrealized PnL — trả lời câu hỏi

**IBKR tính sẵn, không tự tính.** Hai cách lấy:
1. **Tổng**: `get_equity()` = NetLiquidation đã include unrealized (không tách ra được).
2. **Per-position**: `ib.portfolio()` → `item.unrealizedPNL` per symbol. **Hiện KHÔNG dùng trong IBKRBroker** nhưng backend read-only CÓ THỂ gọi trực tiếp mà không sửa runner.

---

## Loại 2 — live_state Snapshot (file)

**File:** `global_index/live_state_data.js` (opt-in: phải pass `--live-state-path` cho `run_live_day.py`)  
**Format:** `window.LIVE_DATA = {...};` (JS assignment, parse bằng regex hoặc đọc JSON phần giữa)  
**Viết khi:** Cuối `run_day()` duy nhất — `runner.py:1134`. `run_maxhold_exit` KHÔNG gọi `dump_state`.

### Schema thực tế (từ live_state_data.js 2026-07-09)

```
window.LIVE_DATA = {
  runner_health: {
    last_heartbeat: "2026-07-09",   // ngày run_day cuối
    ibkr_connected: null,           // LUÔN null (không set sau connect)
  },
  meta: {
    account: 50000.0,               // account baseline (hardcoded trong runner)
    hard_dd_pct: 0.15,
    daily_loss_pct: 0.04,
    final_equity: 994252.2,         // NetLiquidation lúc dump_state
    net_pnl: 944252.2,              // final_equity - account
    backtest_calmar: 2.04,          // ⚠️ STALE: giá trị cũ (2.04), runner code đã fix → 1.53
    events: [...],                  // Loại 3 events (see below)
    operational_status: {...},
  },
  snapshots: [{
    date: "2026-07-09",
    equity: 994252.2,
    drawdown_pct: 0.0,
    breaker_level: "OK",
    regime: "Unknown",              // ⚠️ LUÔN "Unknown" — hardcoded trong dump_state, không populate
    open_positions: [{
      inst: "MES",
      cluster: "roska4_swing",
      direction: "LONG",
      days_held: 2,
      risk_sized: 1234.0,           // risk_dollars
      entry_day: "2026-07-07",
      entry_price: null,            // ⚠️ LUÔN null — không persist entry price
      entry_time: null,             // ⚠️ LUÔN null — không persist entry time
    }],
    cluster_exposure: {
      roska4_swing: {gross_pct: 0.05, net_pct: 0.044},
      ...
    },
    decision: {
      realized_today: 0.0,          // ⚠️ LUÔN 0.0 — không tính
      taken_today: {roska4_swing: 0, ...},
      rejected_today: {roska4_swing: 0, ...},
      entries: [],                  // ⚠️ LUÔN [] — không populate từ decision
      exits: [],                    // ⚠️ LUÔN [] — không populate từ decision
    },
    per_cluster_pnl: {...},         // ⚠️ LUÔN 0.0 — không tính
    operational_status: {
      runner: {alive: true, pid: ..., last_run_day: "2026-07-09"},
      breaker: {level: "OK", dd_pct: 0.0, day_dd_pct: 0.0},
      regime_freshness: null,       // null nếu không wired hmm_stale_guard
      model_age: null,              // null nếu không wired hmm_stale_guard
      positions: {count: 0, persist_match: true},
    }
  }]
}
```

### Gap trong snapshot (Group B — `dump_state` chưa populate)

| Field | Hiện tại | Cần để dashboard dùng |
|-------|----------|----------------------|
| `regime` | "Unknown" (hardcoded) | regime hôm nay (Normal/Stress/Calm) |
| `entry_price` | null | avg_fill_price từ C1 log |
| `entry_time` | null | fill time từ IBKR |
| `entries` | [] | list entry signals đã fire |
| `exits` | [] | list exits đã fire |
| `realized_today` | 0.0 | pnl thật của ngày |
| `per_cluster_pnl` | 0.0 | realized pnl per cluster |
| `ibkr_connected` | null | True/False sau connect |
| `backtest_calmar` | 2.04 | stale — nên là 1.53 (post-causal fix) |

---

## Loại 3 — Runner Events (_emit_event)

**Lưu trong:** `meta.events` list (bounded 500). Viết cùng lúc với Loại 2 (cuối `run_day()`).  
**Format:** `{ts: "2026-07-09T15:46:24", level: str, category: str, message: str, context?: dict}`

### Event map đầy đủ (từ runner.py — trace code, không đoán)

| Phase | level | category | message mẫu | Ghi khi |
|-------|-------|----------|------------|---------|
| Cold-start | INFO | STATE | "Runner started: loaded N position(s) from persisted file" | `__init__` |
| Day start | INFO | STATE | "Day started: 2026-07-13, N position(s) open" | `run_day()` đầu |
| B1 persist fail | ALERT | STATE | "B1: persist failed — state may not survive restart" | _persist_state exception |
| File/memory mismatch | WARN | STATE | "persist count mismatch — in-memory and saved file differ" | dump_state |
| Retry pending exits | ALERT | EXEC | "retry_pending_exits: N CLOSE(s) retrying" | _retry_pending_exits |
| Retry still FAILED | ALERT | EXEC | "retry_pending_exits: CLOSE still FAILED MES/roska4_swing" | _retry fail |
| I4.8 CLOSE FAILED | ALERT | EXEC | "I4.8: CLOSE FAILED MES/roska4_swing — exit_pending=True" | close loop |
| STP FAILED | ALERT | EXEC | "STP: place_stop FAILED MES LONG @ 5800.0 — no overnight stop" | after OPEN fill |
| MAX_HOLD CLOSE FAILED | ALERT | EXEC | "MAX_HOLD_EXIT: CLOSE FAILED MES/roska4_swing — retry at 14:05" | run_maxhold_exit |
| C2 roll SUCCESS | INFO | ROLLOVER | "C2: Roll MES LONG ×1: close@5820.0 → open@5821.0 slippage=1.0" | rollover ok |
| C2 roll CLOSE fail | CRITICAL | ROLLOVER | "C2: Roll CLOSE failed MES LONG ×1 — position unchanged" | rollover fail |
| C2 roll OPEN fail | CRITICAL | ROLLOVER | "C2: Roll OPEN failed MES LONG ×1 AFTER CLOSE — FLAT in IBKR" | rollover split fail |
| D5 STOP_FILE | CRITICAL | SYSTEM | "STOP_FILE: entries halted for 2026-07-13. Remove raits.stop to resume." | D5 check |
| C3 empty bars | WARN | SIGNAL | "C3: empty bars for MES — possible feed gap; exits unaffected" | fetch_bars |
| E3 clock skew | ALERT | SIGNAL | "E3: clock skew — 5d gap, entries skipped" | bar date check |
| C1 signal fail | ALERT | SIGNAL | "C1: signal_fn failed — entries skipped for today" | signal_fn exception |
| B3 HALT entries | CRITICAL | GUARD | "B3 HALT: 2 entry signal(s) blocked — broker/file mismatch; restart required" | B3 block |
| G1 HARD-STALE | CRITICAL | GUARD | "G1 HARD-STALE: entries HALTED — SPY CSV stale >5 bday" | G1 transition |
| G1 SOFT-STALE | WARN | GUARD | "G1 SOFT-STALE: SPY CSV stale >2 bday — trading continues" | G1 transition |
| G1 RECOVERED | INFO | GUARD | "G1 RECOVERED: SPY CSV fresh — entry halt cleared" | G1 transition |
| G2 WARN | WARN | GUARD | "G2: model age WARN — plan annual re-freeze" | G2 transition |
| G2 URGENT | ALERT | GUARD | "G2: model age URGENT — schedule re-freeze immediately" | G2 transition |
| C2 guard fail | ALERT | GUARD | "C2: stale_guard check failed — entries blocked (conservative)" | guard exception |
| REGIME_UNRELIABLE | WARN | GUARD | "REGIME_UNRELIABLE: 2 entry signal(s) blocked — SPY CSV stale" | entries blocked |
| BREAKER HALT | CRITICAL | GUARD | "BREAKER HALT: DD 15.2% — all new entries blocked" | DD transition |
| BREAKER HALT_DAY | ALERT | GUARD | "BREAKER HALT_DAY: daily loss 4.2% — entries blocked today" | DD transition |
| BREAKER WARN | WARN | GUARD | "BREAKER WARN: DD 10.1% — approaching limit" | DD transition |
| BREAKER OK | INFO | GUARD | "BREAKER OK: recovered from HALT_DAY" | DD transition |
| FAT_FINGER | CRITICAL | RISK | "FAT_FINGER BLOCKED: MES 50 contracts > max 10 — order NOT sent" | F3 check |

### ⚠️ THIẾU event — dashboard sẽ TRỐNG chỗ này

| Gì thiếu | Tại sao quan trọng | Thêm nếu cần |
|----------|-------------------|--------------|
| OPEN fill success | Không biết khi nào entry fire, giá bao nhiêu | Thêm `_emit_event("INFO", "EXEC", f"OPEN FILLED {inst}...")` |
| CLOSE fill success | Không biết khi nào exit fire, giá bao nhiêu | Thêm `_emit_event("INFO", "EXEC", f"CLOSE FILLED {inst}...")` |
| STP placed success | Không biết STP đặt hay không (chỉ log fail) | Thêm `_emit_event("INFO", "ORDER", f"STP placed {inst}...")` |
| OPEN fill FAILED | logger.error nhưng không _emit_event | Thiếu nếu dashboard filter EXEC |
| Regime hôm nay | Không emit khi signal_fn decode regime | Dashboard không biết regime từ events |
| Signal count | Bao nhiêu entry/exit generated | Không có |
| H4 equity sync | Equity synced sau close | Không có |
| Heartbeat đêm | Không có cron giữa runs | Trống từ 15:55→09:31 |

---

## Timing — khi nào data update

| Thời điểm (ET) | Hành động | live_state update? | IBKR query live? |
|----------------|-----------|-------------------|-----------------|
| 09:31 Mon-Fri | run_maxhold_exit — CLOSE MAX_HOLD | ❌ KHÔNG (no dump_state) | ✅ |
| 14:05 Mon-Fri | run_live_day — full cycle | ✅ Cuối run (~14:10?) | ✅ |
| 15:55→09:31 | Không có process | ❌ Stale | ✅ (IBKR 24h) |
| 17:00 | TWS restart | ❌ | ⚠️ Reconnect needed |
| 24h sàn | STP fill nếu chandelier hit | ❌ Runner không biết | ✅ `openTrades()` thấy FILLED |
| Cold-start sáng | B3 check / STP-VERIFY | ✅ Cuối run_day | ✅ |

**Kết luận timing:** `live_state` chỉ fresh từ 14:05 ET đến ~14:10 ET. Phần còn lại của ngày (đặc biệt đêm) = Loại 1 IBKR query duy nhất là live.

---

## Map panel → nguồn đúng

| Panel dashboard | Nguồn đúng | Available đêm? | Gap cần xử lý |
|----------------|-----------|---------------|--------------|
| Account equity | Loại 1: `get_equity()` NetLiquidation | ✅ 24h | Cần connect Gateway |
| Unrealized PnL total | Loại 1: `ib.accountValues()` tag "UnrealizedPNL" | ✅ 24h | Chưa có method trong IBKRBroker |
| Unrealized PnL per-position | Loại 1: `ib.portfolio()` `.unrealizedPNL` | ✅ 24h | Chưa có method trong IBKRBroker |
| Entry price per-position | Loại 1: `ib.portfolio()` `.averageCost` | ✅ 24h | Proxy (avg cost, không phải exact fill) |
| Open positions (inst/dir/qty) | Loại 1: `get_positions()` hoặc Loại 2: snapshot | ✅ / Stale | Loại 1 better đêm |
| STP order status | Loại 1: `ib.openTrades()` | ✅ 24h | Đã có trong ibkr_broker |
| Breaker level / DD% | Loại 2: `snapshots[0].breaker_level` + `drawdown_pct` | ❌ Stale | Tính từ Loại 1 equity + peak_equity từ live_positions.json |
| Regime hôm nay | Loại 2 nhưng LUÔN "Unknown" | ❌ | Phải thêm vào dump_state |
| Runner events / log | Loại 3: `meta.events` | ❌ Stale | Đủ cho "hôm nay đã xảy ra gì" |
| Operational guards | Loại 2: `operational_status` | ❌ Stale | G1/G2/B3 state tại thời điểm run |
| Entry/exit signals ngày | Loại 3: THIẾU event (không _emit_event OPEN/CLOSE fill success) | ❌ | Cần thêm events (xem gap table) |
| Heartbeat runner còn sống | Loại 2: `last_heartbeat` | ❌ Stale | Chỉ biết "chạy lần cuối lúc nào", không phải "đang chạy" |

---

## Cần làm TRƯỚC khi build dashboard (không làm giờ)

1. **Wire `--live-state-path`** vào run_live_day production command (hiện opt-in, không pass → file không viết).
2. **Thêm missing events** trong runner.py nếu muốn dashboard log OPEN/CLOSE/STP fill.
3. **Populate `regime`** trong dump_state (hiện hardcoded "Unknown").
4. **Backend read-only script** (`monitor/backend/`) — connect 4002, gọi `ib.portfolio()` + `ib.accountValues()` + `ib.openTrades()`, expose JSON endpoint. KHÔNG import runner/logic.
5. **Parse live_state_data.js** — extract JSON từ `window.LIVE_DATA = ...;` pattern.

---

## Files liên quan

| File | Vai trò |
|------|---------|
| `global_index/runner.py:1153` | `_emit_event` definition |
| `global_index/runner.py:1265` | `dump_state()` — schema của live_state |
| `global_index/runner.py:1133` | `dump_state(day)` call site (cuối run_day) |
| `global_index/ibkr_broker.py:606` | `get_positions()` |
| `global_index/ibkr_broker.py:663` | `get_equity()` |
| `global_index/ibkr_broker.py:803` | `get_order_status()` |
| `global_index/live_state_data.js` | File snapshot thực tế (từ run 2026-07-09) |
| `live_positions.json` | B1 state (positions + breaker) — đọc được tĩnh |
| `slip_stats.json` | C1 running mean (đọc được tĩnh) |
