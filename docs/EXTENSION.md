# Signature extension: X2, proposal A/B experiments

GigBid can run two proposal **strategies** as a randomised A/B test against GigSim's simulated
clients, and tests whether the difference in reply rate is statistically significant.

## The two arms

| Arm | Strategy instruction given to the Writer (`agent/nodes/proposal.py → STRATEGIES`) |
|---|---|
| **A: evidence_first** | After a one-line restatement of the client's problem, lead with the single most relevant past project and its measured result, then the plan. |
| **B: question_led** | Restate the problem, then ask one sharp clarifying question that shows you understand the hard part, then give the evidence and plan. |

## In the product
- **Assigning arms:** with Settings → Proposal strategy set to **A/B test** (the default), each new
  job gets an arm by a deterministic hash of the job id. The assignment is reproducible and has no
  selection bias.
- **Tracking:** the arm is stored on the thread and the pipeline card.
- **Analytics:** reply and hire rates are shown **by strategy**, next to by-category rates.
- **Outcome memory:** once one arm beats a category's baseline by 10 points or more over at least 5
  outcomes, the promotion rule writes it to outcome memory. After that, the Writer uses the winning
  arm for that category by default. The user can see and delete this in Settings → What GigBid has
  learned.

## Offline experiment (`evals/runners/ab_experiment.py`)
- **Design:** for each fit dev job, the real pipeline writes **one proposal per arm**. That's Fit
  Matcher (MCP), then Writer, then claim verification, then Compliance. Both proposals are submitted
  to GigSim, where the seeded simulated client grades each against its hidden preferences and draws
  reply, interview or hire.
- **Statistics:**
  - **paired McNemar test**, since the same jobs see both arms;
  - **unpaired two-proportion z-test** and **Fisher's exact test**;
  - **95% confidence interval** of the difference;
  - **power analysis:** the number of jobs per arm needed to detect the observed difference with
    80% power at α = 0.05.
- **Run setup (free-tier constraints):** 24 fit jobs (8 per persona) × 2 arms. The writer is
  `qwen/qwen3.8-27b` on Groq's free tier, the same model for both arms. Claim verification and
  Compliance ran in deterministic mode. GigSim used its seeded heuristic grader.

## Results
See `evals/results/ab_experiment.json`. The README and report tables are generated from that file.
The interpretation is written in the report (section 7) once the run completes.

## Limitations
- **The "clients" are our simulator.** The experiment measures which strategy better matches the
  simulated clients' preferences (specificity, personalisation, no generic opening). That's a proxy
  for real clients.
- **The sample is small** (24 jobs per arm), so the test has limited power. The power analysis says
  how many jobs a conclusive test would need.
- **Live use:** the in-product A/B assignment applies unchanged to live Upwork. The outcome events
  there come from scheduled reads of the pipeline.
