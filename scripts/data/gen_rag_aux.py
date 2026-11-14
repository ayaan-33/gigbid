"""Generate V6 contextual lines (per chunk) and V7 HyDE paragraphs (per job) with an open model.

Runs on the `open` profile (Groq free tier, paced by the client-side token limiter);
free-tier limits mean V7 uses a 30-job-per-persona subset and V6 one persona (documented). Results are cached in
data/derived/context_lines_<persona>.json and data/derived/hyde_texts.json (resumable).

  uv run python -m scripts.data.gen_rag_aux --what hyde --per-persona 30
  uv run python -m scripts.data.gen_rag_aux --what context --personas ai_ml_engineer
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DERIVED = ROOT / "data" / "derived"
PERSONAS = ["ai_ml_engineer", "fullstack_dev", "data_analyst"]


def _clean(text: str) -> str:
    text = text.split("</think>")[-1].strip().strip('"')
    return " ".join(text.split())[:400]


async def contexts(persona: str, conc: int) -> None:
    from agent.llm import complete
    from agent.prompts import load_prompt
    from rag.ingest.loaders import load_persona

    out_path = DERIVED / f"context_lines_{persona}.json"
    done = json.loads(out_path.read_text()) if out_path.exists() else {}
    chunks = load_persona(persona)
    by_item: dict[str, list] = {}
    for c in chunks:
        by_item.setdefault(c.evidence_id, []).append(c)
    p = load_prompt("contextual_chunk")
    sem = asyncio.Semaphore(conc)

    async def one(c):
        if c.chunk_id in done:
            return
        doc = " ".join(x.text for x in by_item[c.evidence_id])[:700]
        async with sem:
            try:
                t = await complete("contextual", p.text, f"DOCUMENT ({c.type}, {c.title}):\n{doc[:450]}\n\nCHUNK:\n{c.text[:450]}",
                                   temperature=0.1, max_tokens=120)
                done[c.chunk_id] = _clean(t)
            except Exception as e:  # noqa: BLE001
                print("skip", c.chunk_id, e)
        if len(done) % 25 == 0:
            out_path.write_text(json.dumps(done, indent=0))

    await asyncio.gather(*(one(c) for c in chunks))
    out_path.write_text(json.dumps(done, indent=0))
    print(persona, "context lines:", len(done), "/", len(chunks))


async def hyde(conc: int, per_persona: int | None = None) -> None:
    from agent.llm import complete
    from agent.prompts import load_prompt

    out_path = DERIVED / "hyde_texts.json"
    done = json.loads(out_path.read_text()) if out_path.exists() else {}
    jobs = {json.loads(x)["id"]: json.loads(x) for x in (ROOT / "data/gigsim_seed/jobs.jsonl").read_text().splitlines()}
    want = []
    for pid in PERSONAS:
        bids = [json.loads(x)["job_id"] for x in (ROOT / f"evals/datasets/dev_{pid}.jsonl").read_text().splitlines()
                if json.loads(x)["action"] == "bid"]
        want += bids[:per_persona] if per_persona else bids
    p = load_prompt("hyde")
    sem = asyncio.Semaphore(conc)

    async def one(jid):
        if jid in done:
            return
        j = jobs[jid]
        async with sem:
            try:
                t = await complete("data_generator", p.text, f"JOB: {j['title']}\n{j['description'][:1500]}",
                                   temperature=0.3, max_tokens=220)
                done[jid] = _clean(t)
            except Exception as e:  # noqa: BLE001
                print("skip", jid, e)
        if len(done) % 20 == 0:
            out_path.write_text(json.dumps(done, indent=0))

    await asyncio.gather(*(one(j) for j in want))
    out_path.write_text(json.dumps(done, indent=0))
    print("hyde:", len(done), "/", len(want))


async def main(what: list[str], conc: int, personas: list[str], per_persona: int | None) -> None:
    os.environ.setdefault("MODEL_PROFILE", "open")
    os.environ.setdefault("LLM_CACHE", "1")
    if "hyde" in what:
        await hyde(conc, per_persona)
    if "context" in what:
        for p in personas:
            await contexts(p, conc)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", nargs="+", default=["context", "hyde"])
    ap.add_argument("--conc", type=int, default=2)
    ap.add_argument("--personas", nargs="+", default=PERSONAS)
    ap.add_argument("--per-persona", type=int, default=None, help="HyDE: only the first N bid jobs per persona")
    a = ap.parse_args()
    asyncio.run(main(a.what, a.conc, a.personas, a.per_persona))
