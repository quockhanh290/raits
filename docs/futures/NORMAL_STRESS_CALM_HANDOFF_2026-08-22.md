# Normal / Stress / Calm Handoff - 2026-08-22

Use this as the session-start memory for the current futures strategy research thread.

> **Read the last section first.** Calm-NKD was regenerated on the current sleeve's basis and
> **failed** (negative in-sample across every ema, one positive year in seven). Track 2 is closed
> and the stack below is Track 1. The committed stack is Track 1 — see *Calm-NKD Regeneration*
> at the end of this document.
>
> Calm-NKD was then re-opened as a standalone tight-stop strategy and **rejected again**, this
> time because 290 of 471 stop exits are booked at prices the market had already passed. See
> *Calm-NKD Tight-Stop as a Standalone Strategy* at the end.
>
> Calm-NKD was tested one more time with widened stops and live-stop semantics. That also
> **failed**: the only row positive on floor and 2025 was `daily_atr 1.0 / ema20`, with floor
> PF 1.19 / Calmar 0.28, 2025 +$544 / PF 1.10, and 2026 sanity -$1,111. Calm-NKD is closed.

## Repo / Scope

- Workspace: `D:\raits`
- Production code should not be modified unless explicitly requested.
- Recent work is scratch/report only.
- Main candidate doc:
  - `docs/futures/NORMAL_STRESS_CANDIDATES_2026-08-22.md`
- Main longitudinal research doc:
  - `docs/futures/TF_REGIME_RESEARCH_2026-08-20.md`

## Current Best Research/Paper Stack

```text
Account: $50,000

Normal-R4 filtered:
  Instruments: MES, MNQ, MYM, M2K
  Qty: 1 micro
  Cap: 5.0% gross / 4.4% net

Stress-MNQ:
  Variant: mnq_only_g3_q7
  Instrument: MNQ
  Qty: 7 MNQ micros
  Cap: 10.0% gross-only
  Switch: close same-symbol Normal MNQ only after Stress passes cap/breaker

Current NKD/MNKD:
  Instrument: MNKD
  Qty: 1
  Cap: 6.0% gross / 6.0% net

Calm A PCLoc:
  Gate: D-1 Calm causal
  Instruments: MES/MNQ
  Direction: LONG
  Entry: 10:00 ET open
  Exit: 15:55 ET open
  Disaster stop: entry - 1.5x daily ATR
  Overlap: skip same-symbol if Normal/Stress already open
  Cap: 5.0% gross using true ATR15 stop-risk
```

Status after stop/risk audit + repaired replay: **mechanical replay blockers repaired in scratch, but
the stack is not fully stop/risk-clean if Calm-NKD switch is included**. Do not move the full stack
to production audit until Calm-NKD is regenerated with true stop-at-entry risk.

## Latest Combined Result Shape

The most recent stack evolved in stages:

1. `R4 + Stress + current NKD`
2. add `Calm-NKD switch`
3. add `Calm A PCLoc` with skip same-symbol
4. add Calm A disaster stop `ATR15`

Key measured rows:

- Current NKD + Calm-NKD switch:
  - floor: +$64,094, PF 1.64, Sharpe 1.93, Calmar 1.74, MaxDD $5,274
  - 2025: +$16,166, PF 2.23, Sharpe 2.70, Calmar 4.07, MaxDD $4,057
  - 2026 sanity: +$8,926, PF 1.65, Sharpe 2.58, Calmar 3.37, MaxDD $4,342

- Add Calm A no-stop, cap 5%, skip same-symbol:
  - floor: +$72,732, PF 1.65, Sharpe 2.06, Calmar 2.11, MaxDD $4,923
  - 2025: +$17,881, PF 2.32, Sharpe 2.85, Calmar 4.63, MaxDD $3,943
  - 2026 sanity: +$10,132, PF 1.72, Sharpe 2.77, Calmar 3.72, MaxDD $4,342

- Calm A with disaster stop `entry - 1.5x daily ATR`, cap 5%, skip same-symbol:
  - floor combined: +$73,599, PF 1.66, Sharpe 2.08, Calmar 2.14, MaxDD $4,923
  - 2025 combined: +$18,093, PF 2.33, Sharpe 2.88, Calmar 4.74, MaxDD $3,896
  - 2026 combined: +$9,779, PF 1.65, Sharpe 2.57, Calmar 3.59, MaxDD $4,342

## Important Caveats

- Stop/risk audit is complete and failed the combined stack as risk-clean.
- Normal-R4 and Stress-MNQ were confirmed clean on stop/risk.
- The blockers are:
  - Calm A same-symbol switch bug: Stress closes a Calm A same-symbol position but leaves it open, causing double settlement and real Calm-long/Stress-short overlap.
  - Calm A skip rule is one-directional: Normal-R4 can still open into an existing Calm A position.
  - Calm-NKD switch forced closes were priced across two NKD price scales in prior replay.
  - Calm-NKD declared risk is about 40x true 5-minute chandelier stop risk, so the 6% cluster cap never binds meaningfully.
  - Calm cluster and Normal cluster both use MES/MNQ in the same session but are capped independently; combined same-symbol/index-family exposure is not checked.
- 2026 is sanity only; do not select/tune on 2026.
- Stress OOS sample is sparse:
  - 2025: 3 Stress MNQ legs
  - 2026: 4 Stress MNQ legs, 3 accepted at cap 10%
- Stress is not a same-day daily `Stress` regime sleeve. It is an intraday stress-behavior detector.
- Candidate A had selection-history concerns in Calm research. Even with ATR15 stop, it remains paper/shadow until an untouched paper window exists.
- Candidate A cap was previously ATR proxy because no stop; this has been addressed by testing `entry - 1.5x daily ATR`.
- Calm-NKD switch is not pure replacement. It is current NKD plus Calm-NKD override/add with suppression on overlap.
- Single cap for Normal+Stress was rejected. Keep split caps.
- NKD qty 2 was rejected for now due worse DD/cap sensitivity.

## Key Scratch Artifacts

Stress / Normal / NKD:

- `scratch/stress_switch_full_replay_20260822.py`
- `scratch/stress_switch_full_replay_20260822_report.md`
- `scratch/stress_single_cap_probe_20260822.py`
- `scratch/stress_single_cap_probe_20260822_report.md`
- `scratch/stress_with_nkd_probe_20260822.py`
- `scratch/stress_with_nkd_probe_20260822_report.md`
- `scratch/stress_nkd_size_cap_sweep_20260822.py`
- `scratch/stress_nkd_size_cap_sweep_20260822_report.md`

Calm:

- `scratch/combined_stop_risk_audit_20260822.py`
- `scratch/combined_stop_risk_audit_20260822_report.md`
- `scratch/combined_nkd_offset_correction_20260822.py`
- `scratch/combined_maxhold_stop_order_probe_20260822.py`
- `scratch/combined_unarmed_window_probe_20260822.py`
- `scratch/calm_nkd_switch_vs_current_20260822.py`
- `scratch/calm_nkd_switch_vs_current_20260822_report.md`
- `scratch/calm_a_combined_replay_20260822.py`
- `scratch/calm_a_combined_replay_20260822_report.md`
- `scratch/calm_a_disaster_stop_probe_20260822.py`
- `scratch/calm_a_disaster_stop_probe_20260822_report.md`

Trade artifacts:

- `scratch/normal_promotion_trades_floor_20260821.json`
- `scratch/normal_promotion_trades_vault2025_20260821.json`
- `scratch/normal_promotion_trades_vault2026_20260821.json`
- `scratch/calm_nkd_swing_calm_only_trades.csv`
- `scratch/calm_pcloc_not_deep_gap_trade_list.csv`

## Repaired Replay - 2026-08-22

Scratch artifacts:

- `scratch/combined_repaired_replay_20260822.py`
- `scratch/combined_repaired_replay_20260822_report.md`
- `scratch/combined_repaired_replay_20260822.json`

Repairs applied in the scratch replay:

1. Stress same-symbol override removes both Normal-R4 and Calm A from survivors before admission.
2. Normal-R4 is suppressed if same-symbol Calm A or Stress is already open.
3. Calm-NKD forced close is repriced onto the current-NKD artifact price scale using measured offsets.
4. Calm A uses ATR15 disaster-stop trades and true stop-risk.
5. Optional aggregate Normal+Calm family cap was measured at 5.0%/4.4% and 7.5%/7.5%.

Mechanical blockers are fixed in replay:

- `double_booked = 0` in all windows.
- Stress closed Calm A same-symbol positions without leaving them open.
- Normal-R4 no longer opens same-symbol into existing Calm A/Stress.
- Calm-NKD forced-close PnL uses the corrected basis.

Best repaired-mechanics rows including Calm-NKD switch:

| Window | Policy | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|
| floor | family cap 5.0%/4.4% | +$74,410 | 1.67 | 2.12 | 2.14 | $4,973 |
| 2025 | family cap 5.0%/4.4% | +$16,997 | 2.26 | 2.76 | 4.45 | $3,901 |
| 2026 sanity | family cap 5.0%/4.4% | +$9,288 | 1.62 | 2.47 | 3.41 | $4,342 |

Risk-clean fallback dropping Calm-NKD switch:

| Window | Policy | Net | PF | Sharpe | Calmar | MaxDD |
|---|---|---:|---:|---:|---:|---:|
| floor | no Calm-NKD, family cap 5.0%/4.4% | +$64,903 | 1.62 | 2.34 | 1.92 | $4,845 |
| 2025 | no Calm-NKD, family cap 5.0%/4.4% | +$13,236 | 2.00 | 2.96 | 3.09 | $4,632 |
| 2026 sanity | no Calm-NKD, family cap 5.0%/4.4% | +$8,260 | 1.55 | 2.57 | 2.75 | $4,797 |

Interpretation:

- The repaired full stack still looks strong, but it remains research-only because Calm-NKD's risk
  definition is unresolved.
- The risk-clean fallback is weaker but closer to a production-audit input because it removes the
  unresolved Calm-NKD switch.
- Family cap 5.0%/4.4% is the conservative default. Family cap 7.5%/7.5% admits more Calm A and is
  slightly better in floor/2026, but it loosens shared MES/MNQ exposure.

## Next Gate

Do **not** run production feasibility audit for the full stack with Calm-NKD switch yet.

Next choices:

1. **Risk-clean path:** carry forward `Normal-R4 + Stress-MNQ + current NKD + Calm A ATR15`,
   with bidirectional same-symbol skip and Normal+Calm family cap 5.0%/4.4%.
2. **Upside path:** regenerate Calm-NKD from signal path with true stop-at-entry risk, then rerun
   the repaired combined replay and stop/risk audit.

Only after one of those paths passes should the session move to production feasibility audit.

---

## Calm-NKD Regeneration — resolved 2026-08-22, Track 2 CLOSED

Full detail: `scratch/calm_nkd_regen_same_basis_20260822_report.md`.

Calm-NKD was regenerated on the current sleeve's basis: the frozen NKD file named in each window's
own arguments, ema 10 / mult 2.5, and the fixed stop at entry ± 2.0 × daily ATR armed the next
session — i.e. true stop-at-entry risk. Anchor gate: with the current sleeve's regime labels the
harness must reproduce the artifact's MNKD book exactly.

**Anchor passed in all three windows** — 228 / $3,898.30, 31 / $2,203.04, 26 / $4,292.17, matching
every trade's price, exit reason and P&L. It failed twice first; getting onto the artifact's basis
needed four settings, not two. Two of them (`allowed_regimes` forced to `["Normal"]`, and the SPY
short gate) are applied globally by the artifact generator, read as Ro-4 concerns, and are documented
nowhere in the NKD sleeve's own configuration — yet they reach it.

### Result: fail

| ema | floor 2018-2024 | 2025 | 2026 sanity |
|---:|---:|---:|---:|
| 5 | **−$509** | +$2,556 | +$3,399 |
| 10 | **−$3,556** | +$2,778 | +$1,765 |
| 15 | **−$1,545** | +$2,948 | +$1,330 |
| 20 | **−$1,963** | +$3,416 | +$266 |

Every ema is negative in-sample. At the sleeve's own ema of 10: 205 trades, PF 0.85, win rate 45.9%,
and **one positive year out of seven** (2023 +$1,153; 2018/19/20/21/22/24 all negative).

Stop distance verified at exactly 2.0 × daily ATR on every stop exit, so the risk model half of the
ask succeeded. It is the edge that is not there once the risk model is honest.

`chandelier_atr_mult` is **inert** on this basis — mult 2.0, 2.5 and 3.0 give byte-identical trade
lists in all three windows, because the stop comes from `stop_basis` and the ratchet is off. The old
six-variant grid collapses to ema alone; three of the six were the same run.

### Where the old +$7,156 came from

The two sleeves are genuinely complementary, not redundant: on floor the current sleeve takes 228
entries, every one on a D-1 Normal day, and Calm-NKD takes 205, every one on a D-1 Calm day —
**intersection zero**. The design intent was sound. But the edge on those days was never the Calm
gate; it was the stop. The original variant's 2.5 × five-minute-ATR ratcheting chandelier gave a
median stop 23 index points wide — 4.6 ticks, $11.52 — stopping out 87% of trades at roughly the
round-turn cost and letting the other 13% run. Swap in the sleeve's real stop and the win rate goes
12.9% → 45.9% and floor net goes +$7,156 → −$3,556.

### Decision

Per the rule set before the run: **fail → Track 2 closed, commit to Track 1.**

```text
Normal-R4 filtered qty 1
Stress-MNQ mnq_only_g3_q7 qty 7, cap 10%
Current NKD/MNKD qty 1, cap 6%          (no Calm-NKD switch)
Calm A PCLoc MES/MNQ, ATR15 disaster stop, true stop-risk
Bidirectional same-symbol skip; Stress force-closes same-symbol Calm A
Normal+Calm family cap 5.0% gross / 4.4% net
```

| Window | Net | PF | Sharpe | Calmar | MaxDD |
|---|---:|---:|---:|---:|---:|
| floor 2018-2024 | +$64,903 | 1.62 | 2.34 | 1.92 | $4,845 |
| 2025 | +$13,236 | 2.00 | 2.96 | 3.09 | $4,632 |
| 2026 sanity | +$8,260 | 1.55 | 2.57 | 2.75 | $4,797 |

Item 4 of the repair status table (Calm-NKD declared risk ≈ 40× true stop risk) is now **resolved by
removal**: the sleeve is dropped, not fixed. Items 6, 9 and 10 remain open and sit below the replay.

### Correction to the Stop / Risk Audit above

Section 3 of that audit concluded **"the gap-through fix is a no-op on this trade set."** That was
wrong. The post-hoc correction was switched off because a *stronger implementation of the same law
was already on* one layer down: the artifact generator marks every bar gap-eligible, so any stop the
market opened beyond is relabelled a gap exit and filled at that bar's open. My check scanned stop
exits asking whether the bar had already opened through the stop — and every such case had already
been converted before the scan saw it. **The check could not have gone red.** I printed its funnel as
evidence that the zero was real; the funnel measured the residual after the fix, not the absence of
the problem.

The direction reverses: the artifacts are **more** conservative on stop fills than the production
engine, which only fills at the open after a real time break of more than fifteen minutes. Measured
on the NKD sleeve by running the anchored configuration both ways — floor **−$5.36** (4 exits
relabelled), 2025 **$0.00**, 2026 **−$3.21** (1 exit). The Ro-4 side carries one gap exit on floor
and one in 2026, not separately priced.

The finding that mattered still stands — no stop in the candidate book is filled at a price the
market had already passed — but it stands because the conservative law was applied, not because the
situation never arises.

---

## Calm-NKD Tight-Stop as a Standalone Strategy — REJECTED 2026-08-22

Full detail: `scratch/calm_nkd_tight_stop_audit_20260822_report.md`.

The previous rejection only killed Calm-NKD as a same-risk-model replacement for the current NKD
sleeve. This audit re-opened it as a strategy in its own right, on its own tight 5-minute chandelier
stop, with no requirement to match the current sleeve. It was tested on its own terms and **fails on
measurement**.

**Anchor passed exactly** — all six original variants rebuilt trade-for-trade in all three windows,
including the headline `ema5_mult2.5` floor book of 550 trades / **+$7,156** / PF 1.55.

### Why it is rejected: the edge is impossible fills, not tail capture

The engine checks a carried position's stop **once per calendar day**, at the start of that day's bar
group. For a Tokyo-timezone frame that boundary is **midnight JST — the middle of a continuously
trading session**. A position entered at 14:00–15:55 JST is not stop-checked again for eight to ten
hours. By then price has usually walked past a 22-point stop; because the market never stopped
trading, no time break precedes that bar, the gap-fill rule does not engage, and the engine books
the exit **at the stop price nobody could have got**.

- **290 of 471** stop exits on floor are booked at a price the bar had already opened beyond, worth
  **$13,297** — against a total net of $7,156. 248 of them land at 00:00–00:01 JST, and 228 have a
  previous bar exactly one minute earlier.
- Worked case: 2018-03-23, bar range 20,150–20,165, exit booked at **20,463.2** — 313 points outside
  the bar.

Three independent measurements agree, two of them to the dollar:

| | floor ema5 |
|---|---|
| impossible-fill benefit measured directly | **$13,297** |
| rerun with the fill made possible: net moves | +$7,156 → **−$6,141** (delta **−$13,297**) |
| trades whose adverse move exceeded their own stop | **519 of 550 (94%)**, median 3.62× the stop |

With possible fills, **every ema is negative on floor and on 2025**: floor −$6,141 / −$11,737 /
−$9,833 / −$8,860; 2025 −$1,545 / −$2,381 / −$2,668 / −$3,429. PF 0.53–0.77.

### The other pre-stated rejection tests

- **Slippage** (on the as-shipped book): floor net −17% at +1 stop tick, −33% at +2, −50% at +3.
- **Concentration**: top five trades = 53.7% of floor net; 2021 alone = 48.9%. In 2025 the top five
  winners exceed the entire net.
- **Cap**: median true risk $11.30 against a $3,000 budget, and the engine holds at most one position
  at a time. The cap cannot bind at any minimum charge up to $300; making it bind would need roughly
  $3,000 per trade — 265× true risk, with no derivation behind it.
- **Plateau**: ema5 is the top floor cell and its neighbour ema10 returns 49% of it, so the ±30%
  neighbour rule is not met. Rankings also reorder across all three windows.

Portfolio integration was **not run** — the specification gates it on the standalone passing.

### What this also settles

The old comparison that made Calm-NKD look better than the current sleeve was never like-for-like on
the fill law either: the current sleeve's artifact was generated with every bar treated as
gap-eligible, and the Calm-NKD probe was not. That difference alone is worth $13,297 on floor.

### If anyone wants to revisit tight-stop NKD

The obstacle is structural, not a parameter. Any stop tighter than the typical eight-to-ten-hour move
between the Tokyo afternoon entry and midnight JST **cannot be evaluated by this code path at all**.
A same-session stop harness exists (`model_sameday_stop.run_loop` with `same_day_stop=True`) which
makes the stop live from the fill; that is the only path that could measure it honestly. No promise
that it would pass — the single row that survives possible fills is 2026 ema10 on 40 trades, and
2026 is a sanity window.

**Committed stack is unchanged — Track 1:** Normal-R4 filtered qty 1 · Stress-MNQ `mnq_only_g3_q7`
qty 7 cap 10% · current NKD/MNKD qty 1 cap 6% · Calm A PCLoc MES/MNQ with the ATR15 disaster stop and
true stop-risk · bidirectional same-symbol skip with Stress force-closing same-symbol Calm A ·
Normal+Calm family cap 5.0% gross / 4.4% net.

---

## Track 1 — Production Feasibility Audit — 2026-08-22

Full detail: `scratch/track1_production_feasibility_audit_20260822_report.md`.

### Verdict: **BLOCKED PENDING PATCH** — measurement passes, wiring does not

Gate first: the instrumented replay reproduces Track 1 to the cent in all three windows
($64,902.91 / $4,845.31 · $13,236.11 / $4,631.53 · $8,259.85 / $4,797.44), and the event counts close
against the sleeve tallies without slack.

**Nothing in this audit found a new measurement blocker.** On the evidence Track 1 is a legitimate
production patch candidate. What blocks it is that the patch is bigger than expected.

### The finding that changes the plan

The expectation was that Calm A, Stress and the switch are not wired. True. But **Normal-R4 — the
largest contributor — is also not what production runs today**:

| | Track 1 | production today |
|---|---|---|
| EMA | 50 | **30** (`futures/basket.py: SWING_TF_PARAM`) |
| Stop | entry ± **2.0 × daily ATR**, fixed | **engine chandelier** (2.5 × 5-minute ATR at entry, daily-ATR trail) |
| Ratchet | off | **on** |
| Arm time | 14:05 | **14:00** |
| Cap risk convention | 2.5 × daily ATR × pv | same ✓ |
| R4 context filter, SPY short filter | required | **do not exist** |

`run_live_day.py` builds `SwingTFEngine()` with defaults; no config reaches it. Nothing in production
imports `model_sameday_stop` or `scratch.harness`. So Track 1 is **not** an additive patch — it changes
a sleeve that is already sending orders, and that deserves its own before/after gate rather than
riding in on a Track 1 patch.

### Signal-path regeneration — reproduced byte for byte

`normal_promotion_regen_audit` (which drives `deploy_sim.main()` end to end) was re-run from scratch.
All three promotion artifacts reproduced with **matching sha256**, and the script's own internal
anchors passed in every window ($33,176 / $6,857 / $6,743). That script overwrites those shared files
in place, so they were snapshotted first, this audit was pointed at the untouched snapshot, and the
originals were restored — the shared files end the session exactly as they began. **No reproduction
mismatch to attribute.**

### Measurement results — all clean

- **Fill audit, all four sleeves, all three windows**: 0 outside-entry-bar, 0 outside-exit-bar,
  0 signal-after-entry, 0 same-bar exit, **0 impossible stop fills**. (Two missing lookups: the two
  Calm A legs on 2026-08-19, a data-clip boundary.) This is the same test that killed the Calm-NKD
  tight-stop candidate at 290 of 471 exits; Track 1 has zero.
- **Settlement exact**: floor 1,160 entered / 1,160 settled, 0 twice, 0 never. Same in 2025 (128/128)
  and 2026 (91/91).
- **Position invariants**: 0 violations — no same-symbol stack, no opposite-direction overlap, at any
  instant, re-checked after every entry and every force-close.
- **Cap admission tested before any close**: a rejected Stress performs no force-close. One such
  rejection on floor, one in 2026.
- **Item 9 (14:00 vs 14:05) closes at exactly zero.** For every Track 1 swing position, the stop was
  never touched inside the 14:00–14:05 window, in any window. The five-minute discrepancy carries no
  measurement debt; fix it when the artifacts are next regenerated.
- **Item 6 (max-hold pre-empts the armed stop)**: 4 events on floor, **−$423.54**, 0 in 2025/2026.
  Conservative direction.
- **Item 10 (5-minute timestamp)**: 0 cases on floor, 0 in 2026, **2 in 2025** — a MYM swing entry
  stamped 15:50 (filling 15:55) against two Calm A exits at 15:55 on 2025-08-04. Replay is the
  conservative side. Harmless today; becomes a real defect if any future sleeve trades 14:00–15:55.

### Switch shape, measured

| Window | force-closes | victims | instrument | booked P&L on forced legs | suppressions | breaker halts |
|---|---:|---|---|---:|---:|---:|
| floor | **14** | 10 Normal-R4, 4 Calm A | all MNQ | −$6,072.36 | 22 | 2 |
| 2025 | **1** | 1 Normal-R4 | MNQ | −$1,744.24 | 4 | 0 |
| 2026 | 0 | — | — | — | 1 | 0 |

Roughly two switches a year, every one on MNQ.

### Caps

Carried peaks against cap: family 4.90/4.89% vs 5.0/4.4 (floor), Stress 8.36–8.54% vs 10,
NKD 4.21% floor but **5.92% in 2026 against a 6% cap** — within 0.08 points, with 2 rejections. The
NKD module's own docstring already flags that at 2026 Nikkei volatility the 6% cap clears by only
~5%; Track 1 inherits that.

**The family cap is an admission gate, not a maintained limit.** No family entry was ever admitted
above cap — admission-time family net peak on floor is exactly 4.40% against 4.4%. Carried net drifts
to 4.89% on 7 occasions, five straight after a family position exits. Not introduced by the family
cap; every cluster budget in the guard behaves this way.

### Wiring — the blockers

1. `roska4_calm` does not exist anywhere; the guard has **no family/aggregate concept at all**, and
   the family cap is what holds the shared MES/MNQ tail from 6.86–7.82% down to under 5%.
2. Calm A signal, Stress intraday detector, R4 context filter and SPY short filter: **none exist**.
3. **Close-confirm-then-enter exists but only inside the contract-roll path**
   (`ibkr_broker._handle_rollover`: close → poll to done against a 120s deadline → verify fill → open
   against a 30s deadline → abort untouched on failure). Worst case 150s, comfortably inside the
   10:35–12:30 Stress window. But it is bound to same-instrument, same-direction, same-size, identity
   preserved — while a Stress switch flips direction, changes size 1→7, and crosses clusters.
4. **Stop-cancel ordering is backwards in the one force-close path that exists.**
   `run_maxhold_exit` sends the CLOSE first and cancels the stop after. For a 09:30 max-hold exit that
   window is usually harmless. For the Stress switch it is not: the detector fires precisely when all
   four instruments are below open and VWAP and gapping down — the exact conditions under which a
   resting sell-stop beneath a Normal MNQ long is most likely to fire, opening a fresh short on top of
   the seven-lot Stress short being entered.
5. **No continuous-monitor execution shape.** Track 1 needs three new slots (10:00 Calm A entry,
   15:55 Calm A and Stress exits) **plus a monitor from 10:35 to 12:30** for the Stress entry, which
   fires on a low break at an unknown minute. Every existing slot is one-shot.
6. **No telemetry for any of it.** `FORCE_CLOSE`, `CANCEL_STOP`, `AWAIT_CLOSE_CONFIRM`, `SUPPRESS`,
   and a `family_cap` reject reason have no counterpart in the runner. A live switch would appear as
   an unlinked close and entry, and a suppressed entry as nothing at all.

Files that would need patching: `net_exposure_multi.py`, `runner.py`, `signal_layer.py`,
`run_scheduler.py`, `ibkr_broker.py`, `deploy_sim.py`, plus new modules for the two signals, plus the
Normal-R4 sleeve parameters themselves.

### Recommended sequencing — cheapest risk first

1. Land the guard's family-cap concept and the switch telemetry **before** any new sleeve.
2. Generalise the roll's close-confirm primitive and fix the cancel-before-close ordering — both are
   wanted regardless of Track 1.
3. Treat the Normal-R4 parameter change as a **separate, individually gated** change.
4. Wire Calm A before Stress: Calm A is a single-shot 10:00 entry that fits the existing slot shape;
   Stress needs the continuous monitor that does not exist.

Until at least the first three land, Track 1 is **paper/shadow only**.

---

## Gate — instrumented legacy runtime, before any Track 1 shadow logic — 2026-08-22

Detail: `scratch/runtime_telemetry_patch_plan_20260822.md` and
`scratch/shadow_resume_timing_audit_20260822_report.md`.

**Before Track 1 shadow logic is written, collect instrumented legacy runtime for N days — or
re-derive it from replay logs if a live window is not available.**

Why this gate exists, in one measurement: live-day slots currently run at a median of 191 s and a
p95 of 216 s against a 300 s slot spacing, leaving **84 s of margin**. The behaviour at that boundary
is a step, not a slope — a fixed 216 s runtime skips nothing, a fixed 311 s skips every second slot.
On the four contended days in the sample (2026-08-05/06/07/10, when the median was 337 s) the
scheduler lost **11 of 23 slots per day**. Track 1 adds two sleeves, Calm A and the Stress detector,
to the same process, and nobody has measured what they cost per run.

**Gate conditions**

1. Telemetry running on legacy for **at least 10 trading days** (the current-regime sample is only 10
   days, and it has never seen a high-volatility session with many simultaneous entries; `send_order`
   itself models a 265 s worst-case blocking peak, which alone exceeds the 84 s of margin).
2. Legacy p95 confirmed from the runner's own `runtime_s`, not inferred from APScheduler lines.
3. Then, with Track 1 signals wired in shadow: **target p95 < 240 s, hard gate p95 < 300 s.**
4. If p95 lands between 240 s and 300 s, decide explicitly between runtime optimisation and 10-minute
   spacing in the Stress window — and note that coarser spacing halves the entry-timing resolution of
   a detector that fires on a low break at an unknown minute. That is a cost to measure, not assume.

### Stage 1 executed — offline infra built, 144 tests green — 2026-08-22

Report: `scratch/track1_stage1_execute_report_20260822.md`. Offline only; no service started, no
scheduler job, no order, nothing committed.

**Created, all new:** `global_index/route_params.py` (strategy identity),
`global_index/route_checkpoint.py` (schema v2, keyed route/sleeve/instrument),
`global_index/window_ledger.py` (window coverage),
`scratch/test_track1_route_checkpoint_stage1_20260822.py` (77 tests).

**None of the five legacy files was edited.** `runner.py`, `signal_layer.py` and
`replay_checkpoint.py` show no diff at all; `run_live_day.py` and `run_scheduler.py` carry only the
telemetry patch from an earlier pass — verified by filtering their diff for any non-telemetry line,
which left only that patch's own re-indent and reflow. `fingerprint()` is **imported, never copied**.

**Tests:** 77 (Stage 1) + 23 (telemetry) + 44 (baseline five, unchanged) = **144 passed**.
`test_event_playback` deliberately not run — pre-existing hang.

**Mutation checks were run, not deferred**, and one of them found a defect in my own suite. Breaking
the write-scope assertion, collapsing the two fingerprint codes, and making a missing `window_closed`
read as complete all went red correctly. But **deleting `ratchet` from the params identity left all 50
tests green** — the per-field test was parametrised over `route_params.ALL_FIELDS`, so removing a
field removed its test case and the suite silently *shrank* instead of failing. Same shape as a
fixture reading its expectations from the thing under test. Fixed with an independent pinned list in
the test file; re-running that mutation now gives 3 failures, and the suite grew 50 → 77. Worth
recording that the first run passed 50/50 first time, which is exactly when a suite deserves least
trust.

**Design points that matter downstream:** refusals are values with seven codes, not a bare `None`, and
`Refusal.__bool__` is False so `if usable(...)` cannot pass by accident. `fingerprint_rowcount` and
`fingerprint_content` stay separate because in the recorded evidence they had different causes (48 vs
4 of the historical 64). `pos=None` remains a usable answer, not a miss. `save_route` asserts every
other route's keys are byte-identical before/after the merge and raises `ScopeViolation` otherwise.
The ledger's fail-closed rule is the **absence** of a `window_closed` record — a ledger needing a
positive "I was down" line would be silent in the one case it exists for.

**No blockers.** Nothing required touching the five legacy files.

**Stage 2 next:** the equivalence harness against real parquet (which must first reproduce the
existing shadow record, 91 matched / 0 diverged, 2026-08-10 → 08-21, before judging anything new); a
Track 1 bootstrap from real bars; the telemetry phases implemented alongside the route code, with
`oracle_replay` excluded from the route p95; and the `_catch_up_maxhold` heartbeat hole plus the
route dimension on `_maxhold_done` / `_preflight_ok`. R0 host availability is unchanged and still
governs.


### Stage 1 implementation plan — resume-primary — 2026-08-22

Plan and gates only; no code, no production change, no service started.
Detail: `scratch/track1_resume_primary_stage1_implementation_plan_20260822.md` (+ `.json`).

**One rule the whole plan hangs on: every Stage 1 artefact is a NEW file.** No edit to `runner.py`,
`signal_layer.py`, `replay_checkpoint.py`, `run_live_day.py` or `run_scheduler.py`. Legacy's
checkpoint is a live dependency of the only check that closes the loop on live data; reaching into it
now would risk that evidence stream to buy nothing Stage 1 needs. Stage 1 ends with Track 1 provably
correct **offline** and legacy byte-identical.

**Seven stages**, each with files, isolation, tests, rollback and a gate: 1A schema-v2 module ·
1B params-hash + refusal tests · 1C route path and key space · 1D window-coverage ledger ·
1E equivalence harness · 1F telemetry phase names (implemented in Stage 2) · 1G scheduler review.

**Schema v2** is keyed `route / sleeve / instrument` — legacy keys by instrument alone, which cannot
hold MES in both Normal-R4 and Calm A at once. `roska4_calm` and `roska4_stress` appear with **empty**
instrument maps on purpose: they are same-session sleeves needing no historical checkpoint, and
present-but-empty says "accounted for" where absent would say "nobody thought about it".
`fingerprint()` is **imported, not copied** — its tz-stripping subtlety is hard-won and a copy would
drift exactly where its docstring says drift is fatal. `advance_day`'s rule is reused unchanged; it is
the fix for the 2026-08-07 incident.

**Lost updates**: keep the atomic whole-file write, add a lock file, a per-key merge scoped to the
writer's own route, and a write-scope assertion that every key outside that route is byte-identical to
what was loaded. Cheaper alternative for Stage 2 if the lock costs latency: one file per route.

**`params_hash` covers eight groups** — signal, stop (basis/multiple/anchor/ratchet), arming
(hour+tz), filters (R4 threshold **and its derivation window**, SPY short filter), regime
(`hmm_fit_end`, CSV identity, label lag, Calm gate), caps **including the family cap**, cost, and data
source **plus the fill law in force**. `hashlib`, never Python's `hash()` — it is salted per process.
**A field that cannot be tested is not added**: every field owes a mutation test.

**Two tests matter most.** T1, params mismatch must refuse — that branch has **never fired in
production**. T5, a missing checkpoint must fail closed with no entries proposed and explicitly not a
silent full replay. Every test is mutation-checked: break the guard, confirm the right test goes red,
restore.

**Window ledger is deliberately separate from the checkpoint.** A checkpoint answers "what state did
the last observation leave"; the ledger answers "did an observation happen at all". Merging them lets
a missing observation look like a flat position. **Absence of `window_closed` is itself the signal** —
a suspended host writes nothing, and nothing must read as failure. Cross-checked against
`HEARTBEAT STALLED` (matched a real OS suspend 28/28) and optionally the Power-Troubleshooter log
(39 suspends vs the scheduler's 28).

**Equivalence harness must reproduce the existing shadow record — 91 matched / 0 diverged,
2026-08-10 → 08-21 — before it is used to judge anything new**, then be shown able to detect a
deliberately corrupted resume state.

**Stage 1G (review only)**: `_catch_up_maxhold` is startup-only, so a running scheduler that sleeps
through 09:31 and is never restarted still gets neither path. The Stage 2 shape is to evaluate the
same predicate on the heartbeat as well — no new job, no new trigger, no argv change. And
`_maxhold_done` / `_preflight_ok` are date-keyed and persisted: they need a route dimension before a
second route shares the scheduler process, or Track 1's max-hold run marks the day done and suppresses
legacy's.

**Still unsettled after Stage 1:** R0 host availability (8 of the 9 most recent trading days had an S3
suspend; the idle timer is already off, so `STANDBYIDLE 0` is not the remedy here), and the `run_day`
cost of Track 1's two same-session sleeves — Stage 1 is offline and produces no p95, while the margin
at stake is 84 s.


### Checkpoint/resume design audit — R1 needs rewording — 2026-08-22

Read-only. Detail: `scratch/track1_checkpoint_resume_audit_20260822.md` (+ `.json`).

**The "64 no usable checkpoint" figure is not an open coverage deficit.** All 64 fall on two days —
2026-08-06 (16) and 2026-08-07 (48) — and there have been **zero in the ten trading days since.
Coverage has been 100% from 2026-08-10 to 2026-08-21.** The blended 59% mixes two bootstrap days into
ten clean ones.

The cause is already documented, in the code that fixed it. `advance_day`'s own docstring names the
incident: the checkpoint was advanced on the spliced live frame over a parquet day only half held, so
the next 13:45 ET append changed those rows and the fingerprint stopped matching. Verified against
the logs: 48 of the 64 are row-count mismatches, deltas **−552 to −554**, on the four Ro-4
instruments only — **MNKD skipped zero times** because its Tokyo day closes at 15:00 UTC, before the
ET append, exactly as the docstring says.

**So R1 should be reworded.** "Skipped comparisons have reason codes" aims at a problem that is
fixed. The useful gate is: *100% comparison coverage sustained over the declared window, with a
skipped comparison counted as a failed day rather than a neutral one.* That rule is what would have
caught 2026-08-06 — zero comparisons that day, which under the current phrasing reads as "no
divergence".

**Two additions the plan does not have:**

1. **The params-refusal branch of `usable()` has never fired in production.** Every recorded skip is a
   fingerprint mismatch. The check that stops a checkpoint being resumed under different engine
   settings (added 2026-08-17, commit `c91f14f`) has zero production exercises. Fire it deliberately
   before resume goes primary.
2. **`params` is narrower than what it protects.** It covers `ema_period`, `chandelier_atr_mult`,
   `max_hold_days` — and nothing else. Track 1's Normal-R4 differs from legacy by **stop basis 2.0,
   ratchet off and arm hour 14:05**, none of which are in it, plus the two filters, the regime
   identity and the caps. A Track 1 variant that changed only the stop would silently resume state
   computed under the old one. The route checkpoint needs a `params_hash` covering all of it.

Also: `ckpt.save()` rewrites the whole entries dict with no per-key merge, so two routes sharing one
file is a lost-update bug, not just untidiness. Track 1 needs its own path (the `--checkpoint-path`
flag already exists) and schema 2 keyed by **route / sleeve / instrument** — legacy keys by instrument
alone, which cannot hold MES in both Normal-R4 and Calm A at once.

**Encouraging finding for the route shape:** **two of Track 1's four sleeves need no historical
checkpoint at all.** Stress-MNQ needs only today's 09:30–10:30 bars plus one prior close per
instrument; Calm A needs the prior completed RTH session plus today's 09:30 open, and its gate is
D-1 causal by construction. Only Normal-R4 and current NKD are cross-day, and both already have the
resume path with 91/91 exact matches. Resume-primary fits Track 1 better than it fits legacy.

**The limit that no checkpoint work removes:** a checkpoint stores derived state; it cannot
manufacture an observation the host never made. Normal-R4 and NKD tolerate a missed slot — the state
model is idempotent and the cost is latency. Calm A loses a single-shot 10:00 entry. **Stress-MNQ is
not recoverable at all**: its entry is the break of the 09:30–10:30 low between 10:35 and 12:30, and
re-running later would enter at a price that has moved — the same one-shot-at-the-wrong-price failure
already ruled a design error, not a tolerance question. That is R0/G3, and it is why a missed window
must be recordable as **unobserved** rather than reading as "no signal". Today there is nowhere to
record it: a host suspend leaves no line at all, because no process was alive to write one.


### G1/G3 preparation — two of my own earlier claims corrected — 2026-08-22

Runbook: `scratch/track1_legacy_telemetry_collection_runbook_20260822.md` ·
Risk log: `scratch/maxhold_misfire_risk_log_20260822.md` · `scratch/track1_g1_g3_preparation_20260822.json`

**The sleep remedy I recommended is already applied and does nothing.** Measured read-only:
`STANDBYIDLE` is **0 on both AC and DC** on the active scheme, and `HIBERNATEIDLE` too. The command
the scheduler's own warning prints — `powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE
0` — is a **no-op on this host**, and running it would have produced a false "fixed" signal.

What is actually happening: the machine is on **S3** (no modern standby), and the OS event log shows
**120 suspends in 40 days, 39 of them (22.0 h) inside the audit window**. Wake sources: **Power
Button 24, USB device 13, Unknown 2 — zero wake-timer wakes.** With the idle timer already off, the
mechanism is **deliberate or lid-triggered suspend by a person**, not an idle timeout. The Start-menu
power-button action is set to **Sleep** on both AC and DC.

**28 of 28 scheduler stalls match a real OS suspend, one-to-one** — e.g. `STALLED 2160s` on
2026-08-19 pairs with a 2,155 s suspend ending at the same instant, 99% agreement. That verifies the
stall line against the OS rather than assuming it. It also shows the scheduler **under-reports**: 39
suspends / 22.0 h against 28 stalls / 17.2 h.

So G3 is not a `powercfg` command. It is: lid action to "do nothing", power-button action off Sleep,
stop manually sleeping during the window — **or** move the scheduler to the host in
`docs/futures/VPS_DEPLOY_PLAN.md`, which removes the class instead of managing it and whose argument
is exactly this evidence.

**The 2026-08-04 max-hold job did not "fire 41 minutes late" — it did not run at all.** The grace is
300 s (`run_scheduler.py:363`) and the delay was 2,475 s, so APScheduler dropped it: no `Running job`
line, no `executed successfully` line, while a normal day has both. Same day, pre-flight also failed
and all 23 day-window slots were skipped, so the 14:05 retry path never ran either.

Status: **already fixed for the observed sequence.** `_catch_up_maxhold` was added 2026-08-07 in
commit `91dbc0e`, named for exactly this. Since then: **0 max-hold misfires and 0 weekday sleeps
spanning 09:31 ET.** Residual hole, not observed but not closed: the catch-up is startup-only, so a
running scheduler that sleeps through 09:31 and is never restarted gets neither path.

**Not reconstructible from what is on disk:** which position was affected, intended vs available exit
price, P&L impact. `live_positions.json` is rewritten in place and holds only current state; there is
no dated snapshot and no retained trade-log row for that day. A dated position snapshot is the
cheapest change that would make any future incident reconstructible.


### Stage 0 readiness — gate clarified, one blocker named — 2026-08-22

Full detail: `scratch/track1_stage0_runtime_telemetry_readiness_20260822.md` (+ `.json`).

**Slot contention is not the blocker.** Current regime p95 216 s against 300 s spacing, and adding
Track 1's 25 slots costs at most **1 skipped slot in 48** across all 207 tested phasings. Margin is
84 s and the boundary is a step, not a slope.

**The blocker is machine sleep.** 28 `HEARTBEAT STALLED` events, 17.2 h of stalled scheduler time —
and sharper than the earlier headline of "13 of 18 days": **8 of the 9 trading days in the current
regime had a stall.** Only 2026-08-13 was clean, and the most recent stall in the sample is dated
2026-08-22. Every stall fell outside 14:05–15:55 so far, which is why no day-window slot misfired —
but nothing makes that structural, and Track 1 proposes a *second* continuous window at 10:35–12:30.
**Disable sleep and prove it (zero stall lines over the collection window) before the window goes
live**, otherwise the baseline is measured on a machine that suspends and has to be collected again.
Correction below: this does **not** mean running the scheduler's idle-sleep `powercfg` line; that
setting is already 0 on AC and DC. The issue is manual/lid/button-triggered S3 suspend or the need
for an always-on host.

**The 2026-08-04 max-hold misfire is a trading-job incident, not maintenance.** `MAX_HOLD exit
09:31 ET` did **not** run at all: the 2,475 s miss exceeded the 300 s grace, so APScheduler dropped
the run. It belongs in a trading-risk log of its own — the first version of the timing report filed it
under "NKD night / overnight maintenance", which was wrong on both counts.

**Gates before any live route:** G1 ≥10 instrumented legacy trading days · G2 legacy p95 confirms the
current regime · **G3 zero sleep stalls** · G4 Track 1 shadow **p95 < 300 s hard, < 240 s target** ·
G5 phase markers inside `runner.py`/`signal_layer.py` if `run_day` threatens G4 · G6 slot-outcome
accounting closes per day · G7 legacy unchanged (artifact sha256, empty job/argv diff, 44 baseline
tests).

**Telemetry verified inert this pass:** 23 telemetry tests + 44 baseline tests passed,
`RAITS_TELEMETRY_DIR` unset, no `slot_timing_*.jsonl` anywhere. Enabling is one export before the
scheduler starts; parent and child are on or off together. One convention note: telemetry stamps its
filename in UTC while `runner_events_*.jsonl` stamps in ET — join on `ts`, not on filename.

A stale sentence in the telemetry patch plan's rollback section (it still claimed the scheduler sets
`RAITS_TELEMETRY_DIR` "with `setdefault`") was corrected in place; the code removed that default in
revision 2.


### Telemetry revision 2 + timing addendum — 2026-08-22

Both pieces of the pre-Track-1 instrumentation work were reviewed and repaired; details in
`scratch/runtime_telemetry_patch_plan_20260822.md` and the addendum in
`scratch/shadow_resume_timing_audit_20260822_report.md`.

**Timing audit — two wrong statements corrected, conclusion unchanged.** Misfires are **not** all on
NKD night slots: 43 of 52 are, 9 are not, and one of the nine is the **09:31 max-hold close on
2026-08-04** — a trading job, previously buried inside a sentence about overnight maintenance. Later
G1/G3 work corrected the mechanism again: the job did **not** run late; the 2,475 s miss exceeded the
300 s grace and APScheduler dropped it. The NKD maximum was written as `~180 s`, an
approximation put in a max column; measured it is **532 s**, and the three runs over 300 s are all
the 02:55 `--shadow-verify` slot, which is legitimate. The 2,174 s outlier is machine sleep, not a
runtime. The exclusion rule is now derived from `_SLOT_TIMEOUT_SECS` (1,200 s, the ceiling at which
the parent kills the child) instead of an arbitrary 3,600 s. **The live-day distributions are
untouched, so the gate stands: p95 < 300 s hard, target < 240 s.**

New operational finding, quantified while chasing those corrections: **the machine sleeps on 13 of
18 days — 28 stalls, 17.2 hours of stalled scheduler time in total, worst single stall 3.6 h.** All
fell outside 14:05–15:55 in this sample, which is why no day-window slot misfired, but nothing makes
that structural. Track 1 would add a second window, 10:35–12:30, to a machine that suspends on 72% of
days. Later G1/G3 preparation measured the scheduler's idle-sleep `powercfg` recommendation as
already applied; the real fix is preventing manual/lid/button-triggered suspend during the collection
window or moving the scheduler to an always-on host.

**Telemetry — five defects fixed.** The patch claimed "off by default" while the scheduler injected
`RAITS_TELEMETRY_DIR` into every child; that default is removed, so parent and child are now on or
off together and one export before the scheduler starts is the only switch. `lock_held` and `error`
were documented and never emitted; both now have call sites. `dry_run` was being relabelled `ok` by
the success path; outcomes are now sticky for modes and forced for errors. Tests went 8 to **23**,
and the two guards that matter were **mutation-checked** by re-introducing the original defects and
confirming the right tests fail.


**Instrumentation now in place** (additive, uncommitted, off unless `RAITS_TELEMETRY_DIR` is set):
`global_index/slot_telemetry.py`, plus phase markers in `run_live_day.py` and skip records in
`run_scheduler.py`. One JSON line per slot in `slot_timing_YYYYMMDD.jsonl` carrying `route`
(default `legacy`), `slot_id`, `outcome`, `runtime_s` and per-phase seconds — including the
`skipped_mutex` / `skipped_preflight` outcomes that previously looked identical to a real run.
No job id, trigger or argv changed; the event schema and every monitor reader are untouched.

**Still open before Track 1 shadow:** `run_day` is a single number, so if it grows the cause will not
be attributable without markers inside `runner.py` and `signal_layer.py`; and the 2026-08-11 runtime
improvement (median 337 s → 191 s) remains unexplained, so the margin being spent here could vanish
for a reason nobody has identified.

### Track 1 route shape update — resume-primary, replay-verified — 2026-08-22

Full detail: `scratch/track1_resume_primary_route_plan_20260822.md`.

Do **not** assume Track 1 should copy the legacy "desired basket by rebuilding the whole historical
path every slot" shape. That is the reason the current route is slow. The route design target is
**checkpoint/resume-primary**, with full replay kept as the oracle for validation and periodic audit.

This is exactly what `--shadow-resume` has been preparing: the recorded evidence is **91 matched
comparisons, 0 divergences**. Later checkpoint/resume audit clarified the scary part: the **64 skipped
comparisons were all confined to 2026-08-06 and 2026-08-07**, caused by a fixed bootstrap fingerprint
bug; the ten trading days from 2026-08-10 to 2026-08-21 had **85 matches, 0 skips, 100% coverage**.
Resume is more promising than the blended 59% figure implied, but not yet trusted enough to trade.
The remaining missing pieces are different: route/sleeve checkpoint identity, a widened params hash,
an offline exercise of params-mismatch refusal, restart recovery, stale/missing fail-closed behavior,
window-coverage logging for Calm A / Stress, and a clear equivalence gate against full replay.

Updated principle: Track 1 should be built as a separate route whose normal path loads route-specific
checkpoint state, fetches only new bars, updates rolling sleeve state, computes desired positions,
reconciles with broker/state, and then compares against full replay in shadow until promotion gates
pass. Full replay remains the source of truth, but should not be the 5-minute production mechanism
unless it is an explicit fallback with telemetry and a hard runtime gate.

### Checkpoint/resume audit — corrected promotion gates — 2026-08-22

Full detail: `scratch/track1_checkpoint_resume_audit_20260822.md` (+ `.json`).

The audit reverses the plan's reading of `91 / 64`: **the 64 skipped comparisons are not an open
coverage debt.** They are one bootstrap incident on two days. The current evidence after the fix is
ten trading days of 100% comparison coverage and 0 divergence.

The real blockers are:

1. `usable()`'s params-mismatch refusal branch has **never fired in production** and must be exercised
   deliberately offline before resume-primary can be trusted.
2. Today's checkpoint params cover only `ema_period`, `chandelier_atr_mult`, and `max_hold_days`.
   Track 1 also needs stop basis, ratchet, arm time/timezone, filters, regime identity, caps, costs,
   and data-source identity in a `params_hash`.
3. The checkpoint namespace is **instrument only** and `ckpt.save()` rewrites the whole dict. Track 1
   needs a separate file / schema v2 / key space by route + sleeve + instrument.
4. Stress and Calm A do not mainly need historical checkpoints. They need **window coverage**:
   distinguish "the window was not observed" from "the window produced no signal." A checkpoint cannot
   repair a host sleep through the Stress break window.

Updated R1: require **100% comparison coverage over the declared window**, with any skipped
comparison counted as a failed day rather than neutral. The old "add reason codes for 64 skips" was
aimed at a bug already diagnosed and fixed.

### Stage 1 implementation plan — new-file-only rule — 2026-08-22

Full detail: `scratch/track1_resume_primary_stage1_implementation_plan_20260822.md` (+ `.json`).

Stage 1 is **offline proof only**. Every artefact is a **new file**; do not edit `runner.py`,
`signal_layer.py`, `replay_checkpoint.py`, `run_live_day.py`, or `run_scheduler.py`. Legacy's
checkpoint is the live evidence stream that currently closes the loop on live data, so Stage 1 must
not gamble it to build Track 1 infrastructure.

The seven planned stages are:

1. Schema v2 checkpoint module, separate from legacy, importing `fingerprint()` rather than copying it.
2. Params hash builder plus mutation-checked refusal tests.
3. Track 1 path/key space by route + sleeve + instrument, with lost-update protection.
4. Window-coverage ledger for Calm A / Stress, separate from checkpoint.
5. Offline resume-vs-full-replay equivalence harness anchored on the existing 91/0 shadow record.
6. Resume-primary telemetry phase names, implemented later in Stage 2.
7. Scheduler availability/catch-up review only.

Stage 1 exit requires mutation-checked offline tests, equivalence harness reproducing the existing
shadow record before judging anything new, `params_hash` covering every listed field, ledger
distinguishing `unobserved` from `no_signal`, and legacy byte-identical. Runtime p95 and any scheduler
route work belong to Stage 2, not Stage 1.
