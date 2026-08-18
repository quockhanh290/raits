"""
global_index/run_stop_repair.py — quét sửa stop trong những giờ không có slot nào
=================================================================================
Dựng một `FuturesRunner` rồi thoát. Không sinh tín hiệu, không vào lệnh, không thoát
lệnh: `signal_fn` trả rỗng và job này không gọi `run_day` cũng không gọi
`run_maxhold_exit`. Toàn bộ tác dụng nằm ở B1–B5, vốn chạy trong `__init__`.

── Vì sao cần ────────────────────────────────────────────────────────────────
B4 làm hai việc gộp một:

  * **vũ trang lần đầu** — đặt cái stop đã được cố tình hoãn. Việc này theo sleeve, và
    `_stop_deferred` là cái quyết định. Job này KHÔNG can thiệp: vị từ vẫn chặn, nên một
    lần chạy lúc 20:00 ET không vũ trang sớm vị thế Rổ 4 mở cùng ngày.
  * **sửa chữa** — đặt lại stop cho vị thế đã qua cửa sổ hoãn mà mất stop (bị sàn từ chối,
    bị huỷ tay, id trỏ vào lệnh đã chết). Việc này KHÔNG theo sleeve và càng sớm càng tốt.

Việc sửa chữa cho tới nay chỉ đi ké các slot dựng runner, mà lịch slot được dựng cho việc
VÀO LỆNH — 14:00–15:55 ET cho Rổ 4, 14:00–15:55 JST cho NKD, cộng 09:31 cho MAX_HOLD. Đo
khoảng trống giữa chúng:

    15:55 → 01:10   9h15      ← tệ nhất, và đúng cái đêm stop sinh ra để bảo vệ
    02:55 → 09:31   6h36
    09:31 → 14:05   4h34

Không ai chọn con số 9h15; nó là hệ quả. Một vị thế Rổ 4 mất stop lúc 16:00 chạy trần suốt
phiên tối Mỹ và cả phiên Á.

── Giá phải trả, đã cân ──────────────────────────────────────────────────────
Mỗi lần chạy là một kết nối IBKR nữa và một lượt B3 nữa, tức thêm một cơ hội dính B3
MISMATCH giả và halt entry. Ngoài cửa sổ vào lệnh thì halt không tốn gì — và ba khoảng trống
trên đều nằm ngoài cả hai cửa sổ, nên đó chính là lý do job này chỉ chạy ở đó.

`_b3_halt_entries` là thuộc tính của runner, không ghi xuống đĩa, và mỗi lần chạy là một
tiến trình riêng — nên một lần halt ở đây không theo sang slot giao dịch.

Chạy như một job TRONG scheduler, không phải CLI rời: nó dùng chung `_slot_lock` nên không
tranh chấp `live_positions.json` với slot khác. Đó cũng là khác biệt với `repair_stops.py`,
vốn tự khai "dừng scheduler trước khi chạy với --execute".

Usage:
    cd d:\\raits
    python -m global_index.run_stop_repair [--port 4002] [--dry-run]
"""
from __future__ import annotations
import argparse
import atexit
import logging
import sys
import time
from pathlib import Path

_CWD = Path.cwd()
if not ((_CWD / "global_index").is_dir() and (_CWD / "futures").is_dir()):
    sys.stderr.write(
        f"CWD guard FAIL: got {_CWD}\n"
        f"  Expected d:\\raits. Fix: cd d:\\raits && python -m global_index.run_stop_repair\n"
    )
    sys.exit(1)
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from futures.basket import RISK
from futures.circuit_breaker import CircuitBreaker
from global_index.ibkr_broker import IBKRBroker
from global_index.net_exposure_multi import MultiClusterGuard
from global_index.runner import (FuturesRunner, RunnerLockError, STOP_FILE_NAME,
                                 _acquire_lock, _release_lock)

ACCOUNT = float(RISK["account"])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_stop_repair")


def main() -> int:
    ap = argparse.ArgumentParser(description="Quét sửa stop ngoài giờ có slot")
    ap.add_argument("--positions-path", default="live_positions.json")
    ap.add_argument("--stop-path", default=STOP_FILE_NAME,
                    help="D5 kill switch: entries skipped while this file exists. This "
                         "job takes no entries, but a path that ignores the switch is "
                         "the defect H2 describes (OPERATIONS.md:89)")
    ap.add_argument("--port", type=int, default=4002)
    # 1, trùng runner — cùng lý do với run_maxhold_exit. B4 trong job này ĐẶT stop; nếu đặt
    # bằng một id khác thì sau này runner (id 1) sẽ không huỷ được chính stop đó khi đóng vị
    # thế. Mọi tiến trình chạm tới STP phải dùng CHUNG một clientId.
    ap.add_argument("--client-id", type=int, default=1,
                    help="BAT BUOC trùng clientId của run_live_day (1). IBKR chỉ nhận lệnh huỷ "
                         "từ chính clientId đã đặt lệnh, nên một id khác KHÔNG BAO GIỜ huỷ "
                         "được STP do runner đặt — xem OPERATIONS.md muc 'clientId'.")
    ap.add_argument("--lock-path", default="runner.pid",
                    help="PID lockfile (E1 duplicate-runner guard). Cùng mặc định với "
                         "run_live_day và run_maxhold_exit — ba entry point phải dùng "
                         "CHUNG một tệp, nếu không thì mỗi cái tự khoá mình.")
    ap.add_argument("--dry-run", action="store_true",
                    help="chỉ báo cáo; KHÔNG dựng runner nên B4 không đặt lệnh nào")
    a = ap.parse_args()

    pos_path = Path(a.positions_path)
    if not pos_path.exists():
        log.info("Không có %s — không có gì để sửa.", pos_path)
        return 0

    now = pd.Timestamp.now(tz="America/New_York").tz_localize(None)
    log.info("STOP REPAIR SWEEP — %s ET", now.strftime("%Y-%m-%d %H:%M"))

    # ── E1 lock TRƯỚC khi nối ────────────────────────────────────────────────
    # Guard E1 vốn chỉ run_live_day dùng; job này và MAX_HOLD chạy trần, và cả ba nối
    # trên clientId 1. Mutex trong run_scheduler là `threading.Lock` nên chỉ thấy các
    # slot trong CÙNG một tiến trình — hai scheduler thì hai khoá riêng, không ai biết
    # ai. Khoá tệp PID thì thấy.
    #
    # Khác MAX_HOLD: bỏ qua ở đây chấp nhận được, vì quét sửa là idempotent và lượt sau
    # cách 2 tiếng sẽ làm đúng việc lượt này định làm — cùng lý lẽ `_run_guarded` đã
    # dùng để bỏ qua job này. Nên WARNING và thoát 0, không phải lỗi.
    if a.lock_path:
        try:
            _acquire_lock(Path(a.lock_path))
            # Trả khoá trên MỌI đường thoát, kể cả khi `broker.connect()` ném.
            #
            # run_live_day truyền `lock_path` vào FuturesRunner và runner tự đăng ký
            # `atexit.register(_release_lock, ...)`; hai entry point này giành khoá thủ
            # công nên không ai đăng ký gì, và bản vá đầu tiên của tôi bỏ hẳn phần trả.
            # Đo được ngay đêm nó lên: STOP_REPAIR_0420 chạy xong lúc 02:20:11 và để
            # lại `runner.pid` mang PID 43248 đã chết.
            #
            # Bản sửa thứ hai đặt lời gọi trong `finally` của khối làm việc — vẫn hụt,
            # vì khoá được giành TRƯỚC `broker.connect()`, nên một lần nối hỏng thì
            # không bao giờ tới `finally`. Đó đúng là ca đã xảy ra. atexit phủ hết.
            atexit.register(_release_lock, Path(a.lock_path))
        except RunnerLockError as exc:
            log.warning("[lock] %s — bo qua luot quet nay; luot sau se lam. "
                        "Khong phai loi: quet sua la idempotent.", exc)
            return 0

    broker = IBKRBroker(host="127.0.0.1", port=a.port, client_id=a.client_id)
    broker.connect()
    time.sleep(5)          # để IB Gateway ổn định farm connection
    try:
        if a.dry_run:
            # Không dựng runner: B4 nằm trong __init__ nên dựng nó LÀ hành động.
            # Báo cáo bằng phép kiểm chỉ-đọc, đúng cái B5 dùng.
            try:
                unprot = broker.unprotected_positions()
            except Exception as exc:
                log.error("unprotected_positions() lỗi: %s", exc)
                return 1
            if unprot is None:
                log.info("[dry-run] broker không trả lời được — không kết luận.")
            elif not unprot:
                log.info("[dry-run] mọi vị thế đều được phủ stop trên đúng hợp đồng.")
            else:
                for u in unprot:
                    log.warning("[dry-run] TRẦN: %s x%+d hợp đồng %s (phủ %d)",
                                u["inst"], u["qty"], u["expiry"], u.get("covered", 0))
            return 0

        runner = FuturesRunner(
            broker=broker,
            guard=MultiClusterGuard(account=ACCOUNT),
            contracts_by_inst={},                  # không dùng — job này không vào lệnh
            signal_fn=lambda d, b, h: ([], []),    # rỗng: không entry, không exit
            breaker=CircuitBreaker(account=ACCOUNT),
            positions_path=pos_path,
            # Job này không vào/ra lệnh, nhưng B3 chạy trong __init__ và ĐƯỢC PHÉP ghi
            # sổ: khi nó thấy một stop đã khớp, `_record_stop_exit` book tiền và ghi
            # dòng CLOSE. Thiếu đường dẫn thì `_append_trade_raw` trả về ngay, nên lượt
            # quét vẫn chuyển tiền vào sổ vốn mà không để lại dòng nào — cùng lỗ hổng
            # vừa đo được ở max-hold ngày 2026-08-17.
            trade_log_path=str(_CWD / "trade_log.jsonl"),
            stop_path=a.stop_path,        # D5 — see RUNNER_AUDIT.md H2
            # today/now truyền tường minh: runner sẽ tự đọc đồng hồ nếu thiếu, và hai khái
            # niệm "hôm nay" trong một lần chạy là cách cửa sổ hoãn bị tính sai.
            today=now.normalize(),
            now=now,
        )
        naked = list(getattr(runner, "_b4_naked_stops", []))
        if naked:
            # [BOOKED]: placing a stop is a change on the exchange, and WARNING is not
            # enough to survive — the scheduler keeps only CRITICAL/ERROR from a child
            # that exited 0, and this job has no log file of its own.
            log.warning("[BOOKED] B4 đã xử lý %d vị thế thiếu stop: %s", len(naked), naked)
        else:
            log.info("Không vị thế nào thiếu stop.")
        return 0
    finally:
        broker.disconnect()
        log.info("[ibkr] Đã ngắt kết nối.")


if __name__ == "__main__":
    sys.exit(main())
