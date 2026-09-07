# Stage 5Q-8 — Is the Track 1 paper path the same strategy as the backtest?

**2026-08-24, 20:50–22:10 ET ·** read-only audit · no scheduler or backend started or stopped ·
**no IBKR connection** · no parquet, CSV or runtime evidence written · no order · no
confirmation file · B1 still blocking · overlap guard untouched · no commit.

Two test files were edited and one was added; both edits are stale-literal repairs named below.

---

## Verdict: **NOT_READY_IDENTITY_MISMATCH**

Not because a sleeve computes a different signal. **The signal path is proven identical** — all
four sleeves reproduce their committed rows exactly, on today's repaired parquets, and the one
data-identity defect was closed last night.

Two things are still wrong, and both sit between the strategy and the book:

| | finding | severity |
|---|---|---|
| **I-1** | `global_nkd`'s **declared** identity names a stop rule the sleeve does not run — five fields — so the checkpoint hash and every live explanation record describe legacy NKD | the hash decides checkpoint acceptance |
| **I-3** | the **sizing basis** differs from the artifact's by exactly **1.25×** on `roska4_swing` and `global_nkd`, on all 1,223 rows, undeclared and never measured against the caps | admission, not signal |
| **I-2** | the identity hash carries **no tradable identity, point_value or sizing basis** — the 2026-08-14 ten-times-size incident would not have moved a single hash | latent |

The stage's own criterion is "same signal data identity, clock, fill law, rule parameters,
**sizing basis**, and trade rows". Five of six are confirmed. The sixth is not.

---

## 1. Identity per sleeve — backtest / live signal / live order

| sleeve | instruments | backtest data (file) | fetched as | live signal fetches | live **order** | clock |
|---|---|---|---|---|---|---|
| `roska4_swing` | MES MNQ MYM M2K | `ES/NQ/YM/RTY_continuous_1m_8y.parquet` | MES MNQ MYM M2K | **same** | MES MNQ MYM M2K | ET |
| `roska4_calm` | MES MNQ | `ES/NQ_continuous_1m_8y.parquet` | MES MNQ | **same** | MES MNQ | ET |
| `roska4_stress` | MNQ | `NQ_continuous_1m_8y.parquet` | MNQ | **same** | MNQ | ET |
| `global_nkd` | **MNKD** | `NKD_continuous_1m_8y.parquet` | **NKD** | **NKD** *(since 5Q-7)* | **MNK** | **Asia/Tokyo** |

`point_value`: MES 5.0 · MNQ 2.0 · MYM 0.5 · M2K 5.0 · **MNKD 0.50** (NKD full-size is 5.0 and
is never traded). **No code path multiplies an OHLC value by a multiplier** — the only
`point_value`-beside-price occurrence in the package is a docstring in `track1_calm_a`
describing `|entry − stop| × point_value × qty`, which is risk, not price.

### Clocks, as numbers

```text
global_nkd scheduler slots   01:10-02:55 ET, 22 entry slots
  summer  01:10 ET -> 14:10 JST      02:55 ET -> 15:55 JST     the Tokyo power hour
  winter  01:10 ET -> 15:10 JST      02:55 ET -> 16:55 JST     outside it  (B-5R-C)
```

Every instrument is read on its own declared session zone: MNKD `Asia/Tokyo`, the other four
`America/New_York`. `frozen_frame` converts from the spec, not from a caller.

---

## 2. Exact reproduction — re-run tonight, on the repaired parquets

All three committed windows end on or before **2026-08-19**, so tonight's boundary repair
(2026-08-24 13:45) and its 335-bar append cannot reach them. Confirmed rather than assumed by
re-running the whole three-window suite after the repair.

| sleeve | window | expected | reproduced | mismatches | P&L delta |
|---|---|---|---|---|---|
| **Normal-R4** *(incl. MNKD)* | floor | 980 | 980 | 0 | 0.00 |
| | vault2025 | 136 | 136 | 0 | 0.00 |
| | vault2026 | 107 | 107 | 0 | 0.00 |
| | **all three** | **1,223** | **1,223** | **0** | **0.00** |
| **Calm A** | floor | 349 | 349 | 0 | 0.00 |
| | vault2025 | 44 | 44 | 0 | 0.00 |
| | vault2026 | 28 | 28 | 0 | 0.00 |
| | **all three** | **421** | **421** | **0** | **0.00** |
| **Stress-MNQ** | floor | 50 rows, +$23,748.85 | 50 | 0 | 0.00 |
| | vault2025 | 3 rows, +$4,530.96 | 3 | 0 | 0.00 |
| | vault2026 | 4 rows, −$405.72 | 4 | 0 | 0.00 |
| **MNKD** *(inside Normal-R4)* | floor | 228 | 228 | 0 | 0.00 |
| | vault2025 | 31 | 31 | 0 | 0.00 |
| | vault2026 | 26 | 26 | 0 | 0.00 |

Per-instrument on vault2026: MES 22/22, MNQ 18/18, MYM 24/24, M2K 17/17, MNKD 26/26.
Calm A also matches its four recorded feature columns to 1e-9.

Suites: Stage 4 three-window run **31 passed** (17 min); Stress **29 passed, 1 skipped**.

---

## 3. Intentional differences — explicit, measured, accepted

| # | difference | measurement | why it is accepted |
|---|---|---|---|
| **D-1** | **MNKD signal reads NKD; MNKD orders route to MNK** | fetch-as-MNK: **1,155 of 1,186** shared minutes disagree, worst 375.0, median-where-bad 25.0, **signed close median 0.0**. fetch-as-NKD: **0 of 1,186**, worst 0.0000 | the micro MNK has history only from 2024 Q4; the backtest runs on full-size NKD from 2018. One index, two order books. The multiplier — never the bars — carries the size difference |
| **D-2** | artifact ran `artifact_all_bars_gappable`; the live route runs `production_gap_after_15min_break` | vault2026 **+$3.21** (1 row, MNKD) · vault2025 **$0.00** (0 rows) · floor **+$5.57** (5 rows: M2K +0.21, MNKD +5.36). **+$8.78 total on $49,389** | 4/5, 5/5 and 3/5 instruments byte-identical. The production law is the more permissive, so every published Track 1 number was measured under the more conservative one. Nothing needs re-rating |

Both are named in `route_params.ALL_FIELDS` — `data_source_identity` and `fill_law` — so a run
that used one and declared the other moves the hash and gets refused.

### The MNKD proof, stated plainly

Both arms travelled the same `on_frozen_clock` conversion keyed on MNKD, so the clock was held
fixed and the symbol was the only thing that varied, over the same 1,186 shared minutes:

```text
fetch as MNK (the ORDER symbol)     1155 / 1186 disagree
fetch as NKD (the HISTORY symbol)      0 / 1186 disagree
```

The clock explanation was tested rather than dismissed — the overlap guard's own docstring
records a 1,050-bar Nikkei incident from a thirteen-hour error, and the first count taken was
1,052. It is ruled out by **magnitude**: a clock error is a large persistent one-directional
offset of 900–1,000 points; here the *signed* close median is **0.0** and the typical gap is 25
points, one tick on a five-point grid. That is two order books on one index, differing
symmetrically. **The signal must use NKD** because that is the series every committed MNKD row
was computed on, and it is the only one that agrees with history to the tick.

---

## 4. Forbidden and undeclared differences — what this audit found

### I-1 · `global_nkd` declares a stop rule it does not run

`track1_params.sleeve_config` is what `params_hash` is computed over, and what a live decision
reports as `stop_basis` in its explanation record. It is written by hand beside — not derived
from — the module that runs.

| field | **declared** | **executed**, and what the artifact reproduces under |
|---|---|---|
| `stop_basis` | `chandelier_atr` | entry ∓ 2.0 × daily ATR |
| `stop_multiple` | **2.5** | **2.0** |
| `stop_anchor` | `extreme_through_prior_bar` | `entry` |
| `ratchet` | **True** | **False** |
| `arm_hour` | **14:00** Asia/Tokyo | **14:05** on the frame's own clock |

Everything that decides *which bars* and *which days* agrees: `ema_period` 10, `max_hold_days`
5, `label_lag_days` 1.

The declaration describes **legacy NKD**. The Track 1 sleeve runs
`NormalR4Params(ema_period=10)` — and the committed artifact reproduces **exactly** under that
rule (228 / 31 / 26). So the code is right and the declaration is wrong.

Consequences, in order of cost: the checkpoint hash for `global_nkd` is computed over a rule
nothing runs, so it would accept state from a genuinely different configuration and refuse
nothing if someone "corrected" the code to match the text; and a live MNKD decision is
explained to the operator as `chandelier_atr` while the stop actually placed is
`entry ∓ 2.0 × ATR`.

*A wrong turn worth recording:* I first read `generate_replay_snapshots.py:94`
(`backtest_swing_tf(ema_period=10, chandelier_atr_mult=2.5)`) as the NKD generator, which would
have made the **live path** the defect. Running both engines over the same window gave 62 vs 26
trades and a P&L sign flip — but the arm meant to reproduce the committed rows **reproduced
none of them** (0 of 26 exact), so the instrument had failed and the comparison was discarded
rather than reported. The actual Track 1 NKD artifact is the Normal-R4 promotion file, which
carries MNKD alongside the four basket instruments. `generate_replay_snapshots.py` is a legacy
producer the Track 1 route does not consume.

### I-3 · the sizing basis differs from the artifact by exactly 1.25×

The live route sizes every candidate on `|entry − stop| × point_value × qty`, recorded as
`risk_basis: "true_stop_distance"` at all four call sites. The artifacts do not all agree:

| sleeve | artifact carries a stop price? | artifact risk == true stop distance? | ratio artifact ÷ live |
|---|---|---|---|
| `roska4_calm` | yes | **28 of 28 exact** | 1.000 |
| `roska4_stress` | yes | **4 of 4 exact** | 1.000 |
| `roska4_swing` | **no** | — risk is `2.5 × daily ATR × pv × qty` | **1.25 on 938 of 938 rows** |
| `global_nkd` | **no** | — risk is `2.5 × daily ATR × pv × qty` | **1.25 on 285 of 285 rows** |

`ROSKA4_MULT = NKD_MULT = 2.5`, while the stop those two sleeves actually place is
`2.0 × daily ATR`. Every distinct ratio across all three windows is exactly `1.25` — not a
distribution, a constant.

So the live route reports **80% of the risk the artifact recorded for the same trade** on the
two ATR-stop sleeves. The caps are in the identity hash (`cap_roska4_swing`, `cap_global_nkd`,
…) and are unchanged — but the quantity they gate is computed on a different basis, so the same
cap admits roughly **25% more** than the measured book did. Nothing in `route_params` names the
sizing basis, so this does not move a hash.

Which basis is *right* is a separate question, and the true stop distance is arguably the better
one. What is missing is the measurement: **nobody has measured what the change does to
admissions under the caps.** That is the gap, and it is why this stage cannot say
IDENTITY_MATCH_CONFIRMED.

### I-2 · the identity hash carries no tradable identity

`route_params.ALL_FIELDS` contains no name for the order symbol, the point value, the multiplier
or the sizing basis. The 2026-08-14 defect — MNKD routed to full-size NKD, ten times the
intended size, −$1,400 at the broker against −$140 in the ledger — **would not have moved a
single params hash**, and a checkpoint written before it would have been accepted after it.

Recorded rather than fixed: adding a field invalidates every stored hash, which is a decision
and not a tidy-up. Pinned by a test so the gap stays visible.

### Checked and clean

| checked | result |
|---|---|
| any live signal source different from the backtest source | **none** — all four sleeves fetch the symbol their parquet was built from |
| any order symbol used for signal data | **none** — closed by Stage 5Q-7; MNKD is the only split and it now goes the right way |
| any `point_value` drift | **none** — MNKD 0.50, NKD 5.00, basket unchanged |
| any clock conversion drift | **none** — each instrument on its declared session zone; NKD's ET slots are the Tokyo power hour in summer |
| any multiplier applied to OHLC | **none** |

---

## 5. Per-sleeve checklist

**`roska4_swing` / Normal-R4** — MES MNQ MYM M2K ✓ · same parquets as the backtest, fetched as
themselves ✓ · ET ✓ · entry window 14:05–15:55 ET ✓ · EMA **50** ✓ · R4 range filter
p90 = 0.02652437 from `floor_2018_2024_p90` ✓ · entry-bar relative volume ≤ 2.0 on
`rvol_slot20` ✓ · SPY D-1 short filter `d1_spy_close_below_sma50_for_shorts_only`, lookback 50,
lag 1 ✓ · stop entry ∓ **2.0 × daily ATR** ✓ · ratchet **off** ✓ · armed **14:05** next session
(`ARM_HOURS = 14 + 5/60`) ✓ · max hold **5** ✓ · qty **1** micro each ✓ · fill law declared =
run ✓ · **1,223 / 1,223 rows** ✓. **Sizing basis 1.25× — I-3.**

**`roska4_calm` / Calm A** — MES MNQ ✓ · 10:00 ET one-shot ✓ · D-1 Calm (`regime_lag_sessions`
1) ✓ · prior RTH close in the bottom third (`close_loc_max` = 1/3) ✓ · prior RTH down close
(`prev_ret_max` 0.0) ✓ · gap not deep (`gap_min` −0.010) ✓ · entry at the 10:00 **open** ✓ ·
disaster stop entry − **1.5 × ATR15**, placed at the fill and never moved ✓ · exit 15:55 ✓ · a
session missing its 10:00 or 15:55 bar is not traded ✓ · **421 / 421** plus four feature columns
to 1e-9 ✓ · sizing basis exact ✓.

**`roska4_stress` / Stress-MNQ** — MNQ only ✓ · qty **7**, from the sleeve not the symbol ✓ ·
**no regime label at all** ✓ · scan 10:35–12:30 ET, starting at 10:35 because the 10:30 bar's
close is not known until then ✓ · breadth: all 4 R4 instruments below both the day open and
session VWAP (`breadth_min` 4) ✓ · gap-down 3 at ≤ −0.004, average gap ≤ −0.001 ✓ · stop
`pre_high × 1.001` (`stop_pad` 0.001) ✓ · target `entry − 1.5 × (stop − entry)` ✓ · exit 15:55 ✓
· **50 / 3 / 4 rows, +$23,748.85 / +$4,530.96 / −$405.72** ✓ · sizing basis exact ✓.

**`global_nkd` / NKD-MNKD** — runner instrument **MNKD** ✓ · history and signal on **NKD** bars
✓ · live provider asks for **NKD** since 5Q-7 ✓ · orders remain **MNK** ✓ · point_value **$0.50**
✓ · no multiplier on OHLC ✓ · session clock **Asia/Tokyo** ✓ · ET slots **01:10–02:55** = Tokyo
**14:10–15:55** in summer ✓ · EMA **10** ✓ · max hold **5** ✓ · lag-1 regime ✓ · fill-law delta
**+$3.21 / $0.00 / +$5.36** ✓ · **228 / 31 / 26 rows** exact ✓.
**Chandelier 2.5 is strategy config, not the stop width — and the declared identity says
otherwise: I-1. Sizing basis 1.25× — I-3.**

---

## 6. Tests

`scratch/test_track1_stage5q8_identity_audit_20260824.py` — **15 passed, 1 xfailed(strict)**.

- MNKD live signal provider asks for **NKD**; order routing asks for **MNK**; the two are
  different strings, and MNKD's `point_value` is 0.50 while NKD's is 5.00.
- Every instrument fetches the symbol its parquet was built from — held shut for all five, not
  only the one that had the defect.
- Three sleeves declare the rule they run. **`global_nkd` is `xfail(strict=True)`** with the
  finding in its reason: it is visible in every run, it does not break the suite, and it turns
  into a failure the moment someone fixes it, which is when the marker should go.
- A companion test **bounds** I-1 at exactly five fields, so the finding cannot quietly grow.
- The hash moves on `data_source_identity` and on `fill_law`; a test pins that it does **not**
  yet move on the tradable identity (I-2).
- The NKD ET window is the Tokyo power hour in summer and leaves it in winter — B-5R-C as a
  number rather than a warning.
- All four live sleeves record `true_stop_distance`, parsed from the AST rather than grepped.

Reproduction, re-run tonight on the repaired parquets: Stage 4 three-window **31 passed**,
Stress **29 passed 1 skipped**, Stage 5Q-7 identity **16 passed**.

### Two stale literals repaired

Both files pinned the default schedule at **60** jobs; Stage 5Q-5 deliberately made it **61** by
adding `spy_refresh_pm` at 16:20 ET. Re-pinned at 61 with the reason inline, plus an assertion
naming the new job — `scratch/test_track1_stage4_production_clean_20260823.py` and
`scratch/test_track1_stage5n_nkd_track1_ownership_20260824.py`. Neither is a reproduction
failure; both are inventory pins that had not caught up.

---

## 7. What to do before paper orders

| | action | why |
|---|---|---|
| 1 | **Correct `sleeve_config('global_nkd')`** to `fixed_entry_atr` / 2.0 / `entry` / `ratchet=False` / `14:05`, and delete the `xfail` marker | the hash and the explanation record must name the rule that runs. Every stored `global_nkd` checkpoint hash changes — that is the point, and it should be done before any state worth keeping exists |
| 2 | **Measure I-3**: replay all three windows through the cap gate on both bases and report how many admissions change | the caps are unchanged but their input is 1.25× smaller. Until this is measured, the live book is not the measured book |
| 3 | **Decide I-2**: whether the tradable identity, point value and sizing basis belong in `ALL_FIELDS` | a ten-times-size routing change currently moves no hash |

None of this blocks the *shadow* session — nothing routes an order while B1 blocks. All three
block **paper orders**, because each one sits between a correct signal and the size that would
be sent.

---

## Files

**Read-only audit — no production code changed.**

```text
added    scratch/test_track1_stage5q8_identity_audit_20260824.py        16 checks
added    scratch/track1_stage5q8_raw_backtest_identity_audit_20260824.md / .json
edited   scratch/test_track1_stage4_production_clean_20260823.py        60 -> 61 job pin
edited   scratch/test_track1_stage5n_nkd_track1_ownership_20260824.py   60 -> 61 job pin
```
