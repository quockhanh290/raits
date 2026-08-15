"""
futures/detect_regime_miss.py — L11 điều kiện 2: model đông cứng có gán SAI regime không?
==========================================================================================
`compare_refit.py` trả lời điều kiện 1 của LESSONS L11 (fit cũ vs fit mới decode khác bao nhiêu).
Nó có một điểm mù nghiêm trọng: nó so HMM với **chính HMM**. Nếu cả hai fit cùng sai theo một
kiểu, nó báo 0% và mọi thứ trông ổn.

File này trả lời câu còn lại: nhãn có còn ĐÚNG với thị trường không.

BA LỚP, ĐỘ ĐỘC LẬP KHÁC NHAU — và phải nói rõ, vì gọi nhầm là tự lừa mình.

  Lớp A — ĐỘC LẬP THẬT (dự báo tiến).
      `raits/hmm/features.py` cho thấy HMM chỉ nhìn hai thứ: log-return ngày và vol thực hiện
      5 ngày TRAILING. Nó không bao giờ thấy tương lai. Nên câu hỏi công bằng là: nhãn hôm nay
      có dự báo được vol thực hiện 10 ngày TỚI không? Đo bằng xác suất vượt trội (Mann-Whitney
      AUC) giữa ngày Stress và ngày Calm. 1.0 = phân tách hoàn hảo, 0.5 = không mang thông tin.
      Dựa trên hạng, không ngưỡng, không có gì để tinh chỉnh.

  Lớp B — KHÔNG ĐỘC LẬP (nhất quán nội bộ).
      Vol 5 ngày trailing CHÍNH LÀ feature của model. So nhãn với nó không kiểm được tính đúng,
      chỉ kiểm được model có dùng đầu vào của nó một cách nhất quán không. Vẫn đáng chạy: nó bắt
      sập trạng thái và đảo thứ tự — đúng kiểu hỏng của lần retrain 20260619 (Normal sập vào Calm).
      Output ghi rõ đây là nhất quán, không phải hiệu lực.

  Lớp C — ĐỘC LẬP YẾU.
      Sụt từ đỉnh 60 ngày là một hàm khác của cùng chuỗi giá, và KHÔNG nằm trong feature set.
      Độc lập hơn lớp B, kém hơn lớp A.

NEO TRƯỚC, ĐO SAU. Trên giai đoạn IS, lớp A phải cho AUC >= ANCHOR_AUC_MIN và lớp B phải xếp
đúng thứ tự Calm < Normal < Stress. Không đạt thì hoặc detector sai, hoặc tiền đề sai — dừng,
KHÔNG phát verdict. Cùng kỷ luật với SC-ANCHOR trong `measure_seed_pnl.py`.

KHÔNG CÓ NGƯỠNG SUY GIẢM. Script này báo cáo AUC của giai đoạn gần đây cạnh AUC của IS, kèm cỡ
mẫu, và chỉ tự kết luận ở hai trường hợp không thể cãi: thứ tự bị ĐẢO, hoặc AUC tụt xuống <= 0.5
(hết sạch thông tin). Đặt một ngưỡng kiểu "giảm 15% là báo động" cần block bootstrap trên chuỗi
tự tương quan — chưa làm, nên không bịa ra.

KHÔNG ĐO ĐƯỢC KHI KHÔNG CÓ STRESS. Nếu cửa sổ gần đây không có đủ ngày Stress thì không có cách
nào biết model còn nhận ra Stress hay không. Khi đó script nói thẳng "không đánh giá được" thay
vì trả một con số — trùng với trạng thái "STRESS sleeve OOS-pending-bear" đã ghi ở OOS_VALIDATION_LOG.

CHỈ ĐỌC. Không chạm registry / basket.py / model / parquet.

Chạy từ d:\\raits (một lần fit HMM, ~10s):

    python futures/detect_regime_miss.py
    python futures/detect_regime_miss.py --recent-months 24
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes
from futures.basket import REGIME

# Khớp raits/hmm/features.py — lớp B phải dùng ĐÚNG feature của model, không phải biến thể.
VOL_WINDOW = 5
ANNUALISATION = np.sqrt(252)

FORWARD_DAYS = 10        # cửa sổ dự báo tiến của lớp A
DRAWDOWN_WINDOW = 60     # đỉnh trailing cho lớp C
IS_START = "2018-01-02"  # ngày nhãn đầu tiên (train_end = 2018-01-01)
IS_END = "2024-12-31"    # = hmm_fit_end production; sau mốc này là ngoài mẫu fit

ANCHOR_AUC_MIN = 0.70    # lớp A trên IS phải đạt, nếu không thì detector/tiền đề sai
MIN_CALM_DAYS = 20       # cỡ mẫu tối thiểu để tính AUC cửa sổ gần đây
MIN_STRESS_DAYS = 10


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


# ── Chỉ báo ───────────────────────────────────────────────────────────────────

def build_indicators(close: pd.Series) -> pd.DataFrame:
    """Ba chỉ báo, mỗi cái ghi rõ nó nhìn về phía nào so với ngày t."""
    logret = np.log(close / close.shift(1))

    # Lớp B: ĐÚNG feature của model (trailing, gồm cả ngày t).
    vol_trail = logret.rolling(VOL_WINDOW).std() * ANNUALISATION

    # Lớp A: CHỈ tương lai. shift(-1) đẩy cửa sổ sang t+1..t+FORWARD_DAYS nên ngày t không
    # đóng góp gì. FORWARD_DAYS ngày cuối chuỗi thành NaN — SC-NOLOOKAHEAD kiểm điều đó.
    vol_fwd = (logret.shift(-1).rolling(FORWARD_DAYS).std().shift(-(FORWARD_DAYS - 1))
               * ANNUALISATION)

    # Lớp C: trailing, không phải feature của model.
    peak = close.rolling(DRAWDOWN_WINDOW).max()
    ddown = close / peak - 1.0

    return pd.DataFrame({"close": close, "vol_trail": vol_trail,
                         "vol_fwd": vol_fwd, "drawdown": ddown})


def auc_superiority(a: np.ndarray, b: np.ndarray) -> float:
    """P(giá trị lấy từ a > giá trị lấy từ b), hoà tính 0.5. Dựa trên hạng, không ngưỡng."""
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    allv = np.concatenate([a, b])
    ranks = pd.Series(allv).rank(method="average").to_numpy()
    r_a = ranks[:len(a)].sum()
    u_a = r_a - len(a) * (len(a) + 1) / 2.0
    return float(u_a / (len(a) * len(b)))


def evaluate(df: pd.DataFrame, labels: pd.Series, start, end, tag: str) -> dict:
    """Ba lớp trên một cửa sổ. Trả về dict, không tự phán quyết."""
    idx = df.index.intersection(labels.index)
    idx = idx[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]
    sub = df.loc[idx].copy()
    sub["label"] = labels.loc[idx]

    counts = sub["label"].value_counts().to_dict()
    out = {"tag": tag, "start": str(idx.min().date()) if len(idx) else None,
           "end": str(idx.max().date()) if len(idx) else None,
           "n_days": len(idx), "label_counts": counts}

    def _vals(col, lab):
        return sub.loc[sub["label"] == lab, col].dropna().to_numpy()

    # Lớp A — độc lập thật
    s_fwd = _vals("vol_fwd", "Stress")
    c_fwd = _vals("vol_fwd", "Calm")
    n_fwd = _vals("vol_fwd", "Normal")
    out["layer_a"] = {
        "what": "forward realised vol, day t+1..t+%d (model never sees this)" % FORWARD_DAYS,
        "independent": True,
        "n_stress": len(s_fwd), "n_calm": len(c_fwd), "n_normal": len(n_fwd),
        "auc_stress_over_calm": auc_superiority(s_fwd, c_fwd),
        "auc_normal_over_calm": auc_superiority(n_fwd, c_fwd),
        "median_stress": float(np.median(s_fwd)) if len(s_fwd) else None,
        "median_normal": float(np.median(n_fwd)) if len(n_fwd) else None,
        "median_calm": float(np.median(c_fwd)) if len(c_fwd) else None,
    }

    # Lớp B — KHÔNG độc lập (chính feature của model)
    s_tr = _vals("vol_trail", "Stress")
    c_tr = _vals("vol_trail", "Calm")
    n_tr = _vals("vol_trail", "Normal")
    meds = {"Calm": float(np.median(c_tr)) if len(c_tr) else None,
            "Normal": float(np.median(n_tr)) if len(n_tr) else None,
            "Stress": float(np.median(s_tr)) if len(s_tr) else None}
    ordered = (meds["Calm"] is not None and meds["Normal"] is not None
               and meds["Stress"] is not None
               and meds["Calm"] < meds["Normal"] < meds["Stress"])
    out["layer_b"] = {
        "what": "trailing %d-day realised vol — THIS IS THE MODEL OWN INPUT FEATURE" % VOL_WINDOW,
        "independent": False,
        "median_by_label": meds, "monotone_calm_lt_normal_lt_stress": bool(ordered),
    }

    # Lớp C — độc lập yếu
    s_dd = _vals("drawdown", "Stress")
    c_dd = _vals("drawdown", "Calm")
    out["layer_c"] = {
        "what": "drawdown from trailing %d-day peak (same prices, not a model feature)"
                % DRAWDOWN_WINDOW,
        "independent": "weak",
        "median_drawdown_stress": float(np.median(s_dd)) if len(s_dd) else None,
        "median_drawdown_calm": float(np.median(c_dd)) if len(c_dd) else None,
        "auc_calm_over_stress": auc_superiority(c_dd, s_dd),   # Calm nên ÍT âm hơn
    }
    return out


def _fmt_meds(d: dict) -> str:
    return str({k: (round(v, 4) if v is not None else None) for k, v in d.items()})


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="L11 dieu kien 2 — model dong cung co gan sai regime khong (read-only)")
    ap.add_argument("--spy-csv", default=str(ROOT / "spy_daily_live.csv"))
    ap.add_argument("--fit-end", default=REGIME["hmm_fit_end"])
    ap.add_argument("--train-end", default="2018-01-01")
    ap.add_argument("--n-components", type=int, default=REGIME["n_components"])
    ap.add_argument("--recent-months", type=int, default=12)
    ap.add_argument("--out", default=str(ROOT / "futures" / "regime_miss_report"))
    a = ap.parse_args()

    csv_path = Path(a.spy_csv)
    ck = Checks()

    print("=" * 74)
    print("L11 DIEU KIEN 2 — model dong cung co gan SAI regime khong?")
    print("=" * 74)

    if not csv_path.exists():
        print(f"\nFATAL: khong thay CSV {csv_path}")
        return 2

    close = benchmark_daily(str(csv_path))
    basis = {
        "spy_csv": str(csv_path), "spy_csv_sha256": _sha256(csv_path),
        "spy_csv_last_date": str(close.index.max().date()), "spy_csv_rows": int(len(close)),
        "hmm_fit_end": a.fit_end, "train_end": a.train_end,
        "n_components": a.n_components,
        "vol_window": VOL_WINDOW, "forward_days": FORWARD_DAYS,
        "drawdown_window": DRAWDOWN_WINDOW, "recent_months": a.recent_months,
        "anchor_auc_min": ANCHOR_AUC_MIN,
        "git_commit": _git_commit(), "python": sys.version.split()[0],
    }
    print("\nCO SO DO")
    for k, v in basis.items():
        print(f"  {k:<20} {v}")

    print(f"\nbuilding production labels (fit_end={a.fit_end}) ...")
    labels = pd.Series(label_regimes(close, a.train_end, a.n_components, a.fit_end))
    idx = pd.DatetimeIndex(labels.index)
    labels.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    labels = labels.sort_index()
    print(f"  {len(labels)} nhan  {labels.index.min().date()} .. {labels.index.max().date()}")

    df = build_indicators(close)

    # ── Self-check ───────────────────────────────────────────────────────────
    ck.add("SC1", "nhan khong rong", len(labels) > 0, f"n={len(labels)}")
    ck.add("SC2", "nhan chi thuoc Calm/Normal/Stress",
           set(labels.unique()) <= {"Calm", "Normal", "Stress"},
           f"{sorted(set(labels.unique()))}")

    tail_nan = bool(df["vol_fwd"].tail(FORWARD_DAYS).isna().all())
    mid_ok = bool(df["vol_fwd"].iloc[VOL_WINDOW + 5: -(FORWARD_DAYS + 5)].notna().all())
    ck.add("SC-NOLOOKAHEAD",
           f"vol_fwd NaN o {FORWARD_DAYS} ngay cuoi (khong the biet tuong lai), co gia tri o giua",
           tail_nan and mid_ok, f"tail_all_nan={tail_nan} mid_all_present={mid_ok}")

    print("\nSELF-CHECK (truoc neo)")
    for c in ck.items:
        print(c.line())
    if ck.failed:
        print("\nDUNG.")
        _write(a.out, basis, None, None, ck, None)
        return 1

    # ── NEO: detector phai dung tren giai doan IS ────────────────────────────
    anchor = evaluate(df, labels, IS_START, IS_END, f"IS {IS_START}..{IS_END}")
    auc_is = anchor["layer_a"]["auc_stress_over_calm"]
    print(f"\nNEO — giai doan IS ({anchor['start']} .. {anchor['end']}, {anchor['n_days']} ngay)")
    print(f"  phan bo nhan: {anchor['label_counts']}")
    print(f"  lop A  AUC(Stress>Calm) tren vol TIEN = {auc_is:.4f}   "
          f"(n_stress={anchor['layer_a']['n_stress']}, n_calm={anchor['layer_a']['n_calm']})")
    print(f"  lop B  median vol trailing theo nhan = "
          f"{_fmt_meds(anchor['layer_b']['median_by_label'])}")
    print(f"  lop C  median drawdown  Stress={anchor['layer_c']['median_drawdown_stress']} "
          f"Calm={anchor['layer_c']['median_drawdown_calm']}")

    ck.add("SC-ANCHOR-A",
           f"lop A tren IS >= {ANCHOR_AUC_MIN} (nhan co du bao duoc vol tien khong)",
           (auc_is == auc_is) and auc_is >= ANCHOR_AUC_MIN, f"AUC={auc_is:.4f}")
    ck.add("SC-ANCHOR-B", "lop B tren IS xep dung thu tu Calm < Normal < Stress",
           anchor["layer_b"]["monotone_calm_lt_normal_lt_stress"],
           _fmt_meds(anchor["layer_b"]["median_by_label"]))

    print("\nSELF-CHECK (neo)")
    for c in ck.items[-2:]:
        print(c.line())
    if ck.failed:
        print("\nDUNG — neo truot. Hoac detector sai, hoac tien de sai.")
        print("Khong phat verdict khi chua chung minh detector nhin thay duoc thu no phai nhin thay.")
        _write(a.out, basis, anchor, None, ck, None)
        return 1

    # ── Cua so gan day ───────────────────────────────────────────────────────
    last = labels.index.max()
    r_start = last - pd.DateOffset(months=a.recent_months)
    recent = evaluate(df, labels, r_start, last, f"recent {a.recent_months}m")
    la = recent["layer_a"]

    print(f"\nGAN DAY ({recent['start']} .. {recent['end']}, {recent['n_days']} ngay)")
    print(f"  phan bo nhan: {recent['label_counts']}")

    enough = la["n_calm"] >= MIN_CALM_DAYS and la["n_stress"] >= MIN_STRESS_DAYS
    ck.add("SC-SAMPLE",
           f"du mau de danh gia (>={MIN_CALM_DAYS} Calm, >={MIN_STRESS_DAYS} Stress)",
           enough, f"n_calm={la['n_calm']} n_stress={la['n_stress']}")

    if not enough:
        # "Khong du ngay Stress" mơ hồ giữa HAI khả năng trái ngược: thị trường không có
        # stress, hoặc model đã MÙ với stress. Cùng một output, hai kết luận đối lập — nên
        # phải tách bằng một thước KHÔNG phụ thuộc nhãn. Ngưỡng lấy từ IS chứ không bịa:
        # median drawdown của chính những ngày IS gọi là Stress.
        is_stress_dd = anchor["layer_c"]["median_drawdown_stress"]
        r_idx = df.index[(df.index >= pd.Timestamp(r_start)) & (df.index <= last)]
        r_dd = df.loc[r_idx, "drawdown"].dropna()
        worst = float(r_dd.min()) if len(r_dd) else float("nan")
        n_reached = int((r_dd <= is_stress_dd).sum()) if len(r_dd) else 0
        market_reached = n_reached > 0

        probe = {
            "is_stress_median_drawdown": is_stress_dd,
            "recent_worst_drawdown": worst,
            "recent_days_at_or_below_is_stress_level": n_reached,
            "market_reached_stress_territory": market_reached,
        }
        print(f"  sut sau nhat cua so nay: {worst:.2%}  |  nguong IS-Stress: {is_stress_dd:.2%}"
              f"  |  so ngay cham nguong: {n_reached}")

        if market_reached and la["n_stress"] == 0:
            verdict = {
                "verdict": "CO BANG CHUNG MODEL SAI",
                "reason": (f"thi truong CO cham vung stress ({n_reached} ngay sut <= "
                           f"{is_stress_dd:.2%}, sau nhat {worst:.2%}) nhung model KHONG gan "
                           f"mot ngay Stress nao. Do la miss that, khong phai thieu du lieu."),
                "probe": probe,
            }
        elif market_reached:
            verdict = {
                "verdict": "KHONG DANH GIA DUOC (thi truong chi vua cham)",
                "reason": (f"chi {la['n_stress']} ngay Stress — duoi muc {MIN_STRESS_DAYS} can "
                           f"de tinh AUC. Nhung thi truong CO cham vung stress ({n_reached} ngay "
                           f"sut <= {is_stress_dd:.2%}) va model CO bat, nen day khong phai dau "
                           f"hieu model mu. Chua du mau de do MUC DO, du de loai kha nang mu."),
                "probe": probe,
            }
        else:
            verdict = {
                "verdict": "KHONG DANH GIA DUOC (thi truong yen)",
                "reason": (f"chi {la['n_stress']} ngay Stress, va thi truong khong he cham vung "
                           f"stress: sut sau nhat {worst:.2%} nong hon nguong IS-Stress "
                           f"{is_stress_dd:.2%}. Khong the kiem viec nhan dien Stress khi khong "
                           f"co Stress. KHONG phai tin hieu tot cung khong phai tin hieu xau — "
                           f"la khong co du lieu. Trung trang thai 'STRESS sleeve "
                           f"OOS-pending-bear' o OOS_VALIDATION_LOG.md."),
                "probe": probe,
            }
        print(f"\n{'=' * 74}\nVERDICT: {verdict['verdict']}\n{'=' * 74}")
        print("  " + verdict["reason"])
    else:
        auc_r = la["auc_stress_over_calm"]
        print(f"  lop A  AUC(Stress>Calm) = {auc_r:.4f}   (IS: {auc_is:.4f}, "
              f"chenh {auc_r - auc_is:+.4f})")
        print(f"  lop B  median vol trailing = "
              f"{_fmt_meds(recent['layer_b']['median_by_label'])}")

        inverted = not recent["layer_b"]["monotone_calm_lt_normal_lt_stress"]
        no_info = auc_r <= 0.5
        if inverted or no_info:
            verdict = {
                "verdict": "CO BANG CHUNG MODEL SAI",
                "reason": ("thu tu nhan bi DAO tren vol trailing" if inverted else "")
                          + ("; " if inverted and no_info else "")
                          + (f"AUC tien {auc_r:.4f} <= 0.5 — nhan het mang thong tin"
                             if no_info else ""),
            }
        else:
            verdict = {
                "verdict": "KHONG CO BANG CHUNG MODEL SAI",
                "reason": (f"thu tu nhan giu nguyen va AUC tien {auc_r:.4f} > 0.5. "
                           f"Chenh so voi IS ({auc_r - auc_is:+.4f}) duoc BAO CAO chu khong "
                           f"duoc phan quyet: dat mot nguong suy giam can block bootstrap tren "
                           f"chuoi tu tuong quan, chua lam. So chenh nay voi cac lan chay truoc."),
            }
        print(f"\n{'=' * 74}\nVERDICT: {verdict['verdict']}\n{'=' * 74}")
        print("  " + verdict["reason"])

    print("\n  Gioi han phai nhac lai: lop B dung CHINH feature cua model (vol 5 ngay trailing)")
    print("  nen no kiem tinh NHAT QUAN, khong kiem tinh DUNG. Chi lop A la ngoai mau that su.")

    print("\nSELF-CHECK (cuoi)")
    print(ck.items[-1].line())

    _write(a.out, basis, anchor, recent, ck, verdict)
    return 0


def _write(out_base, basis, anchor, recent, ck, verdict) -> None:
    payload = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "basis": basis, "anchor_is": anchor, "recent": recent, "verdict": verdict,
        "selfchecks": [{"id": c.id, "desc": c.desc, "passed": c.passed,
                        "detail": c.detail} for c in ck.items],
    }
    jp = Path(str(out_base) + ".json")
    jp.parent.mkdir(parents=True, exist_ok=True)
    jp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    lines = ["L11 DIEU KIEN 2 — model co gan sai regime khong",
             f"measured_at  {payload['measured_at']}", "",
             "CO SO DO", *[f"  {k:<20} {v}" for k, v in basis.items()], "",
             "SELF-CHECK", *[c.line() for c in ck.items], ""]
    for name, blk in (("NEO (IS)", anchor), ("GAN DAY", recent)):
        if blk:
            lines += [f"{name}  {blk['start']} .. {blk['end']}  ({blk['n_days']} ngay)",
                      f"  nhan: {blk['label_counts']}",
                      f"  lop A (doc lap)       AUC(Stress>Calm) = "
                      f"{blk['layer_a']['auc_stress_over_calm']:.4f}  "
                      f"n_stress={blk['layer_a']['n_stress']} n_calm={blk['layer_a']['n_calm']}",
                      f"  lop B (KHONG doc lap) median vol trailing = "
                      f"{_fmt_meds(blk['layer_b']['median_by_label'])}  "
                      f"monotone={blk['layer_b']['monotone_calm_lt_normal_lt_stress']}",
                      f"  lop C (doc lap yeu)   median drawdown Stress="
                      f"{blk['layer_c']['median_drawdown_stress']} "
                      f"Calm={blk['layer_c']['median_drawdown_calm']}", ""]
    if verdict:
        lines += [f"VERDICT  {verdict['verdict']}", f"  {verdict['reason']}", ""]
    Path(str(out_base) + ".txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nDa ghi:\n  {jp}\n  {Path(str(out_base) + '.txt')}")


if __name__ == "__main__":
    raise SystemExit(main())
