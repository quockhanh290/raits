# Futures — PIPELINE FLOW
_Trace thật từ runner.run_day(). Thứ tự CHÍNH XÁC trong code, không phải thiết kế lý tưởng._
_Cập nhật: 2026-07-14. Chi tiết file: xem [SCRIPT_INVENTORY.md](SCRIPT_INVENTORY.md). Xem thêm: [DAILY_FLOW.md](DAILY_FLOW.md) (timeline lệnh) · [DAILY_UPDATE_RUNBOOK.md](DAILY_UPDATE_RUNBOOK.md) (data safety)._

---

## Sơ đồ bước — mỗi ngày trading

```
PRE-DAY (13:45 ET, scheduler tự động):
  update_ibkr_daily.py → futures parquet (4 instruments MES/MNQ/MYM/M2K + NKD = 5 total, append daily bars)
  update_spy_csv.py    → spy_daily_live.csv  (Polygon adjusted close, 30d overlap)
  [G1 freshness gate: HMMStaleGuard chưa wire trong production — xem I5.12]
  ── (annual) ──
  refreeze.py       → models/PRODUCTION.pkl

CONSTRUCTION (MỖI NGÀY — run_live_day.py là run-and-exit subprocess, label_regimes gọi trong main()):
  label_regimes(spy_daily_live.csv, fit_end=2024-12-31)
  → RegimeLabels dict {date → "Calm"/"Normal"/"Stress"}   ← HMM model frozen (fit_end=2024-12-31)
  SwingTFEngine(basket), StressMidEngine(basket), CircuitBreaker
  → bound vào signal_fn (closure)
  → FuturesRunner(broker, signal_fn, guard, breaker, hmm_stale_guard=None)
  [G1 HMMStaleGuard chưa wire: hmm_stale_guard=None trong production — xem I5.12]

────────────────────────────────────────────────
RUN_DAY(day):
────────────────────────────────────────────────

[0-EMIT] "Day started: {day}, {N} position(s) open"
  └── runner.py:_emit_event()

[0-KILL] D5 Kill-switch gate (trước mọi thứ)
  └── runner.py: check STOP_FILE.exists()
  └── Nếu có → log + emit CRITICAL; entries bị discard ở bước 2
  └── Exits KHÔNG bị ảnh hưởng

[1-DATA] Fetch bars qua broker
  └── runner.py: bars = {inst: broker.fetch_bars(inst, through=day+23:59)}
  [through=day+23:59, KHÔNG through=day — LIVE_RUNNER_AUDIT Mismatch B fix, runner.py:745]
  └── broker.py / ibkr_broker.py: IBKRBroker._fetch_raw() [TODO: live]
  In : danh sách instruments (open positions + contracts)
  Out: dict {inst → DataFrame(OHLCV, tz-aware)}
  Guards: C3 (empty bars → WARN), E3 (today - last_bar > 3d → skip entries)

[2-SIGNAL] Signal generation — TẤT CẢ 3 SLEEVE cùng một lần
  └── runner.py: entry_candidates, exit_positions = signal_fn(day, bars, open_positions)
  └── signal_layer.py: generate_today_signals()
      ├── [SLEEVE-Rổ4] swing_tf.SwingTFEngine.desired_position(bars["MES"/"MNQ"/...])
      │     → diff desired vs held → entry/exit events
      │     → gated: chỉ chạy nếu regime ≠ Stress (basket.REGIME)
      │     → to_candidate(): tính risk_dollars = n × mult × ATR × pv
      │     → cluster = "roska4_swing"
      ├── [SLEEVE-STRESS] stress_mid.StressMidEngine.entry_signal(bars, day)
      │     → chỉ kích khi regime == "Stress"
      │     → SHORT tại 10:15 if price < VWAP AND price < open
      │     → cluster = "roska4_stress"
      └── [SLEEVE-NKD] swing_tf.SwingTFEngine.desired_position(bars["MNKD"])
            → diff desired vs held → entry/exit events
            → regime = RegimeLabels.get(day - 1 calendar day)  ← lag=1 (lookahead-safe)
            → cluster = "global_nkd", contracts = 1 (fixed, không scale)
  In : day, bars dict, open_positions list
  Out: entry_candidates list, exit_positions list
  Guards: C1 (exception → empty lists; exits unaffected)
  J2   : _SWING_CACHE.clear() sau signal (memory bound)
  E3/D5: discard entry_candidates nếu clock skew / STOP_FILE

[2b-GUARD] HMM Stale Guard (AFTER signal — entries đã compute, giờ mới gate)
  ⚠️ CHƯA WIRE TRONG PRODUCTION (I5.12): hmm_stale_guard=None → bước này bị SKIP.
  Freshness hiện chỉ dựa pre-flight flag (update_ibkr_daily + update_spy_csv success).
  Thiết kế (khi wire):
  └── runner.py: entries_allowed = hmm_stale_guard.check_day(day)
  └── hmm_stale_guard.py: đọc spy_daily_live.csv last_date
      G1 SOFT (>2 bday stale): WARN, vẫn trade
      G1 HARD (>5 bday stale): regime_unreliable=True → entry_candidates = []
      G2 SOFT (>12 month model age): WARN only
      G2 HARD (>18 month model age): ALERT, WARN only (không halt)
  In : day, spy_daily_live.csv last_date
  Out: entries_allowed bool (False → entry_candidates = [])
  Guards: C2 (exception → entries_allowed=False, conservative block)

[3-EXIT] Mark exits từ signal
  └── runner.py: p.exit_day = day nếu (p.inst, p.cluster) trong exit_positions
  In : exit_positions từ signal_layer, open_positions
  Out: open_positions với exit_day cập nhật (set trong state)

[4-DECIDE] Risk brain
  └── runner.py: decision = decide_day(day, state, entry_candidates, guard, contracts)
  └── live_decision.py: decide_day()
      ├── EXITS: positions với exit_day <= day → realized + removed từ open_positions
      │         CircuitBreaker.update(realized_pnl) → peak_equity, DD track
      ├── BREAKER CHECK: breaker.status().level
      │         HALT/HALT_DAY → entry_candidates = [] (entries blocked)
      └── ENTRIES: for each candidate (ưu tiên risk-high-first):
                   guard.admits(candidate) → MultiClusterGuard per-cluster cap
                   breaker.admits() → account-level DD check
                   Admitted → OpenPos, added to state.open_positions
  └── net_exposure_multi.py: MultiClusterGuard.admits()
  └── circuit_breaker.py: CircuitBreaker.status(), update()
  In : day, state (open_positions, breaker, taken/rejected), entry_candidates, contracts
  Out: DayDecision(exits=[], entries=[], realized=float)

[5-EXEC] Execute orders qua broker
  └── runner.py:
      for exit in decision.exits → broker.send_order(Order CLOSE)
      for entry in decision.entries:
          F3: n > max_contracts → FAT_FINGER BLOCKED (không gửi)
          broker.send_order(Order OPEN, n=contracts[inst])
          same-day entry+exit → broker.send_order(Order CLOSE) immediately
  └── broker.py / ibkr_broker.py: IBKRBroker.send_order() [TODO: live]
  In : DayDecision.exits, DayDecision.entries, contracts_by_inst
  Out: fills tới broker; broker equity update

[5b-BREAKER] Breaker level transition detect (sau execute)
  └── runner.py: breaker.status(broker.get_equity())
  └── emit events khi level thay đổi: OK/WARN/HALT_DAY/HALT
  In : broker.get_equity()
  Out: events (CRITICAL/ALERT/WARN khi level change)

[6-PERSIST] B1 Atomic state persist
  └── runner.py: _persist_state()
  └── write live_positions.json.tmp → os.replace → live_positions.json
  In : state.open_positions, breaker.peak_equity, breaker.day_start_equity, cur_day
  Out: live_positions.json (crash-safe, atomic)

[7-DASH] Dashboard dump (no-op nếu live_state_path=None)
  └── runner.py: dump_state(day)
  → generate_replay_snapshots.py format (khi wired)
  In : state, events, operational_status
  Out: live_state_data.js (nếu live_state_path set)

[RETURN] DayDecision
```

---

## Data Flow

```
                        ┌─────────────────────────────────────────────────────┐
  PRE-DAY               │           CONSTRUCTION (một lần)                    │
                        │                                                     │
  spy_daily_live.csv ───┼──► label_regimes() ──► RegimeLabels dict           │
  (Polygon, daily)      │    (fit_end=2024-12-31, walk-forward HMM)           │
                        │         │                                           │
                        │         ▼                                           │
                        │    signal_fn = wrap(generate_today_signals,         │
                        │         roska4_engines=SwingTFEngine×4,             │
                        │         stress_engine=StressMidEngine,              │
                        │         nkd_engine=SwingTFEngine(NKD),              │
                        │         labels=RegimeLabels,                        │
                        │         costs=FuturesCost)                          │
                        │                                                     │
                        │    runner = FuturesRunner(                          │
                        │         broker=IBKRBroker(account),                 │
                        │         signal_fn=signal_fn,                        │
                        │         guard=MultiClusterGuard,                    │
                        │         breaker=CircuitBreaker(account),            │
                        │         hmm_stale_guard=None)  ← CHƯA WIRE (I5.12) │
                        └─────────────────────────────────────────────────────┘

  EVERY DAY:

  [G1 HMMStaleGuard: CHƯA WIRE — bước này không chạy trong production (I5.12)]

  IBKRBroker ──────────► broker.fetch_bars(insts, through=day+23:59)
  (IBKR TWS API)              │
                              ▼
                         bars = {inst: DataFrame(OHLCV)}
                              │
                              ▼
                         signal_fn(day, bars, open_positions)
                              │
              ┌───────────────┼───────────────────┐
              ▼               ▼                   ▼
         [Rổ4-MES]      [STRESS_MID]          [NKD-MNKD]
         [Rổ4-MNQ]      (Stress only)         regime = D-1 lag
         [Rổ4-MYM]
         [Rổ4-M2K]
              │               │                   │
              └───────────────┴───────────────────┘
                              │
                              ▼
                    entry_candidates + exit_positions
                              │
                              ▼ (filtered by G1, E3, D5)
                              │
                              ▼
                    decide_day(day, state, candidates, guard, contracts)
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
                 EXITS               ENTRIES
              realized_pnl         guard.admits?  ──NO──► rejected
              breaker.update()     breaker.admits? ──NO──► halted
              close OpenPos        ──YES──► new OpenPos
                    │                    │
                    └─────────┬──────────┘
                              ▼
                    DayDecision(exits, entries, realized)
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
            broker.send_order(CLOSE)  broker.send_order(OPEN)
            [IBKRBroker.send_order]   [F3: fat-finger check first]
                    │
                    ▼
            live_positions.json  ◄── _persist_state() (atomic .tmp + replace)
            (peak_equity,
             open_positions,
             cur_day)
                    │
                    ▼
            live_state_data.js ◄── dump_state() (dashboard, nếu wired)
```

---

## Sleeve Activation — điều kiện mỗi sleeve kích

| Sleeve | Module | Cluster | Kích khi | Contracts | Note |
|---|---|---|---|---|---|
| **Rổ4 swing-TF** | `futures/swing_tf.py` SwingTFEngine | `roska4_swing` | regime ≠ Stress (basket.REGIME) → `desired_position()` diff | n_contracts (1 hiện tại) | 4 instruments: MES/MNQ/MYM/M2K |
| **STRESS_MID** | `futures/stress_mid.py` StressMidEngine | `roska4_stress` | regime == "Stress" AND price < VWAP AND price < open tại 10:15 | 1 (same n_contracts) | SHORT only, same-day exit |
| **NKD** | `futures/swing_tf.py` SwingTFEngine | `global_nkd` | regime D-1 (lag 1 day, lookahead-safe) → `desired_position()` diff | **fixed = 1** (không scale) | JST tz, budget 2% = $1,000 chỉ đủ 1 contract |

**Thứ tự trong signal_fn**: tất cả 3 sleeve chạy CÙNG LÚC trong một `signal_fn()` call. Runner không biết sleeve nào — chỉ thấy danh sách `entry_candidates` đã gộp.

**Thứ tự trong decide_day**: entries sorted by `entry_priority_key` (risk-high-first). Cluster caps check độc lập — NKD không ảnh hưởng Rổ4 và ngược lại.

---

## Quan sát quan trọng (không self-evident từ code)

**G1 gate đặt SAU signal_fn** — signal tính hết rồi mới check stale. Đây là ý đồ thiết kế: exits không bị ảnh hưởng (exit_day-based), nên signal_fn phải chạy để có exit_positions. Entries thì bị discard nếu G1 block.

**Regime labels tính MỖI NGÀY trong construction block** — `run_live_day.py` là run-and-exit subprocess, spawn mỗi ngày 14:05. `label_regimes()` gọi trong `main()` nên chạy lại mỗi lần spawn. Nó tính walk-forward labels cho toàn bộ spy_daily_live.csv với model frozen (fit_end=2024-12-31). Mỗi ngày `signal_fn` chỉ lookup `labels.get(day)` trong run_day. `update_spy_csv.py` cập nhật file source — ngày mới có label ngay khi run_live_day.py spawn lại.

**CLOSE trước OPEN** — runner gửi CLOSE trước OPEN (step 5). Quan trọng cho exposure cap: đóng vị thế trước khi mở mới tránh tạm thời double-count trong guard.

**Breaker state persist qua restart (B1)** — `peak_equity` lưu trong live_positions.json. Khi restart, `breaker.peak_equity` được restore. Không có điều này: restart → peak reset → DD=0% → runner "quên" đang trong drawdown.

**NKD contracts cố định = 1** — không scale cùng n_contracts Rổ4. Hardcoded trong `contracts_by[NKD] = 1` ở construction. Budget 2% × $50k = $1,000 chỉ đủ 1 MNKD.

---

_Xem [SCRIPT_INVENTORY.md](SCRIPT_INVENTORY.md) cho phân loại đầy đủ từng file._
