"""Stage 5ZZZ-CU. Ba chỗ chủ dự án chỉ ra, đo trên trang thật.

1. CHỮ TRÊN ĐƯỜNG NGƯỠNG. Nhãn nằm TRONG vùng vẽ, đè lên nến. Bản trước đặt cho nó một
   nền cùng màu thẻ — nền ấy phủ hết chữ nhưng không tách ô chữ khỏi biểu đồ, và bản chưa
   vũ trang còn bị hạ xuống `opacity: .75`, tức là làm mờ đúng thứ đang phải tranh chỗ với
   thân nến. Ba mức giá đọc được hay không quyết định ở đây.

2. Ô TRỐNG KHÔNG CÓ GÌ ĐỂ NÓI. `No slot has recorded a reading for this session yet.` chỉ
   nói lại điều mà một ô trống đã nói, trong một khối cao 250px.

   Nửa còn lại của phép kiểm này QUAN TRỌNG HƠN nửa đầu: ba câu còn lại ở cùng chỗ mang ba
   sự thật KHÁC nhau về cùng một ô trống, và không sự thật nào có ở đâu khác trên trang.
   Một bản sửa "bỏ câu thừa" quét luôn cả ba sẽ làm cổng đầu xanh trong khi thông tin biến
   mất — đúng dạng lỗi mà luật "bản sửa làm bớt hiển thị thì thứ bị bớt đi đâu" nói tới.

3. ĐỘ BẤT ĐỊNH VÀ MỐC KIỂM. Ba mức bất định in cùng một bậc chữ xám, nên cái chấm 5px là
   thứ duy nhất mang tin. Và mốc kiểm gần nhất trả lời "cũ bao nhiêu" (`43h ago`) mà không
   trả lời "lúc nào" — vế duy nhất đối chiếu được với nhật ký job.
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright.sync_api")

from monitor.test_realtime_dom import (  # noqa: F401,E402
    _market_view, _regime, _with_slot_series, browser_page, open_realtime,
    realtime_server, stub_api,
)

SLEEVE_TAB = '[data-mv-inner="Price context"]'


# ══════════════════════════════════════════════════════════════════════════════════════
# 1 · Chữ trên đường ngưỡng
# ══════════════════════════════════════════════════════════════════════════════════════

_LEVELS = [
    {"kind": "stop", "label": "Planned stop", "price": 66760.0, "armed": False},
    {"kind": "setup_trigger", "label": "Trigger (pre-session low)", "price": 66790.0,
     "armed": False},
    {"kind": "reference", "label": "Session open", "price": 66805.0, "armed": False},
]

_STYLE_JS = """
() => [...document.querySelectorAll('.mv-level-label')].map(e => {
  const c = getComputedStyle(e);
  return {t: e.textContent.trim(), bg: c.backgroundColor, weight: c.fontWeight,
          size: parseFloat(c.fontSize), op: parseFloat(c.opacity),
          bw: parseFloat(c.borderTopWidth), bc: c.borderTopColor, color: c.color};
})
"""


def _open_with_levels(page, server):
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    s = mv["sleeves"]["global_nkd"]
    s["setup_boundary"] = dict(s["setup_boundary"])
    s["setup_boundary"]["price_levels"] = _LEVELS
    s["setup_boundary"]["status"] = "armed_pending"
    s["price_levels"] = _LEVELS
    stub_api(page, {"/api/v1/track1-market-view": {
        "market_view": mv, "regime": _regime(),
        "sessions": [{"day": "2026-08-27", "has_diagnostics": True}]}})
    open_realtime(page, server)
    page.click(SLEEVE_TAB)
    page.wait_for_selector(".mv-level-label", timeout=20_000)
    return page.evaluate(_STYLE_JS)


def _alpha(css_colour: str) -> float:
    m = re.match(r"rgba?\(([^)]*)\)", css_colour or "")
    if not m:
        return 1.0
    parts = [p.strip() for p in m.group(1).replace("/", ",").split(",")]
    return float(parts[3]) if len(parts) >= 4 else 1.0


def test_moi_nhan_muc_gia_co_mot_o_chu_dac_tach_khoi_nen_bieu_do(
        realtime_server, browser_page):
    """Nền đặc VÀ một vành. Chỉ có nền là chưa đủ: nền cùng màu thẻ làm ô chữ chìm vào
    biểu đồ, và ranh giới duy nhất còn lại là chỗ nền vừa vặn hết chữ."""
    labs = _open_with_levels(browser_page, realtime_server)
    assert len(labs) >= 3, f"chỉ thấy {len(labs)} nhãn — phép đo hỏng, không phải trang sạch"
    for a in labs:
        assert _alpha(a["bg"]) >= 0.99, f"{a['t'][:34]!r} nền trong suốt: {a['bg']}"
        assert a["bw"] >= 1, f"{a['t'][:34]!r} không có vành: {a['bw']}px"
        assert _alpha(a["bc"]) >= 0.5, f"{a['t'][:34]!r} vành trong suốt: {a['bc']}"


def test_nhan_chua_vu_trang_khong_bi_lam_mo_toi_muc_kho_doc(realtime_server, browser_page):
    """`.75` là mức đã bị chỉ ra. Trạng thái "chưa vũ trang" do NÉT ĐỨT của đường và do
    chính chữ trong nhãn nói; làm mờ chữ nằm trên nến là trả giá ở đúng chỗ đắt nhất."""
    labs = _open_with_levels(browser_page, realtime_server)
    mo = [(a["t"][:34], a["op"]) for a in labs if a["op"] < 0.9]
    assert not mo, f"nhãn bị làm mờ dưới 0.9: {mo}"


def test_chu_tren_hinh_khong_dung_bac_manh_nhat(realtime_server, browser_page):
    labs = _open_with_levels(browser_page, realtime_server)
    for a in labs:
        assert int(a["weight"]) >= 600, f"{a['t'][:34]!r} nét {a['weight']}"
        assert a["size"] >= 11.5, f"{a['t'][:34]!r} cỡ {a['size']}px"


# ══════════════════════════════════════════════════════════════════════════════════════
# 2 · Ô trống: bỏ câu rỗng, GIỮ ba câu mang tin
# ══════════════════════════════════════════════════════════════════════════════════════

def _open_price_tab(page, server, mv, sessions):
    stub_api(page, {"/api/v1/track1-market-view": {
        "market_view": mv, "regime": _regime(), "sessions": sessions}})
    open_realtime(page, server)
    page.click(SLEEVE_TAB)
    page.wait_for_selector(".mv2-plot", timeout=20_000)
    page.wait_for_timeout(400)
    return page.query_selector(".mv2-slotchart-empty")


def test_khong_slot_nao_va_khong_ly_do_nao_thi_khong_dung_khoi_nao(
        realtime_server, browser_page):
    """`_market_view()` không mang `slot_series`, và phiên thì CÓ bản ghi chẩn đoán — nên
    không có sự thật nào để nêu ngoài chính sự trống. Không render gì."""
    box = _open_price_tab(browser_page, realtime_server, _market_view(),
                          [{"day": "2026-08-27", "has_diagnostics": True}])
    assert box is None, f"vẫn dựng khối rỗng: {box.inner_text()[:120]!r}"


def test_slot_co_ghi_nhung_khong_slot_nao_cong_bo_gia_thi_VAN_phai_noi_ra(
        realtime_server, browser_page):
    """Sleeve Stress đúng hình dạng này: 24 slot ghi lại, 0 slot công bố giá đóng cửa, vì
    bộ dò của nó đo độ rộng của cả rổ chứ không đo một cây nến. Không nói ra thì người đọc
    ngồi chờ một đường sẽ không bao giờ tới."""
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    for p in mv["sleeves"]["global_nkd"]["strategy"]["slot_series"]:
        p["close"] = None
    box = _open_price_tab(browser_page, realtime_server, mv,
                          [{"day": "2026-08-27", "has_diagnostics": True}])
    assert box is not None, "đã quét luôn cả câu mang tin"
    txt = box.inner_text()
    assert "none published a close price" in txt, txt[:200]


def test_kho_slot_chua_voi_toi_ngay_nay_thi_VAN_phai_noi_ra(realtime_server, browser_page):
    """Sự thật thứ hai, và nó khác hẳn sự thật thứ nhất: các điều kiện phía trên là thật,
    dựng lại từ nến trên đĩa — chỉ riêng dòng theo slot là chưa có kho để đọc."""
    mv = _market_view()
    mv["sleeves"]["global_nkd"]["strategy"]["slot_series_session"] = "2026-08-27"
    box = _open_price_tab(browser_page, realtime_server, mv,
                          [{"day": "2026-08-27", "has_diagnostics": False}])
    assert box is not None, "đã quét luôn cả câu mang tin"
    assert "per-slot store" in box.inner_text(), box.inner_text()[:200]


# ══════════════════════════════════════════════════════════════════════════════════════
# 3 · Độ bất định có màu, và mốc kiểm có giờ
# ══════════════════════════════════════════════════════════════════════════════════════

def _open_regime(page, server, entropy):
    r = _regime()
    r["entropy_bits"] = entropy
    stub_api(page, {"/api/v1/track1-market-view": {
        "market_view": {"session_date": "2026-08-27", "sleeves": {}}, "regime": r}})
    open_realtime(page, server)
    page.wait_for_selector(".rg2-uncertain", timeout=20_000)
    return page.eval_on_selector(
        ".rg2-uncertain",
        "el => ({t: el.innerText.trim(), color: getComputedStyle(el).color})")


@pytest.mark.parametrize("entropy,muc", [(0.05, "low"), (0.4, "moderate"), (1.2, "high")])
def test_moi_muc_bat_dinh_co_mau_rieng_cua_no(realtime_server, browser_page, entropy, muc):
    got = _open_regime(browser_page, realtime_server, entropy)
    assert muc in got["t"].lower(), got["t"]
    # Bậc nhãn xám là bậc mà mọi dòng phụ khác trên thẻ đang dùng, và là bậc mà cả ba mức
    # dùng chung trước bản sửa. Còn ở đó nghĩa là chưa có màu nào được gán.
    # Đọc token từ CHÍNH trang, không gõ tay: skin có thể đổi giá trị và một literal ở đây
    # sẽ xanh vì so với một màu không còn ai dùng.
    xam = browser_page.evaluate(
        "() => { const d = document.createElement('span');"
        " d.style.color = 'var(--t-label)'; document.body.appendChild(d);"
        " const c = getComputedStyle(d).color; d.remove(); return c; }")
    assert xam and xam != "rgb(0, 0, 0)", f"không đọc được bậc nhãn: {xam!r}"
    assert got["color"] != xam, f"{muc} vẫn dùng bậc nhãn xám {xam}"


def test_ba_muc_bat_dinh_khong_dung_chung_mot_mau(realtime_server, browser_page):
    """Ghim NGHĨA. Ba lượt trên có thể xanh trong khi cả ba cùng đổi sang MỘT màu khác —
    và như thế thì chấm màu vẫn là thứ duy nhất phân biệt được mức."""
    mau = {muc: _open_regime(browser_page, realtime_server, e)["color"]
           for e, muc in [(0.05, "low"), (0.4, "moderate"), (1.2, "high")]}
    assert len(set(mau.values())) == 3, f"ba mức không ba màu: {mau}"


def test_moc_kiem_gan_nhat_noi_ra_GIO_chu_khong_chi_noi_khoang_cach(
        realtime_server, browser_page):
    """`43h ago` trả lời "cũ bao nhiêu". Chỉ có giờ tuyệt đối mới tra được vào nhật ký job
    để biết lượt chạy nào đã ghi cái nhãn này."""
    _open_regime(browser_page, realtime_server, 0.4)
    card = browser_page.eval_on_selector(".rg2-card", "el => el.innerText")
    assert "last checked" in card, card[:200]
    assert re.search(r"\d\d-\d\d,\s*\d\d:\d\d\s*ET", card), (
        f"không có giờ theo đồng hồ trong khối nhãn: {card[:200]!r}")


def test_moc_kiem_dung_CUOI_khoi_nhan(realtime_server, browser_page):
    """Ba dòng trên nói về BẢN ĐỌC — nhãn gì, mô hình chắc tới đâu, phép kiểm có qua không.
    Dòng này nói về chính lượt đọc ấy đã chạy lúc nào, nên nó là xuất xứ và xuất xứ đứng
    cuối, đúng như dòng nguồn đứng cuối ở mọi section khác của trang.

    Ghim THỨ TỰ chứ không ghim sự có mặt: bản trước đặt nó xen giữa độ bất định và dòng
    kiểm nhãn, và một phép kiểm chỉ hỏi "có dòng đó không" thì xanh ở cả hai chỗ.
    """
    _open_regime(browser_page, realtime_server, 0.4)
    dong = [x.strip() for x in browser_page.eval_on_selector(
        ".rg2-anchor", "el => el.innerText").splitlines() if x.strip()]
    assert dong, "khối nhãn rỗng — phép đo hỏng"
    co = [x for x in dong if "last checked" in x]
    # ĐÚNG MỘT dòng. Một mutation chỉ THÊM bản thứ hai ở giữa khối vẫn để bản gốc nằm
    # cuối, nên một phép kiểm chỉ hỏi "dòng cuối có phải nó không" sẽ xanh trong khi câu
    # ấy đang hiện hai lần.
    assert len(co) == 1, f"mốc kiểm hiện {len(co)} lần: {dong}"
    assert "last checked" in dong[-1], f"mốc kiểm không ở đáy khối: {dong}"


def test_tuoi_ban_doc_van_chi_duoc_noi_MOT_lan(realtime_server, browser_page):
    """Luật 5ZZY: ngày nhãn và tuổi bản đọc nói một lần. Bản này CHUYỂN tuổi bản đọc vào
    khối nhãn — chuyển thì dòng nguồn phải thôi nói, nếu không là dựng lại đúng cặp câu
    trùng nhau cách 176px mà luật ấy đã gỡ."""
    _open_regime(browser_page, realtime_server, 0.4)
    src = browser_page.eval_on_selector(".regime-section .source-note",
                                        "el => el.textContent")
    assert "daily label" in src, f"dòng nguồn mất luôn xuất xứ: {src!r}"
    assert "checked" not in src.lower(), f"tuổi bản đọc nói hai lần; dòng nguồn: {src!r}"


# ══════════════════════════════════════════════════════════════════════════════════════
# 4 · Ô đọc của biểu đồ nằm trên hàng PRICE
# ══════════════════════════════════════════════════════════════════════════════════════

def test_o_doc_cua_bieu_do_nam_TREN_hang_dau_the_chu_khong_chen_giua(
        realtime_server, browser_page):
    """Một dải riêng nằm giữa hàng Data health và biểu đồ cắt ngang hai thứ nó không nói
    về, và khi chưa ai rê chuột thì nó là một khung rỗng chiếm nguyên một hàng chỉ để in
    một câu hướng dẫn. Cùng chỗ với ô đọc của lưới lane ở tab bên cạnh."""
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    _open_price_tab(browser_page, realtime_server, mv,
                    [{"day": "2026-08-27", "has_diagnostics": True}])
    browser_page.wait_for_selector(".mv2-chart-readout", timeout=20_000)
    got = browser_page.eval_on_selector(".mv2-chart-readout", """el => ({
        trongHead: !!el.closest('.mv2-card-head'),
        cuoiHang: el.parentElement.lastElementChild === el,
        vien: parseFloat(getComputedStyle(el).borderTopWidth),
        canh: getComputedStyle(el).textAlign})""")
    assert got["trongHead"], "ô đọc vẫn không nằm trong hàng đầu thẻ"
    assert got["cuoiHang"], "ô đọc không ở cuối hàng — nó phải là nửa phải của hàng đầu"
    assert got["vien"] == 0, f"còn khung riêng khi đã nằm trong hàng đầu: {got['vien']}px"
    assert got["canh"] == "right", got["canh"]


def test_hang_dau_the_khong_cao_them_khi_o_doc_day_so(realtime_server, browser_page):
    """Chuỗi O/H/L/C khi rê chuột dài hơn hẳn câu hướng dẫn, và nó nằm chung hàng với chữ
    "Price". Điều phải giữ là hàng ấy KHÔNG xuống dòng.

    Bản đầu của phép kiểm này đòi một `max-width` — và mutation cho thấy gỡ `max-width` đi
    thì nó vẫn xanh, tức nó không đo cái nó nói. Cơ chế thật là `white-space: nowrap` cộng
    `text-overflow: ellipsis`: chuỗi dài THU LẠI và cắt bằng ba chấm chứ không đẩy ai.
    Nên đo đúng cơ chế ấy: chiều cao hàng trước và trong khi rê chuột, và luật không-xuống-
    dòng có còn hiệu lực không.
    """
    mv = _with_slot_series(_market_view(), series_day="2026-08-27")
    _open_price_tab(browser_page, realtime_server, mv,
                    [{"day": "2026-08-27", "has_diagnostics": True}])
    browser_page.wait_for_selector(".mv-mark", timeout=20_000)
    truoc = browser_page.eval_on_selector(
        ".mv2-card-head", "el => Math.round(el.getBoundingClientRect().height)")
    browser_page.hover(".mv-mark >> nth=5")
    browser_page.wait_for_timeout(400)
    got = browser_page.evaluate("""() => {
        const r = document.querySelector('.mv2-chart-readout');
        const k = document.querySelector('.mv2-card-head .mv2-kicker');
        const h = document.querySelector('.mv2-card-head');
        return {doc: r.textContent,
                cao: Math.round(h.getBoundingClientRect().height),
                wrap: getComputedStyle(r).whiteSpace,
                rTop: Math.round(r.getBoundingClientRect().top),
                kTop: Math.round(k.getBoundingClientRect().top),
                rLeft: Math.round(r.getBoundingClientRect().left),
                kRight: Math.round(k.getBoundingClientRect().right),
                hRight: Math.round(h.getBoundingClientRect().right),
                rRight: Math.round(r.getBoundingClientRect().right)};}""")
    # Chốt chặn: phải THẬT SỰ đang ở trạng thái đọc số, nếu không phép kiểm chỉ đo câu
    # hướng dẫn ngắn và sẽ xanh ở mọi bề ngang.
    assert "O " in got["doc"], f"chưa đọc được số nến: {got['doc']!r}"
    assert len(got["doc"]) > 40, f"chuỗi quá ngắn để kiểm được điều này: {got['doc']!r}"
    assert got["cao"] == truoc, (
        f"hàng đầu cao thêm khi ô đọc đầy số: {truoc} -> {got['cao']}")
    assert got["wrap"] == "nowrap", f"ô đọc được phép xuống dòng: {got['wrap']}"
    assert abs(got["rTop"] - got["kTop"]) <= 6, f"hai nửa không cùng một hàng: {got}"
    assert got["rLeft"] > got["kRight"], f"ô đọc đè lên chữ Price: {got}"
    assert got["rRight"] <= got["hRight"] + 1, f"ô đọc tràn khỏi hàng đầu: {got}"
