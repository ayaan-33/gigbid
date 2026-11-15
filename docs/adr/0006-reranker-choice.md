# ADR 0006: Reranker, MiniLM-L6 rather than bge-reranker-v2-m3

**Status:** accepted · **Evidence:** `evals/results/reranker_bench.json`

On 20 jobs with identical candidates on CPU:

| Reranker | Recall@5 | p95 / job | ms / pair |
|---|---|---|---|
| ms-marco-MiniLM-L-6 | 0.343 | 1.0 s | 13 |
| jina-reranker-v1-turbo | 0.293 | 1.3 s | 17 |
| bge-reranker-v2-m3-int8 | 0.363 | 10.6 s | 137 |

bge-reranker-v2-m3 is only 0.02 better and 10× slower. That would break the 25 s per-job latency
budget on a free ARM VM, so MiniLM-L6 ships. Whether reranking stays in the shipped pipeline at all
is decided by the ablation (ADR 0004).
