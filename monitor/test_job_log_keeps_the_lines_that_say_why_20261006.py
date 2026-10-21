# -*- coding: utf-8 -*-
"""A failed job's log keeps the lines that say why, not Python's position markers. 2026-10-06.

The 12-line diagnostic tail filled up with traceback noise: on 2026-10-06's sixteen failed jobs,
46 of 189 shown lines were `^^^^` markers and 28 were frames inside ib_insync / asyncio, and for
TRACK1_STRESS_1130 the frame that said the slot failed in `broker.connect()` was among the lines
the cap cut. The fixture is that slot's real block, copied verbatim from scheduler_1006.log.

Dropped before the cap: caret-only lines, library frames (site-packages, the standard library,
frozen modules) and the source line printed under such a frame. Kept: the project's own frames,
the exception line and everything that is not a traceback.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from monitor.backend import job_journal_reader as jj

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "scheduler_1006_stress_1130_traceback.log"
DAY = "2026-10-06"


def _job(tmp_path: Path) -> dict:
    shutil.copy(FIXTURE, tmp_path / "scheduler_1006.log")
    jobs = jj.read_job_journal(DAY, tmp_path)["jobs"]
    rows = [j for j in jobs if j["job_id"] == "TRACK1_STRESS_1130"]
    assert len(rows) == 1, [j["job_id"] for j in jobs]
    return rows[0]


def test_the_fixture_really_holds_the_noise_this_is_about():
    text = FIXTURE.read_text(encoding="utf-8")
    assert text.count("^^^^") >= 5 and "site-packages" in text and "\\Lib\\asyncio" in text


def test_the_lines_that_say_why_are_kept(tmp_path):
    j = _job(tmp_path)
    shown = "\n".join(j["diagnostics"])
    assert j["status"] == "failed"
    assert "broker.connect()" in shown, shown
    assert "build_bar_provider" in shown, shown
    assert j["diagnostics"][-1] == "TimeoutError", j["diagnostics"]


def test_no_marker_line_or_library_frame_reaches_the_tail(tmp_path):
    j = _job(tmp_path)
    for line in j["diagnostics"]:
        assert not set(line) <= set("^~ "), line
        assert "site-packages" not in line and "\\Lib\\" not in line, line
    assert "loop.run_until_complete(task)" not in "\n".join(j["diagnostics"]), (
        "the source line printed under a library frame must go with its frame")


def test_every_echoed_line_is_either_shown_or_counted(tmp_path):
    """Filtering must not make lines vanish: shown + omitted == every non-empty echoed line."""
    echoed = 0
    for x in FIXTURE.read_text(encoding="utf-8").splitlines():
        if "[TRACK1_STRESS_1130]" in x and (" stdout:" in x or " stderr:" in x) \
                and (" ERROR " in x or " CRITICAL " in x):
            body = x.split(" stdout:", 1)[-1] if " stdout:" in x else x.split(" stderr:", 1)[-1]
            echoed += bool(body.strip())
    j = _job(tmp_path)
    assert echoed > 12, "control: the fixture must overflow the cap or this proves nothing"
    assert len(j["diagnostics"]) + j["diagnostics_omitted"] == echoed, (
        len(j["diagnostics"]), j["diagnostics_omitted"], echoed)


def test_parse_state_never_reaches_the_record(tmp_path):
    j = _job(tmp_path)
    assert not any(k.startswith("_") for k in j), sorted(j)


@pytest.mark.parametrize("line, kept", [
    ('File "D:\\raits\\global_index\\ibkr_broker.py", line 608, in connect', True),
    ('File "C:\\Python311\\Lib\\site-packages\\ib_insync\\ib.py", line 279, in connect', False),
    ('File "C:\\Python311\\Lib\\asyncio\\tasks.py", line 492, in wait_for', False),
    ('File "<frozen runpy>", line 198, in _run_module_as_main', False),
    ("^^^^^^^^^^^^^", False),
    ("~~~~^^^^", False),
    ("TimeoutError", True),
    ("AttributeError: 'NoneType' object has no attribute 'index'", True),
    ("IBKR code=1100 reqId=-1: Connectivity between IBKR and Trader Workstation has been lost.", True),
])
def test_each_kind_of_line(line, kept):
    job = {"diagnostics": [], "diagnostics_omitted": 0}
    jj._append_child_diagnostic(job, line)
    assert (job["diagnostics"] == [line]) is kept, (line, job["diagnostics"])


def test_an_exception_straight_after_a_frozen_frame_is_not_mistaken_for_its_source_line():
    """A frozen frame prints no source line, so what follows it can be the exception itself."""
    job = {"diagnostics": [], "diagnostics_omitted": 0}
    for line in ('File "<frozen runpy>", line 88, in _run_code', "SystemExit: 2"):
        jj._append_child_diagnostic(job, line)
    assert job["diagnostics"] == ["SystemExit: 2"]


def test_parse_state_does_not_leak_when_the_output_stops_on_a_library_frame(tmp_path):
    """The scheduler keeps only the last 25 child lines, so a tail can end on any line —
    including a library frame, which is exactly when the skip flag is still set."""
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    cut = max(i for i, x in enumerate(lines) if "stderr:" in x and r"\Lib\asyncio" in x)
    (tmp_path / "scheduler_1006.log").write_text(
        "\n".join(lines[:cut + 1] + [lines[-1]]) + "\n", encoding="utf-8")
    rows = [j for j in jj.read_job_journal(DAY, tmp_path)["jobs"] if j["job_id"] == "TRACK1_STRESS_1130"]
    assert rows and not any(k.startswith("_") for k in rows[0]), sorted(rows[0])
