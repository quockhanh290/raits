# Stress Gap-Shock Controlled Expansion - 2026-08-21

Scratch-only. No production code modified.

Purpose: increase sample from the strict gap-shock clue by relaxing one condition at a time.
This is not a broad parameter sweep.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| relax_gap_gap2_below4_mnqmes | 134 | 76 | 66 | $3,910 | 1.53 | 0.30 | $1,646 | 0 | 0 | $3,642 | $3,374 | 0.91 | $-749 |
| wide_gap2_below3_mnqmes | 238 | 142 | 119 | $3,186 | 1.22 | 0.20 | $1,989 | 0 | 0 | $2,710 | $2,234 | 0.79 | $-3,003 |
| relax_breadth_gap3_below3_mnqmes | 142 | 85 | 77 | $2,040 | 1.23 | 0.13 | $2,017 | 0 | 0 | $1,756 | $1,472 | 0.78 | $-2,428 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $1,569 | $1,372 | $197 | $-1,098 | 29 | 122 | False |
