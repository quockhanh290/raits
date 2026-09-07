# Stress Switch On Normal-R4 Filtered Probe - 2026-08-22

Scratch-only. No production code modified.

Base Normal: `normal_promotion_trades_*` bucket `filtered`, R4 only (MES/MNQ/MYM/M2K), MNKD excluded.

Note: this uses the regenerated trade artifact directly. It is not a full production cap/breaker replay.

Switch policy: close existing same-symbol Normal-R4 position at Stress entry timestamp, then allow Stress on that symbol.

## floor

| scenario | legs | days | margin_est | switched_normal | switch_delta | base_net | stress_net | combined_net | base_maxdd | switched_base_maxdd | combined_maxdd | maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 50 | 50 | $15,400 | 20 | $450 | $27,711 | $23,749 | $51,910 | $16,866 | $16,562 | $11,854 | $-5,012 | $0 |
| r4_basket_g3_q1each | 202 | 61 | $5,300 | 64 | $2,276 | $27,711 | $6,088 | $36,076 | $16,866 | $16,069 | $12,778 | $-4,088 | $0 |
| r4_basket_g3_q2each | 202 | 61 | $10,600 | 64 | $2,276 | $27,711 | $12,176 | $42,164 | $16,866 | $16,069 | $12,647 | $-4,219 | $0 |

## vault2025

| scenario | legs | days | margin_est | switched_normal | switch_delta | base_net | stress_net | combined_net | base_maxdd | switched_base_maxdd | combined_maxdd | maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 3 | 3 | $15,400 | 2 | $1,351 | $8,751 | $4,531 | $14,633 | $5,846 | $5,209 | $5,209 | $-636 | $0 |
| r4_basket_g3_q1each | 15 | 6 | $5,300 | 7 | $-1,161 | $8,751 | $1,614 | $9,204 | $5,846 | $5,209 | $5,644 | $-201 | $0 |
| r4_basket_g3_q2each | 15 | 6 | $10,600 | 7 | $-1,161 | $8,751 | $3,228 | $10,818 | $5,846 | $5,209 | $6,079 | $234 | $0 |

## vault2026

| scenario | legs | days | margin_est | switched_normal | switch_delta | base_net | stress_net | combined_net | base_maxdd | switched_base_maxdd | combined_maxdd | maxdd_delta | bad20_stress |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mnq_only_g3_q7 | 4 | 4 | $15,400 | 3 | $2,510 | $2,534 | $-406 | $4,638 | $12,890 | $10,380 | $10,691 | $-2,200 | $0 |
| r4_basket_g3_q1each | 16 | 4 | $5,300 | 11 | $4,256 | $2,534 | $121 | $6,911 | $12,890 | $8,634 | $8,418 | $-4,473 | $0 |
| r4_basket_g3_q2each | 16 | 4 | $10,600 | 11 | $4,256 | $2,534 | $242 | $7,031 | $12,890 | $8,634 | $8,297 | $-4,593 | $0 |
