# Daily Update Runbook — Futures Paper Trading

_Cập nhật: 2026-07-12_

> **Bài học:** Futures thiếu backup frozen → baseline $52,936 không tái tạo. Rule #1: frozen = ĐÓNG BĂNG, backup external, không đụng.

---

## Ranh giới Frozen / Live

```
FROZEN (đóng băng, không bao giờ update)     LIVE (append-only hằng ngày)
──────────────────────────────────────────   ────────────────────────────
*_frozen_2024.parquet  (baseline/vault 24)   *_8y.parquet   ← ibkr_daily appends đây
*_frozen_2025.parquet  (vault 2025)          spy_daily_live.csv  ← update_spy_csv appends đây
NKD_frozen_*.parquet
frozen_sim/            (shim, deploy_sim)
frozen_2025_sim/       (shim, deploy_sim)
spy_daily.csv          (frozen/sacred)
```

**Code load đúng nguồn:**
- `deploy_sim --data-dir data/cache/futures/frozen_sim` → dùng baseline frozen
- `run_live_day` → dùng `*_8y.parquet` (live-updated)
- KHÔNG BAO GIỜ `deploy_sim --data-dir data/cache/futures` để verify vault (lẫn live + frozen)

---

## Quy trình hằng ngày (mỗi ngày paper)

### Bước 1 — Append futures bars (sau 17:30 ET hôm qua settled)

```powershell
cd d:\raits
# IB Gateway phải đang chạy port 4002 (paper)
python -m global_index.update_ibkr_daily --dry-run   # kiểm tra trước
python -m global_index.update_ibkr_daily              # thật
```

**Verify sau:**
- Script tự kiểm history invariant (200 bars cuối). Nếu log `HISTORY INVARIANT VIOLATED` → STOP, không dùng data đó.
- Output sẽ in last bar của từng instrument sau update → phải là hôm qua.

**Nếu fail (IBKR không kết nối được):**
- Thử lại sau khi IB Gateway ổn định
- Ngày hôm sau chạy `--duration "5 D"` để catch up

---

### Bước 2 — Update SPY regime labels

```powershell
cd d:\raits
python -m global_index.update_spy_csv --csv spy_daily_live.csv
```

**Verify sau:**
- Script tự snapshot (`spy_snapshots/`) trước khi update
- Script tự verify historical prices 2018-2024 bất biến. Nếu log `WARNING` về price thay đổi → Polygon revise → so sánh snapshot vs new, điều tra trước khi dùng
- Nếu labels 2018-2024 đổi → HMM retrain có thể cho regime khác → NOTE nhưng không phải emergency (regime forward-looking, không retroactive ảnh hưởng vault)

---

### Bước 3 — Chạy live signal (14:05 ET, qua APScheduler)

```powershell
# APScheduler đã schedule — không cần chạy tay nếu run_scheduler đang chạy
# Manual nếu cần:
python -m global_index.run_live_day --port 4002
```

---

## Rollback nếu update sai

### Futures parquet bị corrupt / sai
```powershell
# 1. Xác định instrument bị lỗi (ví dụ MES):
python -m global_index.verify_frozen verify   # frozen intact?

# 2. Nếu chỉ *_8y.parquet bị lỗi (live file, không phải frozen):
#    Copy lại từ frozen:
copy "data\cache\futures\ES_frozen_2024.parquet" "data\cache\futures\ES_continuous_1m_8y.parquet"
#    Sau đó re-append từ IBKR với --duration "30 D" để fill gap

# 3. Nếu frozen bị lỗi → restore từ external backup (xem verify_frozen)
```

### SPY CSV bị lỗi
```powershell
# Snapshots có tên trong spy_snapshots/
ls spy_snapshots\
# Restore:
copy "spy_snapshots\spy_daily_live_snapshot_YYYYMMDD.csv" spy_daily_live.csv
```

---

## Kiểm tra định kỳ

### Weekly (mỗi tuần 1 lần — full SHA-256)

```powershell
cd d:\raits
python -m global_index.verify_frozen verify
```

Tại sao cần: startup size-only (<0.1s) bắt file mất/sai-size, NHƯNG không bắt **byte-level corruption
cùng size** (bars đổi giá trị, số bytes ngẫu nhiên không đổi). Full SHA-256 bắt cái này.

Nếu có lỗi: so sánh với external backup, restore từ `E:\raits_backup\frozen`.

---

### Trước mỗi re-freeze hoặc major update

```powershell
cd d:\raits
# Verify tất cả frozen intact:
python -m global_index.verify_frozen verify

# Verify baseline vẫn reproduce:
python -m global_index.deploy_sim \
  --data-dir data/cache/futures/frozen_sim \
  --nkd-parquet global_index/data/NKD_frozen_2024.parquet \
  --regime-csv spy_daily_live.csv \
  --end 2024-12-31 --n-contracts 1 --slippage-ticks 2
# Expected: net=$40,919, Calmar=1.66 (±$5 float rounding OK)
```

---

## KHÔNG làm (anti-patterns)

| KHÔNG | Thay bằng |
|---|---|
| `update_futures_data.py` để update hằng ngày | `update_ibkr_daily.py` (append-only) |
| `update_futures_data.py --full-refetch` mà không backup | Verify frozen trước, backup external, rồi mới chạy với `--i-confirmed-frozen-backup` |
| Chạm vào `*_frozen_*.parquet` | Không bao giờ |
| `deploy_sim --data-dir data/cache/futures` (live dir) cho baseline | `--data-dir data/cache/futures/frozen_sim` |
| Xóa `spy_snapshots/` | Giữ, snapshots phục vụ rollback |

---

## External Backup (chạy 1 lần khi setup + sau mỗi freeze mới)

```powershell
cd d:\raits
# Tạo manifest (commit to git):
python -m global_index.verify_frozen create
git add data/frozen_manifest.json
git commit -m "data: frozen manifest YYYY-MM-DD"

# Copy ra ổ ngoài (thay E:\raits_backup bằng path thực):
python -m global_index.verify_frozen backup --dest "E:\raits_backup\frozen" --execute

# Verify sau khi backup:
python -m global_index.verify_frozen verify
```

**Backup gồm (primary, irreplaceable):**
- `{ES,NQ,YM,RTY}_frozen_2024.parquet` — 4 files ~170MB
- `{ES,NQ,YM,RTY}_frozen_2025.parquet` — 4 files ~193MB
- `NKD_frozen_2024/2025.parquet` — 2 files ~48MB
- `spy_daily.csv`, `spy_daily_live.csv`, `spy_snapshots/`

**Total: ~420MB primary frozen** (+ shim dirs tùy chọn)
