# Stocks — ASSUMPTIONS
_Số CHƯA đo + basis + verify-when._
_Cập nhật: 2026-07-06_

> **Mục đích:** Chống "số-đoán-dùng-như-fact".  
> Mọi số trong bảng này là CHƯA ĐO đầy đủ. Không finalize live cho đến khi verified.

---

| Assumption | Giá trị hiện dùng | Basis | Verify when | Impact nếu sai |
|---|---|---|---|---|
| SPY adjustment impact trên HMM labels | "nhỏ" ~24 ex-div days/năm | Ước, chưa đo | Measure trước Vault 2025 — viết script compare split-only vs dividend-adjusted labels | Regime misclassification → P&L sai; stability numbers (churn 1.1%) dựa trên split-only data |
| Stability (churn 1.1%) đúng với dividend-adjusted SPY | Chưa biết | Measured trên split-only | Re-check sau khi SPY adjustment issue resolved | Churn có thể cao hơn; inversions có thể > 0 |
| Gap 1 live P&L impact = $312.72 backtest optimism | Measured IS only | `verify_live_path.py --live-feed --costs` | Check trên fresh OOS data | OOS optimism có thể khác IS |
| VWAP_MR P&L với ETF universe | Unknown | Chưa test | Run `vwap_mr_etf_sim.py` sau ETF fetch | Có thể re-add strategy nếu p<0.05 |
| annual vs weekly: artifact hoặc structural? | Structural (preliminary) | `hmm_retrain_artifact_check.py` committed | Run artifact check | Nếu artifact → annual advantage inflated |

---

## Lịch sử assumption đã sửa

| Assumption cũ | Giá trị sai | Giá trị đúng | Sửa khi | Commit |
|---|---|---|---|---|
| HMM stability "98.5% agreement" | 98.5% | 68% actual | hmm_stability_measure.py | Trust audit session |
| "3/6 convergence fail" | 3/6 fail | 6/6 converge | hmm_annual_convergence.py | Trust audit session |
| COVID recall | 91.6% (claimed) | 100% actual | hmm_stability_measure.py | Trust audit session |
| 2022 bear recall | 80.2% (claimed) | 88.6% actual | hmm_stability_measure.py | Trust audit session |