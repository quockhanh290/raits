# Stage 5Z — the rehearsal, and the wall it has to stop at

**2026-08-25, 04:50–06:00 ET ·** no order · **no IBKR connection** · the only broker in this
stage refuses by name · no confirmation file · `TRACK1_ORDERS_APPROVED` unset · no
`--allow-orders` · nothing wired into the runtime slot path · scheduler pid 48604 and backend
pid 35352 untouched, not restarted · no runtime evidence written · no commit.

> **Clock correction (Stage 5ZB, 2026-08-25).** The times in this header were read with
> `TZ=America/New_York date`, which on this machine returns **UTC**. The real ET times were
> four hours earlier than stated. Nothing else in this report depends on them — no window
> was open during the work either way — but the numbers themselves were wrong and are
> corrected here rather than left for a later reader to trust. Anchor with
> `zoneinfo`, never with the shell.

---

## Verdict: **READY_FOR_PAPER_CALLSITE_IMPLEMENTATION_AFTER_EVIDENCE**

Every piece between a decision and a broker now runs in sequence and stops at the last inch.
What remains is the evidence gate and one design decision about scope, both named below.

---

## The seam is not where Stage 5W said it was

That report named `run_shadow`'s `NoOrderBroker()` line as "the call site — one line". **Both
halves are wrong**, and it took reading the file to see it:

| the claim | measured |
|---|---|
| the seam is in `run_shadow` | `run_shadow` replays a whole measured **window**. The scheduler's 70 strategy slots run `observe_live_slot`, a different function that takes no gate and no broker. |
| swapping `NoOrderBroker` would enable orders | in `run_shadow` the broker object is **never passed to anything**. It is constructed and read exactly once — `len(broker.calls)` — to prove nothing was sent. Replacing it changes nothing, because no code hands it an order. |

The real seam is in `observe_live_slot`, immediately after

```python
settlements, decisions = run_candidates(found, book=book)
```

— the first and only moment a live slot holds admitted decisions.

**`seam()` derives that location from the file** rather than restating it. A comment naming a
line number is a comment that will be wrong, and this one already was. It also refuses when the
anchor becomes ambiguous: two `run_candidates` calls in that function means there is no single
right answer, and picking the first would be wrong half the time.

---

## The dry run

`global_index/track1_paper_callsite.py` — pure, imported by nothing, and unable to send even if
it were. Six stages, and the sixth is a wall:

| stage | what it exercises | result today |
|---|---|---|
| `gate` | the **real** blocker table | `allow_orders=False`; B1 and `PAPER_SHADOW_EVIDENCE` |
| `reconcile_precheck` | book read-back + broker positions | entries **would be blocked** — the wall cannot testify |
| `executor` | construction against the wall | built; reports order id at placement |
| `mapping` | every admitted decision → `broker.Order` | 2 of 2 admitted from 3 offered |
| `journal` | INTENDED + SUBMITTED, durable | 6 rows, 0 invalid, in a **redirected** root |
| `boundary` | the broker refuses | 2 of 2 stopped, **0 sent** |

The rehearsal runs on a **synthetic** gate — a distinct type from `ProductionGate`, so
`isinstance` tells them apart — and records the true answer beside it. Arming the rehearsal
arms nothing.

### A dry run succeeds by being STOPPED

`ok` requires `reached_boundary`. A run where nothing was admitted has every stage pass and is
**not** ok, because it never got as far as the thing it exists to test. That is the difference
between a rehearsal and a test suite that checks nothing, and three tests exist purely to hold
the line.

### What it leaves behind, deliberately

```text
intended · submitted · unknown        ×2
```

`UNKNOWN` because the wall raises — which is the correct record of *"we were about to send and
could not see what happened"*, and is exactly the crash-path rehearsal worth having.

Those rows are indistinguishable from real ones once written: same route stamp, same schema,
and they read as unresolved orders. **The only thing keeping them apart is the directory**, so
the directory is checked hard. `assert_dry_run_root` refuses the production journal, any parent
of it, and any child of it — a parent matters because `journal.read(day=None)` walks the tree.

---

## Scope of the remaining stubs — measured, and the answer surprised me

The question was whether entry-only is safe or whether close / protective stop / switch must be
designed first. The answer came from the scheduler registry, not from judgement:

**The protective stop and the max-hold exit are already covered.** `run_stop_repair` and
`run_maxhold_exit` are registered as **11 Track 1 safety jobs** against
`live_positions.track1.json`, and B3/B4 run inside `FuturesRunner.__init__` — they place stops
on unprotected positions and book exits past max hold.

They no-op today **only because that book file does not exist.**

Which turns the finding around: an entry-only call site does not leave a naked position. It
does something with a larger blast radius — **the first paper fill activates eleven jobs that
have never run against anything**, and they connect to IBKR on the Track 1 safety client id.
That is designed behaviour, and it should be a deliberate, watched event rather than a side
effect of the first fill.

| operation | covered by | what is missing |
|---|---|---|
| `open_position` | the executor (5W) | nothing — built and rehearsed |
| `place_protective_stop` | `run_stop_repair`, B4 | **no journal row** — a stop placed by the safety job is invisible to the order journal |
| `close_position` (max hold) | `run_maxhold_exit`, B3/B4 | same: books the exit and writes `trade_log`, not the order journal |
| `close_position` (strategy exit) | nobody | the sleeves' own exits have no path to a broker at all |
| `switch_same_symbol` | nobody — **`track1_switch` is imported by NOTHING** | it calls `send_order` at two sites with no journal; if it is ever wired it must go through the executor, or two orders leave no record |

**Recommendation: entry-only is the right first scope**, on three measured grounds — the exit
and stop paths already exist and are already scheduled, the switch cannot bypass the journal
because nothing imports it, and the strategy-exit gap is not reachable from a live slot either.
The two things to do before the first fill are not code: watch the eleven safety jobs on their
first real run, and accept that stops and exits will not appear in the order journal until a
later stage routes them through the executor.

---

## Confirmations

**No scheduler or ops path can trigger a send.** Three independent facts, all by AST: no arming
flag in any argv, no broker constructed anywhere in `observe_live_slot`, and no `send_order`
call reachable from either `run_scheduler.py` or `monitor/ops.py`.

**Armed and shadow still decide identically before the boundary.** The mode label is read
exactly once after assignment and that read is the explanation writer's argument; both live
modes sit inside `FRESHNESS_BINDING_MODES`. And the live slot path records `SHADOW_LIVE`
unconditionally — it has no gate, so it cannot record `armed` even by accident.

**The evidence gate still blocks.** `gate_measurement` returns `False`; 0 of 5 judgeable days.

**No real runtime orders directory** exists, and none was created — every rehearsal journal
lives under `tmp_path`, and `track1_dry_run` is absent from the repo.

**No IBKR connection.** The dry-run module imports no `ib_insync`, no `ibkr_broker`, no
`socket`, asserted by AST.

---

## Tests and mutations

**44 tests. 23 mutations, all red**, each with a proven-green baseline.

The mutations that matter are the ones that make a rehearsal *look like a pass*:

| | mutation | caught by |
|---|---|---|
| M1 | `seam()` names `run_shadow` again | the seam test |
| M2 | `seam()` picks the first anchor instead of refusing ambiguity | the doubled-anchor test |
| M3 / M4 | `run_shadow` hands its broker on / the slot path builds one | the two structural tests |
| M5 / M6 | the wall returns a fill / the wall testifies and answers | the wall tests |
| M7 | the supplied-broker check skipped | a willing broker accepted |
| M8 / M9 / M9b | the production root accepted / only equality checked | the three root tests |
| M10 / M10b / M11 | a rehearsal that never ran reports success | the not-ok tests |
| M12 / M13 | the synthetic gate reported as production's / the wall believed | gate and precheck |
| M14 | rejected decisions mapped anyway | the journal test |
| M15 / M16 / M17 | the coverage finding invalidated | the three scope tests |
| M18 / M19 / M20 / M21 | production imports it / arming flag / label leaks / gate opens | the wall tests |

### Two mutations found the code being right twice

**M10 and M11 stayed green at first, and the code was the reason.** `ok` is guarded *twice* —
the property requires `reached_boundary`, and the boundary stage carries the same flag as its
own `ok`. Removing one guard changes nothing. **M6 was the same shape**: the wall both declines
to testify *and* returns "cannot say" from every read.

Redundancy like that is normally a smell. Here it is the difference between a rehearsal that
has to lie once and one that has to lie twice, so both are now pinned by their own tests
(`test_24b`, `test_7b`) and the mutations remove both guards — which is what a well-meaning
"simplify this" or "make the fake more useful" change would actually look like.

That is three stages running where the mutation harness taught me something about the code
rather than the reverse.

---

## Regression

| | result |
|---|---|
| Stage 5Z alone | **44 passed** |
| one combined run: 5Z + 5Q-9 · 5R-0 · 5S · 5T · 5U · 5V · 5V-1 · 5W · 5X · 5Y + the 16 legacy `Fill`/`send_order` consumers + the schedule mirror (27 files) | **695 passed**, 52s |
| Stage 5Z mutations | 23 red, 0 green |
| Stage 5X and 5Y mutations, rerun after the test edits | all red |

Five tests in the older suites needed updating, all for the same reason and all in the
direction of a **stronger** guarantee. Those suites asserted the chain had two heads — the
executor and the read module, each imported by nothing. Stage 5Z put a single head back on it:
the dry-run module imports both, and nothing imports the dry-run module. **One door to watch
instead of two**, and each of the five now asserts exactly that, so any of them fails if the
head is ever wired in.

---

## What is left

| # | what | note |
|---|---|---|
| 1 | `PAPER_SHADOW_EVIDENCE` — **0 of 5** judgeable days | the first NKD window that can be judged on the fixed gate is **2026-08-26 01:10 ET** |
| 2 | `B1_broker_account_or_legacy_retirement` | a decision about the account, not code |
| 3 | the eleven safety jobs have never run against a real book | the first fill activates them; that should be watched, not discovered |
| 4 | stops and exits do not appear in the order journal | a later stage routes them through the executor |
| 5 | `close_position` / `place_protective_stop` / `switch_same_symbol` | still 5T stubs, and none of them is reachable from a live slot |

Nothing on that list is a code gap in the order path. **The call site is designed, rehearsed
end to end, and blocked only by evidence.**

---

## Files

```text
global_index/track1_paper_callsite.py                        NEW · imported by nothing
scratch/test_track1_stage5z_callsite_dryrun_20260825.py      44 tests
scratch/track1_stage5z_mutations_20260825.py                 23 mutations, all red
```

No production file was modified by this stage.
