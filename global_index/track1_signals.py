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
    "roska4_stress": ("no_regime_label_required", "breadth_down_count", "gapdown_count",
                      "avg_gap", "mnq_only_short_setup", "pre_high_stop_reference",
                      "stop_within_max_pct", "rr_target_computed",
                      "same_symbol_suppression", "family_cap", "cluster_cap"),
    "roska4_swing": ("ema50_filter", "r4_prior_range_filter", "entry_bar_volume_filter",
                     "spy_d1_close_below_sma50_short_filter", "fixed_stop_2x_daily_atr",
                     "stop_arm_rule", "admission_cap_result"),
    "global_nkd": ("ema10_filter", "regime_lag_1", "japan_session_window",
                   "fixed_stop_2x_daily_atr", "max_hold_context", "admission_cap_result"),
}


def rule_names(sleeve: str) -> tuple:
    return RULES.get(sleeve, ())


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
                        "regime_lag_1": {"lag": 1},
                        "japan_session_window": {"clock": "Asia/Tokyo"},
                        "max_hold_context": {"max_hold_days": p.max_hold_days}})
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
                    raw_candidates: int = 0) -> list:
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
              regime_basis: str = "") -> SignalRow:
    """A `SignalRow` from the state a slot already has. Pure: reads nothing, writes nothing."""
    status = classify(decided=decided, reason=reason, raw_candidates=raw_candidates,
                      accepted=accepted, rejected=rejected)
    checks = rule_checks_for(sleeve, decided=decided, freshness_allow=freshness_allow,
                             gate_allow=gate_allow, gate_codes=gate_codes,
                             decisions=decisions, raw_candidates=raw_candidates)

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
