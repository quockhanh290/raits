"""
nonequity/ — self-contained CTA daily-bar trend INVESTIGATION (Gate 0, fresh)
=============================================================================
Discovery of trend-following on NON-equity futures (gold, crude, ...). This is a
NEW strategy hypothesis (session-agnostic daily-bar trend), NOT a transfer of the
validated equity power-hour engine. It therefore:

  • starts from Gate 0 — it borrows NO validation credit from the equity basket;
  • is FULLY SELF-CONTAINED — primitives are verbatim copies of the validated
    futures/_validated_core logic (load_parquet, atr14, daily_atr_series, Trade)
    + futures/cost.FuturesCost, copied in _core.py so this folder runs standalone
    and never imports root scripts or the equity-RTH entry (trend_follow.py);
  • NEVER touches futures/ (validated, locked) or the equities engine (NO-GO).

Contract specs (point_value / tick) live ONLY in specs.py — never import
futures/basket.py (that hardcodes equity index pv/tick → the M2K-class bug).
"""
