"""Code fragments used to build SYNTHETIC persona repos. Skills show up through imports and
idioms (so a repo with a vague README is still provably relevant from its code)."""

PY = {
    "FastAPI": ("fastapi", '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="{title}")


class Query(BaseModel):
    text: str
    top_k: int = 5


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
'''),
    "RAG": ("", '''def retrieve(query: str, index, k: int = 5) -> list[dict]:
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
'''),
    "Vector DB": ("psycopg[binary]\npgvector", '''import psycopg
from pgvector.psycopg import register_vector


def nearest(conn: psycopg.Connection, embedding, k: int = 8):
    register_vector(conn)
    return conn.execute(
        "select id, body from chunks order by embedding <=> %s limit %s", (embedding, k)
    ).fetchall()
'''),
    "LLM": ("openai", '''from openai import OpenAI

client = OpenAI()

SYSTEM = "Answer only from the provided context. If the context is insufficient, say so."


def answer(question: str, context: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": f"Context:\\n{context}\\n\\nQuestion: {question}"}],
    )
    return resp.choices[0].message.content
'''),
    "LangChain": ("langgraph\nlangchain-core", '''from typing import TypedDict

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
'''),
    "scikit-learn": ("scikit-learn", '''from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_predict


def compare_models(X, y):
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    models = {
        "logreg": LogisticRegression(max_iter=2000, class_weight="balanced"),
        "rf": RandomForestClassifier(n_estimators=400, class_weight="balanced_subsample"),
    }
    out = {}
    for name, model in models.items():
        proba = cross_val_predict(model, X, y, cv=cv, method="predict_proba")[:, 1]
        out[name] = average_precision_score(y, proba)
        print(name, classification_report(y, proba > 0.5))
    return out
'''),
    "XGBoost": ("xgboost", '''import xgboost as xgb


def train_gbm(X_train, y_train, X_val, y_val):
    model = xgb.XGBClassifier(
        n_estimators=600, max_depth=5, learning_rate=0.05, subsample=0.8,
        scale_pos_weight=(len(y_train) - y_train.sum()) / y_train.sum(), eval_metric="aucpr",
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    return model
'''),
    "pandas": ("pandas", '''import pandas as pd


def build_features(events: pd.DataFrame) -> pd.DataFrame:
    events["month"] = events["ts"].dt.to_period("M")
    agg = events.groupby(["customer_id", "month"]).agg(
        sessions=("session_id", "nunique"), spend=("amount", "sum")
    )
    return agg.groupby(level=0).tail(3).groupby(level=0).mean()
'''),
    "SQL": ("", '''MONTHLY_REVENUE = """
select date_trunc('month', o.created_at) as month,
       c.region,
       sum(o.amount) as revenue,
       count(distinct o.customer_id) as customers,
       sum(o.amount) / nullif(count(distinct o.customer_id), 0) as arpu
from orders o
join customers c on c.id = o.customer_id
where o.status = 'paid'
group by 1, 2
order by 1, 2
"""
'''),
    "NLP": ("spacy", '''import re

import spacy

nlp = spacy.load("en_core_web_sm")


def normalise(text: str) -> str:
    text = re.sub(r"\\s+", " ", text)
    return " ".join(t.lemma_.lower() for t in nlp(text) if not t.is_stop)
'''),
    "Hugging Face": ("transformers\ndatasets", '''from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments

MODEL = "distilbert-base-uncased"
tokenizer = AutoTokenizer.from_pretrained(MODEL)


def make_trainer(train_ds, eval_ds, num_labels: int) -> Trainer:
    model = AutoModelForSequenceClassification.from_pretrained(MODEL, num_labels=num_labels)
    args = TrainingArguments("out", per_device_train_batch_size=16, num_train_epochs=3,
                             evaluation_strategy="epoch", learning_rate=3e-5)
    return Trainer(model=model, args=args, train_dataset=train_ds, eval_dataset=eval_ds)
'''),
    "Fine-tuning": ("peft", '''from peft import LoraConfig, get_peft_model


def add_lora(model):
    config = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules=["q_lin", "v_lin"])
    return get_peft_model(model, config)
'''),
    "PyTorch": ("torch\ntorchvision", '''import torch
from torch import nn


class Head(nn.Module):
    def __init__(self, dim: int, n_classes: int):
        super().__init__()
        self.net = nn.Sequential(nn.Dropout(0.2), nn.Linear(dim, n_classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)
'''),
    "Computer Vision": ("opencv-python\ntimm", '''import cv2
import timm

model = timm.create_model("efficientnet_b0", pretrained=True, num_classes=2)


def preprocess(path: str):
    img = cv2.imread(path)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return cv2.resize(img, (224, 224))
'''),
    "MLOps": ("mlflow", '''import mlflow


def register(model, name: str, metrics: dict) -> None:
    with mlflow.start_run():
        mlflow.log_metrics(metrics)
        mlflow.sklearn.log_model(model, "model", registered_model_name=name)
'''),
    "Time Series": ("statsmodels", '''from statsmodels.tsa.holtwinters import ExponentialSmoothing


def seasonal_baseline(series, periods: int = 52):
    model = ExponentialSmoothing(series, trend="add", seasonal="add", seasonal_periods=periods)
    return model.fit().forecast(12)
'''),
    "Speech": ("openai-whisper", '''import whisper

model = whisper.load_model("small")


def transcribe(path: str) -> str:
    return model.transcribe(path, fp16=False)["text"]
'''),
    "Statistics": ("scipy", '''from scipy import stats


def two_proportion_test(conv_a: int, n_a: int, conv_b: int, n_b: int) -> float:
    table = [[conv_a, n_a - conv_a], [conv_b, n_b - conv_b]]
    _, p, _, _ = stats.chi2_contingency(table)
    return p
'''),
    "Recommendation Systems": ("implicit", '''import implicit
from scipy.sparse import csr_matrix


def fit_als(user_item: csr_matrix):
    model = implicit.als.AlternatingLeastSquares(factors=64, regularization=0.05, iterations=20)
    model.fit(user_item)
    return model
'''),
    "Chatbot": ("", '''FLOWS = {
    "reset_password": ["Open Settings", "Tap Security", "Choose Reset password"],
    "change_plan": ["Open Billing", "Pick a plan", "Confirm"],
}


def respond(intent: str, fallback) -> str:
    if intent in FLOWS:
        return "\\n".join(f"{i + 1}. {s}" for i, s in enumerate(FLOWS[intent]))
    return fallback(intent)
'''),
    "Docker": ("", ""),
    "Airflow": ("apache-airflow", '''from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

with DAG("daily_kpis", start_date=datetime(2025, 1, 1), schedule="0 6 * * *", catchup=False) as dag:
    extract = PythonOperator(task_id="extract", python_callable=lambda: None, retries=3)
    publish = PythonOperator(task_id="publish", python_callable=lambda: None)
    extract >> publish
'''),
    "ETL": ("", '''def validate(df) -> list[str]:
    problems = []
    if df["id"].duplicated().any():
        problems.append("duplicate ids")
    if df["amount"].lt(0).any():
        problems.append("negative amounts")
    return problems
'''),
    "Celery": ("celery", '''from celery import Celery

app = Celery("tasks", broker="redis://localhost:6379/0")


@app.task(bind=True, max_retries=3, acks_late=True)
def process(self, item_id: str) -> str:
    return item_id
'''),
    "Django": ("django\ndjangorestframework", '''from django.db import models


class Deal(models.Model):
    account = models.ForeignKey("Account", on_delete=models.CASCADE)
    stage = models.CharField(max_length=32, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)
'''),
    "PostgreSQL": ("psycopg[binary]", '''TENANT_POLICY = """
alter table projects enable row level security;
create policy tenant_isolation on projects
  using (tenant_id = current_setting('app.tenant_id')::uuid);
"""
'''),
    "Redis": ("redis", '''import redis

r = redis.Redis.from_url("redis://localhost:6379/0")


def cached(key: str, ttl: int, compute):
    if (hit := r.get(key)) is not None:
        return hit
    value = compute()
    r.setex(key, ttl, value)
    return value
'''),
    "AWS": ("boto3", '''import boto3

s3 = boto3.client("s3")


def presign_upload(bucket: str, key: str) -> str:
    return s3.generate_presigned_url("put_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=900)
'''),
    "Testing": ("pytest", '''import pytest


@pytest.mark.parametrize("value,expected", [(0, 0), (10, 10)])
def test_identity(value, expected):
    assert value == expected
'''),
    "Python": ("", ""),
    "Data Visualization": ("plotly", '''import plotly.express as px


def trend_chart(df):
    return px.line(df, x="week", y="value", color="segment", markers=True)
'''),
    "dbt": ("", ""),
    "Snowflake": ("snowflake-connector-python", '''import snowflake.connector


def run(query: str):
    with snowflake.connector.connect(account="xy12345", warehouse="ANALYTICS") as conn:
        return conn.cursor().execute(query).fetchall()
'''),
    "Google Analytics": ("google-analytics-data", '''from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest


def sessions_by_channel(property_id: str):
    client = BetaAnalyticsDataClient()
    req = RunReportRequest(property=f"properties/{property_id}",
                           dimensions=[Dimension(name="sessionDefaultChannelGroup")],
                           metrics=[Metric(name="sessions"), Metric(name="conversions")],
                           date_ranges=[DateRange(start_date="28daysAgo", end_date="today")])
    return client.run_report(req)
'''),
    "Excel": ("openpyxl", '''from openpyxl import load_workbook


def read_sheet(path: str, sheet: str):
    wb = load_workbook(path, data_only=True)
    return [[c.value for c in row] for row in wb[sheet].iter_rows(min_row=2)]
'''),
    "R": ("", ""),
}

TS = {
    "React": '''import { useMemo, useState } from "react";

export function DataTable<T extends { id: string }>({ rows, columns }: { rows: T[]; columns: (keyof T)[] }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => rows.filter((r) => JSON.stringify(r).toLowerCase().includes(query.toLowerCase())),
    [rows, query],
  );
  return (
    <div>
      <input aria-label="Search" value={query} onChange={(e) => setQuery(e.target.value)} />
      <table>
        <tbody>
          {filtered.map((r) => (
            <tr key={r.id}>{columns.map((c) => <td key={String(c)}>{String(r[c])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
''',
    "Next.js": '''import { notFound } from "next/navigation";

export const revalidate = 300;

export default async function Page({ params }: { params: { slug: string } }) {
  const res = await fetch(`${process.env.API_URL}/items/${params.slug}`, { next: { revalidate } });
  if (!res.ok) notFound();
  const item = await res.json();
  return <main><h1>{item.title}</h1></main>;
}
''',
    "Node.js": '''import express from "express";

const app = express();
app.use(express.json());

app.get("/health", (_req, res) => res.json({ ok: true }));

app.listen(process.env.PORT ?? 3000);
''',
    "Stripe": '''import Stripe from "stripe";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

export async function handleWebhook(rawBody: Buffer, signature: string) {
  const event = stripe.webhooks.constructEvent(rawBody, signature, process.env.STRIPE_WEBHOOK_SECRET!);
  switch (event.type) {
    case "invoice.payment_failed":
      return markPastDue(event.data.object.customer as string);
    case "customer.subscription.updated":
      return syncSubscription(event.data.object);
  }
}
declare function markPastDue(id: string): Promise<void>;
declare function syncSubscription(s: unknown): Promise<void>;
''',
    "WebSockets": '''import { Server } from "socket.io";
import { createAdapter } from "@socket.io/redis-adapter";
import { createClient } from "redis";

const pub = createClient({ url: process.env.REDIS_URL });
const sub = pub.duplicate();
await Promise.all([pub.connect(), sub.connect()]);

const io = new Server(3001, { cors: { origin: "*" } });
io.adapter(createAdapter(pub, sub));
io.on("connection", (socket) => {
  socket.on("message", (room: string, text: string) => io.to(room).emit("message", { text, at: Date.now() }));
});
''',
    "GraphQL": '''import { ApolloServer } from "@apollo/server";
import DataLoader from "dataloader";

const typeDefs = `#graphql
  type Order { id: ID!, total: Float!, customer: Customer! }
  type Customer { id: ID!, name: String! }
  type Query { orders(limit: Int = 20): [Order!]! }
`;

export const customerLoader = new DataLoader(async (ids: readonly string[]) => fetchCustomers(ids));
declare function fetchCustomers(ids: readonly string[]): Promise<{ id: string; name: string }[]>;
export const server = new ApolloServer({ typeDefs, resolvers: {} });
''',
    "TypeScript": '''export type Result<T> = { ok: true; value: T } | { ok: false; error: string };

export function assertNever(x: never): never {
  throw new Error(`unexpected: ${String(x)}`);
}
''',
    "Supabase": '''import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!);

export async function myEvents() {
  const { data, error } = await supabase.from("events").select("*").order("starts_at");
  if (error) throw error;
  return data;
}
''',
    "Vue": '''<script setup lang="ts">
import { ref, onMounted } from "vue";
const readings = ref<{ id: string; value: number }[]>([]);
onMounted(() => {
  const ws = new WebSocket(import.meta.env.VITE_WS_URL);
  ws.onmessage = (e) => readings.value.unshift(JSON.parse(e.data));
});
</script>
<template><ul><li v-for="r in readings" :key="r.id">{{ r.value }}</li></ul></template>
''',
    "Tailwind CSS": '''export function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 p-6 shadow-sm dark:border-slate-800">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <div className="mt-3 text-sm text-slate-600">{children}</div>
    </section>
  );
}
''',
    "Shopify": '''const QUERY = `#graphql
  query Product($handle: String!) {
    product(handle: $handle) { id title variants(first: 10) { nodes { id price { amount } } } }
  }
`;

export async function getProduct(handle: string) {
  const res = await fetch(`https://${process.env.SHOP}/api/2024-07/graphql.json`, {
    method: "POST",
    headers: { "X-Shopify-Storefront-Access-Token": process.env.STOREFRONT_TOKEN!, "Content-Type": "application/json" },
    body: JSON.stringify({ query: QUERY, variables: { handle } }),
  });
  return (await res.json()).data.product;
}
''',
}

SQL_DBT = '''{{ config(materialized="table") }}

with orders as (
    select * from {{ ref("stg_orders") }}
),
payments as (
    select order_id, sum(amount) as paid from {{ ref("stg_payments") }} group by 1
)
select o.order_id, o.customer_id, o.ordered_at, coalesce(p.paid, 0) as revenue
from orders o
left join payments p using (order_id)
'''

DOCKERFILE = '''FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
'''

DAX = '''Revenue YoY % =
VAR Curr = [Revenue]
VAR Prev = CALCULATE([Revenue], SAMEPERIODLASTYEAR('Date'[Date]))
RETURN DIVIDE(Curr - Prev, Prev)

Target Attainment = DIVIDE([Revenue], [Target])
'''
