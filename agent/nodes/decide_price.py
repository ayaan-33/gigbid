"""Decision node (skip / watch / bid) and Pricing Strategist. Both are deterministic, driven by
config thresholds so a policy or cost change is a config edit (change request)."""

from __future__ import annotations

from agent.handoffs import BidDecision, PriceQuote
from agent.nodes.base import node
from agent.nodes.common import profile, tools
from agent.settings import cfg


def connects_cost(job: dict, marketplace_reports_cost: bool = True) -> int:
    """Connects cost to bid. The marketplace's own figure is authoritative (GigSim prices jobs under
    its CURRENT policy, surcharge included), so it is never adjusted twice. The config surcharge is
    only applied when a marketplace does not report the cost (e.g. some live listings)."""
    base = int(job.get("connects_cost") or 0)
    if marketplace_reports_cost and base:
        return base
    s = cfg("policy.connects_surcharge", {}) or {}
    if s.get("enabled") and int(job.get("proposals_count") or 0) >= int(s.get("proposals_threshold", 20)):
        base += int(s.get("extra_connects", 4))
    return base


@node("decision")
async def decide(state: dict) -> dict:
    job, risk, fit = state["job"], state.get("risk_report") or {}, state.get("fit_report") or {}
    persona = profile(state["persona"])
    reasons: list[str] = []
    t = cfg("thresholds")
    budget = job.get("budget") or {}
    bmax = budget.get("max") or 0
    floor = persona["fixed_floor"] if budget.get("type", "fixed") == "fixed" else persona["hourly_rate"] * 0.7
    if risk.get("is_scam") or risk.get("score", 0) >= t["scam_risk_score"]:
        action, conf = "skip", 0.95
        reasons.append(f"likely scam / unsafe (risk {risk.get('score')}; flags {risk.get('flags')})")
    elif risk.get("score", 0) > t["maximum_risk_score"]:
        action, conf = "skip", 0.8
        reasons.append(f"risk {risk.get('score')} above limit {t['maximum_risk_score']}")
    elif bmax and bmax < floor:
        action, conf = "skip", 0.85
        reasons.append(f"budget {bmax} below the freelancer's floor {floor}")
    elif fit.get("score", 0) >= t["minimum_fit_score"]:
        action, conf = "bid", min(0.95, 0.5 + fit["score"] / 2)
        reasons.append(f"fit {fit['score']} >= {t['minimum_fit_score']}")
    elif fit.get("score", 0) >= t["watch_fit_score"]:
        action, conf = "watch", 0.6
        reasons.append(f"fit {fit['score']} is borderline (watch range {t['watch_fit_score']}-{t['minimum_fit_score']})")
    else:
        action, conf = "skip", 0.8
        reasons.append(f"fit {fit.get('score')} below {t['watch_fit_score']}")
    if risk.get("injection_detected") and action == "bid":
        reasons.append("post contains injected instructions; they were ignored (data, not commands)")
    autonomy = state.get("autonomy", cfg("autonomy.default_level", "suggest"))
    decided_by = "rules"
    status = {"bid": "drafting", "watch": "watch", "skip": "skipped"}[action]
    if action == "skip" and autonomy != "auto_skip":
        reasons.append("recommendation only: the user confirms skips (autonomy=suggest)")
    d = BidDecision(action=action, confidence=round(conf, 2), reasons=reasons, decided_by=decided_by)
    return {"decision": d.model_dump(), "status": status, "status_reason": reasons[0]}


@node("pricing")
async def price(state: dict) -> dict:
    job, client = state["job"], state.get("client") or {}
    persona = profile(state["persona"])
    tb = tools("pricing", state)
    budget = job.get("budget") or {}
    unit = budget.get("type", "fixed")
    stats = await tb.call("get_market_stats", {"category": job.get("category"), "budget_type": unit})
    balance = (await tb.call("get_connects_balance", {})).get("balance", 0)
    cost = connects_cost(job)
    policy = await tb.call("get_policy", {})
    drift = int(policy.get("version", 1)) > int(cfg("policy.version", 1))
    if unit == "hourly":
        floor = persona["hourly_rate"]
        lo, hi = budget.get("min") or floor * 0.8, budget.get("max") or floor * 1.3
        amount = max(floor, min(hi, (lo + hi) / 2 if hi >= floor else floor))
    else:
        floor = persona["fixed_floor"]
        bmax = budget.get("max") or stats.get("median") or floor * 2
        target = 0.92 * bmax
        if client.get("total_spent", 0) > 20000:  # experienced, quality-seeking clients tolerate the top of range
            target = 0.98 * bmax
        amount = max(floor, target)
    fit = (state.get("fit_report") or {}).get("score", 0.5)
    quality = (state.get("risk_report") or {}).get("client_quality", 0.5)
    crowd = int(job.get("proposals_count") or 0)
    win = max(0.02, min(0.6, 0.35 * fit + 0.15 * quality - 0.004 * crowd))
    value = win * amount * (1 if unit == "fixed" else 20)  # hourly: ~20h first milestone
    worth = value >= cost * cfg("connects.value_per_connect_usd", 0.15) * 10 and win >= cfg("connects.min_expected_win_prob", 0.05)
    weekly = int(state.get("weekly_connects_budget") or cfg("connects.weekly_budget_default", 80))
    spent = int(state.get("connects_spent_this_week") or 0)
    rationale = (f"{unit} bid of ${amount:,.0f} ({'within' if amount <= (budget.get('max') or amount) else 'above'} the client's "
                 f"stated budget {budget.get('min')}-{budget.get('max')}; market median {stats.get('median')}; your floor {floor}). "
                 f"Costs {cost} Connects (balance {balance}, weekly budget {weekly - spent} left). "
                 f"Estimated win chance {win:.0%} -> {'worth it' if worth else 'NOT worth the Connects'}.")
    if spent + cost > weekly:
        worth = False
        rationale += " Weekly Connects budget would be exceeded."
    if drift:
        rationale += (f" WARNING: marketplace policy is v{policy.get('version')} but GigBid is configured for "
                      f"v{cfg('policy.version', 1)} (update agent/config.yaml -> policy).")
    q = PriceQuote(amount=round(amount, 2), unit=unit, market_p25=stats.get("p25"), market_median=stats.get("median"),
                   market_p75=stats.get("p75"), user_floor=floor, connects_cost=cost, expected_win_prob=round(win, 3),
                   connects_worth_it=worth, rationale=rationale)
    return {"price_quote": q.model_dump()}
