# STEP_OUTPUT_MAP — run_day print vs event

_Nguồn: runner.py (code thật). Không đoán._
_Cập nhật: 2026-07-14_

---

## 0. PHÂN BIỆT

| Kênh | Cơ chế | Ai đọc |
|---|---|---|
| **Terminal print** | `logger.*` → stderr/stdout (handler từ run_live_day.py) | Operator (khi chạy tay P0c) |
| **Event** | `_emit_event()` → `self._events` list → `dump_state()` → `live_state_data.js` | Dashboard (`meta.events`) |

`_emit_event()` KHÔNG gọi `logger` — 2 kênh hoàn toàn độc lập. Event chỉ available sau `dump_state()` cuối run_day.

**Event format** (`runner.py:1190`):
```json
{
  "ts":       "2026-07-14T18:05:01+00:00",
  "level":    "INFO|WARN|ALERT|CRITICAL",
  "category": "STATE|GUARD|SIGNAL|EXEC|ORDER|RISK|SYSTEM",
  "message":  "...",
  "context":  { ... }   // optional, absent nếu context=None
}
```

**Dashboard filter logic** (`dashboard.html:1893+1918`):
- Buttons `CRITICAL/ALERT/WARN/INFO` → lọc theo `e.level` (severity ≥ threshold)
- Buttons `GUARD/STATE/SIGNAL/FEED/ORDER` → lọc theo `e.category` (exact match)

`LOG_CAT_FILTERS = ['GUARD','STATE','SIGNAL','FEED','ORDER']`

Categories runner ghi NHƯNG không có category button: `EXEC`, `RISK`, `SYSTEM`, `ROLLOVER`
→ Chỉ thấy khi ALL hoặc dùng level button (CRITICAL/WARN/INFO).
→ Category `FEED` có button nhưng **runner KHÔNG BAO GIỜ emit FEED** → filter đó luôn rỗng.
→ Nút `ORDER` chỉ bắt được **STP placed** — OPEN/CLOSE fills category là `EXEC`, KHÔNG phải ORDER.

---

## 1. BẢNG MAP — step × terminal × event

| Step | file:line | Terminal print (logger — dòng thật) | Event? | category | level | message | context fields |
|---|---|---|---|---|---|---|---|
| **[INIT]** Runner started | runner.py:459 | `logger.info("B1: restored breaker peak_equity=...")` (nếu có position) | Y | STATE | INFO | `"Runner started: loaded N position(s) from persisted file/fresh state"` | — |
| **[B3]** Broker/file reconcile match | runner.py:357 | `logger.info("B3: broker/file positions match (N)")` | **N** | — | — | — | — |
| **[B3]** Broker/file mismatch | runner.py:360 | `logger.critical("B3: N mismatch(es) — new entries HALTED")` | Y (delayed) | GUARD | CRITICAL | `"B3 HALT: N entry signal(s) blocked — broker/file mismatch; restart required"` | count, day |
| **[0-EMIT]** Day started | runner.py:709 | — (không có logger riêng) | Y | STATE | INFO | `"Day started: YYYY-MM-DD, N position(s) open"` | — |
| **[D5]** Kill-switch | runner.py:728 | `logger.warning("D5: STOP_FILE present ({path}) on {date}...")` | Y | SYSTEM | CRITICAL | `"STOP_FILE: entries halted for {date}. Existing positions exit normally. Remove {name} to resume."` | — |
| **[C2-ROLL]** Roll fail (CLOSE) | runner.py:661 | `logger.critical("C2: roll CLOSE failed ...")` | Y | ROLLOVER | CRITICAL | `"C2: Roll CLOSE failed {inst} ..."` | inst, direction, contracts |
| **[C2-ROLL]** Roll fail (OPEN after CLOSE) | runner.py:676 | `logger.critical("C2: roll OPEN failed ...")` | Y | ROLLOVER | CRITICAL | `"C2: Roll OPEN failed ... position FLAT"` | inst, direction, contracts |
| **[C2-ROLL]** Roll success | runner.py:692 | `logger.info("C2: roll complete ...")` | Y | ROLLOVER | INFO | `"C2: Roll {inst} ... close@{p} → open@{p}"` | inst, direction, contracts |
| **[1-DATA]** fetch_bars (thành công) | runner.py:746 | — | **N** | — | — | — | — |
| **[1-DATA]** C3: empty bars | runner.py:757 | `logger.warning("C3: fetch_bars empty for {inst}...")` | Y | SIGNAL | WARN | `"C3: empty bars for {inst} — possible feed gap; exits unaffected"` | inst, day |
| **[1-DATA]** E3: clock skew | runner.py:780 | `logger.error("E3: clock skew suspected — today={} but last bar={}...")` | Y | SIGNAL | ALERT | `"E3: clock skew — {N}d gap, entries skipped"` | delta_days, today, last_bar |
| **[2-SIGNAL]** signal_fn (thành công) | runner.py:794 | — | **N** | — | — | — | — |
| **[2-SIGNAL]** C1: signal_fn fail | runner.py:802 | `logger.error("C1: signal_fn FAILED on {date}: {exc}...")` | Y | SIGNAL | ALERT | `"C1: signal_fn failed — entries skipped for today"` | error |
| **[2-SIGNAL]** Regime capture | runner.py:812 | — | **N** (stored → dump_state `snap.regime`) | — | — | — | — |
| **[2b-GUARD]** G1 (chưa wire) | runner.py:853 | — | **N** (`if self._hmm_stale_guard is not None:` → False → skip) | — | — | — | — |
| **[B3 HALT gate]** entries blocked | runner.py:843 | `logger.critical("B3 HALT: N entry signal(s) BLOCKED...")` | Y | GUARD | CRITICAL | `"B3 HALT: N entry signal(s) blocked — broker/file mismatch; restart required"` | count, day |
| **[3-EXIT]** mark exits | runner.py:908 | — | **N** | — | — | — | — |
| **[4-DECIDE]** decide_day | live_decision.py | — (0 logger calls) | **N** | — | — | — | — |
| **[RETRY]** pending exits | runner.py:534 | `logger.warning("_retry_pending_exits: N position(s) exit_pending=True...")` | Y | EXEC | ALERT | `"retry_pending_exits: N CLOSE(s) retrying"` | count, day |
| **[RETRY]** CLOSE still fail | runner.py:558 | `logger.error("_retry: CLOSE still FAILED {inst}/{cluster}...")` | Y | EXEC | ALERT | `"retry: CLOSE still FAILED {inst}/{cluster}"` | inst, cluster, error |
| **[5-EXEC]** CLOSE fill (thành công) | runner.py:945 | `logger.info("C1 CLOSE: {inst} {dir} avg={} stop_ref={} slip={}...")` | Y | EXEC | INFO | `"CLOSE {inst} {dir} ×{n} @{price:.4f}"` | inst, direction, contracts, price, cluster |
| **[5-EXEC]** CLOSE fail I4.8 | runner.py:963 | `logger.warning("I4.8: CLOSE FAILED {inst}/{cluster}...")` | Y | EXEC | ALERT | `"I4.8: CLOSE FAILED {inst}/{cluster} — exit_pending=True"` | inst, cluster |
| **[5-EXEC]** STP cancel (sau CLOSE) | runner.py:974 | `logger.info/error("STP: cancelled / cancel_order FAILED...")` | **N** | — | — | — | — |
| **[5-EXEC]** F3 fat-finger (same-day) | runner.py:999 | `logger.error("F3: FAT_FINGER BLOCKED: {inst}...")` | Y | RISK | CRITICAL | `"FAT_FINGER BLOCKED: {inst} {n} contracts > max {max} — order NOT sent"` | inst, ordered, max |
| **[5-EXEC]** same-day OPEN+CLOSE (STRESS_MID) | runner.py:1006–1011 | — | **N** | — | — | — | — |
| **[5-EXEC]** F3 fat-finger (multi-day) | runner.py:1045 | `logger.error("F3: FAT_FINGER BLOCKED...")` | Y | RISK | CRITICAL | same | inst, ordered, max |
| **[5-EXEC]** OPEN fill (multi-day) | runner.py:1081 | `logger.info("C1 OPEN: {inst} {dir} avg={} expected={} slip={}...")` | Y | EXEC | INFO | `"OPEN {inst} {dir} ×{n} @{price:.4f}"` | inst, direction, contracts, price, cluster |
| **[5-EXEC]** OPEN fail | runner.py:1074 | `logger.error("C1 OPEN FAILED: {inst} {dir}...")` | **N** | — | — | — | — |
| **[STP]** place_stop thành công | runner.py:1110 | `logger.info("STP: placed {inst} {dir} stop @ {stop} orderId={id}...")` | Y | ORDER | INFO | `"STP placed {inst} {dir} @{stop:.4f}"` | inst, direction, stop, order_id, cluster |
| **[STP]** place_stop fail | runner.py:1122 | `logger.error("STP: place_stop FAILED...")` | Y | EXEC | ALERT | `"STP: place_stop FAILED {inst} {dir} @ {stop} — no overnight stop protection"` | inst, direction, stop, cluster |
| **[5b-BREAKER]** HALT | runner.py:1137 | — (không logger riêng) | Y | GUARD | CRITICAL | `"BREAKER HALT: DD {pct}% — all new entries blocked"` | level, dd_pct |
| **[5b-BREAKER]** HALT_DAY | runner.py:1144 | — | Y | GUARD | ALERT | `"BREAKER HALT_DAY: daily loss {pct}% — entries blocked today"` | level, dd_pct, day_loss_pct |
| **[5b-BREAKER]** WARN | runner.py:1150 | — | Y | GUARD | WARN | `"BREAKER WARN: DD {pct}% — approaching limit"` | level, dd_pct |
| **[5b-BREAKER]** Recovery | runner.py:1156 | — | Y | GUARD | INFO | `"BREAKER OK: recovered from {prior_level}"` | level, dd_pct |
| **[5b-BREAKER]** Không đổi level | runner.py:1131 | — | **N** | — | — | — | — |
| **[6-PERSIST]** _persist_state thành công | runner.py:485 | — | **N** | — | — | — | — |
| **[6-PERSIST]** persist fail | runner.py:509 | `logger.error("B1: state persist failed...")` | Y | STATE | ALERT | `"B1: persist failed — state may not survive restart"` | error |
| **[7-DASH]** dump_state → live_state_data.js | runner.py:1297 | — | — | (flush self._events vào file) | — | — | — |
| **[7-DASH]** persist_match mismatch | runner.py:1350 | — | Y | STATE | WARN | `"persist count mismatch — in-memory and saved file differ"` | in_memory |
| **MAX_HOLD_EXIT** thành công | runner.py:584–610 | `logger.info("MAX_HOLD_EXIT: {inst}/{cluster} held={N}...")` | **N** | — | — | — | — |
| **MAX_HOLD_EXIT** CLOSE fail | runner.py:618 | `logger.error("MAX_HOLD_EXIT: CLOSE FAILED...")` | Y | EXEC | ALERT | `"MAX_HOLD_EXIT: CLOSE FAILED {inst}/{cluster} — retry at 14:05"` | inst, cluster, hold_days |

---

## 2. ⚠️ THIẾU EVENT — dashboard trống chỗ này

| Step thiếu event | Terminal có | Tác động dashboard |
|---|---|---|
| fetch_bars thành công | N | Dashboard không biết data đã fetch ("FEED" filter luôn rỗng) |
| signal_fn thành công (N entries) | N | Dashboard không thấy có bao nhiêu signal generated — chỉ thấy OPEN fill sau đó |
| decide_day | N | Không thấy admit/reject/halt decisions (chỉ thấy breaker event nếu level đổi) |
| same-day OPEN+CLOSE (STRESS_MID) | N | Dashboard không thấy stress trades chút nào — phantom trade |
| OPEN fail | logger.error | Event KHÔNG emit → dashboard không alert về order reject |
| STP cancel thành công/fail | logger.info/error | Dashboard không biết STP cancel trạng thái |
| B3 reconcile thành công | logger.info | Dashboard không biết startup OK |
| MAX_HOLD_EXIT thành công | logger.info | Dashboard không thấy position đóng vào buổi sáng |
| H4 equity sync | logger.info | Dashboard không thấy intraday equity update |
| breaker level KHÔNG đổi | N | Khi OK mỗi ngày → không có event (expected behavior, chỉ emit khi transition) |

**Category FEED: 0 events bao giờ** — button lọc trong dashboard sẽ luôn hiện trống.

**Categories emitted nhưng không có filter button:**
- `EXEC` — OPEN/CLOSE/retry fills: thấy trong ALL, không filter riêng
- `RISK` — F3 fat-finger: thấy trong ALL, không filter riêng
- `SYSTEM` — D5 kill-switch: thấy trong ALL, không filter riêng

---

## 3. CATEGORY → FILTER MAPPING

| Runner category | Dashboard category button | Notes |
|---|---|---|
| STATE | ✅ STATE | Runner started, Day started, persist fail |
| GUARD | ✅ GUARD | B3 halt, G1 transitions (khi wire), breaker transitions |
| SIGNAL | ✅ SIGNAL | Chỉ exceptions (C3/E3/C1 fail) — normal OK = 0 SIGNAL events |
| ORDER | ✅ ORDER | **Chỉ STP placed success** — OPEN/CLOSE fills KHÔNG phải ORDER |
| FEED | ✅ button có | **0 events bao giờ** — filter luôn rỗng |
| EXEC | ❌ không có button | OPEN/CLOSE fills, retry, I4.8, MAX_HOLD fail, STP fail — chỉ thấy ALL/level filter |
| ROLLOVER | ❌ không có button | C2 roll fail/success — chỉ thấy ALL/level filter |
| RISK | ❌ không có button | F3 fat-finger — chỉ thấy ALL/level filter |
| SYSTEM | ❌ không có button | D5 stop file — chỉ thấy ALL/level filter |

**Level filter** (CRITICAL/ALERT/WARN/INFO) lọc theo `e.level`, cross-category.
→ OPEN/CLOSE fill thường là INFO → thấy khi bấm INFO.
→ FAT_FINGER là CRITICAL → thấy khi bấm CRITICAL.

---

## 4. --print-signals (P0c) — terminal only, KHÔNG event

Nhánh `if a.print_signals:` (`run_live_day.py:264`) — return sớm, KHÔNG tạo FuturesRunner → KHÔNG `_emit_event` → KHÔNG `dump_state` → dashboard KHÔNG thấy.

**Format terminal print** (`run_live_day.py:301–324`):
```
====================================================================
SIGNAL PREVIEW — 2026-07-14
  regime:  Normal
  held:    0 position(s)
  bars:    MES=✓ 1741b  MNQ=✓ 1741b  MYM=✓ 1741b  M2K=✓ 1741b  MNKD=✓ 1734b
  entries: 2
  exits:   0

  ENTRY  MES   LONG  ×1  cluster=roska4_swing  exit=2026-07-17  exp_pnl=$+234
  ENTRY  MNQ   LONG  ×1  cluster=roska4_swing  exit=2026-07-17  exp_pnl=$+187
====================================================================
```
Fields per ENTRY: `inst`, `direction`, `×contracts`, `cluster`, `exit` (date), `exp_pnl` (pnl_sized).
Fields per EXIT: `inst`, `direction`, `×contracts`, `cluster`, `held_since` (entry_day).

→ **P0c bạn đọc TERMINAL**. Dashboard không liên quan đến --print-signals.

---

## 5. EVENT NÀO CÓ DATA NGAY vs CHỜ P0c/P2

### Có data MỖI NGÀY (ngay cả Calm + --dry-run scheduler)
> Lưu ý: `--dry-run` scheduler KHÔNG chạy run_live_day subprocess → KHÔNG có event nào từ runner. Phải chạy run_live_day thật (không --dry-run, hoặc chạy tay).

Khi run_live_day thật (P1 non-dry hoặc P2):

| Event | Điều kiện |
|---|---|
| `STATE` "Runner started: loaded N position(s)" | Mỗi lần run_live_day spawn |
| `STATE` "Day started: YYYY-MM-DD, N position(s) open" | Mỗi run_day() |
| `GUARD` "BREAKER OK: recovered from ..." | Chỉ khi level vừa đổi về OK |

### Chờ P2 (order thật, bất kỳ regime)
| Event | Điều kiện |
|---|---|
| `EXEC` "OPEN {inst} ×N @{price}" | Có entry + IBKR fill |
| `ORDER` "STP placed {inst} @{stop}" | Sau OPEN multi-day fill |
| `EXEC` "CLOSE {inst} ×N @{price}" | Có exit + IBKR fill |

### Chờ điều kiện lỗi / hiếm
| Event | Điều kiện |
|---|---|
| `SIGNAL` "C3: empty bars" | Feed gap (IBKR drop) |
| `SIGNAL` "E3: clock skew" | Timezone bug / stale data |
| `GUARD` "BREAKER HALT/HALT_DAY/WARN" | DD đủ lớn |
| `GUARD` "G1 HARD-STALE" | G1 chưa wire (I5.12) |
| `SYSTEM` "STOP_FILE" | Operator tạo D5 file |
| `RISK` "FAT_FINGER BLOCKED" | contracts_by_inst sai |
| `EXEC` "MAX_HOLD_EXIT CLOSE FAILED" | MAX_HOLD exit lỗi |

### Không bao giờ có event (thiếu, thêm sau runner-side)
- Fetch bars OK → "feed freshness" dashboard luôn trống (FEED filter)
- Signal generated N entries → không biết bao nhiêu signal trước khi order
- decide_day admit/reject per candidate → không thấy risk brain hoạt động
- same-day STRESS_MID fills → hoàn toàn im lặng với dashboard
