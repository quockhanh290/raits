## CONSUMER SURVEY

Survey command and raw output:

```text
> rg -l "\bentry_time\b" global_index -g "*.py" -g "!test*.py"
global_index\generate_replay_snapshots.py
global_index\ibkr_broker.py
global_index\replay_checkpoint.py
global_index\route_checkpoint.py
global_index\runner.py
global_index\run_live_day_track1.py
global_index\track1_book_backfill.py
global_index\track1_bootstrap.py
global_index\track1_calm_a.py
global_index\track1_explain.py
global_index\track1_live_source.py
global_index\track1_normal_r4.py
global_index\track1_paper_order.py
global_index\track1_paper_send.py
global_index\track1_signals.py
global_index\track1_signal_layer.py
global_index\track1_strategy_diagnostics.py
global_index\track1_stress_mnq.py
global_index\track1_trade_log_backfill.py
global_index\verify_concat_desired.py
global_index\_core.py
```

The 21 lexical matches were reviewed before changing the producer:

- `generate_replay_snapshots.py`: serializes timestamps through `_ts_str` or passes the value through. Full timestamps are already its supported form; no edit.
- `ibkr_broker.py`: prose variable name in a timing estimate, not the position field; no edit.
- `replay_checkpoint.py`: `_pos_from_json` calls `pd.Timestamp` for `entry_time`; the dated form is accepted. P1.2 asserts this conversion; no edit.
- `route_checkpoint.py`: same `pd.Timestamp` conversion as the replay checkpoint. P1.2 asserts it; no edit.
- `runner.py`: its dashboard payload currently emits `entry_time: None`; the row reader is the authorized Part 2 edit. No clock-only dependency exists.
- `run_live_day_track1.py`: displays with `str`, extracts the window clock through `_hhmm_on`, and extracts the session with `_day`. The full value preserves the same 15:00 clock while making the session real; no edit, as required.
- `track1_book_backfill.py`: writes an already dated timestamp; no edit.
- `track1_bootstrap.py`: parses with `pd.Timestamp`, compares timestamps, and derives a date. The full value is supported and prevents parsing a clock against the machine's current date; no edit.
- `track1_calm_a.py`: separate Calm setup whose `entry_time` is already a `pd.Timestamp`; no dependency on the swing producer.
- `track1_explain.py`: schema/feature name only; no value parsing.
- `track1_live_source.py`: direct pass-through `entry_time=setup.entry_time` into `Candidate`. P1.2 asserts the pass-through remains present; no edit.
- `track1_normal_r4.py`: backtest position timestamps are already full; only the live setup builder discarded the date. This is the Part 1 edit.
- `track1_paper_order.py`: prose explicitly says `ref_day` is not derived from `candidate.entry_time`; no field read.
- `track1_paper_send.py`: string serialization preserves the full value. Its trade-log `entry_time[:10]` now receives a date for future swing rows, which is the intended repair rather than a clock behavior that must be retained; no edit.
- `track1_signals.py`: Calm parameter/feature name only; no parsing of the changed swing value.
- `track1_signal_layer.py`: `pd.Timestamp` and `_hhmm_on` accept both forms. P1.2 asserts the swing window verdict is identical for `15:00` and `2026-09-25 15:00:00`; no edit.
- `track1_strategy_diagnostics.py`: Calm parameter/feature name only; no dependency on the swing producer.
- `track1_stress_mnq.py`: separate Stress setup whose value is already a `pd.Timestamp`; no dependency on the swing producer.
- `track1_trade_log_backfill.py`: date-prefix matching now works for future live swing rows; this is the intended date preservation, not a reason to strip the date upstream; no edit.
- `verify_concat_desired.py`: explicitly parses `entry_time` with `pd.Timestamp`; full timestamps are its expected input.
- `_core.py`: optional timestamp type declaration only.

P1.2 also contains an explicit 21-file inventory assertion so additions/removals cannot silently invalidate the survey. The actual changed swing path is asserted through the live-source pass-through, window clock, replay checkpoint, and route checkpoint.

## CHANGE

Part 1, `global_index/track1_normal_r4.py:722`, setup builder only:

```diff
-                      stop=float(stop), entry_time=str(pd.Timestamp(bar_ts).time())[:5],
+                      stop=float(stop), entry_time=str(pd.Timestamp(bar_ts)),
```

Part 2, `global_index/runner.py:320-342`, row reader only:

```python
def entry_day_value():
    explicit = pd.Timestamp(d["entry_day"]) if d.get("entry_day") else None
    entry_time = str(d.get("entry_time") or "")
    derived = None
    if (len(entry_time) >= 10 and entry_time[4:5] == "-"
            and entry_time[7:8] == "-"):
        parsed = pd.to_datetime(entry_time[:10], format="%Y-%m-%d", errors="coerce")
        if not pd.isna(parsed):
            derived = pd.Timestamp(parsed)
    if (explicit is not None and derived is not None
            and explicit.normalize().tz_localize(None) != derived):
        raise ValueError(
            f"conflicting values for entry_day/entry_time: "
            f"{d['entry_day']!r} != {entry_time!r}")
    return explicit if explicit is not None else derived
```

The constructor now uses:

```diff
-        entry_day=pd.Timestamp(d["entry_day"]) if d.get("entry_day") else None,
+        entry_day=entry_day_value(),
```

New tests/golden:

- `global_index/test_entrydate_v2.py`
- `global_index/test_entrydate_golden.json`

No production file outside the two authorized functions was changed by this task.

## GATES

P1.1 PASS, P1.2 PASS, P1.3 PASS, P2.1 PASS, P2.2 PASS, P2.3 PASS, P2.4 PASS, P2.5 PASS, and P2.6 PASS.

Command and raw output:

```text
> python -m pytest global_index/test_entrydate_v2.py -vv
============================= test session starts =============================
platform win32 -- Python 3.11.4, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\quock\AppData\Local\Programs\Python\Python311\python.exe
cachedir: .pytest_cache
hypothesis profile 'default'
rootdir: D:\raits
configfile: pyproject.toml
plugins: anyio-4.12.1, hypothesis-6.151.9, cov-7.0.0
collecting ... collected 9 items

global_index/test_entrydate_v2.py::test_p1_1_live_swing_setup_keeps_the_signal_date PASSED [ 11%]
global_index/test_entrydate_v2.py::test_p1_2_all_twenty_one_consumers_are_surveyed_and_timestamp_safe PASSED [ 22%]
global_index/test_entrydate_v2.py::test_p1_3_nkd_aware_stamp_path_is_untouched_and_byte_identical PASSED [ 33%]
global_index/test_entrydate_v2.py::test_p2_1_dated_entry_times_yield_et_naive_and_tokyo_dates PASSED [ 44%]
global_index/test_entrydate_v2.py::test_p2_2_bare_clock_does_not_guess_and_remains_not_deferred PASSED [ 55%]
global_index/test_entrydate_v2.py::test_p2_3_explicit_entry_day_wins_when_no_date_can_be_derived PASSED [ 66%]
global_index/test_entrydate_v2.py::test_p2_4_disagreeing_entry_day_and_entry_time_raise_with_both_field_names PASSED [ 77%]
global_index/test_entrydate_v2.py::test_p2_5_four_measured_rows_split_due_deferred_and_absent_date PASSED [ 88%]
global_index/test_entrydate_v2.py::test_p2_6_every_on_disk_row_matches_the_nonempty_prechange_golden PASSED [100%]

============================== 9 passed in 1.10s ==============================
```

P2.5's fixed-clock outcomes at `2026-09-25 16:30 ET` are M2K `False` (due), MYM `False` (due), MNKD `True` (deferred), and MES `False`. The test separately asserts `MES.entry_day is None`; therefore its result is the reader's absent-date branch, not a computed arm-time verdict. After the operator performs Part 3, MES is expected to flip to deferred and this gate must be updated at that time, not before.

P2.6 rebuilt a non-empty 14-row golden across nine book/snapshot files. It permits exactly these six changes and no others: base rows 5, 6, 7 and current live M2K, MYM, MNKD, each `entry_day: None -> entry_time[0:10]`. The current MES row and the two empty-clock snapshot rows remain `None`. All other loaded values retain their pre-change digest.

Formatting gate:

```text
> git diff --check -- global_index/runner.py global_index/track1_normal_r4.py global_index/test_entrydate_v2.py global_index/test_entrydate_golden.json
warning: in the working copy of 'global_index/runner.py', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'global_index/track1_normal_r4.py', LF will be replaced by CRLF the next time Git touches it
```

Exit code 0; there are no whitespace errors.

## SUITES

Before changes, measured in this worktree:

```text
> python -m pytest global_index/test_contract_month.py -q
........                                                                 [100%]
8 passed in 1.98s
> python -m pytest global_index/test_operational_fixes.py -q
.......................................                                  [100%]
39 passed in 2.60s
> python -m pytest global_index/test_stp.py -q
.....................................................                    [100%]
53 passed in 3.74s
> python -m pytest global_index/test_runner_book_dialects.py -q
..........                                                               [100%]
10 passed in 1.76s
> python -m pytest global_index/test_arm_time_per_sleeve.py -q
...................                                                      [100%]
19 passed in 1.85s
> python -m pytest global_index/test_stop_deferral.py -q
...                                                                      [100%]
3 passed in 2.00s
> python -m pytest global_index/test_stop_placement_time.py -q
.....                                                                    [100%]
5 passed in 2.24s
```

After changes, raw output:

```text
> python -m pytest global_index/test_contract_month.py -q
........                                                                 [100%]
8 passed in 1.49s
> python -m pytest global_index/test_operational_fixes.py -q
.......................................                                  [100%]
39 passed in 1.81s
> python -m pytest global_index/test_stp.py -q
.....................................................                    [100%]
53 passed in 2.66s
> python -m pytest global_index/test_runner_book_dialects.py -q
..........                                                               [100%]
10 passed in 1.33s
> python -m pytest global_index/test_arm_time_per_sleeve.py -q
...................                                                      [100%]
19 passed in 1.53s
> python -m pytest global_index/test_stop_deferral.py -q
...                                                                      [100%]
3 passed in 1.43s
> python -m pytest global_index/test_stop_placement_time.py -q
.....                                                                    [100%]
5 passed in 1.67s
```

All seven retain their baseline pass counts. No test encoding the arming rule was edited.

## PART 3

Proposed operator repair, not written:

```json
"entry_time": "2026-09-25 15:00:00"
```

This replaces the MES row's current bare `"15:00"`; seconds are made explicit to match the producer's `str(pd.Timestamp(...))` form. The clock remains the strategy's existing entry-reference clock. The date comes from `ref_day` on the MES order journal's `state: "filled"` record, not from `trade_id`. `ref_day` is route-owned input attached to that actual OPEN order, while `created_at` independently corroborates that the fill occurred on the same ET calendar day: `2026-09-25T19:07:02+00:00` is 15:07:02 ET. `created_at` is the journal event time, not the strategy entry-reference time, so it must not replace `15:00`.

Evidence command and raw output:

```text
> rg -n "normal_r4::MES::2026-09-25|2026-09-25T19:07:02" global_index/track1_runtime/orders
global_index/track1_runtime/orders\track1_orders_20260925.jsonl:5:{"action": "OPEN", "avg_price": 0.0, "candidate_id": "normal_r4::MES::2026-09-25", "commission": 0.0, "created_at": "2026-09-25T19:07:01+00:00", "error": "", "fill_status": "", "filled_qty": 0, "idempotency_key": "track1_candidate:2026-09-25:roska4_swing:MES:OPEN:normal_r4::MES::2026-09-25", "instrument": "MES", "order_id": "", "planned_stop_distance": null, "planned_stop_price": null, "planned_stop_type": "", "qty": 1, "ref_day": "2026-09-25", "route": "track1_candidate", "schema_version": 1, "sleeve": "roska4_swing", "slot_id": "TRACK1_SWING_1505", "state": "intended", "tradable_symbol": "MES"}
global_index/track1_runtime/orders\track1_orders_20260925.jsonl:6:{"action": "OPEN", "avg_price": 0.0, "candidate_id": "normal_r4::MES::2026-09-25", "commission": 0.0, "created_at": "2026-09-25T19:07:01+00:00", "error": "", "fill_status": "", "filled_qty": 0, "idempotency_key": "track1_candidate:2026-09-25:roska4_swing:MES:OPEN:normal_r4::MES::2026-09-25", "instrument": "MES", "order_id": "", "planned_stop_distance": null, "planned_stop_price": null, "planned_stop_type": "", "qty": 1, "ref_day": "2026-09-25", "route": "track1_candidate", "schema_version": 1, "sleeve": "roska4_swing", "slot_id": "TRACK1_SWING_1505", "state": "submitted", "tradable_symbol": "MES"}
global_index/track1_runtime/orders\track1_orders_20260925.jsonl:7:{"action": "OPEN", "avg_price": 0.0, "candidate_id": "normal_r4::MES::2026-09-25", "commission": 0.0, "created_at": "2026-09-25T19:07:01+00:00", "error": "", "fill_status": "", "filled_qty": 0, "idempotency_key": "track1_candidate:2026-09-25:roska4_swing:MES:OPEN:normal_r4::MES::2026-09-25", "instrument": "MES", "order_id": "68", "planned_stop_distance": null, "planned_stop_price": null, "planned_stop_type": "", "qty": 1, "ref_day": "2026-09-25", "route": "track1_candidate", "schema_version": 1, "sleeve": "roska4_swing", "slot_id": "TRACK1_SWING_1505", "state": "submitted", "tradable_symbol": "MES"}
global_index/track1_runtime/orders\track1_orders_20260925.jsonl:8:{"action": "OPEN", "avg_price": 7797.25, "candidate_id": "normal_r4::MES::2026-09-25", "commission": 0.61, "created_at": "2026-09-25T19:07:02+00:00", "error": "", "fill_status": "FILLED", "filled_qty": 0, "idempotency_key": "track1_candidate:2026-09-25:roska4_swing:MES:OPEN:normal_r4::MES::2026-09-25", "instrument": "MES", "order_id": "68", "planned_stop_distance": null, "planned_stop_price": null, "planned_stop_type": "", "qty": 1, "ref_day": "2026-09-25", "route": "track1_candidate", "schema_version": 1, "sleeve": "roska4_swing", "slot_id": "TRACK1_SWING_1505", "state": "filled", "tradable_symbol": "MES"}
```

## BOOK

Before and after are identical; no book or snapshot was written. Position content both times:

```text
positions_count= 4
M2K  sleeve=roska4_swing entry_time='2026-09-24 15:55:00'       entry_day=<absent> qty=1 order_id='30'
MYM  sleeve=roska4_swing entry_time='2026-09-24 15:55:00'       entry_day=<absent> qty=1 order_id='28'
MNKD sleeve=global_nkd   entry_time='2026-09-25 14:20:00+09:00' entry_day=<absent> qty=1 order_id='40'
MES  sleeve=roska4_swing entry_time='15:00'                     entry_day=<absent> qty=1 order_id='68'
```

The parser now derives dates in memory for M2K, MYM, and MNKD. It does not mutate their JSON rows. MES still loads with `entry_day=None`.

## NOT DONE

- The MES book repair was not written. It is the operator's Part 3 action and requires their snapshot-first procedure.
- The absent-date condition was not added to a dashboard or status payload because the authorized production files permit only the setup builder and row reader edits. The appropriate surface is the position/status payload near `runner.py`'s open-position serialization: emit a distinct machine-readable state such as `stop_deferral_status: "unknown_missing_entry_date"`, then render that state. It must not label the position due or deferred.
- No broker order was placed or cancelled. The scheduler and backend were not restarted. No `git add` or `git commit` was run. No full test suite was run.

## SPEC PROBLEMS

- The statement that `entry_time` is “read in twenty-one files” is only true as a lexical count of non-test Python files under `global_index`. `ibkr_broker.py` is prose, `track1_paper_order.py` is prose, and several other matches are type declarations, feature names, or unrelated Calm/Stress producers. The actual changed swing value has fewer consumers. The report lists all 21 so the measured count remains reproducible.
- P1.2 cannot literally require every observable consumer output to remain identical: the intended fix necessarily changes date-sensitive results in `track1_paper_send.py`, `track1_bootstrap.py`, `track1_trade_log_backfill.py`, and session extraction in `run_live_day_track1.py`. The safe invariant is that clock/window/trading behavior is unchanged while the previously discarded date is preserved. The gate asserts that invariant and guards the complete 21-file survey.
- P2.5 asks for an asserted “reason,” but `_stop_deferred` returns only a boolean and the allowed Part 2 change is restricted to the row reader. Within that scope, the strongest non-invented assertion is the pair `MES.entry_day is None` and `_stop_deferred(...) is False`, which directly exercises the absent-date branch. A production-readable reason requires the separate status-surface change proposed under NOT DONE.
