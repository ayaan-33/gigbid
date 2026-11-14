"""GigSim platform policy versions.

v1 is the launch policy. v2 is the "platform policy update" (the assignment's change request):
  * Connects surcharge: jobs that already have >= 20 proposals cost +4 Connects.
  * AI-assistance disclosure: proposals must contain an AI-assistance disclosure line
    (e.g. "Drafted with AI assistance and reviewed by me."). Missing it -> 422 on submit.
"""

from __future__ import annotations

import re
from typing import Any

POLICIES: dict[int, dict[str, Any]] = {
    1: {
        "version": 1,
        "effective": "2026-10-27",
        "rules": [
            "No off-platform contact or payment requests.",
            "No unpaid production work disguised as a trial.",
            "Never fabricate skills, clients, outcomes, credentials or years of experience.",
            "Do not guarantee results that cannot be guaranteed.",
            "Automation must keep a human in the loop for every proposal and message.",
        ],
        "connects_surcharge": None,
        "require_ai_disclosure": False,
    },
    2: {
        "version": 2,
        "effective": "2026-11-02",
        "rules": [
            "No off-platform contact or payment requests.",
            "No unpaid production work disguised as a trial.",
            "Never fabricate skills, clients, outcomes, credentials or years of experience.",
            "Do not guarantee results that cannot be guaranteed.",
            "Automation must keep a human in the loop for every proposal and message.",
            "NEW: Proposals drafted with AI tools must include an AI-assistance disclosure.",
            "NEW: Jobs with 20 or more proposals cost 4 additional Connects to bid on.",
        ],
        "connects_surcharge": {"proposals_threshold": 20, "extra_connects": 4},
        "require_ai_disclosure": True,
    },
}

_CONTACT = re.compile(
    r"([\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s().-]{8,}\d|whatsapp|telegram|skype|wechat|"
    r"paypal\.me|wire transfer|western union|crypto)",
    re.I,
)
DISCLOSURE = re.compile(r"\b(ai[- ]assist(ed|ance)|drafted with (the help of )?ai)\b", re.I)


def connects_cost_for(job: dict[str, Any], policy: dict[str, Any]) -> int:
    base = int(job.get("connects_cost", 8))
    s = policy.get("connects_surcharge")
    if s and int(job.get("proposals_count", 0)) >= s["proposals_threshold"]:
        base += s["extra_connects"]
    return base


def validate_proposal_text(text: str, policy: dict[str, Any], message: bool = False) -> list[str]:
    problems = []
    if _CONTACT.search(text):
        problems.append("off_platform_contact_or_payment")
    if policy.get("require_ai_disclosure") and not message and not DISCLOSURE.search(text):
        problems.append("missing_ai_disclosure")
    return problems
