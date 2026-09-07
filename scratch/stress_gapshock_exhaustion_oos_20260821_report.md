# Stress Gap-Shock Exhaustion / D-1 Filters - 2026-08-21

Scratch-only. No production code modified.

Tests controlled filters on strict gap-shock: deep-gap, 10:30 extension, D-1 crash/weak-close, open location, and MNQ leadership.

## vault2025

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| base_mnqmes | 6 | 3 | 3 | $1,160 | 50.91 | inf | $0 | 0 | 0 | $1,148 | $1,136 | 1.00 | $496 |
| d1_not_crash_mnqmes | 6 | 3 | 3 | $1,160 | 50.91 | inf | $0 | 0 | 0 | $1,148 | $1,136 | 1.00 | $496 |
| not_deep_gap_mnqmes | 4 | 2 | 2 | $730 | 32.39 | inf | $0 | 0 | 0 | $722 | $714 | 1.00 | $66 |
| not_extended_1030_mnqmes | 2 | 1 | 1 | $697 | inf | inf | $0 | 0 | 0 | $693 | $689 | 1.00 | $697 |
| not_deep_gap_or_extended_mnqmes | 2 | 1 | 1 | $697 | inf | inf | $0 | 0 | 0 | $693 | $689 | 1.00 | $697 |
| base_mnq | 3 | 3 | 3 | $647 | 28.85 | 28.02 | $23 | 0 | 0 | $641 | $635 | 0.96 | $226 |
| d1_close_weak_not_extreme_mnqmes | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0 | 0 | $0 | $0 | 0.00 | $0 |
| in_prior_range_open_mnqmes | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0 | 0 | $0 | $0 | 0.00 | $0 |
| leadership_mnq_weakest_mnq | 1 | 1 | 1 | $-23 | 0.00 | -1.01 | $23 | 0 | 0 | $-25 | $-27 | 0.00 | $-23 |

## vault2026

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| d1_close_weak_not_extreme_mnqmes | 2 | 1 | 1 | $428 | inf | inf | $0 | 0 | 0 | $424 | $420 | 1.00 | $428 |
| leadership_mnq_weakest_mnq | 2 | 2 | 2 | $56 | 1.32 | 0.50 | $177 | 0 | 0 | $52 | $48 | 0.75 | $-353 |
| base_mnqmes | 8 | 4 | 4 | $20 | 1.04 | 0.06 | $534 | 0 | 0 | $4 | $-12 | 0.59 | $-1,053 |
| not_deep_gap_mnqmes | 8 | 4 | 4 | $20 | 1.04 | 0.06 | $534 | 0 | 0 | $4 | $-12 | 0.59 | $-1,053 |
| not_extended_1030_mnqmes | 8 | 4 | 4 | $20 | 1.04 | 0.06 | $534 | 0 | 0 | $4 | $-12 | 0.59 | $-1,053 |
| not_deep_gap_or_extended_mnqmes | 8 | 4 | 4 | $20 | 1.04 | 0.06 | $534 | 0 | 0 | $4 | $-12 | 0.59 | $-1,053 |
| d1_not_crash_mnqmes | 8 | 4 | 4 | $20 | 1.04 | 0.06 | $534 | 0 | 0 | $4 | $-12 | 0.59 | $-1,053 |
| base_mnq | 4 | 4 | 4 | $-58 | 0.84 | -0.26 | $359 | 0 | 0 | $-66 | $-74 | 0.40 | $-713 |
| in_prior_range_open_mnqmes | 2 | 1 | 1 | $-275 | 0.00 | -1.59 | $275 | 0 | 0 | $-279 | $-283 | 0.00 | $-275 |
