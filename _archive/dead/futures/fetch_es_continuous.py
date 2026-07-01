"""
futures/ — self-contained futures engine for RAITS.

Deploys the validated swing-TF basket (RỔ 4) + STRESS_MID sleeve. Imports ONLY
raits.hmm (regime brain, read-only); reimplements all other layers fresh so the
existing equities engine is never touched (locked constraint).

Modules:
  cost.py    — FuturesCost (per-contract commission + slippage)
  basket.py  — RỔ 4 contract specs, frozen param, regime + risk config
  (coming)   — swing_tf.py, stress_mid.py, sizer.py, net_exposure.py, runner.py
"""
from futures.cost import FuturesCost
from futures.basket import BASKET, SWING_TF_PARAM, REGIME, RISK, Contract

__all__ = ["FuturesCost", "BASKET", "SWING_TF_PARAM", "REGIME", "RISK", "Contract"]
