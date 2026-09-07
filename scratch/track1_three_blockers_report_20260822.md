# Track 1 — the three blockers, decided by measurement — 2026-08-22

Offline. No scheduler, runner, monitor backend or IBKR connection was started. No order. No
production path written. Nothing committed. None of the five legacy files edited.

---

## 0. What changed, in one place

| blocker | status | decided by |
|---|---|---|
| **SPY short gate** | **RESOLVED — it is part of the measured candidate.** Now encoded in the params identity as four fields | reading the generator that wrote the artifacts, plus a causality mutation |
| **fill law** | **measured on both laws, all three windows.** The production-feasible law is the cheaper one — see §2 | 12 regenerations through the shipped generator, anchored |
| **Track 1 bootstrap** | **gate closed** — the thing bootstrapped is the BOOK, not the per-instrument checkpoint, and all six carried decision fields are proved load-bearing | full replay vs resume at three cuts, ordered events exact |

---

## 1. The SPY short gate — it ships, and it is causal

### Is it part of the measured Normal-R4 candidate?

**Yes, and it is not part of the R4 context filter — it sits above it.** The generator that
*wrote* the committed promotion artifacts applies it unconditionally, before the context
filter is consulted:

```
scratch/normal_promotion_regen_audit_20260821.py:121   short_days = allowed_short_days(feature_frame(spy_csv), "below_sma50")
                                             :124   """SHORT gate (existing Normal config) + R4 context gate at the decision bar."""
                                             :131   if sig.get("direction") == "SHORT" and day not in short_days: return None
                                             :475   dump = scratch/normal_promotion_trades_<window>_20260821.json
```

That same file writes the `raw`, `filtered` and `filtered_prevbar` buckets, and the Track 1
book reads `filtered` through `load_normal` / `load_r4_and_nkd`. So the gate is inside every
Track 1 number already published. Its own comment calls it *"the existing Normal config"* —
it predates the R4 filter rather than arriving with it.

### Where is it implemented?

`scratch/directional_market_filter_probe.py:18-46`.

```
c   = spy.shift(1)                                     # the D-1 close
f["above_sma50"] = c > spy.rolling(50).mean().shift(1) # SMA50 through D-1
allowed_short_days(f, "below_sma50") -> ~above_sma50
```

### Is it causal D-1?

**Yes — proved by mutation, not by reading.** Multiplying SPY's close *at D* by ten leaves
the value at D unchanged and moves the value at D+1. The SMA recomputed from closes ≤ D-1
only is identical to the shifted rolling mean to 1e-9.

### Lookback and source

| | |
|---|---|
| lookback | **50** sessions (`spy.rolling(50).mean()`) |
| source | `spy_daily_live.csv`, the file the generator was invoked with |
| lag | **1** — both the close and the average are shifted |
| direction scope | SHORT entries only; LONG is never gated |

### What happens if it is removed?

Measured on all three windows, both levels. Sleeve standalone, one contract:

| window | sleeve | trades on → off | net with gate | net without | Δ net | Δ MaxDD |
|---|---|---|---|---|---|---|
| floor 2018-2024 | swing | 752 → 822 | 27,711 | 7,243 | **−20,469** | +5,170 |
| floor | NKD | 228 → 235 | 3,898 | 1,533 | **−2,365** | +2,400 |
| vault2025 | swing | 106 → 116 | 8,751 | 12,077 | **+3,326** | −498 |
| vault2025 | NKD | 31 → 30 | 2,203 | 1,908 | −295 | −41 |
| vault2026 | swing | 81 → 103 | 2,534 | −3,214 | **−5,748** | +580 |
| vault2026 | NKD | 26 → 27 | 4,292 | 6,243 | **+1,951** | −1,532 |

Through the guard, at book level:

| window | Δ net with the gate removed | PF | Calmar | MaxDD |
|---|---|---|---|---|
| floor 2018-2024 | **−11,663 to −14,143** | 1.68 → 1.50 | 2.17 → 1.35 | 4,973 → 6,527 (**+31%**) |
| vault2025 | +700 to +1,270 | 2.25 → 2.24 | 4.48 → 6.75 | 3,901 → 2,694 |
| vault2026 | **−1,701 to −3,682** | 1.65 → 1.44 | 3.59 → 2.91 | 4,342 → 4,342 |

**Keep it.** Removing the gate loses roughly $13.6k on the in-sample floor window and up to
$3.7k on 2026, against a gain of at most $1.3k on 2025 — and on floor it also raises the
book's worst drawdown by nearly a third. The one window that prefers the gate off does not
come close to paying for the two that do not.

**The gate is not additive.** Turning it off on vault2026 adds 22 trades but *changes* 58 —
a short taken earlier occupies the instrument and alters what comes after it. Any reasoning
that treats the gate as "the shorts it blocks" is wrong at the trade level.

**And it is not sleeve-local.** The book run reports `calm/stress same = False` on several
gate-off rows: removing a gate on the swing sleeve changes how many Calm and Stress trades
are admitted, through the caps and the same-symbol suppression. This was checked rather than
assumed, and the assumption would have been wrong.

### Encoded

`global_index/route_params.py` now carries four fields instead of two, because the rule
alone is not an identity without the file it read and the lag it read it at:

```
spy_short_filter          d1_spy_close_below_sma50_for_shorts_only
spy_short_lookback        50
spy_short_lag_days        1
spy_short_source_identity spy_daily_live.csv:<sha256>
```

Widening the contract turned **70 tests red** on the pinned field lists, which is what those
lists are for. Both were then updated deliberately and the suites are green again.

---

## 2. The fill law — measured on both, on the shipped generator

### How it was measured

Both axes are flipped by monkeypatching the ONE generator that produced the committed
artifacts, in process — `force_all_bars_gappable` replaced by a function that patches
nothing, `allowed_short_days` replaced by one that allows every session. Nothing is
re-implemented, because a second implementation of a rule proves nothing about the first.

**Anchor first.** The `artifact_gate_on` variant IS the shipped configuration, so its
regenerated table must equal the committed artifact exactly — same count and same ordered
rows per instrument. It does, on all three windows:

| window | committed trades reproduced |
|---|---|
| vault2026 | **107 / 107** |
| vault2025 | **136 / 136** |
| floor | **980 / 980** |

### Result

| window | sleeve | trades changed | Δ net (production − artifact) |
|---|---|---|---|
| floor 2018-2024 | swing | 2 | **+$1** |
| floor | NKD | 8 | **+$5** |
| vault2025 | swing | 0 | **$0** |
| vault2025 | NKD | 0 | **$0** |
| vault2026 | swing | 0 | **$0** |
| vault2026 | NKD | 2 | **+$3** |

At book level, across all three windows and all five policies: **$0 to +$6**. Floor, the
seven-year window, moves +$4 on three policies and +$6 on two — against a book netting
$75,288.

### The direction matters and was stated backwards before

The production law is the **more permissive** of the two: it fills at the stop unless a real
break of more than 15 minutes preceded the bar, while the artifact law treats every bar as
gappable and fills at the worse open. So the production law is worth *slightly more*, not
less — the published Track 1 numbers were measured under the **more conservative** law.

Two independent runs now agree on the magnitudes — ~$5 on floor, $0 on 2025, ~$3 on 2026 —
matching the figures carried in the earlier notes. What those notes had wrong was the sign:
they recorded it as a cost of the production law.

### Recommendation

**Adopt `production_gap_after_15min_break` as the Track 1 identity.** It is the law the live
engine actually runs, it is measurably free — under $6 across seven years, on a book netting
tens of thousands — and it errs in the safe direction relative to what was published. Track 1
does **not** need re-rating on this axis: the largest change to any headline metric is inside
rounding.

---

## 3. Stage 2C — the bootstrap that has to exist

### What Stage 2B's file could not do

The Stage 2B checkpoint records one thing per instrument: the swing engine's open position.
The Track 1 book carries strictly more across a day boundary, and each of these decides which
trades are **admitted**, not merely how they are reported:

| carried | why it decides admissions |
|---|---|
| `open_pos` with cluster and risk | the cap gate reads it |
| `equity` | drives the circuit breaker |
| `peak_equity` | `CircuitBreaker` keeps it **across** days; drawdown is measured from it |
| `_day_start_equity` | the −4% daily rule is measured from it |
| `cur_day` | decides when `start_day()` re-bases that rule |
| `booked` | the double-settlement detector |

Seeding only the engine positions resumes a book whose breaker believes it is at its all-time
peak. **So the Track 1 bootstrap is a bootstrap of the book; Stage 2B's file is one component
of it.**

### The equivalence gate on the tool itself

`replay()` in `scratch/track1_stage2c_book_bootstrap_20260822.py` is a re-host of the
committed `replay_repaired` with two seams added. It is not trusted: with both seams unused
it must reproduce the committed function's daily series and every counter exactly, for every
policy, before anything else runs. It does — 5/5 policies on vault2026, nets matching to the
dollar (9,779 · 9,288 · 9,853 · 8,260 · 8,825).

### Reproduction: full Track 1 vs resume-from-bootstrap

Cut 2026-05-29, two positions carried, equity 54,462.01, peak 54,993.56.

| policy | events resumed / expected | ordered list | open positions | metrics |
|---|---|---|---|---|
| repaired_mechanics_independent_cap | 49 / 49 | exact | exact | exact |
| repaired_mechanics_family_cap_5_44 | 45 / 45 | exact | exact | exact |
| repaired_mechanics_family_cap_7p5 | 47 / 47 | exact | exact | exact |
| risk_clean_no_calm_nkd (a) | 32 / 32 | exact | exact | exact |
| risk_clean_no_calm_nkd (b) | 34 / 34 | exact | exact | exact |

### The cut cannot be a calendar day, and that took two attempts to see

The first attempt failed by exactly one event on every policy: the head stopped at the first
timestamp of the cut day while the resume skipped the whole day. Moving the stop to the day
boundary fixed vault2026 — and was still wrong.

Floor exposed the real defect. The loop runs in **absolute time**, but `_day()` strips the
timezone without converting it. MNKD carries a Tokyo session date, so the event stamped
`2022-01-11 00:00+09:00` actually occurs at **10:00 ET on 2022-01-10** — earlier than that
same afternoon's ET events at 10:35 and 14:01. A day-keyed cut is therefore **not a prefix**
of the sequence: the head broke at the Tokyo-dated event because its local date was already
past the cut, the resume skipped everything whose local date was not, and the two ET events
in between ran in **neither half**. One of them was a Stress override that closes a Normal
position early, so the resumed book carried a position the real book had already closed, and
the divergence cascaded from there.

```
FULL    2022-01-11 00:00+09:00  MNKD_112   -271.40     <- absolute 2022-01-10 10:00 ET
        2022-01-10 10:35-05:00  MNQ_92     -888.74     <- lost by the day-keyed cut
        2022-01-10 14:01-05:00  STRESS_MNQ -3,346.30   <- lost by the day-keyed cut
RESUME  2022-01-11 00:00+09:00  MNKD_112   -271.40
        2022-01-12 09:30-05:00  MNQ_92     +575.76     <- still open, wrong book
```

The fix is to make the cut an **absolute instant** — the last event whose local date is still
within the cut day — and to split on `ts <= cut_instant`. The bootstrap now records
`cut_instant` alongside the human-readable `cut`, and a bootstrap written by the old
day-keyed cut is refused rather than resumed.

**This generalises beyond this harness.** Any Track 1 resume keyed on a calendar day is wrong
for a book that mixes an ET session with a Tokyo one, and the error is silent — it produces a
plausible, slightly different book rather than an exception.

### The cut is an instant now, and the old form is refused

`cut_day` is gone as a resume key; the bootstrap splits on **`cut_instant`**, the last event
whose local date still falls inside the cut day. `cut` survives only as a human-readable
label. A bootstrap written by the old day-keyed cut carries no `cut_instant` and is
**refused**, not resumed — verified rather than claimed:

```
new bootstrap schema : 2 | cut: 2026-05-29 | cut_instant: 2026-05-29 14:50:00+09:00
REFUSAL GATE enforced: bootstrap has no cut_instant — it was written by the old day-keyed
                       cut and cannot be resumed correctly
control still resumes: 49 events
```

Note the instant on that line: the vault2026 cut resolves to a **Tokyo** stamp, 01:50 ET.
That window reproduced exactly both before and after the fix only because no event happened
to be stranded between the two boundaries — the defect was always there, it simply had
nothing to bite on.

### Every carried field, and whether it is load-bearing

Three cuts on `floor`, the only window where the circuit breaker binds (`halted = 2`): end of
2022-01-10, inside 2022-11-07, and the isolation run. **Control matched at all three**
(726/726 · 727/727 · 577/577), which is what makes the rest mean anything.

| field | probe | result | verdict |
|---|---|---|---|
| `open_pos` | forget all / drop one | diverges — 725/727 · 576/577 | **load-bearing** |
| `equity` | reset to the account size | diverges — 2/727 · 1/577 | **load-bearing** |
| `peak_equity` | raised 20%, drawdown past the hard cap | diverges — 2/727 · 1/577 | **load-bearing** |
| `risk` | × 20, eats the cluster cap | diverges — 724/726 | **load-bearing** |
| `day_start_equity` | raised so the daily loss reads −10% | diverges — 575/577 | **load-bearing** |
| `cluster` | × 20 risk in `global_nkd` vs × 20 risk in place | **724 vs 725 events** | **load-bearing** |
| `booked` | cleared | matches | **not a decision input** — it feeds only the double-settlement counter, and the control pins that claim |

`cluster` needed an isolation rather than a straight probe. Changing it alone never moved
anything, because the caps had headroom; changing it together with an inflated risk diverges,
but so does the risk on its own. The clean separation is **same risk, different bucket**:
risk × 20 in place gives 724 events, risk × 20 moved to `global_nkd` gives 725. The
difference is attributable to the cluster and to nothing else.

Three things this cost, each worth keeping:

**A single cut proves less than it looks.** `risk` went red on 2022-01-10 and matched on
2022-11-07; `day_start_equity` did the opposite. Caps and the breaker only bite near a
threshold, so a load-bearing field can still leave a green run.

**A relaxing mutation cannot go red.** The first attempts *lowered* `peak_equity` and
`day_start_equity`, which only loosens a rule that was not binding. They were reported as
failures when they were measurements of nothing. They are now declared controls that must
MATCH, and the probes raise the values instead.

**`day_start_equity` needs a cut with a later entry the same day**, since the next
`start_day()` overwrites it. The cut for it was chosen by listing the 34 sessions in
2021-2022 carrying three or more distinct entry instants — not by guessing.

## 4. Reproduction under the chosen fill law

Stage 2C re-run with the `production_gate_on` tables swapped in — the production fill law
and the confirmed SPY gate, which is the configuration a deploy would actually run:

| policy | events resumed / expected | ordered list | open positions | metrics |
|---|---|---|---|---|
| repaired_mechanics_independent_cap | 49 / 49 | exact | exact | exact |
| repaired_mechanics_family_cap_5_44 | 45 / 45 | exact | exact | exact |
| repaired_mechanics_family_cap_7p5 | 47 / 47 | exact | exact | exact |
| risk_clean_no_calm_nkd (a) | 32 / 32 | exact | exact | exact |
| risk_clean_no_calm_nkd (b) | 34 / 34 | exact | exact | exact |

The swap is visible in the gate line rather than merely asserted: the two `risk_clean`
policies read 8,263 and 8,828 under the production law where they read 8,260 and 8,825 under
the artifact law. That $3 is the fill-law difference arriving through the book, and it is
what proves the variant tables were actually in force.

---

## 5. Verdict

**The Stage 2C bootstrap gate closes.**

| | |
|---|---|
| filters | confirmed — the SPY gate is in the measured candidate, encoded as four fields |
| fill law | measured on both; the production law is chosen, $0 to +$6 over seven years |
| reproduction under the chosen law | **exact** — 5/5 policies, ordered events, open positions, metrics |
| cut correctness | fixed to an instant, old form refused, controls match at three cuts |
| carried state | **all six decision-carrying fields proved load-bearing**; `booked` proved diagnostic |

What this does and does not license. It licenses the claim that **the bootstrap and resume
reproduce Track 1 exactly, under the fill law and the filters a deploy would run**, and that
nothing the book carries across a day is missing from the file. It does not by itself make
Track 1 live: the gates recorded earlier are untouched by this work and still govern —

| still open, separately | |
|---|---|
| **R0 host availability** | 8 of the 9 most recent trading days had an S3 suspend; the idle timer is already off, so `STANDBYIDLE 0` is not the remedy on this host |
| **route wiring** | no route runs; `run_live_day --checkpoint-path` exists but nothing points at it |
| **scheduler** | `_catch_up_maxhold` is startup-only; `_maxhold_done` / `_preflight_ok` are date-keyed and need a route dimension before a second route shares the process |
| **telemetry phases** | `ckpt_load`, `ckpt_verify`, `bars_fetch_incremental`, `sleeve_update`, `ckpt_advance_write`, `oracle_replay` — belong with the route code |

## 6. Files

| file | role |
|---|---|
| `scratch/track1_fill_shortgate_regen_20260822.py` | 2×2 regeneration through the shipped generator, with the anchor gate |
| `scratch/track1_fill_shortgate_measure_20260822.py` | sleeve-level and book-level measurement, with a wiring check |
| `scratch/track1_stage2c_book_bootstrap_20260822.py` | the book bootstrap, its equivalence gate and the reproduction proof |
| `scratch/track1_variants_20260822/` | 12 variant trade tables plus the three anchor records |

A note on one of those wiring checks: the first book-level run returned **zero delta for
every variant**. That was not a result — `audit.load_all` memoises per window, so every
variant after the first silently replayed the first one's trades. A table of clean zeros is
what a broken measurement looks like. The fix clears the cache and then asserts the book is
actually holding the variant's trade counts before any number is read.

---

## Addendum, 2026-08-23 (Stage 5M-1): the implementation has caught up

*Append-only. Nothing above is restated or revised — this records that the recommendation in
§2 was, until today, a recommendation the code did not follow.*

### What was wrong

§2 adopted `production_gap_after_15min_break` as the Track 1 identity. The code kept running
the other one. `NormalR4Params.fill_law` defaulted to the artifact law, and five places took
that default:

* **Four in the route** — the string recorded in the identity hash on every shadow explanation,
  every route checkpoint, and every checkpoint comparison.
* **One in the engine** — the live sleeve source built its engine parameters without naming a
  law, so the artifact law decided which bars were gap-eligible and therefore **which trades
  exist**, not merely what a hash said.

That fifth one is the one worth remembering. It contains no `fill_law` token anywhere, so the
search that found the other four walked straight past it. Patching the four callsites would
have left the trap armed, and left it armed on the only path where the law changes behaviour
rather than bookkeeping.

### What changed

The engine default is now the **production** law, and reproducing a committed artifact is the
**explicit** case — `fill_law=FILL_ARTIFACT`, said out loud. That is the right way round: the
default is what the live route runs, and reproducing history is the special request.

The route no longer reads the engine's default at all. Its law has one name,
`track1_params.LIVE_FILL_LAW`, and every live and shadow callsite reads that. An identity is a
route decision; taking it from an engine default meant it followed whatever that default
happened to be.

### Reproducibility is unchanged

The Stage 4 reproduction still matches the committed rows exactly, now by asking for the
artifact law by name. The anchor in §2 — 107/107, 136/136, 980/980 — is untouched, because
nothing about how those rows were generated has changed. Only the request for them is explicit.

### Why an immaterial delta was still worth a stage

§2 measured the difference at **$0 to +$6** across seven years against a book netting $75,288,
and that number has not moved. This was never about P&L.

The fill law is hashed into `params_hash`, and a route checkpoint is **accepted or refused** on
that hash. A route whose identity names a law it did not run would accept state computed under
the other one — a position seeded into a live book by an engine that would never have held it.
Stage 4B removed exactly that defect when the law was a hard-coded literal in the params
module. A default nobody passed is the same defect wearing a different hat, and it survived
Stage 4B because a default does not look like a decision.

**The delta stays immaterial. The identity is mandatory.**
