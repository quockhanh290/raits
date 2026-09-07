# Stage 5ZZH — the page's biggest number belonged to the wrong route

**2026-08-27.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED` never set · no
orders directory · **nothing restarted** · no runtime trading file written. Read-only API calls
against the running backend only.

---

## Verdicts

| | before | after |
|---|---|---|
| **dashboard_account_source** | **LEGACY** — headline from the legacy runner's 80-hour-old snapshot | **TRACK1_BASELINE** — headline from `track1-runtime.paper_account`, currency spelled out |
| **open_issue_scope** | **SCOPED, NOT GROUPED** — every issue already carried `route_scope` (5ZZF); the list was flat | **GROUPED** — Track 1 / Shared / Legacy, nothing hidden, nothing dropped |
| **track1_runtime_panel** | readable, but silent about where its blockers came from | names its source; legacy/debt issues explicitly do not block |
| **orders_possible** | **False** | **False** — unchanged, and asserted before and after |

---

## 1. A file-location correction first

The stage names `monitor/static/dashboard.js` and `monitor/static/dashboard.css`. **Neither
exists**, and neither does `monitor/static/`. The live dashboard is
`global_index/dash/realtime/realtime.{js,css}`, served by `monitor/backend/app.py` — the same
files Stage 5ZZF worked in. All frontend work below is there.

## 2. Part A — measured, not inferred

```text
ops status        backend pid 6420 (port 5002) · scheduler pid 14344
                  track1_mode = track1-only-shadow  (source: process_table)
                  blocking = B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
                  orders_possible = False · confirmation = False · approved = False
                  slot table: 71 source / 71 registered

/api/v1/track1-runtime   paper_account  PASS  USD 250,817.91  DUR125337
                                        checked 2026-08-27T11:29:47Z
                         route          track1_candidate
                         gates          blocking_now = the two above

/api/v1/broker           equity 250,818.61 · fresh · age ~5s

/api/v1/runner-state     meta.account         50,000.00      <- the card's "base"
                         snapshot.equity      50,408.25      <- the card's headline
                         meta.broker_equity  996,730.93      <- the CAD-era figure
                         observed_at 2026-08-24T06:58:47Z
                         age_seconds 288,670  (80.2 hours)
                         freshness   "fresh"                 <- see §4

/api/v1/open-issues      5 issues · scopes [known_debt, legacy, scheduler]
                         track1_readiness_blockers_come_from =
                             global_index.track1_gates.blocking()
                         track1_readiness_blocker = False on all five
```

## 3. What the card was actually saying

```text
        $50,408   +408
        +0.82%  since Aug 10, 2026  /  base $50,000
        Paper account USD 250,818 · baseline PASS · broker now 250,819 · ...
```

Every figure in the first two lines came from the **legacy** runner: the equity from a snapshot
dated 2026-08-24, the base from its own `meta.account`. The account this route would actually
start from — USD 250,818, proven flat against the broker that morning — was the small print
underneath. **The largest figure on the page was the least current one**, and it belonged to a
different route.

Stage 5ZZF fixed the small print. It did not touch the headline, and the headline is what a
reader sees first.

## 4. A second finding, measured on the way

`/api/v1/runner-state` reports **`freshness: "fresh"` for a payload 288,670 seconds — 80.2
hours — old.**

The freshness label comes from the schedule model, which asks whether a publication was *due*.
In track1-only mode the legacy runner is never scheduled, so nothing is ever late and nothing
is ever called stale. The page's whole runner-derived zone dims on that label, so it never
dimmed.

A freshness model that assumes its producer still runs cannot report a producer that has
stopped. The legacy contract is left alone — other panels read it — but nothing in this card
trusts it any more: staleness here is measured from `age_seconds`, past a twelve-hour line,
because the legacy runner published daily and one missed publication is a producer that has
stopped rather than one running late.

## 5. Part B — the source contract

Decided in the **backend**, not in a template. A policy spelled out in string interpolation is
a policy nothing can test.

```text
track1_runtime_reader._paper_account now returns
    age_hours        computed at read time from checked_at
    headline_usable  status in (PASS, WARN) AND a real equity
    headline_reason  why, in words, when it is not
```

and the page follows it:

```text
usable            -> headline is  USD 250,818, currency spelled out
                     sub-line     baseline PASS · read 3.7h ago  /  USD 250,000
UNKNOWN or FAIL   -> headline is  "not measured" / "baseline FAIL"  — AND STOPS
no Track 1 block  -> the legacy card, exactly as before
```

**The refusal branch is the point.** Falling back to the legacy figure is what produced the
confusion, and a fallback that fires silently is worse than a blank.

### Why the funded baseline is not shown as a gain

`+818 since 250,000` is arithmetically correct and would be read as Track 1 making money.
**Track 1 has sent no orders.** The difference is whatever the paper account happened to hold
when it was funded. A number that will be misread as P&L is not improved by being right, so the
slot is empty and says why on hover. The legacy runner's realised figure and its return are
blanked in Track 1 mode for the same reason — they are another route's day.

### `age_hours` exists because prose goes stale

The recorded `detail` ends with *"read 0 minute(s) ago"*. That sentence was true when written.
Measured today it sat on a record made at 11:29 UTC while the clock read 15:10 — a description
that had walked away from the thing it describes. Anything that needs the age now asks the
field, which is recomputed on every read.

## 6. Part C — the issues, grouped

Every issue is still listed and the count still counts all of them. What changed is that they
arrive in three groups instead of one column:

```text
TRACK 1   affects Track 1 paper readiness
SHARED    the scheduler and the contract calendar serve both routes
LEGACY    reads legacy artefacts only — does not block Track 1 paper readiness
```

`scheduler` was chipped as **SCHEDULER**, which reads as a component. The chip answers a
different question — *whose problem is this* — so the word is now **SHARED**. Carried debt joins
the legacy group rather than taking a fourth heading, and an unrecognised scope falls into
Shared, where it is visible, rather than out of all three.

The Track 1 panel now carries one extra row naming where its blockers come from and where they
do not. Four of the five open issues are about the legacy route; nothing at panel level said so,
so the natural reading was that Track 1 was blocked by five things. It is blocked by two, and
those come from the gate registry — never from issue prose, which cannot open or close a gate
and has twice been written as if it could.

## 7. Part E — **a backend restart IS required**

The endpoint imports its reader *inside* the view function, which looks like it picks up code
changes per request. It does not: Python caches the module, so a backend started before this
stage keeps serving the old block. Measured against the running process, pid 6420:

```text
status           PASS
currency         USD
equity           250,817.91
age_hours        null      <- new
headline_usable  null      <- new
headline_reason  null      <- new
```

**Restart command** (not run — the operator's call):

```powershell
python monitor\ops.py restart --backend
```

Quiet window: any. The backend serves the dashboard and reads evidence; it places no orders and
holds no trading state. **The scheduler must not be restarted** and was not.

### The defect that measurement exposed in my own work

Read naively, `headline_usable: null` is falsy — and the page would have printed **"baseline
FAIL" over a funded, reconciled, PASSING account.** A worse lie than the one this stage set out
to fix, appearing the moment the page shipped ahead of a restart.

So the page distinguishes **absent** from **false**: a field the backend does not serve is not a
field the backend said no to. Absent means derive it here from what the old block does carry;
false means the backend decided, and its decision stands. Both halves are tested, and both go
red under mutation.

This is the same correction as Stage 5ZZE, where I inferred from file mtimes that a restart was
unnecessary and was wrong. This time the endpoint was asked.

## 8. Part D — the panel, and the overflow

The labels were already plain and the gate chips already wrapped (5ZZF). `Routetrack1_candidate`
is not what the page renders — label and value are separate block elements on separate lines;
it is what `innerText` concatenation looks like when read without the layout. Asserted rather
than assumed.

What *was* broken is width. Measured in a real browser:

```text
                          375px   720px   1440px
legacy headline            0px    17px     0px     <- pre-existing
Track 1 headline (new)    41px    59px     0px     <- mine, before the fix
Track 1 headline (fixed)   0px    17px     0px
```

Two `white-space: nowrap` rules met here — the headline figure and the note under it — both
written when the headline was `$50,408` and the note was one figure long. Both now wrap below
1100px. **Wrapping, not ellipsis:** a truncated money figure still looks like a money figure.

The residual 17px belongs to a tooltip pseudo-element, is identical whichever headline renders,
and does not scroll the page. Rather than bless it with a literal, the test asserts the
**property**: the Track 1 headline is never wider than the legacy one it replaced. The page's
own horizontal scroll is asserted separately, and is zero at 375, 720 and 1024.

## 9. Also fixed on the way: `from 76.8h ago ago`

`age()` already ends in "ago"; both branches carrying the legacy figure appended a second one.
Rendered on every poll since 5ZZF. No test looked past the number.

## 10. Tests

**36** in `scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py` — backend contract, live
reader, source-file invariants, and DOM in a real browser with the API stubbed. No broker is
contacted; nothing writes to the runtime tree; one test asserts that about the session it runs
in.

**9/9 mutations RED**, source-level in a subprocess, every file restored byte-identical, exit 5
never counted as red:

```text
the headline falls back to the stale legacy figure
an absent field is read as a refusal (the version-skew case)
an explicit false is overruled by re-deriving from status
a refused baseline is treated as usable
age is never computed
the shared scope reverts to a component name
the legacy group stops collecting carried debt
the equity card stops wrapping at narrow widths
the legacy return is written back onto the Track 1 card
```

The last one **failed to go red the first time**, and it was a hole in my test data rather than
in the code: the fixture's `total_return` was `null`, so both branches rendered `--` and the
test agreed with the mutation that deleted the guard. A non-null figure now makes the guard
provable. That is the second stage running where a mutation found a test proving less than its
name promised.

### Four pins restated, not weakened

Three in `monitor/test_realtime_dom.py` and one in the 5ZZF suite pinned the exact phrase
*"legacy runner state still shows"*. The clause is now *"Legacy runner state stale:"* — it says
**why** the figure is not the account, which Part B.5 asked for. The invariants are unchanged
and are what the tests now assert: the legacy figure appears under its own name, never without
its age, never with a doubled word, and — where it must be absent — nowhere outside its own
clause, checked by cutting that clause out and looking again.

Editing them needed care: the negative pin **contains** the positive one as a substring, so
replacing the positive first would have silently rewritten the negative into something that
still read plausibly and asserted something else.

### Suites run

```text
dashboard backend + realtime contract + realtime DOM + 5ZZH     303 passed
ops status + 5ZZE + 5ZZF + monitor/test_ops                      84 passed
```

**No pre-existing failures in any suite this stage ran.** The four adjusted pins were adjusted
by this stage's own change and are listed above; nothing was left red.

## 11. Part G — safety, before and after

```text
orders_possible                False        (unchanged)
blocking                       B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
TRACK1_ORDERS_APPROVED         unset
confirmation file              ABSENT
track1_runtime/orders          ABSENT
broker constructed by dashboard code   never — asserted over the page and its reader
restarts performed             0
runtime trading files written  none
```

Nothing in this stage touches order gates, scheduler behaviour, strategy rules or broker
execution. The dashboard reads; it has no path that writes.
