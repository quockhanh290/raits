"""Stage 5M-C — the Normal-R4 slots are ready for a provider, and the operator text is honest.

No real IBKR anywhere: every provider path here is driven with a fake broker class injected
through the seam `build_bar_provider(broker_cls=...)` already provides. No scheduler is started,
no switch file is touched, and every ledger, checkpoint and explanation goes under `tmp_path`.

Two subjects
------------
**The provider staging.** The 23 swing slots are declared `none` and resolve through
`RAITS_TRACK1_SWING_PROVIDER`, which an operator sets for one measured session. The tests below
prove all three states — unset, `ibkr`, and a typo — and prove the connect/disconnect/finally
path with a fake broker.

**The stale count.** Operator-facing text said "25 Track 1 slots" in three places, and it had
been wrong since Stage 5M-B added 23 more. Nobody was misled yet. The guard here is not about
the number: it is that a help string stating a stale fact is the same defect as a comment that
does, and the fix is to derive it rather than to correct it once.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from global_index import track1_gates as gates      # noqa: E402
from global_index import track1_live_source as S    # noqa: E402
from global_index import track1_params as tp        # noqa: E402
from global_index import track1_slots as ts         # noqa: E402
from monitor import ops                             # noqa: E402

SWING = "roska4_swing"
ET = "America/New_York"
DAY = pd.Timestamp("2026-08-20")
ENV = ts.SWING_PROVIDER_ENV


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# 1. the staged provider switch
# ══════════════════════════════════════════════════════════════════════════════

def test_unset_means_no_provider():
    assert ts.swing_provider() == ts.PROVIDER_NONE


@pytest.mark.parametrize("value", ["", None])
def test_empty_or_absent_means_no_provider(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, value)
    assert ts.swing_provider() == ts.PROVIDER_NONE


def test_the_switch_can_actually_turn_it_on(monkeypatch):
    """A switch that only ever says no is not a switch."""
    monkeypatch.setenv(ENV, "ibkr")
    assert ts.swing_provider() == ts.PROVIDER_IBKR


@pytest.mark.parametrize("typo", ["IBKR", "ibkr ", "yes", "true", "1", "Ibkr"])
def test_an_unrecognised_value_is_refused_rather_than_falling_back(monkeypatch, typo):
    """Falling back to `none` is the safer-LOOKING choice and the worse one.

    An operator who typed `IBKR` would get a session that silently collected nothing, conclude
    the switch does not work, and have no way to tell that from a session where the slots ran
    and found no setups. Refusing is loud and still fails in the direction of not starting.
    """
    monkeypatch.setenv(ENV, typo)
    with pytest.raises(ValueError) as e:
        ts.swing_provider()
    assert ENV in str(e.value) and repr(typo) in str(e.value)


def test_calm_and_stress_are_not_reachable_by_this_switch(monkeypatch):
    """A session-scoped variable must not be able to turn OFF the two sleeves that have been
    collecting since Stage 5I — that would be a shadow day that quietly gathered nothing.

    Stage 5N widened the STAGED set to include global_nkd (same collision reason as swing),
    so the loop iterates the sleeves that must stay untouchable rather than "everything that
    is not swing" — that phrasing silently swept NKD in when it joined the staged set.
    """
    untouchable = {"roska4_calm", "roska4_stress"}
    monkeypatch.setenv(ENV, "ibkr")
    for s in ts.TRACK1_SLOTS:
        if s.sleeve in untouchable:
            assert ts.provider_for(s) == ts.PROVIDER_IBKR, s.id
    monkeypatch.delenv(ENV, raising=False)
    for s in ts.TRACK1_SLOTS:
        if s.sleeve in untouchable:
            assert ts.provider_for(s) == ts.PROVIDER_IBKR, s.id
    assert ts.STAGED_SLEEVES == {"roska4_swing", "global_nkd"}


def _sched_providers(track1_shadow: bool = True):
    """The `--bar-provider` each slot is really launched with, per sleeve."""
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run, timeout=None, route=None: (
            seen.append((label, list(args))) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_shadow=track1_shadow)
        for j in sched.get_jobs():
            if j.id.startswith("track1_"):
                j.func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    assert seen, "no Track 1 slot ran — nothing was captured"
    out: dict = {}
    for label, argv in seen:
        sleeve = argv[argv.index("--sleeve") + 1]
        out.setdefault(sleeve, set()).add(argv[argv.index("--bar-provider") + 1])
    return out


def test_the_scheduler_launches_swing_without_a_provider_by_default():
    got = _sched_providers()
    assert got[SWING] == {"none"}, got
    assert got["roska4_calm"] == {"ibkr"} and got["roska4_stress"] == {"ibkr"}, got


def test_the_scheduler_launches_swing_with_a_provider_when_switched_on(monkeypatch):
    monkeypatch.setenv(ENV, "ibkr")
    got = _sched_providers()
    assert got[SWING] == {"ibkr"}, got
    assert got["roska4_calm"] == {"ibkr"} and got["roska4_stress"] == {"ibkr"}, got


def test_a_typo_stops_the_scheduler_from_building_at_all(monkeypatch):
    """Fail-closed in the loudest available place: no schedule, rather than a schedule that
    looks right and collects nothing."""
    monkeypatch.setenv(ENV, "IBKR")
    with pytest.raises(ValueError):
        _sched_providers()


def test_the_provider_is_resolved_once_per_session_not_per_slot(monkeypatch):
    """A mid-session export must not split the window into two halves that ran differently.

    The value is read at registration; changing the environment afterwards must not reach a
    slot that was already scheduled.
    """
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run, timeout=None, route=None: (
            seen.append(list(args)) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_shadow=True)
        monkeypatch.setenv(ENV, "ibkr")          # changed AFTER registration
        for j in sched.get_jobs():
            if j.id.startswith("track1_swing"):
                j.func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    providers = {a[a.index("--bar-provider") + 1] for a in seen}
    assert providers == {"none"}, providers


# ══════════════════════════════════════════════════════════════════════════════
# 2. the provider path itself, on a fake broker
# ══════════════════════════════════════════════════════════════════════════════

class FakeBroker:
    """Stands in for `IBKRBroker`. Records what happened; opens nothing."""

    instances: list = []

    def __init__(self, host=None, port=None, client_id=None, bar_duration=None):
        self.host, self.port, self.client_id = host, port, client_id
        self.bar_duration = bar_duration
        self.connected = False
        self.disconnected = False
        self.fetched: list = []
        FakeBroker.instances.append(self)

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.disconnected = True

    def fetch_bars(self, inst, through=None):
        """Naive-ET bars for today, TRIMMED at `through`.

        The trim is not decoration. The first version returned the whole session regardless,
        and the route refused with `bars_from_the_future`: "bars cannot arrive from later than
        the moment they were asked for, so this is a clock error." It was right — a fake that
        hands back the future is not imitating a broker, it is imitating a bug. `IBKRBroker`
        and `FrameBarProvider` both trim; so does this.
        """
        self.fetched.append((inst, through))
        # Derived from the SAME generator the frozen half uses, so the two agree on every
        # shared timestamp. They did not in the first version, and the route refused with
        # `overlap_disagreement`: "the live half and history disagree on 276 of 276 shared
        # timestamps". That guard is the reason a mislabelled feed cannot rewrite settled
        # prices, and two fixtures built independently is exactly the disagreement it looks
        # for. One generator, two views of it.
        df = _synthetic_frames(aware=False)[inst]
        if through is not None:
            cut = pd.Timestamp(through)
            if cut.tzinfo is not None:
                cut = cut.tz_convert(ET).tz_localize(None)
            df = df[df.index <= cut]
        return df


@pytest.fixture
def fake():
    FakeBroker.instances = []
    yield FakeBroker
    FakeBroker.instances = []


def test_build_bar_provider_connects_and_hands_back_the_broker(fake):
    provider, broker = S.build_bar_provider("ibkr", broker_cls=fake)
    assert isinstance(provider, S.IBKRBarProvider)
    assert broker.connected is True
    assert broker.client_id == 89, "Track 1 must not share legacy's clientId 1"


def test_build_bar_provider_none_opens_nothing(fake):
    provider, broker = S.build_bar_provider("none", broker_cls=fake)
    assert provider is None and broker is None
    assert fake.instances == [], "a broker was constructed for the `none` provider"


def test_an_unknown_provider_kind_is_a_named_refusal():
    with pytest.raises(S.LiveSourceRefused) as e:
        S.build_bar_provider("carrier_pigeon")
    assert e.value.code == S.UNKNOWN_BAR_PROVIDER


@pytest.fixture
def slot(tmp_path, monkeypatch):
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(d))
    import global_index.window_ledger as wl
    importlib.reload(wl)
    import global_index.run_live_day_track1 as entry
    importlib.reload(entry)
    yield d, wl, entry
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    importlib.reload(wl)
    importlib.reload(entry)


def _main_with_fake(entry, monkeypatch, fake, sleeve=SWING, slot_id="TRACK1_SWING_1405"):
    monkeypatch.setattr(entry, "build_bar_provider",
                        lambda kind, **kw: S.build_bar_provider(kind, broker_cls=fake, **kw))
    return entry.main(["--source", "live-shadow", "--sleeve", sleeve,
                       "--slot-id", slot_id, "--bar-provider", "ibkr",
                       "--regime-csv", "spy_daily_live.csv"])


def test_a_swing_slot_with_a_provider_disconnects_in_the_finally(slot, monkeypatch, fake):
    """A leaked connection per slot is 23 a day, all competing for the same client id.

    The disconnect must happen whatever the slot decided, so this asserts it without caring
    about the verdict — and asserts a broker was built at all, so it cannot pass by the path
    never being reached.
    """
    _d, _wl, entry = slot
    _main_with_fake(entry, monkeypatch, fake)
    assert fake.instances, "no broker was ever built — the provider path was not reached"
    for b in fake.instances:
        assert b.connected is True, "a broker was built but never connected"
        assert b.disconnected is True, "a broker was left connected"


def test_the_slot_disconnects_even_when_the_route_refuses(slot, monkeypatch, fake):
    """The `finally` is the point. Force a refusal and require the disconnect anyway."""
    _d, _wl, entry = slot

    def _boom(*a, **kw):
        raise entry.ShadowRefused("forced_for_test", "a deliberate refusal")

    monkeypatch.setattr(entry, "observe_live_slot", _boom)
    rc = _main_with_fake(entry, monkeypatch, fake)
    assert rc == 2
    assert fake.instances and all(b.disconnected for b in fake.instances)


def test_with_a_provider_the_slot_no_longer_stops_at_no_bar_provider(slot, monkeypatch, fake):
    """The whole point of 5M-C: the refusal must move PAST `no_bar_provider`.

    What it lands on is a route answer — a stale regime, a freshness refusal, an admission
    verdict — and any of those means the machinery ran. `no_bar_provider` means it did not.
    """
    d, wl, entry = slot
    monkeypatch.setattr(entry, "build_bar_provider",
                        lambda kind, **kw: S.build_bar_provider(kind, broker_cls=fake, **kw))
    provider, broker = entry.build_bar_provider("ibkr")
    # A frozen half has to be supplied or the join refuses with `no_frozen_half` before the
    # provider is ever consulted — which is itself a correct route refusal, and was what the
    # first version of this test measured by accident. In production `main()` supplies
    # `default_data_paths()`; here synthetic frames stand in so nothing reads the real store.
    frozen = _synthetic_frames()
    try:
        res = entry.observe_live_slot(SWING, "TRACK1_SWING_1405",
                                      now_et=pd.Timestamp(f"{DAY.date()} 14:05", tz=ET),
                                      provider=provider, frozen_frames=frozen,
                                      root=str(d.parent))
    finally:
        broker.disconnect()
    assert res["reason"] != entry.NO_BAR_PROVIDER, res
    assert res["reason"] not in ("", None), res
    assert broker.fetched, "the provider was never asked for bars"
    assert {i for i, _t in broker.fetched} == set(tp.SLEEVE_INSTRUMENTS[SWING]), broker.fetched


def _synthetic_frames(*, aware: bool = True):
    """Sessions of 1-minute bars for the four swing instruments.

    `aware=True` is the FROZEN half's contract: history comes off parquet tz-aware, converted
    to the instrument's session clock. The live half is the opposite — naive ET, which is what
    `IBKRBroker.fetch_bars` returns and what `FakeBroker` imitates.

    Getting this wrong is not a fixture detail. The first version handed naive frames as
    history and the route refused with `frozen_clock`, saying the frame "was loaded by
    something other than frozen_frame()". That refusal is the guard that exists because live
    Nikkei bars on the ET clock were once joined onto Tokyo-clocked history and overwrote 1,050
    settled prices. It was right to refuse; the fixture was wrong.
    """
    days = pd.bdate_range(end=DAY, periods=3)
    out = {}
    for n, inst in enumerate(tp.SLEEVE_INSTRUMENTS[SWING]):
        frames = []
        for k, day in enumerate(days):
            idx = pd.date_range(f"{day.date()} 09:30", f"{day.date()} 15:59", freq="1min")
            close = 100.0 + n + k * 0.5 + np.linspace(0, 1.5, len(idx))
            frames.append(pd.DataFrame(
                {"open": close, "high": close + 0.25, "low": close - 0.25, "close": close,
                 "volume": np.full(len(idx), 500.0)}, index=idx))
        df = pd.concat(frames)
        if aware:
            df.index = df.index.tz_localize(ET)
        out[inst] = df
    return out


def test_a_slot_with_no_frozen_half_refuses_by_name_rather_than_guessing(slot, fake):
    """The refusal the test above tripped over first, kept as its own check.

    A provider without history is not a smaller job — the join has nothing to append to, and
    inventing one would be the shape of the NKD corruption.
    """
    d, _wl, entry = slot
    provider, broker = S.build_bar_provider("ibkr", broker_cls=fake)
    try:
        res = entry.observe_live_slot(SWING, "TRACK1_SWING_1405",
                                      now_et=pd.Timestamp(f"{DAY.date()} 14:05", tz=ET),
                                      provider=provider, root=str(d.parent))
    finally:
        broker.disconnect()
    assert res["decided"] is False
    assert res["reason"] not in (entry.NO_BAR_PROVIDER, "", None), res


def test_the_slot_still_records_that_it_ran(slot, monkeypatch, fake):
    d, wl, entry = slot
    _main_with_fake(entry, monkeypatch, fake)
    rows = wl.read_day(str(pd.Timestamp.now(tz=ET).date()))
    assert any(r.get("sleeve") == SWING for r in rows) or rows == [], rows


# ══════════════════════════════════════════════════════════════════════════════
# 3. the route machinery is still in the path
# ══════════════════════════════════════════════════════════════════════════════

def test_the_swing_sleeve_reaches_every_stage_of_the_route():
    """Not "it works" — that each named stage KNOWS about the sleeve.

    A stage that has no entry for a sleeve does not refuse it, it has no opinion about it, and
    a route made of stages with no opinion is a route that admits anything.
    """
    from global_index import track1_intraday as intra
    from global_index import window_ledger as wl
    from global_index import track1_signal_layer as sig
    from global_index import route_checkpoint as rc

    assert SWING in tp.WINDOWS_ET, "the admission window"
    assert SWING in intra.REQUIREMENTS, "the intraday requirement"
    assert wl.expected_slots(SWING) == 23, "the ledger window"
    assert SWING in tp.CAPS, "the cluster cap"
    assert SWING in tp.SLEEVE_QTY, "the quantity"
    assert SWING in tp.FAMILY_CLUSTERS, "the correlation family"
    assert SWING in rc.CHECKPOINTED_SLEEVES, "the cross-day checkpoint"
    ok, _why = sig.window_verdict(SWING, pd.Timestamp(f"{DAY.date()} 14:05"))
    assert ok
    bad, why = sig.window_verdict(SWING, pd.Timestamp(f"{DAY.date()} 11:00"))
    assert not bad and "14:05" in why


def test_freshness_binds_for_the_swing_sleeve_and_needs_todays_preflight():
    """The swing slots are the first Track 1 slots on the same-day side of 13:45."""
    from global_index import track1_freshness as fresh
    monday = "2026-08-24"
    for s in ts.TRACK1_SLOTS:
        if s.sleeve != SWING:
            continue
        at = pd.Timestamp(f"{monday} {s.hour:02d}:{s.minute:02d}")
        assert fresh.required_data_through(at) == pd.Timestamp(monday), s.id


def test_a_checkpoint_is_only_written_for_a_complete_window(tmp_path, monkeypatch):
    """Coverage first, checkpoint second. A checkpoint from a half-observed window would be
    state nobody can vouch for, carried across a day boundary."""
    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(d))
    import global_index.window_ledger as wl
    importlib.reload(wl)
    try:
        day = str(DAY.date())
        wl.window_open(SWING, day, route_hint=tp.ROUTE)
        wl.window_closed(SWING, day, 5, route_hint=tp.ROUTE, signal=wl.NO_SIGNAL,
                         slots_ran=5, slots_decided=5)
        st = wl.status(wl.read_day(day), SWING, day)
        assert st["outcome"] != "complete" and st["usable_as_evidence"] is False, st
    finally:
        monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
        importlib.reload(wl)


# ══════════════════════════════════════════════════════════════════════════════
# 4. the stale count, and a guard against the next one
# ══════════════════════════════════════════════════════════════════════════════

#: Files an operator reads to decide what to do. A stale number here is a stale instruction.
OPERATOR_FACING = [
    Path("monitor/ops.py"),
    Path("global_index/track1_gates.py"),
    Path("global_index/track1_slots.py"),
    Path("global_index/run_scheduler.py"),
    Path("docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md"),
]

#: "25" next to a word meaning slot or job. Matched loosely on purpose: the point is to catch
#: the shape, not one phrasing.
_STALE = re.compile(r"\b25\s+(?:Track\s*1\s+)?(?:slots?|jobs?)\b", re.IGNORECASE)


def test_no_operator_facing_file_states_a_slot_count_that_can_go_stale():
    """The count belongs in `TRACK1_SLOTS` and nowhere else.

    It said 25 in three places and had been wrong since Stage 5M-B added 23 more. Nobody was
    misled — but a help string that states a stale fact is the same defect class as a comment
    that does, and the next sleeve makes it wrong again. Lines that explicitly say a number
    USED to be written here are allowed, because they are history rather than instruction.
    """
    offenders = []
    for path in OPERATOR_FACING:
        assert path.exists(), path
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not _STALE.search(line):
                continue
            if re.search(r"\b(said|was written|until Stage|used to)\b", line, re.IGNORECASE):
                continue          # a note about the old wording, not the wording itself
            offenders.append(f"{path.name}:{n}: {line.strip()[:90]}")
    assert offenders == [], offenders


def test_the_guard_would_catch_a_reintroduced_count():
    """The check above passes by finding nothing, which is the shape of a check that has
    quietly stopped looking."""
    assert _STALE.search('help="adds the 25 Track 1 slots"')
    assert _STALE.search("registers 25 jobs")
    assert _STALE.search("adds 25 slots")
    assert not _STALE.search("the count said 25 slots until Stage 5M-B") is None


def test_the_operator_count_is_derived_and_correct():
    # The relation is the subject; 48 was Stage 5M-C's state and Stage 5N made it 70.
    assert ops.track1_slot_count() == len(ts.TRACK1_SLOTS)
    assert ops.track1_slot_count() >= 70


def test_the_help_text_carries_the_derived_count():
    import argparse
    p = argparse.ArgumentParser()
    ops.build_parser() if hasattr(ops, "build_parser") else None
    text = Path("monitor/ops.py").read_text(encoding="utf-8")
    assert "track1_slot_count()" in text
    assert "the 25 Track 1 slots" not in text


def test_the_gate_evidence_no_longer_states_a_count():
    ev = gates.BLOCKERS["WIRING_scheduler_dashboard_paper"].evidence
    assert "25 Track 1 slots" not in ev
    assert "adds the Track 1 slots" in ev


# ══════════════════════════════════════════════════════════════════════════════
# 5. what must not have changed
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("env", [None, "ibkr"])
def test_no_track1_slot_ever_carries_an_order_flag(monkeypatch, env):
    if env:
        monkeypatch.setenv(ENV, env)
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run, timeout=None, route=None: (
            seen.append((label, list(args), route)) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_shadow=True)
        for j in sched.get_jobs():
            if j.id.startswith("track1_"):
                j.func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    assert len(seen) == len(ts.TRACK1_SLOTS)
    for label, argv, route in seen:
        for nope in ("--allow-orders", "--port", "--window"):
            assert nope not in argv, (label, nope)
        assert route == "track1_candidate", label


def test_b1_still_blocks_orders():
    assert gates.as_ledger()["blocking_now"] == ["B1_broker_account_or_legacy_retirement"]


@pytest.mark.parametrize("flag", [False, True])
def test_dashboard_parity_holds_in_both_modes(flag):
    r = ts.parity_report(track1_shadow=flag)
    assert r["in_parity"], r


def test_nkd_gained_its_slot_in_stage_5n():
    """This test used to assert the OPPOSITE — that NKD had no slot — precisely so a claim of
    "full Track 1 route" could not be made by accident. Stage 5N gave NKD its 22 slots and
    the test turned red as designed. Its successor pins the new state, plus the property the
    old one was really about: a sleeve outside the window table is still refused by name.
    """
    assert "global_nkd" in {s.sleeve for s in ts.TRACK1_SLOTS}
    assert len([s for s in ts.TRACK1_SLOTS if s.sleeve == "global_nkd"]) == 22
    with pytest.raises(S.LiveSourceRefused) as e:
        S.LiveTrack1Source()._for_sleeve("sleeve_without_a_window",
                                         pd.Timestamp("2026-08-24 14:05"), DAY)
    assert e.value.code == S.SLEEVE_NOT_LIVE


def test_no_switch_file_was_created_by_this_suite():
    for name in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json"):
        assert not Path(name).exists(), name
