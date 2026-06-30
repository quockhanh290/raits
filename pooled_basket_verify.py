"""
pooled_basket_verify.py — verify a STRESS_MID edge across the INDEX BASKET
=========================================================================
Per-instrument PF ranged 1.05–1.65. Judging that spread by eye ("looks like
luck") is not rigorous. This verifies the basket edge three proper ways:

[A] PER-EPISODE ROBUSTNESS  (the key test, given stress is clustered)
    The instruments are correlated (~0.9) — they are NOT independent samples.
    The real independent units are the few stress EPISODES (2018-Q4, 2020-COVID,
    2022-bear). A robust edge is profitable in EACH episode, not carried by one
    (the way TF was carried by 2022-H1). Reports basket P&L per episode.

[B] PORTFOLIO AGGREGATE
    Equal-weight (1 micro each) basket daily P&L. Instrument-specific noise
    should average out — if the aggregate equity curve is stable (Sharpe, Calmar,
    low single-episode concentration), the basket edge is real even if any one
    instrument is noisy.

[C] BOOTSTRAP DISPERSION TEST
    Is PF 1.05–1.65 actually inconsistent with ONE true edge + sampling noise?
    Pool all trades, resample into k groups of the observed sizes, measure the
    PF spread distribution, and see where the OBSERVED spread falls. If observed
    spread is ordinary under the bootstrap, the dispersion is NOT evidence of
    fragility — it is just small-sample noise.

Input: trade CSVs dumped by gate2 (--dump-csv), columns include day,pnl.
    python pooled_basket_verify.py --trades "MES=mes_sm.csv,MNQ=nq_sm.csv,YM=ym_sm.csv,RTY=rty_sm.csv,NKD=nkd_sm.csv"
    (add --alpha-only to drop RTY/NKD if you only want the clean-alpha basket)
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

EPISODES = [
    ("2018-Q4",   "2018-10-01", "2018-12-31"),
    ("2020-COVID","2020-02-15", "2020-05-31"),
    ("2022-bear", "2022-01-01", "2022-12-31"),
]

def pf(pnl: np.ndarray) -> float:
    w = pnl[pnl > 0].sum(); l = -pnl[pnl < 0].sum()
    return float(w / l) if l > 0 else np.inf

def load(spec: str) -> dict:
    out = {}
    for part in spec.split(","):
        name, path = part.split("=")
        df = pd.read_csv(path.strip())
        df["day"] = pd.to_datetime(df["day"])
        out[name.strip()] = df[["day", "pnl"]].copy()
    return out

def episode_of(d: pd.Timestamp) -> str:
    for name, s, e in EPISODES:
        if pd.Timestamp(s) <= d <= pd.Timestamp(e):
            return name
    return "other"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", required=True, help='NAME=path,NAME=path,...')
    ap.add_argument("--alpha-only", action="store_true", help="drop RTY and NKD")
    ap.add_argument("--boot", type=int, default=5000)
    a = ap.parse_args()

    books = load(a.trades)
    if a.alpha_only:
        books = {k: v for k, v in books.items() if k not in ("RTY", "NKD")}
    print(f"\n{'='*68}\nPOOLED BASKET VERIFY | {', '.join(books)}\n{'='*68}")

    # ── [A] per-episode robustness ────────────────────────────────────────────
    print("\n[A] PER-EPISODE BASKET P&L  (robust = positive in EACH independent episode)")
    print(f"    {'episode':<11}" + "".join(f"{n:>10}" for n in books) + f"{'BASKET':>11}{'trades':>8}")
    ep_basket = {}
    for ep, s, e in EPISODES + [("other", None, None)]:
        row = {}
        tot = 0.0; ntr = 0
        for n, df in books.items():
            if ep == "other":
                m = df[~df["day"].apply(lambda d: episode_of(d) != "other")]
            else:
                m = df[(df["day"] >= pd.Timestamp(s)) & (df["day"] <= pd.Timestamp(e))]
            row[n] = m["pnl"].sum(); tot += m["pnl"].sum(); ntr += len(m)
        ep_basket[ep] = tot
        print(f"    {ep:<11}" + "".join(f"{row[n]:>10,.0f}" for n in books) + f"{tot:>11,.0f}{ntr:>8}")
    pos_eps = sum(1 for ep, _, _ in EPISODES if ep_basket[ep] > 0)
    print(f"    → basket positive in {pos_eps}/{len(EPISODES)} independent stress episodes")
    total = sum(ep_basket.values())
    if total > 0:
        worst_dep = max(ep_basket[ep] for ep, _, _ in EPISODES) / total
        print(f"    → single biggest episode = {worst_dep*100:.0f}% of total P&L "
              f"({'concentrated' if worst_dep > 0.6 else 'spread'})")

    # ── [B] portfolio aggregate ───────────────────────────────────────────────
    daily = None
    for n, df in books.items():
        s = df.groupby("day")["pnl"].sum().rename(n)
        daily = s.to_frame() if daily is None else daily.join(s, how="outer")
    daily = daily.fillna(0.0)
    basket = daily.sum(axis=1)
    eq = basket.cumsum()
    dd = (eq.cummax() - eq).max()
    ann = basket.mean() * 252
    sharpe = (basket.mean() / basket.std() * np.sqrt(252)) if basket.std() > 0 else np.nan
    calmar = (ann / dd) if dd > 0 else np.inf
    allpnl = basket[basket != 0].to_numpy()
    print("\n[B] PORTFOLIO AGGREGATE  (1 micro each, equal-weight)")
    print(f"    trading days with a trade: {(basket!=0).sum()} | total net ${basket.sum():,.0f}")
    print(f"    PF {pf(allpnl):.2f} | Sharpe {sharpe:.2f} | MaxDD ${dd:,.0f} | Calmar {calmar:.2f}")

    # ── [C] bootstrap dispersion test ─────────────────────────────────────────
    sizes = {n: len(df) for n, df in books.items()}
    obs_pf = {n: pf(df["pnl"].to_numpy()) for n, df in books.items()}
    obs_spread = max(obs_pf.values()) - min(obs_pf.values())
    pool = np.concatenate([df["pnl"].to_numpy() for df in books.values()])
    rng = np.random.default_rng(0)
    spreads = []
    for _ in range(a.boot):
        pfs = []
        for n in books:
            samp = rng.choice(pool, size=sizes[n], replace=True)
            pfs.append(pf(samp))
        spreads.append(max(pfs) - min(pfs))
    spreads = np.array(spreads)
    pctile = (spreads < obs_spread).mean() * 100
    print("\n[C] BOOTSTRAP DISPERSION  (is PF spread bigger than one-edge + noise?)")
    print(f"    observed PF per instrument: " + ", ".join(f"{n} {p:.2f}" for n, p in obs_pf.items()))
    print(f"    observed PF spread = {obs_spread:.2f}")
    print(f"    bootstrap spread (one common edge): median {np.median(spreads):.2f}, "
          f"95th pct {np.percentile(spreads,95):.2f}")
    print(f"    observed spread sits at the {pctile:.0f}th percentile of pure-noise spreads")

    # ── read ──────────────────────────────────────────────────────────────────
    print("\n" + "-" * 68)
    robust_eps = pos_eps >= 3
    noise_disp = pctile < 90
    if robust_eps and noise_disp:
        print("READ: basket positive across all independent episodes AND the per-instrument")
        print("      spread is consistent with one edge + noise → the basket edge holds up")
        print("      better than the eyeball 'it's just luck' read. Worth a pooled vault.")
    elif robust_eps and not noise_disp:
        print("READ: edge survives each episode, but instruments differ MORE than noise →")
        print("      real heterogeneity; size winners, drop the genuinely weak ones.")
    elif not robust_eps:
        print("READ: one stress episode carries the basket → NOT robust across regimes,")
        print("      same failure shape as TF. The edge is episode-dependent, fragile.")
    print("-" * 68 + "\n")

if __name__ == "__main__":
    main()
