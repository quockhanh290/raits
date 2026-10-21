"""monitor/test_surfaces_show_the_trading_route.py — the panels must show the route that trades.

Measured 2026-09-24, the first armed day. The route placed two orders, both filled, and:

  * `/api/v1/runner-positions` answered `route=legacy`, `observed_at=2026-09-04`, `positions=[]`
    — a twenty-day-old snapshot of a book nobody writes any more, because legacy is retired.
    An operator opening the positions panel saw nothing while the broker held two contracts.
  * `/api/v1/track1-runtime` had no `orders` key at all, so the order journal — the only file
    that recorded the two fills — appeared on no surface. The fills were found by reading the
    file by hand.

Neither was a lie: the positions endpoint labels its source honestly and carries a note saying
where Track 1's state lives. Both were nonetheless unusable, and for the same reason — the
question an operator asks a positions panel is "what do I hold", and the answer came from a
route that stopped trading on 2026-08-27.

So: the legacy payload stays exactly where it is and keeps its label (something still drains
there), and beside it these surfaces now carry the route that actually trades, and say how old
the legacy snapshot is rather than leaving its date to be noticed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitor.backend.track1_runtime_reader import read_track1_runtime


def _seed(root: Path, *, positions=(), orders=()):
    (root / "global_index" / "track1_runtime" / "orders").mkdir(parents=True, exist_ok=True)
    (root / "live_positions.track1.json").write_text(json.dumps({
        "schema_version": 2, "route": "track1_candidate", "window": "live",
        "positions": list(positions),
    }), encoding="utf-8")
    if orders:
        p = (root / "global_index" / "track1_runtime" / "orders"
             / "track1_orders_20260924.jsonl")
        p.write_text("\n".join(json.dumps(o) for o in orders) + "\n", encoding="utf-8")


def _filled(tid, inst, oid, price):
    return {"candidate_id": tid, "instrument": inst, "state": "filled", "action": "OPEN",
            "qty": 1, "order_id": oid, "avg_price": price, "sleeve": "roska4_swing",
            "slot_id": "TRACK1_SWING_1555", "commission": 0.61, "filled_qty": 0}


def test_sf1_the_order_journal_reaches_a_surface(tmp_path):
    """The two fills of 2026-09-24 existed only in a file no endpoint read."""
    _seed(tmp_path, orders=[_filled("normal_r4::MYM::2026-09-24", "MYM", "28", 51732.0)])
    out = read_track1_runtime(tmp_path)
    assert "orders" in out, "no orders surface at all — the journal is still invisible"
    assert out["orders"]["filled"] == 1
    assert out["orders"]["rows"][0]["instrument"] == "MYM"
    assert out["orders"]["rows"][0]["order_id"] == "28"


def test_sf2_no_orders_yet_is_said_plainly_not_left_blank(tmp_path):
    """Before the first order there is no journal, and "none yet" must not read as "unknown"."""
    _seed(tmp_path)
    out = read_track1_runtime(tmp_path)
    assert out["orders"]["present"] is False
    assert out["orders"]["filled"] == 0
    assert "no order" in str(out["orders"].get("reading", "")).lower()


def test_sf3_a_fill_whose_qty_the_broker_reported_as_zero_is_flagged(tmp_path):
    """Both fills on 2026-09-24 carried `fill_status=FILLED` with `filled_qty: 0`.

    A surface that prints the broker's own number without comment teaches a reader that the
    route filled nothing. A surface that silently substitutes the intended size hides a real
    discrepancy. It gets named instead.
    """
    _seed(tmp_path, orders=[_filled("normal_r4::MYM::2026-09-24", "MYM", "28", 51732.0)])
    out = read_track1_runtime(tmp_path)
    assert out["orders"]["filled_qty_zero"] == 1, (
        "a FILLED order reporting zero quantity passed without a flag")


def test_sf4_once_legacy_is_retired_the_positions_panel_stops_showing_it(monkeypatch, tmp_path):
    """Operator instruction, 2026-09-24: "bỏ phần ảnh chụp legacy đi, legacy retired rồi mà."

    Right, and the measurement agrees. The legacy snapshot the panel was serving had not been
    written since 2026-09-04 — legacy retired on 2026-08-27 and nothing has touched its book
    since. A dead snapshot beside a live one is two answers to "what do I hold", and the older
    one was winning because it was the one in `payload.positions`.

    Kept conditional rather than deleted: while legacy is NOT retired it can still hold
    something, and then it is the only book that can say so.
    """
    from monitor.backend import app as A

    _seed(tmp_path, positions=[{"trade_id": "t", "instrument": "MYM",
                                "direction": "LONG", "qty": 1}])
    monkeypatch.setattr(A, "ROOT", tmp_path)

    with A.app.test_client() as c:
        out = c.get("/api/v1/runner-positions").get_json()
    assert out["route"] == "track1_candidate", f"still serving {out['route']!r}"
    assert len(out["payload"]["positions"]) == 1
    assert "legacy" in out["route_note"] and "retired" in out["route_note"]


def test_sf5_legacy_is_never_served_here_again(monkeypatch, tmp_path):
    """Operator instruction, 2026-09-24: "ko can giu gi cho nhanh legacy, it's done deal."

    The conditional it replaces was a hedge, and a hedge on this question is the defect: a panel
    with two possible answers to "what do I hold" is read by whichever one lands in
    `payload.positions`, and for a month that was a book nothing had written.

    Pinned so a later edit cannot reinstate the branch quietly. Legacy's own file is still on
    disk for anyone auditing it; it is simply not what this endpoint answers.
    """
    from monitor.backend import app as A

    _seed(tmp_path)
    monkeypatch.setattr(A, "ROOT", tmp_path)
    with A.app.test_client() as c:
        out = c.get("/api/v1/runner-positions").get_json()
    assert out["route"] == "track1_candidate"
    assert out["source"] == "live_positions.track1.json"

    import inspect
    src = inspect.getsource(A.api_v1_runner_positions)
    assert "read_runner_positions" not in src, (
        "the legacy reader is back in the positions endpoint")
