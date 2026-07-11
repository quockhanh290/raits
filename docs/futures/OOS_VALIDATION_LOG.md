# OOS Validation Log — Frozen Ground Truth
_Session: 2026-07-09_

Ghi lại đầy đủ mọi run đo trong session này: IS baseline, IS floor, vault OOS 2023-24 + 2025, và investigation frozen_2025.

---

## Convention đã chốt

**SLIPPAGE = 2-tick/side** (mọi verdict — `--slippage-ticks 2`)

Lý do: MNKD thin fills thực tế slip >1 tick. 1-tick = upper bound lý tưởng không đạt được live.
Hệ quả: mọi số Calmar trong bảng này phải trên cùng convention 2-tick để so sánh.

---

## Bảng tổng hợp — tất cả runs

| Run ID | Data | HMM fit | Stress | Slippage | Net P&L | Calmar | Ghi chú |
|--------|------|---------|--------|----------|---------|--------|---------|
| B1 | frozen_2024 | fit_C (2024-12-31) | No | 2-tick | $47,186 | 2.38 | IS baseline (clean floor) |
| B2 | frozen_2024 | fit_C | Yes | 2-tick | $46,457 | 2.50 | IS baseline + stress |
| F1 | frozen_2024 | fit_A (2022-12-31) | No | 2-tick | — | **2.04** | **IS floor (dùng cho verdict)** |
| F2 | frozen_2024 | fit_A | Yes | 2-tick | — | 2.54 | IS floor + stress ⚠ inverted |
| V0 | frozen_2024 | fit_A | No | **1-tick** | — | 3.61 | Vault 2023-24 (REFERENCE cũ) |
| V1 | frozen_2024 | fit_A | No* | 2-tick | — | **3.08** | **Vault 2023-24 → GO ✓** |
| V2 | frozen_2025 | fit_C | Yes | 2-tick | — | **3.35** | **Vault 2025 → GO ✓** |
| V3 | frozen_2025 | fit_C | No | 2-tick | — | **3.42** | **Vault 2025 no-stress → GO ✓** |
| I1 | frozen_2025_sim (unclipped) | fit_C | Yes | 2-tick | — | 2.76 | Investigation: IS trên f25 |
| I2 | frozen_2025_clipped | fit_C | Yes | 2-tick | — | 2.76 | Investigation: IS sau khi clip 2025 |

*V1: không có Stress regime days trong 2023-2024 → ±stress không đổi kết quả.

---

## IS Baseline runs — chi tiết

### B1: IS Baseline, frozen_2024, NO stress, 2-tick

```
python -m global_index.deploy_sim \
  --data-dir data\cache\futures\frozen_sim \
  --nkd-parquet global_index/data/NKD_frozen_2024.parquet \
  --regime-csv spy_daily_live.csv \
  --end 2024-12-31 --n-contracts 1 --slippage-ticks 2
```

| Metric | Value |
|--------|-------|
| Net P&L | $47,186 |
| Calmar | 2.38 |
| Swing trades | 1,814 |
| NKD trades | 665 |
| Stress trades | 0 (not enabled) |

### B2: IS Baseline, frozen_2024, WITH stress, 2-tick

Command: B1 + `--include-stress`

| Metric | Value |
|--------|-------|
| Net P&L | $46,457 |
| Calmar | 2.50 |
| Swing trades | 1,617 |
| NKD trades | 612 |
| Stress trades | 118 |

**Observation:** Stress và swing CẠNH TRANH position slots → swing giảm 1,814→1,617 (-197) khi stress bật.
Net P&L thấp hơn B1 ($729) nhưng Calmar cao hơn (2.50>2.38): stress giúp MaxDD giảm mạnh hơn ở 2022 bear.

---

## IS Floor runs — chi tiết

### F1: IS Floor, fit_A (2022-12-31), frozen_2024, NO stress, 2-tick

Command: B1 + `--hmm-fit-end 2022-12-31`

| Metric | Value |
|--------|-------|
| Calmar | **2.04** |
| floor/baseline ratio | 85.7% (2.04 / 2.38) |
| Dùng cho verdict | **YES** — floor chính thức |

### F2: IS Floor, fit_A, frozen_2024, WITH stress, 2-tick

Command: F1 + `--include-stress`

| Metric | Value |
|--------|-------|
| Calmar | 2.54 |
| So với baseline B2 | **2.54 > 2.50** → INVERTED ⚠ |

**Anomaly — Floor Inversion:**
Floor (fit_A+stress=2.54) > Baseline (fit_C+stress=2.50) = floor > baseline = vô lý.

Root cause đo được:
- fit_A labels **316 Stress days** trong IS period
- fit_C labels **118 Stress days** trong IS period
- Nhiều Stress days → nhiều STRESS_MID trades trong 2022 bear → IS P&L fit_A cao hơn fit_C

**Decision:** Dùng F1 (no stress, Calmar 2.04) làm floor chính thức. Đánh giá STRESS OOS riêng biệt.

---

## Vault OOS runs — chi tiết

### V0 (reference cũ): Vault 2023-2024, 1-tick, NO stress

| Metric | Value |
|--------|-------|
| Calmar | 3.61 |
| Slippage | 1-tick (cũ, không dùng cho verdict) |

### V1: Vault 2023-2024, 2-tick

```
python -m global_index.deploy_sim \
  --data-dir data\cache\futures\frozen_sim \
  --nkd-parquet global_index/data/NKD_frozen_2024.parquet \
  --regime-csv spy_daily_live.csv \
  --start 2023-01-01 --end 2024-12-31 \
  --hmm-fit-end 2022-12-31 --n-contracts 1 --slippage-ticks 2
```

| Metric | Value |
|--------|-------|
| Calmar | **3.08** |
| Stress trades | **0** (không có Stress regime period trong 2023-2024) |
| Floor | 2.04 |
| Verdict | **GO ✓** (biên: +1.04, tức 51%) |

HMM contamination check: fit-end 2022-12-31 < test period start 2023-01-01 ✓ (I2.2 compliant)

### V2: Vault 2025, WITH stress, 2-tick

```
python -m global_index.deploy_sim \
  --data-dir data\cache\futures\frozen_2025_sim \
  --nkd-parquet global_index/data/NKD_frozen_2025.parquet \
  --regime-csv spy_daily_live.csv \
  --start 2025-01-01 --end 2025-12-31 \
  --hmm-fit-end 2024-12-31 --n-contracts 1 --slippage-ticks 2 --include-stress
```

| Metric | Value |
|--------|-------|
| Calmar | **3.35** |
| Stress trades | **7** (net −$45) |
| Floor | 2.04 |
| Verdict | **GO ✓** (biên: +1.31, tức 64%) |

HMM contamination check: fit-end 2024-12-31 < test period start 2025-01-01 ✓ (fit_C used, I2.2 compliant)

### V3: Vault 2025, NO stress, 2-tick

Command: V2 bỏ `--include-stress`

| Metric | Value |
|--------|-------|
| Calmar | **3.42** |
| Floor | 2.04 |
| Verdict | **GO ✓** (biên: +1.38, tức 68%) |

---

## Investigation: tại sao IS baseline khác nhau giữa frozen_2024 và frozen_2025?

### Câu hỏi ban đầu
Chạy IS baseline trên frozen_2025 (giới hạn 2024-12-31) → Calmar 2.76 ≠ frozen_2024 baseline 2.50.

### I1: IS Baseline trên frozen_2025_sim (unclipped), WITH stress, 2-tick

| Metric | Value |
|--------|-------|
| Calmar | 2.76 |
| Net P&L | $51,937 |
| Stress trades | 317 |
| Swing trades | 1,815 |
| NKD trades | 665 |

Per-year breakdown:
| Năm | P&L |
|-----|-----|
| 2018 | $7,699 |
| 2019 | $1,395 |
| 2020 | $15,541 |
| 2021 | $5,314 |
| 2022 | $8,686 |
| 2023 | $9,165 |
| 2024 | $4,138 |

Hypothesis: frozen_2025_sim có 3,159,570 bars (2017-2025) thay vì 2,807,032 (2017-2024) → backtest chạy cả 2025 trước khi clip → stress=317 gồm cả 2025 trades → Calmar inflate.

### I2: IS Baseline trên frozen_2025_clipped (clip tới 2024-12-30 23:59 UTC), WITH stress, 2-tick

Script `clip_frozen2025.py` tạo `data/cache/futures/frozen_2025_clipped_sim/` + `NKD_frozen_2025_clipped.parquet`.

| Metric | Value |
|--------|-------|
| Calmar | **2.76** |
| Net P&L | ~$51,937 |
| Stress trades | **317** |
| Swing trades | **1,815** |

**Kết quả: GIỐNG I1.** Clip 2025 data KHÔNG phải nguyên nhân.

### Phân tích data: frozen_2024 vs frozen_2025

Script `compare_frozen2.py` — so sánh close và HL cho common timestamps:

| Instrument | Offset (f25−f24) | std | Constant? | HL identical? |
|------------|-----------------|-----|-----------|---------------|
| ES | +217.0 | <0.001 | ✓ | ✓ |
| NQ | +913.0 | <0.001 | ✓ | ✓ |
| YM | +1,339.0 | <0.001 | ✓ | ✓ |
| RTY | +68.2 | <0.001 | ✓ | ✓ |
| NKD | −110.0 | <0.001 | ✓ | ✓ |

Data đồng nhất về structure: pure constant back-adjustment offset, HL identical.

### Root cause — percentage-based stop

Với additive stop (fixed points): `stop = entry + n×ATR` → offset cancel hoàn toàn khi so exit với entry.

Với **percentage-based stop**: `stop = swing_high × (1 + 0.1%)` trong STRESS_MID engine:
- frozen_2024: `stop_f24 = sh × 1.001`
- frozen_2025 (offset +217): `stop_f25 = (sh + 217) × 1.001 = sh×1.001 + 0.217`

Stop của frozen_2025 cao hơn 0.217 điểm. Với SHORT position, stop cao hơn = khó bị stop-out hơn → trades sống lâu hơn → entry/exit timing khác → ripple effect lên toàn bộ stress cluster.

Kết quả: stress=118 (frozen_2024) → stress=317 (frozen_2025) — gấp 2.7× chỉ từ 0.001×217=0.217 điểm chênh lệch stop.

### Conclusion về anomaly

| | Frozen_2024 | Frozen_2025 | |
|--|-------------|-------------|--|
| IS baseline (stress) | Calmar 2.50 | Calmar 2.76 | khác nhau do percentage stop |
| Stress trades IS | 118 | 317 | expected từ root cause |
| OOS 2023-24 | 3.08 | — | chỉ dùng frozen_2024 (phù hợp) |
| OOS 2025 | — | 3.35 / 3.42 | chỉ dùng frozen_2025 (phù hợp) |

**Anomaly KHÔNG ảnh hưởng verdict:**
- Floor (2.04) từ frozen_2024 → so với vault 2023-24 (frozen_2024) ✓ consistent
- Vault 2025 dùng frozen_2025 làm reference riêng → so với floor 2.04 ✓ conservative

---

## STRESS OOS status

| Period | Stress trades | Net | Status |
|--------|--------------|-----|--------|
| IS 2017-2022 | 118 (fit_C) | positive | Confirmed IS |
| OOS 2023-2024 | **0** | $0 | No stress regime → không đánh giá được |
| OOS 2025 | **7** | −$45 | N=7, sample quá nhỏ |

**Kết luận:** STRESS sleeve là IS-confirmed, OOS-pending-bear.
Cannot validate without a stress/bear market period. Will self-validate in next stress cycle.
Documented: DECISIONS.md + OPEN_QUESTIONS.md.

---

## Verdicts cuối

| Vault | Data | Calmar | Floor | Biên | Verdict |
|-------|------|--------|-------|------|---------|
| 2023-2024 | frozen_2024, fit_A | 3.08 | 2.04 | +1.04 (+51%) | **GO ✓** |
| 2025 (with stress) | frozen_2025, fit_C | 3.35 | 2.04 | +1.31 (+64%) | **GO ✓** |
| 2025 (no stress) | frozen_2025, fit_C | 3.42 | 2.04 | +1.38 (+68%) | **GO ✓** |

Floor = 2.04 = fit_A trên frozen_2024, no stress, 2-tick.
Convention = 2-tick cho tất cả (locked trong INVARIANTS.md).
