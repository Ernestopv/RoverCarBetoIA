import { describe, expect, it } from "vitest";

import {
  FAILURE_BANNER_AFTER,
  initialRoverState,
  roverReducer,
  type RoverState,
} from "./roverState";
import type { RoverStatus, TelemetrySnapshot } from "../types/rover";

function status(overrides: Partial<RoverStatus> = {}): RoverStatus {
  return {
    connection: "connected",
    moving: false,
    linear: 0,
    angular: 0,
    pose: { x: 0, y: 0, heading: 0 },
    battery_voltage: 8.4,
    battery_percentage: 100,
    battery_current_ma: null,
    battery_charge_state: "unknown",
    latency_ms: 0,
    last_command_age_s: 0,
    timestamp: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function snapshot(rover: RoverStatus): TelemetrySnapshot {
  return {
    timestamp: "2026-01-01T00:00:00Z",
    rover,
    cpu_temperature_c: 41,
    ai_inference_ms: null,
    detections: null,
  };
}

describe("roverReducer", () => {
  it("starts offline and empty", () => {
    expect(initialRoverState).toEqual({
      telemetry: null,
      status: null,
      online: false,
      mode: null,
      error: null,
      failureCount: 0,
    });
  });

  it("marks the link online when telemetry arrives", () => {
    const next = roverReducer(initialRoverState, {
      type: "telemetry",
      snapshot: snapshot(status()),
    });

    expect(next.online).toBe(true);
    expect(next.error).toBeNull();
    expect(next.telemetry?.rover.connection).toBe("connected");
    expect(next.status?.connection).toBe("connected");
  });

  it("clears a previous failure after a successful poll", () => {
    const failing: RoverState = { ...initialRoverState, online: false, error: "boom" };
    const next = roverReducer(failing, {
      type: "telemetry",
      snapshot: snapshot(status()),
    });

    expect(next.error).toBeNull();
    expect(next.online).toBe(true);
    expect(next.failureCount).toBe(0);
  });

  it("ignores the first failures and only shows the banner after enough consecutive ones", () => {
    const online: RoverState = { ...initialRoverState, status: status(), online: true };

    const one = roverReducer(online, { type: "failure", message: "Backend unreachable" });
    expect(one.online).toBe(true);
    expect(one.error).toBeNull();
    expect(one.failureCount).toBe(1);

    const two = roverReducer(one, { type: "failure", message: "Backend unreachable" });
    expect(two.online).toBe(true);
    expect(two.error).toBeNull();
    expect(two.failureCount).toBe(2);

    const three = roverReducer(two, { type: "failure", message: "Backend unreachable" });
    expect(three.online).toBe(false);
    expect(three.error).toBe("Backend unreachable");
    expect(three.failureCount).toBe(FAILURE_BANNER_AFTER);
    // The last known status survives the outage.
    expect(three.status).toBe(online.status);
  });

  it("resets the failure counter the moment a poll succeeds again", () => {
    const flaky: RoverState = {
      ...initialRoverState,
      status: status(),
      online: true,
      failureCount: 2,
    };

    const back = roverReducer(flaky, {
      type: "telemetry",
      snapshot: snapshot(status({ moving: false })),
    });
    expect(back.online).toBe(true);
    expect(back.failureCount).toBe(0);
  });

  it("treats a command response as proof the link is up", () => {
    const failing: RoverState = { ...initialRoverState, online: false, error: "boom" };
    const next = roverReducer(failing, {
      type: "status",
      status: status({ moving: true, linear: 0.5 }),
    });

    expect(next.online).toBe(true);
    expect(next.error).toBeNull();
    expect(next.status?.moving).toBe(true);
  });

  it("stores the rover mode", () => {
    const next = roverReducer(initialRoverState, { type: "mode", mode: "simulator" });
    expect(next.mode).toBe("simulator");
  });

  it("returns the same state object when nothing changes", () => {
    const state: RoverState = { ...initialRoverState, mode: "simulator", online: false, error: "x" };

    expect(roverReducer(state, { type: "mode", mode: "simulator" })).toBe(state);
    expect(roverReducer(state, { type: "failure", message: "x" })).toBe(state);
  });
});
