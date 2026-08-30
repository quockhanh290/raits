"""Stage 5ZZZ-B — the variables a sleeve decided on, and where each number came from.

Stage 5ZZR could name the four things NKD and Swing decide on and had to print "Not reported by
detector" beside every one. The detector computes all four for every bar it looks at and threw
them away. This stage gave it an observer seam, so the numbers come out of the same call the
live slot makes rather than out of a second implementation.

Two sources, never mixed:

    recorded_runtime      the slot wrote it while deciding
    reconstructed_today   the same detector replayed afterwards over the bars on disk

The first thing this file proves is that none of it changed a decision.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd                                              # noqa: E402
from global_index import track1_normal_r4 as NR                  # noqa: E402
from global_index import track1_params as tp                     # noqa: E402
from global_index import track1_strategy_diagnostics as SD       # noqa: E402
from monitor.backend import track1_market_view as mv             # noqa: E402

DAY = "2026-08-28"


@pytest.fixture(scope="module")
def frames():
    from global_index import run_live_day_track1 as rl
    paths = rl.default_data_paths() or {}
    out = {}
    for inst in ("MES", "MNKD"):
        p = paths.get(inst)
        if p and Path(p).exists():
            out[inst] = pd.read_parquet(p)
    if not out:
        pytest.skip("no persisted bar stores on this machine")
    return out


@pytest.fixture(scope="module")
def labels():
    return mv._label_map(REPO)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the seam changed no decision
# ══════════════════════════════════════════════════════════════════════════════════════════

def _setup_signature(setup):
    if setup is None:
        return None
    return (round(float(getattr(setup, "entry", 0) or 0), 6),
            round(float(getattr(setup, "stop", 0) or 0), 6),
            str(getattr(setup, "regime", "")))


@pytest.mark.parametrize("inst,ema,ctx", [("MES", 50, True), ("MNKD", 10, False)])
@pytest.mark.parametrize("day", ["2026-08-27", "2026-08-28"])
def test_the_observer_seam_changes_no_decision(frames, labels, inst, ema, ctx, day):
    """The claim the whole stage rests on, asserted across three sessions and both sleeves.

    An optional listener that altered an outcome would be a strategy change wearing an
    observability label, which is the one thing this stage was not allowed to do.
    """
    if inst not in frames:
        pytest.skip(f"no store for {inst}")
    params = NR.NormalR4Params(ema_period=ema, fill_law=tp.LIVE_FILL_LAW)
    short = NR.short_days_from_csv(str(REPO / "spy_daily_live.csv"), params.spy_short_filter)
    now = pd.Timestamp(f"{day} 23:59", tz=mv.ET)
    kw = dict(short_days=short, apply_context_filter=ctx)

    without = NR.detect_entry_for_slot(frames[inst], labels, inst, pd.Timestamp(day), now,
                                       params, **kw)
    obs = SD.NormalR4Observer()
    with_obs = NR.detect_entry_for_slot(frames[inst], labels, inst, pd.Timestamp(day), now,
                                        params, observer=obs, **kw)
    assert _setup_signature(without) == _setup_signature(with_obs)


def test_an_observer_that_raises_does_not_break_the_detector(frames, labels):
    """The seam swallows its listener's exceptions, and that is asserted rather than assumed —
    a diagnostics bug must never cost a slot its entry."""
    if "MES" not in frames:
        pytest.skip("no store for MES")

    def boom(_event):
        raise RuntimeError("a diagnostics bug")

    params = NR.NormalR4Params(fill_law=tp.LIVE_FILL_LAW)
    short = NR.short_days_from_csv(str(REPO / "spy_daily_live.csv"), params.spy_short_filter)
    now = pd.Timestamp(f"{DAY} 23:59", tz=mv.ET)
    kw = dict(short_days=short, apply_context_filter=True)
    clean = NR.detect_entry_for_slot(frames["MES"], labels, "MES", pd.Timestamp(DAY), now,
                                     params, **kw)
    noisy = NR.detect_entry_for_slot(frames["MES"], labels, "MES", pd.Timestamp(DAY), now,
                                     params, observer=boom, **kw)
    assert _setup_signature(clean) == _setup_signature(noisy)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. reconstruction stops at now, and never runs ahead of it
# ══════════════════════════════════════════════════════════════════════════════════════════

#: One build per instant, shared across sleeves. `build()` returns every sleeve, and asking it
#: once per sleeve doubled a suite whose slowest call is a full detector pass over a
#: 3.3-million-row frame — measured at ~50s when a caller names an instant, which bypasses the
#: live path's cache on purpose so a test gets the moment it asked for.
_BUILDS: dict = {}


def _built(now=None):
    key = str(now)
    if key not in _BUILDS:
        if now is None:
            # Stage 5ZZZ-S deferred the LIVE path (`now=None`) to a background worker, so a
            # cold process answers "still being computed" until it lands. Wait for the same
            # worker a browser waits for. Every assertion below is unchanged - only the
            # precondition is, and weakening them instead would have been the wrong fix.
            mv.warm(REPO)
        _BUILDS[key] = mv.build(REPO, now=now)
    return _BUILDS[key]


def _boundary(sleeve, now=None):
    return (_built(now)["sleeves"][sleeve].get("setup_boundary") or {})


@pytest.mark.parametrize("sleeve", ["global_nkd", "roska4_swing"])
def test_reconstruction_stops_at_the_instant_it_was_asked_about(sleeve):
    """Three instants across one session. The bar count has to grow with the clock and the last
    bar has to stop at it — a reconstruction that ran to the end of the session whatever it was
    asked would be reporting bars that had not happened."""
    early = _boundary(sleeve, pd.Timestamp(f"{DAY} 09:00", tz=mv.ET))
    mid = _boundary(sleeve, pd.Timestamp(f"{DAY} 14:20", tz=mv.ET))
    late = _boundary(sleeve, pd.Timestamp(f"{DAY} 23:00", tz=mv.ET))
    assert early.get("bars_evaluated") == 0, early.get("bars_evaluated")
    assert early.get("last_bar_ts") in (None, ""), early.get("last_bar_ts")
    assert 0 < mid["bars_evaluated"] < late["bars_evaluated"]
    assert str(mid["last_bar_ts"]) <= f"{DAY} 14:20:00"
    assert str(late["last_bar_ts"]) > str(mid["last_bar_ts"])


def test_a_future_session_is_not_reconstructed():
    """Nothing is invented for a day that has not happened."""
    out = (mv.build(REPO, day="2026-12-31")["sleeves"]["roska4_swing"]
           .get("setup_boundary") or {})
    assert not out.get("bars_evaluated")


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. the values themselves — NKD and Swing, their own variables and not the basket's
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("sleeve,period", [("global_nkd", 10), ("roska4_swing", 50)])
def test_each_sleeve_reports_its_own_trend_period(sleeve, period):
    labels_seen = [m["label"] for m in _boundary(sleeve).get("metrics") or []]
    assert f"Trend filter (EMA {period})" in labels_seen, labels_seen


@pytest.mark.parametrize("sleeve", ["global_nkd", "roska4_swing"])
def test_the_four_decision_variables_carry_real_numbers(sleeve):
    """`make_signal_fn(prev_bar, resume_bar, ema, atr, regime, avgv)` — every one of them."""
    metrics = {m["label"]: m for m in _boundary(sleeve).get("metrics") or []}
    for want in ("Daily ATR", "Volume", "Average volume (10 bars)", "Volume vs average"):
        assert want in metrics, sorted(metrics)
        assert metrics[want]["display_value"] not in ("", None, "Not reported by detector"), want
        assert metrics[want]["missing"] is None, (want, metrics[want])


@pytest.mark.parametrize("sleeve", ["global_nkd", "roska4_swing"])
def test_no_basket_metric_appears_on_a_normal_r4_sleeve(sleeve):
    """Breadth, gap-down count and basket gap belong to `track1_stress_mnq`. This detector never
    evaluates them, and naming them here would say the sleeve checks something it does not."""
    text = json.dumps(_boundary(sleeve)).lower()
    for basket in ("gapped down", "below open and vwap", "basket gap", "wide range"):
        assert basket not in text, basket


@pytest.mark.parametrize("sleeve", ["global_nkd", "roska4_swing"])
def test_a_sleeve_that_found_no_setup_says_why_in_words(sleeve):
    b = _boundary(sleeve)
    assert b.get("summary"), b
    assert not b.get("levels_armed"), "no setup, so nothing may be armed"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. every panel says where its numbers came from
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("sleeve", ["global_nkd", "roska4_swing", "roska4_stress"])
def test_every_sleeve_declares_a_diagnostics_source(sleeve):
    src = _boundary(sleeve).get("diagnostics_source")
    assert src in (SD.RECORDED, SD.RECONSTRUCTED, SD.NOT_YET_RUN,
                   SD.MISSING_NOT_REPORTED), (sleeve, src)


def test_a_reconstruction_carries_its_warning_and_its_horizon():
    from global_index import track1_strategy_diagnostics as sd
    obs = sd.NormalR4Observer()
    block = sd.normal_r4_block(sleeve="roska4_swing", slot_id="", ema_period=50, observer=obs,
                               setup=None, source=sd.RECONSTRUCTED,
                               reconstructed_through="2026-08-28 14:20")
    assert block["warning"] == sd.RECONSTRUCTION_WARNING
    assert block["reconstructed_at"] and block["reconstructed_through"]


def test_a_recorded_block_carries_no_reconstruction_fields():
    """The two must not blur. A recorded block that carried a `reconstructed_at` would invite a
    reader to treat evidence and replay as the same thing."""
    from global_index import track1_strategy_diagnostics as sd
    block = sd.normal_r4_block(sleeve="global_nkd", slot_id="", ema_period=10,
                               observer=sd.NormalR4Observer(), setup=None, source=sd.RECORDED)
    assert "reconstructed_at" not in block
    assert "warning" not in block
    assert block["diagnostics_source"] == sd.RECORDED


def test_a_slot_that_has_not_run_is_never_reconstructed():
    block = SD.not_yet_run_block(sleeve="roska4_calm", slot_id="TRACK1_CALM_DECIDE_0932",
                                 detector="track1_calm_a", at="09:32")
    assert block["diagnostics_source"] == SD.NOT_YET_RUN
    assert block["rows"] == [] and block["price_levels"] == []
    assert "09:32" in block["summary"]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. the runtime store, and how a reader prefers it
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_recorded_beats_reconstructed_for_the_same_slot(tmp_path):
    rec = SD.normal_r4_block(sleeve="roska4_swing", slot_id="TRACK1_SWING_1405", ema_period=50,
                             observer=SD.NormalR4Observer(), setup=None, source=SD.RECORDED)
    rec["session_date"] = DAY
    con = SD.normal_r4_block(sleeve="roska4_swing", slot_id="TRACK1_SWING_1405", ema_period=50,
                             observer=SD.NormalR4Observer(), setup=None,
                             source=SD.RECONSTRUCTED)
    con["session_date"] = DAY
    SD.record(con, root=tmp_path, day=DAY)
    SD.record(rec, root=tmp_path, day=DAY)
    got = SD.recorded_for(tmp_path, DAY, "roska4_swing", "TRACK1_SWING_1405")
    assert got is not None and got["diagnostics_source"] == SD.RECORDED


def test_a_day_with_no_runtime_record_reads_as_empty_not_as_an_error(tmp_path):
    """Every historical day is such a day, and none of them may raise."""
    assert SD.read(root=tmp_path, day="2026-01-02") == []
    assert SD.recorded_for(tmp_path, "2026-01-02", "global_nkd") is None


def test_a_corrupt_line_does_not_take_the_day_down(tmp_path):
    p = SD.path_for(tmp_path, DAY)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"sleeve": "global_nkd", "diagnostics_source": "recorded_runtime"}\n'
                 "{ not json at all\n", encoding="utf-8")
    assert len(SD.read(root=tmp_path, day=DAY)) == 1


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6. the page reads, and does not compute
# ══════════════════════════════════════════════════════════════════════════════════════════

JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"


def test_the_page_shows_the_source_and_does_not_decide_it():
    code = JS.read_text(encoding="utf-8")
    assert "MV_SOURCE_WORDS" in code and "mvSourceBadge" in code
    for key in ("recorded_runtime", "reconstructed_today", "not_yet_run"):
        assert key in code, key
    assert "diagnostics_source" in code


def test_the_page_computes_no_strategy_value():
    """The rule from Stage 5ZZL onward: values are addressed out of the payload, never derived."""
    code = JS.read_text(encoding="utf-8")
    for forbidden in ("calculate_ema", "function ema(", "atr14", "Math.exp(",
                      "generate_signal"):
        assert forbidden not in code, forbidden


def test_the_reconstruction_warning_is_not_softened_on_the_page():
    code = JS.read_text(encoding="utf-8")
    seg = code.split("MV_SOURCE_WORDS")[1][:600]
    assert "not official runtime evidence" in seg


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7. nothing was armed, and no gate moved
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_orders_remain_impossible():
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in [r.split(":")[0] for r in reasons]


def test_diagnostics_are_not_consulted_by_any_gate():
    """The safety line. A reconstruction must never satisfy readiness, an audit or an order
    gate, and the cheapest way to keep that true is for none of them to import the module."""
    for name in ("track1_gates.py", "track1_paper_readiness.py", "track1_shadow_acceptance.py"):
        src = (REPO / "global_index" / name).read_text(encoding="utf-8")
        assert "track1_strategy_diagnostics" not in src, name


def test_no_order_artefacts_exist():
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not (REPO / "global_index" / "live_positions.track1.json").exists()
