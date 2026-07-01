"""
futures/ — self-contained futures engine for RAITS.

Deploys the validated swing-TF basket (RỔ 4) + STRESS_MID sleeve. Imports raits.hmm (regime brain) AND raits.strategies.trend_follow (entry signal)
— the two shared-core equity modules. All other layers reimplemented fresh so the
existing equities engine is never touched (locked constraint).

Modules:
  cost.py    — FuturesCost (per-contract commission + slippage)
  basket.py  — RỔ 4 contract specs, frozen param, regime + risk config
  (coming)   — swing_tf.py, stress_mid.py, sizer.py, net_exposure.py, runner.py
"""
from futures.cost import FuturesCost
from futures.basket import BASKET, SWING_TF_PARAM, REGIME, RISK, Contract
from futures.swing_tf import SwingTFEngine
from futures.stress_mid import StressMidEngine
from futures.net_exposure import NetExposureGuard, Position
from futures.circuit_breaker import CircuitBreaker
from futures.sizer import size_basket, SizingResult
from futures.runner import RaitsFuturesRunner, Signal, Order

__all__ = ["FuturesCost", "BASKET", "SWING_TF_PARAM", "REGIME", "RISK", "Contract",
           "SwingTFEngine", "StressMidEngine", "NetExposureGuard", "Position",
           "CircuitBreaker", "size_basket", "SizingResult", "RaitsFuturesRunner", "Signal", "Order"]
