# Stocks — DECISIONS
_Quyết định đã chốt + lý do + alternatives bị reject._
_Cập nhật: 2026-07-07_

---

## HMM

**HMM basis = split-only (5-min derived) — CLOSED 2026-07-07**  
Why: HMM features are log returns; div-adj differs only on ~28 SPY ex-div days/yr;
ex-div drop ~0.4% too small to shift realized vol into Stress range; strategies execute
on split-only prices — regime gate must see same series. 8.17% label diff vs div-adj is
~3.3% HMM noise + ~4.9% Viterbi path sensitivity; Calm↔Stress direct flips = 0.  
Rejected: div-adjusted — wrong standard for intraday; smooths actual price moves strategies face.  
Caveat: STRESS_ORB shows basis-sensitive verdict (rim-of-system, low N, monitor not act).  
See: [docs/stocks/HMM_BASIS_DECISION.md](HMM_BASIS_DECISION.md)

**HMM seed pinned at RANDOM_SEED=42 — baseline is reproducible**  
Why: `HMMEngine._fit_best` re-creates `RandomState(42)` on every call; both engine.py and
engine_refactored.py call `HMMEngine()` with no args → seed 42 always. Baseline produces
identical labels given same input data. Sensitivity: ~3.28% label change if seed were altered.  
DO NOT change RANDOM_SEED before or during baseline regeneration.

**Weekly-expanding retrain (vs frozen như futures / annual)**  
Why: matches stocks trading nature — individual stock alpha thay đổi nhanh hơn macro; stability measured (churn 1.1%, zero calm-stress inversion).  
Rejected: frozen — stocks HMM degraded faster; annual — 2025 retraining cost quá cao.

**Expanding-from-2017 (vs rolling-252 days)**  
Why: mỗi crisis (2018, 2020, 2022) trở thành training data — mô hình học Stress regime từ real crisis.  
Rejected: rolling-252 — crisis data cuối cùng bị drop khỏi window.

**Giữ weekly cadence (vs đổi sang annual sau artifact check)**  
Why: pre-committed criteria MET (annual +11.4pp recall 2022, false-alarm lower) nhưng 2025 cost quá cao. Decision: weekly stays, annual is table for next retrain review.  
Rejected: switch to annual now — cost + disruption không justify mid-cycle.

**Edge = cross-sectional (vs index-level / ETF pivot)**  
Why: QQQ PF collapsed trong 6-yr backtest. RAITS edge = individual stock idiosyncratic alpha.  
Rejected: index pivot — tested, definitively NO-GO.

---

## Strategy removal

**FADE + GAP_FILL + VWAP_MR removed from engine**  
Why: bootstrap p-values no edge confirmed (10,000 iterations).  
Rejected: giữ — zero edge = dilutes Sharpe, adds noise.

**STRESS_MID kept (p=0.112 borderline)**  
Why: positive across Stress years, n đủ để judge directionally.  
Rejected: remove — borderline positive is signal in Stress environment.

**GF_SHORT kept (p=0.128, n=33)**  
Why: n too small to decide; cost of false removal > cost of keeping low-trade strategy.  
Rejected: remove — premature, n too small.

**VWAP_MR: removal may need re-evaluation**  
Why: was trading stocks (wrong instrument) — should trade ETFs. Need ETF universe test.  
Status: OPEN — run `vwap_mr_etf_sim.py` after ETF data ready.

---

## Sizing / Risk

**max_position_pct = 0.40 (vs 0.30)**  
Why: Kelly-based. ORB/STRESS_MID/PE_SHORT benefit (were PosLimit-bound). TF already Kelly-bound at 21%.  
Rejected: 0.30 — unnecessarily conservative given Kelly ceiling.

**max_risk_pct = 1.5% (vs 1.0%)**  
Why: VolTarget constraint — 1% too tight for equity universe.

**kelly_fraction = 0.75 (3/4 Kelly)**  
Why: P&L +37% vs 0.5 Kelly; half-Kelly too conservative for measured edge.

**MAX_TREND = 3 (vs 2)**  
Why: +$3,158 (+11%), ann 9.4% → 10.5%. Backtest confirms 3 positions not over-concentrated.

---

## Architecture

**OOS là one-shot — không iterate sau khi nhìn kết quả**  
Why: iterating on OOS = look-ahead bias = vault kết quả vô nghĩa.  
Rejected: "one more adjustment" — this is the exact failure mode vault protects against.

**Không run WFO cho đến khi fetch + rebuild hoàn chỉnh**  
Why: WFO với incomplete data (META missing 2017-2020, sector ETFs pending) = stale params.

**`day_stocks` incremental trong live mode (bars up to bar_ts only)**  
Why: correct live semantics — không look-ahead vào full-day data.  
Rejected: pre-load full day — look-ahead bias (Gap 1 root cause).

**MockBroker realizes P&L từ backtest ledger (không bars)**  
Why: apples-to-apples vs deploy_sim; bar-based P&L có timing differences.