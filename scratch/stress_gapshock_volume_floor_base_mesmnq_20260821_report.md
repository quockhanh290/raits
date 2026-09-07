# Stress Gap-Shock Volume Confirmation - 2026-08-21

Scratch-only. No production code modified.

Tests volume confirmation on the strict gap-shock sleeve only.
Volume baselines use prior-day-only rolling medians, so filters are causal.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_mnqmes_base | 101 | 57 | 51 | $3,208 | 1.58 | 0.31 | $1,295 | 0 | 0 | $3,006 | $2,804 | 0.92 | $-485 |
