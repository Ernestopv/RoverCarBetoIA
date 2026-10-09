// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Bomb(): ReactNode {
  throw new Error("camera exploded");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs every caught error; keep the test output readable.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders its children when nothing fails", () => {
    render(
      <ErrorBoundary label="Camera">
        <p>viewport</p>
      </ErrorBoundary>,
    );

    expect(screen.getByText("viewport")).toBeDefined();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a fallback instead of letting the crash reach the page", () => {
    render(
      <ErrorBoundary label="Camera">
        <Bomb />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText("Camera is unavailable")).toBeDefined();
    expect(screen.getByText("camera exploded")).toBeDefined();
  });
});
