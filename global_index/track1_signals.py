"""global_index/track1_signals.py — the Track 1 signal diagnostics journal. NEW FILE.

Stage 5ZD. **Observability only. Nothing here can place an order, and nothing here changes a
decision.** It imports no broker, no executor, and no order journal, and a test proves it.

What it is for
--------------
The window ledger answers *"did anyone look?"* and the audit answers *"did the window hold
together?"*. Neither answers the question an operator actually asks at 10:05 in the morning:

    the slot ran and decided nothing — WHY?

`candidates: 0` is not that answer. It is the shape of an answer, and after four stages of
removing exactly this pattern from the broker reads it should not survive on the strategy side.
A slot that found nothing must be able to say *which rule failed, on what value, against what
threshold* — otherwise "no signal" and "the sleeve never got as far as looking" are the same
row, and they are entirely different days.

Five statuses, and they are deliberately not collapsible
---------------------------------------------------------
    SLOT_REFUSED             the gate or the live source said no; the sleeve never ran
    NO_SIGNAL                the sleeve ran, looked, and no rule produced a candidate
    RAW_SIGNAL_FOUND         a candidate exists and has not been through admission yet
    SIGNAL_REJECTED          a candidate existed and a NAMED layer refused it
    SIGNAL_ACCEPTED_SHADOW   the book admitted it, and no order was attempted

`NO_SIGNAL` and `SIGNAL_REJECTED` are the pair worth guarding: one means the market offered
nothing, the other means the market offered something and this route declined it. A summary
that showed both as "no trade" would hide every cap, every family limit and every suppression.

A missed slot is NOT a row here
-------------------------------
If a slot never spawned, it writes nothing. Its absence belongs to schedule-status and the
post-window audit as `SLOT_MISSED`. Manufacturing a `NO_SIGNAL` row for a slot that never ran
would turn "the machine was asleep" into "the strategy looked and declined", which is the
single most misleading thing this file could do — and on 2026-08-25 the machine slept through
the whole Calm window, so this is not hypothetical.

Best effort, and honest about it
---------------------------------
Writing fails soft, exactly like `window_ledger._write`: diagnostics must never break a slot,
because a slot that dies recording why it did nothing is worse than one that quietly records
less. But the failure is REMEMBERED — `last_error()` returns it, the reader surfaces it, and a
disabled channel reports as disabled rather than as an empty day.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = 1
ROUTE = "track1_candidate"

#: Under the route's own runtime tree, beside window_coverage and slot_timing. Never scratch:
#: this is evidence, and evidence that lives in a scratch directory is evidence somebody
#: deletes while tidying up.
SIGNALS_DIR = "global_index/track1_runtime/signals"

# ── the five statuses ────────────────────────────────────────────────────────────────────
SLOT_REFUSED = "SLOT_REFUSED"
NO_SIGNAL = "NO_SIGNAL"
RAW_SIGNAL_FOUND = "RAW_SIGNAL_FOUND"
SIGNAL_REJECTED = "SIGNAL_REJECTED"
SIGNAL_ACCEPTED_SHADOW = "SIGNAL_ACCEPTED_SHADOW"

STATUSES: tuple = (SLOT_REFUSED, NO_SIGNAL, RAW_SIGNAL_FOUND, SIGNAL_REJECTED,
                   SIGNAL_ACCEPTED_SHADOW)

#: Reported by schedule-status and the audit, NEVER written into this journal. Named here so
#: the vocabulary is in one place and a reader can render it beside the real statuses.
SLOT_MISSED = "SLOT_MISSED"

#: The slot DID run and left no diagnostics row. Distinct from SLOT_MISSED, and the distinction
#: is not academic: on the day this was built, 22 NKD slots had already run before the journal
#: existed. Rendering those as MISSED would have said the scheduler failed when it had not.
#: Also covers a slot whose diagnostics channel was disabled by a write failure.
SLOT_NO_ROW = "SLOT_NO_ROW"

#: Which layer refused a candidate. A rejection with no layer is a rejection nobody can act on.
LAYER_FRESHNESS = "freshness"
LAYER_ADMISSION = "admission"
LAYER_CAP = "cap"
LAYER_SAME_SYMBOL = "same_symbol"
LAYER_WINDOW = "window"
LAYER_ROUTE_SWITCH = "route_switch"
LAYERS: tuple = (LAYER_FRESHNESS, LAYER_ADMISSION, LAYER_CAP, LAYER_SAME_SYMBOL,
                 LAYER_WINDOW, LAYER_ROUTE_SWITCH)

#: The 70 strategy slots are the only ones that may write here. Safety, max-hold, stop-repair,
#: audit, pre-flight and the SPY refresh are operations health, not signal diagnostics — and a
#: stop-repair job writing "NO_SIGNAL" would be a category error a reader could not undo.
STRATEGY_SLEEVES: tuple = ("roska4_calm", "roska4_stress", "roska4_swing", "global_nkd")

MEASURED = "measured"
NOT_REACHED = "not_reached"
NOT_EXPOSED = "not_exposed_by_sleeve"
SOURCES: tuple = (MEASURED, NOT_REACHED, NOT_EXPOSED)

_disabled = False
_last_error: "str | None" = None


class SignalJournalRefused(ValueError):
    """A row that must not be written. Raised at BUILD time, never at write time.

    The split matters: a malformed row is a programming error and should stop a test, while a
    full disk is an operational event that must not stop a slot.
    """


# ── the structured rule check ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RuleCheck:
    """One strategy rule, with the number that decided it.

    `value` and `threshold` are what make this different from a log line. "breadth failed" is
    prose; "breadth 2 < 4" is a measurement, and only the second lets someone reading at
    10:05 know whether the day was close or nowhere near.
    """

    rule: str
    passed: "bool | None"
    value: Any = None
    threshold: Any = None
    comparator: str = ""
    detail: str = ""
    #: True when the sleeve never got far enough to evaluate this rule. Distinct from
    #: `passed=False`: "not reached" and "checked and failed" are different facts, and the
    #: nearest-miss report is wrong if it confuses them.
    not_reached: bool = False
    #: WHERE the answer came from, and the third value is the honest one.
    #:
    #:   measured               the slot computed it and `value` is real
    #:   not_reached            the sleeve stopped before this rule
    #:   not_exposed_by_sleeve  the rule DID run, inside the detector, and the detector does
    #:                          not return its value yet
    #:
    #: The third exists because the alternative was to re-implement the sleeve rules here to
    #: fill in numbers, and a second copy of a strategy rule is a copy that silently disagrees
    #: with the one that trades. "Not measured" and "measured and fine" must not look alike.
    source: str = MEASURED

    def as_row(self) -> dict:
        return asdict(self)


def rule(name: str, passed=None, value=None, threshold=None, comparator="", detail="",
         source: str = MEASURED) -> RuleCheck:
    """One check. `source` decides what `passed=None` MEANS, so it is never ambiguous."""
    if source not in SOURCES:
        raise SignalJournalRefused(f"{source!r} is not one of {SOURCES}")
    if source != MEASURED:
        passed = None
    return RuleCheck(rule=name, passed=(None if passed is None else bool(passed)),
                     value=value, threshold=threshold, comparator=comparator,
                     detail=detail, not_reached=(source == NOT_REACHED), source=source)


# ── the per-sleeve rule catalogue, derived from the params ───────────────────────────────

#: The rule NAMES each sleeve must be able to report on. Declared so a reader can tell
#: "this rule passed" from "this sleeve never mentioned this rule", and so a test can assert
#: the catalogue rather than a hand-written list that drifts.
#:
#: The order is the order they are evaluated in, which is what makes "primary failed rule"
#: mean something: the first failure is the one that stopped the sleeve.
RULES: dict = {
    "roska4_calm": ("regime_is_calm_d1", "prior_rth_close_bottom_third",
                    "prior_rth_down_close", "gap_not_deep", "entry_time_valid",
                    "stop_risk_computed"),
    # Stage 5ZZZ-AP. `wide_count` added: the detector's own `_ENTRY_CHECKS` names four entry
    # conditions and `entry_conditions` is `all()` over that tuple, so all four decide. Three
    # were declared. The declared name is the detector's own, as `gapdown_count` and
    # `avg_gap` already are -- a synonym would have been a third vocabulary.
    "roska4_stress": ("no_regime_label_required", "breadth_down_count", "gapdown_count",
                      "wide_count",
                      "avg_gap", "mnq_only_short_setup", "pre_high_stop_reference",
                      "stop_within_max_pct", "rr_target_computed",
                      "same_symbol_suppression", "family_cap", "cluster_cap"),
    # Stage 5ZZZ-AO. Both entries were measured against what the detector ACTUALLY runs, by
    # running it and reading the gates it reported, rather than against what the table said.
    #
    # Swing gained `regime_lag_1`. It always ran one: `_strategy` sets `allowed_regimes` from
    # a single module constant shared with NKD, and the live path wraps its labels in
    # `RegimeLabels(lag_days=1)` exactly as NKD does. So on a Calm day both sleeves stop for
    # the same reason, and only NKD's panel could say so.
    #
    # NKD gained the volume pattern and the SPY short gate. It runs both — the same
    # `TrendFollowStrategy` and the same `make_signal_fn` wrapper Swing uses — and declared
    # neither. Measured on one real session: the volume pattern refuses 20 of 22 bars, so the
    # rule the panel omitted was the one deciding the outcome.
    "roska4_swing": ("regime_lag_1", "ema50_filter", "r4_prior_range_filter",
                     "entry_bar_volume_filter",
                     "spy_d1_close_below_sma50_short_filter", "fixed_stop_2x_daily_atr",
                     "stop_arm_rule", "admission_cap_result"),
    "global_nkd": ("regime_lag_1", "ema10_filter", "entry_bar_volume_filter",
                   "spy_d1_close_below_sma50_short_filter", "japan_session_window",
                   "fixed_stop_2x_daily_atr", "max_hold_context", "admission_cap_result"),
}


#: Stage 5ZZZ-AJ. Names in `RULES` that are NOT entry conditions, and the reason for each.
#:
#: Declared HERE, one line under the table it qualifies, so the two cannot drift apart. A copy
#: of this list kept in the dashboard would be a copy that goes stale the first time a rule is
#: renamed, and the panel would then quietly promote an exit parameter back into the entry
#: lanes without anyone deciding to.
#:
#: These stay in `RULES` and stay on the evidence row: taking them out would change the shape
#: of a record that sessions already on disk were written in, and the fact that the sleeve
#: declares them is itself worth keeping. What changes is only how a panel may present them —
#: as configuration that IS, not as a test awaiting a verdict it can never receive.
#:
#: Measured across every stored session (291 slot records, 5 days, three sleeves): not one of
#: the 24 declared rules has ever carried a verdict. For the twenty-one others that is a gap
#: waiting on the detector to report which gate it stopped at. For these three it is not a gap
#: — there is no verdict for them to report, and a lane that must stay empty forever is a lane
#: an operator learns to skip, taking the twenty-one that CAN fill with it.
NOT_ENTRY_CONDITIONS: dict = {
    "japan_session_window":
        "not a test — the window is applied by slicing the bars before the detector runs, so "
        "every bar it evaluates is inside the window by construction and none can fail it",
    "max_hold_context":
        "an EXIT parameter — how many days a position may be held. At entry time there is no "
        "position to measure it against",
    "stop_arm_rule":
        "an EXIT parameter — when the stop is armed AFTER an entry exists, and how long the "
        "position may run. Nothing about it is decided at the moment of entry",
    # Stage 5ZZZ-BG. Asked on the panel: if nothing is required, why is the row there at all?
    # Because the ABSENCE is the fact. Three sleeves gate on the regime label and this one
    # deliberately does not, which is the answer to "why was NKD blocked all night by Calm
    # while Stress kept running". But it is a property of the sleeve, not a test a slot takes,
    # so it belongs beside the declared configuration rather than in a lane that can never
    # fill. The behaviour itself is pinned by `test_the_rule_uses_no_regime_label_at_all`,
    # which builds a source with NO labels at all and requires the candidate to appear anyway.
    "no_regime_label_required":
        "not a test — the sleeve was built to avoid the lag-0 daily regime label, so the "
        "detector never asks for one and no slot can fail this. Declared so the difference "
        "from the three sleeves that DO gate on regime is visible rather than inferred",
}


#: Stage 5ZZZ-AO. The bridge between the two vocabularies, in ONE place.
#:
#: The detectors name their own gates; this table names what a sleeve DECLARES it checks. The
#: two were never reconciled, and the drift showed up as rules the panel listed but nobody
#: evaluated, and rules the engine ran that the panel never mentioned.
#:
#: Kept as a mapping rather than by renaming one side to the other, and the reason is the
#: blast radius: five committed test files pin the declared names, and the declared names
#: carry the sleeve's own parameter (`ema10` vs `ema50`) where the engine's single
#: `ema_proximity` cannot. What makes a mapping safe is not care — it is that a test RUNS the
#: detectors and asserts this table is total in both directions. A hand-checked mapping is a
#: mapping that drifts on the first rule anybody adds.
#:
#: One declared name may answer TWO emitted gates: the engine decides the volume pattern in
#: two halves with different thresholds, and on one measured session each half refused ten of
#: the twenty-two bars. The halves stay separate where they are drawn; the declared table
#: names the rule once.
EMITTED_TO_DECLARED: dict = {
    "regime": "regime_lag_1",
    "volume_pullback_declined": "entry_bar_volume_filter",
    "volume_resume_surge": "entry_bar_volume_filter",
    "spy_short_gate": "spy_d1_close_below_sma50_short_filter",
    "r4_context_filter": "r4_prior_range_filter",
    "fixed_stop_daily_atr": "fixed_stop_2x_daily_atr",
    # Stress reports through its own path -- `entry_checks`, derived from the same
    # `_ENTRY_CHECKS` tuple the decision is `all()` over.
    "below_count": "breadth_down_count",
    "gapdown_count": "gapdown_count",
    "wide_count": "wide_count",
    "avg_gap": "avg_gap",
}

#: Where one emitted gate answers to a DIFFERENT declared name per sleeve. Only the trend
#: filter does: the engine has one `ema_proximity`, and each sleeve declares it with its own
#: period so a reader can see which one at a glance.
EMITTED_TO_DECLARED_BY_SLEEVE: dict = {
    "global_nkd": {"ema_proximity": "ema10_filter"},
    "roska4_swing": {"ema_proximity": "ema50_filter"},
}


#: Which CHANNEL a gate is reported through, and it decides where a rule can be DRAWN.
#:
#: The observer keeps two lists for a reason measured on 2026-08-10: within ONE slot the
#: volume rule came back twelve times pass and ten times fail, because the detector answers it
#: once per BAR while a slot is a moment of asking. A grid cell keyed on the slot therefore has
#: no single value -- which is why every one of these rules read "value not published" on all
#: 291 slot records ever written, and why exactly the two that ARE answered once per slot,
#: `gate_allow` and `freshness_allow`, are the only two that ever carried a verdict.
#:
#: `regime` appears in BOTH lists: the detector answers it once for the slot and the engine
#: answers it again for every bar. The slot-level answer is the one a lane can hold, so it is
#: NOT classified as per-bar.
SLOT_LEVEL_GATES: frozenset = frozenset({"session_bars", "regime", "daily_atr",
                                         "bars_so_far", "setup_bar"})
PER_BAR_GATES: frozenset = frozenset({"regime", "ema_proximity", "volume_pullback_declined",
                                      "volume_resume_surge", "spy_short_gate",
                                      "r4_context_filter", "fixed_stop_daily_atr"})


def per_bar_rule_names(sleeve: str) -> tuple:
    """Declared rules whose only answer is per BAR, so a per-SLOT cell cannot hold one.

    Stress is untouched by this: its detector has no bar channel at all -- `entry_conditions`
    is `all()` over four basket-wide checks answered once per slot -- so none of its gates are
    in `PER_BAR_GATES` and none of its lanes move.
    """
    declared = set(RULES.get(sleeve, ()))
    slot_answerable = {declared_for(sleeve, g) for g in SLOT_LEVEL_GATES} - {None}
    per_bar = {declared_for(sleeve, g) for g in PER_BAR_GATES} - {None} - slot_answerable
    return tuple(n for n in RULES.get(sleeve, ()) if n in per_bar and n in declared)


def declared_for(sleeve: str, emitted: str) -> "str | None":
    """The declared rule an emitted gate answers to, or None when nothing declares it.

    None is the finding, not an error: it means the detector runs something the sleeve does
    not admit to running.
    """
    per = EMITTED_TO_DECLARED_BY_SLEEVE.get(sleeve, {})
    if emitted in per:
        return per[emitted]
    if emitted in EMITTED_TO_DECLARED:
        return EMITTED_TO_DECLARED[emitted]
    # Stage 5ZZZ-AT. The IDENTITY case, and it is not a fallback: Calm has one source of truth
    # for its rules, so its detector emits the declared names themselves and there is nothing
    # to bridge. Returning None here would have said "the detector runs a rule nobody declares"
    # about a sleeve whose two vocabularies are the same vocabulary.
    #
    # Only for a name the sleeve actually declares. An unknown name still comes back None,
    # which is what the drift test reads as the finding it is.
    if emitted in RULES.get(sleeve, ()):
        return emitted
    return None


def rule_names(sleeve: str) -> tuple:
    return RULES.get(sleeve, ())


def entry_rule_names(sleeve: str) -> tuple:
    """`rule_names` minus the ones that can never carry an entry-time verdict."""
    return tuple(n for n in RULES.get(sleeve, ()) if n not in NOT_ENTRY_CONDITIONS)


def thresholds(sleeve: str) -> dict:
    """The declared thresholds, READ FROM THE PARAMS rather than restated here.

    A second copy of `breadth_min = 4` in this file is a copy that goes stale the first time
    anyone tunes the sleeve, and a diagnostics row carrying a stale threshold is worse than one
    carrying none: it would report a rule as failing against a number nobody uses.
    """
    if sleeve == "roska4_calm":
        from global_index.track1_calm_a import CalmAParams
        p = CalmAParams()
        return {"regime_is_calm_d1": {"label": p.calm_label, "lag": p.regime_lag_sessions},
                "prior_rth_close_bottom_third": {"close_loc_max": p.close_loc_max},
                "prior_rth_down_close": {"prev_ret_max": p.prev_ret_max},
                "gap_not_deep": {"gap_min": p.gap_min},
                "entry_time_valid": {"entry_time": p.entry_time},
                "stop_risk_computed": {"disaster_stop_atr_mult": p.disaster_stop_atr_mult}}
    if sleeve == "roska4_stress":
        from global_index.track1_stress_mnq import StressParams
        p = StressParams()
        return {"no_regime_label_required": {"regime_label": None},
                "breadth_down_count": {"breadth_min": p.breadth_min},
                "gapdown_count": {"gapdown_min": p.gapdown_min, "gapdown_at": p.gapdown_at},
                # Stage 5ZZZ-AP. `wide_count` is one of the FOUR entry checks the Stress
                # detector runs -- `entry_conditions` is `all()` over `_ENTRY_CHECKS`, and it
                # is in that tuple -- and nothing declared it. Threshold read from the params
                # the detector compares against, never restated.
                "wide_count": {"wide_min": p.wide_min},
                "avg_gap": {"avg_gap_max": p.avg_gap_max},
                "mnq_only_short_setup": {"instruments": list(p.instruments),
                                         "qty": p.qty},
                "pre_high_stop_reference": {"setup_time": p.setup_time,
                                            "min_pre_bars": p.min_pre_bars},
                "stop_within_max_pct": {"max_stop_pct": p.max_stop_pct},
                "rr_target_computed": {"rr": p.rr},
                "same_symbol_suppression": {}, "family_cap": {}, "cluster_cap": {}}
    if sleeve in ("roska4_swing", "global_nkd"):
        from global_index.track1_normal_r4 import NormalR4Params
        p = NormalR4Params(ema_period=10) if sleeve == "global_nkd" else NormalR4Params()
        out = {"fixed_stop_2x_daily_atr": {"stop_basis_atr_mult": p.stop_basis_atr_mult},
               "admission_cap_result": {}}
        if sleeve == "roska4_swing":
            out.update({"ema50_filter": {"ema_period": p.ema_period},
                        "r4_prior_range_filter": {"range_max": p.range_max},
                        "entry_bar_volume_filter": {"rel_volume_max": p.rel_volume_max,
                                                    "vol_feature": p.vol_feature},
                        "spy_d1_close_below_sma50_short_filter": {
                            "spy_short_filter": p.spy_short_filter},
                        "stop_arm_rule": {"arm_hours": p.arm_hours,
                                          "max_hold_days": p.max_hold_days}})
        else:
            out.update({"ema10_filter": {"ema_period": p.ema_period},
                        "japan_session_window": {"clock": "Asia/Tokyo"},
                        "max_hold_context": {"max_hold_days": p.max_hold_days}})
        # Shared by both sleeves, because the detector applies them to both. `regime_lag_1`
        # was NKD-only and the volume/short pair was Swing-only; neither split existed in the
        # code that decides.
        out.update({"regime_lag_1": {"lag": 1},
                    "entry_bar_volume_filter": {"rel_volume_max": p.rel_volume_max,
                                                "vol_feature": p.vol_feature},
                    "spy_d1_close_below_sma50_short_filter": {
                        "spy_short_filter": p.spy_short_filter}})
        return out
    return {}


# ── the row ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SignalRow:
    """One Track 1 strategy slot's diagnostics. Flat enough to read back after a crash."""

    session_date: str
    sleeve: str
    slot_id: str
    slot_time: str
    mode: str
    status: str
    reason: str = ""
    detail: str = ""
    raw_candidates: int = 0
    accepted: int = 0
    rejected: int = 0
    params_hash: str = ""
    #: Stage 5ZZZ-Q. Which regime object the sleeve's detector was handed - `causal_d1` for the
    #: two Normal-R4 sleeves and for Calm's entry gate, `intraday_basket_gate` for Stress.
    #: Added because Stage 5ZZZ-P could not tell, from any recorded row, whether the live Swing
    #: detector read the previous session's label or the session's own. For eight stages the
    #: signed paper identity said one and the detector did the other, and nothing on disk said
    #: which. Defaulted to "" so every row written before this stage stays readable and is
    #: reported as UNKNOWN rather than being assumed to match.
    regime_basis: str = ""
    data_source_identity: str = ""
    freshness_allow: "bool | None" = None
    freshness_proof: str = ""
    rule_checks: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    rejecting_layer: str = ""
    route: str = ROUTE
    schema: int = SCHEMA
    #: Constant in shadow, and written on EVERY row rather than inferred by a reader. A row
    #: that merely omitted them would let a future reader assume the wrong default, and the
    #: whole point of this journal is that it can be read years later by someone who was not
    #: here.
    orders_enabled: bool = False
    order_attempted: bool = False

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise SignalJournalRefused(
                f"{self.status!r} is not one of {STATUSES}; a status a reader cannot "
                f"classify is worse than no row")
        if self.sleeve not in STRATEGY_SLEEVES:
            raise SignalJournalRefused(
                f"{self.sleeve!r} is not a strategy sleeve. Safety, max-hold, stop-repair, "
                f"audit, pre-flight and the SPY refresh are operations health and must never "
                f"write signal diagnostics")
        if self.status == SIGNAL_ACCEPTED_SHADOW:
            if self.order_attempted or self.orders_enabled:
                raise SignalJournalRefused(
                    "an accepted SHADOW signal cannot report an order attempt; that is the "
                    "one claim this journal exists to make impossible")
            if not self.reason:
                self.reason = "shadow_only"
        if self.status == SIGNAL_REJECTED and self.rejecting_layer not in LAYERS:
            raise SignalJournalRefused(
                f"a rejection needs a named layer, got {self.rejecting_layer!r}; "
                f"known: {LAYERS}")
        if self.status in (NO_SIGNAL, SIGNAL_REJECTED, SIGNAL_ACCEPTED_SHADOW) \
                and not self.rule_checks:
            raise SignalJournalRefused(
                f"{self.status} without rule_checks is `candidates: 0` wearing a longer name; "
                f"the whole point is to say WHICH rule decided it")

    def as_row(self) -> dict:
        d = asdict(self)
        d["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        d["rule_checks"] = [c.as_row() if isinstance(c, RuleCheck) else dict(c)
                            for c in self.rule_checks]
        return d


# ── classification ───────────────────────────────────────────────────────────────────────

def classify(*, decided: bool, reason: str, raw_candidates: int, accepted: int,
             rejected: int) -> str:
    """The status, from what the slot actually did. Explicit branches, no fallthrough.

    Written as a separate pure function so the one thing that must never collapse — NO_SIGNAL
    against SIGNAL_REJECTED — is decided in a place a test can drive directly with every
    combination rather than only through a whole slot run.
    """
    if not decided:
        return SLOT_REFUSED
    if raw_candidates <= 0:
        return NO_SIGNAL
    if accepted > 0:
        return SIGNAL_ACCEPTED_SHADOW
    if rejected > 0:
        return SIGNAL_REJECTED
    # A candidate existed, nothing admitted it and nothing rejected it: it has not been
    # through admission. Saying NO_SIGNAL here would erase the candidate entirely.
    return RAW_SIGNAL_FOUND


def primary_failure(checks: Sequence) -> dict:
    """The first rule that failed, plus the ones after it — the "nearest miss" report.

    First rather than worst, because the rules are evaluated in order and the first failure is
    the one that stopped the sleeve. Everything after it was never reached, and reporting a
    later rule as the cause would send someone to look at the wrong thing.
    """
    rows = [c.as_row() if isinstance(c, RuleCheck) else dict(c) for c in checks]
    failed = [c for c in rows if c.get("passed") is False]
    nreached = [c for c in rows if c.get("source") == NOT_REACHED or c.get("not_reached")]
    unexposed = [c for c in rows if c.get("source") == NOT_EXPOSED]
    return {
        "primary_failed_rule": failed[0]["rule"] if failed else None,
        "primary_failed": failed[0] if failed else None,
        "nearest_failed_rules": [c["rule"] for c in failed[:3]],
        "not_reached": [c["rule"] for c in nreached],
        # Reported separately and never folded into "passed". A rule whose value the sleeve
        # does not expose has NOT been shown to be fine.
        "not_exposed_by_sleeve": [c["rule"] for c in unexposed],
        "failed_count": len(failed),
    }


# ── building a row from what the slot actually knows ─────────────────────────────────────

def _candidate_brief(c: Any, *, sleeve: str) -> dict:
    """The candidate fields a reader needs to judge a rejection, and no more."""
    g = (lambda k, d=None: getattr(c, k, d))
    out = {
        "instrument": str(g("instrument", "") or ""),
        "direction": str(g("direction", "") or ""),
        "qty": g("qty"),
        "entry": g("entry_price"),
        "stop": g("stop_price"),
        "risk": g("risk_dollars"),
        "trade_id": str(g("trade_id", "") or ""),
    }
    try:
        from global_index import track1_params as tp
        out["tradable_symbol"] = tp._contract(out["instrument"]).ibkr
    except Exception:
        # The identity split is worth reporting when available and is not worth failing a
        # diagnostics row over. `""` says "not resolved", which is not the same as wrong.
        out["tradable_symbol"] = ""
    meta = g("meta") or {}
    if isinstance(meta, Mapping) and meta.get("target") is not None:
        out["target"] = meta.get("target")
    return out


def _layer_for(verdict: Any) -> str:
    """Map the book's own verdict vocabulary onto a named layer.

    Kept as an explicit table rather than a substring match: `reject_cap` and
    `reject_family_cap` are different layers and a `startswith("reject_")` would flatten them
    into one, which is precisely the distinction an operator needs.
    """
    from global_index import track1_signal_layer as T

    return {
        getattr(T, "REJECT_CAP", "reject_cap"): LAYER_CAP,
        getattr(T, "REJECT_FAMILY_CAP", "reject_family_cap"): LAYER_CAP,
        getattr(T, "REJECT_WINDOW", "reject_window"): LAYER_WINDOW,
        getattr(T, "SUPPRESS_SAME_SYMBOL", "suppress_same_symbol"): LAYER_SAME_SYMBOL,
        getattr(T, "SUPPRESS_SAME_SLEEVE", "suppress_same_sleeve"): LAYER_SAME_SYMBOL,
        getattr(T, "HALT_BREAKER", "halt_breaker"): LAYER_ADMISSION,
        getattr(T, "STRESS_DISPLACES", "stress_displaces"): LAYER_ROUTE_SWITCH,
    }.get(str(verdict), LAYER_ADMISSION)


def rule_checks_for(sleeve: str, *, decided: bool, freshness_allow, gate_allow,
                    gate_codes: Sequence = (), decisions: Sequence = (),
                    raw_candidates: int = 0,
                    measured: "Mapping | None" = None) -> list:
    """The declared rules for this sleeve, each answered as honestly as the slot can.

    Three answers are possible and all three are visible:

      * measured               the slot computed it — freshness, the gate, admission and the
                               caps are all decided OUTSIDE the detector, so their values are
                               real here;
      * not_reached            the sleeve stopped before this rule ran;
      * not_exposed_by_sleeve  the rule ran INSIDE the detector, which does not return its
                               value yet.

    The third is the one that matters. The alternative was to recompute breadth, EMA and the
    gap here so every row carried a number — and a second implementation of a strategy rule is
    a second answer to the same question, which is the defect this project has paid for more
    than once. A rule reported as `not_exposed_by_sleeve` has NOT been shown to be fine, and
    the reader keeps it out of the "passed" count.
    """
    th = thresholds(sleeve)
    names = rule_names(sleeve)
    out: list = []

    # Everything a refused slot can say: the sleeve never ran, so no strategy rule was reached.
    if not decided:
        out.append(rule("gate_allow", passed=bool(gate_allow), value=list(gate_codes) or None,
                        threshold="no refusal codes", comparator="==",
                        detail="the intraday gate decides whether the slot may decide at all"))
        if freshness_allow is not None:
            out.append(rule("freshness_allow", passed=bool(freshness_allow),
                            comparator="==", threshold=True))
        for n in names:
            out.append(rule(n, source=NOT_REACHED,
                            detail="the slot was refused before the sleeve ran"))
        return out

    # The slot ran. Freshness and the gate are measured facts about it.
    out.append(rule("gate_allow", passed=bool(gate_allow) if gate_allow is not None else None,
                    value=list(gate_codes) or None, threshold="no refusal codes",
                    comparator="==",
                    source=MEASURED if gate_allow is not None else NOT_EXPOSED))
    if freshness_allow is not None:
        out.append(rule("freshness_allow", passed=bool(freshness_allow), comparator="==",
                        threshold=True,
                        detail="binding in shadow_live and armed"))

    # The strategy rules the detector owns. Named, with their real thresholds, and marked as
    # unexposed rather than silently passed.
    admission_names = {"same_symbol_suppression", "family_cap", "cluster_cap",
                       "admission_cap_result"}
    for n in names:
        if n in admission_names:
            continue
        # Stage 5ZZZ-AT. A rule the SLOT measured is reported as measured. `measured` carries
        # only what the detector itself answered once for this slot, mapped through the single
        # bridge in this file. Nothing here recomputes a rule.
        m = (measured or {}).get(n)
        if m is not None:
            out.append(rule(n, passed=m.get("passed"), value=m.get("value"),
                            threshold=m.get("threshold", th.get(n) or None),
                            comparator=str(m.get("comparator") or ""),
                            detail=str(m.get("detail") or ""), source=MEASURED))
            continue
        # A per-BAR rule has no single per-slot verdict -- it is answered once per bar and the
        # answers disagree inside one slot -- so it stays unexposed here and is drawn on the
        # bar grid, where every cell is one bar and holds exactly one answer.
        out.append(rule(n, threshold=th.get(n) or None, source=NOT_EXPOSED,
                        detail="evaluated inside the sleeve detector; value not returned yet"))

    # Admission and the caps ARE decided outside the detector, so these are measured.
    verdicts = [str(getattr(d, "verdict", "")) for d in decisions]
    from global_index import track1_signal_layer as T
    took = [v for v in verdicts if v == getattr(T, "TAKE", "take")]
    for n in names:
        if n not in admission_names:
            continue
        if raw_candidates <= 0:
            out.append(rule(n, source=NOT_REACHED,
                            detail="no candidate reached admission"))
        else:
            refused = [v for v in verdicts if v != getattr(T, "TAKE", "take")]
            out.append(rule(n, passed=not refused, value=refused or None,
                            threshold="admitted", comparator="==",
                            detail=f"{len(took)} admitted, {len(refused)} refused"))
    return out


def build_row(*, sleeve: str, slot_id: str, slot_time: str, session_date, mode: str,
              decided: bool, reason: str, detail: str = "", raw_candidates: int = 0,
              accepted: int = 0, rejected: int = 0, decisions: Sequence = (),
              candidates: Sequence = (), freshness_allow=None, gate_allow=None,
              gate_codes: Sequence = (), params_hash: str = "",
              data_source_identity: str = "", freshness_proof: str = "",
              regime_basis: str = "",
              measured_rules: "Mapping | None" = None) -> SignalRow:
    """A `SignalRow` from the state a slot already has. Pure: reads nothing, writes nothing."""
    status = classify(decided=decided, reason=reason, raw_candidates=raw_candidates,
                      accepted=accepted, rejected=rejected)
    checks = rule_checks_for(sleeve, decided=decided, freshness_allow=freshness_allow,
                             gate_allow=gate_allow, gate_codes=gate_codes,
                             decisions=decisions, raw_candidates=raw_candidates,
                             measured=measured_rules)

    briefs = [_candidate_brief(c, sleeve=sleeve) for c in (candidates or [])]
    layer = ""
    row_reason = reason
    if status == SIGNAL_REJECTED:
        from global_index import track1_signal_layer as T
        refusals = [d for d in decisions
                    if str(getattr(d, "verdict", "")) != getattr(T, "TAKE", "take")]
        if refusals:
            layer = _layer_for(getattr(refusals[0], "verdict", ""))
            row_reason = str(getattr(refusals[0], "verdict", "")) or reason
            note = str(getattr(refusals[0], "detail", "") or "")
            if note:
                detail = note[:200]
        else:
            layer = LAYER_ADMISSION
    if status == SIGNAL_ACCEPTED_SHADOW:
        row_reason = "shadow_only"

    return SignalRow(
        session_date=str(session_date), sleeve=sleeve, slot_id=slot_id,
        slot_time=slot_time, mode=mode, status=status, reason=row_reason,
        detail=str(detail or "")[:200], raw_candidates=int(raw_candidates),
        accepted=int(accepted or 0), rejected=int(rejected or 0),
        params_hash=params_hash, data_source_identity=data_source_identity,
        regime_basis=regime_basis,
        freshness_allow=freshness_allow, freshness_proof=freshness_proof,
        rule_checks=checks, candidates=briefs, rejecting_layer=layer)


# ── writing ──────────────────────────────────────────────────────────────────────────────

def signals_dir(root: str | Path = ".") -> Path:
    return Path(root) / SIGNALS_DIR


#: Stage 5ZZZ-AA. A test may opt IN to writing the production journal, for a deliberate
#: integration check. Nothing else may.
ALLOW_TEST_WRITE_ENV = "TRACK1_ALLOW_RUNTIME_WRITE_IN_TEST"


def _refuse_production_write_under_pytest(target: Path) -> None:
    """Refuse to append to the PRODUCTION signals journal from inside a test run.

    Stage 5ZZZ-Z ran the whole scratch suite without isolating output, and a test exercising
    the live Swing path appended two rows to the real journal on a Saturday. They had to be
    quarantined rather than deleted, because runtime evidence is append-only.

    The refusal is deliberately narrow. It fires only when BOTH are true: pytest is running,
    and the destination is the real `global_index/track1_runtime/` tree. A test writing under
    `tmp_path` - which is what a test should do - never sees this, and neither does the
    scheduler, which does not run under pytest. A test that genuinely means to write the real
    journal sets the opt-in env var and says so.
    """
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        return                                   # not a test run: the scheduler's normal path
    if os.environ.get(ALLOW_TEST_WRITE_ENV):
        return                                   # deliberate, opted-in integration write
    try:
        resolved = target.resolve()
    except OSError:                                                # noqa: BLE001
        resolved = target
    parts = [p.lower() for p in resolved.parts]
    if "track1_runtime" not in parts:
        return                                   # tmp_path or any other root: allowed
    raise SignalJournalRefused(
        f"refusing to write production runtime evidence from a test: {resolved}. "
        f"Point the test at tmp_path, or set {ALLOW_TEST_WRITE_ENV}=1 if the write is "
        f"deliberate. See Stage 5ZZZ-AA - two rows written this way had to be quarantined.")


def journal_path(day, root: str | Path = ".") -> Path:
    d = str(day).replace("-", "")
    if len(d) != 8 or not d.isdigit():
        raise SignalJournalRefused(f"{day!r} is not a YYYYMMDD day")
    return signals_dir(root) / f"track1_signals_{d}.jsonl"


def last_error() -> "str | None":
    """Why the channel is off, if it is. A disabled channel must not read as a quiet day."""
    return _last_error


def enabled() -> bool:
    return not _disabled


def append(row: SignalRow, *, root: str | Path = ".", day=None) -> "Path | None":
    """Append one row. Fails SOFT and remembers why.

    Deliberately unlike `track1_order_journal.append`, which raises. That one is a
    write-ahead log for something that moves money and must stop the caller; this one is
    observability and must never be the reason a slot dies. The difference is stated here
    because the two files otherwise look alike enough to be confused.
    """
    global _disabled, _last_error
    if not isinstance(row, SignalRow):
        raise SignalJournalRefused(f"expected a SignalRow, got {type(row).__name__}")
    target = journal_path(day or row.session_date, root)
    _refuse_production_write_under_pytest(target)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row.as_row(), ensure_ascii=False, default=str) + "\n"
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return target
    except Exception as exc:
        _disabled = True
        _last_error = f"{type(exc).__name__}: {exc}"
        return None


# ── reading ──────────────────────────────────────────────────────────────────────────────

def read_day(day, *, root: str | Path = ".") -> "tuple[list, list]":
    """`(rows, invalid)`. Invalid lines are returned, never dropped."""
    p = journal_path(day, root)
    if not p.exists():
        return [], []
    rows, bad = [], []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception as exc:
            bad.append(f"line {n}: {type(exc).__name__}: {exc}")
    return rows, bad


def days(root: str | Path = ".") -> list:
    d = signals_dir(root)
    if not d.is_dir():
        return []
    return sorted(p.name[len("track1_signals_"):-len(".jsonl")] for p in
                  d.glob("track1_signals_*.jsonl"))


def summary(day, *, root: str | Path = ".") -> dict:
    """The compact per-sleeve summary the dashboard renders. One small object, not a page.

    `present=False` is NOT an error. A day before the first slot has run has no file, and a
    reader that raised on that would make "the day has not started" look like a fault — the
    same conflation this route has spent four stages removing everywhere else.
    """
    rows, bad = read_day(day, root=root)
    p = journal_path(day, root)
    if not p.exists():
        return {"present": False, "day": str(day), "route": ROUTE,
                "reading": "not yet observed",
                "channel_disabled": not enabled(), "channel_error": last_error(),
                "sleeves": {}, "invalid": 0}

    out = {"present": True, "day": str(day), "route": ROUTE, "rows": len(rows),
           "invalid": len(bad), "invalid_detail": bad[:3],
           "channel_disabled": not enabled(), "channel_error": last_error(),
           "orders_enabled": False, "order_attempted": False, "sleeves": {}}
    for sleeve in STRATEGY_SLEEVES:
        mine = [r for r in rows if r.get("sleeve") == sleeve]
        if not mine:
            out["sleeves"][sleeve] = {"observed": 0, "reading": "not yet observed"}
            continue
        counts: dict = {}
        for r in mine:
            counts[r.get("status")] = counts.get(r.get("status"), 0) + 1
        latest = mine[-1]
        accepted = [r for r in mine if r.get("status") == SIGNAL_ACCEPTED_SHADOW]
        declined = [r for r in mine if r.get("status") in (SIGNAL_REJECTED, SLOT_REFUSED)]
        out["sleeves"][sleeve] = {
            "observed": len(mine),
            "counts": counts,
            "latest_status": latest.get("status"),
            "latest_slot_id": latest.get("slot_id"),
            "latest_slot_time": latest.get("slot_time"),
            "latest_reason": latest.get("reason"),
            "latest_accepted": _brief(accepted[-1]) if accepted else None,
            "latest_declined": _brief(declined[-1]) if declined else None,
        }
    return out


def _brief(row: Mapping) -> dict:
    c = (row.get("candidates") or [{}])[0]
    return {"slot_id": row.get("slot_id"), "slot_time": row.get("slot_time"),
            "status": row.get("status"), "reason": row.get("reason"),
            "rejecting_layer": row.get("rejecting_layer") or None,
            "instrument": c.get("instrument"), "direction": c.get("direction"),
            "risk": c.get("risk"),
            "order_attempted": bool(row.get("order_attempted"))}


# ── operator language ────────────────────────────────────────────────────────────────────
#
# Stage 5ZE. One owner for every string an operator reads, and it is here rather than in the
# browser for the same reason `one_line` is: two owners for a phrase is two places for them to
# disagree, and only one of them has tests.

#: Internal name -> what a human calls it. Used for the fields an operator is MEANT to see.
#: Setup rules are in here too, but see `operator_lines`: they are deliberately not rendered
#: for NO_SIGNAL until the sleeve actually returns a measured value, because a mapped name with
#: no number beside it is a longer way of saying nothing.
LABELS: dict = {
    # runtime, and these are the ones an operator acts on
    "gate_allow": "Runtime gate",
    "freshness_allow": "Freshness check",
    "live_frame_refused": "Live frame refused",
    "overlap_disagreement": "History/feed overlap disagreement",
    "no_bar_provider": "Bar provider unavailable",
    "live_source_not_ready": "Live source not ready",
    "gate_refused": "Runtime gate refused the slot",
    "freshness_refused": "Freshness check refused the slot",
    "stale": "Bars are stale",
    "partial_coverage": "Session bars incomplete",
    "gap_in_coverage": "Gap in the session bars",
    "too_late": "Slot fired after its window closed",
    "ledger_not_configured": "Evidence ledger not configured",
    # admission, which an operator also acts on
    "same_symbol_suppression": "Same-symbol rule",
    "family_cap": "Family cap",
    "cluster_cap": "Cluster cap",
    "admission_cap_result": "Admission and caps",
    # the sleeve's own setup rules
    "regime_is_calm_d1": "Prior-day regime is Calm",
    "prior_rth_close_bottom_third": "Prior close in the bottom third",
    "prior_rth_down_close": "Prior session closed down",
    "gap_not_deep": "Gap not too deep",
    "entry_time_valid": "Entry time valid",
    "stop_risk_computed": "Stop and risk computed",
    "no_regime_label_required": "No regime label required",
    "breadth_down_count": "Basket breadth",
    "gapdown_count": "Gap-down count",
    # Stage 5ZZZ-AP. Added with `wide_count` itself: a declared rule with no label renders as
    # its raw identifier, and the stage-5ZE guard caught exactly that within one run. The
    # wording follows the detector's own `_ENTRY_CHECKS` entry ("Instruments with a wide
    # range"), shortened for a lane the way its three neighbours already are — and the
    # vocabulary test asserts every declared Stress rule keeps a label, so a fifth check
    # cannot arrive without one.
    "wide_count": "Wide-range count",
    "avg_gap": "Average gap",
    "mnq_only_short_setup": "MNQ short setup",
    "pre_high_stop_reference": "Pre-window high (stop reference)",
    "stop_within_max_pct": "Stop within the maximum",
    "rr_target_computed": "Reward/risk target",
    "ema50_filter": "EMA50 filter",
    "ema10_filter": "EMA10 filter",
    "r4_prior_range_filter": "Prior-range filter",
    "entry_bar_volume_filter": "Entry-bar volume filter",
    "spy_d1_close_below_sma50_short_filter": "SPY below its 50-day average",
    "fixed_stop_2x_daily_atr": "Stop at 2x daily ATR",
    "stop_arm_rule": "Stop arming rule",
    "regime_lag_1": "Prior-day regime",
    "japan_session_window": "Japan session window",
    "max_hold_context": "Max-hold context",
}

#: The layers, in the words an operator would use.
LAYER_LABELS: dict = {
    LAYER_FRESHNESS: "Freshness check",
    LAYER_ADMISSION: "Admission",
    LAYER_CAP: "Position cap",
    LAYER_SAME_SYMBOL: "Same-symbol rule",
    LAYER_WINDOW: "Trading window",
    LAYER_ROUTE_SWITCH: "Route switch",
}

#: The chip an operator sees, and what it means in plain English. The tooltip is required —
#: a five-state chip with no explanation is five colours nobody can act on.
CHIPS: dict = {
    NO_SIGNAL: ("NO SIGNAL", "neutral",
                "Slot ran and reached the strategy layer; no setup matched."),
    RAW_SIGNAL_FOUND: ("RAW SIGNAL", "watch",
                       "A setup matched before admission/cap checks."),
    SIGNAL_REJECTED: ("REJECTED", "warn",
                      "A setup matched but was rejected by an admission, cap, or switch rule."),
    SIGNAL_ACCEPTED_SHADOW: ("ACCEPTED SHADOW", "good",
                             "Setup passed admission in shadow; no order was attempted."),
    SLOT_REFUSED: ("REFUSED", "muted",
                   "Slot did not reach strategy evaluation; see operational details."),
    SLOT_MISSED: ("MISSED", "bad", "Expected slot did not run."),
    SLOT_NO_ROW: ("NO DIAGNOSTICS", "muted",
                  "Job ran before signal diagnostics existed, or no signal row was written."),
}


def label(name: str) -> str:
    """A human name, or the raw one if nobody has named it.

    Falling back to the raw name is deliberate: a missing label should look wrong on the page
    so somebody adds one, rather than silently rendering an empty cell.
    """
    return LABELS.get(str(name), str(name))


def chip(status: str) -> dict:
    text, tone, tip = CHIPS.get(status, (str(status), "muted", ""))
    return {"label": text, "tone": tone, "tooltip": tip, "status": status}


#: Rules that guard ADMISSION rather than the setup itself. A slot that produced no candidate
#: never reached them, so reporting one as "the first rule that failed" names a cause that did
#: not act. Stage 5ZP; the distinction is the brief's, and the live evidence matched it exactly.
ADMISSION_LAYER_RULES = frozenset({
    "freshness_allow", "admission_cap_result", "cluster_cap", "family_cap",
    "same_symbol_suppression", "breaker",
})


def operator_lines(row: Mapping) -> list:
    """What the expanded panel says about the STRATEGY, in operator language.

    Two things are deliberately absent:

    **Raw field names and JSON thresholds.** `breadth_down_count` and
    `{"gapdown_min": 3, "gapdown_at": -0.004}` are developer variables. They still exist on the
    row and the reader still ships them under `debug`, but nothing renders them by default.

    **A wall of UNKNOWN rows.** After Stage 5ZD the sleeve detectors do not return their
    measured values, so every setup rule comes back `not_exposed_by_sleeve`. Listing thirty
    mapped names with no numbers beside them is a longer way of saying nothing, and it buries
    the two lines that do carry information. One sentence says the same thing honestly.

    **Runtime refusals are not repeated here.** They belong to the Operational section, and a
    REFUSED row says where to look rather than printing the evidence twice.
    """
    status = row.get("status")
    if status == SLOT_REFUSED:
        return ["Strategy was not evaluated.",
                "See Operational details for the runtime refusal."]
    if status in (SLOT_MISSED, SLOT_NO_ROW):
        return [CHIPS.get(status, ("", "", ""))[2],
                "See Operational details."]

    if status == NO_SIGNAL:
        out = ["No setup matched this slot.", "The slot reached strategy evaluation."]
        pf = primary_failure(row.get("rule_checks") or [])
        failed = pf["primary_failed_rule"]
        # Stage 5ZP. The panel used to say "First rule that failed: Freshness check" on a slot
        # with ZERO candidates, which reads as though freshness stopped a setup. It did not —
        # nothing reached admission for it to stop. Measured on the live 2026-08-26 night
        # window: 22 NO_SIGNAL rows, `candidates: []`, `freshness_allow: false`, and every one
        # of them printed that sentence.
        #
        # A rule that guards ADMISSION has nothing to say about a slot that admitted nothing.
        # It is still reported — it was genuinely measured and an operator may want it — but
        # as a measurement rather than as a cause.
        n_cands = len(row.get("candidates") or [])
        if failed and failed in ADMISSION_LAYER_RULES and n_cands == 0:
            out.append(f"{label(failed)}: measured as not allowing admission, "
                       f"but no candidate reached admission.")
        elif failed:
            out.append(f"First rule that failed: {label(failed)}.")
        elif pf["not_exposed_by_sleeve"]:
            out.append("Detailed setup measurements are not exposed yet.")
        return out

    cand = (row.get("candidates") or [{}])[0]
    who = _candidate_sentence(cand)
    if status == SIGNAL_REJECTED:
        layer = LAYER_LABELS.get(row.get("rejecting_layer"), row.get("rejecting_layer") or "")
        out = ["Setup matched."]
        if layer:
            out.append(f"Rejected by: {layer}.")
        if who:
            out.append(who)
        return out
    if status == SIGNAL_ACCEPTED_SHADOW:
        out = []
        if who:
            out.append(who)
        out.append("Admitted in shadow; no order attempted.")
        return out
    if status == RAW_SIGNAL_FOUND:
        out = ["Setup matched.", "Not yet through admission and cap checks."]
        if who:
            out.append(who)
        return out
    return []


def _candidate_sentence(cand: Mapping) -> str:
    """The candidate as one readable sentence, skipping anything the row did not carry."""
    if not cand or not cand.get("instrument"):
        return ""
    bits = [f"{cand['instrument']} {str(cand.get('direction') or '').upper()}".strip()]
    for key, name, money in (("entry", "entry", False), ("stop", "stop", False),
                             ("target", "target", False), ("risk", "risk", True)):
        v = cand.get(key)
        if v is None:
            continue
        bits.append(f"{name} ${v:,.0f}" if money else f"{name} {v:,.2f}")
    if cand.get("qty") is not None:
        bits.insert(1, f"x{cand['qty']}")
    return " · ".join(bits)


# ── the one-line summary the job view renders ────────────────────────────────────────────

_LABEL = {SLOT_REFUSED: "REFUSED", NO_SIGNAL: "NO SIGNAL",
          RAW_SIGNAL_FOUND: "RAW SIGNAL", SIGNAL_REJECTED: "REJECTED",
          SIGNAL_ACCEPTED_SHADOW: "ACCEPTED SHADOW", SLOT_MISSED: "MISSED",
          SLOT_NO_ROW: "NO DIAGNOSTICS"}


def one_line(row: Mapping) -> str:
    """`Signal: <STATUS> · <primary reason> · <key candidate/count>` — one sentence, no prose.

    Built here rather than in the browser so the phrasing has one owner and the tests can
    assert it. The dashboard renders the string; it does not compose it.
    """
    status = row.get("status") or SLOT_MISSED
    label = _LABEL.get(status, status)
    bits = [f"Signal: {label}"]
    if status in (SLOT_MISSED, SLOT_NO_ROW):
        bits.append(row.get("reason") or ("not scheduled or never spawned"
                                          if status == SLOT_MISSED else "slot ran, no row"))
        return " · ".join(bits)
    if status == SLOT_REFUSED:
        bits.append(row.get("reason") or "refused")
        if row.get("detail"):
            bits.append(str(row["detail"])[:60])
        return " · ".join(bits)
    if status == NO_SIGNAL:
        bits.append(f"candidates {row.get('raw_candidates', 0)}")
        pf = primary_failure(row.get("rule_checks") or [])
        if pf["primary_failed_rule"]:
            bits.append(f"blocker {pf['primary_failed_rule']}")
        elif pf["not_exposed_by_sleeve"]:
            # Say so rather than fall silent. A line that names no blocker reads as "nothing
            # was close", and the truth is that the sleeve did not report its rules at all.
            bits.append(f"blocker not reported ({len(pf['not_exposed_by_sleeve'])} rules)")
        return " · ".join(bits)
    cand = (row.get("candidates") or [{}])[0]
    who = " ".join(str(x) for x in (cand.get("instrument"), cand.get("direction")) if x)
    if status == SIGNAL_REJECTED:
        bits.append(row.get("rejecting_layer") or row.get("reason") or "rejected")
        if who:
            bits.append(who)
        if cand.get("risk") is not None:
            bits.append(f"risk ${cand['risk']:,.0f}")
        return " · ".join(bits)
    if status == SIGNAL_ACCEPTED_SHADOW:
        if who:
            bits.append(who)
        if cand.get("risk") is not None:
            bits.append(f"risk ${cand['risk']:,.0f}")
        bits.append("order not attempted")
        return " · ".join(bits)
    bits.append(f"candidates {row.get('raw_candidates', 0)}")
    return " · ".join(bits)
