# Stress Gap-Shock Exhaustion / D-1 Filters - 2026-08-21

Scratch-only. No production code modified.

Tests controlled filters on strict gap-shock: deep-gap, 10:30 extension, D-1 crash/weak-close, open location, and MNQ leadership.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| d1_not_crash_mnqmes | 100 | 56 | 50 | $3,390 | 1.63 | 0.33 | $1,295 | 0 | 0 | $3,190 | $2,990 | 0.94 | $-297 |
| in_prior_range_open_mnqmes | 25 | 15 | 15 | $3,255 | 7.15 | 1.21 | $337 | 0 | 0 | $3,205 | $3,155 | 1.00 | $1,505 |
| leadership_mnq_weakest_mnq | 19 | 19 | 19 | $1,515 | 2.07 | 0.38 | $504 | 0 | 0 | $1,477 | $1,439 | 0.91 | $-412 |
| d1_close_weak_not_extreme_mnqmes | 29 | 15 | 14 | $-294 | 0.84 | -0.03 | $1,170 | 0 | 0 | $-352 | $-410 | 0.43 | $-2,128 |
