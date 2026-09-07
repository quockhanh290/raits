"""Lưới an toàn của tuyến cũ nghỉ hưu ở chế độ chỉ-Track-1. TỆP MỚI.

Vì sao gỡ, và vì sao chỉ gỡ ở MỘT chế độ
----------------------------------------
Mười một lượt quét của tuyến cũ canh `live_positions.json`. Lý do giữ chúng từng đúng: bỏ đi
là để một vị thế còn mở trong sổ ấy không có ai sửa lệnh dừng và không có lượt thoát năm ngày.

Điều kiện đó đã hết. Đo ngày 2026-09-06: sổ giữ 0 vị thế và không đổi từ 04/09; bản rà B1 báo
môi giới phẳng, không lệnh nào đang treo; và 45 slot chiến lược của tuyến cũ vốn đã không còn
được đăng ký ở chế độ này.

Giữ tiếp thì có giá. Mỗi lượt quét vẫn kết nối và đối chiếu vị thế môi giới với sổ của chính
nó — mà môi giới KHÔNG lọc theo tuyến, đó là toàn bộ nội dung của B1: một login là một sổ vị
thế. Nên mọi vị thế Track 1 mở ra đọc vào chúng như một vị thế không có mục nào khớp trong
file, và nhánh đó ghi CRITICAL "B3 ORPHAN ... vị thế mở ngoài runner này?". Bộ lập lịch nâng
CRITICAL của tiến trình con thành sự cố, nên mười lượt một ngày là mười sự cố giả, kéo dài
suốt thời gian Track 1 còn giữ vị thế — bắt đầu từ lệnh đầu tiên, đúng ngày bảng điều khiển
cần được tin nhất.

Hai chế độ kia KHÔNG đổi, và đó là nửa quan trọng của bản sửa: ở chế độ mặc định và chế độ
chuyển tiếp, tuyến cũ vẫn có thể giao dịch, và các lượt quét ấy là thứ duy nhất canh nó.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_slots as ts                     # noqa: E402

PORT = 4002


def _ids(**kw) -> set:
    """Job id mà bộ lập lịch thật sự đăng ký. Dựng chứ không khởi động."""
    logging.disable(logging.CRITICAL)
    try:
        from global_index.run_scheduler import make_scheduler

        sched = make_scheduler(port=PORT, dry_run=True, **kw)
        try:
            return {j.id for j in sched.get_jobs()}
        finally:
            try:
                sched.shutdown(wait=False)
            except Exception:
                pass
    finally:
        logging.disable(logging.NOTSET)


@pytest.fixture(scope="module")
def legacy_mode():   return _ids()


@pytest.fixture(scope="module")
def transitional():  return _ids(track1_shadow=True)


@pytest.fixture(scope="module")
def track1_only():   return _ids(track1_shadow=True, track1_only=True)


@pytest.fixture(scope="module")
def legacy_safety():
    s = ts.legacy_safety_retirement_candidates(PORT, track1_shadow=True)
    assert s, "danh sách rỗng — mọi phép kiểm dưới đây sẽ pass mà không kiểm gì"
    return s


# ── nghỉ hưu, ở đúng một chế độ ──────────────────────────────────────────────

def test_the_retiring_routes_sweeps_are_gone_from_track1_only(track1_only, legacy_safety):
    left = legacy_safety & track1_only
    assert not left, f"còn {len(left)} lượt quét của tuyến cũ: {sorted(left)}"


def test_they_are_untouched_in_the_default_mode(legacy_mode, legacy_safety):
    """Chế độ mặc định là tuyến cũ chạy thật. Gỡ ở đây là bỏ vị thế không ai canh."""
    assert legacy_safety <= legacy_mode, (
        f"thiếu {sorted(legacy_safety - legacy_mode)} ở chế độ mặc định")


def test_they_are_untouched_in_the_transitional_mode(transitional, legacy_safety):
    """Chế độ chuyển tiếp: cả hai tuyến cùng chạy, tuyến cũ vẫn có thể mở vị thế."""
    assert legacy_safety <= transitional, (
        f"thiếu {sorted(legacy_safety - transitional)} ở chế độ chuyển tiếp")


# ── thứ thay thế phải có mặt ─────────────────────────────────────────────────

def test_track1_keeps_its_own_safety_net(track1_only):
    """Gỡ một lưới thì lưới kia phải còn. Không có phép kiểm này, bản sửa có thể bỏ
    protection của CẢ HAI tuyến mà mọi assert ở trên vẫn xanh."""
    own = {j for j in track1_only if j.startswith(("track1_stop_repair", "track1_maxhold"))}
    assert len(own) == len(ts.track1_safety_jobs()) == 11, sorted(own)


def test_shared_infrastructure_survives(track1_only):
    shared = set(ts.SHARED_INFRA_JOBS)
    missing = shared - track1_only
    assert not missing, f"hạ tầng dùng chung bị gỡ nhầm: {sorted(missing)}"


# ── hai khái niệm nghỉ hưu không được lẫn ────────────────────────────────────

def test_retiring_the_strategy_does_not_retire_protection(legacy_safety):
    """Hai danh sách phải rời nhau.

    Gộp chúng lại là để một lời gọi "dừng giao dịch của tuyến cũ" âm thầm bỏ luôn phần bảo
    vệ — hai quyết định với hai điều kiện khác nhau, đi chung một cái tên.
    """
    strategy = ts.legacy_retirement_candidates(PORT, track1_shadow=True)
    assert strategy, "danh sách chiến lược rỗng — phép kiểm không kiểm gì"
    assert not (strategy & legacy_safety), sorted(strategy & legacy_safety)


def test_surviving_jobs_still_answers_about_strategy_only(legacy_safety):
    """`surviving_jobs` trả lời câu "nghỉ hưu chiến lược để lại gì", nên nó vẫn phải
    chứa các lượt quét. Đổi nghĩa của nó là đổi câu trả lời cho mọi caller cũ."""
    surviving = ts.surviving_jobs(PORT, track1_shadow=True)
    assert legacy_safety <= surviving, sorted(legacy_safety - surviving)


# ── bảng phân loại phải đầy đủ ───────────────────────────────────────────────

def test_no_registered_job_is_unclassified():
    """Một job không ai đặt tên thì không nhóm nào sở hữu — và job SPY chiều Chủ nhật đã
    nằm ở đó từ lúc nó ra đời, nên nó không bao giờ được gọi là hạ tầng dùng chung."""
    for shadow in (False, True):
        c = ts.route_classification(PORT, track1_shadow=shadow)
        assert c["unclassified"] == [], (shadow, c["unclassified"])


def test_the_sunday_spy_job_is_shared_infrastructure():
    c = ts.route_classification(PORT, track1_shadow=True)
    assert "spy_weekend_pre_nkd_check" in c["shared_infra"], c["shared_infra"]
