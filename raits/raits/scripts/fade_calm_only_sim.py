"""
Retroactive sim: FADE Calm-only (remove Normal regime FADE).
Loads scenario_g pkl, no engine re-run needed.

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_calm_only_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
SCENE_G  = os.path.join(SNAP_DIR, "results_scenario_g.pkl")


def load_trades(path):
    with open(path, "rb") as f:
        results = pickle.load(f)
    rows = []
    for window in results:
        yr = window.get("label", "?")
        for t in window.get("trades", []):
            d = t.__dict__.copy() if hasattr(t, "__dict__") else dict(t)
            d["year"] = yr
            rows.append(d)
    df = pd.DataFrame(rows)
    if "strategy" in df.columns:
        df["strategy_type"] = df["strategy"]
    return df


def div(label, w=68):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")


all_trades = load_trades(SCENE_G)
fade = all_trades[all_trades["strategy_type"] == "FADE"].copy()
non_fade_pnl = all_trades[all_trades["strategy_type"] != "FADE"]["net_pnl"].sum()

# ── FADE by regime × year ─────────────────────────────────────────────────────
div("FADE P&L by REGIME × YEAR (Scenario G)")
piv = fade.groupby(["year", "hmm_state"])["net_pnl"].agg(n="count", total="sum").reset_index()
piv["total"] = piv["total"].round(0).astype(int)
print(piv.to_string(index=False))

div("FADE: Calm trades vs Normal trades")
for regime in ["Calm", "Normal"]:
    r = fade[fade["hmm_state"] == regime]
    print(f"\n  {regime}: {len(r)} trades, ${r['net_pnl'].sum():+.0f}, "
          f"win={(r['net_pnl']>0).mean()*100:.1f}%")
    for yr in ["2020", "2021", "2022"]:
        ry = r[r["year"] == yr]
        if len(ry):
            w = (ry["net_pnl"] > 0).sum()
            print(f"    {yr}: {len(ry)} trades, {w/len(ry)*100:.0f}% win, ${ry['net_pnl'].sum():+.0f}")

# ── Direction × Regime ───────────────────────────────────────────────────────
div("FADE: Direction × Regime breakdown")
for regime in ["Calm", "Normal"]:
    for direction in ["SHORT", "LONG"]:
        sub = fade[(fade["hmm_state"] == regime) & (fade["direction"] == direction)]
        if len(sub):
            print(f"  {regime} {direction}: {len(sub)} trades, "
                  f"{(sub['net_pnl']>0).mean()*100:.0f}% win, ${sub['net_pnl'].sum():+.0f}")

# ── Calm-only sim ─────────────────────────────────────────────────────────────
div("SCENARIO COMPARISON")

scenarios = {
    "G — current (Calm + Normal FADE)":
        fade,
    "H — Calm-only FADE":
        fade[fade["hmm_state"] == "Calm"],
    "I — Normal-only FADE":
        fade[fade["hmm_state"] == "Normal"],
}

print(f"\n  {'Scenario':<40} {'FADE':>8} {'System':>8} {'Trades':>7}")
print(f"  {'-'*65}")
for name, f in scenarios.items():
    fp = f["net_pnl"].sum()
    sp = fp + non_fade_pnl
    print(f"  {name:<40} {fp:>+8.0f} {sp:>+8.0f} {len(f):>7}")

# ── Calm-only year breakdown ──────────────────────────────────────────────────
div("SCENARIO H (Calm-only) — year breakdown")
calm_fade = fade[fade["hmm_state"] == "Calm"]
for yr in ["2020", "2021", "2022"]:
    f = calm_fade[calm_fade["year"] == yr]
    if len(f):
        w = (f["net_pnl"] > 0).sum()
        print(f"  {yr}: {len(f):>3} trades, {w/len(f)*100:.0f}% win, ${f['net_pnl'].sum():+.0f}")
    else:
        print(f"  {yr}:   0 trades")

# ── Normal-only for context ───────────────────────────────────────────────────
div("SCENARIO I (Normal-only) — year breakdown")
norm_fade = fade[fade["hmm_state"] == "Normal"]
for yr in ["2020", "2021", "2022"]:
    f = norm_fade[norm_fade["year"] == yr]
    if len(f):
        w = (f["net_pnl"] > 0).sum()
        print(f"  {yr}: {len(f):>3} trades, {w/len(f)*100:.0f}% win, ${f['net_pnl'].sum():+.0f}")
    else:
        print(f"  {yr}:   0 trades")

# ── What's being removed (Normal FADE trades)? ────────────────────────────────
div("NORMAL REGIME FADE — what gets removed in Scenario H")
norm = fade[fade["hmm_state"] == "Normal"]
print(f"  Total removed: {len(norm)} trades, ${norm['net_pnl'].sum():+.0f}")
print(f"\n  By direction:")
for d in ["SHORT", "LONG"]:
    s = norm[norm["direction"] == d]
    print(f"    {d}: {len(s)} trades, ${s['net_pnl'].sum():+.0f}")
print(f"\n  By ticker (top losers):")
tk = norm.groupby("ticker")["net_pnl"].agg(n="count", total="sum").reset_index()
tk["total"] = tk["total"].round(0).astype(int)
print(tk.nsmallest(8, "total")[["ticker","n","total"]].to_string(index=False))
