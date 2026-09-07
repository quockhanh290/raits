from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_open_search_20260821 as base
from scratch.stress_mnq_overlap_insurance_20260821 import (
    CANDIDATES as PRIOR_CANDIDATES,
    CALM_FILES,
    CALM_VARIANT,
    NORMAL_FILES,
    dense_daily,
    fmt_money,
    insurance_rows,
    load_calm,
    load_normal,
    load_stress,
    overlaps,
    summarize_daily,
    table,
)


OUT = Path("scratch/stress_final_gate_20260821_report.md")


@dataclass(frozen=True)
class Scenario:
    candidate: str
    scale: int
    block_normal_mnq: bool


SCENARIOS = [
    Scenario("mnq_strict_10:30_b4_g2_rr15_x1555", 5, False),
    Scenario("mnq_strict_10:30_b4_g2_rr15_x1555", 5, True),
    Scenario("mnq_strict_10:30_b4_g3_rr15_x1555", 7, False),
    Scenario("mnq_strict_10:30_b4_g3_rr15_x1555", 7, True),
]


def make_rules() -> list[base.Rule]:
    base.SETUPS = ("10:30",)
    out = []
    for name, gap_min in [
        ("mnq_strict_10:30_b4_g2_rr15_x1555", 2),
        ("mnq_strict_10:30_b4_g3_rr15_x1555", 3),
    ]:
        out.append(base.Rule(
            name=name,
            family="cont_short",
            direction="SHORT",
            instruments=("MNQ",),
            setup_time="10:30",
            entry_start="10:35",
            entry_end="12:30",
            exit_time="15:55",
            rr=1.5,
            breadth_min=4,
            gapdown_min=gap_min,
            wide_min=0,
            avg_ret_max=None,
            avg_gap_max=-0.001,
        ))
    return out


def block_normal_overlap(stress: pd.DataFrame, normal: pd.DataFrame) -> pd.DataFrame:
    if stress.empty or normal.empty:
        return stress.copy()
    normal_mnq = normal[normal["instrument"] == "MNQ"]
    keep = []
    for _, s in stress.iterrows():
        hit = normal_mnq[
            (normal_mnq["entry_time"] < s["exit_time"])
            & (normal_mnq["exit_time"] > s["entry_time"])
        ]
        keep.append(hit.empty)
    return stress.loc[keep].copy()


def cluster_stability(stress: pd.DataFrame, scale: int) -> dict:
    if stress.empty:
        return {"clusters": 0, "total": 0.0, "best": 0.0, "without_best": 0.0, "final4": 0.0, "positive": 0, "pass": False}
    by = stress.groupby("event_cluster")["pnl"].sum().sort_index() * scale
    total = float(by.sum())
    best = float(by.max())
    final4 = float(by.tail(4).sum())
    return {
        "clusters": int(len(by)),
        "total": total,
        "best": best,
        "without_best": total - best,
        "final4": final4,
        "positive": int((by > 0).sum()),
        "pass": bool(total > 0 and total - best > 0 and best <= 0.5 * total and final4 >= 0),
    }


def scenario_metrics(which: str, stress_by_name: dict[str, pd.DataFrame], sessions, scenario: Scenario) -> dict:
    normal = load_normal(which)
    calm = load_calm(which)
    base_book = pd.concat([x for x in (normal, calm) if not x.empty], ignore_index=True) if (not normal.empty or not calm.empty) else pd.DataFrame()
    base_daily = dense_daily(base_book, sessions, 1.0)
    base_sum = summarize_daily(base_daily)

    raw_stress = stress_by_name[scenario.candidate].copy()
    stress = block_normal_overlap(raw_stress, normal) if scenario.block_normal_mnq else raw_stress
    stress_daily = dense_daily(stress, sessions, scenario.scale)
    combined_daily = base_daily + stress_daily
    stress_sum = summarize_daily(stress_daily)
    combined_sum = summarize_daily(combined_daily)
    normal_ov = overlaps(stress, normal)
    calm_ov = overlaps(stress, calm)
    stability = cluster_stability(stress, scenario.scale)
    return {
        "window": which,
        "candidate": scenario.candidate.replace("mnq_strict_10:30_", ""),
        "scale": f"{scenario.scale}x",
        "policy": "block_normal_mnq" if scenario.block_normal_mnq else "allow_overlap",
        "raw_trades": int(len(raw_stress)),
        "kept_trades": int(len(stress)),
        "blocked": int(len(raw_stress) - len(stress)),
        "stress_net": fmt_money(stress_sum["net"]),
        "stress_net_raw": stress_sum["net"],
        "stress_maxdd": fmt_money(stress_sum["maxdd"]),
        "combined_net": fmt_money(combined_sum["net"]),
        "combined_maxdd": fmt_money(combined_sum["maxdd"]),
        "base_maxdd": fmt_money(base_sum["maxdd"]),
        "maxdd_delta": fmt_money(combined_sum["maxdd"] - base_sum["maxdd"]),
        "maxdd_delta_raw": combined_sum["maxdd"] - base_sum["maxdd"],
        "normal_opp_days": normal_ov["opposite_days"],
        "calm_opp_days": calm_ov["opposite_days"],
        "clusters": stability["clusters"],
        "cluster_total": fmt_money(stability["total"]),
        "best_cluster": fmt_money(stability["best"]),
        "without_best": fmt_money(stability["without_best"]),
        "final4": fmt_money(stability["final4"]),
        "cluster_pass": stability["pass"],
        "bad20_stress": insurance_rows(base_daily, stress_daily)[2]["stress_pnl"],
    }


def verdict_for(floor: dict, oos25: dict) -> str:
    if floor["normal_opp_days"] != 0:
        return "fail_overlap"
    if not floor["cluster_pass"]:
        return "fail_cluster"
    if oos25["stress_net_raw"] <= 0:
        return "fail_2025"
    if oos25["maxdd_delta_raw"] > 0:
        return "fail_2025_maxdd"
    if floor["maxdd_delta_raw"] > 0:
        return "fail_floor_maxdd"
    return "pass_research_gate"


def main() -> int:
    rules = make_rules()
    parts = [
        "# Stress Final Gate - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Purpose: stop tuning and decide whether the MNQ-only Stress branch survives as an active hedge/diversifier candidate.",
        "",
        "Gate policy:",
        "",
        "- 2026 is sanity-only, not a rejection input.",
        "- Test only fixed candidates and fixed scales.",
        "- Test both allowing overlap and blocking Stress when Normal already holds MNQ.",
        "- Required to keep candidate: zero Normal same-symbol opposite overlap after policy, positive 2025, floor cluster stability, and no combined MaxDD worsening.",
        "",
    ]
    by_window = {}
    for which in ("floor", "vault2025", "vault2026"):
        stress_by_name, sessions = load_stress(which, rules)
        rows = [scenario_metrics(which, stress_by_name, sessions, s) for s in SCENARIOS]
        by_window[which] = rows
        parts += [
            f"## {which}",
            "",
            table(rows, [
                "candidate", "scale", "policy", "raw_trades", "kept_trades", "blocked",
                "stress_net", "stress_maxdd", "base_maxdd", "combined_net", "combined_maxdd",
                "maxdd_delta", "normal_opp_days", "calm_opp_days", "clusters", "best_cluster",
                "without_best", "final4", "cluster_pass", "bad20_stress",
            ]),
            "",
        ]

    decision_rows = []
    for scenario in SCENARIOS:
        key_candidate = scenario.candidate.replace("mnq_strict_10:30_", "")
        key_policy = "block_normal_mnq" if scenario.block_normal_mnq else "allow_overlap"
        floor = next(r for r in by_window["floor"] if r["candidate"] == key_candidate and r["policy"] == key_policy)
        oos25 = next(r for r in by_window["vault2025"] if r["candidate"] == key_candidate and r["policy"] == key_policy)
        s26 = next(r for r in by_window["vault2026"] if r["candidate"] == key_candidate and r["policy"] == key_policy)
        decision_rows.append({
            "candidate": key_candidate,
            "scale": f"{scenario.scale}x",
            "policy": key_policy,
            "floor_cluster_pass": floor["cluster_pass"],
            "floor_maxdd_delta": floor["maxdd_delta"],
            "2025_net": oos25["stress_net"],
            "2025_maxdd_delta": oos25["maxdd_delta"],
            "2026_sanity_net": s26["stress_net"],
            "2026_sanity_maxdd_delta": s26["maxdd_delta"],
            "decision": verdict_for(floor, oos25),
        })

    parts += [
        "## Gate Decision",
        "",
        table(decision_rows, [
            "candidate", "scale", "policy", "floor_cluster_pass", "floor_maxdd_delta",
            "2025_net", "2025_maxdd_delta", "2026_sanity_net", "2026_sanity_maxdd_delta", "decision",
        ]),
        "",
        "## Verdict",
        "",
        "- If both block-normal scenarios fail, reject the independent Stress sleeve for deploy/paper and keep it as research only.",
        "- If a block-normal scenario passes, keep only that exact fixed candidate/policy as a deploy-track research candidate.",
        "- Allow-overlap scenarios cannot be deployed because same-symbol MNQ netting risk remains unresolved.",
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
