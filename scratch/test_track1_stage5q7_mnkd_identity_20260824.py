"""Stage 5Q-7 — the three names an instrument has, and the two that must never collapse.

MNKD carries three identities on purpose:

    runner name     MNKD    what this system calls it everywhere internally
    history symbol  NKD     what its parquet was fetched under (full-size, from 2018)
    order symbol    MNK     what goes on an IBKR order ($0.50 micro)

Two of those were already separated, in August 2026, after live orders for the micro were
routed to the full-size contract and ran at ten times the intended size for four days. The
third was not: `IBKRBroker.fetch_bars` resolves whatever it is handed through the ORDER map,
so the Track 1 live provider asked for MNK and compared the answer against NKD history.

Measured 2026-08-24 20:25 ET, one read-only fetch per arm, same 1,186 shared minutes:

    fetch as MNK  ->  1,155 of 1,186 minutes disagree, median gap 25 pts, signed median 0.0
    fetch as NKD  ->      0 of 1,186 minutes disagree, worst gap 0.0000

These tests hold that split open. They are written against the CALL SITE, not the helper:
a helper that returns the right string while nothing calls it is the shape this repo has
been caught by before.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from futures.basket import BASKET                                  # noqa: E402
from global_index import specs as gi_specs                         # noqa: E402
from global_index import track1_live_source as src                 # noqa: E402
from global_index.ibkr_broker import ibkr_symbol_and_exchange      # noqa: E402
from global_index.update_ibkr_daily import (                       # noqa: E402
    _build_jobs, history_ibkr_symbol,
)

ALL_INSTS = ["MES", "MNQ", "MYM", "M2K", "MNKD"]


class RecordingBroker:
    """A broker that records what symbol it was asked for and returns one plausible bar."""

    def __init__(self):
        self.asked: list[str] = []

    def fetch_bars(self, inst, through):
        self.asked.append(inst)
        idx = pd.date_range("2026-08-24 09:30", periods=3, freq="min")
        return pd.DataFrame(
            {"open": [1.0, 2.0, 3.0], "high": [1.0, 2.0, 3.0],
             "low": [1.0, 2.0, 3.0], "close": [1.0, 2.0, 3.0],
             "volume": [10.0, 10.0, 10.0]},
            index=idx,
        )


# ── the three identities, each read from the layer that owns it ──────────────────────

def test_the_history_symbol_for_mnkd_is_nkd():
    assert history_ibkr_symbol("MNKD") == "NKD"


def test_the_order_symbol_for_mnkd_is_still_mnk():
    """The 2026-08-14 fix. Nothing in Stage 5Q-7 may disturb it."""
    sym, exch = ibkr_symbol_and_exchange("MNKD")
    assert sym == "MNK"
    assert exch == "CME"


def test_the_two_identities_for_mnkd_are_different_strings():
    """If these ever become equal, one of the two defects is back — which one depends on
    which way they collapsed, and both are expensive."""
    assert history_ibkr_symbol("MNKD") != ibkr_symbol_and_exchange("MNKD")[0]


def test_point_value_still_describes_the_micro():
    """Stage 5Q-7 fixes which BARS are fetched. It must not touch what a contract is WORTH:
    point_value drives sizing, risk and realised P&L, never the price of a bar."""
    assert gi_specs.SPECS["MNKD"].point_value == 0.5
    assert gi_specs.SPECS["NKD"].point_value == 5.0


# ── the call site: the provider must ASK for the history symbol ──────────────────────

def test_the_live_provider_asks_the_broker_for_nkd_when_given_mnkd():
    broker = RecordingBroker()
    provider = src.IBKRBarProvider(broker)
    provider.fetch_session_bars("MNKD", through=pd.Timestamp("2026-08-24 15:55"))
    assert broker.asked == ["NKD"], (
        f"the provider asked for {broker.asked} — handing the runner name straight to "
        f"fetch_bars routes through the ORDER map and fetches the micro MNK")


@pytest.mark.parametrize("inst", ["MES", "MNQ", "MYM", "M2K"])
def test_the_four_basket_instruments_are_asked_for_unchanged(inst):
    """The regression that nearly happened. `Contract.data_symbol` for MES is "ES" — the
    FILE STEM, not the fetch symbol — so a fix written against `data_symbol` would have sent
    all four basket instruments at the full-size E-mini contracts to repair the one that
    needed repairing."""
    broker = RecordingBroker()
    provider = src.IBKRBarProvider(broker)
    provider.fetch_session_bars(inst, through=pd.Timestamp("2026-08-24 15:55"))
    assert broker.asked == [inst]


def test_data_symbol_is_not_the_fetch_symbol_and_the_difference_is_load_bearing():
    """Pins the trap itself, so that "simplify this to use data_symbol" fails loudly."""
    disagree = [i for i in ALL_INSTS
                if getattr({**BASKET, **gi_specs.SPECS}[i], "data_symbol") != history_ibkr_symbol(i)]
    assert disagree, "if these ever agree everywhere, re-read why this function exists"
    assert set(disagree) == {"MES", "MNQ", "MYM", "M2K"}


# ── the helper is derived, not declared ──────────────────────────────────────────────

def test_history_symbol_is_derived_from_the_job_table_that_built_the_files():
    """Not a second copy. If `_build_jobs` changes what it fetches, this must follow it."""
    jobs = {j["name"]: j["ibkr_symbol"] for j in _build_jobs(Path("."), Path("."))}
    assert jobs, "the job table is empty — this test would pass vacuously"
    for inst, expected in jobs.items():
        assert history_ibkr_symbol(inst) == expected


def test_every_instrument_the_route_trades_has_an_answer():
    jobs = {j["name"] for j in _build_jobs(Path("."), Path("."))}
    assert set(ALL_INSTS) <= jobs
    for inst in ALL_INSTS:
        assert history_ibkr_symbol(inst)


def test_an_unknown_instrument_answers_with_its_own_name():
    """The behaviour every caller had before this function existed."""
    assert history_ibkr_symbol("ZZZZ") == "ZZZZ"


def test_track1_live_source_delegates_rather_than_keeping_its_own_table():
    """Two tables is how MNKD reached the full-size contract to begin with. Parsed, not
    grepped — a docstring mentioning a symbol must not be able to pass or fail this."""
    import ast

    tree = ast.parse(Path(src.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "history_symbol")
    calls = [n.func.id for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "history_ibkr_symbol" in calls, "history_symbol stopped delegating"
    literals = [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)
                and isinstance(n.value, str) and n.value in {"NKD", "MNK", "MNKD"}]
    assert not literals, f"a symbol literal appeared inside history_symbol: {literals}"


# ── the frozen half is unchanged, and still the full-size series ─────────────────────

def test_the_mnkd_parquet_is_the_nkd_file():
    from global_index import run_live_day_track1 as R

    path = Path(R.default_data_paths()["MNKD"])
    assert path.name.startswith("NKD_"), (
        f"MNKD history is filed as {path.name}; the whole point of the split is that this "
        f"is the full-size series")


def test_the_measured_evidence_is_recorded_next_to_the_fix():
    """The numbers that justified the change must survive in the repo, not only in a chat.

    Guards against the file being emptied or the arms being renamed — a report that no
    longer names both arms cannot be the evidence for a two-arm experiment."""
    import json

    p = Path(__file__).resolve().parent / "_track1_stage5q7_mnkd_identity.json"
    if not p.exists():
        pytest.skip("probe report not present in this checkout")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["verdict"] == "symbol_explains_it"
    assert d["arms"]["MNKD"]["broker_symbol"] == "MNK"
    assert d["arms"]["NKD"]["broker_symbol"] == "NKD"
    assert d["arms"]["NKD"]["disagreeing_bars"] == 0
    assert d["arms"]["MNKD"]["disagreeing_bars"] > 0
    assert d["arms"]["MNKD"]["shared"] == d["arms"]["NKD"]["shared"] > 0
