"""Versioned prompt loader. Every prompt lives in agent/prompts/<name>.md (CI-enforced).

File format:
    ---
    name: writer
    version: 3
    ---
    <system prompt text, may contain {placeholders}>
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

PROMPT_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str

    def render(self, **kwargs: object) -> str:
        out = self.text
        for k, v in kwargs.items():
            out = out.replace("{" + k + "}", str(v))
        return out

    @property
    def tag(self) -> str:
        return f"{self.name}@v{self.version}"


@cache
def load_prompt(name: str) -> Prompt:
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"prompt {name} is missing its version header")
    _, header, body = raw.split("---", 2)
    meta = yaml.safe_load(header)
    return Prompt(name=meta["name"], version=int(meta["version"]), text=body.strip())


def all_prompts() -> list[Prompt]:
    return [load_prompt(p.stem) for p in sorted(PROMPT_DIR.glob("*.md")) if p.stem != "README"]
