# raits/risk/__init__.py
#
# Phase 1C will add the full 4-layer risk architecture here.
# For Week 10, we build only the position sizer (Section 5.3),
# which is needed to complete the ORB integration loop.
#
# Modules:
#   position_sizer.py  — three-constraint position sizing (Kelly + VolTarget + Limit)
#   circuit_breakers.py — daily loss limit, max drawdown  (Week 16)
#   beta_controls.py   — portfolio beta management         (Week 16)
