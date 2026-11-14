"""Proposal Writer -> claim verification -> Critic (<= 2 revisions) -> Compliance Guard."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agent.guardrails import spotlight
from agent.handoffs import (
    Citation,
    ComplianceVerdict,
    ComplianceViolation,
    Critique,
    ProposalDraft,
    ScreeningAnswer,
)
from agent.llm import structured
from agent.nodes.base import node
from agent.nodes.common import profile, tools
from agent.prompts import load_prompt
from agent.settings import cfg

CITE = re.compile(r"\[([a-z_]+:[a-z_]+:[\w\-.]+)\]")

STRATEGIES = {
    "evidence_first": "Strategy: after the one-line problem restatement, lead with the single most relevant past "
                      "project and its measured result, then the plan.",
    "question_led": "Strategy: open by restating the problem, then ask one sharp clarifying question that shows "
                    "you understand the hard part, then give the evidence and plan.",
    "default": "",
}


class WriterOut(BaseModel):
    cover_letter: str = Field(description="the proposal text with [evidence_id] citations")
    screening_answers: list[ScreeningAnswer] = Field(default_factory=list)


def _citations(text: str) -> list[Citation]:
    out = []
    for i, s in enumerate(re.split(r"(?<=[.!?])\s+", text)):
        ids = CITE.findall(s)
        if ids:
            out.append(Citation(sentence_index=i, evidence_ids=ids))
    return out


async def _evidence_pack(state: dict) -> dict[str, str]:
    """id -> text for the evidence the writer may cite (case studies expanded via MCP)."""
    pack: dict[str, str] = {}
    tb = tools("writer", state)
    for e in state.get("evidence", []):
        pack.setdefault(e["evidence_id"], e.get("snippet", ""))
    case_ids = [i for i in pack if ":case:" in i][:4]
    for cid in case_ids:
        try:
            cs = await tb.call("get_case_study", {"id": cid})
            pack[cid] = f"{cs['title']} ({cs['client_industry']}, {cs['date'][:4]}): {cs['markdown'][:1400]}"
        except Exception:  # noqa: BLE001 - keep the snippet
            pass
    return pack


def _policy_rules() -> str:
    rules = []
    if cfg("policy.require_ai_disclosure", False):
        rules.append("7. Platform policy: end the cover letter with this exact line: "
                     "\"Drafted with AI assistance and reviewed by me.\"")
    return "\n".join(rules)


@node("writer")
async def writer(state: dict) -> dict:
    from langgraph.config import get_store

    from agent.memory.store import outcome_hint, style_rules

    job, spec = state["job"], state.get("job_spec") or {}
    persona = profile(state["persona"])
    try:
        store = get_store()
    except Exception:  # noqa: BLE001
        store = None
    rules = await style_rules(store, state.get("user_id", "local"))
    hint = await outcome_hint(store, state.get("user_id", "local"), job.get("category", "other"))
    strategy = state.get("strategy") or (hint or {}).get("strategy") or "default"
    pack = await _evidence_pack(state)
    unsupported = [r["text"] for r in (state.get("retrieval") or {}).get("requirements", [])
                   if r["id"] in (state.get("retrieval") or {}).get("unsupported_requirements", [])]
    t = cfg("thresholds")
    p = load_prompt("writer")
    system = p.render(
        persona_name=persona["name"], headline=persona.get("headline", ""), voice=persona.get("voice", ""),
        length_rule=f"Cover letter {t['proposal_min_words']}-{t['proposal_max_words']} words.",
        policy_rules=_policy_rules(),
        style_rules=("Learned preferences of this freelancer:\n- " + "\n- ".join(rules)) if rules else "",
        strategy_rule=STRATEGIES.get(strategy, ""),
    )
    critique = (state.get("critiques") or [None])[-1] if state.get("revision", 0) else None
    ev_text = "\n".join(f"[{k}] {v[:900]}" for k, v in pack.items())
    user = (f"REQUIREMENTS: {[r.get('text') for r in spec.get('requirements', [])]}\n"
            f"SCREENING QUESTIONS: {spec.get('screening_questions') or job.get('screening_questions') or []}\n"
            f"BID: {state.get('price_quote', {}).get('amount')} {state.get('price_quote', {}).get('unit')}\n"
            f"NO_EVIDENCE (do not claim): {unsupported}\n\nPORTFOLIO EVIDENCE:\n{ev_text}\n\n"
            + (f"PREVIOUS DRAFT:\n{state['draft']['cover_letter']}\nCRITIC SAYS: {critique.get('instructions')} "
               f"{[i.get('detail') for i in critique.get('issues', [])]}\n\n" if critique else "")
            + spotlight("job_post", f"{job['title']}\n\n{job['description']}"))
    out = await structured("writer", system, user, WriterOut)
    version = (state.get("draft") or {}).get("version", 0) + 1
    draft = ProposalDraft(job_id=job["id"], version=version, cover_letter=out.cover_letter.strip(),
                          screening_answers=out.screening_answers, citations=_citations(out.cover_letter),
                          bid_amount=(state.get("price_quote") or {}).get("amount"), strategy=strategy,
                          status="drafting")
    return {"draft": draft.model_dump(), "draft_history": [{"version": version, "text": draft.cover_letter, "by": "writer"}],
            "memory_applied": rules + ([hint["rule"]] if hint else []), "evidence_pack": pack}


@node("verifier")
async def verifier(state: dict) -> dict:
    from rag.verify import verify_claims_async

    draft = dict(state["draft"])
    pack: dict[str, str] = dict(state.get("evidence_pack") or {})
    for e in state.get("evidence", []):
        pack.setdefault(e["evidence_id"], e.get("snippet", ""))
    tb = tools("verifier", state)

    async def search(claim: str):
        try:
            res = await tb.call("search_evidence", {"requirement": claim[:900], "k": 3})
            return [(i["id"], i["snippet"]) for i in res["items"]]
        except Exception:  # noqa: BLE001
            return []

    text, report = await verify_claims_async(draft["cover_letter"], pack.get, search, use_llm="batch")
    answers = []
    for a in draft.get("screening_answers", []):
        a_text, a_rep = await verify_claims_async(a["answer"], pack.get, search, use_llm=False)
        answers.append({**a, "answer": a_text or a["answer"]})
        report.unsupported_before += a_rep.unsupported_before
        report.claims += a_rep.claims
        report.total_claims += a_rep.total_claims
    draft["cover_letter"] = text
    draft["screening_answers"] = answers
    draft["citations"] = [c.model_dump() for c in _citations(text)]
    return {"draft": draft, "claim_report": report.model_dump(mode="json"),
            "draft_history": [{"version": draft["version"], "text": text, "by": "verifier"}]}


@node("critic")
async def critic(state: dict) -> dict:
    t = cfg("thresholds")
    draft, job = state["draft"], state["job"]
    rep = state.get("claim_report") or {}
    words = len(draft["cover_letter"].split())
    p = load_prompt("critic")
    system = p.render(min_words=t["proposal_min_words"], max_words=t["proposal_max_words"])
    user = (f"JOB: {job['title']}\nSCREENING QUESTIONS: {job.get('screening_questions')}\nWORDS: {words}\n"
            f"CLAIM REPORT: {[(c['label'], c['text'][:80]) for c in rep.get('claims', []) if c['label'] != 'not_a_claim']}\n\n"
            f"DRAFT:\n{draft['cover_letter']}\n\nSCREENING ANSWERS: {draft.get('screening_answers')}\n\n"
            + spotlight("job_post", job["description"][:2500]))
    c = await structured("critic", system, user, Critique)
    # deterministic checks the LLM may miss
    if not t["proposal_min_words"] <= words <= t["proposal_max_words"] + 40:
        c.passed = False
        c.issues.append({"kind": "length", "detail": f"{words} words; target {t['proposal_min_words']}-{t['proposal_max_words']}"})
    first = draft["cover_letter"].strip().split("\n")[0].lower()
    if re.match(r"^(dear|hello|hi|greetings)\b|^i am (a|an) ", first):
        c.passed = False
        c.issues.append({"kind": "generic_opening", "detail": "opens with a greeting/self-description"})
    c = Critique.model_validate(c.model_dump())
    revision = state.get("revision", 0)
    out = {"critiques": [c.model_dump()]}
    if not c.passed and revision < cfg("budgets.max_revisions", 2):
        out["revision"] = revision + 1
    return out


CONTACT = re.compile(r"([\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{8,}\d|https?://\S+|www\.\S+|"
                     r"\b(whatsapp|telegram|skype|wechat|signal)\b[^.]*)", re.I)
GUARANTEE = re.compile(r"[^.]*\b(guarantee[ds]?|100% (sure|success|accuracy|satisfaction)|risk[- ]free)\b[^.]*\.?", re.I)
UNPAID = re.compile(r"[^.]*\b(for free|free of charge|unpaid|no charge|at no cost)\b[^.]*\.?", re.I)
AGREE_OFFPLAT = re.compile(r"(?i)(happy|glad|sure|ok(ay)?)[^.]{0,40}(move|talk|continue|chat)[^.]{0,30}(whatsapp|telegram|email|outside)")


def rule_compliance(text: str) -> tuple[str, list[ComplianceViolation], bool]:
    violations, blocked = [], False
    if AGREE_OFFPLAT.search(text):
        violations.append(ComplianceViolation(rule="no off-platform contact", excerpt=AGREE_OFFPLAT.search(text).group(0), fix="blocked"))
        blocked = True
    # contact details first: other filters cut at "." and could leave half an address behind
    for m in CONTACT.finditer(text):
        violations.append(ComplianceViolation(rule="no contact details / links", excerpt=m.group(0)[:120], fix="removed"))
    text = CONTACT.sub("", text)
    for pat, rule in [(GUARANTEE, "no guarantees"), (UNPAID, "no unpaid work")]:
        for m in pat.finditer(text):
            violations.append(ComplianceViolation(rule=rule, excerpt=m.group(0).strip()[:200], fix="removed"))
            text = text.replace(m.group(0), " ")
    text = re.sub(r"[ \t]{2,}", " ", text).replace(" .", ".").strip()
    return text, violations, blocked


@node("compliance")
async def compliance(state: dict, *, key: str = "draft") -> dict:
    text = (state.get("approval") or {}).get("edited_text") or state["draft"]["cover_letter"]
    cleaned, violations, blocked = rule_compliance(text)
    if cfg("policy.require_ai_disclosure", False) and "ai assistance" not in cleaned.lower():
        cleaned = cleaned.rstrip() + "\n\nDrafted with AI assistance and reviewed by me."
        violations.append(ComplianceViolation(rule="AI-assistance disclosure required (policy v2)", excerpt="(missing)",
                                              fix="rewritten"))
    rules = "\n".join(f"- {r}" for r in _policy_text())
    p = load_prompt("compliance")
    try:
        llm = await structured("compliance", p.render(policy_version=cfg("policy.version", 1), policy_rules=rules),
                               f"TEXT:\n{cleaned}", ComplianceVerdict)
        for v in llm.violations:
            if v.fix == "blocked":
                blocked = True
            violations.append(v)
        if llm.cleaned_text and not blocked and len(llm.cleaned_text) > 0.6 * len(cleaned):
            cleaned2, more, b2 = rule_compliance(llm.cleaned_text)  # never trust the LLM's text unchecked
            cleaned, blocked = cleaned2, blocked or b2
            violations += more
    except Exception:  # noqa: BLE001 - rules alone are the floor
        pass
    verdict = ComplianceVerdict(allowed=not blocked, blocked_reason=(violations[0].rule if blocked else None),
                                violations=violations, cleaned_text=cleaned, policy_version=cfg("policy.version", 1))
    draft = dict(state["draft"])
    draft["cover_letter"] = cleaned
    draft["status"] = "pending_review" if verdict.allowed else "drafting"
    out = {"compliance": verdict.model_dump(), "draft": draft}
    if blocked:
        out.update(status="blocked", status_reason=f"Compliance Guard blocked the draft: {verdict.blocked_reason}")
    return out


def _policy_text() -> list[str]:
    from pathlib import Path

    from agent.settings import ROOT

    pack = Path(ROOT) / "data" / "policy_pack" / "marketplace_policy.md"
    lines = [ln.strip()[2:].strip() if ln.strip()[:2].rstrip(".").isdigit() else ln.strip()
             for ln in pack.read_text().splitlines() if re.match(r"^\s*\d+\.", ln)]
    if cfg("policy.require_ai_disclosure", False):
        lines.append("Proposals drafted with AI tools must include an AI-assistance disclosure.")
    return lines
