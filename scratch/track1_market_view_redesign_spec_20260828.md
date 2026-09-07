# Track 1 Market View — strategy-native redesign specification

**2026-08-28.** Design specification only. No code changed, no orders, no gates touched.

---

## 0. Three measured corrections before any layout

The brief's core principle is right — *show the variables the strategy actually used*. Two of
its premises are not, and one of my own earlier classifications was incomplete. All three change
the design materially, so they come first.

### 0.1 NKD is **not** basket/breadth driven

> *"Assume NKD setup is driven by basket/metric conditions such as breadth, gapdown count,
> basket gap, average gap."*

Measured — `track1_live_sleeves.py` and `BOUNDARY_KIND`:

```text
global_nkd     -> track1_normal_r4.run_instrument(..., NormalR4Params(ema_period=10))
roska4_swing   -> the SAME detector, ema_period=50
roska4_stress  -> track1_stress_mnq   <- the ONLY sleeve with breadth/gapdown/basket gap
```

**NKD and Swing are the same strategy at different EMA periods.** Breadth, gapdown count and
basket gap belong to Stress alone and are never computed for NKD. A four-lane breadth view for
NKD would render four lanes that can never be populated — the worst possible outcome for a panel
whose purpose is explaining absence, because it would look like missing data forever.

**So NKD gets the price/EMA/volume view, not the metric view.** It is Swing's twin, and the two
share a layout.

### 0.2 The Stress metrics are **session-level**, not per-slot

The brief asks for lanes across slots (01:10→02:55, one point per slot). Measured:

```python
def basket_state(day, bars, prev_close, params)      # no slot time in the signature
def session_context(day_bars_1m, prev_rth_close, p)  # pre = bars5[time <= 10:30]
```

The four conditions are computed **once, from bars at or before 10:30**, and do not change for
the rest of the window. A lane chart across 24 Stress slots would draw four flat lines repeated
24 times — motion that implies information that is not there.

**So the gate is a card row, not a time series.** What genuinely varies per slot is the *entry
scan*, and that gets the slot lane.

### 0.3 Stress **does** have real price levels — my 5ZZQ classification was incomplete

I classified Stress as `metric_boundary` with `price_levels: []`. That is only half true, and
the missing half is the most useful thing on the panel. Measured on 2026-08-27, a day the gate
**failed**:

```text
MNQ  pre_low  = 29,575.25     <- the trigger; first 1-minute low through it is the entry
     pre_high = 29,632.75     -> stop_price() = 29,662.38
     vwap     = 29,603.31     open = 29,598.25
```

`session_context` returns these **whether or not the gate passes**, and `first_low_break` scans
for `pre_low` between 10:35 and now. So Stress is genuinely **two-stage**:

```text
stage 1   GATE      four basket conditions, decided once at 10:30      metric
stage 2   TRIGGER   first break of pre_low, scanned 10:35 -> 12:30      price
```

**Correction to the "no fake price line" rule:** the rule is right, but `pre_low` is not a fake
line — it is a real level the detector computes and compares against. What must never be drawn
is a line on a day where **no level was computed**. On a gate-failed day the levels exist and are
simply **not armed**, and that is a state worth showing, clearly marked.

### 0.4 What NKD/Swing actually decide on

```python
def signal_for(prev_bar, resume_bar, ema, atr, regime, avgv)
```

The decision variables are **EMA** (10 or 50), **daily ATR**, **regime**, and **average volume**
over the preceding ten bars. These are computed inside `_scan_window` and not returned — the
same shape as the Stress rule values before Stage 5ZZP. Publishing them is a backend change of
the same narrow kind (§8.2), and until then the Swing/NKD view shows price + volume and says
plainly which prerequisites are unpublished.

---

## 1. Market View layout

One section, unchanged in outer structure from the current panel.

```text
┌ TRACK 1 MARKET VIEW ─────────────────────────── MNQ · 5m · window 10:35–12:30 ┐
│ [ NKD ]  [ Stress ]  [ Swing ]                                                │
│                                                                               │
│ ‹ status chip › ‹ slots chip › ‹ data chip › ‹ setup chip › ‹ session chip ›   │
│                                                                               │
│ ┌─ body: SEE §2 (metric-gate sleeve) or §3 (price sleeve) ──────────────────┐ │
│ └───────────────────────────────────────────────────────────────────────────┘ │
│ one-line footer, only when the chips have not already said it                 │
└───────────────────────────────────────────────────────────────────────────────┘
```

Sleeve metadata sits in the existing `.source-note` on the heading line, right-aligned:
`MNQ · 5m bars · window 10:35–12:30`.

### Which body a sleeve gets

| sleeve | body | why |
|---|---|---|
| Stress | §2 gate cards + slot lane, price chart **secondary** | the gate is metric; the trigger is price |
| NKD | §3 price/EMA/volume | `normal_r4`, ema 10 |
| Swing | §3 price/EMA/volume | `normal_r4`, ema 50 |
| Calm | §4 compact two-phase card, no tab | one-shot contract, no window to chart |

---

## 2. Stress body — gate cards, then trigger

### 2.1 Gate row (primary, always first)

Four cards, session-level, with the decision time stated **once** above them so nobody reads
them as live:

```text
SETUP GATE · decided 10:30 ET

┌ Instruments below ─┐ ┌ Instruments gapped ┐ ┌ Wide ranges ──┐ ┌ Basket gap ────┐
│ 4                  │ │ 0        ◀ nearest │ │ 0             │ │ +0.51%         │
│ needs ≥ 4      PASS │ │ needs ≥ 3     FAIL │ │ needs ≥ 0 PASS│ │ needs ≤ −0.10% │
│                    │ │ 3 more needed      │ │               │ │ 0.61 pp away   │
└────────────────────┘ └────────────────────┘ └───────────────┘ └────────────────┘

Nearest miss · Instruments gapped down 0, needs ≥ 3
```

- Left border 2px: green pass, red fail, muted unknown. **Only the nearest failure** gets the
  3px border and the 5%-tint background — four red cards shout equally and rank nothing.
- Distance line appears **only on a failing card**. A passing card showing "4 to spare" invites
  reading a margin as a forecast.

### 2.2 Trigger strip (when the gate passes)

Only rendered when `set_up` is true. Shows the price stage:

```text
TRIGGER · MNQ

  Trigger (pre-session low)   29,575.25    ── not yet broken
  Planned stop                29,662.38    from the pre-session high
  Last price                  29,610.00    35.25 above trigger
```

When the gate **fails**, this strip is replaced by one muted line and **no chart lines are
drawn**:

```text
Trigger levels computed at 10:30 but not armed — the setup gate did not pass.
```

That sentence is the whole of §0.3: the numbers exist, and they are explicitly not in play.

### 2.3 Slot lane (what actually varies per slot)

A single horizontal lane, 24 markers, x-positioned by slot time across 10:35–12:30 — **not four
metric lanes**, because the metrics do not vary (§0.2).

```text
SLOTS   10:35 ······················································· 12:30
        ● ● ● ● ● ○ ○ ○ ● ● ● ● ● ● ● ● ● ● ○ ○ ● ● ● ●        18/24 observed
```

### 2.4 Price chart — secondary for Stress

Collapsed to a 120px strip by default with a `Show price` affordance, expanding to the standard
320px chart. Rationale: on a gate-failed day the price context does not explain the absence, and
giving it the top half of the panel says it does.

When a candidate exists, the chart expands by default and carries its levels (§7).

---

## 3. NKD / Swing body — price, EMA, volume

Same layout for both; only the EMA period and window differ.

```text
┌ chart 320px ───────────────────────────────────────────────────────────┐
│  price scale right · window band shaded · EMA(10|50) line              │
│  ─────────────────────────────────────────────────────────────────     │
│  volume pane, 44px, inside the same box                                │
│  slot lane + baseline                                                  │
│  time axis                                                             │
└─────────────────────────────────────────────────────────────────────────┘
legend: ● no signal  ● signal  ● refused  ○ no record  ○ not yet
```

### Setup prerequisites row

Below the chart, the four variables the detector actually consumes (§0.4):

```text
SETUP PREREQUISITES

┌ Trend filter (EMA 10) ┐ ┌ Volume vs 10-bar avg ┐ ┌ Daily ATR ────┐ ┌ Regime ───────┐
│ not published         │ │ not published        │ │ not published │ │ Calm          │
└───────────────────────┘ └──────────────────────┘ └───────────────┘ └───────────────┘

Entry forms only after a bar signals — there is no standing level to be a distance from.
```

Cards render greyed with `not published` until §8.2 lands. **The card is shown even when
unpublished**, because a named empty slot tells an operator what the strategy looks at; omitting
it tells them nothing.

---

## 4. Calm — compact two-phase card, no tab

Not a chart tab. A two-column card in the Track 1 Runtime area:

```text
CALM · one-shot                     DECIDE 09:32              OBSERVE 10:02
  prior-close location              measured                  —
  gap depth                         measured                  —
  10:00 reference price             not known at decide       10:02 refused
  planned stop                      not known at decide       —
```

The DECIDE column may **never** display a value the OBSERVE half produces. Where OBSERVE has not
run or refused, the cell says which — never blank, never borrowed from the other column.

---

## 5. Chip copy — exact strings

Left to right, and a chip is omitted rather than shown empty.

| chip | strings | tone |
|---|---|---|
| status | `NO SIGNAL` · `SIGNAL` · `2 SIGNALS` · `REJECTED` · `DATA REFUSED` · `WAITING` · `LIVE` · `INCOMPLETE` | muted / good / good / bad / bad / muted / accent / warn |
| slots | `18/24 slots` | plain |
| data | `Data OK` · `Latest 15:54 ET` · `No live bars` | plain / plain / bad |
| setup | `Gapdown 0/3` · `Basket gap 0.61 pp away` · `Entry forms after setup` · `Entry 29,575.25` | warn / warn / muted / good |
| session | `Stored session 2026-08-27` | muted |

Precedence for the status chip: **data refused → waiting → live → signal → no signal**. A feed
that did not answer outranks what the slots did, because it explains them.

### Tooltip copy

| element | tooltip |
|---|---|
| slots chip | Slots the window ledger recorded as observed, out of those scheduled. |
| `Data OK` | Today's bars joined onto history without disagreement. |
| `No live bars` | *the provider's own message, e.g.* IBKR 162: Historical Market Data Service error. |
| setup chip | The condition furthest from being met, and by how much. |
| `Entry forms after setup` | The entry is produced by a signalling bar, not by a level waiting to be reached. |
| gate card | Value now, the limit it must meet, and the distance when it does not. |
| trigger level | Computed from the pre-session low at 10:30. Armed only once the gate passes. |
| slot marker | *see §6* |
| posterior bar | *state* · *probability* · lead over the next state. |

---

## 6. Markers, colours, legend

Reuses the existing tokens; no new palette.

| marker | fill | token | means |
|---|---|---|---|
| ● | solid | `--dim` | evaluated, no signal |
| ● | solid | `--green` | signal / setup formed |
| ● | solid | `--amber` | refused — gate or data |
| ● | solid | `--red` | rejected by a cap |
| ○ | hollow | `--red` | past its time, **no record written** |
| ○ | hollow | `--muted` | future — has not fired |

`no record` and `not yet` are deliberately different marks. Absence is not a quiet result.

**Slot marker tooltip:**
```text
11:05 · TRACK1_STRESS_1105
No signal · 0 candidates
Data OK · latest bar 11:04 ET
Nearest miss: Instruments gapped down 0, needs ≥ 3
```

---

## 7. When a price line may be drawn — the rule

A line is drawn **if and only if** the backend payload carries a `price_levels` entry with a
finite `price` and `source: "sleeve_detector"`. The frontend never derives one.

| condition | drawn |
|---|---|
| `price_levels: []` | nothing |
| gate failed, levels computed | **nothing on the chart**; §2.2 muted line instead |
| gate passed, trigger not broken | trigger + planned stop, dashed |
| candidate exists | entry, stop, target, solid; trigger dashed |
| NKD/Swing, no setup | nothing — no standing level exists |

Style: dashed 4-3 amber for a level not yet in play; solid for a level belonging to a live
candidate; a right-edge label carrying the price. A level is never extrapolated past the bars
that produced it.

---

## 8. Empty and missing states

### 8.1 The five states, kept distinct

| state | body | copy |
|---|---|---|
| market said no | full gate cards + slot lane | `No signal · Instruments gapped down 3 more needed` |
| data missing | gate row replaced | `Setup not judgeable · MES has no bars for this session` |
| setup not formed | gate cards, trigger strip muted | `Trigger levels computed at 10:30 but not armed` |
| candidate exists | chart expands, levels drawn | `Signal · entry 29,575.25` |
| not started | chips only | `Waiting · window has not opened · 24 slots scheduled` |

**Missing data never renders as no-signal.** It replaces the gate row rather than showing four
cards of `--`, because four empty cards read as four measured zeros.

### 8.2 Values that need a backend change before their card can fill

| card | source | status |
|---|---|---|
| Trend filter (EMA) | `make_signal_fn(..., ema, ...)` | computed, not returned |
| Volume vs 10-bar avg | `_scan_window` → `avgv` | computed, not returned |
| Daily ATR | `cache["datr"].asof(day)` | computed, not returned |
| Calm DECIDE values | `track1_calm_a.entry_conditions` → dict | returned, not wired through the two-phase path |

Same narrow shape as Stage 5ZZP's Stress work: extract the value beside the decision, prove the
decision is byte-identical over a swept grid, publish. Until then the card shows `not published`
and the panel is honest about it.

---

## 9. Regime Monitor

Separate panel below Market View. Structure as built in 5ZZQ, with the layout stated here.

```text
┌ REGIME MONITOR ──────────────────────── daily label · 2026-08-27 ┐
│  Calm    as of 2026-08-27    checked 1.4h ago                    │
│                                                                  │
│  MODEL CONFIDENCE · uncertainty 0.018 of 1.585 bits              │
│    Calm    ████████████████████████████████████████  99.84%      │
│    Normal  ▏                                          0.16%      │
│    Stress  ▏                                          0.00%      │
│                                                                  │
│  Lead over Normal 99.7 pp · Uncertainty Low                      │
│  No fixed threshold — the model chooses the most likely state.   │
│                                                                  │
│  WHY THIS LABEL                                                  │
│    Input                          Now        60-day      Leans   │
│    SPY 1-day log return        +0.65%   77th pct z+0.72  no lean │
│    Realised volatility, 5-day  5.8% ann.  0th pct z−1.39   Calm  │
│                                                                  │
│  LAST 60 TRADING DAYS   ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇  ■Calm ■Normal ■Stress │
│  LAST 5   08-21 Calm · 08-24 Calm · 08-25 Calm · 08-26 Calm · 08-27 Calm │
└──────────────────────────────────────────────────────────────────┘
```

**Uncertainty word from entropy:** `Low` below 0.25 bits, `Moderate` to 0.9, `High` above.
Stated as a word beside the number so the bits do not have to be interpreted.

**Only two feature rows exist** — the model is fitted on exactly two columns
(`raits/hmm/features.py`). The brief lists range, trend/SMA and drawdown; **those are not model
inputs** and must not appear, or the table would claim the model looked at things it did not.

`no lean` where the states are not separated, with the reason on hover. Never an attribution:
a Gaussian HMM decodes a path over a joint distribution and does not decompose per input.

---

## 10. Responsive

| width | Market View | Regime |
|---|---|---|
| ≥1100px | gate cards 4-up; chart full width below | posterior and feature table side by side |
| 720–1099 | gate cards 2-up; chart full width | stacked, table full width |
| <720 | cards 1-up; chart 240px; legend wraps | feature rows become blocks, heading row hidden |

Fixed heights: chart 320 / 240. The gate row, prerequisites row, legend and all regime blocks
sit **outside** the chart box, so switching tabs cannot move the panel — measured spread 0px.

---

## 11. Staying consistent with the existing dashboard

- **Chips** reuse `.issue-status`' shape exactly: `3px 6px`, `1px solid currentColor`, radius 3,
  `700 11px/1.25 mono`, uppercase, nowrap. Tone by token only.
- **Cards** are the `#track1Facts .fact` idiom — uppercase sans label at 11px/.1em, mono value —
  plus a 2px left border for verdict. No card inside a card.
- **Tokens only**: `--green --red --amber --accent --dim --muted --line --line-hair --panel
  --t-label --t-primary`. No new colours.
- **Type**: sans for labels and prose, mono for values. Explanatory sentences are **not** mono.
- **Section chrome**: one `.section-band`, one `.section-heading.compact`, one `.source-note`.
  No nested panels, no gradients, no decorative headers.
- **Tooltips** use the existing `.has-tip` mechanism, and any tooltip on a right-edge element
  gets the `left:auto; right:0` flip — measured twice now as a source of container overflow.
- **No raw identifiers** in visible text. `gapdown_count` → `Instruments gapped down`;
  `metric_boundary` → never shown; `not_exposed_by_sleeve` → `Not published`;
  `splice_result` → `Data join`; `provider_lag` → `Data delayed`.

---

## 12. Build order

1. **Stress two-stage view** — gate cards + trigger strip + slot lane; price chart demoted to a
   strip. Uses only what the payload already carries plus `pre_low`/`pre_high`, which
   `session_context` already returns.
2. **Publish `pre_low`/`pre_high`** into `setup_boundary.price_levels`, armed flag included.
   Corrects §0.3.
3. **NKD/Swing prerequisites row** with `not published` cards — honest immediately, and fills in
   as §8.2 lands.
4. **§8.2 backend extraction** — EMA, avgv, daily ATR, one sleeve at a time, each with a swept
   equivalence proof.
5. **Calm two-phase card**.

Steps 1–3 need no change to any detector. Step 4 does, and each part carries the same burden
Stage 5ZZP met: the decision must be provably identical, over a grid that contains real setups
and not only empty results.
