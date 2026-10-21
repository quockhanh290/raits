# -*- coding: utf-8 -*-
"""The Calm 15:55 time exit: the missing half of "in at the 10:00 open, out at the 15:55 open".

Before 2026-10-05 nothing on the route closed a Calm position: the 09:31 MAX_HOLD job reads a
five-day rule, so an entry that filled would have been held like a swing trade while 99% of the
backtest trades leave at 15:55. These tests pin the pieces that make the exit exist and be safe:

  runner    `run_time_exit` closes every position of ONE cluster regardless of hold-days, with the
            same close as MAX_HOLD (market order, stop cancelled, CLOSE row, position removed),
            and never touches another cluster; `run_maxhold_exit` is unchanged unless it is given
            a per-cluster override
  cli       connects ONLY when the book holds a position of the cluster (15:55 is inside the swing
            entry window, and a connected run is a reconcile) — unreadable book connects
  schedule  the job is in the one table the scheduler and the dashboard mirror read, its clock
            comes from the rule, and its id cannot be mistaken for a Calm STRATEGY slot
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futures.circuit_breaker import CircuitBreaker
from global_index import run_maxhold_exit as cli
from global_index import track1_calm_a as CA
from global_index import track1_slots as t1
from global_index.broker import Fill, MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner

ACCOUNT = 50_000.0
CALM = "roska4_calm"
SWING = "roska4_swing"
TODAY = pd.Timestamp("2026-10-05")
YESTERDAY = pd.Timestamp("2026-10-02")


def _guard():
    return MultiClusterGuard(clusters={
        CALM: ClusterBudget(CALM, max_gross_pct=0.05, max_net_pct=0.044),
        SWING: ClusterBudget(SWING, max_gross_pct=0.05, max_net_pct=0.044),
    }, account=ACCOUNT)


def _runner(broker, tmp_path, log=True):
    kw = dict(trade_log_path=str(tmp_path / "trades.jsonl"), route="track1_candidate") if log else {}
    return FuturesRunner(broker=broker, guard=_guard(), contracts_by_inst={},
                         signal_fn=lambda d, b, h: ([], []),
                         breaker=CircuitBreaker(account=ACCOUNT),
                         positions_path=tmp_path / "pos.json", **kw)


def _add(runner, inst, cluster, entry_day=TODAY, stop_order_id=None):
    p = OpenPos(inst=inst, direction="LONG", contracts=1, risk_dollars=300.0, cluster=cluster,
                entry_day=entry_day, stop_price=5000.0, stop_order_id=stop_order_id)
    runner.state.open_positions.append(p)
    return p


class _Spy(MockBroker):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.cancelled = []

    def cancel_order(self, oid):
        self.cancelled.append(oid)
        return True


class _FailClose(_Spy):
    def send_order(self, o, **kw):
        if o.action == "CLOSE":
            return Fill(o.inst, o.action, o.direction, o.contracts, o.cluster,
                        status="FAILED", error_msg="mock CLOSE failure")
        return super().send_order(o, **kw)


def _rows(tmp_path):
    p = tmp_path / "trades.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if p.exists() else []


# ── runner ───────────────────────────────────────────────────────────────────

def test_time_exit_closes_a_same_day_calm_position_that_maxhold_would_keep(tmp_path):
    b = _Spy({}, ACCOUNT)
    r = _runner(b, tmp_path)
    _add(r, "MES", CALM, entry_day=TODAY, stop_order_id="stp-1")

    # The control: the rule that exists today leaves it open. Without this the test below could
    # pass on a runner that closes everything.
    assert r.run_maxhold_exit(TODAY, max_hold_days=5) == []
    assert len(r.state.open_positions) == 1

    closed = r.run_time_exit(TODAY, CALM)

    assert closed == [("MES", CALM)]
    assert r.state.open_positions == []
    assert [o.action for o in b.fills] == ["CLOSE"], b.fills
    assert b.cancelled == ["stp-1"], "the working stop must be cancelled or it outlives the trade"


def test_time_exit_writes_a_close_row_labelled_as_a_time_exit(tmp_path):
    r = _runner(_Spy({}, ACCOUNT), tmp_path)
    _add(r, "MNQ", CALM)
    r.run_time_exit(TODAY, CALM)
    rows = [x for x in _rows(tmp_path) if x.get("type") == "CLOSE"]
    assert len(rows) == 1, rows
    assert rows[0]["exit_reason"] == "TIME_EXIT" and rows[0]["cluster"] == CALM, rows[0]
    assert rows[0]["route"] == "track1_candidate", rows[0]


def test_time_exit_never_touches_another_cluster(tmp_path):
    b = _Spy({}, ACCOUNT)
    r = _runner(b, tmp_path)
    _add(r, "MES", CALM)
    _add(r, "MNQ", SWING, entry_day=TODAY, stop_order_id="stp-swing")
    r.run_time_exit(TODAY, CALM)
    left = [(p.inst, p.cluster) for p in r.state.open_positions]
    assert left == [("MNQ", SWING)], left
    assert "stp-swing" not in b.cancelled


def test_time_exit_closes_a_stale_calm_position_too(tmp_path):
    r = _runner(_Spy({}, ACCOUNT), tmp_path)
    _add(r, "MES", CALM, entry_day=YESTERDAY)
    assert r.run_time_exit(TODAY, CALM) == [("MES", CALM)]


def test_a_failed_close_leaves_the_position_marked_pending(tmp_path):
    r = _runner(_FailClose({}, ACCOUNT), tmp_path)
    p = _add(r, "MES", CALM)
    assert r.run_time_exit(TODAY, CALM) == []
    assert r.state.open_positions == [p] and p.exit_pending is True
    assert [x for x in _rows(tmp_path) if x.get("type") == "CLOSE"] == []


def test_maxhold_is_unchanged_without_an_override_and_uses_it_when_given(tmp_path):
    r = _runner(_Spy({}, ACCOUNT), tmp_path)
    _add(r, "MES", CALM, entry_day=YESTERDAY)       # held 3 calendar days
    _add(r, "MNQ", SWING, entry_day=YESTERDAY)      # held 3 calendar days
    assert r.run_maxhold_exit(TODAY, max_hold_days=5) == []             # default: both stay
    got = r.run_maxhold_exit(TODAY, max_hold_days=5, cluster_max_hold={CALM: 1})
    assert got == [("MES", CALM)], got                                  # override: Calm only
    assert [(p.inst, p.cluster) for p in r.state.open_positions] == [("MNQ", SWING)]


# ── cli ──────────────────────────────────────────────────────────────────────

def _book(tmp_path, clusters):
    p = tmp_path / "live_positions.track1.json"
    p.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                             "positions": [{"inst": "MES", "cluster": c, "sleeve": c}
                                           for c in clusters]}), encoding="utf-8")
    return p


def test_book_holds_cluster_has_three_outcomes(tmp_path):
    assert cli._book_holds_cluster(_book(tmp_path, [CALM, SWING]), CALM) is True
    assert cli._book_holds_cluster(_book(tmp_path, [SWING]), CALM) is False
    torn = tmp_path / "torn.json"
    torn.write_text('{"positions": [', encoding="utf-8")
    assert cli._book_holds_cluster(torn, CALM) is None, "unreadable must not read as empty"
    assert cli._book_holds_cluster(tmp_path / "absent.json", CALM) is None
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({"positions": "nope"}), encoding="utf-8")
    assert cli._book_holds_cluster(odd, CALM) is None


def test_cluster_max_hold_arguments_parse_or_refuse():
    assert cli._parse_cluster_max_hold(["roska4_calm=1", "x=3"]) == {"roska4_calm": 1, "x": 3}
    assert cli._parse_cluster_max_hold([]) == {}
    for bad in ("roska4_calm", "=1", "roska4_calm=one"):
        with pytest.raises(ValueError):
            cli._parse_cluster_max_hold([bad])


class _NeverConnect:
    constructed = 0

    def __init__(self, *a, **k):
        type(self).constructed += 1
        raise AssertionError("the time exit connected to the broker")


def _run_cli(monkeypatch, tmp_path, book, extra):
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)
    monkeypatch.setattr(cli, "IBKRBroker", _NeverConnect)
    _NeverConnect.constructed = 0
    argv = ["run_maxhold_exit", "--positions-path", str(book), "--lock-path", "",
            "--trade-log-path", str(tmp_path / "t.jsonl"), "--route", "track1_candidate",
            *extra]
    monkeypatch.setattr(sys, "argv", argv)
    return cli.main()


def test_the_time_exit_does_not_connect_when_the_book_has_no_calm_position(monkeypatch, tmp_path):
    book = _book(tmp_path, [SWING])
    rc = _run_cli(monkeypatch, tmp_path, book, ["--time-exit-cluster", CALM])
    assert rc == 0 and _NeverConnect.constructed == 0


def test_the_control_a_calm_position_does_make_it_connect(monkeypatch, tmp_path):
    """Without this the previous test passes on a CLI that never connects under any book."""
    book = _book(tmp_path, [CALM])
    with pytest.raises(AssertionError, match="connected to the broker"):
        _run_cli(monkeypatch, tmp_path, book, ["--time-exit-cluster", CALM])
    assert _NeverConnect.constructed == 1


def test_an_unreadable_book_is_a_loud_refusal_never_a_quiet_skip(monkeypatch, tmp_path):
    """A torn book must not read as "nothing to exit". The CLI's own book check refuses first
    (exit 1, so the scheduler raises an incident); `_book_holds_cluster` returning None is the
    second line of defence for a book that parses but has the wrong shape."""
    torn = tmp_path / "live_positions.track1.json"
    torn.write_text('{"positions": [', encoding="utf-8")
    rc = _run_cli(monkeypatch, tmp_path, torn, ["--time-exit-cluster", CALM])
    assert rc == 1, "a book that cannot be read must fail the job, not skip it"
    assert _NeverConnect.constructed == 0


# ── schedule ─────────────────────────────────────────────────────────────────

def test_the_time_exit_is_in_the_one_table_the_scheduler_and_the_dashboard_read():
    job = [j for j in t1.track1_safety_jobs() if j.kind == "time_exit"]
    assert len(job) == 1, job
    j = job[0]
    _xt = CA.CalmAParams().exit_time
    hh, mm = divmod(int(_xt[:2]) * 60 + int(_xt[3:]) - t1.CALM_TIME_EXIT_LEAD_MINUTES, 60)
    assert (j.hour, j.minute, j.day_of_week) == (hh, mm, "mon-fri")
    assert j.id == f"track1_time_exit_calm_{hh:02d}{mm:02d}"
    # It starts BEFORE the rule's 15:55 so its book rewrite finishes ahead of the 15:55 swing slot.
    assert (j.hour, j.minute) < (15, 55) and t1.CALM_TIME_EXIT_LEAD_MINUTES >= 1


def test_the_job_id_cannot_be_mistaken_for_a_calm_strategy_slot():
    from monitor.backend import job_journal_reader as jr

    job_id = t1.calm_time_exit_job().id.upper()
    assert not job_id.startswith(jr.TRACK1_STRATEGY_PREFIXES), (
        "a TRACK1_CALM_ prefix is typed as a strategy slot, so an exit failure would read "
        "'no signal'")
    assert jr._job_type(job_id) != jr.TRACK1_STRATEGY_SLOT


def test_maxhold_gives_the_clock_exit_cluster_a_one_day_limit():
    assert t1.TRACK1_CLUSTER_MAX_HOLD == {t1.CALM_TIME_EXIT_CLUSTER: 1}
    assert t1.CALM_TIME_EXIT_CLUSTER == CALM


# ── the call site: the REAL scheduler, argv captured, nothing executed ───────

def _fire(job_ids, **kw):
    import logging
    import os

    from global_index import run_scheduler as rs

    os.environ.setdefault("PYTEST_CURRENT_TEST", "calm_time_exit")
    seen = {}
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.setdefault(label, {"args": list(args), "route": route}) and True)
        sched = rs.make_scheduler(port=4002, dry_run=True, **kw)
        jobs = {j.id: j for j in sched.get_jobs()}
        for jid in job_ids:
            assert jid in jobs, f"{jid} is not registered; registered: {sorted(jobs)[:8]}..."
            jobs[jid].func()
        return seen, jobs
    finally:
        rs._run = orig
        rs._maxhold_done.clear()
        rs._maxhold_done_t1.clear()
        logging.disable(lvl)


def _flag(args, name):
    return args[args.index(name) + 1] if name in args else None


def test_the_scheduler_registers_the_time_exit_and_fires_it_against_track1s_book():
    jid = t1.calm_time_exit_job().id
    seen, jobs = _fire([jid], track1_only=True)
    assert list(seen) == [jid.upper()], seen.keys()
    a = seen[jid.upper()]["args"]
    assert "global_index.run_maxhold_exit" in a
    assert _flag(a, "--time-exit-cluster") == CALM
    assert _flag(a, "--positions-path") == t1.TRACK1_POSITIONS_PATH
    assert _flag(a, "--lock-path") == t1.TRACK1_LOCK_PATH
    assert _flag(a, "--stop-path") == t1.TRACK1_STOP_PATH
    assert _flag(a, "--client-id") == str(t1.TRACK1_SAFETY_CLIENT_ID), (
        "the stops this cancels were placed by client 90; IBKR only cancels from the placer")
    assert _flag(a, "--trade-log-path") == t1.TRACK1_TRADE_LOG_PATH
    assert _flag(a, "--route") == t1.EVENT_ROUTE_VALUE
    assert seen[jid.upper()]["route"] == t1.EVENT_ROUTE_VALUE
    assert "live_positions.json" not in a, "it must never touch the legacy book"

    trig = {f.name: str(f) for f in jobs[jid].trigger.fields}
    job = t1.calm_time_exit_job()
    assert (trig["hour"], trig["minute"], trig["day_of_week"]) == (
        str(job.hour), str(job.minute), "mon-fri"), trig


def test_the_time_exit_job_exists_only_in_track1_only_mode():
    import logging
    import os

    from global_index import run_scheduler as rs

    os.environ.setdefault("PYTEST_CURRENT_TEST", "calm_time_exit")
    jid = t1.calm_time_exit_job().id
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        for kw, want in (({}, False), ({"track1_shadow": True}, False), ({"track1_only": True}, True)):
            ids = {j.id for j in rs.make_scheduler(port=4002, dry_run=True, **kw).get_jobs()}
            assert (jid in ids) is want, (kw, want)
    finally:
        logging.disable(lvl)


def test_the_track1_maxhold_job_gives_calm_a_one_day_limit_and_legacy_gets_nothing():
    seen, _ = _fire(["track1_maxhold_exit"], track1_only=True)
    t1_args = seen["TRACK1_MAX_HOLD_EXIT"]["args"]
    assert _flag(t1_args, "--cluster-max-hold") == f"{CALM}=1", t1_args
    # Legacy's job is retired in track1-only mode, so it is read from the mode that keeps it.
    seen, _ = _fire(["maxhold_exit"], track1_shadow=True)
    legacy = seen["MAX_HOLD_EXIT"]["args"]
    assert "--cluster-max-hold" not in legacy and "--time-exit-cluster" not in legacy, legacy
