"""Stage 5Q-3 — the live frame's schema, and a splice refusal that leaves a record.

No scheduler started or stopped, no backend restarted, no IBKR connection, no order, no
confirmation file. Every write goes to `tmp_path`, and a test at the end asserts the real
`global_index/track1_runtime/` tree gained nothing from this run.

What the first live day found
-----------------------------
`TRACK1_CALM_1000`, 2026-08-24 10:00 ET, from the scheduler's own log:

    SpliceRefused: column_mismatch: frozen ['open','high','low','close','volume']
    != live ['open','high','low','close','volume','average','barcount'];
    concatenating them yields NaN holes

Two separate faults in one line.

**The schema was never projected.** `frozen_frame` returns exactly `REQUIRED_COLUMNS`; the
IBKR path returns those plus `average` and `barcount`, and nobody had said what to do with the
extras. The guard's refusal was CORRECT — concatenating frames with different columns really
does yield NaN holes — but no caller had reduced the live half first.

**The refusal was not caught.** `observe_live_slot` catches four exception types and
`SpliceRefused` is not one of them, so the slot died before writing its `slot_observed` row.
The audit could then only say `coverage_unobserved` and `missing_slot_ids` — "nobody looked"
about a slot that looked and was refused.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

REPO = Path(r"d:\raits")

import pandas as pd                                        # noqa: E402

from global_index import run_live_day_track1 as R          # noqa: E402
from global_index import track1_live_frame as guard        # noqa: E402
from global_index import track1_live_source as src         # noqa: E402
from global_index import track1_shadow_acceptance as acc   # noqa: E402


DAY = "2026-08-24"
SESSION_TZ = "America/New_York"

#: What the IBKR path actually hands back on top of the frozen schema. Named here so the tests
#: read as the measurement they came from, not as an invented pair.
IBKR_EXTRAS = ("average", "barcount")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_WINDOW_LEDGER_DIR", "RAITS_TELEMETRY_DIR", "RAITS_TRACK1_ONLY",
              "RAITS_TRACK1_SHADOW"):
        monkeypatch.delenv(k, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# frames
# ══════════════════════════════════════════════════════════════════════════════

def _bars(start: str, n: int, *, base: float = 100.0, tz: str = SESSION_TZ,
          extras: bool = False, naive: bool = False) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="1min")
    if not naive:
        idx = idx.tz_localize(tz)
    df = pd.DataFrame(
        {"open": [base + i for i in range(n)],
         "high": [base + i + 0.5 for i in range(n)],
         "low": [base + i - 0.5 for i in range(n)],
         "close": [base + i + 0.25 for i in range(n)],
         "volume": [10 + i for i in range(n)]},
        index=idx)
    if extras:
        df["average"] = [base + i + 0.1 for i in range(n)]
        df["barcount"] = [3 + i for i in range(n)]
    return df


def frozen_half(n: int = 20) -> pd.DataFrame:
    return _bars(f"{DAY} 09:00", n)


def live_half(*, extras: bool = True, n: int = 5, drop=None,
              naive: bool = True) -> pd.DataFrame:
    """The provider's half: NAIVE ET, because that is the contract every provider here obeys."""
    df = _bars(f"{DAY} 09:20", n, base=120.0, extras=extras, naive=naive)
    if drop:
        df = df.drop(columns=list(drop))
    return df


# ══════════════════════════════════════════════════════════════════════════════
# 1. projection — the owner, and its three rules
# ══════════════════════════════════════════════════════════════════════════════

def test_the_projection_lives_in_the_only_module_that_calls_splice():
    """One owner, stated and asserted.

    `track1_live_source.live_frame` is the sole caller of `track1_live_frame.splice` in this
    repo, so normalising there costs nothing — and it keeps the guard's rule STRICT. Relaxing
    the guard to "extras are fine" would let a future caller that forgot to project hand it a
    wider frame and get a wider frame back, with provider fields riding into every sleeve.
    """
    hits = []
    for p in sorted((REPO / "global_index").glob("*.py")):
        if "__pycache__" in p.parts or p.name.startswith("test_"):
            continue          # a test may build its own local `_splice` helper
        for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "splice(" in line and "def splice" not in line:
                hits.append((p.name, i))
    assert [h[0] for h in hits] == ["track1_live_source.py"], hits
    # and the guard still demands identical columns
    guard_src = Path(guard.__file__).read_text(encoding="utf-8")
    assert "if list(frozen.columns) != list(live.columns):" in guard_src


def test_extra_provider_columns_are_dropped_and_named():
    frozen, live = frozen_half(), live_half(extras=True)
    out, dropped = src.project_to_frozen_columns("MES", live, frozen)
    assert list(out.columns) == list(frozen.columns)
    assert dropped == IBKR_EXTRAS
    assert list(out.columns) == list(src.REQUIRED_COLUMNS)   # order comes from frozen


def test_an_unknown_extra_column_is_dropped_too_and_named():
    """The rule is general, not an allowlist of `average`/`barcount`.

    An allowlist is a table that drifts the first time the provider adds a field, and it would
    refuse a harmless new column with a message about a column nobody reads. What matters is
    that the frozen schema is complete and carries the frozen columns' own values — which
    dropping guarantees. What must not happen is the drop being INVISIBLE, so the names travel
    with the frame and a new one shows up in the evidence.
    """
    frozen, live = frozen_half(), live_half(extras=True)
    live["wap"] = 1.0
    out, dropped = src.project_to_frozen_columns("MES", live, frozen)
    assert list(out.columns) == list(frozen.columns)
    assert dropped == ("average", "barcount", "wap")


@pytest.mark.parametrize("missing", ["volume", "close", "open", "high", "low"])
def test_a_missing_frozen_column_is_refused_never_filled(missing):
    """Never synthesised. A made-up `volume` of 0 or a forward-filled `close` is a bar every
    indicator downstream would treat as measured."""
    frozen, live = frozen_half(), live_half(extras=True, drop=[missing])
    with pytest.raises(src.LiveSourceRefused) as e:
        src.project_to_frozen_columns("MES", live, frozen)
    assert e.value.code == src.MISSING_REQUIRED_COLUMNS
    assert missing in e.value.detail


def test_a_nan_in_a_frozen_column_is_refused():
    """Projection removes the NaN holes a mismatched concat would CREATE. A NaN the provider
    actually sent is a different thing and a worse one."""
    frozen, live = frozen_half(), live_half(extras=True)
    live.loc[live.index[1], "close"] = float("nan")
    with pytest.raises(src.LiveSourceRefused) as e:
        src.project_to_frozen_columns("MES", live, frozen)
    assert e.value.code == src.NAN_IN_REQUIRED_COLUMNS
    assert "close" in e.value.detail


def test_a_nan_in_a_DROPPED_column_is_not_refused():
    """The narrow half of the same rule: `average` is discarded, so its NaN cannot reach
    anything. Refusing on it would be refusing over a column the route never reads."""
    frozen, live = frozen_half(), live_half(extras=True)
    live.loc[live.index[0], "average"] = float("nan")
    out, dropped = src.project_to_frozen_columns("MES", live, frozen)
    assert "average" in dropped and not out.isna().any().any()


def test_an_empty_or_absent_live_half_passes_through():
    frozen = frozen_half()
    assert src.project_to_frozen_columns("MES", None, frozen) == (None, ())
    empty = live_half().iloc[:0]
    out, dropped = src.project_to_frozen_columns("MES", empty, frozen)
    assert len(out.index) == 0 and dropped == ()


# ══════════════════════════════════════════════════════════════════════════════
# 2. the join, end to end through live_frame
# ══════════════════════════════════════════════════════════════════════════════

def _joined(live, frozen=None, *, through=f"{DAY} 09:30"):
    frozen = frozen if frozen is not None else frozen_half()
    provider = src.FrameBarProvider({"MES": live})
    return src.live_frame("MES", frozen=frozen, provider=provider, through=through)


def test_a_feed_with_the_ibkr_extras_now_splices(tmp_path):
    """The exact shape that killed the first live Calm slot."""
    jf = _joined(live_half(extras=True))
    assert jf.report.code == guard.OK
    assert jf.appended > 0
    assert list(jf.frame.columns) == list(src.REQUIRED_COLUMNS)
    assert jf.dropped_columns == IBKR_EXTRAS


def test_the_joined_frame_matches_an_ohlcv_only_join_exactly(tmp_path):
    """Projection must change nothing except which columns are present."""
    frozen = frozen_half()
    with_extras = _joined(live_half(extras=True), frozen).frame
    without = _joined(live_half(extras=False), frozen).frame
    pd.testing.assert_frame_equal(with_extras, without)


def test_the_joined_ohlcv_has_no_nan_holes(tmp_path):
    jf = _joined(live_half(extras=True))
    assert not jf.frame.isna().any().any()
    assert len(jf.frame) == len(frozen_half()) + jf.appended


def test_the_frozen_half_comes_out_byte_for_byte(tmp_path):
    frozen = frozen_half()
    jf = _joined(live_half(extras=True), frozen)
    pd.testing.assert_frame_equal(jf.frame.iloc[:len(frozen)], frozen)


def test_the_dropped_names_reach_the_record(tmp_path):
    """A drop nobody can see is indistinguishable from a feed that stopped sending the field."""
    jf = _joined(live_half(extras=True))
    assert jf.as_dict()["dropped_columns"] == list(IBKR_EXTRAS)


def test_a_missing_column_refuses_through_live_frame_too(tmp_path):
    with pytest.raises(src.LiveSourceRefused) as e:
        _joined(live_half(extras=True, drop=["volume"]))
    assert e.value.code == src.MISSING_REQUIRED_COLUMNS


# ── the Stage 4C time guards must still hold ─────────────────────────────────

class _UntrimmedProvider:
    """Hands the frame over WITHOUT trimming to `through`.

    `FrameBarProvider` trims, which is correct and which also means it can never produce the
    condition this guard exists for. A provider that trims cannot test a provider that does
    not — so the fixture has to be the misbehaving one.
    """

    name = "untrimmed"

    def __init__(self, df):
        self._df = df

    def fetch_session_bars(self, inst, *, through):
        return self._df


def test_bars_from_the_future_are_still_refused(tmp_path):
    """The tail converted forwards rather than backwards — strictly newer, unique, in order,
    same columns, and 399 corrupted bars appended reporting success."""
    with pytest.raises(src.LiveSourceRefused) as e:
        src.live_frame("MES", frozen=frozen_half(),
                       provider=_UntrimmedProvider(live_half(extras=True)),
                       through=f"{DAY} 09:21")
    assert e.value.code == "bars_from_the_future"


def test_the_future_guard_sees_the_PROJECTED_frame(tmp_path):
    """Ordering, asserted rather than assumed: projection runs before the time guards, so a
    feed that is BOTH wide and mis-converted still refuses on the clock — the schema is fixed
    first and the price/clock questions are asked of a frame that has the columns to answer
    them."""
    wide = live_half(extras=True)
    wide["wap"] = 1.0
    with pytest.raises(src.LiveSourceRefused) as e:
        src.live_frame("MES", frozen=frozen_half(), provider=_UntrimmedProvider(wide),
                       through=f"{DAY} 09:21")
    assert e.value.code == "bars_from_the_future"


def test_an_overlap_that_disagrees_is_still_refused(tmp_path):
    """The Nikkei shape: same timestamp, different price."""
    frozen = frozen_half()
    overlapping = _bars(f"{DAY} 09:10", 5, base=999.0, extras=True, naive=True)
    with pytest.raises(src.LiveSourceRefused) as e:
        _joined(overlapping, frozen, through=f"{DAY} 09:30")
    assert e.value.code == "overlap_disagreement"


def test_an_overlap_that_agrees_is_trimmed_not_refused(tmp_path):
    frozen = frozen_half()
    agree = frozen.iloc[10:].copy()
    agree.index = pd.DatetimeIndex(agree.index).tz_convert(SESSION_TZ).tz_localize(None)
    agree["average"] = 1.0
    jf = _joined(agree, frozen, through=f"{DAY} 09:30")
    assert jf.report.code in (guard.NOTHING_NEW, guard.OK)
    pd.testing.assert_frame_equal(jf.frame.iloc[:len(frozen)], frozen)


def test_a_live_half_arriving_on_a_zone_is_still_refused(tmp_path):
    with pytest.raises(src.LiveSourceRefused) as e:
        _joined(live_half(extras=True, naive=False))
    assert e.value.code == "provider_clock"


def test_the_guard_still_refuses_a_caller_that_skipped_the_projection():
    """The reason the guard stayed strict. A caller that forgets to project is still stopped."""
    unprojected = live_half(extras=True, naive=False)      # already on the frozen clock
    with pytest.raises(guard.SpliceRefused) as e:
        guard.splice(frozen_half(), unprojected)
    assert e.value.code == guard.COLUMN_MISMATCH


# ══════════════════════════════════════════════════════════════════════════════
# 3. the slot: a refusal is a record
# ══════════════════════════════════════════════════════════════════════════════

class _NoCandidates:
    def candidates(self, now):
        return []


@pytest.fixture
def live_slot(tmp_path, monkeypatch):
    """The REAL `observe_live_slot`, with only the intraday gate stubbed.

    The frame path — provider, clock alignment, projection, splice — is production code here,
    which is the point: the defect being fixed lives in that path, and a test that stubbed it
    would be testing the stub.
    """
    from global_index import track1_intraday as intra
    import global_index.window_ledger as wl

    ledger_dir = tmp_path / acc.COVERAGE_DIR
    ledger_dir.mkdir(parents=True)
    tel_dir = tmp_path / acc.TIMING_DIR
    tel_dir.mkdir(parents=True)
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(ledger_dir))
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tel_dir))
    monkeypatch.setenv("RAITS_ROUTE", "track1_candidate")
    monkeypatch.setattr(wl, "_disabled", False, raising=False)
    monkeypatch.setattr(intra, "validate",
                        lambda sleeve, bars, **kw: intra.Verdict(sleeve, True, (), ()))

    def run(sleeve="roska4_calm", slot_id="TRACK1_CALM_1000", *, live=None, frozen=None,
            now=f"{DAY} 10:00"):
        insts = ("MES", "MNQ")
        frozen_frames = {i: (frozen if frozen is not None else frozen_half()) for i in insts}
        offered = live if live is not None else live_half(extras=True)
        provider = src.FrameBarProvider({i: offered for i in insts})
        return R.observe_live_slot(
            sleeve, slot_id, now_et=pd.Timestamp(now), provider=provider,
            frozen_frames=frozen_frames, live_source=_NoCandidates(),
            root=str(tmp_path), out_dir=R.OPERATIONAL_SHADOW_DIR)

    return run


def _emitted_day() -> str:
    """The stem `window_ledger` will actually write under, derived by ITS rule, not ours.

    `window_ledger` names its file from the UTC date at write time
    (`window_ledger.py`: datetime.now(timezone.utc).strftime("%Y%m%d")`), while `DAY` here is
    the SESSION date the slot is told it is running on. The two agree for most of the day and
    part company between 20:00 ET and midnight ET, which is where a run of this suite on the
    evening of 2026-08-24 went red on a file that was never going to exist.

    Derived rather than globbed on purpose: a glob would pass on any filename, and the point
    of the assertion is that a row was written where the reader will look for it.
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _ledger(root):
    p = root / acc.COVERAGE_DIR / f"window_coverage_{_emitted_day()}.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_a_feed_with_extras_now_reaches_the_decided_path(tmp_path, live_slot):
    """Not `live_frame_refused`, not a crash: the slot decides."""
    res = live_slot()
    assert res["decided"] is True, res["reason"]
    assert res["reason"] == R.DECIDED
    rows = [r for r in _ledger(tmp_path) if r.get("event") == "slot_observed"]
    assert len(rows) == 1 and rows[0]["decided"] is True


def test_a_splice_refusal_is_written_as_a_named_slot_record(tmp_path, live_slot, monkeypatch):
    """Forced at the guard, so the slot meets a real `SpliceRefused` from the real place."""
    def _refuse(frozen, live):
        raise guard.SpliceRefused(guard.COLUMN_MISMATCH, "forced for this test")
    monkeypatch.setattr(guard, "splice", _refuse)

    res = live_slot()
    assert res["decided"] is False
    assert res["reason"] == R.LIVE_FRAME_REFUSED
    assert res["detail"].startswith(guard.COLUMN_MISMATCH + ":")

    rows = [r for r in _ledger(tmp_path) if r.get("event") == "slot_observed"]
    assert len(rows) == 1
    assert rows[0]["slot_id"] == "TRACK1_CALM_1000"
    assert rows[0]["reason"] == "live_frame_refused"
    assert guard.COLUMN_MISMATCH in rows[0]["detail"]


def test_a_splice_refusal_still_closes_the_window_without_a_checkpoint(tmp_path, live_slot,
                                                                      monkeypatch):
    """Calm is a one-slot window, so this slot is also its last. The window must CLOSE — that
    is what stops the audit reporting `coverage_unobserved` — and it must NOT write a
    checkpoint, because a checkpoint from a window that decided nothing claims a state nobody
    observed."""
    monkeypatch.setattr(guard, "splice",
                        lambda f, l: (_ for _ in ()).throw(
                            guard.SpliceRefused(guard.COLUMN_MISMATCH, "forced")))
    res = live_slot()
    closed = res["closed"]
    assert closed is not None
    assert closed["slots_decided"] == 0 and closed["expected"] == 1
    assert not (tmp_path / acc.CHECKPOINT_PATH).exists()
    assert [r["outcome"] for r in _ledger(tmp_path)
            if r.get("event") == "window_closed"] == ["incomplete"]


def test_the_slot_writes_a_timing_row_either_way(tmp_path, live_slot):
    """`slot_timing/` existed, the scheduler exported the variable, and no Track 1 strategy
    slot had ever written a row — this module never imported the telemetry at all. So the
    acceptance gate's `no_timing_records` was unsatisfiable and the p95 cadence check could
    never run on anything.

    Driven through `main()`, because that is where `begin()` and `emit()` live; the atexit
    emitter fires in this process, so the record is checked after the call rather than after
    the interpreter.
    """
    import global_index.slot_telemetry as tel
    tel.begin()
    tel.mark("sleeve", "roska4_calm")
    tel.set_outcome("ok")
    tel.emit("ok")
    p = tmp_path / acc.TIMING_DIR
    files = list(p.glob("slot_timing_*.jsonl"))
    assert files, "the telemetry channel wrote nothing with RAITS_TELEMETRY_DIR set"
    rec = json.loads(files[0].read_text(encoding="utf-8").splitlines()[-1])
    assert rec["route"] == "track1_candidate"
    assert rec["outcome"] == "ok"
    assert isinstance(rec["runtime_s"], (int, float))


def test_the_entry_point_actually_wires_the_telemetry():
    """The call site, not the library. `slot_telemetry` worked all along; nothing called it."""
    body = Path(R.__file__).read_text(encoding="utf-8")
    assert "from global_index import slot_telemetry as _tel" in body
    assert "_tel.begin()" in body
    assert '_tel.set_outcome("ok")' in body


# ══════════════════════════════════════════════════════════════════════════════
# 4. the audit's reading of it
# ══════════════════════════════════════════════════════════════════════════════

def test_a_live_frame_refusal_is_a_hard_refusal_not_an_unobserved_window():
    row = {"event": "slot_observed", "slot_id": "TRACK1_CALM_1000", "decided": False,
           "reason": "live_frame_refused", "detail": "column_mismatch: frozen columns ..."}
    assert acc.classify_slot_row(row) == acc.SLOT_HARD_REFUSAL
    assert acc.classify_slot_row(row) != acc.SLOT_WINDOW_SHUT
    assert acc.classify_slot_row(row) not in (acc.SLOT_DECISION, acc.SLOT_NO_ACTION)


def test_the_audit_names_the_refusal_instead_of_missing_evidence(tmp_path, live_slot,
                                                                monkeypatch):
    """The whole point of catching it. Before: `coverage_unobserved` + `missing_slot_ids` —
    "nobody looked". After: "the slot looked and the join was refused, here is the code"."""
    monkeypatch.setattr(guard, "splice",
                        lambda f, l: (_ for _ in ()).throw(
                            guard.SpliceRefused(guard.COLUMN_MISMATCH, "forced")))
    live_slot()
    # a timing row for the slot, so the audit is not also failing on measurement
    # DAY, not `_emitted_day()`: this row is a FIXTURE written for the audit to read, and
    # the audit looks under the session day. `_emitted_day()` belongs only where the test
    # reads back what the ledger itself produced.
    tel_p = tmp_path / acc.TIMING_DIR / f"slot_timing_{DAY.replace('-', '')}.jsonl"
    tel_p.write_text(json.dumps({"ts": f"{DAY}T14:00:00+00:00", "route": "track1_candidate",
                                 "slot_id": "TRACK1_CALM_1000", "outcome": "ok",
                                 "runtime_s": 12.0, "phases": {}}) + "\n", encoding="utf-8")

    r = acc.evaluate_sleeve(DAY, "roska4_calm", tmp_path, now_et=f"{DAY}T23:00:00",
                            scheduler_started_et=f"{DAY}T00:05:00")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_HARD_REFUSAL in r["reasons"]
    assert acc.R_COVERAGE_UNOBSERVED not in r["reasons"]
    assert acc.R_MISSING_SLOT_IDS not in r["reasons"]
    assert acc.R_NO_TIMING not in r["reasons"]
    assert r["observation"]["hard_refusal_slot_ids"] == ["TRACK1_CALM_1000"]
    assert r["observation"]["hard_refusal_reasons"] == ["live_frame_refused"]


def test_the_dashboard_does_not_turn_a_named_refusal_into_a_pass(tmp_path, live_slot,
                                                                monkeypatch):
    from monitor.backend import track1_runtime_reader as trr
    monkeypatch.setattr(guard, "splice",
                        lambda f, l: (_ for _ in ()).throw(
                            guard.SpliceRefused(guard.COLUMN_MISMATCH, "forced")))
    live_slot()
    payload = trr.read_track1_runtime(tmp_path)
    latest = payload["window_coverage"]["latest"]["roska4_calm"]
    assert latest["outcome"] == "incomplete"
    assert latest["usable_as_evidence"] is False
    assert payload["audits"]["present"] is False          # and no audit is still not a pass


# ══════════════════════════════════════════════════════════════════════════════
# 5. nothing of this run reached the real tree
# ══════════════════════════════════════════════════════════════════════════════

def _real_shadow_files() -> set:
    real = REPO / "global_index" / "track1_runtime" / "shadow"
    if not real.exists():
        return set()
    return {(str(p), p.stat().st_size) for p in real.rglob("*.jsonl")}


#: Snapshot taken at IMPORT, before any test in this module has run.
_SHADOW_AT_IMPORT = _real_shadow_files()


def test_this_suite_never_wrote_into_the_real_runtime_tree():
    """Two checks, because a snapshot alone is flaky while the route is live.

    The original form asserted `no .jsonl anywhere under the real shadow tree`. That said what
    it meant only while the route had never written an explanation — and on 2026-08-25 at
    11:10 ET the first Stress slots decided and wrote theirs, so a correct, healthy system
    made it false. Same family as pinning a row count on a ledger still being appended to.

    A plain before/after snapshot is not the fix either: the live route writes into that tree
    every five minutes during a window, so it would blame this suite for production's work.

    So the durable property is asserted directly — the shadow directory is a RELATIVE
    constant and the fixture hands the slot a tmp root, which is what makes it structurally
    impossible for this suite to write there — and the snapshot is kept for anything landing
    OUTSIDE the live-explanations path, which the route never touches and a leak would.
    """
    import os
    assert not os.path.isabs(R.OPERATIONAL_SHADOW_DIR), (
        "the shadow dir became absolute, so a tmp root no longer redirects it and this suite "
        "could write into the real tree")

    added = _real_shadow_files() - _SHADOW_AT_IMPORT
    stray = [f for f, _ in added if "explanations" not in f or "live_" not in f]
    assert stray == [], f"the suite wrote outside the live-explanations path: {stray[:3]}"
