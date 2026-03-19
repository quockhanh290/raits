"""
RAITS Mock Data Generator

Generates synthetic market data for testing without API access.
Simulates realistic price action, volume patterns, and market regimes.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, time
from typing import List, Optional
from raits_data_models import BarData, HistoricalData, StockMetadata, SplitDividend


class MockDataGenerator:
    """
    Generates synthetic OHLCV data for testing.
    
    Creates realistic-looking price action with:
    - Trending periods
    - Mean-reverting periods
    - Volatility clusters
    - Gap patterns
    - Volume variation
    """
    
    def __init__(self, seed: Optional[int] = 42):
        """
        Initialize mock data generator.
        
        Args:
            seed: Random seed for reproducibility
        """
        self.seed = seed
        if seed is not None:
            np.random.seed(seed)
    
    def generate_daily_bars(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        initial_price: float = 100.0,
        volatility: float = 0.02,
        trend: float = 0.0001,
        include_gaps: bool = True
    ) -> HistoricalData:
        """
        Generate daily OHLCV bars.
        
        Args:
            ticker: Stock ticker symbol
            start_date: Start date
            end_date: End date
            initial_price: Starting price
            volatility: Daily volatility (std dev of returns)
            trend: Daily drift (mean return)
            include_gaps: Include random gaps (overnight moves)
        
        Returns:
            HistoricalData with daily bars
        """
        # Generate trading days (skip weekends)
        dates = pd.bdate_range(start=start_date, end=end_date)
        
        bars = []
        current_price = initial_price
        
        for date in dates:
            # Opening gap (if enabled)
            if include_gaps and np.random.random() < 0.15:  # 15% chance of gap
                gap = np.random.normal(0, volatility * 1.5)
                current_price *= (1 + gap)
            
            # Daily price action
            open_price = current_price
            
            # Generate intraday volatility
            daily_return = np.random.normal(trend, volatility)
            close_price = open_price * (1 + daily_return)
            
            # High/Low based on intraday range
            intraday_range = abs(np.random.normal(0, volatility * 0.5))
            high_price = max(open_price, close_price) * (1 + intraday_range)
            low_price = min(open_price, close_price) * (1 - intraday_range)
            
            # Volume (log-normal distribution)
            base_volume = 1_000_000
            volume = int(np.random.lognormal(np.log(base_volume), 0.5))
            
            # VWAP (roughly between open and close)
            vwap = (open_price + close_price + high_price + low_price) / 4
            
            # Transactions (roughly proportional to volume)
            transactions = int(volume / np.random.uniform(100, 500))
            
            bar = BarData(
                timestamp=datetime.combine(date.date(), time(16, 0)),  # 4 PM close
                open=round(open_price, 2),
                high=round(high_price, 2),
                low=round(low_price, 2),
                close=round(close_price, 2),
                volume=volume,
                vwap=round(vwap, 2),
                transactions=transactions
            )
            
            bars.append(bar)
            current_price = close_price
        
        # Create metadata
        metadata = StockMetadata(
            ticker=ticker,
            name=f"{ticker} Mock Company",
            exchange="MOCK",
            sector="Technology",
            industry="Software",
            market_cap=current_price * 100_000_000,  # Assume 100M shares
            is_active=True
        )
        
        return HistoricalData(
            ticker=ticker,
            bars=bars,
            metadata=metadata,
            data_source='mock',
            fetch_timestamp=datetime.now()
        )
    
    def generate_intraday_bars(
        self,
        ticker: str,
        date: datetime,
        interval_minutes: int = 1,
        initial_price: float = 100.0,
        volatility: float = 0.001,  # Per-minute volatility
        include_opening_range: bool = True
    ) -> HistoricalData:
        """
        Generate intraday minute bars for a single trading day.
        
        Args:
            ticker: Stock ticker
            date: Trading date
            interval_minutes: Bar interval (1, 5, 15 minutes)
            initial_price: Opening price
            volatility: Per-interval volatility
            include_opening_range: Simulate ORB-friendly opening range
        
        Returns:
            HistoricalData with intraday bars
        """
        # Market hours: 9:30 AM - 4:00 PM ET (390 minutes)
        market_open = datetime.combine(date.date(), time(9, 30))
        market_close = datetime.combine(date.date(), time(16, 0))
        
        # Generate timestamps
        timestamps = []
        current_time = market_open
        while current_time <= market_close:
            timestamps.append(current_time)
            current_time += timedelta(minutes=interval_minutes)
        
        bars = []
        current_price = initial_price
        
        for i, timestamp in enumerate(timestamps):
            # Opening range behavior (first 15 minutes)
            if include_opening_range and i < (15 // interval_minutes):
                # Lower volatility, tighter range during OR
                interval_vol = volatility * 0.5
            else:
                interval_vol = volatility
            
            # Price movement
            open_price = current_price
            price_change = np.random.normal(0, interval_vol)
            close_price = open_price * (1 + price_change)
            
            # High/Low
            range_mult = abs(np.random.normal(0, interval_vol * 0.3))
            high_price = max(open_price, close_price) * (1 + range_mult)
            low_price = min(open_price, close_price) * (1 - range_mult)
            
            # Volume (higher at open and close)
            if i < 10 or i > len(timestamps) - 10:
                volume_mult = 2.0  # 2x volume at open/close
            else:
                volume_mult = 1.0
            
            base_volume = 50_000 // interval_minutes  # Scale by interval
            volume = int(np.random.lognormal(np.log(base_volume * volume_mult), 0.3))
            
            # VWAP
            vwap = (open_price + close_price + high_price + low_price) / 4
            
            # Transactions
            transactions = int(volume / np.random.uniform(50, 200))
            
            bar = BarData(
                timestamp=timestamp,
                open=round(open_price, 2),
                high=round(high_price, 2),
                low=round(low_price, 2),
                close=round(close_price, 2),
                volume=volume,
                vwap=round(vwap, 2),
                transactions=transactions
            )
            
            bars.append(bar)
            current_price = close_price
        
        return HistoricalData(
            ticker=ticker,
            bars=bars,
            data_source='mock',
            fetch_timestamp=datetime.now()
        )
    
    def generate_regime_data(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        initial_price: float = 100.0
    ) -> HistoricalData:
        """
        Generate data with distinct market regimes.
        
        Creates three regime periods:
        - Normal: Low volatility, slight uptrend
        - Volatile: High volatility, no trend
        - Stress: Very high volatility, downtrend
        
        Args:
            ticker: Stock ticker
            start_date: Start date
            end_date: End date
            initial_price: Starting price
        
        Returns:
            HistoricalData with regime-based patterns
        """
        dates = pd.bdate_range(start=start_date, end=end_date)
        total_days = len(dates)
        
        # Divide into regime periods
        regime_1_end = total_days // 3
        regime_2_end = 2 * total_days // 3
        
        bars = []
        current_price = initial_price
        
        for i, date in enumerate(dates):
            # Determine current regime
            if i < regime_1_end:
                # Normal regime
                volatility = 0.01
                trend = 0.0005
                regime_name = "Normal"
            elif i < regime_2_end:
                # Volatile regime
                volatility = 0.03
                trend = 0.0
                regime_name = "Volatile"
            else:
                # Stress regime
                volatility = 0.04
                trend = -0.002
                regime_name = "Stress"
            
            # Generate bar with regime parameters
            open_price = current_price
            daily_return = np.random.normal(trend, volatility)
            close_price = open_price * (1 + daily_return)
            
            intraday_range = abs(np.random.normal(0, volatility * 0.5))
            high_price = max(open_price, close_price) * (1 + intraday_range)
            low_price = min(open_price, close_price) * (1 - intraday_range)
            
            # Volume increases with volatility
            base_volume = 1_000_000
            volume_mult = 1 + (volatility - 0.01) * 50  # More vol = more volume
            volume = int(np.random.lognormal(np.log(base_volume * volume_mult), 0.5))
            
            vwap = (open_price + close_price + high_price + low_price) / 4
            transactions = int(volume / np.random.uniform(100, 500))
            
            bar = BarData(
                timestamp=datetime.combine(date.date(), time(16, 0)),
                open=round(open_price, 2),
                high=round(high_price, 2),
                low=round(low_price, 2),
                close=round(close_price, 2),
                volume=volume,
                vwap=round(vwap, 2),
                transactions=transactions
            )
            
            bars.append(bar)
            current_price = close_price
        
        return HistoricalData(
            ticker=ticker,
            bars=bars,
            data_source='mock_regime',
            fetch_timestamp=datetime.now()
        )
    
    def generate_split_event(
        self,
        ticker: str,
        split_date: datetime,
        split_ratio: float = 2.0
    ) -> SplitDividend:
        """
        Generate a stock split event.
        
        Args:
            ticker: Stock ticker
            split_date: Date of split
            split_ratio: Split ratio (2.0 = 2-for-1)
        
        Returns:
            SplitDividend object
        """
        return SplitDividend(
            ticker=ticker,
            ex_date=split_date.date(),
            action_type='split',
            split_ratio=split_ratio
        )
    
    def generate_dividend_event(
        self,
        ticker: str,
        ex_date: datetime,
        dividend_amount: float = 0.50
    ) -> SplitDividend:
        """
        Generate a dividend event.
        
        Args:
            ticker: Stock ticker
            ex_date: Ex-dividend date
            dividend_amount: Dividend per share ($)
        
        Returns:
            SplitDividend object
        """
        return SplitDividend(
            ticker=ticker,
            ex_date=ex_date.date(),
            action_type='dividend',
            dividend_amount=dividend_amount
        )


# Convenience functions for quick mock data generation

def generate_mock_daily_data(
    ticker: str = "MOCK",
    days: int = 252,
    **kwargs
) -> HistoricalData:
    """
    Quick function to generate mock daily data.
    
    Args:
        ticker: Stock ticker
        days: Number of trading days
        **kwargs: Additional arguments for generate_daily_bars
    
    Returns:
        HistoricalData with daily bars
    """
    generator = MockDataGenerator()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days * 1.5)  # Account for weekends
    
    return generator.generate_daily_bars(
        ticker=ticker,
        start_date=start_date,
        end_date=end_date,
        **kwargs
    )


def generate_mock_intraday_data(
    ticker: str = "MOCK",
    date: Optional[datetime] = None,
    interval_minutes: int = 1,
    **kwargs
) -> HistoricalData:
    """
    Quick function to generate mock intraday data.
    
    Args:
        ticker: Stock ticker
        date: Trading date (defaults to today)
        interval_minutes: Bar interval
        **kwargs: Additional arguments for generate_intraday_bars
    
    Returns:
        HistoricalData with intraday bars
    """
    if date is None:
        date = datetime.now()
    
    generator = MockDataGenerator()
    return generator.generate_intraday_bars(
        ticker=ticker,
        date=date,
        interval_minutes=interval_minutes,
        **kwargs
    )


if __name__ == '__main__':
    # Example usage
    print("Generating mock data examples...\n")
    
    # Daily data
    daily_data = generate_mock_daily_data(ticker="AAPL", days=252)
    print(f"Daily data: {daily_data}")
    print(f"Date range: {daily_data.get_date_range()}")
    print(f"\nFirst 5 bars:")
    for bar in daily_data.bars[:5]:
        print(f"  {bar.timestamp.date()}: O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume:,}")
    
    # Intraday data
    print("\n" + "="*60)
    intraday_data = generate_mock_intraday_data(ticker="SPY", interval_minutes=5)
    print(f"\nIntraday data: {intraday_data}")
    print(f"Total bars: {len(intraday_data.bars)}")
    print(f"\nFirst 5 bars:")
    for bar in intraday_data.bars[:5]:
        print(f"  {bar.timestamp.time()}: O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume:,}")
    
    # Regime data
    print("\n" + "="*60)
    generator = MockDataGenerator()
    regime_data = generator.generate_regime_data(
        ticker="TEST",
        start_date=datetime(2024, 1, 1),
        end_date=datetime(2024, 12, 31)
    )
    print(f"\nRegime data: {regime_data}")
    
    # Convert to DataFrame
    df = regime_data.to_dataframe()
    print(f"\nDataFrame shape: {df.shape}")
    print(df.head())
