# Your remaining tasks (in order)

Everything else is built and measured. These need *you*: your accounts, your judgement or your
voice. Times are estimates.

## 1. Label 30 proposals for judge calibration (about 20 minutes)

The LLM judge has already scored them. Your labels let us report Cohen's kappa (required by B4).

```bash
cd "/Users/ayaan/Documents/Agentic AI /Assignment 2/gigbid"
```
```bash
uv run python -m evals.runners.judge label
```

Read each job and proposal, then type 1–5 for "as the client, would I reply?" (5 = definitely).
Type `q` to pause; progress is saved, so run the same command again to continue.

When all 30 are done:
```bash
uv run python -m evals.runners.judge kappa
```

## 2. Commit and push to GitHub (about 10 minutes)

The repo is local only so far.

1. Commit everything (this stops if a secret is staged):
   ```bash
   cd "/Users/ayaan/Documents/Agentic AI /Assignment 2/gigbid" && git add -A && if git status --short | grep -E '(^| )\.env$|data/raw/|datasets/hidden/|gigsim_seed_hidden/|inspector_url'; then echo "STOP: sensitive file staged"; else git commit -m "Evals, R&D studies, deploy kit, docs, report"; fi
   ```
2. Create a **private** GitHub repo and push. This uses the `gh` CLI, which is already installed;
   if asked, run `gh auth login` first and choose GitHub.com → HTTPS → Login with a web browser:
   ```bash
   gh repo create gigbid --private --source=. --remote=origin --push
   ```
3. **Before you submit**, make it public (the assignment requires a public repo):
   ```bash
   gh repo edit --visibility public --accept-visibility-change-consequences
   ```
4. Turn on GitHub Actions if asked: open the repo → **Actions** tab → **I understand my workflows,
   enable them**. CI runs lint, tests, Playwright, Docker builds, gitleaks and the smoke eval.

## 3. Go live (about 5 minutes)

Run `./scripts/deploy/live_local.sh` and copy the `LIVE:` URL it prints. Keep the Mac on and awake. (Oracle VM alternative below.)

### Oracle Cloud free VM alternative (about 45 minutes)

Follow `docs/DEPLOY.md` step by step: create the VM, open ports 80/443, run `setup_vm.sh`, fill
`.env`, then `docker compose up`.

Then open `https://<DOMAIN>/panel` once to check it loads. You'll share that link with classmates
in step 5.

## 4. Make 3–4 Langfuse traces public (about 5 minutes)

1. Open https://cloud.langfuse.com, then your project → **Tracing / Sessions**.
2. Open these sessions, using the thread ids below, or run fresh ones on the deployed site:
   - **Skipped scam:** `bid-u_review-job_00044-acb34b`
   - **Approved proposal:** `bid-u_review-job_00154-c38c14`
   - **Critic loop** and **crash and resume:** the ids are listed at the end of my final message
     (`docs/TRACES.md`).
3. For each one, click **Share** (top right) → **Public**, then copy the link.
4. Paste the 4 links into `README.md` under **Public traces** (replace the `<langfuse link>`
   placeholders) and commit.

## 5. Blind classmate panel (about 5 minutes for you, plus your classmates' time)

Send classmates this message, with your deployed URL:

> Could you help with my AI course project? Open https://<DOMAIN>/panel, enter any nickname, and for 24 pairs pick the proposal you'd reply to as a client (about 10 min). Thanks!

Results appear live at `https://<DOMAIN>/api/panel/results`. Before writing the final report
numbers, save them:
```bash
curl -s https://<DOMAIN>/api/panel/results > evals/results/panel_results.json
```

## 6. Connect your Upwork account in live mode (optional, about 10 minutes)

1. Sign in to the deployed site, then go to **Settings → Connect Upwork**.
2. Upwork's OAuth page opens. Sign in and **Allow**.
3. You come back to Settings showing "connected". The inbox can now scout Upwork via the official
   MCP server.
4. **GigBid only creates drafts.** Nothing is sent unless you confirm it on Upwork itself.
5. If Upwork rejects the OAuth client (for example, their MCP server needs app approval), that's
   fine: the adapter is built and contract-tested. The report states the limitation.

## 7. Publish the Portfolio MCP server to PyPI (about 10 minutes)

1. Create a free account at https://pypi.org/account/register/ and verify your email.
2. Go to **Account settings → API tokens → Add API token**, with scope "Entire account" (for the
   first upload). Copy it; it starts with `pypi-`.
3. Build and upload. Paste the token when asked; it isn't saved:
   ```bash
   cd "/Users/ayaan/Documents/Agentic AI /Assignment 2/gigbid/packaging/portfolio-mcp" && ./build.sh && uv publish --token "$(read -rs -p 'PyPI token: ' T; echo $T)"
   ```
4. Check it works: `uvx ayaan33-gigbid-portfolio-mcp --help`, or see https://pypi.org/project/ayaan33-gigbid-portfolio-mcp/.

## 8. Post the technical write-up (about 15 minutes)

`docs/writeup/WRITEUP.md` is a finished draft of about 1,500 words. Copy it into a LinkedIn
article (**Write article**) or onto Medium, and publish. Copy the URL into `README.md` and your
submission.

## 9. Record the 3-minute demo (about 45 minutes, including retakes)

Follow `docs/DEMO_SCRIPT.md`. It has the shot list and word-for-word narration timed to 3:00.
Upload it as **Unlisted** on YouTube, then put the link in `README.md`.

## 10. Submit on Google Classroom

Attach or link the following:
- [ ] the deployed URL (`https://<DOMAIN>`);
- [ ] the **reviewer login in a private comment**: `REVIEWER_EMAIL` plus the `REVIEWER_PASSWORD`
      from the VM's `.env`;
- [ ] the public GitHub repo link (made public in step 2.3);
- [ ] the R&D report PDF: `docs/report/GigBid_RD_Report.pdf` (rebuild after the kappa and panel
      results with `uv run python -m scripts.make_readme_tables && uv run python -m scripts.build_report`);
- [ ] the 3-minute demo video link;
- [ ] the Portfolio MCP link (PyPI) and the write-up link.
