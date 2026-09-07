# Stage 5ZZM — Market View and Regime Monitor visual polish

**2026-08-27.** No orders · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · no orders
directory · confirmation untouched · **scheduler not restarted by me** · no broker call · no
strategy, threshold, window, schedule or gate change.

---

## Read this first — an external change that outranks the polish

A test from Stage 5ZZJ went red during this stage's regression run, and it is **not** a test
problem. It is the alarm it was written to be:

```text
scheduler pid       14344  ->  11332          restarted externally, not by me
track1_mode         track1-only-shadow  ->  legacy-only
legacy entry jobs   NOT REGISTERED  ->  REGISTERED
B1 gate             still closed
orders_possible     False (unchanged)
```

The B1 decision the operator signed on 2026-08-27 asserts *legacy is retired for this paper
login*. The running scheduler now registers legacy entry jobs on that same login, and the gate
goes on reading the recorded decision as true.

**This is exactly what the 5ZZJ preview said would happen:**

> Legacy is dormant because of a command-line flag, not because it has been retired: a restart
> without `--track1-only-shadow` registers its entry jobs again, and this recorded decision
> would go on reading as true.

Nothing unsafe can execute — `PAPER_SHADOW_EVIDENCE` still blocks, the approval variable is
unset, and no order path is armed. But the signed claim and the running configuration now
disagree, and that is worth a decision rather than a footnote.

**I left that test red on purpose.** It is the only thing on the route that notices this, and
adjusting it to pass would remove the alarm while leaving the condition.

---

## Part A — before, measured in a browser

```text
                          375px            720px            1440px
page horizontal overflow   0px              0px              0px
chart height per tab       [240,240,240]    [240,240,240]    [320,320,320]   spread 0.0px
chips in summary           0                0                0
legends                    0                0                0
raw phrase visible         entry levels not exposed by sleeve evidence yet   (all widths)

summary  "Complete - 3/3 slots observed - no signal - entry levels not exposed"
footer   "entry levels not exposed by sleeve evidence yet · Latest bar 15:55"
regime   "REGIME | Calm as of 2026-08-26 · read 0.3h ago | LABEL CHECK | PASS · 1761
          compared, none changed | SCORE | not exposed by model | SHIFT THRESHOLD | n…"
empty    "NO BARS TO SHOW / no persisted bars"
```

The layout was already sound. What was rough was everything a reader actually reads: a
comma-joined sentence where the page uses chips everywhere else, the same levels phrase printed
**twice** on one panel, and a regime row quoting a log line.

## Part A — after

```text
                          375px            720px            1440px
page horizontal overflow   0px              0px              0px
market view container      0                0                0
chart / summary            0 / 0            0 / 0            0 / 0
regime panel / strip       0 / 0            0 / 0            0 / 0
chart height per tab       [240,240,240]    [240,240,240]    [320,320,320]   spread 0.0px
chips in summary           5                5                5
legends                    2 (markers + regime)
raw phrase visible         none

summary  NO SIGNAL · 1 slots · Latest 15:55 ET · Strategy levels unavailable ·
         Stored session 2026-08-26           (five chips)
footer   ""                                  (empty — the chips already said it)
regime   Calm | as of 2026-08-26 | checked 0.3h ago | LABEL CHECK | Label check passed |
         SCORE | Score not published | SHIFT THRESHOLD | Shift threshold not published
empty    "NO BARS AVAILABLE FOR THIS SESSION / Latest stored session 2026-08-26."
```

## What changed visually

**The summary became chips**, in the page's own chip idiom — `3px 6px`, a 1px border in
`currentColor`, radius 3, 700/11 mono, uppercase — the same shape `.issue-status` and
`.issue-origin` already wear. No second badge language. Tone carries meaning rather than
decoration: bad is a refusal, warn is incomplete, good is a signal, live is in progress, muted
is a fact with nothing to act on.

**The chart got room and a lane.** Left padding went from 8px to 34px, so candles no longer run
into the edge, and the slot markers moved off the plot floor onto their own baseline above the
time axis — which is what turns them from stray ink into a row of outcomes. Candle width is now
`2.5–9px`: readable at 1440, still distinct at 375. The window band is labelled `Window`, but
**only when the band is wide enough to hold the word without sitting on a candle**; below that
it stays an unlabelled tint.

**A marker key** sits at the foot of the chart — `No signal · Signal · Refused · No record ·
Not yet`. It is laid *over* the chart's fixed box rather than added below it, so a sleeve with
bars and one without still occupy the same height. The tab-switch spread is 0.0px.

**The regime label became the anchor**: 22px, coloured by regime, with `as of 2026-08-26` and
`checked 0.3h ago` beside it. Never shown alone — "Calm" from a reading nobody refreshed in
three days is a different statement from "Calm" from this morning.

**The 60-day run is quieter** (10px tall, 80% opacity) with a colour legend above it and the
recent days spelled out underneath. Sixty unlabelled cells at full strength read as a barcode.

## What copy changed

| was | now |
|---|---|
| `entry levels not exposed by sleeve evidence yet` | **`Strategy levels unavailable`** |
| — | tooltip: *The strategy has not published entry/reference levels for this sleeve yet. The chart only renders prices and slot outcomes.* |
| `splice_result` | `Data join` |
| `not_exposed_by_sleeve` | `Not published` |
| `provider_lag` | `Data delayed` |
| `gate_refused` | `Gate refused` |
| `PASS · 1761 compared, none changed` | **`Label check passed · 1,761 days compared · no drift`** |
| `not exposed by model` | **`Score not published`** / **`Shift threshold not published`** |
| `NO BARS TO SHOW / no persisted bars` | **`No bars available for this session`** / `Latest stored session 2026-08-26.` |

The translation happens in one place, and an **unmapped** token is shown with its underscores
removed rather than folded into "unknown" — a phrase nobody has translated should be visible so
somebody translates it, not swallowed where it disappears.

The footer is now empty on the ordinary path. It used to restate the levels note the chips
carry, so one sentence appeared twice on one panel.

## Still unavailable, because nothing publishes it

```text
entry / stop / target / reference price   every rule reads source: not_exposed_by_sleeve
regime score                              the model returns label strings only
regime shift threshold                    likewise
distance to a regime shift                nothing to measure against — and the panel says so
today's bars                              not persisted until the daily append
```

No distance-to-shift is implied anywhere, and a test asserts that.

## Three defects this stage introduced and then measured out

**The regime panel overflowed by 178px** at 720px and 111px at 1440px. The new anchor is a grid
child, and a grid child without `min-width: 0` refuses to shrink below its content — this one
holds a 22px figure plus two clauses. Fixed, and it now spans the full row because it is the
panel's heading rather than one fact among several.

**Two tooltips pushed their panels sideways.** The rightmost cell of a fact grid, and the last
chip in the summary row, both open their bubble past the panel edge — 11px and 85px measured.
The page already solves this for the header zones (`.header-zone:last-child .has-tip::after {
left: auto; right: 0 }`), so the same flip was applied rather than a second remedy invented.

The 85px one is instructive: it appeared **only after** the shorter copy let the chips reflow
onto fewer lines. This class of overflow moves when the text does, which is why it is measured
at three widths after every copy change rather than once.

**The DOM fixture was pinning the old phrase.** It hardcoded
`entry levels not exposed by sleeve evidence yet`, so the layout probe reported the old wording
as still visible after the backend had stopped emitting it. It now reads the backend constant,
and cannot drift from the copy the page actually receives.

## Tests

**73** in the market-view suite (26 added by this stage), covering: chips replace the sentence,
the status-chip vocabulary, a data refusal outranking everything, the levels chip and its
tooltip, the footer not repeating a chip, the marker legend and its lane baseline, the window
label, the empty-state wording, the stored-session chip reading as muted metadata, the regime
anchor being larger than a fact value, plain-English label check including its drift and
not-run branches, both "not published" fields and their tooltip, no distance-to-shift implied,
the regime legend, and the run being quieter than the recent row.

**Six 5ZZL tests restated**, all copy changes this stage made deliberately — each keeps its
invariant:

| test | invariant kept |
|---|---|
| levels are not exposed and say so | the summary still SAYS the levels are missing |
| no raw field names in visible labels | the translation TABLE is excluded from the scan; the DOM test proves the render |
| empty state is intentional | still one intentional state, still no SVG, and now names the stored session |
| a provider refusal is shown | the reason is still FINDABLE — chip plus tooltip — rather than a sentence |
| levels said in words | still said, in the new words |
| regime shows label and verification | the absent score is still NAMED |

### Suites

```text
dashboard backend + realtime contract + realtime DOM + ops
  + 5ZZL/M + 5ZZH + 5ZZK + 5ZZJ                                440 passed, 1 failed
```

**The one failure is the external scheduler-mode change described at the top**, not a defect in
this stage. No other test was left red, and nothing was weakened.

## Part F — safety, before and after

```text
orders_possible                False -> False
track1_blocking                ['PAPER_SHADOW_EVIDENCE'] -> unchanged
confirmation                   True -> True, untouched by this stage
TRACK1_ORDERS_APPROVED         unset
track1_runtime/orders          ABSENT
scheduler restarted by me      no
broker order calls             0
strategy / gates / order wire  untouched
```

### External changes recorded

```text
scheduler process   pid 14344 -> 11332, and its mode changed to legacy-only
                    NOT done by this stage; see the section at the top
```

**Backend restart** is still required for `/api/v1/track1-market-view` — that was true from
Stage 5ZZL and this stage did not change it. The copy changes in the backend module ride along
with it. Not run:

```powershell
python monitor\ops.py restart --backend
```
