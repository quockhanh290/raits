"""Stage 5ZZZ-E — Calm becomes observable without DECIDE learning what OBSERVE knows.

Calm already recorded both phases while it ran: `_write_shadow_intent` appends a DECIDE row at
09:32 and an OBSERVE row at 10:02 on every path including the refusals, because "silence is the
one outcome that is not allowed". So the runtime half of this stage is a READER. A second writer
would put two accounts of one phase on disk, and the day they disagreed nobody could say which
was the slot.

The line between the phases is not a judgement call and is not written out by hand:

    detect_entry_for_day  IS  detect_setup_before_entry  +  entry price  +  entry timestamp

so DECIDE-knowable is exactly `CalmPreEntry`'s fields, and OBSERVE-only is exactly what
`CalmSetup` adds, plus whatever is derived from `entry`. The tests below take that split from the
two dataclasses, so a field added to either lands on the correct side without anyone remembering
to update a list.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd                                              # noqa: E402
from global_index import track1_calm_a as CA                     # noqa: E402
from global_index import track1_shadow_intent as si              # noqa: E402
from global_index import track1_strategy_diagnostics as SD       # noqa: E402
from monitor.backend import track1_market_view as mv             # noqa: E402

ET = "America/New_York"
DAY = "2026-08-28"


def _at(hhmm, day=DAY):
    return pd.Timestamp(f"{day} {hhmm}", tz=ET)


def _phases(day=DAY, now=None):
    return SD.calm_blocks(REPO, day, now=now)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the line between the phases, taken from the code that draws it
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_decide_field_set_is_the_pre_entry_dataclass():
    assert SD.calm_decide_fields() == frozenset(CA.CalmPreEntry.__dataclass_fields__)
    assert SD.calm_decide_fields(), "an empty set would make every leak check vacuous"


def test_the_observe_only_set_is_exactly_what_the_entry_bar_adds():
    added = SD.calm_observe_only_fields()
    assert "entry" in added and "entry_time" in added
    assert "planned_stop" in added and "entry_reference_price" in added
    # and the trap the detector's own docstring names
    assert "open_loc_prev_range" not in added, (
        "open_loc_prev_range reads like a price feature and is computed from the 09:30 open, "
        "so it is knowable at DECIDE")


def test_the_two_sets_do_not_overlap():
    assert not (SD.calm_decide_fields() & SD.calm_observe_only_fields())


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. the leak, tested against every DECIDE block this repo can produce
# ══════════════════════════════════════════════════════════════════════════════════════════

def _decide_text(block) -> str:
    return json.dumps(block, default=str).lower()


@pytest.mark.parametrize("day", ["2026-08-27", "2026-08-28", "2026-08-20"])
def test_a_decide_block_never_carries_an_observe_only_value(day):
    block = _phases(day, now=_at("23:00"))["decide"]
    text = _decide_text(block)
    for field in SD.calm_observe_only_fields():
        assert field not in text, (day, field, block)


def test_a_decide_card_shows_the_stop_as_a_rule_and_never_as_a_level():
    """"entry - 1.5 x daily ATR" is fully known at half past nine. The number it evaluates to
    waits for ten o'clock, and printing one now would be printing the single thing this phase is
    not allowed to know."""
    be = {"instrument": "MES", "direction": "LONG",
          "stop_rule": "entry - 1.5 x daily_atr",
          "entry_reference_time": "10:00",
          "risk_inputs": {"daily_atr_causal": 8.0, "point_value": 5.0,
                          "stop_atr_mult": 1.5, "stop_distance": 12.0,
                          "risk_dollars": 60.0}}
    rows = SD._calm_decide_rows(be, CA.CalmAParams())
    labels = {r["label"]: r for r in rows}
    assert "Stop rule" in labels
    assert labels["Stop rule"]["display_value"] == "entry - 1.5 x daily_atr"
    assert "Planned stop" not in labels, "a level, at DECIDE"
    assert "Entry reference" not in labels
    # a DISTANCE needs no entry price and is allowed
    assert labels["Stop distance"]["value"] == 12.0


def test_a_decide_block_carries_no_price_level():
    for day in ("2026-08-27", "2026-08-28"):
        block = _phases(day, now=_at("23:00"))["decide"]
        assert block["price_levels"] == [], block
        assert block["levels_armed"] is False


def test_a_malformed_decide_row_still_cannot_print_a_level(monkeypatch):
    """The mutation that found this came back GREEN honestly.

    Until it did, the DECIDE card carried no price level only because a DECIDE row on disk
    happens never to have an `after_reference` - the leak was held off by the DATA, not by the
    code. This feeds the one row that breaks that assumption: a DECIDE row carrying a planned
    stop. The phase, not the row's contents, must be what refuses it.
    """
    poisoned = [{"phase": si.DECIDE, "status": "SETUP", "reason_code": "ok",
                 "before_entry": {"instrument": "MES", "direction": "LONG",
                                  "stop_rule": "entry - 1.5 x daily_atr",
                                  "risk_inputs": {"stop_distance": 12.0}},
                 "after_reference": {"planned_stop": 7727.75,
                                     "entry_reference_price": 7739.75}}]
    monkeypatch.setattr(si, "read_day", lambda *a, **k: poisoned)
    block = SD.calm_blocks(REPO, DAY, now=_at("23:00"))["decide"]
    assert block["price_levels"] == [], block
    assert block["levels_armed"] is False
    assert "7727.75" not in _decide_text(block)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. OBSERVE may say more — but only behind a matched DECIDE
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_an_observe_card_carries_the_reference_and_the_evaluated_stop():
    be = {"instrument": "MES", "direction": "LONG",
          "risk_inputs": {"daily_atr_causal": 8.0, "stop_distance": 12.0,
                          "risk_dollars": 60.0}}
    ar = {"entry_reference_price": 7739.75, "planned_stop": 7727.75}
    labels = {r["label"]: r for r in SD._calm_observe_rows(be, ar)}
    assert labels["Entry reference"]["value"] == 7739.75
    assert labels["Planned stop"]["value"] == 7727.75


def test_observe_without_a_decide_row_stays_refused_today():
    """Today's real shape, and the contract working: DECIDE found no candidate, so OBSERVE has
    nothing to match and says exactly that."""
    block = _phases(DAY, now=_at("23:00"))["observe"]
    assert block["diagnostics_source"] == SD.RECORDED
    assert block.get("reason_code") == si.NO_DECIDE_ROW
    assert block["rows"] == []
    assert block["price_levels"] == []


def test_a_reconstructed_observe_refuses_without_a_decide_too():
    """A replay is not a licence to do after the fact what the live path forbids. An observe
    answer standing alone would say a reference price was seen and imply a decision nobody can
    point to — the collapse the two phases exist to prevent."""
    block = _phases("2026-08-20", now=_at("23:00", "2026-08-28"))["observe"]
    assert block["diagnostics_source"] == SD.RECONSTRUCTED
    assert block.get("matched_decide") is False
    assert block.get("reason_code") == "no_decide_row_for_this_day"
    assert block["rows"] == []


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. which source answers, and when
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_before_either_phase_both_are_not_yet_run():
    got = _phases(DAY, now=_at("09:00"))
    assert got["decide"]["diagnostics_source"] == SD.NOT_YET_RUN
    assert got["observe"]["diagnostics_source"] == SD.NOT_YET_RUN


def test_between_the_phases_only_decide_has_answered():
    got = _phases(DAY, now=_at("09:45"))
    assert got["decide"]["diagnostics_source"] == SD.RECORDED
    assert got["observe"]["diagnostics_source"] == SD.NOT_YET_RUN


def test_after_both_phases_both_read_from_the_record():
    got = _phases(DAY, now=_at("23:00"))
    assert got["decide"]["diagnostics_source"] == SD.RECORDED
    assert got["observe"]["diagnostics_source"] == SD.RECORDED


def test_a_phase_not_yet_reached_is_never_reconstructed():
    """Asking what 09:32 looked like at 09:00 must not be answered with the row it wrote half an
    hour later — a real artefact answering a different question is the most convincing way to be
    wrong."""
    got = _phases(DAY, now=_at("09:00"))
    for phase in ("decide", "observe"):
        assert got[phase]["rows"] == []
        assert "reconstructed_at" not in got[phase]


def test_a_day_that_left_no_rows_is_reconstructed_and_says_so():
    got = _phases("2026-08-20", now=_at("23:00", "2026-08-28"))
    for phase in ("decide", "observe"):
        assert got[phase]["diagnostics_source"] == SD.RECONSTRUCTED
        assert got[phase]["warning"] == SD.RECONSTRUCTION_WARNING
        assert got[phase]["reconstructed_at"]


def test_todays_recorded_blocks_carry_the_streams_own_identity():
    got = _phases(DAY, now=_at("23:00"))["decide"]
    assert got.get("params_hash"), got
    assert got.get("data_source_identity"), got


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. nothing here writes, and nothing here decides
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_reading_calm_diagnostics_writes_no_intent_row():
    day = str(pd.Timestamp(DAY).date())
    p = si.path_for(REPO, day)
    before = p.read_bytes() if p.exists() else b""
    _phases(DAY, now=_at("23:00"))
    _phases("2026-08-20", now=_at("23:00", "2026-08-28"))
    after = p.read_bytes() if p.exists() else b""
    assert after == before


def test_the_stage_added_no_second_runtime_writer_for_calm():
    """Calm already writes both phases. A second writer would put two accounts of one phase on
    disk, and the day they disagreed nobody could say which was the slot."""
    src = (REPO / "global_index" / "track1_strategy_diagnostics.py").read_text(encoding="utf-8")
    calm_half = src.split("# Calm — two phases")[1]
    for forbidden in ("si.append", "shadow_intent.append"):
        assert forbidden not in calm_half, forbidden


def test_calm_diagnostics_are_unreachable_from_any_gate():
    for name in ("track1_gates.py", "track1_paper_readiness.py", "track1_shadow_acceptance.py"):
        src = (REPO / "global_index" / name).read_text(encoding="utf-8")
        assert "track1_strategy_diagnostics" not in src, name


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6. the payload, and the page
# ══════════════════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def payload():
    return mv.build(REPO)


def test_the_market_view_publishes_calm_as_two_phases(payload):
    calm = payload.get("calm") or {}
    assert calm.get("sleeve") == "roska4_calm"
    assert set((calm.get("phases") or {})) == {"decide", "observe"}


def test_calm_is_not_forced_into_the_sleeve_shape(payload):
    """Every entry in `SLEEVES` is a continuous window on one instrument with a bar chart. Calm
    is two instants half an hour apart under a contract forbidding the first from seeing what
    the second learns, and one card is where the leak would live."""
    assert "roska4_calm" not in mv.SLEEVES
    assert "roska4_calm" not in (payload.get("sleeves") or {})


def test_every_calm_phase_declares_its_source(payload):
    for phase, block in (payload["calm"]["phases"]).items():
        assert block["diagnostics_source"] in (SD.RECORDED, SD.RECONSTRUCTED, SD.NOT_YET_RUN)
        assert block["phase"] == phase
        assert block["summary"]


def test_orders_remain_impossible():
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in [r.split(":")[0] for r in reasons]


def test_no_order_artefacts_and_the_decision_is_intact():
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    conf = REPO / "track1_go_live_confirmation.json"
    assert conf.exists()
    assert (json.loads(conf.read_text(encoding="utf-8")).get("confirmed_by") or "").strip()


# ══════════════════════════════════════════════════════════════════════════════════════════
# 7. the page renders both phases, and computes nothing
# ══════════════════════════════════════════════════════════════════════════════════════════

JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"


def test_the_page_renders_two_calm_cards_and_decides_nothing():
    code = JS.read_text(encoding="utf-8")
    assert "mvCalmCards" in code and "marketViewCalm" in code
    fn = code.split("function mvCalmCards")[1].split("\n  function ")[0]
    # it prints the rows the backend put in each phase
    assert "b.rows" in fn and "mvSourceBadge" in fn
    # and works out no strategy value of its own
    for forbidden in ("entry -", "* atr", "planned_stop =", "disaster_stop", "1.5"):
        assert forbidden not in fn, forbidden


def test_the_page_never_moves_a_value_between_the_phases():
    """Each card reads its OWN phase block. A renderer that fell back to the other phase for a
    missing value would leak across the line the backend just drew."""
    code = JS.read_text(encoding="utf-8")
    fn = code.split("function mvCalmCards")[1].split("\n  function ")[0]
    assert "phases[key]" in fn
    for cross in ("phases.observe", "phases['observe']", "phases.decide", "phases['decide']"):
        assert cross not in fn, cross


pytest.importorskip("playwright.sync_api")
from monitor.test_realtime_dom import (           # noqa: E402
    browser_page, open_realtime, realtime_server, stub_api)

assert browser_page and realtime_server


#: Built once. `mv.build` is the slowest call in this file and the three viewport cases plus the
#: two content cases would otherwise pay it five times over.
_MV_PAYLOAD: dict = {}


def _open_with_calm(page, server):
    """Open the page against a payload that actually carries Calm.

    The shared DOM stub predates this stage and has no `calm` key, so the panel correctly
    rendered nothing and the first version of these tests waited on an empty div — a test
    failing because its fixture never described the thing it was checking.
    """
    if not _MV_PAYLOAD:
        _MV_PAYLOAD["v"] = {"market_view": mv.build(REPO), "regime": mv.regime(REPO)}
    stub_api(page, {"/api/v1/track1-market-view": _MV_PAYLOAD["v"]})
    open_realtime(page, server)
    page.wait_for_selector("#marketViewCalm .mv2-calm-card", timeout=15000)


@pytest.mark.parametrize("width", [375, 720, 1440])
def test_dom_calm_renders_without_overflow(browser_page, realtime_server, width):
    browser_page.set_viewport_size({"width": width, "height": 1200})
    _open_with_calm(browser_page, realtime_server)
    over = browser_page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, f"page scrolls by {over}px at {width}px"
    inner = browser_page.eval_on_selector(
        "#marketViewCalm", "el => el.scrollWidth - el.clientWidth")
    assert inner <= 1, f"the Calm block overflows by {inner}px at {width}px"


def test_dom_calm_shows_both_phases_with_their_source(browser_page, realtime_server):
    _open_with_calm(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#marketViewCalm", "el => el.innerText").upper()
    if not text.strip():
        pytest.skip("the stubbed payload carried no Calm block")
    assert "DECIDE" in text and "OBSERVE" in text
    assert "09:32" in text and "10:02" in text
    assert any(w in text for w in ("RECORDED", "RECONSTRUCTED", "NOT YET"))


def test_dom_the_decide_card_shows_no_entry_or_planned_stop(browser_page, realtime_server):
    """The leak, checked where a reader would actually meet it."""
    _open_with_calm(browser_page, realtime_server)
    cards = browser_page.eval_on_selector_all(
        "#marketViewCalm .mv2-calm-card", "els => els.map(e => e.innerText)")
    if not cards:
        pytest.skip("the stubbed payload carried no Calm block")
    decide = next((c for c in cards if c.upper().startswith("DECIDE")), "")
    up = decide.upper()
    assert "PLANNED STOP" not in up, decide
    assert "ENTRY REFERENCE" not in up, decide
