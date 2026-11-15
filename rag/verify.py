"""B3 claim verification: split a draft into claims, check each against portfolio evidence, and
remove or rewrite unsupported claims BEFORE the Critic sees the draft.

Pipeline per draft
  1. split   - sentences; plans/questions/greetings/sign-offs are `not_a_claim`
  2. gather  - evidence cited inline as [evidence_id] + top hits from searching the claim itself
  3. check   - deterministic gate: every number/percentage in the claim must appear in the
               evidence; then an entailment check (LLM `verifier` node, JSON) or, without an LLM,
               a lexical-overlap heuristic
  4. fix     - unsupported -> removed (or rewritten from evidence by the LLM); partly supported ->
               numbers/specifics not in evidence are dropped
Returns the cleaned text + a ClaimReport (unsupported_before / unsupported_after are reported).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from agent.handoffs import Claim, ClaimLabel, ClaimReport

CITE = re.compile(r"\[([a-z_]+:[a-z_]+:[\w\-.]+(?:#[\w.:\-]+)?)\]")
NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?\s?(?:%|x|k|ms|s|hours?|weeks?|days?|months?|years?)?", re.I)
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")
NOT_CLAIM = re.compile(
    r"^(hi|hello|dear|best|regards|thanks|thank you|cheers|kind regards)\b|\?\s*$|"
    r"\b(i would|i will|i'd|i can|i could|we could|we can|happy to|let's|next step|i propose|i plan|my plan|"
    r"i'll|would you|could you|do you|are you|if you|we will|i'm available|available to start)\b",
    re.I,
)
CLAIMY = re.compile(r"\b(i|i've|i have|my|we|our team|built|delivered|shipped|led|reduced|improved|cut|increased|"
                    r"designed|developed|implemented|deployed|trained|migrated|automated|launched|worked)\b", re.I)
STOP = set("the a an and or of to for in on with by at from as is are was were be been it this that my our your i we "
           "you they their client clients project projects work worked using use used into over than which who".split())


def split_claims(text: str) -> list[str]:
    parts = []
    for para in text.split("\n"):
        para = para.strip().lstrip("-*• ").strip()
        if para:
            parts += [s.strip() for s in SENT.split(para) if s.strip()]
    return parts


def is_claim(sentence: str) -> bool:
    if len(sentence.split()) < 4 or NOT_CLAIM.search(sentence):
        return False
    return bool(CLAIMY.search(sentence) or NUM.search(sentence))


def _norm_num(s: str) -> str:
    return re.sub(r"[\s,$]", "", s.lower())


def numbers_supported(claim: str, evidence: str) -> tuple[bool, list[str]]:
    nums = [_norm_num(n) for n in NUM.findall(claim)]
    nums = [n for n in nums if re.search(r"\d", n) and not re.fullmatch(r"(19|20)\d\d", n)]
    ev = _norm_num(evidence)
    missing = [n for n in nums if re.sub(r"[a-z%]+$", "", n) not in ev]
    return not missing, missing


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z0-9+#.\-]{2,}", s.lower()) if t not in STOP}


def heuristic_label(claim: str, evidence: list[tuple[str, str]]) -> tuple[ClaimLabel, list[str], str]:
    if not evidence:
        return ClaimLabel.unsupported, [], "no evidence found"
    ct = _tokens(CITE.sub("", claim))
    best, best_ids = 0.0, []
    for eid, text in evidence:
        overlap = len(ct & _tokens(text)) / max(1, len(ct))
        if overlap > best:
            best, best_ids = overlap, [eid]
    joined = " ".join(t for _, t in evidence)
    nums_ok, missing = numbers_supported(claim, joined)
    if best >= 0.45 and nums_ok:
        return ClaimLabel.supported, best_ids, f"token overlap {best:.2f}"
    if best >= 0.25:
        reason = f"overlap {best:.2f}" + (f"; numbers not in evidence: {missing}" if missing else "")
        return ClaimLabel.partly_supported, best_ids, reason
    return ClaimLabel.unsupported, [], f"overlap {best:.2f}"


class _LLMVerdict:  # parsed JSON from the verifier prompt
    def __init__(self, d: dict):
        self.label = ClaimLabel(d.get("label", "unsupported"))
        self.evidence_ids = [str(x) for x in d.get("evidence_ids", [])]
        self.reason = str(d.get("reason", ""))[:300]
        self.rewrite = d.get("supported_rewrite") or None


async def llm_label(claim: str, evidence: list[tuple[str, str]]) -> _LLMVerdict:
    from agent.llm import complete
    from agent.prompts import load_prompt

    p = load_prompt("verifier")
    ev = "\n\n".join(f"[{eid}]\n{text[:900]}" for eid, text in evidence[:6])
    raw = await complete("verifier", p.text, f"CLAIM:\n{claim}\n\nEVIDENCE:\n{ev}", json_mode=True, max_tokens=400)
    from agent.llm import _extract_json

    return _LLMVerdict(_extract_json(raw))


def _strip_unsupported_specifics(sentence: str, missing: list[str]) -> str:
    out = sentence
    for m in missing:
        out = re.sub(re.escape(m), "", out, flags=re.I)
    out = re.sub(r"\(\s*\)|\s{2,}", " ", out).replace(" ,", ",").replace(" .", ".").strip()
    return out


async def llm_label_batch(items: list[tuple[str, list[tuple[str, str]]]]) -> list[_LLMVerdict]:
    """One LLM call for every claim of a draft (cost: ~1 call per draft instead of per claim)."""
    from agent.llm import _extract_json, complete
    from agent.prompts import load_prompt

    p = load_prompt("verifier")
    blocks = []
    for n, (claim, ev) in enumerate(items):
        evs = "\n".join(f"  [{eid}] {text[:600]}" for eid, text in ev[:4])
        blocks.append(f"CLAIM {n}: {claim}\nEVIDENCE {n}:\n{evs or '  (none)'}")
    sys = p.text + '\n\nYou will get several numbered claims. Return {"verdicts": [<one object per claim, in order>]}.'
    raw = await complete("verifier", sys, "\n\n".join(blocks), json_mode=True, max_tokens=300 + 160 * len(items))
    vs = _extract_json(raw).get("verdicts", [])
    if len(vs) != len(items):
        raise ValueError("verifier returned wrong number of verdicts")
    return [_LLMVerdict(v) for v in vs]


async def _maybe_await(x):
    import inspect

    return await x if inspect.isawaitable(x) else x


async def verify_claims_async(
    draft: str,
    evidence_lookup: Callable[[str], str | None],
    search: Callable[[str], object] | None = None,
    use_llm: bool | str = True,
) -> tuple[str, ClaimReport]:
    """`evidence_lookup(id) -> text`; `search(claim) -> [(id, text)]` (sync or async portfolio search).
    use_llm: True (per claim), "batch" (one call per draft), False (deterministic only)."""
    claims: list[Claim] = []
    kept_sentences: list[str] = []
    sentences = split_claims(draft)
    gathered: dict[int, list[tuple[str, str]]] = {}
    for n, sentence in enumerate(sentences):
        if is_claim(sentence):
            cited = CITE.findall(sentence)
            ev = [(c, t) for c in cited if (t := evidence_lookup(c))]
            if search:
                seen = {e for e, _ in ev}
                found = await _maybe_await(search(CITE.sub("", sentence)))
                ev += [(e, t) for e, t in found if e not in seen][:3]
            gathered[n] = ev
    batch: dict[int, _LLMVerdict] = {}
    batch_err = ""
    if use_llm == "batch" and gathered:
        try:
            order = sorted(gathered)
            for n, v in zip(order, await llm_label_batch([(sentences[n], gathered[n]) for n in order]), strict=True):
                batch[n] = v
        except Exception as e:  # noqa: BLE001
            batch_err = f"llm unavailable ({type(e).__name__}); heuristic used"
    for n, sentence in enumerate(sentences):
        if n not in gathered:
            if _FRAGMENT.match(sentence):  # stray split fragments like "At." are dropped, not kept
                continue
            claims.append(Claim(text=sentence, label=ClaimLabel.not_a_claim))
            kept_sentences.append(sentence)
            continue
        ev = gathered[n]
        verdict_label, ids, reason, rewrite = None, [], batch_err, None
        if n in batch:
            v = batch[n]
            verdict_label, ids, reason, rewrite = v.label, v.evidence_ids, v.reason, v.rewrite
        elif use_llm is True and ev:
            try:
                v = await llm_label(sentence, ev)
                verdict_label, ids, reason, rewrite = v.label, v.evidence_ids, v.reason, v.rewrite
            except Exception as e:  # noqa: BLE001 - fall back to the deterministic checker
                reason = f"llm unavailable ({type(e).__name__}); heuristic used"
        if verdict_label is None:
            verdict_label, ids, h_reason = heuristic_label(sentence, ev)
            reason = (reason + "; " if reason else "") + h_reason
        # deterministic gate: numbers must exist in evidence even if the LLM said "supported"
        nums_ok, missing = numbers_supported(sentence, " ".join(t for _, t in ev))
        if verdict_label == ClaimLabel.supported and not nums_ok:
            verdict_label, reason = ClaimLabel.partly_supported, reason + f"; numbers not in evidence: {missing}"
        c = Claim(text=sentence, label=verdict_label, evidence_ids=ids, reason=reason)
        if verdict_label == ClaimLabel.supported:
            kept_sentences.append(sentence)
        elif verdict_label == ClaimLabel.partly_supported:
            fixed = rewrite or _strip_unsupported_specifics(sentence, missing)
            c.action, c.rewritten = "rewritten", fixed
            kept_sentences.append(fixed)
        else:
            if rewrite and ids:
                c.action, c.rewritten = "rewritten", rewrite
                kept_sentences.append(rewrite)
            else:
                c.action = "removed"
        claims.append(c)
    real = [c for c in claims if c.label != ClaimLabel.not_a_claim]
    report = ClaimReport(
        claims=claims,
        total_claims=len(real),
        unsupported_before=sum(1 for c in real if c.label == ClaimLabel.unsupported),
        unsupported_after=sum(1 for c in real if c.label == ClaimLabel.unsupported and c.action == "kept"),
    )
    return _rejoin(draft, kept_sentences), report


_FRAGMENT = re.compile(r"^\W*\w{0,3}\W*$")


def _rejoin(original: str, sentences: list[str]) -> str:
    """Rebuild paragraphs: keep the draft's paragraph breaks where sentences survived."""
    paras, out = [p for p in original.split("\n") if p.strip()], []
    remaining = list(sentences)
    for para in paras:
        mine = [s for s in split_claims(para)]
        kept = []
        for s in mine:
            match = next((r for r in remaining if r == s or s.startswith(r[:20]) or r.startswith(s[:20])), None)
            if match is not None:
                kept.append(match)
                remaining.remove(match)
        if kept:
            out.append(" ".join(kept))
    out += remaining
    return "\n\n".join(out)


def verify_claims(draft: str, evidence: list[dict]) -> list[dict]:
    """Starter-kit signature, kept for compatibility: heuristic only, evidence = [{id, text}]."""
    import asyncio

    lut = {e["id"]: e.get("text", "") for e in evidence}

    def search(claim: str) -> list[tuple[str, str]]:
        return list(lut.items())

    _, rep = asyncio.run(verify_claims_async(draft, lut.get, search, use_llm=False))
    return [json.loads(c.model_dump_json()) for c in rep.claims]
