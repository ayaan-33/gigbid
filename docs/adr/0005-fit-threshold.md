# ADR 0005: Fit threshold 0.25, chosen by a sweep on the dev set

**Status:** accepted · **Evidence:** `evals/results/decision_eval_dev_rules.json`,
`evals/results/threshold_sweep.json`

## Context
The first 600-job dev decision eval (rules-only risk) ran with `minimum_fit_score: 0.55`. It was
perfectly precise but far too conservative:
- bid/skip F1 **0.340**;
- precision 1.00;
- recall 0.205.

GigBid would have skipped about 80% of the jobs it should bid on. The Fit Matcher's score is
`0.6 × evidence coverage + 0.4 × skill coverage`, where evidence strength comes from cross-encoder
probabilities. Those probabilities are compressed on this corpus, so a strong match scores about
0.3–0.7, not about 0.8–1.0.

## Decision
I re-applied the deterministic decision rule to the stored per-job rows for thresholds from 0.20 to
0.60. The sweep reproduces the eval exactly at 0.55 (F1 0.340), which validates it.

| Threshold | F1 | Precision | Recall |
|---|---|---|---|
| 0.20 | 0.940 | 0.899 | 0.986 |
| **0.25** | **0.944** | **0.948** | **0.941** |
| 0.30 | 0.909 | 0.972 | 0.854 |
| 0.40 | 0.737 | 1.000 | 0.583 |
| 0.55 | 0.340 | 1.000 | 0.205 |

So `minimum_fit_score: 0.25` and `watch_fit_score: 0.18`.

## Consequences
- **Tuning risk:** the threshold was tuned on dev, so the **hidden set** run checks whether it
  generalises (`decision_eval_hidden_rules.json`).
- **Users can override it:** a stricter user can raise it in config. It's in the viva live-change
  list.
- **Precision is protected elsewhere:** scams, low budgets and high risk are filtered by separate
  rules before fit is considered, so lowering the fit threshold doesn't let scams through.
