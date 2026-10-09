// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Follow } from "../hooks/useFollow";
import type { FollowStatus } from "../types/rover";
import { FollowToggle } from "./FollowToggle";

afterEach(cleanup);

function status(partial: Partial<FollowStatus> = {}): FollowStatus {
  return {
    enabled: false,
    target_label: "person",
    min_confidence: 0.5,
    target_height: 0.7,
    max_linear: 0.4,
    max_angular: 0.6,
    min_linear: 0.15,
    face_deadband: 0.2,
    target_id: null,
    has_target: false,
    linear: 0,
    angular: 0,
    lost_s: null,
    timestamp: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

function follow(partial: Partial<Follow> = {}): Follow {
  return { status: status(), error: null, pending: false, setEnabled: vi.fn(), ...partial };
}

describe("FollowToggle", () => {
  it("hides itself until the behaviour status is known", () => {
    const { container } = render(<FollowToggle follow={follow({ status: null })} />);

    expect(container.textContent).toBe("");
  });

  it("enables following when the button is pressed", () => {
    const setEnabled = vi.fn();
    render(<FollowToggle follow={follow({ setEnabled })} />);

    fireEvent.click(screen.getByRole("button"));

    expect(setEnabled).toHaveBeenCalledWith(true);
  });

  it("offers to stop, and disables for the status, when already following", () => {
    render(
      <FollowToggle
        follow={follow({ status: status({ enabled: true, has_target: true, target_id: 4 }) })}
      />,
    );

    expect(screen.getByText("Following #4")).toBeDefined();
    expect(screen.getByRole("button").textContent).toContain("Stop following");
  });

  it("says it is searching when enabled but nobody is in view", () => {
    render(<FollowToggle follow={follow({ status: status({ enabled: true }) })} />);

    expect(screen.getByText("Searching…")).toBeDefined();
  });

  it("surfaces a backend error", () => {
    render(
      <FollowToggle
        follow={follow({ error: "The rover is not connected; following was not enabled" })}
      />,
    );

    expect(screen.getByRole("alert").textContent).toContain("not connected");
  });
});
