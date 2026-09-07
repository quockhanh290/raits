# Stress Gap-Shock Controlled Expansion - 2026-08-21

Scratch-only. No production code modified.

Purpose: increase sample from the strict gap-shock clue by relaxing one condition at a time.
This is not a broad parameter sweep.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| smallgap_gap3_below4_mnqmes | 141 | 80 | 68 | $3,554 | 1.45 | 0.26 | $1,685 | 0 | 0 | $3,272 | $2,990 | 0.89 | $-1,321 |
| strict_gap3_below4_mnqmes | 101 | 57 | 51 | $3,208 | 1.58 | 0.31 | $1,295 | 0 | 0 | $3,006 | $2,804 | 0.91 | $-756 |
| strict_gap3_below4_mnq | 46 | 46 | 43 | $2,554 | 1.98 | 0.48 | $670 | 0 | 0 | $2,462 | $2,370 | 0.97 | $394 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $1,029 | $944 | $85 | $-133 | 23 | 66 | False |
