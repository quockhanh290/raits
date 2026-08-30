"""scratch/test_track1_stage5e_live_source_20260823.py — the Stage 5E gate.

    python -m pytest scratch/test_track1_stage5e_live_source_20260823.py -q

Offline. No scheduler, no IBKR, no order, no dashboard write. The ledger and the checkpoint are
written into pytest's temporary directory; the repo's own route state is asserted absent.

What this suite proves, and what it must not be read as proving
----------------------------------------------------------------
Stage 5D left precondition 2b open: `load_source("live").candidates()` raised, so every real
slot recorded `live_source_not_ready`. Stage 5E built the source for the ONE sleeve that can be
answered in-package — Calm A at 10:00 — with a causal regime label, an explicit cost object and
risk taken from the actual disaster-stop distance.

It does NOT prove:
  * that a broker provider works. Every test here injects `FrameBarProvider`. No IBKR object is
    constructed, let alone connected.
  * that the Stress window can decide. Its rule is in scratch, the source refuses by name, and
    a test below pins that refusal so it cannot quietly become a fake pass.
  * that Normal-R4 or NKD are live. They have no Track 1 slot at all.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import track1_calm_a as CA  # noqa: E402
from global_index import track1_gates as g  # noqa: E402
from global_index import track1_live_source as S  # noqa: E402
from global_index import track1_params as tp  # noqa: E402
from global_index import track1_sleeves as SL  # noqa: E402

ET = "America/New_York"
DAY = pd.Timestamp("2026-08-24")
SESSIONS = pd.bdate_range("2026-07-01", "2026-08-21")


#: When this module was imported, i.e. before any test in it ran. Stage 5ZK. The live route
#: writes `replay_checkpoint.track1.json` and `live_positions.track1.json` in one call every
#: day a window completes — first observed 2026-08-25 15:56:19 ET — so asserting their ABSENCE
#: forbids the running system from doing what these very tests exercise. An mtime older than
#: this process says the thing actually being guarded: no test in this run touched it.
_IMPORTED_AT = __import__("time").time()


def _assert_not_written_by_this_run(name: str) -> None:
    p = Path(name)
    if not p.exists():
        return
    assert p.stat().st_mtime < _IMPORTED_AT, (
        f"{name} was written DURING this test run — every fixture must be under tmp_path")

def _session(dt, o, h, l, c):
    """One synthetic RTH session, 09:30 through 16:05 so both session-end conventions are met.

    `track1_intraday` requires the prior session through 16:00 and Calm A's own RTH ends at
    15:59. Real frames carry both bars; a fixture that stopped at 15:59 made the gate refuse
    every slot with `partial_coverage` — which is how that difference was found.
    """
    idx = pd.date_range(pd.Timestamp(dt) + pd.Timedelta(hours=9, minutes=30),
                        pd.Timestamp(dt) + pd.Timedelta(hours=16, minutes=5),
                        freq="1min", tz=ET)
    close = np.linspace(o, c, len(idx))
    return pd.DataFrame({"open": close, "high": np.maximum(close, h),
                         "low": np.minimum(close, l), "close": close, "volume": 1000.0},
                        index=idx)


def frames(*, setup: bool = True):
    """(frozen, live). `setup=False` makes the prior session close in the TOP third, so the
    rule runs and legitimately finds nothing — which must not look like a failure."""
    frozen, live = {}, {}
    for inst in ("MES", "MNQ"):
        parts = [_session(d, 100.0, 101.0, 99.0, 100.0) for d in SESSIONS[:-1]]
        parts.append(_session(SESSIONS[-1], 100.0, 101.0, 97.0,
                              97.2 if setup else 100.9))
        frozen[inst] = pd.concat(parts)
        today = _session(DAY, 97.0, 98.0, 96.5, 97.5)
        today = today.loc[:pd.Timestamp(f"{DAY.date()} 10:00", tz=ET)]
        today.index = pd.DatetimeIndex(today.index).tz_convert(ET).tz_localize(None)
        live[inst] = today
    return frozen, live


def labels(value: str = "Calm", *, today: str | None = None):
    out = {pd.Timestamp(d).normalize(): value for d in SESSIONS}
    if today is not None:
        out[DAY.normalize()] = today
    return out


def source(**kw):
    frozen, live = kw.pop("frames", None) or frames()
    return S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), labels=kw.pop("labels", labels()),
                              frozen_frames=frozen, **kw)


NOW = pd.Timestamp(f"{DAY.date()} 10:00", tz=ET)


# ══════════════════════════════════════════════════════════════════════════════
# 1. the source returns instead of raising
# ══════════════════════════════════════════════════════════════════════════════
def test_the_live_shadow_source_returns_candidates():
    """Precondition 2b for the Calm window. Stage 5D's slot recorded live_source_not_ready
    here; this is the line that changed."""
    cands = source().candidates(NOW)
    assert len(cands) == 2, [c.instrument for c in cands]
    for c in cands:
        assert c.sleeve == "roska4_calm" and c.direction == "LONG" and c.qty == 1
        assert c.entry_price and c.stop_price and c.stop_price < c.entry_price
        assert c.risk_dollars > 0
        assert c.exit_time is None, "a 10:00 slot must not carry a 15:55 exit"
        assert c.meta["risk_basis"] == "true_stop_distance"


def test_a_day_that_does_not_set_up_returns_an_empty_list_not_a_refusal():
    """The distinction the whole refusal vocabulary exists for: the rule RAN and found
    nothing, which is a real observation, versus the rule could not run."""
    cands = source(frames=frames(setup=False)).candidates(NOW)
    assert cands == []


def test_load_source_exposes_it_by_name():
    src = SL.load_source("live-shadow")
    assert isinstance(src, S.LiveTrack1Source)
    with pytest.raises(S.LiveSourceRefused) as e:
        src.candidates(NOW)
    assert e.value.code == "no_bar_provider", "a source with no provider must refuse by name"


def test_the_old_live_source_still_refuses_and_says_what_is_missing():
    """`live` is the not-implemented candidate source and stays that way; `live-shadow` is the
    new one. Collapsing them would hide which sleeves are actually answerable."""
    with pytest.raises(NotImplementedError):
        SL.load_source("live").candidates("today")


# ══════════════════════════════════════════════════════════════════════════════
# 2. which sleeves can be asked at all
# ══════════════════════════════════════════════════════════════════════════════
def test_only_two_sleeves_have_a_track1_slot():
    """Superseded and re-pointed by Stage 5M-B, which gave Normal-R4 its 23 slots.

    The property was never "two sleeves" — it was that the four tables which describe a slot
    agree about which sleeves have one. Pinning the number turned this red for a change that
    was intended, so it now derives the set and checks the tables against each other. NKD is
    still slotless, and that is asserted rather than assumed."""
    from global_index import track1_intraday as intra
    from global_index import track1_slots as t1
    from global_index import window_ledger as wl

    slotted = {s.sleeve for s in t1.TRACK1_SLOTS}
    # Stage 5N: all four sleeves are slotted; the cross-table agreement is now the whole test.
    assert slotted == {"roska4_calm", "roska4_stress", "roska4_swing", "global_nkd"}
    assert set(intra.REQUIREMENTS) == slotted
    assert set(wl.WINDOWS) == slotted
    assert set(tp.SLEEVE_INSTRUMENTS) - slotted == set()


# roska4_swing gained a slot in 5M-B, global_nkd in 5N; only a name outside the window
# table stays a valid example now.
@pytest.mark.parametrize("sleeve", ["sleeve_without_a_window"])
def test_asking_for_an_unslotted_sleeve_is_a_named_refusal(sleeve):
    with pytest.raises(S.LiveSourceRefused) as e:
        source()._for_sleeve(sleeve, NOW, DAY)
    assert e.value.code == S.SLEEVE_NOT_LIVE


def test_the_stress_window_is_answerable_since_stage_5f():
    """Superseded and re-pointed. When this was written the Stress rule lived only in
    scratch and the source refused by name on 24 of the 25 slots. Stage 5F promoted it into
    global_index/track1_stress_mnq.py, so the refusal is gone — asserting it would have
    pinned the gap in place. What it checks now is that the window ANSWERS: either a
    candidate list or an empty list, never stress_rule_not_in_package."""
    frozen, live = frames()
    src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), labels=labels(),
                             frozen_frames=frozen)
    try:
        out = src.candidates(pd.Timestamp(f"{DAY.date()} 11:00", tz=ET))
        assert isinstance(out, list)
    except S.LiveSourceRefused as e:
        assert e.code != S.STRESS_RULE_NOT_IN_PACKAGE, "Stress still refuses as not-in-package"


def test_an_instant_in_no_window_is_a_refusal_not_an_empty_list():
    with pytest.raises(S.LiveSourceRefused) as e:
        source().candidates(pd.Timestamp(f"{DAY.date()} 14:00", tz=ET))
    assert e.value.code == S.NO_SLEEVE_AT_THIS_INSTANT


# ══════════════════════════════════════════════════════════════════════════════
# 3. the regime label is causal
# ══════════════════════════════════════════════════════════════════════════════
def test_todays_own_label_cannot_change_todays_slot():
    """The lookahead test. A morning slot reading today's label would be reading a row
    computed from today's close — and it would look perfectly normal."""
    base = source(labels=labels("Calm")).candidates(NOW)
    assert len(base) == 2

    mutated = source(labels=labels("Calm", today="Crisis")).candidates(NOW)
    assert len(mutated) == 2, "today's own label moved the decision — that is lookahead"
    assert [c.trade_id for c in base] == [c.trade_id for c in mutated]


def test_the_previous_sessions_label_does_change_todays_slot():
    """The other half. If nothing moves the answer the first test proves nothing."""
    lab = labels("Calm")
    lab[pd.Timestamp(SESSIONS[-1]).normalize()] = "Stress"
    assert source(labels=lab).candidates(NOW) == []


def test_causal_lookup_takes_the_last_row_strictly_before_the_day():
    lab = {pd.Timestamp("2026-08-20"): "Calm",
           pd.Timestamp("2026-08-21"): "Normal",
           pd.Timestamp("2026-08-24"): "Crisis"}
    assert S.causal_regime_label(lab, "2026-08-24") == "Normal"
    assert S.causal_regime_label(lab, "2026-08-21") == "Calm"
    assert S.causal_regime_label(lab, "2026-08-20") is None
    assert S.causal_regime_label({}, "2026-08-24") is None


def test_no_label_before_today_is_a_named_refusal():
    only_today = {DAY.normalize(): "Calm"}
    with pytest.raises(S.LiveSourceRefused) as e:
        source(labels=only_today).candidates(NOW)
    assert e.value.code == S.REGIME_UNAVAILABLE
    assert "lookahead" in e.value.detail


# ══════════════════════════════════════════════════════════════════════════════
# 4. costs
# ══════════════════════════════════════════════════════════════════════════════
def test_every_track1_instrument_has_a_cost_object():
    costs = S.default_costs()
    need = {i for v in tp.SLEEVE_INSTRUMENTS.values() for i in v}
    assert need <= set(costs), need - set(costs)
    for inst in sorted(need):
        c = costs[inst]
        assert c.point_value > 0 and c.tick > 0, inst


def test_the_cost_slippage_matches_what_the_measured_rows_were_built_under():
    c = S.default_costs()["MES"]
    assert float(c.slippage_ticks_per_side) == 2.0


def test_a_missing_cost_is_a_named_refusal():
    thin = {k: v for k, v in S.default_costs().items() if k != "MNQ"}
    with pytest.raises(S.LiveSourceRefused) as e:
        source(costs=thin).candidates(NOW)
    assert e.value.code == S.COST_MISSING and "MNQ" in e.value.detail


def test_risk_scales_with_the_instruments_point_value():
    cands = {c.instrument: c for c in source().candidates(NOW)}
    costs = S.default_costs()
    ratio = costs["MES"].point_value / costs["MNQ"].point_value
    assert abs(cands["MES"].risk_dollars / cands["MNQ"].risk_dollars - ratio) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# 5. risk comes from the actual stop distance
# ══════════════════════════════════════════════════════════════════════════════
def test_risk_is_the_stop_distance_times_point_value_times_qty():
    costs = S.default_costs()
    for c in source().candidates(NOW):
        pv = float(costs[c.instrument].point_value)
        expected = abs(c.entry_price - c.stop_price) * pv * c.qty
        assert abs(c.risk_dollars - expected) < 1e-9, (c.instrument, c.risk_dollars, expected)


def test_moving_the_stop_moves_the_risk():
    """The property an ATR-multiple formula cannot have. `mult x atr x pv` is blind to where
    the stop actually sits; `abs(entry - stop) x pv` is not."""
    a = CA.stop_risk_dollars(5000.0, 4970.0, 5.0, 1)
    b = CA.stop_risk_dollars(5000.0, 4900.0, 5.0, 1)
    assert a == 150.0 and b == 500.0 and b > a

    wide = source(calm_params=CA.CalmAParams(disaster_stop_atr_mult=3.0)).candidates(NOW)
    narrow = source(calm_params=CA.CalmAParams(disaster_stop_atr_mult=1.5)).candidates(NOW)
    for w, n in zip(wide, narrow):
        assert w.stop_price < n.stop_price
        assert w.risk_dollars > n.risk_dollars * 1.9


def test_an_atr_proxy_that_ignores_the_stop_would_fail_this():
    """Written out so the distinction is checkable rather than asserted in a docstring: a
    formula reading only the ATR and the multiple returns the same number for two different
    stops, and the route's risk must not."""
    def proxy(mult, atr, pv, qty=1):
        return qty * mult * atr * pv

    assert proxy(1.5, 20.0, 5.0) == proxy(1.5, 20.0, 5.0)
    moved = CA.stop_risk_dollars(5000.0, 5000.0 - 1.5 * 20.0 - 10.0, 5.0, 1)
    unmoved = CA.stop_risk_dollars(5000.0, 5000.0 - 1.5 * 20.0, 5.0, 1)
    assert moved != unmoved, "the risk did not follow the stop"


def test_the_daily_atr_used_for_the_stop_is_causal():
    """The same trap as the label, in the sizing. The daily ATR row for a session is built
    from that session's own high, low and close."""
    frozen, _live = frames()
    frame = frozen["MES"]
    causal = S.causal_daily_atr(frame, DAY)
    assert causal is not None and causal > 0

    from futures._validated_core import daily_atr_series
    naive = frame.copy()
    naive.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    series = daily_atr_series(naive)
    assert causal == pytest.approx(float(series.loc[series.index < DAY.normalize()].iloc[-1]))

    for c in source().candidates(NOW):
        assert c.meta["daily_atr_causal"] == pytest.approx(causal)


def test_no_atr_before_today_is_a_named_refusal():
    frozen, live = frames()
    short = {k: v.loc[v.index >= pd.Timestamp(f"{SESSIONS[-1].date()} 09:30", tz=ET)]
             for k, v in frozen.items()}
    src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), labels=labels(),
                             frozen_frames=short)
    with pytest.raises(S.LiveSourceRefused) as e:
        src.candidates(NOW)
    assert e.value.code in (S.STOP_RISK_UNAVAILABLE, S.REGIME_UNAVAILABLE)


# ══════════════════════════════════════════════════════════════════════════════
# 6. the whole live-shadow slot, end to end
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def ledger(tmp_path, monkeypatch):
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


def test_a_slot_reaches_decided_and_closes_the_window(ledger, monkeypatch):
    d, wl, entry = ledger
    # Stage 5I made the live slot evaluate freshness and BIND on it, so a synthetic future
    # session — whose regime CSV is necessarily stale — now refuses instead of deciding. That
    # is the correct new behaviour and it is tested directly in the Stage 5I suite. What THIS
    # test is about is the window/ledger plumbing reaching `complete`, so the freshness verdict
    # is allowed here to isolate it, rather than the assertion being weakened to match.
    class _Allow:
        allow = True
        unverified = ()
        reasons = ()
        def as_dict(self):
            return {"allow": True, "unverified": [], "reasons": []}

    monkeypatch.setattr(entry.fresh, "evaluate", lambda **kw: _Allow())
    frozen, live = frames()
    src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), labels=labels(),
                             frozen_frames=frozen)
    res = entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000", now_et=NOW,
                                  provider=S.FrameBarProvider(live), frozen_frames=frozen,
                                  live_source=src, root=str(d.parent))
    assert res["decided"] is True and res["reason"] == entry.DECIDED
    assert res["candidates"] == 2

    st = wl.status(wl.read_day(str(DAY.date())), "roska4_calm", str(DAY.date()))
    assert st["outcome"] == "complete" and st["observed_slots"] == 1

    row = [r for r in wl.read_day(str(DAY.date())) if r["event"] == "slot_observed"][0]
    assert row["candidates"] == 2 and row["gate"] is True


def test_the_slot_records_the_sources_own_reason_not_a_generic_one(ledger):
    """A window of rows that all said `live_source_not_ready` could not tell a stale regime
    from a rule that lives in scratch."""
    d, wl, entry = ledger
    frozen, live = frames()
    src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live),
                             labels={DAY.normalize(): "Calm"}, frozen_frames=frozen)
    res = entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000", now_et=NOW,
                                  provider=S.FrameBarProvider(live), frozen_frames=frozen,
                                  live_source=src, root=str(d.parent))
    assert res["decided"] is False
    assert res["reason"] == S.REGIME_UNAVAILABLE, res
    st = wl.status(wl.read_day(str(DAY.date())), "roska4_calm", str(DAY.date()))
    assert st["outcome"] == "incomplete"


def test_a_checkpoint_can_be_written_to_a_temp_path_after_a_complete_window(ledger, tmp_path):
    d, wl, entry = ledger
    from global_index import track1_bootstrap as boot
    from global_index import track1_normal_r4 as NR

    ck = tmp_path / "cp.json"
    idx = pd.date_range(f"{DAY.date()} 09:30", periods=20, freq="5min", tz=ET)
    paths, fr = {}, {}
    for inst in ("MES", "MNQ", "MYM", "M2K", "MNKD"):
        f = tmp_path / f"{inst}.parquet"
        f.write_bytes(inst.encode())
        paths[inst] = str(f)
        fr[inst] = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                                 "volume": 1.0}, index=idx)
    entry.write_route_checkpoint("roska4_calm", now_et=NOW, regime_csv="spy_daily_live.csv",
                                 data_paths=paths, frames=fr, path=str(ck),
                                 book_path=str(tmp_path / "book.json"))
    res = boot.accepts(str(ck), sleeve="roska4_swing", inst="MES", frame=fr["MES"],
                       regime_csv="spy_daily_live.csv", data_path=paths["MES"],
                       fill_law=NR.NormalR4Params().fill_law)
    assert bool(res) is True
    # Stage 5ZK: mtime, not absence — the live close writes this file every day a
    # window completes, and forbidding that forbids the system from working.
    _assert_not_written_by_this_run("global_index/replay_checkpoint.track1.json")


def test_replay_still_writes_no_coverage(ledger):
    d, wl, entry = ledger
    assert wl.enabled() is True
    summary = entry.run_shadow(window="vault2026", regime_csv="spy_daily_live.csv",
                               now_et=pd.Timestamp("2026-08-21 11:00", tz=ET),
                               out_dir=str(d.parent / "shadow"))
    assert "not driven" in summary["window_ledger"]
    assert wl.files() == []
    assert summary["send_order_calls"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 7. nothing was armed and nothing was left behind
# ══════════════════════════════════════════════════════════════════════════════
def test_orders_remain_impossible(monkeypatch):
    from global_index import run_live_day_track1 as entry
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    # Property, not a count. This line used to pin the blocker list to exactly one element,
    # which made it red the moment a MEASURED gate legitimately re-shut — and a measured gate
    # re-shutting is the mechanism working, not a regression. What must hold is that orders are
    # impossible and that B1 is among the reasons; an extra blocker is allowed only if it is
    # genuinely holding.
    _blockers = {b.id for b in g.blocking()}
    assert "B1_broker_account_or_legacy_retirement" in _blockers, _blockers
    assert g.may_enable_orders()[0] is False
    for _extra in _blockers - {"B1_broker_account_or_legacy_retirement"}:
        _b = g.BLOCKERS[_extra]
        assert _b.blocks_orders and not _b.released(g.NO_CONFIRMATIONS), _extra
    if g.live_frame_wiring()[0]:
        assert _blockers == {"B1_broker_account_or_legacy_retirement"}, _blockers
    assert entry.OrderGate(True).allow_orders is False


def test_no_repo_route_state_was_created():
    for f in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
              "runner.track1.pid"):
        assert not Path(f).exists(), f
    # Stage 5ZK: the two route artefacts came off the absence list. The live close
    # writes both, in one call, every day a window completes.
    for f in ("live_positions.track1.json",
              "global_index/replay_checkpoint.track1.json"):
        _assert_not_written_by_this_run(f)


def test_no_broker_object_is_constructed_by_the_live_source():
    """Every test here injects FrameBarProvider. If this suite ever imports ib_insync, the
    claim 'no broker was exercised' stops being true and should fail here first."""
    assert "ib_insync" not in sys.modules


def test_the_runbook_still_does_not_claim_starting_fixes_five_and_six():
    txt = Path("docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md").read_text(encoding="utf-8")
    for line in txt.split("\n"):
        if "starting is what fixes them" in line:
            assert line.lstrip().startswith(">"), line
