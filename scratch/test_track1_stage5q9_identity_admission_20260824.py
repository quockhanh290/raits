"""Stage 5Q-9 — the three blockers Stage 5Q-8 left open, closed and held shut.

READ-ONLY of production data. No scheduler, no backend, no broker, no order.

    I-1  global_nkd declared a stop rule it did not run          -> corrected
    I-3  the sizing basis differed from the artifact by 1.25x    -> measured, then aligned
    I-2  the identity hash carried no tradable identity          -> four fields added

`route_params`'s own docstring sets the rule for adding a field: *a field that cannot be
tested is not added; every name in FIELDS owes a mutation assertion — change that one field,
the hash must move.* The four new names pay that here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import route_params as rp                 # noqa: E402
from global_index import track1_normal_r4 as NR             # noqa: E402
from global_index import run_live_day_track1 as R           # noqa: E402
from global_index import track1_params as tp                # noqa: E402

PATHS = R.default_data_paths()
KW = dict(regime_csv="spy_daily_live.csv", fill_law=tp.LIVE_FILL_LAW)

NEW_FIELDS = ("tradable_symbol", "point_value", "tick", "sizing_basis")


def cfg(sleeve="global_nkd", inst="MNKD"):
    return tp.sleeve_config(sleeve, inst, data_path=PATHS[inst], **KW)


# ── I-2: the four new names, and one mutation each ───────────────────────────────────

def test_the_new_names_are_in_the_hashed_field_list():
    for name in NEW_FIELDS:
        assert name in rp.ALL_FIELDS, name


@pytest.mark.parametrize("field,moved", [
    ("tradable_symbol", "NKD"),      # the 2026-08-14 defect: micro order sent to full-size
    ("point_value", 5.0),            # ten times the intended size
    ("tick", 0.25),
    ("sizing_basis", tp.SIZING_TRUE_STOP),
])
def test_moving_one_new_field_moves_the_hash(field, moved):
    base = cfg()
    assert base[field] != moved, f"{field} fixture does not actually change anything"
    other = {**base, field: moved}
    assert rp.params_hash(base) != rp.params_hash(other)
    assert list(rp.diff(base, other)) == [field]


def test_the_ten_times_size_defect_would_now_be_caught():
    """The concrete case, not an abstraction. On 2026-08-14 MNKD orders were found routing to
    the FULL-SIZE NKD contract — -$1,400.00 at the broker against -$140.00 in the ledger,
    exactly 10.0000x. Correcting that moved no params hash at the time."""
    good = cfg()
    assert good["tradable_symbol"] == "MNK" and good["point_value"] == 0.5
    bad = {**good, "tradable_symbol": "NKD", "point_value": 5.0}
    assert rp.params_hash(good) != rp.params_hash(bad)
    assert set(rp.diff(good, bad)) == {"tradable_symbol", "point_value"}


def test_the_data_identity_and_the_order_identity_are_separate_fields():
    """They are ALLOWED to differ — for MNKD they must. What is not allowed is one standing
    in for the other, which is what a single field would have meant."""
    c = cfg()
    assert "NKD_continuous_1m_8y.parquet" in c["data_source_identity"]
    assert c["tradable_symbol"] == "MNK"
    a = {**c, "data_source_identity": "somewhere/MNK_continuous_1m_8y.parquet:deadbeef"}
    assert rp.params_hash(c) != rp.params_hash(a)
    assert list(rp.diff(c, a)) == ["data_source_identity"]


def test_fill_law_still_moves_the_hash():
    kw = dict(regime_csv="spy_daily_live.csv", data_path=PATHS["MES"])
    a = tp.sleeve_identity("roska4_swing", "MES", fill_law=tp.FILL_ARTIFACT, **kw)[1]
    b = tp.sleeve_identity("roska4_swing", "MES", fill_law=tp.FILL_PRODUCTION, **kw)[1]
    assert a != b


def test_a_missing_new_field_is_refused_not_defaulted():
    """Absent is unknown, and unknown is not the same as equal."""
    for name in NEW_FIELDS:
        broken = {k: v for k, v in cfg().items() if k != name}
        with pytest.raises(rp.MissingParamError):
            rp.params_hash(broken)


def test_the_hash_is_hashlib_and_stable_across_processes():
    """Python's `hash()` is salted per interpreter, so a config would hash differently every
    run and every checkpoint would be refused while looking like it was working."""
    import ast
    import subprocess

    tree = ast.parse(Path(rp.__file__).read_text(encoding="utf-8"))
    builtin = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "hash"]
    assert not builtin, "route_params calls the salted built-in hash()"

    code = ("import sys; sys.path.insert(0, r'%s');"
            "from global_index import track1_params as tp;"
            "from global_index import run_live_day_track1 as R;"
            "print(tp.sleeve_identity('global_nkd','MNKD',regime_csv='spy_daily_live.csv',"
            "data_path=R.default_data_paths()['MNKD'],fill_law=tp.LIVE_FILL_LAW)[1])" % ROOT)
    outs = set()
    for seed in ("0", "1", "12345"):
        import os
        env = {**os.environ, "PYTHONHASHSEED": seed}
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           cwd=str(ROOT), env=env)
        assert r.returncode == 0, r.stderr[-800:]
        outs.add(r.stdout.strip().splitlines()[-1])
    assert len(outs) == 1, f"the hash moved with PYTHONHASHSEED: {outs}"
    assert next(iter(outs)) == rp.params_hash(cfg())


# ── I-3: the sizing basis, and the measurement behind the choice ─────────────────────

def test_the_sizing_basis_table_is_two_and_two():
    assert tp.SIZING_BASIS == {
        "roska4_swing": tp.SIZING_ARTIFACT_ATR,
        "global_nkd": tp.SIZING_ARTIFACT_ATR,
        "roska4_calm": tp.SIZING_TRUE_STOP,
        "roska4_stress": tp.SIZING_TRUE_STOP,
    }
    assert set(tp.SIZING_BASIS) == set(tp.SLEEVE_INSTRUMENTS)


def test_the_proxy_multiple_is_read_from_the_module_that_made_the_artifacts():
    from global_index.signal_layer import NKD_MULT, ROSKA4_MULT
    assert tp.sizing_atr_mult("roska4_swing") == ROSKA4_MULT
    assert tp.sizing_atr_mult("global_nkd") == NKD_MULT


def test_the_two_bases_differ_by_exactly_the_ratio_that_was_measured():
    """2.5 / 2.0 = 1.25, the constant Stage 5Q-8 found on all 938 swing and all 285 NKD
    artifact rows.

    The ratio is 1.25 only where the stop IS the live stop — `entry -+ 2.0 x daily ATR`. The
    first version of this test put the stop two points from the entry with an ATR of four and
    got 5.0, which is the correct answer to a different question; the fixture has to place the
    stop the way the sleeve does or it is not measuring the two bases of the same trade."""
    atr, pv, qty = 4.0, 2.0, 1
    entry = 100.0
    stop = entry - NR.NormalR4Params().stop_basis_atr_mult * atr      # the live stop, derived
    proxy, b1 = tp.risk_dollars("roska4_swing", entry=entry, stop=stop, daily_atr=atr,
                                point_value=pv, qty=qty)
    true_stop = abs(entry - stop) * pv * qty
    assert b1 == tp.SIZING_ARTIFACT_ATR
    assert proxy / true_stop == 1.25
    # and the same ratio for the other proxy sleeve
    proxy_n, _ = tp.risk_dollars("global_nkd", entry=entry, stop=stop, daily_atr=atr,
                                 point_value=pv, qty=qty)
    assert proxy_n / true_stop == 1.25


def test_a_proxy_sleeve_refuses_without_an_atr_rather_than_sizing_light():
    for sleeve in ("roska4_swing", "global_nkd"):
        for atr in (None, 0.0, -1.0, float("nan")):
            with pytest.raises(ValueError):
                tp.risk_dollars(sleeve, entry=100.0, stop=98.0, daily_atr=atr,
                                point_value=2.0, qty=1)


def test_the_true_stop_sleeves_are_unchanged_by_the_atr_argument():
    """The control. Calm and Stress must ignore the ATR entirely — if they ever start reading
    it, their artifacts and their live sizing have parted company."""
    for sleeve in ("roska4_calm", "roska4_stress"):
        a, _ = tp.risk_dollars(sleeve, entry=100.0, stop=98.0, daily_atr=4.0,
                               point_value=2.0, qty=1)
        b, _ = tp.risk_dollars(sleeve, entry=100.0, stop=98.0, daily_atr=999.0,
                               point_value=2.0, qty=1)
        assert a == b == 4.0


def test_the_live_route_sizes_through_the_one_authority():
    """Call site, not implementation. A helper that returns the right number while nothing
    calls it is the shape this repo has been caught by before."""
    import ast

    from global_index import track1_live_source as src
    tree = ast.parse(Path(src.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "risk_dollars"
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "tp"]
    assert len(calls) == 2, f"expected the two proxy sleeves to size through tp, found {len(calls)}"


def test_the_measurement_that_decided_the_basis_is_recorded():
    """A choice this large must not rest on a number that lives only in a chat."""
    import json

    p = Path(__file__).resolve().parent / "_track1_stage5q9_sizing_basis.json"
    if not p.exists():
        pytest.skip("Part B report not present in this checkout")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["verdict"] == "admissions_change"
    assert not d["self_check_failures"]
    assert d["total_changed_admissions"] == 166
    assert set(d["windows"]) == {"floor", "vault2025", "vault2026"}
    for w, r in d["windows"].items():
        assert r["measured"] and all(r["self_checks"].values()), w
    # the direction that matters: one window gets MORE trades and LESS money
    v26 = d["windows"]["vault2026"]
    assert v26["true_stop_distance"]["settlements"] > v26["artifact_basis"]["settlements"]
    assert v26["pnl_delta"] < 0
