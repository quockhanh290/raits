"""
RAITS Data Pipeline - Example Usage

Demonstrates how to use the data pipeline for common tasks.
Works in MOCK MODE without API key - perfect for learning and testing!
"""

from datetime import datetime, timedelta
from raits_data_pipeline import DataPipeline, quick_daily_data, quick_universe


def example_1_fetch_single_ticker():
    """Example 1: Fetch data for a single ticker."""
    print("\n" + "="*60)
    print("EXAMPLE 1: Fetch Single Ticker")
    print("="*60)
    
    # Initialize pipeline (no API key = mock mode)
    pipeline = DataPipeline(api_key=None, use_cache=True)
    
    # Define date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)  # 1 year
    
    # Fetch data
    print(f"\nFetching AAPL data from {start_date.date()} to {end_date.date()}...")
    data = pipeline.get_daily_data(
        ticker="AAPL",
        start_date=start_date,
        end_date=end_date
    )
    
    print(f"✓ Fetched: {data}")
    print(f"  Bars: {len(data.bars)}")
    print(f"  Date range: {data.get_date_range()}")
    print(f"  Data source: {data.data_source}")
    
    # Show first few bars
    print("\n  First 5 bars:")
    for bar in data.bars[:5]:
        print(f"    {bar.timestamp.date()}: "
              f"O=${bar.open:.2f} H=${bar.high:.2f} "
              f"L=${bar.low:.2f} C=${bar.close:.2f} "
              f"V={bar.volume:,}")
    
    return data


def example_2_convert_to_dataframe(data):
    """Example 2: Convert to pandas DataFrame for analysis."""
    print("\n" + "="*60)
    print("EXAMPLE 2: Convert to DataFrame")
    print("="*60)
    
    df = data.to_dataframe()
    
    print(f"\nDataFrame shape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print("\nFirst few rows:")
    print(df.head())
    
    print("\nBasic statistics:")
    print(df[['open', 'high', 'low', 'close', 'volume']].describe())
    
    return df


def example_3_validate_data_quality(data):
    """Example 3: Validate data quality."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Data Quality Validation")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None)
    
    print(f"\nValidating {data.ticker} data quality...")
    quality = pipeline.validate_data_quality(data)
    
    print(f"\n{quality}")
    
    if quality.passed:
        print("\n✓ Data quality: PASS")
    else:
        print("\n✗ Data quality: FAIL")
        print("  Issues detected:")
        if quality.missing_percentage > 5:
            print(f"    - High missing data: {quality.missing_percentage:.1f}%")
        if quality.price_anomalies:
            print(f"    - Price anomalies: {len(quality.price_anomalies)}")
        if quality.volume_anomalies:
            print(f"    - Volume anomalies: {len(quality.volume_anomalies)}")


def example_4_build_universe():
    """Example 4: Build a trading universe (multiple tickers)."""
    print("\n" + "="*60)
    print("EXAMPLE 4: Build Trading Universe")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None)
    
    # Define universe
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)  # 6 months
    
    print(f"\nBuilding universe: {tickers}")
    print(f"Date range: {start_date.date()} to {end_date.date()}")
    
    universe = pipeline.build_universe(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        show_progress=True
    )
    
    print(f"\n✓ Universe built: {len(universe)} tickers")
    
    # Show summary
    print("\nUniverse summary:")
    for ticker, data in universe.items():
        print(f"  {ticker}: {len(data.bars)} bars, "
              f"source={data.data_source}")
    
    return universe


def example_5_cache_usage():
    """Example 5: Demonstrate caching."""
    print("\n" + "="*60)
    print("EXAMPLE 5: Cache Usage")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None, use_cache=True)
    
    ticker = "AAPL"
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    # First fetch (will generate mock data and cache it)
    print(f"\nFirst fetch of {ticker} (will cache)...")
    import time
    start_time = time.time()
    data1 = pipeline.get_daily_data(ticker, start_date, end_date)
    time1 = time.time() - start_time
    print(f"  Time: {time1:.3f}s")
    print(f"  Source: {data1.data_source}")
    
    # Second fetch (should hit cache)
    print(f"\nSecond fetch of {ticker} (should use cache)...")
    start_time = time.time()
    data2 = pipeline.get_daily_data(ticker, start_date, end_date)
    time2 = time.time() - start_time
    print(f"  Time: {time2:.3f}s")
    print(f"  Source: {data2.data_source}")
    
    # Compare
    speedup = time1 / time2 if time2 > 0 else 0
    print(f"\n✓ Cache speedup: {speedup:.1f}x faster")
    
    # Show cache stats
    stats = pipeline.get_pipeline_stats()
    print("\nCache statistics:")
    if 'cache_stats' in stats:
        for key, value in stats['cache_stats'].items():
            print(f"  {key}: {value}")


def example_6_intraday_data():
    """Example 6: Fetch intraday data."""
    print("\n" + "="*60)
    print("EXAMPLE 6: Intraday Data")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None)
    
    # Fetch 5-minute bars for today
    date = datetime.now()
    
    print(f"\nFetching intraday data for SPY on {date.date()}...")
    print("Interval: 5 minutes")
    
    data = pipeline.get_intraday_data(
        ticker="SPY",
        date=date,
        interval_minutes=5
    )
    
    print(f"\n✓ Fetched: {data}")
    print(f"  Total bars: {len(data.bars)}")
    print(f"  Data source: {data.data_source}")
    
    # Show market open
    print("\n  First 5 bars (market open):")
    for bar in data.bars[:5]:
        print(f"    {bar.timestamp.time()}: "
              f"O=${bar.open:.2f} H=${bar.high:.2f} "
              f"L=${bar.low:.2f} C=${bar.close:.2f} "
              f"V={bar.volume:,}")
    
    return data


def example_7_export_to_csv(data):
    """Example 7: Export data to CSV."""
    print("\n" + "="*60)
    print("EXAMPLE 7: Export to CSV")
    print("="*60)
    
    pipeline = DataPipeline(api_key=None)
    
    output_path = f"./raits/data/processed/{data.ticker}_daily.csv"
    
    print(f"\nExporting {data.ticker} to CSV...")
    print(f"Output: {output_path}")
    
    pipeline.export_to_csv(data, output_path)
    
    print(f"✓ Export complete!")


def example_8_quick_helpers():
    """Example 8: Use quick helper functions."""
    print("\n" + "="*60)
    print("EXAMPLE 8: Quick Helper Functions")
    print("="*60)
    
    # Quick single ticker
    print("\nUsing quick_daily_data()...")
    data = quick_daily_data(ticker="TSLA", days=60)
    print(f"✓ {data}")
    
    # Quick universe
    print("\nUsing quick_universe()...")
    universe = quick_universe(
        tickers=["AAPL", "MSFT"],
        days=30
    )
    print(f"✓ Loaded {len(universe)} tickers")
    for ticker in universe:
        print(f"  - {ticker}: {len(universe[ticker].bars)} bars")


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print(" " * 15 + "RAITS DATA PIPELINE EXAMPLES")
    print("="*70)
    print("\nThese examples work in MOCK MODE - no API key required!")
    print("When you add your Polygon.io API key, they'll fetch real data.")
    
    try:
        # Run examples
        data = example_1_fetch_single_ticker()
        df = example_2_convert_to_dataframe(data)
        example_3_validate_data_quality(data)
        universe = example_4_build_universe()
        example_5_cache_usage()
        intraday_data = example_6_intraday_data()
        example_7_export_to_csv(data)
        example_8_quick_helpers()
        
        # Final summary
        print("\n" + "="*70)
        print("✓ All examples completed successfully!")
        print("="*70)
        
        print("\nWhat you learned:")
        print("  1. How to fetch daily data")
        print("  2. How to convert to pandas DataFrame")
        print("  3. How to validate data quality")
        print("  4. How to build a trading universe")
        print("  5. How caching speeds up repeated fetches")
        print("  6. How to fetch intraday data")
        print("  7. How to export data to CSV")
        print("  8. How to use quick helper functions")
        
        print("\nNext steps:")
        print("  - Add your Polygon.io API key to config_private.py")
        print("  - Re-run examples to fetch real market data")
        print("  - Build your own data queries for RAITS")
        
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
