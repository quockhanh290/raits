# PAPER_ROUTE — đường đi paper → live

Tài liệu này là **điểm vào cho thứ Hai (và mọi instance sau)** để không mất mạch.
Cập nhật khi qua từng cửa.

---

## Nguyên tắc

**Mỗi bước = CỬA.** Qua (verify đúng) mới sang bước sau.
Hỏng → DỪNG, điều tra, sửa, chạy lại. Không vội tuần tự.

**Paper trả lời 2 câu backtest KHÔNG trả lời:**
1. Code chạy đúng không? (execution runtime — bug chỉ lộ khi chạy thật)
2. Edge THẬT không? (P&L gần backtest? — 80% strategy tốt-backtest thất bại live)

**Đo trước khi tin:** mỗi path chạy thật lần đầu → đọc log thủ công, không background.

**Không vội live:** paper phải đủ lâu — nhiều tháng, nhiều regime/đêm/exit path, C1 N lớn.

---

## Trạng thái hiện tại (2026-07-30, P0c DONE — tiếp theo P1)

| Hạng mục | Trạng thái |
|----------|-----------|
| Logic backtest | VERIFIED — look-ahead/MAX_HOLD 09:30/TZ/entry fixed, reconcile 4/4 |
| Live execution code | COMPLETE — STP-VERIFY/retry/EMPTY-WARN/cold-start, bug fixes committed |
| Data discipline | DONE — backup/manifest/verify labels/append-only guard |
| Sweep | DONE — strategy-vs-live + TZ oracle 26/26 |
| P0a plumbing | PASS — connect/equity/positions/fetch/HMM trên code cuối |
| B1 verify_concat | PASS — 30/30 (3 runs), concat(frozen+live)→desired==backtest |
| B2 cron | PASS — ET-native 14:05/09:31, APScheduler 3.11.3, DST đúng |
| Account | CLEAN — broker []+file []+production key đúng+P0a không WARN |
| INVARIANTS | baseline 1.66/$40,919 \| floor 1.57 \| vault 2.77/3.39 \| STP residual -$573 |
| Splice fix | DONE 2026-07-13 — 3 bugs (anchor/dtype/MYM exchange), gap=0.00 all 5, frozen 23/23 |
| Pre-flight scheduler | DONE 2026-07-13 — update_ibkr_daily→spy_csv→run_live_day, fail-closed 2-branch |
| **P0b gate+logic** | **DONE 2026-07-13** — gate ✅ (Calm→no entry) logic ✅ (desired=backtest 53124) |
| **P0c live path** | **✅ DONE 2026-07-28/30** — NKD PASS + MYM/M2K PASS (xem section bên dưới) |
| **Monitor/Dashboard** | **DONE 2026-07-13/14** — xem section bên dưới |

---

## P0b — SIGNAL PATH (Calm day 2026-07-13)

### P0b-A: Gate + Logic ✅ DONE

- Gate: regime=Calm → 0 entries, 0 exits ✓ (live path, Gateway thật)
- Logic: `desired_basket()` = `backtest_swing_tf()` offline → MYM SHORT entry=53124 MATCH ✓
- Data: splice fix (gap=0.00 all 5, frozen 23/23, entry 53932→53124 = −808 exact) ✓

### P0b-B: Live Path 4-field ⏳ CHỜ Normal/Stress

Calm regime → no entry → không thể so `--print-signals` vs `desired_basket()`. = P0c.

---

## MONITOR/DASHBOARD — Trạng thái (2026-07-13/14)

### Loại 1 — IBKR real-time (commits f753b43, 50bd59e) ✅ VERIFIED
- Account equity, unrealized PnL, positions, open orders — 8s refresh
- ibkr_reader.py: equity CAD fix (BASE>USD>any) + reqAllOpenOrders() cho tất cả clientId
- Stale on disconnect: giữ data + dim + timestamp; clear chỉ khi backend offline
- Verified browser: equity $994,294, MESU6 position, STP order, SNAPSHOT divider

### Loại 2 — Regime (commits 68ab035, 7e8a690) ✅ VERIFIED END-TO-END
- runner.py: regime_fn param → dump_state hiện regime thật (không "Unknown")
- run_scheduler.py: `--live-state-path global_index/live_state_data.js` truyền vào run_live_day
- End-to-end: --dry-run → live_state_data.js `"regime": "Calm"` → dashboard hiện Calm ✓
- Reconcile GĐ0+STRESS PASS (diff $0.00) sau cả regime + events commits

### Loại 2/3 — Events OPEN/CLOSE/STP (commit f139fa5) ⏳ CODE DONE — FIRE ⏳ P2
- Code done + reconcile PASS — NHƯNG --print-signals không order → events chưa fire
- Verify fire đúng format/chỗ: chờ P2 (order thật)
- Bound 500 events đã có trong runner.py

### Control (start/stop runner) — CHƯA LÀM
- Bước riêng sau P2 — process control cẩn thận, không rush

---

## P0c — LIVE PATH 4-FIELD VERIFY ✅ DONE 2026-07-28/30

**Mục đích:** Verify live path `run_live_day → generate_today_signals → entries` ra đúng entry thật so với `desired_basket()` offline.

### Kết quả

| Instrument | Ngày | --print-signals | desired_basket() offline | Kết quả |
|------------|------|-----------------|--------------------------|---------|
| MNKD | 2026-07-28 | LONG entry=62720.00 stop=62601.43 | LONG entry=62720.00 stop=62601.43 | **PASS** ✅ |
| MYM | 2026-07-30 | LONG entry=52310.00 stop=52234.25 | LONG entry=52310.00 stop=52234.25 | **PASS** ✅ |
| M2K | 2026-07-30 | LONG entry=2949.20 stop=2944.78 | LONG entry=2949.20 stop=2944.78 | **PASS** ✅ |
| MES, MNQ | 2026-07-30 | None | None | **Consistent** ✅ |

### Bài học từ P0c

**1. Verify cần IBKR live bars (không thể dùng frozen parquet alone)**

Frozen parquet cắt tại ~13:45 ET; NKD signal fire trong cửa sổ 13:45–15:35 ET từ bars IBKR live.
Verify ban đầu dùng parquet-only → `desired_position()` = None hoặc sai direction.
Fix: `p0c_verify_mnkd.py` và `p0c_verify_swing.py` đều connect IBKR → `fetch_bars()` trước khi gọi engine.

**2. desired_position() = full backtest replay từ đầu**

Mỗi lần gọi `desired_position()` chạy lại toàn bộ backtest trên data concat.
Thêm bars (live window) có thể làm trade cũ close → trade mới open → direction đổi.
Không phải bug — đây là cơ chế đúng. Lý do cần bars live cùng cutoff với --print-signals.

**3. p0c_overnight.py auto-verify**

Khi `_has_swing_entry(output)` = True, job_print_signals() tự gọi `p0c_verify_swing.py`.
Luồng hoàn chỉnh: --print-signals → detect ENTRY → verify → save block cùng 1 file p0c_signals_MMDD.txt.

### Verify scripts (để dùng lại nếu cần)

```powershell
# NKD verify (khi có MNKD signal):
python p0c_verify_mnkd.py --port 4002 --client-id 91

# Swing verify (khi có MES/MNQ/MYM/M2K signal):
python p0c_verify_swing.py --port 4002 --client-id 92
```

---

## SCHEDULER — VẬN HÀNH (quan trọng, đọc trước khi chạy)

```powershell
cd d:\raits
pythonw -m global_index.run_scheduler --port 4002   # background, không block terminal
# Hoặc block (để xem log):
python -m global_index.run_scheduler --port 4002
```

**25 slots (tự động, mon-fri ET):**
- `09:31 ET` — MAX_HOLD exit (đóng vị thế qua đêm quá ngưỡng)
- `13:45 ET` — Pre-flight: `update_ibkr_daily` → `update_spy_csv` (blocking, 2 bước)
- `14:05 ET` — `run_live_day` initial slot (chỉ nếu pre-flight OK)
- `14:10–15:55 ET` — Continuous runner, mỗi 5 phút (22 slots) — TF entry capture
  _Lý do: 14:05 chỉ có 1 bar → 0% same-day TF capture. Xem run_scheduler.py docstring._

**Fail-safe (fail-closed):**
- Pre-flight fail bất kỳ bước nào → flag=False → live_day skip ngày đó
- Scheduler restart → flag=None → live_day skip (không đoán data fresh)
- `update_ibkr_daily` exit 1 nếu bất kỳ instrument nào không fetch được bars
- Kết quả: không bao giờ trade trên data không chắc chắn fresh

**⚠️ Giới hạn máy cá nhân:**
- Scheduler CHỈ chạy khi process sống. Sleep/reboot/crash → không tự phục hồi (chưa có systemd).
- Cần máy sống lúc job fire (09:31 ET và 13:45 ET). Không cần sống cả đêm (STP giữ tầng sàn).
- Restart scheduler sau reboot: `pythonw -m global_index.run_scheduler --port 4002` TRƯỚC 13:45 ET.

**Routine sáng (mỗi ngày trading):**
1. Check scheduler còn sống (nếu reboot qua đêm → khởi động lại trước 13:45)
2. `python global_index\check_next_entry.py` → xem regime hôm nay

**Polygon API key:** Truyền qua `--polygon-api-key KEY` hoặc env var `POLYGON_API_KEY`. Nếu thiếu → update_spy_csv fail → live_day skip.

---

## P1 — TIMING TỰ ĐỘNG ✅ DONE 2026-07-30

**Cách verify:** Start scheduler --dry-run, đọc startup log, kill. Không cần chờ cả ngày.

```
Jobs (25): maxhold_exit(09:31) + preflight(13:45) + live_day(14:05) + continuous 14:10→15:55
Scheduler TZ: America/New_York ✅  Port: 4002 ✅  dry-run: True ✅  Không lỗi.
```

---

## P2 — ORDER THẬT ⬅ BƯỚC TIẾP THEO (bước lớn — nhiều unknown-unknowns)

**Mục đích:** Lần đầu gửi order thật. Order path chưa chạy lần nào — bug chỉ lộ đây.

**Lệnh:**
```
cd d:\raits
python -m global_index.run_live_day \
  --data-dir data/cache/futures \
  --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet \
  --regime-csv spy_daily_live.csv \
  --port 4002
```

**Theo dõi cực kỹ lần đầu (đọc log thủ công):**
1. OPEN → fill: giá fill vs expected (C1 log: `C1 OPEN: ... slip=...`)
2. STP đặt ngay sau OPEN fill (`place_stop` log)
3. State persist: `live_positions.json` có entry + stop_price + stop_order_id
4. Cold-start sáng sau: B3 cross-check không HALT

**CỬA:** Order fill + STP đặt + state persist đúng.

**Rủi ro (chỉ lộ khi chạy thật):**
- Fill format IBKR: field name, timezone, partial fill
- STP orderId async: đã có retry 10×0.3s nhưng edge case có thể còn
- Timing: fill poll loop timeout
- `_persist_state` race: đã fix 4cec39e nhưng Windows atomic khác POSIX

---

## OVERNIGHT sau P2 — TWS RESTART (NGAY, không defer)

**Mục đích:** Verify STP survive TWS restart 17:00 ET — bug mỗi-đêm nghiêm trọng nhất.

**Khi nào:** Đêm ĐẦU có vị thế qua đêm = đêm đầu gặp restart. Không đợi phase riêng.

**Kiểm sáng hôm sau:**
```
python -m global_index.run_live_day --port 4002 --print-signals
# Đọc B3 log: STP-VERIFY, find_execution, openTrades
```

**CỬA:**
- B3 cold-start: STP-VERIFY thấy order trong `openTrades()` hoặc `find_execution()` → True
- KHÔNG false halt, KHÔNG double-STP
- `live_positions.json` giữ nguyên sau restart

**Rủi ro:**
- `ib.openTrades()` clear sau TWS restart → `get_order_status()` trả NOT_FOUND → STP-VERIFY gọi `find_execution()` (reqExecutions 2-day lookback)
- Nếu `find_execution()` False → HALT (đúng behavior — phải investigate TWS manually)
- Double-STP nếu cold-start gặp STP vẫn live + đặt STP mới → orphan SHORT

---

## P3+ — MONITOR (nhiều tháng)

**Mục đích:** Đo edge THẬT + execution sạch qua thời gian — không thể biết sớm hơn.

**Đo liên tục:**

| Metric | Ngưỡng | Hành động nếu vượt |
|--------|--------|-------------------|
| C1 slippage mean | ≤ 2 tick (~$25/trade MES) | Vượt → baseline optimistic → điều tra |
| Paper P&L vs swing-only backtest | Trong kỳ vọng | Lệch lớn → execution bug hoặc edge không thật |
| B3 reconcile | 0 mismatch mỗi cold-start | Mismatch → HALT đúng → investigate |
| STP-VERIFY | Không false halt | False halt → find_execution bug |
| Exit path coverage | Chandelier/MAX_HOLD/STP mỗi loại vài lần | Thiếu → chưa đủ để tin code đúng |

Monitor C1 scope note (2026-08-12): Paper dashboard applies the active
`monitor/paper_inputs.json` spec (`min_n=100`, `max_mean_ticks=5`,
`scope=separate`, `close_scope=stp_only`, `use_absolute=true`). Signal/market
CLOSE rows are excluded from C1 because the runner does not persist a clean
expected close reference; those exits are covered by Paper P&L vs backtest
instead.

**Benchmark P&L:** So **swing-only IS subset** (KHÔNG full $40,919 — NKD deferred).
Chạy: `deploy_sim.py --exclude-nkd` hoặc extract trades MES/MNQ/MYM/M2K+STRESS_MID.

**CỬA để nghĩ tới live:**
- Paper nhiều THÁNG (không tuần) — 30-60 ngày tối thiểu, hold nhiều ngày → nhiều tháng
- Nhiều regime (Normal + Stress đều thấy)
- Nhiều đêm TWS restart (không chỉ 1)
- Mỗi exit path (chandelier/MAX_HOLD/STP-triggered) vài lần
- C1 N đủ lớn (bias hệ thống lộ, không chỉ noise)

---

## Sau paper — hai nhánh

### Nhánh 1: Edge chứng minh (P&L gần backtest + execution sạch)

**VPS/ops trước tiên (đã defer từ paper):**
- NTP sync (clock drift → wrong bar)
- systemd / Windows Service auto-restart (cron cần alive 24/7)
- APScheduler misfire policy (nếu process restart lỡ fire time)
- Monitoring / alerting (không chạy → không biết)
- Paper máy cá nhân thiếu tầng này → làm TRƯỚC live tiền thật

**Live tiền thật:**
- 1 micro contract (DD cap 15%, không all-in)
- Scale dần CHỈ SAU live 1 micro chứng minh (không vội nhiều contract)
- Benchmark lại vs full $40,919 sau khi add NKD

### Nhánh 2: Paper thất bại (P&L << backtest)

- Biết sớm (mất ít, không tiền thật) — paper làm đúng vai trò
- Không live — giữ kỷ luật
- Giữ kỹ năng/công cụ (falsification/reconcile/oracle) cho hệ sau

---

## Deferred (sau paper, không quên)

| Item | Khi nào | Lý do defer |
|------|---------|------------|
| **NKD** | Sau Rule 576 cert | Paper P&L so swing-only subset, không full $40,919 |
| **STRESS_MID** | Sau P2 ổn | Cần cron 10:15 ET + `stress_bars_1015` populate (Phase C2) |
| **Ratchet STP** | Post-paper | Recover -$573 residual; paper dùng fixed entry-stop |
| **UI monitoring** | Sau P2 (thấy log thật) | Build mù = xây sai. Structured log prefix giai đoạn ngay; UI đầy đủ sau |
| **Oracle mở rộng** | Bất cứ lúc | Test concat live-vs-frozen tz khác (bắt layer-4 TZ offline) |
| **VPS/ops** | Sau paper, trước live | Paper máy cá nhân OK; live cần reliable infra |

---

## Files tham chiếu nhanh

| File | Dùng khi |
|------|---------|
| `docs/futures/INVARIANTS.md` | Verify baseline/floor không drift |
| `docs/futures/OPERATIONS.md` | Runbook B3/D5/E1/circuit breaker |
| `docs/futures/DIVERGENCE_SWEEP.md` | strategy-vs-live path analysis |
| `global_index/verify_concat_desired.py` | Re-verify concat oracle sau code change |
| `global_index/verify_account_clean.py` | Verify account clean trước P2 |
| `global_index/verify_runner_real.py` | Baseline reconcile (deploy_sim == runner) |
| `TASK.md` (sub-task "Futures signal pipeline") | Detailed history + completed items |
