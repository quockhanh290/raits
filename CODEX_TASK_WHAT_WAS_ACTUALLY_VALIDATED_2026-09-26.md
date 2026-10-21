# Two questions about what the backtest actually validated — read only

No code, no file edits, no writes. Two questions, and both have the same shape: a rule is running live
and nobody has checked it against the model that justified it. Answer from the engine and the
walk-forward, not from comments and not from a document that describes intent.

Both answers change a decision that is waiting on them, so a confident wrong answer is worse than an
honest cannot-tell.

---

## Question 1 — at what level was the four-percent daily loss limit validated

The circuit breaker refuses new entries after a four-percent loss in a day. On the live route that arm
cannot fire today, for reasons already measured and not in question here. It is about to be made to
fire, and the design has run into a question the validated model may already answer.

The live route runs two sleeves on different clocks. The Tokyo sleeve runs 01:10 to 02:55 ET. The
afternoon sleeve runs 14:05 to 15:55 ET. Same ET calendar day, thirteen hours apart. The book carries
ONE session-day field and ONE day-start equity.

So if the day opens at the first slot, a night slot opens it, and the afternoon sleeve measures its
daily loss against a mark taken thirteen hours earlier that already contains the whole overnight
session. The afternoon can be refused entry on a day it has not traded because the night lost four
percent — and a night gain hands the afternoon a cushion it did not earn.

What I need to know:

1. In the backtest that validated this limit, what is a day? A calendar day, a session, or a bar index
   boundary. Show the code that decides it.
2. Did that backtest ever have two sessions inside one of its days? Specifically, was the Nikkei sleeve
   ever run through the same daily-limit accounting as the afternoon sleeve, on the same day key, in
   the run that produced the accepted figures?
3. Was the limit applied to one combined equity curve, or per sleeve, or per basket? Show where.
4. If the backtest only ever had one session per day, say so plainly — that makes the live question a
   fact rather than a choice, and the design has one correct answer instead of three.

Three candidate answers are on the table and I am NOT asking you to pick on taste: one baseline per ET
day shared across sleeves, one baseline per sleeve, or one baseline reset at a chosen instant. Answer
which of those the validated model corresponds to. If the model is silent because the situation never
arose in it, say that — it is the most useful answer you can give, because it means the choice is the
operator's and cannot be justified by the backtest either way.

---

## Question 2 — is sizing against the design figure the validated model

Position exposure on the live route is computed as risk divided by a fixed account figure of fifty
thousand, not by measured equity. Contract counts are fixed per sleeve. The relevant lines are in the
Track 1 signal layer where the gross and net exposure ratios are formed.

This has been sitting as NOT A DEFECT PENDING CONFIRMATION for a reason: if the walk-forward validated
a fixed-capital model then this is correct and the only problem is that the dashboard may describe it
as live-equity sizing. If the walk-forward sized against a compounding equity curve then the live route
is not running the model that was validated, which is a different and much larger matter.

What I need to know:

1. In the run that produced the accepted figures, was position size derived from a fixed capital base
   or from an equity curve that changed as the run progressed? Show the code and, if it compounds, show
   where the equity that feeds it is updated.
2. If it is fixed, is fifty thousand the same figure the walk-forward used? Not approximately — the
   same figure, from the same place.
3. Does the sizing path on the live route reach the same contract count the backtest would have reached
   for the same signal? If you can demonstrate that on one real signal, do.
4. Name every place, in code or on the dashboard, where this is described in words. I need the list,
   not a fix — the wording change has to wait for a round that is currently editing the dashboard.

---

## Rules for both

Read the engine, the walk-forward and the accepted-figures run. Comments and design documents are
evidence of intent, not of behaviour; where they disagree with the code, the code is the answer and the
disagreement is itself a finding worth reporting.

Do not change any file. Do not run the walk-forward. Do not touch the live book. Do not run any suite
under monitor — another round is editing one of them.

Three labels, kept apart: verified by my own measurement · claimed but not measured · cannot tell from
here. Do not collapse the third into the second, and in this task the third is a respectable answer:
both questions ask what a past run did, and if the record does not say, the honest report is that the
record does not say.

Commands and raw output for everything asserted.
