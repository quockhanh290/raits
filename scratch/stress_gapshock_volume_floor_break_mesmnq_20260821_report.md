# Stress Gap-Shock Volume Confirmation - 2026-08-21

Scratch-only. No production code modified.

Tests volume confirmation on the strict gap-shock sleeve only.
Volume baselines use prior-day-only rolling medians, so filters are causal.

## floor

| name | trades | days | clusters | net | pf | calmar | maxdd | sig_after | same_bar | slip2x | slip3x | boot_p_pos | boot_p5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gapshock_mnqmes_breakvol12 | 95 | 54 | 49 | $2,048 | 1.37 | 0.20 | $1,295 | 0 | 0 | $1,858 | $1,668 | 0.82 | $-1,482 |
