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
import logging
import pandas as pd
from futures._validated_core import daily_atr_series

logger = logging.getLogger(__name__)

# cluster names must match net_exposure_multi / deploy_sim exactly
CLUSTER_SWING = "roska4_swing"
CLUSTER_STRESS = "roska4_stress"
CLUSTER_NKD = "global_nkd"

# chandelier multipliers — must match deploy_sim --roska4-mult / --nkd-mult defaults
ROSKA4_MULT = 2.5
NKD_MULT    = 2.5


def _asof_naive(atr_s: "pd.Series", ts) -> float:
    """ATR lookup: strip tz before asof() because daily_atr_series index is tz-naive."""
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_localize(None)
    av = atr_s.asof(t)
    return float(av) if av is not None and not pd.isna(av) else float(atr_s.median())


def to_candidate(inst, direction, entry, stop, cluster, contracts, point_value,
                 daily_atr, mult):
    """Build an entry_candidate dict in the exact shape decide_day expects.
    risk_sized = daily_ATR × mult × pv × contracts  (deploy_sim real_risk formula).
    entry/stop kept in dict for order execution; risk_sized drives guard cap."""
    risk_sized = int(contracts) * float(mult) * float(daily_atr) * float(point_value)
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
                           held, point_values, contracts_by_inst,
                           today):
    """Produce (entry_candidates, exit_positions) for today from all engines on
    data-through-now. STATE engines (swing, NKD) go through diff_desired_vs_held;
    STRESS_MID (event) is added as fresh entry candidates only.

    today : pd.Timestamp (tz-naive, normalized) — the current ET trading session date.

    Guard (mirrors real_signal_fn in verify_runner_real ~L242):
      Only generate a new entry when desired_position's entry_day == today.
      If entry_day < today the entry was already attempted on a prior day and
      cap-rejected; re-presenting it would submit a live order at yesterday's
      stale close price. Suppress by setting desired=None for that key.

    Same-direction rollover (mirrors real_signal_fn ~L233):
      diff_desired_vs_held only checks direction, not entry_day. When the backtest
      shows a new trade (different entry_day) in the same direction as the currently
      held position, diff would silently "hold" — missing the exit+re-entry. Detect
      this via cur.entry_day != new_ed and push to force_entries.

    NOTE (real-data reconcile required): engine calls below must reproduce deploy_sim's
    trades. gap_fill per engine must match deploy_sim. Verify before live.
    """
    today_norm = pd.Timestamp(today).normalize()

    # NKD desired_position returns entry_day as tz-naive JST calendar date.
    # NKD session (09:00-15:30 JST) ends by ~01:30 ET — before US open (09:30 ET) —
    # so JST calendar date always equals ET calendar date when the runner operates.
    # Using today_norm (ET) directly mirrors real_signal_fn (uses day_ts, ET) and is
    # conservative for late feed: if NKD bars are delayed, desired_position returns an
    # old entry_day that does not match today_norm → suppressed, matching reference behavior.

    held_by_key = {(p.inst, p.cluster): p for p in held}
    desired: dict = {}
    force_entries: list = []  # same-direction rollover: exit old + enter new

    # --- swing TF (Rổ 4) : STATE ---
    # C4: isolated try/except — swing failure skips swing entries; held positions
    # get "hold" dummy signals so diff does NOT generate spurious exits for them.
    try:
        for inst, sig in swing_engine.desired_basket(swing_dfs, swing_labels, swing_costs).items():
            key = (inst, CLUSTER_SWING)
            if sig is None:
                desired[key] = None
                continue
            new_ed = pd.Timestamp(sig["entry_day"]).normalize()
            cur = held_by_key.get(key)
            if (cur is not None
                    and cur.direction == sig["direction"]
                    and cur.entry_day.normalize() != new_ed):
                # Same-direction rollover: old trade closed, new one starts today.
                # diff_desired_vs_held would see same direction → hold and miss the turnover.
                desired[key] = None              # triggers exit of old pos in diff
                force_entries.append((inst, CLUSTER_SWING, sig))
            elif cur is None:
                # Guard: only fire on the actual entry day (matches real_signal_fn ~L242).
                desired[key] = sig if new_ed == today_norm else None
            else:
                desired[key] = sig               # direction flip or same-trade hold
    except Exception as exc:
        logger.error(
            "C4: cluster %s FAILED on %s: %s — swing entries skipped; held positions preserved",
            CLUSTER_SWING, today_norm.date(), exc,
        )
        # Clear any partial swing state from desired / force_entries.
        for key in [k for k in desired if k[1] == CLUSTER_SWING]:
            del desired[key]
        force_entries[:] = [fe for fe in force_entries if fe[1] != CLUSTER_SWING]
        # Restore "hold" signal for each currently-held swing position so diff treats
        # them as unchanged (same entry_day → no rollover, same direction → no exit).
        for p in held:
            if p.cluster == CLUSTER_SWING:
                desired[(p.inst, CLUSTER_SWING)] = {
                    "direction": p.direction, "entry": 0.0, "stop": 0.0,
                    "entry_day": p.entry_day,
                }

    # --- NKD : STATE (same swing machinery, NKD params; gap_fill must match backtest) ---
    # C4: isolated try/except — NKD failure skips NKD entries; held NKD position preserved.
    try:
        nkd_key = (nkd_inst, CLUSTER_NKD)
        nkd_sig = nkd_engine.desired_position(nkd_df, nkd_labels, nkd_cost)
        if nkd_sig is None:
            desired[nkd_key] = None
        else:
            new_ed = pd.Timestamp(nkd_sig["entry_day"]).normalize()
            cur = held_by_key.get(nkd_key)
            if (cur is not None
                    and cur.direction == nkd_sig["direction"]
                    and cur.entry_day.normalize() != new_ed):
                desired[nkd_key] = None
                force_entries.append((nkd_inst, CLUSTER_NKD, nkd_sig))
            elif cur is None:
                desired[nkd_key] = nkd_sig if new_ed == today_norm else None
            else:
                desired[nkd_key] = nkd_sig
    except Exception as exc:
        logger.error(
            "C4: cluster %s FAILED on %s: %s — NKD entries skipped; held position preserved",
            CLUSTER_NKD, today_norm.date(), exc,
        )
        # Remove any partial NKD state from desired / force_entries.
        desired.pop((nkd_inst, CLUSTER_NKD), None)
        force_entries[:] = [fe for fe in force_entries if fe[1] != CLUSTER_NKD]
        # Restore "hold" signal for any currently-held NKD position.
        for p in held:
            if p.cluster == CLUSTER_NKD:
                desired[(p.inst, CLUSTER_NKD)] = {
                    "direction": p.direction, "entry": 0.0, "stop": 0.0,
                    "entry_day": p.entry_day,
                }

    # state-diff → entry/exit events for swing + NKD
    state_entries, exits = diff_desired_vs_held(desired, held)
    state_entries.extend(force_entries)

    # pre-compute daily ATR series — same as deploy_sim's  atr = {n: daily_atr_series(df) ...}
    atr_swing = {inst: daily_atr_series(df) for inst, df in swing_dfs.items()}
    atr_nkd   = daily_atr_series(nkd_df)

    candidates = []
    for inst, cluster, sig in state_entries:
        if cluster == CLUSTER_NKD:
            atr_s, mult = atr_nkd, NKD_MULT
        else:  # CLUSTER_SWING
            atr_s, mult = atr_swing[inst], ROSKA4_MULT
        av = _asof_naive(atr_s, sig["entry_day"])
        candidates.append(to_candidate(
            inst, sig["direction"], sig["entry"], sig["stop"],
            cluster, contracts_by_inst.get(inst, 1), point_values[inst],
            daily_atr=av, mult=mult))

    # --- STRESS_MID : EVENT (only at 10:15, only in Stress regime) ---
    # C4: isolated try/except — stress is an event model (same-day entry+exit), no held
    # state across days, so failure here only suppresses new stress entries for today.
    try:
        if stress_bars_1015 and today_regime == "Stress":
            # derive today (tz-naive) for ATR lookup — stress entry is always today
            _any = next(iter(stress_bars_1015.values()))
            _ts = pd.Timestamp(_any.index[-1])
            today_naive = _ts.tz_localize(None).normalize() if _ts.tzinfo else _ts.normalize()

            held_stress = {(p.inst, p.cluster) for p in held}
            for inst, bars in stress_bars_1015.items():
                if (inst, CLUSTER_STRESS) in held_stress:
                    continue
                s = stress_engine.entry_signal(bars, today_regime)
                if s:
                    atr_s = atr_swing.get(inst, daily_atr_series(bars))
                    av = _asof_naive(atr_s, today_naive)
                    candidates.append(to_candidate(
                        inst, s["direction"], s["entry"], s["stop"],
                        CLUSTER_STRESS, contracts_by_inst.get(inst, 1), point_values[inst],
                        daily_atr=av, mult=ROSKA4_MULT))
    except Exception as exc:
        logger.error(
            "C4: cluster %s FAILED on %s: %s — stress entries skipped",
            CLUSTER_STRESS, today_norm.date(), exc,
        )

    return candidates, exits


# ── unit tests for the data-independent core (run: python -m global_index.signal_layer) ──
if __name__ == "__main__":
    @dataclass
    class _Held:
        inst: str; cluster: str; direction: str

    # to_candidate: risk_sized = daily_atr × mult × pv × contracts (deploy_sim formula)
    c = to_candidate("MES", "LONG", 5000.0, 4980.0, CLUSTER_SWING, 2, 5.0,
                     daily_atr=20.0, mult=ROSKA4_MULT)
    assert c["risk_sized"] == 20.0 * ROSKA4_MULT * 5.0 * 2, c   # = 500.0
    assert c["entry"] == 5000.0 and c["stop"] == 4980.0           # kept for order execution
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
