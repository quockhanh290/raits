"""The operator's decision to carry Swing into paper scope — read, validated, and inert.

Stage 5ZZZ-N established the canonical baselines and the operator accepted the risk of keeping
`roska4_swing` in paper on the causal D-1 identity. Until this module that decision lived only in
a report, which is the one place a route cannot read.

What this record IS
-------------------
A statement of SCOPE and of who accepted the risk. It says the sleeve is in paper by an
operator's override rather than because the evidence asked for it, and it carries the reasons
against it alongside the decision so neither can be quoted without the other.

What this record IS NOT
-----------------------
It is not a gate release, and it cannot become one. `track1_gates` does not import this module —
measured before it was written: the gate source mentioned no swing override at all, and
`blocking()` returned `['PAPER_SHADOW_EVIDENCE']` with `may_enable_orders()` False. A test
asserts the import graph, and another asserts those two answers are identical whether the record
is absent, valid or corrupt.

It is also not a parameter promotion. `parameter_promotion` and `evidence_promotion` are recorded
as false and VALIDATED as false — a record claiming either is refused, because that is the claim
this whole sequence of stages declined to make.

Fail-closed
-----------
Malformed, unreadable, unsigned, route- or sleeve-mismatched, wrong identity, expired, or
claiming a promotion → the record grants nothing and `reason` says which. "Grants nothing" is
also what a valid record does; the difference is only what an operator is told.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA = "track1_swing_paper_override/1"

#: The one decision this record may carry. Anything else is refused rather than interpreted.
DECISION = "INCLUDE_SWING_IN_PAPER_BY_OPERATOR_OVERRIDE"
DECISION_TYPE = "swing_paper_scope"
ROUTE = "track1_candidate"
SLEEVE = "roska4_swing"
REGIME_BASIS = "causal_d1"
SELECTED_IDENTITY = "D1_OLD_EFFECTIVE_EMA50"

RECORD_PATH = "track1_swing_paper_override.json"

#: The caveats are part of the record, not commentary on it. A record that has dropped them is
#: refused: an override whose reasons-against have gone missing reads as an endorsement.
REQUIRED_CAVEATS = (
    "same-day Swing not live-tradable",
    "Swing 2026 contribution negative",
    "no-Swing risk-adjusted OOS better",
    "no bootstrap yet",
)

REQUIRED_FIELDS = (
    "schema", "decision_type", "decision", "confirmed_by", "confirmed_at", "route", "sleeve",
    "regime_basis", "selected_identity", "parameter_promotion", "evidence_promotion",
    "risk_acceptance", "caveats", "source_stage", "baseline_reference",
)

#: Optional. Enforced when present; absent means the record does not expire. An override is a
#: standing decision, not a timed permission — but an operator who wants it to lapse can say so.
EXPIRY_FIELD = "expires_at"


@dataclass(frozen=True)
class Override:
    """A validated record. `valid` False means it grants nothing and `reason` says why."""

    valid: bool
    reason: str = ""
    decision: str = ""
    confirmed_by: str = ""
    confirmed_at: str = ""
    route: str = ""
    sleeve: str = ""
    regime_basis: str = ""
    selected_identity: str = ""
    risk_acceptance: bool = False
    caveats: tuple = ()
    source_stage: str = ""
    baseline_reference: str = ""
    expires_at: str = ""

    #: Stated on the object so no caller has to remember it. All four are ALWAYS false: this
    #: record is scope, never permission.
    grants_orders: bool = False
    satisfies_shadow_evidence: bool = False
    is_parameter_promotion: bool = False
    is_evidence_promotion: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _refused(reason: str) -> Override:
    return Override(valid=False, reason=reason)


def load(path: str | Path = RECORD_PATH, *, now: str | None = None) -> Override:
    """Read and validate the record. Never raises, never writes, never grants."""
    p = Path(path)
    if not p.exists():
        return _refused(f"no override record at {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                                       # noqa: BLE001
        return _refused(f"unreadable: {type(exc).__name__}: {exc}")
    if not isinstance(raw, dict):
        return _refused("the record is not an object")

    missing = [f for f in REQUIRED_FIELDS if f not in raw]
    if missing:
        return _refused(f"missing required fields: {', '.join(missing)}")

    for field_name, want in (("schema", SCHEMA), ("decision_type", DECISION_TYPE),
                             ("decision", DECISION), ("route", ROUTE), ("sleeve", SLEEVE),
                             ("regime_basis", REGIME_BASIS),
                             ("selected_identity", SELECTED_IDENTITY)):
        if raw.get(field_name) != want:
            return _refused(f"{field_name} {raw.get(field_name)!r} is not {want!r}")

    signed = str(raw.get("confirmed_by") or "").strip()
    if not signed:
        return _refused("unsigned: confirmed_by is empty")
    if not str(raw.get("confirmed_at") or "").strip():
        return _refused("confirmed_at is empty")

    # The two claims this record is forbidden to make.
    if raw.get("parameter_promotion") is not False:
        return _refused("parameter_promotion must be false; this record cannot promote a parameter")
    if raw.get("evidence_promotion") is not False:
        return _refused("evidence_promotion must be false; this record is an override, not evidence")
    if raw.get("risk_acceptance") is not True:
        return _refused("risk_acceptance must be true; an override without it says nothing")

    caveats = raw.get("caveats")
    if not isinstance(caveats, list):
        return _refused("caveats must be a list")
    lowered = [str(c).strip().lower() for c in caveats]
    absent = [c for c in REQUIRED_CAVEATS if c.lower() not in lowered]
    if absent:
        return _refused(f"caveats dropped: {'; '.join(absent)}")

    expires = str(raw.get(EXPIRY_FIELD) or "").strip()
    if expires:
        today = now or _dt.date.today().isoformat()
        if expires < today:
            return _refused(f"expired on {expires} (today {today})")

    return Override(
        valid=True, reason="",
        decision=raw["decision"], confirmed_by=signed,
        confirmed_at=str(raw["confirmed_at"]), route=raw["route"], sleeve=raw["sleeve"],
        regime_basis=raw["regime_basis"], selected_identity=raw["selected_identity"],
        risk_acceptance=True, caveats=tuple(str(c) for c in caveats),
        source_stage=str(raw["source_stage"]),
        baseline_reference=str(raw["baseline_reference"]),
        expires_at=expires,
    )


#: How a sleeve came to be in paper scope. Swing is the only one carrying an override; the rest
#: are in scope on the route's own design.
_BY_DESIGN = "in_scope_by_route_design"


def paper_scope(root: str | Path = ".", *, now: str | None = None) -> dict:
    """Which sleeves are in paper scope, and on what basis. Evidence is a separate question."""
    ov = load(Path(root) / RECORD_PATH, now=now)
    swing = {
        "in_scope": True,
        "basis": "operator_override" if ov.valid else _BY_DESIGN,
        "risk_accepted": bool(ov.valid),
        "evidence_promoted": False,
        "parameter_promoted": False,
        "identity": SELECTED_IDENTITY if ov.valid else "unrecorded",
        "regime_basis": REGIME_BASIS if ov.valid else "unrecorded",
        "override_valid": ov.valid,
        "override_reason": ov.reason,
        "caveats": list(ov.caveats),
        # Said on every sleeve, because scope is not readiness.
        "evidence": "pending",
    }
    return {
        "schema": SCHEMA, "route": ROUTE,
        "sleeves": {
            "global_nkd": {"in_scope": True, "basis": _BY_DESIGN, "evidence": "pending"},
            "roska4_stress": {"in_scope": True, "basis": _BY_DESIGN, "evidence": "pending"},
            "roska4_calm": {"in_scope": True, "basis": _BY_DESIGN, "evidence": "pending"},
            "roska4_swing": swing,
        },
        # Repeated here so a caller reading only this dict cannot mistake scope for permission.
        "grants_orders": False,
        "satisfies_shadow_evidence": False,
        "note": ("Paper SCOPE only. No entry here releases a gate, satisfies "
                 "PAPER_SHADOW_EVIDENCE, or promotes a parameter."),
    }


def lines(root: str | Path = ".", *, now: str | None = None) -> list:
    """The operator-facing rendering, for the readiness report. Never buried, never trimmed."""
    ov = load(Path(root) / RECORD_PATH, now=now)
    if not ov.valid:
        return ["  SWING PAPER SCOPE : no valid operator override on record",
                f"         {ov.reason}",
                "         Swing stays in scope by route design; nothing is granted either way."]
    out = [
        "  SWING PAPER SCOPE : included by operator risk acceptance",
        f"         identity   {ov.selected_identity}  ·  regime basis {ov.regime_basis}",
        f"         accepted   {ov.confirmed_by} at {ov.confirmed_at}  (stage {ov.source_stage})",
        "         This is NOT a parameter promotion and NOT an evidence promotion.",
        "         It releases no gate and does not satisfy PAPER_SHADOW_EVIDENCE.",
        "         Accepted against:",
    ]
    out += [f"           - {c}" for c in ov.caveats]
    if ov.expires_at:
        out.append(f"         expires    {ov.expires_at}")
    out.append(f"         baseline   {ov.baseline_reference}")
    return out
