"""scratch/test_track1_stage4b_identity_liveframe_20260823.py — the Stage 4B gate.

    python -m pytest scratch/test_track1_stage4b_identity_liveframe_20260823.py -q

Offline. No scheduler started, no IBKR, no order, no dashboard write, no network.

Two caveats are under test:

  1. **fill-law identity.** The route used to declare `production_gap_after_15min_break` while
     every measured row had been generated with every bar gap-eligible. The P&L difference is
     immaterial; the identity was still false, and an identity is what a checkpoint is accepted
     on. It is now an argument with no default.
  2. **the live-frame splice.** Every reproduction so far ran on historical frames. This repo
     has already paid for a live splice: 1,050 of 1,590 NKD bars overwrote frozen history with
     a 13-hour clock offset, silently.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes  # noqa: E402
from futures.swing_tf import costs_for_basket  # noqa: E402
from global_index import route_checkpoint as rc  # noqa: E402
from global_index import track1_bootstrap as boot  # noqa: E402
from global_index import track1_calm_a as CA  # noqa: E402
from global_index import track1_gates as g  # noqa: E402
from global_index import track1_intraday as intra  # noqa: E402
from global_index import track1_live_frame as LF  # noqa: E402
from global_index import track1_normal_r4 as NR  # noqa: E402
from global_index import track1_params as tp  # noqa: E402
from scratch.normal_promotion_variant_matrix_20260821 import load_frames  # noqa: E402

WINDOW = "vault2026"
_CACHE: dict = {}


def _committed():
    return json.loads(Path(f"scratch/normal_promotion_trades_{WINDOW}_20260821.json")
                      .read_text(encoding="utf-8"))


def _frames():
    if "f" not in _CACHE:
        _CACHE["f"] = load_frames(_committed())
    return _CACHE["f"]


def _labels():
    if "l" not in _CACHE:
        argv = _committed()["argv"]
        fit = argv[argv.index("--hmm-fit-end") + 1]
        lab = label_regimes(benchmark_daily("spy_daily_live.csv"), "2018-01-01", 3, fit)
        _CACHE["l"] = {pd.Timestamp(k).normalize(): v for k, v in lab.items()}
    return _CACHE["l"]


def _slice(inst: str, lo: str, hi: str):
    df = _frames()[inst]
    idx = df.index
    return df[(idx >= pd.Timestamp(lo).tz_localize(idx.tz))
              & (idx <= pd.Timestamp(hi).tz_localize(idx.tz))]


# ══════════════════════════════════════════════════════════════════════════════
# 1. fill-law identity
# ══════════════════════════════════════════════════════════════════════════════
def test_identity_moves_with_the_fill_law():
    kw = dict(regime_csv="spy_daily_live.csv", data_path="data/x.parquet")
    a = tp.sleeve_identity("roska4_swing", "MES", fill_law=tp.FILL_ARTIFACT, **kw)
    b = tp.sleeve_identity("roska4_swing", "MES", fill_law=tp.FILL_PRODUCTION, **kw)
    assert a[1] != b[1], "the two laws hash the same — the identity cannot tell them apart"
    assert tp.FILL_ARTIFACT in a[0] and tp.FILL_PRODUCTION in b[0]


def test_the_fill_law_has_no_default_and_no_third_value():
    """A default is a default that gets taken. The defect was a fill law nobody passed."""
    kw = dict(regime_csv="spy_daily_live.csv", data_path="data/x.parquet")
    with pytest.raises(TypeError):
        tp.sleeve_config("roska4_swing", "MES", **kw)
    with pytest.raises(ValueError):
        tp.sleeve_config("roska4_swing", "MES", fill_law="whatever_is_convenient", **kw)
    with pytest.raises(ValueError):
        NR.NormalR4Params(fill_law="whatever_is_convenient")


def test_the_route_declares_the_law_its_sleeve_actually_runs():
    """One source, not two. The literal that was wrong got that way by being a second copy."""
    assert set(tp.FILL_LAWS) == set(NR.FILL_LAWS)
    assert tp.FILL_ARTIFACT == NR.FILL_ARTIFACT
    assert tp.FILL_PRODUCTION == NR.FILL_PRODUCTION

    from global_index import run_live_day_track1 as entry
    law = NR.NormalR4Params().fill_law
    rows = entry.checkpoint_report(regime_csv="spy_daily_live.csv",
                                   data_paths=entry.default_data_paths())
    expected = tp.sleeve_identity("roska4_swing", "MES", regime_csv="spy_daily_live.csv",
                                  data_path=entry.default_data_paths()["MES"],
                                  fill_law=law)[1]
    mes = next(r for r in rows if r["sleeve"] == "roska4_swing" and r["inst"] == "MES")
    assert mes["params_hash"] == expected, \
        "the entry point reports an identity built from a different law than the sleeve runs"


def _tiny_checkpoint(tmp_path, law):
    """A schema-2 checkpoint written under `law`, with small synthetic frames.

    Synthetic because the fingerprint is computed over whatever frame both sides are handed,
    so the mechanism under test — identity acceptance and refusal — is exercised without
    spending minutes reading eight years of bars.
    """
    idx = pd.date_range("2026-03-25", periods=40, freq="5min", tz="America/New_York")
    frames, paths = {}, {}
    for inst in ("MES", "MNQ", "MYM", "M2K", "MNKD"):
        frames[inst] = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                                     "volume": 1.0}, index=idx)
        f = tmp_path / f"{inst}.parquet"
        f.write_bytes(inst.encode())
        paths[inst] = str(f)
    state = {"schema_version": 2, "route": tp.ROUTE, "window": WINDOW,
             "cut_instant": "2026-03-31 11:14:00-04:00", "equity": 50000.0,
             "cur_day": "2026-03-31", "peak_equity": 50000.0, "day_start_equity": 50000.0,
             "positions": [], "booked_counter": {}, "counters": {}}
    entries = boot.checkpoint_entries(state, frames=frames, regime_csv="spy_daily_live.csv",
                                      data_paths=paths, fill_law=law)
    ck = tmp_path / "replay_checkpoint.track1.json"
    boot.write(state, entries=entries, book_path=str(tmp_path / "book.json"),
               checkpoint_path=str(ck))
    return str(ck), frames, paths


def test_a_checkpoint_is_accepted_only_under_the_law_it_was_written_with(tmp_path):
    ck, frames, paths = _tiny_checkpoint(tmp_path, tp.FILL_ARTIFACT)

    same = boot.accepts(ck, sleeve="roska4_swing", inst="MES", frame=frames["MES"],
                        regime_csv="spy_daily_live.csv", data_path=paths["MES"],
                        fill_law=tp.FILL_ARTIFACT)
    assert bool(same) is True, getattr(same, "detail", "")

    other = boot.accepts(ck, sleeve="roska4_swing", inst="MES", frame=frames["MES"],
                         regime_csv="spy_daily_live.csv", data_path=paths["MES"],
                         fill_law=tp.FILL_PRODUCTION)
    assert bool(other) is False, "a production-law run accepted an artifact-law checkpoint"
    assert other.code == rc.PARAMS_MISMATCH
    assert "stored=" in other.detail and "caller=" in other.detail

    # ...and the other way round, so the refusal is about disagreement rather than about one
    # particular law being unwelcome.
    other_dir = tmp_path / "b"
    other_dir.mkdir()
    ck2, frames2, paths2 = _tiny_checkpoint(other_dir, tp.FILL_PRODUCTION)
    back = boot.accepts(ck2, sleeve="roska4_swing", inst="MES", frame=frames2["MES"],
                        regime_csv="spy_daily_live.csv", data_path=paths2["MES"],
                        fill_law=tp.FILL_ARTIFACT)
    assert bool(back) is False and back.code == rc.PARAMS_MISMATCH


def test_the_written_checkpoint_carries_the_law_in_its_readable_params(tmp_path):
    ck, _f, _p = _tiny_checkpoint(tmp_path, tp.FILL_ARTIFACT)
    payload = rc.load(ck)
    entry = rc.get_entry(payload, tp.ROUTE, "roska4_swing", "MES")
    assert entry, "no entry was written"
    assert f"fill_law={tp.FILL_ARTIFACT}" in entry["params"], entry["params"]
    assert tp.FILL_PRODUCTION not in entry["params"]


def test_the_stage2b_bootstrap_is_still_refused():
    """The old file predates all of this and must stay refused, whichever law is asked for."""
    old = Path("scratch/replay_checkpoint.track1.bootstrap_20260822.json")
    if not old.exists():
        pytest.skip("the Stage 2B bootstrap is not on disk")
    from global_index import run_live_day_track1 as entry
    for law in tp.FILL_LAWS:
        rows = entry.checkpoint_report(regime_csv="spy_daily_live.csv",
                                       data_paths=entry.default_data_paths(),
                                       path=str(old), fill_law=law)
        swing = [r for r in rows if r["sleeve"] == "roska4_swing"]
        assert swing and all(r["code"] == rc.PARAMS_MISMATCH for r in swing), (law, swing)


def test_the_measured_delta_between_the_laws_is_small_but_not_claimed_to_be_zero():
    """Pinned from `scratch/_stage4b_fill_law_delta.json`, which this stage produced.

    The point is not the size. It is that the two laws produce DIFFERENT rows, so an identity
    that names the wrong one is naming a different dataset — which is why "immaterial P&L" was
    never an argument for leaving the literal alone.
    """
    p = Path("scratch/_stage4b_fill_law_delta.json")
    if not p.exists():
        pytest.skip("the delta measurement has not been run")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d, "the measurement file is empty"
    any_diff = False
    for window, rec in d.items():
        for inst, per in rec["per_inst"].items():
            if not per["identical"]:
                any_diff = True
                assert per["rows_differing"] > 0
        assert abs(rec["sleeve_pnl_delta"]) < 500, (window, rec["sleeve_pnl_delta"])
    assert any_diff, ("no instrument differed under the two laws on any measured window — "
                      "then the identity distinction would be untestable, and this test "
                      "would be asserting nothing")


# ══════════════════════════════════════════════════════════════════════════════
# 2. the live-frame splice
# ══════════════════════════════════════════════════════════════════════════════
def test_splice_round_trip_reproduces_the_original_frame_exactly():
    df = _slice("MES", "2026-02-02", "2026-02-27")
    assert len(df) > 5000
    frozen, live = LF.cut(df, df.index[int(len(df) * 0.8)])
    assert len(frozen) and len(live)
    out, rep = LF.splice(frozen, live)
    assert rep.code == LF.OK
    assert out.index.equals(df.index)
    assert out.equals(df), "the reconstructed frame is not the original"
    assert rep.live_rows_appended == len(live)


def test_the_frozen_half_is_never_modified():
    df = _slice("MES", "2026-02-02", "2026-02-27")
    frozen, live = LF.cut(df, df.index[int(len(df) * 0.6)])
    before = frozen.copy(deep=True)
    out, _rep = LF.splice(frozen, live)
    assert frozen.equals(before), "splice mutated the frame it was handed"
    assert out.iloc[:len(frozen)].equals(before)


def test_an_overlapping_live_half_is_trimmed_and_cannot_rewrite_history():
    """The direction that matters: a live bar carrying a timestamp history already owns must
    not win. It is dropped, never applied."""
    df = _slice("MES", "2026-02-02", "2026-02-27")
    frozen, live = LF.cut(df, df.index[int(len(df) * 0.6)])
    overlap = df.iloc[int(len(df) * 0.4):].copy()
    overlap["close"] = overlap["close"] + 999.0          # a wrong price on old timestamps
    out, rep = LF.splice(frozen, overlap)
    assert LF.OVERLAP_TRIMMED in rep.notices
    assert out.iloc[:len(frozen)].equals(frozen), "the corrupted overlap reached history"
    assert out.equals(pd.concat([frozen, overlap[overlap.index > frozen.index[-1]]]))


def test_the_nkd_thirteen_hour_clock_offset_is_refused():
    """The incident this module exists for.

    1,050 of 1,590 live NKD bars once overwrote frozen history because the live half arrived on
    the ET wall clock and the frozen half was carried on Tokyo's. Every check that existed
    passed: the result was the right length and monotonic. This one does not pass.
    """
    df = _slice("MNQ", "2026-02-02", "2026-02-20")
    frozen_jst = df.copy()
    frozen_jst.index = df.index.tz_convert("Asia/Tokyo")
    _f, live_et = LF.cut(df, df.index[int(len(df) * 0.7)])          # still on ET

    with pytest.raises(LF.SpliceRefused) as exc:
        LF.splice(frozen_jst, live_et)
    assert exc.value.code == LF.TZ_MISMATCH
    assert "Tokyo" in str(exc.value) or "13-hour" in str(exc.value)

    # And the naive version of the same mistake — both sides tz-stripped, so the clocks are
    # silently different — is caught by the overlap rule instead of corrupting history.
    a = frozen_jst.copy(); a.index = a.index.tz_localize(None)
    b = live_et.copy(); b.index = b.index.tz_localize(None)
    out, rep = LF.splice(a, b)
    assert out.iloc[:len(a)].equals(a), "tz-stripped live bars rewrote frozen history"
    assert rep.live_rows_appended < len(b) or rep.code == LF.NOTHING_NEW


@pytest.mark.parametrize("case,code", [
    ("dup_live", LF.DUPLICATE_TIMESTAMPS),
    ("dup_frozen", LF.DUPLICATE_TIMESTAMPS),
    ("unsorted_live", LF.OUT_OF_ORDER),
    ("columns", LF.COLUMN_MISMATCH),
    ("empty_frozen", LF.EMPTY_FROZEN),
    ("not_a_frame", LF.NOT_A_FRAME),
])
def test_splice_refuses_every_way_the_join_can_be_wrong(case, code):
    df = _slice("MES", "2026-02-02", "2026-02-10")
    frozen, live = LF.cut(df, df.index[int(len(df) * 0.7)])
    if case == "dup_live":
        live = pd.concat([live, live.iloc[[-1]]]).sort_index()
    elif case == "dup_frozen":
        frozen = pd.concat([frozen, frozen.iloc[[-1]]]).sort_index()
    elif case == "unsorted_live":
        live = live.iloc[list(range(len(live) - 2)) + [len(live) - 1, len(live) - 2]]
    elif case == "columns":
        live = live.drop(columns=["volume"])
    elif case == "empty_frozen":
        frozen = frozen.iloc[0:0]
    elif case == "not_a_frame":
        live = 42
    with pytest.raises(LF.SpliceRefused) as exc:
        LF.splice(frozen, live)
    assert exc.value.code == code, (case, exc.value.code)


def test_no_live_bars_is_not_an_error():
    df = _slice("MES", "2026-02-02", "2026-02-10")
    out, rep = LF.splice(df, None)
    assert out.equals(df) and rep.code == LF.NOTHING_NEW
    out, rep = LF.splice(df, df.iloc[0:0])
    assert out.equals(df) and rep.code == LF.NOTHING_NEW


# ── the property that matters: same decisions on a spliced frame ─────────────
def test_normal_r4_makes_the_same_decisions_on_a_spliced_frame():
    """Cut a real frame, hand the tail back as 'live', and the sleeve must decide identically.

    This is the check that would have caught the NKD incident, because a tail on a different
    clock does not reconstruct.
    """
    df = _slice("MES", "2026-01-02", "2026-04-30")
    lab, cost = _labels(), costs_for_basket(slippage_ticks=2.0)["MES"]
    p = NR.NormalR4Params()
    short = NR.short_days_from_csv("spy_daily_live.csv")

    base, _s = NR.run_instrument(df, lab, cost, p, short_days=short)
    assert base, "the historical run produced no trades — the comparison would be empty"

    frozen, live = LF.cut(df, df.index[int(len(df) * 0.75)])
    spliced, rep = LF.splice(frozen, live)
    assert rep.code == LF.OK and rep.live_rows_appended > 0
    got, _s2 = NR.run_instrument(spliced, lab, cost, p, short_days=short)

    keys = ("day", "exit_day", "direction", "entry", "exit", "pnl")
    a = [tuple(str(t[k]) for k in keys) for t in base]
    b = [tuple(str(t[k]) for k in keys) for t in got]
    first = next((i for i in range(max(len(a), len(b)))
                  if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)), None)
    assert first is None, (f"first divergence at {first}",
                           a[first] if first is not None and first < len(a) else None,
                           b[first] if first is not None and first < len(b) else None)


def test_the_nikkei_sleeve_makes_the_same_decisions_on_a_spliced_frame():
    """The instrument the incident actually happened to.

    Every other equivalence check here runs on the S&P frame. That is the wrong place to stop:
    the frame that got corrupted was the Nikkei one, it is the frame carried on a different
    wall clock from the feed that updates it, and it runs a different engine — ema 10 on
    lagged labels, no context filter. A guard proven only on the instrument that never broke
    is a guard proven in the easy place.
    """
    from global_index.regime import RegimeLabels
    from global_index import specs as gi_specs
    from global_index._core import FuturesCost as GIFC

    inst = _committed()["nkd_instrument"]
    df = _frames()[inst]
    assert len(df) > 5000, (inst, len(df))

    lab = RegimeLabels(pd.Series(_labels()).sort_index(), lag_days=1)
    c = gi_specs.SPECS[inst]
    cost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                slippage_ticks_per_side=2.0)
    p = NR.NormalR4Params(ema_period=10)
    short = NR.short_days_from_csv("spy_daily_live.csv")

    base, _s = NR.run_instrument(df, lab, cost, p, short_days=short,
                                 apply_context_filter=False)
    assert base, "the historical Nikkei run produced no trades — nothing would be compared"

    frozen, live = LF.cut(df, df.index[int(len(df) * 0.75)])
    spliced, rep = LF.splice(frozen, live)
    assert rep.code == LF.OK and rep.live_rows_appended > 0
    assert len(spliced) == len(df), (len(spliced), len(df))

    got, _s2 = NR.run_instrument(spliced, lab, cost, p, short_days=short,
                                 apply_context_filter=False)
    keys = ("day", "exit_day", "direction", "entry", "exit", "pnl")
    a = [tuple(str(t[k]) for k in keys) for t in base]
    b = [tuple(str(t[k]) for k in keys) for t in got]
    first = next((i for i in range(max(len(a), len(b)))
                  if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)), None)
    assert first is None, (f"first divergence at {first}",
                           a[first] if first is not None and first < len(a) else None,
                           b[first] if first is not None and first < len(b) else None)


def test_calm_a_makes_the_same_decisions_on_a_spliced_frame():
    df = _slice("MES", "2026-01-02", "2026-05-29")
    lab = _labels()
    base = CA.detect(df, lab, "MES")
    assert base, "no Calm A setups in the slice — the comparison would be empty"

    frozen, live = LF.cut(df, df.index[int(len(df) * 0.75)])
    spliced, rep = LF.splice(frozen, live)
    assert rep.code == LF.OK
    got = CA.detect(spliced, lab, "MES")

    def key(s):
        return (str(s.day.date()), s.direction, round(float(s.entry), 4),
                round(float(s.exit), 4), str(s.prev_session_day.date()))
    assert [key(s) for s in got] == [key(s) for s in base]


def test_a_partial_current_session_yields_no_setup_for_that_day_rather_than_a_wrong_one():
    """Calm A's day needs its 10:00 AND 15:55 bars. A session cut before 15:55 must simply not
    produce that day — not produce it at a substituted price."""
    df = _slice("MES", "2026-01-02", "2026-03-31")
    lab = _labels()
    full = {str(s.day.date()) for s in CA.detect(df, lab, "MES")}
    assert full

    last_day = pd.DatetimeIndex(df.index).tz_convert(None).normalize().max()
    cut_at = pd.Timestamp(last_day) + pd.Timedelta(hours=12)
    frozen, _live = LF.cut(df, cut_at.tz_localize(df.index.tz))
    partial = {str(s.day.date()) for s in CA.detect(frozen, lab, "MES")}
    assert str(last_day.date()) not in partial, \
        "a session truncated before 15:55 still produced a setup"
    assert partial <= full


# ── the per-sleeve intraday requirements, on a spliced frame ─────────────────
def _calm_quote(day):
    """Stage 5ZU: Calm prices its entry on a ONE-MINUTE bar, and the gate reports UNVERIFIED
    rather than a pass when nobody says where that price is read from."""
    return pd.date_range(day + pd.Timedelta(hours=9, minutes=30),
                         day + pd.Timedelta(hours=10), freq="1min")


def test_calm_a_intraday_gate_on_a_spliced_frame():
    day, prior = pd.Timestamp("2026-03-02"), pd.Timestamp("2026-02-27")
    frozen = intra.synth_bars(prior, "09:30", "16:00")
    live = intra.synth_bars(day, "09:30", "10:00")
    spliced, rep = LF.splice(frozen, live)
    assert rep.code == LF.OK
    v = intra.validate("roska4_calm", spliced, now_et=day + pd.Timedelta(hours=10),
                       session_day=day, prior_session_day=prior,
                       entry_quote_index=_calm_quote(day))
    assert v.allow, v.as_dict()

    short = intra.synth_bars(day, "09:30", "09:50")
    spliced2, _ = LF.splice(frozen, short)
    v2 = intra.validate("roska4_calm", spliced2, now_et=day + pd.Timedelta(hours=10),
                        session_day=day, prior_session_day=prior,
                        entry_quote_index=_calm_quote(day))
    # Stage 5ZU. This asserted `decision_bar_absent`, a code Calm no longer emits: the
    # decision no longer waits for the 10:00 bar to close. The frame here stops short of the
    # DECISION span, so it refuses for that — which is the same claim (a short frame is
    # refused) said in the terms the contract now uses.
    assert not v2.allow
    assert intra.PARTIAL_COVERAGE in v2.codes or intra.STALE in v2.codes


def test_stress_intraday_gate_on_a_spliced_frame():
    day = pd.Timestamp("2026-03-02")
    frozen = intra.synth_bars(pd.Timestamp("2026-02-27"), "09:30", "16:00")
    live = intra.synth_bars(day, "09:30", "12:30")
    spliced, rep = LF.splice(frozen, live)
    assert rep.code == LF.OK
    ok_ledger = {"outcome": "complete", "observed_slots": 24, "expected_slots": 24}
    v = intra.validate("roska4_stress", spliced, now_et=day + pd.Timedelta(hours=11),
                       session_day=day, ledger_status=ok_ledger)
    assert v.allow, v.as_dict()

    # detector window incomplete -> refused
    thin = intra.synth_bars(day, "09:30", "10:00")
    s2, _ = LF.splice(frozen, thin)
    v2 = intra.validate("roska4_stress", s2, now_et=day + pd.Timedelta(hours=11),
                        session_day=day, ledger_status=ok_ledger)
    assert not v2.allow and intra.PARTIAL_COVERAGE in v2.codes

    # window not observed -> refused even with a complete frame
    v3 = intra.validate("roska4_stress", spliced, now_et=day + pd.Timedelta(hours=11),
                        session_day=day,
                        ledger_status={"outcome": "incomplete", "observed_slots": 9,
                                       "expected_slots": 24})
    assert not v3.allow and intra.WINDOW_UNOBSERVED in v3.codes


# ══════════════════════════════════════════════════════════════════════════════
# 3. gates
# ══════════════════════════════════════════════════════════════════════════════
def test_the_registry_is_structurally_sound_and_the_ledger_agrees():
    assert g.self_check() == []
    on_disk = json.loads(
        Path("scratch/track1_blocking_ledger_20260822.json").read_text(encoding="utf-8"))
    assert on_disk == g.as_ledger(), "the ledger on disk and the registry disagree"


def test_the_order_gate_reflects_the_true_remaining_blockers(monkeypatch):
    from global_index import run_live_day_track1 as entry
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    gate = entry.OrderGate(True)
    assert gate.allow_orders is False
    reported = set(gate.blockers)
    assert reported == {b.id for b in g.blocking()}, reported
    assert not Path(g.CONFIRMATION_PATH).exists()


def test_no_blocker_is_closed_without_evidence():
    for b in g.BLOCKERS.values():
        if b.status == g.CLOSED:
            assert not b.blocks_orders
            assert len(b.evidence) > 80, b.id
        else:
            assert b.blocks_orders and b.decision_needed, b.id
            assert b.released_by or b.released_by_measurement, b.id


def test_the_live_frame_gate_cannot_be_opened_by_a_signature(monkeypatch):
    """The reason it is a MEASURED_GATE and not a decision gate.

    Stage 4C released this gate by building the path, so the assertion had to be rewritten to
    keep testing the thing that matters. It now HOLDS the measurement shut and then grants
    every confirmation flag the file accepts — the most permissive state a signed file can
    express — and requires the gate to stay closed anyway. Written the other way it would
    have passed for the wrong reason from now on, which is worse than failing.
    """
    b = g.BLOCKERS["LIVE_FRAME_ADAPTER_VERIFICATION"]
    assert b.status == g.MEASURED_GATE and b.blocks_orders
    assert b.released_by == (), "a flag can release it — then it is prose with extra steps"

    monkeypatch.setitem(g.MEASUREMENTS, "live_frame_wiring",
                        lambda root="": (False, "held shut for this test"))
    everything = g.Confirmations({f: True for f in g.CONFIRMATION_FLAGS},
                                 "nobody", "2026-08-23", "(synthetic)")
    still = {x.id for x in g.blocking(everything)}
    assert still == {"LIVE_FRAME_ADAPTER_VERIFICATION"}, still
    assert g.may_enable_orders(everything)[0] is False


def _fake_route(root, sleeves_src: str):
    root.mkdir(parents=True, exist_ok=True)
    for m in g.ROUTE_MODULES:
        (root / f"{m}.py").write_text("x = 1\n", encoding="utf-8")
    (root / "track1_sleeves.py").write_text(sleeves_src, encoding="utf-8")
    return root


def test_the_route_has_a_live_bar_path_and_it_is_guarded():
    """The measured claim behind the gate, updated by Stage 4C and still pinned.

    When this was written the assertion was the opposite — no module on the route could obtain
    a live bar at all. Stage 4C built one, so the pin moved with it rather than being deleted:
    what must stay true is that a fetch exists AND that it is joined through the guard.
    """
    ok, detail = g.live_frame_wiring()
    assert ok is True, detail
    assert "track1_live_source" in detail


def test_the_measurement_would_still_notice_an_unguarded_fetch(tmp_path):
    """The half of the measurement that has no live example any more, kept exercised."""
    root = _fake_route(tmp_path / "raw",
                       "from ib_insync import IB\n"
                       "def bars(ib):\n    return ib.reqHistoricalData()\n")
    ok, detail = g.live_frame_wiring(root)
    assert ok is False and "without the splice guard" in detail
