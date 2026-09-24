import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Loading, SLOW_LOAD_MS } from "../components/State";

describe("Loading", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("says what is loading, with no excuse at first", () => {
    render(<Loading what="forecasts" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading forecasts…");
    expect(screen.queryByText(/taking longer than usual/)).toBeNull();
  });

  it("explains a slow load once it has lasted long enough", () => {
    render(<Loading />);
    act(() => {
      vi.advanceTimersByTime(SLOW_LOAD_MS + 1);
    });
    expect(screen.getByRole("status")).toHaveTextContent(/taking longer than usual/);
    expect(screen.getByRole("status")).toHaveTextContent(/free plan/);
  });
});
