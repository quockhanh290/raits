"""
raits/coordinator — Phase 1C Week 17: Regime Coordination & Conflict Resolution

Blueprint Sections 4.6 and 6.

Components
----------
regime_coordinator.py  State machine: ACTIVE/OVERRIDE_STRESS/COOLDOWN/SAFETY_MODE/SHUTDOWN
strategy_router.py     Time-based and regime-based strategy activation → RoutingDecision
conflict_resolver.py   Position limits, same-stock dedup, priority (TREND > ORB > VWAP_MR)
"""

from .regime_coordinator import RegimeCoordinator, SystemState
from .strategy_router import StrategyRouter, RoutingDecision, TimeWindow
from .conflict_resolver import ConflictResolver, SignalPriority, ResolvedSignal

__all__ = [
    "RegimeCoordinator", "SystemState",
    "StrategyRouter", "RoutingDecision", "TimeWindow",
    "ConflictResolver", "SignalPriority", "ResolvedSignal",
]
