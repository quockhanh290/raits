# Stage 5ZG — a Track 1 safety exit can no longer be recorded as a legacy close

**2026-08-25, ET 19:00–21:10.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **nothing restarted** · no IBKR call · no runtime evidence
written or edited · no strategy logic changed.

```text
UTC 2026-08-26 01:12 · ET 2026-08-25 21:12 EDT · Calgary 19:12 MDT · Tokyo 10:12 JST (26th)
```

---

## Verdicts

| | |
|---|---|
| safety-exit legacy trade-log blocker | **CLOSED in code, tested — NOT yet live** (see §7) |
| next shadow window | **READY** |
| paper | **NOT_READY** — four reasons, unchanged |
| scheduler / backend / runtime / live file touched | **no** |
| legacy safety behaviour changed | **no** — new optional arguments only |
| Track 1 trade log path | `global_index/track1_runtime/trade_log.track1.jsonl` |
| route tag | **implemented now**, `route="track1_candidate"` |

---

## 1. What the write path was

Both safety entry points handed the runner the same literal, with no way to say otherwise:

    trade_log_path=str(_CWD / "trade_log.jsonl")

`run_stop_repair.py:180` and `run_maxhold_exit.py:171` as they stood this morning. Neither
accepted a destination argument, so the scheduler had no way to give them one.

Who calls them, and with what:

| caller | book | log |
|---|---|---|
| legacy `maxhold_exit` 09:31 | `live_positions.json` | legacy (hardcoded) |
| legacy `stop_repair_HH20` × 10 + Sunday | `live_positions.json` | legacy (hardcoded) |
| **`track1_maxhold_exit` 09:31** | **`live_positions.track1.json`** | **legacy (hardcoded)** |
| **`track1_stop_repair_*` × 10** | **`live_positions.track1.json`** | **legacy (hardcoded)** |

The Track 1 copies already received their own book, kill switch, lock file, client id and
max-hold marker — five per-route files. The trade log was the sixth and it was missing. No
route argument of any kind reached either script.

The stop-repair sweep is a writer even though it takes no entries: B3 runs inside
`FuturesRunner.__init__`, and when it finds a stop that has filled it books the money and
writes a CLOSE row. That is why the hardcoded path was there at all — it was added on
2026-08-17 after a max-hold close left equity moved and the log untouched.

Legacy behaviour therefore had to stay byte-for-byte unless a new argument is supplied,
because the legacy drain safety keeps running in this mode against the legacy book.

## 2. The destination chosen

    global_index/track1_runtime/trade_log.track1.jsonl

Named once, in `track1_slots.py`, beside the five constants it belongs with. Under the
Track 1 runtime root rather than beside `trade_log.jsonl` at the repository root: everything
else this route produces already lives there, and the readers that will consume it are being
written against that root. The scheduler passes the constant, both entry points accept it,
and no reader hardcodes it — a test changes the constant and asserts the argv moves with it.

A separate file rather than a shared one is not a preference. `paper_evidence_reader`
aggregates the whole trade log and splits on nothing — measured, and the route's own design
record already said so before this stage existed:

    "trade_log": "SEPARATE file until paper_evidence_reader can split on route"

A Track 1 close in the shared file would have entered legacy's fill-quality and P&L gates as
a legacy row. That record now names the real path and the real tag.

Checked, because a new file at that root could have broken something: every Track 1 runtime
reader targets a named subdirectory with an explicit glob (`window_coverage_*.jsonl`,
`slot_timing_*.jsonl`, `track1_audit_*.jsonl`, `explanations_*.jsonl`). Nothing enumerates
the root. The new file is invisible to all of them.

## 3. The contract

One small shared module, `global_index/safety_trade_log.py`, so the two scripts cannot drift:

| given | result |
|---|---|
| nothing | `trade_log.jsonl`, byte for byte what it was — no probe, no mkdir, no touch |
| `--trade-log-path P` | `P`, **proven writable now** or the job fails |
| `--route R` | every row this run writes carries `route=R` |
| `--route` alone | **refused**, exit 1 |

The destination is never inferred from `--positions-path`. That would have been one fewer
argument and one silent failure mode: a caller who changed the book but not the log would
have got legacy's file with no warning at all. The route tag without a destination is
refused for the mirror-image reason — rows tagged `track1_candidate` sitting inside the
aggregate that must not contain them.

**The probe runs before the positions check, not after.** Both scripts return early when
their book does not exist, which for most of the shadow period was every single run — so a
check placed after that return would never have executed, and a wrong path would first have
been discovered by the first real fill. Probed first, the eleven Track 1 safety jobs prove
the destination writable every day they run, months before there is anything to write.

The probe is an append-open of the real file, not a permission bit on its directory, because
an append-open is exactly what the writer will do; a writable directory containing an
unwritable file is a real state and the weaker check passes it. It creates the file empty on
first success, which is wanted: a reader can then tell "this route has never swept" (no file)
from "it swept and closed nothing" (empty file).

## 4. Route tagging — implemented, not deferred

`FuturesRunner` gained one optional keyword, `route=None`, last in the signature. When None
nothing is added, so every existing caller writes byte-identical rows and no legacy reader
meets a field it has never seen. When set, `_append_trade_raw` stamps `route` on every row —
`setdefault`, so a caller that already named its route is not overruled.

Measured on the real production log first: 28 rows, 20 distinct keys, **no `route` key
anywhere**. Legacy rows gain nothing; a Track 1 row's key set is the legacy set plus exactly
one, asserted both directions.

The tag duplicates what the path already says, deliberately. The path can be mis-wired by a
single argument; a row that ended up in the wrong file still names its own route. Nothing
splits on it yet — but a row is written once and read for years, and a reader taught to split
later cannot go back and label rows written before it existed.

The value is `track1_candidate`, matching the `route` field every other Track 1 artefact
already carries, not the shorter `track1` the brief suggested. Consistency with the five
existing per-route files wins; a tag that differs from the one on slot timing and window
coverage would need a translation table on day one.

OPEN rows are tagged too. An OPEN row that cannot say which route opened it is the same
defect one step earlier.

## 5. Scheduler wiring

The two Track 1 safety bodies now pass `--trade-log-path` and `--route`, both read from the
constant. Nothing else in their argv moved. Measured argv, track1-only mode:

```text
-m global_index.run_maxhold_exit
   --positions-path live_positions.track1.json
   --stop-path      STOP_TRADING.track1
   --lock-path      runner.track1.pid
   --client-id      90
   --trade-log-path global_index/track1_runtime/trade_log.track1.jsonl
   --route          track1_candidate
   --port           4002
```

| mode | jobs | Track 1 safety argv | legacy safety argv |
|---|---:|---|---|
| default | 61 | — | no destination, no route |
| transitional | 130 | — | no destination, no route |
| **track1-only** | **101** | destination + route | **no destination, no route** |

Job inventory unchanged: still 101 in track1-only. No job was added or removed.

## 6. Tests

**40 tests**, `scratch/test_track1_stage5zg_route_aware_safety_reporting_20260825.py`.
All ten items the brief asked for, plus the ones the code suggested.

The claim is split into two layers and then composed, because neither half is the claim on
its own: **which destination the script chooses** (call `main()` with the broker class and
`FuturesRunner` replaced, capture the kwargs) and **what the runner's real writer does with
it** (feed those captured kwargs into `FuturesRunner._append_trade` itself, bound to a bare
instance via `object.__new__` so B3 and B4 never run). A simulated Track 1 close therefore
travels the real selection path into the real writer and lands in the real file — and the
same tests assert no legacy log was created anywhere near it.

Notable coverage beyond the list:

- the refusal message must name what it is refusing to fall back to;
- the probe must not truncate an existing log (append, not write);
- the default path must not be probed or created — legacy is untouched, provably;
- the check must fire even when the book is missing (the shadow-period case);
- a refusal must exit **1**, not 0 — exit 0 is read by the scheduler as completed OK;
- `route` must be last in the runner's signature, so no positional caller can land on it.

**Mutation harness: 24 mutations, 24 red.** Source-level edits applied to the real files and
run in a subprocess, because the scheduler wiring and the entry-point ordering are not values
an in-process patch can express — a patch that only replaces `Path.read_text` cannot alter an
already-imported function, and that produced false green in six consecutive stages. Every
mutation proves its selected tests green first; two were reported as harness-broken on the
first pass (an anchor whose indentation made it a suffix of a second line, matching twice) and
were pinned rather than counted.

Two harness defects found and fixed while building it: the restore step compared file *bytes*
against re-encoded *text*, which fails on a correct restore in a CRLF repository and aborted
the sweep mid-run; and the two ambiguous anchors above.

## 7. What is closed, and what is not yet live

The blocker is closed **in code and under test**. It is **not yet closed in the running
system**, and that distinction is the whole of it:

- the entry-point changes are already live — the scheduler spawns each safety job as a fresh
  subprocess, which imports current source;
- the **argv** is built inside the running scheduler process, pid 48604, started 01:07 ET
  today and holding this morning's code.

Until that process is restarted, the Track 1 safety jobs are still invoked with no
destination and no route, and would still write the legacy log. No restart was performed —
the constraint forbids it and no measurement here needed one.

Also observed, and it changes what those jobs do at their next sweep: **`live_positions.track1.json`
now exists in production**, written at 15:56 ET today by the 15:55 shadow slot, with zero
positions. Both Track 1 safety jobs will therefore stop taking their early return and will
begin acquiring the lock and connecting to IBKR on every sweep. Nothing to do with this
stage, and not a defect, but it is new load and it is new since this morning.

## 8. Paper readiness — unchanged, and why

| blocker | class | still open |
|---|---|---|
| `PAPER_SHADOW_EVIDENCE` 0 / 5 clean sessions | evidence | **yes** |
| `B1_broker_account_or_legacy_retirement` | operator | **yes** |
| route-aware P&L / Flex / session report | code | **yes** — 5 of 6 pieces |
| `verify_regime_labels` is warn-only | code | **yes** |
| Track 1 safety exits write the legacy log | code | **closed here** |

Measured, not assumed: `orders_possible=False`, blocking list
`['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']`, no confirmation file,
no orders directory, `TRACK1_ORDERS_APPROVED` unset.

Stage 5ZF listed six missing reporting pieces and named this one first because it was the
only one that *corrupts* an existing artefact rather than merely omitting a new one. Five
remain, and they omit rather than corrupt.

## 9. Regression

| suite | result |
|---|---|
| Stage 5ZG | **40 passed** |
| Stage 5ZG mutations | **24 / 24 red** |
| dashboard backend · realtime contract · 5ZE · 5ZD · 5ZB · pre-sleep schedule status | **392 passed** |
| 17 suites that construct `FuturesRunner` (arm time, rollover, STP, sleeve ledger, …) | **222 passed** |
| safety + scheduler suites (5ZG, 5ZF, 5O, 5M-D, 5M0, 5P, stop-repair slots, max-hold, exit reason, entry-point lock, kill switch, client id, stop placement, critical echo) | **252 passed, 4 failed** |

**866 passed, 4 failed.** `test_event_playback.py` not run.

One test was updated because this stage closed what it pinned: Stage 5ZF's
`test_17_track1_safety_exits_write_the_LEGACY_trade_log` was a deliberate tripwire carrying
"if this becomes route-aware the report is stale", and it fired within hours. Inverted and
kept rather than deleted; its neighbour that guessed at a repo-root filename now asserts the
part that is still missing, the P&L output.

### The four failures are older than this stage, and here is the proof

| test | asserts | why it fails |
|---|---|---|
| 5O `test_no_switch_or_state_file_was_created` | `live_positions.track1.json` absent | the file exists |
| 5M-D `test_no_switch_or_state_file_was_touched` | same | same |
| 5P `test_no_switch_or_state_file_was_created` | same | same |
| 5M-D `test_b1_still_blocks_orders` | blocking list is exactly `[B1]` | it is `[B1, PAPER_SHADOW_EVIDENCE]` |

`live_positions.track1.json` has mtime **13:56:19 Calgary**; the earliest file this stage
edited has mtime **19:05:23**, five hours later. The gate name in the fourth is defined in
`track1_gates.py` and `track1_paper_executor.py`, and appears **zero** times in all six files
this stage touched.

Three of the four are the same one-line pattern, and it is one this project has already
diagnosed twice: **absence standing in for "no test wrote it"**, which breaks the moment the
running system starts writing the file legitimately. 5P's own comment says so, three lines
above the assertion that still uses it. The fix is the mtime comparison sitting immediately
below it in the same function. Not applied — they are unrelated to this stage and the brief
says not to chase them.

## 10. Files touched

| file | change |
|---|---|
| `global_index/safety_trade_log.py` | **new** — the destination/tag contract, shared by both entry points |
| `global_index/track1_slots.py` | `TRACK1_TRADE_LOG_PATH`; the output policy now names the real path and tag |
| `global_index/runner.py` | optional `route=None`, last in the signature; `setdefault` in the writer |
| `global_index/run_stop_repair.py` | `--trade-log-path`, `--route`, probe before the book check |
| `global_index/run_maxhold_exit.py` | same, plus the destination on its startup banner |
| `global_index/run_scheduler.py` | the two Track 1 safety bodies pass both, from the constant |
| `scratch/test_track1_stage5zg_…py` | new, 40 tests |
| `scratch/track1_stage5zg_mutations_…py` | new, 24 mutations |
| `scratch/test_track1_stage5zf_…py` | two tests inverted — this stage closed what they pinned |

No file under `global_index/track1_runtime/`, `monitor/`, or any live state was written.
