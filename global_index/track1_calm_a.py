"""global_index/track1_calm_a.py — the Calm A PCLoc detector, as a function.

Stage 4, closing SLEEVE_calm_a by IMPLEMENTING the detector rather than accepting a frozen
list of its answers.

What was frozen, and what this replaces
---------------------------------------
`scratch/calm_a_disaster_stop_probe_20260822.build_calm_trades` computes the ATR15 disaster
stop, the exit simulation, the risk and the P&L from bars — that half was always callable.
Its SETUP LIST came from `scratch/calm_pcloc_not_deep_gap_trade_list.csv`: which days set up,
in which direction, at what entry price. Nothing in the tree writes that CSV. Every reference
to it is a reader. So the detector existed as a column and as prose, and today had no answer.

The rule, and where each number comes from
-------------------------------------------
Named in the audit as `lag1calm_pcloc_bottom_down_long_e1000_x1555__MES_MNQ__not_deep_gap`:

    regime      the SPY HMM label at the PRIOR session is "Calm" — lag 1, so the label the
                decision uses closed before the session it trades
    pcloc       the prior session's RTH close sits in the BOTTOM THIRD of that session's RTH
                range:  (close - low) / (high - low) <= 1/3
    down        the prior session's RTH closed at or below its own open:  close/open - 1 <= 0
    not_deep    the gap from the prior RTH close is not worse than -1.0%:
                current_rth_open / prior_rth_close - 1 >= -0.010
    trade       LONG only, MES and MNQ only, entry at the 10:00 OPEN, exit at the 15:55 OPEN

The two thresholds that could have been guessed were instead read off the frozen list and
then confirmed against the audit: `prev_close_loc` tops out at exactly 0.333333 and
`prev_rth_ret` at exactly 0.000000 across all 421 rows, and the audit states the gap filter
verbatim as `current_rth_open / prior_rth_close - 1 >= -0.010`.

The RTH window is [09:30, 15:59], not [09:30, 16:00]
-----------------------------------------------------
Measured, not assumed, and it changes the answer. For MNQ on 2018-01-04 the frozen row implies
a prior RTH close of 8724.50. The 09:30-16:00 window closes at 8725.75; the 09:30-15:59 window
closes at 8724.50. Reading one bar too far moves `prev_close_loc` from 0.3248 to 0.3675 —
across the 1/3 threshold — so that single bar decides whether the day sets up at all.

`open_loc_prev_range` is carried in the frozen list and is NOT a criterion: it ranges from
-1.53 to +2.05 across the selected rows, so nothing is being filtered on it. It is computed
here anyway, because a diagnostic that exists in the record and not in the code is the next
thing somebody mistakes for a rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

CALM = "Calm"
LONG = "LONG"


@dataclass(frozen=True)
class CalmAParams:
    """Every threshold the detector reads. Defaults are the shipped configuration."""
    instruments: tuple = ("MES", "MNQ")
    calm_label: str = CALM
    regime_lag_sessions: int = 1
    close_loc_max: float = 1.0 / 3.0
    prev_ret_max: float = 0.0
    gap_min: float = -0.010
    rth_start: str = "09:30"
    rth_end: str = "15:59"
    #: A session counts only if it ran to the RTH end. See `rth_sessions` — this is the rule
    #: that decides which session is PRIOR, and it is read off the record rather than guessed.
    require_full_rth_session: bool = True
    entry_time: str = "10:00"
    exit_time: str = "15:55"
    #: The disaster stop is `entry - mult x ATR`, LONG only. 1.5 is `StopSpec("atr15","atr",1.5)`
    #: from the probe that measured the sleeve; it is the sleeve's own stop, not a house risk
    #: parameter, so it lives beside the rest of the rule rather than in a risk config.
    disaster_stop_atr_mult: float = 1.5


@dataclass(frozen=True)
class CalmSetup:
    """One detected setup. Prices are the bar OPENs the strategy actually transacts at."""
    day: pd.Timestamp
    inst: str
    direction: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    #: `None` at a live 10:00 slot: the exit bar is six hours away and must not be invented.
    exit_time: "pd.Timestamp | None"
    entry: float
    exit: float
    prev_session_day: pd.Timestamp
    gap_from_prev_rth_close: float
    prev_close_loc: float
    prev_rth_ret: float
    open_loc_prev_range: float

    def as_row(self) -> dict:
        return {"day": str(self.day.date()), "inst": self.inst,
                "direction": self.direction,
                "signal_time": str(self.signal_time), "entry_time": str(self.entry_time),
                "exit_time": str(self.exit_time),
                "entry": float(self.entry), "exit": float(self.exit),
                "prev_session_day": str(self.prev_session_day.date()),
                "gap_from_prev_rth_close": float(self.gap_from_prev_rth_close),
                "prev_close_loc": float(self.prev_close_loc),
                "prev_rth_ret": float(self.prev_rth_ret),
                "open_loc_prev_range": float(self.open_loc_prev_range)}


def _naive(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return idx.tz_localize(None) if idx.tz is not None else idx


def rth_sessions(df1m: pd.DataFrame, params: CalmAParams | None = None) -> pd.DataFrame:
    """One row per session: the RTH open/high/low/close on the [09:30, 15:59] window.

    Indexed by tz-naive session date, which is the key everything downstream joins on.

    A session counts only if it RAN TO THE RTH END. That is the rule that decides which
    session is "prior", and it was read out of the frozen record rather than guessed — the
    record's own `prev_session_day` column names it four times:

        2019-12-26 -> prior 2019-12-23, skipping Christmas Eve (early close)
        2020-12-28 -> prior 2020-12-23, skipping Christmas Eve
        2023-11-27 -> prior 2023-11-22, skipping Black Friday (early close)
        2025-02-18 -> prior 2025-02-14, skipping Presidents' Day (shortened session)

    A calendar was tried first and is the wrong tool: `raits.live.trading_calendar` calls
    2019-12-24 and 2023-11-24 trading days, which they are — the exchange is open. What this
    detector cannot use is a session with no 15:59 bar, because its close and its range would
    then be measured at 13:00 and mean something different. Requiring the end bar is the same
    rule the data can answer on its own, with no calendar to install and none to disagree with.

    Measured cost of getting it wrong: with the calendar rule, floor lost 5 rows and gained 2
    that the record does not have.
    """
    p = params or CalmAParams()
    d = df1m.copy()
    d.index = _naive(df1m.index)
    rth = d.between_time(p.rth_start, p.rth_end)
    if rth.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    g = rth.groupby(rth.index.normalize())
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last()})
    if p.require_full_rth_session and len(out):
        end_t = pd.Timestamp(p.rth_end).time()
        ran_to_close = {d for d, gg in rth.groupby(rth.index.normalize())
                        if (gg.index.time == end_t).any()}
        out = out[[d in ran_to_close for d in out.index]]
    return out


def _bar_open_at(df1m: pd.DataFrame, day: pd.Timestamp, hhmm: str):
    """The OPEN of the bar that starts at `hhmm` on `day`, or None if that bar is absent.

    None rather than the nearest bar: this sleeve transacts at a named instant, and silently
    substituting a neighbouring bar is how an entry price ends up belonging to a minute the
    strategy never chose.
    """
    idx = _naive(df1m.index)
    sel = df1m[idx.normalize() == day]
    if sel.empty:
        return None, None
    sel_naive = sel.copy()
    sel_naive.index = _naive(sel.index)
    want = day + pd.Timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:]))
    if want not in sel_naive.index:
        return None, None
    return float(sel_naive.loc[want, "open"]), sel.index[sel_naive.index.get_loc(want)]


def regime_at(regime, day) -> str | None:
    """The label for a session. Accepts a dict, a Series or a RegimeLabels wrapper."""
    if regime is None:
        return None
    getter = getattr(regime, "get", None)
    if getter is not None:
        try:
            v = getter(pd.Timestamp(day))
        except TypeError:
            v = None
        if v is not None:
            return str(v)
    try:
        v = regime[pd.Timestamp(day)]
        return None if v is None else str(v)
    except Exception:
        return None


def entry_conditions(prev_row, cur_rth_open: float, params: CalmAParams) -> "dict | None":
    """The Calm A entry test, in one place. `None` means the day does not set up.

    Extracted so the full-session detector and the 10:00 live-shadow path cannot drift into two
    slightly different rules — the failure this project has paid for more than once. Everything
    it reads is causal at 10:00: the prior session is complete, and the current session's RTH
    OPEN is fixed at 09:30.
    """
    p = params
    rng = float(prev_row["high"]) - float(prev_row["low"])
    if not np.isfinite(rng) or rng <= 0:
        return None
    close_loc = (float(prev_row["close"]) - float(prev_row["low"])) / rng
    if not (close_loc <= p.close_loc_max):
        return None

    po = float(prev_row["open"])
    if not np.isfinite(po) or po == 0:
        return None
    prev_ret = float(prev_row["close"]) / po - 1.0
    if not (prev_ret <= p.prev_ret_max):
        return None

    pc = float(prev_row["close"])
    if not np.isfinite(pc) or pc == 0:
        return None
    gap = float(cur_rth_open) / pc - 1.0
    if not (gap >= p.gap_min):
        return None
    return {"rng": rng, "close_loc": close_loc, "prev_ret": prev_ret, "gap": gap}


def detect(df1m: pd.DataFrame, regime, inst: str,
           params: CalmAParams | None = None) -> list:
    """Every Calm A setup this instrument's bars produce, in session order.

    Causal by construction: every input except the entry and exit prices comes from sessions
    strictly before the one being traded, and the two prices are the OPENs of bars at 10:00
    and 15:55, both after the decision instant of 09:30.
    """
    p = params or CalmAParams()
    if inst not in p.instruments:
        return []
    sessions = rth_sessions(df1m, p)
    if sessions.empty:
        return []
    days = list(sessions.index)
    out: list = []

    for i in range(1, len(days)):
        day, prev = days[i], days[i - p.regime_lag_sessions] if i >= p.regime_lag_sessions \
            else None
        if prev is None:
            continue

        if regime_at(regime, prev) != p.calm_label:
            continue

        feats = entry_conditions(sessions.loc[prev], float(sessions.loc[day]["open"]), p)
        if feats is None:
            continue
        close_loc, prev_ret, gap = feats["close_loc"], feats["prev_ret"], feats["gap"]
        rng, pr = feats["rng"], sessions.loc[prev]
        cur = sessions.loc[day]

        entry, entry_ts = _bar_open_at(df1m, day, p.entry_time)
        exit_px, exit_ts = _bar_open_at(df1m, day, p.exit_time)
        if entry is None or exit_px is None:
            # A session missing its own 10:00 or 15:55 bar cannot be traded at the price the
            # rule names. Dropped rather than filled from a neighbour.
            continue

        sig_ts = df1m.index[_naive(df1m.index).get_indexer(
            [day + pd.Timedelta(hours=9, minutes=30)], method="nearest")[0]]
        out.append(CalmSetup(
            day=day, inst=inst, direction=LONG,
            signal_time=sig_ts, entry_time=entry_ts, exit_time=exit_ts,
            entry=entry, exit=exit_px, prev_session_day=prev,
            gap_from_prev_rth_close=gap, prev_close_loc=close_loc, prev_rth_ret=prev_ret,
            open_loc_prev_range=(float(cur["open"]) - float(pr["low"])) / rng))
    return out


def detect_entry_for_day(df1m: pd.DataFrame, regime, inst: str, day,
                        params: CalmAParams | None = None) -> "CalmSetup | None":
    """Does `day` set up, judged with only what exists by 10:00? Entry-only; no exit.

    `detect` cannot answer this. It needs the 15:55 bar to fill `exit`, and a session that has
    not reached its own close is not in `rth_sessions` at all — which is correct for the
    historical detector and useless at a 10:00 slot. Rather than a second copy of the rule, both
    paths call `entry_conditions`; only the prices differ.

    Causality, spelled out because a morning slot is exactly where lookahead hides:

        prior session    complete, and it closed yesterday
        RTH open         today's 09:30 bar open, fixed 30 minutes before the decision
        entry            today's 10:00 bar open — the bar the rule transacts at
        exit             NOT read. It does not exist yet, and the returned setup says so by
                         carrying `exit_time=None`.

    Returns `None` when the day does not set up, when the prior session is missing, or when
    today has no 09:30 or 10:00 bar — never a guess filled from a neighbouring bar.
    """
    pre = detect_setup_before_entry(df1m, regime, inst, day, params)
    if pre is None:
        return None

    p = params or CalmAParams()
    entry, entry_ts = _bar_open_at(df1m, pre.day, p.entry_time)
    if entry is None:
        return None

    return CalmSetup(
        day=pre.day, inst=pre.inst, direction=pre.direction,
        signal_time=pre.signal_time, entry_time=entry_ts, exit_time=None,
        entry=float(entry), exit=float("nan"), prev_session_day=pre.prev_session_day,
        gap_from_prev_rth_close=pre.gap_from_prev_rth_close,
        prev_close_loc=pre.prev_close_loc, prev_rth_ret=pre.prev_rth_ret,
        open_loc_prev_range=pre.open_loc_prev_range)


@dataclass(frozen=True)
class CalmPreEntry:
    """What the Calm A rule has already decided BEFORE the entry bar exists.

    Stage 5ZX. Everything here is fixed by 09:31: the prior session closed yesterday, and
    today's 09:30 open is the last price the rule reads to decide. The ONLY things the entry
    bar adds are the entry price and its timestamp — including `open_loc_prev_range`, which
    looks like a price feature and is computed entirely from the 09:30 open.

    This exists so the DECIDE phase can record an intent at 09:32 without inventing a price.
    `detect_entry_for_day` is built ON it rather than beside it: two copies of a rule is a
    rule that will drift, and this one would drift silently — a shadow intent recorded from
    a stale copy would still look exactly like evidence.
    """
    day: pd.Timestamp
    inst: str
    direction: str
    signal_time: pd.Timestamp
    prev_session_day: pd.Timestamp
    rth_open: float
    gap_from_prev_rth_close: float
    prev_close_loc: float
    prev_rth_ret: float
    open_loc_prev_range: float


def detect_setup_before_entry(df1m: pd.DataFrame, regime, inst: str, day,
                              params: CalmAParams | None = None) -> "CalmPreEntry | None":
    """Does `day` set up, judged with only what exists by 09:31? No entry price read.

    Stage 5ZX. Same rule, same objects, one bar earlier. `_bar_open_at` is called ONCE here —
    for the 09:30 open — where `detect_entry_for_day` calls it twice. That difference is the
    whole point: the second call is what cannot be satisfied at half past nine, and asking for
    it is what made the live Calm slot report an empty candidate list on every day of its life
    instead of saying it was too early to know.

    Returns `None` for the same three reasons the full detector does: the day does not set up,
    the prior session is missing, or today has no 09:30 bar.
    """
    p = params or CalmAParams()
    if inst not in p.instruments:
        return None
    day = pd.Timestamp(day).normalize()

    sessions = rth_sessions(df1m, p)
    if sessions.empty:
        return None
    earlier = [d for d in sessions.index if d < day]
    if len(earlier) < p.regime_lag_sessions:
        return None
    prev = earlier[-p.regime_lag_sessions]
    if regime_at(regime, prev) != p.calm_label:
        return None

    rth_open, open_ts = _bar_open_at(df1m, day, p.rth_start)
    if rth_open is None:
        return None
    feats = entry_conditions(sessions.loc[prev], float(rth_open), p)
    if feats is None:
        return None

    return CalmPreEntry(
        day=day, inst=inst, direction=LONG, signal_time=open_ts, prev_session_day=prev,
        rth_open=float(rth_open),
        gap_from_prev_rth_close=feats["gap"], prev_close_loc=feats["close_loc"],
        prev_rth_ret=feats["prev_ret"],
        open_loc_prev_range=(float(rth_open) - float(sessions.loc[prev]["low"])) / feats["rng"])


def disaster_stop(entry: float, atr: float, params: CalmAParams | None = None) -> float:
    """The Calm A disaster stop: `entry - mult x ATR`, LONG only.

    The multiple is the sleeve's own, not a generic risk parameter, and the ATR handed in must
    be one the caller can justify at the decision instant — see `stop_risk_dollars`.
    """
    p = params or CalmAParams()
    return float(entry) - float(p.disaster_stop_atr_mult) * float(atr)


def stop_risk_dollars(entry: float, stop: float, point_value: float, qty: int = 1) -> float:
    """Risk from the ACTUAL stop distance, not from a multiple of anything.

    `abs(entry - stop) x point_value x qty`. Written to take the stop PRICE rather than the ATR
    and the multiple, so that changing where the stop sits changes the risk — which a formula
    reading `mult x atr` cannot do, and which is the whole distinction the Candidate dataclass
    draws between Calm A and the ATR-proxy sleeves.
    """
    return abs(float(entry) - float(stop)) * float(point_value) * int(qty)


def detect_basket(dfs: Mapping[str, pd.DataFrame], regime,
                  params: CalmAParams | None = None) -> dict:
    p = params or CalmAParams()
    return {inst: detect(dfs[inst], regime, inst, p)
            for inst in p.instruments if inst in dfs}


def to_frame(setups: Sequence[CalmSetup]) -> pd.DataFrame:
    return pd.DataFrame([s.as_row() for s in setups])


# ══════════════════════════════════════════════════════════════════════════════
# The execution contract — Stage 5ZV
# ══════════════════════════════════════════════════════════════════════════════

#: What must be true for SHADOW and PAPER to be the same trade.
#:
#: Stage 5ZU established that this sleeve's decision reads the prior RTH session and today's
#: 09:30 OPEN, and nothing else. Measured across the frozen record: 407 of 421 setups
#: reproduce from a frame TRUNCATED at 09:30 — the fourteen that do not are five sessions
#: missing their own 09:30 bar and nine the rule no longer selects on today's re-adjusted
#: series, neither of which is about truncation.
#:
#: So the decision is computable from CLOSED bars at 09:31:00 and the entry is at 10:00:
#: twenty-nine minutes of slack. That is what makes the original contract TRADABLE, and it is
#: why the entry does not have to move.
#:
#: The alternative was measured too, on the same 416 comparable rows and one consistent read:
#:
#:     entry at 10:00 (the record)   $14,776 total   mean $35.5   win 61.5%
#:     entry at 10:01                $13,606        (-$1,170, -7.9%)   18 trades flip sign
#:     entry at 10:05                $14,726        (-$51, -0.3%)      29 trades flip sign
#:
#: The 10:05 TOTAL is almost unchanged and its per-trade spread is nearly double (stdev $36.7
#: against $20.6), so the aggregate hides the change rather than showing there is none. Moving
#: the entry is a different strategy that happens to sum to a similar number, and it would
#: need its own walk-forward rather than a parameter edit.
@dataclass(frozen=True)
class CalmExecutionContract:
    """Four instants, kept apart because collapsing any two of them is a lie somewhere.

    `entry_reference_time` is the strategy's identity and is asserted equal to
    `CalmAParams.entry_time`. Nothing here may move it.
    """
    #: The first moment a CLOSED bar carries everything the rule reads.
    setup_known_from: str = "09:31"
    #: The intended order must be journalled by here — strictly before it would be sent, so a
    #: restart between the two finds a record rather than a gap.
    intent_journalled_by: str = "09:59"
    #: When a paper order would be SENT. Not when the decision is made.
    order_sent_at: str = "10:00"
    #: The bar whose OPEN the fill is measured against. The strategy's identity.
    entry_reference_time: str = "10:00"
    #: The first moment that OPEN is readable from a CLOSED bar — one minute later, because a
    #: one-minute bar stamped 10:00 closes at 10:01:00. Shadow reads it here; paper does not
    #: wait for it, because paper transacts at the open rather than reading it.
    entry_reference_readable_from: str = "10:01"
    exit_reference_time: str = "15:55"

    def self_check(self) -> list:
        """Structural rules. Returned as a list so a test can assert []."""
        errs = []
        if not (self.setup_known_from < self.intent_journalled_by
                <= self.order_sent_at):
            errs.append("the setup must be known before the intent is journalled, and the "
                        "intent journalled before the order is sent")
        if self.order_sent_at != self.entry_reference_time:
            errs.append("a paper order sent at a different instant from the one its fill is "
                        "measured against is a fill nobody can achieve")
        if self.entry_reference_readable_from <= self.entry_reference_time:
            errs.append("the reference cannot be readable from a closed bar at or before the "
                        "bar it belongs to")
        if self.entry_reference_time != CalmAParams().entry_time:
            errs.append("the reference time and the strategy's entry time disagree — the "
                        "entry price definition has moved")
        if self.exit_reference_time != CalmAParams().exit_time:
            errs.append("the exit reference and the strategy's exit time disagree")
        return errs


#: What SHADOW may assert, and when. The whole point of the split.
#:
#: Before the entry instant a shadow run may record an INTENDED order — the setup, the
#: instrument, the direction, the planned stop and the reference the fill will be measured
#: against. It may NOT record a price, because no trade has happened.
#:
#: After the reference bar has closed it may record what that OPEN was, as the reference the
#: fill WOULD have been measured against. It still may not record a FILL: shadow sends
#: nothing, so nothing filled, and a shadow row claiming one is a claim paper cannot honour.
SHADOW_MAY_RECORD: dict = {
    "before_entry": ("setup", "instrument", "direction", "qty", "stop_rule",
                     "risk_inputs", "entry_reference_time", "intent"),
    "after_reference_bar_closes": ("entry_reference_price", "planned_stop"),
    "never_in_shadow": ("fill_price", "fill_time", "realised_pnl", "slippage"),
}

#: What only PAPER can establish, and therefore what shadow evidence can never stand in for.
PAPER_ONLY_EVIDENCE: tuple = (
    "that an order sent at 10:00:00 was accepted",
    "the actual fill price against the 10:00 OPEN",
    "the slippage between them",
    "that a protective stop rested at the broker afterwards",
)
