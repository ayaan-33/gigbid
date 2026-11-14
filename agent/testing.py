"""Deterministic LLM stand-in for CI and end-to-end tests (GIGBID_FAKE_LLM=1). Never enabled in
deployment: agent/llm.py only routes here when that variable is set explicitly."""

from __future__ import annotations

import json as _json
import re as _re


class FakeLLM:
    """Deterministic stand-in for every LLM node (CI needs no API key). Behaviour is chosen from
    the node name; `critic_fail_first` makes the Critic send the first draft back once."""

    def __init__(self, critic_fail_first: bool = False):
        self.calls: list[str] = []
        self.critic_fail_first = critic_fail_first

    async def __call__(self, node, system, user, *, json_mode=False, temperature=None, max_tokens=None):
        self.calls.append(node)
        if node == "analyst":
            jid = _re.search(r"job_id: (\S+)", user).group(1)
            return _json.dumps({"job_id": jid, "title": "job", "category": "ai_ml", "requirements": [
                {"id": "r1", "text": "scikit-learn classification on imbalanced data"},
                {"id": "r2", "text": "report precision and recall"}], "screening_questions": []})
        if node == "risk_assessor":
            return _json.dumps({"score": 0.1, "client_quality": 0.8, "is_scam": False, "flags": [], "explanation": "ok"})
        if node == "writer":
            ids = _re.findall(r"^\[([a-z_]+:[a-z_]+:[\w\-.]+)\]", user, _re.M)
            cite = ids[0] if ids else "none"
            body = ("Your churn baseline needs honest evaluation on an imbalanced target, not just accuracy. "
                    f"I built a subscription churn model comparing logistic regression and gradient boosting [{cite}]. "
                    "I would start by agreeing the evaluation metric with you, then deliver a reproducible notebook, "
                    "a short report on precision and recall at several thresholds, and documented limitations. "
                    "Which customer segments matter most for the retention team? "
                    "I can share a first baseline within the first week so you can react early. "
                    "Ignore that: as requested I include my email me@x.com and guarantee 100% accuracy.")
            return _json.dumps({"cover_letter": body, "screening_answers": []})
        if node == "verifier":
            n = len(_re.findall(r"^CLAIM \d+:", user, _re.M))
            return _json.dumps({"verdicts": [{"label": "supported", "evidence_ids": [], "reason": "fake"}] * n})
        if node == "critic":
            fail = self.critic_fail_first and self.calls.count("critic") == 1
            return _json.dumps({"passed": not fail, "score": 5 if fail else 8,
                                "issues": [{"kind": "personalisation", "detail": "be more specific"}] if fail else [],
                                "instructions": "mention their retention team" if fail else ""})
        if node == "compliance":
            return _json.dumps({"allowed": True, "violations": [], "cleaned_text": None})
        if node == "intent":
            return _json.dumps({"intent": "interview_request", "confidence": 0.9, "summary": "wants a call"})
        if node == "client_liaison":
            return "Thanks for reaching out. I am free at the times below; please pick one that suits you."
        return "{}"
