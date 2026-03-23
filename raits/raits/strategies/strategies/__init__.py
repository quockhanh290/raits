# raits/strategies/__init__.py
#
# Phase 1B: Strategy implementations
#
# Build order (blueprint Weeks 9-15):
#   orb.py          - Opening Range Breakout  "The Gappers"   (Weeks 9-10)
#   vwap_mr.py      - VWAP Mean Reversion     "The Grinders"  (Weeks 11-12)
#   trend_follow.py - Trend Following         "The Runners"   (Weeks 13-14)
#   cash_defense.py - Cash / Defense mode                     (Week 15)
#
# All four strategies share the same external contract:
#   - Receive hmm_state as a plain string ('Calm' / 'Normal' / 'Stress')
#   - Return a signal dict on entry opportunity, or None
#   - Know nothing about where the HMM state came from
#
# The Master Strategy Router (raits/router.py, Phase 1C) is the only component
# that calls HMMEngine.predict() and distributes the result to these modules.
