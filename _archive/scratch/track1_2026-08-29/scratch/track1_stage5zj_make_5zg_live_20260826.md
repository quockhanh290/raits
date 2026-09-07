# Stage 5ZJ — 5ZG is live, and the first Track 1 sweep proved it

**2026-08-26, ET 00:01–00:25.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · no strategy, rule, cap or backtest-identity change · no manual
edit to any book, checkpoint or audit record.

```text
UTC 2026-08-26 04:21 · ET 2026-08-26 00:21 EDT · Calgary 2026-08-25 22:21 MDT · Tokyo 13:21 JST
```

**Restarted, deliberately and with evidence: the scheduler and the backend.** One runtime file
was created as a direct and intended consequence, named in full below.

---

## The nine answers

| | |
|---|---|
| 1. scheduler restarted? | **yes** — pid **48604 → 18096** |
| 2. backend restarted? | **yes** — pid **7872 → 30604** |
| 3. is 5ZG live? | **yes** — proven by the live argv of a real sweep, quoted below |
| 4. did Track 1 safety route to `trade_log.track1.jsonl`? | **the destination is proven; a close row is not** — the file was created by the writability probe and is 0 bytes, because there is nothing to close |
| 5. legacy safety unchanged? | **yes** — same-second argv comparison, and its log untouched |
| 6. runtime/live data changed? | **exactly one file**, created empty: `global_index/track1_runtime/trade_log.track1.jsonl` |
| 7. orders still impossible? | **yes** — `orders_possible=False`, both blockers present, no confirmation file, no orders directory |
| 8. what remains before paper? | six items, unchanged from 5ZI minus this one |
| 9. next stage? | **5ZK — checkpoint frames**, and the reason is below |

---

## Part A — what was true before anything was touched

```text
scheduler pid 48604   started 2026-08-24 23:07:22 Calgary  (= 2026-08-25 01:07 ET)
backend   pid  7872   started 2026-08-25 18:36:28 Calgary
track1_mode           track1-only-shadow
orders_possible       False
blocking              B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
```

Inventory from source, constructed read-only: **101** jobs — 70 Track 1 strategy, 11 Track 1
safety, 5 Track 1 audit, 4 shared infra including `spy_refresh_pm`, 11 legacy drain safety,
0 legacy strategy.

**The live argv was stale, and the log says so rather than an inference.** The most recent
Track 1 safety launch before the restart:

```text
2026-08-25 20:20:00 [TRACK1_STOP_REPAIR_2220]
  -m global_index.run_stop_repair --positions-path live_positions.track1.json
     --stop-path STOP_TRADING.track1 --lock-path runner.track1.pid --client-id 90 --port 4002
```

No `--trade-log-path`. No `--route`. The scheduler holding that argv started fourteen hours
before 5ZG was written.

Artefacts: `trade_log.track1.jsonl` **absent**; legacy `trade_log.jsonl` 8486 B, mtime
2026-08-15; `live_positions.track1.json` present, 284 B, zero positions;
`track1_runtime/orders/` absent.

**The backend was half-current, and that too was measured rather than assumed.** It started at
18:36, after 5ZF and before 5ZH, so `/api/v1/schedule-status` already carried 5ZF's
`legacy_runner` block and `route_mode: track1_only_shadow` — while the checkpoint summary still
read `route: null` with no `routes` key, which is 5ZH's defect exactly.

---

## Part B — the restart, and its timing

Restarted at **ET 00:03**, chosen rather than taken: no window open, no `run_live_day` child
running (runner scan `ok=True, pids=[]`), seventeen minutes to the next scheduled sweep and
sixty-seven to the NKD window. The widest gap the night offered.

```text
python monitor\ops.py restart --scheduler --track1-only-shadow --yes
```

`--yes` was added to the command as briefed. This shell is non-interactive, and without it
`ensure_single` puts a confirmation prompt in front of the restart that would read EOF. It is
the flag's documented purpose — *"for unattended runs"* — not a widening of the action.

```text
scheduler: stopped [48604]      scheduler=started pid 18096
backend:   stopped [7872]       backend=started pid 30604
```

### The second restart was not run, and here is why

`restart --scheduler` restarts the backend as well — the transcript above shows it. The new
backend started at 22:03:41 Calgary, after every source edit in this sequence, the latest being
5ZH's at 19:44. Running `restart --no-scheduler` afterwards would have replaced a
seconds-old process with an identical one.

Verified rather than reasoned, against the live API:

| fix | marker | before | after |
|---|---|---|---|
| 5ZH | checkpoint summary | `route: null`, no `routes` | `route: "track1_candidate"`, `routes: ["track1_candidate"]`, `entry_count: 0` |
| 5ZF | schedule status | `legacy_runner`, `route_mode` present | still present |
| 5ZD | job row | — | `signal` chip present |
| 5ZE | job row | — | `operational` block present |

A second restart would have churned a live system to prove nothing.

---

## Part C — verification after the restart

**Mode and identity.** `track1_mode=track1-only-shadow`; the new process's own argv is
`-m global_index.run_scheduler --port 4002 --shadow-resume --track1-only-shadow`, i.e.
`--shadow-resume` survived the restart.

**Inventory, from the new process's own log rather than from source:**

```text
[track1-only] 45 legacy strategy jobs not scheduled; 85 jobs remain
[track1-only] 11 Track 1 safety jobs registered against live_positions.track1.json
[track1-only] 5 Track 1 audit jobs registered (read-only, no broker)
Track 1 SHADOW slots registered: 70 (no orders — the route's gate refuses)
```

Counted independently from the same log: 146 jobs added, 45 removed, **net 101** — matching the
pre-restart source construction exactly. `spy_refresh_pm` present. Legacy drain safety still
scheduled, and the scheduler's own session-report line names `stop_repair_2220` as the last job
of the day, which is one of them.

**Argv, from the code the new process loaded.** All eleven Track 1 safety jobs, identical:

| flag | Track 1 | legacy drain |
|---|---|---|
| `--positions-path` | `live_positions.track1.json` | `live_positions.json` |
| `--trade-log-path` | `global_index/track1_runtime/trade_log.track1.jsonl` | **absent** |
| `--route` | `track1_candidate` | **absent** |
| `--client-id` | `90` | (default 1) |
| `--lock-path` | `runner.track1.pid` | (default `runner.pid`) |

`--allow-orders` appears in **no** fired argv, in any mode.

**Gates.** `orders_possible=False`; `track1_stop_trading=False confirmation=False
track1_orders_approved=False`; blocking still
`['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']`. No confirmation file, no
`track1_runtime/orders/`.

---

## Part D — the first live sweep, twelve minutes later

The 00:20 ET sweep fired. Both routes launched in the same second, which makes the comparison
exact rather than approximate:

```text
22:20:00 [STOP_REPAIR_0020]         -m global_index.run_stop_repair
             --positions-path live_positions.json --port 4002

22:20:00 [TRACK1_STOP_REPAIR_0020]  -m global_index.run_stop_repair
             --positions-path live_positions.track1.json
             --stop-path STOP_TRADING.track1
             --lock-path runner.track1.pid
             --client-id 90
             --trade-log-path global_index/track1_runtime/trade_log.track1.jsonl
             --route track1_candidate
             --port 4002

22:20:11 [STOP_REPAIR_0020]         completed OK
22:20:13 [TRACK1_STOP_REPAIR_0020]  completed OK
```

That is the proof. Not a source reading, not a dry run — the running scheduler launching the
real job with both flags, beside a legacy job that has neither.

### What the sweep wrote, stated exactly

```text
global_index/track1_runtime/trade_log.track1.jsonl   created 22:20:01.18   0 bytes   0 rows
trade_log.jsonl                                      8486 bytes, mtime 2026-08-15   28 rows
```

**The Track 1 log exists solely because of the writability probe.** Recorded explicitly, as
briefed. `safety_trade_log.resolve` append-opens the destination before the job looks for its
book, so the file appears whether or not there is anything to write — and the timing confirms
the ordering: launched at :00, file created at :01.18, job finished at :13 after connecting to
IB Gateway. The probe ran first, exactly as designed.

**No close row was created, and none should have been.** `live_positions.track1.json` holds
zero positions, so the sweep found nothing to repair. The legacy log was not touched: same byte
count, same mtime from eleven days ago.

Both lock files were released — `runner.track1.pid` and `runner.pid` are both absent after the
run, so the `atexit` release worked on a path that connects to the broker.

**Runtime close-row proof is pending.** The destination is proven; that a real Track 1 safety
close lands in that file, tagged `route: track1_candidate`, cannot be shown until the route
holds a position and a sweep or a max-hold exit closes it. Nothing in this stage fakes that,
and the empty file is not evidence of it.

---

## Part E — tests

Nothing new was added. The five items the brief lists were already pinned, and adding a second
copy would have been noise:

| item | pinned by |
|---|---|
| Track 1 safety argv carries the log path and the route | 5ZG · `test_track1_stop_repair_argv_…`, `test_track1_maxhold_argv_…` |
| legacy safety argv stays legacy | 5ZG · `test_the_legacy_drain_safety_never_touches_the_track1_log` |
| the dashboard reads Track 1 evidence, not the stale legacy runner | 5ZF suite + `monitor/test_dashboard_backend.py` |
| checkpoint schema-2 summary reads route and date | 5ZH · the panel tests |
| no caller passes `--allow-orders` | 5M-D (strategy slots) + 5O (safety jobs) |

**Regression: 433 passed**, across 5ZG, 5ZH, 5ZF, 5O, 5M-D, 5P, the dashboard backend and the
realtime contract.

Three failures, all the pre-existing absence-proxy class. One was inside this stage's own
surface — 5O is the Track 1 safety-wiring suite that this stage makes live — and it asserted
`live_positions.track1.json` does not exist, which the live 15:55 close now writes by design.
Repaired with the identical one-line fix already applied to 5P: moved onto the
written-during-this-run check that sits two lines below it, with the measurement recorded.
**26 passed** after. The remaining two belong to 5M-D and are the gate-list staleness already
classified in 5ZI; untouched, as briefed.

---

## Part F — exactly what changed on disk

| file | change | why |
|---|---|---|
| `global_index/track1_runtime/trade_log.track1.jsonl` | **created, 0 bytes** | the writability probe in the 00:20 ET sweep. Intended: a reader can now tell "this route has never swept" from "it swept and closed nothing" |
| `scratch/test_track1_stage5o_route_aware_safety_20260824.py` | one assertion moved | absence-proxy repair, this stage's surface |

Everything else is byte-identical, checked by mtime before and after:
`replay_checkpoint.track1.json` and `live_positions.track1.json` (both 13:56:19),
`live_positions.json` and both max-hold markers (2026-08-24), the 2026-08-25 audit journal
(14:15:03), the signals journal and window coverage (13:56:19), and legacy `trade_log.jsonl`
(2026-08-15). No audit record was rewritten. No book or checkpoint was edited.

---

## What remains before paper

Six items, one fewer than 5ZI listed:

| | item | class |
|---|---|---|
| 1 | machine sleep — 16 missed jobs in one burst on the 25th | **operator** |
| 2 | B1 — separate account or a proven-flat legacy book | **operator decision** |
| 3 | checkpoint cannot resume: the call site passes no frames | code — **5ZK** |
| 4 | regime verification is warn-only and its return is discarded | code — **5ZL** |
| 5 | route-aware P&L, open-position parity, and keeping Track 1 rows out of legacy readers | code — **5ZM** |
| 6 | the planned stop is not journalled; `close_position` and `place_protective_stop` are unbuilt | code — **5ZN** |

Evidence stands where it stood: two judgeable days, both FAIL, five required, none clean. That
is item 1's consequence more than anything else's.

**Removed from the list:** *"5ZG's argv is not live"*. It is live, and a real sweep proved it.

## Next stage — 5ZK, and why

5ZK, checkpoint frames. Three reasons, in order of weight.

It has a **measurement gate in front of it** that nothing else on the list has: whether the
closing slot can reuse the frames it already holds or must load them again is unmeasured, and
if that cost is large the stage changes shape. Finding that out early is worth more than
finding it out late.

It is **cheap and self-contained** — one call site, no broker, no strategy change.

And it is the last thing standing between the route and a checkpoint that means something. The
audit now reads the checkpoint correctly and the artefact is still inert; a correct reader over
an empty file is a smaller achievement than it looks, and the gap between those two is exactly
5ZK.

5ZL is a close second and could be done in either order — it is smaller still. What should
**not** come next is 5ZM, for the reason 5ZI already gave: a P&L reader over the order journal
would be reading a journal that nothing writes yet.
