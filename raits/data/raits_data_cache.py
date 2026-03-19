"""
RAITS Data Cache Manager

Implements intelligent caching to minimize API calls and costs.
Stores data locally in efficient formats (Parquet, HDF5).
"""

import os
import pickle
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import pandas as pd
from raits.data.raits_data_models import HistoricalData


class DataCache:
    """
    Manages local caching of historical data.
    
    Features:
    - Saves data in Parquet format (efficient compression)
    - Metadata stored separately (JSON)
    - Configurable expiry times
    - Cache key based on query parameters
    - Automatic cleanup of expired entries
    """
    
    def __init__(
        self,
        cache_dir: str = './raits/data/cache',
        default_expiry_hours: int = 24
    ):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Directory for cache storage
            default_expiry_hours: Default cache expiry time
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.default_expiry_hours = default_expiry_hours
        
        # Separate directories for different data types
        self.data_dir = self.cache_dir / 'data'
        self.metadata_dir = self.cache_dir / 'metadata'
        
        self.data_dir.mkdir(exist_ok=True)
        self.metadata_dir.mkdir(exist_ok=True)
    
    def _generate_cache_key(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = 'day'
    ) -> str:
        """
        Generate unique cache key for data request.
        
        Args:
            ticker: Stock ticker
            start_date: Start date
            end_date: End date
            interval: Data interval (day, minute, 5min, etc.)
        
        Returns:
            Cache key string
        """
        # Create deterministic key from parameters
        key_string = f"{ticker}_{start_date.date()}_{end_date.date()}_{interval}"
        
        # Hash for filesystem safety
        key_hash = hashlib.md5(key_string.encode()).hexdigest()
        
        # Readable prefix + hash
        return f"{ticker}_{interval}_{key_hash}"
    
    def _get_cache_path(self, cache_key: str) -> tuple[Path, Path]:
        """
        Get paths for data and metadata files.
        
        Args:
            cache_key: Cache key
        
        Returns:
            (data_path, metadata_path)
        """
        data_path = self.data_dir / f"{cache_key}.parquet"
        metadata_path = self.metadata_dir / f"{cache_key}.pkl"
        
        return data_path, metadata_path
    
    def get(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = 'day',
        max_age_hours: Optional[int] = None
    ) -> Optional[HistoricalData]:
        """
        Retrieve data from cache if available and not expired.
        
        Args:
            ticker: Stock ticker
            start_date: Start date
            end_date: End date
            interval: Data interval
            max_age_hours: Override default expiry time
        
        Returns:
            HistoricalData if found and valid, None otherwise
        """
        cache_key = self._generate_cache_key(ticker, start_date, end_date, interval)
        data_path, metadata_path = self._get_cache_path(cache_key)
        
        # Check if cache exists
        if not data_path.exists() or not metadata_path.exists():
            return None
        
        # Check expiry
        max_age = max_age_hours or self.default_expiry_hours
        file_age = datetime.now() - datetime.fromtimestamp(metadata_path.stat().st_mtime)
        
        if file_age > timedelta(hours=max_age):
            # Cache expired
            self._delete_cache(cache_key)
            return None
        
        try:
            # Load metadata
            with open(metadata_path, 'rb') as f:
                metadata = pickle.load(f)
            
            # Load data
            df = pd.read_parquet(data_path)
            
            # Reconstruct HistoricalData
            historical_data = HistoricalData.from_dataframe(
                ticker=ticker,
                df=df,
                metadata=metadata.get('stock_metadata'),
                splits_dividends=metadata.get('splits_dividends'),
                data_source='cache',
                fetch_timestamp=metadata.get('fetch_timestamp')
            )
            
            return historical_data
            
        except Exception as e:
            # Cache corrupted, delete it
            print(f"Warning: Cache corrupted for {cache_key}: {e}")
            self._delete_cache(cache_key)
            return None
    
    def set(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str,
        data: HistoricalData
    ) -> None:
        """
        Save data to cache.
        
        Args:
            ticker: Stock ticker
            start_date: Start date
            end_date: End date
            interval: Data interval
            data: HistoricalData to cache
        """
        cache_key = self._generate_cache_key(ticker, start_date, end_date, interval)
        data_path, metadata_path = self._get_cache_path(cache_key)
        
        try:
            # Save data as Parquet (efficient compression)
            df = data.to_dataframe()
            df.to_parquet(data_path, compression='snappy')
            
            # Save metadata separately
            metadata = {
                'ticker': data.ticker,
                'stock_metadata': data.metadata,
                'splits_dividends': data.splits_dividends,
                'fetch_timestamp': data.fetch_timestamp,
                'cache_timestamp': datetime.now()
            }
            
            with open(metadata_path, 'wb') as f:
                pickle.dump(metadata, f)
                
        except Exception as e:
            print(f"Error caching data for {cache_key}: {e}")
            # Clean up partial save
            self._delete_cache(cache_key)
    
    def _delete_cache(self, cache_key: str) -> None:
        """Delete cache files for a given key."""
        data_path, metadata_path = self._get_cache_path(cache_key)
        
        if data_path.exists():
            data_path.unlink()
        if metadata_path.exists():
            metadata_path.unlink()
    
    def clear(
        self,
        ticker: Optional[str] = None,
        older_than_hours: Optional[int] = None
    ) -> int:
        """
        Clear cache entries.
        
        Args:
            ticker: Clear only this ticker (None = all)
            older_than_hours: Clear only entries older than this
        
        Returns:
            Number of entries cleared
        """
        cleared = 0
        
        for metadata_file in self.metadata_dir.glob('*.pkl'):
            cache_key = metadata_file.stem
            
            # Filter by ticker if specified
            if ticker and not cache_key.startswith(ticker):
                continue
            
            # Filter by age if specified
            if older_than_hours:
                file_age = datetime.now() - datetime.fromtimestamp(metadata_file.stat().st_mtime)
                if file_age < timedelta(hours=older_than_hours):
                    continue
            
            # Delete
            self._delete_cache(cache_key)
            cleared += 1
        
        return cleared
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dict with cache stats
        """
        data_files = list(self.data_dir.glob('*.parquet'))
        metadata_files = list(self.metadata_dir.glob('*.pkl'))
        
        # Calculate total size
        total_size = sum(f.stat().st_size for f in data_files)
        total_size += sum(f.stat().st_size for f in metadata_files)
        
        # Size in MB
        size_mb = total_size / (1024 * 1024)
        
        return {
            'total_entries': len(data_files),
            'total_size_mb': round(size_mb, 2),
            'data_files': len(data_files),
            'metadata_files': len(metadata_files),
            'cache_dir': str(self.cache_dir)
        }
    
    def __repr__(self) -> str:
        """String representation."""
        stats = self.get_cache_stats()
        return (f"DataCache(entries={stats['total_entries']}, "
               f"size={stats['total_size_mb']:.1f}MB, "
               f"dir={stats['cache_dir']})")


if __name__ == '__main__':
    # Example usage
    from raits_mock_data import generate_mock_daily_data
    
    print("Testing DataCache...\n")
    
    # Create cache
    cache = DataCache(cache_dir='./test_cache')
    print(f"Cache initialized: {cache}\n")
    
    # Generate mock data
    print("Generating mock data...")
    data = generate_mock_daily_data(ticker="AAPL", days=100)
    print(f"Generated: {data}\n")
    
    # Save to cache
    print("Saving to cache...")
    start_date = data.bars[0].timestamp
    end_date = data.bars[-1].timestamp
    cache.set(
        ticker="AAPL",
        start_date=start_date,
        end_date=end_date,
        interval='day',
        data=data
    )
    
    # Check stats
    stats = cache.get_cache_stats()
    print(f"Cache stats: {stats}\n")
    
    # Retrieve from cache
    print("Retrieving from cache...")
    cached_data = cache.get(
        ticker="AAPL",
        start_date=start_date,
        end_date=end_date,
        interval='day'
    )
    
    if cached_data:
        print(f"Retrieved: {cached_data}")
        print(f"Bars match: {len(cached_data.bars) == len(data.bars)}")
        print(f"Source: {cached_data.data_source}")
    else:
        print("Cache miss!")
    
    # Clean up test cache
    import shutil
    shutil.rmtree('./test_cache')
    print("\nTest cache cleaned up.")
