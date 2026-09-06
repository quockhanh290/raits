"""Stage 5ZZZ-CF. Hai lỗi dàn trang trong khối Book, và cách giữ chúng không quay lại.

Cả hai đều thuộc cùng một họ: **một khung được vẽ, phần ruột không được chỉnh theo.**

  TRÀN CHỮ   Ô "Paper equity" có hai dòng phụ, cả hai đều `nowrap`, cả hai đều không có
             `overflow` chặn. Dòng dưới đã bị bắt một lần — đo được ở 1440px: rộng 232px
             chứa 413px nội dung, tràn 181px sang ô Model Inputs và in đè lên "Model age".
             Dòng TRÊN thì không được sửa, và nó là dòng nhận CÂU chứ không nhận số: nhánh
             Track 1 đổ `headline_reason` vào đó, dài 72 ký tự, trong khi nhánh legacy chỉ
             viết `since 2026-08-24` — 16 ký tự. Nó in đè lên chữ "Sharpe" của ô bên cạnh.

             Lần sửa trước đặt trong `@media (max-width: 1100px)` vì người sửa đo ở 720px.
             Nên lỗi chỉ hiện ở màn hình RỘNG — ngược với trực giác, và vì thế sống sót.

  MẤT THỤT   `next.css` vẽ khung quanh ba container. Hai cái là `.section-body` nên ăn theo
             luật khác; `.position-grid` thì không, và `.empty-state` khai `padding: 28px 0`
             — chỉ dọc, không ngang. Chữ nằm ép vào đường viền trái. Chỉ sai ở trạng thái
             RỖNG, tức là trạng thái duy nhất xảy ra mỗi ngày trong chế độ bóng; trạng thái
             có vị thế thì đúng, vì thẻ vị thế tự mang padding của nó.

Các con số ở đây không phải giá trị tự chọn: chúng đọc từ `SECTION_ANATOMY.md`, tài liệu
thiết kế đã nằm sẵn trong kho. Nên cổng cuối cùng đối chiếu CSS với chính tài liệu đó —
sửa một bên mà quên bên kia thì đỏ.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip('playwright.sync_api')

from monitor.test_realtime_dom import (  # noqa: F401,E402
    browser_page, realtime_server,
)

ROOT = Path(__file__).resolve().parent.parent
DASH = ROOT / "global_index" / "dash"
def _css(path: Path) -> str:
    """CSS đã bỏ comment.

    Bộ đọc đầu tiên không làm bước này và ba trong sáu cổng đỏ ngay — không phải vì bản sửa
    sai, mà vì lời giải thích của chính bản sửa có nhắc `@media (max-width: 1100px)` trong
    văn xuôi, và bộ đọc cắt file ở đó. Một phép đo đọc lời mô tả như đọc mã thì trả về số
    trông hợp lý và sai.
    """
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)


BASE = _css(DASH / "realtime" / "realtime.css")
NEXT = _css(DASH / "realtime-next" / "next.css")
# Trang realtime-next nap BA stylesheet. Ban dau cong doc hai, va bao mot loi khong
# ton tai: khung quanh bang Open Orders duoc thut vao boi padding cua chinh cac o
# `th`/`td`, ma luat do song trong skin.
SKIN = _css(DASH / "realtime-next" / "skin-e.css")
LOADED = (NEXT, BASE, SKIN)
JS = (DASH / "realtime" / "realtime.js").read_text(encoding="utf-8")
ANATOMY = (DASH / "SECTION_ANATOMY.md").read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    """Thân của luật cuối cùng khớp selector này — luật cuối là luật thắng."""
    hits = [m for m in re.finditer(
        r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)]
    assert hits, f"không tìm thấy luật cho {selector!r}"
    return hits[-1].group(1)


# ── tràn chữ ───────────────────────────────────────────────────────────────────────────
def test_hai_dong_phu_cua_the_paper_equity_deu_xuong_dong_duoc():
    """Viết cho CẢ HAI, không cho riêng dòng vừa hỏng: chúng là anh em trong cùng một thẻ,
    nhận cùng loại nội dung, và lần trước chỉ một cái được sửa."""
    for selector in (".equity-zone > small", ".broker-account-line"):
        body = _rule(BASE, selector)
        assert "nowrap" not in body, f"{selector} vẫn cấm xuống dòng: {body.strip()}"


def _equity_card() -> str:
    """Phần CSS dựng riêng thẻ Paper equity — nơi cả hai lần tràn chữ đã xảy ra."""
    return BASE[BASE.index(".equity-line {"):BASE.index(".zone-grid {")]


#: Những chỗ trong thẻ Paper equity được PHÉP cấm xuống dòng, kèm lý do đã rà.
#: Danh sách này là một quyết định đã xem xét, không phải một quan sát — nên nó được ghim.
NOWRAP_REVIEWED = {
    ".equity-line > b":       "con số 37px; nội dung là tiền hoặc một cụm từ chối ngắn",
    ".equity-line > strong":  "P&L ròng, luôn là số",
    ".broker-account-line a": "chữ 'Reconcile'; cố ý không bẻ đôi một liên kết",
}


def test_thu_cam_xuong_dong_trong_the_paper_equity_dung_bang_danh_sach_da_ra():
    """Ghim một QUYẾT ĐỊNH, không ghim một quan sát.

    Bản đầu của cổng này phát biểu rộng hơn: "không ô nào trong hàng bốn block vừa cấm
    xuống dòng vừa không chặn tràn". Nghe đúng, nhưng từ CSS không phân biệt được `nowrap`
    nguy hiểm với `nowrap` cố ý — nó gắn cờ cả chữ "Reconcile", thứ được cấm bẻ đôi có chủ
    đích. Một cổng gắn cờ thứ đúng là cổng người ta học cách bỏ qua.

    Cái phân biệt được: dòng nào nhận CÂU thì phải xuống dòng được, dòng nào nhận SỐ hoặc
    một từ khoá thì không cần. Ba mục dưới đây đã được đọc từng cái. Thêm một `nowrap` mới
    vào thẻ này thì cổng đỏ, và người thêm phải nói nó nhận nội dung gì — đó chính là câu
    hỏi không ai đặt ra hai lần trước, khi `headline_reason` dài 72 ký tự được đổ vào một ô
    dựng cho `since 2026-08-24`.
    """
    card = _equity_card()
    rules = list(re.finditer(r"(?m)^\s*(\.[^{\n]+)\{([^}]*)\}", card))
    assert len(rules) >= 6, f"lát cắt chỉ có {len(rules)} luật — mốc cắt đã trôi"

    found = {m.group(1).strip() for m in rules if "nowrap" in m.group(2)}
    assert found, "không còn nowrap nào trong thẻ — cổng này hết việc để kiểm"
    assert found == set(NOWRAP_REVIEWED), (
        f"thêm: {sorted(found - set(NOWRAP_REVIEWED))} · "
        f"mất: {sorted(set(NOWRAP_REVIEWED) - found)}")


def test_ban_sua_khong_bi_khoa_trong_mot_be_ngang():
    """Lỗi cũ sống sót vì bản vá nằm trong `@media (max-width: 1100px)`. Luật mới phải nằm
    ở thân file, nơi mọi bề rộng đều đọc tới."""
    top = BASE.split("@media", 1)[0]
    assert "text-wrap: pretty" in _rule(top, ".equity-zone > small")


def test_khong_de_lai_luat_chet_trong_media_query():
    """Dòng cũ trong media query giờ lặp lại đúng thứ thân file đã nói. Một luật không còn
    tác dụng nào là một lời mô tả đã rời khỏi thứ nó mô tả."""
    for chunk in BASE.split("@media")[1:]:
        block = chunk[:chunk.index("\n}\n")] if "\n}\n" in chunk else chunk
        assert ".equity-zone > small {" not in block, block[:200]


# ── mất thụt ───────────────────────────────────────────────────────────────────────────
def test_moi_khung_co_chua_o_trong_deu_thut_o_trong_vao():
    """Cổng hẹp hơn cổng tôi định viết, và đây là lý do.

    Bản đầu phát biểu điều đúng nhưng không kiểm được: "cái gì có viền thì phần ruột phải
    được thụt vào". Từ văn bản CSS không lần được quan hệ đó — nó đoán rằng luật thụt phải
    có selector bắt đầu bằng selector của khung, và đoán sai hai lần liên tiếp. Bảng Open
    Orders được thụt bởi padding của chính các ô `th`/`td`; ô trống Open Positions được thụt
    bởi một class anh em chứ không phải con của khung. Cả hai lần cổng báo một lỗi không tồn
    tại — và một cổng hay báo nhầm là cổng người ta học cách bỏ qua.

    Cái kiểm được, và cũng đúng là chỗ đã hỏng: khung nào ĐƯỢC ĐỔ `.empty-state` vào thì ô
    trống đó phải có phần thụt NGANG. `.empty-state` khai `padding: 28px 0` — dọc, không
    ngang — và điều đó đúng khi chưa có khung nào được vẽ quanh nó.
    """
    framed = {sel.strip() for sel in re.findall(
        r"(?m)^(\.[^{\n]+)\{[^}]*border: 1px solid var\(--line-card\)[^}]*\}", NEXT)}
    assert len(framed) >= 3, framed

    # Nơi nào được đổ `.empty-state` vào — đọc từ chính mã dựng, không liệt kê tay.
    hosts = set(re.findall(r'(\w+)\.innerHTML\s*=\s*.<div class="empty-state"', JS))
    assert "grid" in hosts, f"không tìm thấy nơi nào đổ empty-state: {sorted(hosts)}"

    # `grid` là `$('positionGrid')` → `.position-grid`, và next.css vẽ khung quanh nó.
    assert "$('positionGrid')" in JS
    holder = next(s for s in framed if "position-grid" in s)
    body = _rule(NEXT, holder.replace(".position-grid", ".empty-state"))
    pad = re.search(r"padding:\s*(\S+)\s+(\S+);", body)
    assert pad and pad.group(2) != "0", f"{holder} có viền, ô trống không thụt ngang: {body}"


def test_o_trong_cua_open_positions_thut_vao_ca_hai_chieu():
    body = _rule(NEXT, ".positions-section .empty-state")
    pad = re.search(r"padding:\s*([^;]+);", body)
    assert pad, body
    parts = pad.group(1).split()
    assert len(parts) == 2 and parts[1] != "0", f"không có phần thụt ngang: {pad.group(1)}"


# ── các con số phải là con số của bản thiết kế ─────────────────────────────────────────
def _anatomy_open_positions() -> str:
    start = ANATOMY.index("## Open Positions")
    return ANATOMY[start:ANATOMY.index("\n## ", start + 5)]


def test_o_trong_dung_dung_cac_con_so_ban_thiet_ke_ghi():
    """Chống trôi hai chiều: đổi CSS mà không đổi tài liệu thì đỏ, và ngược lại. Tài liệu
    này đã nằm sẵn trong kho trước khi lỗi được sửa — nó không phải thứ viết ra sau."""
    spec = _anatomy_open_positions()
    body = _rule(NEXT, ".positions-section .empty-state")
    dot = _rule(NEXT, ".positions-section .empty-state::before")

    want_pad = re.search(r"padding\s*`?(\d+px \d+px)`?", spec)
    want_gap = re.search(r"gap\s*(\d+)px", spec)
    want_dot = re.search(r"dot\s*(\d+)px\s*`?(#[0-9a-f]{6})`?", spec)
    want_font = re.search(r"sans\s*(\d+)px\s*secondary", spec)
    assert want_pad and want_gap and want_dot and want_font, spec

    assert f"padding: {want_pad.group(1)}" in body, (want_pad.group(1), body)
    assert f"gap: {want_gap.group(1)}px" in body, (want_gap.group(1), body)
    assert f"width: {want_dot.group(1)}px" in dot, (want_dot.group(1), dot)
    assert want_dot.group(2) in dot, (want_dot.group(2), dot)
    assert f"font: {want_font.group(1)}px" in body, (want_font.group(1), body)


def test_mau_secondary_la_token_chu_khong_phai_mau_tu_chon():
    """`secondary` trong tài liệu trỏ về bảng token của DESIGN_SPEC, không phải một mã màu
    ai đó gõ tay. Bảng đó nói `#a8b1c0`, và biến mang nó là `--muted`."""
    spec = (DASH / "DESIGN_SPEC.md").read_text(encoding="utf-8")
    row = re.search(r"\|\s*secondary\s*\|\s*`(#[0-9a-f]{6})`", spec)
    assert row, "bảng token không còn dòng secondary"
    tokens = (DASH / "shared" / "tokens.css").read_text(encoding="utf-8")
    declared = re.search(r"color:\s*([^;]+);", _rule(NEXT, ".positions-section .empty-state"))
    assert declared, "ô trống không khai màu"

    # Ghim MÀU chứ không ghim tên biến. Hai stylesheet gọi cùng một màu bằng hai tên --
    # `--muted` ở file nền, `--t-secondary` ở bộ token dùng chung -- và một cổng ghim tên
    # sẽ đỏ khi ai đó dùng đúng tên của file mình đang sửa. Cái phải đúng là màu.
    resolved = set()
    for var in re.findall(r"var\(\s*(--[a-z-]+)", declared.group(1)):
        hit = re.search(re.escape(var) + r":\s*(#[0-9a-f]{6})", tokens)
        if hit:
            resolved.add(hit.group(1))
    resolved |= set(re.findall(r"#[0-9a-f]{6}", declared.group(1)))
    assert resolved, f"không lần được màu từ {declared.group(1)!r}"
    assert resolved == {row.group(1)}, (
        f"bảng token nói secondary là {row.group(1)}; ô trống dùng {sorted(resolved)}")


# ── câu chữ ────────────────────────────────────────────────────────────────────────────
def test_o_trong_noi_duoc_vi_sao_no_trong():
    """Tài liệu gọi mệnh đề thứ hai là mệnh đề quan trọng, và ở chế độ bóng nó đúng là vậy:
    "không có vị thế" với "có vị thế mà không ai bảo vệ" đọc giống hệt nhau khi bảng rỗng."""
    quoted = re.search(r'\*"([^"]*No broker positions[^"]*)"\*', _anatomy_open_positions())
    assert quoted, "tài liệu không còn câu mẫu"
    # Câu mẫu nằm trong blockquote nên bị bẻ dòng kèm tiền tố `> `.
    want = " ".join(t for t in quoted.group(1).split() if t != ">")
    rendered = " ".join(re.sub(r"'\s*\+\s*'", "", JS[JS.index("No broker positions") - 40:]
                               [:260]).split())
    assert want in rendered, f"cần {want!r}\ncó  {rendered[:200]!r}"


# ── chữ có đi ra ngoài chỗ của nó không — đo trên trang thật ──────────────────────
_INK = """
() => {
  /* HAI câu hỏi, vì có HAI cách chữ đi ra khỏi chỗ của nó, và mỗi câu chỉ thấy một cách.

     A. Hộp bị ràng buộc (ô lưới), chữ rộng hơn hộp -> chữ sơn ra ngoài hộp.
        Đây là ca `#modelFitStatus`: ô 70px, chữ 202px.

     B. Hộp KHÔNG bị ràng buộc, nó tự nở theo chữ rồi vượt khỏi ô cha.
        Đây là ca `#metricDrawdownLimit` và dòng trạng thái thẻ equity. Câu A mù hoàn
        toàn trước ca này -- clientWidth bằng đúng bề rộng chữ nên không có gì "tràn".

     Bản đầu chỉ hỏi A, và ba trong bốn đột biến sống sót. Đo mực bằng `Range` chứ không
     bằng `scrollWidth`, vì `scrollWidth` tính cả hộp tooltip ẩn và biến mọi nhãn có
     tooltip thành dương tính giả ~287px. */
  const out = [];
  document.querySelectorAll('#metrics .header-zone').forEach(zone => {
    const zr = zone.getBoundingClientRect();
    const cs = getComputedStyle(zone);
    const lo = zr.left + parseFloat(cs.paddingLeft);
    const hi = zr.right - parseFloat(cs.paddingRight);
    zone.querySelectorAll('*').forEach(el => {
      if (el.offsetParent === null) return;
      const t = el.textContent.trim();
      if (!t) return;
      for (const c of el.children) if (c.textContent.trim()) return;
      const range = document.createRange();
      range.selectNodeContents(el);
      const ink = range.getBoundingClientRect();
      const name = (el.id ? '#' + el.id
                    : el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0]);
      if (el.clientWidth && ink.width - el.clientWidth > 1) {
        out.push({ kind: 'A', el: name, over: Math.round(ink.width - el.clientWidth),
                   box: Math.round(el.clientWidth), text: t.slice(0, 44) });
      }
      const spill = Math.round(Math.max(lo - ink.left, ink.right - hi));
      if (spill > 1) {
        out.push({ kind: 'B', el: name, over: spill,
                   box: Math.round(hi - lo), text: t.slice(0, 44) });
      }
    });
  });
  return out;
}
"""


@pytest.mark.parametrize("path", ["/realtime", "/realtime-next"])
@pytest.mark.parametrize("width", [2058, 1600, 1440])
def test_khong_o_nao_trong_hang_bon_block_co_chu_di_ra_ngoai_cho_cua_no(
        realtime_server, browser_page, path, width):
    """Cổng duy nhất trong phiên này bắt được thứ mà đọc CSS không bắt được.

    Ba lần liên tiếp một bản vá `white-space` được viết đúng rồi THUA — một lần vì bị khoá
    trong `@media (max-width: 1100px)`, hai lần vì thua độ cụ thể — và nằm im trong file
    không tác dụng gì. Mọi cổng đọc CSS đều xanh cả ba lần, vì luật CÓ trong file. Chỉ hình
    học trên trang thật mới trả lời được, và nó trả lời bằng số:

        #metricDrawdownLimit   vượt ô 231–462px   (tôi gây ra, trong chính phiên sửa hai
                                                   lỗi cùng loại — kiểu B)
        #modelFitStatus        chữ 202px / ô 70px  (bản vá đã có, bản vá thua — kiểu A)
        dòng trạng thái equity vượt ô              (lỗi gốc bạn chỉ ra — kiểu B)

    Đo ở ba bề rộng vì bản vá lần trước đặt trong một media query hẹp và lỗi chỉ hiện ở màn
    hình RỘNG — đo một bề ngang là đủ để bỏ sót nó.
    """
    browser_page.set_viewport_size({"width": width, "height": 900})
    browser_page.goto(f"{realtime_server}{path}", wait_until="domcontentloaded")
    browser_page.wait_for_selector("#statusRail .system-conclusion", timeout=25_000)
    browser_page.wait_for_selector("#metricDrawdown", timeout=10_000)
    browser_page.wait_for_timeout(1500)

    zones = browser_page.evaluate(
        "() => document.querySelectorAll('#metrics .header-zone').length")
    assert zones >= 4, f"chỉ thấy {zones} ô trong hàng bốn block — phép đo hỏng"

    rows = browser_page.evaluate(_INK)
    assert not rows, "\\n".join(
        f"  [{r['kind']}] +{r['over']}px (ô {r['box']}px) {r['el']} {r['text']!r}"
        for r in rows)
