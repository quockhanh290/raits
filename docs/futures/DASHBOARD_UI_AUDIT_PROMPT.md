# Prompt: Track 1 Dashboard UI Audit

Use this prompt to audit what the realtime dashboard **says**, not how it looks. Every defect
class listed below was found on this panel on 2026-08-31, each with the measurement that found
it. They are listed because each one survived a reading of the code and only fell to a number.

```text
You are working in D:\raits on the Track 1 futures monitoring dashboard.

GOAL
Audit what the dashboard asserts. A panel that renders cleanly and states something untrue is
worse than an empty panel: the operator acts on it. Look for numbers that are right, labels
that are wrong, and states that are collapsed into one word.

Scope: http://127.0.0.1:5002/realtime and /paper, served by monitor/start_backend.py.
  global_index/dash/realtime/realtime.js     the render path
  global_index/dash/realtime/realtime.css
  monitor/backend/track1_market_view.py      the payload
  global_index/track1_strategy_diagnostics.py  the blocks the slots record
  global_index/track1_signals.py             the rule vocabulary

HARD RULES
- Read first, fix second. No change lands without a measurement that would have caught the
  defect, and a test that goes red when the fix is removed.
- Never recompute a trading rule in the display layer. If the page needs a verdict the
  detector did not publish, the answer is a reporting seam in the detector, not a second
  implementation. A previous stage stamped a recomputed verdict on one row and it agreed with
  the real gate 52.7% of the time -- a coin flip, wrong in both directions.
- Do not change strategy logic, gates, the scheduler, or anything under
  global_index/track1_runtime/. Do not delete or rewrite evidence files.
- Before calling any behaviour "unmeasured" or "a bug", search the project's own audit
  documents (*_AUDIT.md, docs/futures/OPERATIONS.md, DAILY_FLOW.md, ISSUES_LOG.md) and ask
  which LAYER owns the question. Twice on 2026-08-31 an alarm was raised about something
  already handled one layer away and already written down.

THE SEVEN DEFECT CLASSES TO HUNT, each with the case that produced it

1. A label that asserts the wrong quantity.
   The row reading "Daily ATR" was `atr14()` over fourteen FIVE-MINUTE bars -- about seventy
   minutes. Measured on MNKD 2026-08-28: the row read 55, the daily ATR the stop is actually
   sized from read 1,548.93. Twenty-eight times apart, and the number that places the stop
   appeared nowhere on the page.
   -> For every number on the page, name its UNITS and the bar or day it was measured on, then
      check the label says that.

2. A verdict-shaped hole where no verdict can exist.
   Eight rows each printed "NOT REPORTED" under their value. Seven of them are measurements
   and carry no verdict by design; the eighth had its verdict sitting a few fields away in the
   same block, unjoined. One word covered "deliberately absent", "not joined up" and "broken".
   -> A state word that can mean three things is not a state word.

3. Missing data rendered as a real zero.
   `Number(null)` is 0 in JavaScript and `Number.isFinite(0)` is true. Nine slots that had not
   run became nine zeros and dragged a price axis to -7,975.88 for an instrument trading at
   66,000. No unit test caught it; the axis label did.
   -> Look at the rendered page. An impossible value is the cheapest way this announces itself.

4. A format too coarse for the value it now carries.
   Four decimals stripped of trailing zeros rendered 1.2e-05 as "0", against a threshold of
   -0.001. It only appeared when rows that are fractions joined a card whose rows had always
   been prices in the tens of thousands. The ruler did not change; what was put on it did.
   -> Every formatter: find the smallest value it can now receive and check it survives.

5. A snapshot presented as a session.
   Slots fire on the five-minute boundary, so the bar the detector last evaluated is seconds
   old. The card read volume 0 at essentially every slot while the ten-bar average behind it
   grew from 5.8 to 32. A single slot cannot show that, and the card did not say it was a
   single slot.
   -> Ask of every card: is this one moment, or a session? Does it say which?

6. Old numbers under today's label.
   The replay path reads a store that is appended after a session closes, so during a live
   session its newest bar is the previous day's. A card headed with today's date was being
   filled from a replay of a different day.
   -> Prefer the slot's own recorded account; fall back to a replay only when there is none,
      and say which one is on screen.

7. A description that has drifted from the thing it describes.
   Comments, test names and doc lines age. One test named "the unwired sleeves say so" still
   asserts two sleeves are unwired that were wired stages ago.
   -> Derive from data where you can. Where you cannot, let a test hold the claim.

METHOD
- Trace every displayed number back to the function that produced it. Name the units.
- The backend does NOT hot-reload:
      python monitor\ops.py restart --no-scheduler --track1-only-shadow --yes
  This leaves the scheduler alone. Check `ops.py status` first and preserve the mode it
  reports.
- Hard-refresh the browser; realtime.js is cached.
- Recorded blocks carry the labels that existed when the SLOT ran. A label change does not
  appear until the next slot writes a block -- do not read that as the change not working.
- Check a narrow viewport. Measure `document.body.scrollWidth` against `clientWidth`, and when
  there is overflow, hide your own element and measure again before blaming it. On this page
  the overflow comes from a table elsewhere.
- Look at the rendered page, not only at assertions. Defects 3 and 4 above were both invisible
  to the numbers and obvious in a screenshot.

WHAT NOT TO TOUCH
- scratch/track1_blocking_ledger_20260822.json is GENERATED and is already stale at HEAD.
  Do not regenerate it into an unrelated commit.
- realtime.js, realtime.css and monitor/test_dashboard_backend.py may carry another session's
  uncommitted work. Check `git diff` before staging them.

DELIVERABLE
A findings document. For every finding: what the page says, what is true, the measurement that
separates them, and what an operator would do wrong if they believed the page. Then a SEPARATE
list of what you could not check and why -- including anything waiting on a market session.

Label every claim: verified / unproven / unchecked. "Not proven" is not "false", and a check
that could not run is not a check that passed.
```
