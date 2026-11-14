"""Explicit promotion rules (R7). Nothing reaches long-term memory except through these.

Style rule   : an edit pattern (e.g. "cut_first_sentence", "removed_word:passionate") is promoted
               when it occurs in >= `memory.style.min_occurrences` of the user's last
               `memory.style.window` approved edits.
Outcome rule : in a job category with >= `memory.outcome.min_outcomes` recorded outcomes, a proposal
               strategy is promoted when its reply rate beats the category baseline by
               >= `memory.outcome.min_lift` (absolute).
Inputs are the event logs (user edits, marketplace outcomes) - never raw tool output.
"""

from __future__ import annotations

import re
from collections import Counter

from agent.settings import cfg

WATCHWORDS = {"passionate", "hardworking", "hard-working", "expert", "guru", "ninja", "rockstar", "synergy",
              "leverage", "dedicated", "guarantee", "guaranteed", "best", "perfect", "excited", "thrilled", "honestly"}
PATTERN_TEXT = {
    "cut_first_sentence": "Always cut the first sentence of the draft (start with the second idea).",
    "shortened": "Keep proposals shorter: the user consistently trims ~20%+ of the draft.",
    "removed_signoff": "End without a formal sign-off line.",
    "added_question": "End with one specific question to the client.",
}


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", t.strip()) if s.strip()]


def edit_patterns(draft: str, edited: str) -> list[str]:
    """Interpretable features of how the user changed a draft."""
    pats: list[str] = []
    ds, es = _sentences(draft), _sentences(edited)
    if ds and es and ds[0] not in edited and (len(ds) < 2 or ds[1][:30] in edited):
        pats.append("cut_first_sentence")
    if len(edited.split()) < 0.8 * len(draft.split()):
        pats.append("shortened")
    dw = Counter(w.lower().strip(".,!?;:") for w in draft.split())
    ew = Counter(w.lower().strip(".,!?;:") for w in edited.split())
    for w in WATCHWORDS:
        if dw[w] and not ew[w]:
            pats.append(f"removed_word:{w}")
    if re.search(r"(?im)^(best|regards|kind regards|cheers|thanks)\b", draft) and not re.search(
            r"(?im)^(best|regards|kind regards|cheers|thanks)\b", edited):
        pats.append("removed_signoff")
    if edited.rstrip().endswith("?") and not draft.rstrip().endswith("?"):
        pats.append("added_question")
    return pats


def rule_text(pattern: str) -> str:
    if pattern.startswith("removed_word:"):
        return f"Never use the word \"{pattern.split(':', 1)[1]}\"."
    return PATTERN_TEXT.get(pattern, pattern)


def promote_style(edit_log: list[list[str]]) -> dict[str, dict]:
    """edit_log: pattern lists of approved edits, oldest first -> {pattern: rule} to promote."""
    window = cfg("memory.style.window", 10)
    need = cfg("memory.style.min_occurrences", 3)
    recent = edit_log[-window:]
    counts = Counter(p for pats in recent for p in set(pats))
    return {p: {"rule": rule_text(p), "support": c, "window": len(recent)} for p, c in counts.items() if c >= need}


def should_promote_style_edit(edit_count: int, consistent_pattern: bool) -> bool:
    """Starter-kit signature kept for compatibility."""
    return edit_count >= cfg("memory.style.min_occurrences", 3) and consistent_pattern


def promote_outcomes(outcomes: list[dict]) -> dict[str, dict]:
    """outcomes: [{category, strategy, replied: bool}] -> {category: promoted insight}."""
    need = cfg("memory.outcome.min_outcomes", 5)
    lift_min = cfg("memory.outcome.min_lift", 0.10)
    out: dict[str, dict] = {}
    cats: dict[str, list[dict]] = {}
    for o in outcomes:
        cats.setdefault(o["category"], []).append(o)
    for cat, rows in cats.items():
        if len(rows) < need:
            continue
        base = sum(r["replied"] for r in rows) / len(rows)
        by: dict[str, list[bool]] = {}
        for r in rows:
            by.setdefault(r["strategy"], []).append(r["replied"])
        best = max(by.items(), key=lambda kv: (sum(kv[1]) / len(kv[1]), len(kv[1])))
        rate = sum(best[1]) / len(best[1])
        if len(best[1]) >= 3 and rate - base >= lift_min:
            out[cat] = {"strategy": best[0], "reply_rate": round(rate, 3), "baseline": round(base, 3), "n": len(rows),
                        "rule": f"In {cat} jobs, '{best[0]}' proposals got replies {rate:.0%} of the time vs {base:.0%} overall."}
    return out
