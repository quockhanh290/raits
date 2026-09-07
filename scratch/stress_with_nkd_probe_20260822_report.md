# Stress With NKD Probe - 2026-08-22

Scratch-only. Candidate: `mnq_only_g3_q7` with split caps: Normal-R4 5.0% gross / 4.4% net, Stress 10.0% gross, NKD 6.0% gross / 6.0% net.

Books measured: R4 only, R4+Stress, R4+NKD, R4+Stress+NKD. Stress switch only affects same-symbol R4 positions; NKD is a separate cluster.

## floor

Stress legs: 50. NKD/MNKD trades in artifact: 228.

| book | trades_attempted | R4 taken/rej | Stress taken/rej | NKD taken/rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | winrate | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R4 only | 752 | 546/206 | 0/0 | 0/0 | 0 | 0 | $29,046 | 58.1% | 1.49 | 2.25 | 0.68 | $6,209 | 51.9% | 0 |
| R4 + Stress | 802 | 551/192 | 49/1 | 0/0 | 11 | 7 | $52,139 | 104.3% | 1.75 | 2.97 | 1.15 | $6,646 | 55.1% | 2 |
| R4 + NKD | 980 | 546/206 | 0/0 | 228/0 | 0 | 0 | $32,944 | 65.9% | 1.40 | 1.84 | 0.79 | $6,078 | 50.3% | 0 |
| R4 + Stress + NKD | 1030 | 551/192 | 49/1 | 228/0 | 11 | 7 | $56,037 | 112.1% | 1.61 | 2.45 | 1.67 | $4,893 | 52.7% | 2 |

## vault2025

Stress legs: 3. NKD/MNKD trades in artifact: 31.

| book | trades_attempted | R4 taken/rej | Stress taken/rej | NKD taken/rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | winrate | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R4 only | 105 | 55/50 | 0/0 | 0/0 | 0 | 0 | $5,395 | 10.8% | 1.58 | 1.94 | 1.56 | $3,768 | 50.0% | 0 |
| R4 + Stress | 108 | 55/50 | 3/0 | 0/0 | 1 | 0 | $10,167 | 20.3% | 2.37 | 3.49 | 3.12 | $3,540 | 52.2% | 0 |
| R4 + NKD | 136 | 55/50 | 0/0 | 31/0 | 0 | 0 | $7,598 | 15.2% | 1.53 | 2.01 | 1.45 | $5,679 | 53.2% | 0 |
| R4 + Stress + NKD | 139 | 55/50 | 3/0 | 31/0 | 1 | 0 | $12,370 | 24.7% | 1.99 | 3.23 | 2.80 | $4,792 | 53.1% | 0 |

## vault2026

Stress legs: 4. NKD/MNKD trades in artifact: 26.

| book | trades_attempted | R4 taken/rej | Stress taken/rej | NKD taken/rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | winrate | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R4 only | 81 | 46/35 | 0/0 | 0/0 | 0 | 0 | $1,059 | 2.1% | 1.16 | 0.87 | 0.47 | $4,075 | 59.4% | 0 |
| R4 + Stress | 85 | 46/35 | 3/1 | 0/0 | 0 | 0 | $1,890 | 3.8% | 1.24 | 1.21 | 0.93 | $3,656 | 61.8% | 0 |
| R4 + NKD | 107 | 46/35 | 0/0 | 24/2 | 0 | 0 | $7,066 | 14.1% | 1.58 | 2.88 | 2.43 | $5,253 | 66.0% | 0 |
| R4 + Stress + NKD | 111 | 46/35 | 3/1 | 24/2 | 0 | 0 | $7,898 | 15.8% | 1.59 | 2.89 | 2.93 | $4,877 | 67.3% | 0 |
