/**
 * Public API types, re-exported from the generated file.
 *
 * `api.ts` is generated from the backend's OpenAPI (`npm run gen:api`) — do not
 * edit it by hand. These re-exports keep the names the components already use,
 * so the drift risk lives in `api.ts`, where a stale file fails the build.
 *
 * The one exception is `AiStreamMessage`: the backend sends it only over the
 * WebSocket, and WebSocket payloads are not part of the OpenAPI document, so it
 * is composed here from the generated snapshots.
 */
export type {
  CameraStatus,
  ConnectionState,
  Detection,
  DetectionSnapshot,
  FollowRequest,
  FollowStatus,
  HealthResponse,
  Keypoint,
  ModelDescription,
  ModelsReport,
  MotionRequest,
  Pose,
  PosePerson,
  PoseSnapshot,
  RoverStatus,
  TelemetrySnapshot,
} from "./api";

// Local imports so the aliases and the composed message below can use the names.
import type { DetectionSnapshot, MotionRequest, PoseSnapshot } from "./api";

/** The move payload is what the API calls `MotionRequest`. */
export type MotionCommand = MotionRequest;

/** One message from the AI stream (`app/api/routes/ai.py::stream`). */
export interface AiStreamMessage {
  detections: DetectionSnapshot;
  pose: PoseSnapshot;
}