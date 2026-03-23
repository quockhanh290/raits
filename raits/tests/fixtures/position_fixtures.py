# tests/fixtures/position_fixtures.py
#
# Synthetic inputs for position sizer tests.
#
# The three-constraint system (Section 5.3) always produces the MINIMUM of:
#   Kelly shares    — based on win rate and win/loss ratio
#   VolTarget shares — based on 1% account risk cap
#   Limit shares    — based on 20% account concentration cap
#
# We need one fixture per binding constraint so we can test each path.
# We also need bootstrap strategy stats — since we have no real trade history
# yet, the blueprint's example values for ORB are used:
#   win_rate = 0.62, avg_win = $4.50/share, avg_loss = $2.00/share

# ──────────────────────────────────────────────────────────────────────────────
# SHARED CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

ACCOUNT_EQUITY = 25_000.0   # $25k PDT account (blueprint default)

# Bootstrap ORB stats (Section 5.3 worked example)
# These will be replaced by real backtested values after Phase 1D.
ORB_STATS = {
    'win_rate': 0.62,     # 62% historical win rate
    'avg_win':  4.50,     # average win per share ($)
    'avg_loss': 2.00,     # average loss per share ($)
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO A: POSITION LIMIT IS THE BINDING CONSTRAINT
# ──────────────────────────────────────────────────────────────────────────────
#
# Blueprint worked example (Section 5.3): TSLA @ $178.50, stop $174.00
#
# Kelly:        31 shares  ($5,625 / $178.50)
# VolTarget:    55 shares  ($250 / $4.50 risk)
# Limit:        28 shares  ($5,000 / $178.50)  ← MINIMUM
#
# The stock is expensive relative to account size, so the 20% cap bites first.

POSITION_LIMIT_BINDS = {
    'entry_price': 178.50,
    'stop_loss':   174.00,   # risk = $4.50/share
    'account_equity': ACCOUNT_EQUITY,
    'strategy_stats': ORB_STATS,

    # Expected outputs
    'expected_kelly_shares':    31,
    'expected_vol_shares':      55,   # $250 / $4.50 = 55.5 → 55
    'expected_limit_shares':    28,   # $5,000 / $178.50 = 28.01 → 28
    'expected_final_shares':    28,
    'expected_limiting_factor': 'POSITION_LIMIT',
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO B: VOLATILITY TARGET IS THE BINDING CONSTRAINT
# ──────────────────────────────────────────────────────────────────────────────
#
# Blueprint test example (Section 12.3): $100 entry, $95 stop → $5 risk
#
# Kelly:        56 shares  (Half-Kelly 22.5% of $25k = $5,625 / $100)
# VolTarget:    50 shares  ($250 / $5.00 risk)  ← MINIMUM
# Limit:        50 shares  ($5,000 / $100)
#
# VolTarget and Limit tie at 50. Limiting factor is VolTarget
# (checked first in the tie-break logic: Kelly ≥ VolTarget ≥ Limit order).
#
# Kelly calculation detail:
#   b = 4.50 / 2.00 = 2.25
#   f = (0.62 × 2.25 - 0.38) / 2.25 = (1.395 - 0.38) / 2.25 = 0.451
#   half_kelly = 0.451 / 2 = 0.2255
#   capital = $25,000 × 0.2255 = $5,637.50
#   shares = $5,637.50 / $100 = 56.37 → 56

VOL_TARGET_BINDS = {
    'entry_price': 100.00,
    'stop_loss':    95.00,   # risk = $5.00/share
    'account_equity': ACCOUNT_EQUITY,
    'strategy_stats': ORB_STATS,

    'expected_kelly_shares':    56,
    'expected_vol_shares':      50,   # $250 / $5.00 = 50.0 → 50
    'expected_limit_shares':    50,   # $5,000 / $100 = 50.0 → 50
    'expected_final_shares':    50,
    'expected_limiting_factor': 'VOLATILITY_TARGET',
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO C: KELLY IS THE BINDING CONSTRAINT
# ──────────────────────────────────────────────────────────────────────────────
#
# Cheap stock, very tight stop → VolTarget and Limit allow many shares.
# But Kelly (based on our edge) is the most restrictive.
#
# Stock: $15.00, stop $14.85 → risk = $0.15/share
#
# Kelly:        56 shares  (same as above — Kelly is independent of price/stop)
#                          capital = $5,637.50 / $15.00 = 375.8 → wait...
#
# Actually let's recalculate all three:
#   Kelly: $5,637.50 / $15.00 = 375.8 → 375 shares
#   VolTarget: $250 / $0.15 = 1666 shares  (very tight stop = huge allowance)
#   Limit: $5,000 / $15.00 = 333 shares
#
# Hmm, at $15 and 0.15 stop, Limit (333) < Kelly (375). Let me adjust.
#
# Stock: $20.00, stop $19.80 → risk = $0.20/share
#   Kelly: $5,637.50 / $20.00 = 281 shares
#   VolTarget: $250 / $0.20 = 1250 shares
#   Limit: $5,000 / $20.00 = 250 shares
#
# Still Limit < Kelly. The issue is Kelly at $20 stock = 281 shares while
# Limit = 250. Let me use a low-priced stock where Kelly is explicitly smallest.
#
# To make Kelly bind we need:
#   Kelly < VolTarget  → always true when stop is tight
#   Kelly < Limit      → kelly_capital < 20% of account
#
#   kelly_capital = $25,000 × 0.2255 = $5,637
#   20% of account = $5,000
#   $5,637 > $5,000 → Kelly capital > Limit capital → Limit always binds for cheap stocks
#
# This reveals something important: with ORB stats (win_rate=0.62, b=2.25),
# Half-Kelly = 22.55%, which EXCEEDS the 20% position limit. So for cheap
# stocks (where VolTarget is loose due to tight stops), Limit always binds.
#
# To test Kelly binding, we need weaker strategy stats so Half-Kelly < 20%:
#   win_rate = 0.45, avg_win = 2.00, avg_loss = 2.00
#   b = 1.0
#   Kelly = (0.45 × 1.0 - 0.55) / 1.0 = -0.10  → NEGATIVE (no edge!)
#
# Negative Kelly means no edge exists. Let's use borderline stats:
#   win_rate = 0.52, avg_win = 2.00, avg_loss = 2.00
#   b = 1.0
#   Kelly = (0.52 - 0.48) / 1.0 = 0.04 (4%)
#   Half-Kelly = 2% of $25,000 = $500
#   Shares at $20: $500 / $20 = 25 shares  ← clearly smallest
#   VolTarget: $250 / $0.20 = 1250
#   Limit: $5,000 / $20 = 250
#
# Yes. With weak stats (barely any edge), Kelly is the binding constraint.

WEAK_STATS = {
    'win_rate': 0.52,
    'avg_win':  2.00,
    'avg_loss': 2.00,
}

KELLY_BINDS = {
    'entry_price': 20.00,
    'stop_loss':   19.80,    # risk = $0.20/share (tight stop)
    'account_equity': ACCOUNT_EQUITY,
    'strategy_stats': WEAK_STATS,

    # Kelly: b=1.0, f=(0.52-0.48)/1.0=0.04, half=0.02, capital=$500, shares=25
    'expected_kelly_shares':    25,
    'expected_vol_shares':    1250,   # $250 / $0.20
    'expected_limit_shares':   250,   # $5,000 / $20
    'expected_final_shares':    25,
    'expected_limiting_factor': 'KELLY_CRITERION',
}


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO D: NEGATIVE KELLY (no edge — should return None)
# ──────────────────────────────────────────────────────────────────────────────
#
# If Kelly is negative it means expected value is negative — we'd be better
# off not trading at all. The position sizer must detect this and refuse.
#
# win_rate = 0.40, avg_win = 1.00, avg_loss = 2.00
#   b = 0.5
#   Kelly = (0.40 × 0.5 - 0.60) / 0.5 = (0.20 - 0.60) / 0.5 = -0.80
#   → Negative. No position.

NEGATIVE_KELLY = {
    'entry_price': 50.00,
    'stop_loss':   47.00,
    'account_equity': ACCOUNT_EQUITY,
    'strategy_stats': {
        'win_rate': 0.40,
        'avg_win':  1.00,
        'avg_loss': 2.00,
    },
    'expected_final_shares': None,  # should be rejected
}
