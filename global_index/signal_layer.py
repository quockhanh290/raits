"""
global_index/signal_layer.py — engine (data-so-far) → today's decisions → decide_day
====================================================================================
The bridge between validated engines and the decision brain (live_decision.decide_day).
Each trading tick this produces: (1) entry_candidates for TODAY, (2) exit marks for
held positions the engines no longer want. decide_day then applies the risk layer.

TWO SIGNAL MODELS (they differ — do not unify):
  • swing TF + NKD = STATE: engine.desired_position() runs the validated backtest on
    data-through-now and returns the OPEN position it wants held. We diff desired-vs-held
    to get entry/exit EVENTS. "live == backtest by construction" because desired_position
    reads the backtest's own open-position timeline (causal, no look-ahead).
  • STRESS_MID = EVENT: entry_signal() fires once at 10:15, position exits same day by
    14:00. Not a held-state → handled separately, not through the state diff.

WHAT IS TESTABLE HERE WITHOUT DATA (unit-tested below in __main__):
  • diff_desired_vs_held() — the state→event logic (desired vs held → entries/exits)
  • to_candidate() — risk_sized computation + cluster tagging

WHAT NEEDS REAL-DATA RECONCILE (Claude Code, before trusting live):
  • generate_today_signals() end-to-end MUST match deploy_sim trade-for-trade when run
    through history (the live path == backtest path proof).
  • NKD: desired_position must use the SAME gap_fill setting as the NKD backtest in
    deploy_sim (deploy_sim line ~181 uses gap_fill=True). If Rổ-4 swing and NKD use
    different gap_fill, the engine configs must differ accordingly. → reconcile_nkd.
  • Rổ-4 swing: confirm desired_position's gap_fill matches the Rổ-4 backtest (gd0 proves
    the engine==harness for the BACKTEST path; desired_position is a DIFFERENT call —
    verify it too).
"""
from __future__ import annotations
from dataclasses import dataclass

# cluster names must match net_exposure_multi / deploy_sim exactly
CLUSTER_SWING = "roska4_swing"
CLUSTER_STRESS = "roska4_stress"
CLUSTER_NKD = "global_nkd"


def to_candidate(inst, direction, entry, stop, cluster, contracts, point_value):
    """Build an entry_candidate dict in the exact shape decide_day expects.
    risk_sized = stop distance × point value × contracts (real $ at risk)."""
    risk_sized = abs(float(entry) - float(stop)) * float(point_value) * int(contracts)
    return dict(inst=inst, direction=direction, cluster=cluster,
                risk_sized=risk_sized, entry=float(entry), stop=float(stop))


def diff_desired_vs_held(desired: dict, held: list):
    """State→event diff for swing/NKD (held-position engines).

    desired: {(inst, cluster): sig_or_None}  where sig = {direction, entry, stop}
    held:    list of objects with .inst, .cluster, .direction attributes

    Returns (entries, exits):
      entries = desired positions not currently held (or held in opposite direction)
      exits   = held positions no longer desired (or desired flipped direction)
    A direction flip = exit old + enter new (close then reopen opposite).
    """
    held_by_key = {(p.inst, p.cluster): p for p in held}
    entries, exits = [], []
    desired_live_keys = set()

    for (inst, cluster), sig in desired.items():
        if sig is None:
            continue
        key = (inst, cluster)
        desired_live_keys.add(key)
        cur = held_by_key.get(key)
        if cur is None:
            entries.append((inst, cluster, sig))            # new position
        elif cur.direction != sig["direction"]:
            exits.append(cur)                                # flip: close old...
            entries.append((inst, cluster, sig))            # ...open opposite
    # held positions the engine no longer wants (and not a flip already handled)
    for key, p in held_by_key.items():
        if key not in desired_live_keys:
            exits.append(p)
    return entries, exits


def generate_today_signals(*, swing_engine, swing_dfs, swing_labels, swing_costs,
                           nkd_engine, nkd_df, nkd_labels, nkd_cost, nkd_inst,
                           stress_engine, stress_bars_1015, today_regime,
                           held, point_values, contracts_by_inst):
    """Produce (entry_candidates, exit_positions) for today from all engines on
    data-through-now. STATE engines (swing, NKD) go through diff_desired_vs_held;
    STRESS_MID (event) is added as fresh entry candidates only.

    NOTE (real-data reconcile required): engine calls below must reproduce deploy_sim's
    trades. gap_fill per engine must match deploy_sim. Verify before live.
    """
    desired: dict = {}

    # --- swing TF (Rổ 4) : STATE ---
    for inst, sig in swing_engine.desired_basket(swing_dfs, swing_labels, swing_costs).items():
        desired[(inst, CLUSTER_SWING)] = sig

    # --- NKD : STATE (same swing machinery, NKD params; gap_fill must match backtest) ---
    nkd_sig = nkd_engine.desired_position(nkd_df, nkd_labels, nkd_cost)
    desired[(nkd_inst, CLUSTER_NKD)] = nkd_sig

    # state-diff → entry/exit events for swing + NKD
    state_entries, exits = diff_desired_vs_held(desired, held)

    candidates = []
    for inst, cluster, sig in state_entries:
        candidates.append(to_candidate(
            inst, sig["direction"], sig["entry"], sig["stop"],
            cluster, contracts_by_inst.get(inst, 1), point_values[inst]))

    # --- STRESS_MID : EVENT (only at 10:15, only in Stress regime) ---
    if stress_bars_1015 and today_regime == "Stress":
        held_stress = {(p.inst, p.cluster) for p in held}
        for inst, bars in stress_bars_1015.items():
            if (inst, CLUSTER_STRESS) in held_stress:
                continue
            s = stress_engine.entry_signal(bars, today_regime)
            if s:
                candidates.append(to_candidate(
                    inst, s["direction"], s["entry"], s["stop"],
                    CLUSTER_STRESS, contracts_by_inst.get(inst, 1), point_values[inst]))

    return candidates, exits


# ── unit tests for the data-independent core (run: python -m global_index.signal_layer) ──
if __name__ == "__main__":
    @dataclass
    class _Held:
        inst: str; cluster: str; direction: str

    # to_candidate: risk_sized = |entry-stop| × pv × contracts
    c = to_candidate("MES", "LONG", 5000.0, 4980.0, CLUSTER_SWING, 2, 5.0)
    assert c["risk_sized"] == 20.0 * 5.0 * 2, c
    assert c["cluster"] == CLUSTER_SWING and c["direction"] == "LONG"

    # diff: new desired, nothing held → 1 entry, 0 exit
    des = {("MES", CLUSTER_SWING): {"direction": "LONG", "entry": 5000, "stop": 4980}}
    e, x = diff_desired_vs_held(des, [])
    assert len(e) == 1 and len(x) == 0

    # diff: held matches desired → hold (0 entry, 0 exit)
    held = [_Held("MES", CLUSTER_SWING, "LONG")]
    e, x = diff_desired_vs_held(des, held)
    assert len(e) == 0 and len(x) == 0, (e, x)

    # diff: held but no longer desired → exit
    e, x = diff_desired_vs_held({("MES", CLUSTER_SWING): None}, held)
    assert len(e) == 0 and len(x) == 1 and x[0].inst == "MES"

    # diff: direction flip → exit old + enter new
    des_short = {("MES", CLUSTER_SWING): {"direction": "SHORT", "entry": 5000, "stop": 5020}}
    e, x = diff_desired_vs_held(des_short, held)
    assert len(e) == 1 and len(x) == 1 and e[0][2]["direction"] == "SHORT"

    # diff: multi — one hold, one new, one exit
    des_multi = {
        ("MES", CLUSTER_SWING): {"direction": "LONG", "entry": 5000, "stop": 4980},  # held→hold
        ("MNQ", CLUSTER_SWING): {"direction": "LONG", "entry": 17000, "stop": 16900},  # new
        ("MYM", CLUSTER_SWING): None,  # not desired
    }
    held_multi = [_Held("MES", CLUSTER_SWING, "LONG"), _Held("MYM", CLUSTER_SWING, "LONG")]
    e, x = diff_desired_vs_held(des_multi, held_multi)
    assert len(e) == 1 and e[0][0] == "MNQ", e
    assert len(x) == 1 and x[0].inst == "MYM", x

    print("signal_layer core logic: all unit tests PASS")
    print("  (state-diff + to_candidate verified; engine integration needs real-data reconcile)")
