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
# net_exposure (2-cluster) không re-export — live deploy dùng
#  global_index/net_exposure_multi. backtest_system.py import trực tiếp nếu cần.
from futures.circuit_breaker import CircuitBreaker
from futures.sizer import size_basket, SizingResult
# runner archived → _archive/superseded/futures_runner_2cluster.py (2-cluster net_exposure, pre-NKD).
# Risk layer thay bằng global_index/net_exposure_multi + live_decision.
# Runner đầy đủ sẽ ở global_index/ (cần NKD live-wrapper + reconcile_nkd trước khi wire live).

__all__ = ["FuturesCost", "BASKET", "SWING_TF_PARAM", "REGIME", "RISK", "Contract",
           "SwingTFEngine", "StressMidEngine",
           "CircuitBreaker", "size_basket", "SizingResult"]
