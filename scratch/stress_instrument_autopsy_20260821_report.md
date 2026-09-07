# Stress Instrument Autopsy - 2026-08-21

Scratch-only synthesis. No production code modified.

Question: should Stress candidates be split by instrument instead of bundled as MNQ/MES?

## Gap-Shock Instrument Evidence

| window | candidate | trades | net | pf | calmar | maxdd | 3x slip | bootstrap p5 | read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| floor | MNQ/MES strict | 101 | +$3,208 | 1.58 | 0.31 | $1,295 | +$2,804 | -$842 | higher dollars, weaker quality |
| floor | MNQ-only strict | 46 | +$2,554 | 1.98 | 0.48 | $670 | +$2,370 | +$369 | cleaner standalone shape |
| floor by instrument inside MNQ/MES | MNQ leg | 46 | +$2,554 | n/a | n/a | n/a | n/a | n/a | 80% of MNQ/MES net |
| floor by instrument inside MNQ/MES | MES leg | 55 | +$654 | n/a | n/a | n/a | n/a | n/a | adds trades, little edge |
| 2025 | MNQ/MES strict | 6 | +$1,160 | 50.91 | inf | $0 | +$1,136 | +$496 | both legs good, tiny sample |
| 2025 | MNQ-only strict | 3 | +$647 | 28.85 | 28.02 | $23 | +$635 | +$226 | good, tiny sample |
| 2026 | MNQ/MES strict | 8 | +$20 | 1.04 | 0.06 | $534 | -$12 | -$1,053 | flat before slippage |
| 2026 | MNQ-only strict | 4 | -$58 | 0.84 | -0.26 | $359 | -$74 | -$713 | does not confirm |
| 2026 by instrument inside MNQ/MES | MES leg | 4 | +$78 | n/a | n/a | n/a | n/a | n/a | MES offsets MNQ in 2026 |
| 2026 by instrument inside MNQ/MES | MNQ leg | 4 | -$58 | n/a | n/a | n/a | n/a | n/a | MNQ fails recent sample |

## Interpretation

- Floor says MNQ is the real edge carrier: MNQ contributes about $2,554 of the $3,208 MNQ/MES total; MES contributes only about $654 while increasing trades and drawdown.
- Quality metrics favor MNQ-only on floor: PF 1.98 vs 1.58, MaxDD $670 vs $1,295, bootstrap p5 positive vs negative.
- 2025 does not distinguish much because both legs win and the sample is only three event days.
- 2026 cuts against blindly choosing MNQ-only: MNQ loses while MES is slightly positive, leaving MNQ/MES roughly flat.
- Therefore the instrument question is not settled by OOS; it is a research-design question.

## Verdict

- Yes, future Stress research should split instruments instead of bundling MNQ/MES by default.
- For standalone sleeve development, carry at least two fixed variants: `MNQ-only` and `MNQ/MES`, and select by event WFO only.
- Do not promote MES as an equal edge source. In floor it mostly adds noise and operational overlap.
- Do not promote MNQ-only yet either, because 2026 does not confirm and OOS event count is too small.
- If broker/netting or subaccount cost matters, MNQ-only is the cleaner operational candidate to test first.
