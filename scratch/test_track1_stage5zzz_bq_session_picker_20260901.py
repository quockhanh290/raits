"""Stage 5ZZZ-BQ. The panel could only ever describe the session in progress.

`build` has taken a `day` since it was written; the endpoint pinned it to today, so there was
no way to look at yesterday without editing code. Two things had to be true before a picker
was safe to offer:

  1. It must list the sessions that EXIST, not a calendar range. Measured 2026-09-01: the
     signal store holds 25/08 through 01/09 and per-slot diagnostics begin 31/08, while 30/08
     is a Sunday and is in neither. A picker offering "the last 7 days" hands back an empty
     panel for a day nothing ever wrote -- the absence-with-no-reason this band has spent
     several stages removing.
  2. It must say which kind of session each one is. A day without per-slot diagnostics still
     shows its condition rows, because the detector is replayed over the bars on disk and
     labelled RECONSTRUCTED; only the session chart stays empty. "Nothing here" and "nothing
     was recorded here" are different facts and the picker has to carry both.
"""
from __future__ import annotations

import json

import pytest

from monitor.backend import track1_market_view as MV


def _touch(root, store: str, day: str, line: dict | None = None):
    d = root / "global_index" / "track1_runtime" / store
    d.mkdir(parents=True, exist_ok=True)
    p = d / ("track1_%s_%s.jsonl" % (
        "strategy_diagnostics" if store == "strategy_diagnostics" else "signals",
        day.replace("-", "")))
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line or {"day": day}) + "\n")


@pytest.fixture()
def store(tmp_path):
    """The shape measured on 2026-09-01: signals reach further back than diagnostics."""
    for day in ("2026-08-25", "2026-08-26", "2026-08-28", "2026-08-31", "2026-09-01"):
        _touch(tmp_path, "signals", day)
    for day in ("2026-08-31", "2026-09-01"):
        _touch(tmp_path, "strategy_diagnostics", day)
    return tmp_path


def test_the_sessions_offered_are_the_ones_on_disk(store):
    """A calendar range would offer 27/08 and 30/08, which nothing ever wrote."""
    days = [r["day"] for r in MV.available_sessions(store, today="2026-09-01")]
    assert days == ["2026-09-01", "2026-08-31", "2026-08-28", "2026-08-26", "2026-08-25"], days


def test_a_day_says_whether_it_has_a_per_slot_record(store):
    """What the chart needs, and the only thing separating "empty" from "never recorded"."""
    got = {r["day"]: r["has_diagnostics"] for r in MV.available_sessions(store, today="2026-09-01")}
    assert got == {"2026-09-01": True, "2026-08-31": True, "2026-08-28": False,
                   "2026-08-26": False, "2026-08-25": False}, got


def test_today_is_offered_even_before_anything_has_been_written(tmp_path):
    """The first request of a morning happens before any slot has run. A picker that drops
    today until a file appears would take the live session off the page at exactly the moment
    an operator is most likely to be looking at it."""
    _touch(tmp_path, "signals", "2026-08-31")
    rows = MV.available_sessions(tmp_path, today="2026-09-01")
    assert rows[0]["day"] == "2026-09-01" and rows[0]["is_today"] is True, rows
    assert rows[0]["has_signals"] is False, rows[0]


def test_exactly_one_row_is_marked_today(store):
    """Two would let the page highlight a past session as the live one."""
    rows = MV.available_sessions(store, today="2026-09-01")
    assert [r["day"] for r in rows if r["is_today"]] == ["2026-09-01"], rows


def test_the_limit_keeps_the_newest_not_the_oldest(store):
    """Off-by-one here reads as "the store only goes back two days"."""
    days = [r["day"] for r in MV.available_sessions(store, today="2026-09-01", limit=2)]
    assert days == ["2026-09-01", "2026-08-31"], days


def test_a_missing_runtime_directory_is_an_empty_list_not_a_crash(tmp_path):
    """This feeds an endpoint whose whole contract is that it never takes the page down."""
    assert MV.available_sessions(tmp_path, today="2026-09-01") == [
        {"day": "2026-09-01", "has_signals": False, "has_diagnostics": False, "is_today": True}]


# -- the endpoint ------------------------------------------------------------------------
def _client():
    from monitor.backend.app import app
    return app.test_client()


def test_the_endpoint_answers_for_the_day_it_was_asked_for():
    """The defect: `build(ROOT)` with no day, so every request described today."""
    r = _client().get("/api/v1/track1-market-view?day=2026-08-31")
    assert r.status_code == 200
    body = r.get_json()
    assert body["requested_day"] == "2026-08-31", body["requested_day"]
    assert body["market_view"]["session_date"] == "2026-08-31"
    assert body["market_view"]["session_is_today"] is False


def test_a_day_that_is_not_a_date_falls_back_to_today_rather_than_failing():
    """This endpoint feeds a page that must keep rendering. A 400 here blanks the band over a
    typo in a query string."""
    r = _client().get("/api/v1/track1-market-view?day=' OR 1=1--")
    assert r.status_code == 200
    body = r.get_json()
    assert body["requested_day"] is None, body["requested_day"]
    assert body["market_view"]["session_date"], body["market_view"].get("session_date")


def test_the_session_list_travels_with_the_payload():
    """The picker cannot be built from the market view alone: it has to know which days exist,
    and which of them carry a per-slot record."""
    body = _client().get("/api/v1/track1-market-view").get_json()
    rows = body["sessions"]
    assert rows, "no sessions listed -- the picker would have nothing to draw"
    assert all({"day", "has_signals", "has_diagnostics", "is_today"} <= set(r) for r in rows), rows
    assert rows == sorted(rows, key=lambda r: r["day"], reverse=True), rows


# -- Stage 5ZZZ-BV: a file on disk is not a session ---------------------------------------
def test_a_non_trading_day_on_disk_is_not_offered(store):
    """2026-08-29 was a Saturday and carried two rows -- a swing slot the gate refused -- and
    the first version of this picker offered it as a session. Opening it would have anchored
    the band on a day the market was shut: twenty-two slots reading "no record was written"
    for a session that never existed, which is the page `_anchor_day` exists to prevent."""
    _touch(store, "signals", "2026-08-29")
    days = [r["day"] for r in MV.available_sessions(store, today="2026-09-01")]
    assert "2026-08-29" not in days, days
    assert "2026-08-28" in days and "2026-08-31" in days, days


def test_the_live_row_is_the_session_the_band_anchors_on(store):
    """On a Saturday the calendar date and the anchored session differ. Marking the calendar
    date live would put a non-session at the top of the list while the band below it described
    Friday."""
    rows = MV.available_sessions(store, today="2026-08-29")
    live = [r["day"] for r in rows if r["is_today"]]
    assert live == ["2026-08-28"], rows
    assert "2026-08-29" not in [r["day"] for r in rows]


def test_the_calendar_is_the_projects_own_not_a_weekday_test_written_here(store, monkeypatch):
    """A holiday looks like a trading day to anything that only counts days of the week. This
    monkeypatches the project's calendar rather than waiting for a real holiday: if the picker
    stopped delegating, the refused day would come back."""
    from global_index import track1_freshness as fresh
    import pandas as pd

    real = fresh._is_trading_day
    monkeypatch.setattr(fresh, "_is_trading_day",
                        lambda d: False if str(pd.Timestamp(d).date()) == "2026-08-26"
                        else real(d))
    days = [r["day"] for r in MV.available_sessions(store, today="2026-09-01")]
    assert "2026-08-26" not in days, days
    assert "2026-08-25" in days, days


def test_a_calendar_that_cannot_be_loaded_does_not_empty_the_picker(store, monkeypatch):
    """A picker that empties itself because a calendar failed is worse than one that offers a
    weekend: the band still labels whatever is opened, but an empty bar looks like "there are
    no sessions"."""
    from global_index import track1_freshness as fresh

    def boom(_d):
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(fresh, "_is_trading_day", boom)
    days = [r["day"] for r in MV.available_sessions(store, today="2026-09-01")]
    assert len(days) >= 5, days
