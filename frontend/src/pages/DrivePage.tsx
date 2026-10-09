import { useCallback, useEffect, useRef, useState } from "react";

import { ArrowPad } from "../components/ArrowPad";
import { AxesReadout } from "../components/AxesReadout";
import { ConnectionStatus } from "../components/ConnectionStatus";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { FollowToggle } from "../components/FollowToggle";
import { Joystick } from "../components/Joystick";
import { ModelSwitcher } from "../components/ModelSwitcher";
import { TelemetryPanel } from "../components/TelemetryPanel";
import { ThrottleSlider } from "../components/ThrottleSlider";
import { VideoPanel } from "../components/VideoPanel";
import { useAiStream } from "../hooks/useAiStream";
import { useCameraModels } from "../hooks/useCameraModels";
import { useFollow } from "../hooks/useFollow";
import { useKeyboardControls } from "../hooks/useKeyboardControls";
import { useLiveVideo } from "../hooks/useLiveVideo";
import { useRover } from "../hooks/useRover";
import { useVideoAlive } from "../hooks/useVideoAlive";
import { shortModelName } from "../lib/models";
import type { MotionCommand } from "../types/rover";

const MODE_LABELS: Record<string, string> = {
  simulator: "Simulator",
  hardware: "Hardware",
};

export function DrivePage() {
  const rover = useRover();
  const stream = useLiveVideo();
  const models = useCameraModels();
  const follow = useFollow();
  const videoAlive = useVideoAlive(stream.videoRef);
  const { detections, pose } = useAiStream();
  // Which drive control is showing. `null` is not needed here as it is in the
  // video panel: either control drives the same rover, the choice is cosmetic.
  const [driveControl, setDriveControl] = useState<"stick" | "arrows">("stick");
  // Which keyboard directions are held, so the on-screen arrows light up in step.
  const heldKeys = useKeyboardControls(rover.move, rover.stop);

  // The reload overlay must cover the whole camera restart: not just while the
  // switch request is in flight, but until the picture is moving again on
  // screen. The camera restarts in under a second, the publish returns a few
  // seconds later, and the browser takes a moment more to show frames.
  const [justSwitched, setJustSwitched] = useState(false);
  const previousSwitching = useRef(models.switching);
  useEffect(() => {
    if (previousSwitching.current && !models.switching) setJustSwitched(true);
    previousSwitching.current = models.switching;
  }, [models.switching]);

  useEffect(() => {
    if (justSwitched && videoAlive) setJustSwitched(false);
  }, [justSwitched, videoAlive]);

  // If the video never returns, fall back to the regular "no video" banner
  // (which has a manual retry) instead of showing the overlay forever.
  useEffect(() => {
    if (!justSwitched) return;
    const timer = window.setTimeout(() => setJustSwitched(false), 45_000);
    return () => window.clearTimeout(timer);
  }, [justSwitched]);

  const reloading = models.switching || (justSwitched && !videoAlive);
  const reloadingTarget = models.switching
    ? shortModelName(models.target)
    : shortModelName(models.active);

  const chooseControl = useCallback(
    (control: "stick" | "arrows") => {
      setDriveControl(control);
      // Changing the control unmounts whichever is engaged, so its own release
      // will never fire. Stop explicitly or the command loop keeps re-sending
      // whatever is still held.
      rover.stop();
    },
    [rover.stop],
  );

  const handleCommand = useCallback(
    (command: MotionCommand) => rover.move(command.linear, command.angular),
    [rover.move],
  );

  const { status, telemetry, error, mode, online, command, throttle } = rover;
  const modeLabel = mode === null ? null : (MODE_LABELS[mode] ?? mode);
  // The loaded network, shown beside the heading and the inference gauge.
  const modelLabel = shortModelName(models.active);

  return (
    <div className="app">
      <header className="rail">
        <div className="rail__brand">
          <span className="brand__name">RoverCarBeto</span>
          {modeLabel && <span className="tag">{modeLabel}</span>}
          {modelLabel && <span className="tag tag--model">{modelLabel}</span>}
        </div>
        <ConnectionStatus
          online={online}
          connection={status?.connection ?? null}
          latencyMs={status?.latency_ms ?? null}
        />
      </header>

      {error && (
        <div className="alert" role="alert">
          <strong className="alert__title">Can&apos;t reach the rover service</strong>
          <span className="alert__detail">{error}</span>
          <span className="alert__hint">
            Retrying automatically. Check that the backend is running.
          </span>
        </div>
      )}

      {/* Each panel is isolated: a failure in the camera or the readouts must
          never take the drive controls with it. */}
      <main className="console">
        <section className="panel panel--view" aria-label="Camera view">
          <ErrorBoundary label="Camera">
            <VideoPanel
              linear={status?.linear ?? 0}
              angular={status?.angular ?? 0}
              battery={telemetry?.rover.battery_percentage ?? null}
              heading={((status?.pose.heading ?? 0) * 180) / Math.PI}
              stream={stream}
              detections={detections}
              pose={pose}
              reloading={reloading}
              reloadingTarget={reloadingTarget}
            />
          </ErrorBoundary>
        </section>

        <section className="panel panel--drive" aria-label="Drive controls">
          <h2 className="panel__title">Drive</h2>

          {/* Two ways to drive, one speed. Everything below the buttons is shared,
              including the throttle, so either control respects it. */}
          <div className="drive__modes" role="group" aria-label="Drive control">
            <button
              type="button"
              className="drive__mode"
              aria-pressed={driveControl === "stick"}
              onClick={() => chooseControl("stick")}
            >
              Joystick
            </button>
            <button
              type="button"
              className="drive__mode"
              aria-pressed={driveControl === "arrows"}
              onClick={() => chooseControl("arrows")}
            >
              Arrows
            </button>
          </div>

          <ErrorBoundary label="Drive controls">
            {driveControl === "arrows" ? (
              <ArrowPad
                onCommand={handleCommand}
                onRelease={rover.stop}
                disabled={!online}
                keyboardHeld={heldKeys}
              />
            ) : (
              <Joystick onChange={handleCommand} onRelease={rover.stop} disabled={!online} />
            )}
            <ThrottleSlider value={throttle} onChange={rover.setThrottle} />
            <AxesReadout command={command} />
            <p className="hint">Arrow keys or WASD to drive. Space stops the rover.</p>
          </ErrorBoundary>
        </section>

        <section className="panel panel--status" aria-label="Rover status">
          <h2 className="panel__title">Status</h2>
          <ErrorBoundary label="Status readouts">
            <TelemetryPanel telemetry={telemetry} aiModel={modelLabel} />
            <ModelSwitcher models={models} />
            <FollowToggle follow={follow} />
          </ErrorBoundary>
        </section>
      </main>

      <footer className="foot">
        Speed limits and the watchdog live in the backend safety layer.
      </footer>
    </div>
  );
}
