# Stage 5ZP — the diagnostics panel stops looking like three different pages

**2026-08-26, ET 04:30–05:40.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **nothing restarted** · no runtime evidence, audit record,
checkpoint, book, trade log or order journal touched · no strategy decision, threshold, cap or
backtest identity changed · **nothing recomputed in a diagnostics path**.

```text
UTC 2026-08-26 09:40 · ET 2026-08-26 05:40 EDT · Calgary 2026-08-26 03:40 MDT
```

---

## The ten answers

| | |
|---|---|
| 1. runtime/live file changed? | **no** |
| 2. orders still impossible? | **yes** — three blockers |
| 3. what changed in the chip? | text, class and position — three separate faults (§2) |
| 4. details inside the block? | **yes**, and asserted structurally rather than by looking |
| 5. Track 1 panel consistent? | **yes** — same shape as the schedule facts beside it |
| 6. new rule values exposed? | **no, and deliberately** (§5) |
| 7. anything recomputed? | **no** |
| 8. mobile / overflow? | **passed** at 380, 720 and 1024 px, expanded |
| 9. data proof displays? | **yes**, all three states, one line inside Operational |
| 10. what remains? | five items, unchanged |

---

## 1. Baseline

`orders_possible=False`; blockers `B1_broker_account_or_legacy_retirement`,
`PAPER_SHADOW_EVIDENCE`, `REGIME_LABEL_VERIFICATION`. Scheduler 18780, backend 48760 — the pids
from your 02:09 restart, untouched by me.

## 2. The chip — three faults, not one

```js
class="job-signal-chip signal-…"  →  "Signal NO SIGNAL"
.job-signal-chip { grid-column: 1 / -1; border: 1px solid currentColor; … }
```

- **The text doubled itself.** *Signal* was already implied by the chip's position beside
  RUNNER and COMPLETED, which made the longest chip on the row the least informative.
- **It was a bordered pill of its own invention** while every other chip on the page is
  `.event-status`, so it read as a different *kind* of object.
- **`grid-column: 1 / -1`** is literally what put it on its own line. That is the whole of the
  "on its own row, too large" complaint — one property.

It now renders as `.event-status signal-<tone>` carrying only its label, emitted **inside**
`<span class="job-badges">` beside the other two. The tooltip is unchanged and still composed
by the backend, so the page and the journal cannot drift.

Measured in the browser: a Track 1 row and a row with no chip at all are now the same height to
within two pixels.

## 3. The expanded panel

The two sections were concatenated **after** `renderJobDetails(...)`:

```js
renderJobDetails(job, snap, presentation) + operationalDetails(job) + signalDetails(job)
```

— siblings of the panel, not part of it, which is exactly why they rendered as loose text
below the structured evidence. They now sit inside `<div class="job-detail">`, after the
EVIDENCE / RESOLUTION block, in the `.job-section` style the IMPACT and ACTION blocks already
use.

Asserted structurally rather than by reading: a test counts `.job-section` nodes that are **not**
inside `.job-detail` and requires zero, and another checks the DOM order so the sections read as
the end of one panel rather than an interruption of it.

## 4. A misleading sentence, found on the live journal

The brief asked to avoid blaming freshness when no candidate existed. It was not hypothetical.
Measured against the real 2026-08-26 night journal — 22 `NO_SIGNAL` rows, `candidates: []`,
`freshness_allow: false` — every one of them printed:

```text
First rule that failed: Freshness check.
```

Freshness stopped nothing. Nothing reached admission for it to stop. A rule that guards
**admission** has nothing to say about a slot that admitted nothing, and naming it as the first
failure names a cause that did not act.

Now, for the admission-layer rules only, and only when the candidate count is zero:

```text
Freshness check: measured as not allowing admission, but no candidate reached admission.
```

The distinction is narrow on purpose, and two tests hold the edges: a rule that **did** block a
candidate is still named as the first failure, and a **setup** rule that failed with no
candidate is also still named — because there, the failed rule is precisely why no candidate
exists. A fourth test runs the whole real journal through the composer and requires no row to
blame freshness.

## 5. Rule exposure — nothing new, and that is the finding

The brief asked to expose values *already computed during detection*. I inventoried them and
**exposed none**, because there are none to expose: after Stage 5ZD every sleeve setup rule
still returns `not_exposed_by_sleeve` — 210 of 324 checks on the live journal. The detectors do
not return their measured values, and the only way to produce a number here would be to compute
it in the diagnostics path.

That is forbidden by this stage's own constraints and by the reason behind them: a second
implementation beside the one that trades would disagree on exactly the day it mattered, and
the diagnostics copy would be the one that looked right.

So the panel keeps the single honest sentence 5ZE already gave it — *"Detailed setup
measurements are not exposed yet"* — rather than a list of variable names with no numbers. A
test requires that sentence and caps the section at four lines, so a wall of UNKNOWN cannot
come back.

**Making the detectors return their values is real work in the strategy layer**, not a
dashboard change, and it is recorded as such rather than half-done here.

## 6. The Track 1 Runtime panel

`Route track1_candidate` and `Orders possible no` ran together because label and value were
inline siblings with nothing separating them — `#track1Facts` only ever set `min-width: 0`.

The panel now uses the same shape as `.schedule-fact` next door: a small uppercase label on its
own line, the value beneath it, wrapping allowed. No new card, no new colours, existing tokens
only.

The blocker list was the one value that could grow. It renders as wrapping chips in plain
English, with the raw id kept in the tooltip:

```text
BLOCKING GATES
  Account / legacy retirement gate   Shadow evidence gate   Regime label verification gate
```

Nothing is hidden — the exact identifier is one hover away — but nothing has to be decoded at a
glance either. Measured: with three gates the panel's `scrollWidth` does not exceed its
`clientWidth`.

## 7. Data proof

Already one line inside Operational from 5ZO. All three states are rendered and tested:

```text
Data: IBKR · NKD · 1186 live bars checked · last 02:55 ET · splice OK
Data proof: not recorded by this slot version
Data refused: overlap mismatch
```

A test also requires exactly one `Data` line per job, so a second source cannot start adding
its own.

## 8. Tests

**31 tests**, `scratch/test_track1_stage5zp_dashboard_polish_20260826.py` — real chromium, real
page, API stubbed, using the harness `monitor/test_realtime_dom.py` already provides.

Structural throughout, because a substring check would pass on a chip rendered in the wrong
place: *is the chip a child of `.job-badges`*, *is its computed `grid-column` no longer
`1 / -1`*, *how many `.job-section` nodes are outside `.job-detail`*, *does the badge group
overhang its row*, *does the document scroll horizontally*. Overflow is checked at three widths
with the panel expanded, and the page is required to log no console error.

Four tests are not browser tests at all. The DOM test for the freshness wording renders a
fixture, so it would stay green if the backend regressed — the backend composer is therefore
asked directly, including once against the real journal on this machine.

## 9. Two pinning suites updated, and why that is not weakening them

Sixteen tests in 5ZD and 5ZE pinned the old chip — its class, its text, and its own-row
property. All three are what this stage changed, deliberately, so they were updated rather than
deleted.

One of them got **stronger**. `test_41_the_chip_reuses_the_existing_visual_language` used to
check that a bespoke pill had borrowed three properties from the dashboard's look. It now
checks that the chip *is* the dashboard's chip and that `.job-signal-chip` appears nowhere in
either file. `test_46` was inverted for the same reason: it asserted `grid-column: 1 / -1`,
which is the defect, so it now requires its absence.

And one test failed for a reason worth recording. `test_47_the_dashboard_does_not_compose_the_wording_itself`
searches the renderer for chip labels — and went red because **my new comment quoted the old
label to explain why it had been removed**. Substring-over-prose, on a test built to catch a
different trap. It now strips line comments first, so it reads what the renderer emits rather
than what it says about itself.

## 10. Regression

**572 passed, 0 failed** — 5ZP, 5ZO, 5ZE, 5ZD, 5ZM, 5ZN, and every browser suite the repo has:
`test_realtime_dom`, `test_realtime_skin`, `test_realtime_contract`, `test_dashboard_backend`
and `test_paper_dom`.

## 11. Files changed and liveness

| file | change |
|---|---|
| `global_index/dash/realtime/realtime.js` | chip text, class and placement; both sections inside the panel; plain-English gate chips |
| `global_index/dash/realtime/realtime.css` | chip uses `.event-status`; `#track1Facts` label/value layout; wrapping gate chips |
| `global_index/track1_signals.py` | admission-layer rules reported as measurements, not causes, when nothing was admitted |
| `scratch/test_track1_stage5zp_…py` | new, 31 tests |
| `scratch/test_track1_stage5zd/5ze_…py` | sixteen pins updated, one made stronger, one prose check repaired |

**No runtime file changed.** Coverage, signals and audits carry their baseline mtimes; the
checkpoint and book carry 00:55 from the live NKD close; `data_observation/` still does not
exist and will be created by the next slot. No screenshots were produced.

**Nothing restarted.** The dashboard's JS and CSS are static assets served fresh on reload, so
the visual changes are live at the next page load without a restart. The one backend change —
the signal wording — lives in `track1_signals`, which the job reader imports at module load, so
**the running backend still composes the old sentence until it is restarted**. Everything else
in this stage is browser-side and needs nothing.

## 12. What remains before paper

| | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 — separate account, or a proven-flat legacy book | **operator decision** |
| 3 | five clean judgeable days | **time**, once 1 is fixed |
| 4 | the regime gate's first PASS | **time** — `--verify-strict` is live |
| 5 | broker stop proof, partial fills, an order in flight across a restart | **paper only** |

Unchanged by this stage, which touched no gate. Two smaller items are now recorded rather than
open questions: the sleeve detectors do not return their measured values (§5), and nothing
records whether the provider's last bar was still open (5ZO). Neither blocks anything; both are
explainability, and both are named where a future stage can pick them up.
