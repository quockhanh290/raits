# Stage 5ZZG — the SEND wire exists, and the proof it stays shut

**2026-08-27, ET 10:05–10:45.** No orders sent · no confirmation file · `TRACK1_ORDERS_APPROVED`
never set · no orders directory · **nothing restarted** · no broker order path exercised outside
`tmp_path` stubs.

---

## The seven answers

| | |
|---|---|
| **1. Is the SEND wire implemented?** | **Yes.** `track1_paper_send.maybe_send_orders`, called by the live slot after the coverage row |
| **2. Can the scheduler reach it?** | **No.** Not without a manual `--allow-orders`, which no scheduler or ops path can produce |
| **3. Can a manual live-shadow run reach it with the gates open?** | **Yes** — and only then |
| **4. Did any broker order get sent?** | **No.** Every broker in every test is a stub |
| **5. Was a runtime order journal created?** | **No.** `track1_runtime/orders` is still absent; every journal in this stage lived in a `tmp_path` |
| **6. What blockers remain?** | `B1_broker_account_or_legacy_retirement`, `PAPER_SHADOW_EVIDENCE` — `orders_possible=False` |
| **7. Tests and failures?** | 33 new + 4 restated; **221** in the order-layer set and **113** in ops/dashboard. 4 pre-existing failures classified, none introduced |

---

## 1. What was missing, and why "missing" was a problem

The executor, the journal, the order mapping and the stop plan were all built. **Nothing called
them.** That was safe, and it was also a hole in the story: *"the wire is missing"* is not a state
anybody can write a test about, and a wire built later under time pressure is a wire built without
the tests written here.

## 2. The shape

```text
observe_live_slot(...)
    ...coverage row written...                    <- evidence first, always
    maybe_send_orders(decisions, order_gate=gate, broker=broker, ...)
        gate shut  -> return; nothing imported, nothing built, nothing written
        gate open  -> executor(broker, gate) -> open_position per ADMITTED decision
```

**The gate check comes before the import**, and that ordering is the contract rather than a
style choice. A subprocess test asserts that after a closed-gate call
`global_index.track1_paper_executor` is not in `sys.modules` at all — an assertion that only
means something while the import sits below the check. A second test reads the function's AST and
pins the ordering, so the first cannot quietly stop proving anything.

**It never constructs a broker.** The live-shadow path already builds `(provider, broker)`
together for bars; the send uses that same object. Armed with no broker it **refuses** rather than
building one — a second connection on a second client id is how this project lost six entry slots
in a morning, and an order path the gate does not govern is worse than no order path at all.

**It decides nothing.** Not what to trade, not how large, not whether a candidate was admitted.
The word for "admitted" is asked of the signal layer that owns it rather than spelled here.

## 3. A hardcoded claim replaced by a measurement

The live-shadow branch ended with:

```python
print("send_order calls: 0")
```

True every day it was printed, and true because nothing *could* send — not because anything had
counted. A claim nobody measures is a claim that goes on being printed after it stops being true.
It is now the send pass's own summary:

```text
send_order calls: 0 — the order gate is closed; no executor was built and no broker was called
```

## 4. Failure is never a rejection

If a send raises, the executor writes UNKNOWN and re-raises. This module counts it as **unknown**,
never as rejected, marks the run fatal, and `main` returns **3** with:

```text
ORDER UNRESOLVED — calm_a::MES::2026-08-27: TimeoutError: gateway went away
  the journal holds an UNKNOWN row. This is NOT a rejection: the order may be live and simply
  invisible. Reconcile before the next slot.
```

A slot with two admitted decisions reports both outcomes; one bad send does not hide a good one.

## 5. Verified against the real entry point

```text
--allow-orders against the real closed gate
    EXIT 2   mode: armed_but_refused   — refused before any provider or broker was built
    orders dir: still absent

ordinary shadow slot, no --allow-orders
    EXIT 0
    slot TRACK1_STRESS_1035 seq=0  decided=False  reason=no_bar_provider
    send_order calls: 0 — the order gate is closed; no executor was built and no broker was called
    shadow_intent md5 unchanged · orders dir still absent
```

## 6. The scheduler still cannot reach it

Asserted by AST and by source, with comments stripped so a note about the flag is not mistaken
for the flag:

- `run_scheduler.py` and `monitor/ops.py` contain no `--allow-orders` in any branch
- `_track1_body`'s launcher, read from its own AST, carries none
- no slot's argv carries one, across all 71 slots
- `TRACK1_ORDERS_APPROVED` is still required, and is unset in this session
- `orders_possible` is **False**, and the live-frame gate did not close

A mutation that adds the flag to the launcher turns that test red.

## 7. The old invariant, restated rather than weakened

Four tests held *"nothing in production imports the executor"* and *"the slot path has no order
gate"*. Both were true while the wire did not exist and are now false **by design**. Weakening
them to "anything may import it" would throw away the only thing that would notice a second road
to a broker, so they say what is now the case:

> the executor may be named by exactly the modules listed, and by nothing else — one **walled**
> (a broker whose `send_order` raises), one **gated** (the import past the check)

and

> the slot's gate argument exists, **defaults to shut**, and the scheduler passes nothing

The second matters more than the form it replaced: nobody was watching the default before,
because there was no default to watch.

One of these needed care. The 5W scan **excludes** the dry-run callsite by name, so its allowed
set is one entry; listing both there would have been a truer-sounding sentence about a scan that
never looks at the second. The full picture is asserted in this stage's own suite, over an
unfiltered scan.

## 8. A bug I introduced, and the measurement that bounded it

I added the new parameter **to the wrong function.** `broker=None` landed on
`emit_explanations`, and `main` then passed `order_gate`/`broker` to `observe_live_slot`, which
did not accept them. **Every live-shadow slot would have crashed with a `TypeError`.**

Caught by running the real entry point rather than by re-reading the patch, and bounded by
measurement rather than by hope:

```text
the broken edit was live roughly 10:10 – 10:26 ET
last live-shadow slot before it   10:02 ET  (TRACK1_CALM_OBSERVE_1002, completed OK)
next scheduled                    10:35 ET  (the Stress window)
track1 failure lines in today's scheduler log: 0
```

**No live slot hit it.** That is the answer a log gave, not one I inferred from the clock.

## 9. What the live Calm phases actually did this morning

Two stages listed this as pending. It has happened, and it is worth recording plainly because it
is not the outcome anybody was hoping for:

```text
09:32:06 ET  TRACK1_CALM_DECIDE_0932   gate_refused: missing_session, stale, partial_coverage
10:02:10 ET  TRACK1_CALM_OBSERVE_1002  gate_refused: missing_session, entry_quote_absent,
                                                     stale, partial_coverage
```

Both phases ran, both refused, and both left a `REFUSED / gate_refused` row in the shadow intent
stream — which is the machinery working: the refusal **is** the record, and the day classifies as
incomplete rather than counting.

**It is not the stale daily file.** That was fixed before the window and `freshness_refused` is
not among the reasons. `missing_session` says today's session bars were not in the frame the gate
was handed. **I have not traced why, and I am not going to guess** — it is the next thing to
investigate and it belongs to a stage that can measure it, not to a sentence here.

I also misread the clock while diagnosing this: I took the time for 08:2x and briefly attributed
these rows to my own test runs. They are the live scheduler's, timestamped 13:32:06Z and
14:02:10Z. Corrected by reading the row timestamps rather than trusting my sense of the hour.

## 10. Tests

**33** in `scratch/test_track1_stage5zzg_order_send_wire_20260827.py`. No broker is contacted;
every journal root is a `tmp_path`; no test arms the real gate or sets the approval flag — and one
test asserts that last point about the session it is running in.

Closed gate: nothing sent, nothing built, nothing written, the order layer not even imported
(checked in a subprocess, because once any earlier test arms the gate the module stays in
`sys.modules` for the rest of the session and an in-process check would pass on somebody else's
import).

Open gate with stubs: admitted decisions reach the broker, unadmitted ones never do, mixed slots
send only the admitted half, the journal walks INTENDED → SUBMITTED → outcome, each outcome is
counted under its own name, a receipt writes the order id as an amendment, and a raising broker
produces UNKNOWN — never REJECTED — with the error and the lookup key on the row.

Four mutations, all red: the gate stops being checked · an unknown counted as rejected ·
unadmitted decisions sent · the scheduler gaining the flag.

The stub broker needed all five methods the executor requires, taken from
`broker_capability_report` rather than guessed — the first version was missing two and every
armed test failed at construction. And `on_submit` is a **named** parameter, not swallowed by
`**kw`: `accepts_receipt` inspects the signature, so a stub hiding it would have made the receipt
test skip while proving nothing.

**Pre-existing failures, classified against the recorded list from three stages ago**: four in the
Stage 5D suite, all in the Calm slot-split bucket. None introduced here.
