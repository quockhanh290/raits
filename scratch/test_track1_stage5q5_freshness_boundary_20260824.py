"""Stage 5Q-5 — the D-1 freshness contract, and the boundary bar the appender never revisited.

No scheduler started or stopped, no backend restarted, no IBKR connection, no order, no
confirmation file. Every parquet or CSV this suite writes lives under `tmp_path`, and a test at
the end proves the real data files are byte-identical to what they were at import.

The two faults, both measured on 2026-08-24 before any of this was written
--------------------------------------------------------------------------
**B-5R-E.** One requirement was being asked of two data sources with different availability.
`update_spy_csv` runs inside the 13:45 pre-flight and fetches through "today"; SPY's daily bar
does not close until 16:00, so it can never bring today's close. Asking the CSV for today from
13:45 asks for a number that does not exist — and the route does not need it: a session on day
D trades the label of D-1 (`RegimeLabels.get` = `reg.asof(day - 1)`). Measured:
`preflight_state` said `2026-08-21: true` while `spy_daily_live.csv` ended `2026-08-20`.

**B-5R-F.** `update_ibkr_daily` appends `new_bars[... > last_existing]` — strictly newer — so
the minute the previous fetch stopped on is never re-fetched. A partial boundary bar is frozen
for ever, and MNQ `2026-08-21 13:45` is one: `low = 29400.25` stored against `29395.75` from
twelve independent live fetches.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

REPO = Path(r"d:\raits")

import pandas as pd                                        # noqa: E402

from global_index import run_live_day_track1 as R          # noqa: E402
from global_index import track1_freshness as fresh         # noqa: E402
from global_index import update_ibkr_daily as U            # noqa: E402

ET = "America/New_York"

REAL_DATA = {**R.default_data_paths(), "spy": "spy_daily_live.csv",
             "preflight": "global_index/preflight_state.json"}
REAL_FINGERPRINT = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
                    for k, v in REAL_DATA.items() if Path(v).exists()}

#: The snapshots that already existed when this module was imported. Anchored rather than
#: required-empty: on 2026-08-24 an APPROVED operator repair left three legitimate
#: `.pre5q5-*.bak` files beside the real parquets, and a guard that reads "none may exist"
#: cannot tell that from "this suite made one". What must stay true is that the SUITE adds
#: none, which is a comparison, not an absence.
PRE_EXISTING_SNAPSHOTS = {
    str(q) for v in R.default_data_paths().values()
    for q in (Path(v).parent.glob("*.pre5q5-*.bak") if Path(v).parent.exists() else [])
}


# ══════════════════════════════════════════════════════════════════════════════
# Part A — the requirement, split by data kind
# ══════════════════════════════════════════════════════════════════════════════

def _at(s: str):
    return pd.Timestamp(s, tz=ET)


@pytest.mark.parametrize("instant,intraday,daily", [
    # Friday, before its own pre-flight
    ("2026-08-21 09:00", "2026-08-20", "2026-08-20"),
    # Friday, after 13:45 but before the close: the parquets have today, the CSV cannot
    ("2026-08-21 14:00", "2026-08-21", "2026-08-20"),
    # Friday, after the close: the daily requirement STILL says Thursday, because a Friday
    # session trades Thursday's label. Today's close is what SATURDAY's readers need.
    ("2026-08-21 16:30", "2026-08-21", "2026-08-20"),
    # Monday morning: Friday for both. This is the case the route actually runs in.
    ("2026-08-24 09:00", "2026-08-21", "2026-08-21"),
    ("2026-08-24 10:00", "2026-08-21", "2026-08-21"),
    # Monday afternoon
    ("2026-08-24 14:00", "2026-08-24", "2026-08-21"),
    # Tuesday morning needs Monday
    ("2026-08-25 09:00", "2026-08-24", "2026-08-24"),
])
def test_the_two_requirements_at_each_instant(instant, intraday, daily):
    assert str(fresh.required_intraday_through(_at(instant)).date()) == intraday
    assert str(fresh.required_daily_close_through(_at(instant)).date()) == daily


def test_the_old_name_still_means_the_intraday_one():
    """Every existing caller means the intraday requirement. Renaming it would have moved the
    meaning of live call sites silently."""
    for t in ("2026-08-21 09:00", "2026-08-21 14:00", "2026-08-24 09:00"):
        assert fresh.required_data_through(_at(t)) == fresh.required_intraday_through(_at(t))


def test_a_weekend_asks_for_friday_not_for_saturday():
    for t in ("2026-08-22 10:00", "2026-08-23 10:00"):
        assert str(fresh.required_daily_close_through(_at(t)).date()) == "2026-08-21"
        assert str(fresh.required_intraday_through(_at(t)).date()) == "2026-08-21"


def test_the_day_after_a_holiday_does_not_ask_for_the_holiday():
    """The hole a weekday-only rule leaves. 2026-07-03 and 2026-07-04 are both closed, so the
    Monday after must reach back to Thursday 2026-07-02 — a close that can exist. Asking for a
    holiday is asking for a number no refresh can ever supply, and the gate would refuse for
    ever on a route that was fine."""
    from raits.live.trading_calendar import is_trading_day
    import datetime as dt
    assert not is_trading_day(dt.date(2026, 7, 3))
    req = fresh.required_daily_close_through(_at("2026-07-06 09:00"))
    assert is_trading_day(req.date()), req
    assert str(req.date()) == "2026-07-02"


def test_the_calendar_source_is_reported_not_assumed():
    assert fresh.calendar_source() in ("raits.live.trading_calendar",
                                       "weekday_only_fallback")


# ── the measured case, both behaviours ───────────────────────────────────────

def _spy_csv(tmp_path: Path, last_date: str) -> Path:
    days = pd.bdate_range(end=last_date, periods=60)
    p = tmp_path / "spy.csv"
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"),
                  "close": [700.0 + i for i in range(len(days))]}).to_csv(p, index=False)
    return p


def _preflight(tmp_path: Path, day: str, value=True) -> Path:
    import json
    p = tmp_path / "preflight_state.json"
    p.write_text(json.dumps({day: value}), encoding="utf-8")
    return p


def test_the_measured_case_friday_afternoon_now_passes(tmp_path):
    """The half B-5R-E's fix actually closes.

    Friday 14:00: `preflight_state` says 2026-08-21 true and the CSV ends 2026-08-20. Under the
    old single requirement the gate asked the CSV for 2026-08-21 — a close that would not exist
    for another two hours — and refused. It now asks for 2026-08-20, which is both what the
    session needs and what the file holds.
    """
    csv = _spy_csv(tmp_path, "2026-08-20")
    pf = _preflight(tmp_path, "2026-08-21")
    v = fresh.evaluate(now_et=_at("2026-08-21 14:00"), regime_csv=str(csv),
                       parquets={}, preflight_state=str(pf))
    by = {c.name: c for c in v.checks}
    assert by["regime_csv"].status == "ok", by["regime_csv"]
    assert by["preflight_consistency"].status == "ok"
    assert v.allow is True


def test_the_measured_case_monday_morning_still_refuses_and_says_why(tmp_path):
    """The half the fix does NOT close, stated rather than papered over.

    Monday needs Friday's close. The only refresh ran at 13:45 on Friday, before Friday closed,
    so the file holds Thursday. That is a missing refresh, not a wrong threshold, and widening
    the requirement to accept Thursday would trade a session on a label the backtest never used.
    """
    csv = _spy_csv(tmp_path, "2026-08-20")
    pf = _preflight(tmp_path, "2026-08-21")
    v = fresh.evaluate(now_et=_at("2026-08-24 09:00"), regime_csv=str(csv),
                       parquets={}, preflight_state=str(pf))
    by = {c.name: c for c in v.checks}
    assert by["regime_csv"].status == "stale"
    assert by["regime_csv"].required == "2026-08-21"
    assert by["regime_csv"].observed == "2026-08-20"
    assert v.allow is False


def test_a_true_preflight_over_short_data_is_named_as_a_contradiction(tmp_path):
    """`preflight_state` says the 13:45 job succeeded; the CSV still does not satisfy the
    requirement. Both true, and nothing named the contradiction before this check."""
    csv = _spy_csv(tmp_path, "2026-08-20")
    pf = _preflight(tmp_path, "2026-08-21")
    v = fresh.evaluate(now_et=_at("2026-08-24 09:00"), regime_csv=str(csv),
                       parquets={}, preflight_state=str(pf))
    c = {x.name: x for x in v.checks}["preflight_consistency"]
    assert c.status == "stale"
    assert "SUCCEEDED" in c.detail and "regime_csv" in str(c.observed)


def test_the_consistency_check_is_silent_when_the_preflight_itself_failed(tmp_path):
    """Two different problems must not print as one. A failed 13:45 job is a retry; a
    successful job that leaves an input short is a contract question."""
    csv = _spy_csv(tmp_path, "2026-08-20")
    pf = _preflight(tmp_path, "2026-08-21", value=False)
    v = fresh.evaluate(now_et=_at("2026-08-24 09:00"), regime_csv=str(csv),
                       parquets={}, preflight_state=str(pf))
    by = {c.name: c for c in v.checks}
    assert by["preflight_record"].status == "stale"
    assert by["preflight_consistency"].status == "ok"
    assert "not applicable" in by["preflight_consistency"].detail


def test_a_csv_that_reached_the_required_day_passes(tmp_path):
    """The other side, so the refusals above are measuring the GAP and not merely that the
    gate can say no."""
    csv = _spy_csv(tmp_path, "2026-08-21")
    pf = _preflight(tmp_path, "2026-08-21")
    v = fresh.evaluate(now_et=_at("2026-08-24 09:00"), regime_csv=str(csv),
                       parquets={}, preflight_state=str(pf))
    by = {c.name: c for c in v.checks}
    assert by["regime_csv"].status == "ok"
    assert by["preflight_consistency"].status == "ok"
    assert v.allow is True


def test_the_record_says_which_requirement_it_used(tmp_path):
    csv = _spy_csv(tmp_path, "2026-08-21")
    pf = _preflight(tmp_path, "2026-08-21")
    v = fresh.evaluate(now_et=_at("2026-08-24 09:00"), regime_csv=str(csv),
                       parquets={}, preflight_state=str(pf))
    req = {c.name: c for c in v.checks}["requirement"]
    assert "intraday through 2026-08-21" in req.detail
    assert "daily close through 2026-08-21" in req.detail
    assert fresh.calendar_source() in req.detail


# ══════════════════════════════════════════════════════════════════════════════
# Part A2 — the post-close refresh job
# ══════════════════════════════════════════════════════════════════════════════

def _sched(**kw):
    import logging
    import os
    from global_index import run_scheduler as rs
    os.environ.setdefault("PYTEST_CURRENT_TEST", "track1-5q5")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return rs.make_scheduler(port=4002, dry_run=True, **kw)
    finally:
        logging.disable(lvl)


def test_the_post_close_spy_job_exists_in_every_mode():
    """Shared infrastructure: one CSV, one refresher. Registering it in only one scheduler mode
    would make the file's freshness depend on which mode is running."""
    for kw in ({}, {"track1_shadow": True}, {"track1_only": True}):
        job = _sched(**kw).get_job("spy_refresh_pm")
        assert job is not None, kw


def test_it_runs_after_the_close_and_before_midnight():
    from global_index import run_scheduler as rs
    src = Path(rs.__file__).read_text(encoding="utf-8")
    assert 'hour=16, minute=20' in src
    assert 'id="spy_refresh_pm"' in src


def test_it_refreshes_spy_only_and_writes_no_preflight_record():
    """A second IBKR fetch would open a second Gateway client for nothing, and a second writer
    of `preflight_state.json` would make 'did the pre-flight run' ambiguous."""
    from global_index import run_scheduler as rs
    src = Path(rs.__file__).read_text(encoding="utf-8")
    body = src[src.index("def job_spy_refresh_pm("):src.index("def _prev_bday(")]
    assert "update_spy_csv" in body
    assert "update_ibkr_daily" not in body
    assert "_preflight_ok" not in body and "_save_preflight_state" not in body
    assert "--allow-orders" not in body


def test_the_inventory_grew_by_exactly_one_in_every_mode():
    assert len(_sched().get_jobs()) == 61
    assert len(_sched(track1_shadow=True).get_jobs()) == 130
    ids = {j.id for j in _sched(track1_only=True).get_jobs()}
    assert len(ids) == 101
    assert [i for i in ids if i.startswith(("live_day", "nkd_night"))] == []


def test_scheduler_and_dashboard_mirror_still_agree():
    from global_index import track1_slots as ts
    for kw in ({}, {"track1_shadow": True}, {"track1_only": True}):
        r = ts.parity_report(**kw)
        assert r["in_parity"], (kw, r["only_in_scheduler"], r["only_in_dashboard_mirror"])


def test_the_new_job_is_classified_as_shared_infrastructure():
    """Not Track 1's and not legacy's: both routes read that CSV, and it decides no trade. A
    job in `unclassified` would turn the Stage 5L test red, which is the point of that test."""
    from global_index import track1_slots as ts
    assert ts._bucket_for("spy_refresh_pm") == "shared_infra"
    assert ts.route_classification(track1_shadow=True)["unclassified"] == []
    assert "spy_refresh_pm" not in ts.legacy_retirement_candidates(track1_shadow=True)


# ══════════════════════════════════════════════════════════════════════════════
# Part B — the boundary bar
# ══════════════════════════════════════════════════════════════════════════════

TS = pd.Timestamp("2026-08-21 17:45", tz="UTC")          # 13:45 ET


def _row(o, h, l, c, v, ts=TS):
    return pd.DataFrame({"open": [o], "high": [h], "low": [l], "close": [c], "volume": [v]},
                        index=pd.DatetimeIndex([ts]))


#: The bar as it is stored in the MNQ parquet today.
STORED = _row(29404.5, 29408.0, 29400.25, 29404.5, 1399.0)


def test_the_measured_mnq_bar_is_recognised_as_a_completion():
    got, why = U.boundary_replacement(
        STORED, _row(29404.5, 29408.0, 29395.75, 29402.0, 1600.0), last_existing=TS)
    assert got is not None
    assert why.startswith("completed:")
    assert float(got.iloc[0]["low"]) == 29395.75


@pytest.mark.parametrize("feed,code", [
    (_row(29405.0, 29408.0, 29395.75, 29402.0, 1600.0), "open_changed"),
    (_row(29404.5, 29408.0, 29401.00, 29402.0, 1600.0), "low_rose"),
    (_row(29404.5, 29407.0, 29395.75, 29402.0, 1600.0), "high_fell"),
    (_row(29404.5, 29408.0, 29395.75, 29402.0, 900.0), "volume_shrank"),
    (_row(29404.5, 29999.0, 29395.75, 29402.0, 1600.0), "moved_too_far"),
])
def test_anything_that_is_not_a_completion_refuses(feed, code):
    """A partial bar can only be COMPLETED, never contradicted. Two sources describing the same
    minute differently is a contract, clock or feed question, and this rule has no business
    guessing which."""
    got, why = U.boundary_replacement(STORED, feed, last_existing=TS)
    assert got is None
    assert why.startswith(code), why


def test_an_identical_bar_is_not_a_replacement():
    got, why = U.boundary_replacement(STORED, STORED.copy(), last_existing=TS)
    assert got is None and why.startswith("identical")


def test_a_fetch_that_does_not_cover_the_boundary_refuses():
    later = _row(1, 2, 0.5, 1.5, 10, ts=TS + pd.Timedelta(minutes=5))
    got, why = U.boundary_replacement(STORED, later, last_existing=TS)
    assert got is None and why.startswith("not_offered")


def test_a_missing_column_refuses_rather_than_comparing_what_is_left():
    got, why = U.boundary_replacement(
        STORED, _row(29404.5, 29408.0, 29395.75, 29402.0, 1600.0).drop(columns=["volume"]),
        last_existing=TS)
    assert got is None and why.startswith("schema")


def test_the_rule_is_pure_and_needs_no_broker():
    """It runs once a day at 13:45 against a live Gateway. A rule that can only be exercised
    there is a rule that is never exercised."""
    import ast
    import inspect
    fn = ast.parse(inspect.getsource(U.boundary_replacement).lstrip()).body[0]

    # Parsed, not grepped. The first version scanned the function text for "fetch" and went
    # red on its own refusal message "not_offered: the fetch does not cover ...". That is the
    # FOURTH substring-over-prose test across these stages and the fourth time it failed on a
    # sentence rather than on code.
    called = {getattr(n.func, "attr", getattr(n.func, "id", ""))
              for n in ast.walk(fn) if isinstance(n, ast.Call)}
    banned = {"read_parquet", "to_parquet", "open", "connect", "fetch_bars",
              "fetch_session_bars", "write_bytes", "read_bytes", "now", "today"}
    assert not (called & banned), called & banned
    assert not [n for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))]


def test_the_appender_is_off_by_default():
    """The only path in that file which rewrites a bar the parquet already has, and the job
    runs unattended at 13:45."""
    a = U.main.__globals__  # noqa: F841  - the flag lives on the parser
    src = Path(U.__file__).read_text(encoding="utf-8")
    assert '"--repair-boundary", action="store_true"' in src
    assert "if a.repair_boundary:" in src


def test_the_strictly_newer_filter_is_still_there_for_everything_else():
    """The boundary bar is the ONE exception. Every other historical bar is still excluded from
    the append by the same filter as before."""
    src = Path(U.__file__).read_text(encoding="utf-8")
    assert "new_only = new_bars_adj[new_bars_adj.index > last_existing]" in src


def test_the_history_invariant_exempts_only_the_boundary_timestamp():
    src = Path(U.__file__).read_text(encoding="utf-8")
    assert 'old_tail = old_tail.drop(index=[last_existing], errors="ignore")' in src
    assert "if boundary is not None:" in src


def test_a_replacement_snapshots_and_verifies_by_re_reading():
    src = Path(U.__file__).read_text(encoding="utf-8")
    body = src[src.index("_backup = None"):src.index("history-check OK")]
    assert "write_bytes(parquet_path.read_bytes())" in body
    assert "pd.read_parquet(parquet_path)" in body
    assert "BOUNDARY REPAIR DID NOT LAND" in body


# ── the concat mechanics, exercised on frames ────────────────────────────────

def _history(n=30):
    idx = pd.date_range("2026-08-21 17:16", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({"open": [100.0 + i for i in range(n)],
                         "high": [101.0 + i for i in range(n)],
                         "low": [99.0 + i for i in range(n)],
                         "close": [100.5 + i for i in range(n)],
                         "volume": [500.0 + i for i in range(n)]}, index=idx)


def _splice(existing, boundary, new_only, keep_cols):
    """The exact concat the appender performs, so the mechanics are tested rather than read."""
    parts = [existing[keep_cols]]
    if boundary is not None:
        parts.append(boundary[keep_cols])
    parts.append(new_only[keep_cols])
    out = pd.concat(parts)
    return out[~out.index.duplicated(keep="last")].sort_index()


def test_the_replacement_wins_over_the_stored_copy_and_nothing_else_moves():
    hist = _history()
    last = hist.index[-1]
    keep = list(hist.columns)
    fixed = hist.loc[[last]].copy()
    fixed.loc[last, "low"] -= 4.5
    fixed.loc[last, "volume"] += 200.0
    new_bars = _history(3).set_index(
        pd.date_range(last + pd.Timedelta(minutes=1), periods=3, freq="1min", tz="UTC"))

    out = _splice(hist, fixed, new_bars, keep)
    assert len(out) == len(hist) + 3
    assert float(out.loc[last, "low"]) == float(hist.loc[last, "low"]) - 4.5
    others = [t for t in hist.index if t != last]
    pd.testing.assert_frame_equal(out.loc[others, keep], hist.loc[others, keep])


def test_without_a_replacement_the_result_is_byte_identical_to_before():
    """Off by default must mean unchanged, not merely `if False`."""
    hist = _history()
    keep = list(hist.columns)
    new_bars = _history(3).set_index(
        pd.date_range(hist.index[-1] + pd.Timedelta(minutes=1), periods=3, freq="1min",
                      tz="UTC"))
    out = _splice(hist, None, new_bars, keep)
    pd.testing.assert_frame_equal(out.loc[hist.index, keep], hist[keep])


def test_the_index_shape_is_unchanged_by_a_replacement():
    hist = _history()
    last = hist.index[-1]
    fixed = hist.loc[[last]].copy()
    fixed.loc[last, "low"] -= 1.0
    out = _splice(hist, fixed, hist.iloc[:0], list(hist.columns))
    assert out.index.equals(hist.index)


# ══════════════════════════════════════════════════════════════════════════════
# nothing real was touched
# ══════════════════════════════════════════════════════════════════════════════

def test_no_real_data_file_was_modified_by_this_suite():
    now = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
           for k, v in REAL_DATA.items() if Path(v).exists()}
    assert now == REAL_FINGERPRINT


def test_this_suite_added_no_snapshot_beside_a_real_parquet():
    """A snapshot appearing DURING the run means a test reached a real parquet. One that was
    already there when the module loaded is the operator's, and is evidence, not a leak."""
    now = {str(q) for v in R.default_data_paths().values()
           for q in (Path(v).parent.glob("*.pre5q5-*.bak") if Path(v).parent.exists() else [])}
    assert now - PRE_EXISTING_SNAPSHOTS == set(), sorted(now - PRE_EXISTING_SNAPSHOTS)


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5Q-6 — the pre-flight now asks for the boundary repair
# ══════════════════════════════════════════════════════════════════════════════

def test_the_preflight_passes_repair_boundary():
    """Enabled on measured recurrence: one pre-flight on 2026-08-24 left THREE partial
    boundary bars out of five instruments, and Friday's equivalents refused 46 Track 1 slots.
    """
    from global_index import run_scheduler as rs
    src = Path(rs.__file__).read_text(encoding="utf-8")
    body = src[src.index("ibkr_ok = _run("):src.index("if not ibkr_ok:")]
    assert '"--repair-boundary"' in body
    assert '"global_index.update_ibkr_daily"' in body
    assert "--allow-orders" not in body


def test_a_refused_repair_marks_the_preflight_failed_not_silently_ok():
    """The condition that makes it safe to run unattended: every refusal in the appender takes
    the `failed` path, and that path exits non-zero, which the pre-flight reads as failure."""
    src = Path(U.__file__).read_text(encoding="utf-8")
    assert "sys.exit(1)   # pre-flight detects failure via returncode != 0" in src
    # every boundary refusal routes into `failed`
    body = src[src.index("_backup = None"):src.index("history-check OK")]
    assert body.count("failed.append(name)") >= 2

    from global_index import run_scheduler as rs
    sched_src = Path(rs.__file__).read_text(encoding="utf-8")
    tail = sched_src[sched_src.index("if not ibkr_ok:"):]
    assert "_preflight_ok[today] = False" in tail[:600]


def test_the_snapshot_only_happens_when_a_replacement_happens():
    """An ordinary day writes no `.bak`: the snapshot block is under the replacement branch,
    so enabling the flag does not start littering the data directory."""
    src = Path(U.__file__).read_text(encoding="utf-8")
    # The whole snapshot block, bounded by the two lines around it rather than by a character
    # count — the first draft sliced 400 characters and the block is longer than that, so the
    # assertion was measuring where the slice ended, not where the guard is.
    block = src[src.index("_backup = None"):src.index("parquet_path.parent.mkdir")]
    assert "if boundary is not None:" in block
    assert "write_bytes(parquet_path.read_bytes())" in block
    assert block.index("if boundary is not None:") < block.index("write_bytes")
