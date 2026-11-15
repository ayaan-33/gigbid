# Langfuse traces (E3 / C deliverables)

One trace id per graph thread: it's the Langfuse **session id**, the `X-Trace-Id` sent to every
MCP server, and the `trace_id` in the MCP audit logs. Each node and LLM call shows its tokens,
cost and latency.

| What it shows | Thread / session | Langfuse session |
|---|---|---|
| **Skipped scam**: risk flags `poor_client_history`, `unpaid_work`, `unverified_payment`; the Writer never runs | `bid-u_review-job_00044-acb34b` | https://cloud.langfuse.com/project/cmwg77zqn0119ad0jshvuwwkz/sessions/bid-u_review-job_00044-acb34b |
| **Approved proposal**: parallel analysts → Writer → verifier (3/3 claims supported) → Critic 9/10 → Compliance → approval → submitted (4 Connects) | `bid-u_review-job_00154-c38c14` | https://cloud.langfuse.com/project/cmwg77zqn0119ad0jshvuwwkz/sessions/bid-u_review-job_00154-c38c14 |
| **Critic loop**: round 1 sent back (3/10) → Writer revision → round 2 passed (9/10) | `bid-u_review-job_00145-0483d1` | https://cloud.langfuse.com/project/cmwg77zqn0119ad0jshvuwwkz/sessions/bid-u_review-job_00145-0483d1 |
| **Crash and resume**: the same thread; the API was killed with `kill -9` while the approval was pending, restarted, the approve was clicked twice, and exactly 1 proposal was submitted (6 Connects) | `bid-u_review-job_00145-0483d1` (3 traces: initial run, resume, duplicate resume) | https://cloud.langfuse.com/project/cmwg77zqn0119ad0jshvuwwkz/sessions/bid-u_review-job_00145-0483d1 |
| Dead-letter example (failure analysis #13): an LLM node timed out under free-tier pacing | `bid-u_review-job_00063-e336f0` | https://cloud.langfuse.com/project/cmwg77zqn0119ad0jshvuwwkz/sessions/bid-u_review-job_00063-e336f0 |

All three sessions above are **public**: the links open without a Langfuse login.
