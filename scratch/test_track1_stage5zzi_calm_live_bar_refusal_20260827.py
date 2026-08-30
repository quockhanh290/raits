"""Stage 5ZZI — why Calm refused this morning, and why nobody could tell from the record.

Two separate things, and the tests keep them separate because the fixes are not the same fix.

**The refusal itself was correct.** Both Calm phases asked for bars they could causally have
had, the provider offered none, and the gate refused. The first four tests are the ones the
stage asked for by name, and they prove the rule is satisfiable rather than impossible:

    DECIDE asks only for bars it can causally have
    OBSERVE asks only for bars it can causally have
    missing provider bars still refuse
    available correct bars pass

**The record was not correct.** Every zero-row fetch recorded `provider_error: null`, which
reads as *"there were simply no bars"* — while the gateway was answering each request with
error 162, *Historical Market Data Service error message: Trading TWS session is connected from
a different IP address*. `IBKRBroker._fetch_raw` returns an empty frame both when the feed says
nothing and when the feed refuses, so the two arrive identical and the difference is gone
before anything can write it down. The rest of the tests are about that.

Nothing here connects to a broker, and nothing here writes to the runtime tree.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import track1_data_observation as obs        # noqa: E402
from global_index import track1_intraday as intra              # noqa: E402
from global_index import track1_live_source as src             # noqa: E402

ET = "America/New_York"
SLEEVE = "roska4_calm"
DAY = pd.Timestamp("2026-08-27")
PRIOR = pd.Timestamp("2026-08-26")

#: exactly what the two live slots wrote this morning, copied from the runtime rows rather
#: than retyped from memory of them.
RECORDED = {
    "DECIDE": ("09:32", ["missing_session", "stale", "partial_coverage"]),
    "OBSERVE": ("10:02", ["missing_session", "entry_quote_absent", "stale",
                          "partial_coverage"]),
}


# ── frames, built here rather than fetched ──────────────────────────────────────────────
def _bars(*spans) -> pd.DataFrame:
    """1-minute bars over the given (start, end) wall-clock spans. Naive ET: that is the
    clock a provider delivers on, and `on_frozen_clock` refuses a tz-aware one on purpose."""
    idx = pd.DatetimeIndex([])
    for a, b in spans:
        idx = idx.append(pd.date_range(a, b, freq="1min"))
    return pd.DataFrame({"open": 6000.0, "high": 6001.0, "low": 5999.0,
                         "close": 6000.0, "volume": 100}, index=idx)


def _today_through(hhmm: str) -> pd.DataFrame:
    """Yesterday's close and today up to `hhmm` — the two days the provider asks for.

    The frozen parquet stops at the 13:45 ET append boundary, so yesterday's 13:45-16:00 is
    not in history either; it arrives on the same fetch. A stub that offered only today would
    leave `partial_coverage` standing on YESTERDAY, and that would be the stub's shape being
    tested rather than the rule's.
    """
    return _bars((f"{PRIOR.date()} 13:45", f"{PRIOR.date()} 16:00"),
                 (f"{DAY.date()} 09:30", f"{DAY.date()} {hhmm}"))


class SilentProvider:
    """The gateway's behaviour this morning: asked, answered nothing, said nothing."""
    name = "silent"
    last_error = ""

    def fetch_session_bars(self, inst, *, through):
        return None


class AnsweringProvider:
    name = "answering"
    last_error = ""

    def __init__(self, frame):
        self.frame = frame

    def fetch_session_bars(self, inst, *, through):
        return self.frame


def _frozen():
    """A frozen half that ends where the real one ends: yesterday 13:44, on the ET clock.

    The zone matters and is not decoration. `on_frozen_clock` takes its target from THIS
    frame, so a naive stub here would be testing a conversion the production parquet never
    performs — the real frame's last stamp reads `2026-08-26 13:44:00-04:00`.
    """
    df = _bars((f"{PRIOR.date()} 09:30", f"{PRIOR.date()} 13:44"))
    df.index = df.index.tz_localize(ET)
    return df


def _verdict(provider, phase: str, hhmm: str):
    from global_index import run_live_day_track1 as rl
    now = pd.Timestamp(f"{DAY.date()} {hhmm}", tz=ET)
    joined = src.live_frame("MES", frozen=_frozen(), provider=provider, through=now)
    req = intra.requirement_for(SLEEVE, phase)
    assert req is not None, f"{phase} declares no requirement"
    return joined, req, intra.validate(
        SLEEVE, rl._resample(joined.frame, SLEEVE, req), now_et=now,
        session_day=DAY, requirement=req, entry_quote_index=joined.frame.index)


# ── the four the stage named ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("phase,hhmm,last_needed", [
    ("DECIDE", "09:32", "09:30"),
    ("OBSERVE", "10:02", "10:00"),
])
def test_phase_asks_only_for_bars_it_can_causally_have(phase, hhmm, last_needed):
    """The newest bar the phase requires must have CLOSED before the phase runs.

    A 1-minute bar stamped 09:30 closes at 09:31, so a phase firing at 09:32 may ask for it.
    Asking for the bar stamped at its own instant is the failure this pins: that bar is still
    forming, and a decision on a price nobody has quoted yet is the whole reason this route
    has a gate at all.
    """
    req = intra.requirement_for(SLEEVE, phase)
    fires = pd.Timestamp(f"{DAY.date()} {hhmm}")
    newest = pd.Timestamp(f"{DAY.date()} {req.today_to}")
    closes = newest + pd.Timedelta(minutes=req.bar_minutes)

    assert req.today_to == last_needed
    assert closes <= fires, (
        f"{phase} fires at {hhmm} and needs the {req.today_to} bar, which does not close "
        f"until {closes.time()} — it would be deciding on a price nobody has quoted")
    if req.required_entry_quote_time:
        quote = pd.Timestamp(f"{DAY.date()} {req.required_entry_quote_time}")
        assert quote + pd.Timedelta(minutes=1) <= fires, (
            "the entry quote bar has not closed by the time the phase asks for it")


def test_missing_provider_bars_still_refuse():
    """The morning, reproduced. Same codes, in the same set, from the same code."""
    for phase, (hhmm, codes) in RECORDED.items():
        joined, _req, v = _verdict(SilentProvider(), phase, hhmm)
        assert joined.provider_rows == 0
        assert v.allow is False
        assert sorted(v.codes) == sorted(codes), (
            f"{phase}: local {sorted(v.codes)} != recorded {sorted(codes)}")


def test_available_correct_bars_pass():
    """And the same rule ALLOWS when the bars are there — which is what makes the refusal a
    statement about the feed rather than about the requirement."""
    for phase, hhmm, last in (("DECIDE", "09:32", "09:31"), ("OBSERVE", "10:02", "10:01")):
        _joined, _req, v = _verdict(AnsweringProvider(_today_through(last)), phase, hhmm)
        assert v.allow is True, f"{phase} refused with bars present: {list(v.codes)}"
        assert list(v.codes) == []


def test_the_refusal_is_not_the_stale_daily_file():
    """`freshness_refused` is not among the recorded reasons, and the codes that ARE there
    are all about intraday bars. Worth pinning: the daily SPY file WAS stale earlier in the
    week, it was repaired before this window, and the tempting story is the one already told."""
    for _phase, (_hhmm, codes) in RECORDED.items():
        assert "freshness_refused" not in codes
        assert set(codes) <= {"missing_session", "stale", "partial_coverage",
                              "entry_quote_absent"}


# ── the evidence half ───────────────────────────────────────────────────────────────────
class _Event:
    """The shape ib_insync's `errorEvent` presents: `+=`, `-=`, and callable."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self

    def __isub__(self, fn):
        self.handlers.remove(fn)
        return self

    def emit(self, *a):
        for fn in list(self.handlers):
            fn(*a)


class _IB:
    def __init__(self):
        self.errorEvent = _Event()


class _RefusingBroker:
    """What the gateway was: it emits a named error and then returns no bars.

    This is the whole defect in four lines. ib_insync does not raise, `reqHistoricalData`
    returns an empty list, and `_fetch_raw` turns that into an empty DataFrame — the identical
    value a genuinely quiet market produces.
    """

    def __init__(self, code=162, msg="Historical Market Data Service error message: Trading "
                                     "TWS session is connected from a different IP address"):
        self._ib = _IB()
        self.code, self.msg = code, msg

    def fetch_bars(self, sym, through):
        self._ib.errorEvent.emit(7, self.code, self.msg, "")
        return pd.DataFrame()


class _QuietBroker:
    """A feed with nothing to say and nothing wrong: no error, no bars."""

    def __init__(self):
        self._ib = _IB()

    def fetch_bars(self, sym, through):
        return pd.DataFrame()


def test_a_named_refusal_reaches_the_provider():
    p = src.IBKRBarProvider(broker=_RefusingBroker())
    assert p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32")) is None
    assert "162" in p.last_error
    assert "different IP address" in p.last_error


def test_a_quiet_feed_is_not_reported_as_a_refusal():
    """The point of the whole change: the two must not print the same."""
    p = src.IBKRBarProvider(broker=_QuietBroker())
    assert p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32")) is None
    assert p.last_error == ""


def test_the_message_reaches_the_joined_frame_and_the_row():
    """Provider -> JoinedFrame -> as_dict -> the data observation row.

    Every hop is asserted rather than the endpoints only. A field added to the dataclass and
    left out of `as_dict` would still be a field that never reaches anyone, which is exactly
    how it was written the first time.
    """
    p = src.IBKRBarProvider(broker=_RefusingBroker())
    joined = src.live_frame("MES", frozen=_frozen(), provider=p,
                            through=pd.Timestamp(f"{DAY.date()} 09:32", tz=ET))
    assert joined.provider_rows == 0
    assert "162" in joined.provider_error
    assert "162" in joined.as_dict()["provider_error"]

    row = obs.instrument_row(joined)
    assert row["live_rows_fetched"] == 0
    assert "162" in (row["provider_error"] or "")


def test_the_row_says_none_when_the_feed_said_nothing():
    p = src.IBKRBarProvider(broker=_QuietBroker())
    joined = src.live_frame("MES", frozen=_frozen(), provider=p,
                            through=pd.Timestamp(f"{DAY.date()} 09:32", tz=ET))
    row = obs.instrument_row(joined)
    assert row["live_rows_fetched"] == 0
    assert row["provider_error"] is None, (
        "an empty string in the row would print as a value and read as 'the feed answered, "
        "with nothing' — the absent case has to be absent")


def test_todays_rows_would_now_be_distinguishable():
    """The two conditions side by side, which is the only comparison that matters: this
    morning both of these produced byte-identical rows."""
    refused = obs.instrument_row(src.live_frame(
        "MES", frozen=_frozen(), provider=src.IBKRBarProvider(broker=_RefusingBroker()),
        through=pd.Timestamp(f"{DAY.date()} 09:32", tz=ET)))
    quiet = obs.instrument_row(src.live_frame(
        "MES", frozen=_frozen(), provider=src.IBKRBarProvider(broker=_QuietBroker()),
        through=pd.Timestamp(f"{DAY.date()} 09:32", tz=ET)))

    assert refused["live_rows_fetched"] == quiet["live_rows_fetched"] == 0
    assert refused["splice_result"] == quiet["splice_result"]
    assert refused["provider_error"] != quiet["provider_error"], (
        "the only field that separates a refused feed from a quiet one")


def test_an_unrelated_error_is_not_collected():
    """Not every IBKR message is about the data service. A row that collected all of them
    would fill up with connection notices and stop being read."""
    b = _RefusingBroker(code=2104, msg="Market data farm connection is OK:usfarm")
    p = src.IBKRBarProvider(broker=b)
    p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32"))
    assert p.last_error == ""


def test_a_repeated_message_is_recorded_once():
    class _Chatty(_RefusingBroker):
        def fetch_bars(self, sym, through):
            for _ in range(8):
                self._ib.errorEvent.emit(7, self.code, self.msg, "")
            return pd.DataFrame()

    p = src.IBKRBarProvider(broker=_Chatty())
    p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32"))
    assert p.last_error.count("162") == 1


def test_the_handler_does_not_outlive_the_fetch():
    """A listener added per fetch and never removed is 25 listeners a day, each one appending
    to a provider that has already returned."""
    b = _RefusingBroker()
    p = src.IBKRBarProvider(broker=b)
    p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32"))
    assert b._ib.errorEvent.handlers == []


def test_the_handler_is_removed_even_when_the_fetch_raises():
    class _Exploding(_RefusingBroker):
        def fetch_bars(self, sym, through):
            raise TimeoutError("gateway went away")

    b = _Exploding()
    p = src.IBKRBarProvider(broker=b)
    with pytest.raises(TimeoutError):
        p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32"))
    assert b._ib.errorEvent.handlers == []


def test_the_previous_fetchs_message_does_not_carry_over():
    """`last_error` means THIS fetch. A message left standing from the last one would make a
    recovered feed keep reporting the outage that ended."""
    p = src.IBKRBarProvider(broker=_RefusingBroker())
    p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32"))
    assert "162" in p.last_error
    p._broker = _QuietBroker()
    p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:33"))
    assert p.last_error == ""


def test_a_broker_with_no_session_behaves_exactly_as_before():
    """Fail-soft. The listener is a diagnostic, and a diagnostic that can break a fetch is
    worse than no diagnostic — every test broker in this repo lacks `_ib`."""
    class _Plain:
        def fetch_bars(self, sym, through):
            return _today_through("09:31")

    p = src.IBKRBarProvider(broker=_Plain())
    got = p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32"))
    assert got is not None and len(got) > 0
    assert p.last_error == ""


def test_an_event_that_refuses_a_handler_does_not_break_the_fetch():
    class _Hostile:
        def __init__(self):
            self._ib = type("X", (), {"errorEvent": property(lambda s: (_ for _ in ()).throw(
                RuntimeError("no")))})()

        def fetch_bars(self, sym, through):
            return _today_through("09:31")

    p = src.IBKRBarProvider(broker=_Hostile())
    got = p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} 09:32"))
    assert got is not None and len(got) > 0


def test_the_bar_the_gate_wants_is_the_bar_the_provider_was_asked_for():
    """A refusal blamed on the feed has to be a refusal the feed was actually given a chance
    to prevent. `through` is the phase's own instant, so the fetch covers the required span."""
    seen = []

    class _Recording:
        def __init__(self):
            self._ib = _IB()

        def fetch_bars(self, sym, through):
            seen.append(pd.Timestamp(through))
            return pd.DataFrame()

    p = src.IBKRBarProvider(broker=_Recording())
    for phase, (hhmm, _codes) in RECORDED.items():
        seen.clear()
        p.fetch_session_bars("MES", through=pd.Timestamp(f"{DAY.date()} {hhmm}"))
        req = intra.requirement_for(SLEEVE, phase)
        needed = pd.Timestamp(f"{DAY.date()} {req.today_to}")
        asked = seen[0]
        if asked.tzinfo is not None:
            asked = asked.tz_convert(ET).tz_localize(None)
        assert asked >= needed, (
            f"{phase}: the fetch stopped at {asked} but the gate needs {needed}")


def test_the_shape_of_the_defect_is_pinned_in_the_broker():
    """The reason this had to be fixed at the provider and not in `_fetch_raw`: that function
    returns the same empty frame on both paths, and the only place the difference still exists
    is the event, which fires before either return."""
    text = (ROOT / "global_index" / "ibkr_broker.py").read_text(encoding="utf-8")
    assert "return pd.DataFrame()" in text
    assert text.count("return pd.DataFrame()") >= 2, (
        "if _fetch_raw grows a distinct return for the refusal case, this stage's workaround "
        "can be retired — revisit rather than leaving both")
