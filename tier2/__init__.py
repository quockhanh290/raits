"""
tier2/ — Diversification via a DIFFERENT asset class with its own edge
=====================================================================
TẦNG 2: real diversification (corr~0 with equity), NOT an extension of the
equity-index edge. Power-hour swing TF does NOT transfer here (gold/crude NO-GO
proved the edge is equity-index-microstructure-specific). So tier 2 needs a
DIFFERENT edge designed for a DIFFERENT asset — effectively a new mini-RAITS.

Discipline (the GOLD lesson): measure STRUCTURE before building any strategy.
Gold daily trend-following failed because gold ≈ random walk (VR≈1) at that scale
— discovered only AFTER wasted backtests. Tier 2 inverts the order:

  Gate 0  data     : fetch + verify roll / liquidity / session (new asset = new roll)
  Gate 1  STRUCTURE: Variance Ratio. VR>1 → trend-able; VR<1 → MR-able; VR≈1 →
                     random walk → NO-GO immediately (no backtest wasted).
  Gate 2+ edge     : only if Gate 1 shows exploitable structure.

Candidate asset–edge pairs (priors, honest):
  - Rates ZN/ZB + trend daily : best prior (bonds trend on rate cycles, CTA-classic,
                                uncorrelated equity) — but daily-trend failed on gold,
                                so VR must clear first.
  - FX 6E/6J + trend/carry    : medium (FX choppy; carry needs funding data)
  - Commodity + term-structure: medium (opposite of the roll artifact; complex)
"""
