# Live vs Backtest Divergence Sweep
**Date:** 2026-07-03  
**Scope:** Futures system — roska4_swing / roska4_stress / global_nkd  
**Data:** Full 2018-2024 backtest (2,442 swing + 429 stress + 648 NKD trades)  
**Constraint:** Read-only audit. No code changes. `_validated_core.py` + `live_decision.py` untouched.

---

## Bước 1 — Divergence Surface

### A. Exit Mechanisms

| Mechanism | Description | Reconcile covers? |
|---|---|---|
| CHANDELIER | Trailing stop ratchet: extreme→prev_bar calc | YES — reconcile_gd0, reconcile_nkd (trade-for-trade) |
| GAP | Time-break + open past stop → fill at open (worse) | YES — same code path, 128 occurrences in history |
| MAX_HOLD | 5 calendar days → exit at open of day 5 | YES — reconcile_gd0 (492 occurrences) |
| STRESS_MID stop/target/eod | Same-day 10:15→14:00, entry vs adapter verified | YES — reconcile_stress (entry match), deploy_sim (exit) |
| same-day swing/NKD (hold=0) | Runner: `if t.get("exit") == day: send CLOSE` | **PARTIAL** — STRESS_MID exercises it; swing/NKD have 0 same-day in history |
| circuit_breaker HALT | `state.breaker.status().allow_new_entries == False` | **NO** — halts=0 in all historical runs (MaxDD < 15% by construction) |

### B. Entry Mechanisms

| Mechanism | Description | Reconcile covers? |
|---|---|---|
| Cap gross/net check | `guard.admits(pos, open_book)` per cluster | YES — decide_day == deploy_sim.replay in verify_runner_real |
| Priority ordering | `entry_priority_key` (risk-high-first, negated risk$) | YES — verify_runner_real exercises multi-entry days |
| Sizing (size_combined, n_contracts) | DD-cap + margin budget → n_contracts | YES — deploy_sim sizer, n=1 for $50k baseline |
| **Rejected → stale price retry** | desired_position returns entry_day=D price on D+1 | **BUG — see UT-2** |
| STRESS_MID only Stress + 10:15 | entry_signal() checks regime=="Stress"; bars_through_1015 | YES — reconcile_stress full coverage |

### C. Calendar / Time

| Mechanism | Covered? |
|---|---|
| Normal trading days | YES — 2018-2024 full range |
| Half-day / CME early close (~13:00 ET) | **NO** — 0 short-data days in parquet; engine never exercises early-close |
| NKD JST session (lag_days=1 via RegimeLabels.asof) | YES — strips JST tz, subtracts 1 calendar day, asof() handles US holidays |
| gap_fill=True alignment (swing + NKD) | YES — desired_position uses default=True; deploy_sim explicit True. **MATCH** |
| time-break detection (GAP_MIN=15min) | YES — 128 occurrences (rare but code exercised) |
| MAX_HOLD boundary (5 calendar days) | YES — 492 occurrences |
| daily_atr.asof(entry_day) / _asof_naive tz strip | YES — both paths strip tz before asof. MATCH |

### D. Context

| Mechanism | Covered? |
|---|---|
| HMM regime (fit_C frozen, expanding predict) | YES — both paths call label_regimes with hmm_fit_end="2024-12-31" |
| NKD US→JST date align in backtest | YES — ndf indexed JST, RegimeLabels strips JST tz → asof US ET |
| NKD today in live runner | PARTIAL — runner passes US ET date; NKD desired_position handles JST internally; stress check is ET-only (correct). Live feed timing TBD. |
| extreme/ratchet carry across days | YES — same code path in desired_position (identical backtest_swing_tf) |
| missing-bar | **NO** — parquet data is complete; live can have gaps |

### E. Feed (live-only, not historical-coverable)

| Condition | Injection test exists? |
|---|---|
| Late / missing / duplicate bars | NO |
| Out-of-order bar delivery | NO |
| IBKR disconnect + reconnect + backfill | NO |
| NKD JST: US bar arrives after NKD signal time | NO |
| Databento cache format vs IBKR real-time format mismatch | NO |
| IBKR reconnect → double-count open position | NO |

---

## Bước 2 — Coverage Table

### Exit breakdown (2018-2024, all instruments)

| Engine | Total | CHANDELIER | MAX_HOLD | GAP | same-day |
|---|---|---|---|---|---|
| Swing TF (MES/MNQ/MYM/M2K) | 2,442 | **1,922** (78.7%) | **396** (16.2%) | **124** (5.1%) | 0 |
| NKD (MNKD) | 648 | **548** (84.6%) | **96** (14.8%) | **4** (0.6%) | 0 |
| STRESS_MID (4 instr.) | 429 | n/a | n/a | n/a | **429** (100%) — stop 156 / target 86 / eod 187 |

### STRESS_MID year distribution

| Year | Count | % |
|---|---|---|
| 2018 | 85 | 19.8% |
| 2019 | 25 | 5.8% |
| 2020 | 106 | 24.7% |
| 2021 | 22 | 5.1% |
| **2022** | **188** | **43.8%** |
| 2024 | 3 | 0.7% |

Regime distribution (2018-2022 IS window): Normal=851d, Calm=798d, Stress=112d (8.1% of days).

### Circuit breaker thresholds

```
1-micro combined MaxDD ≈ $5,185  (10.4% of $50k account)
WARN threshold (10% DD) = $5,000  → likely briefly crossed
HALT threshold (15% DD) = $7,500  → NEVER reached in 7-year history
historical halts = 0 in every reconcile run
```

### Coverage adequacy

| Mechanism | # exercises | Adequate? |
|---|---|---|
| CHANDELIER exit | 2,470 | ✓ Well tested |
| MAX_HOLD exit | 492 | ✓ Well tested |
| STRESS_MID eod/stop/target | 429 | ✓ OK |
| GAP exit | 128 (5.1% swing, 0.6% NKD) | ⚠ Rare; fill-price assumption is critical |
| Same-day runner close — state-diff path | **0** | ✗ UNTESTED |
| Circuit breaker HALT (allow_new_entries=False) | **0** | ✗ UNTESTED |
| Circuit breaker WARN (size×0.5) | **0** | ✗ UNTESTED — and size_multiplier is never read by caller |
| Half-day CME early close | **0** | ✗ UNTESTED |
| Rejected entry → stale-price retry | **0 correct** | ✗ BUG (see UT-2) |

---

## Under-Tested List

### UT-1: circuit_breaker HALT — halts=0, path dead in all history

**Root cause:** Sizer targets MaxDD=10%, buffer under 15% hard cap. System is designed to never hit HALT threshold in normal operation.

**Why it matters:** `decide_day` calls `breaker.start_day + update + status.allow_new_entries`. This path has never executed in any reconcile. Bugs here (uninitialized breaker, wrong equity reference, `_day_start_equity=None`) are invisible.

**Also:** `size_multiplier=0.5` at WARN is returned by `CircuitBreaker.status()` but is **never read** in `decide_day` or `runner.run_day`. WARN reduces nothing. Silent dead field.

**Synthetic scenario:** Force equity = `account × 0.83` (17% DD from peak) → verify `allow_new_entries=False` propagates through `decide_day → halted list → runner.run_day`.

---

### UT-2: Rejected entry → stale price retry — STRUCTURAL BUG

**The bug:** When a swing/NKD entry is cap-rejected on day D, `generate_today_signals` calls `desired_position()` on day D+1. Backtest still returns open position with `entry_day=D` and `entry=D_close_price`. `diff_desired_vs_held` sees `cur is None` → generates entry candidate with **stale price from yesterday**. Live IBKR order targets the wrong price.

**Where verify_runner_real avoids this** (`real_signal_fn`, line ~242):
```python
# Only generate entry on the trade's actual entry day.
# If new_ed < day_ts the entry was already attempted (and rejected) — never retries.
if new_ed == day_ts:
    desired[key] = sig
else:
    desired[key] = None
```

**The actual `generate_today_signals` has no such guard.** It would retry with stale price every day until the backtest's exit_day passes.

**Coverage:** verify_runner_real is self-consistent (reference suppresses retries, runner matches reference), but it does NOT prove the live signal path is correct under cap rejection. This is a divergence between `verify_runner_real.real_signal_fn` and `signal_layer.generate_today_signals`.

---

### UT-3: Same-day runner close (state-diff path) — CLOSED ✅

**Findings (2026-07-04):**

**B1 — backtest cannot produce same-day swing:** `backtest_swing_tf` exit check runs BEFORE entry check in the day loop. Earliest possible exit is D+1. 592 trades, 0 same-day confirmed.

**B2 — runner path exercises correctly (synthetic injection):** Injected a state-diff candidate with `exit == entry_day` directly. Runner fires OPEN + CLOSE, residual=0, pnl=$250 realized. PASS.

**B3 — path is structurally dead in live signal path:** `generate_today_signals` state-diff candidates have no `exit` field. `runner.run_day` same-day branch (`if t.get("exit") == day`) never fires for live swing/NKD.

**Conclusion:** Same-day runner close path active only for STRESS_MID (explicit `exit=day` in event candidates) + verify_runner_real (ledger injection). Swing/NKD: structurally impossible in backtest, structurally dead in live. No latent bug — behavior is consistent by design.

---

### UT-4: Half-day CME sessions — 0 in parquet

CME half-days (approx 8×/year): day-after-Thanksgiving, Christmas Eve, July 3, Good Friday. Exchange closes ~13:00 ET.

**MES parquet:** `0` days with `<200 1-minute bars` → continuous data does not model early close.

**Two consequences:**
1. **Open position:** chandelier stop evaluated against truncated bars. If price gaps through stop after 13:00, engine sees nothing.
2. **Entry:** `between_time("14:00", "15:55")` returns empty → no TREND_FOLLOW signal. Correct behavior but untested.

---

## Bước 3 — Fault Injection Results (E-conditions, tested 2026-07-04)

| E-condition | Result | Action required |
|---|---|---|
| **C1: Late bar** | PASS — single dropped bar: no crash, 100% matching trades (64/64) | None — gap bridged by time-break detection |
| **C2: Duplicate bar** | PASS — exact duplicate: idempotent OHLC accumulate, PnL identical, no crash | None — exact dup is idempotent; different-value dup still a risk (C2 risk) |
| **C3: Out-of-order bars** | PASS (no crash), DOCUMENTED — shuffled 10 bars within day: 0 trade shift in this sample. Chandelier ratchet order-dependent in general. | IBKRBroker must sort bars by timestamp before passing to signal layer |
| **C4: Missing bar (30 bars)** | PASS — no crash, 64/64 trades, PnL identical; gap falls in overnight session (no impact) | None — GAP_MIN detection handles feed gaps naturally |
| **C5: IBKR disconnect double-count** | **FAIL** — injected duplicate OpenPos in runner.state → 2 CLOSE orders, PnL doubled (+$300 vs +$150). runner.state is NOT self-healing. | IBKRBroker reconnect handler MUST reconcile broker.get_positions() vs runner.state and dedup before next run_day() |
| **C6: OHLC uppercase format** | **FAIL** — KeyError: engine expects lowercase `open/high/low/close/volume`; IBKR uppercase crashes immediately | IBKRBroker data normalizer MUST lowercase column names on ingestion |
| **C7: NKD JST late feed** | PASS — covered by UT-5 S2; `new_ed != today_norm` → suppressed (conservative) | None — UT-5 fix handles this |

---

## Summary

### Final verification (2026-07-04)

```
verify_runner_real.py -- ALL PASS
  Reference (deploy_sim.replay):  $52,961.74
  Runner + real signal:           $52,961.74  Diff $+0.00  PASS
  Taken/rejected per cluster:     all match   PASS
  Circuit breaker halted:         0           PASS
  OPEN fills: 2706  CLOSE fills: 2706         PASS
  Residual positions: 0                       PASS
  Broker equity: $102,961.74 (expected)       PASS
```

Baseline preserved through all Phase A/B/C work.

### Solid (reconcile proved)
- CHANDELIER / MAX_HOLD / GAP exit math: identical engine → harness → live signal path
- STRESS_MID entry_signal vs adapter: identical on all historical Stress days
- NKD desired_position Phase 1+2: boundary-verified (all trades)
- Swing desired_position: boundary-verified (20 samples/instrument)
- deploy_sim.replay vs decide_day: byte-identical (verify_runner_real PASS)
- gap_fill=True: consistent across all paths
- Regime labeling: fit_C consistent across all 3 clusters

### Under-tested (reconcile passes, coverage near-zero)
| # | Issue | Priority |
|---|---|---|
| UT-2 | **Stale price retry — FIXED** in generate_today_signals (cap-rejected entries, swing/NKD guard) | ✅ Fixed |
| UT-5 | **NKD late-bar — FIXED** in generate_today_signals (feed-delayed bars admitted stale entry) | ✅ Fixed |
| UT-6 | NKD branch zero synthetic coverage — guard/rollover/alignment not in 6 cap-rejection scenarios | 🟡 Medium |
| UT-1 | circuit_breaker HALT never exercised — path dead in history | 🟡 Medium |
| UT-3 | **Same-day runner close — CLOSED** (path dead in live; synthetic injection PASS) | ✅ Closed |
| UT-4 | **Half-day CME — CLOSED** (A1-A4 PASS: no crash, no entry, position carries through) | ✅ Closed |
| — | WARN size_multiplier=0.5 — **intentional dead field** (see note below) | ✅ Closed |

### Feed / E-condition injection (C1–C7, tested 2026-07-04)

| # | Condition | Result | Pre-live action |
|---|---|---|---|
| C1 | Late bar (single drop) | PASS | None |
| C2 | Duplicate bar (exact) | PASS — idempotent | IBKRBroker: guard against different-value dup on same ts |
| C3 | Out-of-order bars | No crash; stop levels order-dependent | IBKRBroker: sort_index() before passing to signal layer |
| C4 | Missing bars (30 overnight) | PASS | None |
| C5 | IBKR disconnect double-count | **FAIL** — runner.state not self-healing | IBKRBroker reconnect: reconcile broker vs runner.state |
| C6 | OHLC uppercase format | **FAIL** — KeyError on uppercase columns | IBKRBroker: lowercase column names on ingestion |
| C7 | NKD JST late feed | PASS (UT-5 covers this) | None |

**Two hard pre-live requirements from E-injection:** C5 (reconnect reconcile) + C6 (column normalization).
Implemented in `global_index/ibkr_broker.py`. Verified by injection test `global_index/test_ibkr_injection.py`:
14/14 PASS (C3: 3/3, C6: 4/4, C5: 7/7). No live IBKR connection required — uses `_raw_fetcher` injection point.

### Circuit breaker design — WARN intentionally not wired

Protection is **binary**: full size until HALT, then full stop. No gradual de-risking.

Active layers:
- **HALT (15% DD)**: `allow_new_entries=False` — no new entries until equity recovers past 15%
- **HALT_DAY (>4% daily loss)**: same effect, resets each day

WARN layer (10% DD) — `size_multiplier=0.5` in `CircuitBreaker.status()` — is **deliberately
not wired**. `decide_day` reads only `allow_new_entries` and ignores `size_multiplier`.
This was a conscious decision: the WFO and vault results were validated at full size with
binary protection only. Wiring WARN de-risking changes sizing behavior and would require
re-running WFO and re-sealing vault params. Do not wire without that re-validation.

Practical note: WARN is also nearly unreachable. A same-day 10% equity loss trips HALT_DAY
(4% daily stop, evaluated first in `status()`) before the WARN branch, so WARN only appears
through gradual multi-day accumulation with no single day exceeding 4% loss.

### Operational constraint — NKD date alignment

**Assumption baked into UT-5 fix (generate_today_signals):**

The NKD guard uses `today_norm` (ET trading date) to compare against `desired_position`'s
`entry_day` (tz-naive JST calendar date). This works because:

> NKD regular session (09:00–15:30 JST) ends at ~01:30–02:30 ET.
> The runner is assumed to execute **after NKD closes**, at US market open (~09:30 ET).
> By then, all NKD bars for today's JST session are available → JST calendar date == ET calendar date.
> A stale feed (last bar = yesterday) has `entry_day < today_norm (ET)` → suppressed (conservative).

**If the runner schedule changes to before ~02:30 ET:**
- NKD session may still be in progress → today's bars are incomplete
- `desired_position` returns today's partially-filled session trade with `entry_day = today JST = today ET`
- Guard admits it — but bars are mid-session, signal may be unreliable
- The `nkd_today_norm` approach (comparing JST last bar date to JST entry_day) was more conservative here
- **Action required:** revisit NKD alignment if runner ever moves to pre-market / overnight hours.

**Verified (2026-07-04):** 4 NKD synthetic scenarios (fresh/late/rollover/admission) PASS.
Historical baseline $52,961.74 unchanged (no late-feed in historical data).

### No coverage (feed / injection)
All of E: late/missing/duplicate/reordered bars, IBKR disconnect, NKD JST timing, format mismatch. Cannot be proved by historical replay. Requires fault injection suite before any live IBKR connection.
