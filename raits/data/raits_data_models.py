"""
RAITS Data Models

Defines the data structures used throughout the RAITS system.
All data conforms to these schemas for consistency.
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, List
import pandas as pd


@dataclass
class BarData:
    """
    Single OHLCV bar (candlestick) data.
    
    Represents one time period of price action.
    Used for intraday (1min, 5min, 15min) and daily bars.
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None  # Volume-weighted average price
    transactions: Optional[int] = None  # Number of trades
    
    def __post_init__(self):
        """Validate bar data after initialization."""
        # Price validation
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than low ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError(f"High ({self.high}) must be >= open and close")
        if self.low > self.open or self.low > self.close:
            raise ValueError(f"Low ({self.low}) must be <= open and close")
        
        # Volume validation
        if self.volume < 0:
            raise ValueError(f"Volume cannot be negative: {self.volume}")


@dataclass
class StockMetadata:
    """
    Metadata about a stock ticker.
    
    Used for filtering and validation.
    """
    ticker: str
    name: str
    exchange: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    is_active: bool = True
    delisted_date: Optional[date] = None
    
    def is_tradeable(self, as_of_date: date) -> bool:
        """Check if stock was tradeable on a given date."""
        if not self.is_active:
            if self.delisted_date and as_of_date >= self.delisted_date:
                return False
        return True


@dataclass
class SplitDividend:
    """
    Corporate action data (splits, dividends).
    
    Critical for Point-in-Time data accuracy.
    """
    ticker: str
    ex_date: date
    action_type: str  # 'split' or 'dividend'
    
    # For splits
    split_ratio: Optional[float] = None  # e.g., 2.0 for 2-for-1 split
    
    # For dividends
    dividend_amount: Optional[float] = None  # $ per share
    
    def __post_init__(self):
        """Validate corporate action data."""
        if self.action_type not in ['split', 'dividend']:
            raise ValueError(f"Invalid action_type: {self.action_type}")
        
        if self.action_type == 'split' and self.split_ratio is None:
            raise ValueError("Split must have split_ratio")
        
        if self.action_type == 'dividend' and self.dividend_amount is None:
            raise ValueError("Dividend must have dividend_amount")


class HistoricalData:
    """
    Container for historical price data with metadata.
    
    Provides convenient access to OHLCV data as both:
    - List of BarData objects (for iteration)
    - Pandas DataFrame (for analysis)
    """
    
    def __init__(
        self,
        ticker: str,
        bars: List[BarData],
        metadata: Optional[StockMetadata] = None,
        splits_dividends: Optional[List[SplitDividend]] = None,
        data_source: str = 'unknown',
        fetch_timestamp: Optional[datetime] = None
    ):
        """
        Initialize historical data container.
        
        Args:
            ticker: Stock ticker symbol
            bars: List of OHLCV bars
            metadata: Stock metadata
            splits_dividends: Corporate actions
            data_source: Where data came from ('polygon', 'cache', 'mock')
            fetch_timestamp: When data was fetched
        """
        self.ticker = ticker
        self.bars = sorted(bars, key=lambda x: x.timestamp)  # Ensure chronological order
        self.metadata = metadata
        self.splits_dividends = splits_dividends or []
        self.data_source = data_source
        self.fetch_timestamp = fetch_timestamp or datetime.now()
        
        # Validate
        if not bars:
            raise ValueError(f"No bars provided for {ticker}")
    
    def to_dataframe(self) -> pd.DataFrame:
        """
        Convert bars to pandas DataFrame.
        
        Returns:
            DataFrame with OHLCV data indexed by timestamp
        """
        data = {
            'timestamp': [bar.timestamp for bar in self.bars],
            'open': [bar.open for bar in self.bars],
            'high': [bar.high for bar in self.bars],
            'low': [bar.low for bar in self.bars],
            'close': [bar.close for bar in self.bars],
            'volume': [bar.volume for bar in self.bars],
            'vwap': [bar.vwap for bar in self.bars],
            'transactions': [bar.transactions for bar in self.bars],
        }
        
        df = pd.DataFrame(data)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        
        return df
    
    @classmethod
    def from_dataframe(
        cls,
        ticker: str,
        df: pd.DataFrame,
        **kwargs
    ) -> 'HistoricalData':
        """
        Create HistoricalData from pandas DataFrame.
        
        Args:
            ticker: Stock ticker
            df: DataFrame with OHLCV columns
            **kwargs: Additional arguments for HistoricalData constructor
        
        Returns:
            HistoricalData instance
        """
        # Reset index if timestamp is the index
        if df.index.name == 'timestamp' or isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
        
        bars = []
        for _, row in df.iterrows():
            bar = BarData(
                timestamp=pd.to_datetime(row['timestamp']),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=int(row['volume']),
                vwap=float(row['vwap']) if 'vwap' in row and pd.notna(row['vwap']) else None,
                transactions=int(row['transactions']) if 'transactions' in row and pd.notna(row['transactions']) else None,
            )
            bars.append(bar)
        
        return cls(ticker=ticker, bars=bars, **kwargs)
    
    def get_date_range(self) -> tuple[datetime, datetime]:
        """Get the date range of the data."""
        if not self.bars:
            raise ValueError("No bars available")
        return self.bars[0].timestamp, self.bars[-1].timestamp
    
    def __len__(self) -> int:
        """Number of bars."""
        return len(self.bars)
    
    def __repr__(self) -> str:
        """String representation."""
        if self.bars:
            start, end = self.get_date_range()
            return (f"HistoricalData(ticker={self.ticker}, "
                   f"bars={len(self.bars)}, "
                   f"range={start.date()} to {end.date()}, "
                   f"source={self.data_source})")
        return f"HistoricalData(ticker={self.ticker}, bars=0)"


@dataclass
class DataQualityReport:
    """
    Report on data quality issues.
    
    Used by data validation (Step 1.4).
    """
    ticker: str
    total_bars: int
    missing_bars: int
    missing_percentage: float
    has_gaps: bool
    gap_dates: List[date]
    has_splits: bool
    has_dividends: bool
    price_anomalies: List[str]  # List of anomaly descriptions
    volume_anomalies: List[str]
    passed: bool  # Overall pass/fail
    
    def __repr__(self) -> str:
        """String representation."""
        status = "✓ PASS" if self.passed else "✗ FAIL"
        return (f"DataQualityReport({self.ticker}): {status}\n"
               f"  Bars: {self.total_bars}, Missing: {self.missing_bars} ({self.missing_percentage:.1f}%)\n"
               f"  Gaps: {len(self.gap_dates)}, Splits: {self.has_splits}, Dividends: {self.has_dividends}\n"
               f"  Anomalies: {len(self.price_anomalies)} price, {len(self.volume_anomalies)} volume")
