# Stage 5ZZR — the Market View stops being one chart and starts being three strategies

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## 1. What the previous view assumed, and why it was wrong

Every sleeve got the same panel: a five-minute candle chart with a place for entry, stop and
target lines. That shape came from a mental model in which all three sleeves are price-trigger
strategies that differ only in their hours.

They are not. Measured from the detectors themselves:

| Sleeve | Detector | Trend period | How a setup forms |
|---|---|---|---|
| `global_nkd` | `track1_normal_r4` | EMA 10 | a setup **bar** must appear; nothing stands at a level |
| `roska4_swing` | `track1_normal_r4` — the same one | EMA 50 | the same, at a slower period |
| `roska4_stress` | `track1_stress_mnq` | — | a **basket gate** at 10:30, then a price trigger |

Two of the three sleeves share a detector and differ only by a period. The third is a different
strategy entirely, and it is the **only** one that uses breadth, gap-down counts and basket-gap
style metrics. An earlier draft of this redesign assumed NKD was basket-driven; it is not, and
that assumption would have put four numbers on the NKD panel that its detector never looks at.

The one-chart design produced two specific harms:

- **On NKD and Swing** it offered a frame for entry/stop/target lines that can never be filled,
  because those sleeves have no standing level to draw. An empty chart reads as missing data
  rather than as a strategy that works differently.
- **On Stress** it drew nothing at all, because Stage 5ZZQ had recorded that a metric boundary
  publishes no price levels. That record was wrong — see §3.

---

## 2. What each sleeve shows now

### NKD and Swing — the four variables their detector actually consumes

`make_signal_fn(prev_bar, resume_bar, ema, atr, regime, avgv)` is the signature the detector
calls. So the panel names exactly those four inputs and nothing else:

```
Trend filter (EMA 10)        Not reported by detector       ← EMA 50 on Swing
Volume vs 10-bar average     Not reported by detector
Daily ATR                    Not reported by detector
Regime                       Not reported by detector
```

The values are absent because `_scan_window` computes them internally and does not return them
— the same shape the Stress rule values had before Stage 5ZZP, and fixable the same way. The
panel says **"Not reported by detector"**, which is a statement about the plumbing, distinct
from "the market did not provide this" and from "nobody looked". Those stay five separate
answers in the payload: `not_yet`, `no_record`, `refused`, `missing_data`,
`not_reported_by_detector`.

The heading reads **Setup prerequisites**, and the body says entry forms only after a setup bar
appears. No line is drawn on either chart, because there is no level to draw.

### Stress — the gate, then the levels the gate governs

Measured on session **2026-08-27**, a day the gate **failed**:

```
Setup gate · decided 10:30 ET
  Instruments below open and VWAP    4        >= 4        passed
  Instruments gapped down            0        >= 3        FAILED   ← nearest miss
  Instruments with a wide range      0        >= 0        passed
  Average basket gap              +0.51%   <= -0.10%      FAILED

  Trigger (pre-session low)     29,575.25    not armed
  Planned stop                  29,662.38    not armed
  Session open                  29,598.25    not armed

  "Trigger levels were computed at 10:30 but are not armed — the setup gate did not pass"
```

The heading states the decision time **once**, so four session-level readings are not misread as
four live ones. The Stress conditions settle from bars at or before 10:30 and do not move again.

---

## 3. The correction this stage is really about

Stage 5ZZQ recorded that a metric boundary publishes no price levels, and wrote a test pinning
it. Reading the detector rather than the record: `session_context` returns `pre_low` and
`pre_high` for **every judgeable session**, gate or no gate, and `first_low_break` scans for a
one-minute low through `pre_low`. The trigger is a real published price on days nothing trades.

So the earlier claim was not a safe conservative default — it **hid a real number** an operator
wants to read. But publishing it live would have been worse: a solid line at 29,575.25 on a day
the gate failed is a line someone would trade against.

The rule that actually protects the operator is not *no level*. It is **no armed level**:

| State | Drawn |
|---|---|
| no level published | nothing |
| published, gate did not pass | dashed, dimmed, labelled `· not armed`, with a note saying why |
| published, gate passed | solid amber |

The 5ZZQ test has been rewritten from `price_levels == []` to *no level may be armed unless the
gate passed*, with the measurement that disproved the original claim recorded in it.

---

## 4. Regime numbers

The model takes exactly **two** features, and the panel now shows exactly those two:

| | |
|---|---|
| SPY 1-day log return | `log_return` |
| Realised volatility, 5-day annualised | `realised_vol` |

Nothing else appears. Range, trend/SMA and drawdown are not model inputs and would have been
invented had they been shown.

Measured 2026-08-28: label **Calm**, posterior **99.84%**, lead over next **99.67% over Normal**,
uncertainty **0.018 of 1.585 bits**.

**Shift threshold: "No published shift threshold."** The label comes from a Viterbi decode,
which compares states against each other rather than against a cut, so there is no threshold to
be near, and the model does not expose a simple flip threshold. Nothing on the page says
"distance to threshold" — that phrase would describe a decision procedure the model does not use.

That explanation is **read from the model**, not written into the page. A first cut of this
stage hardcoded the sentence in the frontend; that is the drift failure this project keeps
meeting, so the sentence now lives in `track1_regime_record.NO_THRESHOLD` and the page reads it.
The test asserts the page does **not** contain the words — a stronger property than containing
them. The test fixture that held its own transcription of that string had already gone stale,
so it now derives from the constant too.

---

## 5. What did not change

No strategy rule, no threshold, no schedule, no gate, no order path. The detectors were read,
not modified. This stage publishes values that already existed and decides how they are drawn.

Verified after the work:

```
track1_blocking=['PAPER_SHADOW_EVIDENCE']  orders_possible=False
track1_scheduler_mode=compatible  confirmation=True  legacy_entry_jobs=0
global_index/track1_runtime/orders          absent
global_index/live_positions.track1.json     absent
TRACK1_ORDERS_APPROVED                      unset
```

No broker connection was opened; a test asserts the backend opens none. The scheduler was not
restarted, and no restart is required — see §7.

---

## 6. Tests

- **33 new** (`scratch/test_track1_stage5zzr_strategy_native_market_view_20260828.py`): 19
  backend/source, 14 in a real browser at 375 / 720 / 1440 px.
- **8/8 mutations caught** (`scratch/track1_stage5zzr_mutations_20260828.py`). Each new rule was
  broken at the source in a subprocess and restored: arming a failed gate, withholding the
  computed trigger, deleting the prerequisite cards, giving NKD the Swing period, drawing every
  level as armed, making muted and armed look alike, restating the model in the page, and
  un-fixing the tooltip box model. All eight turned the right tests red.
- **474 passed** across the adjacent suites (5ZZL, 5ZZN, 5ZZO, 5ZZP, 5ZZQ, dashboard backend,
  realtime contract, realtime DOM).

### Six adjacent tests changed, and why each

Four were wording superseded by the corrected spec (`None published` → `No published shift
threshold`). One pinned the identifier `sleeve.levels`, which moved under the boundary that
publishes it — its intent, that the page addresses values out of the payload rather than
deriving them, is unchanged. The sixth is the 5ZZQ claim disproved in §3.

### Ten ops tests are red, and this stage did not do it

`test_track1_stage5zf_*`, `test_track1_stage5k_*` and `test_track1_ops_status_mode_*` fail on
assertions that pin the **pre-B1** world: that `track1_go_live_confirmation.json` does not exist,
and that `B1_broker_account_or_legacy_retirement` is still a blocker. Stage 5ZZJ created that
file on 2026-08-27 as a deliberate operator decision and Stage 5ZZK closed B1.

Evidence this stage is not the cause: the confirmation file is dated a day earlier; the only ops
test that reads a file 5ZZR touched (`test_14`, on `realtime.js`) passes; and inside the failing
`test_28`, the safety assertion itself — `allowed is False` — still passes. Orders remain
impossible; what is stale is the claim about *which* gate is blocking.

**This is left open, named, and not silently repaired.** Ten permanently-red tests are an alarm
people learn to ignore, so they need a stage of their own to re-pin to the post-B1 world — not a
quiet edit inside a dashboard stage.

### What the tests caught in this stage

- A **real layout defect**: `max-width: 100%` on a content-box pseudo-element is 100% *plus* its
  own padding and border. At 375 px the row is 343 px and the tooltip rendered 367 — the 24 px
  is 9/11 px padding and a 1 px border each side. Two earlier attempts (capping the width,
  flipping the last chip) each reduced the overflow without removing it; sizing the bubble by
  its border box, and anchoring it to the row rather than the chip, is what made the cap mean
  what it says.
- For the **fourth** time in these panels, an assertion of mine was case-sensitive against a
  heading the stylesheet uppercases. My own spec had already called this a property of the page.
  It is now handled once, by a normalising helper every text assertion goes through, rather than
  by a fifth patch.

---

## 7. Restart

**Not required.** `realtime.js` and `realtime.css` are static and no build step exists — a
browser reload picks them up. `track1_market_view.py` and `track1_regime_record.py` are imported
by the backend, so a running backend keeps the old code in memory until it is restarted; the
dashboard will show the previous panel until then. That is a display lag, not a safety matter,
and restarting the backend alone does not touch the scheduler (Stage 5ZZO).

---

## 8. Still open

- NKD and Swing prerequisite **values** — computed in `_scan_window`, not returned. Fixable the
  way Stage 5ZZP fixed the Stress rule values.
- The Calm sleeve's two-phase diagnostics: DECIDE at 09:32 must not display OBSERVE values.
- Per-slot diagnostic persistence.
- The ~62 s cost of the first request to a freshly started backend, which predates this work.
- The ten stale ops assertions above.
