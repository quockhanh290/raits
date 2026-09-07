# Stress Gap-Shock Volume Confirmation - 2026-08-21

Scratch-only. No production code modified.

Tests volume confirmation on the strict gap-shock sleeve only.
Volume baselines use prior-day-only rolling medians, so filters are causal.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_mnqmes_cumvol12 | 42 | 24 | 23 | $-458 | 0.85 | -0.04 | $1,469 | 0 | 0 | $-542 | $-626 | 0.38 | $-3,256 |
