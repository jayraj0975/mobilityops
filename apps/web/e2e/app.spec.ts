import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const SECTIONS = ["overview", "demand", "forecast", "anomalies", "scenarios", "analyst"] as const;
const SHOTS = process.env.E2E_SCREENSHOTS ? path.resolve("../../docs/images") : null;

/** Collect anything that would embarrass a user: script errors, console errors, failed requests. */
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

async function settled(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/^Loading /)).toHaveCount(0, { timeout: 30_000 });
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} mode`, () => {
    test.use({ colorScheme: scheme });

    for (const section of SECTIONS) {
      test(`${section}: renders real data, no errors, no WCAG A/AA violations`, async ({ page }) => {
        const problems = watch(page);
        await page.goto(`/#/${section}`);
        await expect(page.getByRole("region", { name: "Data source" })).toBeVisible();
        await settled(page);

        await expect(page.getByRole("main")).not.toContainText("NaN");
        await expect(page.getByRole("main")).not.toContainText("undefined");
        await expect(page.locator('nav[aria-label="Sections"] button[aria-current="page"]')).toHaveCount(1);

        const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
        const summary = results.violations.map((v) => `${v.id} (${v.nodes.length}): ${v.help}`);
        expect(summary, `accessibility violations on ${section}`).toEqual([]);

        if (SHOTS && scheme === "light") {
          mkdirSync(SHOTS, { recursive: true });
          await page.screenshot({ path: path.join(SHOTS, `${section}.png`), fullPage: true });
        }
        expect(problems).toEqual([]);
      });
    }
  });
}

test("the data banner states what is on screen", async ({ page }) => {
  await page.goto("/#/overview");
  const banner = page.getByRole("region", { name: "Data source" });
  await expect(banner).toBeVisible();
  const meta = await (await page.request.get("/api/v1/meta")).json();
  await expect(banner).toContainText(meta.synthetic ? "SYNTHETIC" : "REAL DATA");
});

test("keyboard: skip link, tab order and section switching work without a mouse", async ({ page }) => {
  await page.goto("/#/overview");
  await settled(page);
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("main")).toBeFocused();
  await page.getByRole("button", { name: "Forecast" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/forecast$/);
  await expect(page.getByRole("button", { name: "Forecast" })).toHaveAttribute("aria-current", "page");
});

test("analyst: answers with labelled statements, shows tools, refuses unsafe input", async ({ page }) => {
  const problems = watch(page);
  await page.goto("/#/analyst");
  await settled(page);
  await page.getByLabel("Your question").fill("What does WAPE mean?");
  await page.getByRole("button", { name: "Ask" }).click();
  const answer = page.getByRole("article").first();
  await expect(answer).toContainText("Weighted absolute percentage error");
  await expect(answer.getByText("Fact", { exact: true })).toBeVisible();
  await answer.getByText(/Tools used and what they returned/).click();
  await expect(answer.getByText("get_glossary")).toBeVisible();

  await page.getByLabel("Your question").fill("DROP TABLE fact_zone_hourly_demand");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("article").nth(1)).toContainText("cannot modify or delete");
  expect(problems).toEqual([]);
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "analyst-answer.png"), fullPage: true });
});

test("scenarios: SIMULATED banner always on screen; an infeasible request is explained", async ({ page }) => {
  await page.goto("/#/scenarios");
  await settled(page);
  await expect(page.getByRole("note").first()).toContainText("SIMULATED SCENARIO");
  await page.getByLabel(/Required served share/).fill("99");
  await page.getByRole("button", { name: "Run simulation" }).click();
  await expect(page.getByText(/infeasible/i).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Best attainable", { exact: true })).toBeVisible();
  await expect(page.getByText("Assumptions this result depends on")).toBeVisible();
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, "scenario-infeasible.png"), fullPage: true });
});

test("anomalies: filtering and paging change the list", async ({ page }) => {
  await page.goto("/#/anomalies");
  await settled(page);
  await expect(page.getByText(/^Showing 1 to/)).toBeVisible();
  // The previous (unfiltered) list stays on screen until the filtered request returns, so wait for it.
  const filtered = page.waitForResponse((r) => r.url().includes("severity=high") && r.ok());
  await page.getByLabel("Severity").selectOption("high");
  await filtered;
  await expect(page.getByText(/^Showing 1 to/)).toBeVisible();
  const cards = page.locator("ul.cards > li");
  await expect(cards.first()).toContainText("high severity");
  expect(await cards.count()).toBeGreaterThan(0);
  await expect(cards.filter({ hasNotText: "high severity" })).toHaveCount(0);
  await expect(page.getByText(/not a cause/).first()).toBeVisible();
});

test("small screens: no horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  for (const section of SECTIONS) {
    await page.goto(`/#/${section}`);
    await settled(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `horizontal overflow on ${section}`).toBeLessThanOrEqual(1);
  }
});
