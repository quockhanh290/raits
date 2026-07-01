"""
xsect/ — Cross-sectional stock momentum (Gate-1 structure probe)
================================================================
A DIFFERENT edge from Phase-1 equities (which was directional intraday ORB/
VWAP-MR/trend, NO-GO). Cross-sectional momentum: rank the whole universe by
trailing return, long top decile / short bottom decile, hold, rebalance,
market-neutral → alpha not beta.

STRUCTURE-FIRST (gold/rates lesson): before building the full long/short system,
measure cheaply whether the cross-sectional structure even exists — do winners
keep beating losers? If the top-minus-bottom spread isn't persistent, NO-GO now,
no big build wasted.

CAVEATS this probe must surface (not hide):
  - SURVIVORSHIP: if the cache holds only stocks alive today, delisted losers are
    missing → momentum spread is inflated (the losers that went to zero aren't
    there to short). Read results knowing this is an OPTIMISTIC upper bound.
  - SHORT SIDE: the probe decomposes long-leg vs short-leg contribution. If the
    edge lives mostly on the short leg, it's hard for a small Vietnam-resident
    account to capture (borrow cost, restrictions) — long-only would re-introduce
    beta. Decomposition tells us which case we're in.
  - Cross-sectional momentum is a well-known, arbitraged factor with crash risk
    (2009). Structure existing ≠ profitable after cost — later gates decide.
"""
