# Stress As Filter Probe - 2026-08-21

Scratch-only. No production code modified.

Tests Stress detectors as risk-off skip filters for existing Normal corrected trades and the clean Calm open-location 10:00 candidate.

## floor

| source | filter | filter_days | base_trades | skipped_trades | skipped_pnl | base_net | kept_net | delta | base_pf | kept_pf | base_maxdd | kept_maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| calm_openloc_e1000 | late_break_1100_b3_days | 244 | 666 | 42 | $-3,288 | $9,049 | $12,337 | $3,288 | 1.41 | 1.67 | $1,706 | $1,304 |
| calm_openloc_e1000 | gapdown_full_breadth_1030_days | 59 | 666 | 20 | $-1,651 | $9,049 | $10,700 | $1,651 | 1.41 | 1.53 | $1,706 | $1,418 |
| calm_openloc_e1000 | union_days | 266 | 666 | 53 | $-3,889 | $9,049 | $12,938 | $3,889 | 1.41 | 1.74 | $1,706 | $954 |
| normal_corrected | late_break_1100_b3_days | 244 | 1067 | 196 | $7,279 | $31,380 | $24,101 | $-7,279 | 1.21 | 1.20 | $16,593 | $19,378 |
| normal_corrected | gapdown_full_breadth_1030_days | 59 | 1067 | 55 | $6,836 | $31,380 | $24,544 | $-6,836 | 1.21 | 1.17 | $16,593 | $17,191 |
| normal_corrected | union_days | 266 | 1067 | 213 | $10,575 | $31,380 | $20,804 | $-10,575 | 1.21 | 1.17 | $16,593 | $19,618 |
