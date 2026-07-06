# RAITS — Global Index Expansion (NKD) — Tổng hợp

**Trạng thái:** Hoàn tất nghiên cứu/backtest offline. Cấu hình deploy đã chốt và wired.
Phần còn lại chặn bởi IBKR account (giống Rổ 4).

**Cảnh báo đọc số:** Mọi kết quả dưới đây là **in-sample-broad** — cap, priority, param
đều chọn bằng cách nhìn data 2018-2024 nhiều lần; vault 2023-2024 đã contaminated.
Đây là *trần lạc quan*, không phải kỳ vọng live. Trọng tài thật là paper trade →
vault 2025 (còn sạch) → live nhỏ.

---

## 1. Mục tiêu & định vị

NKD = **Nikkei 225 USD futures (CME/GLBX)**. Đây là **equity index nước ngoài** — cùng
asset class với Rổ 4 (US index), **KHÔNG phải non-equity**, **KHÔNG phải diversification**.

- Tương quan với Rổ 4: ~0.6-0.85 (cùng factor equity, risk-off toàn cầu kéo cùng nhau).
- Mục đích: **tăng return** + **lợi thế timezone vận hành** — power-hour Nikkei (14:00-15:55
  JST) = ~12:00-13:55 trưa VN (giờ thức, giám sát được), trong khi Rổ-4 power-hour
  (14:00-15:55 ET) = ~02:00-03:55 sáng VN (giờ ngủ).
- Phân biệt với `nonequity/` (gold/crude — asset class khác thật, ~0 corr): gold NO-GO,
  crude data-blocked, đã đóng.

---

## 2. Đã làm gì (pipeline đầy đủ)

NKD đi hết mọi cổng như Rổ 4, không bỏ gate, không nới tiêu chí:

| Bước | Việc | File |
|---|---|---|
| Data | Fetch NKD continuous 1m 2018-2024 (GLBX, volume-roll), verify liquidity power-hour JST ổn định mọi năm (median 33-49/60 bar) | `fetch.py`, `_core.py` |
| Specs | NKD pv=$5/tick=$25; MNKD micro pv=$0.5/tick=$2.5 (verified CME) | `specs.py` |
| Edge | Power-hour transfer "như Rổ 4" qua **tz-convert** (data → Asia/Tokyo làm cửa sổ 14:00-15:55 thành power-hour JST, tái dùng *chính* `backtest_swing_tf` validated) | `swing_tf_powerhour.py` |
| Regime | SPY-HMM gate với mapping JST→ET **lookahead-safe** (phiên Nikkei ngày D dùng SPY regime D-1, đã verify không nhìn tương lai) | `regime.py` |
| WFO | Walk-forward rolling, chọn param theo Calmar ở **2× cost** (thước cost-thực cho micro mỏng), so gated vs agnostic | `wfo.py` |
| Vault | One-shot 2023-2024, param đóng băng, có guard `--i-understand-one-shot` | `vault.py` |
| Combined | Gộp NKD + Rổ 4, đo combined Calmar/DD + cross-stream correlation (cửa quyết định "có đáng thêm không") | `combined.py` |
| Risk layer | Multi-cluster exposure (Rổ4-swing / Rổ4-stress / NKD độc lập, DD cap gộp account) | `net_exposure_multi.py` |
| Full system | Replay qua risk layer + circuit breaker; bản deploy-realistic có sizer thật + risk$ thật | `combined_system.py`, `deploy_sim.py` |
| Diagnostics | risk$ thật / reject value / hold-vs-entry / cap sweep / priority sweep | `risk_diagnostic.py`, `reject_value_diagnostic.py`, `hold_vs_entry_diagnostic.py`, `cap_sweep.py`, `priority_sweep.py` |

---

## 3. Đạt được gì (kết quả số)

### NKD standalone (đã qua mọi cổng)

| Cổng | Kết quả |
|---|---|
| Edge full-history 2× cost (gated) | PF 1.57; ex-roll 1.48 (edge không phải roll artifact); mọi năm dương |
| WFO select@2× cost | gated OOS Calmar 2.25, agnostic 2.33; cả hai 6/6 folds dương |
| Vault 2023-24 (gated, 2× cost) | Calmar 2.51 — **nhất quán với WFO** (agnostic vault 2× sụp 0.87 → fragile) |

**Quyết định cấu hình NKD:** **gated, ema=10, mult=2.5.** Lý do: gated nhất quán WFO↔vault
ở cost thực (2×); agnostic thắng WFO 1× nhưng fragile ở vault 2× → loại vì không tổng quát
hóa dưới cost realistic.

### Kết hợp với Rổ 4 — NKD CẢI THIỆN portfolio

| Cấu hình | Calmar | MaxDD | Ghi chú |
|---|---|---|---|
| Rổ 4 + STRESS (alone) | 1.28 | $5,185 | trước NKD |
| + NKD (pooled thô) | 1.73 | $5,232 | combined.py |
| + NKD qua risk layer (deploy cuối, 2t) | **2.38** | **$2,911 (5.8%)** | deploy_sim, cap 5% + priority |

- **Cross-stream correlation +0.225** (thấp) → return đến lệch thời điểm (timezone lag) →
  **timing-smoothing thật**, không phải DD trùng pha.
- **MaxDD gần như không tăng** khi thêm NKD ($5,185→$5,232 pooled) → NKD thêm return gần
  như miễn phí về drawdown.
- **2022 (bear, Rổ-4 swing yếu):** NKD +$4,193 — gánh đúng năm khó.
- Mọi năm dương, không năm nào gánh (QQQ rule pass).

### Con số deploy cuối (cấu hình chốt, slippage 2t)

```
Calmar 2.38 | MaxDD 5.8% | return ~13.8%/yr | Sharpe 2.01 | 1 micro (DD-bound)
```
(+~3-4%/yr tiềm năng từ yield T-bill trên buffer ~$44k idle — xác nhận chính sách IBKR)

---

## 4. Quyết định kiến trúc then chốt

1. **tz-convert = "như Rổ 4 by construction".** Convert data NKD sang Asia/Tokyo trước khi
   gọi `backtest_swing_tf` → cửa sổ 14:00-15:55 tự thành power-hour JST, ngày cắt theo phiên
   Nhật, lễ TSE auto-skip. Tái dùng *chính* engine validated, không tái tạo dòng nào.

2. **Regime lookahead-safe.** Phiên Nikkei ngày D (JST ~05:00 UTC) xảy ra trước SPY close
   ngày D (21:00 UTC) nhưng sau SPY close D-1 → dùng SPY regime D-1. Đã verify không lookahead.

3. **Cluster độc lập, DD gộp.** Exposure budget tách per-cluster (NKD corr thấp + lệch giờ →
   không tranh slot với Rổ 4); nhưng drawdown cap **gộp** account-level (một tài khoản,
   risk-off toàn cầu kéo mọi cluster cùng ngày). Verify: thêm NKD không làm Rổ-4 bị reject
   thêm (cluster không rò).

4. **Cap 5% gross / 4.4% net** (Rổ-4 swing) — chọn bằng `cap_sweep`: Calmar cao nhất dưới
   target DD 10%, robust cả 1×/2× slippage. Cap cũ 4%/3.5% calibrate cho $500-stub, bóp 64%
   entry khi dùng real risk$ → sai. Real risk$ thật: MES $822, MNQ $1,399, MYM $637, M2K
   $526, MNKD $599 (≠ $500 stub).

5. **Priority risk-high-first** — khi nhiều entry tranh budget cùng ngày, ưu tiên cái risk$
   cao (biến động cao, trend-tail béo, MNQ-like). +0.15 Calmar robust 2 slippage, MaxDD phẳng.
   Tiên-nghiệm (sort theo risk$, không nhìn P&L) → tổng quát hóa, không overfit.

6. **Sizer DD-bound → 1 micro.** Combined MaxDD ~$2,911 / target 10% ($5k) → dd_scale 1.72 →
   floor 1 micro. Không lên 2 micro được (sẽ vượt hard cap 15%).

---

## 5. Đã loại trừ / đóng

- **DAX/Stoxx (Eurex):** Databento XEUR chỉ có data từ 2025-03-10 (~15 tháng) → không đủ
  WFO/vault. Cần nguồn data khác (dự án data riêng). Loại khỏi vòng này.
- **NIY (Nikkei JPY):** trùng index với NKD + thêm FX risk → vô nghĩa.
- **GLBX gần cạn index nước ngoài USD-denominated khác** → NKD nhiều khả năng là index nước
  ngoài duy nhất đáng thêm qua hạ tầng hiện tại.

---

## 6. Giới hạn & caveat (giữ kỷ luật)

- **In-sample-broad:** cap/priority/param tuned trên 2018-2024 đã nhìn nhiều lần → Calmar
  2.38 là trần lạc quan, không phải dự báo live.
- **Vault 2023-2024 contaminated** (nhìn nhiều lần khi chọn gated/agnostic) → không còn OOS
  sạch. **Vault 2025 vẫn nguyên** — final validation thật, chạy MỘT lần sau paper.
- **0 ngày dữ liệu thật:** slippage MNKD live có thể >2t (micro mỏng), fill partial, gap
  qua đêm, sự kiện chưa thấy (sideways dài, Nhật-Mỹ phân kỳ) — không có trong backtest.
- **2018-2024 là giai đoạn trend-thuận;** chưa test thị trường thực sự khó.
- **Cap NKD 2% + risk-per-pos là ESTIMATE** — calibrate bằng paper.
- **Hold-time median = 1 ngày:** swing TF thực chất gần day-trade với đuôi 5-ngày hiếm
  (edge có thể đến từ vài trade giữ-lâu) — câu về chiến lược, chưa khảo sát sâu.

---

## 7. Còn cần làm

### Làm được trước IBKR (offline, không viết mù)
- [ ] **Decision module:** gom signal (EMA/ATR/regime → entry/exit) + risk (cap 5% +
      priority risk-high-first + sizer + circuit breaker) thành `decide(bars, positions,
      equity) → orders`. Test bằng replay (phải khớp `deploy_sim`). Đây là ~80% bộ não
      runner, không phụ thuộc broker.
- [ ] Khảo sát hold-time distribution + P&L theo hold-days (câu chiến lược, optional).

### Chặn bởi IBKR account
- [ ] Wire **runner** dựa trên API IBKR thật (đừng stub đoán): `fetch_live_bars`,
      `send_order` qua `ib_async` + IB Gateway (port 7497).
- [ ] Quyết **data feed live** (Polygon / IBKR / Databento live) cho cả Rổ 4 (giờ ET) lẫn
      NKD (giờ JST/GLBX).
- [ ] **Paper trade** qua runner — OOS sạch duy nhất còn lại. Fix **chỉ** Type-1 bug
      (connection, fill, sizing, slippage); KHÔNG đụng Type-2 (strategy param — đã khóa).
- [ ] **Calibrate** cap NKD 2% + slippage MNKD thật từ paper.
- [ ] **Vault 2025** (một lần, sau paper) — final validation OOS sạch.
- [ ] **Live 1 micro** sau khi paper + vault 2025 xác nhận.

### Vận hành / khác
- [ ] Lưu ý timezone: NKD power-hour = trưa VN (canh được); Rổ-4 power-hour = 2h sáng VN
      (runner phải tự chạy lúc ngủ — test reconnect/halt cẩn thận).
- [ ] Buffer ~$44k idle → T-bill/money market (IBKR trả lãi cash hoặc SGOV/BIL) — xác nhận
      chính sách lãi/collateral IBKR cho Vietnam resident.
- [ ] Vietnam relocation: IBKR entity/PDT/tax cross-border.

---

## 8. File inventory (`global_index/`)

**Production / pipeline:**
`__init__.py` · `_core.py` · `fetch.py` · `specs.py` · `regime.py` ·
`swing_tf_powerhour.py` · `wfo.py` · `vault.py` · `combined.py` ·
`net_exposure_multi.py` · `combined_system.py` · `deploy_sim.py`

**Diagnostics (read-only, không sửa engine):**
`risk_diagnostic.py` · `reject_value_diagnostic.py` · `hold_vs_entry_diagnostic.py` ·
`cap_sweep.py` · `priority_sweep.py`

**Self-contained:** `_core.py`/`fetch.py` là bản copy generic; các harness tái dùng *chính*
`futures._validated_core.backtest_swing_tf` (qua tz-convert) để test đúng "như Rổ 4".

---

## 9. Lệnh chạy nhanh (từ `D:\raits`)

```powershell
# Edge transfer (regime-agnostic, cost stress)
python -m global_index.swing_tf_powerhour --parquet global_index/data/NKD_continuous_1m_8y.parquet --raw global_index/data/NKD_continuous_1m_8y_raw.parquet --instrument MNKD --tz Asia/Tokyo --cost-mult 2.0

# WFO (chọn param @ 2× cost)
python -m global_index.wfo --parquet global_index/data/NKD_continuous_1m_8y.parquet --instrument MNKD --tz Asia/Tokyo --regime-mode gated --regime-csv spy_daily.csv --select-cost-mult 2.0

# Deploy-realistic (cấu hình chốt: cap 5% + priority risk-high-first đã là mặc định)
python -m global_index.deploy_sim --data-dir data\cache\futures --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet --regime-csv spy_daily.csv --include-stress --slippage-ticks 2
```
