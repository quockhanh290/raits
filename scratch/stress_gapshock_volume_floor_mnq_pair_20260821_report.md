# Stress Gap-Shock Volume Confirmation - 2026-08-21

Scratch-only. No production code modified.

Tests volume confirmation on the strict gap-shock sleeve only.
Volume baselines use prior-day-only rolling medians, so filters are causal.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_mnq_base | 46 | 46 | 43 | $2,554 | 1.98 | 0.48 | $670 | 0 | 0 | $2,462 | $2,370 | 0.96 | $191 |
| gapshock_mnq_breakvol12 | 43 | 43 | 40 | $1,744 | 1.67 | 0.33 | $670 | 0 | 0 | $1,658 | $1,572 | 0.89 | $-522 |
