import type { PoseSnapshot } from "../types/rover";

interface PoseOverlayProps {
  pose: PoseSnapshot;
  /** Pixel size of the video stream, used as the SVG coordinate system. */
  videoWidth: number;
  videoHeight: number;
}

/**
 * Draws the skeletons over the video.
 *
 * Same geometry as `DetectionOverlay`: the SVG uses the stream's own pixel size as
 * its coordinate system and `preserveAspectRatio="xMidYMid slice"`, which
 * transforms the drawing exactly like `object-fit: cover` transforms the video.
 *
 * The joint names and the skeleton come from the snapshot instead of being
 * hard-coded here, so this component cannot drift from the network.
 *
 * Nothing here is interactive, and nothing is recorded.
 */
export function PoseOverlay({ pose, videoWidth, videoHeight }: PoseOverlayProps) {
  const people = pose.people.filter((person) => person.keypoints.length > 0);
  if (people.length === 0) return null;

  // The viewBox is the video size, so radii are in video pixels: this scales with
  // the stream and keeps the dots about the same size on screen.
  const jointRadius = videoWidth / 180;

  return (
    <svg
      className="pose"
      viewBox={`0 0 ${videoWidth} ${videoHeight}`}
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      {people.map((person, index) => {
        const joints = new Map<number, { x: number; y: number }>();
        for (const joint of person.keypoints) {
          const position = pose.keypoint_names.indexOf(joint.name);
          if (position >= 0) {
            joints.set(position, { x: joint.x * videoWidth, y: joint.y * videoHeight });
          }
        }

        return (
          <g key={index}>
            {pose.skeleton.map(([start, end]) => {
              const from = joints.get(start);
              const to = joints.get(end);
              if (!from || !to) return null;
              return (
                <line
                  key={`${start}-${end}`}
                  className="pose__bone"
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                  vectorEffect="non-scaling-stroke"
                />
              );
            })}

            {person.keypoints.map((joint) => (
              <circle
                key={joint.name}
                className="pose__joint"
                cx={joint.x * videoWidth}
                cy={joint.y * videoHeight}
                r={jointRadius}
              />
            ))}

            <text className="pose__label" x={person.x_min * videoWidth} y={person.y_min * videoHeight - jointRadius}>
              {Math.round(person.confidence * 100)}%
            </text>
          </g>
        );
      })}
    </svg>
  );
}
