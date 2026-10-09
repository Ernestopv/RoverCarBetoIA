/**
 * Which AI network the sensor is running, and how to change it.
 *
 * The sensor holds one network at a time, so switching restarts the camera and
 * the video drops while it comes back — that is inherent, not a bug, and the
 * response only resolves when the new network is actually live.
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../services/api";
import type { ModelsReport } from "../types/rover";

export interface CameraModels {
  report: ModelsReport | null;
  /** Which network is loaded, as an id from the report. */
  active: string | null;
  /** The network a switch is heading to, so the interface can name it. */
  target: string | null;
  switching: boolean;
  error: string | null;
  /** Load another network. Resolves when the camera is back with it. */
  switchTo: (id: string) => Promise<void>;
}

export function useCameraModels(): CameraModels {
  const [report, setReport] = useState<ModelsReport | null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .models()
      .then((next) => {
        if (!cancelled) setReport(next);
      })
      .catch(() => {
        // Unavailable: the panel simply stays hidden.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const switchTo = useCallback(async (id: string) => {
    setSwitching(true);
    setTarget(id);
    setError(null);
    try {
      const next = await api.switchModel(id);
      setReport(next);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSwitching(false);
      setTarget(null);
    }
  }, []);

  return { report, active: report?.active ?? null, target, switching, error, switchTo };
}