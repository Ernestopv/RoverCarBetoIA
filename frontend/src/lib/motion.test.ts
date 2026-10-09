import { describe, expect, it } from "vitest";

import { applyThrottle, clampThrottle, isIdleCommand } from "./motion";

describe("isIdleCommand", () => {
  it("is true only when both axes are zero", () => {
    expect(isIdleCommand({ linear: 0, angular: 0 })).toBe(true);
  });

  it("is false when any axis is non-zero", () => {
    expect(isIdleCommand({ linear: 0.1, angular: 0 })).toBe(false);
    expect(isIdleCommand({ linear: 0, angular: -0.1 })).toBe(false);
  });
});

describe("clampThrottle", () => {
  it("keeps values inside the 0..1 range", () => {
    expect(clampThrottle(0)).toBe(0);
    expect(clampThrottle(0.5)).toBe(0.5);
    expect(clampThrottle(1)).toBe(1);
  });

  it("clamps out-of-range values", () => {
    expect(clampThrottle(1.5)).toBe(1);
    expect(clampThrottle(-0.2)).toBe(0);
  });

  it("fails safe to zero on non-finite input", () => {
    expect(clampThrottle(Number.NaN)).toBe(0);
    expect(clampThrottle(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe("applyThrottle", () => {
  it("scales both axes", () => {
    expect(applyThrottle({ linear: 1, angular: -1 }, 0.5)).toEqual({
      linear: 0.5,
      angular: -0.5,
    });
  });

  it("stops all motion at zero throttle", () => {
    expect(applyThrottle({ linear: 1, angular: 1 }, 0)).toEqual({ linear: 0, angular: 0 });
  });

  it("never amplifies a command above the requested value", () => {
    const raw = { linear: 0.4, angular: 0.25 };
    for (const throttle of [1, 0.9, 0.5, 0.1, 5, Number.NaN]) {
      const scaled = applyThrottle(raw, throttle);
      expect(Math.abs(scaled.linear)).toBeLessThanOrEqual(Math.abs(raw.linear));
      expect(Math.abs(scaled.angular)).toBeLessThanOrEqual(Math.abs(raw.angular));
    }
  });

  it("leaves a command unchanged at full throttle", () => {
    const raw = { linear: 0.6, angular: -0.3 };
    expect(applyThrottle(raw, 1)).toEqual(raw);
  });
});
