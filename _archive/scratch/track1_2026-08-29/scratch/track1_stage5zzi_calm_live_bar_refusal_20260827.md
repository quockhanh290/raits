# Stage 5ZZI — why Calm refused, and why the record could not say so

**2026-08-27.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED` never set · no
orders directory · nothing restarted · no runtime evidence modified or deleted. One read-only
IBKR probe on client id **95**, reported below.

---

## The seven answers

| | |
|---|---|
| **1. Root cause of the Calm refusal?** | The bar feed answered every request with **no bars**. Both phases asked for bars they could causally have had; there were none to have |
| **2. Which gate condition failed, and why?** | DECIDE: `missing_session, stale, partial_coverage`. OBSERVE: those plus `entry_quote_absent`. All four are downstream of one fact — today's session bars were never in the frame |
| **3. Fix class?** | **PROVIDER_LAG** for the refusal — external, an operator action, no code change. **EVIDENCE_BUG** for the record, and that part is fixed here |
| **4. Was the refusal correct?** | **Yes.** Reproduced offline, same codes; and the same rule ALLOWS both phases the moment bars are present |
| **5. Code changed?** | Only the evidence path — the provider, the joined frame, and the observation row. **No requirement, no threshold, no strategy meaning** |
| **6. Operator action needed?** | **Yes.** Only one TWS/Gateway login may hold this account. The gateway is refusing the historical data service because the session is held from another address |
| **7. Tests?** | 19 new, **6/6 mutations RED**, 164 passed across the named regression suites; 7 pre-existing failures classified (all the deferred Calm slot-split roster pins) |

---

## 1. What actually happened

Both Calm phases ran on schedule and both refused:

```text
09:32:06 ET  TRACK1_CALM_DECIDE_0932   missing_session, stale, partial_coverage
10:02:10 ET  TRACK1_CALM_OBSERVE_1002  missing_session, entry_quote_absent, stale,
                                       partial_coverage
```

Their own data-observation rows say what the gate was handed:

```text
live_rows_fetched  0        splice_result  nothing_new
live_rows_offered  0        splice_detail  no live bars offered
live_rows_appended 0        provider_error null
final_frame_last_ts          2026-08-26 13:44:00-04:00
```

**The join dropped nothing, because there was nothing to drop.** `final_frame_last_ts` is the
parquet's own 13:45 ET append boundary from yesterday — the frozen half, untouched, with no
live half laid on top of it.

## 2. It is not Calm's problem, and not today's schedule

The same zero appears everywhere the feed was asked, and nowhere it was not:

```text
2026-08-27  01:10-02:55 ET  MNKD  1,806 -> 1,910 rows per slot   the overnight sleeve, fine
2026-08-27  09:32, 10:02    MES/MNQ    0 rows                     both Calm phases
2026-08-27  10:35 onward    MNQ        0 rows                     Stress, same
```

The boundary is sharp and it is in the route's own evidence:

```text
last fetch with rows   2026-08-27T06:55:35Z   TRACK1_NKD_0255   MNKD  1,910
first fetch with none  2026-08-27T07:05:10Z   TRACK1_CALM_1000  MES       0
```

Between 02:55 and 03:05 ET the feed stopped answering, and it has not answered since. Yesterday
the same instruments fetched 2,340 and 121,464 rows without complaint. The roll table is not
involved: MES and MNQ front month is 202609, rolled 2026-06-12, next roll 2026-09-11.

## 3. What the feed was actually saying

**Read-only probe, client id 95, no orders, no writes:**

```text
IBKR code=162: Historical Market Data Service error message:
               Trading TWS session is connected from a different IP address
MES rows=0   MNQ rows=0   NKD rows=0
```

The account's TWS/Gateway session is held from another address, and IB restricts the historical
data service while that is true. Nothing about this route caused it and nothing in this route
can fix it.

## 4. The part that is a code defect

The refusal was correct. **The silence was not.**

```python
# global_index/ibkr_broker.py, _fetch_raw
if not bars:
    return pd.DataFrame()          # the market was quiet
...
except Exception as exc:
    log.error(...)
    return pd.DataFrame()          # the request failed
```

ib_insync does not raise on error 162 — it emits the message on an event and returns an empty
list. So a refused request and a quiet market arrive at the join as the same value, and the
difference is gone before anything downstream can write it down. Every row for three days read
`provider_error: null`, which says *there were no bars* when the truth was *the data service
declined to give any*.

That is the failure family this project keeps finding: **an empty answer standing in for an
error.** It is the same shape as the scheduler process scan that returned `[]` for "none
running" and `[]` for "I could not look".

### The fix

Three hops, each of them narrow:

```text
IBKRBarProvider.fetch_session_bars   listens on errorEvent while the request is in flight,
                                     keeps named historical-service refusals in `last_error`
JoinedFrame.provider_error           carries it, and as_dict carries it out
the data observation row             emits it, or None when the feed genuinely said nothing
```

Fail-soft in every direction: a broker with no session, an event that will not take a handler,
an attribute that raises — all leave `last_error` empty and the fetch behaves exactly as
before. Unrelated IBKR chatter (`2104 Market data farm connection is OK`) is not collected; a
row that gathered everything would fill with connection notices and stop being read. The handler
is removed in a `finally`, because one added per fetch and never removed is 25 listeners a day.

**No requirement, threshold, window, or strategy rule was touched.** Shadow and paper still read
the identical path.

## 5. Reproduced, both ways

Offline, from recorded parquet, with no provider and no network:

```text
provider offers nothing
  DECIDE  09:32  ALLOW=False  missing_session, stale, partial_coverage           == recorded
  OBSERVE 10:02  ALLOW=False  missing_session, entry_quote_absent, stale,
                              partial_coverage                                   == recorded

the same fetch, answering with the two days it is configured to ask for
  DECIDE  09:32  ALLOW=True   []
  OBSERVE 10:02  ALLOW=True   []
```

The second run is the one that settles it. The requirement is not impossible and the clock is
not wrong — the rule passes the moment the bars exist.

One detail worth keeping: a stub offering only *today* still left `partial_coverage` standing,
because the frozen parquet stops at yesterday 13:44 and yesterday's 13:45–16:00 close normally
arrives on the same live fetch. That is why the provider's duration is `2 D`. A test built on
the narrower stub would have "found" a requirement bug that is really the stub's own shape.

## 6. The eight cause questions

| | |
|---|---|
| Did the provider return bars at all? | **No.** Zero, on every instrument, from 03:05 ET |
| Did the join drop them? | **No.** `offered 0, appended 0` — nothing to drop |
| Was the requirement asking for a bar that cannot exist yet? | **No.** DECIDE needs the 09:30 bar, closed 09:31, fires 09:32. OBSERVE needs 10:00, closed 10:01, fires 10:02 |
| Was the clock wrong? | **No.** The same frames pass at the same instants once bars are present |
| Was it the stale daily SPY file? | **No.** Repaired before the window; `freshness_refused` is not among the reasons |
| Was it Calm-specific? | **No.** Stress fetched zero too; NKD fetched normally before the boundary |
| Was it the roll? | **No.** Front month 202609, next roll 2026-09-11 |
| Was the evidence able to say any of this? | **No** — and that is the defect fixed here |

## 7. What is verified and what is inferred

Kept apart deliberately, because they are not the same strength of claim.

- **Verified:** every fetch from 03:05 ET returned zero rows; the boundary at 06:55:35Z /
  07:05:10Z; the gate codes and their reproduction; that the probe on client id 95 received
  error 162 and zero rows for all three instruments.
- **Inferred:** that error 162 was the answer to the 09:32 and 10:02 fetches *specifically*.
  The probe ran later in the morning, and the slots' own rows cannot say, **because the field
  did not exist yet**. The inference is strong — one continuous outage, one boundary, one
  named cause at the same gateway — and it is exactly the inference nobody should have to make.
  From the next fetch onward the row will say it outright.

## 8. Operator action

**No code change will restore the bars.** The account's market-data session is held from another
IP address; while that is true IB will keep declining historical requests.

```text
1. Find the other TWS or IB Gateway logged into this account and log it out.
   Only ONE session may hold the account, and paper and live count as the same login.
2. Confirm with a read-only fetch — a slot's own row will now carry the reason if it is
   still refused, rather than a bare zero.
3. Until the feed answers, every Track 1 slot will refuse. That is correct behaviour:
   the day classifies incomplete and does not count.
```

Nothing needs restarting on this machine, and no runtime evidence should be cleared. The
refusals are the record of a day the feed was down, and they are worth keeping as exactly that.

## 9. Tests

**19** in `scratch/test_track1_stage5zzi_calm_live_bar_refusal_20260827.py`. No broker is
contacted; nothing writes to the runtime tree.

The four the stage named, plus the evidence half: a named refusal reaches the provider, the
joined frame and the row; a quiet feed does **not**; the two are distinguishable side by side;
unrelated chatter is ignored; a repeated message is recorded once; the handler does not outlive
the fetch, including when the fetch raises; a previous fetch's message does not carry over; and
a broker with no session behaves exactly as before.

**6/6 mutations RED**, source-level in a subprocess, every file restored byte-identical:

```text
the listener stops collecting                              RED
the frame carries it but as_dict drops it                  RED
an absent message becomes an empty string in the row       RED
the handler is left attached after the fetch               RED
DECIDE may ask for the bar still forming at its own instant RED
OBSERVE stops needing the entry quote bar                  RED
```

Two of those were not written correctly the first time. `as_dict` did not carry the new field
at all — a field added to a dataclass and shown to nobody, which is the same defect one layer
up. And the mutation harness itself skipped three mutations silently: these files are CRLF on
disk, so any anchor written with a bare newline matched nothing, and **a skipped mutation reads
in the output as "we tried" while proving exactly as much as not running it.** Both were found
by looking at the harness output rather than at its summary line.

A test also found a real gap in the fix: `hasattr` only swallows `AttributeError`, so a
property raising anything else took the whole fetch down with it. The attach is now guarded
outright — a diagnostic that can break a fetch is worse than no diagnostic.

**Regression suites named by the stage:** 164 passed. **7 pre-existing failures**, all in 5ZA
and 5ZB, all the same deferred family — `71 == 70` slot count, `roska4_calm: 2` against a pinned
`1`, and a test gating DECIDE with the unsplit sleeve's 10:00 rule. Neither suite reads any
field this stage touched.

## 10. Where the route stands

Orders remain impossible: `B1_broker_account_or_legacy_retirement` and
`PAPER_SHADOW_EVIDENCE` both still block, `orders_possible` is False, no confirmation file, no
orders directory.

Track 1's machinery did the right thing all morning. It asked, it was given nothing, it refused,
and it wrote down that it refused. The only thing it could not do was say **why** — and it can
now.
