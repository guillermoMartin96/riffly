"""Documentation consistency checks (run in CI with the backend venv).

1. Repository paths quoted in Markdown (`backend/...`, `docs/...`, ...) and relative links exist.
2. Gate thresholds and dataset minimums written in the protocol and the manual-testing guide equal
   the constants the gate code enforces (bench/jamrecall_bench/real.py).
3. The decision register lists every decision request with the same status.

Usage: backend/.venv/bin/python scripts/check_docs.py   (exit 1 on any problem)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench"))

from jamrecall_bench import real  # noqa: E402

DOCS = [ROOT / "README.md", ROOT / "bench" / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
PATH_PREFIXES = ("backend/", "frontend/", "bench/", "docs/", "scripts/", ".github/")
# Generated, git-ignored or placeholder locations that legitimately do not exist in a checkout.
SKIP = ("var/", ".cache", ".venv", "node_modules", "test-results", "playwright-report",
        "bench/results/real-", "bench/real/references/<")
problems: list[str] = []


def check_paths() -> None:
    for doc in DOCS:
        text = doc.read_text()
        for token in re.findall(r"`([^`\s]+)`", text):
            t = token.rstrip(".,:;)").removeprefix("./")
            if not t.startswith(PATH_PREFIXES) or any(s in t for s in SKIP):
                continue
            if any(c in t for c in "<>*{}…|") or t.endswith("/<"):
                continue
            t = t.split("::")[0].split("#")[0]
            if not (ROOT / t).exists():
                problems.append(f"{doc.relative_to(ROOT)}: path `{token}` does not exist")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not (doc.parent / target.split("#")[0]).resolve().exists():
                problems.append(f"{doc.relative_to(ROOT)}: link ({target}) is broken")


def check_numbers() -> None:
    protocol = (ROOT / "docs/research/real-recording-validation-protocol.md").read_text()
    guide = (ROOT / "docs/testing/manual-testing-guide.md").read_text()
    expect = {
        "aggregate onset F1": f"Basic Pitch onset F1 ≥ {real.GATE_F1:.2f}",
        "per-condition onset F1": f"F1 ≥ {real.POOR_F1:.2f}",
        "per-condition pitch": f"≥ {round(real.POOR_PITCH * 100)}% of onset-matched notes",
    }
    for what, phrase in expect.items():
        if phrase not in protocol:
            problems.append(f"protocol: {what} should read '{phrase}' (gate code value)")
    for cond, (dev, hold, notes) in real.MINIMUMS.items():
        if cond in real.GATING:
            row = f"{dev} / {hold} recordings, ≥ {notes} holdout notes"
        else:
            row = f"{dev} / {hold} recordings"
        line = next((ln for ln in protocol.splitlines() if ln.startswith(f"| {cond}.")), "")
        if row not in line:
            problems.append(f"protocol: condition {cond} minimum should be '{row}'")
        gl = next((ln for ln in guide.splitlines() if ln.startswith(f"| {cond} |")), "")
        cells = [c.strip() for c in gl.split("|")[1:-1]]
        want_notes = f"≥ {notes}" if cond in real.GATING else "–"
        if cells[2:5] != [f"≥ {dev}", f"≥ {hold}", want_notes]:
            problems.append(f"guide §7.1: condition {cond} row {cells[2:5]} != gate minimums")
    total = sum(d + h for c, (d, h, _) in real.MINIMUMS.items() if c in real.GATING)
    for name, text in (("protocol", protocol), ("guide", guide)):
        if f"{total} " not in text or (f"**{total} " not in text and f"**{total}" not in text):
            problems.append(f"{name}: minimum number of gating takes should be stated as {total}")


def check_register() -> None:
    register = (ROOT / "docs/decisions/README.md").read_text()
    for dr in sorted((ROOT / "docs/decisions/requests").glob("DR-*.md")):
        dr_id = dr.name[:7]
        status = next(ln for ln in dr.read_text().splitlines() if ln.startswith("Status:"))
        row = next((ln for ln in register.splitlines() if f"[{dr_id}]" in ln), None)
        if row is None:
            problems.append(f"decision register: {dr_id} missing")
            continue
        for word in ("Approved", "Open", "Proposed", "Rejected"):
            if (word in status) != (word in row):
                problems.append(f"decision register: {dr_id} status differs ({word}?)")


check_paths()
check_numbers()
check_register()
if problems:
    print("Documentation consistency problems:")
    for p in problems:
        print(" -", p)
    sys.exit(1)
print(f"Documentation consistent ({len(DOCS)} files checked).")
