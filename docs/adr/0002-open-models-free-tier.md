# ADR 0002: Open-weight models only, hosted free tier for the deployment

**Status:** accepted

## Context
The deployed link must run on the open profile. Free hosts have no GPU. No paid APIs may be used
in this project.

## Decision
| Profile | Where | Small tier | Large tier | Fallback |
|---|---|---|---|---|
| `open` (deployed) | Groq free tier | `openai/gpt-oss-20b` | `openai/gpt-oss-120b` | `qwen/qwen3.8-27b` (small), `gpt-oss-20b` (large) |
| `open_local` | Ollama on an M3 laptop | `qwen3:4b` | `qwen3:4b` | `qwen3:4b` |

- **Embeddings:** `nomic-embed-text-v1.5`, on CPU via fastembed, in both profiles.
- **Reranker:** chosen by benchmark (ADR 0006).
- **Injection guard:** Llama Prompt Guard 2 (86M) on Groq.
- **Routing:** set per node in config. Cheap, frequent nodes use the small tier; the Writer, Critic
  and Client Liaison use the large tier.

## Consequences
- **Free-tier limits:** about 8k tokens per minute and about 200k tokens per day per model.
  - A client-side token pacer, honouring retry-after hints, prevents 429 storms.
  - Heavy evals run on subsets or on the local profile. The report states this.
- **Reported cost** uses Groq list prices. Actual spend is $0.
- **The local qwen3:4b is slow** (about 13 tokens/s) and leaks reasoning text. It's fine for
  experiments, but not used in the deployment.
