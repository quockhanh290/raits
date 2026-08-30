"""Stage 5ZM — Track 1 reports from Track 1's artefacts, and legacy stops eating its rows.

Two directions, and they are different failures. A Track 1 report that quietly showed legacy's
book would be worse than an empty one, because an empty one is obviously empty and a borrowed
one looks like an answer. And a Track 1 row reaching legacy's aggregate enters legacy's
fill-quality and P&L gates as a legacy fill.

Nothing here writes into the runtime tree. Every artefact is under `tmp_path` and the last part
proves it by mtime — scoped to the paths this suite touches, because the live NKD window may be
open and writing while these run.
"""
from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from global_index import track1_report as tr                    # noqa: E402

REPO = Path(r"d:\raits")
_IMPORTED_AT = time.time()

LEGACY_PATHS = ("trade_log.jsonl", "live_positions.json")


# ══════════════════════════════════════════════════════════════════════════════
# helpers — every artefact written the way the real writer writes it
# ══════════════════════════════════════════════════════════════════════════════

def write_t1_trade_log(root: Path, rows) -> Path:
    p = root / tr.TRADE_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def a_close(*, route: str | None = tr.ROUTE, inst: str = "MES") -> dict:
    row = {"type": "CLOSE", "inst": inst, "cluster": "roska4_swing", "direction": "long",
           "contracts": 1, "fill_price": 5000.0, "exit_reason": "MAX_HOLD",
           "ts": "2026-08-26T18:00:00+00:00"}
    if route is not None:
        row["route"] = route
    return row


def write_t1_book(root: Path, *, positions=(), route: str = tr.ROUTE,
                  cut_day: str = "2026-08-26") -> Path:
    p = root / tr.BOOK
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "schema_version": 2, "route": route, "window": "live",
        "cut_instant": f"{cut_day}T15:55:01-04:00", "cur_day": cut_day,
        "equity": 0.0, "peak_equity": 0.0, "day_start_equity": 0.0,
        "positions": list(positions), "booked_counter": {}, "counters": {}}), encoding="utf-8")
    return p


def write_journal(root: Path, rows, day: str = "20260826") -> Path:
    p = root / tr.ORDERS_DIR / f"track1_orders_{day}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def an_intent(state: str = "intended") -> dict:
    return {"trade_id": "t1", "sleeve": "roska4_swing", "instrument": "MES",
            "tradable_symbol": "MES", "direction": "long", "qty": 1, "state": state,
            "ref_day": "2026-08-26", "idempotency_key": "k1"}


def a_position(inst: str = "MES") -> dict:
    return {"inst": inst, "instrument": inst, "sleeve": "roska4_swing",
            "cluster": "roska4_swing", "direction": "long", "entry_price": 5000.0,
            "stop_price": 4950.0, "entry_time": "2026-08-26T14:05:00", "contracts": 1}


def legacy_fixture(root: Path, *, rows) -> Path:
    p = root / "trade_log.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════════════════════════
# A. the Track 1 reader never reads a legacy path — structurally
# ══════════════════════════════════════════════════════════════════════════════

def test_2_the_module_contains_no_legacy_path_literal():
    """Asserted by AST over string LITERALS, so a docstring mentioning a legacy file is not
    mistaken for code that reads one — and so the claim survives a rewrite of the prose."""
    tree = ast.parse((REPO / "global_index" / "track1_report.py").read_text(encoding="utf-8"))
    lits = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and len(n.value) < 70 and "\n" not in n.value]
    offenders = [l for l in lits if any(p in l for p in LEGACY_PATHS)]
    assert offenders == [], offenders


def test_the_module_opens_nothing_outside_its_own_three_paths(tmp_path):
    """Behavioural, not textual: run the whole report against an empty root and record every
    path it tried to open. A literal check alone would miss a path built by concatenation."""
    import builtins
    opened = []
    real_open = builtins.open
    real_read = Path.read_text

    def spy_open(file, *a, **kw):
        opened.append(str(file))
        return real_open(file, *a, **kw)

    def spy_read(self, *a, **kw):
        opened.append(str(self))
        return real_read(self, *a, **kw)

    builtins.open, Path.read_text = spy_open, spy_read
    try:
        write_t1_trade_log(tmp_path, [a_close()])
        write_t1_book(tmp_path, positions=[a_position()])
        write_journal(tmp_path, [an_intent()])
        opened.clear()
        tr.report(tmp_path)
    finally:
        builtins.open, Path.read_text = real_open, real_read
    bad = [o for o in opened if any(p in o.replace("\\", "/") for p in LEGACY_PATHS)]
    assert bad == [], bad
    assert opened, "nothing was opened at all — the spy did not observe the reader"


def test_the_report_says_so_in_its_own_payload(tmp_path):
    assert tr.report(tmp_path)["reads_legacy_paths"] is False


# ══════════════════════════════════════════════════════════════════════════════
# B. missing vs empty — never the same, never a fallback
# ══════════════════════════════════════════════════════════════════════════════

def test_3_a_missing_track1_trade_log_reports_not_produced(tmp_path):
    r = tr.read_trade_log(tmp_path)
    assert r["state"] == tr.NOT_PRODUCED
    assert r["rows"] == 0
    assert "yet" in r["reading"]


def test_4_an_empty_track1_trade_log_reports_zero_rows_not_missing(tmp_path):
    write_t1_trade_log(tmp_path, [])
    r = tr.read_trade_log(tmp_path)
    assert r["state"] == tr.EMPTY, r
    assert r["state"] != tr.NOT_PRODUCED
    assert r["rows"] == 0


def test_3b_a_missing_track1_reader_does_not_fall_back_even_when_legacy_is_full(tmp_path):
    """The fallback that must never exist: legacy has 28 rows, Track 1 has none."""
    legacy_fixture(tmp_path, rows=[{"type": "CLOSE", "inst": "MES", "fill_price": 1.0}] * 28)
    (tmp_path / "live_positions.json").write_text(
        json.dumps({"positions": [a_position(), a_position("MNQ")]}), encoding="utf-8")
    r = tr.report(tmp_path)
    assert r["trade_log"]["state"] == tr.NOT_PRODUCED
    assert r["trade_log"]["rows"] == 0
    assert r["book"]["state"] == tr.NOT_PRODUCED
    assert r["book"]["positions"] is None


def test_6_a_zero_position_book_reports_zero_not_missing(tmp_path):
    write_t1_book(tmp_path, positions=[])
    b = tr.read_book(tmp_path)
    assert b["state"] == tr.EMPTY and b["positions"] == 0, b
    assert "flat route" in b["reading"]


def test_a_missing_book_reports_none_positions_not_zero(tmp_path):
    """Zero and 'no answer' must not be the same number."""
    b = tr.read_book(tmp_path)
    assert b["state"] == tr.NOT_PRODUCED
    assert b["positions"] is None, "a missing book reported zero positions"


# ══════════════════════════════════════════════════════════════════════════════
# C. the route tag is required on every row
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("route", [None, "legacy", "", "track1"])
def test_5_a_row_without_the_right_route_is_invalid_not_counted(tmp_path, route):
    write_t1_trade_log(tmp_path, [a_close(route=route)])
    r = tr.read_trade_log(tmp_path)
    assert r["rows"] == 0, "an untagged or foreign row was counted as Track 1 P&L"
    assert r["invalid_rows"] == 1
    assert r["invalid"][0]["route"] == route


def test_a_correctly_tagged_row_is_counted(tmp_path):
    write_t1_trade_log(tmp_path, [a_close(), a_close(inst="MNQ")])
    r = tr.read_trade_log(tmp_path)
    assert r["rows"] == 2 and r["invalid_rows"] == 0
    assert r["closes"] == 2


def test_a_book_naming_another_route_is_refused(tmp_path):
    write_t1_book(tmp_path, route="legacy_r4")
    b = tr.read_book(tmp_path)
    assert b["state"] == tr.UNREADABLE
    assert b["positions"] is None
    assert "legacy_r4" in b["detail"]


def test_a_malformed_line_is_counted_not_swallowed(tmp_path):
    p = write_t1_trade_log(tmp_path, [a_close()])
    p.write_text(p.read_text(encoding="utf-8") + "{ truncated\n", encoding="utf-8")
    r = tr.read_trade_log(tmp_path)
    assert r["rows"] == 1 and r["malformed_lines"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# D. the dry-run journal feeds EXPECTED reporting, never actual
# ══════════════════════════════════════════════════════════════════════════════

def test_7_a_dry_run_journal_feeds_the_expected_report(tmp_path):
    write_journal(tmp_path, [an_intent(), an_intent("submitted")])
    j = tr.read_order_journal(tmp_path)
    assert j["state"] == tr.AVAILABLE
    assert j["rows"] == 2
    assert j["source"] == "dry_run"
    assert "INTENDED" in j["reading"], "the report does not say these were never sent"
    assert sorted(j["order_states"]) == ["intended", "submitted"]


def test_a_missing_journal_is_not_produced_not_empty(tmp_path):
    j = tr.read_order_journal(tmp_path)
    assert j["state"] == tr.NOT_PRODUCED and j["rows"] == 0


def test_journal_rows_never_claim_broker_verification(tmp_path):
    write_journal(tmp_path, [an_intent("submitted")])
    b = tr.broker_evidence(tmp_path)
    assert b["broker_verified"] is False
    assert tr.NO_ORDERS_YET in b["reasons"]


# ══════════════════════════════════════════════════════════════════════════════
# E. broker evidence — false, with the reason, always
# ══════════════════════════════════════════════════════════════════════════════

def test_8_no_statement_on_disk_reports_statement_unavailable(tmp_path):
    b = tr.broker_evidence(tmp_path)
    assert b["broker_verified"] is False
    assert tr.STATEMENT_UNAVAILABLE in b["reasons"]
    assert b["statements_on_disk"] == 0


def test_9_a_statement_that_cannot_name_a_route_reports_route_unattributed(tmp_path):
    d = tmp_path / "monitor" / "inputs" / "ibkr_flex"
    d.mkdir(parents=True, exist_ok=True)
    (d / "flex_x.csv").write_text('"ClientAccountID","Symbol"\n"U1","MES"\n', encoding="utf-8")
    b = tr.broker_evidence(tmp_path)
    assert b["broker_verified"] is False
    assert tr.ROUTE_UNATTRIBUTED in b["reasons"]
    assert tr.STATEMENT_UNAVAILABLE not in b["reasons"], (
        "a statement exists; the problem is that it cannot say whose fill it is")


def test_the_real_statements_carry_no_route_field():
    """Measured, not assumed — this is the fact B1 rests on."""
    d = REPO / "monitor" / "inputs" / "ibkr_flex"
    files = sorted(d.glob("*.csv")) if d.is_dir() else []
    if not files:
        pytest.skip("no broker statement on this machine")
    header = files[-1].read_text(encoding="utf-8", errors="replace").splitlines()[0]
    fields = [f.strip().strip('"').lower() for f in header.split(",")]
    for name in ("route", "strategy", "orderref", "clientid"):
        assert not any(name in f for f in fields), (name, fields)
    assert any("clientaccountid" in f for f in fields), fields


def test_broker_verified_is_never_true_anywhere_in_the_report(tmp_path):
    write_t1_trade_log(tmp_path, [a_close()])
    write_t1_book(tmp_path, positions=[a_position()])
    write_journal(tmp_path, [an_intent("submitted")])
    payload = json.dumps(tr.report(tmp_path))
    assert '"broker_verified": true' not in payload.lower().replace(" ", " ")
    assert tr.report(tmp_path)["broker"]["broker_verified"] is False


# ══════════════════════════════════════════════════════════════════════════════
# F. parity — three answers, and UNKNOWN is never PASS
# ══════════════════════════════════════════════════════════════════════════════

def test_both_flat_is_pass_but_says_attribution_is_unknown(tmp_path):
    write_t1_book(tmp_path, positions=[])
    p = tr.open_position_parity(tmp_path)
    assert p["status"] == tr.PASS and p["code"] == "both_flat"
    assert p["attribution"] == tr.ATTRIBUTION_UNKNOWN
    assert "B1" in p["attribution_note"]
    assert p["broker_verified"] is False


def test_a_missing_book_is_unknown_not_pass(tmp_path):
    p = tr.open_position_parity(tmp_path)
    assert p["status"] == tr.UNKNOWN
    assert p["status"] != tr.PASS


def test_a_position_with_no_journal_row_is_a_failure(tmp_path):
    write_t1_book(tmp_path, positions=[a_position()])
    p = tr.open_position_parity(tmp_path)
    assert p["status"] == tr.FAIL and p["code"] == "book_without_journal"


def test_a_journal_row_with_a_flat_book_is_a_failure(tmp_path):
    write_t1_book(tmp_path, positions=[])
    write_journal(tmp_path, [an_intent("submitted")])
    p = tr.open_position_parity(tmp_path)
    assert p["status"] == tr.FAIL and p["code"] == "journal_without_book"


def test_both_populated_is_unknown_until_real_fills_exist(tmp_path):
    write_t1_book(tmp_path, positions=[a_position()])
    write_journal(tmp_path, [an_intent("submitted")])
    p = tr.open_position_parity(tmp_path)
    assert p["status"] == tr.UNKNOWN and p["code"] == "not_comparable_yet"


# ══════════════════════════════════════════════════════════════════════════════
# G. the legacy side — Track 1 rows excluded, legacy history kept
# ══════════════════════════════════════════════════════════════════════════════

def test_1_legacy_rows_are_unchanged_by_the_split(tmp_path):
    from monitor.backend import paper_evidence_reader as per
    rows = [{"type": "CLOSE", "inst": "MES", "fill_price": 1.0},
            {"type": "OPEN", "inst": "MNQ", "fill_price": 2.0}]
    p = legacy_fixture(tmp_path, rows=rows)
    kept, foreign, bad, err = per._trade_records_split(p)
    assert kept == rows, "untagged legacy history was dropped"
    assert foreign == [] and bad == 0 and err is None


def test_a_track1_tagged_row_is_excluded_from_the_legacy_aggregate(tmp_path):
    from monitor.backend import paper_evidence_reader as per
    legacy = {"type": "CLOSE", "inst": "MES", "fill_price": 1.0}
    intruder = a_close()
    p = legacy_fixture(tmp_path, rows=[legacy, intruder])
    kept, foreign, _bad, _err = per._trade_records_split(p)
    assert kept == [legacy]
    assert foreign == [intruder]


def test_the_exclusion_is_reported_not_silent(tmp_path):
    """A filter whose effect nobody can see is a filter nobody can check."""
    import inspect
    from monitor.backend import paper_evidence_reader as per
    src = inspect.getsource(per)
    tree = ast.parse(src)
    keys = {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "trade_log_foreign_route_rows" in keys
    assert "trade_log_foreign_routes" in keys


def test_the_legacy_pnl_report_also_excludes_foreign_rows(tmp_path):
    """The third layer, and the one that matters most: this module IS the P&L number.

    The corruption path is closed at source — Track 1 writes its own file — so this should
    never fire. It is here because a file can be mis-wired by one argument and the tag travels
    with the row.
    """
    import monitor.paper_pnl_compare as ppc
    assert ppc.FOREIGN_ROUTES == ("track1_candidate",)
    tree = ast.parse((REPO / "monitor" / "paper_pnl_compare.py").read_text(encoding="utf-8"))
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)
              and any(isinstance(c, ast.Name) and c.id == "FOREIGN_ROUTES"
                      for c in n.comparators)]
    assert len(guards) == 2, f"{len(guards)} guard(s); both row loops must be covered"


def test_the_legacy_pnl_report_keeps_untagged_rows(tmp_path):
    """Every row written before Stage 5ZG is untagged. Dropping those would empty the report
    of its entire history — the failure that would look like a working filter."""
    import monitor.paper_pnl_compare as ppc
    rows = [{"type": "OPEN", "inst": "MES", "entry_day": "2026-08-01", "fill_price": 1.0},
            {"type": "OPEN", "inst": "MNQ", "entry_day": "2026-08-02", "fill_price": 2.0},
            a_close(route=tr.ROUTE) | {"type": "OPEN", "entry_day": "2026-08-03"}]
    p = tmp_path / "trade_log.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    got = ppc._paper_open_signals(p, "2026-01-01")
    days = sorted({str(g.get("day") or g.get("entry_day") or "")[:10] for g in got}
                  if isinstance(got, list) and got and isinstance(got[0], dict) else [])
    assert len(got) == 2, (len(got), got)
    assert "2026-08-03" not in days, days


def test_the_old_three_tuple_helper_still_exists_for_its_callers(tmp_path):
    from monitor.backend import paper_evidence_reader as per
    p = legacy_fixture(tmp_path, rows=[{"type": "CLOSE"}])
    out = per._trade_records(p)
    assert len(out) == 3, "the back-compatible signature changed"
    assert out[0] == [{"type": "CLOSE"}]


def test_the_filter_keeps_untagged_history_by_design():
    """Every row written before Stage 5ZG is untagged. 'keep only rows tagged legacy' would
    silently empty the aggregate of its entire history, so the filter excludes FOREIGN routes
    rather than selecting legacy ones."""
    from monitor.backend import paper_evidence_reader as per
    assert per.FOREIGN_ROUTES == ("track1_candidate",)


# ══════════════════════════════════════════════════════════════════════════════
# H. the dashboard exposes the state without claiming readiness
# ══════════════════════════════════════════════════════════════════════════════

def test_10_the_panel_shows_reporting_state_and_does_not_claim_paper_readiness(tmp_path):
    from monitor.backend import track1_runtime_reader as trr
    write_t1_trade_log(tmp_path, [a_close()])
    write_t1_book(tmp_path, positions=[])
    block = trr.read_track1_runtime(tmp_path)["reporting"]
    assert block["present"] is True
    assert block["paper_ready"] is False
    assert block["broker"]["broker_verified"] is False
    assert block["reads_legacy_paths"] is False
    assert "not paper readiness" in block["paper_ready_reading"]


def test_the_panel_fails_closed_if_the_reader_raises(tmp_path, monkeypatch):
    from monitor.backend import track1_runtime_reader as trr
    monkeypatch.setattr(tr, "report",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    block = trr.read_track1_runtime(tmp_path)["reporting"]
    assert block["present"] is False
    assert block["paper_ready"] is False
    assert block["broker"]["broker_verified"] is False


# ══════════════════════════════════════════════════════════════════════════════
# I. nothing was armed, nothing real was written
# ══════════════════════════════════════════════════════════════════════════════

def test_11_no_allow_orders_was_introduced_anywhere():
    for rel in ("global_index/track1_report.py",
                "monitor/backend/paper_evidence_reader.py",
                "monitor/backend/track1_runtime_reader.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        lits = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not any("--allow-orders" in l for l in lits), rel


def test_orders_are_still_impossible():
    from global_index import track1_gates as g
    allowed, reasons = g.may_enable_orders()
    ids = [r.split(":")[0] for r in reasons]
    assert allowed is False
    for want in ("B1_broker_account_or_legacy_retirement", "PAPER_SHADOW_EVIDENCE",
                 "REGIME_LABEL_VERIFICATION"):
        assert want in ids, ids


def test_no_production_artefact_was_written_by_this_run():
    for name in ("trade_log.jsonl", tr.TRADE_LOG, "live_positions.json", tr.BOOK,
                 "global_index/preflight_state.json"):
        p = REPO / name
        if p.exists():
            assert p.stat().st_mtime < _IMPORTED_AT, name


def test_the_preflight_record_still_holds_the_operator_restored_seven_days():
    """The 5ZL incident must not quietly come back, and 2026-08-26 must stay out until the
    real 13:45 ET pre-flight sets it."""
    p = REPO / "global_index" / "preflight_state.json"
    if not p.exists():
        pytest.skip("no pre-flight record on this machine")
    days = json.loads(p.read_text(encoding="utf-8"))
    assert sorted(days) == ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
                            "2026-08-21", "2026-08-24", "2026-08-25"], sorted(days)


def test_no_order_directory_or_confirmation_file_appeared():
    for name in ("track1_go_live_confirmation.json", tr.ORDERS_DIR):
        assert not (REPO / name).exists(), name
