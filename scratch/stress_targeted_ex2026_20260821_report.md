# Stress Targeted Ex-2026 Search - 2026-08-21

Scratch-only. No production code modified.

Purpose: after removing 2026 from the gate, deepen the morning broad-weakness continuation family without using regime labels.

Search space:

- setup `10:00` and `10:30`, known five minutes later;
- SHORT only, low-break continuation;
- instruments: `MNQ` and `MNQ/MES`;
- breadth: 3/4 or 4/4 below open/VWAP;
- gap-down count: 1/4, 2/4, or 3/4;
- RR: 1.5, 2.0, 2.5;
- exit: 14:00 or 15:55;
- 2026 is reported only as sanity, not used for ranking or rejection.

Rules searched: 144

## Ranked Candidates

| name | inst | trades | clusters | net | pf | calmar | maxdd | slip3 | boot_p5 | best_share | 2025 | 2025_trades | 2026_sanity | 2026_trades |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| target_gapcont_10:30_b4_g2_mnqmes_rr15_x1555 | MNQ/MES | 144 | 67 | $5,347 | 1.68 | 0.41 | $1,630 | $4,771 | $266 | 0.28 | $1,158 | 6 | $-773 | 17 |
| target_gapcont_10:30_b4_g2_mnqmes_rr25_x1555 | MNQ/MES | 144 | 67 | $5,097 | 1.65 | 0.39 | $1,630 | $4,521 | $-13 | 0.31 | $1,160 | 6 | $-773 | 17 |
| target_gapcont_10:30_b4_g2_mnqmes_rr20_x1555 | MNQ/MES | 144 | 67 | $5,054 | 1.64 | 0.39 | $1,630 | $4,478 | $44 | 0.32 | $1,160 | 6 | $-773 | 17 |
| target_gapcont_10:30_b4_g3_mnqmes_rr15_x1555 | MNQ/MES | 107 | 52 | $4,048 | 1.70 | 0.40 | $1,279 | $3,620 | $277 | 0.20 | $1,158 | 6 | $20 | 8 |
| target_gapcont_10:30_b4_g1_mnqmes_rr15_x1555 | MNQ/MES | 177 | 83 | $4,752 | 1.44 | 0.31 | $1,913 | $4,044 | $-1,174 | 0.32 | $1,314 | 16 | $-1,655 | 25 |
| target_gapcont_10:30_b4_g3_mnqmes_rr25_x1555 | MNQ/MES | 107 | 52 | $3,935 | 1.68 | 0.38 | $1,279 | $3,507 | $11 | 0.28 | $1,160 | 6 | $20 | 8 |
| target_gapcont_10:30_b4_g2_mnqmes_rr25_x1400 | MNQ/MES | 144 | 67 | $3,741 | 1.60 | 0.37 | $1,260 | $3,165 | $-199 | 0.25 | $1,387 | 6 | $-185 | 17 |
| target_gapcont_10:30_b4_g2_mnq_rr15_x1555 | MNQ | 68 | 59 | $4,046 | 2.03 | 0.54 | $933 | $3,774 | $1,070 | 0.23 | $647 | 3 | $-561 | 8 |
| target_gapcont_10:30_b4_g3_mnqmes_rr20_x1555 | MNQ/MES | 107 | 52 | $3,892 | 1.67 | 0.38 | $1,279 | $3,464 | $53 | 0.24 | $1,160 | 6 | $20 | 8 |
| target_gapcont_10:30_b4_g2_mnqmes_rr15_x1400 | MNQ/MES | 144 | 67 | $3,657 | 1.59 | 0.36 | $1,260 | $3,081 | $-178 | 0.23 | $1,438 | 6 | $-185 | 17 |
| target_gapcont_10:30_b4_g2_mnqmes_rr20_x1400 | MNQ/MES | 144 | 67 | $3,685 | 1.59 | 0.37 | $1,260 | $3,109 | $-209 | 0.24 | $1,387 | 6 | $-185 | 17 |
| target_gapcont_10:30_b4_g2_mnq_rr25_x1555 | MNQ | 68 | 59 | $3,892 | 1.99 | 0.52 | $933 | $3,620 | $970 | 0.25 | $647 | 3 | $-561 | 8 |
| target_gapcont_10:30_b4_g2_mnq_rr20_x1555 | MNQ | 68 | 59 | $3,759 | 1.95 | 0.50 | $933 | $3,487 | $876 | 0.25 | $647 | 3 | $-561 | 8 |
| target_gapcont_10:30_b4_g3_mnq_rr15_x1555 | MNQ | 50 | 45 | $3,393 | 2.31 | 0.63 | $670 | $3,193 | $1,040 | 0.15 | $647 | 3 | $-58 | 4 |
| target_gapcont_10:30_b4_g3_mnq_rr25_x1555 | MNQ | 50 | 45 | $3,392 | 2.31 | 0.63 | $670 | $3,192 | $956 | 0.20 | $647 | 3 | $-58 | 4 |
| target_gapcont_10:30_b4_g1_mnqmes_rr25_x1555 | MNQ/MES | 177 | 83 | $4,429 | 1.41 | 0.29 | $1,922 | $3,721 | $-1,647 | 0.36 | $1,316 | 16 | $-1,655 | 25 |
| target_gapcont_10:30_b4_g1_mnqmes_rr20_x1555 | MNQ/MES | 177 | 83 | $4,429 | 1.41 | 0.29 | $1,922 | $3,721 | $-1,689 | 0.36 | $1,316 | 16 | $-1,655 | 25 |
| target_gapcont_10:30_b4_g3_mnq_rr20_x1555 | MNQ | 50 | 45 | $3,258 | 2.26 | 0.61 | $670 | $3,058 | $863 | 0.16 | $647 | 3 | $-58 | 4 |
| target_gapcont_10:30_b4_g1_mnq_rr15_x1555 | MNQ | 83 | 73 | $3,689 | 1.66 | 0.38 | $1,223 | $3,357 | $298 | 0.25 | $776 | 8 | $-1,271 | 12 |
| target_gapcont_10:30_b4_g1_mnq_rr25_x1555 | MNQ | 83 | 73 | $3,536 | 1.63 | 0.36 | $1,223 | $3,204 | $110 | 0.27 | $776 | 8 | $-1,271 | 12 |
| target_gapcont_10:30_b4_g1_mnqmes_rr15_x1400 | MNQ/MES | 177 | 83 | $3,250 | 1.37 | 0.29 | $1,394 | $2,542 | $-1,494 | 0.26 | $1,958 | 16 | $-1,471 | 25 |
| target_gapcont_10:30_b4_g1_mnq_rr20_x1555 | MNQ | 83 | 73 | $3,402 | 1.61 | 0.35 | $1,223 | $3,070 | $34 | 0.28 | $776 | 8 | $-1,271 | 12 |
| target_gapcont_10:30_b4_g1_mnqmes_rr20_x1400 | MNQ/MES | 177 | 83 | $3,250 | 1.37 | 0.29 | $1,394 | $2,542 | $-1,537 | 0.27 | $1,907 | 16 | $-1,471 | 25 |
| target_gapcont_10:30_b4_g1_mnqmes_rr25_x1400 | MNQ/MES | 177 | 83 | $3,210 | 1.36 | 0.29 | $1,394 | $2,502 | $-1,565 | 0.29 | $1,907 | 16 | $-1,471 | 25 |
| target_gapcont_10:30_b4_g2_mnq_rr25_x1400 | MNQ | 68 | 59 | $2,858 | 1.86 | 0.44 | $804 | $2,586 | $594 | 0.21 | $863 | 3 | $48 | 8 |

## Event WFO Across Top Candidate Set

| total | best | without_best | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- |
| $2,472 | $692 | $1,780 | $-306 | 21 | 71 | False |

WFO selected counts:

                                              folds         net
selected                                                       
target_gapcont_10:30_b4_g1_mnq_rr15_x1555        23  1736.02675
target_gapcont_10:30_b4_g1_mnqmes_rr15_x1555     13   382.85500
target_gapcont_10:30_b4_g2_mnq_rr15_x1555         5   219.74650
target_gapcont_10:30_b4_g1_mnqmes_rr15_x1400     16   150.15000
target_gapcont_10:30_b4_g1_mnqmes_rr20_x1400     12    63.71475
target_gapcont_10:30_b4_g3_mnqmes_rr15_x1555      2   -80.39625

## Best Candidate Autopsy: `target_gapcont_10:30_b4_g2_mnqmes_rr15_x1555`

      trades          net        avg
year                                
2018       8  -545.277500 -68.159687
2019      21   483.614500  23.029262
2020      23  1555.957625  67.650332
2021       9   542.340000  60.260000
2022      40  3302.179250  82.554481
2023      26  -471.048000 -18.117231
2024      17   479.286000  28.193294

By instrument:

            trades          net        avg
instrument                                
MES             76  1300.681875  17.114235
MNQ             68  4046.370000  59.505441

By exit reason:

             trades          net         avg
exit_reason                                 
stop             24 -4889.553250 -203.731385
target           14  5007.295125  357.663937
time            106  5229.310000   49.333113

## Verdict

- This is still a research pass, not a deploy pass.
- Promote only if a fixed candidate, not just dynamic WFO selection, clears concentration and 2025 holdout.
- 2026 remains a visible warning column outside the gate.