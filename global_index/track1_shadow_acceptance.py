"""global_index/track1_shadow_acceptance.py — the gate a shadow day is judged by. NEW FILE.

Stage 5P. Read-only and pure: it reads the Track 1 runtime directories and returns a verdict.
Nothing here starts anything, connects to anything, or writes anywhere.

Why this is a module and not a section of a runbook
---------------------------------------------------
The shadow period exists to produce evidence, and evidence needs a judge whose questions were
fixed BEFORE the answers existed. A runbook paragraph gets re-read charitably after the fact;
a function returns the same named refusals on every day it is shown. The thresholds below are
committed now, while no shadow day exists to be graded, so they cannot drift toward whatever
the first day happens to produce.

The checks, and where each threshold comes from
------------------------------------------------
    coverage        every sleeve's window COMPLETE: Calm 1, Stress 24, Normal-R4 23, NKD 22
                    decided slots, with a close record — the ledger's own fail-closed rule.
                    Expected counts come from the ledger table, not restated here.
    slot gaps       every registered slot id present as a ledger row. A window can read
                    complete-by-count while a specific slot never fired and another fired
                    twice; the ids are the check the count cannot do.
    runtime         p95 < 300s REQUIRED — the slot cadence is 300s, and a p95 at or above it
                    means slots overrun into each other. p95 < 240s is the TARGET (legacy's
                    own median is 194s of a 300s window); missing the target is reported,
                    not failed.
    stalls          no slot record may show runtime >= 300s (an overrun IS a stall inside a
                    window), and no gap: see slot gaps.
    orders          none attempted: no telemetry or ledger record carries an order mark, the
                    gate registry still refuses an order, the out-of-band approval is unset and
                    no order journal exists. Stage 5ZZZ-A: a signed B1 confirmation is NOT one
                    of these. It records a decision; whether an order could be sent is a
                    question for the gate registry, and it is asked there.
    freshness       every DECIDED slot's explanation records carry a freshness proof — the
                    Stage 5Z contract: binding modes cite the gate they passed.
    explanations    present for the day, and validated rows only (the writer refuses invalid
                    rows, so presence of the file is presence of validated records).
    checkpoint      the route checkpoint file exists, is schema 2, carries this route under
                    `routes`, and is cut on the day under judgment. The cut day comes from
                    the entries' `last_day` when there are entries; on a QUIET window there
                    are none, so it comes from the book written in the same call. If neither
                    can answer, the check FAILS as `day_unverifiable` — it never passes for
                    lack of a way to look. What this check does NOT do is re-verify the
                    identity hashes against frames — that is `route_checkpoint.usable`'s job
                    and it needs the frames; the check says `identity: not_checked_here`
                    rather than silently passing it.
"""
from __future__ import annotations

import datetime as _dt
import json
import os as _os
from pathlib import Path
from typing import Any

#: Required ceiling and target for per-slot runtime. The ceiling is the slot cadence; the
#: target is under legacy's own measured median-plus-margin.
RUNTIME_P95_REQUIRED_S = 300.0
RUNTIME_P95_TARGET_S = 240.0

COVERAGE_DIR = "global_index/track1_runtime/window_coverage"
TIMING_DIR = "global_index/track1_runtime/slot_timing"
SHADOW_DIR = "global_index/track1_runtime/shadow"
CHECKPOINT_PATH = "global_index/replay_checkpoint.track1.json"
#: The book written in the SAME `track1_bootstrap.write` call as the checkpoint. It is where
#: the day proof lives on a quiet day: an empty checkpoint carries no `last_day` anywhere,
#: because `last_day` is a property of an instrument entry and there are none.
CHECKPOINT_BOOK_PATH = "live_positions.track1.json"
CONFIRMATION_PATH = "track1_go_live_confirmation.json"

#: Structured outcomes of the checkpoint check. Carried on the check dict as `code`, so the
#: audit can classify without matching prose — the reason mapping used to read
#: `"route is" in detail`, which ties a machine decision to a sentence anyone may reword.
CK_OK = "ok"
CK_MISSING = "missing"
CK_UNREADABLE = "unreadable"
CK_WRONG_ROUTE = "wrong_route"
CK_WRONG_DAY = "wrong_day"
CK_DAY_UNVERIFIABLE = "day_unverifiable"
#: Stage 5ZK. The book says something is open and the checkpoint records no position for it,
#: so a restart would resume flat against a book that is not. Fails closed.
CK_ENTRIES_MISSING_FOR_OPEN_BOOK = "entries_missing_for_open_book"
#: The mirror: entries carry a position and the book says flat. Same disagreement, other way
#: round, and named separately so a reader knows which side to believe.
CK_BOOK_DISAGREES_WITH_ENTRIES = "book_disagrees_with_entries"
#: An entry's history claim is older than a long weekend plus a holiday. Still a VALID prefix
#: — `route_checkpoint.usable` would accept it — but a checkpoint quietly describing history
#: from three weeks ago is the alarm that never fires.
CK_HISTORY_STALE = "history_stale"

#: How far behind the judged day an entry's `last_day` may sit. Five calendar days covers a
#: Friday close read on the following Monday plus one holiday. It is a judgement call, not a
#: derived quantity, and moving it changes what "current" means and nothing else.
CHECKPOINT_MAX_HISTORY_LAG_DAYS = 5

OK = "ok"
FAIL = "fail"
WARN = "warn"
NOT_CHECKED = "not_checked_here"


def _check(name: str, status: str, detail: str = "", **extra) -> dict:
    return {"name": name, "status": status, "detail": detail, **extra}


def checkpoint_check(root: Path, day: str) -> dict:
    """Does the route checkpoint on disk describe THIS route, cut on THIS day?

    Written against `route_checkpoint.save_route`'s actual output, which the version this
    replaces was not. That version read `payload["route"]` and `payload["cut_instant"]` —
    a flat shape the writer has never produced and the route module's own loader rejects
    outright, because it requires a `routes` key. Against the first real checkpoint the
    live system ever wrote it reported `route is None`, and it could not have reported
    anything else. Three test suites certified it green by building the same flat payload
    the reader believed in; not one of them ever asked the writer what it writes.

    The day proof is the COMPANION BOOK, always — for a quiet checkpoint and for a full one
    alike. Stage 5ZH used the entries' own `last_day` when there were entries, on the
    assumption that a checkpoint written at the close would name the day it closed. Stage 5ZK
    measured the store and the assumption is false: the daily append runs at 13:45 ET, so at
    the 15:55 close the parquet holds today only through 13:44 while yesterday runs to 23:59.
    A fingerprint through today is invalidated by the next append; one through the last
    COMPLETE day survives it. So a correct entry names the previous trading day, and a rule
    demanding it name the judged day would fail every real checkpoint the writer can produce.

    What `last_day` is still asked is that it is not from the FUTURE and not stale. Both are
    real conditions: a day ahead of the judgement means the artefact was written by something
    else, and a history three weeks behind is a checkpoint nobody has refreshed.

    The book proves the day because it is written in the same call, by the same function,
    atomically beside the checkpoint. When it cannot answer, the result is `day_unverifiable`
    and it FAILS. "I could not check" is not "I checked and it was fine", and collapsing the
    two is how a gate stops guarding.

    Stage 5ZK also closes the case the route has never reached and will the first day it holds
    something overnight: a book with open positions and a checkpoint that records none. A
    restart would then resume flat against a book that is not, which is the
    resume-a-state-that-never-existed failure the whole identity machinery exists to prevent.
    That fails closed as `entries_missing_for_open_book`, and the mirror — entries carrying a
    position while the book says flat — as `book_disagrees_with_entries`.
    """
    ck = root / CHECKPOINT_PATH
    if not ck.exists():
        return _check("checkpoint", FAIL, f"{CHECKPOINT_PATH} does not exist",
                      code=CK_MISSING)
    try:
        payload = json.loads(ck.read_text(encoding="utf-8"))
    except Exception as exc:                                   # noqa: BLE001
        return _check("checkpoint", FAIL, f"unreadable: {exc}", code=CK_UNREADABLE)

    if not isinstance(payload, dict):
        return _check("checkpoint", FAIL, "payload is not an object", code=CK_UNREADABLE)
    schema = payload.get("schema_version")
    if schema != 2:
        return _check("checkpoint", FAIL,
                      f"schema_version {schema!r} is not the route checkpoint shape (2)",
                      code=CK_UNREADABLE)
    routes = payload.get("routes")
    if not isinstance(routes, dict):
        return _check("checkpoint", FAIL,
                      "no `routes` map — this is not a schema 2 route checkpoint",
                      code=CK_UNREADABLE)
    if AUDIT_ROUTE not in routes:
        return _check("checkpoint", FAIL,
                      f"route {AUDIT_ROUTE!r} is not in the checkpoint; it holds "
                      f"{sorted(routes)!r}",
                      code=CK_WRONG_ROUTE)

    sleeves = (routes.get(AUDIT_ROUTE) or {}).get("sleeves") or {}
    entries = [e for s in sleeves.values()
               for e in ((s or {}).get("instruments") or {}).values()]
    has_entries = bool(entries)
    entries_with_pos = [e for e in entries if e.get("pos") is not None]

    # ── the day, from the book that was written with it ──────────────────────
    book = root / CHECKPOINT_BOOK_PATH
    shape = "with entries" if has_entries else "route present and empty"
    if not book.exists():
        return _check("checkpoint", FAIL,
                      f"{shape}, and {CHECKPOINT_BOOK_PATH} — written in the same call and "
                      f"the only record of the cut — does not exist, so the day cannot be "
                      f"verified",
                      code=CK_DAY_UNVERIFIABLE, entries=has_entries)
    try:
        bstate = json.loads(book.read_text(encoding="utf-8"))
        cut = str((bstate or {}).get("cut_instant") or "")[:10]
        positions = list((bstate or {}).get("positions") or [])
    except Exception as exc:                                   # noqa: BLE001
        return _check("checkpoint", FAIL,
                      f"{shape}, and {CHECKPOINT_BOOK_PATH} is unreadable ({exc}), so the "
                      f"day cannot be verified",
                      code=CK_DAY_UNVERIFIABLE, entries=has_entries)
    if not cut:
        return _check("checkpoint", FAIL,
                      f"{shape}, and {CHECKPOINT_BOOK_PATH} carries no cut_instant, so the "
                      f"day cannot be verified",
                      code=CK_DAY_UNVERIFIABLE, entries=has_entries)
    if cut != day:
        return _check("checkpoint", FAIL,
                      f"{shape}, and the book it was written with is cut on {cut!r}, not "
                      f"the day under judgment {day!r}",
                      code=CK_WRONG_DAY, entries=has_entries)

    # ── the book and the checkpoint must agree about whether anything is held ─
    if positions and not entries_with_pos:
        return _check("checkpoint", FAIL,
                      f"the book holds {len(positions)} open position(s) and the checkpoint "
                      f"records none — a restart would resume flat against a book that is "
                      f"not, which is the state the identity machinery exists to prevent",
                      code=CK_ENTRIES_MISSING_FOR_OPEN_BOOK, entries=has_entries,
                      open_positions=len(positions))
    if entries_with_pos and not positions:
        return _check("checkpoint", FAIL,
                      f"{len(entries_with_pos)} checkpoint entr(y/ies) carry a position and "
                      f"the book says flat — the two were written in one call and cannot "
                      f"disagree unless one of them is wrong",
                      code=CK_BOOK_DISAGREES_WITH_ENTRIES, entries=has_entries,
                      open_positions=0)

    if not has_entries:
        return _check("checkpoint", OK,
                      f"route ok, no entries (a quiet window admitted nothing), book cut "
                      f"{cut}, book flat",
                      code=CK_OK, entries=False)

    # ── the history claim: not from the future, not stale ────────────────────
    last_days = sorted({str(e.get("last_day")) for e in entries if e.get("last_day")})
    if len(last_days) != len(entries):
        missing = len(entries) - len([e for e in entries if e.get("last_day")])
        if missing:
            return _check("checkpoint", FAIL,
                          f"{missing} entr(y/ies) carry no last_day, so their history claim "
                          f"cannot be checked at all",
                          code=CK_UNREADABLE, entries=True)
    ahead = [d for d in last_days if d > day]
    if ahead:
        return _check("checkpoint", FAIL,
                      f"entries claim history through {ahead!r}, which is after the day "
                      f"under judgment {day!r}",
                      code=CK_WRONG_DAY, entries=True)
    try:
        judged = _dt.date.fromisoformat(day)
        lag = max((judged - _dt.date.fromisoformat(d)).days for d in last_days)
    except Exception as exc:                                   # noqa: BLE001
        return _check("checkpoint", FAIL,
                      f"entry last_day unparseable among {last_days!r}: {exc}",
                      code=CK_UNREADABLE, entries=True)
    if lag > CHECKPOINT_MAX_HISTORY_LAG_DAYS:
        return _check("checkpoint", FAIL,
                      f"the newest entry history is {lag} day(s) behind {day!r} "
                      f"(entries at {last_days!r}), past the {CHECKPOINT_MAX_HISTORY_LAG_DAYS}"
                      f"-day allowance",
                      code=CK_HISTORY_STALE, entries=True, history_lag_days=lag)
    return _check("checkpoint", OK,
                  f"route ok, {len(entries)} entr(y/ies) through {last_days!r} "
                  f"({lag} day(s) behind), book cut {cut}, "
                  f"{len(positions)} open position(s) matched",
                  code=CK_OK, entries=True, history_lag_days=lag,
                  open_positions=len(positions))


def _ledger_rows(root: Path, day: str) -> list:
    rows: list = []
    d = root / COVERAGE_DIR
    if not d.is_dir():
        return rows
    for f in sorted(d.glob("window_coverage_*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:                              # noqa: BLE001
                continue
            if str(rec.get("date")) == day:
                rows.append(rec)
    return rows


def explanation_attribution(path, root: str | Path = ".") -> dict:
    """Which day/sleeve/slot a file's rows belong to. Pass-through to the layout's owner.

    It exists so the DASHBOARD never imports `track1_explain`. That boundary is held by a
    test — the dashboard reads evidence and verdicts, and a panel that imported the writer
    would be one edit away from being able to produce them.
    """
    from global_index import track1_explain as tx
    return tx.attribution_from_path(path, root, out_dir=SHADOW_DIR)


def _timing_rows(root: Path, day_compact: str) -> list:
    f = root / TIMING_DIR / f"slot_timing_{day_compact}.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:                                  # noqa: BLE001
            continue
    return out


def _explanation_rows(root: Path, day_compact: str) -> list:
    """Every explanation row written for this day, from wherever the writer put it.

    Stage 5Q-1 repair: this read ONE flat path that nothing has ever written to. See
    `explanation_files` for the measurement.
    """
    out = []
    for f in explanation_files(root, day_compact):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except Exception:                              # noqa: BLE001
                continue
    return out


def evaluate_day(day, root: str | Path = ".") -> dict:
    """One shadow day against the full gate. `{day, accepted, checks[]}` — fails closed.

    `accepted` is True only when every REQUIRED check passed; WARN and NOT_CHECKED never
    fail a day and never silently pass one either — they are in the record by name.
    """
    import pandas as pd

    import global_index.window_ledger as wl
    from global_index import track1_slots as ts
    from global_index.track1_params import WINDOWS_ET

    root = Path(root)
    day = str(pd.Timestamp(day).date())
    day_compact = day.replace("-", "")
    checks: list = []

    # ── coverage, per sleeve, from the ledger's own judge ────────────────────
    rows = _ledger_rows(root, day)
    for sleeve in sorted(WINDOWS_ET):
        st = wl.status(rows, sleeve, day)
        if st["outcome"] == "complete":
            checks.append(_check(f"coverage:{sleeve}", OK,
                                 f"{st['observed_slots']} of {st['expected_slots']} decided"))
        else:
            checks.append(_check(f"coverage:{sleeve}", FAIL,
                                 f"{st['outcome']}: {st.get('reason', '')}"))

    # ── slot gaps: every registered slot id has a row ────────────────────────
    seen_ids = {str(r.get("slot_id")) for r in rows if r.get("event") == "slot_observed"}
    missing = sorted(s.id for s in ts.TRACK1_SLOTS if s.id not in seen_ids)
    if missing:
        checks.append(_check("slot_gaps", FAIL,
                             f"{len(missing)} registered slot(s) wrote no ledger row",
                             missing=missing[:10]))
    else:
        checks.append(_check("slot_gaps", OK, f"all {len(ts.TRACK1_SLOTS)} slots present"))

    # ── runtime and stalls, from the slots' own telemetry ────────────────────
    trows = _timing_rows(root, day_compact)
    durations = sorted(float(r["runtime_s"]) for r in trows
                       if isinstance(r.get("runtime_s"), (int, float))
                       and r["runtime_s"] > 0)
    if not durations:
        checks.append(_check("runtime_p95", FAIL,
                             "no telemetry with a positive runtime for this day — a shadow "
                             "day without timing evidence cannot be judged fast OR slow"))
    else:
        p95 = durations[max(0, int(0.95 * len(durations)) - 1)]
        if p95 >= RUNTIME_P95_REQUIRED_S:
            checks.append(_check("runtime_p95", FAIL,
                                 f"p95 {p95:.1f}s >= {RUNTIME_P95_REQUIRED_S:.0f}s — slots "
                                 f"overrun the cadence", p95_s=round(p95, 1)))
        elif p95 >= RUNTIME_P95_TARGET_S:
            checks.append(_check("runtime_p95", WARN,
                                 f"p95 {p95:.1f}s under the {RUNTIME_P95_REQUIRED_S:.0f}s "
                                 f"ceiling but over the {RUNTIME_P95_TARGET_S:.0f}s target",
                                 p95_s=round(p95, 1)))
        else:
            checks.append(_check("runtime_p95", OK, f"p95 {p95:.1f}s", p95_s=round(p95, 1)))
        stalled = [r.get("slot_id") for r in trows
                   if isinstance(r.get("runtime_s"), (int, float))
                   and r["runtime_s"] >= RUNTIME_P95_REQUIRED_S]
        if stalled:
            checks.append(_check("stalls", FAIL,
                                 f"{len(stalled)} slot(s) ran >= the 300s cadence",
                                 slots=stalled[:10]))
        else:
            checks.append(_check("stalls", OK, "no slot reached the cadence ceiling"))

    # ── orders: none attempted, and the gate could not have allowed one ──────
    order_marks = [r for r in trows + rows
                   if any("order" in str(k).lower() and bool(r.get(k))
                          for k in r if str(k).lower() not in ("orders_possible",))]
    from global_index import track1_gates as g
    blocking = g.as_ledger().get("blocking_now") or []
    possible, _why = g.may_enable_orders()
    confirmation = (root / CONFIRMATION_PATH).exists()
    # Stage 5ZZZ-A. The two things that ACTUALLY arm an order, checked as themselves.
    #
    # `TRACK1_ORDERS_APPROVED` is the out-of-band approval and the orders directory is where a
    # sent order would leave its journal. Neither is implied by a signature, and the gate
    # registry deliberately does not read the environment — Stage 5ZZS pinned that — so if this
    # check did not look at them, an approved shadow run would pass an audit whose whole subject
    # is whether an order could have been sent.
    approved = bool(_os.environ.get("TRACK1_ORDERS_APPROVED"))
    orders_dir = (root / "global_index" / "track1_runtime" / "orders").exists()

    if order_marks:
        checks.append(_check("no_orders", FAIL,
                             f"{len(order_marks)} record(s) carry an order mark"))
    elif possible or not blocking:
        checks.append(_check("no_orders", FAIL,
                             "no gate blocker is open — an order would not have been refused"))
    elif approved:
        checks.append(_check("no_orders", FAIL,
                             "TRACK1_ORDERS_APPROVED is set during a shadow period"))
    elif orders_dir:
        checks.append(_check("no_orders", FAIL,
                             "an order journal directory exists during a shadow period"))
    elif confirmation:
        # Stage 5ZZZ-A. NOT a failure any more, and the reason is a change in what the file
        # means rather than a relaxation of what the audit demands.
        #
        # When this rule was written, the signature was the last thing between this route and an
        # order, so its presence during a shadow period really did mean the route could send.
        # Stage 5S added a measured evidence gate and Stage 5ZZK gave B1 a measured half of its
        # own; the operator signed on 2026-08-27 and `orders_possible` stayed false throughout.
        # From then on the file records that a DECISION was made, and the question of whether an
        # order could be sent is answered by the gate registry — which is asked directly above.
        #
        # Keeping the old rule would have failed every shadow day from the signature onward, for
        # a condition that is the intended state of the route. An audit that fails on every day
        # is an audit nobody reads by the time a real breach arrives.
        checks.append(_check("no_orders", OK,
                             f"no order marks; B1 confirmation present; orders remain blocked "
                             f"by {', '.join(blocking)}"))
    else:
        checks.append(_check("no_orders", OK,
                             f"no order marks; blocking={blocking}; no confirmation file"))

    # ── freshness proofs on decided slots ────────────────────────────────────
    erows = _explanation_rows(root, day_compact)
    if not erows:
        checks.append(_check("explanations", FAIL, "no explanation rows for this day"))
        checks.append(_check("freshness_proofs", FAIL,
                             "no explanations, so no freshness proofs either"))
    else:
        checks.append(_check("explanations", OK, f"{len(erows)} rows"))
        missing_proof = [r for r in erows
                         if not any("freshness" in str(p.get("name", "")).lower()
                                    for p in (r.get("proofs") or []))
                         and "freshness" not in json.dumps(r).lower()]
        if missing_proof:
            checks.append(_check("freshness_proofs", FAIL,
                                 f"{len(missing_proof)} explanation row(s) carry no "
                                 f"freshness proof"))
        else:
            checks.append(_check("freshness_proofs", OK,
                                 "every row carries a freshness reference"))

    # ── the route checkpoint ─────────────────────────────────────────────────
    checks.append(checkpoint_check(root, day))
    checks.append(_check("checkpoint_identity", NOT_CHECKED,
                         "params-hash acceptance needs the frames; run "
                         "route_checkpoint.usable per sleeve for it — recorded here so a "
                         "green day cannot be read as having verified it"))

    # ── safety wiring, from the same tables the scheduler registers from ─────
    if (ts.TRACK1_POSITIONS_PATH == "live_positions.track1.json"
            and ts.TRACK1_MAXHOLD_STATE.endswith("maxhold_state.track1.json")):
        checks.append(_check("safety_paths", OK,
                             "Track 1 safety watches the route's own book and marker"))
    else:
        checks.append(_check("safety_paths", FAIL,
                             f"safety points at {ts.TRACK1_POSITIONS_PATH} / "
                             f"{ts.TRACK1_MAXHOLD_STATE}"))

    failed = [c["name"] for c in checks if c["status"] == FAIL]
    return {"day": day, "accepted": not failed, "failed": failed, "checks": checks}


#: The three verdicts a LIVE audit can return. `evaluate_day` grades a finished day and
#: answers accepted/not; this is the mid-session question, which needs a third answer.
#: The VERDICT vocabulary, deliberately distinct from the per-check status words above.
#: `FAIL` was very nearly reused for both — it is already the check status `"fail"` at the
#: top of this module — and the rebinding would have silently changed every
#: `c["status"] == FAIL` comparison in `evaluate_day` to compare against `"FAIL"`, which no
#: check ever emits. Every coverage failure would have stopped being seen. Two vocabularies,
#: two names.
NOT_ENOUGH_DATA_YET = "NOT_ENOUGH_DATA_YET"
SHADOW_DAY_PASS = "SHADOW_DAY_PASS"
VERDICT_FAIL = "FAIL"


def windows_status(now_et, scheduler_started_et=None, day=None) -> dict:
    """Per sleeve: has its window closed, and was the scheduler up for ALL of it?

    The distinction is the whole reason this function exists. A window that closed while the
    scheduler was down produced no evidence and cannot be a FAILURE — nothing was asked to
    run. A window that closed with the scheduler up throughout is judgeable. A window the
    scheduler joined halfway is neither: some slots could never have fired, so an incomplete
    coverage row there is expected, and calling it a failure would train an operator to
    ignore the audit.

    Measured on the live box the first time this ran: the scheduler started 04:32 ET and the
    NKD window is 01:10-02:55 ET, so NKD had closed BEFORE the process existed. Empty
    coverage was the correct state, and a naive gate would have called it a failed sleeve.
    """
    import pandas as pd

    from global_index.track1_params import WINDOWS_ET

    now = pd.Timestamp(now_et)
    if now.tzinfo is not None:
        now = now.tz_convert("America/New_York").tz_localize(None)
    started = None
    if scheduler_started_et is not None:
        started = pd.Timestamp(scheduler_started_et)
        if started.tzinfo is not None:
            started = started.tz_convert("America/New_York").tz_localize(None)

    # `day` exists for the AUDIT, which is asked about a specific session day and not always
    # about today's. Without it every window was built on `now`'s date, so auditing yesterday
    # compared yesterday's ledger against today's clock and reported a closed window as still
    # open. Default unchanged: no argument means today, which is what every existing caller
    # passes and what the live mid-session audit means.
    day = now.normalize() if day is None else pd.Timestamp(day).normalize()
    out = {}
    for sleeve, (lo, hi) in WINDOWS_ET.items():
        lo_h, lo_m = (int(x) for x in lo.split(":"))
        hi_h, hi_m = (int(x) for x in hi.split(":"))
        opens = day + pd.Timedelta(hours=lo_h, minutes=lo_m)
        closes = day + pd.Timedelta(hours=hi_h, minutes=hi_m)
        closed = now > closes
        if not closed:
            # Say the FIRST reason it is not judgeable. A window that has not closed yet is
            # pending because the day has not got there — reporting an uptime fact instead
            # answers a question the operator did not ask and reads as if uptime were the
            # problem.
            covered = False
            why = (f"window has not closed yet (closes {closes.time()}, now {now.time()})"
                   if now < closes else "window is open right now")
            out[sleeve] = {"window": [lo, hi], "closed": False, "judgeable": False,
                           "reason": why}
            continue
        if started is None:
            covered = True
            why = "scheduler uptime unknown — treated as judgeable"
        elif started <= opens:
            covered = True
            why = "window closed and the scheduler was up before it opened"
        elif started <= closes:
            covered = False
            why = (f"scheduler started {started.time()} — inside the window, so some slots "
                   f"could never have fired")
        else:
            covered = False
            why = (f"scheduler started {started.time()} — AFTER the window closed at "
                   f"{closes.time()}; no slot was ever due")
        out[sleeve] = {"window": [lo, hi], "closed": bool(closed),
                       "judgeable": bool(closed and covered), "reason": why}
    return out


def audit_now(root: str | Path = ".", now_et=None, scheduler_started_et=None) -> dict:
    """The live, mid-session audit. Read-only. Returns one of the three verdicts.

    `NOT_ENOUGH_DATA_YET` when no window has both closed AND been fully covered by scheduler
    uptime — the state before a shadow day can be judged at all, and the state this returns
    rather than FAIL so that an audit run at 05:00 does not read as a broken route.
    """
    import pandas as pd

    root = Path(root)
    now = pd.Timestamp(now_et) if now_et is not None else         pd.Timestamp.now(tz="America/New_York")
    day = str(pd.Timestamp(now).tz_convert("America/New_York").date()
              if pd.Timestamp(now).tzinfo is not None else pd.Timestamp(now).date())

    wins = windows_status(now, scheduler_started_et)
    judgeable = [s for s, v in wins.items() if v["judgeable"]]

    full = evaluate_day(day, root=root)
    by_name = {c["name"]: c for c in full["checks"]}

    # Only the sleeves whose windows are judgeable can fail on coverage; the rest are
    # reported as pending with the reason, never as failures.
    coverage_fail, coverage_pending = [], []
    for sleeve, v in wins.items():
        c = by_name.get(f"coverage:{sleeve}", {})
        if not v["judgeable"]:
            coverage_pending.append(sleeve)
        elif c.get("status") == FAIL:          # the CHECK status "fail"
            coverage_fail.append(sleeve)

    # Checks that are meaningless before any slot has run are held back the same way.
    evidence_checks = {"slot_gaps", "runtime_p95", "stalls", "explanations",
                       "freshness_proofs", "checkpoint"}
    hard_fail = [n for n, c in by_name.items()
                 if c["status"] == "fail" and n not in evidence_checks
                 and not n.startswith("coverage:")]
    evidence_fail = [n for n in evidence_checks
                     if by_name.get(n, {}).get("status") == "fail"]

    if hard_fail or coverage_fail:
        verdict = VERDICT_FAIL
    elif not judgeable:
        verdict = NOT_ENOUGH_DATA_YET
    elif evidence_fail:
        verdict = VERDICT_FAIL
    else:
        verdict = SHADOW_DAY_PASS

    return {
        "day": day,
        "now_et": str(now),
        "scheduler_started_et": str(scheduler_started_et) if scheduler_started_et else None,
        "verdict": verdict,
        "windows": wins,
        "judgeable_sleeves": judgeable,
        "coverage_pending": sorted(coverage_pending),
        "coverage_failed": sorted(coverage_fail),
        "hard_failures": sorted(hard_fail),
        "evidence_failures_when_judgeable": sorted(evidence_fail) if judgeable else [],
        "checks": full["checks"],
    }



def evaluate_period(days, root: str | Path = ".") -> dict:
    """Every day of a shadow period. Accepted only when every day is."""
    results = [evaluate_day(d, root=root) for d in days]
    return {"days": [r["day"] for r in results],
            "accepted": bool(results) and all(r["accepted"] for r in results),
            "failed_days": [r["day"] for r in results if not r["accepted"]],
            "results": results}


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5Q — the public API a POST-WINDOW audit is built from.
#
# Why this lives here and not in the audit runner
# -----------------------------------------------
# `global_index/track1_shadow_audit.py` schedules, writes and reports. It must not own a
# single acceptance rule, because the moment a second copy of "what counts as complete"
# exists, the two drift and the operator is shown whichever one is looser. So the runner
# calls down into this module for every judgement, and everything below is derived from the
# SAME tables `evaluate_day` already reads: `window_ledger.WINDOWS` for the expected counts,
# `track1_slots.TRACK1_SLOTS` for the ids, `WINDOWS_ET` for the bands, and the two runtime
# constants at the top of this file.
#
# The one thing that is genuinely new here is SCOPE. `evaluate_day` grades a whole finished
# day; an audit fires ten minutes after a single window closes, when three of the four
# sleeves have not run yet and grading them would be inventing failures.
# ══════════════════════════════════════════════════════════════════════════════

#: The AUDIT verdict vocabulary. Four values, and they are deliberately NOT the same names as
#: the per-check statuses (`ok`/`fail`/`warn`) at the top of this module: a check is one
#: question, a verdict is the answer for a whole window or day, and the module docstring
#: already records what happened the one time two vocabularies shared a name.
#:
#: `AUDIT_FAIL` and `AUDIT_NOT_ENOUGH_DATA_YET` are the same STRINGS as `VERDICT_FAIL` and
#: `NOT_ENOUGH_DATA_YET`, so the live mid-session audit and the post-window audit cannot
#: disagree about what "FAIL" is spelled like. A test pins that equality — if someone renames
#: one, the other has to move with it.
AUDIT_PASS = "PASS"
AUDIT_WARN = "WARN"
AUDIT_FAIL = VERDICT_FAIL                    # "FAIL"
AUDIT_NOT_ENOUGH_DATA_YET = NOT_ENOUGH_DATA_YET

#: Severity order, so a roll-up can take the worst of a set without a chain of ifs. FAIL is
#: worst; NOT_ENOUGH_DATA_YET is NOT ranked with them and is handled explicitly — "we cannot
#: tell yet" is not a degree of badness, and folding it into the ladder is how a pending
#: window ends up presented as a mild failure.
_SEVERITY = {AUDIT_PASS: 0, AUDIT_WARN: 1, AUDIT_FAIL: 2}

#: Machine-readable reason codes. The audit record carries these; the prose in `details` is
#: for a human and is never parsed. Two vocabularies on purpose — a dashboard that switches on
#: an English sentence breaks the first time the sentence is improved.
R_WINDOW_NOT_CLOSED = "window_not_closed"
R_CLOSED_BEFORE_SCHEDULER_START = "window_closed_before_scheduler_start"
R_SCHEDULER_JOINED_MIDWAY = "scheduler_joined_window_midway"
R_UPTIME_UNKNOWN_NO_EVIDENCE = "scheduler_uptime_unknown_and_no_evidence"
R_COVERAGE_INCOMPLETE = "coverage_incomplete"
R_COVERAGE_UNOBSERVED = "coverage_unobserved"
R_MISSING_SLOT_IDS = "missing_slot_ids"
R_NO_TIMING = "no_timing_records"
R_P95_OVER_CEILING = "runtime_p95_over_ceiling"
R_P95_OVER_TARGET = "runtime_p95_over_target"
R_SLOT_STALL = "slot_runtime_over_ceiling"
R_EXPLANATIONS_MISSING = "explanations_missing"
R_NO_CANDIDATES_TO_EXPLAIN = "no_candidates_to_explain"
R_MISSING_FRESHNESS_PROOF = "explanation_without_freshness_proof"
R_ORDER_MARK = "order_mark_present"
R_ORDER_GATE_NOT_BLOCKING = "order_gate_not_blocking"
R_CONFIRMATION_FILE = "confirmation_file_present"
R_CHECKPOINT_MISSING = "checkpoint_missing"
R_CHECKPOINT_WRONG_ROUTE = "checkpoint_wrong_route"
R_CHECKPOINT_WRONG_DAY = "checkpoint_wrong_day"
#: Stage 5ZH. Two conditions that used to be forced into `wrong_day` by an `else`, which is
#: how a payload of the wrong SHAPE got reported as a payload of the wrong DAY.
R_CHECKPOINT_UNREADABLE = "checkpoint_unreadable"
R_CHECKPOINT_DAY_UNVERIFIABLE = "checkpoint_day_unverifiable"
#: Stage 5ZK. The book holds something and the checkpoint records nothing to resume it from.
R_CHECKPOINT_ENTRIES_MISSING_FOR_OPEN_BOOK = "checkpoint_entries_missing_for_open_book"
R_CHECKPOINT_BOOK_DISAGREEMENT = "checkpoint_book_disagrees_with_entries"
R_CHECKPOINT_HISTORY_STALE = "checkpoint_history_stale"
#: Stage 5ZO. A slot that DECIDED with no record of what data it looked at.
#:
#: WARN, not FAIL, and the reason is deliberate. The ledger row already proves the slot ran and
#: decided; the observation row proves what it observed. A missing observation weakens the
#: evidence without contradicting it — and making it fatal would fail every window recorded
#: before this stage existed, which is not a finding about those windows.
#:
#: It stops being tolerable the day a paper order is sent on a decision nobody can show the
#: data for; the readiness gate is where that belongs, not here.
R_DECIDED_WITHOUT_DATA_OBSERVATION = "decided_without_data_observation"

#: code -> reason. A mapping, not a chain of substring tests on the detail sentence.
CHECKPOINT_REASON_BY_CODE = {
    CK_MISSING: R_CHECKPOINT_MISSING,
    CK_UNREADABLE: R_CHECKPOINT_UNREADABLE,
    CK_WRONG_ROUTE: R_CHECKPOINT_WRONG_ROUTE,
    CK_WRONG_DAY: R_CHECKPOINT_WRONG_DAY,
    CK_DAY_UNVERIFIABLE: R_CHECKPOINT_DAY_UNVERIFIABLE,
    CK_ENTRIES_MISSING_FOR_OPEN_BOOK: R_CHECKPOINT_ENTRIES_MISSING_FOR_OPEN_BOOK,
    CK_BOOK_DISAGREES_WITH_ENTRIES: R_CHECKPOINT_BOOK_DISAGREEMENT,
    CK_HISTORY_STALE: R_CHECKPOINT_HISTORY_STALE,
}
R_SAFETY_PATHS = "safety_paths_not_track1"
R_ACCEPTANCE_GATE_REFUSED = "daily_acceptance_gate_refused"

#: Stage 5Q-1. Reason codes for the observation classification and the two evidence
#: cross-checks it made possible.
R_HARD_REFUSAL = "slot_could_not_evaluate"
R_ALL_SLOTS_NO_ACTION = "all_slots_observed_no_action"
R_ALL_SLOTS_WINDOW_SHUT = "all_slots_observed_window_shut"
R_DUPLICATE_SLOT_IDS = "duplicate_slot_ids"
R_UNREGISTERED_SLOT_IDS = "unregistered_slot_ids"
R_SLOT_WITHOUT_TIMING = "slot_without_timing"
R_TIMING_WITHOUT_LEDGER_ROW = "timing_without_ledger_row"
R_EXPLANATIONS_OVERWRITTEN = "explanations_overwritten_by_a_later_sleeve"

#: The route every audit record is stamped with. Same constant the runtime reader and the
#: scheduler's child environment use — an audit record that does not say which route it
#: judged is a record that will be read as judging whichever route the reader had in mind.
AUDIT_ROUTE = "track1_candidate"

#: Where audit reports are written. Under the durable runtime root, NOT scratch: an audit is
#: evidence about evidence, and ordinary cleanup of scratch would delete the record of
#: whether a window was ever judged. Beside the evidence, never inside it — the audit reads
#: `window_coverage/`, `slot_timing/` and `shadow/` and must never be able to write there.
AUDITS_DIR = "global_index/track1_runtime/audits"


def sleeve_slot_ids(sleeve: str) -> list:
    """Every registered slot id for one sleeve, in fire order.

    Read from `track1_slots.TRACK1_SLOTS`, which is itself derived from `WINDOWS_ET`, so this
    cannot disagree with what the scheduler registered.
    """
    from global_index import track1_slots as ts
    return [s.id for s in ts.TRACK1_SLOTS if s.sleeve == sleeve]


def _sleeve_of_slot(slot_id: str) -> "str | None":
    from global_index import track1_slots as ts
    for s in ts.TRACK1_SLOTS:
        if s.id == str(slot_id):
            return s.sleeve
    return None


def _p95(durations: list) -> float:
    """The SAME index `evaluate_day` uses. Restating the formula is how two readers of one
    day end up quoting two different p95s."""
    return durations[max(0, int(0.95 * len(durations)) - 1)]


def _worse(a: str, b: str) -> str:
    """The worse of two verdicts on the PASS/WARN/FAIL ladder.

    `NOT_ENOUGH_DATA_YET` is not on the ladder and is never returned from here — it is
    decided before any check runs, because "we cannot tell" is a different axis from "how bad
    is it", and ranking it would let a pending window be printed as a mild failure.
    """
    return a if _SEVERITY.get(a, 0) >= _SEVERITY.get(b, 0) else b


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5Q-1 — what a slot's ledger row actually MEANS.
#
# 5Q counted a window complete when the ledger said so, and the ledger counts only slots that
# DECIDED. That is the right rule for the committed daily gate and the wrong one for an
# operational audit, because two of the ways a slot can end with `decided=False` are the route
# behaving exactly as designed.
#
# Measured on 2026-08-24, by running `observe_live_slot` against a temp tree rather than by
# reading it — the four outcomes and the row each one writes:
#
#     provider=None            decided=False  reason=no_bar_provider
#     gate ok, 0 candidates    decided=TRUE   reason=decided        candidates=0
#     gate refused too_late    decided=False  reason=gate_refused   detail="too_late"
#     gate refused stale       decided=False  reason=gate_refused   detail="stale"
#     live source not ready    decided=False  reason=live_source_not_ready
#
# The first thing that measurement settled is that **"no candidate" was never the problem**:
# a slot that looked and found nothing already records `decided=True` and already counts
# toward coverage. The gap is narrower and it is the CLOCK codes. `track1_intraday` refuses a
# slot `too_early`/`too_late` when the instant sits outside the sleeve's own decision band —
# and that band is not the same as the scheduler's ET slot grid. For NKD the band is the Tokyo
# session, and once US DST ends the late ET slots land after 15:55 JST and are refused by
# design. Those slots ran, looked, and were told the window was shut. Counting them as
# unobserved would make an NKD window permanently incomplete every winter, and an audit that
# fails every winter night is an audit nobody reads.
#
# Everything else that sets `decided=False` is the route being UNABLE to evaluate — no bars,
# no source, stale frame, a gap in coverage, or an admission taken while the daily inputs were
# refused. Those stay failures. The distinction is machine-readable off the row itself,
# because `gate_refused` writes the gate's own codes into `detail`.
# ══════════════════════════════════════════════════════════════════════════════

#: Slot outcome classes. Derived from the row, never from the file's existence.
SLOT_DECISION = "observed_decision"
SLOT_NO_ACTION = "observed_no_action"
SLOT_WINDOW_SHUT = "observed_window_shut"
SLOT_HARD_REFUSAL = "observed_hard_refusal"
SLOT_UNOBSERVED = "unobserved"

#: The three that prove somebody looked. A window is OBSERVATION-complete when every
#: registered slot id landed in one of these — which is a different question from the ledger's
#: `complete`, and both are reported.
OBSERVED_CLASSES = frozenset({SLOT_DECISION, SLOT_NO_ACTION, SLOT_WINDOW_SHUT})


def clock_refusal_codes() -> frozenset:
    """The gate codes that mean "the sleeve's decision band was shut at this instant".

    Read from `track1_intraday`, not restated. If a new clock code is added there and not
    here, this returns the old set and a slot that was correctly refused reads as a hard
    refusal — loud and wrong in the safe direction, rather than quiet and wrong in the
    dangerous one.
    """
    from global_index import track1_intraday as intra
    return frozenset({intra.TOO_EARLY, intra.TOO_LATE})


def classify_slot_row(row) -> str:
    """One `slot_observed` row -> one outcome class. Fails closed.

    `gate_refused` with an EMPTY detail is a hard refusal, not a window-shut: the gate always
    writes its codes, so an empty detail means something wrote a row this function cannot
    read, and guessing in the lenient direction is how a silent failure becomes a pass.
    """
    if not isinstance(row, dict):
        return SLOT_HARD_REFUSAL
    if row.get("decided"):
        cands = row.get("candidates")
        return SLOT_NO_ACTION if not cands else SLOT_DECISION
    if str(row.get("reason")) != "gate_refused":
        return SLOT_HARD_REFUSAL
    codes = [c.strip() for c in str(row.get("detail") or "").split(",") if c.strip()]
    if codes and all(c in clock_refusal_codes() for c in codes):
        return SLOT_WINDOW_SHUT
    return SLOT_HARD_REFUSAL


def window_observation(rows, sleeve: str, day) -> dict:
    """Did every registered slot of this window leave a row, and what did each row say?

    Answers three questions the ledger's own `status` cannot, because it returns one number:

        which registered slot ids are MISSING          a count cannot see a silent slot
                                                       masked by a doubled one
        which slot ids appear TWICE                    named, so a duplicate can never be
                                                       read as compensating for a gap
        what CLASS each row fell into                  observed vs unable-to-evaluate
    """
    import global_index.window_ledger as wl

    day = str(day)
    mine = [r for r in rows
            if r.get("sleeve") == sleeve and str(r.get("date")) == day
            and r.get("event") == wl.SLOT_OBSERVED]
    registered = sleeve_slot_ids(sleeve)

    by_id: dict = {}
    for r in mine:
        by_id.setdefault(str(r.get("slot_id")), []).append(r)

    classes: dict = {}
    counts = {k: 0 for k in (SLOT_DECISION, SLOT_NO_ACTION, SLOT_WINDOW_SHUT,
                             SLOT_HARD_REFUSAL, SLOT_UNOBSERVED)}
    for sid in registered:
        got = by_id.get(sid)
        # The LAST row for a slot id is the one that stands: a slot re-run after a failure
        # ends on its final outcome. The duplicate is still reported by name below.
        cls = classify_slot_row(got[-1]) if got else SLOT_UNOBSERVED
        classes[sid] = cls
        counts[cls] += 1

    return {
        "sleeve": sleeve, "date": day,
        "registered": len(registered),
        "classes": classes,
        "counts": counts,
        "observed": sum(counts[c] for c in OBSERVED_CLASSES),
        "missing_slot_ids": [s for s in registered if classes[s] == SLOT_UNOBSERVED],
        "duplicate_slot_ids": sorted(k for k, v in by_id.items() if len(v) > 1),
        "hard_refusal_slot_ids": [s for s in registered
                                  if classes[s] == SLOT_HARD_REFUSAL],
        "hard_refusal_reasons": sorted({str(by_id[s][-1].get("reason"))
                                        + (":" + str(by_id[s][-1].get("detail"))
                                           if by_id[s][-1].get("reason") == "gate_refused"
                                           else "")
                                        for s in registered
                                        if classes[s] == SLOT_HARD_REFUSAL}),
        "unregistered_slot_ids": sorted(set(by_id) - set(registered)),
    }


def explanation_files(root, day_compact: str) -> list:
    """Every file a Track 1 explanation row for this day could be in.

    **This is a repair, and it is the reason 5Q-1 exists at all.** The gate read

        global_index/track1_runtime/shadow/explanations/explanations_YYYYMMDD.jsonl

    and NOTHING has ever written there. Measured 2026-08-24 by running the real writer into a
    temp tree: `emit_explanations` resolves its destination as
    `<shadow>/explanations/<window>/` — one directory deeper, keyed by the window name
    (`live_YYYY-MM-DD` for a live-shadow slot) — and `write_shadow` is the only caller of that
    path in the repo. So on the first real shadow day the `explanations` and
    `freshness_proofs` checks would both have failed a route that wrote its explanations
    correctly, and the failure would have looked exactly like missing evidence.

    Both shapes are searched. The flat one is kept because it costs nothing and a reader that
    only accepts today's layout is the same brittleness in the other direction.
    """
    from global_index import track1_explain as tx
    # Stage 5Q-2: the layout has ONE owner, and it is the module that writes it. This
    # function keeps its name because the gate and the dashboard both call it, but the shape
    # it looks for is no longer restated here — the version that restated it globbed one
    # directory too shallow and found nothing on any real day.
    return tx.explanation_files(root, day_compact, out_dir=SHADOW_DIR)


def evaluate_sleeve(day, sleeve, root: str | Path = ".", *, now_et=None,
                    scheduler_started_et=None) -> dict:
    """One sleeve's window on one day. Returns one of the four audit verdicts.

    The order of the questions is the point:

    1. **Is it judgeable at all?** A window that has not closed, or that closed before the
       scheduler existed, or that the scheduler joined halfway, returns
       `NOT_ENOUGH_DATA_YET`. It does NOT return PASS — nothing was proved — and it does not
       return FAIL, because nothing was ever asked to run. The NKD window of 2026-08-24 is
       the measured case: it closed at 02:55 ET and the track1-only scheduler started at
       04:32 ET.
    2. **Did every registered slot LOOK?** Stage 5Q-1's question, and it is not the same as
       the ledger's "did every slot decide". A slot that ran and was told by the intraday gate
       that the sleeve's decision band was shut (`too_early`/`too_late`) observed its window
       exactly as designed. A slot that could not get bars, could not build a source, read a
       stale frame, or admitted a candidate while the daily inputs were refused did not — and
       that stays a failure. Both answers are in the record: `observation` is the audit's, and
       `ledger_outcome` is the committed gate's, unchanged.
    3. **Did it leave the evidence?** every slot id present and none doubled in place of a
       missing one; a timing record for every slot that wrote a ledger row AND a ledger row
       for every slot that wrote timing; explanations with freshness proofs.
    4. **Could an order have been sent?** Order marks, the gate registry and the confirmation
       file — checked on every audit regardless of sleeve, because an order mark during a
       shadow period is a failure of the whole route, not of one window.

    Absence is never a default pass. A sleeve with no close record FAILS. A sleeve with no
    timing FAILS. A sleeve with no explanations passes only when the ledger itself records
    that no candidate was ever explained, and that reason is named in the record.
    """
    import pandas as pd

    import global_index.window_ledger as wl

    root = Path(root)
    day = str(pd.Timestamp(day).date())
    day_compact = day.replace("-", "")
    now = (pd.Timestamp(now_et) if now_et is not None
           else pd.Timestamp.now(tz="America/New_York"))

    reasons: list = []
    details: list = []
    notes: list = []

    wins = windows_status(now, scheduler_started_et, day=day)
    w = wins.get(sleeve) or {}
    judgeable = bool(w.get("judgeable"))

    rows = _ledger_rows(root, day)
    mine = [r for r in rows if r.get("sleeve") == sleeve]
    observed_rows = [r for r in mine if r.get("event") == wl.SLOT_OBSERVED]
    st = wl.status(rows, sleeve, day)
    obs = window_observation(rows, sleeve, day)

    # ── Stage 5ZO: the data-observation stream ───────────────────────────────
    #
    # `obs_expected` is what keeps a window recorded BEFORE this stage from being accused of
    # something it could not have done. A day with no observation stream at all is a day whose
    # slots ran under an earlier version of the writer — `pre_observation_schema` — not a day
    # whose slots decided without looking. Once the stream exists for a day, every decided slot
    # in it is expected to appear.
    from global_index import track1_data_observation as dobs

    obs_rows_all, obs_malformed = dobs.read(root=root, day=day)
    obs_rows = [r for r in obs_rows_all if str(r.get("sleeve") or "") == sleeve]
    obs_by_slot = {str(r.get("slot_id") or ""): r for r in obs_rows}
    obs_expected = bool(obs_rows)
    decided_slot_ids = sorted({str(r.get("slot_id") or "")
                               for r in observed_rows if r.get("decided")})
    obs_summary = dobs.summary(obs_rows)

    all_trows = _timing_rows(root, day_compact)
    trows = [r for r in all_trows if _sleeve_of_slot(r.get("slot_id")) == sleeve]
    durations = sorted(float(r["runtime_s"]) for r in trows
                       if isinstance(r.get("runtime_s"), (int, float)) and r["runtime_s"] > 0)
    p95 = round(_p95(durations), 1) if durations else None
    rt_max = round(durations[-1], 1) if durations else None

    ledger_ids = {str(r.get("slot_id")) for r in observed_rows}
    timing_ids = {str(r.get("slot_id")) for r in trows}
    slots_without_timing = sorted(ledger_ids - timing_ids)
    timing_without_row = sorted(timing_ids - ledger_ids)

    erows_all = _explanation_rows(root, day_compact)
    erows = [r for r in erows_all if r.get("sleeve") == sleeve]
    # What the LEDGER says was due, not what the file happens to hold. A slot that saw
    # candidates owed an explanation for each; a slot that saw none owed nothing.
    expected_expl = sum(1 for r in observed_rows
                        if (r.get("candidates") or 0) or (r.get("explained") or 0))
    # Stage 5Q-2. Structural, not a substring over the whole record. The rule lives in the
    # module that BUILDS the records — a row owes a freshness_allow feature exactly when the
    # rules it cites declare one, an accepted admission in a binding mode must cite the gate
    # that governed it, and every decision row must carry the run's freshness verdict as a
    # typed field. What it replaces passed any row containing the word anywhere, including in
    # a sentence, which is the same shape as counting every traceback line with "python" in it
    # as a job launch.
    from global_index import track1_explain as tx
    no_proof = [r for r in erows_all if tx.check_freshness_proof(r)]
    proof_errors = sorted({e for r in erows_all for e in tx.check_freshness_proof(r)})[:5]

    # Day-level facts, taken from the committed gate rather than recomputed here.
    full = evaluate_day(day, root=root)
    by = {c["name"]: c for c in full["checks"]}
    order_check = by.get("no_orders", {})
    ck_check = by.get("checkpoint", {})
    safety_check = by.get("safety_paths", {})

    # ── the order gate: judged on every audit, judgeable window or not ───────
    if order_check.get("status") == FAIL:
        d = str(order_check.get("detail", ""))
        # Stage 5ZZZ-C. The `confirmation file` branch is gone with the check that fed it.
        #
        # Stage 5ZZZ-A removed the FAIL that produced that detail, and left this mapping in
        # place. It was unreachable — no check emits a detail containing those words any more —
        # but "unreachable" is a property of a string nobody is writing today, which is a thin
        # thing to rest on. It also made the reason look live to anything that reads this file
        # to find out which reasons the code can still produce, and Stage 5ZZZ-C has a registry
        # that does exactly that.
        #
        # The two remaining branches are the conditions that actually mean an order could have
        # been sent, plus the approval and order-journal checks the same stage added upstream.
        if "no gate blocker" in d:
            reasons.append(R_ORDER_GATE_NOT_BLOCKING)
        else:
            reasons.append(R_ORDER_MARK)
        details.append("order gate: " + d)
    if safety_check.get("status") == FAIL:
        reasons.append(R_SAFETY_PATHS)
        details.append("safety: " + str(safety_check.get("detail", "")))

    order_blocking_fail = bool(reasons)

    # ── judgeability ─────────────────────────────────────────────────────────
    if not judgeable:
        why = str(w.get("reason", ""))
        if not w.get("closed"):
            code = R_WINDOW_NOT_CLOSED
        elif "AFTER the window closed" in why:
            code = R_CLOSED_BEFORE_SCHEDULER_START
        elif "inside the window" in why:
            code = R_SCHEDULER_JOINED_MIDWAY
        else:
            code = R_WINDOW_NOT_CLOSED
        reasons.append(code)
        details.append(why)

    # A closed window with UNKNOWN scheduler uptime and NO evidence at all cannot be told
    # apart from one that closed before the process existed. Reported as such rather than as
    # a failure — and rather than as a pass, which is the other way to get it wrong.
    uptime_unknown_blind = (judgeable and scheduler_started_et is None
                            and not observed_rows and not trows)
    if uptime_unknown_blind:
        reasons.append(R_UPTIME_UNKNOWN_NO_EVIDENCE)
        details.append("the window has closed and left no evidence at all, and the "
                       "scheduler's start instant could not be read — 'nothing ran' and "
                       "'nothing was asked to run' are not distinguishable here")

    if order_blocking_fail:
        verdict = AUDIT_FAIL
    elif not judgeable or uptime_unknown_blind:
        verdict = AUDIT_NOT_ENOUGH_DATA_YET
    else:
        verdict = AUDIT_PASS

        # ── the window was closed at all ─────────────────────────────────────
        # The ledger's fail-closed rule, kept exactly: no `window_closed` record means
        # nobody can vouch for the window, whatever else is on disk.
        if st["outcome"] == wl.UNOBSERVED:
            reasons.append(R_COVERAGE_UNOBSERVED)
            details.append("coverage: " + str(st.get("reason", "")))
            verdict = AUDIT_FAIL

        # The ledger's own completeness, reported by name whenever it disagrees with the
        # audit's. The two diverge exactly when a slot ran and the sleeve's decision band was
        # shut, and an operator who sees `all_slots_observed_window_shut` beside
        # `coverage_incomplete` can read the whole story: the window WAS observed, and the
        # committed daily gate will not count it. Informational — it does not move the
        # verdict, because the thing it describes is not a gap in the observation.
        elif st["outcome"] != wl.COMPLETE:
            reasons.append(R_COVERAGE_INCOMPLETE)
            details.append("the committed ledger rule counts only slots that DECIDED: "
                           + str(st.get("reason", "")))

        # ── every registered slot LOOKED ─────────────────────────────────────
        if obs["missing_slot_ids"]:
            reasons.append(R_MISSING_SLOT_IDS)
            details.append("%d registered slot(s) wrote no ledger row: %s"
                           % (len(obs["missing_slot_ids"]), obs["missing_slot_ids"][:10]))
            verdict = AUDIT_FAIL
        if obs["duplicate_slot_ids"]:
            # Reported by name so it can never be read as compensating for a gap. The gap
            # itself is already a FAIL above; a duplicate on its own is odd, not a gap.
            reasons.append(R_DUPLICATE_SLOT_IDS)
            details.append("slot id(s) wrote more than one row: %s"
                           % obs["duplicate_slot_ids"][:10])
            verdict = _worse(verdict, AUDIT_WARN)
        if obs["unregistered_slot_ids"]:
            reasons.append(R_UNREGISTERED_SLOT_IDS)
            details.append("row(s) for slot id(s) this sleeve does not register: %s"
                           % obs["unregistered_slot_ids"][:10])
            verdict = _worse(verdict, AUDIT_WARN)

        # ── the slots that looked but could not evaluate ─────────────────────
        if obs["hard_refusal_slot_ids"]:
            reasons.append(R_HARD_REFUSAL)
            details.append("%d slot(s) could not evaluate: %s (%s)"
                           % (len(obs["hard_refusal_slot_ids"]),
                              obs["hard_refusal_slot_ids"][:10],
                              ", ".join(obs["hard_refusal_reasons"][:5])))
            verdict = AUDIT_FAIL

        # ── what the window DID, once it is known to be whole ────────────────
        c = obs["counts"]
        if not obs["missing_slot_ids"] and not obs["hard_refusal_slot_ids"]:
            if c[SLOT_WINDOW_SHUT] == obs["registered"] and obs["registered"]:
                # Every slot ran and every one was told the sleeve's decision band was shut.
                # Legitimate — the NKD ET grid drifts off the Tokyo session every winter —
                # but not silently: a grid that never opens is worth an operator's eye.
                reasons.append(R_ALL_SLOTS_WINDOW_SHUT)
                details.append("every slot ran and the sleeve's decision band was shut at "
                               "each one; for NKD this is the ET grid drifting off the "
                               "Tokyo session, which is legacy's inherited behaviour")
                verdict = _worse(verdict, AUDIT_WARN)
            elif c[SLOT_NO_ACTION] == obs["registered"] and obs["registered"]:
                reasons.append(R_ALL_SLOTS_NO_ACTION)
                details.append("every slot ran, evaluated, and found no candidate — a "
                               "complete observation of a quiet window")

        # ── timing, both directions ──────────────────────────────────────────
        if not durations:
            reasons.append(R_NO_TIMING)
            details.append("no telemetry with a positive runtime for this sleeve — a window "
                           "nobody measured cannot be judged fast OR slow")
            verdict = AUDIT_FAIL
        else:
            if p95 >= RUNTIME_P95_REQUIRED_S:
                reasons.append(R_P95_OVER_CEILING)
                details.append("p95 %.1fs >= %.0fs — slots overrun the cadence"
                               % (p95, RUNTIME_P95_REQUIRED_S))
                verdict = AUDIT_FAIL
            elif p95 >= RUNTIME_P95_TARGET_S:
                reasons.append(R_P95_OVER_TARGET)
                details.append("p95 %.1fs is under the %.0fs ceiling but over the %.0fs "
                               "target" % (p95, RUNTIME_P95_REQUIRED_S,
                                           RUNTIME_P95_TARGET_S))
                verdict = _worse(verdict, AUDIT_WARN)
            stalled = [r.get("slot_id") for r in trows
                       if isinstance(r.get("runtime_s"), (int, float))
                       and r["runtime_s"] >= RUNTIME_P95_REQUIRED_S]
            if stalled:
                reasons.append(R_SLOT_STALL)
                details.append("%d slot(s) ran >= the %.0fs cadence: %s"
                               % (len(stalled), RUNTIME_P95_REQUIRED_S, stalled[:10]))
                verdict = AUDIT_FAIL

        # Both directions, because they are different failures. A slot with a ledger row and
        # no timing ran without being measured; a slot with timing and no ledger row started
        # and never got far enough to say what it saw — a crash, or a mutex skip the parent
        # recorded on the child's behalf. Neither is an observation.
        if slots_without_timing:
            reasons.append(R_SLOT_WITHOUT_TIMING)
            details.append("%d slot(s) wrote a ledger row and no timing record: %s"
                           % (len(slots_without_timing), slots_without_timing[:10]))
            verdict = AUDIT_FAIL
        if timing_without_row:
            reasons.append(R_TIMING_WITHOUT_LEDGER_ROW)
            details.append("%d slot(s) wrote a timing record and no ledger row — started "
                           "and never said what they saw: %s"
                           % (len(timing_without_row), timing_without_row[:10]))
            verdict = AUDIT_FAIL

        # ── explanations and their freshness proofs ──────────────────────────
        #
        # The expectation is DERIVED from the ledger's own counters, not from the presence of
        # a file. A sleeve that saw no candidate has nothing to explain, and requiring rows
        # there would fail a correct quiet day.
        #
        # The third branch is the one that needs saying out loud. Every live slot writes into
        # ONE file per session date — `<shadow>/explanations/live_<date>/explanations_<date>.jsonl`
        # — and `write_shadow` is called with `mode="w"` on every slot, so each slot truncates
        # the last. Measured 2026-08-24: after a second slot wrote, the file held that slot's
        # row and nothing else. So a sleeve's rows can be legitimately absent because a LATER
        # sleeve overwrote them, and that signature — this sleeve has none, other sleeves do —
        # is named rather than failed. It is a defect in the writer, recorded as a blocker,
        # not something the audit may quietly call a gap.
        if expected_expl > 0 and not erows and not erows_all:
            reasons.append(R_EXPLANATIONS_MISSING)
            details.append("%d slot(s) saw candidates and not one explanation row exists "
                           "for the day" % expected_expl)
            verdict = AUDIT_FAIL
        elif expected_expl > 0 and not erows:
            reasons.append(R_EXPLANATIONS_OVERWRITTEN)
            details.append("%d slot(s) saw candidates and this sleeve has no explanation "
                           "row, but %d row(s) from %s do exist — the writer truncates the "
                           "day's file on every slot, so attribution cannot be checked here"
                           % (expected_expl, len(erows_all),
                              sorted({str(r.get("sleeve")) for r in erows_all})))
            notes.append(_check("explanations_attribution", NOT_CHECKED,
                                "the live writer opens the day's explanation file with "
                                "mode='w' on every slot, so only the last slot's rows "
                                "survive; per-candidate attribution is not verifiable until "
                                "that is fixed"))
        elif not erows and observed_rows:
            # `observed_rows` is the guard, and it was added after watching this line print
            # on the live tree for a sleeve whose only slot CRASHED before writing anything.
            # "it observed its window and found nothing to admit" claims something about a
            # slot that never reported at all — true-sounding, and about the wrong thing. A
            # sleeve with no rows fails on coverage above and needs no sentence here.
            reasons.append(R_NO_CANDIDATES_TO_EXPLAIN)
            details.append("no explanation rows for this sleeve, and the ledger records no "
                           "candidate for it — it observed its window and found nothing to "
                           "admit")
        if no_proof:
            reasons.append(R_MISSING_FRESHNESS_PROOF)
            details.append("%d explanation row(s) fail the structured freshness check: %s"
                           % (len(no_proof), proof_errors))
            verdict = AUDIT_FAIL

        # ── Stage 5ZO: did every slot that decided prove what it looked at? ──
        if obs_rows or obs_expected:
            missing = sorted(set(decided_slot_ids) - set(obs_by_slot))
            if missing:
                reasons.append(R_DECIDED_WITHOUT_DATA_OBSERVATION)
                details.append(
                    "%d slot(s) decided with no record of the data they observed: %s%s"
                    % (len(missing), missing[:8], " ..." if len(missing) > 8 else ""))
                verdict = _worse(verdict, AUDIT_WARN)

        # ── the route checkpoint, expected once the window completed ─────────
        if st["outcome"] == wl.COMPLETE and ck_check.get("status") == FAIL:
            reasons.append(CHECKPOINT_REASON_BY_CODE.get(
                ck_check.get("code"), R_CHECKPOINT_WRONG_DAY))
            details.append("checkpoint: " + str(ck_check.get("detail", "")))
            verdict = AUDIT_FAIL

    return {
        "route": AUDIT_ROUTE,
        "date": day,
        "session_day": day,
        "scope": "sleeve",
        "sleeve": sleeve,
        "window_et": list(w.get("window") or []),
        "verdict": verdict,
        "reasons": reasons,
        "details": details,
        "notes": notes,
        "judgeable": judgeable,
        "judgeability_reason": str(w.get("reason", "")),
        "window_closed": bool(w.get("closed")),
        "scheduler_started_et": (str(scheduler_started_et)
                                 if scheduler_started_et is not None else None),
        "expected_slots": st.get("expected_slots"),
        "observed_slots": st.get("observed_slots"),
        # Stage 5Q-1. The audit's own completeness question, beside the ledger's. They differ
        # exactly when a slot ran and the sleeve's decision band was shut, and printing both
        # is what stops either from being mistaken for the other.
        "observation": {
            "registered": obs["registered"],
            "observed": obs["observed"],
            "counts": obs["counts"],
            "hard_refusal_slot_ids": obs["hard_refusal_slot_ids"],
            "hard_refusal_reasons": obs["hard_refusal_reasons"],
            "duplicate_slot_ids": obs["duplicate_slot_ids"],
            "unregistered_slot_ids": obs["unregistered_slot_ids"],
        },
        "ledger_outcome": st.get("outcome"),
        "slots_with_ledger_row": len(observed_rows),
        "registered_slots": obs["registered"],
        "missing_slot_ids": obs["missing_slot_ids"],
        "coverage_outcome": st.get("outcome"),
        "coverage_signal": st.get("signal"),
        "timing_records": len(trows),
        "slots_without_timing": slots_without_timing,
        "timing_without_ledger_row": timing_without_row,
        "runtime_p95_s": p95,
        "runtime_max_s": rt_max,
        "explanations": {"rows": len(erows), "rows_for_day": len(erows_all),
                         "expected_from_ledger": expected_expl,
                         "without_freshness_proof": len(no_proof)},
        # Stage 5ZO. `schema_state` is the part that matters for old windows: absent means
        # the slots ran before the writer existed, which is a fact about the software rather
        # than about the window.
        "data_observation": {
            "schema_state": ("present" if obs_expected else dobs.PRE_SCHEMA),
            "records": obs_summary["records"],
            "malformed_lines": len(obs_malformed),
            "decided_slots": len(decided_slot_ids),
            "slots_without_data_observation": sorted(
                set(decided_slot_ids) - set(obs_by_slot)) if obs_expected else [],
            "providers": obs_summary["providers"],
            "refusals_by_reason": obs_summary["refusals_by_reason"],
            "splice_results": obs_summary["splice_results"],
            "live_rows_fetched_total": obs_summary["live_rows_fetched_total"],
        },
        "checkpoint": {"status": ck_check.get("status"),
                       "detail": ck_check.get("detail", ""),
                       "code": ck_check.get("code"),
                       "expected": st.get("outcome") == wl.COMPLETE},
        "order_gate": {"status": order_check.get("status"),
                       "detail": order_check.get("detail", "")},
        "safety": {"status": safety_check.get("status")},
    }


def evaluate_day_audit(day, root: str | Path = ".", *, now_et=None,
                       scheduler_started_et=None) -> dict:
    """The whole day: every sleeve audited, plus the committed daily gate, side by side.

    Two answers, deliberately not merged into one:

        `verdict`          the OPERATIONAL roll-up. Sleeves whose windows are pending or were
                           never asked to run do not drag it down; a real gap in a judgeable
                           window does.
        `acceptance_gate`  `evaluate_day`'s verdict, verbatim. That gate is stricter — among
                           other things it requires explanation rows for the DAY, so a session
                           in which every sleeve legitimately found no candidate does not
                           satisfy it. It is reported unchanged rather than softened, because
                           it is the gate the shadow PERIOD is judged by and an audit that
                           quietly relaxed it would be grading its own homework.
    """
    import pandas as pd

    from global_index.track1_params import WINDOWS_ET

    root = Path(root)
    day = str(pd.Timestamp(day).date())
    sleeves = sorted(WINDOWS_ET)
    per = {s: evaluate_sleeve(day, s, root, now_et=now_et,
                              scheduler_started_et=scheduler_started_et) for s in sleeves}

    judged = [v for v in per.values() if v["verdict"] != AUDIT_NOT_ENOUGH_DATA_YET]
    reasons: list = []
    notes: list = []
    for v in per.values():
        reasons.extend(v["reasons"])
        notes.extend(v.get("notes") or [])

    # Reported, never enforced here. `evaluate_day` counts a window complete only when every
    # slot DECIDED, so a day on which one sleeve legitimately spent its whole window with its
    # decision band shut does not satisfy it. Stage 5Q-1's rule is that such a day must not be
    # a FAIL — the sleeve verdicts decide, and the committed gate rides along by name so that
    # nobody can read a green audit as having satisfied it.
    full = evaluate_day(day, root=root)
    if not full["accepted"]:
        reasons.append(R_ACCEPTANCE_GATE_REFUSED)

    if not judged:
        verdict = AUDIT_NOT_ENOUGH_DATA_YET
    else:
        verdict = AUDIT_PASS
        for v in judged:
            verdict = _worse(verdict, v["verdict"])

    return {
        "route": AUDIT_ROUTE,
        "date": day,
        "session_day": day,
        "scope": "day",
        "sleeve": None,
        "verdict": verdict,
        "reasons": sorted(set(reasons)),
        "notes": notes,
        "scheduler_started_et": (str(scheduler_started_et)
                                 if scheduler_started_et is not None else None),
        "sleeves": {s: {"verdict": v["verdict"], "reasons": v["reasons"],
                        "expected_slots": v["expected_slots"],
                        "observed_slots": v["observed_slots"],
                        "observation": v["observation"],
                        "ledger_outcome": v["ledger_outcome"],
                        "missing_slot_ids": v["missing_slot_ids"],
                        "runtime_p95_s": v["runtime_p95_s"],
                        "runtime_max_s": v["runtime_max_s"],
                        "coverage_outcome": v["coverage_outcome"],
                        "explanations": v["explanations"],
                        "judgeable": v["judgeable"],
                        "judgeability_reason": v["judgeability_reason"]}
                    for s, v in per.items()},
        "pending_sleeves": sorted(s for s, v in per.items()
                                  if v["verdict"] == AUDIT_NOT_ENOUGH_DATA_YET),
        "acceptance_gate": {"accepted": full["accepted"], "failed": full["failed"]},
        "checkpoint": per[sleeves[0]]["checkpoint"] if sleeves else {},
        "order_gate": per[sleeves[0]]["order_gate"] if sleeves else {},
    }
