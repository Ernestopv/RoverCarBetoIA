import { useState } from "react";

import { DetectionOverlay } from "./DetectionOverlay";
import { PoseOverlay } from "./PoseOverlay";
import { ReloadVeil } from "./ReloadVeil";
import { SimulatedFeed } from "./SimulatedFeed";
import type { LiveVideo, StreamState } from "../hooks/useLiveVideo";
import type { DetectionSnapshot, PoseSnapshot } from "../types/rover";

interface VideoPanelProps {
  /** Applied forward speed (-1..1). */
  linear: number;
  /** Applied turn rate (-1..1). */
  angular: number;
  battery: number | null;
  heading: number;
  stream: LiveVideo;
  detections: DetectionSnapshot | null;
  pose: PoseSnapshot | null;
  /** Whether the sensor is reloading another network. */
  reloading: boolean;
  /** Short name of the network being loaded, for the reload overlay. */
  reloadingTarget: string | null;
}

type ViewMode = "live" | "sim";

const STATE_TITLES: Record<Exclude<StreamState, "live">, string> = {
  idle: "Waiting for the camera",
  connecting: "Connecting to the camera",
  error: "The stream is unavailable",
};

/**
 * Camera panel.
 *
 * Two sources, because they answer different questions:
 *
 * - **Live**: the real pipeline (WebRTC/WHEP from MediaMTX). This is what the
 *   hardware will feed. The test signal it carries is static.
 * - **Sim**: a synthetic scene drawn in the browser that reacts to the rover
 *   state, so the operator gets immediate visual feedback while driving. The
 *   motion values are real; the image is not, and it is labelled as such.
 *
 * In `simulator` mode the panel opens in **Sim** (there is no camera to look at
 * yet); with real hardware it opens in **Live**.
 *
 * Nothing here is captured, uploaded or persisted.
 */
export function VideoPanel({
  linear,
  angular,
  battery,
  heading,
  stream,
  detections,
  pose,
  reloading,
  reloadingTarget,
}: VideoPanelProps) {
  const { videoRef, state, error, camera, whepUrl, reconnect } = stream;

  // `null` means "follow the camera mode" until the operator chooses explicitly.
  const [chosenView, setChosenView] = useState<ViewMode | null>(null);
  const view: ViewMode = chosenView ?? (camera?.mode === "simulator" ? "sim" : "live");

  const liveConnected = state === "live";
  // Show the synthetic scene either because it was asked for, or because live
  // was asked for and there is no picture.
  const showSimulation = view === "sim" || !liveConnected;
  // The sensor holds one network at a time, so only one of these has anything to
  // say. Both are drawn if they do, and neither is drawn over the simulation:
  // they come from the camera.
  const showAnalysis = view === "live" && liveConnected;
  const showDetections = showAnalysis && detections !== null;
  const showPose = showAnalysis && pose !== null;
  // The sensor reloading another network: the picture is gone for real, so it
  // gets the reload veil instead of the generic "no video" banner.
  const showReload = reloading && view === "live";

  return (
    <div className="view">
      {/* Always mounted: the hook attaches the WebRTC track to this element. */}
      <video
        ref={videoRef}
        className="view__video"
        autoPlay
        muted
        playsInline
        aria-label="Live camera feed"
      />

      {showSimulation && <SimulatedFeed linear={linear} angular={angular} />}

      {showDetections && (
        <DetectionOverlay
          detections={detections.detections}
          videoWidth={camera?.width ?? 1280}
          videoHeight={camera?.height ?? 720}
        />
      )}

      {showPose && (
        <PoseOverlay
          pose={pose}
          videoWidth={camera?.width ?? 1280}
          videoHeight={camera?.height ?? 720}
        />
      )}

      {showReload && <ReloadVeil target={reloadingTarget} />}

      <span className="view__badge">{view === "sim" ? "Simulated view" : "Live stream"}</span>

      <div className="view__modes" role="group" aria-label="Video source">
        <button
          type="button"
          className="view__mode"
          aria-pressed={view === "live"}
          onClick={() => setChosenView("live")}
        >
          Live
        </button>
        <button
          type="button"
          className="view__mode"
          aria-pressed={view === "sim"}
          onClick={() => setChosenView("sim")}
        >
          Sim
        </button>
      </div>

      {/* Only when live was requested and there is nothing to show. Sim view is
          not an error: it is a labelled simulation. */}
      {view === "live" && !liveConnected && !reloading && (
        <div className="view__status" role="status">
          <strong className="view__watermark">NO LIVE VIDEO</strong>
          <span className="view__status-title">{STATE_TITLES[state]}</span>
          {error && <span className="view__status-detail">{error}</span>}
          {whepUrl && <code className="view__status-url">{whepUrl}</code>}
          <button type="button" className="view__retry" onClick={reconnect}>
            Retry now
          </button>
        </div>
      )}

      <div className="view__osd">
        <div className="osd">
          <OsdItem label="Forward" value={linear.toFixed(2)} live={linear !== 0} />
          <OsdItem label="Turn" value={angular.toFixed(2)} live={angular !== 0} />
        </div>
        <div className="osd">
          <OsdItem label="Battery" value={battery === null ? "—" : `${battery.toFixed(0)}%`} />
          <OsdItem label="Heading" value={`${Math.round(((heading % 360) + 360) % 360)}°`} />
        </div>
      </div>
    </div>
  );
}

function OsdItem({ label, value, live = false }: { label: string; value: string; live?: boolean }) {
  return (
    <div className="osd__item">
      <span className="osd__label">{label}</span>
      <span className={`osd__value${live ? " osd__value--live" : ""}`}>{value}</span>
    </div>
  );
}
