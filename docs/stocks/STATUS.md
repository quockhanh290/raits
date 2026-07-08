# Stocks — STATUS
_Cập nhật: 2026-07-06. Equity RAITS (`raits/`) — hệ riêng biệt với futures._

---

## Trạng thái tổng

**Live-ready. Edge hẹp. Chờ Vault 2025 (true GO/NO-GO).**

Không phải NO-GO — là independent system chờ OOS confirm.

---

## Đã hoàn thành

### HMM weekly retrain — wired live
- Weekly-expanding retrain WIRED vào live context_feed (3 paths)
- Stability measured: churn 1.1% (claimed 1.8%, overstated), inversions=0 confirmed
- Annual vs weekly detection: COVID tied (100%/100%); 2022 bear: annual +11.4pp recall, weekly stays (2025 cost)
- HMM agreement actual: **68%** (NOT 98.5% — claim wrong, measured `hmm_stability_measure.py`)
- → Quyết định giữ weekly MẠNH HƠN sau measurement (68% = retrain necessary)

### Stale fix
- `daily_data["SPY"]` fail-loud DONE — không âm thầm dùng stale data

### Paper-trading harness (stocks)
- MockBroker + ReconciliationLog + PaperTrader DONE (Phase 1-3)
- ReplayContextFeed: 116926/116926 bars identical — verified
- LivePolygonFeed: incremental bars, correct live semantics
- 604/604 trades identical end-to-end; net P&L $15,926.85 verified

### Refactor gate — PASSED
- RefactoredBacktestEngine byte-identical to BacktestEngine: 604==604 trades, P&L diff $0.00

### Current IS baseline (locked)
- Snapshot: `results_20260624_200216.pkl`
- Settings: IS 2017–2022 | $50k | 1.5% risk | 0.75 Kelly | MAX_TREND=3 | 5% PE gap | max_pos=0.40
- **Total: +$34,214 | Calmar ~1.55**
- Strategy: ORB=$5,910 | TF=$16,191 | PE_SHORT=$6,888 | STRESS_MID=$3,290 | STRESS_ORB=$1,734 | GF_SHORT=$203

### Removed strategies (bootstrap confirmed no edge)
- FADE, GAP_FILL, VWAP_MR — removed from `_REGIME_STRATEGIES`
- VWAP_MR zombie fixed (bypass `_REGIME_STRATEGIES` via vol gate)

### Vault test (2023–2024 OOS) — DONE (prior baseline)
- +$7,404 (+14.8%), Sharpe=0.88, PF=1.18
- Locked params: orb=20 / bb=1.5 / ema=30 → `configs/final_params.yaml` (SEALED)

---

## Edge

Cross-sectional alpha (individual stock idiosyncratic) — NOT index-level.  
Index pivot NO-GO: QQQ PF collapsed 6-yr. Edge = stock selection, not direction of index.

---

## Chờ xử lý

| Item | Priority | Note |
|---|---|---|
| Fetch FB (META pre-rename) + sector ETFs | HIGH | Prereq cho baseline hoàn chỉnh |
| Run VWAP_MR ETF sim sau khi ETF data ready | MEDIUM | Re-evaluate removal với ETF universe |
| Run WFO (wfo_real_run.py) | HIGH | Params 15/2.0/30 stale — engine changed |
| Update configs/final_params.yaml | HIGH | Sau WFO |
| Final snapshot post-WFO | HIGH | Pre-OOS baseline |
| OOS Vault 2025 | HIGH | One-shot — KHÔNG iterate sau khi nhìn kết quả |
| Auto-refresh daily SPY live source | MEDIUM | Polygon? IBKR? Cần quyết định trước live |

---

## Không làm

- Không đụng futures khi làm stocks
- Không modify `configs/final_params.yaml` (sealed)
- Không run OOS cho đến khi WFO hoàn chỉnh và engine locked