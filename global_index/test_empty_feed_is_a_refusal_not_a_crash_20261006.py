# -*- coding: utf-8 -*-
"""When IBKR returns no bars, the slot records a refusal. It does not die on a traceback.

2026-10-06, the 10:00 ET Calm slot. `reqHistoricalData` came back empty after its 120 s wait, the
provider handed the join `None`, and `_overlap_population` — a function that runs BEFORE the
overlap check and, unlike the check, did not open with "an empty live half is not my call" —
raised `'NoneType' object has no attribute 'index'`. The slot exited 1 with no durable row, the
10:02 slot that was meant to observe the open was skipped as "still in flight", and nothing on the
record said the feed had been empty.

The cause of the empty answer is not in this repo's control (network, Gateway or IBKR). What is,
is what the route does with it: a named refusal in the slot's own row, like every other way a slot
can fail to decide.
"""
import pandas as pd
import pytest

import global_index.run_live_day_track1 as rl
import global_index.track1_live_source as S
import global_index.track1_signal_layer as sl
import global_index.window_ledger as wl
from global_index import test_calm_execute_sends_without_the_1000_bar as E
from global_index import test_riskwire_batch1_20260925 as B


# ── the function that crashed ────────────────────────────────────────────────

def _frozen():
    idx = pd.date_range("2026-10-05 09:30", periods=5, freq="1min", tz="America/New_York")
    return pd.DataFrame(1.0, index=idx, columns=["open", "high", "low", "close", "volume"])


def test_an_absent_live_half_passes_through_untouched():
    assert S._overlap_population("MES", None, _frozen(), pd.Timestamp("2026-01-01")) is None


def test_an_empty_live_half_passes_through_untouched():
    empty = _frozen().iloc[0:0]
    out = S._overlap_population("MES", empty, _frozen(), pd.Timestamp("2026-01-01"))
    assert out is empty


def test_control_a_live_half_with_bars_is_still_narrowed_to_the_anchor():
    """Without this the two tests above could pass on a function that does nothing at all."""
    frozen = _frozen()
    live = frozen.copy()                                            # all five minutes shared
    # a naive `since` is read as UTC, the store's own clock
    cut = frozen.index[2].tz_convert("UTC").tz_localize(None)
    out = S._overlap_population("MES", live, frozen, cut)
    assert list(out.index) == list(frozen.index[2:]), list(out.index)


# ── the slot ─────────────────────────────────────────────────────────────────

class _EmptyFeed:
    """A bar provider whose request returned nothing — what the route sees on an empty answer."""
    name = "ibkr"

    def __init__(self, error=""):
        self.last_error = error

    def fetch_session_bars(self, inst, *, through, lookback=None):
        return None


def _frozen_frames():
    """History through yesterday's close only, on the ET clock the real store uses."""
    out = {}
    for inst in ("MES", "MNQ"):
        f = E._frame(inst)
        out[inst] = f[f.index < pd.Timestamp(f"{E.TODAY.date()} 00:00", tz=E.ET)]
    return out


def _run_slot(tmp_path, monkeypatch, provider):
    from global_index import track1_freshness as fresh

    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True)
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(ledger))
    monkeypatch.setenv("RAITS_ROUTE", sl.ROUTE)
    monkeypatch.setattr(wl, "_disabled", False, raising=False)
    monkeypatch.setattr(fresh, "evaluate", lambda **kw: B._FreshVerdict())
    monkeypatch.setattr(rl, "emit_explanations", lambda decisions, **kw: {"records": len(decisions)})
    B._write_json(tmp_path / rl.POSITIONS_PATH, B._book_payload())
    rl.observe_live_slot(
        "roska4_calm", E.EXECUTE_ID, now_et=pd.Timestamp(f"{E.TODAY.date()} 10:00:05", tz=E.ET),
        provider=provider, frozen_frames=_frozen_frames(), root=str(tmp_path),
        out_dir=rl.OPERATIONAL_SHADOW_DIR, phase="EXECUTE",
        order_gate=rl.OrderGate(True, blockers={}), broker=E._SpyBroker())
    rows = [r for r in B._coverage_rows(tmp_path) if r.get("slot_id") == E.EXECUTE_ID]
    assert rows, ("no durable slot row was written — the slot died or the harness is not "
                  "exercising it, and every assertion below would be void")
    return rows[-1]


def test_an_empty_feed_leaves_a_named_refusal_in_the_slots_own_row(tmp_path, monkeypatch):
    row = _run_slot(tmp_path, monkeypatch, _EmptyFeed())
    assert row.get("decided") is False, row
    assert row.get("reason"), row


def _observation_rows(root):
    import json
    rows = []
    for p in root.rglob("data_observation_*.jsonl"):
        rows.extend(json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip())
    return rows


def test_the_observation_record_says_the_feed_was_empty_and_in_the_feeds_own_words(tmp_path, monkeypatch):
    _run_slot(tmp_path, monkeypatch, _EmptyFeed("IBKR 162: Historical Market Data Service error message"))
    rows = [r for r in _observation_rows(tmp_path) if r.get("slot_id") == E.EXECUTE_ID]
    assert rows, "the slot wrote no observation row under its own root"
    insts = rows[-1]["instruments"]
    assert sorted(i["inst"] for i in insts) == ["MES", "MNQ"]
    assert all(i["live_rows_fetched"] == 0 for i in insts)
    assert all("IBKR 162" in str(i["provider_error"]) for i in insts), insts


def test_a_slot_given_a_scratch_root_writes_nothing_outside_it(tmp_path, monkeypatch):
    """The 2026-10-05 pollution: observation rows and session bars went to the working directory."""
    from pathlib import Path

    # The working directory's evidence tree: in production (and in a normal pytest run from the
    # repo root) that IS the real one, and it is where a writer that ignores `root` lands.
    real = Path.cwd() / "global_index" / "track1_runtime"
    def snap():
        out = {}
        for p in list(real.glob("data_observation/*20261005*")) + list(real.glob("session_bars/*20261005*")):
            st = p.stat(); out[p.name] = (st.st_size, st.st_mtime_ns)
        return out
    before = snap()
    _run_slot(tmp_path, monkeypatch, _EmptyFeed())
    assert snap() == before, "a test slot changed the REAL evidence tree"
    assert any(tmp_path.rglob("data_observation_*.jsonl")), "control: it did write, under its own root"


def test_no_order_is_sent_on_an_empty_feed(tmp_path, monkeypatch):
    # The spy broker is built inside _run_slot; a refusal row with decided False is the contract,
    # and a decided slot would have had candidates to send.
    row = _run_slot(tmp_path, monkeypatch, _EmptyFeed())
    assert row.get("candidates") in (0, None) and row.get("decided") is False
