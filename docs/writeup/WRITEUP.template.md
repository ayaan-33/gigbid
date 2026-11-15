# My retrieval upgrades didn't stack. The reranker that helped on its own made things worse once retrieval understood projects.

*A technical write-up from building GigBid, a multi-agent freelancer copilot. Not a tutorial: this
is about one result I didn't expect, and what it changed in how I evaluate RAG.*

---

I spent three weeks building a system that reads freelance job posts and writes proposals backed by
real portfolio evidence. The whole product depends on one step: given a job that asks for five
things, find the five pieces of the freelancer's past work that prove they can do them. If
retrieval gets this wrong, the writer either hallucinates experience (my claim verifier then
deletes it) or writes something generic that clients ignore.

So I did what every RAG tutorial suggests. I started with a naive baseline and stacked the
well-known upgrades on top: query decomposition, hybrid BM25 + dense search, a cross-encoder
reranker, outcome-aware boosting, multi-vector indexing, contextual chunk headers, HyDE and a
corrective retrieval loop. Each one is a flag in one configurable pipeline, so I could switch any
of them off and measure.

The surprise: **the improvements were not additive.** The reranker improved recall on its own,
then made it *worse* once the pipeline started reasoning about projects instead of chunks. Two
celebrated techniques, HyDE and contextual chunk headers, didn't help at all.

## The corpus was built to break naive RAG

The evaluation used three synthetic freelancer portfolios: an AI/ML engineer, a full-stack
developer and a data analyst. Each had 18–20 case studies, 9–10 code repositories, client reviews
and 150 past proposals labelled won, replied or ignored. The job posts came from about 107,000 real
Upwork postings on Kaggle. I augmented them with requirements whose correct evidence I knew by
construction.

The corpus is deliberately hostile, the way real portfolios are:
- **Each project has three names:** the case study calls it "Support-desk answer engine", the CV
  says "RAG assistant for customer support", and an old proposal says "help-centre chatbot
  grounded in docs".
- **Some skills are implied, never named.** "Shipped it as a container image so their ops team
  could run it anywhere" is the only evidence of Docker.
- **Half the repositories have useless READMEs** ("Internal utilities and scripts"). Their
  relevance lives only in the code's imports.
- **Past proposals dominate:** 150 per persona, against about 20 case studies, so they crowd the
  top results. Most of them were ignored by clients, so their wording is weak evidence.

The metric was evidence Recall@5, against gold items for 96 bid jobs per persona (288 in total).

## What each upgrade bought

| Variant | Recall@5 |
|---|---|
| V0: whole job post as one dense query, fixed-size chunks | 0.108 |
| V1: one query per extracted requirement, coverage-aware merge | 0.187 |
| V2: + BM25 fused with dense by reciprocal rank fusion | 0.196 |
| V3: + cross-encoder reranker (MiniLM-L6) | 0.220 |
| V4: + boost evidence from proposals that won | 0.214 |
| **V5: + multi-vector projects** | **0.323** |

So far it reads like the textbook. Decomposition is the biggest single jump, because a job asking
for five things gets five chances instead of one blended embedding. Hybrid search helps exact tool
names that embeddings blur ("Celery", "dbt"). The reranker adds a little. V5 is the big win: it
scores a project by its best view (summary, README or code) and then returns that project's case
study, repo and review together. That's how the "useless README" repos finally get found: the code
chunk matches, and the whole project comes back.

## Then I ablated the best pipeline

The standard advice is to take your best pipeline and remove one component at a time. I expected
every removal to hurt. On a 30-jobs-per-persona sample:

{{ABLATION_TABLE}}

**Removing the reranker made it better: Recall@5 rose from 0.382 to 0.404, and nDCG@10 from 0.364
to 0.406.** On jobs with four or more requirements, the case that motivated the whole project, it
rose from 0.477 to 0.515.

Why? The cross-encoder scores a (requirement, chunk) pair *in isolation*. Without multi-vector
grouping, that's exactly what you want: it pushes the one relevant chunk above the noise. With
grouping, the unit of retrieval is a *project*, and a project is relevant if *any* of its views
matches. Reciprocal rank fusion of BM25 and dense ranks naturally rewards a project that shows up
in several views and several lists. The reranker overrides that consensus with a single pairwise
opinion from a small model (MiniLM-L6, 22M parameters) that has never seen code mixed with prose.
It had become a second, weaker judge sitting on top of a better one.

I'd also benchmarked a much larger reranker (bge-reranker-v2-m3). It was only 0.02 better than
MiniLM and ten times slower on CPU: 10.6 s versus 1.0 s at p95 per job, on a free ARM VM with a
25-second budget. So "use a bigger reranker" wasn't a free fix either.

## HyDE and contextual chunk headers: honest nulls

Two famous techniques didn't help on this corpus, even on matched subsets:
- **HyDE**, which writes a hypothetical ideal proposal and retrieves with it, scored 0.216 against
  0.240 for plain V3 on the same 90 jobs. A hypothetical proposal is written in the *generic*
  register of proposals, which is exactly the register of the 150 mostly-ignored past proposals I
  was trying to rank below real proof.
- **Contextual retrieval**, an LLM-written line situating each chunk, scored 0.199 against 0.211.
  The generated headers made chunks more similar to each other ("Case study for a SaaS client
  showing…"), and that blurred the lexical signal BM25 depends on.

Neither is a bad technique. Both were tuned for corpora where the problem is missing context. Mine
had too much of the wrong context.

## Better retrieval didn't always mean better proposals

The product metric isn't recall; it's whether a client replies. GigBid submits proposals to a
simulator whose clients have hidden preferences: must-have skills, a budget ceiling, a dislike of
generic openings.

{{PROPOSAL_PARAGRAPH}}

The gap between retrieval metrics and outcomes is the second lesson. Retrieval decides what the
writer *can* cite. The claim verifier decides what survives. The client cares about the first two
sentences.

## What I changed because of this

1. **I ship V5 without the reranker.** It's more accurate and cheaper, and it removes about 3
   seconds of CPU per job from the latency budget. The decision is recorded in
   `docs/adr/0004-rag-variant.md`, with the ablation file that justifies it.
2. **I ablate every candidate, not just the winner.** Each variant was a flag on one pipeline, so
   the ablation was a single command. Without that structure I would have shipped the reranker,
   because "everyone uses one".
3. **I measure on matched subsets.** HyDE and contextual headers were compared against V3 on
   *exactly* the same jobs. Comparing a subset to a full-set average would have hidden the null.
4. **I keep the negative results in the report.** A well-measured "the reranker hurt, and here's
   why" is more useful to the next person than one more leaderboard number.

The code, data generator, evaluation scripts and every result file are in the repository. Every
number in this post comes from a file in `evals/results/`, and CI fails if a README number doesn't
trace to one.

*Built with LangGraph, the MCP Python SDK, FastAPI, Next.js, Postgres + pgvector, and open-weight
models only (gpt-oss and Qwen3 on Groq's free tier, nomic-embed-text and MiniLM on CPU).*
