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
import scratch.stress_with_nkd_probe_20260822 as nkd_probe
from global_index.deploy_sim import metrics
from scratch.normal_sleeve_fill_audit import ACCOUNT


OUT = Path("scratch/stress_nkd_size_cap_sweep_20260822_report.md")
JSON_OUT = Path("scratch/stress_nkd_size_cap_sweep_20260822.json")


@dataclass(frozen=True)
class Sweep:
    name: str
    nkd_qty: int
    nkd_cap: float


SWEEPS = [
    Sweep("nkd_off", 0, 0.06),
    Sweep("nkd_q1_cap6", 1, 0.06),
    Sweep("nkd_q1_cap9", 1, 0.09),
    Sweep("nkd_q1_cap12", 1, 0.12),
    Sweep("nkd_q2_cap6", 2, 0.06),
    Sweep("nkd_q2_cap9", 2, 0.09),
    Sweep("nkd_q2_cap12", 2, 0.12),
]


def scaled_nkd(nkd: pd.DataFrame, qty: int) -> pd.DataFrame:
    if qty <= 0 or nkd.empty:
        return nkd.iloc[0:0].copy()
    out = nkd.copy()
    out["pnl_sized"] = out["pnl_sized"].astype(float) * qty
    out["risk_sized"] = out["risk_sized"].astype(float) * qty
    out["qty"] = qty
    return out


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
    return f"{100 * x:.1f}%"


def fmt_float(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run_window(which: str) -> tuple[str, list[dict]]:
    r4, nkd, prices, extra = nkd_probe.load_r4_and_nkd(which)
    stress = extra["stress"]
    rows, raw = [], []
    for sw in SWEEPS:
        spec = nkd_probe.BookSpec(
            name=f"R4 + Stress + {sw.name}",
            use_stress=True,
            use_nkd=sw.nkd_qty > 0,
            stress_cap=0.10,
        )
        nkd_scaled = scaled_nkd(nkd, sw.nkd_qty)
        old_make_guard = nkd_probe.make_guard

        def make_guard_override(stress_cap: float):
            from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
            clusters = {
                "roska4_swing": ClusterBudget("roska4_swing", 0.050, 0.044),
                "roska4_stress": ClusterBudget("roska4_stress", stress_cap, None),
                "global_nkd": ClusterBudget("global_nkd", sw.nkd_cap, sw.nkd_cap),
            }
            return MultiClusterGuard(clusters=clusters, account=ACCOUNT)

        nkd_probe.make_guard = make_guard_override
        try:
            daily, st = nkd_probe.replay_book(r4, nkd_scaled, stress, prices, spec)
        finally:
            nkd_probe.make_guard = old_make_guard
        m = summarize(daily)
        row = {
            "sweep": sw.name,
            "nkd_qty": sw.nkd_qty,
            "nkd_cap": fmt_pct(sw.nkd_cap),
            "R4 taken/rej": f"{st['taken']['roska4_swing']}/{st['rejected']['roska4_swing']}",
            "Stress taken/rej": f"{st['taken']['roska4_stress']}/{st['rejected']['roska4_stress']}",
            "NKD taken/rej": f"{st['taken']['global_nkd']}/{st['rejected']['global_nkd']}",
            "net": fmt_money(m["net"]),
            "ret": fmt_pct(m["ret"]),
            "pf": fmt_float(m["pf"]),
            "sharpe": fmt_float(m["sharpe"]),
            "calmar": fmt_float(m["calmar"]),
            "maxdd": fmt_money(m["maxdd"]),
            "halts": st["halted"],
        }
        rows.append(row)
        raw.append({"sweep": sw.__dict__, "metrics": m, "state": st})
    return "\n".join([f"## {which}", "", table(rows, [
        "sweep", "nkd_qty", "nkd_cap", "R4 taken/rej", "Stress taken/rej",
        "NKD taken/rej", "net", "ret", "pf", "sharpe", "calmar", "maxdd", "halts",
    ]), ""]), raw


def main() -> int:
    parts = [
        "# Stress + NKD Size/Cap Sweep - 2026-08-22",
        "",
        "Scratch-only. Fixed book: Normal-R4 5.0% gross / 4.4% net, Stress-MNQ `mnq_only_g3_q7` qty 7 with 10% cap. Sweep only NKD/MNKD qty and cap.",
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
