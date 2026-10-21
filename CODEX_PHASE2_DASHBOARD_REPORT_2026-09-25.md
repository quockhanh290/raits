# PER ITEM

1. **Fired vs missed slots**
   - Files: `monitor/backend/track1_market_view.py`
   - Added date-qualified job indexing and `fired_no_record`.
   - A launched slot without a decision record carries its own failure reason; a slot with no launch remains `missed`.

2. **Late child diagnostics**
   - Files: `monitor/backend/job_journal_reader.py`
   - Added capped attachment to the active or most recent failed execution.
   - Retains only ERROR/CRITICAL child output.
   - Order refusal and WinError 1225 are classified separately; NameError remains unclassified.
   - Existing diagnostic counts remain `ANCHOR_CHECK_0055=1` and `TRACK1_STOP_REPAIR_1020=4`.

3. **Issue scope**
   - Files: `global_index/dash/realtime/realtime.js`; one xfail marker removed from `scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py`.
   - Recognized scopes render as visible route labels. Missing or unmapped scopes render `UNKNOWN SCOPE`.

4. **Decision vs execution**
   - Files: `monitor/backend/track1_market_view.py`, `global_index/dash/realtime/realtime.js`
   - Reads the order journal once and joins only on the complete dated `trade_id`.
   - Fill information is a separate structured execution fact; the decision reason remains unchanged.

5. **Job-row test wiring**
   - Files: `monitor/test_job_row_never_invents_a_cause.py`
   - Corrected the trailing-slash stub, removed the skip, and asserted nonzero rendered rows before inspecting text.

6. **Position-book field bridge**
   - Files: `global_index/dash/realtime/realtime.js`
   - Derives holding age from `entry_time` and falls back from `risk_sized` to `risk_dollars`.
   - Existing snapshot fields remain authoritative. Missing age or risk renders `not recorded`.

7. **MNK broker symbol**
   - Files: `global_index/dash/realtime/realtime.js`
   - Explicitly maps the MNK contract family to `MNKD`.
   - Existing roots and the unknown-symbol fallback remain unchanged.

8. **Next protection job**
   - Files: `monitor/backend/track1_market_view.py`, `global_index/dash/realtime/realtime.js`
   - The backend derives `next_protection_job` from the canonical `track1_safety_jobs()` table and registration calendar.
   - The page adds `NEXT PROTECTION` only when a matched position is armed, has no valid working stop, and is therefore naked.
   - `NEXT JOB` and `NEXT DECISION` remain unchanged.
   - Measurement:
   ```text
   NEXT JOB
   TRACK1_SWING_1405
   14:05 ET

   NEXT PROTECTION
   TRACK1_STOP_REPAIR_1620
   16:20 ET
   ```

9. **Deferred vs naked protection**
   - Files: `global_index/dash/realtime/realtime.js`
   - Computes deferral from `entry_time` and sleeve without modifying the position book.
   - R4 uses New York; NKD uses Tokyo.
   - Explicit legacy `stop_deferred` values remain authoritative.
   - Armed positions remain naked; unmatched positions render unknown.
   - Four-case measurement: `0 covered / 2 deferred / 2 naked`.
   - Unmatched measurement: `0 covered / 1 unknown`.

10. **Stale source tagging**
    - Files: `global_index/dash/realtime/realtime.js`
    - Paper Equity is tagged according to whether the paper-account source supplied it.
    - Gross is tagged according to whether the Track 1 book or legacy snapshot supplied it.
    - The stale threshold and envelope-age calculation were not changed.
    - With a 48-hour legacy envelope: Paper Equity opacity `1`, Gross opacity `1`, Realized opacity `0.42`, and `runner-stale=true`.

# GATES

- **G1 PASS; G2.1 PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py::test_g1_g21_three_slot_states_and_clean_output_guard -q
  .                                                                        [100%]
  1 passed in 5.38s
  ```

- **G1 date guard PASS; G2.2 PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py::test_g1_job_index_rejects_wrong_payload_and_execution_dates monitor/test_dashboard_truthfulness_phase2.py::test_g22_existing_non_child_diagnostic_counts_do_not_move -q
  ..                                                                       [100%]
  2 passed in 5.70s
  ```

- **G3 PASS; G4 PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py::test_g3_absent_and_unmapped_issue_scopes_render_visible_unknown monitor/test_dashboard_truthfulness_phase2.py::test_g4_fill_join_uses_full_dated_trade_id monitor/test_dashboard_truthfulness_phase2.py::test_item4_dom_shows_decision_and_fill_as_separate_facts -q
  ...                                                                      [100%]
  3 passed in 15.26s
  ```

- **G5 PASS**
  ```text
  $ python -m pytest monitor/test_job_row_never_invents_a_cause.py -q
  .....                                                                    [100%]
  5 passed in 21.09s
  ```

- **G6 PASS**
  ```text
  Start: d7d63c3fd7d137139da201854942b719d04ee7607855720fae8b75362e7948bc
  End:   d7d63c3fd7d137139da201854942b719d04ee7607855720fae8b75362e7948bc
  ```

- **G7 PASS**
  ```text
  $ python -m pytest monitor/test_realtime_dom.py -q
  88 passed in 396.81s

  $ python -m pytest monitor/test_dashboard_backend.py -q
  225 passed in 279.73s

  $ python -m pytest scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py -q
  37 passed in 265.53s

  $ python -m pytest monitor/test_job_row_never_invents_a_cause.py -q
  5 passed in 55.96s
  ```

- **G8.1 PASS; G8.2 PASS; G8.3 PASS; G8.4 PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py::test_g81_g82_g94_book_fields_and_mnk_contract_render monitor/test_dashboard_truthfulness_phase2.py::test_g83_existing_snapshot_risk_and_age_are_unchanged monitor/test_dashboard_truthfulness_phase2.py::test_g84_missing_age_and_risk_are_not_reported_as_zero -q
  ...                                                                      [100%]
  3 passed in 17.08s
  ```

- **G8.5 PASS**
  ```text
  $ python -m pytest monitor/test_realtime_dom.py -q
  88 passed in 396.81s

  $ python -m pytest monitor/test_decision_panel_reads_track1_series.py -q
  8 passed in 91.06s
  ```

- **G9.1 PASS; G9.2 PASS; G9.3 PASS; G9.4 PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py::test_g91_every_mnk_month_letter_resolves_to_mnkd monitor/test_dashboard_truthfulness_phase2.py::test_g92_other_live_symbol_roots_are_unchanged monitor/test_dashboard_truthfulness_phase2.py::test_g93_unknown_symbol_keeps_existing_fallback_and_stays_unmatched monitor/test_dashboard_truthfulness_phase2.py::test_g81_g82_g94_book_fields_and_mnk_contract_render -q
  ....                                                                     [100%]
  4 passed in 15.44s
  ```

- **G10.1 PASS; G10.2 PASS; G10.3 PASS; G10.4 PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py -q -k "g101 or g102 or g103 or g104"
  .....                                                                    [100%]
  5 passed, 15 deselected in 16.22s
  ```

- **G11.1 PASS; G11.2 PASS; G11.3 PASS; G11.4 PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py -q -k "g111 or g112 or g113 or g114"
  ..                                                                       [100%]
  2 passed, 18 deselected in 10.26s
  ```

- **G12.1 PASS; G12.2 PASS; G12.3 PASS; G12.4 PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py -q -k "g121 or g122 or g123 or g124"
  ..                                                                       [100%]
  2 passed, 18 deselected in 10.25s
  ```

- **All focused Phase 2 gates PASS**
  ```text
  $ python -m pytest monitor/test_dashboard_truthfulness_phase2.py -q
  ....................                                                     [100%]
  20 passed in 33.35s
  ```

- **Diff hygiene PASS**
  ```text
  $ git diff --check -- monitor/backend/job_journal_reader.py monitor/backend/track1_market_view.py global_index/dash/realtime/realtime.js monitor/test_job_row_never_invents_a_cause.py scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py monitor/test_dashboard_truthfulness_phase2.py
  Exit code: 0
  ```
  Git emitted only existing LF-to-CRLF notices.

# TESTS

| Suite | Baseline | Final |
|---|---:|---:|
| `monitor/test_realtime_dom.py` | 88 passed | 88 passed |
| `monitor/test_dashboard_backend.py` | 225 passed | 225 passed |
| `scratch/test_track1_stage5zzh_dashboard_hygiene_20260827.py` | 36 passed, 1 xfailed | 37 passed |
| `monitor/test_job_row_never_invents_a_cause.py` | 5 skipped | 5 passed |
| `monitor/test_decision_panel_reads_track1_series.py` | 8 passed | 8 passed |
| New `monitor/test_dashboard_truthfulness_phase2.py` | N/A | 20 passed |

The full repository suite was not run.

# BOOK HASH

```text
Start:
d7d63c3fd7d137139da201854942b719d04ee7607855720fae8b75362e7948bc

End:
d7d63c3fd7d137139da201854942b719d04ee7607855720fae8b75362e7948bc
```

The live Track 1 position book did not change during this run.

# NOT DONE

Nothing remains from the ten approved items.

No position book, runtime snapshot, production trading file, scheduler, backend process, or live-investigation file was modified or restarted. No sweep was run. No `git add` or `git commit` was run.

# NEW FINDINGS

- Item 3's literal requirement for a scope chip on every row conflicts with G7: the protected realtime suite explicitly forbids restoring the retired `.issue-scope` chip for recognized legacy rows, while the former xfail requires recognized scope labels to remain visible. Recognized values therefore use a plain `.issue-route` label; only missing or unmapped values use the explicit `UNKNOWN SCOPE` chip.

- Item 6's "bridge helper, not call sites" instruction conflicts with G8.4. The existing render expressions hardcoded `--d` and `--`; the bridge alone cannot make absent data say `not recorded`. The fallbacks live in the bridge, while the two display expressions were minimally changed for the required explicit absence.

- Item 8's exclusive list of stop-capable jobs omits `track1_stop_repair_sun_1830`, although the canonical `track1_safety_jobs()` table and runtime safety payload include it. The implementation reads the canonical table, so the Sunday sweep is eligible when actually registered.

- The real `TRACK1_NKD_0205` failure remains an unclassified `NameError`, as required. No production or live-investigation file was touched.
