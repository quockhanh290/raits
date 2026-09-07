# Stress Intraday 10:15-Close Causal Pass - 2026-08-21

Scope: scratch-only. No production code modified.

Rules use the fully closed 5-minute bar stamped 10:15 and enter at the 10:20
1-minute open. They do not use daily Stress labels.

## floor

Candidate table:

| name | trades | days | clusters | net | pf | sharpe | calmar | maxdd | target_rate | stop_rate | signal_after_entry | same_bar_exit | slip2x_net | slip3x_net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| causal1015_b3_rr2_x1555 | 1099 | 606 | 304 | $7,227 | 1.11 | 0.33 | 0.23 | $4,215 | 0.12 | 0.30 | 0 | 0 | $5,230 | $3,232 |
| causal1015_b4_mnq_rr2_x1555 | 327 | 327 | 215 | $1,570 | 1.06 | 0.14 | 0.09 | $2,440 | 0.10 | 0.31 | 0 | 0 | $1,243 | $916 |
| causal1015_b4_rr2_x1555 | 671 | 345 | 222 | $1,229 | 1.03 | 0.07 | 0.04 | $4,624 | 0.10 | 0.30 | 0 | 0 | $42 | $-1,145 |
| causal1015_b4_rr15_x1400 | 671 | 345 | 222 | $-787 | 0.98 | -0.05 | -0.03 | $3,892 | 0.13 | 0.21 | 0 | 0 | $-1,974 | $-3,161 |
| causal1015_b4_wide3_rr2_x1555 | 207 | 113 | 84 | $-1,232 | 0.94 | -0.10 | -0.03 | $5,728 | 0.07 | 0.36 | 0 | 0 | $-1,607 | $-1,982 |

Swing overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| causal1015_b3_rr2_x1555 | 455 | 269 | 191 | $1,964 | $38,791 |
| causal1015_b4_mnq_rr2_x1555 | 140 | 77 | 77 | $571 | $14,785 |
| causal1015_b4_rr2_x1555 | 291 | 167 | 112 | $-225 | $25,325 |
| causal1015_b4_rr15_x1400 | 291 | 167 | 112 | $-1,048 | $20,601 |
| causal1015_b4_wide3_rr2_x1555 | 125 | 61 | 41 | $234 | $12,756 |

Calm overlap:

| name | held | opposite | conflict_days | opposite_net | opposite_gross |
| --- | --- | --- | --- | --- | --- |
| causal1015_b3_rr2_x1555 | 96 | 96 | 63 | $-1,419 | $8,618 |
| causal1015_b4_mnq_rr2_x1555 | 28 | 28 | 28 | $-559 | $3,221 |
| causal1015_b4_rr2_x1555 | 51 | 51 | 31 | $-1,054 | $4,995 |
| causal1015_b4_rr15_x1400 | 51 | 51 | 31 | $-997 | $4,853 |
| causal1015_b4_wide3_rr2_x1555 | 9 | 9 | 6 | $-561 | $632 |

Event bootstrap:

| name | events | p_pos | p5 | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| causal1015_b3_rr2_x1555 | 304 | 0.84 | $-4,303 | $7,096 | $19,360 |
| causal1015_b4_mnq_rr2_x1555 | 215 | 0.66 | $-4,230 | $1,498 | $7,552 |
| causal1015_b4_rr2_x1555 | 222 | 0.58 | $-7,907 | $1,151 | $10,711 |
| causal1015_b4_rr15_x1400 | 222 | 0.42 | $-8,323 | $-897 | $6,818 |
| causal1015_b4_wide3_rr2_x1555 | 84 | 0.38 | $-9,024 | $-1,410 | $6,621 |

Chronological event WFO:

| test_cluster | selected | event_subtype | trades | net | pf |
| --- | --- | --- | --- | --- | --- |
| E009 | causal1015_b3_rr2_x1555 | weak | 3 | $-124 | 0.00 |
| E010 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $66 | 3.33 |
| E011 | causal1015_b4_wide3_rr2_x1555 | broad-liquidation | 4 | $-816 | 0.00 |
| E012 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $141 | 2.04 |
| E013 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 8 | $277 | 1.62 |
| E014 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-26 | 0.00 |
| E015 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-138 | 0.00 |
| E016 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $84 | inf |
| E017 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $275 | inf |
| E018 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $394 | inf |
| E019 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-124 | 0.64 |
| E020 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $27 | 1.07 |
| E021 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $122 | inf |
| E022 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $124 | 2.23 |
| E023 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-291 | 0.00 |
| E024 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-186 | 0.00 |
| E025 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-48 | 0.61 |
| E026 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-2 | 0.31 |
| E027 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $25 | 3.53 |
| E028 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-200 | 0.00 |
| E029 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-100 | 0.00 |
| E030 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-110 | 0.00 |
| E031 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-124 | 0.64 |
| E032 | causal1015_b3_rr2_x1555 | broad-liquidation | 6 | $-52 | 0.89 |
| E033 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 8 | $118 | 1.52 |
| E034 | causal1015_b3_rr2_x1555 | opening-selloff | 6 | $186 | 1.63 |
| E035 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-186 | 0.00 |
| E036 | causal1015_b4_rr2_x1555 | broad-liquidation | 6 | $-125 | 0.77 |
| E037 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-227 | 0.00 |
| E038 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $606 | 19.23 |
| E039 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $184 | 1.70 |
| E040 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-305 | 0.00 |
| E041 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $793 | inf |
| E042 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $295 | inf |
| E043 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $-816 | 0.00 |
| E044 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $130 | inf |
| E045 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-200 | 0.00 |
| E046 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $273 | inf |
| E047 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-143 | 0.00 |
| E048 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-79 | 0.00 |
| E049 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-59 | 0.00 |
| E050 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $-55 | 0.60 |
| E051 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-45 | 0.11 |
| E052 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-126 | 0.00 |
| E053 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-113 | 0.00 |
| E054 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 8 | $-178 | 0.01 |
| E055 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-135 | 0.00 |
| E056 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 6 | $184 | 1.70 |
| E057 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-305 | 0.00 |
| E058 | causal1015_b3_rr2_x1555 | opening-selloff | 5 | $788 | 159.00 |
| E059 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $295 | inf |
| E060 | causal1015_b3_rr2_x1555 | opening-selloff | 11 | $-1,031 | 0.13 |
| E061 | causal1015_b3_rr2_x1555 | broad-liquidation | 2 | $-200 | 0.00 |
| E062 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $549 | inf |
| E063 | causal1015_b3_rr2_x1555 | weak | 4 | $-47 | 0.67 |
| E064 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-248 | 0.00 |
| E065 | causal1015_b3_rr2_x1555 | weak | 2 | $-49 | 0.00 |
| E066 | causal1015_b3_rr2_x1555 | weak | 11 | $-248 | 0.38 |
| E067 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-45 | 0.11 |
| E068 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-121 | 0.00 |
| E069 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $150 | 1.75 |
| E070 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $-220 | 0.00 |
| E071 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 8 | $157 | 1.57 |
| E072 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $-79 | 0.75 |
| E073 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $55 | 1.38 |
| E074 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-27 | 0.00 |
| E075 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $2 | 1.43 |
| E076 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-58 | 0.03 |
| E077 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $-72 | 0.27 |
| E078 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $-209 | 0.12 |
| E079 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $329 | inf |
| E080 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $241 | 3.37 |
| E081 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-56 | 0.15 |
| E082 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $93 | inf |
| E083 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $307 | 1.80 |
| E084 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-408 | 0.00 |
| E085 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-311 | 0.00 |
| E086 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $259 | inf |
| E087 | causal1015_b4_rr2_x1555 | broad-liquidation | 1 | $195 | inf |
| E088 | causal1015_b4_rr2_x1555 | broad-liquidation | 8 | $-1,019 | 0.00 |
| E089 | causal1015_b4_mnq_rr2_x1555 | broad-liquidation | 1 | $230 | inf |
| E090 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-100 | 0.35 |
| E091 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-353 | 0.00 |
| E092 | causal1015_b4_mnq_rr2_x1555 | full-breadth-selloff | 1 | $-115 | 0.00 |
| E093 | causal1015_b4_mnq_rr2_x1555 | broad-liquidation | 1 | $397 | inf |
| E094 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-167 | 0.03 |
| E095 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $653 | inf |
| E096 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-124 | 0.17 |
| E097 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-254 | 0.00 |
| E098 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $-760 | 0.00 |
| E099 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-184 | 0.00 |
| E100 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $957 | inf |
| E101 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $685 | inf |
| E102 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-157 | 0.00 |
| E103 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 5 | $283 | 2.50 |
| E104 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-15 | 0.87 |
| E105 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-71 | 0.00 |
| E106 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-590 | 0.00 |
| E107 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $50 | inf |
| E108 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $700 | inf |
| E109 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-142 | 0.00 |
| E110 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-220 | 0.00 |
| E111 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-149 | 0.02 |
| E112 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-285 | 0.13 |
| E113 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $110 | inf |
| E114 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-314 | 0.00 |
| E115 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $221 | 1.38 |
| E116 | causal1015_b4_rr2_x1555 | broad-liquidation | 3 | $-377 | 0.16 |
| E117 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-153 | 0.00 |
| E118 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-113 | 0.00 |
| E119 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-254 | 0.38 |
| E120 | causal1015_b4_mnq_rr2_x1555 | full-breadth-selloff | 1 | $13 | inf |
| E121 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-0 | 0.99 |
| E122 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $114 | inf |
| E123 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $245 | 3.48 |
| E124 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $451 | inf |
| E125 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-137 | 0.61 |
| E126 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $59 | inf |
| E127 | causal1015_b4_rr2_x1555 | broad-liquidation | 6 | $-40 | 0.93 |
| E128 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-364 | 0.00 |
| E129 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $41 | 2.30 |
| E130 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-405 | 0.06 |
| E131 | causal1015_b4_mnq_rr2_x1555 | broad-liquidation | 1 | $192 | inf |
| E132 | causal1015_b4_rr2_x1555 | broad-liquidation | 1 | $99 | inf |
| E133 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $-483 | 0.47 |
| E134 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 5 | $283 | 2.50 |
| E135 | causal1015_b3_rr2_x1555 | opening-selloff | 3 | $-342 | 0.00 |
| E136 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-15 | 0.87 |
| E137 | causal1015_b3_rr2_x1555 | weak | 1 | $-22 | 0.00 |
| E138 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-71 | 0.00 |
| E139 | causal1015_b3_rr2_x1555 | weak | 2 | $316 | inf |
| E140 | causal1015_b3_rr2_x1555 | weak | 6 | $-580 | 0.10 |
| E141 | causal1015_b4_mnq_rr2_x1555 | broad-liquidation | 1 | $405 | inf |
| E142 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-211 | 0.00 |
| E143 | causal1015_b3_rr2_x1555 | broad-liquidation | 2 | $-142 | 0.00 |
| E144 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $925 | inf |
| E145 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-76 | 0.76 |
| E146 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 3 | $-172 | 0.67 |
| E147 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $971 | inf |
| E148 | causal1015_b4_rr2_x1555 | broad-liquidation | 1 | $-331 | 0.00 |
| E149 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $143 | inf |
| E150 | causal1015_b4_rr2_x1555 | broad-liquidation | 7 | $524 | 8.77 |
| E151 | causal1015_b4_rr2_x1555 | broad-liquidation | 3 | $-341 | 0.00 |
| E152 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-419 | 0.00 |
| E153 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-541 | 0.00 |
| E154 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-316 | 0.00 |
| E155 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-564 | 0.00 |
| E156 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $360 | inf |
| E157 | causal1015_b4_rr2_x1555 | broad-liquidation | 6 | $248 | 1.60 |
| E158 | causal1015_b4_rr2_x1555 | broad-liquidation | 1 | $-42 | 0.00 |
| E159 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $-121 | 0.48 |
| E160 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E161 | causal1015_b4_rr2_x1555 | broad-liquidation | 8 | $57 | 1.11 |
| E162 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E163 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $545 | inf |
| E164 | causal1015_b4_rr2_x1555 | broad-liquidation | 3 | $-244 | 0.06 |
| E165 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $52 | 2.30 |
| E166 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-266 | 0.00 |
| E167 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $563 | inf |
| E168 | causal1015_b4_rr2_x1555 | broad-liquidation | 6 | $1,167 | 36.91 |
| E169 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $-14 | 0.41 |
| E170 | causal1015_b4_rr2_x1555 | no selected trade | 0 | $0 | inf |
| E171 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 8 | $-347 | 0.48 |
| E172 | causal1015_b4_rr2_x1555 | broad-liquidation | 4 | $-177 | 0.51 |
| E173 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $152 | 2.04 |
| E174 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $31 | 3.09 |
| E175 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $158 | 1.57 |
| E176 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-16 | 0.88 |
| E177 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-164 | 0.31 |
| E178 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-515 | 0.00 |
| E179 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-44 | 0.02 |
| E180 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $38 | 1.15 |
| E181 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $-318 | 0.07 |
| E182 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $249 | inf |
| E183 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-351 | 0.00 |
| E184 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $91 | inf |
| E185 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $66 | inf |
| E186 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 6 | $-294 | 0.54 |
| E187 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-244 | 0.00 |
| E188 | causal1015_b4_rr2_x1555 | broad-liquidation | 2 | $248 | inf |
| E189 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $-203 | 0.00 |
| E190 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 2 | $349 | inf |
| E191 | causal1015_b4_rr2_x1555 | full-breadth-selloff | 4 | $625 | inf |
| E192 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 3 | $-172 | 0.67 |
| E193 | causal1015_b3_rr2_x1555 | opening-selloff | 2 | $719 | inf |
| E194 | causal1015_b3_rr2_x1555 | weak | 4 | $1,593 | inf |
| E195 | causal1015_b3_rr2_x1555 | broad-liquidation | 1 | $-331 | 0.00 |
| E196 | causal1015_b3_rr2_x1555 | broad-liquidation | 2 | $143 | inf |
| E197 | causal1015_b3_rr2_x1555 | broad-liquidation | 7 | $524 | 8.77 |
| E198 | causal1015_b3_rr2_x1555 | weak | 1 | $-98 | 0.00 |
| E199 | causal1015_b3_rr2_x1555 | opening-selloff | 7 | $739 | 3.16 |
| E200 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-419 | 0.00 |
| E201 | causal1015_b3_rr2_x1555 | opening-selloff | 4 | $-495 | 0.09 |
| E202 | causal1015_b3_rr2_x1555 | weak | 5 | $597 | 2.89 |
| E203 | causal1015_b3_rr2_x1555 | weak | 4 | $-332 | 0.41 |
| E204 | causal1015_b3_rr2_x1555 | weak | 2 | $-118 | 0.00 |
| E205 | causal1015_b3_rr2_x1555 | opening-selloff | 4 | $-359 | 0.04 |
| E206 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $360 | inf |
| E207 | causal1015_b3_rr2_x1555 | broad-liquidation | 6 | $248 | 1.60 |
| E208 | causal1015_b3_rr2_x1555 | broad-liquidation | 1 | $-42 | 0.00 |
| E209 | causal1015_b3_rr2_x1555 | wide-chop | 3 | $609 | 6.25 |
| E210 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 6 | $-121 | 0.48 |
| E211 | causal1015_b3_rr2_x1555 | wide-chop | 2 | $356 | inf |
| E212 | causal1015_b3_rr2_x1555 | broad-liquidation | 10 | $-327 | 0.64 |
| E213 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $545 | inf |
| E214 | causal1015_b3_rr2_x1555 | opening-selloff | 2 | $-579 | 0.00 |
| E215 | causal1015_b3_rr2_x1555 | broad-liquidation | 3 | $-244 | 0.06 |
| E216 | causal1015_b3_rr2_x1555 | weak | 8 | $523 | 7.32 |
| E217 | causal1015_b3_rr2_x1555 | weak | 3 | $-389 | 0.00 |
| E218 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $563 | inf |
| E219 | causal1015_b3_rr2_x1555 | weak | 8 | $970 | 5.24 |
| E220 | causal1015_b3_rr2_x1555 | broad-liquidation | 2 | $-14 | 0.41 |
| E221 | causal1015_b3_rr2_x1555 | opening-selloff | 2 | $-477 | 0.00 |
| E222 | causal1015_b3_rr2_x1555 | weak | 2 | $485 | inf |
| E223 | causal1015_b3_rr2_x1555 | weak | 2 | $-302 | 0.00 |
| E224 | causal1015_b3_rr2_x1555 | weak | 1 | $-40 | 0.00 |
| E225 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 10 | $-231 | 0.68 |
| E226 | causal1015_b3_rr2_x1555 | weak | 2 | $31 | 5.97 |
| E227 | causal1015_b3_rr2_x1555 | broad-liquidation | 7 | $-200 | 0.66 |
| E228 | causal1015_b3_rr2_x1555 | weak | 2 | $-60 | 0.56 |
| E229 | causal1015_b3_rr2_x1555 | weak | 8 | $-374 | 0.44 |
| E230 | causal1015_b3_rr2_x1555 | opening-selloff | 3 | $148 | 7.22 |
| E231 | causal1015_b3_rr2_x1555 | weak | 1 | $3 | inf |
| E232 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $31 | 3.09 |
| E233 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $158 | 1.57 |
| E234 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-16 | 0.88 |
| E235 | causal1015_b3_rr2_x1555 | opening-selloff | 9 | $-485 | 0.19 |
| E236 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-515 | 0.00 |
| E237 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-44 | 0.02 |
| E238 | causal1015_b3_rr2_x1555 | opening-selloff | 1 | $31 | inf |
| E239 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 6 | $38 | 1.15 |
| E240 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-318 | 0.07 |
| E241 | causal1015_b3_rr2_x1555 | weak | 2 | $-279 | 0.00 |
| E242 | causal1015_b3_rr2_x1555 | weak | 2 | $447 | inf |
| E243 | causal1015_b3_rr2_x1555 | weak | 1 | $146 | inf |
| E244 | causal1015_b3_rr2_x1555 | weak | 6 | $-384 | 0.39 |
| E245 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-7 | 0.98 |
| E246 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $432 | inf |
| E247 | causal1015_b3_rr2_x1555 | weak | 1 | $93 | inf |
| E248 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 3 | $76 | inf |
| E249 | causal1015_b3_rr2_x1555 | weak | 8 | $-566 | 0.38 |
| E250 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-244 | 0.00 |
| E251 | causal1015_b3_rr2_x1555 | weak | 5 | $220 | 7.52 |
| E252 | causal1015_b3_rr2_x1555 | broad-liquidation | 4 | $22 | 1.10 |
| E253 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $331 | 2.63 |
| E254 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $349 | inf |
| E255 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 7 | $490 | 2.84 |
| E256 | causal1015_b3_rr2_x1555 | weak | 6 | $-133 | 0.51 |
| E257 | causal1015_b3_rr2_x1555 | weak | 2 | $-86 | 0.00 |
| E258 | causal1015_b3_rr2_x1555 | weak | 2 | $237 | inf |
| E259 | causal1015_b3_rr2_x1555 | weak | 2 | $135 | inf |
| E260 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $68 | inf |
| E261 | causal1015_b3_rr2_x1555 | broad-liquidation | 4 | $-344 | 0.00 |
| E262 | causal1015_b3_rr2_x1555 | weak | 2 | $-187 | 0.00 |
| E263 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-19 | 0.90 |
| E264 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-355 | 0.00 |
| E265 | causal1015_b3_rr2_x1555 | weak | 1 | $-104 | 0.00 |
| E266 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-16 | 0.00 |
| E267 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-283 | 0.00 |
| E268 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-373 | 0.00 |
| E269 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-204 | 0.26 |
| E270 | causal1015_b3_rr2_x1555 | weak | 1 | $-4 | 0.00 |
| E271 | causal1015_b3_rr2_x1555 | weak | 2 | $-49 | 0.24 |
| E272 | causal1015_b3_rr2_x1555 | opening-selloff | 5 | $139 | 1.43 |
| E273 | causal1015_b3_rr2_x1555 | weak | 9 | $1,454 | 4.33 |
| E274 | causal1015_b3_rr2_x1555 | weak | 2 | $82 | 22.80 |
| E275 | causal1015_b3_rr2_x1555 | weak | 6 | $-1,043 | 0.00 |
| E276 | causal1015_b3_rr2_x1555 | weak | 2 | $-35 | 0.00 |
| E277 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $683 | inf |
| E278 | causal1015_b3_rr2_x1555 | weak | 6 | $-110 | 0.76 |
| E279 | causal1015_b3_rr2_x1555 | weak | 2 | $17 | 10.78 |
| E280 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 3 | $-259 | 0.00 |
| E281 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $14 | 11.90 |
| E282 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-30 | 0.00 |
| E283 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $553 | 3.09 |
| E284 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 6 | $1,162 | 9.69 |
| E285 | causal1015_b3_rr2_x1555 | opening-selloff | 2 | $-518 | 0.00 |
| E286 | causal1015_b3_rr2_x1555 | weak | 5 | $541 | 2.58 |
| E287 | causal1015_b3_rr2_x1555 | weak | 2 | $157 | inf |
| E288 | causal1015_b3_rr2_x1555 | weak | 6 | $1,806 | 9.57 |
| E289 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-1,273 | 0.00 |
| E290 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-291 | 0.00 |
| E291 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-307 | 0.35 |
| E292 | causal1015_b3_rr2_x1555 | broad-liquidation | 3 | $-477 | 0.00 |
| E293 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $169 | inf |
| E294 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 3 | $612 | 22.28 |
| E295 | causal1015_b3_rr2_x1555 | opening-selloff | 2 | $405 | inf |
| E296 | causal1015_b3_rr2_x1555 | weak | 10 | $552 | 2.59 |
| E297 | causal1015_b3_rr2_x1555 | broad-liquidation | 2 | $-765 | 0.00 |
| E298 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 4 | $-220 | 0.20 |
| E299 | causal1015_b3_rr2_x1555 | weak | 1 | $-46 | 0.00 |
| E300 | causal1015_b3_rr2_x1555 | weak | 2 | $384 | inf |
| E301 | causal1015_b3_rr2_x1555 | weak | 1 | $38 | inf |
| E302 | causal1015_b3_rr2_x1555 | weak | 3 | $-45 | 0.78 |
| E303 | causal1015_b3_rr2_x1555 | full-breadth-selloff | 2 | $-503 | 0.00 |
| E304 | causal1015_b3_rr2_x1555 | broad-liquidation | 3 | $-554 | 0.00 |

WFO concentration gate:

| total | best | without_best | best_share | final4 | positive | folds | pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| $2,076 | $1,806 | $270 | 0.87 | $-1,064 | 126 | 296 | False |

By year/instrument/subtype for `causal1015_b4_rr2_x1555`:

 year  trades         net        avg       pf
 2017      26   156.89900   6.034577 1.404952
 2018     112  1501.72875  13.408292 1.280553
 2019     116  -694.57650  -5.987728 0.827699
 2020      76   162.63125   2.139885 1.027966
 2021      72 -1033.10225 -14.348642 0.817229
 2022     108  2910.53000  26.949352 1.331439
 2023      74  -677.77900  -9.159176 0.851992
 2024      87 -1097.76800 -12.618023 0.877409

inst  trades        net       avg       pf
 MES     344 -341.20125 -0.991864 0.981255
 MNQ     327 1569.76450  4.800503 1.061918

       event_subtype  trades         net       avg       pf
   broad-liquidation     207 -1231.67150 -5.950104 0.937933
full-breadth-selloff     464  2460.23475  5.302230 1.103762

By year/instrument/subtype for `causal1015_b4_wide3_rr2_x1555`:

 year  trades         net        avg       pf
 2018      30  -611.09075 -20.369692 0.784789
 2019      14  -230.47800 -16.462714 0.634323
 2020      42  -490.74975 -11.684518 0.881377
 2021      22 -1342.84100 -61.038227 0.516784
 2022      72   955.64075  13.272788 1.151438
 2023       8   370.70025  46.337531 2.032276
 2024      19   117.14700   6.165632 1.042005

inst  trades        net        avg       pf
 MES     112 -1185.8825 -10.588237 0.869251
 MNQ      95   -45.7890  -0.481989 0.995750

    event_subtype  trades        net       avg       pf
broad-liquidation     207 -1231.6715 -5.950104 0.937933

By year/instrument/subtype for `causal1015_b4_rr15_x1400`:

 year  trades          net        avg       pf
 2017      26   -53.896000  -2.072923 0.857963
 2018     112   345.095250   3.081208 1.070164
 2019     116  -267.670375  -2.307503 0.922493
 2020      76   651.285500   8.569546 1.138659
 2021      72 -1214.019625 -16.861384 0.764707
 2022     108  1405.660000  13.015370 1.183774
 2023      74  -871.976500 -11.783466 0.777060
 2024      87  -781.594625  -8.983846 0.888168

inst  trades          net       avg       pf
 MES     344 -1807.953125 -5.255678 0.884405
 MNQ     327  1020.836750  3.121825 1.047444

       event_subtype  trades          net        avg       pf
   broad-liquidation     207 -2693.166500 -13.010466 0.846133
full-breadth-selloff     464  1906.050125   4.107867 1.096981

By year/instrument/subtype for `causal1015_b4_mnq_rr2_x1555`:

 year  trades       net        avg       pf
 2017      13   86.1390   6.626077 1.385995
 2018      56  717.3225  12.809330 1.238430
 2019      58 -204.8490  -3.531879 0.905089
 2020      38 -188.7475  -4.967039 0.949517
 2021      34 -266.7160  -7.844588 0.915258
 2022      49 2010.3925  41.028418 1.422472
 2023      37 -471.7065 -12.748824 0.840909
 2024      42 -112.0705  -2.668345 0.979062

inst  trades       net      avg       pf
 MNQ     327 1569.7645 4.800503 1.061918

       event_subtype  trades       net       avg       pf
   broad-liquidation      95  -45.7890 -0.481989 0.995750
full-breadth-selloff     232 1615.5535  6.963593 1.110821

By year/instrument/subtype for `causal1015_b3_rr2_x1555`:

 year  trades         net        avg       pf
 2017      67    20.71100   0.309119 1.020633
 2018     170  1234.40850   7.261226 1.168261
 2019     160 -1678.17550 -10.488597 0.702478
 2020     107   413.11475   3.860886 1.055094
 2021     135  -430.15575  -3.186339 0.948928
 2022     177  8108.88600  45.812915 1.630855
 2023     143  -862.77475  -6.033390 0.900445
 2024     140   421.09425   3.007816 1.036629

inst  trades       net       avg       pf
 MES     599 1002.7625  1.674061 1.036407
 MNQ     500 6224.3460 12.448692 1.175954

       event_subtype  trades         net        avg       pf
   broad-liquidation     207 -1231.67150  -5.950104 0.937933
full-breadth-selloff     464  2460.23475   5.302230 1.103762
     opening-selloff      85   876.42375  10.310868 1.184165
                weak     328  2754.25900   8.397131 1.203474
           wide-chop      15  2367.86250 157.857500 3.217304

## Verdict

Read the floor WFO gate plus OOS/slippage/overlap together. A standalone
positive row is not enough for this branch.
