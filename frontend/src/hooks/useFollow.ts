/**
 * The person-following behaviour (Phase 7).
 *
 * Off by default and enabled by the operator. The status is polled so the panel
 * can show whether a person is being followed and how the rover is moving; the
 * backend owns every safety decision (it never reverses and stops on target loss).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../services/api";
import type { FollowStatus } from "../types/rover";

const POLL_MS = 1_000;

export interface Follow {
  status: FollowStatus | null;
  error: string | null;
  /** A toggle request is in flight. */
  pending: boolean;
  setEnabled: (enabled: boolean) => Promise<void>;
}

export function useFollow(): Follow {
  const [status, setStatus] = useState<FollowStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const load = () => {
      api
        .behaviorStatus()
        .then((next) => {
          if (mounted.current) setStatus(next);
        })
        .catch(() => {
          // Keep the last known status: a poll blip must not hide the control.
        });
    };
    load();
    const timer = window.setInterval(load, POLL_MS);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, []);

  const setEnabled = useCallback(async (enabled: boolean) => {
    setPending(true);
    setError(null);
    try {
      const next = await api.setFollow(enabled);
      setStatus(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPending(false);
    }
  }, []);

  return { status, error, pending, setEnabled };
}
