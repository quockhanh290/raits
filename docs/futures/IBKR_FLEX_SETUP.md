# IBKR Flex Setup For Paper Monitoring

Muc tieu: lay transaction history tu IBKR lam evidence doc lap cho Paper dashboard.

Nguon chinh thuc:

- IBKR Flex Web Service dung 2 buoc: `/SendRequest` de tao report, sau do `/GetStatement` de tai report bang `ReferenceCode`.
- Request can `Current Token`, `Flex Query ID`, `v=3`, va `User-Agent` header.
- Endpoint `/SendRequest` co pacing limit 1 request/second va toi da 10 requests/minute.
- Flex token/query duoc tao trong Client Portal -> Reporting -> Flex Queries -> Flex Web Service Configuration.

## 1. Tao Flex token trong IBKR

Trong IBKR Client Portal:

1. Vao `Reporting`.
2. Chon `Flex Queries`.
3. Mo `Flex Web Service Configuration`.
4. Enable Flex Web Service.
5. Generate token.
6. Copy `Current Token`.

Khong commit token vao repo. Dat token qua environment variable.

## 2. Tao Flex Query

Trong `Flex Queries`, tao query cho transaction/activity history cua paper account.

Khuyen nghi:

- Account: `DUR125337` neu day la paper account dang dung.
- Section: transaction history / trades / executions.
- Include fields can reconcile: date/time neu co, symbol, buy/sell, quantity, price, commission, net amount, order id/perm id neu Flex UI cho phep.
- Output/report format: uu tien CSV neu Client Portal cho chon, vi repo da co `global_index/statement.py` parse CSV Transaction History.
- Date range: co the de default trong query, hoac override bang `--from-date` / `--to-date`.

Sau khi save, copy `Flex Query ID`.

## 3. Pull report

### Keo tay, mot lan

`$env:` chi song trong dung cua so PowerShell do. Dung cho mot lan keo tay:

```powershell
$env:IBKR_FLEX_TOKEN = "paste-current-token-here"
$env:IBKR_FLEX_QUERY_ID = "paste-query-id-here"
python monitor\flex_pull.py --from-date 20260810 --to-date 20260813
```

### Cho job FLEX_PULL 22:20 ET — phai dat ben vung

**Cach tren KHONG bao gio toi duoc scheduler.** Scheduler la mot tien trinh khac; no
sinh `monitor.flex_pull` lam tien trinh con, va con thua huong moi truong cua **cha**,
duoc chup lai luc scheduler khoi dong. Mot bien dat bang `$env:` trong terminal cua ban
khong nam trong do, hom nay hay ngay mai cung vay.

Do la ly do dem 2026-08-17 job hong sau **0 giay** voi `Missing env var
IBKR_FLEX_TOKEN` trong khi cung token do van keo tay duoc: bien co that, nhung o trong
mot pham vi khong the voi toi.

Dat ben vung (mot lan, khong can quyen admin):

```powershell
setx IBKR_FLEX_TOKEN "paste-current-token-here"
setx IBKR_FLEX_QUERY_ID "paste-query-id-here"
```

Roi **khoi dong lai scheduler**. `setx` ghi vao pham vi User; tien trinh dang chay
khong doc lai — no chi chup moi truong mot lan luc sinh ra. Khong khoi dong lai thi
dem sau van hong y het.

Kiem tra da toi noi chua, tu **mot cua so moi** (cua so dat `setx` khong tu thay):

```powershell
[Environment]::GetEnvironmentVariable('IBKR_FLEX_TOKEN','User').Length
```

Ra `0` hoac rong tuc la chua dat — `flex_pull` goi `.strip()` truoc khi kiem, nen mot
gia tri toan khoang trang cung truot y nhu khong co.

Output duoc luu vao:

```text
monitor/inputs/ibkr_flex/
```

Folder nay da duoc git-ignore vi report co du lieu account.

## 3b. Flex chi doi chieu toi HOM QUA — day la tran, khong phai loi

Sao ke Flex khong phai nguon thoi gian thuc va khong bao gio la. Do duoc 2026-08-18:

| xin toi | ket qua |
|---|---|
| 17/8 (phien dang chay) | `code=1004 Statement is incomplete at this time` |
| 16/8 | 35.085 byte, binh thuong |

Luc do la **00:05 ET** — hon 6 tieng sau gio dong cua va gan 2 tieng sau khung chay
22:20 ET. So cua broker cho phien dang chay chua ton tai vao luc doi chieu chay.

Nen job truyen `--to-date` = **hom qua**. Do tre mot phien o phia broker la ban chat
chu khong phai lua chon, va ghim tuong minh con hon de khoang mac dinh cua query quyet
dinh — bang khi do noi ro duoc no dang phu toi dau.

**He qua tren bang Paper Evidence:** moi con so cot Flex chi dung TOI ngay do. Bang mang
truong `flex_coverage` va in ra `Flex covers through <ngay>` ngay tren the ket luan.

Mot lenh dong sau ngay do duoc phan loai `AWAITING_FLEX`, **khong** phai `unresolved`:
cau hoi chua toi luot hoi thi khong duoc chan go-live. No van duoc dem va van hien,
chi duoi dung ten cua no. Chi ap dung khi mat DUY NHAT nguon Flex — ban phat lai thieu
thi van la bat dong that va van chan.

Phan loai lai chi chay khi biet CHAC tam phu, tuc doc duoc tu khoang da xin trong ten
tep. Neu chi suy ra tu khop lenh cuoi cung thi khong — ban ke hien tai xin toi 13/8
nhung khop lenh cuoi la 11/8, tin vao ngay suy ra la hut hai ngay, va hut ve phia nguy
hiem: bien mot bat dong that thanh "chua toi luot".

**Chua chung minh:** IBKR co luon xong phien D-1 truoc 22:20 ET ngay D khong. Moi co mot
quan sat thanh cong. Neu hut, `flex_pull` se noi `code=1004` chu khong im, va cach chua
la doi khung chay muon hon.

## 4. Reconcile voi trade log

Neu report la CSV Transaction History dung format parser hien co:

```powershell
python -X utf8 global_index\reconcile_statement.py --csv monitor\inputs\ibkr_flex\<file>.csv
```

Chay read-only truoc, khong dung `--backfill` cho Paper dashboard input.

Ket qua dung de quyet dinh:

- `PASS - the log agrees with the statement`: co the dung lam statement evidence.
- `FAIL - missing/mismatched`: dua vao Paper gaps/worksheet, khong tu pass gate.

## 5. Paper dashboard mapping

Dung duoc:

- STP fill/history: statement la broker-authored evidence.
- Trade log completeness: statement vs `trade_log.jsonl`.
- Commission/fees neu statement co field.
- Paper P&L actual fill history.

Van can quyet dinh:

- Cach convert statement reconcile result thanh `monitor/paper_inputs.json`.
- Co luu raw statement only, hay them monitoring-only summary JSON.
- Neu Flex tra XML thay vi CSV, can them parser XML hoac doi query output sang CSV.
