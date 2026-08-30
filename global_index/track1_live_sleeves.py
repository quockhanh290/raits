"""global_index/track1_live_sleeves.py — one readiness verdict per sleeve, in code.

Stage 3B, breaking up LIVE_SLEEVE_SOURCE. Offline and declarative: this file records what
each sleeve's generator IS, what still stands between it and a live decision, and how that is
checked. It generates nothing itself.

Why one blocker became four
---------------------------
"No sleeve has a live signal generator" was true and useless — it named a wall rather than
four different doors. Splitting it was what made the difference visible, and Stage 4 then
walked the last two through:

    roska4_stress   computed from bars start to finish; was ready in Stage 3B
    global_nkd      the sleeve IS futures.swing_tf.SwingTFEngine, production code today
    roska4_swing    PROMOTED in Stage 4 — same rows, no monkeypatching
    roska4_calm     PROMOTED in Stage 4 — the detector is a function, and it reproduces the
                    frozen list row for row

All four are now computed from bars. The `frozen_input` and `anchored_regeneration` kinds are
kept in the vocabulary rather than deleted: they are the states a future sleeve will arrive
in, and a type system that only describes the happy end state cannot describe the way there.

The distinction that decides each verdict
------------------------------------------
Not "is there code" but **can a live decision be taken without inventing something**:

    computed_from_bars      a function, given today's bars, returns today's answer
    anchored_regeneration   a function reproduces the measured rows exactly, but its side
                            effects make it unsafe to call in a trading process as it stands
    frozen_input            some input is a file of answers, so today has no answer at all
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COMPUTED_FROM_BARS = "computed_from_bars"
ANCHORED_REGENERATION = "anchored_regeneration"
FROZEN_INPUT = "frozen_input"
SOURCE_KINDS = (COMPUTED_FROM_BARS, ANCHORED_REGENERATION, FROZEN_INPUT)


@dataclass(frozen=True)
class SleeveSource:
    sleeve: str
    kind: str
    call_chain: tuple
    frozen_inputs: tuple = ()
    side_effects: tuple = ()
    live_ready: bool = False
    gap: str = ""
    anchor: str = ""
    blocker_id: str = ""

    def as_dict(self) -> dict:
        return {"sleeve": self.sleeve, "kind": self.kind,
                "call_chain": list(self.call_chain),
                "frozen_inputs": list(self.frozen_inputs),
                "side_effects": list(self.side_effects),
                "live_ready": self.live_ready, "gap": self.gap,
                "anchor": self.anchor, "blocker_id": self.blocker_id}


SOURCES: dict = {

    "roska4_stress": SleeveSource(
        sleeve="roska4_stress",
        kind=COMPUTED_FROM_BARS,
        call_chain=(
            "scratch/stress_open_search_20260821.load_window(which) -> dfs, costs",
            "scratch/stress_open_search_20260821.build_day_cache(dfs) -> frames, ctx",
            "scratch/stress_switch_full_replay_20260822.make_rule("
            "Scenario('mnq_only_g3_q7', ('MNQ',), 7))",
            "scratch/stress_switch_full_replay_20260822.build_rule_with_levels("
            "frames, ctx, costs, rule)",
        ),
        frozen_inputs=(),
        side_effects=("sets scratch.stress_open_search_20260821.SETUPS to ('10:30',) for the "
                      "duration of the call and restores it in a finally block — scoped and "
                      "reversed, unlike the Normal generator's",),
        live_ready=True,
        gap="needs today's bars and an intraday gate; global_index/track1_intraday.py is that "
            "gate, and the bar source is the same one legacy already fetches",
        anchor="qty 7 and the risk travel on the rows themselves; asserted by the Stage 3 "
               "suite against the measured window",
        blocker_id="SLEEVE_stress_mnq"),

    "global_nkd": SleeveSource(
        sleeve="global_nkd",
        kind=COMPUTED_FROM_BARS,
        call_chain=(
            "global_index/track1_normal_r4.run_instrument(df, labels, cost, "
            "NormalR4Params(ema_period=10), apply_context_filter=False)",
            "  -> the SAME machinery as Normal-R4 at the sleeve's own ema, on the Tokyo "
            "session clock, with the R4 context filter OFF — that filter is an R4 thing and "
            "applying it to a Tokyo session would be inventing a rule",
            "  -> global_index.regime.RegimeLabels(spy_regime, lag_days=1)",
            "the SPY short gate DOES apply here, because the generator that wrote the "
            "artifacts applied it on the strategy class and therefore to every instrument",
        ),
        frozen_inputs=(),
        side_effects=(),
        live_ready=True,
        gap="none for the sleeve itself; it resumes once the bootstrap is regenerated under "
            "track1_params, which the checkpoint blocker covers",
        anchor="MNKD rows reproduce EXACTLY on all three windows — 228 on floor, 31 on "
               "vault2025, 26 on vault2026 — from bars, through the promoted generator",
        blocker_id="SLEEVE_nkd_mnkd"),

    "roska4_swing": SleeveSource(
        sleeve="roska4_swing",
        kind=COMPUTED_FROM_BARS,
        call_chain=(
            "global_index/track1_normal_r4.run_instrument(df, labels, cost, params, "
            "short_days=...) -> (trades, filter_stats)",
            "  -> _cache_for()      futures._validated_core._swing_cache, with the fill law "
            "applied to a COPY so the production cache is left as found",
            "  -> make_signal_fn()  strategy -> SPY short gate -> R4 context filter -> stop "
            "re-anchored to entry -+ 2.0 x daily ATR",
            "  -> scan_signals()    first admitted signal per session, 14:00-15:55",
            "  -> _replay()         ratchet off, armed 14:05 next session, gap fill, and the "
            "same-day rescan after an exit",
            "  -> global_index/track1_normal_filters  R4ContextFilter + allowed_short_days, "
            "PROMOTED from scratch and asserted bar-for-bar against the original",
        ),
        frozen_inputs=("FLOOR_RANGE_P90 = 0.02652437134968455, frozen on the floor window — "
                       "a threshold, not a table of answers, and it travels in the route "
                       "identity",),
        side_effects=(),
        live_ready=True,
        gap="needs today's bars and an intraday gate; global_index/track1_intraday.py is that "
            "gate, and the bar source is the one legacy already fetches",
        anchor="reproduces the committed rows EXACTLY on all three windows — 980 on floor, "
               "136 on vault2025, 107 on vault2026 — with no production symbol replaced, "
               "asserted by object identity",
        blocker_id="SLEEVE_normal_r4"),

    "roska4_calm": SleeveSource(
        sleeve="roska4_calm",
        kind=COMPUTED_FROM_BARS,
        call_chain=(
            "global_index/track1_calm_a.detect(df, regime, inst, params) -> [CalmSetup]",
            "  -> rth_sessions()   [09:30, 15:59] per session, and only sessions that RAN TO "
            "that close",
            "  -> D-1 Calm gate, prior close in the bottom third, prior RTH down, gap "
            ">= -1.0%",
            "  -> entry at the 10:00 OPEN, exit at the 15:55 OPEN, LONG, MES/MNQ",
            "scratch/calm_a_disaster_stop_probe_20260822.build_calm_trades still supplies the "
            "ATR15 stop, exit simulation, risk and P&L — that half was always callable",
        ),
        frozen_inputs=(),
        side_effects=(),
        live_ready=True,
        gap="needs today's and yesterday's bars plus the D-1 regime label; the intraday gate "
            "covers the first and track1_freshness the second",
        anchor="reproduces the frozen list EXACTLY on all three windows — 421 of 421 rows — "
               "and matches its four recorded feature columns to 1e-9",
        blocker_id="SLEEVE_calm_a"),
}


def readiness() -> dict:
    ready = sorted(s.sleeve for s in SOURCES.values() if s.live_ready)
    blocked = sorted(s.sleeve for s in SOURCES.values() if not s.live_ready)
    return {"live_ready": ready, "blocked": blocked,
            "sleeves": {k: v.as_dict() for k, v in SOURCES.items()}}


def self_check() -> list:
    """Structural rules, so the table cannot quietly become decorative."""
    from global_index import track1_gates as g
    from global_index.track1_params import SLEEVE_INSTRUMENTS
    errs = []
    if set(SOURCES) != set(SLEEVE_INSTRUMENTS):
        errs.append(f"sleeve set drifted: sources={sorted(SOURCES)} "
                    f"params={sorted(SLEEVE_INSTRUMENTS)}")
    for name, s in SOURCES.items():
        if s.sleeve != name:
            errs.append(f"{name}: key and sleeve disagree ({s.sleeve})")
        if s.kind not in SOURCE_KINDS:
            errs.append(f"{name}: kind {s.kind!r} unknown")
        if not s.call_chain:
            errs.append(f"{name}: a source with no call chain is prose")
        if s.blocker_id not in g.BLOCKERS:
            errs.append(f"{name}: blocker_id {s.blocker_id!r} is not in the registry")
            continue
        b = g.BLOCKERS[s.blocker_id]
        # The two tables must agree about whether this sleeve can decide live. A sleeve
        # marked ready whose blocker still holds the gate shut — or the reverse — is exactly
        # the drift the registry exists to prevent.
        if s.live_ready and b.status != g.CLOSED:
            errs.append(f"{name}: live_ready but {b.id} is {b.status}")
        if not s.live_ready and b.status != g.USER_DECISION_GATE:
            errs.append(f"{name}: not live_ready but {b.id} is {b.status}")
        if s.kind == FROZEN_INPUT and s.live_ready:
            errs.append(f"{name}: a frozen input cannot be live-ready")
        if s.kind == FROZEN_INPUT and not s.frozen_inputs:
            errs.append(f"{name}: kind is frozen_input but nothing is named as frozen")
    return errs
