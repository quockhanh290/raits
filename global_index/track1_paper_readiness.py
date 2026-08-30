"""global_index/track1_paper_readiness.py — is there enough evidence for paper orders? NEW FILE.

Stage 5S. **Read-only.** Nothing here connects, writes, restarts or arms anything. It answers
one question from the audit records the route has already written:

    has the shadow route produced enough evidence that it works to justify sending orders?

Why this file exists
--------------------
Before it, the order gate had two kinds of condition and neither was evidence:

    B1_broker_account_or_legacy_retirement   a DECISION the operator records on disk
    LIVE_FRAME_ADAPTER_VERIFICATION          a MEASUREMENT of the code's wiring
    + TRACK1_ORDERS_APPROVED=1               an out-of-band approval
    + --allow-orders                         an explicit request

All four are about AUTHORISATION. Not one of them asks whether a single shadow window has ever
closed cleanly. `track1_shadow_acceptance` computes exactly that judgement, every day, and
`track1_gates` never read it — so a route with zero judgeable days and a route with a hundred
were indistinguishable to the thing that decides whether orders may be sent.

That is the gap this closes, and the direction matters: this can only ever REFUSE. It adds a
condition to arming; it removes none, and it cannot arm anything by itself.

What counts as evidence, and what cannot
----------------------------------------
Absence is never a pass. A day with no audit record is not a day that went well; it is a day
nobody watched. Every rule below is written so that a missing file, an unparsable record, a
`NOT_ENOUGH_DATA_YET` verdict or a record for the wrong route counts AGAINST readiness, never
for it. A checker that fails open on a missing file is the shape this project has already paid
for once — see `scheduler_processes()` returning `[]` for "I could not tell".

Staleness is the same problem wearing a date. Five clean days in August do not make December
ready, so the qualifying days must be the most RECENT judgeable ones and the newest of them
must be inside `MAX_EVIDENCE_AGE_DAYS`.

The thresholds are a proposal
-----------------------------
`REQUIRED_JUDGEABLE_DAYS` and the two allowances below are judgement calls, not derived
quantities, and they are gathered here in one block so the operator can move them deliberately
in one place rather than discover them scattered through a checker. Moving them changes what
"ready" means and nothing else.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from global_index import track1_shadow_acceptance as acc
# Stage 5ZX. Module level rather than lazy, unlike pandas above: this one is stdlib only,
# so it costs nothing on the hot path that `ops status` and every slot spawn walk through.
from global_index import track1_account_baseline as _ab
from global_index import track1_shadow_intent as si

SCHEMA = "track1_paper_readiness/1"

# ── the thresholds. Proposals; change them here and nowhere else. ────────────────────────

#: How many judgeable days the route must have produced. A day is judgeable when its DAY-scope
#: audit reached a verdict at all — that is, when every sleeve's window both closed AND was
#: covered by scheduler uptime. Five is one full trading week: enough that a single lucky
#: session cannot carry it, few enough to be reachable.
REQUIRED_JUDGEABLE_DAYS = 5

#: FAIL days permitted among them. Zero: a FAIL is the audit saying a window did not do what it
#: was supposed to, and a route that cannot manage five clean days has not earned an order.
MAX_FAIL_DAYS = 0

#: WARN days permitted. One: WARN is "it worked and something is worth looking at" — p95 over
#: the 240s target but under the 300s ceiling is the ordinary case. Tolerating one keeps the
#: gate from being decided by a single slow afternoon; tolerating more would make the target
#: meaningless.
MAX_WARN_DAYS = 1

#: The newest qualifying day must be no older than this, in calendar days. Evidence describes
#: the route as it was; a month-old clean week says nothing about the code running today.
MAX_EVIDENCE_AGE_DAYS = 21

#: Every sleeve must have reached PASS on its own at least once inside the qualifying window.
#: A day can pass while a sleeve merely observed and found nothing; that is a legitimate day
#: but it is not evidence that the sleeve works.
REQUIRED_SLEEVES: tuple = ("roska4_swing", "roska4_calm", "roska4_stress", "global_nkd")


# ── reading the evidence ─────────────────────────────────────────────────────────────────

def audit_records(root: str | Path = ".") -> list:
    """Every audit record on disk, oldest file first. Unreadable lines are DROPPED, and the
    count of them is reported by `readiness` rather than swallowed."""
    d = Path(root) / acc.AUDITS_DIR
    out: list = []
    if not d.is_dir():
        return out
    for f in sorted(d.glob("track1_audit_*.jsonl")):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                out.append({"__unreadable__": True, "file": f.name})
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _authoritative(records: list) -> dict:
    """`{(scope, sleeve, day): record}` keeping the LAST record for each.

    A sleeve is audited when its own window closes and again in the daily sweep, so the same
    (scope, sleeve, day) appears more than once. The later record is the one written with more
    of the day visible, so it is the one that counts — and taking the FIRST would grade a
    sleeve on a moment when three of its four peers had not run.
    """
    out: dict = {}
    for rec in records:
        if rec.get("__unreadable__"):
            continue
        if rec.get("route") != acc.AUDIT_ROUTE:
            continue
        key = (rec.get("scope"), rec.get("sleeve"), rec.get("session_day"))
        if key[0] is None or key[2] is None:
            continue
        out[key] = rec
    return out


def day_verdicts(root: str | Path = ".") -> dict:
    """`{day: {"verdict": …, "sleeves": {sleeve: verdict}}}`, from the DAY-scope records."""
    auth = _authoritative(audit_records(root))
    days: dict = {}
    for (scope, sleeve, day), rec in auth.items():
        if scope == "day":
            days.setdefault(day, {})["verdict"] = rec.get("verdict")
            days[day]["p95_by_sleeve"] = {}
        elif scope == "sleeve":
            days.setdefault(day, {}).setdefault("sleeves", {})[sleeve] = rec.get("verdict")
            days[day].setdefault("p95_by_sleeve", {})[sleeve] = rec.get("runtime_p95_s")
    for day, rec in days.items():
        rec.setdefault("verdict", None)
        rec.setdefault("sleeves", {})
    return dict(sorted(days.items()))


def _age_days(day: str, today: str) -> int:
    import datetime as dt

    a = dt.date.fromisoformat(day)
    b = dt.date.fromisoformat(today)
    return (b - a).days


# ── the judgement ────────────────────────────────────────────────────────────────────────

def readiness(root: str | Path = ".", *, today: str | None = None) -> dict:
    """`{"ready": bool, "checks": [...], "detail": {...}}` — the whole gate, read-only.

    `today` is taken as an ISO date so a caller can ask the question as of a fixed day; it
    defaults to the ET session date, because every other date in this route is ET.
    """
    if today is None:
        # stdlib, not pandas. This runs inside `track1_gates.blocking()`, which `ops status`,
        # the dashboard poll and every slot spawn call — measured at 75 ms/call when it
        # imported pandas for a single date, against ~1 ms for this.
        import datetime as _dt
        import zoneinfo as _zi

        today = str(_dt.datetime.now(_zi.ZoneInfo("America/New_York")).date())

    records = audit_records(root)
    unreadable = sum(1 for r in records if r.get("__unreadable__"))
    days = day_verdicts(root)

    judgeable = [(d, v) for d, v in days.items()
                 if v["verdict"] not in (None, acc.AUDIT_NOT_ENOUGH_DATA_YET)]
    #: the MOST RECENT ones — evidence is about the route as it is now.
    window = judgeable[-REQUIRED_JUDGEABLE_DAYS:]

    checks: list = []

    def add(name, ok, detail, **extra):
        checks.append({"name": name, "status": "ok" if ok else "fail",
                       "detail": detail, **extra})
        return ok

    add("audit_records_readable", unreadable == 0,
        "every audit line parsed" if unreadable == 0
        else f"{unreadable} audit line(s) could not be parsed; an unreadable record is not a "
             f"passing one", unreadable=unreadable)

    enough = len(window) >= REQUIRED_JUDGEABLE_DAYS
    add("judgeable_days", enough,
        f"{len(judgeable)} judgeable day(s) on record, {REQUIRED_JUDGEABLE_DAYS} required"
        + ("" if enough else " — a day with no audit record is not a day that went well"),
        have=len(judgeable), required=REQUIRED_JUDGEABLE_DAYS,
        days=[d for d, _ in window])

    fails = [d for d, v in window if v["verdict"] == acc.AUDIT_FAIL]
    add("no_failing_days", len(fails) <= MAX_FAIL_DAYS,
        f"{len(fails)} FAIL day(s) in the qualifying window, at most {MAX_FAIL_DAYS} allowed",
        failing=fails)

    warns = [d for d, v in window if v["verdict"] == acc.AUDIT_WARN]
    add("warn_days_within_allowance", len(warns) <= MAX_WARN_DAYS,
        f"{len(warns)} WARN day(s), at most {MAX_WARN_DAYS} allowed", warning=warns)

    if window:
        age = _age_days(window[-1][0], today)
        add("evidence_is_recent", age <= MAX_EVIDENCE_AGE_DAYS,
            f"newest qualifying day {window[-1][0]} is {age} day(s) old, "
            f"at most {MAX_EVIDENCE_AGE_DAYS} allowed", age_days=age)
    else:
        add("evidence_is_recent", False, "no qualifying day at all, so nothing is recent",
            age_days=None)

    # Stage 5ZX. Calm's own evidence, counted from the shadow intent stream and labelled for
    # what it is. The other three sleeves reach PASS through the audit record; Calm's slot
    # could not, because until this stage it fired at the entry instant and needed a bar that
    # would not close for another five minutes.
    #
    # It counts the DECISION and nothing beyond it. A judgeable Calm day says the route decided
    # causally and named the price it would have transacted at — not that an order was
    # accepted, not that it filled, and not at what slippage. The label travels with the number
    # for exactly that reason: a reader who sees only a count will read five clean days as five
    # proven executions, and nobody would ever find out from the count alone.
    calm = calm_decision_evidence(root, [d for d, _ in window])
    calm_ok = [d for d, lab in calm.items() if lab in _CALM_COUNTS]
    calm_bad = {d: lab for d, lab in calm.items() if lab not in _CALM_COUNTS}
    add("calm_decision_evidence", window and not calm_bad,
        (f"{len(calm_ok)} Calm day(s) decision-judgeable or correctly no-setup"
         if window and not calm_bad else
         "no qualifying window, so there is no Calm evidence to judge" if not window else
         f"Calm decision evidence missing or incomplete: {calm_bad}"),
        labels=calm, counted=sorted(calm_ok), not_counted=calm_bad,
        # Spelled out in the record rather than left to the reader. This gate cannot conclude
        # execution from anything it counts here, and the field says so on every run.
        proves="decision_only", does_not_prove="acceptance_fill_or_slippage")

    # Stage 5ZZE. The account the route would start from, proven against the broker rather
    # than assumed from a clean local book.
    #
    # The measurement that put this here: on 2026-08-27 the B1 record was still inside its own
    # 24-hour window — 19.77 hours old — and the equity it carried was 996,875.91 against a
    # stated baseline of 250,000, three hundred per cent away, with no currency recorded
    # anywhere in the row. The paper account had been reset underneath a PASS. B1's freshness
    # window is about POSITIONS AND ORDERS, and a reset changes neither, so the record went on
    # vouching for an account that no longer existed.
    #
    # Only PASS satisfies this. WARN and UNKNOWN both refuse, and an absent baseline refuses
    # loudest of all: a check that never ran is not a check that passed.
    base = _ab.latest(root)
    add("paper_account_baseline", base.status in _ab.SATISFIES_GATE,
        (f"{_ab.operator_line(base)}" if base.status == _ab.PASS
         else f"{base.status} ({base.code}): {base.detail}"),
        status_code=base.status, reason=base.code, checked_at=base.checked_at,
        # Named in the record rather than left to a reader, because a zero here means one thing
        # on a private login and another on a shared one.
        attribution="zero positions is attributable to every route; a non-zero count to none")

    passing_sleeves = {s for _d, v in window
                       for s, sv in v.get("sleeves", {}).items() if sv == acc.AUDIT_PASS}
    missing = [s for s in REQUIRED_SLEEVES if s not in passing_sleeves]
    add("every_sleeve_passed_at_least_once", not missing,
        "all four sleeves reached PASS in the qualifying window" if not missing
        else f"never PASSED inside the window: {missing}",
        passed=sorted(passing_sleeves), missing=missing)

    ready = all(c["status"] == "ok" for c in checks)
    return {
        "schema": SCHEMA,
        "route": acc.AUDIT_ROUTE,
        "today": today,
        "ready": ready,
        "checks": checks,
        "thresholds": {
            "REQUIRED_JUDGEABLE_DAYS": REQUIRED_JUDGEABLE_DAYS,
            "MAX_FAIL_DAYS": MAX_FAIL_DAYS,
            "MAX_WARN_DAYS": MAX_WARN_DAYS,
            "MAX_EVIDENCE_AGE_DAYS": MAX_EVIDENCE_AGE_DAYS,
            "REQUIRED_SLEEVES": list(REQUIRED_SLEEVES),
            "runtime_p95_required_s": acc.RUNTIME_P95_REQUIRED_S,
            "runtime_p95_target_s": acc.RUNTIME_P95_TARGET_S,
        },
        "detail": {"days": days, "judgeable_days": [d for d, _ in judgeable],
                   "qualifying_window": [d for d, _ in window],
                   "unreadable_records": unreadable},
    }


#: The Calm labels a judgeable day may carry. A no-setup day counts: the route was watching
#: and correctly recorded that the rule said nothing today, which is evidence about the route.
#: A day with no rows at all does NOT count, and that is the distinction the whole stream was
#: built to make — an absent record and a quiet day are the same silence to a counter.
_CALM_COUNTS = (si.DECISION_JUDGEABLE, si.NO_SETUP_DAY)


def calm_decision_evidence(root: str | Path = ".", days=()) -> dict:
    """`{day: label}` from the Calm shadow intent stream. Never returns an execution label.

    A day the stream cannot speak for comes back as the pre-schema label rather than as an
    absence, so a caller cannot iterate a shorter dict and conclude every day was fine.
    """
    out = {}
    for d in days:
        try:
            out[d] = str(si.classify_day(si.read_day(root, d))["label"])
        except Exception:                                     # noqa: BLE001
            # Unreadable is not clean. The stream said something this reader could not parse,
            # and a day that cannot be read must never sit in the same bucket as one that read
            # fine — that collapse is what let a fail-open dashboard publish `connected: true`.
            out[d] = "unreadable"
    if si.EXECUTION_PROVEN in out.values():                   # pragma: no cover - structural
        raise AssertionError(
            f"the Calm evidence reader produced {si.EXECUTION_PROVEN!r}. Nothing in shadow can "
            f"prove an execution; a label saying otherwise means the classifier changed under "
            f"a gate that is not allowed to conclude it")
    return out


def gate_measurement(root: str | Path = ".") -> "tuple[bool, str]":
    """`(released, detail)` in the shape `track1_gates.MEASUREMENTS` expects.

    Fails CLOSED on any exception: a readiness check that cannot run is not a readiness check
    that passed, and this is the one place where getting that backwards would open a gate.
    """
    try:
        r = readiness(root)
    except Exception as exc:                                  # pragma: no cover - defensive
        return False, f"the readiness check could not run ({type(exc).__name__}: {exc}); " \
                      f"unknown is not the same as ready"
    if r["ready"]:
        return True, (f"{len(r['detail']['qualifying_window'])} judgeable day(s), "
                      f"all four sleeves passed, newest evidence within "
                      f"{MAX_EVIDENCE_AGE_DAYS} days")
    failed = [c for c in r["checks"] if c["status"] != "ok"]
    return False, "; ".join(f"{c['name']}: {c['detail']}" for c in failed)


def report(root: str | Path = ".", *, today: str | None = None) -> str:
    """A human-facing rendering. The hash-free half of the same answer."""
    r = readiness(root, today=today)
    lines = [f"TRACK 1 PAPER READINESS — route {r['route']}, as of {r['today']}",
             "=" * 72]
    for c in r["checks"]:
        lines.append(f"  [{'PASS' if c['status'] == 'ok' else 'FAIL'}] {c['name']}")
        lines.append(f"         {c['detail']}")
    lines.append("-" * 72)
    lines.append(f"  judgeable days on record : {r['detail']['judgeable_days'] or '(none)'}")
    lines.append(f"  qualifying window        : {r['detail']['qualifying_window'] or '(none)'}")
    lines.extend(account_lines(r))
    lines.extend(calm_lines(r))
    lines.append(f"  READY FOR PAPER (evidence half): {r['ready']}")
    lines.append("")
    # Stage 5ZZZ-O. Placed HERE, above the B1 block, because an operator's risk acceptance is
    # not a footnote to the legacy decision - it is a statement about which sleeves are in
    # scope and on what basis. Presentational only: `swing_override_lines` reads a record that
    # releases no gate, and `gate_measurement` below is untouched by it.
    lines.extend(swing_override_lines(root))
    lines.append("")
    lines.extend(b1_lines(root))
    lines.append("")
    lines.append("  Evidence is only one half. The order gate also requires B1 — which since")
    lines.append("  Stage 5ZQ needs BOTH a recorded decision and a passing measurement, not a")
    lines.append("  signature alone — plus TRACK1_ORDERS_APPROVED=1 and --allow-orders. And")
    lines.append("  none of that builds an order path: run_live_day_track1 constructs")
    lines.append("  NoOrderBroker unconditionally and never constructs IBKRBroker, so no code")
    lines.append("  on this route can send an order however many gates are open.")
    lines.append("  This check can refuse; it can never arm.")
    return "\n".join(lines)


def swing_override_lines(root: str | Path = ".") -> list:
    """The Swing paper-scope override, rendered for an operator.

    Wrapped, because a decision-trail reader must never be the reason a readiness report fails
    to render - and it carries no authority, so a failure here costs information and nothing
    else.
    """
    try:
        from global_index import track1_swing_paper_override as _so

        return _so.lines(root)
    except Exception as exc:                                      # noqa: BLE001
        return [f"  SWING PAPER SCOPE : override record unreadable "
                f"({type(exc).__name__}: {exc})",
                "         Nothing is granted by its absence or its presence."]


def account_lines(r: dict) -> list:
    """The paper account, in the words an operator can act on. Stage 5ZZE.

    Kept apart from the shadow evidence above it and from the slot verdicts below: the account
    being right and the route having watched five clean mornings are different claims, and one
    standing in for the other is how a gate opens on half its reasons.
    """
    c = next((x for x in r["checks"] if x["name"] == "paper_account_baseline"), None)
    if c is None:                                             # pragma: no cover - structural
        return ["  paper account baseline   : NOT MEASURED"]
    out = ["  paper account baseline   :", f"      {c['detail']}"]
    if c.get("status") != "ok":
        out.append("      the gate does not open on anything but a PASS taken within 24h")
    out.append(f"      {c.get('attribution', '')}")
    return out


def calm_lines(r: dict) -> list:
    """Calm's decision evidence, in the words an operator can act on. Stage 5ZX."""
    c = next((x for x in r["checks"] if x["name"] == "calm_decision_evidence"), None)
    if c is None:                                             # pragma: no cover - structural
        return ["  calm decision evidence   : NOT MEASURED"]
    labels = c.get("labels") or {}
    if not labels:
        return ["  calm decision evidence   : missing — no qualifying day to judge"]
    words = {si.DECISION_JUDGEABLE: "present", si.NO_SETUP_DAY: "present (no setup)",
             si.INCOMPLETE: "incomplete", si.PRE_SCHEMA: "missing", "unreadable": "unreadable"}
    out = ["  calm decision evidence   :"]
    for d, lab in sorted(labels.items()):
        out.append(f"      {d}  {words.get(lab, lab)}")
    out.append("      counts the DECISION only — never acceptance, fill or slippage")
    return out


def b1_lines(root: str | Path = ".") -> list:
    """B1's two halves, reported separately because they fail for different reasons and are
    fixed by different people: the decision is the operator's, the measurement is a command.

    Added in Stage 5ZR. Before it, this report's closing paragraph said B1 was released by "a
    confirmation file" — true until Stage 5ZQ, and quietly wrong afterwards. A summary that
    describes a gate it does not consult is how the gate and the description drift apart.
    """
    from global_index import track1_b1 as b1
    from global_index import track1_gates as g

    out = ["  B1 — the two halves, and neither is the other:"]
    try:
        conf, errs = g.load_confirmations()
        decisions = [f for f in ("legacy_retired_confirmed", "separate_account_confirmed")
                     if conf.get(f)]
        if errs:
            out.append("    decision    : REFUSED — the confirmation file does not validate, "
                       "so it grants nothing")
        elif decisions:
            out.append(f"    decision    : recorded ({', '.join(decisions)}) "
                       f"by {conf.confirmed_by or '(unnamed)'} on "
                       f"{conf.confirmed_at or '(undated)'}")
        else:
            out.append("    decision    : pending — no decision is recorded")
    except Exception as exc:                                      # noqa: BLE001
        out.append(f"    decision    : could not be read ({type(exc).__name__})")

    try:
        m = b1.latest(root)
        out.append(f"    measurement : {m.status} ({m.code})")
        out.append(f"                  {b1.operator_line(m)}")
        if m.checked_at:
            out.append(f"                  observed {m.checked_at}, counts for "
                       f"{b1.MAX_RECORD_AGE_HOURS}h")
    except Exception as exc:                                      # noqa: BLE001
        out.append(f"    measurement : UNKNOWN — could not be read ({type(exc).__name__})")

    try:
        blocking = [b.id for b in g.blocking()]
        out.append(f"    B1 blocking now: {'B1_broker_account_or_legacy_retirement' in blocking}")
        others = [b for b in blocking if b != "B1_broker_account_or_legacy_retirement"]
        out.append(f"    also blocking  : {', '.join(others) or 'nothing'}")
        out.append(f"    orders_possible: {g.may_enable_orders()[0]}")
    except Exception as exc:                                      # noqa: BLE001
        out.append(f"    gate state  : could not be read ({type(exc).__name__})")
    return out


if __name__ == "__main__":                                    # pragma: no cover
    import sys

    print(report(sys.argv[1] if len(sys.argv) > 1 else "."))
