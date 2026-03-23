# raits/strategies/trend_follow.py
#
# Trend Following Strategy — "The Runners"
#
# Blueprint ref: Section 4.4
# Active period:    2:00 PM – 3:55 PM ET
# Allowed regimes:  Normal, Stress  (skip Calm — opposite of VWAP MR)
# Max positions:    2 concurrent
# Bar resolution:   5-MINUTE bars (not 1-minute)
#
# ──────────────────────────────────────────────────────────────────────────────
# CORE CONCEPT
# ──────────────────────────────────────────────────────────────────────────────
#
# Late-day momentum continuation. By 2 PM, stocks that have been moving all day
# have established a clear trend. We look for a brief, healthy pullback to the
# 20-period EMA on the 5-minute chart, confirmed by volume declining during the
# pullback (lack of selling pressure) and surging when price resumes (buyers
# returning with conviction).
#
# The exit is a Chandelier trailing stop — not a fixed target. We let the trade
# run as long as the trend continues, with the stop rising (for longs) to lock
# in profits. Hard exit at 3:55 PM to avoid overnight holds.
#
# ──────────────────────────────────────────────────────────────────────────────
# KEY DESIGN DIFFERENCES FROM ORB AND VWAP MR
# ──────────────────────────────────────────────────────────────────────────────
#
# 1. 5-MINUTE BARS: EMA and Chandelier are calculated on 5-min data.
#    The session replayer must aggregate 1-min bars to 5-min bars before
#    calling this strategy (or provide 5-min data directly).
#
# 2. ENTRY ON RESUME BAR CLOSE (not next-bar-open):
#    Because 5-min bars represent 5 minutes of price action, by the time a
#    bar closes we have high confidence in the signal. We enter at close.
#    ORB uses next-bar-open because 1-min bars can have large gaps between
#    close and next open. On 5-min bars this gap is typically negligible.
#
# 3. TRAILING STOP (Chandelier):
#    ORB and VWAP MR have FIXED stops. Trend Following has a TRAILING stop
#    that moves in the direction of the trade. No fixed profit target.
#    The position stays open until stopped out or 3:55 PM.
#
# 4. EMA PERIOD IS THE WFO PARAMETER:
#    Section 7.1: "EMA Period (5-min chart): 20, 30, 50" — one of three
#    hyperparameters optimized during Walk-Forward Optimization.

import logging
import pandas as pd
import numpy as np
from typing import Optional

logger = logging.getLogger('RAITS.TrendFollow')


DEFAULT_CONFIG = {
    # Scanner filters (Section 4.4)
    'near_hod_lod_pct':         0.03,   # within 3% of HOD/LOD (Method A)
    'near_hod_lod_atr_mult':    2.0,    # within 2×ATR of HOD/LOD (Method B)
    'min_volume_ratio':         1.5,    # current volume > 1.5× avg intraday

    # EMA (Section 7.1 — WFO parameter)
    'ema_period':               20,     # WFO grid: 20, 30, 50

    # Entry: EMA proximity
    'ema_proximity_pct':        0.002,  # pullback bar close within 0.2% of EMA

    # Volume pattern
    'resume_volume_surge_mult': 1.3,    # resume bar volume > 1.3× avg

    # Chandelier trailing stop (Section 4.4)
    'chandelier_atr_mult':      3.0,    # stop = highest_high - 3×ATR

    # Regime filter (Section 6.1)
    'allowed_regimes': ['Normal', 'Stress'],  # NOT Calm
}


class TrendFollowStrategy:
    """
    Trend Following strategy — "The Runners".

    Usage (backtesting — bar-by-bar loop from 2:00 PM to 3:55 PM):
        trend = TrendFollowStrategy()

        # Scanner (run at 2:00 PM and periodically)
        watchlist = trend.run_scanner(candidates)

        # Per 5-min bar:
        ema_20 = trend.calculate_ema(all_bars_today, period=20)

        # Check for pullback entry (on prev bar completion)
        signal = trend.generate_signal(
            pullback_bar=bars.iloc[-2],
            resume_bar=bars.iloc[-1],
            ema_20=ema_20, atr=atr,
            hmm_state=hmm_state,
            avg_volume_10=avg_volume_10,
        )

        # If in position: update trailing stop each bar
        current_stop = trend.calculate_chandelier_stop(
            bars_since_entry, atr, direction
        )
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.watchlist: list = []

    def reset(self):
        self.watchlist = []

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 1: run_scanner
    # Blueprint ref: Section 4.4 "Scanner Criteria (Late-Day Momentum Filter)"
    # ──────────────────────────────────────────────────────────────────────────

    def run_scanner(self, candidates: list) -> list:
        """
        Filter for late-day momentum continuation setups.

        The key question: is this stock at an extreme of its day's range
        with enough volume momentum to continue?

        Parameters
        ----------
        candidates : list[dict]
            Each dict must contain:
                ticker              : str
                current_price       : float
                hod                 : float  — high of day
                lod                 : float  — low of day
                atr                 : float  — 14-period ATR
                avg_intraday_volume : float  — 10-bar avg 5-min volume
                current_volume      : float  — current 5-min bar volume
                sector_strength     : float  — positive = sector bullish today

        Returns
        -------
        list[str] — tickers that passed all filters
        """
        accepted = []

        for c in candidates:
            ticker = c['ticker']
            price  = c['current_price']
            hod    = c['hod']
            lod    = c['lod']
            atr    = c['atr']

            # ── Filter 1: Near HOD or LOD ─────────────────────────────────────
            # Two methods — use whichever is MORE permissive (OR logic).
            # This catches both high-priced stocks (where 3% is very wide) and
            # high-volatility stocks (where 2×ATR is more appropriate).

            # Method A: percentage-based
            near_hod_pct = (hod - price) / hod < self.config['near_hod_lod_pct']
            near_lod_pct = (price - lod) / lod < self.config['near_hod_lod_pct']

            # Method B: ATR-based
            atr_mult = self.config['near_hod_lod_atr_mult']
            near_hod_atr = (hod - price) < atr_mult * atr
            near_lod_atr = (price - lod) < atr_mult * atr

            near_hod = near_hod_pct or near_hod_atr
            near_lod = near_lod_pct or near_lod_atr

            if not (near_hod or near_lod):
                logger.debug(f"TrendFollow Scanner REJECT {ticker}: "
                             f"price ${price:.2f} not near HOD ${hod:.2f} or LOD ${lod:.2f}")
                continue

            # ── Filter 2: Volume confirmation ─────────────────────────────────
            # Late-day momentum must be backed by volume, not just price drift.
            vol_ratio = c['current_volume'] / c['avg_intraday_volume']
            if vol_ratio < self.config['min_volume_ratio']:
                logger.debug(f"TrendFollow Scanner REJECT {ticker}: "
                             f"volume {vol_ratio:.1f}× avg "
                             f"(min {self.config['min_volume_ratio']:.1f}×)")
                continue

            # ── Filter 3: Sector strength ─────────────────────────────────────
            # Don't buy a stock near HOD if its whole sector is selling off.
            # Sector momentum confirms the individual stock move isn't an outlier.
            if c['sector_strength'] <= 0:
                logger.debug(f"TrendFollow Scanner REJECT {ticker}: "
                             f"sector_strength={c['sector_strength']:.2f} <= 0")
                continue

            logger.info(f"TrendFollow Scanner ACCEPT {ticker}: "
                        f"near_hod={near_hod}, near_lod={near_lod}, "
                        f"vol_ratio={vol_ratio:.1f}×")
            accepted.append(ticker)

        self.watchlist = accepted
        return accepted

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 2: calculate_ema
    # Blueprint ref: Section 7.1 (EMA period is the WFO parameter: 20/30/50)
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_ema(self, bars: pd.DataFrame, period: int = 20) -> float:
        """
        Compute the current Exponential Moving Average of close prices.

        EMA gives exponentially more weight to recent bars.
        The multiplier is: k = 2 / (period + 1)
        Each new EMA = current_close × k + previous_EMA × (1 - k)

        The period is the sole WFO-optimizable parameter for this strategy
        (Section 7.1 grid: 20, 30, 50).

        Parameters
        ----------
        bars   : pd.DataFrame with 'close' column (5-min bars)
        period : int — EMA lookback period

        Returns
        -------
        float — current EMA value
        """
        closes = bars['close']

        # pandas ewm with adjust=False implements the standard EMA formula.
        # span=period sets the multiplier k = 2/(period+1).
        ema_series = closes.ewm(span=period, adjust=False).mean()
        ema_value  = float(ema_series.iloc[-1])

        logger.debug(f"EMA({period}): ${ema_value:.4f}")
        return ema_value

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 3: calculate_chandelier_stop
    # Blueprint ref: Section 4.4 "Exit Logic — Chandelier Exit"
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_chandelier_stop(self, bars_since_entry: pd.DataFrame,
                                   atr: float,
                                   direction: str) -> float:
        """
        Compute the current Chandelier trailing stop level.

        The Chandelier stop is anchored to the EXTREME of the trade — the
        highest high for longs, lowest low for shorts — then offset by 3×ATR.
        As price makes new extremes, the stop advances. It NEVER retreats.

        LONG:  stop = max(bars_since_entry['high']) - 3.0 × ATR
        SHORT: stop = min(bars_since_entry['low'])  + 3.0 × ATR

        Parameters
        ----------
        bars_since_entry : pd.DataFrame — all 5-min bars from entry bar onward
        atr              : float — 14-period ATR (fixed at entry, not updated)
        direction        : 'LONG' or 'SHORT'

        Returns
        -------
        float — current stop level
        """
        stop_distance = self.config['chandelier_atr_mult'] * atr

        if direction == 'LONG':
            highest_high = float(bars_since_entry['high'].max())
            stop = highest_high - stop_distance
            logger.debug(f"Chandelier LONG: highest_high=${highest_high:.2f}, "
                         f"stop=${stop:.2f} (−{stop_distance:.2f})")
        else:  # SHORT
            lowest_low = float(bars_since_entry['low'].min())
            stop = lowest_low + stop_distance
            logger.debug(f"Chandelier SHORT: lowest_low=${lowest_low:.2f}, "
                         f"stop=${stop:.2f} (+{stop_distance:.2f})")

        return round(stop, 2)

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 4: check_volume_pattern
    # Blueprint ref: Section 4.4 "Entry Logic — Volume pattern confirmation"
    # ──────────────────────────────────────────────────────────────────────────

    def check_volume_pattern(self, pullback_bar: pd.Series,
                              resume_bar: pd.Series,
                              avg_volume: float) -> bool:
        """
        Validate the volume pattern for a pullback entry.

        A healthy pullback has TWO characteristics:
          1. LOW volume on the pullback  — sellers are absent, not aggressive
          2. HIGH volume on the resume   — buyers return with conviction

        This is the "volume declination + surge" pattern that distinguishes
        a temporary pause from a genuine reversal.

        Parameters
        ----------
        pullback_bar : pd.Series — the bar where price touched the EMA
        resume_bar   : pd.Series — the bar where price moved back in trend direction
        avg_volume   : float     — 10-bar average 5-min volume

        Returns
        -------
        bool — True if pattern is valid (enter), False if not
        """
        # Check 1: Volume declined on pullback
        pullback_ok = pullback_bar['volume'] < avg_volume
        if not pullback_ok:
            logger.debug(f"Volume pattern FAIL: pullback volume "
                         f"{pullback_bar['volume']:,} >= avg {avg_volume:,}")
            return False

        # Check 2: Volume surged on resume
        surge_threshold = avg_volume * self.config['resume_volume_surge_mult']
        resume_ok = resume_bar['volume'] > surge_threshold
        if not resume_ok:
            logger.debug(f"Volume pattern FAIL: resume volume "
                         f"{resume_bar['volume']:,} <= threshold {surge_threshold:,.0f}")
            return False

        logger.debug(f"Volume pattern OK: pullback={pullback_bar['volume']:,}, "
                     f"resume={resume_bar['volume']:,}, "
                     f"surge_threshold={surge_threshold:,.0f}")
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 5: generate_signal  (main entry point)
    # Blueprint ref: Section 4.4 "Entry Logic"
    # ──────────────────────────────────────────────────────────────────────────

    def generate_signal(self,
                        pullback_bar: pd.Series,
                        resume_bar: pd.Series,
                        ema_20: float,
                        atr: float,
                        hmm_state: str,
                        avg_volume_10: float) -> Optional[dict]:
        """
        Evaluate a two-bar pullback pattern for a trend continuation entry.

        Called after each 5-min bar completes during 2:00 PM – 3:55 PM.
        The two bars provided are:
          pullback_bar = bar[-2]: price pulled back to EMA on low volume
          resume_bar   = bar[-1]: price resumed trend on high volume

        DECISION SEQUENCE:
          1. Regime gate       → None if Calm
          2. EMA proximity     → pullback_bar.close within 0.2% of ema_20?
          3. Direction         → long (pullback_bar close > ema_20?) or short?
          4. Volume pattern    → declined on pullback, surged on resume?
          5. Compute levels    → entry, initial_stop (Chandelier on resume_bar)
          6. Return signal

        Parameters
        ----------
        pullback_bar  : pd.Series — bar that touched EMA (5-min)
        resume_bar    : pd.Series — bar confirming resumption (5-min)
        ema_20        : float     — current 20-period EMA
        atr           : float     — 14-period ATR
        hmm_state     : str       — 'Calm', 'Normal', or 'Stress'
        avg_volume_10 : float     — 10-bar avg volume for volume pattern check

        Returns
        -------
        dict or None
        """

        # ── Gate 1: Regime — Normal and Stress only ───────────────────────────
        # This is the OPPOSITE of VWAP MR. We need trending conditions.
        # Calm regime = range-bound market = no trend to follow = skip.
        if hmm_state not in self.config['allowed_regimes']:
            logger.debug(f"TrendFollow BLOCKED: regime={hmm_state} "
                         f"not in {self.config['allowed_regimes']}")
            return None

        # ── Gate 2: EMA proximity — did pullback bar touch the EMA? ──────────
        # The pullback_bar's close must be within 0.2% of the 20 EMA.
        # This confirms the pullback reached the moving average support level.
        ema_distance_pct = abs(pullback_bar['close'] - ema_20) / ema_20
        if ema_distance_pct > self.config['ema_proximity_pct']:
            logger.debug(f"TrendFollow BLOCKED: pullback bar close "
                         f"${pullback_bar['close']:.2f} is {ema_distance_pct:.3%} "
                         f"from EMA ${ema_20:.2f} (max 0.2%)")
            return None

        # ── Gate 3: Direction — which side of EMA is price on? ───────────────
        # Pullback close ABOVE EMA → uptrend → looking for LONG
        # Pullback close BELOW EMA → downtrend → looking for SHORT
        if pullback_bar['close'] >= ema_20:
            direction = 'LONG'
        else:
            direction = 'SHORT'

        # ── Gate 4: Volume pattern ────────────────────────────────────────────
        if not self.check_volume_pattern(pullback_bar, resume_bar, avg_volume_10):
            return None

        # ── Compute trade levels ─────────────────────────────────────────────

        # Entry: close of the resume bar
        # On 5-min bars we use the bar close (not next-bar-open) because by
        # the time the bar closes, both conditions are confirmed in one bar.
        entry_price = float(resume_bar['close'])

        # Initial Chandelier stop: based on resume bar alone (first bar in trade)
        resume_as_df = resume_bar.to_frame().T
        resume_as_df.index = pd.DatetimeIndex([pd.Timestamp('2024-01-15 14:05')])
        initial_stop = self.calculate_chandelier_stop(resume_as_df, atr, direction)

        signal = {
            'direction':    direction,
            'entry_price':  entry_price,
            'initial_stop': initial_stop,
            'atr':          atr,     # passed through so replayer can update stop
        }

        logger.info(
            f"TrendFollow SIGNAL: {direction} @ ${entry_price:.2f} | "
            f"initial_stop=${initial_stop:.2f} | "
            f"atr=${atr:.2f} | regime={hmm_state}"
        )

        return signal
