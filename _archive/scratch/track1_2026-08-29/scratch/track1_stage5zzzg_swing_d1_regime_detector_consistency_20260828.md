# Stage 5ZZZ-G — the Swing regime object: what it is, and what the backtest actually uses

**Route:** `track1_candidate` · **Date:** 2026-08-29 (measurements taken on the 2026-08-28 session)
**Orders:** never enabled, still impossible

---

## The short answer

**Half of the brief's premise is confirmed. The other half is contradicted by the code and by measurement, so the fix it asks for was not made.**

| the brief said | measured |
|---|---|
| the outer live gate uses `causal_regime_label` | **yes** |
| the inner detector calls `labels.get(day)` | **yes** |
| raw labels are passed into the Swing detector, so it sees same-day/None while causal D-1 exists | **yes — confirmed on 2026-08-28** |
| **Track 1 Swing identity is D-1/causal** | **not supported.** The Track 1 Swing backtest runs the same `labels.get(day)` against the same raw map |

Passing a D-1 object into the Swing detector would therefore **not** restore parity with the backtest — it would break it, on **93 of 235 entries**. That is a decision with a number attached, and it is not mine to make quietly inside a consistency stage.

**What was implemented** is the part that is safe and that the brief also asks for: the diagnostics now report **which regime object the detector was handed**, so the panel can explain a disagreement it previously just displayed.

---

## 1. The mechanism, measured

A label for session D is produced from D's own close:

```python
for d in test_days:
    window = daily[daily.index <= d]
    labels[d] = eng.state_name(eng.predict_current(window))   # needs D's close
```

SPY closes at 16:00 ET. The Swing window is **14:05–15:55 ET**. So D's label cannot exist while Swing is deciding — and on the evening of 2026-08-28 the map's last entry was still **2026-08-27**.

```text
2026-08-28   same-day raw = None      causal D-1 = 'Calm'      RegimeLabels(lag 1) = 'Calm'
2026-08-27   same-day raw = 'Calm'    causal D-1 = 'Calm'      RegimeLabels(lag 1) = 'Calm'
```

Run through the detector itself, same bars, same params, same day:

```text
raw map  (what live Swing passes)   regime gate -> value=None    passed=False
lag 1    (what live NKD passes)     regime gate -> value='Calm'  passed=False
```

**Both refuse today**, and that nuance matters: this sleeve trades `Normal` only, and the label is Calm. Today the outcome is identical and only the *reason* differs. On a day when D-1 is Normal and D's row is absent, the outcome would differ — one refuses on a missing label, the other trades.

---

## 2. What the authoritative backtest passes

This is the correction, and it is the part I was asked to prove rather than assume.

The Track 1 Normal-R4 engine states the identity in its own entry point:

> *"Labels and params are PER INSTRUMENT rather than shared, because they genuinely differ: **R4 reads the SPY labels directly** at ema 50, while **MNKD reads them through `RegimeLabels(lag_days=1)`** at ema 10."*

And the backtest's day loop is the same lookup the live detector uses:

```python
for day in cache["days"]:
    reg = labels.get(day)          # scan_signals, and again in _replay
    if reg not in ALLOWED_REGIMES: continue
    ... _scan_window(..., bars5.between_time("14:00", "15:55"), reg, ...)
```

Every caller that produces the record follows that split — raw for the swing basket, `RegimeLabels(lag_days=1)` for NKD. So the Swing backtest gates a 14:00 decision on a label computed from that day's 16:00 close.

**Measured, not argued** — the sleeve's own backtest run twice over the full store, identical in every input but the labels object:

```text
                            trades     pnl
raw labels (D's own)          186   -4,345.29
RegimeLabels(lag_days=1)      191   -7,401.32

entries only in raw : 44
entries only in lag1: 49
shared              : 142
```

The two objects disagree on **238 of 2,175 days (10.9%)**, and that propagates to **93 of 235 entries**. Swapping the object is not a no-op dressed as a consistency fix.

---

## 3. Why I did not make the change

The brief's own verification list requires *"Historical decision parity remains unchanged where applicable"* and *"No trading thresholds, schedules, gates or order behavior changed."* Passing D-1 into the Swing detector fails both, by the numbers above.

There is a real defect here, and it is **not** the one the brief describes. It is this:

- **In the backtest**, `labels.get(D)` returns a label built from D's close and uses it to decide D's 14:00 entry. That is information from after the decision.
- **In live**, the same call returns `None`, because the row does not exist yet — so the sleeve fails closed instead of reproducing it.

The live path is the honest one. The backtest is the one that cannot be reproduced. The live source already carries a helper that says exactly this, and it guards the **outer** gate only:

> *"A morning slot that reads today's own label is reading a row computed from today's close — six hours of the future — and it would not look wrong, because the label would be present and plausible."*

Fixing that means re-earning the sleeve's numbers under a causal label, not editing a call site. It is a decision about the strategy's justification, and it needs the operator.

**Also stated plainly:** whether this has cost anything live is **not measurable from the shadow window**. Swing has produced no signal in every recorded session, but the regime has been Calm throughout and the sleeve trades Normal only — it would have refused either way. The confound is total, and I am not claiming a live impact I cannot separate.

---

## 4. What was implemented

The panel showed `Regime: Calm` for NKD and `Regime: Unavailable` for Swing on the same session, from the same detector, with nothing to explain it. Both values were correct; the page could not say why they differed, and an operator cannot audit a difference nobody names.

The diagnostics now carry the **basis** — described from the object that was actually passed, never from the sleeve's name:

```text
global_nkd     regime_basis = "previous session (lag 1)"      Regime = Calm
roska4_swing   regime_basis = "this session's own label"      Regime = Unavailable
```

and the Regime row's detail reads *"this session's own label — handed to the detector, not computed here."*

Three properties hold by construction:

- **It is derived.** `regime_basis()` reads `lag` off the object; a hand-written sleeve→basis map would go stale the first time a call site changed and would then say the opposite of what the detector saw. A mutation replacing it with a guess goes red.
- **It is the detector's own value.** A test asserts the Regime row equals the observer's regime **gate** value — not a second lookup done for display.
- **It is absent rather than guessed.** A block built without a basis reports `""`, and its row claims neither basis.

The reconstruction was already mirroring the live object per sleeve; that is now pinned, because a reconstruction handed a *different* regime object would show what the slot did **not** see, which is worse than showing nothing.

---

## 5. Results

| | |
|---|---|
| New suite | **18 passed** |
| Regression across the diagnostics suites | **184 passed** |
| Mutation harness | **8/8 red**, files restored byte-identical |
| Trading decisions changed | **none** |

One mutation anchor matched twice on the first run and was reported as **HARNESS BROKEN**, not as a pass — a mutation applied in two places is not the mutation described. Retargeted, then red.

A guard test now fails if any sleeve changes which object it hands the detector, with the 44/49 measurement in its message, so the swap cannot arrive as a quiet edit.

### Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
orders dir ABSENT · TRACK1_ORDERS_APPROVED unset · confirmation intact · no broker call
gates · schedules · thresholds · strategy decisions — untouched
```

`track1_live_source.py` was touched, and only to pass the labels object it *already had* into the diagnostics stash as a descriptive string. No detector argument changed. A test asserts the detector module never reads `regime_basis`.

---

## 6. The decision this leaves open

The Swing sleeve's regime gate reads a label that, in live, cannot exist at decision time, and in backtest is drawn from after the decision. Three ways forward, with what each costs:

1. **Make Swing causal (D-1), re-earn the numbers.** Honest live behaviour; the sleeve's backtest justification has to be re-measured — 93 of 235 entries move, and the raw-vs-lag1 run above is a first read, not a verdict.
2. **Keep the identity and accept that live Swing refuses whenever D's row is missing.** No re-measurement, but the sleeve then trades on a rule the live route can never execute.
3. **Establish whether D's row can legitimately exist before 14:05** — the earlier open question about a partial daily bar. If it can, the premise changes; if it cannot, option 2 is a sleeve that never fires.

I have no basis for choosing among these, and the choice moves a gate. It belongs to the operator.
