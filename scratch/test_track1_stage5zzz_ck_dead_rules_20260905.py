"""Stage 5ZZZ-CK. Luật CSS không có tác dụng, đo tách TỪNG luật.

`DESIGN_AUDIT_2026-09-04.md` đo trục này bằng cách tắt/bật CẢ stylesheet và ghi rõ giới hạn
của chính nó: cách ấy không tách được "thừa thật" khỏi "bị một luật KHÁC cùng file che", nên
con số 12 của họ là TRẦN TRÊN và họ không xoá gì. Cổng này đo tách từng luật qua CSSOM.

BỐN phân loại, không thay thế nhau được:

    EFFECTIVE   tắt riêng nó thì có element đổi giá trị
    NO-OP       nó ÁP, có element khớp, tắt đi không gì đổi
    MEDIA-OFF   media query của nó không áp ở khổ này — không nói được gì
    UNMATCHED   không element nào khớp trên payload/khổ này — CHƯA BIẾT, không phải sạch

Bản đầu của phép đo này không hỏi "media có áp không" và xếp 12 luật responsive vào NO-OP
ở khổ rộng — tắt một luật `max-width: 680px` ở 1900px thì đương nhiên không đổi gì. Vì thế
nó đo ở NĂM khổ và chỉ kết luận khi có ít nhất một khổ luật ấy vừa áp vừa khớp element.

GIỚI HẠN, và nó đã suýt gây ra một lần xoá nhầm: phép đo chỉ thấy trạng thái ĐANG hiện.
`.has-tip { outline: revert }` đo ra "không đổi gì" vì element lúc đo không được focus — mà
nó chính là thứ trả lại vòng focus cho 21 phần tử. Focus, hover, `<details>` đóng, tab chưa
mở: không cái nào nằm trong lượt đo. Vì vậy danh sách dưới là "im ở những trạng thái nhìn
được", không phải "chết".
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api")

from monitor.test_realtime_dom import (  # noqa: F401,E402
    browser_page, realtime_server, stub_api,
)

#: Đo trên THẾ GIỚI STUB (cùng payload cố định mà bộ DOM dùng), không phải dữ liệu sống:
#: tập này phải như nhau giữa hai lượt chạy, còn dữ liệu sống làm nó đổi theo trạng thái
#: thanh trạng thái. Con số ở thế giới sống là 20; ở đây 13, phần chênh là những luật thế
#: giới stub không dựng ra element — CHƯA ĐO ĐƯỢC, không phải đã sạch.
#:
#: Đã đo, đã đọc từng cái, và đã quyết GIỮ — lý do đầy đủ trong khối `CK` của `next.css`.
#: Ba nhóm: phép đo không nhìn thấy trạng thái (focus/watch) · lưới dự phòng khi lớp gom
#: nhóm không chạy · mâu thuẫn thiết kế chưa ai chốt (xoá là biến bản đè thành vĩnh viễn).
#: Luật im MỚI nào không nằm trong danh sách này thì cổng đỏ, và người thêm phải nói nó
#: thuộc nhóm nào.
PINNED_INERT = {
    ('#metrics .metrics-lead', ''),
    ('.broker-account-line', '(max-width: 680px)'),
    ('.equity-line > b', ''),
    ('.has-tip', ''),
    ('.primary-column > .decision-section', ''),
    ('.primary-column > .open-issues-section', ''),
    ('.primary-column > .orders-section', ''),
    ('.primary-column > .positions-section', ''),
    ('.risk-zone .metric-dd-value > b', ''),
    ('.schedule-fact', ''),
    ('.status-rail .system-conclusion b', ''),
    ('.system-conclusion b', ''),
    ('.system-conclusion.ok .status-dot', ''),
}

WIDTHS = (1900, 1440, 1050, 680, 390)

JS = r"""
(sheetName) => {
  const sheet = [...document.styleSheets].find(s => (s.href || '').includes(sheetName));
  if (!sheet) return {err: 'no sheet ' + sheetName};
  const rules = [];
  const walk = (list, media) => {
    for (const r of list) {
      if (r.type === CSSRule.MEDIA_RULE) { walk(r.cssRules, r.conditionText); continue; }
      if (r.type === CSSRule.STYLE_RULE) rules.push({rule: r, media});
    }
  };
  walk(sheet.cssRules, null);

  const split = sel => {
    const m = sel.match(/^(.*?)(::?(?:before|after|placeholder|marker|selection|first-line))$/);
    return m ? [m[1].trim() || '*', m[2]] : [sel, null];
  };

  const out = [];
  for (const {rule, media} of rules) {
    const declared = [...rule.style].filter(p => p);
    if (!declared.length) continue;
    const rec = {sel: rule.selectorText, media: media || '', props: declared};

    if (media && !window.matchMedia(media).matches) {
      rec.verdict = 'MEDIA-OFF'; out.push(rec); continue;
    }
    let els = [], pseudo = null;
    try {
      const seen = new Set();
      for (const part of rule.selectorText.split(',').map(s => s.trim())) {
        const [base, pe] = split(part);
        if (pe) pseudo = pe;
        for (const el of document.querySelectorAll(base))
          if (!seen.has(el)) { seen.add(el); els.push(el); }
      }
    } catch (e) { els = []; }
    if (!els.length) { rec.verdict = 'UNMATCHED'; out.push(rec); continue; }

    const read = () => els.map(el => declared.map(
      p => getComputedStyle(el, pseudo).getPropertyValue(p)));
    const before = read();
    const saved = rule.style.cssText;
    rule.style.cssText = '';
    const after = read();
    rule.style.cssText = saved;

    let changed = false;
    for (let i = 0; i < before.length && !changed; i++)
      for (let j = 0; j < declared.length && !changed; j++)
        if (before[i][j] !== after[i][j]) changed = true;

    rec.verdict = changed ? 'EFFECTIVE' : 'NO-OP';
    rec.n = els.length;
    out.push(rec);
  }
  return {rules: out};
}
"""


CONTROLS = """
(sheetName) => {
  const sheet = [...document.styleSheets].find(s => (s.href || '').includes(sheetName));
  sheet.insertRule('body { letter-spacing: 3px; }', sheet.cssRules.length);
  sheet.insertRule('.model-inputs-zone { padding: 99px; }', sheet.cssRules.length);
}
"""



def _measure(page, server, width):
    # THẾ GIỚI PHẢI CỐ ĐỊNH. Bản đầu đọc dữ liệu sống và tập luật "im" đổi giữa hai lượt
    # chạy cách nhau vài phút: `.system-conclusion .status-dot` chỉ bị che khi thanh trạng
    # thái đang ở `watch`, mà trạng thái ấy do bằng chứng thật quyết định. Một cổng chập
    # chờn dạy người ta bỏ qua nó.
    stub_api(page)
    page.set_viewport_size({"width": width, "height": 1000})
    page.goto(f"{server}/realtime", wait_until="domcontentloaded")
    page.wait_for_selector("#statusRail .system-conclusion", timeout=25_000)
    page.wait_for_timeout(8000)
    page.evaluate(CONTROLS, "next.css")
    res = page.evaluate(JS, "next.css")
    assert "err" not in res, res
    rows = res["rules"]

    # Hai luật đối chứng, kiểm ở MỖI khổ: một cái chắc chắn có tác dụng, một cái chắc chắn
    # bị `skin-e` che. Không có bước này thì một phép đo hỏng sẽ báo "sạch" hoặc báo hàng
    # loạt, và cả hai đều trông như kết quả.
    eff = [r for r in rows if r["sel"] == "body" and "letter-spacing" in r["props"]]
    mask = [r for r in rows if r["sel"] == ".model-inputs-zone"
            and "padding-top" in r["props"]]
    assert eff and eff[0]["verdict"] == "EFFECTIVE", (width, eff)
    assert mask and mask[0]["verdict"] == "NO-OP", (width, mask)
    return [r for r in rows if r not in eff + mask]


def _classify(page, server):
    """(im ở mọi khổ đo được, có tác dụng ở ít nhất một khổ) — hai tập RỜI NHAU.

    Tách hai tập ra là bản sửa. Bản đầu chỉ tính tập "im" rồi lấy `PINNED - im` làm "đã
    sửa", nên mọi mục KHÔNG ĐO ĐƯỢC ở lượt này bị báo là đã sửa — tám mục cùng lúc, chỉ vì
    thế giới stub không dựng ra element cho chúng. "Chưa đo được" không phải "đã xong",
    đúng cái luật mà chính phép đo này in ra bốn phân loại để giữ.
    """
    obs: dict[tuple[str, str], list[str]] = {}
    for w in WIDTHS:
        rows = _measure(page, server, w)
        assert len(rows) > 200, f"@{w}px chỉ đọc được {len(rows)} luật — phép đo hỏng"
        for r in rows:
            obs.setdefault((r["sel"], r["media"]), []).append(r["verdict"])
    inert, effective = set(), set()
    for k, v in obs.items():
        live = [x for x in v if x in ("EFFECTIVE", "NO-OP")]
        if not live:
            continue
        (inert if all(x == "NO-OP" for x in live) else effective).add(k)
    assert inert or effective, "không luật nào đo được — phép đo hỏng, không phải file sạch"
    return inert, effective


def test_khong_luat_chet_nao_MOI_trong_next_css(realtime_server, browser_page):
    """Một luật chỉ bị gọi là im khi ở MỌI khổ nó vừa áp vừa khớp element, tắt đi đều không
    đổi gì. Danh sách im đã được ghim; cổng bắt cái mới."""
    inert, _ = _classify(browser_page, realtime_server)
    fresh = sorted(inert - PINNED_INERT)
    assert not fresh, 'luat im MOI, chua ai quyet giu hay xoa:' + chr(10) + chr(10).join(
        f"  {x}" + (f"  @{m}" if m else "") for x, m in fresh)


def test_muc_ghim_nao_da_het_im_thi_phai_go_khoi_danh_sach(
        realtime_server, browser_page):
    """Ghim theo HAI chiều — nhưng chỉ gỡ khi có BẰNG CHỨNG nó đã sống lại, tức đo ra
    EFFECTIVE ở ít nhất một khổ. Mục không đo được ở lượt này thì để yên."""
    _, effective = _classify(browser_page, realtime_server)
    stale = sorted(PINNED_INERT & effective)
    assert not stale, 'da het im thi go khoi PINNED_INERT:' + chr(10) + chr(10).join(
        f"  {x}" + (f"  @{m}" if m else "") for x, m in stale)


def test_ghi_lai_tap_im_de_ghim(realtime_server, browser_page, tmp_path_factory):
    """Không phải phép kiểm — là cách sinh danh sách ghim mà không phải gõ tay."""
    import json, os
    if not os.environ.get("CK_DUMP"):
        pytest.skip("chỉ chạy khi cần sinh lại danh sách ghim")
    inert, effective = _classify(browser_page, realtime_server)
    p = __import__("pathlib").Path(os.environ["CK_DUMP"])
    p.write_text(json.dumps({"inert": sorted(inert), "effective": sorted(effective)},
                            ensure_ascii=False, indent=1), encoding="utf-8")
