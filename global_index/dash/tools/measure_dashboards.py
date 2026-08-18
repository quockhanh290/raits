"""Đo trạng thái hiển thị của cả năm dashboard, để có mốc so trước khi sửa.

Chạy:  python global_index/dash/tools/measure_dashboards.py

Ghi ra `global_index/dash/DASHBOARD_BASELINE.md` (đọc được) và `.json` (so bằng
máy). Cả script này lẫn kết quả đều được commit: một con số không kèm công cụ đã
tạo ra nó là con số không tái tạo được, và mốc so không tái tạo được thì lần sau
không ai dám dùng.

Bốn cái bẫy đã thật sự làm sai số trong phiên 2026-08-17, nay chặn ngay ở đây:

  1. Node văn bản KHÔNG được vẽ vẫn có toạ độ, theo HAI cách khác nhau. Node cỡ 0
     thì dễ thấy. Khó thấy hơn: nội dung của `<details>` đóng giữ NGUYÊN kích
     thước cũ vì nó nằm dưới `content-visibility: hidden` — chỉ là không bao giờ
     được vẽ. Đếm chúng cho ra 397 "va chạm" ở /paper Gates; lọc đúng còn 0.
  2. Nền trong suốt một phần. `rgba(255,255,255,0.01)` bị coi là nền đặc thì tỉ số
     tương phản thành vô nghĩa. Ở đây mọi lớp được ghép xuống nền trang.
  3. Chữ đã bị `overflow` cắt vẫn trả hình học. Không loại nó ra thì mọi thẻ kẹp
     dòng và mọi khung cuộn đều báo "chữ đè chữ" giả. Danh sách phải đủ bốn:
     hidden, clip, auto, scroll.
  4. Trang chưa render xong vẫn cho ra "0 vấn đề". Mỗi trang phải vượt ngưỡng số
     node tối thiểu, nếu không dòng đó bị đánh dấu KHÔNG TIN ĐƯỢC chứ không phải
     sạch, và script trả mã lỗi.

ĐÂY LÀ ẢNH CHỤP, KHÔNG PHẢI MỐC ĐÓNG BĂNG — và sự khác biệt đó quan trọng.

Đã thử làm nó tái tạo được và không được: chạy trên backend live, `/realtime` ra
226 node lần này và 294 lần sau, cùng một commit, vì dữ liệu vận hành thay đổi.
Thử cố định bằng payload của `test_realtime_dom.py` thì bốn trang kia bị bỏ đói —
bộ đó viết cho `/realtime`, nên `/paper` tụt còn 22 node. Không có một bộ payload
nào phục vụ cả năm trang.

Nên dùng nó ĐÚNG cách: chạy trước khi sửa và chạy lại ngay sau khi sửa, TRONG
CÙNG một buổi, rồi so hai lần chạy với nhau. Cột nào phụ thuộc lượng dữ liệu
(số node, số va chạm, số node dưới AA) chỉ có nghĩa khi so như vậy. Cột nào là
tính chất thiết kế (stylesheet nạp, số cỡ chữ, số họ chữ, tràn trang, cắt ngoài
mép) thì bền hơn và so được qua thời gian.

Giới hạn còn lại, ghi thẳng vào báo cáo: chỉ đo nội dung ĐANG hiện. Ba tab của
/paper được mở lần lượt, nhưng phần trong `<details>` đóng thì không.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

MIN_TEXT_NODES = 40          # dưới ngưỡng này coi như trang chưa dựng xong
VIEWPORTS = [(1900, 1000), (390, 844)]
PAGES = ["/realtime", "/paper", "/analytics", "/reports", "/"]

PROBE = r"""
() => {
  // Bố trí xong KHÔNG có nghĩa là được vẽ. Nội dung của `<details>` đóng nằm
  // dưới `content-visibility: hidden`: `getBoundingClientRect()` vẫn trả kích
  // thước cũ, còn `elementFromPoint` tại tâm nó trả về phần tử phía sau. Bỏ qua
  // bước này thì mỗi khối thu gọn thành một chùm "chữ đè chữ" giả — đã đo:
  // /paper Gates ở 390px báo 397 va chạm, lọc đúng còn 0, và 348 trên 693 node
  // được đếm là ma.
  const notPainted = el => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (cs.contentVisibility === 'hidden' || cs.visibility === 'hidden') return true;
      const parent = p.parentElement;
      if (parent && parent.tagName === 'DETAILS' && !parent.open && p.tagName !== 'SUMMARY')
        return true;
    }
    return false;
  };
  const outOfView = (el, rect) => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (!/hidden|clip|auto|scroll/.test(cs.overflowY + ' ' + cs.overflowX)) continue;
      const b = p.getBoundingClientRect();
      if (rect.top >= b.bottom - 1 || rect.bottom <= b.top + 1) return true;
      if (rect.left >= b.right - 1 || rect.right <= b.left + 1) return true;
    }
    return false;
  };
  const lum = c => {
    const p = (c || '').match(/[\d.]+/g); if (!p) return null;
    const [r, g, b] = p.slice(0, 3).map(Number).map(v => {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const bgOf = el => {
    const stack = [];
    for (let p = el; p && p.nodeType === 1; p = p.parentElement) {
      const m = (getComputedStyle(p).backgroundColor || '').match(/[\d.]+/g);
      if (!m) continue;
      const a = m.length > 3 ? Number(m[3]) : 1;
      if (a === 0) continue;
      stack.push({ r: +m[0], g: +m[1], b: +m[2], a });
      if (a >= 0.999) break;
    }
    const page = (getComputedStyle(document.documentElement).backgroundColor || '')
      .match(/[\d.]+/g) || [0, 0, 0];
    let out = { r: +page[0], g: +page[1], b: +page[2] };
    for (let i = stack.length - 1; i >= 0; i--) {
      const l = stack[i];
      out = { r: l.r * l.a + out.r * (1 - l.a),
              g: l.g * l.a + out.g * (1 - l.a),
              b: l.b * l.a + out.b * (1 - l.a) };
    }
    return `rgb(${out.r}, ${out.g}, ${out.b})`;
  };

  const leaves = [];
  let belowAA = 0, contrastCounted = 0;
  const sizes = new Set(), families = new Set();
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = w.nextNode())) {
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (el.closest('[hidden]') || notPainted(el)) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    const box = r.getBoundingClientRect();
    if (box.width < 2 || box.height < 2) continue;        // không được vẽ
    const cs = getComputedStyle(el);
    sizes.add(cs.fontSize);
    families.add(cs.fontFamily.split(',')[0].replace(/["']/g, '').trim());
    const L1 = lum(cs.color), L2 = lum(bgOf(el));
    if (L1 !== null && L2 !== null) {
      contrastCounted++;
      if ((Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05) < 4.5) belowAA++;
    }
    for (const rect of r.getClientRects()) {
      if (rect.width < 1 || rect.height < 1) continue;
      if (outOfView(el, rect)) continue;
      leaves.push({ t: n.nodeValue.trim().slice(0, 26), el, rect });
    }
  }

  const collisions = [];
  for (let i = 0; i < leaves.length; i++)
    for (let j = i + 1; j < leaves.length; j++) {
      const a = leaves[i].rect, b = leaves[j].rect;
      if (leaves[i].el.contains(leaves[j].el) || leaves[j].el.contains(leaves[i].el)) continue;
      const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (ox > 1 && oy > 3) collisions.push(leaves[i].t + ' | ' + leaves[j].t);
    }

  const scroller = el => {
    for (let p = el; p && p !== document.body; p = p.parentElement) {
      const cs = getComputedStyle(p);
      if (/auto|scroll/.test(cs.overflowX) && p.scrollWidth > p.clientWidth + 1) return true;
    }
    return false;
  };
  let clipped = 0;
  document.querySelectorAll('main *, header *').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 1) return;
    if (r.right > innerWidth + 1 && !scroller(el)) clipped++;
  });

  return {
    textNodes: leaves.length,
    collisions: collisions.length,
    collisionSample: collisions.slice(0, 4),
    clippedPastRightEdge: clipped,
    pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    contrastCounted, belowAA,
    distinctFontSizes: [...sizes].length,
    fontFamilies: [...families].sort(),
    stylesheets: [...document.styleSheets].map(s => (s.href || 'inline').split('/').pop()),
  };
}
"""


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def main() -> int:
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright

    from monitor.backend.app import app

    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.port}"

    basis = {
        "measured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "commit": git("rev-parse", "--short", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "dash_tree_state": git("status", "--porcelain", "--",
                               "global_index/dash") or "(sạch)",
        "python": sys.version.split()[0],
        "min_text_nodes_required": MIN_TEXT_NODES,
        "data_source": "backend live — số ĐẾM là ảnh chụp, không phải mốc đóng băng",
    }

    rows: list[dict] = []
    untrusted: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for path in PAGES:
            for width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(f"{base}{path}", wait_until="domcontentloaded")
                # Chờ theo TÍN HIỆU, không theo đồng hồ. Bản đầu dùng
                # `wait_for_timeout(2500)` và đo /realtime ra 86 node trong khi
                # đo tay trên cùng trang được 234 — trang chưa dựng xong, và một
                # phép đo trên trang chưa dựng cho ra "0 vấn đề" rất thuyết phục.
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)

                tabs = page.eval_on_selector_all(
                    ".paper-tab-nav label", "els => els.map(e => e.textContent.trim())")
                for index, label in enumerate(tabs or [None]):
                    if label is not None:
                        page.eval_on_selector_all(
                            ".paper-tab-nav label",
                            "(els, i) => els[i] && els[i].click()", index)
                        page.wait_for_timeout(700)
                    # Thử lại thay vì chờ mù. Bản trước đo /paper Overview ra 22
                    # node ở 1900 và 197 ở 390 — CÙNG một tab, nên chênh lệch đó
                    # là của công cụ chứ không phải của trang. Một mốc so không
                    # lặp lại được thì lần sau không ai dám dùng.
                    result = page.evaluate(PROBE)
                    for _ in range(6):
                        if result["textNodes"] >= MIN_TEXT_NODES:
                            break
                        page.wait_for_timeout(1000)
                        result = page.evaluate(PROBE)
                    name = path + (f" · {label}" if label else "")
                    rendered = result["textNodes"] >= MIN_TEXT_NODES
                    if not rendered:
                        untrusted.append(
                            f"{name} @{width}px: chỉ {result['textNodes']} node được vẽ — "
                            "trang chưa dựng xong, mọi số 0 ở dòng này không kiểm gì")
                    rows.append({"page": name, "width": width,
                                 "rendered": rendered, **result})
                page.close()
        browser.close()
    server.shutdown()

    dash = ROOT / "global_index" / "dash"
    (dash / "DASHBOARD_BASELINE.json").write_text(
        json.dumps({"basis": basis, "rows": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8")

    lines = ["# Mốc đo hiển thị — năm dashboard", "",
             "Sinh bởi `global_index/dash/tools/measure_dashboards.py`. **Đừng sửa tay**:",
             "chạy lại script để cập nhật, nếu không con số sẽ rời khỏi thứ nó mô tả.", ""]
    lines += [f"- **{k}**: `{v}`" for k, v in basis.items()]
    lines += ["", "## Kết quả", "",
              "| Trang | Rộng | Node vẽ ra | Chữ đè chữ | Cắt ngoài mép | Tràn trang |"
              " Dưới AA | Cỡ chữ | Họ chữ |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        flag = "" if r["rendered"] else " ⚠"
        lines.append(
            f"| {r['page']}{flag} | {r['width']} | {r['textNodes']} | {r['collisions']} |"
            f" {r['clippedPastRightEdge']} | {r['pageOverflow']} |"
            f" {r['belowAA']}/{r['contrastCounted']} | {r['distinctFontSizes']} |"
            f" {len(r['fontFamilies'])} |")
    lines += ["", "## Đo được cái gì, và không đo được cái gì", "",
              "- Chỉ nội dung ĐANG hiện. Ba tab của `/paper` được mở lần lượt, nhưng phần",
              "  nằm trong `<details>` đóng thì không — chúng không có kích thước, và đếm",
              "  chúng chính là cái đã cho ra một con số sai gấp mười lần.",
              "- Tương phản tính sau khi ghép mọi lớp nền trong suốt xuống nền trang.",
              "- Chữ bị `overflow` cắt không tính là va chạm: nó không được vẽ ra.",
              "- Cột `Họ chữ` đếm số họ chữ khác nhau đang thật sự hiển thị trên trang.",
              "- **Số đếm là ảnh chụp trên dữ liệu live.** Cùng một commit, `/realtime` đã",
              "  ra 226 rồi 294 node ở hai lần chạy khác nhau. So hai lần chạy trong cùng",
              "  một buổi thì có nghĩa; so với một bảng ghi từ tuần trước thì không."]
    if untrusted:
        lines += ["", "## Dòng KHÔNG tin được", ""] + [f"- {u}" for u in untrusted]
    (dash / "DASHBOARD_BASELINE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    if untrusted:
        print("\nCÓ DÒNG KHÔNG TIN ĐƯỢC — xem mục cuối.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
