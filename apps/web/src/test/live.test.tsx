/**
 * Live check against a running API (no mocks). Skipped unless E2E_API_URL is set:
 *   E2E_API_URL=http://127.0.0.1:8000 npm run test:live
 * It renders the real app against real responses, so a contract drift between the API and the
 * interface fails here even if every mocked test still passes.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import App from "../App";
import { api } from "../api/client";

const base = process.env.E2E_API_URL;
const realFetch = globalThis.fetch;

describe.skipIf(!base)("live API", () => {
  beforeAll(() => {
    vi.stubGlobal("fetch", (input: RequestInfo | URL, init?: RequestInit) =>
      realFetch(`${base}${String(input)}`, init),
    );
  });
  afterAll(() => vi.unstubAllGlobals());

  it("serves consistent metadata and zones", async () => {
    const meta = await api.meta();
    const zones = await api.zones();
    expect(zones).toHaveLength(meta.n_zones);
    expect(["sample", "real"]).toContain(meta.mode);
    expect(meta.data_label).toMatch(meta.mode === "sample" ? /SYNTHETIC/ : /real/);
  });

  it("renders the overview from real responses, with the data label", async () => {
    window.location.hash = "#/overview";
    render(<App />);
    const banner = await screen.findByRole("region", { name: "Data source" }, { timeout: 15000 });
    expect(banner.textContent ?? "").toMatch(/SYNTHETIC|REAL DATA/);
    expect(await screen.findByText(/Last 7 days/, {}, { timeout: 15000 })).toBeInTheDocument();
    expect((await screen.findAllByText(/checks pass/, {}, { timeout: 15000 })).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("NaN")).not.toBeInTheDocument();
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument();
  }, 30000);

  it("asks the analyst a question through the interface", async () => {
    window.location.hash = "#/analyst";
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Analyst" }, { timeout: 15000 }));
    await userEvent.type(await screen.findByLabelText("Your question"), "What does WAPE mean?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    const answer = await screen.findByRole("article", {}, { timeout: 15000 });
    expect(within(answer).getByText("Fact")).toBeInTheDocument();
    expect(answer).toHaveTextContent(/Weighted absolute percentage error/);
  }, 30000);

  it("refuses an unsafe question through the interface", async () => {
    window.location.hash = "#/analyst";
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Analyst" }, { timeout: 15000 }));
    await userEvent.type(await screen.findByLabelText("Your question"), "DROP TABLE fact_zone_hourly_demand");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("article", {}, { timeout: 15000 })).toHaveTextContent(/cannot modify or delete/);
  }, 30000);
});
