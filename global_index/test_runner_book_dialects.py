from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from futures.circuit_breaker import CircuitBreaker
from global_index.broker import MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner, _openpos_from_dict, _openpos_to_dict
from global_index.track1_b1 import BOOK_READ, read_track1_book
from global_index.track1_signal_layer import read_route_positions, seed_open_positions
from global_index.track1_slots import TRACK1_BOOK_SCHEMA, TRACK1_ROUTE


GOLDEN = Path(__file__).with_name("test_runner_book_dialect_golden.json")
DIALECT_KEYS = {"inst", "contracts", "cluster"}


def _json_values(value):
    return json.loads(json.dumps(value, default=str))


def _required_row(**overrides):
    row = {
        "inst": "MES",
        "direction": "LONG",
        "contracts": 2,
        "risk_dollars": 125.5,
        "cluster": "roska4_swing",
    }
    row.update(overrides)
    return row


def _position() -> OpenPos:
    return OpenPos(
        inst="MNKD",
        direction="LONG",
        contracts=3,
        risk_dollars=1761.25,
        cluster="global_nkd",
        entry_day=pd.Timestamp("2026-09-25"),
        stop_price=63321.5,
        stop_order_id="40",
        entry_price=66145.0,
        contract_month="202612",
    )


def _make_guard() -> MultiClusterGuard:
    return MultiClusterGuard(
        clusters={
            "roska4_swing": ClusterBudget("roska4_swing", max_gross_pct=0.05, max_net_pct=0.044),
            "global_nkd": ClusterBudget("global_nkd", max_gross_pct=0.02, max_net_pct=0.02),
        },
        account=50_000,
    )


def _make_runner_for_book(path: Path, *, route=None) -> FuturesRunner:
    return FuturesRunner(
        broker=MockBroker({}, account=50_000),
        guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda day, bars, held: ([], []),
        breaker=CircuitBreaker(account=50_000),
        positions_path=path,
        route=route,
    )


def test_existing_unparseable_book_refuses_without_rewriting_bytes(tmp_path):
    path = tmp_path / "live_positions.json"
    original = b'{"positions": ['
    path.write_bytes(original)

    with pytest.raises(RuntimeError) as caught:
        _make_runner_for_book(path)

    message = str(caught.value)
    assert str(path) in message
    assert "JSONDecodeError" in message
    assert "Expecting" in message
    assert path.read_bytes() == original


def test_g1_prechange_golden_equivalence_and_only_dialect_keyerrors_are_rescued():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    records = golden["records"]
    assert records, "the pre-change golden set must contain position rows"
    assert sum(item["outcome"] == "loaded" for item in records) == 5
    assert sum(item["outcome"] == "raised" for item in records) == 5

    rescued = 0
    for item in records:
        if item["outcome"] == "loaded":
            actual = _json_values(dataclasses.asdict(_openpos_from_dict(item["input"])))
            assert actual == item["values"], (item["path"], item["index"])
            continue

        was_dialect_keyerror = (
            item["exception_type"] == "KeyError"
            and item["exception_args"]
            and item["exception_args"][0] in DIALECT_KEYS
        )
        if was_dialect_keyerror:
            loaded = _openpos_from_dict(item["input"])
            assert loaded.inst == item["input"]["instrument"]
            assert loaded.contracts == int(item["input"]["qty"])
            assert loaded.cluster == item["input"]["sleeve"]
            rescued += 1
        else:
            with pytest.raises(Exception) as caught:
                _openpos_from_dict(item["input"])
            assert type(caught.value).__name__ == item["exception_type"]
            assert list(caught.value.args) == item["exception_args"]

    assert rescued == 5


def test_g2_track1_dialect_loads_the_three_values():
    loaded = _openpos_from_dict({
        "instrument": "M2K",
        "direction": "SHORT",
        "qty": 4,
        "risk_dollars": 469.4643,
        "sleeve": "roska4_swing",
    })
    assert loaded.inst == "M2K"
    assert loaded.contracts == 4
    assert loaded.cluster == "roska4_swing"


@pytest.mark.parametrize(
    ("legacy", "track1"),
    [("inst", "instrument"), ("contracts", "qty"), ("cluster", "sleeve")],
)
def test_g3_neither_spelling_still_raises_keyerror(legacy, track1):
    row = _required_row()
    row.pop(legacy)
    row.pop(track1, None)
    with pytest.raises(KeyError) as caught:
        _openpos_from_dict(row)
    assert caught.value.args == (legacy,)


@pytest.mark.parametrize(
    ("legacy", "track1", "other"),
    [
        ("inst", "instrument", "MYM"),
        ("contracts", "qty", 7),
        ("cluster", "sleeve", "global_nkd"),
    ],
)
def test_g4_conflicting_spellings_raise_and_name_the_field(legacy, track1, other):
    row = _required_row()
    row[track1] = other
    with pytest.raises(ValueError) as caught:
        _openpos_from_dict(row)
    message = str(caught.value)
    assert legacy in message
    assert track1 in message


def test_g5_g6_writer_round_trip_and_both_reader_dialects(tmp_path):
    original = _position()
    written = _openpos_to_dict(original)

    assert written["inst"] == written["instrument"] == original.inst
    assert written["contracts"] == written["qty"] == original.contracts
    assert written["cluster"] == written["sleeve"] == original.cluster

    loaded = _openpos_from_dict(written)
    assert _json_values(dataclasses.asdict(loaded)) == _json_values(dataclasses.asdict(original))

    # The runner's OpenPos model has no trade_id. Add the route-owned identity that
    # seed_open_positions independently requires; every field emitted by the writer is unchanged.
    route_row = dict(written, trade_id="global_nkd::MNKD::2026-09-25")
    path = tmp_path / "live_positions.track1.json"
    path.write_text(json.dumps({
        "schema_version": TRACK1_BOOK_SCHEMA,
        "route": TRACK1_ROUTE,
        "positions": [route_row],
    }), encoding="utf-8")

    route_rows = read_route_positions(path)
    assert len(route_rows) == 1
    assert route_rows[0]["instrument"] == "MNKD"
    assert route_rows[0]["qty"] == 3
    assert route_rows[0]["sleeve"] == "global_nkd"

    book = SimpleNamespace(open_book=[])
    assert seed_open_positions(book, route_rows) == 1
    assert book.open_book[0].position.instrument == "MNKD"
    assert book.open_book[0].position.contracts == 3
    assert book.open_book[0].position.cluster == "global_nkd"

    state = read_track1_book(path)
    assert state.state == BOOK_READ
    assert state.count == 1
    assert state.positions[0]["qty"] == 3


def test_g6_legacy_writer_fields_remain_present_and_unchanged():
    original = _position()
    written = _openpos_to_dict(original)
    assert written["inst"] == original.inst
    assert written["contracts"] == original.contracts
    assert written["cluster"] == original.cluster


def test_route_safety_persist_preserves_position_identity_and_provenance(tmp_path):
    """A no-op safety sweep must not turn a readable Track 1 row into an anonymous one."""
    position = _position()
    source_row = dict(
        _openpos_to_dict(position),
        trade_id="global_nkd::MNKD::2026-09-25",
        order_id="38",
        slot_id="TRACK1_NKD_0125",
        booked_from="track1_paper_send",
    )
    path = tmp_path / "live_positions.track1.json"
    path.write_text(json.dumps({
            "schema_version": TRACK1_BOOK_SCHEMA,
            "route": TRACK1_ROUTE,
            "window": "live",
            "positions": [source_row],
    }), encoding="utf-8")
    runner = _make_runner_for_book(path, route=TRACK1_ROUTE)
    runner.state.open_positions[0].stop_order_id = "41"

    runner._persist_state()

    persisted = json.loads(path.read_text(encoding="utf-8"))["positions"][0]
    assert persisted["trade_id"] == source_row["trade_id"]
    assert persisted["order_id"] == source_row["order_id"]
    assert persisted["slot_id"] == source_row["slot_id"]
    assert persisted["booked_from"] == source_row["booked_from"]
    assert persisted["stop_order_id"] == "41", "new safety state must win over the source row"
