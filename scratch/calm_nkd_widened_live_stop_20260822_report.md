# Calm-NKD Widened Live-Stop Excavation - 2026-08-22

Scratch-only. Production code was not modified.

Hypothesis: maybe the tight Calm-NKD stop failed because it was too narrow, while the 2x daily ATR stop was too wide. This tests the middle with live-stop semantics: stop armed immediately after entry and checked on 1-minute bars.

Rows use baseline 2 ticks/side cost. Slippage columns add extra ticks only to stop exits.

## floor

| kind | value | ema | trades | net | PF | Calmar | MaxDD | stop rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| daily_atr | 1.0 | 20 | 261 | $4,363 | 1.19 | 0.28 | $2,213 | 34.5% |
| daily_atr | 1.0 | 15 | 263 | $1,902 | 1.08 | 0.08 | $3,327 | 35.4% |

## vault2025

| kind | value | ema | trades | net | PF | Calmar | MaxDD | stop rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| daily_atr | 1.0 | 20 | 36 | $544 | 1.10 | 0.31 | $1,931 | 33.3% |
| daily_atr | 1.0 | 15 | 36 | $-252 | 0.96 | -0.14 | $1,931 | 36.1% |

## vault2026

| kind | value | ema | trades | net | PF | Calmar | MaxDD | stop rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| daily_atr | 1.0 | 15 | 21 | $2,953 | 1.49 | 2.58 | $2,125 | 33.3% |
| daily_atr | 1.0 | 20 | 23 | $-1,111 | 0.87 | -0.60 | $3,450 | 43.5% |

## Cross-Window Survivors

| kind | value | ema | floor net | floor PF | floor Calmar | 2025 net | 2025 PF | 2025 Calmar |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| daily_atr | 1.0 | 20 | $4,363 | 1.19 | 0.28 | $544 | 1.10 | 0.31 |

## Verdict

**REJECT.** The only row positive on both floor and 2025 is `daily_atr 1.0 / ema20`, and it is too
thin to carry forward:

- floor: +$4,363, PF 1.19, Calmar 0.28, MaxDD $2,213
- 2025: +$544, PF 1.10, Calmar 0.31, MaxDD $1,931
- 2026 sanity: -$1,111, PF 0.87, Calmar -0.60
- floor top 5 winners = 87% of net
- 2025 top 5 winners = 6.77x total net

This does not meet the bar for a standalone sleeve or portfolio integration. Calm-NKD remains
rejected and Track 1 stays the candidate.

## Broad Floor Screen Before Focused OOS

The full broad run was interrupted by runtime before writing JSON, but it printed the floor screen
below. Every printed widened-stop row before `daily_atr 1.0` was negative, so the focused rerun
measured only the two barely positive `daily_atr 1.0` rows across all windows.

| stop | ema | floor net | PF | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| width 1.5x | 5 | -$4,507 | 0.79 | -0.12 | $5,562 |
| width 1.5x | 10 | -$5,411 | 0.74 | -0.13 | $6,022 |
| width 1.5x | 15 | -$5,277 | 0.75 | -0.13 | $5,902 |
| width 1.5x | 20 | -$5,038 | 0.76 | -0.13 | $5,556 |
| width 2.0x | 5 | -$5,784 | 0.75 | -0.13 | $6,598 |
| width 2.0x | 10 | -$7,694 | 0.68 | -0.14 | $7,930 |
| width 2.0x | 15 | -$8,229 | 0.65 | -0.14 | $8,403 |
| width 2.0x | 20 | -$6,959 | 0.71 | -0.14 | $7,107 |
| width 3.0x | 5 | -$3,481 | 0.86 | -0.09 | $5,445 |
| width 3.0x | 10 | -$5,511 | 0.79 | -0.11 | $6,971 |
| width 3.0x | 15 | -$6,117 | 0.77 | -0.14 | $6,245 |
| width 3.0x | 20 | -$4,289 | 0.84 | -0.11 | $5,494 |
| width 4.0x | 5 | -$5,610 | 0.79 | -0.12 | $6,506 |
| width 4.0x | 10 | -$5,625 | 0.80 | -0.13 | $6,226 |
| width 4.0x | 15 | -$6,463 | 0.76 | -0.14 | $6,730 |
| width 4.0x | 20 | -$4,770 | 0.83 | -0.13 | $5,253 |
| width 6.0x | 5 | -$11,023 | 0.64 | -0.13 | $11,854 |
| width 6.0x | 10 | -$9,291 | 0.70 | -0.14 | $9,769 |
| width 6.0x | 15 | -$9,882 | 0.68 | -0.14 | $10,297 |
| width 6.0x | 20 | -$7,749 | 0.75 | -0.13 | $8,433 |
| width 8.0x | 5 | -$8,088 | 0.73 | -0.12 | $9,452 |
| width 8.0x | 10 | -$4,959 | 0.83 | -0.12 | $5,864 |
| width 8.0x | 15 | -$3,965 | 0.87 | -0.09 | $6,242 |
| width 8.0x | 20 | -$3,237 | 0.89 | -0.09 | $5,314 |
| daily ATR 0.25x | 5 | -$2,847 | 0.89 | -0.09 | $4,333 |
| daily ATR 0.25x | 10 | -$4,218 | 0.83 | -0.09 | $6,653 |
| daily ATR 0.25x | 15 | -$5,900 | 0.77 | -0.13 | $6,720 |
| daily ATR 0.25x | 20 | -$4,990 | 0.81 | -0.13 | $5,522 |
| daily ATR 0.35x | 5 | -$6,860 | 0.76 | -0.13 | $7,588 |
| daily ATR 0.35x | 10 | -$6,950 | 0.75 | -0.12 | $8,078 |
| daily ATR 0.35x | 15 | -$7,821 | 0.73 | -0.14 | $7,965 |
| daily ATR 0.50x | 5 | -$8,296 | 0.72 | -0.13 | $8,855 |
| daily ATR 0.50x | 10 | -$7,960 | 0.74 | -0.11 | $10,168 |
| daily ATR 0.50x | 15 | -$8,536 | 0.72 | -0.12 | $10,083 |
| daily ATR 0.50x | 20 | -$5,598 | 0.81 | -0.11 | $7,395 |
| daily ATR 0.75x | 5 | -$4,678 | 0.83 | -0.11 | $6,106 |
| daily ATR 0.75x | 10 | -$3,269 | 0.88 | -0.08 | $6,111 |
| daily ATR 0.75x | 15 | -$2,799 | 0.90 | -0.10 | $4,110 |
| daily ATR 0.75x | 20 | -$579 | 0.98 | -0.02 | $4,573 |
| daily ATR 1.00x | 5 | -$4,593 | 0.84 | -0.11 | $6,058 |
| daily ATR 1.00x | 10 | -$899 | 0.97 | -0.03 | $4,035 |
