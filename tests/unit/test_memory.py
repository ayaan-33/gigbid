"""R7: long-term memory only changes through explicit promotion rules."""

from langgraph.store.memory import InMemoryStore

from agent.memory.promotion_rules import edit_patterns, promote_outcomes, promote_style
from agent.memory.store import delete_memory, list_memory, record_edit, record_outcome, style_rules

DRAFT = "I am a passionate engineer who loves data. Your churn model needs honest evaluation. Best regards, Maya"


def test_edit_patterns():
    edited = "Your churn model needs honest evaluation. What does success look like?"
    pats = edit_patterns(DRAFT, edited)
    assert "cut_first_sentence" in pats and "removed_word:passionate" in pats and "added_question" in pats


def test_style_needs_three_of_last_ten():
    log = [["removed_word:passionate"], ["shortened"], ["removed_word:passionate"]]
    assert promote_style(log) == {}
    log.append(["removed_word:passionate"])
    assert "removed_word:passionate" in promote_style(log)
    # pattern falling out of the window is no longer promoted
    assert promote_style(log + [[]] * 10) == {}


def test_outcome_needs_volume_and_lift():
    rows = [{"category": "ai_ml", "strategy": "question_led", "replied": True}] * 3 + \
           [{"category": "ai_ml", "strategy": "default", "replied": False}] * 3
    out = promote_outcomes(rows)
    assert out["ai_ml"]["strategy"] == "question_led" and out["ai_ml"]["reply_rate"] == 1.0
    assert promote_outcomes(rows[:4]) == {}  # fewer than 5 outcomes -> nothing promoted


async def test_store_promotion_and_user_delete_tombstone():
    s = InMemoryStore()
    for i in range(3):
        await record_edit(s, "u1", DRAFT, DRAFT.replace("passionate ", ""), f"t{i}")
    rules = await style_rules(s, "u1")
    assert any("passionate" in r for r in rules)
    assert await style_rules(s, "u2") == []  # tenant scoped
    await delete_memory(s, "u1", "style", "removed_word:passionate")
    await record_edit(s, "u1", DRAFT, DRAFT.replace("passionate ", ""), "t9")
    assert not any("passionate" in r for r in await style_rules(s, "u1"))  # deletion is respected
    for i in range(6):
        await record_outcome(s, "u1", "web_dev", "evidence_first" if i < 3 else "default", i < 3, f"p{i}")
    kinds = {m["kind"] for m in await list_memory(s, "u1")}
    assert "outcome" in kinds
