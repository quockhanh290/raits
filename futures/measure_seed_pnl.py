"""
futures/measure_seed_pnl.py — chênh lệch nhãn theo seed có thành TIỀN không?
=============================================================================
`measure_fit_noise.py` cho thấy đổi random seed làm đổi 1.20-7.58% số nhãn, và số ngày
Stress trượt 253-321. Nhưng nhãn khác ≠ tiền khác: entry còn phải qua chandelier, cap
cụm, sizer, circuit breaker. Script này đo phần tiền.

CÁCH ĐO — KHÔNG CHÉP LẠI deploy_sim. Chép lại một pipeline 150 dòng là mời đúng loại lỗi
mà cả phiên này đang truy: bản chép trôi khỏi bản gốc rồi vẫn ra số trông hợp lý. Thay vào đó
script tự spawn chính nó ở chế độ con; tiến trình con **vá `HMMEngine.__init__` để ghim seed**
rồi gọi thẳng `global_index.deploy_sim.main()`. Đường đi là đường production, khác đúng một hằng số.

Mỗi seed chạy trong **tiến trình riêng** — không phải để cho đẹp: `_validated_core` giữ
`_SWING_CACHE` ở module level, và một cache không khoá theo nhãn sẽ trả kết quả của seed trước
mà không báo gì. Tiến trình riêng loại bỏ cả lớp lỗi đó.

NEO TRƯỚC, ĐO SAU. Seed 42 (`engine.RANDOM_SEED`) phải tái tạo baseline INVARIANTS.md dòng 22:
**net $42,459 / Calmar 1.72**. Lệch là dừng — hoặc harness sai, hoặc invariant đã trôi, và cả hai
đều phải xử lý trước khi tin bất kỳ con số per-seed nào. Đã verify tay 2026-08-15: khớp chính xác.

CƠ SỞ ĐO (ghim, khớp cách `BACKTEST_CALMAR_FLOOR = 1.65` được đo — runner.py:100-105):
    frozen_sim + NKD_frozen_2024 + spy_daily_live.csv + --end 2024-12-31
    + --n-contracts 1 + --slippage-ticks 2 + KHÔNG --include-stress

⚠️ `deploy_sim` sập `UnicodeEncodeError` khi stdout bị chuyển hướng ra file/pipe trên Windows
(ký tự `ổ` trong "Rổ 4" vs cp1252) — chạy xong 2m41s rồi mới chết ở dòng print đầu tiên.
Tiến trình con ở đây gọi `sys.stdout.reconfigure(encoding="utf-8")` trước khi vào `main()`.

CHỈ ĐỌC với production: không chạm registry / basket.py / model / parquet.

Chạy từ d:\\raits — mỗi run ~2m41s, mặc định 5 seed → ~13 phút. Có cache, chạy lại chỉ đo phần thiếu:

    python futures/measure_seed_pnl.py
    python futures/measure_seed_pnl.py --seeds 42,1,7
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── Che do con: va seed roi goi deploy_sim.main() ────────────────────────────
# Phai xu ly TRUOC moi import nang de tien trinh con khong lam thua viec cua cha.
if "--child-seed" in sys.argv:
    _i = sys.argv.index("--child-seed")
    _seed = int(sys.argv[_i + 1])
    _rest = sys.argv[_i + 2:]
    if _rest and _rest[0] == "--":
        _rest = _rest[1:]

    try:
        sys.stdout.reconfigure(encoding="utf-8")          # deploy_sim thieu cai nay
    except Exception:
        pass

    from raits.hmm import engine as _eng
    _orig_init = _eng.HMMEngine.__init__

    def _seeded_init(self, *a, **kw):
        kw.setdefault("random_state", _seed)               # KHAC BIET DUY NHAT
        _orig_init(self, *a, **kw)

    _eng.HMMEngine.__init__ = _seeded_init

    from global_index import deploy_sim as _ds
    sys.argv = ["deploy_sim"] + _rest
    _ds.main()
    raise SystemExit(0)


# ── Che do cha ────────────────────────────────────────────────────────────────

METRIC_RE = re.compile(
    r"net \$([\d,\-]+)\s*\|\s*Calmar\s+([\d.\-]+)\s*\|\s*PF\s+([\d.\-]+)\s*\|\s*Sharpe\s+([\d.\-]+)")
MAXDD_RE = re.compile(r"MaxDD \$([\d,\-]+)\s*\(([\d.\-]+)%\)")
TAKEN_RE = re.compile(r"(\w+)\s+taken\s+(\d+)\s+rejected\s+(\d+)")


@dataclass
class Check:
    id: str
    desc: str
    passed: bool
    detail: str = ""

    def line(self) -> str:
        head = f"  [{'PASS' if self.passed else 'FAIL'}] {self.id}  {self.desc}"
        return head + (f"\n         {self.detail}" if self.detail else "")


@dataclass
class Checks:
    items: list = field(default_factory=list)

    def add(self, cid, desc, passed, detail="") -> bool:
        self.items.append(Check(cid, desc, bool(passed), detail))
        return bool(passed)

    @property
    def failed(self):
        return [c for c in self.items if not c.passed]


def _git_commit() -> str:
    try:
        c = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=10).stdout.strip()
        d = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=30).stdout.strip()
        return (c or "unknown") + ("-dirty" if d else "")
    except Exception:
        return "unknown"


def run_seed(seed: int, sim_args: list) -> dict:
    """Spawn tien trinh con, chay deploy_sim voi seed ghim, parse metrics."""
    cmd = [sys.executable, str(Path(__file__).resolve()),
           "--child-seed", str(seed), "--"] + sim_args
    t0 = time.monotonic()
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    took = time.monotonic() - t0

    if p.returncode != 0:
        return {"seed": seed, "ok": False, "took_s": round(took, 1),
                "error": (p.stderr or p.stdout or "")[-800:]}

    m = METRIC_RE.search(p.stdout)
    d = MAXDD_RE.search(p.stdout)
    if not m or not d:
        return {"seed": seed, "ok": False, "took_s": round(took, 1),
                "error": "khong parse duoc DEPLOY METRICS tu stdout:\n" + p.stdout[-800:]}

    taken = {g[0]: {"taken": int(g[1]), "rejected": int(g[2])}
             for g in TAKEN_RE.findall(p.stdout)}
    return {
        "seed": seed, "ok": True, "took_s": round(took, 1),
        "net": int(m.group(1).replace(",", "")),
        "calmar": float(m.group(2)),
        "pf": float(m.group(3)),
        "sharpe": float(m.group(4)),
        "maxdd": int(d.group(1).replace(",", "")),
        "maxdd_pct": float(d.group(2)),
        "clusters": taken,
    }


def _spread(vals: list) -> dict:
    vals = [v for v in vals if v is not None]
    if not vals:
        return {}
    out = {"n": len(vals), "min": min(vals), "max": max(vals),
           "median": statistics.median(vals), "range": max(vals) - min(vals)}
    if len(vals) > 1:
        out["stdev"] = round(statistics.stdev(vals), 4)
    if out["median"]:
        out["range_pct_of_median"] = round(100.0 * out["range"] / abs(out["median"]), 2)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="P&L theo random seed cua HMM, tren co so ghim (read-only)")
    ap.add_argument("--seeds", default="42,1,7,123,2026",
                    help="phai co 42 (engine.RANDOM_SEED) — dung lam neo")
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--nkd-parquet", default="global_index/data/NKD_frozen_2024.parquet")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--n-contracts", type=int, default=1)
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--hmm-fit-end", default=None, help="mac dinh lay tu futures.basket REGIME")
    # Neo: INVARIANTS.md dong 22 (baseline fit_C, frozen, 2-tick, causal, MAX_HOLD 09:30, nkd 6%)
    ap.add_argument("--anchor-calmar", type=float, default=1.72)
    ap.add_argument("--anchor-net", type=int, default=42459)
    ap.add_argument("--out", default=str(ROOT / "futures" / "seed_pnl_report"))
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    from futures.basket import REGIME
    fit_end = a.hmm_fit_end or REGIME["hmm_fit_end"]
    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    ck = Checks()

    sim_args = [
        "--data-dir", a.data_dir,
        "--nkd-parquet", a.nkd_parquet,
        "--regime-csv", a.regime_csv,
        "--end", a.end,
        "--n-contracts", str(a.n_contracts),
        "--slippage-ticks", str(a.slippage_ticks),
        "--hmm-fit-end", fit_end,
    ]

    basis = {
        "data_dir": a.data_dir, "nkd_parquet": a.nkd_parquet, "regime_csv": a.regime_csv,
        "end": a.end, "n_contracts": a.n_contracts, "slippage_ticks": a.slippage_ticks,
        "include_stress": False, "hmm_fit_end": fit_end, "seeds": seeds,
        "anchor_calmar": a.anchor_calmar, "anchor_net": a.anchor_net,
        "anchor_source": "docs/futures/INVARIANTS.md line 22",
        "deploy_sim_args": " ".join(sim_args),
        "git_commit": _git_commit(), "python": sys.version.split()[0],
    }

    print("=" * 74)
    print("P&L THEO SEED — co so ghim, deploy_sim duong production")
    print("=" * 74)
    print("\nCO SO DO")
    for k, v in basis.items():
        print(f"  {k:<20} {v}")

    ck.add("SC0", "seed 42 co trong danh sach (bat buoc — dung lam neo)",
           42 in seeds, f"seeds={seeds}")
    if ck.failed:
        print("\nSELF-CHECK")
        for c in ck.items:
            print(c.line())
        print("\nDUNG.")
        return 1

    # ── Cache: chay lai chi do phan thieu ────────────────────────────────────
    jp = Path(str(a.out) + ".json")
    cache = {}
    if jp.exists() and not a.no_cache:
        try:
            old = json.loads(jp.read_text(encoding="utf-8"))
            if old.get("basis", {}).get("deploy_sim_args") == basis["deploy_sim_args"]:
                cache = {int(k): v for k, v in old.get("runs", {}).items() if v.get("ok")}
                if cache:
                    print(f"\n  cache: dung lai {sorted(cache)} (cung co so do)")
        except Exception:
            pass

    # ── Neo truoc: seed 42 ───────────────────────────────────────────────────
    print(f"\nNEO — seed 42, ky vong net ${a.anchor_net:,} / Calmar {a.anchor_calmar}")
    r42 = cache.get(42) or run_seed(42, sim_args)
    if not r42.get("ok"):
        print(f"  LOI: {r42.get('error')}")
        ck.add("SC-ANCHOR", "seed 42 chay duoc", False, r42.get("error", "")[:300])
        print("\nSELF-CHECK")
        for c in ck.items:
            print(c.line())
        return 1
    print(f"  net ${r42['net']:,}  Calmar {r42['calmar']}  MaxDD ${r42['maxdd']:,} "
          f"({r42['maxdd_pct']}%)  [{r42['took_s']}s]")

    ck.add("SC-ANCHOR",
           "seed 42 tai tao baseline INVARIANTS (net + Calmar)",
           r42["calmar"] == a.anchor_calmar and r42["net"] == a.anchor_net,
           f"do duoc net=${r42['net']:,} calmar={r42['calmar']}  |  "
           f"ky vong net=${a.anchor_net:,} calmar={a.anchor_calmar}")

    if ck.failed:
        print("\nSELF-CHECK")
        for c in ck.items:
            print(c.line())
        print("\nDUNG — neo truot. Hoac harness sai, hoac invariant da troi.")
        print("Khong doc so per-seed nao khi neo chua dung.")
        _write(a.out, basis, {42: r42}, {}, ck)
        return 1

    # ── Cac seed con lai ─────────────────────────────────────────────────────
    runs = {42: r42}
    for s in [x for x in seeds if x != 42]:
        if s in cache:
            runs[s] = cache[s]
            print(f"seed {s:<6} (cache) net ${runs[s]['net']:,}  Calmar {runs[s]['calmar']}")
            continue
        print(f"seed {s:<6} ...", end=" ", flush=True)
        r = run_seed(s, sim_args)
        runs[s] = r
        if r.get("ok"):
            print(f"net ${r['net']:,}  Calmar {r['calmar']}  MaxDD ${r['maxdd']:,} "
                  f"({r['maxdd_pct']}%)  [{r['took_s']}s]")
        else:
            print(f"LOI — {r.get('error','')[:200]}")

    ok_runs = {s: r for s, r in runs.items() if r.get("ok")}
    ck.add("SC1", "moi seed chay xong", len(ok_runs) == len(seeds),
           f"{len(ok_runs)}/{len(seeds)} thanh cong")
    ck.add("SC2", "moi run deu duoi cung mot co so do", True, basis["deploy_sim_args"])

    # ── Phan tan ─────────────────────────────────────────────────────────────
    spread = {k: _spread([r[k] for r in ok_runs.values()])
              for k in ("net", "calmar", "maxdd", "pf", "sharpe")}

    print("\nSELF-CHECK")
    for c in ck.items:
        print(c.line())

    print("\n" + "-" * 74)
    print("KET QUA THEO SEED")
    print(f"  {'seed':<8} {'net $':>10} {'Calmar':>8} {'MaxDD $':>10} {'PF':>6} {'Sharpe':>7}")
    for s in seeds:
        r = runs.get(s, {})
        if r.get("ok"):
            print(f"  {s:<8} {r['net']:>10,} {r['calmar']:>8.2f} {r['maxdd']:>10,} "
                  f"{r['pf']:>6.2f} {r['sharpe']:>7.2f}")
        else:
            print(f"  {s:<8} {'LOI':>10}")

    print("\n" + "-" * 74)
    print("PHAN TAN")
    for k, sp in spread.items():
        if not sp:
            continue
        rng = sp.get("range_pct_of_median")
        print(f"  {k:<8} min={sp['min']:>10,.2f}  median={sp['median']:>10,.2f}  "
              f"max={sp['max']:>10,.2f}  range={sp['range']:>10,.2f}"
              + (f"  ({rng}% cua median)" if rng is not None else ""))

    # ── Doi chieu voi floor ──────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("KET LUAN")
    print("=" * 74)
    csp = spread.get("calmar", {})
    if csp:
        try:
            from global_index.runner import BACKTEST_CALMAR_FLOOR as FLOOR
        except Exception:
            FLOOR = None
        print(f"  Calmar trai tu {csp['min']:.2f} den {csp['max']:.2f} "
              f"chi do doi random seed (range {csp['range']:.2f}).")
        if FLOOR is not None:
            below = [s for s, r in ok_runs.items() if r["calmar"] < FLOOR]
            print(f"  Floor dang dung (runner.BACKTEST_CALMAR_FLOOR) = {FLOOR}")
            if below:
                print(f"  ⚠️ {len(below)}/{len(ok_runs)} seed cho Calmar DUOI floor: {sorted(below)}")
                print("     → floor khong phan biet duoc 'he suy giam' voi 'doi seed'.")
            else:
                print(f"  Moi seed deu tren floor (min {csp['min']:.2f} > {FLOOR}) — "
                      f"bien hep nhat = {csp['min'] - FLOOR:.2f}")
        print("\n  Luu y: day la phan tan cua CHINH mot he khong doi gi ngoai seed.")
        print("  Moi nguong dat tren Calmar phai rong hon khoang nay moi co nghia.")

    _write(a.out, basis, runs, spread, ck)
    return 0 if not ck.failed else 1


def _write(out_base, basis, runs, spread, ck) -> None:
    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "basis": basis,
        "runs": {str(k): v for k, v in runs.items()},
        "spread": spread,
        "selfchecks": [{"id": c.id, "desc": c.desc, "passed": c.passed,
                        "detail": c.detail} for c in ck.items],
    }
    jp = Path(str(out_base) + ".json")
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = ["P&L THEO SEED — co so ghim, deploy_sim duong production",
             f"measured_at  {payload['measured_at']}", "",
             "CO SO DO", *[f"  {k:<20} {v}" for k, v in basis.items()], "",
             "SELF-CHECK", *[c.line() for c in ck.items], "",
             "KET QUA THEO SEED"]
    for s, r in sorted(runs.items()):
        if r.get("ok"):
            lines.append(f"  seed {s:<6} net=${r['net']:,}  Calmar={r['calmar']}  "
                         f"MaxDD=${r['maxdd']:,} ({r['maxdd_pct']}%)  "
                         f"PF={r['pf']}  Sharpe={r['sharpe']}")
        else:
            lines.append(f"  seed {s:<6} LOI: {r.get('error','')[:200]}")
    lines += ["", "PHAN TAN",
              *[f"  {k:<8} {sp}" for k, sp in spread.items() if sp], ""]
    Path(str(out_base) + ".txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nDa ghi:\n  {jp}\n  {Path(str(out_base) + '.txt')}")


if __name__ == "__main__":
    raise SystemExit(main())
