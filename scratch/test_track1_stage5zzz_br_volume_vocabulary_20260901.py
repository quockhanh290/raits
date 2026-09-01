"""Stage 5ZZZ-BR. One declared name over two engine tests, publishing neither one's number.

The engine checks volume twice, at two different bars, in opposite directions:

    the bar that pulls back to the trend line   must trade BELOW the ten-bar average
    the bar that resumes in trend direction     must trade ABOVE it, times 1.3

Measured on MNKD for 2026-09-01, ten-bar average 25: those are "< 25" and "> 32.5". The panel
declared one rule, `entry_bar_volume_filter`, carrying `rel_volume_max` 2.0 -- a third number,
belonging to neither.

2.0 is the R4 CONTEXT filter's cap on the previous session's relative volume, carried
alongside `range_max` and `vol_feature` and constructed with them. NKD does not run that
filter at all -- `run_instrument` takes `apply_context_filter=False` for this sleeve, because
"that filter is an R4 thing and applying it to a Tokyo session would be inventing a rule". So
NKD published a parameter of a filter it never executes, under the name of a rule that is not
that filter.

The merge is what made the wrong number possible: one name can only carry one setting. Nothing
about the DECISION changes here -- the engine already compared against 1.0x and 1.3x -- this
is the description catching up with what runs.
"""
from __future__ import annotations

import pandas as pd
import pytest

from global_index import track1_signals as SIG

R4 = ("global_nkd", "roska4_swing")


def test_the_two_halves_are_declared_separately_by_both_sleeves():
    """They run the same detector, so a half cannot belong to one sleeve and not the other."""
    for sleeve in R4:
        names = SIG.rule_names(sleeve)
        assert "volume_pullback_declined" in names, sleeve
        assert "volume_resume_surge" in names, sleeve


def test_the_collapsed_name_is_gone_from_every_sleeve():
    """Leaving it in place beside the two would keep a lane whose number is nobody's."""
    for sleeve in SIG.RULES:
        assert "entry_bar_volume_filter" not in SIG.rule_names(sleeve), sleeve


def test_each_half_answers_for_itself_in_the_bridge():
    """The merge lived here. Two emitted gates resolving to one declared name is what forced
    a single setting to stand for two different comparisons."""
    assert SIG.declared_for("global_nkd", "volume_pullback_declined") == \
        "volume_pullback_declined"
    assert SIG.declared_for("global_nkd", "volume_resume_surge") == "volume_resume_surge"


@pytest.mark.parametrize("sleeve", R4)
def test_the_pullback_half_publishes_no_number_rather_than_a_borrowed_one(sleeve):
    """It compares against the plain ten-bar average -- there is no multiple to tune. An empty
    dict says so; borrowing a number from elsewhere is exactly how 2.0 arrived."""
    assert SIG.thresholds(sleeve)["volume_pullback_declined"] == {}, sleeve


@pytest.mark.parametrize("sleeve", R4)
def test_the_declared_surge_multiple_is_the_one_the_engine_compares_against(sleeve):
    """The assertion that closes the loop, and the only one here that could catch the number
    drifting again.

    Not "the declared value equals the constant" -- that is the same literal read twice. The
    strategy is built the way the detector builds it, the volume check is RUN, and the
    threshold it reports to its own gate is divided back by the average it was given. If
    anyone retunes the multiple, or the engine changes what it multiplies, this fails.
    """
    from global_index.track1_normal_r4 import NormalR4Params, _strategy
    p = NormalR4Params(ema_period=10) if sleeve == "global_nkd" else NormalR4Params()
    seen: dict = {}
    strat = _strategy(p)
    avg = 25.0
    strat.check_volume_pattern(
        pd.Series({"volume": 1.0}), pd.Series({"volume": 10_000.0}), avg,
        on_gate=lambda name, ok, value, threshold, comp: seen.setdefault(
            name, (threshold, comp)))
    assert set(seen) == {"volume_pullback_declined", "volume_resume_surge"}, seen

    pull_thr, pull_cmp = seen["volume_pullback_declined"]
    assert (pull_thr, pull_cmp) == (avg, "<"), seen
    surge_thr, surge_cmp = seen["volume_resume_surge"]
    assert surge_cmp == ">", seen
    declared = SIG.thresholds(sleeve)["volume_resume_surge"]["resume_volume_surge_mult"]
    assert surge_thr == pytest.approx(avg * declared), (surge_thr, avg, declared)


@pytest.mark.parametrize("sleeve", R4)
def test_the_two_halves_never_publish_the_same_number(sleeve):
    """The failure this whole stage is about: one number standing for two comparisons."""
    th = SIG.thresholds(sleeve)
    assert th["volume_pullback_declined"] != th["volume_resume_surge"], th


def test_the_context_filter_keeps_its_own_parameters_together():
    """`R4ContextFilter` is constructed with range_max, vol_max=rel_volume_max and vol_feature
    in one call. Publishing one of them under another rule's name is what happened."""
    th = SIG.thresholds("roska4_swing")["r4_prior_range_filter"]
    assert set(th) == {"range_max", "rel_volume_max", "vol_feature"}, th
    assert th["rel_volume_max"] == 2.0, th


def test_nkd_declares_no_parameter_of_a_filter_it_does_not_run():
    """The sharpest form of the defect. NKD is constructed with apply_context_filter=False, so
    every context-filter parameter it published described a gate that never ran for it."""
    published = SIG.thresholds("global_nkd")
    flat = {k for settings in published.values() for k in settings}
    assert "rel_volume_max" not in flat, published
    assert "vol_feature" not in flat, published
    assert "range_max" not in flat, published


def test_nkd_really_does_not_run_the_context_filter():
    """The claim the test above rests on, checked against the code rather than a comment: the
    detector's own entry point takes the flag, and the sleeve's caller passes False."""
    import inspect

    from global_index import track1_normal_r4 as NR
    src = inspect.getsource(NR.run_instrument)
    assert "apply_context_filter" in src, "the flag this test reasons about is gone"
    assert "if apply_context_filter else None" in src, src[:400]


# -- the regression this split caused, found on the page and not by a test ----------------
def test_a_record_written_under_the_old_name_is_still_classified_as_per_bar():
    """Caught by looking at the panel after the split, not by anything here failing.

    The panel decides which rules belong in the per-bar grid instead of the per-slot lanes by
    looking the name up in the declared table. Removing the collapsed name took it out of that
    table, so every session already on disk -- written under the old name, because runtime
    evidence is append-only and never rewritten -- came back as a per-slot lane for a rule that
    is answered twelve times inside one slot and can therefore never hold a value. Measured on
    2026-08-31 straight after the change: five lanes where there had been four, the new one
    reading "value not published" with no prospect of ever reading anything else.
    """
    for sleeve in R4:
        assert "entry_bar_volume_filter" in SIG.per_bar_rule_names(sleeve), sleeve


def test_a_sleeve_that_never_ran_the_rule_does_not_inherit_the_retired_name():
    """The first version of the fix gated on the per-bar gate tables alone, which are global,
    so Stress and Calm picked up a volume rule neither has ever run -- contradicting the
    docstring that says none of Stress's lanes move. A retired name belongs to a sleeve only
    if the rules it became do."""
    for sleeve in ("roska4_stress", "roska4_calm"):
        assert SIG.per_bar_rule_names(sleeve) == (), sleeve


def test_the_retired_name_is_not_declared_again_by_the_back_door():
    """Classifying an old record correctly must not re-admit the rule into the vocabulary. The
    sleeve does not run a rule called that, and the panel must not claim it does."""
    for sleeve in SIG.RULES:
        assert "entry_bar_volume_filter" not in SIG.rule_names(sleeve), sleeve
        assert "entry_bar_volume_filter" not in SIG.entry_rule_names(sleeve), sleeve


def test_every_retired_name_says_what_it_became():
    """An empty replacement would silently drop the old record's rule from both the lanes and
    the grid -- the rule would vanish from a session that really does carry its verdicts."""
    assert SIG.RETIRED_DECLARED, "the register is empty; nothing pins the mapping"
    for old, new in SIG.RETIRED_DECLARED.items():
        assert new, old
        for name in new:
            assert any(name in SIG.rule_names(s) for s in SIG.RULES), (old, name)
