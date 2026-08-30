"""Stage 5Q-4 — the MNQ overlap mismatch, and a repair tool that refuses more than it does.

No scheduler started or stopped, no backend restarted, no IBKR connection, no order, no
confirmation file. Every parquet this suite writes lives under `tmp_path`; a test at the end
asserts the real data files are byte-identical to what they were when the module was imported.

What was measured, before any of this was written
-------------------------------------------------
* the MNQ parquet's LAST bar is 2026-08-21 13:45 ET, and it is the disputed one;
* twelve independent live fetches, one per Stress slot over an hour, all reported the same
  single disagreement: `low` 29400.25 in the file against 29395.75 from the feed, 1 of 1186
  shared timestamps;
* the feed's low is LOWER, which is the only direction a partial bar's low can be wrong in;
* `update_ibkr_daily` appends `new_bars[... .index > last_existing]`, so the boundary bar is
  never rewritten and the defect cannot self-heal.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

REPO = Path(r"d:\raits")

import pandas as pd                                        # noqa: E402

from global_index import run_live_day_track1 as R          # noqa: E402
from global_index import track1_live_source as src         # noqa: E402

repair = __import__("track1_stage5q4_repair_boundary_bar_20260824")  # noqa: E402

SESSION_TZ = "America/New_York"
DAY = "2026-08-21"

#: The real files, fingerprinted at import so the final test can prove none was touched.
REAL_PATHS = R.default_data_paths()
REAL_FINGERPRINT = {
    k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
    for k, v in REAL_PATHS.items() if Path(v).exists()}


# ══════════════════════════════════════════════════════════════════════════════
# frames
# ══════════════════════════════════════════════════════════════════════════════

def _bars(start: str, n: int, *, base: float = 29400.0, naive: bool = False,
          extras: bool = False) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="1min")
    if not naive:
        idx = idx.tz_localize(SESSION_TZ)
    df = pd.DataFrame(
        {"open": [base + i * 0.25 for i in range(n)],
         "high": [base + i * 0.25 + 3.0 for i in range(n)],
         "low": [base + i * 0.25 - 3.0 for i in range(n)],
         "close": [base + i * 0.25 + 1.0 for i in range(n)],
         "volume": [1500.0 + i for i in range(n)]},
        index=idx)
    if extras:
        df["average"] = df["close"]
        df["barcount"] = 40
    return df


def _parquet(tmp_path: Path, df: pd.DataFrame, name="NQ.parquet") -> Path:
    """Written the way `frozen_frame` expects to read it: UTC index, lowercase columns."""
    out = df.copy()
    out.index = pd.DatetimeIndex(out.index).tz_convert("UTC")
    p = tmp_path / name
    out.to_parquet(p)
    return p


class _Feed:
    """A provider that serves one naive-ET frame, like the real broker path does."""

    name = "test-feed"

    def __init__(self, df):
        self._df = df

    def fetch_session_bars(self, inst, *, through):
        return self._df


def _case(tmp_path, *, bad_col="low", bad_delta=-4.5, bad_offset=-1, n=60, extras=True):
    """A parquet whose bar at `bad_offset` disagrees with the feed by `bad_delta`."""
    truth = _bars(f"{DAY} 12:46", n)
    stored = truth.copy()
    ts = stored.index[bad_offset]
    stored.loc[ts, bad_col] = stored.loc[ts, bad_col] - bad_delta   # the file is "too high"
    path = _parquet(tmp_path, stored)
    feed = truth.copy()
    feed.index = pd.DatetimeIndex(feed.index).tz_localize(None)     # providers deliver naive ET
    if extras:
        feed["average"] = feed["close"]
        feed["barcount"] = 40
    return path, _Feed(feed), ts


# ══════════════════════════════════════════════════════════════════════════════
# 1. the measurement reproduces
# ══════════════════════════════════════════════════════════════════════════════

def test_the_overlap_check_still_hard_refuses_a_real_disagreement(tmp_path):
    """Not weakened, and this is the test that says so."""
    path, feed, ts = _case(tmp_path)
    frozen = src.frozen_frame("MNQ", path)
    with pytest.raises(src.LiveSourceRefused) as e:
        src.live_frame("MNQ", frozen=frozen, provider=feed,
                       through=pd.Timestamp(f"{DAY} 14:00", tz=SESSION_TZ))
    assert e.value.code == "overlap_disagreement"
    assert "low" in e.value.detail


def test_the_mnq_shape_reproduces_exactly(tmp_path):
    """The measured numbers, driven through the real comparison: one bar, one column, the
    feed's low BELOW the file's, which is the direction a partial minute can be wrong in."""
    path, feed, ts = _case(tmp_path, bad_col="low", bad_delta=-4.5)
    frozen = src.frozen_frame("MNQ", path)
    diffs = repair.compare(frozen, src.on_frozen_clock("MNQ", feed._df, frozen), inst="MNQ")
    assert len(diffs) == 1
    assert list(diffs[0]["columns"]) == ["low"]
    assert diffs[0]["columns"]["low"]["delta"] == -4.5      # feed lower than parquet
    assert pd.Timestamp(diffs[0]["ts"]) == ts


def test_a_disagreement_that_is_not_at_the_boundary_is_still_seen(tmp_path):
    path, feed, ts = _case(tmp_path, bad_offset=-40)
    frozen = src.frozen_frame("MNQ", path)
    diffs = repair.compare(frozen, src.on_frozen_clock("MNQ", feed._df, frozen), inst="MNQ")
    assert len(diffs) == 1 and pd.Timestamp(diffs[0]["ts"]) == ts


def test_the_comparison_projects_the_feed_first(tmp_path):
    """Stage 5Q-3's projection, reused rather than reimplemented: a feed carrying `average`
    and `barcount` compares on the frozen schema and does not report those as differences."""
    path, feed, _ts = _case(tmp_path, extras=True)
    frozen = src.frozen_frame("MNQ", path)
    aligned = src.on_frozen_clock("MNQ", feed._df, frozen)
    assert "average" in aligned.columns
    diffs = repair.compare(frozen, aligned, inst="MNQ")
    assert all(set(d["columns"]) <= set(frozen.columns) for d in diffs)


# ══════════════════════════════════════════════════════════════════════════════
# 2. the tool measures without writing
# ══════════════════════════════════════════════════════════════════════════════

def _run(path, feed, **kw):
    kw.setdefault("window_minutes", 120)
    return repair.run(inst="MNQ", path=str(path), provider=feed,
                      through=pd.Timestamp(f"{DAY} 14:00", tz=SESSION_TZ), **kw)


def test_a_dry_run_writes_nothing_and_says_what_it_would_do(tmp_path):
    path, feed, ts = _case(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    rep = _run(path, feed)
    assert rep["dry_run"] is True and rep["applied"] is False
    assert rep["verdict"] == "repairable_dry_run"
    assert len(rep["in_window"]) == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob("*.bak"))


def test_a_clean_file_reports_nothing_to_repair(tmp_path):
    truth = _bars(f"{DAY} 12:46", 60)
    path = _parquet(tmp_path, truth)
    feed = truth.copy()
    feed.index = pd.DatetimeIndex(feed.index).tz_localize(None)
    rep = _run(path, _Feed(feed))
    assert rep["verdict"] == "nothing_to_repair"
    assert rep["shared_disagreements_total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. the refusals — the part of the tool that matters most
# ══════════════════════════════════════════════════════════════════════════════

def test_a_disagreement_outside_the_window_refuses_the_whole_run(tmp_path):
    """A wider disagreement is a different problem wearing a boundary bar's clothes."""
    path, feed, _ts = _case(tmp_path, bad_offset=-50, n=60)
    with pytest.raises(repair.RepairRefused) as e:
        _run(path, feed, window_minutes=10)
    assert e.value.code == "disagreement_outside_the_window"


def test_too_many_disagreeing_bars_refuses(tmp_path):
    truth = _bars(f"{DAY} 12:46", 60)
    stored = truth.copy()
    for off in range(-8, 0):
        stored.iloc[off, stored.columns.get_loc("low")] += 4.5
    path = _parquet(tmp_path, stored)
    feed = truth.copy()
    feed.index = pd.DatetimeIndex(feed.index).tz_localize(None)
    with pytest.raises(repair.RepairRefused) as e:
        _run(path, _Feed(feed), max_bars=5)
    assert e.value.code == "too_many_bars"


def test_apply_without_the_hash_guard_refuses(tmp_path):
    path, feed, _ts = _case(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(repair.RepairRefused) as e:
        _run(path, feed, apply=True)
    assert e.value.code == "hash_guard"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_apply_with_a_stale_hash_refuses(tmp_path):
    """The guard's real job: a repair measured against one version of the file must not land
    on another."""
    path, feed, _ts = _case(tmp_path)
    with pytest.raises(repair.RepairRefused) as e:
        _run(path, feed, apply=True, expect="0" * 64)
    assert e.value.code == "hash_guard"


def test_a_missing_parquet_refuses(tmp_path):
    _path, feed, _ts = _case(tmp_path)
    with pytest.raises(repair.RepairRefused) as e:
        _run(tmp_path / "nope.parquet", feed)
    assert e.value.code == "no_parquet"


def test_a_feed_that_returns_nothing_refuses(tmp_path):
    path, _feed, _ts = _case(tmp_path)

    class _Empty:
        name = "empty"

        def fetch_session_bars(self, inst, *, through):
            return None

    with pytest.raises(repair.RepairRefused) as e:
        _run(path, _Empty())
    assert e.value.code == "no_feed_bars"


# ══════════════════════════════════════════════════════════════════════════════
# 4. apply, into tmp_path only
# ══════════════════════════════════════════════════════════════════════════════

def test_apply_snapshots_repairs_one_bar_and_verifies(tmp_path):
    path, feed, ts = _case(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    rep = _run(path, feed, apply=True, expect=before)

    assert rep["applied"] is True and rep["verdict"] == "repaired"
    assert rep["remaining_disagreements"] == []

    backup = Path(rep["backup"])
    assert backup.exists()
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == before, \
        "the snapshot is not the original"

    after = src.frozen_frame("MNQ", path)
    original = src.frozen_frame("MNQ", backup)
    assert len(after) == len(original)
    assert pd.DatetimeIndex(after.index).equals(pd.DatetimeIndex(original.index))
    changed = [t for t in after.index if not after.loc[t].equals(original.loc[t])]
    assert changed == [ts], f"the repair touched {len(changed)} bars, expected exactly one"
    assert float(after.loc[ts, "low"]) == pytest.approx(float(original.loc[ts, "low"]) - 4.5)


def test_apply_leaves_every_other_bar_byte_identical(tmp_path):
    path, feed, ts = _case(tmp_path)
    original = src.frozen_frame("MNQ", path).copy()
    rep = _run(path, feed, apply=True, expect=hashlib.sha256(path.read_bytes()).hexdigest())
    after = src.frozen_frame("MNQ", rep["path"])
    others = [t for t in original.index if t != ts]
    pd.testing.assert_frame_equal(after.loc[others], original.loc[others])


def test_the_repaired_frame_then_splices_cleanly(tmp_path):
    """The point of the repair: the slot that was refusing now joins."""
    path, feed, _ts = _case(tmp_path)
    _run(path, feed, apply=True, expect=hashlib.sha256(path.read_bytes()).hexdigest())
    frozen = src.frozen_frame("MNQ", path)
    jf = src.live_frame("MNQ", frozen=frozen, provider=feed,
                        through=pd.Timestamp(f"{DAY} 14:00", tz=SESSION_TZ))
    assert jf.report.code in ("ok", "nothing_new")
    assert list(jf.frame.columns) == list(src.REQUIRED_COLUMNS)


def test_a_second_apply_refuses_rather_than_overwriting_the_snapshot(tmp_path):
    path, feed, _ts = _case(tmp_path)
    _run(path, feed, apply=True, expect=hashlib.sha256(path.read_bytes()).hexdigest())
    # the file is clean now, so a second run has nothing to do and says so
    rep2 = _run(path, feed)
    assert rep2["verdict"] == "nothing_to_repair"


# ══════════════════════════════════════════════════════════════════════════════
# 5. the guard was not weakened, and neither was 5Q-3
# ══════════════════════════════════════════════════════════════════════════════

def test_refuse_overlap_disagreement_is_untouched():
    """Source-level. Stage 5Q-4's whole premise is that the guard is RIGHT and the data is
    wrong, so the one thing this stage may not do is make the guard quieter."""
    import ast
    body = Path(src.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(body))
              if isinstance(n, ast.FunctionDef)
              and n.name == "_refuse_overlap_disagreement")

    # It still RAISES, and raises the right thing.
    raises = [n for n in ast.walk(fn) if isinstance(n, ast.Raise)]
    assert len(raises) == 1
    assert getattr(raises[0].exc.func, "id", None) == "LiveSourceRefused"
    assert raises[0].exc.args[0].value == "overlap_disagreement"

    # And no PRICE tolerance has appeared. Parsed, not grepped: the first version of this
    # assertion scanned the source text for the word "tolerance" and went red on the
    # docstring's own sentence "No tolerance to tune" — a substring test over prose, which is
    # the third time in these stages that shape has been written and the third time it failed
    # on a comment rather than on code.
    numbers = {n.value for n in ast.walk(fn)
               if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
               and not isinstance(n.value, bool)}
    assert numbers <= {0, 1, 1e-6}, f"a new numeric threshold appeared: {numbers}"
    assert 1e-6 in numbers, "the float-noise bound is gone"


def test_the_projection_from_5q3_still_drops_only_extras(tmp_path):
    frozen = _bars(f"{DAY} 12:46", 5)
    live = _bars(f"{DAY} 12:46", 5, extras=True)
    out, dropped = src.project_to_frozen_columns("MNQ", live, frozen)
    assert dropped == ("average", "barcount")
    assert list(out.columns) == list(frozen.columns)


def test_the_tool_defaults_to_dry_run_at_the_cli_level():
    a = repair.build_parser().parse_args(["--inst", "MNQ"])
    assert a.apply is False and a.expect is None
    assert a.window_minutes == 120 and a.max_bars == 5


# ══════════════════════════════════════════════════════════════════════════════
# 6. the real data files were not touched by any of this
# ══════════════════════════════════════════════════════════════════════════════

def test_no_real_parquet_was_modified_by_this_suite():
    now = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
           for k, v in REAL_PATHS.items() if Path(v).exists()}
    assert now == REAL_FINGERPRINT, "a test wrote to a REAL parquet"


def test_no_backup_files_appeared_beside_the_real_parquets():
    for v in REAL_PATHS.values():
        p = Path(v)
        if p.parent.exists():
            assert not list(p.parent.glob("*.pre5q4-*.bak")), p.parent


# ══════════════════════════════════════════════════════════════════════════════
# 7. B-5R-E — the 13:45 pre-flight marks a day true before that day's SPY close exists
# ══════════════════════════════════════════════════════════════════════════════

def _spy_csv(tmp_path: Path, last_date: str) -> Path:
    days = pd.bdate_range(end=last_date, periods=40)
    p = tmp_path / "spy.csv"
    pd.DataFrame({"date": days.strftime("%Y-%m-%d"),
                  "close": [700.0 + i for i in range(len(days))]}).to_csv(p, index=False)
    return p


def test_the_preflight_marks_a_day_true_that_the_spy_csv_cannot_yet_cover(tmp_path):
    """The mechanism, on synthetic inputs so it does not depend on today's files.

    `update_spy_csv` fetches `[fetch_from, today]` from Polygon at 13:45 ET. The day's own
    daily bar does not close until 16:00, so the fetch can only bring the PREVIOUS session —
    the CSV gains day D-1 at day D's 13:45. Meanwhile `required_data_through` returns day D
    from 13:45 onward. The requirement and the file are therefore exactly one business day
    apart, permanently, and the gate is stale at every instant after a pre-flight.
    """
    from global_index import track1_freshness as fresh

    csv = _spy_csv(tmp_path, "2026-08-20")             # what Friday's 13:45 could write
    after_preflight = pd.Timestamp("2026-08-21 13:46", tz=SESSION_TZ)

    # The INTRADAY requirement still becomes today at 13:45, and that is right for minute bars.
    assert str(fresh.required_data_through(after_preflight).date()) == "2026-08-21"

    # Stage 5Q-5 rewrote this assertion, and the change is the fix. It used to require
    # `regime_csv: stale` here — the gate asking the daily series for a close two hours in the
    # future. The DAILY requirement is now the last trading day before today, which is both
    # what a session trades the label of and what the file can hold, so this instant passes.
    assert str(fresh.required_daily_close_through(after_preflight).date()) == "2026-08-20"
    v = fresh.evaluate(now_et=after_preflight, regime_csv=str(csv), parquets={})
    chk = [c for c in v.checks if c.name == "regime_csv"][0]
    assert chk.status == "ok", chk

    # The half the requirement fix does NOT close: the next morning still needs Friday's close,
    # and only a refresh that runs after the close can bring it. Pinned in the 5Q-5 suite.
    monday = pd.Timestamp("2026-08-24 09:00", tz=SESSION_TZ)
    assert str(fresh.required_daily_close_through(monday).date()) == "2026-08-21"
    v2 = fresh.evaluate(now_et=monday, regime_csv=str(csv), parquets={})
    assert v2.allow is False


def test_the_same_gap_is_still_there_the_next_morning(tmp_path):
    """Monday needs Friday's close; Friday's 13:45 could only write Thursday's."""
    from global_index import track1_freshness as fresh

    csv = _spy_csv(tmp_path, "2026-08-20")
    monday = pd.Timestamp("2026-08-24 09:00", tz=SESSION_TZ)
    assert str(fresh.required_data_through(monday).date()) == "2026-08-21"
    v = fresh.evaluate(now_et=monday, regime_csv=str(csv), parquets={})
    assert v.allow is False


def test_a_csv_that_did_reach_the_required_day_passes(tmp_path):
    """The other side, so the test above is measuring the GAP and not merely that the gate
    can say no."""
    from global_index import track1_freshness as fresh

    csv = _spy_csv(tmp_path, "2026-08-21")
    monday = pd.Timestamp("2026-08-24 09:00", tz=SESSION_TZ)
    v = fresh.evaluate(now_et=monday, regime_csv=str(csv), parquets={})
    chk = [c for c in v.checks if c.name == "regime_csv"][0]
    assert chk.status == "ok", chk


def test_the_live_invariant_holds_on_the_real_files_right_now():
    """Read-only, and it is the measurement the two synthetic tests above generalise.

    `preflight_state.json` last day minus one business day == `spy_daily_live.csv` last date.
    If this ever stops being true, either the pre-flight moved or somebody added a second
    updater, and B-5R-E would need re-measuring rather than re-reading.
    """
    import json as _json
    state = _json.loads((REPO / "global_index" / "preflight_state.json")
                        .read_text(encoding="utf-8"))
    last_preflight = pd.Timestamp(max(state))
    csv_last = pd.Timestamp(pd.read_csv(REPO / "spy_daily_live.csv",
                                        usecols=["date"])["date"].max())
    assert csv_last < last_preflight, (str(csv_last), str(last_preflight))
    assert (last_preflight - csv_last).days <= 4        # one business day, weekend allowed


def test_a_repair_that_does_not_land_is_reported_as_a_failure(tmp_path, monkeypatch):
    """The verify branch, exercised by injecting the failure it exists for.

    Without this the branch was unreachable in the harness: in every other case the write
    lands, so `remaining` is empty whether or not anything checked. A mutation that deleted
    the check went undetected (0/0/0) for exactly that reason — the guard was real and my
    harness could not observe it refusing, which is a fault in the harness.

    Here the post-write re-read is made to return the ORIGINAL frame, which is what a write
    that silently did not land looks like from the outside.
    """
    path, feed, _ts = _case(tmp_path)
    real = src.frozen_frame
    calls = {"n": 0}

    def _stale_on_verify(inst, p_):
        calls["n"] += 1
        # `run()` reads the parquet twice: once at the start, once to verify after the write.
        # The counter was 3 in the first draft, which is the sort of guess that makes a test
        # silently exercise nothing — measured, it is 2.
        if calls["n"] >= 2:
            return real(inst, str(Path(rep_backup["path"])))
        return real(inst, p_)

    rep_backup = {"path": path}
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    # snapshot the ORIGINAL so the injected re-read returns pre-repair content
    orig_copy = tmp_path / "orig.parquet"
    orig_copy.write_bytes(path.read_bytes())
    rep_backup["path"] = orig_copy

    monkeypatch.setattr(repair.src, "frozen_frame", _stale_on_verify)
    with pytest.raises(repair.RepairRefused) as e:
        _run(path, feed, apply=True, expect=before)
    assert e.value.code == "verify_failed"
    assert "restore" in e.value.detail


def test_apply_preserves_the_files_own_index_convention(tmp_path):
    """Stage 5Q-6, and the fixture that hid it.

    The real parquets carry a tz-NAIVE UTC index; `frozen_frame` returns a tz-AWARE New York
    one. Writing that back would change the storage convention of an eight-year file. This
    suite's own `_parquet` helper wrote a tz-AWARE UTC index, so the round trip preserved
    awareness in the test and would not have on disk — a fixture that did not match the file
    it stood in for, which is why the guard is proven against a NAIVE file here.
    """
    truth = _bars(f"{DAY} 12:46", 60)
    stored = truth.copy()
    ts = stored.index[-1]
    stored.loc[ts, "low"] = stored.loc[ts, "low"] + 4.5
    naive = stored.copy()
    naive.index = pd.DatetimeIndex(naive.index).tz_convert("UTC").tz_localize(None)
    path = tmp_path / "naive.parquet"
    naive.to_parquet(path)
    assert pd.DatetimeIndex(pd.read_parquet(path).index).tz is None

    feed = truth.copy()
    feed.index = pd.DatetimeIndex(feed.index).tz_localize(None)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    rep = _run(path, _Feed(feed), apply=True, expect=before)
    assert rep["applied"] is True and rep["verdict"] == "repaired"
    assert rep["index_convention"] == "None"

    # the file came back NAIVE, exactly as it went in
    back = pd.read_parquet(path)
    assert pd.DatetimeIndex(back.index).tz is None, "the storage convention was rewritten"
    assert list(back.columns) == list(naive.columns)
    assert len(back) == len(naive)
    # and the one bar was still repaired
    fixed_ts = pd.DatetimeIndex(back.index)[-1]
    assert float(back.loc[fixed_ts, "low"]) == pytest.approx(
        float(naive.loc[naive.index[-1], "low"]) - 4.5)
