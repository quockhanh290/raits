# Stage 5M-C — Normal-R4 provider readiness, and operator text that cannot go stale

**2026-08-23 ·** no scheduler started or stopped · **no real IBKR connection** (fake broker
only) · no order · no `STOP_TRADING`, `STOP_TRADING.track1` or confirmation file touched · no
live state file written · no commit.

---

## Verdict: **READY_FOR_5N_NKD_TRACK1_OWNERSHIP**

The Normal-R4 slots are ready for a provider, the full connect → fetch → decide → disconnect
path is proved on a fake broker, and the provider is **off by default** behind an explicit
switch.

**Still not true:** Track 1 is not a full route. NKD has no slot, so a shadow period covers
three sleeves of four — and with legacy frozen, the fourth is not traded by anyone.

---

## First: a blocker that Stage 5M-B shipped

`run_live_day_track1.py` declared its `--sleeve` argument with a hard-coded list:

```python
choices=[None, "roska4_calm", "roska4_stress"]
```

`roska4_swing` was not in it. The scheduler was building an argv that **argparse rejects**:

```
error: argument --sleeve: invalid choice: 'roska4_swing'
```

**All 23 swing slots would have failed at parse time, every day, before any of the route ran.**

**Why 5M-B's tests missed it.** They captured the argv the scheduler builds — correctly — and
then called `observe_live_slot` directly. Nothing drove the argv through `main()`. The two
halves were each right and the seam between them was never crossed. That is the same shape as
the phantom-job defect: a check that verified the parts and not the join.

Fixed by deriving the choices from `WINDOWS_ET`, so a new sleeve cannot be rejected by a list
nobody updated. Mutation **P5** puts the hard-coded list back and confirms the suite reds.

---

## The decision on the provider: staged, not switched on

The brief said the user accepts freezing legacy, which removes the reason 5M-B kept the swing
slots at `none`. **I checked that premise and it does not hold.**

`STOP_TRADING` **halts new entries. It does not stop legacy from running.** The check lives in
`runner.run_day`, and by the time it is reached the legacy slot has already:

* spawned its child,
* **connected to IBKR on clientId 1**,
* fetched bars for every instrument,
* rolled any contract expiring that day,
* run the exit path — positions still exit, deliberately,
* run the broker/file reconcile and stop checks.

So a frozen legacy slot costs nearly what a live one costs, and puts the same load on the
Gateway. The collision the swing slots would land in is **unchanged by the freeze**, and it has
never been measured — no Track 1 slot has ever run in production, and today no Track 1 window
overlaps a legacy entry window at all. Switching the provider on unconditionally would be
exactly the estimate-instead-of-measure move 5M-B avoided.

**So it is staged.** One environment variable, set per session by an operator who means it:

```powershell
$env:RAITS_TRACK1_SWING_PROVIDER = "ibkr"
```

| State | Result |
|---|---|
| unset or empty | `none` — the declared default |
| `ibkr` | the 23 swing slots connect, like Calm and Stress |
| anything else | **refused at scheduler build time; the scheduler does not start** |

Refusing a typo rather than falling back is the deliberate choice. A fallback to `none` looks
safer and is worse: an operator who typed `IBKR` would get a session that silently collected
nothing, conclude the switch was broken, and have no way to tell that from a session where the
slots ran and found no setups.

Two more properties, both tested: **Calm and Stress are not reachable by this variable** — a
session-scoped switch must not be able to turn off the sleeves that have been collecting since
Stage 5I — and the value is **resolved once at registration**, so a mid-session export cannot
split the window into two halves that ran differently.

---

## The provider path, proved on a fake broker

`build_bar_provider(broker_cls=...)` already had the seam. With a fake standing in for
`IBKRBroker`:

* it constructs on **clientId 89**, not legacy's 1;
* `connect()` is called, and `disconnect()` happens in the `finally` — **including when the
  route refuses**, which is the case that matters, since a leak is 23 connections a day all
  competing for one client id;
* `--bar-provider none` constructs **no broker at all**;
* an unknown kind is a named refusal, not a crash.

And end to end, a swing slot at 14:05 with the fake provider reaches:

```
reason  : decided        decided: True
fetched : MES, MNQ, MYM, M2K
ledger  : window_open, slot_observed
```

Freshness, the admission window, the join guard, the caps, the explanation writer and the ledger
all ran. The refusal has moved past `no_bar_provider`, which was the point of the stage.

### Four route guards caught my fixture before the test passed

Worth recording, because each one is a guard that would have caught a real defect and the
fixture is what was wrong every time:

| Refusal | What my fixture did |
|---|---|
| `no_frozen_half` | supplied a provider with no history to append to |
| `frozen_clock` | handed over naive history — "loaded by something other than `frozen_frame()`" |
| `bars_from_the_future` | the fake returned the whole session regardless of `through`; a real broker trims |
| `overlap_disagreement` | the fake feed and the frozen half disagreed on **276 of 276** shared timestamps |

The third and fourth are the NKD-corruption guards. A fake that hands back the future, or that
disagrees with history on shared bars, is not imitating a broker — it is imitating the bug. The
fake now trims at `through` and both halves are derived from one generator.

---

## Stale operator text, and a guard against the next one

Three places told an operator there were **25 Track 1 slots**. That had been wrong since
Stage 5M-B added 23 more. Nobody was misled yet — but a help string stating a stale fact is the
same defect as a comment that does, and correcting the number would only have reset the clock.

| File | Was | Now |
|---|---|---|
| `monitor/ops.py` | "adds the 25 Track 1 slots" ×3 | `ops.track1_slot_count()`, derived from `TRACK1_SLOTS` |
| `global_index/track1_gates.py` | "adds the 25 Track 1 slots" | states no count at all, and says why |
| `global_index/run_scheduler.py` | a 5M-B comment saying "25 slots" | corrected |
| `TRACK1_SWITCHOVER_RUNBOOK.md` | two mentions | rewritten |
| `track1_blocking_ledger_20260822.json` | generated from the gate registry | **regenerated**, not edited — only the evidence field differed |

The guard scans those five operator-facing files for a slot-or-job count and fails on any it
finds, allowing only lines that describe the old wording as history. It is itself checked
against strings that should trip it, so it cannot pass by having quietly stopped looking.

---

## Runbook

Section 8 added: what freezing legacy does and does not do, the exact command for a measured
provider session, and a table of what is still not true — NKD has no slot (Stage 5N) and the
safety jobs are still hard-wired to legacy's positions file with a shared max-hold marker
(Stage 5O).

---

## Test results

| Suite | Result |
|---|---|
| **Stage 5M-C** `test_track1_stage5m_c_swing_provider_readiness_20260823.py` | **38 passed** |
| **Stage 5M-C mutation harness** | **6 / 6 detected**, production files restored byte-for-byte |
| 5M-B + 5I + 5L + 3B + `monitor/test_ops.py` + mirror | **250 passed, 1 skipped**, then the ledger regenerated → **72 passed** |

`global_index/test_event_playback.py` **not run** — still the known hang.

```
P1  provider_for ignores the switch and returns ibkr    → the default test reds
P2  an unrecognised value falls back to none            → the typo test reds
P3  the switch also governs Calm and Stress             → the scope test reds
P4  disconnect is a no-op, so the connection leaks      → the finally test reds
P5  --sleeve choices hard-coded again                   → the slot path reds
P6  a hard-coded '25 Track 1 slots' returns             → the stale-text guard reds
```

P5 and P6 edit production files on disk; the harness asserts both come back byte-for-byte, and
they did.

---

## Preserved

No `--allow-orders` on any of the 48 slots, with the switch on **and** off. Gate still reports
`B1_broker_account_or_legacy_retirement`. `RAITS_ROUTE=track1_candidate` on all 48. Dashboard
parity true in both modes. No switch file created or removed. No scheduler start or stop. No
real IBKR.

---

## What is still not true

| Sleeve | Track 1 slots | Status |
|---|---|---|
| Calm | 1 | connected |
| Stress | 24 | connected |
| Normal-R4 | 23 | **staged — provider off unless switched on** |
| **NKD** | **0** | **no slot** |

Plus: **the swing slot's runtime against a live Gateway is still unmeasured.** That is what the
switch exists to allow, and the first session that uses it is the measurement, not the
conclusion.

**Next: Stage 5N** — NKD Track 1 ownership. Its strategy already matches legacy's (ema 10,
chandelier 2.5, five-day hold, lag 1), so it is a plumbing job rather than a port — and it is
the one that decides whether freezing legacy leaves a sleeve untraded.
