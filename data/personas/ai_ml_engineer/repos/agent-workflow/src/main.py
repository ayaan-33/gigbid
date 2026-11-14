FLOWS = {
    "reset_password": ["Open Settings", "Tap Security", "Choose Reset password"],
    "change_plan": ["Open Billing", "Pick a plan", "Confirm"],
}


def respond(intent: str, fallback) -> str:
    if intent in FLOWS:
        return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(FLOWS[intent]))
    return fallback(intent)


from openai import OpenAI

client = OpenAI()

SYSTEM = "Answer only from the provided context. If the context is insufficient, say so."


def answer(question: str, context: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}],
    )
    return resp.choices[0].message.content


from typing import TypedDict

from langgraph.graph import END, StateGraph


class State(TypedDict):
    request: str
    plan: list[str]
    result: str


def plan_step(state: State) -> dict:
    return {"plan": ["lookup", "draft", "review"]}


graph = StateGraph(State)
graph.add_node("plan", plan_step)
graph.set_entry_point("plan")
graph.add_edge("plan", END)
workflow = graph.compile()


TENANT_POLICY = """
alter table projects enable row level security;
create policy tenant_isolation on projects
  using (tenant_id = current_setting('app.tenant_id')::uuid);
"""
