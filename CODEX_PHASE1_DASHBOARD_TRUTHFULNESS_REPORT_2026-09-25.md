# Phase 1 Read-Only Report: Dashboard Truthfulness

## PER ITEM

### Item 1

**Reproduces: yes.**

Command:

```powershell
python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:5002/api/v1/track1-market-view')); print(json.dumps([s for s in d['market_view']['sleeves']['global_nkd']['slots'] if s['slot_id'] in ('TRACK1_NKD_0110','TRACK1_NKD_0115','TRACK1_NKD_0120','TRACK1_NKD_0125','TRACK1_NKD_0200','TRACK1_NKD_0205')],indent=2))"
```

Raw output:

```text
[
  {
    "candidate_count": 0,
    "reason": "no record was written for this slot",
    "slot_id": "TRACK1_NKD_0110",
    "status": "missed",
    "time_et": "01:10"
  },
  {
    "candidate_count": 0,
    "reason": "no record was written for this slot",
    "slot_id": "TRACK1_NKD_0115",
    "status": "missed",
    "time_et": "01:15"
  },
  {
    "candidate_count": 0,
    "reason": "no record was written for this slot",
    "slot_id": "TRACK1_NKD_0120",
    "status": "missed",
    "time_et": "01:20"
  },
  {
    "candidate_count": 1,
    "reason": "shadow_only",
    "slot_id": "TRACK1_NKD_0125",
    "status": "unknown",
    "time_et": "01:25"
  },
  {
    "candidate_count": 0,
    "reason": "no record was written for this slot",
    "slot_id": "TRACK1_NKD_0200",
    "status": "missed",
    "time_et": "02:00"
  },
  {
    "candidate_count": 0,
    "reason": "no record was written for this slot",
    "slot_id": "TRACK1_NKD_0205",
    "status": "missed",
    "time_et": "02:05"
  }
]
```

Log command:

```powershell
Get-Content -LiteralPath 'monitor\logs\ops_scheduler.err.log' | Where-Object { ($_ -match '^2026-09-24 23:(10|15|20):' -or $_ -match '^2026-09-25 00:0(0|5):') -and $_ -match '\[TRACK1_NKD_(0110|0115|0120|0200|0205)\]' -and ($_ -match 'pythonw\.exe|exited with code|REFUSED|Nothing was run|WinError 1225|NameError: name') }
```

Raw output:

```text
2026-09-24 23:10:00  INFO     run_scheduler — [TRACK1_NKD_0110] ...pythonw.exe ... --slot-id TRACK1_NKD_0110 ... --allow-orders
2026-09-24 23:10:02  ERROR    run_scheduler — [TRACK1_NKD_0110] exited with code 2
2026-09-24 23:10:02  ERROR    run_scheduler — [TRACK1_NKD_0110] stdout:   mode:        armed_but_refused
2026-09-24 23:10:02  ERROR    run_scheduler — [TRACK1_NKD_0110] stdout: REFUSED — order sending was requested and is not available:
2026-09-24 23:10:02  ERROR    run_scheduler — [TRACK1_NKD_0110] stdout: Nothing was run. Re-run without --allow-orders for a shadow pass.
2026-09-24 23:15:00  INFO     run_scheduler — [TRACK1_NKD_0115] ...pythonw.exe ... --slot-id TRACK1_NKD_0115 ... --allow-orders
2026-09-24 23:15:01  ERROR    run_scheduler — [TRACK1_NKD_0115] exited with code 2
2026-09-24 23:15:01  ERROR    run_scheduler — [TRACK1_NKD_0115] stdout: REFUSED — order sending was requested and is not available:
2026-09-24 23:15:01  ERROR    run_scheduler — [TRACK1_NKD_0115] stdout: Nothing was run. Re-run without --allow-orders for a shadow pass.
2026-09-24 23:20:00  INFO     run_scheduler — [TRACK1_NKD_0120] ...pythonw.exe ... --slot-id TRACK1_NKD_0120 ... --allow-orders
2026-09-24 23:20:02  ERROR    run_scheduler — [TRACK1_NKD_0120] exited with code 2
2026-09-24 23:20:02  ERROR    run_scheduler — [TRACK1_NKD_0120] stdout: REFUSED — order sending was requested and is not available:
2026-09-24 23:20:02  ERROR    run_scheduler — [TRACK1_NKD_0120] stdout: Nothing was run. Re-run without --allow-orders for a shadow pass.
2026-09-25 00:00:00  INFO     run_scheduler — [TRACK1_NKD_0200] ...pythonw.exe ... --slot-id TRACK1_NKD_0200 ... --allow-orders
2026-09-25 00:00:04  ERROR    run_scheduler — [TRACK1_NKD_0200] exited with code 1
2026-09-25 00:00:04  ERROR    run_scheduler — [TRACK1_NKD_0200] stderr: ConnectionRefusedError: [WinError 1225] The remote computer refused the network connection
2026-09-25 00:05:00  INFO     run_scheduler — [TRACK1_NKD_0205] ...pythonw.exe ... --slot-id TRACK1_NKD_0205 ... --allow-orders
2026-09-25 00:05:37  ERROR    run_scheduler — [TRACK1_NKD_0205] exited with code 1
2026-09-25 00:05:37  ERROR    run_scheduler — [TRACK1_NKD_0205] stderr: NameError: name 'read_route_book' is not defined
2026-09-25 00:05:37  ERROR    run_scheduler — [TRACK1_NKD_0205] stderr: NameError: name 'BookRefused' is not defined
```

Mechanism: `monitor/backend/track1_market_view.py::_signal_rows()` at lines 385–396 reads only signal rows. `_slots_for()` at lines 399–439 classifies every elapsed slot absent from those rows as `SLOT_MISSED` and inserts the generic reason at lines 428–433. `build()` reads no job journal before calling `_slots_for()` at lines 1958 and 2009. `realtime.js` lines 2610–2615 renders that status and reason directly.

Smallest complete change: in `track1_market_view.py`, read the day’s job journal once in `build()`, index Track 1 jobs by `job_id`, and pass that index into `_slots_for()`. Add a distinct fired-without-record status. Use `missed` only when no matching launch/job exists; for a matching failed/refused job, carry evidence from its diagnostics/reason. Add the corresponding marker vocabulary to `realtime.js`.

Risk if wrong: a truly never-fired slot could be reported as an application failure; repeated job IDs could attach yesterday’s reason; or a generic exit code could replace known refusal/Gateway/NameError evidence.

Gate: a new backend test must assert three separate outcomes: stdout gate refusal, stderr `WinError 1225`, and no launch at all. A DOM test must assert distinct status text and the individual reason for each. The over-wide assertion is that the no-launch case remains exactly `missed` and does not inherit a neighboring job’s reason.

### Item 2

**Reproduces: yes, but the specification’s mechanism and proposed fix are incomplete.**

Command:

```powershell
python -c "from pathlib import Path; from monitor.backend.job_journal_reader import read_job_journal; import json; d=read_job_journal('2026-09-25',Path('.')); print(json.dumps([{k:j.get(k) for k in ('job_id','status','reason','diagnostics','impact')} for j in d['jobs'] if j.get('job_id') in {'TRACK1_NKD_0110','TRACK1_NKD_0115','TRACK1_NKD_0120','TRACK1_NKD_0200','TRACK1_NKD_0205'}],indent=2))"
```

Raw output:

```text
[
  {"job_id":"TRACK1_NKD_0110","status":"failed","reason":"exited with code 2","diagnostics":[],"impact":"The job emitted an unclassified error; completion and operational effects cannot be confirmed from this evidence."},
  {"job_id":"TRACK1_NKD_0115","status":"failed","reason":"exited with code 2","diagnostics":[],"impact":"The job emitted an unclassified error; completion and operational effects cannot be confirmed from this evidence."},
  {"job_id":"TRACK1_NKD_0120","status":"failed","reason":"exited with code 2","diagnostics":[],"impact":"The job emitted an unclassified error; completion and operational effects cannot be confirmed from this evidence."},
  {"job_id":"TRACK1_NKD_0200","status":"failed","reason":"exited with code 1","diagnostics":[],"impact":"The job emitted an unclassified error; completion and operational effects cannot be confirmed from this evidence."},
  {"job_id":"TRACK1_NKD_0205","status":"failed","reason":"exited with code 1","diagnostics":[],"impact":"The job emitted an unclassified error; completion and operational effects cannot be confirmed from this evidence."}
]
```

Clean-run command:

```powershell
python -c "from pathlib import Path; from monitor.backend.job_journal_reader import read_job_journal; import json; d=read_job_journal('2026-09-25',Path('.')); print(json.dumps([{k:j.get(k) for k in ('job_id','status','diagnostics')} for j in d['jobs'] if j.get('status')=='completed' and not j.get('diagnostics')][:3],indent=2))"
```

Raw output:

```text
[
  {"job_id":"TRACK1_STOP_REPAIR_0020","status":"completed","diagnostics":[]},
  {"job_id":"SPY_LAST_CHANCE_PRE_NKD","status":"completed","diagnostics":[]},
  {"job_id":"SPY_LAST_CHANCE_PRE_NKD_REGIME_LABEL","status":"completed","diagnostics":[]}
]
```

Mechanism: `_parse()` lines 690–708 admits only stderr and only while `current` is active. The scheduler logs `exited with code` before echoing child output. Lines 789–798 finish the job and remove it from `active`, so later stdout and stderr encounter `current is None` and are discarded at line 708. Separately, `_annotate_impact_and_action()` lines 544–546 has no refusal-specific classifier, so retaining stdout alone would still produce the catch-all impact.

Smallest complete change: add one capped child-diagnostic attachment helper. For stdout/stderr, target the active execution or the most recent failed execution of the same `job_id`; do not run child text through launch detection. Retain failure output only, enforce `_MAX_CHILD_DIAGNOSTICS`, and add a refusal-evidence branch in `_annotate_impact_and_action()` before the unclassified fallback.

Risk if wrong: normal stdout could flood every clean row, traceback frames could again create phantom launches, or late output from a repeated job ID could attach to the wrong execution.

Gate: synthetic log tests must assert that refusal text is retained and its impact names the refusal, late stderr retains `WinError 1225`, diagnostics never exceed 12, and a completed clean job remains at exactly zero diagnostics. The zero-diagnostic clean assertion is the required over-wide guard.

### Item 3

**Reproduces: yes.**

Command:

```powershell
python -m pytest scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py::test_dom_every_row_says_whose_problem_it_is -q -rxX
```

Raw output:

```text
x                                                                        [100%]
XFAIL scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py::test_dom_every_row_says_whose_problem_it_is - MEASURED DEFECT 2026-09-24: no rendered row says whose problem it is. Stage 5ZZZ-CM removed the group headings and justified it by saying each item's scope stays on its own row's chip — the row markup has no scope chip, and `issueScope()`, the function that would produce one, has no caller anywhere in realtime.js (1 occurrence: its own definition, in the working copy and in HEAD alike). Left failing on purpose so it is visible and named; it flips to XPASS the day the chip comes back.
1 xfailed in 8.91s
```

Static command:

```powershell
python -c "from pathlib import Path; s=Path('global_index/dash/realtime/realtime.js').read_text(encoding='utf-8'); print('issueScope_occurrences='+str(s.count('issueScope(')))"
```

Raw output:

```text
issueScope_occurrences=1
```

Mechanism: `realtime.js::issueScope()` lines 1452–1463 defines the four mappings. `renderOpenIssues()`’s `issueRow` at lines 4329–4336 renders only component and status; it never reads `route_scope`.

Smallest change: add one scope badge to each issue row using `issueScope(issue.route_scope)`, with an explicit unknown-scope fallback rather than an empty chip. Remove only the `xfail` marker at scratch-test lines 565–571.

Risk if wrong: route mappings could be swapped, unknown scopes could render blank, or the chip could appear only in selected detail rather than every row.

Gate: the existing strict-xfail test must become a normal pass and the entire 5ZZH suite must become 37 passed. A supplementary DOM assertion should map each issue title to exactly one expected label; that catches a global label or a chip applied only to some rows.

### Item 4

**Reproduces: yes.**

Command:

```powershell
python -c "from global_index import track1_report as R; import json; print(json.dumps(R.read_order_journal('.'), indent=1, default=str))"
```

Raw output:

```text
{
 "path": "global_index/track1_runtime/orders",
 "state": "available",
 "rows": 12,
 "files": 2,
 "malformed_lines": 0,
 "order_states": ["filled", "intended", "submitted"],
 "submitted": 6,
 "sent_order_ids": ["28", "30", "40"],
 "filled_trades": [
  "global_nkd::MNKD::2026-09-25",
  "normal_r4::M2K::2026-09-24",
  "normal_r4::MYM::2026-09-24"
 ],
 "source": "paper_send",
 "reading": "12 journal row(s) — 3 order(s) SENT to the paper broker (ids 28, 30, 40), 3 filled"
}
```

Signal-row command:

```powershell
rg -n 'TRACK1_NKD_0125' global_index/track1_runtime/signals/track1_signals_20260925.jsonl
```

Raw output includes:

```text
1:{"session_date":"2026-09-25","sleeve":"global_nkd","slot_id":"TRACK1_NKD_0125",...,"status":"SIGNAL_ACCEPTED_SHADOW","reason":"shadow_only",...,"candidates":[{"instrument":"MNKD","direction":"LONG","qty":1,...,"trade_id":"global_nkd::MNKD::2026-09-25",...}]...}
```

Mechanism: `track1_market_view.py::_slots_for()` lines 418–423 copies the decision row’s reason and candidate count but reads no order journal. `_STATUS_MAP` lines 133–135 does not map `SIGNAL_ACCEPTED_SHADOW`, so the slot status becomes `unknown`. `realtime.js` lines 2610–2615 renders the backend reason verbatim. The order journal is not referenced in `track1_market_view.py`.

Smallest change: read `track1_report.read_order_journal(root)` once in `build()`, compare each signal candidate’s `trade_id` with `filled_trades`, and add a separate structured execution field such as `order_state:"filled"`. Keep the decision-layer `reason:"shadow_only"` unchanged, then render both facts together in `realtime.js`.

Risk if wrong: matching only sleeve/instrument instead of the full dated trade ID could label later shadow candidates as ordered; replacing the decision reason would erase true decision-layer evidence.

Gate: one test must assert that 01:25 retains its shadow decision fact and also says an order filled. A second slot with the same decision status but no matching journal entry must retain exactly its current status and reason. That second assertion is the over-wide guard.

### Item 5

**The skip reproduces, but the specification’s fixture diagnosis does not.**

Command:

```powershell
python -m pytest monitor/test_job_row_never_invents_a_cause.py -q -rs
```

Raw output:

```text
sssss                                                                    [100%]
SKIPPED [5] monitor\test_job_row_never_invents_a_cause.py: fixture not wired: a stubbed job-journal renders no .job-row rows; the fix itself is verified on the live page (see the note above this line)
5 skipped in 2.91s
```

Read-only browser probe with the current no-slash override:

```text
job_journal_requests=["/api/v1/job-journal/2026-08-14"]
rows_immediately=0
Page.wait_for_selector: Timeout 20000ms exceeded.
```

The same probe with the override key changed in memory from `/api/v1/job-journal` to `/api/v1/job-journal/`:

```text
job_journal_requests=["/api/v1/job-journal/2026-08-14"]
rows=1
row_text=09-25, 01:10 ET | 2s | + | RUNNER | RECOVERED | TRACK1_NKD_0110 | This execution failed and a later slot ran clean: exited with code 2.
```

Running the five test functions directly after removing the colliding empty-fixture prefix in memory:

```text
test_1_a_gate_refusal_is_not_reported_as_a_windows_permission_fault=PASS
test_2_a_real_publication_failure_keeps_its_own_sentence=PASS
test_3_a_publication_reason_also_keeps_it=PASS
test_4_a_recovered_job_with_no_reason_at_all_still_says_something=PASS
test_5_an_open_failure_still_reads_as_open=PASS
```

Mechanism: `monitor/test_realtime_dom.py::stub_api()` lines 184–192 sorts prefixes longest-first. Its base key is `/api/v1/job-journal/`. `monitor/test_job_row_never_invents_a_cause.py::_stub()` line 88 overrides `/api/v1/job-journal` without the trailing slash. The longer base key wins and returns the empty journal. `realtime.js::journalJobs()` lines 5293–5295 does not filter supplied jobs; the stated filtered-collection diagnosis is false.

Smallest change: change `_stub()` in `monitor/test_job_row_never_invents_a_cause.py` to override `/api/v1/job-journal/`, then remove the module skip. No shared-fixture change is required.

Risk if wrong: changing general prefix matching could affect every stubbed endpoint or let a shorter endpoint consume another endpoint’s request.

Gate: the five tests must run normally and pass. The over-wide guard is the full `monitor/test_realtime_dom.py` suite, especially its other endpoint stubs; its count must remain 88 passed.

## TESTS

| File | Before | After |
|---|---:|---:|
| `monitor/test_realtime_dom.py` | 88 passed | Not run after changes; Phase 1 made no source/test changes |
| `monitor/test_dashboard_backend.py` | 225 passed | Not run after changes; Phase 1 made no source/test changes |
| `scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py` | 36 passed, 1 xfailed | Not run after changes; Phase 1 made no source/test changes |
| `monitor/test_job_row_never_invents_a_cause.py` | 5 skipped | Not run after changes; Phase 1 made no source/test changes |

Raw mandated-suite outputs:

```text
88 passed in 302.91s (0:05:02)
225 passed in 227.98s (0:03:47)
36 passed, 1 xfailed in 145.90s (0:02:25)
```

Additional read-only Item 5 execution with the fixture collision removed in memory: 5 of 5 test functions passed.

## SKIP REMOVED

No. Phase 1 was read-only. Evidence shows the skip can be removed after correcting the test helper’s missing trailing slash; the shared fixture itself does not require modification.

## BOOK HASH

Start:

```text
beece7572841653b4a674126cbc89ddac076562f4ad38fc11f2ba1fb1c8e7498
```

End:

```text
beece7572841653b4a674126cbc89ddac076562f4ad38fc11f2ba1fb1c8e7498
```

## NOT DONE

No source or test file was changed. No skip or xfail marker was removed, no backend was restarted, and no Phase 2 implementation was attempted. This report file was created only after Phase 1 ended, at the user’s explicit request.

## PLAN PROBLEMS

- Item 2 understates the parser defect. Because child output follows the exit line, both stdout and stderr are discarded after the job is removed from `active`; changing only the stdout condition would not recover the measured refusal, Gateway, or NameError evidence.
- Item 2 omits the required refusal classification in `_annotate_impact_and_action()`. Retaining stdout alone would still leave the impact as “unclassified error.”
- Item 5 incorrectly attributes missing rows to filtered collection entry conditions and asks for a shared-fixture change. The actual cause is the missing trailing slash in `monitor/test_job_row_never_invents_a_cause.py::_stub()`. Correcting that key in memory rendered the row, and all five test functions passed without changing `monitor/test_realtime_dom.py`.
