"""Neo lại TRƯỚC cửa sổ, và chỉ khi hợp đồng thật sự đổi. TỆP MỚI.

Chuyện đã xảy ra đêm 10/09
--------------------------
IBKR chuyển chuỗi liên tục NKD sang kỳ hạn tháng 12 trong khoảng giữa job 13:45 hôm trước và
slot NKD đầu tiên lúc 01:10. Mười hai slot từ chối với `series_rolled`: bar đến từ NKDZ6 còn
lịch sử neo trên NKDU6.

Việc neo lại chỉ nằm trong job 13:45, nên nó sửa được — **sau** khi cửa sổ đã trôi qua. Mỗi
lần roll mất trọn một cửa sổ, bốn lần một năm.

Và lần tới đắt hơn: rổ Mỹ đáo hạn 18/09, IBKR roll trước đáo hạn một ngày. Cửa sổ Calm
(10:00) và Stress (10:35-12:30) đều nằm TRƯỚC job 13:45 — cả hai sẽ mất trọn ngày hôm đó.

Vì sao không chạy job đầy đủ trước mỗi cửa sổ
----------------------------------------------
Vì neo lại và ghi bar là một việc trong mã hiện tại, nên làm thế là **ghi vào parquet thêm
hai lần mỗi ngày, quanh năm** — trên đúng đường mã đã gây ra sự cố 2026-08-05, khi một độ
lệch sai được viết vào chuỗi và trôi ba ngày không ai thấy.

Roll thì chỉ bốn lần một năm. Nên bước dò quyết định có ghi hay không:

    hợp đồng trùng sổ neo   ->  thoát, không đụng gì          ~246 ngày
    hợp đồng khác           ->  neo lại, chỉ ghi SỔ NEO       ~4 ngày

Bốn điều kiện an toàn không đổi. Không đạt thì từ chối, y như trước.

Điều tệp này canh
-----------------
    1. hợp đồng không đổi  ->  KHÔNG ghi gì, kể cả sổ neo
    2. hợp đồng đổi        ->  ghi sổ neo, KHÔNG chạm parquet
    3. bốn điều kiện vẫn chặn được một lần neo sai
    4. job 13:45 sau đó KHÔNG neo lại lần nữa, và vẫn xác minh được
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import global_index.update_ibkr_daily as U        # noqa: E402


# ── cờ và hợp đồng của chế độ mới ────────────────────────────────────────────

def test_the_mode_exists_and_is_off_by_default():
    """Một chế độ ghi ít hơn phải là lựa chọn có ý thức, không phải mặc định lặng lẽ."""
    ap = U._argparser() if hasattr(U, "_argparser") else None
    assert ap is not None, "chưa tách được bộ đọc tham số để kiểm"
    ns = ap.parse_args([])
    assert ns.reanchor_only is False
    assert ap.parse_args(["--reanchor-only"]).reanchor_only is True


def test_the_flag_says_what_it_does_not_do():
    ap = U._argparser()
    txt = " ".join(a.help or "" for a in ap._actions if "--reanchor-only" in a.option_strings)
    for word in ("parquet", "sidecar"):
        assert word in txt.lower(), txt


# ── quyết định: có phải neo không ────────────────────────────────────────────

@pytest.mark.parametrize("stored,fetched,want", [
    ("NKDU6", "NKDU6", False),      # trùng — không đụng gì
    ("NKDU6", "NKDZ6", True),       # roll thật
    ("", "NKDZ6", False),           # chưa có sổ neo — lần đầu, không phải roll
    ("NKDU6", "", False),           # không đọc được hợp đồng — không đoán
])
def test_it_only_acts_when_the_contract_actually_changed(stored, fetched, want):
    assert U.contract_rolled(stored, fetched) is want


def test_an_unreadable_contract_is_not_a_roll():
    """Không đọc được tên hợp đồng KHÁC với hợp đồng đã đổi. Gộp hai thứ đó là neo lại dựa
    trên một câu hỏi chưa ai trả lời."""
    assert U.contract_rolled(None, "NKDZ6") is False
    assert U.contract_rolled("NKDU6", None) is False


# ── bốn điều kiện an toàn không được nới ─────────────────────────────────────

def test_the_four_conditions_are_unchanged():
    """Chế độ mới dùng lại đúng ngưỡng cũ. Một chế độ chạy thường xuyên hơn mà ngưỡng lỏng
    hơn là hai thay đổi trong một, và chỉ một trong hai được ai đó xem xét."""
    assert U.ALIGN_MIN_OVERLAP == 500
    assert U.REANCHOR_MAX_IQR_FRAC == 0.20
    assert U.REANCHOR_MIN_PCT == 0.20
    assert U.REANCHOR_MAX_PCT == 2.00


@pytest.mark.parametrize("n_ov,med,iqr,px,ok", [
    (2500, 530.0, 40.0, 65000.0, True),      # roll Sep->Dec thật: 0,82% giá, IQR 7,5%
    (300, 530.0, 40.0, 65000.0, False),      # không đủ bar chồng lấn
    (2500, 530.0, 300.0, 65000.0, False),    # IQR 57% — nhiễu, không phải bậc sạch
    (2500, 5.0, 0.4, 65000.0, False),        # 0,008% — quá nhỏ để là chênh kỳ hạn
    (2500, 3000.0, 100.0, 65000.0, False),   # 4,6% — quá lớn
])
def test_the_measurement_must_corroborate_the_roll(n_ov, med, iqr, px, ok):
    why = U.reanchor_refusals(n_ov=n_ov, med=med, iqr=iqr, price=px)
    assert (not why) is ok, why


def test_every_refusal_names_a_number():
    """Một lời từ chối không kèm số đo là một lời từ chối không kiểm lại được."""
    why = U.reanchor_refusals(n_ov=300, med=5.0, iqr=300.0, price=65000.0)
    assert len(why) == 3, why
    for w in why:
        assert any(ch.isdigit() for ch in w), w


def test_a_zero_median_does_not_divide_by_zero():
    why = U.reanchor_refusals(n_ov=2500, med=0.0, iqr=0.0, price=65000.0)
    assert why, "trung vị 0 nghĩa là không có bậc nào — không được coi là roll hợp lệ"


# ── độ lệch mới phải làm hai nửa khớp nhau ───────────────────────────────────

def test_the_new_offset_makes_the_halves_agree():
    """Đây là toàn bộ số học. Nếu sai thì job 13:45 cùng ngày sẽ bắt được — nhưng bắt được
    sau khi cửa sổ đã chạy trên một thang giá sai là quá muộn."""
    stored_offset, med = 0.0, 530.0
    new_offset = U.reanchored_offset(stored_offset, med)
    assert new_offset == pytest.approx(530.0)
    fetched_close, stored_close = 64_585.0, 65_115.0
    assert fetched_close + new_offset == pytest.approx(stored_close)


def test_it_accumulates_rather_than_replaces():
    """Roll thứ hai cộng tiếp lên độ lệch đã có, không ghi đè — một tệp đi qua nhiều kỳ hạn
    mang tổng của mọi lần chuyển."""
    assert U.reanchored_offset(530.0, -120.0) == pytest.approx(410.0)


# ── job 13:45 sau đó không được neo lại lần nữa ──────────────────────────────

def test_after_a_reanchor_the_daily_append_sees_nothing_to_do():
    """Câu hỏi của chủ dự án: nếu 00:55 đã ghi thì 13:45 có ghi lại không?

    Không. Nó đọc hợp đồng TỪ SỔ NEO, thấy trùng với hợp đồng vừa fetch, nên `contract_rolled`
    trả về False và độ lệch đo được xấp xỉ 0.
    """
    assert U.contract_rolled("NKDZ6", "NKDZ6") is False
    residual = 65_115.0 - (64_585.0 + U.reanchored_offset(0.0, 530.0))
    assert abs(residual) < U.ALIGN_MAX_DRIFT, residual


def test_the_daily_append_still_verifies_the_new_anchor():
    """Neo sai thì phép kiểm căn chỉnh của job 13:45 phải bắt được — bước 00:55 rút thời gian
    một lần neo sai có thể sống từ 24 giờ xuống 13, chứ không được bỏ phép kiểm ấy đi."""
    wrong = U.reanchored_offset(0.0, 300.0)          # đo sai, lệch 230
    residual = 65_115.0 - (64_585.0 + wrong)
    assert abs(residual) > U.ALIGN_MAX_DRIFT, residual


# ── chạy thật cả main(): tệp bar có bị chạm không ────────────────────────────
#
# Bốn phép kiểm trên đo các hàm rời. Bốn phép dưới chạy trọn `main()` với một IBKR giả và
# hỏi câu duy nhất đáng hỏi: **tệp parquet có đổi không.** Một hàm đúng mà chưa được nối vào
# đường chạy là chuyện kho này đã trả giá — cơ chế đủ code, đủ tài liệu, đủ "đã grep xác
# nhận", mà không entry point nào gọi tới.

def _tmp_world(tmp_path, *, stored_contract, fetched_contract, med=530.0,
               n_overlap=2000):
    """Dựng một thế giới nhỏ: một tệp bar, một sổ neo, một IBKR giả."""
    import types

    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    import numpy as np

    # 3.000 phút liên tục — quá 500 bar chồng lấn, và mỗi ngày đủ 24 giờ nên phép kiểm
    # quy ước UTC đọc ra "UTC" thay vì "ET".
    idx = pd.date_range("2026-09-07 00:00", periods=3000, freq="1min")
    px = 65_000.0 + np.arange(3000) * 0.25
    existing = pd.DataFrame({"open": px, "high": px + 1, "low": px - 1,
                             "close": px, "volume": 100.0}, index=idx)
    pq = tmp_path / "NKD_continuous_1m_8y.parquet"
    existing.to_parquet(pq)

    off = tmp_path / "off.json"
    off.write_text(json.dumps({"MNKD": {"offset": 0.0, "contract": stored_contract}}),
                   encoding="utf-8")

    # Bar mới: chồng lên 2.000 bar cuối, thấp hơn đúng `med`, cộng 60 phút mới.
    _first = 3000 - n_overlap
    n_idx = pd.date_range(idx[_first], periods=n_overlap + 60, freq="1min")
    n_px = 65_000.0 + np.arange(_first, 3060) * 0.25 - med
    new = pd.DataFrame({"open": n_px, "high": n_px + 1, "low": n_px - 1,
                        "close": n_px, "volume": 100.0}, index=n_idx)

    fake = types.SimpleNamespace(
        IB=lambda: types.SimpleNamespace(
            connect=lambda *a, **k: None, sleep=lambda *a, **k: None,
            disconnect=lambda: None))
    return pq, off, new, fake


def _run_main(monkeypatch, tmp_path, *, stored_contract, fetched_contract,
              reanchor_only, med=530.0, quiet=True, n_overlap=2000):
    import logging

    pq, off, new, fake = _tmp_world(tmp_path, stored_contract=stored_contract,
                                    fetched_contract=fetched_contract, med=med,
                                    n_overlap=n_overlap)
    before = pq.read_bytes()

    monkeypatch.setitem(sys.modules, "ib_insync", fake)
    monkeypatch.setattr(U, "_fetch_contfuture",
                        lambda ib, sym, exch, duration="3 D":
                        (new.copy(), fetched_contract,
                         pd.Timestamp("2026-09-09 12:00")))
    argv = ["update_ibkr_daily", "--symbols", "MNKD",
            "--nkd-parquet", str(pq), "--splice-offsets", str(off),
            "--data-dir", str(tmp_path)]
    if reanchor_only:
        argv.append("--reanchor-only")
    monkeypatch.setattr(sys, "argv", argv)

    if quiet:
        logging.disable(logging.CRITICAL)
    rc = 0
    try:
        U.main()
    except SystemExit as e:                    # một lần từ chối phải kêu ra ngoài
        rc = int(e.code or 0)
    finally:
        logging.disable(logging.NOTSET)
    return before, pq.read_bytes(), json.loads(off.read_text(encoding="utf-8")), rc


def test_a_roll_writes_the_anchor_and_leaves_the_bars_alone(monkeypatch, tmp_path):
    """Ca chính. Hợp đồng đổi -> sổ neo mang độ lệch mới, tệp bar KHÔNG một byte nào đổi."""
    before, after, sidecar, rc = _run_main(
        monkeypatch, tmp_path, stored_contract="NKDU6", fetched_contract="NKDZ6",
        reanchor_only=True)
    assert rc == 0, "neo lại thành công mà báo hỏng — bộ tiền kiểm sẽ dựng một sự cố giả"
    assert after == before, "tệp bar bị ghi trong chế độ chỉ-neo"
    assert sidecar["MNKD"]["contract"] == "NKDZ6", sidecar
    assert sidecar["MNKD"]["offset"] == pytest.approx(530.0), sidecar


def test_no_roll_writes_nothing_at_all(monkeypatch, tmp_path):
    """~246 ngày một năm đi qua đường này. Không sổ neo, không tệp bar, không gì cả."""
    before, after, sidecar, rc = _run_main(
        monkeypatch, tmp_path, stored_contract="NKDU6", fetched_contract="NKDU6",
        reanchor_only=True, med=0.0)
    assert rc == 0, "ngày thường mà báo hỏng thì 246 ngày một năm đều đỏ"
    assert after == before
    assert sidecar == {"MNKD": {"offset": 0.0, "contract": "NKDU6"}}, sidecar


def test_the_same_roll_without_the_flag_still_appends(monkeypatch, tmp_path):
    """Đối chứng. Nếu thiếu nó thì hai phép trên cũng xanh khi `main()` hỏng hoàn toàn và
    chẳng ghi gì trong MỌI chế độ."""
    before, after, sidecar, rc = _run_main(
        monkeypatch, tmp_path, stored_contract="NKDU6", fetched_contract="NKDZ6",
        reanchor_only=False)
    assert rc == 0, rc
    assert after != before, "job 13:45 phải ghi bar — nếu không thì phép đo này vô nghĩa"
    assert sidecar["MNKD"]["contract"] == "NKDZ6", sidecar


def test_a_refused_reanchor_writes_nothing(monkeypatch, tmp_path):
    """Bậc 4,6% giá — quá lớn để là chênh kỳ hạn. Từ chối, và từ chối nghĩa là không ghi
    sổ neo lẫn tệp bar."""
    before, after, sidecar, rc = _run_main(
        monkeypatch, tmp_path, stored_contract="NKDU6", fetched_contract="NKDZ6",
        reanchor_only=True, med=3000.0)
    assert rc != 0, "từ chối mà thoát êm — bộ tiền kiểm đọc mã trả về, nên nó sẽ không thấy"
    assert after == before
    assert sidecar["MNKD"] == {"offset": 0.0, "contract": "NKDU6"}, sidecar


def _log_of(monkeypatch, tmp_path, **kw):
    import logging

    lines: list = []

    class Grab(logging.Handler):
        def emit(self, r): lines.append(r.getMessage() if not r.args else r.msg % r.args)

    h = Grab()
    h.setLevel(logging.DEBUG)
    lg = logging.getLogger("update_ibkr_daily")
    was = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    try:
        _run_main(monkeypatch, tmp_path, quiet=False, **kw)
    finally:
        lg.removeHandler(h)
        lg.setLevel(was)
    assert lines, "không bắt được dòng nhật ký nào — phép kiểm sẽ xanh trên hư không"
    return "\n".join(lines)


def test_the_three_exits_do_not_say_each_others_lines(monkeypatch, tmp_path):
    """Ba trường hợp, ba câu khác nhau. Gộp "không đổi" với "chưa trả lời được" là đúng dạng
    fail-open đã mở toang một chốt chặn trong kho này: `[]` vừa nghĩa là "không có" vừa nghĩa
    là "không đo được", và chốt chọn nghĩa thứ nhất."""
    rolled = _log_of(monkeypatch, tmp_path / "a", stored_contract="NKDU6",
                     fetched_contract="NKDZ6", reanchor_only=True)
    assert "re-anchored NKDU6 -> NKDZ6" in rolled, rolled[-600:]
    assert "unchanged" not in rolled, "đường roll nói câu của ngày thường"

    same = _log_of(monkeypatch, tmp_path / "b", stored_contract="NKDU6",
                   fetched_contract="NKDU6", reanchor_only=True, med=0.0)
    assert "contract unchanged" in same, same[-600:]
    assert "re-anchored" not in same, "ngày thường nói câu của ngày roll"


def test_the_roll_question_never_needs_a_single_shared_bar(monkeypatch, tmp_path):
    """Hai câu hỏi khác nhau, và bản đầu của tôi gộp làm một.

        hợp đồng có đổi không?   ->  đọc TÊN kỳ hạn sàn trả về. Không cần bar nào.
        bậc chênh bao nhiêu?     ->  cần bar chồng lấn.

    Gộp lại thì một buổi sáng thiếu bar chồng lấn trở thành "không biết có roll không", trong
    khi thật ra vẫn biết chắc — chỉ là chưa đo được bậc. Chủ dự án không đoán trước được ngày
    roll, nên "không biết" đúng vào sáng hôm roll là câu trả lời đắt nhất có thể đưa ra.
    """
    log = _log_of(monkeypatch, tmp_path / "d", stored_contract="NKDU6",
                  fetched_contract="NKDZ6", reanchor_only=True, n_overlap=100)
    assert "NKDU6" in log and "NKDZ6" in log, log[-800:]
    assert "could not tell whether the contract rolled" not in log, log[-800:]


def test_a_roll_it_cannot_measure_is_loud_not_silent(monkeypatch, tmp_path):
    """Biết đã roll mà không đo được bậc = biết chắc cửa sổ sắp tới sẽ từ chối.

    Đó là thứ đáng đánh thức người, không phải một dòng INFO rồi thoát 0. Bảng điều khiển
    đọc MÃ TRẢ VỀ, nên thoát 0 làm "chưa ai xác minh" trông hệt "đã xác minh, không sao".
    """
    before, after, sidecar, rc = _run_main(
        monkeypatch, tmp_path, stored_contract="NKDU6", fetched_contract="NKDZ6",
        reanchor_only=True, n_overlap=100)
    assert rc != 0, "một lần roll không đo được mà thoát êm"
    assert after == before
    assert sidecar["MNKD"] == {"offset": 0.0, "contract": "NKDU6"}, sidecar


def test_no_roll_with_few_bars_is_still_a_confident_no(monkeypatch, tmp_path):
    """Mặt kia của cùng một chuyện: ít bar mà hợp đồng trùng thì vẫn là một câu KHÔNG chắc
    chắn, không phải một câu lấp lửng. Ngày thường không được đỏ."""
    before, after, sidecar, rc = _run_main(
        monkeypatch, tmp_path, stored_contract="NKDU6", fetched_contract="NKDU6",
        reanchor_only=True, med=0.0, n_overlap=100)
    assert rc == 0, rc
    assert after == before


def test_the_daily_append_also_refuses_a_roll_it_cannot_measure(monkeypatch, tmp_path):
    """LỖI CÓ SẴN, không phải của chế độ mới.

    Khi thiếu bar chồng lấn, đường ghi hằng ngày chỉ log "alignment unchecked" rồi **vẫn nối
    bar**. Nếu chuỗi đã roll thì đó là nối bar của kỳ hạn khác vào lịch sử — đúng hình dạng
    sự cố 05/08, khi một độ lệch sai được viết vào chuỗi và trôi ba ngày không ai thấy.
    """
    before, after, sidecar, rc = _run_main(
        monkeypatch, tmp_path, stored_contract="NKDU6", fetched_contract="NKDZ6",
        reanchor_only=False, n_overlap=100)
    assert after == before, "đã nối bar của kỳ hạn khác vào lịch sử"
    assert rc != 0


def test_too_few_shared_bars_is_not_read_as_no_roll(monkeypatch, tmp_path):
    """Chốt chặn `scheduler_processes` hỏng theo chiều mở vì `[]` vừa nghĩa là "không có"
    vừa nghĩa là "không đo được", và chốt chọn nghĩa thứ nhất — hai scheduler cùng chạy, sáu
    slot vào lệnh hỏng.

    Bản đầu của phép kiểm này mắc đúng lỗi ấy ở chiều ngược lại: nó ĐÒI câu trả lời phải là
    "không biết" khi thiếu bar. Sai. Thiếu bar chỉ làm không đo được BẬC; tên kỳ hạn vẫn nằm
    đó, nên vẫn biết chắc là đã roll. Điều phải canh là câu trả lời **không được** biến thành
    "không đổi" — và bây giờ nó là một lời từ chối có nêu tên hai kỳ hạn.
    """
    log = _log_of(monkeypatch, tmp_path / "c", stored_contract="NKDU6",
                  fetched_contract="NKDZ6", reanchor_only=True, n_overlap=100)
    assert "CONTRACT ROLLED NKDU6 -> NKDZ6" in log, log[-800:]
    assert "could NOT be measured" in log, log[-800:]
    assert "unchanged" not in log, "một lần roll bị đọc thành không đổi"


def test_the_refusal_names_the_consequence_and_the_way_out(monkeypatch, tmp_path):
    """Một lời từ chối không nói hậu quả là một lời từ chối người ta học cách bỏ qua, và
    một lời từ chối không nói cách thoát thì bắt người trực tự nghĩ ra lúc 09:16 sáng."""
    log = _log_of(monkeypatch, tmp_path / "e", stored_contract="NKDU6",
                  fetched_contract="NKDZ6", reanchor_only=True, n_overlap=100)
    assert "series_rolled" in log, log[-800:]          # hậu quả, gọi đúng tên slot sẽ báo
    assert "--duration" in log, log[-800:]             # cách thoát, chạy được ngay


def test_an_unreadable_contract_name_is_the_only_unanswered_case(monkeypatch, tmp_path):
    """Trạng thái thứ ba, và nguyên nhân của nó là TÊN, không phải số bar. Gộp bất kỳ hai
    trong ba trạng thái này là cách một cổng fail-closed trở thành fail-open."""
    log = _log_of(monkeypatch, tmp_path / "f", stored_contract="",
                  fetched_contract="NKDZ6", reanchor_only=True, med=0.0)
    assert "unanswered" in log, log[-800:]
    assert "unchanged" not in log, log[-800:]


def test_too_few_shared_bars_writes_nothing(monkeypatch, tmp_path):
    before, after, sidecar, rc = _run_main(
        monkeypatch, tmp_path, stored_contract="NKDU6", fetched_contract="NKDZ6",
        reanchor_only=True, n_overlap=100)
    assert after == before
    assert sidecar["MNKD"] == {"offset": 0.0, "contract": "NKDU6"}, sidecar


def test_the_closing_summary_says_what_actually_happened(monkeypatch, tmp_path, capsys):
    """Dòng tổng kết cũ in "ALL 5 INSTRUMENTS UPDATED" sau một lượt chỉ-neo không nối một bar
    nào — và vào ngày thường thì không ghi cả sổ neo. Người vận hành đọc đúng dòng ấy để
    quyết định buổi sáng có sạch hay không."""
    _run_main(monkeypatch, tmp_path / "g", stored_contract="NKDU6",
              fetched_contract="NKDU6", reanchor_only=True, med=0.0)
    out = capsys.readouterr().out
    assert "ANCHORS UNCHANGED" in out, out[-400:]
    assert "INSTRUMENTS UPDATED" not in out, out[-400:]

    _run_main(monkeypatch, tmp_path / "h", stored_contract="NKDU6",
              fetched_contract="NKDZ6", reanchor_only=True)
    out = capsys.readouterr().out
    assert "RE-ANCHORED" in out and "MNKD" in out, out[-400:]
    assert "INSTRUMENTS UPDATED" not in out, out[-400:]


def test_the_daily_append_keeps_its_own_summary(monkeypatch, tmp_path, capsys):
    """Đối chứng: đường ghi hằng ngày vẫn nói câu cũ, vì nó thật sự có nối bar."""
    _run_main(monkeypatch, tmp_path / "i", stored_contract="NKDU6",
              fetched_contract="NKDZ6", reanchor_only=False)
    out = capsys.readouterr().out
    assert "INSTRUMENTS UPDATED" in out, out[-400:]
