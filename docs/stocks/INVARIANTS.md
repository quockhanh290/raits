# Stocks — INVARIANTS
_Bất biến phải luôn đúng + cách kiểm tra._
_Cập nhật: 2026-07-06_

---

| Invariant | Cách check | Tại sao |
|---|---|---|
| HMMEngine class không sửa interface | `git log --oneline raits/hmm/engine.py` | SHARED với futures — xem `docs/SHARED.md` |
| Churn < 2%/quarter | Chạy `raits/raits/scripts/hmm_stability_measure.py` | Weekly retrain stable; >2% → investigate |
| Zero calm↔stress inversion | Same stability script, inversions output | Regime không brittle; inversion = wrong direction |
| Weekly retrain wired (3 paths trong context_feed) | `grep -n "retrain\|hmm" raits/live/context_feed.py` | Live retrain active |
| RefactoredBacktestEngine == BacktestEngine | `python raits/raits/scripts/verify_parallel_run.py` → 604==604, diff $0.00 | Refactor gate |
| `day_stocks` incremental trong live mode | `grep -n "iloc\|full_day\|day_stocks" raits/live/context_feed.py` | No look-ahead bias (Gap 1 lesson) |
| `configs/final_params.yaml` không sửa | `git log --oneline raits/raits/configs/final_params.yaml` | Vault params sealed |
| VWAP_MR = 0 trades trong IS | Kiểm snapshot trades VWAP_MR count | Zombie fixed; removal confirmed |
| Live tests PASS (raits/tests/live/) | `pytest raits/tests/live/` → 117/117 PASS | Live harness intact |

---

## Invariant bị phá → làm gì

1. **STOP** — không commit
2. Revert thay đổi ngay
3. Trace root cause — đặc biệt nếu liên quan HMMEngine class (check futures cũng bị ảnh hưởng không)
4. Ghi vào `stocks/OPEN_QUESTIONS.md`
5. Nếu HMMEngine class bị sửa → chạy cả futures reconcile chain trước khi commit