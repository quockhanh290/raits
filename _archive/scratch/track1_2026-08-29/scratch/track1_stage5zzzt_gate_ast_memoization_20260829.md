# Stage 5ZZZ-T — the gate stopped re-reading forty files to answer the same question

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

This is the fix Stage 5ZZZ-S named and was not permitted to make. `track1_gates.py` is a safety
file, so the standard here is higher than "it got faster": the gate must give the **same answer**,
and it must still be **unable to say a file is clean when it cannot read it**.

---

## 1. Before

```text
blocking()            0.212s      40 modules parsed, every call
as_ledger()           0.448s
may_enable_orders()   0.212s
live_frame_wiring()   0.210s
```

One `/api/v1/track1-runtime` request runs that machinery four times — the 160 parses Stage
5ZZZ-S measured — which is what put the endpoint at 1.89s.

`orders_possible: False`, blocking `['PAPER_SHADOW_EVIDENCE']`. The **full ledger** — all 11
blockers with every `measured_now` and `required_measurement_now` — was written to disk first, so
"unchanged" could be a comparison rather than a claim.

## 2. The change

One function, `_identifiers`, which is a pure function of file content. A `stat`, a dict lookup,
and a frozenset store.

```python
p = Path(path)
st = p.stat()                     # raises for missing/unreadable — fail-closed, as before
key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
```

**Every part of the key earns its place:**

| part | what it catches |
|---|---|
| resolved path | two modules must not share an entry |
| `st_mtime_ns` | the ordinary change signal — **nanoseconds**, because a coarse clock lets two edits inside one second look identical |
| `st_size` | the case mtime cannot see: a same-second, same-timestamp rewrite |

Getting past both at once needs two files of identical length *and* an identical nanosecond
timestamp. That is not something an editor does.

The value is a **`frozenset`**. The cached object is handed to every later caller, and a mutable
set would let one caller quietly edit what the next one measures.

**What is not cached:** every gate decision, blocker list and measurement result. Those read state
that no file timestamp can speak for. Only the parse is remembered.

### Fail-closed, deliberately ordered

`stat()` runs **before** the cache is consulted. A file that has gone missing or unreadable raises
there, exactly as the read used to, and is never answered from a remembered scan — because
*"I cannot see the file"* and *"I saw the file and it was clean"* are the two answers this gate
exists to keep apart.

## 3. After

| | before | after | |
|---|---:|---:|---|
| `blocking()` | 0.212s | **0.034s** | 6.2× |
| `as_ledger()` | 0.448s | **0.069s** | 6.5× |
| `may_enable_orders()` | 0.212s | **0.033s** | 6.4× |
| `live_frame_wiring()` | 0.210s | **0.023s** | 9.1× |
| `ast.parse` per `blocking()` | 40 | **0** | |
| **`track1-runtime` warm** | **1.89s** | **0.655s** | target <1s **met** |

`track1-market-view` stays at 0.031s. Cold first calls (runtime 45.2s) are dominated by the Stage
5ZZZ-S background warm-up workers saturating the CPU, not by the gate — labelled, not attributed
to this change.

## 4. Proof the gate says the same thing

The full ledger, captured before the edit and after, compared as sorted JSON:

```text
FULL LEDGER + DECISIONS BYTE-IDENTICAL : True
orders_possible   False -> False
blocking          ['PAPER_SHADOW_EVIDENCE'] -> ['PAPER_SHADOW_EVIDENCE']
blockers in ledger  11 -> 11
```

Not just the summary — every blocker's live measurement, which is exactly where a wrongly cached
wiring result would surface.

## 5. Proof the cache invalidates

The two invalidation tests are **adversarial on purpose**. Either key part alone would pass a
naive test and miss a real change, so each is tested against the edit the *other* part cannot see:

- **Same-size edit** — `import alpha` → `import bravo`, identical length on disk. Only mtime can
  see it. The scan must return `bravo`.
- **Same-mtime edit** — content lengthened, then the timestamp **forced back** with `os.utime` to
  the exact original nanosecond. Only size can see it. The scan must return the new name.

And the one that matters to the gate: a module that gains `from ib_insync import IB` must **stop
reading clean**. It does.

Three fail-closed cases: a missing file raises and leaves **no cache entry**; a file cached and
then deleted raises on the next call; unparseable source still raises `SyntaxError`.

## 6. Tests

**18 new, all passing. Seven mutations, seven caught, none survived:**

```text
key omits mtime            -> caught by the same-size edit
key omits size             -> caught by the same-mtime edit
returns a mutable set      -> caught
unreadable file -> empty   -> caught  (this is the fail-OPEN one)
deleted file served cached -> caught
blocker list in the cache  -> caught
memoisation removed        -> caught
```

One of my tests failed on its first run for a real reason: it compared against `len()` of a Python
string while Windows writes CRLF, so the on-disk sizes were 14 and the assertion said 13. It now
compares the two on-disk sizes.

### Regression: 362 passed, 7 failed — and all seven are pre-existing

I did not assume that. Every one was re-run with an **uncached `_identifiers`** — the pre-stage
logic byte for byte. All seven **fail there too**. Four ran standalone; the other three need
fixtures, so they were re-run under a pytest plugin that swaps the function at import.

What they actually pin: a suite written **2026-08-22** asserting `track1_go_live_confirmation.json`
does *not* exist (the operator signed it on 08-27), a slot count of 70 against today's 71, and a
ledger/registry comparison. **Left failing, not re-pinned** — that is the operator's call.

## 7. The scheduler still runs the old code

It was not restarted, so pid 34564 holds the pre-memoisation module in memory. The speed-up is
live for the dashboard and for any newly started process; the scheduler picks it up whenever it is
next restarted.

**This is not a divergence risk.** The change is performance-only and the gate output is
byte-identical either way, so the two processes cannot disagree about whether orders are possible.

---

## 8. Answers

| question | answer |
|---|---|
| Before/after | `blocking()` **0.212s → 0.034s**; `track1-runtime` warm **1.89s → 0.655s** |
| Exact cache key | `(str(Path(path).resolve()), st.st_mtime_ns, st.st_size)` → `frozenset` |
| Invalidation proven | same-size edit caught by mtime; same-mtime edit caught by size; deleted file raises rather than serving a stale hit |
| Gate output unchanged | **full ledger byte-identical**, 11 blockers, decisions identical |
| Backend restart | needed and **done once**; scheduler untouched |

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
env var alone            proven unable to open orders (test)
confirmation             untouched, sha16 67504a1c8a31a6a4, grants no order authority
swing paper override     present, valid, grants nothing
orders dir               ABSENT
orders sent              ZERO
broker / subprocess / network calls from the gate path   ZERO
scheduler                pid 34564, NOT restarted, still alive
gate decisions · blocker logic · strategy logic · params   unchanged
```

**One line worth keeping.** The cache remembers what a file *said*, never what the gate
*concluded* — and it re-checks that the file is still there, in its current state, before it
answers at all.
