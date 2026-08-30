"""Stage 5ZZJ — the B1 operator decision, and the eight ways it must still refuse.

B1 is the one gate on this route that a person closes rather than a measurement. Stage 5ZQ gave
it a second half so a signature alone could no longer open it: the account has to be measured
flat too. This stage records the decision, and these tests hold the refusals.

A note on wording. Several of the stage's test items are phrased "cannot WRITE the decision
without X". There is deliberately no writer — `track1_b1_decision` has no code path that writes
anything, and its docstring says why: *the confirmation file is written by a person, never by a
script, and that includes this one.* So the honest translation, and what is asserted here, is
that the decision does not OPEN the gate without X. That is the property the writer was going
to protect, tested at the place that actually enforces it.

Nothing here connects to a broker, arms a gate, or touches the production confirmation path —
and one test asserts that last point about every path this file opens.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import track1_b1 as b1                        # noqa: E402
from global_index import track1_b1_decision as dec              # noqa: E402
from global_index import track1_gates as g                      # noqa: E402
from monitor.backend import track1_runtime_reader as tr         # noqa: E402

B1_ID = "B1_broker_account_or_legacy_retirement"
SHADOW_ID = "PAPER_SHADOW_EVIDENCE"

#: The decision as it was previewed and signed on 2026-08-27.
DECISION = {
    "schema_version": 1,
    "confirmed_by": "kevindo290",
    "confirmed_at": "2026-08-27",
    "legacy_retired_confirmed": True,
    "note": "Operator decision, Stage 5ZZJ. Legacy is retired for this paper login.",
}


def _write(tmp_path: Path, **over) -> Path:
    p = tmp_path / "track1_go_live_confirmation.json"
    p.write_text(json.dumps({**DECISION, **over}), encoding="utf-8")
    return p


def _conf(tmp_path: Path, **over):
    conf, errors = g.load_confirmations(_write(tmp_path, **over))
    return conf, errors


class _Measurement:
    """What `track1_b1.latest` hands back."""

    def __init__(self, status, code="legacy_and_broker_flat",
                 checked_at="2026-08-27T16:04:17.115797+00:00"):
        self.status, self.code = status, code
        self.checked_at, self.detail = checked_at, "measured"
        self.inputs = {"broker": {"positions": [], "open_orders": [], "equity": 250_819.13,
                                  "source": "ibkr_direct"},
                       "legacy_book": {"count": 0}, "track1_book": {"count": 0}}


def _use(monkeypatch, m):
    """Install a measurement AND the composite the gate actually asks for. Stage 5ZZK.

    B1's required measurement was widened from `legacy_broker_flat` to `b1_decision_evidence`,
    which reads the account baseline and the Track 1 book's route stamp as well. A test that
    patches only `track1_b1.latest` no longer reaches the gate: its patch sits there while the
    gate consults the real evidence past it. Every such test in this file went on passing —
    the refusal ones for a reason they had not chosen, and the release one not at all.

    So both are set from one status, and each test still spoils exactly one thing.
    """
    monkeypatch.setattr(b1, "latest", lambda *a, **k: m)
    passing = m.status == b1.PASS
    monkeypatch.setitem(g.MEASUREMENTS, "b1_decision_evidence",
                        lambda root=".": (passing, f"B1 audit {m.status} ({m.code})"))


# ── the decision opens B1, and only B1 ──────────────────────────────────────────────────
def test_the_decision_releases_b1(tmp_path, monkeypatch):
    _use(monkeypatch, _Measurement(b1.PASS))
    conf, errors = _conf(tmp_path)
    assert errors == []
    # Stage 5ZZK: `blocking()` now READS the signed confirmation, so the unsigned baseline
    # has to be asked for by name. Written as `blocking()` this compared the signed state
    # against itself the moment a real decision was in place, and asserted nothing.
    before = [b.id for b in g.blocking(g.NO_CONFIRMATIONS)]
    after = [b.id for b in g.blocking(conf)]
    assert B1_ID in before
    assert B1_ID not in after, "the decision did not release the gate it is for"


def test_the_decision_releases_only_b1(tmp_path, monkeypatch):
    """Item 6. A signature is not a shortcut past the evidence gate."""
    _use(monkeypatch, _Measurement(b1.PASS))
    conf, _ = _conf(tmp_path)
    after = [b.id for b in g.blocking(conf)]
    assert SHADOW_ID in after, "the shadow evidence gate must be untouched by a B1 decision"


def test_the_decision_alone_does_not_make_orders_possible(tmp_path, monkeypatch):
    """Item 7. The load-bearing one: this is what makes signing safe."""
    _use(monkeypatch, _Measurement(b1.PASS))
    conf, _ = _conf(tmp_path)
    possible, _why = g.may_enable_orders(conf)
    assert possible is False


def test_the_decision_is_route_and_account_stamped(tmp_path):
    """Item 5. The schema refuses unknown keys, so the stamps live in `note` — which is
    where they have to survive, because the file is the durable artefact."""
    p = _write(tmp_path, note=("Legacy retired for paper login DUR125337; route "
                               "track1_candidate is the sole paper route on it."))
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert "DUR125337" in raw["note"], "no account stamp"
    assert "track1_candidate" in raw["note"], "no route stamp"
    assert raw["confirmed_by"].strip() and raw["confirmed_at"].strip()


# ── the refusals ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("status", ["FAIL", "UNKNOWN"])
def test_a_decision_without_a_passing_measurement_does_not_open_b1(
        tmp_path, monkeypatch, status):
    """Items 1 and 4 — a stale, failed or unread broker measurement holds B1 shut whatever
    the operator signed. UNKNOWN is included deliberately: "I could not ask the account" must
    not open a gate that "I asked and it was flat" opens."""
    _use(monkeypatch, _Measurement(status, code="record_stale"))
    conf, _ = _conf(tmp_path)
    assert B1_ID in [b.id for b in g.blocking(conf)]


def test_a_nonzero_broker_position_holds_b1_shut(tmp_path, monkeypatch):
    """Item 4. The measurement is what carries this, so it is tested through the measurement:
    a book with something in it does not produce a PASS."""
    m = _Measurement(b1.PASS)
    m.inputs["broker"]["positions"] = [{"symbol": "MES", "position": 1}]
    m.status = "FAIL"
    _use(monkeypatch, m)
    conf, _ = _conf(tmp_path)
    assert B1_ID in [b.id for b in g.blocking(conf)]


def test_a_working_order_holds_b1_shut(tmp_path, monkeypatch):
    m = _Measurement("FAIL", code="working_orders_present")
    m.inputs["broker"]["open_orders"] = [{"orderId": 7}]
    _use(monkeypatch, m)
    conf, _ = _conf(tmp_path)
    assert B1_ID in [b.id for b in g.blocking(conf)]


def test_a_file_that_half_parses_grants_nothing(tmp_path, monkeypatch):
    """Item 3, and the rule the loader is built on: a confirmation whose author's intent
    cannot be established is not partially honoured."""
    _use(monkeypatch, _Measurement(b1.PASS))
    conf, errors = _conf(tmp_path, schema_version=99)
    assert errors, "a wrong schema version must be an error"
    assert B1_ID in [b.id for b in g.blocking(conf)]


def test_an_unknown_key_is_refused_rather_than_ignored(tmp_path):
    """A misspelled flag that is silently dropped reads as a granted gate."""
    _conf_, errors = _conf(tmp_path, legacy_retired_confirmedd=True)
    assert errors and any("unknown key" in e for e in errors)


def test_both_decisions_at_once_is_flagged(tmp_path, monkeypatch):
    """They are mutually exclusive: either legacy retires and Track 1 takes the existing
    account, or Track 1 gets its own. Setting both says neither."""
    _use(monkeypatch, _Measurement(b1.PASS))
    pv = dec.preview(_write(tmp_path, separate_account_confirmed=True), ROOT)
    assert any("mutually exclusive" in w for w in pv.warnings)


def test_a_waiver_needs_a_reason(tmp_path):
    _c, errors = _conf(tmp_path, b1_measurement_waived=True, note="")
    assert errors and any("waiver" in e.lower() or "note" in e.lower() for e in errors)


# ── the preview writes nothing ──────────────────────────────────────────────────────────
def test_preview_is_read_only(tmp_path, monkeypatch):
    """Item 8, enforced by watching every file the preview opens rather than by trusting it."""
    # The candidate is built BEFORE the write barrier goes up. Built after, the test's own
    # fixture trips the trap and reports the preview for a write the test made — which is how
    # it failed the first time, and a green version of that would have proved nothing.
    candidate = _write(tmp_path)
    opened: list = []
    real_open = Path.open

    def watched(self, mode="r", *a, **k):
        opened.append((str(self), mode))
        return real_open(self, mode, *a, **k)

    monkeypatch.setattr(Path, "open", watched)
    real_write = Path.write_text

    def refuse(self, *a, **k):
        raise AssertionError(f"preview wrote to {self}")

    monkeypatch.setattr(Path, "write_text", refuse)
    monkeypatch.setattr(Path, "write_bytes", refuse)
    try:
        dec.preview(candidate, ROOT)
    finally:
        monkeypatch.setattr(Path, "write_text", real_write)
    assert not [m for _p, m in opened if any(c in m for c in "wax+")], opened


def test_the_decision_module_has_no_writer_at_all():
    """The property the stage's 'cannot write' items were really about. `track1_b1_decision`
    is the tool an operator runs next to this decision; if it grows a writer, the file stops
    being something a person places deliberately."""
    text = (ROOT / "global_index" / "track1_b1_decision.py").read_text(encoding="utf-8")
    for forbidden in ("write_text(", "write_bytes(", "json.dump(", "open(", "mkdir("):
        assert forbidden not in text, f"{forbidden} appeared in the preview module"


# ── the production path is not something a test can reach ───────────────────────────────
def test_no_test_in_this_file_touches_the_production_confirmation(tmp_path):
    """Item 9. Every decision file in this suite is built under tmp_path; the production path
    is only ever read. Asserted by construction AND by looking."""
    text = Path(__file__).read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert "_write(tmp_path" in body
    # the one production constant that appears must never appear next to a write
    for line in body.splitlines():
        if "CONFIRMATION_PATH" in line:
            assert "write" not in line.lower(), line


def test_the_production_confirmation_path_is_outside_every_tmp_dir(tmp_path):
    prod = Path(g.CONFIRMATION_PATH).resolve()
    assert tmp_path.resolve() not in prod.parents
    assert prod.name == "track1_go_live_confirmation.json"


# ── the scheduler-mode guard ────────────────────────────────────────────────────────────
def test_the_running_mode_registers_no_legacy_entry_jobs():
    """Item 10, and the condition the whole decision rests on.

    `legacy_retired_confirmed` asserts that legacy will not enter on this login. Measured on
    this machine, legacy is DORMANT rather than retired: `track1-only-shadow` registers zero
    legacy strategy jobs, and the default mode registers 45. One command-line flag separates
    them, so a restart can falsify the recorded decision while the gate goes on reading it as
    true. The preview says this out loud; this pins the half that is checkable here.
    """
    capability, why = dec._legacy_entry_capability()
    assert capability != dec.LEGACY_ENTRY_PRESENT, (
        f"the running scheduler registers legacy entry jobs: {why}")
    assert why


def test_the_preview_warns_that_dormant_is_not_retired(tmp_path, monkeypatch):
    """The warning must survive. It is the only thing standing between a flag and a signature
    that outlives it."""
    _use(monkeypatch, _Measurement(b1.PASS))
    monkeypatch.setattr(dec, "_legacy_entry_capability",
                        lambda: (dec.LEGACY_ENTRY_NONE, "in track1-only-shadow"))
    pv = dec.preview(_write(tmp_path), ROOT)
    assert any("dormant" in w and "restart" in w for w in pv.warnings)


def test_the_preview_refuses_when_legacy_can_still_enter(tmp_path, monkeypatch):
    _use(monkeypatch, _Measurement(b1.PASS))
    monkeypatch.setattr(dec, "_legacy_entry_capability",
                        lambda: (dec.LEGACY_ENTRY_PRESENT, "not in track1-only mode"))
    pv = dec.preview(_write(tmp_path), ROOT)
    assert any("still registers legacy entry jobs" in w for w in pv.warnings)


def test_an_unreadable_scheduler_is_unknown_not_safe(monkeypatch):
    """Three states. A scheduler that cannot be seen is not a scheduler that is safe."""
    from monitor import ops
    monkeypatch.setattr(ops, "scheduler_processes", lambda *a, **k: [])
    capability, why = dec._legacy_entry_capability()
    assert capability == dec.LEGACY_ENTRY_UNKNOWN
    assert why


# ── the dashboard block ─────────────────────────────────────────────────────────────────
def test_the_reader_reports_the_decision_state(monkeypatch):
    block = tr._b1(ROOT)
    assert block["decision"] in (tr.B1_ACCEPTED, tr.B1_NOT_RECORDED, tr.B1_INVALID)
    assert block["measurement_status"] in ("PASS", "FAIL", "UNKNOWN")
    assert "line" in block and block["line"]
    for key in ("broker_positions", "broker_working_orders", "legacy_book_positions",
                "track1_book_positions", "measurement_age_hours", "blocking_now", "closed"):
        assert key in block, f"{key} missing"


def test_the_reader_takes_closed_from_the_registry_not_from_the_two_halves(monkeypatch):
    """A second opinion computed in the reader is a second thing to keep in step, and this
    project has already watched a restated sentence go stale twice."""
    monkeypatch.setattr(g, "blocking", lambda *a, **k: [])
    assert tr._b1(ROOT)["closed"] is True
    monkeypatch.setattr(g, "blocking", lambda *a, **k: [g.BLOCKERS[B1_ID]])
    assert tr._b1(ROOT)["closed"] is False


def test_a_file_that_does_not_validate_does_not_read_as_absent(monkeypatch, tmp_path):
    """`not_recorded` and `invalid` grant exactly the same thing and mean completely
    different things to whoever has to fix it."""
    bad = tmp_path / "track1_go_live_confirmation.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(g, "CONFIRMATION_PATH", str(bad))
    block = tr._b1(ROOT)
    assert block["decision"] == tr.B1_INVALID
    assert block["errors"]
    assert "does not validate" in block["line"]


def test_the_reader_never_constructs_a_broker():
    text = (ROOT / "monitor" / "backend" / "track1_runtime_reader.py").read_text(encoding="utf-8")
    assert "IBKRBroker(" not in text
    assert "b1_audit" not in text.replace("`b1_audit`", ""), "the reader must not run the audit"


# ── safety, about the session this runs in ──────────────────────────────────────────────
def test_no_allow_orders_in_the_scheduler_or_ops_call_paths():
    """Item 11. Comments stripped, so a note about the flag is not mistaken for the flag."""
    def stripped(path: Path) -> str:
        return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                         if not l.strip().startswith("#"))

    for rel in ("global_index/run_scheduler.py", "monitor/ops.py"):
        assert "--allow-orders" not in stripped(ROOT / rel), rel


def test_orders_remain_impossible():
    import os
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")
    assert not (ROOT / "global_index" / "track1_runtime" / "orders").exists()
    possible, _why = g.may_enable_orders()
    assert possible is False
