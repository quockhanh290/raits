"""Stage 5ZZE — is the paper account safe to start from?

The measurement that put this here, taken against the live record on 2026-08-27:

    B1 record age     19.77 h   (inside its own 24 h window — still PASS)
    recorded equity   996,875.91   with no currency recorded anywhere in the row
    stated baseline   250,000
    drift             299%

The paper account had been reset underneath a PASS. B1's freshness window is about POSITIONS AND
ORDERS, and a reset changes neither — so the record went on vouching for an account that no
longer existed, and nothing in it could have said so.

Nothing here connects. Every broker reply is a stub.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "monitor"))

from global_index import track1_account_baseline as ab  # noqa: E402
from global_index import track1_b1 as b1  # noqa: E402


def _rows(**by_currency):
    """`accountValues()` rows, in the shape ib_insync yields them."""
    return [{"tag": "NetLiquidation", "currency": c, "value": v, "account": "DU1234567"}
            for c, v in by_currency.items()]


def _b1_pass():
    """A B1 result that says everything is flat, built from the real measure()."""
    book = b1.BookState(path="x", state=b1.BOOK_READ, count=0, positions=[], error="")
    ev = b1.from_direct_probe({"source": "ibkr_direct", "connected": True,
                               "observed_at": ab._now(), "positions": [], "open_orders": []})
    return b1.measure(book, book, ev)


def _b1_fail():
    held = b1.BookState(path="x", state=b1.BOOK_READ, count=1,
                        positions=[{"inst": "MES"}], error="")
    flat = b1.BookState(path="y", state=b1.BOOK_READ, count=0, positions=[], error="")
    ev = b1.from_direct_probe({"source": "ibkr_direct", "connected": True,
                               "observed_at": ab._now(), "positions": [], "open_orders": []})
    return b1.measure(held, flat, ev)


# ═══════════════════════════════════════════════════════════════════════════════
# 1-4  the happy account, and the number that keeps its unit
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_usd_250k_flat_and_fresh_is_a_pass():
    acc = ab.from_account_values(_rows(USD=250_000.0), account_id="DU1234567")
    r = ab.measure(acc, _b1_pass())
    assert r.status == ab.PASS, r.detail
    assert r.code == ab.OK
    assert "USD" in r.detail and "250,000" in r.detail
    assert ab.operator_line(r) == "Paper account baseline: USD 250,000 — broker reconcile flat"


def test_2_the_currency_stays_attached_to_the_number():
    """The defect this module exists for. `get_equity()` returns a bare float and its own
    docstring says it accepts any currency."""
    acc = ab.from_account_values(_rows(USD=250_000.0, CAD=340_000.0))
    assert acc.currency == "USD", "the expected currency was not preferred"
    assert acc.equity == 250_000.0
    # and every currency the account reported is kept, so a reader can see there were two
    assert acc.equity_by_currency == {"USD": 250_000.0, "CAD": 340_000.0}
    assert ab.measure(acc, _b1_pass()).status == ab.PASS


def test_3_an_account_reporting_only_CAD_fails(monkeypatch):
    acc = ab.from_account_values(_rows(CAD=250_000.0))
    assert acc.currency == "CAD"
    r = ab.measure(acc, _b1_pass())
    assert r.status == ab.FAIL
    assert r.code == ab.CURRENCY_WRONG
    assert "CAD" in r.detail and "USD" in r.detail


def test_4_the_account_b1_actually_recorded_would_fail_today():
    """996,875.91 against a stated 250,000. The row that prompted this whole stage."""
    acc = ab.from_account_values(_rows(USD=996_875.91))
    r = ab.measure(acc, _b1_pass())
    assert r.status == ab.FAIL
    assert r.code == ab.EQUITY_IMPLAUSIBLE
    assert r.findings["drift_fraction"] > ab.EQUITY_FAIL_FRACTION


# ═══════════════════════════════════════════════════════════════════════════════
# 5-7  the band, decided and documented
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("equity,expect", [
    (250_000.0, ab.PASS),
    (245_000.0, ab.PASS),       # 2% — fees and marks
    (238_000.0, ab.PASS),       # 4.8%, just inside
    (230_000.0, ab.WARN),       # 8% — plausible, not expected
    (200_000.0, ab.WARN),       # 20%
    (180_000.0, ab.FAIL),       # 28% — a different account or a different currency
    (0.0, ab.FAIL),
])
def test_5_the_equity_band_is_three_bands_not_two(equity, expect):
    r = ab.measure(ab.from_account_values(_rows(USD=equity)), _b1_pass())
    assert r.status == expect, f"{equity}: {r.one_line()}"


def test_6_a_WARN_does_not_open_the_gate():
    """The difference between WARN and FAIL is what an operator does next, not what the gate
    does. A gate with a maybe in it is a gate somebody argues with."""
    r = ab.measure(ab.from_account_values(_rows(USD=230_000.0)), _b1_pass())
    assert r.status == ab.WARN
    assert r.status not in ab.SATISFIES_GATE
    assert ab.SATISFIES_GATE == (ab.PASS,)


def test_7_the_expected_figure_is_declared_once():
    assert ab.EXPECTED_CURRENCY == "USD"
    assert ab.EXPECTED_EQUITY == 250_000.0
    assert 0 < ab.EQUITY_PASS_FRACTION < ab.EQUITY_FAIL_FRACTION < 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8-11  fail closed on everything that did not answer
# ═══════════════════════════════════════════════════════════════════════════════

def test_8_a_broker_that_could_not_be_reached_is_UNKNOWN_not_empty():
    r = ab.measure(ab.account_unavailable("connection refused"), _b1_pass())
    assert r.status == ab.UNKNOWN
    assert r.code == ab.BROKER_NOT_QUERIED
    assert r.status not in ab.SATISFIES_GATE


def test_9_an_account_that_reported_no_currency_is_UNKNOWN():
    acc = ab.from_account_values([{"tag": "NetLiquidation", "currency": "", "value": 250_000}])
    assert not acc.currency_known
    r = ab.measure(acc, _b1_pass())
    assert r.status == ab.UNKNOWN
    assert r.code in (ab.BROKER_NOT_QUERIED, ab.CURRENCY_UNKNOWN)


def test_10_a_stale_reading_is_UNKNOWN():
    import datetime as dt

    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).isoformat()
    acc = ab.from_account_values(_rows(USD=250_000.0), observed_at=old)
    r = ab.measure(acc, _b1_pass())
    assert r.status == ab.UNKNOWN
    assert r.code == ab.OBSERVATION_STALE
    assert r.findings["observation_age_minutes"] > ab.MAX_OBSERVATION_MINUTES


def test_11_b1_failing_or_absent_stops_the_baseline():
    good = ab.from_account_values(_rows(USD=250_000.0))
    fail = ab.measure(good, _b1_fail())
    assert fail.status == ab.FAIL and fail.code == ab.B1_NOT_PASSING

    class _Absent:
        status, code, detail = None, "", ""
    unk = ab.measure(good, _Absent())
    assert unk.status == ab.UNKNOWN and unk.code == ab.B1_MISSING


def test_12_a_non_flat_book_reaches_the_baseline_through_b1():
    """The books are not re-read here. Two implementations of 'is it flat' is how they come to
    disagree, so this asserts the ONE implementation is consulted."""
    import inspect

    src = inspect.getsource(ab.measure)
    assert "track1_b1" in src
    assert "read_book" not in src and "read_track1_book" not in src, \
        "the baseline reads the books itself — that is a second implementation"


# ═══════════════════════════════════════════════════════════════════════════════
# 13-16  the record, and what it may never claim
# ═══════════════════════════════════════════════════════════════════════════════

def test_13_a_recorded_baseline_is_durable_and_appends(tmp_path):
    r = ab.measure(ab.from_account_values(_rows(USD=250_000.0)), _b1_pass())
    p1 = ab.record(r, tmp_path, source="test")
    p2 = ab.record(r, tmp_path, source="test")
    assert p1 == p2
    assert str(p1).replace("\\", "/").endswith(
        f"{ab.BASELINE_DIR}/account_baseline_{r.checked_at[:10].replace('-', '')}.jsonl") or \
        ab.BASELINE_DIR in str(p1).replace("\\", "/")
    rows = [json.loads(x) for x in p1.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 2, "the second record overwrote the first"
    assert rows[0]["schema"] == ab.SCHEMA and rows[0]["route"] == ab.ROUTE


def test_14_every_record_carries_the_attribution_caveat(tmp_path):
    """On a shared login, zero is attributable and non-zero is not."""
    r = ab.measure(ab.from_account_values(_rows(USD=250_000.0)), _b1_pass())
    row = json.loads(ab.record(r, tmp_path).read_text(encoding="utf-8").splitlines()[0])
    assert "attribution" in row
    assert "non-zero" in row["attribution"]


def test_15_an_absent_or_stale_record_never_reads_as_pass(tmp_path):
    assert ab.latest(tmp_path).status == ab.UNKNOWN
    assert ab.latest(tmp_path).code == ab.NO_RECORD

    import datetime as dt

    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=30)).isoformat()
    r = ab.BaselineResult(ab.PASS, ab.OK, "fine", old)
    ab.record(r, tmp_path)
    got = ab.latest(tmp_path)
    assert got.status == ab.UNKNOWN, "a 30-hour-old PASS was read back as a PASS"
    assert got.code == ab.RECORD_STALE


def test_16_an_unreadable_record_is_unknown_not_missing(tmp_path):
    d = tmp_path / ab.BASELINE_DIR
    d.mkdir(parents=True)
    (d / "account_baseline_20260827.jsonl").write_text("{not json\n", encoding="utf-8")
    got = ab.latest(tmp_path)
    assert got.status == ab.UNKNOWN
    assert got.code == ab.RECORD_UNREADABLE
    assert got.code != ab.NO_RECORD, "unreadable was flattened into absent"


# ═══════════════════════════════════════════════════════════════════════════════
# 17-19  the readiness gate
# ═══════════════════════════════════════════════════════════════════════════════

def test_17_readiness_refuses_without_a_current_baseline(tmp_path):
    from global_index import track1_paper_readiness as pr

    r = pr.readiness(tmp_path, today="2026-08-27")
    chk = next(c for c in r["checks"] if c["name"] == "paper_account_baseline")
    assert chk["status"] != "ok"
    assert r["ready"] is False


def test_18_a_fresh_pass_satisfies_that_one_check(tmp_path):
    from global_index import track1_paper_readiness as pr

    ab.record(ab.measure(ab.from_account_values(_rows(USD=250_000.0)), _b1_pass()), tmp_path)
    r = pr.readiness(tmp_path, today="2026-08-27")
    chk = next(c for c in r["checks"] if c["name"] == "paper_account_baseline")
    assert chk["status"] == "ok", chk["detail"]
    # and it did not open anything else
    assert r["ready"] is False, "one check passing made the whole gate ready"


def test_19_orders_are_still_impossible_and_nothing_was_armed():
    from global_index import track1_gates as gates

    possible, blocking = gates.may_enable_orders()
    assert possible is False
    assert blocking
    assert not Path("global_index/track1_runtime/orders").exists()
    assert not Path("track1_go_live_confirmation.json").exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 20-22  status, dashboard, and the shadow evidence that must survive
# ═══════════════════════════════════════════════════════════════════════════════

def test_20_the_dashboard_block_is_separate_from_shadow_evidence(tmp_path):
    from monitor.backend import track1_runtime_reader as rd

    d = rd._paper_account(tmp_path)
    assert d["separate_from_shadow_evidence"] is True
    assert d["status"] == ab.UNKNOWN
    assert "attribution" in d or d["code"] == "reader_failed"


def test_21_a_recorded_baseline_renders_with_its_currency(tmp_path):
    from monitor.backend import track1_runtime_reader as rd

    ab.record(ab.measure(ab.from_account_values(_rows(USD=250_000.0)), _b1_pass()), tmp_path)
    d = rd._paper_account(tmp_path)
    assert d["status"] == ab.PASS
    assert d["currency"] == "USD" and d["equity"] == 250_000.0
    assert "USD 250,000" in d["line"]
    # the expectation travels too, so a reader can see what it was compared against
    assert d["expected_equity"] == 250_000.0 and d["expected_currency"] == "USD"


def test_22_recording_a_baseline_clears_no_shadow_evidence(tmp_path):
    """The account was reset; the evidence of what the route did must not be."""
    from global_index import track1_shadow_intent as si

    day = "2026-08-21"
    si.append(si.decide_row("D", day, status=si.NO_SETUP, reason_code=si.NO_CANDIDATE),
              root=tmp_path, day=day)
    before = si.read_day(str(tmp_path), day)
    assert before

    ab.record(ab.measure(ab.from_account_values(_rows(USD=250_000.0)), _b1_pass()), tmp_path)

    assert si.read_day(str(tmp_path), day) == before, "shadow evidence changed"
    # and the baseline lives somewhere else entirely
    assert ab.BASELINE_DIR != si.SHADOW_INTENT_DIR


def test_23_zero_on_a_dashboard_is_not_a_broker_reconcile():
    """`from_dashboard_snapshot` refuses to read an old snapshot as proof, and the baseline
    inherits that refusal by requiring B1 to PASS on evidence that knows the difference."""
    snap = b1.from_dashboard_snapshot({"connected": True, "positions": [], "open_orders": []})
    r = ab.measure(ab.from_account_values(_rows(USD=250_000.0)),
                   b1.measure(
                       b1.BookState(path="x", state=b1.BOOK_READ, count=0, positions=[],
                                    error=""),
                       b1.BookState(path="y", state=b1.BOOK_READ, count=0, positions=[],
                                    error=""),
                       snap))
    assert r.status != ab.PASS, \
        "a dashboard snapshot showing 0/0 was accepted as a broker reconcile"


# ═══════════════════════════════════════════════════════════════════════════════
# 24-25  the tool itself
# ═══════════════════════════════════════════════════════════════════════════════

def test_24_the_connecting_tool_is_outside_the_gate_scanned_prefix():
    """Stage 5ZQ closed the live-frame gate by naming a connecting module `track1_b1_audit.py`.
    The gate was not softened; the file was renamed. The same rule applies here."""
    from global_index import track1_gates as gates

    assert not Path("global_index/track1_account_baseline_audit.py").exists()
    assert Path("global_index/account_baseline_audit.py").exists()

    mods = gates.route_modules("global_index")
    assert "track1_account_baseline" in mods, "the pure module is not on the route"
    assert "account_baseline_audit" not in mods

    src = Path("global_index/track1_account_baseline.py").read_text(encoding="utf-8")
    import ast
    names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
    assert "IBKRBroker" not in names, "the gate-scanned module constructs a broker"

    ok, _detail = gates.live_frame_wiring("global_index")
    assert ok is True, "the live-frame gate closed"


def test_25_the_tool_has_no_order_path_and_its_own_client_id():
    from global_index import account_baseline_audit as tool

    src = Path("global_index/account_baseline_audit.py").read_text(encoding="utf-8")
    for forbidden in ("send_order", "placeOrder", "--allow-orders", "TRACK1_ORDERS_APPROVED"):
        assert forbidden not in src, forbidden
    # distinct from every other id this repo connects with
    from global_index.track1_slots import TRACK1_SAFETY_CLIENT_ID
    from global_index.b1_audit import DEFAULT_CLIENT_ID as B1_ID

    assert tool.DEFAULT_CLIENT_ID not in (1, 89, TRACK1_SAFETY_CLIENT_ID, B1_ID), \
        "the account probe shares a client id — two processes on one id cost this project " \
        "six entry slots in a morning"


# ═══════════════════════════════════════════════════════════════════════════════
# mutations
# ═══════════════════════════════════════════════════════════════════════════════

def _must_fail(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except AssertionError:
        return True
    return False


def test_M1_currency_dropped_mutation(monkeypatch):
    """Collapse: the probe stops keeping the currency, so CAD reads as fine."""
    monkeypatch.setattr(ab, "from_account_values",
                        lambda rows, **k: ab.AccountEvidence(
                            source="x", connected=True, observed_at=ab._now(),
                            currency="USD", equity=250_000.0))
    assert _must_fail(test_3_an_account_reporting_only_CAD_fails, monkeypatch), \
        "test_3 stayed green while the currency was discarded"


def test_M2_warn_starts_opening_the_gate_mutation(monkeypatch):
    monkeypatch.setattr(ab, "SATISFIES_GATE", (ab.PASS, ab.WARN))
    assert _must_fail(test_6_a_WARN_does_not_open_the_gate), \
        "test_6 stayed green while a WARN satisfied the gate"


def test_M3_stale_record_read_as_pass_mutation(monkeypatch, tmp_path):
    monkeypatch.setattr(ab, "MAX_RECORD_AGE_HOURS", 100_000)
    assert _must_fail(test_15_an_absent_or_stale_record_never_reads_as_pass, tmp_path), \
        "test_15 stayed green while a stale record was read back as a PASS"


def test_M4_unreadable_flattened_into_absent_mutation(monkeypatch, tmp_path):
    real = ab.latest
    monkeypatch.setattr(ab, "latest",
                        lambda root=".", **k: ab.BaselineResult(
                            ab.UNKNOWN, ab.NO_RECORD, "mutated", ab._now()))
    assert _must_fail(test_16_an_unreadable_record_is_unknown_not_missing, tmp_path), \
        "test_16 stayed green while unreadable was flattened into absent"
    assert real is not None


def test_M5_readiness_stops_asking_for_a_baseline_mutation(monkeypatch, tmp_path):
    from global_index import track1_paper_readiness as pr

    monkeypatch.setattr(pr._ab, "latest",
                        lambda root=".", **k: ab.BaselineResult(
                            ab.PASS, ab.OK, "mutated", ab._now()))
    r = pr.readiness(tmp_path, today="2026-08-27")
    chk = next(c for c in r["checks"] if c["name"] == "paper_account_baseline")
    assert chk["status"] == "ok", "the mutation did not take"
    assert _must_fail(test_17_readiness_refuses_without_a_current_baseline, tmp_path), \
        "test_17 stayed green while readiness accepted a baseline that was never recorded"
