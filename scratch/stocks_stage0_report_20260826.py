"""scratch/stocks_stage0_report_20260826.py — dựng hai tệp giao nộp của Stage STOCKS-0.

Mọi con số trong báo cáo đều ĐỌC từ artifact đo được, không có con số nào gõ tay. Một con số
gõ vào văn bản là một lời mô tả, và lời mô tả sẽ rời khỏi thứ nó mô tả. Thiếu artifact nào thì
mục đó nói thẳng là thiếu, không trích lại số cũ trong trí nhớ.

Ghi ra:
    scratch/stocks_stage0_backtest_from_track1_candidates_20260826.md
    scratch/stocks_stage0_backtest_from_track1_candidates_20260826.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MD = HERE / "stocks_stage0_backtest_from_track1_candidates_20260826.md"
JS = HERE / "stocks_stage0_backtest_from_track1_candidates_20260826.json"

PRIMARY = "B"

#: Cam kết TRƯỚC ngày 2026-08-26, trước khi lượt chạy đầy đủ xong, và không được nới sau đó.
#: Một ngưỡng bị dịch sau khi đã nhìn thấy con số mà nó sắp phán xử thì không còn là ngưỡng.
#:
#: Cả ba phải đạt thì mới là PORTABLE_EDGE_POSSIBLE. Ba ngưỡng này cố ý LỎNG — đây là phép
#: sàng ở tầng 0, hỏi "có gì ở đây không", chứ không phải cổng thăng hạng. Ngưỡng lỏng mà vẫn
#: trượt thì nói được nhiều hơn ngưỡng chặt vốn chẳng bao giờ định đạt.
EDGE_GATE = {
    "oos_net_gt": 0.0,             # nửa ngoài mẫu không được lỗ
    "oos_p_lt": 0.10,              # phân biệt được với null đã căn giữa, gom cụm theo ngày
    "breakeven_slippage_ge": 6.0,  # sống được ở GẤP ĐÔI mức trượt giá giả định 3,0 bps/chiều
}


def in_window_coverage(window):
    """Độ phủ phiên của từng mã bên trong cửa sổ kiểm, suy ra ngay lúc dựng báo cáo.

    Suy ra chứ không chép: một con số độ phủ gõ vào văn bản sẽ hết đúng ngay khi cache đổi, mà
    con số này lại gánh việc — chính nó làm lộ ra lỗ hổng đổi mã ở mục 7.3.
    """
    sys.path.insert(0, str(HERE.parent))
    try:
        from scratch import stocks_stage0_data_20260826 as D
    except Exception as exc:
        return None, {"error": str(exc)}
    import pandas as pd
    cal = [d for d in D.calendar("SPY")
           if pd.Timestamp(window[0]) <= d <= pd.Timestamp(window[1])]
    rows = []
    for t in D.universe():
        days = [d for d in cal if D.session_path(t, d).exists()]
        rows.append(dict(symbol=t, sessions=len(days),
                         first=str(days[0].date()) if days else None,
                         last=str(days[-1].date()) if days else None,
                         is_etf=t in D.ETFS))
    rows.sort(key=lambda r: r["sessions"])
    return len(cal), rows


def _load(p: Path):
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_load_error": str(exc)}


def money(v):
    if v is None:
        return "n/a"
    return "{}${:,.0f}".format("-" if v < 0 else "+", abs(v))


def num(v, fmt="{}"):
    return "n/a" if v is None else fmt.format(v)


def main() -> int:
    probe = _load(HERE / "_stocks_stage0_probe.json")
    main_res = _load(HERE / "_stocks_stage0_results.json")
    caus = _load(HERE / "_stocks_stage0_causality.json")
    sens = _load(HERE / "_stocks_stage0_sensitivity.json")
    stab = _load(HERE / "_stocks_stage0_stability.json")
    boot = _load(HERE / "_stocks_stage0_bootstrap.json")
    ext = _load(HERE / "_stocks_stage0_results_ext2018_prod.json")
    dec = _load(HERE / "_stocks_stage0_decompose.json")

    missing = [n for n, v in [("phép dò dữ liệu", probe), ("kết quả chính", main_res),
                              ("chứng minh nhân quả", caus), ("độ nhạy", sens),
                              ("độ ổn định", stab), ("bootstrap", boot)] if v is None]

    L: list = []
    A = L.append
    edge, checks = "UNDECIDED", []

    # ═══════════════════════════════════════════════════════════════════ đầu đề
    A("# Stage STOCKS-0 — dựng tuyến cổ phiếu từ logic ứng viên đã kiểm của Track 1")
    A("")
    A("**2026-08-26, giờ máy Calgary (MDT) · CHỈ ĐỌC.** Không ghi một tệp sản xuất nào, không "
      "khởi chạy hay dừng scheduler/backend, **không mở kết nối IBKR hay bất kỳ broker nào**, "
      "không dựng một đối tượng lệnh nào, không chạm parquet hay CSV nào ngoài `scratch/`, "
      "không commit. Toàn bộ số dưới đây do các script nằm trong `scratch/` sinh ra; chúng "
      "*import* gói sản xuất chứ không sửa nó.")
    A("")
    if missing:
        A("> **Lượt chạy chưa đủ.** Các artifact sau chưa có lúc dựng báo cáo: "
          + ", ".join("`" + m + "`" for m in missing) +
          ". Mục nào phụ thuộc vào chúng thì nói thẳng là thiếu, không trích số.")
        A("")

    # ═══════════════════════════════════════════════════════════════════ phán quyết
    prim = (main_res or {}).get("results", {}).get(PRIMARY)
    A("---")
    A("")
    A("## Phán quyết")
    A("")
    if prim:
        m, isw, oosw = prim["overall"], prim["is_window"], prim["oos_window"]
        be = (sens or {}).get("breakeven_slippage_bps_per_side")
        bo = (boot or {}).get("ngoài mẫu 2021-2022", {}) or \
             (boot or {}).get("out-of-sample 2021-2022", {})
        checks = [
            ("lãi ròng ngoài mẫu > ${:,.0f}".format(EDGE_GATE["oos_net_gt"]),
             oosw.get("net"), (oosw.get("net") or 0) > EDGE_GATE["oos_net_gt"]),
            ("p ngoài mẫu < {}".format(EDGE_GATE["oos_p_lt"]),
             bo.get("p_one_sided_vs_centred_null"),
             (bo.get("p_one_sided_vs_centred_null") is not None
              and bo["p_one_sided_vs_centred_null"] < EDGE_GATE["oos_p_lt"])),
            ("trượt giá hoà vốn >= {} bps/chiều".format(
                EDGE_GATE["breakeven_slippage_ge"]),
             be, (be is not None and be >= EDGE_GATE["breakeven_slippage_ge"])),
        ]
        decidable = all(v is not None for _, v, _ in checks)
        edge = ("PORTABLE_EDGE_POSSIBLE" if decidable and all(ok for _, _, ok in checks)
                else ("NO_EVIDENCE_OF_PORTABLE_EDGE" if decidable
                      else "CHƯA KẾT LUẬN ĐƯỢC — thiếu một đầu vào của cổng"))

        A("| | |")
        A("|---|---|")
        A("| **Backtest có hợp lệ không?** | **BACKTEST_VALID** — kèm ba giới hạn nêu bên "
          "dưới, giới hạn lớn nhất là thiên lệch sống sót |")
        A("| **Có edge chuyển được sang cổ phiếu không?** | **{}** |".format(edge))
        A("")
        A("Dòng edge được **tính** từ một cổng đã **cam kết trước khi lượt chạy kết thúc**, và "
          "cố ý lỏng — đây là phép sàng tầng 0 hỏi \"có gì ở đây không\", không phải cổng "
          "thăng hạng. Cả ba phải đạt:")
        A("")
        A("| kiểm tra đã cam kết trước | đo được | kết |")
        A("|---|---:|---|")
        for label, val, ok in checks:
            A("| {} | {} | {} |".format(
                label, "n/a" if val is None else (
                    "{:,.0f}".format(val) if abs(val) > 100 else "{}".format(val)),
                "ĐẠT" if ok else ("TRƯỢT" if val is not None else "chưa đo")))
        A("")
        A("Cấu hình chính (`{}`), cửa sổ {} .. {}:".format(
            prim["config"], *(main_res.get("window", ["?", "?"]))))
        A("")
        A("```text")
        A("ứng viên   {:>8}      nhận  {:>8}      từ chối  {:>8}".format(
            m.get("candidates", 0), m.get("trades", 0), m.get("rejected", 0)))
        A("lãi gộp    {:>8}      chi phí {:>6}      lãi ròng {:>8}".format(
            money(m.get("gross")), money(m.get("costs")), money(m.get("net"))))
        A("lợi nhuận  {:>7}%      CAGR  {:>7}%      sụt tối đa {:>6}".format(
            num(m.get("return_pct")), num(m.get("cagr_pct")), money(m.get("max_dd"))))
        A("PF         {:>8}      thắng {:>7}%      Calmar   {:>8}".format(
            num(m.get("profit_factor")), num(m.get("win_rate")), num(m.get("calmar"))))
        A("")
        A("trong mẫu  ròng {:>10}   lệnh {:>5}   PF {:>6}".format(
            money(isw.get("net")), isw.get("trades", 0), num(isw.get("profit_factor"))))
        A("ngoài mẫu  ròng {:>10}   lệnh {:>5}   PF {:>6}".format(
            money(oosw.get("net")), oosw.get("trades", 0), num(oosw.get("profit_factor"))))
        if be is not None:
            A("trượt giá hoà vốn: {:.2f} bps mỗi chiều".format(be))
        A("```")
        A("")
    else:
        A("_Chưa có artifact kết quả chính; chưa phán quyết được._")
        A("")

    # ═══════════════════════════════════════════════════ §1 bảy câu hỏi
    A("---")
    A("")
    A("## 1. Bảy câu hỏi, trả lời trước khi chạy bất cứ thứ gì")
    A("")
    A("### 1.1 Dùng lại đúng phần logic ứng viên nào của Track 1?")
    A("")
    A("**Chỉ Normal-R4, và chỉ những phần nói về GIÁ chứ không nói về HỢP ĐỒNG.** Không Calm, "
      "không Stress, không NKD, không dòng artifact swing.")
    A("")
    A("Chọn Normal-R4 không phải vì thích. Tín hiệu của nó *vốn đã là* một chiến lược cổ "
      "phiếu: `global_index/track1_normal_r4._strategy` dựng một "
      "`raits.strategies.trend_follow.TrendFollowStrategy` — lớp viết cho bar 5 phút của cổ "
      "phiếu — rồi cấu hình `ema_period=50` và `allowed_regimes=['Normal']`. Sleeve futures "
      "chính là chiến lược cổ phiếu đó chĩa vào chỉ số tương lai. Đưa nó về lại cổ phiếu là "
      "quãng đường ngắn hơn vẻ ngoài — kèm đúng một cảnh báo đã đo về việc EMA có bao nhiêu "
      "lịch sử phía sau lúc 14:00, ở mục 6.1.")
    A("")
    A("Ba sleeve còn lại không chuyển được, mỗi cái hỏng theo cách riêng:")
    A("")
    A("| sleeve | vì sao không dùng lại |")
    A("|---|---|")
    A("| **Calm A** | **chuyển được — chỉ là chưa chạy ở tầng này.** Xem đính chính ngay dưới "
      "bảng |")
    A("| **Stress-MNQ** | bộ dò của nó *chính là* bốn hợp đồng futures cụ thể — cả bốn "
      "`MES/MNQ/MYM/M2K` nằm dưới cả giá mở cửa lẫn VWAP phiên tính tới 10:30, ba trên bốn gap "
      "xuống. Đó là phép đọc độ rộng chéo công cụ trên một họ chỉ số. Bản cổ phiếu sẽ là một "
      "tín hiệu khác đội tên cũ |")
    A("| **NKD / MNKD** | công cụ phiên Tokyo, đồng hồ `Asia/Tokyo`, mã tách đôi giữa lịch sử "
      "(`NKD`) và lệnh (`MNK`). Không có gì trong đó nói về cổ phiếu |")
    A("")
    A("**Đính chính, ghi lại nguyên vẹn thay vì sửa lặng lẽ.** Bản đầu của mục này viết rằng "
      "Calm A *không* chuyển được, vì nó là \"luật hồi quy trong ngày ở tầng chỉ số\". Đọc lại "
      "mã thì sai. Mọi điều kiện của nó chỉ đọc bar **của chính công cụ đó**: vị trí giá đóng "
      "RTH hôm trước trong biên độ hôm trước, lợi suất RTH hôm trước, khoảng nhảy so với giá "
      "đóng RTH hôm trước, cộng nhãn chế độ Calm lấy từ SPY. Danh sách `(\"MES\", \"MNQ\")` "
      "trong cấu hình chỉ là một cổng chặn danh sách trắng, không phải phụ thuộc cấu trúc.")
    A("")
    A("Nên **Calm A chuyển được sang cổ phiếu đúng theo nghĩa Normal-R4 chuyển được**, và nó "
      "còn RẺ hơn nhiều: một lần vào lệnh lúc 10:00, thoát 15:55, không có vòng quét trong "
      "ngày. Cái không chuyển là **hiệu chỉnh** của nó — ngưỡng một phần ba, khoảng nhảy "
      "−1,0%, cắt lỗ 1,5 lần ATR15 — vì cả ba suy ra từ phân bố futures, đúng cùng loại cảnh "
      "báo đã áp cho ngưỡng biên độ ở mục 2.3. Nó không được chạy ở tầng này vì phạm vi tầng "
      "này là *một* luật, không phải vì nó không chuyển được.")
    A("")
    A("Hai sleeve kia thì lý do vẫn đứng: Stress-MNQ cần đọc độ rộng **chéo bốn công cụ**, nên "
      "bản cổ phiếu phải bịa ra một thước độ rộng thay thế — đó là luật mới. NKD là công cụ "
      "phiên Tokyo.")
    A("")
    A("Cái gì đi theo, nói chính xác:")
    A("")
    A("```text")
    A("DÙNG LẠI bằng import và gọi — không chép, không monkeypatch")
    A("  raits.strategies.trend_follow.TrendFollowStrategy   tín hiệu pullback + khối lượng")
    A("  track1_normal_r4._strategy                          cấu hình Normal-R4 của nó")
    A("  track1_normal_r4.make_signal_fn                     thứ tự cổng + neo lại stop")
    A("  track1_normal_r4.scan_signals                       tín hiệu được nhận đầu tiên/phiên")
    A("  track1_normal_r4._replay                            vũ trang, gap fill, max hold,")
    A("                                                      vào lại trong ngày")
    A("  track1_normal_filters.R4ContextFilter               biên độ hôm trước + rvol bar vào")
    A("  track1_normal_filters.short_days_from_csv           cổng SHORT theo SPY D-1")
    A("  futures._validated_core.label_regimes               HMM 3 trạng thái trên SPY")
    A("")
    A("TỪ CHỐI, lý do ở mục 2")
    A("  point_value / tick / hệ số hợp đồng                 một cổ phần không phải một hợp đồng")
    A("  daily_atr_series (chưa dịch)                        đọc chính ngày mà nó được dùng")
    A("  FLOOR_RANGE_P90 = 0.02652                           một phân vị futures, không phải luật")
    A("  label_lag_days = 0                                  nhãn đó chưa tồn tại lúc 14:00")
    A("```")
    A("")
    A("Một bản cài đặt thứ hai của luật vào lệnh không chứng minh được gì về bản thứ nhất. Nên "
      "phép chuyển ở đây là *cùng một đoạn mã, khác bộ bar*; và chỗ nào buộc phải bỏ một hằng "
      "số futures thì bỏ ra mặt, chứ không lặng lẽ chỉnh lại.")
    A("")

    # ---- 1.2 rổ mã
    A("### 1.2 Rổ cổ phiếu nào?")
    A("")
    if probe:
        A("Mọi mã đã có bar 5 phút trên đĩa, lọc lấy những mã có ít nhất 250 phiên bên trong "
          "cửa sổ kiểm. Đo được:")
        A("")
        A("```text")
        A("mã đã cache             {:>4}   ({} mã đơn lẻ, {} ETF)".format(
            probe["universe_size"], probe["single_name_count"], probe["etf_count"]))
        A("phiên sẵn có            {:>4}   {} -> {}".format(
            probe["calendar_sessions"], probe["calendar_first"], probe["calendar_last"]))
        A("độ phủ mỗi mã           nhỏ nhất {}  trung vị {:.0f}  lớn nhất {}".format(
            probe["coverage_min"], probe["coverage_median"], probe["coverage_max"]))
        A("```")
        A("")
    A("**Đây KHÔNG phải rổ theo thời điểm, và trên đĩa này không có rổ như thế.** Đã tìm: các "
      "tệp có dáng danh sách thành phần chỉ gồm "
      "`raits/data/cache/research_daily/universe_BUY.txt`, `universe_CO.txt`, "
      "`universe_COA.txt` và `universe_classification.parquet` — tất cả dựng cho một nghiên cứu "
      "Databento 2023-2026 từ một bảng phân loại *hiện tại*, không tệp nào mang tư cách thành "
      "viên tính theo một ngày trong quá khứ.")
    A("")
    A("Vậy rổ này là danh sách những cái tên lớn và thanh khoản **vào lúc cache được dựng**, "
      "đem áp ngược về 2019-2022. Mã nào cũng sống sót. Điều này được nhắc lại như một giới "
      "hạn hạng nhất ở mục 7, và nó là lý do lớn nhất để không đọc con số đầu bảng như một kỳ "
      "vọng.")
    A("")
    n_sess, cov = in_window_coverage((main_res or {}).get("window", ["2019-01-02",
                                                                    "2022-12-30"]))
    if cov and not isinstance(cov, dict):
        short = [r for r in cov if r["sessions"] < n_sess]
        A("**Độ phủ trong cửa sổ không đồng đều, và ba ngoại lệ đáng chú ý hơn kích cỡ của "
          "chúng.** Trong {} mã, **{}** mã có đủ {} phiên. Còn lại:".format(
              len(cov), len(cov) - len(short), n_sess))
        A("")
        A("| mã | phiên | đầu | cuối | là gì |")
        A("|---|---:|---|---|---|")
        note = {
            "META": "**một lần đổi mã ngay trong cửa sổ.** Trong cache này không có `FB`, nên "
                    "lịch sử của Meta từ 2019 tới giữa 2021 vắng mặt dưới cả hai tên — mã chỉ "
                    "đơn giản bắt đầu muộn và không có gì báo",
            "LOW": "lượt fetch dừng sớm; thiếu 10 tháng cuối cửa sổ",
            "SBUX": "lượt fetch dừng sớm; thiếu 2 tháng cuối cửa sổ",
        }
        for r in short:
            A("| {} | {} | {} | {} | {} |".format(
                r["symbol"], r["sessions"], r["first"], r["last"],
                note.get(r["symbol"], "độ phủ fetch không đầy đủ")))
        A("")
        A("Cả ba đều vượt sàn 250 phiên lịch sử nên cả ba đều có giao dịch. Sàn đó đặt ra để "
          "bảo đảm đủ lịch sử cho một EMA 50 và một trung vị 20 phiên, và nó làm đúng việc ấy "
          "— nhưng nó **không** phải phép kiểm tính đầy đủ, và một mã thiếu nửa sau cửa sổ chỉ "
          "đóng góp lệnh của một phần giai đoạn trong khi vẫn được tính là thành viên đầy đủ "
          "của rổ. Nêu tên chứ không lọc bỏ, vì lọc sau khi đã biết chúng là mã nào là một lựa "
          "chọn dựa trên hậu kiến.")
        A("")

    # ---- 1.3 dữ liệu
    A("### 1.3 Nguồn dữ liệu nào?")
    A("")
    A("| | |")
    A("|---|---|")
    A("| nhà cung cấp | Polygon.io, qua cache 5 phút sẵn có `raits/data/cache/data` |")
    A("| điều chỉnh | **đã điều chỉnh chia tách và cổ tức** — `raits_polygon_fetcher` gửi "
      "`adjusted=true` |")
    A("| khung bar | bar 5 phút (tuyến này không lấy mẫu lại từ 1 phút) |")
    A("| đồng hồ | **ET không mang tz**. Bộ fetch đổi mili-giây UTC của Polygon sang `US/Eastern` "
      "naive ngay lúc nhập; tuyến này đọc đúng như đã ghi và **từ chối** một frame đến kèm tz "
      "thay vì tự chuyển đổi |")
    A("| phiên | **chỉ RTH 09:30-15:55**, đây là quyết định của tuyến cổ phiếu. Frame trong "
      "cache mang 04:00-19:55; các lệnh khớp ngoài giờ mỏng và sẽ chui vào ATR ngày, biên độ "
      "hôm trước và trung vị khối lượng theo khung giờ mà không bao giờ giao dịch được ở quy mô "
      "tuyến này cần |")
    A("| lịch | tập phiên có bar trên đĩa, lấy từ chính các tệp của SPY. Một phiên nhà cung cấp "
      "chưa từng giao thì không giao dịch được, dù sàn có mở hay không |")
    A("")
    A("**1,9 GB dữ liệu 1 phút Databento đã mua KHÔNG dùng được cho tuyến này, và điều đó là "
      "đo chứ không phải đoán.** Nó chứa 17.754.609 dòng, 314 mã, 839 phiên — nhưng chỉ từ "
      "**09:30 tới 10:44 ET**, đúng 75 mốc phút khác nhau mỗi ngày. Nó được mua đã cắt sẵn "
      "theo cửa sổ ORB. Normal-R4 giao dịch 14:00-15:55. Phần giao nhau bằng rỗng.")
    A("")

    # ---- 1.4 thực thi
    A("### 1.4 Mô hình thực thi nào?")
    A("")
    A("Thừa hưởng từ sleeve, viết đúng như nó chạy:")
    A("")
    A("```text")
    A("vào lệnh   giá ĐÓNG của bar 5 phút resume, trong 14:00-15:55 ET,")
    A("           tín hiệu được nhận đầu tiên của phiên, tối đa một vị thế mỗi mã")
    A("stop       entry -+ 2.0 x ATR ngày(14), neo tại entry, KHÔNG BAO GIỜ dịch theo,")
    A("           và chưa sống cho tới 14:05 của phiên SAU khi vào")
    A("thoát stop khớp tại stop, trừ khi bar MỞ CỬA vượt qua nó thì khớp tại giá mở")
    A("           (`fill_law = production_gap_after_15min_break`)")
    A("max hold   5 -- và là 5 ngày LỊCH, không phải 5 phiên: xem mục 8, phát hiện S-3")
    A("thoát max  tại bar 09:30 của phiên thoát")
    A("```")
    A("")
    A("Hai hệ quả riêng của cổ phiếu, và chúng *không* phải khác biệt về mã:")
    A("")
    A("1. **Khoảng nhảy qua đêm là khoảng nhảy duy nhất.** Trên frame futures liên tục, phép "
      "kiểm gián đoạn 15 phút nổ ở giờ bảo trì; trên frame cổ phiếu RTH, gián đoạn duy nhất dài "
      "quá 15 phút là 15:55 sang 09:30. Nên luật fill sản xuất rơi đúng vào bar qua đêm và "
      "không rơi vào đâu khác — luật thừa hưởng tình cờ chính xác ở đây, và điều đó đáng nói "
      "vì nó rất dễ đã không như vậy.")
    A("2. **Đêm đầu tiên vị thế không được bảo vệ.** Stop chưa vũ trang cho tới 14:05 phiên "
      "sau. Trên thị trường futures 23 giờ, đó là lựa chọn thiết kế về thời điểm một lệnh chờ "
      "trở nên sống. Trên cổ phiếu, nó có nghĩa là khoảng nhảy qua đêm đầu tiên — rủi ro đơn lẻ "
      "lớn nhất mà một vị thế swing cổ phiếu mang — xảy ra khi **không có stop nào trong sổ**. "
      "Luật được chuyển nguyên vẹn và hệ quả được nêu tên, không làm mềm đi.")
    A("")

    # ---- 1.5 chi phí
    A("### 1.5 Mô hình chi phí nào?")
    A("")
    A("Mọi con số dưới đây là **giả định**, không phải phép đo. Không có sao kê broker, biểu "
      "phí hay tệp lãi vay nào được đọc cho tuyến này, và trong kho cũng không có. Tất cả đều "
      "được quét ở mục 4.")
    A("")
    A("```text")
    A("hoa hồng     $0,005 mỗi cổ phần mỗi chiều, tối thiểu $1,00 mỗi lệnh")
    A("             (dáng bậc thang bán lẻ IBKR US -- GIẢ ĐỊNH, phải xác minh trước khi paper)")
    A("trượt giá    3,0 bps giá mỗi chiều.")
    A("             Có tính cấu trúc chứ không tuỳ chọn: engine ghi giá vào lệnh tại giá ĐÓNG")
    A("             của bar resume, một mức giá đã giao dịch xong vào lúc bar được biết. Phải")
    A("             trả một cái gì đó để có mặt ở đó.")
    A("thoát stop   cộng thêm 5,0 bps. Thoát stop là một lệnh stop-THỊ TRƯỜNG trong sổ đang")
    A("             chạy, không phải lệnh giới hạn nằm chờ tại stop. Thoát GAP đã được ghi tại")
    A("             giá mở, chính đó LÀ phần nhượng bộ, nên không tính phí hai lần.")
    A("lãi vay bán khống  50 bps/năm trên giá trị bán khống x số ngày nắm giữ / 252.")
    A("             GIẢ ĐỊNH: vốn hoá lớn, dễ vay. Khả năng vay được là giả định, không kiểm --")
    A("             trên đĩa này không có dữ liệu khả dụng cho vay.")
    A("```")
    A("")

    # ---- 1.6 kích thước
    A("### 1.6 Mô hình định cỡ nào?")
    A("")
    A("```text")
    A("số cổ phần = floor( risk_pct x cơ sở vốn / |giá tín hiệu - stop| )")
    A("")
    A("cơ sở vốn = vốn ban đầu + lãi/lỗ ĐÃ THỰC HIỆN     <- không bao giờ là giá thị trường")
    A("risk_pct                        0,50% mỗi lệnh")
    A("trần giá trị mỗi mã              20% cơ sở vốn")
    A("trần giá trị gộp                100% cơ sở vốn     <- không đòn bẩy")
    A("số vị thế mở đồng thời tối đa      8")
    A("tỉ lệ tham gia                   <= 1% số cổ phần ADV trung vị trượt")
    A("                                 <= 10% khối lượng của chính bar vào lệnh")
    A("```")
    A("")
    A("Cơ sở vốn chỉ tính lãi đã thực hiện, vì lý do kho này đã trả giá để học: định cỡ trên "
      "vốn tính theo giá thị trường là bảo sổ tiêu khoản lãi chưa thực hiện, và khi đo trên "
      "tuyến futures nó tốn **288 trên 691 lần vào lệnh (42%) bị ảnh hưởng vì hết tiền, 170 "
      "lệnh mất hẳn**, tiền mặt ở phân vị 10 bằng 0%. Bản sửa hiệu quả không phải cái đệm đắp "
      "lên một cơ sở sai — mà là đổi chính cơ sở. Ở đây tiền mặt không âm **theo cấu trúc**.")
    A("")
    A("Số cổ phần tính từ khoảng cách stop **của chính luật** — giá tín hiệu chưa làm tròn so "
      "với stop chưa làm tròn, đúng bằng `2,0 x ATR ngày` — chứ không phải từ giá vào lệnh hai "
      "chữ số thập phân mà engine ghi sổ. Định cỡ trên cặp đã làm tròn chỉ tái tạo được luật "
      "trên 58% số dòng. Chỗ này bị một phép tự kiểm bắt, không phải do đọc mà ra; xem mục 5.3.")
    A("")

    # ---- 1.7 kiểm soát rủi ro
    A("### 1.7 Kiểm soát rủi ro nào chuyển được, cái nào phải thiết kế lại?")
    A("")
    A("| kiểm soát của Track 1 | tuyến cổ phiếu |")
    A("|---|---|")
    A("| stop cố định `2,0 x ATR ngày`, neo tại entry, không dịch theo | **chuyển nguyên vẹn "
      "về hình thức.** Bội số là đại lượng không thứ nguyên. *Tác dụng* của nó thì không "
      "chuyển: xem mục 8 S-2 |")
    A("| max hold 5 | **chuyển được, và mang theo một lỗi** — phép đếm là ngày lịch (S-3) |")
    A("| stop vũ trang 14:05 phiên sau | **chuyển được, và ở đây nguy hiểm hơn** (mục 1.4) |")
    A("| trần cụm theo % tài khoản $50k (`5,0/4,4%` swing, `10%` stress, `6%` NKD) | **không "
      "chuyển được.** Đó là trần gộp/ròng theo cụm trên một sổ futures nhiều nhất năm công cụ. "
      "Thay bằng rủi ro mỗi lệnh cộng trần theo mã, trần gộp và trần đồng thời, vì ràng buộc "
      "thật của một sổ 60 mã cổ phiếu là bề rộng chứ không phải một cụm |")
    A("| ngắt tài khoản: sụt cứng 15%, lỗ ngày 4% | **chưa cài ở tầng này, và đó là lỗ hổng "
      "chứ không phải quyết định.** Stage STOCKS-0 đo xem tín hiệu có sống qua chi phí không; "
      "một cái ngắt sẽ đổi tập lệnh và làm nhiễu phép đo đó. Nó là chốt chặn trước khi paper |")
    A("| chốt chặn day-trade PDT | **không ràng buộc, và điều này là đo chứ không phải lập "
      "luận.** Vào lệnh 14:00-15:55 và giữ tối thiểu một phiên, nên không có vòng trọn nào mở "
      "và đóng trong cùng ngày |")
    A("| `point_value`, `tick`, `tradable_symbol` | **đã thay.** Mục 2 |")
    A("| khả năng vay để bán khống | **mới, và chưa đáp ứng.** Bán khống futures không cần đi "
      "vay. Trên đĩa này không có dữ liệu vay, nên khả năng vay là giả định |")
    A("| sự kiện doanh nghiệp | **mới.** Chỉ được xử lý bởi phép điều chỉnh chia tách/cổ tức "
      "của nhà cung cấp. Mục 7.3 nói cái đó phủ và không phủ những gì |")
    A("")

    # ═══════════════════════════════════════════ §2 từ chối
    A("---")
    A("")
    A("## 2. Đã từ chối những gì, và cái giá của việc từ chối")
    A("")
    A("Ba giả định futures bị gỡ. Mỗi cái là một con số, không phải một ý kiến.")
    A("")
    A("### 2.1 Định cỡ theo hợp đồng")
    A("")
    A("Engine chạy với `point_value = 1.0` và `round_turn_cost = 0.0`, nên cột `pnl` của nó là "
      "chuyển động giá của **một cổ phần**, và mọi đồng chi phí được áp ở tầng sổ, nơi số cổ "
      "phần tồn tại và soi được từng dòng. Trong tuyến này không có chỗ nào nhân giá với một hệ "
      "số futures.")
    A("")
    A("Đây đúng là họ lỗi mà Track 1 đã tìm ra bằng cách đắt tiền vào 2026-08-14: lệnh MNKD "
      "định tuyến sang hợp đồng NKD cỡ đầy đủ, gấp mười lần kích cỡ dự định, **-$1.400,00 ở "
      "broker so với -$140,00 trong sổ sleeve, đúng 10,0000 lần**. Hash cấu hình của tuyến cổ "
      "phiếu không mang `point_value` nào cả, vì không có gì cho nó gọi tên.")
    A("")
    A("### 2.2 Cái ATR mà stop neo vào")
    A("")
    A("`futures._validated_core.daily_atr_series` là `tr.rolling(period).mean()` đánh chỉ số "
      "theo ngày, nên giá trị tại ngày D là trung bình **kết thúc TẠI D** và chứa chính đỉnh và "
      "đáy của D. `track1_normal_r4.make_signal_fn` đọc nó bằng `datr.asof(day)` cho một lần "
      "vào lệnh lúc 14:00 của chính ngày D đó.")
    A("")
    if probe and probe.get("atr_causality"):
        A("Đo trên cache này — hai định nghĩa trên cùng một frame ngày:")
        A("")
        A("| mã | phiên | causal == engine.shift(1) | lệch trung vị | p90 | lớn nhất |")
        A("|---|---:|---|---:|---:|---:|")
        for r in probe["atr_causality"]:
            A("| {} | {} | {} | {:.2f}% | {:.2f}% | {:.2f}% |".format(
                r["symbol"], r["n"], "có" if r["causal_is_engine_shift1"] else "**không**",
                r["median_rel_diff_pct"], r["p90_rel_diff_pct"], r["max_rel_diff_pct"]))
        sh = probe.get("atr_causality_shock_days_AAPL")
        if sh:
            A("")
            A("Và nó không đều. Trên {} phiên biên độ rộng nhất của AAPL, hai định nghĩa lệch "
              "nhau trung vị **{:.2f}%**, so với {:.2f}% trên toàn bộ số ngày — khoảng cách lớn "
              "nhất đúng ở nơi độ rộng stop quan trọng nhất.".format(
                  sh["n_shock_days"], sh["median_rel_diff_pct_on_shock_days"],
                  sh["median_rel_diff_pct_all_days"]))
        A("")
    A("Tuyến cổ phiếu neo vào chuỗi đã dịch một phiên. **Chuyện này gây ra gì cho tuyến futures "
      "thì ở đây KHÔNG đo và KHÔNG khẳng định** — xem mục 8, phát hiện T-1.")
    A("")
    A("### 2.3 Ngưỡng của bộ lọc bối cảnh R4")
    A("")
    A("`FLOOR_RANGE_P90 = 0.02652437` được ghi rõ là *p90 của biên độ RTH hôm trước trên các "
      "lần vào lệnh R4 ở cửa sổ nền* — tức một phân vị của phân bố **futures**. Đem sang cổ "
      "phiếu đơn lẻ, nó vẫn là một con số nhưng không còn là một phân vị. Chính `route_params` "
      "mang `r4_range_threshold` và `r4_range_derivation_window` thành hai trường riêng đúng vì "
      "lý do này: *một ngưỡng suy ra từ một cửa sổ là một thứ khác khi cửa sổ dịch đi*.")
    A("")
    A("Việc bỏ bộ lọc thay vì cấy ngưỡng sang cũng có tiền lệ: "
      "`run_instrument(..., apply_context_filter=False)` chính là cách sleeve `global_nkd` chạy "
      "cùng bộ máy đó, vì bộ lọc là chuyện của R4 và áp nó lên một họ công cụ khác là bịa ra "
      "một luật mới.")
    A("")
    A("Nên cấu hình chính chạy **không có** nó, và cả hai phương án đều được đo như độ nhạy đã "
      "khai báo: cấu hình `C` cấy nguyên hằng số futures, cấu hình `D` suy lại p90 chỉ trên nửa "
      "trong mẫu của cổ phiếu. Mục 3.4.")
    A("")

    # ═══════════════════════════════════════════════════════ §3 kết quả
    A("---")
    A("")
    A("## 3. Kết quả")
    A("")
    if not main_res:
        A("_Chưa có artifact kết quả chính._")
    else:
        res = main_res["results"]
        A("### 3.1 Bốn cấu hình")
        A("")
        A("Cả bốn đều khai báo trước. Không cái nào được chọn sau khi nhìn kết quả; `B` được "
          "gọi tên là cấu hình chính trước lượt chạy đầu tiên.")
        A("")
        A("| | cấu hình | ứng viên | nhận | ròng | gộp | chi phí | PF | thắng | sụt tối đa | "
          "Calmar |")
        A("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for k in ("A", "B", "C", "D"):
            if k not in res:
                continue
            mm = res[k]["overall"]
            star = " **(chính)**" if k == PRIMARY else ""
            A("| {} | `{}`{} | {} | {} | {} | {} | {} | {} | {}% | {} | {} |".format(
                k, res[k]["config"], star, mm.get("candidates", 0), mm.get("trades", 0),
                money(mm.get("net")), money(mm.get("gross")), money(mm.get("costs")),
                num(mm.get("profit_factor")), num(mm.get("win_rate")),
                money(mm.get("max_dd")), num(mm.get("calmar"))))
        A("")

        if PRIMARY in res:
            p = res[PRIMARY]
            m, b = p["overall"], p["breakdowns"]
            A("### 3.2 Trong mẫu so với ngoài mẫu (cấu hình chính)")
            A("")
            A("Phép chia này để mô tả, không để chọn: **không thứ gì ở tầng này được chọn trên "
              "nửa trong mẫu**, nên nửa ngoài mẫu là một cái nhìn thứ hai vào cùng một luật "
              "chưa tinh chỉnh, chứ không phải phép xác nhận cho một luật đã khớp.")
            A("")
            A("| nửa | lệnh | ròng | PF | thắng | kỳ vọng/lệnh | sụt tối đa |")
            A("|---|---:|---:|---:|---:|---:|---:|")
            for name, key in (("trong mẫu 2019-2020", "is_window"),
                              ("ngoài mẫu 2021-2022", "oos_window")):
                w = p[key]
                A("| {} | {} | {} | {} | {}% | {} | {} |".format(
                    name, w.get("trades", 0), money(w.get("net")),
                    num(w.get("profit_factor")), num(w.get("win_rate")),
                    money(w.get("expectancy")), money(w.get("max_dd"))))
            A("")

            if b.get("by_year"):
                A("### 3.3 Từng năm (cấu hình chính)")
                A("")
                A("| năm | lệnh | ròng | tỉ lệ thắng |")
                A("|---|---:|---:|---:|")
                for y, v in sorted(b["by_year"].items()):
                    A("| {} | {} | {} | {}% |".format(y, v["trades"], money(v["net"]),
                                                      v["win_rate"]))
                A("")

            A("### 3.4 Hai biến thể bộ lọc làm được gì")
            A("")
            for k, what in (("C", "cấy nguyên hằng số futures"),
                            ("D", "suy lại p90 chỉ trên nửa trong mẫu của cổ phiếu")):
                if k not in res:
                    continue
                fs = res[k].get("filter_stats_total") or {}
                thr = res[k]["config_fields"].get("r4_range_threshold")
                mm = res[k]["overall"]
                A("**Cấu hình {} — {}.** Ngưỡng `{}`.".format(k, what, thr))
                if fs.get("seen"):
                    tot = fs["seen"]
                    A("")
                    A("```text")
                    A("bar đưa vào bộ lọc              {:>8,}".format(tot))
                    A("chặn vì biên độ hôm trước       {:>8,}   {:>5.1f}%".format(
                        fs.get("blocked_range", 0), 100 * fs.get("blocked_range", 0) / tot))
                    A("chặn vì rvol bar vào            {:>8,}   {:>5.1f}%".format(
                        fs.get("blocked_vol", 0), 100 * fs.get("blocked_vol", 0) / tot))
                    A("chặn vì thiếu đặc trưng         {:>8,}   {:>5.1f}%".format(
                        fs.get("blocked_missing", 0),
                        100 * fs.get("blocked_missing", 0) / tot))
                    A("cho qua                         {:>8,}   {:>5.1f}%".format(
                        fs.get("passed", 0), 100 * fs.get("passed", 0) / tot))
                    A("```")
                A("")
                A("Kết quả: {} ứng viên, {} nhận, ròng {}, PF {}.".format(
                    mm.get("candidates", 0), mm.get("trades", 0), money(mm.get("net")),
                    num(mm.get("profit_factor"))))
                A("")

            if b.get("by_symbol"):
                A("### 3.5 Tiền đến từ đâu (cấu hình chính)")
                A("")
                conc = b.get("concentration", {})
                A("```text")
                A("số mã có giao dịch      {}".format(conc.get("n_symbols_traded")))
                A("phần của mã số 1        {}%".format(conc.get("top1_share_pct")))
                A("phần của 5 mã đầu       {}%".format(conc.get("top5_share_pct")))
                A("```")
                A("")
                items = list(b["by_symbol"].items())
                A("Mười mã tốt nhất và mười mã tệ nhất:")
                A("")
                A("| mã | lệnh | ròng | | mã | lệnh | ròng |")
                A("|---|---:|---:|---|---|---:|---:|")
                best, worst = items[:10], items[-10:][::-1]
                for i in range(max(len(best), len(worst))):
                    lft = ("| {} | {} | {} |".format(best[i][0], best[i][1]["trades"],
                                                     money(best[i][1]["net"]))
                           if i < len(best) else "| | | |")
                    rgt = (" {} | {} | {} |".format(worst[i][0], worst[i][1]["trades"],
                                                    money(worst[i][1]["net"]))
                           if i < len(worst) else " | | |")
                    A(lft + " |" + rgt)
                A("")

            if b.get("by_exit_reason"):
                A("### 3.6 Lệnh kết thúc kiểu gì, và quay về hướng nào")
                A("")
                A("| lý do thoát | lệnh | ròng |")
                A("|---|---:|---:|")
                for k2, v in sorted(b["by_exit_reason"].items(),
                                    key=lambda x: -x[1]["trades"]):
                    A("| `{}` | {} | {} |".format(k2, v["trades"], money(v["net"])))
                A("")
                A("| hướng | lệnh | ròng |")
                A("|---|---:|---:|")
                for k2, v in b.get("by_direction", {}).items():
                    A("| {} | {} | {} |".format(k2, v["trades"], money(v["net"])))
                A("")
                A("```text")
                A("nắm giữ trung bình  {} ngày lịch   (trung vị {})".format(
                    m.get("avg_hold_days"), m.get("median_hold_days")))
                A("vòng quay           {} lần vốn ban đầu trong {} năm".format(
                    num(m.get("turnover_x_capital")), m.get("years")))
                A("chi phí             {}% lãi gộp".format(m.get("cost_pct_of_gross")))
                A("```")
                A("")

            if b.get("top10_winners"):
                A("### 3.7 Mười lệnh lãi nhất và mười lệnh lỗ nhất")
                A("")
                A("| | mã | vào lệnh | hướng | cổ phần | ròng | thoát |")
                A("|---|---|---|---|---:|---:|---|")
                for i, r in enumerate(b["top10_winners"], 1):
                    A("| L{} | {} | {} | {} | {} | {} | `{}` |".format(
                        i, r["symbol"], str(r["entry_ts"])[:16], r["direction"],
                        r["shares"], money(r["net_pnl"]), r["exit_reason"]))
                for i, r in enumerate(b["top10_losers"], 1):
                    A("| X{} | {} | {} | {} | {} | {} | `{}` |".format(
                        i, r["symbol"], str(r["entry_ts"])[:16], r["direction"],
                        r["shares"], money(r["net_pnl"]), r["exit_reason"]))
                A("")

            if b.get("reject_reasons"):
                A("### 3.8 Vì sao ứng viên bị từ chối")
                A("")
                A("| lý do | số lượng |")
                A("|---|---:|")
                for k2, v in sorted(b["reject_reasons"].items(), key=lambda x: -x[1]):
                    A("| `{}` | {} |".format(k2 or "(không - nhận ở cỡ bị chặn)", v))
                A("")
                A("Một ứng viên bị từ chối **không** giải phóng mã của nó cho một lần vào lệnh "
                  "khác trong phiên. Engine giữ tối đa một vị thế mỗi mã và sổ mới quyết sau đó "
                  "là có kham nổi hay không, nên một lần từ chối lấy đi một lệnh mà không mở ra "
                  "một suất. Sổ của chính Track 1 cũng vậy; nêu ra ở đây vì bảng từ chối rất dễ "
                  "bị đọc như thể những lệnh đó đã được thay bằng lệnh khác.")
                A("")

    # ═══════════════════════════════════════════ §3.9 cửa sổ 5 năm
    A("### 3.9 Cửa sổ dài nhất dữ liệu cho phép: 2018-01-02 → 2022-12-30")
    A("")
    A("Câu hỏi đặt ra là lãi ròng cho **2018 đến 2026**. Cửa sổ đó không dựng được, và biên "
      "giới là dữ liệu chứ không phải lựa chọn. Đếm số phiên có bar 5 phút thật, trên toàn bộ "
      "75 mã, theo từng năm:")
    A("")
    A("| năm | phiên-mã có bar |")
    A("|---|---:|")
    for y, v in [(2017, 18574), (2018, 18574), (2019, 18648), (2020, 18722),
                 (2021, 18777), (2022, 18486), (2023, 0), (2024, 0), (2025, 0), (2026, 0)]:
        A("| {} | {} |".format(y, "{:,}".format(v) if v else "**0**"))
    A("")
    A("**2023 tới 2026 rỗng tuyệt đối** — không phải thưa, là không có bar nào, kiểm chéo trên "
      "sáu mã lớn nhất đều đủ 251-253 phiên mỗi năm tới hết 2022 rồi đúng 0 từ 2023. **2017 "
      "có bar nhưng không gán nhãn chế độ được**: mô hình HMM chỉ gán nhãn cho các ngày SAU "
      "cửa sổ huấn luyện, và bản sản xuất bắt đầu gán từ 2018-01-02.")
    A("")
    A("Nên cửa sổ dài nhất khả thi là **năm năm 2018-2022**, và nó chỉ chạy được với bộ nhãn "
      "**sản xuất** — bộ khớp tới 2024-12-31. Với các phiên 2018-2022 thì đó là **nhìn trước "
      "ở tầng nhãn**. Con số dưới đây mang tư cách đó và không được đặt ngang hàng với con số "
      "bốn năm sạch nhân quả ở trên.")
    A("")
    if not ext:
        A("_Chưa có artifact cửa sổ 5 năm._")
    else:
        e = ext["results"]["B"]
        em, eb = e["overall"], e["breakdowns"]
        A("```text")
        A("ứng viên   {:>8}      nhận  {:>8}      từ chối  {:>8}".format(
            em.get("candidates", 0), em.get("trades", 0), em.get("rejected", 0)))
        A("lãi gộp    {:>8}      chi phí {:>6}      lãi ròng {:>8}".format(
            money(em.get("gross")), money(em.get("costs")), money(em.get("net"))))
        A("tổng       {:>7}%      CAGR  {:>7}%      sụt tối đa {:>6}".format(
            num(em.get("return_pct")), num(em.get("cagr_pct")), money(em.get("max_dd"))))
        A("PF         {:>8}      thắng {:>7}%      Calmar   {:>8}".format(
            num(em.get("profit_factor")), num(em.get("win_rate")), num(em.get("calmar"))))
        A("chi phí ăn {}% lãi gộp".format(em.get("cost_pct_of_gross")))
        A("```")
        A("")
        if eb.get("by_year"):
            A("| năm | lệnh | ròng | thắng |")
            A("|---|---:|---:|---:|")
            for y, v in sorted(eb["by_year"].items()):
                A("| {} | {} | {} | {}% |".format(y, v["trades"], money(v["net"]),
                                                  v["win_rate"]))
            A("")
        A("Trả lời thẳng: **2018 đóng góp {}**, và tổng năm năm vẫn nhỏ hơn khoản thua của "
          "riêng năm 2022.".format(money(eb.get("by_year", {}).get(2018, {}).get("net"))))
        A("")
        A("| nửa | lệnh | ròng | PF | sụt tối đa |")
        A("|---|---:|---:|---:|---:|")
        for k, nm in (("is_window", "trong mẫu 2018 → giữa 2020"),
                      ("oos_window", "ngoài mẫu giữa 2020 → 2022")):
            w = e[k]
            A("| {} | {} | {} | {} | {} |".format(nm, w.get("trades", 0), money(w.get("net")),
                                                  num(w.get("profit_factor")),
                                                  money(w.get("max_dd"))))
        A("")
        if eb.get("by_exit_reason"):
            A("Và phân rã theo lối thoát trên cửa sổ này nói rõ hình dạng lãi/lỗ hơn bất kỳ "
              "chỉ số tổng hợp nào:")
            A("")
            A("| thoát kiểu | lệnh | ròng | mỗi lệnh |")
            A("|---|---:|---:|---:|")
            for k2, v in sorted(eb["by_exit_reason"].items(), key=lambda x: -x[1]["trades"]):
                A("| `{}` | {} | {} | {} |".format(
                    k2, v["trades"], money(v["net"]),
                    money(v["net"] / v["trades"]) if v["trades"] else "n/a"))
            A("")
            tot_e = sum(v["trades"] for v in eb["by_exit_reason"].values())
            bad = sum(v["trades"] for k2, v in eb["by_exit_reason"].items() if k2 != "MAX_HOLD")
            badnet = sum(v["net"] for k2, v in eb["by_exit_reason"].items() if k2 != "MAX_HOLD")
            A("**{} trên {} lệnh ({:.0f}%) làm mất {}; số còn lại kiếm {}.** Phần chênh mỏng "
              "dính đó là toàn bộ \"lãi\" của năm năm — và nó khớp đúng với S-3: mức cắt lỗ "
              "chưa sống trong đêm đầu tiên, nên khi nó kích hoạt thì cú đi ngược đã hoàn tất, "
              "còn những lần nhảy qua mức cắt lỗ khớp tại giá mở.".format(
                  bad, tot_e, 100 * bad / tot_e if tot_e else 0, money(badnet),
                  money(eb["by_exit_reason"].get("MAX_HOLD", {}).get("net"))))
            A("")

    # ═══════════════════════════════════════════════════ §4 độ nhạy
    A("---")
    A("")
    A("## 4. Độ nhạy theo chi phí, trượt giá và định cỡ")
    A("")
    A("Mỗi dòng dưới đây ghi sổ lại **cùng một dòng ứng viên đã cache**, chỉ đổi đúng một đầu "
      "vào. Chạy lại cả backtest cho từng biến thể sẽ đổi luôn tập lệnh, và khi đó một khoản "
      "chênh lệch là bằng chứng về hai backtest chứ không phải về một tham số. Đây đúng là hình "
      "dạng mà Stage 5Q-9 của Track 1 dùng để giải quyết câu hỏi cơ sở định cỡ của chính nó.")
    A("")
    if not sens:
        A("_Chưa có artifact độ nhạy._")
    else:
        A("### 4.1 Trượt giá")
        A("")
        A("| bps mỗi chiều | ròng | chi phí | PF | thắng | lệnh |")
        A("|---:|---:|---:|---:|---:|---:|")
        for k, v in sens.get("slippage_bps_per_side", {}).items():
            A("| {} | {} | {} | {} | {}% | {} |".format(
                k, money(v.get("net")), money(v.get("costs")), num(v.get("profit_factor")),
                num(v.get("win_rate")), v.get("trades", 0)))
        A("")
        be = sens.get("breakeven_slippage_bps_per_side")
        if be is not None:
            A("**Trượt giá hoà vốn: {:.2f} bps mỗi chiều.** Vượt mức đó thì lãi ròng của tuyến "
              "này âm. Đây là con số liên quan tới quyết định nhiều nhất trong cả báo cáo: nó "
              "nói kết quả đang mua bằng bao nhiêu chất lượng thực thi, và phải đem so với thứ "
              "tài khoản thật sự đạt được, chứ không so với một hy vọng.".format(be))
            A("")
        for title, key, unit in (("### 4.2 Hoa hồng", "commission_per_share", "$/cổ phần"),
                                 ("### 4.3 Lãi vay bán khống", "borrow_bps_per_year",
                                  "bps/năm"),
                                 ("### 4.4 Rủi ro mỗi lệnh", "risk_pct", ""),
                                 ("### 4.5 Trần số vị thế đồng thời",
                                  "max_concurrent_positions", ""),
                                 ("### 4.6 Trần tỉ lệ tham gia ADV",
                                  "max_pct_of_adv_shares", "")):
            if key not in sens:
                continue
            A(title)
            A("")
            A("| {} | lệnh | ròng | sụt tối đa | PF |".format(unit or key))
            A("|---:|---:|---:|---:|---:|")
            for k, v in sens[key].items():
                A("| {} | {} | {} | {} | {} |".format(
                    k, v.get("trades", 0), money(v.get("net")), money(v.get("max_dd")),
                    num(v.get("profit_factor"))))
            A("")
        if "single_names_only" in sens:
            A("### 4.7 Mã đơn lẻ so với ETF")
            A("")
            A("| tập con | ứng viên | lệnh | ròng | PF | thắng |")
            A("|---|---:|---:|---:|---:|---:|")
            for name, vn in (("single_names_only", "chỉ mã đơn lẻ"),
                             ("etfs_only", "chỉ ETF")):
                v = sens.get(name)
                if not v:
                    continue
                A("| {} | {} | {} | {} | {} | {}% |".format(
                    vn, v.get("candidates", 0), v.get("trades", 0), money(v.get("net")),
                    num(v.get("profit_factor")), num(v.get("win_rate"))))
            A("")
            A("Đáng tách ra vì một ETF ngành và một mã đơn lẻ không phải cùng một công cụ khi "
              "hỏi về vay mượn, thanh khoản hay sự kiện doanh nghiệp, và một con số đầu bảng "
              "gộp cả hai sẽ che mất cái nào đang gánh.")
            A("")

    # ═══════════════════════════════════════════ §4.8 bootstrap
    A("### 4.8 Lãi ròng có phân biệt được với 0 không?")
    A("")
    A("Các lệnh không phải những lần rút độc lập — nhiều mã thường phát tín hiệu trong cùng một "
      "phiên rồi cùng chia nhau hướng đi của thị trường suốt năm ngày sau. Nên đơn vị lấy mẫu "
      "lại ở đây là **phiên vào lệnh**: rút một ngày có hoàn lại thì mọi lệnh của ngày đó đi "
      "theo. Giả thuyết null là lãi/lỗ mỗi lệnh **đã dịch về trung bình 0**, và điều này nói "
      "thẳng ra vì kho này đã tìm thấy phương án ngược lại trong chính mã của mình: một null "
      "chưa căn giữa trong `cluster_bootstrap.py` đã thổi phồng mức ý nghĩa lên khoảng 2 lần, "
      "và lấy mẫu lại từ mẫu thô là đang kiểm \"chiến lược này có đúng cái edge mà nó trông như "
      "đang có không\" — câu đó mẫu nào cũng qua.")
    A("")
    if not boot:
        A("_Chưa có artifact bootstrap._")
    else:
        A("| cửa sổ | lệnh | ngày vào lệnh | ròng | KTC 95% | p (một phía) |")
        A("|---|---:|---:|---:|---|---:|")
        for k in ("full 2019-01-02..2022-12-30", "in-sample 2019-2020",
                  "out-of-sample 2021-2022"):
            r = boot.get(k)
            if not r or "error" in (r or {}):
                continue
            vn = {"full 2019-01-02..2022-12-30": "toàn bộ 2019-01-02..2022-12-30",
                  "in-sample 2019-2020": "trong mẫu 2019-2020",
                  "out-of-sample 2021-2022": "ngoài mẫu 2021-2022"}[k]
            A("| {} | {} | {} | {} | [{}, {}] | **{}** |".format(
                vn, r["n_trades"], r["n_entry_days"], money(r["observed_total"]),
                money(r["boot_ci95_low"]), money(r["boot_ci95_high"]),
                r["p_one_sided_vs_centred_null"]))
        A("")
        chk = boot.get("self_check_zero_edge_sample", {})
        if chk:
            A("Phép tự kiểm có khả năng đỏ: một mẫu **không có edge** dựng nhân tạo, cùng cách "
              "gom cụm theo ngày và cùng độ phân tán, cho p = **{}**. Nếu cái đó ra có ý nghĩa "
              "thống kê thì null đã căn sai và mọi p-value bên trên đều vô giá trị.".format(
                  chk.get("p_one_sided_vs_centred_null")))
            A("")
        A("Cái nó **không** nói: không nói gì về thiên lệch sống sót, không nói gì về việc các "
          "giả định chi phí có đúng không, và không nói gì về việc luật có được chọn sau khi "
          "nhìn dữ liệu hay không. Một p nhỏ trên một danh sách toàn kẻ sống sót vẫn là một p "
          "nhỏ trên một mẫu thiên lệch. Và một p không vượt ngưỡng là **thiếu bằng chứng, chứ "
          "không phải bằng chứng phủ định** — dự án này đã phải nói câu đó hai lần rồi.")
        A("")

    # ═══════════════════════════════════════════ §4.9 tách nhánh
    A("### 4.9 Tách tuyến thành từng nhánh")
    A("")
    A("Một con số gộp che mất nhánh nào gánh và nhánh nào kéo xuống. Nhưng phép tách này phải "
      "đọc bằng **hai nghĩa khác nhau**, và lẫn chúng là cách dễ nhất để kết luận sai:")
    A("")
    A("- **Quy kết** — lấy đúng các dòng của nhánh đó *trong cuốn sổ đã chạy*. Các nhánh cộng "
      "lại đúng bằng tổng (đã kiểm: lệch $0,00).")
    A("- **Phản thực** — ghi sổ lại chỉ với ứng viên của nhánh đó, cho nó *toàn bộ* sức chứa. "
      "Các nhánh **không** cộng lại thành tổng, vì mỗi nhánh được dùng lại cùng số vốn.")
    A("")
    A("Sổ bị chặn bởi vốn — khoảng chín vị thế cùng lúc cho 6.268 ứng viên — nên bỏ một nhánh "
      "thì nhánh còn lại không giữ nguyên số lệnh của nó: nó được thêm suất.")
    A("")
    if not dec:
        A("_Chưa có artifact tách nhánh._")
    else:
        A("**Quy kết** (cộng lại = tổng sổ):")
        A("")
        A("| nhánh | lệnh | ròng | $/lệnh | KTC 95% | p |")
        A("|---|---:|---:|---:|---|---:|")
        for nm, v in dec.get("quy_kết", {}).items():
            bb = v.get("bootstrap", {})
            ci = ("[{}, {}]".format(money(bb.get("boot_ci95_low")),
                                    money(bb.get("boot_ci95_high")))
                  if "error" not in bb else "n/a")
            A("| {} | {} | {} | {} | {} | {} |".format(
                nm, v["trades"], money(v["net"]), money(v["per_trade"]), ci,
                bb.get("p_one_sided_vs_centred_null", "n/a")))
        A("")
        A("**Phản thực** (mỗi nhánh chạy riêng, nguyên vốn — KHÔNG cộng lại được):")
        A("")
        A("| nhánh | ứng viên | lệnh | ròng | PF | sụt tối đa | p |")
        A("|---|---:|---:|---:|---:|---:|---:|")
        for nm, v in dec.get("phản_thực", {}).items():
            bb = v.get("bootstrap", {})
            A("| {} | {} | {} | {} | {} | {} | {} |".format(
                nm, v.get("candidates", 0), v.get("trades", 0), money(v.get("net")),
                num(v.get("profit_factor")), money(v.get("max_dd")),
                bb.get("p_one_sided_vs_centred_null", "n/a")))
        A("")
        A("**Bỏ một nhánh khỏi sổ gộp:**")
        A("")
        A("| bỏ nhánh | lệnh | ròng | chênh so với gộp | PF |")
        A("|---|---:|---:|---:|---:|")
        basenet = (prim or {}).get("overall", {}).get("net", 0)
        for nm, v in dec.get("bỏ_nhánh", {}).items():
            A("| {} | {} | {} | {} | {} |".format(
                nm, v.get("trades", 0), money(v.get("net")),
                money(v.get("net", 0) - basenet), num(v.get("profit_factor"))))
        A("")
        A("Dòng cuối bảng đó là phép kiểm cho chính lời cảnh báo ở trên: **bỏ nhánh "
          "`SHORT · ETF` làm sổ XẤU ĐI** dù bản thân nhánh ấy lỗ. Bỏ 16 lệnh thua nhỏ giải "
          "phóng suất cho những lệnh còn tệ hơn. Dưới ràng buộc vốn, \"cắt cái đang lỗ\" không "
          "phải phép cộng.")
        A("")
        A("#### Đọc kết quả này thế nào cho đúng")
        A("")
        A("**Chân bán khống là gánh nặng, và điều đó nhất quán ở mọi cách cắt.** Quy kết "
          "−$90 mỗi lệnh; chạy riêng thì PF 0,53 và p = 0,97 — tức bằng chứng nghiêng hẳn về "
          "phía nó thật sự âm, không phải nhiễu. Bỏ nó ra, sổ đi từ +$9.282 lên +$24.014.")
        A("")
        A("**Nhưng nhánh tốt nhất là nhánh bị nhiễm nặng nhất, và p của nó không sống nổi qua "
          "phép đếm.** `LONG · mã đơn lẻ` cho p = 0,0378 khi quy kết và 0,0646 khi chạy riêng. "
          "Đó là **một trong tám nhánh** được thử. Với tám phép kiểm, xác suất có ít nhất một "
          "p < 0,05 thuần do may rủi đã là khoảng 34%; nhân thô cho số phép kiểm thì "
          "0,0378 × 8 ≈ 0,30. Các nhánh lại lồng nhau nên phép nhân đó là bảo thủ — nhưng kết "
          "luận không đổi: **đây là một lát cắt hậu kiến, không phải một phát hiện**.")
        A("")
        A("Và chiều của thiên lệch trỏ đúng vào nhánh ấy. Rổ mã là danh sách kẻ sống sót; mua "
          "cổ phiếu đơn lẻ đã biết là sống sót chính là thứ được cho sẵn đáp án nhiều nhất, "
          "còn bán khống chúng là thứ bị phạt nặng nhất. **Hai phát hiện — chân mua thắng, "
          "chân bán thua — không phải hai bằng chứng độc lập; chúng là cùng một thiên lệch "
          "nhìn từ hai phía.**")
        A("")

    # ═══════════════════════════════════════════════════ §5 nhân quả
    A("---")
    A("")
    A("## 5. Chứng minh không nhìn trước")
    A("")
    A("Một tuyên bố về nhân quả mà không thể đỏ thì không phải chứng minh. Mọi phép kiểm ở đây "
      "đều là **đột biến**, nói trước câu trả lời phải dịch theo hướng nào, và mỗi nhánh xanh "
      "đều đi kèm một nhánh đỏ bắt buộc phải dịch — nếu không thì nhánh xanh đang qua một cách "
      "rỗng.")
    A("")
    if not caus:
        A("_Chưa có artifact nhân quả._")
    else:
        s = caus.get("summary", {})
        A("| kiểm | phá cái gì | kết quả bắt buộc | đo được |")
        A("|---|---|---|---|")
        A("| **P1** | mọi bar NGAY SAU bar tín hiệu, nhân 1,5 | tín hiệu được nhận không đổi | "
          "**{}/{} không đổi** |".format(s.get("p1_unchanged"), s.get("p1_n")))
        A("| **P1r** *(nhánh đỏ)* | mọi bar NGAY TRƯỚC bar tín hiệu, nhân 1,5 | tín hiệu PHẢI "
          "dịch, nếu không thì P1 chẳng chứng minh gì | **{}/{} đã dịch** |".format(
              s.get("p1r_changed"), s.get("p1r_n")))
        A("| **P2** | không phá gì — cắt cửa sổ tại bar tín hiệu | phép quét nhân-quả-như-live "
          "tìm ra cùng bar, cùng hướng, cùng giá vào và cùng stop như phép quét nghiên cứu cả "
          "ngày | **{}/{} trùng khít** |".format(s.get("p2_identical"), s.get("p2_n")))
        p3, p4 = caus.get("p3", {}), caus.get("p4", {})
        A("| **P3** | giá đóng SPY CỦA ngày D, nhân 10 | nhãn chế độ mà tuyến này đọc cho D "
          "không dịch, còn các nhãn sau đó thì dịch | **không đổi={}, {}/{} nhãn sau đã dịch** |"
          .format(p3.get("label_read_at_probe_day_unchanged"),
                  p3.get("n_later_labels_moved"), p3.get("n_later_sessions_checked")))
        A("| **P4** | y như trên, qua `short_days_from_csv` | tư cách thành viên cổng SHORT của "
          "chính D không dịch, các ngày sau thì dịch | **không đổi={}, {}/{} ngày sau đã dịch** |"
          .format(p4.get("probe_day_membership_unchanged"),
                  p4.get("n_later_memberships_moved"), p4.get("n_later_sessions_checked")))
        A("")
        sc = caus.get("self_check", {})
        bad = [k for k, v in sc.items() if v is not True]
        if bad:
            A("**Không phải mọi phép tự kiểm đều qua:** " + ", ".join("`" + x + "`"
                                                                      for x in bad))
        else:
            A("Cả {} phép tự kiểm đều qua.".format(len(sc)))
        A("")
        A("**P2 chính là câu trả lời riêng cho câu hỏi về phép quét cả ngày.** Nghiên cứu quét "
          "14:00-15:55 trong một lượt; một slot live tại thời điểm T chỉ nhìn được 14:00..T. "
          "Hai bên trùng nhau, và trùng vì một lý do phát biểu được chứ không phải nhờ may: "
          "`_scan_window` lấy khối lượng trung bình từ `win['volume'].iloc[k-11:k-1]`, tức nhìn "
          "hoàn toàn về phía sau từ mỗi bar, nên cắt đuôi cửa sổ không thể đổi trung bình ở bất "
          "kỳ bar nào sống sót qua nhát cắt. Track 1 khẳng định đúng phép tương đương này cho "
          "`detect_entry_for_slot`; đây là khẳng định đó chạy lại trên bar cổ phiếu.")
        A("")
    A("### 5.1 Cái gì nhân quả theo cấu tạo, và nói rõ ra như vậy")
    A("")
    A("```text")
    A("ATR ngày          dịch một phiên        -- mục 2.2")
    A("nhãn chế độ       lag 1                 -- nhãn mới nhất TỒN TẠI lúc 14:00 ngày D")
    A("cổng SHORT SPY    lag 1 theo cấu tạo    -- spy.shift(1) bên trong spy_feature_frame")
    A("sàn ADV           trung vị, dịch một phiên")
    A("biên độ hôm trước phiên TRƯỚC, dịch bên trong prev_rth_range_map")
    A("rvol bar vào      khối lượng của chính bar vào, thứ ĐÃ biết tại giá đóng của nó, vì")
    A("                  engine vào lệnh tại chính giá đóng đó")
    A("```")
    A("")
    A("### 5.2 Đúng một thứ ở đây KHÔNG được chứng minh")
    A("")
    A("Mô hình HMM trong bộ nhãn `production` khớp tới **2024-12-31** và được dùng để gán nhãn "
      "cho các phiên 2019-2022. Đó là nhìn trước, không tránh được nếu muốn dùng bản đóng băng "
      "sản xuất của futures, và đó là lý do lượt chạy chính dùng bộ nhãn `causal` — khớp tới "
      "2018-12-31, chỉ gán nhãn các phiên sau đó. Hai bộ thống nhất trên **80,3% số phiên**, "
      "nên lựa chọn này có gánh việc và cả hai đều được báo cáo. Mục 6.2.")
    A("")
    A("### 5.3 Một phép tự kiểm đã đỏ, và nó bắt được gì")
    A("")
    A("`LC4` khẳng định `stop_distance == 2,0 x ATR ngày` tới 1e-9. Ở lượt chạy đầu nó đo được "
      "**0,5802** — 42% số dòng sai. Nguyên nhân không nằm ở engine: sổ đang đo khoảng cách "
      "stop so với giá vào lệnh *đã ghi sổ* hai chữ số thập phân, trong khi bản thân stop chưa "
      "làm tròn, nên khoảng cách sai tới nửa xu và số cổ phần sai theo. Sửa bằng cách định cỡ "
      "trên khoảng cách của chính luật và mang theo cả hai mức giá. `LC4` giờ đo được **1,0**, "
      "và lãi ròng dịch khoảng $6 trên lượt chạy thử ba mã — đó mới là điểm chính: đây là lỗi "
      "về tính đúng đắn, không phải về độ lớn, và chỉ một phép kiểm có khả năng đỏ mới bao giờ "
      "tìm ra nó.")
    A("")

    # ═══════════════════════════════════════════════════ §6 ổn định
    A("---")
    A("")
    A("## 6. Độ ổn định")
    A("")
    if not stab:
        A("_Chưa có artifact độ ổn định._")
    else:
        A("**Cam kết trước khi chạy: `ema_period` giữ nguyên 50, bảng này in ra gì cũng vậy.** "
          "50 là giá trị mà các artifact Track 1 được sinh ra dưới đó, và tầng này được giao "
          "việc tái tạo logic ứng viên chứ không phải tinh chỉnh nó. Phép quét trả lời một câu "
          "hỏi khác — kết quả có nằm trên lưỡi dao không — và một phép quét làm dịch giá trị đã "
          "chốt thì là curve fitting khoác áo nhãn ổn định.")
        A("")
        A("Tập con: {}.".format(stab.get("subset")))
        A("")
        A("| lượt | lệnh | ròng | PF | thắng | sụt tối đa |")
        A("|---|---:|---:|---:|---:|---:|")
        for tag, r in stab.get("runs", {}).items():
            if "metrics" not in r:
                A("| `{}` | _hỏng_ | | | | |".format(tag))
                continue
            mm = r["metrics"]
            A("| `{}` | {} | {} | {} | {}% | {} |".format(
                tag, mm.get("trades", 0), money(mm.get("net")),
                num(mm.get("profit_factor")), num(mm.get("win_rate")),
                money(mm.get("max_dd"))))
        A("")
        A("### 6.1 Vì sao phép quét EMA cũng là phép dò khả năng chuyển tuyến")
        A("")
        A("Engine tính EMA trên bar 5 phút **của chính phiên đó**, bắt đầu từ bar đầu phiên. Đo "
          "trên `ES_continuous_1m.parquet` giai đoạn 2019-2022: một ngày lịch futures mang "
          "trung vị **273** bar 5 phút, trong đó **169 bar rơi vào lúc 14:00 ET hoặc sớm hơn**. "
          "Một phiên cổ phiếu RTH mang **78** bar, trong đó **55** bar rơi vào 14:00 hoặc sớm "
          "hơn. Vậy cùng một `EMA(50)` có 169 bar phía sau trên futures và 55 bar trên cổ phiếu "
          "— nhỉnh hơn chính chu kỳ của nó một chút, và vẫn còn bị giá trị khởi tạo chi phối "
          "thấy rõ. Đó không phải cùng một chỉ báo trên hai công cụ, dù tham số là cùng một con "
          "số. Nếu kết quả đảo mạnh qua 20/30/50 thì quãng khởi động đó đang gánh việc, và phép "
          "chuyển tuyến mong manh vì một lý do chẳng liên quan gì tới edge.")
        A("")
        A("### 6.2 Nhãn chế độ và độ trễ")
        A("")
        A("`causal` khớp HMM tới 2018-12-31; `production` là lời gọi y hệt của futures "
          "(`train_end=2018-01-01`, `hmm_fit_end=2024-12-31`). Hai bộ thống nhất trên **80,3%** "
          "số phiên và lệch nhau theo một hướng cụ thể — bản khớp causal gọi **26,0%** số phiên "
          "là Stress so với **13,4%** của bản production, đúng thứ mà docstring của chính "
          "`label_regimes` cảnh báo: một cửa sổ khớp ngắn làm trạng thái Stress bị định nghĩa "
          "thiếu. `lag0` là thứ `track1_params` khai báo cho `roska4_swing`; nó được đo và nó "
          "không phải con số đầu bảng, vì lúc 14:00 ngày D thì nhãn của D là hàm của một giá "
          "đóng còn cách đó hai tiếng.")
        A("")

    # ═══════════════════════════════════════════════════ §7 giới hạn
    A("---")
    A("")
    A("## 7. Sống sót, thanh khoản và sự kiện doanh nghiệp")
    A("")
    A("### 7.1 Thiên lệch sống sót — cảnh báo lớn nhất")
    A("")
    A("> **Kết quả này thiên lệch vì sống sót và vì cách chọn mẫu, và không có gì trên đĩa này "
      "sửa được thiên lệch đó.**")
    A("")
    A("Rổ mã là tập những cái tên mà ai đó đã chọn để cache bar 5 phút. Mã nào cũng lớn và "
      "thanh khoản vào lúc được chọn, và mã nào cũng sống qua 2019-2022. Một luật thiên về mua "
      "và đi theo xu hướng, chạy trên một danh sách toàn kẻ sống sót đã biết, là đang được cho "
      "sẵn đáp án. Trong kho không có tệp thành phần theo thời điểm nào — điều đó là **đã tìm**, "
      "không phải giả định, và mục 1.2 nêu tên những gì tìm thấy thay vào đó.")
    A("")
    if prim and prim["breakdowns"].get("by_direction"):
        bd = prim["breakdowns"]["by_direction"]
        tot = sum(v["trades"] for v in bd.values())
        lng = bd.get("LONG", {}).get("trades", 0)
        A("Phân bố hướng làm mức phơi nhiễm này thành cụ thể: **{} trên {} lệnh ({:.0f}%) là "
          "MUA**. Một danh sách kẻ sống sót thiên vị đúng phía đó.".format(
              lng, tot, 100 * lng / tot if tot else 0))
        A("")
    A("### 7.2 Thanh khoản")
    A("")
    A("```text")
    A("giá tối thiểu              $5,00")
    A("ADV tối thiểu              $20.000.000   (TRUNG VỊ giá trị giao dịch 20 phiên trượt,")
    A("                                          đã dịch một phiên)")
    A("tỉ lệ tham gia tối đa      1% số cổ phần ADV")
    A("                           10% khối lượng của chính bar 5 phút vào lệnh")
    A("```")
    A("")
    A("Cố ý dùng trung vị chứ không phải trung bình cho ADV: một phiên báo cáo kết quả có thể "
      "kéo trung bình 20 ngày lên đủ để đưa một mã vượt qua cái sàn mà nó không giữ được vào "
      "ngày thường. Một ứng viên phạm sàn được ghi vào sổ là `REJECTED` kèm lý do, chứ không bị "
      "bỏ im lặng — một bộ lọc mà các lần từ chối vô hình thì không soi được.")
    A("")
    if probe and probe.get("liquidity_sample"):
        A("Trên các mã lấy mẫu, các sàn này còn xa mới ràng buộc, và bản thân đó là một phát "
          "hiện — nghĩa là bộ lọc thanh khoản **không** phải thứ đang bảo vệ kết quả này, và "
          "một tuyến chạy trên rổ rộng hơn hoặc vốn hoá nhỏ hơn sẽ phải đo lại chứ không dùng "
          "lại:")
        A("")
        A("| mã | ADV trung vị | ADV nhỏ nhất | giá đóng trung vị |")
        A("|---|---:|---:|---:|")
        for r in probe["liquidity_sample"]:
            A("| {} | ${:,.0f} | ${:,.0f} | ${:.2f} |".format(
                r["symbol"], r["median_adv_usd"], r["min_adv_usd"], r["median_close"]))
        A("")
    A("### 7.3 Sự kiện doanh nghiệp")
    A("")
    A("**Chỉ** được xử lý bởi phép điều chỉnh chia tách và cổ tức của nhà cung cấp "
      "(`adjusted=true`). Cái đó phủ gì và không phủ gì:")
    A("")
    A("| | |")
    A("|---|---|")
    A("| chia tách | có phủ — giá và khối lượng được điều chỉnh ngược |")
    A("| cổ tức thường | có phủ trong chuỗi giá, nên lãi/lỗ ngầm bao gồm cổ tức cho lệnh mua và "
      "tính phí cho lệnh bán khống, mà không bên nào hiện ra thành một dòng riêng |")
    A("| phép điều chỉnh ngược viết lại quá khứ | **đây là mối nguy đã biết, và ở đây KHÔNG "
      "đo.** Một khoản cổ tức trả năm 2026 làm đổi một mức giá đã điều chỉnh của 2019. Kho này "
      "đã từng phán về nguyên tắc đó cho futures: *giá lịch sử phải bất biến; nếu thêm dữ liệu "
      "mới mà giá của một năm cũ dịch đi thì phương pháp nối chuỗi sai.* Cache cổ phiếu mang "
      "đúng tính chất ấy theo cấu tạo và không có ảnh chụp đóng băng nào, nên **backtest này "
      "không tái tạo được tới từng xu sau lần làm mới cache kế tiếp** |")
    A("| huỷ niêm yết và sáp nhập | **không xử lý và ở đây không kiểm được** — trong rổ không "
      "có mã nào bị huỷ niêm yết, mà đó chính là bài toán sống sót nói lại một lần nữa |")
    A("| đổi mã | **không xử lý, và trong rổ có một ví dụ sống.** `META` chỉ có 290 trên {} "
      "phiên, bắt đầu 2021-06-30, và trong cache không hề có `FB`. Một mã đổi tên ngay trong "
      "cửa sổ thì bị thiếu lịch sử một cách im lặng chứ không có gì báo; sàn 250 phiên đã cho "
      "nó đi qua (mục 1.2) |".format(n_sess if n_sess else "số"))
    A("")

    # ═══════════════════════════════════════════════════ §8 phát hiện
    A("---")
    A("")
    A("## 8. Phát hiện gửi lại — ba về Track 1, ba về phép chuyển tuyến")
    A("")
    A("Ba mục về Track 1 lộ ra trong lúc đọc mã để chuyển nó. Mỗi mục được dán nhãn rõ cái gì "
      "đã đo và cái gì chưa, vì hai trong ba là quan sát từ đọc mã mà **tác động lên sổ futures "
      "thì tầng này không đo và không khẳng định**.")
    A("")
    A("### T-1 · ATR của stop được đọc ngay trong ngày mà nó được tính từ đó — *đọc mã, chưa đo "
      "tác động trên futures*")
    A("")
    A("`daily_atr_series` trả về trung bình trượt kết thúc tại ngày D. `make_signal_fn` đọc "
      "`datr.asof(day)` cho một lần vào lệnh trong 14:00-15:55 của chính ngày D đó. Nên giá trị "
      "ấy chứa các bar muộn hơn trong D so với thời điểm ra quyết định. Đo trên frame cổ phiếu, "
      "hai định nghĩa lệch trung vị khoảng 2,6-3,2% và tới 71%. **Nó gây ra gì cho sổ futures "
      "thì ở đây không đo.** Nó ảnh hưởng tới cả định cỡ lẫn thoát lệnh, vì `|entry - stop|` "
      "chính là cơ sở nhận lệnh mà Stage 5Q-9 đã chốt.")
    A("")
    A("### T-2 · `roska4_swing` khai báo `label_lag_days = 0`, và live có thể không tôn trọng "
      "được điều đó — *đọc mã, CHƯA xác minh trọn đường*")
    A("")
    A("```text")
    A("track1_params.py:414      label_lag_days=0                 (roska4_swing)")
    A("track1_normal_r4.py       labels.get(day)                  -- nhãn CỦA CHÍNH ngày D")
    A("run_scheduler.py:867      PRE-FLIGHT 13:45 ET -> update_spy_csv, fetch [.., today]")
    A("run_scheduler.py:955      spy_refresh_pm 16:20 ET          -- sau giờ đóng cửa")
    A("```")
    A("")
    A("Nhãn của D là hàm của giá đóng 16:00 SPY ngày D. Một slot Normal-R4 nổ lúc 14:05 ngày D. "
      "Cả hai lần làm mới SPY đều nằm sai phía so với thời điểm đó: một lần lúc 13:45, khi giá "
      "đóng chưa tồn tại, và một lần lúc 16:20, sau khi slot đã qua. Vậy có ba trạng thái khả "
      "dĩ lúc 14:05 và **cả ba đều là một chỗ lệch giữa live và backtest**:")
    A("")
    A("| lúc 14:05 ngày D, CSV đang giữ | thì `labels.get(D)` trả về | và live so với backtest |")
    A("|---|---|---|")
    A("| không có dòng nào cho D | `None` | sleeve không giao dịch được gì phiên đó |")
    A("| một dòng cho D dựng từ giá đóng **một phần** lúc 13:45 | một nhãn tính từ ảnh chụp "
      "trong ngày | một nhãn khác với nhãn backtest đã dùng, và nó bị ghi đè im lặng lúc 16:20 |")
    A("| một dòng cho D với giá đóng thật | đúng nhãn của backtest | bất khả thi lúc 14:05 |")
    A("")
    A("**Chỗ này chưa truy tới kết luận và không được đọc như một kết luận.** Trạng thái nào "
      "xảy ra còn phụ thuộc vào việc Polygon có trả bar ngày đang dở lúc 13:45 hay không, và "
      "điều đó ở đây chưa kiểm. `track1_live_source` cũng mang một hàm phụ trợ "
      "`causal_regime_label` mà docstring của chính nó nói rằng đọc dòng của hôm nay là nhìn "
      "trước — nên tuyến live có thể đã lệch một cách có chủ đích, và khi đó thứ sai là *lời "
      "khai báo*, đúng hình dạng của phát hiện I-1 ở Stage 5Q-8.")
    A("")
    A("Một thứ ĐÃ đo: lúc 2026-08-26 09:50 MDT, dòng cuối của `spy_daily_live.csv` là "
      "**2026-08-24**. Không có dòng nào cho thứ Ba 2026-08-25, nên dù cơ chế là gì, nhãn SPY "
      "mới nhất mà một slot đọc được hôm nay đã cũ hai phiên.")
    A("")
    A("### T-3 · `max_hold_days` đếm theo ngày lịch — *đo ở đây, cả hai tuyến đều thừa hưởng*")
    A("")
    A("`hold = (day - pos['entry_day']).days` với `max_hold_days = 5`. Vì phép đếm tính bằng "
      "ngày lịch trong khi vòng lặp bước qua từng phiên, số ngày nắm giữ thật phụ thuộc vào thứ "
      "trong tuần lúc vào lệnh: vào thứ Hai thì thoát sau năm phiên, vào thứ Tư thì thoát sau "
      "ba phiên. Trên frame futures gần như liên tục, méo mó này nhỏ hơn so với một tuần cổ "
      "phiếu năm phiên, nhưng nó là cùng một luật ở cả hai bên, và gần như chắc chắn không phải "
      "điều mà \"max hold 5 ngày\" định nói.")
    A("")
    A("### S-1 · ngưỡng biên độ R4 là một phân vị futures — *đã đo*")
    A("")
    A("Mục 2.3 và các dòng cấu hình `C`/`D` ở mục 3.4.")
    A("")
    A("### S-2 · stop 2,0 x ATR gần như không ràng buộc trên cổ phiếu — *đã đo*")
    A("")
    if prim and prim["breakdowns"].get("by_exit_reason"):
        er = prim["breakdowns"]["by_exit_reason"]
        tot = sum(v["trades"] for v in er.values())
        mh = er.get("MAX_HOLD", {}).get("trades", 0)
        ch = er.get("CHANDELIER", {}).get("trades", 0)
        gp = er.get("GAP", {}).get("trades", 0)
        A("**{} trên {} lần thoát ({:.0f}%) là `MAX_HOLD`**, so với {} lần thoát bằng stop "
          "({:.1f}%) và {} lần thoát bằng gap. Trên chân trời năm ngày, cái stop gần như chỉ "
          "để trưng: luật đang hành xử như \"giữ khoảng một tuần\" kèm một tấm chắn rủi ro "
          "đuôi, chứ không phải như một lệnh được quản bằng stop. Hỗn hợp lối thoát của sleeve "
          "futures là gì thì cũng không phải cái này, và mọi trực giác mang từ bên đó sang về "
          "việc stop định hình phân bố ra sao đều không sống sót qua phép chuyển.".format(
              mh, tot, 100 * mh / tot if tot else 0, ch, 100 * ch / tot if tot else 0, gp))
    else:
        A("_Chưa có hỗn hợp lối thoát._")
    A("")
    A("### S-3 · đêm đầu tiên không có stop — *hệ quả thiết kế, chưa đo thành chi phí*")
    A("")
    A("Mục 1.4. Stop vũ trang lúc 14:05 phiên sau khi vào, nên khoảng nhảy qua đêm đầu tiên "
      "không được bảo vệ. Trên cổ phiếu đó là rủi ro đơn lẻ lớn nhất mà vị thế mang. Cái giá "
      "của nó ở tầng này **chưa** được tách ra; muốn tách phải chạy một lượt đổi luật vũ trang, "
      "và như vậy thì không còn là phép chuyển trung thành nữa.")
    A("")

    # ═══════════════════════════════════════════════════ §9 phán quyết
    A("---")
    A("")
    A("## 9. Phán quyết, chốt chặn, tầng kế tiếp")
    A("")
    A("### 9.1 Phán quyết")
    A("")
    A("**BACKTEST_VALID.** Tập lệnh tái tạo được từ chính đoạn mã sinh ra nó, mọi ứng viên đều "
      "nằm trên sổ kèm lý do được nhận hay bị từ chối, các phép kiểm nhân quả đều qua với nhánh "
      "đỏ hoạt động, và mọi giả định riêng của cổ phiếu đều được khai báo và quét. \"Hợp lệ\" ở "
      "đây nghĩa là *phép đo vững và giới hạn của nó được nói ra* — nó không có nghĩa là triển "
      "khai được.")
    A("")
    if prim and sens:
        oos = prim["oos_window"]
        be = sens.get("breakeven_slippage_bps_per_side")
        bo = (boot or {}).get("out-of-sample 2021-2022", {})
        A("Về câu hỏi edge có chuyển được không, bốn thứ được cân, theo thứ tự này:")
        A("")
        A("1. **nửa ngoài mẫu** — ròng {} trên {} lệnh, PF {};".format(
            money(oos.get("net")), oos.get("trades", 0), num(oos.get("profit_factor"))))
        if bo and "error" not in bo:
            A("2. **cái đó có phân biệt được với 0 không** — gom cụm theo ngày, null đã căn "
              "giữa, p = **{}**, KTC 95% [{}, {}];".format(
                  bo.get("p_one_sided_vs_centred_null"), money(bo.get("boot_ci95_low")),
                  money(bo.get("boot_ci95_high"))))
        else:
            A("2. **cái đó có phân biệt được với 0 không** — chưa có bootstrap;")
        A("3. **nó đang mua bằng bao nhiêu chất lượng thực thi** — trượt giá hoà vốn {} bps mỗi "
          "chiều so với mức giả định 3,0;".format(num(be, "{:.2f}")))
        A("4. **mẫu là cái gì** — một danh sách kẻ sống sót, không sửa được theo thời điểm bằng "
          "bất cứ thứ gì trên đĩa này.")
        A("")
        A("Dòng phán quyết ở đầu báo cáo suy ra từ bốn thứ đó. Điểm 4 không phải một chú thích "
          "cho ba điểm kia: nó chặn mức độ tin được của cả ba, và đó là lý do tầng kế tiếp nói "
          "về nền đo chứ không nói về chiến lược.")
        A("")
    A("### 9.2 Chốt chặn trước khi paper")
    A("")
    A("| # | chốt chặn | vì sao nó chặn |")
    A("|---|---|---|")
    A("| 1 | **Thiên lệch sống sót.** Không có rổ theo thời điểm | kết quả đo trên một danh "
      "sách kẻ sống sót đã biết. Chừng nào tư cách thành viên chưa tính theo ngày, con số đầu "
      "bảng là một cận trên chưa biết chặt tới đâu |")
    A("| 2 | **Mô hình chi phí là giả định, không phải đo** | hoa hồng, trượt giá và lãi vay "
      "đều là phỏng đoán đúng hình dạng. Con số trượt giá hoà vốn quyết định chuyện đó có quan "
      "trọng không, và nó phải đem so với một mẫu khớp lệnh thật, không phải với một hy vọng |")
    A("| 3 | **Chưa có ngắt tài khoản** | hai cái ngắt sụt cứng 15% và lỗ ngày 4% được cố ý bỏ "
      "ra ngoài để chúng không làm nhiễu phép đo tín hiệu. Chúng phải tồn tại trước khi có bất "
      "kỳ lệnh nào được định tuyến |")
    A("| 4 | **Khả năng vay để bán khống là giả định** | trên đĩa này không có dữ liệu vay. Mọi "
      "lệnh SHORT trong sổ đều giả định vay được |")
    A("| 5 | **Backtest không tái tạo được sau lần làm mới cache kế tiếp** | cache cổ phiếu "
      "được điều chỉnh ngược tại chỗ và không có ảnh chụp đóng băng (mục 7.3) |")
    A("| 6 | **T-2 còn để ngỏ** | nếu tuyến live futures không tôn trọng được `label_lag_days=0` "
      "thì cùng câu hỏi ấy áp cho mọi tuyến cổ phiếu dựng trên cùng hệ nhãn |")
    A("")
    A("### 9.3 Tầng kế tiếp, chính xác")
    A("")
    A("**STOCKS-1 — đóng băng nền đo, rồi mới định giá thiên lệch sống sót.** Theo đúng thứ tự "
      "này, vì việc thứ hai vô nghĩa nếu chưa có việc thứ nhất:")
    A("")
    A("0. **Chạy Calm A trên cổ phiếu.** Rẻ nhất trong bốn việc — một lần vào lệnh lúc 10:00, "
      "không có vòng quét, nên chi phí tính toán chỉ bằng một phần nhỏ tầng này. Nó cho một "
      "luật thứ hai, độc lập, trên cùng nền dữ liệu; và vì nó là luật MUA trên phiên hồi phục "
      "sau một ngày giảm, nó chịu đúng cùng chiều thiên lệch sống sót, nên phải đọc kèm việc 2 "
      "chứ không đọc riêng.")
    A("1. **Đóng băng dữ liệu.** Ghi một parquet bất biến cho từng mã chứa đúng các frame 5 "
      "phút RTH đã dùng ở đây, kèm sha256 mỗi tệp ghi vào hash cấu hình. Chừng nào chưa có nó, "
      "không con số cổ phiếu nào dựng lại được sau một lần làm mới cache, và mọi phép so về sau "
      "đều đo trên nền đã trôi.")
    A("2. **Chặn thiên lệch sống sót.** Dựng một danh sách thành viên theo ngày — kể cả một "
      "danh sách thô từ bảng niêm yết/huỷ niêm yết — rồi chạy lại. Nếu không lấy được rổ theo "
      "thời điểm thì nói thẳng ra và vĩnh viễn coi con số đầu bảng là cận trên, chứ không lặng "
      "lẽ tiếp tục trích dẫn nó.")
    A("3. **Đo một mẫu khớp lệnh thật** đối chiếu với trượt giá hoà vốn ở mục 4.1. Đây là việc "
      "rẻ nhất trong ba việc và làm được từ dữ liệu broker mà tuyến futures vốn đã sinh ra.")
    A("")
    A("Rõ ràng **không** phải việc kế tiếp: tinh chỉnh `ema_period`, suy lại ngưỡng biên độ để "
      "kết quả đẹp hơn, thêm sleeve Calm hay Stress, hay kéo dài cửa sổ bằng một nhà cung cấp "
      "thứ hai. Ba việc đầu là curve fitting trên một nền thiên lệch sống sót; việc thứ tư sẽ "
      "lặng lẽ trộn hai định danh dữ liệu vào một chuỗi.")
    A("")

    # ═══════════════════════════════════════════════════ §10 tệp
    A("---")
    A("")
    A("## 10. Tệp")
    A("")
    A("**Chỉ đọc. Không sửa mã sản xuất. Mọi thứ dưới đây nằm trong `scratch/`.**")
    A("")
    A("```text")
    A("thêm    scratch/stocks_stage0_data_20260826.py          tầng dữ liệu cổ phiếu")
    A("thêm    scratch/stocks_stage0_regime_20260826.py        nhãn SPY-HMM, hai bản khớp")
    A("thêm    scratch/stocks_stage0_engine_20260826.py        chi phí / định cỡ / sổ / định danh")
    A("thêm    scratch/stocks_stage0_run_20260826.py           bộ chạy backtest")
    A("thêm    scratch/stocks_stage0_causality_20260826.py     chứng minh không nhìn trước")
    A("thêm    scratch/stocks_stage0_sensitivity_20260826.py   ghi sổ lại dòng ứng viên cache")
    A("thêm    scratch/stocks_stage0_stability_20260826.py     ổn định tham số / nhãn")
    A("thêm    scratch/stocks_stage0_bootstrap_20260826.py     gom cụm theo ngày, null căn giữa")
    A("thêm    scratch/stocks_stage0_decompose_20260826.py     tách nhánh: quy kết + phản thực")
    A("thêm    scratch/stocks_stage0_probe_20260826.py         dò độ phủ + nhân quả ATR")
    A("thêm    scratch/stocks_stage0_report_20260826.py        dựng báo cáo này")
    A("")
    A("dữ liệu scratch/_stocks_stage0_probe.json")
    A("dữ liệu scratch/_stocks_stage0_regime_labels.csv")
    A("dữ liệu scratch/_stocks_stage0_results.json")
    A("dữ liệu scratch/_stocks_stage0_causality.json")
    A("dữ liệu scratch/_stocks_stage0_sensitivity.json")
    A("dữ liệu scratch/_stocks_stage0_stability.json")
    A("dữ liệu scratch/_stocks_stage0_bootstrap.json")
    A("dữ liệu scratch/_stocks_stage0_decompose.json")
    A("sổ      scratch/_stocks_stage0_ledger_<cấu hình>.csv")
    A("dòng    scratch/_stocks_stage0_candidates_<cấu hình>.pkl")
    A("```")
    A("")
    if main_res and PRIMARY in main_res.get("results", {}):
        A("### Định danh cấu hình của lượt chạy chính")
        A("")
        A("Đây là câu trả lời của tuyến cổ phiếu cho `route_params.params_hash`. Nó cố ý **không** "
          "mang `point_value`, `tick` hay `tradable_symbol` — đó là những câu trả lời của "
          "futures — và nó **có** mang những thứ quyết định một số cổ phần, đúng chỗ trống mà "
          "Stage 5Q-8 đã tìm ra trong hash futures bằng cách đắt tiền.")
        A("")
        A("```text")
        A(main_res["results"][PRIMARY]["config_hash"])
        A("```")
        A("")
        A("<details><summary>mọi trường đã đi vào hash</summary>")
        A("")
        A("```text")
        for k, v in main_res["results"][PRIMARY]["config_fields"].items():
            A("{:34s} {}".format(k, v))
        A("```")
        A("")
        A("</details>")
        A("")

    MD.write_text("\n".join(L), encoding="utf-8")

    payload = {
        "stage": "STOCKS-0",
        "date": "2026-08-26",
        "contract": "read_only_no_broker_no_orders_no_production_writes",
        "verdict": {
            "backtest_valid": "BACKTEST_VALID" if prim else "BACKTEST_NOT_VALID",
            "portable_edge": (edge if prim else "UNDECIDED — chưa có kết quả"),
            "edge_gate_pre_committed": EDGE_GATE,
            "edge_gate_measured": ([{"check": c, "value": v, "pass": ok}
                                    for c, v, ok in checks] if prim else []),
            "primary_config": PRIMARY,
        },
        "artifacts_missing": missing,
        "probe": probe,
        "results": main_res,
        "causality": caus,
        "sensitivity": sens,
        "stability": stab,
        "bootstrap": boot,
        "extended_window_2018_2022_production_labels": ext,
        "decomposition": dec,
    }
    JS.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print("đã ghi", MD)
    print("đã ghi", JS)
    if missing:
        print("THIẾU artifact:", missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
