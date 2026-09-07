# Stage 5ZZB — the warning named its own escalation condition, and nobody was reading

**2026-08-27, ET 05:05–05:25.** Investigation and a bounded fix. No orders · no confirmation
file · nothing restarted · no runtime trading file touched · **production `spy_daily_live.csv`
untouched** (md5 identical before and after).

---

## Verdict

| | |
|---|---|
| `spy_refresh_pm_success_claim_valid` | **YES, and it did not claim coverage** — it warned, in the right words |
| `spy_csv_last_date` | **2026-08-25** |
| `freshness_required_date_for_nkd_20260827` | **2026-08-26** |
| `root_cause` | **the escalation nobody owned** — the post-close job noticed it was short, warned "only a problem if it is still true tomorrow", and nothing looked tomorrow |
| `fix_applied` | coverage made a first-class four-state answer with its own exit code; the scheduler now asks the child for the day it needs; `status` says the missing date in plain words |
| `production_spy_csv_touched` | **NO** |
| `runtime_files_touched` | **NO** |
| `orders_possible` | **false**, blockers unchanged |
| `next_action` | **refresh before 09:32 ET or today's Calm phases refuse too** — the bar does exist at the provider now; the command is in §11 and writes production data, so it is left for the operator |

---

## 1. The premise needs one correction before anything else

The brief says the scheduler logged the job as completed successfully. It did — **and on the
very next line it warned**:

```text
2026-08-26 14:20:00  INFO     [SPY_REFRESH_PM] Starting: update_spy_csv after the close (2026-08-26)
2026-08-26 14:20:00  INFO     [SPY_REFRESH_PM] pythonw.exe -m global_index.update_spy_csv
                              --csv spy_daily_live.csv --verify-strict --api-key ...
2026-08-26 14:20:13  INFO     [SPY_REFRESH_PM] completed OK
2026-08-26 14:20:13  WARNING  [SPY_REFRESH_PM] ran cleanly but the daily series still ends on
                              2026-08-25, not 2026-08-26 — the close for today was not
                              available yet. Tomorrow's sessions ask for the last trading day
                              BEFORE them, so this is only a problem if it is still true
                              tomorrow.
```

*(Times are machine-local, Calgary. 14:20 MT = 16:20 ET.)*

So there was no silent success. Stage 5ZL had already removed that defect from this exact job —
its source comment records the day it printed "the daily series now covers today" having checked
nothing. The check exists, it ran, and it said the true thing.

**The defect is the last sentence.** The warning names its own escalation condition — *only a
problem if it is still true tomorrow* — and nothing in the system looks tomorrow. Tomorrow came,
the overnight Nikkei window ran at ten past one in the morning, and the condition was true.

The day before, the same job at the same time got the close and said so:

```text
2026-08-25 14:20:13  INFO  [SPY_REFRESH_PM] OK — the daily series now covers 2026-08-25,
                           which is what tomorrow's sessions need.
```

Same job, same minute, different luck at the provider.

## 2. The freshness verdict, exactly

```text
preflight_record       ok       observed 2026-08-26   required 2026-08-26
regime_csv             STALE    last date 2026-08-25 is before the required 2026-08-26
preflight_consistency  STALE    the pre-flight record for 2026-08-26 says the 13:45 job
                                SUCCEEDED, and ['regime_csv'] still do not satisfy what the
                                gate asks of them
requirement            ok       daily close through 2026-08-26
intraday_source        UNVERIFIED
=> allow = False
```

The third line deserves attention, because it is the gate doing something better than reporting
a flag: it separates *"the job did not run"* from *"the job ran, reported success, and the data
still does not satisfy what we ask of it"* — and its own words for the second are **"a contract
question, not a retry."** That is the correct diagnosis, written down before this stage started.

The 13:45 pre-flight on 2026-08-26 was also **right** to succeed: at quarter to two the market
had not closed, so that day's daily bar could not exist, and the pre-flight asks only for the
previous day's close, which was there.

## 3. Why the file is still short — proved, and the alternatives refuted

Run against a **temp copy** of the series (production untouched, md5 identical throughout):

```text
first attempt   SSLError — this sandbox intercepts TLS to api.polygon.io; not a Polygon fault
second attempt  Updated ...spy_copy.csv: 1 new row(s), 2425 total (last=2026-08-26)
                spy_daily.csv: appended 1 new row(s)
                regime verification: PASS (ok): 1761 label(s) compared through 2024-12-31
```

**The provider has 2026-08-26 now** — `766.08`. It did not at 16:20 ET yesterday, which is what
the warning said.

| candidate cause | verdict |
|---|---|
| provider returned data only through 2026-08-25 | **CONFIRMED for the moment it was asked**; the bar exists today |
| wrong output path / working directory | **refuted** — the same command against a copy writes correctly |
| write skipped because the row existed or parsing failed | **refuted** — it appended the moment the bar was there |
| timezone/date issue at 16:20 ET | **refuted** — the script uses the machine date, and 14:20 MT is the same calendar day as 16:20 ET |
| market holiday / delayed availability | **half** — 2026-08-26 was a Wednesday, so no holiday; the delay was real |
| verification compares labels only through an old common end | **CONFIRMED, and it is the second defect** — see below |
| the success log came from the wrapper, not real verification | **refuted** — the wrapper reads the file's last date and warns |

## 4. What `--verify-strict` actually verified

Its own output answers it: **"1761 label(s) compared through 2024-12-31"**.

It is a drift check over settled history. It exits non-zero when the regime labels move or
cannot be verified, and it says **nothing whatever** about whether last night's close arrived.

- Does it require the just-closed day? **No.**
- Does it treat "no new daily bar" as success? **Yes** — `appended == 0` prints "already
  up-to-date" and returns 0.
- Does it verify drift but not coverage? **Precisely that.**
- Does it write success before checking the tail? It never checked the tail; the scheduler did,
  afterwards.
- Does it swallow provider failures? **No, and this was measured** — an invalid key exits **1**
  and leaves the file untouched, and an empty fetch records UNKNOWN which strict mode fails on.

So the job was honest about the thing it checked and silent about the thing that mattered.

## 5. The contract, before and after

```text
BEFORE   --verify-strict : exit 1 if the regime LABELS drifted or could not be verified
                           coverage: not examined
                           a clean run that supplied nothing: exit 0

AFTER    --verify-strict : unchanged
         --require-through YYYY-MM-DD : the caller names the day it needs
                           covers_required_day                    -> exit 0
                           provider_did_not_return_required_day   -> exit 2
                           coverage_unknown (unreadable)          -> exit 2
                           coverage_not_requested                 -> reported, exit 0
```

**Exit 2, not 1, and deliberately.** A data-supply gap and a history that moved under you are
different problems with different owners; one exit code for both would leave an operator unable
to tell which they had.

The scheduler now passes `--require-through <today>`, so the child carries the answer in its exit
status. That flips the existing branch from WARNING to the FAILED line the file already had:

```text
[SPY_REFRESH_PM] FAILED — the daily series still ends before 2026-08-26. Tomorrow's Track 1
slots will refuse on `regime_csv: stale` until it is re-run.
```

A job status, rather than a line somebody has to be reading at 16:20.

**This takes effect at the next scheduler restart.** Nothing is worse in the meantime: the
running scheduler already emits the correct warning. **No restart is required by this stage.**

## 6. Who reads it tomorrow

That was the missing half, and it is the operator's own command:

```text
BEFORE   (nothing — the freshness gate refused, and said `freshness_allow=false`)

AFTER    spy_daily_coverage=provider_did_not_return_required_day last=2026-08-25
                            required=2026-08-26 calendar=raits.live.trading_calendar
           SPY daily file is missing 2026-08-26 — it ends on 2026-08-25. Sleeves that run
           before the 13:45 pre-flight (the overnight NKD window) will refuse on stale daily
           context until the refresh is re-run
```

`freshness_allow=false` is true and tells nobody what to do. A named file and a named date do.

It asks `track1_freshness` for the requirement rather than restating it: a second copy of "which
day is needed" is a second copy that can drift from the gate that actually refuses, and then the
status and the gate disagree about the same morning.

**It does not blame the window that passed.** The Nikkei window on 2026-08-27 observed all 22
slots and decided in every one; the daily file being short is a separate fact about the inputs.
Rendering it as an operational failure would send somebody to inspect a window that worked, and
a test pins that the wording never does.

## 7. The structural fact underneath

The overnight sleeve is **the only one that runs before its own day's pre-flight**. Its window is
01:10–02:55 ET; the pre-flight is 13:45 ET. So it depends entirely on the previous evening's
post-close refresh having landed — and that refresh is, by design, allowed to come up empty
because the provider is not always ready at 16:20.

That is a real gap in the schedule, not a bug in any one job, and closing it means either a
retry between 16:20 ET and 01:10 ET or accepting that the overnight sleeve will occasionally
refuse. **This stage does not add a job** — that changes production scheduling and is an operator
decision. It is recorded as the recommendation.

## 8. Should it be fatal?

- **Paper readiness**: no. The gate already refuses on its own, which is the correct behaviour
  — a stale input must not produce evidence, and a day that produced none is simply not a
  judgeable day.
- **Dashboard health**: **yes, visibly** — as a stale daily-context warning, separate from
  operational slot status. Now done.
- **Next-morning freshness**: it already is fatal, and correctly so. That is why the overnight
  window refused.
- **The post-close job itself**: now non-zero, because that is the moment somebody can still act.

## 8b. A defect of mine, from Stage 5ZX, that this stage walked into

Chasing the consequence of the stale file turned up something worse than the stale file.

Measured: a phased Calm slot returns **`freshness_allow=None`**. The gate never ran. Stage 5ZX
put the phase's early exit *before* `fresh.evaluate`, on the reasoning that freshness belongs with
the cap guard and the admission layer — all things that describe a position being taken, which a
decide half does not take.

**That reasoning does not reach freshness.** It is not a statement about positions; it asks
whether the INPUTS are current enough to decide on at all, and that is exactly as live for a half
that records an intent as for one that books a trade. With the gate skipped, the decide half
would have recorded an intent computed from a two-day-old regime label, in a row carrying no note
that it was — evidence describing a route that is not the route that would trade.

Corrected here, because it is bounded and because the first-ever run of that phase is this
morning. Freshness now runs for a phased slot and it **binds**:

```text
DECIDE with stale inputs   decided=False  reason=freshness_refused
                           detail: the inputs a decision needs are not current: regime_csv
intent row                 DECIDE  REFUSED  freshness_refused
classify_day               incomplete       <- the day does not count
```

The refusal is the record, as everywhere else on this route, and a counter can no longer reach
five clean days through days nobody would have traded on.

## 8c. Which means today's Calm phases would refuse too

This corrects something I wrote earlier in this same report and had wrong.

The 13:45 ET pre-flight runs **after** both Calm phases, so it cannot help them today:

```text
Calm DECIDE   @09:32 ET   allow=False   regime_csv=stale (has 2026-08-25, needs 2026-08-26)
Calm OBSERVE  @10:02 ET   allow=False   regime_csv=stale (has 2026-08-25, needs 2026-08-26)
```

So unless the series is refreshed before half past nine, the first run of the new phases records
a refusal rather than an intent. That is the correct outcome — and it is not the outcome anyone
was waiting to see this morning, which is why it is worth saying plainly rather than leaving in a
table.

It also widens the structural fact in §7: it is not only the overnight sleeve that runs before
its own pre-flight. **Calm does too.** Everything before 13:45 ET depends on the previous
evening's post-close refresh having landed.

## 9. Tests

**23**, in `scratch/test_track1_stage5zzb_spy_refresh_coverage_20260827.py`. Nothing calls
Polygon; nothing writes outside `tmp_path`.

Coverage states and exit codes · the live shortfall reproduced exactly (session 2026-08-27,
series to 2026-08-25 → stale, required 2026-08-26) · one more day and the regime-csv side is
satisfied · the requirement is the **previous** trading day and, across a weekend, the Friday ·
the scheduler asks the child for the day · the success line is still guarded by a coverage read ·
status names the date in plain words · stale context is not rendered as an operational failure.

Five mutations, all **red**: a short series treated as success · an unreadable series read as
covered · the requirement moved to the session's own day · status reverting to the
machine-readable flag · the scheduler dropping the day from the child's argv.

Adjacent suites after the change: **170 passed**.

## 10. Two things I got wrong along the way

**I piped a command through `tail` and read `$?`** — which is `tail`'s exit code, not the
program's. The first probe therefore reported "EXIT=0" for a run that had thrown an SSL error.
Re-measured properly; the real answer is that a provider failure exits **1**. This project's own
notes warn about exactly this and I did it anyway.

**I silenced the wrong logger, twice.** The trading-calendar module warns at import that it is
using hardcoded rules, and my change made that line appear above the status header where it
reads like the command failed. First attempt silenced a lowercase spelling of a logger that is
capitalised — silencing a logger nobody uses. Second attempt was in the right place for the
wrong call order. The warning is now suppressed where the import actually happens and reported
as a **field** (`calendar=...`), so the information survives rather than being tidied away.

## 11. What remains

The bar exists at the provider. Re-running the refresh would land it — **that command writes
production data and is left for the operator**:

```powershell
python -m global_index.update_spy_csv --csv spy_daily_live.csv --verify-strict `
       --require-through 2026-08-26 --api-key <key>
```

Without it, the 13:45 ET pre-flight will fetch the day — but that is **after** both Calm phases,
so it does not help them. Today's DECIDE and OBSERVE would record refusals.

Gate unchanged: `orders_possible=false`, blocking on B1 and `PAPER_SHADOW_EVIDENCE`, order
journal absent, shadow intent stream still absent.

The next event to watch is still **09:32 ET, `TRACK1_CALM_DECIDE_0932`**. What it records now
depends on whether the series is refreshed first — an intent if it is, an honest refusal if it is
not. Both are better than the third option this stage removed, which was an intent computed from
a stale label with nothing saying so.
