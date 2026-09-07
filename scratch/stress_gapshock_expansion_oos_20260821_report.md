# Stress Gap-Shock Controlled Expansion - 2026-08-21

Scratch-only. No production code modified.

Purpose: increase sample from the strict gap-shock clue by relaxing one condition at a time.
This is not a broad parameter sweep.

## vault2025

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| smallgap_gap3_below4_mnqmes | 8 | 4 | 4 | $1,527 | 66.71 | inf | $0 | 0 | 0 | $1,511 | $1,495 | 1.00 | $796 |
| strict_gap3_below4_mnqmes | 6 | 3 | 3 | $1,160 | 50.91 | inf | $0 | 0 | 0 | $1,148 | $1,136 | 1.00 | $99 |
| relax_gap_gap2_below4_mnqmes | 6 | 3 | 3 | $1,160 | 50.91 | inf | $0 | 0 | 0 | $1,148 | $1,136 | 1.00 | $99 |
| relax_breadth_gap3_below3_mnqmes | 10 | 5 | 5 | $781 | 1.90 | 0.93 | $845 | 0 | 0 | $761 | $741 | 0.72 | $-1,408 |
| strict_gap3_below4_mnq | 3 | 3 | 3 | $647 | 28.85 | 28.02 | $23 | 0 | 0 | $641 | $635 | 0.95 | $-70 |
| wide_gap2_below3_mnqmes | 16 | 8 | 7 | $-69 | 0.97 | -0.07 | $1,063 | 0 | 0 | $-101 | $-133 | 0.49 | $-2,417 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $0 | $0 | $0 | $0 | 0 | 2 | False |

## vault2026

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| strict_gap3_below4_mnqmes | 8 | 4 | 4 | $20 | 1.04 | 0.06 | $534 | 0 | 0 | $4 | $-12 | 0.61 | $-1,053 |
| smallgap_gap3_below4_mnqmes | 21 | 11 | 10 | $-10 | 0.99 | -0.02 | $845 | 0 | 0 | $-52 | $-94 | 0.52 | $-1,832 |
| strict_gap3_below4_mnq | 4 | 4 | 4 | $-58 | 0.84 | -0.26 | $359 | 0 | 0 | $-66 | $-74 | 0.43 | $-713 |
| relax_breadth_gap3_below3_mnqmes | 9 | 5 | 5 | $-253 | 0.69 | -0.75 | $534 | 0 | 0 | $-271 | $-289 | 0.40 | $-1,338 |
| relax_gap_gap2_below4_mnqmes | 17 | 9 | 9 | $-809 | 0.53 | -1.52 | $845 | 0 | 0 | $-843 | $-877 | 0.17 | $-2,337 |
| wide_gap2_below3_mnqmes | 25 | 14 | 13 | $-2,011 | 0.46 | -1.30 | $2,451 | 0 | 0 | $-2,061 | $-2,111 | 0.12 | $-4,786 |

WFO gate:

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $-1,386 | $0 | $-1,386 | $-1,083 | 0 | 5 | False |
