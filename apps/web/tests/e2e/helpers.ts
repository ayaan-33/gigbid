import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const PASSWORD = "e2e-password-123";

export function uniqueEmail(tag: string) {
  return `e2e-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/** Register + onboard a fresh user through the API (each test is isolated). */
export async function newUser(request: APIRequestContext, tag: string, search = "machine learning") {
  const email = uniqueEmail(tag);
  const r = await request.post("/api/auth/register", { data: { email, password: PASSWORD, name: `E2E ${tag}` } });
  expect(r.ok()).toBeTruthy();
  const o = await request.post("/api/auth/onboarding", {
    data: { persona: "ai_ml_engineer", hourly_rate: 55, fixed_floor: 300, weekly_connects_budget: 200, marketplace_mode: "gigsim", saved_search: search, category: "ai_ml" },
  });
  expect(o.ok()).toBeTruthy();
  return email;
}

/** Run the saved searches and wait until at least one proposal is waiting for approval. */
export async function waitForDraft(request: APIRequestContext): Promise<string> {
  await request.post("/api/jobs/scout");
  const deadline = Date.now() + 150_000;
  while (Date.now() < deadline) {
    const r = await request.get("/api/approvals");
    if (r.ok()) {
      const list = (await r.json()) as { thread_id: string; payload: { kind: string } }[];
      const p = list.find((x) => x.payload.kind === "proposal");
      if (p) return p.thread_id;
    }
    await new Promise((res) => setTimeout(res, 2000));
  }
  throw new Error("no proposal reached the approval gate in time");
}

export async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/inbox/);
}

export async function threadStatus(request: APIRequestContext, threadId: string, want: string[], timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  let last = "";
  while (Date.now() < deadline) {
    const r = await request.get(`/api/runs/${threadId}`);
    if (r.ok()) {
      last = (await r.json()).status;
      if (want.includes(last)) return last;
    }
    await new Promise((res) => setTimeout(res, 1500));
  }
  throw new Error(`thread ${threadId} ended in ${last}, wanted ${want.join("/")}`);
}
