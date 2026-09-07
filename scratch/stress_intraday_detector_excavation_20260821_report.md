# Stress Intraday Detector Excavation - 2026-08-21

Scope: scratch-only. No production code modified.

This pass does not use daily Stress labels. Candidates are activated only by
intraday-known morning conditions: cross-index below-open/below-VWAP breadth,
opening range expansion, gap-down breadth, or breakdown through the morning low.

## floor

Top intraday-only detector candidates:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liq_1020_b3_rr15_x1400 | 1090 | 594 | 290 | $15,396 | 1.32 | 0.85 | 0.76 | $2,711 | 0.18 | 0.17 |
| liq_1000_b3_rr15_x1400 | 1137 | 626 | 298 | $14,728 | 1.30 | 0.84 | 0.74 | $2,656 | 0.29 | 0.26 |
| liq_0945_b3_rr15_x1400 | 1100 | 613 | 310 | $14,299 | 1.32 | 0.91 | 0.51 | $3,762 | 0.37 | 0.33 |
| liq_1020_b4_rr2_x1555 | 699 | 358 | 237 | $10,982 | 1.27 | 0.58 | 0.57 | $2,577 | 0.14 | 0.27 |
| liq_1045_b3_rr2_x1555 | 1062 | 590 | 303 | $7,922 | 1.14 | 0.39 | 0.36 | $2,968 | 0.10 | 0.25 |
| wide_1020_b3_w3_rr15 | 267 | 150 | 101 | $5,719 | 1.31 | 0.47 | 0.31 | $2,681 | 0.15 | 0.24 |
| liq_1045_b3_rr15_x1400 | 1062 | 590 | 303 | $5,118 | 1.11 | 0.31 | 0.27 | $2,541 | 0.13 | 0.14 |
| wide_1045_b3_w3_rr15 | 324 | 184 | 125 | $1,358 | 1.06 | 0.11 | 0.06 | $3,463 | 0.11 | 0.17 |
| gap_1020_b3_g2_rr15 | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| gap_1045_b3_g2_rr15 | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| break_1045_b3_rr15 | 603 | 353 | 213 | $-853 | 0.97 | -0.08 | -0.04 | $2,925 | 0.19 | 0.32 |
| break_1100_b3_rr15 | 430 | 265 | 175 | $-2,118 | 0.89 | -0.23 | -0.06 | $5,038 | 0.19 | 0.31 |
| break_0945_b3_rr15 | 843 | 503 | 279 | $-4,326 | 0.90 | -0.30 | -0.08 | $7,563 | 0.20 | 0.34 |

Eligible candidate WFO uses only variants with at least 8 clusters and 20 trades.

Chronological event WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E009 | weak | liq_1000_b3_rr15_x1400 | 4 | $-7 | 0.89 |
| E010 | opening-selloff | wide_1020_b3_w3_rr15 | 3 | $9 | 1.06 |
| E011 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $61 | inf |
| E012 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-156 | 0.00 |
| E013 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-112 | 0.00 |
| E014 | wide-chop | wide_1045_b3_w3_rr15 | 4 | $-654 | 0.00 |
| E015 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $22 | 3.46 |
| E016 | broad-liquidation | wide_1020_b3_w3_rr15 | 4 | $-59 | 0.82 |
| E017 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $-26 | 0.00 |
| E018 | weak | liq_1020_b4_rr2_x1555 | 2 | $-138 | 0.00 |
| E019 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-408 | 0.00 |
| E020 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $275 | inf |
| E021 | weak | liq_1020_b4_rr2_x1555 | 2 | $394 | inf |
| E022 | opening-selloff | liq_1020_b4_rr2_x1555 | 4 | $-124 | 0.64 |
| E023 | broad-liquidation | liq_1020_b4_rr2_x1555 | 4 | $27 | 1.07 |
| E024 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $122 | inf |
| E025 | weak | liq_1020_b4_rr2_x1555 | 2 | $224 | inf |
| E026 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $443 | inf |
| E027 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $-186 | 0.00 |
| E028 | weak | liq_1020_b4_rr2_x1555 | 4 | $-48 | 0.61 |
| E029 | weak | liq_1020_b4_rr2_x1555 | 4 | $-152 | 0.00 |
| E030 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $25 | 3.53 |
| E031 | broad-liquidation | wide_1020_b3_w3_rr15 | 4 | $-383 | 0.00 |
| E032 | weak | liq_1020_b4_rr2_x1555 | 2 | $32 | 7.47 |
| E033 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-196 | 0.00 |
| E034 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-60 | 0.04 |
| E035 | broad-liquidation | wide_1020_b3_w3_rr15 | 3 | $458 | inf |
| E036 | opening-selloff | wide_1020_b3_w3_rr15 | 4 | $109 | 1.77 |
| E037 | wide-chop | wide_1020_b3_w3_rr15 | 2 | $-590 | 0.00 |
| E038 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $523 | inf |
| E039 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-322 | 0.00 |
| E040 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $343 | inf |
| E041 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-579 | 0.00 |
| E042 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $-85 | 0.00 |
| E043 | wide-chop | wide_1045_b3_w3_rr15 | 3 | $-78 | 0.18 |
| E044 | broad-liquidation | wide_1045_b3_w3_rr15 | 1 | $309 | inf |
| E045 | opening-selloff | wide_1045_b3_w3_rr15 | 3 | $288 | 6.62 |
| E046 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $-440 | 0.00 |
| E047 | broad-liquidation | liq_1020_b4_rr2_x1555 | 4 | $-604 | 0.00 |
| E048 | opening-selloff | wide_1045_b3_w3_rr15 | 3 | $-21 | 0.88 |
| E049 | broad-liquidation | wide_1045_b3_w3_rr15 | 4 | $566 | inf |
| E050 | broad-liquidation | wide_1045_b3_w3_rr15 | 4 | $-127 | 0.60 |
| E051 | broad-liquidation | wide_1045_b3_w3_rr15 | 1 | $-74 | 0.00 |
| E052 | wide-chop | wide_1045_b3_w3_rr15 | 2 | $-535 | 0.00 |
| E053 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $555 | inf |
| E054 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $-193 | 0.00 |
| E055 | broad-liquidation | wide_1045_b3_w3_rr15 | 1 | $-106 | 0.00 |
| E056 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $850 | inf |
| E057 | broad-liquidation | wide_1045_b3_w3_rr15 | 1 | $-284 | 0.00 |
| E058 | opening-selloff | wide_1045_b3_w3_rr15 | 2 | $195 | inf |
| E059 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $214 | inf |
| E060 | wide-chop | wide_1045_b3_w3_rr15 | 1 | $-95 | 0.00 |
| E061 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $-46 | 0.00 |
| E062 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $-232 | 0.00 |
| E063 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $15 | inf |
| E064 | broad-liquidation | wide_1045_b3_w3_rr15 | 5 | $-248 | 0.58 |
| E065 | wide-chop | wide_1045_b3_w3_rr15 | 2 | $-144 | 0.00 |
| E066 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $333 | inf |
| E067 | no selected trade | wide_1045_b3_w3_rr15 | 0 | $0 | inf |
| E068 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $89 | 24.67 |
| E069 | broad-liquidation | wide_1045_b3_w3_rr15 | 3 | $-748 | 0.00 |
| E070 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $-143 | 0.00 |
| E071 | opening-selloff | wide_1045_b3_w3_rr15 | 6 | $684 | 2.24 |
| E072 | opening-selloff | wide_1045_b3_w3_rr15 | 4 | $-844 | 0.00 |
| E073 | wide-chop | wide_1045_b3_w3_rr15 | 3 | $240 | inf |
| E074 | broad-liquidation | wide_1045_b3_w3_rr15 | 1 | $84 | inf |
| E075 | broad-liquidation | wide_1045_b3_w3_rr15 | 10 | $-34 | 0.97 |
| E076 | wide-chop | wide_1020_b3_w3_rr15 | 2 | $675 | inf |
| E077 | broad-liquidation | wide_1020_b3_w3_rr15 | 12 | $-606 | 0.45 |
| E078 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-490 | 0.00 |
| E079 | broad-liquidation | wide_1020_b3_w3_rr15 | 1 | $11 | inf |
| E080 | opening-selloff | wide_1020_b3_w3_rr15 | 2 | $154 | inf |
| E081 | broad-liquidation | wide_1045_b3_w3_rr15 | 3 | $-49 | 0.82 |
| E082 | broad-liquidation | wide_1045_b3_w3_rr15 | 2 | $-481 | 0.00 |
| E083 | weak | liq_1000_b3_rr15_x1400 | 2 | $-104 | 0.00 |
| E084 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $457 | inf |
| E085 | opening-selloff | wide_1020_b3_w3_rr15 | 2 | $-477 | 0.00 |
| E086 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $241 | inf |
| E087 | broad-liquidation | wide_1020_b3_w3_rr15 | 4 | $-231 | 0.36 |
| E088 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $117 | inf |
| E089 | opening-selloff | wide_1020_b3_w3_rr15 | 1 | $79 | inf |
| E090 | opening-selloff | wide_1020_b3_w3_rr15 | 2 | $442 | inf |
| E091 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $256 | inf |
| E092 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-176 | 0.00 |
| E093 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-34 | 0.07 |
| E094 | opening-selloff | wide_1020_b3_w3_rr15 | 2 | $401 | inf |
| E095 | broad-liquidation | wide_1020_b3_w3_rr15 | 3 | $781 | inf |
| E096 | broad-liquidation | wide_1020_b3_w3_rr15 | 4 | $1,369 | inf |
| E097 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-920 | 0.00 |
| E098 | broad-liquidation | wide_1020_b3_w3_rr15 | 1 | $-126 | 0.00 |
| E099 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $-214 | 0.00 |
| E100 | broad-liquidation | wide_1020_b3_w3_rr15 | 2 | $274 | 9.43 |
| E101 | broad-liquidation | wide_1020_b3_w3_rr15 | 1 | $-52 | 0.00 |
| E102 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E103 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E104 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E105 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E106 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E107 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E108 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E109 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E110 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E111 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E112 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E113 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E114 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E115 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E116 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E117 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E118 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E119 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E120 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E121 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E122 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E123 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E124 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E125 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E126 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E127 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E128 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E129 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E130 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E131 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E132 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E133 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E134 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E135 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E136 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E137 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E138 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E139 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E140 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E141 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E142 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E143 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E144 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E145 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E146 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E147 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E148 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E149 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E150 | broad-liquidation | liq_1020_b4_rr2_x1555 | 1 | $-331 | 0.00 |
| E151 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E152 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E153 | broad-liquidation | liq_1020_b4_rr2_x1555 | 11 | $11 | 1.01 |
| E154 | opening-selloff | liq_1020_b4_rr2_x1555 | 4 | $-495 | 0.09 |
| E155 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E156 | opening-selloff | liq_1020_b4_rr2_x1555 | 4 | $-332 | 0.41 |
| E157 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E158 | no selected trade | wide_1020_b3_w3_rr15 | 0 | $0 | inf |
| E159 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $547 | inf |
| E160 | broad-liquidation | liq_1020_b4_rr2_x1555 | 4 | $659 | inf |
| E161 | broad-liquidation | liq_1020_b4_rr2_x1555 | 1 | $-42 | 0.00 |
| E162 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $-240 | 0.00 |
| E163 | opening-selloff | liq_1020_b4_rr2_x1555 | 6 | $-121 | 0.48 |
| E164 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E165 | broad-liquidation | liq_1020_b4_rr2_x1555 | 8 | $57 | 1.11 |
| E166 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E167 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $545 | inf |
| E168 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $-579 | 0.00 |
| E169 | broad-liquidation | liq_1020_b4_rr2_x1555 | 3 | $-244 | 0.06 |
| E170 | weak | liq_1020_b4_rr2_x1555 | 2 | $61 | 5.91 |
| E171 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $-266 | 0.00 |
| E172 | opening-selloff | liq_1020_b4_rr2_x1555 | 4 | $563 | inf |
| E173 | broad-liquidation | liq_1020_b4_rr2_x1555 | 6 | $1,167 | 36.91 |
| E174 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $-14 | 0.41 |
| E175 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E176 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $-302 | 0.00 |
| E177 | weak | liq_1020_b4_rr2_x1555 | 2 | $-228 | 0.00 |
| E178 | weak | liq_1020_b4_rr2_x1555 | 6 | $75 | 1.31 |
| E179 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $183 | inf |
| E180 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $207 | inf |
| E181 | weak | liq_1020_b4_rr2_x1555 | 2 | $-269 | 0.00 |
| E182 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $355 | inf |
| E183 | weak | liq_1020_b4_rr2_x1555 | 2 | $-25 | 0.09 |
| E184 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $31 | 3.09 |
| E185 | weak | liq_1020_b4_rr2_x1555 | 4 | $158 | 1.57 |
| E186 | broad-liquidation | liq_1020_b4_rr2_x1555 | 4 | $-16 | 0.88 |
| E187 | weak | liq_1020_b4_rr2_x1555 | 2 | $74 | inf |
| E188 | opening-selloff | liq_0945_b3_rr15_x1400 | 4 | $-101 | 0.64 |
| E189 | weak | liq_0945_b3_rr15_x1400 | 2 | $248 | inf |
| E190 | opening-selloff | liq_0945_b3_rr15_x1400 | 4 | $-399 | 0.32 |
| E191 | weak | liq_0945_b3_rr15_x1400 | 4 | $251 | 203.22 |
| E192 | broad-liquidation | liq_0945_b3_rr15_x1400 | 6 | $531 | 1.76 |
| E193 | opening-selloff | liq_0945_b3_rr15_x1400 | 4 | $-265 | 0.13 |
| E194 | weak | liq_0945_b3_rr15_x1400 | 2 | $191 | inf |
| E195 | weak | liq_0945_b3_rr15_x1400 | 4 | $661 | inf |
| E196 | opening-selloff | liq_0945_b3_rr15_x1400 | 6 | $1,505 | inf |
| E197 | weak | liq_0945_b3_rr15_x1400 | 2 | $-401 | 0.00 |
| E198 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-180 | 0.00 |
| E199 | weak | liq_0945_b3_rr15_x1400 | 4 | $-436 | 0.00 |
| E200 | weak | liq_0945_b3_rr15_x1400 | 2 | $259 | inf |
| E201 | opening-selloff | liq_0945_b3_rr15_x1400 | 9 | $635 | 1.86 |
| E202 | opening-selloff | liq_0945_b3_rr15_x1400 | 9 | $-290 | 0.74 |
| E203 | broad-liquidation | liq_0945_b3_rr15_x1400 | 10 | $96 | 1.14 |
| E204 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $181 | inf |
| E205 | broad-liquidation | liq_0945_b3_rr15_x1400 | 3 | $-398 | 0.25 |
| E206 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-214 | 0.00 |
| E207 | weak | liq_0945_b3_rr15_x1400 | 2 | $259 | inf |
| E208 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-249 | 0.00 |
| E209 | weak | liq_0945_b3_rr15_x1400 | 2 | $-133 | 0.00 |
| E210 | broad-liquidation | liq_0945_b3_rr15_x1400 | 4 | $-408 | 0.16 |
| E211 | weak | liq_0945_b3_rr15_x1400 | 7 | $-180 | 0.37 |
| E212 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-225 | 0.00 |
| E213 | weak | liq_0945_b3_rr15_x1400 | 4 | $-164 | 0.64 |
| E214 | weak | liq_0945_b3_rr15_x1400 | 2 | $196 | inf |
| E215 | weak | liq_0945_b3_rr15_x1400 | 6 | $490 | inf |
| E216 | weak | liq_0945_b3_rr15_x1400 | 2 | $186 | inf |
| E217 | opening-selloff | liq_0945_b3_rr15_x1400 | 5 | $476 | 4.12 |
| E218 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $432 | inf |
| E219 | weak | liq_0945_b3_rr15_x1400 | 4 | $183 | 1.73 |
| E220 | weak | liq_0945_b3_rr15_x1400 | 5 | $198 | 2.66 |
| E221 | broad-liquidation | liq_0945_b3_rr15_x1400 | 2 | $452 | inf |
| E222 | opening-selloff | liq_0945_b3_rr15_x1400 | 8 | $1,176 | 5.65 |
| E223 | weak | liq_0945_b3_rr15_x1400 | 4 | $65 | 1.23 |
| E224 | weak | liq_0945_b3_rr15_x1400 | 2 | $308 | inf |
| E225 | weak | liq_0945_b3_rr15_x1400 | 11 | $31 | 1.05 |
| E226 | weak | liq_0945_b3_rr15_x1400 | 6 | $928 | inf |
| E227 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-308 | 0.00 |
| E228 | weak | liq_0945_b3_rr15_x1400 | 1 | $55 | inf |
| E229 | weak | liq_0945_b3_rr15_x1400 | 4 | $536 | inf |
| E230 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $372 | inf |
| E231 | opening-selloff | liq_0945_b3_rr15_x1400 | 8 | $193 | 1.36 |
| E232 | opening-selloff | liq_0945_b3_rr15_x1400 | 4 | $233 | 19.65 |
| E233 | broad-liquidation | liq_0945_b3_rr15_x1400 | 8 | $-704 | 0.28 |
| E234 | broad-liquidation | liq_0945_b3_rr15_x1400 | 2 | $-562 | 0.00 |
| E235 | weak | liq_0945_b3_rr15_x1400 | 2 | $-19 | 0.11 |
| E236 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-18 | 0.00 |
| E237 | weak | liq_0945_b3_rr15_x1400 | 2 | $70 | inf |
| E238 | weak | liq_0945_b3_rr15_x1400 | 3 | $41 | 1.94 |
| E239 | broad-liquidation | liq_0945_b3_rr15_x1400 | 2 | $-437 | 0.00 |
| E240 | weak | liq_0945_b3_rr15_x1400 | 2 | $-14 | 0.87 |
| E241 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-203 | 0.00 |
| E242 | weak | liq_0945_b3_rr15_x1400 | 4 | $-218 | 0.34 |
| E243 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $143 | inf |
| E244 | weak | liq_0945_b3_rr15_x1400 | 2 | $83 | inf |
| E245 | weak | liq_0945_b3_rr15_x1400 | 3 | $-86 | 0.51 |
| E246 | opening-selloff | liq_0945_b3_rr15_x1400 | 12 | $-87 | 0.82 |
| E247 | weak | liq_0945_b3_rr15_x1400 | 3 | $-192 | 0.30 |
| E248 | weak | liq_0945_b3_rr15_x1400 | 4 | $-67 | 0.57 |
| E249 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-51 | 0.00 |
| E250 | weak | liq_0945_b3_rr15_x1400 | 1 | $-49 | 0.00 |
| E251 | weak | liq_0945_b3_rr15_x1400 | 3 | $-24 | 0.62 |
| E252 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $132 | 4.53 |
| E253 | weak | liq_0945_b3_rr15_x1400 | 4 | $-42 | 0.82 |
| E254 | weak | liq_0945_b3_rr15_x1400 | 5 | $362 | 9.96 |
| E255 | weak | liq_0945_b3_rr15_x1400 | 2 | $287 | inf |
| E256 | weak | liq_0945_b3_rr15_x1400 | 2 | $169 | inf |
| E257 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $-151 | 0.00 |
| E258 | weak | liq_0945_b3_rr15_x1400 | 2 | $-219 | 0.00 |
| E259 | weak | liq_0945_b3_rr15_x1400 | 5 | $384 | 6.02 |
| E260 | weak | liq_0945_b3_rr15_x1400 | 3 | $-117 | 0.46 |
| E261 | weak | liq_0945_b3_rr15_x1400 | 3 | $77 | 1.59 |
| E262 | opening-selloff | liq_0945_b3_rr15_x1400 | 2 | $7 | 1.07 |
| E263 | weak | liq_0945_b3_rr15_x1400 | 3 | $-151 | 0.42 |
| E264 | opening-selloff | liq_0945_b3_rr15_x1400 | 6 | $828 | inf |
| E265 | weak | liq_0945_b3_rr15_x1400 | 2 | $-331 | 0.00 |
| E266 | weak | liq_0945_b3_rr15_x1400 | 4 | $-26 | 0.86 |
| E267 | weak | liq_0945_b3_rr15_x1400 | 2 | $-180 | 0.00 |
| E268 | weak | liq_0945_b3_rr15_x1400 | 4 | $68 | 3.71 |
| E269 | weak | liq_0945_b3_rr15_x1400 | 5 | $66 | 1.30 |
| E270 | weak | liq_0945_b3_rr15_x1400 | 2 | $-148 | 0.00 |
| E271 | weak | liq_0945_b3_rr15_x1400 | 1 | $58 | inf |
| E272 | weak | liq_0945_b3_rr15_x1400 | 3 | $273 | 6.17 |
| E273 | opening-selloff | liq_0945_b3_rr15_x1400 | 5 | $-500 | 0.00 |
| E274 | weak | liq_1020_b3_rr15_x1400 | 2 | $275 | inf |
| E275 | weak | liq_1020_b3_rr15_x1400 | 6 | $1,158 | 6.49 |
| E276 | opening-selloff | liq_1020_b3_rr15_x1400 | 4 | $-1,122 | 0.00 |
| E277 | weak | liq_1020_b3_rr15_x1400 | 2 | $-291 | 0.00 |
| E278 | opening-selloff | liq_1020_b3_rr15_x1400 | 4 | $96 | 1.20 |
| E279 | broad-liquidation | liq_1020_b3_rr15_x1400 | 3 | $-168 | 0.00 |
| E280 | weak | liq_1020_b3_rr15_x1400 | 2 | $478 | inf |
| E281 | opening-selloff | liq_1020_b3_rr15_x1400 | 2 | $445 | inf |
| E282 | weak | liq_1020_b3_rr15_x1400 | 6 | $825 | 68.40 |
| E283 | broad-liquidation | liq_1020_b3_rr15_x1400 | 2 | $-214 | 0.00 |
| E284 | weak | liq_1020_b3_rr15_x1400 | 4 | $-89 | 0.56 |
| E285 | weak | liq_1020_b3_rr15_x1400 | 3 | $61 | 7.93 |
| E286 | weak | liq_1020_b3_rr15_x1400 | 2 | $300 | inf |
| E287 | weak | liq_1020_b3_rr15_x1400 | 1 | $51 | inf |
| E288 | weak | liq_1020_b3_rr15_x1400 | 4 | $137 | 1.81 |
| E289 | opening-selloff | liq_1020_b3_rr15_x1400 | 2 | $-503 | 0.00 |
| E290 | broad-liquidation | liq_1020_b3_rr15_x1400 | 3 | $-519 | 0.00 |
| E291 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E292 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E293 | opening-selloff | liq_1000_b3_rr15_x1400 | 4 | $-514 | 0.16 |
| E294 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E295 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E296 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E297 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E298 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E299 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E300 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E301 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E302 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E303 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E304 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E305 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E306 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E307 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E308 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E309 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E310 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |
| E311 | no selected trade | liq_1020_b3_rr15_x1400 | 0 | $0 | inf |

Concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $6,526 | $1,505 | $5,021 | 0.23 | $0 | 111 | 303 | True |

By subtype for `liq_1020_b3_rr15_x1400`:

    event_subtype  trades         net       avg       pf
broad-liquidation     215 4782.207000 22.242823 1.323651
  opening-selloff     394 5048.788000 12.814183 1.299643
             weak     464 5521.680375 11.900173 1.393130
        wide-chop      17   42.860625  2.521213 1.022717

By subtype for `liq_1000_b3_rr15_x1400`:

    event_subtype  trades          net        avg       pf
broad-liquidation     140 -2896.555250 -20.689680 0.804995
  gap-liquidation       2   145.504250  72.752125      inf
  opening-selloff     370 13016.773000  35.180468 1.886609
             weak     605  4955.972750   8.191690 1.273228
        wide-chop      20  -493.425125 -24.671256 0.698412

By subtype for `liq_0945_b3_rr15_x1400`:

    event_subtype  trades          net         avg       pf
broad-liquidation      65 -1473.622500  -22.671115 0.809396
  opening-selloff     282  8785.439625   31.154041 1.644197
             weak     749  7692.422375   10.270257 1.349651
        wide-chop       4  -705.704250 -176.426062 0.000000

By subtype for `liq_1020_b4_rr2_x1555`:

    event_subtype  trades        net       avg       pf
broad-liquidation     215 6712.37425 31.220345 1.382507
  opening-selloff     302 2106.47125  6.975070 1.130232
             weak     182 2162.88925 11.884007 1.317634

By subtype for `liq_1045_b3_rr2_x1555`:

    event_subtype  trades         net         avg       pf
broad-liquidation     254  2940.35225   11.576190 1.140240
  opening-selloff     397  8992.40375   22.650891 1.514883
             weak     378    71.15975    0.188253 1.005051
        wide-chop      33 -4082.21975 -123.703629 0.108169

## vault2025

Top intraday-only detector candidates:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liq_0945_b3_rr15_x1400 | 145 | 78 | 46 | $8,014 | 1.96 | 2.28 | 4.84 | $1,770 | 0.46 | 0.32 |
| liq_1020_b4_rr2_x1555 | 86 | 44 | 31 | $6,952 | 2.14 | 1.67 | 5.38 | $1,357 | 0.15 | 0.26 |
| liq_1000_b3_rr15_x1400 | 157 | 86 | 43 | $6,875 | 1.70 | 1.78 | 3.65 | $1,932 | 0.35 | 0.22 |
| liq_1020_b3_rr15_x1400 | 143 | 79 | 45 | $5,778 | 1.64 | 1.48 | 4.41 | $1,321 | 0.20 | 0.14 |
| liq_1045_b3_rr15_x1400 | 131 | 73 | 43 | $4,031 | 1.54 | 1.25 | 2.47 | $1,645 | 0.10 | 0.11 |
| liq_1045_b3_rr2_x1555 | 131 | 73 | 43 | $3,078 | 1.33 | 0.86 | 1.25 | $2,486 | 0.08 | 0.21 |
| wide_1045_b3_w3_rr15 | 55 | 32 | 22 | $2,465 | 1.64 | 0.98 | 1.67 | $1,541 | 0.15 | 0.09 |
| break_0945_b3_rr15 | 110 | 62 | 39 | $2,227 | 1.29 | 0.77 | 1.17 | $2,043 | 0.26 | 0.31 |
| wide_1020_b3_w3_rr15 | 46 | 25 | 17 | $1,231 | 1.26 | 0.42 | 0.75 | $1,729 | 0.11 | 0.15 |
| gap_1020_b3_g2_rr15 | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| gap_1045_b3_g2_rr15 | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| break_1100_b3_rr15 | 56 | 32 | 21 | $-1,020 | 0.82 | -0.44 | -0.68 | $1,702 | 0.23 | 0.41 |
| break_1045_b3_rr15 | 78 | 42 | 29 | $-1,137 | 0.82 | -0.49 | -0.55 | $2,146 | 0.19 | 0.32 |

Eligible candidate WFO uses only variants with at least 8 clusters and 20 trades.

Chronological event WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E009 | weak | liq_0945_b3_rr15_x1400 | 5 | $-679 | 0.16 |
| E010 | broad-liquidation | liq_1020_b4_rr2_x1555 | 4 | $1,001 | 2.24 |
| E011 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $98 | inf |
| E012 | weak | liq_1020_b4_rr2_x1555 | 2 | $-240 | 0.00 |
| E013 | weak | liq_1020_b4_rr2_x1555 | 4 | $-210 | 0.48 |
| E014 | weak | liq_1000_b3_rr15_x1400 | 1 | $-197 | 0.00 |
| E015 | broad-liquidation | liq_1000_b3_rr15_x1400 | 2 | $-732 | 0.00 |
| E016 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $420 | inf |
| E017 | weak | liq_1020_b4_rr2_x1555 | 2 | $86 | inf |
| E018 | weak | liq_1020_b4_rr2_x1555 | 2 | $-207 | 0.00 |
| E019 | weak | liq_1020_b4_rr2_x1555 | 2 | $-49 | 0.00 |
| E020 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $17 | inf |
| E021 | weak | liq_1020_b4_rr2_x1555 | 2 | $371 | inf |
| E022 | opening-selloff | liq_1020_b4_rr2_x1555 | 4 | $951 | inf |
| E023 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $-668 | 0.00 |
| E024 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $41 | 7.57 |
| E025 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $73 | inf |
| E026 | weak | liq_1020_b4_rr2_x1555 | 2 | $-214 | 0.00 |
| E027 | opening-selloff | liq_1020_b4_rr2_x1555 | 6 | $73 | 1.23 |
| E028 | weak | liq_1020_b4_rr2_x1555 | 2 | $448 | inf |
| E029 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $-23 | 0.58 |
| E030 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $341 | inf |
| E031 | opening-selloff | liq_1020_b4_rr2_x1555 | 6 | $305 | 1.72 |
| E032 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E033 | weak | liq_0945_b3_rr15_x1400 | 2 | $95 | inf |
| E034 | weak | liq_0945_b3_rr15_x1400 | 4 | $-142 | 0.73 |
| E035 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E036 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E037 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E038 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E039 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E040 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E041 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E042 | weak | liq_0945_b3_rr15_x1400 | 2 | $188 | 2.27 |
| E043 | broad-liquidation | liq_0945_b3_rr15_x1400 | 2 | $-527 | 0.00 |
| E044 | weak | liq_0945_b3_rr15_x1400 | 2 | $-33 | 0.00 |
| E045 | weak | liq_0945_b3_rr15_x1400 | 2 | $344 | inf |
| E046 | weak | liq_0945_b3_rr15_x1400 | 6 | $556 | 2.16 |

Concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $1,486 | $1,001 | $485 | 0.67 | $340 | 17 | 38 | False |

By subtype for `liq_0945_b3_rr15_x1400`:

    event_subtype  trades         net        avg       pf
broad-liquidation      12  483.290250  40.274188 1.340627
  opening-selloff      40 5226.271750 130.656794 4.578687
             weak      93 2304.516625  24.779749 1.419252

By subtype for `liq_1020_b4_rr2_x1555`:

    event_subtype  trades        net        avg       pf
broad-liquidation      34 4060.35700 119.422265 2.218399
  opening-selloff      26 3065.63875 117.909183 4.857065
             weak      26 -173.95275  -6.690490 0.910788

By subtype for `liq_1000_b3_rr15_x1400`:

    event_subtype  trades         net        avg       pf
broad-liquidation      30  893.797625  29.793254 1.242955
  opening-selloff      49 3717.560625  75.868584 2.815485
             weak      76 1880.713500  24.746230 1.460669
        wide-chop       2  382.634250 191.317125      inf

By subtype for `liq_1020_b3_rr15_x1400`:

    event_subtype  trades          net         avg       pf
broad-liquidation      34  3083.026875   90.677261 2.216529
  opening-selloff      40  3052.598125   76.314953 2.599967
             weak      63   866.298875   13.750776 1.263947
        wide-chop       6 -1223.850000 -203.975000 0.042086

By subtype for `liq_1045_b3_rr15_x1400`:

    event_subtype  trades          net        avg       pf
broad-liquidation      42  2843.456750  67.701351 2.253460
  opening-selloff      56  2627.178375  46.913900 1.949128
             weak      28 -1390.897125 -49.674897 0.330339
        wide-chop       5   -49.042500  -9.808500 0.869144

## vault2026

Top intraday-only detector candidates:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liq_1020_b4_rr2_x1555 | 51 | 27 | 19 | $2,776 | 1.57 | 1.12 | 3.36 | $1,439 | 0.16 | 0.22 |
| liq_1045_b3_rr2_x1555 | 85 | 47 | 27 | $2,115 | 1.28 | 0.71 | 1.74 | $2,042 | 0.07 | 0.15 |
| break_0945_b3_rr15 | 52 | 31 | 21 | $1,898 | 1.36 | 0.82 | 1.10 | $2,906 | 0.33 | 0.29 |
| break_1045_b3_rr15 | 51 | 28 | 24 | $1,629 | 1.40 | 0.78 | 2.92 | $943 | 0.16 | 0.27 |
| break_1100_b3_rr15 | 36 | 23 | 20 | $1,364 | 1.48 | 0.78 | 1.45 | $1,537 | 0.17 | 0.28 |
| liq_1045_b3_rr15_x1400 | 85 | 47 | 27 | $660 | 1.10 | 0.27 | 0.59 | $1,891 | 0.08 | 0.12 |
| gap_1020_b3_g2_rr15 | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| gap_1045_b3_g2_rr15 | 0 | 0 | 0 | $0 | inf | 0.00 | inf | $0 | 0.00 | 0.00 |
| liq_1000_b3_rr15_x1400 | 90 | 49 | 27 | $-536 | 0.94 | -0.19 | -0.25 | $3,664 | 0.17 | 0.27 |
| liq_0945_b3_rr15_x1400 | 83 | 47 | 25 | $-574 | 0.93 | -0.24 | -0.27 | $3,531 | 0.31 | 0.46 |
| wide_1045_b3_w3_rr15 | 37 | 21 | 16 | $-598 | 0.85 | -0.35 | -0.52 | $2,136 | 0.08 | 0.16 |
| wide_1020_b3_w3_rr15 | 29 | 17 | 13 | $-1,027 | 0.71 | -0.70 | -1.01 | $1,763 | 0.03 | 0.17 |
| liq_1020_b3_rr15_x1400 | 70 | 39 | 25 | $-1,636 | 0.81 | -0.64 | -0.88 | $3,222 | 0.14 | 0.23 |

Eligible candidate WFO uses only variants with at least 8 clusters and 20 trades.

Chronological event WFO:

| test_cluster | event_subtype | selected | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E009 | broad-liquidation | liq_1000_b3_rr15_x1400 | 2 | $-678 | 0.00 |
| E010 | weak | liq_1000_b3_rr15_x1400 | 2 | $-482 | 0.00 |
| E011 | opening-selloff | liq_1000_b3_rr15_x1400 | 2 | $226 | inf |
| E012 | weak | liq_1020_b4_rr2_x1555 | 2 | $22 | 1.77 |
| E013 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $-476 | 0.00 |
| E014 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $600 | inf |
| E015 | weak | liq_1020_b4_rr2_x1555 | 2 | $-576 | 0.00 |
| E016 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $1,026 | inf |
| E017 | opening-selloff | liq_1020_b4_rr2_x1555 | 2 | $-66 | 0.00 |
| E018 | broad-liquidation | liq_1020_b4_rr2_x1555 | 2 | $502 | inf |
| E019 | broad-liquidation | liq_1020_b4_rr2_x1555 | 5 | $-1,206 | 0.16 |
| E020 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E021 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E022 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E023 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E024 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E025 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E026 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |
| E027 | no selected trade | liq_1020_b4_rr2_x1555 | 0 | $0 | inf |

Concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $-1,108 | $1,026 | $-2,134 | inf | $0 | 5 | 19 | False |

By subtype for `liq_1020_b4_rr2_x1555`:

    event_subtype  trades        net        avg       pf
broad-liquidation      27 -879.17975 -32.562213 0.765196
  opening-selloff      14 3356.81275 239.772339 7.190946
             weak      10  297.89100  29.789100 1.486393

By subtype for `liq_1045_b3_rr2_x1555`:

    event_subtype  trades        net         avg       pf
broad-liquidation      24  275.39450   11.474771 1.117653
  opening-selloff      33 1378.46625   41.771705 1.401612
             weak      23 1179.59900   51.286913 2.067027
        wide-chop       5 -718.82500 -143.765000 0.005204

By subtype for `break_0945_b3_rr15`:

    event_subtype  trades         net         avg       pf
broad-liquidation       1 -104.990000 -104.990000 0.000000
  opening-selloff      15 -742.293062  -49.486204 0.680877
             weak      36 2745.472625   76.263128 1.956500

By subtype for `break_1045_b3_rr15`:

    event_subtype  trades         net        avg        pf
broad-liquidation      17  182.456500  10.732735  1.084446
  opening-selloff      18  -55.905562  -3.105865  0.966007
             weak      13 1504.101562 115.700120 11.452953
        wide-chop       3   -1.470000  -0.490000  0.987243

By subtype for `break_1100_b3_rr15`:

    event_subtype  trades         net        avg       pf
broad-liquidation      11  266.930875  24.266443 1.237203
  opening-selloff      17 1270.868750  74.756985 1.991328
             weak       7 -287.332500 -41.047500 0.321309
        wide-chop       1  113.760000 113.760000      inf

## Verdict

A floor intraday-only detector passed the concentration gate. This requires
separate holdout verification before any paper/deploy discussion.
