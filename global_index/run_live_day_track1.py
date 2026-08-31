"""global_index/run_live_day_track1.py — the Track 1 route entry point. NEW FILE.

Stage 3. **Shadow only.** This process cannot send an order: the order gate refuses while
any Stage 2D blocker is open, and every blocker is open. It does not connect to IB Gateway,
does not start a scheduler, and does not write a single legacy path.

Why a separate entry point rather than a flag on run_live_day
--------------------------------------------------------------
Three reasons, each measured rather than aesthetic:

1. `run_scheduler.py` carries an explicit invariant: **no slot may call `run_live_day`
   between 10:20 and 14:05 ET**, because the legacy signal layer never marks the stress
   cluster unchanged, so `diff_desired_vs_held` closes a stress position on the next run.
   Track 1's Calm A (10:00) and Stress (10:35-12:30) windows land inside that band. A flag
   on `run_live_day` would breach the invariant on its first slot.
2. The legacy invocation's argv is parsed by three dashboard readers and logged verbatim by
   the scheduler one line above the run. It has to stay byte-identical.
3. Track 1 sizes per CANDIDATE. `run_live_day` builds `contracts_by_inst = {inst: 1}` and
   both `decide_day` and `FuturesRunner.run_day` read size from it. MNQ = 1 under Normal and
   MNQ = 7 under Stress on the same day has no key in that dict.

What it writes, and where
-------------------------
Route-scoped, all of it:

    live_positions.track1.json              the route's own book
    runner.track1.pid                       the route's own lock
    global_index/replay_checkpoint.track1.json   route checkpoint, schema 2
    STOP_TRADING.track1                     the route's own kill switch (read, never written)
    scratch/track1_shadow/                  decisions, settlements, gate verdicts

It writes NOTHING under `live_positions.json`, `replay_checkpoint.json`, `runner.pid`,
`live_state_data.js`, `trade_log.jsonl` or any `live_day_*.log`. `scratch/test_track1_stage3
_route_20260822.py` asserts that by hashing those paths before and after a run — the last
one matters more than it looks: a `--dry-run` of the legacy runner once wrote `live_day_*
.log`, which `paper_evidence_reader` globs, and it manufactured a paper-evidence episode
that was then attributed to a different session.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

_CWD = Path.cwd()
if not ((_CWD / "global_index").is_dir() and (_CWD / "futures").is_dir()):
    sys.stderr.write(
        f"CWD guard FAIL: got {_CWD}\n"
        f"  Expected d:\\raits. Fix: cd d:\\raits && python -m global_index.run_live_day_track1\n")
    sys.exit(1)
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd  # noqa: E402

from futures.circuit_breaker import CircuitBreaker  # noqa: E402
from global_index import route_checkpoint as rc  # noqa: E402
from global_index import track1_freshness as fresh  # noqa: E402
from global_index import track1_params as tp  # noqa: E402
from global_index import track1_gates as gates  # noqa: E402
from global_index import track1_explain as tx  # noqa: E402
from global_index import track1_signal_layer as sl  # noqa: E402
from global_index import track1_sleeves as sleeves  # noqa: E402
from global_index import track1_signals as sig
from global_index import window_ledger as wl  # noqa: E402
from global_index.track1_live_frame import SpliceRefused  # noqa: E402
# Stage 5Q-3. Additive and OFF unless RAITS_TELEMETRY_DIR names a directory, exactly as
# for the legacy runner. Until now this module never imported it: `slot_timing/` was
# created, the scheduler exported the variable, and no Track 1 strategy slot has ever
# written a row -- so the acceptance gate's `no_timing_records` was unsatisfiable and its
# p95 cadence check could never run on anything.
from global_index import slot_telemetry as _tel  # noqa: E402
from global_index.track1_live_source import (  # noqa: E402
    IBKRBarProvider, LiveSourceRefused,
    build_bar_provider as _live_source_build_bar_provider)
from global_index.track1_normal_r4 import NormalR4Params  # noqa: E402
from global_index.track1_params import WINDOWS_ET  # noqa: E402
from global_index.track1_signal_layer import (ACCOUNT, Track1Book, daily_series,
                                              make_guard, run_candidates, window_verdict)
# Private on purpose, and imported rather than re-implemented. `_day` strips a timezone
# WITHOUT converting it and `_hhmm_on` reads a stamp on the window's own clock — both
# behaviours the admission rules depend on. A second copy here would be a second definition
# of "which session is this", and the two would eventually disagree about a Tokyo-dated
# MNKD event, which is the defect Stage 2C already paid for.
from global_index.track1_signal_layer import _day, _hhmm_on  # noqa: E402

ROUTE = tp.ROUTE

# Route-scoped paths. Declared once, in one place, so that "did Track 1 touch a legacy file"
# is a question about this tuple rather than about grep.
POSITIONS_PATH = "live_positions.track1.json"
#: Stage 5ZS. Read from the module that owns the path rather than restated here, so the
#: route, the paper executor and the safety guard cannot disagree about what a valid book
#: looks like.
from global_index.track1_slots import TRACK1_BOOK_SCHEMA as BOOK_SCHEMA  # noqa: E402
LOCK_PATH = "runner.track1.pid"
CHECKPOINT_PATH = rc.DEFAULT_PATH               # global_index/replay_checkpoint.track1.json
STOP_FILE = "STOP_TRADING.track1"
#: REPLAY output. `scratch/` is the right home for it: a replay is research, it is
#: reproducible from the measured windows, and losing it costs a re-run.
SHADOW_DIR = "scratch/track1_shadow"

#: LIVE-SHADOW operational evidence, and the reason it is not under `scratch/`: a multi-day
#: shadow period is what a go-live gate is read from, and it is NOT reproducible — nobody can
#: re-observe a window that has closed. Sweeping scratch would delete the only copy. These sit
#: with the route runtime state this repo already keeps under `global_index/`.
RUNTIME_ROOT = "global_index/track1_runtime"
OPERATIONAL_SHADOW_DIR = f"{RUNTIME_ROOT}/shadow"

#: Recommended homes for the two env-driven channels, so the runbook and the code cannot name
#: different directories. Both remain opt-in: unset still means off for telemetry and a hard
#: refusal for the ledger.
RECOMMENDED_LEDGER_DIR = f"{RUNTIME_ROOT}/window_coverage"
RECOMMENDED_TELEMETRY_DIR = f"{RUNTIME_ROOT}/slot_timing"

#: Paths this route must never write. Asserted by test, not merely intended.
LEGACY_PATHS: tuple = (
    "live_positions.json",
    "global_index/replay_checkpoint.json",
    "runner.pid",
    "global_index/live_state_data.js",
    "global_index/paper_history.json",
    "trade_log.jsonl",
    "slip_stats.json",
    "global_index/preflight_state.json",
    "global_index/maxhold_state.json",
)

#: The blocker registry is the single source of truth — `global_index/track1_gates.py`.
#: This alias is kept because the Stage 3 tests and the shadow summary read it by this name,
#: and because a second hand-written copy of the list here is exactly the drift the registry
#: was built to remove. It is DERIVED, never edited.
def _open_blockers() -> dict:
    return {b.id: (b.decision_needed or b.evidence) for b in gates.blocking()}


OPEN_ORDER_BLOCKERS: dict = _open_blockers()


class OrderGate:
    """Whether this process may place an order. Three states, never two.

    `shadow` is the default and is not a degraded mode — it is the mode this route is
    designed to run in until the blockers close. `armed` is refused rather than granted, and
    the refusal names what is open.

    Two independent things must both be true to arm, and that is deliberate. The blocker
    registry must report nothing blocking — which for the gated blockers means a CONFIRMATION
    recorded on disk, schema-checked, failing closed on anything it cannot fully validate —
    and `TRACK1_ORDERS_APPROVED` must be set in the environment. One flag on a command line
    is never enough to reach an exchange.
    """

    SHADOW = "shadow"
    REFUSED = "armed_but_refused"
    ARMED = "armed"

    def __init__(self, requested: bool, *, blockers: dict | None = None,
                 approval_env: str = "TRACK1_ORDERS_APPROVED",
                 confirmation_path: str = gates.CONFIRMATION_PATH) -> None:
        self.requested = bool(requested)
        self.approved = os.environ.get(approval_env) == "1"
        self.confirmations, self.confirmation_errors = gates.load_confirmations(
            confirmation_path)

        if blockers is not None:
            # Test seam only: an explicit dict replaces the registry so a suite can prove the
            # gate WOULD arm with nothing open, i.e. that the refusal is the blockers talking
            # and not a switch that can never move.
            self.blockers = dict(blockers)
        else:
            self.blockers = {b.id: (b.decision_needed or b.evidence)
                             for b in gates.blocking(self.confirmations)}

        if not self.requested:
            self.state = self.SHADOW
            self.reasons: tuple = ()
            return

        reasons = [f"{k}: {v}" for k, v in sorted(self.blockers.items())]
        if self.confirmation_errors:
            reasons.extend(f"confirmation file: {e}" for e in self.confirmation_errors)
        if not self.approved:
            reasons.append(
                f"{approval_env} is not set to 1; arming also requires an explicit "
                f"out-of-band approval, so that a flag alone can never be enough")
        self.reasons = tuple(reasons)
        self.state = self.ARMED if not reasons else self.REFUSED

    @property
    def allow_orders(self) -> bool:
        return self.state == self.ARMED

    def as_dict(self) -> dict:
        return {"state": self.state, "requested": self.requested,
                "allow_orders": self.allow_orders, "reasons": list(self.reasons),
                "confirmations": dict(self.confirmations.flags),
                "confirmation_source": self.confirmations.source,
                "confirmation_errors": list(self.confirmation_errors)}


class NoOrderBroker:
    """A broker that records what would have been sent and sends nothing.

    Used in shadow so the route exercises the same call sites a live broker would see. Every
    method raises or records; none of them reaches a network. `send_order` raising rather
    than returning a synthetic fill is deliberate: a shadow run that silently produced fills
    would build a book nobody could distinguish from a traded one.
    """

    #: This broker answers from nothing, so nothing it says may be believed as a fact about
    #: the account. `get_positions()` below returns `[]`, and in shadow that means "never
    #: asked", not "flat" — several suites already depend on the empty list, so the marker
    #: goes beside it rather than changing what it returns. `track1_broker_read` reads this
    #: and refuses to treat any answer from here as KNOWN.
    CAN_TESTIFY = False

    def __init__(self) -> None:
        self.calls: list = []

    def send_order(self, order):
        self.calls.append(("send_order", order))
        raise RuntimeError(
            "NoOrderBroker.send_order was reached in shadow mode. Nothing was sent. This is "
            "a wiring defect: the shadow path must not attempt to place orders.")

    def cancel_order(self, order_id):
        self.calls.append(("cancel_order", order_id))
        raise RuntimeError("NoOrderBroker.cancel_order was reached in shadow mode.")

    def get_positions(self):
        self.calls.append(("get_positions", None))
        return []

    def get_equity(self):
        self.calls.append(("get_equity", None))
        raise RuntimeError("NoOrderBroker.get_equity was reached in shadow mode.")


#: The live-bar factory lives in `track1_live_source`, which owns every other live-bar
#: primitive and imports the splice guard. Re-exported here so a caller that reaches for it on
#: the entry point still finds it, WITHOUT this module holding a broker touchpoint of its own —
#: which is what shut LIVE_FRAME_ADAPTER_VERIFICATION after Stage 5AB-G1.
#: Stage 5ZZG. The gated send seam. Imported at module level because the SLOT calls
#: it on every run — armed or not — and it is the closed path that must be cheap:
#: it returns before importing the order layer at all.
from global_index import track1_paper_send as _ps

build_bar_provider = _live_source_build_bar_provider


def checkpoint_report(*, regime_csv: str, data_paths: dict,
                      path: str = CHECKPOINT_PATH,
                      fill_law: str | None = None) -> list:
    """What the route checkpoint says about each cross-day sleeve, per instrument.

    Surfaces the REFUSAL CODE rather than a bare miss. `route_checkpoint.usable` returns a
    `Refusal` with one of seven codes precisely because the legacy checkpoint returned
    `None` for four distinct conditions and reconstructing which one fired meant diffing
    hashes out of log lines.

    Expect `params_mismatch` today for the Normal sleeve, and that is the mechanism working:
    the file on disk was bootstrapped under the LEGACY engine identity (ema 30, chandelier
    2.5, ratchet on) and Track 1's Normal-R4 is ema 50 with a fixed entry-anchored 2.0x ATR
    stop and no ratchet. Do not loosen the identity to make it pass.
    """
    # The law the ROUTE runs, named once in `track1_params` and read from there — Stage 5M-1.
    # This used to read `NormalR4Params().fill_law`, which made the route's identity a side
    # effect of an ENGINE default, and until Stage 5M-1 that default was the artifact law. So
    # a live checkpoint comparison was being made against a law the live route does not run.
    law = fill_law if fill_law is not None else tp.LIVE_FILL_LAW
    payload = rc.load(path)
    out = []
    for sleeve in rc.CHECKPOINTED_SLEEVES:
        for inst in tp.SLEEVE_INSTRUMENTS.get(sleeve, ()):
            data_path = data_paths.get(inst)
            _readable, phash = tp.sleeve_identity(sleeve, inst, regime_csv=regime_csv,
                                                  data_path=data_path or "",
                                                  fill_law=law)
            entry = rc.get_entry(payload, ROUTE, sleeve, inst)
            row = {"sleeve": sleeve, "inst": inst, "params_hash": phash}
            if not entry:
                row.update(resumed=False, code=rc.NO_ENTRY,
                           detail=f"no entry under routes/{ROUTE}/sleeves/{sleeve}")
                out.append(row)
                continue
            # Compare identity WITHOUT loading the frame: a params mismatch is decidable
            # from the entry alone, and loading an 8-year parquet to be told the settings
            # moved is minutes spent to learn nothing.
            if entry.get("params_hash") != phash:
                row.update(resumed=False, code=rc.PARAMS_MISMATCH,
                           detail=f"stored={entry.get('params_hash')} caller={phash} "
                                  f"stored_params={entry.get('params')!r}")
                out.append(row)
                continue
            if entry.get("route") not in (None, ROUTE):
                row.update(resumed=False, code=rc.ROUTE_MISMATCH,
                           detail=f"entry route={entry.get('route')!r}")
                out.append(row)
                continue
            row.update(resumed=None, code="params_ok_frame_not_loaded",
                       detail="identity matches; the fingerprint check needs the frame and "
                              "is done by the sleeve source when it loads it")
            out.append(row)
    return out


def record_window_observation(sleeve: str, date, slot_ids, *, entered: bool) -> dict:
    """Write one detection window's coverage to the route ledger.

    The live path calls this once per sleeve per session, after the window has closed. It is
    separated from the replay above because the two can testify to different things: a live
    slot that ran and saw nothing IS evidence, and a replay row is not.

    `slot_ids` is the list of slots that actually reported, not a count, so an incomplete
    window can name which ones are missing. A no-op unless RAITS_WINDOW_LEDGER_DIR is set.
    """
    day = str(pd.Timestamp(date).date())
    ids = list(slot_ids)
    wl.window_open(sleeve, day, route_hint=ROUTE)
    for i, sid in enumerate(ids):
        ok, why = window_verdict(sleeve, pd.Timestamp(f"{day} {sid}")) if ":" in str(sid) \
            else (True, "")
        wl.slot_observed(sleeve, day, str(sid), seq=i, in_window=ok, note=why)
    wl.window_closed(sleeve, day, len(ids),
                     signal=wl.ENTERED if entered else wl.NO_SIGNAL)
    return {"sleeve": sleeve, "date": day, "observed_slots": len(ids),
            "expected_slots": wl.expected_slots(sleeve), "entered": bool(entered)}


#: Why a live-shadow slot could not take a decision. Recorded on the slot's own ledger row, so
#: a window that never decided cannot later be mistaken for one that decided nothing.
LEDGER_NOT_CONFIGURED = "ledger_not_configured"
NO_BAR_PROVIDER = "no_bar_provider"
LIVE_SOURCE_NOT_READY = "live_source_not_ready"
GATE_REFUSED = "gate_refused"
FRESHNESS_REFUSED = "freshness_refused"
#: Stage 5Q-3. The join guard refused. Its own code -- column_mismatch, tz_mismatch,
#: duplicate_timestamps, history_mutated -- travels in `detail`, the same way the intraday
#: gate's codes do, so a window of these rows can be told apart at a glance.
LIVE_FRAME_REFUSED = "live_frame_refused"
#: Stage 5ZX. The slot was launched naming a phase its sleeve does not declare. Refusing is the
#: whole point: the alternative is gating a decide-half slot with the entry-half requirement,
#: which passes at the wrong instant and leaves a record indistinguishable from a correct run.
UNKNOWN_PHASE = "unknown_phase"
DECIDED = "decided"


class _PhaseHalfComplete(Exception):
    """A phased half finished everything it is entitled to do. Stage 5ZX.

    A structured early exit rather than a flag, because what follows it is one straight-line
    block of four steps inside the slot's own `try`, and the alternative — indenting all four
    under a condition — moves production code that runs for three other sleeves in order to
    add a branch for a fourth. This exception cannot escape: it is caught by the handler
    immediately below the block that raises it, and it is private to this module.

    It is NOT a refusal, and the handler that catches it deliberately changes nothing: the
    slot keeps `decided=True` and the reason `decided`, because the phase DID look at today
    and was not stopped.

    Both halves take it, for the same reason in two shapes: neither takes a position, so
    neither may run freshness, the cap guard, admission or the explanation records. The
    decide half has nothing to admit yet; the observe half has nothing left to admit.
    """


class ShadowRefused(RuntimeError):
    """A live-shadow slot refused to run. Carries the reason it will be judged on."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _slots_for(sleeve: str) -> list:
    from global_index import track1_slots as t1
    return [s for s in t1.TRACK1_SLOTS if s.sleeve == sleeve]


def _resample(frame, sleeve: str, requirement=None):
    """`frame` at the bar size `track1_intraday` declares for `sleeve`.

    Derived from the requirement rather than hard-coded to five minutes, so a sleeve that ever
    declares a different size does not silently keep being validated at the old one.

    Stage 5ZX. The caller may hand in the requirement it ALREADY resolved. It has to be able
    to: a phased slot is governed by a phase requirement, and re-deriving one here from the
    sleeve name alone would resample Calm's decide half to five minutes while the gate judged
    it at one — two bar sizes for one frame, which is the exact confusion 5ZU came out of.
    """
    from global_index import track1_intraday as intra

    req = requirement if requirement is not None else intra.REQUIREMENTS.get(sleeve)
    n = int(getattr(req, "bar_minutes", 1) or 1)
    if n <= 1:
        return frame
    o = frame["open"].resample(f"{n}min").first()
    h = frame["high"].resample(f"{n}min").max()
    lo = frame["low"].resample(f"{n}min").min()
    c = frame["close"].resample(f"{n}min").last()
    v = frame["volume"].resample(f"{n}min").sum()
    out = pd.concat([o, h, lo, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna(subset=["open"])


#: Last failure from the observation writer, if any. A list so the writer can record into it
#: without a global statement — the same shape the signal diagnostics use, and read by tests.
_data_observation_last_error = [""]


#: Stage 5ZZZ-B. Last strategy-diagnostics failure, in a one-element list for the same reason
#: `_data_observation_last_error` is: a module-level name a nested function can write without a
#: `global` statement, and one the dashboard can render. A failure that only reached a log file
#: would be a failure nobody sees.
_strategy_diagnostics_last_error: list = [None]


def _write_data_observation(*, sleeve, day, slot_id, joined, refusal, decided, reason,
                            candidates, data_paths, root: str = ".") -> None:
    """Compose and append one data-observation row. Reads; never recomputes.

    `joined` is `{inst: JoinedFrame}` when the frame was built, or None when the slot was
    refused before that. `refusal` is `(code, detail)` in the second case. Both may be absent
    — a slot whose provider was missing never reached either — and then nothing is written,
    because a row claiming an observation nobody made is worse than no row.
    """
    from global_index import track1_data_observation as obs
    from global_index import track1_params as _tp

    if joined is None and refusal is None:
        return

    if joined is None:
        code, detail = refusal
        obs.record(obs.refusal_row(session_date=str(day), sleeve=sleeve, slot_id=slot_id,
                                   mode="shadow_live", error_code=code, error=detail),
                   root=root, day=str(day))
        return

    rows = []
    for inst in sorted(joined):
        jf = joined[inst]
        path = str((data_paths or {}).get(inst, "") or "")
        rows.append(obs.instrument_row(
            jf,
            history_symbol=_history_symbol(inst),
            tradable_symbol=_tradable_symbol_for(inst),
            data_path=path,
            data_identity=(_tp.file_identity(path) if path else "")))

    outcome = obs.DECIDED if decided else obs.REFUSED
    row = obs.build_row(session_date=str(day), sleeve=sleeve, slot_id=slot_id,
                        mode="shadow_live", instruments=rows,
                        decision_reached=bool(decided), decision_reason=str(reason),
                        candidate_count=int(candidates or 0), outcome=outcome,
                        error_code=("" if decided else str(reason)))
    obs.record(row, root=root, day=str(day))


def _history_symbol(inst: str) -> str:
    """The symbol the PARQUET is stored under, which is not always the runner's name for it.

    Three identities per instrument and they have already diverged once: the runner calls the
    Nikkei micro MNKD, its history lives under NKD, and its orders go to MNK. A record that
    printed one of the three and called it "the symbol" would be the reason somebody later
    compared the wrong two.
    """
    return {"MNKD": "NKD"}.get(str(inst), str(inst))


def _tradable_symbol_for(inst: str) -> str:
    try:
        from global_index import track1_paper_order as _po
        return str(_po.tradable_symbol(str(inst)))
    except Exception:                                          # noqa: BLE001
        return ""


#: Stage 5ZX. Why a shadow intent row could not be written, or "" when the last attempt
#: succeeded. A list so the dashboard can read it the way it already reads the data-observation
#: channel's error, and — the point — so a failure to record evidence is itself visible. A
#: stream that silently stopped writing would look, to every reader downstream, exactly like a
#: route that had no intents to record.
_shadow_intent_last_error = [""]


def shadow_intent_last_error() -> str:
    return _shadow_intent_last_error[0]


def _write_shadow_intent(*, phase, slot_id, day, root, decided, reason,
                         pre_entry, joined, now_et, data_paths=None) -> None:
    """One phase's evidence rows. Appends to the shadow intent stream and nothing else.

    Every path writes SOMETHING. A phase that refused writes a REFUSED row carrying the gate's
    own reason; a phase that ran and found nothing writes NO_SETUP. Silence is the one outcome
    that is not allowed, because an absent row and a no-setup day are indistinguishable to a
    reader and only one of them means the route was watching.
    """
    from global_index import track1_shadow_intent as si
    from global_index import track1_calm_a as CA

    sess = str(pd.Timestamp(day).date())
    # The slot's OWN data paths, not None. Passing None returned an empty identity, so every
    # intent row would have said the same nothing about where its numbers came from — and two
    # rows computed from different data would have compared equal, which is the same defect
    # the signals channel has carried since it was written (recorded, not repaired from here).
    ident = _signal_data_identity(data_paths, "roska4_calm")
    # This stream's own strategy digest rather than the signals channel's, which has been
    # empty since the day it was added. See `si.calm_params_identity`.
    phash = si.calm_params_identity()
    common = dict(session_date=sess, data_identity=ident, params_hash=phash)

    if not decided:
        # The slot's OWN reason, not a blanket "gate_refused". Measured: the first observe
        # run refused with `no_sleeve_at_this_instant`, which came from the candidate source
        # and not from the gate at all — and the row said gate_refused, which would have sent
        # whoever read it to inspect a gate that had passed. The stream carries the route's
        # vocabulary where the stream has a name for it, and the slot's where it does not.
        code = si.GATE_REFUSED if reason == GATE_REFUSED else str(reason)
        row = (si.decide_row if phase == si.DECIDE else si.observe_row)(
            slot_id, status=si.REFUSED, reason_code=code, **common)
        si.append(row, root=root, day=sess)
        return

    if phase == si.DECIDE:
        if not pre_entry:
            si.append(si.decide_row(slot_id, status=si.NO_SETUP,
                                    reason_code=si.NO_CANDIDATE, **common),
                      root=root, day=sess)
            return
        p = CA.CalmAParams()
        for pre, atr, point_value, qty in pre_entry:
            dist = float(p.disaster_stop_atr_mult) * float(atr)
            si.append(si.decide_row(
                slot_id, status=si.RECORDED, reason_code=si.OK, **common,
                before_entry={
                    "setup": "calm_a",
                    "instrument": pre.inst,
                    "direction": pre.direction,
                    "qty": int(qty),
                    # The RULE, not a price. "entry - 1.5 x ATR" is fully known now; only the
                    # level it evaluates to waits for ten o'clock.
                    "stop_rule": "entry - %s x daily_atr" % p.disaster_stop_atr_mult,
                    "risk_inputs": {"daily_atr_causal": float(atr),
                                    "point_value": float(point_value),
                                    "stop_atr_mult": float(p.disaster_stop_atr_mult),
                                    "stop_distance": dist,
                                    "risk_dollars": dist * float(point_value) * int(qty)},
                    "entry_reference_time": p.entry_time,
                    "intent": "would_send_at_entry_reference_time",
                }), root=root, day=sess)
        return

    # ── OBSERVE ──────────────────────────────────────────────────────────────
    # Refuses unless THIS DAY already carries a recorded decide row. An observe row standing
    # alone would say a reference price was seen and imply a decision behind it that nobody
    # can point to — which is the collapse this phase exists to make impossible.
    prior = [r for r in si.read_day(root, sess)
             if r.get("phase") == si.DECIDE and r.get("status") == si.RECORDED]
    if not prior:
        si.append(si.observe_row(slot_id, status=si.REFUSED,
                                 reason_code=si.NO_DECIDE_ROW, **common),
                  root=root, day=sess)
        return

    p = CA.CalmAParams()
    for d in prior:
        be = dict(d.get("before_entry") or {})
        inst = be.get("instrument")
        held = (joined or {}).get(inst)
        ref = None
        if held is not None:
            ref, _ts = CA._bar_open_at(held.frame, pd.Timestamp(day).normalize(), p.entry_time)
        if ref is None:
            si.append(si.observe_row(slot_id, status=si.REFUSED,
                                     reason_code=si.NO_REFERENCE,
                                     before_entry=be, **common), root=root, day=sess)
            continue
        atr = float((be.get("risk_inputs") or {}).get("daily_atr_causal"))
        si.append(si.observe_row(
            slot_id, status=si.RECORDED, reason_code=si.OK, before_entry=be, **common,
            after_reference={
                "entry_reference_price": float(ref),
                "planned_stop": si.planned_stop_from(float(ref), atr,
                                                     p.disaster_stop_atr_mult),
            }), root=root, day=sess)


def observe_live_slot(sleeve: str, slot_id: str, *, now_et, provider=None,
                      data_paths=None, frozen_frames=None, live_source=None,
                      regime_csv: str = "spy_daily_live.csv",
                      out_dir: str = OPERATIONAL_SHADOW_DIR, root: str = ".",
                      phase: str = "",
                      # Stage 5ZZG. The gate governing this slot, and the broker the BARS came
                      # from. Both default to the shut/absent case so every existing caller —
                      # the scheduler included — is unchanged and cannot arm anything.
                      order_gate: "OrderGate | None" = None, broker=None) -> dict:
    """One Track 1 slot, observing TODAY. Writes the ledger row this slot is entitled to.

    This is the path the scheduler drives, and it is deliberately not the replay path. A replay
    of a measured window cannot testify that anyone looked at today, which is the single thing
    the window ledger exists to record — so the two are different functions rather than one
    function with a flag.

    **Fails closed, and the refusal is the record.** Four things can stop a slot from deciding,
    and each is written to the slot's own row rather than swallowed:

        ledger_not_configured   RAITS_WINDOW_LEDGER_DIR is unset, so nothing could be written
                                at all. This one raises before anything else happens: a shadow
                                run whose whole purpose is to leave evidence must not run
                                silently when it cannot.
        no_bar_provider         nobody handed the slot a source of today's bars.
        live_source_not_ready   bars and gate were fine; the sleeve cannot yet turn them into a
                                candidate. This is precondition 2b, and it is the honest state
                                today.
        gate_refused            the intraday gate said no — a real, informative observation.

    A slot only counts toward window coverage when it actually DECIDED. That is what keeps
    precondition 5 from turning green on a route that cannot trade: while the live source is
    not ready every slot records `decided=False`, the window closes INCOMPLETE, and coverage
    never reports complete. Counting an undecidable slot as observed would manufacture exactly
    the evidence the ledger was built to withhold.
    """
    if not wl.enabled():
        raise ShadowRefused(
            LEDGER_NOT_CONFIGURED,
            "RAITS_WINDOW_LEDGER_DIR is unset or not a directory, so this slot could not "
            "record that it ran. A shadow slot exists to leave evidence; one that cannot is "
            "not a quieter success, it is a silent absence, and the ledger cannot tell that "
            "apart from a window nobody watched")

    day = pd.Timestamp(now_et).date()
    slots = _slots_for(sleeve)
    ids = [s.id for s in slots]
    if slot_id not in ids:
        raise ShadowRefused("unknown_slot", f"{slot_id!r} is not a {sleeve} slot; known: {ids}")
    seq = ids.index(slot_id)
    if seq == 0:
        wl.window_open(sleeve, day, route_hint=ROUTE)

    gate = order_gate if order_gate is not None else OrderGate(False)
    reason, detail, decided = DECIDED, "", True
    verdict, n_cands = None, None
    freshness_allow = accepted = n_rejected = n_explained = None
    # Stage 5ZD. Pre-bound so the signal-diagnostics row can be built on EVERY path, including
    # the refusals — a slot that was refused still has something to say, and a row that only
    # existed on the happy path would be missing exactly the days worth explaining.
    found, decisions = [], []
    # Stage 5ZX. Pre-bound with the two above and for the same reason: the shadow intent row
    # is written on every path including the refusals, and a name that only existed on the
    # happy path would leave exactly the days worth explaining with nothing to say.
    _decide_pre_entry: list = []
    # Stage 5ZO. Pre-bound like `found`/`decisions` above and for the same reason: a slot that
    # was REFUSED still observed something — or tried to — and a variable that only existed on
    # the happy path would leave exactly the slots worth explaining with no record.
    _joined_for_obs, _obs_refusal = None, None
    # Stage 5ZZZ-B. Pre-bound with the three above and for the identical reason: the strategy
    # diagnostics block is written on every path including the refusals, and a name that only
    # existed on the happy path would leave exactly the slots worth explaining with nothing.
    _strategy_diag_source = None
    try:
        if provider is None:
            raise ShadowRefused(NO_BAR_PROVIDER,
                                "no bar provider was handed to the slot, so today's session "
                                "could not be joined onto history")
        from global_index import track1_intraday as intra
        from global_index import track1_live_source as src

        joined = src.sleeve_frames(provider=provider, through=now_et,
                                   data_paths=data_paths, frozen_frames=frozen_frames,
                                   sleeves=[sleeve])[sleeve]
        # A reference, not a copy and not a computation: everything the observation record
        # needs was already recorded by the join while it ran.
        _joined_for_obs = joined
        first = joined[sorted(joined)[0]]
        # The gate declares its own bar size per sleeve and the joined frame is 1-minute, which
        # is what the detectors read. Handing the gate the raw frame made it refuse every slot
        # with `gate_refused` for a reason that had nothing to do with the market — resample to
        # the size the requirement names rather than assuming the two agree.
        # Stage 5ZU. The MINUTE index goes with it, because one sleeve's requirement is about
        # two different bar sizes and the gate cannot invent the second. Calm decides on the
        # five-minute span through 09:55 and prices its entry at the 10:00 OPEN, which is
        # readable from a closed one-minute bar at 10:01 and from a closed five-minute bar
        # only at 10:05 — four minutes after its own deadline. Passing the resampled frame
        # alone is what made the gate ask for a bar that cannot exist when it asks.
        #
        # `first.frame` is the joined 1-minute frame the detectors read, already built above.
        # Stage 5ZX. The requirement is resolved ONCE, here, and both the gate and the
        # resampling use that one object. An unknown phase refuses by name rather than
        # falling back to the sleeve's own requirement — a typo in a scheduler argument
        # must not quietly gate the decide half with the entry-half rule and then look,
        # in every record afterwards, exactly like a slot that ran correctly.
        _req = intra.requirement_for(sleeve, phase)
        if _req is None:
            raise ShadowRefused(
                UNKNOWN_PHASE,
                f"{phase!r} is not a declared phase of {sleeve}; known: "
                f"{sorted(ph for sl, ph in intra.PHASE_REQUIREMENTS if sl == sleeve)}")
        verdict = intra.validate(sleeve, _resample(first.frame, sleeve, _req), now_et=now_et,
                                 session_day=pd.Timestamp(day), requirement=_req,
                                 entry_quote_index=first.frame.index)
        if not verdict.allow:
            reason, detail, decided = GATE_REFUSED, ",".join(verdict.codes), False
        else:
            # The slot instant, not the day: which sleeve may decide is a question about the
            # window this slot sits in, and a date cannot answer it.
            source = live_source
            if source is None:
                from global_index.track1_live_source import LiveTrack1Source
                source = LiveTrack1Source(bar_provider=provider, regime_csv=regime_csv,
                                          data_paths=data_paths, frozen_frames=frozen_frames)
            _strategy_diag_source = source

            # Stage 5ZX. The decide half stops before the ADMISSION machinery, and the
            # steps below are the reason it has to: the cap guard, admission and the
            # explanation records all describe a POSITION being taken, and the decide half
            # takes none. Running them at 09:32 and again at 10:02 would book the same intent
            # through the same guard twice, and the second pass would find the first one's
            # state waiting for it.
            #
            # Stage 5ZZB CORRECTION. Freshness was bundled in with those and should not have
            # been. It is not a statement about positions — it asks whether the INPUTS are
            # current enough to decide on at all, and that question is exactly as live for a
            # half that records an intent as for one that books a trade. Measured on
            # 2026-08-27: the phased slots returned `freshness_allow=None`, meaning the gate
            # never ran, while the daily regime file was two sessions stale. An intent
            # recorded from a two-day-old regime label, carrying no note that it was, is
            # evidence describing a route that is not the route that would trade.
            #
            # So freshness runs for a phased slot too, and it BINDS: a refused input makes the
            # phase record its refusal rather than an intent. That costs nothing — nothing
            # trades on either half — and it is the difference between a day that is missing
            # from the evidence and a day that quietly counts.
            #
            # `found` stays the empty list it was pre-bound to, and that is honest rather than
            # convenient: `candidates` means TRADABLE candidates, and at half past nine there
            # are none, because the price they would trade at does not exist. What the phase
            # actually found goes to the shadow intent stream below, where a reader can tell
            # "recorded an intent" from "no setup today" — a distinction the coverage row was
            # never built to carry and must not be taught to fake.
            if phase == "DECIDE":
                _decide_pre_entry = source.calm_pre_entry(pd.Timestamp(now_et))
                n_cands = 0
            elif phase == "OBSERVE":
                # Runs no detector at all, and measurement is what settled that rather than
                # taste. `candidates` begins with `sleeves_at(now)`, and 10:02 sits inside no
                # Track 1 window — Calm's is the single instant 10:00 — so asking it here
                # refuses `no_sleeve_at_this_instant` on every day. Which is the right answer
                # to the wrong question: this phase is not looking for a setup. The setup was
                # found half an hour ago and written down. All that is left is to read the
                # price the decision named, and that comes from the joined frame below.
                n_cands = 0
            else:
                found = source.candidates(pd.Timestamp(now_et))
                n_cands = len(found)

            # ── route-level decision machinery ────────────────────────────────────────
            # The replay path evaluates freshness, builds the cap guard, runs the admission
            # layer and emits explanations. Until Stage 5I the live slot did NONE of those, so
            # a shadow day would have recorded `decided=true` for candidates that had passed
            # no cap, no family cap, no same-symbol rule and no freshness gate — evidence
            # describing a route that is not the route that would trade. The same four steps
            # run here, in the same order, on the same objects.
            fresh_verdict = fresh.evaluate(now_et=pd.Timestamp(now_et),
                                           regime_csv=regime_csv, parquets=data_paths or {})
            freshness_allow = bool(fresh_verdict.allow)
            if phase:
                if not freshness_allow:
                    # The refusal IS the record, as everywhere else on this route. The reason
                    # travels in the route's own vocabulary so a reader can tell a stale daily
                    # file from a gate refusal from a sleeve that found nothing.
                    codes = ",".join(
                        c.name for c in fresh_verdict.checks
                        if getattr(c, "status", "ok") not in ("ok", "unverified"))
                    raise FreshnessRefused(
                        f"the inputs a decision needs are not current: {codes or 'stale'}")
                raise _PhaseHalfComplete()

            book = Track1Book(guard=make_guard(), breaker=CircuitBreaker(account=ACCOUNT),
                              enforce_windows=True)
            settlements, decisions = run_candidates(found, book=book)
            accepted = sum(1 for d in decisions if d.verdict == "take")
            n_rejected = len(decisions) - accepted

            # `mode` is shadow_live, so freshness BINDS: `explanations_for` refuses to record an
            # admission taken while the daily inputs were refused, rather than writing a record
            # that contradicts itself. That refusal is caught below and becomes the slot's
            # reason — it must not become a silent `decided=true`.
            # `out_dir`/`root` are parameters, not the constant they were for one draft: the
            # slot wrote its explanations straight into the real scratch/track1_shadow, so a
            # test that merely called it left artefacts in the repo. Caught by another
            # session's guard asserting that directory is untouched.
            # Stage 5Q-2: the window sub-path is per SLEEVE and per SLOT, built by
            # `track1_explain.live_window` so the layout has one owner. It was
            # `f"live_{day}"` — one file shared by every slot of every sleeve, opened with
            # mode="w" by each of them, so Calm's 10:00 rows were erased by Stress at 10:35
            # every day. Truncation was never the bug; a shared path was. A slot with its own
            # file may replace its own evidence and can no longer touch anyone else's.
            explained = emit_explanations(
                decisions, out_dir=out_dir, root=root,
                window=tx.live_window(day, sleeve, slot_id), slot_id=slot_id,
                regime_csv=regime_csv, data_paths=data_paths or {},
                fill_law=tp.LIVE_FILL_LAW, freshness_allow=freshness_allow,
                mode=tx.SHADOW_LIVE, as_of=pd.Timestamp(now_et), context_sleeve=sleeve)
            n_explained = (explained or {}).get("records")
    except _PhaseHalfComplete:
        # Not a refusal — see the class. Nothing is reassigned: `decided` is still True and
        # the reason is still `decided`, which is the truth about a slot that looked at today
        # and was not stopped. What it FOUND is in the shadow intent row below.
        pass
    except ShadowRefused as exc:
        reason, detail, decided = exc.code, exc.detail[:200], False
    except FreshnessRefused as exc:
        # A binding mode caught an admission taken while the daily inputs were refused. The
        # slot records that, and does NOT count toward window coverage.
        reason, detail, decided = FRESHNESS_REFUSED, str(exc)[:200], False
    except LiveSourceRefused as exc:
        # The source's own vocabulary, kept rather than flattened. "regime_unavailable" and
        # "the rule is in scratch" are different problems with different owners, and a window
        # of rows that all said `live_source_not_ready` could not tell them apart.
        reason, detail, decided = exc.code, exc.detail[:200], False
    except SpliceRefused as exc:
        # Stage 5Q-3. Until now this was the ONLY refusal on the live path that was not
        # caught, so it propagated out of the slot and the slot died before writing
        # anything -- no `slot_observed` row and no window close. Measured on the first
        # live Calm slot, 2026-08-24 10:00 ET: the audit could then only report
        # `coverage_unobserved` and `missing_slot_ids`, which says 'nobody looked' about a
        # slot that looked and was refused. The guard's own docstring already said the
        # refusal IS the record.
        reason, detail, decided = (LIVE_FRAME_REFUSED,
                                   ("%s: %s" % (exc.code, exc.detail))[:200], False)
        _obs_refusal = (str(exc.code), str(exc.detail)[:200])
    except NotImplementedError as exc:
        reason, detail, decided = (LIVE_SOURCE_NOT_READY,
                                  str(exc).split("\n")[0][:200], False)
        _obs_refusal = (LIVE_SOURCE_NOT_READY, str(exc).split("\n")[0][:200])

    wl.slot_observed(sleeve, day, slot_id, seq=seq, decided=decided, reason=reason,
                     detail=detail or None, candidates=n_cands,
                     freshness_allow=freshness_allow, accepted=accepted,
                     rejected=n_rejected, explained=n_explained,
                     route_hint=ROUTE,
                     gate=(None if verdict is None else bool(verdict.allow)))

    # Stage 5ZO — the data-observation record. OBSERVABILITY ONLY.
    #
    # Written AFTER the coverage row, for the same reason the signal row is: the coverage row
    # is the evidence the audit counts, and a diagnostics failure must never be the reason a
    # slot loses it. Wrapped for the same reason too.
    #
    # It cannot change a decision. Everything it writes was recorded by the join while the
    # slot was deciding; nothing here computes a feature, calls a detector or touches a rule.
    try:
        _write_data_observation(sleeve=sleeve, day=day, slot_id=slot_id,
                                joined=_joined_for_obs, refusal=_obs_refusal,
                                decided=decided, reason=reason, candidates=n_cands,
                                data_paths=data_paths)
    except Exception as _obs_exc:                              # noqa: BLE001
        _data_observation_last_error[0] = f"{type(_obs_exc).__name__}: {_obs_exc}"

    # Stage 5ZZZ-B — strategy diagnostics. OBSERVABILITY ONLY.
    #
    # The third block of its kind here, placed and wrapped exactly like the two around it: after
    # the coverage row, because that row is the evidence the audit counts and nothing below it
    # may be the reason a slot loses it.
    #
    # What it persists was collected by the detector while it was deciding — the trend filter,
    # the ATR, the ten-bar average volume, the regime it was handed and the gate it stopped at.
    # It computes nothing: `_stash_diagnostics` built the block on the candidate path and this
    # only writes it, so a slot's own record says what it looked at rather than what someone
    # replayed afterwards.
    #
    # Nothing reads it for a decision. The readiness gate, the audit and the order gate are all
    # unchanged by its presence or its absence.
    try:
        _blocks = list(getattr(_strategy_diag_source, "last_diagnostics", {}).get(sleeve) or [])
        if _blocks:
            from global_index import track1_strategy_diagnostics as _sd

            _slot_hhmm_d = next((f"{x.hour:02d}:{x.minute:02d}"
                                 for x in slots if x.id == slot_id), "")
            for _b in _blocks:
                _b = dict(_b)
                _b.update(session_date=str(day), slot_id=slot_id, slot_time=_slot_hhmm_d,
                          mode=tx.SHADOW_LIVE, route=ROUTE, decided=decided, reason=reason)
                _sd.record(_b, root=root, day=str(day))
    except Exception as _sd_exc:               # pragma: no cover - defence, not a code path
        _strategy_diagnostics_last_error[0] = f"{type(_sd_exc).__name__}: {_sd_exc}"

    # Stage 5ZD — signal diagnostics. OBSERVABILITY ONLY.
    #
    # Written AFTER the coverage row on purpose: the coverage row is the evidence the audit
    # counts, and a diagnostics failure must never be the reason a slot loses it. The whole
    # block is wrapped because a row that explains why nothing happened is not worth a slot.
    #
    # It cannot change a decision: everything it reads is already computed, and `sig.build_row`
    # is pure. The `except` is not a swallow of the slot's own work — `sig.append` already
    # fails soft — it is the last line against a diagnostics bug taking a slot down with it.
    # Stage 5ZZZ-AT. The verdicts the slot already reported, keyed by the DECLARED rule name,
    # so the signal row can say "measured" where it has actually measured something.
    #
    # Built only from `gates` -- the slot-level channel. The per-bar channel is deliberately
    # left out: a rule answered once per bar has no single verdict for the slot (measured on a
    # real session, twelve passes and ten failures inside one slot), and writing one here would
    # put a number in a cell that cannot hold it. Those are drawn on the bar grid instead.
    #
    # Nothing is computed. The mapping is `track1_signals.declared_for`, the same bridge the
    # panel reads, so the row and the panel cannot disagree about which rule a gate answers.
    _measured: dict = {}
    try:
        for _b in list(getattr(_strategy_diag_source, "last_diagnostics", {}).get(sleeve) or []):
            for _g in (_b.get("gates") or []):
                _name = sig.declared_for(sleeve, str(_g.get("gate") or ""))
                if not _name or _g.get("passed") is None:
                    continue
                _measured[_name] = {"passed": bool(_g.get("passed")), "value": _g.get("value"),
                                    "threshold": _g.get("threshold"),
                                    "comparator": str(_g.get("comparator") or ""),
                                    "detail": str(_g.get("detail") or "")}
    except Exception:                          # pragma: no cover - defence, not a code path
        _measured = {}

    try:
        _slot_hhmm = next((f"{x.hour:02d}:{x.minute:02d}" for x in slots if x.id == slot_id),
                          "")
        sig.append(
            sig.build_row(
                sleeve=sleeve, slot_id=slot_id, slot_time=_slot_hhmm, session_date=day,
                mode=tx.SHADOW_LIVE, decided=decided, reason=reason, detail=detail,
                raw_candidates=int(n_cands or 0), accepted=int(accepted or 0),
                rejected=int(n_rejected or 0), decisions=decisions, candidates=found,
                freshness_allow=freshness_allow,
                gate_allow=(None if verdict is None else bool(verdict.allow)),
                gate_codes=(() if verdict is None else tuple(verdict.codes)),
                params_hash=_signal_params_hash(sleeve),
                regime_basis=_signal_regime_basis(sleeve),
                data_source_identity=_signal_data_identity(data_paths, sleeve),
                measured_rules=_measured),
            root=root)
    except Exception as _sig_exc:            # pragma: no cover - defence, not a code path
        # Recorded through the signals channel's own error slot rather than a logger, for two
        # reasons: this module has no logger, and `last_error()` is what the dashboard already
        # renders. A failure that only reached a log file would be a failure nobody sees.
        sig._disabled = True
        sig._last_error = f"{type(_sig_exc).__name__}: {_sig_exc}"

    # Stage 5ZZG — the SEND pass. Held shut by the gate, and placed here on purpose.
    #
    # AFTER the coverage row, for the reason every write below it carries: the coverage row is
    # the evidence the audit counts and nothing that follows may be the reason a slot loses it.
    # OUTSIDE the refusal handler above, because a send failure is not a slot that could not
    # decide — it is an order whose fate is unknown, and flattening it into a ledger reason
    # would file the most serious outcome this route has under the same word as a stale bar.
    #
    # `decisions` is the list `run_candidates` returned, pre-bound to `[]` at the top, so every
    # path reaches this with something. A phased Calm slot exits before the admission layer
    # runs, so its list is empty and this sends nothing — which is correct: the decide and
    # observe halves record intent, and the step that sends at the entry instant does not
    # exist yet.
    #
    # `broker` is the object the BARS came from. Nothing here builds one.
    _send = _ps.maybe_send_orders(decisions, order_gate=gate, broker=broker,
                                  ref_day=day, slot_id=slot_id, root=root)

    # Stage 5ZX — the shadow intent row. EVIDENCE ONLY, and never an order.
    #
    # Written last, after the coverage row and the two diagnostics rows, for the reason all
    # three state: the coverage row is what the audit counts, and nothing written afterwards
    # may be the reason a slot loses it. Wrapped for the same reason.
    #
    # It goes to `track1_runtime/shadow_intent/`, NOT to `track1_runtime/orders/`. Four
    # separate readers treat the mere existence of the orders directory as proof this route
    # has acted — the book repair refuses to run, the call-site guard trips, the report flips
    # off NOT_PRODUCED, and the runbook says stop and investigate. A rehearsal written there
    # would make all four describe a route that traded on a day it sent nothing.
    if phase:
        try:
            _write_shadow_intent(phase=phase, slot_id=slot_id, day=day, root=root,
                                 decided=decided, reason=reason,
                                 pre_entry=_decide_pre_entry, joined=_joined_for_obs,
                                 now_et=now_et, data_paths=data_paths)
        except Exception as _si_exc:                                   # noqa: BLE001
            _shadow_intent_last_error[0] = f"{type(_si_exc).__name__}: {_si_exc}"

    closed = None
    if seq == len(ids) - 1:
        closed = close_live_window(sleeve, day)
    return {"sleeve": sleeve, "slot_id": slot_id, "seq": seq, "date": str(day),
            "decided": decided, "reason": reason, "detail": detail,
            "candidates": n_cands, "freshness_allow": freshness_allow,
            "accepted": accepted, "rejected": n_rejected, "explained": n_explained,
            "closed": closed, "send": _send.as_dict()}


#: Stage 5ZZZ-Q. The regime object each sleeve hands its detector, named once so the signal row
#: and the parity checker cannot drift apart. Taken from the live call sites, which Stage 5ZZZ-Q
#: made uniform for the two Normal-R4 sleeves.
SLEEVE_REGIME_BASIS = {
    "global_nkd": "causal_d1",       # RegimeLabels(lag_days=1), always was
    "roska4_swing": "causal_d1",     # RegimeLabels(lag_days=1) as of Stage 5ZZZ-Q
    "roska4_stress": "intraday_basket_gate",   # decided at 10:30 from the session's own bars
    "roska4_calm": "causal_d1",      # the entry gate reads the previous session's label
}


def _signal_params_hash(sleeve: str) -> str:
    """The sleeve's params identity, or `""` if it cannot be computed honestly HERE.

    Never a guess and never a partial hash: a diagnostics row carrying half an identity would
    be worse than one carrying none, because a reader would compare it against a real one.

    Stage 5ZZZ-Q looked at why this has returned `""` on every live row ever written, since
    Stage 5ZZZ-P's parity checker found it empty and could only report UNKNOWN.

    The cause is a deliberate contract, not an oversight. The canonical identity is
    `track1_params.sleeve_config`, and `route_params.normalise` refuses a config that is
    missing any of its 27 fields - "an absent field is refused, not defaulted, so two configs
    cannot hash alike because one forgot to say". One of those fields is
    `data_source_identity`, which is `path:sha256` of the parquet. Hashing a multi-gigabyte
    file on every slot would put real work on the decision path for a diagnostics field, which
    is the same reason `_signal_data_identity` below records the path alone.

    So a REAL hash is not cheaply available at this call site, and a cheap one would be the
    partial identity this docstring forbids. The full `path:sha256` identity is written by the
    explanation record for the same run, and that is where a parity check should join it from.
    Returning empty here is the honest answer; `regime_basis` on the row carries the part of
    the identity this route kept getting wrong.
    """
    return ""


#: Stage 5ZZZ-Q. The regime object each sleeve hands its detector, named once so the signal row
#: and the parity checker cannot drift apart. Taken from the live call sites - and for the two
#: Normal-R4 sleeves those call sites are now identical.
SLEEVE_REGIME_BASIS = {
    "global_nkd": "causal_d1",       # RegimeLabels(lag_days=1), always was
    "roska4_swing": "causal_d1",     # RegimeLabels(lag_days=1) as of Stage 5ZZZ-Q
    "roska4_stress": "intraday_basket_gate",   # decided at 10:30 from the session's own bars
    "roska4_calm": "causal_d1",      # the entry gate reads the previous session's label
}


def _signal_regime_basis(sleeve: str) -> str:
    """Which regime object this sleeve's detector was handed.

    The field Stage 5ZZZ-P could not find and therefore had to report as UNKNOWN for the two
    sleeves whose identity turns on it. Cheap, and it is the thing that was actually wrong:
    for eight stages the signed paper identity said causal D-1 while the live Swing detector
    read the session's own label, and no row recorded either.
    """
    return SLEEVE_REGIME_BASIS.get(sleeve, "")


def _signal_data_identity(data_paths, sleeve: str) -> str:
    """The parquet the sleeve read, by path. The sha lives in the explanation record.

    Deliberately the path only. Hashing a multi-gigabyte parquet on every slot would put real
    work on the decision path for a diagnostics field, and the explanation writer already
    records the full `path:sha256` for the same run.
    """
    try:
        insts = {"roska4_calm": "MES", "roska4_stress": "MNQ",
                 "roska4_swing": "MES", "global_nkd": "MNKD"}
        return str((data_paths or {}).get(insts.get(sleeve, ""), "") or "")
    except Exception:
        return ""


def close_live_window(sleeve: str, date) -> dict:
    """Close today's window, counting only the slots that actually decided.

    Read back from the ledger rather than from memory: each slot is its own process, so the
    only place that knows what the whole window did is the file the slots wrote to.
    """
    day = str(pd.Timestamp(date).date())
    rows = wl.read_day(day) if hasattr(wl, "read_day") else []
    mine = [r for r in rows if r.get("sleeve") == sleeve and str(r.get("date")) == day
            and r.get("event") == wl.SLOT_OBSERVED]
    decided = [r for r in mine if r.get("decided")]
    entered = any(r.get("entered") for r in decided)
    wl.window_closed(sleeve, day, len(decided), route_hint=ROUTE,
                     signal=wl.ENTERED if entered else wl.NO_SIGNAL,
                     slots_ran=len(mine), slots_decided=len(decided))
    return {"sleeve": sleeve, "date": day, "slots_ran": len(mine),
            "slots_decided": len(decided), "expected": wl.expected_slots(sleeve)}


def last_complete_day(df) -> "pd.Timestamp | None":
    """The newest day this parquet is COMPLETE for, tz-naive, or None.

    Stage 5ZK, and it is the whole reason a checkpoint written at the window close cannot
    simply claim the cut day. Measured 2026-08-26 on the live store: the daily append runs at
    13:45 ET, so at the 15:55 close the parquet holds today only up to 13:44 while YESTERDAY
    runs to 23:59. The next append backfills today's afternoon — which sits below the cut a
    fingerprint through today would use, so that fingerprint changes and every later resume is
    refused with `fingerprint_rowcount`. Measured both ways, on MES and MNKD:

        fingerprint(parquet, newest stored day)  stable after the next append: False
        fingerprint(parquet, previous day)       stable after the next append: True

    So the newest stored day is the one still being filled, and the day before it is the last
    one whose history has stopped moving. Derived from the data rather than from the clock: on
    a day the append has already completed, the same rule still names a day that is finished.

    A checkpoint that names this day is honest — "as of the close of this day the engine held
    X, and here is the history that produced it" — and the replay resumes from there and
    re-runs the days after it. Naming the cut day instead would be a claim the parquet cannot
    support at the moment the claim is made.
    """
    if df is None or len(df) == 0:
        return None
    idx = pd.DatetimeIndex(df.index)
    days = idx.normalize().unique().sort_values()
    if len(days) < 2:
        return None
    prev = pd.Timestamp(days[-2])
    return prev.tz_localize(None) if prev.tz is not None else prev


def checkpoint_frames(data_paths: dict, insts=None) -> "tuple[dict, dict]":
    """`({inst: parquet frame}, {inst: why not})` for the cross-day instruments.

    The parquet, not the joined live frame — and the reason is narrower than it first looked,
    so it is worth stating accurately rather than dramatically.

    Legacy's resume path fingerprints the parquet and says why in a comment earned the hard
    way: *"validity is checked against the PARQUET, not the spliced frame; splicing leaves
    that history the same length but not the same hash."* That is true THROUGH THE CUT DAY,
    and it reproduces here — one appended bar changes the fingerprint. But `last_complete_day`
    puts the cut a day earlier, and below that cut the two frames hold the same bars, so
    measured, they hash identically. Reusing the frames already in the slot's memory would
    therefore have worked.

    Reloading is a choice, made for three reasons rather than a necessity:
      * the parquet is what the resume path reads, so fingerprinting it is the contract
        directly rather than by an argument about what the join does or does not touch;
      * the closing slot holds only ITS OWN sleeve's instruments — `sleeve_frames` is called
        with one sleeve — so reuse would checkpoint four instruments at the Swing close and
        one at the NKD close, and never all five from one place;
      * it costs 2.7–3.0s for all five (2.0M–3.4M rows each; ~0.1s to read, ~0.5s to
        fingerprint), measured three times on the live store, against 221s of headroom under
        the 300s slot ceiling — and it lands on ONE slot per sleeve, at the close.

    If the join ever starts rewriting history below the cut, reuse stops being equivalent and
    this becomes the only correct option. Stage 5ZK pins that with a test.

    Read-only. A frame that cannot be loaded is reported by name rather than raised: a
    checkpoint writer must not be able to stop a window from closing, and the missing entry is
    caught downstream by the open-book guard.
    """
    from global_index import route_checkpoint as rc
    from futures._validated_core import load_parquet

    want = tuple(insts) if insts is not None else tuple(sorted(
        {i for s in rc.CHECKPOINTED_SLEEVES for i in tp.SLEEVE_INSTRUMENTS.get(s, ())}))
    frames, why = {}, {}
    for inst in want:
        path = (data_paths or {}).get(inst)
        if not path:
            why[inst] = "no data path"
            continue
        try:
            frames[inst] = load_parquet(str(path))
        except Exception as exc:                               # noqa: BLE001
            why[inst] = f"{type(exc).__name__}: {exc}"
    return frames, why


def _carry_forward_book(book_path: str, now_et) -> "tuple[dict, str | None]":
    """The route's current book, restamped for this cut — or a fresh flat one if none exists.

    Stage 5ZN. Returns `(state, carried_from)` where `carried_from` names the file the
    positions came from, or None when the book is being created for the first time. The
    distinction is reported rather than inferred: "flat because it has always been flat" and
    "flat because we just read a flat book" are different facts, and once paper starts only
    one of them is safe to write over.

    Refuses on an unreadable book. A window close must not be able to erase a position by
    failing to parse the file that records it.
    """
    import json as _json

    p = Path(book_path)
    cut = pd.Timestamp(now_et)
    fresh = {"schema_version": 2, "route": ROUTE, "window": "live",
             "cut_instant": cut.isoformat(), "equity": 0.0,
             "cur_day": str(cut.date()), "peak_equity": 0.0, "day_start_equity": 0.0,
             "positions": [], "booked_counter": {}, "counters": {}}
    if not p.exists():
        return fresh, None
    try:
        prev = _json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(prev, dict):
            raise ValueError("book is not an object")
        # Stage 5ZS. `route is None` used to PASS this check, and that is how a book written
        # by a legacy-shaped writer was accepted in silence. Measured 2026-08-26 09:31 ET:
        # the Track 1 max-hold sweep rewrote this file as schema 1 with no route at all, and
        # nothing here objected. An unstamped book at the route's own path is not "a book
        # that forgot to say" — it is a book something else wrote.
        route = prev.get("route")
        if str(route) != ROUTE:
            raise ValueError(
                f"book is stamped route={route!r}, not {ROUTE!r}. A book at the route's own "
                f"path that does not name the route was written by something else")
        schema = prev.get("schema_version")
        if int(schema or 0) != BOOK_SCHEMA:
            raise ValueError(
                f"book carries schema_version={schema!r}, not {BOOK_SCHEMA}. A downgraded "
                f"envelope has already lost the fields this route carries across days")
        positions = prev.get("positions")
        if positions is None or not isinstance(positions, list):
            raise ValueError("book carries no positions list")
    except Exception as exc:                                   # noqa: BLE001
        raise RuntimeError(
            f"{p} exists and could not be read ({type(exc).__name__}: {exc}); refusing to "
            f"write a book over it. An unreadable book is not an empty one, and a window "
            f"close that erased a real position would be unrecoverable") from exc

    # Stage 5ZS. `dict(prev)` copied EVERY key, so a legacy `breaker` block — peak_equity
    # 50000.0, last_broker_equity 996881.46, an account-scale number this route has never
    # used — travelled into the Track 1 book and would have stayed there. Only the fields
    # this schema declares are carried; anything else the file happens to hold is dropped
    # rather than inherited.
    carried = {k: prev[k] for k in fresh if k in prev}
    carried.update({"schema_version": BOOK_SCHEMA, "route": ROUTE, "window": "live",
                    "cut_instant": cut.isoformat(), "cur_day": str(cut.date()),
                    "positions": list(positions)})
    # A field the schema declares and the previous book lacked comes back at its fresh
    # default rather than absent, so a reader never has to guess which of the two it is.
    for k, v in fresh.items():
        carried.setdefault(k, v)
    return carried, str(p)


def write_route_checkpoint(sleeve: str, *, now_et, regime_csv: str,
                           data_paths: dict, book_state: dict | None = None,
                           frames: dict | None = None,
                           path: str = CHECKPOINT_PATH,
                           book_path: str = POSITIONS_PATH) -> dict:
    """Write the Track 1 route checkpoint after a window that actually completed.

    `track1_bootstrap.write` had no caller at all before this — the checkpoint format, its
    identity fingerprint and its refusal codes were all built and tested, and nothing ever
    produced one. That is why runbook precondition 6 could not turn green by running the
    scheduler, and it is the second half of the same defect as the ledger having no caller.

    Guarded rather than trusted: the caller must have closed a COMPLETE window first. A
    checkpoint written from a partial window would record a book position nobody watched being
    reached, which is the resume-from-a-state-that-never-existed failure the whole checkpoint
    identity exists to prevent.
    """
    from global_index import track1_bootstrap as boot
    from global_index import track1_normal_r4 as NR

    # Stage 5ZK. `None` means "load them"; `{}` means "deliberately none". They used to mean
    # the same thing, and that is exactly how the production call site — which passes neither —
    # wrote an empty checkpoint on every window for as long as the route has been running.
    loaded_why: dict = {}
    if frames is None:
        frames, loaded_why = checkpoint_frames(data_paths)
    last_day_by_inst = {i: d for i, d in
                        ((i, last_complete_day(f)) for i, f in frames.items())
                        if d is not None}
    # Stage 5ZN. The previous version synthesised `positions: []` whenever no book_state was
    # handed in — which is every production call. Harmless while the route holds nothing and
    # exactly wrong the moment it does: the close of a window would overwrite a book holding a
    # position with one claiming none, and the checkpoint written beside it would agree.
    #
    # So the existing book is READ and carried forward. A book that cannot be read is NOT
    # treated as an empty one; the write is refused, because "I could not read what I hold"
    # answered as "I hold nothing" is the shape that erases a real position.
    state = book_state
    carried_from = None
    if state is None:
        state, carried_from = _carry_forward_book(book_path, now_et)
    entries = boot.checkpoint_entries(state, frames=frames, regime_csv=regime_csv,
                                      data_paths=data_paths,
                                      fill_law=tp.LIVE_FILL_LAW,
                                      last_day_by_inst=last_day_by_inst)
    # `book_path` is a parameter, not the constant it was for one draft. The first version
    # hard-coded the route's live positions path, so a test that carefully redirected the
    # checkpoint still wrote real route state into the repo — caught by this stage's own
    # "must not create" assertion, which is the only reason it was noticed.
    boot.write(state, entries=entries, book_path=book_path, checkpoint_path=path)
    return {"path": path, "book_path": book_path, "sleeve": sleeve,
            "sleeves": sorted(entries), "cut_instant": state["cut_instant"],
            # Stage 5ZK: what the checkpoint actually got, so a caller printing this line can
            # tell an empty checkpoint that was CORRECT from one that was empty because a
            # frame did not load. `sleeves` alone could not distinguish them.
            "instruments": sorted({i for per in entries.values() for i in per}),
            "entry_count": sum(len(per) for per in entries.values()),
            "last_day_by_inst": {i: str(d.date()) for i, d in last_day_by_inst.items()},
            "frames_unavailable": loaded_why,
            # Stage 5ZN: where the positions came from. None means the book was created here;
            # a path means an existing book was read and carried forward.
            "book_carried_from": carried_from,
            "positions_carried": len(state.get("positions") or [])}


def default_data_paths() -> dict:
    from futures.basket import BASKET, data_filename
    paths = {n: f"data/cache/futures/{data_filename(c)}" for n, c in BASKET.items()}
    paths["MNKD"] = "global_index/data/NKD_continuous_1m_8y.parquet"
    return paths


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def book_state(book, *, window: str) -> dict:
    """The route's book, in the shape a resume would have to rebuild.

    Deliberately the same set of carried values Stage 2C proved load-bearing — open
    positions with their cluster and risk, equity, the breaker's peak and day-start, and the
    current day. `booked` travels too, but as a double-settlement COUNTER and never as an
    admission input; Stage 2C mutated it and the match was a control, not a gap.
    """
    br = book.breaker
    return {
        "schema_version": 1,
        "route": ROUTE,
        "window": window,
        "equity": round(float(book.equity), 6),
        "cur_day": str(book.cur_day.date()) if book.cur_day is not None else None,
        "peak_equity": (round(float(br.peak_equity), 6) if br is not None else None),
        "day_start_equity": (round(float(br._day_start_equity), 6)
                             if br is not None and br._day_start_equity is not None else None),
        "positions": [
            {"trade_id": h.candidate.trade_id, "sleeve": h.candidate.sleeve,
             "instrument": h.candidate.instrument, "direction": h.candidate.direction,
             "qty": int(h.candidate.qty),
             "risk_dollars": round(float(h.candidate.risk_dollars), 6),
             "entry_time": str(h.candidate.entry_time),
             "exit_time": str(h.candidate.exit_time) if h.candidate.exit_time else None,
             "entry_price": h.candidate.entry_price,
             "stop_price": h.candidate.stop_price}
            for h in book.open_book
        ],
        "booked_counter": {k: v for k, v in book.booked.items() if v > 1},
        "counters": {k: v for k, v in book.counters.items() if v},
    }


# ── explanation emission (Stage 5Y) ──────────────────────────────────────────
#
# One audit record per shadow DECISION, written beside the existing decision file and never
# instead of it. `shadow_decisions_<window>.jsonl` keeps the exact shape it has always had:
# anything reading it today keeps working, and the comparison "one explanation per decision"
# stays checkable because the two files are produced from the same list in the same pass.
#
# Where the records go, and why not one file per run
# --------------------------------------------------
# Grouped by each record's OWN session date, one file per date. A replay window spans many
# historical sessions — 139 decisions across 75 dates on vault2026, 183 across 104 on
# vault2025, both measured — so naming one file after the run date would produce
# `explanations_20260823.jsonl` holding rows from 2026-01-02 onward. This repository has
# already paid for exactly that: a scheduler log named for the day the process started
# collected the next day's slots, and looking for last night's window in last night's file
# found it empty, which reads exactly like the window never ran. A file named for a date it
# does not contain is a trap, so the date in the name is always the date in the rows.
#
# Windows get their own sub-directory because two windows can cover the same calendar date
# and neither should silently overwrite the other's evidence.
EXPLAIN_SUBDIR = "explanations"

#: Verdict -> (status, rule ids). Every verb `track1_signal_layer` can return needs a row,
#: and `test_every_signal_layer_verdict_has_an_explanation_mapping` fails when one does not
#: — a new verdict must announce itself rather than fall through to a default that quietly
#: mislabels it.
EXPLAIN_VERDICT_MAP: dict = {
    # The accepted proof set is DERIVED from the registry per mode, never retyped here.
    # Stage 5Z made it mode-dependent — replay does not cite the freshness gate — and a
    # second copy of that decision in this file is exactly the drift the registry exists to
    # remove. `_rules_for` reads it; this entry is a placeholder that must never be used
    # directly, and `_rules_for` asserts as much.
    sl.TAKE:                 (tx.ACCEPTED, ()),
    sl.REJECT_CAP:           (tx.REJECTED, ("GATE.CAP_CLUSTER",)),
    sl.REJECT_FAMILY_CAP:    (tx.REJECTED, ("GATE.CAP_FAMILY",)),
    sl.SUPPRESS_SAME_SYMBOL: (tx.REJECTED, ("GATE.SAME_SYMBOL",)),
    sl.SUPPRESS_SAME_SLEEVE: (tx.REJECTED, ("GATE.SAME_SLEEVE",)),
    sl.REJECT_WINDOW:        (tx.REJECTED, ("GATE.WINDOW",)),
    sl.HALT_BREAKER:         (tx.REJECTED, ("GATE.BREAKER",)),
}

class DecisionModeMismatch(RuntimeError):
    """A caller named a decision mode that contradicts the source it asked to run.

    Refused rather than resolved. The two are not opinions about the same thing: the source
    decides what the run READS, and the mode decides what an accepted decision has to PROVE.
    Silently preferring one would either bind a replay to today's freshness or — the direction
    that actually mattered — let a live run stamp `replay` and stop binding at all.
    """


#: source -> the mode it may be run under. `live` resolves to one of two, on the gate.
SOURCE_MODES: dict = {
    "replay": (tx.REPLAY,),
    "live": (tx.SHADOW_LIVE, tx.ARMED),
    "live-shadow": (tx.SHADOW_LIVE, tx.ARMED),
}


def decision_mode_for(source_name: str, order_gate=None) -> str:
    """The one decision mode a given source and gate state may record under.

    Pure, and total over the sources the CLI accepts:

        replay                          -> replay        (freshness is run CONTEXT)
        live / live-shadow, not armed   -> shadow_live    (freshness BINDS)
        live / live-shadow, armed       -> armed          (freshness BINDS)

    This exists because `run_shadow` used to take `source_name` and `mode` as two independent
    arguments with independent defaults, and `main()` passed only the first. A run started with
    `--source live` therefore recorded `decision_mode="replay"`, and since binding is decided by
    the mode, the freshness gate quietly stopped binding on the one kind of run where it must.
    Deriving it removes the possibility rather than documenting it.
    """
    allowed = SOURCE_MODES.get(str(source_name))
    if allowed is None:
        raise ValueError(f"unknown source {source_name!r}; known: {sorted(SOURCE_MODES)}")
    if allowed == (tx.REPLAY,):
        return tx.REPLAY
    return tx.ARMED if bool(getattr(order_gate, "allow_orders", False)) else tx.SHADOW_LIVE


def resolve_decision_mode(source_name: str, order_gate=None,
                          mode: "str | None" = None) -> str:
    """`decision_mode_for`, plus a refusal when a caller insists on a different one."""
    derived = decision_mode_for(source_name, order_gate)
    if mode is None or mode == derived:
        return derived
    if mode not in tx.DECISION_MODES:
        raise ValueError(f"mode must be one of {tx.DECISION_MODES}, got {mode!r}")
    raise DecisionModeMismatch(
        f"source {source_name!r} with gate "
        f"{getattr(order_gate, 'state', 'shadow')!r} runs as {derived!r}, but {mode!r} was "
        f"asked for. Binding is decided by the mode, so accepting this would change whether "
        f"the freshness gate has to hold — pass the source you mean instead.")


def _rules_for(verdict: str, mode: str) -> tuple:
    """(status, rule ids) for one verdict in one mode.

    An accepted decision's proof set comes from `track1_explain.ACCEPTED_PROOF_RULES_BY_MODE`
    so that the route and the validator cannot disagree about what a mode owes. Rejections
    are mode-independent: a cap refusal is a cap refusal whoever asked.
    """
    if verdict not in EXPLAIN_VERDICT_MAP:
        raise KeyError(
            f"verdict {verdict!r} has no explanation mapping. Refused rather than "
            f"defaulted: a verdict silently filed under the wrong status is worse than a "
            f"run that stops and says which verb is new.")
    if mode not in tx.DECISION_MODES:
        raise ValueError(f"mode must be one of {tx.DECISION_MODES}, got {mode!r}")
    status, rules = EXPLAIN_VERDICT_MAP[verdict]
    if status == tx.ACCEPTED:
        assert rules == (), "the accepted proof set is derived per mode, not written here"
        return status, tuple(tx.ACCEPTED_PROOF_RULES_BY_MODE[mode])
    return status, rules


#: Features the shadow route cannot fill with a real number today, and why. NOT filled with
#: a plausible figure: `MultiClusterGuard.admits` returns `(True, "ok")` on success and a
#: PRE-FORMATTED sentence rounded to one decimal on failure, and the book has moved on by
#: the time the decision list is written. The only honest ways to get these are to capture
#: them inside the admission loop — an engine change this stage is not authorised to make —
#: or to parse the sentence, which is the regex-over-prose failure this route's own audit
#: flagged. So they travel as absent values that say why, they are COUNTED into the run
#: summary, and `test_the_unmeasured_features_are_declared_and_counted` fails if the count
#: silently drops to zero.
EXPLAIN_UNMEASURED: dict = {
    "cluster_gross_after":
        "not captured: MultiClusterGuard.admits returns no number on success and a "
        "one-decimal sentence on failure; capturing it needs a hook inside the admission "
        "loop (Stage 5Z)",
    "family_gross":
        "not captured: family_verdict returns the same shape as the cluster guard "
        "(Stage 5Z)",
    "held_by_clusters":
        "not captured: the blocking clusters are named only inside the refusal sentence "
        "and the book has moved on by write time (Stage 5Z)",
}


def _explain_identity(sleeve: str, inst: str, *, regime_csv: str, data_paths: dict,
                      fill_law: str, commit: str | None, cache: dict) -> "tx.Identity":
    """Route/params/data identity for one sleeve+instrument, hashed once per pair.

    `sleeve_identity` is the SAME helper `checkpoint_report` uses, so a decision and the
    checkpoint that would resume it cannot disagree about which configuration produced
    them. Measured at ~0.05s per pair, which is why it is cached: paying it per decision
    would be ~7s of re-hashing the same five parquets.
    """
    key = (sleeve, inst)
    if key not in cache:
        data_path = data_paths.get(inst) or ""
        _readable, phash = tp.sleeve_identity(sleeve, inst, regime_csv=regime_csv,
                                              data_path=data_path, fill_law=fill_law)
        cache[key] = tx.Identity(
            route=ROUTE, params_hash=phash, fill_law=fill_law,
            data_source_identity=tp.file_identity(data_path) if data_path else "",
            regime_csv_identity=tp.file_identity(regime_csv), git_commit=commit)
    return cache[key]


def _explain_features(verdict: str, cand, *, freshness_allow: bool,
                      mode: str = tx.REPLAY) -> list:
    """Every feature the cited rules require, with real values wherever one exists.

    What is real here, and provably so:

    - `freshness_allow` is the verdict `fresh.evaluate` returned for this run.
    - `allow_new_entries` is derived from the decision itself, not guessed:
      `Track1Book.evaluate` returns HALT_BREAKER before looking at anything else, so any
      other verdict is proof the breaker allowed new risk.
    - `decision_hhmm` uses `_hhmm_on`, the same function the window gate compares against,
      so the value in the record is the value the rule saw.
    - `held_by_same_sleeve` is asserted BY the verdict: SUPPRESS_SAME_SLEEVE is returned
      only when that sleeve already holds the instrument.

    What is absent travels as `value=None` with a `source` naming why — see
    EXPLAIN_UNMEASURED. An absent value is never dressed up as a measured one.
    """
    status, rule_ids = _rules_for(verdict, mode)
    caps = tp.CAPS.get(cand.sleeve, (None, None))
    feats: list = []
    for rid in rule_ids:
        for name in tx.RULES[rid].features:
            if name in EXPLAIN_UNMEASURED:
                threshold = {"cluster_gross_after": caps[0],
                             "family_gross": tp.FAMILY_GROSS,
                             "held_by_clusters": "no other sleeve holds it"}[name]
                feats.append(tx.Feature(name, None, threshold, "<=",
                                        passed=(status == tx.ACCEPTED),
                                        source=EXPLAIN_UNMEASURED[name]))
            elif name == "freshness_allow":
                feats.append(tx.Feature(name, bool(freshness_allow), True, "==",
                                        passed=bool(freshness_allow),
                                        source="track1_freshness.evaluate for this run"))
            elif name == "allow_new_entries":
                allowed = verdict != sl.HALT_BREAKER
                feats.append(tx.Feature(name, allowed, True, "==", passed=allowed,
                                        source="derived from the verdict: evaluate() "
                                               "returns HALT_BREAKER before any other "
                                               "check, so any other verdict proves the "
                                               "breaker allowed new risk"))
            elif name == "decision_hhmm":
                # The SAME window and clock the gate compares against — Stage 5N: for a
                # session-clock sleeve (NKD) that is SESSION_WINDOWS on its own clock, not
                # the ET slot band. An explanation that read a different window from the
                # verdict it explains would contradict itself on every NKD row.
                lo, hi = (tp.SESSION_WINDOWS.get(cand.sleeve)
                          or WINDOWS_ET.get(cand.sleeve, ("", "")))
                clk = tp.SESSION_WINDOW_CLOCKS.get(cand.sleeve, "America/New_York")
                feats.append(tx.Feature(name, _hhmm_on(cand.entry_time, clk), f"{lo}..{hi}",
                                        "within", passed=(verdict != sl.REJECT_WINDOW),
                                        source="track1_signal_layer._hhmm_on, the same "
                                               "reading the window gate compares"))
            elif name == "held_by_same_sleeve":
                feats.append(tx.Feature(name, cand.sleeve, "no holder", "==",
                                        passed=False,
                                        source="asserted by the verdict: "
                                               "SUPPRESS_SAME_SLEEVE is returned only "
                                               "when that sleeve already holds it"))
            else:                                    # pragma: no cover - registry guard
                raise KeyError(
                    f"rule {rid!r} requires feature {name!r} and the shadow route has no "
                    f"rule for filling it. Refused rather than emitted empty: a record "
                    f"missing a required feature is the thing validate() exists to catch, "
                    f"and inventing one here would defeat it.")
    return feats


class FreshnessRefused(RuntimeError):
    """A binding mode tried to admit a candidate while the freshness gate refused."""


def explanations_for(decisions, *, regime_csv: str, data_paths: dict, fill_law: str,
                     freshness_allow: bool, commit: str | None = None,
                     mode: str = tx.REPLAY, slot_id: str = "") -> list:
    """One validated DECISION record per shadow decision, in the decisions' own order.

    Pure: builds and validates, writes nothing. `emit_explanations` does the writing, so a
    caller (and a test) can inspect the records without a filesystem.

    `mode` decides what an accepted decision has to prove, and Stage 5Z made that a real
    difference rather than a label:

    - **replay** — the freshness gate is NOT cited as a proof. It reads the machine's
      CURRENT daily inputs, which did not govern an admission that happened months ago.
      Measured: the same 2026-01-02 decision carried a PASSED freshness proof at 12:00 and
      a FAILED one at 15:00 on the same afternoon, with 91 accepted either way. The verdict
      is still recorded — as run context, on its own record, under
      `CONTEXT.FRESHNESS_OBSERVED` — so nothing is lost, only correctly labelled.
    - **shadow_live / armed** — the gate BINDS. An accepted decision must cite it and it
      must have passed, and this function REFUSES to build an accepted record when it did
      not. Refused rather than downgraded to a rejection: a candidate the engine admitted
      is not the same thing as one the engine refused, and writing the second would be
      inventing a decision that never happened.
    """
    if mode not in tx.DECISION_MODES:
        raise ValueError(f"mode must be one of {tx.DECISION_MODES}, got {mode!r}")
    binding = mode in tx.FRESHNESS_BINDING_MODES
    cache: dict = {}
    out: list = []
    for seq, d in enumerate(decisions):
        cand = d.candidate
        status, rule_ids = _rules_for(d.verdict, mode)
        if binding and status == tx.ACCEPTED and not freshness_allow:
            raise FreshnessRefused(
                f"{mode}: the freshness gate refused, yet the engine admitted "
                f"{cand.trade_id!r}. In a binding mode no accepted decision may exist "
                f"while the daily inputs are refused — bind the gate BEFORE admission "
                f"rather than recording a contradiction after it.")
        session_date = str(_day(cand.entry_time).date())
        rec = tx.decision_record(
            route=ROUTE, session_date=session_date, sleeve=cand.sleeve,
            instrument=cand.instrument, candidate_id=cand.trade_id,
            decision_time=cand.entry_time, data_time=cand.entry_time,
            status=status, reason_code=d.verdict, rule_ids=list(rule_ids),
            decision_mode=mode,
            features=_explain_features(d.verdict, cand,
                                       freshness_allow=freshness_allow, mode=mode),
            thresholds={"cluster_gross_cap": tp.CAPS.get(cand.sleeve, (None,))[0],
                        "cluster_net_cap": tp.CAPS.get(cand.sleeve, (None, None))[1],
                        "family_gross_cap": tp.FAMILY_GROSS,
                        "family_net_cap": tp.FAMILY_NET,
                        "account": ACCOUNT},
            inputs_summary={"decision_mode": mode, "regime_csv": regime_csv,
                            "data_path": data_paths.get(cand.instrument),
                            "candidate_source": cand.source or None,
                            "freshness_allow": bool(freshness_allow)},
            outputs={"direction": cand.direction, "qty": int(cand.qty),
                     "entry_basis": cand.source or "replay_row",
                     "entry_price": cand.entry_price,
                     "stop_basis": tp.sleeve_config(
                         cand.sleeve, cand.instrument, regime_csv=regime_csv,
                         data_path=data_paths.get(cand.instrument) or "",
                         fill_law=fill_law)["stop_basis"],
                     "stop_price": cand.stop_price,
                     "risk_dollars": round(float(cand.risk_dollars), 4),
                     "cap_bucket": cand.sleeve},
            rejection=({"verdict": d.verdict, "detail": d.detail,
                        "forced_closes": [f.held.candidate.trade_id
                                          for f in d.forced_closes]}
                       if status == tx.REJECTED else None),
            identity=_explain_identity(cand.sleeve, cand.instrument,
                                       regime_csv=regime_csv, data_paths=data_paths,
                                       fill_law=fill_law, commit=commit, cache=cache),
            stage="shadow_admission", sequence=seq)
        tx.check(rec)          # raises; nothing invalid may reach the file
        out.append(rec)
    return out


def emit_explanations(decisions, *, out_dir: str, window: str, regime_csv: str,
                      data_paths: dict, fill_law: str, freshness_allow: bool,
                      root: str = ".", mode: str = tx.REPLAY, as_of=None,
                      context_sleeve: str = "roska4_swing", slot_id: str = "") -> dict:
    """Build, validate and write the explanation rows. Returns what it did.

    The first batch for a given date TRUNCATES and later batches append, so re-running a
    window replaces its evidence instead of doubling it — the decision file beside it is
    opened with `"w"` and the two counts have to stay comparable.
    """
    target = f"{out_dir}/{EXPLAIN_SUBDIR}/{window}"
    # Check the destination BEFORE building anything, not as a side effect of writing. A
    # window that produced no decisions would otherwise never resolve the path at all, so a
    # run aimed at a legacy directory would pass quietly and only write there on the first
    # pass that happened to have rows. Raises ShadowPathRefused. Public form of the bound
    # since Stage 5Z — the route no longer reaches into a private helper for it.
    resolved = tx.resolve_shadow_dir(target, root)

    commit = tx.git_commit(root)
    records = explanations_for(decisions, regime_csv=regime_csv, data_paths=data_paths,
                               fill_law=fill_law, freshness_allow=freshness_allow,
                               commit=commit, mode=mode, slot_id=slot_id)
    # The freshness verdict, recorded once per run as CONTEXT rather than as a decision
    # proof. This is where the replay reading goes now that accepted replay decisions no
    # longer cite the gate: still written, still auditable, and no longer claiming to
    # testify about an admission it did not govern. Emitted even when the run produced no
    # decisions at all — "the gate was read and said X" is a fact about the run, and a run
    # that recorded nothing is indistinguishable from a run that never happened.
    context = tx.no_action_record(
        route=ROUTE, session_date=str(pd.Timestamp(as_of).date()) if as_of else
                     (sorted({r["session_date"] for r in records})[-1] if records
                      else str(pd.Timestamp.now(tz="UTC").date())),
        sleeve=context_sleeve, instrument=tp.SLEEVE_INSTRUMENTS[context_sleeve][0],
        candidate_id=f"run:{window}", decision_time=as_of, decision_mode=mode,
        reason_code=(tx.NONE if freshness_allow else tx.FRESHNESS_FAIL),
        rule_ids=["CONTEXT.FRESHNESS_OBSERVED"],
        features=[tx.Feature("freshness_allow", bool(freshness_allow), True, "==",
                             passed=bool(freshness_allow),
                             source="track1_freshness.evaluate for this run; NON-BINDING "
                                    "in replay because it reads the machine's current "
                                    "daily inputs, not the ones that governed a "
                                    "historical admission")],
        inputs_summary={"window": window, "mode": mode, "regime_csv": regime_csv,
                        "binding": mode in tx.FRESHNESS_BINDING_MODES,
                        # Stage 5Q-2. The directory already says which slot wrote this, but a
                        # row that is read out of its directory — copied into a report, pasted
                        # into a ticket — keeps its provenance only if it carries it.
                        "slot_id": slot_id or None},
        outputs={}, identity=_explain_identity(
            context_sleeve, tp.SLEEVE_INSTRUMENTS[context_sleeve][0],
            regime_csv=regime_csv, data_paths=data_paths, fill_law=fill_law,
            commit=commit, cache={}))
    tx.check(context)

    by_date: dict = {}
    for rec in records + [context]:
        by_date.setdefault(rec["session_date"], []).append(rec)
    written = []
    for day in sorted(by_date):
        written.append(str(tx.write_shadow(by_date[day], session_date=day,
                                           out_dir=target, root=root, mode="w")))
    unmeasured: dict = {}
    # An ACCEPTED decision whose own proof feature says it FAILED. Counted rather than
    # smoothed over: the first real run produced 91 of them, because `fresh.evaluate` is
    # computed in `run_shadow` and reported in the summary but never gates the replay —
    # nothing consults `verdict.allow` before `run_candidates`. For a replay of a historical
    # window that may well be right; today's regime CSV being a day short says nothing about
    # January. But the record is not the place to decide that, so it states the
    # contradiction and this counter makes it a number somebody has to look at.
    contradicted: dict = {}
    for rec in records:
        for f in rec["feature_snapshot"]:
            if f["value"] is None:
                unmeasured[f["name"]] = unmeasured.get(f["name"], 0) + 1
            if rec["status"] == tx.ACCEPTED and f["passed"] is False:
                contradicted[f["name"]] = contradicted.get(f["name"], 0) + 1
    return {"records": len(records), "files": len(written), "dir": target,
            # Explicit, and present even at zero. "explanations_written: 0" beside a
            # resolved destination is a run that had nothing to say; a MISSING field is a
            # run nobody can tell apart from one that never emitted at all.
            "explanations_written": len(records),
            "context_records": 1,
            "rows_written": len(records) + 1,
            "destination_resolved": str(resolved),
            "mode": mode,
            "freshness_binding": mode in tx.FRESHNESS_BINDING_MODES,
            "freshness_allow": bool(freshness_allow),
            "session_dates": len(by_date),
            "unmeasured_features": dict(sorted(unmeasured.items())),
            "unmeasured_total": sum(unmeasured.values()),
            "accepted_with_failed_proof": dict(sorted(contradicted.items())),
            "accepted_with_failed_proof_total": sum(contradicted.values())}


def run_shadow(*, window: str, source_name: str = "replay", regime_csv: str,
               now_et=None, out_dir: str = SHADOW_DIR, order_gate: OrderGate | None = None,
               ledger: bool = True, persist_book: bool = False,
               positions_path: str = POSITIONS_PATH,
               explain: bool = True, root: str = ".",
               mode: "str | None" = None) -> dict:
    """One shadow pass over a measured window. Returns the summary that is also written out.

    Nothing here can trade. The broker handed to the route is `NoOrderBroker`, whose
    `send_order` raises; the summary records that it was never called.
    """
    gate = order_gate if order_gate is not None else OrderGate(False)
    # Derived from the source and the gate, never defaulted independently of them. `mode=` is
    # still accepted so a caller can be explicit, and a caller who is explicitly WRONG is
    # refused by name rather than quietly overruled.
    mode = resolve_decision_mode(source_name, gate, mode)
    broker = NoOrderBroker()
    data_paths = default_data_paths()
    # ONE reading of the fill law for this run. The summary reports it and the explanation
    # identity hashes it, and those two must be the same string: an identity naming a law
    # the run did not use is the exact defect Stage 4B removed from track1_params, and a
    # second reading here would be a second place for it to come back.
    #
    # Stage 5M-1: read from `track1_params.LIVE_FILL_LAW`, not from the engine dataclass. The
    # route's law is a route decision; taking it from `NormalR4Params()` meant the identity
    # followed whatever the engine's default happened to be, and that default was the ARTIFACT
    # law — so every shadow record this route has written names a law the live engine does not
    # run. Immaterial in P&L, $0 to +$6 over seven years. Not immaterial in a hash a
    # checkpoint is accepted or refused on.
    law = tp.LIVE_FILL_LAW

    kill_switch = Path(STOP_FILE).exists()

    verdict = fresh.evaluate(
        now_et=now_et if now_et is not None else pd.Timestamp.now(tz="America/New_York"),
        regime_csv=regime_csv, parquets=data_paths)

    ck = checkpoint_report(regime_csv=regime_csv, data_paths=data_paths,
                           fill_law=law)

    src = sleeves.load_source(source_name)
    cands = src.candidates(window)
    valuer = src.early_exit_valuer(window)

    # The window ledger is deliberately NOT driven from a replay. Its whole contract is
    # "did an observation happen at all", and a replay of a measured window cannot testify
    # to that: it only knows the days a trade existed, not the days the window was watched
    # and produced nothing. Emitting `window_closed` here would manufacture exactly the
    # evidence the ledger exists to withhold. `record_window_observation` below is the
    # entry the live path will call, and it is tested directly.
    ledger_note = ("not driven: a replay cannot testify to observation"
                   if ledger else "disabled by caller")

    book = Track1Book(guard=make_guard(), breaker=CircuitBreaker(account=ACCOUNT),
                      enforce_windows=True)
    settlements, decisions = run_candidates(cands, book=book, early_exit_value=valuer)

    daily = daily_series(settlements)
    summary = {
        "route": ROUTE,
        "window": window,
        "source": source_name,
        "fill_law": law,
        "order_gate": gate.as_dict(),
        "send_order_calls": sum(1 for c in broker.calls if c[0] == "send_order"),
        "kill_switch_present": kill_switch,
        "window_ledger": ledger_note,
        "freshness": verdict.as_dict(),
        "checkpoint": ck,
        "candidates": len(cands),
        "settlements": len(settlements),
        "net": round(float(daily.sum()), 2) if len(daily) else 0.0,
        "days": int(len(daily)),
        "equity_end": round(float(book.equity), 2),
        "counters": {k: v for k, v in book.counters.items() if v},
        "open_at_end": [
            {"trade_id": h.candidate.trade_id, "sleeve": h.candidate.sleeve,
             "inst": h.candidate.instrument, "direction": h.candidate.direction,
             "qty": h.candidate.qty, "risk": round(h.candidate.risk_dollars, 2)}
            for h in book.open_book
        ],
        "state_paths": {
            "positions": POSITIONS_PATH, "lock": LOCK_PATH,
            "checkpoint": CHECKPOINT_PATH, "kill_switch": STOP_FILE,
            "shadow_dir": out_dir,
        },
    }

    # `root` relocates EVERYTHING this run writes, not just the explanations. A test that
    # moved only half the output would leave the other half landing in the real
    # scratch/track1_shadow, and a suite that writes into the directory it is auditing
    # cannot tell its own output from the route's.
    out = Path(out_dir) if Path(out_dir).is_absolute() else Path(root) / out_dir
    state = book_state(book, window=window)
    summary["book_state_positions"] = len(state["positions"])
    # Off by default. A replay's end-state book is a book as of the END OF A HISTORICAL
    # WINDOW, and writing that to a path that reads like a live position file is how a
    # misleading artifact gets created and then believed. When it is asked for, it goes to
    # the ROUTE's path and never to legacy's — which is the property the test pins.
    summary["book_persisted_to"] = None
    if persist_book:
        _write_json(Path(positions_path), state)
        summary["book_persisted_to"] = str(positions_path)
    _write_json(out / f"book_state_{window}.json", state)
    _write_json(out / f"shadow_summary_{window}.json", summary)
    with open(out / f"shadow_decisions_{window}.jsonl", "w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps({
                "ts": str(d.candidate.entry_time), "trade_id": d.candidate.trade_id,
                "sleeve": d.candidate.sleeve, "inst": d.candidate.instrument,
                "direction": d.candidate.direction, "qty": d.candidate.qty,
                "risk": round(d.candidate.risk_dollars, 4),
                "verdict": d.verdict, "detail": d.detail,
                "forced_closes": [f.held.candidate.trade_id for f in d.forced_closes],
            }, default=str) + "\n")
    with open(out / f"shadow_settlements_{window}.jsonl", "w", encoding="utf-8") as fh:
        for s in settlements:
            fh.write(json.dumps(asdict(s), default=str) + "\n")

    # Stage 5Y. Written AFTER the decision file and from the SAME list, so "one explanation
    # per decision" is a property of one pass rather than of two producers that have to be
    # kept in step. The decision file above is untouched by this: whatever reads it today
    # keeps reading exactly what it read before.
    #
    # `explain=False` exists for the tests that fingerprint legacy paths and for anyone who
    # wants the old artifacts alone. It is not a fallback for failure: an invalid record
    # RAISES, because a shadow run that quietly wrote no explanations would be
    # indistinguishable from one that had nothing to explain — the same conflation this
    # route's audit found on the live dashboard.
    summary["explanations"] = None
    if explain:
        try:
            summary["explanations"] = emit_explanations(
                decisions, out_dir=out_dir, window=window, regime_csv=regime_csv,
                data_paths=data_paths, fill_law=law, freshness_allow=bool(verdict.allow),
                root=root, mode=mode, as_of=now_et)
            summary["explanations"]["written"] = True
        except tx.ShadowPathRefused as exc:
            # A caller may point `out_dir` anywhere — the Stage 3 route tests aim it at a
            # pytest temp directory precisely to prove a run touches nothing real, and that
            # contract predates this stage and stays. The explanation writer has a stricter
            # bound and cannot know that directory is harmless, so the two conflict.
            #
            # Resolved by SAYING SO rather than by loosening the bound or by silence. The
            # summary records that explanations were skipped and why, so "no explanations"
            # can never be mistaken for "nothing to explain" — the same conflation this
            # route's own dashboard audit found and named. `root=` is the supported way to
            # relocate a whole run, and it moves the shadow root with it.
            if out_dir == SHADOW_DIR:
                raise      # the route's own directory must always be writable
            summary["explanations"] = {
                "written": False, "records": 0, "decisions": len(decisions),
                "skipped": f"out_dir was redirected to {out_dir!r}, which is outside "
                           f"{tx.SHADOW_ROOT}. Explanations are NOT written there. Pass "
                           f"root=<dir> instead — it relocates the shadow root too.",
                "refusal": str(exc).split(".")[0],
            }
        summary["explanations"]["decisions"] = len(decisions)
        _write_json(out / f"shadow_summary_{window}.json", summary)
    return summary


def main(argv=None) -> int:
    # Before argument parsing, so a slot that dies on its own argv still leaves a record that
    # it started. `begin` registers an atexit emitter, so no `finally` here can be forgotten.
    _tel.begin()
    ap = argparse.ArgumentParser(
        description="Track 1 route — SHADOW ONLY. Places no orders and touches no legacy path.")
    ap.add_argument("--window", default="vault2026",
                    help="measured window to replay (floor | vault2025 | vault2026)")
    ap.add_argument("--source", default="replay", choices=["replay", "live", "live-shadow"],
                    help="replay = re-run a measured window (produces NO window coverage, by "
                         "design: a replay cannot testify that anyone looked at today). "
                         "live-shadow = observe today's window and write the ledger row this "
                         "slot is entitled to; places no orders. 'live' is the candidate "
                         "source and is not implemented yet.")
    # DERIVED from the window table, not listed. It was listed until Stage 5M-C, and the list
    # still said Calm and Stress after Stage 5M-B added 23 Normal-R4 slots — so the scheduler
    # was building an argv that argparse would reject, and every swing slot would have failed
    # at parse time, every day, before any of the route ran.
    #
    # It was not caught by the Stage 5M-B suite because those tests called `observe_live_slot`
    # directly. The captured argv was correct; nothing drove it through `main()`. A hard-coded
    # list next to a derived caller is the same drift the slot count had, one layer down.
    ap.add_argument("--sleeve", default=None,
                    choices=[None, *sorted(tp.WINDOWS_ET)],
                    help="which detection window this slot belongs to (live-shadow only)")
    ap.add_argument("--slot-id", default=None,
                    help="the slot firing now, e.g. TRACK1_STRESS_1035 (live-shadow only)")
    ap.add_argument("--bar-provider", default="none", choices=["none", "ibkr"],
                    help="where today's bars come from (live-shadow only). 'none' is the "
                         "default so a manual run cannot open IBKR by accident; the scheduler "
                         "passes 'ibkr'. Data only — orders stay governed by the order gate.")
    # Stage 5ZX. Which half of a split sleeve's evidence this slot produces. The choices are
    # NOT derived from the phase table: a typo has to be refused at argument-parse time, before
    # a process connects to anything, rather than three layers down where the refusal would be
    # one more ledger row nobody reads.
    ap.add_argument("--phase", default="", choices=["", "DECIDE", "OBSERVE"],
                    help="the evidence phase this slot produces (Calm only, live-shadow "
                         "only). Empty means the sleeve is not split and gates as it always "
                         "did. Never sends an order in any phase.")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--out-dir", default=SHADOW_DIR)
    ap.add_argument("--as-of", default=None,
                    help="ET instant the freshness gate is evaluated at (default: now)")
    ap.add_argument("--persist-book", action="store_true",
                    help=f"also write the end-state book to {POSITIONS_PATH} (the ROUTE's "
                         f"path, never legacy's). Off by default: a replay's end state is a "
                         f"book as of a historical window, not a live one.")
    ap.add_argument("--allow-orders", action="store_true",
                    help="request order sending. REFUSED while any Stage 2D blocker is open, "
                         "and also requires TRACK1_ORDERS_APPROVED=1 in the environment.")
    a = ap.parse_args(argv)

    gate = OrderGate(a.allow_orders)
    print("=" * 72)
    print(f"TRACK 1 ROUTE — {ROUTE}")
    print(f"  mode:        {gate.state}")
    print(f"  source:      {a.source}   window: {a.window}")
    print(f"  state paths: {POSITIONS_PATH} | {LOCK_PATH} | {CHECKPOINT_PATH}")
    print("=" * 72)

    if gate.requested and not gate.allow_orders:
        print("REFUSED — order sending was requested and is not available:")
        for r in gate.reasons:
            print(f"  - {r}")
        print("\nNothing was run. Re-run without --allow-orders for a shadow pass.")
        return 2

    if Path(STOP_FILE).exists():
        print(f"KILL SWITCH — {STOP_FILE} is present; no entries would be taken.")

    now = pd.Timestamp(a.as_of) if a.as_of else pd.Timestamp.now(tz="America/New_York")

    if a.source == "live-shadow":
        # The scheduler's path. One slot, one ledger row, no orders, and no replay anywhere in
        # it. Every refusal below is written to the row before it is printed, so a slot that
        # could not decide still leaves the evidence that it ran and why it stopped.
        if not a.sleeve or not a.slot_id:
            print("REFUSED — live-shadow needs --sleeve and --slot-id naming the firing slot.")
            return 2
        # The ledger check runs FIRST, before a broker is built. A slot that could not record
        # that it ran must not open a connection to find that out.
        if not wl.enabled():
            print(f"REFUSED — {LEDGER_NOT_CONFIGURED}: RAITS_WINDOW_LEDGER_DIR is unset or is "
                  f"not a directory, so this slot could not record that it ran.")
            return 2
        _tel.mark("sleeve", a.sleeve)
        _tel.mark("source", a.source)
        _tel.mark("bar_provider", a.bar_provider)
        _tel.split("setup")
        provider = broker = None
        try:
            provider, broker = build_bar_provider(a.bar_provider)
            # Stage 5ZZG. The gate travels with the slot, and so does the broker the bars came
            # from — the same object, not a second connection. When the gate is shut the slot's
            # send pass returns before importing anything, so this is byte-for-byte the run it
            # was before: no executor, no journal, no orders directory.
            res = observe_live_slot(a.sleeve, a.slot_id, phase=a.phase, now_et=now,
                                    provider=provider, order_gate=gate, broker=broker,
                                    regime_csv=a.regime_csv,
                                    data_paths=default_data_paths())
        except (ShadowRefused, LiveSourceRefused) as exc:
            # A refusal that got past `observe_live_slot` -- today only the two it raises
            # before writing a row. Recorded as its own outcome so it is not counted as a
            # clean run in the cadence numbers.
            _tel.set_outcome("refused", sticky=True)
            _tel.mark("refusal_code", exc.code)
            print(f"REFUSED — {exc.code}: {exc.detail}")
            return 2
        finally:
            # Always, and defensively: a leaked connection per slot is 25 a day, all of them
            # competing for the same client id. `getattr` because a fake broker in a test is
            # not obliged to have the method.
            if broker is not None and callable(getattr(broker, "disconnect", None)):
                try:
                    broker.disconnect()
                except Exception as _exc:      # a failed disconnect must not mask the result
                    print(f"  warning: broker disconnect failed: {_exc}")
        _tel.split("observe")
        # `ok` means THE SLOT RAN, not that it decided. A refusal recorded by name is a
        # successful observation of a window that refused, and its runtime belongs in the
        # cadence numbers exactly as much as a decision does -- the p95 gate asks how long
        # slots take, not how many of them liked what they saw.
        _tel.set_outcome("ok")
        _tel.mark("decided", bool(res["decided"]))
        _tel.mark("reason", str(res["reason"]))
        print(f"slot {res['slot_id']} seq={res['seq']}  decided={res['decided']}  "
              f"reason={res['reason']}")
        if res["detail"]:
            print(f"  {res['detail']}")
        if res["closed"]:
            c = res["closed"]
            print(f"window closed: {c['slots_decided']} of {c['expected']} decided "
                  f"({c['slots_ran']} slots ran)")
            if c["slots_decided"] >= (c["expected"] or 0):
                wrote = write_route_checkpoint(a.sleeve, now_et=now,
                                               regime_csv=a.regime_csv,
                                               data_paths=default_data_paths())
                print(f"checkpoint: {wrote}")
            else:
                print("checkpoint: NOT written — the window did not complete, and a checkpoint "
                      "written from an incomplete window would claim a state nobody observed")
        # Stage 5ZZG. This line used to be the literal `send_order calls: 0` — true every day
        # it was printed, and true because nothing could have sent an order, not because
        # anything had counted. A claim nobody measures is a claim that goes on being printed
        # after it stops being true. It is now the send pass's own summary.
        _send = res.get("send") or {}
        print(_ps.SendSummary(**{k: v for k, v in _send.items()
                                 if k in _ps.SendSummary.__dataclass_fields__}).one_line())
        if _send.get("fatal"):
            # An order whose fate is unknown is the most serious outcome this route has. It
            # does not get a zero exit and it does not get folded into the slot's reason.
            for e in _send.get("errors") or ():
                print(f"  ORDER UNRESOLVED — {e}")
            print("  the journal holds an UNKNOWN row. This is NOT a rejection: the order may "
                  "be live and simply invisible. Reconcile before the next slot.")
            return 3
        return 0

    # Passed, not left to a default. The default was `replay` regardless of `--source`, which
    # is the whole of G1.
    summary = run_shadow(window=a.window, source_name=a.source, regime_csv=a.regime_csv,
                         now_et=now, out_dir=a.out_dir, order_gate=gate,
                         persist_book=a.persist_book,
                         mode=decision_mode_for(a.source, gate))

    v = summary["freshness"]
    print(f"freshness: allow={v['allow']}  unverified={v['unverified']}")
    for r in v["reasons"]:
        print(f"  refuse: {r}")
    print(f"checkpoint: " + ", ".join(
        f"{r['sleeve']}/{r['inst']}={r['code']}" for r in summary["checkpoint"]))
    print(f"candidates={summary['candidates']} settlements={summary['settlements']} "
          f"net={summary['net']} days={summary['days']}")
    print(f"counters: {summary['counters']}")
    print(f"send_order calls: {summary['send_order_calls']}")
    print(f"book: {summary['book_state_positions']} open at end; "
          f"persisted to {summary['book_persisted_to'] or '(not persisted)'}")
    print(f"written to {a.out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
