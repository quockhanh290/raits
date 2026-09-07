# Stress Switch On Normal-R4 Filtered Metrics - 2026-08-22

Scratch-only. No production code modified.

Base: Normal-R4 filtered trade artifact (`filtered`, MES/MNQ/MYM/M2K only, MNKD excluded).
Return % uses $50,000 account and raw window net, not annualized return.
PF/Sharpe/Calmar are computed from daily PnL series.
Winrate is trade-level for Stress and combined switched trade books.

## floor

| book | trades | net | return_pct | pf | sharpe | calmar | maxdd | winrate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Normal-R4 filtered only | 752 | $27,711 | 55.4% | 1.29 | 0.56 | 0.21 | $16,866 | 53.7% |
| Stress mnq_only_g3_q7 | 50 | $23,749 | 47.5% | 2.31 | 0.72 | 0.63 | $4,688 | 68.0% |
| Combined + mnq_only_g3_q7 | 802 | $51,910 | 103.8% | 1.49 | 0.90 | 0.55 | $11,854 | 54.1% |
| Stress r4_basket_g3_q1each | 202 | $6,088 | 12.2% | 1.73 | 0.53 | 0.49 | $1,560 | 60.4% |
| Combined + r4_basket_g3_q1each | 954 | $36,076 | 72.2% | 1.38 | 0.75 | 0.35 | $12,778 | 54.7% |
| Stress r4_basket_g3_q2each | 202 | $12,176 | 24.4% | 1.73 | 0.53 | 0.49 | $3,120 | 60.4% |
| Combined + r4_basket_g3_q2each | 954 | $42,164 | 84.3% | 1.41 | 0.81 | 0.42 | $12,647 | 54.7% |

## vault2025

| book | trades | net | return_pct | pf | sharpe | calmar | maxdd | winrate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Normal-R4 filtered only | 105 | $8,751 | 17.5% | 1.52 | 0.90 | 1.51 | $5,846 | 55.2% |
| Stress mnq_only_g3_q7 | 3 | $4,531 | 9.1% | 28.85 | 1.21 | 28.02 | $163 | 66.7% |
| Combined + mnq_only_g3_q7 | 108 | $14,633 | 29.3% | 1.93 | 1.43 | 2.83 | $5,209 | 55.6% |
| Stress r4_basket_g3_q1each | 15 | $1,614 | 3.2% | 4.71 | 1.13 | 3.73 | $435 | 80.0% |
| Combined + r4_basket_g3_q1each | 120 | $9,204 | 18.4% | 1.63 | 1.21 | 1.64 | $5,644 | 59.2% |
| Stress r4_basket_g3_q2each | 15 | $3,228 | 6.5% | 4.71 | 1.13 | 3.73 | $870 | 80.0% |
| Combined + r4_basket_g3_q2each | 120 | $10,818 | 21.6% | 1.72 | 1.36 | 1.79 | $6,079 | 59.2% |

## vault2026

| book | trades | net | return_pct | pf | sharpe | calmar | maxdd | winrate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Normal-R4 filtered only | 81 | $2,534 | 5.1% | 1.14 | 0.31 | 0.31 | $12,890 | 54.3% |
| Stress mnq_only_g3_q7 | 4 | $-406 | -0.8% | 0.84 | -0.19 | -0.26 | $2,516 | 50.0% |
| Combined + mnq_only_g3_q7 | 85 | $4,638 | 9.3% | 1.25 | 0.59 | 0.69 | $10,691 | 54.1% |
| Stress r4_basket_g3_q1each | 16 | $121 | 0.2% | 1.25 | 0.20 | 0.39 | $488 | 56.2% |
| Combined + r4_basket_g3_q1each | 97 | $6,911 | 13.8% | 1.48 | 0.95 | 1.30 | $8,418 | 54.6% |
| Stress r4_basket_g3_q2each | 16 | $242 | 0.5% | 1.25 | 0.20 | 0.39 | $975 | 56.2% |
| Combined + r4_basket_g3_q2each | 97 | $7,031 | 14.1% | 1.47 | 0.95 | 1.35 | $8,297 | 54.6% |
