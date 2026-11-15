"""Deploy GigBid to a free Hugging Face Docker Space (no card needed).

Uploads ONLY git-tracked files (so .env, raw data and the hidden test set never leave the machine),
puts infra/hf/Dockerfile at the Space root, and copies the needed keys from .env into the Space as
encrypted secrets. Nothing secret is printed.

    uv run --with huggingface_hub python -m scripts.deploy.hf_space [--name gigbid]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]
SECRETS = ["APP_SECRET_KEY", "TOKEN_ENCRYPTION_KEY", "REVIEWER_EMAIL", "REVIEWER_PASSWORD", "MCP_BEARER_TOKEN",
           "GIGSIM_API_TOKEN", "GIGSIM_ADMIN_TOKEN", "GROQ_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
           "LANGFUSE_HOST", "GITHUB_PERSONAL_ACCESS_TOKEN", "UPWORK_OAUTH_CLIENT_ID", "UPWORK_OAUTH_CLIENT_SECRET",
           "UPWORK_MCP_URL"]
SKIP = ("data/raw/", "evals/datasets/hidden/", "data/gigsim_seed_hidden/", "apps/web/tests/", "docs/images/")

FRONT = """---
title: GigBid
emoji: 🧭
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Multi-agent freelancer copilot (LangGraph + MCP + RAG)
---

# GigBid (live demo)

Source code, docs and evaluation: see the GitHub repository linked in the course submission.
Sign in with the reviewer account shared privately. First start takes a few minutes while the
portfolio index is built.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="gigbid")
    a = ap.parse_args()
    env = dotenv_values(ROOT / ".env")
    token = env.get("HF_TOKEN") or os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN missing from .env")
    api = HfApi(token=token)
    user = api.whoami()["name"]
    repo = f"{user}/{a.name}"
    api.create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)

    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        n = 0
        for f in filter(None, files):
            if f.startswith(SKIP) or f == ".env" or f.endswith("/.env") or not (ROOT / f).is_file():
                continue
            (t / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, t / f)
            n += 1
        shutil.copy2(ROOT / "infra/hf/Dockerfile", t / "Dockerfile")
        shutil.copy2(ROOT / "infra/hf/Dockerfile.dockerignore", t / ".dockerignore")
        (t / "SPACE_README.md").write_text(FRONT)
        # HF reads the Space card from README.md; the app image copies README.md too (pyproject), so keep both.
        (t / "README.md").write_text(FRONT + "\n\n" + (ROOT / "README.md").read_text())
        for k in SECRETS:
            v = env.get(k)
            if v:
                api.add_space_secret(repo, k, v)
        api.add_space_variable(repo, "MODEL_PROFILE", env.get("MODEL_PROFILE") or "open")
        api.upload_folder(repo_id=repo, repo_type="space", folder_path=tmp, commit_message="Deploy GigBid")
    host = f"{user}-{a.name}".lower().replace("_", "-") + ".hf.space"
    print(f"uploaded {n} files to https://huggingface.co/spaces/{repo}")
    print(f"app URL (after the build, ~10-15 min): https://{host}")


if __name__ == "__main__":
    main()
