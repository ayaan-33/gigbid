import { defineConfig, devices } from "@playwright/test";

// Backend (GigSim, MCP servers, API with GIGBID_FAKE_LLM=1) is started by scripts/e2e_stack.sh;
// Playwright starts (or reuses) the web app.
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: {
    command: process.env.CI ? "npm run build && npm run start" : "npm run dev",
    url: "http://localhost:3000/login",
    reuseExistingServer: true,
    timeout: 240_000,
  },
});
