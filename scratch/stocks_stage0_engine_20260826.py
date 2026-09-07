"""scratch/stocks_stage0_engine_20260826.py — the stock route's signal + book. READ-ONLY.

Stage STOCKS-0. No production file is written, no broker is contacted, no order object is
constructed anywhere in this module.

What is REUSED from Track 1, and what is deliberately not
---------------------------------------------------------
Every function that decides *whether a bar is a trade* is imported from the production
package and called, never copied and never monkeypatched:

    raits.strategies.trend_follow.TrendFollowStrategy   the pullback/volume signal itself
    global_index.track1_normal_r4._strategy             its Normal-R4 configuration
    global_index.track1_normal_r4.make_signal_fn        SPY gate + context gate + stop anchor
    global_index.track1_normal_r4.scan_signals          first admitted signal of a session
    global_index.track1_normal_r4._replay               arming, gap fill, max-hold, re-entry
    global_index.track1_normal_filters.R4ContextFilter  prior-day range + entry-bar rvol
    global_index.track1_normal_filters.short_days_from_csv   the SPY D-1 short gate

A second implementation of an entry rule proves nothing about the first, and this rule already
has committed futures artifacts that a re-derivation would silently stop reproducing. So the
port is: same code, different bars.

Three things are NOT reused, each for a stated reason:

1. **`point_value` / `tick` / contract sizing.** A share is not a contract. The engine is run
   at `point_value = 1.0` and `round_turn_cost = 0.0` so its `pnl` column is the raw price
   move of ONE share, and every dollar of cost is applied in the book below, where the share
   count exists and can be audited. Nothing here multiplies a price by a futures multiplier.

2. **The daily ATR the stop is anchored to.** `futures._validated_core.daily_atr_series` is a
   rolling mean ENDING at day D, so its value at D contains D's own high and low. The futures
   route reads it at a 14:00 entry on D. Measured on this cache: the two definitions differ by
   a median of 2.6-3.2% and by up to 71%, and by 7.7% on the widest-range sessions — that is,
   they differ most exactly where the stop matters most. The stock route anchors on the
   session-shifted series. The unshifted one is available as a declared sensitivity.

3. **The R4 context filter's threshold.** `FLOOR_RANGE_P90 = 0.02652` is the p90 of prior-day
   range across R4 **futures** entries on 2018-2024. Index futures and single stocks do not
   have the same range distribution, so transplanting the number transplants a quantile that
   is no longer a quantile. The filter is also documented as R4-only — the `global_nkd` sleeve
   runs the same machinery without it — so a route on different instruments dropping it has
   precedent rather than convenience behind it. Primary config runs without it; the futures
   constant and a stock-derived threshold are both measured as sensitivities.

Equity basis
------------
Position size is a fraction of `initial capital + REALISED P&L`, never of marked-to-market
equity. Sizing off unrealised gains asks the book to spend money that does not exist yet, and
in this repo that has already been measured once: 42% of entries affected, 170 lost outright,
cash at the 10th percentile of 0%. Cash is non-negative by construction here, not by buffer.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from global_index import track1_normal_r4 as NR            # noqa: E402
from global_index import track1_normal_filters as NF       # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════════
#  Cost / sizing / liquidity — every stock-specific assumption, in one place
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StockCostModel:
    """Per-share commission plus a per-side price concession, in basis points.

    `commission_per_share` / `min_commission_per_order`: IBKR US tiered retail shape. It is an
    ASSUMPTION, not a measurement — no broker statement was read for this route.

    `slippage_bps_per_side`: the concession between the price the engine books and the price a
    real order gets. The engine enters at the CLOSE of the resume bar, which is a price that
    has already traded by the time the bar is known, so some concession is structural rather
    than optional. 3 bps is the default and 0/1/3/5/10 are all reported.

    `stop_exit_extra_bps`: a stop exit is a stop-MARKET fill in a moving book, not a limit at
    the stop. It is charged more than an ordinary side. A gap exit is already booked at the
    open, which is the concession, so it is not charged twice.

    `borrow_bps_per_year`: short financing on large-cap easy-to-borrow names. Also an
    assumption; no borrow-rate file exists in this repo.
    """
    commission_per_share: float = 0.005
    min_commission_per_order: float = 1.00
    slippage_bps_per_side: float = 3.0
    stop_exit_extra_bps: float = 5.0
    borrow_bps_per_year: float = 50.0

    def entry_cost(self, shares: int, price: float) -> tuple:
        comm = max(self.min_commission_per_order, shares * self.commission_per_share)
        slip = shares * price * self.slippage_bps_per_side / 1e4
        return comm, slip

    def exit_cost(self, shares: int, price: float, reason: str) -> tuple:
        comm = max(self.min_commission_per_order, shares * self.commission_per_share)
        bps = self.slippage_bps_per_side
        if reason == "CHANDELIER":                 # stop-market, not a limit at the stop
            bps += self.stop_exit_extra_bps
        slip = shares * price * bps / 1e4
        return comm, slip

    def borrow_cost(self, shares: int, price: float, hold_days: int, direction: str) -> float:
        if direction != "SHORT" or hold_days <= 0:
            return 0.0
        return shares * price * (self.borrow_bps_per_year / 1e4) * (hold_days / 252.0)


@dataclass(frozen=True)
class SizingModel:
    """Risk-per-trade sizing with three independent ceilings.

    Three ceilings rather than one because they fail differently: `risk_pct` bounds the loss if
    the stop works, `max_position_notional_pct` bounds the loss if it gaps through, and the
    participation limits bound whether the fill was ever available at all.
    """
    initial_capital: float = 100_000.0
    risk_pct: float = 0.005                    # 0.5% of the equity basis per trade
    max_position_notional_pct: float = 0.20    # one name never exceeds 20% of the basis
    max_gross_notional_pct: float = 1.00       # no leverage across open positions
    max_concurrent_positions: int = 8
    max_pct_of_adv_shares: float = 0.01        # <= 1% of a session's typical share volume
    max_pct_of_entry_bar_volume: float = 0.10  # <= 10% of the 5-minute bar being entered on


@dataclass(frozen=True)
class LiquidityFilter:
    min_price: float = 5.0
    min_adv_usd: float = 20_000_000.0
    min_history_sessions: int = 250            # enough for a 50-EMA and a 20-session median


#: What the engine is handed in place of a futures cost object. `point_value = 1.0` makes its
#: `pnl` column the per-share price move; `round_turn_cost = 0.0` keeps every dollar of cost
#: out of the engine and inside the book, where the share count is visible.
class _UnitCost:
    point_value = 1.0

    @staticmethod
    def round_turn_cost() -> float:
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
#  Config identity — the stock route's answer to route_params.params_hash
# ═══════════════════════════════════════════════════════════════════════════════

import hashlib                                              # noqa: E402
import json                                                 # noqa: E402

STOCK_SCHEMA = "stocks_route_params/1"

#: Every input that changes which position the bars produce, or the size that would be sent.
#: Same discipline as `global_index/route_params.FIELDS` and deliberately NOT the same list:
#: `point_value`, `tick` and `tradable_symbol` are futures answers to a futures question, and
#: the equity route replaces them with the things that actually decide a share count.
STOCK_FIELDS = (
    "universe_definition", "universe_size", "universe_is_point_in_time",
    "data_source_identity", "bar_interval", "adjusted", "session", "timezone",
    "calendar_source",
    "ema_period", "max_hold_days", "entry_window", "signal_rule",
    "stop_basis", "stop_multiple", "stop_anchor", "ratchet", "arm_hour", "arm_timezone",
    "atr_basis", "fill_law",
    "regime_model", "regime_fit_end", "regime_label_lag_days", "regime_csv_identity",
    "spy_short_filter", "spy_short_lookback", "spy_short_lag_days",
    "r4_context_filter", "r4_range_threshold", "r4_range_derivation_window",
    "r4_rel_volume_max",
    "execution_model", "sizing_basis", "risk_pct", "max_position_notional_pct",
    "max_gross_notional_pct", "max_concurrent_positions",
    "commission_per_share", "min_commission_per_order", "slippage_bps_per_side",
    "stop_exit_extra_bps", "borrow_bps_per_year",
    "min_price", "min_adv_usd", "min_history_sessions",
    "max_pct_of_adv_shares", "max_pct_of_entry_bar_volume",
    "initial_capital", "window",
)


def _render(v) -> str:
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return "{:.10g}".format(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(_render(x) for x in v) + "]"
    return str(v)


def config_identity(cfg: dict) -> tuple:
    missing = [f for f in STOCK_FIELDS if f not in cfg]
    if missing:
        raise ValueError(
            "stocks route config missing required field(s) {}. An absent field is refused, "
            "not defaulted — two configs must not hash alike because one forgot to "
            "say.".format(missing))
    norm = {f: _render(cfg[f]) for f in STOCK_FIELDS}
    readable = ";".join("{}={}".format(f, norm[f]) for f in STOCK_FIELDS)
    payload = json.dumps({"schema": STOCK_SCHEMA, "fields": norm},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return readable, "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
#  Signal generation — production functions, composed
# ═══════════════════════════════════════════════════════════════════════════════

def _recording_signal_fn(inner):
    """Wrap a `signal_for` so every admitted signal's stop is captured by bar timestamp.

    The engine's trade rows carry entry, exit, points and reason but not the stop, and the
    stop is what the share count is computed from. Recomputing it afterwards from the ATR
    would be a second implementation of the rule that produced it — including its "ATR
    missing, keep the original stop" branch — so the value is taken from the function that
    actually returned it.
    """
    seen: dict = {}

    def wrapped(prev_bar, resume_bar, ema, atr, regime, avgv):
        sig = inner(prev_bar, resume_bar, ema, atr, regime, avgv)
        if sig:
            seen[pd.Timestamp(resume_bar.name)] = (float(sig["entry_price"]),
                                                   float(sig["initial_stop"]),
                                                   str(sig["direction"]))
        return sig

    wrapped.seen = seen
    return wrapped


def run_symbol(df: pd.DataFrame, labels, params: NR.NormalR4Params, *,
               short_days: set, datr: pd.Series,
               context_filter: "NF.R4ContextFilter | None") -> tuple:
    """One symbol, through the production decision path, on a supplied causal ATR.

    Returns `(trades, stops_by_bar_ts, filter_stats)`.

    `_cache_for` is called for its per-day structures — the 5-minute frames, the high/low/open
    arrays and the gap flags — and its `datr` is then replaced by the causal series. That
    replacement is made on a COPY of the returned dict for the reason the function's own
    docstring gives about `_swing_cache`: the cache hands back a live object, and rewriting it
    in place would change what every other reader of that frame sees.
    """
    cache = dict(NR._cache_for(df, params))
    cache["datr"] = datr
    strat = NR._strategy(params)
    signal_for = _recording_signal_fn(
        NR.make_signal_fn(strat, params, datr, short_days=short_days, context=context_filter))
    signals = NR.scan_signals(strat, cache, labels, params, signal_for)
    trades = NR._replay(strat, labels, _UnitCost(), params,
                        cache=cache, signals=signals, signal_for=signal_for)
    stats = context_filter.stats() if context_filter is not None else None
    return trades, signal_for.seen, stats


def clear_engine_cache() -> None:
    """Drop `_swing_cache` between symbols.

    Not hygiene. The cache is keyed by `id(df)`, and a freed frame's address is recycled: leave
    entries behind and one symbol's bars are served to another with no error, only wrong
    numbers. The function's own docstring says callers that build frames in a loop must clear
    it, and this is such a caller.
    """
    from futures import _validated_core as VC
    VC._SWING_CACHE.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  The book — sizing, liquidity admission, costs, ledger
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LedgerRow:
    symbol: str = ""
    candidate_ts: str = ""
    entry_ts: str = ""
    exit_ts: str = ""
    entry_day: str = ""
    exit_day: str = ""
    direction: str = ""
    regime: str = ""
    entry_price: float = 0.0          # engine's booked price (2dp) — the P&L basis
    entry_price_signal: float = 0.0   # the signal's unrounded price — the sizing basis
    exit_price: float = 0.0
    stop_price: float = float("nan")
    stop_distance: float = float("nan")
    stop_distance_pct: float = float("nan")
    daily_atr: float = float("nan")
    prev_day_range_pct: float = float("nan")
    entry_bar_rvol: float = float("nan")
    adv_usd: float = float("nan")
    entry_bar_volume: float = float("nan")
    shares: int = 0
    notional: float = 0.0
    equity_basis_at_entry: float = 0.0
    risk_budget_usd: float = 0.0
    gross_pnl: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0
    borrow: float = 0.0
    total_cost: float = 0.0
    net_pnl: float = 0.0
    hold_days: int = 0
    entry_reason: str = ""
    exit_reason: str = ""
    status: str = ""            # TAKEN | REJECTED
    reject_reason: str = ""


def _size(entry: float, dist: float, equity_basis: float, sizing: SizingModel,
          adv_usd: float, bar_volume: float) -> tuple:
    """`(shares, reject_reason)`. Every ceiling that binds is named, not silently applied.

    `dist` is the RULE's stop distance — `2.0 x daily ATR` measured against the signal's own
    unrounded price — not `|booked entry - stop|`. The two differ by up to half a cent because
    the engine books entry at two decimals, and sizing on the rounded pair reproduces the rule
    on only 58% of rows.
    """
    if not np.isfinite(dist) or dist <= 0:
        return 0, "stop_distance_not_positive"
    risk = sizing.risk_pct * equity_basis
    shares = int(math.floor(risk / dist))
    if shares < 1:
        return 0, "risk_budget_below_one_share"

    cap_notional = int(math.floor(sizing.max_position_notional_pct * equity_basis / entry))
    if cap_notional < shares:
        shares = cap_notional
        binding = "position_notional_cap"
    else:
        binding = ""

    if np.isfinite(adv_usd) and adv_usd > 0:
        adv_shares = adv_usd / entry
        cap_adv = int(math.floor(sizing.max_pct_of_adv_shares * adv_shares))
        if cap_adv < shares:
            shares, binding = cap_adv, "adv_participation_cap"

    if np.isfinite(bar_volume) and bar_volume > 0:
        cap_bar = int(math.floor(sizing.max_pct_of_entry_bar_volume * bar_volume))
        if cap_bar < shares:
            shares, binding = cap_bar, "entry_bar_participation_cap"

    if shares < 1:
        return 0, binding or "size_floored_to_zero"
    return shares, binding


def build_book(candidates: list, sizing: SizingModel, cost: StockCostModel) -> tuple:
    """Walk candidates in entry-time order and book what the caps admit.

    Candidates are sorted by entry timestamp, and same-instant ties by stop distance
    descending. The tie-break is there to be DETERMINISTIC, not to mirror Track 1's economics,
    and the difference is worth stating rather than implying: `Track1Book.process_instant`
    sorts by risk because its quantity is fixed and its risk therefore varies, while here the
    risk dollars are identical across candidates by construction — `risk_pct x basis` — and it
    is the quantity that varies. So the ordering only decides who wins a contested slot; it
    carries none of the meaning it carries there.

    Realised-P&L accounting: a position's P&L lands in the basis at its EXIT, not at its
    entry, so the basis at any entry contains only money that has actually been booked.
    """
    cands = sorted(candidates, key=lambda c: (c["entry_ts"], -c["risk_rank"]))
    equity_basis = sizing.initial_capital
    realised = 0.0
    open_pos: list = []          # (exit_ts, symbol, net_pnl, notional)
    rows: list = []
    equity_curve: list = []

    def _settle_until(ts):
        nonlocal realised, equity_basis
        still = []
        for p in sorted(open_pos, key=lambda x: x[0]):
            if p[0] <= ts:
                realised += p[2]
                equity_basis = sizing.initial_capital + realised
                equity_curve.append((p[0], equity_basis))
            else:
                still.append(p)
        open_pos[:] = still

    for c in cands:
        ets = c["entry_ts"]
        _settle_until(ets)

        row = LedgerRow(**{k: v for k, v in c.items() if k in LedgerRow.__annotations__})
        row.equity_basis_at_entry = round(equity_basis, 2)
        row.risk_budget_usd = round(sizing.risk_pct * equity_basis, 2)

        if c.get("liquidity_reject"):
            row.status, row.reject_reason = "REJECTED", c["liquidity_reject"]
            rows.append(row)
            continue

        if len(open_pos) >= sizing.max_concurrent_positions:
            row.status, row.reject_reason = "REJECTED", "max_concurrent_positions"
            rows.append(row)
            continue

        shares, binding = _size(c["entry_price"], c["stop_distance"], equity_basis, sizing,
                                c["adv_usd"], c["entry_bar_volume"])
        if shares < 1:
            row.status, row.reject_reason = "REJECTED", binding
            rows.append(row)
            continue

        gross_open = sum(p[3] for p in open_pos)
        notional = shares * c["entry_price"]
        if gross_open + notional > sizing.max_gross_notional_pct * equity_basis:
            room = sizing.max_gross_notional_pct * equity_basis - gross_open
            shares = int(math.floor(max(room, 0.0) / c["entry_price"]))
            if shares < 1:
                row.status, row.reject_reason = "REJECTED", "gross_notional_cap"
                rows.append(row)
                continue
            notional = shares * c["entry_price"]
            binding = "gross_notional_cap"

        ec, es = cost.entry_cost(shares, c["entry_price"])
        xc, xs = cost.exit_cost(shares, c["exit_price"], c["exit_reason"])
        borrow = cost.borrow_cost(shares, c["entry_price"], c["hold_days"], c["direction"])
        gross = c["points"] * shares
        total_cost = ec + es + xc + xs + borrow
        net = gross - total_cost

        row.shares = shares
        row.notional = round(notional, 2)
        row.gross_pnl = round(gross, 2)
        row.commission = round(ec + xc, 2)
        row.slippage = round(es + xs, 2)
        row.borrow = round(borrow, 2)
        row.total_cost = round(total_cost, 2)
        row.net_pnl = round(net, 2)
        row.status = "TAKEN"
        row.reject_reason = binding
        rows.append(row)
        open_pos.append((c["exit_ts"], c["symbol"], net, notional))

    _settle_until(pd.Timestamp.max)
    return rows, equity_curve
