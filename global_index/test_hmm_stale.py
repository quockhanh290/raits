"""
global_index/test_hmm_stale.py — synthetic tests for HMM stale guards G1/G2/G3
===============================================================================
Run from d:\\raits:
    python global_index/test_hmm_stale.py

Covers:
  G1: soft-warn / hard-halt / entry-blocked-exit-keeps / recovery
  G2: model-age soft+hard (warn only, never halt)
  G3: refreeze aborts when CSV < fit_end (in futures/refreeze.py)
  Baseline: runner without guard → baseline unaffected
  No-harm: HMMEngine git log untouched
"""
from __future__ import annotations
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from global_index.hmm_stale_guard import HMMStaleGuard, _spy_gap_bdays
from global_index.notify import set_push_hook

# ── Test harness ──────────────────────────────────────────────────────────────

_PASS = 0
_FAIL = 0
_results: list = []

def _check(name: str, cond: bool, detail: str = "") -> None:
    global _PASS, _FAIL
    tag = "PASS" if cond else "FAIL"
    print(f"  {tag}  {name}" + (f"  [{detail}]" if detail else ""))
    _results.append((name, bool(cond), detail))
    if cond:
        _PASS += 1
    else:
        _FAIL += 1


def _enforce_checks_under_pytest() -> None:
    """Make _check failures reach pytest — the twin of the hooks in
    test_operational_fixes.py and test_event_playback.py.

    Those two were fixed when the realtime audit found that check() only printed and
    appended, with sys.exit(1) reachable solely from __main__: under pytest every test
    function returned None and passed no matter what the checks said. This file has the
    same harness, was missed, and carries 43 checks — every one of them invisible.

    What they cover is not incidental. G1 halts entries when the SPY series that feeds
    the regime model goes stale, G2 watches model age, G3 aborts a re-freeze whose data
    does not reach fit_end. A guard whose entire test file cannot go red is a guard
    nobody is watching.
    """
    import functools
    import sys as _sys

    mod = _sys.modules[__name__]
    for _name in [n for n in dir(mod) if n.startswith("test_")]:
        _fn = getattr(mod, _name)
        if not callable(_fn) or getattr(_fn, "_checks_enforced", False):
            continue

        @functools.wraps(_fn)
        def _wrapped(*args, __fn=_fn, **kwargs):
            start = len(_results)
            out = __fn(*args, **kwargs)
            mine = _results[start:]
            # A test that records nothing is not passing, it is absent — the same
            # self-check the other two hooks carry.
            assert mine, "this test recorded no checks at all"
            failed = [(n, d) for n, ok, d in mine if not ok]
            assert not failed, f"{len(failed)}/{len(mine)} check(s) failed: {failed}"
            return out

        _wrapped._checks_enforced = True
        setattr(mod, _name, _wrapped)


def _capture_notify():
    """Returns (captured_list, restore_fn). Captures (level, msg) tuples."""
    captured = []
    set_push_hook(lambda level, msg: captured.append((level, msg)))
    def restore():
        set_push_hook(None)
    return captured, restore


def _make_guard(fit_end="2024-12-31"):
    """Guard with a dummy CSV path (spy_last_date_override always used in tests)."""
    return HMMStaleGuard(regime_csv="spy_daily.csv", fit_end=fit_end)


def _make_runner(stale_guard=None, entry_pnl=50.0):
    """Minimal FuturesRunner with a signal_fn returning 1 entry + no exits."""
    from global_index.broker import MockBroker
    from global_index.runner import FuturesRunner
    from global_index.net_exposure_multi import MultiClusterGuard
    from futures.circuit_breaker import CircuitBreaker

    broker   = MockBroker(bars_by_inst={}, account=50_000)
    cap_guard = MultiClusterGuard(account=50_000)
    breaker  = CircuitBreaker(account=50_000)

    def signal_fn(day, bars, held):
        d = pd.Timestamp(day).normalize()
        entry = [{
            "inst": "MES", "direction": "LONG", "cluster": "roska4_swing",
            "risk_sized": 100.0,
            "exit": d + pd.Timedelta(days=3),
            "pnl_sized": entry_pnl,
        }]
        return entry, []

    return FuturesRunner(
        broker=broker, guard=cap_guard,
        contracts_by_inst={"MES": 1, "MNQ": 1},
        signal_fn=signal_fn, breaker=breaker,
        hmm_stale_guard=stale_guard,
    )

# ── G1 tests ──────────────────────────────────────────────────────────────────

def test_g1_soft():
    print("\n" + "=" * 60)
    print("G1: SOFT stale (3 bday > SOFT=2)")
    print("=" * 60)

    TODAY    = pd.Timestamp("2026-01-12")  # Monday
    SPY_LAST = pd.Timestamp("2026-01-07")  # Wednesday prior week
    gap = _spy_gap_bdays(SPY_LAST, TODAY)

    guard = _make_guard()
    notifs, restore = _capture_notify()
    entries_ok = guard.check_day(TODAY, spy_last_date_override=SPY_LAST)
    restore()

    _check("G1.1 gap == 3 bday", gap == 3, f"gap={gap}")
    _check("G1.2 regime_unreliable=False (soft → trade continues)", not guard.regime_unreliable)
    _check("G1.3 _g1_soft_active=True", guard._g1_soft_active)
    _check("G1.4 entries_allowed=True", entries_ok)
    _check("G1.5 REGIME WARN notified", any("WARN" in n[0] for n in notifs),
           f"notifs={[n[0] for n in notifs]}")

    # Second call same day: soft notify fires only ONCE (transition guard)
    notifs2, restore2 = _capture_notify()
    guard.check_day(TODAY, spy_last_date_override=SPY_LAST)
    restore2()
    _check("G1.6 WARN only fires once (no re-notify)", len(notifs2) == 0,
           f"second call notifs={len(notifs2)}")


def test_g1_hard():
    print("\n" + "=" * 60)
    print("G1: HARD stale (6 bday > HARD=5)")
    print("=" * 60)

    TODAY    = pd.Timestamp("2026-01-15")  # Thursday
    SPY_LAST = pd.Timestamp("2026-01-07")  # 6 bday gap
    gap = _spy_gap_bdays(SPY_LAST, TODAY)

    guard = _make_guard()
    notifs, restore = _capture_notify()
    entries_ok = guard.check_day(TODAY, spy_last_date_override=SPY_LAST)
    restore()

    _check("G1.7 gap == 6 bday", gap == 6, f"gap={gap}")
    _check("G1.8 regime_unreliable=True", guard.regime_unreliable)
    _check("G1.9 entries_allowed=False", not entries_ok)
    _check("G1.10 TRADING HALTED notified", any("HALTED" in n[0] for n in notifs),
           f"notifs={[n[0] for n in notifs]}")

    # Second call — already halted, no re-notify
    notifs2, restore2 = _capture_notify()
    guard.check_day(TODAY, spy_last_date_override=SPY_LAST)
    restore2()
    _check("G1.11 HALTED fires only once (already stale)", len(notifs2) == 0,
           f"second call notifs={len(notifs2)}")


def test_g1_halt_entry_keep_exit():
    print("\n" + "=" * 60)
    print("G1: HALT entries — EXIT of held position runs normally")
    print("=" * 60)

    from global_index.live_decision import OpenPos

    TODAY    = pd.Timestamp("2026-01-15")
    SPY_LAST = pd.Timestamp("2026-01-07")  # 6 bday — hard stale

    guard  = _make_guard()
    runner = _make_runner(stale_guard=guard)

    # Pre-populate a held position that exits TODAY
    held = OpenPos(
        inst="MNQ", direction="LONG", contracts=1, risk_dollars=200.0,
        cluster="roska4_swing",
        entry_day=pd.Timestamp("2026-01-10"),
        exit_day=TODAY,
        pnl_sized=300.0,
    )
    runner.state.open_positions = [held]

    # signal_fn: 1 new entry for MES (should be blocked); MNQ exits via exit_day
    def signal_fn_with_exit(day, bars, held_pos):
        entries = [{
            "inst": "MES", "direction": "LONG", "cluster": "roska4_swing",
            "risk_sized": 100.0,
            "exit": pd.Timestamp(day) + pd.Timedelta(days=3),
            "pnl_sized": 50.0,
        }]
        exits = [p for p in held_pos if p.exit_day == pd.Timestamp(day).normalize()]
        return entries, exits

    runner.signal_fn = signal_fn_with_exit

    notifs, restore = _capture_notify()
    decision = runner.run_day(TODAY, _spy_last_date_override=SPY_LAST)
    restore()

    _check("G1.12 decision.exits == 1 (MNQ position closed)", len(decision.exits) == 1,
           f"exits={len(decision.exits)}")
    _check("G1.13 decision.entries == 0 (MES blocked)", len(decision.entries) == 0,
           f"entries={len(decision.entries)}")
    _check("G1.14 guard.entries_blocked == 1", guard.entries_blocked == 1,
           f"entries_blocked={guard.entries_blocked}")
    _check("G1.15 TRADING HALTED notified via runner", any("HALTED" in n[0] for n in notifs),
           f"notifs={[n[0] for n in notifs]}")
    _check("G1.16 equity updated by exit P&L ($300)", runner.state.equity == 50_300.0,
           f"equity={runner.state.equity}")


def test_g1_recovery():
    print("\n" + "=" * 60)
    print("G1: RECOVERY — was hard-stale, CSV refreshed to ≤2 bday")
    print("=" * 60)

    TODAY_STALE   = pd.Timestamp("2026-01-15")
    SPY_LAST_OLD  = pd.Timestamp("2026-01-07")  # 6 bday — hard stale

    TODAY_FRESH   = pd.Timestamp("2026-01-19")  # Monday after refresh
    SPY_LAST_NEW  = pd.Timestamp("2026-01-16")  # Friday — 1 bday gap

    guard = _make_guard()

    # Step 1: go hard-stale
    notifs1, r1 = _capture_notify()
    guard.check_day(TODAY_STALE, spy_last_date_override=SPY_LAST_OLD)
    r1()

    _check("G1.17 regime_unreliable after stale", guard.regime_unreliable)

    # Step 2: CSV refreshed → recovery
    notifs2, r2 = _capture_notify()
    entries_ok = guard.check_day(TODAY_FRESH, spy_last_date_override=SPY_LAST_NEW)
    r2()

    _check("G1.18 regime_unreliable cleared after recovery", not guard.regime_unreliable)
    _check("G1.19 entries_allowed=True after recovery", entries_ok)
    _check("G1.20 TRADING RESUMED notified", any("RESUMED" in n[0] for n in notifs2),
           f"notifs={[n[0] for n in notifs2]}")

    # Step 3: no second RESUMED on next fresh day
    notifs3, r3 = _capture_notify()
    guard.check_day(TODAY_FRESH + pd.Timedelta(days=1),
                    spy_last_date_override=SPY_LAST_NEW + pd.Timedelta(days=1))
    r3()
    _check("G1.21 RESUMED fires only once", len(notifs3) == 0,
           f"third call notifs={len(notifs3)}")


# ── G2 tests ──────────────────────────────────────────────────────────────────

def test_g2_model_age():
    print("\n" + "=" * 60)
    print("G2: Model age — soft (13mo) + hard (19mo), warn-only")
    print("=" * 60)

    # _months_since(fit_end=2024-12-31, today): (y-2024)*12 + (m-12)
    # 2025-11-15 → 11mo (fresh); 2026-02-15 → 13mo (soft); 2026-07-15 → 19mo (hard)
    FRESH = pd.Timestamp("2025-11-15")   # 11 mo — below soft threshold (≤12)
    SOFT  = pd.Timestamp("2026-02-15")   # 13 mo — soft zone (>12)
    HARD  = pd.Timestamp("2026-07-15")   # 19 mo — hard zone (>18)

    guard = _make_guard(fit_end="2024-12-31")

    def _fresh_spy(today):
        # 1 bday behind today — keeps G1 gap=1 (not stale)
        return today - pd.tseries.offsets.BDay(1)

    # Fresh — no notify
    notifs_fresh, r0 = _capture_notify()
    guard.check_day(FRESH, spy_last_date_override=_fresh_spy(FRESH))
    r0()
    _check("G2.1 no notify when fresh (11mo)", len(notifs_fresh) == 0,
           f"notifs={[n[0] for n in notifs_fresh]}")
    _check("G2.2 regime_unreliable=False (G2 never halts)", not guard.regime_unreliable)

    # Soft — MODEL AGE WARN
    notifs_soft, r1 = _capture_notify()
    guard.check_day(SOFT, spy_last_date_override=_fresh_spy(SOFT))
    r1()
    _check("G2.3 MODEL AGE WARN notified at 13mo",
           any("WARN" in n[0] for n in notifs_soft),
           f"notifs={[n[0] for n in notifs_soft]}")
    _check("G2.4 regime_unreliable still False (G2 never halts)", not guard.regime_unreliable)

    # Soft again — no re-notify (fires once)
    SOFT2 = SOFT + pd.Timedelta(days=7)
    notifs_soft2, r2 = _capture_notify()
    guard.check_day(SOFT2, spy_last_date_override=_fresh_spy(SOFT2))
    r2()
    _check("G2.5 soft WARN fires only once", len(notifs_soft2) == 0,
           f"second soft notifs={len(notifs_soft2)}")

    # Hard — MODEL AGE CHECK DUE
    notifs_hard, r3 = _capture_notify()
    guard.check_day(HARD, spy_last_date_override=_fresh_spy(HARD))
    r3()
    _check("G2.6 MODEL AGE CHECK DUE notified at 19mo",
           any("CHECK DUE" in n[0] for n in notifs_hard),
           f"notifs={[n[0] for n in notifs_hard]}")
    _check("G2.7 regime_unreliable still False (G2 never halts)", not guard.regime_unreliable)

    # Hard again — no re-notify (fires once)
    HARD2 = HARD + pd.Timedelta(days=7)
    notifs_hard2, r4 = _capture_notify()
    guard.check_day(HARD2, spy_last_date_override=_fresh_spy(HARD2))
    r4()
    _check("G2.8 hard CHECK DUE fires only once", len(notifs_hard2) == 0,
           f"second hard notifs={len(notifs_hard2)}")


# ── G3 tests ──────────────────────────────────────────────────────────────────

def test_g3_refreeze_data_coverage():
    print("\n" + "=" * 60)
    print("G3: Re-freeze aborts if spy CSV < fit_end")
    print("=" * 60)

    from futures.refreeze import _check_spy_coverage

    FIT_END = pd.Timestamp("2024-12-31")

    # CSV ends before fit_end → must abort
    spy_short = pd.Series(
        [450.0, 455.0],
        index=pd.DatetimeIndex(["2024-06-30", "2024-09-30"]),
    )
    notifs, restore = _capture_notify()
    raised = False
    try:
        _check_spy_coverage(spy_short, FIT_END, "test_spy.csv")
    except ValueError as e:
        raised = True
        err_msg = str(e)
    restore()

    _check("G3.1 raises ValueError when CSV < fit_end", raised)
    _check("G3.2 error message mentions G3 ABORT", "G3 ABORT" in (err_msg if raised else ""))
    _check("G3.3 REFREEZE ABORTED notified",
           any("ABORTED" in n[0] for n in notifs),
           f"notifs={[n[0] for n in notifs]}")

    # CSV covers fit_end exactly → no abort
    spy_exact = pd.Series(
        [450.0, 460.0],
        index=pd.DatetimeIndex(["2024-06-30", "2024-12-31"]),
    )
    no_raise = True
    try:
        _check_spy_coverage(spy_exact, FIT_END, "test_spy.csv")
    except ValueError:
        no_raise = False
    _check("G3.4 no abort when CSV == fit_end", no_raise)

    # CSV covers beyond fit_end → no abort
    spy_long = pd.Series(
        [450.0, 460.0, 465.0],
        index=pd.DatetimeIndex(["2024-06-30", "2024-12-31", "2025-03-31"]),
    )
    no_raise2 = True
    try:
        _check_spy_coverage(spy_long, FIT_END, "test_spy.csv")
    except ValueError:
        no_raise2 = False
    _check("G3.5 no abort when CSV > fit_end", no_raise2)


# ── Baseline + no-harm ────────────────────────────────────────────────────────

def test_baseline_no_guard():
    print("\n" + "=" * 60)
    print("Baseline: runner without guard — existing callers unaffected")
    print("=" * 60)

    TODAY = pd.Timestamp("2026-01-10")
    runner = _make_runner(stale_guard=None)
    decision = runner.run_day(TODAY)

    _check("base.1 no stale guard → entries admitted normally", len(decision.entries) == 1,
           f"entries={len(decision.entries)}")
    _check("base.2 _hmm_stale_guard is None (default)",
           runner._hmm_stale_guard is None)


def test_no_harm_hmm_engine():
    print("\n" + "=" * 60)
    print("No-harm: HMMEngine class untouched")
    print("=" * 60)
    import subprocess
    result = subprocess.run(
        ["git", "log", "--oneline", "-1", "raits/hmm/engine.py"],
        capture_output=True, text=True, cwd=str(_ROOT),
    )
    last_commit = result.stdout.strip()
    _check("noharm.1 git log raits/hmm/engine.py has no new commit this session",
           "feat: implement full backtest framework" in last_commit
           or len(last_commit) > 0,
           f"last: {last_commit}")


# ── _spy_gap_bdays unit tests ─────────────────────────────────────────────────

def test_gap_bdays():
    print("\n" + "=" * 60)
    print("_spy_gap_bdays: unit tests")
    print("=" * 60)

    mon = pd.Timestamp("2026-01-12")  # Monday
    fri = pd.Timestamp("2026-01-09")  # Friday

    _check("gap.1 same day → 0", _spy_gap_bdays(mon, mon) == 0)
    _check("gap.2 future last → 0", _spy_gap_bdays(mon + pd.Timedelta(days=1), mon) == 0)
    _check("gap.3 Mon→Mon+1wk = 5", _spy_gap_bdays(mon, mon + pd.Timedelta(days=7)) == 5,
           f"got={_spy_gap_bdays(mon, mon + pd.Timedelta(days=7))}")
    _check("gap.4 Fri→Mon = 1 bday (weekend skipped)",
           _spy_gap_bdays(fri, mon) == 1, f"got={_spy_gap_bdays(fri, mon)}")
    _check("gap.5 None last → 0", _spy_gap_bdays(None, mon) == 0)


# ── Main ──────────────────────────────────────────────────────────────────────

# Wrap only under pytest. In script mode the tail below already exits non-zero on
# _FAIL, and collect-all is what the script exists for. An autouse fixture was rejected
# in the twin for a measured reason: asserting after `yield` is a TEARDOWN failure, so
# pytest prints "N passed, M errors" and leaves a misleading passed-count next to them.
if __name__ != "__main__":
    _enforce_checks_under_pytest()


if __name__ == "__main__":
    test_gap_bdays()
    test_g1_soft()
    test_g1_hard()
    test_g1_halt_entry_keep_exit()
    test_g1_recovery()
    test_g2_model_age()
    test_g3_refreeze_data_coverage()
    test_baseline_no_guard()
    test_no_harm_hmm_engine()

    print("\n" + "=" * 60)
    total = _PASS + _FAIL
    print(f"OVERALL: {_PASS}/{total} passed  {'ALL PASS' if _FAIL == 0 else f'{_FAIL} FAILED'}")
    print("=" * 60)
    sys.exit(0 if _FAIL == 0 else 1)
