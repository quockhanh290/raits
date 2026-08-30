"""Stage 5M-0 — the state reconstructor writes only what a log line attests.

Every test builds its own log text and its own state files under `tmp_path`. The real
`global_index/preflight_state.json` and `global_index/maxhold_state.json` are never read as
inputs and never written; one test asserts that explicitly by hashing them around a full
`--apply` run pointed at temporary targets.

The property under test is a refusal, not a transformation. These files are fail-closed
evidence — a `true` next to a day is why a slot is permitted to trade — so the failure that
matters is not "it repaired the wrong day", it is "it wrote a day nothing attests". Most of
what follows is therefore negative: a failed run, a run whose outcome line never arrived, a
run for the wrong job, a stray key nobody can account for.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import track1_stage5m0_state_repair_20260823 as rep  # noqa: E402


# ── fixture log builders ────────────────────────────────────────────────────────────────
# Real lines, copied in shape from scheduler_0821.log, so the parser is not being tested
# against a format invented to suit it.

def pf_run(day: str, *, outcome: str, local: str = "11:45:00") -> str:
    head = (f"{day} {local}  INFO     run_scheduler — [PRE-FLIGHT] Starting: "
            f"update_ibkr_daily -> update_spy_csv ({day})")
    if outcome == "ok":
        return head + (f"\n{day} 11:48:01  INFO     run_scheduler — [PRE-FLIGHT] OK — parquet "
                       f"+ spy CSV fresh. run_live_day cleared for 14:05.")
    if outcome == "failed":
        return head + (f"\n{day} 11:46:02  ERROR    run_scheduler — [PRE-FLIGHT] "
                       f"update_ibkr_daily FAILED — run_live_day WILL BE SKIPPED today.")
    return head          # launched, never resolved


def mh_run(day: str, *, outcome: str, local: str = "07:31:00", label="MAX_HOLD_EXIT") -> str:
    head = (f"{day} {local}  INFO     run_scheduler — [{label}] "
            f"C:\\Python311\\pythonw.exe -m global_index.run_maxhold_exit "
            f"--positions-path live_positions.json --port 4002")
    if outcome == "ok":
        return head + f"\n{day} 07:31:10  INFO     run_scheduler — [{label}] completed OK"
    if outcome == "failed":
        return head + (f"\n{day} 07:31:10  ERROR    run_scheduler — [{label}] exited with "
                       f"code 1")
    return head


@pytest.fixture
def logdir(tmp_path):
    def _write(name: str, *blocks: str) -> str:
        (tmp_path / name).write_text("\n".join(blocks) + "\n", encoding="utf-8")
        return str(tmp_path / "scheduler*.log")
    return _write


# ── pre-flight: what is written, and what is refused ────────────────────────────────────

def test_a_successful_preflight_is_recorded_true(logdir):
    pat = logdir("scheduler_0820.log", pf_run("2026-08-20", outcome="ok"))
    assert rep.reconstruct(rep.scan_preflight(pat), record_failures=True) == \
        {"2026-08-20": True}


def test_a_failed_preflight_is_recorded_false_not_dropped(logdir):
    """False is a real state the writer produces, and it REFUSES the day. Dropping it would
    turn a recorded failure into a missing record — which fails closed too, but for the wrong
    reason and with a message that points at a missed job."""
    pat = logdir("scheduler_0804.log", pf_run("2026-08-04", outcome="failed"))
    assert rep.reconstruct(rep.scan_preflight(pat), record_failures=True) == \
        {"2026-08-04": False}


def test_a_preflight_launch_with_no_outcome_line_is_not_recorded_at_all(logdir):
    """The scheduler was killed mid-run, or the log was truncated. Either way nobody knows
    whether the update finished, and "probably" is not evidence."""
    pat = logdir("scheduler_0820.log", pf_run("2026-08-20", outcome="none"))
    runs = rep.scan_preflight(pat)
    assert [r["verdict"] for r in runs] == ["no_outcome_line"]
    assert rep.reconstruct(runs, record_failures=True) == {}


def test_an_ok_line_belonging_to_the_next_run_is_not_borrowed_by_the_previous(logdir):
    """Two runs back to back, the first unresolved. Scanning forward without stopping at the
    next 'Starting' line would hand the second run's success to the first."""
    pat = logdir("scheduler_0820.log",
                 pf_run("2026-08-19", outcome="none"),
                 pf_run("2026-08-20", outcome="ok"))
    got = rep.reconstruct(rep.scan_preflight(pat), record_failures=True)
    assert got == {"2026-08-20": True}, got


def test_the_day_comes_from_the_jobs_own_message_not_the_log_stamp(logdir):
    """The pre-flight prints the ET date it is recording. A late local stamp must not shift
    it — the key the scheduler writes is the one in the parentheses."""
    pat = logdir("scheduler_0820.log", pf_run("2026-08-20", outcome="ok", local="23:45:00"))
    assert list(rep.reconstruct(rep.scan_preflight(pat), record_failures=True)) == \
        ["2026-08-20"]


# ── max-hold: the refusal the incident of 2026-08-13 makes concrete ─────────────────────

def test_maxhold_records_only_completed_runs(logdir):
    pat = logdir("scheduler_0820.log", mh_run("2026-08-20", outcome="ok"))
    assert rep.reconstruct(rep.scan_maxhold(pat), record_failures=False) == \
        {"2026-08-20": True}


def test_maxhold_refuses_to_infer_a_day_whose_runs_never_completed(logdir):
    """2026-08-13, for real: the job launched twice that day — two scheduler processes racing
    the same slot — and neither launch produced a completion line.

    A reconstructor that assumed "it launched, so it ran" would write True and tell the next
    scheduler the max-hold sweep is done for a day it cannot show finishing. MAX_HOLD exits
    average +$398.60 and are where the edge leaves; a false 'already done' is the expensive
    direction.
    """
    pat = logdir("scheduler_0813.log",
                 mh_run("2026-08-13", outcome="none", local="07:31:00"),
                 mh_run("2026-08-13", outcome="failed", local="07:31:01"))
    runs = rep.scan_maxhold(pat)
    assert len(runs) == 2, runs
    assert {r["verdict"] for r in runs} == {"no_outcome_line", "failed"}
    assert rep.reconstruct(runs, record_failures=False) == {}


def test_maxhold_never_writes_false_because_the_scheduler_never_does(logdir):
    """`job_maxhold` only ever sets True. A False key here would be a value no production code
    path can produce, and the next reader would have to guess what it meant."""
    pat = logdir("scheduler_0813.log", mh_run("2026-08-13", outcome="failed"))
    got = rep.reconstruct(rep.scan_maxhold(pat), record_failures=False)
    assert got == {}
    assert False not in got.values()


def test_a_catchup_run_counts_and_carries_its_own_et_day(logdir):
    """The 2026-08-19 recovery ran at 21:51 local — 23:51 ET, still the same session day."""
    pat = logdir("scheduler_0819.log",
                 mh_run("2026-08-19", outcome="ok", local="21:51:48",
                        label="MAX_HOLD_EXIT_CATCHUP"))
    assert rep.reconstruct(rep.scan_maxhold(pat), record_failures=False) == \
        {"2026-08-19": True}


def test_a_local_stamp_after_2200_rolls_into_the_next_et_day(logdir):
    """Calgary is two hours behind ET, so 22:30 local is already tomorrow in New York.

    Slicing the date off the front of the line would key this to the wrong session. The test
    exists because that slice is the obvious shortcut and it is wrong exactly twice a day.
    """
    pat = logdir("scheduler_0820.log",
                 mh_run("2026-08-20", outcome="ok", local="22:30:00",
                        label="MAX_HOLD_EXIT_CATCHUP"))
    assert list(rep.reconstruct(rep.scan_maxhold(pat), record_failures=False)) == \
        ["2026-08-21"]


def test_the_two_scanners_do_not_read_each_others_lines(logdir):
    """A max-hold log must produce no pre-flight days, and the reverse."""
    pat = logdir("scheduler_0820.log",
                 pf_run("2026-08-20", outcome="ok"),
                 mh_run("2026-08-20", outcome="ok"))
    assert len(rep.scan_preflight(pat)) == 1
    assert len(rep.scan_maxhold(pat)) == 1


# ── the stray Sunday key, and pruning ───────────────────────────────────────────────────

def test_an_unattested_key_is_dropped_even_though_it_says_true(logdir):
    """The whole incident in one assertion: a key claiming a successful Sunday pre-flight,
    with no log line anywhere, must not survive into the repaired file."""
    pat = logdir("scheduler_0821.log", pf_run("2026-08-21", outcome="ok"))
    proposed = rep.reconstruct(rep.scan_preflight(pat), record_failures=True)
    d = rep.diff({"2026-08-23": True}, proposed)
    assert d["dropped_unattested"] == ["2026-08-23"]
    assert "2026-08-23" not in proposed


def test_the_reconstruction_prunes_to_the_same_seven_the_writer_keeps(logdir):
    """`_save_preflight_state` keeps the newest 7 by sorted key. A repaired file holding more
    is not the file the scheduler would have written."""
    days = [f"2026-07-{d:02d}" for d in range(13, 25)]
    pat = logdir("scheduler_0700.log", *[pf_run(d, outcome="ok") for d in days])
    got = rep.reconstruct(rep.scan_preflight(pat), record_failures=True)
    assert len(got) == rep.KEEP == 7
    assert list(got) == sorted(days)[-7:]


def test_an_empty_log_set_reconstructs_nothing_rather_than_guessing(tmp_path):
    pat = str(tmp_path / "scheduler*.log")
    assert rep.scan_preflight(pat) == [] and rep.scan_maxhold(pat) == []
    assert rep.reconstruct([], record_failures=True) == {}


# ── the script itself: dry-run default, and the real files stay shut ────────────────────

def _hash(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def test_the_default_invocation_writes_nothing(logdir, tmp_path, capsys):
    pat = logdir("scheduler_0821.log", pf_run("2026-08-21", outcome="ok"),
                 mh_run("2026-08-21", outcome="ok"))
    pf, mh = tmp_path / "pf.json", tmp_path / "mh.json"
    pf.write_text(json.dumps({"2026-08-23": True}), encoding="utf-8")
    mh.write_text(json.dumps({"2026-08-23": True}), encoding="utf-8")
    before = (_hash(pf), _hash(mh))
    assert rep.main(["--logs", pat, "--preflight-path", str(pf),
                     "--maxhold-path", str(mh)]) == 0
    assert (_hash(pf), _hash(mh)) == before
    assert "DRY RUN" in capsys.readouterr().out


def test_apply_writes_only_the_targets_it_was_given_and_never_the_real_files(logdir, tmp_path):
    """`--apply` is the dangerous path, so it is exercised — pointed at temporary files, with
    the operator's real files hashed around it."""
    real = {p: _hash(p) for p in (rep.PREFLIGHT_PATH, rep.MAXHOLD_PATH)}
    assert any(v for v in real.values()), (
        "neither real state file exists, so this test cannot show they were left alone")

    pat = logdir("scheduler_0821.log", pf_run("2026-08-21", outcome="ok"),
                 mh_run("2026-08-21", outcome="ok"))
    pf, mh = tmp_path / "pf.json", tmp_path / "mh.json"
    pf.write_text(json.dumps({"2026-08-23": True}), encoding="utf-8")
    mh.write_text(json.dumps({"2026-08-23": True}), encoding="utf-8")

    assert rep.main(["--apply", "--logs", pat, "--preflight-path", str(pf),
                     "--maxhold-path", str(mh)]) == 0
    assert json.loads(pf.read_text(encoding="utf-8")) == {"2026-08-21": True}
    assert json.loads(mh.read_text(encoding="utf-8")) == {"2026-08-21": True}
    assert {p: _hash(p) for p in (rep.PREFLIGHT_PATH, rep.MAXHOLD_PATH)} == real


def test_apply_refuses_when_the_target_has_changed_since_the_plan(logdir, tmp_path, capsys):
    """The file self-heals at Monday 13:45 if the scheduler is left alone. A repair executed
    after that would overwrite a healthy file with a reconstruction — older, and for no
    reason. `--expect-current` makes the plan check its assumption before writing."""
    pat = logdir("scheduler_0821.log", pf_run("2026-08-21", outcome="ok"),
                 mh_run("2026-08-21", outcome="ok"))
    pf, mh = tmp_path / "pf.json", tmp_path / "mh.json"
    healed = {"2026-08-21": True, "2026-08-24": True}
    pf.write_text(json.dumps(healed), encoding="utf-8")
    mh.write_text(json.dumps(healed), encoding="utf-8")
    before = (_hash(pf), _hash(mh))

    rc = rep.main(["--apply", "--logs", pat, "--preflight-path", str(pf),
                   "--maxhold-path", str(mh),
                   "--expect-current", json.dumps({"2026-08-23": True})])
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().out
    assert (_hash(pf), _hash(mh)) == before


def test_the_expectation_guard_lets_a_matching_plan_through(logdir, tmp_path):
    """The guard must be able to say yes, or it is just a permanent refusal."""
    pat = logdir("scheduler_0821.log", pf_run("2026-08-21", outcome="ok"),
                 mh_run("2026-08-21", outcome="ok"))
    pf, mh = tmp_path / "pf.json", tmp_path / "mh.json"
    for p in (pf, mh):
        p.write_text(json.dumps({"2026-08-23": True}), encoding="utf-8")
    assert rep.main(["--apply", "--logs", pat, "--preflight-path", str(pf),
                     "--maxhold-path", str(mh),
                     "--expect-current", json.dumps({"2026-08-23": True})]) == 0
    assert json.loads(pf.read_text(encoding="utf-8")) == {"2026-08-21": True}


# ── the reconstruction actually proposed for the operator ───────────────────────────────

def test_the_proposal_against_the_real_logs_is_all_true_and_attested():
    """Reads the real logs — which is safe, they are append-only text — and asserts the shape
    of what would be written. No state file is opened."""
    pf = rep.reconstruct(rep.scan_preflight(), record_failures=True)
    mh = rep.reconstruct(rep.scan_maxhold(), record_failures=False)
    assert pf and mh, "the real logs produced no reconstruction at all"
    assert all(v is True for v in pf.values()), pf
    assert all(v is True for v in mh.values()), mh
    assert "2026-08-23" not in pf and "2026-08-23" not in mh
    # The one key Monday's night slots actually need.
    assert pf.get("2026-08-21") is True
    # The day the two-scheduler incident left unresolved must not appear as a done max-hold.
    assert "2026-08-13" not in mh
