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

PowerShell:

```powershell
$env:IBKR_FLEX_TOKEN = "paste-current-token-here"
$env:IBKR_FLEX_QUERY_ID = "paste-query-id-here"
python monitor\flex_pull.py --from-date 20260810 --to-date 20260813
```

Output duoc luu vao:

```text
monitor/inputs/ibkr_flex/
```

Folder nay da duoc git-ignore vi report co du lieu account.

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
