# Stage 5ZZQ — what would have to happen, and why the model said Calm

**2026-08-28.** No orders · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · no orders
directory · confirmation unchanged · scheduler untouched · no broker call · **no trading
decision changed**.

---

## 1. Setup boundary classification, per sleeve

Read from each detector, and the **proof travels in the payload** so the claim cannot drift away
from the code.

| sleeve | type | proof from source |
|---|---|---|
| **Stress** | `metric_boundary` | `entry_conditions` compares four basket **counts** and an average gap against `StressParams`; no single price is the trigger |
| **NKD** | `entry_after_setup_only` | `detect_entry_for_slot` returns `SwingSetup(entry, stop)` when a bar signals and `None` otherwise; the entry comes from a per-bar signal function, not a standing level |
| **Swing** | `entry_after_setup_only` | same detector at a different `ema_period` |
| **Calm** | `two_phase` | DECIDE and OBSERVE know different things; the 10:00 reference and planned stop are OBSERVE-only |

**No sleeve gets a price line drawn before a candidate exists**, and for Stress that is the
whole point: the setup is a statement about a four-instrument basket at 10:30, so there is no
price on the chart that a line could honestly mark. Drawing one would invent a trigger the
strategy does not have.

## 2. What Stress can now say when it says nothing

```text
Setup conditions                                            (2026-08-27)
  Instruments below open and VWAP        4    needs >= 4          PASS
  Instruments gapped down                0    needs >= 3          FAIL   3 more needed
  Instruments with a wide range          0    needs >= 0          PASS
  Average basket gap                +0.51%    needs <= -0.10%     FAIL   0.61 pp away

nearest failed condition   Instruments gapped down 0, needs >= 3
summary                    No setup · Instruments gapped down 3 more needed
price_levels               []
```

**Nearest**, not first. An operator asks how close the day came, and the order the rules happen
to be declared in is an accident rather than an answer — so the failures are ranked by distance
relative to their own threshold.

`missing_data` stays distinct from `no setup`: a session with no bars is not a session that
looked and found nothing.

## 3. Why the model said Calm

The model is fitted on **exactly two columns**, named at source in `raits/hmm/features.py`:

```text
                                            value        60-day      leans
SPY 1-day log return                       +0.65%    77th pct  z +0.72   no lean
Realised volatility, 5-day annualised   5.8% ann.     0th pct  z -1.39   Calm

posterior      Calm 99.8354%   Normal 0.1643%   Stress 0.0003%
runner-up      Normal, margin 0.996711
uncertainty    0.0176 of a possible 1.5850 bits
threshold      none
```

That is a genuine answer: **realised volatility is at the floor of its 60-day range** and sits
nearest the Calm state's own mean, while the day's return does not discriminate at all.

### The lean is deliberately modest, and one feature refuses to claim one

The lean is the distance from the value to each state's mean, **in that state's own standard
deviations**, and it reports `no lean` when the best and second-best are closer together than
half a standard deviation. Measured:

```text
log_return     state means   Calm +0.0010  Normal +0.0005  Stress -0.0015
               sd-distance   Calm 0.976    Normal 0.546    Stress 0.319   separation 0.228
realised_vol   state means   Calm  0.0693  Normal  0.1568  Stress  0.3533
               sd-distance   Calm 0.437    Normal 2.451    Stress 1.520   separation 1.083
```

The three state means for the return sit within a thousandth of each other. Naming a lean there
would be inventing attribution. **This is not an attribution of the label to a feature** in any
case — a Gaussian HMM decodes a path over a joint distribution and does not decompose into
per-feature contributions, so anything stronger would be a claim the model cannot support.

**No fake threshold.** Viterbi compares states against one another and never against a cut. The
page says *"No fixed shift threshold; the model chooses the most likely state"* and offers the
lead over the runner-up and the entropy in its place.

## 4. A performance regression I caused, found and fixed

Stage 5ZZP added the sleeve diagnostic and called `daily_slices` on **every request**.

```text
                                    before 5ZZQ      after
backend first request (any route)      ~62s          ~62s      pre-existing — see below
market view, own cold                   9.9s         11.0s
market view, WARM                       3.9s         0.02-0.23s
```

Of that 3.9s warm, `daily_slices` alone measured **3.24s**. It is now cached, keyed on the four
stores' **modification times** — not on a clock. A TTL would hand back a stale answer as a fresh
one for the length of the timer, which is the failure this route keeps finding in other clothes;
an mtime key invalidates the moment a store is appended.

### The ~62s is not this endpoint, and I nearly said it was

The first measurement read *"cold 95s"* and the obvious reading was that the new work had made
it worse. Measured properly: **the first request to a freshly started backend costs about 62
seconds whichever endpoint it is** — a cheap reader took 62.63s in that position, and the market
view took 11.0s once that cost had been paid by something else.

So the number belongs to backend startup, not to this route. It is **pre-existing and untouched
by this stage**, and it is recorded here as a named finding rather than folded into a figure
that would have made this stage look responsible for it. The page already survives it: the
market-view fetch is independent, so every other panel renders while it waits.

## 5. Dashboard

**Market View** gained a setup-conditions row under the chart — one card per condition with its
value, its threshold, and the distance when it fails, with the nearest failure the only one
emphasised. Colour alone would have made four cards shout at once. A sleeve whose entry forms
only after a bar signals says so in a sentence instead of showing empty cards.

**Regime Monitor** gained the full posterior as bars with the uncertainty in bits, and a
*"Why this label"* table: input, current value, 60-day percentile with a z-score, and the lean —
`no lean` where none can be claimed, with the reason on hover.

Both sit **outside** the chart's fixed box, so the pinned panel height is untouched: measured
across all three tabs at 375, 720 and 1440, the spread is 0px and no container overflows.

## 6. What is intentionally not exposed

```text
a price line for Stress          the setup is counts and an average, not a price
distance-to-entry for NKD/Swing  the entry comes from a per-bar signal function; publishing a
                                 distance would mean forming an entry the detector never formed
Calm phase diagnostics           DECIDE must not show OBSERVE-only values; unwired rather than
                                 wired wrongly (unchanged from Stage 5ZZP)
a regime threshold               Viterbi has none
per-feature attribution          a Gaussian HMM does not decompose; `leans` is a distance to a
                                 state mean and is named as such
```

## 7. Tests

**35** in `scratch/test_track1_stage5zzq_setup_boundaries_hmm_explain_20260828.py` — backend
contract, boundary classification with its source proof, metric values checked **against the
detector's own output**, the nearest-failure ranking, entropy checked against its definition
rather than against the implementation, the no-fake-threshold rule, cache behaviour, and DOM at
three widths.

One test asserts the **page computes nothing**: the added block is scanned for
`build_feature_matrix`, `predict_proba`, `Math.log`, `entry_conditions`, `peer_features` and
`breadth_min`, and every displayed number is shown to be addressed out of the payload.

### Two defects the tests caught

**The feature table overflowed 208px at 375px.** Four columns carrying *"Realised volatility,
5-day annualised"* do not fit a phone. A horizontally scrolling container would have hidden the
overflow rather than removed it, and the row would still have been unreadable — below 560px each
row is now a block with the input name on its own line.

**And a case-sensitivity slip of mine**, for the third time in these panels: an assertion pinned
to `Why this label` against a heading the stylesheet uppercases.

### Suites

```text
5ZZQ + 5ZZP + 5ZZL/M + dashboard backend + realtime contract + realtime DOM
  + ops + 5ZZO                                            423 passed, 0 failed
```

## 8. Safety, before and after

```text
orders_possible                False -> False
track1_blocking                ['PAPER_SHADOW_EVIDENCE'] -> unchanged
confirmation                   True -> True, untouched
scheduler                      pid 3000, track1-only-shadow, 0 legacy entry jobs, untouched
TRACK1_ORDERS_APPROVED         unset
track1_runtime/orders          ABSENT
broker order calls             0
trading decisions changed      0
```

Backend restarted three times during timing measurement — the read-only dashboard process only,
via `restart --no-scheduler`, which Stage 5ZZO made work and which leaves the scheduler alone.
Runtime evidence written: one appended regime-label record. No trading file touched.
