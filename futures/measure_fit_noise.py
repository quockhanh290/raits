"""
futures/measure_fit_noise.py — sàn nhiễu của HMM fit: bao nhiêu % là seed, bao nhiêu là tín hiệu?
==================================================================================================
`compare_refit.py` đo fit-2024 vs fit-2025 lệch **5.84%** trên cửa sổ L11 (2026), và `run_gate`
đo **3.87%** trên cửa sổ 2019+. Cả hai con số vô nghĩa cho tới khi biết **hai fit CÙNG `fit_end`
nhưng khác random seed** lệch nhau bao nhiêu.

Nếu sàn nhiễu ~4% thì `GATE_AUTO_PCT = 5.0` phần lớn đang đo nhiễu chứ không đo thay đổi chế độ,
và 3.87% của `run_gate` nằm trọn trong nhiễu — tức gate không phân biệt được "fit mới" với
"chạy lại fit cũ".

TẠI SAO PHẢI DỰNG LẠI VÒNG LẶP. `_validated_core.label_regimes` hardcode
`HMMEngine(n_components=n_components)` — không có đường truyền seed vào. Script này chép lại đúng
vòng lặp đó, **chỉ thêm mỗi tham số `random_state`**, và KHÔNG sửa production.

Bản chép phải được chứng minh là trung thành, không phải tin lời: **SC-FIDELITY** chạy bản chép
với `seed=42` (chính là `engine.RANDOM_SEED`) rồi so hash nhãn với `label_regimes` thật. Sai một
dòng trong vòng lặp là check đó đỏ. Không có nó thì mọi con số dưới đây đều là đo một hệ khác.

Ghi chú: hmmlearn in `Model is not converging` ở mọi fit (EM dừng khi log-likelihood giảm nhẹ).
Script KHÔNG đếm cảnh báo đó — hmmlearn có thể phát qua `warnings` hoặc qua `logging` tuỳ phiên bản,
và một bộ đếm bắt nhầm kênh sẽ báo 0 một cách im lặng. Xem SCRATCHPAD.

CHỈ ĐỌC. Không chạm registry / basket.py / model.

Chạy từ d:\\raits (mỗi fit ~5-8s; mặc định 5 seed → dưới một phút):

    python futures/measure_fit_noise.py
    python futures/measure_fit_noise.py --seeds 42,1,7,123,2026,31337
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes
from futures.basket import REGIME
from futures.refreeze import _labels_hash

VALID_LABELS = {"Calm", "Normal", "Stress"}

# Cua so phai TRUNG voi cua so cua compare_refit.py thi so sanh moi co nghia.
L11_WINDOW_START = "2026-01-01"    # cua so L11 forward (max(fit_prev, fit_new) + 1)
GATE_WINDOW_START = "2019-01-01"   # refreeze.COMMON_START


# ── Self-checks ───────────────────────────────────────────────────────────────

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

    def add(self, cid: str, desc: str, passed: bool, detail: str = "") -> bool:
        self.items.append(Check(cid, desc, bool(passed), detail))
        return bool(passed)

    @property
    def failed(self) -> list:
        return [c for c in self.items if not c.passed]


# ── Ban chep cua label_regimes, chi khac mot tham so seed ────────────────────

def label_regimes_seeded(daily: pd.Series, train_end: str, n_components: int,
                         hmm_fit_end: str, seed: int) -> dict:
    """Chep nguyen van `_validated_core.label_regimes`, THEM `random_state=seed`.

    Moi dong duoi day phai khop ban goc. SC-FIDELITY (seed=42) la thu chung minh dieu do.
    """
    from raits.hmm.engine import HMMEngine

    train_end_ts = pd.Timestamp(train_end)
    fit_end_ts = pd.Timestamp(hmm_fit_end) if hmm_fit_end else train_end_ts

    train = daily[daily.index <= fit_end_ts]
    if len(train) < 40:
        raise ValueError(f"Not enough HMM-fit days ({len(train)}); need >=40.")

    eng = HMMEngine(n_components=n_components, random_state=seed)   # <-- KHAC BIET DUY NHAT
    eng.fit(train, version_tag="gate2_spike", save=False)

    labels: dict = {}
    for d in daily[daily.index > train_end_ts].index:
        window = daily[daily.index <= d]
        try:
            labels[pd.Timestamp(d).normalize()] = eng.state_name(eng.predict_current(window))
        except Exception:
            continue
    return labels


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _git_commit() -> str:
    try:
        c = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=10).stdout.strip()
        d = subprocess.run(["git", "status", "--porcelain"], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=30).stdout.strip()
        return (c or "unknown") + ("-dirty" if d else "")
    except Exception:
        return "unknown"


def _to_series(labels: dict) -> pd.Series:
    idx = pd.DatetimeIndex([pd.Timestamp(k).normalize() for k in labels])
    return pd.Series(list(labels.values()), index=idx).sort_index()


def pct_diff(sa: pd.Series, sb: pd.Series, start: str | None) -> tuple:
    idx = sa.index.intersection(sb.index)
    if start is not None:
        idx = idx[idx >= pd.Timestamp(start)]
    if len(idx) == 0:
        return None, 0, 0
    nd = int((sa[idx] != sb[idx]).sum())
    return round(100.0 * nd / len(idx), 4), nd, len(idx)


def _stats(vals: list) -> dict:
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"n_pairs": 0, "min": None, "median": None, "max": None}
    return {"n_pairs": len(vals), "min": round(min(vals), 4),
            "median": round(statistics.median(vals), 4), "max": round(max(vals), 4)}


def _read_signal() -> dict:
    """Doc so da do tu compare_refit_report.json — derive tu du lieu, khong hardcode."""
    p = ROOT / "futures" / "compare_refit_report.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        w = d.get("windows", {})
        return {
            "l11": (w.get("l11_forward") or {}).get("pct"),
            "gate": (w.get("refreeze_gate") or {}).get("pct"),
            "fit_prev": d.get("basis", {}).get("fit_prev"),
            "fit_new": d.get("basis", {}).get("fit_new"),
            "csv_sha": d.get("basis", {}).get("spy_csv_sha256"),
        }
    except Exception:
        return {}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="San nhieu cua HMM fit — cung fit_end, khac seed (read-only)")
    ap.add_argument("--spy-csv", default=str(ROOT / "spy_daily_live.csv"))
    ap.add_argument("--fit-end", default=REGIME["hmm_fit_end"])
    ap.add_argument("--train-end", default="2018-01-01")
    ap.add_argument("--n-components", type=int, default=REGIME["n_components"])
    ap.add_argument("--seeds", default="42,1,7,123,2026",
                    help="danh sach seed, phai co 42 (engine.RANDOM_SEED) cho SC-FIDELITY")
    ap.add_argument("--out", default=str(ROOT / "futures" / "fit_noise_report"))
    a = ap.parse_args()

    seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
    csv_path = Path(a.spy_csv)
    ck = Checks()

    print("=" * 74)
    print("SAN NHIEU HMM FIT — cung fit_end, khac random seed")
    print("=" * 74)

    if not csv_path.exists():
        print(f"\nFATAL: khong thay CSV {csv_path}")
        return 2

    bench = benchmark_daily(str(csv_path))
    basis = {
        "spy_csv":            str(csv_path),
        "spy_csv_sha256":     _sha256(csv_path),
        "spy_csv_last_date":  str(bench.index.max().date()),
        "spy_csv_rows":       int(len(bench)),
        "train_end":          a.train_end,
        "n_components":       a.n_components,
        "fit_end":            a.fit_end,
        "seeds":              seeds,
        "git_commit":         _git_commit(),
        "python":             sys.version.split()[0],
    }
    print("\nCO SO DO")
    for k, v in basis.items():
        print(f"  {k:<20} {v}")

    ck.add("SC0", "seed 42 co trong danh sach (bat buoc cho SC-FIDELITY)",
           42 in seeds, f"seeds={seeds}")
    ck.add("SC1", "co it nhat 2 seed de tao cap", len(seeds) >= 2, f"n={len(seeds)}")
    if ck.failed:
        print("\nSELF-CHECK")
        for c in ck.items:
            print(c.line())
        print("\nDUNG.")
        return 1

    # ── Ban goc production (moc de doi chieu ban chep) ───────────────────────
    print(f"\nbaseline production: label_regimes(fit_end={a.fit_end}) ...")
    t0 = time.monotonic()
    labels_prod = label_regimes(bench, a.train_end, a.n_components, a.fit_end)
    h_prod = _labels_hash(labels_prod)
    print(f"  {len(labels_prod)} nhan  hash={h_prod}  ({time.monotonic() - t0:.0f}s)")

    # ── Cac seed ─────────────────────────────────────────────────────────────
    labels_by_seed: dict = {}
    for s in seeds:
        print(f"seed {s} ...", end=" ", flush=True)
        t0 = time.monotonic()
        labels_by_seed[s] = label_regimes_seeded(
            bench, a.train_end, a.n_components, a.fit_end, s)
        print(f"{len(labels_by_seed[s])} nhan  hash={_labels_hash(labels_by_seed[s])}"
              f"  ({time.monotonic() - t0:.0f}s)")

    # ── SC-FIDELITY: ban chep phai == ban goc tai seed 42 ────────────────────
    h42 = _labels_hash(labels_by_seed[42])
    ck.add("SC-FIDELITY",
           "ban chep voi seed=42 cho nhan Y HET label_regimes production",
           h42 == h_prod, f"production={h_prod}  replica_seed42={h42}")

    ck.add("SC2", "moi seed deu tra du nhan",
           all(len(v) == len(labels_prod) for v in labels_by_seed.values()),
           f"prod={len(labels_prod)}  seeds="
           + str({s: len(v) for s, v in labels_by_seed.items()}))

    bad = set()
    for v in labels_by_seed.values():
        bad |= set(v.values()) - VALID_LABELS
    ck.add("SC3", f"nhan chi thuoc {sorted(VALID_LABELS)}", not bad,
           f"la: {sorted(bad)}" if bad else "")

    # Regime collapse: mot seed lam bien mat han mot trang thai la dau hieu hong
    dists = {s: pd.Series(list(v.values())).value_counts().to_dict()
             for s, v in labels_by_seed.items()}
    collapsed = [s for s, d in dists.items() if len(d) < a.n_components]
    ck.add("SC4", f"khong seed nao lam sap trang thai (du {a.n_components} regime)",
           not collapsed, f"seed sap: {collapsed}" if collapsed else "")

    print("\nSELF-CHECK")
    for c in ck.items:
        print(c.line())
    if ck.failed:
        print("\nDUNG — self-check do; so do khong tin duoc.")
        _write(a.out, basis, dists, {}, {}, None, ck, {}, h_prod)
        return 1

    print("\nPHAN BO NHAN THEO SEED")
    for s, d in dists.items():
        tot = sum(d.values())
        parts = "  ".join(f"{k}={v} ({100*v/tot:.1f}%)" for k, v in sorted(d.items()))
        print(f"  seed {s:<6} {parts}")

    # ── Nhieu tung doi seed, tren tung cua so ────────────────────────────────
    series = {s: _to_series(v) for s, v in labels_by_seed.items()}
    windows = {
        "l11_window":  L11_WINDOW_START,
        "gate_window": GATE_WINDOW_START,
        "full":        None,
    }
    noise: dict = {}
    pairs_detail: dict = {}
    for wname, wstart in windows.items():
        vals, detail = [], {}
        for x, y in combinations(seeds, 2):
            p, nd, n = pct_diff(series[x], series[y], wstart)
            vals.append(p)
            detail[f"{x}v{y}"] = {"pct": p, "n_diff": nd, "n": n}
        noise[wname] = _stats(vals)
        pairs_detail[wname] = detail

    sig = _read_signal()

    print("\n" + "-" * 74)
    print("SAN NHIEU (chenh lech giua cac cap seed, CUNG fit_end)")
    print(f"  {'cua so':<14} {'cap':>4} {'min':>8} {'trung vi':>10} {'max':>8}   tin hieu da do")
    for wname in windows:
        st = noise[wname]
        s_txt = ""
        if wname == "l11_window" and sig.get("l11") is not None:
            s_txt = f"   {sig['l11']:.2f}%  (fit-{sig.get('fit_prev')} vs fit-{sig.get('fit_new')})"
        elif wname == "gate_window" and sig.get("gate") is not None:
            s_txt = f"   {sig['gate']:.2f}%  (run_gate)"
        print(f"  {wname:<14} {st['n_pairs']:>4} {st['min']:>7.2f}% "
              f"{st['median']:>9.2f}% {st['max']:>7.2f}%{s_txt}")

    # ── Ket luan ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    print("KET LUAN")
    print("=" * 74)

    verdicts = {}
    for wname, key in (("l11_window", "l11"), ("gate_window", "gate")):
        s = sig.get(key)
        st = noise[wname]
        if s is None or st["median"] is None:
            continue
        if s <= st["max"]:
            v = "TRONG NHIEU"
            msg = (f"tin hieu {s:.2f}% <= nhieu max {st['max']:.2f}% — KHONG phan biet duoc "
                   f"voi viec chay lai cung mot fit bang seed khac")
        elif s <= 2 * st["median"]:
            v = "GAN NHIEU"
            msg = (f"tin hieu {s:.2f}% > nhieu max {st['max']:.2f}% nhung chua toi 2x trung vi "
                   f"({st['median']:.2f}%) — bien mong")
        else:
            v = "TREN NHIEU"
            msg = (f"tin hieu {s:.2f}% > 2x trung vi nhieu ({st['median']:.2f}%) — "
                   f"co the coi la thay doi that")
        verdicts[wname] = {"verdict": v, "signal_pct": s, "noise": st, "message": msg}
        print(f"  [{wname}] {v}: {msg}")

    if not verdicts:
        print("  Chua co futures/compare_refit_report.json — chay compare_refit.py truoc")
        print("  de co con so tin hieu doi chieu. San nhieu o tren van dung duoc.")
    else:
        print("\n  He qua cho nguong gate: GATE_AUTO_PCT = 5.0 va nguong L11 15-20% chi co nghia")
        print("  khi chung nam TREN san nhieu do o day. Doi chieu truoc khi tin bat ky verdict nao.")

    _write(a.out, basis, dists, noise, pairs_detail, verdicts, ck, sig, h_prod)
    return 0


def _write(out_base, basis, dists, noise, pairs_detail, verdicts, ck,
           sig=None, h_prod=None) -> None:
    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "basis": basis,
        "production_labels_hash": h_prod,
        "label_distribution_by_seed": {str(k): v for k, v in dists.items()},
        "noise": noise,
        "pairs": pairs_detail,
        "signal_from_compare_refit": sig or {},
        "verdicts": verdicts or {},
        "selfchecks": [{"id": c.id, "desc": c.desc,
                        "passed": c.passed, "detail": c.detail} for c in ck.items],
    }
    jp = Path(str(out_base) + ".json")
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = ["SAN NHIEU HMM FIT — cung fit_end, khac random seed",
             f"measured_at  {payload['measured_at']}", "",
             "CO SO DO", *[f"  {k:<20} {v}" for k, v in basis.items()],
             f"  {'production_hash':<20} {h_prod}", "",
             "SELF-CHECK", *[c.line() for c in ck.items], ""]
    if dists:
        lines += ["PHAN BO NHAN THEO SEED",
                  *[f"  seed {s}: {d}" for s, d in dists.items()], ""]
    if noise:
        lines += ["SAN NHIEU",
                  *[f"  {w:<14} n_pairs={st['n_pairs']}  min={st['min']}%  "
                    f"median={st['median']}%  max={st['max']}%"
                    for w, st in noise.items()], ""]
    if verdicts:
        lines += ["KET LUAN",
                  *[f"  [{w}] {v['verdict']}: {v['message']}" for w, v in verdicts.items()], ""]
    Path(str(out_base) + ".txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nDa ghi:\n  {jp}\n  {Path(str(out_base) + '.txt')}")


if __name__ == "__main__":
    raise SystemExit(main())
