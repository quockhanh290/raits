# Stage 5ZA - post-stage causal slot audit

Verdict: **READY_FOR_NEXT_SHADOW_WINDOW_WITH_CAUSAL_SLOT_GUARD**.

This was the audit raised after 5V-1: do not wait for a live window to discover that a
five-minute slot is accidentally asking for the end of its whole window/session.

## What was swept

The new suite walks all **70 Track 1 strategy slots**:

| sleeve | slots |
|---|---:|
| `roska4_calm` | 1 |
| `roska4_stress` | 24 |
| `roska4_swing` | 23 |
| `global_nkd` | 22 |

For each slot it builds a synthetic partial frame containing only the bars that slot is
causally allowed to require, then runs `track1_intraday.validate()` at the slot instant plus
three seconds. The assertion is direct: no slot may demand the end of its window/session, and
no slot may fail `partial_coverage` or `stale` on bars that are legitimately not available yet.

Static seams are also pinned:

- every live-source sleeve fetches bars with `through=now`;
- Stress truncates its entry scan with `end = min(end, hhmm)`;
- Normal-R4 and NKD truncate their scan to `widx_naive <= now_ts`;
- Calm uses `detect_entry_for_day`, not the full-day replay detector;
- the paper callsite seam is `observe_live_slot`, not `run_shadow`.

## Finding fixed

`TRACK1_CALM_1000` had a hidden one-shot clock defect:

| instant | before | after |
|---|---|---|
| `10:00:00` | allow | allow |
| `10:00:01` | `too_late` | allow |
| `10:00:03` | `too_late` | allow |
| `10:01:01` | `too_late` | `too_late` |

The scheduler child naturally starts a few seconds after its nominal minute. Without a small
dispatch grace, the route would have observed a correct Calm slot as late the first day the
splice/data path reached the gate. The fix is a 60-second `decision_grace_seconds` on the
intraday requirement: seconds of dispatch latency are still the scheduled slot; beyond the
grace it still fails closed.

The same rule updates the final scanning-window slot: a few seconds after the final minute is
still the final slot. A genuinely late row remains `too_late`, and the acceptance module still
classifies that as observed-window-shut rather than as a hard data refusal.

## Tests

```text
scratch/test_track1_stage5za_causal_slot_audit_20260825.py        9 passed
scratch/test_track1_stage5v1_intraday_causality_20260825.py       31 passed
combined                                                         40 passed
```

No mutation pass was run for 5ZA yet. The direct test did catch one production defect; mutation
proof is still worth doing before paper.

## Still pending operational audit

- Runtime verification after the next judgeable window: audit row, timing rows, explanation
  rows, and no phantom dashboard overdue row.
- First-paper safety watch: the first paper fill activates 11 Track 1 safety jobs that have
  never protected a real Track 1 book.
- Mutation pass for this new causal audit.

## Safety

No scheduler/backend restart, no IBKR connection, no order, no runtime evidence edited, no
confirmation file, and `TRACK1_ORDERS_APPROVED` remains unset.
