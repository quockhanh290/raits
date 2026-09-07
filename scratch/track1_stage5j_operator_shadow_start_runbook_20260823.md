# Stage 5J — operator runbook for the first Track 1 shadow start

**2026-08-23 · preparation only · no scheduler started, no IBKR connection, no order, no
dashboard runtime write, no `STOP_TRADING` created, no confirmation file, no commit.**

---

## Verdict: **READY_FOR_MANUAL_SHADOW_START**

**Shadow only.** Live orders remain blocked by B1, and this runbook contains no step that
unblocks them.

---

## The one thing to hold on to

**The first shadow start is the first time a real IBKR feed has ever reached this route.** Every
test to date injected a fake broker. The wiring is proved; the feed is not. So the first window
is an experiment whose expected outcomes include a *named refusal* — and a named refusal is a
pass, not a failure. Silence is the failure.

---

## [R] Read-only checks — safe to run any time, change nothing

Everything below was run at 2026-08-23 20:56 ET and its result is recorded beside it.

```powershell
# 1. is a scheduler already running?  (0 = none; >1 is the client-id collision failure)
@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*run_scheduler*' }).Count
```
→ **0**. `runner.pid` absent.

```powershell
# 2. gate state, confirmation file, order refusal
python -c "import sys; sys.path.insert(0,'.'); from global_index import track1_gates as g; print(g.live_frame_wiring()[0], [b.id for b in g.blocking()], g.self_check())"
python -m global_index.run_live_day_track1 --allow-orders --window vault2026   # expect exit 2
```
→ `True ['B1_broker_account_or_legacy_retirement'] []` · `--allow-orders` **exit 2** ·
no `track1_go_live_confirmation.json`.

```powershell
# 3. scheduler shape and dashboard parity — builds, never starts
python -c "import logging,sys; sys.path.insert(0,'.'); logging.disable(logging.CRITICAL); from global_index import run_scheduler as rs, track1_slots as ts; off={j.id for j in rs.make_scheduler(port=4002,dry_run=True,track1_shadow=False).get_jobs()}; on={j.id for j in rs.make_scheduler(port=4002,dry_run=True,track1_shadow=True).get_jobs()}; print(len(off),len(on),len([i for i in on if i.startswith('track1_')]),len([i for i in on if i.startswith('live_day')]),sorted(off-on)); print(ts.parity_report(track1_shadow=False)['in_parity'], ts.parity_report(track1_shadow=True)['in_parity'])"
```
→ `60 84 25 23 ['stop_repair_1220']` · parity `True True`.

```powershell
# 4. kill switches, env, legacy book
Test-Path STOP_TRADING ; Test-Path STOP_TRADING.track1
$env:RAITS_WINDOW_LEDGER_DIR ; $env:TRACK1_ORDERS_APPROVED
python -c "import json;d=json.load(open('live_positions.json'));print(len(d['positions']),d['breaker']['cur_day'])"
```
→ both switches **absent** · both env vars **unset** · legacy book **0 positions**, last day
`2026-08-21`.

**Dashboard `stale_code`:** it is `None` while nothing is running — "nothing running" is a
different state from "running stale code", deliberately. After the start it should read
**false**; if it reads true, the scheduler is running code older than the files on disk and
should be restarted rather than watched.

---

## [OP] Operator actions, in order — **none of these has been performed**

### 1. Confirm the intent: shadow only

No live orders. Nothing in this runbook writes `track1_go_live_confirmation.json`, sets
`TRACK1_ORDERS_APPROVED`, or passes `--allow-orders`. B1 stays open throughout; even if
`--allow-orders` were passed by hand it exits 2.

### 2. Create the legacy kill switch — **before any scheduler start**

```powershell
if (-not (Test-Path STOP_TRADING)) { New-Item -ItemType File STOP_TRADING }
```

**Why before, not after.** Shadow mode adds Track 1's 25 slots and removes exactly one legacy
job (`stop_repair_1220`). **All 23 legacy entry slots survive.** Starting the scheduler without
this file resumes legacy trading — the opposite of the intent, and nobody decided it.

`STOP_TRADING` blocks legacy **entries** and leaves exits, stop repairs and max-hold running,
which is what lets legacy drain. It is a different file from `STOP_TRADING.track1`, which is
Track 1's own switch and is not needed here.

### 3. Export the ledger directory — into the **scheduler's** environment

> **Corrected by Stage 5K0.** This step originally pointed at `D:\raits\scratch\track1_ledger`.
> `scratch/` is the directory this project treats as disposable, and a multi-day shadow
> period's coverage is **not reproducible** — nobody can re-observe a window that has closed.
> Sweeping scratch would have deleted the only copy of the evidence the go-live gate is read
> from. Operational evidence now lives under `global_index/track1_runtime/`.

```powershell
$env:RAITS_WINDOW_LEDGER_DIR = "D:\raits\global_index\track1_runtime\window_coverage"
New-Item -ItemType Directory -Force $env:RAITS_WINDOW_LEDGER_DIR

# optional, and worth setting on the first day: per-slot runtime, which is what the
# p95 < 300 s gate is judged from.
$env:RAITS_TELEMETRY_DIR = "D:\raits\global_index\track1_runtime\slot_timing"
New-Item -ItemType Directory -Force $env:RAITS_TELEMETRY_DIR
```

Both directories are git-ignored, so a shadow period cannot offer its runtime output for commit.

Unset means every Track 1 slot **hard-refuses** — verified: with it unset the slot exits 2 with
`ledger_not_configured` and **no broker is constructed**, so it will not even reach the feed. It
must be set in the shell that starts the scheduler, not merely in a shell you tested from.

### 4. Confirm the order approval is absent

```powershell
$env:TRACK1_ORDERS_APPROVED     # must print nothing
```

### 5. Start the scheduler in Track 1 shadow mode

```powershell
python -m global_index.run_scheduler --track1-shadow
```

**A start is not inert.** `_catch_up_maxhold` runs before the scheduler starts and, on a weekday
after 09:31 ET, immediately runs a max-hold pass that **reads the broker**. `STOP_TRADING` does
not prevent it — D5 governs entries, not exits, by design. Starting on a weekend or before 09:31
ET avoids it. The banner should list **84** jobs.

### 6. Watch the first Track 1 slot

Slot times, ET: **Calm A once at 10:00**, then **Stress every 5 minutes from 10:35 to 12:30**
(24 slots). The first thing to happen is the 10:00 Calm slot.

Each slot prints one line of the form:

```
slot TRACK1_CALM_1000 seq=0  decided=<bool>  reason=<named>
```

`reason` is one of: `decided` · `no_bar_provider` · `ledger_not_configured` ·
`live_source_not_ready` · `gate_refused` · `freshness_refused` · `stress_breadth_incomplete` ·
`regime_unavailable` · `cost_missing` · `stop_risk_unavailable`. **Any of these is an acceptable
first-day outcome provided it is named.** A slot that produces no line at all is not.

### 7. Inspect the ledger — by record, not by filename

```powershell
python -c "import sys; sys.path.insert(0,'.'); from global_index import window_ledger as wl; rows=wl.read_day('YYYY-MM-DD'); print([r['event'] for r in rows]); print(wl.status(rows,'roska4_calm','YYYY-MM-DD'))"
```

**Do not look for the file by today's ET date.** The file is named by the **UTC write date**
while the records carry the **ET session day**, so after 20:00 ET they differ. `read_day()`
filters on the record's own `date` field, which is why it is the supported way to look. (Today
the two happen to coincide — which is exactly what makes the trap intermittent.)

Expected first rows: `window_open` · `slot_observed` · `window_closed`.

### 8. Confirm the route identity

Every row must carry `route: "track1_candidate"`.

```powershell
python -c "import sys,json; sys.path.insert(0,'.'); from global_index import window_ledger as wl; print(sorted({r['route'] for r in wl.read_day('YYYY-MM-DD')}))"
```

They were previously stamped `legacy`, which filed Track 1's coverage under the route it exists
to replace. `['track1_candidate']` is the pass. Anything containing `legacy` means the child
environment is wrong — stop and report.

### 9. Confirm no orders were sent and no legacy artefacts moved

- each slot prints `send_order calls: 0`
- `trade_log.jsonl` mtime unchanged
- `live_positions.json` unchanged, still `positions: []`
- `track1_go_live_confirmation.json` still absent
- no `live_day_*.log` entry showing a legacy entry — every legacy run should log
  `D5: STOP_FILE present`

### 10. Confirm the checkpoint rule

A checkpoint is written **only** after a window whose expected slots all decided. An incomplete
window prints:

```
checkpoint: NOT written — the window did not complete
```

That is correct behaviour, not an error. `global_index/replay_checkpoint.track1.json` appearing
after an incomplete window would be the defect.

### 11. If the feed fails: stop and report

A provider or feed error on the first real connection is the **expected class of surprise** — it
is the first time this path has touched IBKR. Capture the slot line, the ledger rows and the
scheduler log, and stop. **Do not improvise a fix against a live feed.** The refusal vocabulary
exists so the failure is legible afterwards.

### 12. Continue only if the first window is clean

Judged against the criteria below, not by impression.

---

## Acceptance criteria — first day

**Pass:**
- Track 1 slots fired at their scheduled times (1 Calm, 24 Stress).
- Ledger rows exist for both windows.
- Every row carries `route=track1_candidate`.
- No orders; no confirmation file; no legacy entry after `STOP_TRADING`.
- A named refusal — freshness, provider, no signal — **counts as a pass**.
- A window is `complete` only when every expected slot decided.
- A checkpoint exists only for a complete window.
- Runtime telemetry captured if `RAITS_TELEMETRY_DIR` was set.

**Fail:**
- **Silent success: a slot that ran with no ledger row.** This is the one that matters most,
  because it looks like nothing happened.
- Any row under `route=legacy`.
- A legacy entry taken after `STOP_TRADING` was placed.
- A checkpoint written for an incomplete window.
- `stale_code` true on the dashboard.

## Acceptance criteria — the multi-day gate

- Coverage `complete` on **every** trading day of the measured period, both windows — not most.
- `track1_bootstrap.accepts(...)` returns `Resumed` for every checkpointed sleeve and instrument.
- Runtime **p95 < 300 s**, target **< 240 s**. The Track 1 provider's cost is **unmeasured** —
  no claim can be made about it until real shadow telemetry exists.
- No scheduler stall or machine sleep inside either window; a mutex skip, a misfire or a grace
  overrun marks the day **invalid**, not partial.
- No legacy trading resumed.
- No unexplained dashboard incidents.
- **No broker-flat or orphan-STP claim** — those need IBKR and are checked separately.

---

## What makes accidental go-live hard

Four independent things would each have to be done deliberately, and **this runbook contains
none of them**:

| | required to trade | present here |
|---|---|---|
| `track1_go_live_confirmation.json` | must exist and validate | **no step writes it** |
| `TRACK1_ORDERS_APPROVED=1` | must be exported | **step 4 checks it is unset** |
| `--allow-orders` | must be passed | **no step passes it; slot argv excludes it** |
| B1 | must be released | **still open — `blocking()` returns it** |

And the belt underneath: the shadow route holds a `NoOrderBroker` whose `send_order` raises, and
`observe_live_slot` never calls it — verified by parsing the function's call graph, not by
reading it.

---

## Checks run for this stage

| check | result |
|---|---|
| gate: wiring released / blocking / self_check / confirmation | True / `['B1…']` / `[]` / absent |
| `--allow-orders` | **exit 2** |
| scheduler OFF / ON, slots, legacy entries, removal | 60 / 84 · 25 · 23 · `['stop_repair_1220']` |
| dashboard parity OFF / ON | True / True |
| Track 1 argv, captured from the real job closure | `--source live-shadow --sleeve --slot-id --bar-provider ibkr --regime-csv`; no `--allow-orders`/`--window`/`--port` |
| child route: Track 1 / legacy | `track1_candidate` / `legacy` |
| ledger unset → refusal before a broker is built | exit 2, `ledger_not_configured`, `ib_insync` not imported |
| ledger set → rows and status | `window_open`·`slot_observed`·`window_closed`, `incomplete 0/1`, route `track1_candidate` |
| checkpoint on an incomplete window | not written |
| Stage 5I suite | **19 passed** |
| real `scratch/track1_shadow` | clean |

`global_index/test_event_playback.py` was not run. No live IBKR was contacted.

---

## No side effects

No scheduler started or stopped (0 processes). No IBKR connection. No orders. No dashboard
runtime write. **No `STOP_TRADING` created** — step 2 is written for the operator, not performed.
No `STOP_TRADING.track1`. No `track1_go_live_confirmation.json`. `TRACK1_ORDERS_APPROVED` unset.
No commit — `HEAD` unchanged. The only files written are this runbook and its JSON, both under
`scratch/`.

---

Stage 5J complete: READY_FOR_MANUAL_SHADOW_START. Operator may create STOP_TRADING, export RAITS_WINDOW_LEDGER_DIR, and start scheduler with --track1-shadow. This is shadow only; live orders remain blocked by B1.
