"""Data card guarantees: synthetic labelling, corpus sizes, gold labels resolvable, hidden set isolated."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PERSONAS = ["ai_ml_engineer", "fullstack_dev", "data_analyst"]
pytestmark = pytest.mark.skipif(not (ROOT / "data/personas/ai_ml_engineer/manifest.json").exists(),
                                reason="run `make seed` first")


@pytest.mark.parametrize("pid", PERSONAS)
def test_persona_corpus_shape(pid):
    base = ROOT / "data/personas" / pid
    man = json.loads((base / "manifest.json").read_text())
    assert man["synthetic"] is True
    types = [m["type"] for m in man["items"]]
    assert 15 <= types.count("case_study") <= 25
    assert types.count("proposal") >= 140
    assert (base / "cv.pdf").exists() and types.count("repo") >= 5
    outcomes = {json.loads(line)["outcome"] for line in (base / "proposals.jsonl").read_text().splitlines()}
    assert outcomes == {"won", "replied", "ignored"}


@pytest.mark.parametrize("pid", PERSONAS)
def test_gold_evidence_ids_exist(pid):
    ids = {m["id"] for m in json.loads((ROOT / "data/personas" / pid / "manifest.json").read_text())["items"]}
    gold = [json.loads(x) for x in (ROOT / f"evals/datasets/dev_{pid}.jsonl").read_text().splitlines()]
    assert len(gold) == 200
    for g in gold:
        assert set(g["relevant_evidence"]) <= ids
        if g["action"] == "bid":
            assert g["relevant_evidence"] and g["fair_price"]["low"] <= g["fair_price"]["high"]
        assert not (g["is_scam"] and g["action"] == "bid")


def test_seed_jobs_mark_synthetic_fields_and_real_source():
    for line in (ROOT / "data/gigsim_seed/jobs.jsonl").read_text().splitlines()[:200]:
        j = json.loads(line)
        assert j["real_source"].startswith("kaggle_")
        assert isinstance(j["synthetic_fields"], list)
        assert "gold" not in j


def test_hidden_set_is_git_ignored():
    ignore = (ROOT / ".gitignore").read_text()
    assert "evals/datasets/hidden/" in ignore and "data/gigsim_seed_hidden/" in ignore
