"""
futures/compare_refit.py — L11 gate: model cũ có SAI không, hay chỉ là có data mới?
====================================================================================
LESSONS.md L11 đặt luật: *"Refit trigger phải là model cũ sai, không phải có data mới."*
Điều kiện 1 của L11 là một phép đo cụ thể: fit-cũ vs fit-mới **decode period hiện tại**
khác nhau bao nhiêu phần trăm, so ngưỡng ~15-20%.

Phép đo đó đã từng chạy một lần (2026-07-09, ra 93.7% giống nhau → quyết định KHÔNG refit,
ghi ở DECISIONS.md). Nhưng script gốc `compare_refit_2025.py` là scratchpad và **chưa bao giờ
được commit** — `git log --all -- "*compare_refit*"` rỗng. Nên con số 93.7% không tái tạo được,
đúng cùng một bệnh với `CALMAR_FLOOR = 2.38` và `FreezeRecord.calmar = 2.744`
(xem docs/futures/CALMAR_PROVENANCE.md).

File này là bản dựng lại, tổng quát cho mọi cặp fit_end, và **lưu kèm cơ sở đo** để lần sau
không phải đoán lại.

HAI CỬA SỔ, HAI CÂU HỎI KHÁC NHAU — báo cáo cả hai vì chúng có thể trái ngược:
  - **L11 forward**: chỉ những ngày SAU cả hai fit_end. Cả hai model đều decode-forward ở đó,
    không model nào đã thấy dữ liệu. Đây là cửa sổ trả lời "model cũ có sai không".
  - **refreeze gate**: cửa sổ của chính `run_gate` (2019-01-01 → hết chuỗi, ~7,5 năm).
    Trả lời "nhãn có đổi nhiều không". Một khác biệt dồn vào vài chục ngày gần đây
    bị pha loãng gần như biến mất trên mẫu 7,5 năm.

KHUNG ĐO = KHUNG PRODUCTION. Gọi đúng cách `run_live_day.py:242` gọi:
    label_regimes(benchmark_daily(csv), "2018-01-01", 3, fit_end)
Không clip anchor, không dedup — production không làm hai việc đó, và mục đích ở đây là đo
cái hệ thống thật sự chạy, không phải một biến thể sạch hơn.

CHỈ ĐỌC. Không chạm registry, không chạm basket.py, không ghi model.

Chạy từ d:\\raits (mất vài phút — hai lần fit HMM + decode expanding-window):

    python futures/compare_refit.py
    python futures/compare_refit.py --fit-new 2026-06-30
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes
from futures.basket import REGIME
from futures.refreeze import _labels_hash, run_gate

# L11 điều kiện 1: ngưỡng decode-flip. Dưới cận dưới → giữ model cũ.
L11_THRESHOLD_LOW = 15.0
L11_THRESHOLD_HIGH = 20.0

VALID_LABELS = {"Calm", "Normal", "Stress"}


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


# ── Basis ─────────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=str(ROOT), capture_output=True, text=True, timeout=10)
        commit = out.stdout.strip() or "unknown"
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        return commit + ("-dirty" if dirty.stdout.strip() else "")
    except Exception:
        return "unknown"


# ── Window comparison ─────────────────────────────────────────────────────────

def _to_series(labels: dict) -> pd.Series:
    idx = pd.DatetimeIndex([pd.Timestamp(k).normalize() for k in labels])
    return pd.Series(list(labels.values()), index=idx).sort_index()


def compare_window(sp: pd.Series, sn: pd.Series,
                   start: pd.Timestamp | None,
                   end: pd.Timestamp | None) -> dict:
    """% ngày khác nhau giữa hai chuỗi nhãn trên [start, end], kèm phân rã flip."""
    idx = sp.index.intersection(sn.index)
    if start is not None:
        idx = idx[idx >= start]
    if end is not None:
        idx = idx[idx <= end]
    if len(idx) == 0:
        return {"n": 0, "n_diff": 0, "pct": None, "flips": {},
                "start": None, "end": None}

    a, b = sp[idx], sn[idx]
    diff = a != b
    n_diff = int(diff.sum())

    flips: dict[str, int] = {}
    for d in idx[diff]:
        key = f"{a[d]}->{b[d]}"
        flips[key] = flips.get(key, 0) + 1

    return {
        "n": len(idx),
        "n_diff": n_diff,
        "pct": round(100.0 * n_diff / len(idx), 4),
        "flips": dict(sorted(flips.items(), key=lambda kv: -kv[1])),
        "start": str(idx.min().date()),
        "end": str(idx.max().date()),
    }


def per_year(sp: pd.Series, sn: pd.Series) -> dict:
    idx = sp.index.intersection(sn.index)
    out = {}
    for y in sorted({d.year for d in idx}):
        yi = idx[idx.year == y]
        nd = int((sp[yi] != sn[yi]).sum())
        out[str(y)] = {"n": len(yi), "n_diff": nd,
                       "pct": round(100.0 * nd / len(yi), 4) if len(yi) else None}
    return out


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="L11 refit gate — decode-flip giua hai fit_end (read-only)")
    ap.add_argument("--spy-csv", default=str(ROOT / "spy_daily_live.csv"),
                    help="CSV production dung (mac dinh spy_daily_live.csv, KHONG phai spy_daily.csv)")
    ap.add_argument("--fit-prev", default=REGIME["hmm_fit_end"],
                    help="fit_end dang chay production (mac dinh doc tu futures.basket REGIME)")
    ap.add_argument("--fit-new", default="2025-12-31", help="fit_end de xuat")
    ap.add_argument("--train-end", default="2018-01-01")
    ap.add_argument("--n-components", type=int, default=REGIME["n_components"])
    ap.add_argument("--out", default=str(ROOT / "futures" / "compare_refit_report"),
                    help="duong dan goc cho .txt va .json")
    a = ap.parse_args()

    csv_path = Path(a.spy_csv)
    ck = Checks()

    print("=" * 74)
    print("L11 REFIT GATE — decode-flip giua hai fit_end")
    print("=" * 74)

    if not csv_path.exists():
        print(f"\nFATAL: khong thay CSV {csv_path}")
        return 2

    # ── Co so do ─────────────────────────────────────────────────────────────
    bench = benchmark_daily(str(csv_path))
    basis = {
        "spy_csv":            str(csv_path),
        "spy_csv_sha256":     _sha256(csv_path),
        "spy_csv_first_date": str(bench.index.min().date()),
        "spy_csv_last_date":  str(bench.index.max().date()),
        "spy_csv_rows":       int(len(bench)),
        "train_end":          a.train_end,
        "n_components":       a.n_components,
        "fit_prev":           a.fit_prev,
        "fit_new":            a.fit_new,
        "git_commit":         _git_commit(),
        "python":             sys.version.split()[0],
    }
    print("\nCO SO DO")
    for k, v in basis.items():
        print(f"  {k:<20} {v}")

    # ── Self-check truoc khi fit (re hon fit xong moi biet tien de sai) ──────
    fp_ts, fn_ts = pd.Timestamp(a.fit_prev), pd.Timestamp(a.fit_new)
    last_ts = bench.index.max()

    ck.add("SC1", "CSV phu den fit_new (khong fit tren du lieu cut)",
           last_ts >= fn_ts, f"CSV last={last_ts.date()}  fit_new={fn_ts.date()}")
    ck.add("SC2", "fit_new > fit_prev", fn_ts > fp_ts,
           f"{fp_ts.date()} -> {fn_ts.date()}")
    dup = int(bench.index.duplicated().sum())
    ck.add("SC3", "CSV khong co ngay trung (duong swing production khong dedup)",
           dup == 0, f"{dup} ngay trung")

    if ck.failed:
        print("\nSELF-CHECK TRUOC FIT")
        for c in ck.items:
            print(c.line())
        print("\nDUNG — khong fit khi tien de da sai.")
        return 1

    # ── Fit ──────────────────────────────────────────────────────────────────
    print(f"\nfit prev ({a.fit_prev}) — expanding-window decode, vai phut...")
    t0 = time.monotonic()
    labels_prev = label_regimes(bench, a.train_end, a.n_components, a.fit_prev)
    print(f"  {len(labels_prev)} nhan  ({time.monotonic() - t0:.0f}s)")

    print(f"fit new  ({a.fit_new}) ...")
    t0 = time.monotonic()
    labels_new = label_regimes(bench, a.train_end, a.n_components, a.fit_new)
    print(f"  {len(labels_new)} nhan  ({time.monotonic() - t0:.0f}s)")

    sp, sn = _to_series(labels_prev), _to_series(labels_new)
    h_prev, h_new = _labels_hash(labels_prev), _labels_hash(labels_new)

    # ── Self-check sau fit ───────────────────────────────────────────────────
    ck.add("SC4", "ca hai bo nhan khong rong",
           len(labels_prev) > 0 and len(labels_new) > 0,
           f"prev={len(labels_prev)} new={len(labels_new)}")

    only_p = sp.index.difference(sn.index)
    only_n = sn.index.difference(sp.index)
    ck.add("SC5", "hai bo nhan phu cung tap ngay",
           len(only_p) == 0 and len(only_n) == 0,
           f"chi co o prev={len(only_p)}  chi co o new={len(only_n)}")

    bad = (set(sp.unique()) | set(sn.unique())) - VALID_LABELS
    ck.add("SC6", f"nhan chi thuoc {sorted(VALID_LABELS)}",
           not bad, f"la: {sorted(bad)}" if bad else "")

    ck.add("SC7", "hai fit KHAC nhau (hash khac) — giong het = fit_end khong co tac dung",
           h_prev != h_new, f"prev={h_prev} new={h_new}")

    fwd_start = max(fp_ts, fn_ts) + pd.Timedelta(days=1)
    l11 = compare_window(sp, sn, fwd_start, None)
    ck.add("SC8", "cua so L11 forward du ngay de ket luan (>=20)",
           l11["n"] >= 20, f"n={l11['n']} tu {fwd_start.date()}")

    ck.add("SC9", "phan tram nam trong [0,100]",
           l11["pct"] is not None and 0.0 <= l11["pct"] <= 100.0, f"pct={l11['pct']}")

    print("\nSELF-CHECK")
    for c in ck.items:
        print(c.line())

    if ck.failed:
        print("\nDUNG — self-check do; khong dua verdict tren phep do khong tin duoc.")
        _write(a.out, basis, h_prev, h_new, labels_prev, labels_new,
               l11, None, {}, None, ck)
        return 1

    # ── Hai cua so ───────────────────────────────────────────────────────────
    gate = run_gate(labels_prev, labels_new)
    years = per_year(sp, sn)

    print("\n" + "-" * 74)
    print(f"CUA SO 1 — L11 forward  ({l11['start']} .. {l11['end']})")
    print("  Ca hai model deu decode-forward o day; khong model nao da thay du lieu.")
    print(f"  {l11['n_diff']} / {l11['n']} ngay khac  =  {l11['pct']:.2f}%"
          f"   (giong nhau {100 - l11['pct']:.2f}%)")
    if l11["flips"]:
        print("  Phan ra flip:")
        for k, v in l11["flips"].items():
            print(f"    {k:<22} {v} ngay")
    else:
        print("  Khong co ngay nao khac nhau.")

    print("\n" + "-" * 74)
    print("CUA SO 2 — refreeze run_gate  (COMMON_START 2019-01-01 .. het chuoi)")
    print(f"  verdict={gate.verdict}  {gate.pct_change:.2f}%  "
          f"({gate.n_diff}/{gate.n_common} ngay)  calm_flips={gate.calm_flip_count}")
    print(f"  {gate.reason}")

    print("\n" + "-" * 74)
    print("PHAN RA THEO NAM")
    print(f"  {'nam':<6} {'n':>5} {'khac':>6} {'%':>8}")
    for y, d in years.items():
        pct_y = d["pct"] if d["pct"] is not None else float("nan")
        print(f"  {y:<6} {d['n']:>5} {d['n_diff']:>6} {pct_y:>7.2f}%")

    # ── Verdict L11 dieu kien 1 ──────────────────────────────────────────────
    pct = l11["pct"]
    if pct < L11_THRESHOLD_LOW:
        verdict = "HOLD"
        rationale = (f"{pct:.2f}% < {L11_THRESHOLD_LOW}% — dieu kien 1 cua L11 KHONG dat. "
                     f"Co data moi khong dong nghia model cu sai. Giu fit_prev.")
    elif pct <= L11_THRESHOLD_HIGH:
        verdict = "BORDERLINE"
        rationale = (f"{pct:.2f}% trong vung xam {L11_THRESHOLD_LOW}-{L11_THRESHOLD_HIGH}%. "
                     f"Can dieu kien 2 va 3 truoc khi quyet.")
    else:
        verdict = "REFIT-CANDIDATE"
        rationale = (f"{pct:.2f}% > {L11_THRESHOLD_HIGH}% — dieu kien 1 DAT. "
                     f"Van con dieu kien 2 va 3 phai kiem.")

    print("\n" + "=" * 74)
    print(f"VERDICT (L11 dieu kien 1): {verdict}")
    print("=" * 74)
    print(f"  {rationale}")
    print("\n  Hai dieu kien L11 con lai KHONG do duoc bang script nay:")
    print("    [2] Model cu co miss regime that khong? — so nhan voi thi truong that")
    print("    [3] Co OOS moi bu cho period bi dua vao fit khong?")
    print(f"  Chi phi refit {a.fit_prev} -> {a.fit_new}: period do thanh in-sample,")
    print("  phai re-validate baseline / floor / vault tren fit moi.")

    _write(a.out, basis, h_prev, h_new, labels_prev, labels_new,
           l11, gate, years, {"verdict": verdict, "rationale": rationale}, ck)
    return 0


def _write(out_base, basis, h_prev, h_new, labels_prev, labels_new,
           l11, gate, years, verdict, ck) -> None:
    """Ghi ca .json (may doc) va .txt (nguoi doc). Luon kem co so do."""
    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "basis": basis,
        "labels": {
            "hash_prev": h_prev, "hash_new": h_new,
            "n_prev": len(labels_prev), "n_new": len(labels_new),
        },
        "windows": {
            "l11_forward":   l11,
            "refreeze_gate": (None if gate is None else {
                "verdict": gate.verdict, "pct": gate.pct_change,
                "n_diff": gate.n_diff, "n_common": gate.n_common,
                "calm_flip_count": gate.calm_flip_count,
                "flips": gate.flip_breakdown, "reason": gate.reason,
            }),
            "per_year": years,
        },
        "verdict": verdict,
        "selfchecks": [{"id": c.id, "desc": c.desc,
                        "passed": c.passed, "detail": c.detail} for c in ck.items],
    }
    jp = Path(str(out_base) + ".json")
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "L11 REFIT GATE — decode-flip giua hai fit_end",
        f"measured_at  {payload['measured_at']}",
        "",
        "CO SO DO",
        *[f"  {k:<20} {v}" for k, v in basis.items()],
        f"  {'labels_hash_prev':<20} {h_prev}",
        f"  {'labels_hash_new':<20} {h_new}",
        "",
        "SELF-CHECK",
        *[c.line() for c in ck.items],
        "",
    ]
    if l11 and l11.get("pct") is not None:
        lines += [
            f"CUA SO L11 forward  {l11['start']} .. {l11['end']}",
            f"  {l11['n_diff']}/{l11['n']} ngay khac = {l11['pct']:.2f}%",
            *[f"    {k:<22} {v}" for k, v in l11["flips"].items()],
            "",
        ]
    if gate is not None:
        lines += [
            "CUA SO refreeze run_gate  2019-01-01 .. het chuoi",
            f"  {gate.verdict}  {gate.pct_change:.2f}%  ({gate.n_diff}/{gate.n_common})",
            "",
        ]
    if years:
        lines += ["PHAN RA THEO NAM",
                  *[f"  {y}  n={d['n']:>4}  khac={d['n_diff']:>4}  {d['pct']:.2f}%"
                    for y, d in years.items()],
                  ""]
    if verdict:
        lines += [f"VERDICT  {verdict['verdict']}", f"  {verdict['rationale']}", ""]

    tp = Path(str(out_base) + ".txt")
    tp.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nDa ghi:\n  {jp}\n  {tp}")


if __name__ == "__main__":
    raise SystemExit(main())
