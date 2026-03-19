# test_step_1_3_works.py
from raits.data.raits_data_pipeline import DataPipeline
from datetime import datetime, timedelta

pipeline = DataPipeline(api_key=None)

# Test 1: Daily data
print("Test 1: Fetching daily data...")
data = pipeline.get_daily_data(
    "AAPL",
    datetime.now() - timedelta(days=30),
    datetime.now()
)
assert len(data.bars) > 0
print(f"✓ {len(data.bars)} bars fetched")

# Test 2: DataFrame conversion
print("Test 2: Converting to DataFrame...")
df = data.to_dataframe()
assert 'close' in df.columns
print(f"✓ DataFrame: {df.shape}")

# Test 3: Intraday data
print("Test 3: Fetching intraday data...")
intraday = pipeline.get_intraday_data(
    "SPY",
    datetime.now(),
    interval_minutes=5
)
assert len(intraday.bars) > 0
print(f"✓ {len(intraday.bars)} intraday bars fetched")

print("\n✅ Step 1.3: DATA PIPELINE WORKING!")