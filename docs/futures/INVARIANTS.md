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
| Baseline deploy = **$42,459 / Calmar 1.72** (frozen, 2-tick, causal, MAX_HOLD 09:30, global_nkd 6%) | `deploy_sim --data-dir data\cache\futures\frozen_sim --nkd-parquet global_index/data/NKD_frozen_2024.parquet --regime-csv spy_daily_live.csv --end 2024-12-31 --n-contracts 1 --slippage-ticks 2` → net=$42,459, Calmar=1.72, MaxDD=$3,574 (7.1%) | 2-tick + causal + 09:30 ET MAX_HOLD exit convention. **[2026-08-04] global_nkd cap 2%→6%** — NKD had stopped trading entirely in the 2026 regime (94.1% of days over the $1,000 sleeve). Deprecated: $40,919/1.66 (nkd cap 2%). Deprecated: $41,266/1.72 (bar-0 exit, 2026-07-10). Dirty: $47,186/2.38 (look-ahead). |
| fit_A degradation floor = **Calmar 1.65** (frozen, 2-tick, causal, MAX_HOLD 09:30, global_nkd 6%) | `deploy_sim --data-dir data\cache\futures\frozen_sim --nkd-parquet global_index/data/NKD_frozen_2024.parquet --regime-csv spy_daily_live.csv --end 2024-12-31 --hmm-fit-end 2022-12-31 --n-contracts 1 --slippage-ticks 2` → Calmar=1.65, net=$42,565, MaxDD=$3,744 (7.5%) | floor/baseline=95.9% (1.65/1.72) — headroom **+4.2%**, hẹp hơn mức +5.7% trước khi nâng cap. Tight nhưng baseline > floor ✓. Deprecated: 1.57 (nkd cap 2%). Deprecated: 1.53 (bar-0 exit). Dirty floor 2.04 deprecated (look-ahead). |
| *_frozen_2024.parquet KHÔNG UPDATE | `ls -la data/cache/futures/*_frozen*` → mtime KHÔNG thay đổi sau khi tạo | Frozen = ground truth; update phá reproducibility |
| frozen_sim/ = staging dir cho deploy_sim | `ls data/cache/futures/frozen_sim/` = 4 file *_8y.parquet (copy từ *_frozen_2024) | deploy_sim hardcodes filename _8y.parquet; frozen_sim là shim layer |
| Live parquet (*_8y) chỉ append qua ibkr_daily | `python -m global_index.update_ibkr_daily` — KHÔNG dùng `update_futures_data.py` trên *_8y | update_futures_data overlap-replaces 30 ngày → lịch sử dịch → baseline drift (A5 incident: $151 offset so với frozen) |
| Trước bất kỳ Databento re-fetch (update_futures_data): tạo frozen copy trước | verify frozen tồn tại, baseline match, rồi mới chạy | Mỗi Databento re-fetch thay thế overlap window → giá lịch sử lệch → mất reproducibility |
| Vault 2023-2024 = **GO** (frozen, 2-tick, causal, MAX_HOLD 09:30) | `deploy_sim --data-dir data\cache\futures\frozen_sim --nkd-parquet global_index/data/NKD_frozen_2024.parquet --regime-csv spy_daily_live.csv --start 2023-01-01 --end 2024-12-31 --hmm-fit-end 2022-12-31 --n-contracts 1 --slippage-ticks 2` → Calmar **2.86**, net=$10,757, PF=1.50, Sharpe=1.71, MaxDD=$1,899 (3.8%) | 2.86 > 1.65 floor ✓. Sau khi nâng cap: Calmar +3% nhưng Sharpe 1.80→1.71 và PF 1.51→1.50. Deprecated: 2.77/$10,415 (nkd cap 2%). Dirty: 3.08 (look-ahead). |
| Vault 2025 = **GO** (frozen_2025, 2-tick, causal, MAX_HOLD 09:30) | `deploy_sim --data-dir data/cache/futures/frozen_2025_sim --nkd-parquet global_index/data/NKD_frozen_2025.parquet --regime-csv spy_daily_live.csv --start 2025-01-01 --end 2025-12-31 --hmm-fit-end 2024-12-31 --n-contracts 1 --slippage-ticks 2 --include-stress` → Calmar **2.54**, net=$7,404, PF=1.54, Sharpe=1.74, MaxDD=$3,001 (6.0%) | 2.54 > 1.65 floor ✓ (biên +54%). ⚠️ **Kỳ xấu đi nhiều nhất sau khi nâng cap**: Calmar 3.39→2.54 (−25%), Sharpe 1.89→1.74, PF 1.62→1.54, MaxDD ~$2,174→$3,001 (+38%) đổi lấy +$33 lãi. 2025 là kỳ gần chế độ hiện tại nhất. Deprecated: 3.39/$7,371 (nkd cap 2%). Dirty: 3.35. |
| **Không sàn nào được đặt BÊN TRONG dải nhiễu của chính phép đo sinh ra nó** | `python futures/measure_seed_pnl.py` → lấy `[min, max]` của Calmar; mọi sàn phải nằm ngoài dải đó | Đo 2026-08-15: 5 seed của **cùng một hệ** cho Calmar **1.56–1.72**, và **2/5 nằm dưới sàn 1.65**. Sàn nằm trong dải không phân biệt được "hệ suy giảm" với "fit rơi vào cực trị khác". Số liệu: [CALMAR_PROVENANCE.md](CALMAR_PROVENANCE.md) §4b, §4c |
| ⚠️ Live Calmar floor 1.65 **đang vi phạm bất biến ngay trên** — chưa sửa, có chủ ý | xem CALMAR_PROVENANCE §4b "Chỗ còn hở" | Cổng promotion đã thoát nhiễu bằng cách **đo theo cặp** (luôn có 2 model để so). Theo dõi paper chỉ có 1 đường cong live + 1 hằng số nên không so cặp được. **Hệ quả vận hành: một lần Calmar paper < 1.65 CHƯA đủ để kết luận suy giảm** — chạy `measure_seed_pnl.py` xem con số có nằm trong dải nhiễu không rồi mới kết luận. Ba lựa chọn để đóng hẳn: §4b |
| Live Calmar floor = **1.65** (fit_A, frozen, 2-tick, causal, MAX_HOLD 09:30, global_nkd 6%) | vault result files — Calmar > 1.65 | 2-tick + causal + 09:30 convention. Vaults pass: 2.86 > 1.65 ✓, 2.54 > 1.65 ✓. Hardcode phải khớp: `runner.py` + `generate_replay_snapshots.py`. Deprecated: 1.57 (nkd cap 2%), 1.53 (bar-0 exit). Dirty floor 2.04 deprecated. |
| Vault deploy_sim dùng `--n-contracts 1` | grep `n_contracts` in vault result files | Vault phải pin n=1 (production config); auto-size cho vault window không có COVID → n=2-3 → config khác production |
| HMMEngine class không sửa interface | `git log --oneline raits/hmm/engine.py` | SHARED với stocks — xem `docs/SHARED.md` |
| Deploy dùng `label_regimes` không dùng `regime_coordinator` | `grep -n "label_regimes\|regime_coordinator" global_index/*.py` | Validated path |
| fit_C hash bất biến khi re-run refreeze | `python futures/test_refreeze.py` T1 | Deterministic anchored-expanding |
| Reconcile chain PASS sau mọi sửa `_validated_core` | Chạy gd0/stress/nkd/swing_desired (Phase 1) — tất cả PASS 2026-07-11 sau MAX_HOLD 09:30 fix | Engines locked |
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

---

## Chạy test KHÔNG được ghi vào bằng chứng runtime thật

**Sự cố có thật, 2026-08-29 (Stage 5ZZZ-Z → 5ZZZ-AA).** Chạy `python -m pytest scratch -q`
trên toàn bộ thư mục mà **không cô lập đầu ra**. Một test đi qua đường Swing live đã **ghi 2
dòng vào file bằng chứng runtime thật**:

```text
global_index/track1_runtime/signals/track1_signals_20260829.jsonl
  roska4_swing · TRACK1_SWING_1405 · mode shadow_live · 2 dòng
  ghi lúc 21:50:49 giờ máy = 23:50 ET, **thứ Bảy** — không slot nào chạy được
```

Hậu quả đo được: `replay parity` chuyển `roska4_swing` từ `NOT_YET_OBSERVED` sang **FAIL** cho
một slot chưa từng chạy. Cổng `PAPER_SHADOW_EVIDENCE` **không bị ảnh hưởng** (2026-08-29 không
vào cửa sổ 5 ngày), nhưng đó là may, không phải thiết kế.

### Luật

1. **Test ghi ra `tmp_path`, không bao giờ ghi vào `global_index/track1_runtime/`.**
2. **Không chạy cả `scratch/` một lượt** trừ khi đã cô lập đầu ra. Các suite ở đó gọi thẳng
   đường live.
3. Bằng chứng runtime là **append-only**: dòng bẩn **không được xoá, không được sửa**. Cách xử
   lý đúng là ghi một bản ghi *taint* (xem `global_index/track1_evidence_taint.py`) để bên đọc
   biết không được tin dòng đó. Xoá nó đi là làm giả lần thứ hai, êm hơn lần đầu.

### Chốt chặn đã cài

`track1_signals.append` gọi `_refuse_production_write_under_pytest`. Nó chỉ chặn khi **cả hai**
đúng: đang chạy dưới pytest (`PYTEST_CURRENT_TEST`) **và** đích nằm trong cây
`track1_runtime/`. Ghi vào `tmp_path` không bị chặn; scheduler không chạy dưới pytest nên
không bị ảnh hưởng. Test nào **cố ý** muốn ghi thật thì đặt
`TRACK1_ALLOW_RUNTIME_WRITE_IN_TEST=1` và nói rõ lý do.

Chốt chặn này hẹp có chủ đích. Chặn rộng hơn sẽ làm hỏng các test hợp lệ, và một chốt chặn hay
báo động giả là chốt chặn người ta học cách tắt.
