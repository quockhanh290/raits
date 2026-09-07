# STRESS_MID Legacy Status - 2026-08-21

Scratch-only. No production code modified.

Measures current legacy STRESS_MID under current lag-0 labels versus lag-1 live-causal labels.
The timing column treats the 5-minute bar stamped 10:15 as known at 10:20.

## floor

| label_basis | trades | days | net | pf | calmar | sharpe | maxdd | signal_after_entry | same_bar_exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lag0_current_backtest | 183 | 61 | $3,700 | 1.38 | 0.13 | 0.32 | $3,670 | 183 | 0 |
| lag1_live_causal | 171 | 56 | $1,313 | 1.14 | 0.06 | 0.12 | $2,802 | 171 | 0 |

By year/instrument for `lag0_current_backtest`:

      trades      net        avg
year                            
2018      43  -651.88 -15.160000
2019      10  -542.38 -54.238000
2020      56  -398.75  -7.120536
2022      74  5293.16  71.529189

            trades      net        avg
instrument                            
M2K             41   -72.60  -1.770732
MES             46  1194.29  25.962826
MNQ             45  1877.17  41.714889
MYM             51   701.29  13.750784

By year/instrument for `lag1_live_causal`:

      trades      net        avg
year                            
2018      35   271.03   7.743714
2019      10  -542.38 -54.238000
2020      56   333.89   5.962321
2022      70  1250.82  17.868857

            trades     net        avg
instrument                           
M2K             40 -232.34  -5.808500
MES             42  364.87   8.687381
MNQ             43  443.01  10.302558
MYM             46  737.82  16.039565

## vault2025

| label_basis | trades | days | net | pf | calmar | sharpe | maxdd | signal_after_entry | same_bar_exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lag0_current_backtest | 38 | 14 | $4,033 | 2.90 | 4.06 | 1.23 | $999 | 38 | 0 |
| lag1_live_causal | 40 | 14 | $3,998 | 3.13 | 4.03 | 1.25 | $999 | 40 | 0 |

By year/instrument for `lag0_current_backtest`:

      trades      net     avg
year                         
2025      38  4032.56  106.12

            trades      net       avg
instrument                           
M2K              8   191.38   23.9225
MES             10  1613.16  161.3160
MNQ             10  1998.93  199.8930
MYM             10   229.09   22.9090

By year/instrument for `lag1_live_causal`:

      trades      net      avg
year                          
2025      40  3998.14  99.9535

            trades      net         avg
instrument                             
M2K              7   182.79   26.112857
MES             11  1638.11  148.919091
MNQ             11  1655.69  150.517273
MYM             11   521.55   47.413636

## vault2026

| label_basis | trades | days | net | pf | calmar | sharpe | maxdd | signal_after_entry | same_bar_exit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lag0_current_backtest | 1 | 1 | $-64 | 0.00 | -1.59 | -1.13 | $64 | 1 | 0 |
| lag1_live_causal | 5 | 2 | $-779 | 0.00 | -1.59 | -1.22 | $779 | 5 | 0 |

By year/instrument for `lag0_current_backtest`:

      trades    net    avg
year                      
2026       1 -63.89 -63.89

            trades    net    avg
instrument                      
MYM              1 -63.89 -63.89

By year/instrument for `lag1_live_causal`:

      trades    net    avg
year                      
2026       5 -779.0 -155.8

            trades     net     avg
instrument                        
M2K              1  -78.09  -78.09
MES              1 -175.94 -175.94
MNQ              1 -356.79 -356.79
MYM              2 -168.18  -84.09
