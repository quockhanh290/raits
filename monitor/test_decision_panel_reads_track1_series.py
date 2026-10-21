"""The decision panel must read a Track 1 snapshot, and must not turn absent evidence into zero.

2026-09-24, evening. Reported from the live page: the book section was not showing. Measured on
the real backend rather than a stub, because the question was about the live page:

    /api/v1/runner-positions   2 positions, error null      -> Open Positions rendered both
    /api/v1/runner-state       1 snapshot, date 2026-09-24,  -> "Decision unavailable",
                               `opens` = 2 rows, NO          Entered / Closed / Rejected
                               `decision` key                all showing `--`

`renderDecisions` and `journalRows` read `snap.decision` and nothing else. Stage 3 of the
dashboard migration replaced the legacy snapshot with a Track 1 per-day series that has no such
key, so on the first day the route actually traded, the panel that exists to show what it did went
blank. Same defect family as `pos.inst` against `pos.instrument`, which was normalised for the
positions panel that morning and not here.

The shape is asymmetric and the adapter has to carry that through rather than smooth it:

    opens      a list with detail       -> entries, rendered in full
    closes     an integer COUNT         -> a count; per-close detail is not in the series
    rejected   no counterpart at all    -> absent, and absent is not zero

The last one is the assertion worth having. `0 rejected` reads as "nothing was rejected today",
which this series cannot say, and the stage-3 plan's own gate calls for refusing a day rather than
showing a 0 that reads like an answer.
"""
from __future__ import annotations

import json

from monitor.test_realtime_dom import (          # noqa: E402
    BASE_PAYLOADS, browser_page, open_realtime, realtime_server, stub_api)

assert browser_page and realtime_server          # re-exported fixtures, used by pytest


#: The live snapshot of 2026-09-24, field for field, including the types: `opens` is a list of
#: dicts and `closes` is an integer. Copied from the running endpoint, not invented — a fixture
#: that guessed `closes` was a list would have tested a shape the backend never serves.
T1_SNAPSHOT = {
    "audit_verdict": "FAIL",
    "closes": 0,
    "cumulative_realised_pnl": 0.0,
    "date": "2026-09-24",
    "open_close_commissions": 1.22,
    "opens": [
        {"contracts": 1, "direction": "LONG", "fill_price": 2857.0, "inst": "M2K",
         "order_id": "30", "sleeve": "roska4_swing"},
        {"contracts": 1, "direction": "LONG", "fill_price": 51732.0, "inst": "MYM",
         "order_id": "28", "sleeve": "roska4_swing"},
    ],
    "realised_pnl": 0.0,
    "refusal_reason": None,
    "regime_label_date": "2026-09-23",
    "regime_traded_under": "Normal",
    "status": "evidenced",
    "unpaired_closes": None,
    "window_coverage_rows": 79,
}


def _runner_state(snapshot=None, **over):
    """A runner-state response carrying a Track 1 series, shaped like the live one: the payload is
    Track 1's while `observed_at` and `source_era` still describe the retired legacy producer."""
    base = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/runner-state"]))
    base["payload"] = {"meta": (base.get("payload") or {}).get("meta") or {},
                       "runner_health": {},
                       "snapshots": [snapshot or json.loads(json.dumps(T1_SNAPSHOT))]}
    base["payload_era"] = "track1"
    base["source_era"] = "legacy"
    base["observed_at"] = "2026-08-24T06:58:47.545152Z"
    base["built_at"] = "2026-09-25T03:22:07.236688Z"
    base.update(over)
    return base


def _text(page, sel):
    return page.eval_on_selector(sel, "el => el.innerText.split('\\n').join(' | ')")


# ── the defect, stated as the thing that must render ─────────────────────────────────────────

def test_1_the_entries_come_from_opens(browser_page, realtime_server):
    stub_api(browser_page, {"/api/v1/runner-state": _runner_state()})
    open_realtime(browser_page, realtime_server)

    assert _text(browser_page, "#decisionEntryCount").strip() == "2", (
        "the panel counted %r entries against a snapshot holding two opens"
        % _text(browser_page, "#decisionEntryCount"))
    entries = _text(browser_page, "#decisionEntries")
    for token in ("M2K", "MYM", "LONG", "roska4_swing", "2,857", "51,732"):
        assert token in entries, f"{token!r} missing from the entries list: {entries!r}"
    assert "No open entries" not in entries


def test_2_the_regime_comes_from_the_track1_field(browser_page, realtime_server):
    """`snap.regime` is the legacy spelling; a Track 1 snapshot says `regime_traded_under`. The
    summary read "Unknown" on a day the route traded under a known regime."""
    stub_api(browser_page, {"/api/v1/runner-state": _runner_state()})
    open_realtime(browser_page, realtime_server)
    summary = _text(browser_page, "#decisionSummary")
    assert "Normal" in summary, summary
    assert "Unknown" not in summary, summary


def test_3_absent_rejected_evidence_is_not_reported_as_zero(browser_page, realtime_server):
    """The assertion this file exists for. Nothing in the series carries rejected or halted
    candidates, so a `0` in that box would be a claim the data cannot support."""
    stub_api(browser_page, {"/api/v1/runner-state": _runner_state()})
    open_realtime(browser_page, realtime_server)

    count = _text(browser_page, "#decisionRejectedCount").strip()
    assert count == "--", (
        "the rejected box reads %r; a number there says the series measured rejections, and it "
        "holds none" % count)
    box = _text(browser_page, "#decisionRejected")
    assert "not measured" in box.lower(), box
    assert "No rejected or halted entries" not in box, (
        "the box asserts there were none, which this series cannot say")


def test_4_a_counted_close_with_no_detail_says_so(browser_page, realtime_server):
    """`closes` is an integer. A count of 3 with no per-close rows must not render as "No closes
    in this decision" — the sentence and the number would contradict each other."""
    snap = json.loads(json.dumps(T1_SNAPSHOT))
    snap["closes"] = 3
    payload = _runner_state()
    payload["payload"]["snapshots"] = [snap]
    stub_api(browser_page, {"/api/v1/runner-state": payload})
    open_realtime(browser_page, realtime_server)

    assert _text(browser_page, "#decisionCloseCount").strip() == "3"
    box = _text(browser_page, "#decisionCloses")
    assert "not part of it" in box.lower() or "detail is not" in box.lower(), box
    assert "No closes in this decision" not in box


def test_5_a_genuine_zero_still_reads_as_zero(browser_page, realtime_server):
    """The other direction, and the reason test_4 is not simply "never say no closes". When the
    series counts zero closes, zero IS the evidence and the old sentence is correct."""
    stub_api(browser_page, {"/api/v1/runner-state": _runner_state()})
    open_realtime(browser_page, realtime_server)
    assert _text(browser_page, "#decisionCloseCount").strip() == "0"
    assert "No closes in this decision" in _text(browser_page, "#decisionCloses")


def test_6_the_source_line_does_not_mix_two_eras(browser_page, realtime_server):
    """It printed "2026-09-24 / runner 08-24, 02:58 ET": a Track 1 snapshot date beside the legacy
    runner's last dump, a month older, with the word "runner" attached to the older one. The
    endpoint itself distinguishes them — `payload_era: track1`, `source_era: legacy`."""
    stub_api(browser_page, {"/api/v1/runner-state": _runner_state()})
    open_realtime(browser_page, realtime_server)
    src = _text(browser_page, "#decisionSource")
    assert "2026-09-24" in src, src
    assert "08-24" not in src, (
        "the source line still carries the legacy runner's timestamp: %r" % src)
    assert "Track 1 series" in src, src


def test_7_a_legacy_snapshot_still_renders_the_legacy_way(browser_page, realtime_server):
    """The adapter must not have replaced the old path. A snapshot carrying a real `decision`
    object is still read from it, untouched."""
    snap = {"date": "2026-08-24", "regime": "Calm", "decision": {
        "entries": [{"inst": "MES", "direction": "LONG", "cluster": "legacy_c1",
                     "entry_price": 5000.0, "risk_sized": 250.0}],
        "exits": [], "rejected_detail": [], "realized_today": 0.0,
        "taken_today": {"c1": 1}, "rejected_today": {}}}
    payload = _runner_state()
    payload["payload"]["snapshots"] = [snap]
    payload["payload_era"] = "legacy"
    stub_api(browser_page, {"/api/v1/runner-state": payload})
    open_realtime(browser_page, realtime_server)

    assert "MES" in _text(browser_page, "#decisionEntries")
    assert "Calm" in _text(browser_page, "#decisionSummary")
    # a legacy decision DOES carry rejected evidence, so zero means zero there
    assert _text(browser_page, "#decisionRejectedCount").strip() == "0"
    assert "runner" in _text(browser_page, "#decisionSource")


def test_8_a_snapshot_with_neither_shape_still_refuses_rather_than_inventing(
        browser_page, realtime_server):
    """Three states. A snapshot with no `decision` and no `opens` is unknown, not empty, and the
    panel's original refusal branch is the right answer for it."""
    payload = _runner_state()
    payload["payload"]["snapshots"] = [{"date": "2026-09-24", "status": "refused",
                                        "refusal_reason": "no audit for this day"}]
    stub_api(browser_page, {"/api/v1/runner-state": payload})
    open_realtime(browser_page, realtime_server)

    assert "unavailable" in _text(browser_page, "#decisionSource").lower()
    assert _text(browser_page, "#decisionEntryCount").strip() == "--"
