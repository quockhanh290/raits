# Stage 5F — the Stress rule, promoted and proved

**2026-08-23 · no scheduler started, no IBKR connection, no order, no dashboard write, no
`STOP_TRADING`, no confirmation file, no repo route state, no commit.**

---

## Verdict: **READY_FOR_BROKER_PROVIDER_SHADOW**

Precondition 2b is **closed offline for both slotted sleeves**. The Stress rule was promoted out
of scratch and reproduces the canonical chain **exactly**. The live source now answers in both
windows instead of refusing on 24 of the 25 slots.

> **Not claimed:** that a broker provider works — every test injects `FrameBarProvider` and no
> IBKR object is ever constructed. Not claimed: that Track 1 can trade. B1 is untouched and
> still the only thing holding the order gate.

---

## 1. The canonical rule, traced not remembered

`mnq_only_g3_q7`, documented in `docs/futures/NORMAL_STRESS_CANDIDATES_2026-08-22.md` and
implemented across two scratch scripts. The chain that reached the measured Track 1 book:

```
stress_with_nkd_probe.load_r4_and_nkd
  -> stress_switch_full_replay.load_stress(Scenario("mnq_only_g3_q7", ("MNQ",), 7))
     -> stress_open_search.load_window / build_day_cache
     -> build_rule_with_levels
  -> combined_stop_risk_audit.load_all  ->  track1_replay_source.candidates
```

Every threshold was read off the `Rule` that produced the book, not reconstructed:

| | value |
|---|---|
| instrument / direction / qty | MNQ · SHORT · **7** |
| setup · known · entry window · exit | 10:30 · 10:35 · 10:35–12:30 · 15:55 |
| breadth | all **4** R4 instruments below both the day open and the session VWAP |
| gap down | at least **3** of 4 at ≤ **−0.4%**, and the mean gap ≤ **−0.1%** |
| entry | first 1-min bar breaking the 09:30–10:30 low; filled at `min(open, level)` |
| stop / target | `pre_high × 1.001` · `entry − 1.5 × (stop − entry)` |
| reject | a stop further than **2%** of entry |
| risk | `(stop − entry) × point_value × qty` |

**There is no regime label anywhere in this rule.** It was built deliberately to avoid the lag-0
daily `Stress` label an earlier candidate leaked on — so there is no D-1 lookup to get wrong, and
a test proves it by handing the source an empty label map and still getting the candidate.

---

## 2. Equivalence — exact, on all three windows

`global_index/track1_stress_mnq.py` against the scratch chain, comparing day, instrument,
direction, entry and exit times, entry, stop, target, exit, exit reason, qty, sized P&L and
sized risk:

| window | rows | P&L (sized) | identical |
|---|---|---|---|
| vault2026 | 4 | −$405.72 | **yes** |
| vault2025 | 3 | +$4,530.96 | **yes** |
| floor | 50 | +$23,748.85 | **yes** |

**57 trades, every compared field identical, P&L delta $0.000000.** Not a tolerance — equality.

---

## 3. Causality, which is where a 10:35 slot goes wrong

**The setup bar is left-labelled.** The 5-minute bar stamped 10:30 covers 10:30 up to 10:35, so
its close is not known until 10:35 — which is exactly why the entry window starts there and why
the original context carries `known_time = signal_time + 5 minutes`. The entry scan begins at the
first 1-minute bar stamped 10:35, the first bar that is not inside the setup bar. No bar is used
twice and none before it closed.

**The entry scan is bounded by the slot instant.** A slot at 11:00 may see a break that happened
at 10:40 and not one that will happen at 11:30.

**No same-bar exit.** `exit_conditions` scans strictly after the entry bar, and within a bar the
stop is checked before the target — the pessimistic side when one bar spans both.

**Verified on a real day, not only on synthetic bars.** 2026-02-05 from the measured book:

| slot | live-path result |
|---|---|
| 10:35 | `[]` |
| 11:00 | `[]` |
| **11:14** | 1 candidate — entry **25085.75**, stop **25521.99650**, qty 7, risk **$6,107.45** |
| 11:15, 12:30 | same candidate, unchanged |

The historical row for that day is entry 25085.75 at 11:14. The live slot finds it at 11:14 and
not a minute earlier.

---

## 4. Refusal versus empty list, kept

An **empty list** means the rule ran and the basket was not stressed, or it was and never broke
the low. Both are answers. These are refusals, and each is named:

`no_bar_provider` · `stress_breadth_incomplete` · `cost_missing` · `stop_risk_unavailable` ·
`sleeve_not_live` · `no_sleeve_at_this_instant`

`stress_breadth_incomplete` is new and load-bearing: `below_count` is a count out of **four**, so
running the rule on three instruments would quietly lower the bar it was measured at. A missing
instrument stops the slot rather than shrinking the basket.

---

## 5. Sizing

Quantity 7 rides on the **candidate**, not on a symbol table — MNQ is one micro under Normal and
seven under Stress on the same day, and `contracts_by_inst[inst]` has no key that can say so.
Risk is `abs(stop − entry) × point_value × qty`, so widening `stop_pad` moves the stop and moves
the risk, which a multiple-of-ATR formula could not do. Costs are 2 ticks a side, the slippage
the measured rows were built under.

---

## 6. Two things the tests found

**The detector rejected my first synthetic setup, and it was right.** A session that fell four
points on a 98 price put the stop 4.4% from entry, past the rule's own 2% `max_stop_pct`. The
fixture was a violent market, not a stressed one.

**And the first fixture was not even falling.** Pinning `low` to a constant floor dragged the
typical-price VWAP below every close, so `below` was false on a session that was plainly
declining. Both fixture bugs, both caught by the rule refusing to fire — which is the right
direction for a detector to fail in.

---

## 7. Two superseded tests, re-pointed

Stage 5E and Stage 5D each asserted that the Stress window refuses with
`stress_rule_not_in_package`. That is precisely what this stage removed, so both went red —
correctly. Asserting the old refusal would have pinned the gap in place. Both now require the
window to **answer**, and neither claims anything about a broker.

---

## 8. Tests

| suite | result |
|---|---|
| Stage 5F Stress live source (new) | **30 passed, 1 skipped** — and **31 passed** with `TRACK1_STAGE5F_EQUIV=1`, which runs the full three-window equivalence |
| Stage 5E live source | **30 passed** |
| Stage 5D shadow-live wiring | **18 passed** |
| Stage 5C shadow readiness | **11 passed** |
| Stage 5B runbook fix | **22 passed** |
| Stage 4C · 3B · Stage 3 route | **159 passed, 2 skipped** |

`global_index/test_event_playback.py` was not run.

**The Stage 4 all-window suite was not re-run.** Nothing in this stage touches a sleeve the
Stage 4 book measures: `track1_stress_mnq.py` is a new file, and the Stress rows in the measured
book come from the scratch chain, which is unchanged and is the thing this stage compares
against. The Calm A and Normal-R4 generators were not modified.

---

## 9. What remains

1. **A real bar provider** — `IBKRBarProvider` wrapping the runner's existing broker. It cannot
   be built or tested without a broker, and until it exists no shadow day can produce a frame.
   This is now the *only* thing between the route and a shadow period that collects.
2. **B1** — legacy retirement or a separate account. Unchanged, and still the only thing holding
   the order gate: `blocking()` returns it alone, no confirmation file exists, and
   `TRACK1_ORDERS_APPROVED` is unset.

Both windows are answerable offline. That is not the same as tradeable, and this report does not
say it is.
