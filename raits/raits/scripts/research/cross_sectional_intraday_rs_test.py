"""
CROSS_SECTIONAL_INTRADAY_RELATIVE_STRENGTH — do intraday winners keep winning?
(RESEARCH ONLY. Reads the local cache; modifies no production code.)

THE QUESTION (spec §2, §6)
--------------------------
At a fixed intraday moment, rank the universe by how much each stock has moved
since the open. Do the leaders keep leading over the next 30-240 minutes
(cross-sectional momentum), or do the laggards catch up (reversal)? The
direction is NOT assumed; the top-minus-bottom spread carries its own sign.

This is a different KIND of question from the three studies before it. Those
tested candle patterns on single names and all three found symmetric diffusion.
This one is cross-sectional and dollar-neutral, so the market component cancels
by construction and what is left is stock-specific.

TWO CONVENTIONS THAT DECIDE THE ANSWER
--------------------------------------
BAR LABELS ARE START TIMES. Verified: a session runs 09:30..15:55 in 78 bars.
    The price AT 10:00 is therefore the close of the bar labelled 09:55.
    Using the bar labelled 10:00 would embed five minutes of future.

LONG-SHORT COST ACCOUNTING (spec §15). The T-B spread is the return on
    $1 long PLUS $1 short. Both legs are opened and closed, so a c bps per-side
    cost is paid four times: 4c bps. At 2 bps/side that is 8 bps, at 5 bps/side
    20 bps — not 4 and 10. Charging one leg is the mistake the spec warns about.

SECTOR MAPPING — fixed at the 2017 classification (spec §26)
------------------------------------------------------------
No stock-to-sector map exists in the repo, so one is built here. It is
TIME-INVARIANT and set to where each name sat at the START of the sample. That
is deliberate: GICS moved GOOGL, META and NFLX into Communication Services in
September 2018, and applying today's classification backwards would be exactly
the "future classification" §26 forbids. A stable 2017 map uses only
information available on day one.

Consequences, stated rather than hidden:
  * XLC and XLRE are absent from the cache, so Communication Services and Real
    Estate have no ETF. Under the 2017 map no stock needs them.
  * XLK holds 23 of 62 names (37%). Any raw-rank result will lean on it, which
    is precisely what the sector-adjusted signal exists to test.

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\cross_sectional_intraday_rs_test.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parents[4]
CACHE = _ROOT / "raits" / "data" / "cache" / "research_daily" / "ema_scalp_5min"
WORK = _ROOT / "raits" / "data" / "cache" / "research_daily"
PANEL = WORK / "xs_rs_panel.parquet"

MARKET = "SPY"
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLY", "XLP", "XLV", "XLI", "XLB", "XLU"]
NON_STOCK = set(SECTOR_ETFS) | {"SPY", "QQQ", "IWM", "GLD"}

# 2017 GICS. Fixed for the whole sample — see module docstring.
SECTOR = {
    **{t: "XLK" for t in ["AAPL", "ADBE", "AMAT", "AMD", "AVGO", "CRM", "CSCO",
                          "EBAY", "GOOGL", "INTC", "INTU", "MA", "META", "MSFT",
                          "MU", "NOW", "NVDA", "ORCL", "PANW", "PYPL", "QCOM",
                          "TXN", "V"]},
    **{t: "XLY" for t in ["AMZN", "HD", "LOW", "MCD", "NFLX", "NKE", "SBUX",
                          "TGT", "TSLA"]},
    **{t: "XLP" for t in ["COST", "KO", "PEP", "PG", "WMT"]},
    **{t: "XLV" for t in ["ABBV", "AMGN", "BIIB", "BMY", "GILD", "JNJ", "LLY",
                          "MRK", "PFE", "REGN", "VRTX"]},
    **{t: "XLF" for t in ["BAC", "C", "GS", "JPM", "MS", "WFC"]},
    **{t: "XLE" for t in ["CVX", "XOM"]},
    **{t: "XLI" for t in ["BA", "CAT", "DE", "GE", "HON", "MMM"]},
}

OPEN_LABEL = "09:30"
EOD_LABEL = "15:55"
FORMATIONS = [("10:00", 30), ("11:00", 90), ("12:00", 150)]   # label, min from open
FWD_MIN = [30, 60, 120, 180]
MIN_STOCKS = 30
N_SHUFFLE = 500
N_BOOT = 10_000
COST_SIDES = (2.0, 5.0)


def label_at(hhmm: str) -> str:
    """Bar LABEL whose close is the price at wall-clock `hhmm`.

    Labels are bar START times, so the price at 10:00 is the close of the bar
    that began at 09:55. Off-by-one here is a five-minute look-ahead.
    """
    t = pd.Timestamp(f"2000-01-01 {hhmm}") - pd.Timedelta(minutes=5)
    return t.strftime("%H:%M")


def plus(hhmm: str, minutes: int) -> str:
    return (pd.Timestamp(f"2000-01-01 {hhmm}") + pd.Timedelta(minutes=minutes)
            ).strftime("%H:%M")


# ──────────────────────────────────────────────────────────────────────────────

def build_panel() -> tuple:
    if PANEL.exists():
        px = pd.read_parquet(PANEL)
        op = pd.read_parquet(PANEL.with_name("xs_rs_open.parquet"))
        print(f"  panel: cached  {px.shape[0]:,} (date,label) rows x "
              f"{px.shape[1]} tickers")
        return px, op
    files = sorted(CACHE.glob("*.parquet"))
    closes, opens = [], []
    for n, f in enumerate(files, 1):
        d = pd.read_parquet(f)
        d["ts"] = pd.to_datetime(d["ts"])
        d["date"] = d["ts"].dt.normalize()
        d["lab"] = d["ts"].dt.strftime("%H:%M")
        closes.append(d[["date", "lab", "close"]].assign(sym=f.stem))
        o = d[d["lab"] == OPEN_LABEL][["date", "open"]].assign(sym=f.stem)
        opens.append(o)
        if n % 25 == 0 or n == len(files):
            print(f"    loaded {n}/{len(files)}", flush=True)
    c = pd.concat(closes, ignore_index=True)
    px = c.pivot_table(index=["date", "lab"], columns="sym", values="close")
    op = pd.concat(opens, ignore_index=True).pivot_table(
        index="date", columns="sym", values="open")
    WORK.mkdir(parents=True, exist_ok=True)
    px.to_parquet(PANEL)
    op.to_parquet(PANEL.with_name("xs_rs_open.parquet"))
    print(f"  panel cached -> {PANEL.name}")
    return px, op


def series_at(px: pd.DataFrame, hhmm: str) -> pd.DataFrame:
    """date x ticker frame of prices at wall-clock `hhmm`."""
    lab = label_at(hhmm)
    s = px.xs(lab, level="lab", drop_level=True)
    return s


# ──────────────────────────────────────────────────────────────────────────────

def _row_ranks(X: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Rank 0..k-1 within each row over valid entries; invalid -> -1.

    Invalid cells are pushed to +inf before argsort so they always sort last
    and never occupy a rank a real stock should have.
    """
    Xf = np.where(valid, X, np.inf)
    order = np.argsort(Xf, axis=1, kind="stable")
    ranks = np.empty(order.shape, dtype=np.int32)
    cols = np.broadcast_to(np.arange(X.shape[1], dtype=np.int32), order.shape)
    np.put_along_axis(ranks, order, cols, axis=1)
    return np.where(valid, ranks, -1)


def daily_spread(sig: pd.DataFrame, fwd: pd.DataFrame, q=5):
    """One T-B spread per date, plus bucket means, legs and rank IC.

    VECTORISED over dates. The first version looped 1,510 dates per
    configuration and, at 60 configurations, never finished inside a 50-minute
    timeout. The maths is identical; only the loop is gone.

    Ranking and forward measurement come from separate frames, and a date is
    used only when BOTH are populated for >= MIN_STOCKS names — so no date is
    scored on a thin cross-section.
    """
    cols = sig.columns.intersection(fwd.columns)
    idx = sig.index.intersection(fwd.index)
    if len(idx) == 0 or len(cols) == 0:
        return pd.DataFrame()
    S = sig.loc[idx, cols].to_numpy(float)
    F = fwd.loc[idx, cols].to_numpy(float)
    valid = np.isfinite(S) & np.isfinite(F)
    k = valid.sum(1)
    keep = k >= MIN_STOCKS
    if not keep.any():
        return pd.DataFrame()
    S, F, valid, k = S[keep], F[keep], valid[keep], k[keep]
    dates = idx[keep]

    rs = _row_ranks(S, valid)
    rf = _row_ranks(F, valid)
    kk = k[:, None]
    bucket = np.where(valid, (rs * q) // np.maximum(kk, 1), -1)

    def bmean(mask):
        cnt = mask.sum(1)
        tot = np.where(mask, F, 0.0).sum(1)
        return np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)

    qm = {i: bmean(bucket == i) for i in range(q)}
    top, bot = qm[q - 1], qm[0]
    uni = np.where(valid, F, 0.0).sum(1) / k

    # Spearman IC = Pearson correlation of the two rank vectors, per row,
    # computed only over the valid cells.
    rsf = np.where(valid, rs.astype(float), 0.0)
    rff = np.where(valid, rf.astype(float), 0.0)
    ms, mf = rsf.sum(1) / k, rff.sum(1) / k
    ds = np.where(valid, rsf - ms[:, None], 0.0)
    df_ = np.where(valid, rff - mf[:, None], 0.0)
    cov = (ds * df_).sum(1)
    den = np.sqrt((ds * ds).sum(1) * (df_ * df_).sum(1))
    ic = np.where(den > 0, cov / np.maximum(den, 1e-12), np.nan)

    sv = np.where(valid, S, np.nan)
    disp = np.nanstd(sv, axis=1)

    names = np.array(cols, dtype=object)
    top_names = ["|".join(names[(bucket[i] == q - 1)]) for i in range(len(dates))]
    bot_names = ["|".join(names[(bucket[i] == 0)]) for i in range(len(dates))]

    out = dict(date=dates, n=k, spread=top - bot, top=top, bot=bot, uni=uni,
               long_leg=top - uni, short_leg=uni - bot, ic=ic, disp=disp,
               top_names=top_names, bot_names=bot_names)
    for i in range(q):
        out[f"q{i+1}"] = qm[i]
    return pd.DataFrame(out)


def boot_days(x, n_boot=N_BOOT, seed=42):
    x = np.asarray(x, float)
    x = x[~np.isnan(x)]
    if len(x) < 20:
        return None
    rng = np.random.default_rng(seed)
    n = len(x)
    batch = max(1, 20_000_000 // n)
    means = np.empty(n_boot)
    done = 0
    while done < n_boot:
        k = min(batch, n_boot - done)
        means[done:done + k] = x[rng.integers(0, n, size=(k, n))].mean(axis=1)
        done += k
    return dict(mean=float(x.mean()), lo=float(np.percentile(means, 2.5)),
                hi=float(np.percentile(means, 97.5)),
                p_le0=float((means <= 0).mean()), n=n)


def bps(v):
    return 1e4 * v


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    if a.rebuild and PANEL.exists():
        PANEL.unlink()

    print("=" * 112)
    print("CROSS_SECTIONAL_INTRADAY_RELATIVE_STRENGTH")
    print("=" * 112)
    px, op = build_panel()
    all_syms = list(px.columns)
    stocks = [s for s in all_syms if s not in NON_STOCK]
    mapped = [s for s in stocks if s in SECTOR]
    print(f"  tickers {len(all_syms)} | stocks {len(stocks)} | "
          f"sector-mapped {len(mapped)}")
    print(f"  sector ETFs present: {[s for s in SECTOR_ETFS if s in all_syms]}")
    print(f"  MISSING: XLC, XLRE (no stock needs them under the 2017 map)")
    dates = op.index
    print(f"  sessions {len(dates):,}  {dates.min().date()} .. {dates.max().date()}")
    sc = pd.Series({s: SECTOR[s] for s in mapped}).value_counts()
    print(f"  sector counts: {dict(sc)}")

    o0 = op[stocks]
    results = {}

    for fhh, _fm in FORMATIONS:
        pf = series_at(px, fhh)
        form_stock = pf[stocks] / o0 - 1.0
        form_mkt = pf[MARKET] / op[MARKET] - 1.0
        sec_ret = {e: (pf[e] / op[e] - 1.0) for e in SECTOR_ETFS if e in all_syms}
        sec_al = pd.DataFrame({s: sec_ret[SECTOR[s]] for s in mapped
                               if SECTOR[s] in sec_ret})

        signals = {
            "raw": form_stock,
            "mkt-adj": form_stock.sub(form_mkt, axis=0),
            "sec-adj": form_stock[sec_al.columns] - sec_al,
        }
        # Control 2 (spec §10): rank by the PREVIOUS session's open-to-close.
        prev = (series_at(px, EOD_LABEL)[stocks] / o0 - 1.0).shift(1)
        signals["prev-day"] = prev

        for hz in FWD_MIN + ["EOD"]:
            thh = EOD_LABEL if hz == "EOD" else plus(fhh, hz)
            if hz != "EOD" and thh > "15:55":
                continue
            pt = series_at(px, "16:00") if hz == "EOD" else series_at(px, thh)
            if hz == "EOD":
                pt = px.xs(EOD_LABEL, level="lab")
            fwd = pt[stocks] / pf[stocks] - 1.0
            for name, sig in signals.items():
                d = daily_spread(sig, fwd)
                if len(d):
                    results[(fhh, name, hz)] = d

    # ── §11 monotonicity + §12 spread + §22 IC ───────────────────────────────
    print("\n" + "=" * 112)
    print("BUCKET MONOTONICITY + T-B SPREAD + RANK IC   (all in bps; day-clustered CI)")
    print("=" * 112)
    print(f"  {'form':<7}{'signal':<10}{'hz':>5}{'days':>7}"
          f"{'Q1':>8}{'Q2':>8}{'Q3':>8}{'Q4':>8}{'Q5':>8}"
          f"{'T-B':>9}{'95% CI':>20}{'P(<=0)':>9}{'IC':>8}{'%IC>0':>7}")
    for key in sorted(results, key=lambda k: (k[0], k[1], str(k[2]))):
        fhh, name, hz = key
        d = results[key]
        b = boot_days(d["spread"].to_numpy())
        if not b:
            continue
        qs = [bps(d[f"q{i}"].mean()) for i in range(1, 6) if f"q{i}" in d]
        ic = d["ic"].mean()
        print(f"  {fhh:<7}{name:<10}{str(hz):>5}{len(d):>7,}"
              + "".join(f"{q:>8.1f}" for q in qs)
              + f"{bps(b['mean']):>9.2f}"
              + f"{f'[{bps(b[chr(108)+chr(111)]):+.1f},{bps(b[chr(104)+chr(105)]):+.1f}]':>20}"
              + f"{b['p_le0']:>9.3f}{ic:>8.4f}{100*(d['ic']>0).mean():>6.0f}%")

    # ── §10 control 1: random ranking ───────────────────────────────────────
    print("\n" + "=" * 112)
    print("CONTROL 1 — RANDOM RANKING null distribution (spec §10)")
    print("=" * 112)
    rng = np.random.default_rng(7)
    for fhh in [f for f, _ in FORMATIONS][:1]:
        for hz in (60, "EOD"):
            key = (fhh, "raw", hz)
            if key not in results:
                continue
            obs = results[key]["spread"].mean()
            pf = series_at(px, fhh)
            thh = EOD_LABEL if hz == "EOD" else plus(fhh, hz)
            pt = px.xs(EOD_LABEL, level="lab") if hz == "EOD" else series_at(px, thh)
            fwd = pt[stocks] / pf[stocks] - 1.0
            sig = pf[stocks] / o0 - 1.0
            null = []
            for _ in range(N_SHUFFLE):
                sh = pd.DataFrame(
                    rng.permuted(sig.to_numpy(), axis=1),
                    index=sig.index, columns=sig.columns)
                dd = daily_spread(sh, fwd)
                if len(dd):
                    null.append(dd["spread"].mean())
            null = np.array(null)
            pct = (null >= obs).mean()
            print(f"  form {fhh} hz {hz}: observed {bps(obs):+.2f} bps | "
                  f"null mean {bps(null.mean()):+.2f} "
                  f"[{bps(np.percentile(null, 2.5)):+.2f},"
                  f"{bps(np.percentile(null, 97.5)):+.2f}]  "
                  f"P(null >= observed) = {pct:.3f}")

    # ── §17 leg decomposition, §15 costs, §23 breadth ───────────────────────
    print("\n" + "=" * 112)
    print("LEG DECOMPOSITION, COSTS AND BREADTH — raw + sec-adj, all horizons")
    print("=" * 112)
    print("  long leg = top bucket minus universe mean; short leg = universe")
    print("  mean minus bottom bucket. Cost = 4x per-side bps (both legs, in+out).")
    print(f"\n  {'form':<7}{'signal':<10}{'hz':>5}{'gross':>9}{'long':>9}{'short':>9}"
          f"{'net@2':>9}{'net@5':>9}{'win%':>7}{'p5':>9}{'p50':>9}{'p95':>9}")
    for key in sorted(results, key=lambda k: (k[0], k[1], str(k[2]))):
        fhh, name, hz = key
        if name in ("prev-day",):
            continue
        d = results[key]
        g = bps(d["spread"].mean())
        print(f"  {fhh:<7}{name:<10}{str(hz):>5}{g:>9.2f}"
              f"{bps(d['long_leg'].mean()):>9.2f}{bps(d['short_leg'].mean()):>9.2f}"
              f"{g - 4 * COST_SIDES[0]:>9.2f}{g - 4 * COST_SIDES[1]:>9.2f}"
              f"{100*(d['spread'] > 0).mean():>6.0f}%"
              f"{bps(d['spread'].quantile(.05)):>9.1f}"
              f"{bps(d['spread'].median()):>9.1f}"
              f"{bps(d['spread'].quantile(.95)):>9.1f}")

    # ── §20 year, §25 dispersion, §24 market state ──────────────────────────
    print("\n" + "=" * 112)
    print("CONDITIONING — year / dispersion tercile / market state  (T-B bps)")
    print("=" * 112)
    spy_form = {}
    for fhh, _ in FORMATIONS:
        spy_form[fhh] = series_at(px, fhh)[MARKET] / op[MARKET] - 1.0
    for name in ("raw", "sec-adj"):
        for hz in (60, "EOD"):
            key = ("10:00", name, hz)
            if key not in results:
                continue
            d = results[key].set_index("date")
            print(f"\n  form 10:00  {name}  hz {hz}")
            ys = d.groupby(d.index.year)["spread"].agg(["size", "mean"])
            print("    year:  " + "  ".join(
                f"{y}:{bps(r['mean']):+.1f}({int(r['size'])})"
                for y, r in ys.iterrows()))
            t = pd.qcut(d["disp"], 3, labels=["low", "mid", "high"])
            print("    dispersion: " + "  ".join(
                f"{k}:{bps(v):+.1f}" for k, v in d.groupby(t, observed=True)["spread"].mean().items()))
            sp = spy_form[key[0]].reindex(d.index)
            st = pd.cut(sp, [-9, -0.005, 0.005, 9], labels=["down", "flat", "up"])
            print("    market:     " + "  ".join(
                f"{k}:{bps(v):+.1f}" for k, v in d.groupby(st, observed=True)["spread"].mean().items()))

    # ── §18 sector concentration ────────────────────────────────────────────
    print("\n" + "=" * 112)
    print("SECTOR CONCENTRATION of the buckets (spec §18)")
    print("=" * 112)
    for name in ("raw", "mkt-adj", "sec-adj"):
        key = ("10:00", name, 60)
        if key not in results:
            continue
        d = results[key]
        for side in ("top_names", "bot_names"):
            cnt = {}
            for row in d[side]:
                for s in row.split("|"):
                    if s in SECTOR:
                        cnt[SECTOR[s]] = cnt.get(SECTOR[s], 0) + 1
            tot = sum(cnt.values()) or 1
            top_sec = max(cnt, key=cnt.get) if cnt else "-"
            print(f"  {name:<9} {side.replace('_names',''):<4} "
                  f"max {top_sec} {100*cnt.get(top_sec,0)/tot:>5.1f}%   "
                  + " ".join(f"{k}:{100*v/tot:.0f}%" for k, v in
                             sorted(cnt.items(), key=lambda x: -x[1])[:5]))
    print(f"\n  For reference the universe itself is "
          f"{100*sc.get('XLK',0)/len(mapped):.0f}% XLK — a raw-rank tilt toward")
    print("  it is expected, which is what the sector-adjusted row tests.")
    print("=" * 112)


if __name__ == "__main__":
    main()
