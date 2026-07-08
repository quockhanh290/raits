# Stocks — OPEN QUESTIONS
_Câu hỏi chưa giải quyết + blocker + priority._
_Cập nhật: 2026-07-06_

---

## HIGH priority

**VWAP_MR: thực sự không có edge hay chỉ vì wrong universe?**  
Priority: HIGH  
Status: Chờ ETF data (sector ETFs XLF/XLE/...)  
Note: VWAP_MR was tested on stocks (wrong) — should be ETF universe. Run `vwap_mr_etf_sim.py` after ETF fetch. Nếu p<0.05 và P&L positive → re-add permanently; else removal confirmed.

**SPY adjustment inconsistency: HMM train dùng split-only (5-min), scanner dùng dividend-adjusted (daily)**  
Priority: HIGH  
Status: Inconsistency FOUND — impact CHƯA ĐO  
Note: ~24 ex-div days mỗi năm potentially misclassified. Impact trên: (1) regime labels, (2) P&L.  
**Measure when:** tiếp theo khi làm stocks — trước Vault 2025.  
Xem: `docs/SHARED.md` — cùng chủ đề SPY adjustment nhưng nguồn STOCKS độc lập với futures.  
Action: viết script so sánh labels với split-only vs dividend-adjusted SPY.  
**Independence from futures CSV fix (2026-07-06):** cùng root cause (dividend gap) nhưng path riêng.  
Futures đã fix (spy_daily.csv → Polygon adjusted=True). Stocks path riêng: 5-min intraday bars  
vẫn dùng split-only → fix cần đổi fetch call riêng, test riêng — zero impact từ futures fix.

**WFO params stale — cần re-run**  
Priority: HIGH  
Status: Engine changed (zombie fix + refactor); params 15/2.0/30 từ old engine.  
Blocker: fetch FB (META) + sector ETFs → rebuild baseline → run WFO.

**HMM annual refreeze gate: MISSING**  
Priority: MEDIUM (HIGH before live)  
Status: OPEN — pre-live blocker  
Note: Futures system has full gate pipeline (AUTO_APPROVE <5% label change, VERIFY 5-15%, HOLD >15%), Calmar floor, 3-record rollback registry (`futures/refreeze.py`). Stocks `HMMEngine.retrain()` validates before promoting + falls back to last_good, but has no annual review cadence, no label-drift threshold, no rollback registry. Becomes load-bearing when stocks goes live — arbitrary model drift will go undetected.  
Action: Port refreeze gate concept from futures; adapt threshold to 4-state model (track label agreement rate annually).  
See: `docs/CROSS_SYSTEM_FINDINGS.md` § c.

**Live state persistence: IN-MEMORY ONLY**  
Priority: LOW (HIGH before live)  
Status: OPEN — not yet needed (paper-only)  
Note: `raits/live/runner.py` `PaperTrader` keeps `_running_equity` and `_session_start_equity` in memory only. No `peak_equity` tracking. No atomic JSON persist. `LiveContextFeed` raises `NotImplementedError`. On restart: equity resets to `account_equity` config, not recovered from broker. Futures system solves this with B1 atomic `live_positions.json` (`global_index/runner.py`). Stocks needs equivalent before live deployment.  
Action: Implement atomic state persist (equity + peak_equity + open positions) + broker-restart reconciliation before going live.  
See: `docs/CROSS_SYSTEM_FINDINGS.md` § d.

---

## MEDIUM priority

**FB (META pre-rename): cần fetch 2017-2020**  
Priority: MEDIUM  
Status: IN PROGRESS — fetch pending  
Note: META missing 2017-2020 (FB ticker issue). Ảnh hưởng baseline completeness.

**Auto-refresh daily SPY live source (Polygon? IBKR?)**  
Priority: MEDIUM  
Blocker: trước live  
Note: HMM weekly retrain cần SPY data fresh. Nguồn live chưa chốt.

**Annual vs weekly detection: annual is table for next review**  
Priority: LOW  
Status: pre-committed criteria MET (annual +11.4pp 2022 recall, false-alarm lower)  
Note: decision = weekly stays (2025 cost). Review khi cần annual re-freeze.  
See: `hmm_retrain_artifact_check.py` — artifact check committed, run để finalize.

---

## Vault (chờ WFO + data)

**Vault 2025 (true GO/NO-GO)**  
Priority: HIGH  
Status: PENDING — prereqs: WFO complete + engine locked  
Note: one-shot OOS. Không iterate. Không chỉnh params sau khi nhìn kết quả.  
Gate: run once → accept result → live or no-live.

---

## Đã đóng

**"3/6 convergence fail"** → WRONG — 6/6 converge (hmm_annual_convergence.py).  
**"98.5% HMM agreement"** → WRONG — actual 68% (hmm_stability_measure.py). Weekly retrain decision STRONGER.  
**Gap 1 root cause** → RESOLVED: `day_stocks.iloc[-1]` look-ahead in CB/SAFETY_MODE. Documented `KNOWN_DIFFERENCES.md`.