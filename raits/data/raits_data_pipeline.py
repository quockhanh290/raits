"""
RAITS Data Pipeline

Main interface for all data operations.
Coordinates fetching, caching, and validation.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict
from pathlib import Path
import pandas as pd

from raits_data_models import HistoricalData, DataQualityReport
from raits_polygon_fetcher import PolygonDataFetcher
from raits_data_cache import DataCache
from raits_mock_data import MockDataGenerator


class DataPipeline:
    """
    High-level data pipeline for RAITS.
    
    Provides simple interface for:
    - Fetching historical data
    - Building trading universe
    - Data quality validation
    - Batch downloads
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: str = './raits/data/cache',
        use_cache: bool = True
    ):
        """
        Initialize data pipeline.
        
        Args:
            api_key: Polygon.io API key (None = mock mode)
            cache_dir: Cache directory
            use_cache: Enable caching
        """
        self.fetcher = PolygonDataFetcher(
            api_key=api_key,
            use_cache=use_cache,
            cache_dir=cache_dir
        )
        
        self.cache = DataCache(cache_dir=cache_dir) if use_cache else None
        self.mock_generator = MockDataGenerator()
    
    def get_daily_data(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        use_cache: bool = True
    ) -> HistoricalData:
        """
        Get daily OHLCV data for a ticker.
        
        Args:
            ticker: Stock ticker
            start_date: Start date
            end_date: End date
            use_cache: Use cached data if available
        
        Returns:
            HistoricalData with daily bars
        """
        return self.fetcher.fetch_daily_bars(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            use_cache=use_cache
        )
    
    def get_intraday_data(
        self,
        ticker: str,
        date: datetime,
        interval_minutes: int = 1,
        use_cache: bool = True
    ) -> HistoricalData:
        """
        Get intraday bars for a single trading day.
        
        Args:
            ticker: Stock ticker
            date: Trading date
            interval_minutes: Bar interval
            use_cache: Use cached data
        
        Returns:
            HistoricalData with intraday bars
        """
        return self.fetcher.fetch_intraday_bars(
            ticker=ticker,
            date=date,
            interval_minutes=interval_minutes,
            use_cache=use_cache
        )
    
    def build_universe(
        self,
        tickers: List[str],
        start_date: datetime,
        end_date: datetime,
        show_progress: bool = True
    ) -> Dict[str, HistoricalData]:
        """
        Fetch data for multiple tickers (build trading universe).
        
        Args:
            tickers: List of stock tickers
            start_date: Start date
            end_date: End date
            show_progress: Show progress bar
        
        Returns:
            Dict mapping ticker -> HistoricalData
        """
        universe = {}
        
        if show_progress:
            try:
                from tqdm import tqdm
                ticker_iter = tqdm(tickers, desc="Building universe")
            except ImportError:
                ticker_iter = tickers
                print(f"Fetching data for {len(tickers)} tickers...")
        else:
            ticker_iter = tickers
        
        for ticker in ticker_iter:
            try:
                data = self.get_daily_data(ticker, start_date, end_date)
                universe[ticker] = data
            except Exception as e:
                print(f"⚠️  Failed to fetch {ticker}: {e}")
                continue
        
        return universe
    
    def validate_data_quality(
        self,
        data: HistoricalData,
        max_missing_pct: float = 0.05,
        check_anomalies: bool = True
    ) -> DataQualityReport:
        """
        Validate data quality (Step 1.4 preview).
        
        Args:
            data: Historical data to validate
            max_missing_pct: Max allowed missing data %
            check_anomalies: Check for price/volume anomalies
        
        Returns:
            DataQualityReport
        """
        df = data.to_dataframe()
        
        # Check for missing bars (gaps in expected trading days)
        expected_bars = len(pd.bdate_range(
            start=data.bars[0].timestamp,
            end=data.bars[-1].timestamp
        ))
        actual_bars = len(data.bars)
        missing_bars = expected_bars - actual_bars
        missing_pct = (missing_bars / expected_bars) * 100 if expected_bars > 0 else 0
        
        # Detect gaps
        timestamps = pd.DatetimeIndex([bar.timestamp for bar in data.bars])
        gaps = timestamps.to_series().diff() > pd.Timedelta(days=3)
        gap_dates = timestamps[gaps].tolist()
        
        # Price anomalies
        price_anomalies = []
        if check_anomalies:
            # Check for extreme price jumps (>20% single day)
            returns = df['close'].pct_change()
            extreme_moves = returns[abs(returns) > 0.20]
            
            for date, ret in extreme_moves.items():
                price_anomalies.append(
                    f"{date.date()}: {ret*100:.1f}% move"
                )
        
        # Volume anomalies
        volume_anomalies = []
        if check_anomalies:
            # Check for zero volume days
            zero_volume = df[df['volume'] == 0]
            if not zero_volume.empty:
                volume_anomalies.append(
                    f"{len(zero_volume)} days with zero volume"
                )
        
        # Overall pass/fail
        passed = (
            missing_pct <= max_missing_pct * 100 and
            len(price_anomalies) < 5 and  # Max 5 extreme moves
            len(volume_anomalies) == 0
        )
        
        return DataQualityReport(
            ticker=data.ticker,
            total_bars=actual_bars,
            missing_bars=missing_bars,
            missing_percentage=missing_pct,
            has_gaps=len(gap_dates) > 0,
            gap_dates=[g.date() for g in gap_dates],
            has_splits=len([s for s in data.splits_dividends if s.action_type == 'split']) > 0,
            has_dividends=len([s for s in data.splits_dividends if s.action_type == 'dividend']) > 0,
            price_anomalies=price_anomalies,
            volume_anomalies=volume_anomalies,
            passed=passed
        )
    
    def export_to_csv(
        self,
        data: HistoricalData,
        output_path: str
    ) -> None:
        """
        Export data to CSV file.
        
        Args:
            data: Historical data
            output_path: Output file path
        """
        df = data.to_dataframe()
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        df.to_csv(output_file)
        print(f"✓ Exported {data.ticker} to {output_file}")
    
    def get_pipeline_stats(self) -> Dict:
        """
        Get pipeline statistics.
        
        Returns:
            Dict with pipeline stats
        """
        usage = self.fetcher.get_api_usage()
        
        return {
            'api_configured': usage['api_configured'],
            'api_calls': usage['api_calls_made'],
            'cache_enabled': usage['cache_enabled'],
            'cache_stats': usage.get('cache_stats', {})
        }
    
    def clear_cache(
        self,
        ticker: Optional[str] = None,
        older_than_hours: Optional[int] = None
    ) -> int:
        """
        Clear cache entries.
        
        Args:
            ticker: Clear specific ticker (None = all)
            older_than_hours: Clear only old entries
        
        Returns:
            Number of entries cleared
        """
        if self.cache:
            return self.cache.clear(ticker=ticker, older_than_hours=older_than_hours)
        return 0


# Convenience functions for common operations

def quick_daily_data(
    ticker: str,
    days: int = 252,
    api_key: Optional[str] = None
) -> HistoricalData:
    """
    Quick fetch of daily data (last N days).
    
    Args:
        ticker: Stock ticker
        days: Number of trading days
        api_key: Polygon API key (None = mock)
    
    Returns:
        HistoricalData
    """
    pipeline = DataPipeline(api_key=api_key)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=int(days * 1.5))  # Account for weekends
    
    return pipeline.get_daily_data(ticker, start_date, end_date)


def quick_universe(
    tickers: List[str],
    days: int = 252,
    api_key: Optional[str] = None
) -> Dict[str, HistoricalData]:
    """
    Quick build of trading universe.
    
    Args:
        tickers: List of tickers
        days: Number of days
        api_key: Polygon API key
    
    Returns:
        Dict of ticker -> HistoricalData
    """
    pipeline = DataPipeline(api_key=api_key)
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=int(days * 1.5))
    
    return pipeline.build_universe(tickers, start_date, end_date)


if __name__ == '__main__':
    # Example usage
    print("RAITS Data Pipeline Example\n")
    print("=" * 60)
    
    # Initialize pipeline (mock mode - no API key)
    pipeline = DataPipeline(api_key=None)
    
    # Fetch single ticker
    print("\n1. Fetching daily data for AAPL...")
    aapl_data = pipeline.get_daily_data(
        ticker="AAPL",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31)
    )
    print(f"   {aapl_data}")
    
    # Validate data quality
    print("\n2. Validating data quality...")
    quality = pipeline.validate_data_quality(aapl_data)
    print(f"   {quality}")
    
    # Build universe
    print("\n3. Building trading universe...")
    universe = pipeline.build_universe(
        tickers=["AAPL", "MSFT", "GOOGL"],
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31),
        show_progress=True
    )
    print(f"   Loaded {len(universe)} tickers")
    
    # Get pipeline stats
    print("\n4. Pipeline statistics:")
    stats = pipeline.get_pipeline_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")
    
    print("\n" + "=" * 60)
    print("✓ Data pipeline ready for RAITS development!")
