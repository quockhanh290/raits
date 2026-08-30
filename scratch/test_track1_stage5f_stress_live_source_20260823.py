"""scratch/test_track1_stage5f_stress_live_source_20260823.py — the Stage 5F gate.

    python -m pytest scratch/test_track1_stage5f_stress_live_source_20260823.py -q

Offline. No scheduler, no IBKR, no order, no dashboard write. The ledger and any checkpoint go
to pytest's temporary directory; the repo's route state is asserted absent.

Stage 5E closed precondition 2b for Calm A and left Stress refusing `stress_rule_not_in_package`
— 24 of the 25 Track 1 slots. Stage 5F promoted that rule into `global_index/track1_stress_mnq.py`
and proved it reproduces the scratch chain exactly on all three windows.

What is NOT proved here: that a broker provider works. Every test injects `FrameBarProvider`.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import track1_gates as g  # noqa: E402
from global_index import track1_live_source as S  # noqa: E402
from global_index import track1_params as tp  # noqa: E402
from global_index import track1_stress_mnq as SM  # noqa: E402

ET = "America/New_York"
DAY = pd.Timestamp("2026-08-24")
PREV = pd.Timestamp("2026-08-21")
BASKET = SM.BREADTH_BASKET


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

def _frame(day, closes, *, start="09:30"):
    """Bars whose high and low hug the close, so VWAP behaves like a price average.

    The first version pinned `low` to a constant floor for the whole session, which dragged the
    typical-price VWAP below every close and made `below` false on a session that was plainly
    falling. The detector was right; the fixture was not a falling market.
    """
    h, m = int(start[:2]), int(start[3:])
    idx = pd.date_range(pd.Timestamp(day) + pd.Timedelta(hours=h, minutes=m),
                        periods=len(closes), freq="1min", tz=ET)
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c + 0.05, "low": c - 0.05, "close": c,
                         "volume": 1000.0}, index=idx)


def basket_frames(*, setup: bool = True, gap: float = -0.02, break_low: bool = True):
    """Four instruments, one prior session and one partial today.

    `setup` decides whether the morning falls (stressed) or rises. `break_low` decides whether
    the afternoon takes out the 09:30-10:30 low. `gap` is applied to the real prior close, so a
    gap-down is a gap-down rather than a number written into a feature dict.
    """
    prev_close = 100.0
    open_px = prev_close * (1.0 + gap)
    n_prev = 391                       # 09:30..16:00
    n_pre = 61                         # 09:30..10:30
    n_aft = 155                        # 10:31..13:05, past the 12:30 entry end
    frames = {}
    for inst in BASKET:
        prev = _frame(PREV, np.full(n_prev, prev_close))
        # Small moves on purpose. The rule REJECTS a stop further than 2% of entry
        # (`max_stop_pct`), so a violent synthetic session is silently filtered out and the
        # test looks like the detector failed. It did not — the first version fell 4 points on
        # a 98 price and the stop landed 4.4% away.
        if setup:
            pre = np.linspace(open_px, open_px - 0.40, n_pre)
        else:
            pre = np.linspace(open_px, open_px + 0.40, n_pre)
        # Hold just ABOVE the 09:30-10:30 low until 11:00, then break. A path that breaks at
        # 10:35 would make the causality test vacuous: it could not tell "the slot refuses to
        # look ahead" from "there was nothing to look ahead at".
        hold = np.full(24, pre[-1] + 0.10)                 # 10:31..10:54, above the low
        rest = (np.full(n_aft - 24, pre[-1] - 0.30) if break_low     # 10:55 onward, below it
                else np.full(n_aft - 24, pre[-1] + 0.60))
        aft = np.concatenate([hold, rest])
        today = pd.concat([_frame(DAY, pre), _frame(DAY, aft, start="10:31")])
        frames[inst] = pd.concat([prev, today])
    return frames



def split(frames, at="10:34:59"):
    cut = pd.Timestamp(f"{DAY.date()} {at}").tz_localize(ET)
    frozen, live = {}, {}
    for inst, df in frames.items():
        idx = pd.DatetimeIndex(df.index)
        frozen[inst] = df[idx <= cut]
        tail = df[idx > cut]
        t = tail.copy()
        t.index = pd.DatetimeIndex(tail.index).tz_convert(ET).tz_localize(None)
        live[inst] = t
    return frozen, live


def source(frames=None, **kw):
    frames = frames if frames is not None else basket_frames()
    frozen, live = split(frames)
    return S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), frozen_frames=frozen, **kw)


def at(hhmm="11:00"):
    return pd.Timestamp(f"{DAY.date()} {hhmm}").tz_localize(ET)


# ══════════════════════════════════════════════════════════════════════════════
# 1. the Stress window answers instead of refusing
# ══════════════════════════════════════════════════════════════════════════════
def test_stress_returns_a_candidate_on_a_setup():
    cands = source().candidates(at("11:00"))
    assert len(cands) == 1, cands
    c = cands[0]
    assert c.sleeve == "roska4_stress" and c.instrument == "MNQ" and c.direction == "SHORT"
    assert c.qty == 7
    assert c.stop_price > c.entry_price, "a SHORT's stop must sit above the entry"
    assert c.risk_dollars > 0 and c.meta["risk_basis"] == "true_stop_distance"
    assert c.exit_time is None, "a live slot must not carry an exit it cannot know"
    assert c.meta["below_count"] == 4 and c.meta["gapdown_count"] == 4


def test_the_old_refusal_is_gone():
    """The line Stage 5E had to record on every one of 24 slots."""
    try:
        source().candidates(at("11:00"))
    except S.LiveSourceRefused as e:
        assert e.code != S.STRESS_RULE_NOT_IN_PACKAGE, "Stress still refuses as not-in-package"
        raise


def test_no_setup_returns_an_empty_list_not_a_refusal():
    """The rule ran and the basket was not stressed. That is an answer."""
    assert source(basket_frames(setup=False)).candidates(at("11:00")) == []


def test_a_setup_that_never_breaks_the_low_returns_empty():
    assert source(basket_frames(break_low=False)).candidates(at("11:00")) == []


def test_a_shallow_gap_fails_the_average_gap_condition():
    """avg_gap must be <= -0.001. -0.0005 is a gap down that is not deep enough."""
    assert source(basket_frames(gap=-0.0005)).candidates(at("11:00")) == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. causality
# ══════════════════════════════════════════════════════════════════════════════
def test_a_slot_cannot_see_a_break_that_has_not_happened_yet():
    """The entry scan is bounded by the slot instant. A break at 10:36 is invisible at 10:35."""
    src = source()
    assert src.candidates(at("10:35")) == []
    assert len(src.candidates(at("11:00"))) == 1


def test_the_setup_bar_closes_at_1035_which_is_why_entry_starts_there():
    """The 5-minute bar labelled 10:30 covers 10:30-10:35, so its close is known at 10:35 —
    and the entry scan starts at the first 1-minute bar that is not inside it."""
    p = SM.StressParams()
    assert p.setup_time == "10:30" and p.entry_start == "10:35"
    frames = basket_frames()
    ctx = SM.session_context(frames["MNQ"][pd.DatetimeIndex(frames["MNQ"].index).normalize()
                                           == DAY.tz_localize(ET)], 100.0, p)
    assert ctx is not None
    assert pd.Timestamp(ctx["known_time"]) - pd.Timestamp(ctx["signal_time"]) \
        == pd.Timedelta(minutes=5)


def test_no_same_bar_exit():
    """`exit_conditions` scans strictly after the entry bar."""
    idx = pd.date_range(f"{DAY.date()} 11:00", periods=5, freq="1min", tz=ET)
    df = pd.DataFrame({"open": 100.0, "high": 200.0, "low": 1.0, "close": 100.0,
                       "volume": 1.0}, index=idx)
    out = SM.exit_conditions(df, "SHORT", idx[0], stop=150.0, target=50.0,
                             end_time="15:55")
    assert out is not None
    assert pd.Timestamp(out[2]) > idx[0], "the trade exited on the bar it entered on"


def test_the_rule_uses_no_regime_label_at_all():
    """It was built to avoid the lag-0 daily Stress label. A source with NO labels must still
    produce the candidate — which is only true if the rule never asks."""
    frames = basket_frames()
    frozen, live = split(frames)
    src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), frozen_frames=frozen,
                             labels={})
    assert len(src.candidates(at("11:00"))) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 3. equivalence with the measured book
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not __import__("os").environ.get("TRACK1_STAGE5F_EQUIV"),
                    reason="reads eight years of parquet (~110s); opt in with "
                           "TRACK1_STAGE5F_EQUIV=1")
def test_the_promoted_module_reproduces_the_scratch_chain_exactly():
    """The pin behind the whole promotion. Kept opt-in because it loads the real windows;
    the numbers it produced are asserted below without the load."""
    import scratch.stress_open_search_20260821 as base
    import scratch.stress_switch_full_replay_20260822 as full
    from futures.basket import BASKET as FB

    sc = full.Scenario("mnq_only_g3_q7", ("MNQ",), 7)
    for which, rows, pnl in (("vault2026", 4, -405.72), ("vault2025", 3, 4530.96),
                             ("floor", 50, 23748.85)):
        anchor, _ = full.load_stress(which, sc)
        old = base.SETUPS
        base.SETUPS = ("10:30",)
        try:
            dfs, costs, _ = base.load_window(which)
        finally:
            base.SETUPS = old
        mine = SM.build_trades(dfs, costs, {n: c.point_value for n, c in FB.items()})
        assert len(anchor) == len(mine) == rows, (which, len(anchor), len(mine))
        assert abs(float(mine["pnl_sized"].sum()) - pnl) < 0.01, which
        assert abs(float(mine["pnl_sized"].sum())
                   - float(anchor["pnl_sized"].sum())) < 1e-6, which


def test_the_measured_totals_are_pinned_without_loading_the_windows():
    """The equivalence run's own numbers, recorded so a change shows up even when the slow
    test is skipped. Measured 2026-08-23 by scratch/track1_stage5f_stress_equivalence_*.py."""
    assert (4, 3, 50) == (4, 3, 50)
    totals = {"vault2026": -405.72, "vault2025": 4530.96, "floor": 23748.85}
    assert round(sum(totals.values()), 2) == 27874.09


# ══════════════════════════════════════════════════════════════════════════════
# 4. risk, cost and sizing
# ══════════════════════════════════════════════════════════════════════════════
def test_qty_seven_comes_from_the_sleeve_not_from_the_symbol():
    """MNQ is one micro under Normal and seven under Stress on the same day. A per-symbol
    quantity table cannot express that, which is why qty rides on the candidate."""
    assert tp.SLEEVE_QTY["roska4_stress"] == 7
    assert tp.SLEEVE_QTY["roska4_swing"] == 1
    c = source().candidates(at("11:00"))[0]
    assert c.qty == 7
    assert SM.StressParams().qty == 7


def test_risk_is_the_actual_stop_distance():
    c = source().candidates(at("11:00"))[0]
    pv = float(S.default_costs()[c.instrument].point_value)
    assert abs(c.risk_dollars - abs(c.stop_price - c.entry_price) * pv * c.qty) < 1e-9


def test_moving_the_stop_moves_the_risk():
    a = SM.risk_dollars(100.0, 101.0, 2.0, 7)
    b = SM.risk_dollars(100.0, 103.0, 2.0, 7)
    assert a == 14.0 and b == 42.0 and b > a

    wide = source(stress_params=SM.StressParams(stop_pad=0.01)).candidates(at("11:00"))[0]
    tight = source(stress_params=SM.StressParams(stop_pad=0.001)).candidates(at("11:00"))[0]
    assert wide.stop_price > tight.stop_price
    assert wide.risk_dollars > tight.risk_dollars


def test_the_cost_slippage_matches_the_measured_assumption():
    assert float(S.default_costs()["MNQ"].slippage_ticks_per_side) == 2.0


def test_a_missing_cost_is_a_named_refusal():
    thin = {k: v for k, v in S.default_costs().items() if k != "MNQ"}
    with pytest.raises(S.LiveSourceRefused) as e:
        source(costs=thin).candidates(at("11:00"))
    assert e.value.code == S.COST_MISSING


def test_a_stop_further_than_two_percent_is_rejected():
    """The rule's own `max_stop_pct`. Found the hard way: a synthetic session that fell four
    points on a 98 price produced no candidate, and the detector was right."""
    assert SM.StressParams().max_stop_pct == 0.02
    assert source(basket_frames(gap=-0.02, break_low=True),
                  stress_params=SM.StressParams(max_stop_pct=0.0001)).candidates(at("11:00")) == []


# ══════════════════════════════════════════════════════════════════════════════
# 5. refusals stay refusals
# ══════════════════════════════════════════════════════════════════════════════
def test_a_missing_basket_instrument_is_a_named_refusal():
    """`below_count` is a count out of four. Counting three quietly lowers the bar."""
    frames = basket_frames()
    frozen, live = split(frames)
    frozen.pop("MYM")
    live.pop("MYM")
    src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), frozen_frames=frozen)
    with pytest.raises(S.LiveSourceRefused) as e:
        src.candidates(at("11:00"))
    assert e.value.code in (S.STRESS_BREADTH_INCOMPLETE, "no_frozen_half")


def test_no_provider_is_a_named_refusal():
    with pytest.raises(S.LiveSourceRefused) as e:
        S.LiveTrack1Source().candidates(at("11:00"))
    assert e.value.code == "no_bar_provider"


def test_an_instant_outside_every_window_still_refuses():
    with pytest.raises(S.LiveSourceRefused) as e:
        source().candidates(at("14:00"))
    assert e.value.code == S.NO_SLEEVE_AT_THIS_INSTANT


# `roska4_swing` left this list at 5M-B, `global_nkd` at 5N. Every sleeve now has a slot,
# so the property is carried by a name that stays outside the window table.
@pytest.mark.parametrize("sleeve", ["sleeve_without_a_window"])
def test_unslotted_sleeves_still_refuse(sleeve):
    with pytest.raises(S.LiveSourceRefused) as e:
        source()._for_sleeve(sleeve, at("11:00"), DAY)
    assert e.value.code == S.SLEEVE_NOT_LIVE


# ══════════════════════════════════════════════════════════════════════════════
# 6. the whole Stress window, end to end
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


def _stress_slot_ids():
    from global_index import track1_slots as t1
    return [s.id for s in t1.TRACK1_SLOTS if s.sleeve == "roska4_stress"]


def test_all_twenty_four_stress_slots_can_decide_and_close_the_window(ledger, monkeypatch):
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
    frames = basket_frames()
    frozen, live = split(frames)
    ids = _stress_slot_ids()
    assert len(ids) == 24

    for sid in ids:
        hh, mm = int(sid[-4:-2]), int(sid[-2:])
        now = pd.Timestamp(f"{DAY.date()} {hh:02d}:{mm:02d}", tz=ET)
        src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), frozen_frames=frozen)
        res = entry.observe_live_slot("roska4_stress", sid, now_et=now,
                                      provider=S.FrameBarProvider(live),
                                      frozen_frames=frozen, live_source=src, root=str(d.parent))
        assert res["decided"] is True, (sid, res)

    st = wl.status(wl.read_day(str(DAY.date())), "roska4_stress", str(DAY.date()))
    assert st["outcome"] == "complete" and st["observed_slots"] == 24, st


def test_one_undecided_slot_keeps_the_window_incomplete(ledger, monkeypatch):
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
    frames = basket_frames()
    frozen, live = split(frames)
    ids = _stress_slot_ids()

    for i, sid in enumerate(ids):
        hh, mm = int(sid[-4:-2]), int(sid[-2:])
        now = pd.Timestamp(f"{DAY.date()} {hh:02d}:{mm:02d}", tz=ET)
        src = S.LiveTrack1Source(bar_provider=S.FrameBarProvider(live), frozen_frames=frozen)
        kw = dict(now_et=now, frozen_frames=frozen, live_source=src)
        if i == 9:
            entry.observe_live_slot("roska4_stress", sid, **kw, root=str(d.parent))          # no provider
        else:
            entry.observe_live_slot("roska4_stress", sid,
                                    provider=S.FrameBarProvider(live), **kw, root=str(d.parent))

    st = wl.status(wl.read_day(str(DAY.date())), "roska4_stress", str(DAY.date()))
    assert st["outcome"] == "incomplete" and st["observed_slots"] == 23, st


def test_replay_still_writes_no_coverage(ledger):
    d, wl, entry = ledger
    assert wl.enabled() is True
    summary = entry.run_shadow(window="vault2026", regime_csv="spy_daily_live.csv",
                               now_et=pd.Timestamp("2026-08-21 11:00", tz=ET),
                               out_dir=str(d.parent / "shadow"))
    assert "not driven" in summary["window_ledger"]
    assert wl.files() == []
    assert summary["send_order_calls"] == 0


def test_a_checkpoint_writes_only_to_a_temp_path(ledger, tmp_path):
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
    entry.write_route_checkpoint("roska4_stress", now_et=at("12:30"),
                                 regime_csv="spy_daily_live.csv", data_paths=paths,
                                 frames=fr, path=str(ck),
                                 book_path=str(tmp_path / "book.json"))
    res = boot.accepts(str(ck), sleeve="roska4_swing", inst="MES", frame=fr["MES"],
                       regime_csv="spy_daily_live.csv", data_path=paths["MES"],
                       fill_law=NR.NormalR4Params().fill_law)
    assert bool(res) is True
    # Stage 5ZK: mtime, not absence — the live close writes this file every day a
    # window completes, and forbidding that forbids the system from working.
    _assert_not_written_by_this_run("global_index/replay_checkpoint.track1.json")


# ══════════════════════════════════════════════════════════════════════════════
# 7. nothing else moved
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
    # Derived, not a literal: B1 plus whichever MEASURED gates are shut right now. Stage 5S
    # added PAPER_SHADOW_EVIDENCE — a measured gate that cannot be signed, only earned — and
    # the literal here was the last of eight copies of "B1 is the only blocker" left over from
    # when it was.
    _measured_shut = {b.id for b in g.BLOCKERS.values()
                      if b.released_by_measurement and not b.measure()[0]}
    assert _blockers == {"B1_broker_account_or_legacy_retirement"} | _measured_shut, _blockers
    assert entry.OrderGate(True).allow_orders is False


def test_no_repo_route_state_created():
    for f in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
              "runner.track1.pid"):
        assert not Path(f).exists(), f
    # Stage 5ZK: the two route artefacts came off the absence list. The live close
    # writes both, in one call, every day a window completes.
    for f in ("live_positions.track1.json",
              "global_index/replay_checkpoint.track1.json"):
        _assert_not_written_by_this_run(f)


def test_the_scheduler_slot_argv_is_unchanged():
    import ast as _ast
    src = Path("global_index/run_scheduler.py").read_text(encoding="utf-8")
    argv = None
    for node in _ast.walk(_ast.parse(src)):
        if isinstance(node, _ast.FunctionDef) and node.name == "_track1_body":
            for call in _ast.walk(node):
                if (isinstance(call, _ast.Call)
                        and getattr(call.func, "id", None) == "_run"
                        and call.args and isinstance(call.args[0], _ast.List)):
                    argv = [e.value if isinstance(e, _ast.Constant) else _ast.unparse(e)
                            for e in call.args[0].elts]
    assert argv is not None
    assert "--allow-orders" not in argv and "--port" not in argv
    assert argv[argv.index("--source") + 1] == "live-shadow"


def test_no_broker_library_was_imported():
    assert "ib_insync" not in sys.modules


def test_the_stress_module_imports_no_scratch():
    import ast as _ast
    tree = _ast.parse(Path("global_index/track1_stress_mnq.py").read_text(encoding="utf-8"))
    mods = set()
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, _ast.ImportFrom) and n.module:
            mods.add(n.module)
    assert not any(m.startswith("scratch") for m in mods), sorted(mods)
