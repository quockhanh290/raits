from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.calm_a_combined_replay_20260822 as calm_a_base
import scratch.calm_a_disaster_stop_probe_20260822 as dis
import scratch.calm_nkd_switch_vs_current_20260822 as calm_nkd
import scratch.combined_stop_risk_audit_20260822 as audit
import scratch.stress_switch_full_replay_20260822 as full
from global_index.deploy_sim import metrics
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard, Position, entry_priority_key
from scratch.normal_sleeve_fill_audit import ACCOUNT


OUT = Path("scratch/combined_repaired_replay_20260822_report.md")
JSON_OUT = Path("scratch/combined_repaired_replay_20260822.json")
OFFSET = {"floor": 100.0, "vault2025": -10.0, "vault2026": 0.0}


@dataclass(frozen=True)
class Policy:
    name: str
    include_calm_nkd_switch: bool
    family_gross: float | None = None
    family_net: float | None = None


POLICIES = [
    Policy("repaired_mechanics_independent_caps", True, None, None),
    Policy("repaired_mechanics_family_cap_5_44", True, 0.050, 0.044),
    Policy("repaired_mechanics_family_cap_7p5", True, 0.075, 0.075),
    Policy("risk_clean_no_calm_nkd_family_cap_5_44", False, 0.050, 0.044),
    Policy("risk_clean_no_calm_nkd_family_cap_7p5", False, 0.075, 0.075),
]


def make_guard() -> MultiClusterGuard:
    return MultiClusterGuard(clusters={
        "roska4_swing": ClusterBudget("roska4_swing", 0.050, 0.044),
        "roska4_stress": ClusterBudget("roska4_stress", 0.10, None),
        "global_nkd": ClusterBudget("global_nkd", 0.060, 0.060),
        "roska4_calm": ClusterBudget("roska4_calm", 0.050, None),
    }, account=ACCOUNT)


def load_calm_a_atr15(which: str, meta: dict) -> pd.DataFrame:
    frames = dis.load_price_frames(which)
    return dis.build_calm_trades(which, dis.StopSpec("atr15", "atr", 1.5), meta, frames)


def family_admits(pos: Position, open_positions: list[Position], policy: Policy) -> bool:
    if policy.family_gross is None or pos.cluster not in ("roska4_swing", "roska4_calm"):
        return True
    book = [p for p in open_positions if p.cluster in ("roska4_swing", "roska4_calm")] + [pos]
    long_r = sum(p.risk_dollars for p in book if p.direction == "LONG")
    short_r = sum(p.risk_dollars for p in book if p.direction == "SHORT")
    gross = max(long_r, short_r) / ACCOUNT
    net = abs(long_r - short_r) / ACCOUNT
    if gross > policy.family_gross:
        return False
    if policy.family_net is not None and net > policy.family_net:
        return False
    return True


def replay_repaired(which: str, policy: Policy) -> tuple[pd.Series, dict]:
    r4, current_nkd, prices, extra, stress, calm_nkd_df = audit.load_all(which)
    calm_a = load_calm_a_atr15(which, extra["meta"])
    if not policy.include_calm_nkd_switch:
        calm_nkd_df = calm_nkd_df.iloc[0:0]
    guard = make_guard()
    breaker = full.CircuitBreaker(account=ACCOUNT)
    open_pos: list[tuple[Position, dict]] = []
    realized: dict[pd.Timestamp, float] = {}
    equity = ACCOUNT
    cur_day = None
    st = {
        "taken": {c: 0 for c in guard.clusters},
        "rejected": {c: 0 for c in guard.clusters},
        "family_rejected": 0,
        "halted": 0,
        "stress_closed_r4": 0,
        "stress_closed_calm": 0,
        "stress_switch_delta": 0.0,
        "calm_closed_current_nkd": 0,
        "calm_switch_delta": 0.0,
        "suppressed_current_nkd": 0,
        "suppressed_current_nkd_pnl": 0.0,
        "suppressed_calm_same_symbol": 0,
        "suppressed_calm_pnl": 0.0,
        "suppressed_normal_same_symbol": 0,
        "suppressed_normal_pnl": 0.0,
        "double_booked": 0,
        # Stage 5ZZZ-H. Purely additive: an accumulator, read by nobody in the control flow.
        # Added here rather than in a copy of this function because a copy is a second
        # implementation that can drift from the one that produced the record - and the whole
        # question this stage asks is a difference of a few thousand dollars.
        "pnl_by_cluster": {},
    }
    entries = pd.concat([p for p in (r4, stress, current_nkd, calm_nkd_df, calm_a) if not p.empty], ignore_index=True)
    by_time: dict[pd.Timestamp, list[dict]] = {}
    times = set()
    for _, row in entries.iterrows():
        tr = row.to_dict()
        et = pd.Timestamp(tr["entry_time"])
        xt = pd.Timestamp(tr["exit_time"])
        by_time.setdefault(et, []).append(tr)
        times.add(et)
        times.add(xt)
    booked = {}

    def book(ts: pd.Timestamp, tr: dict, pnl: float):
        nonlocal equity
        day = (pd.Timestamp(ts).tz_localize(None) if pd.Timestamp(ts).tz is not None else pd.Timestamp(ts)).normalize()
        c = str(tr.get("cluster") or "?")
        st["pnl_by_cluster"][c] = st["pnl_by_cluster"].get(c, 0.0) + float(pnl)
        equity += float(pnl)
        realized[day] = realized.get(day, 0.0) + float(pnl)
        tid = tr.get("trade_id", "?")
        booked[tid] = booked.get(tid, 0) + 1
        if booked[tid] > 1:
            st["double_booked"] += 1

    for ts in sorted(times):
        day = (pd.Timestamp(ts).tz_localize(None) if pd.Timestamp(ts).tz is not None else pd.Timestamp(ts)).normalize()
        if cur_day is None or day != cur_day:
            breaker.start_day(equity)
            cur_day = day
        still = []
        for pos, tr in open_pos:
            if pd.Timestamp(tr["exit_time"]) <= ts:
                book(ts, tr, float(tr["pnl_sized"]))
            else:
                still.append((pos, tr))
        open_pos = still
        breaker.update(equity)
        allow = breaker.status(equity).get("allow_new_entries", True)
        for tr in sorted(by_time.get(ts, []), key=entry_priority_key):
            if not allow:
                st["halted"] += 1
                continue
            src, inst, cluster = tr["source"], tr["instrument"], tr["cluster"]
            open_positions = [p for p, _ in open_pos]

            if src == "normal_nkd_filtered_bucket" and any(t["source"] == "calm_nkd" for _, t in open_pos):
                st["suppressed_current_nkd"] += 1
                st["suppressed_current_nkd_pnl"] += float(tr["pnl_sized"])
                continue

            if src == "calm_nkd":
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket")]
                proposed = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    st["rejected"][cluster] += 1
                    continue
                for _, old in [(p, t) for p, t in open_pos
                               if p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket"]:
                    ep = calm_nkd.early_nkd_pnl(old, float(tr["entry"]) + OFFSET[which])
                    book(ts, old, ep)
                    st["calm_closed_current_nkd"] += 1
                    st["calm_switch_delta"] += ep - float(old["pnl_sized"])
                open_pos = survivors
                st["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if src == "calm_a_pcloc_not_deep":
                if any(p.instrument == inst and p.cluster in ("roska4_swing", "roska4_stress") for p, _ in open_pos):
                    st["suppressed_calm_same_symbol"] += 1
                    st["suppressed_calm_pnl"] += float(tr["pnl_sized"])
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, open_positions)
                if ok and not family_admits(pos, open_positions, policy):
                    ok = False
                    st["family_rejected"] += 1
                if ok:
                    st["taken"][cluster] += 1
                    open_pos.append((pos, tr))
                else:
                    st["rejected"][cluster] += 1
                continue

            if cluster == "roska4_stress":
                # Repair: Stress override removes both Normal and Calm A same-symbol
                # positions from the survivor book before admission, then closes them
                # only if Stress is actually admitted.
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == inst and p.cluster in ("roska4_swing", "roska4_calm"))]
                proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)), float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    st["rejected"][cluster] += 1
                    continue
                for p, old in [(p, t) for p, t in open_pos
                               if p.instrument == inst and p.cluster in ("roska4_swing", "roska4_calm")]:
                    px = full.price_at_or_after(prices[inst], ts)
                    if px is None:
                        continue
                    if p.cluster == "roska4_calm":
                        ep = calm_a_base.early_calm_pnl(old, px, 2.0)
                        st["stress_closed_calm"] += 1
                    else:
                        ep = full.early_pnl(old, px, full.costs_for_basket(slippage_ticks=2.0))
                        st["stress_closed_r4"] += 1
                        st["stress_switch_delta"] += ep - float(old["pnl_sized"])
                    book(ts, old, ep)
                open_pos = survivors
                st["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if cluster == "roska4_swing":
                # Repair: bidirectional same-symbol suppression with Calm A as well
                # as Stress.
                if any(p.instrument == inst and p.cluster in ("roska4_stress", "roska4_calm") for p, _ in open_pos):
                    st["suppressed_normal_same_symbol"] += 1
                    st["suppressed_normal_pnl"] += float(tr["pnl_sized"])
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, open_positions)
                if ok and not family_admits(pos, open_positions, policy):
                    ok = False
                    st["family_rejected"] += 1
                if ok:
                    st["taken"][cluster] += 1
                    open_pos.append((pos, tr))
                else:
                    st["rejected"][cluster] += 1
                continue

            pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
            ok, _ = guard.admits(pos, open_positions)
            if ok:
                st["taken"][cluster] += 1
                open_pos.append((pos, tr))
            else:
                st["rejected"][cluster] += 1

    return pd.Series(realized).sort_index(), st


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_pct(x: float) -> str:
    return f"{100*x:.1f}%"


def fmt_float(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run_window(which: str) -> tuple[str, list[dict]]:
    rows, raw = [], []
    for p in POLICIES:
        daily, st = replay_repaired(which, p)
        m = metrics(daily)
        rows.append({
            "policy": p.name,
            "family_cap": "none" if p.family_gross is None else f"{p.family_gross:.1%}/{p.family_net:.1%}",
            "R4 taken/rej": f"{st['taken']['roska4_swing']}/{st['rejected']['roska4_swing']}",
            "Calm taken/rej": f"{st['taken']['roska4_calm']}/{st['rejected']['roska4_calm']}",
            "Stress taken/rej": f"{st['taken']['roska4_stress']}/{st['rejected']['roska4_stress']}",
            "NKD taken/rej": f"{st['taken']['global_nkd']}/{st['rejected']['global_nkd']}",
            "family_rej": st["family_rejected"],
            "stress_closed_calm": st["stress_closed_calm"],
            "supp_norm": st["suppressed_normal_same_symbol"],
            "supp_calm": st["suppressed_calm_same_symbol"],
            "calm_nkd_closes": st["calm_closed_current_nkd"],
            "calm_switch_delta": fmt_money(st["calm_switch_delta"]),
            "double_booked": st["double_booked"],
            "net": fmt_money(m["pnl"]),
            "pf": fmt_float(m["pf"]),
            "sharpe": fmt_float(m["sharpe"]),
            "calmar": fmt_float(m["calmar"]),
            "maxdd": fmt_money(m["maxdd"]),
            "halts": st["halted"],
        })
        raw.append({"policy": p.__dict__, "metrics": m, "state": st})
    section = "\n".join([f"## {which}", "", table(rows, [
        "policy", "family_cap", "R4 taken/rej", "Calm taken/rej", "Stress taken/rej",
        "NKD taken/rej", "family_rej", "stress_closed_calm", "supp_norm", "supp_calm",
        "calm_nkd_closes", "calm_switch_delta", "double_booked", "net", "pf", "sharpe",
        "calmar", "maxdd", "halts",
    ]), ""])
    return section, raw


def main() -> int:
    parts = [
        "# Combined Repaired Replay - 2026-08-22",
        "",
        "Scratch-only repair/re-measure after stop/risk audit blockers.",
        "",
        "Repairs applied:",
        "",
        "- Stress same-symbol override removes both Normal-R4 and Calm A from survivors before admission; no double settlement.",
        "- Normal-R4 is suppressed if same-symbol Calm A or Stress is already open.",
        "- Calm-NKD forced close is repriced onto the current-NKD artifact price scale using measured constant offsets.",
        "- Calm A uses ATR15 disaster-stop trades and true stop-risk.",
        "",
        "Still not repaired here: Calm-NKD risk definition. Rows with Calm-NKD switch remain research-only until that sleeve is regenerated with true stop-at-entry risk.",
        "",
    ]
    out = {}
    for which in ("floor", "vault2025", "vault2026"):
        section, raw = run_window(which)
        parts.append(section)
        out[which] = raw
    OUT.write_text("\n".join(parts), encoding="utf-8")
    JSON_OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    print(JSON_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
