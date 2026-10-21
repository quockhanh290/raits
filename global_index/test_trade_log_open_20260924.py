"""global_index/test_trade_log_open_20260924.py — a confirmed fill reaches all THREE records.

Plan stage 1. Measured 2026-09-24, the first armed day:

    order journal   track1_orders_20260924.jsonl     MYM filled 51,732.00 (order 28)
                                                     M2K filled  2,857.00 (order 30)
    book            live_positions.track1.json       positions: []   (back-filled 18:50 ET)
    trade log       trade_log.track1.jsonl           0 rows, last written 2026-08-25

The book seam was closed that afternoon (`test_book_advance.py`). The trade log is the same
seam one record further on: the safety sweeps append CLOSE rows to it, so without an OPEN row
every close the route books is a close of a position the log never saw opened, and a P&L series
cannot be built from half of each round trip.

The gate the plan set: one send under a temp `root` writes all three files, and touches NO file
in the repository — checked by listing files before and after, not only by finding the temp
files populated. The same afternoon, a writer that defaulted to the production path put two
fixture rows into the live book.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from global_index import track1_order_state as st  # noqa: E402
from global_index import track1_paper_send as ps  # noqa: E402
from global_index import track1_report as tr  # noqa: E402


# ── stubs, shaped on the interfaces the executor reads ───────────────────────

class _Gate:
    allow_orders = True


class _Cand:
    def __init__(self, tid="normal_r4::MYM::2026-09-24", inst="MYM", direction="LONG",
                 entry=51747.0):
        self.trade_id = tid
        self.sleeve = "roska4_swing"
        self.instrument = inst
        self.direction = direction
        self.contracts = 1
        self.qty = 1
        self.entry_price = entry
        self.stop_price = 50662.29
        self.risk_dollars = 677.95
        self.entry_time = "2026-09-24 15:55:00"


class _Decision:
    def __init__(self, cand=None):
        from global_index import track1_signal_layer as T
        self.verdict = T.TAKE
        self.candidate = cand or _Cand()
        self.sleeve = "roska4_swing"


class _Fill:
    # 2026-09-24's real fills: FILLED, filled_qty 0 — which `broker.Fill` documents as a full fill.
    def __init__(self, status=st.FILLED, order_id="28", filled_qty=0, avg_price=51732.0):
        self.status = status
        self.order_id = order_id
        self.filled_qty = filled_qty
        self.avg_price = avg_price
        self.commission = 0.61
        self.error_msg = ""


class _Broker:
    """Every method the executor requires; nothing that reaches a network."""

    def __init__(self, fill=None):
        self._fill = fill or _Fill()
        self.calls: list = []

    def send_order(self, order, on_submit=None, **kw):
        self.calls.append(order)
        return self._fill

    def get_order_status(self, order_id):
        return {"order_id": order_id, "status": st.FILLED}

    def place_stop(self, *a, **k):
        return _Fill(order_id="STOP-1")

    def get_open_orders(self):
        return []

    def get_positions(self):
        return []

    def cancel_order(self, *a, **k):
        return True

    def get_equity(self):
        return 251_341.45


def _seed_book(root: Path) -> Path:
    # `track1_report.BOOK`, not the executor's `BOOK_PATH`: the 5Z suite forbids any module
    # outside the send seam from importing the executor, tests included. If the two constants
    # ever part, tl1 fails on "BOOK NOT ADVANCED" — which is the check that they agree.
    p = Path(root) / tr.BOOK
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                             "window": "live", "positions": []}), encoding="utf-8")
    return p


def _rows(p: Path) -> list:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _repo_state_listing() -> dict:
    """Every file a Track 1 writer could plausibly reach in the repo, with size and mtime.

    The repo root (non-recursive: the book and the legacy trade log live there), the whole
    Track 1 runtime tree, and the top of `global_index`. Not the parquet caches — no writer
    here goes near them, and walking them would make this test slow for nothing."""
    out = {}
    places = [(REPO, False), (REPO / "global_index", False),
              (REPO / "global_index" / "track1_runtime", True)]
    for base, recursive in places:
        it = base.rglob("*") if recursive else base.glob("*")
        for f in it:
            if f.is_file() and "__pycache__" not in f.parts and not f.name.endswith(".pyc"):
                s = f.stat()
                out[str(f)] = (s.st_size, s.st_mtime_ns)
    return out


# ── the gate ─────────────────────────────────────────────────────────────────

def test_tl1_one_send_under_a_temp_root_writes_all_three_and_nothing_in_the_repo(tmp_path):
    before = _repo_state_listing()
    assert len(before) > 20, "the listing saw almost nothing — it would miss a stray write"

    book = _seed_book(tmp_path)
    s = ps.maybe_send_orders([_Decision()], order_gate=_Gate(), broker=_Broker(),
                             ref_day="2026-09-24", slot_id="TRACK1_SWING_1555", root=tmp_path)
    assert s.filled == 1 and not s.errors, s.as_dict()

    journal = list((tmp_path / tr.ORDERS_DIR).glob("track1_orders_*.jsonl"))
    assert journal and any(r.get("state") == "filled" for r in _rows(journal[0])), \
        "the order journal did not record the fill"
    book_rows = json.loads(book.read_text(encoding="utf-8"))["positions"]
    assert [r["instrument"] for r in book_rows] == ["MYM"], "the book did not record the fill"
    trade = _rows(tmp_path / tr.TRADE_LOG)
    assert [(r["type"], r["inst"], r["route"]) for r in trade] == \
        [("OPEN", "MYM", "track1_candidate")], f"the trade log did not record the fill: {trade}"

    after = _repo_state_listing()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert not changed, f"a send under a temp root changed files in the repo: {changed}"


def test_tl2_the_row_is_one_the_track1_reader_counts(tmp_path):
    """Written for its reader, not for itself: `track1_report.read_trade_log` rejects a row
    whose route is not track1_candidate, so a row it would reject is a row that does not exist."""
    _seed_book(tmp_path)
    ps.maybe_send_orders([_Decision()], order_gate=_Gate(), broker=_Broker(),
                         ref_day="2026-09-24", slot_id="TRACK1_SWING_1555", root=tmp_path)
    got = tr.read_trade_log(tmp_path)
    assert got["state"] == tr.AVAILABLE and got["rows"] == 1 and got["invalid_rows"] == 0, got


def test_tl3_the_row_carries_the_legacy_open_keys_plus_the_join_keys(tmp_path):
    p = tmp_path / "t.jsonl"
    assert ps.append_trade_open(_Fill(), _Decision(), trade_log_path=p,
                                ref_day="2026-09-24", slot_id="TRACK1_SWING_1555")
    (r,) = _rows(p)
    legacy_open_keys = {"type", "inst", "cluster", "direction", "contracts", "entry_day",
                        "expected_entry", "fill_price", "commission", "filled_qty", "status",
                        "regime"}
    assert legacy_open_keys <= set(r), legacy_open_keys - set(r)
    assert r["trade_id"] == "normal_r4::MYM::2026-09-24" and r["order_id"] == "28"
    assert r["slot_id"] == "TRACK1_SWING_1555" and r["entry_day"] == "2026-09-24"
    # filled_qty 0 is the broker's "full fill"; the raw figure travels beside it.
    assert r["filled_qty"] == 1 and r["fill_reported_qty"] == 0
    # Adverse positive: a LONG signalled at 51,747 and filled at 51,732 paid 15 points LESS.
    assert r["slip"] == pytest.approx(-15.0)


def test_tl4_a_short_uses_the_other_sign(tmp_path):
    p = tmp_path / "t.jsonl"
    ps.append_trade_open(_Fill(avg_price=100.0),
                         _Decision(_Cand(tid="x::MNQ::d", inst="MNQ", direction="SHORT",
                                         entry=101.0)),
                         trade_log_path=p)
    assert _rows(p)[0]["slip"] == pytest.approx(1.0), "a SHORT filled below its signal paid up"


@pytest.mark.parametrize("status", ["unknown", "", "rejected", st.PARTIAL])
def test_tl5_only_a_confirmed_fill_is_logged(tmp_path, status):
    p = tmp_path / "t.jsonl"
    assert not ps.append_trade_open(_Fill(status=status), _Decision(), trade_log_path=p)
    assert _rows(p) == []


def test_tl6_the_same_trade_twice_is_one_row(tmp_path):
    """The 2026-09-24 signal was re-sent across three slots under one idempotency key."""
    p = tmp_path / "t.jsonl"
    assert ps.append_trade_open(_Fill(), _Decision(), trade_log_path=p)
    assert not ps.append_trade_open(_Fill(), _Decision(), trade_log_path=p)
    assert len(_rows(p)) == 1


def test_tl7_neither_writer_has_a_production_default():
    """The property that would have prevented this afternoon's contamination, by signature."""
    import inspect
    for fn, arg in ((ps.advance_book, "book_path"), (ps.append_trade_open, "trade_log_path")):
        param = inspect.signature(fn).parameters[arg]
        assert param.default is inspect.Parameter.empty, (
            f"{fn.__name__}({arg}=...) has a default again — a test that reaches a fill would "
            f"write wherever that default points")


def test_tl8_the_writer_and_the_sweeps_name_the_same_file():
    """The sweeps append CLOSE rows via `track1_slots`; the reader and this writer use
    `track1_report`. Two constants for one file are two chances for OPEN and CLOSE to part."""
    from global_index.track1_slots import TRACK1_TRADE_LOG_PATH
    assert TRACK1_TRADE_LOG_PATH == tr.TRADE_LOG


def test_tl9_a_book_failure_does_not_cost_the_trade_log_its_row(tmp_path):
    """No book under root → the book write fails; the trade log must still be written, and the
    error must name the book, not the trade log."""
    s = ps.maybe_send_orders([_Decision()], order_gate=_Gate(), broker=_Broker(),
                             ref_day="2026-09-24", slot_id="TRACK1_SWING_1555", root=tmp_path)
    assert any("BOOK NOT ADVANCED" in e for e in s.errors), s.errors
    assert not any("TRADE LOG NOT WRITTEN" in e for e in s.errors), s.errors
    assert len(_rows(tmp_path / tr.TRADE_LOG)) == 1
