# Bảng kiểm phủ

Quét trực tiếp template của `Realtime Dashboard.dc.html` để trả lời một câu:
**có component nào trong bản design mà ba file spec chưa mô tả?**

Số đo, không phải cảm nhận:

| Đại lượng | Số |
|---|---|
| `<sc-for>` (nhóm lặp) | 52 lần dùng, **48 danh sách riêng biệt** |
| `<sc-if>` (nhánh trạng thái) | **18** |
| `grid-template-columns` riêng biệt | **18** |
| `<svg>` | 2 |
| `<text>` trong SVG | **0** |
| hole `{{ }}` riêng biệt | 296, thuộc 67 gốc |

`<text> = 0` là bằng chứng thực nghiệm cho luật 5 của mục 6: bản design không vẽ
chữ trong SVG ở đâu cả, nên không chỗ nào méo được. Luật đó cấm một cấu trúc mà
bản design vốn không có — không phải một ngưỡng ai đó chọn.

---

## 48 danh sách — mô tả ở đâu

| Danh sách | Tài liệu |
|---|---|
| `monitor` `monitorList` | ANATOMY · Now Monitor |
| `issues` (+ `detail`) | ANATOMY · Open Issues |
| `runtime` | ANATOMY · Track 1 Runtime |
| `perf` `expo` | ANATOMY · Hàng bốn block |
| `decision` `decisionGroups` | ANATOMY · Today's Decision |
| `modelInputs` `regimeMetrics` `posterior` `features` `regimeLegend` `regimeRuns` | ANATOMY · Regime Monitor |
| `journalTabs` `jobs` `j.log` | ANATOMY · Job journal |
| `events` | ANATOMY · Event journal |
| `clocks` | ANATOMY · Source Clocks |
| `sleeveTabs` | SPEC 4.1 |
| `sessions` | SPEC 4.2 |
| `mv.chips` `mv.meta2` | SPEC 4.3 |
| `mvTabs` | SPEC 4.4 |
| `lanes` `ln.cells` `slotCells` `legend` | SPEC 4.5 |
| `grid.rows` `gr.cells` `readings` | SPEC 4.6 |
| `hoverRead` `price.bars` `price.cols` `price.marks` `price.times` `price.grid` `price.axis` `chartKeys` `chart.grid` `chart.closeDots` `chart.emaDots` `chart.avgvDots` `chart.vol` `seriesCols` | SPEC 4.7 |
| `instruments` `iv.rows` `iv.gates` | SPEC 4.8 |

Không có dòng trống. `price.axis` từng chỉ được nhắc trong bảng pane — nay đã có
giải phẫu riêng ở 4.7 (3 mốc, `translateY` theo mốc).

## 18 nhánh trạng thái — mô tả ở đâu

| Nhánh | Tài liệu |
|---|---|
| `s.isToday` | SPEC 4.2 (chip "today") |
| `mv.showRules` `mv.showDetector` `mv.showPrice` | SPEC 4.5 / 4.6 / 4.7 |
| `hover.on` ×4 | SPEC 3 (hover đồng bộ) + 4.7 |
| `hover.hasClose` `hover.hasVol` | SPEC 4.7 — dot crosshair **ẩn** khi slot đó không có số, không vẽ ở `top:0` |
| `chart.showHi` `chart.showLo` | SPEC 4.7 (luật 22%) |
| `mv.showCalm` | SPEC 4.8 |
| `showJobs` `showEvents` | ANATOMY · Job journal / Event journal |
| `j.hasTag` `j.open` | ANATOMY · Job journal |
| `e.hasTimes` | ANATOMY · Event journal |

## 18 grid — tất cả đều có mặt

`1fr 380px` · `repeat(4,1fr)` · `352px 1fr` · `1fr 1fr` ·
`1.2fr .7fr .7fr .5fr .9fr 1.1fr .6fr` · `1.25fr 1fr 1fr 1fr` · `repeat(5,1fr)` ·
`repeat(3,1fr)` · `300px 1fr` · `60px 1fr 50px` · `1fr auto auto` · `1fr auto` ·
`246px 1fr 110px` · `1.15fr 1fr` · `1fr 72px` ·
`repeat(auto-fit,minmax(430px,1fr))` · `1fr 108px 108px` · `62px 46px 1fr`

---

## Kết luận — và chỗ dễ hiểu sai

**Mô tả 100% những gì bản design CÓ:** đạt. 48/48 danh sách, 18/18 nhánh, 18/18
grid.

**Mô tả 100% những gì dashboard CẦN:** không đạt, và không thể đạt từ bản design
này.

Hai câu đó khác nhau, và khoảng cách giữa chúng chính là phần B của `ROUND_2.md`.
Bản design vẽ **một** trạng thái mỗi section — trạng thái yên. 18 nhánh `sc-if`
kể trên là 18 nhánh *hiển thị* (tab nào đang mở, hover hay không), **không phải**
18 trạng thái *dữ liệu*. Không có nhánh nào cho "có position", "có order", "levels
được publish", "label check fail", "status band mức bad".

Nói cách khác: bản design đầy đủ về **hình**, và mỏng về **trạng thái**. Tài liệu
không sửa được điều đó — nó chỉ ghi lại trung thực.

### Nếu cần đủ cả trạng thái

Đó là việc thiết kế mới, không phải việc viết tài liệu. Thứ tự theo giá trị vận
hành:

1. **Market View khi `levels_armed === true`** — đường entry/stop/target trên pane
   nến, bảng levels, ba trạng thái đường giá. Đây là phần lớn giá trị của section.
2. **Status band mức `watch` và `bad`** — gradient đổi màu, và câu điều kiện dài
   (repo dựng từ ~14 nhánh).
3. **Now Monitor có incident thật** — 8 nguồn, mỗi nguồn một hình dạng.
4. **Open Positions / Open Orders / Today's Decision có hàng dữ liệu.**
5. **Track 1 Runtime 3 trạng thái còn lại** · **Regime Monitor khi check fail.**

Mỗi mục là một lần thiết kế riêng, có duyệt riêng. Đừng để Claude Code tự vẽ —
prompt vòng 2 đã có dòng cấm việc đó.
