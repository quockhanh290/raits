# Stage 5ZE — job view: health first, signal chip second

**2026-08-25, ET 12:05–12:55.** Dashboard, backend reader and one label mapper only · no
strategy change · no scheduler change · no order/paper gate change · no runtime evidence write ·
no IBKR call.

```text
UTC 16:55 · ET 12:55 EDT · Calgary 10:55 MDT · Tokyo 01:55 JST (26th)
```

| | |
|---|---|
| scheduler restarted | **no** — pid 48604, unchanged since 01:07 ET |
| backend restarted **by me** | **no** — see §7 |
| runtime files touched | **no** — production wrote its own signal rows, I wrote none |
| paper/order gates changed | **no** — `orders_possible=False`, both blockers unchanged |

---

## Part A — what the Job View already showed, measured

Read from the real backend payload and the real render path, not assumed.

The job dict a Track 1 strategy slot produced carried exactly: `status`, `started_at`,
`ended_at`, `duration_seconds`, `reason`, `impact`, `action`, `diagnostics`, `events`,
`event_counts`. The expanded panel rendered Started / Completed / Duration / Outcome, a
Problem line, IMPACT and ACTION, an evidence list, and EVIDENCE / RESOLUTION.

**The evidence list is always empty for a shadow slot** — it is built from trade and protection
events, and a shadow slot emits none.

| # | field | already visible? | where | operator-readable? | action |
|---|---|---|---|---|---|
| 1 | scheduler status: ran / missed / failed | **yes** | collapsed `.event-status` badge + expanded *Outcome* | yes | none |
| 2 | runtime refusal: freshness, live frame, splice, bar provider, too late, stale, overlap | **NO** | nowhere on the job at all | — | **added** |
| 3 | timing: duration | **yes** | expanded *Duration* | yes | none |
| 3b | timing: 300 s breach | **NO** | nowhere — a number with nothing to judge it against | — | **added** |
| 4 | ledger / window coverage: slot observed | **NO** | day-level counts in the Track 1 panel only | not per job | **added** |
| 5 | audit verdict | **partly** | Track 1 panel, day and sleeve level | not per job | **added per job** |
| 6 | checkpoint / book effects | **partly** | Track 1 panel, present/absent for the day | absence not explained | **added**, as an expectation |

So an operator could see *that* a slot ran and for how long, and **nothing** about whether the
freshness gate passed, whether the live frame was refused, whether the evidence row the audit
counts was written, or whether the duration was anywhere near its budget.

---

## Part B — the Operational block

Added to the **expanded** panel, above Signal. Every field is read from evidence that already
existed; nothing new is computed about the strategy.

```text
OPERATIONAL
  Ran at 11:55:00 ET, duration 3s.
  Runtime within the 300s budget.
  Ledger row written.
  Freshness check passed.
  Live frame passed.
  No checkpoint or book write expected in shadow.
```

and when a slot was refused:

```text
OPERATIONAL
  Ran at 01:10:00 ET, duration 3s.
  Runtime within the 300s budget.
  Ledger row written.
  Slot refused before strategy evaluation.
  Reason: Runtime gate refused the slot. (Session bars incomplete, Bars are stale)
  No checkpoint or book write expected in shadow.
  Window audit for global_nkd: FAIL.
```

Three details worth naming:

**The timestamp is ET.** The stored field is UTC, and a panel that printed it would make the
operator convert in their head — the habit this project lost an hour to yesterday.

**It falls back to the window-coverage ledger** when no signal row exists. That is not a corner
case: 33 slots ran before the signal journal existed, and they still get full operational
diagnostics from the ledger.

**"No checkpoint or book write expected in shadow" is said out loud**, so an absence is not read
as a fault.

---

## Part C — the signal chip

One chip, in the existing `.event-status` language — 3px/6px padding, 1px `currentColor`
border, 3px radius, mono 700 11px — placed **inside the existing job row**, on the row below the
job name and summary, spanning the row (`grid-column: 1 / -1`). No new column, no new card, and
the schedule table is not wider.

| chip | tone | tooltip |
|---|---|---|
| NO SIGNAL | neutral | Slot ran and reached the strategy layer; no setup matched. |
| RAW SIGNAL | watch | A setup matched before admission/cap checks. |
| REJECTED | warn | A setup matched but was rejected by an admission, cap, or switch rule. |
| ACCEPTED SHADOW | good | Setup passed admission in shadow; no order was attempted. |
| REFUSED | muted | Slot did not reach strategy evaluation; see operational details. |
| MISSED | bad | Expected slot did not run. |
| NO DIAGNOSTICS | muted | Job ran before signal diagnostics existed, or no signal row was written. |

The tooltip is required, not decorative: a seven-state chip with no explanation is seven colours
nobody can act on. It uses the page's own `.has-tip[data-tooltip]` pattern with `tabindex="0"`.

**The chip replaced the Stage 5ZD sentence.** That sentence pushed every row to two lines
whether or not anything had happened, which is exactly what makes a list of thirty rows
unscannable.

---

## Part D — operator language, and what is deliberately hidden

The Stage 5ZD expanded block rendered `gate_allow`, `freshness_allow`, `breadth_down_count`,
raw JSON thresholds and a column of `UNKNOWN`. All of it is gone from the page.

```text
SIGNAL                          SIGNAL
  No setup matched this slot.     Setup matched.
  The slot reached strategy       Rejected by: Position cap.
  evaluation.                     MNQ SHORT · x7 · entry 20,100.00 ·
  Detailed setup measurements       stop 20,160.00 · risk $420
  are not exposed yet.
```

**Hidden until debug — shipped, never rendered.** `signal.debug` still carries `rule_checks`,
`primary_failure`, `params_hash`, `data_source_identity`, `freshness_allow` and the raw detail
string. There is **no code path in the page that renders it**. It travels so it is not lost, and
a future stage can surface it once the sleeves return measured values.

Why hidden rather than mapped-and-shown: after Stage 5ZD every sleeve rule comes back
`not_exposed_by_sleeve`, so a mapped list would be thirty human names with no numbers beside
them — a longer way of saying nothing, burying the two lines that do carry information. One
sentence says the same thing honestly: *"Detailed setup measurements are not exposed yet."*

**REFUSED, MISSED and NO DIAGNOSTICS do not repeat the runtime evidence.** They say *"See
Operational details"*, because two copies of the same fact are two things to reconcile and only
one of them ever gets updated. A test asserts the refusal sentence appears exactly once in the
expanded row.

---

## Part E — the label mapper

One owner, in the backend beside the summary composer, so the page and the journal cannot drift.
`gate_allow` → *Runtime gate*, `freshness_allow` → *Freshness check*, `family_cap` → *Family
cap*, `overlap_disagreement` → *History/feed overlap disagreement*, and so on for every declared
rule, every refusal code and every layer.

An **unmapped** name falls back to the raw name rather than an empty cell — a missing label
should look wrong on the page so somebody adds one. A test asserts every declared sleeve rule
has a label.

---

## Part F — the Track 1 Runtime panel

Reduced to counts:

```text
Signals today    no signal 9 across 1 sleeve(s)
```

The Stage 5ZD version printed a per-sleeve latest status, slot time, per-status counts and a
trailing "latest accepted" clause — a one-line fact row that grew all day. Per-slot detail
belongs to the job view.

---

## Part G — tests

**64 tests. 26 mutations, all red.** Eleven of the tests drive a **real chromium** against the real page
with the API stubbed, because `assert "string" in file` is how every finding in the earlier
dashboard audit got through.

The three the stage named all bite: removing the chip (M1), emptying a tooltip (M2), removing an
operational field (M3). So do the ones that put developer material back — raw names (M4), JSON
thresholds (M5), the wall of unknowns (M6), the rule grid (M7), and the raw names reaching the
browser (M8).

### Two mutations that found my TESTS wrong

**M24 — a chip given `min-width: 900px` on a 380px screen.** My first overflow test measured
`document.scrollWidth`; the chip sits in a scrolling container, so the page never scrolled and
the test passed. I switched to the project's own element-level clipping detector and **it stayed
green too** — correctly, because that detector deliberately allows content to be wide inside a
scrolling ancestor.

Both checks were answering *"does the page overflow?"*. The claim this stage actually made is
*"the chip does not widen its row"*, which is a different question. The test now measures the
chip's own bounding box against its row's.

Two wrong tests before the right one, and each time the code was fine — the assertion was
aimed at the wrong property.

**M12b — a non-strategy job given a chip, checked in the browser.** Patching the backend
annotator could not reach chromium: the DOM fixture builds its stub payload directly and never
calls that function, so the mutation stayed green while exercising nothing. It is mutated in
the JS the browser actually loads now. Same family as the source-patch-versus-behaviour mistake
this project has now made in six consecutive stages, which is itself worth recording.

### Six Stage 5ZD tests updated

They pinned the UI this stage deliberately replaced: the sentence in the collapsed row, the rule
grid, the per-sleeve panel row, and the shape of the `signal` object before `chip`/`operator`/
`debug` existed. Each was rewritten to assert the **same intent** against the new rendering —
the row is scannable, the panel is readable, the backend owns the wording — rather than deleted.

---

## Regression

| | result |
|---|---|
| Stage 5ZE | **64 passed** (11 in a real browser) |
| Stage 5ZE + 5ZD together | **127 passed** |
| Stage 5ZE mutations | **26 red, 0 green** |
| dashboard backend · realtime contract · realtime DOM · schedule-status mirror · 5ZB | **327 passed** |

`test_event_playback.py` was not run, as instructed.

---

## §7 — restarts, and what the live dashboard shows right now

**I restarted nothing.**

The scheduler is pid 48604, unchanged since 01:07 ET. The backend is pid **35592, started
12:14 ET** — restarted by the operator or by something else, not by this stage; the pid it
replaced (35352) is the one the earlier reports named.

That restart landed **between** Stage 5ZD and Stage 5ZE, so the live dashboard right now serves
the 5ZD shape: `signal` with `details`/`source`/`status`/`summary`, and **no `chip`, no
`operator`, no `debug`, and no `operational`**. Measured against the live endpoint, not assumed.

`app.run(..., use_reloader=False)`, so it will not pick the new code up on its own.

**For the operator's live dashboard to show Stage 5ZE, one backend restart is needed:**

```powershell
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

I did not run it. The stage permits a backend restart *only if needed for UI verification*, and
it was not: the UI was verified in a real browser against a freshly-imported app inside the test
process. Leaving the decision with the operator also keeps the two Rổ 4 windows still to run
today — Swing at 14:05 — undisturbed.

---

## Files

```text
global_index/track1_signals.py                  + LABELS, LAYER_LABELS, CHIPS, label(), chip(),
                                                  operator_lines()
monitor/backend/job_journal_reader.py           + the operational block, + signal chip/operator/debug
global_index/dash/realtime/realtime.js          chip, Operational section, operator signal block,
                                                  counts-only panel row
global_index/dash/realtime/realtime.css         chip + section styles; the 5ZD rule grid removed
scratch/test_track1_stage5ze_job_view_operator_20260825.py   64 tests, 11 in a browser
scratch/track1_stage5ze_mutations_20260825.py                25 mutations
scratch/test_track1_stage5zd_signal_diagnostics_20260825.py  6 tests updated for the new UI
```

No strategy file, no scheduler file, and no gate file was touched.
