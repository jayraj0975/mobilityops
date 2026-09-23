import { describe, expect, it, vi } from "vitest";
import { ApiError, api, request } from "../api/client";
import { addDays, fmtInt, fmtNum, fmtPct, isoDate } from "../lib/format";
import { errorResponse, mockApi } from "./fixtures";

describe("format helpers", () => {
  it("never print a made-up number for missing values", () => {
    expect(fmtInt(null)).toBe("n/a");
    expect(fmtNum(undefined)).toBe("n/a");
    expect(fmtPct(Number.NaN)).toBe("n/a");
  });
  it("format numbers and percentages", () => {
    expect(fmtInt(1234567.4)).toBe("1,234,567");
    expect(fmtNum(3.14159, 2)).toBe("3.14");
    expect(fmtPct(0.1783)).toBe("17.8%");
  });
  it("do date arithmetic on local calendar dates without timezone drift", () => {
    expect(addDays("2024-03-09", 2)).toBe("2024-03-11"); // across the spring-forward night
    expect(addDays("2024-03-01", -1)).toBe("2024-02-29"); // leap day
    expect(addDays("2024-01-01T00:00:00", 6)).toBe("2024-01-07");
    expect(isoDate(new Date(2024, 11, 31))).toBe("2024-12-31");
  });
});

describe("api client", () => {
  it("builds query strings and drops empty values", async () => {
    const fn = mockApi({ "/api/v1/demand/top-zones": [] });
    await api.topZones({ start: "2024-01-01", end: "2024-01-08", limit: 3, metric: undefined });
    const url = String(fn.mock.calls[0]?.[0]);
    expect(url).toBe("/api/v1/demand/top-zones?start=2024-01-01&end=2024-01-08&limit=3");
  });

  it("turns the API's error shape into an ApiError with its request id", async () => {
    mockApi({ "/x": () => errorResponse(422, "invalid_query", "end must be after start", { details: [{ field: "query.end", message: "bad" }] }) });
    const err = await request("/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const e = err as ApiError;
    expect([e.status, e.code, e.message, e.requestId]).toEqual([422, "invalid_query", "end must be after start", "req-123"]);
    expect(e.details).toEqual([{ field: "query.end", message: "bad" }]);
  });

  it("reports a non-JSON error body and a network failure clearly", async () => {
    mockApi({ "/y": () => new Response("<html>bad gateway</html>", { status: 502 }) });
    await expect(request("/y")).rejects.toMatchObject({ status: 502, code: "http_error" });
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("failed"))));
    await expect(request("/z")).rejects.toMatchObject({ status: 0, code: "network" });
  });

  it("posts JSON bodies", async () => {
    const fn = mockApi({ "/api/v1/analyst/ask": { ok: true } });
    await api.analystAsk("hello");
    const init = fn.mock.calls[0]?.[1];
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ question: "hello" });
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});
