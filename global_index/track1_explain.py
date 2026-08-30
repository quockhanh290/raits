"""global_index/track1_explain.py — route-scoped audit records for Track 1. NEW FILE.

Stage 5X. Pure, offline, and **writes nothing unless a caller asks**. It imports no broker,
starts no service, and is not wired into `run_live_day_track1`, the scheduler or the
dashboard. Building a record is a function call that returns a dict.

What this is for
----------------
Every Track 1 signal, decision and (later) execution should be answerable without re-running
the code that produced it:

    what happened            record_type + status
    why it happened          rule_ids that fired, each with the feature VALUE and the
                             THRESHOLD it was compared against
    why the alternatives     the rejected candidates get their own records, one per
      were rejected          refusal, with the verb that refused them
    which data was used      inputs_summary + feature_snapshot + data/params identity
    where the rule lives     code_refs: file + symbol + rule_id
    what proves the rule     evidence_refs: the test or report that goes red without it

The shape of the defect this exists for
---------------------------------------
`shadow_decisions_*.jsonl` (written by `run_live_day_track1.run_shadow`) already records
`verdict` and a `detail` STRING. A string is a description, and this repo has paid for
descriptions that drifted away from the thing they described — a hard-coded funding caption
that went wrong the day the calculation changed, a docstring that reported the backtest's
exit mix as if it were live's. A `detail` of "family gross 5.31% > cap 5.00%" cannot be
re-checked, cannot be filtered, and cannot tell you which file computed 5.31%.

So a rule that fires here has to carry three things a sentence cannot fake: the value, the
threshold it was compared to, and the symbol that made the comparison.

Namespaces are IMPORTED, not retyped
------------------------------------
The decision verbs come from `track1_signal_layer.DECISIONS`, the freshness refusals from
`track1_freshness`, the intraday refusals from `track1_intraday`, the route and fill laws
from `track1_params`. A second hand-written copy of any of those lists is the drift
`track1_slots.parity_report` was built to catch, arriving through a different door.

Determinism
-----------
`explain_id` is a sha256 over the identifying tuple, never `hash()` — Python's `hash()` is
salted per process (PYTHONHASHSEED), so the same record would get a different id on every
run and nothing could be linked across a restart. Same reason `route_params.params_hash`
uses hashlib.

Writing
-------
`write_shadow` is the ONLY function that touches the filesystem, it must be called
explicitly, and it REFUSES any destination outside `scratch/track1_shadow`. That refusal is
not politeness: a `--dry-run` of the legacy runner once wrote `live_day_*.log`, which
`paper_evidence_reader` globs, and it manufactured a paper-evidence episode that was then
attributed to a different session. A writer that can be pointed at a legacy path will one
day be pointed at one.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from global_index import track1_intraday as _intraday
from global_index.track1_freshness import MISSING as _FRESH_MISSING
from global_index.track1_freshness import STALE as _FRESH_STALE
from global_index.track1_freshness import UNREADABLE as _FRESH_UNREADABLE
from global_index.track1_freshness import UNVERIFIED as _FRESH_UNVERIFIED
from global_index.track1_params import FILL_LAWS, ROUTE, SLEEVE_INSTRUMENTS
from global_index.track1_signal_layer import DECISIONS as _DECISION_VERBS
from global_index.track1_signal_layer import (HALT_BREAKER, REJECT_CAP, REJECT_FAMILY_CAP,
                                              REJECT_WINDOW, SUPPRESS_SAME_SLEEVE,
                                              SUPPRESS_SAME_SYMBOL, TAKE)

SCHEMA_VERSION = "track1_explain/2"

#: Which mode produced a record. The proof set an ACCEPTED decision must show depends on it,
#: so it is recorded rather than inferred — and it is a field of its own rather than a
#: spelling of `stage`, because `stage` is part of the identifier and a field the validator
#: branches on must not also be a field that changes the id.
#:
#: Bumped /1 -> /2 on 2026-08-23 when this field became required. Nothing had been written to
#: a production path yet, so the bump costs nothing now and would have cost a migration later.
REPLAY = "replay"
SHADOW_LIVE = "shadow_live"
ARMED = "armed"
DECISION_MODES = (REPLAY, SHADOW_LIVE, ARMED)

#: Modes in which the daily-input freshness gate BINDS: a decision may only be accepted when
#: the gate passed, and an accepted record must prove it.
FRESHNESS_BINDING_MODES: frozenset = frozenset({SHADOW_LIVE, ARMED})

#: The only directory `write_shadow` will write into. Compared after resolution, so
#: `scratch/track1_shadow/../../global_index` cannot slip past it.
#: Where REPLAY and TEST artifacts go. `scratch/` is swept — research output lives there and
#: is expected to be disposable.
SHADOW_ROOT = "scratch/track1_shadow"

#: Where LIVE-SHADOW operational evidence goes. Deliberately NOT under `scratch/`: a multi-day
#: shadow period is the evidence a go-live gate is read from, and clearing scratch would delete
#: the thing the gate depends on. It sits beside the other route runtime state this repo already
#: keeps in `global_index/` — `live_state_data.js`, `preflight_state.json`,
#: `replay_checkpoint.track1.json` — rather than inventing a new top-level directory.
OPERATIONAL_ROOT = "global_index/track1_runtime/shadow"

#: The only two destinations a Track 1 explanation writer may aim at. A SET, not a relaxation:
#: everything outside both is still refused, which is what stops a writer being pointed at a
#: legacy path.
APPROVED_ROOTS: tuple = (SHADOW_ROOT, OPERATIONAL_ROOT)

# ── record types ─────────────────────────────────────────────────────────────
SIGNAL = "SIGNAL"
DECISION = "DECISION"
EXECUTION = "EXECUTION"
NO_SIGNAL = "NO_SIGNAL"
NO_ACTION = "NO_ACTION"
RECORD_TYPES = (SIGNAL, DECISION, EXECUTION, NO_SIGNAL, NO_ACTION)

# ── statuses ─────────────────────────────────────────────────────────────────
PASS = "pass"
FAIL = "fail"
ACCEPTED = "accepted"
REJECTED = "rejected"
INFO = "info"
STATUSES = (PASS, FAIL, ACCEPTED, REJECTED, INFO)

#: Which statuses each record type may carry. A DECISION that says "pass" is a DECISION
#: nobody can filter on: "pass" is what a gate check says, "accepted" is what a candidate
#: becomes.
STATUS_FOR_TYPE: dict = {
    SIGNAL:    (PASS, FAIL, INFO),
    DECISION:  (ACCEPTED, REJECTED),
    EXECUTION: (PASS, FAIL, INFO),
    NO_SIGNAL: (INFO,),
    NO_ACTION: (INFO,),
}

# ── reason codes ─────────────────────────────────────────────────────────────
NONE = "none"
NO_SETUP = "no_setup"
KILL_SWITCH = "kill_switch"
ORDER_GATE_REFUSED = "order_gate_refused"
CHECKPOINT_REFUSED = "checkpoint_refused"
FRESHNESS_FAIL = "freshness_fail"
INTRADAY_FAIL = "intraday_fail"
LIVE_FRAME_REFUSED = "live_frame_refused"
WINDOW_UNOBSERVED = "window_unobserved"
SETUP_DETECTED = "setup_detected"
FILTER_BLOCKED = "filter_blocked"

#: Everything a record may put in `reason_code`, assembled from the modules that OWN each
#: namespace rather than retyped. `_DECISION_VERBS` supplies the seven admission verbs
#: (`take` .. `halt_breaker`); `track1_intraday.REFUSAL_CODES` the fourteen bar-level
#: refusals; the freshness module its four statuses.
REASON_CODES: tuple = tuple(sorted({
    NONE, NO_SETUP, KILL_SWITCH, ORDER_GATE_REFUSED, CHECKPOINT_REFUSED,
    FRESHNESS_FAIL, INTRADAY_FAIL, LIVE_FRAME_REFUSED, WINDOW_UNOBSERVED,
    SETUP_DETECTED, FILTER_BLOCKED,
    *_DECISION_VERBS,
    *_intraday.REFUSAL_CODES,
    _FRESH_STALE, _FRESH_MISSING, _FRESH_UNREADABLE, _FRESH_UNVERIFIED,
}))

#: The reason codes that mean a candidate was refused admission. Used to enforce that a
#: REJECTED decision names one of them, and that an ACCEPTED decision names none.
REJECTION_REASONS: frozenset = frozenset({
    REJECT_CAP, REJECT_FAMILY_CAP, SUPPRESS_SAME_SYMBOL, SUPPRESS_SAME_SLEEVE,
    REJECT_WINDOW, HALT_BREAKER, KILL_SWITCH, ORDER_GATE_REFUSED, CHECKPOINT_REFUSED,
    FRESHNESS_FAIL, INTRADAY_FAIL, LIVE_FRAME_REFUSED, NO_SETUP, FILTER_BLOCKED,
})


# ── the small value types ────────────────────────────────────────────────────
@dataclass(frozen=True)
class CodeRef:
    """Where a rule lives. `line` is optional ON PURPOSE.

    A line number is the first thing to rot — every edit above it moves it — so it may be
    recorded but is never required and is never what identifies the rule. `symbol` is: a
    function or class name survives an edit that a line number does not.
    """
    file: str
    symbol: str
    rule_id: str
    line: int | None = None

    def as_dict(self) -> dict:
        return {"file": self.file, "symbol": self.symbol, "rule_id": self.rule_id,
                "line": self.line}


@dataclass(frozen=True)
class EvidenceRef:
    """A test, report or artifact that proves the rule.

    `kind="test"` means: remove the rule and this goes red. That is the only claim worth
    recording — a report that merely mentions a rule proves nothing about whether the rule
    is still wired in.
    """
    kind: str          # "test" | "report" | "artifact"
    path: str
    note: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "path": self.path, "note": self.note}


EVIDENCE_KINDS = ("test", "report", "artifact")


@dataclass(frozen=True)
class Feature:
    """One measured value and the threshold it was compared against.

    Both halves are required, and that is the whole point of this type existing. "rvol was
    high" is a sentence; `rvol=2.41 <= 2.0 -> False` can be re-checked by someone who was
    not there. `op` is recorded rather than inferred so a reader does not have to guess
    whether the bound was inclusive.

    `value=None` is legal and means the feature was ABSENT — which for the R4 context
    filter is a BLOCK, not a pass, and `passed` must say so.
    """
    name: str
    value: Any
    threshold: Any
    op: str = "<="
    passed: bool | None = None
    unit: str = ""
    source: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "value": _jsonable(self.value),
                "threshold": _jsonable(self.threshold), "op": self.op,
                "passed": self.passed, "unit": self.unit, "source": self.source}


@dataclass(frozen=True)
class Rule:
    """One auditable rule: what it says, where it lives, what proves it."""
    id: str
    description: str
    code_ref: CodeRef
    evidence: tuple = ()
    features: tuple = ()          # feature names an explanation of this rule must carry
    scope: str = ""               # sleeve name, or "shared"

    def as_dict(self) -> dict:
        return {"rule_id": self.id, "description": self.description, "scope": self.scope,
                "code_ref": self.code_ref.as_dict(),
                "evidence": [e.as_dict() for e in self.evidence],
                "required_features": list(self.features)}


def _rule(rid: str, description: str, file: str, symbol: str, *, scope: str,
          features: Sequence[str] = (), evidence: Sequence[EvidenceRef] = (),
          line: int | None = None) -> Rule:
    return Rule(rid, description, CodeRef(file, symbol, rid, line),
                tuple(evidence), tuple(features), scope)


# ── the rule registry ────────────────────────────────────────────────────────
# Part C of the Stage 5X brief. Every id below names a rule a Track 1 record may cite. A
# record citing an id that is NOT here is refused by `validate` — an unknown rule id is the
# same failure as an unknown confirmation flag in `track1_gates`: silently accepting it
# would let a record claim a provenance nobody can follow.
#
# `features` is what an explanation of that rule MUST carry. It is the mechanism that stops
# a record asserting "R4.RANGE_P90 fired" without saying what the range was.

_T_STAGE3 = "scratch/test_track1_stage3_route_20260822.py"
_T_STAGE3B = "scratch/test_track1_stage3b_blockers_20260822.py"
_T_CKPT = "scratch/test_track1_route_checkpoint_stage1_20260822.py"
_R_BLOCKERS = "scratch/track1_three_blockers_report_20260822.md"
_R_CALM = "docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md"

RULES: dict = {r.id: r for r in (

    # ── 1. Normal-R4  (sleeve roska4_swing) ──────────────────────────────────
    _rule("R4.EMA50",
          "Normal-R4 trend filter runs at ema_period=50, not legacy's 10.",
          "global_index/track1_normal_r4.py", "NormalR4Params", scope="roska4_swing",
          features=("ema_period",),
          evidence=(EvidenceRef("test", _T_STAGE3,
                                "Normal-R4 rows reproduce the committed table exactly"),)),
    _rule("R4.STOP_FIXED_ATR2",
          "Stop is entry +/- 2.0 x DAILY ATR, anchored at the ENTRY price. Legacy anchors "
          "on the running extreme through the prior bar; the two put the same multiple in "
          "a different place.",
          "global_index/track1_normal_r4.py", "make_signal_fn", scope="roska4_swing",
          features=("entry_price", "daily_atr", "stop_multiple", "stop_price"),
          evidence=(EvidenceRef("test", _T_CKPT,
                                "stop_basis / stop_multiple / stop_anchor each move the "
                                "params hash when mutated"),)),
    _rule("R4.RATCHET_OFF",
          "The stop never moves after the fill. Legacy ratchets it.",
          "global_index/track1_params.py", "sleeve_config", scope="roska4_swing",
          features=("ratchet",),
          evidence=(EvidenceRef("test", _T_CKPT, "ratchet mutation moves the hash"),)),
    _rule("R4.ARM_1405",
          "The broker stop is armed at 14:05 America/New_York on the session AFTER the "
          "fill, not at the fill.",
          "global_index/track1_params.py", "sleeve_config", scope="roska4_swing",
          features=("arm_hour", "arm_timezone"),
          evidence=(EvidenceRef("test", "global_index/test_arm_time_per_sleeve.py",
                                "per-sleeve arming times"),)),
    _rule("R4.MAX_HOLD_5",
          "A position is closed once it has been held max_hold_days=5 sessions.",
          "global_index/track1_normal_r4.py", "NormalR4Params", scope="roska4_swing",
          features=("max_hold_days",),
          evidence=(EvidenceRef("test", "global_index/test_maxhold.py", ""),)),
    _rule("R4.RANGE_P90",
          "Context filter: the PRIOR session's RTH range, as a fraction of its close, must "
          "be <= the p90 of the frozen 2018-2024 floor window. A MISSING value is a BLOCK, "
          "never a pass.",
          "global_index/track1_normal_filters.py", "R4ContextFilter.allow",
          scope="roska4_swing",
          features=("prev_range_pct",),
          evidence=(EvidenceRef("report", _R_BLOCKERS,
                                "threshold frozen on the floor window"),)),
    _rule("R4.RVOL_MAX",
          "Context filter: slot-relative volume must be <= 2.0. A MISSING value is a BLOCK.",
          "global_index/track1_normal_filters.py", "R4ContextFilter.allow",
          scope="roska4_swing",
          features=("rvol",),
          evidence=(EvidenceRef("report", _R_BLOCKERS, ""),)),
    _rule("R4.SPY_SHORT_GATE",
          "A SHORT is permitted only on a session where SPY's D-1 close was BELOW its "
          "50-day SMA (both shifted one day). Applied unconditionally, ahead of the "
          "context filter, exactly as the generator that wrote the promotion artifacts "
          "applied it.",
          "global_index/track1_normal_filters.py", "allowed_short_days",
          scope="roska4_swing",
          features=("spy_below_sma50", "direction"),
          evidence=(EvidenceRef("report", _R_BLOCKERS,
                                "removing the gate costs -11,663 to -14,143 at book level "
                                "on the floor window and widens MaxDD by 31%"),)),
    _rule("R4.FILL_LAW",
          "Which fill law the run used. The promotion artifacts were produced with every "
          "bar gap-eligible; the production engine only fills at the open after a real "
          ">15-minute break. Same bars, different exits.",
          "global_index/track1_params.py", "_base", scope="roska4_swing",
          features=("fill_law",),
          evidence=(EvidenceRef("report", _R_BLOCKERS,
                                "twelve regenerations, both laws, all three windows"),)),

    # ── 2. NKD / MNKD  (sleeve global_nkd) ───────────────────────────────────
    _rule("NKD.EMA10",
          "The promoted MNKD sleeve runs at ema_period=10, unchanged from legacy.",
          "global_index/track1_params.py", "sleeve_config", scope="global_nkd",
          features=("ema_period",),
          evidence=(EvidenceRef("test", _T_STAGE3B,
                                "MNKD rows reproduce exactly: 228 floor / 31 vault2025 / "
                                "26 vault2026"),)),
    _rule("NKD.CHANDELIER_25",
          "Chandelier stop at 2.5 x ATR anchored on the extreme through the prior bar, "
          "ratchet ON. Kept as legacy has it: Track 1 adopts the sleeve as it stands "
          "rather than re-deriving it.",
          "global_index/track1_params.py", "sleeve_config", scope="global_nkd",
          features=("stop_multiple", "stop_anchor", "ratchet"),
          evidence=(EvidenceRef("test", _T_CKPT, ""),)),
    _rule("NKD.REGIME_LAG1",
          "Regime labels are read at lag 1 session, because the Tokyo power hour precedes "
          "the US close that produced the label.",
          "global_index/regime.py", "RegimeLabels", scope="global_nkd",
          features=("label_lag_days", "regime_label"),
          evidence=(EvidenceRef("test", _T_CKPT,
                                "label_lag_days mutation moves the hash"),)),
    _rule("NKD.PRODUCTION_ENGINE",
          "The sleeve is produced by the SAME generator as Normal-R4 at its own ema, with "
          "the R4 context filter OFF — that filter is an R4 rule and applying it to a "
          "Tokyo session would be inventing one. The SPY short gate DOES apply.",
          "global_index/track1_normal_r4.py", "run_instrument", scope="global_nkd",
          features=("ema_period", "apply_context_filter"),
          evidence=(EvidenceRef("test", _T_STAGE3B, ""),)),

    # ── 3. Calm A  (sleeve roska4_calm) ──────────────────────────────────────
    _rule("CALM.D1_CALM_CAUSAL",
          "The PRIOR session's regime label must be Calm. Causal by construction: the "
          "label read is the one from a session strictly before the traded one.",
          "global_index/track1_calm_a.py", "detect", scope="roska4_calm",
          features=("prev_regime_label", "regime_lag_sessions"),
          evidence=(EvidenceRef("report", _R_CALM, ""),)),
    _rule("CALM.PCLOC_BOTTOM_THIRD",
          "The prior session's RTH close must sit in the bottom third of its own RTH "
          "range: (close - low) / (high - low) <= 1/3.",
          "global_index/track1_calm_a.py", "detect", scope="roska4_calm",
          features=("prev_close_loc",),
          evidence=(EvidenceRef("report", _R_CALM, ""),)),
    _rule("CALM.PRIOR_RTH_DOWN",
          "The prior session's RTH return (close/open - 1) must be <= 0.",
          "global_index/track1_calm_a.py", "detect", scope="roska4_calm",
          features=("prev_rth_ret",),
          evidence=(EvidenceRef("report", _R_CALM, ""),)),
    _rule("CALM.GAP_NOT_DEEP",
          "The gap from the prior RTH close to today's RTH open must be >= -1.0%. A deeper "
          "gap is a different setup and is not traded.",
          "global_index/track1_calm_a.py", "detect", scope="roska4_calm",
          features=("gap_from_prev_rth_close",),
          evidence=(EvidenceRef("report", _R_CALM, ""),)),
    _rule("CALM.PRIOR_FULL_RTH",
          "The session used as PRIOR must have run to the RTH end (15:59). Read off the "
          "record rather than assumed, so a half session cannot silently become the "
          "reference.",
          "global_index/track1_calm_a.py", "rth_sessions", scope="roska4_calm",
          features=("prev_session_last_bar",),
          evidence=(EvidenceRef("report", _R_CALM, ""),)),
    _rule("CALM.ENTRY_1000_OPEN",
          "Entry is the OPEN of the 10:00 ET bar. One-shot: a missed 10:00 is not entered "
          "late, because a 10:20 entry is a different trade at a price that has moved.",
          "global_index/track1_signal_layer.py", "window_verdict", scope="roska4_calm",
          features=("entry_time", "entry_price"),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("CALM.EXIT_1555_OPEN",
          "Exit is the OPEN of the 15:55 ET bar, same session.",
          "global_index/track1_calm_a.py", "detect", scope="roska4_calm",
          features=("exit_time",),
          evidence=(EvidenceRef("report", _R_CALM, ""),)),
    _rule("CALM.ATR15_DISASTER_STOP",
          "One disaster stop at entry - 1.5 x ATR15, placed at the fill and never moved. "
          "The cap denominator for this sleeve is the TRUE stop distance, not the "
          "mult x ATR x point-value proxy the other sleeves use.",
          "global_index/track1_params.py", "sleeve_config", scope="roska4_calm",
          features=("atr15", "stop_multiple", "true_stop_risk_dollars"),
          evidence=(EvidenceRef("test", _T_STAGE3B,
                                "listed as the sleeve's remaining live prerequisite"),)),

    # ── 4. Stress-MNQ  (sleeve roska4_stress) ────────────────────────────────
    _rule("STRESS.MNQ_ONLY_G3_Q7",
          "The committed scenario: MNQ only, quantity 7, minimum gap 3, R:R 1.5, on a "
          "break of the pre-window low. NOT futures/stress_liquidation_1020.py, which is a "
          "different 10:20 candidate that says of itself it is deliberately not wired.",
          "global_index/track1_live_sleeves.py", "SOURCES", scope="roska4_stress",
          features=("qty", "gap_min", "rr"),
          evidence=(EvidenceRef("test", _T_STAGE3B,
                                "test_sleeves_stress_is_mnq_only_g3_q7_and_not_the_1020_"
                                "candidate"),)),
    _rule("STRESS.DETECTOR_0930_1030",
          "The low that must break is taken from the 09:30-10:30 ET pre-window. The "
          "intraday gate requires that whole span present before a decision is allowed.",
          "global_index/track1_intraday.py", "REQUIREMENTS", scope="roska4_stress",
          features=("pre_window_low", "today_from", "today_to"),
          evidence=(EvidenceRef("test", _T_STAGE3B, ""),)),
    _rule("STRESS.WINDOW_1035_1230",
          "Entries are permitted only inside 10:35-12:30 ET inclusive. Inside it a missed "
          "slot costs nothing; outside it there is no entry at any price.",
          "global_index/track1_signal_layer.py", "window_verdict", scope="roska4_stress",
          features=("decision_hhmm",),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("STRESS.QTY_7",
          "Seven contracts, carried on the CANDIDATE. MNQ is 1 under Normal and 7 under "
          "Stress on the same day, which `contracts_by_inst[inst]` has no key to express.",
          "global_index/track1_params.py", "SLEEVE_QTY", scope="roska4_stress",
          features=("qty",),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("STRESS.FORCE_CLOSE_ORDER",
          "A Stress entry may DISPLACE a Normal or Calm holder of the same symbol — but "
          "only after passing the cap gate against the book it would LEAVE BEHIND. Nothing "
          "is closed for an entry that is then refused.",
          "global_index/track1_signal_layer.py", "Track1Book.evaluate",
          scope="roska4_stress",
          features=("displaced_trade_ids", "cap_checked_against"),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),

    # ── 5. Shared gates ──────────────────────────────────────────────────────
    _rule("GATE.FRESHNESS",
          "Daily inputs (pre-flight record, regime CSV, each parquet) must already cover "
          "the required session. Fails CLOSED. `unverified` is a third state and is never "
          "reported as either a pass or a failure.",
          "global_index/track1_freshness.py", "evaluate", scope="shared",
          features=("freshness_allow",),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("CONTEXT.FRESHNESS_OBSERVED",
          "The daily-input freshness verdict was READ and RECORDED for this run, and it "
          "bound nothing. Used by replay, where the gate describes the machine's data at "
          "the moment the replay ran and cannot be evidence about an admission that "
          "happened months earlier. Measured 2026-08-23: the SAME historical decision "
          "carries passed=True at 12:00 and passed=False at 15:00 on one afternoon, with "
          "91 accepted either way — a field that moves while the thing it describes does "
          "not is run context, not proof.",
          "global_index/track1_freshness.py", "evaluate", scope="shared",
          features=("freshness_allow",),
          evidence=(EvidenceRef("test", "scratch/test_track1_stage5z_freshness_root_"
                                "20260823.py",
                                "the same replay under two clocks yields two freshness "
                                "readings and one identical decision stream"),)),
    _rule("GATE.INTRADAY",
          "The same-session sleeves need this morning's bars: the contiguous span the "
          "decision reads, the decision bar itself, staleness against the decision "
          "instant, and the prior RTH where the rule reads it.",
          "global_index/track1_intraday.py", "validate", scope="shared",
          features=("intraday_allow",),
          evidence=(EvidenceRef("test", _T_STAGE3B, ""),)),
    _rule("GATE.LIVE_FRAME",
          "Today's bars are joined onto the frozen history through ONE splice, which "
          "refuses a tz mismatch, duplicate or out-of-order timestamps, a column mismatch, "
          "and any mutation of the frozen history.",
          "global_index/track1_live_frame.py", "splice", scope="shared",
          features=("frozen_rows", "live_rows"),
          evidence=(EvidenceRef("test", _T_STAGE3B, ""),)),
    _rule("GATE.CAP_CLUSTER",
          "A candidate's risk must fit its cluster's gross (and where declared, net) "
          "budget as a fraction of the account.",
          "global_index/net_exposure_multi.py", "MultiClusterGuard.admits", scope="shared",
          features=("cluster_gross_after",),
          evidence=(EvidenceRef("test", "global_index/test_cluster_gate.py", ""),)),
    _rule("GATE.CAP_FAMILY",
          "Normal and Calm share ONE combined budget on top of their own, because Calm A "
          "is long MES/MNQ into the same session Normal is trend-following. No production "
          "equivalent exists: MultiClusterGuard checks a candidate against its own cluster "
          "only.",
          "global_index/track1_signal_layer.py", "family_verdict", scope="shared",
          features=("family_gross",),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("GATE.SAME_SYMBOL",
          "A Normal or Calm candidate is suppressed when another sleeve already holds the "
          "same instrument. Stress is deliberately absent from this table: it displaces a "
          "holder rather than deferring to one.",
          "global_index/track1_signal_layer.py", "SAME_SYMBOL_BLOCKERS", scope="shared",
          features=("held_by_clusters",),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("GATE.SAME_SLEEVE",
          "One sleeve may not hold the same instrument twice.",
          "global_index/track1_signal_layer.py", "Track1Book.evaluate", scope="shared",
          features=("held_by_same_sleeve",),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("GATE.WINDOW",
          "The instant must sit inside the sleeve's declared detection window. Sleeves "
          "with no declared window (Normal, NKD) are always inside one — bounding them "
          "here would be inventing a rule.",
          "global_index/track1_signal_layer.py", "window_verdict", scope="shared",
          features=("decision_hhmm",),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("GATE.BREAKER",
          "The circuit breaker is marked at every instant and its verdict decides whether "
          "NEW risk is allowed. Marked AFTER this instant's closes are booked, which is "
          "the ordering every measured Track 1 figure was produced under.",
          "global_index/track1_signal_layer.py", "Track1Book.begin_instant", scope="shared",
          features=("allow_new_entries",),
          evidence=(EvidenceRef("test", "global_index/test_kill_switch.py", ""),)),
    _rule("GATE.CHECKPOINT",
          "A resumed position is accepted only when route, sleeve, instrument, schema, "
          "params hash and the frame fingerprint all match. Unknown is NOT equal: a "
          "missing field is a refusal, never a default.",
          "global_index/route_checkpoint.py", "usable", scope="shared",
          features=("checkpoint_accepted",),
          evidence=(EvidenceRef("test", _T_CKPT, ""),)),
    _rule("GATE.B1_ORDER",
          "No order may be sent while any Stage 2D blocker is open. Arming needs BOTH an "
          "on-disk confirmation that schema-checks and TRACK1_ORDERS_APPROVED=1 in the "
          "environment; one flag on a command line is never enough to reach an exchange.",
          "global_index/run_live_day_track1.py", "OrderGate", scope="shared",
          features=("open_blockers",),
          evidence=(EvidenceRef("test", _T_STAGE3, ""),)),
    _rule("GATE.WINDOW_LEDGER",
          "Whether the window was WATCHED at all, which is a different fact from whether "
          "it produced a signal. Absence of a complete observation is itself the signal.",
          "global_index/window_ledger.py", "status", scope="shared",
          features=("observed_slots",),
          evidence=(EvidenceRef("test", _T_STAGE3B, ""),)),
)}

#: Rules an ACCEPTED decision must show it passed, BY MODE. A decision that admitted a
#: candidate without the numbers from the gates that could have stopped it is a decision
#: nobody can audit — so each mode names the gates that actually governed it.
#:
#: Replay does not include the freshness gate, and that is the Stage 5Z finding rather than
#: a convenience. `fresh.evaluate` reads the machine's CURRENT daily inputs. On a replay of
#: a historical window those inputs did not govern the admission and cannot testify about
#: it: measured 2026-08-23, the same 2026-01-02 decision — same explain_id, same accepted
#: status — carried a PASSED freshness proof when the replay ran at 12:00 and a FAILED one
#: at 15:00, with 91 accepted decisions in both. A proof that moves while the decision does
#: not is not a proof of that decision. It travels as run context instead, under
#: CONTEXT.FRESHNESS_OBSERVED, where it is still recorded and still visible.
#:
#: Live and armed DO include it, because there the gate reads the inputs that govern the
#: decision being taken right now.
ACCEPTED_PROOF_RULES_BY_MODE: dict = {
    REPLAY:      ("GATE.CAP_CLUSTER", "GATE.BREAKER"),
    SHADOW_LIVE: ("GATE.CAP_CLUSTER", "GATE.FRESHNESS", "GATE.BREAKER"),
    ARMED:       ("GATE.CAP_CLUSTER", "GATE.FRESHNESS", "GATE.BREAKER"),
}

#: Kept as the strictest set, for callers and tests that want "what a live decision owes".
ACCEPTED_PROOF_RULES: tuple = ACCEPTED_PROOF_RULES_BY_MODE[ARMED]


# ── helpers ──────────────────────────────────────────────────────────────────
def _jsonable(value: Any) -> Any:
    """Anything a record may hold, rendered so `json.dumps` cannot fail.

    Timestamps arrive as `pd.Timestamp` from every producer on this route. Stringifying
    them here rather than at each call site is what makes `json.dumps(record)` a property
    of this module instead of a hope about its callers.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return str(value)


def explain_id(*, route: str, session_date: str, sleeve: str, instrument: str,
               candidate_id: str, record_type: str, stage: str = "",
               sequence: int | None = None) -> str:
    """Deterministic id for one record. sha256, never `hash()`.

    `hash()` is salted per interpreter (PYTHONHASHSEED), so the same record would get a
    different id in every process and nothing could be linked across a restart — the same
    trap `route_params.params_hash` documents.

    `stage` and `sequence` are what separate two records that are otherwise the same tuple:
    a candidate evaluated at 10:35 and again at 10:40 inside the Stress window is two
    decisions, not one.
    """
    if record_type not in RECORD_TYPES:
        raise ValueError(f"record_type must be one of {RECORD_TYPES}, got {record_type!r}")
    parts = [str(route), str(session_date), str(sleeve), str(instrument),
             str(candidate_id), str(record_type), str(stage),
             "" if sequence is None else str(int(sequence))]
    payload = "|".join(parts)
    return "t1x_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def git_commit(root: str | Path = ".") -> str | None:
    """Current HEAD, or None. Never raises, and never guesses.

    None means "could not read it", which is a different statement from a commit hash and
    must stay distinguishable from one — the fail-open shape this repo has already paid
    for is a status probe that answers "no" when it means "I do not know".
    """
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


@dataclass(frozen=True)
class Identity:
    """The route/params/data identity every record carries.

    Separate from the record so one run builds it once. `params_hash` is what a checkpoint
    is accepted or refused on; recording it beside a decision is what lets someone ask
    later whether the decision and the resumed state were computed under the same config.
    """
    route: str = ROUTE
    params_hash: str = ""
    fill_law: str = ""
    data_source_identity: str = ""
    regime_csv_identity: str = ""
    git_commit: str | None = None

    def as_dict(self) -> dict:
        # `route` is deliberately NOT emitted here. It reached the record from two places
        # until 2026-08-23 — the builder's `route=` argument fed the explain_id, and this
        # spread overwrote the field afterwards — so a record could carry an id naming one
        # route and a field naming another, and be internally inconsistent while passing
        # every check. One field, one source: the builder's argument. `_base_record`
        # refuses a disagreement rather than silently preferring either side.
        return {"track1_params_hash": self.params_hash,
                "fill_law": self.fill_law,
                "data_source_identity": self.data_source_identity,
                "regime_csv_identity": self.regime_csv_identity,
                "git_commit": self.git_commit}


def derived_refs(rule_ids: Sequence[str]) -> tuple:
    """`(code_refs, evidence_refs)` for a set of rule ids. The ONLY derivation.

    Called by the builder to fill the fields and by the validator to re-derive and compare.
    One function rather than two, because a validator holding its own copy of the rule is a
    second description of the same thing — which is the drift the whole registry exists to
    remove, and it would arrive in the one place whose job is to catch drift.

    Unknown ids are skipped here and reported separately by `validate`; deriving nothing
    for them keeps one bad id from cascading into a page of confusing errors.
    """
    rid = list(rule_ids)
    code_refs = [RULES[r].code_ref.as_dict() for r in rid if r in RULES]
    evidence: list = []
    seen = set()
    for r in rid:
        rule = RULES.get(r)
        if rule is None:
            continue
        for e in rule.evidence:
            key = (e.kind, e.path, r)
            if key in seen:
                continue
            seen.add(key)
            evidence.append({**e.as_dict(), "rule_id": r})
    return code_refs, evidence


def _comparable(refs: Sequence[Mapping[str, Any]]) -> list:
    """Refs as sorted tuples, so a comparison is about CONTENT and not about order.

    A record that reordered its own refs on a round-trip is not a tampered record, and a
    check that went red for it would be a check people learn to switch off.
    """
    return sorted(tuple(sorted((str(k), _jsonable(v)) for k, v in dict(r).items()))
                  for r in refs)


def _base_record(*, record_type: str, route: str, session_date: str, sleeve: str,
                 instrument: str, candidate_id: str, decision_time: Any,
                 decision_mode: str = REPLAY,
                 status: str, reason_code: str, rule_ids: Sequence[str] = (),
                 features: Sequence[Feature] = (),
                 thresholds: Mapping[str, Any] | None = None,
                 inputs_summary: Mapping[str, Any] | None = None,
                 outputs: Mapping[str, Any] | None = None,
                 data_time: Any = None, bar_timestamps: Sequence[Any] = (),
                 parent_explain_id: str | None = None,
                 identity: Identity | None = None,
                 stage: str = "", sequence: int | None = None,
                 rejection: Mapping[str, Any] | None = None,
                 extra: Mapping[str, Any] | None = None) -> dict:
    ident = identity or Identity()
    if ident.route != route:
        raise ValueError(
            f"route disagreement: the record says {route!r} and its Identity says "
            f"{ident.route!r}. Refused rather than resolved — a record whose id is built "
            f"from one route and whose field names another is internally inconsistent, and "
            f"picking a winner here would hide which caller was wrong.")
    rid = list(rule_ids)
    # code_refs are DERIVED from the rule ids, never passed in. A record whose code_refs
    # were written by hand is a record that can name a rule and point at the wrong file —
    # the exact drift this repo keeps paying for when a description travels beside the
    # thing it describes instead of being computed from it.
    code_refs, evidence = derived_refs(rid)
    rec = {
        "schema_version": SCHEMA_VERSION,
        "explain_id": explain_id(route=route, session_date=session_date, sleeve=sleeve,
                                 instrument=instrument, candidate_id=candidate_id,
                                 record_type=record_type, stage=stage, sequence=sequence),
        "parent_explain_id": parent_explain_id,
        "route": route,
        "sleeve": sleeve,
        "instrument": instrument,
        "session_date": str(session_date),
        "candidate_id": str(candidate_id),
        "record_type": record_type,
        "decision_mode": decision_mode,
        "stage": stage,
        "sequence": sequence,
        "decision_time": _jsonable(decision_time),
        "data_time": _jsonable(data_time),
        "bar_timestamps": [_jsonable(b) for b in bar_timestamps],
        "status": status,
        "reason_code": reason_code,
        "rule_ids": rid,
        "code_refs": code_refs,
        "evidence_refs": evidence,
        "feature_snapshot": [f.as_dict() for f in features],
        "thresholds": _jsonable(dict(thresholds or {})),
        "inputs_summary": _jsonable(dict(inputs_summary or {})),
        "outputs": _jsonable(dict(outputs or {})),
        "rejection": _jsonable(dict(rejection)) if rejection else None,
        **ident.as_dict(),
    }
    if extra:
        for k, v in dict(extra).items():
            rec.setdefault(k, _jsonable(v))
    return rec


# ── builders ─────────────────────────────────────────────────────────────────
def signal_record(**kw) -> dict:
    """A setup was detected, or was looked for and a rule said no."""
    kw.setdefault("status", PASS)
    kw.setdefault("reason_code", SETUP_DETECTED)
    return _base_record(record_type=SIGNAL, **kw)


def decision_record(**kw) -> dict:
    """The admission verdict: accepted, or refused and by which gate."""
    return _base_record(record_type=DECISION, **kw)


def execution_record(**kw) -> dict:
    """Order intent, fill, cancel or failure. Nothing on this route produces one yet."""
    kw.setdefault("status", INFO)
    kw.setdefault("reason_code", NONE)
    return _base_record(record_type=EXECUTION, **kw)


def no_signal_record(**kw) -> dict:
    """A window was watched and produced nothing.

    Meaningful, not spam: it is the difference between "the rule said no" and "nobody
    looked", which is the distinction `window_ledger` exists to keep.
    """
    kw.setdefault("status", INFO)
    kw.setdefault("reason_code", NO_SETUP)
    return _base_record(record_type=NO_SIGNAL, **kw)


def no_action_record(**kw) -> dict:
    kw.setdefault("status", INFO)
    kw.setdefault("reason_code", NONE)
    return _base_record(record_type=NO_ACTION, **kw)


# ── validation ───────────────────────────────────────────────────────────────
REQUIRED_FIELDS: tuple = (
    "schema_version", "explain_id", "route", "sleeve", "instrument", "session_date",
    "candidate_id", "record_type", "decision_mode", "decision_time", "status",
    "reason_code",
    "rule_ids", "code_refs", "evidence_refs", "feature_snapshot", "thresholds",
    "inputs_summary", "outputs", "track1_params_hash", "fill_law", "git_commit",
)


def validate(record: Mapping[str, Any]) -> list:
    """Every problem with one record, as sentences. Empty list means valid.

    Returns rather than raises so a caller can report all of them at once; `check` raises
    for callers that want a hard stop. Nothing here is a warning — a record that half
    validates is the confirmation file that half parses, and this repo already knows what
    that costs.
    """
    errs: list = []
    missing = [f for f in REQUIRED_FIELDS if f not in record]
    if missing:
        errs.append(f"missing required field(s): {missing}")
        if "record_type" not in record or "status" not in record:
            return errs

    rtype, status = record.get("record_type"), record.get("status")
    if rtype not in RECORD_TYPES:
        errs.append(f"record_type {rtype!r} is not one of {RECORD_TYPES}")
    elif status not in STATUS_FOR_TYPE[rtype]:
        errs.append(f"status {status!r} is not valid for {rtype}; "
                    f"allowed: {STATUS_FOR_TYPE[rtype]}")

    if record.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version {record.get('schema_version')!r} "
                    f"!= {SCHEMA_VERSION!r}")

    mode = record.get("decision_mode")
    if mode not in DECISION_MODES:
        errs.append(f"decision_mode {mode!r} is not one of {DECISION_MODES}; the proof set "
                    f"an accepted decision owes depends on it, so it is never inferred")

    reason = record.get("reason_code")
    if reason not in REASON_CODES:
        errs.append(f"reason_code {reason!r} is not in the registry")

    # This module validates ONE route. The sleeve table below is Track 1's, the rule
    # registry is Track 1's, and a record carrying another route would be checked against
    # rules that do not govern it while looking fully validated. Measured 2026-08-23: a
    # record built with route="legacy" produced an explain_id that recomputes CORRECTLY
    # from "legacy", so the id check further down cannot stand in for this one.
    if record.get("route") != ROUTE:
        errs.append(f"route {record.get('route')!r} is not {ROUTE!r}; this registry only "
                    f"governs Track 1 and cannot vouch for another route's records")

    sleeve, inst = record.get("sleeve"), record.get("instrument")
    known = SLEEVE_INSTRUMENTS.get(sleeve)
    if known is None:
        errs.append(f"sleeve {sleeve!r} is not a Track 1 sleeve "
                    f"({sorted(SLEEVE_INSTRUMENTS)})")
    elif inst not in known:
        errs.append(f"instrument {inst!r} is not traded by {sleeve!r} (allowed: {known})")

    if record.get("fill_law") not in FILL_LAWS:
        errs.append(f"fill_law {record.get('fill_law')!r} is not one of {FILL_LAWS}; it "
                    f"has no default because a default here is a default that will be "
                    f"taken")

    rule_ids = list(record.get("rule_ids") or [])
    unknown = [r for r in rule_ids if r not in RULES]
    if unknown:
        errs.append(f"rule_id(s) not in the registry: {unknown}")

    refs = list(record.get("code_refs") or [])
    if rule_ids and not refs:
        errs.append("rule_ids were cited but code_refs is empty; a rule that cannot be "
                    "pointed at in code is a rule nobody can check")
    ref_rules = {r.get("rule_id") for r in refs}
    for r in rule_ids:
        if r not in ref_rules:
            errs.append(f"rule {r!r} fired but no code_ref names it")
    for r in refs:
        if not r.get("file") or not r.get("symbol"):
            errs.append(f"code_ref {r!r} needs both a file and a symbol; a line number is "
                        f"optional and is never the identifier")

    # Re-derive rather than trust. The builder computed these from the registry, but a
    # record travels — through JSON, through a file, through an edit — and after that the
    # derivation is only a copy sitting next to the thing it claims to describe. Measured
    # 2026-08-23 before this check existed: swapping a ref's file for "wrong.py", swapping
    # its symbol, and appending a whole extra ref for a rule that never fired were all
    # accepted. `derived_refs` is the SAME function the builder called, so there is no
    # second copy of the rule here to drift.
    want_refs, want_evidence = derived_refs(rule_ids)
    if _comparable(refs) != _comparable(want_refs):
        errs.append(
            f"code_refs do not match what the cited rules derive. expected "
            f"{[(r['rule_id'], r['file'], r['symbol']) for r in want_refs]}, got "
            f"{[(r.get('rule_id'), r.get('file'), r.get('symbol')) for r in refs]}")
    ev = list(record.get("evidence_refs") or [])
    if _comparable(ev) != _comparable(want_evidence):
        errs.append(
            f"evidence_refs do not match what the cited rules derive. expected "
            f"{[(e['rule_id'], e['kind'], e['path']) for e in want_evidence]}, got "
            f"{[(e.get('rule_id'), e.get('kind'), e.get('path')) for e in ev]}")

    # Feature/threshold pairing. A rule that decided a pass or a fail must show the value
    # AND the bound it was compared against; either half alone is a sentence.
    feats = {f.get("name"): f for f in (record.get("feature_snapshot") or [])}
    for f in (record.get("feature_snapshot") or []):
        if "threshold" not in f:
            errs.append(f"feature {f.get('name')!r} carries no threshold")
        if f.get("passed") is None and rtype in (SIGNAL, DECISION):
            errs.append(f"feature {f.get('name')!r} does not say whether it passed")
    for r in rule_ids:
        want = RULES[r].features if r in RULES else ()
        absent = [n for n in want if n not in feats]
        if absent:
            errs.append(f"rule {r!r} fired but its explanation omits {absent}")

    # The identifier must still be the identifier OF THIS RECORD. Recomputed from the
    # record's own components rather than taken on trust: the builder got it right, but
    # nothing downstream re-checked it, and measured 2026-08-23 a record whose
    # session_date, stage or sequence had been edited after the build — or whose id had
    # been replaced with thirty-two zeros — validated clean. An id that no longer names its
    # own contents is worse than no id: it links a reader to the wrong record confidently.
    if rtype in RECORD_TYPES:
        try:
            want_id = explain_id(
                route=record.get("route"), session_date=record.get("session_date"),
                sleeve=record.get("sleeve"), instrument=record.get("instrument"),
                candidate_id=record.get("candidate_id"), record_type=rtype,
                stage=record.get("stage") or "", sequence=record.get("sequence"))
        except (ValueError, TypeError) as exc:
            errs.append(f"explain_id could not be recomputed: {exc}")
        else:
            if record.get("explain_id") != want_id:
                errs.append(
                    f"explain_id {record.get('explain_id')!r} does not match this "
                    f"record's own components; recomputing them gives {want_id!r}. Either "
                    f"the id or a field it is built from was changed after the record was "
                    f"built")

    if rtype == DECISION:
        if status == REJECTED:
            if reason not in REJECTION_REASONS:
                errs.append(f"a rejected decision must name a refusal reason; {reason!r} "
                            f"is not one of {sorted(REJECTION_REASONS)}")
            if not record.get("rejection"):
                errs.append("a rejected decision must carry rejection details")
        elif status == ACCEPTED:
            if reason not in (TAKE, NONE):
                errs.append(f"an accepted decision cannot carry reason_code {reason!r}")
            want = ACCEPTED_PROOF_RULES_BY_MODE.get(mode, ())
            absent = [r for r in want if r not in rule_ids]
            if absent:
                errs.append(f"an accepted {mode} decision must prove it checked {absent}; "
                            f"the gates that could have stopped it are the gates it has to "
                            f"show it passed")
            # A gate that BINDS in this mode may not be cited by a decision that was
            # accepted anyway. Before 2026-08-23 every accepted replay record carried a
            # freshness proof marked FAILED and validated clean — a record asserting both
            # "this gate refused" and "the candidate was admitted" is not an explanation,
            # it is a contradiction with an id.
            failed = sorted({f.get("name") for f in (record.get("feature_snapshot") or [])
                             if f.get("passed") is False})
            if failed:
                errs.append(
                    f"an accepted decision carries proof feature(s) {failed} marked FAILED. "
                    f"Either the gate did not refuse and the feature is wrong, or it did "
                    f"and the decision should not be accepted — a record cannot say both.")
            binding = [r for r in rule_ids
                       if r == "GATE.FRESHNESS" and mode not in FRESHNESS_BINDING_MODES]
            if binding:
                errs.append(
                    f"a {mode} decision may not cite GATE.FRESHNESS as a proof: the gate "
                    f"reads the machine's CURRENT daily inputs, which did not govern a "
                    f"historical admission. Record it as CONTEXT.FRESHNESS_OBSERVED "
                    f"instead, which is what that rule is for.")
    return errs


def check(record: Mapping[str, Any]) -> dict:
    """`validate`, but raising. Returns the record so it can be used inline."""
    errs = validate(record)
    if errs:
        raise ValueError("track1_explain: invalid record\n  - " + "\n  - ".join(errs))
    return dict(record)


def to_json(record: Mapping[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ── the only writer ──────────────────────────────────────────────────────────
class ShadowPathRefused(RuntimeError):
    """A write was aimed outside `scratch/track1_shadow`."""


def _resolve_shadow(out_dir: str | Path, root: str | Path = ".") -> Path:
    root_p = Path(root).resolve()
    target = Path(out_dir)
    target = (target if target.is_absolute() else root_p / target).resolve()
    for approved in APPROVED_ROOTS:
        allowed = (root_p / approved).resolve()
        if target == allowed or allowed in target.parents:
            return target
    raise ShadowPathRefused(
        f"track1_explain writes only under {' or '.join(APPROVED_ROOTS)}; refused {target}. A "
        f"writer that can be aimed at a legacy path will one day be aimed at one — a "
        f"--dry-run once wrote live_day_*.log, which paper_evidence_reader globs, and "
        f"it manufactured a paper-evidence episode attributed to a different session.")


def resolve_shadow_dir(out_dir: str | Path = SHADOW_ROOT,
                       root: str | Path = ".") -> Path:
    """Where a write WOULD go, or raise. The public form of the bound.

    Exists so a caller can check the destination BEFORE building anything — a writer that
    only resolves its path when it happens to have rows is fail-open, and Stage 5Y measured
    exactly that: a run with zero decisions never resolved at all, so one aimed at a legacy
    directory passed quietly and would only have written there on the first pass that had
    rows.

    Relocating with `root` is the supported way to write somewhere else: the bound moves
    with it, so a temp root allows `<root>/scratch/track1_shadow` and still refuses
    `<root>/global_index`. There is deliberately NO flag that switches the bound off.
    """
    return _resolve_shadow(out_dir, root)


def write_shadow(records: Iterable[Mapping[str, Any]], *, session_date: str,
                 out_dir: str | Path = SHADOW_ROOT, root: str | Path = ".",
                 validate_first: bool = True, mode: str = "a") -> Path:
    """Write validated records to `<out_dir>/explanations_YYYYMMDD.jsonl`.

    `out_dir` may be a sub-directory of the shadow root — a caller that writes several
    replay windows keeps them apart that way — but never anything outside it.

    `mode` is `"a"` by default and `"w"` truncates. Truncation exists because the
    decision file this runs beside is opened with `"w"`: append-only here would mean a
    second run of the same window produced 139 decisions and 278 explanations, and a count
    that drifts on a re-run is a count nobody can use as a check. A caller that writes a
    date in several batches truncates on the first and appends after — which is what
    `run_live_day_track1` does.

    Validation happens for EVERY record before the file is opened. A partially written
    batch is a file whose tail nobody can trust, and the caller would have no way to tell
    which rows landed.
    """
    if mode not in ("a", "w"):
        raise ValueError(f"mode must be 'a' or 'w', got {mode!r}")
    target = _resolve_shadow(out_dir, root)
    rows = list(records)
    if validate_first:
        for i, rec in enumerate(rows):
            errs = validate(rec)
            if errs:
                raise ValueError(f"track1_explain: record {i} is invalid and NOTHING was "
                                 f"written\n  - " + "\n  - ".join(errs))
    target.mkdir(parents=True, exist_ok=True)
    day = str(session_date).replace("-", "")
    path = target / f"explanations_{day}.jsonl"
    with open(path, mode, encoding="utf-8") as fh:
        for rec in rows:
            fh.write(to_json(rec) + "\n")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5Q-2 — the LIVE evidence layout, owned in one place.
#
# The defect this replaces
# ------------------------
# Every live slot wrote into `<shadow>/explanations/live_<date>/explanations_<date>.jsonl`
# and `write_shadow` was called with `mode="w"`, so each slot TRUNCATED the last. All four
# sleeves shared that one file per session date. Measured 2026-08-24 by running the writer
# twice: after the second slot wrote, the file held that slot's single row and nothing else.
# Calm's 10:00 rows were erased by Stress at 10:35 every day, and no reader could tell that
# apart from a Calm slot that never explained anything.
#
# The fix is the PATH, not the mode. Truncation is not the bug — it is what keeps a re-run of
# one slot from doubling its own rows, and the decision file beside it is opened `"w"` for the
# same reason. The bug is that one path was shared by writers that are separate processes with
# separate lifetimes. Give each slot its own file and truncation becomes exactly right: a
# slot may replace its own evidence and can no longer touch anyone else's.
#
#     <shadow>/explanations/live_<YYYY-MM-DD>/<sleeve>/<slot_id>/explanations_<YYYYMMDD>.jsonl
#
# The REPLAY path is untouched and stays flat under its window name: a replay writes one
# window from one process, which is the case truncation was designed for.
# ══════════════════════════════════════════════════════════════════════════════

#: Prefix of a live-shadow window sub-path. Parsed as well as built, so the two cannot drift.
LIVE_WINDOW_PREFIX = "live_"


def live_window(session_date, sleeve: str, slot_id: str) -> str:
    """The window sub-path ONE live slot writes under. The layout lives here and nowhere else.

    Three levels, and each earns its place:

        live_<date>   the session day, so a day's evidence is one subtree
        <sleeve>      so "what did Normal-R4 explain today" is a directory, not a filter
        <slot_id>     so a slot owns its file and may replace only its own rows

    A caller that built this string by hand would be a second definition of the layout, and
    the reader below resolves the same shape — that is why both are in this module.
    """
    sleeve = str(sleeve or "unknown_sleeve")
    slot_id = str(slot_id or "unknown_slot")
    for part, what in ((sleeve, "sleeve"), (slot_id, "slot_id")):
        if "/" in part or "\\" in part or part in (".", ".."):
            raise ValueError(
                f"{what}={part!r} would escape the evidence tree. Refused rather than "
                f"sanitised: a name that needs cleaning is a name a caller got wrong, and "
                f"silently rewriting it files the rows somewhere nobody will look for them.")
    return f"{LIVE_WINDOW_PREFIX}{session_date}/{sleeve}/{slot_id}"


def explanation_files(root: str | Path = ".", day_compact: str = "",
                      out_dir: str | Path = OPERATIONAL_ROOT) -> list:
    """Every file holding explanation rows for one day, at ANY depth under the tree.

    Recursive on purpose. It has to find:

        explanations_<day>.jsonl                              a flat writer (tests, and the
                                                              layout before Stage 5Q-1)
        live_<date>/explanations_<day>.jsonl                  the 5Q layout
        live_<date>/<sleeve>/<slot>/explanations_<day>.jsonl  the 5Q-2 layout

    A reader that only accepts today's shape is the same brittleness that made the gate read
    a path nothing wrote to — and rows already on disk in an older shape are evidence, not
    litter.
    """
    d = Path(root) / Path(out_dir) / "explanations"
    if not d.is_dir():
        return []
    name = f"explanations_{day_compact}.jsonl" if day_compact else "explanations_*.jsonl"
    out = [p for p in [d / name] if p.exists() and day_compact]
    out.extend(sorted(p for p in d.rglob(name) if p not in out))
    return out


def attribution_from_path(path, root: str | Path = ".",
                          out_dir: str | Path = OPERATIONAL_ROOT) -> dict:
    """Which day/sleeve/slot a file's rows belong to, read off the path the writer created.

    The path is authoritative for the SLOT: the row itself carries route, sleeve and session
    date, and a decision row does not carry the slot id. Reading it here means a row can be
    attributed without threading a new field through every builder — and when the row DOES
    carry `slot_id`, the audit prefers the row and reports any disagreement rather than
    picking a winner.

    Everything is `None` when the path is not in a recognised shape. `None` is a third
    answer, not a default: "this file is not laid out the way the writer lays them out" must
    not read as "this file belongs to no slot".
    """
    p = Path(path)
    base = (Path(root) / Path(out_dir) / "explanations").resolve()
    try:
        rel = p.resolve().relative_to(base)
    except Exception:                                      # noqa: BLE001
        return {"session_date": None, "sleeve": None, "slot_id": None, "shape": "outside"}
    parts = list(rel.parts[:-1])                           # drop the file name
    if not parts:
        return {"session_date": None, "sleeve": None, "slot_id": None, "shape": "flat"}
    window = parts[0]
    day = window[len(LIVE_WINDOW_PREFIX):] if window.startswith(LIVE_WINDOW_PREFIX) else None
    if len(parts) >= 3:
        return {"session_date": day, "sleeve": parts[1], "slot_id": parts[2],
                "shape": "live_sleeve_slot"}
    if len(parts) == 2:
        return {"session_date": day, "sleeve": parts[1], "slot_id": None,
                "shape": "live_sleeve"}
    return {"session_date": day, "sleeve": None, "slot_id": None, "shape": "live_day"}


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5Q-2 — the freshness proof, checked structurally instead of by substring.
#
# What was there, and why it was wrong in BOTH directions
# -------------------------------------------------------
# The acceptance gate asked `"freshness" in json.dumps(row).lower()`. Measured 2026-08-24
# against records built by this module:
#
#   a real REJECTED live decision (reject_cap) contains the word NOWHERE  -> it FAILED,
#       and rejections are mode-independent, so the first day any candidate was refused by a
#       cap, a window or the same-symbol rule would have failed the audit;
#   a row whose only "freshness" is a sentence in `rejection.detail`      -> it PASSED.
#
# Too strict and too loose at once, which is what a substring test over free text always is —
# the same shape as counting every traceback line containing "python" as a job launch.
#
# The structured rule, derived from the tables rather than restated
# -----------------------------------------------------------------
# A row owes a `freshness_allow` FEATURE exactly when the rules it cites declare that
# feature — that is `RULES[rid].features`, the same table the record was built from. So:
#
#   accepted, binding mode  -> must cite GATE.FRESHNESS (ACCEPTED_PROOF_RULES_BY_MODE) and
#                              carry a boolean freshness_allow feature that PASSED
#   accepted, replay        -> owes nothing: the gate reads today's inputs and did not govern
#                              an admission taken months ago (the Stage 5Z finding)
#   rejected                -> owes it only if a cited rule declares it; a cap refusal does
#                              not consult freshness and must not be asked to prove it
#   NO_ACTION context       -> the run's freshness observation. Owes a boolean feature; that
#                              is the record the day's freshness verdict is audited from
# ══════════════════════════════════════════════════════════════════════════════

#: The one feature name that constitutes a freshness proof. Named once.
FRESHNESS_FEATURE = "freshness_allow"

#: The rule that carries the run-level freshness observation on a NO_ACTION record.
FRESHNESS_CONTEXT_RULE = "CONTEXT.FRESHNESS_OBSERVED"


def _feature(record: Mapping[str, Any], name: str):
    for f in record.get("feature_snapshot") or []:
        if isinstance(f, Mapping) and str(f.get("name")) == name:
            return f
    return None


def freshness_proof(record: Mapping[str, Any]) -> dict:
    """What this record owes on freshness, and whether it paid.

    `{owed, present, value, passed, cited, why}`. Nothing here reads free text: `owed` comes
    from the cited rules' declared features, and `present` from `feature_snapshot`.
    """
    rule_ids = [str(r) for r in (record.get("rule_ids") or [])]
    declared = set()
    for rid in rule_ids:
        rule = RULES.get(rid)
        if rule is not None:
            declared.update(rule.features)

    mode = record.get("decision_mode")
    status = record.get("status")
    binding_accept = (status == ACCEPTED and mode in FRESHNESS_BINDING_MODES)

    owed = FRESHNESS_FEATURE in declared or binding_accept
    feat = _feature(record, FRESHNESS_FEATURE)
    value = feat.get("value") if feat else None
    passed = feat.get("passed") if feat else None
    # The RUN-level observation, which every DECISION record carries whether or not the
    # decision consulted the gate. This is what makes a cap refusal auditable without asking
    # it to prove a gate it never reached — and it is a typed field, so a sentence mentioning
    # freshness cannot stand in for it.
    inputs = record.get("inputs_summary")
    observed = inputs.get(FRESHNESS_FEATURE) if isinstance(inputs, Mapping) else None
    return {
        "owed": bool(owed),
        "present": feat is not None,
        "value": value,
        "passed": passed,
        "observed": observed,
        "observed_is_bool": isinstance(observed, bool),
        "cited": sorted(rid for rid in rule_ids
                        if RULES.get(rid) is not None
                        and FRESHNESS_FEATURE in RULES[rid].features),
        "binding_accept": bool(binding_accept),
        "why": ("an accepted decision in a binding mode must prove the gate that governed it"
                if binding_accept else
                "a cited rule declares the feature" if owed else
                "no cited rule declares it, and this is not a binding admission"),
    }


def check_freshness_proof(record: Mapping[str, Any]) -> list:
    """Every problem with one record's freshness proof, as sentences. Empty means fine.

    A record that owes nothing returns `[]` — and that is a real answer, not a skipped check:
    a cap refusal never consulted the freshness gate and a record that claimed it had would
    be inventing a proof.
    """
    p = freshness_proof(record)
    errs: list = []
    # Fails closed on anything that is not a record. A row with no `record_type` owes nothing
    # by the rules below and would sail through — which is how a malformed line becomes a
    # passing check. It is not this function's job to validate the whole schema, but it is
    # its job not to certify something it could not read.
    if record.get("record_type") not in RECORD_TYPES:
        return [f"record_type {record.get('record_type')!r} is not one of {RECORD_TYPES}; "
                f"a row this check cannot recognise is not a row it may certify"]
    # Every DECISION record owes the RUN's freshness observation as a typed field, whatever
    # its verdict. Measured 2026-08-24: the writer already puts it in `inputs_summary`, so
    # this is a contract being written down, not a new demand — and it is the check that
    # makes prose fail, because the substring test it replaces passed any row containing the
    # word anywhere.
    if record.get("record_type") == DECISION and not p["observed_is_bool"]:
        errs.append(f"a DECISION record carries no boolean "
                    f"inputs_summary[{FRESHNESS_FEATURE!r}]; the run's freshness verdict is "
                    f"not recorded, and the word appearing in prose is not a record of it")
    if not p["owed"]:
        return errs
    if p["binding_accept"] and not p["cited"]:
        errs.append(
            f"an ACCEPTED decision in {record.get('decision_mode')!r} does not cite "
            f"{[r for r in ACCEPTED_PROOF_RULES_BY_MODE.get(record.get('decision_mode'), ()) if FRESHNESS_FEATURE in (RULES[r].features if r in RULES else ())]}; "
            f"it cites {list(record.get('rule_ids') or [])}")
    if not p["present"]:
        errs.append(f"owes a {FRESHNESS_FEATURE!r} feature and carries none; the word "
                    f"appearing in prose is not a proof")
        return errs
    if not isinstance(p["value"], bool):
        errs.append(f"{FRESHNESS_FEATURE} value is {p['value']!r}, not a boolean — an "
                    f"unmeasured proof is not a proof")
    if not isinstance(p["passed"], bool):
        errs.append(f"{FRESHNESS_FEATURE} carries no boolean `passed`")
    elif p["binding_accept"] and p["passed"] is False:
        errs.append("an admission was recorded in a binding mode with a FAILED freshness "
                    "proof — the writer refuses to build this, so a record shaped like it "
                    "on disk was not written by this module")
    return errs


def freshness_context_records(records: Iterable[Mapping[str, Any]]) -> list:
    """The run-context freshness observations in a set of rows.

    One per live slot since Stage 5Q-2, because each slot writes its own file. A day with
    ledger rows and none of these is a day whose freshness verdict nobody recorded.
    """
    out = []
    for r in records:
        if (r.get("record_type") == NO_ACTION
                and FRESHNESS_CONTEXT_RULE in [str(x) for x in (r.get("rule_ids") or [])]):
            out.append(r)
    return out


# ── introspection ────────────────────────────────────────────────────────────
def registry() -> dict:
    """The whole rule table as data. What the schema document is generated FROM."""
    return {
        "schema_version": SCHEMA_VERSION,
        "route": ROUTE,
        "record_types": list(RECORD_TYPES),
        "statuses": list(STATUSES),
        "status_for_type": {k: list(v) for k, v in STATUS_FOR_TYPE.items()},
        "reason_codes": list(REASON_CODES),
        "rejection_reasons": sorted(REJECTION_REASONS),
        "required_fields": list(REQUIRED_FIELDS),
        "accepted_proof_rules": list(ACCEPTED_PROOF_RULES),
        "shadow_root": SHADOW_ROOT,
        "sleeve_instruments": {k: list(v) for k, v in SLEEVE_INSTRUMENTS.items()},
        "rules": {rid: r.as_dict() for rid, r in sorted(RULES.items())},
    }


def self_check() -> list:
    """Problems with the REGISTRY itself, not with any record.

    Asserts what a reader would otherwise take on trust: every rule id matches its own
    code_ref, no rule claims a scope that is not a Track 1 sleeve, and every rule cites
    something.
    """
    out: list = []
    scopes = set(SLEEVE_INSTRUMENTS) | {"shared"}
    for rid, rule in sorted(RULES.items()):
        if rule.code_ref.rule_id != rid:
            out.append(f"{rid}: its code_ref names {rule.code_ref.rule_id!r}")
        if rule.scope not in scopes:
            out.append(f"{rid}: scope {rule.scope!r} is not a sleeve or 'shared'")
        if not rule.evidence:
            out.append(f"{rid}: cites no test, report or artifact")
        for e in rule.evidence:
            if e.kind not in EVIDENCE_KINDS:
                out.append(f"{rid}: evidence kind {e.kind!r} not in {EVIDENCE_KINDS}")
        if not rule.description.strip():
            out.append(f"{rid}: has no description")
        if not rule.features:
            out.append(f"{rid}: requires no feature, so an explanation citing it could "
                       f"carry no measured value at all")
    return out


def missing_code_files(root: str | Path = ".") -> list:
    """Rules whose `file` does not exist under `root`. Measured, not assumed."""
    base = Path(root)
    return sorted({r.code_ref.file for r in RULES.values()
                   if not (base / r.code_ref.file).exists()})


def missing_evidence_files(root: str | Path = ".") -> list:
    """Evidence paths that do not exist under `root`.

    Reported rather than raised: a rule may legitimately cite a report that has not been
    written yet, and refusing to import the module over it would be worse. But the number
    must be visible, because an evidence list nobody checks is the prose-only registry
    `track1_gates` was built to replace.
    """
    base = Path(root)
    out = set()
    for r in RULES.values():
        for e in r.evidence:
            if not (base / e.path).exists():
                out.add(e.path)
    return sorted(out)
