# raits/backtester/orb_session.py
#
# ORB single-day session replayer.
# Blueprint ref: Sections 4.2, 5.3, 1.0 ("Entry Timing" note)
#
# WHAT THIS DOES
# --------------
# Takes a DataFrame of 1-minute bars for ONE trading day and replays them
# in time order, running the full ORB workflow:
#
#   9:30      Opening print — tracked but excluded from OR
#   9:31–9:34 OR formation begins (scanner not run yet)
#   9:35      Scanner fires — builds watchlist from pre-9:35 data
#   9:35–9:45 OR formation continues
#   9:46      First monitoring bar — check for breakout signal
#   9:47      If signal fired at 9:46, ENTER at THIS bar's open  ← key rule
#   9:47–10:14 Hold position, check target and stop each bar
#   10:15     Hard exit if still open (time-based cutoff)
#
# THE KEY RULE: NEXT-BAR-OPEN ENTRY
# -----------------------------------
# When generate_signal() returns a signal on bar T (e.g., 9:46),
# the entry price is bar T+1's OPEN (e.g., 9:47 open).
#
# This is how live trading works: you see the 9:46 bar complete, you send
# your order, and you fill when the 9:47 bar opens. The backtest MUST
# mirror this exactly or it will show impossible fills and overstated returns.
#
# SCOPE
# -----
# This replayer handles ONE ticker for ONE day. The future multi-strategy,
# multi-ticker backtester (Phase 1D) will call this per ticker per day and
# aggregate results. Keeping scope small here makes integration testing
# tractable and bugs easy to isolate.

import logging
import pandas as pd
from typing import Optional

from raits.strategies.orb import ORBStrategy
from raits.risk.position_sizer import PositionSizer

logger = logging.getLogger('RAITS.ORBSession')

# Time constants (as strings matching DataFrame index format HH:MM)
SCANNER_TIME    = '09:35'
OR_START_TIME   = '09:31'    # 30 seconds after open, effectively the 9:31 bar
OR_END_TIME     = '09:45'    # last bar of OR window
MONITOR_START   = '09:46'    # first bar of breakout monitoring window
HARD_CUTOFF     = '10:15'    # any open position is force-closed at this bar


def run_orb_session(bars: pd.DataFrame, context: dict) -> list:
    """
    Replay one trading day bar by bar and return all ORB trades executed.

    Parameters
    ----------
    bars : pd.DataFrame
        1-minute OHLCV bars with a DatetimeIndex.
        Should cover at least 9:30–10:15. Extra bars (post-10:15) are ignored.
        Columns: open, high, low, close, volume

    context : dict
        Everything the session needs that isn't in the bars:
            ticker               : str
            prev_close           : float
            premarket_volume     : int
            avg_daily_volume     : int
            opening_5min_volume  : int   — actual 9:30–9:35 volume
            atr                  : float — 14-day ATR
            vwap                 : float — VWAP at monitoring time (precomputed)
            hist_avg_vol_9_46    : float — historical avg volume for 9:46 bar
            hmm_state            : str   — 'Calm', 'Normal', or 'Stress'
            account_equity       : float
            strategy_stats       : dict  — win_rate, avg_win, avg_loss

    Returns
    -------
    list[dict]
        One dict per completed trade. Empty list if no trades.
        Each trade dict contains:
            ticker, direction, entry_price, entry_time,
            exit_price, exit_time, exit_reason,
            shares, pnl, or_high, or_low
    """
    ticker    = context['ticker']
    hmm_state = context['hmm_state']

    strategy = ORBStrategy()
    sizer    = PositionSizer(account_equity=context['account_equity'])
    trades   = []

    # ── Step 1: Scanner at 9:35 ──────────────────────────────────────────────
    # The scanner filters the universe. In single-ticker mode we just check
    # whether this one ticker passes the scanner criteria.
    candidates = [{
        'ticker':              ticker,
        'prev_close':          context['prev_close'],
        'open_price':          bars.iloc[0]['open'],   # use first bar's open as open price
        'premarket_volume':    context['premarket_volume'],
        'avg_daily_volume':    context['avg_daily_volume'],
        'opening_5min_volume': context['opening_5min_volume'],
    }]
    watchlist = strategy.run_scanner(candidates)

    if ticker not in watchlist:
        logger.info(f"{ticker}: Scanner rejected — no ORB candidates today")
        return []

    # ── Step 2: Calculate Opening Range from 9:31–9:45 bars ─────────────────
    # Extract OR bars: everything with time HH:MM between OR_START and OR_END.
    # We use the string time portion of the index for filtering.
    bar_times = bars.index.strftime('%H:%M')
    or_mask   = (bar_times >= OR_START_TIME) & (bar_times <= OR_END_TIME)
    or_bars   = bars[or_mask]

    if len(or_bars) == 0:
        logger.warning(f"{ticker}: No OR bars found in {OR_START_TIME}–{OR_END_TIME}")
        return []

    or_high, or_low, or_status = strategy.calculate_opening_range(
        or_bars, context['atr']
    )

    if or_status != 'VALID':
        logger.info(f"{ticker}: OR rejected — status={or_status}")
        return []

    logger.info(f"{ticker}: OR established — high=${or_high:.2f}, low=${or_low:.2f}")

    # ── Step 3: Monitor 9:46–10:15 bars for breakout ─────────────────────────
    monitor_mask  = (bar_times >= MONITOR_START) & (bar_times <= HARD_CUTOFF)
    monitor_bars  = bars[monitor_mask]

    if len(monitor_bars) == 0:
        logger.warning(f"{ticker}: No monitoring bars found after {MONITOR_START}")
        return []

    # Convert to a list of (timestamp, row) pairs so we can look ahead by index
    monitor_list = list(monitor_bars.iterrows())

    # State: are we currently in a trade?
    position: Optional[dict] = None

    for i, (ts, candle) in enumerate(monitor_list):
        bar_time = ts.strftime('%H:%M')

        # ── If in a position: check exit conditions first ──────────────────
        if position is not None:
            exit_result = _check_exit(candle, bar_time, position)
            if exit_result:
                trades.append(_close_trade(position, exit_result, ticker))
                position = None
                # After a trade closes we stop for today (1 trade per session
                # for integration testing; multi-trade logic comes in Phase 1D)
                break
            continue  # still holding — skip signal logic

        # ── Not in a position: check for new signal ─────────────────────────

        # Hard cutoff: don't enter new positions at or after 10:15.
        # (The 10:15 bar itself is used for time-exits on open positions,
        # but we never ENTER on it.)
        if bar_time >= HARD_CUTOFF:
            break

        # Check for signal on this bar
        rvol = strategy.calculate_intraday_rvol(
            int(candle['volume']), context['hist_avg_vol_9_46']
        )
        signal = strategy.generate_signal(
            candle=candle,
            or_high=or_high,
            or_low=or_low,
            vwap=context['vwap'],
            rvol=rvol,
            hmm_state=hmm_state,
        )

        if signal is None:
            continue

        # ── Signal fired — look ahead to NEXT bar for entry ─────────────────
        # This is the core of the next-bar-open rule.
        # We need the bar AFTER the signal bar (index i+1 in monitor_list).
        if i + 1 >= len(monitor_list):
            # Signal fired on the very last monitoring bar — no next bar.
            # Cannot enter. Skip.
            logger.info(f"{ticker}: Signal on last bar {bar_time} — no next bar, skip")
            continue

        next_ts, next_bar = monitor_list[i + 1]
        entry_price = next_bar['open']    # ← THE KEY RULE: next bar's OPEN
        entry_time  = next_ts.strftime('%H:%M')

        # ── Size the position ────────────────────────────────────────────────
        size_result = sizer.calculate(
            entry_price=entry_price,
            stop_loss=signal['stop_loss'],
            strategy_stats=context['strategy_stats'],
        )

        if size_result is None:
            logger.info(f"{ticker}: Signal at {bar_time} — position sizer rejected")
            continue

        # ── Recompute target from actual fill price ──────────────────────────
        # generate_signal() computed the target from the signal candle close.
        # The actual fill is at the NEXT bar open. Target must be recomputed
        # from the real fill price — otherwise we aim at a phantom level.
        actual_risk = abs(entry_price - signal['stop_loss'])
        if signal['direction'] == 'LONG':
            actual_target = round(entry_price + 2.0 * actual_risk, 2)
        else:
            actual_target = round(entry_price - 2.0 * actual_risk, 2)

        # ── Open position ────────────────────────────────────────────────────
        position = {
            'direction':   signal['direction'],
            'entry_price': entry_price,
            'entry_time':  entry_time,
            'stop_loss':   signal['stop_loss'],
            'target':      actual_target,
            'shares':      size_result['shares'],
            'or_high':     or_high,
            'or_low':      or_low,
        }

        logger.info(
            f"{ticker}: ENTER {signal['direction']} @ ${entry_price:.2f} "
            f"(signal bar {bar_time}, entry bar {entry_time}) | "
            f"stop=${signal['stop_loss']:.2f} | target=${actual_target:.2f} | "
            f"shares={size_result['shares']} | regime={hmm_state}"
        )

    # ── If still in position at end of loop: time exit ───────────────────────
    if position is not None:
        # Find the 10:15 bar for the time exit price
        cutoff_mask = bar_times == HARD_CUTOFF
        cutoff_bars = bars[cutoff_mask]

        if len(cutoff_bars) > 0:
            exit_price = float(cutoff_bars.iloc[0]['open'])
        else:
            # No 10:15 bar in data — use last available bar
            exit_price = float(bars.iloc[-1]['close'])

        exit_result = {
            'exit_price':  exit_price,
            'exit_time':   HARD_CUTOFF,
            'exit_reason': 'TIME_EXIT',
        }
        trades.append(_close_trade(position, exit_result, ticker))

    return trades


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _check_exit(candle: pd.Series, bar_time: str,
                position: dict) -> Optional[dict]:
    """
    Check whether the current bar triggers a target, stop, or time exit.

    For a LONG position:
        Target hit: bar high   >= target     → exit at target price
        Stop hit:   bar low    <= stop_loss  → exit at stop price
        Time exit:  bar_time   >= '10:15'    → exit at bar open

    For a SHORT position:
        Target hit: bar low    <= target     → exit at target price
        Stop hit:   bar high   >= stop_loss  → exit at stop price
        Time exit:  bar_time   >= '10:15'    → exit at bar open

    Returns exit dict if an exit condition was met, None otherwise.

    Exit price is the LEVEL (target or stop), not the bar's extreme.
    In live trading you'd have a limit order sitting at the target and
    a stop order sitting at the stop — you get exactly those prices
    (assuming sufficient liquidity, which is reasonable for our universe).
    """
    direction = position['direction']
    target    = position['target']
    stop      = position['stop_loss']

    # Time exit takes priority — check first
    if bar_time >= HARD_CUTOFF:
        return {
            'exit_price':  float(candle['open']),
            'exit_time':   bar_time,
            'exit_reason': 'TIME_EXIT',
        }

    if direction == 'LONG':
        if candle['high'] >= target:
            return {'exit_price': target, 'exit_time': bar_time, 'exit_reason': 'TARGET_HIT'}
        if candle['low'] <= stop:
            return {'exit_price': stop,   'exit_time': bar_time, 'exit_reason': 'STOP_HIT'}

    else:  # SHORT
        if candle['low'] <= target:
            return {'exit_price': target, 'exit_time': bar_time, 'exit_reason': 'TARGET_HIT'}
        if candle['high'] >= stop:
            return {'exit_price': stop,   'exit_time': bar_time, 'exit_reason': 'STOP_HIT'}

    return None


def _close_trade(position: dict, exit_result: dict, ticker: str) -> dict:
    """
    Build the final trade record from open position + exit result.

    P&L:
        LONG:  (exit_price - entry_price) × shares
        SHORT: (entry_price - exit_price) × shares
    """
    direction   = position['direction']
    entry_price = position['entry_price']
    exit_price  = exit_result['exit_price']
    shares      = position['shares']

    if direction == 'LONG':
        pnl = (exit_price - entry_price) * shares
    else:
        pnl = (entry_price - exit_price) * shares

    trade = {
        'ticker':      ticker,
        'direction':   direction,
        'entry_price': entry_price,
        'entry_time':  position['entry_time'],
        'exit_price':  exit_price,
        'exit_time':   exit_result['exit_time'],
        'exit_reason': exit_result['exit_reason'],
        'shares':      shares,
        'pnl':         round(pnl, 2),
        'or_high':     position['or_high'],
        'or_low':      position['or_low'],
    }

    logger.info(
        f"{ticker}: EXIT {direction} @ ${exit_price:.2f} "
        f"({exit_result['exit_reason']}) | "
        f"entry=${entry_price:.2f} | pnl=${pnl:.2f} | "
        f"shares={shares}"
    )

    return trade
