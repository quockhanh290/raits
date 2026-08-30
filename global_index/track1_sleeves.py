"""global_index/track1_sleeves.py — where Track 1 candidates come from. NEW FILE.

Stage 3. Declares the boundary between "which trades exist" and "which trades are admitted".
The admission side is `track1_signal_layer`. This file is the other side, and today it has
exactly one working implementation.

Why this boundary is drawn here, and drawn honestly
---------------------------------------------------
The four Track 1 sleeves are not four calls to an engine that lives in `futures/`. Read end
to end, the Normal-R4 sleeve that produced every committed Track 1 number runs through:

    scratch/harness.py                        Cfg(ema=50, stop_basis=2.0, ratchet=False,
                                                  arm_hours=ARM_LIVE) + patched_engine()
    model_sameday_stop.run_loop               a root-level script, not package code
    raits.strategies.trend_follow             with generate_signal wrapped twice
    scratch/harness.force_all_bars_gappable   every bar made gap-eligible
    scratch/normal_promotion_filter_lib_20260821.R4ContextFilter
    scratch/directional_market_filter_probe.allowed_short_days

`futures/_validated_core.backtest_swing_tf` is monkeypatched out of the way for the whole
run. So the Track 1 Normal sleeve is a DIFFERENT ENGINE from the one production ships, not a
different parameterisation of it. Calm A and Stress are the same story with different files.

Promoting that into production is a job with its own equivalence proof, and re-deriving it
from memory here would be the exact move this project has been bitten by: a second copy of a
decision rule, which can only ever prove that the copy behaves like itself. So it is not
done here, it is NAMED here, and the route runs shadow-only until it is done.

What a source must provide
--------------------------
    candidates(window_or_day) -> list[Candidate]
    early_exit_valuer(window_or_day) -> callable(held, ts) -> float | None

`early_exit_valuer` exists because a Stress entry that displaces a Normal or Calm position
has to book that position at a price, and the two callers get that price from different
places — offline from the measured price series, live from the fill the broker reports on
the close leg. Neither may be hard-coded into the rule set.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

#: Everything that would have to be promoted before a live source can exist. Kept as data
#: rather than prose so a test can assert the list is non-empty while the route is
#: shadow-only, and so the list cannot quietly shrink.
LIVE_SOURCE_PREREQUISITES: dict[str, tuple[str, ...]] = {
    # Stage 4 PROMOTED the first three of these into the package and Stage 4C wired the bars
    # in. What is left is deliberately narrower than what used to be here, and the old text is
    # gone rather than struck through: a prerequisite list that still names solved problems is
    # a list nobody trusts, and it hid how much of this was actually finished.
    "roska4_swing": (
        "today's regime label and cost model — the sleeve itself is "
        "global_index/track1_normal_r4, which reproduces the committed rows exactly and now "
        "reads the joined live frame, but a live decision still needs the D-1 label for "
        "today and a cost object, and neither may be invented here",
    ),
    "global_nkd": (
        "same as roska4_swing: the sleeve is production code at ema 10 on lag-1 labels and "
        "reads the joined live frame; today's label is the missing input",
    ),
    "roska4_calm": (
        "true stop-risk sizing — the cap denominator is the disaster-stop distance, not "
        "signal_layer.to_candidate's mult x ATR x pv proxy. The detector itself is "
        "global_index/track1_calm_a, which reproduces the frozen list row for row and now "
        "reads the joined live frame",
    ),
    "roska4_stress": (
        "scratch/stress_open_search_20260821 — the rule the mnq_only_g3_q7 scenario is "
        "built from (gap >= 3, R:R 1.5, break of the pre-window low)",
        "scratch/stress_switch_full_replay_20260822.Scenario('mnq_only_g3_q7', ('MNQ',), 7)",
        "NOT futures/stress_liquidation_1020.py — that is a different 10:20 candidate that "
        "says of itself that it is deliberately not wired",
    ),
}


@runtime_checkable
class SleeveSource(Protocol):
    """The shape `run_live_day_track1` will accept from any source."""

    def candidates(self, key: Any) -> list: ...

    def early_exit_valuer(self, key: Any) -> Any: ...


class LiveSleeveSource:
    """The source that reads today's bars and produces today's candidates.

    Stage 4C changed half of this. The BARS are now real: `frames()` returns, per sleeve, the
    frame that sleeve would read today — yesterday's history with today's session joined onto
    it through `track1_live_frame`, and through nothing else. `detect()` hands those frames to
    the promoted detectors and returns what they say.

    `candidates()` still refuses, and the refusal is now much shorter than it was. What is
    missing is no longer the sleeves: it is today's regime label, a cost object, and Calm A's
    true stop-risk sizing. Those are inputs a live decision needs and that this class must not
    invent — a source that quietly picked a regime for today would be the worst possible place
    to make that choice.
    """

    def __init__(self, provider=None, *, data_paths=None, frozen_frames=None):
        self.provider = provider
        self.data_paths = data_paths
        self.frozen_frames = frozen_frames

    def frames(self, *, through, sleeves=None) -> dict:
        """`{sleeve: {inst: JoinedFrame}}`, joined through the guard.

        Delegated whole to `track1_live_source`, which is the ONLY module on this route that
        obtains live bars. Fetching here as well would put a second join in the route, and a
        second join is a second chance to overwrite history.
        """
        from global_index import track1_live_source as src

        if self.provider is None:
            raise NotImplementedError(
                "LiveSleeveSource has no bar provider. Hand it one — "
                "track1_live_source.FrameBarProvider for a deterministic frame, or "
                "IBKRBarProvider wrapping the runner's broker for a real session.")
        return src.sleeve_frames(provider=self.provider, through=through,
                                 data_paths=self.data_paths,
                                 frozen_frames=self.frozen_frames,
                                 sleeves=sleeves)

    def detect(self, *, through, labels_by_inst, costs=None, params=None,
               sleeves=None) -> dict:
        """Run each sleeve's detector on ITS joined frame. `{sleeve: {inst: result}}`.

        Labels and costs are arguments with no defaults for the same reason the fill law is:
        this class picking a regime model for today would be a decision made in the last place
        anyone would look for it.

        The Stress sleeve is absent by design rather than by omission — its rule still lives in
        scratch, so what is returned for it is the intraday gate's verdict on the joined frame,
        which is real, and no entry.
        """
        from global_index import track1_calm_a as CA
        from global_index import track1_normal_r4 as NR

        by_sleeve = self.frames(through=through, sleeves=sleeves)
        params = params or {}
        out: dict = {}
        for sleeve, per_inst in by_sleeve.items():
            res: dict = {}
            for inst, jf in per_inst.items():
                if sleeve in ("roska4_swing", "global_nkd"):
                    if costs is None or inst not in costs:
                        raise NotImplementedError(
                            f"{sleeve}/{inst} needs a cost object; none was handed in")
                    # `fill_law` is named here rather than defaulted — Stage 5M-1, and this
                    # is the callsite that made the point. It carries no `fill_law` token, so
                    # the search that found the four identity callsites reading
                    # `NormalR4Params().fill_law` walked straight past it — and unlike those
                    # four, this one reaches the ENGINE: the law it takes decides which bars
                    # are gap-eligible and therefore which trades exist, not merely what a
                    # hash says. It was taking the artifact law by default.
                    #
                    # Same reasoning as the labels and costs above: this class picking the
                    # route's fill law would be a decision made in the last place anyone would
                    # look for it. A caller handing in its own `params` still wins, which is
                    # how the artifact reproduction asks for the other law.
                    from global_index import track1_params as _tp
                    pr = params.get(inst) or NR.NormalR4Params(
                        ema_period=10 if sleeve == "global_nkd" else 50,
                        fill_law=_tp.LIVE_FILL_LAW)
                    trades, stats = NR.run_instrument(
                        jf.frame, labels_by_inst[inst], costs[inst], pr,
                        short_days=NR.short_days_from_csv("spy_daily_live.csv"),
                        apply_context_filter=(sleeve == "roska4_swing"))
                    res[inst] = {"trades": trades, "filter_stats": stats,
                                 "join": jf.report.code}
                elif sleeve == "roska4_calm":
                    res[inst] = {"setups": CA.detect(jf.frame, labels_by_inst[inst], inst),
                                 "join": jf.report.code}
                else:
                    res[inst] = {"setups": None, "join": jf.report.code,
                                 "note": "the Stress rule is not in the package; the joined "
                                         "frame is real and its intraday gate is checked"}
            out[sleeve] = res
        return out

    def _refuse(self) -> None:
        lines = []
        for sleeve, items in LIVE_SOURCE_PREREQUISITES.items():
            lines.append(f"  {sleeve}:")
            lines.extend(f"    - {i}" for i in items)
        raise NotImplementedError(
            "Track 1 has no live sleeve source. Every sleeve's signal generator still lives "
            "outside the package and has to be promoted with its own equivalence proof "
            "before a live candidate can be produced:\n" + "\n".join(lines))

    def candidates(self, key: Any) -> list:
        self._refuse()
        return []

    def early_exit_valuer(self, key: Any):
        self._refuse()


def load_source(name: str):
    """Resolve a source by name. `replay` is imported lazily so that production code never
    imports scratch at module load."""
    if name == "replay":
        import importlib
        mod = importlib.import_module("scratch.track1_replay_source_20260822")

        class _Adapter:
            windows = mod.WINDOWS

            def candidates(self, key):
                return mod.candidates(key)

            def early_exit_valuer(self, key):
                return mod.early_exit_valuer(key)

        return _Adapter()
    if name == "live":
        return LiveSleeveSource()
    if name == "live-shadow":
        # Stage 5E. The candidate source for the two sleeves that have a Track 1 slot. It takes
        # its bar provider by injection and opens no connection, so a caller that hands it
        # nothing gets a named refusal rather than a broker.
        from global_index.track1_live_source import LiveTrack1Source
        return LiveTrack1Source()
    raise ValueError(f"unknown Track 1 sleeve source {name!r}; known: replay, live")
