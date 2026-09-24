import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const SECTIONS = ["overview", "map", "forecast", "events", "quality", "analyst", "method"] as const;
const SHOTS = process.env.E2E_SCREENSHOTS ? path.resolve("../../docs/images") : null;

// Runs against a server in pune mode with the worker running (see docs/OPERATIONS.md).
test.beforeEach(async ({ request }) => {
  const meta = (await (await request.get("/api/v1/meta")).json()) as { mode: string };
  test.skip(meta.mode !== "pune", "server is not in pune mode");
});

function watch(page: Page) {
  const problems: string[] = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() === "error") problems.push(`console: ${m.text()}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`);
  });
  return problems;
}

const link = (page: Page) => page.locator(".ops-status-item").filter({ hasText: "Link" });

/** The console holds a stream open, so the network never idles: wait for content instead. */
async function ready(page: Page) {
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Pune");
  await expect(link(page)).toHaveText(/CONNECTED/, { timeout: 30_000 });
  await expect(page.locator(".skeleton")).toHaveCount(0, { timeout: 30_000 });
}

for (const scheme of ["dark", "light"] as const) {
  test.describe(`${scheme} mode`, () => {
    test.use({ colorScheme: scheme });
    for (const section of SECTIONS) {
      test(`${section}: renders, no errors, no WCAG A/AA violations`, async ({ page }) => {
        const problems = watch(page);
        await page.goto(`/#/${section}`);
        await ready(page);
        await page.waitForTimeout(1500); // charts and the first snapshot
        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        expect(
          results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`),
          `accessibility in ${section} (${scheme})`,
        ).toEqual([]);
        expect(problems).toEqual([]);
        if (SHOTS && section !== "analyst") {
          mkdirSync(SHOTS, { recursive: true });
          await page.screenshot({ path: path.join(SHOTS, `pune-${section}-${scheme}.png`), fullPage: true });
        }
      });
    }
  });
}

test("the simulated label and attributions are always on screen", async ({ page }) => {
  await page.goto("/#/overview");
  await ready(page);
  await expect(page.getByRole("region", { name: "Data source", exact: true })).toContainText("SIMULATED DEMAND");
  await expect(page.getByText(/Open-Meteo.com \(CC BY 4.0\)/)).toBeVisible();
  await expect(page.getByText(/OpenStreetMap contributors/).first()).toBeVisible();
  for (const route of SECTIONS.filter((s) => s !== "analyst")) {
    await page.goto(`/#/${route}`);
    await expect(page.getByRole("region", { name: "Data source", exact: true })).toContainText("SIMULATED DEMAND");
  }
});

test("every number is labelled with its data class and freshness", async ({ page }) => {
  await page.goto("/#/overview");
  await ready(page);
  const cards = page.getByRole("article");
  await expect(cards).toHaveCount(6);
  await expect(page.getByRole("article", { name: "Forecast, window" })).toContainText("PREDICTED");
  await expect(page.getByRole("article", { name: "Weather" })).toContainText(/NEAR-REAL-TIME/);
  await expect(page.getByRole("article", { name: "Weather" })).toContainText(/LIVE|DELAYED|STALE|OFFLINE/);
  await expect(page.getByText("MODELLED").first()).toBeVisible();
});

test("time control changes the window and the numbers", async ({ page }) => {
  await page.goto("/#/overview");
  await ready(page);
  const now = await page.getByRole("article", { name: /Simulated pickups/ }).innerText();
  await page.getByRole("radio", { name: "TODAY" }).check({ force: true });
  await expect(page.getByText("Today so far, 00:00 to now").first()).toBeVisible({ timeout: 15_000 });
  const today = await page.getByRole("article", { name: /Simulated pickups/ }).innerText();
  expect(today).not.toEqual(now);
  await page.getByRole("radio", { name: "FORECAST" }).check({ force: true });
  await expect(page.getByText("Forecast for the next full hour").first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("article", { name: /Simulated pickups/ })).toContainText("not yet");
});

test("clicking a zone shows its day against the forecast range", async ({ page }) => {
  await page.goto("/#/overview");
  await ready(page);
  await page.locator("path.zone").nth(20).click();
  await expect(page.getByRole("button", { name: "Clear" })).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Today so far", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("View data as a table").first()).toBeVisible();
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page.getByText("No zone selected")).toBeVisible();
});

test("a zone can be chosen without a mouse", async ({ page }) => {
  await page.goto("/#/overview");
  await ready(page);
  await page.getByRole("combobox", { name: /^Zone/ }).selectOption({ index: 5 });
  await expect(page.getByRole("button", { name: "Clear" })).toBeVisible({ timeout: 15_000 });
});

test("layers change the map", async ({ page }) => {
  await page.goto("/#/overview");
  await ready(page);
  const fills = async () => page.locator("path.zone").evaluateAll((els) => els.map((e) => (e as SVGElement).getAttribute("fill")).join("|"));
  const ratio = await fills();
  await page.getByRole("combobox", { name: "Layer" }).selectOption("demand");
  expect(await fills()).not.toEqual(ratio);
});

test("data quality shows sources, the run log and what is not connected", async ({ page }) => {
  await page.goto("/#/quality");
  await ready(page);
  await expect(page.getByRole("heading", { name: "Recent ingestion runs" })).toBeVisible();
  await expect(page.getByText("NOT CONFIGURED").first()).toBeVisible();
  await expect(page.getByText(/not implemented: no adapter exists yet/).first()).toBeVisible();
  await expect(page.getByText("Store version")).toBeVisible();
});

test("losing the network says so and recovers", async ({ page, context }) => {
  await page.goto("/#/overview");
  await ready(page);
  await context.setOffline(true);
  await expect(page.getByRole("status").filter({ hasText: /offline|Reconnecting/ })).toBeVisible({ timeout: 20_000 });
  await expect(link(page)).not.toHaveText(/^\s*●\s*CONNECTED/);
  await expect(page.getByRole("article").first()).toBeVisible(); // the last numbers stay, marked as possibly out of date
  await context.setOffline(false);
  await expect(link(page)).toHaveText(/●\s*CONNECTED/, { timeout: 45_000 });
});

test("the console works on a phone: no sideways scroll, controls reachable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/overview");
  await ready(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.getByRole("radio", { name: "−1 h" }).check({ force: true });
  await expect(page.getByText(/60 minutes ago/).first()).toBeVisible({ timeout: 15_000 });
});

test("theme can be switched and is remembered", async ({ page }) => {
  await page.goto("/#/overview");
  await ready(page);
  await page.getByRole("button", { name: /Theme:/ }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
