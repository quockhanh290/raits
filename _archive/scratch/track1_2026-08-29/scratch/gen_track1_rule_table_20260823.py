"""Render the Part C rule mapping FROM the registry into the design note.

Replaces everything between the two markers in
scratch/track1_explainability_design_20260823.md. Run it again after any registry change:
a rule table typed by hand beside the code is a description that will drift from it.
"""
import sys
from pathlib import Path
sys.path.insert(0, r"d:\raits")
from global_index import track1_explain as tx

GROUPS = [("roska4_swing", "1. Normal-R4  (sleeve `roska4_swing` — MES, MNQ, MYM, M2K)"),
          ("global_nkd",   "2. NKD / MNKD  (sleeve `global_nkd` — MNKD)"),
          ("roska4_calm",  "3. Calm A  (sleeve `roska4_calm` — MES, MNQ)"),
          ("roska4_stress","4. Stress-MNQ  (sleeve `roska4_stress` — MNQ)"),
          ("shared",       "5. Shared gates (every sleeve)")]

lines = []
for scope, title in GROUPS:
    rules = [r for r in tx.RULES.values() if r.scope == scope]
    assert rules, f"no rules in scope {scope}"      # an empty group would render silently
    lines.append(f"### {title}\n")
    for r in sorted(rules, key=lambda x: x.id):
        ev = "; ".join(f"{e.kind}: `{e.path}`" + (f" — {e.note}" if e.note else "")
                       for e in r.evidence)
        lines.append(f"**`{r.id}`**  \n"
                     f"{r.description}\n\n"
                     f"- lives in: `{r.code_ref.file}` → `{r.code_ref.symbol}`\n"
                     f"- an explanation citing it must carry: "
                     f"{', '.join('`'+f+'`' for f in r.features)}\n"
                     f"- proved by: {ev}\n")
    lines.append("")

table = "\n".join(lines)
doc = Path(r"d:\raits\scratch\track1_explainability_design_20260823.md")
text = doc.read_text(encoding="utf-8")
lo, hi = "<!-- RULES:BEGIN -->", "<!-- RULES:END -->"
a, b = text.index(lo) + len(lo), text.index(hi)
doc.write_text(text[:a] + "\n\n" + table + "\n" + text[b:], encoding="utf-8")
print(f"rendered {len(tx.RULES)} rules into {doc.name}")
