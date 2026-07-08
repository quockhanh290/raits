# FUTURES SYSTEM — 4-Tầng Visualization
> Vẽ từ SYSTEM_MODEL.md. Mỗi tầng một view độc lập.

---

## TẦNG A — Orchestration (runner là nhạc trưởng)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FUTURES RUNNER  (global_index/runner.py)                                   │
│  FuturesRunner.run_day(day)          [daily]                                │
│                                                                             │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────┐  ┌─────────────┐ │
│  │  Broker      │  │  signal_fn     │  │  decide_day    │  │  Persist    │ │
│  │ [daily]      │  │  [daily]       │  │  [daily]       │  │  [daily]    │ │
│  │              │  │                │  │                │  │             │ │
│  │fetch_bars()  │  │generate_today  │  │decide_day()    │  │_persist_    │ │
│  │→ bars        │  │_signals()      │  │→ DayDecision   │  │state()      │ │
│  │              │  │→ (candidates,  │  │                │  │→ positions  │ │
│  │send_order()  │  │   exits)       │  │                │  │  .json      │ │
│  └──────┬───────┘  └───────┬────────┘  └───────┬────────┘  └──────┬──────┘ │
│         │                  │                   │                  │        │
│  ┌──────┴───────────────────┴───────────────────┴──────────────────┴──────┐ │
│  │                    runner.run_day() orchestrates:                      │ │
│  │  1→fetch_bars  2→signal_fn  2b→stale_guard  3→mark_exits              │ │
│  │  4→decide_day  5→send_orders  B1→persist  dump_state                  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘

  Construction (once):
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ FuturesRunner.__init__                                                   │
  │   E1 lock_path    → acquire PID lockfile                                │
  │   positions_path  → load live_positions.json (B1)                       │
  │   H2 validate     → discard corrupt positions                           │
  │   breaker         → restore peak_equity, day_start_equity (B1)          │
  │   DecisionState   → equity, open_positions, taken, rejected             │
  └──────────────────────────────────────────────────────────────────────────┘

  signal_fn detail (injected closure):
  ┌────────────────────────────────────────────────────────────────────────────┐
  │ generate_today_signals()   (global_index/signal_layer.py)                  │
  │                                                                            │
  │  SwingTFEngine ──desired_basket──► diff_desired_vs_held ──► entries/exits  │
  │  (swing_tf.py)                    (signal_layer.py:67)                     │
  │       └── backtest_swing_tf(return_open=True)  (_validated_core.py:226)    │
  │              └── _swing_cache(df)  (precompute arrays)                     │
  │                                                                            │
  │  NKD engine ──desired_position──► diff_desired_vs_held ──► entries/exits   │
  │  (same SwingTFEngine, NKD params, RegimeLabels lag=1)                      │
  │       └── backtest_swing_tf(return_open=True)                              │
  │                                                                            │
  │  StressMidEngine ──entry_signal──► fresh candidates (event model)          │
  │  (stress_mid.py:59)  only if regime=="Stress"                              │
  │       └── StressMidAdapter logic (_validated_core.py:121)                  │
  │                                                                            │
  │  to_candidate() ──► risk_sized = n×mult×ATR×pv                            │
  └────────────────────────────────────────────────────────────────────────────┘

  Annual (operator-triggered):
  ┌────────────────────────────────────────────────────────────────────────────┐
  │ run_refreeze_pipeline()   (futures/refreeze.py)                            │
  │   refreeze_hmm → run_gate → run_verify → apply_freeze / rollback           │
  │   registry: models/hmm/futures_freeze_registry.json                        │
  └────────────────────────────────────────────────────────────────────────────┘
```

---

## TẦNG B — Data Flow (mũi tên có nhãn dữ liệu)

```
  [Parquet files]          [spy_daily.csv]         [live_positions.json]
  MES/MNQ/MYM/M2K/NKD      SPY daily closes         open_positions, peak_equity
        │                        │                         │
        ▼                        ▼ (once at startup)       ▼ (BOD load)
  broker.fetch_bars(inst,   label_regimes()         FuturesRunner.__init__
    through=day)            → labels: {day:regime}   → state.open_positions
  → bars: {inst: DataFrame}   tz-naive, normalized    → breaker.peak_equity
        │                        │                         │
        │            ┌───────────┘                         │
        │            │                                     │
        ▼            ▼                                     ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  generate_today_signals(                                            │
  │      swing_engine, swing_dfs={inst:DF}, swing_labels, swing_costs  │
  │      nkd_engine,  nkd_df,             nkd_labels, nkd_cost         │
  │      stress_engine, stress_bars_1015,  today_regime                │
  │      held=state.open_positions,        point_values, contracts_by  │
  │  )                                                                  │
  │                                                                     │
  │  desired: {(inst,cluster): {dir,entry,stop,entry_day}|None}        │
  │  diff_desired_vs_held → state_entries(list), exits(list[OpenPos])  │
  │  atr: {inst: pd.Series}  daily_atr_series(df)                      │
  │  to_candidate → risk_sized = n×mult×atr×pv                         │
  │                                                                     │
  │  OUTPUT:                                                            │
  │  entry_candidates: [{inst,direction,cluster,risk_sized,entry,stop}]│
  │  exit_positions:   [OpenPos]                                        │
  └──────────────────────────┬──────────────────────────────────────────┘
                             │
                             │  [batch guards may set entry_candidates=[]]
                             │  D5/E3/C1/G1 (see Tầng C)
                             ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  decide_day(day, state, entry_candidates, guard, contracts)      │
  │                                                                  │
  │  INPUT  state.open_positions: [OpenPos]                         │
  │         state.equity: float                                      │
  │         state.breaker: CircuitBreaker                            │
  │                                                                  │
  │  exits:   p.exit_day==day → pnl_sized realized                  │
  │           state.equity += pnl_sized                              │
  │                                                                  │
  │  breaker.status(equity) → allow: bool                            │
  │  sorted(candidates, key=entry_priority_key)  [risk-high-first]  │
  │  guard.admits(pos, open_positions) → (bool, reason)             │
  │                                                                  │
  │  OUTPUT DayDecision:                                             │
  │    .exits:    [OpenPos]  — closed today                          │
  │    .entries:  [dict]     — admitted (pos added to state)         │
  │    .rejected: [dict]     — blocked by cap                        │
  │    .halted:   [dict]     — blocked by breaker                    │
  │    .realized: float      — P&L today                             │
  │                                                                  │
  │  state MUTATED:  equity, open_positions, taken, rejected, halted │
  └──────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
  broker.send_order(Order) → Fill   [3 phases, runner.py:505-535]
    PHASE 1:   ALL legacy exits → CLOSE (decision.exits)
    PHASE 2+3: per entry in decision.entries (nested, NOT all-OPEN then all-CLOSE):
                  [F3 fat-finger check: n > 10 → skip]
                  PHASE 2: send OPEN
                  PHASE 3: if same-day (entry.exit==today) → send CLOSE immediately
                             │
                             ▼
  ┌───────────────────────────────────────────────────┐
  │  _persist_state()   → live_positions.json         │
  │  dump_state(day)    → live_state_data.js           │
  └───────────────────────────────────────────────────┘
```

---

## TẦNG C — Safety Layers (guard/risk/breaker — cắt ngang pipeline)

```
  Pipeline:     fetch → signal → [guards] → decide_day → broker

  ══════════════════════════════════════════════════════════════════════════
  CONSTRUCTION
  ══════════════════════════════════════════════════════════════════════════

  fetch ──────────────────────────────────── broker ─────────────────────
  │                                                                      │
  │  ┌─────────────────────────────────────────────────────────────────┐ │
  │  │  E1: PID LOCKFILE (runner.py:186)                               │ │
  │  │  Scope: PROCESS LEVEL — second instance → RunnerLockError       │ │
  │  └─────────────────────────────────────────────────────────────────┘ │

  ══════════════════════════════════════════════════════════════════════════
  DAILY PIPELINE (entry flow, top to bottom = earlier to later)
  ══════════════════════════════════════════════════════════════════════════

  STEP 1: fetch_bars
     │
     ├──[C3]─── empty bars: ·················· WARN only (no block) ···
     │          runner.py:361
     │
     └──[E3]─── clock skew >3d: ██████████████ ALL entries killed ████
                runner.py:377                   exits unaffected

  STEP 2: signal_fn
     │
     ├──[C1]─── signal_fn exception: ██████████ ALL entries + exits killed
     │          runner.py:404
     │
     └──[C4]─── per-cluster exception: ███████ ONE cluster entries killed
                signal_layer.py:162/201/257      held positions preserved

  POST-SIGNAL
     │
     ├──[D5]─── STOP_FILE present: █████████████ ALL entries killed ████
     │          runner.py:434                    exits unaffected
     │
  STEP 2b: HMM guard block (runner.py:441)
     │
     ├──[C2]─── stale_guard.check_day raises: ██ ALL entries killed ████
     │          conservative fail-CLOSED           exits unaffected
     │          entries_allowed=False  runner.py:449-460
     │
     ├──[G1 HARD]── SPY CSV stale >5 bday: ████ ALL entries killed ████
     │          runner.py:481                    exits unaffected
     │          hmm_stale_guard.py:136
     │
     ├──[G1 SOFT]── SPY CSV stale >2 bday: ····· WARN, trade continues
     │          hmm_stale_guard.py:150
     │
     ├──[G2 URGENT]── model >18 months: ········ WARN only
     │          hmm_stale_guard.py:183
     │
     └──[G2 WARN]── model >12 months: ·········· WARN only
                hmm_stale_guard.py:197

  STEP 4: decide_day — PER-ENTRY gates
     │
     for each entry (risk-high-first order):
     │
     ├──[CircuitBreaker HALT]──────────────────── entry → halted list
     │   DD ≥ 15% from peak                       live_decision.py:102
     │   allow=False → ALL subsequent entries halted (not just one)
     │
     ├──[CircuitBreaker HALT_DAY]─────────────── entry → halted list
     │   daily_loss ≥ 4%                          live_decision.py:102
     │
     ├──[CircuitBreaker WARN]─ allow=True ─────── DEAD FIELD — NOT WIRED
     │   DD ≥ 10%  size_multiplier=0.5 returned   but decide_day ignores it
     │   System is BINARY: full-size or HALT only  circuit_breaker.py:19
     │   (wiring needs WFO+vault re-validation)
     │
     └──[MultiClusterGuard.admits]─────────────── entry → rejected list
         per-cluster: gross/net % of $50k account net_exposure_multi.py:98
         ┌──────────────────────────────────────────────┐
         │  roska4_swing:  gross≤5%   net≤4.4%          │
         │  roska4_stress: gross≤2.5% net=N/A           │
         │  global_nkd:    gross≤2%   net≤2%            │
         │  (clusters are INDEPENDENT — NKD never eats  │
         │   Rổ4 budget; Rổ4 never eats NKD budget)     │
         └──────────────────────────────────────────────┘

  STEP 5: broker.send_order — AT-BROKER gate
     │
     └──[F3 FAT-FINGER]────────────────────────── order NOT sent
         n > max_contracts_per_order (=10)         runner.py:514
         emit CRITICAL event

  ══════════════════════════════════════════════════════════════════════════
  ANNUAL: re-freeze pipeline (operator-triggered)
  ══════════════════════════════════════════════════════════════════════════

     └──[G3 SPY coverage]──────────────────────── ABORT refreeze pipeline
         SPY CSV last_date < fit_end               refreeze.py:127
         notify + write pending flag

  ══════════════════════════════════════════════════════════════════════════
  SUMMARY TABLE
  ══════════════════════════════════════════════════════════════════════════

  Guard          │ When     │ Scope         │ Exits?     │ Code
  ───────────────┼──────────┼───────────────┼────────────┼─────────────────
  E1 PID lock    │ startup  │ process kill  │ N/A        │ runner.py:186
  E3 clock skew  │ post-fch │ all entries   │ unaffected │ runner.py:377
  C1 signal fail │ signal   │ all entries   │ killed too │ runner.py:404
  C4 cluster fail│ signal   │ 1 cluster     │ held safe  │ sl.py:162
  D5 STOP_FILE   │ post-sig │ all entries   │ unaffected │ runner.py:434
  G1 HARD stale  │ post-sig │ all entries   │ unaffected │ runner.py:481
  G1 SOFT stale  │ post-sig │ warn only     │ —          │ hsg.py:150
  G2 age         │ post-sig │ warn only     │ —          │ hsg.py:181
  CB HALT        │ decide   │ per-entry→all │ unaffected │ ld.py:102
  CB HALT_DAY    │ decide   │ per-entry→all │ unaffected │ ld.py:102
  MCGuard.admits │ decide   │ per-entry     │ unaffected │ nem.py:98
  F3 fat-finger  │ broker   │ per-order     │ unaffected │ runner.py:514
  G3 SPY cov.    │ refreeze │ abort pipeline│ —          │ rf.py:127
  C3 empty bars  │ post-fch │ warn only     │ —          │ runner.py:361
  C2 guard fail  │ guard-chk│ all entries   │ unaffected │ runner.py:449
  H2 corrupt pos │ startup  │ discard pos   │ N/A        │ runner.py:237
```

---

## TẦNG D — State Lifecycle

```
  ┌────────────────────────────────────────────────────────────────────────────┐
  │  ONCE AT STARTUP (computed once, lives in signal_fn closure)               │
  │                                                                            │
  │  spy_daily.csv ──► benchmark_daily() ──► label_regimes()                  │
  │                    (_validated_core.py:68)  (_validated_core.py:79)        │
  │                    HMMEngine.fit(train=[2017→2024-12-31])                  │
  │                    HMMEngine.predict_current(expanding window)             │
  │                    → labels: {day→"Calm/Normal/Stress"}  (dict, tz-naive)  │
  │                                                                            │
  │  NKD: RegimeLabels(spy_regime, lag=1)  (global_index/regime.py:42)         │
  │       .get(day) = spy_regime.asof(day-1)  [lookahead-safe, JST session]    │
  │                                                                            │
  │  MultiClusterGuard.clusters  ─────────────── fixed config (net_exp_m.py:53)│
  │  contracts_by_inst            ─────────────── fixed config                 │
  └────────────────────────────────────────────────────────────────────────────┘

                              ↓ once, then stays alive in memory

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  CROSS-DAY PERSISTENT (file → memory → file cycle)                         │
  │                                                                             │
  │  live_positions.json                                                        │
  │  ┌─────────────────────────────────────────────────────────────────────┐   │
  │  │  schema_version: 1                                                  │   │
  │  │  positions: [{inst, direction, contracts, risk_dollars, cluster,    │   │
  │  │               entry_day, exit_day, pnl_sized}]                      │   │
  │  │  breaker:   {peak_equity, day_start_equity, cur_day}                │   │
  │  └─────────────────────────────────────────────────────────────────────┘   │
  │                                                                             │
  │  Written:  _persist_state()  after EVERY run_day()   runner.py:295         │
  │            atomic: .tmp → os.replace                                        │
  │  Read:     FuturesRunner.__init__() on startup        runner.py:195         │
  │                                                                             │
  │  CYCLE:  EOD persist ──► restart ──► BOD load ──► run_day ──► EOD persist  │
  └─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  WITHIN-DAY (re-computed each day)                                          │
  │                                                                             │
  │  bars: {inst: DataFrame}                                                    │
  │  ── broker.fetch_bars(through=day) each day (causal slice)                  │
  │                                                                             │
  │  entry_candidates, exit_positions                                           │
  │  ── signal_fn(day, bars, held) each day                                     │
  │                                                                             │
  │  daily_atr_series(df) per instrument                                        │
  │  ── computed inside generate_today_signals() each call                      │
  │                                                                             │
  │  _SWING_CACHE  (_validated_core.py:197)                                     │
  │  ── keyed by id(df); populated during backtest_swing_tf()                   │
  │  ── CLEARED after signal generation:  _SWING_CACHE.clear()  [J2]            │
  │     runner.py:424 — prevents unbounded growth in long-running process       │
  └─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  IN-MEMORY ONLY — NOT persisted, reset on restart                           │
  │                                                                             │
  │  state.equity          ← reset to broker.get_equity()   ← CORRECT by design │
  │                         broker is source-of-truth; state.equity and         │
  │                         broker._equity both receive same pnl_sized delta    │
  │                         per run_day, staying in sync during session.        │
  │                         On restart: broker holds the real value.            │
  │                         peak_equity MUST persist separately (B1) because    │
  │                         broker only knows current equity, not historical    │
  │                         peak — that asymmetry is intentional.               │
  │  state.taken           ← reset to {cluster:0}                               │
  │  state.rejected        ← reset to {cluster:0}                               │
  │  state.halted          ← reset to 0                                         │
  │  _last_breaker_level   ← reset to "OK"                                      │
  │  _events (bounded 500) ← reset to []                                        │
  │  HMMStaleGuard flags   ← reset (regime_unreliable=False, etc.)              │
  └─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  ANNUAL / OPERATOR (HMM re-freeze)                                          │
  │                                                                             │
  │  futures_freeze_registry.json   (models/hmm/)                               │
  │  ── current: FreezeRecord  (version, fit_end, calmar, labels_hash, ...)     │
  │  ── history: last 3 records  (for rollback)                                 │
  │  Written: apply_freeze()  refreeze.py:453                                   │
  │  Read:    current_freeze() / rollback()                                     │
  │                                                                             │
  │  refreeze_pending.json  (models/hmm/)                                       │
  │  ── written when re-freeze fails; re-alerts on every subsequent attempt     │
  │  ── cleared when re-freeze succeeds                                         │
  │  refreeze.py:146                                                            │
  └─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  DASHBOARD SNAPSHOT (per-day)                                               │
  │                                                                             │
  │  live_state_data.js   (window.LIVE_DATA)                                    │
  │  ── written by dump_state(day)  after every run_day()   runner.py:704       │
  │  ── contains: equity, DD, breaker_level, open_positions, cluster_exposure   │
  │               operational_status, events, runner_health                     │
  │  ── atomic: .tmp → os.replace                                               │
  └─────────────────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────────────────┐
  │  PROCESS LIFETIME                                                           │
  │                                                                             │
  │  runner.pid   (E1 lockfile)                                                 │
  │  ── created: FuturesRunner.__init__()  runner.py:186                        │
  │  ── removed: atexit.register(_release_lock)  runner.py:187                  │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## SUMMARY: 3 CLUSTER PIPELINES (cùng runner, khác thời gian)

```
  ┌─────────────────────────────────────────────────────────────────────────────┐
  │                                                                             │
  │  Rổ 4 SWING TF  ─── STATE model ────────────────────────────────────────   │
  │  MES / MNQ / MYM / M2K          cluster: roska4_swing                      │
  │  Entry: 14:00-15:55 ET          Exit: chandelier stop (up to 5 days)       │
  │  Signal: desired_position → diff → entry if entry_day==today               │
  │  ATR mult: 2.5                  cap: gross≤5% net≤4.4%                     │
  │                                                                             │
  │  NKD (Nikkei micro) ──── STATE model ────────────────────────────────────   │
  │  MNKD                           cluster: global_nkd                        │
  │  Session: JST (Asia/Tokyo)      Exit: chandelier stop (up to 5 days)       │
  │  Signal: desired_position → diff → entry if entry_day==today               │
  │  Regime: SPY lag=1 (no lookahead) cap: gross≤2% net≤2%                    │
  │  ATR mult: 2.5  ema: 10                                                    │
  │                                                                             │
  │  STRESS_MID ──────────── EVENT model ─────────────────────────────────────  │
  │  Same instruments as Rổ4        cluster: roska4_stress                     │
  │  Entry: 10:15 ET (Stress regime only)  Exit: same day by 14:00             │
  │  Signal: entry_signal(bars_through_1015)                                   │
  │  Condition: close < VWAP AND close < open  → SHORT                        │
  │  ATR mult: 2.5  stop_dist≤1.5%  target 2R  cap: gross≤2.5%               │
  │                                                                             │
  │  CircuitBreaker — COMBINED across ALL 3 clusters                           │
  │  DD from peak ≥15% → HALT all; daily_loss ≥4% → HALT_DAY                  │
  │                                                                             │
  └─────────────────────────────────────────────────────────────────────────────┘
```
