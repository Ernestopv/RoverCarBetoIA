/**
 * Single source of truth for the rover state in the UI.
 *
 * Responsibilities are kept deliberately narrow:
 * - poll `/telemetry` so status, battery and link health stay fresh;
 * - re-send the active command at a fixed rate so the backend watchdog stays
 *   armed while the user keeps driving;
 * - apply the throttle limit to every command source (stick and keyboard).
 *
 * State transitions live in the pure `roverReducer`; this hook only performs
 * side effects.
 *
 * The throttle is a *client-side* limit only: it can never raise the command
 * above the limits enforced by the backend safety layer.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import {
  IDLE_COMMAND,
  applyThrottle as scaleCommand,
  clampThrottle,
  isIdleCommand,
} from "../lib/motion";
import { initialRoverState, roverReducer } from "../lib/roverState";
import { ApiError, api } from "../services/api";
import type { MotionCommand, RoverStatus, TelemetrySnapshot } from "../types/rover";

const POLL_INTERVAL_MS = 1_000;
/** Often enough to keep the backend watchdog armed while the stick is held. */
const COMMAND_INTERVAL_MS = 150;

export interface RoverController {
  telemetry: TelemetrySnapshot | null;
  status: RoverStatus | null;
  /** Effective command (already scaled by the throttle) that is being sent. */
  command: MotionCommand;
  /** Throttle limit in the `0..1` range. */
  throttle: number;
  online: boolean;
  /** Rover mode reported by the backend: "simulator" or "hardware". */
  mode: string | null;
  error: string | null;
  move: (linear: number, angular: number) => void;
  setThrottle: (value: number) => void;
  stop: () => void;
}

function messageOf(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : String(cause);
}

export function useRover(): RoverController {
  const [state, dispatch] = useReducer(roverReducer, initialRoverState);
  const [command, setCommand] = useState<MotionCommand>(IDLE_COMMAND);
  const [throttle, setThrottleState] = useState(1);

  /** Command as asked by the operator, before the throttle is applied. */
  const rawRef = useRef<MotionCommand>(IDLE_COMMAND);
  const throttleRef = useRef(1);
  /** Guards against queueing motion commands when the link is slow. */
  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);

  // Latched so a promise that resolves after unmount cannot update state.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fail = useCallback((cause: unknown) => {
    if (mountedRef.current) dispatch({ type: "failure", message: messageOf(cause) });
  }, []);

  const applyThrottle = useCallback(
    (raw: MotionCommand): MotionCommand => scaleCommand(raw, throttleRef.current),
    [],
  );

  const releaseCommand = useCallback(() => {
    rawRef.current = IDLE_COMMAND;
    setCommand(IDLE_COMMAND);
  }, []);

  // --- Which rover mode is the backend running? (once) ----------------------
  useEffect(() => {
    let cancelled = false;

    api
      .health()
      .then((health) => {
        if (!cancelled) dispatch({ type: "mode", mode: health.rover_mode });
      })
      .catch(() => {
        // Mode is a nicety: the link chip already reports connectivity.
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // --- Poll telemetry: status, battery and link health ----------------------
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const snapshot = await api.telemetry();
        if (!cancelled) dispatch({ type: "telemetry", snapshot });
      } catch (cause) {
        if (!cancelled) dispatch({ type: "failure", message: messageOf(cause) });
      } finally {
        // Reschedule from a settled request, so a slow link never stacks polls.
        if (!cancelled) timer = window.setTimeout(() => void poll(), POLL_INTERVAL_MS);
      }
    };

    void poll();

    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  // --- Command loop: keeps the backend watchdog fed -------------------------
  useEffect(() => {
    const id = window.setInterval(() => {
      const current = applyThrottle(rawRef.current);
      if (isIdleCommand(current)) return;
      if (inFlightRef.current) return;

      inFlightRef.current = true;
      api
        .move(current)
        .then((status) => {
          if (mountedRef.current) dispatch({ type: "status", status });
        })
        .catch((cause) => {
          if (!mountedRef.current) return;
          // Safety first: never keep retrying a command that cannot be delivered.
          fail(cause);
          releaseCommand();
        })
        .finally(() => {
          inFlightRef.current = false;
        });
    }, COMMAND_INTERVAL_MS);

    return () => window.clearInterval(id);
  }, [applyThrottle, fail, releaseCommand]);

  const move = useCallback(
    (linear: number, angular: number) => {
      const raw: MotionCommand = { linear, angular };
      rawRef.current = raw;
      setCommand(applyThrottle(raw));
    },
    [applyThrottle],
  );

  const setThrottle = useCallback(
    (value: number) => {
      const clamped = clampThrottle(value);
      throttleRef.current = clamped;
      setThrottleState(clamped);
      // Update the readout now; the command loop re-sends it scaled.
      setCommand(applyThrottle(rawRef.current));
    },
    [applyThrottle],
  );

  const stop = useCallback(() => {
    releaseCommand();
    api
      .stop()
      .then((status) => {
        if (mountedRef.current) dispatch({ type: "status", status });
      })
      .catch(fail);
  }, [fail, releaseCommand]);

  return {
    telemetry: state.telemetry,
    status: state.status,
    command,
    throttle,
    online: state.online,
    mode: state.mode,
    error: state.error,
    move,
    setThrottle,
    stop,
  };
}
