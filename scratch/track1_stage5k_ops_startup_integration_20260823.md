# Stage 5K — ops startup integration for Track 1 shadow

**2026-08-23 · no service started, no IBKR connection, no order, no dashboard runtime write, no
`STOP_TRADING`, no `STOP_TRADING.track1`, no confirmation file, no commit.**

---

## Verdict: **READY_TO_START_TRACK1_SHADOW_VIA_OPS**

…with one correction that changes the operator's first command, and that I owe you plainly.

---

## Correction first: a scheduler has been running the whole time

Every stage of mine since 5C reported **"0 scheduler processes"**. That was wrong. My probe
filtered `Name='python.exe'`, and `monitor/ops.py` launches the scheduler with **`pythonw.exe`**.

`ops.scheduler_processes()` — the project's own function, which I should have used from the
start — reports:

```
pid     : 36656
started : 2026-08-20 06:35:53   (3d 12h ago)
cmd     : pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume
```

**Consequences:**

- Stage 5H's open question — *"why is the scheduler down, and was it deliberate?"* — dissolves.
  It was never down. There is no incident to investigate.
- The legacy route has been running normally throughout, which matches the evidence I had and
  misread: `live_positions.json` shows `cur_day 2026-08-21`, the last trading day, and
  `positions: []`. I read a flat book as a stopped system.
- **That scheduler is running code from before today's edits** — `run_scheduler.py` was last
  written at 18:23 today. It predates the Track 1 slot argv, the route stamping, everything.

This also changes the first operator command: `up` deliberately leaves a healthy scheduler
alone, so **`up --track1-shadow` would have done nothing at all**. That trap is now closed in
code — see below.

---

## What changed

`monitor/ops.py` only. Legacy behaviour is untouched when the flag is absent, and a test asserts
the argv difference is exactly one element.

**1. `--track1-shadow` on `up` and `restart`.** When set, `--track1-shadow` is appended to the
scheduler command.

**2. A Track 1 child environment.** `RAITS_WINDOW_LEDGER_DIR` and `RAITS_TELEMETRY_DIR` are set
to the durable Stage 5K0 paths — `global_index/track1_runtime/window_coverage` and
`.../slot_timing` — via `setdefault`, so an explicit export still wins. The launcher fills a gap;
it does not overrule a decision. Without this the operator exports by hand into the wrong shell
and gets a scheduler whose slots hard-refuse with `ledger_not_configured`, collecting nothing.

**3. `TRACK1_ORDERS_APPROVED` is removed from the child**, whatever the launching shell carries.
It is one of the two factors that arm Track 1, and a launcher must never be the thing that
supplies it. Legacy children are unaffected.

**4. Fail-closed preflight**, `track1_shadow_blockers()`:

- `track1_go_live_confirmation.json` **present** → refuse. That file arms the route; a *shadow*
  start must not run beside it.
- `STOP_TRADING` **absent** → refuse. Shadow mode adds Track 1's 25 slots and removes exactly one
  legacy job — **all 23 legacy entry slots survive** — so starting without the kill switch
  resumes legacy trading, silently. The refusal says why and gives the command.

Neither file is created by ops. Fail-closed, as preferred.

**5. A no-op flag is refused.** If a scheduler is already running and `up` would leave it alone,
`--track1-shadow` cannot take effect. Rather than print a banner and change nothing — leaving an
operator waiting days for evidence never being written — it returns 2 and names the right
command.

**6. Status.** `ops.py status` now prints a Track 1 block: mode, both evidence directories and
whether they exist, `STOP_TRADING`, the confirmation file, the order env, `blocking()` and
`orders_possible`. The **mode is read from the running process's own command line**, not from a
flag someone remembers passing — which is precisely how a 3-day-old scheduler looked identical
to no scheduler at all.

---

## The operator flow after this patch

```powershell
# 0. see where you are — this now shows Track 1 as well
python monitor/ops.py status

# 1. freeze legacy. MUST come first; ops refuses without it.
if (-not (Test-Path STOP_TRADING)) { New-Item -ItemType File STOP_TRADING }

# 2. start. `restart` — not `up` — because a scheduler is already running (pid 36656,
#    3d12h old, and running code older than today's edits).
python monitor/ops.py restart --scheduler --track1-shadow --yes

# 3. confirm
python monitor/ops.py status
```

The launcher now does what the Stage 5J runbook asked the operator to remember: the two evidence
directories are created and exported, the order approval is stripped from the child, and the
preflight refuses if the kill switch is missing.

Still the operator's own decisions, unchanged: whether to freeze legacy at all, and B1.

---

## Safety invariants

| invariant | how it holds |
|---|---|
| legacy entries frozen before start | ops **refuses to start** without `STOP_TRADING`; the refusal names the 23 surviving entry slots |
| legacy exits still run | `STOP_TRADING` clears `entry_candidates` only — drains, stop repairs and max-hold continue |
| Track 1 orders impossible | four independent things, none supplied here: B1 open · no confirmation file (**refused if present**) · `TRACK1_ORDERS_APPROVED` **removed from the child** · no `--allow-orders` in the scheduler args or the slot argv |
| evidence is durable | `global_index/track1_runtime/…`, created by ops, git-ignored, **not** `scratch/` |
| legacy startup unchanged | the Track 1 flag is the only argv difference; legacy children keep their env, including `TRACK1_ORDERS_APPROVED` if the shell has it |
| the flag cannot silently do nothing | a no-op `--track1-shadow` under `up` returns 2 |

---

## Tests

| suite | result |
|---|---|
| Stage 5K ops startup (new) | **17 passed** |
| `monitor/test_ops.py` · Stage 5K0 · Stage 5I | **54 passed** |
| dashboard snapshot · scheduler shadow-verify · heartbeat · log hygiene · 5B runbook | **58 passed** |
| dashboard parity, both modes | `RAITS_TRACK1_SHADOW=0` → in_parity **True**; `=1` → in_parity **True** |

Every test that reaches a launch fakes `subprocess.Popen`; nothing was started. The suite asserts
at the end that `global_index/track1_runtime`, `STOP_TRADING`, `STOP_TRADING.track1` and the
confirmation file are all still absent.

`global_index/test_event_playback.py` was **not run** — it is the known hang.

One pre-existing out-of-scope failure is unchanged and untouched:
`test_no_monitor_or_dashboard_file_mentions_the_module`, from a `monitor/` file another session
created.

---

## No side effects

No scheduler, backend or dashboard started or stopped — **the scheduler found running was
already running and was not touched**. No IBKR connection. No order. No dashboard runtime write.
No `STOP_TRADING`, no `STOP_TRADING.track1`, no `track1_go_live_confirmation.json`.
`TRACK1_ORDERS_APPROVED` unset. No commit — `HEAD` unchanged at `601970b`. The real
`global_index/track1_runtime/` does not exist; ops creates it at start time, and no test did.

---

## What an operator should decide before starting

The running scheduler is **3½ days old and running pre-Track-1 code**. Restarting it is required
for shadow mode either way, but it is worth knowing that the restart also picks up every legacy
change made since 2026-08-20 — that is a legacy change as well as a Track 1 one, and it is the
operator's call, not mine.

---

Stage 5K complete: READY_TO_START_TRACK1_SHADOW_VIA_OPS. Freeze legacy with STOP_TRADING, then `python monitor/ops.py restart --scheduler --track1-shadow`. Shadow only; live orders remain blocked by B1.
