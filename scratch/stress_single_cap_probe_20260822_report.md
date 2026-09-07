# Stress Single-Cap Probe - 2026-08-22

Scratch-only. Candidate: `mnq_only_g3_q7`. This tests whether using one cap level for both Normal and Stress improves the book.

`single_X` means Normal gross cap = X, Normal net cap = X, and Stress gross cap = X.

## floor

| policy | normal_cap | stress_cap | normal_taken_rej | stress_taken_rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| split_current_normal5_net44_stress10 | 5.0%/4.4% | 10.0% | 551/192 | 49/1 | 11 | 7 | $52,139 | 104.3% | 1.75 | 2.97 | 1.15 | $6,646 | 2 |
| single_5 | 5.0%/5.0% | 5.0% | 595/151 | 32/18 | 8 | 4 | $45,950 | 91.9% | 1.66 | 2.77 | 1.32 | $5,082 | 2 |
| single_7p5 | 7.5%/7.5% | 7.5% | 704/39 | 47/3 | 16 | 7 | $50,236 | 100.5% | 1.54 | 2.34 | 0.67 | $10,986 | 2 |
| single_10 | 10.0%/10.0% | 10.0% | 734/9 | 49/1 | 19 | 7 | $53,098 | 106.2% | 1.55 | 2.38 | 0.72 | $10,729 | 2 |

## vault2025

| policy | normal_cap | stress_cap | normal_taken_rej | stress_taken_rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| split_current_normal5_net44_stress10 | 5.0%/4.4% | 10.0% | 55/50 | 3/0 | 1 | 0 | $10,167 | 20.3% | 2.37 | 3.49 | 3.12 | $3,540 | 0 |
| single_5 | 5.0%/5.0% | 5.0% | 63/42 | 0/3 | 0 | 0 | $6,603 | 13.2% | 1.66 | 2.22 | 2.07 | $3,465 | 0 |
| single_7p5 | 7.5%/7.5% | 7.5% | 82/21 | 2/1 | 2 | 0 | $11,360 | 22.7% | 1.84 | 3.15 | 2.43 | $5,077 | 2 |
| single_10 | 10.0%/10.0% | 10.0% | 97/6 | 3/0 | 2 | 0 | $11,746 | 23.5% | 1.74 | 2.90 | 1.93 | $6,612 | 2 |

## vault2026

| policy | normal_cap | stress_cap | normal_taken_rej | stress_taken_rej | closed | blocked_late_normal | net | ret | pf | sharpe | calmar | maxdd | halts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| split_current_normal5_net44_stress10 | 5.0%/4.4% | 10.0% | 46/35 | 3/1 | 0 | 0 | $1,890 | 3.8% | 1.24 | 1.21 | 0.93 | $3,656 | 0 |
| single_5 | 5.0%/5.0% | 5.0% | 49/32 | 0/4 | 0 | 0 | $878 | 1.8% | 1.12 | 0.66 | 0.40 | $3,990 | 0 |
| single_7p5 | 7.5%/7.5% | 7.5% | 62/19 | 1/3 | 1 | 0 | $5,091 | 10.2% | 1.57 | 2.65 | 1.55 | $5,934 | 0 |
| single_10 | 10.0%/10.0% | 10.0% | 66/15 | 3/1 | 2 | 0 | $4,293 | 8.6% | 1.33 | 1.60 | 0.96 | $8,090 | 0 |
