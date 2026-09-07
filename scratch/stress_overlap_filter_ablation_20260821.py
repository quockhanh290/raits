from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_open_search_20260821 as base
from scratch.stress_mnq_overlap_insurance_20260821 import (
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


OUT = Path("scratch/stress_overlap_filter_ablation_20260821_report.md")


@dataclass(frozen=True)
class Candidate:
    name: str
    scale: int
    gap_min: int


CANDIDATES = [
    Candidate("mnq_strict_10:30_b4_g2_rr15_x1555", 5, 2),
    Candidate("mnq_strict_10:30_b4_g3_rr15_x1555", 7, 3),
]

POLICIES = [
    "allow_all",
    "drop_normal_mnq",
    "drop_calm_mnq",
    "drop_any_mnq",
    "keep_normal_mnq_only",
    "keep_no_mnq_overlap_only",
]


def make_rules() -> list[base.Rule]:
    base.SETUPS = ("10:30",)
    return [
        base.Rule(
            name=c.name,
            family="cont_short",
            direction="SHORT",
            instruments=("MNQ",),
            setup_time="10:30",
            entry_start="10:35",
            entry_end="12:30",
            exit_time="15:55",
            rr=1.5,
            breadth_min=4,
            gapdown_min=c.gap_min,
            wide_min=0,
            avg_ret_max=None,
            avg_gap_max=-0.001,
        )
        for c in CANDIDATES
    ]


def has_overlap(row: pd.Series, other: pd.DataFrame) -> bool:
    if other.empty:
        return False
    same = other[other["instrument"] == "MNQ"]
    if same.empty:
        return False
    hit = same[(same["entry_time"] < row["exit_time"]) & (same["exit_time"] > row["entry_time"])]
    return not hit.empty


def apply_policy(stress: pd.DataFrame, normal: pd.DataFrame, calm: pd.DataFrame, policy: str) -> pd.DataFrame:
    if stress.empty or policy == "allow_all":
        return stress.copy()
    flags = []
    for _, row in stress.iterrows():
        n = has_overlap(row, normal)
        c = has_overlap(row, calm)
        if policy == "drop_normal_mnq":
            keep = not n
        elif policy == "drop_calm_mnq":
            keep = not c
        elif policy == "drop_any_mnq":
            keep = not (n or c)
        elif policy == "keep_normal_mnq_only":
            keep = n
        elif policy == "keep_no_mnq_overlap_only":
            keep = not (n or c)
        else:
            raise ValueError(policy)
        flags.append(keep)
    return stress.loc[flags].copy()


def maxdd_delta(base_daily: pd.Series, stress_daily: pd.Series) -> float:
    b = summarize_daily(base_daily)
    c = summarize_daily(base_daily + stress_daily)
    return c["maxdd"] - b["maxdd"]


def run_window(which: str, rules: list[base.Rule]) -> tuple[list[dict], list[dict]]:
    stress_by_name, sessions = load_stress(which, rules)
    normal = load_normal(which)
    calm = load_calm(which)
    base_book = pd.concat([x for x in (normal, calm) if not x.empty], ignore_index=True) if (not normal.empty or not calm.empty) else pd.DataFrame()
    base_daily = dense_daily(base_book, sessions, 1.0)
    rows = []
    insurance = []
    for cand in CANDIDATES:
        raw = stress_by_name[cand.name]
        for policy in POLICIES:
            df = apply_policy(raw, normal, calm, policy)
            sd = dense_daily(df, sessions, cand.scale)
            ss = summarize_daily(sd)
            ovn = overlaps(df, normal)
            ovc = overlaps(df, calm)
            bad20 = insurance_rows(base_daily, sd)[2]
            rows.append({
                "window": which,
                "candidate": cand.name.replace("mnq_strict_10:30_", ""),
                "scale": f"{cand.scale}x",
                "policy": policy,
                "raw": int(len(raw)),
                "kept": int(len(df)),
                "blocked": int(len(raw) - len(df)),
                "stress_net": fmt_money(ss["net"]),
                "stress_net_raw": ss["net"],
                "stress_maxdd": fmt_money(ss["maxdd"]),
                "maxdd_delta": fmt_money(maxdd_delta(base_daily, sd)),
                "maxdd_delta_raw": maxdd_delta(base_daily, sd),
                "normal_opp_days": ovn["opposite_days"],
                "calm_opp_days": ovc["opposite_days"],
                "bad20_stress": bad20["stress_pnl"],
            })
            insurance.append({
                "window": which,
                "candidate": cand.name.replace("mnq_strict_10:30_", ""),
                "policy": policy,
                **bad20,
            })
    return rows, insurance


def main() -> int:
    rules = make_rules()
    all_rows = []
    all_ins = []
    for which in ("floor", "vault2025", "vault2026"):
        rows, ins = run_window(which, rules)
        all_rows.extend(rows)
        all_ins.extend(ins)

    parts = [
        "# Stress Overlap Filter Ablation - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Purpose: measure whether removing specific overlap classes makes the MNQ-only Stress candidates stronger.",
        "",
        "Policies:",
        "",
        "- `allow_all`: no overlap filter.",
        "- `drop_normal_mnq`: remove Stress trades overlapping any Normal MNQ position.",
        "- `drop_calm_mnq`: remove Stress trades overlapping any Calm MNQ position.",
        "- `drop_any_mnq`: remove Stress trades overlapping Normal or Calm MNQ.",
        "- `keep_normal_mnq_only`: keep only trades that overlap Normal MNQ, to test whether edge lives in the conflict.",
        "- `keep_no_mnq_overlap_only`: same as `drop_any_mnq`, kept for readability.",
        "",
    ]
    for which in ("floor", "vault2025", "vault2026"):
        parts += [
            f"## {which}",
            "",
            table(
                [
                    {
                        k: (fmt_money(v) if k.endswith("_raw") and False else v)
                        for k, v in r.items()
                        if k not in {"stress_net_raw", "maxdd_delta_raw"}
                    }
                    for r in all_rows
                    if r["window"] == which
                ],
                ["candidate", "scale", "policy", "raw", "kept", "blocked", "stress_net", "stress_maxdd", "maxdd_delta", "normal_opp_days", "calm_opp_days", "bad20_stress"],
            ),
            "",
        ]
    # Compact decision view for ex-2026 gate: floor + 2025 only.
    decision = []
    for cand in [c.name.replace("mnq_strict_10:30_", "") for c in CANDIDATES]:
        for policy in POLICIES:
            f = next(r for r in all_rows if r["window"] == "floor" and r["candidate"] == cand and r["policy"] == policy)
            y = next(r for r in all_rows if r["window"] == "vault2025" and r["candidate"] == cand and r["policy"] == policy)
            decision.append({
                "candidate": cand,
                "policy": policy,
                "floor_net": f["stress_net"],
                "floor_maxdd_delta": f["maxdd_delta"],
                "floor_normal_opp": f["normal_opp_days"],
                "floor_calm_opp": f["calm_opp_days"],
                "2025_net": y["stress_net"],
                "2025_maxdd_delta": y["maxdd_delta"],
                "read": (
                    "candidate_stronger"
                    if f["stress_net_raw"] > 0 and y["stress_net_raw"] > 0 and f["maxdd_delta_raw"] <= 0 and y["maxdd_delta_raw"] <= 0 and f["normal_opp_days"] == 0
                    else "not_enough"
                ),
            })
    parts += [
        "## Decision View",
        "",
        table(decision, ["candidate", "policy", "floor_net", "floor_maxdd_delta", "floor_normal_opp", "floor_calm_opp", "2025_net", "2025_maxdd_delta", "read"]),
        "",
        "## Verdict",
        "",
        "- The useful test is whether an overlap removal keeps floor and 2025 positive while removing Normal MNQ conflict.",
        "- If only `allow_all` or `keep_normal_mnq_only` works, the edge is tied to the conflict and should not be deployed.",
        "- If `drop_calm_mnq` improves results, Calm overlap can be dropped cheaply because Calm conflicts are operationally smaller.",
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
