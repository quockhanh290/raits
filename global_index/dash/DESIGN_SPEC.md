# Realtime dashboard — design spec

Hợp đồng thị giác của `Realtime Dashboard.dc.html`, viết ra dưới dạng giá trị
tuyệt đối để đối chiếu và implement mà **không cần mở file DC**.

Lý do có file này: file DC là template runtime, style nằm inline rải khắp 1500
dòng, đọc nó như đọc spec thì phải tự suy ra token — và suy sai là ra kết quả
lệch. Dưới đây là token đã trích sẵn.

> **Cảnh báo trước khi dùng:** file này chỉ mô tả *hình*. Về *nội dung*,
> repo `dash/realtime/` đang đúng hơn bản design ở 8 chỗ — đọc
> `IMPLEMENTATION_PROMPT.md` phần 2. Đừng lấy chữ trong spec này thay chữ trong
> repo; chỉ lấy màu, cỡ, khoảng cách, cấu trúc.

**Giải phẫu từng section** — Now Monitor, Open Issues, Track 1 Runtime, Open
Orders, hàng 4 block, Open Positions, Today's Decision, Regime Monitor, Job
journal, Event journal, Source Clocks — nằm ở `SECTION_ANATOMY.md`. File này là
token và pattern dùng chung; file kia là từng section một.

---

## 1 · Token

### Nền — bốn bậc, không hơn

| Token | Hex | Dùng cho |
|---|---|---|
| page | `#08090c` | nền trang |
| gutter | `#07080b` | khe 14px giữa ba nhóm |
| sunken | `#0a0c10` | cột phải; đáy gradient của group band |
| panel | `#0e1116` | mặt card |
| inset | `#0b0d11` | header/footer trong card, card cấp 2 |
| well | `#141920` | lòng track của bar/gauge |

### Viền — năm bậc

| Token | Hex | Dùng cho |
|---|---|---|
| page-rule | `#1b2027` | vạch giữa section, viền cột |
| card | `#1e242c` | viền ngoài card |
| divider | `#1a1f26` | vạch trong card |
| hairline | `#171b22` | vạch giữa các dòng trong list |
| chip | `#262d36` | viền chip, viền group band trên |

### Chữ — bốn bậc ĐỌC + một dấu KHÔNG-GIÁ-TRỊ

**Bốn bậc đọc** — dùng cho chữ người ta đọc để lấy thông tin:

| Token | Hex | Nghĩa |
|---|---|---|
| primary | `#e8ebf0` | số và tên — thứ người đọc đến để lấy |
| secondary | `#a8b1c0` | câu giải thích, giá trị phụ |
| label | `#798394` | nhãn, caption, meta |
| null | `#4b5563` | "không có giá trị", provenance, đơn vị mờ |

**Một dấu không-giá-trị**, không phải bậc đọc:

| Token | Hex | Chỉ dùng cho |
|---|---|---|
| void | `#2a323d` | kí tự `—` đứng một mình trong ô của bảng hai pha |

`void` tách riêng vì nó không bao giờ tô lên chữ thật — chỉ lên dấu gạch. Đếm
bậc xám thì đếm bốn, không đếm năm.

Bản Ops Console cũ có 8 bậc xám gần giống nhau và đó chính là thứ lần redesign
này bỏ đi.

### Màu trạng thái — **chỉ tô khi màu LÀ thông điệp**

| Token | Hex | Dùng cho |
|---|---|---|
| green | `#3ecf8e` | dot pass/live |
| green-text | `#8ae6cc` | chữ trên nền xanh, giá trị OK |
| green-link | `#5fd3b2` | link, nhãn accent Book |
| red | `#f2555a` | dot/cell fail |
| red-text | `#ff8085` | chữ FAIL |
| amber | `#f0b429` | cảnh báo, degradation |
| amber-dot | `#e0913c` | dot bar volume |
| blue | `#5b9cf0` | accent Operations, đường EMA |
| blue-text | `#8dc0f7` | đường close, chữ crosshair |
| purple | `#9d8cf5` | accent Market, lane runner |
| neutral-dot | `#3a424f` | slot đã quyết, không fire |

**Giá, stop, side, số lượng luôn là `primary` — không bao giờ tô màu.** Chỉ
indicator trạng thái (PnL, degradation, breach, pass/fail) được tô.

### Nền chip theo tone

| Tone | bg | border | fg |
|---|---|---|---|
| muted | `#0f1319` | `#262d36` | `#a8b1c0` |
| plain | trong suốt | `#1e242c` | `#798394` |
| good | `#0f1d18` | `#1e3a30` | `#8ae6cc` |
| warn | `#1b1608` | `#3a2f14` | `#f0b429` |
| bad | `#1c1012` | `#3d1f22` | `#ff8085` |
| live | `#101a2c` | `#233348` | `#8dc0f7` |

### Chữ

- Sans: `'IBM Plex Sans', Helvetica, Arial, sans-serif` — nhãn, câu, tiêu đề
- Mono: `'IBM Plex Mono', monospace` — **mọi con số, mọi mã, mọi giờ**
- Root: `font-size:14px; line-height:1.45; font-variant-numeric:tabular-nums`

Thang cỡ, và mỗi cỡ chỉ có một việc:

| px | weight | dùng cho |
|---|---|---|
| 9 | 600 | nhãn cột trong card (DECIDE/OBSERVE/GATES), letter-spacing `.12em` |
| 10 | 500 | nhãn cell, badge; `.11em`–`.12em`, uppercase |
| 11 | 400/500 | meta mono, nhãn section (`.1em`, uppercase), tally |
| 12 | 400/500 | nhãn hàng, nav, legend |
| 13 | 400 | câu giải thích, nhãn hàng có giá trị; số group band (600) |
| 14 | 400 | body; giá trị mono trong bảng hai phase |
| 15 | 500 | câu status band |
| 17 | 600 | tiêu đề section, `-.01em` |
| 18 | 500/600 | verdict; giá trị metric regime |
| 20 | 600 | tên group band, `-.02em` |
| 23 | 600 | nhãn regime (Calm), `-.02em` |
| 24 | 500 | số drawdown, `-.02em` |
| 30 | 500 | số paper equity, `-.03em` |

**Lỗi đã biết trong DC:** có `Times New Roman` lọt lên trang — element không thừa
hưởng font, khả năng là `<text>` trong SVG. Không copy. Nếu repo có leak tương tự
thì sửa, đừng bắt chước.

### Bán kính & khoảng

- Card `8px` · chip/nav `5px` · badge/chip nhỏ `4px` · badge mono `3px` · track `2–3px`
- Section padding **`18px 22px`**; Now Monitor `16px 22px`; hàng 4 block `15px 22px`; Open Orders `18px 22px 24px`
- Card: header `9px 15px`, thân `11px 15px`, hàng list `9px–11px × 12–15px`
- Khe giữa nhóm: `14px`, nền `#07080b`, `border-top:1px solid #161b22`

---

## 2 · Bố cục trang

```
header               flex, padding 12px 22px, border-bottom page-rule
status band          flex, 11px 22px, gradient 90deg #0c1512 0% → #0b0d11 42%
grid 1fr / 380px
├── cột trái  (border-right page-rule)
│   ├── GROUP BAND 01 Operations
│   │   Now Monitor · Open Issues · Track 1 Runtime · Open Orders
│   ├── gutter 14px
│   ├── GROUP BAND 02 Book
│   │   hàng 4 block (Paper equity·Performance·Risk·Exposure) · Open Positions · Today's Decision
│   ├── gutter 14px
│   └── GROUP BAND 03 Market
│       Regime Monitor · Track 1 Market View · Calm two phases
└── cột phải (bg sunken)
    Job journal (tab Jobs|Events) · Source Clocks
```

### Group band — giải phẫu chính xác

```
display:flex; align-items:baseline; gap:14px;
padding:16px 22px 13px;
border-top:1px solid #262d36;
border-bottom:2px solid <accent>;
background:linear-gradient(180deg, <tint> 0%, #0a0c10 100%);
```

| nhóm | accent | tint |
|---|---|---|
| 01 Operations | `#5b9cf0` | `#0d1219` |
| 02 Book | `#5fd3b2` | `#0b1512` |
| 03 Market | `#9d8cf5` | `#100e1a` |

Bốn con bên trong, theo thứ tự: số mono 13px/600 màu accent · tên sans 20px/600
`-.02em` primary · phụ đề sans 13px label · `margin-left:auto` đếm section mono
11px null.

Accent được mang bởi **cả** border-bottom **và** màu của số — để người không phân
biệt được ba màu vẫn đọc ra ba nhóm.

### Section heading (trong nhóm)

```
flex, align-items:baseline, gap:12px, margin-bottom:11px
├── span 3×15px, radius 2px, background <accent nhóm>
├── tiêu đề sans 17px/600 -.01em primary
├── [trạng thái: dot 6px + mono 10px .14em label]
└── margin-left:auto → meta mono 11px label
```

---

## 3 · Các pattern lặp lại

### Card

`border:1px solid #1e242c; border-radius:8px; background:#0e1116; overflow:hidden`

**Không lồng card trong card.** Chia bằng vạch `#1a1f26` bên trong. Header và
footer trong card dùng nền `#0b0d11`.

### Metric compact — nhãn và giá trị **cùng một dòng**

```
flex; align-items:baseline; gap:12px; padding:5px 0;
border-bottom:1px solid #171b22
├── nhãn sans 12px label
└── margin-left:auto → giá trị mono 14px primary
```

Không xếp dọc. Bản cũ xếp dọc và cao gấp đôi mà không thêm thông tin.

### Hàng metadata phân cách bằng vạch dọc

```
flex; flex-wrap:wrap
mỗi span: padding:0 11px; border-left:1px solid #1e242c; mono 11px
span đầu: bỏ border-left
```

Màu theo nội dung: mục có số `#a8b1c0` · mục fail `#f0b429` · provenance `#4b5563`.

### Empty state — nói **tại sao** trống

```
flex; align-items:center; gap:11px; padding:14px 16px
├── dot 5px #4b5563
└── câu sans 14px secondary
```

Ví dụ đúng: *"No broker positions. Nothing to protect, so no protection is
asserted."* — không phải "No data".

### Lane (một cell mỗi slot)

```
grid-template-columns:246px 1fr 110px
├── nhãn: padding 10px 18px 10px 15px; border-left:3px solid <accent|transparent>
│         tên sans 13px primary + điều kiện mono 11px label
├── track: flex; gap:2px; padding:0 6px
│          cell flex:1; height:10px; radius:2px
│          pass #3ecf8e · fail #f2555a · chưa tới: trong suốt + 1px solid #22282f (height 9px)
└── tally: mono 12px, text-align:right
           tất cả pass #8ae6cc · có fail #ff8085 · chưa tới #4b5563
```

Lane đang chặn: `border-left:3px solid #f2555a` + nền hàng `#100f12`.

### Hover đồng bộ

Một `hoverSlot` duy nhất điều khiển: cột overlay trên cả hai chart
(`rgba(91,156,240,.07)`), đường dọc `#3a5a80` 1px, dot 7px trên từng line, ô lane
được `outline:1px solid #8dc0f7; outline-offset:1px`, dot slot đổi sang `#8dc0f7`,
và một hàng readout mono phía trên chart.

Readout khi chưa hover: *"hover a slot to read both charts at the same minute"*,
mọi giá trị màu `#4b5563`.

---

## 4 · Market View

Section này có **năm** lớp điều khiển xếp trên nhau. Đọc theo đúng thứ tự dưới,
vì mỗi lớp chọn cái gì được hiển thị ở lớp sau.

```
1  sleeve tab   NKD | Stress | Swing        ← chọn rổ nào
2  session      08-25 … 08-31 (today)       ← chọn ngày nào
3  header verdict                            ← câu trả lời + bằng chứng
4  inner tab    Setup rules | Detector rules | Price context
5  nội dung tab
```

### 4.1 · Sleeve tab (ngoài card, cạnh tiêu đề section)

```
flex; gap:3px; padding:3px
border:1px solid #1e242c; radius:7px; background:#0e1116
mỗi tab: padding 5px 14px; radius 5px
         sans 11px/500 .1em uppercase; cursor pointer
  đang chọn: bg #14251f, fg #8ae6cc
  còn lại:   trong suốt, fg label
→ meta mono 11px label  ("MNKD · 5m · window 01:20–02:55 ET · session 2026-08-31")
```

### 4.2 · Session picker (ngoài card, dưới sleeve tab)

```
flex; gap:6px; flex-wrap:wrap; margin-bottom:10px
nhãn "Session" sans 10px/500 .12em uppercase null, margin-right 4px
mỗi chip: flex gap 6px; padding 4px 10px; radius 5px; mono 11px; cursor pointer
  đang chọn  bg #14251f · border #1e3a30 · fg #8ae6cc
  ngày khác  trong suốt · border #1e242c · fg #a8b1c0
  không có diagnostics  fg #4b5563
chip hôm nay kèm "today" sans 9px .1em uppercase #5fd3b2
→ ghi chú sans 12px label, text-wrap pretty
```

Ghi chú đổi theo trạng thái: đang xem ngày cũ thì nói rõ *chỉ band này* theo ngày
đó, còn job list và open issues bên dưới vẫn ở ngày live.

### 4.3 · Header verdict (hàng đầu trong card)

```
grid 1fr / auto; gap 24px; align-items:center
padding:11px 15px; border-bottom divider; background inset
├── trái, cột dọc gap 9px
│   ├── hàng 1: flex gap 9px wrap
│   │   2 chip: flex gap 8px; padding 4px 12px; radius 5px
│   │            border 1px <border>; bg <bg>
│   │            dot 7px + chữ mono 12px/600 .1em
│   │     COMPLETE   bg #0f1319 · border #262d36 · fg #a8b1c0 · dot #4b5563
│   │     NO SIGNAL  bg #0f1319 · border #262d36 · fg #e8ebf0 · dot #4b5563
│   │   + câu lý do sans 13px secondary, max-width 88ch
│   └── hàng 2: hàng metadata, 5 mục
│       mỗi mục padding 0 11px; border-left 1px #1e242c; mono 11px
│       (mục đầu KHÔNG có border-left)
│       N/N slots · latest HH:MM ET · boundary kind · rule → regime · live|reviewing date
│       màu: mục có số #a8b1c0 · rule-fail #f0b429 · ngày #4b5563
└── phải, text-align:right
    verdictDetail mono 11px label
    + boundaryProof mono 11px null, margin-top 4px
```

Chip **chỉ mang một từ**. Detail thuộc hàng metadata, không nhồi vào chip.

### 4.4 · Inner tab

```
flex; align-items:center; gap:12px; padding:8px 15px; border-bottom divider
├── hộp tab: flex gap:3px; padding:3px
│            border 1px #1e242c; radius 7px; background #0b0d11
│            ← bg INSET, khác sleeve tab (dùng #0e1116): tab trong card thì tối hơn
│   mỗi tab padding 5px 13px; radius 5px; sans 12px/500; cursor pointer
│           KHÔNG uppercase, KHÔNG letter-spacing — khác sleeve tab
│     đang chọn: bg #14251f, fg #8ae6cc
│     còn lại:   trong suốt, fg label
└── ghi chú tab  sans 12px label
```

Ghi chú đổi theo tab đang mở — nó nói tab này trả lời câu gì:

| Tab | Ghi chú |
|---|---|
| Setup rules | *"What each rule did, slot by slot — open Detector rules for the per-bar verdicts."* |
| Detector rules | *"One cell per bar, not per slot, plus the readings the detector returned."* |
| Price context | *"No candidate in this session, so no levels are published — price context only."* |

> Sleeve tab uppercase + letter-spacing, inner tab thì không. Hai hệ tab khác cấp
> — sleeve chọn *dữ liệu nào*, inner chọn *cách xem*. Cho chúng cùng kiểu chữ là
> nói chúng cùng cấp.

---

### 4.5 · Tab 1 — Setup rules

Trả lời: *"từng slot đã quyết gì?"* Một cell mỗi **slot**.

```
head  flex gap 12px; padding 8px 15px; border-bottom divider
      nhãn "<SLEEVE> setup rules" sans 11px/500 .1em uppercase label
      + "one cell per slot · <window>" mono 11px null
      → slot đang hover  mono 11px #8dc0f7
      ← đây là readout duy nhất của tab này; không có hàng riêng

4 lane  grid 246px 1fr 110px; align-items:center
        border-bottom #171b22; background <rowBg>
├── nhãn  padding 8px 15px 10px 15px
│         border-left:3px solid <accent|transparent>
│         tên sans 13px primary
│         + điều kiện mono 11px label, margin-top 3px
├── track  flex; gap:2px; padding:0 6px
│          onMouseLeave → clear hover
│   mỗi cell  flex:1; radius 2px; cursor crosshair
│             outline:<1px solid #8dc0f7 khi hover>; outline-offset:1px
│     pass       height 10px; bg #3ecf8e
│     fail       height 10px; bg #f2555a
│     chưa tới   height  9px; trong suốt; border 1px #22282f
└── tally  padding 8px 15px; text-align:right; mono 12px
           tất cả pass #8ae6cc · có fail #ff8085 · chưa tới #4b5563

hàng "Slot decisions"  cùng grid 246px 1fr 110px, border-bottom divider
├── nhãn  padding 7px 15px, sans 11px/500 .1em uppercase label
├── track  flex gap:2px; padding 0 6px
│          mỗi ô flex:1, justify-content:center
│          dot 5px  #3a424f bình thường · #8dc0f7 khi hover slot đó
└── tally  mono 12px secondary  ("22 / 22")

legend  flex gap:18px; padding 7px 15px; bg inset; flex-wrap wrap
        mỗi mục: swatch 10×4px radius 2px + nhãn sans 12px label
        6 mục: Passed · Failed · Not reached · No verdict published ·
               No record · Not yet run
        → "declared · <session/clock/max hold>" mono 11px null
```

Lane đang chặn: `border-left:3px solid #f2555a` **và** nền hàng `#100f12`. Hai
dấu hiệu cho một sự thật, để nó không mất khi người đọc không phân biệt được màu.

Swatch legend là **10×4px chữ nhật**, không phải dot — nó mô phỏng hình dạng cell
trong lane, không phải hình dạng dot slot.

### 4.6 · Tab 2 — Detector rules

Trả lời: *"detector đọc ra gì, và phán gì?"* Một cell mỗi **bar** — khác tab 1.

**Phần trên · bar grid**

```
head  flex gap 12px; padding 8px 15px; border-bottom divider
      "Per-bar verdicts" sans 11px/500 .1em uppercase label
      + "<N> bars in this session's window — one cell per bar, not per slot"
        mono 11px null
      → "detector answered <N> times" mono 11px label

4 hàng  grid 246px 1fr 110px; border-bottom #171b22
├── nhãn  padding 7px 15px   ← KHÔNG có border-left accent (khác lane tab 1)
│         tên sans 13px primary + điều kiện mono 11px label
├── track  flex; gap:1px; padding 0 6px     ← gap 1px, KHÔNG phải 2px
│   mỗi cell flex:1; height 9px; radius 1px  ← radius 1px, KHÔNG phải 2px
└── tally  padding 7px 15px; text-align:right; mono 12px
```

> **gap 1px và radius 1px là cố ý.** Bar grid có ~N+10 cell, nhiều hơn lane
> (~22). Giữ gap 2px thì các cell mảnh đến mức đọc thành một dải nhiễu. Và cell
> nhỏ hơn thì radius phải nhỏ hơn, nếu không nó thành hình tròn.
>
> **Không có border-left accent** ở nhãn: bar grid không có khái niệm "lane đang
> chặn" — mỗi bar là một câu trả lời độc lập, không có lane nào chặn lane nào.

**Phần dưới · grid `1.15fr 1fr`, `border-top` divider**

Ô trái — Conditions & Readings:

```
padding:11px 15px; border-right divider
├── head  flex baseline gap 10px
│         "Conditions" sans 11px/500 .1em uppercase label
│         → "market ref <giá> · <giờ> · RECORDED" mono 11px label
│            giá màu secondary · "RECORDED" màu #8ae6cc
├── hàng Regime  grid 1fr auto auto; gap 0 14px; align-items baseline
│                margin-top 11px; padding-bottom 11px; border-bottom divider
│                "Regime" sans 13px primary + "needs Normal" mono 11px label
│                · giá trị mono 14px primary · "FAIL" mono 10px/500 .1em #ff8085
├── nhãn "Readings · no verdict published"
│        sans 11px/500 .1em uppercase null, margin 13px 0 3px
├── 6 reading  grid 1fr 1fr; gap 0 22px
│   mỗi cái: flex baseline gap 12px; padding 6px 0; border-bottom #171b22
│            nhãn sans 13px secondary → giá trị mono 13px
│            fg primary, hoặc #f0b429 khi bất thường (vd bar volume = 0)
└── ghi chú  sans 12px label, margin-top 10px, text-wrap pretty
```

Ô phải — Nearest miss & Trade levels:

```
padding:11px 15px; flex column; gap 14px
├── Nearest miss
│   nhãn uppercase label + câu sans 13px primary, margin-top 6px
└── Trade levels  padding-top 13px; border-top divider
    nhãn uppercase label
    + flex gap 8px: dot 5px #4b5563 + câu sans 13px secondary
    + lý do sans 12px label, margin-top 7px, text-wrap pretty
```

> Nhãn "Readings · no verdict published" màu **null**, không phải label. Cả khối
> reading là số detector đã đọc *nhưng chưa ai so* — regime gate đã chặn trước
> đó. Màu mờ hơn nói điều đó mà không cần thêm câu.

### 4.7 · Tab 3 — Price context

Trả lời: *"giá làm gì trong lúc sleeve đang xem?"*

Đây là tab duy nhất có chart. Cấu trúc: **một** grid `1fr 72px` chứa cả năm pane,
dùng chung crosshair, và chỉ **một** hàng nhãn giờ ở đáy.

```
head giá  flex gap 14px; padding 9px 15px 0; flex-wrap wrap
├── "Price" sans 11px/500 .1em uppercase label
├── chip ngày  mono 11px .06em; padding 2px 8px
│              border 1px #262d36; radius 4px; fg secondary
│              nội dung: "bars · <bars_session_date>"
├── OHLC  mono 12px secondary  ("O … H … L … C …")
├── thay đổi  mono 12px, #3ecf8e khi tăng / #ff8085 khi giảm
└── → ghi chú  mono 11px null  ("<N> bars · <inst> 5m · levels not published")

readout hover  margin 7px 15px 0; padding 7px 12px
               border 1px #1a1f26; radius 6px; bg inset; flex gap 18px wrap
├── slot đang trỏ  mono 11px .06em #8dc0f7
└── 6 mục: nhãn sans 11px null + giá trị mono 12px
   bar · bar vol · close · <ema> · 10-bar vol · slot vol
   khi CHƯA hover: slot in "hover a slot to read both charts at the same minute",
                   mọi giá trị màu #4b5563
```

Rồi grid `1fr 72px`, các pane theo thứ tự dọc:

| # | Pane | Cao | Nội dung |
|---|---|---|---|
| 1 | nến | 210px | dải WINDOW · 3 gridline `#141920` · nến |
| 2 | volume nến | 58px | cột volume, cao tối đa 82% |
| 3 | slot | 24px | dot 6px `#3a424f`, vạch ngang `#171b22` |
| 4 | series | 128px | area fill · close · EMA · 3 gridline `#12161c` |
| 5 | slot volume | 66px | 10-bar avg · bar volume |
| 6 | nhãn giờ | 22px | 5 mốc, `border-top` divider |

Cột phải 72px của từng pane: trục giá (pane 1), nhãn peak/0 (pane 2, 5), nhãn
cao/thấp + nhãn giá cuối (pane 4). Pane 3 và 6 để trống.

**Trục giá pane 1 — 3 mốc, không phải 5:**

```
mỗi mốc  position:absolute; left:8px
         top: 0% | 50% | 100%
         transform:translateY(<shift>)
           mốc trên   0
           mốc giữa   -50%
           mốc dưới   -100%
         mono 11px label; white-space:nowrap
giá trị  pTop − pRng × f, với f = 0 | 0.5 | 1
```

Ba mốc, không phải năm: `pTop` và `pBot` đã có padding 6% mỗi đầu, nên mốc
25%/75% rơi vào khoảng trống và chỉ thêm chữ. `translateY` theo mốc thay vì
`-50%` cho cả ba — mốc trên và dưới phải nằm **trong** pane, không tràn ra
ngoài mép.

**Chi tiết vẽ:**

```
dải WINDOW   bg #101a2c; border-left 1px #233348
             nhãn "WINDOW" mono 10px/500 .14em #5b9cf0, top 6px
nến          thân width 58% ô; wick 1px
             xanh #3ecf8e khi close ≥ open, đỏ #f2555a khi ngược lại
cột volume   xanh #1f6b4c / đỏ #7a2b30  ← tối hơn nến, vì volume là phụ
area fill    linearGradient #8dc0f7 .20 → 0
close        polyline 1.8px #8dc0f7; linejoin+linecap round
             dot ĐẶC 5px #8dc0f7
EMA          polyline 1.3px #5b9cf0; dash "5 4"
             dot RỖNG 5px, border 1px #5b9cf0, bg #0e1116
10-bar avg   polyline 1.3px #4b5563; dot RỖNG 5px border #4b5563
bar volume   polyline 1.3px #e0913c; dot ĐẶC 5px #e0913c
crosshair    đường dọc 1px #3a5a80 trên MỌI pane
             dot 7px trên từng line tại slot đang trỏ
cột hover    overlay rgba(91,156,240,.07), full height pane, cursor crosshair
```

Dot **đặc** = giá trị đo được. Dot **rỗng** = giá trị dẫn xuất (EMA, đường trung
bình). Quy ước này áp cho cả bốn line.

**Trục giá (pane 4) — cách chống đè chữ:**

```
nhãn cao   left 8px; top 0
nhãn giá cuối  left 8px; top <clamp(PY, 9%, 91%)>; translateY(-50%)
               padding 1px 5px; radius 3px; bg #1b3454; fg #bcd8f8
nhãn thấp  left 8px; bottom 2px
```

Khi nhãn giá cuối nằm trong **22% trên** → **ẩn** nhãn cao. Trong 22% dưới → ẩn
nhãn thấp. Ẩn, không phải đẩy vị trí — đẩy thì hai nhãn cùng sai vị trí thay vì
một nhãn mất đi.

**Legend (dưới chart):** flex gap 16px, padding `0 15px 9px`, dot 8px + nhãn sans
12px label, → `mv.levelsChip` sans 12px label.

Legend key có `flex:0 0 auto` và `width`/`height` riêng cho từng loại — dot phải
`6px × 6px` mới tròn; đường phải `14px × 2px`. Thiếu `flex:0 0 auto` thì flex co
dot lại thành hình bầu dục.

**Hai ghi chú cuối:** mỗi cái sans 12px label, `text-wrap:pretty`, padding
`0 15px 7px` và `0 15px 11px`.

**Quy tắc SVG:** `preserveAspectRatio="none"` **chỉ** cho `<polyline>` /
`<polygon>`. Mọi chữ, dot, nến, cột volume là **DOM element định vị bằng `%`** —
không phải `<text>` hay `<rect>` trong SVG. SVG bị kéo méo theo bề rộng thì chữ
và hình tròn méo theo.

### 4.8 · Calm · two phases (band riêng, dưới Market View)

**Không** nằm trong sleeve tab — nó là band riêng, accent `#3ecf8e`.

```
head band  vạch accent + "Calm · two phases" sans 17px/600
           → "09:32 decides · 10:02 reads the price" mono 11px label

card
├── head  flex gap 14px; padding 7px 15px; border-bottom divider; bg inset; wrap
│   ├── "DECIDE" sans 10px/600 .12em primary + "09:32 · RECORDED" mono 11px label
│   ├── vạch dọc 1×11px #262d36
│   ├── "OBSERVE" sans 10px/600 .12em primary + "10:02 · RECORDED" mono 11px label
│   ├── câu sans 12px label
│   └── → "2 instruments · 5 rows · 4 gates each" mono 11px null
├── grid repeat(auto-fit, minmax(430px, 1fr))
│   mỗi instrument: border-left divider; padding 9px 14px 10px
│   ├── đầu  flex baseline gap 9px
│   │        mã mono 13px/600 primary · hướng mono 10px .1em label
│   │        → tally mono 11px #8ae6cc
│   ├── bảng  grid 1fr 108px 108px; gap 0 10px; margin-top 8px
│   │   hàng nhãn cột: ô trống · "DECIDE" · "OBSERVE"
│   │                  sans 9px/600 .12em null; text-align right
│   │   mỗi hàng dữ liệu (3 ô, đều có border-top #171b22):
│   │     ô nhãn   flex baseline gap 7px; padding 5px 0; min-width 0
│   │              nhãn sans 12px primary nowrap
│   │              + phụ sans 11px null, ellipsis
│   │     ô DECIDE / OBSERVE  padding 5px 0; text-align right
│   │                          mono 12px; nowrap
│   │       giá trị đọc được    fg primary
│   │       công thức/giờ       fg label   (vd "entry − 1.5 × ATR")
│   │       không đổi giữa 2 pha  in "—" màu #2a323d
│   └── gates  flex gap 8px wrap; margin-top 10px; padding-top 9px
│              border-top divider
│              "GATES" sans 9px/600 .12em null
│              mỗi gate: dot 4px + nhãn sans 11px label + giá trị mono 11px secondary
└── footer  padding 7px 15px; bg inset; border-top divider; sans 12px label
```

`auto-fit minmax(430px, 1fr)` — nhiều instrument hơn thì xuống một cột, không
tràn. Đây là điểm khác bản đầu: khối 4 cột cố định không scale.

Cột OBSERVE in `—` màu `#2a323d` cho hàng không đổi (ATR, stop distance, risk).
Đó là **void**, mờ hơn cả null — nó không phải "chưa có giá trị", nó là "cùng giá
trị với cột bên trái, và nói lại là nói dư".

---

## 5 · Số đo mốc (viewport 1714×1086)

Trang 3638px · cột 1520/380 · group band 60px · khe nhóm 14px

| Section | Cao |
|---|---|
| Now Monitor | 380 |
| Open Issues | 453 |
| Track 1 Runtime | 273 |
| Open Orders | 168 |
| Hàng 4 block | 206 |
| Open Positions | 121 |
| Today's Decision | 256 |
| Regime Monitor | 514 |
| Track 1 Market View | 567 |
| Calm two phases | 374 |

Đọc như **tỉ lệ**, không phải pixel bắt buộc — số phụ thuộc lượng dữ liệu giả
trong DC. So được là *thứ tự*, *padding*, và *tỉ lệ giữa các section*.

---

## 6 · Điều KHÔNG được làm

Mười luật. Luật 5 đã bắt được lỗi thật vì nó cấm một **cấu trúc** (đếm thẻ là
xong), không đặt ngưỡng méo. Bốn luật 1/2/4/6 dưới đây được viết lại theo đúng
kiểu đó — có phạm vi, có cách đếm, có ngoại lệ ghi thẳng.

---

### Luật 1 · Không quá bốn bậc xám cho chữ

**Đếm cái gì:** giá trị `color` đã tính (computed) của mọi element **có text node
không rỗng làm con trực tiếp**, lọc còn những giá trị *không có sắc* — định nghĩa
được: chuyển sang HSL, `saturation ≤ 6%`.

**Tập hợp đúng, đủ:** `#e8ebf0` · `#a8b1c0` · `#798394` · `#4b5563` — bốn.

**Không tính vào bốn bậc:**
- `#2a323d` (void) — chỉ hợp lệ khi text node của element đó, sau khi trim, **đúng
  bằng** `—` (U+2014). Bất kì chữ nào khác mang màu này là vi phạm.
- Mọi màu **có** sắc (`saturation > 6%`) — chúng thuộc luật 2, không thuộc luật này.
- `color` thừa hưởng trên element **không** có text node con trực tiếp — đếm nó là
  đếm cùng một bậc nhiều lần.

**Vi phạm** = xuất hiện một giá trị xám thứ năm ngoài tập trên.

### Luật 2 · Không tô màu số tiền và số lệnh

**Phạm vi:** element có text node khớp `/^[+−-]?[\d.,]+%?$/` sau khi trim, **hoặc**
mang một trong các nhãn nghiệp vụ: giá, stop, entry, target, side/direction, qty,
order id.

**Bắt buộc:** `color` của chúng phải là `primary`, hoặc `null`/`void` khi không có
giá trị.

**Ngoại lệ, và chỉ ba cái này** — nơi màu chính là thông điệp:

| Được tô | Vì |
|---|---|
| chỉ số PnL / drawdown | dấu của nó là thông tin |
| verdict pass/fail (`FAIL`, tally lane) | trạng thái, không phải số đo |
| chỉ báo degradation (`bar volume 0`, model age stale) | cảnh báo về chất lượng dữ liệu |

**Vi phạm** = một con giá, stop, side hoặc qty mang màu có sắc mà không thuộc ba
ngoại lệ trên. `7,689.75` màu xanh là vi phạm. `+447.72` PnL màu xanh thì không.

### Luật 4 · Metric compact không xếp dọc

**Định nghĩa "metric compact"** — nhận dạng được bằng ba điều kiện đồng thời:

1. element có **đúng hai** con element,
2. con thứ nhất là nhãn (sans, `font-size ≤ 12px`, không mono),
3. con thứ hai là giá trị (`font-family` mono).

**Bắt buộc:** element đó có `display:flex` và `align-items:baseline`, và hai con
nằm **cùng một dòng** — kiểm được: `|rect(con1).top − rect(con2).top| < 4px`.

**Không phải metric compact, đừng soi:**
- ô có **ba** con hoặc hơn (vd metric Regime Monitor: nhãn + giá trị + ghi chú) —
  chúng xếp dọc là **đúng spec**
- ô Track 1 Runtime (nhãn + câu mô tả) — giá trị là câu, không phải số
- ô Today's Decision tầng 1 (nhãn + số 18px) — xếp dọc là đúng

**Vi phạm** = một ô thoả cả ba điều kiện nhận dạng nhưng hai con lệch `top` ≥ 4px.

Sàng của bạn báo "4 metric xếp dọc" — kiểm lại xem chúng có phải nhóm 3-con ở
Regime Monitor hay Today's Decision không. Nếu đúng thì đó là dương tính giả của
sàng, không phải lỗi của trang.

### Luật 6 · Không quá hai màu nền cho một section

**Đếm cái gì:** `background-color` đã tính của mọi element **có diện tích ≥
600px²** bên trong section, sau khi bỏ những cái trong suốt
(`rgba(...,0)` / `transparent`).

**Không tính:**
- **chip, badge, pill, tab, nút** — mục 1 bảng "nền chip theo tone" cấp hẳn 6 nền
  cho chúng. Nhận dạng: diện tích < 600px², **hoặc** có `border-radius ≥ 3px`
  cùng với `padding` ngang ≤ 14px. Đây là chỗ sàng của bạn đang nhầm.
- **track / fill** của bar, gauge, posterior (`#141920` và fill của nó)
- **swatch, dot, vạch phân cách** — dưới ngưỡng diện tích
- **gradient** — group band và status band dùng gradient hai điểm dừng, tính là
  một nền
- **overlay hover** (`rgba(91,156,240,.07)`) — trạng thái tạm, không phải nền

**Tính:** nền của chính section, nền card (`panel`), nền header/footer trong card
(`inset`), nền hàng được nhấn (`rowBg`).

**Vi phạm** = ≥ 3 giá trị khác nhau trong tập đã tính.

Sàng của bạn báo "7 section quá hai nền" — gần như chắc là do đếm chip. Loại chip
ra rồi đếm lại; con số thật có thể là 0.

---

### Sáu luật còn lại (không đổi)

3. **Không lồng card.** Chia bằng vạch trong. Kiểm được: không có element mang
   `border-radius ≥ 6px` **và** `background` khác trong suốt nằm bên trong một
   element khác cũng thoả hai điều đó.
5. **Không dùng `<text>` trong SVG có `preserveAspectRatio="none"`.** Kiểm được
   bằng một câu: `svg[preserveAspectRatio="none"] text` phải trả về rỗng. Bản
   design có **0** thẻ `<text>` trong toàn bộ file — trục của nó là cột HTML 72px
   bên cạnh, nến và dot là `<div>` định vị tuyệt đối, nên không chỗ nào méo được.
   Đây là lý do luật cấm thẳng thay vì đặt mức méo cho phép.
7. **Không nhồi detail vào chip** — chip một từ. Kiểm được: text node của chip
   không chứa `·` và không quá 2 từ.
8. **Không hover chung khi hai chart không chung trục.** Xem G3.
9. **Không in placeholder** cho mục metadata không có dữ liệu — bỏ hẳn mục đó.
   Kiểm được: không có mục nào trong hàng metadata có text `--` hoặc rỗng.
10. **Không thay chữ trong repo bằng chữ trong spec này.** Repo đúng hơn về nội
    dung; spec này chỉ nói về hình.

---

## 7 · Breakpoint — cái nào được đổi, cái nào không

Spec ở trên mô tả trạng thái **≥1600px**. Repo có bốn ngưỡng đang chạy thật, và
chúng **không phải** thứ suy ra từ bản design — chúng là hợp đồng của repo. Bảng
dưới nói rõ ngưỡng nào được phép chạm.

| Ngưỡng | Là gì | Được đổi? |
|---|---|---|
| **680px** | `matchMedia('(max-width: 680px)')` ở `realtime.js:11` (`compactIssueMedia`) quyết định issue đầu có tự mở | ❌ **TUYỆT ĐỐI KHÔNG.** Con số này là hợp đồng giữa CSS và JS |
| **681px** | `.mode-badge { white-space: nowrap }` — chỉ áp từ 681px lên | ❌ Không. Ở 390px `nowrap` làm badge rộng 57px → 106px, đẩy cả hàng header vượt viewport 35px |
| **1051px** | `main.is-two-column` bật grid hai cột | ⚠️ Không nên. Dưới ngưỡng này base đã stack sẵn |
| **1600px** | hàng metrics từ 2 cột lên 4 cột | ✅ Được, đây là ngưỡng của bản design |

### Quy tắc 680px, viết lại cho rõ

`next.css` ghi thẳng trong header của nó (rule 3):

> *Narrow-screen breakpoints must use EXACTLY 680px — that number is a contract
> with realtime.js. A different value creates a band where the page lays out
> narrow while the script still behaves wide.*

Nghĩa là: mọi `@media (max-width: …)` cho màn nhỏ phải là **680px**, không phải
640, không phải 700, không phải 768. Thêm một ngưỡng khác là tạo ra một dải bề
rộng mà trang bố trí kiểu hẹp trong khi script vẫn xử sự kiểu rộng.

### Hành vi từng ngưỡng

**≥1600px** — trạng thái spec ở trên. Hàng metrics 4 cột `1.25fr 1fr 1fr 1fr`.

**1051–1599px** — hàng metrics xuống **2 cột** `repeat(2, minmax(0,1fr))`.
Cột phải vẫn 380px, vẫn `position:sticky; top:58px; height:calc(100vh - 58px)`.

> Vì sao không giữ 4 cột: ở 1440×900 đo được "0.00%" của Risk in đè
> "Protection" của Exposure. Bốn cột của bản design đi kèm `min-width:1900px`
> của bản design — lấy cột mà không lấy bề rộng thì không phải là bản design,
> đó là một vụ đè chữ.

**≤1050px** — một cột. Cột phải bỏ sticky: `position:static; height:auto`.

**≤680px** — thêm vào một cột:
- group band: `padding:13px 14px 11px; gap:10px; flex-wrap:wrap`, và **ẩn phụ đề**
  (`.group-note { display:none }`) — phụ đề giải thích nhóm nhưng không mang số
  nào, mất nó không tốn gì về mặt vận hành
- section padding: `18px 22px` → **`14px 16px`**
- hàng metrics: `minmax(0, 1fr)` — một cột
- `.mode-badge` bỏ `nowrap`

### Chỗ spec này KHÔNG nói gì

Grid `352px 1fr` (Now Monitor, Open Issues), grid `300px 1fr` (Regime Monitor),
`repeat(4,1fr)` (Track 1 Runtime), `repeat(5,1fr)` (Today's Decision), và
`repeat(auto-fit,minmax(430px,1fr))` (Calm) — bản design không định nghĩa hành vi
hẹp cho những cái này.

**Chart trong Price context ở màn hẹp cũng không được định nghĩa.** Bản design
khai `min-width:1900px`, nên chưa bao giờ có ai vẽ nó ở 390px. Ba câu chưa có
đáp án, và spec này **không** trả lời được:

- 22 slot trên ~350px là ~16px mỗi slot. Cell lane còn đọc được, nhưng cột hover
  16px thì bấm bằng ngón tay là chuyện khác.
- 5 mốc nhãn giờ trên 350px sẽ đè nhau. Giảm còn 2–3 mốc là quyết định thiết kế
  chưa ai duyệt.
- Cột trục 72px chiếm 18% bề rộng ở 390px.

**Đừng tự phát minh.** Xem `next.css` hiện có xử lý thế nào rồi giữ nguyên. Nếu
chưa có xử lý thì để nguyên — một grid tràn ở 900px là vấn đề đã tồn tại, không
phải vấn đề nhiệm vụ này tạo ra, và sửa nó ngoài phạm vi thì thành thay đổi
không ai duyệt.

> **Lưu ý cho phép phản-scale (`undoPaneStretch`):** hệ số `k = sy/sx` phụ thuộc
> bề rộng thật của pane. Ở 1900px pane kéo 1,606/1,000 nên `k` đáng kể; ở 1440px
> chỉ 1,011 nên phép này gần như không làm gì — và đó chính là lý do test phải
> ghim ở 1900px, không phải 1440px. Ở 390px `sx` sẽ khác hẳn lần nữa. Nếu định
> khẳng định phép này đúng ở màn hẹp thì phải đo ở màn hẹp; suy ra từ số ở 1900px
> là không có cơ sở.

---

## 8 · Giữ nguyên — spec này không nói tới nghĩa là ĐỪNG CHẠM

Bản design là bản **vẽ**, không phải bản **dựng**. Nó thiếu nhiều thứ mà repo có,
và thiếu ở đây nghĩa là *chưa vẽ*, không phải *nên bỏ*.

### Tooltip

Repo có hệ riêng: `class="has-tip tip-bottom"` / `tip-right`, cộng
`data-tooltip="…"` và `tabindex="0"`. Dùng khắp `index.html` — trên `zone-title`,
trên từng nhãn metric, trên `source-note`, trên chip scheduler.

Bản design **không có tooltip nào**. Giữ toàn bộ của repo.

Đặc biệt: `next.js` có hàm ghi tooltip vào node (`el.dataset.tooltip = txt` —
"the sentence stays one hover away"). Đó là cơ chế cố ý để rút gọn chữ trên màn
mà không mất câu giải thích. Đừng bỏ.

### Accessibility

Repo có, bản design không có:

| Thuộc tính | Ở đâu |
|---|---|
| `role="listbox"` / `role="option"` / `aria-selected` | `nowMonitorList`, `openIssueList` |
| `aria-expanded` | nút issue, nút job, nút event |
| `aria-pressed` | nút tab Jobs / Events |
| `aria-live="polite"` | `nowMonitorDetail`, `openIssueDetail` |
| `aria-label` | `statusRail`, `metrics`, `mv-chart`, `dd-gauge`, `journal` |
| `aria-current="page"` | nav item đang mở |
| `role="meter"` | gauge drawdown |
| `role="img"` + `aria-label` | `marketViewChart` |
| `tabindex="0"` | mọi node có tooltip |

**Giữ tất cả.** Sửa hình mà làm rơi `aria-live` là làm người dùng screen reader
mất thông báo khi panel đổi nội dung.

### Cấu trúc HTML repo đang dựa vào

| Thứ | Vì sao không được bỏ |
|---|---|
| Mọi `id` | `realtime.js` resolve bằng `getElementById`, **nhiều chỗ gán property không check null** — thiếu một id là chết cả trang, không phải chết một tile |
| `<details id="openIssuesShell">` | `realtime.js:3395` set `.open` trên nó |
| `.metrics-figures` (đang `hidden`) | `next.js` làm rỗng và ẩn, **không xoá** — nó là container `realtime.js` có thể ghi vào lại; xoá thì thứ ghi vào sau đó bay khỏi trang |
| `[data-journal-view]` | listener gắn theo attribute này |
| `.market-view-section` | `next.js` delegate hover từ đây vì nó là node tĩnh, sống qua mọi lần re-render 8s |

### Quy tắc thay cho "ẩn"

`next.css` rule 2, nguyên văn:

> *NEVER remove an element from the page. To hide something, use `display: none`
> and keep the id.*

Áp dụng cả cho nhiệm vụ này. Muốn bỏ một tile → `display:none`, giữ id. Không
xoá node.

### Thứ tự nạp stylesheet

```
fonts.css → realtime.css → tokens.css → next.css → skin-e.css
```

`skin-e.css` nạp **sau** `next.css`. Nên rule mới trong `next.css` phải viết
**cụ thể hơn một bậc** so với rule tương ứng trong skin, chứ không dựa vào thứ tự
nạp. `next.css` đã làm vậy ở phần "Design alignment" — làm theo đúng cách đó.
