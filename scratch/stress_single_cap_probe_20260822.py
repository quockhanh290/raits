from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_switch_full_replay_20260822 as full
from futures.basket import BASKET
from futures.circuit_breaker import CircuitBreaker
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard, Position, entry_priority_key
from scratch.normal_sleeve_fill_audit import ACCOUNT


OUT = Path("scratch/stress_single_cap_probe_20260822_report.md")
JSON_OUT = Path("scratch/stress_single_cap_probe_20260822.json")


@dataclass(frozen=True)
class Policy:
    name: str
    normal_gross: float
    normal_net: float
    stress_gross: float


POLICIES = [
    Policy("split_current_normal5_net44_stress10", 0.050, 0.044, 0.100),
    Policy("single_5", 0.050, 0.050, 0.050),
    Policy("single_7p5", 0.075, 0.075, 0.075),
    Policy("single_10", 0.100, 0.100, 0.100),
]


SCENARIO = full.Scenario("mnq_only_g3_q7", ("MNQ",), 7)


def make_guard(policy: Policy) -> MultiClusterGuard:
    clusters = {
        "roska4_swing": ClusterBudget("roska4_swing", policy.normal_gross, policy.normal_net),
        "roska4_stress": ClusterBudget("roska4_stress", policy.stress_gross, None),
    }
    return MultiClusterGuard(clusters=clusters, account=ACCOUNT)


def replay_intraday_policy(normal: pd.DataFrame, stress: pd.DataFrame, prices: dict[str, pd.DataFrame],
                           policy: Policy) -> tuple[pd.Series, dict]:
    costs = costs_for_basket(slippage_ticks=2.0)
    guard = make_guard(policy)
    breaker = CircuitBreaker(account=ACCOUNT)
    realized: dict[pd.Timestamp, float] = {}
    open_pos: list[tuple[Position, dict]] = []
    equity = ACCOUNT
    cur_day = None
    stats = {
        "taken": {"roska4_swing": 0, "roska4_stress": 0},
        "rejected": {"roska4_swing": 0, "roska4_stress": 0},
        "halted": 0,
        "closed_for_switch": 0,
        "switch_delta": 0.0,
        "suppressed_normal": 0,
        "suppressed_normal_pnl": 0.0,
        "stress_attempts": int(len(stress)),
    }
    by_time: dict[pd.Timestamp, list[dict]] = {}
    times = set()
    for _, r in normal.iterrows():
        obj = r.to_dict()
        ts = pd.Timestamp(obj["entry_time"])
        by_time.setdefault(ts, []).append(obj)
        times.add(ts)
        times.add(pd.Timestamp(obj["exit_time"]))
    for _, r in stress.iterrows():
        obj = r.to_dict()
        ts = pd.Timestamp(obj["entry_time"])
        by_time.setdefault(ts, []).append(obj)
        times.add(ts)
        times.add(pd.Timestamp(obj["exit_time"]))

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
            inst = tr["instrument"]
            cluster = tr["cluster"]
            if cluster == "roska4_swing":
                if any(p.instrument == inst and p.cluster == "roska4_stress" for p, _ in open_pos):
                    stats["suppressed_normal"] += 1
                    stats["suppressed_normal_pnl"] += float(tr["pnl_sized"])
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, [p for p, _ in open_pos])
                if ok:
                    stats["taken"][cluster] += 1
                    open_pos.append((pos, tr))
                else:
                    stats["rejected"][cluster] += 1
                continue
            survivors = [(p, t) for p, t in open_pos if not (p.instrument == inst and p.cluster == "roska4_swing")]
            proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)), float(tr["risk_sized"]), cluster)
            ok, _ = guard.admits(proposed, [p for p, _ in survivors])
            if not ok:
                stats["rejected"][cluster] += 1
                continue
            closing = [(p, t) for p, t in open_pos if p.instrument == inst and p.cluster == "roska4_swing"]
            for _, old in closing:
                px = full.price_at_or_after(prices[inst], ts)
                if px is None:
                    continue
                ep = full.early_pnl(old, px, costs)
                realize(ts, ep)
                stats["closed_for_switch"] += 1
                stats["switch_delta"] += ep - float(old["pnl_sized"])
            open_pos = survivors
            stats["taken"][cluster] += 1
            open_pos.append((proposed, tr))
    return pd.Series(realized).sort_index(), stats


def summarize(daily: pd.Series) -> dict:
    m = metrics(daily)
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1) if len(daily) else 1.0
    return dict(
        net=float(m["pnl"]),
        ret=float(m["pnl"] / ACCOUNT),
        pf=float(m["pf"]),
        sharpe=float(m["sharpe"]),
        calmar=float(m["calmar"]),
        maxdd=float(m["maxdd"]),
        ret_yr=float(m["pnl"] / ACCOUNT / span),
    )


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def fmt_float(x: float) -> str:
    return "inf" if x == float("inf") else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run_window(which: str) -> tuple[str, dict]:
    normal, _ = full.load_normal(which)
    stress, prices = full.load_stress(which, SCENARIO)
    rows = []
    raw = []
    for p in POLICIES:
        daily, st = replay_intraday_policy(normal, stress, prices, p)
        m = summarize(daily)
        row = {
            "policy": p.name,
            "normal_cap": f"{p.normal_gross:.1%}/{p.normal_net:.1%}",
            "stress_cap": f"{p.stress_gross:.1%}",
            "normal_taken_rej": f"{st['taken']['roska4_swing']}/{st['rejected']['roska4_swing']}",
            "stress_taken_rej": f"{st['taken']['roska4_stress']}/{st['rejected']['roska4_stress']}",
            "closed": st["closed_for_switch"],
            "blocked_late_normal": st["suppressed_normal"],
            "net": fmt_money(m["net"]),
            "ret": fmt_pct(m["ret"]),
            "pf": fmt_float(m["pf"]),
            "sharpe": fmt_float(m["sharpe"]),
            "calmar": fmt_float(m["calmar"]),
            "maxdd": fmt_money(m["maxdd"]),
            "halts": st["halted"],
        }
        rows.append(row)
        raw.append({"policy": p.__dict__, "metrics": m, "state": st})
    return "\n".join([f"## {which}", "", table(rows, [
        "policy", "normal_cap", "stress_cap", "normal_taken_rej", "stress_taken_rej",
        "closed", "blocked_late_normal", "net", "ret", "pf", "sharpe", "calmar",
        "maxdd", "halts",
    ]), ""]), {"rows": raw, "stress_legs": int(len(stress)), "normal_attempts": int(len(normal))}


def main() -> int:
    parts = [
        "# Stress Single-Cap Probe - 2026-08-22",
        "",
        "Scratch-only. Candidate: `mnq_only_g3_q7`. This tests whether using one cap level for both Normal and Stress improves the book.",
        "",
        "`single_X` means Normal gross cap = X, Normal net cap = X, and Stress gross cap = X.",
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
