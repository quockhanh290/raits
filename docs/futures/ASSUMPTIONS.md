# Futures — ASSUMPTIONS
_Số CHƯA đo + basis + verify-when._
_Cập nhật: 2026-07-06_

> **Mục đích:** Chống "số-đoán-dùng-như-fact".  
> Mọi số trong bảng này là CHƯA ĐO trong production. Không dùng để ra quyết định live cho đến khi verified.

---

| Assumption | Giá trị hiện dùng | Basis | Verify when | Impact nếu sai |
|---|---|---|---|---|
| Entry fill timeout | 30s | Design: 6× expected fill time | Paper — đo real fill time | Block time worst-case 265s sẽ sai; schedule timing affected |
| Exit fill time | 5s | Design assumption | Paper — đo real market exit | Block time sai |
| Block time worst-case | 265s | order_count × fill_time (MEASURED × ASSUMED) | Paper — real fill time thay | Runner schedule, EOD timing |
| Fill rate | ~100% (fill-at-price) | Backtest assumption | Paper — đo skip rate thực tế | P&L thấp hơn $52,936 nếu miss nhiều |
| Slippage 2-tick/side | Baseline assumption | `baseline_fit_c.txt` | Paper — so paper fills vs backtest | Nếu >2-tick → P&L thấp hơn |
| Roll slippage cost | Không ước tính | — | Paper — đo roll cost khi lăn hợp đồng | P&L chưa account for; expectation unknown |
| 2-micro MaxDD = $3,810 (@$55,784) | Đo deploy_sim re-run 2026-07-08; scaling_dd_trust.py có NKD bug → $5,890 overstated | IS backtest n=2 deploy_sim | Paper — MaxDD thật với 2 micro live | Sizer threshold ước tính ~$58-59k (tự tham chiếu, chưa đo; cần --account 59000) |
| chandelier mult 2.5 | Validated-by-outcome | Design — không phải WFO-derived | Không cần verify thêm (design choice, not fit) | — |
| STRESS_MID cứu bear tiếp theo như 2022 | IS 2022 bear: +$6,632 | Một event (COVID bear); bootstrap p=0.112 không-sig; OOS 2025 −$44 | Live bear period | Nếu không generalize: cost $0-44/năm (không block deploy); cân nhắc bỏ sau live evidence đủ |
| STRESS_MID không false-active trong non-bear | Regime-gated (Stress only, round params) | Design assumption; chưa live test | Paper/live Stress period | False Stress activation → drag; có thể tệ hơn hedge giả thuyết |

---

## Lịch sử assumption đã sửa

| Assumption cũ | Giá trị sai | Giá trị đúng | Sửa khi | Commit |
|---|---|---|---|---|
| 2-micro MaxDD | $9,854 | $5,890 | scaling_dd_trust.py | ee75963 |
| 2-micro MaxDD (tiếp) | $5,890 (NKD bug inflate) | $3,810 (@$55,784) | deploy_sim re-run | 2026-07-08 |
| Scaling threshold | $82k (manual buffer) | $55,784 (dùng MaxDD@$50k) | scaling_dd_trust.py | ee75963 |
| Scaling threshold (tiếp) | $55,784 (tự tham chiếu lỗi) | ~$58-59k (ước tính, chưa đo; cần --account 59000) | SCALING_ANALYSIS.md | 2026-07-08 |
| HMM stability | 98.5% agreement | 68% actual | hmm_stability_measure.py | (stocks trust audit) |
| STRESS_MID 2022 standalone | $5,296 | $6,632 (fit_C stronger) | stress_mid_trust.py | ee75963 |
| MaxDD fit_C | $5,185 (old pre-NKD) | $2,789 | baseline_fit_c.txt | 23161a1 |