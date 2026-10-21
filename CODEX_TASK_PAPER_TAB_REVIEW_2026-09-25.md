# READ-ONLY REVIEW: the paper tab and everything it claims about paper trading

**Change no file.** Not source, not tests, not notes. This ends with a report. If a fix is approved
it will be a separate instruction, and it may differ from what you propose.

ENGLISH only. No git add or commit. No scheduler or backend restart. Do not run the whole test suite
— it takes 80 minutes and has 282 unrelated failures under separate triage. Do not run anything that
connects to a broker to place or cancel an order.

---

## 0. Why this review exists

The route placed its first real paper orders on 2026-09-24. Before that the paper tab described a
route that had never traded, so every number on it was either absent or borrowed. It now describes
four filled orders, four open positions and four working stops, and nobody has checked whether what
it says is true.

In the two days since, five defects of one family were found elsewhere on the dashboard: a branch or
a label that states the prose of the one case it was written for. Expect more of the same here.
The question to hold throughout is not "does it render" but **"is the number it prints the number it
claims to be, and does it say so when it does not have one."**

---

## 1. What is in scope

    global_index/dash/paper/            index.html, paper.css, paper.js
    monitor/backend/paper_evidence_reader.py
    the two endpoints that feed the tab: /api/v1/paper-evidence and /api/v1/execution-quality
    monitor/paper_pnl_compare.json      and whatever produces it
    the evidence the tab reads: global_index/track1_runtime/trade_log.track1.jsonl,
                                the order journal under track1_runtime/orders/,
                                live_positions.track1.json

You may READ anything else. Note that another session is editing the REALTIME dashboard right now:
global_index/dash/realtime/realtime.js, monitor/backend/track1_market_view.py and
monitor/backend/job_journal_reader.py are being changed as you read. Do not report findings in those
three files; they are covered elsewhere.

---

## 2. Anchors — measured 2026-09-25 19:4x ET, so you can tell drift from disagreement

Paper evidence, 7 gate rows:

    paper_duration        PENDING
    regime_coverage       PENDING
    exit_path_coverage    PENDING
    c1_slippage           QUALITY_BREACH
    b3_reconcile          NOT_WIRED
    stp_verification      NOT_WIRED
    tws_restart_nights   NOT_WIRED

and 15 entries in a not_wired list, including b3_reconcile, data_freshness, log_hygiene and
manual_intervention. The endpoint's freshness field reads None.

Execution quality:

    state              available
    day                None
    source             trade_log.track1.jsonl
    assumption_ticks   2.0
    fills              4
    exceptions         0
    summary (opens)    n 4, mean -6.0, median -5.0, worst +1.0,
                       adverse_count 1, over_assumption_count 0

The trade log holds 4 rows, all OPEN, no CLOSE.

---

## 3. The questions. Answer each with a measurement.

### 3.1 Fill quality and slippage

The sign convention matters and the tab must be read-proof about it. Establish, from the code that
computes it, which direction is adverse, and then check every place that displays it uses the same
direction.

Note what the numbers above say: mean -6.0 ticks against a modelled assumption of 2.0, with
over_assumption_count 0 and adverse_count 1. So on a one-sided cost reading, execution is inside the
model on every fill. Yet the c1_slippage gate reads QUALITY_BREACH.

Find out why, and specifically: does the gate compare the ABSOLUTE mean against its limit? If so, a
fill better than the signal price counts against you. Read the spec that defines the limit —
monitor/paper_inputs.json — and report whether its own rationale is written in cost terms or in
correspondence terms. Quote it. Do not fix it; this is a live question the operator has already been
asked and has not yet answered, and your evidence feeds that decision.

Also: is n=4 enough for that gate to speak at all? Report the minimum sample the spec sets and
whether the tab makes the sample size visible beside the verdict.

### 3.2 Account and book reconciliation

Three records must agree: the order journal, the position book and the broker. A fourth, the paper
account baseline, says whether the account itself is the one this route thinks it is.

Report what the tab shows for each, and whether any of them is displayed as a fact when it is
actually stale. Two specifics worth checking, because both have already bitten this week:

  * the paper account baseline expires 24 hours after it is recorded and no job refreshes it. What
    does the tab show between expiry and the next manual record?
  * B1 reads a stored record, not the broker. What does the tab show if that record is hours old and
    the broker has moved?

### 3.3 The NOT_WIRED rows

Fifteen of them. For each, say which of these it is:

    the source genuinely does not exist yet
    the source exists and nothing reads it
    the source exists, something reads it, and the wiring is broken

Those are three different pieces of work and the tab currently presents them as one word. Name any
row where the evidence is already on disk — b3_reconcile is the one to check first, because the
route now produces B3 reconcile output every time a sweep runs.

### 3.4 Numbers that are absent versus numbers that are zero

The trade log holds 4 OPEN rows and no CLOSE. So realised P&L, Sharpe, Calmar and drawdown cannot be
computed. Check every such field on the tab and report whether it renders as "not measured" or as a
zero. A zero in a P&L column reads as "we traded and made nothing", which is a different claim from
"nothing has closed yet".

### 3.5 The execution-quality day

The endpoint returns day None. Find out whether anything downstream compares that field to a date —
if it does, that comparison can never be true. Report where, and what the user sees as a result.

### 3.6 Anything the tab states that it cannot know

The general form of the five defects found elsewhere. Look for: a hardcoded sentence inside a
status branch, a label that names one route while the data comes from another, a count that is a
default rather than a measurement, a freshness that is asserted rather than read.

---

## 4. Report

    ANCHORS         the measurements in section 2, re-taken, and any that differ from what is
                    written there
    PER QUESTION    3.1 to 3.6, each with the command or the file and line, and the raw output
    FINDINGS        one line each, ordered by how misleading the displayed result is, not by how
                    hard it is to fix. For each: what is shown, what is true, and how you know
    NOT A DEFECT    anything that looks wrong and is not, with the reason. This section earns its
                    place — half of what looks broken on this dashboard is a correct refusal
    UNCHECKED       what you did not get to, and what it would take
    SPEC PROBLEMS   anything in this file you believe is wrong, or empty — and if empty, say you
                    looked
