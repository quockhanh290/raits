"""
global_index/ — foreign EQUITY-INDEX expansion of Rổ 4 (NOT non-equity / NOT diversification)
==============================================================================================
These are equity indices listed abroad — Nikkei (NKD, CME/GLBX), DAX later. They
are the SAME asset class as Rổ 4 (US index futures), correlated ~0.6-0.85 with it.

Purpose: INCREASE RETURN by transferring the validated Rổ-4 power-hour swing edge
to other equity indices. This is NOT diversification — risk-off moves them with
Rổ 4. Whether they actually help (vs just adding correlated drawdown) is decided
by backtest_combined with Rổ 4, NOT by standalone PF.

Distinct from nonequity/ (gold/crude/rates/FX — genuinely different asset classes,
~0 correlation, the real diversification question — gold NO-GO, crude data-blocked).

Self-contained: _core.py + fetch.py are verbatim copies of the validated/generic
nonequity versions. swing_tf_powerhour.py reuses the EXACT Rổ-4 engine
(futures._validated_core.backtest_swing_tf) via tz-convert.
"""
