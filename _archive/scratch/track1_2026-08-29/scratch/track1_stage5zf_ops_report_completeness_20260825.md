# Stage 5ZF — ops and report completeness before paper

**2026-08-25, ET 12:55–13:40.** Audit, plus two small reader fixes it proved necessary · no
orders · no confirmation file · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · **nothing
restarted** · no IBKR call · no runtime evidence written or edited · no strategy change · no
scheduler change.

```text
UTC 17:40 · ET 13:40 EDT · Calgary 11:40 MDT · Tokyo 02:40 JST (26th)
```

---

## Verdicts

| | |
|---|---|
| next shadow window | **READY** |
| paper | **NOT_READY** |
| SPY_REFRESH_PM failure visible correctly | **now yes** — it was visible but unactionable; fixed |
| dashboard stale runner label | **fixed** — backend + rail, tested |
| Track 1 Flex / P&L / report | **MISSING** — not partial. Confirmed, not assumed |
| regime labelling consistent with two SPY updates | **yes** — by construction, with one caveat |
| any live/runtime file touched | **no** |

*Naming note: Stage 5ZE (job-view chip and operator diagnostics) is **complete**, not running.
This stage neither overwrote nor extended its UI.*

---

## 1. Job inventory — 101, nothing unclassified

Built by constructing the real scheduler in dry-run and enumerating it, not by counting source.

| class | n | ids |
|---|---:|---|
| Track 1 strategy | **70** | 1 Calm · 24 Stress · 23 Swing · 22 NKD |
| Track 1 safety | **11** | `track1_maxhold_exit` + 10 × `track1_stop_repair_*` |
| Track 1 audit | **5** | 4 per-sleeve + `track1_audit_daily` |
| shared infra | **4** | `preflight`, `heartbeat`, `session_report_fallback`, `spy_refresh_pm` |
| legacy drain safety | **11** | `maxhold_exit` + 10 × `stop_repair_*` |
| **unclassified** | **0** | — |

**Legacy strategy jobs: 0.** The scheduler logs `45 legacy strategy jobs not scheduled`.

Runtime, read-only: scheduler pid **48604** (unchanged since 01:07 ET), backend pid **35592**
(restarted 12:14 ET by the operator, not by this stage), `track1_mode=track1-only-shadow`,
`orders_possible=False`.

---

## 2. SPY_REFRESH_PM — visible, but it was saying nothing

Three of the four checks passed as-is:

- it runs through `_run(label="SPY_REFRESH_PM")`, so it emits the same started / completed /
  failed evidence every other job does. **No separate evidence system was needed and none was
  built;**
- it is **mirrored** in `schedule_status.PIPELINE_FIXED_SLOTS` at 16:20;
- it does **not** write `preflight_state.json` — measured by AST: `job_spy_refresh_pm` never
  calls `_save_preflight_state` and never touches `_preflight_ok`.

The fourth failed. `_job_type("SPY_REFRESH_PM")` returned **`other`**, the catch-all, so a
failure rendered:

> *The job emitted an unclassified error; completion and operational effects cannot be
> confirmed from this evidence.*

True of anything, and useful for nothing. This job's failure has one specific consequence, and
the reader can state it — so **the minimal reader fix was made**: a `spy_refresh_pm` type with a
real impact and action, for both the failed and the missed case.

```text
failed:  The daily SPY series was not refreshed after the close, so it is still a day short.
         Nothing is at risk right now; tomorrow's Track 1 slots will be refused by the
         freshness gate until the missing close is present.
missed:  ... and check whether the machine was asleep at the scheduled time.
```

The missed wording is deliberate: **33 stall events across 16 days** is the observed failure
mode, not a hypothetical.

---

## 3. The stale runner label — root cause confirmed, fixed

The suspicion in the prompt is exactly right, and now measured end to end:

```text
LIVE_STATE_PATH (legacy runner state)
  -> observed_at
  -> stale_against_latest   (older than the last expected slot, > 20 min)
  -> freshness = "stale"
  -> stripFreshness === 'stale'
  -> stripScheduleBad = true
  -> "scheduler attention required"
```

In track1-only shadow the 45 legacy strategy jobs are deliberately not registered, so **nothing
ever writes that file**. Its age grows without bound — measured live at **34.1 hours** — and the
rail reads *attention required* for the entire shadow period.

That is an alarm that never turns off, which is the same defect this module already fixed once
with `open_incidents`: an operator learns to ignore a light that is always on, and the next real
one is invisible.

### The fix, and why it is the narrowest one

`track1_only_enabled()` already existed. When it is true, a stale legacy snapshot no longer sets
`freshness`. Every other freshness branch reads the **scheduler log**, which in this mode
contains the Track 1 slots — so falling through gives a route-correct answer rather than a
legacy one.

**The staleness is demoted, not hidden.** A new `legacy_runner` block reports it by name:

```json
{ "inactive_by_design": true, "state_stale": true, "state_age_seconds": 122532,
  "reading": "legacy runner inactive / draining — its state file is stale by design in
              track1-only shadow, and does not describe the Track 1 route",
  "drain_safety_still_scheduled": true }
```

and `route_mode: "track1_only_shadow"` names the mode.

### What the rail says now, and it is true

Measured under the real mode: `stale` → **`late`**. Not a green light — a *different, genuine*
one. `unexplained_overdue` names `TRACK1_CALM_1000` and `TRACK1_STRESS_1035`: the slots the
machine slept through this morning.

**Before:** attention required, because a legacy file nobody writes was old.
**After:** attention required, because Track 1 slots did not run.

Outside track1-only the old behaviour is unchanged, and a test holds that — a fix that altered
the legacy route's own health reading would be a different bug.

### One thing that looked like a defect and was not

`track1_only_enabled()` returned `False` in my shell, which would have made the whole fix inert.
It reads `RAITS_TRACK1_ONLY`, which `monitor/ops.py:177` sets on the backend's environment and
my shell simply does not have. The live backend reports `state_slot_count: 70` — the Track 1
count — which is only possible if it *does* have the flag. Measured before reporting, because
"the mirror does not know the route mode" would have been a serious and wrong claim.

---

## 4. Signal diagnostics placement — the accepted contract

Stage 5ZD implemented the diagnostics and **Stage 5ZE is complete**, so this is a record of what
was built rather than a design left for later. It matches the accepted design exactly:

| rule | status |
|---|---|
| covers only the 70 strategy slots | **yes** — enforced in two places, and non-strategy jobs get no `signal` key at all |
| non-strategy jobs use operations health | **yes** — the Operational block, added in 5ZE |
| no expanded card per slot | **yes** — one chip inside the existing row |
| compact "Signals today" in the Track 1 panel | **yes** — counts only |
| per-job compact chip in the job view | **yes** — with a required plain-English tooltip |
| full `rule_checks` only when expanded | **stricter than asked** — they are on the payload under `debug` and **no code path renders them**, because every sleeve rule currently returns unmeasured |
| no raw developer names in the operator view | **yes** — tested against rendered output, not the file |
| no duplicated runtime detail inside signal diagnostics | **yes** — REFUSED/MISSED/NO DIAGNOSTICS point at Operational |

---

## 5. Route-aware report / Flex / P&L — **missing, not partial**

Measured by AST over string literals and imports, ignoring docstrings:

| module | Track 1 imports | Track 1 paths | legacy paths it reads |
|---|---|---|---|
| `global_index/session_report.py` | none | none | `live_positions.json` |
| `monitor/flex_pull.py` | none | none | — |
| `monitor/paper_pnl_compare.py` | none | none | `live_positions.json`, `trade_log.jsonl` |

The expectation in the prompt — *"shared jobs exist but Track 1 route-scoped evidence is not
fully ported"* — is **understated**. Not one of the three knows Track 1 exists.

### The sharpest gap, and it is not in those three

```python
# run_maxhold_exit.py:171   and   run_stop_repair.py:180
trade_log_path=str(_CWD / "trade_log.jsonl"),
```

Both are **Track 1's own safety jobs** — the scheduler passes them
`--positions-path live_positions.track1.json` — and both **hardcode the legacy trade log with no
route scoping**. The first Track 1 fill that a safety job later exits writes a CLOSE row into
the legacy log, indistinguishable from a legacy row. There is exactly one trade log on disk.

The route's own entry point is clean: `trade_log.jsonl` appears in `run_live_day_track1.py` only
inside `LEGACY_PATHS`, the list it must never write.

### Exact missing pieces before paper

| # | piece | state |
|---|---|---|
| 1 | Track 1 order journal → P&L reader | **missing** |
| 2 | `live_positions.track1.json` → open-position parity | **missing** |
| 3 | Track 1 fills → Flex statement reconcile | **missing** |
| 4 | Track 1 safety exits → a route-scoped reporting path | **missing, and actively wrong** — they write the legacy log |
| 5 | route-aware session report section, or a separate Track 1 report | **missing** |
| 6 | prevention of Track 1 rows folding into the legacy trade log | **missing** — see #4 |

Not implemented here. Six pieces is a stage of its own, and #4 is the one to do first because it
is the only one that *corrupts* an existing artefact rather than merely omitting a new one.

Five tests pin these as negatives. They fail if somebody implements Track 1 support and leaves
this report claiming it is absent — a finding nobody can falsify is not a finding.

---

## 6. Regime labelling and the two SPY refreshes

**`spy_daily_live.csv` is a close series only** — `date,close`, 2,424 rows. It is also the source
labels are derived from, but no label is in it.

**Labels are not persisted anywhere.** `regime.py` has zero persistence calls; `load_spy_regime`
runs the HMM decode on every read. So:

> **Both refresh times are sufficient by construction.** There is no materialisation step that
> could lag behind a SPY update, because there is no materialisation.

- **13:45** runs before the close and can never carry today's bar — and the gate does not ask
  for it. `required_daily_close_through` is the *last trading day before today*, the same answer
  all day.
- **16:20** writes today's close, which is exactly what the next morning needs.
- **Monday reads Friday**: `RegimeLabels.get` uses `asof(day − lag)`, so Monday with lag 1 asks
  for Sunday and gets Friday's label. Verified against a two-day series.
- **A Friday 16:20 refresh is enough for Monday** — `required_daily_close_through(Mon 09:00)`
  returns the Friday.
- **Holidays** use `prev_trading_day`, the same trading calendar as the requirement itself.

### The caveat, and it is real

`verify_regime_labels` **only ever warns**. Every path returns `0`:

```text
ImportError            -> warn, return 0
CSV load failure       -> warn, return 0
label_regimes failure  -> warn, return 0
labels actually changed-> warn, return count
```

Two consequences:

1. **A label drift does not fail the job.** `update_spy_csv` succeeds, the job journal shows
   success, and the dashboard shows nothing. The check exists specifically to catch an HMM refit
   changing labels on unchanged prices, and today it catches it into a log nobody reads.
2. **"Verified, no drift" and "could not verify" both return 0** — the tri-state defect this
   route has spent five stages removing from its broker reads, still standing here.

**Acceptable for shadow. Not acceptable for paper**, because a silent label change moves which
sleeve is permitted to trade. It should become a child failure — visible as the same job's
failure — before the first paper order. Not changed here: it is a behaviour change to a shared
job, and this stage's remit was reader-level.

---

## 7. Paper readiness, by blocker class

| blocker | class | blocks next shadow window | blocks paper | blocks live |
|---|---|---|---|---|
| `PAPER_SHADOW_EVIDENCE` (0 of 5 judgeable days) | evidence | no | **yes** | yes |
| `B1_broker_account_or_legacy_retirement` | operator | no | **yes** | yes |
| Track 1 route-aware P&L / Flex / report (6 pieces) | code | no | **yes** | yes |
| Track 1 safety exits writing the legacy trade log | code | no | **yes** | yes |
| regime label verification is warn-only | code | no | **yes** | yes |
| machine sleep (33 stalls, 22.1 h) | operator | **yes** | yes | yes |
| SPY_REFRESH_PM unactionable impact | UI/ops | no | no | no — **fixed** |
| stale runner label | UI/ops | no | no | no — **fixed** |

**Nothing on this list blocks the next shadow window except the machine sleeping**, which is an
operator power setting and was reported in Stage 5ZC.

---

## Files

```text
monitor/backend/job_journal_reader.py     + spy_refresh_pm job type, failed and missed impacts
monitor/backend/schedule_status.py        legacy staleness demoted; + legacy_runner, route_mode
global_index/dash/realtime/realtime.js    the rail no longer fires on an inactive legacy runner
scratch/test_track1_stage5zf_ops_report_completeness_20260825.py   33 tests
```

No strategy file, no scheduler file, no gate file, and no runtime evidence was touched.
