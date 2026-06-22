## Task: Strategy Exploration — find next additive opportunity
Status: IN PROGRESS

### Completed
- [x] Remove ORB_FADE from engine.py → +$330
- [x] RS Momentum — 10 rounds tested, DEFERRED
- [x] Gap Fill — implemented into engine.py (23t, +$2,838 sim, Normal regime only)
- [x] Calm afternoon diagnostic — NO edge found (52 days, 71% in 2021, no directional bias)
- [x] VWAP_MR root cause investigation — see Key Decisions below

### In progress
- [ ] Find next opportunity (new strategy slot or existing strategy improvement)

### Next steps
- [ ] STRESS_MID: implement in engine (new strategy, edge confirmed in sim)
- [ ] GAP_FILL discrepancy: debug sim +$2,838 vs engine -$61
- [ ] ORB 2022: test SPY-alignment direction filter (WR=26%, -$1,574 in 2022)
- [ ] STRESS_ORB_STK: sim +$5,581 p=0.030 but engine -$2,528 — needs isolated root cause analysis (sim vs engine discrepancy)

### Key decisions
- Gap Fill: LONG only, gap 1.5-3% down, retrace ≥50%, Normal regime, target fill+50%
- Calm afternoon: no edge — 52 days too few, no directional bias, stock MR rate 34.5%
- VWAP_MR F2+F3 filters: available but NOT implemented — see SCRATCHPAD for detail
- RS SHORT deferred: 2021-driven (130% P&L from 2021), 2020 negative

### Expected system (sim estimates, backtest chưa chạy lại)
- Total: +$12,216 | 2020=+$3,050 | 2021=+$6,645 | 2022=+$2,521
- TREND_FOLLOW: 275t +$8,073 | Gap Fill: 23t +$2,838 | FADE: 182t +$1,064
- ORB: 59t +$369 | VWAP_MR: 267t -$128

### Files touched
raits/backtest/engine.py, raits/raits/scripts/gap_fill_*.py,
raits/raits/scripts/vmr_*.py, raits/raits/scripts/calm_afternoon_diagnostic.py,
raits/raits/scripts/vmr_root_cause.py, raits/raits/scripts/vmr_filter_sim.py
