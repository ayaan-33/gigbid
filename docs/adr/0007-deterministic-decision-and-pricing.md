# ADR 0007: Deterministic decision, pricing and Fit Matcher

**Status:** accepted

## Decision
- The **skip / watch / bid decision** and the **Pricing Strategist** are rules over typed
  hand-offs, with thresholds in config.
- The **Fit Matcher** scores evidence with retrieval plus a cross-encoder, not an LLM.
- **LLMs are used where language matters:** job analysis, risk explanation, writing, critique,
  compliance and conversations.

## Why
- **Auditable:** every reason appears in the UI.
- **Cheap:** a skipped job costs about 3k tokens, not about 15k.
- **Stable:** results are reproducible in CI.
- **Absorbs policy changes:** a policy or cost change is a config edit.
- **Safe:** the Risk Assessor keeps a rule floor, so hard scam signals can't be "explained away" by
  an LLM.

## Trade-off
Rules miss nuance. The failure analysis in the report lists the misses (for example, implied
requirements with weak evidence scores).
