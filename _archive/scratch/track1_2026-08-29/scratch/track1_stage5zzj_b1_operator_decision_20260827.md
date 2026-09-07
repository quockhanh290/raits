# Stage 5ZZJ — the B1 operator decision: measured, previewed, and **not yet placed**

**2026-08-27.** No orders · `TRACK1_ORDERS_APPROVED` never set · no orders directory · no order
journal · no `--allow-orders` · scheduler not restarted · legacy books read only. One read-only
IBKR connection on **client id 97**, stated before it was made.

---

## Status in one line

**Parts A, B, E and F are complete. Part C — placing the decision file — was refused by the
harness, so B1 is still open and I need your go-ahead.** Everything that does not depend on
that write is finished, and the write itself is one file-copy away.

---

## The two things you need to decide

### 1. The harness blocked the write

Placing `track1_go_live_confirmation.json` was denied by the auto-mode classifier. It is the
file that releases a go-live gate, so I stopped rather than reaching for a different tool to
put the same bytes in the same place. The exact command, ready to run:

```powershell
copy scratch\track1_b1_decision_candidate_20260827.json track1_go_live_confirmation.json
```

Those are the **exact bytes that were previewed** — placing anything else would mean the preview
described a different file. Say the word and I will place it, or run the line yourself.

### 2. Part C and Part D.3 contradict each other

Part C says write the B1 decision. Part D.3 expects `confirmation` to remain **false** after.
Measured: `ops status`'s `confirmation` field and `track1_gates.CONFIRMATION_PATH` resolve to the
**same file** — `D:\raits\track1_go_live_confirmation.json`. So writing the decision *necessarily*
makes `confirmation=True`; there is no way to satisfy both.

I read Part D.3 as carried over from earlier stages, where the file was forbidden outright. The
invariant that actually matters — **`orders_possible=False`** — holds either way, and the preview
proved it before anything was written. If you meant Part D.3 literally, then the stage cannot be
completed as written and I should not place the file at all.

---

## Part A — measured before deciding

`ops status` opened with **`b1_legacy_flat=UNKNOWN (record_stale)` — "the last B1 audit is too
old to count."** Part A.5 applies, so the measurement was refreshed first. Nothing stale was
signed.

```text
python -m global_index.b1_audit --broker ibkr --record      (client id 97, read-only)

  legacy book        read  positions=0
  track1 book        read  positions=0
  broker       ibkr_direct  connected=True  positions=0  working orders=0
  equity       250,819.13

  B1  PASS  (legacy_and_broker_flat)
  recorded -> global_index\track1_b1\track1_b1_20260827.jsonl
```

| condition | required | measured |
|---|---|---|
| broker positions | 0 | **0** |
| broker working orders | 0 | **0** |
| legacy book positions | 0 | **0** |
| Track 1 book positions | 0 | **0** |
| Track 1 book schema | 2 | **schema_version 2** |
| Track 1 book route | `track1_candidate` | **`track1_candidate`** |
| paper baseline | PASS / USD / ~250k | **PASS · USD 250,817.91 · DUR125337** |
| confirmation file | absent | **absent** |
| `track1_runtime/orders` | absent | **absent** |
| `orders_possible` before | False | **False** |

```text
B1 audit         checked 2026-08-27T16:04:17Z   age 0.07h   expires 2026-08-28T16:04:17Z
account baseline checked 2026-08-27T11:29:47Z   age 4.58h   policy max 24h
```

Both inside their windows. **External change noted:** the backend pid moved from 6420 to 45676
between Stage 5ZZH and this stage — someone restarted it. Nothing this stage did.

## Part B — the preview, run through the 5ZR tool

The candidate lives in `scratch/`, never at the production path.

```text
  validates      : yes
  decision       : legacy_retired_confirmed
  waiver         : not set
  B1 measurement : PASS (legacy_and_broker_flat)
                   counts until 2026-08-28T16:04:17Z
  legacy entries : none
  would release  : B1_broker_account_or_legacy_retirement
  would still block: PAPER_SHADOW_EVIDENCE
  orders possible: False
```

**Part B.3's stop condition is not triggered:** `legacy entries: none` — the running scheduler is
in `track1-only-shadow`, which registers no legacy strategy job.

### The one warning, and it is the important one

> Legacy is dormant because of a command-line flag, not because it has been retired: a restart
> without `--track1-only-shadow` registers its entry jobs again, and this recorded decision would
> go on reading as true.

That is the module's own designed warning and it is worth stating plainly: **`track1-only-shadow`
registers zero legacy strategy jobs; the default mode registers 45.** One flag separates them. So
the decision you are about to record is a claim that a plain restart can falsify silently, while
the gate keeps reading it as true. Retiring legacy properly is the switch-over runbook's ordered
procedure, not this flag.

This does not block the decision — it is your call and you have made it — but it is the thing to
carry forward, and it is why the running mode is now pinned by a test.

## Part C — **not done**

Blocked as described above. The candidate is written and previewed; the production path is still
absent.

## Part D — established analytically, not executed

The preview computes the after-state from the real registry with the candidate's confirmations,
so this is measured rather than predicted — but it has not been observed on disk:

```text
before   blocking = [B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE]
after    blocking = [PAPER_SHADOW_EVIDENCE]           B1 released
         orders_possible = False                       PAPER_SHADOW_EVIDENCE still blocks
         orders approved  = False                      env var unset
         orders dir       = ABSENT
         confirmation     = True                       <- necessarily; see the contradiction above
```

If B1 still refuses after the file is placed, the causes are enumerated and each is separately
tested: missing decision · stale measurement (>24h) · FAIL/UNKNOWN measurement · a file that does
not validate · an unknown key · both decisions set at once · a waiver with no reason.

## Part E — B1 on the dashboard

B1 appeared in `ops status` and **nowhere on the page**, so the operator had to leave the
dashboard to learn whether the route's most consequential gate was open. The runtime reader now
carries a `b1` block: decision state, who signed it and when, measurement status with its age and
expiry, broker and book counts, account equity, remaining blockers, and one operator sentence.

Three decision states, because two would lose the one that matters:

```text
not_recorded   the operator has not decided — the normal state, not an error
accepted       a valid decision is on file
invalid        a file exists and does not validate
```

`invalid` grants exactly what `not_recorded` grants — nothing — and means something completely
different to whoever has to fix it. `closed` is asked of the gate registry rather than computed
from the two halves: a second opinion in the reader is a second thing to keep in step, and this
project has already watched a restated sentence go stale twice.

Legacy issues stay scoped as legacy; nothing was deleted. **No backend restart is needed for this
stage's own verification** — but the running backend will not serve the new `b1` block until it
restarts, for the reason measured in 5ZZH (the module is cached even though the import sits
inside the view). Command, **not run**:

```powershell
python monitor\ops.py restart --backend
```

## Part F — tests

**26** in `scratch/test_track1_stage5zzj_b1_operator_decision_20260827.py`. No broker contacted,
every decision file under `tmp_path`, and two tests assert the production path is never written
by anything in the file.

### A wording correction worth making

Four of the stage's test items say *"cannot **write** the decision without X"*. **There is no
writer** — `track1_b1_decision` has no code path that writes anything, deliberately: *"the
confirmation file is written by a person, never by a script, and that includes this one."* So the
honest translation is *the decision does not **open the gate** without X*, tested where it is
actually enforced. A test is also added asserting the preview module never grows a writer, because
that property is the thing the "cannot write" items were really protecting.

**9/9 mutations RED**, source-level in a subprocess, every file restored byte-identical:

```text
a signature alone opens B1 again (the measurement half is dropped)
B1 stops blocking orders
an unknown key is silently dropped instead of refused
a half-parsing file has its valid flags honoured
the preview stops warning that dormant is not retired
the preview stops warning that legacy can still enter
an unreadable scheduler is reported as safe
the reader computes `closed` itself instead of asking the registry
an invalid decision file reads as absent
```

Two of those first came back labelled **"GREEN — the guard is asleep"** at exit code 2. Exit 2 is
a pytest usage error: my mutation had broken the file's syntax and nothing ran. Calling that green
is the worst available label — it reads as a guard that failed to notice when in fact there was
no run at all, the same family as counting "nothing collected" as a pass. The harness now names
exit 2–5 **"BROKE THE FILE — proves nothing"**, and both mutations were rewritten to flip a
condition rather than mangle a statement.

One test caught a bug in itself: the read-only proof built its candidate file *after* installing
the write barrier, so the test's own fixture tripped the trap and reported the preview for a write
the test had made. A green version of that would have proved nothing.

### Two stale pins repaired

`test_5_a_waiver...` and `test_18_the_preview_reports...` in the 5ZR suite pinned
`REGIME_LABEL_VERIFICATION` as still blocking. That gate was released by its own measurement on
2026-08-26, so both failed for a reason with nothing to do with B1 — the roster-pin anti-pattern
again. Rewritten as the property each test is actually about: the preview reports everything still
blocking **except** B1.

### Suites

```text
5ZZJ + 5ZR + 5ZQ + ops + ops-status + dashboard backend + realtime contract   352 passed
```

**Pre-existing failures: 2**, both the stale `REGIME_LABEL_VERIFICATION` pins described above.
Both repaired rather than left red; nothing else was red before or after.

## Part G — safety

```text
orders_possible                False  (before, and after by preview)
blocking now                   B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
TRACK1_ORDERS_APPROVED         unset
confirmation file              ABSENT (Part C blocked)
track1_runtime/orders          ABSENT
order journal                  not created, not modified
--allow-orders                 absent from run_scheduler.py and monitor/ops.py (comments stripped)
scheduler restarts             0
legacy trade logs / books      read only
IBKR connections               1, read-only, client id 97, announced before it ran
```

---

## What I need from you

1. **May I place the decision file?** One copy of the previewed candidate to
   `track1_go_live_confirmation.json`, or run the line yourself.
2. **Was Part D.3's "confirmation remains false" meant literally?** If so, the decision cannot be
   recorded at all and I should stop here.

After the file is placed I will re-run `ops status`, confirm B1 has left the blocking list, and
confirm `orders_possible` is still False with `PAPER_SHADOW_EVIDENCE` still holding.
