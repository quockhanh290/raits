"""
RAITS Polygon.io Data Fetcher

Fetches historical market data from Polygon.io with:
- Rate limiting
- Automatic caching
- Error handling
- Fallback to mock data (when API key not configured)

TIMEZONE NOTE (critical):
  Polygon.io returns timestamps as UTC milliseconds.
  All bar timestamps are converted to US/Eastern (ET) naive datetimes on
  the way in, so the rest of the engine can use plain ET time constants
  (9:30, 9:35, 15:55, etc.) without any offset arithmetic.
"""

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List
import requests
from raits.data.raits_data_models import BarData, HistoricalData, StockMetadata, SplitDividend
from raits.data.raits_data_cache import DataCache
from raits.data.raits_mock_data import MockDataGenerator

# Single source of truth for the target timezone.
# Using ZoneInfo handles EDT/EST transitions automatically.
EASTERN = ZoneInfo("America/New_York")


def _utc_ms_to_et(utc_ms: int) -> datetime:
    """
    Convert a Polygon.io UTC millisecond timestamp to a naive ET datetime.

    Steps:
      1. Build a UTC-aware datetime from the millisecond epoch.
      2. Convert to Eastern Time (handles EST/EDT automatically).
      3. Strip tzinfo so the rest of the codebase works with naive datetimes,
         consistent with how pandas DatetimeIndex comparisons work throughout
         the engine (bar_t = bar_ts.time() etc.).

    Args:
        utc_ms: Polygon timestamp in UTC milliseconds.

    Returns:
        Naive datetime in US/Eastern time.
    """
    utc_dt = datetime.fromtimestamp(utc_ms / 1000, tz=timezone.utc)
    et_dt = utc_dt.astimezone(EASTERN)
    return et_dt.replace(tzinfo=None)


class RateLimiter:
    """
    Simple rate limiter for API calls.

    Prevents exceeding API rate limits.
    """

    def __init__(self, calls_per_minute: int = 100):
        """
        Initialize rate limiter.

        Args:
            calls_per_minute: Maximum API calls per minute
        """
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute  # Seconds between calls
        self.last_call_time = 0.0

    def wait_if_needed(self) -> None:
        """Sleep if necessary to respect rate limit."""
        current_time = time.time()
        time_since_last_call = current_time - self.last_call_time

        if time_since_last_call < self.min_interval:
            sleep_time = self.min_interval - time_since_last_call
            time.sleep(sleep_time)

        self.last_call_time = time.time()


class PolygonDataFetcher:
    """
    Fetches historical data from Polygon.io API.

    Features:
    - Automatic caching to minimize API calls
    - Rate limiting
    - Retry logic for failed requests
    - Falls back to mock data if API key not configured
    - All timestamps stored as naive US/Eastern datetimes
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        use_cache: bool = True,
        cache_dir: str = './raits/data/cache',
        rate_limit_calls_per_minute: int = 100
    ):
        """
        Initialize Polygon data fetcher.

        Args:
            api_key: Polygon.io API key (None = use mock data)
            use_cache: Enable local caching
            cache_dir: Directory for cache
            rate_limit_calls_per_minute: API rate limit
        """
        self.api_key = api_key
        self.use_cache = use_cache
        self.base_url = "https://api.polygon.io"

        # Initialize cache
        if use_cache:
            self.cache = DataCache(cache_dir=cache_dir)
        else:
            self.cache = None

        # Initialize rate limiter
        self.rate_limiter = RateLimiter(calls_per_minute=rate_limit_calls_per_minute)

        # Mock data generator (fallback)
        self.mock_generator = MockDataGenerator()

        # Track API usage
        self.api_calls_made = 0

    def _is_api_configured(self) -> bool:
        """Check if API key is configured."""
        return self.api_key is not None and self.api_key not in ['', 'YOUR_API_KEY_HERE', 'demo']

    def fetch_daily_bars(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        adjusted: bool = True,
        use_cache: bool = True
    ) -> HistoricalData:
        """
        Fetch daily OHLCV bars.

        Args:
            ticker: Stock ticker symbol
            start_date: Start date
            end_date: End date
            adjusted: Use split/dividend adjusted data
            use_cache: Check cache first

        Returns:
            HistoricalData with daily bars (timestamps in ET)
        """
        # Check cache first
        if use_cache and self.cache:
            cached_data = self.cache.get(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                interval='day'
            )
            if cached_data:
                return cached_data

        # Fetch from API or generate mock data
        if self._is_api_configured():
            data = self._fetch_from_polygon_daily(ticker, start_date, end_date, adjusted)
        else:
            print(f"⚠️  API key not configured, using mock data for {ticker}")
            data = self.mock_generator.generate_daily_bars(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date
            )

        # Cache the result
        if use_cache and self.cache:
            self.cache.set(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                interval='day',
                data=data
            )

        return data

    def _fetch_from_polygon_daily(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        adjusted: bool
    ) -> HistoricalData:
        """
        Fetch daily bars from Polygon.io API.

        Timestamps are converted from UTC milliseconds to naive ET datetimes.

        Args:
            ticker: Stock ticker
            start_date: Start date
            end_date: End date
            adjusted: Use adjusted data

        Returns:
            HistoricalData with ET timestamps
        """
        self.rate_limiter.wait_if_needed()

        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        url = (f"{self.base_url}/v2/aggs/ticker/{ticker}/range/1/day/"
               f"{start_str}/{end_str}")

        params = {
            'adjusted': 'true' if adjusted else 'false',
            'sort': 'asc',
            'limit': 50000,
            'apiKey': self.api_key
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            self.api_calls_made += 1

            data = response.json()

            if data.get('status') != 'OK':
                raise ValueError(f"API returned status: {data.get('status')}")

            results = data.get('results', [])

            if not results:
                raise ValueError(f"No data returned for {ticker}")

            bars = []
            for result in results:
                bar = BarData(
                    timestamp=_utc_ms_to_et(result['t']),
                    open=result['o'],
                    high=result['h'],
                    low=result['l'],
                    close=result['c'],
                    volume=result['v'],
                    vwap=result.get('vw'),
                    transactions=result.get('n')
                )
                bars.append(bar)

            metadata = StockMetadata(
                ticker=ticker,
                name=ticker,
                exchange="Unknown",
                is_active=True
            )

            return HistoricalData(
                ticker=ticker,
                bars=bars,
                metadata=metadata,
                data_source='polygon',
                fetch_timestamp=datetime.now()
            )

        except requests.exceptions.RequestException as e:
            print(f"❌ API request failed for {ticker}: {e}")
            print(f"   Falling back to mock data")
            return self.mock_generator.generate_daily_bars(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date
            )

    def fetch_intraday_bars(
        self,
        ticker: str,
        date: datetime,
        interval_minutes: int = 1,
        use_cache: bool = True
    ) -> HistoricalData:
        """
        Fetch intraday bars for a single trading day.

        Includes pre-market (04:00 ET) and after-hours (up to 20:00 ET) bars
        when available from Polygon. The engine filters by time window.

        Args:
            ticker: Stock ticker
            date: Trading date
            interval_minutes: Bar interval (1, 5, 15, etc.)
            use_cache: Check cache first

        Returns:
            HistoricalData with intraday bars (timestamps in ET)
        """
        start_date = datetime.combine(date.date(), datetime.min.time())
        end_date = datetime.combine(date.date(), datetime.max.time())
        interval_str = f"{interval_minutes}min"

        # Check cache
        if use_cache and self.cache:
            cached_data = self.cache.get(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                interval=interval_str
            )
            if cached_data:
                return cached_data

        # Fetch from API or generate mock
        from_api = False
        if self._is_api_configured():
            data, from_api = self._fetch_from_polygon_intraday(ticker, date, interval_minutes)
        else:
            print(f"⚠️  API key not configured, using mock data for {ticker}")
            data = self.mock_generator.generate_intraday_bars(
                ticker=ticker,
                date=date,
                interval_minutes=interval_minutes
            )

        # Only cache real API data — never cache fallback mock data
        if use_cache and self.cache and from_api:
            self.cache.set(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                interval=interval_str,
                data=data
            )

        return data

    def _fetch_from_polygon_intraday(
        self,
        ticker: str,
        date: datetime,
        interval_minutes: int
    ) -> HistoricalData:
        """
        Fetch intraday bars from Polygon.io.

        Polygon returns all bars for the calendar date, starting from
        pre-market (04:00 ET). Timestamps are converted from UTC milliseconds
        to naive ET datetimes so the engine's time constants work correctly.

        Args:
            ticker: Stock ticker
            date: Trading date
            interval_minutes: Bar interval

        Returns:
            HistoricalData with ET timestamps (includes pre-market bars)
        """
        self.rate_limiter.wait_if_needed()

        date_str = date.strftime('%Y-%m-%d')

        url = (f"{self.base_url}/v2/aggs/ticker/{ticker}/range/"
               f"{interval_minutes}/minute/{date_str}/{date_str}")

        params = {
            'adjusted': 'true',
            'sort': 'asc',
            'limit': 50000,
            'apiKey': self.api_key
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            self.api_calls_made += 1

            data = response.json()

            if data.get('status') != 'OK':
                raise ValueError(f"API returned status: {data.get('status')}")

            results = data.get('results', [])

            if not results:
                raise ValueError(f"No intraday data for {ticker} on {date_str}")

            bars = []
            for result in results:
                bar = BarData(
                    timestamp=_utc_ms_to_et(result['t']),
                    open=result['o'],
                    high=result['h'],
                    low=result['l'],
                    close=result['c'],
                    volume=result['v'],
                    vwap=result.get('vw'),
                    transactions=result.get('n')
                )
                bars.append(bar)

            return HistoricalData(
                ticker=ticker,
                bars=bars,
                data_source='polygon',
                fetch_timestamp=datetime.now()
            ), True

        except requests.exceptions.RequestException as e:
            # Retry up to 3 times with backoff before falling back to mock
            import time
            for attempt in range(1, 4):
                wait = attempt * 10
                print(f"❌ API request failed for {ticker} intraday (attempt {attempt}/3): {e}")
                print(f"   Retrying in {wait}s...")
                time.sleep(wait)
                try:
                    self.rate_limiter.wait_if_needed()
                    response = requests.get(url, params=params, timeout=30)
                    response.raise_for_status()
                    self.api_calls_made += 1
                    data = response.json()
                    results = data.get('results', [])
                    bars = []
                    for result in results:
                        bar = BarData(
                            timestamp=_utc_ms_to_et(result['t']),
                            open=result['o'],
                            high=result['h'],
                            low=result['l'],
                            close=result['c'],
                            volume=result['v'],
                            vwap=result.get('vw'),
                            transactions=result.get('n')
                        )
                        bars.append(bar)
                    return HistoricalData(
                        ticker=ticker,
                        bars=bars,
                        data_source='polygon',
                        fetch_timestamp=datetime.now()
                    ), True
                except requests.exceptions.RequestException:
                    continue
            print(f"   All retries failed — skipping {ticker} {date.date()}")
            return self.mock_generator.generate_intraday_bars(
                ticker=ticker,
                date=date,
                interval_minutes=interval_minutes
            ), False

    def get_api_usage(self) -> dict:
        """
        Get API usage statistics.

        Returns:
            Dict with API usage stats
        """
        cache_stats = self.cache.get_cache_stats() if self.cache else {}

        return {
            'api_configured': self._is_api_configured(),
            'api_calls_made': self.api_calls_made,
            'cache_enabled': self.use_cache,
            'cache_stats': cache_stats
        }

    def __repr__(self) -> str:
        """String representation."""
        status = "configured" if self._is_api_configured() else "mock mode"
        return (f"PolygonDataFetcher(status={status}, "
                f"calls={self.api_calls_made}, "
                f"cache={self.use_cache})")


if __name__ == '__main__':
    print("Testing PolygonDataFetcher...\n")

    fetcher = PolygonDataFetcher(api_key=None, use_cache=True)
    print(f"Fetcher: {fetcher}\n")

    print("Fetching daily data for AAPL...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)

    daily_data = fetcher.fetch_daily_bars(
        ticker="AAPL",
        start_date=start_date,
        end_date=end_date
    )

    print(f"Fetched: {daily_data}")
    print(f"Bars: {len(daily_data.bars)}")
    print(f"Date range: {daily_data.get_date_range()}\n")

    print("Fetching intraday data for SPY...")
    intraday_data = fetcher.fetch_intraday_bars(
        ticker="SPY",
        date=datetime.now(),
        interval_minutes=5
    )

    print(f"Fetched: {intraday_data}")
    print(f"Bars: {len(intraday_data.bars)}\n")

    usage = fetcher.get_api_usage()
    print("API Usage:")
    for key, value in usage.items():
        print(f"  {key}: {value}")
