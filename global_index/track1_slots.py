"""global_index/track1_slots.py — Track 1's slot table, and the legacy parity check.

Stage 3B. Declarative and offline. **Registering none of these with a scheduler is the
point**: this file says what the slots WOULD be, and a test says the legacy schedule and its
dashboard mirror still agree. Nothing here starts anything.

The defect this exists for
---------------------------
`monitor/backend/schedule_status.py` keeps a HAND-WRITTEN copy of the scheduler's slot table —
R4 slots, NKD slots, the fixed pipeline jobs, the stop-repair sweeps and the Sunday reopen.
Its own comment says what happens when a slot is added to one file and not the other: the
dashboard "coi no la slot la va dung incident gia moi tuan" — treats it as an unknown slot and
manufactures a fake incident every week.

Two copies of a schedule is a schedule that will drift. It has not drifted yet, and
`parity_report()` below is what will notice when it does — for LEGACY today, and for Track 1
the moment its slots are added to both.

Why Track 1's slots cannot simply be added
-------------------------------------------
`run_scheduler.py:672` carries an invariant: no slot may call `run_live_day` between 10:20 and
14:05 ET, because the legacy signal layer never marks the stress cluster unchanged and
`diff_desired_vs_held` closes a stress position on the next run. Track 1's windows land inside
that band — which is safe only because Track 1 has its own entry point and never calls
`run_live_day`.

But one legacy job DOES land inside the Stress window: `STOP_REPAIR_1220`. It builds a runner
and runs B3-B5, and inside an entry window that is an extra chance to halt entries on a false
mismatch. `_ENTRY_WINDOWS` is what excludes such sweeps, and it would need `((10,35),(12,30))`
added. That edit is NOT made here — it changes what a running production process does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from global_index.track1_params import ROUTE, WINDOWS_ET


#: The bar provider a slot's child process is launched with. Stage 5M-B made this per-slot
#: rather than one constant for the whole route, and the reason is a staging decision rather
#: than a preference: Calm and Stress have been wired to `ibkr` since Stage 5I and changing
#: them here would alter production behaviour in a stage whose whole point is that it does
#: not. The new swing slots start at `none`, which means every one of them refuses by name,
#: writes a ledger row, and costs one short-lived process — which is how the runtime and the
#: collision behaviour against the legacy 14:05-15:55 slots get MEASURED in 5M-C instead of
#: estimated. Legacy's own runs take a median 194s of a 300s slot and a measured maximum of
#: 291s, so the headroom for a second child every minute is real but thin, and nobody has
#: measured what the swing slot costs because no Track 1 slot has ever run in production.
PROVIDER_IBKR = "ibkr"
PROVIDER_NONE = "none"
PROVIDERS = (PROVIDER_NONE, PROVIDER_IBKR)

#: The env var that turns the Normal-R4 slots' provider on for a measured session. Stage 5M-C.
#:
#: Unset means `none`, which is what the slot table declares. Set it to `ibkr` and the 23 swing
#: slots connect like Calm and Stress do. It is deliberately an operator action per session
#: rather than an edit to the table, because switching it on is the first time ANY Track 1 slot
#: has shared a minute with a legacy entry slot, and that is a thing to do on purpose.
#:
#: Why not simply flip the table now that legacy will be frozen: because freezing legacy does
#: not stop legacy from running. `STOP_TRADING` halts NEW ENTRIES — `runner.run_day` checks it
#: and skips entries — but the slot has already spawned a child, connected on IBKR clientId 1
#: and gone on to fetch bars for every instrument, roll contracts and run the exit and
#: reconcile checks. So the load the swing slots would land beside is very nearly unchanged by
#: the freeze; only the trading is gone. The collision question is still open and still
#: unmeasured, which is exactly what this switch exists to let someone measure.
SWING_PROVIDER_ENV = "RAITS_TRACK1_SWING_PROVIDER"


def swing_provider(*, track1_only: bool = False) -> str:
    """The provider the Normal-R4 slots should use right now.

    The DEFAULT depends on the scheduler mode, and that is the Stage 5M-D change:

        legacy-compatible shadow   `none` — legacy still has a child in every 14:05-15:55
                                   minute, connected and fetching, and the cost of a second
                                   one there has never been measured.
        track1-only shadow         `ibkr` — those legacy jobs are not scheduled at all, so the
                                   collision that kept the provider staged does not exist.

    The env var remains an override in BOTH directions: set it to `none` to run a Track 1-only
    session without a provider, or to `ibkr` to run a legacy-compatible one with it.

    An unrecognised value RAISES rather than falling back. Falling back would be the
    safer-looking choice and the worse one: an operator who typed `IBKR` or `ibkr ` would get a
    session that silently did nothing, conclude the switch does not work, and have no way to
    tell that from a session where the slots ran and found nothing. Refusing at scheduler build
    time is loud, and it fails in the direction of not starting.
    """
    import os
    raw = os.environ.get(SWING_PROVIDER_ENV)
    if raw is None or raw == "":
        return PROVIDER_IBKR if track1_only else PROVIDER_NONE
    if raw not in PROVIDERS:
        raise ValueError(
            f"{SWING_PROVIDER_ENV}={raw!r} is not one of {PROVIDERS}. Unset it to take the "
            f"mode's default, or set it to one of those two to override.")
    return raw


def provider_for(slot: "Slot", *, track1_only: bool = False) -> str:
    """The effective `--bar-provider` for one slot.

    Calm and Stress carry `ibkr` in the table and are NOT overridable here — they have been
    running that way since Stage 5I and a session-scoped env var must not be able to turn them
    off by accident, or a shadow day would quietly collect nothing.
    """
    if slot.sleeve in STAGED_SLEEVES:
        return swing_provider(track1_only=track1_only)
    return slot.provider


#: Sleeves whose provider is staged by scheduler MODE rather than fixed in the table.
#: Both share the same reason: their slots land on minutes the LEGACY schedule also occupies
#: (swing 14:05-15:55 beside live_day, NKD 01:10-02:55 beside nkd_night), so in the
#: transitional mode they run without a provider and in track1-only — where those legacy jobs
#: are not scheduled — they default to ibkr. The env var keeps its historical SWING name; it
#: now governs both staged sleeves, and renaming it would break the runbook command an
#: operator may already have saved.
STAGED_SLEEVES = frozenset({"roska4_swing", "global_nkd"})


@dataclass(frozen=True)
class Slot:
    id: str
    hour: int
    minute: int
    sleeve: str
    kind: str          # "one_shot" | "window" | "state"
    note: str = ""
    #: what `--bar-provider` this slot's child is launched with
    provider: str = PROVIDER_IBKR
    #: Stage 5ZX. Which half of a split sleeve's evidence this slot produces, or "" for a slot
    #: that is not split. Only Calm is split today, and only because its decision and its entry
    #: price are half an hour apart: the rule is fixed by 09:31 and the price it transacts at
    #: is the 10:00 OPEN, readable from a closed bar at 10:01. One slot spanning both would
    #: hold a process and a client id across the entry instant and could not report which half
    #: failed.
    phase: str = ""


#: Stage 5ZX. The two Calm phases, in the terms `track1_calm_a.CalmExecutionContract` declares.
#: They are written out rather than derived from the window, because the window's low bound is
#: the ENTRY instant and neither phase runs at it: one runs before, one after.
CALM_DECIDE_AT = (9, 32)
CALM_OBSERVE_AT = (10, 2)


def _calm_slots() -> list:
    """Two phases, replacing the single 10:00 slot that could never pass its own gate.

    The old slot fired at the entry instant and needed a CLOSED 10:00 five-minute bar, which
    first exists at 10:05 — four minutes after its own deadline (Stage 5ZU). Splitting it is
    not a workaround for that: the decision genuinely is fixed by 09:31 and the price genuinely
    is not readable until 10:01, and one slot cannot be in both places.

    The entry reference does not move. It is still the 10:00 OPEN.
    """
    dh, dm = CALM_DECIDE_AT
    oh, om = CALM_OBSERVE_AT
    return [
        Slot(f"TRACK1_CALM_DECIDE_{dh:02d}{dm:02d}", dh, dm, "roska4_calm", "one_shot",
             "decides from bars closed by 09:30; records intent, never a price",
             phase="DECIDE"),
        Slot(f"TRACK1_CALM_OBSERVE_{oh:02d}{om:02d}", oh, om, "roska4_calm", "one_shot",
             "records the 10:00 OPEN and the stop level; entry is NOT taken late",
             phase="OBSERVE"),
    ]


def _stress_slots() -> list:
    lo, hi = WINDOWS_ET["roska4_stress"]
    lo_h, lo_m = (int(x) for x in lo.split(":"))
    hi_h, hi_m = (int(x) for x in hi.split(":"))
    out = []
    t = lo_h * 60 + lo_m
    end = hi_h * 60 + hi_m
    while t <= end:
        h, m = divmod(t, 60)
        out.append(Slot(f"TRACK1_STRESS_{h:02d}{m:02d}", h, m, "roska4_stress", "window",
                        "a missed slot inside the window costs nothing; after 12:30 there "
                        "is no entry at any price"))
        t += 5
    return out


def _swing_slots() -> list:
    """Normal-R4, 14:05-15:55, every five minutes. Stage 5M-B.

    Derived from `WINDOWS_ET` like the others, so the 23 slots, the admission gate's decision
    span and the ledger's `expected_slots` cannot drift apart.

    They mirror the legacy entry minutes EXACTLY. That is deliberate and it is the expensive
    choice: two children now run in the same minute. An offset would have been cheaper
    operationally and would also have made the evidence worthless, because the measured rule
    takes the FIRST admitted signal after the 14:00 resume bar — move the slot and a different
    bar wins.
    """
    lo, hi = WINDOWS_ET["roska4_swing"]
    lo_h, lo_m = (int(x) for x in lo.split(":"))
    hi_h, hi_m = (int(x) for x in hi.split(":"))
    out = []
    t = lo_h * 60 + lo_m
    end = hi_h * 60 + hi_m
    while t <= end:
        h, m = divmod(t, 60)
        out.append(Slot(f"TRACK1_SWING_{h:02d}{m:02d}", h, m, "roska4_swing", "window",
                        "the first admitted signal in the window wins; a missed slot costs "
                        "nothing unless the signal was in it",
                        provider=PROVIDER_NONE))
        t += 5
    return out


def _nkd_slots() -> list:
    """MNKD, 01:10-02:55 ET, every five minutes. Stage 5N — the fourth and last sleeve.

    22 slots, mirroring the legacy `nkd_night_*` cadence exactly, for the same reason the
    swing slots mirror `live_day`: the rule takes the FIRST admitted signal in its session
    window, so the slot grid is part of what was measured. The sleeve decides on the Tokyo
    clock; the ET times here are the scheduler's, and the DST drift between the two is
    legacy's own (see WINDOWS_ET).
    """
    lo, hi = WINDOWS_ET["global_nkd"]
    lo_h, lo_m = (int(x) for x in lo.split(":"))
    hi_h, hi_m = (int(x) for x in hi.split(":"))
    out = []
    t = lo_h * 60 + lo_m
    end = hi_h * 60 + hi_m
    while t <= end:
        h, m = divmod(t, 60)
        out.append(Slot(f"TRACK1_NKD_{h:02d}{m:02d}", h, m, "global_nkd", "window",
                        "the first admitted signal in the Tokyo session window wins; a "
                        "missed slot costs nothing unless the signal was in it",
                        provider=PROVIDER_NONE))
        t += 5
    return out


#: Every Track 1 slot, derived from the SAME window table the admission gate and the window
#: ledger read. Derived rather than written out, so a window change moves all three together.
TRACK1_SLOTS: tuple = tuple(_calm_slots() + _stress_slots() + _swing_slots() + _nkd_slots())

#: What `run_scheduler._ENTRY_WINDOWS` would need for the stop-repair sweeps to stay out of
#: the Stress window. Declared, not applied.
REQUIRED_ENTRY_WINDOW: tuple = ((10, 35), (12, 30))

#: Every Track 1 entry window a stop-repair sweep must stay out of, Stage 5M-B. The swing
#: window needs NO new exclusion and this entry says so explicitly rather than by silence:
#: the sweeps run every two hours at :20, and hour 14 is ALREADY excluded because it is the
#: legacy R4 entry window. The window ends at 15:55 and the next sweep is 16:20, outside it.
#: Measured, not assumed — `schedule_status._stop_repair_slots()` returns
#: (0,20) (4,20) (6,20) (8,20) (10,20) (16,20) (18,20) (20,20) (22,20) with the flag on.
REQUIRED_ENTRY_WINDOWS: dict = {
    "roska4_stress": ((10, 35), (12, 30)),
    "roska4_swing": ((14, 5), (15, 55)),
    # Stage 5N. Needs no new stop-repair exclusion either: hour 2 is already excluded because
    # it is the legacy NKD window, and the 01:10-02:55 band contains no other sweep minute.
    "global_nkd": ((1, 10), (2, 55)),
}

# ── Stage 5O: Track 1's own safety net ──────────────────────────────────────────────────
#
# Until this stage the ONLY safety sweeps in any mode were legacy's, and both were hard-wired
# to `live_positions.json` — the 2026-08-23 audit's blocker L3 and the one dependency the
# 5M-D removability probe measured and refused to accept. A Track 1 position would have had
# no stop repair and no five-day exit.
#
# The Track 1 jobs mirror the legacy safety SHAPE — max-hold at 09:31 (the backtest exits
# MAX_HOLD at the 09:30 bar and legacy's 09:31 convention is what every recorded number was
# produced under; moving it would be a semantics change dressed as plumbing), stop-repair
# sweeps every two hours at :20 with a Sunday-reopen sweep at 18:30 — but every path is the
# route's own:
#
#     positions   live_positions.track1.json     never legacy's book
#     kill switch STOP_TRADING.track1            never the root switch
#     lock        runner.track1.pid              never runner.pid — in track1-only mode the
#                                                LEGACY safety jobs stay registered to drain
#                                                legacy's open positions, so both sets fire
#                                                on the same minutes and must not contend
#     client id   90                             legacy safety dials 1, Track 1 data slots
#                                                dial 89; a sweep firing while the 10:00 Calm
#                                                slot still holds 89 must not collide with it
#     maxhold marker  global_index/maxhold_state.track1.json — the shared marker was the
#                     silent failure the audit named: one file, two routes, and the second
#                     route reads a marker it did not write, concludes the sweep already ran,
#                     and skips it. Positions past the five-day limit stay open.
TRACK1_SAFETY_CLIENT_ID = 90
TRACK1_POSITIONS_PATH = "live_positions.track1.json"
#: The envelope version of the book at that path. It lives here, beside the path, because
#: three modules need to agree on it and none of them may import the others: the route writes
#: the book, the paper executor reconciles against it, and the safety guard refuses a book
#: whose envelope does not match. Stage 5ZS — before this the schema was declared only inside
#: the executor, so the route's own carry-forward had no number to check against and accepted
#: a legacy schema-1 book written over it in silence.
TRACK1_BOOK_SCHEMA = 2
#: The route tag every Track 1 book, trade row and ledger row carries.
TRACK1_ROUTE = "track1_candidate"
TRACK1_STOP_PATH = "STOP_TRADING.track1"
TRACK1_LOCK_PATH = "runner.track1.pid"
TRACK1_MAXHOLD_STATE = "global_index/maxhold_state.track1.json"
#     trade log      global_index/track1_runtime/trade_log.track1.jsonl — Stage 5ZG. Sixth
#                    and last of the per-route files, and the one that was missing: both
#                    safety jobs read Track 1's book and wrote the LEGACY log, so a Track 1
#                    close would have landed in the file `paper_evidence_reader` aggregates
#                    whole. Under the Track 1 runtime root rather than beside
#                    `trade_log.jsonl` at the repository root, because every other thing
#                    this route produces already lives there and the readers that will
#                    consume it are being written against that root. This constant is the
#                    single place the path is named; the scheduler passes it, the two entry
#                    points accept it, and no reader may hardcode it.
TRACK1_TRADE_LOG_PATH = "global_index/track1_runtime/trade_log.track1.jsonl"


@dataclass(frozen=True)
class SafetyJob:
    id: str
    hour: int
    minute: int
    kind: str            # "maxhold" | "stop_repair"
    day_of_week: str = "mon-fri"


def _track1_sweep_hours() -> list:
    """Sweep hours, derived from Track 1's OWN entry windows.

    The same rule legacy applies to its windows: a sweep runs B3-B5 checks that can falsely
    halt entries, so no sweep may land inside an entry window. Derived rather than listed —
    a new window moves the sweeps with it. (Today this yields the same nine hours legacy
    keeps when the Stress exclusion is live: 2:20 falls inside the NKD band, 12:20 inside
    Stress, 14:20 inside the swing window.)
    """
    out = []
    for h in range(0, 24, 2):
        inside = any(lo <= (h, 20) <= hi for lo, hi in REQUIRED_ENTRY_WINDOWS.values())
        if not inside:
            out.append(h)
    return out


def track1_safety_jobs() -> tuple:
    """The Track 1 safety schedule, one table for the scheduler AND the dashboard mirror.

    Registered only in track1-only mode. In the transitional mode legacy's safety already
    watches the only book that can hold positions (Track 1 places no orders), and adding a
    second connected child per sweep minute there would be load without a book to protect.
    """
    jobs = [SafetyJob("track1_maxhold_exit", 9, 31, "maxhold")]
    jobs += [SafetyJob(f"track1_stop_repair_{h:02d}20", h, 20, "stop_repair")
             for h in _track1_sweep_hours()]
    jobs.append(SafetyJob("track1_stop_repair_sun_1830", 18, 30, "stop_repair",
                          day_of_week="sun"))
    return tuple(jobs)


#: The route field every Track 1 event and trade row must carry once wiring is approved.
#: `runner_event_reader` passes unknown keys through untouched, so this is additive for the
#: dashboard; `paper_evidence_reader` aggregates the whole trade log and does NOT split on
#: anything, so sharing trade_log.jsonl without teaching it this key would fold Track 1 rows
#: into legacy's fill-quality and P&L gates.
EVENT_ROUTE_FIELD = "route"
EVENT_ROUTE_VALUE = ROUTE
PAPER_OUTPUT_POLICY = {
    "runner_events": "shared file, add a route field — readers tolerate unknown keys",
    # Stage 5ZG: done. The separate file exists and both safety jobs write it, tagged.
    # The tag is carried from day one even though nothing splits on it yet — a row is
    # written once and read for years, and a reader taught to split later cannot go back
    # and label rows that were written untagged.
    "trade_log": f"SEPARATE file {TRACK1_TRADE_LOG_PATH}, rows tagged {EVENT_ROUTE_FIELD}"
                 f"={EVENT_ROUTE_VALUE}; paper_evidence_reader still does not split on it",
    "live_state": "separate route-scoped file; the dashboard shows one system today",
    "slot_timing": "shared file, already carries route",
    "window_coverage": "shared file, already carries route",
}


# ── Stage 5Q: the post-window audit jobs ────────────────────────────────────────────────
#
# The shadow period produces evidence every day, and until this stage the only thing that
# ever READ that evidence was a dated script somebody ran by hand. The morning nobody looked
# was a morning with no record of whether the night had been judged — and "no record" is the
# exact failure the window ledger exists to make impossible for slots. It should not be
# possible for the audit either.
#
# Times are DERIVED from the same `WINDOWS_ET` the slots come from, so moving a window moves
# its audit with it. The buffer is not a taste: the last slot of a window fires AT the close
# minute and may legitimately run to the 300 s cadence ceiling the acceptance gate enforces,
# so close + 5 min is the earliest the window can be guaranteed finished writing. The other
# five minutes are margin, and they are what keeps the audit from reading a half-written
# window and calling a slot silent that was still running.
#
# These jobs are registered in track1-only shadow mode ONLY. They connect to nothing, send
# nothing and spawn `global_index.track1_shadow_audit`, which reads the runtime evidence and
# appends one record per sleeve. No `--allow-orders`, no `--bar-provider`, no broker import
# anywhere on that path.
AUDIT_BUFFER_MINUTES = 10


@dataclass(frozen=True)
class AuditJob:
    id: str
    hour: int
    minute: int
    scope: str           # "sleeve" | "day"
    sleeve: str = ""
    day_of_week: str = "mon-fri"
    note: str = ""


def _audit_minute(close_et: str) -> tuple:
    h, m = (int(x) for x in close_et.split(":"))
    t = (h * 60 + m + AUDIT_BUFFER_MINUTES) % (24 * 60)
    return divmod(t, 60)


def track1_audit_jobs() -> tuple:
    """One audit job per sleeve, fired after that sleeve's window closes, plus a daily
    roll-up after the last of them.

    One table, two readers — the scheduler registers from it and the dashboard mirror
    expects from it — for the same reason the safety table is shared: two lists drift, and
    the drift shows up as a phantom overdue row on the operator's screen.
    """
    jobs = []
    for sleeve in sorted(WINDOWS_ET):
        _lo, hi = WINDOWS_ET[sleeve]
        h, m = _audit_minute(hi)
        jobs.append(AuditJob(f"track1_audit_{sleeve}", h, m, "sleeve", sleeve=sleeve,
                             note=f"audits the {sleeve} window ({hi} ET close) "
                                  f"{AUDIT_BUFFER_MINUTES} minutes after it closes"))
    # The day roll-up goes after the LAST sleeve audit, computed rather than written down:
    # the latest close today is Normal-R4 at 15:55, but nothing here depends on that staying
    # true.
    last = max(j.hour * 60 + j.minute for j in jobs)
    h, m = divmod((last + AUDIT_BUFFER_MINUTES) % (24 * 60), 60)
    jobs.append(AuditJob("track1_audit_daily", h, m, "day",
                         note="rolls the four sleeve verdicts into one day verdict and "
                              "records the committed daily acceptance gate beside it"))
    return tuple(jobs)


def audit_job_argv(job: "AuditJob", *, scheduler_started_et: str = "") -> list:
    """The exact argv one audit job spawns. Built HERE so the scheduler and the tests that
    prove no order flag can reach it read the same construction.

    What is deliberately absent, and stays absent: `--allow-orders`, `--bar-provider`,
    `--port`, `--window`. An audit reads files. It has no reason to know a broker exists, and
    an argv that could name one is one edit away from a path that does.
    """
    import sys as _sys
    argv = [_sys.executable, "-m", "global_index.track1_shadow_audit"]
    if job.scope == "sleeve":
        argv += ["--latest", "--sleeve", job.sleeve]
    else:
        argv += ["--latest", "--all"]
    if scheduler_started_et:
        argv += ["--scheduler-started", scheduler_started_et]
    return argv


def scheduler_slot_ids(port: int = 4002, *, track1_shadow: bool = False,
                       track1_only: bool = False) -> set:
    """Job ids the LEGACY scheduler actually registers, read from the scheduler itself.

    Builds a scheduler object and enumerates it. It is never started, and `dry_run=True`
    means even a fired job would execute nothing — but nothing is fired, because `.start()`
    is not called.
    """
    import logging
    import os
    prev = os.environ.get("PYTEST_CURRENT_TEST")
    os.environ.setdefault("PYTEST_CURRENT_TEST", "track1_slots-parity")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from global_index import run_scheduler as rs
        sched = rs.make_scheduler(port=port, dry_run=True, track1_shadow=track1_shadow,
                                  track1_only=track1_only)
        return {j.id for j in sched.get_jobs()}
    finally:
        logging.disable(lvl)
        if prev is None:
            os.environ.pop("PYTEST_CURRENT_TEST", None)


def legacy_scheduler_slot_ids(port: int = 4002) -> set:
    """Kept as the name the Stage 3B tests use. Legacy = Track 1 off."""
    return scheduler_slot_ids(port, track1_shadow=False)


def dashboard_mirror_slot_ids(day=None) -> set:
    """Slot ids the dashboard's hand-written mirror expects for a trading day."""
    import datetime as dt

    from monitor.backend import schedule_status as ss
    d = day or _first_weekday()
    ids = {s["id"] for s in ss._scheduled_slots_for(d)}
    # The Sunday sweep only appears on a Sunday, so ask for one too.
    sunday = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    ids |= {s["id"] for s in ss._scheduled_slots_for(sunday)}
    return ids


def _first_weekday():
    import datetime as dt
    d = dt.date(2026, 8, 24)          # a Monday, pinned so the check does not move with the
    while d.weekday() >= 5:            # calendar — a test whose verdict drifts is not a test
        d += dt.timedelta(days=1)
    return d


#: Two namespaces, not one — this is the finding the parity check turned up on its first run.
#:
#: APScheduler keys a job by its `id`. The dashboard does not see APScheduler at all: it
#: parses `scheduler_*.log` and keys on the LABEL the scheduler prints in `[BRACKETS]`, which
#: `_run(label=...)` and `_live_day_body(slot_id=...)` supply. For 56 of the 58 timed jobs the
#: two strings coincide, so nothing has ever gone wrong. Two do not:
#:
#:     job id `live_day`      logs as `LIVE_DAY_1405`   (run_scheduler.py:876 vs :879)
#:     job id `maxhold_exit`  logs as `MAX_HOLD_EXIT`   (run_scheduler.py:650 vs :651)
#:
#: The alias table is asserted, not merely applied: a THIRD job whose id and label diverge
#: turns the parity check red, which is the point. Coincidence that holds 56 times out of 58
#: is not a contract, and the day someone adds a slot is the day it matters.
ID_TO_LOG_LABEL: dict = {
    "live_day": "live_day_1405",
    "maxhold_exit": "max_hold_exit",
}

#: Job ids that exist in the scheduler but deliberately have no dashboard mirror row, and
#: why. Anything NOT on this list must appear on both sides.
MIRROR_EXEMPT: dict = {
    "heartbeat": "every minute, all week; the mirror models timed operational jobs and a "
                 "beat is not one",
    "session_report_fallback": "a safety net that only fires when the event-driven report "
                               "did not; the mirror has no concept of a conditional job",
}


def parity_report(port: int = 4002, *, track1_shadow: bool = False,
                  track1_only: bool = False) -> dict:
    """Where the scheduler and the dashboard mirror disagree, in both directions.

    `track1_shadow` flips BOTH sides at once, which is the point: the scheduler gates the
    Track 1 slots behind `--track1-shadow` and the mirror gates them behind
    `RAITS_TRACK1_SHADOW=1`, and this asks whether the two gates agree about what the day
    contains. Flipping one side only is the drift the check exists to catch.
    """
    import os as _os
    if track1_only:
        track1_shadow = True
    prev = _os.environ.get("RAITS_TRACK1_SHADOW")
    prev_only = _os.environ.get("RAITS_TRACK1_ONLY")
    if track1_shadow:
        _os.environ["RAITS_TRACK1_SHADOW"] = "1"
    else:
        _os.environ.pop("RAITS_TRACK1_SHADOW", None)
    if track1_only:
        _os.environ["RAITS_TRACK1_ONLY"] = "1"
    else:
        _os.environ.pop("RAITS_TRACK1_ONLY", None)
    try:
        sched = scheduler_slot_ids(port, track1_shadow=track1_shadow,
                                   track1_only=track1_only)
        mirror = {m.lower() for m in dashboard_mirror_slot_ids()}
    finally:
        for _k, _v in (("RAITS_TRACK1_SHADOW", prev), ("RAITS_TRACK1_ONLY", prev_only)):
            if _v is None:
                _os.environ.pop(_k, None)
            else:
                _os.environ[_k] = _v
    sched_cmp = {ID_TO_LOG_LABEL.get(s, s) for s in sched if s not in MIRROR_EXEMPT}
    only_scheduler = sorted(sched_cmp - mirror)
    only_mirror = sorted(mirror - sched_cmp)
    return {
        "scheduler_jobs": len(sched),
        "compared": len(sched_cmp),
        "mirror_rows": len(mirror),
        "only_in_scheduler": only_scheduler,
        "only_in_dashboard_mirror": only_mirror,
        "track1_shadow": track1_shadow,
        "track1_only": track1_only,
        "in_parity": not only_scheduler and not only_mirror,
        "exempt": sorted(MIRROR_EXEMPT),
        "aliased": dict(ID_TO_LOG_LABEL),
        "aliases_still_needed": sorted(k for k in ID_TO_LOG_LABEL if k in sched),
    }


# ── Stage 5L: which jobs survive the retirement of legacy ────────────────────────────────
#
# The audit of 2026-08-23 found blocker L6: the 13:45 pre-flight sits in the middle of the
# legacy job block in `run_scheduler.py`, purely because legacy was written first. Anyone
# retiring "the legacy jobs" by reading that file top to bottom would take the data refresh
# with it — and Track 1's freshness gate reads the record that job writes.
#
# The failure would not announce itself. `track1_freshness.check_preflight_record` returns
# MISSING when the record is absent, Track 1 fails closed, and the operator sees a route that
# refuses every entry for a reason that points at a file rather than at a deleted job.
#
# So the classification is written down HERE, where a test can hold it, rather than living as
# a sentence in a runbook. `route_classification` derives every bucket from the scheduler that
# actually runs, so a job added tomorrow lands in `unclassified` and turns the Stage 5L test
# red — the one outcome a hand-written list could never produce.

#: Jobs that belong to NEITHER route. They refresh data, prove liveness, or report — none of
#: them decides a trade, and both routes need every one of them.
SHARED_INFRA_JOBS: dict = {
    "preflight": "the 13:45 data refresh (update_ibkr_daily + update_spy_csv) and the "
                 "preflight_state.json record. Legacy reads the in-memory flag; Track 1 "
                 "reads the file. Retiring legacy must NOT retire this.",
    "heartbeat": "liveness measurement, every minute all week; decides nothing",
    "session_report_fallback": "the 23:55 safety net for the session report; decides nothing",
    "spy_refresh_pm": "Stage 5Q-5. The 16:20 SPY daily refresh. The 13:45 pre-flight runs "
                      "before the close and can never bring today's daily bar, so the regime "
                      "series it writes is always a day short of what the next morning needs. "
                      "Shared: both routes read that CSV, and it decides no trade.",
    # Stage 5ZZS. These three were registered by Stages 5ZZC and 5ZZD and never classified, so
    # `route_classification` had been returning them as `unclassified` ever since — which is
    # precisely what the comment above says should happen, and it did its job: the Stage 5L
    # inventory test went red and stayed red until someone came to name them. Naming them now.
    #
    # Nothing about retirement changes. `legacy_retirement_candidates` returns only the
    # `legacy_entry` bucket, so an unclassified job was never removable and a shared_infra one
    # is not either; the count a legacy start would register is the same before and after.
    # What changes is that the route table now knows these jobs exist.
    "spy_refresh_pm_r1": "Stage 5ZZC. First retry rung of the post-close SPY ladder. Carries "
                         "--skip-if-covered, so a rung with nothing to do exits 0 without a "
                         "fetch. Refreshes data; decides no trade.",
    "spy_refresh_pm_r2": "Stage 5ZZC. Second retry rung of the same ladder, same contract.",
    "spy_last_chance_pre_nkd": "Stage 5ZZD. The 00:45 look before anything freshness-bound "
                               "runs, asking for the previous TRADING day rather than "
                               "yesterday's date - the Monday gap, where the last evening "
                               "rung ran thirty-one hours earlier. Both routes read the file "
                               "it protects, and it decides no trade.",
}

#: Prefixes of the jobs that DO decide legacy trades. These are the retirement candidates.
_LEGACY_ENTRY_PREFIXES = ("live_day", "nkd_night")

#: Safety sweeps. They are neither route's strategy, but unlike shared infra they are wired to
#: a specific positions file today, so they are their own bucket rather than shared (audit L3).
_SAFETY_PREFIXES = ("stop_repair", "maxhold_exit")

_TRACK1_PREFIX = "track1_"


def _bucket_for(job_id: str) -> str:
    if job_id in SHARED_INFRA_JOBS:
        return "shared_infra"
    if job_id.startswith(_TRACK1_PREFIX):
        return "track1"
    if job_id.startswith(_LEGACY_ENTRY_PREFIXES):
        return "legacy_entry"
    if job_id.startswith(_SAFETY_PREFIXES):
        return "safety"
    return "unclassified"


def route_classification(port: int = 4002, *, track1_shadow: bool = False) -> dict:
    """Every registered job id, bucketed by who owns it — read from the scheduler itself.

    Exhaustive by construction: an id matching no rule lands in `unclassified`, which the
    Stage 5L test requires to be empty. A hand-written list would simply not mention a new
    job, and silence is what let the pre-flight be mistaken for legacy in the first place.
    """
    ids = scheduler_slot_ids(port, track1_shadow=track1_shadow)
    out: dict = {"shared_infra": [], "legacy_entry": [], "safety": [], "track1": [],
                 "unclassified": []}
    for jid in sorted(ids):
        out[_bucket_for(jid)].append(jid)
    out["total"] = len(ids)
    out["track1_shadow"] = track1_shadow
    return out


def legacy_retirement_candidates(port: int = 4002, *, track1_shadow: bool = False) -> set:
    """Exactly the job ids that a legacy retirement is allowed to remove.

    Nothing else. Shared infrastructure, the safety sweeps, and Track 1's own slots are all
    outside this set, and `surviving_jobs` is its complement rather than a second list — two
    lists is how they drift apart.
    """
    return set(route_classification(port, track1_shadow=track1_shadow)["legacy_entry"])


def surviving_jobs(port: int = 4002, *, track1_shadow: bool = False) -> set:
    """What the schedule still holds after legacy entry jobs are retired."""
    ids = scheduler_slot_ids(port, track1_shadow=track1_shadow)
    return ids - legacy_retirement_candidates(port, track1_shadow=track1_shadow)


def track1_slot_ids() -> set:
    return {s.id for s in TRACK1_SLOTS}


def as_dict() -> dict:
    return {
        "route": ROUTE,
        "scheduled_live": False,
        "slots": [{"id": s.id, "hour": s.hour, "minute": s.minute, "sleeve": s.sleeve,
                   "kind": s.kind, "note": s.note} for s in TRACK1_SLOTS],
        "required_entry_window": [list(REQUIRED_ENTRY_WINDOW[0]),
                                  list(REQUIRED_ENTRY_WINDOW[1])],
        "event_route_field": {"key": EVENT_ROUTE_FIELD, "value": EVENT_ROUTE_VALUE},
        "paper_output_policy": PAPER_OUTPUT_POLICY,
    }
