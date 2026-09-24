import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { ServiceMix } from "../components/ServiceMix";
import { baseRoutes, meta, mockApi } from "./fixtures";

const withServices = {
  ...meta,
  services: [
    { service: "fhvhv", label: "High-volume for-hire vehicles (Uber, Lyft and similar)" },
    { service: "green", label: "Green taxis (boro taxis)" },
    { service: "yellow", label: "Yellow taxis" },
  ],
};

const point = (period: string, service: string, label: string, pickups: number, share: number) => ({ period, service, label, pickups, share });

const mixRoute = (url: URL) =>
  url.searchParams.get("grain") === "total"
    ? [
        point("2024-01-01T00:00:00", "fhvhv", "High-volume for-hire vehicles (Uber, Lyft and similar)", 800000, 0.8),
        point("2024-01-01T00:00:00", "green", "Green taxis (boro taxis)", 10000, 0.01),
        point("2024-01-01T00:00:00", "yellow", "Yellow taxis", 190000, 0.19),
      ]
    : [
        point("2024-01-01T00:00:00", "fhvhv", "x", 400000, 0.78),
        point("2024-01-01T00:00:00", "green", "x", 5000, 0.01),
        point("2024-01-01T00:00:00", "yellow", "x", 108000, 0.21),
        point("2024-02-01T00:00:00", "fhvhv", "x", 400000, 0.82),
        point("2024-02-01T00:00:00", "green", "x", 5000, 0.01),
        point("2024-02-01T00:00:00", "yellow", "x", 82000, 0.17),
      ];

beforeEach(() => {
  window.location.hash = "";
});

describe("service mix", () => {
  it("shows each service's pickups and share, and says what the share is not", async () => {
    const fetchMock = mockApi({ ...baseRoutes, "/api/v1/demand/services": mixRoute });
    render(<ServiceMix meta={withServices} />);
    const table = await screen.findByRole("table", { name: /Pickups by service for the whole period/ });
    expect(within(table).getByText("Yellow taxis")).toBeInTheDocument();
    expect(within(table).getByText("800,000")).toBeInTheDocument();
    expect(within(table).getByText(/80\.0\s?%/)).toBeInTheDocument();
    expect(screen.getByText(/not the share of all mobility/i)).toBeInTheDocument();
    const grains = fetchMock.mock.calls.map(([u]) => new URL(String(u), "http://localhost").searchParams.get("grain"));
    expect(grains.sort()).toEqual(["month", "total"]);
    // the chart has a text alternative with the same numbers
    expect(await screen.findByText("View data as a table")).toBeInTheDocument();
  });

  it("passes the selected zone to the API", async () => {
    const fetchMock = mockApi({ ...baseRoutes, "/api/v1/demand/services": mixRoute });
    render(<ServiceMix meta={withServices} zone={7} />);
    await screen.findByRole("table", { name: /Pickups by service/ });
    for (const [u] of fetchMock.mock.calls) expect(new URL(String(u), "http://localhost").searchParams.get("zone_id")).toBe("7");
  });

  it("is absent on the Demand page when the data holds yellow taxis only", async () => {
    mockApi(baseRoutes);
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Demand" }));
    await screen.findByRole("heading", { name: /Top zones for the period/ });
    expect(screen.queryByRole("heading", { name: /Yellow taxis, green taxis and for-hire/ })).toBeNull();
  });

  it("appears on the Demand page when the data holds several services", async () => {
    mockApi({ ...baseRoutes, "/api/v1/meta": withServices, "/api/v1/demand/services": mixRoute });
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "Demand" }));
    expect(await screen.findByRole("heading", { name: /Yellow taxis, green taxis and for-hire/ })).toBeInTheDocument();
  });
});
