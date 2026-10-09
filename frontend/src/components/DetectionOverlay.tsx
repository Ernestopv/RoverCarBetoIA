import type { Detection } from "../types/rover";

interface DetectionOverlayProps {
  detections: Detection[];
  /** Pixel size of the video stream, used as the SVG coordinate system. */
  videoWidth: number;
  videoHeight: number;
}

/**
 * Draws the detector's boxes over the video.
 *
 * The SVG uses the stream's own pixel size as its coordinate system and
 * `preserveAspectRatio="xMidYMid slice"`, which transforms the drawing exactly
 * like `object-fit: cover` transforms the video. That is what keeps the boxes
 * glued to the picture instead of drifting when the frame is cropped.
 *
 * `vector-effect` keeps the outlines a constant screen width whatever the scale.
 * Nothing here is interactive, and nothing is recorded.
 */
export function DetectionOverlay({ detections, videoWidth, videoHeight }: DetectionOverlayProps) {
  if (detections.length === 0) return null;

  return (
    <svg
      className="detections"
      viewBox={`0 0 ${videoWidth} ${videoHeight}`}
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      {detections.map((detection, index) => {
        const x = detection.x_min * videoWidth;
        const y = detection.y_min * videoHeight;
        const width = (detection.x_max - detection.x_min) * videoWidth;
        const height = (detection.y_max - detection.y_min) * videoHeight;

        // Track id when we have one; otherwise the label plus position, so a
        // re-render does not remount every box.
        const key = detection.track_id ?? `${detection.label}-${index}`;

        return (
          <g key={key}>
            <rect
              className="detections__box"
              x={x}
              y={y}
              width={width}
              height={height}
              vectorEffect="non-scaling-stroke"
            />
            <text className="detections__label" x={x} y={y - 6}>
              {detection.track_id !== null ? `#${detection.track_id} ` : ""}
              {detection.label} {Math.round(detection.confidence * 100)}%
            </text>
          </g>
        );
      })}
    </svg>
  );
}
