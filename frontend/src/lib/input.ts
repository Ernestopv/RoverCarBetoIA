/**
 * Joystick shaping: deadzone plus an RC-style expo curve.
 *
 * Two problems this solves, both about *precision*:
 *
 * 1. **Deadzone.** A hand on a virtual stick always wobbles a little, so
 *    "centred" rarely is exactly zero. Without a deadzone the rover creeps and
 *    drifts when the operator means to go straight.
 * 2. **Expo.** A linear stick is far too twitchy near the centre and wastes most
 *    of its travel there. An expo curve gives fine control around the middle
 *    while still reaching full authority at the edges (`out(1) === 1`).
 *
 * Both values are deliberately tunable: see `STICK_DEADZONE` and `STICK_EXPO`.
 * The command that reaches the backend is the shaped one, so the axis readout on
 * screen shows exactly what the rover is being asked to do.
 */

import type { MotionCommand } from "../types/rover";

/** Stick travel below this magnitude is treated as centred. */
export const STICK_DEADZONE = 0.06;

/** 0 = linear response, 1 = fully cubic (finest near the centre). */
export const STICK_EXPO = 0.35;

/**
 * Shape one axis.
 *
 * The deadzone is not simply cut: the remaining travel is rescaled back to the
 * full `0..1` range, so the stick still reaches maximum at the edge and there is
 * no jump when leaving the deadzone.
 */
export function shapeAxis(
  value: number,
  deadzone: number = STICK_DEADZONE,
  expo: number = STICK_EXPO,
): number {
  if (!Number.isFinite(value)) return 0;

  const magnitude = Math.abs(value);
  if (magnitude <= deadzone) return 0;

  const rescaled = Math.min(1, (magnitude - deadzone) / (1 - deadzone));
  const curved = (1 - expo) * rescaled + expo * rescaled ** 3;

  return Math.sign(value) * curved;
}

/** Shape both axes of a command. */
export function shapeCommand(
  command: MotionCommand,
  deadzone: number = STICK_DEADZONE,
  expo: number = STICK_EXPO,
): MotionCommand {
  return {
    linear: shapeAxis(command.linear, deadzone, expo),
    angular: shapeAxis(command.angular, deadzone, expo),
  };
}

// --- D-pad and keyboard, one vocabulary ------------------------------------

export interface PadDirection {
  name: string;
  linear: number;
  angular: number;
}

/** The four directions, signed the same way everywhere: up is +linear, left is +angular. */
export const PAD_DIRECTIONS: readonly PadDirection[] = [
  { name: "Forward", linear: 1, angular: 0 },
  { name: "Back", linear: -1, angular: 0 },
  { name: "Turn left", linear: 0, angular: 1 },
  { name: "Turn right", linear: 0, angular: -1 },
];

/** `KeyboardEvent.key` → direction name, so the keyboard drives exactly like the pad. */
export const KEY_DIRECTIONS: Readonly<Record<string, string>> = {
  ArrowUp: "Forward",
  w: "Forward",
  W: "Forward",
  ArrowDown: "Back",
  s: "Back",
  S: "Back",
  ArrowLeft: "Turn left",
  a: "Turn left",
  A: "Turn left",
  ArrowRight: "Turn right",
  d: "Turn right",
  D: "Turn right",
};

/**
 * Combine the held directions into one command.
 *
 * Holding several at once sums them, which gives diagonals for free. The default
 * directions are the shared `PAD_DIRECTIONS`, so the pad, the keyboard and the
 * tests all reason about the same names.
 */
export function padCommand(
  held: Iterable<string>,
  directions: readonly PadDirection[] = PAD_DIRECTIONS,
): MotionCommand {
  let linear = 0;
  let angular = 0;
  for (const name of held) {
    const direction = directions.find((item) => item.name === name);
    if (direction) {
      linear += direction.linear;
      angular += direction.angular;
    }
  }
  return { linear, angular };
}
