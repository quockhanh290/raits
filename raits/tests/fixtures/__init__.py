# tests/fixtures/__init__.py
#
# Synthetic OHLCV DataFrames for strategy testing.
#
# Philosophy: fixtures are the "test scenarios" written from the blueprint spec.
# They are created BEFORE the implementation, so they describe what the system
# SHOULD do, not what it currently does.
#
# Each fixture module owns the scenarios for one strategy:
#   orb_fixtures.py       - Opening Range Breakout scenarios
#   vwap_mr_fixtures.py   - VWAP Mean Reversion scenarios  (Week 11)
#   trend_fixtures.py     - Trend Following scenarios       (Week 13)
