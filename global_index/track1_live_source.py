"""global_index/track1_live_source.py — where Track 1's live bars come from. NEW FILE.

Stage 4C. **No connection is opened here in this stage.** This module is the boundary between
"a broker hands us bars" and "a sleeve reads a frame", and it exists so that boundary has
exactly one implementation instead of four.

The two halves, and the step between them
------------------------------------------
Track 1's history is a parquet file. Today's session is whatever a provider hands over. They
do not arrive on the same clock, and that is not an accident of this repo — it is the contract
on both sides:

    the frozen half   parquet timestamps are UTC, read as UTC and converted to New York; for
                      the Nikkei sleeve they are converted once more to Tokyo, because that is
                      the session the instrument trades in.
    the live half     the broker path returns bars already converted to New York and then
                      STRIPPED of the zone — naive wall-clock ET. That is what
                      `IBKRBroker.fetch_bars` produces today, and it is the contract this
                      module declares its providers must meet.

So a conversion has to happen before the two can be joined, and **that conversion is the whole
danger**. Getting it wrong is not hypothetical here: live Nikkei bars on the New York clock
were once joined onto Tokyo-clocked history, thirteen hours apart in summer, and 1,050 of 1,590
of them landed on labels history already owned and overwrote settled prices by roughly 900 to
1,000 points. Nothing raised.

The two ways to convert are one keystroke apart and mean opposite things:

    tz_localize("Asia/Tokyo")                       WRONG — asserts the ET wall clock was
                                                    already Tokyo time. This is the bug.
    tz_localize("America/New_York")
        .tz_convert("Asia/Tokyo")                   RIGHT — says when the bar happened, then
                                                    re-reads that instant on Tokyo's clock.

`on_frozen_clock` below does the second, and it takes its target **from the frozen frame
itself** rather than from a table that could disagree with the file. There is a test that does
it the wrong way and requires the join to be refused.

Why the guard is not optional here
-----------------------------------
`track1_live_frame.splice` refuses a clock mismatch rather than fixing one. That is deliberate:
a converter inside the join would make a wrongly-clocked frame look plausible, which is how the
Nikkei corruption passed every check that existed. So conversion is explicit and lives here,
and the join stays suspicious of whatever it is handed. Every path in this module ends in that
join — there is no route from a provider to a sleeve that skips it.

What these checks do NOT cover
-------------------------------
Two checks guard the seam: no bar may be stamped after the instant it was fetched at, and where
the live half and history share a timestamp the prices must agree. Between them they catch a
clock error in either direction — but only while the live half is SESSION-SIZED, which is what
a live fetch returns. A shift smaller than the live half's own span leaves most bars before the
fetch instant and past the end of history, where neither check can see them. A whole-zone error
is thirteen or fourteen hours and a session is a few, so the realistic case is covered; a caller
that starts handing over multi-day live halves is outside what has been proven, and there is a
test that says so by name rather than leaving it to be discovered.

And the thirteen is not a constant. Japan does not observe summer time and the United States
does, so the same mistake is worth thirteen hours from March to November and fourteen the rest
of the year. Nothing here hard-codes it; both sides of that boundary are pinned in the tests.

What this module does NOT do
-----------------------------
It does not connect, and nothing here has ever been executed against a broker. `IBKRBarProvider`
is written against the same API the legacy path uses so that the wiring is real rather than
sketched, but it is never instantiated by Track 1 code in this stage, and the tests run entirely
on `FrameBarProvider`, which serves frames a caller already has.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from global_index import specs as gi_specs
from global_index import track1_live_frame as guard

#: The clock a provider must deliver. Naive ET wall time — the same thing
#: `IBKRBroker.fetch_bars` returns after its own UTC handling, so a provider written against
#: the existing broker needs no adapter of its own.
PROVIDER_CLOCK = "America/New_York"

#: What the frozen parquet timestamps mean before any conversion.
PARQUET_CLOCK = "UTC"

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def as_provider_clock(through) -> Any:
    """`through` as the NAIVE ET instant a provider can compare its own index against.

    Providers index on naive ET, and callers hold aware instants, so somebody has to convert.
    Doing it here rather than in each provider is not tidiness: the first version left it to
    the providers and the causal filter blew up comparing a naive index with an aware
    timestamp — and the legacy broker's own `fetch_bars` filters exactly the same way, so the
    real IBKR path would have hit it too, on the first live day, in the dark.
    """
    ts = pd.Timestamp(through)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(PROVIDER_CLOCK).tz_localize(None)
    return ts


#: The two Calm phase names, from the diagnostics module that defines them.
CA_DECIDE_PHASE = "decide"
CA_OBSERVE_PHASE = "observe"


def _new_observer():
    """A detector observer, or a no-op if the diagnostics module cannot be imported.

    Stage 5ZZZ-B. The fallback is the point: this runs on the candidate path, and an import
    error in an observability module must not stop a sleeve finding its entries.
    """
    try:
        from global_index import track1_strategy_diagnostics as SD

        return SD.NormalR4Observer()
    except Exception:                                              # noqa: BLE001
        return None


class LiveSourceRefused(RuntimeError):
    """The live half could not be made joinable. Raised rather than returned, for the same
    reason the join raises: a caller that must remember to check a flag will forget once."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@runtime_checkable
class BarProvider(Protocol):
    """Anything that can hand over today's bars.

    The return is a frame of `REQUIRED_COLUMNS` on a **naive ET** index. Naive is not laziness:
    it is the existing broker's actual output, and pretending otherwise here would hide the
    conversion this module exists to make visible.
    """

    name: str

    def fetch_session_bars(self, inst: str, *, through) -> Any: ...


@dataclass
class FrameBarProvider:
    """A provider that serves frames it was given. Deterministic, offline, no connection.

    This is what every test and the shadow path use. It is production code rather than a test
    fixture on purpose: a fake that lives in the test file proves the test's fake joins
    cleanly, whereas this one is the object the route actually holds.
    """
    frames: Mapping[str, Any]
    name: str = "frames"

    def fetch_session_bars(self, inst: str, *, through) -> Any:
        df = self.frames.get(inst)
        if df is None:
            return None
        idx = pd.DatetimeIndex(df.index)
        if idx.tz is not None:
            raise LiveSourceRefused(
                "provider_clock",
                f"{self.name} returned {inst} on {idx.tz!r}; providers deliver NAIVE ET, "
                f"because that is what the broker path produces and the conversion to the "
                f"frozen frame's clock is this module's job, not the provider's")
        if through is not None:
            df = df[idx <= as_provider_clock(through)]
        return df


class IBKRBarProvider:
    """The real boundary, written against the API the legacy path already uses.

    **Not instantiated by Track 1 in this stage and never executed.** It is here so the route
    has a genuine fetch rather than a placeholder, and so that the day a connection is opened,
    the bars it returns are already obliged to travel the same conversion and the same join as
    everything else.

    It deliberately reuses `IBKRBroker`, rather than opening a second connection of its own:
    one Gateway login is one session, and a module that quietly dialled out on its own would
    be a second client competing with the runner for the same client id.
    """

    name = "ibkr"

    #: IBKR error codes that mean "the historical data service declined", as opposed to "there
    #: are no bars". 162 is the one measured on 2026-08-27: *Historical Market Data Service
    #: error message: Trading TWS session is connected from a different IP address* — emitted
    #: for every request all morning while the route recorded, for each of them, that the
    #: provider had simply offered nothing.
    HISTORICAL_REFUSAL_CODES = frozenset({162, 165, 200, 354, 366, 420, 10197})

    def __init__(self, broker: Any = None, *, bar_duration: str = "2 D"):
        self._broker = broker
        self._bar_duration = bar_duration
        #: What the feed said about the LAST fetch, or "" if it said nothing. Stage 5ZZI.
        #: ib_insync reports these through an event rather than by raising, and
        #: `reqHistoricalData` then returns an empty list — so without this the difference
        #: between a refused request and a quiet market is lost before anyone can record it.
        self.last_error: str = ""

    def _require_broker(self) -> Any:
        if self._broker is None:
            raise LiveSourceRefused(
                "no_broker",
                "IBKRBarProvider was asked for bars without a broker. Track 1 does not open "
                "its own connection: hand it the runner's IBKRBroker, which already owns the "
                "session, the client id and the contract resolution.")
        return self._broker

    def fetch_session_bars(self, inst: str, *, through) -> Any:
        """Naive-ET bars for `inst` through `through`, straight from the broker's own path.

        `IBKRBroker.fetch_bars` already lowercases the columns, sorts the index, converts the
        exchange-local timestamps to New York and drops the zone. Re-implementing any of that
        here would be a second copy of a decision rule, and second copies are what this route
        keeps getting caught by — so it is delegated whole.
        """
        broker = self._require_broker()
        self.last_error = ""
        # Stage 5ZZI. Listen while the request is in flight.
        #
        # Measured on 2026-08-27: every MES and MNQ fetch from 03:05 ET onward returned zero
        # rows and recorded `provider_error: null`, while the gateway was answering each one
        # with error 162 — the historical data service refusing because the account was logged
        # in from another address. `fetch_bars` cannot see it: ib_insync raises nothing, the
        # request returns an empty list, and `if not bars: return pd.DataFrame()` makes a
        # refusal and a quiet market into the same answer.
        #
        # Fail-soft in both directions: a broker with no session, or an event API that will not
        # take a handler, leaves `last_error` empty and the fetch behaves exactly as before.
        _seen: list = []
        _ib = None
        _handler = None
        try:
            _ib = getattr(broker, "_ib", None)
            _has = _ib is not None and hasattr(_ib, "errorEvent")
        except Exception:                                             # noqa: BLE001
            # `hasattr` only swallows AttributeError; a property raising anything else
            # propagates, and a diagnostic that can take the fetch down with it is worse
            # than no diagnostic.
            _has = False
        if _has:
            def _on_error(reqId=None, errorCode=None, errorString="", *rest):
                try:
                    code = int(errorCode)
                except (TypeError, ValueError):
                    return
                if code in self.HISTORICAL_REFUSAL_CODES or "Historical" in str(errorString):
                    _seen.append(f"IBKR {code}: {errorString}")
            try:
                _ib.errorEvent += _on_error
                _handler = _on_error
            except Exception:                                         # noqa: BLE001
                _handler = None
        # Stage 5Q-7. Ask for the symbol the HISTORY was built from, not the runner's name.
        # `IBKRBroker.fetch_bars` resolves whatever it is handed through `_RAITS_TO_IBKR`,
        # which is the ORDER map — so handing it "MNKD" fetched the $0.50 micro MNK while
        # the parquet holds full-size NKD, and 1,155 of 1,186 shared minutes disagreed.
        # See `update_ibkr_daily.history_ibkr_symbol` for why this is not `data_symbol`.
        fetch_as = history_symbol(inst)
        # Naive ET, because that is the clock `IBKRBroker.fetch_bars` compares against when it
        # trims to `through`. Handing it an aware instant raises inside pandas.
        try:
            bars = broker.fetch_bars(fetch_as, as_provider_clock(through))
        finally:
            if _handler is not None:
                try:
                    _ib.errorEvent -= _handler
                except Exception:                                     # noqa: BLE001
                    pass
        # De-duplicated: one refused fetch can emit the same message for several requests, and
        # a row repeating it eight times is a row nobody reads to the end.
        self.last_error = "; ".join(dict.fromkeys(_seen))[:300]
        if bars is None or len(bars) == 0:
            return None
        return bars

    def fetch_session_bars_direct(self, ib: Any, contract: Any, *, through) -> Any:
        """The unmediated call, for the day a caller has an `ib_insync` session and no broker.

        Kept separate and unused by the route so that the ordinary path stays single. It is
        written out rather than described because a fetch that exists only in a docstring is a
        fetch nothing can check.
        """
        import ib_insync as ibi

        bars = ib.reqHistoricalData(
            contract,
            endDateTime=as_provider_clock(through).strftime("%Y%m%d %H:%M:%S"),
            durationStr=self._bar_duration,
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
            timeout=120,
        )
        if not bars:
            return None
        df = ibi.util.df(bars)
        if df is None or df.empty:
            return None
        df = df.set_index("date")
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_convert(PROVIDER_CLOCK).tz_localize(None)
        df.columns = [c.lower() for c in df.columns]
        return df.sort_index()


UNKNOWN_BAR_PROVIDER = "unknown_bar_provider"


def build_bar_provider(kind: str, *, host: str = "127.0.0.1", port: int = 4002,
                       client_id: int = 89, bar_duration: str = "2 D",
                       broker_cls=None):
    """Build the data provider for a live-shadow slot. `(provider, broker)`.

    `none` is the default so a manual run cannot open IBKR by accident. `ibkr` is data-only: it
    wraps the existing broker so bars travel the same `fetch_bars` contract as legacy, while
    orders stay governed by `OrderGate` somewhere else entirely.

    The caller gets the broker back so it can disconnect in a `finally`. Tests pass
    `broker_cls` to exercise the wiring without importing or connecting IBKR.

    **Why it lives here and not in the entry point.** It was written in
    `run_live_day_track1.py`, and that closed the `LIVE_FRAME_ADAPTER_VERIFICATION` gate: the
    rule is that any module which obtains live bars must import
    `global_index/track1_live_frame`, and the entry point did the first without the second. The
    gate was right. Moving the touchpoint into the module that already holds every other live-bar
    primitive — and already imports the guard — makes the structural claim TRUE rather than
    making the detector look away. Every frame this provider yields still reaches a sleeve only
    through `live_frame` -> `guard.splice`.
    """
    if kind == "none":
        return None, None
    if kind != "ibkr":
        raise LiveSourceRefused(UNKNOWN_BAR_PROVIDER,
                                f"unknown bar provider {kind!r}; expected 'none' or 'ibkr'")
    if broker_cls is None:
        from global_index.ibkr_broker import IBKRBroker
        broker_cls = IBKRBroker
    broker = broker_cls(host=host, port=port, client_id=client_id,
                        bar_duration=bar_duration)
    broker.connect()
    return IBKRBarProvider(broker), broker


def _live_sleeves() -> list:
    """The sleeves this source can be asked about, read from the window table.

    Derived rather than listed, so the refusal message cannot name a set the source no longer
    serves — which is exactly what happened before Stage 5M-B, when the message still said
    "the 10:00 and 10:35-12:30 windows" would have been the whole truth and then stopped being
    it the moment a third window existed.
    """
    from global_index import track1_params as tp
    return list(tp.WINDOWS_ET)


def session_tz(inst: str) -> str:
    """The clock the frozen frame for `inst` is carried on.

    Read from the instrument spec, which is where the Nikkei sleeve's Tokyo session is already
    declared, so this cannot drift away from the loader that built the file.
    """
    spec = gi_specs.SPECS.get(inst)
    tz = getattr(spec, "session_tz", None) if spec is not None else None
    return tz or PROVIDER_CLOCK


def history_symbol(inst: str) -> str:
    """The IBKR symbol to ask for when the answer has to line up with `inst`'s parquet.

    An instrument has three names and they are not interchangeable: what this system calls
    it, what its history was fetched under, and what goes on an order. `IBKRBroker.fetch_bars`
    resolves through the ORDER map, which is correct for orders and wrong for bars the moment
    the two differ — and for MNKD they differ on purpose, because the $0.50 micro MNK has
    history only from 2024 Q4 while the backtest runs on full-size NKD from 2018.

    Delegated, not re-derived: the authority is `update_ibkr_daily`, which is the module that
    actually fetched the files. A table here could disagree with the one that wrote them.
    """
    from global_index.update_ibkr_daily import history_ibkr_symbol

    return history_ibkr_symbol(inst)


def frozen_frame(inst: str, path: str | Path) -> Any:
    """The historical half, on the clock the sleeves read it on.

    One implementation, because there were two: the parquet is UTC, `_core.load_parquet`
    converts it to New York, and the Nikkei frame is converted once more to Tokyo by the
    caller that happens to remember. That last step living in a caller is how a frame ends up
    on the wrong clock, so it is done here for every instrument, from the spec.
    """
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise LiveSourceRefused("frozen_columns", f"{inst} parquet is missing {sorted(missing)}")
    idx = pd.to_datetime(df.index, utc=True)
    df = df.set_index(idx).sort_index()
    df.index = df.index.tz_convert(session_tz(inst))
    return df[list(REQUIRED_COLUMNS)]


def on_frozen_clock(inst: str, live: Any, frozen: Any) -> Any:
    """Put naive-ET live bars onto the frozen frame's clock. **The dangerous step.**

    Two rules, both of which exist because of the same incident:

    1. The target is taken from `frozen`, never from a constant here. A table in this file
       could disagree with the file on disk; the frame cannot disagree with itself.
    2. The naive index is LOCALISED to New York first and only then converted. Localising
       straight to the target instead would assert that an ET wall-clock reading was already
       Tokyo time, which is precisely the thirteen-hour error that overwrote 1,050 Nikkei bars.

    A live half that already carries a zone is refused rather than re-interpreted: it means the
    provider broke its contract, and guessing which contract it meant instead is the move that
    turns a loud failure into a silent one.
    """
    if live is None:
        return None
    lidx = pd.DatetimeIndex(live.index)
    if lidx.tz is not None:
        raise LiveSourceRefused(
            "provider_clock",
            f"the live half for {inst} arrived on {lidx.tz!r}; providers deliver naive ET so "
            f"that this conversion is visible and testable rather than assumed")
    target = pd.DatetimeIndex(frozen.index).tz
    if target is None:
        raise LiveSourceRefused(
            "frozen_clock",
            f"the frozen frame for {inst} carries no timezone, so there is nothing to convert "
            f"onto; it was loaded by something other than frozen_frame()")
    out = live.copy()
    out.index = lidx.tz_localize(PROVIDER_CLOCK).tz_convert(target)
    return out


MISSING_REQUIRED_COLUMNS = "missing_required_columns"
NAN_IN_REQUIRED_COLUMNS = "nan_in_required_columns"


def project_to_frozen_columns(inst: str, live: Any, frozen: Any) -> tuple:
    """`(projected, dropped)` — the live half reduced to exactly the frozen frame's columns.

    **This module owns the projection, and `track1_live_frame.splice` stays strict.** That
    split is the whole design and it is worth stating plainly: the guard's rule is "the two
    frames must have IDENTICAL columns", and relaxing it to "extras are fine" would mean a
    future caller that forgot to project could hand it a wider frame and get a wider frame
    back, with provider fields riding downstream into every sleeve. `live_frame` below is the
    only caller of `splice` in this repo, so normalising here loses nothing and keeps the
    guard able to catch a caller that skipped this step.

    Measured 2026-08-24, first live Calm slot: the frozen parquet carries
    `['open','high','low','close','volume']` and the IBKR feed hands back those plus
    `['average','barcount']`. `splice` refused `column_mismatch` and the slot died — correctly,
    because concatenating frames with different columns yields NaN holes. The feed was not
    wrong; nobody had said what to do with the two extra fields.

    The three rules, and why each is the way it is:

        missing a frozen column  REFUSED. Never filled in: a synthesised `volume` of 0 or a
                                 forward-filled `close` is a made-up bar, and every indicator
                                 downstream would treat it as measured. `frozen_frame` already
                                 refuses a parquet missing one, and this is the same rule
                                 applied to the other half of the join.
        extra provider columns   DROPPED, and NAMED in the return and in the joined frame's
                                 record. Not allowlisted: an allowlist of `average`/`barcount`
                                 is a table that drifts the first time IBKR adds a field, and
                                 it would refuse a harmless new column with a message about a
                                 column nobody reads. What matters is that the frozen schema
                                 is complete and carries the frozen columns' own values —
                                 which dropping guarantees. What must NOT happen is the drop
                                 being invisible, so the names travel with the frame.
        NaN in a frozen column   REFUSED. Projection removes the NaN holes a mismatched concat
                                 would CREATE; a NaN the provider actually sent is a different
                                 thing and a worse one, because it is a bar with no price that
                                 would propagate silently through every rolling window.

    Column ORDER comes from `frozen`, not from the live half: `reindex(columns=...)` is what
    makes the two frames identical rather than merely equal as sets, and `splice` compares
    lists.
    """
    if live is None or len(pd.DatetimeIndex(live.index)) == 0:
        return live, ()
    want = list(frozen.columns)
    have = list(live.columns)
    missing = [c for c in want if c not in have]
    if missing:
        raise LiveSourceRefused(
            MISSING_REQUIRED_COLUMNS,
            f"{inst}: the live half is missing {missing} — it has {have} and the frozen half "
            f"needs {want}. Refused rather than filled: a synthesised bar is a bar every "
            f"indicator downstream would treat as measured.")
    dropped = tuple(c for c in have if c not in want)
    out = live.reindex(columns=want)
    bad = [c for c in want if out[c].isna().any()]
    if bad:
        n = int(out[bad].isna().any(axis=1).sum())
        first = pd.DatetimeIndex(out.index)[out[bad].isna().any(axis=1)][0]
        raise LiveSourceRefused(
            NAN_IN_REQUIRED_COLUMNS,
            f"{inst}: {n} live bar(s) carry no value in {bad}; first at {first}. A bar with "
            f"no price is not a quiet bar — it would travel into every rolling window as if "
            f"it had been measured.")
    return out, dropped


@dataclass(frozen=True)
class JoinedFrame:
    inst: str
    frame: Any
    report: Any
    provider: str
    #: how many bars the provider handed over, BEFORE the join saw them. Reported rather than
    #: judged: a provider that offers bars none of which survive is not always wrong — a fetch
    #: taken right after the parquet was appended legitimately offers only bars already stored
    #: — but "offered 399, appended 0" and "offered 0, appended 0" must not print the same,
    #: because one of them is a quiet session and the other is a feed that is not landing.
    provider_rows: int = 0
    #: shared timestamps whose prices were compared against history and agreed
    overlap_checked: int = 0
    #: What the FEED said, when it said anything. Stage 5ZZI. Empty is not "fine": it means the
    #: provider reported nothing, which on a provider that cannot report is the same as not
    #: being asked. `provider_rows == 0` with a message here is a refusal; without one it is a
    #: quiet market, and for three days those two printed identically.
    provider_error: str = ""
    #: provider columns the projection removed before the join, e.g. ('average', 'barcount').
    #: Reported rather than discarded: a NEW column appearing here is how anyone finds out the
    #: feed changed shape, and a drop nobody can see is indistinguishable from a feed that
    #: stopped sending the field.
    dropped_columns: tuple = ()

    @property
    def appended(self) -> int:
        return int(self.report.live_rows_appended)

    @property
    def offered_but_unused(self) -> int:
        return max(0, self.provider_rows - self.appended)

    def as_dict(self) -> dict:
        return {"inst": self.inst, "provider": self.provider, "rows": int(len(self.frame)),
                "provider_rows": self.provider_rows,
                "offered_but_unused": self.offered_but_unused,
                "overlap_checked": self.overlap_checked,
                "provider_error": self.provider_error,
                "dropped_columns": list(self.dropped_columns),
                **self.report.as_dict()}


def _as_instant(through) -> Any:
    """`through` as a real instant. Naive means ET, which is the provider clock."""
    ts = pd.Timestamp(through)
    return ts.tz_localize(PROVIDER_CLOCK) if ts.tzinfo is None else ts


def _refuse_bars_from_the_future(inst: str, aligned: Any, through) -> None:
    """No joined bar may be stamped after the instant it was fetched at.

    This check exists because the guard cannot do it, and MEASURING found the gap rather than
    reasoning about it. The guard defends history from being overwritten: it refuses a live
    bar that lands on a timestamp history already owns. But a mis-converted tail does not
    always land backwards. Convert the Nikkei tail the wrong way — read a Tokyo wall-clock
    reading as if it were New York — and every bar lands THIRTEEN HOURS LATER than it happened,
    in empty space past the end of history. Strictly newer, unique, in order, same columns:
    every rule the join has, satisfied. It appended 399 corrupted bars and reported success.

    A fetch cannot return bars from after the moment it was taken, so the timestamp of the last
    joined bar is checkable against the instant it was asked for, with no tolerance to tune.
    That is what closes the second direction of the same error.
    """
    if aligned is None or len(aligned.index) == 0:
        return
    limit = _as_instant(through)
    last = pd.DatetimeIndex(aligned.index).max()
    if last > limit:
        raise LiveSourceRefused(
            "bars_from_the_future",
            f"{inst}: the live half ends at {last}, after the {limit} it was fetched at. Bars "
            f"cannot arrive from later than the moment they were asked for, so this is a clock "
            f"error, not late data — most likely a naive index localised straight to the "
            f"session zone instead of being localised to {PROVIDER_CLOCK} and converted")


def _refuse_overlap_disagreement(inst: str, aligned: Any, frozen: Any) -> int:
    """Where the live half and history share a timestamp, the prices must match. Returns the
    number of timestamps compared.

    This is the check that speaks directly to the incident. When live Nikkei bars were joined
    onto Tokyo-clocked history on the wrong clock, 1,050 of them landed on labels history
    already owned — and the prices there differed by roughly 900 to 1,000 points. The join
    itself cannot notice: it trims the overlap away and keeps history, which is safe but
    silent, and silence is what let the original error run.

    An overlap is normal and expected — a fetch window reaches back before the last stored bar
    almost every time. What is not normal is an overlap that DISAGREES. Two feeds of the same
    instrument at the same instant either report the same trade or one of them is not the
    instrument, the instant, or the clock it claims to be.

    No tolerance to tune: futures prices are exact decimals in both frames, so anything beyond
    floating-point noise is a real difference.
    """
    if aligned is None or len(aligned.index) == 0:
        return 0
    shared = pd.DatetimeIndex(aligned.index).intersection(pd.DatetimeIndex(frozen.index))
    if len(shared) == 0:
        return 0
    cols = [c for c in ("open", "high", "low", "close") if c in aligned.columns
            and c in frozen.columns]
    for col in cols:
        a = pd.to_numeric(aligned.loc[shared, col], errors="coerce")
        b = pd.to_numeric(frozen.loc[shared, col], errors="coerce")
        diff = (a - b).abs()
        bad = diff[diff > 1e-6]
        if len(bad):
            where = bad.index[0]
            raise LiveSourceRefused(
                "overlap_disagreement",
                f"{inst}: the live half and history disagree on {len(bad)} of {len(shared)} "
                f"shared timestamps in {col!r}; first at {where}, history says "
                f"{float(b.loc[where]):.4f} and the feed says {float(a.loc[where]):.4f}, "
                f"largest gap {float(bad.max()):.4f}. Two readings of the same instrument at "
                f"the same instant cannot differ — this is a clock, a contract or a source "
                f"error, and it is the shape the Nikkei corruption had")
    return int(len(shared))


def live_frame(inst: str, *, frozen: Any, provider: BarProvider, through) -> JoinedFrame:
    """History plus today, for one instrument. **The only way bars reach a Track 1 sleeve.**

    Every branch ends in `track1_live_frame.splice`, including the one where the provider has
    nothing to offer — so there is no path that returns a frame the guard has not seen.

    `through` is required and is not decoration: it is the instant the fetch was taken at, and
    it is the only thing that can catch a tail converted forwards rather than backwards.
    """
    if through is None:
        raise LiveSourceRefused(
            "no_fetch_instant",
            f"live_frame({inst}) needs the instant the bars were fetched at. Without it a "
            f"mis-converted tail landing in the future cannot be told from late data.")
    raw = provider.fetch_session_bars(inst, through=through)
    offered = 0 if raw is None else int(len(raw.index))
    aligned = on_frozen_clock(inst, raw, frozen)
    # Stage 5Q-3. Schema BEFORE prices: the overlap check compares values column by column and
    # cannot compare a column that is not there, so the live half is reduced to the frozen
    # frame's own columns first. This is the step whose absence killed the first live Calm
    # slot on 2026-08-24 — the feed offered `average` and `barcount`, `splice` refused
    # `column_mismatch`, and the refusal was correct.
    aligned, dropped = project_to_frozen_columns(inst, aligned, frozen)
    _refuse_bars_from_the_future(inst, aligned, through)
    checked = _refuse_overlap_disagreement(inst, aligned, frozen)
    frame, report = guard.splice(frozen, aligned)
    return JoinedFrame(inst, frame, report,
                       getattr(provider, "name", type(provider).__name__),
                       provider_rows=offered, overlap_checked=checked,
                       provider_error=str(getattr(provider, "last_error", "") or ""),
                       dropped_columns=dropped)


def live_frames(insts, *, provider: BarProvider, through,
                data_paths: Mapping[str, str] | None = None,
                frozen_frames: Mapping[str, Any] | None = None) -> dict:
    """`{inst: JoinedFrame}` for a whole basket.

    `frozen_frames` is offered so a caller that already holds the history does not read eight
    years of parquet twice; `data_paths` is the ordinary route. Handing neither is an error
    rather than an empty result, because "no instruments" and "no data" must not look alike.
    """
    if frozen_frames is None and data_paths is None:
        raise LiveSourceRefused("no_frozen_half",
                                "live_frames needs either data_paths or frozen_frames")
    out = {}
    for inst in insts:
        frozen = (frozen_frames or {}).get(inst)
        if frozen is None:
            path = (data_paths or {}).get(inst)
            if path is None:
                raise LiveSourceRefused("no_frozen_half", f"no frozen half offered for {inst}")
            frozen = frozen_frame(inst, path)
        out[inst] = live_frame(inst, frozen=frozen, provider=provider, through=through)
    return out


def sleeve_frames(*, provider: BarProvider, through,
                  data_paths: Mapping[str, str] | None = None,
                  frozen_frames: Mapping[str, Any] | None = None,
                  sleeves=None) -> dict:
    """`{sleeve: {inst: JoinedFrame}}` — the joined frame each sleeve reads today.

    Every sleeve is served from ONE join per instrument rather than one per sleeve. Calm A and
    the swing sleeve both trade the S&P; joining its history twice would let two frames of the
    same instrument disagree inside a single decision, which is the kind of difference nobody
    finds until it has already sized a position.
    """
    from global_index import track1_params as tp

    want = tuple(sleeves) if sleeves is not None else tuple(tp.SLEEVE_INSTRUMENTS)
    need = sorted({i for s in want for i in tp.SLEEVE_INSTRUMENTS[s]})
    joined = live_frames(need, provider=provider, through=through,
                         data_paths=data_paths, frozen_frames=frozen_frames)
    return {s: {i: joined[i] for i in tp.SLEEVE_INSTRUMENTS[s]} for s in want}


def join_report(by_sleeve: Mapping[str, Mapping[str, JoinedFrame]]) -> dict:
    """What the joins did, flat enough to print or write to a shadow summary."""
    seen: dict = {}
    for per_inst in by_sleeve.values():
        for inst, jf in per_inst.items():
            seen[inst] = jf.as_dict()
    return {"instruments": seen,
            "appended_total": sum(int(v["live_rows_appended"]) for v in seen.values()),
            "codes": sorted({str(v["code"]) for v in seen.values()})}


# ═════════════════════════════════════════════════════════════════════════════
# The live candidate source — precondition 2b
# ═════════════════════════════════════════════════════════════════════════════
#: Named refusals. Every one is recorded on the slot's ledger row, because "the slot could not
#: decide" and "the slot decided there was nothing" must never be the same record.
REGIME_UNAVAILABLE = "regime_unavailable"
COST_MISSING = "cost_missing"
STOP_RISK_UNAVAILABLE = "stop_risk_unavailable"
SLEEVE_NOT_LIVE = "sleeve_not_live"
STRESS_RULE_NOT_IN_PACKAGE = "stress_rule_not_in_package"
STRESS_BREADTH_INCOMPLETE = "stress_breadth_incomplete"
NO_SLEEVE_AT_THIS_INSTANT = "no_sleeve_at_this_instant"

HMM_FIT_END = "2024-12-31"


def _session_day(day) -> "pd.Timestamp":
    """A session day as this repo writes them: naive and normalised.

    The slot instant is tz-aware ET and every day-keyed structure here — labels, ATR rows, the
    RTH session table — is naive. Converting at the one boundary rather than at each comparison
    is what stops a tz-aware/naive mismatch turning into a silent empty lookup.
    """
    ts = pd.Timestamp(day)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


def causal_regime_label(labels, day) -> "str | None":
    """The label a slot on `day` is allowed to read: the last one STRICTLY BEFORE `day`.

    Strictly, and the word is the whole function. A morning slot that reads today's own label
    is reading a row computed from today's close — six hours of the future — and it would not
    look wrong, because the label would be present and plausible. `asof(day)` returns today's
    row when today has one, which is why this does not use it.
    """
    if labels is None:
        return None
    s = labels if isinstance(labels, pd.Series) else pd.Series(labels)
    if s.empty:
        return None
    idx = pd.DatetimeIndex(s.index)
    idx = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    s = pd.Series(list(s.values), index=idx).sort_index()
    before = s.loc[s.index < _session_day(day)]
    return None if before.empty else str(before.iloc[-1])


def default_costs(slippage_ticks: float = 2.0) -> dict:
    """One cost object per Track 1 instrument, at the backtest's own slippage.

    Two ticks a side is what every measured Track 1 number was produced under; the entry point
    that could pass a different number is not consulted, because a default at a CLI is not the
    value that made the artifact — this repo has already published a wrong conclusion by
    reading one instead of the other.

    Nothing here asks a broker. Live commissions are a runtime lookup and would make the risk a
    slot computes depend on when it ran.
    """
    from futures.swing_tf import costs_for_basket
    from global_index import specs as gi_specs
    from global_index._core import FuturesCost as GIFC

    costs = dict(costs_for_basket(slippage_ticks=slippage_ticks))
    for inst, spec in gi_specs.SPECS.items():
        costs.setdefault(inst, GIFC(point_value=spec.point_value, tick=spec.tick,
                                    commission_rt=spec.commission_rt,
                                    slippage_ticks_per_side=slippage_ticks))
    return costs


def causal_daily_atr(frame, day, period: int = 14) -> "float | None":
    """The daily ATR a slot on `day` may use: the last value STRICTLY BEFORE `day`.

    The same trap as the regime label, and easier to miss. `daily_atr_series` builds one row per
    session from that session's own high, low and close, so the row for today is not finished
    until today is. The measured artifacts size from `asof(day)`, which takes today's row when
    it exists; that is defensible in a backtest that books the whole session at once and is
    lookahead at 10:00.

    So the live risk a slot computes can differ slightly from the risk recorded in the measured
    artifact for the same day. That is a real difference, it is in the causal direction, and it
    is written down here rather than reconciled away.
    """
    from futures._validated_core import daily_atr_series

    idx = pd.DatetimeIndex(frame.index)
    naive = frame.copy()
    naive.index = idx.tz_localize(None) if idx.tz is not None else idx
    series = daily_atr_series(naive, period)
    before = series.loc[series.index < _session_day(day)]
    if before.empty:
        return None
    v = float(before.iloc[-1])
    return None if not np.isfinite(v) or v <= 0 else v


@dataclass
class LiveTrack1Source:
    """Today's Track 1 candidates, from today's bars. **Precondition 2b, as far as it goes.**

    What it can answer
    ------------------
    Only the sleeves that have a Track 1 slot: `roska4_calm` at 10:00, `roska4_stress`
    between 10:35 and 12:30, and — since Stage 5M-B — `roska4_swing` between 14:05 and 15:55.
    `global_nkd` still has no slot, no intraday requirement and no ledger window: it decides
    overnight, and asking this source for it is a refusal, not an empty list.

    The swing slots are registered with `--bar-provider none` in Stage 5M-B, so in production
    they reach `no_bar_provider` and stop there by design. The path below them is real and is
    exercised with an injected frame provider; what has not happened yet is a live feed.

    And of those two, only Calm A is answerable in-package. The Stress rule still lives in
    `scratch/`, and importing scratch from a live path is the move this route has refused
    since Stage 3. That refusal is named rather than hidden.

    What it refuses, and why each one is a refusal instead of an empty list
    ----------------------------------------------------------------------
    An empty list means "the rule ran and today does not set up". Every condition below means
    "the rule did not run", and the two must never be recorded the same way — a window full of
    silent failures would otherwise close as a clean day with no signals.

        no_bar_provider          nobody handed it a source of today's bars
        regime_unavailable       no label exists for any session before today
        cost_missing             an instrument the sleeve trades has no cost object
        stop_risk_unavailable    the disaster stop could not be computed causally, so the risk
                                 the cap gate reads would have to be invented
        sleeve_not_live          the sleeve has no Track 1 slot
        stress_rule_not_in_package   the rule is in scratch

    No broker anywhere in it. The provider is injected, and `FrameBarProvider` is what the
    tests use — so nothing here has been exercised against a live feed, and this class does not
    claim otherwise.
    """
    bar_provider: Any = None
    regime_csv: str = "spy_daily_live.csv"
    labels: Any = None
    costs: Mapping[str, Any] | None = None
    data_paths: Mapping[str, str] | None = None
    frozen_frames: Mapping[str, Any] | None = None
    calm_params: Any = None
    stress_params: Any = None
    #: Stage 5M-B. Both default to None and are DERIVED when needed rather than defaulted to a
    #: value here: `swing_params` would otherwise be a second place the route's fill law lives,
    #: and `short_days` a second place the SPY short gate is decided.
    swing_params: Any = None
    #: Stage 5N. Defaults to None and is derived — NormalR4Params(ema_period=10,
    #: fill_law=LIVE_FILL_LAW) — for the same reason swing_params is: a value stored here
    #: would be a second place the sleeve's identity lives.
    nkd_params: Any = None
    short_days: Any = None
    hmm_fit_end: str = HMM_FIT_END
    name: str = "live"

    @property
    def last_diagnostics(self) -> dict:
        """Per-sleeve diagnostics blocks from the most recent candidate scan.

        An attribute created on first read rather than in `__init__`, so an instance built by
        any of this class's constructors — including the ones tests use — has it without those
        constructors needing to know about it.
        """
        if not hasattr(self, "_last_diagnostics"):
            self._last_diagnostics = {}
        return self._last_diagnostics

    def _stash_calm_gates(self, phase: str, inst: str, gates: list, setup) -> None:
        """Keep Calm's gates for the slot to persist, in the sleeve's own block shape.

        Stage 5ZZZ-AR. Wrapped end to end for the same reason its Normal-R4 neighbour is: a
        diagnostics failure must not be the reason a sleeve loses a candidate, and this runs
        on the path that finds them.
        """
        try:
            if not gates:
                return
            from global_index import track1_strategy_diagnostics as SD

            block = SD._calm_block(
                phase=phase, source=SD.RECORDED, slot_id="", at="",
                summary=("recorded by the slot" if setup is not None
                         else "recorded by the slot; no setup"),
                rows=[], gates=list(gates),
                nearest_failed_condition=next(
                    (g for g in gates if g.get("passed") is False), None))
            block["instrument"] = inst
            self.last_diagnostics.setdefault("roska4_calm", []).append(block)
        except Exception:                                          # noqa: BLE001
            pass

    def _stash_diagnostics(self, sleeve: str, inst: str, params, observer, setup,
                           labels=None) -> None:
        """Keep the detector's own account of this instrument, for the slot to persist.

        Stage 5ZZZ-B, OBSERVABILITY ONLY. Wrapped end to end: a diagnostics failure must not be
        the reason a sleeve loses a candidate, and this runs on the path that finds them.
        """
        try:
            from global_index import track1_strategy_diagnostics as SD

            block = SD.normal_r4_block(
                sleeve=sleeve, slot_id="", ema_period=params.ema_period,
                observer=observer, setup=setup, data_identity=inst,
                source=SD.RECORDED,
                # Stage 5ZZZ-G. Descriptive only. Taken from the object this sleeve just handed
                # the detector, so a RECORDED block names its regime basis exactly as a
                # reconstructed one does. Nothing here decides anything.
                regime_basis_note=SD.regime_basis(labels) if labels is not None else "")
            block["instrument"] = inst
            self.last_diagnostics.setdefault(sleeve, []).append(block)
        except Exception:                                          # noqa: BLE001
            pass

    def _label_map(self):
        if self.labels is not None:
            return self.labels
        from futures._validated_core import benchmark_daily, label_regimes
        raw = label_regimes(benchmark_daily(self.regime_csv), "2018-01-01", 3, self.hmm_fit_end)
        return {pd.Timestamp(k).normalize(): v for k, v in raw.items()}

    def _cost_for(self, inst: str):
        costs = self.costs if self.costs is not None else default_costs()
        c = costs.get(inst)
        if c is None:
            raise LiveSourceRefused(COST_MISSING,
                                    f"no cost object for {inst}; risk and P&L would both be "
                                    f"guesses, so the slot stops here")
        return c

    def sleeves_at(self, now_et) -> list:
        from global_index import track1_params as tp

        ts = pd.Timestamp(now_et)
        hhmm = (ts.hour, ts.minute)
        out = []
        for sleeve, (lo, hi) in tp.WINDOWS_ET.items():
            lo_t = tuple(int(x) for x in lo.split(":"))
            hi_t = tuple(int(x) for x in hi.split(":"))
            if lo_t <= hhmm <= hi_t:
                out.append(sleeve)
        return out

    def candidates(self, key) -> list:
        """Every candidate decidable at `key`, which is the slot instant.

        Raises `LiveSourceRefused` when the rule could not run. Returns a list — possibly
        empty — when it ran.
        """
        now = pd.Timestamp(key)
        day = _session_day(now)
        sleeves = self.sleeves_at(now)
        if not sleeves:
            raise LiveSourceRefused(NO_SLEEVE_AT_THIS_INSTANT,
                                    f"{now} is inside no Track 1 window")
        out: list = []
        for sleeve in sleeves:
            out.extend(self._for_sleeve(sleeve, now, day))
        return out

    def _for_sleeve(self, sleeve: str, now, day) -> list:
        if sleeve == "roska4_stress":
            return self._stress_candidates(now, day)
        if sleeve == "roska4_swing":
            return self._swing_candidates(now, day)
        if sleeve == "global_nkd":
            return self._nkd_candidates(now, day)
        if sleeve != "roska4_calm":
            raise LiveSourceRefused(
                SLEEVE_NOT_LIVE,
                f"{sleeve} has no Track 1 slot. The sleeves that do are "
                f"{sorted(_live_sleeves())}, and their windows are the only instants this "
                f"source can be asked about")
        return self._calm_candidates(now, day)

    def _nkd_candidates(self, now, day) -> list:
        """MNKD at a slot between 01:10 and 02:55 ET — 14:10 onward on the Tokyo clock.

        Stage 5N, and deliberately thin: the sleeve is the SAME engine as Normal-R4 at
        different settings — ema 10, no R4 context filter, labels read through
        `RegimeLabels(lag_days=1)` — which is exactly how the committed artifacts were
        generated (`NormalR4Params(ema_period=10)`, `apply_context_filter=False`). Nothing
        about the entry rule is written here, because a second implementation of a rule
        proves nothing about the first.

        Two clock facts carry the whole sleeve and are stated rather than implied:

        * the joined frame arrives on **Asia/Tokyo** (`frozen_frame` converts to the
          instrument's declared session zone), and `detect_entry_for_slot` truncates on the
          frame's own clock — so `now` is never compared against Tokyo stamps in ET terms;
        * the regime label is `RegimeLabels(lag_days=1)`: the label as of the Tokyo session
          date minus one day, because the Tokyo afternoon precedes the US close that would
          produce today's own label. That is the promoted sleeve's causality, reused whole.
        """
        from global_index import track1_normal_r4 as NR
        from global_index import track1_params as tp
        from global_index.regime import RegimeLabels
        from global_index.track1_signal_layer import Candidate

        if self.bar_provider is None:
            raise LiveSourceRefused(
                "no_bar_provider",
                "the live source was asked for MNKD candidates without a bar provider; "
                "today's Tokyo session could not be read")

        labels = self._label_map()
        if not labels:
            raise LiveSourceRefused(REGIME_UNAVAILABLE,
                                    "the regime label map is empty; the lag-1 read the "
                                    "sleeve was measured under has nothing to read")
        nlab = RegimeLabels(pd.Series(labels).sort_index(), lag_days=1)

        insts = tp.SLEEVE_INSTRUMENTS["global_nkd"]
        joined = sleeve_frames(provider=self.bar_provider, through=now,
                               data_paths=self.data_paths,
                               frozen_frames=self.frozen_frames,
                               sleeves=["global_nkd"])["global_nkd"]
        params = self.nkd_params or NR.NormalR4Params(ema_period=10,
                                                      fill_law=tp.LIVE_FILL_LAW)
        short_days = self.short_days
        if short_days is None:
            short_days = NR.short_days_from_csv(self.regime_csv, params.spy_short_filter)

        out = []
        for inst in insts:
            frame = joined[inst].frame
            # Stage 5ZZZ-B. OBSERVABILITY ONLY — the detector reports what it looked at.
            #
            # The observer's return value is discarded, its exceptions are swallowed inside the
            # detector, and the block is built in a `try`. Nothing below reads it; the slot
            # persists it after its coverage row. A diagnostics bug must not cost a candidate.
            _obs = _new_observer()
            setup = NR.detect_entry_for_slot(frame, nlab, inst, day, now, params,
                                             short_days=short_days,
                                             apply_context_filter=False,
                                             observer=_obs)
            self._stash_diagnostics("global_nkd", inst, params, _obs, setup, labels=nlab)
            if setup is None:
                continue
            cost = self._cost_for(inst)
            qty = int(tp.SLEEVE_QTY["global_nkd"])
            # Stage 5Q-9 — I-3. Sized through the one authority, on the basis the MEASURED
            # BOOK was admitted under. This read `abs(entry - stop)` until 2026-08-24, which
            # is 2.0 x daily ATR while the artifact admitted on 2.5 x daily ATR — exactly 20%
            # light against caps that were never re-measured for it.
            risk, risk_basis = tp.risk_dollars(
                "global_nkd", entry=setup.entry, stop=setup.stop,
                daily_atr=setup.daily_atr, point_value=cost.point_value, qty=qty)
            if not np.isfinite(risk) or risk <= 0:
                raise LiveSourceRefused(
                    STOP_RISK_UNAVAILABLE,
                    f"{inst}: stop {setup.stop} against entry {setup.entry} gives risk "
                    f"{risk}; a non-positive risk passes every cap gate unconditionally")
            # The candidate's entry_time is the AWARE Tokyo signal-bar stamp — the same
            # convention the committed replay rows carry (+09:00). The first draft converted
            # it to an ET string, and the window gate then rejected the live candidate for
            # the same reason it was rejecting the artifacts: a session-clock window judged
            # against the wrong wall. Aware stamps are instants; the gate converts them to
            # the window's own clock, so this is correct in both DST regimes.
            out.append(Candidate(
                trade_id=f"global_nkd::{inst}::{day.date()}",
                sleeve="global_nkd", instrument=inst, direction=setup.direction,
                qty=qty, risk_dollars=float(risk),
                entry_time=pd.Timestamp(setup.signal_bar), exit_time=None,
                entry_price=float(setup.entry), stop_price=float(setup.stop),
                pnl_sized=0.0, source="live-shadow",
                meta={"daily_atr_causal": setup.daily_atr,
                      "regime_lag1": setup.regime,
                      "signal_bar_session_clock": str(setup.signal_bar),
                      "session_tz": session_tz(inst),
                      "ema_period": params.ema_period,
                      "stop_basis_atr_mult": params.stop_basis_atr_mult,
                      "arm_hours": params.arm_hours,
                      "fill_law": params.fill_law,
                      "risk_basis": risk_basis}))
        return out

    def _swing_candidates(self, now, day) -> list:
        """Normal-R4 at a slot between 14:05 and 15:55. Stage 5M-B.

        Four instruments, each scanned independently: the sleeve has no basket-wide statement
        the way Stress does, so one instrument having no signal is an ordinary empty result
        rather than a reason to refuse the others.

        The regime is read CAUSALLY — the label that closed on a session strictly before today.
        Reading today's own row would be lookahead, and this sleeve trades one regime only, so
        that read decides whether anything happens at all.

        The stop is the sleeve's own: entry -+ 2.0 x the DAILY ATR, anchored at entry and never
        ratcheted. It comes back from the engine's own signal function rather than being
        recomputed here, because a second copy of a stop rule is a second thing to keep in step
        with the artifacts.
        """
        from global_index import track1_normal_r4 as NR
        from global_index import track1_params as tp
        from global_index.track1_signal_layer import Candidate

        if self.bar_provider is None:
            raise LiveSourceRefused(
                "no_bar_provider",
                "the live source was asked for Normal-R4 candidates without a bar provider; "
                "today's 14:00-15:55 window could not be read")

        labels = self._label_map()
        regime = causal_regime_label(labels, day)
        if regime is None:
            raise LiveSourceRefused(
                REGIME_UNAVAILABLE,
                f"no regime label exists for any session before {day.date()}. Normal-R4 "
                f"trades one regime, so a slot that cannot read yesterday's label cannot "
                f"decide anything — and today's own row is computed from today's close")

        # Stage 5ZZZ-Q. The detector gets the SAME causal object the outer gate just used.
        #
        # Until this line the gate above resolved `causal_regime_label` - the last label
        # strictly before `day` - and then handed the detector the raw map, in which
        # `labels.get(day)` looks up the session's OWN row. That row is computed from this
        # session's 16:00 close and does not exist at 14:05, so the detector's regime gate read
        # None and the sleeve refused every session, while the outer gate had just passed.
        #
        # `RegimeLabels(lag_days=1)` is not a new rule: it is exactly what the NKD path forty
        # lines above already passes, and exactly what the artifact regeneration wraps the
        # labels in. Stage 5ZZZ-N proved that object returns the previous session's label on
        # all 147 floor sessions where the two disagree. This makes the live detector read what
        # the backtest, the artifact and the signed paper identity all already say.
        #
        # No parameter changed. No threshold changed. The sleeve still trades one regime.
        from global_index.regime import RegimeLabels as _RegimeLabels

        _ser = pd.Series(labels)
        _idx = pd.DatetimeIndex(_ser.index)
        _ser.index = (_idx.tz_localize(None) if _idx.tz is not None else _idx).normalize()
        swing_labels = _RegimeLabels(_ser.sort_index(), lag_days=1)

        insts = tp.SLEEVE_INSTRUMENTS["roska4_swing"]
        joined = sleeve_frames(provider=self.bar_provider, through=now,
                               data_paths=self.data_paths,
                               frozen_frames=self.frozen_frames,
                               sleeves=["roska4_swing"])["roska4_swing"]
        params = self.swing_params or NR.NormalR4Params(fill_law=tp.LIVE_FILL_LAW)
        short_days = self.short_days
        if short_days is None:
            short_days = NR.short_days_from_csv(self.regime_csv, params.spy_short_filter)

        out = []
        for inst in insts:
            frame = joined[inst].frame
            # Stage 5ZZZ-B. Same as the NKD path above, and for the same reasons.
            _obs = _new_observer()
            setup = NR.detect_entry_for_slot(frame, swing_labels, inst, day, now, params,
                                             short_days=short_days,
                                             apply_context_filter=True,
                                             observer=_obs)
            # The basis recorded is the one taken from the object actually passed on the line
            # above - never from the sleeve's name.
            self._stash_diagnostics("roska4_swing", inst, params, _obs, setup,
                                    labels=swing_labels)
            if setup is None:
                continue
            cost = self._cost_for(inst)
            qty = int(tp.SLEEVE_QTY["roska4_swing"])
            # Stage 5Q-9 — I-3, same as global_nkd: the cap gate reads the basis the measured
            # book was admitted under, not the honest stop distance. See track1_params.
            risk, risk_basis = tp.risk_dollars(
                "roska4_swing", entry=setup.entry, stop=setup.stop,
                daily_atr=setup.daily_atr, point_value=cost.point_value, qty=qty)
            if not np.isfinite(risk) or risk <= 0:
                raise LiveSourceRefused(
                    STOP_RISK_UNAVAILABLE,
                    f"{inst}: stop {setup.stop} against entry {setup.entry} gives risk "
                    f"{risk}; a non-positive risk passes every cap gate unconditionally")
            out.append(Candidate(
                trade_id=f"normal_r4::{inst}::{day.date()}",
                sleeve="roska4_swing", instrument=inst, direction=setup.direction,
                qty=qty, risk_dollars=float(risk),
                entry_time=setup.entry_time, exit_time=None,
                entry_price=float(setup.entry), stop_price=float(setup.stop),
                pnl_sized=0.0, source="live-shadow",
                meta={"daily_atr_causal": setup.daily_atr,
                      "regime_prev_session": regime,
                      "signal_bar": str(setup.signal_bar),
                      "stop_basis_atr_mult": params.stop_basis_atr_mult,
                      "arm_hours": params.arm_hours,
                      "fill_law": params.fill_law,
                      "risk_basis": risk_basis}))
        return out

    def _stress_candidates(self, now, day) -> list:
        """Stress-MNQ at a slot between 10:35 and 12:30.

        The signal is a statement about the whole R4 basket, so all four instruments' frames
        are joined even though only MNQ is traded. A missing one is a refusal rather than a
        smaller basket: `below_count` and `gapdown_count` are counts out of four, and counting
        three would quietly lower the bar the rule was measured at.

        There is no regime label here. The rule was built to avoid the lag-0 daily label an
        earlier candidate leaked on, so there is nothing causal to get wrong in that direction.
        """
        from global_index import track1_params as tp
        from global_index import track1_stress_mnq as SM
        from global_index.track1_signal_layer import Candidate

        if self.bar_provider is None:
            raise LiveSourceRefused("no_bar_provider",
                                    "the live source was asked for Stress candidates without "
                                    "a bar provider")
        need = sorted(set(SM.BREADTH_BASKET) | set(SM.StressParams().instruments))
        joined = live_frames(need, provider=self.bar_provider, through=now,
                             data_paths=self.data_paths, frozen_frames=self.frozen_frames)
        frames = {i: joined[i].frame for i in need}
        for inst in need:
            if frames[inst] is None or len(frames[inst].index) == 0:
                raise LiveSourceRefused(
                    STRESS_BREADTH_INCOMPLETE,
                    f"{inst} has no bars, and the Stress signal counts how many of "
                    f"{len(SM.BREADTH_BASKET)} instruments are below their open and VWAP; "
                    f"counting a smaller basket lowers the bar the rule was measured at")

        params = self.stress_params or SM.StressParams()
        setups = SM.detect_entry_for_slot(frames, day, now=now, params=params)
        # Stage 5ZZZ-AT, NOT DONE HERE. Stress answers all four entry conditions in full --
        # `entry_conditions` is `all()` over the table `entry_checks` walks -- and the slot
        # records none of it, so its lanes read "value not published" for rules the detector
        # answered. Wiring it needs an observer seam in `track1_stress_mnq` the way Calm got
        # one, because the features are computed inside `detect_entry_for_slot` and reaching
        # them from here would mean recomputing a basket state the slot already has. A first
        # attempt called `basket_state` with the wrong arguments; recomputing it correctly
        # would still be a second evaluation of a rule that decides, which is the thing this
        # whole stage refuses to do.
        out = []
        for st in setups:
            cost = self._cost_for(st.inst)
            qty = int(tp.SLEEVE_QTY["roska4_stress"])
            risk = SM.risk_dollars(st.entry, st.stop, float(cost.point_value), qty)
            if not np.isfinite(risk) or risk <= 0:
                raise LiveSourceRefused(
                    STOP_RISK_UNAVAILABLE,
                    f"{st.inst}: stop {st.stop} against entry {st.entry} gives risk {risk}; a "
                    f"non-positive risk passes every cap gate unconditionally")
            out.append(Candidate(
                trade_id=f"stress_mnq_only_g3_q7::{st.inst}::{day.date()}",
                sleeve="roska4_stress", instrument=st.inst, direction=st.direction,
                qty=qty, risk_dollars=float(risk),
                entry_time=st.entry_time, exit_time=None,
                entry_price=float(st.entry), stop_price=float(st.stop),
                pnl_sized=0.0, source="live-shadow",
                meta={"target": st.target, "pre_high": st.pre_high, "pre_low": st.pre_low,
                      "vwap": st.vwap, "gap": st.gap,
                      "below_count": st.below_count, "gapdown_count": st.gapdown_count,
                      "avg_gap": st.avg_gap,
                      "signal_time": str(st.signal_time), "known_time": str(st.known_time),
                      "risk_basis": "true_stop_distance"}))
        return out

    def calm_pre_entry(self, key) -> list:
        """The Calm setups decidable at `key` WITHOUT reading the entry bar. Stage 5ZX.

        `candidates` cannot answer this and never could. Two separate things stop it: its
        first act is `sleeves_at(now)`, and 09:32 sits inside no Track 1 window at all; and
        `detect_entry_for_day` returns `None` whenever today has no 10:00 bar, which at half
        past nine is every single day. A decide-half slot calling it would receive an empty
        list on every day of its life and record, in perfectly good faith, that Calm did not
        set up today.

        Returns a list of `(CalmPreEntry, atr, point_value, qty)`. Not `Candidate` objects,
        deliberately: a `Candidate` carries `entry_price` and `stop_price`, and there is no
        honest number to put in either at this hour. Anything that produced one here would be
        inventing the very price this phase exists to avoid inventing.
        """
        from global_index import track1_calm_a as CA
        from global_index import track1_params as tp

        now = pd.Timestamp(key)
        day = _session_day(now)

        labels = self._label_map()
        if causal_regime_label(labels, day) is None:
            raise LiveSourceRefused(
                REGIME_UNAVAILABLE,
                f"no regime label exists for any session before {day.date()}. The label a "
                f"morning slot may read is the one that closed yesterday")

        insts = tp.SLEEVE_INSTRUMENTS["roska4_calm"]
        joined = sleeve_frames(provider=self.bar_provider, through=now,
                               data_paths=self.data_paths,
                               frozen_frames=self.frozen_frames,
                               sleeves=["roska4_calm"])["roska4_calm"]
        params = self.calm_params or CA.CalmAParams()
        out: list = []
        for inst in insts:
            frame = joined[inst].frame
            # Stage 5ZZZ-AR. OBSERVABILITY ONLY, and it reaches disk through a stream that
            # already exists: `run_live_day_track1` writes whatever `last_diagnostics` holds
            # for the sleeve, so nothing in the runner changes. The shadow-intent record is
            # deliberately NOT touched -- six readers, two of them gates.
            _cg: list = []
            pre = CA.detect_setup_before_entry(
                frame, labels, inst, day, params,
                observer=lambda e, _cg=_cg: (_cg.append({k: v for k, v in e.items()
                                                         if k != "kind"})
                                             if e.get("kind") == "gate" else None))
            self._stash_calm_gates(CA_DECIDE_PHASE, inst, _cg, pre)
            if pre is None:
                continue
            atr = causal_daily_atr(frame, day)
            if atr is None:
                # Same refusal the full path makes, at the same strength. The stop DISTANCE
                # is 1.5 x ATR and is knowable now; without the ATR it is not, and an intent
                # recorded with no stop distance is an intent nobody could act on.
                raise LiveSourceRefused(
                    STOP_RISK_UNAVAILABLE,
                    f"{inst}: no daily ATR from a session before {day.date()}, so the "
                    f"disaster stop has no distance")
            cost = self._cost_for(inst)
            out.append((pre, float(atr), float(cost.point_value),
                        int(tp.SLEEVE_QTY["roska4_calm"])))
        return out

    def _calm_candidates(self, now, day) -> list:
        from global_index import track1_calm_a as CA
        from global_index import track1_params as tp
        from global_index.track1_signal_layer import Candidate

        if self.bar_provider is None:
            raise LiveSourceRefused("no_bar_provider",
                                    "the live source was asked for candidates without a bar "
                                    "provider; today's session could not be read")
        labels = self._label_map()
        if causal_regime_label(labels, day) is None:
            raise LiveSourceRefused(
                REGIME_UNAVAILABLE,
                f"no regime label exists for any session before {day.date()}. The label a "
                f"morning slot may read is the one that closed yesterday; today's own row, if "
                f"present, is computed from today's close and reading it would be lookahead")

        insts = tp.SLEEVE_INSTRUMENTS["roska4_calm"]
        joined = sleeve_frames(provider=self.bar_provider, through=now,
                               data_paths=self.data_paths,
                               frozen_frames=self.frozen_frames,
                               sleeves=["roska4_calm"])["roska4_calm"]
        params = self.calm_params or CA.CalmAParams()
        out = []
        for inst in insts:
            frame = joined[inst].frame
            _cg: list = []
            setup = CA.detect_entry_for_day(
                frame, labels, inst, day, params,
                observer=lambda e, _cg=_cg: (_cg.append({k: v for k, v in e.items()
                                                         if k != "kind"})
                                             if e.get("kind") == "gate" else None))
            if setup is None:
                self._stash_calm_gates(CA_OBSERVE_PHASE, inst, _cg, None)
                continue
            cost = self._cost_for(inst)
            atr = causal_daily_atr(frame, day)
            if atr is None:
                raise LiveSourceRefused(
                    STOP_RISK_UNAVAILABLE,
                    f"{inst}: no daily ATR from a session before {day.date()}, so the disaster "
                    f"stop has no distance and the risk the cap gate reads would be invented")
            stop = CA.disaster_stop(setup.entry, atr, params)
            qty = int(tp.SLEEVE_QTY["roska4_calm"])
            risk = CA.stop_risk_dollars(setup.entry, stop, float(cost.point_value), qty)
            # The fourth Calm rule, and it is decided HERE rather than in the detector: the
            # two stop functions are only ever called from this path. Reported before the
            # refusal below so a refused slot still says which condition refused it.
            _cg.append({"gate": "stop_risk_computed",
                        "passed": bool(np.isfinite(risk) and risk > 0),
                        "value": float(risk) if np.isfinite(risk) else None,
                        "threshold": {"must_be": "> 0"}, "comparator": ">"})
            self._stash_calm_gates(CA_OBSERVE_PHASE, inst, _cg, setup)
            if not np.isfinite(risk) or risk <= 0:
                raise LiveSourceRefused(
                    STOP_RISK_UNAVAILABLE,
                    f"{inst}: stop distance {setup.entry - stop} gives risk {risk}; a "
                    f"non-positive risk would pass every cap gate unconditionally")
            out.append(Candidate(
                trade_id=f"calm_a::{inst}::{day.date()}",
                sleeve="roska4_calm", instrument=inst, direction=setup.direction,
                qty=qty, risk_dollars=float(risk),
                entry_time=setup.entry_time, exit_time=None,
                entry_price=float(setup.entry), stop_price=float(stop),
                pnl_sized=0.0, source="live-shadow",
                meta={"prev_session_day": str(setup.prev_session_day.date()),
                      "prev_close_loc": setup.prev_close_loc,
                      "prev_rth_ret": setup.prev_rth_ret,
                      "gap_from_prev_rth_close": setup.gap_from_prev_rth_close,
                      "daily_atr_causal": atr,
                      "regime_prev_session": causal_regime_label(labels, day),
                      "risk_basis": "true_stop_distance"}))
        return out

    def early_exit_valuer(self, key):
        """Price a displaced position. A live displacement is priced at the fill the broker
        reports on the close leg, and no broker is attached — so this refuses rather than
        returning a number from a replay, which would be a price from another year."""
        def _refuse(*_a, **_k):
            raise LiveSourceRefused(
                "no_live_valuer",
                "a displaced position must be booked at the price the close leg actually "
                "filled at; there is no broker attached to this source")
        return _refuse
