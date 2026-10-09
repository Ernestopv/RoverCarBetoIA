import { useEffect, useRef } from "react";

interface SimulatedFeedProps {
  /** Applied forward speed (-1..1); drives the ground scroll. */
  linear: number;
  /** Applied turn rate (-1..1); shifts the vanishing point. */
  angular: number;
}

/**
 * Synthetic view used **only** as a fallback when there is no live stream.
 *
 * It is drawn locally in the browser: nothing is captured, sent or persisted.
 * It must never be mistakeable for the real camera, so `VideoPanel` overlays a
 * "NO LIVE VIDEO" banner on top whenever this is what is on screen — a rover is
 * driven by camera, and a fake feed that looks real is worse than a black panel.
 *
 * The scene reacts to the rover state so the operator still gets a sense of
 * motion while the camera is down. The motion values are real; the image is not.
 */
export function SimulatedFeed({ linear, angular }: SimulatedFeedProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const speedRef = useRef(0);
  const turnRef = useRef(0);

  // Refs must not be written during render: sync them from an effect instead.
  useEffect(() => {
    speedRef.current = Math.abs(linear);
    turnRef.current = angular;
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let animationId = 0;
    let offset = 0;

    const render = () => {
      // Match the backing store to the displayed size so the scene is crisp at
      // any frame shape and on any device pixel ratio.
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const targetWidth = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const targetHeight = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
        canvas.width = targetWidth;
        canvas.height = targetHeight;
      }

      const { width, height } = canvas;
      const horizon = height * 0.44;
      const speed = speedRef.current;
      const vanishX = width / 2 - turnRef.current * width * 0.07;

      const sky = context.createLinearGradient(0, 0, 0, horizon);
      sky.addColorStop(0, "#0a1417");
      sky.addColorStop(1, "#122528");
      context.fillStyle = sky;
      context.fillRect(0, 0, width, horizon);

      const ground = context.createLinearGradient(0, horizon, 0, height);
      ground.addColorStop(0, "#122427");
      ground.addColorStop(1, "#0a1619");
      context.fillStyle = ground;
      context.fillRect(0, horizon, width, height - horizon);

      context.lineWidth = 1;
      context.strokeStyle = "rgba(144, 168, 163, 0.16)";
      for (let i = -7; i <= 7; i += 1) {
        context.beginPath();
        context.moveTo(vanishX + i * 16, horizon);
        context.lineTo(vanishX + i * (width / 5), height);
        context.stroke();
      }

      const step = 46;
      offset = (offset + 0.4 + speed * 5.5) % step;
      strokeGroundLines(context, width, height, horizon, offset, step);

      context.strokeStyle = "rgba(242, 118, 46, 0.4)";
      context.beginPath();
      context.moveTo(0, horizon);
      context.lineTo(width, horizon);
      context.stroke();

      const vignette = context.createRadialGradient(
        width / 2,
        height / 2,
        height * 0.25,
        width / 2,
        height / 2,
        height * 1.05,
      );
      vignette.addColorStop(0, "rgba(0, 0, 0, 0)");
      vignette.addColorStop(1, "rgba(0, 0, 0, 0.55)");
      context.fillStyle = vignette;
      context.fillRect(0, 0, width, height);

      animationId = window.requestAnimationFrame(render);
    };

    animationId = window.requestAnimationFrame(render);
    return () => window.cancelAnimationFrame(animationId);
  }, []);

  return (
    <div className="sim-feed">
      <canvas ref={canvasRef} className="sim-feed__canvas" aria-hidden="true" />
    </div>
  );
}

function strokeGroundLines(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  horizon: number,
  offset: number,
  step: number,
): void {
  const count = 16;
  context.strokeStyle = "rgba(144, 168, 163, 0.14)";
  for (let i = 0; i < count; i += 1) {
    const progress = (i * step + offset) / (count * step);
    const y = horizon + progress * progress * (height - horizon);
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  }
}
