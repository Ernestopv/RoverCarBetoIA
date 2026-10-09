import { describe, expect, it } from "vitest";

import { KEY_DIRECTIONS, PAD_DIRECTIONS, padCommand, shapeAxis, shapeCommand } from "./input";

const DEADZONE = 0.1;
const EXPO = 0.35;

describe("shapeAxis", () => {
  it("treats everything inside the deadzone as centred", () => {
    expect(shapeAxis(0, DEADZONE, EXPO)).toBe(0);
    expect(shapeAxis(0.05, DEADZONE, EXPO)).toBe(0);
    expect(shapeAxis(-0.09, DEADZONE, EXPO)).toBe(0);
  });

  it("still reaches full deflection at the edge", () => {
    expect(shapeAxis(1, DEADZONE, EXPO)).toBeCloseTo(1, 6);
    expect(shapeAxis(-1, DEADZONE, EXPO)).toBeCloseTo(-1, 6);
  });

  it("keeps the sign of the input", () => {
    expect(shapeAxis(-0.5, DEADZONE, EXPO)).toBeLessThan(0);
    expect(shapeAxis(0.5, DEADZONE, EXPO)).toBeGreaterThan(0);
  });

  it("is monotonic, with no jump when leaving the deadzone", () => {
    let previous = -1;
    for (let value = 0.1; value <= 1.0001; value += 0.01) {
      const shaped = shapeAxis(value, DEADZONE, EXPO);
      expect(shaped).toBeGreaterThanOrEqual(previous);
      previous = shaped;
    }
  });

  it("gives finer control near the centre than a linear stick", () => {
    // Half stick must produce clearly less than half output.
    expect(shapeAxis(0.5, DEADZONE, EXPO)).toBeLessThan(0.5);
  });

  it("never leaves the valid range", () => {
    for (let value = -2; value <= 2; value += 0.05) {
      const shaped = shapeAxis(value, DEADZONE, EXPO);
      expect(shaped).toBeGreaterThanOrEqual(-1);
      expect(shaped).toBeLessThanOrEqual(1);
    }
  });

  it("fails safe on a non-finite input", () => {
    expect(shapeAxis(Number.NaN)).toBe(0);
    expect(shapeAxis(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe("shapeCommand", () => {
  it("shapes both axes independently", () => {
    const shaped = shapeCommand({ linear: 1, angular: 0.02 }, DEADZONE, EXPO);

    expect(shaped.linear).toBeCloseTo(1, 6);
    expect(shaped.angular).toBe(0);
  });
});

describe("padCommand", () => {
  it("points the same way as the keyboard: up forward, left to the left", () => {
    // Uses the canonical PAD_DIRECTIONS by default, so the four names are fixed.
    expect(padCommand(["Forward"])).toEqual({ linear: 1, angular: 0 });
    expect(padCommand(["Back"])).toEqual({ linear: -1, angular: 0 });
    expect(padCommand(["Turn left"])).toEqual({ linear: 0, angular: 1 });
    expect(padCommand(["Turn right"])).toEqual({ linear: 0, angular: -1 });
  });

  it("exposes the four canonical directions", () => {
    expect(PAD_DIRECTIONS.map((direction) => direction.name)).toEqual([
      "Forward",
      "Back",
      "Turn left",
      "Turn right",
    ]);
  });

  it("sums simultaneous directions, giving diagonals", () => {
    expect(padCommand(["Forward", "Turn left"])).toEqual({ linear: 1, angular: 1 });
    expect(padCommand(["Back", "Turn right"])).toEqual({ linear: -1, angular: -1 });
  });

  it("returns idle when nothing is held", () => {
    expect(padCommand([])).toEqual({ linear: 0, angular: 0 });
  });

  it("ignores unknown directions", () => {
    expect(padCommand(["Nope", "Forward"])).toEqual({ linear: 1, angular: 0 });
  });
});

describe("KEY_DIRECTIONS", () => {
  it("maps arrows and WASD onto the same names the pad uses", () => {
    expect(KEY_DIRECTIONS["ArrowUp"]).toBe("Forward");
    expect(KEY_DIRECTIONS["w"]).toBe("Forward");
    expect(KEY_DIRECTIONS["ArrowDown"]).toBe("Back");
    expect(KEY_DIRECTIONS["a"]).toBe("Turn left");
    expect(KEY_DIRECTIONS["ArrowRight"]).toBe("Turn right");
  });

  it("turns every mapped key onto exactly the four pad directions", () => {
    const mapped = new Set(Object.values(KEY_DIRECTIONS));
    const canonical = new Set(PAD_DIRECTIONS.map((direction) => direction.name));
    expect(mapped).toEqual(canonical);
  });
});
