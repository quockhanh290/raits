"""Mot so do khong doc duoc thi khong duoc bien thanh 0 roi lot qua nguong cua chinh no.

Day khong phai mot loi, day la mot hinh dang. Dem 2026-08-17 no bi bat o bon cho khac
nhau trong cung mot phien — han muc so sanh, doi soat tien, so vi the duoc bao ve, tran
cua sao ke — va lan nao cung cung mot co che: `Number(x || 0)`. `null` thanh `0`, ma `0`
thi nam trong moi dung sai va duoi moi tran, nen mot chi so KHONG DOC DUOC hien ra nhu
mot chi so DA DAT.

Bang chung ro nhat rang day la sot chu khong phai chu y nam gon trong mot ham. Truoc
ban va nay, `fillMetricCards` viet:

    fillsOk   = (m.fills ?? 0) >= (spec.min_fills ?? Infinity)          <- fail-CLOSED
    partialOk = Number(m.partial_rate || 0) <= Number(spec.max_partial_rate ?? 0)
    failedOk  = (m.failed_or_cancelled ?? 0) <= (spec.max_failed_or_cancelled ?? 0)
    scaleOk   = Number(m.max_contracts_observed || 0) <= Number(m.max_contracts_tested || 0)

Dong dau dung `Infinity` — nguoi viet biet cai bay. Ba dong sau, cung ham, cung hinh
dang, thieu ca hai ve thi ra PASS.

Va - luat nay chi bat DUNG mot hinh dang: mot phep do dem so sanh voi HAN MUC cua no.
No khong dung toi cho to mau P&L (`Number(pnl || 0) > 0`), noi ma thieu so ra trung tinh
la hop ly. Luat hep thi song lau; luat rong thi bi tat.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "global_index" / "dash"

# Ve trai: mot gia tri duoc ep ve 0 khi vang mat.
_COERCED = r"(?:Number\([^()]*\|\|\s*0\s*\)|\([^()]*\?\?\s*0\s*\))"
# Ve phai: mot HAN MUC. Day la thu bien luat nay tu "cam || 0" thanh "cam so mot phep
# do voi han muc cua no bang cach gia vo rang thieu la 0".
_LIMIT = r"[^;\n]*(?:spec\.|max_|min_|required_|_tested|_target|target_)"
_PATTERN = re.compile(rf"{_COERCED}\s*(?:<=|>=|<|>)\s*{_LIMIT}")


def _rule_hit(line: str) -> bool:
    """Khop hinh dang, TRU khi ve han muc da tu chui minh lai bang Infinity.

    Ban dau luat khong co ngoai le nay va no gan co ngay chinh hai dong lam DUNG:

        fillsOk  = (m.fills ?? 0) >= (spec.min_fills ?? Infinity)
        sampleOk = Number(m.rejections || 0) >= Number(m.required_records ?? Infinity)

    Thieu spec thi han muc thanh vo cuc, phep so ra False, cong fail-CLOSED. Do la cach
    chua dung — va mot luat gan co ca cach chua dung se bi tat chu khong duoc tuan thu.
    `Infinity` chinh la dau hieu nguoi viet da nghi den truong hop vang mat.

    Soi tu diem khop den het dong chu khong chi trong doan khop: `[^;\\n]*` la tham nen
    no dung lai o tu khoa han muc cuoi cung tim duoc, tuc truoc `Infinity`, va ban dau
    ngoai le nay khong bao gio chay. Bat duoc vi phep tu kiem duoi day do nguoc lai.
    """
    m = _PATTERN.search(line)
    return bool(m) and "Infinity" not in line[m.start():]

_COMMENT = re.compile(r"^\s*(//|\*|/\*)")


def _offenders() -> list[str]:
    found = []
    for path in sorted(DASH.rglob("*.js")):
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _COMMENT.match(line):
                continue          # chu thich trich lai ma cu khong phai ma song
            if _rule_hit(line):
                found.append(f"{path.relative_to(ROOT)}:{n}  {line.strip()[:120]}")
    return found


def test_the_rule_can_actually_see_the_shape_it_bans():
    """Tu kiem truoc khi khang dinh.

    Mot luat quet ma khong khop duoc gi la mot phep kiem xanh vinh vien. Nap lai chinh
    bon dong da tung co that trong repo va bat buoc luat phai bat ba dong hong, va bo
    qua dong fail-closed cung nhu dong to mau.
    """
    caught = [_rule_hit(s) for s in [
        "const partialOk = Number(m.partial_rate || 0) <= Number(spec.max_partial_rate ?? 0);",
        "const failedOk = (m.failed_or_cancelled ?? 0) <= (spec.max_failed_or_cancelled ?? 0);",
        "const scaleOk = Number(m.max_contracts_observed || 0) <= Number(m.max_contracts_tested || 0);",
    ]]
    assert all(caught), f"luat bo sot chinh cac dong no sinh ra de bat: {caught}"

    ignored = [
        # Hai dong fail-closed co that trong repo: thieu spec -> han muc vo cuc -> False.
        "const fillsOk = (m.fills ?? 0) >= (spec.min_fills ?? Infinity);",
        "const sampleOk = Number(m.rejections || 0) >= Number(m.required_records ?? Infinity);",
        "const cls = Number(exit.pnl || 0) > 0 ? 'ok' : 'bad';",
        "if (Math.abs(Number(row.delta || 0)) > 0.005) return true;",
    ]
    for line in ignored:
        assert not _rule_hit(line), (
            f"luat bat ca cho vo hai — no se bi tat thay vi duoc tuan thu: {line}")


def test_no_measurement_is_compared_against_its_limit_by_pretending_missing_is_zero():
    offenders = _offenders()
    assert not offenders, (
        "mot so do khong doc duoc dang duoc coi la 0 roi so voi han muc cua chinh no, "
        "tuc la thieu du lieu se hien ra nhu da dat:\n  " + "\n  ".join(offenders)
        + "\n\nDung num()/withinLimit() trong paper.js: chung tra ve null khi mot ve "
          "vang mat, va limitRead() bien null thanh CHECK thay vi PASS.")
