# Giải phẫu từng section

Phụ lục của `DESIGN_SPEC.md`. Spec kia nói token và pattern dùng chung; file này
nói **từng section một** — cấu trúc, giá trị, và *lý do* nó được dựng như vậy.

Đọc cùng `DESIGN_SPEC.md` mục 1 (token) và mục 3 (pattern lặp lại). Ở dưới, khi
viết `label` / `secondary` / `primary` / `null` / `divider` là đang trỏ về bảng
token đó, không phải màu tự chọn.

Ký hiệu: `→` nghĩa là `margin-left:auto` (đẩy sang phải).

---

# Khung ngoài

## Header

```
flex; align-items:center; justify-content:space-between; gap:32px
padding:12px 22px; border-bottom:1px solid #1b2027
├── trái  flex gap:14px
│   ├── "RAITS FUTURES"  sans 13px/600 .15em uppercase primary
│   └── badge PAPER·NEXT  mono 10px .12em, padding 3px 9px,
│                          border 1px #262d36, radius 4px, fg label
├── giữa  flex gap:4px — nav 4 mục, mỗi mục padding 7px 16px
│   đang mở: radius 5px, bg #14251f, fg #8ae6cc
│   còn lại: không nền, fg label
│   cả bốn: sans 12px/500 .06em uppercase
└── phải  flex gap:22px, mono 12px label
    ├── ngày  fg primary
    ├── dot 6px #3ecf8e + animation lp 2.4s + "Live" primary + "updated 6s ago"
    └── dot 6px #3ecf8e + "On schedule · next 14:35 ET"
```

`@keyframes lp { 0%,100%{opacity:1} 50%{opacity:.32} }` — **chỉ** dot Live nhấp
nháy. Dot "On schedule" tĩnh: nó là trạng thái, không phải nhịp tim.

## Status band

```
flex; align-items:center; gap:16px; padding:11px 22px
border-bottom:1px solid #1b2027
background:linear-gradient(90deg,#0c1512 0%,#0b0d11 42%)
├── dot 7px + "OK" mono 11px .1em #8ae6cc
├── câu trạng thái  sans 15px/500 -.005em primary
├── chip "2 ISSUES OPEN"  mono 11px .06em, padding 3px 9px,
│                          border 1px #262d36, radius 4px, fg label
└── → khối phải, text-align:right, mono
    ├── giờ ET  14px primary
    └── các zone khác  11px label, margin-top 2px
```

Gradient dừng ở 42% — nó nhuộm phần *trạng thái*, không nhuộm phần đồng hồ. Màu
đáy gradient đổi theo mức: xanh `#0c1512` khi OK, hổ phách khi watch, đỏ khi bad.

---

# 01 · OPERATIONS

## Now Monitor

Accent section: `#5b9cf0`. Padding section: `16px 22px` (chặt hơn các section
khác vì nó đứng ngay dưới group band).

**Heading:** vạch accent + "Now Monitor" + `dot 6px #3ecf8e` & "CLEAR" mono 10px
`.14em` label + → "0 incident · 0 telemetry gap" mono 11px label.

**Hàng lịch — 4 cell, mỗi cell MỘT dòng:**

```
card, grid-template-columns:repeat(4,1fr), overflow:hidden
mỗi cell:
  flex; align-items:baseline; gap:9px; min-width:0
  padding:8px 14px
  border-right:1px solid #1a1f26
  border-left:2px solid <hue>          ← vạch màu bên TRÁI
  ├── nhãn   sans 10px/500 .11em uppercase, fg = <hue>
  ├── tên    mono 12px primary, ellipsis, min-width:0
  ├── →  giờ mono 11px label
  └── khoảng cách  mono 11px secondary
```

Bốn hue, mỗi cell một màu riêng: `#5b9cf0` · `#9d8cf5` · `#3a6ea8` · `#6b5cb8`.

> **Vì sao vạch bên trái, không phải bên trên:** bốn accent xếp ngang ở cạnh trên
> đọc thành *một* đường kẻ bị đứt. Ở cạnh trái, mỗi vạch nằm cạnh nhãn nó thuộc về.
>
> **Vì sao một dòng:** bản trước xếp dọc (nhãn → tên → giờ+khoảng cách) và cao
> ~80px. Một dòng cao ~34px, cùng lượng thông tin.

**Khối list + detail (grid `352px 1fr`, gap 14px, margin-top 12px):**

Card trong list — `border 1px #171b22`, `border-left:2px solid <accent>`,
radius 8px, bg `#0b0d11`, padding `9px 12px`:
- hàng badge: badge component mono 9px `.12em` padding `2px 7px` border `1px #2a323d` radius 3px → giờ mono 11px label
- tiêu đề sans 13px primary, margin-top 7px, `text-wrap:pretty`

Card detail — card chuẩn, padding `11px 15px`, **`align-self:start`** (không kéo
cao bằng list):
- dot 6px + tiêu đề sans 14px/500 → giờ mono 11px label
- câu sans 13px secondary, margin-top 9px
- grid `1fr 1fr` gap `0 20px`, margin-top 12px, padding-top 11px, border-top divider — hai khối Impact | Action: nhãn sans 11px/500 `.1em` uppercase label + câu sans 13px secondary
- evidence mono 11px null, margin-top 11px

## Open Issues

Accent `#5b9cf0`, padding `18px 22px`. Cùng grid `352px 1fr` như Now Monitor.

Card trong list **bấm được**: `cursor:pointer`, `style-hover` đổi
`border-color:#2a323d`. Đang chọn: bg `#0f1319`, border `#232c3d`. Không chọn:
bg `#0b0d11`, border `#171b22`.

Hàng badge có **hai** badge (kind + state) + → số lần `10x` mono 11px label.
Tiêu đề sans 13px/**600** `-.005em`. Dòng cuối "last …" mono 11px label.

Card detail có **năm khối, chia bằng vạch trong — không lồng card:**

```
header   padding 11px 16px, border-bottom divider
         badge kind · badge state · tiêu đề sans 15px/600 · → occurrences
Problem  padding 12px 16px, border-bottom divider
         nhãn + câu sans 14px primary + window mono 11px label
Impact|Action  grid 1fr 1fr, border-bottom divider
         mỗi ô padding 12px 16px, ô trái thêm border-right divider
Evidence padding 12px 16px, background #0b0d11
         nhãn + mono 11px secondary line-height 1.75
         + "closes when" mono 11px label margin-top 9px
```

> Evidence dùng `line-height:1.75` — cao hơn phần còn lại. Nó là log, đọc theo
> dòng, không đọc theo câu.

## Track 1 Runtime

Accent `#e0913c`. Card chứa grid `repeat(4,1fr)`, 8 ô:

```
mỗi ô  padding:11px 15px
       border-right + border-bottom: 1px solid #1a1f26
       ├── nhãn  sans 11px/500 .1em uppercase label
       └── giá trị  mono 12px, margin-top 6px, line-height 1.6, text-wrap pretty
                    fg: primary khi bình thường, #f0b429 khi cảnh báo,
                        secondary khi là câu mô tả
```

Footer trong card: padding `9px 15px`, bg `#0b0d11`, mono 11px label.

> Giá trị ở đây là **câu**, không phải số (`"account/legacy retirement ·
> final_bar_divergence · shadow evidence"`). Nên `line-height:1.6` và
> `text-wrap:pretty` — và vì thế mono 12px, không phải 18px như Today's Decision.

## Open Orders

Accent `#e0913c`. Padding `18px 22px 24px` — đáy dày hơn vì nó đóng nhóm 01.

```
card (KHÔNG có background — chỉ border + overflow:hidden)
├── header  grid 1.2fr .7fr .7fr .5fr .9fr 1.1fr .6fr, gap 14px
│            padding 11px 22px, bg #0b0d11
│            sans 11px/500 .1em uppercase label
│            cột Stop và ID: text-align:right
└── thân    padding 16px 18px, bg #0e1116, border-top divider
             text-align:center, sans 13px label
```

Cột số (Qty, Stop, ID) căn phải. Cột chữ căn trái. Không có cột nào căn giữa.

---

# 02 · BOOK

## Hàng bốn block

```
padding:15px 22px; border-bottom page-rule
grid-template-columns: 1.25fr 1fr 1fr 1fr; gap:12px
```

Paper equity rộng hơn (`1.25fr`) vì nó chứa số 30px cộng hai dòng phụ.

> **Ràng buộc thật:** bốn cột chỉ đúng khi trang đủ rộng. Root của design khai
> `min-width:1900px`. Ở 1440×900 mà giữ bốn cột thì "0.00%" của Risk đè
> "Protection" của Exposure. Dưới ~1600px phải xuống hai cột.

**Paper equity** — border `#1c2a2b` (hơi xanh, khác ba block kia dùng `#1e242c`):

```
padding:11px 15px
├── nhãn "Paper equity" sans 11px/500 .1em uppercase #5fd3b2
│   → "base $50,000" mono 11px null
├── số  mono 30px/500 -.03em line-height:1, margin-top 9px
├── câu trạng thái  mono 11px label, margin-top 9px, text-wrap pretty
└── margin-top 11px, padding-top 10px, border-top divider
    dot 5px #f0b429 · "Broker $50,231 · legacy epoch stale" mono 11px #f0b429
    → "Reconcile" mono 11px #5fd3b2
```

Khi không đo được, số 30px in chữ **"not measured"** — không in `--`, không in
`$0`. Một số 0 ở vị trí đó là một lời khẳng định sai.

**Performance / Exposure** — cùng khuôn, khác nhãn accent (`#5fd3b2` / `#5b9cf0`):

```
padding:11px 15px
nhãn sans 11px/500 .1em uppercase <accent>, margin-bottom 11px
rồi 4 hàng metric compact (xem DESIGN_SPEC mục 3):
  flex baseline gap 12px, padding 5px 0, border-bottom #171b22
  nhãn sans 12px label + → giá trị mono 14px
giá trị fg: primary khi có số, null (#4b5563) khi là "—" hoặc "n/a"
```

**Risk** — block duy nhất có gauge:

```
padding:11px 15px
├── nhãn "Risk" #e0913c → "of 15.00% limit" mono 11px label
├── flex baseline gap 10px
│   số mono 24px/500 -.02em primary + "$0.00 drawdown" mono 12px label
├── gauge: margin-top 11px, height 3px, radius 2px, bg #1a1f26, overflow hidden
│          fill: width theo tỉ lệ, height 100%, bg #3a424f, radius 2px
└── "peak 0.00% · no closed trades yet" mono 11px label, margin-top 9px
```

Fill khi bằng 0 vẫn giữ `width:2px` — để người đọc thấy track có fill, chỉ là gần
0. Fill màu `#3a424f` (trung tính) khi trong hạn; đổi hổ phách/đỏ khi vượt ngưỡng.

## Open Positions

Accent `#5fd3b2`. Heading có **ba** phần trước dấu đẩy phải: vạch + tiêu đề +
"legacy / drain" mono 11px **null** (đây là scope, không phải trạng thái).

Thân là empty state chuẩn: card padding `14px 16px`, flex gap 11px, dot 5px
`#4b5563`, câu sans 14px secondary.

> Câu phải nói **tại sao**: *"No broker positions. Nothing to protect, so no
> protection is asserted."* — mệnh đề thứ hai là mệnh đề quan trọng.

## Today's Decision

Accent `#9d8cf5`. Card có **hai** tầng:

```
tầng 1  grid repeat(5,1fr)
        mỗi ô padding 11px 16px, border-right divider
        nhãn sans 11px/500 .1em uppercase label
        + giá trị mono 18px, margin-top 5px
        fg: primary cho Regime/Realized, secondary cho các số đếm

tầng 2  grid repeat(3,1fr), border-top divider
        mỗi nhóm border-right divider
        ├── head  flex gap 10px, padding 8px 16px, bg #0b0d11,
        │          border-bottom #171b22
        │          nhãn uppercase label → count mono 13px
        └── thân  padding 10px 16px, sans 13px label, text-wrap pretty

footer  padding 10px 16px, bg #0b0d11, border-top divider, sans 12px label
```

Ba nhóm là Entered | Closed | Rejected/Halted. Nhóm rỗng in câu riêng
("No open entries in this decision.") — không in `0` rồi để trống.

---

# 03 · MARKET

## Regime Monitor

Accent `#9d8cf5`. Card có **năm** hàng, chia bằng vạch trong.

**Hàng 1 — Model inputs (nằm TRONG card, là hàng đầu):**

```
flex; border-bottom divider; bg #0b0d11
├── ô nhãn  padding 9px 15px, flex gap 9px
│           "Model inputs" sans 11px/500 .1em uppercase #9d8cf5
│           + dot 5px #f0b429 (khi có input cảnh báo)
├── 6 ô  mỗi ô padding 9px 15px, border-left divider
│        nhãn sans 11px label + giá trị mono 15px, margin-top 3px
│        fg: primary, hoặc #f0b429 khi stale, secondary khi là câu
└── →  "Refit" mono 11px #5fd3b2, padding 9px 15px
```

> Model inputs **thuộc Regime Monitor**, không phải một block riêng ở hàng metrics.
> Regime, SPY date, model age, HMM fit, fit end, re-freeze — cả sáu là *đầu vào của
> nhãn regime*. Đặt chúng cạnh Paper Equity là đặt đầu vào của model cạnh số dư tài
> khoản. Và nó vào trong **`.rg2-card`** (chia khung với label bên dưới), không phải
> vào section — vào section thì nó nổi ra ngoài khung, trên cả heading.

**Hàng 2 — nhãn + 4 metric (grid `300px 1fr`):**

```
ô trái  padding 13px 18px, border-right divider
├── flex gap 11px: dot 8px #3ecf8e
│   + "Calm" sans 23px/600 -.02em #8ae6cc, line-height 1.1
│   + → "held 24 days" mono 11px #5fd3b2
├── flex gap 8px margin-top 9px: dot 5px + "Label check passed" sans 12px #8ae6cc
│   + "1,761 days · no drift" mono 11px label
└── "as of … · checked 29.9h ago" mono 11px null, margin-top 8px
ô phải  grid repeat(4,1fr)
        mỗi ô padding 13px 18px, border-right divider
        nhãn uppercase label + giá trị mono 18px/500 -.01em
        + ghi chú sans 12px label margin-top 6px
```

Nhãn regime **không bao giờ đứng một mình** — luôn kèm "held N days" và dòng label
check. "Calm" từ một lần đọc ba ngày trước là một phát biểu khác với "Calm" sáng nay.

**Hàng 3 — posterior + features (grid `300px 1fr`):**

```
ô trái  nhãn "State probabilities" + 4 hàng, gap 8px
        mỗi hàng grid 60px 1fr 50px, gap 11px, align-items center
        ├── dot vuông 6px radius 2px + tên sans 12px
        │   fg primary khi >1%, label khi ≤1%
        ├── track height 5px radius 3px bg #141920
        │   fill width = max(value, 0.4)%  ← sàn 0.4% để 0% vẫn thấy được track
        └── giá trị mono 12px text-align right
            fg primary khi >1%, null khi ≤1%
ô phải  head: nhãn + "SPY features behind the … label" mono 11px label
              → "Show all 9" mono 11px #5fd3b2
        grid 1fr 1fr gap 0 22px, mỗi feature:
        grid 1fr auto auto, gap 12px, padding 7px 0, border-bottom #171b22
        nhãn sans 13px secondary · giá trị mono 13px primary
        · [rank mono 11px label | vạch 1×9px #262d36 | "leans …" sans 11px #5fd3b2]
```

**Hàng 4 — strip 60 ngày:**

```
padding 13px 18px, border-bottom divider
├── head: nhãn + → legend 4 mục (dot vuông 8px radius 2px + tên sans 12px secondary)
└── flex gap 3px, margin-top 10px
    mỗi run: flex = số ngày (KHÔNG phải flex:1), min-width:0
    ├── thanh height 10px radius 3px bg <màu regime>
    └── nhãn mono 10px label margin-top 5px, ellipsis
        "Normal · 31d" khi ≥10 ngày, chỉ "6d" khi ngắn
```

`flex` theo số ngày, không chia đều — một run 31 ngày phải rộng gấp 5 run 6 ngày.

**Hàng 5 — footer:** padding `12px 18px`, bg `#0b0d11`, flex gap 11px, dot 5px
label margin-top 7px, rồi câu sans 13px primary + câu sans 12px secondary
`max-width:130ch`.

## Track 1 Market View · Calm hai phase

Xem `DESIGN_SPEC.md` mục 4 — đã chi tiết ở đó.

---

# Cột phải · 380px

`background:#0a0c10` (sunken — tối hơn cột trái, để tách bằng độ sâu chứ không
bằng vạch).

## Job journal — header

```
padding:16px 18px 0
├── vạch accent #9d8cf5 + "Job journal" sans 17px/600
│   → "66 jobs · 2026-08-31" mono 11px label
├── margin-top 9px: dot 6px #3ecf8e
│   + "Scheduler" mono 10px .14em uppercase label
│   + "on schedule" mono 11px secondary
└── tab: margin-top 14px, flex gap 4px, padding 3px,
         border 1px #1e242c, radius 7px, bg #0e1116
    mỗi tab flex:1, text-align:center, padding 8px, radius 5px
             sans 12px/500 .1em uppercase
    đang mở: bg #1c1a2b, fg #c9c0fb   ← tím, KHÁC nav header (xanh #14251f)
    còn lại: trong suốt, fg label
```

Tab journal dùng tím vì nó thuộc cột phải; nav header dùng xanh. Hai hệ tab khác
cấp, không được trông giống nhau.

## Job journal — hàng job

```
padding:5px 18px 20px, mỗi card margin-top 8px
card: border 1px <cardBorder>, radius 8px, bg <cardBg>, overflow hidden
      đang mở  border #2a323d, bg #0e1116
      đóng     border #171b22, bg #0b0d11

phần bấm  padding 10px 13px, cursor pointer, style-hover bg #12161c
├── flex gap 10px: giờ mono 11px label → thời lượng mono 11px label
├── flex gap 7px wrap, margin-top 8px:
│   badge lane   mono 9px .12em, border 1px #2e2745, fg #9d8cf5
│   badge state  mono 9px .12em, border 1px #2a323d, fg <theo state>
│   [badge tag]  cùng khuôn, fg #798394 hoặc #8ae6cc
│   → nút +/−  20×20px, border 1px #262d36, radius 4px,
│               sans 12px, line-height 18px, text-align center
├── tên  mono 13px primary, margin-top 8px
└── ghi chú  sans 12px label, margin-top 4px, text-wrap pretty
```

Badge lane có border **`#2e2745`** (tím), khác `#2a323d` của badge state — lane là
phân loại, state là trạng thái.

## Job journal — chi tiết khi mở

```
border-top divider, bg #0b0d11
├── Started | Exit   grid 1fr 1fr, border-bottom #171b22
│   mỗi ô padding 10px 13px (ô trái + border-right #171b22)
│   nhãn uppercase label + giá trị mono 12px
│   Exit lấy màu theo state của job
├── Outcome  padding 11px 13px, border-bottom #171b22
│             nhãn + câu sans 12px primary
├── Log      padding 11px 13px, border-bottom #171b22
│   mỗi dòng grid 62px 46px 1fr, gap 9px, padding 3px 0
│              mono 11px, line-height 1.6
│              giờ label · level <màu theo level> · message secondary
└── nút      padding 10px 13px, flex gap 8px
    "Full log" / "Artifacts"  padding 6px 12px, border 1px #262d36,
                               radius 5px, mono 11px primary
    → "Re-run"  padding 6px 12px, radius 5px, bg #14251f, mono 11px #8ae6cc
```

Log dùng grid ba cột cố định (`62px 46px 1fr`) — timestamp và level phải thẳng
hàng dọc, nếu không mắt không quét được xuống.

Cuối danh sách: "Show all 66 jobs" mono 11px `#5fd3b2` → "Collapse all" mono 11px
label, hover `#a8b1c0`.

## Event journal

```
mỗi card  border 1px #171b22, border-left:2px solid <accent>,
          radius 8px, bg #0b0d11, padding 10px 13px
├── flex gap 9px: category mono 9px .12em label (KHÔNG có border — chỉ chữ)
│   · badge status mono 9px .12em có border → giờ mono 11px label
├── tiêu đề sans 13px primary, margin-top 8px, text-wrap pretty
├── message sans 12px label, margin-top 4px
└── [khi có mốc thời gian]
    grid 1fr 1fr, gap 10px, margin-top 10px, padding-top 9px,
    border-top #171b22
    INCURRED / RECOVERED  sans 9px/600 .12em null
    + giá trị mono 11px (recovered lấy màu theo trạng thái)
```

Category **không có border**, status **có** — category là phân loại, status là
trạng thái. Cùng cỡ chữ nhưng khác trọng lượng thị giác.

Footer: mono 11px null — *"Structured events only — repeated observations are
grouped, and an absence of log lines is never read as a recovery."*

## Source Clocks

```
padding:0 18px 22px
khối trong: border-top page-rule, padding-top 16px
├── heading  vạch accent 3×13px #5b9cf0 (thấp hơn 15px của section chính)
│            + "Source Clocks" sans 15px/600 -.01em
│            ← 15px, KHÔNG phải 17px: đây là section phụ trong cột phải
└── mỗi hàng  flex baseline gap 12px, padding 6px 0,
              border-bottom #171b22
              nhãn sans 12px label → giá trị mono 12px, white-space nowrap
              fg: primary khi bình thường, #f0b429 khi stale, secondary khi là câu
```

---

# Bảng tra nhanh accent theo section

| Section | Accent vạch |
|---|---|
| Now Monitor | `#5b9cf0` |
| Open Issues | `#5b9cf0` |
| Track 1 Runtime | `#e0913c` |
| Open Orders | `#e0913c` |
| Open Positions | `#5fd3b2` |
| Today's Decision | `#9d8cf5` |
| Regime Monitor | `#9d8cf5` |
| Track 1 Market View | `#5b9cf0` |
| Calm two phases | `#3ecf8e` |
| Job journal | `#9d8cf5` |
| Source Clocks | `#5b9cf0` |

Accent lặp lại là **cố ý**: hai section cùng màu là hai section trả lời cùng loại
câu hỏi. Đừng cấp màu mới cho mỗi section.
