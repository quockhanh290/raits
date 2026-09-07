# Stage 5ZZF — the dashboard was subtracting across a currency boundary, three days late

**2026-08-27, ET 07:45–08:10.** Source, tests and docs only. No orders · no confirmation file ·
no order directory · **nothing restarted** · **no runtime evidence edited** · no broker
connection (the already-served API was enough).

---

## 1. Why the old equity was still visible

Measured on the live endpoints before a line was changed:

```text
/api/v1/track1-runtime  paper_account       USD 250,817.91  PASS      correct
/api/v1/broker          payload.equity          250,818.18  fresh 7s  correct, live drift
/api/v1/runner-state    meta.broker_equity      996,730.93            76.8 hours old
                        meta.paper_start      1,000,480.00  "CAD"     a different era
```

and the line the page drew from the last two:

```text
Broker acct $996,731 / -$3,749 since 2026-07-08
```

**Two faults in one sentence, and the second is the one nobody could have seen.**

**The subtraction crossed a currency boundary.** `meta.paper_start` carries its own note —
`"connect_test_paper.py, DUR125337, CAD"` — and `meta.broker_equity` carries no currency at all.
The difference was rendered with a dollar sign, on a page where every other money figure is USD,
for the account `DUR125337` which now holds USD.

**And the payload was three days old while the page had no way to tell.** The runner-state
envelope reported:

```text
observed_at       2026-08-24T06:58:47Z
age_seconds       276,575     = 76.8 hours
freshness         not_expected_yet         <- not "stale"
expected_next_at  2026-08-27T13:32:00Z     <- in the future
```

In track1-only mode the legacy runner is **never scheduled**, so `expected_next_at` keeps sliding
forward and the reader never calls the payload old. **A freshness model that assumes its producer
still runs cannot report a producer that has stopped** — and the page's own staleness guard
(`['missing','unknown','stale'].includes(freshness)`) therefore never fired.

## 2. Which source is now authoritative

| what | source | shown as |
|---|---|---|
| the account this route starts from | `track1-runtime.paper_account` | **Paper account USD 250,818 · baseline PASS** |
| the live broker figure | `/api/v1/broker.payload.equity`, only when fresh | `· broker now 250,818` |
| the legacy runner's last view | `runner-state.meta.broker_equity` | only under **Legacy runner state**, always with its age, never as the current account |

The recorded baseline wins. A fresh broker reading sits beside it as a separate labelled fact and
is allowed to differ by live drift — the two differed by **$0.27** when measured, which is exactly
the drift the label exists to permit.

**And a divergence is called out rather than left on the page.** When the legacy figure differs
from the baseline by more than 10%, the line says so, names the age, and turns negative:

```text
Paper account USD 250,818 · baseline PASS · broker now 250,818
  · legacy runner state still shows 996,731 from 3d 4h ago
```

The account line no longer consults `runner.freshness` at all. It uses the **age**, which is a
fact, rather than a schedule, which in this mode is a fiction.

## 3. Open issues: reclassified, and nothing deleted

**Nothing was deleted, hidden, downgraded or resolved.** Five issues in, five out, each keeping
its status, evidence, occurrence count and place in the list. Each gained three fields:

```text
scheduler   incident    job:session_report:missed              blocker=False
legacy      incident    paper:lifecycle:unresolved             blocker=False
legacy      incident    paper:pnl:paper_flex_total_mismatch    blocker=False
legacy      incident    paper:decision_path:unresolved         blocker=False
known_debt  known_debt  known_debt:model_age                   blocker=False
```

The three `paper:` issues compare the **legacy** paper ledger against broker statements and read
no Track 1 artefact; the scope reason says so in those words, and it is a tooltip on the chip.

The scope is **derived from the key**, not from a hand-kept list of titles — this repo already has
the scar for a list maintained beside the thing it describes.

**And the reader declares that it does not decide blockers.** `track1_readiness_blocker` is
`False` on every issue, always, and the payload carries
`track1_readiness_blockers_come_from: "global_index.track1_gates.blocking()"`. A log parser
holding a second opinion about what stops orders is how two answers come to disagree.

Visually it is one chip in the badge lane that already exists — same pill geometry as the status
beside it, only the colour differs, and the legacy and debt lanes are deliberately quieter than
TRACK 1 so they stay visible without competing with a live incident. **No new section, no new
card.**

## 4. Does the dashboard need a restart

**Yes — a backend restart, for the issue scope chips only.** Measured rather than assumed:

```text
backend PID 42260 started            07:08:35 ET
monitor/backend/open_issue_reader.py edited 07:56:22 ET  -> NOT served
monitor/backend/track1_runtime_reader.py    07:24:34 ET  -> IS served
```

`open_issue_reader` is imported at **module top** (`app.py:39`), bound at boot, so the running
process holds the pre-change version. `track1_runtime_reader` is imported **inside the handler**
(`app.py:249`) and was picked up only because nothing had called that endpoint between the
restart and the edit, leaving `sys.modules` empty for it.

**That corrects something in the previous stage's report.** Stage 5ZZE said no backend restart was
required, having measured that the new block was being served. The measurement was right and the
conclusion was too general: the block was served by luck of import ordering, not by a reload
mechanism, and the same cannot be relied on here.

The page's own JavaScript and CSS are static files — a browser refresh is enough for the equity
line and the chip styling. Only the API field needs the process replaced.

```powershell
python monitor\ops.py restart --backend --yes
```

**Not run — the operator's call.** Nothing is worse meanwhile: the issues are all still listed,
they simply carry no scope chip yet.

## 5. Orders and blockers

```text
orders_possible : False
blocking        : B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
confirmation    : ABSENT      orders dir : ABSENT
```

Unchanged. Nothing in this stage touches a gate, and the open-issue reader is now explicit that
it never could.

## 6. Tests

**18** in `scratch/test_track1_stage5zzf_dashboard_source_hygiene_20260827.py` and **5 new
browser tests** in the existing DOM suite, driven with the exact numbers that were on the page.

Three mutations on the reader, all red: a legacy issue promoted to Track 1 · scoping quietly
filtering instead of labelling · the log parser declaring its own readiness blockers.

Two mutations on the page, both red, with the file restored byte-identical: the account line
reverting to the legacy number (3 of 5 browser tests fail), and the divergence threshold removed
so nothing is ever material (1 fails).

**Suites: 287 passed** across the DOM, realtime-contract and dashboard-backend suites, and **144
passed** across the adjacent Track 1 set.

### One pre-existing test was rewritten, not deleted

`test_broker_account_delta_is_visible_in_equity_header` asserted that the delta `4,168` appeared
in the header — it pinned **the very behaviour this stage removed**, including the cross-currency
subtraction. Its concern is worth keeping: a sharp divergence around the account must be visible
rather than averaged away. So it now measures that divergence between the recorded baseline and
the legacy figure, on the same scenario, and additionally asserts the old delta is gone in every
spelling.

### Three faults in my own tests, found by running them

**A substring assertion read my own comment.** `assert "Broker acct" not in JS` found the phrase
inside the comment I had just written to record what was wrong. That trap has now caught this
project four times. The reader strips comments; and a second assertion demands the explanatory
comment is still *there*, so the record cannot be tidied away either.

**A slice with no end.** `JS[i:i+3000]` ran past the account line into `runnerFreshnessText`, so
an assertion about one function was reading another's source. It is bounded at its own closing
statement now.

**A cached reader made a mutation into a no-op.** `read_open_issues` memoises on a file/date
signature, so patching the builder changed nothing and the mutation test passed while proving
nothing. The cache is cleared before and after, and the test now asserts the issue list is
non-empty first — a loop over nothing passes whatever you do to it.

## 7. One fault in the production code, surfaced the same way

`_build` called `_scoped(issues)` for its **side effect** and then read `issues` again. That works
while `_scoped` labels in place and breaks silently the day it returns a new list — which is
exactly what the mutation did, turning a wrong answer into a `KeyError`. The caller uses the
return value now.
