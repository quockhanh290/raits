# Prompt: Repo Source Resurrection

For delegating the first, non-negotiable step of the repo cleanup: bringing into Git the source
files that committed code already imports. Measured 2026-08-31 on branch future/incorporation.

The block below contains no backtick characters, deliberately. A prompt forwarded through a
shell will run command substitution on them, and the last time that happened two writers ended
up editing one file at the same time.

~~~text
You are working in D:\raits, branch future/incorporation. Python repo, futures trading.

THE ONE JOB
Make a clean clone of this repo able to import what its committed code imports. Nothing else.
Right now it cannot: 771 tracked .py files make 3,355 internal imports and 21 of them resolve
to a file that is not in Git. Every working tree has those files on disk, so no test noticed.

Do not clean up, archive, delete, move or reformat anything. That is a later stage and it is
not yours.

STEP 1 - DERIVE THE LIST YOURSELF, DO NOT TRUST MINE
Write a read-only scanner and run it. Method:
  - git ls-files, keep the .py entries
  - parse each with ast, collect Import and ImportFrom targets, skip relative imports
  - a target is INTERNAL when its first dotted part is one of:
      global_index, futures, monitor, raits, orb_stocks, scratch
  - resolve an internal target to PKG/SUB/MOD.py or PKG/SUB/MOD/__init__.py on disk
  - report every resolved path that is NOT in git ls-files, with who imports it

Cross-check against these numbers before going further. If yours differ, stop and say so
rather than proceeding on a different list:
    tracked .py files            771
    internal imports resolved  3,355
    missing from git              21

Also derive, separately, the untracked NON-.py files that committed code opens by path
(fixtures, runbooks, JSON templates). Expect roughly a dozen. Report the list.

WHY A SCANNER AND NOT git status
One of the 21 cannot appear in git status at all. The file raits/data/raits_news.py is
excluded by .gitignore line 225, the rule "data/", meant for the bar cache but also swallowing
a source package. A list built from git status silently omits it, which is exactly how an
earlier review counted 8 files instead of 9.

STEP 2 - COMMIT THE SOURCE, ON ITS OWN
One commit containing only the missing source modules plus one .gitignore change.

  - git add each missing .py that lives under global_index, futures, monitor, raits,
    orb_stocks or scratch
  - for raits/data/raits_news.py do NOT use git add -f. Add a narrow negation to .gitignore
    instead, of the form: exclamation mark, then raits/data/, then star dot py. Using -f fixes
    today and lets the same rule swallow the next file added to that directory. The negation
    fixes it by construction, and it belongs in THIS commit so the commit stands alone.
  - commit message: say what was missing, how many tracked files imported each of the top few,
    and that a clean clone could not previously import them

Two of these are load-bearing and worth naming in the message:
    global_index/window_ledger.py       25 tracked importers, one of them
                                        track1_shadow_acceptance, which is one of three files
                                        that hold this repo's reconstruction safety line
    global_index/route_checkpoint.py    17, including run_live_day_track1
And one is quietly worse: scratch/stress_open_search_20260821.py is imported by the Stress
equivalence gate, the test that pins 57 trades across three windows. On a clean clone that
gate cannot run, so the repo cannot verify itself.

STEP 3 - SHRINK THE DEBT REGISTER IN THE SAME COMMIT
The file scratch/test_repo_import_closure_20260831.py holds a dict named KNOWN_UNTRACKED,
dated 2026-08-31. It has two assertions around it: nothing outside the list may be missing,
and everything in the list must STILL be missing. So after you commit the source, that second
assertion goes red until you delete the entries you just fixed. Deleting them is how a fix is
recorded. Do not add entries.

STEP 4 - FIXTURES, AS A SEPARATE COMMIT
The untracked non-.py files that committed tests open by path. One commit, no source in it.

EXCEPT ONE, which is not yours: scratch/track1_blocking_ledger_20260822.md. It is out of step
with the JSON ledger generated from the blocker registry, and the parity test between them is
already red. Tracking it now would commit a document that is known to be wrong. Leave it
untracked, and say in your report that it is still outstanding.

FILES YOU MUST NOT TOUCH, FOR ANY REASON
    global_index/dash/realtime/realtime.js
    global_index/dash/realtime/realtime.css
    monitor/test_dashboard_backend.py
        These three carry another session's uncommitted work. Do not stage, revert, reformat
        or read-modify-write them.
    global_index/track1_runtime/ and anything under it
    live_positions.track1.json, runner.track1.pid, track1_go_live_confirmation.json
        Live runtime state. A scheduler and a backend are running and writing here.
    data/ and raits/data/cache/
        7.86 GB of bar caches. Rebuilding them takes two to three hours from the provider.
    TASK.md, SCRATCHPAD.md
        Owned elsewhere this session.

DO NOT
  - do not run git stash, with or without untracked. It REMOVES files from the working tree,
    and a scheduler process is reading them right now
  - do not normalize line endings, and do not touch trailing whitespace anywhere
  - do not archive, move or delete any file
  - do not push to origin. 50 commits are unpushed and whether they go out is not your call
  - do not commit more than the two commits described above

ACCEPTANCE, MEASURED NOT REPORTED
Run these and paste the actual output:
  1. your scanner again: the count of missing-from-git must have dropped by the number of
     source files you committed, and the remainder must be only non-.py fixtures
  2. python -m pytest scratch/test_repo_import_closure_20260831.py -q
     must be 4 passed. If the shrink assertion is red you have not done step 3
  3. python -m pytest scratch/test_track1_stage5f_stress_live_source_20260823.py -q
     record the pass/fail counts before and after your change; they must be identical
  4. git status --porcelain, before and after, so the diff in what is staged is visible
  5. git log --oneline -3

IF THE PLAN IS WRONG, SAY SO
If the scan disagrees with my numbers, or a file I told you to commit turns out to be a
duplicate of something already tracked under another name, or the .gitignore negation does not
take effect, stop and report it. Do not make the tests green around a plan that is wrong. A
previous round of this work caught a genuine error in my spec, and saying so was worth more
than finishing.
~~~
