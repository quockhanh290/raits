# Stage 5ZI — the pre-paper error-proofing map

**2026-08-25, ET 22:00–23:10.** Audit and map only — **no code implemented**, no read-only
helper needed. No orders · no confirmation file · `TRACK1_ORDERS_APPROVED` unset · no
`--allow-orders` · **nothing restarted** · **no IBKR call** · **no runtime evidence written or
edited** · no strategy change · no paper-gate change.

```text
UTC 2026-08-26 02:20 · ET 2026-08-25 22:20 EDT · Calgary 20:20 MDT · Tokyo 11:20 JST (26th)
```

---

## Verdicts

| | |
|---|---|
| next shadow window | **READY** — nothing on this map blocks it except the machine sleeping |
| paper | **NOT_READY** — six machine gates open, one of them an operator decision |
| any runtime / live file touched | **no** |
| top three next stages | **5ZJ** (make 5ZG live) → **5ZK** (checkpoint frames) → **5ZL** (regime tri-state) |

Requires paper broker evidence and **cannot** be finished in shadow: broker stop placement and
its reconcile, partial fills, the SUBMITTED→outcome restart path, Flex statement reconcile, and
position attribution under a shared account.

---

## 1. Current operational state

Read-only. `ops.py status` reads a cached connection record; no broker call was made.

```text
scheduler pid 48604   started 01:07 ET, holding this morning's code
backend   pid 7872    port 5002
track1_mode           track1-only-shadow
blocking              B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
orders_possible       False
```

| artefact | state |
|---|---|
| `live_positions.track1.json` | **exists**, 13:56:19, 284 B — schema 2, route `track1_candidate`, window `live`, cut `2026-08-25T15:55:01-04:00`, **zero positions**, equity 0 |
| `replay_checkpoint.track1.json` | **exists**, 13:56:19, 315 B — schema 2, one route, four sleeves, **zero instrument entries** |
| `global_index/track1_runtime/orders/` | **absent** — no order has ever been journalled |
| `global_index/track1_runtime/trade_log.track1.jsonl` | **absent** — 5ZG's destination, not yet created |
| `track1_go_live_confirmation.json` | absent |
| `runner.track1.pid`, `STOP_TRADING.track1` | absent |
| `global_index/maxhold_state.track1.json` | 2026-08-24 — **the 09:31 job did not run on the 25th** |

### Windows judged, and why they failed

Only two days of evidence exist. The audit **records on disk** say:

| day | calm | stress | swing | nkd |
|---|---|---|---|---|
| 2026-08-24 | FAIL | FAIL | FAIL | NOT_ENOUGH_DATA_YET |
| 2026-08-25 | FAIL | FAIL | **FAIL** | FAIL |

Re-evaluated now, after 5ZH, 2026-08-25 Swing is **PASS** — 23 of 23 slots, all decided, no
candidates, p95 78.5 s, checkpoint ok. **The record still says FAIL**, because the audit ran at
20:15 UTC before the fix and the gate reads records, not fresh evaluations. Re-running that
day's audit is an operator action and would write runtime evidence; this stage did not.

The other three failed for one cause and one only, and it is not code:

```text
2026-08-25 09:11:35 Calgary — the scheduler woke and reported
  "Stop repair sweep 08:20 ET"      missed by 2:51:35
  "MAX_HOLD exit 09:31 ET"          missed by 1:40:35
  "Track 1 MAX_HOLD exit 09:31 ET"  missed by 1:40:35
  "Track1 roska4_calm 10:00 ET"     missed by 1:11:35
  ... 16 missed-job warnings in one burst
```

The machine slept. Calm has exactly one slot and it was inside the sleep, so the sleeve is
unobserved. Stress lost 1035–1105, seven of twenty-four. NKD's slots ran but were refused for
stale data — a different cause, and the one genuine data problem of the day.

### Paper blockers, measured

```text
judgeable_days                    2 of 5 required
no_failing_days                   2 FAIL days, 0 allowed
warn_days_within_allowance        ok
evidence_is_recent                ok (0 days old)
every_sleeve_passed_at_least_once passed: []   <- reads records; nothing has passed on record
```

---

## 2. Route-aware safety reporting — closed in code, **not live**

5ZG closed the blocker: the Track 1 trade log is
`global_index/track1_runtime/trade_log.track1.jsonl`, rows tagged `route=track1_candidate`,
both entry points accept `--trade-log-path` and `--route`, legacy default unchanged.

**The running scheduler still calls them the old way**, and the live log proves it rather than
implying it:

```text
2026-08-25 18:20:00 [TRACK1_STOP_REPAIR_2020] python -m global_index.run_stop_repair
   --positions-path live_positions.track1.json --stop-path STOP_TRADING.track1
   --lock-path runner.track1.pid --client-id 90 --port 4002
```

No `--trade-log-path`. No `--route`. The argv is built inside pid 48604, which started at
01:07 and predates the change.

**A second thing changed today and the same log measures it.** The Track 1 book file appeared
at 13:56, so the safety jobs stopped taking their early return:

| sweep | book present? | duration |
|---|---|---|
| 02:20, 04:20 Calgary | no | **1 s** |
| 14:20, 16:20, 18:20 Calgary | yes | **13 s** |

They now acquire the lock and connect to IB Gateway on every sweep, thirteen times a day, on
client id 90, against a book holding nothing. Not a defect — it is the safety net doing its
job the moment there is a book to watch — but it is new load that began today.

### Remaining work

| item | blocks shadow | blocks paper | blocks live |
|---|---|---|---|
| operator restarts the scheduler so 5ZG's argv goes live | no | **yes** | yes |
| after restart, verify the argv carries both flags | no | **yes** | yes |
| verify the empty log file is created and stays empty on a no-op sweep | no | **yes** | yes |
| verify no legacy-log write during a Track 1 no-op sweep | no | **yes** | yes |
| verify a real safety close lands in the Track 1 log, tagged | no | no | **yes** |

Files: `run_scheduler.py`, `run_stop_repair.py`, `run_maxhold_exit.py`, `safety_trade_log.py`.
Minimum fix shape: **none in code** — an operator restart plus a post-restart verification that
reads the live argv out of the scheduler log and asserts both flags. The last row needs a real
Track 1 fill and therefore paper evidence. Stage **5ZJ**.

---

## 3. Order execution lifecycle

Built, tested, and **wired to nothing**.

| piece | file | state |
|---|---|---|
| state machine | `track1_order_state.py` | INTENDED · SUBMITTED · FILLED · PARTIAL · REJECTED · UNKNOWN; `transition_allowed`, `is_amendment`, `resolve_journal` |
| journal writer | `track1_order_journal.py` | fail-closed — a write that did not land stops the order |
| executor | `track1_paper_executor.py` | `open_position` only |
| order builder | `track1_paper_order.py` | `candidate_to_order`, `assert_admitted`, micro/full symbol guard |
| broker read side | `track1_broker_read.py` | `Answer(KNOWN/UNKNOWN)`, `resolve_submitted`, `exit_allowed`, `entries_allowed` |
| call site | `track1_paper_callsite.py` | dry-run design + `RefusingBroker`; **no production call** |
| the live route | `run_live_day_track1.py` | broker is `NoOrderBroker`, which raises on `send_order` |

**Three of the four lifecycle verbs do not exist on the real executor.** Measured against the
protocol: missing `close_position`, `place_protective_stop`, `switch_same_symbol`. The
call-site coverage table already says what happens to each of them today, and it is worth
quoting because it is the actual gap:

- `place_protective_stop` — done by the safety job inside `FuturesRunner.__init__`; **no journal row**
- `close_position (max hold)` — done by the safety job; writes the trade log, not the journal
- `close_position (strategy exit)` — **nobody**; the sleeves' own exits have no path to a broker
- `switch_same_symbol` — `track1_switch` is imported by nothing; it calls `send_order` twice with no journal

`NoOrderBroker` still blocks the accidental path: `send_order`, `cancel_order` and `get_equity`
all raise.

| question | unit-testable today | needs paper evidence |
|---|---|---|
| INTENDED before anything, SUBMITTED before send | **yes** — done | no |
| journal write failure stops the order | **yes** — done | no |
| unrecognised broker status → UNKNOWN | **yes** — done | no |
| order id arrives on a receipt mid-flight | **yes** — done | confirm shape against real IBKR |
| restart between SUBMITTED and outcome | **partly** — `resolve_submitted` is tested against fakes | **yes** — a real orphan |
| partial fill | classification only | **yes** — a real partial |
| disconnect / timeout mid-send | **yes** with fakes | **yes** — real behaviour |

Blocks shadow: **no**. Blocks paper: **yes**. Stage **5ZN**.

---

## 4. Stop lifecycle — the widest gap on the map

The strategy computes a stop (`stop`, `stop0` on the signal). From there it goes nowhere near
the order path:

- `Order` has **no stop field**. Measured: `inst, action, direction, contracts, cluster,
  ref_day, exit_day, pnl_sized, contract_month`.
- `OrderRecord` has **no stop field**. Measured: `trade_id, sleeve, instrument,
  tradable_symbol, direction, qty, state, ref_day, idempotency_key, broker_order_id,
  filled_qty, avg_price, detail`.
- The stop is placed by **B4 inside `FuturesRunner.__init__`**, reached through the safety
  sweep — a different process, on a different schedule, with no journal row.

So the planned stop and the placed stop are never written down in the same place, and **there
is nothing to reconcile a broker working-stop against**. Everything downstream inherits that:
side, quantity, price, bracket/OCO behaviour, orphan detection.

Orphan stops are not hypothetical here. The project's own record: a max-hold close on
2026-08-10 left an orphaned STP on MYM #12, and an orphaned STP that fills **opens a position
in the opposite direction**. That is why the client id must be shared, and it is why a stop
with no journal row is a real accounting hole rather than a tidiness complaint.

| item | shadow | paper | live |
|---|---|---|---|
| journal the planned stop with the entry | no | **yes** | yes |
| planned vs placed comparison | no | **yes** | yes |
| broker working-stop reconcile | no | no | **yes** |
| orphan STP detection for the route | no | no | **yes** |
| stop-repair route awareness | **already route-scoped** (5O: own book, switch, lock, id 90) | — | — |
| max-hold route awareness | **already route-scoped**, own marker | — | — |

Unit-testable: carrying the stop through `candidate_to_order` into the journal, and the
planned-vs-placed comparison against a fake broker. Needs paper: that IBKR actually holds the
stop at the price and quantity asked, and that cancel-on-close works from client id 90.

Stage **5ZN** (journalling the stop) and a later live stage for the reconcile.

---

## 5. Position reconcile

`track1_order_state.reconcile` is built and gives three answers. Entries blocked on MISMATCH
**and** UNKNOWN; exits allowed in all three, because refusing to reduce exposure while the book
is confused is the wrong failure direction. `reconcile_at_startup` on the executor takes the
broker positions as an argument rather than fetching them, so it stays testable without a
socket.

Wired into the live path: **no**, because the executor is not wired.

**The B1 problem is modelled honestly, and that is what makes it a blocker.** With one login
serving both routes the strongest available statement is

```text
broker_net(contract) == track1_net(contract) + legacy_net(contract)
```

which **detects** disagreement and cannot **attribute** it. Equal-and-opposite errors — legacy
long one, Track 1 short one — cancel in the broker's net and read as agreement. A dedicated
account, or a proven-flat legacy book, makes the comparison exact.

Restart cases: book written and no fill; fill and no book write; fill, book write, crash before
journal. The journal is written before the broker call precisely so the third is recoverable,
and `resolve_submitted` asks working orders first, executions second, positions last and never
alone.

| item | shadow | paper | live |
|---|---|---|---|
| three-answer reconcile exists and is tested | done | — | — |
| wire it to the live start-up path | no | **yes** | yes |
| B1: separate account or proven-flat legacy | no | **yes — operator decision** | yes |
| attribution under a shared account | no | **cannot be proved** | — |

---

## 6. Route-aware P&L / Flex / report

The corruption risk is closed in code by 5ZG and goes live with the scheduler restart. What
remains **omits** rather than corrupts. Re-verified by AST today, not carried over:

| module | knows Track 1 | reads |
|---|---|---|
| `global_index/session_report.py` | **no** | `live_positions.json` |
| `monitor/flex_pull.py` | **no** | neither route by name |
| `monitor/paper_pnl_compare.py` | **no** | `live_positions.json`, `trade_log.jsonl` |

Five pieces missing:

1. Track 1 order journal → a P&L reader
2. `live_positions.track1.json` → open-position parity
3. Track 1 fills → Flex statement reconcile — **needs a real statement**
4. route-aware session report, or a separate Track 1 report
5. prevention of Track 1 rows folding into legacy reporting readers (`paper_evidence_reader`
   aggregates the whole trade log and splits on nothing)

**Does this block paper orders?** Being conservative: **items 1, 2 and 5 do.** Not because an
order cannot be sent without them, but because an order sent without them cannot be *accounted
for* — a paper probe whose fills nobody can reconcile produces no evidence, and evidence is the
entire purpose of the paper stage. Items 3 and 4 block paper **evaluation** rather than paper
orders, and 3 cannot be finished before a statement exists to reconcile against.

Stage **5ZM**.

---

## 7. Regime verification

Labels are never persisted — recomputed on every read — so both SPY refreshes are sufficient
for data availability **by construction**, and the 13:45 / 16:20 pair was verified in 5ZF.

The verification itself is weaker than 5ZF recorded, and the correction matters. It is not that
every path returns 0 — the drift path returns `n_diff`. It is that:

- three "could not verify" paths (`cannot import`, `could not load CSVs`, `label_regimes
  failed`) return **0**, which is the same value as "verified, no drift";
- and the single call site, `update_spy_csv.py:300`, is a bare call that **discards the return
  value entirely**.

So even a fifty-label drift changes nothing: it logs a WARNING, returns a number nobody reads,
and the job exits 0. The scheduler keeps only CRITICAL/ERROR from a child that exited 0, so the
warning does not survive to the journal either. A label drift is currently **invisible end to
end**.

Required behaviour before paper: three outcomes — PASS / DRIFT / UNKNOWN — with UNKNOWN failing
closed, and the result reaching the job's exit status so it becomes a child failure the journal
and the dashboard can show. Never green a verification that could not run.

Files: `global_index/update_spy_csv.py`, plus whatever job wrapper surfaces the child failure.
Unit-testable in full; no broker evidence needed. Blocks shadow: **no**. Blocks paper: **yes**.
Stage **5ZL**.

---

## 8. Signal rule-detail exposure

Measured across the whole signals journal — 32 rows, all `NO_SIGNAL`, 23 Swing and 9 Stress:

| rule-check source | count | share |
|---|---:|---:|
| `measured` | 64 | 19.8 % |
| `not_reached` | 50 | 15.4 % |
| **`not_exposed_by_sleeve`** | **210** | **64.8 %** |

Fourteen distinct rules are unexposed: Swing's `ema50_filter`, `r4_prior_range_filter`,
`entry_bar_volume_filter`, `spy_d1_close_below_sma50_short_filter`, `fixed_stop_2x_daily_atr`,
`stop_arm_rule`; Stress's `no_regime_label_required`, `breadth_down_count`, `gapdown_count`,
`avg_gap`, `mnq_only_short_setup`, `pre_high_stop_reference`, `stop_within_max_pct`,
`rr_target_computed`.

Two thirds of what an operator would want to know is recorded as *"the rule ran inside the
detector and the detector does not return its value"*. That is the honest label and it is the
right one — the alternative, having the dashboard recompute the rule, would put a second
implementation of the strategy beside the one that trades, and "not measured" and "measured and
fine" would stop being distinguishable.

The fix is in the detectors: return the measured values, and re-run artifact reproduction
afterwards to prove the returns changed nothing about the decisions.

**Does not block shadow plumbing or paper plumbing.** It blocks explainability and operator
confidence: on a day the route declines to trade, nobody can say which rule declined. Low
priority against the accounting gaps, high priority against the day someone asks *why not*.

---

## 9. Operational resilience

| item | state |
|---|---|
| Windows sleep | **the dominant live problem.** 16 missed-job warnings in one burst on the 25th; three of four sleeves failed because of it |
| scheduler heartbeat | present — 60 s beat, 30 s tolerance, hourly throttle, STALLED marker, journal reader marks recovery |
| missed-slot alert | present — `unexplained_overdue` names the slots; measured naming `TRACK1_CALM_1000` and `TRACK1_STRESS_1035` |
| dashboard stale-runner label | **fixed in 5ZF** — not live until backend restart |
| `SPY_REFRESH_PM` failure visibility | **fixed in 5ZF** — not live until backend restart |
| backend reload | `use_reloader=False` — a source change needs a restart |
| `ops.py` process discovery | **checked, and it is not the defect it looks like** — see below |

### The process-scan tri-state, checked rather than assumed

`ProcessScan` carries `ok`, and `scheduler_processes()` **discards it**, returning only the
list. `start_scheduler` then does `existing = scheduler_processes(); if existing: return None`
— which on a failed probe reads as "nothing is running" and would launch a second scheduler.

That is the shape of a live fail-open, and it is **not reachable**. Both CLI paths guard it
first: `restart --scheduler` goes through `ensure_single`, whose decision refuses on
`scan.ok == False`; `up` checks `scan.ok` inline and prints REFUSING. The inner guard is a
redundant second check that happens to be the weaker one.

So: **not a live defect.** It is a trap for the next caller — the first person to call
`start_scheduler` from anywhere else inherits the fail-open. Low-priority hygiene: make
`scheduler_processes` carry the third answer, or delete the inner guard so there is one place
that decides. Recorded because a latent fail-open on the duplicate-scheduler guard is exactly
the class that already cost six entry slots.

### Operator actions pending

1. **Fix the sleep.** A power setting, not code. It is currently the largest single cause of
   failed windows and it blocks the evidence gate more effectively than anything on this map.
2. **Restart the backend** — picks up 5ZE, 5ZF and 5ZH's dashboard fixes:
   `python monitor\ops.py restart --no-scheduler --track1-only-shadow`
3. **Restart the scheduler** — picks up 5ZG's safety argv. Higher risk; do it outside a window.

---

## 10. Checkpoint / restart semantics

After 5ZH the reader is correct, the quiet-window contract is Option C (checkpoint plus
companion book, both from one call), and the 2026-08-25 Swing window passes when re-evaluated.

**The named blocker stands: the checkpoint cannot resume anything.** The single production call
site passes no `frames`, so `checkpoint_entries` skips every instrument and the entry map is
empty *whatever the day did*. A day holding an open Swing position would write the same empty
file. `get_entry` returns `{}`, `usable` refuses with `no_entry`, and every run replays in full.

What it should contain for an open cross-day position, per `make_entry`: route, sleeve,
`last_day`, the frame fingerprint, the readable params and their hash, the data source, and the
engine-shaped position (direction, entry, stop, entry day). Five instruments need frames — MES,
MNQ, MYM, M2K for Swing; MNKD for NKD.

### The performance budget, measured

| sleeve | n | p50 | p95 | max | headroom to the 300 s ceiling |
|---|---:|---:|---:|---:|---:|
| `global_nkd` | 22 | 2.5 s | 2.7 s | 3.0 s | 297.0 s |
| `roska4_stress` | 36 | 3.2 s | 19.7 s | 20.8 s | 279.2 s |
| `roska4_swing` | 46 | 39.8 s | **78.5 s** | 78.9 s | **221.1 s** |

The checkpoint is written only at window close, so the cost lands on **one** slot per sleeve,
and Swing — the expensive one — still has 221 s of headroom against the ceiling and 161 s
against the 240 s target. The frames are already loaded during the window; the open question is
whether the closing slot can reuse them or must reload. **That cost is not measured and must
not be assumed** — it is the first thing 5ZK should measure, before deciding whether to reuse
in-memory frames or reload.

| item | testable without a fill | needs an open position |
|---|---|---|
| entries are written when frames are supplied | **yes** | no |
| `usable` accepts a same-day entry and refuses a drifted one | **yes** — already tested | no |
| the close-time cost stays inside the budget | **yes** — measure it | no |
| a resume actually rebuilds the right book | no | **yes** |
| restart mid-window with a position open | no | **yes** |

Stage **5ZK**.

---

## 11. Paper readiness gate

Machine gates open, measured today:

| gate | state |
|---|---|
| `PAPER_SHADOW_EVIDENCE` | 2 of 5 judgeable days; 2 FAIL days against 0 allowed; no sleeve has PASSED **on record** |
| `B1_broker_account_or_legacy_retirement` | open — operator decision, cannot be closed by code |
| order path | not enabled; `NoOrderBroker` raises; no confirmation file; no orders directory |

Additions this map argues for, before a confirmation file is written:

1. 5ZG's safety argv **live and verified after restart** (§2)
2. route-aware P&L and open-position parity present, or **explicitly waived in writing** for a
   deliberately tiny probe — a waiver is acceptable, silence is not (§6)
3. regime verification no longer warn-only, UNKNOWN failing closed (§7)
4. checkpoint resume semantics resolved, or an explicit statement that Track 1 replays in full
   every day and that this is accepted (§10)
5. the entry's planned stop journalled, so a placed stop has something to be compared against (§4)
6. broker/account state verified under whichever B1 answer is chosen

No confirmation file until every machine gate above passes. B1 is a decision and comes first in
time, because §5 shows a shared account cannot attribute a mismatch to a route — which is the
one thing paper evidence is supposed to establish.

---

## 12. Recommended stage order

The suggested order is kept, with one dependency correction argued below.

| # | stage | goal | blocks paper | needs broker |
|---|---|---|---|---|
| 1 | **5ZJ** — make 5ZG live | operator restarts the scheduler; verify the live argv carries `--trade-log-path` and `--route`; verify the empty log appears and no legacy write happens on a no-op sweep | yes | no |
| 2 | **5ZK** — checkpoint frames | measure the close-time cost first, then supply frames so entries are real; prove `usable` accepts them | yes | no |
| 3 | **5ZL** — regime verification tri-state | PASS / DRIFT / UNKNOWN, UNKNOWN fails closed, result reaches the exit status and the journal | yes | no |
| 4 | **5ZM** — route-aware P&L / parity / report | journal → P&L, book → open-position parity, keep Track 1 rows out of legacy readers; Flex left for when a statement exists | yes (1, 2, 5) | partly |
| 5 | **5ZN** — paper execution call site | journal the planned stop with the entry; build `close_position` and `place_protective_stop` on the executor; wire the dry run; **still no orders** | yes | no |
| 6 | 5ZO — stop lifecycle reconcile | planned vs placed, working-stop reconcile, orphan STP detection | — | **yes** |
| 7 | 5ZP — sleeve rule exposure | detectors return measured values; re-run artifact reproduction | no | no |

**Why 5ZJ first rather than the bigger items.** It is the only one already finished in code, it
needs a restart that must happen anyway, and until it lands the route has a known-wrong
reporting destination in the running system. It also costs an operator minute, not a stage.

**Why 5ZK before 5ZL.** Both are cheap. 5ZK has a measurement gate in front of it — the
close-time frame cost — and if that cost turns out to be large the stage changes shape, so it
should be started early rather than late.

**The dependency correction.** 5ZM depends on 5ZN more than the suggested order implies: a P&L
reader over the order journal is reading a journal that, today, no production code writes. 5ZM
can be built against the journal's shape and tested with fixtures, but it cannot be *validated*
until something writes real rows. Either accept that 5ZM ships tested-but-unexercised, or run
5ZN's dry run first so there is a journal to read. **Recommended: keep 5ZM at 4, and have it
consume the dry run's journal output rather than waiting for real orders.**

**Not on the critical path, and say so plainly:** §8 (rule exposure) and the `ops.py`
process-scan hygiene in §9. Neither blocks anything. Both are worth doing before someone has to
ask *why did it not trade* or writes a second caller for `start_scheduler`.

---

## Appendix — the ranked map in one table

| # | item | shadow | paper | live | stage |
|---|---|---|---|---|---|
| 1 | machine sleep | **yes** | yes | yes | operator |
| 2 | B1 account decision | no | **yes** | yes | operator |
| 3 | 5ZG argv not live | no | **yes** | yes | 5ZJ |
| 4 | checkpoint cannot resume | no | **yes** | yes | 5ZK |
| 5 | regime verification warn-only | no | **yes** | yes | 5ZL |
| 6 | order journal → P&L | no | **yes** | yes | 5ZM |
| 7 | book → open-position parity | no | **yes** | yes | 5ZM |
| 8 | Track 1 rows folding into legacy readers | no | **yes** | yes | 5ZM |
| 9 | planned stop not journalled | no | **yes** | yes | 5ZN |
| 10 | `close_position` / `place_protective_stop` unbuilt | no | **yes** | yes | 5ZN |
| 11 | executor unwired | no | **yes** | yes | 5ZN |
| 12 | evidence: 0 clean days | no | **yes** | yes | time + item 1 |
| 13 | Flex reconcile | no | evaluation only | yes | 5ZM/later |
| 14 | route-aware session report | no | evaluation only | yes | 5ZM |
| 15 | broker working-stop reconcile | no | no | **yes** | 5ZO |
| 16 | orphan STP detection | no | no | **yes** | 5ZO |
| 17 | partial fill handling | no | no | **yes** | 5ZO |
| 18 | shared-account attribution | no | **unprovable** | yes | B1 |
| 19 | sleeve rule exposure (65 % unexposed) | no | no | no | 5ZP |
| 20 | `scheduler_processes` drops the third answer | no | no | no | hygiene |
