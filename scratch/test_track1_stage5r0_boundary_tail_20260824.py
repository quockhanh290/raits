"""Stage 5R-0 — B-5R-H: the updater must never persist a minute still in progress.

READ-ONLY of production data. No scheduler, no backend, no broker, no order, no confirmation
file. Every parquet, CSV and sidecar this suite writes lives under `tmp_path`, and a test at
the end proves the real files are byte-identical to what they were at import.

The defect
----------
`--repair-boundary` (Stage 5Q-5) repairs the partial bar the PREVIOUS run left behind. It
cannot help the one the CURRENT run is about to create: the fetch asks for "now", IBKR answers
with the minute in progress, and the append stores that snapshot as a finished bar.

Measured 2026-08-24: one 13:45 pre-flight left partial bars in three of five instruments;
repairing them at 20:20 immediately left three more, at 20:20 and 20:21. Repairing moves the
defect one minute later. Only refusing to store it removes it.

How this is tested
------------------
Tests 1, 2, 4 and 5 drive `drop_open_final_bar` directly, because it is a pure function of two
values and deserves to be tested as one. Tests 3, 8 and the write-convention checks drive the
REAL `main()` end to end against a stubbed `ib_insync` and parquets under `tmp_path` — the
whole append path, including `_fetch_contfuture`'s own clock stamp, the splice, the history
invariant and the convention assertion. A test that stubbed the append would be testing the
stub, and the append is where the defect lives.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(r"d:\raits")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import run_live_day_track1 as R          # noqa: E402
from global_index import track1_live_source as src         # noqa: E402
from global_index import update_ibkr_daily as U            # noqa: E402
from global_index.ibkr_broker import ibkr_symbol_and_exchange  # noqa: E402

REAL_FILES = {**R.default_data_paths(), "spy": "spy_daily_live.csv",
              "preflight": "global_index/preflight_state.json",
              "offsets": "global_index/_splice_offsets.json"}
REAL_FINGERPRINT = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
                    for k, v in REAL_FILES.items() if Path(v).exists()}

COLS = ["open", "high", "low", "close", "volume"]


def bars(start: str, n: int, *, base: float = 5000.0) -> pd.DataFrame:
    """`n` one-minute UTC-naive bars from `start`. Deliberately boring values.

    `base` is 5000, not 100, and that is a fixture bug this suite already made once: the
    one-point-per-minute ramp is a 0.365% step on a price of 205, which trips the REAL
    `JOIN_JUMP_MAX_PCT` guard at 0.35% and refuses the append. The guard was right and the
    fixture was cheap — synthetic data has to sit in the range the production thresholds were
    measured for, or the test measures the fixture."""
    idx = pd.date_range(start, periods=n, freq="min")
    return pd.DataFrame(
        {"open": [base + i for i in range(n)],
         "high": [base + i + 0.5 for i in range(n)],
         "low": [base + i - 0.5 for i in range(n)],
         "close": [base + i + 0.25 for i in range(n)],
         "volume": [10.0 + i for i in range(n)]},
        index=idx)


# ══════════════════════════════════════════════════════════════════════════════
# 1, 2, 4, 5 — the rule itself
# ══════════════════════════════════════════════════════════════════════════════

def test_1_a_fetch_ending_inside_the_final_minute_drops_that_bar():
    df = bars("2026-08-24 17:40", 6)          # last bar stamped 17:45
    out, dropped, why = U.drop_open_final_bar(df, observed_utc=pd.Timestamp("2026-08-24 17:45:30"))
    assert dropped == pd.Timestamp("2026-08-24 17:45")
    assert len(out) == 5 and out.index[-1] == pd.Timestamp("2026-08-24 17:44")
    assert "still open" in why


def test_2_a_fetch_ending_after_the_final_minute_keeps_that_bar():
    df = bars("2026-08-24 17:40", 6)
    out, dropped, why = U.drop_open_final_bar(df, observed_utc=pd.Timestamp("2026-08-24 17:46:00"))
    assert dropped is None
    assert out.index[-1] == pd.Timestamp("2026-08-24 17:45")
    assert len(out) == 6 and why == U.TAIL_KEPT


def test_2b_the_boundary_instant_is_inclusive_and_one_second_earlier_is_not():
    """T+60s exactly is complete; T+59s is not. Pinned because "about a minute" is how a
    threshold gets tuned into meaninglessness."""
    df = bars("2026-08-24 17:40", 6)
    last = pd.Timestamp("2026-08-24 17:45")
    _, d_at, _ = U.drop_open_final_bar(df, observed_utc=last + pd.Timedelta(seconds=60))
    _, d_before, _ = U.drop_open_final_bar(df, observed_utc=last + pd.Timedelta(seconds=59))
    assert d_at is None
    assert d_before == last


def test_4_no_closed_bar_is_ever_dropped_however_late_the_observation():
    """Only the FINAL bar is a candidate. An interior bar cannot be in progress, and a
    function that could drop one would be a filter rather than a tail guard."""
    df = bars("2026-08-24 17:40", 6)
    for offset in (60, 61, 600, 86400):
        out, dropped, _ = U.drop_open_final_bar(
            df, observed_utc=df.index[-1] + pd.Timedelta(seconds=offset))
        assert dropped is None
        assert out.equals(df), offset
    # and even in the drop case, exactly one bar goes
    out, dropped, _ = U.drop_open_final_bar(df, observed_utc=df.index[-1])
    assert len(out) == len(df) - 1
    assert out.equals(df.iloc[:-1])


def test_4b_an_empty_or_single_bar_fetch_is_handled_without_inventing_one():
    empty = pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], name=None))
    out, dropped, why = U.drop_open_final_bar(empty, observed_utc=pd.Timestamp("2026-08-24 18:00"))
    assert dropped is None and why == U.TAIL_NO_BARS and len(out) == 0
    out, dropped, _ = U.drop_open_final_bar(None, observed_utc=pd.Timestamp("2026-08-24 18:00"))
    assert out is None and dropped is None
    one = bars("2026-08-24 17:45", 1)
    out, dropped, _ = U.drop_open_final_bar(one, observed_utc=pd.Timestamp("2026-08-24 17:45:10"))
    assert dropped == pd.Timestamp("2026-08-24 17:45") and len(out) == 0


def test_5_the_rule_never_changes_the_index_convention():
    """tz-naive in, tz-naive out — on both branches."""
    df = bars("2026-08-24 17:40", 6)
    assert pd.DatetimeIndex(df.index).tz is None
    for obs in ("2026-08-24 17:45:30", "2026-08-24 17:46:00"):
        out, _, _ = U.drop_open_final_bar(df, observed_utc=pd.Timestamp(obs))
        assert pd.DatetimeIndex(out.index).tz is None
        assert list(out.columns) == COLS


def test_5b_an_aware_observation_is_converted_not_assumed():
    """A caller handing an aware instant must not have it read as naive local time — that is
    the thirteen-hour class of error this repo has already paid for once."""
    df = bars("2026-08-24 17:40", 6)
    aware = pd.Timestamp("2026-08-24 13:45:30", tz="America/New_York")   # = 17:45:30 UTC
    _, dropped, _ = U.drop_open_final_bar(df, observed_utc=aware)
    assert dropped == pd.Timestamp("2026-08-24 17:45")
    aware_after = pd.Timestamp("2026-08-24 13:46:00", tz="America/New_York")
    _, dropped2, _ = U.drop_open_final_bar(df, observed_utc=aware_after)
    assert dropped2 is None


def test_the_clock_is_stamped_BEFORE_the_request_goes_out():
    """Not fussiness. The snapshot IBKR answers with is at or after the moment we asked, so
    stamping afterwards would let a bar that closed DURING the round trip look complete while
    the row we hold for it is still the partial one. Parsed, not grepped."""
    import ast

    tree = ast.parse(Path(U.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_fetch_contfuture")
    stmts = fn.body
    def _pos(pred):
        return next(i for i, s in enumerate(stmts) if pred(ast.dump(s)))
    i_stamp = _pos(lambda d: "requested_at" in d and "Assign" in d)
    i_req = _pos(lambda d: "reqHistoricalData" in d)
    assert i_stamp < i_req, "requested_at is stamped after the request — see B-5R-H"


# ══════════════════════════════════════════════════════════════════════════════
# 3, 8 — the real append path, end to end, on tmp parquets
# ══════════════════════════════════════════════════════════════════════════════

class _FakeIB:
    """Enough ib_insync for `main()`. Records nothing about orders because it has none."""

    def __init__(self, feed):
        self._feed = feed
        self.connected = False
        self.orders_placed = 0

    def connect(self, host, port, clientId):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def sleep(self, _s):
        pass

    def qualifyContracts(self, contract):
        contract.localSymbol = f"{contract.symbol}U6"
        return [contract]

    def reqHistoricalData(self, contract, **kw):
        """ib_insync returns a LIST of BarData, not a frame. Mirrored exactly, because
        `_fetch_contfuture` does `if not bars:` and a DataFrame there raises "truth value is
        ambiguous" — a fake that returns the wrong shape tests a code path production never
        takes."""
        df = self._feed[contract.symbol]
        return [types.SimpleNamespace(date=ts, **{c: float(row[c]) for c in COLS})
                for ts, row in df.iterrows()]


def _install_fake_ibkr(monkeypatch, feed):
    """Inject an `ib_insync` whose bars come from `feed`, keyed by IBKR symbol."""
    mod = types.ModuleType("ib_insync")

    class ContFuture:
        def __init__(self, symbol, exchange=None):
            self.symbol = symbol
            self.exchange = exchange
            self.localSymbol = ""
            self.lastTradeDateOrContractMonth = ""

    def _df(bars_obj):
        if bars_obj is None or len(bars_obj) == 0:
            return None
        return pd.DataFrame([{"date": b.date, **{c: getattr(b, c) for c in COLS}}
                             for b in bars_obj])

    ib = _FakeIB(feed)
    mod.IB = lambda: ib
    mod.ContFuture = ContFuture
    mod.util = types.SimpleNamespace(df=_df)
    monkeypatch.setitem(sys.modules, "ib_insync", mod)
    return ib


def _stage(tmp_path: Path, stored: pd.DataFrame, name="MES") -> Path:
    """Write a tmp parquet in the file convention: tz-naive UTC, five float columns."""
    d = tmp_path / "cache"
    d.mkdir(exist_ok=True)
    from futures.basket import data_filename, BASKET
    p = d / data_filename(BASKET[name])
    stored.to_parquet(p)
    return p


def _run_main(monkeypatch, tmp_path, argv):
    monkeypatch.setattr(sys, "argv", ["update_ibkr_daily"] + argv)
    try:
        U.main()
        return 0
    except SystemExit as e:
        return int(e.code or 0)


@pytest.fixture
def offsets(tmp_path):
    p = tmp_path / "_splice_offsets.json"
    p.write_text(json.dumps({"MES": {"offset": 0.0, "contract": "MESU6"}}), encoding="utf-8")
    return p


def test_3_repair_boundary_repairs_the_previous_bar_and_appends_only_closed_ones(
        monkeypatch, tmp_path, offsets):
    """The two behaviours together, which is the only way they matter.

    Stored history ends on a PARTIAL 17:45 (low too high, volume too small — the signature a
    partial bar has). The fetch covers it plus newer bars and stops inside 17:50.
    """
    stored = bars("2026-08-24 16:00", 106)                    # ends 17:45
    _b = pd.Timestamp("2026-08-24 17:45")
    stored.loc[_b, "low"] = stored.loc[_b, "low"] + 0.75    # partial: low had not yet fallen
    stored.loc[_b, "high"] = stored.loc[_b, "high"] - 0.25  # nor had the high risen
    stored.loc[_b, "volume"] = 3.0                          # nor the volume grown
    path = _stage(tmp_path, stored)

    feed = {"MES": bars("2026-08-24 16:00", 111)}             # 16:00 .. 17:50
    _install_fake_ibkr(monkeypatch, feed)
    # freeze the clock inside 17:50 so the final fetched bar is open
    class _FrozenDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 8, 24, 17, 50, 20, tzinfo=tz)
    monkeypatch.setattr(U._dt, "datetime", _FrozenDT)

    rc = _run_main(monkeypatch, tmp_path, [
        "--symbols", "MES", "--data-dir", str(path.parent),
        "--nkd-parquet", str(tmp_path / "nope.parquet"),
        "--splice-offsets", str(offsets), "--repair-boundary"])
    assert rc == 0

    after = pd.read_parquet(path)
    idx = pd.DatetimeIndex(after.index)
    # the previous boundary bar was REPAIRED
    row = after.loc[pd.Timestamp("2026-08-24 17:45")]
    assert row["volume"] == feed["MES"].loc[pd.Timestamp("2026-08-24 17:45"), "volume"]
    assert row["low"] == feed["MES"].loc[pd.Timestamp("2026-08-24 17:45"), "low"]
    # only CLOSED newer bars were appended — 17:50 was still open and is absent
    assert idx[-1] == pd.Timestamp("2026-08-24 17:49"), idx[-1]
    assert pd.Timestamp("2026-08-24 17:50") not in idx


def test_8_a_repair_run_no_longer_leaves_a_fresh_partial_tail(monkeypatch, tmp_path, offsets):
    """The Stage 5Q-7 regression, stated as a test.

    On 2026-08-24 the approved repair fixed the 13:45 bars and the SAME run left new partial
    bars at 20:20 and 20:21. Re-probing reported `repairable_dry_run` instead of
    `nothing_to_repair`. After 5R-0 the file's final bar must be one the feed agrees with.
    """
    stored = bars("2026-08-24 16:00", 106)
    stored.loc[pd.Timestamp("2026-08-24 17:45"), "volume"] = 3.0     # partial
    path = _stage(tmp_path, stored)
    feed = {"MES": bars("2026-08-24 16:00", 111)}
    _install_fake_ibkr(monkeypatch, feed)

    class _FrozenDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 8, 24, 17, 50, 20, tzinfo=tz)
    monkeypatch.setattr(U._dt, "datetime", _FrozenDT)

    assert _run_main(monkeypatch, tmp_path, [
        "--symbols", "MES", "--data-dir", str(path.parent),
        "--nkd-parquet", str(tmp_path / "nope.parquet"),
        "--splice-offsets", str(offsets), "--repair-boundary"]) == 0

    after = pd.read_parquet(path)
    last = pd.DatetimeIndex(after.index)[-1]
    # every stored bar the feed also has must MATCH it — no partial tail left behind
    shared = pd.DatetimeIndex(after.index).intersection(feed["MES"].index)
    assert len(shared) > 100
    for col in COLS:
        a = after.loc[shared, col].astype("float64")
        b = feed["MES"].loc[shared, col].astype("float64")
        assert (a - b).abs().max() < 1e-9, col
    assert last == pd.Timestamp("2026-08-24 17:49")


def test_5c_the_written_parquet_stays_tz_naive_with_the_same_columns(
        monkeypatch, tmp_path, offsets):
    stored = bars("2026-08-24 16:00", 106)
    path = _stage(tmp_path, stored)
    before_cols = list(pd.read_parquet(path).columns)
    assert pd.DatetimeIndex(pd.read_parquet(path).index).tz is None

    _install_fake_ibkr(monkeypatch, {"MES": bars("2026-08-24 16:00", 111)})

    class _FrozenDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 8, 24, 17, 50, 20, tzinfo=tz)
    monkeypatch.setattr(U._dt, "datetime", _FrozenDT)

    assert _run_main(monkeypatch, tmp_path, [
        "--symbols", "MES", "--data-dir", str(path.parent),
        "--nkd-parquet", str(tmp_path / "nope.parquet"),
        "--splice-offsets", str(offsets), "--repair-boundary"]) == 0

    after = pd.read_parquet(path)
    assert pd.DatetimeIndex(after.index).tz is None, "the storage convention was rewritten"
    assert list(after.columns) == before_cols


def test_a_fetch_whose_last_bar_has_closed_appends_it(monkeypatch, tmp_path, offsets):
    """The other half of test 2, through the real append rather than the pure function."""
    stored = bars("2026-08-24 16:00", 106)
    path = _stage(tmp_path, stored)
    _install_fake_ibkr(monkeypatch, {"MES": bars("2026-08-24 16:00", 111)})

    class _FrozenDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt.datetime(2026, 8, 24, 17, 51, 0, tzinfo=tz)   # 17:50 has CLOSED
    monkeypatch.setattr(U._dt, "datetime", _FrozenDT)

    assert _run_main(monkeypatch, tmp_path, [
        "--symbols", "MES", "--data-dir", str(path.parent),
        "--nkd-parquet", str(tmp_path / "nope.parquet"),
        "--splice-offsets", str(offsets)]) == 0
    idx = pd.DatetimeIndex(pd.read_parquet(path).index)
    assert idx[-1] == pd.Timestamp("2026-08-24 17:50"), idx[-1]


# ══════════════════════════════════════════════════════════════════════════════
# 6, 7 — the guards and the identity this stage must not disturb
# ══════════════════════════════════════════════════════════════════════════════

def test_6_a_missing_required_frozen_column_still_refuses():
    frozen = bars("2026-08-24 16:00", 5)
    frozen.index = frozen.index.tz_localize("UTC").tz_convert("America/New_York")
    live = bars("2026-08-24 16:00", 5).drop(columns=["volume"])
    with pytest.raises(src.LiveSourceRefused) as e:
        src.project_to_frozen_columns("MES", live, frozen)
    assert e.value.code == src.MISSING_REQUIRED_COLUMNS, e.value.code


def test_6b_extra_provider_columns_are_still_projected_away_not_refused():
    frozen = bars("2026-08-24 16:00", 5)
    frozen.index = frozen.index.tz_localize("UTC").tz_convert("America/New_York")
    live = bars("2026-08-24 16:00", 5)
    live["average"] = 1.0
    live["barcount"] = 2.0
    out, dropped = src.project_to_frozen_columns("MES", live, frozen)
    assert sorted(dropped) == ["average", "barcount"]
    assert list(out.columns) == list(frozen.columns)


def test_7_nkd_identity_is_untouched_by_this_stage():
    """History fetch NKD, orders MNK, and the parquet job table still says so."""
    assert src.history_symbol("MNKD") == "NKD"
    assert ibkr_symbol_and_exchange("MNKD")[0] == "MNK"
    jobs = {j["name"]: j["ibkr_symbol"] for j in U._build_jobs(Path("."), Path("."))}
    assert jobs["MNKD"] == "NKD"
    assert U.history_ibkr_symbol("MNKD") == "NKD"
    from global_index import specs as gi_specs
    assert gi_specs.SPECS["MNKD"].point_value == 0.5


#: Content-hash fields, pinned to a constant so the STRATEGY half can be compared on its own.
#: They are the three that move whenever a file's bytes move.
_CONTENT_FIELDS = ("data_source_identity", "spy_short_source_identity", "regime_csv_identity")


def test_7b_the_5q9_strategy_identity_is_unchanged_by_this_stage():
    """5R-0 touches the fetch tail, not the route's rules. If the STRATEGY half moved here,
    something reached further than it was meant to.

    The first version of this test pinned the FULL `sleeve_identity` hash, and it went red the
    moment Stage 5R-1 appended bars — correctly, because `data_source_identity` is a sha256 of
    the parquet and the whole point of it being in the hash is that it moves when the file
    does. A full-hash pin therefore expires on every trading day, which is a test with a
    built-in expiry date rather than a check.

    So the content-hash fields are pinned to a constant and what remains is the part this
    stage must not touch: the rules, the caps, the fill law, the tradable identity, the sizing
    basis. A strategy change still reds this; a daily append no longer does.
    """
    from global_index import route_params as rp
    from global_index import track1_params as tp

    paths = R.default_data_paths()
    kw = dict(regime_csv="spy_daily_live.csv", fill_law=tp.LIVE_FILL_LAW)
    expected = {
        ("roska4_swing", "MES"): "sha256:8ea91bb2f435cd743cf0175a3a02c91b53e6a8b34010ea76700d5a05d625b0f1",
        ("global_nkd", "MNKD"): "sha256:92da1d8504a598dc3ea572165433745ab21238b8d277d98fba68069f6128150c",
        ("roska4_calm", "MNQ"): "sha256:a0baf8d7a57b97e036f21e2407112f0f0412e95d94f4db8d27a5da5dd0d30318",
        ("roska4_stress", "MNQ"): "sha256:26437f4770c82aea8af53fafa65ec8a74aeaa25e42d9091dc01fbb7f20867fd9",
    }
    for (sleeve, inst), h in expected.items():
        cfg = tp.sleeve_config(sleeve, inst, data_path=paths[inst], **kw)
        pinned = {**cfg, **{f: "PINNED" for f in _CONTENT_FIELDS}}
        assert rp.params_hash(pinned) == h, sleeve


def test_7c_the_data_pin_still_reaches_the_hash():
    """The other half, so pinning the content fields above cannot quietly turn 7b into a test
    that would pass on a route reading the wrong file."""
    from global_index import track1_params as tp

    paths = R.default_data_paths()
    kw = dict(regime_csv="spy_daily_live.csv", fill_law=tp.LIVE_FILL_LAW)
    real = tp.sleeve_identity("roska4_stress", "MNQ", data_path=paths["MNQ"], **kw)[1]
    other = tp.sleeve_identity("roska4_stress", "MNQ", data_path="no/such.parquet", **kw)[1]
    assert real != other


def _frames_that_disagree():
    """A frozen half and a live half that share timestamps and disagree on `close`."""
    frozen = bars("2026-08-24 13:40", 6)
    frozen.index = frozen.index.tz_localize("UTC").tz_convert("America/New_York")
    live = bars("2026-08-24 09:40", 6)          # same wall clock in naive ET
    live["close"] = live["close"] + 7.0
    return frozen, live


def test_the_overlap_guard_still_refuses_a_disagreement():
    """Behavioural, so a mutation that neuters the guard has a test to turn red. The AST check
    below pins that it has no tolerance; this one pins that it fires."""
    frozen, live = _frames_that_disagree()
    provider = src.FrameBarProvider({"MES": live})
    with pytest.raises(src.LiveSourceRefused) as e:
        src.live_frame("MES", frozen=frozen, provider=provider,
                       through=pd.Timestamp("2026-08-24 09:46"))
    assert e.value.code == "overlap_disagreement", e.value.code


def test_the_overlap_guard_was_not_weakened():
    """Its refusal has no tolerance and compares open/high/low/close. Parsed, not grepped —
    a docstring mentioning a number must not be able to pass or fail this."""
    import ast

    tree = ast.parse(Path(src.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_refuse_overlap_disagreement")
    consts = {n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, float)}
    assert consts == {1e-6}, consts
    cols = [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)
            and n.value in ("open", "high", "low", "close")]
    assert set(cols) == {"open", "high", "low", "close"}


# ══════════════════════════════════════════════════════════════════════════════
# 9 — nothing real moved
# ══════════════════════════════════════════════════════════════════════════════

def test_9_no_real_data_file_changed_during_this_suite():
    now = {k: hashlib.sha256(Path(v).read_bytes()).hexdigest()
           for k, v in REAL_FILES.items() if Path(v).exists()}
    assert now == REAL_FINGERPRINT


def test_9b_no_confirmation_or_order_state_appeared():
    assert not Path("global_index/track1_go_live_confirmation.json").exists()
    import os
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "")


def test_9c_the_updater_still_cannot_place_an_order():
    """It has no order path at all, and this is the file the pre-flight runs unattended."""
    srctext = Path(U.__file__).read_text(encoding="utf-8")
    for token in ("placeOrder", "MarketOrder", "LimitOrder", "--allow-orders",
                  "TRACK1_ORDERS_APPROVED"):
        assert token not in srctext, token
