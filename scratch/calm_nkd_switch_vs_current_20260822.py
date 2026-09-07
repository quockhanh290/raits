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
import scratch.stress_with_nkd_probe_20260822 as nkd_base
from futures.circuit_breaker import CircuitBreaker
from global_index.deploy_sim import metrics
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard, Position, entry_priority_key
from scratch.normal_sleeve_fill_audit import ACCOUNT


OUT = Path("scratch/calm_nkd_switch_vs_current_20260822_report.md")
JSON_OUT = Path("scratch/calm_nkd_switch_vs_current_20260822.json")
CALM_NKD_TRADES = Path("scratch/calm_nkd_swing_calm_only_trades.csv")
VARIANT = "nkd_swing_d1calm_as_normal_ema5_mult2.5"


@dataclass(frozen=True)
class Mode:
    name: str
    use_current_nkd: bool
    use_calm_nkd: bool
    calm_switch: bool


MODES = [
    Mode("current_nkd", True, False, False),
    Mode("calm_nkd_replacement", False, True, False),
    Mode("current_nkd_plus_calm_switch", True, True, True),
]


WINDOW_MAP = {
    "floor": "IS_2018_2024",
    "vault2025": "OOS_2025",
    "vault2026": "SANITY_2026",
}


def load_calm_nkd(which: str, meta: dict) -> pd.DataFrame:
    window = WINDOW_MAP[which]
    src = pd.read_csv(CALM_NKD_TRADES)
    src = src[(src["window"] == window) & (src["variant"] == VARIANT)].copy()
    if src.empty:
        return pd.DataFrame()
    rows = []
    m = meta["MNKD"]
    for i, t in src.reset_index(drop=True).iterrows():
        ed = pd.Timestamp(t["day"])
        xd = pd.Timestamp(t["exit_day"]) if pd.notna(t.get("exit_day")) else ed
        rows.append({
            "trade_id": f"calm_nkd_{window}_{i}",
            "source": "calm_nkd",
            "cluster": "global_nkd",
            "instrument": "MNKD",
            "direction": t["direction"],
            "day": ed.normalize(),
            "entry_time": pd.Timestamp(t["entry_time"]),
            "exit_time": pd.Timestamp(t["exit_time"]),
            "entry": float(t["entry"]),
            "exit": float(t["exit"]),
            "pnl_sized": float(t["pnl"]),
            "risk_sized": nkd_base._real_risk(m["atr"], 2.5, m["pv"], ed, 1),
        })
    return pd.DataFrame(rows)


def make_guard() -> MultiClusterGuard:
    clusters = {
        "roska4_swing": ClusterBudget("roska4_swing", 0.050, 0.044),
        "roska4_stress": ClusterBudget("roska4_stress", 0.10, None),
        "global_nkd": ClusterBudget("global_nkd", 0.060, 0.060),
    }
    return MultiClusterGuard(clusters=clusters, account=ACCOUNT)


def early_nkd_pnl(old: dict, exit_px: float) -> float:
    pv = 0.5  # MNKD point value from the repo spec; existing trade pnl confirms this scale.
    # Approximate a flip at the new Calm entry price. The original trade already paid
    # round-turn costs, so keep the same convention as other switch probes and charge
    # one closed trade's cost via the original round-turn embedded in the recomputed path.
    gross = (exit_px - old["entry"]) if old["direction"] == "LONG" else (old["entry"] - exit_px)
    # MNKD round-turn in current artifacts is effectively about $11.40.
    return gross * pv - 11.40


def replay(r4: pd.DataFrame, stress: pd.DataFrame, current_nkd: pd.DataFrame,
           calm_nkd: pd.DataFrame, mode: Mode, prices: dict[str, pd.DataFrame]) -> tuple[pd.Series, dict]:
    guard = make_guard()
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
        "stress_switch_delta": 0.0,
        "calm_closed_current_nkd": 0,
        "calm_switch_delta": 0.0,
        "suppressed_current_nkd": 0,
        "suppressed_current_nkd_pnl": 0.0,
        "suppressed_r4": 0,
    }
    pieces = [r4, stress]
    if mode.use_current_nkd:
        pieces.append(current_nkd)
    if mode.use_calm_nkd:
        pieces.append(calm_nkd)
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
                stats["suppressed_current_nkd_pnl"] += float(tr["pnl_sized"])
                continue

            if src == "calm_nkd" and mode.calm_switch:
                survivors = [(p, t) for p, t in open_pos if not (p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket")]
                proposed = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    stats["rejected"][cluster] += 1
                    continue
                closing = [(p, t) for p, t in open_pos if p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket"]
                for _, old in closing:
                    ep = early_nkd_pnl(old, float(tr["entry"]))
                    realize(ts, ep)
                    stats["calm_closed_current_nkd"] += 1
                    stats["calm_switch_delta"] += ep - float(old["pnl_sized"])
                open_pos = survivors
                stats["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if cluster == "roska4_stress":
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
                    ep = full.early_pnl(old, px, full.costs_for_basket(slippage_ticks=2.0))
                    realize(ts, ep)
                    stats["stress_closed_r4"] += 1
                    stats["stress_switch_delta"] += ep - float(old["pnl_sized"])
                open_pos = survivors
                stats["taken"][cluster] += 1
                open_pos.append((proposed, tr))
                continue

            if cluster == "roska4_swing" and any(p.instrument == inst and p.cluster == "roska4_stress" for p, _ in open_pos):
                stats["suppressed_r4"] += 1
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
    if daily.empty:
        return dict(net=0.0, ret=0.0, pf=0.0, sharpe=0.0, calmar=0.0, maxdd=0.0)
    return dict(
        net=float(m["pnl"]),
        ret=float(m["pnl"] / ACCOUNT),
        pf=float(m["pf"]),
        sharpe=float(m["sharpe"]),
        calmar=float(m["calmar"]),
        maxdd=float(m["maxdd"]),
    )


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
    r4, current_nkd, prices, extra = nkd_base.load_r4_and_nkd(which)
    stress = extra["stress"]
    calm_nkd = load_calm_nkd(which, extra["meta"])
    rows, raw = [], []
    for mode in MODES:
        daily, st = replay(r4, stress, current_nkd, calm_nkd, mode, prices)
        m = summarize(daily)
        rows.append({
            "mode": mode.name,
            "current_nkd_trades": int(len(current_nkd) if mode.use_current_nkd else 0),
            "calm_nkd_trades": int(len(calm_nkd) if mode.use_calm_nkd else 0),
            "R4 taken/rej": f"{st['taken']['roska4_swing']}/{st['rejected']['roska4_swing']}",
            "Stress taken/rej": f"{st['taken']['roska4_stress']}/{st['rejected']['roska4_stress']}",
            "NKD taken/rej": f"{st['taken']['global_nkd']}/{st['rejected']['global_nkd']}",
            "calm_closed_current": st["calm_closed_current_nkd"],
            "calm_switch_delta": fmt_money(st["calm_switch_delta"]),
            "suppressed_current": st["suppressed_current_nkd"],
            "suppressed_current_pnl": fmt_money(st["suppressed_current_nkd_pnl"]),
            "net": fmt_money(m["net"]),
            "ret": fmt_pct(m["ret"]),
            "pf": fmt_float(m["pf"]),
            "sharpe": fmt_float(m["sharpe"]),
            "calmar": fmt_float(m["calmar"]),
            "maxdd": fmt_money(m["maxdd"]),
            "halts": st["halted"],
        })
        raw.append({"mode": mode.__dict__, "metrics": m, "state": st})
    section = "\n".join([f"## {which}", "", table(rows, [
        "mode", "current_nkd_trades", "calm_nkd_trades", "R4 taken/rej",
        "Stress taken/rej", "NKD taken/rej", "calm_closed_current",
        "calm_switch_delta", "suppressed_current", "suppressed_current_pnl",
        "net", "ret", "pf", "sharpe", "calmar", "maxdd", "halts",
    ]), ""])
    return section, raw


def main() -> int:
    parts = [
        "# Calm-NKD Switch vs Current NKD - 2026-08-22",
        "",
        "Scratch-only. Base includes Normal-R4 filtered and Stress-MNQ `mnq_only_g3_q7` cap 10%. This tests Candidate B as replacement and as a switch override of the existing NKD sleeve.",
        "",
        "Switch mode: if Calm-NKD is admitted, close any open current MNKD position at the Calm-NKD entry price, enter Calm-NKD, and suppress current NKD entries while Calm-NKD remains open.",
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
