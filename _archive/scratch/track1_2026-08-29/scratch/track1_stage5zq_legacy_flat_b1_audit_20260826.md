# Stage 5ZQ — somebody finally asked the account

**2026-08-26, ET 06:00–07:00.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **nothing restarted** · no position closed, no order cancelled,
no order modified · no book, trade log, checkpoint or audit record touched · legacy drain
safety left scheduled.

```text
UTC 2026-08-26 10:30 · ET 2026-08-26 06:30 EDT · Calgary 2026-08-26 04:30 MDT
```

---

## The eleven answers

| | |
|---|---|
| 1. legacy file book flat? | **yes** — `positions: []` |
| 2. broker flat? | **yes** — 0 positions, 0 working orders, asked directly at 06:15:51 ET |
| 3. orphan working orders? | **no** — and none is possible: there are no orders at all |
| 4. Track 1 book flat? | **yes** — `positions: []`, cut 02:55 ET today |
| 5. can B1 be closed by measurement? | its **measured half passes**; the gate stays shut, correctly (§4) |
| 6. what remains for B1? | the operator's recorded decision, plus a PASS newer than 24h |
| 7. any broker/order action? | **no** — three reads, nothing written to the account |
| 8. runtime/live file changed? | **one, by design** — the audit's own evidence record |
| 9. orders still impossible? | **yes** — three blockers |
| 10. next shadow window READY? | **yes** — scheduler 18780 untouched, calm opens 10:00 ET |
| 11. before a tiny paper probe? | five things, and the fifth is that **the order path does not exist** |

---

## 1. Baseline

```text
scheduler 18780   backend 48760   track1-only-shadow   orders_possible False
blocking  B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE,
          REGIME_LABEL_VERIFICATION
broker    connected, fresh (5.7s), equity 996,883
```

| artefact | state |
|---|---|
| `live_positions.json` | 481 B, 2026-08-24 09:31 ET — **`positions: []`** |
| `live_positions.track1.json` | 284 B, 2026-08-26 02:55 ET — **`positions: []`**, schema 2, route-stamped |
| `trade_log.jsonl` | 8486 B, 28 rows, last 2026-08-11 — **every row untagged** |
| `trade_log.track1.jsonl` | **0 B** — exists, empty: the 5ZJ writability probe and nothing since |
| `STOP_TRADING`, `STOP_TRADING.track1` | absent |
| `runner.pid`, `runner.track1.pid` | absent |
| `track1_runtime/orders/` | **absent** — nothing has ever been sent or rehearsed |
| `track1_go_live_confirmation.json` | absent |

Both books live at the **repo root**, not under `global_index/`. That matters in §6.

## 2. The account, asked

The dashboard has been printing `0 positions / 0 orders` for weeks. **That number was not
evidence**, and §5 is why. So the account was asked directly, read-only, through the class the
safety jobs already use:

```text
06:15:51 ET   IBKRBroker  client id 97   (1 legacy · 90 Track 1 safety · 99 dashboard)
              positions        0
              working orders   0     reqAllOpenOrders, ALL clients
              equity           996,883.65
```

`get_positions()` raises rather than returning `[]` when it cannot read, and
`get_open_orders()` returns `None` rather than `[]` when it cannot testify — so this path can
tell "holds nothing" from "could not ask", which is the whole difficulty.

Corroborated: the dashboard's own reader, on a different client id and a different code path,
reported the same 0/0 and equity **996,883.66** — a ten-cent tick apart. Two paths, one answer.

**Verdict: `BROKER_FLAT`.**

### Why a shared account can answer this at all

Attribution is B1's whole difficulty — a Flex statement cannot say which route a fill belonged
to. But **attribution only matters when something is nonzero.** Zero positions and zero working
orders is unambiguous however many routes share the login: there is nothing to attribute.

That is the one shape of this question a shared account can answer, and the measurement is
built around it: any nonzero position or working order is FAIL-or-UNKNOWN and never PASS.

## 3. Nothing to close, nothing to cancel

Part D's operator plan is empty, and empty for the strongest reason: there are no positions to
close and no orders to cancel. No close/cancel step was authorised, none was needed, and none
was taken.

## 4. B1 now needs a decision **and** a proof

Before this stage, B1 opened on a signature:

```text
released(conf) = legacy_retired_confirmed OR separate_account_confirmed
```

A person writing `true` in a file asserted a fact about an IBKR account, and **nothing ever
asked the account.** Precondition 7 of the switch-over runbook — *"legacy is flat at the
broker, not only on disk"* — had never been checked by anything.

It now reads:

```text
released(conf) = signed AND (the measurement passes OR an explicit waiver is set)
```

Strictly tighter: every path that opened the gate before still requires the signature, and now
requires proof as well. The waiver exists because the Gateway is sometimes genuinely
unreachable — but it releases **nothing on its own**, and a confirmation file carrying it
without a `note` saying why is refused outright.

So B1 is still shut, and the reason has changed from *"nobody has decided"* to *"nobody has
decided — and the fact the decision would assert is now checked."*

**The measurement cannot close B1 by itself, and should not.** Proving the account flat at
06:15 says nothing about 14:05. Which route owns the login is a decision; no measurement can
make it.

## 5. The dashboard's zero was never evidence

```python
orders: list[dict] = []
try:
    for t in ib.reqAllOpenOrders():
        ...
except Exception as e:
    logger.warning(f"openTrades error: {e}")     # orders stays []

_set({"connected": True, "error": None, ..., "orders": orders})
```

Both collectors are shaped like this. A raised call leaves the list empty and the payload still
publishes **`connected: true, error: null`**. So an empty list meant either *the account holds
nothing* or *the call raised*, with nothing to tell them apart — **fail-open, on the exact
question B1 asks.** There is no backend log on disk, so the warnings that would have
distinguished them are not recoverable either.

Fixed: each section now reports whether it **succeeded**, both flags start False, and both are
cleared when the connection drops so a stale `True` cannot keep testifying with the last good
answer. A snapshot that does not carry the flags is read as UNKNOWN — the backward-compatible
direction, because an old payload proves nothing.

**Not live.** It is in the running backend's code, and the running backend has not been
restarted. Until it is, the audit must be run with `--broker ibkr`.

### A method written in Stage 5X that nobody had called

`IBKRBroker.get_open_orders()` was added for exactly this — unfiltered by clientId, because an
order placed by another client is still exposure on this account, and `None`-not-`[]` because
the caller must be able to tell the two apart. Its docstring says so. **It had zero callers.**
The honest reader existed all along beside the fail-open one, and nothing asked it anything.

## 6. Three things the file evidence cannot do

**The legacy trade log cannot prove flatness.** 28 rows: 18 OPEN, 10 CLOSE, **8 net unmatched**
— and six of those eight are MES SHORT on `entry_day 2026-08-07`, logged at 19:10, 19:20,
19:30, 19:40, 19:50 and 20:01 UTC, every one with `order_id: null` and `perm_id: null`. Six
identical opens at a ten-minute cadence is a job re-logging, not six fills. The log also stops
on 2026-08-11 while the book was last written on 2026-08-24.

So 18 OPEN rows are not 18 positions, and the gap between them is not proof of anything. The
**book** and the **broker** are the authorities. This is the same shape as the known exit-path
gap — three of five close paths book money and write no trade-log row.

**A runbook check that can never fire.** The shadow-window runbook's *"what must NOT exist"*
list names `global_index/live_positions.track1.json`. The code writes
`live_positions.track1.json` at the repo root. The forbidden path is one nothing ever creates,
so that line cannot fail. And substantively it is now stale in the other direction too: since
Stage 5ZN the Track 1 book carries cross-day breaker state and **is expected** in shadow — the
test is `positions: []`, not absence.

**A missing book is not an empty book.** The measurement treats absence as UNKNOWN, never flat,
which is the same rule the window ledger applies to slots.

## 7. Two things caught in my own work

**An unreachable branch.** `measure()` had a `position_without_stop` result that could never be
returned — any nonzero broker position fails on the line above it, so the naked-position check
always ran against an empty list. A branch that cannot fire reads, to anyone auditing the
table, as a check that runs. The status was removed and the detection kept as a **finding** on
the broker-positions failure, where it is reachable.

**The live-frame gate closed on me, and it was right.** The audit tool was first written as
`global_index/track1_b1_audit.py`. That gate scans every `global_index/track1_*.py` for the
identifiers by which live bars can be obtained — `IBKRBroker` among them — and requires each to
import the splice guard. A **fourth blocker appeared** the moment the file was saved.

The rule was not softened. The file was in the wrong category: its subject is positions and
orders, it never asks for a bar, and the other IBKR-connecting operator jobs —
`run_stop_repair.py`, `run_maxhold_exit.py` — sit in the same directory outside that namespace
for the same reason. `run_live_day_track1.py` is added to the scan **by name** because it *is*
on the route, which shows membership there is curated by role rather than by spelling.

So the measurement stays on the route where it opens no connection, and the tool that connects
moved out to `global_index/b1_audit.py`. A test pins both directions, so the move cannot later
be read as evasion.

## 8. What was built

| | |
|---|---|
| `global_index/track1_b1.py` | the measurement. Pure, read-only, opens nothing. PASS / FAIL / UNKNOWN with 14 codes, each declaring the one status it may carry, cross-checked on construction. |
| `global_index/b1_audit.py` | the operator tool. `--broker {snapshot,ibkr,none}`, writes nothing without `--record`, exit code 0/1/2 so the three answers survive a caller that cannot read the text. |
| gate wiring | `also_requires_measurement` (an AND) and `waiver_flag`, both empty for every other blocker. Two new structural rules in `self_check`. |
| `ibkr_reader` + `/api/v1/broker` | per-section success flags (§5). |
| `ops.py status` | one line of plain English, reading the record and opening nothing. |

```text
b1_legacy_flat=PASS (legacy_and_broker_flat)  legacy_book=0 track1_book=0
                broker_positions=0 working_orders=0 orphans=0
  Legacy book flat, Track 1 book flat, broker flat, no working orders.
  [observed 2026-08-26T10:15:51Z]
```

## 9. Tests

**46 tests**, structured payloads and AST throughout — no prose greps. All ten required
scenarios, plus: a snapshot without the success flags proves nothing; a stale record stops
counting; a record whose status and code disagree is refused; a waiver alone releases nothing;
a waiver without a reason is refused; every other blocker is unchanged; the live-frame gate is
still released and still names nothing of mine.

**Mutation sweep: 11 of 11 anchors go red.** The harness checks that pytest actually
**collected** something first — an exit code of 5 means nothing ran, and reading that as "red"
is how a sweep certifies itself. That is not hypothetical: it happened earlier today in a
different sweep and was caught.

### A stale pin, in a suite no regression set included

`test_track1_dashboard_runtime_wiring_20260824.py` pins `t1Fact('Blocking gate')`; the panel
renders `Blocking gates`. **Which stage pluralised it cannot be dated** — the whole panel is
uncommitted work on this branch, so there is no earlier revision to compare against, and I am
not going to guess.

What *is* measurable is that this suite was in no stage's regression set, so whichever stage
renamed the label, nothing was watching. The label is corrected — and the list **completed**:
it pinned ten of the thirteen facts the panel renders, so three could have disappeared
unnoticed. A second test now checks the other direction.

## 10. What remains before a tiny paper probe

| | item | class |
|---|---|---|
| 1 | the B1 decision, recorded — retire legacy, or a second account | **operator** |
| 2 | five clean judgeable shadow days | **time** |
| 3 | the regime gate's first PASS | **time** |
| 4 | machine sleep | **operator** |
| 5 | **the order path itself** — `run_shadow` constructs `NoOrderBroker` unconditionally and never constructs `IBKRBroker`. No code on this route can place an order. | **code, unwritten** |

Item 5 is not a gate and never was. Opening every gate produces a route that still cannot send
anything, which is the correction Stage 5S wrote into the runbook and which this stage does not
change.

**One operator step would make the cheap path work:** restart the backend, after which
`--broker snapshot` answers B1 without opening a connection. Not restarted here.

## 11. Regression, and what it uncovered

**Targeted:** 447 passed, 0 failed — Stage 5ZQ, the whole of `monitor/`, and the two dashboard
suites.

**The full `scratch/` sweep — 67 suites, 18 minutes — came back 2359 passed, 43 failed.** The
same fourteen suites run alone give 28, so fifteen of the forty-three are order-dependent:
cross-suite state leakage, a separate problem this stage did not chase.

### Which of them are mine: one

Measured, not argued. Every 5ZQ edit was reverted and both new modules moved aside, in a
subprocess; the fourteen suites were re-run and everything restored and digest-verified.

```text
with Stage 5ZQ      27 distinct failing tests
without Stage 5ZQ   26
caused by 5ZQ        1
```

`test_41_get_open_orders_is_CALLED_by_nothing_in_the_legacy_route`. Its **name** says nothing
in the legacy route calls the method; its **assertion** said nothing anywhere does. The second
is a stronger claim than the intent behind it — *"it is additive, legacy B3/B4 cannot have
moved"* — and it is the reason a method written for exactly this question sat uncalled for
several stages.

It now names its allowed callers and says why each is allowed, still goes red on any unnamed
one, and a second test requires the allowed caller to *actually call it* — so an allow-list
entry cannot outlive the call it describes.

### The other twenty-six were already red, and nothing was watching

The baseline this stage recorded at 06:03 ET proves the two biggest causes independently:
three blockers, and `live_positions.track1.json` already on disk from the 02:55 NKD close.
Both predate every edit here.

| category | what it pins | stale since |
|---|---|---|
| **roster pins** | the exact blocker list — one, then two | 5S, then 5ZL |
| **absence proxies** | `live_positions.track1.json` must not exist | 5ZN gave the route a book |
| **slot-count pins** | 25 Track 1 slots, "the two windows" | 5N gave it all four sleeves |
| **substring-over-prose** | *"a Track 1 slot asks for orders"* | it never did (below) |

None of the roster-pinning tests is *about* the roster. Pinning it is why one new blocker
breaks a dozen unrelated suites, and it will keep happening.

Two more in 5ZO and three in the freshness suite were **not** traced. Naming which stage
stranded them would be a guess.

### The one that had to be fixed today

A test was reporting **"a Track 1 slot asks for orders."** It was matching a *comment* inside
the slot builder that reads *"Still no `--allow-orders`, no `--port`, no `--window`"* — the
comment asserting the absence read as the presence. Measured after stripping comments: neither
flag appears in any argv the slot builds.

A red test making that claim is the one alarm nobody should have to re-derive, so it was
repaired here along with one roster pin, rewritten to assert its own claim — orders impossible,
B1 among the reasons — rather than the roster. That is the repair the whole family needs.

**The remaining twenty-four were left alone deliberately.** Fixing them is a stage of its own,
and doing it half way inside this one would be worse than naming them precisely. What that
stage should also do is put `scratch/` into a regression set somebody actually runs — because
the measurable fact here is not that these tests broke, it is that nothing noticed.

