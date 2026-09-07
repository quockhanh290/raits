from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.calm_nkd_switch_vs_current_20260822 as calm_nkd
import scratch.stress_switch_full_replay_20260822 as full
import scratch.stress_with_nkd_probe_20260822 as nkd_base
from futures.basket import BASKET
from futures.circuit_breaker import CircuitBreaker
from global_index.deploy_sim import metrics
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard, Position, entry_priority_key
from scratch.normal_sleeve_fill_audit import ACCOUNT, _real_risk


OUT = Path("scratch/calm_a_combined_replay_20260822_report.md")
JSON_OUT = Path("scratch/calm_a_combined_replay_20260822.json")
CALM_A_CSV = Path("scratch/calm_pcloc_not_deep_gap_trade_list.csv")

WINDOW_MAP = {
    "floor": "IS_2018_2024",
    "vault2025": "OOS_2025",
    "vault2026": "SANITY_2026",
}


@dataclass(frozen=True)
class Policy:
    name: str
    calm_cap: float
    overlap: str
    slip_ticks: float


POLICIES = []
for cap in (0.015, 0.025, 0.05):
    POLICIES.append(Policy(f"skip_cap{cap:g}_slip2", cap, "skip_same_symbol", 2.0))
POLICIES.append(Policy("stress_override_cap025_slip2", 0.025, "stress_overrides_calm", 2.0))
POLICIES.append(Policy("stack_cap025_slip2", 0.025, "stack_allowed", 2.0))
for slip in (3.0, 4.0, 6.0):
    POLICIES.append(Policy(f"skip_cap025_slip{int(slip)}", 0.025, "skip_same_symbol", slip))


DATA_CACHE = {}


def load_calm_a(which: str, meta: dict, slip_ticks: float) -> pd.DataFrame:
    df = pd.read_csv(CALM_A_CSV)
    df = df[df["window"] == WINDOW_MAP[which]].copy()
    rows = []
    for i, t in df.reset_index(drop=True).iterrows():
        inst = t["inst"]
        ed = pd.Timestamp(t["day"])
        extra_cost = 2.0 * max(0.0, slip_ticks - 2.0) * BASKET[inst].tick * BASKET[inst].point_value
        rows.append({
            "trade_id": f"calm_a_{which}_{inst}_{i}",
            "source": "calm_a_pcloc_not_deep",
            "cluster": "roska4_calm",
            "instrument": inst,
            "direction": t["direction"],
            "day": ed.normalize(),
            "entry_time": pd.Timestamp(t["entry_time"]),
            "exit_time": pd.Timestamp(t["exit_time"]),
            "entry": float(t["entry"]),
            "exit": float(t["exit"]),
            "pnl_sized": float(t["pnl"]) - extra_cost,
            "risk_sized": _real_risk(meta[inst]["atr"], meta[inst]["mult"], meta[inst]["pv"], ed, 1),
            "outside_exit_bar": int(t.get("outside_exit_bar", 0)),
            "outside_entry_bar": int(t.get("outside_entry_bar", 0)),
            "signal_after_entry": int(t.get("signal_after_entry", 0)),
        })
    return pd.DataFrame(rows)


def make_guard(calm_cap: float) -> MultiClusterGuard:
    clusters = {
        "roska4_swing": ClusterBudget("roska4_swing", 0.050, 0.044),
        "roska4_stress": ClusterBudget("roska4_stress", 0.10, None),
        "global_nkd": ClusterBudget("global_nkd", 0.060, 0.060),
        "roska4_calm": ClusterBudget("roska4_calm", calm_cap, None),
    }
    return MultiClusterGuard(clusters=clusters, account=ACCOUNT)


def early_calm_pnl(old: dict, px: float, slip_ticks: float) -> float:
    inst = old["instrument"]
    pv = BASKET[inst].point_value
    gross = (px - old["entry"]) if old["direction"] == "LONG" else (old["entry"] - px)
    cost = full.costs_for_basket(slippage_ticks=slip_ticks)[inst].round_turn_cost()
    return gross * pv - cost


def replay(which: str, policy: Policy) -> tuple[pd.Series, dict]:
    if which not in DATA_CACHE:
        r4, current_nkd, prices, extra = nkd_base.load_r4_and_nkd(which)
        stress = extra["stress"]
        calm_nkd_df = calm_nkd.load_calm_nkd(which, extra["meta"])
        DATA_CACHE[which] = (r4, current_nkd, prices, extra, stress, calm_nkd_df)
    r4, current_nkd, prices, extra, stress, calm_nkd_df = DATA_CACHE[which]
    calm_a = load_calm_a(which, extra["meta"], policy.slip_ticks)
    guard = make_guard(policy.calm_cap)
    breaker = CircuitBreaker(account=ACCOUNT)
    realized: dict[pd.Timestamp, float] = {}
    open_pos: list[tuple[Position, dict]] = []
    equity = ACCOUNT
    cur_day = None
    stats = {
        "taken": {c: 0 for c in guard.clusters},
        "rejected": {c: 0 for c in guard.clusters},
        "halted": 0,
        "stress_closed_r4": 0,
        "stress_closed_calm": 0,
        "calm_closed_current_nkd": 0,
        "suppressed_current_nkd": 0,
        "suppressed_calm_same_symbol": 0,
        "suppressed_calm_pnl": 0.0,
        "calm_attempted": int(len(calm_a)),
        "calm_audit_bad": int(calm_a[["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]].sum().sum()) if not calm_a.empty else 0,
    }
    pieces = [r4, stress, current_nkd, calm_nkd_df, calm_a]
    entries = pd.concat([p for p in pieces if not p.empty], ignore_index=True)
    by_time: dict[pd.Timestamp, list[dict]] = {}
    times = set()
    for _, r in entries.iterrows():
        obj = r.to_dict()
        ets = pd.Timestamp(obj["entry_time"])
        xts = pd.Timestamp(obj["exit_time"])
        by_time.setdefault(ets, []).append(obj)
        times.add(ets)
        times.add(xts)

    def realize(ts: pd.Timestamp, pnl: float):
        nonlocal equity
        day = pd.Timestamp(ts).tz_localize(None).normalize()
        equity += float(pnl)
        realized[day] = realized.get(day, 0.0) + float(pnl)

    for ts in sorted(times):
        day = pd.Timestamp(ts).tz_localize(None).normalize()
        if cur_day is None or day != cur_day:
            breaker.start_day(equity)
            cur_day = day
        still = []
        for pos, tr in open_pos:
            if pd.Timestamp(tr["exit_time"]) <= ts:
                realize(ts, float(tr["pnl_sized"]))
            else:
                still.append((pos, tr))
        open_pos = still
        breaker.update(equity)
        allow = breaker.status(equity).get("allow_new_entries", True)

        for tr in sorted(by_time.get(ts, []), key=entry_priority_key):
            if not allow:
                stats["halted"] += 1
                continue
            src = tr["source"]
            inst = tr["instrument"]
            cluster = tr["cluster"]

            if src == "normal_nkd_filtered_bucket" and any(t["source"] == "calm_nkd" for _, t in open_pos):
                stats["suppressed_current_nkd"] += 1
                continue

            if src == "calm_nkd":
                survivors = [(p, t) for p, t in open_pos if not (p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket")]
                proposed = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    stats["rejected"][cluster] += 1
                    continue
                closing = [(p, t) for p, t in open_pos if p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket"]
                for _, old in closing:
                    ep = calm_nkd.early_nkd_pnl(old, float(tr["entry"]))
                    realize(ts, ep)
                    stats["calm_closed_current_nkd"] += 1
                open_pos = survivors
                stats["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if src == "calm_a_pcloc_not_deep":
                if policy.overlap in ("skip_same_symbol", "stress_overrides_calm"):
                    hit = any(p.instrument == inst and p.cluster in ("roska4_swing", "roska4_stress") for p, _ in open_pos)
                    if hit:
                        stats["suppressed_calm_same_symbol"] += 1
                        stats["suppressed_calm_pnl"] += float(tr["pnl_sized"])
                        continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, [p for p, _ in open_pos])
                if ok:
                    stats["taken"][cluster] += 1
                    open_pos.append((pos, tr))
                else:
                    stats["rejected"][cluster] += 1
                continue

            if cluster == "roska4_stress":
                survivors = [(p, t) for p, t in open_pos if not (
                    p.instrument == inst and (
                        p.cluster == "roska4_swing"
                        or (policy.overlap == "stress_overrides_calm" and p.cluster == "roska4_calm")
                    )
                )]
                proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)), float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    stats["rejected"][cluster] += 1
                    continue
                closing = [(p, t) for p, t in open_pos if p.instrument == inst and p.cluster in ("roska4_swing", "roska4_calm")]
                for p, old in closing:
                    px = full.price_at_or_after(prices[inst], ts)
                    if px is None:
                        continue
                    if p.cluster == "roska4_calm":
                        ep = early_calm_pnl(old, px, policy.slip_ticks)
                        stats["stress_closed_calm"] += 1
                    else:
                        ep = full.early_pnl(old, px, full.costs_for_basket(slippage_ticks=2.0))
                        stats["stress_closed_r4"] += 1
                    realize(ts, ep)
                open_pos = survivors
                stats["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if cluster == "roska4_swing" and any(p.instrument == inst and p.cluster == "roska4_stress" for p, _ in open_pos):
                continue

            pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if ok:
                stats["taken"][cluster] += 1
                open_pos.append((pos, tr))
            else:
                stats["rejected"][cluster] += 1

    return pd.Series(realized).sort_index(), stats


def summarize(daily: pd.Series) -> dict:
    m = metrics(daily)
    return dict(net=float(m["pnl"]), ret=float(m["pnl"] / ACCOUNT), pf=float(m["pf"]),
                sharpe=float(m["sharpe"]), calmar=float(m["calmar"]), maxdd=float(m["maxdd"]))


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
        daily, st = replay(which, p)
        m = summarize(daily)
        rows.append({
            "policy": p.name,
            "overlap": p.overlap,
            "calm_cap": fmt_pct(p.calm_cap),
            "slip": f"{p.slip_ticks:g}",
            "Calm attempted": st["calm_attempted"],
            "Calm taken/rej": f"{st['taken']['roska4_calm']}/{st['rejected']['roska4_calm']}",
            "Calm suppressed": st["suppressed_calm_same_symbol"],
            "Stress closed Calm": st["stress_closed_calm"],
            "NKD taken/rej": f"{st['taken']['global_nkd']}/{st['rejected']['global_nkd']}",
            "net": fmt_money(m["net"]),
            "ret": fmt_pct(m["ret"]),
            "pf": fmt_float(m["pf"]),
            "sharpe": fmt_float(m["sharpe"]),
            "calmar": fmt_float(m["calmar"]),
            "maxdd": fmt_money(m["maxdd"]),
            "halts": st["halted"],
            "audit_bad": st["calm_audit_bad"],
        })
        raw.append({"policy": p.__dict__, "metrics": m, "state": st})
    section = "\n".join([f"## {which}", "", table(rows, [
        "policy", "overlap", "calm_cap", "slip", "Calm attempted", "Calm taken/rej",
        "Calm suppressed", "Stress closed Calm", "NKD taken/rej", "net", "ret",
        "pf", "sharpe", "calmar", "maxdd", "halts", "audit_bad",
    ]), ""])
    return section, raw


def main() -> int:
    parts = [
        "# Calm A Combined Replay - 2026-08-22",
        "",
        "Scratch-only. Base includes Normal-R4 filtered, Stress-MNQ `mnq_only_g3_q7` cap 10%, and current NKD + Calm-NKD switch challenger. Candidate A is `Calm PCLoc bottom-down not-deep-gap` as `roska4_calm`.",
        "",
        "Calm cap uses ATR risk proxy (`daily_ATR * 2.5 * point_value`) because Candidate A has no explicit stop.",
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
