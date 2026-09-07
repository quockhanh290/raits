"""Stage 5ZZR mutation harness — can the new tests actually turn red?

Every rule this stage added is broken here at the source, in a subprocess, and restored. A test
that stays green under the mutation of the thing it claims to check is not checking it.

The restore compares TEXT rather than bytes: the repo is CRLF and `read_text`/`write_text`
translate on the way through, so a byte comparison fails on a correct restore.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zzr_strategy_native_market_view_20260828.py"
MV = REPO / "monitor" / "backend" / "track1_market_view.py"
JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"
CSS = REPO / "global_index" / "dash" / "realtime" / "realtime.css"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pytest(node_ids):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
         "-p", "no:randomly", *[f"{TEST}::{n}" for n in node_ids]],
        cwd=REPO, capture_output=True, text=True, timeout=900)


def expect_red(name, edits, node_ids):
    base = _pytest(node_ids)
    if base.returncode != 0:
        tail = base.stdout.strip().splitlines()[-1] if base.stdout.strip() else base.stderr[-300:]
        print(f"  [HARNESS BROKEN] {name}: baseline not green — {tail}")
        return False
    originals = {}
    try:
        for path, old, new in edits:
            src = path.read_text(encoding="utf-8")
            originals.setdefault(path, src)
            n = src.count(old)
            if n != 1:
                print(f"  [HARNESS BROKEN] {name}: anchor matched {n}x in {path.name}")
                return False
            path.write_text(src.replace(old, new), encoding="utf-8")
        res = _pytest(node_ids)
    finally:
        for path, src in originals.items():
            path.write_text(src, encoding="utf-8")
            assert _digest(path.read_text(encoding="utf-8")) == _digest(src), f"restore: {path}"
    last = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
    ok = res.returncode != 0
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:56s} {last}")
    return ok


MUTATIONS = [
    ("M1 a failed gate arms its levels anyway",
     [(MV, '        armed = bool(state.get("set_up"))',
           '        armed = True')],
     ["test_dom_a_failed_gate_draws_muted_lines_never_active_ones",
      "test_stress_publishes_the_price_levels_it_computes",
      "test_a_failed_gate_leaves_the_levels_unarmed_and_says_so"]),

    ("M2 the computed trigger is withheld again",
     [(MV, '        if ctx.get("pre_low") is not None:',
           '        if False:')],
     ["test_stress_publishes_the_price_levels_it_computes",
      "test_a_failed_gate_leaves_the_levels_unarmed_and_says_so"]),

    ("M3 NKD/Swing lose their prerequisite cards",
     [(MV, '        for label in (f"Trend filter (EMA {period})", "Volume vs 10-bar average",\n'
           '                      "Daily ATR", "Regime"):',
           '        for label in ():')],
     ["test_nkd_and_swing_name_their_own_decision_variables",
      "test_dom_nkd_shows_its_own_prerequisites_not_basket_metrics"]),

    ("M4 NKD is given the Swing trend period",
     [(MV, '        period = 10 if sleeve == "global_nkd" else 50',
           '        period = 50')],
     ["test_nkd_and_swing_name_their_own_decision_variables",
      "test_dom_nkd_shows_its_own_prerequisites_not_basket_metrics"]),

    ("M5 the page draws every level as armed",
     [(JS, "        const cls = (l.armed === true && armed) ? 'mv-level armed' : 'mv-level muted';",
           "        const cls = 'mv-level armed';")],
     ["test_dom_a_failed_gate_draws_muted_lines_never_active_ones"]),

    ("M6 muted and armed stop looking different",
     [(CSS, '.mv-level.armed { stroke: var(--amber, #c9a227); stroke-width: 1.5; '
            'stroke-dasharray: none; }',
            '.mv-level.armed { stroke: var(--dim, #6a7284); stroke-width: 1; '
            'stroke-dasharray: 2 4; opacity: .65; }')],
     ["test_dom_muted_and_active_levels_are_visually_distinct"]),

    ("M7 the page restates the model instead of reading it",
     [(JS, "             mvEsc(r.threshold_note || ''))",
           "             'The model compares state probabilities; it does not expose a simple "
           "flip threshold.')")],
     ["test_the_regime_says_no_published_threshold_in_the_agreed_words"]),

    ("M8 the tooltip is sized by its content box again",
     [(CSS, '.mv-summary .mv-chip.has-tip::after { box-sizing: border-box; }',
            '.mv-summary .mv-chip.has-tip::after { box-sizing: content-box; }')],
     ["test_dom_no_overflow_on_any_tab"]),
]


def main() -> int:
    print(f"Stage 5ZZR mutations — {len(MUTATIONS)} rules\n")
    results = [expect_red(*m) for m in MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
