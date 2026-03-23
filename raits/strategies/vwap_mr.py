# raits/strategies/vwap_mr.py
#
# VWAP Mean Reversion Strategy — "The Grinders"
#
# Blueprint ref: Section 4.3
# Active period:   10:15 AM – 2:00 PM ET
# Allowed regimes: Calm ONLY  (most restrictive — blocks Normal and Stress)
# Max positions:   3 concurrent
#
# ──────────────────────────────────────────────────────────────────────────────
# CORE CONCEPT
# ──────────────────────────────────────────────────────────────────────────────
#
# ORB bets that a move CONTINUES. VWAP MR bets that a move REVERSES.
#
# The edge: in a calm, range-bound market, stocks oscillate around their
# Volume Weighted Average Price (VWAP) — fair value for the day. When price
# stretches too far (touches a Bollinger Band), rubber-band physics take over:
# the stock tends to snap back toward VWAP.
#
# We fade the extremes. SHORT when price pokes above the upper band and
# closes back inside (sellers pushed it back). LONG when price dips below
# the lower band and closes back inside (buyers stepped in).
#
# ──────────────────────────────────────────────────────────────────────────────
# SIGNAL CONFIRMATION TIMING (critical — differs from ORB)
# ──────────────────────────────────────────────────────────────────────────────
#
# ORB:     Signal fires at bar T close  → entry at bar T+1 open
# VWAP MR: Confirmation at bar T-1 close → entry at bar T open
#
# The VWAP MR confirmation requires BOTH conditions to be true of bar T-1:
#   For SHORT: prev_bar.high >= bb_upper  AND  prev_bar.close < bb_upper
#   For LONG:  prev_bar.low  <= bb_lower  AND  prev_bar.close > bb_lower
#
# We observe this when bar T-1 COMPLETES. Bar T is already opening.
# Entry is at bar T's open — the current bar's first print.
#
# ──────────────────────────────────────────────────────────────────────────────
# DESIGN CONSISTENCY WITH ORB
# ──────────────────────────────────────────────────────────────────────────────
#
# Same architectural decisions as ORBStrategy:
#   - hmm_state passed in as string — not fetched internally
#   - Class (not functions) — holds intra-session state if needed
#   - Indicators (BB, VWAP, ATR) computed upstream, passed as arguments
#   - generate_signal() is pure: given inputs → output, no side effects

import logging
import pandas as pd
import numpy as np
from typing import Optional

logger = logging.getLogger('RAITS.VWAP_MR')


DEFAULT_CONFIG = {
    # Scanner filters (Section 4.3)
    'max_adx':                  25.0,   # must be trendless (ADX < 25)
    'max_sma_distance_pct':      0.03,  # price within ±3% of 20-period SMA
    'max_volume_spike_ratio':    3.0,   # reject if volume > 3× avg daily
    # atr_current must be < atr_5bars_ago (decreasing volatility)
    # earnings check: passed in as bool via has_earnings field

    # Bollinger Band parameters (Section 7.1 — std_dev is the WFO parameter)
    'bb_period':    20,
    'bb_std_dev':    2.0,   # WFO grid: 1.5, 2.0, 2.5 — default 2.0

    # Entry / exit (Section 4.3)
    'stop_atr_multiple':  1.5,   # stop = entry ± 1.5 × ATR

    # Regime filter (Section 6.1)
    'allowed_regimes': ['Calm'],   # ONLY Calm — most restrictive strategy
}


class VWAPMRStrategy:
    """
    VWAP Mean Reversion strategy — "The Grinders".

    Usage (backtesting — bar-by-bar loop from 10:15 AM to 2:00 PM):
        vwap_mr = VWAPMRStrategy()

        # Real-time scanner check (per candidate, continuously)
        watchlist = vwap_mr.run_scanner(candidates)

        # Per bar (for each ticker in watchlist):
        bb_upper, bb_middle, bb_lower = vwap_mr.calculate_bollinger_bands(
            bars[:-1], period=20, std_dev=2.0
        )
        vwap = vwap_mr.calculate_vwap(bars)

        # Generate signal (check prev bar against bands)
        signal = vwap_mr.generate_signal(
            prev_bar=bars.iloc[-2],
            entry_bar=bars.iloc[-1],
            bb_upper=bb_upper, bb_lower=bb_lower,
            vwap=vwap, atr=atr,
            hmm_state=hmm_state,
        )
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self.watchlist: list = []

    def reset(self):
        self.watchlist = []

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 1: run_scanner
    # Blueprint ref: Section 4.3 "Scanner Criteria (Real-Time Filter)"
    # ──────────────────────────────────────────────────────────────────────────

    def run_scanner(self, candidates: list) -> list:
        """
        Filter a universe of stocks to those suitable for mean reversion.

        Unlike ORB (run once at 9:35 AM), this scanner runs continuously
        throughout the 10:15 AM – 2:00 PM window. A stock can enter or
        leave the watchlist as conditions change.

        Parameters
        ----------
        candidates : list[dict]
            Each dict must contain:
                ticker           : str
                adx              : float  — 14-period ADX
                sma_20           : float  — 20-period SMA of close
                current_price    : float
                current_volume   : float  — current bar's volume
                avg_daily_volume : float  — 20-day average daily volume
                atr_current      : float  — current 14-period ATR
                atr_5bars_ago    : float  — ATR 5 bars ago
                has_earnings     : bool   — earnings today or yesterday AH

        Returns
        -------
        list[str] — tickers that passed all filters
        """
        accepted = []

        for c in candidates:
            ticker = c['ticker']

            # ── Filter 1: ADX trendless check ─────────────────────────────────
            # ADX measures trend strength. Below 25 = market oscillating, not
            # trending. Above 25 = stock has directional momentum — fading it
            # means trading against the trend, which loses.
            if c['adx'] >= self.config['max_adx']:
                logger.debug(f"VWAP_MR Scanner REJECT {ticker}: "
                             f"ADX={c['adx']:.1f} >= {self.config['max_adx']}")
                continue

            # ── Filter 2: SMA proximity (ADX lag protection #1) ───────────────
            # ADX uses a 14-period lookback. A stock can begin a violent move
            # while ADX still reads low — the indicator hasn't caught up yet.
            # Requiring price within ±3% of the 20-period SMA confirms the
            # stock is genuinely oscillating around a central value.
            distance_pct = abs(c['current_price'] - c['sma_20']) / c['sma_20']
            if distance_pct > self.config['max_sma_distance_pct']:
                logger.debug(f"VWAP_MR Scanner REJECT {ticker}: "
                             f"price {distance_pct:.1%} from SMA "
                             f"(max {self.config['max_sma_distance_pct']:.0%})")
                continue

            # ── Filter 3: Volume spike (ADX lag protection #2) ────────────────
            # Unusual volume = something is happening (news, FDA, analyst action).
            # Even if price hasn't moved far yet (passing the SMA filter),
            # abnormal volume is a warning sign that a large move is imminent.
            volume_ratio = c['current_volume'] / c['avg_daily_volume']
            if volume_ratio > self.config['max_volume_spike_ratio']:
                logger.debug(f"VWAP_MR Scanner REJECT {ticker}: "
                             f"volume {volume_ratio:.1f}× avg "
                             f"(max {self.config['max_volume_spike_ratio']:.1f}×)")
                continue

            # ── Filter 4: ATR decreasing (volatility compressing) ─────────────
            # Mean reversion works best when volatility is contracting — the
            # market is settling, not expanding. If ATR is rising, the stock
            # may be beginning a breakout (wrong setup for reversion).
            if c['atr_current'] >= c['atr_5bars_ago']:
                logger.debug(f"VWAP_MR Scanner REJECT {ticker}: "
                             f"ATR not decreasing "
                             f"({c['atr_current']:.3f} >= {c['atr_5bars_ago']:.3f})")
                continue

            # ── Filter 5: Earnings calendar ───────────────────────────────────
            # Earnings = guaranteed large move in unpredictable direction.
            # Mean reversion on an earnings day = gambling.
            if c['has_earnings']:
                logger.debug(f"VWAP_MR Scanner REJECT {ticker}: earnings today/yesterday AH")
                continue

            logger.info(f"VWAP_MR Scanner ACCEPT {ticker}: "
                        f"ADX={c['adx']:.1f}, distance={distance_pct:.1%}, "
                        f"vol_ratio={volume_ratio:.1f}×")
            accepted.append(ticker)

        self.watchlist = accepted
        return accepted

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 2: calculate_bollinger_bands
    # Blueprint ref: Section 4.3 "Entry Logic" + Section 7.1 (WFO parameter)
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_bollinger_bands(self, bars: pd.DataFrame,
                                   period: int = 20,
                                   std_dev: float = 2.0):
        """
        Compute Bollinger Bands from the close prices of bars.

        The std_dev parameter (2.0 default) is one of the three WFO-optimizable
        parameters per Section 7.1. The grid is: 1.5σ, 2.0σ, 2.5σ.

        Parameters
        ----------
        bars    : pd.DataFrame with 'close' column
        period  : int   — rolling window (default 20)
        std_dev : float — band width in standard deviations (default 2.0)

        Returns
        -------
        tuple: (bb_upper, bb_middle, bb_lower) as floats
            bb_middle = rolling mean of close (last value)
            bb_upper  = bb_middle + std_dev × rolling_std
            bb_lower  = bb_middle - std_dev × rolling_std
        """
        closes = bars['close']

        # ddof=1 uses the sample standard deviation (N-1 denominator),
        # consistent with how most charting platforms calculate BB.
        rolling_mean = closes.rolling(window=period).mean()
        rolling_std  = closes.rolling(window=period).std(ddof=1)

        # Take the last value — the current BB level
        bb_middle = float(rolling_mean.iloc[-1])
        band_width = float(rolling_std.iloc[-1]) * std_dev

        bb_upper = bb_middle + band_width
        bb_lower = bb_middle - band_width

        logger.debug(f"BB({period}, {std_dev}σ): "
                     f"upper=${bb_upper:.4f}, middle=${bb_middle:.4f}, "
                     f"lower=${bb_lower:.4f}")

        return bb_upper, bb_middle, bb_lower

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 3: calculate_vwap
    # Blueprint ref: Section 4.3 "Exit Logic — Target: VWAP Line"
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_vwap(self, bars: pd.DataFrame) -> float:
        """
        Compute the Volume Weighted Average Price from session open.

        VWAP = Σ(typical_price × volume) / Σ(volume)
        typical_price = (high + low + close) / 3

        This is the TARGET for mean reversion trades — where the stock
        "should" be trading given the day's volume distribution.

        Parameters
        ----------
        bars : pd.DataFrame with 'high', 'low', 'close', 'volume' columns

        Returns
        -------
        float — current VWAP
        """
        typical_price = (bars['high'] + bars['low'] + bars['close']) / 3.0
        total_tpv    = (typical_price * bars['volume']).sum()
        total_volume  = bars['volume'].sum()

        if total_volume == 0:
            logger.warning("VWAP: total volume is zero — returning typical price mean")
            return float(typical_price.mean())

        vwap = total_tpv / total_volume
        logger.debug(f"VWAP: ${vwap:.4f} "
                     f"(Σ(TP×V)={total_tpv:.2f}, Σ(V)={total_volume:,})")
        return float(vwap)

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 4: generate_signal  (main entry point)
    # Blueprint ref: Section 4.3 "Entry Logic — Fade"
    # ──────────────────────────────────────────────────────────────────────────

    def generate_signal(self,
                        prev_bar: pd.Series,
                        entry_bar: pd.Series,
                        bb_upper: float,
                        bb_lower: float,
                        vwap: float,
                        atr: float,
                        hmm_state: str) -> Optional[dict]:
        """
        Evaluate whether the PREVIOUS bar's action confirms a fade entry.

        Called bar-by-bar from 10:15 AM to 2:00 PM. At each bar:
          - prev_bar  = the bar that just completed (bar T-1)
          - entry_bar = the bar now opening (bar T) — entry at its open

        DECISION SEQUENCE:
          1. Regime gate       → None if not Calm
          2. Confirmation      → did prev_bar touch AND close back inside a band?
          3. Direction         → SHORT (upper fade) or LONG (lower fade)
          4. Compute levels    → entry, stop, target
          5. Return signal

        Parameters
        ----------
        prev_bar  : pd.Series — the completed bar to check for BB touch
        entry_bar : pd.Series — the bar we will enter on (use its 'open')
        bb_upper  : float — current upper Bollinger Band
        bb_lower  : float — current lower Bollinger Band
        vwap      : float — current session VWAP (the target)
        atr       : float — current 14-period ATR (for stop calculation)
        hmm_state : str   — 'Calm', 'Normal', or 'Stress'

        Returns
        -------
        dict or None
            None if any gate fails.
            Signal dict: direction, entry_price, stop_loss, target
        """

        # ── Gate 1: Regime — Calm ONLY ───────────────────────────────────────
        # VWAP MR is the most restrictive strategy. Even Normal regime has
        # enough trending behaviour to make mean reversion unreliable.
        if hmm_state not in self.config['allowed_regimes']:
            logger.debug(f"VWAP_MR BLOCKED: regime={hmm_state} "
                         f"(only {self.config['allowed_regimes']} allowed)")
            return None

        # ── Gate 2: Confirmation — did prev_bar touch and close back inside? ──
        #
        # SHORT confirmation (upper band fade):
        #   The stock poked above BB_upper (high >= bb_upper) but sellers pushed
        #   it back down before the bar closed (close < bb_upper).
        #   Interpretation: "buyers tried to push higher but failed."
        #
        # LONG confirmation (lower band fade):
        #   The stock dipped below BB_lower (low <= bb_lower) but buyers stepped
        #   in and pushed it back before the bar closed (close > bb_lower).
        #   Interpretation: "sellers tried to push lower but failed."
        #
        # If the bar closes OUTSIDE the band, momentum is strong — don't fade.

        short_confirmed = (prev_bar['high'] >= bb_upper and
                           prev_bar['close'] < bb_upper)
        long_confirmed  = (prev_bar['low']  <= bb_lower and
                           prev_bar['close'] > bb_lower)

        if short_confirmed:
            direction = 'SHORT'
        elif long_confirmed:
            direction = 'LONG'
        else:
            # No confirmation — bar stayed inside bands or closed outside
            return None

        # ── Compute trade levels ─────────────────────────────────────────────

        entry_price = float(entry_bar['open'])

        # Stop: fixed ATR-based volatility stop.
        # Unlike ORB (which uses structure), VWAP MR uses ATR because the
        # stock is range-bound — there's no clear structural level to anchor to.
        # 1.5× ATR gives enough room to avoid noise while capping max loss.
        stop_distance = self.config['stop_atr_multiple'] * atr

        if direction == 'SHORT':
            stop_loss = round(entry_price + stop_distance, 2)
        else:  # LONG
            stop_loss = round(entry_price - stop_distance, 2)

        # Target: VWAP (fair value / mean)
        # This is fundamentally different from ORB's 2R target.
        # We're not targeting a fixed multiple — we're targeting the point
        # the stock SHOULD return to given current volume distribution.
        target = round(vwap, 2)

        signal = {
            'direction':   direction,
            'entry_price': entry_price,
            'stop_loss':   stop_loss,
            'target':      target,
        }

        logger.info(
            f"VWAP_MR SIGNAL: {direction} @ ${entry_price:.2f} | "
            f"stop=${stop_loss:.2f} | target(VWAP)=${target:.2f} | "
            f"atr=${atr:.2f} | regime={hmm_state}"
        )

        return signal
