# Stress Switch Policy Probe - 2026-08-22

Scratch-only. No production code modified.

Policy: if Stress wants to SHORT MNQ while Normal or Calm MNQ is open, close that existing MNQ trade at the Stress entry timestamp, then allow Stress.

This approximates a live-safe sleeve handoff. It does not model order-book liquidity or partial fills.

## floor

| candidate | scale | stress_trades | switched_normal | normal_pnl_delta | switched_calm | calm_pnl_delta | switched_base_net | stress_net | combined_net | base_maxdd | switched_base_maxdd | combined_maxdd | combined_maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | 68 | 29 | $-574 | 6 | $438 | $40,293 | $20,232 | $60,525 | $16,230 | $15,793 | $11,149 | $-5,081 | $0 |
| b4_g3_rr15_x1555 | 7x | 50 | 23 | $366 | 5 | $470 | $41,265 | $23,749 | $65,014 | $16,230 | $15,474 | $12,299 | $-3,931 | $0 |

## vault2025

| candidate | scale | stress_trades | switched_normal | normal_pnl_delta | switched_calm | calm_pnl_delta | switched_base_net | stress_net | combined_net | base_maxdd | switched_base_maxdd | combined_maxdd | combined_maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | 3 | 2 | $1,285 | 0 | $0 | $12,027 | $3,236 | $15,263 | $9,457 | $8,413 | $7,870 | $-1,586 | $0 |
| b4_g3_rr15_x1555 | 7x | 3 | 2 | $1,285 | 0 | $0 | $12,027 | $4,531 | $16,558 | $9,457 | $8,413 | $7,870 | $-1,586 | $0 |

## vault2026

| candidate | scale | stress_trades | switched_normal | normal_pnl_delta | switched_calm | calm_pnl_delta | switched_base_net | stress_net | combined_net | base_maxdd | switched_base_maxdd | combined_maxdd | combined_maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| b4_g2_rr15_x1555 | 5x | 8 | 4 | $492 | 3 | $-500 | $4,713 | $-2,807 | $1,906 | $16,579 | $14,566 | $14,856 | $-1,722 | $-1,797 |
| b4_g3_rr15_x1555 | 7x | 4 | 3 | $2,117 | 1 | $-104 | $6,734 | $-406 | $6,328 | $16,579 | $14,566 | $14,972 | $-1,606 | $-2,516 |

## Verdict

- If switch policy keeps 2025 positive and preserves combined MaxDD improvement, it may be a viable alternative to blocking Stress.
- If the cost of early-closing Normal consumes the Stress edge, the final rejection remains.