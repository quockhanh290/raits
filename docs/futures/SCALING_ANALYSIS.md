# Futures — Scaling Strategy Analysis
_Đo thực tế, không lập luận. 2026-07-08_

---

## Dữ liệu đo được

```powershell
# Lệnh đo:
python global_index/deploy_sim.py --data-dir data\cache\futures \
    --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet \
    --regime-csv spy_daily.csv --include-stress \
    --account <ACCOUNT> --n-contracts <N>
```

| Config | Net P&L | Calmar | MaxDD | swing taken | swing rejected | stress taken | stress rejected | NKD taken |
|---|---|---|---|---|---|---|---|---|
| n=1 @ $50,000 | $52,936 | 2.75 | $2,657 | 1799 | 704 | 312 | 117 | 665 |
| n=2 @ $50,000 | $47,927 | 1.78 | $3,886 | 1092 | **1411** | 80 | **349** | 665 |
| n=1 @ $55,784 | $55,441 | 2.76 | $2,908 | 1941 | 562 | 343 | 86 | 676 |
| n=2 @ $55,784 | $60,128 | **2.28** | $3,810 | 1184 | **1319** | 116 | **313** | 676 |

NKD: không đổi giữa n=1 và n=2 tại mọi account ✓ (`contracts_by[NKD]=1` hardcoded trong deploy_sim).

---

## 1. Mâu thuẫn ba ngưỡng — CONFIRMED

### Nguồn gốc $55,784

`_archive/answered/scaling_dd_trust.py` tính threshold từ MaxDD n=1 tại $50k = $2,657:
- DD threshold = 20 × $2,657 = $53,140
- Margin threshold = 5 × base_margin = **$55,784** ← binding
- Claim: sizer chọn n=2 tại $55,784 ✓ (dùng MaxDD tại $50k)

### Tại sao sai khi account = $55,784

MaxDD thay đổi với account (budget nới → nhiều trade admitted → DD cao hơn):
```
dd_scale tại $55,784 = 55,784 × 0.10 / 2,908 = 1.918 < 2.0 → sizer vẫn chọn n=1
```

Threshold $55,784 chỉ đúng với MaxDD đo tại $50k. Khi account thực sự = $55,784:
MaxDD đã tăng lên $2,908 → dd_scale không đạt 2.0 → sizer không auto-upgrade.

### Vòng lặp tự tham chiếu

Threshold đúng = `account ≥ 20 × MaxDD_1micro(account)` — phương trình phụ thuộc lẫn nhau:

| Account | MaxDD_1micro (đo) | 20 × MaxDD | dd_scale tại account |
|---|---|---|---|
| $50,000 | $2,657 | $53,140 | 1.88 |
| $55,784 | $2,908 | $58,160 | 1.92 |
| ~$58,160 | ~$2,950 (ước tính) | ~$59,000 | ~1.97 |

Hội tụ ≈ **$58–59k** (cần chạy deploy_sim --account 59000 để xác nhận chính xác).

### Tại ngưỡng ~$58-59k: Calmar n=2 ≈ 2.28 < floor 2.38 → gate fail

**Không tồn tại account level nào cả ba điều kiện đồng ý scale n=2:**
1. Sizer auto-select n=2 (dd_scale ≥ 2) → cần ~$58-59k
2. Calmar n=2 ≥ floor 2.38 → không đạt (IS = 2.28)
3. $55,784 threshold → sizer vẫn n=1

---

## 2. Root cause structural

### Tỷ lệ fixed

```
risk_sized per trade = n × mult × ATR × PV   ← tỷ lệ với n, KHÔNG với account
cluster cap          = pct × account          ← tỷ lệ với account, KHÔNG với n
```

Số trades concurrent trước khi cap đầy:
```
capacity = cap / risk_sized = (pct × account) / (n × mult × ATR × PV)
```

Tăng n từ 1→2: mẫu số × 2, tử số không đổi → **capacity giảm đúng 50% tại mọi account**.

Account nới 11.5% ($50k→$55,784): capacity chỉ tăng 11.5% — không bù được mức giảm 50%.

### MaxDD không scale tuyến tính với n

n=2 MaxDD = $3,810 = **1.31× n=1 MaxDD** (không phải 2×).

Nguyên nhân: cap rejections giảm số positions concurrent → portfolio-level DD giảm so với dự đoán.
Nhưng P&L chỉ tăng **1.08×** ($60,128 / $55,441). DD tăng nhanh hơn P&L → Calmar giảm.

### Kết luận

**n=2 luôn reject nặng hơn n=1 tại mọi account level** (structural, không phải calibration issue).
Cap rejections cap P&L upside. DD tăng (dù ít hơn 2×). Calmar luôn giảm khi scale n.

---

## 3. Scaling strategy alternatives

### a. Cap scale cùng n: `cap = pct × account × n`

Ví dụ: swing cap tăng từ 5% → 10% khi n=2.

Tác động: số concurrent positions giữ nguyên → cap rejections biến mất → P&L tăng ~2×.
MaxDD khi đó tăng gần tuyến tính (~2×). Calmar ≈ giữ nguyên.

**Điều kiện**: đây là thay đổi risk parameter (cluster gross exposure tăng 2×), không phải scaling đơn giản.
Cần vault riêng tại n=2 với cap mới. Không miễn phí về validation.

### b. Scale bằng thêm instrument

Thêm instrument mới (micro-index variant, international futures...) tại n=1. Diversification thay vì concentration.

Calmar stable, không reject, không thay đổi risk parameter.
**Cần validation từ đầu cho mỗi instrument mới.**

### c. n=1 ceiling — path hiện tại đúng

Tại n=1, account tăng → absolute P&L tăng tỷ lệ (14.4%/yr × account), MaxDD tăng tỷ lệ → **Calmar stable**.

n=1 @ $55,784: Calmar 2.76 > floor 2.38 ✓. Không có gì sai với ceiling này.

**Đây là path đúng cho đến khi có vault n=2 OOS validated.**

### d. Floor 2.38 không áp cho n=2

Floor 2.38 từ fit_A **n=1 IS**. n=2 có risk profile khác (cap regime khác, MaxDD ratio khác).
Áp floor n=1 cho n=2 là dùng baseline sai.

Nếu triển khai n=2: cần vault OOS riêng tại n=2 → IS Calmar n=2 = 2.28 làm baseline → floor từ fit_A n=2 (chưa đo).

---

## 4. Threshold recompute đúng

### $55,784 bug

`scaling_dd_trust.py` (archived) có **NKD scaling bug**: NKD scale theo n trong `build_all_trades(n)`:
```python
r  = real_risk(natr, NKD_MULT, ..., n)   # NKD risk × n — SAI
pnl_sized = t["pnl"] * n               # NKD pnl × n — SAI
```
deploy_sim đã fix (NKD hardcoded n=1). $55,784 threshold tính với NKD inflate → lệch nhẹ.

### Sider auto-select logic (đúng về hướng, sai về fixed MaxDD)

```python
dd_scale = account × 0.10 / maxdd_1micro
n = int(dd_scale)   # ≥ 2 → auto-select n=2
```

MaxDD_1micro là input đo tại account hiện tại, không phải fixed. Threshold thực tế hội tụ ~$58-59k (xem bảng mục 1).

### 20 × n=2 MaxDD = ngưỡng n=3, không phải n=2

`20 × $3,810 = $76,200` — đây là account threshold để sizer auto-select n=3 (nếu n=2 là baseline).
Không dùng để gate n=1→n=2.

### Threshold n=2 đúng cần đo iteratively

```powershell
# Chạy để tìm hội tụ:
python global_index/deploy_sim.py ... --account 59000 --n-contracts 1
# Lấy MaxDD_1micro → tính 20 × MaxDD
# Lặp đến convergence
```

---

## 5. Tổng kết — Status document corrections

| Claim cũ | Reality đo | Action |
|---|---|---|
| Scale n=2 tại $55,784 | Sizer dd_scale=1.92 < 2 → auto n=1 | **Threshold sai** — xóa hoặc sửa thành ~$58-59k |
| 2-micro MaxDD $5,890 | Đo được $3,810 (@ $55,784) | **Số sai** — update |
| $82k manual buffer | Không có formula basis | OK — đã note "unverified" |
| Floor 2.38 áp n=2 | Baseline khác — không applicable | Note: n=2 cần vault riêng |
| n=2 đáng vì P&L > n=1 | Đúng tuyệt đối (+8.5%), sai risk-adjusted (Calmar 2.28 < floor 2.38) | Note: cần vault n=2 OOS |

### Quyết định scaling

**Hiện tại: n=1 ceiling.** Không có path consistent để scale n=2 mà không:
1. Thay đổi cap parameter (cap×n) → cần vault mới, hoặc
2. Chấp nhận Calmar 2.28 < floor 2.38 → chưa đủ evidence

Scale n=2 chỉ xem xét khi:
- Có vault OOS n=2 validated (establish n=2 IS baseline + floor), VÀ
- Chọn strategy: cap×n hoặc thêm instrument, HOẶC
- Chấp nhận Calmar 2.28 như baseline n=2 và set floor mới cho n=2 riêng
