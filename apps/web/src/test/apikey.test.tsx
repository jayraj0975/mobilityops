import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { ApiError, api } from "../api/client";
import { authHeaders, getApiKey, setApiKey } from "../api/key";
import { ErrorState } from "../components/State";
import { baseRoutes, errorResponse, meta, mockApi } from "./fixtures";

beforeEach(() => {
  window.localStorage.clear();
  window.location.hash = "";
});
afterEach(() => vi.unstubAllGlobals());

describe("API key storage", () => {
  it("stores a trimmed key, sends it as X-API-Key, and forgets it when cleared", () => {
    expect(authHeaders()).toEqual({});
    setApiKey("  s3cret \n");
    expect(getApiKey()).toBe("s3cret");
    expect(authHeaders()).toEqual({ "X-API-Key": "s3cret" });
    setApiKey("");
    expect(authHeaders()).toEqual({});
  });

  it("carries the key on every API request", async () => {
    setApiKey("abc");
    const fetchMock = mockApi({ "/api/v1/meta": meta });
    await api.meta();
    const init = (fetchMock.mock.calls[0]?.[1] ?? {}) as RequestInit;
    expect((init.headers as Record<string, string>)["X-API-Key"]).toBe("abc");
  });

  it("sends no key header when none was entered", async () => {
    const fetchMock = mockApi({ "/api/v1/meta": meta });
    await api.meta();
    const init = (fetchMock.mock.calls[0]?.[1] ?? {}) as RequestInit;
    expect(Object.keys(init.headers as Record<string, string>)).not.toContain("X-API-Key");
  });
});

describe("a server that needs a key", () => {
  it("asks for the key instead of showing a dead end, then retries with it", async () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new ApiError(401, "http_error", "missing or invalid X-API-Key", null)} onRetry={onRetry} />);
    expect(screen.getByText("This server needs an API key")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    await userEvent.type(screen.getByLabelText(/API key/), "hunter2");
    await userEvent.click(screen.getByRole("button", { name: "Save and retry" }));
    expect(getApiKey()).toBe("hunter2");
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("loads the whole app once the right key is entered", async () => {
    mockApi({
      ...baseRoutes,
      "/api/v1/meta": (_url: URL, init?: RequestInit) =>
        (init?.headers as Record<string, string>)?.["X-API-Key"] === "right"
          ? meta
          : errorResponse(401, "http_error", "missing or invalid X-API-Key"),
    });
    render(<App />);
    expect(await screen.findByText("This server needs an API key")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/API key/), "right");
    await userEvent.click(screen.getByRole("button", { name: "Save and retry" }));
    expect(await screen.findByRole("region", { name: "Data source" })).toHaveTextContent("TEST / SYNTHETIC DATA");
    await waitFor(() => expect(screen.queryByText("This server needs an API key")).toBeNull());
  });
});
