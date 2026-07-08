# Futures — Scaling Plan
_Hướng + điều kiện. Chi tiết hóa SAU paper (paper đổi giả định). 2026-07-08_

---

## Trạng thái hiện tại: n=1 ceiling ✓

n=1 @ $55,784 — Calmar 2.76 > floor 2.38 ✓. Không có vấn đề gì với ceiling này.  
Scale chưa cấp thiết. Không tối ưu sớm.

---

## Tại sao n=2 không khả thi trực tiếp

**Structural** (từ SCALING_ANALYSIS.md):  
`capacity = (pct × account) / (n × mult × ATR × PV)` — mẫu số tăng 2× khi n tăng, tử số không đổi.  
→ cap rejection tăng tại mọi account level. P&L tăng 1.08×, DD tăng 1.31× → Calmar giảm.

**Ba ngưỡng mâu thuẫn:**
- Sizer auto-select n=2 cần ~$58-59k (ước tính tự tham chiếu, chưa đo chính xác; $55,784 sai)
- Calmar n=2 IS = 2.28 < floor 2.38 → gate fail
- Không tồn tại account level thoả cả ba

---

## Ba nhánh scaling (khi cần, sau paper)

### A — cap×n: nới cluster cap cùng n
Tư tưởng: `cluster_cap = pct × account × n` → capacity giữ nguyên → cap rejection biến mất.

Điều kiện trước khi thực thi:
1. Đo: implement cap×n → chạy deploy_sim → Calmar n=2 với cap mới có giữ ≥ 2.38 không?  
   (MaxDD có thể >2× nếu concurrent tăng — chưa verify)
2. Nếu Calmar ổn → vault OOS n=2 (cap mới) → GO → deploy

Lưu ý: đây là thay đổi risk parameter (gross exposure tăng 2×) → **bắt buộc re-vault**.

### B — Thêm instrument (giữ n=1, diversify)
Thay vì scale concentration, thêm micro-index / international futures mới.

Điều kiện:
- Gate 0-4 đầy đủ cho instrument mới (như Rổ4, NKD)
- n=1 per instrument → capacity tăng, Calmar stable, không phá baseline hiện tại

Ưu điểm: không đụng cap parameter → không cần re-vault Rổ4/NKD.

### C — n=1 ceiling (không scale)
Chấp nhận capacity limit. Account lớn → return% giảm dần, Calmar stable.  
Default nếu A/B không justified sau paper.

---

## Điều kiện chung (mọi nhánh)

- **Vault OOS trước deploy** — không nhánh nào bypass (sizer bug pattern: đổi config không validate = GO giả).
- **Chi tiết hóa sau paper** — paper cho số Calmar thật → xác định nhánh nào đáng implement.
- **Không làm bây giờ**: không implement cap×n vào production, không chi tiết execution.

---

## Nguồn

`docs/futures/SCALING_ANALYSIS.md` — đo thật, data table, root cause structural, threshold recompute.
