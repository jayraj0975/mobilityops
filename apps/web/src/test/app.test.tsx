import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import {
  analystAnswer,
  anomalyPage,
  baseRoutes,
  compare,
  errorResponse,
  meta,
  mockApi,
  perf,
  realMeta,
  scenario,
  top,
} from "./fixtures";

beforeEach(() => {
  window.location.hash = "";
});

const goTo = async (name: RegExp | string) => userEvent.click(await screen.findByRole("button", { name }));

describe("shell", () => {
  it("always says whether the data is synthetic, using the label the API returned", async () => {
    mockApi(baseRoutes);
    render(<App />);
    const banner = await screen.findByRole("region", { name: "Data source" });
    expect(banner).toHaveTextContent("TEST / SYNTHETIC DATA");
    expect(banner).toHaveTextContent("not real trips");
  });

  it("shows a calm real-data banner with the data window", async () => {
    mockApi({ ...baseRoutes, "/api/v1/meta": realMeta });
    render(<App />);
    const banner = await screen.findByRole("region", { name: "Data source" });
    expect(banner).toHaveTextContent("REAL DATA");
    expect(banner).toHaveTextContent("2024-01-01 to 2024-05-31");
    expect(banner).not.toHaveTextContent("SYNTHETIC");
  });

  it("is keyboard friendly: skip link, labelled navigation, current page marked", async () => {
    mockApi(baseRoutes);
    render(<App />);
    expect(await screen.findByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    const nav = screen.getByRole("navigation", { name: "Sections" });
    expect(within(nav).getAllByRole("button")).toHaveLength(7);
    expect(within(nav).getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await goTo("Forecast");
    expect(within(nav).getByRole("button", { name: "Forecast" })).toHaveAttribute("aria-current", "page");
    expect(window.location.hash).toBe("#/forecast");
  });

  it("explains a missing artifact instead of showing an empty page", async () => {
    mockApi({ ...baseRoutes, "/api/v1/forecast/performance": () => errorResponse(503, "not_ready", "evaluation.json not found; run `forecast-eval` first") });
    render(<App />);
    await goTo("Forecast");
    const alert = await screen.findAllByRole("alert");
    expect(alert[0]).toHaveTextContent("Not generated yet");
    expect(alert[0]).toHaveTextContent("run `forecast-eval` first");
    expect(alert[0]).toHaveTextContent("req-123");
  });

  it("reports an unreachable API and offers a retry", async () => {
    vi_fetchFails();
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the API");
    expect(screen.getAllByRole("alert")).toHaveLength(1); // one error, not one per failed request
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

function vi_fetchFails() {
  globalThis.fetch = (() => Promise.reject(new TypeError("offline"))) as typeof fetch;
}

describe("overview", () => {
  it("renders numbers from the API only", async () => {
    mockApi(baseRoutes);
    render(<App />);
    expect(await screen.findByText(/^84,000$/)).toBeInTheDocument(); // period_b.total from the fixture
    expect(screen.getByText("20.0%")).toBeInTheDocument(); // per_day_change_pct
    expect(screen.getByText(/1 of 2 checks pass/)).toBeInTheDocument();
    expect(screen.getByText(/weather_coverage – weather for 31 of 152 days/)).toBeInTheDocument();
    expect(compare.period_b.total).toBe(84000);
  });

  it("gives every chart a text alternative as a table", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await screen.findByText(/^84,000$/);
    const tables = await screen.findAllByRole("table", { hidden: true });
    expect(tables.length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("View data as a table").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByRole("img", { name: /Pickups by zone/ }).length).toBe(1);
    expect(top.length).toBe(2);
  });
});

describe("forecast", () => {
  it("shows baselines beside the model, the interval coverage, and labels the oracle experiment", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await goTo("Forecast");
    const table = await screen.findByRole("table", { name: "Forecast accuracy by model" }, { timeout: 3000 });
    expect(within(table).getByText("LightGBM (Poisson)")).toBeInTheDocument();
    expect(within(table).getByText("Naive (same hour yesterday)")).toBeInTheDocument();
    expect(within(table).getByText("22.3%")).toBeInTheDocument();
    expect(screen.getByText(/contained 79.4% of held-out values/)).toBeInTheDocument();
    expect(screen.getByText(/ORACLE experiment, not a deployable result/)).toBeInTheDocument();
    expect(screen.getByText(/0.1 percentage points/)).toBeInTheDocument();
    expect(perf.best_baseline).toBe("seasonal_mean_4w");
  });

  it("states that forecasts are estimates", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await goTo("Forecast");
    expect(await screen.findByText(/not a guarantee/)).toBeInTheDocument();
  });
});

describe("anomalies", () => {
  it("shows the accuracy status and non-causal explanations", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await goTo("Anomalies");
    expect(await screen.findByText(/verified against planted ground truth/, { selector: "p" })).toBeInTheDocument();
    const cards = await screen.findAllByRole("heading", { level: 3, name: /Sample Zone 03/ });
    expect(cards.length).toBe(3);
    expect(screen.getAllByText(/describes co-occurrence in the data, not a cause/).length).toBe(3);
    expect(screen.getAllByText("high severity").length).toBe(3); // severity is text, not colour only
  });

  it("filters and paginates through the API", async () => {
    const calls: string[] = [];
    mockApi({
      ...baseRoutes,
      "/api/v1/anomalies": (url: URL) => {
        calls.push(url.search);
        return anomalyPage(25, Number(url.searchParams.get("offset") ?? 0));
      },
    });
    render(<App />);
    await goTo("Anomalies");
    await screen.findByText(/Showing 1 to 10 of 25/);
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText(/Showing 11 to 20 of 25/);
    await userEvent.selectOptions(screen.getByLabelText("Severity"), "high");
    await screen.findByText(/Showing 1 to 10 of 25/); // filter resets to the first page
    expect(calls.some((c) => c.includes("severity=high") && c.includes("offset=0"))).toBe(true);
  });

  it("says so when nothing matches", async () => {
    mockApi({ ...baseRoutes, "/api/v1/anomalies": () => anomalyPage(0) });
    render(<App />);
    await goTo("Anomalies");
    expect(await screen.findByText("No events match these filters.")).toBeInTheDocument();
  });
});

describe("scenarios", () => {
  it("labels everything as simulated and shows the assumptions and moves", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await goTo("Scenarios");
    const notes = await screen.findAllByRole("note");
    expect(notes[0]).toHaveTextContent("SIMULATED SCENARIO under explicit assumptions");
    await userEvent.click(await screen.findByRole("button", { name: "Run simulation" }));
    expect(await screen.findByText("Assumptions this result depends on")).toBeInTheDocument();
    const result = screen.getByText("Served share without repositioning").closest(".kpis") as HTMLElement;
    expect(within(result).getByText("84.00%")).toBeInTheDocument();
    expect(within(result).getByText("85.00%")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Repositioning moves" })).toHaveTextContent("Sample Zone 07");
    expect(screen.getAllByRole("note").length).toBeGreaterThanOrEqual(2);
  });

  it("presents an infeasible request as infeasible, with the best attainable share", async () => {
    mockApi({
      ...baseRoutes,
      "/api/v1/optimization/scenario": () =>
        scenario({ status: "infeasible", message: "infeasible: 99.0% cannot be reached", best_attainable_service_share: 0.85, service_share_after: null, moves: [], vehicles_moved: 0 }),
    });
    render(<App />);
    await goTo("Scenarios");
    await userEvent.type(await screen.findByLabelText(/Required served share/), "99");
    await userEvent.click(screen.getByRole("button", { name: "Run simulation" }));
    expect(await screen.findByText(/infeasible: 99.0% cannot be reached/)).toBeInTheDocument();
    const kpis = screen.getByText("Best attainable").closest(".kpi") as HTMLElement;
    expect(within(kpis).getByText("85.00%")).toBeInTheDocument();
  });

  it("blocks an impossible hour range before calling the API", async () => {
    const fn = mockApi(baseRoutes);
    render(<App />);
    await goTo("Scenarios");
    const from = await screen.findByLabelText("From hour");
    await userEvent.clear(from);
    await userEvent.type(from, "22");
    expect(await screen.findByText("The end hour must be after the start hour.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run simulation" })).toBeDisabled();
    expect(fn.mock.calls.some((c) => String(c[0]).includes("/optimization/scenario"))).toBe(false);
  });

  it("reports a busy solver in plain words", async () => {
    mockApi({ ...baseRoutes, "/api/v1/optimization/scenario": () => errorResponse(429, "busy", "all scenario solver slots are in use") });
    render(<App />);
    await goTo("Scenarios");
    await userEvent.click(await screen.findByRole("button", { name: "Run simulation" }));
    expect(await screen.findByText(/solver is busy/)).toBeInTheDocument();
  });

  it("shows the backtest, including that the better forecast did not give the better plan", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await goTo("Scenarios");
    const table = await screen.findByRole("table", { name: "Served share by planner" });
    expect(within(table).getByText("Plan with the LightGBM forecast")).toBeInTheDocument();
    expect(screen.getByText(/-0.20 points/)).toBeInTheDocument();
  });
});

describe("about", () => {
  it("says which data the site shows and links to the source", async () => {
    mockApi({ ...baseRoutes, "/api/v1/meta": realMeta });
    render(<App />);
    await goTo("About");
    expect(await screen.findByRole("heading", { name: "What this is" })).toBeInTheDocument();
    expect(screen.getByText(/NYC Taxi and Limousine Commission yellow-taxi trip records/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Source code/ })).toHaveAttribute("href", "https://github.com/jayraj0975/mobilityops");
  });

  it("does not claim real trips when the data is synthetic", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await goTo("About");
    expect(await screen.findByRole("heading", { name: "The data on this site" })).toBeInTheDocument();
    expect(screen.getAllByText(/these are not real trips/).length).toBeGreaterThan(1);
    expect(screen.queryByText(/Taxi and Limousine Commission yellow-taxi trip records/)).not.toBeInTheDocument();
  });
});

describe("robustness", () => {
  it("shows a readable error, not a blank page, if a response has an unexpected shape", async () => {
    mockApi({ ...baseRoutes, "/api/v1/analyst/status": {} });
    const spy = vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<App />);
    await goTo("Analyst");
    await userEvent.type(await screen.findByLabelText("Your question"), "hi");
    mockApi({ ...baseRoutes, "/api/v1/analyst/ask": () => ({ question: "hi" }) });
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/could not be displayed/)).toBeInTheDocument();
    spy.mockRestore();
  });
});

describe("analyst", () => {
  it("labels every statement by kind and shows the tools used with their facts", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await goTo("Analyst");
    expect(await screen.findByText(/only picks from 13 fixed read-only tools/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Your question"), "What were the busiest zones?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    const answer = await screen.findByRole("article");
    for (const kind of ["Fact", "Interpretation", "Assumption", "Limitation"]) {
      expect(within(answer).getByText(kind)).toBeInTheDocument();
    }
    expect(answer).toHaveTextContent("grounding: 2 of 2 statements verified");
    await userEvent.click(within(answer).getByText(/Tools used and what they returned \(1\)/));
    expect(within(answer).getByText("get_top_zones")).toBeInTheDocument();
    expect(within(answer).getByText(/pickups in rank 1 zone: 5,123/)).toBeInTheDocument();
  });

  it("shows refusals as refusals", async () => {
    mockApi({
      ...baseRoutes,
      "/api/v1/analyst/ask": () =>
        analystAnswer({
          question: "DROP TABLE x",
          status: "refused",
          statements: [{ kind: "LIMITATION", text: "I only read data; I cannot modify or delete it.", fact_ids: [] }],
          tools_used: [],
          grounding: { checked: 0, removed: 0 },
        }),
    });
    render(<App />);
    await goTo("Analyst");
    await userEvent.type(await screen.findByLabelText("Your question"), "DROP TABLE x");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    const answer = await screen.findByRole("article");
    expect(answer).toHaveClass("answer-refused");
    expect(answer).toHaveTextContent("Status: refused");
    expect(answer).toHaveTextContent("I only read data");
    expect(within(answer).queryByText(/Tools used/)).not.toBeInTheDocument();
  });

  it("runs an example question with one click and disables the form while working", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    mockApi({ ...baseRoutes, "/api/v1/analyst/ask": async () => (await gate, analystAnswer()) });
    render(<App />);
    await goTo("Analyst");
    await userEvent.click(await screen.findByRole("button", { name: "How accurate is the forecast?" }));
    expect(await screen.findByRole("button", { name: "Working…" })).toBeDisabled();
    release();
    expect(await screen.findByRole("article")).toBeInTheDocument();
  });

  it("does not send an empty question and caps the length", async () => {
    const fn = mockApi(baseRoutes);
    render(<App />);
    await goTo("Analyst");
    const ask = await screen.findByRole("button", { name: "Ask" });
    expect(ask).toBeDisabled();
    expect(screen.getByLabelText("Your question")).toHaveAttribute("maxlength", "500");
    expect(fn.mock.calls.some((c) => String(c[0]).includes("/analyst/ask"))).toBe(false);
  });

  it("surfaces an API error for the question", async () => {
    mockApi({ ...baseRoutes, "/api/v1/analyst/ask": () => errorResponse(422, "validation_error", "invalid request") });
    render(<App />);
    await goTo("Analyst");
    await userEvent.type(await screen.findByLabelText("Your question"), "hi");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid request");
  });
});

describe("demand", () => {
  it("validates the date range in the interface", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await goTo("Demand");
    const from = await screen.findByLabelText("From");
    const to = screen.getByLabelText("To");
    await userEvent.clear(to);
    await userEvent.type(to, "2024-01-02");
    await userEvent.clear(from);
    await userEvent.type(from, "2024-02-01");
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBeGreaterThan(0));
    expect(screen.getAllByText("The start date must not be after the end date.").length).toBeGreaterThan(0);
    expect(meta.n_zones).toBe(2);
  });

  it("always shows the weather caveat next to the weather comparison", async () => {
    mockApi({
      ...baseRoutes,
      "/api/v1/demand/weather-comparison": {
        condition: "rain", zone_id: null, days_with: 17, days_without: 42, mean_daily_with: 124143, mean_daily_without: 112937,
        raw_ratio: 1.099, weekday_adjusted_ratio: 1.061,
        caveat: "This compares observed demand on days with and without the condition. It is an association; it does not show that the weather caused the difference.",
      },
    });
    render(<App />);
    await goTo("Demand");
    expect(await screen.findByText(/17 days with rain and 42 without/)).toBeInTheDocument();
    expect(screen.getByText(/does not show that the weather caused the difference/)).toBeInTheDocument();
  });
});
