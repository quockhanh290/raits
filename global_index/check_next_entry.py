# check_next_entry.py — kiểm tra có entry HÔM NAY không (để biết có P0c hôm nay không)
#
# KHÔNG dự đoán tương lai. Chỉ dùng regime ĐÃ BIẾT:
#   Regime hôm nay = HMM decode từ SPY close ngày hôm qua (last bar trong spy_daily_live.csv).
#   Label_regimes() dùng HMM frozen 2024-12-31 — không predict, chỉ decode historical data.
#
# desired_basket(cutoff=ngày_mai) = "vị trí nào backtest cho là MỞ vào sáng ngày mai?"
#   = "có entry HÔM NAY mà chưa exit hôm nay không?"
#   = CÂU HỎI ĐÚNG cho việc quyết định P0c hôm nay.
#
# Chạy mỗi sáng sau update_spy_csv (để có SPY close ngày hôm qua):
#   cd d:\raits
#   python <đường_dẫn_script>

import sys, datetime, pandas as pd
sys.path.insert(0, '.')
from futures._validated_core import load_parquet, benchmark_daily, label_regimes
from futures.basket import BASKET, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from pathlib import Path

dfs = {n: load_parquet(str(Path('data/cache/futures') / data_filename(c))) for n, c in BASKET.items()}
bench = benchmark_daily('spy_daily_live.csv')
labels = label_regimes(bench, '2018-01-01', 3, '2024-12-31')
costs = costs_for_basket(slippage_ticks=2.0)

today    = datetime.date.today().isoformat()
tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
cutoff   = pd.Timestamp(tomorrow)

# Regime hôm nay (từ SPY close đã biết — không predict):
spy_last = bench.index[-1].date().isoformat() if hasattr(bench.index[-1], 'date') else str(bench.index[-1])
_spy_s = pd.Series(labels).sort_index()
_r = _spy_s.asof(pd.Timestamp(today))
today_regime = str(_r) if _r is not None and not (isinstance(_r, float) and pd.isna(_r)) else 'unknown'
print(f'Ngay hom nay : {today}')
print(f'SPY last bar : {spy_last}  (regime decode tu bar nay)')
print(f'Regime hom nay: {today_regime}')
print(f'=== desired_basket cutoff={tomorrow} (vi tri mo vao sang mai = entry hom nay) ===')

dfs2 = {}
for inst in dfs:
    df = dfs[inst]
    tz = df.index.tz
    dfs2[inst] = df[df.index <= cutoff.tz_localize(tz)]

any_entry = False
for inst_k, sig in SwingTFEngine().desired_basket(dfs2, labels, costs).items():
    if sig:
        dirn  = sig['direction']
        entry = sig['entry']
        stop  = sig['stop']
        eday  = sig['entry_day']
        print(f'  {inst_k}: dir={dirn} entry={entry:.2f} stop={stop:.2f} entry_day={eday}')
        any_entry = True
    else:
        print(f'  {inst_k}: None')

print()
if any_entry:
    print(f'=> Co entry hom nay ({today}) -> P0c: chay --print-signals luc 14:05 ET, so 4 truong')
else:
    if today_regime in ('Normal', 'Stress'):
        print(f'=> Regime={today_regime} nhung khong co entry backtest hom nay. Cho ngay co signal.')
    else:
        print(f'=> Regime={today_regime} (khong phai Normal/Stress) -> khong co entry. Cho ngay doi regime.')
