from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Support-desk answer engine")


class Query(BaseModel):
    text: str
    top_k: int = 5


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


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


def retrieve(query: str, index, k: int = 5) -> list[dict]:
    """Hybrid retrieval: dense candidates merged with keyword hits by reciprocal rank fusion."""
    dense = index.dense_search(query, k=30)
    sparse = index.bm25_search(query, k=30)
    scores: dict[str, float] = {}
    for rank, doc in enumerate(dense):
        scores[doc["id"]] = scores.get(doc["id"], 0) + 1 / (60 + rank)
    for rank, doc in enumerate(sparse):
        scores[doc["id"]] = scores.get(doc["id"], 0) + 1 / (60 + rank)
    ranked = sorted(scores, key=scores.get, reverse=True)[:k]
    return [index.get(doc_id) for doc_id in ranked]


import psycopg
from pgvector.psycopg import register_vector


def nearest(conn: psycopg.Connection, embedding, k: int = 8):
    register_vector(conn)
    return conn.execute(
        "select id, body from chunks order by embedding <=> %s limit %s", (embedding, k)
    ).fetchall()
