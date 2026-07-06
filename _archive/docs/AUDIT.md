# RAITS Structural Audit — Full Report
_Generated: 2026-07-01_

---

## 1. Cây thư mục 3 tầng (có nhãn nhóm)

```
D:\raits\                               [REPO ROOT]
├── raits/                              STOCKS — Python package (editable install)
│   ├── backtest/                       engine.py, engine_refactored.py, wfo.py, wfo_grid.py,
│   │                                   metrics.py, data_types.py, equity_tracker.py, trade_log.py,
│   │                                   orb_session.py, reject_funnel.py
│   ├── coordinator/                    regime_coordinator.py, strategy_router.py, conflict_resolver.py
│   ├── data/                           raits_polygon_fetcher.py, raits_data_cache.py, raits_data_pipeline.py, ...
│   │   └── cache/                      [DATA] 2,803 MB total
│   │       ├── data/       140,469 parquet 5-min stocks  ~1,570 MB   ← AUTHORITATIVE stock data
│   │       ├── daily/      40 daily parquet               ~4 MB
│   │       ├── snapshots/  66 WFO result pkl (results_*.pkl)
│   │       ├── metadata/   pkl duplicates của cache/data/
│   │       └── *.pkl       market_data, window_debug, earnings, vix, ...
│   ├── decision/                       decision_unit.py, types.py
│   ├── hmm/                            engine.py, features.py, state_sorting.py,
│   │                                   retraining.py, volatility_override.py
│   ├── live/                           runner.py, broker.py, context_feed.py,
│   │                                   reconciliation.py, verify_context.py [M in git]
│   ├── models/hmm/                     [DATA] 55,730 pkl files ~78 MB
│   ├── risk/                           circuit_breakers.py, position_sizer.py,
│   │                                   pdt_guard.py, portfolio.py
│   ├── strategies/                     orb.py, vwap_mr.py, trend_follow.py,
│   │                                   cash_defense.py, universe_scanner.py
│   ├── tests/                          pytest suite (decision/, fixtures/, live/, risk/, unit/)
│   ├── configs/                        final_params.yaml (LOCKED: orb=20/bb=1.5/ema=30),
│   │                                   wfo_report.json, ...
│   ├── utils/                          [EMPTY — only __init__.py]
│   ├── raits/                          *** NESTED PACKAGE — legacy path artifact ***
│   │   ├── data/cache/     [DATA] ~14 MB (QQQ + others, parquets từ CWD=D:\raits\raits)
│   │   ├── scripts/        ~130 research/diagnostic scripts
│   │   ├── strategies/strategies/orb.py   [ORPHAN COPY — uncertain dead]
│   │   └── tests/decision/              [ORPHAN TEST COPY — uncertain dead]
│   └── [50+ check_*.py, diag_*.py, sim_*.py]  — raits-level scratch scripts
│
├── futures/                            FUTURES — self-contained production engine
│   ├── _validated_core.py              Source of truth (imports raits.hmm + raits.strategies.trend_follow lazily)
│   ├── basket.py                       Rổ 4 config (MES/MNQ/MYM/M2K)
│   ├── swing_tf.py, stress_mid.py, runner.py
│   ├── sizer.py, net_exposure.py, circuit_breaker.py, cost.py
│   ├── backtest_combined.py, backtest_system.py
│   ├── reconcile_gd0.py, reconcile_stress.py
│   └── swing_tf_harness.py, fetch_es_continuous.py, beta_check.py
│
├── global_index/                       FUTURES — NKD expansion
│   ├── _core.py                        Verbatim copy của futures/_validated_core primitives
│   ├── specs.py, regime.py, fetch.py
│   ├── swing_tf_powerhour.py, combined.py, combined_system.py, deploy_sim.py
│   ├── cap_sweep.py, priority_sweep.py, edge_test.py, wfo.py, vault.py
│   ├── net_exposure_multi.py, risk_diagnostic.py, ...
│   └── data/                           NKD_continuous_1m_8y.parquet ~43 MB
│                                       ← DUPLICATE với nonequity/data/ (xem DEBT-3)
│
├── orb_futures/                        EXPERIMENTAL — ORB on Rổ 4 (unvalidated)
│   ├── _orb_core.py                    Imports từ futures/ (validated_core, basket, cost, swing_tf)
│   └── edge_test.py, gap_fill.py, overnight.py
│
├── tier2/                              EXPERIMENTAL — ZN/ZB/6E structure probe (self-contained)
│   ├── structure_test.py, fetch.py
│   └── data/  ZN/ZB/6E daily parquets ~0.4 MB
│
├── xsect/                              EXPERIMENTAL — cross-sectional momentum probe (self-contained)
│   └── momentum_structure.py
│
├── nonequity/                          EXPERIMENTAL — gold/crude/NKD daily probe (self-contained)
│   ├── _core.py                        Verbatim copy của futures/_validated_core
│   ├── specs.py, fetch.py, mr_explore.py, swing_tf_daily.py, swing_tf_powerhour.py
│   └── data/  GC/CL/NKD parquets ~170 MB (NKD DUPLICATE với global_index/data/)
│
├── configs/                            ROOT configs [DEBT — giá trị khác raits/configs/!]
│   ├── final_params.yaml               [STALE: orb=15/bb=2.5/ema=30 — SAI so với vault]
│   └── wfo_report.json, wfo_megacap_report.json, ...
│
├── data/                               ROOT data cache
│   └── cache/
│       ├── futures/   ES/NQ/YM/RTY/NKD continuous parquets  ~452 MB ← AUTHORITATIVE futures data
│       ├── data/      9 SPY_5min parquets                    ~0.1 MB [UNCERTAIN — possible orphan]
│       └── metadata/  pkl duplicates của data/               [UNCERTAIN — possible orphan]
│
├── models/hmm/                         [DATA] 38,412 pkl files ~48 MB (dùng khi CWD=D:\raits)
├── tests/                              Root-level tests (stocks + integration)
├── scratch/                            One-off scripts + JSON results
├── CodeBase/                           [DEAD] ZIP archives của old milestones
├── docs/, logs/
└── [60+ root .py scripts]              SCRATCH — gate*.py, diagnose_*.py, pooled_*.py,
                                        hmm_validate.py, inspect_wfo.py, ...
```

---

## 2. Dependency Graph

```
raits.hmm ◄──────────────────────────────────────────────────────────────────────────┐
raits.strategies.trend_follow ◄──────────────────────────────────────────────────┐   │
                                                                                  │   │
futures/_validated_core.py ─────────────────────────── lazy import inside fn ────┘───┘
futures/basket.py, swing_tf.py, stress_mid.py,
futures/runner.py, sizer.py, net_exposure.py, cost.py, circuit_breaker.py
    │
    │  ← global_index/ imports từ futures/ (10+ files)
    ▼
global_index/
  combined.py, combined_system.py, deploy_sim.py,
  cap_sweep.py, priority_sweep.py, edge_test.py,
  hold_vs_entry_diagnostic.py, reject_*.py, risk_diagnostic.py,
  vault.py, wfo.py, swing_tf_powerhour.py, regime.py
       imports: futures._validated_core (backtest_swing_tf, label_regimes, ...)
                futures.basket (BASKET, data_filename)
                futures.swing_tf (SwingTFEngine, costs_for_basket)
                futures.stress_mid (StressMidEngine — conditional)
                futures.circuit_breaker (CircuitBreaker — conditional)
                global_index._core, global_index.specs, global_index.regime,
                global_index.net_exposure_multi

orb_futures/_orb_core.py ──── imports: futures._validated_core, futures.basket,
                                        futures.cost, futures.swing_tf
orb_futures/gap_fill.py, overnight.py ─ import from orb_futures._orb_core only

nonequity/                               (self-contained, NO futures/ imports)
  _core.py ── verbatim copy của futures/_validated_core primitives
  swing_tf_powerhour.py, swing_tf_daily.py, mr_explore.py ── imports nonequity._core

tier2/  ─────────────────────────────── self-contained (no cross-imports)
xsect/  ─────────────────────────────── self-contained (no cross-imports)

raits/ (package)
  backtest.engine ──── imports raits.strategies.*, raits.hmm.*, raits.coordinator.*,
                                raits.risk.*, raits.decision.*
  backtest.engine_refactored ── same set + raits.live.*
  live.context_feed ── imports raits.backtest.data_types, raits.decision.types, raits.live.runner
  live.verify_context ── imports raits.backtest.engine_refactored, raits.live.context_feed
  coordinator.strategy_router ── imports raits.coordinator.regime_coordinator

raits/ ──────────────────────────────── NEVER imports futures/, global_index/, or any experimental
```

**Điểm quan trọng nhất:**

- `futures/_validated_core.py` import **cả hai**: `raits.hmm.engine` (lazy, trong `label_regimes()`) **VÀ** `raits.strategies.trend_follow` (lazy, trong `backtest_swing_tf()`).
- `futures/__init__.py` docstring nói "ONLY raits.hmm" — **đó là sai/lỗi thời**.
- `raits/` **KHÔNG BAO GIỜ** import từ `futures/`, `global_index/`, hay bất kỳ experimental module nào.
- `global_index/` phụ thuộc nặng vào `futures/` → transitively phụ thuộc vào `raits.hmm` + `raits.strategies.trend_follow`.

---

## 3. Bảng phân loại Dead/Live

> **Phương pháp:** DEAD chỉ khi cả 3 check đều trống: (a) Python imports, (b) path-string refs, (c) data files. Thiếu bất kỳ check nào → UNCERTAIN.

| Module/Folder | Nhóm | Trạng thái | (a) Import evidence | (b) Path-string evidence | (c) Data evidence |
|---|---|---|---|---|---|
| `raits/hmm/` | STOCKS SHARED | **LIVE** | `futures/_validated_core.py`, `raits/backtest/engine.py`, `gate2_edge_harness.py`, 10+ files | Scripts ref `raits/models/hmm/` | Writes `models/hmm/*.pkl` |
| `raits/strategies/trend_follow.py` | STOCKS SHARED | **LIVE** | `futures/_validated_core.py` — dep của toàn bộ futures production | `diagnose_*.py` scripts | n/a |
| `raits/strategies/` (other) | STOCKS | **LIVE** | `raits/backtest/engine.py`, `tests/`, `gate2_edge_harness.py` | Diagnose scripts | n/a |
| `raits/backtest/engine.py` | STOCKS | **LIVE** | 13+ scripts import `BacktestEngine` (vault_test, window_debug, per_strategy_diagnostic...) | `raits/check_*.py` hardcode paths | Writes `raits/data/cache/snapshots/*.pkl` |
| `raits/backtest/engine_refactored.py` | STOCKS | **LIVE** | `raits/live/verify_context.py`, `diagnose_parallel_run.py`, `diagnose_first_divergence.py` | n/a | n/a |
| `raits/backtest/wfo.py` | STOCKS | **LIVE** | `wfo_real_run.py`, integration tests | Output → `configs/final_params.yaml` | Writes configs |
| `raits/coordinator/` | STOCKS | **LIVE** | `raits/backtest/engine.py`, `tests/coordinator/` | n/a | n/a |
| `raits/decision/` | STOCKS | **LIVE** | `raits/live/context_feed.py`, `raits/tests/decision/` | n/a | n/a |
| `raits/risk/` | STOCKS | **LIVE** | `raits/backtest/engine.py`, `tests/` | n/a | n/a |
| `raits/live/` | STOCKS | **LIVE** | `raits/tests/live/`, `raits/live/verify_context.py` | verify_context.py = M in git | n/a |
| `raits/data/` | STOCKS DATA | **LIVE** | Imported by 20+ files | `raits/data/cache/` hardcoded in many scripts | 140k parquet files |
| `raits/models/hmm/` | STOCKS DATA | **LIVE** | Default `model_dir="models/hmm"` trong `HMMEngine.__init__` | Scripts ref path | 55,730 pkl files |
| `raits/configs/` | STOCKS | **LIVE** | `vault_test.py`, `verify_context.py`, `window_debug.py`, `wfo_real_run.py` đọc `final_params.yaml` | Hardcoded trong 4+ scripts | n/a |
| `raits/tests/` | STOCKS | **LIVE** | pytest suite, imports all raits modules | n/a | n/a |
| `raits/raits/` (nested) | SCRIPTS NEST | **LIVE** (scripts active) | `tests/test_raits_vs_hold.py:11` sys.path.insert trỏ vào scripts/ | `raits/raits/scripts/_check_oos_data.py:49` hardcodes `d:\raits\raits\raits\scripts\window_debug.py` | `raits/raits/data/cache/` ~14 MB active parquets + 66 result pkls |
| `raits/raits/strategies/strategies/orb.py` | STOCKS | **UNCERTAIN** | Không tìm thấy import nào | Không tìm thấy path ref | n/a |
| `raits/raits/tests/decision/` | STOCKS | **UNCERTAIN** | Không tìm thấy import nào ngoài chính nó | Không tìm thấy path ref | n/a |
| `futures/` | FUTURES | **LIVE** | `global_index/` import 10+ modules; `orb_futures/_orb_core.py`; root scripts | `pooled_*.py`, `gate*.py` ref futures | Reads `data/cache/futures/*.parquet` |
| `futures/_validated_core.py` | FUTURES | **LIVE** | Imported by `global_index/` (8+ files), `orb_futures/_orb_core.py`, root scripts | Commented as source-of-truth trong `global_index/_core.py` | n/a |
| `global_index/` | FUTURES | **LIVE** | Self-contained; import từ futures/ | n/a | Reads `global_index/data/NKD_continuous_1m_8y.parquet` + `data/cache/futures/` |
| `global_index/_core.py` | FUTURES | **LIVE** | Imported by `swing_tf_powerhour.py`, `swing_tf_daily.py`, `mr_explore.py` trong global_index/ | Docstring "verbatim copy of futures/_validated_core" | n/a |
| `orb_futures/` | EXPERIMENTAL | **LIVE (standalone)** | `_orb_core.py` import từ `futures/`; không file nào import ngược lại | n/a | Reads `data/cache/futures/` |
| `nonequity/` | EXPERIMENTAL | **LIVE (self-contained)** | Chỉ internal imports; không file nào import ngược | `global_index/fetch.py` có comment ref `nonequity/data/` | Reads `nonequity/data/*.parquet` |
| `tier2/` | EXPERIMENTAL | **LIVE (self-contained)** | Không có external imports trỏ vào tier2 | n/a | Reads `tier2/data/*.parquet` |
| `xsect/` | EXPERIMENTAL | **UNCERTAIN** | Không có external imports | Không có path refs | Đọc user-supplied CLI arg — không có dedicated data dir |
| `configs/` (root) | STOCKS DATA | **LIVE** | `diagnose_exits.py`, `diagnose_wfo.py`, `inspect_wfo.py` đọc `configs/wfo_report.json` | n/a | Contains `final_params.yaml` (STALE values) |
| `data/cache/futures/` | FUTURES DATA | **LIVE** | Đọc bởi tất cả futures/ backtests, global_index/, orb_futures/ | Hardcoded trong `pooled_*.py`, `gate*.py` | 452 MB ES/NQ/YM/RTY/NKD parquets |
| `data/cache/data/` + `metadata/` (root) | DATA | **UNCERTAIN** | Không grep match nào tìm thấy | Không có hardcoded path refs | 9 SPY_5min files, 0.1 MB |
| `models/hmm/` (root) | STOCKS DATA | **LIVE** | `HMMEngine.__init__` default `model_dir="models/hmm"` (relative) khi CWD=D:\raits | `hmm_real_data_check.py` prints "saved to models/hmm/" | 38,412 pkl files |
| `tests/` (root) | STOCKS | **LIVE** | pytest suite; imports `raits.*` | n/a | n/a |
| `scratch/` | SCRATCH | **UNCERTAIN** | Không có imports từ code khác | n/a | JSON results files |
| `CodeBase/` | ARCHIVE | **DEAD** | (a) Không import nào (b) Không path refs nào (c) Chỉ ZIP archives | Đủ ba check đều trống | n/a |
| Root diagnostic scripts (`diagnose_*.py`, `gate*.py`, ...) | SCRATCH | **LIVE (runnable)** | Không bị import bởi gì cả (entry points) | n/a | n/a |

---

## 4. Data Layout + Trùng lặp giữa các tầng

```
LAYER 1 — D:\raits\data\cache\
  futures/    [452 MB]  ES/NQ/YM/RTY/NKD 1-min continuous
              ← AUTHORITATIVE futures data
              ← Đọc bởi futures/, global_index/, orb_futures/
  data/       [0.1 MB]  9 SPY_5min parquets — UNCERTAIN (possible orphan)
  metadata/   [<0.1 MB] pkl duplicates của data/ — UNCERTAIN

LAYER 2 — D:\raits\raits\data\cache\
  data/       [1,570 MB] 140,469 5-min stock parquets
              ← AUTHORITATIVE stock data
  daily/      [4 MB]     40 daily stock parquets
  snapshots/             66 WFO result pkls (results_*.pkl)
  *.pkl                  market_data_5min, window_debug, earnings, vix, ...

LAYER 3 — D:\raits\raits\raits\data\cache\   ← ARTIFACT của path nesting
  data/       [14 MB]  QQQ + others (written khi scripts chạy từ D:\raits\raits)
  metadata/   pkl duplicates

ISOLATED DATA DIRS:
  global_index/data/   [43 MB]  NKD_continuous_1m_8y.parquet + raw variant
  nonequity/data/      [170 MB] NKD + GC + CL parquets (NKD DUPLICATE ← DEBT-3)
  tier2/data/          [0.4 MB] ZN/ZB/6E daily diffs
  raits/models/hmm/    [78 MB]  HMM pkl files (CWD=D:\raits\raits)
  models/hmm/          [48 MB]  HMM pkl files (CWD=D:\raits)   ← DUPLICATE SET (DEBT-2)
```

**Tổng size ước tính:** ~2,800 MB (stocks cache) + 452 MB (futures) + ~350 MB (misc) + ~130 MB (models) ≈ **~3.7 GB**

### Các vấn đề trùng lặp

1. `NKD_continuous_1m_8y.parquet` xuất hiện trong cả `global_index/data/` VÀ `nonequity/data/` (~22 MB mỗi bên = 44 MB wasted)
2. `raits/data/cache/metadata/` chứa pkl duplicates của `raits/data/cache/data/` parquets
3. `models/hmm/` tồn tại ở cả `D:\raits\models\hmm\` VÀ `D:\raits\raits\models\hmm\` (bộ pkl khác nhau, tổng 126 MB)
4. `raits/raits/data/` là nested data cache từ artifact của scripts chạy từ `D:\raits\raits` (14 MB)
5. `configs/final_params.yaml` tồn tại ở cả root VÀ `raits/configs/` với **giá trị KHÁC NHAU** (xem DEBT-5)

---

## 5. Danh sách Debt + Đề xuất dọn dẹp

### 🔴 CRITICAL — DEBT-5: Hai `final_params.yaml` với giá trị KHÁC NHAU

| File | orb_range_minutes | vwap_bb_std | ema_period |
|---|---|---|---|
| `D:\raits\configs\final_params.yaml` | **15** | **2.5** | 30 |
| `D:\raits\raits\configs\final_params.yaml` | **20** | **1.5** | 30 |

MEMORY.md + `vault_test.py` hardcode xác nhận `orb=20/bb=1.5/ema=30` là params locked. Root `configs/final_params.yaml` là version cũ (pre-vault). Scripts chạy từ `D:\raits` với path relative `configs/final_params.yaml` sẽ đọc file sai.

**Verify:**
```powershell
cat D:\raits\configs\final_params.yaml
cat D:\raits\raits\configs\final_params.yaml
# Xác nhận discrepancy, rồi trace xem script nào đọc root configs/
rg -n "configs.final_params" D:\raits --include="*.py"
rg -n "configs\\\\final_params" D:\raits --include="*.py"
```

**Đề xuất (rủi ro thấp):** Annotate root file với comment `# STALE — pre-vault params (orb=15/bb=2.5/ema=30)`. Không xóa, chỉ document.

---

### 🟡 MEDIUM — DEBT-6: `futures/__init__.py` docstring sai

`futures/__init__.py` nói "ONLY raits.hmm (regime brain, read-only)" nhưng `_validated_core.py` thực tế cũng import `raits.strategies.trend_follow` bên trong `backtest_swing_tf()`.

**Tác động:** Ai đó đọc docs sẽ nghĩ có thể refactor `raits.strategies.trend_follow` mà không ảnh hưởng futures — **sai**.

**Fix an toàn:** Update docstring trong `futures/__init__.py` để phản ánh đúng dep thực tế.

---

### 🟡 MEDIUM — DEBT-2: Hai `models/hmm/` directories (126 MB, 94k pkl files)

`HMMEngine.__init__` dùng relative path `model_dir="models/hmm"`. Khi scripts chạy từ `D:\raits` → models đi vào `D:\raits\models\hmm\`. Khi chạy từ `D:\raits\raits` → `D:\raits\raits\models\hmm\`. Hai bộ pkl hoàn toàn tách biệt, không rõ bộ nào là production.

**Verify:**
```powershell
# Tìm PRODUCTION.pkl ở cả hai chỗ
Get-ChildItem D:\raits\models\hmm\ -Filter "PRODUCTION.pkl"
Get-ChildItem D:\raits\raits\models\hmm\ -Filter "PRODUCTION.pkl"
# Xem file mới nhất ở mỗi nơi
Get-ChildItem D:\raits\models\hmm\ | Sort-Object LastWriteTime -Descending | Select-Object -First 5
Get-ChildItem D:\raits\raits\models\hmm\ | Sort-Object LastWriteTime -Descending | Select-Object -First 5
```

**Không an toàn xóa** cho đến khi consolidate path trong `HMMEngine` thành absolute path.

---

### 🟢 LOW — DEBT-3: NKD parquet duplicate (44 MB)

`NKD_continuous_1m_8y.parquet` xuất hiện ở cả `global_index/data/` VÀ `nonequity/data/`.

**Bằng chứng 3 check:**
- (a) `global_index/swing_tf_powerhour.py` đọc từ `global_index/data/NKD...`; `nonequity/swing_tf_daily.py` đọc từ `nonequity/data/NKD...` (CLI default riêng biệt)
- (b) Không path-string cross-ref giữa hai dirs
- (c) Cả hai file present trong cả hai dirs

**Verify hash trước:**
```powershell
$h1 = (Get-FileHash "D:\raits\global_index\data\NKD_continuous_1m_8y.parquet").Hash
$h2 = (Get-FileHash "D:\raits\nonequity\data\NKD_continuous_1m_8y.parquet").Hash
Write-Host "Identical: $($h1 -eq $h2)"
# Nếu True → safe xóa từ nonequity/data/
```

**Revert:** Copy lại từ `global_index/data/`

---

### 🟢 LOW — DEBT-1: Orphan copies trong `raits/raits/`

`raits/raits/strategies/strategies/orb.py` và `raits/raits/tests/decision/` là copies mồ côi.

**Bằng chứng 3 check (cả hai):**
- (a) Không file nào `from raits.raits.strategies.strategies import ...`
- (b) Không path-string nào trỏ vào `raits\raits\strategies\strategies\`
- (c) Không data files liên quan

**Verify trước khi xóa:**
```powershell
rg -rn "raits.raits.strategies" D:\raits --include="*.py"
rg -rn "raits\\raits\\strategies" D:\raits --include="*.py"
# Expected: no matches
rg -rn "raits.raits.tests.decision" D:\raits --include="*.py"
# Expected: no matches
```

**Revert:** `git restore raits/raits/strategies/` và `git restore raits/raits/tests/decision/`

---

### 🟢 LOW — DEBT-4: Root `data/cache/data/` + `data/cache/metadata/` (possible orphan)

Chỉ 9 SPY_5min parquet files (0.1 MB). Tất cả stock data authoritative nằm ở `raits/data/cache/data/` (1.57 GB). Không tìm thấy script nào đọc từ root `data/cache/data/`.

**Verify:**
```powershell
rg -rn "data.cache.data" D:\raits --include="*.py"
rg -rn "data\\\\cache\\\\data" D:\raits --include="*.py"
rg -rn "data.cache.metadata" D:\raits --include="*.py"
# Nếu không có match → DEAD, safe to archive
```

**Revert:** Restore từ `data/cache/metadata/` pkl duplicates nếu cần.

---

### 🟢 LOW — DEBT-7: `CodeBase/` ZIP archives

**Đủ ba check đều trống:** Không imports, không path refs, chỉ là ZIP archives của old milestones.

**Verify:**
```powershell
git log --all -- CodeBase/
# Nếu untracked → safe di chuyển ra ngoài repo hoặc xóa
```

---

### 🔵 TRACK ONLY — DEBT-8: 80+ `sys.path.insert` call sites

Pattern `sys.path.insert(0, r'd:\raits')` hardcode absolute path — sẽ break nếu repo move. Pattern `sys.path.insert(0, str(Path.cwd()))` phụ thuộc vào CWD. Không an toàn để dọn hàng loạt — track as tech debt.

---

## 6. Futures/Stocks Tách bạch — Đánh giá

| Boundary | Tuyên bố trong docs | Thực tế code | Verdict |
|---|---|---|---|
| `futures/` → `raits.hmm` | Cho phép | Confirmed (lazy import trong `label_regimes()`) | ✅ Clean |
| `futures/` → `raits.strategies.trend_follow` | `__init__.py` nói "ONLY raits.hmm" | YES — `_validated_core.backtest_swing_tf()` cũng import `TrendFollowStrategy` | ❌ Docstring sai |
| `futures/` → `raits.backtest` | Không phép | Không có | ✅ Clean |
| `global_index/` → `futures/` | Cho phép | Confirmed (heavy dep) | ✅ Clean |
| `global_index/` → `raits/` trực tiếp | Không documented | Không có | ✅ Clean |
| `orb_futures/` → `futures/` | Cho phép | Confirmed | ✅ Clean |
| `nonequity/` → `futures/` | Tránh (dùng copy) | Không có — dùng verbatim copy `_core.py` | ✅ Clean |
| `raits/` → `futures/` | Không phép | Không bao giờ | ✅ Clean |

**Kết luận:**

- **Chiều an toàn nhất** (`raits/` → `futures/`): **hoàn toàn sạch**. `raits/` không bao giờ biết `futures/` tồn tại.
- **Chiều cần chú ý** (`futures/` → `raits/`): import nhiều hơn docs nói. Dep thực tế = `raits.hmm` + `raits.strategies.trend_follow`. `futures/__init__.py` cần update.
- **Deploy implication:** Khi deploy `global_index/` hoặc `futures/`, cần full `raits/` package (ít nhất `raits.hmm` + `raits.strategies.trend_follow`). Không thể deploy futures standalone mà không có `raits/`.
- **Experimental isolation:** `orb_futures/` phụ thuộc `futures/` → transitively phụ thuộc `raits/`. `nonequity/`, `tier2/`, `xsect/` độc lập hoàn toàn.

---

## Tóm tắt ưu tiên

| # | Vấn đề | Mức độ | Hành động gợi ý |
|---|---|---|---|
| 1 | Hai `final_params.yaml` giá trị khác nhau (root STALE) | 🔴 CRITICAL | Document root file là STALE ngay |
| 2 | `futures/__init__.py` docstring sai (thiếu `trend_follow` dep) | 🟡 MEDIUM | Update docstring |
| 3 | Hai `models/hmm/` dirs (126 MB, không rõ bộ nào production) | 🟡 MEDIUM | Verify + consolidate path |
| 4 | NKD duplicate 44 MB (`global_index/data/` vs `nonequity/data/`) | 🟢 LOW | Verify hash → xóa từ nonequity/ |
| 5 | Orphan `raits/raits/strategies/strategies/orb.py` | 🟢 LOW | Verify 3-check → xóa |
| 6 | Root `data/cache/data/` (9 SPY files, possible orphan) | 🟢 LOW | Verify grep → archive |
| 7 | `CodeBase/` ZIP archives | 🟢 LOW | Verify git log → remove |
| 8 | 80+ hardcoded `sys.path.insert` absolute paths | 🔵 TRACK | Không dọn ngay |
