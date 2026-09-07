# Stress Gap-Shock Volume Confirmation - 2026-08-21

Scratch-only. No production code modified.

Tests volume confirmation on the strict gap-shock sleeve only.
Volume baselines use prior-day-only rolling medians, so filters are causal.

## vault2025

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_mnqmes_base | 6 | 3 | 3 | $1,160 | 50.91 | inf | $0 | 0 | 0 | $1,148 | $1,136 | 1.00 | $496 |
| gapshock_mnqmes_breakvol12 | 5 | 3 | 3 | $1,104 | 48.48 | 47.78 | $23 | 0 | 0 | $1,094 | $1,084 | 0.97 | $384 |
| gapshock_mnq_base | 3 | 3 | 3 | $647 | 28.85 | 28.02 | $23 | 0 | 0 | $641 | $635 | 0.97 | $226 |
| gapshock_mnq_breakvol12 | 3 | 3 | 3 | $647 | 28.85 | 28.02 | $23 | 0 | 0 | $641 | $635 | 0.97 | $226 |
| gapshock_mnqmes_cumvol12 | 2 | 1 | 1 | $430 | inf | inf | $0 | 0 | 0 | $426 | $422 | 1.00 | $430 |
| gapshock_mnqmes_bothvol12 | 2 | 1 | 1 | $430 | inf | inf | $0 | 0 | 0 | $426 | $422 | 1.00 | $430 |
| gapshock_mnq_cumvol12 | 1 | 1 | 1 | $273 | inf | inf | $0 | 0 | 0 | $271 | $269 | 1.00 | $273 |
| gapshock_mnq_bothvol12 | 1 | 1 | 1 | $273 | inf | inf | $0 | 0 | 0 | $271 | $269 | 1.00 | $273 |

## vault2026

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_mnqmes_base | 8 | 4 | 4 | $20 | 1.04 | 0.06 | $534 | 0 | 0 | $4 | $-12 | 0.62 | $-699 |
| gapshock_mnqmes_cumvol12 | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0 | 0 | $0 | $0 | 0.00 | $0 |
| gapshock_mnq_cumvol12 | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0 | 0 | $0 | $0 | 0.00 | $0 |
| gapshock_mnqmes_bothvol12 | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0 | 0 | $0 | $0 | 0.00 | $0 |
| gapshock_mnq_bothvol12 | 0 | 0 | 0 | $0 | inf | 0.00 | $0 | 0 | 0 | $0 | $0 | 0.00 | $0 |
| gapshock_mnq_base | 4 | 4 | 4 | $-58 | 0.84 | -0.26 | $359 | 0 | 0 | $-66 | $-74 | 0.42 | $-479 |
| gapshock_mnqmes_breakvol12 | 6 | 4 | 4 | $-271 | 0.49 | -0.80 | $534 | 0 | 0 | $-283 | $-295 | 0.27 | $-757 |
| gapshock_mnq_breakvol12 | 3 | 3 | 3 | $-291 | 0.19 | -1.28 | $359 | 0 | 0 | $-297 | $-303 | 0.03 | $-542 |
