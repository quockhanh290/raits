from __future__ import annotations

import json
import math
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
from scratch.normal_sleeve_fill_audit import ACCOUNT, R4, _real_risk


OUT = Path("scratch/stress_with_nkd_probe_20260822_report.md")
JSON_OUT = Path("scratch/stress_with_nkd_probe_20260822.json")
SCENARIO = full.Scenario("mnq_only_g3_q7", ("MNQ",), 7)


@dataclass(frozen=True)
class BookSpec:
    name: str
    use_stress: bool
    use_nkd: bool
    stress_cap: float = 0.10


BOOKS = [
    BookSpec("R4 only", False, False),
    BookSpec("R4 + Stress", True, False),
    BookSpec("R4 + NKD", False, True),
    BookSpec("R4 + Stress + NKD", True, True),
]


def load_r4_and_nkd(which: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame], dict]:
    normal, meta = full.load_normal(which)
    raw = json.loads(full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    nkd = raw["nkd_instrument"]
    rows = []
    m = meta[nkd]
    for i, t in enumerate(raw["filtered"].get(nkd, raw["raw"].get(nkd, []))):
        ed = pd.Timestamp(t["day"])
        xd = pd.Timestamp(t["exit_day"]) if t.get("exit_day") else ed
        if ed.tz is not None:
            ed = ed.tz_localize(None)
        if xd.tz is not None:
            xd = xd.tz_localize(None)
        rows.append({
            "trade_id": f"nkd_filtered_{nkd}_{i}",
            "source": "normal_nkd_filtered_bucket",
            "cluster": "global_nkd",
            "instrument": nkd,
            "direction": t["direction"],
            "day": ed.normalize(),
            "entry_time": pd.Timestamp(t["entry_time"]),
            "exit_time": pd.Timestamp(t["exit_time"]),
            "entry": float(t["entry"]),
            "exit": float(t["exit"]),
            "pnl_sized": float(t["pnl"]),
            "risk_sized": _real_risk(m["atr"], m["mult"], m["pv"], ed, 1),
        })
    stress, prices = full.load_stress(which, SCENARIO)
    return normal, pd.DataFrame(rows), prices, {"meta": meta, "stress": stress, "nkd": nkd}


def make_guard(stress_cap: float) -> MultiClusterGuard:
    clusters = {
        "roska4_swing": ClusterBudget("roska4_swing", 0.050, 0.044),
        "roska4_stress": ClusterBudget("roska4_stress", stress_cap, None),
        "global_nkd": ClusterBudget("global_nkd", 0.060, 0.060),
    }
    return MultiClusterGuard(clusters=clusters, account=ACCOUNT)


def replay_book(r4: pd.DataFrame, nkd: pd.DataFrame, stress: pd.DataFrame,
                prices: dict[str, pd.DataFrame], spec: BookSpec) -> tuple[pd.Series, dict]:
    costs = costs_for_basket(slippage_ticks=2.0)
    guard = make_guard(spec.stress_cap)
    breaker = CircuitBreaker(account=ACCOUNT)
    realized: dict[pd.Timestamp, float] = {}
    open_pos: list[tuple[Position, dict]] = []
    equity = ACCOUNT
    cur_day = None
    stats = {
        "taken": {c: 0 for c in guard.clusters},
        "rejected": {c: 0 for c in guard.clusters},
        "halted": 0,
        "closed_for_switch": 0,
        "switch_delta": 0.0,
        "suppressed_normal": 0,
        "suppressed_normal_pnl": 0.0,
    }
    pieces = [r4]
    if spec.use_nkd:
        pieces.append(nkd)
    if spec.use_stress:
        pieces.append(stress)
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
            cluster = tr["cluster"]
            inst = tr["instrument"]
            if not allow:
                stats["halted"] += 1
                continue
            if cluster != "roska4_stress":
                if cluster == "roska4_swing" and any(
                    p.instrument == inst and p.cluster == "roska4_stress" for p, _ in open_pos
                ):
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
    if daily.empty:
        return dict(net=0.0, ret=0.0, pf=0.0, sharpe=0.0, calmar=0.0, maxdd=0.0, winrate=0.0)
    return dict(
        net=float(m["pnl"]),
        ret=float(m["pnl"] / ACCOUNT),
        pf=float(m["pf"]),
        sharpe=float(m["sharpe"]),
        calmar=float(m["calmar"]),
        maxdd=float(m["maxdd"]),
        winrate=float((daily > 0).mean()),
    )


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def fmt_float(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run_window(which: str) -> tuple[str, dict]:
    r4, nkd, prices, extra = load_r4_and_nkd(which)
    stress = extra["stress"]
    rows, raw = [], []
    for spec in BOOKS:
        daily, st = replay_book(r4, nkd, stress, prices, spec)
        m = summarize(daily)
        rows.append({
            "book": spec.name,
            "trades_attempted": int(len(r4) + (len(nkd) if spec.use_nkd else 0) + (len(stress) if spec.use_stress else 0)),
            "R4 taken/rej": f"{st['taken']['roska4_swing']}/{st['rejected']['roska4_swing']}",
            "Stress taken/rej": f"{st['taken']['roska4_stress']}/{st['rejected']['roska4_stress']}",
            "NKD taken/rej": f"{st['taken']['global_nkd']}/{st['rejected']['global_nkd']}",
            "closed": st["closed_for_switch"],
            "blocked_late_normal": st["suppressed_normal"],
            "net": fmt_money(m["net"]),
            "ret": fmt_pct(m["ret"]),
            "pf": fmt_float(m["pf"]),
            "sharpe": fmt_float(m["sharpe"]),
            "calmar": fmt_float(m["calmar"]),
            "maxdd": fmt_money(m["maxdd"]),
            "winrate": fmt_pct(m["winrate"]),
            "halts": st["halted"],
        })
        raw.append({"book": spec.__dict__, "metrics": m, "state": st})
    return "\n".join([f"## {which}", "", f"Stress legs: {len(stress)}. NKD/MNKD trades in artifact: {len(nkd)}.", "", table(rows, [
        "book", "trades_attempted", "R4 taken/rej", "Stress taken/rej", "NKD taken/rej",
        "closed", "blocked_late_normal", "net", "ret", "pf", "sharpe", "calmar",
        "maxdd", "winrate", "halts",
    ]), ""]), {"rows": raw, "stress_legs": int(len(stress)), "nkd_trades": int(len(nkd))}


def main() -> int:
    parts = [
        "# Stress With NKD Probe - 2026-08-22",
        "",
        "Scratch-only. Candidate: `mnq_only_g3_q7` with split caps: Normal-R4 5.0% gross / 4.4% net, Stress 10.0% gross, NKD 6.0% gross / 6.0% net.",
        "",
        "Books measured: R4 only, R4+Stress, R4+NKD, R4+Stress+NKD. Stress switch only affects same-symbol R4 positions; NKD is a separate cluster.",
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
