# RS Momentum Diagnostic Results Log
## Context: Normal regime midday (10:15–14:00), 30-ticker universe, 107 Normal days (2020-2022)

---

## Round 1 — Original sim (`midday_gap_rs_sim.py`)
- Mixed VWAP touch + direct entry fallback, alpha≥0.8%
- **93t, +$10,465, WR=55%**
- Root cause of inflated result: "direct" trades retroactively classified (not real-time)

## Round 2 — Diagnostic (`rs_momentum_diagnostic.py`)
- Tách direct vs VWAP touch
- Direct (retroactive): 39t, +$10,905, WR=67%
- VWAP touch: 54t, -$439, WR=46%
- **BUG**: `bars_after = window[...]` bounded by 12:30 → TIME_STOP thực = 12:25, không phải 13:30

## Round 3 — Final filter (`rs_final_filter.py`)
- Direct entry thực sự tại 10:35, alpha≥1.5%, exit 13:30
- **90t, -$6,735, WR=36%, STOP_HIT=74%**

## Round 4 — VWAP distance grid (`rs_vwap_distance.py`)
| Threshold | n | P&L |
|---|---|---|
| Always direct | 106t | -$6,577 |
| >0.5×ATR direct | worse | — |
| >1.0×ATR direct | worse | — |
| Always wait (touch only) | 46t | **-$643** ← best |

## Round 5 — VWAP touch + confirmation (`rs_vwap_confirm.py`)
| Filter | n | P&L | STOP% |
|---|---|---|---|
| Close confirm only | 45t | -$1,665 | 53% |
| + vol<0.8×avg | 41t | -$719 | 41% |
| + vol<1.0×avg | 42t | -$728 | 48% |
| + vol<1.5×avg | 44t | -$1,967 | 52% |

## Round 6 — Exit time grid (`rs_clean_test.py`)
- Hypothesis: original sim exit ở 12:30 implicit → test explicit
| Exit | n | P&L |
|---|---|---|
| 11:30 | 106t | -$8,998 |
| 12:00 | 106t | -$4,179 |
| 12:30 | 106t | -$6,007 |
| 13:30 | 106t | -$6,577 |
- **Kết luận: exit time không giải thích được original +$10,465**

## Round 7 — Continuation breakout (`rs_breakout_sim.py`)
- Enter khi stock break above 10:30 high (LONG) / below 10:30 low (SHORT)
| Config | n | P&L |
|---|---|---|
| alpha≥0.8% exit 12:30 | 101t | -$5,480 |
| alpha≥1.5% exit 12:30 | 84t | -$3,223 |
| **alpha≥2.0% exit 12:30** | **53t** | **+$235** ← first positive |

## Round 8 — SHORT only + immediate (`rs_short_only.py`)
- alpha≥2.0%, exit 12:30, direction × immediate filter
| Config | n | P&L | 2020 | 2021 | 2022 |
|---|---|---|---|---|---|
| BOTH, any time | 53t | +$235 | -$1,450 | +$2,537 | -$853 |
| BOTH, 10:35 only | 33t | +$1,888 | -$278 | +$2,389 | -$222 |
| **SHORT, any time** | **26t** | **+$2,932** | -$1,002 | +$3,801 | +$133 |
| SHORT, 10:35 only | 18t | +$3,155 | -$114 | +$3,329 | -$60 |
| LONG, any time | 27t | -$2,697 | âm cả 3 năm | | |

## Round 9 — Full grid (`rs_full_grid.py`)
- Grid: RVOL × Profit Target × Stop × Direction
- RVOL >1.2x: collapse signals về 5 trades
- RVOL >1.5x: 1 trade — không viable
- Tighter stop 1.0×ATR: STOP_HIT tăng từ 42% → 77%, tệ hơn nhiều
- Profit target: không thay đổi đáng kể

## Round 10 — Alpha window × Breakeven stop (`rs_alpha_window.py`)
| Config | n | P&L |
|---|---|---|
| 9:30→10:30, no BE | 15t | +$833 |
| 9:30→10:30, BE=yes | 15t | -$643 ← worse |
| 9:30→10:00 (early) | 4t | +$600 (too sparse) |
| 9:45→10:30 (no-gap) | 1t | -$246 (collapsed) |
- Breakeven stop làm WR giảm từ 47% → 13% (BE triggers on noise, kills winners)

---

## Pattern nhất quán xuyên suốt:
- TIME_STOP luôn profitable: WR=68-86%, +$4k-5k
- STOP_HIT luôn catastrophic: WR=0-16%, -$2k-7k
- Không có filter nào phân biệt được 2 nhóm tại entry

## Root cause:
30-ticker universe quá nhỏ cho RS strategy. ~8-9 SHORT signals/năm không đủ statistical significance.

## Best implementable config:
**SHORT only, alpha≥2.0%, breakout 10:30 low, exit 12:30, stop=1.5×ATR**
- 26t, +$2,932, WR=42%
- 2020: -$1,002 (7t), 2021: +$3,801 (11t), 2022: +$133 (8t)
- STOP_HIT: 11t, -$2,681, WR=9%
- TIME_STOP: 15t, +$5,613, WR=67%
- **Decision: DEFERRED** — comparable to FADE's year distribution, but 7× fewer trades

## Comparison with FADE (current system):
| | FADE | RS SHORT |
|---|---|---|
| 3yr P&L | +$1,064 | +$2,932 |
| Trades | 182t | 26t |
| 2020 | -$252 | -$1,002 |
| 2021 | +$1,618 | +$3,801 |
| 2022 | -$302 | +$133 |
| Regime | Calm | Normal |
