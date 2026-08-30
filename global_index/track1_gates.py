"""global_index/track1_gates.py — the Track 1 blocker registry and the go-live gate. NEW FILE.

Stage 3B. Offline and pure except for reading one confirmation file. Nothing here connects
to a broker, starts a service, or decides a trade.

Why a registry in code rather than a document
----------------------------------------------
A blocker that lives only in a report is a blocker that closes itself the day somebody stops
reading the report. Every Track 1 blocker is a row in `BLOCKERS` below, every row carries a
status the code enforces, and `scratch/track1_blocking_ledger_20260822.json` is generated
from this table rather than written beside it. The parity test asserts the two agree, so the
document cannot drift from the gate.

Three statuses, and only three
------------------------------
    CLOSED               the thing that was missing now exists, with a test that goes red
                         when it is removed. It no longer blocks orders.
    USER_DECISION_GATE   the code is done; what is missing is a decision only the project
                         owner can make. It blocks orders, and it can only be released by an
                         explicit confirmation recorded on disk.
    MEASURED_GATE        something is missing from the CODE, and whether it is still missing
                         is decided by a measurement run here and now — never by a signature
                         and never by a sentence. It blocks orders until the measurement
                         passes. No confirmation flag can release one; that is enforced.

Stage 4B added the third. The two-status table had a shape it could not express: a caveat
where nobody has to decide anything and nothing is written down wrong — the code simply is
not connected yet. Filing that as a USER_DECISION_GATE would have let a signature close it,
which is precisely the "prose-only" outcome this registry exists to prevent.

There is deliberately no OPEN. "Open" is where a blocker goes to be forgotten: nobody has to
do anything about it and nothing enforces it. A blocker is either closed with evidence, held
shut awaiting a decision, or held shut by a measurement that currently fails.

The confirmation file
---------------------
`track1_go_live_confirmation.json`, and it is **not created by this build**. It is read, it is
schema-checked, and every failure to read it — absent, unparseable, wrong schema, unknown key,
non-boolean flag — fails CLOSED, meaning no confirmation is granted. A confirmation file that
half-parses must never half-open a gate.
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

CLOSED = "CLOSED"
USER_DECISION_GATE = "USER_DECISION_GATE"
MEASURED_GATE = "MEASURED_GATE"
STATUSES = (CLOSED, USER_DECISION_GATE, MEASURED_GATE)

CONFIRMATION_PATH = "track1_go_live_confirmation.json"
CONFIRMATION_SCHEMA = 1

#: Every flag the confirmation file may carry. An unknown key is a REFUSAL, not something to
#: ignore: `legacy_retired_confirm` (no d) silently ignored would leave the operator believing
#: a gate is open that is shut, which is the worse of the two directions.
#: Stage 4 removed three of these by CLOSING the blockers they existed to release —
#: `normal_generator_isolation_accepted`, `calm_a_detector_accepted_frozen` and
#: `scheduler_wiring_approved`. They are gone rather than left in place unused: a flag that
#: releases nothing is a flag somebody will one day set and believe something happened.
#: `b1_measurement_waived` is not a third way to close B1 — it is a way to close it WITHOUT
#: the account having been asked. It releases nothing on its own: one of the two decisions
#: above must still be recorded. It exists because there are legitimate reasons the broker
#: cannot be queried on the day (Gateway down, a second account not yet reachable), and the
#: alternative to naming that case is an operator quietly deciding the measurement does not
#: apply. Setting it requires a `note` saying why — see `load_confirmations`.
CONFIRMATION_FLAGS: tuple = (
    "legacy_retired_confirmed",
    "separate_account_confirmed",
    "b1_measurement_waived",
)
CONFIRMATION_META: tuple = ("schema_version", "confirmed_by", "confirmed_at", "note")


@dataclass(frozen=True)
class Confirmations:
    flags: Mapping[str, bool]
    confirmed_by: str
    confirmed_at: str
    source: str

    def get(self, name: str) -> bool:
        return bool(self.flags.get(name, False))


NO_CONFIRMATIONS = Confirmations({}, "", "", "(none)")


def load_confirmations(path: str | Path = CONFIRMATION_PATH
                       ) -> tuple[Confirmations, list[str]]:
    """`(confirmations, errors)`. Any error yields NO confirmations at all.

    Not "the valid keys are honoured and the bad ones dropped". A file that cannot be fully
    validated is a file whose author's intent is unknown, and a gate does not open on an
    unknown intent.

    ABSENT is not an error. It is the normal state — this build does not create the file —
    and it grants nothing, so the gated blockers refuse on their own. Reporting absence as an
    error too would make every refusal carry a complaint about a file nobody asked for, and
    would refuse even a route with no gated blocker left. A file that EXISTS and does not
    validate is a different matter and always refuses.
    """
    p = Path(path)
    if not p.exists():
        return Confirmations({}, "", "", f"{p} (absent)"), []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return NO_CONFIRMATIONS, [f"{p} is not readable JSON: {exc}"]
    if not isinstance(raw, dict):
        return NO_CONFIRMATIONS, [f"{p} is not a JSON object"]

    errs: list[str] = []
    if raw.get("schema_version") != CONFIRMATION_SCHEMA:
        errs.append(f"schema_version must be {CONFIRMATION_SCHEMA}, got "
                    f"{raw.get('schema_version')!r}")
    by = raw.get("confirmed_by")
    if not isinstance(by, str) or not by.strip():
        errs.append("confirmed_by must be a non-empty string naming a person")
    at = raw.get("confirmed_at")
    if not isinstance(at, str) or not at.strip():
        errs.append("confirmed_at must be a non-empty ISO date string")
    if raw.get("b1_measurement_waived") is True and not str(raw.get("note") or "").strip():
        errs.append("b1_measurement_waived requires a `note` saying why the account could not "
                    "be asked — a waiver with no reason is indistinguishable from a habit")
    unknown = sorted(set(raw) - set(CONFIRMATION_FLAGS) - set(CONFIRMATION_META))
    if unknown:
        errs.append(f"unknown key(s) {unknown} — refused rather than ignored, because a "
                    f"misspelled flag that is silently dropped reads as a granted gate")
    flags = {}
    for name in CONFIRMATION_FLAGS:
        if name not in raw:
            continue
        v = raw[name]
        if not isinstance(v, bool):
            errs.append(f"{name} must be a JSON boolean, got {type(v).__name__}")
            continue
        flags[name] = v
    if errs:
        return NO_CONFIRMATIONS, errs
    return Confirmations(flags, by.strip(), at.strip(), str(p)), []


# ─────────────────────────────────────────────────────────────────────────────
# Measurements. A MEASURED_GATE is released by one of these returning True, and by nothing
# else. Each must be cheap, offline, and — the part that matters — able to return False.
# ─────────────────────────────────────────────────────────────────────────────

#: The module that IS the guard. Everything else on the route is scanned; this one is excluded
#: because it is the thing being checked for, not a place a fetch could hide.
SPLICE_MODULE = "track1_live_frame"


def route_modules(root: str | Path = "global_index") -> tuple:
    """Every Track 1 module on disk, discovered rather than listed.

    A hand-kept list of "the modules that make up the route" is a list that will one day be
    missing the module somebody just added — and the measurement built on it would report a
    clean route while the new file fetched bars in the corner. This repo has the matching
    scar: a runner list maintained by hand printed "69 passed / 69 total" for a section it
    never called. So the set comes from the filesystem, and the ONE exclusion is the guard
    itself, which is a principle rather than a name to keep updated.
    """
    base = Path(root)
    found = {f.stem for f in base.glob("track1_*.py") if not f.stem.startswith("test_")}
    found.discard(SPLICE_MODULE)
    if (base / "run_live_day_track1.py").exists():
        found.add("run_live_day_track1")
    return tuple(sorted(found))


#: Convenience for tests and reports; the measurement always re-discovers under its own root.
#: The route this registry is about. Named once, because Stage 5ZZK needs to compare a
#: recorded book stamp against it and a second copy of the literal is a second thing to keep
#: in step.
ROUTE = "track1_candidate"

ROUTE_MODULES: tuple = route_modules()

#: Names that mean "bars are being obtained from something live". Matched against parsed
#: identifiers, NOT against the file text: a substring search over source would fire on the
#: word inside a comment or a docstring, and this repo has already been bitten by exactly
#: that — a live-job detector that asked `"python" in detail.lower()` turned every traceback
#: line into a phantom job launch, because interpreter paths contain the word.
LIVE_BAR_NAMES: frozenset = frozenset({
    "ib_insync", "IB", "IBKRBroker", "reqHistoricalData", "reqRealTimeBars", "reqMktData",
    "fetch_bars", "fetch_recent_bars", "reqHistoricalDataAsync",
    # Stage 4C: the provider methods the Track 1 adapter introduced. Without these the rule
    # had a hole exactly the width of the new code — a module could call a provider straight
    # and never be counted as a fetcher, because the measurement only knew the broker's own
    # verb. A name that means "get me bars" belongs here whoever spells it.
    "fetch_session_bars", "fetch_session_bars_direct",
})


#: Stage 5ZZZ-T. Parsed identifier sets, keyed by FILE CONTENT IDENTITY.
#:
#: Measured before the change: 40 modules parsed per `blocking()`, and a single
#: `/api/v1/track1-runtime` request runs that machinery four times — 160 parses for one page
#: poll, which is what put the endpoint at 1.89s.
#:
#: The key is `(resolved path, st_mtime_ns, st_size)` and every part of it earns its place:
#:   path      two modules must not share an entry.
#:   mtime_ns  the ordinary signal that a file changed. Nanoseconds, not seconds, because a
#:             coarse clock lets two edits inside the same second look identical.
#:   size      the backstop for the case mtime cannot see — a same-second, same-timestamp
#:             rewrite. Two different files of the same length AND the same nanosecond
#:             timestamp is the only way past both, and that is not a thing an editor does.
#:
#: What is cached is ONLY the pure extraction: a set of names parsed out of a file. No gate
#: decision, no blocker list and no measurement result is cached — those read state that no
#: file timestamp can speak for.
_IDENT_CACHE: dict = {}
_IDENT_CACHE_MAX = 256


def _identifiers(path: Path) -> frozenset:
    """Every name the module actually references, by parsing it. Comments and docstrings do
    not contribute, which is the whole reason this is an AST walk.

    Memoised on file content identity. `stat()` runs BEFORE the cache is consulted, so a file
    that has gone missing or unreadable raises here exactly as the read used to — an absent
    module must never be answered from a remembered scan, because "I cannot see the file" and
    "I saw the file and it was clean" are the two answers this gate exists to keep apart.

    Returns a `frozenset`: the cached object is handed to every later caller, and a set that
    could be mutated in place would let one caller quietly edit what the next one measures.
    """
    p = Path(path)
    st = p.stat()                     # raises for missing/unreadable — fail-closed, as before
    key = (str(p.resolve()), st.st_mtime_ns, st.st_size)
    hit = _IDENT_CACHE.get(key)
    if hit is not None:
        return hit
    tree = ast.parse(p.read_text(encoding="utf-8"))
    out: set = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.add(a.name.split(".")[0])
                out.add(a.name.rsplit(".", 1)[-1])
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                out.add(n.module.split(".")[0])
                out.add(n.module.rsplit(".", 1)[-1])
            for a in n.names:
                out.add(a.name)
    if len(_IDENT_CACHE) >= _IDENT_CACHE_MAX:
        _IDENT_CACHE.clear()
    frozen = frozenset(out)
    _IDENT_CACHE[key] = frozen
    return frozen


def live_frame_wiring(root: str | Path = "global_index") -> tuple[bool, str]:
    """`(released, detail)` — is every live bar path on the route joined through the guard?

    Three outcomes, and only the third releases:

      no live bar path      The route cannot form a live frame at all: its source is a
                            replay of measured windows. Every reproduction to date therefore
                            ran on history, which is the caveat itself. HOLDS.
      unguarded fetch       A module obtains live bars and does not go through
                            `track1_live_frame`. That is the join that once overwrote 1,050
                            of 1,590 frozen NKD bars without raising. HOLDS.
      guarded fetch         Every module that obtains live bars imports the guard. RELEASES.

    Note what this does NOT claim: that the join was correct on a real trading day. It cannot
    — no live day has been run. It claims that the only way a live bar can reach a sleeve is
    through the checked join, which is the strongest statement available offline.
    """
    base = Path(root)
    mods = route_modules(base)
    if not mods:
        return False, f"no Track 1 route module found under {base} — nothing was measured"
    fetchers, unguarded = [], []
    for mod in mods:
        names = _identifiers(base / f"{mod}.py")
        hits = sorted(names & LIVE_BAR_NAMES)
        if not hits:
            continue
        fetchers.append(f"{mod} ({', '.join(hits)})")
        if SPLICE_MODULE not in names:
            unguarded.append(f"{mod} ({', '.join(hits)})")

    if not fetchers:
        return False, (
            "no module on the Track 1 route obtains live bars — the only source is "
            "sleeves.load_source('replay'), which replays measured windows. So every "
            "reproduction so far, including all of Stage 4, ran on complete historical "
            "frames. The splice guard exists and is proven offline, but nothing on the route "
            "calls it, because there is nothing yet for it to guard.")
    if unguarded:
        return False, ("live bars are obtained without the splice guard in: "
                       + "; ".join(unguarded))
    return True, "every live bar path on the route joins through " + SPLICE_MODULE +                  ": " + "; ".join(fetchers)


def shadow_evidence(root: str | Path = ".") -> tuple[bool, str]:
    """Stage 5S. Has the shadow route produced enough evidence to justify sending orders?

    Imported inside the call rather than at module scope so that this module — which is read
    by `ops status`, the dashboard and the runner on every start — keeps its import graph small
    and cannot be broken by anything the readiness checker reads.

    Fails CLOSED on any exception. See `track1_paper_readiness.gate_measurement`.
    """
    from global_index import track1_paper_readiness as pr

    return pr.gate_measurement(root)


def regime_labels_verified(root: str | Path = ".") -> tuple[bool, str]:
    """Stage 5ZL. Do we KNOW the regime labels have not moved?

    Three answers exist and only one of them opens this gate. PASS opens it; DRIFT and UNKNOWN
    both hold it, for different reasons that the detail sentence keeps apart — a drift is a
    finding about the data, an unknown is the absence of a finding.

    Absence of any record is UNKNOWN, never PASS. A check that never ran is not a check that
    passed, which is the same rule the window ledger applies to slots and the checkpoint reader
    applies to a missing book.

    Imported inside the call for the same reason as its neighbours, and fails CLOSED on any
    exception.
    """
    try:
        from global_index import regime_verify as rv

        v = rv.latest(root)
        return (v.status == rv.PASS), f"{v.status} ({v.code}): {v.detail}"
    except Exception as exc:                                    # noqa: BLE001
        return False, (f"the regime verification record could not be read "
                       f"({type(exc).__name__}: {exc}) — failing closed")


def legacy_broker_flat(root: str | Path = ".") -> tuple[bool, str]:
    """Stage 5ZQ. Has anyone ASKED the account whether it is flat?

    B1 was released by a signature and by nothing else: a person writing
    `legacy_retired_confirmed: true` asserted a fact about an IBKR account, and no code ever
    checked it. This reads the recorded B1 audit, and only a PASS satisfies it.

    Absence is not a pass, and a stale record is not a pass — an account that was flat last
    week is not evidence about the account today. Both are UNKNOWN, which holds the gate.

    Imported inside the call for the same reason as its neighbours, and fails CLOSED on any
    exception. This never opens a connection: it reads what a probe recorded.
    """
    try:
        from global_index import track1_b1 as b1

        r = b1.latest(root)
        return (r.status == b1.PASS), f"{r.status} ({r.code}): {r.detail}"
    except Exception as exc:                                    # noqa: BLE001
        return False, (f"the B1 audit record could not be read "
                       f"({type(exc).__name__}: {exc}) — failing closed")


def b1_decision_evidence(root: str | Path = ".") -> tuple[bool, str]:
    """Stage 5ZZK. Everything the B1 decision ASSERTS, checked against what was recorded.

    `legacy_broker_flat` asked one question — is the account flat — and that was the right
    first question. The decision the operator signs says more than "flat": it says THIS route
    owns THIS login. So this checks the rest of it, and each clause is a separate sentence in
    the detail, because "B1 refused" is not a diagnosis.

        the B1 audit        PASS, inside its own age policy
        the Track 1 book    stamped with this route — read from the file the audit names
        the paper baseline  PASS, inside its own age policy
        the account         the baseline names one

    **Every clause can fail.** The first version of this function compared a route and an
    account id taken from the audit record, and neither field is recorded there — so both
    clauses were `if value and value != expected`, which is a check that never fires reading
    like a check that passed. Caught by printing the detail and noticing two clauses had
    produced no words. A check that cannot go red is worse than no check, because it appears
    in the reasons list as though something had been verified.

    One comparison is deliberately NOT made, and is reported rather than skipped silently:
    the B1 audit does not record the broker's account id, so the audit and the baseline cannot
    be cross-checked against each other yet. That is stated in the detail as an unchecked
    clause, not counted as a passing one.

    Fails CLOSED on every path, and never opens a connection: it reads what the probes wrote.
    """
    parts: list = []
    ok = True

    try:
        from global_index import track1_b1 as b1

        r = b1.latest(root)
        if r.status != b1.PASS:
            ok = False
        parts.append(f"B1 audit {r.status} ({r.code})")
        book_path = ((r.inputs or {}).get("track1_book") or {}).get("path") or ""
    except Exception as exc:                                      # noqa: BLE001
        return False, (f"the B1 audit record could not be read "
                       f"({type(exc).__name__}: {exc}) — failing closed")

    # The route stamp, read from the book file the AUDIT NAMES — the same file the audit
    # read, rather than a path spelled again here. Absent or wrong is a refusal: a book
    # carrying another route's stamp is not this route's book, which is the precise failure
    # B1 exists to prevent.
    try:
        import json as _json

        if not book_path:
            ok = False
            parts.append("the B1 audit names no Track 1 book path")
        else:
            bp = Path(root) / book_path if not Path(book_path).is_absolute() else Path(book_path)
            raw = _json.loads(bp.read_text(encoding="utf-8"))
            route = raw.get("route") or ""
            if route != ROUTE:
                ok = False
                parts.append(f"Track 1 book is stamped {route or '<nothing>'!r}, not {ROUTE!r}")
            else:
                parts.append(f"book route {route}")
    except Exception as exc:                                      # noqa: BLE001
        return False, (f"the Track 1 book's route stamp could not be read "
                       f"({type(exc).__name__}: {exc}) — failing closed")

    try:
        from global_index import track1_account_baseline as ab

        acc = ab.latest(root)
        if acc.status not in ab.SATISFIES_GATE:
            ok = False
        parts.append(f"account baseline {acc.status} ({acc.code})")
        a_id = ((acc.inputs or {}).get("account") or {}).get("account_id") or ""
        if not a_id:
            ok = False
            parts.append("the account baseline names no account")
        else:
            parts.append(f"account {a_id}")
        b_id = ((r.inputs or {}).get("broker") or {}).get("account_id") or ""
        if b_id and b_id != a_id:
            ok = False
            parts.append(f"account mismatch: baseline {a_id}, B1 audit {b_id}")
        elif not b_id:
            parts.append("NOT CHECKED: the B1 audit records no account id, so the two "
                         "records cannot be cross-checked")
    except Exception as exc:                                      # noqa: BLE001
        return False, (f"the paper account baseline could not be read "
                       f"({type(exc).__name__}: {exc}) — failing closed")

    return ok, "; ".join(parts)


MEASUREMENTS: dict = {"live_frame_wiring": live_frame_wiring,
                      "shadow_evidence": shadow_evidence,
                      "regime_labels_verified": regime_labels_verified,
                      "legacy_broker_flat": legacy_broker_flat,
                      "b1_decision_evidence": b1_decision_evidence}


@dataclass(frozen=True)
class Blocker:
    id: str
    title: str
    status: str
    blocks_orders: bool
    evidence: str = ""
    decision_needed: str = ""
    #: Any ONE of these confirmation flags releases the gate. Empty means nothing can.
    released_by: tuple = ()
    #: Name in MEASUREMENTS. When set, the gate opens only if that measurement passes NOW.
    released_by_measurement: str = ""
    #: Name in MEASUREMENTS that must ALSO pass, even once a confirmation flag is present.
    #: This is an AND, where `released_by_measurement` is an OR. It exists for a gate whose
    #: decision asserts a FACT that can be checked: a signature may carry the decision, but it
    #: may not carry the fact. Setting it can only make a gate harder to open.
    also_requires_measurement: str = ""
    #: The one confirmation flag that lets the operator waive `also_requires_measurement` and
    #: take the fact on their own authority. Empty means nothing can waive it.
    waiver_flag: str = ""
    depends_on: tuple = ()

    def measure(self) -> tuple[bool, str]:
        if not self.released_by_measurement:
            return False, ""
        return MEASUREMENTS[self.released_by_measurement]()

    def measure_required(self) -> tuple[bool, str]:
        if not self.also_requires_measurement:
            return True, ""
        return MEASUREMENTS[self.also_requires_measurement]()

    def released(self, conf: Confirmations) -> bool:
        signed = any(conf.get(f) for f in self.released_by)
        if self.also_requires_measurement:
            # Decision AND proof. The signature alone was the whole of this gate until the
            # measurement existed; it is no longer enough, and the only bypass is a waiver
            # the operator has to write down and justify.
            if not signed:
                return False
            if self.waiver_flag and conf.get(self.waiver_flag):
                return True
            return self.measure_required()[0]
        if signed:
            return True
        return self.measure()[0]


BLOCKERS: dict = {

    "B1_broker_account_or_legacy_retirement": Blocker(
        id="B1_broker_account_or_legacy_retirement",
        title="One IB Gateway login is one position book",
        status=USER_DECISION_GATE,
        blocks_orders=True,
        evidence=(
            "IBKRBroker.__init__ takes host/port/client_id/bar_duration and no account. "
            "get_positions() reads ib.positions() unfiltered and get_equity() reads "
            "NetLiquidation unfiltered, so two routes on one login share one net position "
            "per contract. A legacy LONG 1 beside a Track 1 SHORT 1 on the same symbol "
            "reconciles as broker x0 against two file rows and halts entries for BOTH "
            "routes. This is the mechanism that put the legacy STRESS_MID cron behind "
            "`if False:`. Code cannot decide it; only an account or a retirement can."),
        decision_needed=(
            "Either retire legacy first and let Track 1 be the sole route on the existing "
            "account — the stated end state, and the cheaper of the two — or fund and "
            "confirm a dedicated IBKR account for Track 1. Record the choice in "
            f"{CONFIRMATION_PATH} as legacy_retired_confirmed or separate_account_confirmed. "
            "The switch-over runbook is docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md. What else "
            "does or does not hold the gate is deliberately NOT restated here — this "
            "sentence has now gone stale twice by describing another blocker's status, "
            "which is a thing only the registry can answer without drifting. Ask "
            "blocking() for that."),
        released_by=("legacy_retired_confirmed", "separate_account_confirmed"),
        # Stage 5ZQ. The decision stays a decision; the FACT it asserts is now measured.
        # Until this, a signature closed B1 without the account ever being asked, and
        # precondition 7 of the switch-over runbook — "legacy is flat AT THE BROKER" — had
        # never been checked by anything. `python -m global_index.b1_audit` records
        # the answer; this reads it. A waiver exists for the day the broker cannot be
        # reached, and it has to be written down with a reason.
        # Stage 5ZZK. Widened from `legacy_broker_flat`, which asked only whether the
        # account was flat. The decision asserts more than that — it says this route owns
        # this login — so the gate now checks the rest of what it claims. Strictly stronger:
        # every input `legacy_broker_flat` required is still required.
        also_requires_measurement="b1_decision_evidence",
        waiver_flag="b1_measurement_waived"),

    "PAPER_SHADOW_EVIDENCE": Blocker(
        id="PAPER_SHADOW_EVIDENCE",
        title="Enough judgeable shadow days to justify an order",
        status=MEASURED_GATE,
        blocks_orders=True,
        evidence=(
            "Stage 5S. Until 2026-08-25 every condition on this gate was about AUTHORISATION "
            "and none was about EVIDENCE. B1 is a decision recorded on disk, the live-frame "
            "gate measures the code's wiring, TRACK1_ORDERS_APPROVED is an out-of-band "
            "approval and --allow-orders is a request. `track1_shadow_acceptance` computes, "
            "every day, whether the route actually did what it was supposed to — and nothing "
            "that decides whether orders may be sent had ever read it. A route with zero "
            "judgeable days and a route with a hundred were indistinguishable to the gate. "
            "This blocker reads the audit records the route writes to its own durable runtime "
            "directory and asks for a shadow period that went well: judgeable days, no FAIL "
            "among them, every sleeve PASSED at least once, and evidence recent enough to "
            "describe the code running today. Absence never counts as a pass — a missing "
            "audit file is a day nobody watched, not a day that went well — and a check that "
            "cannot run fails closed. "
            "The thresholds live in one named block in track1_paper_readiness.py because they "
            "are judgement calls rather than derived quantities. Moving them changes what "
            "'ready' means and nothing else. "
            "SCOPE: this says the shadow record is good enough to consider an order. It says "
            "nothing about the broker question B1 holds, and it cannot arm anything by "
            "itself — it can only refuse."),
        decision_needed=(
            "Run the shadow route until `python -m global_index.track1_paper_readiness` "
            "reports every check PASS. Nothing to confirm and nothing to sign: this gate "
            "opens when the evidence exists and closes again if it goes stale."),
        released_by_measurement="shadow_evidence",
    ),

    "LIVE_FRAME_ADAPTER_VERIFICATION": Blocker(
        id="LIVE_FRAME_ADAPTER_VERIFICATION",
        title="Live bars reach a sleeve only through the checked join",
        status=MEASURED_GATE,
        blocks_orders=True,
        evidence=(
            "Stage 4B built the join and proved it offline; Stage 4C gave it something to "
            "guard. global_index/track1_live_source.py is the route's only source of live "
            "bars, and every branch of it ends in track1_live_frame.splice — including the "
            "branches where the provider offers nothing, which is where an early return would "
            "otherwise hand back an unchecked frame. The measurement below reads the parsed "
            "code of every Track 1 module and currently answers yes: one module fetches, and "
            "it is guarded. "
            "Two failures the join alone could not catch were found by running bars through "
            "it. The halves are on different clocks by contract — parquet is UTC read as New "
            "York, Tokyo for the Nikkei sleeve, while the broker path returns naive ET — so a "
            "conversion happens, and converting the wrong way shifts a whole session. Landing "
            "BACKWARDS onto history is now caught by comparing prices where the two halves "
            "overlap: the reproduction of the Nikkei error is refused with a largest "
            "disagreement of about a thousand points, the same magnitude the real corruption "
            "had. Landing FORWARDS past history satisfied every rule the join has, and is now "
            "refused because no bar may be stamped after the instant it was fetched at. "
            "SCOPE: this says the path is wired and guarded. It does not say a live day has "
            "been run — none has, and no broker has been connected."),
        decision_needed=(
            "Nothing to decide. This gate is held or released by measurement alone. It is "
            "released today; add a fetch that does not join through "
            "global_index/track1_live_frame.py and it shuts again on its own."),
        released_by_measurement="live_frame_wiring",
        depends_on=("B3_intraday_freshness",)),

    "B3_intraday_freshness": Blocker(
        id="B3_intraday_freshness",
        title="Same-session sleeves decide on bars no gate could see",
        status=CLOSED,
        blocks_orders=False,
        evidence=(
            "global_index/track1_intraday.py validates a bar frame against a declared "
            "requirement per sleeve and fails closed on missing, partial, stale, duplicate, "
            "out-of-order, wrong-timezone and too-early. Calm A requires the prior session's "
            "RTH complete plus today's 09:30-10:00 contiguous and the 10:00 decision bar "
            "present; Stress requires 09:30-10:30 complete, a decision instant inside "
            "10:35-12:30, and a window-ledger observation that is not incomplete. The "
            "validator is source-agnostic, so it is real gate logic rather than a promise "
            "about a source that does not exist yet."),
        depends_on=("SLEEVE_normal_r4", "SLEEVE_calm_a", "SLEEVE_stress_mnq")),

    "SLEEVE_normal_r4": Blocker(
        id="SLEEVE_normal_r4",
        title="Normal-R4 filtered: promoted into the package, no monkeypatching",
        status=CLOSED,
        blocks_orders=False,
        evidence=(
            "global_index/track1_normal_r4.py generates the sleeve from bars without "
            "replacing a single production symbol, and reproduces the committed rows EXACTLY "
            "on all three windows: 980 on floor, 136 on vault2025, 107 on vault2026 — 1,223 "
            "rows, per instrument, row for row. The scratch path got the same answer by "
            "rebinding backtest_swing_tf, _swing_cache, TrendFollowStrategy.generate_signal, "
            "SwingTFEngine and StressMidEngine and mutating trend_follow.DEFAULT_CONFIG; a "
            "test now asserts by OBJECT IDENTITY that a run leaves all five and the config "
            "untouched. The two context filters were PROMOTED rather than re-derived into "
            "global_index/track1_normal_filters.py, and a test requires the promoted copy and "
            "the scratch original to return the same verdict for every 5-minute bar."),
        depends_on=("B3_intraday_freshness",)),

    "SLEEVE_nkd_mnkd": Blocker(
        id="SLEEVE_nkd_mnkd",
        title="NKD/MNKD current sleeve",
        status=CLOSED,
        blocks_orders=False,
        evidence=(
            "The MNKD rows come out of the SAME generator run as Normal-R4 and are anchored "
            "in the same comparison, and the sleeve itself is the already-promoted "
            "futures.swing_tf.SwingTFEngine at ema 10 / chandelier 2.5 / hold 5 with "
            "RegimeLabels(lag_days=1) — production code today, unchanged by Track 1. Its "
            "route identity hash differs from the Stage 2B bootstrap only in RENDERING, "
            "measured field by field: zero strategy differences."),
        depends_on=("SLEEVE_normal_r4",)),

    "SLEEVE_calm_a": Blocker(
        id="SLEEVE_calm_a",
        title="Calm A PCLoc: the detector exists as a function",
        status=CLOSED,
        blocks_orders=False,
        evidence=(
            "global_index/track1_calm_a.py computes the setups from bars and reproduces the "
            "frozen list EXACTLY on all three windows — 421 of 421 rows, and not only the "
            "same days: a test also matches the four recorded feature columns to 1e-9, which "
            "a wrong feature with a compensating threshold could not do. A guard test fails "
            "the run if the detector path so much as opens "
            "scratch/calm_pcloc_not_deep_gap_trade_list.csv. Two conventions had to be read "
            "out of the record rather than guessed: the prior session's RTH window ends at "
            "15:59, not 16:00 (one bar, and it moves close-location across the 1/3 "
            "threshold), and a session counts only if it RAN TO that close — the record's own "
            "prev_session_day column skips Christmas Eve, Black Friday and Presidents' Day, "
            "all of which the exchange calendar calls trading days."),
        depends_on=("B3_intraday_freshness",)),

    "SLEEVE_stress_mnq": Blocker(
        id="SLEEVE_stress_mnq",
        title="Stress-MNQ mnq_only_g3_q7",
        status=CLOSED,
        blocks_orders=False,
        evidence=(
            "Fully computed from bars by a rule: scratch/stress_open_search_20260821 "
            "load_window -> build_day_cache -> build_rule_with_levels(make_rule(Scenario("
            "'mnq_only_g3_q7', ('MNQ',), 7))). No frozen trade table anywhere in the chain, "
            "no monkeypatching of production modules, and quantity 7 travels on the rows "
            "themselves. Confirmed NOT futures/stress_liquidation_1020.py, which is a "
            "different 10:20 candidate that says of itself it is not wired."),
        depends_on=("B3_intraday_freshness",)),

    "CHECKPOINT_bootstrap_under_track1_params": Blocker(
        id="CHECKPOINT_bootstrap_under_track1_params",
        title="A Track 1 checkpoint the route can actually resume from",
        status=CLOSED,
        blocks_orders=False,
        evidence=(
            "global_index/track1_bootstrap.py writes a schema-2 route checkpoint under the "
            "track1_params identity and a book state carrying every field Stage 2C proved "
            "load-bearing, keyed on a cut_instant rather than a cut day. The Stage 2B file "
            "is still refused with params_mismatch and the test that proves it is kept; the "
            "new file is accepted; and resuming from it reproduces the full replay's ordered "
            "settlements exactly.")),

    "WIRING_scheduler_dashboard_paper": Blocker(
        id="WIRING_scheduler_dashboard_paper",
        title="Scheduler slots, dashboard mirror, event route field, paper output",
        status=CLOSED,
        blocks_orders=False,
        evidence=(
            "run_scheduler.make_scheduler takes track1_shadow (CLI --track1-shadow), OFF by "
            "default: off registers the same 60 jobs it always has, with STOP_REPAIR_1220 "
            "still present and the legacy argv byte-identical — all three asserted. On, it "
            "adds the Track 1 slots and extends _ENTRY_WINDOWS with ((10,35),(12,30)) so "
            "the 12:20 sweep stops landing inside the Stress window. The dashboard mirror "
            "gates on RAITS_TRACK1_SHADOW=1 and makes the same subtraction from the same "
            "constant, and the parity check now flips BOTH sides together and is green in "
            "both modes. A Track 1 slot calls run_live_day_track1 with no --allow-orders and "
            "no broker port. "
            "The slot count is deliberately NOT stated here — it said 25 until Stage 5M-B "
            "added the 23 Normal-R4 slots, and a gate whose evidence carries a stale number "
            "is a gate someone will one day disbelieve for the wrong reason. The count lives "
            "in track1_slots.TRACK1_SLOTS and nowhere else. "
            "SCOPE: this closes the WIRING, not the running of it. No scheduler was started "
            "and no Track 1 slot has ever fired."),
        depends_on=("B1_broker_account_or_legacy_retirement",)),

    "REGIME_LABEL_VERIFICATION": Blocker(
        id="REGIME_LABEL_VERIFICATION",
        title="The regime labels are known not to have moved",
        status=MEASURED_GATE,
        blocks_orders=True,
        evidence=(
            "Stage 5ZL. Which sleeve is allowed to trade is decided from HMM regime labels, "
            "and the check that those labels have not moved could not report a failure. It "
            "returned a COUNT, and returned 0 from four places that had verified nothing — no "
            "engine, unreadable inputs, a raising labeller, and no overlapping dates, that "
            "last one printing 'HMM stable' having compared zero labels. Zero is also what a "
            "clean run returns, so 'I could not check' and 'I checked and it was fine' were "
            "the same number. The one call site discarded it anyway, in a process that exited "
            "0, whose non-error output the scheduler throws away. A drift was invisible from "
            "end to end. "
            "This gate reads the recorded status and opens only on PASS. DRIFT and UNKNOWN "
            "both hold it, and they are reported separately: a drift is a finding about the "
            "data, an unknown is the absence of a finding. No record at all is UNKNOWN — a "
            "check that never ran is not a check that passed. "
            "SCOPE: this holds the PAPER gate. It deliberately does not block shadow slots, "
            "and the 13:45 pre-flight deliberately does not run strict, because a "
            "verification that could not run must not skip a trading day."),
        decision_needed=(
            "Run the post-close SPY refresh and let it record a PASS, or resolve the drift it "
            "reports. `python -m global_index.update_spy_csv --csv spy_daily_live.csv "
            "--verify-strict` records the status; the scheduler's 16:20 job does it daily."),
        released_by_measurement="regime_labels_verified"),
}


def current_confirmations(path: "str | Path | None" = None) -> Confirmations:
    """What the operator has actually signed, read from disk. Stage 5ZZK.

    A file that does not validate yields NO confirmations — the same rule `load_confirmations`
    already enforces — so an unreadable or half-parsed file holds every gated blocker shut
    rather than opening one by accident.
    """
    try:
        # Resolved at CALL time, not bound as a default. Bound as a default it would freeze
        # the module-load value, and patching the constant — which is how every test and any
        # relocation of the file works — would change nothing while appearing to. This exact
        # trap cost a stage two days ago in `track1_account_baseline`.
        conf, _errors = load_confirmations(CONFIRMATION_PATH if path is None else path)
        return conf
    except Exception:                                             # noqa: BLE001
        return NO_CONFIRMATIONS


def blocking(conf: "Confirmations | None" = None) -> list:
    """Every blocker still holding the order gate shut, given these confirmations.

    Stage 5ZZK — the default now READS the confirmation file. It used to be
    `NO_CONFIRMATIONS`, and the effect was that this function answered a question nobody was
    asking: *what would still block if the operator had signed nothing?*

    Measured on 2026-08-27, with a valid, hash-verified decision in place and every
    measurement passing: `blocking(conf)` returned `[PAPER_SHADOW_EVIDENCE]` and `blocking()`
    returned that plus B1. Exactly one caller in the repo passed confirmations — the
    live-shadow entry point. `ops status`, the readiness report, the dashboard reader, the
    ledger and the order executor all took the default, so the operator's decision was
    invisible to every one of them and B1 could never be observed closing.

    It failed CLOSED, so nothing unsafe followed from it. But a gate that cannot be seen to
    open is a gate nobody can finish, and "the default stands in for the real answer" is the
    same defect family as an empty list standing in for an error.

    Pass `NO_CONFIRMATIONS` explicitly for the unsigned view — the preview does, to show what
    a decision WOULD release.
    """
    if conf is None:
        conf = current_confirmations()
    return [b for b in BLOCKERS.values() if b.blocks_orders and not b.released(conf)]


def may_enable_orders(conf: "Confirmations | None" = None) -> tuple[bool, list]:
    """Stage 5ZZK: same default change as `blocking`, and for the same reason.

    Note what this does NOT do: reading the confirmation file cannot arm anything on its own.
    Orders additionally require `TRACK1_ORDERS_APPROVED` out of band and `--allow-orders` on
    the command line, and `PAPER_SHADOW_EVIDENCE` is measured, not signed.
    """
    open_ones = blocking(conf)
    return (not open_ones), [f"{b.id}: {b.decision_needed or b.evidence}" for b in open_ones]


def as_ledger() -> dict:
    """The machine-readable ledger. Generated FROM this table, never written beside it."""
    return {
        "route": ROUTE,
        #: what holds the order gate shut RIGHT NOW, reading the confirmations the operator
        #: has actually signed. A reader should not have to cross-reference statuses against
        #: live measurements to answer the only question the ledger is opened for.
        #: Stage 5ZZK: this said "with no confirmations granted", which was an accurate
        #: description of a field that could never reflect a signed decision.
        "blocking_now": [b.id for b in blocking()],
        "confirmations_read_from": CONFIRMATION_PATH,
        "confirmation_path": CONFIRMATION_PATH,
        "confirmation_flags": list(CONFIRMATION_FLAGS),
        "statuses_allowed": list(STATUSES),
        "blockers": [
            {"id": b.id, "title": b.title, "status": b.status,
             "blocks_orders": b.blocks_orders, "evidence": b.evidence,
             "decision_needed": b.decision_needed,
             "released_by": list(b.released_by),
             "released_by_measurement": b.released_by_measurement,
             "measured_now": (lambda r: {"released": r[0], "detail": r[1]})(b.measure())
                             if b.released_by_measurement else None,
             "also_requires_measurement": b.also_requires_measurement,
             "waiver_flag": b.waiver_flag,
             "required_measurement_now":
                 (lambda r: {"satisfied": r[0], "detail": r[1]})(b.measure_required())
                 if b.also_requires_measurement else None,
             "depends_on": list(b.depends_on)}
            for b in BLOCKERS.values()
        ],
    }


def self_check() -> list:
    """Structural rules the table must satisfy. Returned as a list so a test can assert []."""
    errs = []
    for key, b in BLOCKERS.items():
        if key != b.id:
            errs.append(f"{key}: key and id disagree ({b.id})")
        if b.status not in STATUSES:
            errs.append(f"{b.id}: status {b.status!r} is not one of {STATUSES}")
        if b.status == USER_DECISION_GATE:
            if not b.blocks_orders:
                errs.append(f"{b.id}: a USER_DECISION_GATE that does not block is not a gate")
            if not b.decision_needed:
                errs.append(f"{b.id}: a gate must name the decision it is waiting for")
            if not b.released_by:
                errs.append(f"{b.id}: a gate nothing can release is a dead end, not a gate")
        if b.also_requires_measurement:
            if b.also_requires_measurement not in MEASUREMENTS:
                errs.append(f"{b.id}: unknown required measurement "
                            f"{b.also_requires_measurement!r}")
            if not b.released_by:
                errs.append(f"{b.id}: a required measurement on a gate no signature can "
                            f"release is unreachable — nothing would ever consult it")
            if b.waiver_flag and b.waiver_flag not in CONFIRMATION_FLAGS:
                errs.append(f"{b.id}: waiver flag {b.waiver_flag!r} is not a confirmation "
                            f"flag, so it could never be set and the waiver is dead code")
            if b.waiver_flag and b.waiver_flag in b.released_by:
                errs.append(f"{b.id}: {b.waiver_flag!r} both releases the gate and waives its "
                            f"measurement — it would bypass itself")
        if b.waiver_flag and not b.also_requires_measurement:
            errs.append(f"{b.id}: a waiver flag with no measurement to waive waives nothing")
        if b.status == MEASURED_GATE:
            if not b.blocks_orders:
                errs.append(f"{b.id}: a MEASURED_GATE that does not block is not a gate")
            if not b.released_by_measurement:
                errs.append(f"{b.id}: a MEASURED_GATE must name the measurement releasing it")
            elif b.released_by_measurement not in MEASUREMENTS:
                errs.append(f"{b.id}: unknown measurement {b.released_by_measurement!r}")
            if b.released_by:
                errs.append(f"{b.id}: a MEASURED_GATE must not be releasable by a "
                            f"confirmation flag — the point of it is that no signature "
                            f"substitutes for the measurement")
            if not b.evidence:
                errs.append(f"{b.id}: a gate must say what it is holding shut FOR")
        if b.status == USER_DECISION_GATE and b.released_by_measurement:
            errs.append(f"{b.id}: a USER_DECISION_GATE released by measurement is one of the "
                        f"two things, not both")
        if b.status == CLOSED:
            if b.released_by_measurement:
                errs.append(f"{b.id}: CLOSED but still gated on a measurement")
            if b.blocks_orders:
                errs.append(f"{b.id}: CLOSED but still blocking — pick one")
            if not b.evidence:
                errs.append(f"{b.id}: CLOSED without evidence is prose")
        for f in b.released_by:
            if f not in CONFIRMATION_FLAGS:
                errs.append(f"{b.id}: released_by names unknown flag {f!r}")
        for d in b.depends_on:
            if d not in BLOCKERS:
                errs.append(f"{b.id}: depends_on names unknown blocker {d!r}")
    return errs
