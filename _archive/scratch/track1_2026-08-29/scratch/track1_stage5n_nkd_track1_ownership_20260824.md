# Stage 5N — Track 1 owns the MNKD overnight sleeve

**2026-08-24 ·** no scheduler started or stopped · no real IBKR (frame providers only) · no
order · no `STOP_TRADING`, `STOP_TRADING.track1` or confirmation file touched · no live state
written · no commit.

---

## Verdict: **READY_FOR_5O_ROUTE_AWARE_SAFETY**

The exact claim, no wider: **Track 1 owns all four strategy sleeves at slot/source level in
track1-only shadow.**

Not claimed: legacy independence — stop repair ×10 and the max-hold exit still carry
`--positions-path live_positions.json`, which is Stage 5O. Not paper or live readiness. Not
permission to delete the legacy route — 5O + 5P first.

---

## The plumbing

**Legacy inventory, measured from the built scheduler:** 22 `nkd_night` jobs, 01:10–02:55 ET,
5-minute cadence, `run_live_day --clusters nkd --port 4002` on clientId 1, reading the
*previous business day's* pre-flight flag, writing legacy's book.

**Track 1 after 5N:** 22 `TRACK1_NKD_*` slots mirroring those minutes exactly — asserted
against the legacy triggers, not from memory. The sleeve joined the STAGED set: `none` in
transitional shadow (the legacy `nkd_night` jobs still occupy its band there), `ibkr` in
track1-only, same env override as swing. Jobs: 60 default · 129 transitional · **84
track1-only, with zero legacy strategy jobs**. Parity true in all three modes (60/58, 129/127,
84/82).

**The rule is the promoted engine, reused whole.** `_nkd_candidates` calls
`detect_entry_for_slot(ema_period=10, fill_law=LIVE_FILL_LAW, apply_context_filter=False)` with
labels through `RegimeLabels(lag_days=1)` — the exact objects the committed artifacts were
generated with. A test asserts the source path contains no rule re-implementation and no legacy
import. Qty 1, cap 6%, five-day hold, chandelier config 2.5: all read from the tables that
already carried them.

**End-to-end on a synthetic Tokyo session:** the fixture's two-bar pullback/resume pattern
fires SHORT @38040 with the entry-anchored 2.0×ATR stop. Causality across the slot grid is
pinned: the signal bar's 5-minute bucket completes at 01:40 ET, slots at 01:10/01:30/01:35 see
nothing, slots from 01:40 see the same entry. The SPY short gate reaches the sleeve (the SHORT
vanishes when today is outside `short_days`), a missing regime map refuses rather than
returning empty, and the lag-1 read is discriminated in both directions (yesterday-Calm blocks;
today-Stress with yesterday-Normal trades).

---

## Three defects found by measurement — all the 13-hour family

**5N-1. The detector truncated on the wrong clock.** `detect_entry_for_slot` (my own 5M-B
code) converted `now` to **ET** before truncating the scan window — correct for every frame it
had ever seen, and 13 hours wrong for the Tokyo-clocked MNKD frame it was about to receive. It
now truncates on the frame's own clock, keeping the ET assumption only for naive frames.

**5N-2. The window gate silently rejected 26 committed replay rows.** The gate read a
candidate's entry stamp as bare wall-clock text and compared it to the ET slot band. The
committed NKD rows are stamped **+09:00, in the Tokyo session window (14:10–15:55 JST)** —
and judging them against the ET band shrank the replay's accepted tail from **91 to 67**,
measured before any 5N test existed, surfacing through a Stage 3B equity-binding test whose
chosen cut stopped binding.

The correction is a concept, not a patch: the ET table answers *when do slots fire*; a new
`SESSION_WINDOWS` table answers *when may the rule enter*, in the sleeve's own clock. The two
coincide for every US sleeve and drift with US DST for Tokyo — in winter the late ET slots fire
after the session window closes, **which is legacy's own fixed-ET cron behaviour, inherited
deliberately**. The gate converts aware stamps to the window's clock (an instant conversion,
one right answer), the live candidate now carries the aware Tokyo signal-bar stamp exactly as
the artifacts do, and the replay is restored to **91 accepted, 0 window rejections**, pinned by
a full-replay test rather than a sample.

The stale docstring went with it: `_et_hhmm`'s stated ground was "the replay tables carry
ET-aware entry times" — true of every table that existed when the sentence was written, false
of the first Tokyo one. A description of the data expires; converting by rule does not.

**5N-3. The admission gate demanded ET of every frame.** `_index_checks` refused the Tokyo
frame outright (`tz_mismatch`). It now accepts the requirement's own declared clock
(`Requirement.clock`, new in this stage) and still refuses a *wrong* clock without converting —
the whole `validate` call runs on one clock, so the staleness check compares a Tokyo last-bar
against a Tokyo horizon instead of being vacuously green.

---

## Ledger, freshness, checkpoint

* `expected_slots("global_nkd") = 22`, equal by test to the registered slot count; a window is
  complete only at 22 decided slots with a close record — proven at 21 (incomplete) and 22
  (complete), not asserted.
* The ET session date and the Tokyo calendar date coincide across the whole band in both DST
  regimes (01–03 ET is 14–17 JST), so no midnight-crossing rule was invented.
* **Freshness: D-1 for all 22 slots**, measured per slot — the sleeve reads the previous
  business day's 13:45 pre-flight, like Calm and Stress and like legacy's own
  `prev_preflight=True`. The 5L contract table gained the fourth row.
* The route checkpoint already carried `global_nkd` in `CHECKPOINTED_SLEEVES`; a test now
  proves the schema actually closes over a Tokyo frame under a temp path rather than trusting
  the list. Decisions never read legacy's book — asserted at source level and by mutation.

---

## Test results

| Suite | Result |
|---|---|
| **Stage 5N** `test_track1_stage5n_nkd_track1_ownership_20260824.py` | **31 passed** |
| **Mutation harness** | **9 / 9 detected**; both on-disk mutations restored byte-for-byte |
| 5M-D + 5M-C + 5M-B + 5L + 3B + ops + mirror | **267 passed, 1 skipped** |
| stage3 route + 5E + 5F + 5D + 5I + 5M-1 + 4C + explain | **230 passed, 2 skipped** |

`global_index/test_event_playback.py` **not run** — still the known hang.

```
M1  the 22 NKD slots removed                     → the cadence test reds
M2  the NKD window removed (parser loses it)     → the subprocess parser test reds
M3  the source stops serving the sleeve          → the candidate test reds
M4  the NKD ledger window removed                → the coverage test reds
M5  legacy nkd_night jobs survive track1-only    → the absence test reds
M6  --allow-orders added to an NKD slot body     → the argv test reds
M7  the ops count hardcoded to yesterday's 48    → the derived-count test reds
M8  the decision path names live_positions.json  → the no-legacy-book test reds
M9  the gate reads Tokyo stamps as wall text     → the instant test reds
```

M9 re-arms the exact regression this stage hit. M2, M8 are on-disk mutations because their
guards parse source or run subprocesses; hash-verified restored.

### Stale tests updated (the intended-change family)

Sixteen, across 5M-B/C/D, 5L, 5E, 5F and 3B: count pins (48→derived, 107→derived, 62→derived),
`global_nkd` retired as the "unslotted sleeve" example — the second fixture to expire that way,
so the property now rides on a name outside the window table — the 5L freshness table gained
its fourth row, and 3B's cross-table window test learned that a session-clock sleeve's
requirement matches `SESSION_WINDOWS` rather than the ET band. One import fix rippled from
renaming `_et_hhmm` → `_hhmm_on` (`run_live_day_track1` imports it; the explanation feature now
reads the same session window and clock the gate compares, so an NKD explanation cannot
contradict its own verdict).

---

## What is still not true

* **Legacy-independent** — the 11 safety jobs still watch `live_positions.json`. Stage 5O.
* **Paper/live ready** — the order gate still reports B1 open; nothing here changes that.
* **Safe to delete legacy** — 5O (route-aware safety) and 5P (full four-sleeve shadow) first.

**Next: Stage 5O** — route-aware stop repair and max-hold, and the split of the shared
max-hold state file, which fails silently the moment both routes hold positions.
