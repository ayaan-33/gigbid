"""The three parallel analysis branches: Job Analyst, Risk Assessor, Fit Matcher (R3)."""

from __future__ import annotations

import math
import re

from agent.guardrails import spotlight
from agent.handoffs import EvidenceRef, FitReport, JobSpec, RequirementMatch, RiskFlag, RiskReport
from agent.llm import structured
from agent.nodes.base import node
from agent.nodes.common import detect_injection, profile, tools
from agent.prompts import load_prompt
from agent.settings import cfg
from scripts.data.taxonomy import CATEGORY_SKILLS, extract_skills

# --------------------------------------------------------------------------- Job Analyst


@node("analyst")
async def job_analyst(state: dict) -> dict:
    job = state["job"]
    p = load_prompt("analyst")
    user = (f"job_id: {job['id']}\nposted budget: {job.get('budget')}\nscreening questions: "
            f"{job.get('screening_questions')}\n\n" + spotlight("job_post", f"{job['title']}\n\n{job['description']}"))
    spec = await structured("analyst", p.text, user, JobSpec)
    spec.job_id = job["id"]
    if not spec.screening_questions and job.get("screening_questions"):
        spec.screening_questions = list(job["screening_questions"])
    b = job.get("budget") or {}
    spec.budget_type = b.get("type", spec.budget_type) or spec.budget_type
    spec.budget_min = b.get("min", spec.budget_min)
    spec.budget_max = b.get("max", spec.budget_max)
    if not spec.requirements:
        from rag.variants.pipeline import heuristic_requirements

        spec.requirements = [{"id": r["id"], "text": r["text"]} for r in heuristic_requirements(job["title"], job["description"])]
    return {"job_spec": spec.model_dump()}


# --------------------------------------------------------------------------- Risk Assessor

UNPAID = re.compile(r"(?i)\b(unpaid|for free|free (test|trial|sample)|test task.*(free|unpaid)|no pay(ment)? until|only the best submission will be paid)\b")
OFFPLAT = re.compile(r"(?i)(contact me (on|at|via)|text me|email (me|recruiter)[\w.@ ]*@|whatsapp \+|telegram @|@gmail\.com|@yahoo\.com|"
                     r"pay(ment)? (outside|off) (the )?platform|avoid (the )?fees|wire (me|transfer)|western union)")
PAYSCAM = re.compile(r"(?i)(cheque|check deposit|gift ?cards?|send back the difference|usdt|crypto wallet|bitcoin)")
CREDS = re.compile(r"(?i)(share your (upwork )?(login|password|account)|under your account|send (your )?(bank details|id card|ssn))")


def risk_signals(job: dict, client: dict) -> dict:
    text = f"{job.get('title', '')}\n{job.get('description', '')}"
    flags: list[RiskFlag] = []
    if UNPAID.search(text):
        flags.append(RiskFlag.unpaid_work)
    if OFFPLAT.search(text):
        flags.append(RiskFlag.off_platform_contact)
    if PAYSCAM.search(text):
        flags.append(RiskFlag.off_platform_payment)
    if CREDS.search(text):
        flags.append(RiskFlag.credential_request)
    if not client.get("payment_verified"):
        flags.append(RiskFlag.unverified_payment)
    if (client.get("total_spent") or 0) == 0 and (client.get("hires") or 0) == 0:
        flags.append(RiskFlag.poor_client_history)
    bmax = (job.get("budget") or {}).get("max") or 0
    if bmax and bmax < 15 and (job.get("budget") or {}).get("type") == "fixed":
        flags.append(RiskFlag.unrealistic_budget)
    quality = 0.5
    if client:
        quality = min(1.0, 0.25 * bool(client.get("payment_verified")) + 0.25 * min(1, (client.get("hires") or 0) / 10)
                      + 0.25 * min(1, (client.get("total_spent") or 0) / 10000)
                      + 0.25 * (((client.get("avg_rating_given") or 4.0) - 3) / 2 if client.get("avg_rating_given") else 0.3))
    hard = {RiskFlag.unpaid_work, RiskFlag.off_platform_contact, RiskFlag.off_platform_payment, RiskFlag.credential_request}
    return {"flags": flags, "client_quality": round(quality, 3), "hard_hits": [f for f in flags if f in hard]}


@node("risk_assessor")
async def risk_assessor(state: dict) -> dict:
    job = state["job"]
    tb = tools("risk_assessor", state)
    client = {}
    if job.get("client_id"):
        client = await tb.call("get_client_history", {"client_id": job["client_id"]})
    sig = risk_signals(job, client)
    injected, excerpt, guard = await detect_injection(job.get("description", ""))
    if injected:
        sig["flags"].append(RiskFlag.prompt_injection)
    p = load_prompt("risk_assessor")
    user = (f"client history: {client}\nrule-based signals: {[f.value for f in sig['flags']]} "
            f"(client_quality={sig['client_quality']})\ninjection check: {guard}\n\n"
            + spotlight("job_post", f"{job['title']}\n\n{job['description']}"))
    try:
        rep = await structured("risk_assessor", p.text, user, RiskReport)
    except Exception:  # noqa: BLE001 - the rules alone still produce a report
        rep = RiskReport(score=0.5, explanation="LLM unavailable; rule-based assessment only")
    # deterministic floor: hard scam signals can never be explained away by the LLM
    flags = sorted({*rep.flags, *sig["flags"]}, key=lambda f: f.value)
    is_scam = rep.is_scam or len(sig["hard_hits"]) >= 1 and (not client.get("payment_verified") or len(sig["hard_hits"]) >= 2)
    score = max(rep.score, 0.85 if is_scam else 0.0, 0.35 if RiskFlag.unverified_payment in flags else 0.0)
    rep = RiskReport(score=round(min(score, 1.0), 3), client_quality=sig["client_quality"], is_scam=is_scam, flags=flags,
                     injection_detected=injected, injected_text=excerpt, explanation=rep.explanation)
    return {"risk_report": rep.model_dump(mode="json"), "client": client}


# --------------------------------------------------------------------------- Fit Matcher


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


@node("fit_matcher")
async def fit_matcher(state: dict) -> dict:
    """Maps every requirement to portfolio evidence via the Portfolio MCP server, grades each
    match with the cross-encoder, and scores fit = 0.6 * evidence coverage + 0.4 * skill coverage."""
    from rag.index.embed import rerank
    from rag.variants.pipeline import heuristic_requirements

    job = state["job"]
    persona = profile(state["persona"])
    tb = tools("fit_matcher", state)
    reqs = heuristic_requirements(job["title"], job["description"])  # JobSpec is computed in parallel
    matches, evidence = [], []
    for r in reqs:
        query = f"{r['text']} ({job['title']})"
        # proof first (case studies, repos, reviews), then one past proposal for phrasing
        proof = await tb.call("search_evidence", {"requirement": query, "k": 3,
                                                  "filters": {"type": ["case_study", "repo", "review"]}})
        phr = await tb.call("search_evidence", {"requirement": query, "k": 1,
                                                "filters": {"type": ["proposal"], "outcome": ["won", "replied"]}})
        items = proof["items"] + phr["items"]
        # a matching past proposal points at a project: add that project's case study as proof
        for i in phr["items"]:
            if i.get("project") and not any(x.get("project") == i["project"] and x["type"] == "case_study" for x in items):
                try:
                    cs = await tb.call("get_case_study", {"id": f"{state['persona']}:case:{i['project']}"})
                    items.insert(len(proof["items"]), {"id": cs["id"], "title": cs["title"], "type": "case_study",
                                                       "snippet": cs["markdown"][:500], "outcome": None, "project": cs["project"]})
                except Exception:  # noqa: BLE001 - proposal cites a project without a case study
                    pass
        probs = [_sigmoid(s) for s in rerank(r["text"], [i["snippet"] for i in items])] if items else []
        refs = [EvidenceRef(evidence_id=i["id"], title=i["title"], type=i["type"], snippet=i["snippet"][:300],
                            score=round(p, 3), outcome=i.get("outcome")) for i, p in zip(items, probs, strict=True)]
        best = max(probs, default=0.0)
        strength = "strong" if best >= 0.6 else ("partial" if best >= 0.3 else "none")
        matches.append(RequirementMatch(requirement_id=r["id"], requirement=r["text"], evidence=refs[:4], strength=strength,
                                        reason=f"best evidence relevance {best:.2f}"))
        evidence += [e.model_dump() for e in refs[:4]]
    cov = sum({"strong": 1.0, "partial": 0.5, "none": 0.0}[m.strength] for m in matches) / max(1, len(matches))
    caps = set(persona.get("capabilities", []))
    jskills = set(job.get("skills") or []) | set(extract_skills(job["description"]))
    domain_skills = {s for s in jskills if any(s in cs for cs in CATEGORY_SKILLS.values())} - {"Python", "SQL", "JavaScript"}
    skill_cov = len(domain_skills & caps) / len(domain_skills) if domain_skills else 0.5
    in_cat = job.get("category") in persona.get("categories", []) + persona.get("secondary", [])
    score = (0.6 * cov + 0.4 * skill_cov) * (1.0 if in_cat else 0.6)
    report = FitReport(score=round(score, 3), matches=matches, matched_skills=sorted(domain_skills & caps),
                       missing_skills=sorted(domain_skills - caps),
                       reasons=[f"evidence coverage {cov:.2f} over {len(matches)} requirements",
                                f"skill coverage {skill_cov:.2f}", "in persona category" if in_cat else "outside persona category"])
    unsupported = [m.requirement_id for m in matches if m.strength == "none"]
    return {"fit_report": report.model_dump(), "evidence": evidence,
            "retrieval": {"requirements": reqs, "unsupported_requirements": unsupported,
                          "variant": cfg("rag.variant")}}
