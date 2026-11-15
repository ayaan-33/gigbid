# Change request: the GigSim "platform policy update" (v2)

GigSim was not provided, so the policy update was written into our own simulator (`gigsim/policy.py`,
frozen by checksum in CI). It's released through `POST /admin/policy {"version": 2}`.

## What changed on the platform
1. **Connects surcharge:** jobs that already have 20 or more proposals cost **+4 Connects**.
2. **AI-assistance disclosure:** every proposal must contain a disclosure line. Submissions without
   one are rejected with `422 policy_violation: missing_ai_disclosure`.

## What GigBid had to change

| Change | Where | Lines |
|---|---|---|
| `policy.version: 2` | `agent/config.yaml` | 1 |
| `policy.require_ai_disclosure: true` | `agent/config.yaml` | 1 |

Nothing else changed: no prompt edits and no node code.
- **Writer:** reads `policy.require_ai_disclosure` and adds the rule to its prompt (rendered from
  `agent/prompts/writer.md`).
- **Compliance Guard:** enforces it. If the line is missing, it appends the disclosure and records
  a `rewritten` violation that is visible in the studio.
- **Surcharge:** needs no GigBid change, because pricing uses the marketplace's own Connects figure
  and the dry-run preview shows the exact cost.

## What it took, honestly

| Step | Time |
|---|---|
| Read the new policy (`GET /v1/policy`) and decide what it affects | ~3 min |
| Two config edits | ~1 min |
| Write the regression tests (`tests/unit/test_change_request.py`) | ~15 min |
| **One real bug the change request exposed:** pricing would have added the surcharge on top of the marketplace's already-surcharged figure (double counting). Fixed in `connects_cost()` by making the marketplace's figure authoritative. | ~10 min |
| Run the tests (2 change-request + 11 graph tests) | ~4 min |

**About 30 minutes in total, including tests and the bug fix.** The policy itself took 2 config
lines.

## What we added so the next change is cheaper: policy-drift detection
The Pricing Strategist calls `get_policy` on every job. If the marketplace's policy version is
newer than `policy.version` in config, the price rationale shown to the user says:

> WARNING: marketplace policy is v2 but GigBid is configured for v1 (update agent/config.yaml -> policy).

So the next policy update is noticed on the first job analysed after it's released, not on the
first rejected submission.

## Evidence
`tests/unit/test_change_request.py`:
- **Before the config change (config v1, platform v2):** the drift warning is shown, the cost is
  16 Connects (marketplace figure, not double-counted), and the marketplace rejects the proposal.
- **After the config change:** the draft contains "Drafted with AI assistance and reviewed by me.",
  there's no drift warning, and the proposal is **submitted**, spending 16 Connects.

## What this says about the design
- **Rules that change belong in config, not code.** Thresholds, policy flags, budgets and models
  all live in `agent/config.yaml`. The prompts read those flags; nothing is hard-coded.
- **Cost belongs to the marketplace, not to us.** Making the marketplace's figure authoritative
  removed a whole class of bugs.
- **Defence in depth caught the gap.** Even before the config change, nothing non-compliant was
  sent: GigSim rejected it, and the user saw why.
