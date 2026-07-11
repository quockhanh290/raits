# Futures — OPEN QUESTIONS
_Câu hỏi chưa giải quyết + blocker + priority._
_Cập nhật: 2026-07-06 (CSV correction session)_

Format: **Câu hỏi** | Priority | Blocker | Status

---

## Bug Sweep — Offline cạn (2026-07-08)

**Offline sweep đã cạn: 6 cách quét, 0 HIGH tìm thấy. Lớp còn lại = IBKR-gated.**  
Status: CLOSED — không cần tiếp tục offline sweep  
6 cách quét: Sweep 1-3 (5 zone: REGIME/SIGNAL/DATA/NUMERICAL/MULTI-DAY), Sweep 4 (fuzzing/interaction/adversarial 15 scenarios), Sweep 5 (config combo/coverage/reconcile-self-check/long-run/unexplored).  
Kết quả: 2 HIGH fixed (Zone 4 + 2 protected edges), 1 MEDIUM-LOW F1 (monitor), 1 LOW F2 (diagnostic only), 1 structural F3 (documented).  
Paper là test đúng nơi cho lớp còn lại: fill failure thật, IBKR reconnect, clock skew thật, HMM stale thật.

**F1 — NaN 1m bars: chandelier không fire — monitor khi IBKRBroker wired**  
Priority: LOW (monitor, không block paper)  
Note: `_swing_cache()` không dropna trên 1m arrays → NaN stop → position giữ đến MAX_HOLD (backstop finite). Clean CME data không trigger. Khi wire IBKRBroker: log warning nếu NaN xuất hiện trong intraday bars.  
→ `futures/_validated_core.py` `_swing_cache()` lines ~203-228; ISSUES_LOG.md F1

**F2 — real_risk() deploy_sim không raise nếu ATR all-NaN**  
Priority: LOW — diagnostic script only, live path safe  
Note: `deploy_sim.py:real_risk()` dùng `median()` fallback → NaN silently. Khác `signal_layer._asof_naive()` đã có ValueError guard (I4.9). Cap bypass xảy ra trong deploy_sim nếu ATR all-NaN — không phản ánh live behavior.  
→ `global_index/deploy_sim.py:198-205`; ISSUES_LOG.md F2

---

## Đang chờ Paper

**Fill time thật: entry 30s / exit 5s có đúng không?**  
Priority: HIGH  
Blocker: cần paper fills thật  
Note: 30s = 6× expected. Block time worst-case 265s dùng assumed fill time này.  
→ `futures/ASSUMPTIONS.md` row "Entry fill timeout"

**Fill rate: backtest assume ~100% fill-at-price. Thực tế paper bao nhiêu?**  
Priority: HIGH  
Blocker: paper mode  
Note: SKIP logic (entry unfilled → skip) chưa được đo rate thật.

**Slippage thật vs 2-tick/side baseline**  
Priority: HIGH  
Blocker: paper fills  
Note: `deploy_sim` default 1-tick là upper-bound tham chiếu, KHÔNG phải baseline. Baseline = 2-tick/side từ `baseline_fit_c.txt`. Paper slippage > 2-tick → P&L < $52,936.

**Vault Calmar fragile (47% swing giữa các năm)**  
Priority: MEDIUM  
Status: MEASURED — swing đã biết. Quyết định: dùng full-Calmar gate, vault mang tính informational.  
Note: không cần action thêm; ghi để nhớ không panic nếu single-year Calmar thấp.

---

## Đang chờ IBKR

**H4 fix (runner.py equity sync) là điều kiện cứng trước IBKRBroker live — không optional**  
Priority: **HIGH** (PREREQ trước paper/live)  
Status: FIXED (2026-07-07) — `global_index/runner.py` sync sau CLOSE loop, T29 PASS  
Lý do quan trọng: HALT_DAY (4% daily loss gate) là stated safety mechanism. Nếu không sync, `state.equity` không đổi trong session → HALT_DAY không bao giờ fire → live chạy không phanh intraday. Worst-case 1 ngày không có brake: ~$3,000–3,750 (6–7.5% of $50k). WARN dead (I4.2) là design decision (không cần fix). H4 là implementation bug (đã fix). Verify: chạy `python global_index/test_operational_fixes.py` → T29.1+T29.2 PASS.

**C2 Rollover — wire _handle_rollover() + 3 nuances cần đo**  
Priority: **HIGH** (before go-live — first roll là Mar 2026, MNQ/MES/MYM/M2K Mar 13, NKD Mar 6)  
Blocker: IBKR account (send_order live path phải xác nhận trước)  
Status: skeleton done (get_roll_event ✓, ROLL_SCHEDULE 2026 ✓), _handle_rollover raises NotImplementedError  
ROLL_SCHEDULE 2026: MES/MNQ/MYM/M2K → Mar 13, Jun 12, Sep 11, Dec 11; NKD → Mar 6, Jun 5, Sep 4, Dec 4  
**Nuance 1 — Roll slippage cost (optimism source #2 sau fill):**  
  Backtest dùng continuous contract (miễn phí, không trả roll cost). Live tốn ~16 rolls/năm × slippage mỗi chiều.  
  MES tick=$1.25 → 2-tick roll = $2.50/contract/roll × 16 = $40/năm — nhỏ nhưng cần đo paper.  
**Nuance 2 — Position roll qua calendar spread:**  
  Khi roll, close front_month + open next_month → 2 fills. P&L jump do price convergence?  
  chandelier stop recompute cho next_month contract? runner.state.open_positions giữ entry_day, chỉ contract_month đổi.  
  OpenPos.contract_month field chưa có (ghi "TBD" trong code) → cần add trước khi wire.  
**Nuance 3 — Roll timing vs session:**  
  _handle_rollover() gọi start-of-run_day — TRƯỚC signal gen. Cần fill confirm trước session mở?  
  Conflict nếu runner dùng EOD timing? Chốt sau IBKR timing decision.

**Runner timing EOD vs intra-session (265s block)**  
Priority: MEDIUM  
Blocker: IBKR account  
Note: 265s = order_count × assumed fill_time. Cần quyết định schedule timing.

**IBKRBroker C6: IBKR thực sự trả UPPERCASE OHLCV?**  
Priority: HIGH (trước paper)  
Blocker: IBKR account  
Note: C6 fix (lowercase) baked in nhưng chưa verify với live IBKR reqHistoricalData.

**IBKRBroker C3: out-of-order bars thực sự xảy ra với live backfill?**  
Priority: MEDIUM (trước paper)  
Blocker: IBKR account

**NKD: MNKD có trong CME bundle? Rule 576 cert?**  
Priority: HIGH (trước paper)  
Blocker: IBKR account

---

## Đang chờ Data / Live

**NKD sizing bug — scale chưa wired, nhưng projection sai khi n≥2**  
Priority: MEDIUM — sửa khi wire scaling  
Note: deploy_sim:234 `contracts_by[NKD] = n_contracts` (cùng Rổ4). Không cắn ở n=1 (risk≈$437 < budget $1,000). Nhưng scaling projection tại n=2 include NKD PnL ở n=2 (risk=$875, đôi khi pass guard) thay vì n=1 cố định → projection overstated khi ATR<400 pts.  
Sizer calibrate từ n=1 pass (NKD admitted) nhưng scaled replay có thể include NKD at n=2 → inconsistency trong DD projection.  
Fix: tách NKD sizing riêng — `contracts_by[NKD] = 1` luôn (MNKD budget 2% chỉ đủ 1 contract). Sửa trước khi wire scaling.

~~**Scaling projection $55,784 — verify NKD không scale cùng Rổ4**~~ — **CLOSED (2026-07-08)**  
Kết quả: NKD bug xác nhận trong `scaling_dd_trust.py` (scale NKD@n sai). deploy_sim đã fix (hardcoded n=1). MaxDD re-đo deploy_sim = $3,810 (@$55,784). Threshold self-referential → hội tụ ~$58-59k. Xem SCALING_ANALYSIS.md.

**Scaling threshold n=2 chính xác là bao nhiêu? (~$58-59k chưa confirm)**  
Priority: LOW — verify khi có intent scale thực sự  
Note: SCALING_ANALYSIS.md ước tính hội tụ ~$58-59k từ 2 data points ($50k→MaxDD $2,657; $55,784→MaxDD $2,908). Cần chạy `deploy_sim --account 59000 --n-contracts 1` để đo MaxDD@$59k → tính 20×MaxDD → confirm convergence. Chưa verify.

**cap×n unverified: scale cluster cap cùng n có giải quyết cap rejection không?**  
Priority: LOW — trước khi xem xét scale n=2  
Note: structural root cause là `capacity = (pct×account) / (n×mult×ATR×PV)` — capacity giảm 50% khi n×2. Fix: `cap = pct×account×n` → capacity giữ nguyên → cap rej biến mất → P&L ~2×, MaxDD ~2× → Calmar ≈ giữ nguyên. Chưa đo. Cần vault mới nếu wire (risk parameter thay đổi: gross exposure tăng 2×).

**vault n=2: IS Calmar baseline chưa established trong vault context**  
Priority: LOW — prerequisite trước deploy n=2  
Note: n=2 IS Calmar = 2.28 (đo qua deploy_sim, SCALING_ANALYSIS.md). Chưa có vault OOS n=2. Floor 2.38 là fit_A n=1 IS — không applicable trực tiếp cho n=2 (khác risk profile). Cần vault riêng tại n=2 để establish IS baseline + floor n=2 trước khi deploy.

**STRESS_MID — OOS validation chưa đủ, deploy as IS-bet**  
Priority: MEDIUM (monitor live, không block deploy)  
Evidence: IS 2022 bear (strong positive). OOS 2025: 7 trades = −$44 (directionally negative, noise). Bootstrap p=0.112 borderline.  
Cost in calm: $0 (hibernates). Cost 2025 (volatile, non-bear): −$44. Asymmetric → keep deployed.  
Logic (stress_mid.py): general rule (below VWAP + open → SHORT, 2:1 R:R), params are round defaults ("pooled vault used defaults") — không tune 2022.  
Deploy decision: full system (Rổ4+NKD+STRESS). STRESS = IS-bet hedge. OOS evidence accumulates in next bear period.  
Vault GO verdict scope: Rổ4+NKD = OOS-GO. STRESS = IS-only, OOS-pending-bear.  
Paper insufficient if calm — accept; STRESS OOS không có pre-live shortcut.

**update_spy_csv timing look-ahead risk**  
Priority: HIGH (before go-live)  
Blocker: cần xác định runner timing decision  
Note: regime T dùng spy close T-1. Nếu update_spy_csv chạy intra-session (trong khi run_day đang chạy), có thể dùng close T (same day) → look-ahead 1 ngày.  
Fix proposal: chạy update_spy_csv trước khi khởi động runner, không intra-session. Cần confirm với IBKR timing.

**update_spy_csv live test (Polygon fetch)**  
Priority: MEDIUM (before go-live)  
Blocker: cần POLYGON_API_KEY live + paper date  
Note: `fetch_spy_close()` đã wired (Polygon adjusted=True) nhưng chưa test end-to-end với real fetch.  
Test case: chạy với last_date = yesterday, expect 1 row returned, check date + close vs Polygon web.

---

## HMM Refit — Monitoring & Trigger

**Khi nào refit HMM tiếp theo?**  
Priority: LOW (không urgent — fit-2024 decode-forward đủ tốt cho 2026)  
Status: OPEN — theo dõi 2 trigger dưới

**Trigger 1 — Decode lệch thực tế:**  
Quan sát: fit-2024 có label Normal nhưng thị trường rõ ràng đang Stress (VIX > 30, SPY giảm >10% peak)?  
Nếu có → chạy compare_refit ngay, không đợi cuối năm.

**Trigger 2 — Sau paper 1-2 năm (OOS live bù):**  
Khi có đủ paper/live OOS 2026-2027 → refit gồm 2024-2025 không mất OOS evidence thực sự (có evidence mạnh hơn = live fills thay thế backtest).  
Dự kiến: cuối 2027 hoặc sau bear market cycle tiếp theo.

**Quy trình khi trigger:**  
1. Chạy `compare_refit_*.py`: đo % flip fit-cũ vs fit-mới trên period hiện tại  
2. Nếu < ~15% flip VÀ không có miss rõ ràng → giữ fit cũ (đo lại sau 6 tháng)  
3. Nếu ≥ 15% flip HOẶC miss regime thật → refit + re-validate (baseline/floor/vault)  
4. Xem DECISIONS.md "Giữ fit-2024" + LESSONS.md L11 cho chi phí và criteria đầy đủ.

Note: Paper 2026 với fit-2024 = OOS live (model chưa thấy 2026) — mạnh hơn backtest OOS. Giữ fit-2024 không làm mất bằng chứng OOS.

---

## Đã đóng (giữ để reference)

**CSV freeze-2017 dividend bug** → RESOLVED 2026-07-06: chuyển Polygon adjusted=True, 80 label changes, deploy −0.05% ($52,936 vs $52,962), byte-for-byte verified.  
**Anchor=2018 bug** → RESOLVED 2026-07-06: sửa anchor=2017, production-identical 2.744, grep clean triệt để.  
**Rollback máy móc** → RESOLVED 2026-07-06: invalid field + skip-invalid, audit trail giữ, T12 8 cases pass.  
**Live 4.2% divergence nếu spy_daily.csv mismatch** → RESOLVED: corrected CSV deployed, 0 divergence.  
**Full test re-baseline sau CSV switch** → RESOLVED: 68/68 PASS, $52,936/2.744 confirmed.  
**Cat B reproducibility** → RESOLVED: corrected deterministic.  
**98.5% HMM stability claim** → RESOLVED (stocks question, không futures). Weekly retrain stability measured independently.  
**Vault 2023-2024 + 2025 GO** → RESOLVED 2026-07-06: Rổ4+NKD GO (3.33/2.99 > floor 2.38). Details: `vault_2023_2024_result.txt`, `vault_2025_result.txt`. STRESS_MID 7 trades 2025 = weak-bet / OOS-pending.  
**Vault config bug (n=3 vs n=1)** → RESOLVED 2026-07-06: vault auto-size calm window → n=3 ≠ production n=1. Fix: `--n-contracts 1` flag + warning in `deploy_sim`. Vault cũ (n=3, NKD=0) superseded.  
**Vault HMM contamination** → RESOLVED 2026-07-06: fit-2024 saw vault 2023-2024 → Calmar 4.52 (contaminated) vs 3.33 (clean), +1.19 qua MaxDD artifact. Clean run sealed. Rule: fit trước test period.  
**NKD 0 trades vault** → RESOLVED 2026-07-06: symptom của vault n=3 bug → NKD risk $1,312 > budget $1,000. Fix: pin n=1. NKD 125+57 trades trong vaults (2023-2025).  
**Sizer bug audit** → RESOLVED 2026-07-06: grep toàn bộ scripts gọi `size_combined`. Hai chỗ sai: `deploy_sim` subset không pin (fix: `--n-contracts 1` + guard warning) + `generate_replay_snapshots.py:142` NKD bug (fix: `= 1`). Tất cả production scripts n=1.