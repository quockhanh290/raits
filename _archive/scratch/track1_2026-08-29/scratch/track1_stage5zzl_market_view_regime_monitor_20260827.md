# Stage 5ZZL — Track 1 Market View and Regime Monitor

**2026-08-27.** No orders · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · no orders
directory · confirmation unchanged · scheduler not restarted · no broker call · no strategy,
threshold, slot or gate rule touched.

---

## The two findings this panel had to be built around

Both were measured before a line of UI was written, and both change what the panel can honestly
show.

### 1. Today's bars are not persisted anywhere

```text
MNKD  2,045,063 rows   last bar 2026-08-26 17:45   rows for 2026-08-27: 0
MNQ   3,359,919 rows   last bar 2026-08-26 17:44   rows for 2026-08-27: 0
MES   3,372,388 rows   last bar 2026-08-26 17:44   rows for 2026-08-27: 0
```

The store is appended once a day; the live half of each session is spliced **in memory** inside
the slot process and thrown away. So on 2026-08-27 the overnight sleeve had fetched and used
1,910 of today's bars and **not one of them survives anywhere on disk**.

A chart captioned "today" would therefore be empty on every normal day. So each sleeve shows the
most recent session the store actually covers and **says which session that is**, in the summary
line and in the payload. Substituting it silently would make a stale chart look current.

### 2. The strategy publishes no prices, and the model publishes no score

Every rule in the signal diagnostics reads:

```json
{"rule": "breadth_down_count", "value": null, "source": "not_exposed_by_sleeve",
 "detail": "evaluated inside the sleeve detector; value not returned yet"}
```

There is **no entry, stop, target or reference price anywhere in the evidence**. And
`label_regimes` returns a series of strings — there is no score, probability or shift threshold
underneath the label.

So the panel says `entry levels not exposed by sleeve evidence yet` and
`not exposed by model`, in those words, rather than approximating either. A line drawn at a
level nobody published is a line an operator would trade against.

---

## Part C — the charting dependency, and why there isn't one

**Lightweight Charts was NOT added.** Measured first, as the stage asks:

```text
package.json / node_modules / build step        NONE anywhere in the tree
scripts loaded by the realtime page             2, both first-party
pages loading an external library               1 — chart-forward.html, Chart.js from a CDN
                                                and its consumer guards `if (!window.Chart)
                                                return` with an inline-SVG fallback
```

The repo has a de-facto no-external-dependency policy on the operator page, and the one place it
bends already treats the library as optional.

**The tradeoff, stated plainly.** Adding a CDN `<script>` to *this* page is different from adding
one to a report page: this is the page an operator watches a live trading route on, and a
third-party host becomes a dependency at exactly the moment something is going wrong. Vendoring
the library instead means committing a third-party blob into a repo that has none — a
supply-chain decision for the owner, not for this stage.

So the chart is **first-party SVG**, in the same style as the sparkline already in
`shared/live.js`. The cost is real and is the whole of it: crosshair, tooltip, price scale and
time axis are hand-drawn here — roughly 200 lines a library would have provided. If you would
rather vendor Lightweight Charts, say so and it is a small swap; the payload shape already
matches what it consumes.

---

## Part A — before state, measured

```text
window coverage 2026-08-27
  global_nkd      22/22  complete     no_signal
  roska4_stress   18/24  incomplete   no_signal
  roska4_swing     0/23  unobserved   —
  roska4_calm       0/1  incomplete   no_signal

signal rows            63 for the day
  global_nkd      22 NO_SIGNAL                latest TRACK1_NKD_0255 @ 02:55
  roska4_stress   18 NO_SIGNAL + 7 REFUSED    latest TRACK1_STRESS_1230 @ 12:30
  roska4_swing    10 SLOT_REFUSED             latest TRACK1_SWING_1405 @ 14:05
  roska4_calm      6 SLOT_REFUSED             latest TRACK1_CALM_OBSERVE_1002 @ 10:02

regime verify   PASS · 1,761 labels compared through 2024-12-31 · 0 changed
                checked 2026-08-27T09:41:12Z
regime fields   label only. No score, no probability, no threshold anywhere.
SPY daily file  date, close — and NO label column
```

**A live correction to Stage 5ZZI.** That stage recorded every fetch from 03:05 ET returning
zero. The 12:30 Stress observation now reads `live_rows_fetched: 2490, splice_result: ok` — **the
feed recovered during the Stress window.** The outage was bounded, not ongoing.

## Part B — the payload

New endpoint `/api/v1/track1-market-view`, deliberately **not** a block on `/track1-runtime`:
this one slices instrument stores and the runtime endpoint is polled on a short interval by a
page that needs it to stay cheap.

| field | source |
|---|---|
| `bars` | the instrument parquet, day-sliced, resampled to 5m, clipped to the sleeve context range, cached by (path, mtime, day) |
| `slots` | the signal-diagnostics rows, married to the slot table so slots that have not fired appear as `future` |
| `levels` | scanned from `rule_checks` where `source == "measured"` — **empty today**, and written as a scan so the day a detector publishes a price the line appears without anyone editing the file |
| `data_status` | the data-observation row, including the `provider_error` Stage 5ZZI wired in |
| `regime` | the recorded regime label, never computed in the request |

Live output:

```text
NKD     complete    38 bars  22 slots {no_signal: 22}
        Complete · 22/22 slots observed · no signal · entry levels not exposed · bars from 2026-08-26
Stress  incomplete  39 bars  24 slots {no_signal: 18, refused: 6}
        Incomplete · 18/24 slots observed · no signal · 6 refused · entry levels not exposed · bars from 2026-08-26
Swing   waiting     80 bars  23 slots {future: 22, refused: 1}
        Waiting · window has not opened · 23 slots scheduled · no signal · 1 refused · bars from 2026-08-26
```

### The regime is recorded, not computed on request

`label_regimes` takes **8.54 seconds**. A dashboard endpoint calling it would hang the operator's
page for that long on the first poll after every SPY refresh and on every cold backend. So it
follows the pattern the rest of the route already uses — `track1_b1`, `track1_account_baseline`
and `regime_verify` are all shaped this way: a probe measures and writes down what it saw, and
the reader reads what the probe wrote.

`global_index/track1_regime_record.py` is that probe. It fails to **UNKNOWN**, never to a label:
`Calm` is the permissive regime, and a labeller that could not run must not read like one that
answered "safe". Its record carries the fit window that produced the label, because a label
without that is a label nobody can reproduce — the `FreezeRecord` mistake this project already
made once.

## Parts D–F — the panels

Two panels, deliberately separate. Folding the regime into a chart tab would say they answer the
same question about the same window; one is intraday and per sleeve, the other daily and
route-wide.

The market view carries three tabs, one 5-minute chart with a shaded window band, wrapping slot
markers, crosshair and O/H/L/C tooltip, right-side price scale and bottom time axis. Marker
vocabulary keeps `future` (hollow) distinct from `missed` (hollow, red) — a slot that has not
fired is not a slot nobody recorded. It does **not** dump rule checks; the job panel already owns
that detail.

### Three defects caught by measuring rather than by looking

**Two definitions of "observed" on one page.** The summary counted slot markers and printed
`24/24 observed` for a sleeve the window ledger recorded as **18 of 24** — a refused slot leaves
a row here and is not an observation there. The count now comes from the ledger; the markers only
draw.

**"Data refused" over a working feed.** Any `provider_reason` was treated as a refusal, so Swing
— which had simply not opened yet — was labelled as a data problem. `ok is None` now means nobody
looked, and only `ok is False` reads as refused.

**The regime rows rendered unstyled.** The fact-row CSS was scoped to `#track1Facts`, so the
regime panel reused the markup and inherited none of it: label `inline` at 14px instead of
`block` at 11px. On the page that produced **`RegimeCalm as of 2026-08-26`** — label and value run
together into one word. Caught by comparing computed styles against the Track 1 panel, not by
looking at a screenshot. Both selectors are now named in one rule.

## Browser-measured layout

```text
                       page overflow   market view    chart      regime panel
  375px                      0px       375×451 / 0    343×240    375×304 / 0
  720px                      0px       720×407 / 0    668×240    720×197 / 0
 1440px                      0px       987×489 / 0    935×320    987×197 / 0

chart height per tab (NKD / Stress / Swing)   375px [240,240,240]   1440px [320,320,320]
regime row text   REGIME | Calm as of 2026-08-26 · read 0.3h ago | LABEL CHECK | PASS · 1761
                  compared, none changed | SCORE | not exposed by model
```

Zero horizontal overflow at every width; the chart panel does not move when tabs change, and the
empty state occupies the same box so it does not move either.

## Values NOT exposed, and shown as such

```text
entry / stop / target / reference price     every sleeve — no rule publishes a number
regime score                                the model returns strings
regime shift threshold                      likewise
distance to a regime shift                  nothing to compute it from
today's bars                                not persisted; the stored session is named instead
```

## Frontend computes nothing

Asserted, not claimed: the added block is scanned for `label_regimes`, `benchmark_daily`,
`decode(`, `atr(`, `stdev(`, `Math.exp`, `Math.log` and level arithmetic, and every drawn value
is addressed out of the payload. Timestamps are split as strings rather than parsed with `Date`,
because these are wall-clock on the sleeve's own exchange clock and handing them to a `Date`
would reinterpret them in the viewer's zone — the thirteen-hour class of error this project has
already paid for once.

## Tests

**47** in `scratch/test_track1_stage5zzl_market_view_regime_20260827.py` — backend shape, ranges,
bar integrity, level refusal, slot vocabulary, data tri-state, regime record staleness, plus DOM
in a real browser at three widths. No broker contacted; nothing writes to the runtime tree.

Three were wrong the first time and each was my fault, not the code's: a whole-file search for
`HMM` that matched pre-existing *prose* rather than a computation; an NKD fixture generating
09:30 bars for a 01:10–02:55 window so no bar fell inside the band; and an assertion pinned to
rendered casing when CSS uppercases the empty-state heading. All three now scope to the block
this stage added or compare case-insensitively.

Also repaired: the render calls landed inside the **issue-row click handler** rather than the
render pipeline, so the panels only appeared after clicking an issue. Found because the DOM tests
timed out waiting for tabs that were never drawn — a code-read would have shown a call in the
file and looked correct.

Two registrations, both the existing tests doing their job: the new endpoint had to be added to
the realtime endpoint contract, and to the shared DOM fixture (an unstubbed route shows up as a
console 404 and fails the healthy-page test). The contract's list-slot was pinned to `sleeves`,
which is a dict — caught immediately and repointed at `regime.recent` / `regime.context`.

One restatement: 5ZZH's `test_track1_blockers_come_from_the_gate_registry` pinned B1 as blocking.
Stage 5ZZK closed it, so the test now asks the registry for whatever is blocking and requires
something to compare against.

## Safety, before and after

```text
orders_possible                False -> False
track1_blocking                ['PAPER_SHADOW_EVIDENCE'] -> unchanged
confirmation                   True -> unchanged (placed by the operator in 5ZZJ)
TRACK1_ORDERS_APPROVED         unset
track1_runtime/orders          ABSENT
scheduler restarts             0
broker calls                   0
strategy / thresholds / slots / gates / SEND wire   untouched
```

**Backend restart required** for the new endpoint to be served — `/api/v1/track1-market-view` is
a new route and the running process does not have it. The page handles its absence: the fetch is
independent and a failure leaves every other panel exactly as it was.

```powershell
python monitor\ops.py restart --backend
```

Not run. Scheduler must not be restarted and was not.

### Runtime files written by this stage

```text
global_index/track1_runtime/regime_label/regime_label_20260827.jsonl   NEW — the regime probe
```

That is a new evidence directory, written by the recorder this stage adds. No trading file was
touched. Other runtime files changing during the stage are the live scheduler's own work and are
external.
