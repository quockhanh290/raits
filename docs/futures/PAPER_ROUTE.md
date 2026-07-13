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

## Trạng thái hiện tại (2026-07-12, offline xong)

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

**Tất cả offline đóng. Bug tiếp lộ TRONG P0b/P2 khi chạy thật.**

---

## P0b — SIGNAL PATH ⬅ BƯỚC TIẾP THEO (thứ Hai 2026-07-13+)

**Mục đích:** Verify signal fire đúng trong window 14:05-15:55 ET — không chỉ "có chạy".

**Lệnh:**
```
cd d:\raits
python -m global_index.run_live_day \
  --data-dir data/cache/futures \
  --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet \
  --regime-csv spy_daily_live.csv \
  --port 4002 \
  --print-signals
```

**Chuẩn bị trước khi chạy:**
```
# deploy_sim cùng ngày cùng CSV để so sánh:
python global_index/deploy_sim.py --regime-csv spy_daily_live.csv --end <ngày hôm nay>
# Ghi lại: regime hôm nay là gì, inst/direction/entry/stop nào backtest expect
```

**CỬA:** So deploy_sim CÙNG ngày CÙNG `spy_daily_live.csv`:
- `inst/direction/entry/stop` KHỚP → PASS
- Lệch (inst sai, stop khác) → signal bug → DỪNG điều tra
- "Có signal" ≠ "signal đúng" — must compare field-by-field

**Chấp nhận sai lệch:**
- P&L lệch = slippage (2-tick spread + MAX_HOLD drift ±$24 OK)
- entries=0 ngày cold-start OK nếu backtest cũng không có entry hôm đó

**Rủi ro:**
- Regime CSV khác giữa hai lần chạy → lệch giả (dùng cùng file)
- "entries > 0" không đủ: phải verify từng field

---

## P1 — TIMING TỰ ĐỘNG (1-2 ngày sau P0b)

**Mục đích:** Cron fire đúng 14:05 ET tự động không chạy tay.

**Lệnh:**
```
cd d:\raits
python -m global_index.run_scheduler --port 4002 --dry-run
# Để background (không block):
pythonw -m global_index.run_scheduler --port 4002 --dry-run
```

**CỬA:**
- Cron fire đúng 14:05 ET (log hiện `[LIVE_DAY] dry-run`) 1-2 ngày liên tục
- `next_run_time` = 14:05 ET (không phải 14:05 giờ máy)
- `job_maxhold` fire 09:31 ET đúng (nếu có MAX_HOLD position qua đêm)

**Rủi ro:** Scheduler sai giờ → fire sai bar → entry tại giá sai.

---

## P2 — ORDER THẬT (bước lớn — nhiều unknown-unknowns)

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
