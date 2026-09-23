import { defineConfig } from "@playwright/test";

// Runs against an already-running server that serves the built UI (see docs / `make e2e-browser`).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE ?? "http://127.0.0.1:8000",
    viewport: { width: 1280, height: 900 },
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
