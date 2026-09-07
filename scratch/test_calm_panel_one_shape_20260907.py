"""Panel Calm hai pha chỉ có MỘT hình dạng. TỆP MỚI.

Chuyện đã thấy trên màn hình
----------------------------
Mở panel lúc 09:32, khi mới có pha DECIDE và sleeve chỉ ghi một mã: một cột dọc, mỗi pha một
thẻ rời, các cổng xếp thành hàng dọc, có dòng "Instrument: MES" và "Direction: LONG" riêng.

Mở lại khi đã có cả hai pha và hai mã: một bảng hai cột DECIDE | OBSERVE, tên mã nằm trên
tiêu đề, các cổng gom thành một dòng chip, kèm "4 / 4 gates met" và "2 instruments · 7 rows ·
4 gates each".

Cùng một panel, hai hình dạng không liên quan gì nhau.

Nguyên nhân không phải số pha
-----------------------------
Điều kiện thật là **số mã**: dưới hai mã thì rơi xuống đường vẽ cũ. Ý định của nó đúng ở phần
nó nói — một tiêu đề chỉ ghi "MES" khi MES là thứ duy nhất trên màn hình là dòng không mang
tin. Nhưng nó lấy đi nhiều hơn thế: đường cũ tách hai pha thành hai thẻ rời, nên mất luôn

    số cổng đã đạt        "4 / 4 gates met"
    hình dạng bảng        "7 rows · 4 gates"
    câu nói cái gì đổi    "chỉ hai hàng có giá thay đổi"
    dấu — ở cột sau       nghĩa "giống hệt cột trước", chỉ nói được khi có hai cột

Hình đầu **ít thông tin hơn**, không chỉ khác. Và hai pha là một câu chuyện — quyết định trước
phiên, rồi đọc giá lúc 10:00 — nên kể bằng hai thẻ rời là kể mất mối nối.

Các phép kiểm dưới đây chạy chính hàm dựng HTML của trang qua node, với dữ liệu dựng tay ở cả
hai trường hợp, và so hai kết quả với nhau.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="cần node để chạy chính hàm dựng của trang")

#: Dựng đúng hình dạng dữ liệu backend trả về, chép từ payload thật của sleeve Calm.
_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const pick = n => {
  const i = src.indexOf('function ' + n);
  if (i < 0) throw new Error('khong tim thay ' + n);
  let d = 0;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') d++;
    if (src[k] === '}') { d--; if (!d) return src.slice(i, k + 1); }
  }
};
const mvEsc = v => String(v == null ? '' : v);
const mvSourceBadge = () => '';
const _threshWord = () => '';
eval(pick('mvCalmByInstrument'));

const gates = [
  {gate: 'regime_is_calm_d1', passed: true, display_value: 'Calm'},
  {gate: 'prior_rth_close_bottom_third', passed: true, display_value: '0.1555'},
  {gate: 'prior_rth_down_close', passed: true, display_value: '-0.003'},
  {gate: 'gap_not_deep', passed: true, display_value: '-0.0028'},
];
const rows = [
  {label: 'Daily ATR (causal)', display_value: '59.70', detail: 'fixed before the session opened'},
  {label: 'Stop rule', display_value: 'entry - 1.5 x daily_atr'},
  {label: 'Stop distance', display_value: '89.54'},
  {label: 'Risk if taken', display_value: '447.72'},
  {label: 'Entry reference time', display_value: '10:00'},
];
const inst = n => ({instrument: n, direction: 'LONG', gates, rows});
const order = [['decide', 'DECIDE', '09:32 ET'], ['observe', 'OBSERVE', '10:02 ET']];

const names = JSON.parse(process.argv[2]);
const both = process.argv[3] === 'both';
const phases = {decide: {instruments: names.map(inst)}};
if (both) phases.observe = {instruments: names.map(inst)};
process.stdout.write(mvCalmByInstrument(phases, order) || '');
"""


def _render(names: list, both_phases: bool = False) -> str:
    proc = subprocess.run(
        ["node", "-e", _HARNESS, str(JS), json.dumps(names),
         "both" if both_phases else "one"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[:400]
    return proc.stdout


# ── phép kiểm phải chứng minh nó đo được thứ gì ──────────────────────────────

def test_the_harness_actually_renders_something():
    html = _render(["MES", "MNQ"])
    assert len(html) > 400, f"chỉ dựng ra {len(html)} ký tự — bộ dựng hỏng"


# ── cái chính: một mã và hai mã cùng một hình dạng ───────────────────────────

def test_one_instrument_uses_the_same_renderer_as_two():
    """Trước bản sửa, một mã trả về chuỗi rỗng và trang rơi xuống đường vẽ cũ."""
    assert _render(["MES"]).strip(), "một mã vẫn rơi xuống đường vẽ cũ"


@pytest.mark.parametrize("names", [["MES"], ["MES", "MNQ"]])
def test_both_cases_carry_the_two_phase_table(names):
    """Bảng hai cột DECIDE | OBSERVE là thứ kể được mối nối giữa hai pha."""
    assert "mv2-calm-colhead" in _render(names, both_phases=True), names


@pytest.mark.parametrize("names", [["MES"], ["MES", "MNQ"]])
def test_both_cases_carry_the_gate_tally(names):
    """'4 / 4 gates met' tóm tắt bốn dòng dưới thành một con số — đúng với một mã y như
    với hai."""
    assert re.search(r"\d+ / \d+ gates met", _render(names)), names


@pytest.mark.parametrize("names", [["MES"], ["MES", "MNQ"]])
def test_both_cases_state_the_shape_of_the_table(names):
    assert "mv2-calm-shape" in _render(names), names


# ── nhưng KHÔNG in những thứ chỉ có nghĩa khi có hai ─────────────────────────

def test_a_sole_instrument_does_not_print_its_own_name_as_a_heading():
    """Giữ nguyên ý định của bản cũ, và nó đúng: một tiêu đề chỉ ghi "MES" khi MES là thứ
    duy nhất trên màn hình là một dòng không mang tin."""
    assert ">MES<" not in _render(["MES"])
    assert ">MES<" in _render(["MES", "MNQ"]), "hai mã thì PHẢI phân biệt được"


def test_the_shape_line_is_not_ungrammatical_for_one():
    """"1 instruments ... 4 gates each" sai ở cả số nhiều lẫn chữ "each"."""
    one = _render(["MES"])
    assert "1 instruments" not in one
    assert "gates each" not in one
    two = _render(["MES", "MNQ"])
    assert "2 instruments" in two and "gates each" in two


def test_direction_is_kept_even_for_a_sole_instrument():
    """LONG hay SHORT không suy ra được từ chỗ khác trong khối này, nên nó ở lại."""
    assert "LONG" in _render(["MES"])


# ── đường cũ vẫn phải giữ được cho trường hợp không có gì ────────────────────

def test_no_instrument_at_all_still_falls_through():
    """Không có mã nào thì không có gì để dựng bảng, và đường cũ có nhánh nói ra điều đó."""
    assert _render([]).strip() == ""
