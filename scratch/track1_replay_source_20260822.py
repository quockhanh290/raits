"""scratch/track1_replay_source_20260822.py — feed the Track 1 route from the measured
trade tables. Scratch, offline, read-only.

Why this lives in scratch and not in global_index
-------------------------------------------------
It reads the pinned promotion artifacts under `scratch/`, so a production module importing
it would make production depend on scratch. The route's entry point loads it by name only
when `--source replay` is given, which is the default while the route is shadow-only.

What it is for
--------------
Two jobs, and they are the same job seen from two sides:

1. It is the ONLY sleeve source the Track 1 route has today. The live signal generators for
   all four sleeves are not promoted — see `global_index/track1_sleeves.py` for the exact
   list of what would have to move — so a shadow run is a replay of a measured window.
2. It is what makes the equivalence gate possible. Because both this and
   `scratch/track1_stage2c_book_bootstrap_20260822.py::replay` read the same tables, any
   difference in the ordered settlement stream is a difference in the RULES, which is the
   only thing the gate is trying to measure.

Ordering is part of the contract
--------------------------------
Candidates are emitted in the concat order the scratch loop uses — r4, stress, nkd, calm_a —
because Python's sort is stable and `entry_priority_key` ties on equal risk. Two candidates
at the same instant with the same risk would otherwise be admitted in a different order and
the gate would fail for a reason that has nothing to do with the rules.

The Calm-NKD table is not loaded at all. It is a closed strategy; see the Track 1 signal
layer's module docstring.
"""
from __future__ import annotations

import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd  # noqa: E402

from global_index.track1_signal_layer import Candidate  # noqa: E402

WINDOWS = ("floor", "vault2025", "vault2026")

_CACHE: dict = {}


def _load(which: str):
    if which not in _CACHE:
        import scratch.combined_repaired_replay_20260822 as comb
        import scratch.combined_stop_risk_audit_20260822 as audit
        r4, current_nkd, prices, extra, stress, _calm_nkd = audit.load_all(which)
        calm_a = comb.load_calm_a_atr15(which, extra["meta"])
        _CACHE[which] = (r4, current_nkd, prices, stress, calm_a)
    return _CACHE[which]


def _row_to_candidate(row: dict) -> Candidate:
    qty = int(row.get("qty") or 1)
    return Candidate(
        trade_id=str(row["trade_id"]),
        sleeve=str(row["cluster"]),
        instrument=str(row["instrument"]),
        direction=str(row["direction"]),
        qty=qty,
        risk_dollars=float(row["risk_sized"]),
        entry_time=pd.Timestamp(row["entry_time"]),
        exit_time=pd.Timestamp(row["exit_time"]),
        entry_price=float(row["entry"]) if row.get("entry") is not None else None,
        stop_price=float(row["stop"]) if row.get("stop") is not None else None,
        pnl_sized=float(row["pnl_sized"]),
        source=str(row.get("source", "")),
        meta={"variant": row.get("variant"), "exit_reason": row.get("exit_reason")},
    )


def candidates(which: str) -> list:
    """Every Track 1 candidate for one measured window, in the scratch loop's concat order."""
    r4, current_nkd, _prices, stress, calm_a = _load(which)
    out = []
    for frame in (r4, stress, current_nkd, calm_a):
        if frame is None or frame.empty:
            continue
        for _, row in frame.iterrows():
            out.append(_row_to_candidate(row.to_dict()))
    return out


def early_exit_valuer(which: str):
    """Price a position that a Stress entry displaced, exactly as the scratch loop does.

    The two sleeves are valued by different helpers on purpose — Calm A and Normal carry
    different cost conventions in the measured artifacts — and both are called rather than
    re-implemented, so a change on either side moves both this and the anchor together.

    Neither helper multiplies by quantity. That is correct for what it is used for here:
    only Normal and Calm are ever displaced, and both are one micro. A displaced position
    with qty > 1 would be under-booked, so the route asserts that case away rather than
    letting it be priced wrongly — see `assert_displaceable`.
    """
    import scratch.calm_a_combined_replay_20260822 as calm_a_base
    import scratch.stress_switch_full_replay_20260822 as full
    _r4, _nkd, prices, _stress, _calm = _load(which)
    costs = full.costs_for_basket(slippage_ticks=2.0)

    def value(held, ts) -> "float | None":
        cand = held.candidate
        px = full.price_at_or_after(prices[cand.instrument], pd.Timestamp(ts))
        if px is None:
            return None
        assert_displaceable(cand)
        pos = {"instrument": cand.instrument, "direction": cand.direction,
               "entry": cand.entry_price}
        if cand.sleeve == "roska4_calm":
            return calm_a_base.early_calm_pnl(pos, px, 2.0)
        return full.early_pnl(pos, px, costs)

    return value


def assert_displaceable(cand) -> None:
    """A displaced position must be one contract, because the valuers do not size.

    Stated as an assertion rather than left implicit: the day a Normal sleeve runs more than
    one micro, this fires instead of silently booking a seventh of the loss.
    """
    if int(cand.qty) != 1:
        raise ValueError(
            f"{cand.trade_id}: a displaced position carries qty={cand.qty}, but the early-exit "
            f"valuers price one contract. Size the valuation before allowing this.")
