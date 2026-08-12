# Dashboard module plan

This plan covers observation surfaces only. It must not place orders, write runner
state, or change trading behavior.

## Product boundaries

- Realtime Monitor answers: "Is anything broken now?"
- Historical Analytics answers: "How has the system performed?"
- Paper Evidence Ledger answers: "Is there enough paper evidence to judge?"
- Reports Archive answers: "What happened in a completed session?"

Realtime must not load replay data or any CDN asset. Historical is the only module
that loads `replay_snapshots_data.js`. Reports must never be called by Realtime,
including for its journal; the realtime journal uses runner `events[]` only.

## Realtime sources

Every source envelope is stamped by the monitor server clock:

```text
source
observed_at
server_now
age_seconds
expected_next_at
freshness: fresh | late | not_expected_yet | missing | unknown
payload
```

Schedule evidence is independent of freshness:

```text
state: executed | skipped | failed | not_observed | not_scheduled
reason: mutex | preflight | misfire | exception | none | unknown
severity: incident | watch | expected | none
slot_at
```

Rules:

- `failed` is an incident even while the last runner state is fresh.
- `skipped/mutex` is expected contention. It suppresses `late` and advances
  `expected_next_at` to the following state-producing slot.
- `skipped/preflight` and `skipped/misfire` are classified by the server; the UI
  does not infer severity.
- Without schedule evidence, an unexplained missing update is `unknown`, not
  `late`.
- `late` is allowed only after the expected slot plus its allowance and when no
  evidence explains the silence.
- Broker disconnect is `unknown`; runner state must not silently replace broker
  truth and render green.

## State-producing schedule

Only jobs that complete `run_day()` reach the single `dump_state()` call at the
end of `decide_day()`:

- 23 R4 slots: 14:05 ET plus 14:10-15:55 ET every five minutes.
- 22 NKD slots: 01:10-02:55 ET every five minutes.
- Total: 45 slots on a trading day.

MAX_HOLD and stop-repair jobs do not produce runner state and must not enter the
`expected_next_at` sequence. `TASK.md` still describes the old 19-slot stop-repair
schedule. Current `run_scheduler.py` creates 10 two-hour repair slots after
excluding 02:20 and 14:20; that historical number is not a realtime contract.

Trading days come from `raits.live.trading_calendar.is_trading_day`, not the cron
weekday expression. The 15:55 shadow-verify slot may take about 13 minutes and is
the last state-producing slot of its window.

## Read-only invariants

Tests must enforce all of these:

1. Monitor routes expose GET/HEAD only.
2. `monitor.backend` does not import `global_index.runner`.
3. The IBKR reader default remains client ID 99.
4. Monitor code contains no order placement or state-file write path.

Runner-state reads rely on atomic `.tmp -> os.replace` writes and cache parsed data
by file mtime. Session reports cache by `(date, relevant log mtimes)` and run only
when the Reports module requests them.

## Unresolved telemetry decisions

- Runner snapshots do not emit contract quantity for open positions. Realtime
  therefore labels broker/runner reconciliation as symbol/side only, keeps the
  rail at watch, and emits a size-reconcile telemetry gap. Decide separately
  whether a read-only persisted-position adapter should become another source;
  do not alter the runner from the monitor workstream.
- IBKR order data exposed by the monitor does not include OCA group metadata.
  Realtime verifies an individual stop's exact contract, opposite action,
  quantity, and live status, but does not classify multiple same-contract stops
  as duplicates because OCA alternatives cannot yet be distinguished safely.

- Calmar is displayed against a floor derived under a different measurement
  convention. See "Calmar convention" below. Labelled as a stopgap on
  2026-08-11; the structural fix belongs to the paper-trade dashboard work.

## Calmar convention

**Do not compare the replay curve's Calmar to the fit_A floor.** They are not
the same measurement. Fix this when the paper-trade dashboard is built.

`meta.backtest_calmar` (1.65) is the fit_A degradation floor from `deploy_sim`.
`snap.running_metrics.calmar` (1.6781 as of 2026-08-11) is the replay curve's
own Calmar. Seven constraints define the floor; the curve differs on four:

| | Floor 1.65 | Replay curve |
|---|---|---|
| Data | `frozen_sim` + `NKD_frozen_2024` | live `_8y` parquet |
| Window | `--end 2024-12-31` | through today |
| HMM fit | `--hmm-fit-end 2022-12-31` (fit_A) | 2024-12-31 (fit_C) |
| Stress cluster | excluded (no `--include-stress`) | included |
| Slippage | 2 ticks/side | 2 ticks/side — same |
| Size | `--n-contracts 1` | 1 — same |
| Formula | `metrics()` | `metrics()` — same |

The formula is already shared: `generate_replay_snapshots.py` imports `metrics`
from `deploy_sim`. The whole gap is in the inputs, not the arithmetic.

This stayed invisible while the numbers were 2.2993 vs 1.65. Fixing the regime
CSV on 2026-08-11 (`spy_daily.csv` -> `spy_daily_live.csv`, which restored Rổ 4
to the 2025-2026 curve and removed NKD's frozen-label inflation) moved the curve
to 1.6781, and the metric bar began reading as "about to break the floor". It is
a false alarm: the real degradation check, run the same day, reproduced
INVARIANTS exactly at baseline $42,459 / Calmar 1.72 versus floor 1.65.

**Stopgap already applied (2026-08-11), labels only:** the metric bar sub-label
reads `floor 1.65 · quy ước khác` with a `CALMAR_NOTE` tooltip on both the value
and the sub-label; the degradation panel reads `Backtest Calmar (floor fit_A —
frozen, no-stress)` and `Paper Calmar (live, ít ngày)`; `dash/analytics/` shows
`Floor fit_A` instead of `IS Baseline`. Files: `global_index/dashboard.html`,
`global_index/dash/analytics/{index.html,analytics.js}`.

**Decision for the paper-trade dashboard — pair the floor with paper, not with
the curve.** The floor exists to track degradation of the *live* system, so its
counterpart is `paper_calmar` (`metrics()` over real paper-day P&L), which the
degradation panel already pairs correctly. The replay curve's Calmar is a
property of the backtest and cannot degrade with live; it belongs in its own
tile, never beside the floor. Concretely: drop `floor` from the metric bar and
let it live only in the degradation panel next to `paper_calmar`.

Cost of that choice, accepted: `paper_calmar` needs enough paper days and will
render `N/A` for a while (`meta.system_epoch` = 2026-08-10). An honest `N/A`
beats a number compared against the wrong reference. This matches the existing
rule in this document that evidence gaps never render as inferred pass/fail.

Two alternatives considered and rejected:

- *Bring the curve to the floor's convention* — emit a second frozen /
  end-2024 / no-stress curve. Rejected: that number is frozen history, it never
  moves, and it only re-derives 1.72. A reproducibility check, not monitoring.
- *Bring the floor to the curve's convention* — re-derive the floor on full data
  with stress. Rejected for now: it changes a pinned INVARIANT, and
  `docs/futures/INVARIANTS.md` states every Calmar must be compared on one
  convention. It also reopens which fit counts as fit_A in that frame and
  whether stress belongs in a floor at all — a measurement decision, not a
  display one.

Colour thresholds in the metric bar (`>=2.0` go, `>=1.0` warn) are generic and
unrelated to the floor. Revisit them with this section, not separately.

## Existing prototypes

The original untracked `global_index/dash/` prototype was preserved unchanged in
commit `fbfefb4`. Reuse the terminal density, phone responsive ideas, and shared
visual language. Do not reuse the one-shot data architecture. Keep one owner for
shared CSS, API contracts, navigation, and compatibility routing.

## Visual direction

Keep the current dark terminal style, compact status rails, severity colors, and
position-card hierarchy. Use a local-first font stack:

```css
font-family: "Cascadia Mono", "JetBrains Mono", Consolas, monospace;
```

Realtime has no chart dependency. Historical draws its chart with the browser
Canvas API and has no CDN or external runtime dependency.

## Paper evidence contract

- Duration uses the conservative end of the documented 30-60 day minimum: 60
  distinct runner snapshot dates at or after `meta.system_epoch`.
- Regime coverage requires both Normal and Stress.
- "Several" observations per exit path is recorded as 3 for Chandelier,
  MAX_HOLD, and STP-triggered exits.
- C1 signed slippage uses the runner convention: positive is adverse. OPEN and
  CLOSE means remain separate because the runner tracks them separately and
  `PAPER_ROUTE.md` does not define whether they share a gate. It also does not
  define a sufficient sample count. Until both decisions are made, the gate
  stays pending even when an observed mean is above or below 2 ticks.
- TWS restart nights also lack a numeric threshold. B3 mismatch and STP false
  halt lack structured runner-state evidence. All three render as evidence gaps,
  never inferred pass/fail states.

## Delivery status

1. Complete - preserve the prototype baseline in commit `fbfefb4`.
2. Complete - serve modules from Flask with versioned read-only endpoints.
3. Complete - implement freshness and independent schedule evidence.
4. Complete - connect Realtime to runner state and read-only IBKR adapters.
5. Complete - pass backend/dashboard tests and desktop/mobile browser checks.
6. Complete - isolate replay to Historical and remove fallback Calmar values.
7. Complete - build Paper Evidence Ledger with explicit unresolved thresholds.
8. Complete - cache and trim Reports responses; compatibility `/dashboard`
   redirects to Realtime while the legacy file remains preserved.

## Verification notes

- The focused monitor/dashboard suite passes 22 tests, including read-only route
  invariants, schedule freshness, stop-state rendering, and live snapshots.
- Desktop and mobile browser checks pass without horizontal overflow. Realtime
  was also verified against a read-only IBKR connection: one M2KU6 position and
  stop order 288 reconciled 1/1 with runner intent and produced no incident.
- A browser failure injection blocked only `/api/v1/broker` after a fresh poll.
  Broker, protection, and reconcile moved to unknown; the last broker KPIs were
  dimmed, positions were removed from operational conclusions, and one telemetry
  gap appeared with no false incident. The next successful poll recovered all
  states automatically.
- Broker-response injections changed the live M2K stop to wrong-side BUY,
  wrong-size SELL x2, and PendingCancel. Each case produced one deduplicated
  Invalid Stop incident with the expected SELL x1/live-status evidence; the real
  SELL x1 PreSubmitted stop remained 1/1 valid.
- Reports groups the 22 NKD, 23 Live Day, and due stop-repair slots into three
  expandable family rows. Clean families stay collapsed; any family with a
  missing slot opens automatically. Individual jobs such as preflight and
  MAX_HOLD remain visible without drilling down.
- Network interception verified explicit source failures: missing replay shows a
  Historical error banner, missing runner evidence makes Paper UNKNOWN, and a
  failed report request makes Reports UNKNOWN rather than claiming no log data.
- `test_event_playback.py` is not a practical single-shot gate: Part 2h invokes
  `runner.run_day()` 1,381 times and the full script did not finish in 15 minutes.
  Focused Part 4 baseline checks pass 3/3. Part 3 passes 11/14; its remaining
  breaker assertions reproduce in Part 2a before dashboard rendering because the
  old fixture now yields breaker OK/drawdown 0 rather than HALT/15%. This monitor
  session does not change the engine or that engine-facing fixture.
