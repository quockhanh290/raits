from __future__ import annotations

from pathlib import Path


OUT = Path("scratch/stress_instrument_autopsy_20260821_report.md")


def table(rows, cols):
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(lines)


def main() -> int:
    lines = [
        "# Stress Instrument Autopsy - 2026-08-21",
        "",
        "Scratch-only synthesis. No production code modified.",
        "",
        "Question: should Stress candidates be split by instrument instead of bundled as MNQ/MES?",
        "",
        "## Gap-Shock Instrument Evidence",
        "",
        table(
            [
                {
                    "window": "floor",
                    "candidate": "MNQ/MES strict",
                    "trades": "101",
                    "net": "+$3,208",
                    "pf": "1.58",
                    "calmar": "0.31",
                    "maxdd": "$1,295",
                    "3x slip": "+$2,804",
                    "bootstrap p5": "-$842",
                    "read": "higher dollars, weaker quality",
                },
                {
                    "window": "floor",
                    "candidate": "MNQ-only strict",
                    "trades": "46",
                    "net": "+$2,554",
                    "pf": "1.98",
                    "calmar": "0.48",
                    "maxdd": "$670",
                    "3x slip": "+$2,370",
                    "bootstrap p5": "+$369",
                    "read": "cleaner standalone shape",
                },
                {
                    "window": "floor by instrument inside MNQ/MES",
                    "candidate": "MNQ leg",
                    "trades": "46",
                    "net": "+$2,554",
                    "pf": "n/a",
                    "calmar": "n/a",
                    "maxdd": "n/a",
                    "3x slip": "n/a",
                    "bootstrap p5": "n/a",
                    "read": "80% of MNQ/MES net",
                },
                {
                    "window": "floor by instrument inside MNQ/MES",
                    "candidate": "MES leg",
                    "trades": "55",
                    "net": "+$654",
                    "pf": "n/a",
                    "calmar": "n/a",
                    "maxdd": "n/a",
                    "3x slip": "n/a",
                    "bootstrap p5": "n/a",
                    "read": "adds trades, little edge",
                },
                {
                    "window": "2025",
                    "candidate": "MNQ/MES strict",
                    "trades": "6",
                    "net": "+$1,160",
                    "pf": "50.91",
                    "calmar": "inf",
                    "maxdd": "$0",
                    "3x slip": "+$1,136",
                    "bootstrap p5": "+$496",
                    "read": "both legs good, tiny sample",
                },
                {
                    "window": "2025",
                    "candidate": "MNQ-only strict",
                    "trades": "3",
                    "net": "+$647",
                    "pf": "28.85",
                    "calmar": "28.02",
                    "maxdd": "$23",
                    "3x slip": "+$635",
                    "bootstrap p5": "+$226",
                    "read": "good, tiny sample",
                },
                {
                    "window": "2026",
                    "candidate": "MNQ/MES strict",
                    "trades": "8",
                    "net": "+$20",
                    "pf": "1.04",
                    "calmar": "0.06",
                    "maxdd": "$534",
                    "3x slip": "-$12",
                    "bootstrap p5": "-$1,053",
                    "read": "flat before slippage",
                },
                {
                    "window": "2026",
                    "candidate": "MNQ-only strict",
                    "trades": "4",
                    "net": "-$58",
                    "pf": "0.84",
                    "calmar": "-0.26",
                    "maxdd": "$359",
                    "3x slip": "-$74",
                    "bootstrap p5": "-$713",
                    "read": "does not confirm",
                },
                {
                    "window": "2026 by instrument inside MNQ/MES",
                    "candidate": "MES leg",
                    "trades": "4",
                    "net": "+$78",
                    "pf": "n/a",
                    "calmar": "n/a",
                    "maxdd": "n/a",
                    "3x slip": "n/a",
                    "bootstrap p5": "n/a",
                    "read": "MES offsets MNQ in 2026",
                },
                {
                    "window": "2026 by instrument inside MNQ/MES",
                    "candidate": "MNQ leg",
                    "trades": "4",
                    "net": "-$58",
                    "pf": "n/a",
                    "calmar": "n/a",
                    "maxdd": "n/a",
                    "3x slip": "n/a",
                    "bootstrap p5": "n/a",
                    "read": "MNQ fails recent sample",
                },
            ],
            ["window", "candidate", "trades", "net", "pf", "calmar", "maxdd", "3x slip", "bootstrap p5", "read"],
        ),
        "",
        "## Interpretation",
        "",
        "- Floor says MNQ is the real edge carrier: MNQ contributes about $2,554 of the $3,208 MNQ/MES total; MES contributes only about $654 while increasing trades and drawdown.",
        "- Quality metrics favor MNQ-only on floor: PF 1.98 vs 1.58, MaxDD $670 vs $1,295, bootstrap p5 positive vs negative.",
        "- 2025 does not distinguish much because both legs win and the sample is only three event days.",
        "- 2026 cuts against blindly choosing MNQ-only: MNQ loses while MES is slightly positive, leaving MNQ/MES roughly flat.",
        "- Therefore the instrument question is not settled by OOS; it is a research-design question.",
        "",
        "## Verdict",
        "",
        "- Yes, future Stress research should split instruments instead of bundling MNQ/MES by default.",
        "- For standalone sleeve development, carry at least two fixed variants: `MNQ-only` and `MNQ/MES`, and select by event WFO only.",
        "- Do not promote MES as an equal edge source. In floor it mostly adds noise and operational overlap.",
        "- Do not promote MNQ-only yet either, because 2026 does not confirm and OOS event count is too small.",
        "- If broker/netting or subaccount cost matters, MNQ-only is the cleaner operational candidate to test first.",
        "",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
