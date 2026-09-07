# Stage 5ZM — Track 1 reports from Track 1's own artefacts, and legacy stops eating its rows

**2026-08-26, ET 02:20–03:05.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **nothing restarted** · no runtime artefact edited · no P&L or
broker evidence fabricated.

```text
UTC 2026-08-26 06:22 · ET 2026-08-26 02:22 EDT · Calgary 2026-08-26 00:22 MDT
```

*Naming: the 5ZJ and 5ZK reports are dated `20260826`, not `20260825`, and there is no
`track1_stage5z_paper_callsite_dryrun_20260825.md` — the callsite dry-run report is
`track1_stage5z_callsite_dryrun_20260825.md`, which is what was read.*

**Operator restoration verified before anything else.** `preflight_state.json` holds exactly
the seven days named, and `2026-08-26` is absent. A test in this suite pins both, so the 5ZL
incident cannot quietly return and today's real 13:45 ET pre-flight remains the only thing that
can add today.

---

## The eleven answers

| | |
|---|---|
| 1. readers found, and how classified | **9 reporting readers in 5 classes** (§2) |
| 2. made Track 1-aware | a new Track 1 reader, plus a route split in two legacy aggregates (§3) |
| 3. does Track 1 ever fall back to legacy? | **no** — asserted three ways, one of them by watching every file it opens |
| 4. legacy reports unchanged? | **yes for output**; both aggregates now *exclude* foreign-route rows and *say how many* |
| 5. can the dry run feed expected reporting? | **yes**, and every such row is labelled INTENDED |
| 6. broker/Flex P&L verified? | **no.** Two reasons, both measured (§5) |
| 7. open-position parity | **PASS (`both_flat`)** — with attribution unknown, which is not a technicality (§6) |
| 8. runtime/live file changed? | **no** |
| 9. orders still impossible? | **yes** — three blockers |
| 10. next shadow window READY? | **yes** — tonight's NKD window ran throughout, untouched |
| 11. what remains, is 5ZN next? | three items; **yes, 5ZN** |

---

## 1. Baseline

```text
scheduler pid 18096   backend pid 30604   track1-only-shadow   orders_possible False
blocking  B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE,
          REGIME_LABEL_VERIFICATION
```

| artefact | state |
|---|---|
| `trade_log.jsonl` | 8486 B, 2026-08-15 — 28 rows, none tagged |
| `global_index/track1_runtime/trade_log.track1.jsonl` | **0 B**, 2026-08-25 22:20 — the 5ZJ writability probe |
| `live_positions.json` | 481 B, 2026-08-24 |
| `live_positions.track1.json` | 284 B, 2026-08-25 — zero positions |
| `global_index/track1_runtime/orders/` | **absent** — nothing sent or rehearsed |
| Flex statements | **3 on disk**, newest covering 2026-02-18 → 08-17 |
| session report / paper P&L outputs | `paper_pnl_compare.json` 131 KB, 2026-08-25 |

## 2. The readers, and what each of them is

Found by AST over string literals across `global_index`, `monitor` and `futures` — 34 files
mention one of the four artefact families. Stripping tests and operational scripts leaves nine
that *report*:

| reader | class | verdict |
|---|---|---|
| `monitor/backend/track1_runtime_reader.py` | **2 — already Track 1-aware** | extended, not converted |
| `global_index/reconcile_statement.py` | **1 — legacy by design** | untouched |
| `monitor/backend/entry_time_reader.py` | 1 — legacy by design | untouched |
| `monitor/backend/execution_quality_reader.py` | 1 — legacy by design | untouched |
| `monitor/backend/runner_positions_reader.py` | 1 — legacy by design | untouched |
| `monitor/backend/report_reader.py` | 1 — legacy by design | untouched |
| `global_index/session_report.py` | **4 — missing Track 1 implementation** | still missing, deliberately |
| `monitor/backend/paper_evidence_reader.py` | **3 — shared, route split required** | **split** |
| `monitor/paper_pnl_compare.py` | **3 — shared, route split required** | **split** |
| `monitor/flex_pull.py` | **5 — cannot verify until broker evidence exists** | measured, §5 |

Class 1 is the largest and it is the right answer for most of them: a reader whose subject is
the legacy book should keep reading the legacy book. The two that needed splitting are the two
that aggregate *the whole trade log* — the paper evidence gate and the P&L number itself.

## 3. What was built

### The Track 1 reader — `global_index/track1_report.py`

Three artefact states, because two is not enough:

```text
not_produced   the artefact does not exist. Nothing has written it yet.
empty          it exists and holds nothing. Something ran and had nothing to say.
available      it exists and holds rows.
```

A trade log that exists with zero rows means the route swept and closed nothing; a missing one
means no sweep has ever proved its destination writable. Those are different facts and they
never print the same. The book distinguishes them the same way — a missing book reports
`positions: None`, not `0`.

**It never reads a legacy path**, and that is asserted three ways rather than promised:

- by AST, over short string literals, so a docstring mentioning a legacy file is not mistaken
  for code that reads one;
- **behaviourally** — the whole report runs against a populated root with `open` and
  `Path.read_text` wrapped, and every path it touches is recorded. A literal check alone would
  miss a path built by concatenation;
- in its own payload, `reads_legacy_paths: false`.

Every row must carry `route == "track1_candidate"`. A row without it is **invalid**, counted
separately, and never included in a total. That matters more than it looks: the tag is written
by the runner (5ZG) precisely so a row that ended up in the wrong file still names its route —
and a row in the *right* file that does not name it is legacy's, hand-edited, or written by
something that has not been taught the contract. None of those is Track 1 P&L.

### The legacy side — two aggregates, one rule

`paper_evidence_reader` consumes the whole trade log and splits on nothing, which is the
measured reason 5ZG gave Track 1 a separate file. `_trade_records` now delegates to a splitting
version and the excluded rows are **returned, not dropped**, so the payload can say:

```json
"trade_log_foreign_route_rows": 0,
"trade_log_foreign_routes": []
```

Zero is the expected reading, and it is the number to watch — non-zero means a Track 1 row
reached legacy's file. *A filter whose effect nobody can see is a filter nobody can check.*

The same guard went into `monitor/paper_pnl_compare.py` at both of its row loops, because that
module **is** the P&L number.

**The filter excludes foreign routes rather than selecting legacy ones**, and that distinction
is the whole design. Every row written before 5ZG carries no tag. "Keep only rows tagged
legacy" would have silently emptied both aggregates of their entire history — a failure that
would have looked exactly like a working filter. A test pins it.

Legacy output is otherwise untouched: the 28 existing rows are all untagged and all kept,
verified.

## 4. What can be computed now

| | available | why |
|---|---|---|
| shadow / dry-run **intended** orders | **yes**, when the journal exists | labelled `source: dry_run` and *"INTENDED, not sent"* |
| real paper P&L | **no** | no Track 1 order has ever been placed |
| open-position parity, file level | **yes** | book against journal |
| open-position parity, broker level | **no** | §5 |

The order journal reports its source rather than inferring it, because a rehearsal and a real
send produce the same row shape and the only honest way to tell them apart is which gate was
open at the time.

## 5. Broker evidence — false, for two separate reasons

```json
{"broker_verified": false,
 "reasons": ["no_track1_orders_have_been_placed", "route_unattributed"],
 "statements_on_disk": 3}
```

Both are stated because they need different things to change. The first closes itself the day a
Track 1 order fills.

The second does not, and it is measured rather than assumed. The newest Flex statement has
**37 fields**, and none of them is a route, a strategy, an order reference or a client id —
only `ClientAccountID`, one account. So even once fills exist, **a statement cannot say which
route made them** while one login serves both. That is a property of the statement format, and
it is a second concrete reason B1 has to be closed before paper rather than alongside it. A
test asserts the field list against the real file, so the claim decays if the format changes.

## 6. Parity — PASS, and why that word needs its qualifier

```text
status  PASS   code both_flat
        the book holds nothing and no order has been journalled — the two agree,
        and both are empty for the same reason
attribution  attribution_unknown
        file-level agreement only; while one IB login serves both routes a broker
        position cannot be attributed to one of them — see B1
```

Five outcomes, and UNKNOWN is never PASS: a missing book is UNKNOWN; a book with positions and
no journal row is a FAIL and named *a position nobody can account for*; a journal row against a
flat book is a FAIL; both populated is UNKNOWN, because matching them per instrument needs real
fills. The one PASS available today is a genuine agreement between two empty things, and it
carries the attribution caveat in the same payload so it cannot be quoted without it.

## 7. The dashboard

A `reporting` block on `/api/v1/track1-runtime` carrying the whole report through — the states,
the counts, the parity, and `broker_verified: false` with its reasons — plus
`paper_ready: false` and the sentence *"reporting readiness is not paper readiness; the order
gate is held by its own blockers"*. It fails closed if the reader raises.

**The running backend still serves the old reader.** The block appears after a restart, which
was not performed: the NKD window was open and nothing here is urgent.

## 8. Tests

**41 tests**, `scratch/test_track1_stage5zm_route_aware_reporting_20260826.py`. All eleven
items the brief lists, plus the branches the code suggested — a book naming another route is
refused; a malformed line is counted, not swallowed; `broker_verified` is never true anywhere
in the payload; the back-compatible three-tuple helper still exists for its callers.

The one worth naming is the file-watching test. Asserting "no legacy literal" is a textual
claim; running the reader with `open` and `Path.read_text` wrapped and checking what it
actually touched is a behavioural one, and it is the one that would survive a path built by
concatenation.

## 9. Regression

**570 passed, 0 failed** — 5ZM, 5ZL, 5ZF, 5ZG, 5S, 5ZK, and the whole `monitor/` suite
including the two Flex suites and the dashboard DOM.

One 5ZF tripwire fired and was split rather than deleted.
`test_15_the_report_flex_and_pnl_paths_are_not_route_aware` covered three modules; two are
still route-blind and remain pinned, and `paper_pnl_compare` came off the list. It does not
*read* Track 1 paths — it still reads only legacy's book and log — but it now *excludes*
tagged rows, so it names `track1_candidate` and the original assertion could not tell the two
apart. A new test draws exactly that distinction: excluding another route's rows is not reading
that route's artefacts.

## 10. Runtime side effects

**None.** Every artefact still carries its baseline mtime: the legacy log at 2026-08-15, the
Track 1 log at 22:20 (5ZJ's probe), both books unchanged, `paper_pnl_compare.json` unchanged.
No report was generated to disk; `track1_report.report()` returns a payload and writes nothing.
`preflight_state.json` still holds the operator's seven days with `2026-08-26` absent.

Nothing restarted. The Track 1 reader is importable now; the dashboard block needs a backend
restart.

## 11. What remains before paper

| | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 — and §5 gives it a second, sharper reason | **operator decision** |
| 3 | planned stop not journalled; `close_position` and `place_protective_stop` unbuilt; no cross-day book | **5ZN** |

Plus two machine gates that open by themselves: the shadow evidence gate as clean days
accumulate, and the regime gate the first time the 16:20 job records a PASS.

**Removed:** *"route-aware P&L, open-position parity, legacy-reader split"* — with two honest
qualifications. A **route-aware session report** was not built: `session_report.py` is a
legacy-book report and giving Track 1 a section of it before Track 1 has anything to report
would be a page that says nothing, so it stays classified as missing. And **Flex reconcile**
cannot be built, not merely was not — §5 measures why.

**Next is 5ZN.** The stop is the widest remaining gap: neither the order nor the journal row has
anywhere to record it, so there is nothing for a live working stop to be compared against — and
the parity work above ends at UNKNOWN for the same underlying reason, that the route has no book
it carries across a day.
