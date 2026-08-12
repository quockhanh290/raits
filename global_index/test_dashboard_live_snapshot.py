"""Live mode must render the NEWEST snapshot, not the oldest.

dashboard.html's startLive() set `selectedIdx = 0` and hid the day slider, so live mode
could only ever show snapshots[0]. That was invisible while live produced a single
snapshot — index 0 was also the last one. On 2026-08-11, the first day live carried a
second snapshot, the page fell back to 2026-08-10.

Falling back is worse than showing a stale date. Older snapshots are REBUILT FROM TRADE
HISTORY and carry 8 keys where a live one carries 19; missing are open_positions,
regime, cluster_exposure, breaker_level, operational_status, drawdown_pct,
drawdown_dollars, max_dd_dollars, slippage, fill_quality and paper_vs_backtest. History
knows what was realised; it cannot know what was being HELD. So the page rendered them
blank, with no error — four open positions and every stop level vanished from the
operator's screen while the system was holding them.

These run the real startLive() out of dashboard.html in Node against stub DOM/render
functions, rather than grepping the source for `selectedIdx`. The bug was in what the
code DID with the snapshot list; a source-text check would pass on any line that merely
mentions the right variable.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = _ROOT / "global_index" / "dashboard.html"
LIVE_JS = _ROOT / "global_index" / "dash" / "shared" / "live.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not on PATH")


def _extract(source: str, name: str) -> str:
    """The full text of `function <name>(...) { ... }`, matched by brace depth.

    A regex for the closing brace would stop at the first `}` inside the body.
    """
    start = source.index(f"function {name}(")
    depth, i = 0, source.index("{", start)
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[start:j + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def _run_start_live(snapshots: list) -> int:
    """Run dashboard.html's real startLive() and return the selectedIdx it chose."""
    fn = _extract(DASHBOARD.read_text(encoding="utf-8"), "startLive")
    script = f"""
    let mode, data, selectedIdx, liveTimer;
    const _el = {{ style: {{}}, className: '', textContent: '' }};
    global.document = {{ getElementById: () => _el, querySelector: () => _el }};
    global.setInterval = () => 0;
    global.clearInterval = () => {{}};
    function precompute() {{}}
    function buildChart() {{}}
    function updateDayView() {{}}
    function updateHealth() {{}}
    {fn}
    startLive({{ meta: {{}}, snapshots: {json.dumps(snapshots)} }});
    console.log(JSON.stringify({{ idx: selectedIdx, mode: mode }}));
    """
    out = subprocess.run([shutil.which("node"), "-e", script],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["mode"] == "live"
    return result["idx"]


def _snap(date: str, full: bool):
    """full=True mimics a runner-written snapshot, False the rebuilt-from-history one."""
    s = {"date": date, "equity": 50162.0, "decision": {}, "per_cluster_pnl": {}}
    if full:
        s.update(open_positions=[{"inst": "MES"}], regime="Normal",
                 cluster_exposure={}, breaker_level="OK", operational_status={})
    return s


def test_ls1_two_snapshots_render_the_newer():
    """The exact 2026-08-11 shape: a rebuilt 08-10 followed by a live 08-11."""
    idx = _run_start_live([_snap("2026-08-10", False), _snap("2026-08-11", True)])
    assert idx == 1, (
        "live mode selected the OLDER snapshot; open_positions, regime, "
        "cluster_exposure and breaker_level are absent from it and render blank")


def test_ls2_single_snapshot_still_works():
    """The case that hid the bug for as long as it did — must stay correct."""
    assert _run_start_live([_snap("2026-08-11", True)]) == 0


def test_ls3_many_snapshots_take_the_last():
    days = [_snap(f"2026-08-{d:02d}", False) for d in range(1, 12)]
    days[-1] = _snap("2026-08-11", True)
    assert _run_start_live(days) == len(days) - 1


def test_ls4_empty_list_does_not_go_negative():
    """`length - 1` on an empty list is -1, which indexes nothing and blanks the page
    the same way the original bug did. Clamped at 0."""
    assert _run_start_live([]) == 0


def test_ls5_the_selected_snapshot_carries_the_live_only_keys():
    """The point of picking the newest: it is the one with the operator's fields.

    Asserted on the data, not the index, so a future change that renumbers snapshots
    still fails here if it lands on a record that cannot show positions.
    """
    snaps = [_snap("2026-08-10", False), _snap("2026-08-11", True)]
    chosen = snaps[_run_start_live(snaps)]
    for key in ("open_positions", "regime", "cluster_exposure", "breaker_level"):
        assert key in chosen, f"selected snapshot cannot render {key}"


def test_ls6_new_dashboard_variants_pick_the_newest_too():
    """dash/shared/live.js must not reintroduce the same fallback."""
    if not LIVE_JS.exists():
        pytest.skip("dash/shared/live.js not present")
    script = f"""
    global.window = {{ addEventListener: () => {{}} }};
    global.document = {{ querySelectorAll: () => [], addEventListener: () => {{}} }};
    window.LIVE_DATA = {{ meta: {{}}, snapshots: {json.dumps(
        [_snap("2026-08-10", False), _snap("2026-08-11", True)])} }};
    {LIVE_JS.read_text(encoding="utf-8")}
    console.log(window.RaitsLive._test.latestSnap().date);
    """
    out = subprocess.run([shutil.which("node"), "-e", script],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "2026-08-11"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
