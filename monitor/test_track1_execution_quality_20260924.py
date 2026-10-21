"""monitor/test_track1_execution_quality_20260924.py — execution quality describes the route that trades.

Plan stage 4, the execution-quality half. On 2026-09-24 `/api/v1/execution-quality` read
`trade_log.jsonl` — the legacy route's log, newest row 967 hours old — and the page presented it as
execution quality. Track 1's fills reach `trade_log.track1.jsonl` since stage 1. The gate: either
route may be read, but a legacy number is never presented as the current route's.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from monitor.backend import app as app_module
from monitor.backend import execution_quality_reader as eq

REPO = Path(__file__).resolve().parents[1]


def _legacy_log(root: Path) -> None:
    (root / "trade_log.jsonl").write_text(json.dumps({
        "type": "OPEN", "inst": "MES", "direction": "LONG", "contracts": 1, "filled_qty": 1,
        "entry_day": "2026-09-24", "expected_entry": 7765.25, "fill_price": 7799.0,
        "slip": 33.75, "status": "FILLED"}) + "\n", encoding="utf-8")


def _track1_row(root: Path) -> Path:
    """Written by the stage-1 writer itself, so this test reads what production writes."""
    from global_index import track1_paper_send as ps
    from global_index import track1_signal_layer as T
    cand = SimpleNamespace(trade_id="normal_r4::MYM::2026-09-24", instrument="MYM",
                           direction="LONG", contracts=1, entry_price=51747.0,
                           stop_price=50662.29, risk_dollars=677.95,
                           entry_time="2026-09-24 15:55:00")
    dec = SimpleNamespace(verdict=T.TAKE, candidate=cand, sleeve="roska4_swing")
    fill = SimpleNamespace(status="filled", avg_price=51732.0, filled_qty=0, order_id="28",
                           commission=0.61)
    p = root / eq.ROUTE_LOGS["track1_candidate"]
    ps.append_trade_open(fill, dec, trade_log_path=p, slot_id="TRACK1_SWING_1555")
    return p


def test_the_default_is_track1_and_the_legacy_log_is_not_read(tmp_path):
    _legacy_log(tmp_path)
    _track1_row(tmp_path)
    r = eq.read_execution_quality(tmp_path, "2026-09-24")
    assert r["route"] == "track1_candidate"
    assert r["source"].endswith("trade_log.track1.jsonl")
    assert [f["inst"] for f in r["fills"]] == ["MYM"], "a legacy row reached the Track 1 answer"
    f = r["fills"][0]
    # Signalled 51,747, filled 51,732 on a LONG: 15 points in our favour, MYM tick = 1.0.
    assert f["signed_slippage_ticks"] == -15.0 and f["adverse"] is False
    assert f["filled_qty"] == 1.0 and f["partial"] is False


def test_a_track1_row_name_is_not_counted_as_an_execution_venue(tmp_path):
    _track1_row(tmp_path)
    r = eq.read_execution_quality(tmp_path)
    assert r["fills"][0]["route"] is None
    assert r["coverage"]["route_emitted"] == 0


def test_rows_without_the_route_tag_are_not_counted(tmp_path):
    p = _track1_row(tmp_path)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "OPEN", "inst": "MES", "entry_day": "2026-09-24",
                             "fill_price": 1.0, "status": "FILLED"}) + "\n")
    r = eq.read_execution_quality(tmp_path)
    assert len(r["fills"]) == 1 and r["coverage"]["foreign_route_rows"] == 1


def test_no_track1_log_is_not_produced_not_the_legacy_answer(tmp_path):
    _legacy_log(tmp_path)
    r = eq.read_execution_quality(tmp_path)
    assert r["state"] == "not_produced" and r["fills"] == []


def test_legacy_is_readable_only_by_name(tmp_path):
    _legacy_log(tmp_path)
    r = eq.read_execution_quality(tmp_path, route="legacy")
    assert r["route"] == "legacy" and [f["inst"] for f in r["fills"]] == ["MES"]


def test_the_endpoint_serves_track1(monkeypatch, tmp_path):
    _legacy_log(tmp_path)
    _track1_row(tmp_path)
    monkeypatch.setattr(app_module, "ROOT", tmp_path)
    client = app_module.app.test_client()
    for url in ("/api/v1/execution-quality", "/api/v1/execution-quality/2026-09-24"):
        body = client.get(url).get_json()
        assert body["route"] == "track1_candidate", url
        assert [f["inst"] for f in body["fills"]] == ["MYM"], url


def test_the_reader_and_the_writer_name_the_same_file():
    from global_index.track1_report import TRADE_LOG
    assert eq.ROUTE_LOGS["track1_candidate"] == TRADE_LOG
