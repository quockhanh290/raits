# Intraday Pressure Probe (5-min bars) — findings

**Status: DEAD** (strategy question) · **plus a data-quality bug worth more than the probe**
**Date:** 2026-08-03 · Cost: **$0** · Research only — no production code touched.

---

## 1. The strategy question: DEAD

Pre-committed before any number was looked at: the top signal decile must show a
median same-day forward return **> $0.034/share gross** (2× the $0.017 round-trip
cost) at a horizon **≥ 10 min**.

Panel: 4,283,711 bar-observations, 37 tickers, 2017-01 → 2024-12.
Features: `close_pos`, `vwap_dev`, `avg_trade_sz_z`, `rvol`, `bar_ret`.
CIs are **day-clustered** (bars within a day are not independent; overlapping
forward windows make it worse).

**Cells clearing the hurdle at h ≥ 2: 0 of 20.**

Median forward return sat at ±0.5 cent — a half-penny — against a 1.7 cent cost.
Notably the sign was consistently *negative* for all three momentum-style
features, i.e. the data says mean-reversion, not continuation. Even traded in
the reversion direction the median clears nothing.

## 2. The mean looked tradeable. It was corrupt data.

Fading the top decile of `close_pos` at h=2 showed **mean +5.894c**, net +4.19c
after costs — apparently a large edge. Median was **+0.500c**. A 12× mean/median
ratio is the signature this project has been burned by before (PE_SHORT top-3 =
58% of P&L; GAP_FILL top-3 = 80%).

| Check | Result |
|---|---|
| Top 0.1% of obs (856 of 856,749) | **533% of total profit** — the other 99.9% lose money |
| Winsorise ±2 sd (clips 0.18% of rows) | net edge $4.19c → **$0.15c** (−97%) |
| Volatility-quartile split | Q1 −4.0c, Q2 +13.0c, Q3 +6.0c, Q4 +8.5c — non-monotonic noise |

Then the tail itself was inspected:

- **814 of the top 856 observations are META**
- median "move" in that tail = **2,154% of price in 10 minutes**
- 742 of 856 fall in **2021**
- most extreme: META 2021-07-27, close recorded **$14.24**, "move" +$352.78

META traded around $340–380 in July 2021. These are not market moves. The entire
apparent edge was a corrupt price block.

## 3. The actual finding: a corrupt META block in the 5-min data

Scanning every ticker for bars whose close is <50% or >200% of that ticker's
rolling 21-day median level:

```
META    5,157 suspect bars    2021-06-30 .. 2022-01-28    (148 trading days)
─────────────────────────────────────────────────────────────────────────────
TOTAL   5,157                 no other ticker affected
```

Price is recorded around $12–16 instead of ~$300–380. Only META. The block spans
seven months of `window_debug_5min.pkl` — the file behind the validated baseline,
`stress_orb_stk_sim`, and the ORB event index.

### Impact on the validated baseline: negligible

| Source | META trades in the corrupt window | P&L |
|---|---|---|
| `results_20260707_110323.pkl` | **1** (GF_SHORT, entry $12.62) | **−$34** |
| `window_debug_results.pkl` | 1 (same) | −$34 |

−$34 of $33,550 total. The baseline is not materially contaminated — corrupt
prices make META look like a $12 stock, which mostly failed the strategies' own
filters rather than generating fake trades.

### Impact on the event index: small but real, and it exposes a gate weakness

5 META events fall in the corrupt window. **4 have a corrupt `entry_px` (<$100).
The existing `|pct_return| > 25%` gate caught only 1.**

| date | entry_px | exit_px | pct_return | flagged? |
|---|---|---|---|---|
| 2021-10-04 | 14.01 | 329.79 | −22.54 | **yes** |
| 2021-11-29 | 16.17 | 16.43 | −0.016 | no |
| 2021-12-17 | 14.54 | 14.81 | −0.019 | no |
| 2022-01-18 | 319.01 | 303.82 | +0.048 | no (clean) |
| 2022-01-28 | 11.86 | 12.13 | −0.023 | no |

**Why the gate misses them:** `pct_return` is a *ratio* of entry to exit. When
**both** are corrupt (~$14 → ~$14) the ratio looks perfectly normal and the gate
passes it. The gate only fires when corruption is one-sided.

**A price-level sanity check is needed alongside the ratio check** — e.g. flag
any event whose `entry_px` deviates more than 50% from that ticker's rolling
daily median.

3 corrupt events survive into the 267-event clean population (1.1%). They are
also present in the 144-event primary cell of the auction-imbalance study
(`orb_stocks/imbalance_research/FINDINGS.md`), which was already MONITOR and
already shown to be fragile to 5 events (QCOM). **That result should be re-run
after the gate is fixed** before it is relied on for anything.

---

## 4. What this does and does not settle

**Settles:** no bar-level pressure proxy in this dataset supports a 5–30 minute
strategy. Do not build one on 5-min bars.

**Does NOT settle:** the order-flow question itself. Bars destroy exactly the
microstructure (book depth, queue position, aggressor side, sub-minute timing)
that the hypothesis is about. This probe was the cheap pre-check; it returned
nothing, which means buying tick data would be a **bet**, not a follow-up on
evidence. That is a legitimate reason to stop, not proof that nothing is there.

Also unchanged: the system has no scalper-horizon strategy, and the live runtime
(5-minute cron) is architecturally incapable of running one. Any real order-flow
work is a second system, not a strategy addition.

---

## Files

| File | Role |
|---|---|
| `probe_5min_pressure.py` | the probe — panel build, day-clustered bootstrap, pre-committed hurdle |
| `pressure_probe.parquet` | 20 cells × statistics |

Reproduce:
```
cd d:\raits
python intraday_pressure\probe_5min_pressure.py
```
