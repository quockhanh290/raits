"""Stage 5Q-8 — is the Track 1 paper path the same strategy as the backtest?

READ-ONLY. No scheduler, no backend, no broker, no order, no data written.

Three identities have to agree for a route to be the strategy its numbers describe:

    the DATA the signal is computed on   — must be the artifact's data
    the RULE the signal applies          — must be the artifact's rule
    the IDENTITY the route declares      — must name the rule it actually runs

The first two are checked by exact reproduction (Stage 4 and 5Q-7). This file checks the
THIRD, which nothing had been checking: `track1_params.sleeve_config` is what
`params_hash` is computed over and what a live explanation record reports as
`stop_basis`, and it is written by hand beside — not derived from — the modules that run.

Measured 2026-08-24: three of four sleeves agree. `global_nkd` does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import run_live_day_track1 as R          # noqa: E402
from global_index import specs as gi_specs                 # noqa: E402
from global_index import track1_calm_a as CA               # noqa: E402
from global_index import track1_live_source as src         # noqa: E402
from global_index import track1_normal_r4 as NR            # noqa: E402
from global_index import track1_params as tp               # noqa: E402
from global_index import track1_slots as slots             # noqa: E402
from global_index import track1_stress_mnq as SM           # noqa: E402
from global_index.ibkr_broker import ibkr_symbol_and_exchange   # noqa: E402

PATHS = R.default_data_paths()
KW = dict(regime_csv="spy_daily_live.csv", fill_law=tp.LIVE_FILL_LAW)


def cfg(sleeve: str):
    inst = tp.SLEEVE_INSTRUMENTS[sleeve][0]
    return tp.sleeve_config(sleeve, inst, data_path=PATHS[inst], **KW)


# ── 1. the three names, per sleeve ───────────────────────────────────────────────────

def test_every_sleeve_fetches_bars_from_the_symbol_its_parquet_was_built_from():
    """The Stage 5Q-7 defect, held shut for every instrument rather than only the one that
    had it. MNKD is the only split: bars NKD, orders MNK."""
    expect = {"MES": "MES", "MNQ": "MNQ", "MYM": "MYM", "M2K": "M2K", "MNKD": "NKD"}
    insts = {i for v in tp.SLEEVE_INSTRUMENTS.values() for i in v}
    assert insts == set(expect), insts
    for inst in sorted(insts):
        assert src.history_symbol(inst) == expect[inst], inst


def test_order_routing_is_unchanged_and_mnkd_still_goes_to_the_micro():
    expect = {"MES": "MES", "MNQ": "MNQ", "MYM": "MYM", "M2K": "M2K", "MNKD": "MNK"}
    for inst, sym in expect.items():
        assert ibkr_symbol_and_exchange(inst)[0] == sym, inst


def test_mnkd_point_value_is_the_micro_and_nkd_is_the_full_size():
    """A multiplier drives sizing, risk and realised P&L. It has never been able to move the
    price of a bar, so it is never the fix for a price disagreement."""
    assert gi_specs.SPECS["MNKD"].point_value == 0.5
    assert gi_specs.SPECS["NKD"].point_value == 5.0


def test_the_data_and_order_identities_are_different_strings_for_mnkd_only():
    diff = {i for v in tp.SLEEVE_INSTRUMENTS.values() for i in v
            if src.history_symbol(i) != ibkr_symbol_and_exchange(i)[0]}
    assert diff == {"MNKD"}, diff


# ── 2. declared identity vs the rule the slot actually runs ──────────────────────────

def test_roska4_swing_declares_the_rule_it_runs():
    c, p = cfg("roska4_swing"), NR.NormalR4Params()
    assert c["ema_period"] == p.ema_period == 50
    assert c["max_hold_days"] == p.max_hold_days == 5
    assert c["stop_multiple"] == p.stop_basis_atr_mult == 2.0
    assert c["stop_anchor"] == "entry"
    assert c["ratchet"] is p.ratchet is False
    assert c["arm_hour"] == "14:05"
    assert abs(p.arm_hours - (14 + 5 / 60)) < 1e-9
    assert c["arm_timezone"] == "America/New_York"


def test_roska4_calm_declares_the_rule_it_runs():
    c, p = cfg("roska4_calm"), CA.CalmAParams()
    assert c["stop_multiple"] == p.disaster_stop_atr_mult == 1.5
    assert c["stop_anchor"] == "entry"
    assert c["ratchet"] is False
    assert c["arm_hour"] == p.entry_time == "10:00"
    assert c["label_lag_days"] == p.regime_lag_sessions == 1
    assert tuple(tp.SLEEVE_INSTRUMENTS["roska4_calm"]) == p.instruments == ("MES", "MNQ")


def test_roska4_stress_declares_the_rule_it_runs():
    c, p = cfg("roska4_stress"), SM.StressParams()
    assert c["stop_multiple"] == p.rr == 1.5
    assert c["arm_hour"] == p.entry_start == "10:35"
    assert tuple(tp.SLEEVE_INSTRUMENTS["roska4_stress"]) == p.instruments == ("MNQ",)
    assert tp.SLEEVE_QTY["roska4_stress"] == p.qty == 7


def test_global_nkd_declares_the_rule_it_runs():
    """Stage 5Q-8 finding I-1, closed by Stage 5Q-9. This was an xfail(strict) until the
    declaration was corrected; the marker is gone because the mismatch is."""
    c, p = cfg("global_nkd"), NR.NormalR4Params(ema_period=10, fill_law=tp.LIVE_FILL_LAW)
    assert c["ema_period"] == p.ema_period == 10
    assert c["max_hold_days"] == p.max_hold_days == 5
    assert c["label_lag_days"] == 1
    assert c["stop_basis"] == "fixed_entry_atr"
    assert c["stop_multiple"] == p.stop_basis_atr_mult == 2.0
    assert c["stop_anchor"] == "entry"
    assert c["ratchet"] is p.ratchet is False
    assert c["arm_hour"] == "14:05"
    assert abs(p.arm_hours - (14 + 5 / 60)) < 1e-9
    assert c["arm_timezone"] == "Asia/Tokyo" == src.session_tz("MNKD")


def test_the_nkd_mismatch_is_now_zero_fields():
    """Was "exactly five fields" while I-1 stood. Kept, inverted, so a regression cannot slip
    back in under a test that only ever checked the count."""
    c = cfg("global_nkd")
    p = NR.NormalR4Params(ema_period=10, fill_law=tp.LIVE_FILL_LAW)
    bad = set()
    if c["stop_basis"] != "fixed_entry_atr":
        bad.add("stop_basis")
    if c["stop_multiple"] != p.stop_basis_atr_mult:
        bad.add("stop_multiple")
    if c["stop_anchor"] != "entry":
        bad.add("stop_anchor")
    if c["ratchet"] is not p.ratchet:
        bad.add("ratchet")
    if c["arm_hour"] != "14:05":
        bad.add("arm_hour")
    assert bad == set(), bad
    # everything that decides WHICH BARS and WHICH DAYS still agrees
    assert c["ema_period"] == p.ema_period == 10
    assert c["max_hold_days"] == p.max_hold_days == 5
    assert c["label_lag_days"] == 1


# ── 3. what the identity hash does and does not cover ────────────────────────────────

def test_the_hash_covers_the_data_file_it_reads():
    """`data_source_identity` is path + sha256 of the parquet, so a changed file changes the
    identity. This is what makes a checkpoint refuse after a repair."""
    a = tp.sleeve_identity("global_nkd", "MNKD", data_path=PATHS["MNKD"], **KW)[1]
    b = tp.sleeve_identity("global_nkd", "MNKD", data_path="no/such/file.parquet", **KW)[1]
    assert a != b
    c = tp.sleeve_config("global_nkd", "MNKD", data_path=PATHS["MNKD"], **KW)
    assert c["data_source_identity"].startswith("global_index/data/NKD_continuous_1m_8y.parquet:")
    assert ":MISSING" not in c["data_source_identity"]


def test_the_hash_covers_the_fill_law():
    kw = dict(regime_csv="spy_daily_live.csv", data_path=PATHS["MES"])
    a = tp.sleeve_identity("roska4_swing", "MES", fill_law=tp.FILL_ARTIFACT, **kw)[1]
    b = tp.sleeve_identity("roska4_swing", "MES", fill_law=tp.FILL_PRODUCTION, **kw)[1]
    assert a != b


def test_the_hash_now_covers_the_tradable_identity():
    """Stage 5Q-8 finding I-2, closed by Stage 5Q-9.

    Until 2026-08-24 nothing in ALL_FIELDS named the order symbol, the point value or the
    sizing basis, so the MNKD ten-times-size routing defect would have moved no hash at all
    and a checkpoint written before it would have been accepted after it."""
    from global_index import route_params as rp

    for name in ("tradable_symbol", "point_value", "tick", "sizing_basis"):
        assert name in rp.ALL_FIELDS, name


# ── 4. the clocks ────────────────────────────────────────────────────────────────────

def test_the_nkd_et_window_is_the_tokyo_power_hour_in_summer():
    import pandas as pd
    start, end = slots.WINDOWS_ET["global_nkd"]
    assert (start, end) == ("01:10", "02:55")
    jst = [pd.Timestamp(f"2026-08-25 {h}", tz="America/New_York")
           .tz_convert("Asia/Tokyo").strftime("%H:%M") for h in (start, end)]
    assert jst == ["14:10", "15:55"], jst


def test_the_nkd_window_leaves_the_tokyo_band_in_winter():
    """B-5R-C, as a number rather than a warning: the same ET slots land 15:10-16:55 JST."""
    import pandas as pd
    start, end = slots.WINDOWS_ET["global_nkd"]
    jst = [pd.Timestamp(f"2026-12-15 {h}", tz="America/New_York")
           .tz_convert("Asia/Tokyo").strftime("%H:%M") for h in (start, end)]
    assert jst == ["15:10", "16:55"], jst


def test_each_instrument_is_read_on_its_own_declared_session_clock():
    assert src.session_tz("MNKD") == "Asia/Tokyo"
    for inst in ("MES", "MNQ", "MYM", "M2K"):
        assert src.session_tz(inst) == "America/New_York"


# ── 5. sizing basis ──────────────────────────────────────────────────────────────────

def test_the_route_sizes_each_sleeve_on_the_basis_its_artifact_was_admitted_under():
    """Stage 5Q-8 finding I-3, closed by Stage 5Q-9 with a measurement rather than a taste.

    All four used to record `true_stop_distance`. Two of the four artifacts do not: the
    ATR-stop sleeves were admitted on `2.5 x daily ATR`, and replaying the committed stream
    through the real book on both bases moved 166 admissions across three windows."""
    assert tp.SIZING_BASIS == {
        "roska4_swing": tp.SIZING_ARTIFACT_ATR,
        "global_nkd": tp.SIZING_ARTIFACT_ATR,
        "roska4_calm": tp.SIZING_TRUE_STOP,
        "roska4_stress": tp.SIZING_TRUE_STOP,
    }
    # the proxy multiple is READ from the module that produced the artifacts, never restated
    from global_index.signal_layer import NKD_MULT, ROSKA4_MULT
    assert tp.sizing_atr_mult("roska4_swing") == ROSKA4_MULT == 2.5
    assert tp.sizing_atr_mult("global_nkd") == NKD_MULT == 2.5


def test_the_two_true_stop_sleeves_agree_with_their_own_module_helpers():
    """`risk_dollars` is now the single authority; it must not have quietly changed what Calm
    and Stress already computed and have their own tests for."""
    from global_index import track1_calm_a as CA2
    from global_index import track1_stress_mnq as SM2
    kw = dict(entry=100.0, stop=97.5, point_value=2.0, qty=3)
    r_s, b_s = tp.risk_dollars("roska4_stress", daily_atr=9.0, **kw)
    assert b_s == tp.SIZING_TRUE_STOP
    assert r_s == SM2.risk_dollars(kw["entry"], kw["stop"], kw["point_value"], kw["qty"])
    r_c, b_c = tp.risk_dollars("roska4_calm", daily_atr=9.0, **kw)
    assert r_c == CA2.stop_risk_dollars(kw["entry"], kw["stop"], kw["point_value"], kw["qty"])
    assert b_c == tp.SIZING_TRUE_STOP


def test_a_proxy_sleeve_refuses_rather_than_silently_sizing_light():
    """No ATR means no proxy risk. Falling back to the stop distance would size 20% light
    against caps measured on the proxy — quietly, which is the whole failure mode."""
    for sleeve in ("roska4_swing", "global_nkd"):
        for atr in (None, 0.0, -1.0):
            with pytest.raises(ValueError):
                tp.risk_dollars(sleeve, entry=100.0, stop=98.0, daily_atr=atr,
                                point_value=2.0, qty=1)


def test_the_live_route_records_the_basis_it_used_rather_than_a_literal():
    """Parsed, not grepped. The two proxy sleeves must report whatever `risk_dollars`
    returned; a hard-coded string there is how the record and the number part company."""
    import ast
    tree = ast.parse(Path(src.__file__).read_text(encoding="utf-8"))
    literals = [n for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value == "true_stop_distance"]
    assert len(literals) == 2, (
        f"expected the literal only in the two true-stop sleeves, found {len(literals)}")
    names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "risk_basis"]
    assert len(names) >= 4, names
