"""scratch/test_track1_stage3_route_20260822.py — the Stage 3 gate.

    python -m pytest scratch/test_track1_stage3_route_20260822.py -q
    TRACK1_EQUIV_FLOOR=1 python -m pytest scratch/test_track1_stage3_route_20260822.py -q

Offline. No broker, no scheduler, no dashboard, no order.

What this file is for, in one line each
---------------------------------------
* T1  the ported rule set reproduces the anchor's ORDERED settlements, and each rule is
      shown to be load-bearing by mutating it and requiring divergence
* T2  at most one Track 1 position per instrument, across all four sleeves
* T3  quantity belongs to the candidate: MNQ = 1 under Normal and 7 under Stress
* T4  the SPY short gate is causal at D-1, proved by mutation rather than by reading
* T5  a missed 10:00 Calm A is not entered late
* T6  Stress enters inside 10:35-12:30 and never after it
* T7  the shadow route never calls send_order
* T8  the shadow route writes nothing under a legacy path
* T9  route-checkpoint refusals reach the entry point as CODES
* T10 the switch primitive: no second leg without a verified close, and no close without a
      confirmed stop cancel
* T11 the freshness gate fails closed

The floor window is the strongest anchor — 1160 events, and the only one that exercises the
breaker halt — but it costs about two minutes, so it runs only under TRACK1_EQUIV_FLOOR=1.
The default pair still covers the switch, both suppression directions, the family cap and
the cluster caps.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.circuit_breaker import CircuitBreaker  # noqa: E402
from global_index import route_checkpoint as rc  # noqa: E402
from global_index import run_live_day_track1 as entry  # noqa: E402
from global_index import track1_freshness as fresh  # noqa: E402
from global_index import track1_normal_r4 as NR  # noqa: E402
from global_index import track1_params as tp  # noqa: E402
from global_index import track1_signal_layer as T  # noqa: E402
from global_index import track1_switch as sw  # noqa: E402
from global_index.broker import Fill  # noqa: E402

ANCHOR_POLICY = "risk_clean_no_calm_nkd_family_cap_5_44"
DEFAULT_WINDOWS = ("vault2026", "vault2025")


# ── helpers ──────────────────────────────────────────────────────────────────
def _anchor(window: str):
    """The ordered settlements the SCRATCH loop produces. This is the reference, and it is
    re-run rather than read from a pinned file: a stored anchor cannot notice that the
    implementation it came from has moved."""
    import scratch.combined_repaired_replay_20260822 as comb
    import scratch.track1_stage2c_book_bootstrap_20260822 as boot
    pol = next(p for p in comb.POLICIES if p.name == ANCHOR_POLICY)
    daily, st, _end, ev = boot.replay(window, pol)
    keys = [(e["ts"], e["trade_id"], e["cluster"], e["instrument"], round(e["pnl"], 6))
            for e in ev]
    return keys, st, float(daily.sum())


def _port(window: str, **book_kw):
    import scratch.track1_replay_source_20260822 as src
    book = T.Track1Book(guard=T.make_guard(), breaker=CircuitBreaker(account=T.ACCOUNT),
                        **book_kw)
    settlements, decisions = T.run_candidates(src.candidates(window), book=book,
                                              early_exit_value=src.early_exit_valuer(window))
    return [T.event_key(s) for s in settlements], book, decisions


def _cand(sleeve, inst, direction="LONG", qty=1, risk=500.0, ts="2026-03-02 10:00:00",
          exit_ts="2026-03-02 15:55:00", pnl=0.0, tid=None):
    return T.Candidate(trade_id=tid or f"{sleeve}:{inst}:{ts}", sleeve=sleeve,
                       instrument=inst, direction=direction, qty=qty, risk_dollars=risk,
                       entry_time=pd.Timestamp(ts), exit_time=pd.Timestamp(exit_ts),
                       entry_price=100.0, pnl_sized=pnl)


def _fresh_book(**kw):
    return T.Track1Book(guard=T.make_guard(), breaker=CircuitBreaker(account=T.ACCOUNT), **kw)


# ── T1: equivalence, then mutation ───────────────────────────────────────────
@pytest.mark.parametrize("window", DEFAULT_WINDOWS)
def test_1_ported_rules_reproduce_the_anchor_event_for_event(window):
    anchor, st, net = _anchor(window)
    assert len(anchor) > 50, "the anchor produced almost nothing — the comparison would be empty"
    got, book, _dec = _port(window)
    assert len(got) == len(anchor), (len(got), len(anchor))
    first = next((i for i, (a, b) in enumerate(zip(anchor, got)) if a != b), None)
    assert first is None, (f"first divergence at #{first}", anchor[first], got[first])
    assert got == anchor
    assert round(book.equity - T.ACCOUNT, 2) == round(net, 2)
    for cluster, n in st["taken"].items():
        assert book.counters.get(f"taken:{cluster}", 0) == n, cluster
    for cluster, n in st["rejected"].items():
        assert book.counters.get(f"rejected:{cluster}", 0) == n, cluster


@pytest.mark.skipif(os.environ.get("TRACK1_EQUIV_FLOOR") != "1",
                    reason="floor is the two-minute anchor; opt in with TRACK1_EQUIV_FLOOR=1")
def test_1b_floor_window_reproduces_including_the_breaker_halt():
    anchor, st, _net = _anchor("floor")
    got, book, _dec = _port("floor")
    assert got == anchor
    assert st["halted"] > 0, "floor is the window chosen because it halts; it did not"
    assert book.counters.get("halt_breaker", 0) == st["halted"]


def test_1c_the_two_rules_that_are_not_in_the_anchor_are_inert_on_it():
    """Both additions must fire ZERO times on the anchor windows, or the equivalence above
    is passing for the wrong reason."""
    for window in DEFAULT_WINDOWS:
        _got, book, _dec = _port(window)
        assert book.counters.get("suppress_same_sleeve", 0) == 0, window
        assert book.counters.get("reject_window", 0) == 0, window


#: (mutation, window). The window is part of the case, not an afterthought: a rule can only
#: be shown load-bearing on a window where it actually binds, and each pairing below was
#: chosen by MEASURING which windows the mutation moves rather than by assuming.
#:   same_symbol      moves both windows
#:   stress_displace  moves vault2025 only — vault2026 has Stress entries but none that
#:                    displace anything
#:   nkd_cap          moves vault2026 only — vault2025 has no NKD rejection to free
#:   family_cap       moves both windows
MUTATIONS = [("same_symbol", "vault2026"), ("same_symbol", "vault2025"),
             ("stress_displace", "vault2025"), ("nkd_cap", "vault2026"),
             ("family_cap", "vault2026"), ("family_cap", "vault2025")]


@pytest.mark.parametrize("mutation,window", MUTATIONS)
def test_1d_each_rule_is_load_bearing(monkeypatch, mutation, window):
    """Remove one rule at a time; the ordered stream must change.

    Monkeypatched in-process, never by editing a file on disk. A mutation test that leaves
    the source modified is a mutation test that can leave the source modified.
    """
    anchor, _st, _net = _anchor(window)

    if mutation == "same_symbol":
        monkeypatch.setattr(T, "SAME_SYMBOL_BLOCKERS", {})
    elif mutation == "stress_displace":
        monkeypatch.setattr(T, "STRESS_DISPLACES", ())
    elif mutation == "nkd_cap":
        monkeypatch.setitem(T.CAPS, "global_nkd", (0.60, 0.60))
    else:
        monkeypatch.setattr(T, "family_verdict", lambda *a, **k: (True, ""))

    got, _b, _d = _port(window)
    assert got != anchor, f"{mutation} on {window} changed nothing — the rule is not load-bearing"


def test_1e_the_normal_cluster_cap_is_subsumed_by_the_family_cap():
    """Measured, and it is not a defect — but it must not be a surprise either.

    `cap_roska4_swing` is 5.0% gross / 4.4% net and the Normal+Calm family cap is the SAME
    two numbers over a strictly larger book, so the family constraint is always at least as
    tight. Loosening the Normal cluster cap alone therefore changes nothing, on any window.

    Asserted rather than left as folklore: if the family cap is ever widened (7.5% was one
    of the policies measured), this goes red and tells the next reader that the cluster cap
    has just become load-bearing again.
    """
    from global_index import track1_params as _tp
    assert _tp.CAPS["roska4_swing"] == (_tp.FAMILY_GROSS, _tp.FAMILY_NET)
    assert set(_tp.FAMILY_CLUSTERS) == {"roska4_swing", "roska4_calm"}

    window = "vault2026"
    anchor, _st, _net = _anchor(window)
    old = dict(T.CAPS)
    try:
        T.CAPS["roska4_swing"] = (0.50, 0.44)
        got, _b, _d = _port(window)
    finally:
        T.CAPS.clear()
        T.CAPS.update(old)
    assert got == anchor, ("loosening only the Normal cluster cap moved the stream, so it is "
                           "NOT subsumed — this test's premise has changed")


# ── T2: the same-symbol invariant ────────────────────────────────────────────
def test_2_at_most_one_position_per_instrument_across_every_sleeve():
    book = _fresh_book()
    # Stage 5M-B gave `roska4_swing` a declared window (14:05-15:55), so the route now REFUSES
    # a swing candidate stamped at 10:00 — `reject_window`, before the same-symbol guard is
    # ever consulted. That is the intended new behaviour, and it made this scenario stop
    # testing what it is about. Each candidate is now stamped inside its own sleeve's window;
    # the guard being exercised is unchanged.
    SWING_TS = "2026-03-02 14:05:00"
    order = [
        _cand("roska4_swing", "MNQ", ts=SWING_TS, tid="n1"),
        _cand("roska4_calm", "MNQ", tid="c1"),
        _cand("roska4_swing", "MES", ts=SWING_TS, tid="n2"),
        _cand("roska4_calm", "MES", tid="c2"),
        _cand("global_nkd", "MNKD", ts="2026-03-02 01:10:00", tid="k1"),
    ]
    for c in order:
        book.apply(c.entry_time, book.evaluate(c, allow=True))
    held = [(h.position.instrument, h.position.cluster) for h in book.open_book]
    insts = [i for i, _ in held]
    assert insts, "nothing was admitted at all — the uniqueness check would pass on nothing"
    assert len(insts) == len(set(insts)), held
    assert book.counters["suppress_same_symbol"] == 2, book.counters

    # ...and Stress displaces rather than doubling up.
    st = _cand("roska4_stress", "MNQ", direction="SHORT", qty=7, risk=4000.0,
               ts="2026-03-02 11:00:00", tid="s1")
    d = book.apply(st.entry_time, book.evaluate(st, allow=True),
                   early_exit_value=lambda h, ts: 0.0)
    assert d.taken and len(d.forced_closes) == 1
    held = [(h.position.instrument, h.position.cluster) for h in book.open_book]
    assert ("MNQ", "roska4_stress") in held
    assert ("MNQ", "roska4_swing") not in held
    insts = [i for i, _ in held]
    assert len(insts) == len(set(insts)), held


def test_2b_a_second_position_in_the_same_sleeve_on_the_same_instrument_is_refused():
    book = _fresh_book()
    # Both inside the swing window declared in Stage 5M-B; at 10:00 and 11:00 the route now
    # refuses on the window before the same-sleeve guard is reached.
    a = _cand("roska4_swing", "MES", ts="2026-03-02 14:05:00", tid="a")
    b = _cand("roska4_swing", "MES", ts="2026-03-02 14:10:00", tid="b")
    book.apply(a.entry_time, book.evaluate(a, allow=True))
    d = book.evaluate(b, allow=True)
    assert d.verdict == T.SUPPRESS_SAME_SLEEVE, d


# ── T3: quantity is a property of the candidate ──────────────────────────────
def test_3_mnq_is_one_micro_under_normal_and_seven_under_stress():
    assert tp.SLEEVE_QTY["roska4_swing"] == 1
    assert tp.SLEEVE_QTY["roska4_stress"] == 7

    normal = _cand("roska4_swing", "MNQ", qty=tp.SLEEVE_QTY["roska4_swing"], risk=800.0)
    stress = _cand("roska4_stress", "MNQ", direction="SHORT",
                   qty=tp.SLEEVE_QTY["roska4_stress"], risk=4500.0,
                   ts="2026-03-02 11:00:00")
    assert normal.as_position().contracts == 1
    assert stress.as_position().contracts == 7

    book = _fresh_book()
    book.apply(normal.entry_time, book.evaluate(normal, allow=True))
    d = book.apply(stress.entry_time, book.evaluate(stress, allow=True),
                   early_exit_value=lambda h, ts: 0.0)
    assert d.taken
    held = {h.position.cluster: h.position.contracts for h in book.open_book}
    assert held == {"roska4_stress": 7}, held


def test_3b_the_measured_stress_rows_really_do_carry_seven():
    import scratch.track1_replay_source_20260822 as src
    stress = [c for c in src.candidates("vault2026") if c.sleeve == "roska4_stress"]
    assert stress, "no stress candidates in the window — the assertion would be empty"
    assert {c.qty for c in stress} == {7}, {c.qty for c in stress}
    normal_mnq = [c for c in src.candidates("vault2026")
                  if c.sleeve == "roska4_swing" and c.instrument == "MNQ"]
    assert normal_mnq and {c.qty for c in normal_mnq} == {1}


# ── T4: the SPY short gate is causal at D-1 ──────────────────────────────────
def test_4_spy_short_gate_reads_only_closes_strictly_before_the_decision_day(tmp_path):
    from scratch.directional_market_filter_probe import allowed_short_days, feature_frame

    dates = pd.bdate_range("2024-01-01", periods=140)
    close = pd.Series(range(100, 100 + len(dates)), index=dates, dtype=float)
    csv = tmp_path / "spy.csv"
    pd.DataFrame({"date": dates, "close": close.values}).to_csv(csv, index=False)

    base = allowed_short_days(feature_frame(str(csv)), "below_sma50")

    # Multiply the close AT day D by ten. Causality says: D's own verdict is unchanged,
    # and D+1's may move. Anything else means the gate is reading the future.
    d = dates[120]
    bumped = close.copy()
    bumped.loc[d] = float(bumped.loc[d]) * 10.0
    csv2 = tmp_path / "spy_bumped.csv"
    pd.DataFrame({"date": dates, "close": bumped.values}).to_csv(csv2, index=False)
    after = allowed_short_days(feature_frame(str(csv2)), "below_sma50")

    assert (d in base) == (d in after), "the gate's verdict at D moved when D's own close moved"
    changed = {x for x in dates if (x in base) != (x in after)}
    assert changed, "nothing moved at all — the mutation was too small to prove anything"
    assert min(changed) > d, f"a day at or before D changed: {sorted(changed)[:3]}"


def test_4b_the_gate_identity_travels_with_the_route(tmp_path):
    cfg = tp.sleeve_config("roska4_swing", "MES", regime_csv="spy_daily_live.csv",
                           data_path="data/cache/futures/ES_continuous_1m_8y.parquet",
                           fill_law=NR.NormalR4Params().fill_law)
    assert cfg["spy_short_filter"] == "d1_spy_close_below_sma50_for_shorts_only"
    assert cfg["spy_short_lookback"] == 50
    assert cfg["spy_short_lag_days"] == 1
    assert cfg["spy_short_source_identity"].startswith("spy_daily_live.csv:")
    assert len(cfg["spy_short_source_identity"].split(":")[1]) == 64, "not a full sha256"

    # A different SPY file must move the hash, or the identity is decoration.
    other = tmp_path / "spy_other.csv"
    other.write_text("date,close\n2024-01-02,100\n", encoding="utf-8")
    moved = tp.sleeve_config("roska4_swing", "MES", fill_law=NR.NormalR4Params().fill_law,
                             regime_csv=str(other),
                             data_path="data/cache/futures/ES_continuous_1m_8y.parquet")
    from global_index import route_params as rp
    assert rp.params_hash(cfg) != rp.params_hash(moved)


# ── T5 / T6: the detection windows ───────────────────────────────────────────
def test_5_a_missed_calm_a_is_not_entered_late():
    on_time = _cand("roska4_calm", "MES", ts="2026-03-02 10:00:00")
    late = _cand("roska4_calm", "MES", ts="2026-03-02 10:20:00", tid="late")
    book = _fresh_book()
    assert book.evaluate(on_time, allow=True).verdict == T.TAKE
    d = _fresh_book().evaluate(late, allow=True)
    assert d.verdict == T.REJECT_WINDOW, d
    assert "one-shot" in d.detail


@pytest.mark.parametrize("hhmm,expected", [
    ("10:34", T.REJECT_WINDOW), ("10:35", T.TAKE), ("11:14", T.TAKE),
    ("12:30", T.TAKE), ("12:31", T.REJECT_WINDOW), ("14:05", T.REJECT_WINDOW),
])
def test_6_stress_enters_inside_its_window_and_never_after_it(hhmm, expected):
    c = _cand("roska4_stress", "MNQ", direction="SHORT", qty=7, risk=4000.0,
              ts=f"2026-03-02 {hhmm}:00")
    assert _fresh_book().evaluate(c, allow=True).verdict == expected


def test_6b_the_windows_match_the_ledger_contract():
    from global_index import window_ledger as wl
    assert tp.WINDOWS_ET["roska4_stress"] == (wl.WINDOWS["roska4_stress"]["start_et"],
                                              wl.WINDOWS["roska4_stress"]["end_et"])
    assert tp.WINDOWS_ET["roska4_calm"] == (wl.WINDOWS["roska4_calm"]["start_et"],
                                            wl.WINDOWS["roska4_calm"]["end_et"])


def test_6c_the_window_ledger_records_an_incomplete_window_as_incomplete(tmp_path,
                                                                        monkeypatch):
    from global_index import window_ledger as wl
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("RAITS_ROUTE", tp.ROUTE)
    monkeypatch.setattr(wl, "_disabled", False)
    entry.record_window_observation("roska4_stress", "2026-03-02",
                                    [f"10:{m:02d}" for m in range(35, 60, 5)], entered=False)
    rows = wl.read(sorted(tmp_path.glob("window_coverage_*.jsonl")))
    assert rows, "the ledger wrote nothing"
    status = wl.status(rows, "roska4_stress", "2026-03-02")
    assert status["outcome"] == wl.INCOMPLETE, status
    assert status["usable_as_evidence"] is False
    assert status["observed_slots"] == 5 and status["expected_slots"] == 24
    # and a date nobody watched at all reads as unobserved, not as "no signal"
    assert wl.status(rows, "roska4_stress", "2026-03-03")["outcome"] == wl.UNOBSERVED


# ── T7 / T8: no orders, no legacy writes ─────────────────────────────────────
def test_7_the_default_mode_never_calls_send_order():
    gate = entry.OrderGate(False)
    assert gate.state == entry.OrderGate.SHADOW
    assert gate.allow_orders is False

    broker = entry.NoOrderBroker()
    with pytest.raises(RuntimeError):
        broker.send_order(object())

    summary = entry.run_shadow(window="vault2026", regime_csv="spy_daily_live.csv",
                               now_et=pd.Timestamp("2026-08-21 11:00"),
                               out_dir="scratch/track1_shadow_test")
    assert summary["send_order_calls"] == 0
    assert summary["order_gate"]["allow_orders"] is False


def test_7b_asking_for_orders_is_refused_and_names_what_is_open(monkeypatch):
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    gate = entry.OrderGate(True)
    assert gate.state == entry.OrderGate.REFUSED
    assert gate.allow_orders is False
    assert entry.OPEN_ORDER_BLOCKERS, "the blocker list is empty; the gate would open"
    joined = " ".join(gate.reasons)
    for key in entry.OPEN_ORDER_BLOCKERS:
        assert key in joined

    rc_code = entry.main(["--allow-orders", "--window", "vault2026"])
    assert rc_code == 2

    # Even with the out-of-band approval set, an open blocker still refuses.
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    assert entry.OrderGate(True).allow_orders is False
    # ...and with no blockers AND the approval, it would arm — so the refusal above is the
    # blockers talking, not a switch that can never move.
    assert entry.OrderGate(True, blockers={}).allow_orders is True


def _hash_legacy() -> dict:
    out = {}
    for p in list(entry.LEGACY_PATHS) + sorted(str(x) for x in Path(".").glob("live_day_*.log")):
        f = Path(p)
        out[p] = (f.stat().st_mtime_ns, hashlib.sha256(f.read_bytes()).hexdigest()) \
            if f.exists() else None
    return out


def test_8_a_shadow_run_touches_no_legacy_path():
    before = _hash_legacy()
    assert any(v is not None for v in before.values()), \
        "no legacy artifact exists to protect — the assertion would be empty"
    entry.run_shadow(window="vault2026", regime_csv="spy_daily_live.csv",
                     now_et=pd.Timestamp("2026-08-21 11:00"),
                     out_dir="scratch/track1_shadow_test")
    after = _hash_legacy()
    assert after == before, {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert set(after) >= set(before), "a live_day_*.log appeared that did not exist before"


def test_8c_persisting_the_book_writes_the_route_path_and_never_legacy(tmp_path):
    """The route's book must be writable, and writing it must land on the ROUTE's file.

    Declaring a path and never writing it proves nothing about isolation, so this exercises
    the write and then checks both ends: the route file gained the carried state, and every
    legacy artifact is byte-identical.
    """
    before = _hash_legacy()
    target = tmp_path / "live_positions.track1.json"
    summary = entry.run_shadow(window="vault2026", regime_csv="spy_daily_live.csv",
                               now_et=pd.Timestamp("2026-08-21 11:00"),
                               out_dir=str(tmp_path / "shadow"),
                               persist_book=True, positions_path=str(target))
    assert target.exists(), "persist_book was requested and nothing was written"
    state = json.loads(target.read_text(encoding="utf-8"))
    assert state["route"] == tp.ROUTE
    # The values Stage 2C proved load-bearing all have to be there, or a resume from this
    # file would rebuild a book whose breaker starts from the wrong peak.
    for key in ("equity", "peak_equity", "day_start_equity", "cur_day", "positions"):
        assert key in state, key
    assert summary["book_persisted_to"] == str(target)
    assert _hash_legacy() == before
    assert not Path(entry.POSITIONS_PATH).exists(), \
        "the default route path was written even though the test redirected it"


def test_8b_the_route_state_paths_are_all_route_scoped():
    for p in (entry.POSITIONS_PATH, entry.LOCK_PATH, entry.CHECKPOINT_PATH, entry.STOP_FILE):
        assert "track1" in p, p
    assert set(entry.LEGACY_PATHS).isdisjoint(
        {entry.POSITIONS_PATH, entry.LOCK_PATH, entry.CHECKPOINT_PATH, entry.STOP_FILE})


# ── T9: checkpoint refusals surface as codes ─────────────────────────────────
def test_9_checkpoint_refusals_reach_the_entry_point_as_codes():
    rows = entry.checkpoint_report(regime_csv="spy_daily_live.csv",
                                   data_paths=entry.default_data_paths())
    assert rows, "no cross-day sleeve was reported"
    assert {r["code"] for r in rows} <= set(rc.REASON_CODES) | {"params_ok_frame_not_loaded"}
    assert all(r["params_hash"].startswith("sha256:") for r in rows)

    # Against the Stage 2B bootstrap the Normal sleeve must refuse with PARAMS_MISMATCH:
    # that file was seeded under the LEGACY engine identity and Track 1's Normal is a
    # different engine. This is the mechanism working, not a bug to be tuned away.
    boot = Path("scratch/replay_checkpoint.track1.bootstrap_20260822.json")
    if boot.exists():
        rows2 = entry.checkpoint_report(regime_csv="spy_daily_live.csv",
                                        data_paths=entry.default_data_paths(),
                                        path=str(boot))
        swing = [r for r in rows2 if r["sleeve"] == "roska4_swing"]
        assert swing and all(r["code"] == rc.PARAMS_MISMATCH for r in swing), swing
        assert all("stored=" in r["detail"] for r in swing)


def test_9b_every_declared_param_field_has_a_source_and_none_is_unsourced():
    audit = tp.audit_sources()
    assert audit["missing_source"] == []
    assert audit["source_for_unknown_field"] == []
    assert audit["unsourced"] == []
    assert tp.DECIDED_BY_MEASUREMENT, "a settled conflict must still name its evidence"
    for field, why in tp.DECIDED_BY_MEASUREMENT.items():
        assert len(why) > 40, field


# ── T10: the switch primitive ────────────────────────────────────────────────
class _FakeBroker:
    def __init__(self, *, cancel_ok=True, close_status="FILLED", open_status="FILLED"):
        self.cancel_ok = cancel_ok
        self.close_status = close_status
        self.open_status = open_status
        self.sent: list = []
        self.cancelled: list = []

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return self.cancel_ok

    def send_order(self, order):
        self.sent.append(order)
        status = self.close_status if order.action == "CLOSE" else self.open_status
        return Fill(order.inst, order.action, order.direction, order.contracts,
                    order.cluster, status=status, avg_price=100.0)


CLOSE_LEG = sw.Leg("MNQ", "CLOSE", "LONG", 1, "roska4_swing", contract_month="202609")
OPEN_LEG = sw.Leg("MNQ", "OPEN", "SHORT", 7, "roska4_stress")


def test_10_the_default_is_no_orders_and_nothing_is_placed():
    b = _FakeBroker()
    r = sw.close_then_open(b, close_leg=CLOSE_LEG, open_leg=OPEN_LEG,
                           ref_day=pd.Timestamp("2026-03-02"), stop_order_id="9")
    assert r.ok is False and r.stage == sw.REQUESTED
    assert b.sent == [] and b.cancelled == []


def test_10b_the_second_leg_is_never_placed_when_the_close_does_not_fill():
    for status in ("FAILED", "CANCELLED", "PARTIAL"):
        b = _FakeBroker(close_status=status)
        r = sw.close_then_open(b, close_leg=CLOSE_LEG, open_leg=OPEN_LEG,
                               ref_day=pd.Timestamp("2026-03-02"), stop_order_id="9",
                               allow_orders=True)
        assert r.ok is False and r.stage == sw.CLOSE_FAILED, status
        actions = [o.action for o in b.sent]
        assert actions == ["CLOSE"], f"{status}: an OPEN went out anyway: {actions}"


def test_10c_a_failed_stop_cancel_aborts_before_anything_is_closed():
    b = _FakeBroker(cancel_ok=False)
    r = sw.close_then_open(b, close_leg=CLOSE_LEG, open_leg=OPEN_LEG,
                           ref_day=pd.Timestamp("2026-03-02"), stop_order_id="9",
                           allow_orders=True)
    assert r.ok is False and r.stage == sw.STOP_CANCEL_FAILED
    assert b.sent == [], "the position was closed while its stop was still working"


def test_10d_a_failed_open_after_a_filled_close_records_that_the_account_is_flat():
    b = _FakeBroker(open_status="CANCELLED")
    persisted = []
    r = sw.close_then_open(b, close_leg=CLOSE_LEG, open_leg=OPEN_LEG,
                           ref_day=pd.Timestamp("2026-03-02"), stop_order_id="9",
                           allow_orders=True, persist_flat=lambda: persisted.append(True))
    assert r.ok is False and r.stage == sw.OPEN_FAILED_FLAT
    assert r.account_flat is True
    assert persisted == [True], "the book was not told the account is flat"
    assert [o.action for o in b.sent] == ["CLOSE", "OPEN"]


def test_10e_the_happy_path_opens_seven_and_emits_every_stage_in_order():
    b = _FakeBroker()
    r = sw.close_then_open(b, close_leg=CLOSE_LEG, open_leg=OPEN_LEG,
                           ref_day=pd.Timestamp("2026-03-02"), stop_order_id="9",
                           allow_orders=True)
    assert r.ok and r.opened
    assert [o.action for o in b.sent] == ["CLOSE", "OPEN"]
    assert b.sent[1].contracts == 7
    stages = [e["stage"] for e in r.events]
    assert stages == [sw.REQUESTED, sw.STOP_CANCEL, sw.CLOSE_PLACED, sw.CLOSE_FILLED,
                      sw.OPEN_PLACED, sw.OPEN_FILLED], stages


def test_10f_a_cross_symbol_switch_is_refused():
    b = _FakeBroker()
    r = sw.close_then_open(b, close_leg=CLOSE_LEG,
                           open_leg=sw.Leg("MES", "OPEN", "SHORT", 7, "roska4_stress"),
                           ref_day=pd.Timestamp("2026-03-02"), allow_orders=True)
    assert r.ok is False and b.sent == []


# ── T11: the freshness gate fails closed ─────────────────────────────────────
def test_11_the_freshness_gate_refuses_on_stale_missing_and_unreadable(tmp_path):
    now = pd.Timestamp("2026-08-21 11:00")          # before 13:45 ET -> requires 2026-08-20
    assert fresh.required_data_through(now) == pd.Timestamp("2026-08-20")
    assert fresh.required_data_through(pd.Timestamp("2026-08-21 14:00")) == \
        pd.Timestamp("2026-08-21")
    # Monday morning must reach back over the weekend, not to Sunday.
    assert fresh.required_data_through(pd.Timestamp("2026-08-24 09:00")) == \
        pd.Timestamp("2026-08-21")

    state = tmp_path / "preflight.json"
    state.write_text(json.dumps({"2026-08-20": True}), encoding="utf-8")
    csv = tmp_path / "spy.csv"
    pd.DataFrame({"date": pd.bdate_range("2026-08-01", "2026-08-20"),
                  "close": 1.0}).to_csv(csv, index=False)

    good = fresh.evaluate(now_et=now, regime_csv=str(csv), parquets={},
                          preflight_state=str(state))
    assert good.allow is True
    assert "intraday_source" in good.unverified, \
        "the gate claimed to have checked something it cannot see"

    stale_csv = tmp_path / "spy_stale.csv"
    pd.DataFrame({"date": pd.bdate_range("2026-08-01", "2026-08-14"),
                  "close": 1.0}).to_csv(stale_csv, index=False)
    assert fresh.evaluate(now_et=now, regime_csv=str(stale_csv), parquets={},
                          preflight_state=str(state)).allow is False

    assert fresh.evaluate(now_et=now, regime_csv=str(tmp_path / "nope.csv"), parquets={},
                          preflight_state=str(state)).allow is False

    no_record = tmp_path / "empty.json"
    no_record.write_text("{}", encoding="utf-8")
    v = fresh.evaluate(now_et=now, regime_csv=str(csv), parquets={},
                       preflight_state=str(no_record))
    assert v.allow is False and "preflight_record" in " ".join(v.reasons)

    failed = tmp_path / "failed.json"
    failed.write_text(json.dumps({"2026-08-20": False}), encoding="utf-8")
    assert fresh.evaluate(now_et=now, regime_csv=str(csv), parquets={},
                          preflight_state=str(failed)).allow is False


def test_11b_a_missing_file_identity_can_never_match_a_recorded_one():
    missing = tp.file_identity("does/not/exist.parquet")
    assert missing.endswith(":MISSING")
    real = tp.file_identity("spy_daily_live.csv")
    assert real != missing and len(real.split(":")[1]) == 64


# ── T12: the live source refuses, and says what is missing ───────────────────
def test_12_the_live_sleeve_source_refuses_and_names_what_is_actually_left():
    """The refusal must name every sleeve, and must not name anything already solved.

    This test used to pin the string `model_sameday_stop`, which was honest when the Normal
    sleeve lived in a root-level script. Stage 4 promoted it into the package and Stage 4C
    wired the bars in, so a list still naming it would be describing a problem that no longer
    exists — and a prerequisite list nobody trusts is a list nobody reads. The pin therefore
    moved from one literal to the property that made the literal worth pinning: the list is
    non-empty, it covers all four sleeves, and nothing on it has since been built.
    """
    from global_index import track1_sleeves as ts
    src = ts.load_source("live")
    with pytest.raises(NotImplementedError) as exc:
        src.candidates("today")
    msg = str(exc.value)
    for sleeve in ("roska4_swing", "roska4_calm", "roska4_stress", "global_nkd"):
        assert sleeve in msg
    assert all(ts.LIVE_SOURCE_PREREQUISITES[s] for s in ts.LIVE_SOURCE_PREREQUISITES)

    solved = ("model_sameday_stop", "scratch/harness", "force_all_bars_gappable",
              "normal_promotion_filter_lib", "directional_market_filter_probe",
              "calm_a_disaster_stop_probe")
    stale = [(s, item) for s, items in ts.LIVE_SOURCE_PREREQUISITES.items()
             for item in items for name in solved if name in item]
    assert not stale, f"the prerequisite list still names work that is done: {stale}"
