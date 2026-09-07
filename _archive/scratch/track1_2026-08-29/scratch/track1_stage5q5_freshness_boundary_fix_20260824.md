
---

## Follow-up, same day, 20:10 ET (Stage 5Q-6)

Three of the predictions in this report were checked against the live day. Recorded here so
this document is not read later as the last word.

- **The corrected requirement passes, not merely runs.** At 19:46 the gate ALLOWS: csv
  2026-08-21, required daily close 2026-08-21, required intraday 2026-08-24,
  preflight_consistency ok. The old rule would still be refusing.
- **"Repair the MNQ bar" is obsolete as written.** Friday's bad bar has fallen out of the
  fetch overlap and can no longer be measured or repaired. Today's 13:45 preflight created
  **three new ones** — MNQ, MYM and M2K. The live command is now
  `--repair-boundary --symbols MNQ MYM M2K`.
- **The open question is answered: yes.** `--repair-boundary` is now in the scheduler's
  preflight argv, decided on a count (3 of 5 instruments corrupted by one run; 46 slot
  refusals on Friday), not on a judgement about acceptable risk.
- **A defect in the 5Q-4 measurement tool that this report relied on:** its `--apply` would
  have rewritten a 3.3M-row parquet's index convention from tz-naive UTC to tz-aware New York.
  Fixed. The production appender was never affected — it concatenates onto the raw frame.
- **A new blocker this report did not know about:** MNKD, 1052 bars disagreeing, first at
  2026-08-24 07:01 JST. Not a boundary bar; cause unmeasured.

Full detail: `scratch/track1_stage5q6_operationalize_freshness_boundary_20260824.md`.
