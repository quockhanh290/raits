"""monitor/backend/track1_runtime_reader.py — the dashboard's view of the Track 1 route.

Stage 5P. NEW FILE, additive: no existing endpoint changes shape, and nothing here writes.

The defect this exists to prevent
---------------------------------
Until this file, the dashboard had NO Track 1 reader at all. Its positions endpoint serves
`live_positions.json` — legacy's book — and during a Track 1-only shadow period the natural
misreading is that this is "the system's" state. It is not: it is the DRAINING legacy book,
and Track 1's evidence lives somewhere the dashboard never looked:

    live_positions.track1.json                      the route's book (absent while shadow)
    global_index/replay_checkpoint.track1.json      the route checkpoint
    global_index/track1_runtime/window_coverage     the window ledger (the coverage evidence)
    global_index/track1_runtime/slot_timing         per-slot telemetry
    global_index/track1_runtime/shadow              decisions + explanations

Everything here reads those paths and ONLY those paths. `live_positions.json` is deliberately
never opened by this module — a test parses this file's source to keep that true — and the
payload says which route it describes, so a panel cannot present it as something else.

Absence is data, not an error. A missing Track 1 book during shadow is the EXPECTED state
(the route places no orders), and the payload says "absent" with that reading attached rather
than failing or inventing an empty book.
"""
from __future__ import annotations

import json
import statistics
import datetime as _dt
from pathlib import Path
from typing import Any

ROUTE = "track1_candidate"

BOOK_PATH = "live_positions.track1.json"
CHECKPOINT_PATH = "global_index/replay_checkpoint.track1.json"
COVERAGE_DIR = "global_index/track1_runtime/window_coverage"
TIMING_DIR = "global_index/track1_runtime/slot_timing"
SHADOW_DIR = "global_index/track1_runtime/shadow"
#: Stage 5Q — where the post-window audit writes its verdicts. Read here, never written:
#: this module is the dashboard's eye and an eye that can edit the record is not evidence.
AUDITS_DIR = "global_index/track1_runtime/audits"

#: The sleeves an audit is expected to cover, from the SAME window table the gate and the
#: slot registry read, so "not audited yet" cannot silently shrink when a sleeve is added.
def _audit_sleeves() -> list:
    from global_index.track1_params import WINDOWS_ET
    return sorted(WINDOWS_ET)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {"present": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"present": True, "payload": payload}
    except Exception as exc:                              # noqa: BLE001 — a reader reports
        return {"present": True, "error": f"{type(exc).__name__}: {exc}"}


def _book(root: Path) -> dict:
    out = _read_json(root / BOOK_PATH)
    if not out["present"]:
        out["reading"] = ("absent — the expected state during a shadow period: the route "
                          "places no orders, so it has no book to persist")
    return out


def _checkpoint(root: Path) -> dict:
    """Summarise the route checkpoint in the shape `route_checkpoint.save_route` writes.

    Stage 5ZH. This read `p["route"]`, `p["cut_instant"]` and `p["sleeves"]` — flat keys
    from schema 1 that the schema-2 writer has never produced. Against the first real
    checkpoint the live system wrote, on 2026-08-25, the panel reported `route: null` and
    no sleeves for a file that names its route perfectly well one level down, under
    `routes`. The acceptance gate carried the identical mistake and failed a complete
    window over it; both are fixed together because they are one defect read twice.

    `cut_instant` stays in the summary and stays honest: a checkpoint has no such field.
    The cut day lives on each instrument entry as `last_day`, and a quiet window has no
    entries at all — so the value is None when nothing can be said, and the day it does
    report is the one the entries agree on.
    """
    out = _read_json(root / CHECKPOINT_PATH)
    p = out.get("payload")
    if isinstance(p, dict):
        routes = p.get("routes") if isinstance(p.get("routes"), dict) else {}
        mine = (routes.get(ROUTE) or {}).get("sleeves") or {}
        entries = {s: sorted((v or {}).get("instruments") or {}) for s, v in mine.items()}
        days = sorted({str(e.get("last_day"))
                       for v in mine.values()
                       for e in ((v or {}).get("instruments") or {}).values()
                       if e.get("last_day")})
        out["summary"] = {
            "schema_version": p.get("schema_version"),
            # Present when this route is in the file, None when it is not — the same
            # question the old key asked, answered where the answer actually lives.
            "route": ROUTE if ROUTE in routes else None,
            "routes": sorted(routes),
            "cut_instant": days[0] if len(days) == 1 else None,
            "sleeves": sorted(mine),
            "entries": entries,
            "entry_count": sum(len(v) for v in entries.values()),
        }
        out.pop("payload", None)
    return out


def _coverage(root: Path) -> dict:
    """Per sleeve, the latest day's window status, straight from the ledger's own reader."""
    d = root / COVERAGE_DIR
    if not d.is_dir():
        return {"present": False,
                "reading": "no window-coverage directory; no shadow session has run here"}
    import global_index.window_ledger as wl
    from global_index.track1_params import WINDOWS_ET

    rows: list = []
    for f in sorted(d.glob("window_coverage_*.jsonl")):
        try:
            rows.extend(json.loads(line) for line in
                        f.read_text(encoding="utf-8").splitlines() if line.strip())
        except Exception:                                  # noqa: BLE001
            continue
    days = sorted({str(r.get("date")) for r in rows if r.get("date")})
    out: dict = {"present": True, "days": days, "latest": {}}
    if days:
        latest = days[-1]
        for sleeve in WINDOWS_ET:
            out["latest"][sleeve] = wl.status(rows, sleeve, latest)
    return out


def _timing(root: Path) -> dict:
    """Runtime percentiles per day, from the telemetry the slots themselves wrote."""
    d = root / TIMING_DIR
    if not d.is_dir():
        return {"present": False}
    out: dict = {"present": True, "days": {}}
    for f in sorted(d.glob("slot_timing_*.jsonl")):
        durations: list = []
        outcomes: dict = {}
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:                              # noqa: BLE001
                continue
            outcomes[rec.get("outcome")] = outcomes.get(rec.get("outcome"), 0) + 1
            rt = rec.get("runtime_s")
            if isinstance(rt, (int, float)) and rt > 0:
                durations.append(float(rt))
        day = f.stem.replace("slot_timing_", "")
        entry: dict = {"records": sum(outcomes.values()), "outcomes": outcomes}
        if durations:
            durations.sort()
            entry.update({
                "runtime_p50_s": round(statistics.median(durations), 1),
                "runtime_p95_s": round(durations[max(0, int(0.95 * len(durations)) - 1)], 1),
                "runtime_max_s": round(durations[-1], 1),
            })
        out["days"][day] = entry
    return out


#: What a B1 decision record can say about itself. Stage 5ZZJ. `not_recorded` is the normal
#: state on a route that has not decided yet and is NOT an error; `invalid` is a file that
#: exists and does not validate, which grants nothing and must never read like absence.
B1_NOT_RECORDED = "not_recorded"
B1_ACCEPTED = "accepted"
B1_INVALID = "invalid"


def _b1(root: Path) -> dict:
    """The B1 operator decision and the measurement it rests on. Stage 5ZZJ.

    B1 is the one gate on this route that a PERSON closes. It has two halves — a recorded
    decision and a passing broker measurement — and until now the page showed neither: `ops
    status` printed them and the dashboard did not, so the operator had to leave the page to
    learn whether the route's most consequential gate was open.

    Read-only and offline. It reads what `b1_audit` wrote; it never opens a connection, and it
    never writes the decision file — that file is placed by a person, deliberately, and this
    module is not going to become the exception to that.
    """
    from global_index import track1_b1 as _b1m
    from global_index import track1_gates as _g

    out: dict = {"decision": B1_NOT_RECORDED, "decisions": [], "waiver": False,
                 "confirmation_path": str(_g.CONFIRMATION_PATH), "errors": [],
                 "measurement_status": "UNKNOWN", "measurement_code": "",
                 "measurement_checked_at": None, "measurement_age_hours": None,
                 "measurement_expires_at": None, "blocking_now": [], "closed": False}
    try:
        conf, errors = _g.load_confirmations(_g.CONFIRMATION_PATH)
        exists = Path(_g.CONFIRMATION_PATH).exists()
        decisions = [f for f in ("legacy_retired_confirmed", "separate_account_confirmed")
                     if conf.get(f)]
        out["errors"] = list(errors)
        out["decisions"] = decisions
        out["waiver"] = bool(conf.get("b1_measurement_waived"))
        out["confirmed_by"] = getattr(conf, "confirmed_by", "") or None
        out["confirmed_at"] = getattr(conf, "confirmed_at", "") or None
        # Three states, and the middle one is the point: a file that exists and does not
        # validate grants nothing, exactly like absence — but it means something completely
        # different to whoever has to fix it.
        out["decision"] = (B1_INVALID if (exists and errors) else
                           B1_ACCEPTED if decisions else B1_NOT_RECORDED)
    except Exception as exc:                                       # noqa: BLE001
        out["errors"] = [f"{type(exc).__name__}: {exc}"]

    try:
        r = _b1m.latest(root)
        out["measurement_status"] = r.status
        out["measurement_code"] = r.code
        out["measurement_checked_at"] = r.checked_at
        broker = (r.inputs or {}).get("broker") or {}
        legacy = (r.inputs or {}).get("legacy_book") or {}
        track1 = (r.inputs or {}).get("track1_book") or {}
        out["broker_positions"] = (len(broker["positions"])
                                   if isinstance(broker.get("positions"), list) else None)
        out["broker_working_orders"] = (len(broker["open_orders"])
                                        if isinstance(broker.get("open_orders"), list) else None)
        out["legacy_book_positions"] = legacy.get("count")
        out["track1_book_positions"] = track1.get("count")
        out["account_equity"] = broker.get("equity")
        if r.checked_at:
            try:
                when = _dt.datetime.fromisoformat(str(r.checked_at).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=_dt.timezone.utc)
                out["measurement_age_hours"] = round(
                    (_dt.datetime.now(_dt.timezone.utc) - when).total_seconds() / 3600.0, 2)
                out["measurement_expires_at"] = (
                    when + _dt.timedelta(hours=_b1m.MAX_RECORD_AGE_HOURS)).isoformat()
            except (TypeError, ValueError):
                pass
    except Exception as exc:                                       # noqa: BLE001
        # UNKNOWN, which the initialiser already set. Said out loud rather than left as a
        # default nobody can tell from a real reading.
        out["measurement_error"] = f"{type(exc).__name__}: {exc}"

    try:
        blocking = [b.id for b in _g.blocking()]
        out["blocking_now"] = blocking
        # Asked of the registry, never inferred from the two halves above. The registry is the
        # only thing that can answer without drifting, and a second opinion computed here
        # would be a second thing to keep in step.
        out["closed"] = "B1_broker_account_or_legacy_retirement" not in blocking
    except Exception as exc:                                       # noqa: BLE001
        out["blocking_error"] = f"{type(exc).__name__}: {exc}"

    # One sentence for an operator, built from what was actually read.
    if out["decision"] == B1_INVALID:
        out["line"] = "B1 decision file exists but does not validate — it grants nothing"
    elif out["decision"] == B1_NOT_RECORDED:
        out["line"] = "B1 decision not recorded — the operator has not decided"
    else:
        age = out["measurement_age_hours"]
        out["line"] = (f"B1 decision accepted ({', '.join(out['decisions'])}) · measurement "
                       f"{out['measurement_status']}"
                       + (f" · read {age}h ago" if age is not None else "")
                       + (" · gate CLOSED" if out["closed"] else " · gate still OPEN"))
    return out


#: Baseline statuses whose equity may stand as the page's headline paper figure. Stage 5ZZH.
#: UNKNOWN and FAIL are deliberately absent: both must be SAID, not replaced.
HEADLINE_STATUSES = ("PASS", "WARN")


def _paper_account(root: Path) -> dict:
    """The paper account baseline, as its own block. Stage 5ZZE.

    Separate from the shadow evidence and separate from the slot verdicts, for the reason this
    panel has had to learn twice: two true facts about different things, folded together, send
    a reader to inspect the wrong one. Read-only, and it never connects.
    """
    from global_index import track1_account_baseline as _ab

    try:
        r = _ab.latest(root)
    except Exception as exc:                                          # noqa: BLE001
        return {"status": "UNKNOWN", "code": "reader_failed", "line": "",
                "detail": f"{type(exc).__name__}: {exc}",
                "currency": None, "equity": None, "account_id": None,
                "checked_at": None, "age_hours": None,
                # Stage 5ZZH. UNKNOWN is NOT empty and NOT fine. The reader could not look,
                # which is a different answer from "the account is flat" — and the page must
                # be able to tell them apart without inspecting `code`.
                "headline_usable": False,
                "headline_reason": "the baseline could not be read at all",
                "separate_from_shadow_evidence": True}
    acc = (r.inputs or {}).get("account") or {}
    equity = acc.get("equity")
    # Stage 5ZZH. Age computed HERE, at read time, not carried inside `detail`.
    #
    # `detail` ends with "read N minute(s) ago", and that sentence was written when the record
    # was written. On 2026-08-27 it still said "read 0 minute(s) ago" about a record made at
    # 11:29 UTC while the clock read 15:10 — a description that had walked away from the thing
    # it described. Anything that has to say how old this is asks the field, not the prose.
    age_hours = None
    if r.checked_at:
        try:
            checked = _dt.datetime.fromisoformat(str(r.checked_at))
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=_dt.timezone.utc)
            age_hours = round(
                (_dt.datetime.now(_dt.timezone.utc) - checked).total_seconds() / 3600.0, 2)
        except (TypeError, ValueError):
            age_hours = None
    # Stage 5ZZH. May this figure be the page's HEADLINE paper equity?
    #
    # Answered here rather than in the page, because it is a policy question and a policy
    # question spelled out in a template is a policy nothing can test. UNKNOWN and FAIL are
    # both refused, and refused means "say so plainly" — never "fall back to the other number
    # on the page", which is how a legacy account from a different currency and a different
    # era came to be the large figure at the top for three days.
    usable = (r.status in HEADLINE_STATUSES and isinstance(equity, (int, float))
              and equity == equity)                 # NaN is not a reading
    return {"status": r.status, "code": r.code, "detail": r.detail,
            "line": _ab.operator_line(r),
            "currency": acc.get("currency"), "equity": equity,
            "account_id": acc.get("account_id"), "checked_at": r.checked_at,
            "age_hours": age_hours,
            "expected_equity": _ab.EXPECTED_EQUITY,
            "expected_currency": _ab.EXPECTED_CURRENCY,
            "headline_usable": bool(usable),
            "headline_reason": ("a measured baseline in its own currency"
                                if usable else
                                f"status {r.status} — say so plainly; do not substitute "
                                f"another route's figure"),
            "separate_from_shadow_evidence": True,
            "attribution": ("zero positions is attributable to every route; a non-zero count "
                            "to none")}


def _spy_daily(root: Path, regime_csv: str = "spy_daily_live.csv") -> dict:
    """The daily regime file against the day the next session will ask for. Stage 5ZZC.

    Kept as its OWN block, deliberately apart from the audit verdicts. On 2026-08-27 the
    overnight window passed on every one of its twenty-two slots and its per-slot diagnostics
    still carried `freshness_allow=false`, because the daily file was a day short — two true
    facts about different things. Folding the second into the first would render a window that
    worked as a window that failed, and send somebody to inspect the wrong thing.

    Read-only, and it never fetches.
    """
    from global_index import track1_freshness as _fresh
    from global_index import update_spy_csv as _spy

    out: dict = {"state": "unknown", "last": None, "required": None, "line": "",
                 "separate_from_slot_status": True}
    try:
        need = _fresh.required_daily_close_through(_today_et())
        cov = _spy.coverage_status(Path(root) / regime_csv, need.date())
        out.update(state=cov["state"], last=cov["last"], required=cov["required"])
    except Exception as exc:                                          # noqa: BLE001
        out["line"] = (f"could not be determined ({type(exc).__name__}: {exc}) — "
                       f"unknown is not covered")
        return out

    if out["state"] == _spy.COVERAGE_OK:
        out["line"] = f"SPY daily file covers {out['required']}"
    elif out["state"] == _spy.COVERAGE_SHORT:
        out["line"] = (f"SPY daily file is missing {out['required']} — it ends on "
                       f"{out['last']}. This is a stale daily-context warning, not a slot "
                       f"failure: sleeves that run before the 13:45 pre-flight will refuse "
                       f"until the refresh is re-run")
    else:
        out["line"] = "SPY daily file could not be read — unknown is not covered"
    return out


def _calm_phases(root: Path) -> dict:
    """Calm's two shadow phases, per day. Stage 5ZX. Read-only, and it never concludes.

    Three states like every other block here, because the middle one is the whole reason the
    stream exists: a day with no rows is NOT a quiet day. Until this stage Calm's single slot
    refused every morning, and a panel that showed nothing showed the same nothing for a route
    that was watching and a route that could not.

    `label` is carried through verbatim from the classifier rather than turned into a colour
    here. A second place deciding what "judgeable" means is a second place that can drift, and
    this one would drift toward the friendlier reading.
    """
    from global_index import track1_shadow_intent as si

    d = root / si.SHADOW_INTENT_DIR
    if not d.is_dir():
        return {"present": False,
                "note": "no shadow intent written yet — the two Calm phases have not run"}
    out: dict = {"present": True, "days": {}}
    for f in sorted(d.glob("shadow_intent_*.jsonl")):
        raw = f.stem.replace("shadow_intent_", "")
        day = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else raw
        try:
            rows = si.read_day(root, day)
            v = si.classify_day(rows)
            out["days"][day] = {
                "label": v["label"], "why": v["why"],
                "decide": v.get("decide"), "observe": v.get("observe"),
                "rows": len(rows),
            }
        except Exception as exc:                              # noqa: BLE001
            # Unreadable is its own state. A day this reader could not parse must never be
            # rendered as a day with nothing in it.
            out["days"][day] = {"label": "unreadable",
                                "why": f"{type(exc).__name__}: {exc}", "rows": None}
    out["latest"] = (sorted(out["days"])[-1] if out["days"] else None)
    # Said in the payload rather than left to the page: this block counts decisions.
    out["proves"] = "decision_only"
    out["does_not_prove"] = "acceptance_fill_or_slippage"
    return out


def _explanations(root: Path) -> dict:
    """Rows per day, from wherever the writer put them.

    Stage 5Q-1: this globbed the flat `explanations/explanations_*.jsonl` and the live writer
    nests one level deeper under the window name, so it counted zero on every real shadow day.
    The path knowledge now lives in ONE place — the acceptance module — because two readers
    guessing at a layout independently is how they came to disagree with the writer.
    """
    from global_index import track1_shadow_acceptance as acc

    d = root / SHADOW_DIR / "explanations"
    if not d.is_dir():
        return {"present": False}
    out: dict = {"present": True, "days": {}}
    # Days first, then the acceptance module's own file resolver for each — so this reader
    # and the gate cannot disagree about where a day's rows live. A test asserts they find
    # the same files; the version before 5Q-1 globbed one directory too shallow and reported
    # zero rows on every real shadow day.
    days = sorted({f.stem.replace("explanations_", "")
                   for f in d.rglob("explanations_*.jsonl")})
    for day in days:
        files = acc.explanation_files(root, day)
        out["days"][day] = sum(
            sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
            for f in files)
        # Stage 5Q-2: each live slot owns a file, so the day's evidence is attributable
        # without opening a row. Absence of a sleeve here is a sleeve that explained nothing
        # — which the audit judges; this panel only reports what is on disk.
        attrib = [acc.explanation_attribution(f, root) for f in files]
        out.setdefault("attribution", {})[day] = {
            "files": len(files),
            "sleeves": sorted({a["sleeve"] for a in attrib if a["sleeve"]}),
            "slots": len({a["slot_id"] for a in attrib if a["slot_id"]}),
            "shapes": sorted({a["shape"] for a in attrib}),
        }
    return out


def _gates() -> dict:
    from global_index import track1_gates as g
    led = g.as_ledger()
    ok, why = g.may_enable_orders()
    return {"blocking_now": led.get("blocking_now"), "orders_possible": ok,
            "orders_detail": why if not ok else ""}


def _safety() -> dict:
    from global_index import track1_slots as ts
    return {"jobs": [j.id for j in ts.track1_safety_jobs()],
            "positions_path": ts.TRACK1_POSITIONS_PATH,
            "stop_path": ts.TRACK1_STOP_PATH,
            "maxhold_marker": ts.TRACK1_MAXHOLD_STATE,
            "client_id": ts.TRACK1_SAFETY_CLIENT_ID,
            "note": "registered in track1-only mode; legacy safety keeps draining "
                    "live_positions.json separately"}


def _audits(root: Path) -> dict:
    """The latest audit verdict per sleeve and per day — Stage 5Q.

    Absence is stated, never assumed away. Three distinct answers, and collapsing any two of
    them is how a page comes to imply a route was judged when it never was:

        directory missing      no audit has ever run in this tree
        day has no record      the audit did not run for that day — NOT a pass
        record present         the verdict, with the reasons that produced it

    The audit writes one line per run and later runs append, so the LAST record for a
    (day, sleeve) pair is the current answer; earlier ones are kept because "Calm was judged
    at 10:10" is a fact that must not disappear when Stress is judged at 12:40.
    """
    d = root / AUDITS_DIR
    if not d.is_dir():
        return {"present": False,
                "reading": "no audit directory; the post-window audit has never run here — "
                           "this is 'not judged yet', not 'passed'"}
    days: dict = {}
    for f in sorted(d.glob("track1_audit_*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:                              # noqa: BLE001
                continue
            day = str(rec.get("date") or rec.get("session_day") or "")
            if not day:
                continue
            entry = days.setdefault(day, {"sleeves": {}, "day": None, "route": rec.get("route")})
            if rec.get("scope") == "day":
                entry["day"] = {"verdict": rec.get("verdict"), "ts": rec.get("ts"),
                                "reasons": rec.get("reasons") or [],
                                "acceptance_gate": rec.get("acceptance_gate") or {}}
            else:
                entry["sleeves"][str(rec.get("sleeve"))] = {
                    "verdict": rec.get("verdict"), "ts": rec.get("ts"),
                    "reasons": rec.get("reasons") or [],
                    "expected_slots": rec.get("expected_slots"),
                    "observed_slots": rec.get("observed_slots"),
                    "missing_slot_ids": rec.get("missing_slot_ids") or [],
                    "runtime_p95_s": rec.get("runtime_p95_s"),
                    "runtime_max_s": rec.get("runtime_max_s"),
                    "judgeable": rec.get("judgeable"),
                    "judgeability_reason": rec.get("judgeability_reason"),
                }
    ordered = sorted(days)
    latest = ordered[-1] if ordered else None
    out: dict = {"present": True, "days": ordered, "latest_day": latest,
                 "latest": days.get(latest) if latest else None}
    if not ordered:
        out["reading"] = ("audit directory present, no audit record written yet — the "
                          "windows have not been judged, which is not the same as passing")
    else:
        # Named per sleeve rather than left to the page to infer from a missing key.
        missing = [s for s in _audit_sleeves()
                   if s not in (days[latest]["sleeves"] if latest else {})]
        out["not_audited_yet"] = missing
    return out


def _signals(root: Path) -> dict:
    """Stage 5ZD — the compact signals-today summary. Track 1 paths only.

    Deliberately SMALL. The panel gets latest status, latest slot, today's counts, and the
    most recent accepted and declined rows per sleeve — and nothing else. Full `rule_checks`
    and candidate detail belong to the expanded job row, and duplicating them here would give
    the operator two places to read the same thing and two places for them to disagree.

    An absent file is `present: False` with a reading, never an error: before the first slot
    of the day there IS no file, and a reader that raised on that would make "the day has not
    started" look like a fault.
    """
    from global_index import track1_signals as sig

    try:
        day = _today_et().strftime("%Y%m%d")
    except Exception:
        day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
    try:
        out = sig.summary(day, root=root)
    except Exception as exc:
        # A reader that cannot read says so. It does not report an empty day.
        return {"present": False, "reading": "signals unreadable",
                "error": f"{type(exc).__name__}: {exc}"}
    out["days"] = sig.days(root)
    return out


def _today_et():
    from zoneinfo import ZoneInfo
    return _dt.datetime.now(_dt.timezone.utc).astimezone(ZoneInfo("America/New_York"))


def _regime_verify(root: Path) -> dict:
    """The regime-label verification, in three states rather than two.

    Stage 5ZL. The panel had nothing to show here because the check could not report a
    failure: it returned a count, returned 0 from four paths that had verified nothing, and
    the one call site discarded it. What the dashboard must never do is collapse the three
    into "ok" and "stale" — a DRIFT is a finding about the data and an UNKNOWN is the absence
    of one, and an operator needs to act differently on each.
    """
    try:
        from global_index import regime_verify as rv

        v = rv.latest(root)
        return {"present": v.code != rv.NO_RECORD,
                "status": v.status, "code": v.code, "detail": v.detail,
                "checked_at": v.checked_at, "counts": dict(v.counts or {}),
                "blocks_paper": v.blocks_paper,
                "reading": {
                    rv.PASS: "the labels were compared and none moved",
                    rv.DRIFT: "the labels MOVED — the engine's view of history changed",
                    rv.UNKNOWN: "the labels could NOT be verified; this is not 'no drift'",
                }[v.status]}
    except Exception as exc:                                   # noqa: BLE001
        return {"present": False, "status": "UNKNOWN", "code": "reader_failed",
                "detail": f"{type(exc).__name__}: {exc}", "blocks_paper": True,
                "reading": "the verification record could not be read; failing closed"}


def _reporting(root: Path) -> dict:
    """Track 1's own reporting surface, from Track 1 paths only.

    Stage 5ZM. The panel had nothing here because nothing route-scoped existed to read. What
    it must never do is show a number the broker has not confirmed as though it had: every
    payload from `track1_report` carries `broker_verified: false` and the reasons, and this
    passes them through rather than summarising them into a colour.
    """
    try:
        from global_index import track1_report as tr

        r = tr.report(root)
        return {"present": True, "headline": r["headline"],
                "trade_log": r["trade_log"], "book": r["book"],
                "order_journal": r["order_journal"], "broker": r["broker"],
                "open_position_parity": r["open_position_parity"],
                "reads_legacy_paths": r["reads_legacy_paths"],
                "paper_ready": False,
                "paper_ready_reading": ("reporting readiness is not paper readiness; the "
                                        "order gate is held by its own blockers")}
    except Exception as exc:                                   # noqa: BLE001
        return {"present": False, "detail": f"{type(exc).__name__}: {exc}",
                "broker": {"broker_verified": False, "reasons": ["reader_failed"]},
                "paper_ready": False,
                "reading": "the Track 1 reporting reader failed; failing closed"}


def read_track1_runtime(root: str | Path = ".") -> dict:
    """Everything the dashboard needs to describe the Track 1 route, from Track 1 paths only.

    `root` exists for tests, which point it at a temp tree; production callers take the
    default. Read-only in every branch.
    """
    root = Path(root)
    return {
        "source": "track1_runtime",
        "route": ROUTE,
        "book": _book(root),
        "checkpoint": _checkpoint(root),
        "window_coverage": _coverage(root),
        "slot_timing": _timing(root),
        "explanations": _explanations(root),
        "audits": _audits(root),
        "gates": _gates(),
        "safety": _safety(),
        "signals": _signals(root),
        "paper_account": _paper_account(root),
        # Stage 5ZZJ. The one gate a person closes, shown where the rest of the route is shown.
        "b1": _b1(root),
        "spy_daily": _spy_daily(root),
        "calm_phases": _calm_phases(root),
        "regime_verify": _regime_verify(root),
        "reporting": _reporting(root),
        # Stated in the payload, not only in a docstring: the legacy book is a different
        # route's state and a panel must label it as such.
        "legacy_note": ("live_positions.json is the LEGACY route's draining book and is "
                        "not read by this endpoint; present it only under a legacy/drain "
                        "label"),
    }
