"""CI rule: nothing under gigsim/ changes after it was frozen. Re-freeze deliberately with --freeze."""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "gigsim" / "FROZEN.sha256"


def digest() -> dict[str, str]:
    out = {}
    for f in sorted((ROOT / "gigsim").rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f != MANIFEST:
            out[str(f.relative_to(ROOT))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def main() -> int:
    cur = digest()
    if "--freeze" in sys.argv:
        MANIFEST.write_text("".join(f"{h}  {p}\n" for p, h in cur.items()))
        print(f"froze {len(cur)} files")
        return 0
    want = dict(reversed(line.split("  ", 1)) for line in MANIFEST.read_text().splitlines() if line.strip())
    want = {p.strip(): h for p, h in want.items()}
    changed = sorted(p for p in set(cur) | set(want) if cur.get(p) != want.get(p))
    if changed:
        print("gigsim/ was modified after freezing:", *changed, sep="\n  ")
        return 1
    print(f"gigsim frozen: {len(cur)} files unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
