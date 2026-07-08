# Futures — INVARIANTS
_Bất biến phải luôn đúng + cách kiểm tra._
_Cập nhật: 2026-07-06_

> Bất kỳ sửa nào vi phạm invariant = STOP, rollback, investigate.

---

| Invariant | Cách check | Tại sao |
|---|---|---|
| Baseline deploy = $52,936 (corrected) | `python global_index/verify_runner_real.py ...` → diff=$0.00 | Corrected baseline sau CSV switch |
| Vault 2023-2024 = GO (sealed) | `vault_2023_2024_result.txt` — Calmar 3.33 (clean) / PF 1.73 / n=1 / NKD 125 trades | HMM-clean (fit-2022), n=1 production config; 3.33 > 2.38 floor ✓ |
| Vault 2025 = GO (sealed) | `vault_2025_result.txt` — Calmar 2.99 / PF 1.57 / n=1 / NKD 57 trades | Fully clean OOS (HMM fit-2024, test 2025); 2.99 > 2.38 floor ✓ |
| Vault Calmar floor = 2.38 (fit_A) | vault result files — Calmar > 2.38 | fit_A degradation floor; không dùng Calmar≥1 làm ngưỡng |
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
| NKD structural n=1 (không scale cùng Rổ4) | `grep "contracts_by\[" global_index/deploy_sim.py` → `contracts_by[NKD] = 1` | Budget 2% × $50k = $1,000; 1 MNKD risk ≈ $437 < $1,000; n=2 risk=$875 borderline; n=3 reject → không scale cùng Rổ4 dù n_contracts > 1 |
| Sizer: production n=1 từ full IS (COVID) | `python global_index/run_smoke_test.py → assert N==1` | COVID 2020 trong IS → max DD lớn → n=1. Subset không có COVID → auto-n=2-3. Guard warning in deploy_sim khi `--start/--end` không có `--n-contracts` |

---

## Invariant bị phá → làm gì

1. **STOP** — không commit
2. `git stash` hoặc revert thay đổi
3. Trace root cause (đọc code path, không đoán)
4. Ghi vào `futures/OPEN_QUESTIONS.md` nếu cần quyết định
5. Chỉ commit sau khi invariant restore