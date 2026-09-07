"""Quantify how much of the Calm-NKD switch result is a price-series units artifact.

SCRATCH-ONLY.

The current-NKD legs are priced from the frozen NKD parquet named in the promotion
artifact; the Calm-NKD challenger legs are priced from the continuous NKD parquet.
The two series differ by a CONSTANT back-adjustment offset (floor: frozen =
continuous + 100.0 points; 2025: frozen = continuous - 10.0; 2026: same file, 0).

A constant offset cancels inside each sleeve's own P&L, because P&L is a price
difference within one series. It does NOT cancel in the forced close, which
subtracts a current-NKD entry on the frozen scale from a Calm-NKD entry on the
continuous scale. This re-runs the combined replay with the Calm-NKD close price
put back on the artifact scale and reports the difference.

Self-check: the 2026 window has offset 0, so corrected and uncorrected MUST be
identical there. If they are not, the correction is wired wrong.

  python scratch/combined_nkd_offset_correction_20260822.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.calm_nkd_switch_vs_current_20260822 as calm_nkd
import scratch.combined_stop_risk_audit_20260822 as audit
from global_index.deploy_sim import metrics

# frozen_artifact_price - continuous_probe_price, measured bar by bar, constant
OFFSET = {"floor": 100.0, "vault2025": -10.0, "vault2026": 0.0}
OUT = Path("scratch/combined_nkd_offset_correction_20260822.json")


def main() -> int:
    out = {}
    orig = calm_nkd.early_nkd_pnl
    for which in ("floor", "vault2025", "vault2026"):
        print(f"[run] {which}", flush=True)
        d0, s0, _, _, _ = audit.instrumented_replay(which, 0.05, "skip_same_symbol", 2.0)
        m0 = metrics(d0)
        off = OFFSET[which]

        def patched(old, exit_px, _o=orig, _off=off):
            return _o(old, float(exit_px) + _off)

        calm_nkd.early_nkd_pnl = patched
        try:
            d1, s1, _, _, _ = audit.instrumented_replay(which, 0.05, "skip_same_symbol", 2.0)
        finally:
            calm_nkd.early_nkd_pnl = orig
        m1 = metrics(d1)
        out[which] = dict(
            offset_points=off,
            forced_closes=int(s0["calm_closed_current_nkd"]),
            reported_switch_delta=float(s0["calm_switch_delta"]),
            corrected_switch_delta=float(s1["calm_switch_delta"]),
            reported_net=float(m0["pnl"]), corrected_net=float(m1["pnl"]),
            net_shift=float(m1["pnl"] - m0["pnl"]),
            reported_maxdd=float(m0["maxdd"]), corrected_maxdd=float(m1["maxdd"]),
            reported_calmar=float(m0["calmar"]), corrected_calmar=float(m1["calmar"]),
        )
        print(f"[ok] {which} net {m0['pnl']:,.0f} -> {m1['pnl']:,.0f}", flush=True)
    assert abs(out["vault2026"]["net_shift"]) < 1e-6, \
        "self-check failed: zero-offset window moved, correction is wired wrong"
    OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
