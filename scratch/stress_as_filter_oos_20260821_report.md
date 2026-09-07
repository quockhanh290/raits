# Stress As Filter Probe - 2026-08-21

Scratch-only. No production code modified.

Tests Stress detectors as risk-off skip filters for existing Normal corrected trades and the clean Calm open-location 10:00 candidate.

## vault2025

| source | filter | filter_days | base_trades | skipped_trades | skipped_pnl | base_net | kept_net | delta | base_pf | kept_pf | base_maxdd | kept_maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| calm_openloc_e1000 | late_break_1100_b3_days | 38 | 73 | 3 | $-113 | $5,237 | $5,351 | $113 | 4.64 | 5.22 | $603 | $603 |
| calm_openloc_e1000 | gapdown_full_breadth_1030_days | 4 | 73 | 0 | $0 | $5,237 | $5,237 | $0 | 4.64 | 4.64 | $603 | $603 |
| calm_openloc_e1000 | union_days | 39 | 73 | 3 | $-113 | $5,237 | $5,351 | $113 | 4.64 | 5.22 | $603 | $603 |
| normal_corrected | late_break_1100_b3_days | 38 | 144 | 23 | $-1,805 | $5,505 | $7,310 | $1,805 | 1.19 | 1.32 | $9,457 | $9,857 |
| normal_corrected | gapdown_full_breadth_1030_days | 4 | 144 | 1 | $1,066 | $5,505 | $4,439 | $-1,066 | 1.19 | 1.15 | $9,457 | $9,457 |
| normal_corrected | union_days | 39 | 144 | 23 | $-1,805 | $5,505 | $7,310 | $1,805 | 1.19 | 1.32 | $9,457 | $9,857 |

## vault2026

| source | filter | filter_days | base_trades | skipped_trades | skipped_pnl | base_net | kept_net | delta | base_pf | kept_pf | base_maxdd | kept_maxdd |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| calm_openloc_e1000 | late_break_1100_b3_days | 24 | 48 | 13 | $-1,124 | $1,485 | $2,609 | $1,124 | 1.44 | 2.68 | $1,300 | $420 |
| calm_openloc_e1000 | gapdown_full_breadth_1030_days | 4 | 48 | 5 | $-1,113 | $1,485 | $2,598 | $1,113 | 1.44 | 2.14 | $1,300 | $738 |
| calm_openloc_e1000 | union_days | 25 | 48 | 13 | $-1,124 | $1,485 | $2,609 | $1,124 | 1.44 | 2.68 | $1,300 | $420 |
| normal_corrected | late_break_1100_b3_days | 24 | 114 | 11 | $4,070 | $3,236 | $-834 | $-4,070 | 1.10 | 0.97 | $16,404 | $16,256 |
| normal_corrected | gapdown_full_breadth_1030_days | 4 | 114 | 0 | $0 | $3,236 | $3,236 | $0 | 1.10 | 1.10 | $16,404 | $16,404 |
| normal_corrected | union_days | 25 | 114 | 11 | $4,070 | $3,236 | $-834 | $-4,070 | 1.10 | 0.97 | $16,404 | $16,256 |
