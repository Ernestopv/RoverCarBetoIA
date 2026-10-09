/**
 * Connection state of the console, as a pure reducer.
 *
 * Keeping the transitions here (instead of scattered across effects) makes the
 * rules explicit and lets them be tested without React or a browser.
 */

import type { RoverStatus, TelemetrySnapshot } from "../types/rover";

/**
 * A single failed poll trips the "Can't reach the rover service" banner, but a
 * marginal Wi-Fi link stalls for a couple of seconds all the time. Requiring
 * several *consecutive* failures keeps the banner honest: a transient blip stays
 * invisible while a real outage still surfaces promptly. The threshold only
 * delays the *indication* — the command loop still aborts motion on the very
 * first delivery failure, so safety timing is untouched.
 */
export const FAILURE_BANNER_AFTER = 3;

export interface RoverState {
  /** Last telemetry snapshot, or `null` until the first successful poll. */
  telemetry: TelemetrySnapshot | null;
  /** Last known rover status (from a poll or from a command response). */
  status: RoverStatus | null;
  /** Whether the backend answered recently enough to drive; false only after
   *  `FAILURE_BANNER_AFTER` consecutive failures. */
  online: boolean;
  /** Rover mode reported by the backend: "simulator" or "hardware". */
  mode: string | null;
  /** Last failure message, cleared by any successful request. */
  error: string | null;
  /** Consecutive failures since the last success (capped at the threshold). */
  failureCount: number;
}

export type RoverAction =
  | { type: "telemetry"; snapshot: TelemetrySnapshot }
  | { type: "status"; status: RoverStatus }
  | { type: "mode"; mode: string }
  | { type: "failure"; message: string };

export const initialRoverState: RoverState = {
  telemetry: null,
  status: null,
  online: false,
  mode: null,
  error: null,
  failureCount: 0,
};

export function roverReducer(state: RoverState, action: RoverAction): RoverState {
  switch (action.type) {
    // A successful poll is the authoritative signal that the link is healthy.
    case "telemetry":
      return {
        ...state,
        telemetry: action.snapshot,
        status: action.snapshot.rover,
        online: true,
        error: null,
        failureCount: 0,
      };

    // A command response also proves the link is up, and lets the UI react
    // immediately instead of waiting for the next poll.
    case "status":
      return { ...state, status: action.status, online: true, error: null, failureCount: 0 };

    case "mode":
      return state.mode === action.mode ? state : { ...state, mode: action.mode };

    case "failure": {
      // Already showing this outage: nothing changes.
      if (state.online === false && state.error === action.message) return state;

      const failureCount = Math.min(state.failureCount + 1, FAILURE_BANNER_AFTER);
      if (failureCount < FAILURE_BANNER_AFTER) {
        return state.failureCount === failureCount
          ? state
          : { ...state, failureCount };
      }

      // Enough consecutive failures: signal the outage.
      return {
        ...state,
        online: false,
        error: action.message,
        failureCount,
      };
    }
  }
}
