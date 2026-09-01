"""Stage 5ZZZ-BT. The runtime-evidence guard refused the tests it was written to allow.

It exists because of a real incident: a scratch suite run without isolated output appended two
rows to the live signals journal on a Saturday, and they had to be quarantined rather than
deleted, because runtime evidence is append-only. Its own docstring promises

    "A test writing under `tmp_path` - which is what a test should do - never sees this"

and that was not true. The check asked whether any path COMPONENT was named `track1_runtime`,
and a test builds its fake root by mirroring the production layout inside tmp_path, so the fake
tree matched as surely as the real one. Six tests in the signal-journal suite had been refused
since it landed on 2026-08-30 -- the append/read round trip, unreadable-line handling,
write-failure disabling, the day summary, refusal surfacing and the job-card annotation: the
channel that feeds the panel's signal cards.

The point of this file is the OTHER direction. Loosening a guard is easy to get wrong, so what
is pinned here is that it still bites: on the real tree, through the real entry point, with no
possibility of a write actually landing if it does not.
"""
from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from global_index import track1_signals as S

DAY = "2026-09-01"


def _row():
    return S.build_row(sleeve="roska4_stress", slot_id="TRACK1_STRESS_1040",
                       slot_time="10:40", session_date=DAY, mode="shadow_live",
                       decided=True, reason="decided", raw_candidates=0,
                       freshness_allow=True, gate_allow=True)


def _real_journal() -> Path:
    return (Path(S.__file__).resolve().parent.parent / S.SIGNALS_DIR).resolve()


# -- it still bites -----------------------------------------------------------------------
def test_writing_the_real_journal_from_a_test_is_still_refused(monkeypatch):
    """Through `append`, at the real root, with `open` replaced by something that fails loudly.

    So a guard that stopped firing could not quietly append to the live journal while this test
    watched -- the incident would happen inside the test that exists to prevent it.
    """
    def no_writing(*a, **k):
        raise AssertionError("the guard did not fire and a write was attempted: %r" % (a,))

    monkeypatch.setattr(builtins, "open", no_writing)
    monkeypatch.setattr(S, "_disabled", False)
    with pytest.raises(S.SignalJournalRefused):
        S.append(_row(), root=".")


def test_the_refusal_names_the_path_and_the_way_out():
    """An operator meeting this has to be able to act on it without reading the source."""
    with pytest.raises(S.SignalJournalRefused) as e:
        S._refuse_production_write_under_pytest(_real_journal() / "x.jsonl")
    msg = str(e.value)
    assert "track1_runtime" in msg, msg
    assert S.ALLOW_TEST_WRITE_ENV in msg, msg
    assert "tmp_path" in msg, msg


def test_a_deliberate_integration_write_can_still_opt_in(monkeypatch):
    """The escape hatch the message advertises has to work, or the message is a lie."""
    monkeypatch.setenv(S.ALLOW_TEST_WRITE_ENV, "1")
    S._refuse_production_write_under_pytest(_real_journal() / "x.jsonl")


# -- and it stops biting what it was told to allow ----------------------------------------
def test_a_fake_root_that_mirrors_the_production_layout_is_allowed(tmp_path):
    """The defect, exactly. A test builds its root by mirroring the real layout, so the fake
    path contains every component the real one does."""
    target = tmp_path / S.SIGNALS_DIR / ("track1_signals_%s.jsonl" % DAY.replace("-", ""))
    S._refuse_production_write_under_pytest(target)


def test_a_row_really_round_trips_through_a_fake_root(tmp_path):
    """The end the six tests could not reach. Asserted on the read-back rather than on the
    absence of an exception, so a guard that silently swallowed the write would fail here."""
    p = S.append(_row(), root=tmp_path)
    assert p is not None and p.exists(), p
    rows, invalid = S.read_day(DAY, root=tmp_path)
    assert len(rows) == 1 and not invalid, (rows, invalid)
    assert rows[0]["slot_id"] == "TRACK1_STRESS_1040", rows[0]


def test_the_check_is_anchored_on_the_repository_not_on_the_working_directory(monkeypatch,
                                                                             tmp_path):
    """Measured choice, not an accident. Anchoring on `Path(".")` would make the answer depend
    on where pytest was started; the tree worth protecting is the one in the repository this
    module was imported from."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(S.SignalJournalRefused):
        S._refuse_production_write_under_pytest(_real_journal() / "x.jsonl")
    S._refuse_production_write_under_pytest(
        tmp_path / S.SIGNALS_DIR / "track1_signals_20260901.jsonl")


def test_outside_a_test_run_nothing_is_refused(monkeypatch):
    """The scheduler is the whole reason this is scoped to pytest. A guard that fired in
    production would stop the route recording its own evidence."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    S._refuse_production_write_under_pytest(_real_journal() / "x.jsonl")
