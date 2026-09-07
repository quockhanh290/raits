# Stage 5ZZZ-Q — the live Swing detector now reads the previous session's label

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

## A constraint conflict, resolved before any edit

The brief required fixing the live Swing path and also said *do not edit runtime trading files* — and the live Swing decision lives at `global_index/track1_live_source.py:1124`, imported directly by `run_live_day_track1.py`. I stopped and asked rather than picking a reading. **The operator authorised the live fix and the evidence fields.** Everything below follows that authorisation.

---

## 1. What changed

Three lines of substance, in three files.

### The live decision — `track1_live_source.py`, `_swing_candidates`

```python
# before
labels = self._label_map()                       # raw map
regime = causal_regime_label(labels, day)        # outer gate: strictly before `day`
setup  = NR.detect_entry_for_slot(frame, labels, ...)   # detector: labels.get(day) -> the
                                                        # session's OWN row -> None at 14:05

# after
swing_labels = RegimeLabels(pd.Series(labels)…sort_index(), lag_days=1)
setup = NR.detect_entry_for_slot(frame, swing_labels, ...)
self._stash_diagnostics("roska4_swing", inst, params, _obs, setup, labels=swing_labels)
```

`RegimeLabels(lag_days=1)` is not a new rule. It is exactly what the NKD path forty lines above already passed, and exactly what the artifact regeneration wraps its labels in. The outer gate and the detector now read the same object.

### The evidence — `run_live_day_track1.py`, `track1_signals.py`

`SignalRow` gains **`regime_basis`**, written from a map that names what each call site does:

```text
global_nkd      causal_d1                 RegimeLabels(lag_days=1), always was
roska4_swing    causal_d1                 RegimeLabels(lag_days=1) as of this stage
roska4_stress   intraday_basket_gate      decided at 10:30 from the session's own bars
roska4_calm     causal_d1                 the entry gate reads the previous session's label
```

It defaults to `""`, so every row written before today stays readable and is reported as *not applicable* rather than assumed to match.

### The replay side — `track1_market_view.py`

The reconstruction now lags Swing's labels too. It exists to show what the slot saw; a replay handed a different regime object would show what the slot did **not** see.

---

## 2. Proven, from the call and not from the code

`detect_entry_for_slot` was intercepted on the live path and asked what it was handed:

```text
LIVE Swing, 2026-08-28
  MES   RegimeLabels(lag=1)   resolved -> 'Calm'
  MNQ   RegimeLabels(lag=1)   resolved -> 'Calm'
  MYM   RegimeLabels(lag=1)   resolved -> 'Calm'
  M2K   RegimeLabels(lag=1)   resolved -> 'Calm'

LIVE NKD, unchanged
  MNKD  RegimeLabels(lag=1)   resolved -> 'Calm'
```

Before the change that same call resolved **`None`** — which is why the sleeve refused every session. And independently of the wiring, on all **190** floor sessions where the same-day and previous-day labels disagree, the object returns the previous session's value and never the session's own.

## 3. The params hash: an honest empty, and why

Stage 5ZZZ-P found `params_hash` empty on every live row. I tried to fill it and found the reason is a deliberate contract, not an oversight:

> `route_params: missing required field(s) ['arm_hour', … 'data_source_identity', … 'tick', 'tradable_symbol']. Every field in ALL_FIELDS must be supplied explicitly — an absent field is refused, not defaulted, so two configs cannot hash alike because one forgot to say.`

The canonical identity includes `data_source_identity`, which is `path:sha256` of the parquet. Hashing a multi-gigabyte file on every slot would put real work on the decision path for a diagnostics field — the same reason `_signal_data_identity` records the path alone. **A cheap hash would be exactly the partial identity that module forbids**, so the helper now returns empty *deliberately*, says so, and points at the explanation record, which already writes the full `path:sha256` for the same run. Parity should join it from there.

## 4. Reproduction — the selected baseline is unchanged

The live path is not the artifact path (`deploy_sim` → `SwingTFEngine`), so the change cannot reach it — and that was verified rather than assumed. Artifacts byte-identical, replay re-run:

| Window | Full stack | expected | Risk-clean | expected |
|---|---:|---:|---:|---:|
| floor *(in-sample)* | **+$66,796** | +$66,796 ✓ | **+$57,289** | +$57,289 ✓ |
| 2025 *(OOS)* | **+$16,181** | +$16,181 ✓ | **+$12,419** | +$12,419 ✓ |
| 2026 *(OOS, partial)* | **+$8,105** | +$8,105 ✓ | **+$7,077** | +$7,077 ✓ |

`SWING_TF_PARAM` unchanged. `NormalR4Params` unchanged — ema 50, stop basis 2.0, chandelier 2.5, hold 5, `rel_volume_max` 2.0, `vol_feature` rvol_slot20. Artifact hashes `2474723814ae3e92` / `c27ca3902b116912` / `1ee198a9f10387c8`.

## 5. Parity

Two verdicts added so old evidence is **described, not judged by rules it predates** — and never rewritten:

- **`PRE_FIX_MISMATCH`** — the row disagrees with today's code, and yesterday's code wrote it.
- **`NOT_APPLICABLE`** — the field did not exist when the row was written.

Neither is a `PASS`. The 2026-08-28 Swing row is now `PRE_FIX_MISMATCH`, with its basis check `NOT_APPLICABLE`; the whole run still reports `NOT_YET_OBSERVED` for all four sleeves, because no session has run since the fixes.

**Can parity `PASS` on the next post-fix Swing slot? Yes.** A row that records `regime_basis: causal_d1` against a detector on the lagged object now scores `PASS` on that check — proven by test. The remaining `UNKNOWN` on `params_hash` is the §3 gap, and it caps a post-fix slot at `UNKNOWN` until parity joins the identity from the explanation record. **That is the one thing standing between a post-fix Swing slot and a full `PASS`, and it is named rather than papered over.**

## 6. Tests

**134 passed** across six suites. The new suite (14) pins: the live Swing detector receives `RegimeLabels(lag=1)`; it is not a raw dict; it resolves a label at slot time where it used to resolve `None`; NKD is unchanged; the two Normal-R4 sleeves now agree; the object returns the previous label on every disagreeing session; the row records the basis; the basis map is checked **against the live source**, not trusted; a pre-stage row has no basis and is not assumed to match; the empty params hash is honest and documented; no parameter moved; the metadata cannot open a gate; and the baseline artifacts are untouched.

**Four earlier tests were restated, none deleted.** Stage 5ZZZ-G's guard asked *"Swing now builds a lagged object; who decided?"* — the operator did, today, on the record and after Stage 5ZZZ-H measured the cost. It is **inverted, not removed**: Swing must now keep the causal object and NKD must never lose it. The payload test that asserted the two sleeves disagree now asserts they agree, because removing that disagreement at its source was the point of this stage.

---

## 7. Answers

| question | answer |
|---|---|
| Live Swing detector uses causal D-1 | **Yes** — `RegimeLabels(lag=1)` on all four instruments, verified at the call |
| Backtest / artifact / live identities match | **Yes.** All three now read the previous session's label; before today only the first two did |
| Params changed | **No.** `SWING_TF_PARAM` and `NormalR4Params` byte-for-byte as before |
| Selected baseline reproduces | **Yes** — all six figures, artifacts byte-identical |
| Evidence fields added | **`regime_basis`** on `SignalRow`; `params_hash` left honestly empty with the reason recorded |
| Parity can PASS on the next post-fix Swing slot | **On the basis check, yes.** Full-slot `PASS` still blocked by the params-hash gap in §3 |

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
confirmation             present, approves no orders
swing paper override     present, valid, grants nothing
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
broker calls             ZERO
scheduler                pid 3000, track1-only-shadow, NOT restarted
backend                  pid 10136, NOT restarted
gates                    untouched · thresholds untouched · params untouched
PAPER_SHADOW_EVIDENCE    not marked satisfied, and nothing here could
```

**One thing the operator should hold in view.** Live Swing previously refused every session because its detector resolved no label. It will now decide. Orders remain impossible, so nothing can be sent — but the sleeve's shadow decisions, which are the input to `PAPER_SHADOW_EVIDENCE`, change from "always refuse" to "actually deciding" from the next session onward. That is the intended effect of the authorised fix, and it is the first change in this sequence that alters what the live route does rather than what it records.
