from __future__ import annotations

from pathlib import Path


OUT = Path("scratch/stress_candidate_autopsy_20260821_report.md")


def table(rows, cols):
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


def main() -> int:
    lines = [
        "# Stress Candidate Autopsy - 2026-08-21",
        "",
        "Scratch-only synthesis. No production code modified.",
        "",
        "Purpose: explain why the Stress candidates failed, separating timing/causality,",
        "OOS instability, WFO/concentration, slippage, and portfolio/broker interaction.",
        "",
        "Artifacts inspected:",
        "",
        "- `scratch/stress_mid_legacy_status_20260821_report.md`",
        "- `scratch/stress_intraday_static_candidate_audit_20260821_report.md`",
        "- `scratch/stress_intraday_1015_causal_floor_20260821_report.md`",
        "- `scratch/stress_intraday_1015_causal_oos_20260821_report.md`",
        "- `scratch/stress_new_hypothesis_floor_20260821_report.md`",
        "- `scratch/stress_new_hypothesis_oos_20260821_report.md`",
        "- `scratch/stress_new_hypothesis_pass2_floor_gap_20260821_report.md`",
        "- `scratch/stress_new_hypothesis_pass2_floor_late_20260821_report.md`",
        "- `scratch/stress_new_hypothesis_pass2_oos_20260821_report.md`",
        "- `scratch/stress_as_filter_floor_20260821_report.md`",
        "- `scratch/stress_as_filter_oos_20260821_report.md`",
        "",
        "## Candidate Failure Matrix",
        "",
    ]

    rows = [
        {
            "candidate": "STRESS_MID legacy",
            "best-looking evidence": "2025 lag1 +$3,998 PF 3.13",
            "primary failure": "not live/paper clean",
            "why": "floor collapses under lag1 to +$1,313 PF 1.14; 10:15 bar known at 10:20; 2026 lag1 -$779; live cron disabled by netting risk",
            "verdict": "disable",
        },
        {
            "candidate": "liquidation1020 as-measured",
            "best-looking evidence": "floor +$10,982 PF 1.27; 2025 +$6,952 PF 2.14; 2026 +$2,776 PF 1.57",
            "primary failure": "lookahead timing",
            "why": "uses 5m bar stamped 10:20 and enters 10:20; that bar is 10:20-10:24 and known at 10:25; signal_after_entry = all trades",
            "verdict": "discard headline",
        },
        {
            "candidate": "liquidation1020 causal 10:25",
            "best-looking evidence": "2025 +$4,088 PF 1.65; 2026 +$1,743 PF 1.31",
            "primary failure": "thin floor + overlap",
            "why": "floor only +$3,411 PF 1.08; 3x slippage leaves about +$959; swing opposite overlap 168/692, 113 conflict days",
            "verdict": "reject sleeve",
        },
        {
            "candidate": "causal1015_b4_rr2_x1555",
            "best-looking evidence": "2025 +$5,322 PF 1.80",
            "primary failure": "no floor edge / 2026 fail",
            "why": "floor +$1,229 PF 1.03; 2x slip +$42, 3x slip -$1,145; 2026 -$1,754 PF 0.68",
            "verdict": "reject",
        },
        {
            "candidate": "causal1015_b3_rr2_x1555",
            "best-looking evidence": "floor +$7,227 PF 1.11; 2025 +$4,955 PF 1.49",
            "primary failure": "weak WFO / 2026 fail",
            "why": "PF only 1.11 despite 1099 trades; WFO final4 -$1,064; 2026 -$1,188 PF 0.88; broad rule includes weak/chop days",
            "verdict": "reject",
        },
        {
            "candidate": "late_break_1100_b3_rr2_x1555",
            "best-looking evidence": "floor +$4,916 PF 1.20; 2025 +$2,182 PF 1.37; 3x floor slip still +$3,404",
            "primary failure": "regime decay / WFO fail",
            "why": "2023 -$746, 2024 -$1,540, 2026 -$654 PF 0.86; WFO floor total -$650 despite positive standalone row",
            "verdict": "research clue only",
        },
        {
            "candidate": "midday_expansion_1200_b3_rr2_x1555",
            "best-looking evidence": "floor +$3,448 PF 1.21, MaxDD $1,791",
            "primary failure": "OOS contradiction",
            "why": "2025 -$187 PF 0.96 and 2026 -$947 PF 0.76; floor edge does not transfer",
            "verdict": "reject",
        },
        {
            "candidate": "gapdown_break_1030_b3_rr2_x1555",
            "best-looking evidence": "floor +$1,776 PF 1.17; 2025 +$781 PF 1.90",
            "primary failure": "too sparse / subtype contamination",
            "why": "2026 -$253 PF 0.69; WFO floor -$51; plain gapdown loses -$2,116 while gapdown-full-breadth wins +$3,892",
            "verdict": "taxonomy clue only",
        },
        {
            "candidate": "gapdown_break_1130_b3_rr2_x1555",
            "best-looking evidence": "2026 +$1,513 PF 14.91",
            "primary failure": "sample illusion",
            "why": "2026 has only 3 trades; floor +$306 PF 1.04; 2025 -$1,477 PF 0.20; 3x floor slip negative",
            "verdict": "reject",
        },
        {
            "candidate": "vwap_reject_1200_b3_rr2_x1555",
            "best-looking evidence": "floor PF 1.40",
            "primary failure": "no sample",
            "why": "floor only 17 trades / +$161; no OOS trades in pass2",
            "verdict": "reject",
        },
        {
            "candidate": "late_day_break_1400",
            "best-looking evidence": "small positive 2026 rows",
            "primary failure": "negative floor",
            "why": "floor b3 -$236 PF 0.93, b4 -$933 PF 0.63; OOS sample too small to override floor",
            "verdict": "reject",
        },
        {
            "candidate": "Stress-as-filter for Calm",
            "best-looking evidence": "Calm 10:00 union filter floor +$3,889 delta; 2026 +$1,124 delta",
            "primary failure": "not a Stress sleeve",
            "why": "works by skipping Calm longs on stress-detector days; cannot be called Stress alpha; needs Calm protocol/WFO",
            "verdict": "promising filter clue",
        },
        {
            "candidate": "Stress-as-filter for Normal",
            "best-looking evidence": "2025 improves +$1,805",
            "primary failure": "not portable",
            "why": "floor skips +$10,575 of profitable Normal trades; 2026 skips +$4,070 and turns Normal kept net negative",
            "verdict": "reject global filter",
        },
    ]
    lines.append(table(rows, ["candidate", "best-looking evidence", "primary failure", "why", "verdict"]))

    lines += [
        "",
        "## Failure Themes",
        "",
        table(
            [
                {
                    "theme": "Timing mirage",
                    "affected": "liquidation1020 as-measured, STRESS_MID legacy interpretation",
                    "diagnostic": "bar used for signal is not known at claimed entry time",
                    "lesson": "all intraday Stress signals must declare known_time and enter strictly after it",
                },
                {
                    "theme": "Lag-0 regime lookahead",
                    "affected": "daily-label Stress sleeves, STRESS_MID legacy",
                    "diagnostic": "same-day HMM label uses D close; lag1 cuts edge materially",
                    "lesson": "Stress label can be used only as D-1 state unless intraday detector is independent of daily close",
                },
                {
                    "theme": "Single-episode dependence",
                    "affected": "daily-label WFO, 2025/2026 gap candidates",
                    "diagnostic": "one event/window creates most of the apparent net",
                    "lesson": "event-cluster concentration gate is mandatory",
                },
                {
                    "theme": "Short hedge is too late or too noisy",
                    "affected": "causal1015, late_break, midday_expansion",
                    "diagnostic": "floor PF hovers 1.03-1.21 and OOS alternates sign",
                    "lesson": "futures short sleeve is not robust enough as standalone alpha",
                },
                {
                    "theme": "Broker/netting blocker",
                    "affected": "STRESS_MID, liquidation1020, most short sleeves on MNQ/MES",
                    "diagnostic": "same-symbol opposite positions collide with swing/Calm and IBKR net position view",
                    "lesson": "do not spend broker plumbing on a sleeve that fails causal WFO",
                },
                {
                    "theme": "Filter specificity",
                    "affected": "Stress-as-filter",
                    "diagnostic": "helps Calm longs, hurts Normal",
                    "lesson": "Stress detector is context-specific risk-off, not an account-wide kill switch",
                },
            ],
            ["theme", "affected", "diagnostic", "lesson"],
        ),
        "",
        "## What Actually Survived",
        "",
        "- No traded Stress sleeve survived as paper/deploy candidate.",
        "- `late_break_1100_b3_rr2_x1555` survived only as a research clue: wait for post-11:00 continuation instead of shorting the first liquidation print.",
        "- `gapdown-full-breadth` survived only as event-quality taxonomy: gapdown alone is bad, gapdown plus full cross-index stress is better.",
        "- The only constructive branch is **Calm-specific Stress filter**: use stress detectors to skip Calm lower-third longs, not to short futures.",
        "",
        "## Recommended Next Gate",
        "",
        "Stop Stress sleeve work. Next valid work item is a Calm protocol:",
        "",
        "1. Base rule: `openloc_lower_third_long_e1000_x1555`.",
        "2. Candidate filters only: `late_break_1100_b3_days`, `gapdown_full_breadth_1030_days`, and their union.",
        "3. Train/select on floor folds only.",
        "4. Test 2025 and 2026 without tuning.",
        "5. Reject if filter helps only 2026 or worsens combined Normal+Calm account MaxDD.",
        "",
    ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
