/**
 * Generated from the backend's OpenAPI document — do not edit by hand.
 * Regenerate with `npm run gen:api` whenever the backend API changes.
 */

export interface CameraStatus {
  mode: string;
  running: boolean;
  width: number;
  height: number;
  fps: number;
  stream_path: string;
  webrtc_port: number;
  restarts: number;
  model: string | null;
  last_error: string | null;
  timestamp: string;
}

export type ChargeState = "unknown" | "charging" | "discharging";

export type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

export interface Detection {
  label: string;
  confidence: number;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  track_id: number | null;
}

export interface DetectionSnapshot {
  available: boolean;
  model: string | null;
  labels_count: number;
  score_threshold: number;
  tracking: boolean;
  inference_ms: number | null;
  age_s: number | null;
  detections: Detection[];
  timestamp: string;
}

export interface FollowRequest {
  enabled: boolean;
}

export interface FollowStatus {
  enabled: boolean;
  target_label: string;
  min_confidence: number;
  target_height: number;
  max_linear: number;
  max_angular: number;
  min_linear: number;
  face_deadband: number;
  target_id: number | null;
  has_target: boolean;
  linear: number;
  angular: number;
  lost_s: number | null;
  timestamp: string;
}

export interface HTTPValidationError {
  detail: ValidationError[];
}

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  environment: string;
  rover_mode: string;
  camera_mode: string;
}

export interface Keypoint {
  name: string;
  x: number;
  y: number;
  confidence: number;
}

export interface ModelDescription {
  id: string;
  task: string;
  description: string;
}

export interface ModelSwitchRequest {
  id: string;
}

export interface ModelsReport {
  active: string | null;
  models: ModelDescription[];
}

export interface MotionRequest {
  linear: number;
  angular: number;
}

export interface Pose {
  x: number;
  y: number;
  heading: number;
}

export interface PosePerson {
  confidence: number;
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  keypoints: Keypoint[];
}

export interface PoseSnapshot {
  available: boolean;
  model: string | null;
  keypoint_names: string[];
  skeleton: number[][];
  person_threshold: number;
  keypoint_threshold: number;
  inference_ms: number | null;
  age_s: number | null;
  people: PosePerson[];
  timestamp: string;
}

export interface RoverStatus {
  connection: ConnectionState;
  moving: boolean;
  linear: number;
  angular: number;
  pose: Pose;
  battery_voltage: number | null;
  battery_percentage: number | null;
  battery_current_ma: number | null;
  battery_charge_state: ChargeState;
  latency_ms: number | null;
  last_command_age_s: number | null;
  timestamp: string;
}

export interface TelemetrySnapshot {
  timestamp: string;
  rover: RoverStatus;
  cpu_temperature_c: number | null;
  ai_inference_ms: number | null;
  detections: number | null;
}

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input: unknown;
  ctx: Record<string, never>;
}
