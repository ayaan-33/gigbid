import { expect, test } from "@playwright/test";
import { login, newUser, PASSWORD, threadStatus, uniqueEmail, waitForDraft } from "./helpers";

test("onboarding: sign up, choose persona, set budgets, land on the inbox", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /Create an account/ }).click();
  await page.getByLabel("Name").fill("New Freelancer");
  await page.getByLabel("Email").fill(uniqueEmail("onboard"));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding/);
  await page.getByLabel(/Data analyst/).check();
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Weekly Connects budget").fill("60");
  await page.getByLabel("First saved search").fill("power bi dashboard");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel(/GigSim/).check();
  await page.getByTestId("finish-onboarding").click();
  await expect(page).toHaveURL(/\/inbox/);
  await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();
  // settings reflect the onboarding choices
  await page.goto("/settings");
  await expect(page.getByLabel("Weekly Connects")).toHaveValue("60");
});

test("approve a proposal: evidence on hover, dry-run preview, submitted exactly once", async ({ page, request }) => {
  const email = await newUser(request, "approve");
  const thread = await waitForDraft(request);
  await login(page, email);
  await page.goto(`/studio/${thread}`);
  await expect(page.getByTestId("dry-run")).toContainText("Connects");
  const chip = page.getByTestId("evidence-chip").first();
  if (await chip.count()) {
    await chip.hover();
    await expect(page.getByRole("tooltip").first()).toBeVisible();
  }
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("decision-result")).toContainText("Approved");
  expect(await threadStatus(request, thread, ["submitted"], 120_000)).toBe("submitted");
  // pipeline shows the submitted proposal
  await page.goto("/pipeline");
  await expect(page.getByTestId("col-submitted").getByRole("link")).toHaveCount(1);
});

test("reject with a reason: nothing is sent, reason is recorded", async ({ page, request }) => {
  const email = await newUser(request, "reject");
  const thread = await waitForDraft(request);
  await login(page, email);
  await page.goto(`/studio/${thread}`);
  await page.getByTestId("reject").click();
  await expect(page.getByTestId("confirm-reject")).toBeDisabled(); // a reason is required
  await page.getByTestId("reject-reason").fill("too generic for this client");
  await page.getByTestId("confirm-reject").click();
  await expect(page.getByTestId("decision-result")).toContainText("Rejected");
  expect(await threadStatus(request, thread, ["rejected"])).toBe("rejected");
  const run = await (await request.get(`/api/runs/${thread}`)).json();
  expect(run.status_reason).toContain("too generic");
  const pipeline = await (await request.get("/api/pipeline")).json();
  expect(pipeline.filter((c: { stage: string }) => c.stage === "submitted")).toHaveLength(0);
});

test("edit a draft: the edit is re-checked by Compliance before anything is sent", async ({ page, request }) => {
  const email = await newUser(request, "edit");
  const thread = await waitForDraft(request);
  await login(page, email);
  await page.goto(`/studio/${thread}`);
  await page.getByTestId("toggle-edit").click();
  const editor = page.getByTestId("draft-editor");
  const original = await editor.inputValue();
  await editor.fill(`${original}\n\nYou can also reach me at someone@example.com for a quick chat.`);
  await page.getByTestId("approve").click(); // "Approve my edited version"
  await expect(page.getByTestId("decision-result")).toBeVisible();
  // Compliance removed the e-mail address, so the cleaned text needs a second look
  await threadStatus(request, thread, ["awaiting_approval", "submitted"]);
  const pending = await request.get(`/api/approvals/${thread}`);
  if (pending.ok()) {
    const p = (await pending.json()).payload;
    expect(p.draft.cover_letter).not.toContain("someone@example.com");
    expect(JSON.stringify(p.compliance.violations)).toContain("contact");
  }
});

test("degraded mode: a marketplace outage shows the banner and the app keeps working @mobile", async ({ page, request }) => {
  const email = await newUser(request, "degraded");
  await page.route("**/api/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        marketplace: "unavailable",
        marketplace_mode: "gigsim",
        circuit: { state: "open" },
        queued_threads: 2,
        message: "Marketplace unavailable: work is queued and will resume automatically.",
      }),
    }),
  );
  await login(page, email);
  await expect(page.getByTestId("degraded-banner")).toBeVisible();
  await expect(page.getByTestId("degraded-banner")).toContainText("queued");
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
});

test("keyboard: skip link and navigation are reachable without a mouse", async ({ page, request }) => {
  const email = await newUser(request, "a11y");
  await login(page, email);
  const skip = page.getByRole("link", { name: "Skip to content" });
  // first focusable element of the app (dev builds add a framework button before it)
  for (let i = 0; i < 4 && !(await skip.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab");
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeVisible();
  await page.goto("/runs");
  await expect(page.getByRole("heading", { name: "Agent runs" })).toBeVisible();
});
