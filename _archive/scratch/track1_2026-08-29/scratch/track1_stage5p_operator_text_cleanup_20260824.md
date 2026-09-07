# Stage 5P cleanup — the operator text now describes the safety split

**2026-08-24 ·** no scheduler, backend or dashboard started or stopped · no IBKR connection ·
no order · no `STOP_TRADING`, `STOP_TRADING.track1` or confirmation file created or removed ·
no live state written · no commit · **no route, scheduler, safety or order logic changed**.

---

## What was wrong, and why it mattered

Stage 5O split the safety net in two. The operator text did not follow. In three places —
the `--track1-only-shadow` help on **both** `up` and `restart`, and the start banner — `ops.py`
told an operator:

> `safety sweeps   : still run against live_positions.json — Stage 5O`

That sentence was true *before* 5O and false after it. Its specific danger is the unqualified
plural: there are **two** safety sets now, watching **two** books, and a reader of the old
sentence concludes that a Track 1 position would go unprotected — the exact opposite of what
5O built. An operator about to start a shadow period is precisely the reader who would act on
that.

The same shape sat in the runbook, where sections written at Stage 5M-D still asserted, without
a date, that the sweeps were all legacy's and that NKD had no Track 1 slot.

## What the text says now

| | watches | is |
|---|---|---|
| **legacy drain safety** | `live_positions.json` | protection for positions still open in the legacy book — **not** Track 1's safety net |
| **Track 1 safety** | `live_positions.track1.json` | 11 jobs, own lock `runner.track1.pid`, own max-hold marker, clientId 90 |

`track1-only` removes legacy **strategy** jobs and keeps legacy **drain** safety until the old
book is confirmed empty.

The rendered help, with both numbers derived from the slot table rather than restated:

```
--track1-only-shadow  start the scheduler in TRACK 1-ONLY shadow mode: the 70 Track 1 slots
                      (all four sleeves) are registered and the legacy STRATEGY jobs are NOT.
                      ... Track 1 gets its OWN safety net (11 jobs on
                      live_positions.track1.json); the legacy safety jobs stay registered on
                      live_positions.json to drain any position still open in the legacy
                      book. Places no orders.
```

And the banner:

```
  legacy strategy : NOT SCHEDULED (45 jobs omitted, not merely halted)
  track1 safety   : 11 jobs watching live_positions.track1.json
                    (own lock runner.track1.pid, own max-hold marker, clientId 90)
  legacy safety   : still scheduled, watching live_positions.json — the
                    DRAIN. It protects positions still open in the legacy
                    book; it is not Track 1's safety net.
```

## Files changed

**`monitor/ops.py`**

* the banner's one stale line → two lines naming both sets and both books;
* the `--track1-only-shadow` help on `up` **and** `restart` (one identical string, both
  occurrences): stale safety clause removed, "all four sleeves" added, Track 1's own net named;
* new `track1_safety_count()` / `_t1_safety()` / `_t1_const()` so the banner and help read the
  slot table instead of restating counts and paths — the same derive-don't-restate fix Stage
  5M-C applied to the slot count, extended to the safety numbers.

**`docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md`**

Sections 9 (5M-D) and 10 (5N) were **not rewritten** — they are the record of what was true
when, and deleting that would make the next reader trust the document less, not more. They
gained a "Superseded in part" banner pointing at §11 and §12, their stale claims are dated to
their stage, and each names the stage that closed it. §11 (5O) and §12 (5P) were already
correct and are untouched.

**Read, not changed:** `NORMAL_STRESS_CALM_HANDOFF_2026-08-22.md` — its single
`live_positions.json` mention is about that file's rewrite-in-place semantics, not
track1-only guidance. The scratch Stage 5K/5M/5O/5P reports are historical records; no current
instruction in them is wrong, so they stay as the record.

## The guard, and why it is shaped this way

A guard that simply banned `live_positions.json` near the word "safety" would forbid the
**true** drain sentence along with the false one — and the true sentence is the one an operator
most needs. So the guard bans the *claim shape*: safety tied to the legacy book **on a line
that does not name legacy or drain as its owner**.

It is checked against both sides, so it cannot pass by having stopped looking: the exact
removed sentence must trip it, and the true drain sentence must not.

Three further misreadings from the brief are guarded the same way: no line may say the root
`STOP_TRADING` stops Track 1 (while `STOP_TRADING.track1` stays sayable), no unqualified line
may say NKD has no Track 1 slot, and the help counts must be derived.

## Tests

| | Result |
|---|---|
| `test_track1_stage5p_operator_text_20260824.py` | **20 passed** |
| Mutation check (text guards) | **3 / 3 detected**, files restored |
| Sweep: text + 5P + 5O + 5M-D + 5M-C + `test_ops` + dashboard backend + mirror | **375 passed** |

`global_index/test_event_playback.py` **not run** — still the known hang.

The three mutations put the stale text back and required a red: the exact banner sentence,
"STOP_TRADING halts Track 1 too" in the runbook, and an unqualified "NKD has no Track 1 slot".
The file-scan tests otherwise pass by finding nothing, which is the shape of a check that has
quietly stopped checking.

## Nothing about the route moved

Schedules verified unchanged in the same run: **60 / 129 / 95**. Orders still impossible —
`B1_broker_account_or_legacy_retirement` open, `may_enable_orders()` False. No switch file,
confirmation file, Track 1 book, lock file or Track 1 max-hold marker exists on disk.

The operator command is unchanged and now described correctly:

```powershell
python monitor/ops.py restart --scheduler --track1-only-shadow
```
