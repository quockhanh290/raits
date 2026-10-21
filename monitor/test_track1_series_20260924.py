"""monitor/test_track1_series_20260924.py — the per-day series refuses what it cannot prove.

Plan stage 3. The gate the plan set: reproduce a known day to the cent, and REFUSE a day the
series has no evidence for instead of showing zero — a zero reads exactly like "no profit, no
loss".

The known day is 2026-09-24, the first armed day, reproduced from copies of its real rows:
MYM filled 51,732.00 (order 28) and M2K 2,857.00 (order 30), 0.61 commission each, nothing
closed. A second known figure is built by hand so the arithmetic is checkable on paper:
MYM LONG 51,732 -> 51,800, point value 0.50, one contract, 0.61 + 0.61 commission:
68 x 0.50 - 1.22 = 32.78.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from monitor.backend import track1_series_reader as sr

REAL_OPENS = [
    {"type": "OPEN", "route": "track1_candidate", "trade_id": "normal_r4::M2K::2026-09-24",
     "inst": "M2K", "cluster": "roska4_swing", "direction": "LONG", "contracts": 1,
     "entry_day": "2026-09-24", "fill_price": 2857.0, "commission": 0.61, "order_id": "30"},
    {"type": "OPEN", "route": "track1_candidate", "trade_id": "normal_r4::MYM::2026-09-24",
     "inst": "MYM", "cluster": "roska4_swing", "direction": "LONG", "contracts": 1,
     "entry_day": "2026-09-24", "fill_price": 51732.0, "commission": 0.61, "order_id": "28"},
]


def _tree(root: Path, *, audit_days, trade_rows) -> Path:
    rt = root / "global_index" / "track1_runtime"
    for sub in ("orders", "audits", "window_coverage", "regime_label"):
        (rt / sub).mkdir(parents=True, exist_ok=True)
    (rt / "orders" / "track1_orders_20260924.jsonl").write_text(
        json.dumps({"state": "filled", "order_id": "28"}) + "\n", encoding="utf-8")
    for d in audit_days:
        (rt / "audits" / f"track1_audit_{d.replace('-', '')}.jsonl").write_text(
            json.dumps({"scope": "day", "date": d, "verdict": "FAIL"}) + "\n", encoding="utf-8")
    (rt / "regime_label" / "regime_label_20260924.jsonl").write_text(
        json.dumps({"label": "Normal", "label_date": "2026-09-23"}) + "\n"
        + json.dumps({"label": "Stress", "label_date": "2026-09-24"}) + "\n", encoding="utf-8")
    (rt / "trade_log.track1.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in trade_rows), encoding="utf-8")
    return root


def _days(root, today):
    return {d["date"]: d for d in sr.build_series(root, today=today)["days"]}


def test_the_first_armed_day_is_reproduced_to_the_cent(tmp_path):
    root = _tree(tmp_path, audit_days=["2026-09-24"], trade_rows=REAL_OPENS)
    d = _days(root, dt.date(2026, 9, 24))["2026-09-24"]
    assert d["status"] == "evidenced"
    assert sorted((o["inst"], o["fill_price"], o["order_id"]) for o in d["opens"]) == [
        ("M2K", 2857.0, "30"), ("MYM", 51732.0, "28")]
    assert d["open_close_commissions"] == 1.22
    assert d["closes"] == 0 and d["realised_pnl"] == 0.0 and d["cumulative_realised_pnl"] == 0.0
    # The label traded UNDER on 24/9 is 23/9's, not the one written after 24/9's close.
    assert d["regime_traded_under"] == "Normal" and d["regime_label_date"] == "2026-09-23"


def test_a_round_trip_is_priced_from_fills_not_from_pnl_sized(tmp_path):
    close = {"type": "CLOSE", "route": "track1_candidate", "inst": "MYM", "direction": "LONG",
             "contracts": 1, "filled_qty": 1, "entry_day": "2026-09-24", "exit_day": "2026-09-25",
             "fill_price": 51800.0, "commission": 0.61, "exit_reason": "STP",
             "pnl_sized": 999.0}                       # a value that must NOT be used
    root = _tree(tmp_path, audit_days=["2026-09-24", "2026-09-25"],
                 trade_rows=[*REAL_OPENS, close])
    d = _days(root, dt.date(2026, 9, 25))["2026-09-25"]
    assert d["realised_pnl"] == 32.78, d
    assert d["cumulative_realised_pnl"] == 32.78


def test_a_day_without_an_audit_is_refused_and_breaks_the_chain(tmp_path):
    """2026-09-25 (Fri) has no audit. It must be REFUSED — not zero — and every cumulative
    figure after it must be None, because a sum over a gap is not a sum."""
    root = _tree(tmp_path, audit_days=["2026-09-24", "2026-09-28"], trade_rows=REAL_OPENS)
    days = _days(root, dt.date(2026, 9, 28))
    assert list(days) == ["2026-09-24", "2026-09-25", "2026-09-28"], "weekend not skipped"
    gap = days["2026-09-25"]
    assert gap["status"] == "refused" and gap["refusal_reason"]
    assert gap["realised_pnl"] is None and gap["opens"] is None
    assert gap["cumulative_realised_pnl"] is None
    after = days["2026-09-28"]
    assert after["status"] == "evidenced" and after["realised_pnl"] == 0.0
    assert after["cumulative_realised_pnl"] is None, "the chain carried on across a refused day"


def test_today_before_its_audit_is_pending_not_refused_and_not_zero(tmp_path):
    root = _tree(tmp_path, audit_days=["2026-09-24"], trade_rows=REAL_OPENS)
    d = _days(root, dt.date(2026, 9, 25))["2026-09-25"]
    assert d["status"] == "pending" and d["realised_pnl"] is None
    assert d["cumulative_realised_pnl"] is None


def test_a_close_with_no_open_gives_no_realised_figure(tmp_path):
    orphan = {"type": "CLOSE", "route": "track1_candidate", "inst": "MES", "direction": "LONG",
              "contracts": 1, "entry_day": "2026-09-20", "exit_day": "2026-09-24",
              "fill_price": 5000.0}
    root = _tree(tmp_path, audit_days=["2026-09-24"], trade_rows=[*REAL_OPENS, orphan])
    d = _days(root, dt.date(2026, 9, 24))["2026-09-24"]
    assert d["realised_pnl"] is None and d["unpaired_closes"] == [
        {"inst": "MES", "reason": "close_without_open"}]
    assert d["cumulative_realised_pnl"] is None


def test_no_sent_order_means_no_series(tmp_path):
    (tmp_path / "global_index" / "track1_runtime" / "orders").mkdir(parents=True)
    out = sr.build_series(tmp_path, today=dt.date(2026, 9, 24))
    assert out["days"] == [] and out["status"] == "no_paper_epoch"


def test_the_series_is_the_runner_state_snapshots(tmp_path):
    from types import SimpleNamespace
    from monitor.backend import track1_meta_reader as tm
    _tree(tmp_path, audit_days=["2026-09-24"], trade_rows=REAL_OPENS)
    out = tm.build(tmp_path, ibkr_cache={},
                   b1_latest=lambda r: SimpleNamespace(inputs={}, checked_at=None, status=None))
    snaps = out["payload"]["snapshots"]
    assert snaps and snaps[0]["date"] == "2026-09-24"
    assert out["payload_sources"]["snapshots"]["source"]
    assert "snapshots" not in out["payload_absent"]
