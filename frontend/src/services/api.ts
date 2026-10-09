/** Thin API client for the RoverCarBeto backend. */

import type {
  CameraStatus,
  DetectionSnapshot,
  FollowStatus,
  HealthResponse,
  ModelsReport,
  MotionCommand,
  PoseSnapshot,
  RoverStatus,
  TelemetrySnapshot,
} from "../types/rover";

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";

/** A hung request must never stall the polling loop forever. */
const REQUEST_TIMEOUT_MS = 5_000;

/**
 * Switching networks restarts the camera, and the first load of a network uploads
 * firmware to the sensor. This must not be confused with a hung request.
 */
const SWITCH_TIMEOUT_MS = 150_000;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function isTimeout(cause: unknown): boolean {
  return (
    typeof cause === "object" && cause !== null && (cause as { name?: unknown }).name === "TimeoutError"
  );
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
      ...init,
    });
  } catch (cause) {
    // Network-level failure: the backend is unreachable.
    const reason = isTimeout(cause)
      ? `timed out after ${REQUEST_TIMEOUT_MS} ms`
      : (cause as Error).message;
    throw new ApiError(0, `Backend unreachable: ${reason}`);
  }

  if (!response.ok) {
    throw new ApiError(response.status, await extractError(response));
  }

  return (await response.json()) as T;
}

async function extractError(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        return detail
          .map((item) =>
            typeof item === "object" && item !== null && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : JSON.stringify(item),
          )
          .join("; ");
      }
    }
  } catch {
    // Fall through to the generic message below.
  }
  return `HTTP error ${response.status}`;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  status: () => request<RoverStatus>("/rover/status"),
  telemetry: () => request<TelemetrySnapshot>("/telemetry"),
  cameraStatus: () => request<CameraStatus>("/camera/status"),
  detections: () => request<DetectionSnapshot>("/ai/detections"),
  pose: () => request<PoseSnapshot>("/ai/pose"),
  models: () => request<ModelsReport>("/ai/models"),
  switchModel: (id: string) =>
    request<ModelsReport>(
      "/ai/model",
      { method: "POST", body: JSON.stringify({ id }) },
      SWITCH_TIMEOUT_MS,
    ),
  behaviorStatus: () => request<FollowStatus>("/behavior/status"),
  setFollow: (enabled: boolean) =>
    request<FollowStatus>("/behavior/follow", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  move: (command: MotionCommand) =>
    request<RoverStatus>("/rover/move", {
      method: "POST",
      body: JSON.stringify(command),
    }),
  stop: () => request<RoverStatus>("/rover/stop", { method: "POST" }),
};
