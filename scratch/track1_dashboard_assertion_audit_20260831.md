# Track 1 Dashboard Assertion Audit - 2026-08-31

Scope checked: `/realtime` and `/paper` on `http://127.0.0.1:5002`, served by the already-running backend on port 5002. I did not restart the backend because `python monitor\ops.py status` reported `track1_mode=unknown` after an access-denied process scan; preserving the existing mode was safer than changing it.

Repo state note: `global_index/dash/realtime/realtime.js`, `global_index/dash/realtime/realtime.css`, `monitor/test_dashboard_backend.py`, `monitor/backend/track1_market_view.py`, `global_index/track1_strategy_diagnostics.py`, and many unrelated files already had uncommitted changes before this audit. No generated evidence file was rewritten.

## Finding 1 - Verified

**What the page says:** On `/realtime`, the NKD setup card header rendered:

`market ref 66,620.00 · 02:55 ET`

The same card also rendered recorded setup readings:

`Close used 66,440.00`, `Daily ATR 55.36`, `Volume 0`, `Average volume (10 bars) 32`, with the source badge `RECORDED`.

**What is true:** The header joins a price and a time from different facts.

Measured from the live `/api/v1/track1-market-view` payload:

| Fact | Value |
| --- | --- |
| Market-view session | `2026-08-31`, `session_is_today=true` |
| NKD chart bars source | `bars_session_date=2026-08-28` |
| NKD `bars_note` | `no persisted bars for 2026-08-31; showing the most recent stored session 2026-08-28` |
| Stored bar at `02:55` | close `66,640.00` |
| Stored context bars after the slot | `03:00` close `66,620.00`; `03:05` close `66,620.00` |
| Recorded slot-series `02:55` close | `66,440.00` |

Code path: [realtime.js](D:/raits/global_index/dash/realtime/realtime.js:2308) sets `lastBar` from `s.bars[s.bars.length - 1]`, [realtime.js](D:/raits/global_index/dash/realtime/realtime.js:2312) sets `lastSlot` from the last non-future slot, and [realtime.js](D:/raits/global_index/dash/realtime/realtime.js:2398) prints `lastBar.close` beside `lastSlot.time_et`.

**Measurement that separates them:** A live Playwright read at 1365px and 390px captured the rendered header text, then the API payload showed that `66,620.00` is the last stored context-bar close from `2026-08-28 03:05`, not the `02:55` bar and not the recorded `2026-08-31` slot close.

**Operator risk:** An operator could treat `66,620.00` as the market reference at the `02:55 ET` decision slot. That is wrong in two directions: the stored chart's own `02:55` close was `66,640.00`, while the recorded runtime slot close for today's detector account was `66,440.00`. The label makes a stale context price look slot-timed.

**Owner layer:** Display layer. The backend already publishes the separate facts (`bars`, `bars_session_date`, `bars_note`, `slot_series`, setup metrics, and slot times). The UI combines mismatched fields in the header.

**Regression test to add with the fix:** DOM fixture with `bars=[{time:"03:05", close:66620}]`, last slot `02:55`, and `strategy.slot_series[-1].close=66440`. Assert the setup header either says the stored bar's own time/date, or uses the slot-series close for the slot reference. Removing the fix should restore `market ref 66,620.00 · 02:55 ET` and fail.

## Checked And Verified

**Verified:** The old "Daily ATR" label defect appears repaired in current Track 1 setup diagnostics. [track1_strategy_diagnostics.py](D:/raits/global_index/track1_strategy_diagnostics.py:267) documents that the old row was actually fourteen 5-minute bars, and the current measured NKD setup rows separately render `ATR (14 x 5-min bars)` and `Daily ATR`. On the live payload the `Daily ATR` value was `55.36` from `recorded_runtime`; I did not verify the stop-sizing daily ATR independently during a live market session.

**Verified:** The verdict-shaped hole is not currently rendered as `NOT REPORTED` in the NKD live page. The DOM measurement found `hasNotReported=false`; the page renders `Readings - measured, not a pass/fail` for measurement rows and `no verdict` for lane cells that are genuinely not verdicts. The targeted DOM tests passed: `6 passed, 56 deselected`.

**Verified:** Null slot values no longer collapse to zeros in the setup slot chart. [realtime.js](D:/raits/global_index/dash/realtime/realtime.js:2213) treats `null`, `undefined`, and `""` as gaps before calling `Number()`. The live NKD chart axis stayed in the plausible price range `66,067.40` to `66,507.60`; there was no impossible negative axis.

**Verified:** `/paper` kept distinct readiness states in the live DOM at 1365px and 390px: overall `SPEC BLOCKED`, STP panel `BREACH`, and C1 panel `QUALITY_BREACH`. It also rendered the evidence timestamp `observed 2026-08-24T06:58:47.545152Z`. Targeted paper/backend tests passed: `33 passed, 187 deselected`.

**Verified:** Narrow viewport measurements did not show page overflow for the checked pages: `/realtime` had `scrollWidth=clientWidth=390`, and `/paper` had `scrollWidth=clientWidth=390`.

## Unchecked / Unproven

**Unchecked:** I could not use the in-app Browser connector; it returned `No browser is available`. Render checks used local Playwright instead, with screenshots written to `scratch/track1_assertions_audit_1365.png`, `scratch/track1_assertions_audit_390.png`, `scratch/paper_assertions_audit_1365.png`, and `scratch/paper_assertions_audit_390.png`.

**Unchecked:** I did not restart the backend. `monitor\ops.py status` could not prove scheduler/backend processes through process scan due to access denied, and the Track 1 mode was `unknown`; changing process state would have violated the prompt's preserve-mode instruction.

**Unproven:** Stress and Swing live-session setup values could not be fully checked in an active window. At 06:36 ET both were still `waiting`; Stress had no metrics yet, and Swing's reconstructed diagnostics reported `Data unavailable`.

**Unproven:** The true stop-sizing daily ATR for today's NKD slot was not independently compared against order placement or stop geometry. The page now labels `Daily ATR` separately from `ATR (14 x 5-min bars)`, but this audit did not chase the stop order calculation under a live signal.

**Unchecked:** Cached `realtime.js` behavior in a user browser was not tested directly. The Playwright run performed a reload against the local server and saw current rendered text, but I could not hard-refresh an existing operator browser session.

## Round 2 Inventory Sweep - Verified

Artifact: `scratch/track1_dashboard_inventory_20260831.json`.

Method: fetched `/api/v1/runner-state`, `/api/v1/broker`, `/api/v1/schedule-status`, `/api/v1/open-issues`, `/api/v1/runner-positions`, `/api/v1/track1-market-view`, `/api/v1/paper-evidence`, and `/api/v1/track1-runtime`; then rendered `/realtime` and `/paper` through Playwright, clicked the three market-view sleeve tabs, the NKD inner tabs, the four paper tabs, and 17 paper coverage-detail buttons.

### Assertion Inventory - Realtime

| Claim on page | Verified status | Source / unit / session |
| --- | --- | --- |
| Header date `Aug 31, 2026` | verified | Track 1 market view `session_date=2026-08-31`, not legacy runner snapshot |
| Broker `Live - updated 3s ago` | verified | `/api/v1/broker`: `connected=true`, `freshness=fresh`, `age_seconds` single-digit seconds |
| Runner `On schedule - next 09:32 ET` | verified with caveat | `/api/v1/schedule-status`: route mode `track1_only_shadow`, `freshness=not_expected_yet`; legacy runner stale is separately reported under `legacy_runner` |
| Scheduler `up 23h26m` | verified | `/api/v1/schedule-status.scheduler_process.age_seconds`, one process, `stale_code=false` |
| Equity headline `not measured` | verified | `/api/v1/track1-runtime.paper_account.status=UNKNOWN`, `headline_usable=false`; display does not substitute legacy equity |
| Drawdown `0.00% / $0.00` | verified with caveat | legacy runner snapshot values; metrics zone is classed stale when legacy age exceeds threshold |
| Positions/orders `0 / 0` | verified | fresh IBKR broker payload, count units |
| Model age `20 mo stale` | verified | legacy runner operational status / known G2 debt; Track 1 regime record separately reports `fit_end=2024-12-31` |
| HMM fit `22/22 complete / 22 warn` | verified | session-event diagnostic count; warning tone visible |
| NKD verdict `NO SIGNAL - 22/22 slots observed` | verified | Track 1 signal rows for `2026-08-31`, slot count |
| NKD summary includes `STORED SESSION 2026-08-28` | verified | chart bars fall back to persisted store date; payload carries `bars_note` |
| NKD setup header `market ref 66,620.00 - 02:55 ET` | false | See Finding 1: price is the final chart context bar, time is the final slot |
| NKD setup readings (`Close used`, `Daily ATR`, `Volume`, `Average volume`) | verified | recorded runtime setup diagnostics for the last NKD slot; units are price/count/ratio |
| Stress/Swing `WAITING` | verified at measurement time | page time was before their windows; values depending on their live session remain unproven |

### Assertion Inventory - Paper

| Claim on page | Verified status | Source / unit / session |
| --- | --- | --- |
| Top source `Paper epoch 2026-08-10 - source paper_evidence - observed 2026-08-24...` | false label scope | `observed_at` is the runner-state artifact timestamp, while paper bundle also includes fresher sources; see Finding 3 |
| Overall status `SPEC BLOCKED` | false as page-level summary | `payload.gates` has a structural gap, but visible readiness blockers include coverage `BREACH`; see Finding 2 |
| Epoch P&L card `BREACH` | verified | `coverage.paper_vs_backtest` + `coverage.pnl_thresholds`; strategy `-$43.25`, broker `-$1,123.75`, uncovered gap `+$1,080.50` |
| Data freshness card `BREACH` | verified | `coverage.data_freshness`: `regime=OK`, `model=URGENT`, `refreeze_pending=false` |
| STP panel `BREACH` | verified | composite of verification `PENDING`, placement `BREACH`, current protection `MISSING` |
| C1 panel `QUALITY_BREACH` | verified | `c1_slippage`: OPEN `+9.00` ticks, N=5, limit 3 ticks; sample still pending |
| Current protection `MISSING 0/0` | verified | empty persisted open-position book; means no current position to protect, not pass |
| Contract spec guard `OBSERVED 6/6` | verified | `/api/v1/broker payload.contract_specs`, 0 mismatch, 0 missing |
| TWS restart evidence `MISSING 0/10` | verified | raw candidates are context, not proven nights |
| Manual intervention `NEEDS_DECISION` | verified | 3 candidate lines, no structured ledger |

## Finding 2 - Verified

**What the page says:** `/paper` top-level readiness rendered:

`Overall status SPEC BLOCKED`

with reason:

`At least one gate needs a quantified decision before it can pass`

On the same first screen, `What blocks live now` rendered at least two visible breach cards:

`BREACH EPOCH P&L strategy -$43.25 / broker -$1,123.75`

and:

`BREACH DATA FRESHNESS regime=OK | model=URGENT | refreeze_pending=False`

**What is true:** The overall status is not the worst visible readiness-blocker status. It is computed only from `payload.gates`, while the visible blocker list is computed from both `gates` and `coverage`.

Measured from live `/api/v1/paper-evidence`:

| Source collection | Statuses relevant to page |
| --- | --- |
| `payload.gates` | `PENDING`, `STRUCTURAL_GAP`, `QUALITY_BREACH`, `EXPLAINED` |
| `payload.coverage.paper_vs_backtest` | `BREACH` |
| `payload.coverage.data_freshness` | `BREACH` |
| `payload.coverage.open_incidents` | `BREACH` |
| rendered blocker cards | `BREACH` appears before the `SPEC BLOCKED` top-line reason |

Code path: [paper.js](D:/raits/global_index/dash/paper/paper.js:411) builds blocker cards from coverage rows such as `data_freshness`, `open_incidents`, and `pnl_thresholds`; [paper.js](D:/raits/global_index/dash/paper/paper.js:2406) builds `statuses` from `gates` only; [paper.js](D:/raits/global_index/dash/paper/paper.js:2432) chooses the overall word from that gate-only list.

**Measurement that separates them:** Playwright read `/paper` at 1365px and 390px: `overall=SPEC BLOCKED`, while the same rendered DOM's `readinessBlockers` text began with `BREACH EPOCH P&L` and included `BREACH DATA FRESHNESS`. The API confirms those breach words come from `payload.coverage`, not from `payload.gates`.

**Operator risk:** The operator can read the top line as "we are blocked by missing/spec evidence", when the page's own lower panel says there are observed breaches. That changes the action: a spec block asks for a quantified rule or more evidence; a breach asks for remediation or explicit classification before promotion.

**Owner layer:** Display layer unless the backend contract says overall readiness must ignore coverage rows. The visible blocker cards already consume coverage as readiness evidence; the top-level status should either use the same severity set or label itself as "gate status" rather than "overall status".

**Regression test to add with the fix:** DOM fixture where `gates=[{status:"STRUCTURAL_GAP"}]` and `coverage=[{key:"data_freshness",status:"BREACH"}]`. Assert `#overallStatus` is `BREACH` or that its label explicitly scopes itself to gates only. Removing the fix should return `SPEC BLOCKED` and fail.

## Finding 3 - Verified

**What the page says:** `/paper` top source line rendered:

`Paper epoch 2026-08-10 | source paper_evidence | observed 2026-08-24T06:58:47.545152Z`

**What is true:** That timestamp is not the observation time for the whole `paper_evidence` payload. It is copied from `state.get("observed_at")`, which is the `live_state_data.js` / runner-state observation. The same paper-evidence payload also includes data from fresher sources, including `/api/v1/open-issues` observed `2026-08-31T10:20:18Z`, `monitor/paper_pnl_compare.json` freshness marked `CURRENT`, and IBKR contract specs from the current backend cache.

Code path: [paper_evidence_reader.py](D:/raits/monitor/backend/paper_evidence_reader.py:3476) returns `"source": "paper_evidence"` and [paper_evidence_reader.py](D:/raits/monitor/backend/paper_evidence_reader.py:3477) returns `"observed_at": state.get("observed_at")`; [paper.js](D:/raits/global_index/dash/paper/paper.js:2417) renders that as the source timestamp for `paper_evidence`.

**Measurement that separates them:** Live endpoint measurement:

| Field | Value |
| --- | --- |
| `/api/v1/paper-evidence.observed_at` | `2026-08-24T06:58:47.545152Z` |
| `/api/v1/paper-evidence.source` | `paper_evidence` |
| `/api/v1/open-issues.observed_at` consumed inside paper evidence | `2026-08-31T10:20:18Z` |
| `paper_vs_backtest.metrics.artifact_freshness.status` | `CURRENT` |
| `contract_spec_guard.evidence` | `6/6 local contract spec(s) reconciled to IBKR` |

**Operator risk:** A reader can believe the entire paper evidence bundle is a week old, or conversely treat the runner-state timestamp as proof that all subordinate evidence was observed then. Both are wrong: some rows are stale-by-runner-state, some are freshly derived, and the page collapses them into one timestamp.

**Owner layer:** Backend and display contract. The reader should either expose a bundle-level `generated_at` / `sources_observed_at` map, or the UI should label this line as `runner-state observed` rather than `paper_evidence observed`.

**Regression test to add with the fix:** Backend contract fixture with runner-state observed on `2026-08-24` and open-issues observed on `2026-08-31`. Assert the top UI does not render the runner timestamp as the whole paper-evidence observation time; assert a source-clock/detail row carries both timestamps distinctly. Removing the fix should restore `source paper_evidence | observed 2026-08-24...` and fail.

## Round 2 Checks That Did Not Become Findings

**Verified:** `/realtime` and `/paper` both measured `documentElement.scrollWidth - clientWidth = 0` at 1365px. Earlier 390px checks also measured zero overflow.

**Verified:** `NOT REPORTED` did not appear in the current rendered Track 1 market view; absence states are separated as `no verdict`, `not reached`, `no record`, and `not yet run`.

**Verified:** The NKD slot chart did not include impossible zero-derived price-axis values. Axis labels were in the `66,067.40` to `66,507.60` range.

**Verified:** Paper C1 wording distinguishes sample incompleteness from current quality breach: `QUALITY_BREACH`, `sample gate incomplete`, and `Current N=1 contract evidence must be retested when scaling`.

**Unproven:** Stress and Swing setup assertions still need an in-window or post-window check. The sweep happened before their windows, so their live metrics were legitimately absent.

**Unchecked:** I did not mutate tests to prove red-on-removal because this pass produced a findings document only. Each finding above names the regression test that should be added with the eventual fix.
