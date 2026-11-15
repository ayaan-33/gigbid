# ADR 0004: Ship V5 multi-vector retrieval without the cross-encoder

**Status:** accepted · **Evidence:** `evals/results/rag_retrieval.json` (full dev set, 288 bid
jobs), `evals/results/ablation.json` (30 bid jobs per persona), `rag_subset_v6.json`,
`rag_subset_v7.json`, `reranker_bench.json`

## Results that decided it

**Full set, Recall@5 / nDCG@10:**

| Variant | Recall@5 | nDCG@10 |
|---|---|---|
| V0 | 0.108 | 0.108 |
| V1 | 0.187 | 0.197 |
| V2 | 0.196 | 0.204 |
| V3 | 0.220 | 0.222 |
| V4 | 0.214 | 0.234 |
| **V5** | **0.323** | **0.322** |
| V8 | 0.145 | 0.145 |

**Ablation of V5** (removing or adding one component; 30 jobs per persona):

| Change | Recall@5 | nDCG@10 | Recall@5, ≥4 requirements |
|---|---|---|---|
| best V5 | 0.382 | 0.364 | 0.477 |
| − multi-vector | 0.240 | 0.234 | 0.269 |
| **− rerank** | **0.404** | **0.406** | **0.515** |
| − hybrid | 0.268 | 0.289 | 0.408 |
| − decomposition | 0.311 | 0.306 | 0.392 |
| + outcome boost | 0.249 | 0.239 | 0.392 |
| + diversify | 0.382 | 0.364 | 0.477 |

## Decision
`rag.variant: v5_norerank`: requirement decomposition + hybrid BM25/dense RRF + multi-vector
projects, with **no cross-encoder**.

## Why
- **Removing the reranker improved every metric.** Once retrieval returns whole projects, RRF's
  agreement across views and lists beats a small pairwise cross-encoder that has never seen code
  mixed with prose. It also saves about 3 s of CPU per job at p95, inside the 25 s budget on a free
  ARM VM.
- **Multi-vector, hybrid and decomposition each carry real weight.** Removing any one of them
  costs 0.07–0.14 Recall@5.
- **Outcome boosting hurts retrieval** (0.382 → 0.249). It promotes won proposals, which are
  phrasing, over case studies and repos, which are proof. Outcome knowledge is still used, but in
  outcome *memory*, which chooses a writing strategy, not in evidence ranking.
- **HyDE (V7) and contextual headers (V6) didn't help** on matched subsets (0.216 vs 0.240, and
  0.199 vs 0.211), so neither ships.
- **V8 is used for refusal, not recall:** it marks requirements that have no evidence, and the
  Writer is told not to claim them. See `v8_unsupported_requirement_share` in the ablation file.

## Note
The cross-encoder is still used in the **Fit Matcher** to grade evidence *strength* (a calibrated
probability), which is a different job from ranking.
