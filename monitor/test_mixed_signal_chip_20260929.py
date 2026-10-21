from global_index import track1_signals as signals
from monitor.backend.job_journal_reader import _annotate_signal_diagnostics


def test_mixed_slot_chip_names_both_outcomes():
    chip = signals.chip({
        "status": signals.SIGNAL_ACCEPTED_SHADOW,
        "accepted": 1,
        "rejected": 1,
    })

    assert chip["label"] == "1 ACCEPTED \u00b7 1 REJECTED"
    assert "passed shadow admission" in chip["tooltip"]
    assert "rejected in the same slot" in chip["tooltip"]


def test_multi_rejection_chip_shows_the_count():
    chip = signals.chip({
        "status": signals.SIGNAL_REJECTED,
        "accepted": 0,
        "rejected": 2,
    })

    assert chip["label"] == "2 REJECTED"


def test_string_chip_callers_keep_the_existing_label():
    assert signals.chip(signals.SIGNAL_ACCEPTED_SHADOW)["label"] == "ACCEPTED SHADOW"


def test_job_journal_uses_the_count_aware_chip(monkeypatch, tmp_path):
    row = {
        "slot_id": "TRACK1_SWING_1550",
        "slot_time": "15:50",
        "sleeve": "roska4_swing",
        "status": signals.SIGNAL_ACCEPTED_SHADOW,
        "reason": "shadow_only",
        "raw_candidates": 2,
        "accepted": 1,
        "rejected": 1,
        "candidates": [],
        "rule_checks": [],
    }
    monkeypatch.setattr(signals, "read_day", lambda *_args, **_kwargs: ([row], 0))
    jobs = [{"job_id": "TRACK1_SWING_1550", "status": "completed"}]

    _annotate_signal_diagnostics(jobs, "2026-09-29", tmp_path)

    assert jobs[0]["signal"]["chip"]["label"] == "1 ACCEPTED \u00b7 1 REJECTED"
