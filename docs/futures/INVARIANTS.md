# Futures — INVARIANTS
_Bất biến phải luôn đúng + cách kiểm tra._
_Cập nhật: 2026-07-11_

> Bất kỳ sửa nào vi phạm invariant = STOP, rollback, investigate.

---

> **[2026-07-10] Look-ahead bug fixed.** `backtest_swing_tf` entry scan trước đây retroactive: khi prior position đóng lúc 18:xx ET, entry scanner vẫn quét toàn bộ 14:00–15:55 → ghi entry tại 14:35 dù prior chưa close. Fix: `exit_ts_today` reset mỗi ngày; khi exit fire → lưu timestamp; entry scan chỉ xét bars SAU timestamp đó. Effect: P&L inflation 12.5% ($47,186→$41,266), Calmar 2.38→1.72. Look-ahead bidirectional (2025 causal 3.39 > dirty 3.35). **Tất cả số Calmar trong INVARIANTS này đã được cập nhật sang causal (clean).**
>
> _Dirty (deprecated) numbers: Baseline 2.38/$47,186 | Floor 2.04 | Vault 2023-24 3.08 | Vault 2025 3.35_

> **[2026-07-11] MAX_HOLD exit timing fixed: 00:00 ET → 09:30 ET (US futures only).** Stocks engine dùng `iloc[0]["open"]` trên RTH-only data = 09:30 ET. Futures 24h port kế thừa `hl[day][2][0]` = bar 00:00 ET (midnight) — sai so với intent gốc. Fix: `searchsorted` tìm bar đầu tiên ≥ 09:30 ET ngày exit (ET-aware, strip TZ trước `asi8` để tránh UTC offset bug). NKD (Asia/Tokyo TZ) guard riêng → vẫn dùng bar 0. Effect: baseline $41,266→$40,919, Calmar 1.72→1.66; vault 2023-24 Calmar 2.69→**2.77** (cải thiện); vault 2025 không đổi 3.39. Edge SỐNG. Live `run_maxhold_exit.py` cron 09:31 ET → live == backtest mốc đúng.
>
> _Pre-09:30-fix deprecated: Baseline 1.72/$41,266 | Vault 2023-24 2.69_

---

| Invariant | Cách check | Tại sao |
|---|---|---|
| **SLIPPAGE CONVENTION = 2-tick/side** (mọi verdict dùng `--slippage-ticks 2`) | grep `slippage` trong mọi vault/floor run | MNKD thin fills slip >1 tick thực tế; 1-tick = upper bound. Mọi số Calmar phải so trên cùng convention. |
| Baseline deploy = **$40,919 / Calmar 1.66** (frozen, 2-tick, causal, MAX_HOLD 09:30) | `deploy_sim --data-dir data\cache\futures\frozen_sim --nkd-parquet global_index/data/NKD_frozen_2024.parquet --regime-csv spy_daily_live.csv --end 2024-12-31 --n-contracts 1 --slippage-ticks 2` → net=$40,919, Calmar=1.66 | 2-tick + causal + 09:30 ET MAX_HOLD exit convention. Deprecated: $41,266/1.72 (bar-0 exit, 2026-07-10). Dirty: $47,186/2.38 (look-ahead). |
| fit_A degradation floor = **Calmar 1.53** (frozen, 2-tick, causal) | same + `--hmm-fit-end 2022-12-31 --slippage-ticks 2` → Calmar=1.53 | floor/baseline=89.0% — ratio ổn định ✓ (dirty ratio: 85.7%). Dirty floor 2.04 deprecated (look-ahead). |
| *_frozen_2024.parquet KHÔNG UPDATE | `ls -la data/cache/futures/*_frozen*` → mtime KHÔNG thay đổi sau khi tạo | Frozen = ground truth; update phá reproducibility |
| frozen_sim/ = staging dir cho deploy_sim | `ls data/cache/futures/frozen_sim/` = 4 file *_8y.parquet (copy từ *_frozen_2024) | deploy_sim hardcodes filename _8y.parquet; frozen_sim là shim layer |
| Live parquet (*_8y) chỉ append qua ibkr_daily | `python -m global_index.update_ibkr_daily` — KHÔNG dùng `update_futures_data.py` trên *_8y | update_futures_data overlap-replaces 30 ngày → lịch sử dịch → baseline drift (A5 incident: $151 offset so với frozen) |
| Trước bất kỳ Databento re-fetch (update_futures_data): tạo frozen copy trước | verify frozen tồn tại, baseline match, rồi mới chạy | Mỗi Databento re-fetch thay thế overlap window → giá lịch sử lệch → mất reproducibility |
| Vault 2023-2024 = **GO** (frozen, 2-tick, causal, MAX_HOLD 09:30) | `deploy_sim --data-dir data\cache\futures\frozen_sim --nkd-parquet global_index/data/NKD_frozen_2024.parquet --regime-csv spy_daily_live.csv --start 2023-01-01 --end 2024-12-31 --hmm-fit-end 2022-12-31 --n-contracts 1 --slippage-ticks 2` → Calmar **2.77**, net=$10,415, PF=1.51, Sharpe=1.80 | 2.77 > 1.53 floor ✓ (tăng từ 2.69 sau 09:30 fix). Dirty: 3.08 (look-ahead). Deprecated: 2.69 (bar-0 exit). |
| Vault 2025 = **GO** (frozen_2025, 2-tick, causal, MAX_HOLD 09:30) | `deploy_sim --data-dir data/cache/futures/frozen_2025_sim --nkd-parquet global_index/data/NKD_frozen_2025.parquet --regime-csv spy_daily_live.csv --start 2025-01-01 --end 2025-12-31 --hmm-fit-end 2024-12-31 --n-contracts 1 --slippage-ticks 2 --include-stress` → Calmar **3.39**, net=$7,371, PF=1.62, Sharpe=1.89 | 3.39 > 1.53 floor ✓ (biên +148%, không thay đổi sau 09:30 fix). Dirty: 3.35 (deprecated). |
| Live Calmar floor = **1.53** (fit_A, frozen, 2-tick, causal) | vault result files — Calmar > 1.53 | 2-tick + causal convention. Vaults pass: 2.69 > 1.53 ✓, 3.39 > 1.53 ✓. Dirty floor 2.04 deprecated. |
| Vault deploy_sim dùng `--n-contracts 1` | grep `n_contracts` in vault result files | Vault phải pin n=1 (production config); auto-size cho vault window không có COVID → n=2-3 → config khác production |
| HMMEngine class không sửa interface | `git log --oneline raits/hmm/engine.py` | SHARED với stocks — xem `docs/SHARED.md` |
| Deploy dùng `label_regimes` không dùng `regime_coordinator` | `grep -n "label_regimes\|regime_coordinator" global_index/*.py` | Validated path |
| fit_C hash bất biến khi re-run refreeze | `python futures/test_refreeze.py` T1 | Deterministic anchored-expanding |
| Reconcile chain PASS sau mọi sửa `_validated_core` | Chạy gd0/stress/nkd/swing_desired | Engines locked |
| events[] bounded 500 (UI) | `grep -n "events" global_index/runner.py` | Memory guard J2 lesson |
| Position + breaker-state persist atomic one write | Check `_persist_state()` dùng `.tmp + os.replace` | Crash-safe restart |
| CircuitBreaker HALT = computed, không stateful flag | `grep -n "halted" global_index/runner.py` | recover từ peak_equity persist |
| CSV = Polygon corrected (không freeze-2017) | Check `spy_daily.csv` source trong `futures/basket.py` comments | Data correct prereq vault |
| `mult=2.5` sync deploy_sim ↔ signal_layer | `grep -n "ROSKA4_MULT\|NKD_MULT\|roska4_mult\|nkd_mult" global_index/*.py` | Signal/sim mismatch |
| IBKRBroker C3/C5/C6 specs không bypass | `python global_index/test_ibkr_injection.py` → 14/14 PASS | Hardwired specs |
| HMM stale guard tests PASS | `python global_index/test_hmm_stale.py` → 42/42 PASS | Guard logic |
| Refreeze tests PASS | `python futures/test_refreeze.py` → 68/68 PASS | Gate + rollback + T12 skip-invalid |
| `refreeze_hmm` anchor = "2017-01-01" | `grep -n "anchor" futures/refreeze.py` → default="2017-01-01" | anchor=2018 → clips 2017 data → $49,225 (wrong) |
| `update_spy_csv` KHÔNG chạy trong backtest | Run script manually live-only, không gọi từ backtest path | IS/OOS boundary 2024-12-31; fetching 2025+ data sẽ phá boundary |
| **SPY update = snapshot-trước + verify-labels-cũ** | `update_spy_csv.py` tự động: (1) copy vault2025.csv → `spy_snapshots/<stem>_snapshot_<last_date>.csv` trước fetch; (2) verify historical prices unchanged sau write. Log WARNING nếu bất kỳ pre-overlap price thay đổi | Polygon retroactive dividend re-adjustment có thể shift labels; snapshot cho phép diff và rollback nếu cần |
| NKD structural n=1 (không scale cùng Rổ4) | `grep "contracts_by\[" global_index/deploy_sim.py` → `contracts_by[NKD] = 1` | Budget 2% × $50k = $1,000; 1 MNKD risk ≈ $437 < $1,000; n=2 risk=$875 borderline; n=3 reject → không scale cùng Rổ4 dù n_contracts > 1 |
| Sizer: production n=1 từ full IS (COVID) | `python global_index/run_smoke_test.py → assert N==1` | COVID 2020 trong IS → max DD lớn → n=1. Subset không có COVID → auto-n=2-3. Guard warning in deploy_sim khi `--start/--end` không có `--n-contracts` |

---

## Invariant bị phá → làm gì

1. **STOP** — không commit
2. `git stash` hoặc revert thay đổi
3. Trace root cause (đọc code path, không đoán)
4. Ghi vào `futures/OPEN_QUESTIONS.md` nếu cần quyết định
5. Chỉ commit sau khi invariant restore
