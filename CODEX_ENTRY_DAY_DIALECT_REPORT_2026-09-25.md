# BASELINES

All seven required suites passed before any implementation attempt:

```text
$ python -m pytest global_index/test_contract_month.py -q
........                                                                 [100%]
8 passed in 2.50s

$ python -m pytest global_index/test_operational_fixes.py -q
.......................................                                  [100%]
39 passed in 3.28s

$ python -m pytest global_index/test_stp.py -q
.....................................................                    [100%]
53 passed in 4.86s

$ python -m pytest global_index/test_runner_book_dialects.py -q
..........                                                               [100%]
10 passed in 2.15s

$ python -m pytest global_index/test_arm_time_per_sleeve.py -q
...................                                                      [100%]
19 passed in 2.35s

$ python -m pytest global_index/test_stop_deferral.py -q
...                                                                      [100%]
3 passed in 2.50s

$ python -m pytest global_index/test_stop_placement_time.py -q
.....                                                                    [100%]
5 passed in 2.67s
```

# GOLDEN

The pre-change golden is at:

```text
global_index/test_entry_day_dialect_golden.json
```

Its executable comparison is:

```text
global_index/test_entry_day_dialect_golden.py
```

It records nine root position-book files, fourteen position rows, and the complete parser-result digest for every row. All fourteen rows loaded before this task; none raised.

The test permits exactly one kind of change: `entry_day` may move from `None` to the first ten characters of `entry_time`, and only when those characters are a complete `YYYY-MM-DD` date. Every other parsed value is normalized against its pre-change digest.

Current comparison:

```text
$ python -m pytest global_index/test_entry_day_dialect_golden.py -q
.                                                                        [100%]
1 passed in 1.99s
```

Changed rows: zero, because the reader change was not applied. The requested derivation would change six recorded rows across the live book and retained snapshots: M2K, MYM, and MNKD occurrences whose `entry_time` contains a date. MES is correctly excluded by G6 because its current `entry_time` is only `15:00`.

# CHANGE

No change was made to `global_index/runner.py`.

The safe reader change described by section 2 would conceptually replace:

```python
entry_day=pd.Timestamp(d["entry_day"]) if d.get("entry_day") else None,
```

with conflict-checked optional dialect handling where explicit `entry_day` wins and a complete date may be derived from `entry_time`.

It was not applied because it cannot pass G5 and G6 simultaneously on the current four-row book. The measured MES row is:

```text
instrument=MES
entry_time=15:00
trade_id=normal_r4::MES::2026-09-25
```

`entry_time` carries no date. G6 forbids changing `entry_day` for such a row, while G5 requires MES to become deferred. Inferring from `trade_id`, the wall clock, or the current day would exceed the authorized change and create a new source-of-truth rule.

# GATES

## G1 — FAIL / NOT IMPLEMENTED

The current reader still returns `None` for both date-bearing Track 1 forms:

```text
$ python -c "import json,sys; sys.path.insert(0,'.'); from global_index.runner import _openpos_from_dict; rows=json.load(open('live_positions.track1.json',encoding='utf-8'))['positions']; [print(_openpos_from_dict(r).inst, _openpos_from_dict(r).entry_day) for r in rows]"
M2K None
MYM None
MNKD None
MES None
```

The change was withheld because the complete gate set is inconsistent.

## G2 — PASS in current code

An explicit legacy `entry_day` is already read unchanged. Because `entry_time` is not currently considered, explicit values continue to win.

Covered by the unchanged dialect and stop suites:

```text
global_index/test_runner_book_dialects.py  10 passed
global_index/test_stop_deferral.py          3 passed
```

## G3 — FAIL / NOT IMPLEMENTED

The current reader ignores `entry_time`, so conflicting `entry_day` and `entry_time` do not raise. Adding that conflict check alone would be straightforward, but shipping only part of the reader change while G5 remains impossible would put an unapproved partial change on the live order path.

## G4 — PASS

The unchanged reader returns `entry_day=None` when neither date field exists. The unchanged rule contains:

```python
if p.entry_day is None:
    return False       # unknown entry date -> protect, do not guess
```

Therefore a dateless row still reads not-deferred.

## G5 — FAIL; specification contradiction reproduced

Command:

```text
$ python - <<diagnostic using the four live rows and 2026-09-25 16:30 ET>>
CURRENT [('M2K', 'None', False), ('MYM', 'None', False), ('MNKD', 'None', False), ('MES', 'None', False)]
MANDATED_DERIVATION [('M2K', '2026-09-24 00:00:00', False), ('MYM', '2026-09-24 00:00:00', False), ('MNKD', '2026-09-25 00:00:00', True), ('MES', 'None', False)]
```

The prescribed derivation produces three armed and one deferred, not two and two. Deferring MES requires another authorized date source or a corrected `entry_time` writer.

## G6 — PASS for the retained pre-change state

```text
$ python -m pytest global_index/test_entry_day_dialect_golden.py -q
.                                                                        [100%]
1 passed in 1.99s
```

Fourteen rows are equivalent and zero values changed. The golden rejects deriving a date for MES because `15:00` does not carry one.

## G7 — PASS

All seven post-check suites retained their baseline counts; complete output is in SUITES.

## G8 — PASS

Position-content digests before:

```text
[('live_positions.json', 0, '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945'),
 ('live_positions.track1.json', 4, 'df01b167de039dfe5e0402fc9f548360bd1291ced3499c1aa9c082a3dc71f931')]
```

Position-content digests after:

```text
[('live_positions.json', 0, '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945'),
 ('live_positions.track1.json', 4, 'df01b167de039dfe5e0402fc9f548360bd1291ced3499c1aa9c082a3dc71f931')]
```

No book position content changed.

# SUITES

| Suite | Before | After |
|---|---:|---:|
| `global_index/test_contract_month.py` | 8 passed | 8 passed |
| `global_index/test_operational_fixes.py` | 39 passed | 39 passed |
| `global_index/test_stp.py` | 53 passed | 53 passed |
| `global_index/test_runner_book_dialects.py` | 10 passed | 10 passed |
| `global_index/test_arm_time_per_sleeve.py` | 19 passed | 19 passed |
| `global_index/test_stop_deferral.py` | 3 passed | 3 passed |
| `global_index/test_stop_placement_time.py` | 5 passed | 5 passed |

Post-check raw output:

```text
$ python -m pytest global_index/test_contract_month.py -q
........                                                                 [100%]
8 passed in 2.30s

$ python -m pytest global_index/test_operational_fixes.py -q
.......................................                                  [100%]
39 passed in 2.93s

$ python -m pytest global_index/test_stp.py -q
.....................................................                    [100%]
53 passed in 4.20s

$ python -m pytest global_index/test_runner_book_dialects.py -q
..........                                                               [100%]
10 passed in 2.08s

$ python -m pytest global_index/test_arm_time_per_sleeve.py -q
...................                                                      [100%]
19 passed in 2.19s

$ python -m pytest global_index/test_stop_deferral.py -q
...                                                                      [100%]
3 passed in 2.38s

$ python -m pytest global_index/test_stop_placement_time.py -q
.....                                                                    [100%]
5 passed in 2.69s
```

# MEASURED

## 4.1 Does the sweep persist the book, and in which shape?

The 16:20 stop-repair sweep did not persist the book because its normal path only constructs `FuturesRunner`, reads `_b4_naked_stops`, and returns. B4 may assign the accepted stop ID in memory:

```python
if _sid:
    p.stop_order_id = _sid
    logger.warning("B4 REPLACED: ...")
    continue
```

But that branch does not call `_persist_state()`. `run_stop_repair.main()` then does:

```python
runner = FuturesRunner(...)
naked = list(getattr(runner, "_b4_naked_stops", []))
...
return 0
```

The `_persist_state()` calls are in max-hold processing, rollover recovery, rollover completion, the daily runner, and stop-exit bookkeeping—not in the B4 replacement branch used by this sweep. That is why all four route rows retained their route-owned fields after 16:20.

Section 4.1 is partly factually wrong about the potential serialized shape. `_openpos_to_dict` does emit:

```python
"risk_dollars": p.risk_dollars,
"sleeve":       p.cluster,
```

It would strip `trade_id`, `entry_time`, and route `order_id`; it would not strip `risk_dollars` or `sleeve`.

## 4.2 Existing working stop after the position becomes deferred

The code leaves the already-placed stop untouched. Deferred positions are first identified and logged:

```python
_deferred = [p for p in loaded_positions if self._stop_deferred(p)]
```

They are then excluded from the only B4 branch that can inspect or place a stop:

```python
naked = [p for p in loaded_positions
         if broker_key.get((p.inst, p.direction), 0) > 0
         and not self._stop_deferred(p)
         and (...)]
```

There is no cancellation branch for a deferred position. Therefore, if MNKD or MES becomes deferred while an early STP is already working, the 18:20 sweep will neither cancel it nor replace it. It remains working. Applying the reader fix alone would prevent another placement attempt but would not restore the intended stop-free window for an order already placed.

# NOT DONE

The `global_index/runner.py` reader change was not applied because the required gate set cannot pass against the current live evidence.

To proceed, the operator/specification author must authorize one of these:

1. Treat the dated `trade_id` as a fallback date source when `entry_time` contains only a clock; or
2. Correct the writer/book row so MES carries a dated `entry_time`, then rebuild the golden and rerun G5–G8.

No broker order was placed or cancelled. No scheduler or backend was restarted. No book, runtime artifact, sweep entry point, monitor file, scratch file, `TASK.md`, or `SCRATCHPAD.md` was modified. No `git add` or `git commit` was run.

# PLAN PROBLEMS

1. Section 6 names eight report sections, while the request says nine. This report uses the eight names actually specified rather than inventing an unnamed ninth section.

2. G5 and G6 conflict on the current MES row. G5 requires MES to be deferred; G6 permits `entry_day` to change only when `entry_time` carries a date. MES has `entry_time="15:00"`, so both cannot be true under the authorized derivation.

3. Section 2 says both R4 and NKD live values carry the required date portion. That is true for M2K, MYM, and MNKD, but false for the current MES row.

4. Section 4.1 says `_openpos_to_dict` omits `risk_dollars` and `sleeve`. The function emits both. It does omit `trade_id`, `entry_time`, and route `order_id`.
