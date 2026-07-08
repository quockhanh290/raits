# FUTURES SYSTEM MODEL — 4 Dimensions
> Derived entirely from code. No guessing. Source: `global_index/*.py` + `futures/*.py`.  
> IBKR/stocks side (`raits/raits/`) excluded. HMMEngine (`raits/hmm/engine.py`) noted as shared dependency only.

---

## CHIỀU 1 — CONTROL FLOW

### Construction (một lần)

```
FuturesRunner.__init__(broker, guard, contracts_by_inst, signal_fn, breaker,
                       hmm_stale_guard, positions_path, lock_path, live_state_path,
                       stop_path, max_contracts_per_order)
│
├─ E1: _acquire_lock(lock_path)           runner.py:186   — PID lockfile; raise if alive process
├─ B1: load persisted state from positions_path (JSON)    runner.py:195
│     └─ H2: discard corrupt positions (contracts≤0 or risk_dollars<0) runner.py:237
├─ B1: restore breaker.peak_equity, _day_start_equity, cur_day from file  runner.py:273
└─ DecisionState(equity=broker.get_equity(), open_positions=loaded,
                 taken={cluster:0}, rejected={cluster:0}, breaker=breaker)
                                                           live_decision.py:54
```

### Each Trading Day: `run_day(day)`

```
run_day(day)                                               runner.py:327
│
├─ [D5] STOP_FILE check (stop_path.exists())               runner.py:341
│       → if present: log CRITICAL, _emit_event; entry_candidates=[] (applied later)
│
├─ [1] fetch bars — causal
│   insts = held_instruments ∪ contracts.keys()
│   bars = {inst: broker.fetch_bars(inst, through=day)}    runner.py:356 / broker.py:85
│   ├─ [C3] alert empty bars for open-position insts       runner.py:361   (alert only, no block)
│   └─ [E3] clock sanity: if today > max(bar_dates) + 3d   runner.py:377
│            → _e3_skip_entries=True (entries discarded later, exits run)
│
├─ [2] signal generation — C1: wrapped try/except          runner.py:404
│   signal_fn(day, bars, held_positions)
│   └─ generate_today_signals(*)                           signal_layer.py:100
│       ├─ [Swing / C4 per-cluster try/except]
│       │   swing_engine.desired_basket(swing_dfs, labels, costs)
│       │   └─ SwingTFEngine.desired_position(df, labels, cost)  swing_tf.py:47
│       │       └─ backtest_swing_tf(df, labels, cost,            _validated_core.py:226
│       │              ema=30, mult=2.5, hold=5, return_open=True)
│       │           └─ _swing_cache(df)                    _validated_core.py:199
│       │               precompute: daily_atr_series, per-day arrays, 5m frames
│       │
│       ├─ [NKD / C4] nkd_engine.desired_position(nkd_df, nkd_labels, nkd_cost)
│       │   └─ backtest_swing_tf(nkd_df, RegimeLabels(lag=1), ...)  (same core)
│       │
│       ├─ diff_desired_vs_held(desired, held)             signal_layer.py:67
│       │   → (state_entries, exits) — state diff for swing + NKD
│       │
│       ├─ daily_atr_series(df) × instruments (pre-compute each day)
│       ├─ to_candidate(inst, dir, entry, stop, cluster, n, pv, atr, mult)
│       │   risk_sized = n × mult × daily_ATR × point_value signal_layer.py:57
│       │
│       └─ [Stress / C4] only if today_regime=="Stress"
│           stress_engine.entry_signal(bars_1015, regime)  stress_mid.py:59
│           → StressMidAdapter logic internalized           _validated_core.py:121
│
├─ [J2] _SWING_CACHE.clear()  — memory bound after signal   runner.py:424
│
├─ [E3] if _e3_skip_entries → entry_candidates=[]           runner.py:431
├─ [D5] if _stop_active     → entry_candidates=[]           runner.py:434
│
├─ [2b] HMM stale guard — C2: wrapped try/except            runner.py:441
│   hmm_stale_guard.check_day(day)
│   ├─ _read_spy_last_date(csv)                             hmm_stale_guard.py:69
│   ├─ _check_g1(today, spy_last)
│   │   ├─ gap>5 bday → regime_unreliable=True → notify HALTED  hmm_stale_guard.py:136
│   │   ├─ gap>2 bday → WARN once, trade continues          hmm_stale_guard.py:150
│   │   └─ gap≤2 + was unreliable → RECOVERED, clear flag   hmm_stale_guard.py:164
│   └─ _check_g2(today) — model age from fit_end            hmm_stale_guard.py:181
│       ├─ >18 months → URGENT notify once
│       └─ >12 months → WARN notify once
│   [if not entries_allowed] entry_candidates=[]            runner.py:481
│
├─ [3] mark exits — set p.exit_day=day for signals in exit_positions  runner.py:496
│
├─ [4] decide_day(day, state, entry_candidates, guard, contracts)
│                                                           live_decision.py:76
│   ├─ exits: pos.exit_day==day → state.equity += pnl_sized; exits list
│   ├─ circuit breaker:
│   │   breaker.start_day(equity) if new day               live_decision.py:93
│   │   breaker.update(equity)
│   │   allow = breaker.status(equity)["allow_new_entries"] live_decision.py:96
│   │   ├─ DD≥15% → level=HALT  → allow=False
│   │   ├─ daily_loss≥4% → level=HALT_DAY → allow=False
│   │   ├─ DD≥10% → level=WARN  → allow=True  (size_multiplier=0.5 but NOT WIRED)
│   │   └─ else → level=OK      → allow=True
│   └─ entries (sorted entry_priority_key: risk-high-first)
│       ├─ not allow → halted.append, state.halted+=1
│       ├─ guard.admits(pos, open_positions)                net_exposure_multi.py:98
│       │   checks per-cluster gross_pct ≤ max_gross,
│       │              (if set) net_pct ≤ max_net
│       │   roska4_swing:  gross≤5%  net≤4.4%
│       │   roska4_stress: gross≤2.5% (net not set)
│       │   global_nkd:    gross≤2%  net≤2%
│       ├─ not ok → rejected.append, state.rejected[cluster]+=1
│       └─ ok → accepted; OpenPos → state.open_positions.append
│
├─ [5] execute orders — 3 phases                             runner.py:505
│   PHASE 1 — ALL legacy exits first:
│       for p in decision.exits:
│           broker.send_order(Order(p.inst, "CLOSE", ...))
│   PHASE 2+3 — entries, per-entry nested (NOT all-OPEN then all-CLOSE):
│       for t in decision.entries:
│           [F3] if contracts > max_contracts → BLOCK, _emit_event CRITICAL, continue
│           PHASE 2: broker.send_order(Order(t.inst, "OPEN", ...))
│           PHASE 3 (nested, immediate): if t.exit==day:
│               broker.send_order(Order(t.inst, "CLOSE", ...))
│   ORDER MATTERS: exits before entries (cap recalculated after each CLOSE); same-day
│   CLOSE is per-entry inside loop, not deferred to after all OPENs   runner.py:530-535
│
├─ circuit breaker level change detection → _emit_event     runner.py:538
│
├─ [B1] _persist_state()  — atomic JSON write               runner.py:295
│   positions + breaker.peak_equity + _day_start_equity + cur_day
│
└─ dump_state(day) → live_state_data.js (dashboard)         runner.py:704
    operational_status: runner/breaker/regime_freshness/model_age/positions
```

### Annual: Re-freeze Pipeline

```
futures/refreeze.py:run_refreeze_pipeline(anchor, fit_end, spy_csv, data_dir, ...)
│
├─ [0] _alert_if_pending — re-notify if prior failure still pending
├─ [1] refreeze_hmm(anchor, fit_end, spy_csv)
│   ├─ G3: _check_spy_coverage — abort if SPY data < fit_end  refreeze.py:127
│   └─ label_regimes(spy, train_end, n_components, fit_end)   _validated_core.py:79
│       └─ HMMEngine.fit + predict_current (raits.hmm.engine — shared dependency)
├─ [2] run_gate(labels_prev, labels_new)  — % label change vs current
│   AUTO_APPROVE (<5%) / VERIFY (5-15% or calm-flip) / HOLD (>15%)
├─ [3] run_verify(record, labels_new, ...)  — deploy_sim Calmar ≥ 2.38 (floor=fit_A)
├─ [4] apply_freeze(record)  → futures_freeze_registry.json  refreeze.py:453
└─ [5] rollback() if verify failed                           refreeze.py:470
```

---

## CHIỀU 2 — DATA FLOW

### Mạch đầy đủ (một ngày)

```
[SOURCE] bars_by_inst  (Parquet files — loaded once at startup or broker mock)
    │
    ▼
broker.fetch_bars(inst, through=day)
    → bars: {inst: pd.DataFrame}  (causal slice through day)
    │
    ▼
signal_fn(day, bars, held_positions)
    ├─ INPUT:  day (Timestamp), bars ({inst:DF}), held (list[OpenPos])
    ├─ INTERNAL:
    │   swing_dfs + nkd_df (bars passed in)
    │   swing_labels / nkd_labels ({day: "Calm/Normal/Stress"} — from HMM, pre-computed)
    │   swing_costs / nkd_cost  (FuturesCost: point_value, tick, slippage)
    │   stress_bars_1015  (intraday slice 9:30-10:15)
    │   today_regime (string — label for today from labels dict)
    │   point_values / contracts_by_inst (fixed config)
    ├─ PROCESSING:
    │   desired: {(inst,cluster): {direction,entry,stop,entry_day} | None}
    │   diff_desired_vs_held → state_entries (new/flip) + exits (no-longer-desired)
    │   atr_swing: {inst: daily_atr_series}  ← daily_atr_series(df) each call
    │   to_candidate → risk_sized = n × mult × atr × pv
    └─ OUTPUT:
        entry_candidates: list[dict{inst,direction,cluster,risk_sized,entry,stop}]
        exit_positions:   list[OpenPos]
    │
    ▼
[guard layer — G1/D5/E3/C1] → may clear entry_candidates entirely
    │
    ▼
[exits marking] exit_positions → p.exit_day = day
    │
    ▼
decide_day(day, state, entry_candidates, guard, contracts_by_inst)
    ├─ INPUT:
    │   state: DecisionState (equity, open_positions, cur_day, breaker, taken, rejected, halted)
    │   entry_candidates: list[dict]
    │   guard: MultiClusterGuard (clusters, account)
    │   contracts_by_inst: {inst: int}
    ├─ PROCESSING:
    │   exits realized → state.equity += pnl_sized
    │   breaker.status(equity) → allow: bool
    │   sorted(candidates, key=entry_priority_key)  [risk-high-first]
    │   guard.admits(pos, open_positions) → (bool, reason_str)
    └─ OUTPUT:
        DayDecision(day, exits, entries, rejected, halted, realized, rejected_details)
        state mutated: equity, open_positions, taken, rejected, halted, cur_day
    │
    ▼
broker.send_order(Order) → Fill
    ├─ Order: inst, action(OPEN/CLOSE), direction, contracts, cluster, ref_day,
    │         exit_day, pnl_sized
    └─ Fill:  inst, action, direction, contracts, cluster, pnl_sized
    │
    ▼
_persist_state()  → live_positions.json
dump_state(day)   → live_state_data.js
```

### Label pre-computation (tính một lần, trước khi loop)

```
spy_daily.csv
    └─ benchmark_daily(csv)          _validated_core.py:68
    └─ label_regimes(daily, "2018-01-01", 3, "2024-12-31")  _validated_core.py:79
        ├─ HMMEngine.fit(train)  [shared: raits.hmm.engine]
        └─ HMMEngine.predict_current(window) → state_name → label each day
        → labels: {day: "Calm"/"Normal"/"Stress"}  (dict, tz-naive keys)

For NKD: RegimeLabels(spy_regime, lag_days=1)  — regime.py:42
    .get(day) returns SPY regime as-of (day-1)  [lookahead-safe for JST session]
```

---

## CHIỀU 3 — CROSS-CUTTING SAFETY LAYERS

### Thứ tự can thiệp trong run_day pipeline

```
SCOPE:  ████ = blocks all entries (batch kill)
        ░░░░ = blocks per-entry
        ···· = alert/warn only (no block)

run_day(day)
│
│ [Construction gate]
├── E1 PID lockfile ████████████████ → raises RunnerLockError (process level)
│                                      runner.py:186
│
│ [Pre-signal batch gates]
├── D5 STOP_FILE ████████████████████ → entry_candidates=[]
│                                       exits unaffected runner.py:341
│
├── C3 empty bars  ···· alert only ···· (no block)   runner.py:361
│
├── E3 clock skew ████████████████████ → entry_candidates=[]
│   (today > last_bar + 3d)             exits unaffected runner.py:377
│
│ [Signal generation]
├── C1 signal_fn exception ██████████ → entry_candidates=[], exit_positions=[]
│                                       runner.py:404
├── C4 per-cluster exception ███████ → skip that cluster's entries only
│   (swing/NKD/stress isolated)         held positions preserved (dummy "hold" signal)
│                                       signal_layer.py:162/201/257
│
│ [Post-signal HMM guard block — step 2b, runner.py:441]
├── C2 stale_guard exception ███████████ → entry_candidates=[]
│   check_day() raises → entries_allowed=False   conservative block (fail-CLOSED)
│   exits unaffected                             runner.py:449-460
├── G1 HMM HARD-stale ███████████████ → entry_candidates=[]
│   (SPY CSV >5 bday)                   exits unaffected runner.py:481
│                                       hmm_stale_guard.py:136
├── G1 HMM SOFT-stale  ···· warn ···· (no block, notify once) hmm_stale_guard.py:150
├── G2 model age URGENT ···· warn ····  (no block, notify once) hmm_stale_guard.py:183
├── G2 model age WARN   ···· warn ····  (no block) hmm_stale_guard.py:197
│
│ [Per-entry gates — inside decide_day]
├── CircuitBreaker HALT ░░░░░░░░░░░░░ → individual entry → halted list
│   (DD≥15% from peak)                  live_decision.py:92, circuit_breaker.py:69
├── CircuitBreaker HALT_DAY ░░░░░░░░░ → individual entry → halted list
│   (daily_loss≥4%)                     circuit_breaker.py:71
│   [CircuitBreaker WARN: allow=True, size_multiplier=0.5 NOT WIRED]
│
├── MultiClusterGuard.admits ░░░░░░░░ → individual entry → rejected list
│   per-cluster budget check:           net_exposure_multi.py:98
│   roska4_swing  gross≤5%  net≤4.4%
│   roska4_stress gross≤2.5% (no net)
│   global_nkd    gross≤2%  net≤2%
│   [priority: risk-high-first before cap check — net_exposure_multi.py:64]
│
│ [At-broker gate]
└── F3 fat-finger ░░░░░░░░░░░░░░░░░░ → order NOT sent to broker
    (n > max_contracts_per_order=10)    runner.py:514

[Annual gate — re-freeze only]
G3 SPY coverage ████████ → abort refreeze pipeline if CSV < fit_end
                            refreeze.py:127
```

### Chặn-toàn-bộ vs chặn-từng-lệnh

| Layer | Scope | What passes through |
|-------|-------|---------------------|
| E1 (PID lock) | Process | Second instance blocked entirely |
| D5 (STOP_FILE) | All entries | All exits still run |
| E3 (clock skew) | All entries | All exits still run |
| C1 (signal_fn fail) | All entries + exits | Held positions exit via exit_day on next valid day |
| C4 (per-cluster fail) | One cluster's entries | Other clusters and held positions unaffected |
| C2 (stale_guard fail) | All entries | All exits still run |
| G1 HARD (stale) | All entries | All exits still run |
| CircuitBreaker HALT/HALT_DAY | Per-entry | Goes to `halted` list |
| MultiClusterGuard | Per-entry | Goes to `rejected` list |
| F3 (fat-finger) | Per-order | Order not sent to broker |

### Entry lifecycle — what can stop an entry

```
entry_candidate dict
    │
    ├─ batch-killed by D5/E3/C1/C2/G1 (never reaches decide_day)
    │
    ├─ halted by CircuitBreaker in decide_day
    │   → DayDecision.halted, state.halted += 1
    │
    ├─ rejected by MultiClusterGuard.admits in decide_day
    │   → DayDecision.rejected, state.rejected[cluster] += 1
    │
    ├─ accepted → OpenPos appended to state.open_positions
    │   → broker.send_order(OPEN)
    │       ├─ F3 fat-finger check: n > max → not sent (CRITICAL event)
    │       └─ if passes: Fill returned; position live in broker
    │
    └─ same-day exit: entry+exit same day → also send_order(CLOSE) immediately
```

---

## CHIỀU 4 — STATE LIFECYCLE

### State categories

| State | Persistence | Scope | Where |
|-------|-------------|-------|-------|
| `open_positions` | JSON file (atomic) | Cross-day | `live_positions.json` |
| `breaker.peak_equity` | JSON file (atomic) | Cross-day | `live_positions.json` |
| `breaker._day_start_equity` | JSON file (atomic) | Cross-day | `live_positions.json` |
| `state.cur_day` | JSON file (atomic) | Cross-day | `live_positions.json` |
| `state.equity` | Memory only | Cross-day (session) | `DecisionState` |
| `state.taken / rejected / halted` | Memory only | Cross-session cumulative | `DecisionState` |
| `_last_breaker_level` | Memory only | Cross-day | `FuturesRunner` |
| `_events` | Memory only (bounded 500) | Session | `FuturesRunner` |
| HMM labels | Memory (closure) | Computed once at startup | `signal_fn` closure |
| `_SWING_CACHE` | Memory (module-level dict) | Within-day (cleared J2) | `_validated_core` |
| `guard.clusters / account` | Memory (fixed) | Lifetime (config) | `MultiClusterGuard` |
| `HMMStaleGuard` flags | Memory | Session (persists in-process) | `hmm_stale_guard.*` |
| `futures_freeze_registry.json` | JSON file | Annual | `models/hmm/` |
| `refreeze_pending.json` | JSON file | Until resolved | `models/hmm/` |
| `live_state_data.js` | JS file (dashboard) | Per-day write | `dump_state()` |
| `runner.pid` | Lockfile | Process lifetime | `E1` |

### Chu kỳ khép (persist → load ngày mai)

```
EOD:  _persist_state()
        write: live_positions.json = {
            schema_version: 1,
            positions: [OpenPos...],
            breaker: {peak_equity, day_start_equity, cur_day}
        }
        runner.py:309

BOD (restart):  FuturesRunner.__init__()
        read:  live_positions.json
        → loaded_positions → DecisionState.open_positions
        → loaded_peak_equity → breaker.peak_equity restored
        → loaded_day_start_equity → breaker._day_start_equity
        → loaded_cur_day → state.cur_day
        runner.py:195

WHY restore peak_equity: without restore, peak resets to current equity on restart
→ DD appears 0% even if real DD is 12% → HALT blind (bug, B1 fix)
runner.py:271
```

### State that does NOT persist across restarts

```
state.equity        ← reset to broker.get_equity() on __init__
state.taken         ← reset to {cluster:0}
state.rejected      ← reset to {cluster:0}
state.halted        ← reset to 0
_events             ← reset to []
_last_breaker_level ← reset to "OK"
HMMStaleGuard flags ← reset (regime_unreliable=False, etc.)
_SWING_CACHE        ← reset (empty dict)
```

### equity restart — hai nguồn, ĐÚNG (không phải bug)

**Câu hỏi**: `state.equity` tích lũy pnl in-session (`state.equity += pnl_sized` trong decide_day).
Sau restart reset về `broker.get_equity()`. Có mismatch không?

**Verify từ code**:
```
In-session:   decide_day → state.equity += p.pnl_sized  (live_decision.py:85)
              runner → broker.send_order(CLOSE) → broker._equity += pnl_sized  (broker.py:103)
After restart: state.equity = broker.get_equity()  (runner.py:265)
```

**Kết luận: ĐÚNG.** Broker là source-of-truth:
- Trong session: cả `state.equity` lẫn `broker._equity` nhận cùng delta (pnl_sized). Sau mỗi
  `run_day()` hoàn chỉnh chúng bằng nhau.
- Sau restart: `state.equity = broker.get_equity()` — sync từ nguồn thật. Không cần persist
  `state.equity` vì broker đã là record chính xác.
- `peak_equity` PHẢI persist (B1) vì broker không lưu lịch sử đỉnh — chỉ equity hiện tại.
  Không có B1: peak=current → DD=0% mù. Đây là asymmetry có chủ đích, không phải thiếu sót.

**WARN là dead field (OPEN QUESTION)**:
`CircuitBreaker.status()` trả về `size_multiplier=0.5` khi WARN (DD≥10%). NHƯNG `decide_day`
chỉ đọc `allow_new_entries` và bỏ qua `size_multiplier` hoàn toàn (live_decision.py:96).
- Hệ thống là BINARY: full-size hoặc HALT, KHÔNG có tầng giảm-nửa-size.
- WARN thực tế gần như không reach được: loss một ngày >4% trips HALT_DAY trước khi WARN
  được evaluate; WARN chỉ surface qua multi-day accumulation không có ngày nào > 4%.
- Intentional design: wiring `size_multiplier` sẽ thay đổi trade sizing, cần re-validate
  WFO + vault trước khi deploy.
- circuit_breaker.py:19 ghi rõ: "WARN layer — INTENTIONALLY NOT WIRED".

---

## TEST ĐẦYỦ — GREP VERIFICATION

### Tất cả cơ chế chặn tìm thấy trong code → đều có trong mô hình?

| Found in code | In model? | Source |
|---|---|---|
| `admits` (MultiClusterGuard) | ✓ CHIỀU 3 | net_exposure_multi.py:98 |
| `allow_new_entries` (CircuitBreaker) | ✓ CHIỀU 3 | circuit_breaker.py:78, live_decision.py:96 |
| `HALT` / `HALT_DAY` | ✓ CHIỀU 3 | circuit_breaker.py:69-71 |
| `regime_unreliable` (G1 HARD block) | ✓ CHIỀU 3 | hmm_stale_guard.py:136, runner.py:481 |
| G1 SOFT warn | ✓ CHIỀU 3 | hmm_stale_guard.py:150 |
| G2 model age warn | ✓ CHIỀU 3 | hmm_stale_guard.py:181-197 |
| G3 re-freeze abort | ✓ CHIỀU 3 | refreeze.py:127 |
| D5 STOP_FILE | ✓ CHIỀU 3 | runner.py:341 |
| E3 clock skew | ✓ CHIỀU 3 | runner.py:377 |
| C1 signal_fn fail | ✓ CHIỀU 3 | runner.py:404 |
| C2 stale_guard fail | ✓ CHIỀU 3 (intervention order + table) | runner.py:449 |
| C3 empty bars alert | ✓ CHIỀU 3 (warn-only) | runner.py:361 |
| C4 per-cluster fail | ✓ CHIỀU 3 | signal_layer.py:162/201/257 |
| F3 fat-finger | ✓ CHIỀU 3 | runner.py:514 |
| E1 PID lockfile | ✓ CHIỀU 3 | runner.py:186 |
| H2 corrupt position discard | ✓ CHIỀU 1 (construction) | runner.py:237 |
| J2 _SWING_CACHE.clear | ✓ CHIỀU 4 (memory bound) | runner.py:424 |

### Tất cả state persist tìm thấy → đều có trong mô hình?

| Found in code | In model? | Source |
|---|---|---|
| `peak_equity` | ✓ CHIỀU 4 | circuit_breaker.py:41, runner.py:274 |
| `_SWING_CACHE` | ✓ CHIỀU 4 | _validated_core.py:197 |
| `_persist_state` | ✓ CHIỀU 4 | runner.py:295 |
| `live_positions.json` | ✓ CHIỀU 4 | runner.py:309 |
| `futures_freeze_registry.json` | ✓ CHIỀU 4 | refreeze.py:50 |
| `refreeze_pending.json` | ✓ CHIỀU 4 | refreeze.py:54 |
| `live_state_data.js` | ✓ CHIỀU 4 | runner.py:704 |
| `state.cur_day` | ✓ CHIỀU 4 | live_decision.py:58, runner.py:285 |
| `runner.pid` | ✓ CHIỀU 4 | runner.py:186 |
