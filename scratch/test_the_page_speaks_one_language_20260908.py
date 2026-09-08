"""Màn hình nói MỘT thứ tiếng. TỆP MỚI.

Vì sao có tệp này
-----------------
Bảng điều khiển viết bằng tiếng Anh. Chú thích trong mã thì viết bằng tiếng Việt, có chủ
đích, và luật này KHÔNG đụng tới chúng — 570 dòng chú thích tiếng Việt trong tệp giao diện
là cách kho này giải thích cho người đọc, không phải thứ người vận hành nhìn thấy.

Cái đã xảy ra là chữ **hiện lên màn hình** trôi sang tiếng Việt: chín nhãn nguyên nhân, một
câu dẫn và bốn câu giải thích của tầng phân loại. Trên cùng một khung, ngay cạnh nhau:

    Refusals     23, không cái nào cần người
    SPY daily    SPY daily file covers 2026-09-04 — the latest session...

Không dòng nào sai. Hai dòng cạnh nhau bằng hai thứ tiếng thì người đọc phải chuyển ngữ
giữa hai hàng của cùng một bảng.

Vì sao phải là một phép kiểm chứ không phải một lời nhắc
--------------------------------------------------------
Chỗ này đã trôi một lần rồi, và nó trôi vì mỗi lần thêm chữ người ta nhìn hàng bên cạnh chứ
không nhìn cả trang. Lần sau cũng sẽ thế. Một lời nhắc trong tài liệu không chặn được điều
đó; một phép kiểm thì có.

Cách đo
-------
Bóc chú thích bằng máy trạng thái thật (chuỗi, template, `//`, `/* */`, docstring Python)
rồi mới soi các chuỗi còn lại. Bộ lọc theo dòng đã đếm nhầm **22 mảnh chú thích nhiều dòng**
thành chữ trên màn hình — con số sai đó trông hợp lý y như con số đúng.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import sys
import tokenize

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Dấu thanh tiếng Việt. `ã`/`à` cũng khớp phần mojibake `Ã—` của dấu nhân trong vài regex
#: đọc log, nên những tệp ấy không nằm trong danh sách dưới đây.
VN = re.compile(
    r'[àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]', re.I)

BACKSLASH = chr(92)

#: Nơi chữ trên màn hình được sinh ra. Đây là danh sách phải MỞ RỘNG khi có nguồn mới, và
#: `test_the_watched_list_still_points_at_real_files` là thứ giữ nó không mục.
WATCHED = (
    "global_index/dash/realtime/realtime.js",
    "global_index/dash/realtime/index.html",
    "global_index/track1_refusal_cause.py",
    "monitor/backend/track1_runtime_reader.py",
)


def strip_js_comments(src: str) -> str:
    """Bỏ `//` và `/* */`, GIỮ nguyên nội dung chuỗi và template."""
    out, i, n, st = [], 0, len(src), None
    while i < n:
        c = src[i]
        nx = src[i + 1] if i + 1 < n else ""
        if st is None:
            if c == "/" and nx == "/":
                st = "//"; i += 2; continue
            if c == "/" and nx == "*":
                st = "/*"; i += 2; continue
            if c in ('"', "'", "`"):
                st = c; out.append(c); i += 1; continue
            out.append(c); i += 1; continue
        if st == "//":
            if c == "\n":
                st = None; out.append(c)
            i += 1; continue
        if st == "/*":
            if c == "*" and nx == "/":
                st = None; i += 2; continue
            if c == "\n":
                out.append(c)
            i += 1; continue
        if c == BACKSLASH:
            out.append(src[i:i + 2]); i += 2; continue
        out.append(c)
        if c == st:
            st = None
        i += 1
    return "".join(out)


def strip_html_comments(src: str) -> str:
    """`<!-- … -->` không hiện ra, kể cả khi nằm trong một template literal.

    Một câu như thế đã sống sót qua vòng dọn đầu tiên và trông y hệt một lỗi thật."""
    return re.sub(r"<!--.*?-->", "", src, flags=re.S)


def strip_py_docstrings(src: str) -> str:
    keep, spans = [], set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            keep.append(tok)
    for node in ast.walk(ast.parse(src)):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)) and body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            spans.add((body[0].lineno, body[0].end_lineno))
    out = [t for t in keep
           if not (t.type == tokenize.STRING
                   and any(a <= t.start[0] and t.end[0] <= b for a, b in spans))]
    return tokenize.untokenize(out)


def screen_strings(path: pathlib.Path) -> list:
    src = path.read_text(encoding="utf-8")
    code = (strip_py_docstrings(src) if path.suffix == ".py"
            else strip_js_comments(src))
    code = strip_html_comments(code)
    hits = []
    for i, line in enumerate(code.splitlines()):
        for m in re.finditer(r"'([^'\n]*)'|\"([^\"\n]*)\"|`([^`\n]*)`", line):
            t = m.group(1) or m.group(2) or m.group(3) or ""
            if VN.search(t):
                hits.append((i + 1, t[:90]))
    return hits


# ── luật ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", WATCHED)
def test_no_vietnamese_reaches_the_screen(rel):
    hits = screen_strings(REPO / rel)
    assert not hits, f"{rel}: {hits}"


def test_the_watched_list_still_points_at_real_files():
    """Một danh sách trỏ vào tệp đã đổi tên là một phép kiểm xanh vì không có gì để kiểm."""
    for rel in WATCHED:
        assert (REPO / rel).is_file(), rel


def test_the_refusal_row_still_names_its_causes_in_words():
    """Dọn ngôn ngữ không được biến câu thành mã máy — đó là bước lùi về đúng chỗ xuất phát."""
    js = (REPO / "global_index" / "dash" / "realtime" / "realtime.js").read_text(
        encoding="utf-8")
    block = js[js.index("const REFUSAL_WORDS"):]
    block = block[:block.index("};") + 2]
    for phrase in ("market closed", "session open, no bars", "the two halves disagree"):
        assert phrase in block, phrase
    assert "market_closed:" in block            # khoá vẫn là mã, giá trị mới là câu


def test_the_operator_actions_are_still_full_sentences():
    """Nhãn không kèm việc phải làm là một cái tên mới cho cùng sự bối rối — dịch xong vẫn thế."""
    from global_index import track1_refusal_cause as rc

    for f in rc.FAULTS:
        assert len(rc.ACTIONS[f].split()) >= 10, f


# ── phép đo tự kiểm ──────────────────────────────────────────────────────────

def test_the_stripper_does_not_simply_delete_everything():
    """Một bộ bóc chú thích quá tay sẽ làm mọi phép kiểm trên xanh mà không kiểm gì cả.

    Đây là cái chốt: nếu nó nuốt luôn chuỗi thì `market closed` cũng biến mất."""
    js = REPO / "global_index" / "dash" / "realtime" / "realtime.js"
    code = strip_js_comments(js.read_text(encoding="utf-8"))
    assert "market closed" in code
    assert len(code) > len(js.read_text(encoding="utf-8")) * 0.4


def test_the_stripper_actually_removes_comments():
    """Và cái chốt ngược lại: nếu nó không bóc gì thì 22 mảnh chú thích sẽ báo đỏ giả."""
    js = REPO / "global_index" / "dash" / "realtime" / "realtime.js"
    raw = js.read_text(encoding="utf-8")
    assert "ĐƯỜNG CƠ SỞ" in raw, "chú thích mẫu đã đổi — chọn mẫu khác"
    assert "ĐƯỜNG CƠ SỞ" not in strip_js_comments(raw)


def test_a_vietnamese_string_would_be_caught(tmp_path):
    """Chứng minh phép kiểm biết đỏ, không cần chờ ai đó viết nhầm thật."""
    f = tmp_path / "m.js"
    f.write_text("// chú thích tiếng Việt thì bỏ qua\nconst x = 'thị trường đóng';\n",
                 encoding="utf-8")
    hits = screen_strings(f)
    assert [t for _, t in hits] == ["thị trường đóng"], hits


def test_a_vietnamese_comment_would_not_be_caught(tmp_path):
    """Và biết THA đúng thứ phải tha — chú thích là quy ước của kho này, không phải lỗi."""
    f = tmp_path / "m.js"
    f.write_text("/* Ô này nói vì sao.\n   Dòng thứ hai cũng tiếng Việt. */\nconst x = 'ok';\n",
                 encoding="utf-8")
    assert screen_strings(f) == []
