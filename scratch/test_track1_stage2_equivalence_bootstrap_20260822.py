"""scratch/test_track1_stage2_equivalence_bootstrap_20260822.py — Stage 2 offline tests.

Eight checks over the Stage 2 deliverables: the equivalence harness and the Track 1
bootstrap. Offline. No scheduler, no broker, no production path is written.

Two of the eight exist only to prove the other six can fail. A harness that reports
"matched" and an anchor that reports "all_ok" are worth nothing until something has been
broken in front of them and they have gone red — a suite whose every assertion agrees with
itself is the failure mode this file is written against, and it has already bitten once in
this project when a parametrised test SHRANK instead of failing.

Run:
    python -m pytest scratch/test_track1_stage2_equivalence_bootstrap_20260822.py -q
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import route_checkpoint as rc
from global_index import route_params as rp
from scratch import track1_bootstrap_checkpoint_20260822 as boot
from scratch import track1_equivalence_harness_20260822 as harness

BOOTSTRAP_OUT = Path("scratch/replay_checkpoint.track1.bootstrap_20260822.json")

#: Pinned here, independently of the harness module, on purpose. Importing the module's own
#: constants and comparing them to themselves would pass whatever they were changed to.
#: The CLOSED window 2026-08-10 -> 08-21. Bounded by two dates, so it cannot grow and is
#: pinned exactly. This is the anchor that means something.
EXPECTED_WINDOW = {"matched": 85, "diverged": 0, "skipped": 0}

#: The ALL-DAYS totals. `matched` was pinned at 91 until 2026-08-24 and read 96 that evening —
#: not a regression, arithmetic: the live_day logs gain lines every trading day, so an
#: all-days total pinned to a literal is a description that leaves the thing it describes on
#: the next session. Bumping the number would only move the expiry date.
#:
#: What must stay exact is `diverged`: a single divergence is a real failure whatever the
#: total is. `matched` is asserted as a floor at the published figure, and the window above
#: is what pins an exact count.
EXPECTED_ALL_DAYS_EXACT = {"diverged": 0}
PUBLISHED_ALL_DAYS_MATCHED = 91

#: Also pinned independently — this is the contract the bootstrap must fill, and reading it
#: from route_params would let a deleted field delete its own test.
EXPECTED_PARAM_FIELDS = {
    "ema_period", "max_hold_days",
    "stop_basis", "stop_multiple", "stop_anchor", "ratchet",
    "arm_hour", "arm_timezone",
    "r4_range_threshold", "r4_range_derivation_window", "r4_rel_volume_max",
    "spy_short_filter", "spy_short_lookback", "spy_short_lag_days",
    "spy_short_source_identity",
    "hmm_fit_end", "regime_csv_identity", "label_lag_days", "calm_gate_definition",
    "cap_roska4_swing", "cap_roska4_calm", "cap_roska4_stress", "cap_global_nkd",
    "cap_family_normal_calm",
    "slippage_ticks_per_side", "commission_basis",
    "data_source_identity", "fill_law",
    # Stage 5Q-9 — I-2, widened deliberately: the hash now also names what the route
    # TRADES, not only what it reads.
    "tradable_symbol", "point_value", "tick", "sizing_basis",
}


@pytest.fixture(scope="module")
def payload():
    if not BOOTSTRAP_OUT.exists():
        pytest.skip(f"{BOOTSTRAP_OUT} not built yet — run the bootstrap first")
    return json.loads(BOOTSTRAP_OUT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def configs():
    src = {i: f"file_{i}.parquet:deadbeefdeadbeef"
           for i in ("MES", "MNQ", "MYM", "M2K", "MNKD")}
    return boot.sleeve_configs("spy_daily_live.csv:0000000000000000", src)


# ---------------------------------------------------------------------------
# 1-2  the harness anchor, and proof the anchor can fail
# ---------------------------------------------------------------------------
def test_1_log_anchor_reproduces_the_published_shadow_record():
    """Re-derived from the live_day logs on every run, not read back from a stored total.

    The published figure is 91. That is the ALL-DAYS total; the 2026-08-10 -> 08-21 window
    is 85. Both are asserted because conflating them is what made the brief's single number
    ambiguous in the first place.
    """
    got = harness.a1_log_anchor()
    assert got["all_days"]["matched"] > 0, "no log lines parsed — the anchor would pass empty"
    assert {k: got["all_days"][k] for k in EXPECTED_ALL_DAYS_EXACT} == EXPECTED_ALL_DAYS_EXACT
    assert got["all_days"]["matched"] >= PUBLISHED_ALL_DAYS_MATCHED, (
        f"all-days matched fell BELOW the published {PUBLISHED_ALL_DAYS_MATCHED} — the log "
        f"anchor can only grow, so a drop means lines stopped being parsed")
    assert got["all_days"]["matched"] >= got["window"]["matched"], "window exceeds all days"
    assert {k: got["window"][k] for k in EXPECTED_WINDOW} == EXPECTED_WINDOW


def test_2_the_comparison_detects_a_single_perturbed_field():
    """MUTATION. One cent on one trade must be enough. If it is not, every MATCH above is
    decoration."""
    full = [{f: 1.0 for f in harness.TRADE_FIELDS} for _ in range(3)]
    for i, t in enumerate(full):
        # exit_day is what compare() filters on, so it has to be a real date past the cut —
        # leaving it a float silently empties the expected list and the comparison then
        # passes on nothing at all.
        t["day"] = f"2026-01-0{i + 1}"
        t["exit_day"] = f"2026-01-0{i + 2}"
    cut = pd.Timestamp("2025-12-31")

    clean = harness.compare(full, None, copy.deepcopy(full), None, cut)
    assert clean["trades_expected"] == 3, "nothing survived the cut — the control is empty"
    assert clean["trades_match"] and clean["match"], "control did not match"

    for field in ("pnl", "exit", "reason", "exit_time"):
        bad = copy.deepcopy(full)
        bad[-1][field] = 1.01 if field in ("pnl", "exit") else "CHANGED"
        got = harness.compare(full, None, bad, None, cut)
        assert not got["trades_match"], f"perturbing {field} went undetected"
        assert not got["match"]


# ---------------------------------------------------------------------------
# 3-5  the bootstrap output
# ---------------------------------------------------------------------------
def test_3_output_is_schema_v2_with_every_sleeve_and_the_right_instruments(payload):
    assert payload["schema_version"] == rc.SCHEMA == 2
    sleeves = payload["routes"][rc.DEFAULT_ROUTE]["sleeves"]
    assert set(sleeves) == set(rc.SLEEVES)
    assert set(sleeves["roska4_swing"]["instruments"]) == {"MES", "MNQ", "MYM", "M2K"}
    assert set(sleeves["global_nkd"]["instruments"]) == {"MNKD"}
    # Present and empty is the claim being made: these two carry nothing overnight.
    assert sleeves["roska4_calm"]["instruments"] == {}
    assert sleeves["roska4_stress"]["instruments"] == {}


def test_4_identity_separates_strategy_from_data_pin(payload, configs):
    sleeves = payload["routes"][rc.DEFAULT_ROUTE]["sleeves"]
    entries = {**sleeves["roska4_swing"]["instruments"],
               **sleeves["global_nkd"]["instruments"]}
    hashes = [e["params_hash"] for e in entries.values()]
    assert len(set(hashes)) == 5, "a per-instrument data pin is not reaching the hash"

    # Stage 5Q-9 — I-2. Pinning the data source alone NO LONGER collapses the four R4
    # instruments to one hash, and that is deliberate: the identity now also names what each
    # one TRADES — its order symbol, point value and tick. `sleeve_config` always took `inst`
    # and, until 2026-08-24, never used it; the signature promised a per-instrument identity
    # and did not deliver one. That is what let the MNKD ten-times-size routing defect move
    # no hash at all.
    pinned = {i: rp.params_hash({**c, "data_source_identity": "PINNED"})
              for i, c in configs.items()}
    r4 = {pinned[i] for i in ("MES", "MNQ", "MYM", "M2K")}
    assert len(r4) == 4, "the contract each instrument trades must reach its own hash"

    # what the four DO still share is the strategy half. Pin the contract too and they
    # collapse — which is the separation this test was written to prove.
    CONTRACT = {"tradable_symbol": "X", "point_value": 1.0, "tick": 1.0}
    strat = {i: rp.params_hash({**c, "data_source_identity": "PINNED", **CONTRACT})
             for i, c in configs.items()}
    assert len({strat[i] for i in ("MES", "MNQ", "MYM", "M2K")}) == 1, (
        "the four R4 instruments do not share one strategy identity")
    assert strat["MNKD"] not in {strat[i] for i in ("MES", "MNQ", "MYM", "M2K")}, (
        "NKD must differ — ema 10, Tokyo clock, lag 1")
    assert pinned["MNKD"] not in r4

    # and the three things that separate them must each do so on their own
    for field, value in (("ema_period", 30), ("arm_timezone", "America/New_York"),
                         ("label_lag_days", 0)):
        alt = rp.params_hash({**configs["MNKD"], "data_source_identity": "PINNED",
                              field: value})
        assert alt != pinned["MNKD"], f"{field} does not move the hash"


def test_5_unsourced_fields_are_declared_not_defaulted(configs):
    assert set(configs["MES"]) >= EXPECTED_PARAM_FIELDS, "a declared field is unfilled"
    assert EXPECTED_PARAM_FIELDS == set(rp.ALL_FIELDS), (
        "the params contract moved; update this pinned list deliberately")
    declared = set(boot.UNSOURCED)
    # Emptied on 2026-08-22: the SPY fields were sourced by audit and fill_law was settled by
    # measuring both laws. The machinery stays wired — that is what the next two asserts pin —
    # so a future unsourced field still blocks the write instead of defaulting.
    assert declared == set()
    assert boot.DECIDED_BY_MEASUREMENT, "a settled conflict must still name its evidence"
    for inst, cfg in configs.items():
        sentinels = {k for k, v in cfg.items() if v == boot.UNKNOWN}
        assert sentinels == declared, f"{inst}: sentinel set drifted from the table"
    # UNSOURCED is empty today, so a loop over it would pass on nothing. The property that
    # still has something to check is the one that replaced it.
    for field, why in boot.DECIDED_BY_MEASUREMENT.items():
        assert field in EXPECTED_PARAM_FIELDS
        assert len(why) > 20, "a settled conflict must point at its evidence"
    for why in boot.UNSOURCED.values():
        assert len(why) > 40, "an unsourced field must carry a reason, not a shrug"


# ---------------------------------------------------------------------------
# 6  refusal to write outside scratch
# ---------------------------------------------------------------------------
def test_6_refuses_to_write_a_production_path(tmp_path):
    out = tmp_path / "replay_checkpoint.track1.json"
    r = subprocess.run(
        [sys.executable, "scratch/track1_bootstrap_checkpoint_20260822.py",
         "--out", str(out)],
        capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"expected refusal, got {r.returncode}"
    assert "REFUSED" in r.stdout
    assert not out.exists(), "refused but wrote anyway"


# ---------------------------------------------------------------------------
# 7  positive control for the axis the live anchor cannot exercise
# ---------------------------------------------------------------------------
def test_7_a_non_flat_position_survives_the_round_trip(tmp_path):
    """The live anchor compared five FLAT positions, so on the position axis it was
    `None == None` — true by construction. This is the control that axis needs: an open
    position must survive write -> read -> get_entry unchanged, field for field.
    """
    idx = pd.date_range("2026-01-02 09:30", periods=50, freq="1min", tz="America/New_York")
    df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
                      index=idx)
    pos = {"dir": "LONG", "entry": 5123.25, "stop": 5090.5, "extreme": 5140.75,
           "entry_day": pd.Timestamp("2026-01-02"), "entry_time": "2026-01-02 10:00:00",
           "regime": "Normal"}
    entry = rc.make_entry(df, pd.Timestamp("2026-01-02"), pos,
                          route=rc.DEFAULT_ROUTE, sleeve="roska4_swing",
                          params="p", params_hash="h", data_source="d")
    path = tmp_path / "ck.json"
    rc.save_route({"roska4_swing": {"MES": entry}}, route=rc.DEFAULT_ROUTE, path=str(path))
    back = rc.get_entry(rc.load(str(path)), rc.DEFAULT_ROUTE, "roska4_swing", "MES")

    assert back["pos"] is not None, "an open position was dropped in the round trip"
    for f in ("dir", "entry", "stop", "extreme"):
        assert str(back["pos"][f]) == str(pos[f]), f"{f} changed across the round trip"
    # and the control must be able to tell a real position from a flat one
    flat = rc.make_entry(df, pd.Timestamp("2026-01-02"), None,
                         route=rc.DEFAULT_ROUTE, sleeve="roska4_swing",
                         params="p", params_hash="h", data_source="d")
    assert flat["pos"] is None and flat["pos"] != entry["pos"]


# ---------------------------------------------------------------------------
# 8  proof the legacy anchor can fail
# ---------------------------------------------------------------------------
def test_8_the_legacy_anchor_goes_red_when_legacy_disagrees(tmp_path):
    """MUTATION on the anchor itself. Its control run is five flat positions on one day, so
    it has to be shown failing on BOTH axes it claims to cover."""
    df = pd.DataFrame({"close": [1.0]},
                      index=pd.DatetimeIndex(["2026-08-20 10:00"]).tz_localize("UTC"))
    replayed = {"MES": {"df": df, "last_day": pd.Timestamp("2026-08-20"), "pos": None}}

    def write(inst_block):
        p = tmp_path / f"legacy_{abs(hash(json.dumps(inst_block, sort_keys=True)))}.json"
        p.write_text(json.dumps({"schema_version": 1, "instruments": inst_block}),
                     encoding="utf-8")
        return str(p)

    ok = boot.anchor_against_legacy(
        replayed, write({"MES": {"last_day": "2026-08-20", "pos": None}}))
    assert ok["all_ok"], "control anchor failed"

    wrong_day = boot.anchor_against_legacy(
        replayed, write({"MES": {"last_day": "2026-08-19", "pos": None}}))
    assert not wrong_day["all_ok"] and "last_day" in wrong_day["rows"][0]["why"]

    wrong_pos = boot.anchor_against_legacy(
        replayed, write({"MES": {"last_day": "2026-08-20",
                                 "pos": {"dir": "LONG", "entry": 1.0, "stop": 0.5}}}))
    assert not wrong_pos["all_ok"] and "position" in wrong_pos["rows"][0]["why"]

    missing = boot.anchor_against_legacy(replayed, write({}))
    assert not missing["all_ok"] and "absent" in missing["rows"][0]["why"]
