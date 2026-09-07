# Track 1 shadow window — what to check after a window closes

*For the operator. Everything here is read-only. Nothing in this document asks you to start,
stop, arm, or repair anything.*

Written 2026-08-25 (Stage 5ZB) because the answer was previously spread across a dozen stage
reports, and a checklist you have to reconstruct is a checklist nobody runs.

---

## 0. Anchor the clock before you read anything

**Do not use `date` in git bash, and do not use `TZ=America/New_York date`.** On this machine
that returns UTC, and a whole audit hour was lost to it during Stage 5ZB — a window was read as
"four hours overdue" when it was three and a half hours away.

```powershell
python -c "import datetime as dt; from zoneinfo import ZoneInfo; u=dt.datetime.now(dt.timezone.utc); print('UTC ', u.strftime('%Y-%m-%d %H:%M')); print('ET  ', u.astimezone(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M %Z')); print('Calgary', u.astimezone(ZoneInfo('America/Edmonton')).strftime('%H:%M %Z')); print('Tokyo', u.astimezone(ZoneInfo('Asia/Tokyo')).strftime('%H:%M %Z'))"
```

Three clocks, and they are never the same one:

| clock | who uses it |
|---|---|
| **ET** | every window, every slot id, every ledger `date` |
| **Calgary** (machine local) | the scheduler log's own timestamps |
| **Tokyo** | MNKD's session — 14:10–15:55 JST is the NKD window |

The scheduler log stamps **Calgary** time. A line reading `04:20` next to a job named
`STOP_REPAIR_0620` is not a contradiction: 04:20 Calgary **is** 06:20 ET.

---

## 1. The windows, and when each closes

| sleeve | slots | ET window | closes |
|---|---:|---|---|
| `roska4_calm` | 1 | 10:00 (one shot) | 10:00 |
| `roska4_stress` | 24 | 10:35 – 12:30 | 12:30 |
| `roska4_swing` | 23 | 14:05 – 15:55 | 15:55 |
| `global_nkd` | 22 | 01:10 – 02:55 | 02:55 |

The per-sleeve audit runs ten minutes after each window closes.

---

## 2. What to inspect, in order

### 2.1 Window coverage — did the window open, run, and close?

```
global_index/track1_runtime/window_coverage/window_coverage_YYYYMMDD.jsonl
```

Three event types. Read them in this order:

1. **`window_open`** — one per sleeve. Carries `expected_slots`.
2. **`slot_observed`** — one per slot that ran. Carries `decided`, `reason`, `detail`.
3. **`window_closed`** — one per sleeve, carrying `observed_slots` against `expected_slots`.

**An opened window with no `window_closed` is the loudest signal in the whole system.** It
means the last slot of that sleeve never finished — absence is deliberately the signal, so it
cannot be faked by a process that died. Look at the scheduler log for that slot's traceback.

> Seen once, 2026-08-24 `roska4_calm`: the slot crashed on a splice refusal before writing its
> row, leaving the window open forever. Both causes are fixed; the historical row stays.

**Count `slot_observed` rows against `expected_slots`.** Missing rows mean slots that did not
run at all — a different problem from slots that ran and refused.

### 2.2 Refusal reasons — which kind of "no" was it?

Group the `slot_observed` rows by `reason` and `detail`. The three families mean different
things and lead to different actions:

| reason | means | where to look next |
|---|---|---|
| `gate_refused` + `partial_coverage` / `stale` / `gap_in_coverage` | the intraday gate refused the frame | the frame, not the strategy |
| `gate_refused` + `too_late` | the slot fired after its band closed | benign; classified window-shut, not a data refusal |
| `overlap_disagreement` | the live feed and the frozen history disagree on a shared bar | §2.6 — this is a **history** problem |
| `freshness_*` | the daily inputs were stale | the daily CSV / parquet refresh jobs |

A window can be complete and still have decided nothing. `observed_slots` counts slots that
**decided**, not slots that ran.

### 2.3 Slot timing — did each slot fire on time and finish?

```
global_index/track1_runtime/slot_timing/slot_timing_YYYYMMDD.jsonl
```

One row per slot, carrying `pid`, `runtime_s`, `phases`, `outcome`, `reason`, `decided`.

Cross-check the count against §2.1: **a slot with a coverage row and no timing row, or the
reverse, is a half-written slot** and should be read as a crash until proven otherwise.

### 2.4 The audit row

```
python -m global_index.track1_shadow_audit --latest --sleeve <sleeve>
```

It runs automatically ten minutes after each window. It classifies the window as
`pass` / `incomplete` / `fail` / `unobserved`, and its verdict is what the paper-readiness gate
counts. A window that produced no decisions can still be a legitimate `pass` — what it may not
be is silently missing.

### 2.5 Explanations — only if candidates existed

```
global_index/track1_runtime/shadow/<per-sleeve, per-slot window>/
```

Only expect files where a slot actually had candidates. **No explanations is not the same as
nothing to explain** — the slot summary records which it was, and that distinction is the one
the dashboard audit got wrong once. If a slot admitted a candidate and wrote no explanation,
that is a defect.

### 2.6 `overlap_disagreement` — read this before blaming the feed

The `detail` names the instrument, how many shared timestamps disagree, the first one, both
values, and the largest gap. Example:

```
MNQ: the live half and history disagree on 1 of 1186 shared timestamps in 'low';
first at 2026-08-21 13:45:00-04:00, history says 29400.2500 and the feed says 29395.7500
```

**13:45 ET is the daily append boundary.** A single disagreeing bar at that timestamp is a
history-append artefact, not a live-feed fault, and it is what the boundary repair exists for.

Do **not** widen the tolerance. The guard is the reason a corrupt bar cannot reach a decision.

### 2.7 What must NOT exist

While the route is in shadow, none of these should be on disk. Any of them appearing means
something ran that should not have:

| path | if it exists |
|---|---|
| `global_index/track1_runtime/orders/` | an order journal was written — **stop and investigate** |
| `global_index/live_positions.track1.json` | the route believes it holds a position |
| `track1_dry_run/` | a dry-run rehearsal wrote here in the repo root |
| `track1_go_live_confirmation.json` | the order gate's confirmation file |

`global_index/replay_checkpoint.track1.json` **is** expected — it is the shadow checkpoint and
is written on a normal run.

### 2.8 Dashboard schedule-status consistency

```
python monitor/ops.py status
```

Confirm:

- `track1_mode=track1-only-shadow`
- `track1_blocking` lists both open blockers
- `orders_possible=False`
- `confirmation=False`, `track1_orders_approved=False`

Then compare the dashboard's schedule view against the ledger. **A slot that ran should not
appear overdue**, and a window that closed should not still read as open. A disagreement
between the two is a reader bug, not a runtime failure — but it is the reader operators trust.

---

## 3. The one-line health check

```powershell
python -c "import json,collections,pathlib; d=pathlib.Path('global_index/track1_runtime/window_coverage'); p=sorted(d.glob('window_coverage_*.jsonl'))[-1]; rows=[json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]; obs=[r for r in rows if r.get('event')=='slot_observed']; op={r.get('sleeve') for r in rows if r.get('event')=='window_open'}; cl={r.get('sleeve') for r in rows if r.get('event')=='window_closed'}; print(p.name); print(' slots:', len(obs)); print(' reasons:', dict(collections.Counter(r.get('reason') for r in obs))); print(' NEVER CLOSED:', sorted(op-cl) or 'none')"
```

---

## 4. Orders are not possible, and here is how to confirm it

Four independent facts. Check all four; any one of them alone is not the answer.

1. `monitor/ops.py status` → `orders_possible=False` with both blockers listed.
2. `track1_go_live_confirmation.json` does not exist.
3. `TRACK1_ORDERS_APPROVED` is unset or `0`.
4. No scheduler or ops argv contains `--allow-orders` — and the slot path takes no order
   argument at all, so there is no argument by which a slot could reach a broker.

---

## 5. Before the first paper fill

Not a checklist for today. Recorded here so it is not discovered on the day.

The first paper fill writes `live_positions.track1.json`, and that file is what **eleven Track 1
safety jobs** watch. They have never run against a real Track 1 book — they no-op today purely
because the file is absent. On the first fill they begin connecting to IBKR on the Track 1
safety client id, placing protective stops and booking max-hold exits.

That should be a watched event with someone present, not a side effect noticed afterwards.

Known and accepted for the first paper day: stops and exits placed by those safety jobs write
`trade_log.jsonl`, **not** the order journal. The order journal will show the entry and nothing
else until a later stage routes them through the executor.
