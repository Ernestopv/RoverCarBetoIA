/** Pure motion helpers shared by the control UI. */

import type { MotionCommand } from "../types/rover";

export const IDLE_COMMAND: MotionCommand = { linear: 0, angular: 0 };

/** True when a command asks for no motion at all. */
export function isIdleCommand(command: MotionCommand): boolean {
  return command.linear === 0 && command.angular === 0;
}

/**
 * Clamp a throttle setting into the valid `0..1` range.
 *
 * A non-finite value fails safe to `0` (no motion) rather than to full speed:
 * the throttle may only ever restrict a command, never amplify it.
 */
export function clampThrottle(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

/**
 * Scale a requested command by the throttle limit.
 *
 * The result can never exceed the requested command, so the backend safety
 * layer remains the single authority on the real maximum speed.
 */
export function applyThrottle(command: MotionCommand, throttle: number): MotionCommand {
  const scale = clampThrottle(throttle);
  return {
    linear: command.linear * scale,
    angular: command.angular * scale,
  };
}
