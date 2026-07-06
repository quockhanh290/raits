# Play Backtest — Proposal

## Core Insight

Play = `setInterval(() => { selectedIdx++; updateDayView(); equityChart.update('none'); }, delay)`

`updateDayView()` đã sync mọi panel từ `selectedIdx` duy nhất. Không cần panel mới, không cần backend ghi thêm data.

---

## 1. Data đủ không?

**Đủ hoàn toàn.** Mỗi snapshot có:
- `date / equity / drawdown_pct / breaker_level / regime`
- `decision.entries[]` — trade mở ngày đó
- `decision.exits[]` — trade đóng ngày đó (pnl, exit_reason)
- `decision.rejected_detail[]`
- `open_positions[]`, `running_metrics`, `per_cluster_pnl`
- `meta.breaker_events[]` — halt events với date + dd_pct → synthesize GUARD log events

---

## 2. Play Controls

Mở rộng `#slider-container` hiện có (dưới chart):

```
[▶ PLAY]  [1×▾]  [━━━━●━━━━━━━━━━]  Day 47 / 1590 — 2018-03-15
```

- `▶ PLAY` / `⏸ PAUSE` toggle
- Speed: `1×` = 600ms/day · `2×` = 300ms · `5×` = 120ms · `10×` = 60ms
- Slider giữ nguyên làm scrubber — drag để seek, play resume từ vị trí mới
- Tự dừng ở last snapshot

---

## 3. Trade Events — không cần panel mới

| Panel đã có | Role khi play |
|---|---|
| **Today's Decision** | Live trade feed: entries/exits/rejected ngày đang play |
| **Closed Trades** table | Grow dần theo `_idx <= selectedIdx` |
| **Operational Log** (sidebar) | Nhận GUARD/STATE events — TÁCH khỏi trade detail |

---

## 4. Operational Log khi play

Synthesize từ data sẵn có (build 1 lần trong `precompute()`):

| Nguồn | Level | Category | Event |
|---|---|---|---|
| `meta.breaker_events[]` | CRITICAL | GUARD | Circuit breaker HALT — DD X.X% |
| `snap[i].regime !== snap[i-1].regime` | INFO | STATE | Regime changed: Normal → Stress |

Push vào log khi play đến ngày có event. Không cần backend.

ORDER events (filled/rejected/partial): **rỗng trong backtest** — đúng và expected.

---

## 5. Mode Badge

Thêm class `mode-backtest` (purple):

| Trạng thái | Badge |
|---|---|
| Idle / end | `REPLAY` (blue) |
| Đang play | `▶ BACKTEST` (purple + pulse nhẹ) |
| Paused giữa chừng | `⏸ PAUSED` (muted) |

---

## 6. Scope

**UI-only, không cần backend:**
- Play/pause/speed controls
- Timer auto-advance `selectedIdx`
- Mode badge 3 states
- Synthetic log events (breaker halt + regime change)

**Ước lượng:** ~80 lines JS + ~20 lines HTML/CSS. Không thay đổi backend, không thêm panel.

---

## 7. Không làm

- Panel trade feed mới — Today's Decision đã đủ
- Backend ghi thêm — data replay_snapshots_data.js sẵn có đủ
- ORDER category trong backtest — không có real orders, để trống là đúng