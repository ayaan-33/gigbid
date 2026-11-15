"""CI rule: every number in README.md results sections traces to a committed file in evals/results/.

Numbers inside the README's results tables (between `<!-- results:start -->` and
`<!-- results:end -->`) must appear verbatim in at least one evals/results/*.json|csv file.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NUM = re.compile(r"(?<![\w.])(\d+\.\d+|\d{2,})(?![\w.])")


def main() -> int:
    readme = (ROOT / "README.md").read_text()
    blocks = re.findall(r"<!-- results:start -->(.*?)<!-- results:end -->", readme, re.S)
    corpus = "\n".join(p.read_text(errors="ignore") for p in (ROOT / "evals" / "results").glob("*")
                       if p.suffix in (".json", ".csv", ".md"))
    missing = []
    for b in blocks:
        for n in NUM.findall(b):
            variants = {n, n.rstrip("0").rstrip(".") if "." in n else n}
            if not any(v in corpus for v in variants):
                missing.append(n)
    if missing:
        print("numbers in README results without a source in evals/results/:", sorted(set(missing)))
        return 1
    print(f"README numbers traced: {sum(len(NUM.findall(b)) for b in blocks)} values in {len(blocks)} results block(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
