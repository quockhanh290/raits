# Stage 5ZZZ-F — the panel that contradicted itself

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## The answers

| question | answer |
|---|---|
| Diagnostics visible per sleeve | NKD/Swing: trend filter, close, price-vs-EMA, ATR, volume and its ratio, regime, setup state, nearest miss · Stress: four gate metrics + trigger / planned stop / session open, muted while unarmed, with the hour the gate was decided · Calm: DECIDE and OBSERVE as two cards · Regime: label, posterior, confidence, runner-up, lead, entropy, both model inputs, **and the absent threshold named** |
| Does the frontend compute anything strategy-like | **No** — asserted three ways, including a mutation |
| Layout at 375 / 720 / 1440 | **Passes**, and two real overflows were fixed to make it true |
| Gate / order / runtime trading file changed | **None.** No runtime trading file was modified |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |

**A backend restart IS required** for these changes to reach the page — `monitor/backend/track1_market_view.py` changed and pid 44968 is serving the module it loaded at startup. Not done here; it is the operator's call. The scheduler (pid 3000) is untouched and must stay that way.

---

## 1. The panel was contradicting itself, and the payload proved it

The stage began by building the payload and reading it, rather than by reading the page and forming a view about it. The first sleeve printed settled the question:

```text
roska4_stress
  levels_note   "Strategy levels unavailable"
  setup_boundary.price_levels
      Trigger (pre-session low)   29,592.50
      Planned stop                29,652.62
      Session open                29,615.25
```

The chip above the card said the levels were unavailable while the card below it drew three of them. The note was computed from the **signal rows** — where levels used to come from before four diagnostics stages started publishing them elsewhere — and it had gone on answering a question that was now being answered somewhere else.

A panel that contradicts itself in two places costs more than one that says nothing, because the reader has to work out which half to believe and the page gives them no way to do it.

The note now describes what the panel **can actually show**, from any source, and keeps three states apart because they are three different facts:

```text
levels exist and are ARMED       nothing to say; the chart draws them
levels exist and are NOT ARMED   "computed at 10:30 but not armed - the gate did not pass"
no levels at all                 the original note, unchanged
```

The payload-wide note is now **derived** from the sleeves instead of asserted before any of them is built, and it stays silent when they disagree — one string cannot describe three sleeves that no longer say the same thing.

---

## 2. What else the payload was not saying

**Every strategy block was unlabelled.** `diagnostics_source` existed only one level down, at `strategy.diagnostics.diagnostics_source`, so anything reading the strategy block itself got an answer with no provenance on it. An unlabelled reconstruction reads as a recorded one, and telling those two apart is the single thing the diagnostics stages exist for. Every block now declares its source at the top, Stress included.

**The Stress gate had stopped saying when it was decided.** Four metric values with no hour attached read as this minute's; they are the 10:30 bar's. The only surviving mention was inside the sentence about unarmed levels — which does not appear at all on a day the gate passes. The hour is now published from the detector's own `setup_time` rather than spelled into the page's markup.

**The absent shift threshold had stopped being named.** Stage 5ZZP deliberately moved that invariant off the score and onto the threshold, which genuinely does not exist. The rebuild left one mention: a *fallback* on the Lead note, which never renders because the record always supplies `margin_name`. So the panel showed a lead, a confidence and a runner-up, and nothing anywhere told a reader that the number they were looking for — how close is it to flipping — does not exist. It is a row of its own again, carrying the record's own sentence about why a Viterbi decode has no cut to be near.

---

## 3. Two real layout defects, both measured

**The plot's height came from its content.** A populated tab measured 437px and a tab whose session had no bars measured 116px, so switching between them moved every panel below the chart. The stylesheet that was meant to prevent this says so in its own comment — *a panel that resizes under the pointer is a panel an operator misclicks* — and it was pinned to the outer host, which the rebuild stopped being the element that holds the plot.

Fixed by giving the plot a box and putting the empty state in the same box. Then measured again, and the residual was attributed rather than tolerated:

```text
                 populated     empty
  plot            320          320      <- fixed
  card head        41.89        40.39   <- the remaining 1.5px
  card            404.88       403.38
```

1.5px is not much to look at, but it is the whole card moving on every tab switch, and it had the same cause: content setting the height of a box an operator clicks in. The head is pinned too. The legend needed the same treatment for the same reason by a second route — it renders only when there are bars, so in the flow it added 40px to a populated tab and nothing to an empty one.

**A chip carrying a sentence could not wrap.** `white-space: nowrap` is right for "22/22 SLOTS" and wrong for "Trigger levels were computed at 10:30 but are not armed", which ran 10px past the right edge at 375px. The fix carries `box-sizing: border-box` deliberately: `max-width: 100%` on a content-box element resolves to 100% **plus** padding and border, which is how Stage 5ZZR shrank an overflow twice without removing it.

**And one the stage introduced.** Adding the decision hour pushed the card head 20px past its box at every width. A flex item's default `min-width: auto` refuses to shrink below its own text, so `flex-wrap` could not save it — a single item that cannot shrink has nowhere to wrap to.

---

## 4. Calm has its own band now

Stage 5ZZZ-E put Calm outside the sleeve tabs, because it is two instants half an hour apart under a contract forbidding the first from seeing what the second learns, and one tabbed card is where that leak would live. It was still rendering **inside** the market-view band, at the end of the sleeve renderer — so on the NKD tab the page showed NKD's chart, NKD's setup card, and then two Calm cards with nothing between them saying the subject had changed.

It renders once now, into its own headed band, whichever tab is selected. The band hides rather than standing empty: an empty headed band reads as a panel that failed, and Calm having nothing to say is not a failure.

---

## 5. The fourth word

The page had three source words and no way to say the backend could not read something. **"I could not check" and "I checked and there was nothing" are opposite facts** about whether the panel can be trusted, and rendering them identically throws the difference away. `UNAVAILABLE` is now shown only when the backend hands over an explicit error — never inferred from an empty payload — and both sides are tested, so the rule cannot be satisfied by never showing the word at all.

---

## 6. Nineteen tests restated, and why none were weakened

The market view was rebuilt to `mv2-*` markup between stages, and nineteen assertions across three earlier suites were still describing the panel that came before it. Every one was classified before it was touched: **stale selector or wording** in fourteen, and **a real defect the test was right to catch** in five.

The five that were right:

| what it caught | what was done |
|---|---|
| the chart height changing between tabs | fixed (§3) |
| the legend changing the height | fixed (§3) |
| the absent threshold no longer named | fixed (§2) |
| the Stress gate's decision hour missing | fixed (§2) |
| the 60-day regime run no longer dimmed | restored |

That last one is worth a sentence. The rule was overridden by `.regime-strip .regime-run { opacity: 1 }`, whose comment explains the height and the gap and says nothing about the opacity — which is the tell that the reset was collateral rather than a decision. Sixty cells at full strength read as a barcode and pull the eye off the last-N row, which is the row that gets read.

Two restatements changed a claim rather than a selector, and both are stated:

- **The strip legend** printed a fixed four-word list including "Crisis" for a **three-state model** — a legend entry for a state the model cannot emit. It is derived from the states the payload declares, and the assertion is now the relationship rather than the literal list.
- **A stub was lying.** One DOM test fed the page the wording the backend stopped emitting in Stage 5ZZM and then demanded the page not show it — which is asking a page to censor its own data source. The fixture was the stale thing.

---

## 7. What the mutations found

Twelve mutations, each restored byte-identical. **Eight went red on the first run and four came back green** — and all four were findings about the tests rather than passes:

| | |
|---|---|
| M7 the legend goes back into the flow | a text slice could not tell *inside the div* from *just after it* |
| M8 UNAVAILABLE inferred from an empty payload | `calm.error` appears twice in the function, so the substring survived the branch being replaced |
| M11 the chip stops wrapping | the mutation removed one of the two rules the fix is made of — mis-aimed |
| M12 a missing DECIDE filled in from OBSERVE | both phases were present in the fixture, so the fallback could never fire |

Three tests were rewritten to measure the DOM instead of the source, a fixture with a **missing** DECIDE phase was added, and M11 was retargeted. Final: **12/12 red**.

One of those rewrites needed a second correction. Measuring content spill with `scrollWidth > clientWidth` reported four overflows that were not overflows — the tooltip's pseudo-element is an overlay and legitimately wider than the badge it hangs off. Confirmed by measurement rather than assumed: removing `.has-tip` took the OBSERVE card head from 484 to exactly 462. A measurement failing on its own instrument, caught the way this project catches them — by asking why a number was implausible before believing it.

---

## 8. Results

| | |
|---|---|
| New suite | **38 passed** (browser at 375/720/1440, no console errors) |
| Market view + regime + DOM + contract suites | **301 passed** |
| Mutation harness | **12/12 red**, files restored byte-identical |
| Runtime trading files changed | **none** |

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
track1_runtime/orders ABSENT · live_positions.track1.json ABSENT · TRACK1_ORDERS_APPROVED unset
confirmation file intact · gates · schedules · thresholds · strategy decisions — untouched
```

---

## 9. Still open

**A Swing/NKD divergence that this stage did not create and did not fix.** The panel showed `Regime: Calm` for NKD and `Regime: Unavailable` for Swing, from the same detector on the same day. Chasing it found the mechanism:

- NKD reads its label through a one-day lag, by construction and with a stated reason.
- Swing is handed the raw label map, and the detector looks up **that day's own row**.
- The label map's last entry on the evening of 2026-08-28 was **2026-08-27**. Day D's own row does not exist during Swing's 14:05–15:55 window; it is computed from that day's close.

The live path already carries a helper whose docstring says reading today's own label is *"six hours of the future"* and that `asof(day)` is wrong for exactly that reason. That helper guards the outer gate. The detector's own lookup then does the thing the helper exists to prevent.

**This is reported, not concluded.** It was raised as an open question on 2026-08-26 and explicitly left unresolved there; today's reading advances it — one day's observation showing the row absent long after the close — without closing it. It touches a runtime trading file and a live/backtest divergence, both outside this stage's scope and its safety constraints. It belongs to a stage of its own.

Two smaller ones:

- **The cold market-view build measures ~70s** (label map 8.0s, the rest the detector reconstruction), served stale afterwards at 0.03s with a background refresh. Documented rather than changed: the frame cannot be shortened, because the trend filter is recursive over the full history.
- **One DOM test failed once and has not reproduced** across four subsequent runs of the same suite. Recorded as an unexplained single failure rather than dismissed.
