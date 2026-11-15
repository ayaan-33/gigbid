"""CI rule: every prompt lives in agent/prompts/ (versioned .md files), no inline prompts.

Fails if (1) a prompt file lacks its `name`/`version` header, or (2) any call to the LLM layer
(`complete(...)` / `structured(...)`) passes a long string literal as the system prompt.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN = ["agent", "rag", "apps", "worker", "evals", "mcp_servers", "scripts"]
ALLOW = {"agent/testing.py"}  # deterministic test double, not a prompt


def main() -> int:
    problems = []
    for f in sorted((ROOT / "agent" / "prompts").glob("*.md")):
        head = f.read_text().split("---")
        if len(head) < 3 or "name:" not in head[1] or "version:" not in head[1]:
            problems.append(f"{f.relative_to(ROOT)}: missing name/version header")
    for d in SCAN:
        for f in (ROOT / d).rglob("*.py"):
            rel = str(f.relative_to(ROOT))
            if rel in ALLOW or "/tests/" in rel:
                continue
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                    if name in ("complete", "structured") and len(node.args) >= 2:
                        sys_arg = node.args[1]
                        if isinstance(sys_arg, ast.Constant) and isinstance(sys_arg.value, str) and len(sys_arg.value) > 60:
                            problems.append(f"{rel}:{node.lineno}: inline system prompt; move it to agent/prompts/")
    if problems:
        print("\n".join(problems))
        return 1
    n = len(list((ROOT / "agent" / "prompts").glob("*.md")))
    print(f"prompts OK: {n} versioned prompt files, no inline prompts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
