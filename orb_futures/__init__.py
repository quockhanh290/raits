"""
orb_futures/ — Opening-Range Breakout on Rổ 4 (diversification candidate)
=========================================================================
TẦNG 1 diversify: SAME instruments (Rổ 4), DIFFERENT strategy from swing TF.

swing TF: power-hour (14:00-15:55 ET) pullback-resume, 5-day swing hold,
          regimes Normal+Stress.
ORB:      opening-range (9:30-9:45 ET) breakout, INTRADAY exit (same day),
          regimes Calm+Normal (ORB blueprint).

Why this could diversify (must PROVE, not assume):
  - different entry window (open vs power hour)
  - different horizon (intraday vs 5-day)
  - different regimes (Calm/Normal vs Normal/Stress) — only Normal overlaps

The bar to clear is BOTH:
  1. ORB has a real edge on Rổ 4 (gate like any strategy), AND
  2. ORB's daily P&L is LOW-correlated with swing TF (else it just doubles the
     same bet — no diversification, even if profitable standalone).

This is a NEW, UNVALIDATED edge (the stock ORB was cross-sectional and Phase-1
equities are NO-GO). It must pass the full gate sequence. Start at Gate 2 (edge
+ correlation); only proceed to WFO/vault if both look alive.
"""
