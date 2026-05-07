# raits/strategies/orb.py
#
# Opening Range Breakout (ORB) Strategy — "The Gappers"
#
# Blueprint ref: Section 4.2
# Active period:  9:35 AM – 10:15 AM ET
# Allowed regimes: Calm, Normal  (blocked during Stress)
# Max positions:  2 concurrent
#
# ──────────────────────────────────────────────────────────────────────────────
# DESIGN PRINCIPLES (established in the Phase 1B planning session)
# ──────────────────────────────────────────────────────────────────────────────
#
# 1. HMM STATE IS PASSED IN, NOT FETCHED.
#    ORBStrategy receives hmm_state as a plain string ('Calm'/'Normal'/'Stress').
#    It does NOT import or call HMMEngine. The Master Strategy Router
#    (router.py, built in Phase 1C) is the only place that touches HMMEngine.
#    This keeps ORB fully testable in isolation.
#
# 2. CLASS, NOT FUNCTIONS.
#    ORB has intra-session state: the watchlist is built at 9:35 AM and
#    referenced 40 minutes later at 9:46 AM. self.watchlist and
#    self.opening_ranges hold this state naturally between method calls.
#    A functions module would require callers to carry this state manually.
#
# 3. INPUTS ARE PRE-COMPUTED, NOT FETCHED INTERNALLY.
#    generate_signal() receives candle, or_high, or_low, vwap, rvol as
#    arguments. The backtester / router computes these upstream and passes
#    them in. This keeps the method pure and trivially testable.
#
# ──────────────────────────────────────────────────────────────────────────────
# HOW THESE PIECES FIT TOGETHER IN A BACKTEST
# ──────────────────────────────────────────────────────────────────────────────
#
# Simulated time 9:35 AM:
#   candidates = data_pipeline.get_universe_snapshot()
#   watchlist  = orb.run_scanner(candidates)
#
# Simulated time 9:31–9:45 (for each ticker in watchlist):
#   or_high, or_low, status = orb.calculate_opening_range(bars, atr)
#   if status == 'VALID':
#       orb.opening_ranges[ticker] = (or_high, or_low)
#
# Simulated time 9:46–10:15 (for each new 1-min bar):
#   hmm_state = hmm_engine.predict(spy_features)     ← router's job
#   for ticker in orb.opening_ranges:
#       rvol   = orb.calculate_intraday_rvol(bar.volume, hist_avg)
#       signal = orb.generate_signal(bar, or_high, or_low, vwap, rvol, hmm_state)
#       if signal:
#           backtester.execute(signal)

import pandas as pd
import numpy as np
import logging
from typing import Optional

logger = logging.getLogger('RAITS.ORB')


# ──────────────────────────────────────────────────────────────────────────────
# DEFAULT CONFIGURATION
# Every threshold here maps to a specific blueprint rule.
# These are the Standard Configuration values (SHALL + SHOULD).
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    # Scanner filters (Section 4.2 "Scanner Criteria")
    'min_gap_pct':               0.02,    # ±2% minimum gap from prev close
    'min_price':                 10.0,    # $10 minimum stock price
    'max_price':                1000.0,    # $200 maximum stock price
    'premarket_vol_threshold':  10_000,   # pre-market volume Option A threshold
    'opening_vol_multiplier':    1.5,     # opening 5-min volume Option B multiplier

    # Opening Range validation (Section 4.2 "Opening Range Definition")
    'min_range_atr_multiple':    0.5,     # OR range must be >= 0.5 × ATR
    'max_range_atr_multiple':    5.0,     # OR range must be <= 5.0 × ATR
    'min_range_abs':             0.20,    # absolute floor: OR range >= $0.20

    # Entry confirmation (Section 4.2 "Entry Logic")
    'rvol_threshold':            2.0,     # intraday RVol must be >= 2.0×
    'fakeout_wick_ratio':        0.5,     # wick/body ratio threshold for fakeout
    'doji_body_threshold':       0.01,    # body < $0.01 → treat as doji/fakeout

    # Risk / reward (Section 4.2 "Exit Logic")
    'target_rr':                 2.0,     # 2R target

    # Regime filter (Section 6.1 "Regime-Strategy Mapping")
    'allowed_regimes': ['Calm', 'Normal'],
}


class ORBStrategy:
    """
    Opening Range Breakout strategy — "The Gappers".

    Usage (backtesting):
        orb = ORBStrategy()

        # 9:35 AM — build watchlist
        watchlist = orb.run_scanner(universe_candidates)

        # 9:31–9:45 — compute OR for each ticker
        for ticker in watchlist:
            or_high, or_low, status = orb.calculate_opening_range(or_bars, atr)
            if status == 'VALID':
                orb.opening_ranges[ticker] = (or_high, or_low)

        # 9:46–10:15 — monitor for breakouts
        for bar in monitoring_bars:
            rvol   = orb.calculate_intraday_rvol(bar.volume, hist_avg)
            signal = orb.generate_signal(bar, or_high, or_low, vwap, rvol, hmm_state)
    """

    def __init__(self, config: Optional[dict] = None):
        """
        Parameters
        ----------
        config : dict, optional
            Override any DEFAULT_CONFIG value. Unspecified keys fall back to
            the defaults. This allows the WFO optimizer to vary thresholds
            without touching source code.
        """
        # Merge caller's overrides on top of defaults.
        # dict(**a, **b) means b wins on key conflicts.
        self.config = {**DEFAULT_CONFIG, **(config or {})}

        # ── Intra-session state ──────────────────────────────────────────────
        # These are populated during a live session or backtest replay.
        # They must be reset between sessions (different trading days).

        # Tickers that passed the 9:35 AM scanner.
        # Type: list[str]
        self.watchlist: list = []

        # Pre-computed OR levels for each ticker in the watchlist.
        # Populated after the 9:31–9:45 OR formation window.
        # Type: dict[str, tuple[float, float]]  →  {ticker: (or_high, or_low)}
        self.opening_ranges: dict = {}

    def reset(self):
        """
        Clear intra-session state. Call once at the start of each trading day
        (or each simulated day in backtesting).
        """
        self.watchlist = []
        self.opening_ranges = {}

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 1: run_scanner
    # Blueprint ref: Section 4.2 "Scanner Criteria (Executed at 9:35 AM ET)"
    # ──────────────────────────────────────────────────────────────────────────

    def run_scanner(self, candidates: list) -> list:
        """
        Filter a universe of stocks to those with ORB potential.

        Called ONCE at 9:35 AM ET. Uses the actual 9:30–9:35 opening volume
        (not pre-market estimates), eliminating look-ahead bias.

        Parameters
        ----------
        candidates : list[dict]
            Each dict must contain:
                ticker              : str
                prev_close          : float  — yesterday's closing price
                open_price          : float  — today's opening price
                premarket_volume    : int    — pre-market shares traded (0 if unavailable)
                avg_daily_volume    : int    — 20-day average daily volume
                opening_5min_volume : int    — actual 9:30–9:35 volume

        Returns
        -------
        list[str]
            Tickers that passed all three filters. Stored in self.watchlist.
        """
        accepted = []

        for c in candidates:
            ticker = c['ticker']

            # ── Filter 1: Gap percentage ─────────────────────────────────────
            # We use abs() so both gap-ups and gap-downs qualify.
            # A stock that opened flat has no clear directional catalyst.
            gap_pct = abs(c['open_price'] - c['prev_close']) / c['prev_close']
            if gap_pct < self.config['min_gap_pct']:
                logger.debug(f"ORB Scanner REJECT {ticker}: gap {gap_pct:.2%} < "
                             f"{self.config['min_gap_pct']:.0%} minimum")
                continue

            # ── Filter 2: Price range ────────────────────────────────────────
            # Below $10: penny stock risk (wide spreads, thin books).
            # Above $200: position sizing becomes awkward in $25k accounts.
            price = c['open_price']
            if not (self.config['min_price'] <= price <= self.config['max_price']):
                logger.debug(f"ORB Scanner REJECT {ticker}: price ${price:.2f} "
                             f"outside ${self.config['min_price']}–${self.config['max_price']}")
                continue

            # ── Filter 3: Liquidity — two-path logic ─────────────────────────
            # Option A: Pre-market volume > 50,000 shares.
            #   Strong pre-market activity confirms institutions are interested.
            #
            # Option B (fallback): Opening 5-min volume > 2× average.
            #   Used when pre-market data is unavailable (common with free tiers).
            #   avg_5min = avg_daily_volume / 78  (78 five-min bars in trading day)
            #   threshold = opening_vol_multiplier × avg_5min
            #
            # Only ONE of A or B needs to pass.
            premarket_ok = c['premarket_volume'] > self.config['premarket_vol_threshold']

            avg_5min = c['avg_daily_volume'] / 78
            opening_threshold = self.config['opening_vol_multiplier'] * avg_5min
            opening_ok = c['opening_5min_volume'] > opening_threshold

            if not (premarket_ok or opening_ok):
                logger.debug(f"ORB Scanner REJECT {ticker}: insufficient volume "
                             f"(premarket={c['premarket_volume']:,}, "
                             f"opening={c['opening_5min_volume']:,}, "
                             f"threshold={opening_threshold:,.0f})")
                continue

            logger.info(f"ORB Scanner ACCEPT {ticker}: gap={gap_pct:.2%}, "
                        f"price=${price:.2f}, premarket={premarket_ok}, opening={opening_ok}")
            accepted.append(ticker)

        self.watchlist = accepted
        return accepted

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 2: calculate_opening_range
    # Blueprint ref: Section 4.2 "Opening Range Definition"
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_opening_range(self, bars: pd.DataFrame, atr: float):
        """
        Compute the Opening Range (OR) from the 9:31–9:45 bars.

        The OR is simply the highest high and lowest low across all bars in the
        window. It represents the "equilibrium zone" established in the first
        15 minutes. A breakout above OR high or below OR low signals that one
        side has taken control.

        Parameters
        ----------
        bars : pd.DataFrame
            1-minute OHLCV bars covering the OR window.
            Must have columns: open, high, low, close, volume.
            The 9:30 opening print bar must already be excluded by the caller
            (per blueprint: OR starts at 9:30:30, skip the noisy first print).

        atr : float
            14-period ATR (Average True Range) from recent daily bars.
            Used to validate that the OR range is meaningful.

        Returns
        -------
        tuple: (or_high, or_low, status)
            or_high : float or None
            or_low  : float or None
            status  : 'VALID' | 'RANGE_TOO_NARROW' | 'RANGE_TOO_WIDE'
        """
        or_high = bars['high'].max()
        or_low  = bars['low'].min()
        or_range = or_high - or_low

        # ── Validation: minimum range ────────────────────────────────────────
        # Blueprint: "if or_range < max(0.5 * atr, 0.20): return RANGE_TOO_NARROW"
        # We use max() so the $0.20 absolute floor protects against tiny ATRs
        # on low-priced stocks where 0.5× ATR might itself be less than $0.20.
        min_range = max(self.config['min_range_atr_multiple'] * atr,
                        self.config['min_range_abs'])

        if or_range < min_range:
            logger.debug(f"OR RANGE_TOO_NARROW: range=${or_range:.2f}, "
                         f"min=${min_range:.2f} (0.5×ATR={0.5*atr:.2f})")
            return None, None, 'RANGE_TOO_NARROW'

        # ── Validation: maximum range ────────────────────────────────────────
        # A range > 5× ATR suggests a data error or a halted/resumed stock.
        # We don't trade these — the position sizing and stop distances are
        # unpredictable.
        max_range = self.config['max_range_atr_multiple'] * atr

        if or_range > max_range:
            logger.debug(f"OR RANGE_TOO_WIDE: range=${or_range:.2f}, "
                         f"max=${max_range:.2f} (5×ATR={5*atr:.2f})")
            return None, None, 'RANGE_TOO_WIDE'

        logger.info(f"OR VALID: high=${or_high:.2f}, low=${or_low:.2f}, "
                    f"range=${or_range:.2f} ({or_range/atr:.2f}×ATR)")
        return or_high, or_low, 'VALID'

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 3: calculate_intraday_rvol
    # Blueprint ref: Section 4.2 "Calculate Intraday Relative Volume"
    # ──────────────────────────────────────────────────────────────────────────

    def calculate_intraday_rvol(self, current_volume: int,
                                 historical_avg_volume: float) -> float:
        """
        Intraday Relative Volume: how unusual is this bar's volume compared to
        the historical average FOR THIS SAME TIME OF DAY?

        This is more accurate than daily RVol because volume has a strong
        intraday pattern: high at open, drops through midday, rises at close.
        Comparing the 9:46 bar to the daily average would inflate RVol at open.
        We compare it to the average 9:46 bar across the past 20 days instead.

        The computation of historical_avg_volume happens upstream (in the data
        pipeline or backtester). This method just does the ratio.

        Parameters
        ----------
        current_volume      : int   — volume on the current 1-min bar
        historical_avg_volume : float — average volume for this time slot
                                        over the past 20 trading days

        Returns
        -------
        float — RVol ratio (e.g., 3.125 means 3.125× the historical average)
        """
        if historical_avg_volume <= 0:
            # Guard against division by zero. Return 0.0 so downstream
            # RVol threshold check (>= 2.0) will correctly reject this bar.
            logger.warning("historical_avg_volume is zero or negative — returning RVol=0.0")
            return 0.0

        return current_volume / historical_avg_volume

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 4: check_fakeout
    # Blueprint ref: Section 4.2 "Failure Condition — The Fakeout"
    # ──────────────────────────────────────────────────────────────────────────

    def check_fakeout(self, candle: pd.Series, direction: str) -> bool:
        """
        Detect false breakouts via candlestick wick analysis.

        A "fakeout" is when price briefly penetrates the OR boundary but then
        reverses sharply — sellers overwhelmed buyers (on a LONG breakout) or
        buyers overwhelmed sellers (on a SHORT breakdown). The shape of the
        candle reveals this reversal.

        For LONG breakouts — look for Shooting Star:
            The stock punches above OR high but closes back near the open.
            Long upper wick = sellers rejected the move.
            upper_wick = high - max(close, open)
            fakeout if upper_wick > fakeout_wick_ratio × body

        For SHORT breakdowns — look for Hammer:
            The stock dips below OR low but closes back near the open.
            Long lower wick = buyers stepped in and rejected the move.
            lower_wick = min(close, open) - low
            fakeout if lower_wick > fakeout_wick_ratio × body

        Doji candles (body < $0.01) are always treated as fakeouts regardless
        of direction — they show zero conviction.

        Parameters
        ----------
        candle    : pd.Series with open, high, low, close fields
        direction : 'LONG' or 'SHORT'

        Returns
        -------
        bool — True if fakeout detected (reject trade), False if valid
        """
        body = abs(candle['close'] - candle['open'])

        # ── Doji guard ───────────────────────────────────────────────────────
        # A doji has essentially no body — buyers and sellers ended up at the
        # same price. That's the opposite of the conviction we need for ORB.
        if body < self.config['doji_body_threshold']:
            logger.debug("Fakeout: doji candle (body < $0.01)")
            return True

        ratio_threshold = self.config['fakeout_wick_ratio']

        if direction == 'LONG':
            # For a long breakout, the dangerous pattern is a Shooting Star:
            # price spikes high then closes near open — sellers won.
            upper_wick = candle['high'] - max(candle['close'], candle['open'])
            if upper_wick > ratio_threshold * body:
                logger.debug(f"Fakeout (Shooting Star): upper_wick=${upper_wick:.2f}, "
                             f"body=${body:.2f}, ratio={upper_wick/body:.1%}")
                return True

        elif direction == 'SHORT':
            # For a short breakdown, the dangerous pattern is a Hammer:
            # price dips low then recovers near open — buyers defended.
            lower_wick = min(candle['close'], candle['open']) - candle['low']
            if lower_wick > ratio_threshold * body:
                logger.debug(f"Fakeout (Hammer): lower_wick=${lower_wick:.2f}, "
                             f"body=${body:.2f}, ratio={lower_wick/body:.1%}")
                return True

        return False

    # ──────────────────────────────────────────────────────────────────────────
    # METHOD 5: generate_signal  (main entry point)
    # Blueprint ref: Section 4.2 "Entry Logic" + Section 6.2 "Strategy Router"
    # ──────────────────────────────────────────────────────────────────────────

    def generate_signal(self,
                        candle: pd.Series,
                        or_high: float,
                        or_low: float,
                        vwap: float,
                        rvol: float,
                        hmm_state: str) -> Optional[dict]:
        """
        Evaluate the current 1-minute bar for an ORB entry signal.

        This method is called bar-by-bar during the 9:46–10:15 monitoring window
        for each ticker in self.opening_ranges. It applies all entry filters
        in sequence and either returns a signal dict or None.

        DECISION SEQUENCE (order matters — each gate is cheaper than the next):
          1. HMM regime gate  — cheapest: O(1) string check
          2. Direction check  — O(1) price comparison
          3. RVol gate        — O(1) float comparison
          4. Fakeout check    — O(1) arithmetic on candle fields
          5. Compute levels   — O(1) arithmetic, only reached if all gates pass

        Parameters
        ----------
        candle    : pd.Series with open, high, low, close, volume
        or_high   : float — pre-computed OR high from calculate_opening_range()
        or_low    : float — pre-computed OR low from calculate_opening_range()
        vwap      : float — Volume Weighted Average Price at current bar
        rvol      : float — intraday RVol from calculate_intraday_rvol()
        hmm_state : str   — 'Calm', 'Normal', or 'Stress' from HMMEngine

        Returns
        -------
        dict or None
            None if any gate fails.
            Signal dict on a valid setup with keys:
                direction   : 'LONG' or 'SHORT'
                entry_price : candle.close (the trigger price; actual fill = next bar open)
                stop_loss   : min(or_low, vwap) for LONG / max(or_high, vwap) for SHORT
                target      : entry_price ± 2×risk  (2R)
                rvol        : the rvol value passed in (logged with the trade)
        """

        # ── Gate 1: HMM Regime ───────────────────────────────────────────────
        # ORB only runs in Calm and Normal. During Stress, volatility is too
        # high for breakout trades — false breakouts increase dramatically and
        # gaps at execution blow out the R:R ratio.
        if hmm_state not in self.config['allowed_regimes']:
            logger.debug(f"ORB BLOCKED: regime={hmm_state} not in {self.config['allowed_regimes']}")
            return None

        # ── Gate 2: Direction — did price break the OR? ──────────────────────
        # We use candle.close (not candle.high) for breakout confirmation.
        # Using high would fire on a momentary pierce that reverses — a classic
        # fakeout. Requiring a CLOSE above/below the level is more conservative
        # and matches how most ORB practitioners define "breakout confirmed".
        entry_price = candle['close']

        if entry_price > or_high:
            direction = 'LONG'
        elif entry_price < or_low:
            direction = 'SHORT'
        else:
            # Price is still inside the OR — no breakout yet.
            return None

        # ── Gate 3: Volume confirmation ──────────────────────────────────────
        # Blueprint: "RVol >= 2.0 for entry confirmation"
        # A breakout on low volume is often a fake-out caused by a single large
        # order. We require real participation from multiple market participants.
        if rvol < self.config['rvol_threshold']:
            logger.debug(f"ORB BLOCKED: rvol={rvol:.2f} < {self.config['rvol_threshold']:.1f} threshold")
            return None

        # ── Gate 4: Fakeout (candlestick pattern) ────────────────────────────
        # Even with a close above OR high AND good volume, the candle shape can
        # reveal that sellers immediately overwhelmed buyers (Shooting Star).
        # check_fakeout() returns True if the pattern is a rejection.
        if self.check_fakeout(candle, direction):
            logger.debug(f"ORB BLOCKED: fakeout pattern detected on {direction} candle")
            return None

        # ── All gates passed — compute trade levels ──────────────────────────

        # Stop loss:
        #   LONG:  stop = min(or_low, vwap)
        #     We want the stop below BOTH the OR structure AND the fair value line.
        #     If VWAP is already above OR low, using OR low gives a wider stop
        #     (more room to breathe). If VWAP is below OR low, using VWAP places
        #     the stop at fair value — a more defensible level.
        #     Either way, min() picks the lower (more generous) of the two.
        #
        #   SHORT: stop = max(or_high, vwap)
        #     Mirror logic. max() picks the higher (more generous) of the two.
        if direction == 'LONG':
            stop_loss = min(or_low, vwap)
        else:  # SHORT
            stop_loss = max(or_high, vwap)

        # Risk per share: the dollar distance from entry to stop.
        risk = abs(entry_price - stop_loss)

        if risk <= 0:
            # Degenerate case: entry == stop (shouldn't happen with valid data,
            # but guard against division-by-zero in downstream position sizing).
            logger.warning(f"ORB BLOCKED: risk=$0 (entry={entry_price}, stop={stop_loss})")
            return None

        # Target: 2R
        #   LONG:  target = entry + 2 × risk  (price must travel 2× the risk distance)
        #   SHORT: target = entry - 2 × risk
        if direction == 'LONG':
            target = entry_price + self.config['target_rr'] * risk
        else:  # SHORT
            target = entry_price - self.config['target_rr'] * risk

        signal = {
            'direction':   direction,
            'entry_price': entry_price,
            'stop_loss':   stop_loss,
            'target':      round(target, 2),
            'rvol':        rvol,
        }

        logger.info(
            f"ORB SIGNAL: {direction} @ ${entry_price:.2f} | "
            f"stop=${stop_loss:.2f} | target=${target:.2f} | "
            f"risk=${risk:.2f} | rvol={rvol:.2f}x | regime={hmm_state}"
        )

        return signal
