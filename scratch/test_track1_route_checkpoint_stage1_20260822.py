"""Stage 1 offline tests for the Track 1 resume-primary infrastructure. SCRATCH-ONLY.

Connects to nothing, starts nothing, writes only into tmp_path. No legacy file is imported
for mutation — `replay_checkpoint` is imported read-only, to prove the two schemas refuse
each other.

The claim under test is not "the modules work". It is:

  * a checkpoint that should be refused IS refused, with the right reason code;
  * a writer cannot damage another route's state;
  * every field in the params hash actually reaches the hash;
  * a window nobody observed is distinguishable from a window that produced nothing.

Each of those is written so it can go red. The two that matter most are
`test_params_mismatch_refuses` — the branch that has never fired in production — and
`test_missing_checkpoint_fails_closed`.

    python -m pytest scratch/test_track1_route_checkpoint_stage1_20260822.py -q
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import global_index.replay_checkpoint as legacy_ckpt
import global_index.route_checkpoint as rc
import global_index.route_params as rp
import global_index.window_ledger as wl


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _bars(n=400, start="2026-08-01", tz="America/New_York", seed=0):
    idx = pd.date_range(start, periods=n, freq="1min", tz=tz)
    v = [100.0 + ((i * 7 + seed) % 13) * 0.25 for i in range(n)]
    return pd.DataFrame({"open": v, "high": [x + 0.5 for x in v],
                         "low": [x - 0.5 for x in v], "close": v,
                         "volume": [10 + (i % 5) for i in range(n)]}, index=idx)


def _cfg(**over):
    base = {
        "ema_period": 50, "max_hold_days": 5,
        "stop_basis": 2.0, "stop_multiple": 2.5, "stop_anchor": "entry", "ratchet": False,
        "arm_hour": 14.0, "arm_timezone": "America/New_York",
        "r4_range_threshold": 0.0123, "r4_range_derivation_window": "floor_2018_2024",
        "r4_rel_volume_max": 2.0,
        "spy_short_filter": "d1_spy_close_below_sma50_for_shorts_only",
        "spy_short_lookback": 50, "spy_short_lag_days": 1,
        "spy_short_source_identity": "spy_daily_live.csv:abc123",
        "hmm_fit_end": "2024-12-31", "regime_csv_identity": "spy_daily_live.csv:abc123",
        "label_lag_days": 1, "calm_gate_definition": "d1_calm_causal",
        "cap_roska4_swing": [0.05, 0.044], "cap_roska4_calm": [0.05, None],
        "cap_roska4_stress": [0.10, None], "cap_global_nkd": [0.06, 0.06],
        "cap_family_normal_calm": [0.05, 0.044],
        "slippage_ticks_per_side": 2.0, "commission_basis": "per_contract_rt",
        "data_source_identity": "frozen_sim/ES_continuous_1m_8y.parquet:sha1",
        "fill_law": "gap_after_15min_break",
        # Stage 5Q-9 — I-2. What the route TRADES, beside what it reads. MNKD is the case
        # these exist for: bars from full-size NKD, orders to the $0.50 micro MNK.
        "tradable_symbol": "MNK", "point_value": 0.5, "tick": 5.0,
        "sizing_basis": "artifact_mult_x_daily_atr",
    }
    base.update(over)
    return base


@pytest.fixture
def cp(tmp_path):
    return str(tmp_path / "replay_checkpoint.track1.json")


@pytest.fixture(autouse=True)
def _fresh_ledger(monkeypatch):
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    monkeypatch.delenv("RAITS_ROUTE", raising=False)
    importlib.reload(wl)
    yield
    importlib.reload(wl)


def _entry(df, last_day, pos=None, cfg=None, route=rc.DEFAULT_ROUTE,
           sleeve="roska4_swing", src="parquet:x"):
    cfg = cfg or _cfg()
    readable, h = rp.identity(cfg)
    return rc.make_entry(df, last_day, pos, route=route, sleeve=sleeve,
                         params=readable, params_hash=h, data_source=src)


# ---------------------------------------------------------------------------
# 1. round trip
# ---------------------------------------------------------------------------
def test_v2_round_trip(cp):
    df = _bars()
    last = pd.Timestamp("2026-08-01")
    pos = {"dir": "LONG", "entry": 101.5, "stop": 99.0,
           "entry_day": pd.Timestamp("2026-08-01"),
           "entry_time": pd.Timestamp("2026-08-01 14:05")}
    rc.save_route({"roska4_swing": {"MES": _entry(df, last, pos)}}, path=cp)
    payload = rc.load(cp)
    assert payload["schema_version"] == 2
    e = rc.get_entry(payload, rc.DEFAULT_ROUTE, "roska4_swing", "MES")
    got = rc.usable(e, df, route=rc.DEFAULT_ROUTE, params_hash=rp.params_hash(_cfg()))
    assert got, f"expected Resumed, got {got}"
    assert got.last_day == last
    assert got.pos["dir"] == "LONG"
    # timestamps must come back as Timestamps, not strings
    assert isinstance(got.pos["entry_day"], pd.Timestamp)
    assert isinstance(got.pos["entry_time"], pd.Timestamp)


def test_flat_position_is_usable_not_a_miss(cp):
    """pos=None is a valid answer, not a cache miss — otherwise every flat day replays."""
    df = _bars()
    rc.save_route({"roska4_swing": {"MES": _entry(df, pd.Timestamp("2026-08-01"), None)}},
                  path=cp)
    e = rc.get_entry(rc.load(cp), rc.DEFAULT_ROUTE, "roska4_swing", "MES")
    got = rc.usable(e, df, route=rc.DEFAULT_ROUTE, params_hash=rp.params_hash(_cfg()))
    assert got and got.pos is None


# ---------------------------------------------------------------------------
# 2-3. the two schemas refuse each other
# ---------------------------------------------------------------------------
def test_v1_file_refused_by_v2_loader(tmp_path):
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps({"schema_version": 1, "instruments": {"MES": {}}}),
                 encoding="utf-8")
    assert rc.load(str(p)) == {}, "a v1 payload must not load as v2"


def test_v2_file_refused_by_legacy_loader(cp):
    rc.save_route({"roska4_swing": {"MES": _entry(_bars(), pd.Timestamp("2026-08-01"))}},
                  path=cp)
    assert legacy_ckpt.load(cp) == {}, "legacy must refuse a v2 payload"


# ---------------------------------------------------------------------------
# 4-6. refusals with codes
# ---------------------------------------------------------------------------
def test_params_mismatch_refuses(cp):
    """The branch that has NEVER fired in production."""
    df = _bars()
    rc.save_route({"roska4_swing": {"MES": _entry(df, pd.Timestamp("2026-08-01"))}},
                  path=cp)
    e = rc.get_entry(rc.load(cp), rc.DEFAULT_ROUTE, "roska4_swing", "MES")
    other = rp.params_hash(_cfg(stop_basis=2.5))
    r = rc.usable(e, df, route=rc.DEFAULT_ROUTE, params_hash=other)
    assert not r and r.code == rc.PARAMS_MISMATCH, r
    assert "stored=" in r.detail and "caller=" in r.detail


def test_route_mismatch_refuses(cp):
    df = _bars()
    rc.save_route({"roska4_swing": {"MES": _entry(df, pd.Timestamp("2026-08-01"),
                                                  route="legacy_shadow")}},
                  route="legacy_shadow", path=cp)
    e = rc.get_entry(rc.load(cp), "legacy_shadow", "roska4_swing", "MES")
    r = rc.usable(e, df, route=rc.DEFAULT_ROUTE, params_hash=rp.params_hash(_cfg()))
    assert not r and r.code == rc.ROUTE_MISMATCH, r


def test_sleeve_mismatch_refuses_as_no_entry(cp):
    """A different sleeve is a different key — never a silent hit on the wrong state."""
    df = _bars()
    rc.save_route({"roska4_swing": {"MES": _entry(df, pd.Timestamp("2026-08-01"))}},
                  path=cp)
    e = rc.get_entry(rc.load(cp), rc.DEFAULT_ROUTE, "roska4_calm", "MES")
    r = rc.usable(e, df, route=rc.DEFAULT_ROUTE, params_hash=rp.params_hash(_cfg()))
    assert not r and r.code == rc.NO_ENTRY, r


# ---------------------------------------------------------------------------
# 7. rowcount vs content are separate categories
# ---------------------------------------------------------------------------
def test_fingerprint_rowcount_vs_content_are_categorised_separately(cp):
    df = _bars()
    last = pd.Timestamp("2026-08-01")
    entry = _entry(df, last)

    # rowcount: history grew under the entry (48 of the 64 historical skips)
    grown = _bars(n=500)
    r1 = rc.usable(entry, grown, route=rc.DEFAULT_ROUTE, params_hash=rp.params_hash(_cfg()))
    assert not r1 and r1.code == rc.FINGERPRINT_ROWCOUNT, r1
    assert "delta=" in r1.detail

    # content: same length, a bar rewritten in the middle (4 of the 64)
    edited = df.copy()
    edited.iloc[len(edited) // 2, edited.columns.get_loc("close")] += 1.0
    r2 = rc.usable(entry, edited, route=rc.DEFAULT_ROUTE, params_hash=rp.params_hash(_cfg()))
    assert not r2 and r2.code == rc.FINGERPRINT_CONTENT, r2


# ---------------------------------------------------------------------------
# 8-9. fail closed
# ---------------------------------------------------------------------------
def test_missing_checkpoint_fails_closed(cp):
    """No entry -> a refusal a caller must handle. Not a silent fall-through, and
    nothing here triggers a replay of its own."""
    assert rc.load(cp) == {}
    e = rc.get_entry(rc.load(cp), rc.DEFAULT_ROUTE, "roska4_swing", "MES")
    r = rc.usable(e, _bars(), route=rc.DEFAULT_ROUTE, params_hash=rp.params_hash(_cfg()))
    assert not r and r.code == rc.NO_ENTRY
    assert bool(r) is False, "a Refusal must be falsy so `if usable(...)` cannot pass"


def test_stale_checkpoint_is_detected_even_when_fingerprint_matches(cp):
    """Staleness is a separate axis: the history simply stopped growing, which no
    fingerprint comparison can see."""
    df = _bars()
    entry = _entry(df, pd.Timestamp("2026-08-01"))
    ok = rc.usable(entry, df, route=rc.DEFAULT_ROUTE, params_hash=rp.params_hash(_cfg()))
    assert ok, "fingerprint should still match"
    assert rc.stale(entry, pd.Timestamp("2026-08-20"), max_age_days=5) is True
    assert rc.stale(entry, pd.Timestamp("2026-08-03"), max_age_days=5) is False


# ---------------------------------------------------------------------------
# 10-12. write scoping
# ---------------------------------------------------------------------------
def test_save_preserves_other_routes_byte_identically(cp):
    df = _bars()
    rc.save_route({"roska4_swing": {"MES": _entry(df, pd.Timestamp("2026-08-01"),
                                                  route="legacy_shadow")}},
                  route="legacy_shadow", path=cp)
    before = json.dumps(rc.load(cp)["routes"]["legacy_shadow"], sort_keys=True)

    rc.save_route({"roska4_swing": {"MNQ": _entry(df, pd.Timestamp("2026-08-01"))}},
                  route=rc.DEFAULT_ROUTE, path=cp)
    after = json.dumps(rc.load(cp)["routes"]["legacy_shadow"], sort_keys=True)
    assert after == before, "writing one route must not alter another"
    assert "MNQ" in rc.load(cp)["routes"][rc.DEFAULT_ROUTE]["sleeves"]["roska4_swing"]["instruments"]


def test_two_sleeves_on_the_same_instrument_coexist(cp):
    """The thing v1's instrument-only key space could not express."""
    df = _bars()
    last = pd.Timestamp("2026-08-01")
    rc.save_route({"roska4_swing": {"MES": _entry(df, last, sleeve="roska4_swing")},
                   "roska4_calm": {"MES": _entry(df, last, sleeve="roska4_calm")}},
                  path=cp)
    sl = rc.load(cp)["routes"][rc.DEFAULT_ROUTE]["sleeves"]
    assert sl["roska4_swing"]["instruments"]["MES"]["sleeve"] == "roska4_swing"
    assert sl["roska4_calm"]["instruments"]["MES"]["sleeve"] == "roska4_calm"


def test_interleaved_writers_lose_nothing(cp):
    """Two routes writing in turn: both survive. This is what v1's whole-dict rewrite
    could not promise."""
    df = _bars()
    last = pd.Timestamp("2026-08-01")
    for i in range(4):
        rc.save_route({"roska4_swing": {f"A{i}": _entry(df, last, route="rA")}},
                      route="rA", path=cp)
        rc.save_route({"roska4_swing": {f"B{i}": _entry(df, last, route="rB")}},
                      route="rB", path=cp)
    routes = rc.load(cp)["routes"]
    assert set(routes) == {"rA", "rB"}
    # each route keeps only its own latest write, and neither erased the other
    assert list(routes["rA"]["sleeves"]["roska4_swing"]["instruments"]) == ["A3"]
    assert list(routes["rB"]["sleeves"]["roska4_swing"]["instruments"]) == ["B3"]


def test_empty_payload_lists_the_same_session_sleeves(cp):
    """Present-but-empty says 'accounted for'; absent would say 'nobody thought about it'."""
    p = rc.empty_payload()
    sl = p["routes"][rc.DEFAULT_ROUTE]["sleeves"]
    assert set(sl) == set(rc.SLEEVES)
    assert sl["roska4_stress"]["instruments"] == {}
    assert sl["roska4_calm"]["instruments"] == {}


# ---------------------------------------------------------------------------
# 13-14. params hash
# ---------------------------------------------------------------------------
def test_params_hash_is_stable_across_processes():
    import subprocess
    code = ("import sys,json; sys.path.insert(0,'.');"
            "import global_index.route_params as rp;"
            "print(rp.params_hash(json.loads(sys.argv[1])))")
    cfg = _cfg()
    out = subprocess.run([sys.executable, "-c", code, json.dumps(cfg)],
                         capture_output=True, text=True, cwd=str(Path.cwd()))
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == rp.params_hash(cfg), (
        "hash must not depend on PYTHONHASHSEED — use hashlib, never hash()")


@pytest.mark.parametrize("field", rp.ALL_FIELDS)
def test_every_params_field_moves_the_hash(field):
    """Mutation-style: change exactly one field, the hash must move.

    A field in the config that does not move the hash is a field the checkpoint is not
    actually protecting — which is the 'fast and wrong' trade this module refuses.
    """
    base = _cfg()
    v = base[field]
    if isinstance(v, bool):
        changed = not v
    elif isinstance(v, (int, float)):
        changed = v + 1
    elif isinstance(v, (list, tuple)):
        changed = list(v) + ["__mutated__"]
    else:
        changed = f"{v}__mutated__"
    assert rp.params_hash(_cfg(**{field: changed})) != rp.params_hash(base), (
        f"{field} does not reach params_hash")
    d = rp.diff(base, _cfg(**{field: changed}))
    assert list(d) == [field], f"diff should name exactly {field}, got {list(d)}"


def test_missing_field_is_refused_not_defaulted():
    cfg = _cfg()
    cfg.pop("ratchet")
    with pytest.raises(rp.MissingParamError):
        rp.params_hash(cfg)


def test_float_precision_cannot_split_equal_configs():
    assert rp.params_hash(_cfg(stop_basis=2.0)) == rp.params_hash(_cfg(stop_basis=2.00))


#: Pinned INDEPENDENTLY of the module. `test_every_params_field_moves_the_hash` is
#: parametrised over `rp.ALL_FIELDS`, so deleting a field from `route_params.FIELDS`
#: deletes its test case too — the suite shrinks instead of going red. Found by mutation
#: check: removing `ratchet` from FIELDS left all 50 tests green. This literal is the
#: independent source that makes that mutation fail.
EXPECTED_PARAM_FIELDS = sorted([
    "ema_period", "max_hold_days",
    "stop_basis", "stop_multiple", "stop_anchor", "ratchet",
    "arm_hour", "arm_timezone",
    "r4_range_threshold", "r4_range_derivation_window", "r4_rel_volume_max",
    # Widened deliberately on 2026-08-22 after the audit found the SPY short gate is part
    # of the measured candidate: the rule alone is not an identity without the file it read
    # and the lag it read it at.
    "spy_short_filter", "spy_short_lookback", "spy_short_lag_days",
    "spy_short_source_identity",
    "hmm_fit_end", "regime_csv_identity", "label_lag_days", "calm_gate_definition",
    "cap_roska4_swing", "cap_roska4_calm", "cap_roska4_stress", "cap_global_nkd",
    "cap_family_normal_calm",
    "slippage_ticks_per_side", "commission_basis",
    "data_source_identity", "fill_law",
    # Widened again on 2026-08-24 (Stage 5Q-9, I-2). Until then the hash named nothing about
    # what an order is routed to, what a contract is worth or how size is derived — so the
    # 2026-08-14 MNKD ten-times-size routing defect would have moved no hash at all.
    "tradable_symbol", "point_value", "tick", "sizing_basis",
])


def test_params_field_set_matches_the_pinned_list():
    """Removing a field from the module must FAIL here, not silently drop a test case."""
    assert sorted(rp.ALL_FIELDS) == EXPECTED_PARAM_FIELDS, (
        "route_params.ALL_FIELDS drifted from the pinned set: "
        f"missing={sorted(set(EXPECTED_PARAM_FIELDS) - set(rp.ALL_FIELDS))} "
        f"unexpected={sorted(set(rp.ALL_FIELDS) - set(EXPECTED_PARAM_FIELDS))}")


@pytest.mark.parametrize("field", EXPECTED_PARAM_FIELDS)
def test_each_pinned_field_moves_the_hash(field):
    """Same assertion as above but driven by the pinned list, so a deleted field is a
    failing test rather than a missing one."""
    assert field in rp.ALL_FIELDS, f"{field} was removed from route_params"
    base = _cfg()
    v = base[field]
    if isinstance(v, bool):
        changed = not v
    elif isinstance(v, (int, float)):
        changed = v + 1
    elif isinstance(v, (list, tuple)):
        changed = list(v) + ["__mutated__"]
    else:
        changed = f"{v}__mutated__"
    assert rp.params_hash(_cfg(**{field: changed})) != rp.params_hash(base), (
        f"{field} does not reach params_hash")


def test_all_fields_are_declared_in_a_group():
    grouped = sorted(n for g in rp.FIELDS.values() for n in g)
    assert grouped == sorted(rp.ALL_FIELDS)
    assert len(grouped) == len(set(grouped)), "a field is declared in two groups"


# ---------------------------------------------------------------------------
# 15-17. window ledger
# ---------------------------------------------------------------------------
def _ledger_files(d: Path):
    return sorted(d.glob("window_coverage_*.jsonl"))


def test_ledger_distinguishes_unobserved_from_observed_quiet(tmp_path, monkeypatch):
    """The whole point: 'nobody watched' must not read as 'nothing happened'."""
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(tmp_path))
    importlib.reload(wl)

    # an observed but quiet Stress window
    wl.window_open("roska4_stress", "2026-08-25")
    for i in range(24):
        wl.slot_observed("roska4_stress", "2026-08-25", f"T1_STRESS_{i:02d}", seq=i)
    wl.window_closed("roska4_stress", "2026-08-25", observed_slots=24, signal=wl.NO_SIGNAL)

    # a window the host slept through: opened, then nothing
    wl.window_open("roska4_stress", "2026-08-26")

    recs = wl.read(_ledger_files(tmp_path))
    quiet = wl.status(recs, "roska4_stress", "2026-08-25")
    slept = wl.status(recs, "roska4_stress", "2026-08-26")

    assert quiet["outcome"] == wl.COMPLETE and quiet["signal"] == wl.NO_SIGNAL
    assert quiet["usable_as_evidence"] is True
    assert slept["outcome"] == wl.UNOBSERVED
    assert slept["usable_as_evidence"] is False
    assert quiet["outcome"] != slept["outcome"], "the two zeros must be distinguishable"


def test_ledger_marks_a_partial_window_incomplete(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(tmp_path))
    importlib.reload(wl)
    wl.window_open("roska4_stress", "2026-08-27")
    for i in range(9):
        wl.slot_observed("roska4_stress", "2026-08-27", f"s{i}", seq=i)
    wl.window_closed("roska4_stress", "2026-08-27", observed_slots=9)
    st = wl.status(wl.read(_ledger_files(tmp_path)), "roska4_stress", "2026-08-27")
    assert st["outcome"] == wl.INCOMPLETE
    assert st["usable_as_evidence"] is False
    assert st["expected_slots"] == 24


def test_ledger_records_an_entered_window(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(tmp_path))
    importlib.reload(wl)
    wl.window_open("roska4_calm", "2026-08-25")
    wl.slot_observed("roska4_calm", "2026-08-25", "T1_CALM_1000", seq=0)
    wl.window_closed("roska4_calm", "2026-08-25", observed_slots=1, signal=wl.ENTERED)
    st = wl.status(wl.read(_ledger_files(tmp_path)), "roska4_calm", "2026-08-25")
    assert st["outcome"] == wl.COMPLETE and st["signal"] == wl.ENTERED
    assert st["expected_slots"] == 1


def test_ledger_disabled_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert not wl.enabled()
    wl.window_open("roska4_stress", "2026-08-25")
    wl.slot_observed("roska4_stress", "2026-08-25", "x")
    wl.window_closed("roska4_stress", "2026-08-25", observed_slots=1)
    assert list(tmp_path.rglob("*")) == [], "ledger wrote while disabled"


def test_ledger_write_failure_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(tmp_path))
    importlib.reload(wl)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", boom)
    wl.window_open("roska4_stress", "2026-08-25")      # must swallow
    wl.window_closed("roska4_stress", "2026-08-25", observed_slots=0)
    monkeypatch.undo()
    assert wl._disabled is True
    wl.window_open("roska4_stress", "2026-08-25")
    assert _ledger_files(tmp_path) == [] or wl.read(_ledger_files(tmp_path)) == []


def test_mutation_ledger_enabled_does_write(tmp_path, monkeypatch):
    """Proves test_ledger_disabled_writes_nothing is not vacuous."""
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(tmp_path))
    importlib.reload(wl)
    wl.window_open("roska4_stress", "2026-08-25")
    assert _ledger_files(tmp_path), "enabling must produce a file"
