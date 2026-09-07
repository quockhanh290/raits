# Stage 5M-B — Normal-R4 shadow slots, without a provider

**2026-08-23 ·** no scheduler, backend, or dashboard started or stopped · no IBKR connection ·
no order · no `STOP_TRADING` or `STOP_TRADING.track1` touched · no confirmation file · no live
state file written · no commit.

---

## Verdict: **READY_FOR_5M_C_SWING_PROVIDER_MEASUREMENT**

All six blockers from 5M-A are closed and each one is held by a test that has been shown to go
red when the wiring is removed. **7 of 7 mutations detected.**

### What may be claimed after this stage, and what may not

**May:** Normal-R4 slots exist and can produce no-provider shadow evidence safely.

**May not:** anything about full Track 1 shadow. The 23 swing slots refuse by name with
`no_bar_provider` and exit. **No swing candidate has ever been produced from a live feed.** NKD
still has no slot at all, so the route remains three sleeves of four even on paper.

---

## What was built

| # | Blocker | Now |
|---|---|---|
| **N1** | no swing window | `WINDOWS_ET["roska4_swing"] = ("14:05", "15:55")` |
| **N2** | no slots | `_swing_slots()` derives **23** from that window; `TRACK1_SLOTS` = 1 Calm + 24 Stress + 23 Swing = **48** |
| **N3** | source refused the sleeve | `_swing_candidates()` — refuses `no_bar_provider`, not `sleeve_not_live` |
| **N4** | no admission rule | `REQUIREMENTS["roska4_swing"]`, 5-min bars, decides 14:05–15:55, no fixed decision bar |
| **N5** | coverage unmeasurable | `expected_slots("roska4_swing") = 23` |
| **N6** | window undeclared | `REQUIRED_ENTRY_WINDOWS` gains the swing band — and records that **no new stop-repair exclusion was needed** |

**Job inventory: 60 with the flag off, 107 with it on.** Exactly as 5M-A predicted.

### The slots mirror the legacy minutes exactly

Not "roughly the same times" — the same 23 minutes, asserted against the legacy triggers read
from the built scheduler. The measured rule takes the **first admitted signal** after the 14:00
resume bar, so a slot one minute off is a different rule wearing the same name, and the shadow
evidence it produced would not be evidence about what was backtested.

That is the expensive choice. It means two children now fire in the same minute, against a
legacy slot whose runs take a median of 194 s out of a 300 s window and a measured maximum of
291 s. Which is why they start without a provider.

### The provider is per-slot now, not per route

```
Calm 10:00, Stress 10:35-12:30  (25)   --bar-provider ibkr    unchanged since Stage 5I
Normal-R4 14:05-15:55           (23)   --bar-provider none    new
```

A `Slot` carries its own `provider`, and the scheduler closure reads it instead of the literal
`"ibkr"` it used to carry. A test asserts Calm and Stress come out of that change byte for byte
— a staging step that quietly altered production is not a staging step.

The real argv, captured by firing every Track 1 slot closure with the subprocess runner
replaced:

```
-m global_index.run_live_day_track1 --source live-shadow --sleeve roska4_swing
   --slot-id TRACK1_SWING_1405 --bar-provider none --regime-csv spy_daily_live.csv
```

No `--allow-orders`, no `--port`, no `--window`, on any of the 48. `RAITS_ROUTE=track1_candidate`
on all of them. The order gate still reports `B1_broker_account_or_legacy_retirement` open.

### The rule is the measured rule, not a second copy

`detect_entry_for_slot` reuses `_cache_for`, `_strategy`, `make_signal_fn` and `_scan_window`.
Nothing about the entry decision is re-derived, because a second implementation of an entry rule
proves nothing about the first — and this sleeve has committed artifacts a second implementation
would silently stop reproducing.

The one thing that could have gone wrong is truncating the scan window at the slot instant.
`_scan_window` takes its volume average by looking **backward** eleven bars from each candidate,
so cutting the tail cannot change the average at any bar that survives the cut. Measured on
vault2026 MES rather than argued:

```
days where the full-day scan finds a signal : 47
the slot at 15:55 finds the same signal     : 47 / 47
mismatches                                  : 0
signals returned from the future when asked early : 0
```

---

## A finding that came out of this, and it matters operationally

**The 23 swing slots are the first Track 1 slots that need the SAME-DAY 13:45 pre-flight.**

| Sleeve | Slots | Freshness contract |
|---|---|---|
| Calm | 1 | D-1 |
| Stress | 24 | D-1 |
| **Normal-R4** | **23** | **same-day** |

They fire *after* 13:45, so `track1_freshness.required_data_through` returns today, and the gate
demands a pre-flight record for today. That is correct — the data they read was refreshed at
13:45 — but until now every Track 1 slot ran on the previous business day's refresh, and a
failed pre-flight only stopped legacy. **Now it stops a Track 1 sleeve too.** It raises the
operational weight of Stage 5L's blocker L6 from "tidy the ownership" to "this is a shared
dependency with two dependents".

Worth saying how it surfaced: the Stage 5L test that asserted *every* Track 1 slot was a D-1
slot turned red — exactly as its own docstring predicted it would, word for word:

> *"If a slot is ever added after 13:45 this turns red, which is correct: that slot has a
> different contract and the difference should be a decision, not a discovery."*

It has been rewritten as a per-sleeve contract table plus a check that both sides of the
boundary are actually occupied, so it cannot pass vacuously if every sleeve drifts one way.

---

## A second behavioural change, and it is the intended one

Declaring the window did more than describe the sleeve — it made the route **enforce** it.

`track1_signal_layer.window_verdict` returns "always inside" for any sleeve with no declared
window, and its docstring named Normal and NKD as the two. Adding `roska4_swing` to
`WINDOWS_ET` moved Normal-R4 across that branch: a swing candidate stamped outside 14:05–15:55
is now **refused with `reject_window`**, before the same-symbol guard is ever consulted.

That is correct and it is the point of N1. The measured rule scans from the 14:00 resume bar and
takes the first admitted signal, so it cannot produce a candidate outside the window — anything
that does came from somewhere the rule did not.

It surfaced through two Stage 3 guard tests that built swing candidates at 10:00 and 11:00 as a
convenient fixture. One of them then passed its uniqueness assertion **on an empty list** — the
candidates were all refused, nothing was held, and "no duplicates" was true of nothing. The
suppression counter reading 0 is what gave it away. Both now stamp each candidate inside its own
sleeve's window, and the uniqueness check asserts the list is non-empty first.

The `window_verdict` docstring has been corrected: `global_nkd` is now the only sleeve on the
"no declared window" side.

---

## Documentation corrected

**`run_scheduler`** no longer says the Track 1 shadow route *"opens no broker connection"*. That
stopped being true in Stage 5I and the separate-mutex decision was resting on it. The comment
now states what is true per slot, and names clientId 89 versus legacy's 1 as the reason the
mutexes stay separate.

**The runbook** gained section 7: the root `STOP_TRADING` stops legacy entries and **does not
stop Track 1**, which reads its own `STOP_TRADING.track1`. For a shadow measurement that
separation is what you want; it also means "I placed `STOP_TRADING`, the system is stopped" is
false while the flag is on. To stand everything down, place both.

---

## Test results

| Suite | Result |
|---|---|
| **Stage 5M-B** `test_track1_stage5m_b_normal_r4_shadow_slots_20260823.py` | **38 passed** |
| **Stage 5M-B mutation harness** | **7 / 7 detected** |
| `…stage3b_blockers…` + `…stage5l_shared_preflight…` | 122 passed, 1 skipped |
| `monitor/test_schedule_status_track1…` + `monitor/test_ops.py` + `…stage5m1_fill_law…` | 52 passed |
| `…stage4_production_clean…` (artifact reproduction) | **25 passed, 1 skipped** |
| Track 1 live-path sweep (stage3 route, 3b, 4c, 5d, 5e, 5f, 5i, 5l, explain) | **255 passed, 2 skipped** after the stale-test corrections below |

`global_index/test_event_playback.py` **not run** — still the known hang.

### The mutations

```
S1  roska4_swing removed from WINDOWS_ET          → the window test reds
S2  the 23 swing slots removed                    → the inventory test reds
S3  the source stops serving the sleeve           → the source test reds
S4  the swing REQUIREMENTS entry removed          → the admission test reds
S5  the swing ledger window removed               → the coverage test reds
S6  swing slots given --bar-provider ibkr         → the provider test reds
S7  --allow-orders added to the slot body         → the order-flag test reds
```

S6 is the one that matters operationally: it is one word, it changes nothing visible in the
schedule, and it would put a second IBKR child on every legacy entry minute.

**S7 failed on its first run and the mutation was at fault, not the test.** It patched `_run` to
append the flag — but the test replaces `_run` with its own spy to capture argv, so the mutation
sat *downstream* of the capture point and the spy never saw it. A real regression would add the
flag to the slot **body**, upstream of `_run`. Rewritten to rebind the job closures, it is
detected. Same shape as the Stage 5L defect where a test exercised its own stub.

### Five tests from earlier stages went stale, and why each was updated

None was a regression; all five pinned the state at the time they were written rather than the
property they were about.

* **Stage 5L, D-1 slots** — the real finding above. Rewritten as a contract table.
* **Stage 3B, "unknown sleeve"** — it used `roska4_swing` as the stand-in for a sleeve the gate
  does not know. It now knows it. Repointed to a name chosen from outside the requirement table
  rather than one hoped to stay unknown.
* **Stage 3B, slot count `== 25`** — now derived from the window table, so an intended new
  sleeve does not turn it red while an unintended slot outside a window still does.
* **Two dashboard mirror tests, `== 25` and `== 70`** — each sat next to a correctly derived
  relation. The literals were dropped and the relations kept, plus an assertion that the Track 1
  mirror list is not empty so the comparison cannot pass on nothing.
* **Stage 5D and 5I, `len(on) == 84`** — both compared two totals to express "legacy must not
  change", which the totals never said. They now assert that `off - on` is exactly the displaced
  stop-repair sweep and `on - off` is exactly the Track 1 slot ids — which is the property, and
  which survives the next sleeve.
* **Stage 5I, the slot argv** — it parsed the SOURCE of `_track1_body` for the literal `"ibkr"`.
  That literal is now the variable `provider`, so source-parsing could only report a variable
  name. Rewritten to read the argv the scheduler actually builds, which is what it was always
  about.
* **Stage 5E and 5F, "unslotted sleeves"** — both parametrised over `roska4_swing` and
  `global_nkd`. NKD is now the only one, and the 5E table check that listed the two was
  narrowed to it.
* **Stage 4, `len(added) == 25`** — derived, plus a non-empty assertion.
* **Stage 3, two guard tests** — the window-enforcement finding above.

Eleven in total. None was a regression; every one pinned a state rather than a property, and
each is now written so the next sleeve does not turn it red for a change it has no opinion
about.

---

## What is preserved, checked rather than asserted

* Order gate: `B1_broker_account_or_legacy_retirement` open, orders impossible.
* Live/shadow fill law: `production_gap_after_15min_break`, via `LIVE_FILL_LAW`. The swing
  candidates carry it in their own params, and a test pins that.
* Artifact reproduction: explicit `FILL_ARTIFACT`, untouched.
* Separate `live_positions.track1.json` and `replay_checkpoint.track1.json`.
* An AST scan asserts no production module outside `run_live_day.py` and `run_scheduler.py`
  references `global_index.run_live_day` — the swing sleeve cannot quietly borrow legacy's
  engine.
* Two tests hash the operator's state files and the real shadow directory around a full slot
  fire and require them unchanged.

---

## Next: Stage 5M-C

Switch the swing slots to a real provider — but only after the no-provider period has produced
the number nobody has: **what a Track 1 slot actually costs in wall-clock**, measured against a
legacy slot that already uses up to 97% of its 300-second window.

Until then this stage's claim stands exactly as stated: the slots exist, they refuse safely, and
they write down that they ran.
