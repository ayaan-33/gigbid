"""Loads agent/config.yaml (with ${ENV:default} expansion) and environment settings."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.getenv("GIGBID_CONFIG", ROOT / "agent" / "config.yaml"))

load_dotenv(ROOT / ".env", override=False)

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return os.getenv(m.group(1), m.group(2) or "")

        expanded = _ENV_PATTERN.sub(repl, value)
        return expanded
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return _expand(yaml.safe_load(fh))


def reload_config() -> dict[str, Any]:
    config.cache_clear()
    return config()


def cfg(path: str, default: Any = None) -> Any:
    """Dotted lookup: cfg("budgets.max_revisions")."""
    node: Any = config()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def database_url() -> str:
    return env("DATABASE_URL", "postgresql://gigbid:gigbid@localhost:5432/gigbid") or ""
