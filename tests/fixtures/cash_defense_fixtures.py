# tests/fixtures/cash_defense_fixtures.py
#
# Test scenarios for Cash/Defense mode.
#
# Unlike the other three strategies, Cash/Defense has no price-based fixtures.
# The inputs are HMM state strings and a list of open positions.
# The outputs are activation status and liquidation orders.
#
# SCENARIO TAXONOMY
# -----------------
# A. Activation scenarios   — what triggers the mode
# B. Deactivation scenarios — what exits the mode
# C. Liquidation scenarios  — what positions get closed and how
# D. State machine scenarios — idempotency and transition edge cases

# ──────────────────────────────────────────────────────────────────────────────
# SHARED: sample open positions
# ──────────────────────────────────────────────────────────────────────────────
# In Phase 1 simulation, "open positions" are dicts produced by the session
# replayers. Cash/Defense receives a list of these and returns liquidation
# orders for each.

POSITION_TSLA = {
    'ticker':      'TSLA',
    'direction':   'LONG',
    'shares':       28,
    'entry_price': 178.50,
    'strategy':    'ORB',
}

POSITION_AAPL = {
    'ticker':      'AAPL',
    'direction':   'SHORT',
    'shares':       50,
    'entry_price': 182.00,
    'strategy':    'VWAP_MR',
}

POSITION_NVDA = {
    'ticker':      'NVDA',
    'direction':   'LONG',
    'shares':       15,
    'entry_price': 495.00,
    'strategy':    'TREND_FOLLOW',
}

TWO_POSITIONS   = [POSITION_TSLA, POSITION_AAPL]
THREE_POSITIONS = [POSITION_TSLA, POSITION_AAPL, POSITION_NVDA]
NO_POSITIONS    = []


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO A: Activation
# ──────────────────────────────────────────────────────────────────────────────

# A1: Stress with open positions → activate, return liquidation orders
ACTIVATE_WITH_POSITIONS = {
    'hmm_state':      'Stress',
    'open_positions': TWO_POSITIONS,
    'expected_active':      True,
    'expected_liquidations': 2,   # one per open position
    'expected_reason':      'HMM_STRESS',
}

# A2: Stress with NO open positions → activate, nothing to liquidate
ACTIVATE_NO_POSITIONS = {
    'hmm_state':      'Stress',
    'open_positions': NO_POSITIONS,
    'expected_active':       True,
    'expected_liquidations': 0,
    'expected_reason':       'HMM_STRESS',
}

# A3: Calm regime → should NOT activate
NO_ACTIVATE_CALM = {
    'hmm_state':      'Calm',
    'open_positions': TWO_POSITIONS,
    'expected_active': False,
}

# A4: Normal regime → should NOT activate
NO_ACTIVATE_NORMAL = {
    'hmm_state':      'Normal',
    'open_positions': TWO_POSITIONS,
    'expected_active': False,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO B: Deactivation
# ──────────────────────────────────────────────────────────────────────────────

# B1: Calm returns after Stress → deactivate, resume normal trading
DEACTIVATE_CALM_RETURNS = {
    'initial_state':  'Stress',   # start in Stress (active)
    'new_hmm_state':  'Calm',
    'expected_active': False,
    'expected_reason': 'REGIME_NORMALIZED',
}

# B2: Normal returns after Stress → also deactivate
DEACTIVATE_NORMAL_RETURNS = {
    'initial_state':  'Stress',
    'new_hmm_state':  'Normal',
    'expected_active': False,
    'expected_reason': 'REGIME_NORMALIZED',
}

# B3: Stress continues → remain active (no change)
REMAIN_ACTIVE_STRESS_CONTINUES = {
    'initial_state':  'Stress',
    'new_hmm_state':  'Stress',
    'expected_active': True,
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO C: Liquidation order structure
# ──────────────────────────────────────────────────────────────────────────────

# C1: Liquidation orders must have correct structure
LIQUIDATION_ORDER_STRUCTURE = {
    'hmm_state':      'Stress',
    'open_positions': [POSITION_TSLA],
    # Each liquidation order must contain these keys:
    'required_keys': {'ticker', 'direction', 'shares', 'order_type', 'reason'},
    # Order type must be MARKET (not LIMIT) — speed over price
    'expected_order_type': 'MARKET',
    # Liquidation direction is opposite of position direction
    # LONG position → SELL to close
    # SHORT position → BUY to close
    'expected_close_direction': 'SELL',   # closes a LONG
}

# C2: Short position liquidation (direction is BUY to close)
LIQUIDATION_SHORT_POSITION = {
    'hmm_state':      'Stress',
    'open_positions': [POSITION_AAPL],   # SHORT position
    'expected_close_direction': 'BUY',   # closes a SHORT
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO D: State machine edge cases
# ──────────────────────────────────────────────────────────────────────────────

# D1: Calling activate() twice in Stress → second call is a no-op
#     (no double liquidation, no error)
IDEMPOTENT_ACTIVATION = {
    'hmm_state':      'Stress',
    'open_positions': TWO_POSITIONS,
    'description':    'Activating twice should not produce double liquidations',
}

# D2: Calling deactivate() when not active → no-op, returns False
DEACTIVATE_WHEN_NOT_ACTIVE = {
    'hmm_state':       'Calm',
    'description':     'Deactivating when not active should be harmless',
    'expected_active': False,
}
