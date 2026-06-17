# raits/strategies/universe_scanner.py
#
# DailyUniverseScanner — momentum screen using T-1 daily bars
#
# Runs each morning before market open using previous day's close data.
# Selects stocks eligible for TF trading today.
#
# Criteria (in order of filtering):
#   1. Price > SMA50 > SMA200          — confirmed uptrend
#   2. Price > 85% of 52-week high     — near recent strength, not broken
#   3. RS vs SPY (6-month) > 1.0       — outperforming market
#   4. Avg daily volume (20d) > 500k   — liquid enough to trade
#   → Rank survivors by RS score, return top N

import logging
import pandas as pd
from typing import Dict, List, Optional

logger = logging.getLogger("RAITS.UniverseScanner")

# Nasdaq-100 derived pool — large-caps that were established by 2017.
# Selected to avoid survivorship bias: all were significant companies
# at the start of the backtest period, across multiple sectors.
CANDIDATE_POOL = [
    # Mega-cap tech (original 8)
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AMD",
    # Semiconductors
    "QCOM", "INTC", "MU", "AVGO", "TXN", "AMAT",
    # Software / Cloud
    "ADBE", "CRM", "ORCL", "INTU", "CSCO",
    # Biotech / Healthcare
    "AMGN", "GILD", "BIIB", "REGN", "VRTX",
    # Consumer / Retail
    "COST", "SBUX", "NFLX", "EBAY",
    # Financials
    "JPM", "GS", "MS", "V", "MA",
    # Industrials / Other
    "HON", "MMM",
    # Energy
    "XOM", "CVX",
]

# SPY is always loaded as the benchmark — not included in pool
BENCHMARK = "SPY"

# Separate pool for VWAP_MR — range-bound, low-beta stocks.
# Explicitly excludes high-momentum tech (TSLA, NVDA, AMD, META) that TF trades.
# DailyUniverseScanner selects TRENDING stocks; MRUniverseScanner selects OSCILLATING stocks.
MR_CANDIDATE_POOL = [
    # Original 8-stock universe
    "TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL",
    # Phase 1 — high scanner-frequency stocks
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
    # Phase 2 — additional liquid names
    "MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM",
]


class DailyUniverseScanner:
    """
    Selects the top momentum stocks for today using T-1 daily bar data.

    Usage in backtest (bar-by-bar loop):
        scanner = DailyUniverseScanner(top_n=15)
        # At start of each trading day:
        today_universe = scanner.scan(daily_data, scan_date)

    Usage in production:
        # Run after market close or before 9:30 AM next morning
        today_universe = scanner.scan(daily_data, date.today())
    """

    def __init__(
        self,
        top_n: int = 15,
        sma_fast: int = 50,
        sma_slow: int = 200,
        ath_proximity: float = 0.85,   # price must be > 85% of 52-week high
        rs_lookback: int = 126,        # ~6 months of trading days
        min_avg_volume: float = 500_000,
        min_atr_pct: float = 0.015,    # min 14-day ATR / price — filters low-vol stocks
        atr_period: int = 14,
        candidate_pool: Optional[List[str]] = None,
    ):
        self.top_n = top_n
        self.sma_fast = sma_fast
        self.sma_slow = sma_slow
        self.ath_proximity = ath_proximity
        self.rs_lookback = rs_lookback
        self.min_avg_volume = min_avg_volume
        self.min_atr_pct = min_atr_pct
        self.atr_period = atr_period
        self.pool = candidate_pool or CANDIDATE_POOL

    def scan(
        self,
        daily_data: Dict[str, pd.DataFrame],
        scan_date: pd.Timestamp,
    ) -> List[str]:
        """
        Run scanner using data up to and including scan_date (T-1 in production).

        Parameters
        ----------
        daily_data : dict ticker → DataFrame with daily OHLCV, DatetimeIndex
        scan_date  : the date whose close we treat as "yesterday"
                     In backtest: previous trading day's date
                     In production: date.today() - 1 trading day

        Returns
        -------
        List of tickers ranked by RS score (best first), up to top_n.
        Empty list if SPY data unavailable.
        """
        if BENCHMARK not in daily_data or daily_data[BENCHMARK].empty:
            logger.warning("Scanner: SPY daily data missing — returning empty universe")
            return []

        spy_data = daily_data[BENCHMARK]
        spy_slice = spy_data[spy_data.index.normalize() <= pd.Timestamp(scan_date)]
        if len(spy_slice) < self.rs_lookback:
            logger.warning("Scanner: insufficient SPY history — returning empty universe")
            return []

        spy_rs_start = float(spy_slice["close"].iloc[-self.rs_lookback])
        spy_rs_end   = float(spy_slice["close"].iloc[-1])
        spy_rs_return = (spy_rs_end - spy_rs_start) / spy_rs_start if spy_rs_start > 0 else 0.0

        candidates = []

        for ticker in self.pool:
            if ticker not in daily_data or daily_data[ticker].empty:
                continue

            df = daily_data[ticker]
            df = df[df.index.normalize() <= pd.Timestamp(scan_date)]

            # Need enough history for SMA200 + RS lookback
            min_bars = max(self.sma_slow, self.rs_lookback) + 5
            if len(df) < min_bars:
                logger.debug(f"Scanner SKIP {ticker}: only {len(df)} daily bars (need {min_bars})")
                continue

            close = df["close"]
            current_price = float(close.iloc[-1])
            if current_price <= 0:
                continue

            # ── Filter 1: Trend alignment — price > SMA50 > SMA200 ────────────
            sma_fast = float(close.rolling(self.sma_fast).mean().iloc[-1])
            sma_slow = float(close.rolling(self.sma_slow).mean().iloc[-1])

            if pd.isna(sma_fast) or pd.isna(sma_slow):
                continue
            if not (current_price > sma_fast > sma_slow):
                logger.debug(f"Scanner SKIP {ticker}: trend not aligned "
                             f"price={current_price:.2f} SMA{self.sma_fast}={sma_fast:.2f} "
                             f"SMA{self.sma_slow}={sma_slow:.2f}")
                continue

            # ── Filter 2: Near 52-week high ───────────────────────────────────
            high_52w = float(df["high"].iloc[-252:].max()) if len(df) >= 252 else float(df["high"].max())
            if current_price < self.ath_proximity * high_52w:
                logger.debug(f"Scanner SKIP {ticker}: {current_price:.2f} < "
                             f"{self.ath_proximity:.0%} of 52wk high {high_52w:.2f}")
                continue

            # ── Filter 3: Relative strength vs SPY (6-month) ─────────────────
            if len(df) < self.rs_lookback:
                continue
            rs_start = float(close.iloc[-self.rs_lookback])
            rs_end   = float(close.iloc[-1])
            stock_return = (rs_end - rs_start) / rs_start if rs_start > 0 else 0.0
            rs_score = stock_return - spy_rs_return   # excess return vs SPY

            if rs_score <= 0:
                logger.debug(f"Scanner SKIP {ticker}: RS={rs_score:.3f} (underperforming SPY)")
                continue

            # ── Filter 4: Liquidity — avg daily volume ────────────────────────
            avg_vol = float(df["volume"].iloc[-20:].mean())
            if avg_vol < self.min_avg_volume:
                logger.debug(f"Scanner SKIP {ticker}: avg_vol={avg_vol:,.0f} < {self.min_avg_volume:,.0f}")
                continue

            # ── Filter 5: Volatility — 14-day ATR as % of price ──────────────
            # Ensures enough daily range for TF to achieve 2:1 R:R without noise.
            # Low-vol stocks (CSCO, ORCL, HON ~0.8-1.0%) get filtered out.
            if self.min_atr_pct > 0 and len(df) >= self.atr_period + 1:
                hi = df["high"].iloc[-(self.atr_period + 1):]
                lo = df["low"].iloc[-(self.atr_period + 1):]
                cl = df["close"].iloc[-(self.atr_period + 1):]
                tr = pd.concat([
                    hi - lo,
                    (hi - cl.shift(1)).abs(),
                    (lo - cl.shift(1)).abs(),
                ], axis=1).max(axis=1).iloc[1:]   # drop first NaN row
                atr = float(tr.mean())
                atr_pct = atr / current_price if current_price > 0 else 0.0
                if atr_pct < self.min_atr_pct:
                    logger.debug(f"Scanner SKIP {ticker}: ATR%={atr_pct:.2%} < {self.min_atr_pct:.2%}")
                    continue

            candidates.append({
                "ticker":   ticker,
                "rs_score": rs_score,
                "price":    current_price,
                "avg_vol":  avg_vol,
            })
            logger.debug(f"Scanner PASS {ticker}: RS={rs_score:.3f} price={current_price:.2f}")

        # Rank by RS score descending, take top N
        candidates.sort(key=lambda x: x["rs_score"], reverse=True)
        selected = [c["ticker"] for c in candidates[:self.top_n]]

        logger.info(
            f"Scanner {scan_date.date() if hasattr(scan_date,'date') else scan_date}: "
            f"{len(selected)}/{len(self.pool)} stocks selected "
            f"({len(candidates)} passed filters)"
        )
        if selected:
            top3 = candidates[:3]
            logger.info(
                "  Top 3: " +
                ", ".join(f"{c['ticker']}(RS={c['rs_score']:.2%})" for c in top3)
            )

        return selected

    def scan_short_side(
        self,
        daily_data: Dict[str, pd.DataFrame],
        scan_date: pd.Timestamp,
    ) -> List[str]:
        """
        Mirror scan for short candidates: price < SMA50 < SMA200,
        near 52-week LOW, underperforming SPY.
        Used when HMM regime = Stress.
        """
        if BENCHMARK not in daily_data or daily_data[BENCHMARK].empty:
            return []

        spy_data   = daily_data[BENCHMARK]
        spy_slice  = spy_data[spy_data.index.normalize() <= pd.Timestamp(scan_date)]
        if len(spy_slice) < self.rs_lookback:
            return []

        spy_rs_start  = float(spy_slice["close"].iloc[-self.rs_lookback])
        spy_rs_end    = float(spy_slice["close"].iloc[-1])
        spy_rs_return = (spy_rs_end - spy_rs_start) / spy_rs_start if spy_rs_start > 0 else 0.0

        candidates = []

        for ticker in self.pool:
            if ticker not in daily_data or daily_data[ticker].empty:
                continue

            df = daily_data[ticker]
            df = df[df.index.normalize() <= pd.Timestamp(scan_date)]
            min_bars = max(self.sma_slow, self.rs_lookback) + 5
            if len(df) < min_bars:
                continue

            close = df["close"]
            current_price = float(close.iloc[-1])
            if current_price <= 0:
                continue

            sma_fast = float(close.rolling(self.sma_fast).mean().iloc[-1])
            sma_slow = float(close.rolling(self.sma_slow).mean().iloc[-1])
            if pd.isna(sma_fast) or pd.isna(sma_slow):
                continue

            # Downtrend: price < SMA50 < SMA200
            if not (current_price < sma_fast < sma_slow):
                continue

            # Near 52-week LOW (within 15% above it)
            low_52w = float(df["low"].iloc[-252:].min()) if len(df) >= 252 else float(df["low"].min())
            if current_price > low_52w * 1.15:
                continue

            # Underperforming SPY
            rs_start = float(close.iloc[-self.rs_lookback])
            rs_end   = float(close.iloc[-1])
            stock_return = (rs_end - rs_start) / rs_start if rs_start > 0 else 0.0
            rs_score = spy_rs_return - stock_return  # how much worse than SPY

            if rs_score <= 0:
                continue

            avg_vol = float(df["volume"].iloc[-20:].mean())
            if avg_vol < self.min_avg_volume:
                continue

            candidates.append({"ticker": ticker, "rs_score": rs_score})

        candidates.sort(key=lambda x: x["rs_score"], reverse=True)
        return [c["ticker"] for c in candidates[:self.top_n]]


class MRUniverseScanner:
    """
    Daily pre-scanner for VWAP_MR — selects range-bound, low-beta stocks.

    Opposite philosophy from DailyUniverseScanner:
      - TF wants strong trends  → selects stocks with high RS, near ATH
      - MR wants oscillation   → selects stocks with low ADX, near SMA50

    Returns stocks ranked by lowest daily ADX (most trendless first).
    The intraday scanner in vwap_mr.py then applies a second filter
    (ADX<25 on 5-min, SMA proximity) before generating signals.
    """

    def __init__(
        self,
        top_n: int = 8,
        max_daily_adx: float = 20.0,
        max_sma50_distance_pct: float = 0.05,
        min_avg_volume: float = 200_000,
        adx_period: int = 14,
        candidate_pool: Optional[List[str]] = None,
    ):
        self.top_n = top_n
        self.max_daily_adx = max_daily_adx
        self.max_sma50_distance_pct = max_sma50_distance_pct
        self.min_avg_volume = min_avg_volume
        self.adx_period = adx_period
        self.pool = candidate_pool or MR_CANDIDATE_POOL

    def scan(
        self,
        daily_data: Dict[str, pd.DataFrame],
        scan_date: pd.Timestamp,
    ) -> List[str]:
        """
        Select range-bound stocks for VWAP_MR using T-1 daily bar data.

        Criteria:
          1. Price within max_sma50_distance_pct of SMA50 (oscillating, not extended)
          2. Avg daily volume > min_avg_volume (liquid enough to trade)
          3. Daily ADX(14) < max_daily_adx (trendless on daily timeframe)

        Returns tickers ranked by lowest ADX (top N), empty list on failure.
        """
        candidates = []

        for ticker in self.pool:
            if ticker not in daily_data or daily_data[ticker].empty:
                continue

            df = daily_data[ticker]
            df = df[df.index.normalize() <= pd.Timestamp(scan_date)]

            min_bars = max(self.adx_period * 3, 55)
            if len(df) < min_bars:
                logger.debug(f"MR Scanner SKIP {ticker}: only {len(df)} bars")
                continue

            close = df["close"]
            current_price = float(close.iloc[-1])
            if current_price <= 0:
                continue

            # ── Filter 1: SMA50 proximity ─────────────────────────────────────
            sma50 = float(close.rolling(50).mean().iloc[-1])
            if pd.isna(sma50) or sma50 <= 0:
                continue
            dist_pct = abs(current_price - sma50) / sma50
            if dist_pct > self.max_sma50_distance_pct:
                logger.debug(f"MR Scanner SKIP {ticker}: {dist_pct:.1%} from SMA50")
                continue

            # ── Filter 2: Liquidity ───────────────────────────────────────────
            avg_vol = float(df["volume"].iloc[-20:].mean())
            if avg_vol < self.min_avg_volume:
                logger.debug(f"MR Scanner SKIP {ticker}: avg_vol={avg_vol:,.0f}")
                continue

            # ── Filter 3: Daily ADX (trendless) ──────────────────────────────
            adx = self._compute_adx(df)
            if adx >= self.max_daily_adx:
                logger.debug(f"MR Scanner SKIP {ticker}: ADX={adx:.1f} >= {self.max_daily_adx}")
                continue

            candidates.append({"ticker": ticker, "adx": adx})
            logger.debug(f"MR Scanner PASS {ticker}: ADX={adx:.1f}, SMA50_dist={dist_pct:.1%}")

        # Rank by lowest ADX (most range-bound first), take top N
        candidates.sort(key=lambda x: x["adx"])
        selected = [c["ticker"] for c in candidates[:self.top_n]]

        logger.info(
            f"MR Scanner {scan_date.date() if hasattr(scan_date, 'date') else scan_date}: "
            f"{len(selected)}/{len(self.pool)} stocks selected"
        )
        return selected

    def _compute_adx(self, df: pd.DataFrame) -> float:
        """14-period ADX from daily OHLCV bars. Returns 100.0 on failure (assume trending)."""
        period = self.adx_period
        if len(df) < period + 1:
            return 100.0
        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ], axis=1).max(axis=1)
            up = high.diff()
            down = -low.diff()
            plus_dm = up.where((up > down) & (up > 0), 0.0)
            minus_dm = down.where((down > up) & (down > 0), 0.0)
            atr_s = tr.ewm(span=period, adjust=False).mean()
            plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
            minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
            adx = dx.ewm(span=period, adjust=False).mean()
            return float(adx.iloc[-1])
        except Exception:
            return 100.0


class ORBUniverseScanner:
    """
    Pre-market scanner for ORB — selects stocks with a history of news-driven gaps.

    Philosophy: ORB needs stocks that gap because of their OWN catalyst (FDA,
    earnings, analyst action), not because the market moved. These stocks show up
    in the historical data as high gap-frequency: they open materially away from
    the prior close more often than their peers.

    Gap follow-through (the gap continues intraday rather than reversing) is used
    as a quality multiplier — it selects stocks where gaps represent genuine
    directional conviction rather than noise.

    Score = gap_frequency × gap_followthrough_rate
    Ranks by score descending, returns top N.

    Uses T-1 daily bars — no pre-market or news feed required.
    """

    def __init__(
        self,
        top_n: int = 10,
        min_gap_freq: float = 0.05,     # ≥5% of days must have a gap ≥ gap_threshold
        gap_threshold: float = 0.01,    # gap ≥ 1% of prev close counts
        lookback_days: int = 60,        # rolling window for gap stats
        min_avg_volume: float = 500_000,
        candidate_pool: Optional[List[str]] = None,
    ):
        self.top_n = top_n
        self.min_gap_freq = min_gap_freq
        self.gap_threshold = gap_threshold
        self.lookback_days = lookback_days
        self.min_avg_volume = min_avg_volume
        self.pool = candidate_pool or CANDIDATE_POOL

    def scan(
        self,
        daily_data: Dict[str, pd.DataFrame],
        scan_date: pd.Timestamp,
    ) -> List[str]:
        """
        Select news-sensitive stocks for ORB using T-1 daily bar data.

        Returns tickers ranked by gap_freq × followthrough (top N).
        """
        candidates = []

        for ticker in self.pool:
            if ticker not in daily_data or daily_data[ticker].empty:
                continue

            df = daily_data[ticker]
            df = df[df.index.normalize() <= pd.Timestamp(scan_date)]

            if len(df) < self.lookback_days + 1:
                continue

            # ── Filter 1: Liquidity ───────────────────────────────────────────
            avg_vol = float(df["volume"].iloc[-20:].mean())
            if avg_vol < self.min_avg_volume:
                continue

            # ── Filter 2 + Score: gap frequency and follow-through ────────────
            window = df.iloc[-(self.lookback_days + 1):]
            prev_close = window["close"].shift(1)
            gap_pct    = (window["open"] - prev_close).abs() / prev_close
            gap_dir    = (window["open"] - prev_close)        # positive = gap up
            intraday   = (window["close"] - window["open"])   # positive = up day

            # Drop first row (NaN from shift)
            gap_pct  = gap_pct.iloc[1:]
            gap_dir  = gap_dir.iloc[1:]
            intraday = intraday.iloc[1:]

            is_gap      = gap_pct >= self.gap_threshold
            gap_freq    = float(is_gap.mean())

            if gap_freq < self.min_gap_freq:
                logger.debug(
                    f"ORB Scanner SKIP {ticker}: gap_freq={gap_freq:.1%} "
                    f"< {self.min_gap_freq:.1%}"
                )
                continue

            # Follow-through: on gap days, did price close in gap direction?
            followthrough = float(
                ((gap_dir * intraday) > 0)[is_gap].mean()
            ) if is_gap.any() else 0.0

            score = gap_freq * followthrough
            candidates.append({
                "ticker":       ticker,
                "gap_freq":     gap_freq,
                "followthrough": followthrough,
                "score":        score,
            })
            logger.debug(
                f"ORB Scanner PASS {ticker}: gap_freq={gap_freq:.1%} "
                f"followthrough={followthrough:.1%} score={score:.3f}"
            )

        candidates.sort(key=lambda x: x["score"], reverse=True)
        selected = [c["ticker"] for c in candidates[:self.top_n]]

        logger.info(
            f"ORB Scanner {scan_date.date() if hasattr(scan_date, 'date') else scan_date}: "
            f"{len(selected)}/{len(self.pool)} — top: "
            + ", ".join(
                f"{c['ticker']}({c['gap_freq']:.0%}×{c['followthrough']:.0%})"
                for c in candidates[:self.top_n]
            )
        )
        return selected


class ORBFadeUniverseScanner:
    """
    Pre-market scanner for FADE strategy — selects stocks with high gap reversal tendency.

    Philosophy: FADE needs stocks that gap but then REVERSE intraday (mean-reverting
    behaviour), as opposed to ORB which needs stocks that gap and follow through.

    Score = gap_frequency × (1 − followthrough_rate) = gap_freq × reversal_rate
    Ranks by score descending, returns top N.

    Uses T-1 daily bars — same data source as ORBUniverseScanner.
    """

    def __init__(
        self,
        top_n: int = 10,
        min_gap_freq: float = 0.05,
        gap_threshold: float = 0.01,
        lookback_days: int = 60,
        min_avg_volume: float = 500_000,
        candidate_pool: Optional[List[str]] = None,
    ):
        self.top_n = top_n
        self.min_gap_freq = min_gap_freq
        self.gap_threshold = gap_threshold
        self.lookback_days = lookback_days
        self.min_avg_volume = min_avg_volume
        self.pool = candidate_pool or CANDIDATE_POOL

    def scan(
        self,
        daily_data: Dict[str, pd.DataFrame],
        scan_date: pd.Timestamp,
    ) -> List[str]:
        """
        Select mean-reverting stocks for FADE using T-1 daily bar data.

        Returns tickers ranked by gap_freq × (1 − followthrough) — top N.
        """
        candidates = []

        for ticker in self.pool:
            if ticker not in daily_data or daily_data[ticker].empty:
                continue

            df = daily_data[ticker]
            df = df[df.index.normalize() <= pd.Timestamp(scan_date)]

            if len(df) < self.lookback_days + 1:
                continue

            avg_vol = float(df["volume"].iloc[-20:].mean())
            if avg_vol < self.min_avg_volume:
                continue

            window     = df.iloc[-(self.lookback_days + 1):]
            prev_close = window["close"].shift(1)
            gap_pct    = (window["open"] - prev_close).abs() / prev_close
            gap_dir    = (window["open"] - prev_close)
            intraday   = (window["close"] - window["open"])
            gap_pct    = gap_pct.iloc[1:]
            gap_dir    = gap_dir.iloc[1:]
            intraday   = intraday.iloc[1:]

            is_gap   = gap_pct >= self.gap_threshold
            gap_freq = float(is_gap.mean())
            if gap_freq < self.min_gap_freq:
                continue

            followthrough = float(
                ((gap_dir * intraday) > 0)[is_gap].mean()
            ) if is_gap.any() else 0.0

            reversal_rate = 1.0 - followthrough
            score = gap_freq * reversal_rate
            candidates.append({
                "ticker":       ticker,
                "gap_freq":     gap_freq,
                "reversal_rate": reversal_rate,
                "score":        score,
            })
            logger.debug(
                f"FADE Scanner PASS {ticker}: gap_freq={gap_freq:.1%} "
                f"reversal={reversal_rate:.1%} score={score:.3f}"
            )

        candidates.sort(key=lambda x: x["score"], reverse=True)
        selected = [c["ticker"] for c in candidates[:self.top_n]]

        logger.info(
            f"FADE Scanner {scan_date.date() if hasattr(scan_date, 'date') else scan_date}: "
            f"{len(selected)}/{len(self.pool)} — top: "
            + ", ".join(
                f"{c['ticker']}({c['gap_freq']:.0%}×rev{c['reversal_rate']:.0%})"
                for c in candidates[:self.top_n]
            )
        )
        return selected
